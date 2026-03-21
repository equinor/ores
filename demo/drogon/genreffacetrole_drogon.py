#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
genreffacetrole_drogon.py — Generate FacetRole reference-data manifest
for the Drogon pipeline.

Duplicated from demo/grand/py/5genreffacetrole.py so the Drogon tree is
self-contained and independent of grand/.

Output:
  demo/drogon/reftypes_facetroles.json

Usage:
  py demo/drogon/genreffacetrole_drogon.py
"""
import argparse
import json
import os
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent  # demo/drogon

ACL = {
    "owners": ["data.default.owners@dev.dataservices.energy"],
    "viewers": ["data.office.global.viewers@dev.dataservices.energy"],
}
LEGAL = {
    "legaltags": ["dev-equinor-osdu-reference-default"],
    "otherRelevantDataCountries": ["NO"],
}

FACET_TYPE = "statistics"

FACET_ROLES = [
    ("Arithmetic Mean", "ArithmeticMean"),
    ("P10", "P10"),
    ("P50", "P50"),
    ("P90", "P90"),
    ("Minimum", "Minimum"),
    ("Maximum", "Maximum"),
    ("Standard Deviation", "StardardDeviation"),
    ("Geometric Mean", "GeometricMean"),
    ("Harmonic Mean", "HarmonicMean"),
]


def main():
    ap = argparse.ArgumentParser(description="Generate FacetRole reference-data manifest.")
    ap.add_argument("--partition", default=os.getenv("OSDU_PARTITION", "dev"))
    ap.add_argument("--out", default=str(SCRIPT_DIR / "reftypes_facetroles.json"))
    args = ap.parse_args()

    partition = (args.partition or "dev").strip() or "dev"

    reference_entries = []
    for name, code in FACET_ROLES:
        reference_entries.append({
            "kind": "osdu:wks:reference-data--FacetRole:1.1.0",
            "id": f"{partition}:reference-data--FacetRole:{code}",
            "acl": ACL,
            "legal": LEGAL,
            "data": {
                "Name": name,
                "Code": code,
                "Description": f"Facet role '{name}' under FacetType '{FACET_TYPE}'.",
                "FacetType": FACET_TYPE,
            },
        })

    manifest = {
        "kind": "osdu:wks:Manifest:1.0.0",
        "ReferenceData": reference_entries,
        "MasterData": [],
        "Data": {
            "Datasets": [],
            "WorkProductComponents": [],
            "WorkProduct": [],
        },
    }

    Path(args.out).write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote: {args.out} (partition={partition})")
    print(f"  Entries: {len(reference_entries)}")


if __name__ == "__main__":
    main()
