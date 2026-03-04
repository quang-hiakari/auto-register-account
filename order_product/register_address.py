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
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

os.chdir(os.path.dirname(os.path.abspath(__file__)))


def load_config(path="config.yaml"):
    with open(path, encoding="utf-8-sig") as f:
        return yaml.safe_load(f)


def random_phone():
    return str(random.randint(100_000_000, 999_999_999))


def login(driver, wait, cfg, email):
    driver.get(cfg["login_url"])
    wait.until(EC.presence_of_element_located((By.ID, "login-form-email")))
    driver.find_element(By.ID, "login-form-email").clear()
    driver.find_element(By.ID, "login-form-email").send_keys(email)
    driver.find_element(By.ID, "login-form-password").clear()
    driver.find_element(By.ID, "login-form-password").send_keys(cfg["password"])
    driver.find_element(By.ID, "login").click()
    wait.until(EC.url_changes(cfg["login_url"]))


def has_existing_address(driver, wait, cfg):
    driver.get(cfg["address_url"])
    wait.until(EC.presence_of_element_located((By.CLASS_NAME, "modal-address-book-list")))
    section = driver.find_element(By.CLASS_NAME, "modal-address-book-list")
    return len(section.find_elements(By.XPATH, ".//*")) > 0


def register_address(driver, wait, cfg):
    addr = cfg["address"]
    wait.until(EC.element_to_be_clickable((By.ID, "registrationAddressModal"))).click()

    wait.until(EC.visibility_of_element_located((By.ID, "firstName")))
    driver.find_element(By.ID, "firstName").clear()
    driver.find_element(By.ID, "firstName").send_keys(addr["first_name"])

    driver.find_element(By.ID, "lastName").clear()
    driver.find_element(By.ID, "lastName").send_keys(addr["last_name"])

    driver.find_element(By.ID, "streetAddress").clear()
    driver.find_element(By.ID, "streetAddress").send_keys(addr["street"])

    driver.find_element(By.ID, "city").clear()
    driver.find_element(By.ID, "city").send_keys(addr["city"])

    driver.find_element(By.ID, "zip").clear()
    driver.find_element(By.ID, "zip").send_keys(addr["zip"])

    Select(driver.find_element(By.ID, "country")).select_by_value(addr["country"])
    time.sleep(0.5)  # wait for state dropdown to populate
    Select(driver.find_element(By.ID, "state")).select_by_value(addr["state"])

    driver.find_element(By.ID, "telephone").clear()
    driver.find_element(By.ID, "telephone").send_keys(random_phone())

    driver.find_element(By.ID, "submitAddress").click()
    time.sleep(2)


def place_order(driver, wait, cfg):
    cart_url = cfg["cart_url"]

    # Step 1: Add to cart
    print("  [order 1] opening product page...", flush=True)
    driver.get(cfg["product_url"])
    wait.until(EC.element_to_be_clickable(
        (By.CSS_SELECTOR, ".button-basic.add-to-cart")
    )).click()
    print("  [order 1] waiting for cart URL...", flush=True)
    wait.until(EC.url_contains(cart_url))
    print("  [order 1] cart OK", flush=True)

    # Step 2: Go to checkout (target correct product by data-pid)
    print("  [order 2] clicking checkout...", flush=True)
    wait.until(EC.element_to_be_clickable(
        (By.CSS_SELECTOR, ".button-checkout[data-pid='product-instock']")
    )).click()
    wait.until(EC.url_changes(cart_url))
    print("  [order 2] checkout page OK", flush=True)

    # Step 3: Wait for checkout page to load (using sleep loop, not wait.until to avoid crash)
    print(f"  [order 3] current URL: {driver.current_url}", flush=True)
    for _ in range(15):
        found = driver.execute_script(
            "return !!document.querySelector('.jsChooseInstallmentPaymentOption');"
        )
        if found:
            break
        time.sleep(1)
    else:
        raise Exception("Checkout page did not load jsChooseInstallmentPaymentOption")

    # Accept cookie consent
    driver.execute_script("var btn = document.querySelector('.jsCookieYes'); if (btn) btn.click();")
    time.sleep(0.3)

    print("  [order 3] choosing installment payment...", flush=True)
    driver.execute_script("""
        var el = document.querySelector('.jsChooseInstallmentPaymentOption');
        if (el) { el.scrollIntoView(true); el.click(); }
    """)
    time.sleep(0.5)

    print("  [order 3] applying payment option...", flush=True)
    clicked = driver.execute_script("""
        var el = document.querySelector('.jsApplyPaymentOption');
        if (el) { el.scrollIntoView(true); el.click(); return true; }
        return false;
    """)
    if not clicked:
        raise Exception("jsApplyPaymentOption button not found")
    print("  [order 3] payment option applied", flush=True)

    # Step 4: Confirm order
    print("  [order 4] confirming order...", flush=True)
    time.sleep(1)
    driver.execute_script("""
        var el = document.getElementById('button-confirm-order');
        if (el) { el.scrollIntoView(true); el.click(); }
    """)
    wait.until(EC.url_contains("checkout"))
    print("  [order 4] confirm OK", flush=True)

    # Step 5: Complete order — opens popup with T&C checkbox
    time.sleep(1)
    print("  [order 5] completing order...", flush=True)
    driver.execute_script("""
        var el = document.querySelector('.button-complete-order');
        if (el) { el.scrollIntoView(true); el.click(); }
    """)
    for _ in range(10):
        found = driver.execute_script("return !!document.getElementById('is-agree');")
        if found:
            break
        time.sleep(1)
    driver.execute_script("""
        var cb = document.getElementById('is-agree');
        if (cb && !cb.checked) cb.click();
    """)
    print("  [order 5] terms agreed", flush=True)

    # Step 6: Place order
    print("  [order 6] placing order...", flush=True)
    driver.execute_script("""
        var el = document.querySelector('.button-place-order');
        if (el) { el.scrollIntoView(true); el.click(); }
    """)
    time.sleep(3)
    print("  [order 6] done", flush=True)


