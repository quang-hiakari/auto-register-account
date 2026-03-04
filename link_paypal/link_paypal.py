"""
Auto PayPal Account Linker
---------------------------
Reads activation links from a CSV file and links a PayPal account to each
site account using Playwright browser automation.

Flow per row:
  1. Open the activation link (from email) for the site account
  2. Navigate to the PayPal linking page
  3. Click the #link button  →  PayPal login opens in a new tab/popup
  4. Log in to PayPal with the configured credentials
  5. Click #consentButton to authorise the link

Usage:
    python link_paypal.py                  # uses paypal_config.yaml
    python link_paypal.py my_config.yaml
"""

import argparse
import asyncio
import csv
import logging
import os
import sys
import time
from datetime import datetime

import yaml
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

# Resolve all relative paths from this script's folder, regardless of cwd
_LAUNCH_CWD = os.getcwd()
os.chdir(os.path.dirname(os.path.abspath(__file__)))


# ─── Logging setup ────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(open(sys.stdout.fileno(), mode="w", encoding="utf-8", closefd=False)),
        logging.FileHandler("paypal_link.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)


# ─── Config & data loading ────────────────────────────────────────────────────

def load_config(path: str = "paypal_config.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_accounts(csv_path: str) -> list[dict]:
    with open(csv_path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


RESULT_FIELDS = ["Email", "ActivationLink", "status", "error", "timestamp"]

def init_results_file(path: str) -> None:
    """Write CSV header at the start of a run."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=RESULT_FIELDS).writeheader()


def append_result(result: dict, path: str) -> None:
    """Append a single result row immediately after each account is processed."""
    row = {k: result.get(k, "") for k in RESULT_FIELDS}
    with open(path, "a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=RESULT_FIELDS).writerow(row)


def write_accounts(csv_path: str, fields: list[str], accounts: list[dict]) -> None:
    """Rewrite the accounts CSV with remaining (unprocessed) rows."""
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(accounts)


# ─── Single account PayPal linking ───────────────────────────────────────────

async def link_paypal(context, config: dict, account: dict, index: int) -> dict:
    # Normalise keys: accept both snake_case (activation_link, email) and
    # PascalCase/camelCase (ActivationLink, Email) from the input CSV.
    email = account.get("Email") or account.get("email", "")
    activation_link = account.get("ActivationLink") or account.get("activation_link", "")
    result = {
        "Email": email,
        "ActivationLink": activation_link,
        "status": "pending",
        "error": "",
        "timestamp": datetime.now().isoformat(),
    }

    page = await context.new_page()

    try:
        paypal_cfg = config["paypal"]
        activation_link = activation_link.strip()

        # ── Step 1: Open activation link (auto-login) ────────────────────────
        if not activation_link:
            raise ValueError("No ActivationLink provided for this account")

        log.info(f"[{index}] Step 1 — Opening activation link")
        await page.goto(activation_link, wait_until="networkidle", timeout=60_000)
        log.info(f"[{index}]   Landed on: {page.url}")

        if "error=" in page.url and "login" in page.url:
            log.warning(f"[{index}] Activation link invalid/expired — skipping")
            result["status"] = "skipped"
            result["error"] = "Activation link expired or already used"
            return result

        await asyncio.sleep(2)

        # ── Step 2: Navigate to PayPal linking page ───────────────────────────
        paypal_link_url = config["paypal_link_url"]
        log.info(f"[{index}] Step 2 — Navigating to PayPal linking page")
        await page.goto(paypal_link_url, wait_until="networkidle", timeout=30_000)
        await asyncio.sleep(1)

        # ── Step 3: Click #link → redirects to PayPal in same tab ───────────
        log.info(f"[{index}] Step 3 — Checking PayPal link status")
        first_btn = await page.wait_for_selector(
            "#link, #unlink", state="visible", timeout=15_000
        )
        first_btn_id = await first_btn.get_attribute("id")

        if first_btn_id == "unlink":
            log.info(f"[{index}] PayPal already linked (#unlink found) — skipping")
            result["status"] = "skipped"
            result["error"] = "PayPal already linked"
            return result

        log.info(f"[{index}]   Clicking #link button")
        await page.click("#link")
        await page.wait_for_load_state("networkidle", timeout=30_000)
        log.info(f"[{index}]   PayPal page: {page.url}")

        # ── Step 4: Log in to PayPal (skip if session still active) ─────────
        # Wait for whichever appears first: consent page or login email field
        first_el = await page.wait_for_selector(
            "#consentButton, [name='login_email']", state="visible", timeout=20_000
        )
        first_id = await first_el.get_attribute("id") or await first_el.get_attribute("name")

        if first_id == "consentButton":
            log.info(f"[{index}] Step 4 — PayPal session active, skipping login")
        else:
            log.info(f"[{index}] Step 4 — Entering PayPal email")
            await page.fill("[name='login_email']", paypal_cfg["email"])
            await asyncio.sleep(0.5)

            # Check if password is already on screen (1-screen) or need to click Next (2-screen)
            next_el = await page.query_selector("#btnNext")
            if next_el and await next_el.is_visible():
                log.info(f"[{index}]   Clicking #btnNext")
                await page.click("#btnNext")
                await page.wait_for_selector("[name='login_password']", state="visible", timeout=30_000)
            else:
                log.info(f"[{index}]   Password on same screen, skipping #btnNext")
                await page.wait_for_selector("[name='login_password']", state="visible", timeout=10_000)

            log.info(f"[{index}]   Entering PayPal password")
            await page.fill("[name='login_password']", paypal_cfg["password"])
            await asyncio.sleep(0.5)

            log.info(f"[{index}]   Clicking #btnLogin")
            await page.click("#btnLogin")
            await asyncio.sleep(3)

        # ── Step 5: Click #consentButton ─────────────────────────────────────
        log.info(f"[{index}] Step 5 — Clicking #consentButton")
        await page.wait_for_selector("#consentButton", state="visible", timeout=20_000)
        await page.click("#consentButton")
        log.info(f"[{index}] Consent given — waiting for redirect back to site")
        await asyncio.sleep(3)
        log.info(f"[{index}]   Final URL: {page.url}")

        # ── Verify success ────────────────────────────────────────────────────
        # Consent button was clicked without error → treat as success
        log.info(f"[{index}] PayPal linked successfully")
        result["status"] = "success"

    except Exception as exc:
        log.error(f"[{index}] Failed: {exc}")
        result["status"] = "failed"
        result["error"] = str(exc)

    finally:
        await page.close()

    return result


# ─── Main runner ─────────────────────────────────────────────────────────────

async def run(config_path: str = "paypal_config.yaml", limit: int = None) -> None:
    config = load_config(config_path)
    accounts = load_accounts(config["csv_file"])
    csv_file = config["csv_file"]
    csv_fields = list(accounts[0].keys()) if accounts else []

    process_count = min(limit, len(accounts)) if limit else len(accounts)
    log.info(f"Loaded {len(accounts)} account(s) from '{csv_file}'")
    if limit:
        log.info(f"Limit set — will process {process_count} account(s)")
    log.info(f"PayPal credentials: {config['paypal']['email']}")

    browser_name = config.get("browser", "chromium")
    headless = config.get("headless", False)
    slow_mo = config.get("slow_mo", 50)
    delay = config.get("delay_between_accounts", 3)

    results_file = config.get("results_file", "paypal_results.csv")
    init_results_file(results_file)

    success_count = 0

    async with async_playwright() as pw:
        launcher = getattr(pw, browser_name)
        browser = await launcher.launch(headless=headless, slow_mo=slow_mo)

        for i in range(process_count):
            account = accounts[0]  # always process the first remaining row

            # Fresh context per account — clears all cookies and session data
            context = await browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
            )

            result = await link_paypal(context, config, account, i + 1)
            await context.close()

            # Remove processed row from CSV immediately
            accounts.pop(0)
            write_accounts(csv_file, csv_fields, accounts)

            append_result(result, results_file)
            if result["status"] == "success":
                success_count += 1
            else:
                log.warning(f"[{i+1}] Error — Email: {result.get('Email', '')} | {result.get('error', '')}")

            if i < process_count - 1:
                log.info(f"Waiting {delay}s before next account…")
                await asyncio.sleep(delay)

        await browser.close()

    log.info("-" * 60)
    log.info(f"Done. {success_count}/{process_count} account(s) linked successfully.")
    log.info(f"Results saved -> {results_file}")
    log.info(f"Remaining in '{csv_file}': {len(accounts)} account(s)")


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Auto PayPal Account Linker")
    parser.add_argument("config", nargs="?", default=None, help="Config YAML path (default: paypal_config.yaml)")
    parser.add_argument("--limit", type=int, default=100, metavar="N", help="Max number of accounts to process (default: 100)")
    args = parser.parse_args()

    if args.config:
        cfg = args.config if os.path.isabs(args.config) else os.path.join(_LAUNCH_CWD, args.config)
    else:
        cfg = "paypal_config.yaml"   # relative to script dir (after chdir)

    asyncio.run(run(cfg, limit=args.limit))
