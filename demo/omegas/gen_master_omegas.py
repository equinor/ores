#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_master_omegas.py - Generate Reservoir + Well + Wellbore master-data for
Omega Sør (Snorre, block 34/4), plus a WorkProduct container.

Creates OSDU hierarchy:
  Reservoir (Omega Sør Alfa) → ReservoirSegment (Tarbert, Rannoch)
  Well (34/4-19 S) → Wellbore (exploration)
  Well (Omega Sør Producer) → Wellbore (planned)
  Well (Omega Sør Injector) → Wellbore (planned)

Output: manifest_master_omegas.json

Usage:
  python demo/omegas/gen_master_omegas.py
"""
from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path
from typing import Any, Dict, List

from demo.eqn.omegas._shared import (
    SCRIPT_DIR, DEFAULT_ACL, DEFAULT_LEGAL, ID_PREFIX,
    ZONE_NAMES, SPATIAL_AREA_WGS84, PROJECT_CRS_ID,
    FIELD_NAME, DISCOVERY_NAME, LICENCE, BLOCK, WELL_EXPLORATION,
    OPERATOR, WATER_DEPTH_M,
)


def _uid() -> str:
    return str(uuid.uuid4())


def _md_id(pfx: str, entity: str, name: str) -> str:
    return f"{pfx}:master-data--{entity}:{name}:1"


def _wp_id(pfx: str, name: str) -> str:
    return f"{pfx}:work-product:{name}:1"


def main():
    ap = argparse.ArgumentParser(description="Generate Omega Sør master-data manifest")
    ap.add_argument("--manifest", default=str(SCRIPT_DIR / "manifest_master_omegas.json"))
    ap.add_argument("--id-prefix", default=ID_PREFIX)
    args = ap.parse_args()

    pfx = args.id_prefix

    # ── IDs ─────────────────────────────────────────────────────────────
    reservoir_id = _md_id(pfx, "Reservoir", "OmegaSorAlfa")
    seg_tarbert_id = _md_id(pfx, "ReservoirSegment", "OmegaSor-Tarbert")
    seg_rannoch_id = _md_id(pfx, "ReservoirSegment", "OmegaSor-Rannoch")
    workproduct_id = _wp_id(pfx, "OmegaSor-ReservoirStudy")

    # Exploration well (existing)
    well_expl_id = _md_id(pfx, "Well", "34-4-19S")
    wellbore_expl_id = _md_id(pfx, "Wellbore", "34-4-19S")

    # Planned wells (WPC decision)
    well_prod_id = _md_id(pfx, "Well", "OmegaSor-Producer1")
    wellbore_prod_id = _md_id(pfx, "Wellbore", "OmegaSor-Producer1")
    well_inj_id = _md_id(pfx, "Well", "OmegaSor-Injector1")
    wellbore_inj_id = _md_id(pfx, "Wellbore", "OmegaSor-Injector1")

    # ── Reservoir + Segments ────────────────────────────────────────────
    reservoir = {
        "id": reservoir_id,
        "kind": "osdu:wks:master-data--Reservoir:2.0.0",
        "acl": DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": "Omega Sør Alfa",
            "Description": (
                "Oil accumulation in the Brent Group (Tarbert and Rannoch formations), "
                "block 34/4, PL057 Snorre area. Discovery well 34/4-19 S. "
                "Middle Jurassic shallow-marine to fluvial-deltaic sandstones. "
                "STOIIP mean 19.3 MSm³ oil."
            ),
            "FieldID": f"{pfx}:master-data--Field:{FIELD_NAME}:",
            "DiscoveryID": f"{pfx}:master-data--Discovery:{DISCOVERY_NAME.replace(' ', '')}:",
            "CountryID": f"{pfx}:reference-data--Country:NO:",
            "SpatialArea": SPATIAL_AREA_WGS84,
            "CoordinateReferenceSystemID": PROJECT_CRS_ID,
            "ancestry": {
                "parents": [],
                "children": [seg_tarbert_id, seg_rannoch_id],
            },
        },
    }

    seg_tarbert = {
        "id": seg_tarbert_id,
        "kind": "osdu:wks:master-data--ReservoirSegment:2.0.0",
        "acl": DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": "Omega Sør – Tarbert Fm",
            "Description": (
                "Omega Sør Alfa reservoir segment. "
                "Upper Brent Group - Tarbert Formation. Shallow-marine, "
                "very fine- to fine-grained silty sandstone, micaceous, "
                "horizontal parallel bedding. STOIIP ~7.2 MSm³."
            ),
            "ancestry": {"parents": [reservoir_id], "children": []},
        },
    }

    seg_rannoch = {
        "id": seg_rannoch_id,
        "kind": "osdu:wks:master-data--ReservoirSegment:2.0.0",
        "acl": DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": "Omega Sør – Rannoch Fm",
            "Description": (
                "Omega Sør Alfa reservoir segment. "
                "Lower Brent Group - Rannoch Formation. Shallow-marine sandstones. "
                "Higher permeability uncertainty, potential injectivity issues. "
                "STOIIP ~10.8 MSm³. Deformation bands present near ISF."
            ),
            "ancestry": {"parents": [reservoir_id], "children": []},
        },
    }

    # ── Wells ───────────────────────────────────────────────────────────
    well_expl = {
        "id": well_expl_id,
        "kind": "osdu:wks:master-data--Well:1.0.0",
        "acl": DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": "34/4-19 S",
            "FacilityName": "34/4-19 S",
            "Description": (
                "Exploration well - Omega Sør Alfa discovery. "
                "Brent Group (Tarbert + Rannoch). "
                "Not formation-tested but extensive data acquisition."
            ),
            "FacilityOperator": OPERATOR,
            "WellType": "Exploration",
            "StatusID": f"{pfx}:reference-data--WellStatus:PluggedAndAbandoned:",
            "WaterDepth": {"Value": WATER_DEPTH_M, "UnitOfMeasureID": f"{pfx}:reference-data--UnitOfMeasure:m:"},
            "Block": BLOCK,
            "Licence": LICENCE,
            "SpatialArea": SPATIAL_AREA_WGS84,
            "CoordinateReferenceSystemID": PROJECT_CRS_ID,
        },
    }

    wellbore_expl = {
        "id": wellbore_expl_id,
        "kind": "osdu:wks:master-data--Wellbore:1.0.0",
        "acl": DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": "34/4-19 S (wellbore)",
            "FacilityName": "34/4-19 S (Omega Sør Alfa)",
            "Description": "Omega Sør Alfa discovery well 34/4-19 S – main bore. TD 3872 m TVD / 4090 m MD.",
            "WellID": well_expl_id,
            "TotalDepthMeasured": {"Value": 4090.0, "UnitOfMeasureID": f"{pfx}:reference-data--UnitOfMeasure:m:"},
            "TotalDepthVertical": {"Value": 3872.0, "UnitOfMeasureID": f"{pfx}:reference-data--UnitOfMeasure:m:"},
            "PurposeID": f"{pfx}:reference-data--WellborePurpose:Exploration:",
            "SequenceNumber": 1,
            "SpatialArea": SPATIAL_AREA_WGS84,
        },
    }

    well_prod = {
        "id": well_prod_id,
        "kind": "osdu:wks:master-data--Well:1.0.0",
        "acl": DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": "Omega Sør Producer 1",
            "FacilityName": "Omega Sør Producer 1",
            "Description": (
                "Planned production well – deep sidetrack from 34/4-19 S via CAP-X. "
                "Targets Tarbert and Rannoch formations. Phase 1 keeper producer."
            ),
            "FacilityOperator": OPERATOR,
            "WellType": "Development",
            "StatusID": f"{pfx}:reference-data--WellStatus:Planned:",
            "WaterDepth": {"Value": WATER_DEPTH_M, "UnitOfMeasureID": f"{pfx}:reference-data--UnitOfMeasure:m:"},
            "Block": BLOCK,
            "Licence": LICENCE,
            "SpatialArea": SPATIAL_AREA_WGS84,
            "CoordinateReferenceSystemID": PROJECT_CRS_ID,
        },
    }

    wellbore_prod = {
        "id": wellbore_prod_id,
        "kind": "osdu:wks:master-data--Wellbore:1.0.0",
        "acl": DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": "Omega Sør Producer 1 (wellbore)",
            "FacilityName": "Omega Sør Producer 1 (CAP-X ST)",
            "Description": (
                "Planned producer wellbore – sidetrack from 34/4-19 S. "
                "Perforated in both Tarbert and Rannoch. 8\" production flowline."
            ),
            "WellID": well_prod_id,
            "PurposeID": f"{pfx}:reference-data--WellborePurpose:Production:",
            "SequenceNumber": 1,
            "SpatialArea": SPATIAL_AREA_WGS84,
        },
    }

    well_inj = {
        "id": well_inj_id,
        "kind": "osdu:wks:master-data--Well:1.0.0",
        "acl": DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": "Omega Sør Injector 1",
            "FacilityName": "Omega Sør Injector 1",
            "Description": (
                "Planned water injection well – from 4-slot template as sidetrack "
                "from pilot well. Targets Tarbert Fm (base case). 6\" WI flowline. "
                "Placement 5–20 m above OWC for barium scale mitigation."
            ),
            "FacilityOperator": OPERATOR,
            "WellType": "Development",
            "StatusID": f"{pfx}:reference-data--WellStatus:Planned:",
            "WaterDepth": {"Value": WATER_DEPTH_M, "UnitOfMeasureID": f"{pfx}:reference-data--UnitOfMeasure:m:"},
            "Block": BLOCK,
            "Licence": LICENCE,
            "SpatialArea": SPATIAL_AREA_WGS84,
            "CoordinateReferenceSystemID": PROJECT_CRS_ID,
        },
    }

    wellbore_inj = {
        "id": wellbore_inj_id,
        "kind": "osdu:wks:master-data--Wellbore:1.0.0",
        "acl": DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": "Omega Sør Injector 1 (wellbore)",
            "FacilityName": "Omega Sør Injector 1 (Template ST)",
            "Description": (
                "Planned injector wellbore – from 4-slot template. Base case: "
                "perforated in Tarbert only. Rannoch injection is upside "
                "(requires depletion + fracturing)."
            ),
            "WellID": well_inj_id,
            "PurposeID": f"{pfx}:reference-data--WellborePurpose:Injection:",
            "SequenceNumber": 1,
            "SpatialArea": SPATIAL_AREA_WGS84,
        },
    }

    # ── WorkProduct ─────────────────────────────────────────────────────
    workproduct = {
        "id": workproduct_id,
        "kind": "osdu:wks:work-product:1.0.0",
        "acl": DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": "Omega Sør Reservoir Study",
            "Description": (
                "Parent WorkProduct for the Omega Sør Alfa field development "
                "subsurface evaluation (SSVP). Covers volumes, geomodel, "
                "well plans, and WPC decision support."
            ),
            "WorkflowStatus": "Active",
            "ancestry": {"parents": [reservoir_id], "children": []},
        },
    }

    # ── Assemble manifest ───────────────────────────────────────────────
    manifest = {
        "kind": "osdu:wks:Manifest:1.0.0",
        "ReferenceData": [],
        "MasterData": [
            reservoir, seg_tarbert, seg_rannoch,
            well_expl, wellbore_expl,
            well_prod, wellbore_prod,
            well_inj, wellbore_inj,
        ],
        "Data": {
            "Datasets": [],
            "WorkProductComponents": [],
            "WorkProducts": [workproduct],
        },
    }

    out = Path(args.manifest)
    out.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Master manifest written → {out}")
    print(f"  Reservoir      : {reservoir_id}")
    print(f"  Segments       : Tarbert, Rannoch")
    print(f"  Wells          : {WELL_EXPLORATION}, Producer 1, Injector 1")
    print(f"  WorkProduct    : {workproduct_id}")


if __name__ == "__main__":
    main()
