#!/usr/bin/env python3
"""Build an OSDU manifest from a local RDDMS dataspace and summarize it.

Usage: build_and_summarize.py <dataspace> <mode:all|filtered> <out.json>
"""
import json
import re
import sys
import urllib.request
from collections import Counter

BASE = "http://localhost:8080/api/reservoir-ddms/v2"
HDRS = {"data-partition-id": "opendes", "Authorization": "Bearer dummy",
        "Content-Type": "application/json"}


def build(ds: str, mode: str):
    body = {
        "uris": [f"eml:///dataspace('{ds}')"],
        "propertyFilter": "canonical",
        "includeArrayData": False,
    }
    if mode == "filtered":
        body["excludePatterns"] = ["*Activity", "*ActivityTemplate"]
    req = urllib.request.Request(
        f"{BASE}/manifests/build", data=json.dumps(body).encode(),
        headers=HDRS, method="POST")
    with urllib.request.urlopen(req, timeout=600) as r:
        return r.status, json.load(r)


def kinds_from(manifest: dict):
    """Yield every record kind in a manifest envelope (handles both the OSDU
    envelope {ReferenceData,MasterData,Data:{WorkProduct,WorkProductComponents,
    Datasets}} and a flat list)."""
    def walk(obj):
        if isinstance(obj, dict):
            if "kind" in obj and isinstance(obj["kind"], str) and "id" in obj:
                yield obj["kind"]
            for v in obj.values():
                yield from walk(v)
        elif isinstance(obj, list):
            for v in obj:
                yield from walk(v)
    yield from walk(manifest)


def categorize(kind: str) -> str:
    if "master-data" in kind:
        return "MasterData"
    if "work-product-component" in kind:
        return "WPC"
    if "work-product-" in kind and "component" not in kind:
        return "WorkProduct"
    if "reference-data" in kind:
        return "ReferenceData"
    if "dataset" in kind:
        return "Dataset"
    return "other"


def short(kind: str) -> str:
    m = re.search(r"--([A-Za-z]+):", kind)
    return m.group(1) if m else kind


def main():
    ds, mode, out = sys.argv[1], sys.argv[2], sys.argv[3]
    status, manifest = build(ds, mode)
    with open(out, "w") as f:
        json.dump(manifest, f, indent=2)
    kinds = list(kinds_from(manifest))
    cats = Counter(categorize(k) for k in kinds)
    shorts = Counter(short(k) for k in kinds)
    print(f"[{status}] {ds} ({mode}) -> {out}")
    print(f"  total records: {len(kinds)}")
    print(f"  by category: {dict(cats)}")
    top = ", ".join(f"{k}:{v}" for k, v in shorts.most_common(12))
    print(f"  by type: {top}")


if __name__ == "__main__":
    main()
