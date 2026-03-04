import xml.etree.ElementTree as ET
import csv

XML_FILE = "customer_003_20260304.xml"
NS = {"dw": "http://www.demandware.com/xml/impex/customer/2006-10-31"}

with_billing = []
without_billing = []

tree = ET.parse(XML_FILE)
root = tree.getroot()

for customer in root.findall("dw:customer", NS):
    email_el = customer.find("dw:profile/dw:email", NS)
    email = email_el.text.strip() if email_el is not None and email_el.text else ""

    billing_id = None
    for attr in customer.findall(
        "dw:profile/dw:custom-attributes/dw:custom-attribute", NS
    ):
        if attr.get("attribute-id") == "billingAgreementId":
            billing_id = attr.text.strip() if attr.text else None
            break

    if billing_id:
        with_billing.append(email)
    else:
        without_billing.append(email)

with open("accounts_with_billing.csv", "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(["Email"])
    for email in with_billing:
        writer.writerow([email])

with open("accounts_without_billing.csv", "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(["Email"])
    for email in without_billing:
        writer.writerow([email])

print(f"accounts_with_billing.csv    -> {len(with_billing)} records")
print(f"accounts_without_billing.csv -> {len(without_billing)} records")
