#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_devconcept_dg2.py — Generate a DevelopmentConcept WPC manifest for
Drogon DG2.

Output:
  manifest_devconcept_dg2.json

Usage:
  py demo/drogon_dg2/gen_devconcept_dg2.py
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

SCRIPT_DIR = Path(__file__).resolve().parent
DG1_DIR    = SCRIPT_DIR.parent / "drogon"

if str(DG1_DIR) not in sys.path:
    sys.path.insert(0, str(DG1_DIR))

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
    ap = argparse.ArgumentParser(description="Generate Drogon DG2 DevelopmentConcept WPC manifest")
    ap.add_argument("--masterwp", default=str(DG1_DIR / "manifest_masterwp_drogon.json"))
    ap.add_argument("--manifest", default=str(SCRIPT_DIR / "manifest_devconcept_dg2.json"))
    ap.add_argument("--id-prefix", default="dev")
    args = ap.parse_args()

    pfx = args.id_prefix

    masterwp = load_json(args.masterwp)
    reservoir_id = _find_id(masterwp, "master-data--Reservoir:")

    wpc_id = f"{pfx}:work-product-component--DevelopmentConcept:Drogon-DG2:1"

    wpc_record = {
        "id":    wpc_id,
        "kind":  f"{pfx}:wks:work-product-component--DevelopmentConcept:1.0.0",
        "acl":   DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": "Drogon DG2 — Development Concept",
            "Description": (
                "Full development concept for Drogon DG2 Concept Select. "
                "Subsea tie-back to converted FPSO, 2×4-slot templates, "
                "12 production wells, subsea boosting pump."
            ),
            "ParentObjectID": reservoir_id,
            "ancestry": {
                "parents": [reservoir_id] if reservoir_id else [],
                "children": [],
            },

            # ── DevelopmentConcept fields ──
            "Summary": (
                "Subsea development with 2×4-slot templates (8 slots + 2 contingent), "
                "tie-back to converted FPSO via dual 10\" production flowlines and "
                "6\" gas-lift line. Distance to FPSO ~8 km. Water depth 108 m. "
                "Valysar formation at ~1700 m TVD MSL."
            ),
            "WellCount": 12,
            "ContingentWells": 2,
            "TemplateSlots": 10,
            "DrillingCentres": 2,
            "ReservoirFormation": "Valysar",
            "FieldArea": "Drogon",
            "WaterDepth_m": 108,
            "DistanceToHost_km": 8,
            "HostFacility": "Drogon FPSO (converted)",
            "TargetStartUp": "2028-H1",
            "FlowlineSpec": "2\u00d710\" production + 6\" gas lift",
            "SubseaBoostingPump": True,
            "WaterTreatmentCapacity_m3d": 5000,
            "InjectionStrategy": "Water injection for pressure support (4 injectors planned Phase 2)",
            "WellPlan": {
                "Producers": 12,
                "Injectors_Phase2": 4,
                "AvgWellDepth_mMD": 3200,
                "DrillingDuration_days_avg": 45,
                "CompletionType": "Frac-pack + ICD lower completion",
            },
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
    print(f"DevelopmentConcept WPC manifest written \u2192 {out}")
    print(f"  WPC ID      : {wpc_id}")
    print(f"  Reservoir   : {reservoir_id}")


if __name__ == "__main__":
    main()
