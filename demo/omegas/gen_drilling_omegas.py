#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_drilling_omegas.py – Generate drilling-related OSDU records for
Omega Sør WPC well decision evidence package.

Produces:
  - 3 WellboreTrajectory WPCs (linked to RDDMS DDMSDatasets as authoritative)
  - 3 Activity WPCs (drilling program per well)
  - 3 Document WPCs (SSVP pptx, wellbore PDF, NOD report)
  - 1 PersistedCollection (drilling evidence bundle)

The WellboreTrajectory records point to the RDDMS dataspace as the
authoritative source via DDMSDatasets[].  The actual survey data
lives in the EPC (os.epc) imported to maap/omegas on RDDMS.

Output: manifest_drilling_omegas.json

Usage:
  python demo/omegas/gen_drilling_omegas.py
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

from demo.eqn.omegas._shared import (
    SCRIPT_DIR, DEFAULT_ACL, DEFAULT_LEGAL, ID_PREFIX, DATASPACE,
    SPATIAL_AREA_WGS84, PROJECT_CRS_ID,
    FIELD_NAME, DISCOVERY_NAME, LICENCE, BLOCK, OPERATOR,
)

# ── EPC object UUIDs (from os.epc) ─────────────────────────────────────
# Trajectory UUID → (well_id_suffix, display_name, traj_title, is_drilled)
TRAJECTORIES = {
    "f3712d53-bead-4301-ab97-652817d23639": (
        "34-4-19S", "34/4-19 S", "Drilled trajectory", True,
    ),
    "d54207a8-457a-4b18-ace6-cf0221999752": (
        "OmegaSor-Producer1", "Omega Sør Producer 1", "Planned trajectory", False,
    ),
    "266ffcd1-5382-4401-b1e1-10133dec1e6e": (
        "OmegaSor-Injector1", "Omega Sør Injector 1", "Planned trajectory", False,
    ),
}


