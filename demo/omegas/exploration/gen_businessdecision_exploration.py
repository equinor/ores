#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_businessdecision_exploration.py – Generate BusinessDecision manifest for
the Omega Sør exploration well decision (34/4-19 S).

This is the exploration drilling decision – separate from the WPC field
development decision. Focused on:
  - Geological play confirmation (trap, seal, reservoir, charge)
  - Drilling and data acquisition program
  - Prospect evaluation and volumetrics
  - Geological play / segment characterization

Links to the SAME CollaborationProject and Reservoir master data as the
WPC development decision, maintaining context between decisions.

Reads:
  manifest_risk_exploration.json  - Exploration risk IDs

Output: manifest_bd_exploration.json

Usage:
  python demo/omegas/exploration/gen_businessdecision_exploration.py
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

from demo.eqn.omegas.exploration._shared_expl import (
    SCRIPT_DIR, DEFAULT_ACL, DEFAULT_LEGAL, ID_PREFIX,
    SPATIAL_AREA_WGS84, PROJECT_CRS_ID,
    FIELD_NAME, DISCOVERY_NAME, LICENCE, BLOCK, OPERATOR,
    WELL_NAME, WELL_ID_SUFFIX,
    CP_ID, RESERVOIR_ID, SEG_TARBERT_ID, SEG_RANNOCH_ID,
    WELL_EXPL_ID, WELLBORE_EXPL_ID, DATASPACE_ID,
    BD_EXPL_ID, COLLECTION_EXPL_ID,
    DRILLING_COLLECTION_EXPL_ID, GEOSCIENCE_COLLECTION_EXPL_ID,
    load_json,
)


def _find_all_ids(manifest: Dict, kind_fragment: str) -> List[str]:
    ids = []
    for md in manifest.get("MasterData", []):
        if kind_fragment in md.get("kind", ""):
            ids.append(md["id"])
    return ids


