#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_drilling_exploration.py – Generate drilling-related OSDU records for the
Omega Sør exploration well (34/4-19 S).

Maps exploration well technical data to OSDU schemas:
  - WellboreTrajectory (linked to RDDMS DDMSDatasets – drilled survey)
  - Activity WPCs (drilling phases: conductor, surface, intermediate, reservoir)
  - WellLog WPC (composite log suite)
  - FormationMarker WPCs (well tops / formation picks)
  - WellboreMarkerSet (stratigraphic markers)
  - Document WPCs (SharePoint docs mapped to OSDU)
  - PersistedCollection (drilling domain evidence bundle)

Documents from SharePoint site (WCPNO344-19S):
  - DW112 Activity Program Signature Presentation
  - DW100 Handover of exploration wells (D&W to License)
  - EOWR (End of Well Report)
  - Handover MWP to PreEx
  - Handover PEX to OC
  - Risk analysis concept phase

Output: manifest_drilling_exploration.json

Usage:
  python demo/omegas/exploration/gen_drilling_exploration.py
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

from demo.eqn.omegas.exploration._shared_expl import (
    SCRIPT_DIR, DEFAULT_ACL, DEFAULT_LEGAL, ID_PREFIX, DATASPACE,
    SPATIAL_AREA_WGS84, PROJECT_CRS_ID,
    FIELD_NAME, DISCOVERY_NAME, LICENCE, BLOCK, OPERATOR,
    WELL_NAME, WELL_ID_SUFFIX, WELL_EXPL_ID, WELLBORE_EXPL_ID,
    DRILLING_COLLECTION_EXPL_ID,
)

# ── EPC trajectory UUID (from os.epc – drilled survey) ─────────────────
TRAJ_UUID_EXPL = "f3712d53-bead-4301-ab97-652817d23639"


