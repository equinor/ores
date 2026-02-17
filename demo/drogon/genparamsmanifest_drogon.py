#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
genparamsmanifest_drogon.py — Generate OSDU ColumnBasedTable manifest
from valysar_parameters.csv for the Drogon / Valysar dataset.

This stores the per-realisation input parameters (OWC depths and porosities)
as a generic ColumnBasedTable WPC, using the same key column structure as the
ReservoirEstimatedVolumes manifests.

Key columns (GRAND order): Realisation, Zone, SegmentID, Facies
Value columns:
  - OilWaterContact_WestLowland … OilWaterContact_EastLowland  (m, depth)
  - Porosity_Floodplain, Porosity_Channel, Porosity_Crevasse   (fraction)

Reads:
  valysar_parameters.csv            — parameter data
  manifest_masterwp_drogon.json     — Reservoir/WP/Segment IDs

Output:
  manifest_wpcparams_drogon.json

Usage:
  py demo/drogon/genparamsmanifest_drogon.py
"""

import argparse
import csv
import json
import uuid
from pathlib import Path
from typing import Any, Dict, List

SCRIPT_DIR = Path(__file__).resolve().parent          # demo/drogon
JSON_DIR   = SCRIPT_DIR.parent / "json"               # demo/json

# ── Parameter column metadata ───────────────────────────────────────────
# (csv_column_name, display_name, UoM code, ValueType)
PARAM_COLUMNS = [
    ("OilWaterContact_WestLowland",  "OilWaterContact_WestLowland",  "m", "number"),
    ("OilWaterContact_CentralSouth", "OilWaterContact_CentralSouth", "m", "number"),
    ("OilWaterContact_CentralNorth", "OilWaterContact_CentralNorth", "m", "number"),
    ("OilWaterContact_NorthHorst",   "OilWaterContact_NorthHorst",   "m", "number"),
    ("OilWaterContact_CentralRamp",  "OilWaterContact_CentralRamp",  "m", "number"),
    ("OilWaterContact_CentralHorst", "OilWaterContact_CentralHorst", "m", "number"),
    ("OilWaterContact_EastLowland",  "OilWaterContact_EastLowland",  "m", "number"),
    ("Porosity_Floodplain",          "Porosity_Floodplain",          "Euc", "number"),
    ("Porosity_Channel",             "Porosity_Channel",             "Euc", "number"),
    ("Porosity_Crevasse",            "Porosity_Crevasse",            "Euc", "number"),
]

from _shared import load_json, SEGMENT_NAMES  # noqa: E402


def std_ref_id(prefix: str, entity: str, name: str) -> str:
    """Reference-data ID WITHOUT trailing colon."""
    return f"{prefix}:reference-data--{entity}:{name}"


def wpc_id(prefix: str, entity: str, uid: str) -> str:
    return f"{prefix}:work-product-component--{entity}:{uid}:1"


def main():
    ap = argparse.ArgumentParser(description="Generate Drogon parameters ColumnBasedTable manifest")
    ap.add_argument("--csvfile",   default=str(SCRIPT_DIR / "valysar_parameters.csv"))
    ap.add_argument("--masterwp",  default=str(SCRIPT_DIR / "manifest_masterwp_drogon.json"))
    ap.add_argument("--manifest",  default=str(SCRIPT_DIR / "manifest_wpcparams_drogon.json"))
    ap.add_argument("--id-prefix", default="dev")
    args = ap.parse_args()

    # ── Load inputs ─────────────────────────────────────────────────────
    with open(args.csvfile, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ValueError("CSV is empty.")

    masterwp = load_json(args.masterwp)

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

    # ── Build ColumnValues ──────────────────────────────────────────────
    n = len(rows)

    # Key columns
    realisations: List[int]  = []
    zones:        List[str]  = []
    segments:     List[str]  = []
    facies_list:  List[str]  = []

    # Value columns — one list per column
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
                value_data[csv_col].append(float(raw))
            except (TypeError, ValueError):
                value_data[csv_col].append(0.0)

    column_values: Dict[str, Any] = {
        "Realisation": realisations,
        "Zone":        zones,
        "SegmentID":   segments,
        "Facies":      facies_list,
    }
    for csv_col, _, _, _ in PARAM_COLUMNS:
        column_values[csv_col] = value_data[csv_col]

    # ── Key column declarations (GRAND order) ───────────────────────────
    key_columns = [
        {"ColumnName": "Realisation", "ColumnRole": "Key", "ValueType": "integer"},
        {"ColumnName": "Zone",        "ColumnRole": "Key", "ValueType": "string"},
        {"ColumnName": "SegmentID",   "ColumnRole": "Key", "ValueType": "string",
         "KindID": "osdu:wks:master-data--ReservoirSegment:2.0.0"},
        {"ColumnName": "Facies",      "ColumnRole": "Key", "ValueType": "string"},
    ]

    # ── Value column declarations ───────────────────────────────────────
    columns = []
    for csv_col, display_name, uom_code, val_type in PARAM_COLUMNS:
        col_def: Dict[str, str] = {
            "ColumnName":      display_name,
            "ColumnRole":      "Value",
            "ValueType":       val_type,
            "UnitOfMeasureID": std_ref_id(args.id_prefix, "UnitOfMeasure", uom_code),
        }
        columns.append(col_def)

    # ── Ancestry ────────────────────────────────────────────────────────
    ancestry = {
        "parents":  [reservoir_id] if reservoir_id else [],
        "children": segment_ids,
    }

    # ── WPC record ──────────────────────────────────────────────────────
    wpc_record_id = wpc_id(args.id_prefix, "ColumnBasedTable", str(uuid.uuid4()))

    wpc = {
        "id":    wpc_record_id,
        "kind":  "osdu:wks:work-product-component--ColumnBasedTable:1.4.0",
        "acl":   acl,
        "legal": legal,
        "data": {
            "Name": "Drogon Valysar — Input Parameters (per realisation)",
            "Description": (
                "Per-realisation input parameters for the Valysar zone of the Drogon field. "
                "OWC depths (7 segments) and porosity (3 facies), "
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
    print(f"  Kind   : osdu:wks:work-product-component--ColumnBasedTable:1.4.0")
    print(f"  Rows   : {n}")
    print(f"  Keys   : Realisation, Zone, SegmentID, Facies")
    owc_cols = [c for c, _, u, _ in PARAM_COLUMNS if u == "m"]
    por_cols = [c for c, _, u, _ in PARAM_COLUMNS if u == "Euc"]
    print(f"  OWC    : {len(owc_cols)} columns ({', '.join(owc_cols)})")
    print(f"  Poro   : {len(por_cols)} columns ({', '.join(por_cols)})")


if __name__ == "__main__":
    main()
