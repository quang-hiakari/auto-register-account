"""
Auto Address Registration & Order Placement
--------------------------------------------
Reads accounts from a CSV file, registers an address if needed, then places
an order using the installment payment option.
All configuration is in config.yaml.

Usage:
    python register_address.py                # uses config.yaml
    python register_address.py my_config.yaml
    python register_address.py --limit 1      # test with 1 account
"""

import argparse
import csv
import os
import random
import time

import yaml
from playwright.sync_api import sync_playwright

os.chdir(os.path.dirname(os.path.abspath(__file__)))


def load_config(path="config.yaml"):
    with open(path, encoding="utf-8-sig") as f:
        return yaml.safe_load(f)


def random_phone():
    return str(random.randint(100_000_000, 999_999_999))


def login(page, cfg, email):
    page.goto(cfg["login_url"])
    page.wait_for_selector("#login-form-email")
    page.fill("#login-form-email", email)
    page.fill("#login-form-password", cfg["password"])
    page.click("#login")
    page.wait_for_url(lambda url: url != cfg["login_url"])


def has_existing_address(page, cfg):
    page.goto(cfg["address_url"])
    page.wait_for_selector(".modal-address-book-list", state="attached")
    return page.locator(".modal-address-book-list *").count() > 0


def register_address(page, cfg):
    addr = cfg["address"]
    page.click("#registrationAddressModal")

    page.wait_for_selector("#firstName", state="visible")
    page.fill("#firstName", addr["first_name"])
    page.fill("#lastName", addr["last_name"])
    page.fill("#streetAddress", addr["street"])
    page.fill("#city", addr["city"])
    page.fill("#zip", addr["zip"])

    page.select_option("#country", addr["country"])
    time.sleep(0.5)  # wait for state dropdown to populate
    page.select_option("#state", addr["state"])

    page.fill("#telephone", random_phone())
    page.click("#submitAddress")
    time.sleep(2)


def place_order(page, cfg):
    cart_url = cfg["cart_url"]

    # Step 1: Add to cart
    print("  [order 1] opening product page...", flush=True)
    page.goto(cfg["product_url"])
    page.click(".button-basic.add-to-cart")
    print("  [order 1] waiting for cart URL...", flush=True)
    page.wait_for_url(f"**{cart_url}**")
    print("  [order 1] cart OK", flush=True)

    # Step 2: Go to checkout (target correct product by data-pid)
    print("  [order 2] clicking checkout...", flush=True)
    page.click(".button-checkout[data-pid='product-instock']")
    page.wait_for_url(lambda url: cart_url not in url)
    print("  [order 2] checkout page OK", flush=True)

    # Step 3: Wait for checkout page to load
    print(f"  [order 3] current URL: {page.url}", flush=True)
    page.wait_for_selector(".jsChooseInstallmentPaymentOption", timeout=15000)

    # Accept cookie consent
    page.evaluate("var btn = document.querySelector('.jsCookieYes'); if (btn) btn.click();")
    time.sleep(0.3)

    print("  [order 3] choosing installment payment...", flush=True)
    page.locator(".jsChooseInstallmentPaymentOption").scroll_into_view_if_needed()
    page.locator(".jsChooseInstallmentPaymentOption").click()
    time.sleep(0.5)

    print("  [order 3] applying payment option...", flush=True)
    apply_btn = page.locator(".jsApplyPaymentOption")
    if apply_btn.count() == 0:
        raise Exception("jsApplyPaymentOption button not found")
    apply_btn.scroll_into_view_if_needed()
    apply_btn.click()
    print("  [order 3] payment option applied", flush=True)

    # Step 4: Confirm order
    print("  [order 4] confirming order...", flush=True)
    time.sleep(1)
    page.locator("#button-confirm-order").scroll_into_view_if_needed()
    page.locator("#button-confirm-order").click()
    page.wait_for_url(lambda url: "checkout" in url)
    print("  [order 4] confirm OK", flush=True)

    # Step 5: Complete order — opens popup with T&C checkbox
    time.sleep(1)
    print("  [order 5] completing order...", flush=True)
    page.locator(".button-complete-order").scroll_into_view_if_needed()
    page.locator(".button-complete-order").click()
    page.wait_for_selector("#is-agree", state="attached", timeout=10000)
    page.evaluate("var cb = document.getElementById('is-agree'); if (cb && !cb.checked) cb.click();")
    print("  [order 5] terms agreed", flush=True)

    # Step 6: Place order
    print("  [order 6] placing order...", flush=True)
    page.locator(".button-place-order").scroll_into_view_if_needed()
    page.locator(".button-place-order").click()
    time.sleep(3)
    print("  [order 6] done", flush=True)


