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


from _shared import load_json  # noqa: E402


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
            "Name": "Drogon \u2014 Decision Gate 1 DG1 Identify & Assess",
            "Description": (
                "DG1 evaluation of the Valysar fluvial formation in the Drogon field, "
                "covering static in-place volume estimation across 7 reservoir segments "
                "(NorthSea, NorthHorst, CentralHorst, CentralFlanks, CentralSouth, "
                "SouthWing, EastLobe) with three facies types (Channel, Crevasse, "
                "Floodplain). The assessment uses FMU-driven uncertainty realisations "
                "to derive P10/P50/P90 oil and gas volumes, forming the basis for the "
                "DG2 Concept Select recommendation."
            ),
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
                    "Authors": [
                        {
                            "Name": "Kristin Haugen",
                            "Role": "Geoscience Lead",
                            "Organisation": "Drogon Subsurface",
                        },
                        {
                            "Name": "Henrik Bjørnstad",
                            "Role": "Reservoir Engineer",
                            "Organisation": "Drogon Reservoir Management",
                        },
                        {
                            "Name": "Anna-Lise Tveit",
                            "Role": "Petrophysicist",
                            "Organisation": "Drogon Petec",
                        },
                        {
                            "Name": "Erik Stensrud",
                            "Role": "Geologist / FMU Lead",
                            "Organisation": "Drogon Geomodelling",
                        },
                    ],
                    "ReviewTeam": {
                        "PreparedBy": {
                            "Name": "Erik Stensrud",
                            "Organisation": "Drogon Geomodelling",
                        },
                        "Responsible": {
                            "Name": "Kristin Haugen",
                            "Organisation": "Drogon Subsurface Lead",
                        },
                        "QARecommender": {
                            "Name": "Marte Nygaard",
                            "Organisation": "ST MSU Subsurface QA",
                        },
                        "ApprovedBy": {
                            "Name": "Lars Kongsvik",
                            "Organisation": "Drogon Project Director",
                        },
                    },
                    "Alternatives": [
                        {
                            "Name": "Proceed to DG2 with full 7-segment development",
                            "Rank": 1,
                            "Rationale": (
                                "Static in-place volumes support commercial viability "
                                "across all 7 segments; porosity risk manageable with "
                                "appraisal data. Full scope maximises resource capture "
                                "from CentralHorst (highest Oil concentration) through EastLobe."
                            ),
                            "RecommendedAction": "Approve",
                        },
                        {
                            "Name": "Reduced scope \u2014 focus on CentralHorst and CentralSouth",
                            "Rank": 2,
                            "Rationale": (
                                "CentralHorst and CentralSouth carry the highest Oil density "
                                "and lowest porosity uncertainty (Channel facies dominant). "
                                "De-risks early production but leaves ~40% of upside for "
                                "later phases."
                            ),
                            "RecommendedAction": "Consider",
                        },
                        {
                            "Name": "Defer \u2014 acquire additional appraisal data",
                            "Rank": 3,
                            "Rationale": (
                                "Floodplain facies porosity (avg 0.10) and cementation "
                                "effects in deeper segments remain poorly constrained. "
                                "Additional core data from NorthSea and EastLobe segments "
                                "would reduce volume uncertainty range before committing to DG2."
                            ),
                            "RecommendedAction": "Fallback",
                        },
                    ],
                    "DevelopmentConcept": {
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
                    "ReservoirProperties": {
                        "FormationName": "Valysar",
                        "NumberOfSegments": 7,
                        "Segments": [
                            "NorthSea", "NorthHorst", "CentralHorst",
                            "CentralFlanks", "CentralSouth", "SouthWing", "EastLobe",
                        ],
                        "FaciesTypes": ["Channel", "Crevasse", "Floodplain"],
                        "AveragePorosity_Channel": 0.28,
                        "AveragePorosity_Crevasse": 0.21,
                        "AveragePorosity_Floodplain": 0.10,
                        "NetToGross": 0.85,
                        "OWC_m_TVDSS": 1710,
                        "ReservoirTemperature_degC": 72,
                        "ReservoirPressure_bara": 170,
                    },
                    "KeyUncertainties": [
                        {
                            "Factor": "Facies-dependent porosity",
                            "Impact": "High",
                            "Description": (
                                "Porosity varies 0.10\u20130.28 across facies; Channel-dominant "
                                "segments (CentralHorst) have higher confidence than "
                                "Floodplain-rich segments (NorthSea, EastLobe)."
                            ),
                        },
                        {
                            "Factor": "OWC depth and aquifer support",
                            "Impact": "Medium",
                            "Description": (
                                "OWC modelled at 1710 m TVDSS with \u00b115 m uncertainty; "
                                "deeper OWC would increase STOIIP but also water production risk."
                            ),
                        },
                        {
                            "Factor": "Cementation and diagenesis",
                            "Impact": "Medium",
                            "Description": (
                                "Deeper segments show evidence of diagenetic cementation "
                                "reducing effective porosity and permeability, particularly "
                                "in Crevasse facies."
                            ),
                        },
                    ],
                    "UncertaintySummary": {
                        "Basis": (
                            "FMU static in-place volumes from 3 uncertainty realisations "
                            "across 7 segments and 3 facies types"
                        ),
                        "Note": (
                            "See stat WPC for full P10/P50/P90 breakdown per segment "
                            "& facies. Volume Unit: m\u00b3."
                        ),
                        "TotalRealisations": 3,
                        "MethodologyReference": "FMU Level 2 static uncertainty workflow (Valysar geomodel v1)",
                    },
                    "DG2Recommendations": [
                        "Implement Level 3 FMU uncertainty workflow with increased realisation count (target 50+) for DG2",
                        "Acquire additional core data from NorthSea and EastLobe segments to reduce porosity uncertainty",
                        "Evaluate seismic reprocessing for improved depth conversion of Valysar top reservoir",
                        "Conduct cross-discipline review of OWC sensitivity on recovery factor estimates",
                    ],
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
