#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_documents_dg2.py - Generate Document WPC records for the Drogon DG2
(Concept Select) decision gate package.

Creates:
  work-product-component--Document  "Drogon - Subsurface Risk Assessment (SRA) DG2"
  work-product-component--Document  "Drogon - Cost Risk Assessment (CRA) DG2"
  work-product-component--Document  "Drogon - Plan for Development and Operation (PDO) DG2"
  work-product-component--Document  "Drogon - Petroleum Technology Report (PTR) DG2"

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
    "viewers": ["data.default.viewers@dev.dataservices.energy"],
}
DEFAULT_LEGAL = {
    "legaltags": ["opendes-private-usa-default"],
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
            "Name": "Drogon - Schedule Risk Assessment (SRA) DG2",
            "Description": (
                "Schedule Risk Assessment for the Drogon field development DG2 "
                "Concept Select gate. Monte Carlo schedule analysis covering "
                "FPSO preparation, drilling campaign (6 development wells: "
                "A1\u2013A4 producers + A5\u2013A6 injectors), and commissioning. "
                "Phased well startup sequence from real Eclipse schedule: "
                "A1 (Jan 2018), A2 (Mar 2018), A5 injection (May 2018), "
                "A3+A4 (Sep 2018), A6 injection (Dec 2018). Key risk drivers: "
                "A4 horizontal multi-segment completion complexity, VFP table "
                "uncertainty, and water injection pump commissioning timeline."
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
            "Name": "Drogon - Cost Risk Assessment (CRA) DG2",
            "Description": (
                "Cost Risk Assessment for the Drogon field development DG2 Concept "
                "Select gate. Probabilistic cost estimate covering "
                "FPSO facility (eCalc model: ~9 MW baseload, WI pumps at 200 bar, "
                "gas compressor), drilling (6+2 contingent wells), "
                "and project management. Drilling cost range driven by: "
                "A4 horizontal well complexity (multi-segment, X-direction completions), "
                "sand control requirements (frac-pack + ICD), and potential "
                "Phase 2 infill wells depending on fault compartmentalisation."
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
            "Name": "Drogon - Plan for Development and Operation (PDO) DG2 Draft",
            "Description": (
                "Draft PDO for the Drogon DG2 Concept Select gate. Covers field "
                "description (Volantis Group, 3 zones, 7 fault-bounded regions), "
                "selected development concept (FPSO, 4 producers + 2 WI wells), "
                "STOIIP \u2248 34.5 MSm\u00b3, GIIP \u2248 1.0 GSm\u00b3 (NorthHorst gas cap, "
                "GOC 1640 m). Black-oil model (DISGAS+VAPOIL), ref. pressure 310 bar. "
                "Production forecast: peak 14,259 Sm\u00b3/d oil (Oct 2018), declining "
                "to ~2,900 Sm\u00b3/d at RF ~40%. LRAT-controlled prediction with WI "
                "at 6,500 Sm\u00b3/d per well to Jan 2025. Basis for DG3 FEED scope."
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
            "Name": "Drogon - Petroleum Technology Report (PTR) DG2",
            "Description": (
                "Petroleum Technology Report for DG2 Concept Select. Covers "
                "geomodelling (250 FMU realisations, one-by-one sensitivity design), "
                "APS facies model with seismic conditioning, 92\u00d7146\u00d769 simulation grid "
                "(10 properties: PHIT, KLOGH, KV, SW, SWL, SG, VSH, FACIES, REGION, ZONE), "
                "OPM Flow dynamic simulation with history matching. Observation data "
                "used for calibration: BHP (6 wells \u00d7 3 dates), WWCT and WGOR time-series "
                "(4 producers, 10 points each), PLT zone-level rates (A3\u2013A6 at Aug 2019), "
                "RFT pressure profiles (R_A2\u2013R_A6), 4D seismic amplitude maps "
                "(2018\u21922020), and 2 water tracers (WT1, WT2). Volumetric "
                "uncertainty (P10/P50/P90 STOIIP and recoverable) across 7 regions."
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
