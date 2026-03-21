#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
genparamsmanifest_dg2.py — Generate DG2 ColumnBasedTable manifest from
DG1 valysar_parameters.csv with porosity columns scaled by 0.8.

Reads DG1 CSVs and master data, produces new WPC with DG2-specific UUID.
Porosity_Floodplain, Porosity_Channel, Porosity_Crevasse all multiplied
by 0.8 to reflect updated DG2 petrophysical interpretation.

Output:
  manifest_wpcparams_dg2.json

Usage:
  py demo/drogon_dg2/genparamsmanifest_dg2.py
"""

import argparse
import csv
import json
import uuid
from pathlib import Path
from typing import Any, Dict, List

SCRIPT_DIR = Path(__file__).resolve().parent        # demo/drogon_dg2
DG1_DIR    = SCRIPT_DIR.parent / "drogon"            # demo/drogon
JSON_DIR   = SCRIPT_DIR.parent / "drogon"             # demo/drogon (shared ref data)

POROSITY_FACTOR = 0.8  # DG2 downward revision

PARAM_COLUMNS = [
    ("OilWaterContact_WestLowland",  "OilWaterContact_WestLowland",  "m",   "number"),
    ("OilWaterContact_CentralSouth", "OilWaterContact_CentralSouth", "m",   "number"),
    ("OilWaterContact_CentralNorth", "OilWaterContact_CentralNorth", "m",   "number"),
    ("OilWaterContact_NorthHorst",   "OilWaterContact_NorthHorst",   "m",   "number"),
    ("OilWaterContact_CentralRamp",  "OilWaterContact_CentralRamp",  "m",   "number"),
    ("OilWaterContact_CentralHorst", "OilWaterContact_CentralHorst", "m",   "number"),
    ("OilWaterContact_EastLowland",  "OilWaterContact_EastLowland",  "m",   "number"),
    ("Porosity_Floodplain",          "Porosity_Floodplain",          "Euc", "number"),
    ("Porosity_Channel",             "Porosity_Channel",             "Euc", "number"),
    ("Porosity_Crevasse",            "Porosity_Crevasse",            "Euc", "number"),
]

POROSITY_COLS = {"Porosity_Floodplain", "Porosity_Channel", "Porosity_Crevasse"}

import sys
if str(DG1_DIR) not in sys.path:
    sys.path.insert(0, str(DG1_DIR))
from _shared import load_json, SEGMENT_NAMES  # noqa: E402


def std_ref_id(prefix: str, entity: str, name: str) -> str:
    return f"{prefix}:reference-data--{entity}:{name}"

def wpc_id(prefix: str, entity: str, uid: str) -> str:
    return f"{prefix}:work-product-component--{entity}:{uid}:1"


def main():
    ap = argparse.ArgumentParser(description="Generate DG2 parameters ColumnBasedTable manifest (porosity ×0.8)")
    ap.add_argument("--csvfile",   default=str(DG1_DIR / "valysar_parameters.csv"))
    ap.add_argument("--masterwp",  default=str(DG1_DIR / "manifest_masterwp_drogon.json"))
    ap.add_argument("--manifest",  default=str(SCRIPT_DIR / "manifest_wpcparams_dg2.json"))
    ap.add_argument("--id-prefix", default="dev")
    args = ap.parse_args()

    with open(args.csvfile, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ValueError("CSV is empty.")

    masterwp = load_json(args.masterwp)

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

    # ── Build ColumnValues with porosity ×0.8 ───────────────────────────
    n = len(rows)
    realisations: List[int]  = []
    zones:        List[str]  = []
    segments:     List[str]  = []
    facies_list:  List[str]  = []
    value_data: Dict[str, List[float]] = {col: [] for col, _, _, _ in PARAM_COLUMNS}

    for row in rows:
        try:
            realisations.append(int(float(row.get("Realisation", "0"))))
        except (TypeError, ValueError):
            realisations.append(0)
        zones.append(row.get("Zone", ""))
        raw_seg = row.get("SegmentID", "")
        segments.append(SEGMENT_NAMES.get(raw_seg, raw_seg))
        facies_list.append(row.get("Facies", ""))

        for csv_col, _, _, _ in PARAM_COLUMNS:
            raw = row.get(csv_col, "")
            try:
                val = float(raw)
            except (TypeError, ValueError):
                val = 0.0
            # Apply 0.8 factor to porosity columns
            if csv_col in POROSITY_COLS:
                val *= POROSITY_FACTOR
            value_data[csv_col].append(round(val, 8))

    column_values: Dict[str, Any] = {
        "Realisation": realisations,
        "Zone":        zones,
        "SegmentID":   segments,
        "Facies":      facies_list,
    }
    for csv_col, _, _, _ in PARAM_COLUMNS:
        column_values[csv_col] = value_data[csv_col]

    key_columns = [
        {"ColumnName": "Realisation", "ColumnRole": "Key", "ValueType": "integer"},
        {"ColumnName": "Zone",        "ColumnRole": "Key", "ValueType": "string"},
        {"ColumnName": "SegmentID",   "ColumnRole": "Key", "ValueType": "string",
         "KindID": "osdu:wks:master-data--ReservoirSegment:2.0.0"},
        {"ColumnName": "Facies",      "ColumnRole": "Key", "ValueType": "string"},
    ]

    columns = []
    for csv_col, display_name, uom_code, val_type in PARAM_COLUMNS:
        columns.append({
            "ColumnName":      display_name,
            "ColumnRole":      "Value",
            "ValueType":       val_type,
            "UnitOfMeasureID": std_ref_id(args.id_prefix, "UnitOfMeasure", uom_code),
        })

    ancestry = {
        "parents":  [reservoir_id] if reservoir_id else [],
        "children": segment_ids,
    }

    wpc_record_id = wpc_id(args.id_prefix, "ColumnBasedTable", str(uuid.uuid4()))

    wpc = {
        "id":    wpc_record_id,
        "kind":  "osdu:wks:work-product-component--ColumnBasedTable:1.4.0",
        "acl":   acl,
        "legal": legal,
        "data": {
            "Name": "Drogon Valysar — DG2 Input Parameters (porosity revised ×0.8)",
            "Description": (
                "DG2 per-realisation input parameters for the Valysar zone. "
                "Porosity values revised downward by factor 0.8 compared to DG1 "
                "based on additional core analysis and petrophysical reinterpretation. "
                "OWC depths unchanged from DG1. "
                "3 realisations × 7 segments × 4 facies = 84 rows."
            ),
            "ParentObjectID":      reservoir_id,
            "ParentWorkProductID": workproduct_id,
            "ancestry": ancestry,
            "Table": {
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
    print(f"DG2 params manifest written → {args.manifest}")
    print(f"  WPC ID          : {wpc_record_id}")
    print(f"  Porosity factor : {POROSITY_FACTOR}")
    print(f"  Rows            : {n}")

    # Print sample porosity values for verification
    for col in sorted(POROSITY_COLS):
        vals = value_data[col]
        uniq = sorted(set(round(v, 4) for v in vals if v > 0))
        print(f"  {col}: {uniq[:5]}")


if __name__ == "__main__":
    main()
