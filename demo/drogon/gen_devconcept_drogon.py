#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_devconcept_drogon.py — Generate a DevelopmentConcept WPC manifest for
Drogon DG1.

Output:
  manifest_devconcept_drogon.json

Usage:
  py demo/drogon/gen_devconcept_drogon.py
"""

import argparse
import json
from pathlib import Path
from typing import Any, Dict

SCRIPT_DIR = Path(__file__).resolve().parent

from _shared import load_json  # noqa: E402

DEFAULT_ACL = {
    "owners":  ["data.default.owners@dev.dataservices.energy"],
    "viewers": ["data.office.global.viewers@dev.dataservices.energy"],
}
DEFAULT_LEGAL = {
    "legaltags": ["dev-equinor-private-default"],
    "otherRelevantDataCountries": ["NO"],
}


def _find_id(manifest: Dict, kind_fragment: str) -> str:
    for md in manifest.get("MasterData", []):
        if kind_fragment in md.get("kind", ""):
            return md["id"]
    for wpc in manifest.get("Data", {}).get("WorkProductComponents", []):
        if kind_fragment in wpc.get("kind", ""):
            return wpc["id"]
    return ""


def main():
    ap = argparse.ArgumentParser(description="Generate Drogon DG1 DevelopmentConcept WPC manifest")
    ap.add_argument("--masterwp", default=str(SCRIPT_DIR / "manifest_masterwp_drogon.json"))
    ap.add_argument("--manifest", default=str(SCRIPT_DIR / "manifest_devconcept_drogon.json"))
    ap.add_argument("--id-prefix", default="dev")
    args = ap.parse_args()

    pfx = args.id_prefix

    # Load reservoir ID for ancestry
    masterwp = load_json(args.masterwp)
    reservoir_id = _find_id(masterwp, "master-data--Reservoir:")

    wpc_id = f"{pfx}:work-product-component--DevelopmentConcept:Drogon-DG1:1"

    wpc_record = {
        "id":    wpc_id,
        "kind":  f"{pfx}:wks:work-product-component--DevelopmentConcept:1.0.0",
        "acl":   DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": "Drogon DG1 — Development Concept",
            "Description": (
                "Early-stage development concept for Drogon DG1 Identify & Assess. "
                "Subsea tie-back to host facility targeting Valysar formation."
            ),
            "ParentObjectID": reservoir_id,
            "ancestry": {
                "parents": [reservoir_id] if reservoir_id else [],
                "children": [],
            },

            # ── DevelopmentConcept fields ──
            "Summary": (
                "Subsea development with tie-back to existing host facility. "
                "Valysar formation at ~1700 m TVD MSL in the Drogon area, "
                "Norwegian North Sea."
            ),
            "WellCount": 12,
            "TemplateSlots": 16,
            "ReservoirFormation": "Valysar",
            "FieldArea": "Drogon",
            "WaterDepth_m": 108,
            "TargetStartUp": "2028-H1",
        },
    }

    manifest = {
        "kind": "osdu:wks:Manifest:1.0.0",
        "ReferenceData": [],
        "MasterData": [],
        "Data": {
            "Datasets": [],
            "WorkProductComponents": [wpc_record],
            "WorkProducts": [],
        },
    }

    out = Path(args.manifest)
    out.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"DevelopmentConcept WPC manifest written → {out}")
    print(f"  WPC ID      : {wpc_id}")
    print(f"  Reservoir   : {reservoir_id}")


if __name__ == "__main__":
    main()