def place_order_nodeposit(driver, wait, cfg):
    cart_url = cfg["cart_url"]

    # Step 1: Add to cart
    print("  [nodeposit 1] opening product page...", flush=True)
    driver.get(cfg["nodeposit_product_url"])
    wait.until(EC.element_to_be_clickable(
        (By.CSS_SELECTOR, ".button-basic.add-to-cart")
    )).click()
    wait.until(EC.url_contains(cart_url))
    print("  [nodeposit 1] cart OK", flush=True)

    # Step 2: Go to checkout (target correct product by data-pid)
    print("  [nodeposit 2] clicking checkout...", flush=True)
    wait.until(EC.element_to_be_clickable(
        (By.CSS_SELECTOR, ".button-checkout[data-pid='nodeposit-instock']")
    )).click()
    wait.until(EC.url_changes(cart_url))
    print("  [nodeposit 2] checkout page OK", flush=True)

    # Step 3: Wait for confirm button then click directly (no payment plan needed)
    print("  [nodeposit 3] waiting for confirm order button...", flush=True)
    for _ in range(15):
        found = driver.execute_script(
            "return !!document.getElementById('button-confirm-order');"
        )
        if found:
            break
        time.sleep(1)
    else:
        raise Exception("button-confirm-order not found on nodeposit checkout")

    driver.execute_script("var btn = document.querySelector('.jsCookieYes'); if (btn) btn.click();")
    time.sleep(0.3)

    driver.execute_script("""
        var el = document.getElementById('button-confirm-order');
        if (el) { el.scrollIntoView(true); el.click(); }
    """)
    wait.until(EC.url_contains("checkout"))
    print("  [nodeposit 3] confirm OK", flush=True)

    # Step 4: Complete order — popup with T&C checkbox
    time.sleep(1)
    print("  [nodeposit 4] completing order...", flush=True)
    driver.execute_script("""
        var el = document.querySelector('.button-complete-order');
        if (el) { el.scrollIntoView(true); el.click(); }
    """)
    for _ in range(10):
        found = driver.execute_script("return !!document.getElementById('is-agree');")
        if found:
            break
        time.sleep(1)
    driver.execute_script("""
        var cb = document.getElementById('is-agree');
        if (cb && !cb.checked) cb.click();
    """)
    print("  [nodeposit 4] terms agreed", flush=True)

    # Step 5: Place order
    print("  [nodeposit 5] placing order...", flush=True)
    driver.execute_script("""
        var el = document.querySelector('.button-place-order');
        if (el) { el.scrollIntoView(true); el.click(); }
    """)
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


def make_driver(cfg):
    options = webdriver.ChromeOptions()
    options.add_argument("--start-maximized")
    driver = webdriver.Chrome(options=options)
    wait = WebDriverWait(driver, cfg["wait_timeout"])
    return driver, wait


def process_accounts(cfg, limit=None):
    with open(cfg["csv_file"], newline="", encoding="utf-8") as f:
        emails = [row["Email"].strip() for row in csv.DictReader(f) if row["Email"].strip()]
    if limit:
        emails = emails[:limit]

    success, failed = 0, 0

    for idx, email in enumerate(emails, 1):
        print(f"[{idx}/{len(emails)}] {email}", end=" -> ", flush=True)
        driver, wait = make_driver(cfg)
        completed = False
        try:
            login(driver, wait, cfg, email)

            if has_existing_address(driver, wait, cfg):
                print("address exists |", end=" ", flush=True)
            else:
                register_address(driver, wait, cfg)
                print("address registered |", end=" ", flush=True)

            place_order(driver, wait, cfg)
            place_order_nodeposit(driver, wait, cfg)
            completed = True

        except Exception as e:
            print(f"FAIL ({e})")
            failed += 1
        finally:
            try:
                driver.quit()
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
