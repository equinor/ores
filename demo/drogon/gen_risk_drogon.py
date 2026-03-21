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
    risk_fault_id = f"{args.id_prefix}:master-data--Risk:Drogon-FaultCompartment:1"

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

    risk_fault_record = {
        "id":    risk_fault_id,
        "kind":  "osdu:wks:master-data--Risk:1.2.0",
        "acl":   DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": "Drogon \u2014 Fault transmissibility and reservoir compartmentalization",
            "Summary": (
                "Sealing or partially-sealing faults may compartmentalise the Valysar "
                "reservoir, restricting pressure communication and drainage across segments, "
                "leading to production shortfalls and cost increases."
            ),
            "Description": (
                "Fault transmissibility analysis indicates uncertainty in whether "
                "bounding and intra-reservoir faults act as baffles or barriers in the "
                "Valysar formation. Compartmentalization could isolate hydrocarbons in "
                "poorly-drained fault blocks, reducing sweep efficiency and plateau rates. "
                "This risk drives uncertainty in recovery factor and may require additional "
                "infill wells beyond the current 12-well plan, with material cost increase "
                "implications for the DG2 concept. Mitigation relies on production testing "
                "to establish inter-compartment pressure communication and targeted "
                "additional wells to drain isolated blocks."
            ),
            "TypeID": "osdu:wks:reference-data--RiskType:risk:1.0.0",
            "EffectiveDateTime": "2026-02-28T00:00:00Z",
            "ext": {
                "equinor": {
                    "CategoryID": f"{args.id_prefix}:reference-data--RiskCategory:Subsurface-Dynamic:1",
                    "SeverityScaleID": f"{args.id_prefix}:reference-data--RiskSeverityScale:Equinor-5x5:1",
                    "ProbabilityScaleID": f"{args.id_prefix}:reference-data--RiskProbabilityScale:Equinor-5x5:1",
                    "RiskAcceptanceCriteriaID": f"{args.id_prefix}:reference-data--RiskAcceptanceCriteria:RAC-2025-01:1",
                    "InherentSeverity":    "S4",
                    "InherentProbability":  "P3",
                    "ResidualSeverity":    "S3",
                    "ResidualProbability":  "P2",
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
        "MasterData": [risk_record, risk_fault_record],
        "Data": {
            "Datasets": [],
            "WorkProductComponents": [],
            "WorkProducts": [],
        },
    }

    Path(args.manifest).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Risk manifest written → {args.manifest}")
    print(f"  Risk ID (porosity)  : {risk_id}")
    print(f"  Risk ID (fault)     : {risk_fault_id}")


if __name__ == "__main__":
    main()