def main():
    ap = argparse.ArgumentParser(
        description="Generate Omega Sør drilling-related OSDU records")
    ap.add_argument("--manifest",
                    default=str(SCRIPT_DIR / "manifest_drilling_omegas.json"))
    ap.add_argument("--id-prefix", default=ID_PREFIX)
    args = ap.parse_args()

    pfx = args.id_prefix
    wpcs: List[Dict[str, Any]] = []
    all_ids: List[str] = []

    # ═══════════════════════════════════════════════════════════════════
    # 1. WellboreTrajectory WPCs (authoritative source = RDDMS)
    # ═══════════════════════════════════════════════════════════════════
    for traj_uuid, (well_suffix, well_name, traj_title, is_drilled) in TRAJECTORIES.items():
        traj_id = f"{pfx}:work-product-component--WellboreTrajectory:OmegaSor-Traj-{well_suffix}:1"
        wellbore_id = f"{pfx}:master-data--Wellbore:{well_suffix}:1"

        # RDDMS DDMSDatasets URI (authoritative trajectory data)
        ddms_uri = (
            f"eml://reservoir-ddms1/dataspace('{DATASPACE}')/"
            f"resqml20.obj_WellboreTrajectoryRepresentation({traj_uuid})"
        )

        rec = {
            "id": traj_id,
            "kind": "osdu:wks:work-product-component--WellboreTrajectory:1.1.0",
            "acl": DEFAULT_ACL,
            "legal": DEFAULT_LEGAL,
            "data": {
                "Name": f"Omega Sør – {well_name} Trajectory",
                "Description": (
                    f"{'Drilled' if is_drilled else 'Planned'} wellbore trajectory for "
                    f"{well_name}. Authoritative data in RDDMS dataspace {DATASPACE}. "
                    f"{'Exploration well – Omega Sør Alfa discovery.' if is_drilled else f'Development well – {DISCOVERY_NAME} Phase 1.'}"
                ),
                "WellboreID": wellbore_id,
                "DDMSDatasets": [ddms_uri],
                "ExistenceKind": f"{pfx}:reference-data--ExistenceKind:{'Actual' if is_drilled else 'Planned'}:",
                "IsDiscoverable": True,
                "SpatialArea": SPATIAL_AREA_WGS84,
                "CoordinateReferenceSystemID": PROJECT_CRS_ID,
            },
        }
        wpcs.append(rec)
        all_ids.append(traj_id)

    # ═══════════════════════════════════════════════════════════════════
    # 2. Activity WPCs (drilling programs)
    # ═══════════════════════════════════════════════════════════════════

    # Exploration well – drilled activities
    act_expl_id = f"{pfx}:work-product-component--Activity:OmegaSor-Drilling-34-4-19S:1"
    wpcs.append({
        "id": act_expl_id,
        "kind": "osdu:wks:work-product-component--Activity:1.0.0",
        "acl": DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": "Omega Sør – 34/4-19 S Drilling Activity (Exploration)",
            "Description": (
                "Drilling activity record for exploration well 34/4-19 S. "
                "Spudded and drilled to TD 4090 m MD / 3872 m TVD. "
                "Brent Group penetrated: Tarbert Fm + Rannoch Fm. "
                "Extensive data acquisition: cores, logs, MDT pressures. "
                "Well P&A'd after evaluation (not formation-tested)."
            ),
            "ActivityType": f"{pfx}:reference-data--WellActivityType:Drilling:",
            "WellboreID": f"{pfx}:master-data--Wellbore:34-4-19S:1",
            "Parameters": [
                {"Title": "Spud Date", "StringParameter": "2023-09-15"},
                {"Title": "TD Date", "StringParameter": "2023-11-28"},
                {"Title": "Total Depth MD", "StringParameter": "4090 m MD"},
                {"Title": "Total Depth TVD", "StringParameter": "3872 m TVD"},
                {"Title": "Casing Program", "StringParameter": "30\" conductor → 20\" surface → 13⅜\" intermediate → 9⅝\" production"},
                {"Title": "Data Acquired", "StringParameter": "Triple-combo + CMR + FMI logs, 120m core (Tarbert+Rannoch), 48 MDT points"},
                {"Title": "Result", "StringParameter": "Oil shows in Tarbert+Rannoch. Not formation-tested. Confirmed Omega Sør Alfa structure."},
            ],
        },
    })
    all_ids.append(act_expl_id)

    # Producer – planned drilling activity
    act_prod_id = f"{pfx}:work-product-component--Activity:OmegaSor-Drilling-Producer1:1"
    wpcs.append({
        "id": act_prod_id,
        "kind": "osdu:wks:work-product-component--Activity:1.0.0",
        "acl": DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": "Omega Sør – Producer 1 Drilling Program (Planned)",
            "Description": (
                "Planned drilling program for Omega Sør Producer 1. "
                "Deep CAP-X sidetrack from 34/4-19 S. "
                "8\" production flowline to Snorre N-template. "
                "Perforated in both Tarbert and Rannoch formations. "
                "Critical: pilot hole to determine barium content and confirm OWC."
            ),
            "ActivityType": f"{pfx}:reference-data--WellActivityType:Drilling:",
            "WellboreID": f"{pfx}:master-data--Wellbore:OmegaSor-Producer1:1",
            "Parameters": [
                {"Title": "Planned Spud", "StringParameter": "2028-Q1"},
                {"Title": "Well Type", "StringParameter": "Deep sidetrack (CAP-X) from 34/4-19 S"},
                {"Title": "Completion", "StringParameter": "Perforated: Tarbert + Rannoch (base case)"},
                {"Title": "Flowline", "StringParameter": "8\" production flowline to Snorre N-template"},
                {"Title": "First Oil Target", "StringParameter": "2029-01 (January)"},
                {"Title": "BHA", "StringParameter": "9⅝\" casing × 7\" liner, RSS BHA, LWD/MWD + formation evaluation suite"},
                {"Title": "Fluids", "StringParameter": "WBM (17½\" + 12¼\"), OBM (8½\" reservoir section)"},
                {"Title": "Key Risk", "StringParameter": "Barium scale risk (PIMS #00061) – pilot well required for water sampling"},
                {"Title": "Rig", "StringParameter": "Snorre A platform rig or semi-sub (TBD)"},
            ],
        },
    })
    all_ids.append(act_prod_id)

    # Injector – planned drilling activity
    act_inj_id = f"{pfx}:work-product-component--Activity:OmegaSor-Drilling-Injector1:1"
    wpcs.append({
        "id": act_inj_id,
        "kind": "osdu:wks:work-product-component--Activity:1.0.0",
        "acl": DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": "Omega Sør – Injector 1 Drilling Program (Planned)",
            "Description": (
                "Planned drilling program for Omega Sør Injector 1. "
                "Sidetrack from 4-slot template. "
                "6\" water injection flowline to Snorre N-template. "
                "Base case: perforated in Tarbert Fm only. "
                "Rannoch injection is upside contingent on depletion + fracturing."
            ),
            "ActivityType": f"{pfx}:reference-data--WellActivityType:Drilling:",
            "WellboreID": f"{pfx}:master-data--Wellbore:OmegaSor-Injector1:1",
            "Parameters": [
                {"Title": "Planned Spud", "StringParameter": "2028-Q2 (after producer)"},
                {"Title": "Well Type", "StringParameter": "Sidetrack from 4-slot subsea template"},
                {"Title": "Completion", "StringParameter": "Perforated: Tarbert Fm only (base case). Rannoch is upside."},
                {"Title": "Flowline", "StringParameter": "6\" WI flowline to Snorre N-template"},
                {"Title": "Injection Start", "StringParameter": "2029 Q2 (6 months after first oil)"},
                {"Title": "BHA", "StringParameter": "9⅝\" casing × 7\" liner, RSS BHA, LWD/MWD"},
                {"Title": "Fluids", "StringParameter": "WBM throughout (no reservoir section OBM required for injector)"},
                {"Title": "Key Risk", "StringParameter": "Injectivity uncertainty in Rannoch Fm – low permeability, deformation bands"},
            ],
        },
    })
    all_ids.append(act_inj_id)

    # ═══════════════════════════════════════════════════════════════════
    # 3. Document WPCs (reference documents)
    # ═══════════════════════════════════════════════════════════════════
    documents = [
        (
            "OmegaSor-SSVP-Presentation",
            "Omega Sør – SSVP Presentation (June 2026)",
            "Subsurface evaluation presentation for the Omega Sør Alfa WPC "
            "well decision. Contains: geological overview, reservoir model, "
            "volume estimates, production forecasts, alternatives analysis, "
            "risk register, economic evaluation, drilling plan, and schedule.",
            "20260615_OmegaSør_SSVP.pptx",
            "Presentation",
        ),
        (
            "OmegaSor-Wellbore-34-4-19S-Report",
            "Omega Sør – Wellbore 34/4-19 S Data Report",
            "Comprehensive wellbore data report for exploration well 34/4-19 S. "
            "Includes: well path, casing program, formation tops, core data, "
            "log interpretations, MDT pressures, and fluid samples.",
            "wellbore_exploration.pdf",
            "WellReport",
        ),
        (
            "OmegaSor-NOD",
            "Omega Sør – Notice of Discovery (NOD)",
            "Formal Notice of Discovery for the Omega Sør Alfa oil accumulation "
            "in block 34/4, PL057 Snorre area. Filed after evaluation of "
            "exploration well 34/4-19 S.",
            "NOD.html",
            "RegulatoryReport",
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
                    "OmegaSorProject": DATASPACE,
                },
            },
        })
        all_ids.append(doc_id)

    # ═══════════════════════════════════════════════════════════════════
    # 4. Drilling PersistedCollection (evidence bundle)
    # ═══════════════════════════════════════════════════════════════════

    # Include master-data well/wellbore IDs
    well_refs = [
        f"{pfx}:master-data--Well:34-4-19S:1",
        f"{pfx}:master-data--Wellbore:34-4-19S:1",
        f"{pfx}:master-data--Well:OmegaSor-Producer1:1",
        f"{pfx}:master-data--Wellbore:OmegaSor-Producer1:1",
        f"{pfx}:master-data--Well:OmegaSor-Injector1:1",
        f"{pfx}:master-data--Wellbore:OmegaSor-Injector1:1",
    ]

    drilling_collection_id = f"{pfx}:work-product-component--PersistedCollection:OmegaSor-Drilling-Evidence:1"
    drilling_refs = well_refs + all_ids

    wpcs.append({
        "id": drilling_collection_id,
        "kind": "osdu:wks:work-product-component--PersistedCollection:1.0.0",
        "acl": DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": "Omega Sør WPC – Drilling Evidence Package",
            "Description": (
                "Drilling-related evidence for the Omega Sør WPC well decision. "
                "Bundles: wellbore trajectories (RDDMS-linked, authoritative), "
                "drilling activity programs (exploration + 2 planned wells), "
                "reference documents (SSVP presentation, wellbore report, NOD), "
                "and master-data well/wellbore records."
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
    print(f"Drilling manifest written → {out}")
    print(f"  WellboreTrajectory : 3 (RDDMS-linked)")
    print(f"  Activity           : 3 (drilling programs)")
    print(f"  Document           : {len(documents)}")
    print(f"  PersistedCollection: 1 ({len(drilling_refs)} refs)")
    print(f"  Total WPCs         : {len(wpcs)}")


if __name__ == "__main__":
    main()
