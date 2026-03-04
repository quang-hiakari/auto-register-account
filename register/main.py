"""
Auto Account Registration Tool
--------------------------------
Reads account data from a CSV file and registers each account on a website
using Playwright browser automation. All configuration is in config.yaml.

Usage:
    python main.py               # uses config.yaml by default
    python main.py my_config.yaml
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
        logging.FileHandler("register.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)


# ─── Config & data loading ────────────────────────────────────────────────────

def load_config(path: str = "config.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_accounts(csv_path: str) -> list[dict]:
    with open(csv_path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save_results(results: list[dict], path: str) -> None:
    if not results:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=results[0].keys())
        writer.writeheader()
        writer.writerows(results)


def write_accounts(csv_path: str, fields: list[str], accounts: list[dict]) -> None:
    """Rewrite the accounts CSV with remaining (unprocessed) rows."""
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(accounts)


# ─── Field filling ────────────────────────────────────────────────────────────

async def fill_field(page, field: dict, account: dict) -> None:
    column = field["column"]
    selector = field["selector"]
    field_type = field.get("type", "text")
    value = account.get(column, "")

    if value == "" or value is None:
        log.warning(f"  Column '{column}' is empty — skipping")
        return

    await page.wait_for_selector(selector, timeout=10_000)

    if field_type == "select":
        await page.select_option(selector, str(value))
    elif field_type == "checkbox":
        if str(value).lower() in ("true", "1", "yes", "on"):
            await page.check(selector)
        else:
            await page.uncheck(selector)
    else:
        await page.fill(selector, str(value))


# ─── Single account registration ─────────────────────────────────────────────

async def register_account(page, config: dict, account: dict, index: int) -> dict:
    result = {
        **account,
        "status": "pending",
        "error": "",
        "timestamp": datetime.now().isoformat(),
    }

    try:
        log.info(f"[{index}] Opening registration page")
        await page.goto(config["url"], wait_until="networkidle", timeout=30_000)

        # Accept cookie consent dialog if present
        cookie_selector = config.get("cookie_selector")
        if cookie_selector:
            try:
                await page.wait_for_selector(cookie_selector, timeout=5_000)
                await page.click(cookie_selector)
                log.info(f"[{index}] Cookie consent accepted")
                await asyncio.sleep(0.5)
            except PlaywrightTimeoutError:
                pass  # No cookie dialog — continue

        for field in config.get("fields", []):
            log.info(f"[{index}] Filling '{field['column']}'")
            await fill_field(page, field, account)
            await asyncio.sleep(config.get("field_delay", 0.3))

        log.info(f"[{index}] Submitting form")
        await page.click(config["submit_selector"])

        # ── Terms of Service step (if configured) ─────────────────────────
        terms = config.get("terms", {})
        if terms:
            tos_checkbox = terms.get("checkbox_selector")
            tos_submit = terms.get("submit_selector")
            try:
                await page.wait_for_selector(tos_submit, state="visible", timeout=8_000)
                # Checkbox is hidden — check it and fire change event via JavaScript
                await page.evaluate(
                    f'var cb = document.querySelector("{tos_checkbox}");'
                    f'cb.checked = true;'
                    f'cb.dispatchEvent(new Event("change", {{bubbles: true}}))'
                )
                log.info(f"[{index}] Terms of Service checkbox checked")
                await asyncio.sleep(0.5)
                try:
                    await page.click(tos_submit, timeout=5_000)
                    log.info(f"[{index}] Terms of Service submitted")
                except PlaywrightTimeoutError:
                    pass  # Change event already triggered submission
            except PlaywrightTimeoutError:
                log.warning(f"[{index}] Terms of Service dialog not found - skipping")

        # ── Success detection ──────────────────────────────────────────────
        success_cfg = config.get("success", {})
        success = False

        if url_fragment := success_cfg.get("url_contains"):
            try:
                await page.wait_for_url(f"**{url_fragment}**", timeout=10_000)
                success = True
            except PlaywrightTimeoutError:
                pass

        if not success and (sel := success_cfg.get("selector")):
            try:
                await page.wait_for_selector(sel, timeout=10_000)
                success = True
            except PlaywrightTimeoutError:
                pass

        if not success_cfg:
            # No success check configured → assume success after submit
            success = True

        if success:
            log.info(f"[{index}] Registration successful")
            result["status"] = "success"
        else:
            log.warning(f"[{index}] Submit completed but success could not be confirmed")
            result["status"] = "unconfirmed"

    except Exception as exc:
        log.error(f"[{index}] Registration failed: {exc}")
        result["status"] = "failed"
        result["error"] = str(exc)

        if config.get("screenshots_on_failure", True):
            scr_dir = config.get("screenshots_dir", "screenshots")
            os.makedirs(scr_dir, exist_ok=True)
            scr_path = os.path.join(scr_dir, f"failure_{index}_{int(time.time())}.png")
            try:
                await page.screenshot(path=scr_path)
                log.info(f"[{index}] Screenshot saved → {scr_path}")
            except Exception:
                pass

    return result


# ─── Main runner ─────────────────────────────────────────────────────────────

async def run(config_path: str = "config.yaml", limit: int = None) -> None:
    config = load_config(config_path)
    accounts = load_accounts(config["csv_file"])
    csv_file = config["csv_file"]
    csv_fields = list(accounts[0].keys()) if accounts else []

    process_count = min(limit, len(accounts)) if limit else len(accounts)
    log.info(f"Loaded {len(accounts)} account(s) from '{csv_file}'")
    if limit:
        log.info(f"Limit set — will process {process_count} account(s)")
    log.info(f"Target URL: {config['url']}")

    browser_name = config.get("browser", "chromium")
    headless = config.get("headless", False)
    slow_mo = config.get("slow_mo", 50)
    delay = config.get("delay_between_accounts", 3)

    results_file = config.get("results_file", "results.csv")
    results: list[dict] = []

    async with async_playwright() as pw:
        launcher = getattr(pw, browser_name)
        browser = await launcher.launch(headless=headless, slow_mo=slow_mo)
        context = await browser.new_context(
            # Mimic a regular desktop browser
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )

        for i in range(process_count):
            account = accounts[0]  # always process the first remaining row
            page = await context.new_page()
            result = await register_account(page, config, account, i + 1)
            results.append(result)
            await page.close()

            # Remove processed row from CSV immediately
            accounts.pop(0)
            write_accounts(csv_file, csv_fields, accounts)

            if i < process_count - 1:
                log.info(f"Waiting {delay}s before next account…")
                await asyncio.sleep(delay)

        await browser.close()

    save_results(results, results_file)

    success_count = sum(1 for r in results if r["status"] == "success")
    log.info("-" * 60)
    log.info(f"Done. {success_count}/{process_count} account(s) registered successfully.")
    log.info(f"Results saved -> {results_file}")
    log.info(f"Remaining in '{csv_file}': {len(accounts)} account(s)")


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Auto Account Registration Tool")
    parser.add_argument("config", nargs="?", default=None, help="Config YAML path (default: config.yaml)")
    parser.add_argument("--limit", type=int, default=100, metavar="N", help="Max number of accounts to process (default: 100)")
    args = parser.parse_args()

    if args.config:
        cfg = args.config if os.path.isabs(args.config) else os.path.join(_LAUNCH_CWD, args.config)
    else:
        cfg = "config.yaml"   # relative to script dir (after chdir)

    asyncio.run(run(cfg, limit=args.limit))
