#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_businessdecision_dg2.py — Generate a BusinessDecision manifest for
Drogon DG2 (Decision Gate 2 — Concept Select).

This is the enriched DG2 record including elements not present at DG1:
  - KeyEconomics (NPV, IRR, CAPEX, OPEX, Breakeven, Payback)
  - ScheduleMilestones (7 milestones from DG2 through plateau)
  - ProductionProfile (20-year forecast with oil/gas/water/cum/RF)
  - Enriched DevelopmentConcept (host facility, flowlines, IOR, well plan)
  - Per-alternative economics in Alternatives[]
  - Document references in Parameters[] (SRA, CRA, PDO, PTR)
  - VolumesSummary with recoverable volumes
  - Extended UncertaintySummary with StaticInPlace AND Recoverable
  - 4 risks (porosity, fault, HSE, schedule)

Reads (from DG1 folder — shared master data):
  ../drogon/manifest_masterwp_drogon.json   — Reservoir ID, acl, legal

Reads (from DG2 folder — DG2-specific volume tables with ×0.8 porosity):
  manifest_wpcraw_dg2.json      — DG2 Raw REV WPC ID (volumes ×0.8)
  manifest_wpcstat_dg2.json     — DG2 Statistics REV WPC ID
  manifest_wpcparams_dg2.json   — DG2 ColumnBasedTable WPC ID (porosity ×0.8)
  manifest_activity_dg2.json    — DG2 Activity WPC ID
  manifest_risk_dg2.json        — Risk IDs (4 risks)
  manifest_documents_dg2.json   — Document IDs (SRA, CRA, PDO, PTR)

Output:
  manifest_bd_dg2.json

Usage:
  py demo/drogon_dg2/gen_businessdecision_dg2.py
