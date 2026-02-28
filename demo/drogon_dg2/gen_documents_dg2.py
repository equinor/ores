#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_documents_dg2.py — Generate Document WPC records for the Drogon DG2
(Concept Select) decision gate package.

Creates:
  work-product-component--Document  "Drogon — Subsurface Risk Assessment (SRA) DG2"
  work-product-component--Document  "Drogon — Cost Risk Assessment (CRA) DG2"
  work-product-component--Document  "Drogon — Plan for Development and Operation (PDO) DG2"
  work-product-component--Document  "Drogon — Petroleum Technology Report (PTR) DG2"

These are stub records (no file blob) that serve as typed references from
the BusinessDecision Parameters[] and RiskAssessmentDocument fields.

Output:
  manifest_documents_dg2.json

Usage:
  py demo/drogon_dg2/gen_documents_dg2.py
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
    ap = argparse.ArgumentParser(description="Generate Drogon DG2 Document WPC manifest")
    ap.add_argument("--manifest", default=str(SCRIPT_DIR / "manifest_documents_dg2.json"))
    ap.add_argument("--id-prefix", default="dev")
    args = ap.parse_args()

    pfx = args.id_prefix

    sra = {
        "id":    f"{pfx}:work-product-component--Document:Drogon-SRA-DG2-Report:1",
        "kind":  "osdu:wks:work-product-component--Document:1.2.0",
        "acl":   DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": "Drogon \u2014 Schedule Risk Assessment (SRA) DG2",
            "Description": (
                "Schedule Risk Assessment for the Drogon field development DG2 "
                "Concept Select gate. Monte Carlo schedule analysis (1000 iterations) "
                "covering subsea installation, FPSO conversion, drilling campaign, "
                "and commissioning timeline. P50 first oil June 2028, P90 first oil "
                "March 2029. Key risk drivers: FPSO drydock slot availability, subsea "
                "template fabrication (18-month lead), and drilling rig market."
            ),
            "DocumentType": "SRA",
            "DocumentDate": "2026-02-15",
        },
    }

    cra = {
        "id":    f"{pfx}:work-product-component--Document:Drogon-CRA-DG2-Report:1",
        "kind":  "osdu:wks:work-product-component--Document:1.2.0",
        "acl":   DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": "Drogon \u2014 Cost Risk Assessment (CRA) DG2",
            "Description": (
                "Cost Risk Assessment for the Drogon field development DG2 Concept "
                "Select gate. Probabilistic cost estimate (1000 iterations) covering "
                "subsea CAPEX, FPSO conversion, drilling (12+2 contingent wells), "
                "and project management. P50 total CAPEX 8,500 MNOK; P90 10,400 MNOK. "
                "Main cost drivers: drilling duration uncertainty (12\u201316 wells "
                "depending on compartmentalisation), FPSO water treatment module scope, "
                "and steel/fabrication market prices."
            ),
            "DocumentType": "CRA",
            "DocumentDate": "2026-02-15",
        },
    }

    pdo = {
        "id":    f"{pfx}:work-product-component--Document:Drogon-PDO-DG2-Draft:1",
        "kind":  "osdu:wks:work-product-component--Document:1.2.0",
        "acl":   DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": "Drogon \u2014 Plan for Development and Operation (PDO) DG2 Draft",
            "Description": (
                "Draft PDO for the Drogon DG2 Concept Select gate. Covers field "
                "description, selected development concept (subsea tie-back to FPSO, "
                "2\u00d74-slot templates, 12 wells), preliminary environmental impact "
                "assessment, well planning, production forecasts, and regulatory "
                "framework alignment with PSA and MPE requirements. Basis for DG3 "
                "FEED scope definition."
            ),
            "DocumentType": "PDO",
            "DocumentDate": "2026-03-01",
        },
    }

    ptr = {
        "id":    f"{pfx}:work-product-component--Document:Drogon-PTR-DG2-Report:1",
        "kind":  "osdu:wks:work-product-component--Document:1.2.0",
        "acl":   DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": "Drogon \u2014 Petroleum Technology Report (PTR) DG2",
            "Description": (
                "Petroleum Technology Report for DG2 Concept Select. Covers seismic "
                "interpretation, petrophysical evaluation, geomodelling (50 FMU "
                "realisations), dynamic simulation (base + 4 sensitivities), "
                "volumetric uncertainty (P10/P50/P90 STOIIP and recoverable), "
                "production forecasting (20-year profile), and recovery factor "
                "analysis across 7 Valysar segments. 285 pages."
            ),
            "DocumentType": "PTR",
            "DocumentDate": "2026-02-20",
        },
    }

    manifest = {
        "kind": "osdu:wks:Manifest:1.0.0",
        "ReferenceData": [],
        "MasterData": [],
        "Data": {
            "Datasets": [],
            "WorkProductComponents": [sra, cra, pdo, ptr],
            "WorkProducts": [],
        },
    }

    out = Path(args.manifest)
    out.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"DG2 Documents manifest written \u2192 {out}")
    for doc in [sra, cra, pdo, ptr]:
        print(f"  {doc['id']}")


if __name__ == "__main__":
    main()
