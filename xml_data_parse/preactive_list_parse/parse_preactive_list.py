import csv
import glob
import os
import xml.etree.ElementTree as ET

ACTIVATION_BASE = (
    "https://bjfl-003.dx.commercecloud.salesforce.com/on/demandware.store"
    "/Sites-Prime1StudioEc-Site/default/Account-CompletRegistration?Id={}"
)
NS = {"dw": "http://www.demandware.com/xml/impex/customobject/2006-10-31"}


def parse_xml(xml_path: str) -> list[dict]:
    tree = ET.parse(xml_path)
    root = tree.getroot()
    rows = []
    for obj in root.findall("dw:custom-object", NS):
        object_id = obj.get("object-id", "")
        email = ""
        for attr in obj.findall("dw:object-attribute", NS):
            if attr.get("attribute-id") == "email":
                email = attr.text or ""
                break
        rows.append(
            {
                "activation_link": ACTIVATION_BASE.format(object_id),
                "email": email,
            }
        )
    return rows


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    xml_files = glob.glob(os.path.join(script_dir, "*.xml"))

    if not xml_files:
        print("No XML files found in", script_dir)
        return

    all_rows: list[dict] = []
    for xml_file in sorted(xml_files):
        print(f"Parsing: {os.path.basename(xml_file)}")
        all_rows.extend(parse_xml(xml_file))

    output_path = os.path.join(script_dir, "preactive_list.csv")
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["activation_link", "email"])
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"Done - {len(all_rows)} records written to {output_path}")


if __name__ == "__main__":
    main()
