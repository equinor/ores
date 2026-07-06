#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_businessdecision_omegas.py - Generate BusinessDecision manifest for
Omega Sør WPC (Well Planning Committee) decision.

Single BD covering both the production well and injector well:
  - 4 ranked Alternatives[] (base, depletion, WAG, defer)
  - 5 linked Risks
  - Economic KPIs (NPV, IRR, break-even, CAPEX)
  - Schedule milestones
  - Volume summary (STOIIP, recoverable, RF)
  - Parameters[] linking all evidence artifacts
  - Spatial area + CRS for search discoverability

Reads:
  manifest_master_omegas.json   - Reservoir/Well IDs
  manifest_volumes_omegas.json  - Volume WPC IDs
  manifest_risk_omegas.json     - Risk IDs

Output: manifest_bd_omegas.json

Usage:
  python demo/omegas/gen_businessdecision_omegas.py
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

from demo.eqn.omegas._shared import (
    SCRIPT_DIR, DEFAULT_ACL, DEFAULT_LEGAL, ID_PREFIX,
    SPATIAL_AREA_WGS84, PROJECT_CRS_ID, DATASPACE,
    FIELD_NAME, DISCOVERY_NAME, LICENCE, BLOCK, load_json,
)


def _find_id(manifest: Dict, kind_fragment: str) -> str:
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
    ap = argparse.ArgumentParser(description="Generate Omega Sør WPC BusinessDecision manifest")
    ap.add_argument("--master", default=str(SCRIPT_DIR / "manifest_master_omegas.json"))
    ap.add_argument("--volumes", default=str(SCRIPT_DIR / "manifest_volumes_omegas.json"))
    ap.add_argument("--risks", default=str(SCRIPT_DIR / "manifest_risk_omegas.json"))
    ap.add_argument("--manifest", default=str(SCRIPT_DIR / "manifest_bd_omegas.json"))
    ap.add_argument("--id-prefix", default=ID_PREFIX)
    args = ap.parse_args()

    pfx = args.id_prefix

    # ── Load input manifests ────────────────────────────────────────────
    master = load_json(args.master)
    volumes = load_json(args.volumes)
    risks = load_json(args.risks)

    reservoir_id = _find_id(master, "master-data--Reservoir:")
    well_prod_id = ""
    well_inj_id = ""
    for md in master.get("MasterData", []):
        if "Well:" in md.get("kind", ""):
            name = md.get("data", {}).get("Name", "")
            if "Producer" in name:
                well_prod_id = md["id"]
            elif "Injector" in name:
                well_inj_id = md["id"]

    stat_vol_id = _find_id(volumes, "ReservoirEstimatedVolumes")
    inplace_vol_id = _find_id(volumes, "ColumnBasedTable")
    risk_ids = _find_all_ids(risks, "master-data--Risk:")

    # ETP dataspace reference
    dataspace_id = f"{pfx}:dataset--ETPDataspace:maap-omegas:1"

    # Cross-references to CollaborationProject and collections (from gen_collection_omegas.py)
    collection_id = f"{pfx}:work-product-component--PersistedCollection:OmegaSor-WPC-Evidence:1"
    drilling_collection_id = f"{pfx}:work-product-component--PersistedCollection:OmegaSor-Drilling-Evidence:1"
    cp_id = f"{pfx}:master-data--CollaborationProject:OmegaSor-FieldDev:1"

    # ── Build BD record ─────────────────────────────────────────────────
    bd_id = f"{pfx}:master-data--BusinessDecision:OmegaSor-WPC:1"

    bd_record = {
        "id": bd_id,
        "kind": "osdu:wks:master-data--BusinessDecision:1.0.0",
        "acl": DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": "Omega Sør – WPC Well Planning Committee Decision",
            "Description": (
                "Well Planning Committee decision for the Omega Sør Alfa field "
                "development (Snorre area, block 34/4, PL057). Approve drilling of "
                "1 production well (CAP-X sidetrack from 34/4-19 S) and 1 water "
                "injection well (4-slot template) targeting Brent Group "
                "(Tarbert + Rannoch formations). Phase 1 of subsea tieback to "
                "Snorre N-template. STOIIP P50 19.3 MSm³, recoverable P50 5.4 MSm³, "
                "RF mean 28.5%. NPV 116 MUSD (EQN share), IRR 62%, break-even 25 USD/bbl."
            ),
            "ProjectName": f"{DISCOVERY_NAME} Field Development",
            "DecisionLevelID": f"{pfx}:reference-data--DecisionLevel:WPC:",
            "ApprovalStatusID": f"{pfx}:reference-data--DecisionApprovalStatus:Pending:",
            "DecisionDueDate": "2026-09-30",
            "DecisionSummary": (
                "Approve Phase 1 development wells: 1 producer (deep ST from "
                "34/4-19 S via CAP-X, perforated Tarbert+Rannoch) and 1 injector "
                "(from 4-slot template, perforated Tarbert only – base case). "
                "8\" production flowline, 6\" WI flowline, tieback to Snorre N-template. "
                "First oil Jan 2029. Critical dependency: pilot well to determine "
                "barium content and confirm OWC/Tarbert presence."
            ),
            "RiskIDs": risk_ids,
            "PriorActivityIDs": [x for x in [stat_vol_id, inplace_vol_id] if x],
            "ReservoirIDs": [reservoir_id],
            "ReservoirSegmentIDs": [
                f"{pfx}:master-data--ReservoirSegment:OmegaSor-Tarbert:1",
                f"{pfx}:master-data--ReservoirSegment:OmegaSor-Rannoch:1",
            ],
            "CollaborationProjectID": cp_id,
            "EvidenceCollectionID": collection_id,
            "DrillingEvidenceCollectionID": drilling_collection_id,
            "Parameters": _build_parameters(
                pfx, reservoir_id, stat_vol_id, inplace_vol_id,
                well_prod_id, well_inj_id, dataspace_id, risk_ids,
                collection_id, cp_id, drilling_collection_id,
            ),
            # ── Canonical fields ──
            **_build_canonical_fields(pfx),
            "SpatialArea": SPATIAL_AREA_WGS84,
            "CoordinateReferenceSystemID": PROJECT_CRS_ID,
            "ancestry": {
                "parents": [
                    # Prior exploration decision feeds into this WPC decision
                    f"{pfx}:master-data--BusinessDecision:OmegaSor-Exploration:1",
                ],
                "children": [well_prod_id, well_inj_id],
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
    print(f"BusinessDecision manifest written → {out}")
    print(f"  BD ID         : {bd_id}")
    print(f"  Reservoir ref : {reservoir_id}")
    print(f"  Stat vol ref  : {stat_vol_id}")
    print(f"  Risk refs     : {risk_ids}")
    print(f"  Well (prod)   : {well_prod_id}")
    print(f"  Well (inj)    : {well_inj_id}")
    print(f"  Evidence pkg  : {collection_id}")
    print(f"  Collab project: {cp_id}")


# ─────────────────────────────────────────────────────────────────────────
# Parameters[] - typed references to evidence artifacts
# ─────────────────────────────────────────────────────────────────────────

def _build_parameters(
    pfx: str,
    reservoir_id: str,
    stat_vol_id: str,
    inplace_vol_id: str,
    well_prod_id: str,
    well_inj_id: str,
    dataspace_id: str,
    risk_ids: List[str],
    collection_id: str = "",
    cp_id: str = "",
    drilling_collection_id: str = "",
) -> List[Dict[str, Any]]:
    params: List[Dict[str, Any]] = []

    if stat_vol_id:
        params.append({
            "Title": "Statistical volumes (P90/P50/P10)",
            "Selection": "SSVP Monte Carlo 65-realisation ensemble statistics",
            "ParameterKindID": f"{pfx}:reference-data--ParameterKind:DataObject:",
            "ParameterRoleID": f"{pfx}:reference-data--ParameterRole:Input:",
            "DataObjectParameter": stat_vol_id,
            "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "REV-stats"}],
        })

    if inplace_vol_id:
        params.append({
            "Title": "In-place volumes (static model)",
            "Selection": "Static model STOIIP per zone (Tarbert + Rannoch)",
            "ParameterKindID": f"{pfx}:reference-data--ParameterKind:DataObject:",
            "ParameterRoleID": f"{pfx}:reference-data--ParameterRole:Input:",
            "DataObjectParameter": inplace_vol_id,
            "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "InPlace-static"}],
        })

    if reservoir_id:
        params.append({
            "Title": "Reservoir scope",
            "Selection": "Omega Sør Alfa – Brent Group (Tarbert + Rannoch)",
            "ParameterKindID": f"{pfx}:reference-data--ParameterKind:DataObject:",
            "ParameterRoleID": f"{pfx}:reference-data--ParameterRole:InputReference:",
            "DataObjectParameter": reservoir_id,
        })

    # Reservoir segments (target formations)
    seg_tarbert_id = f"{pfx}:master-data--ReservoirSegment:OmegaSor-Tarbert:1"
    seg_rannoch_id = f"{pfx}:master-data--ReservoirSegment:OmegaSor-Rannoch:1"
    params.append({
        "Title": "Target segment – Tarbert Fm",
        "Selection": "Upper Brent Group, primary injection + production target",
        "ParameterKindID": f"{pfx}:reference-data--ParameterKind:DataObject:",
        "ParameterRoleID": f"{pfx}:reference-data--ParameterRole:InputReference:",
        "DataObjectParameter": seg_tarbert_id,
    })
    params.append({
        "Title": "Target segment – Rannoch Fm",
        "Selection": "Lower Brent Group, production target (injection upside)",
        "ParameterKindID": f"{pfx}:reference-data--ParameterKind:DataObject:",
        "ParameterRoleID": f"{pfx}:reference-data--ParameterRole:InputReference:",
        "DataObjectParameter": seg_rannoch_id,
    })

    if well_prod_id:
        params.append({
            "Title": "Planned producer well",
            "Selection": "Phase 1 producer – CAP-X sidetrack from 34/4-19 S",
            "ParameterKindID": f"{pfx}:reference-data--ParameterKind:DataObject:",
            "ParameterRoleID": f"{pfx}:reference-data--ParameterRole:Output:",
            "DataObjectParameter": well_prod_id,
            "Keys": [{"ParameterKey": "wellType", "StringParameterKey": "Producer"}],
        })

    if well_inj_id:
        params.append({
            "Title": "Planned injector well",
            "Selection": "Phase 1 injector – 4-slot template sidetrack",
            "ParameterKindID": f"{pfx}:reference-data--ParameterKind:DataObject:",
            "ParameterRoleID": f"{pfx}:reference-data--ParameterRole:Output:",
            "DataObjectParameter": well_inj_id,
            "Keys": [{"ParameterKey": "wellType", "StringParameterKey": "Injector"}],
        })

    params.append({
        "Title": "Geomodel dataspace (RDDMS)",
        "Selection": "ETP dataspace with Omega Sør RMS RESQML model",
        "ParameterKindID": f"{pfx}:reference-data--ParameterKind:DataObject:",
        "ParameterRoleID": f"{pfx}:reference-data--ParameterRole:InputReference:",
        "DataObjectParameter": dataspace_id,
        "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "ETPDataspace"}],
    })

    if collection_id:
        params.append({
            "Title": "Evidence package (PersistedCollection)",
            "Selection": "Frozen evidence snapshot for WPC review",
            "ParameterKindID": f"{pfx}:reference-data--ParameterKind:DataObject:",
            "ParameterRoleID": f"{pfx}:reference-data--ParameterRole:InputReference:",
            "DataObjectParameter": collection_id,
            "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "PersistedCollection"}],
        })

    if cp_id:
        params.append({
            "Title": "Collaboration project",
            "Selection": "Omega Sør Alfa Field Development project (long-lived)",
            "ParameterKindID": f"{pfx}:reference-data--ParameterKind:DataObject:",
            "ParameterRoleID": f"{pfx}:reference-data--ParameterRole:InputReference:",
            "DataObjectParameter": cp_id,
            "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "CollaborationProject"}],
        })

    if drilling_collection_id:
        params.append({
            "Title": "Drilling evidence package",
            "Selection": "Trajectories, drilling programs, wellbore reports",
            "ParameterKindID": f"{pfx}:reference-data--ParameterKind:DataObject:",
            "ParameterRoleID": f"{pfx}:reference-data--ParameterRole:InputReference:",
            "DataObjectParameter": drilling_collection_id,
            "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "DrillingCollection"}],
        })

    return params

def _build_canonical_fields(pfx: str) -> Dict[str, Any]:
    return {
        "Personnel": [
            {"Name": "Subsurface Lead", "ProjectRoleID": f"{pfx}:reference-data--ProjectRole:GeoscienceLead:", "Organisation": "Snorre Subsurface"},
            {"Name": "Reservoir Engineer", "ProjectRoleID": f"{pfx}:reference-data--ProjectRole:ReservoirEngineer:", "Organisation": "Snorre Reservoir Management"},
            {"Name": "Petrophysicist", "ProjectRoleID": f"{pfx}:reference-data--ProjectRole:Petrophysicist:", "Organisation": "Snorre Petec"},
            {"Name": "FMU Lead", "ProjectRoleID": f"{pfx}:reference-data--ProjectRole:FMULead:", "Organisation": "Snorre Geomodelling"},
            {"Name": "Drilling & Wells Lead", "ProjectRoleID": f"{pfx}:reference-data--ProjectRole:DrillingWellsLead:", "Organisation": "Snorre D&W"},
            {"Name": "Production Technology", "ProjectRoleID": f"{pfx}:reference-data--ProjectRole:ProductionTechnology:", "Organisation": "Snorre ProdTech"},
        ],
        "DecisionOwners": [
            {"Name": "Subsurface Lead", "Organisation": "Snorre Subsurface"},
        ],
        "DecisionMakers": [
            {"Name": "Project Director", "Organisation": "Omega Sør Project"},
        ],
        "Contributors": [
            {"Name": "QAA Team", "Organisation": "ST MSU Subsurface QA"},
        ],
        "Remarks": [
            {"Remark": r, "RemarkSource": "SSVP Recommendations"}
            for r in [
                "Approve Phase 1 wells (1 producer + 1 injector) for Omega Sør Alfa",
                "Critical: pilot well required to determine Ba content and OWC",
                "Base case: inject in Tarbert only; Rannoch injection is upside to mature",
                "Drainage strategy depends on barium level – decision tree in place",
                "Template prepared for WAG – evaluate gas injection in next phase",
                "Complete CPT soil investigation for template location",
                "Mature FMU model towards DG0 level (add WAG, Rannoch injection, deferral)",
            ]
        ],
        "ProjectSpecifications": [
            {"ParameterTypeID": f"{pfx}:reference-data--ParameterType:NPV_10pct:", "DataQuantityParameter": 116, "UnitOfMeasureID": f"{pfx}:reference-data--UnitOfMeasure:MUSD:"},
            {"ParameterTypeID": f"{pfx}:reference-data--ParameterType:IRR:", "DataQuantityParameter": 62, "UnitOfMeasureID": f"{pfx}:reference-data--UnitOfMeasure:%:"},
            {"ParameterTypeID": f"{pfx}:reference-data--ParameterType:CAPEX:", "DataQuantityParameter": 213, "UnitOfMeasureID": f"{pfx}:reference-data--UnitOfMeasure:MUSD:"},
            {"ParameterTypeID": f"{pfx}:reference-data--ParameterType:BreakevenOil:", "DataQuantityParameter": 25, "UnitOfMeasureID": f"{pfx}:reference-data--UnitOfMeasure:USD/bbl:"},
            {"ParameterTypeID": f"{pfx}:reference-data--ParameterType:Production:", "DataQuantityParameter": 16.5, "UnitOfMeasureID": f"{pfx}:reference-data--UnitOfMeasure:Mboe:"},
        ],
        "ActivityStates": [
            {"EffectiveDateTime": "2026-06-15", "ActivityStatusID": f"{pfx}:reference-data--ActivityStatus:Completed:", "Remark": "SSVP / PVP Assessment"},
            {"EffectiveDateTime": "2026-09-30", "ActivityStatusID": f"{pfx}:reference-data--ActivityStatus:Planned:", "Remark": "WPC Decision (DG0)"},
            {"EffectiveDateTime": "2027-03-01", "ActivityStatusID": f"{pfx}:reference-data--ActivityStatus:Planned:", "Remark": "DG3 FEED"},
            {"EffectiveDateTime": "2027-09-01", "ActivityStatusID": f"{pfx}:reference-data--ActivityStatus:Planned:", "Remark": "DG4 Sanction"},
            {"EffectiveDateTime": "2028-06-01", "ActivityStatusID": f"{pfx}:reference-data--ActivityStatus:Planned:", "Remark": "Drill Pilot Well"},
            {"EffectiveDateTime": "2029-01-01", "ActivityStatusID": f"{pfx}:reference-data--ActivityStatus:Planned:", "Remark": "First Oil (Phase 1)"},
            {"EffectiveDateTime": "2030-01-01", "ActivityStatusID": f"{pfx}:reference-data--ActivityStatus:Planned:", "Remark": "Phase 2 Start"},
        ],
    }


# ─────────────────────────────────────────────────────────────────────────
# ext.equinor - enrichment payload
# ─────────────────────────────────────────────────────────────────────────

def _build_ext_equinor(pfx: str, risk_ids: List[str]) -> Dict[str, Any]:
    return {
        "Alternatives": [
            {
                "Name": "Alt-A: Base case – 1 WI (Tarbert) + 2 producers, 4-slot template",
                "Rank": 1,
                "Rationale": (
                    "Highest NPV. 1 water injector perforated in Tarbert only + "
                    "2 producers (Tarbert + Rannoch). 4-slot template ~1.1 km south "
                    "of CAP-X. 8\" production flowline, 6\" WI flowline. "
                    "Tieback to Snorre N-template. Applicable if Ba <50 mg/L. "
                    "NPV 116 MUSD (EQN), IRR 62%, break-even 25 USD/bbl. "
                    "First oil Jan 2029."
                ),
                "RecommendedAction": "Approve",
                "NPV_10pct_MUSD": 116,
                "CAPEX_MUSD": 213,
                "IRR_pct": 62,
                "BreakevenOil_USD_bbl": 25,
            },
            {
                "Name": "Alt-B: Depletion / limited injection (if Ba >100 mg/L)",
                "Rank": 2,
                "Rationale": (
                    "Fallback drainage strategy if barium content >100 mg/L makes "
                    "water injection infeasible. 2 wells in depletion or limited "
                    "injection mode. Reduced recovery but avoids scale risk. "
                    "Room for optimization based on barium findings."
                ),
                "RecommendedAction": "Consider",
                "NPV_10pct_MUSD": None,
                "CAPEX_MUSD": None,
                "IRR_pct": None,
                "BreakevenOil_USD_bbl": None,
            },
            {
                "Name": "Alt-C: WAG injection (gas available from Snorre)",
                "Rank": 3,
                "Rationale": (
                    "Template prepared for WAG but no gas injection line in base case. "
                    "Potential upside if gas available from Snorre system. "
                    "Avoids water-related barium mobilization. "
                    "Evaluate as optimization in next phase (DG3)."
                ),
                "RecommendedAction": "Consider",
                "NPV_10pct_MUSD": None,
                "CAPEX_MUSD": None,
                "IRR_pct": None,
                "BreakevenOil_USD_bbl": None,
            },
            {
                "Name": "Alt-D: Defer – acquire pilot well data first",
                "Rank": 4,
                "Rationale": (
                    "Pilot well to deeper part of structure provides: "
                    "1) OWC confirmation, 2) Ba content measurement, "
                    "3) Tarbert sand presence, 4) deformation band characterisation. "
                    "Reduces subsurface uncertainty but delays first oil. "
                    "Robustness scenario (+1yr) still economic. "
                    "Risk: losing rig window or template fabrication slot."
                ),
                "RecommendedAction": "Fallback",
                "NPV_10pct_MUSD": None,
                "CAPEX_MUSD": None,
                "IRR_pct": None,
                "BreakevenOil_USD_bbl": None,
            },
        ],
        "UncertaintySummary": {
            "Basis": (
                "FMU Monte Carlo ensemble with 65 realisations, 1-by-1 sensitivity "
                "design. Static + dynamic uncertainty across Brent Group (Tarbert + "
                "Rannoch). OPM Flow dynamic simulation."
            ),
            "Note": (
                "Recovery factor not fully QC'd at SSVP level. Not yet included: "
                "WAG, Rannoch injection, deferral effects, new F2F. "
                "Key sensitivities: MULTPERM_R, kvkh_RANN, OWC position, porosity."
            ),
            "TotalRealisations": 65,
            "DesignType": "1-by-1 sensitivity (Monte Carlo)",
            "Simulator": "OPM_FLOW",
            "StaticInPlace_Oil_MSm3": {
                "P90": 15.8,
                "P50": 19.3,
                "P10": 22.9,
            },
            "Recoverable_Oil_MSm3": {
                "P90": 3.3,
                "P50": 5.4,
                "P10": 8.0,
            },
            "RecoveryFactor_pct": {
                "P90": 16.3,
                "P50": 28.5,
                "P10": 43.1,
            },
            "AssociatedGas_GSm3_P50": 5.0,
            "TopUncertaintyDrivers": [
                "MULTPERM (deformation band effect on permeability)",
                "kvkh_RANN (Rannoch vertical permeability)",
                "OWC position (3772.5 ODT to 3860 mean)",
                "Porosity / NTG per zone",
                "Barium content (drainage strategy driver)",
            ],
        },
        "DrainageStrategy": {
            "BaseConcept": "1 injector (Tarbert only) + 2 producers (Tarbert + Rannoch)",
            "FlowlineProduction": "8 inch ID",
            "FlowlineInjection": "6 inch ID",
            "Template": "4-slot, ~1.1 km south of CAP-X, prepared for WAG",
            "TiebackHost": "Snorre N-template",
            "Phase1Start": "2029-01-01",
            "Phase2Start": "2030-01-01",
            "Upside": "Rannoch injection (requires depletion + fracturing)",
        },
    }


if __name__ == "__main__":
    main()
