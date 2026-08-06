#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
genrawmanifest_drogon.py - Generate OSDU ReservoirEstimatedVolumes (ColumnBasedTable)
manifest from valysar_volumes.csv for the Drogon / Valysar dataset.

Differences from the GRAND workflow (1genrawmanifest.py):
  - No "Phases" key column - phase is encoded in column names (BulkOil, BulkGas …)
  - Facies is a key column
  - 12 value columns with phase-qualified names
  - All UoM = m3 (matching GRAND canonical form)
  - Key column order: Realisation, Zone, SegmentID, Facies (GRAND order)

Reads:
  valysar_volumes.csv              - volume data
  manifest_masterwp_drogon.json    - Reservoir/WP/Segment IDs
  reftypes_revpropertytypes.json   - PropertyTypeID mapping

Output:
  manifest_wpcraw_drogon.json

Usage:
  py demo/drogon_dg1/genrawmanifest_drogon.py
"""

import argparse
import csv
import json
import uuid
from pathlib import Path
from typing import Any, Dict, List

SCRIPT_DIR = Path(__file__).resolve().parent          # demo/drogon
JSON_DIR   = SCRIPT_DIR                               # demo/drogon

# ── Volume column metadata ──────────────────────────────────────────────
# (canonical column name, base PropertyType code, UoM code)
VOLUME_COLUMNS = [
    ("BulkOil",            "Bulk",            "m3"),
    ("PoreOil",            "Pore",            "m3"),
    ("HydrocarbonPoreOil", "HydrocarbonPore", "m3"),
    ("Oil",                "Oil",             "m3"),
    ("AssociatedGas",      "AssociatedGas",   "m3"),
    ("BulkGas",            "Bulk",            "m3"),
    ("PoreGas",            "Pore",            "m3"),
    ("HydrocarbonPoreGas", "HydrocarbonPore", "m3"),
    ("Gas",                "Gas",             "m3"),
    ("AssociatedLiquid",   "AssociatedLiquid", "m3"),
    ("Bulk",               "Bulk",            "m3"),
    ("Pore",               "Pore",            "m3"),
]

# ── Helpers ─────────────────────────────────────────────────────────────
from _shared import load_json, SEGMENT_NAMES  # noqa: E402

def ref_id(prefix: str, entity: str, name: str) -> str:
    """Reference-data ID WITH trailing colon (for PropertyTypeID)."""
    return f"{prefix}:reference-data--{entity}:{name}:"

def std_ref_id(prefix: str, entity: str, name: str) -> str:
    """Reference-data ID with trailing colon (latest version convention)."""
    return f"{prefix}:reference-data--{entity}:{name}:"

def wpc_id(prefix: str, entity: str, uid: str) -> str:
    return f"{prefix}:work-product-component--{entity}:{uid}:1"


def main():
    ap = argparse.ArgumentParser(description="Generate Drogon RAW ReservoirEstimatedVolumes manifest")
    ap.add_argument("--csvfile",   default=str(SCRIPT_DIR / "valysar_volumes.csv"))
    ap.add_argument("--masterwp",  default=str(SCRIPT_DIR / "manifest_masterwp_drogon.json"))
    ap.add_argument("--reftypes",  default=str(JSON_DIR / "reftypes_revpropertytypes.json"))
    ap.add_argument("--manifest",  default=str(SCRIPT_DIR / "manifest_wpcraw_drogon.json"))
    ap.add_argument("--id-prefix", default="dev")
    args = ap.parse_args()

    # ── Load inputs ─────────────────────────────────────────────────────
    with open(args.csvfile, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ValueError("CSV is empty.")

    masterwp = load_json(args.masterwp)
    reftypes = load_json(args.reftypes)

    # Extract IDs from MasterWP
    reservoir_id   = ""
    workproduct_id = ""
    acl   = {"owners": [], "viewers": []}
    legal = {"legaltags": [], "otherRelevantDataCountries": []}
    segment_ids: List[str] = []

    for md in masterwp.get("MasterData", []):
        kind = md.get("kind", "")
        if "master-data--Reservoir:" in kind:
            reservoir_id = md["id"]
            acl   = md["acl"]
            legal = md["legal"]
        elif "master-data--ReservoirSegment:" in kind:
            segment_ids.append(md["id"])

    for wp in masterwp.get("Data", {}).get("WorkProducts", []):
        workproduct_id = wp.get("id", "")

    # Build property type map from reftypes: Code -> id
    property_type_map: Dict[str, str] = {}
    for ref in reftypes.get("ReferenceData", []):
        if "ReservoirEstimatedVolumePropertyType" in ref.get("kind", ""):
            code = ref["data"].get("Code", ref["data"].get("Name"))
            property_type_map[code] = ref["id"]

    # ── Build ColumnValues ──────────────────────────────────────────────
    n = len(rows)

    # Key columns
    realisations: List[int]   = []
    zones:        List[str]   = []
    segments:     List[str]   = []
    facies_list:  List[str]   = []

    # Value columns - one list per column
    value_data: Dict[str, List[float]] = {col: [] for col, _, _ in VOLUME_COLUMNS}

    for row in rows:
        try:
            realisations.append(int(float(row.get("Realisation", "0"))))
        except (TypeError, ValueError):
            realisations.append(0)
        zones.append(row.get("Zone", ""))
        raw_seg = row.get("SegmentID", "")
        segments.append(SEGMENT_NAMES.get(raw_seg, raw_seg))
        facies_list.append(row.get("Facies", ""))

        for col_name, _, _ in VOLUME_COLUMNS:
            raw = row.get(col_name, "")
            try:
                value_data[col_name].append(float(raw))
            except (TypeError, ValueError):
                value_data[col_name].append(0.0)

    column_values: Dict[str, Any] = {
        "Realisation": realisations,
        "Zone":        zones,
        "SegmentID":   segments,
        "Facies":      facies_list,
    }
    for col_name, _, _ in VOLUME_COLUMNS:
        column_values[col_name] = value_data[col_name]

    # ── Key column declarations (GRAND order: Realisation, Zone, SegmentID) ──
    key_columns = [
        {"ColumnName": "Realisation", "ColumnRole": "Key", "ValueType": "integer"},
        {"ColumnName": "Zone",        "ColumnRole": "Key", "ValueType": "string"},
        {"ColumnName": "SegmentID",   "ColumnRole": "Key", "ValueType": "string",
         "KindID": "osdu:wks:master-data--ReservoirSegment:2.0.0"},
        {"ColumnName": "Facies",      "ColumnRole": "Key", "ValueType": "string"},
    ]

    # ── Value column declarations ───────────────────────────────────────
    columns = []
    for col_name, base_type, uom_code in VOLUME_COLUMNS:
        prop_type_id = property_type_map.get(
            base_type,
            ref_id(args.id_prefix, "ReservoirEstimatedVolumePropertyType", base_type)
        )
        columns.append({
            "ColumnName":      col_name,
            "ColumnRole":      "Value",
            "ValueType":       "number",
            "PropertyTypeID":  prop_type_id,
            "UnitOfMeasureID": std_ref_id(args.id_prefix, "UnitOfMeasure", uom_code),
        })

    # ── Ancestry ────────────────────────────────────────────────────────
    ancestry = {
        "parents":  [reservoir_id] if reservoir_id else [],
        "children": segment_ids,
    }

    # ── WPC record ──────────────────────────────────────────────────────
    wpc_record_id = wpc_id(args.id_prefix, "ReservoirEstimatedVolumes", str(uuid.uuid4()))

    wpc = {
        "id":    wpc_record_id,
        "kind":  "osdu:wks:work-product-component--ReservoirEstimatedVolumes:1.1.0",
        "acl":   acl,
        "legal": legal,
        "data": {
            "Name": "Drogon - Reservoir Estimated Volumes (RAW, per realisation)",
            "Description": (
                "Uncertainty realisation table for the Valysar zone of the Drogon field. "
                "12 phase-qualified volume columns, 3 realisations × 7 segments × 4 facies."
            ),
            "EstimatedVolumeTypeID": std_ref_id(
                args.id_prefix, "ReservoirEstimatedVolumeType", "EstimatedInPlaceVolumes"
            ),
            "ParentObjectID":      reservoir_id,
            "ParentWorkProductID": workproduct_id,
            "ancestry": ancestry,
            "Volumes": {
                "ColumnBasedTableTypeID": std_ref_id(
                    args.id_prefix, "ColumnBasedTableType", "AdHoc"
                ),
                "KeyColumns":   key_columns,
                "Columns":      columns,
                "ColumnValues": column_values,
            },
        },
    }

    # ── Assemble manifest ───────────────────────────────────────────────
    manifest = {
        "kind": "osdu:wks:Manifest:1.0.0",
        "ReferenceData": [],
        "MasterData": [],
        "Data": {
            "Datasets": [],
            "WorkProductComponents": [wpc],
            "WorkProducts": [],
        },
    }

    Path(args.manifest).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Manifest written → {args.manifest}")
    print(f"  WPC ID : {wpc_record_id}")
    print(f"  Rows   : {n}")
    print(f"  Keys   : Realisation, Zone, SegmentID, Facies")
    print(f"  Values : {', '.join(c for c, _, _ in VOLUME_COLUMNS)}")


if __name__ == "__main__":
    main()
