#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_polygons_dg2.py - Generate OSDU GenericRepresentation WPC catalog
records for the Drogon DG2 polygon/line outputs.

Polygons:
  - Fault lines (4 horizons: TopVolantis, TopTherys, TopVolon, BaseVolantis)
  - Field outline
  - Fluid contact outlines (GOC, FWL)

The actual polygon data lives in the RDDMS dataspace or as CSV files.
These are OSDU catalog records referencing the RDDMS store.

Reads:
  ../drogon/manifest_masterwp_drogon.json  - Reservoir, acl, legal

Output:
  manifest_polygons_dg2.json

Usage:
  python demo/drogon_dg2/gen_polygons_dg2.py
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

_NS = uuid.UUID("a0000000-d509-4e00-8000-000000000000")

def _poly_uuid(name: str) -> str:
    return str(uuid.uuid5(_NS, f"dg2-polygon-{name}"))

DATASPACE_NAME = "maap/drogon_dg"
RDDMS_BASE     = f"eml:///dataspace('{DATASPACE_NAME}')"
CRS_ID         = "ST_WGS84_UTM37N_P32637"

DEFAULT_ACL = {
    "owners":  ["data.ores.owners@dev.dataservices.energy"],
    "viewers": ["data.office.global.viewers@dev.dataservices.energy"],
}
DEFAULT_LEGAL = {
    "legaltags": ["dev-equinor-private-default"],
    "otherRelevantDataCountries": ["NO"],
}

# ── Polygon definitions ─────────────────────────────────────────────

FAULT_HORIZONS = ["TopVolantis", "TopTherys", "TopVolon", "BaseVolantis"]

POLYGONS: List[Dict[str, str]] = [
    # Field outline
    {
        "name": "field_outline",
        "title": "Drogon DG2 - Field Outline",
        "description": "Field boundary polygon for the Drogon reservoir. Standard result: field_outline.",
        "content": "field_outline",
        "standard_result": "field_outline",
    },
    # Fluid contact outlines
    {
        "name": "fluid_contact_outline_goc",
        "title": "Drogon DG2 - Fluid Contact Outline (GOC)",
        "description": "Gas-oil contact outline polygon.",
        "content": "fluid_contact",
        "standard_result": "fluid_contact_outline",
    },
    {
        "name": "fluid_contact_outline_fwl",
        "title": "Drogon DG2 - Fluid Contact Outline (FWL)",
        "description": "Free water level outline polygon.",
        "content": "fluid_contact",
        "standard_result": "fluid_contact_outline",
    },
]


def main():
    ap = argparse.ArgumentParser(description="Generate DG2 polygon WPC catalog records")
    ap.add_argument("--masterwp",  default=str(DG1_DIR / "manifest_masterwp_drogon.json"))
    ap.add_argument("--manifest",  default=str(SCRIPT_DIR / "manifest_polygons_dg2.json"))
    ap.add_argument("--id-prefix", default="dev")
    args = ap.parse_args()

    pfx = args.id_prefix
    masterwp = load_json(args.masterwp)

    reservoir_id = ""
    acl = DEFAULT_ACL
    legal = DEFAULT_LEGAL
    for md in masterwp.get("MasterData", []):
        if "master-data--Reservoir:" in md.get("kind", ""):
            reservoir_id = md["id"]
            acl = md["acl"]
            legal = md["legal"]

    dataspace_id = f"{pfx}:dataset--ETPDataspace:maap-drogon_dg:1"
    records: List[Dict[str, Any]] = []

    # ── Fault lines per horizon ─────────────────────────────────
    for hz in FAULT_HORIZONS:
        hz_lower = hz.lower()
        name = f"{hz_lower}--faultlines"
        poly_id = f"{pfx}:work-product-component--GenericRepresentation:{_poly_uuid(name)}:1"
        records.append({
            "id":   poly_id,
            "kind": "osdu:wks:work-product-component--GenericRepresentation:1.0.0",
            "acl":  acl,
            "legal": legal,
            "data": {
                "Name": f"Drogon DG2 - Fault Lines at {hz}",
                "Description": (
                    f"Fault line polygons at {hz} horizon. "
                    "Standard result: structure_depth_fault_lines."
                ),
                "CoordinateReferenceSystemID": f"{pfx}:reference-data--CoordinateReferenceSystem:{CRS_ID}:",
                "ReservoirID": reservoir_id,
                "DDMSDatasets": [
                    f"{RDDMS_BASE}/polygons/{hz_lower}--faultlines.csv"
                ],
                "FMU": {
                    "Content": "polygons",
                    "PropertyAttribute": "fault_lines",
                    "HorizonName": hz,
                    "StandardResult": "structure_depth_fault_lines",
                },
                "data.ancestry.inputs": [dataspace_id],
            },
        })

    # ── Other polygons (field outline, fluid contacts) ──────────
    for poly in POLYGONS:
        poly_id = f"{pfx}:work-product-component--GenericRepresentation:{_poly_uuid(poly['name'])}:1"
        data: Dict[str, Any] = {
            "Name": poly["title"],
            "Description": poly["description"],
            "CoordinateReferenceSystemID": f"{pfx}:reference-data--CoordinateReferenceSystem:{CRS_ID}:",
            "ReservoirID": reservoir_id,
            "DDMSDatasets": [
                f"{RDDMS_BASE}/polygons/{poly['name']}.csv"
            ],
            "FMU": {
                "Content": "polygons",
                "PropertyAttribute": poly["content"],
                "StandardResult": poly["standard_result"],
            },
            "data.ancestry.inputs": [dataspace_id],
        }
        records.append({
            "id":   poly_id,
            "kind": "osdu:wks:work-product-component--GenericRepresentation:1.0.0",
            "acl":  acl,
            "legal": legal,
            "data": data,
        })

    # ── Assemble manifest ────────────────────────────────────────
    manifest: Dict[str, Any] = {
        "kind": "osdu:wks:Manifest:1.0.0",
        "ReferenceData": [],
        "MasterData": [],
        "Data": {
            "Datasets": [],
            "WorkProductComponents": records,
            "WorkProducts": [],
        },
    }

    out = Path(args.manifest)
    out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"DG2 Polygons manifest written → {args.manifest}")
    print(f"  Fault line records   : {len(FAULT_HORIZONS)}")
    print(f"  Other polygon records: {len(POLYGONS)}")
    print(f"  Total                : {len(records)}")


if __name__ == "__main__":
    main()
