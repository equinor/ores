#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_documents_drogon.py — Generate placeholder Document WPC records for
the Drogon DG1 decision gate package.

Creates:
  work-product-component--Document  "Drogon — Subsurface Risk Assessment (SRA)"
  work-product-component--Document  "Drogon — Cost Risk Assessment (CRA)"
  work-product-component--Document  "Drogon — Plan for Development and Operation (PDO)"

These are stub records (no file blob attached) that serve as typed
references from the BusinessDecision Parameters[] and
RiskAssessmentDocument fields.

Output:
  manifest_documents_drogon.json

Usage:
  py demo/drogon/gen_documents_drogon.py
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
    ap = argparse.ArgumentParser(description="Generate Drogon Document WPC manifest")
    ap.add_argument("--manifest", default=str(SCRIPT_DIR / "manifest_documents_drogon.json"))
    ap.add_argument("--id-prefix", default="dev")
    args = ap.parse_args()

    prefix = args.id_prefix

    sra_id = f"{prefix}:work-product-component--Document:Drogon-SRA-DG1-Report:1"
    cra_id = f"{prefix}:work-product-component--Document:Drogon-CRA-DG1-Report:1"
    pdo_id = f"{prefix}:work-product-component--Document:Drogon-PDO-Draft:1"

    sra_record = {
        "id":    sra_id,
        "kind":  "osdu:wks:work-product-component--Document:1.2.0",
        "acl":   DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": "Drogon \u2014 Subsurface Risk Assessment (SRA) DG1",
            "Description": (
                "Schedule Risk Assessment for the Drogon field development DG1 gate. "
                "Covers subsea installation, FPSO modification, drilling campaign, "
                "and commissioning timeline. Monte Carlo schedule analysis indicates "
                "P50 first oil June 2028, P90 first oil March 2029. Key risk drivers: "
                "FPSO drydock slot availability and subsea template fabrication lead time."
            ),
            "DocumentType": "SRA",
            "DocumentDate": "2026-02-15",
        },
    }

    cra_record = {
        "id":    cra_id,
        "kind":  "osdu:wks:work-product-component--Document:1.2.0",
        "acl":   DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": "Drogon \u2014 Cost Risk Assessment (CRA) DG1",
            "Description": (
                "Cost Risk Assessment for the Drogon field development DG1 gate. "
                "Probabilistic cost estimate covering subsea CAPEX, FPSO modifications, "
                "drilling, and project management. P50 CAPEX estimate 8,200 MNOK; "
                "P90 CAPEX estimate 10,100 MNOK. Main cost drivers: drilling duration "
                "uncertainty (12\u201316 wells depending on compartmentalisation) and "
                "FPSO water treatment module scope."
            ),
            "DocumentType": "CRA",
            "DocumentDate": "2026-02-15",
        },
    }

    pdo_record = {
        "id":    pdo_id,
        "kind":  "osdu:wks:work-product-component--Document:1.2.0",
        "acl":   DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": "Drogon \u2014 Plan for Development and Operation (PDO) Draft",
            "Description": (
                "Draft PDO document for the Drogon field development, prepared for "
                "DG1 preliminary assessment. Covers field description, development "
                "concept (subsea tie-back to FPSO), preliminary well planning, "
                "environmental impact overview, and regulatory framework alignment "
                "with Norwegian Petroleum Safety Authority (PSA) and Ministry of "
                "Petroleum and Energy (MPE) requirements."
            ),
            "DocumentType": "PDO",
            "DocumentDate": "2026-03-01",
        },
    }

    manifest = {
        "kind": "osdu:wks:Manifest:1.0.0",
        "ReferenceData": [],
        "MasterData": [],
        "Data": {
            "Datasets": [],
            "WorkProductComponents": [sra_record, cra_record, pdo_record],
            "WorkProducts": [],
        },
    }

    Path(args.manifest).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Documents manifest written \u2192 {args.manifest}")
    print(f"  SRA ID : {sra_id}")
    print(f"  CRA ID : {cra_id}")
    print(f"  PDO ID : {pdo_id}")


if __name__ == "__main__":
    main()