def main():
    ap = argparse.ArgumentParser(
        description="Generate Omega Sør exploration drilling records")
    ap.add_argument("--manifest",
                    default=str(SCRIPT_DIR / "manifest_drilling_exploration.json"))
    ap.add_argument("--id-prefix", default=ID_PREFIX)
    args = ap.parse_args()

    pfx = args.id_prefix
    wpcs: List[Dict[str, Any]] = []
    all_ids: List[str] = []

    # ═══════════════════════════════════════════════════════════════════
    # 1. WellboreTrajectory (drilled survey – RDDMS authoritative)
    # ═══════════════════════════════════════════════════════════════════
    traj_id = f"{pfx}:work-product-component--WellboreTrajectory:OmegaSor-Traj-{WELL_ID_SUFFIX}:1"
    ddms_uri = (
        f"eml://reservoir-ddms1/dataspace('{DATASPACE}')/"
        f"resqml20.obj_WellboreTrajectoryRepresentation({TRAJ_UUID_EXPL})"
    )
    wpcs.append({
        "id": traj_id,
        "kind": "osdu:wks:work-product-component--WellboreTrajectory:1.1.0",
        "acl": DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": f"Omega Sør – {WELL_NAME} Drilled Trajectory",
            "Description": (
                f"Drilled wellbore trajectory for exploration well {WELL_NAME}. "
                f"TD: 4090 m MD / 3872 m TVD. Authoritative data in RDDMS "
                f"dataspace {DATASPACE}. Brent Group penetration: Tarbert + Rannoch."
            ),
            "WellboreID": WELLBORE_EXPL_ID,
            "DDMSDatasets": [ddms_uri],
            "ExistenceKind": f"{pfx}:reference-data--ExistenceKind:Actual:",
            "IsDiscoverable": True,
            "SpatialArea": SPATIAL_AREA_WGS84,
            "CoordinateReferenceSystemID": PROJECT_CRS_ID,
            "ext": {
                "equinor": {
                    "SpudDate": "2023-09-15",
                    "TDDate": "2023-11-28",
                    "TotalDepthMD_m": 4090.0,
                    "TotalDepthTVD_m": 3872.0,
                    "WaterDepth_m": 381.0,
                    "AzimuthReference": "TrueNorth",
                    "SurveyType": "Gyroscopic + MWD",
                },
            },
        },
    })
    all_ids.append(traj_id)

    # ═══════════════════════════════════════════════════════════════════
    # 2. WellLog (composite logging suite)
    # ═══════════════════════════════════════════════════════════════════
    log_id = f"{pfx}:work-product-component--WellLog:OmegaSor-CompLog-{WELL_ID_SUFFIX}:1"
    wpcs.append({
        "id": log_id,
        "kind": "osdu:wks:work-product-component--WellLog:1.2.0",
        "acl": DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": f"Omega Sør – {WELL_NAME} Composite Log",
            "Description": (
                f"Composite wireline/LWD log suite for {WELL_NAME}. "
                "Includes: GR, RHOB, NPHI, DT, DTSH, Rt (AIT), CMR (T2 distribution, "
                "permeability), FMI (borehole image). Acquired from surface to TD."
            ),
            "WellboreID": WELLBORE_EXPL_ID,
            "TopMeasuredDepth": {"Value": 500.0, "UnitOfMeasureID": f"{pfx}:reference-data--UnitOfMeasure:m:"},
            "BottomMeasuredDepth": {"Value": 4090.0, "UnitOfMeasureID": f"{pfx}:reference-data--UnitOfMeasure:m:"},
            "Curves": [
                {"CurveMnemonic": "GR", "CurveUnit": "gAPI", "CurveDescription": "Gamma Ray"},
                {"CurveMnemonic": "RHOB", "CurveUnit": "g/cm3", "CurveDescription": "Bulk Density"},
                {"CurveMnemonic": "NPHI", "CurveUnit": "v/v", "CurveDescription": "Neutron Porosity"},
                {"CurveMnemonic": "DT", "CurveUnit": "us/ft", "CurveDescription": "Sonic (compressional)"},
                {"CurveMnemonic": "DTSH", "CurveUnit": "us/ft", "CurveDescription": "Sonic (shear)"},
                {"CurveMnemonic": "RT", "CurveUnit": "ohm.m", "CurveDescription": "Deep Resistivity (AIT)"},
                {"CurveMnemonic": "CMR_T2", "CurveUnit": "ms", "CurveDescription": "CMR T2 distribution"},
                {"CurveMnemonic": "CMR_PERM", "CurveUnit": "mD", "CurveDescription": "CMR Permeability"},
                {"CurveMnemonic": "FMI", "CurveUnit": "ohm.m", "CurveDescription": "Formation MicroImager"},
            ],
            "ExistenceKind": f"{pfx}:reference-data--ExistenceKind:Actual:",
            "IsDiscoverable": True,
        },
    })
    all_ids.append(log_id)

    # ═══════════════════════════════════════════════════════════════════
    # 3. WellboreMarkerSet (formation tops / picks)
    # ═══════════════════════════════════════════════════════════════════
    marker_id = f"{pfx}:work-product-component--WellboreMarkerSet:OmegaSor-Markers-{WELL_ID_SUFFIX}:1"
    wpcs.append({
        "id": marker_id,
        "kind": "osdu:wks:work-product-component--WellboreMarkerSet:1.0.0",
        "acl": DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": f"Omega Sør – {WELL_NAME} Formation Tops",
            "Description": (
                f"Formation tops picked in exploration well {WELL_NAME}. "
                "Brent Group formations plus overlying and underlying units. "
                "Picks from composite log interpretation and core-log integration."
            ),
            "WellboreID": WELLBORE_EXPL_ID,
            "Markers": [
                {"MarkerName": "Seabed", "MeasuredDepth": {"Value": 381.0, "UnitOfMeasureID": f"{pfx}:reference-data--UnitOfMeasure:m:"}, "Interpretation": "Seabed pick from sonar/caliper"},
                {"MarkerName": "Top Hordaland Gp", "MeasuredDepth": {"Value": 1450.0, "UnitOfMeasureID": f"{pfx}:reference-data--UnitOfMeasure:m:"}, "Interpretation": "Top Tertiary (Hordaland Group)"},
                {"MarkerName": "Top Shetland Gp", "MeasuredDepth": {"Value": 2800.0, "UnitOfMeasureID": f"{pfx}:reference-data--UnitOfMeasure:m:"}, "Interpretation": "Top Cretaceous (chalk)"},
                {"MarkerName": "Top Viking Gp", "MeasuredDepth": {"Value": 3520.0, "UnitOfMeasureID": f"{pfx}:reference-data--UnitOfMeasure:m:"}, "Interpretation": "Top Jurassic (Viking Group)"},
                {"MarkerName": "Top Heather Fm", "MeasuredDepth": {"Value": 3620.0, "UnitOfMeasureID": f"{pfx}:reference-data--UnitOfMeasure:m:"}, "Interpretation": "Heather Formation (cap rock transition)"},
                {"MarkerName": "Top Drake Fm", "MeasuredDepth": {"Value": 3710.0, "UnitOfMeasureID": f"{pfx}:reference-data--UnitOfMeasure:m:"}, "Interpretation": "Drake Formation (seal)"},
                {"MarkerName": "Top Tarbert Fm", "MeasuredDepth": {"Value": 3750.0, "UnitOfMeasureID": f"{pfx}:reference-data--UnitOfMeasure:m:"}, "Interpretation": "TOP RESERVOIR – Tarbert Fm (oil-bearing)"},
                {"MarkerName": "Top Rannoch Fm", "MeasuredDepth": {"Value": 3820.0, "UnitOfMeasureID": f"{pfx}:reference-data--UnitOfMeasure:m:"}, "Interpretation": "Rannoch Fm (oil-bearing, deformation bands near ISF)"},
                {"MarkerName": "Base Brent Gp", "MeasuredDepth": {"Value": 3870.0, "UnitOfMeasureID": f"{pfx}:reference-data--UnitOfMeasure:m:"}, "Interpretation": "Base Brent Group / Top Dunlin Gp"},
                {"MarkerName": "TD", "MeasuredDepth": {"Value": 4090.0, "UnitOfMeasureID": f"{pfx}:reference-data--UnitOfMeasure:m:"}, "Interpretation": "Total Depth (in Dunlin Gp)"},
            ],
            "ExistenceKind": f"{pfx}:reference-data--ExistenceKind:Actual:",
            "IsDiscoverable": True,
        },
    })
    all_ids.append(marker_id)

    # ═══════════════════════════════════════════════════════════════════
    # 4. Activities (drilling phases + data acquisition)
    # ═══════════════════════════════════════════════════════════════════
    activities = [
        (
            "OmegaSor-Expl-MobilizationSpud",
            "Omega Sør – 34/4-19 S Rig Mobilization & Spud",
            "Rig mobilization and spud of exploration well 34/4-19 S. "
            "Semi-submersible rig positioned on location. 30\" conductor "
            "driven to ~120 m below seabed.",
            [
                ("Activity Phase", "Mobilization & Spud"),
                ("Start Date", "2023-09-01"),
                ("Spud Date", "2023-09-15"),
                ("Rig Type", "Semi-submersible"),
                ("Conductor", "30\" driven, ~120 m below mudline"),
                ("Water Depth", "381 m"),
            ],
        ),
        (
            "OmegaSor-Expl-SurfaceHole",
            "Omega Sør – 34/4-19 S Surface Hole (20\" casing)",
            "Surface hole section for 34/4-19 S. 26\" hole to ~800 m MD, "
            "20\" casing set and cemented. Riser installed, BOP tested.",
            [
                ("Activity Phase", "Surface Hole"),
                ("Hole Size", "26\""),
                ("Casing", "20\" surface casing to ~800 m"),
                ("Mud Type", "Seawater / WBM"),
                ("Duration", "~8 days"),
                ("BOP Test", "Passed – 10,000 psi"),
            ],
        ),
        (
            "OmegaSor-Expl-IntermediateHole",
            "Omega Sør – 34/4-19 S Intermediate Hole (13⅜\" casing)",
            "Intermediate hole section for 34/4-19 S. 17½\" hole through "
            "Hordaland Group to ~3520 m MD. 13⅜\" casing set in Top Viking. "
            "Critical: cement across Hordaland flow unit for P&A integrity.",
            [
                ("Activity Phase", "Intermediate Hole"),
                ("Hole Size", "17½\""),
                ("Casing", "13⅜\" intermediate to ~3520 m (Top Viking Gp)"),
                ("Mud Type", "WBM (KCl-polymer)"),
                ("Duration", "~25 days"),
                ("Key Issue", "Hordaland flow unit – cement verification for P&A"),
                ("ECD Management", "Careful ROP control through Hordaland shales"),
            ],
        ),
        (
            "OmegaSor-Expl-ReservoirSection",
            "Omega Sør – 34/4-19 S Reservoir Section (9⅝\" liner)",
            "Reservoir section for 34/4-19 S. 12¼\" hole from Top Viking to "
            "~3870 m MD (Brent Group), then 8½\" rat-hole to TD 4090 m MD. "
            "9⅝\" production liner set across reservoir. Full data acquisition "
            "program executed: coring, wireline logging, MDT pressures.",
            [
                ("Activity Phase", "Reservoir Section"),
                ("Hole Size", "12¼\" → 8½\" (rat-hole)"),
                ("Liner", "9⅝\" production liner across Brent Group"),
                ("Mud Type", "OBM (reservoir section)"),
                ("Duration", "~30 days (including data acquisition)"),
                ("Core", "120 m recovered (Tarbert + Rannoch)"),
                ("Wireline", "Triple-combo + CMR + FMI"),
                ("MDT", "48 stations (Tarbert, Rannoch, cap rock)"),
                ("Water Sample", "FAILED – unable to obtain formation water"),
                ("TD", "4090 m MD / 3872 m TVD"),
            ],
        ),
        (
            "OmegaSor-Expl-PA",
            "Omega Sør – 34/4-19 S P&A and Rig Release",
            "Plug & Abandonment of 34/4-19 S per NORSOK D-010. "
            "Cement plugs set across reservoir, intermediate casing, and "
            "surface. Well permanently abandoned. Rig released.",
            [
                ("Activity Phase", "P&A and Rig Release"),
                ("Start Date", "2023-12-01"),
                ("Completion Date", "2023-12-15"),
                ("P&A Standard", "NORSOK D-010"),
                ("Cement Plugs", "3 (reservoir, intermediate, surface)"),
                ("Duration", "~14 days"),
                ("Well Status", "Permanently Plugged & Abandoned"),
            ],
        ),
    ]

    for act_suffix, name, desc, params_list in activities:
        act_id = f"{pfx}:work-product-component--Activity:{act_suffix}:1"
        wpcs.append({
            "id": act_id,
            "kind": "osdu:wks:work-product-component--Activity:1.0.0",
            "acl": DEFAULT_ACL,
            "legal": DEFAULT_LEGAL,
            "data": {
                "Name": name,
                "Description": desc,
                "ActivityType": f"{pfx}:reference-data--WellActivityType:Drilling:",
                "WellboreID": WELLBORE_EXPL_ID,
                "Parameters": [
                    {"Title": k, "StringParameter": v} for k, v in params_list
                ],
            },
        })
        all_ids.append(act_id)

    # ═══════════════════════════════════════════════════════════════════
    # 5. WellTechnicalData – Casing, Cement, Fluids, BHA
    # ═══════════════════════════════════════════════════════════════════
    # Tubulars / Casing record
    tubulars_id = f"{pfx}:work-product-component--TubularAssembly:OmegaSor-Tubulars-{WELL_ID_SUFFIX}:1"
    wpcs.append({
        "id": tubulars_id,
        "kind": "osdu:wks:work-product-component--TubularAssembly:1.0.0",
        "acl": DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": f"Omega Sør – {WELL_NAME} Casing Program",
            "Description": (
                f"Casing program for exploration well {WELL_NAME}: "
                "30\" conductor → 20\" surface → 13⅜\" intermediate → 9⅝\" liner."
            ),
            "WellboreID": WELLBORE_EXPL_ID,
            "TubularComponents": [
                {"ComponentType": "Conductor", "OuterDiameter": {"Value": 30.0, "UnitOfMeasureID": f"{pfx}:reference-data--UnitOfMeasure:in:"}, "SettingDepth": {"Value": 120.0, "UnitOfMeasureID": f"{pfx}:reference-data--UnitOfMeasure:m:"}, "CementTop": {"Value": 0.0, "UnitOfMeasureID": f"{pfx}:reference-data--UnitOfMeasure:m:"}},
                {"ComponentType": "Surface Casing", "OuterDiameter": {"Value": 20.0, "UnitOfMeasureID": f"{pfx}:reference-data--UnitOfMeasure:in:"}, "SettingDepth": {"Value": 800.0, "UnitOfMeasureID": f"{pfx}:reference-data--UnitOfMeasure:m:"}, "CementTop": {"Value": 0.0, "UnitOfMeasureID": f"{pfx}:reference-data--UnitOfMeasure:m:"}},
                {"ComponentType": "Intermediate Casing", "OuterDiameter": {"Value": 13.375, "UnitOfMeasureID": f"{pfx}:reference-data--UnitOfMeasure:in:"}, "SettingDepth": {"Value": 3520.0, "UnitOfMeasureID": f"{pfx}:reference-data--UnitOfMeasure:m:"}, "CementTop": {"Value": 2800.0, "UnitOfMeasureID": f"{pfx}:reference-data--UnitOfMeasure:m:"}},
                {"ComponentType": "Production Liner", "OuterDiameter": {"Value": 9.625, "UnitOfMeasureID": f"{pfx}:reference-data--UnitOfMeasure:in:"}, "SettingDepth": {"Value": 3870.0, "UnitOfMeasureID": f"{pfx}:reference-data--UnitOfMeasure:m:"}, "CementTop": {"Value": 3400.0, "UnitOfMeasureID": f"{pfx}:reference-data--UnitOfMeasure:m:"}},
            ],
        },
    })
    all_ids.append(tubulars_id)

    # Drilling Fluids record
    fluids_id = f"{pfx}:work-product-component--DrillingFluid:OmegaSor-Fluids-{WELL_ID_SUFFIX}:1"
    wpcs.append({
        "id": fluids_id,
        "kind": "osdu:wks:work-product-component--DrillingFluid:1.0.0",
        "acl": DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": f"Omega Sør – {WELL_NAME} Drilling Fluids",
            "Description": (
                f"Drilling fluid program for {WELL_NAME}. "
                "Surface: seawater/WBM. Intermediate: KCl-polymer WBM. "
                "Reservoir: OBM (non-aqueous drilling fluid) for formation "
                "protection and wellbore stability."
            ),
            "WellboreID": WELLBORE_EXPL_ID,
            "FluidSections": [
                {"Section": "Surface (26\")", "FluidType": "Seawater → WBM", "MudWeight_sg": 1.05, "Remarks": "Open riser, returns to seabed"},
                {"Section": "Intermediate (17½\")", "FluidType": "KCl-Polymer WBM", "MudWeight_sg": 1.25, "Remarks": "ECD management through Hordaland clays"},
                {"Section": "Reservoir (12¼\" / 8½\")", "FluidType": "OBM (NADF)", "MudWeight_sg": 1.40, "Remarks": "Formation protection, overbalance ~50 bar at reservoir"},
            ],
        },
    })
    all_ids.append(fluids_id)

    # ═══════════════════════════════════════════════════════════════════
    # 6. Documents (from SharePoint WCPNO344-19S)
    # ═══════════════════════════════════════════════════════════════════
    documents = [
        (
            "OmegaSor-Expl-DW112-ActivityProgram",
            "Omega Sør – DW112 Activity Program Signature Presentation",
            "Activity Program Signature Presentation (DW112) for exploration "
            f"well {WELL_NAME}. Contains: well objectives, geological prognosis, "
            "drilling program summary, casing design, data acquisition plan, "
            "risk assessment, time/cost estimate, and approval signatures.",
            "DW112 - Activity Program Signature Presentation NO 34_4-19 S Omega S.pptx",
            "DrillingProgram",
        ),
        (
            "OmegaSor-Expl-DW100-Handover",
            "Omega Sør – DW100 Handover Exploration Wells (D&W to License)",
            f"Formal handover of exploration well {WELL_NAME} from Drilling & Wells "
            "to the License team. Documents well status, data acquired, "
            "preliminary results, and outstanding data processing/interpretation.",
            "34_4-19 S Omega S_DW100 Handover of exploration wells - DW to License.docx",
            "HandoverDocument",
        ),
        (
            "OmegaSor-Expl-DW100-Handover-Signed",
            "Omega Sør – DW100 Handover (Signed)",
            f"Signed PDF version of the DW100 Handover document for {WELL_NAME}. "
            "Confirms formal transfer of well responsibility from D&W to License.",
            "Signed_34_4-19 S Omega S_DW100 Handover of exploration wells - DW to License.pdf",
            "HandoverDocument",
        ),
        (
            "OmegaSor-Expl-EOWR",
            "Omega Sør – End of Well Report (EOWR)",
            f"End of Well Report for exploration well {WELL_NAME}. "
            "Comprehensive post-drill documentation: actual vs planned, "
            "drilling performance, formation evaluation results, lessons learned, "
            "HSE summary, cost summary, and recommendations.",
            "EOWR - Omega S.pptx",
            "EndOfWellReport",
        ),
        (
            "OmegaSor-Expl-HandoverMWPtoPreEx",
            "Omega Sør – Handover Main Well Planning to Pre-Execution",
            "Handover documentation from Main Well Planning (MWP) phase to "
            f"Pre-Execution (PEX) phase for {WELL_NAME}. Includes: well design "
            "basis, geological prognosis, well objectives, time estimate, "
            "and outstanding actions.",
            "Handover MWP to PreEx.pptx",
            "WellPlanningDocument",
        ),
        (
            "OmegaSor-Expl-HandoverPEXtoOC",
            "Omega Sør – Handover Pre-Execution to Operations Centre",
            "Handover from Pre-Execution (PEX) to Operations Centre (OC) for "
            f"{WELL_NAME}. Confirms readiness for execution: operational "
            "procedures, contingency plans, real-time monitoring setup, "
            "and personnel roster.",
            "Handover PEX to OC.pptx",
            "WellPlanningDocument",
        ),
        (
            "OmegaSor-Expl-RiskAnalysis",
            "Omega Sør – Risk Analysis Concept Phase",
            f"Risk analysis for the exploration/concept phase of {WELL_NAME}. "
            "Includes: subsurface risks (play, volume, pressure), drilling risks "
            "(well control, overburden, stuck pipe), HSE risks, and mitigations. "
            "Basis for the DW112 activity program risk section.",
            "Risk analysis concept phase.pptx",
            "RiskAssessment",
        ),
    ]

    for doc_suffix, name, desc, filename, doc_type in documents:
        doc_id = f"{pfx}:work-product-component--Document:{doc_suffix}:1"
        wpcs.append({
            "id": doc_id,
            "kind": "osdu:wks:work-product-component--Document:1.0.0",
            "acl": DEFAULT_ACL,
            "legal": DEFAULT_LEGAL,
            "data": {
                "Name": name,
                "Description": desc,
                "DocumentTypeID": f"{pfx}:reference-data--DocumentType:{doc_type}:",
                "ExistenceKind": f"{pfx}:reference-data--ExistenceKind:Actual:",
                "IsDiscoverable": True,
                "ExtensionProperties": {
                    "OriginalFilename": filename,
                    "SharePointSite": "https://statoilsrm.sharepoint.com/sites/WCPNO344-19S",
                    "OmegaSorProject": DATASPACE,
                },
            },
        })
        all_ids.append(doc_id)

    # ═══════════════════════════════════════════════════════════════════
    # 7. Drilling PersistedCollection (domain evidence bundle)
    # ═══════════════════════════════════════════════════════════════════
    well_refs = [WELL_EXPL_ID, WELLBORE_EXPL_ID]
    drilling_refs = well_refs + all_ids

    wpcs.append({
        "id": DRILLING_COLLECTION_EXPL_ID,
        "kind": "osdu:wks:work-product-component--PersistedCollection:1.0.0",
        "acl": DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": "Omega Sør Exploration – Drilling Evidence Package",
            "Description": (
                f"Drilling-related evidence for the {WELL_NAME} exploration well. "
                "Bundles: drilled wellbore trajectory (RDDMS-linked), "
                "composite log suite, formation tops/markers, "
                "drilling activities (5 phases), casing program, drilling fluids, "
                "and 7 reference documents from SharePoint WCPNO344-19S "
                "(DW112, DW100 handovers, EOWR, risk analysis)."
            ),
            "DataReferences": drilling_refs,
            "SpatialArea": SPATIAL_AREA_WGS84,
            "CoordinateReferenceSystemID": PROJECT_CRS_ID,
        },
    })

    # ═══════════════════════════════════════════════════════════════════
    # Assemble manifest
    # ═══════════════════════════════════════════════════════════════════
    manifest = {
        "kind": "osdu:wks:Manifest:1.0.0",
        "ReferenceData": [],
        "MasterData": [],
        "Data": {
            "Datasets": [],
            "WorkProductComponents": wpcs,
            "WorkProducts": [],
        },
    }

    out = Path(args.manifest)
    out.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Exploration drilling manifest written → {out}")
    print(f"  WPCs ({len(wpcs)}):")
    for w in wpcs:
        print(f"    {w['id']}")


if __name__ == "__main__":
    main()
