#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
genrawmanifest_dg2.py — Generate DG2 ReservoirEstimatedVolumes (RAW) manifest
from DG1 valysar_volumes.csv with all pore/oil/gas volume columns scaled by 0.8.

The 0.8 factor reflects the reduced porosity interpretation at DG2.
BulkOil and BulkGas are NOT scaled (rock volume unchanged).
PoreOil, HydrocarbonPoreOil, Oil, AssociatedGas, PoreGas, HydrocarbonPoreGas,
Gas, AssociatedLiquid, Pore are all scaled by 0.8.
Bulk (total) is NOT scaled.

Output:
  manifest_wpcraw_dg2.json

Usage:
  py demo/drogon_dg2/genrawmanifest_dg2.py
"""

import argparse
import csv
import json
import uuid
from pathlib import Path
from typing import Any, Dict, List

SCRIPT_DIR = Path(__file__).resolve().parent
DG1_DIR    = SCRIPT_DIR.parent / "drogon"
JSON_DIR   = SCRIPT_DIR.parent / "drogon"             # demo/drogon (shared ref data)

VOLUME_FACTOR = 0.8

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
    ("AssociatedLiquid",   "AssociatedLiquid","m3"),
    ("Bulk",               "Bulk",            "m3"),
    ("Pore",               "Pore",            "m3"),
]

# Columns that are scaled — pore-dependent volumes.  Bulk rock volumes stay unchanged.
SCALED_COLS = {
    "PoreOil", "HydrocarbonPoreOil", "Oil", "AssociatedGas",
    "PoreGas", "HydrocarbonPoreGas", "Gas", "AssociatedLiquid", "Pore",
}

import sys
if str(DG1_DIR) not in sys.path:
    sys.path.insert(0, str(DG1_DIR))
from _shared import load_json, SEGMENT_NAMES  # noqa: E402

def ref_id(prefix: str, entity: str, name: str) -> str:
    return f"{prefix}:reference-data--{entity}:{name}:"

def std_ref_id(prefix: str, entity: str, name: str) -> str:
    return f"{prefix}:reference-data--{entity}:{name}"

def wpc_id(prefix: str, entity: str, uid: str) -> str:
    return f"{prefix}:work-product-component--{entity}:{uid}:1"


def main():
    ap = argparse.ArgumentParser(description="Generate DG2 RAW REV manifest (volumes ×0.8)")
    ap.add_argument("--csvfile",   default=str(DG1_DIR / "valysar_volumes.csv"))
    ap.add_argument("--masterwp",  default=str(DG1_DIR / "manifest_masterwp_drogon.json"))
    ap.add_argument("--reftypes",  default=str(JSON_DIR / "reftypes_revpropertytypes.json"))
    ap.add_argument("--manifest",  default=str(SCRIPT_DIR / "manifest_wpcraw_dg2.json"))
    ap.add_argument("--id-prefix", default="dev")
    args = ap.parse_args()

    with open(args.csvfile, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ValueError("CSV is empty.")

    masterwp = load_json(args.masterwp)
    reftypes = load_json(args.reftypes)

    reservoir_id = workproduct_id = ""
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

    property_type_map: Dict[str, str] = {}
    for ref in reftypes.get("ReferenceData", []):
        if "ReservoirEstimatedVolumePropertyType" in ref.get("kind", ""):
            code = ref["data"].get("Code", ref["data"].get("Name"))
            property_type_map[code] = ref["id"]

    n = len(rows)
    realisations: List[int]   = []
    zones:        List[str]   = []
    segments:     List[str]   = []
    facies_list:  List[str]   = []
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
                val = float(raw)
            except (TypeError, ValueError):
                val = 0.0
            if col_name in SCALED_COLS:
                val *= VOLUME_FACTOR
            value_data[col_name].append(round(val, 3))

    column_values: Dict[str, Any] = {
        "Realisation": realisations,
        "Zone":        zones,
        "SegmentID":   segments,
        "Facies":      facies_list,
    }
    for col_name, _, _ in VOLUME_COLUMNS:
        column_values[col_name] = value_data[col_name]

    key_columns = [
        {"ColumnName": "Realisation", "ColumnRole": "Key", "ValueType": "integer"},
        {"ColumnName": "Zone",        "ColumnRole": "Key", "ValueType": "string"},
        {"ColumnName": "SegmentID",   "ColumnRole": "Key", "ValueType": "string",
         "KindID": "osdu:wks:master-data--ReservoirSegment:2.0.0"},
        {"ColumnName": "Facies",      "ColumnRole": "Key", "ValueType": "string"},
    ]

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

    ancestry = {
        "parents":  [reservoir_id] if reservoir_id else [],
        "children": segment_ids,
    }

    wpc_record_id = wpc_id(args.id_prefix, "ReservoirEstimatedVolumes", str(uuid.uuid4()))

    wpc = {
        "id":    wpc_record_id,
        "kind":  "osdu:wks:work-product-component--ReservoirEstimatedVolumes:1.1.0",
        "acl":   acl,
        "legal": legal,
        "data": {
            "Name": "Drogon Valysar — DG2 Reservoir Estimated Volumes (RAW, per realisation, ×0.8)",
            "Description": (
                "DG2 uncertainty realisation table for the Valysar zone. "
                "Pore-dependent volume columns (PoreOil, Oil, Gas, etc.) scaled by 0.8 "
                "relative to DG1 to reflect revised porosity interpretation. "
                "Bulk rock volumes unchanged. 12 columns, 3 realisations × 7 segments × 4 facies."
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
    print(f"DG2 RAW manifest written → {args.manifest}")
    print(f"  WPC ID        : {wpc_record_id}")
    print(f"  Volume factor : {VOLUME_FACTOR}")
    print(f"  Scaled cols   : {sorted(SCALED_COLS)}")
    print(f"  Rows          : {n}")


if __name__ == "__main__":
    main()