def main():
    ap = argparse.ArgumentParser(
        description="Generate Omega Sør Exploration BusinessDecision manifest")
    ap.add_argument("--risks", default=str(SCRIPT_DIR / "manifest_risk_exploration.json"))
    ap.add_argument("--manifest", default=str(SCRIPT_DIR / "manifest_bd_exploration.json"))
    ap.add_argument("--id-prefix", default=ID_PREFIX)
    args = ap.parse_args()

    pfx = args.id_prefix

    # ── Load risk manifest ──────────────────────────────────────────────
    risks = load_json(args.risks)
    risk_ids = _find_all_ids(risks, "master-data--Risk:")

    # ── Build BD record ─────────────────────────────────────────────────
    bd_record = {
        "id": BD_EXPL_ID,
        "kind": "osdu:wks:master-data--BusinessDecision:1.0.0",
        "acl": DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": "Omega Sør – Exploration Well Decision (34/4-19 S)",
            "Description": (
                f"Exploration well decision for the {DISCOVERY_NAME} prospect "
                f"(Snorre area, block {BLOCK}, {LICENCE}). Approve drilling of "
                f"exploration well {WELL_NAME} targeting Brent Group "
                "(Tarbert + Rannoch formations) in a 4-way dip closure on "
                "Top Brent. Primary objectives: confirm hydrocarbon presence, "
                "determine OWC, characterize reservoir quality, and acquire "
                "formation water sample for barium content assessment. "
                "Prospect volumetrics: STOIIP P50 19.3 MSm³. "
                "Geological probability of success Pg = 0.69."
            ),
            "ProjectName": f"{DISCOVERY_NAME} Exploration",
            "DecisionLevelID": f"{pfx}:reference-data--DecisionLevel:ExplorationDrilling:",
            "ApprovalStatusID": f"{pfx}:reference-data--DecisionApprovalStatus:Approved:",
            "DecisionDueDate": "2023-06-01",
            "DecisionSummary": (
                f"Approve drilling of exploration well {WELL_NAME} to evaluate "
                f"the {DISCOVERY_NAME} prospect. Target: Brent Group (Tarbert + "
                "Rannoch Fm) at ~3800-3870 m TVD in 4-way dip closure. "
                "Data acquisition program: 120 m core (Tarbert+Rannoch), "
                "triple-combo + CMR + FMI logs, 48+ MDT pressure points, "
                "formation water sampling. "
                "Well to be drilled from semi-sub, plugged and abandoned after "
                "evaluation. Results feed directly into field development concept "
                "selection (WPC decision)."
            ),
            "RiskIDs": risk_ids,
            "ReservoirIDs": [RESERVOIR_ID],
            "ReservoirSegmentIDs": [SEG_TARBERT_ID, SEG_RANNOCH_ID],
            "CollaborationProjectID": CP_ID,
            "EvidenceCollectionID": COLLECTION_EXPL_ID,
            "DrillingEvidenceCollectionID": DRILLING_COLLECTION_EXPL_ID,
            "GeoscienceEvidenceCollectionID": GEOSCIENCE_COLLECTION_EXPL_ID,
            "Parameters": _build_parameters(pfx, risk_ids),
            **_build_canonical_fields(pfx),
            "SpatialArea": SPATIAL_AREA_WGS84,
            "CoordinateReferenceSystemID": PROJECT_CRS_ID,
            "ancestry": {
                "parents": [],
                "children": [
                    WELL_EXPL_ID,
                    # This exploration decision feeds into WPC development BD
                    f"{pfx}:master-data--BusinessDecision:OmegaSor-WPC:1",
                ],
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
    print(f"Exploration BusinessDecision manifest written → {out}")
    print(f"  BD ID            : {BD_EXPL_ID}")
    print(f"  Well ref         : {WELL_EXPL_ID}")
    print(f"  Reservoir ref    : {RESERVOIR_ID}")
    print(f"  Risk refs        : {risk_ids}")
    print(f"  Evidence pkg     : {COLLECTION_EXPL_ID}")
    print(f"  Drilling pkg     : {DRILLING_COLLECTION_EXPL_ID}")
    print(f"  Geoscience pkg   : {GEOSCIENCE_COLLECTION_EXPL_ID}")
    print(f"  Collab project   : {CP_ID}")


# ─────────────────────────────────────────────────────────────────────────
# Parameters[] – typed references to evidence artifacts
# ─────────────────────────────────────────────────────────────────────────

def _build_parameters(pfx: str, risk_ids: List[str]) -> List[Dict[str, Any]]:
    params: List[Dict[str, Any]] = []

    params.append({
        "Title": "Target reservoir",
        "Selection": f"{DISCOVERY_NAME} – Brent Group (Tarbert + Rannoch)",
        "ParameterKindID": f"{pfx}:reference-data--ParameterKind:DataObject:",
        "ParameterRoleID": f"{pfx}:reference-data--ParameterRole:InputReference:",
        "DataObjectParameter": RESERVOIR_ID,
    })

    params.append({
        "Title": "Exploration well",
        "Selection": f"{WELL_NAME} – discovery well targeting Brent Group",
        "ParameterKindID": f"{pfx}:reference-data--ParameterKind:DataObject:",
        "ParameterRoleID": f"{pfx}:reference-data--ParameterRole:Output:",
        "DataObjectParameter": WELL_EXPL_ID,
        "Keys": [{"ParameterKey": "wellType", "StringParameterKey": "Exploration"}],
    })

    params.append({
        "Title": "Geomodel dataspace (RDDMS)",
        "Selection": "ETP dataspace with Omega Sør RMS RESQML model",
        "ParameterKindID": f"{pfx}:reference-data--ParameterKind:DataObject:",
        "ParameterRoleID": f"{pfx}:reference-data--ParameterRole:InputReference:",
        "DataObjectParameter": DATASPACE_ID,
        "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "ETPDataspace"}],
    })

    params.append({
        "Title": "Evidence package (PersistedCollection)",
        "Selection": "Exploration well evidence snapshot",
        "ParameterKindID": f"{pfx}:reference-data--ParameterKind:DataObject:",
        "ParameterRoleID": f"{pfx}:reference-data--ParameterRole:InputReference:",
        "DataObjectParameter": COLLECTION_EXPL_ID,
        "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "PersistedCollection"}],
    })

    params.append({
        "Title": "Collaboration project",
        "Selection": f"{DISCOVERY_NAME} Field Development project (long-lived)",
        "ParameterKindID": f"{pfx}:reference-data--ParameterKind:DataObject:",
        "ParameterRoleID": f"{pfx}:reference-data--ParameterRole:InputReference:",
        "DataObjectParameter": CP_ID,
        "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "CollaborationProject"}],
    })

    params.append({
        "Title": "Drilling evidence package",
        "Selection": "Trajectory, drilling program, wellbore reports, handover docs",
        "ParameterKindID": f"{pfx}:reference-data--ParameterKind:DataObject:",
        "ParameterRoleID": f"{pfx}:reference-data--ParameterRole:InputReference:",
        "DataObjectParameter": DRILLING_COLLECTION_EXPL_ID,
        "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "DrillingCollection"}],
    })

    params.append({
        "Title": "Geoscience evidence package",
        "Selection": "Seismic horizons, well tops, prospect maps, play assessment",
        "ParameterKindID": f"{pfx}:reference-data--ParameterKind:DataObject:",
        "ParameterRoleID": f"{pfx}:reference-data--ParameterRole:InputReference:",
        "DataObjectParameter": GEOSCIENCE_COLLECTION_EXPL_ID,
        "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "GeoscienceCollection"}],
    })

    # Segment references
    params.append({
        "Title": "Target segment – Tarbert Fm",
        "Selection": "Upper Brent Group, primary reservoir target",
        "ParameterKindID": f"{pfx}:reference-data--ParameterKind:DataObject:",
        "ParameterRoleID": f"{pfx}:reference-data--ParameterRole:InputReference:",
        "DataObjectParameter": SEG_TARBERT_ID,
    })

    params.append({
        "Title": "Target segment – Rannoch Fm",
        "Selection": "Lower Brent Group, secondary reservoir target",
        "ParameterKindID": f"{pfx}:reference-data--ParameterKind:DataObject:",
        "ParameterRoleID": f"{pfx}:reference-data--ParameterRole:InputReference:",
        "DataObjectParameter": SEG_RANNOCH_ID,
    })

    return params


def _build_canonical_fields(pfx: str) -> Dict[str, Any]:
    return {
        "Personnel": [
            {"Name": "Exploration Lead", "ProjectRoleID": f"{pfx}:reference-data--ProjectRole:ExplorationLead:", "Organisation": "Snorre Exploration"},
            {"Name": "Geologist", "ProjectRoleID": f"{pfx}:reference-data--ProjectRole:Geologist:", "Organisation": "Snorre Exploration"},
            {"Name": "Geophysicist", "ProjectRoleID": f"{pfx}:reference-data--ProjectRole:Geophysicist:", "Organisation": "Snorre Exploration"},
            {"Name": "Petrophysicist", "ProjectRoleID": f"{pfx}:reference-data--ProjectRole:Petrophysicist:", "Organisation": "Snorre Petec"},
            {"Name": "Drilling & Wells Lead", "ProjectRoleID": f"{pfx}:reference-data--ProjectRole:DrillingWellsLead:", "Organisation": "Snorre D&W"},
            {"Name": "Well Site Geologist", "ProjectRoleID": f"{pfx}:reference-data--ProjectRole:WellSiteGeologist:", "Organisation": "Snorre Exploration"},
        ],
        "DecisionOwners": [
            {"Name": "Exploration Manager", "Organisation": "Snorre Exploration"},
        ],
        "DecisionMakers": [
            {"Name": "VP Exploration Norway", "Organisation": "EPN Exploration"},
        ],
        "Contributors": [
            {"Name": "Pre-Execution Team", "Organisation": "D&W Pre-Execution"},
            {"Name": "Geoscience QA", "Organisation": "ST MSU Subsurface QA"},
        ],
        "Remarks": [
            {"Remark": r, "RemarkSource": "Exploration Decision"}
            for r in [
                f"Approve drilling of {WELL_NAME} to confirm {DISCOVERY_NAME} prospect",
                "Primary target: Brent Group (Tarbert + Rannoch Fm) in 4-way dip closure",
                "Data acquisition: 120 m core, triple-combo + CMR + FMI, 48+ MDT, water sample",
                "Prospect Pg = 0.69 (combined play elements including Beta segment)",
                "Pre-drill STOIIP P50 = 19.3 MSm³ (volumetrics from GEOX evaluation)",
                "Well feeds directly into field development concept (WPC decision)",
                "Post-drill: oil confirmed in Tarbert + Rannoch, water sample NOT obtained",
            ]
        ],
        "ProjectSpecifications": [
            {"ParameterTypeID": f"{pfx}:reference-data--ParameterType:PreDrillSTOIIP_P50:", "DataQuantityParameter": 19.3, "UnitOfMeasureID": f"{pfx}:reference-data--UnitOfMeasure:MSm3:"},
            {"ParameterTypeID": f"{pfx}:reference-data--ParameterType:GeologicalProbability:", "DataQuantityParameter": 0.69, "UnitOfMeasureID": f"{pfx}:reference-data--UnitOfMeasure:fraction:"},
            {"ParameterTypeID": f"{pfx}:reference-data--ParameterType:WellCost:", "DataQuantityParameter": 45, "UnitOfMeasureID": f"{pfx}:reference-data--UnitOfMeasure:MUSD:"},
            {"ParameterTypeID": f"{pfx}:reference-data--ParameterType:DrillingDays:", "DataQuantityParameter": 74, "UnitOfMeasureID": f"{pfx}:reference-data--UnitOfMeasure:days:"},
            {"ParameterTypeID": f"{pfx}:reference-data--ParameterType:CoreRecovery:", "DataQuantityParameter": 120, "UnitOfMeasureID": f"{pfx}:reference-data--UnitOfMeasure:m:"},
            {"ParameterTypeID": f"{pfx}:reference-data--ParameterType:MDTPoints:", "DataQuantityParameter": 48, "UnitOfMeasureID": f"{pfx}:reference-data--UnitOfMeasure:count:"},
        ],
        "ActivityStates": [
            {"EffectiveDateTime": "2023-03-01", "ActivityStatusID": f"{pfx}:reference-data--ActivityStatus:Completed:", "Remark": "Prospect maturation and GEOX evaluation"},
            {"EffectiveDateTime": "2023-06-01", "ActivityStatusID": f"{pfx}:reference-data--ActivityStatus:Completed:", "Remark": "Exploration drilling decision (DG2)"},
            {"EffectiveDateTime": "2023-06-15", "ActivityStatusID": f"{pfx}:reference-data--ActivityStatus:Completed:", "Remark": "DW112 Activity Program signature"},
            {"EffectiveDateTime": "2023-07-01", "ActivityStatusID": f"{pfx}:reference-data--ActivityStatus:Completed:", "Remark": "Handover MWP → Pre-Execution"},
            {"EffectiveDateTime": "2023-08-01", "ActivityStatusID": f"{pfx}:reference-data--ActivityStatus:Completed:", "Remark": "Handover Pre-Execution → Operations Centre"},
            {"EffectiveDateTime": "2023-09-15", "ActivityStatusID": f"{pfx}:reference-data--ActivityStatus:Completed:", "Remark": "Spud date"},
            {"EffectiveDateTime": "2023-11-28", "ActivityStatusID": f"{pfx}:reference-data--ActivityStatus:Completed:", "Remark": "TD reached (4090 m MD / 3872 m TVD)"},
            {"EffectiveDateTime": "2023-12-15", "ActivityStatusID": f"{pfx}:reference-data--ActivityStatus:Completed:", "Remark": "P&A and rig release"},
            {"EffectiveDateTime": "2024-02-01", "ActivityStatusID": f"{pfx}:reference-data--ActivityStatus:Completed:", "Remark": "EOWR (End of Well Report)"},
            {"EffectiveDateTime": "2024-03-01", "ActivityStatusID": f"{pfx}:reference-data--ActivityStatus:Completed:", "Remark": "DW100 Handover exploration wells – D&W to Licence"},
        ],
    }


# ─────────────────────────────────────────────────────────────────────────
# ext.equinor – exploration-specific enrichment
# ─────────────────────────────────────────────────────────────────────────

def _build_ext_equinor(pfx: str, risk_ids: List[str]) -> Dict[str, Any]:
    return {
        "Alternatives": [
            {
                "Name": "Alt-A: Drill exploration well (recommended)",
                "Rank": 1,
                "Rationale": (
                    f"Drill {WELL_NAME} to confirm {DISCOVERY_NAME} prospect. "
                    "4-way dip closure on Top Brent, Pg = 0.69. "
                    "Data acquisition: core + logs + MDT + water sample. "
                    "Confirms play elements and provides input to development "
                    "concept selection. Estimated well cost 45 MUSD. "
                    "Success case feeds into high-value WPC development decision "
                    "(NPV 116 MUSD if developed)."
                ),
                "RecommendedAction": "Approve",
            },
            {
                "Name": "Alt-B: Defer – acquire additional seismic first",
                "Rank": 2,
                "Rationale": (
                    "Acquire additional 3D seismic (reprocessing or new survey) "
                    "to improve fault imaging and reduce structural uncertainty "
                    "before committing to exploration well. "
                    "Pro: reduced risk of dry well. "
                    "Con: 12-18 month delay, potential loss of rig window, "
                    "and seismic unlikely to resolve OWC or barium question."
                ),
                "RecommendedAction": "Consider",
            },
            {
                "Name": "Alt-C: Do not drill – farm out or relinquish",
                "Rank": 3,
                "Rationale": (
                    "Farm out exploration commitment or evaluate relinquishment "
                    "at next licence renewal. Eliminates well cost exposure. "
                    "Con: high Pg (0.69) and significant volumes make this "
                    "unattractive given licence commitment schedule."
                ),
                "RecommendedAction": "Reject",
            },
        ],
        "ProspectAssessment": {
            "ProspectName": DISCOVERY_NAME,
            "PlayName": "Middle Jurassic Brent Group (Tampen Spur)",
            "TrapType": "4-way dip closure on Top Brent, fault-bounded to east (ISF)",
            "ProbabilityOfSuccess": {
                "Pg_Combined": 0.69,
                "Pg_Trap": 0.85,
                "Pg_Seal": 0.90,
                "Pg_Reservoir": 0.95,
                "Pg_Charge": 0.95,
            },
            "PreDrillVolumes": {
                "STOIIP_P90_MSm3": 15.8,
                "STOIIP_P50_MSm3": 19.3,
                "STOIIP_P10_MSm3": 22.9,
                "Recoverable_P50_MSm3": 5.4,
            },
            "SourceRock": "Draupne Fm (Upper Jurassic)",
            "MigrationPathway": "Lateral from Snorre kitchen, short distance",
            "ReservoirFormations": ["Tarbert Fm", "Rannoch Fm"],
            "SealFormation": "Drake Fm (top), ISF juxtaposition (lateral)",
            "DepthTarget_mTVD": 3840,
            "AnalogueFields": ["Snorre", "Vigdis"],
        },
        "DataAcquisitionProgram": {
            "CoreProgram": "120 m conventional core (Tarbert + Rannoch), contingency SWC",
            "LoggingProgram": "Triple-combo + CMR + FMI (wireline), LWD/MWD backup",
            "PressureProgram": "48+ MDT stations across Tarbert + Rannoch + cap rock",
            "FluidSampling": "Formation water sample (MDT extended pump-out) – CRITICAL for Ba content",
            "WellTesting": "No formation test (P&A well) – MDT data sufficient for prospect evaluation",
        },
        "PostDrillResults": {
            "Outcome": "Discovery – oil confirmed",
            "OilShows": "Oil in Tarbert Fm and Rannoch Fm (both zones oil-bearing)",
            "OWC_Confirmed": False,
            "OWC_Remark": "ODT at 3772.5 m, OWC not penetrated (deeper than TD)",
            "WaterSampleObtained": False,
            "WaterSampleRemark": "Unable to obtain formation water sample – barium content unknown",
            "CoreRecovery_m": 120,
            "MDTPoints": 48,
            "ReservoirQuality": "Tarbert: good (50-200 mD). Rannoch: moderate (20-80 mD, deformation bands near ISF)",
            "FeedToNextDecision": "WPC field development decision (2026)",
        },
        "SharePointSite": "https://statoilsrm.sharepoint.com/sites/WCPNO344-19S",
    }


if __name__ == "__main__":
    main()
