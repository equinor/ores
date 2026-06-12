"""Fetch authoritative OSDU schemas from interop and extract data field names."""
import sys
import json

sys.path.insert(0, "demo")
from _auth import get_token, load_instance  # noqa: E402
import httpx  # noqa: E402

inst = load_instance("interop")
host = inst["host"].replace("https://", "").replace("http://", "").rstrip("/")
token = get_token("interop", verbose=False)
base = f"https://{host}"
partition = inst.get("partition", "opendes")
headers = {"Authorization": f"Bearer {token}", "data-partition-id": partition}


def resolve_data_fields(sch):
    defs = sch.get("definitions", {})
    fields = {}

    def collect(node, depth=0):
        if not isinstance(node, dict) or depth > 8:
            return
        if "$ref" in node:
            ref = node["$ref"].split("/")[-1]
            collect(defs.get(ref, {}), depth + 1)
            return
        if "properties" in node:
            for k, v in node["properties"].items():
                t = v.get("type") or v.get("$ref", "").split("/")[-1] or "?"
                fields[k] = t
        for key in ("allOf", "anyOf", "oneOf"):
            for sub in node.get(key, []):
                collect(sub, depth + 1)

    data = sch.get("properties", {}).get("data", {})
    collect(data)
    return fields


KINDS = [
    "osdu:wks:work-product-component--StructureMap:1.0.0",
    "osdu:wks:work-product-component--GenericBinGrid:1.0.0",
    "osdu:wks:work-product-component--StructuralModel:1.0.0",
    "osdu:wks:work-product-component--SeismicHorizon:2.1.0",
    "osdu:wks:master-data--LocalBoundaryFeature:1.1.0",
    "osdu:wks:master-data--BoundaryFeature:1.2.0",
    "osdu:wks:work-product-component--LocalBoundaryFeature:1.2.0",
]

for kind in KINDS:
    r = httpx.get(f"{base}/api/schema-service/v1/schema/{kind}", headers=headers, timeout=20)
    print(f"\n=== {kind} → HTTP {r.status_code} ===")
    if r.status_code == 200:
        fields = resolve_data_fields(r.json())
        for k in sorted(fields):
            print(f"    {k}: {fields[k]}")