def place_order_nodeposit(page, cfg):
    cart_url = cfg["cart_url"]

    # Step 1: Add to cart
    print("  [nodeposit 1] opening product page...", flush=True)
    page.goto(cfg["nodeposit_product_url"], wait_until="domcontentloaded")
    page.click(".button-basic.add-to-cart")
    page.wait_for_url(f"**{cart_url}**")
    print("  [nodeposit 1] cart OK", flush=True)

    # Step 2: Go to checkout (target correct product by data-pid)
    print("  [nodeposit 2] clicking checkout...", flush=True)
    page.click(".button-checkout[data-pid='nodeposit-instock']")
    page.wait_for_url(lambda url: cart_url not in url)
    print("  [nodeposit 2] checkout page OK", flush=True)

    # Step 3: Wait for confirm button then click directly (no payment plan needed)
    print("  [nodeposit 3] waiting for confirm order button...", flush=True)
    page.wait_for_selector("#button-confirm-order", timeout=15000)

    page.evaluate("var btn = document.querySelector('.jsCookieYes'); if (btn) btn.click();")
    time.sleep(0.3)

    page.locator("#button-confirm-order").scroll_into_view_if_needed()
    page.locator("#button-confirm-order").click()
    page.wait_for_url(lambda url: "checkout" in url)
    print("  [nodeposit 3] confirm OK", flush=True)

    # Step 4: Complete order — popup with T&C checkbox
    time.sleep(1)
    print("  [nodeposit 4] completing order...", flush=True)
    page.locator(".button-complete-order").scroll_into_view_if_needed()
    page.locator(".button-complete-order").click()
    page.wait_for_selector("#is-agree", state="attached", timeout=10000)
    page.evaluate("var cb = document.getElementById('is-agree'); if (cb && !cb.checked) cb.click();")
    print("  [nodeposit 4] terms agreed", flush=True)

    # Step 5: Place order
    print("  [nodeposit 5] placing order...", flush=True)
    page.locator(".button-place-order").scroll_into_view_if_needed()
    page.locator(".button-place-order").click()
    time.sleep(3)
    print("  [nodeposit 5] done", flush=True)


def remove_from_csv(csv_file, email):
    with open(csv_file, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    rows = [r for r in rows if r["Email"].strip() != email]
    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["Email"])
        writer.writeheader()
        writer.writerows(rows)


def make_browser(cfg):
    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=False, args=["--start-maximized"])
    context = browser.new_context(no_viewport=True)
    page = context.new_page()
    page.set_default_timeout(cfg["wait_timeout"] * 1000)
    return pw, browser, page


def process_accounts(cfg, limit=None):
    with open(cfg["csv_file"], newline="", encoding="utf-8") as f:
        emails = [row["Email"].strip() for row in csv.DictReader(f) if row["Email"].strip()]
    if limit:
        emails = emails[:limit]

    success, failed = 0, 0

    for idx, email in enumerate(emails, 1):
        print(f"[{idx}/{len(emails)}] {email}", end=" -> ", flush=True)
        pw, browser, page = make_browser(cfg)
        completed = False
        try:
            login(page, cfg, email)

            if has_existing_address(page, cfg):
                print("address exists |", end=" ", flush=True)
            else:
                register_address(page, cfg)
                print("address registered |", end=" ", flush=True)

            place_order(page, cfg)
            place_order_nodeposit(page, cfg)
            completed = True

        except Exception as e:
            print(f"FAIL ({str(e).encode('ascii', errors='replace').decode()})")
            failed += 1
        finally:
            try:
                browser.close()
                pw.stop()
            except Exception:
                pass

        if completed:
            print("orders placed OK")
            success += 1
            remove_from_csv(cfg["csv_file"], email)

        time.sleep(cfg.get("delay_between_accounts", 1))

    print(f"\nDone. success={success}  failed={failed}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("config", nargs="?", default="config.yaml")
    parser.add_argument("--limit", type=int, default=None, help="Process only N accounts (for testing)")
    args = parser.parse_args()

    process_accounts(load_config(args.config), limit=args.limit)
