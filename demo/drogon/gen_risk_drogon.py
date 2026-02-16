#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_risk_drogon.py — Generate a Risk manifest for Drogon / Valysar.

Creates:
  master-data--Risk  "Drogon — Porosity and cementation uncertainty"

Output:
  manifest_risk_drogon.json

Usage:
  py demo/drogon/gen_risk_drogon.py
"""

import argparse
import json
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent

DEFAULT_ACL = {
    "owners":  ["data.default.owners@dev.dataservices.energy"],
    "viewers": ["data.office.global.viewers@dev.dataservices.energy"],
}
DEFAULT_LEGAL = {
    "legaltags": ["dev-equinor-private-default"],
    "otherRelevantDataCountries": ["NO"],
}


def main():
    ap = argparse.ArgumentParser(description="Generate Drogon Risk manifest")
    ap.add_argument("--manifest", default=str(SCRIPT_DIR / "manifest_risk_drogon.json"))
    ap.add_argument("--id-prefix", default="dev")
    args = ap.parse_args()

    risk_id = f"{args.id_prefix}:master-data--Risk:Drogon-PorosityAndCementation:1"

    risk_record = {
        "id":    risk_id,
        "kind":  "osdu:wks:master-data--Risk:1.2.0",
        "acl":   DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": "Drogon — Porosity and cementation uncertainty",
            "Summary": (
                "Porosity and cementation quality in the Valysar fluvial deposits "
                "drive uncertainty in pore volume and hydrocarbon recovery."
            ),
            "Description": (
                "The Valysar fluvial system shows significant facies-dependent porosity "
                "variation (Floodplain ~0.10, Channel ~0.28, Crevasse ~0.21). "
                "Cementation and diagenetic effects further reduce effective porosity, "
                "particularly in the deeper segments. This risk affects volumetric "
                "estimates (BulkOil, PoreOil, HydrocarbonPoreOil) and recovery factor "
                "across all 7 reservoir segments."
            ),
            "TypeID": "osdu:wks:reference-data--RiskType:risk:1.0.0",
            "EffectiveDateTime": "2026-02-13T00:00:00Z",
            "ext": {
                "equinor": {
                    "CategoryID": f"{args.id_prefix}:reference-data--RiskCategory:Subsurface-Static:1",
                    "SeverityScaleID": f"{args.id_prefix}:reference-data--RiskSeverityScale:Equinor-5x5:1",
                    "ProbabilityScaleID": f"{args.id_prefix}:reference-data--RiskProbabilityScale:Equinor-5x5:1",
                    "RiskAcceptanceCriteriaID": f"{args.id_prefix}:reference-data--RiskAcceptanceCriteria:RAC-2025-01:1",
                    "InherentSeverity":    "S3",
                    "InherentProbability":  "P4",
                    "ResidualSeverity":    "S2",
                    "ResidualProbability":  "P3",
                    "AcceptedAsIs": False,
                    "Status": "Open",
                    "MitigationActionIDs": [],
                },
            },
        },
    }

    manifest = {
        "kind": "osdu:wks:Manifest:1.0.0",
        "ReferenceData": [],
        "MasterData": [risk_record],
        "Data": {
            "Datasets": [],
            "WorkProductComponents": [],
            "WorkProducts": [],
        },
    }

    Path(args.manifest).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Risk manifest written → {args.manifest}")
    print(f"  Risk ID: {risk_id}")


if __name__ == "__main__":
    main()
