#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_businessdecision_drogon.py — Generate a BusinessDecision manifest for
Drogon DG1 (Decision Gate 1 — Identify & Assess).

Reads:
  manifest_masterwp_drogon.json    — Reservoir ID
  manifest_wpcraw_drogon.json      — Raw REV WPC ID
  manifest_wpcstat_drogon.json     — Statistics REV WPC ID
  manifest_wpcparams_drogon.json   — ColumnBasedTable WPC ID (parameters)
  manifest_risk_drogon.json        — Risk IDs

Output:
  manifest_bd_drogon.json

Usage:
  py demo/drogon/gen_businessdecision_drogon.py
"""

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

SCRIPT_DIR = Path(__file__).resolve().parent

DEFAULT_ACL = {
    "owners":  ["data.default.owners@dev.dataservices.energy"],
    "viewers": ["data.office.global.viewers@dev.dataservices.energy"],
}
DEFAULT_LEGAL = {
    "legaltags": ["dev-equinor-private-default"],
    "otherRelevantDataCountries": ["NO"],
}


def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _find_id(manifest: Dict, kind_fragment: str) -> str:
    """Find the first record ID whose kind contains kind_fragment."""
    for md in manifest.get("MasterData", []):
        if kind_fragment in md.get("kind", ""):
            return md["id"]
    for wpc in manifest.get("Data", {}).get("WorkProductComponents", []):
        if kind_fragment in wpc.get("kind", ""):
            return wpc["id"]
    return ""


def _find_all_ids(manifest: Dict, kind_fragment: str) -> List[str]:
    ids = []
    for md in manifest.get("MasterData", []):
        if kind_fragment in md.get("kind", ""):
            ids.append(md["id"])
    return ids


def main():
    ap = argparse.ArgumentParser(description="Generate Drogon DG1 BusinessDecision manifest")
    ap.add_argument("--masterwp",  default=str(SCRIPT_DIR / "manifest_masterwp_drogon.json"))
    ap.add_argument("--rawvol",    default=str(SCRIPT_DIR / "manifest_wpcraw_drogon.json"))
    ap.add_argument("--statvol",   default=str(SCRIPT_DIR / "manifest_wpcstat_drogon.json"))
    ap.add_argument("--params",    default=str(SCRIPT_DIR / "manifest_wpcparams_drogon.json"))
    ap.add_argument("--risks",     default=str(SCRIPT_DIR / "manifest_risk_drogon.json"))
    ap.add_argument("--manifest",  default=str(SCRIPT_DIR / "manifest_bd_drogon.json"))
    ap.add_argument("--id-prefix", default="dev")
    args = ap.parse_args()

    masterwp = load_json(args.masterwp)
    rawvol   = load_json(args.rawvol)
    statvol  = load_json(args.statvol)
    params   = load_json(args.params)
    risks    = load_json(args.risks)

    reservoir_id = _find_id(masterwp, "master-data--Reservoir:")
    raw_wpc_id   = _find_id(rawvol, "ReservoirEstimatedVolumes")
    stat_wpc_id  = _find_id(statvol, "ReservoirEstimatedVolumes")
    params_wpc_id = _find_id(params, "ColumnBasedTable")
    risk_ids     = _find_all_ids(risks, "master-data--Risk:")

    bd_id = f"{args.id_prefix}:master-data--BusinessDecision:Drogon-DG1-Identify:1"

    bd_record = {
        "id":    bd_id,
        "kind":  "osdu:wks:master-data--BusinessDecision:1.0.0",
        "acl":   DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": "Drogon — Decision Gate 1 DG1 Identify & Assess",
            "ProjectName": "Drogon Field Development",
            "DecisionLevelID": f"{args.id_prefix}:reference-data--DecisionLevel:DG1:1",
            "ApprovalStatusID": f"{args.id_prefix}:reference-data--DecisionApprovalStatus:Pending:1",
            "DecisionDueDate": "2026-06-30",
            "DecisionSummary": (
                "Evaluate the Valysar formation of the Drogon field. "
                "Assess in-place volumes (oil + gas) across 7 reservoir segments "
                "with facies-dependent porosity uncertainty. "
                "Determine whether to proceed to DG2 Concept Select."
            ),
            "RiskIDs": risk_ids,
            "PriorActivityIDs": [x for x in [raw_wpc_id, stat_wpc_id, params_wpc_id] if x],
            "Parameters": [
                {
                    "Title": "Raw volumes (per realisation)",
                    "Selection": "Raw per-realisation volumes feeding the statistical summary",
                    "ParameterKindID": f"{args.id_prefix}:reference-data--ParameterKind:DataObject:1",
                    "ParameterRoleID": f"{args.id_prefix}:reference-data--ParameterRole:Input:1",
                    "DataObjectParameter": raw_wpc_id,
                    "Keys": [
                        {"ParameterKey": "artifact", "StringParameterKey": "REV-raw"},
                    ],
                },
                {
                    "Title": "Statistical volumes (P10/P50/P90)",
                    "Selection": "Aggregated statistics used for the DG1 assessment",
                    "ParameterKindID": f"{args.id_prefix}:reference-data--ParameterKind:DataObject:1",
                    "ParameterRoleID": f"{args.id_prefix}:reference-data--ParameterRole:Input:1",
                    "DataObjectParameter": stat_wpc_id,
                    "Keys": [
                        {"ParameterKey": "artifact", "StringParameterKey": "REV-stats"},
                    ],
                },
                {
                    "Title": "Valysar parameters (OWC, porosity)",
                    "Selection": "Per-segment, per-facies input parameters",
                    "ParameterKindID": f"{args.id_prefix}:reference-data--ParameterKind:DataObject:1",
                    "ParameterRoleID": f"{args.id_prefix}:reference-data--ParameterRole:Input:1",
                    "DataObjectParameter": params_wpc_id,
                    "Keys": [
                        {"ParameterKey": "artifact", "StringParameterKey": "ColumnBasedTable-params"},
                    ],
                },
                {
                    "Title": "Reservoir scope",
                    "Selection": "Master-data context for the decision",
                    "ParameterKindID": f"{args.id_prefix}:reference-data--ParameterKind:DataObject:1",
                    "ParameterRoleID": f"{args.id_prefix}:reference-data--ParameterRole:InputReference:1",
                    "DataObjectParameter": reservoir_id,
                },
            ],
            "ext": {
                "equinor": {
                    "Alternatives": [
                        {
                            "Name": "Proceed to DG2 with full 7-segment development",
                            "Rank": 1,
                            "Rationale": (
                                "Static in-place volumes support commercial viability; "
                                "porosity risk manageable with appraisal data."
                            ),
                        },
                        {
                            "Name": "Reduced scope — focus on CentralHorst and CentralSouth",
                            "Rank": 2,
                            "Rationale": (
                                "Highest Oil concentrations in CentralHorst and CentralSouth; "
                                "de-risks early production but leaves upside for later phases."
                            ),
                        },
                    ],
                    "UncertaintySummary": {
                        "Basis": "FMU static in-place volumes from 3 uncertainty realisations",
                        "Note": "See stat WPC for full P10/P50/P90 breakdown per segment & facies",
                    },
                },
            },
        },
    }

    manifest = {
        "kind": "osdu:wks:Manifest:1.0.0",
        "ReferenceData": [],
        "MasterData": [bd_record],
        "Data": {
            "Datasets": [],
            "WorkProductComponents": [],
            "WorkProducts": [],
        },
    }

    Path(args.manifest).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"BusinessDecision manifest written → {args.manifest}")
    print(f"  BD ID        : {bd_id}")
    print(f"  Reservoir ref: {reservoir_id}")
    print(f"  Raw REV ref  : {raw_wpc_id}")
    print(f"  Stat REV ref : {stat_wpc_id}")
    print(f"  Params ref   : {params_wpc_id}")
    print(f"  Stat WPC ref : {stat_wpc_id}")
    print(f"  Risk refs    : {risk_ids}")


if __name__ == "__main__":
    main()
