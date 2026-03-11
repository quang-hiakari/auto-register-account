import xml.etree.ElementTree as ET
import csv

XML_FILE = "customerList_20260311.xml"
OUTPUT_FILE = "customer_default_country.csv"
NS = {"dw": "http://www.demandware.com/xml/impex/customer/2006-10-31"}

rows = []

tree = ET.parse(XML_FILE)
root = tree.getroot()

for customer in root.findall("dw:customer", NS):
    customer_no = customer.get("customer-no", "")

    country_code = ""
    for address in customer.findall("dw:addresses/dw:address", NS):
        if address.get("preferred") == "true":
            cc_el = address.find("dw:country-code", NS)
            country_code = cc_el.text.strip() if cc_el is not None and cc_el.text else ""
            break

    rows.append([customer_no, country_code])

with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(["customer-no", "country-code"])
    writer.writerows(rows)

print(f"{OUTPUT_FILE} -> {len(rows)} records")