"""

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

SCRIPT_DIR = Path(__file__).resolve().parent       # demo/drogon_dg2
DG1_DIR    = SCRIPT_DIR.parent / "drogon"           # demo/drogon

import sys
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
    for wpc in manifest.get("Data", {}).get("WorkProductComponents", []):
        if kind_fragment in wpc.get("kind", ""):
            ids.append(wpc["id"])
    return ids


def main():
    ap = argparse.ArgumentParser(description="Generate Drogon DG2 BusinessDecision manifest")
    # DG1 shared master data
    ap.add_argument("--masterwp",  default=str(DG1_DIR / "manifest_masterwp_drogon.json"))
    # DG2-specific volume tables (×0.8 porosity)
    ap.add_argument("--rawvol",    default=str(SCRIPT_DIR / "manifest_wpcraw_dg2.json"))
    ap.add_argument("--statvol",   default=str(SCRIPT_DIR / "manifest_wpcstat_dg2.json"))
    ap.add_argument("--params",    default=str(SCRIPT_DIR / "manifest_wpcparams_dg2.json"))
    ap.add_argument("--activity",  default=str(SCRIPT_DIR / "manifest_activity_dg2.json"))
    # DG2-specific risks & documents
    ap.add_argument("--risks",     default=str(SCRIPT_DIR / "manifest_risk_dg2.json"))
    ap.add_argument("--documents", default=str(SCRIPT_DIR / "manifest_documents_dg2.json"))
    ap.add_argument("--production", default=str(SCRIPT_DIR / "manifest_wpc_production_dg2.json"))
    ap.add_argument("--devconcept", default=str(SCRIPT_DIR / "manifest_devconcept_dg2.json"))
    ap.add_argument("--manifest",  default=str(SCRIPT_DIR / "manifest_bd_dg2.json"))
    ap.add_argument("--id-prefix", default="dev")
    args = ap.parse_args()

    pfx = args.id_prefix

    # ── Load shared master data + DG2 volume manifests ────────────────
    masterwp = load_json(args.masterwp)
    rawvol   = load_json(args.rawvol)
    statvol  = load_json(args.statvol)
    params   = load_json(args.params)
    risks    = load_json(args.risks)

    # Activity (from DG1)
    activity_id = ""
    if Path(args.activity).exists():
        act_man = load_json(args.activity)
        activity_id = _find_id(act_man, "work-product-component--Activity:")

    # DG2 documents
    doc_ids: Dict[str, str] = {}
    if Path(args.documents).exists():
        doc_man = load_json(args.documents)
        for wpc in doc_man.get("Data", {}).get("WorkProductComponents", []):
            rid = wpc.get("id", "")
            if "SRA" in rid:
                doc_ids["sra"] = rid
            elif "CRA" in rid:
                doc_ids["cra"] = rid
            elif "PDO" in rid:
                doc_ids["pdo"] = rid
            elif "PTR" in rid:
                doc_ids["ptr"] = rid

    reservoir_id  = _find_id(masterwp, "master-data--Reservoir:")
    raw_wpc_id    = _find_id(rawvol,   "ReservoirEstimatedVolumes")
    stat_wpc_id   = _find_id(statvol,  "ReservoirEstimatedVolumes")
    params_wpc_id = _find_id(params,   "ColumnBasedTable")
    risk_ids      = _find_all_ids(risks, "master-data--Risk:")

    # PP WPC manifest
    pp_wpc_id = ""
    if Path(args.production).exists():
        pp_wpc_id = _find_id(load_json(args.production), "ColumnBasedTable")

    # DevelopmentConcept WPC manifest
    devconcept_wpc_id = ""
    if Path(args.devconcept).exists():
        devconcept_wpc_id = _find_id(load_json(args.devconcept), "DevelopmentConcept")

    # Reference to DG1 BD (prior decision gate)
    dg1_bd_id = f"{pfx}:master-data--BusinessDecision:Drogon-DG1-Identify:1"

    # ETP dataspace for RESQML artefacts
    dataspace_id = f"{pfx}:dataset--ETPDataspace:maap-drogon_dg:1"

    # ── Build DG2 BusinessDecision ───────────────────────────────────
    bd_id = f"{pfx}:master-data--BusinessDecision:Drogon-DG2-ConceptSelect:1"

    bd_record = {
        "id":    bd_id,
        "kind":  "osdu:wks:master-data--BusinessDecision:1.0.0",
        "acl":   DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": "Drogon \u2014 Decision Gate 2 DG2 Concept Select",
            "Description": (
                "DG2 Concept Select for the Drogon field development. Valysar fluvial "
                "formation across 7 reservoir segments (NorthSea, NorthHorst, CentralHorst, "
                "CentralFlanks, CentralSouth, SouthWing, EastLobe) with three facies types "
                "(Channel, Crevasse, Floodplain). Revised petrophysical interpretation: "
                "porosity reduced by factor 0.8 based on core analysis and thin sections. "
                "50 FMU realisations quantify STOIIP uncertainty: "
                "P90 33.8 / P50 45.4 / P10 59.4 MSm\u00b3 oil in-place. "
                "Recoverable oil (P50) 14.8 MSm\u00b3 at 32.5% recovery factor. "
                "Recommended concept: subsea tie-back to FPSO with 2\u00d74-slot templates, "
                "12 production wells. NPV@10% 520 MUSD, CAPEX 8,500 MNOK, first oil 2028-H1."
            ),
            "ProjectName": "Drogon Field Development",
            "DecisionLevelID": f"{pfx}:reference-data--DecisionLevel:DG2:1",
            "ApprovalStatusID": f"{pfx}:reference-data--DecisionApprovalStatus:Pending:1",
            "DecisionDueDate": "2026-06-30",
            "DecisionSummary": (
                "Approve subsea tie-back development concept. Two 4-slot templates (8 slots), "
                "12 wells targeting full 7-segment Valysar scope. Reference case STOIIP "
                "45.4 MSm\u00b3 (P90 33.8, P10 59.4) — revised porosity interpretation ×0.8. "
                "Recoverable oil P50 14.8 MSm\u00b3 (RF 32.5%). "
                "First oil target 2028-H1. Proceed to DG3 FEED."
            ),
            "RiskAssessmentDocument": doc_ids.get("sra", ""),
            "RiskIDs": risk_ids,
            "PriorActivityIDs": (
                [activity_id] if activity_id
                else [x for x in [raw_wpc_id, stat_wpc_id, params_wpc_id] if x]
            ),
            "Parameters": _build_parameters(
                pfx, raw_wpc_id, stat_wpc_id, params_wpc_id,
                reservoir_id, dataspace_id, dg1_bd_id, doc_ids,
                pp_wpc_id, devconcept_wpc_id,
            ),
            # ── Canonical fields (survive OSDU ingestion) ──
            **_build_canonical_fields(pfx),
            "ancestry": {
                "parents": [activity_id] if activity_id else [],
                "children": [],
            },
            "ext": {
                "equinor": _build_ext_equinor(pfx, risk_ids),
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

    out = Path(args.manifest)
    out.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"DG2 BusinessDecision manifest written \u2192 {out}")
    print(f"  BD ID        : {bd_id}")
    print(f"  Reservoir ref: {reservoir_id}")
    print(f"  Raw REV ref  : {raw_wpc_id}")
    print(f"  Stat REV ref : {stat_wpc_id}")
    print(f"  Params ref   : {params_wpc_id}")
    print(f"  Risk refs    : {risk_ids}")
    print(f"  Doc refs     : {list(doc_ids.values())}")


# ─────────────────────────────────────────────────────────────────────
# Parameters[] — typed references to evidence artefacts
# ─────────────────────────────────────────────────────────────────────

def _build_parameters(
    pfx: str,
    raw_wpc_id: str, stat_wpc_id: str, params_wpc_id: str,
    reservoir_id: str, dataspace_id: str, dg1_bd_id: str,
    doc_ids: Dict[str, str],
    pp_wpc_id: str = "",
    devconcept_wpc_id: str = "",
) -> List[Dict[str, Any]]:
    params: List[Dict[str, Any]] = [
        {
            "Title": "Raw volumes (per realisation)",
            "Selection": "Raw per-realisation volumes feeding the statistical summary",
            "ParameterKindID": f"{pfx}:reference-data--ParameterKind:DataObject:1",
            "ParameterRoleID": f"{pfx}:reference-data--ParameterRole:Input:1",
            "DataObjectParameter": raw_wpc_id,
            "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "REV-raw"}],
        },
        {
            "Title": "Statistical volumes (P10/P50/P90)",
            "Selection": "Aggregated statistics used for the DG2 concept selection",
            "ParameterKindID": f"{pfx}:reference-data--ParameterKind:DataObject:1",
            "ParameterRoleID": f"{pfx}:reference-data--ParameterRole:Input:1",
            "DataObjectParameter": stat_wpc_id,
            "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "REV-stats"}],
        },
        {
            "Title": "Valysar parameters (OWC, porosity)",
            "Selection": "Per-segment, per-facies input parameters",
            "ParameterKindID": f"{pfx}:reference-data--ParameterKind:DataObject:1",
            "ParameterRoleID": f"{pfx}:reference-data--ParameterRole:Input:1",
            "DataObjectParameter": params_wpc_id,
            "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "ColumnBasedTable-params"}],
        },
        {
            "Title": "Reservoir scope",
            "Selection": "Master-data context for the decision",
            "ParameterKindID": f"{pfx}:reference-data--ParameterKind:DataObject:1",
            "ParameterRoleID": f"{pfx}:reference-data--ParameterRole:InputReference:1",
            "DataObjectParameter": reservoir_id,
        },
        {
            "Title": "GeoModelDataspace",
            "Selection": "RDDMS ETP dataspace with the Drogon DG2 geomodel EPC files",
            "ParameterKindID": f"{pfx}:reference-data--ParameterKind:DataObject:1",
            "ParameterRoleID": f"{pfx}:reference-data--ParameterRole:InputReference:1",
            "DataObjectParameter": dataspace_id,
            "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "ETPDataspace"}],
        },
        {
            "Title": "Prior gate (DG1 Identify & Assess)",
            "Selection": "DG1 decision record for the Drogon field",
            "ParameterKindID": f"{pfx}:reference-data--ParameterKind:DataObject:1",
            "ParameterRoleID": f"{pfx}:reference-data--ParameterRole:InputReference:1",
            "DataObjectParameter": dg1_bd_id,
            "Keys": [{"ParameterKey": "gate", "StringParameterKey": "DG1"}],
        },
    ]
    # Document references
    doc_entries = [
        ("SRA report",                 "sra"),
        ("CRA report",                 "cra"),
        ("PDO (draft)",                "pdo"),
        ("Petroleum Technology Report", "ptr"),
    ]
    for title, key in doc_entries:
        did = doc_ids.get(key)
        if did:
            params.append({
                "Title": title,
                "ParameterKindID": f"{pfx}:reference-data--ParameterKind:DataObject:1",
                "ParameterRoleID": f"{pfx}:reference-data--ParameterRole:InputReference:1",
                "DataObjectParameter": did,
            })
    # Production Forecast WPC reference
    if pp_wpc_id:
        params.append({
            "Title": "Production Forecast (20-year)",
            "Selection": "Reference case forecast from dynamic simulation (revised porosity ×0.8)",
            "ParameterKindID": f"{pfx}:reference-data--ParameterKind:DataObject:1",
            "ParameterRoleID": f"{pfx}:reference-data--ParameterRole:Input:1",
            "DataObjectParameter": pp_wpc_id,
            "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "ProductionForecast"}],
        })
    # DevelopmentConcept WPC reference
    if devconcept_wpc_id:
        params.append({
            "Title": "Development Concept",
            "Selection": "DG2 development concept definition",
            "ParameterKindID": f"{pfx}:reference-data--ParameterKind:DataObject:1",
            "ParameterRoleID": f"{pfx}:reference-data--ParameterRole:Input:1",
            "DataObjectParameter": devconcept_wpc_id,
            "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "DevelopmentConcept"}],
        })
    return params


# ─────────────────────────────────────────────────────────────────────
# Canonical BD fields (survive OSDU ingestion)
# ─────────────────────────────────────────────────────────────────────

def _build_canonical_fields(pfx: str) -> Dict[str, Any]:
    """Return canonical data.* fields mapped from ext.equinor concepts."""
    return {
        # ── Personnel[] ← Authors ──
        "Personnel": [
            {"Name": "Kristin Haugen",   "ProjectRoleID": f"{pfx}:reference-data--ProjectRole:GeoscienceLead:1",   "Organisation": "Drogon Subsurface"},
            {"Name": "Henrik Bjørnstad", "ProjectRoleID": f"{pfx}:reference-data--ProjectRole:ReservoirEngineer:1", "Organisation": "Drogon Reservoir Management"},
            {"Name": "Anna-Lise Tveit",  "ProjectRoleID": f"{pfx}:reference-data--ProjectRole:Petrophysicist:1",   "Organisation": "Drogon Petec"},
            {"Name": "Erik Stensrud",    "ProjectRoleID": f"{pfx}:reference-data--ProjectRole:FMULead:1",           "Organisation": "Drogon Geomodelling"},
            {"Name": "Silje Vik",        "ProjectRoleID": f"{pfx}:reference-data--ProjectRole:FacilitiesEngineer:1","Organisation": "Drogon Concept"},
            {"Name": "Olav Mæland",      "ProjectRoleID": f"{pfx}:reference-data--ProjectRole:DrillingWellsLead:1", "Organisation": "Drogon D&W"},
        ],
        # ── DecisionOwners/Makers/Contributors[] ← ReviewTeam ──
        "DecisionOwners": [
            {"Name": "Kristin Haugen", "Organisation": "Drogon Subsurface Lead"},
        ],
        "DecisionMakers": [
            {"Name": "Lars Kongsvik", "Organisation": "Drogon Project Director"},
        ],
        "Contributors": [
            {"Name": "Erik Stensrud", "Organisation": "Drogon Geomodelling"},
            {"Name": "Marte Nygaard", "Organisation": "ST MSU Subsurface QA"},
            {"Name": "Trond Berge",   "Organisation": "Drogon QRM Manager"},
        ],
        # ── Remarks[] ← Recommendations ──
        "Remarks": [
            {"Remark": r, "RemarkSource": "DG2 Recommendations"}
            for r in [
                "Execute FEED for FPSO conversion and subsea installation scope",
                "Secure FPSO drydock slot (2027-Q4 target) with dual-yard tendering strategy",
                "Drill NorthHorst appraisal sidetrack to constrain fault compartmentalisation model",
                "Finalise Phase 2 water injection well locations based on DG3 dynamic simulation",
                "Complete EIA with cold-water coral avoidance routing for flowline corridor",
                "Run Level 3+ FMU workflow with 100+ realisations for DG3 volumetric basis",
                "Prepare PDO final draft for MPE submission post-FID",
            ]
        ],
        # ── ProjectSpecifications[] ← KeyEconomics ──
        "ProjectSpecifications": [
            {"ParameterTypeID": f"{pfx}:reference-data--ParameterType:NPV_10pct:1",      "DataQuantityParameter": 520,  "UnitOfMeasureID": f"{pfx}:reference-data--UnitOfMeasure:MUSD:1"},
            {"ParameterTypeID": f"{pfx}:reference-data--ParameterType:IRR:1",             "DataQuantityParameter": 17,   "UnitOfMeasureID": f"{pfx}:reference-data--UnitOfMeasure:percent:1"},
            {"ParameterTypeID": f"{pfx}:reference-data--ParameterType:CAPEX:1",           "DataQuantityParameter": 8500, "UnitOfMeasureID": f"{pfx}:reference-data--UnitOfMeasure:MNOK:1"},
            {"ParameterTypeID": f"{pfx}:reference-data--ParameterType:OPEX_pa:1",         "DataQuantityParameter": 420,  "UnitOfMeasureID": f"{pfx}:reference-data--UnitOfMeasure:MNOK:1"},
            {"ParameterTypeID": f"{pfx}:reference-data--ParameterType:BreakevenOil:1",    "DataQuantityParameter": 42,   "UnitOfMeasureID": f"{pfx}:reference-data--UnitOfMeasure:USDperbbl:1"},
            {"ParameterTypeID": f"{pfx}:reference-data--ParameterType:Payback:1",         "DataQuantityParameter": 7.0,  "UnitOfMeasureID": f"{pfx}:reference-data--UnitOfMeasure:years:1"},
        ],
        # ── ActivityStates[] ← ScheduleMilestones ──
        "ActivityStates": [
            {"EffectiveDateTime": "2026-02-28", "ActivityStatusID": f"{pfx}:reference-data--ActivityStatus:Completed:1", "Remark": "DG2 Concept Select"},
            {"EffectiveDateTime": "2027-01-01", "ActivityStatusID": f"{pfx}:reference-data--ActivityStatus:Planned:1",   "Remark": "DG3 FEED"},
            {"EffectiveDateTime": "2027-07-01", "ActivityStatusID": f"{pfx}:reference-data--ActivityStatus:Planned:1",   "Remark": "FID / DG4"},
            {"EffectiveDateTime": "2027-10-01", "ActivityStatusID": f"{pfx}:reference-data--ActivityStatus:Planned:1",   "Remark": "FPSO Drydock Start"},
            {"EffectiveDateTime": "2028-01-01", "ActivityStatusID": f"{pfx}:reference-data--ActivityStatus:Planned:1",   "Remark": "Subsea Installation"},
            {"EffectiveDateTime": "2028-06-01", "ActivityStatusID": f"{pfx}:reference-data--ActivityStatus:Planned:1",   "Remark": "First Oil"},
            {"EffectiveDateTime": "2029-01-01", "ActivityStatusID": f"{pfx}:reference-data--ActivityStatus:Planned:1",   "Remark": "Plateau Production"},
        ],
    }


# ─────────────────────────────────────────────────────────────────────
# ext.equinor — the enrichment payload
# ─────────────────────────────────────────────────────────────────────

def _build_ext_equinor(pfx: str, risk_ids: List[str]) -> Dict[str, Any]:
    return {

        # ── Alternatives with per-alternative economics ──────────────
        "Alternatives": [
            {
                "Name": "Alt-A: Subsea tie-back to FPSO (2\u00d74-slot templates)",
                "Rank": 1,
                "Rationale": (
                    "Highest NPV; leverages planned FPSO conversion for Drogon area. "
                    "12 wells across 7 segments, 2\u00d74-slot templates with 2 contingent "
                    "slots for infill. Subsea boosting pump included for low-pressure "
                    "phase. Modular water treatment allows staged capacity expansion."
                ),
                "RecommendedAction": "Approve",
                "NPV_10pct_MUSD": 520,
                "CAPEX_MNOK": 8500,
                "IRR_pct": 17,
            },
            {
                "Name": "Alt-B: Reduced scope \u2014 CentralHorst + CentralSouth only",
                "Rank": 2,
                "Rationale": (
                    "Focus on the two highest-confidence segments (Channel facies "
                    "dominant, lowest porosity uncertainty). 6 wells, single 4-slot "
                    "template + 2 satellite wells. Lower investment but captures "
                    "only ~55% of recoverable resource. Provides first-oil option "
                    "if FPSO schedule slips."
                ),
                "RecommendedAction": "Consider",
                "NPV_10pct_MUSD": 300,
                "CAPEX_MNOK": 4800,
                "IRR_pct": 20,
            },
            {
                "Name": "Alt-C: Defer \u2014 acquire DG3-quality appraisal data",
                "Rank": 3,
                "Rationale": (
                    "NorthHorst and EastLobe fault compartmentalisation remains "
                    "poorly constrained. Additional well test data (est. 12 months, "
                    "200 MNOK) would reduce dynamic uncertainty range by ~40%. "
                    "Risk of losing FPSO drydock window if deferred beyond 2026-Q3."
                ),
                "RecommendedAction": "Fallback",
                "NPV_10pct_MUSD": None,
                "CAPEX_MNOK": None,
                "IRR_pct": None,
            },
        ],

        # ── Uncertainty Summary (enriched with recoverable) ──────────
        "UncertaintySummary": {
            "Basis": (
                "FMU static + dynamic uncertainty from 50 geo-realisations across "
                "7 segments and 3 facies types. Porosity revised \u00d70.8 from DG1. "
                "Dynamic forecasts run on 3 selected realisations (P90/P50/P10) "
                "with 5 sensitivity cases each."
            ),
            "Note": (
                "See stat WPC for full P10/P50/P90 breakdown per segment & facies. "
                "Recoverable estimated from dynamic simulation with 12-producer base case."
            ),
            "TotalRealisations": 50,
            "SelectedRealisations": {
                "P90": "Real 42",
                "P50": "Real 1",
                "P10": "Real 17",
            },
            "MethodologyReference": "FMU Level 3 static + dynamic uncertainty workflow (Valysar geomodel v2)",
            "StaticInPlace_Oil_MSm3": {
                "P90": 33.8,
                "P50": 45.4,
                "P10": 59.4,
            },
            "Recoverable_Oil_MSm3": {
                "P90": 10.0,
                "P50": 14.8,
                "P10": 20.6,
            },
            "RecoveryFactor_pct": {
                "P90": 28.0,
                "P50": 32.5,
                "P10": 37.0,
            },
        },
    }


if __name__ == "__main__":
    main()
