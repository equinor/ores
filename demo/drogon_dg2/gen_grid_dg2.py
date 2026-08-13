#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_grid_dg2.py - Generate OSDU IjkGridRepresentation + grid property WPC
catalog records for the Drogon DG2 geomodel.

The actual grid geometry and property arrays live in the RDDMS dataspace
(eml:///dataspace(maap/drogon_dg)), exported from RMS via resqpy.
This generator creates OSDU **catalog records** that reference the RDDMS
objects, enabling search/query via OSDU while data is served by ETP.

Grid: 92 × 146 × 69  (3 zones: Valysar k0-19, Therys k20-53, Volon k54-68)
Properties: PHIT, KLOGH, KV, SW, SWL, SG, VSH, FACIES, REGION, ZONE

Reads:
  ../drogon/manifest_masterwp_drogon.json  - Reservoir, acl, legal
  manifest_activity_dg2.json               - Activity ID (provenance)

Output:
  manifest_grid_dg2.json

Usage:
  python demo/drogon_dg2/gen_grid_dg2.py
"""

from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path
from typing import Any, Dict, List

SCRIPT_DIR = Path(__file__).resolve().parent
DG1_DIR    = SCRIPT_DIR.parent / "drogon"

import sys
if str(DG1_DIR) not in sys.path:
    sys.path.insert(0, str(DG1_DIR))
from _shared import load_json  # noqa: E402

# ── Stable deterministic UUIDs ──────────────────────────────────────
_NS = uuid.UUID("a0000000-d509-4e00-8000-000000000000")
GRID_UUID     = str(uuid.uuid5(_NS, "dg2-geogrid"))

def _prop_uuid(name: str) -> str:
    return str(uuid.uuid5(_NS, f"dg2-geogrid-{name}"))

# ── RDDMS dataspace (same as Activity generator) ───────────────────
DATASPACE_NAME = "maap/drogon_dg"
RDDMS_BASE     = f"eml:///dataspace('{DATASPACE_NAME}')"

# ── Grid geometry ────────────────────────────────────────────────────
GRID_NI, GRID_NJ, GRID_NK = 92, 146, 69
ZONES = [
    {"Name": "Valysar", "KStart": 0,  "KEnd": 19},
    {"Name": "Therys",  "KStart": 20, "KEnd": 53},
    {"Name": "Volon",   "KStart": 54, "KEnd": 68},
]

# ── Grid properties ─────────────────────────────────────────────────
# (name, attribute, uom, is_discrete, description)
GRID_PROPERTIES: List[tuple] = [
    ("phit",    "porosity",                "Euc",   False, "Total porosity (PHIT)"),
    ("klogh",   "permeability",            "mD",    False, "Horizontal log-permeability (KLOGH)"),
    ("kv",      "permeability_vertical",   "mD",    False, "Vertical permeability (Kv)"),
    ("sw",      "saturation_water",        "Euc",   False, "Initial water saturation (Sw)"),
    ("swl",     "saturation_water_connate","Euc",   False, "Connate water saturation (Swl)"),
    ("sg",      "saturation_gas",          "Euc",   False, "Initial gas saturation (Sg)"),
    ("vsh",     "volume_shale",            "Euc",   False, "Shale volume indicator (Vsh)"),
    ("facies",  "facies",                  "Euc", True, "Facies code (discrete: Floodplain, Channel, Crevasse, …)"),
    ("region",  "region",                  "Euc", True, "Reservoir region (discrete: 7 segments)"),
    ("zone",    "zone",                    "Euc", True, "Stratigraphic zone (discrete: Valysar, Therys, Volon)"),
]

# ── CRS ─────────────────────────────────────────────────────────────
CRS_ID = "ST_WGS84_UTM37N_P32637"

DEFAULT_ACL = {
    "owners":  ["data.ores.owners@dev.dataservices.energy"],
    "viewers": ["data.office.global.viewers@dev.dataservices.energy"],
}
DEFAULT_LEGAL = {
    "legaltags": ["dev-equinor-private-default"],
    "otherRelevantDataCountries": ["NO"],
}


def _find_id(manifest: Dict, kind_fragment: str) -> str:
    for md in manifest.get("MasterData", []):
        if kind_fragment in md.get("kind", ""):
            return md["id"]
    for wpc in manifest.get("Data", {}).get("WorkProductComponents", []):
        if kind_fragment in wpc.get("kind", ""):
            return wpc["id"]
    wp = manifest.get("Data", {}).get("WorkProduct")
    if isinstance(wp, dict) and kind_fragment in wp.get("kind", ""):
        return wp["id"]
    return ""


def main():
    ap = argparse.ArgumentParser(description="Generate DG2 Grid + property WPC catalog records")
    ap.add_argument("--masterwp",  default=str(DG1_DIR / "manifest_masterwp_drogon.json"))
    ap.add_argument("--activity",  default=str(SCRIPT_DIR / "manifest_activity_dg2.json"))
    ap.add_argument("--manifest",  default=str(SCRIPT_DIR / "manifest_grid_dg2.json"))
    ap.add_argument("--id-prefix", default="dev")
    args = ap.parse_args()

    pfx = args.id_prefix
    masterwp = load_json(args.masterwp)

    reservoir_id = ""
    acl = DEFAULT_ACL
    legal = DEFAULT_LEGAL

    for md in masterwp.get("MasterData", []):
        kind = md.get("kind", "")
        if "master-data--Reservoir:" in kind:
            reservoir_id = md["id"]
            acl = md["acl"]
            legal = md["legal"]

    # Activity ID for provenance
    activity_id = ""
    act_path = Path(args.activity)
    if act_path.exists():
        act_man = load_json(str(act_path))
        activity_id = _find_id(act_man, "Activity")

    # Dataspace dataset ID
    dataspace_id = f"{pfx}:dataset--ETPDataspace:maap-drogon_dg:1"

    # ── Build IjkGridRepresentation WPC ──────────────────────────
    grid_id = f"{pfx}:work-product-component--IjkGridRepresentation:{GRID_UUID}:1"

    grid_record: Dict[str, Any] = {
        "id":   grid_id,
        "kind": "osdu:wks:work-product-component--IjkGridRepresentation:1.0.0",
        "acl":  acl,
        "legal": legal,
        "data": {
            "Name": "Drogon DG2 - Geogrid (static geomodel)",
            "Description": (
                "Corner-point grid exported from RMS (fmu-drogon tutorial 26.0.0). "
                f"{GRID_NI}×{GRID_NJ}×{GRID_NK} cells, 3 zones "
                "(Valysar k0-19, Therys k20-53, Volon k54-68), "
                "7 reservoir segments. Grid geometry stored in RDDMS dataspace "
                f"({DATASPACE_NAME}). Standard result: grid_model_static."
            ),
            "Ni": GRID_NI,
            "Nj": GRID_NJ,
            "Nk": GRID_NK,
            "KDirection": "down",
            "Handedness": "right",
            "CoordinateReferenceSystemID": f"{pfx}:reference-data--CoordinateReferenceSystem:{CRS_ID}:",
            "ReservoirID": reservoir_id,
            "DDMSDatasets": [
                f"{RDDMS_BASE}/resqml22.IjkGridRepresentation('{GRID_UUID}')"
            ],
            "Zones": [
                {"Name": z["Name"], "KStart": z["KStart"], "KEnd": z["KEnd"]}
                for z in ZONES
            ],
            "StandardResult": "grid_model_static",
            "FMU": {
                "CaseName": "drogon_design",
                "DataioVersion": "2.23",
                "SchemaVersion": "0.19.0",
                "Content": "grid",
            },
            "data.ancestry.inputs": [dataspace_id],
        },
    }

    # ── Build grid property WPCs ─────────────────────────────────
    property_records: List[Dict[str, Any]] = []
    property_ids: List[str] = []

    for prop_name, attribute, uom, is_discrete, description in GRID_PROPERTIES:
        prop_id = f"{pfx}:work-product-component--IjkGridRepresentation:{_prop_uuid(prop_name)}:1"
        property_ids.append(prop_id)

        prop_record: Dict[str, Any] = {
            "id":   prop_id,
            "kind": "osdu:wks:work-product-component--IjkGridRepresentation:1.0.0",
            "acl":  acl,
            "legal": legal,
            "data": {
                "Name": f"Drogon DG2 - geogrid {prop_name}",
                "Description": description,
                "SupportedByID": grid_id,
                "PropertyAttribute": attribute,
                "IsDiscrete": is_discrete,
                "UnitOfMeasureID": f"{pfx}:reference-data--UnitOfMeasure:{uom}:",
                "CoordinateReferenceSystemID": f"{pfx}:reference-data--CoordinateReferenceSystem:{CRS_ID}:",
                "ReservoirID": reservoir_id,
                "DDMSDatasets": [
                    f"{RDDMS_BASE}/resqml22.ContinuousProperty('{_prop_uuid(prop_name)}')"
                    if not is_discrete else
                    f"{RDDMS_BASE}/resqml22.DiscreteProperty('{_prop_uuid(prop_name)}')"
                ],
                "FMU": {
                    "Content": "property",
                    "PropertyAttribute": attribute,
                    "IsDiscrete": is_discrete,
                    "StandardResult": "grid_model_static",
                },
                "data.ancestry.inputs": [grid_id, dataspace_id],
            },
        }
        property_records.append(prop_record)

    # ── Assemble manifest ────────────────────────────────────────
    all_wpcs = [grid_record] + property_records

    manifest: Dict[str, Any] = {
        "kind": "osdu:wks:Manifest:1.0.0",
        "ReferenceData": [],
        "MasterData": [],
        "Data": {
            "Datasets": [],
            "WorkProductComponents": all_wpcs,
            "WorkProducts": [],
        },
    }

    out = Path(args.manifest)
    out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"DG2 Grid manifest written → {args.manifest}")
    print(f"  Grid WPC ID : {grid_id}")
    print(f"  Properties  : {len(property_records)}")
    for prop_name, _, _, _, _ in GRID_PROPERTIES:
        print(f"    - {prop_name}")
    print(f"  RDDMS base  : {RDDMS_BASE}")


if __name__ == "__main__":
    main()
