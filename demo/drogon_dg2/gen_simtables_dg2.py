#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_simtables_dg2.py - Generate OSDU ColumnBasedTable WPC records for
the Drogon DG2 simulator table outputs.

These are **catalog + schema** records (column definitions, metadata)
without embedding the full data arrays - the actual table data lives
in the RDDMS dataspace or as files referenced by DDMSDatasets.

Tables generated:
  1. Relative permeability (relperm) - per SATNUM region
  2. PVT data - per PVT region (7 regions)
  3. Eclipse summary vectors - field-level timeseries
  4. Well completion data - completion intervals
  5. Group tree - Eclipse group/well hierarchy

Reads:
  ../drogon/manifest_masterwp_drogon.json  - Reservoir, acl, legal

Output:
  manifest_simtables_dg2.json

Usage:
  python demo/drogon_dg2/gen_simtables_dg2.py
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

def _tab_uuid(name: str) -> str:
    return str(uuid.uuid5(_NS, f"dg2-simtable-{name}"))

DATASPACE_NAME = "maap/drogon_dg"
RDDMS_BASE     = f"eml:///dataspace('{DATASPACE_NAME}')"

DEFAULT_ACL = {
    "owners":  ["data.default.owners@dev.dataservices.energy"],
    "viewers": ["data.default.viewers@dev.dataservices.energy"],
}
DEFAULT_LEGAL = {
    "legaltags": ["opendes-private-usa-default"],
    "otherRelevantDataCountries": ["NO"],
}

# ── Table definitions ────────────────────────────────────────────────

RELPERM_TABLE = {
    "name": "relperm",
    "title": "Drogon DG2 - Relative Permeability (saturation functions)",
    "description": (
        "Relative permeability and capillary pressure curves per SATNUM region. "
        "Exported by RES2CSV:satfunc from Eclipse restart data. "
        "Covers water-oil (SWOF) and gas-oil (SGOF) tables for all 7 FIP regions."
    ),
    "fmu_content": "relperm",
    "key_columns": [
        {"ColumnName": "SATNUM",  "ColumnRole": "Key", "ValueType": "integer"},
        {"ColumnName": "KEYWORD", "ColumnRole": "Key", "ValueType": "string"},
    ],
    "value_columns": [
        {"ColumnName": "SW",   "ColumnRole": "Value", "ValueType": "number", "UOM": "Euc"},
        {"ColumnName": "SG",   "ColumnRole": "Value", "ValueType": "number", "UOM": "Euc"},
        {"ColumnName": "KRW",  "ColumnRole": "Value", "ValueType": "number", "UOM": "Euc"},
        {"ColumnName": "KROW", "ColumnRole": "Value", "ValueType": "number", "UOM": "Euc"},
        {"ColumnName": "KRG",  "ColumnRole": "Value", "ValueType": "number", "UOM": "Euc"},
        {"ColumnName": "KROG", "ColumnRole": "Value", "ValueType": "number", "UOM": "Euc"},
        {"ColumnName": "PCOW", "ColumnRole": "Value", "ValueType": "number", "UOM": "bar"},
        {"ColumnName": "PCOG", "ColumnRole": "Value", "ValueType": "number", "UOM": "bar"},
    ],
    "file_ref": "share/results/tables/relperm.csv",
}

PVT_TABLE = {
    "name": "pvt",
    "title": "Drogon DG2 - PVT Data (fluid properties)",
    "description": (
        "PVT data per PVT region (7 regions with distinct BO, RS, BG, RV). "
        "Exported by RES2CSV:pvt. Covers oil (PVTO) and gas (PVDG/PVTG) tables. "
        "Regions: WestLowland, CentralSouth, CentralNorth, NorthHorst, "
        "CentralRamp, CentralHorst, EastLowland."
    ),
    "fmu_content": "pvt",
    "key_columns": [
        {"ColumnName": "PVTNUM",  "ColumnRole": "Key", "ValueType": "integer"},
        {"ColumnName": "KEYWORD", "ColumnRole": "Key", "ValueType": "string"},
    ],
    "value_columns": [
        {"ColumnName": "PRESSURE",        "ColumnRole": "Value", "ValueType": "number", "UOM": "bar"},
        {"ColumnName": "VOLUMEFACTOR",     "ColumnRole": "Value", "ValueType": "number", "UOM": "Euc"},
        {"ColumnName": "VISCOSITY",        "ColumnRole": "Value", "ValueType": "number", "UOM": "cP"},
        {"ColumnName": "RS",               "ColumnRole": "Value", "ValueType": "number", "UOM": "Sm3/Sm3"},
        {"ColumnName": "RV",               "ColumnRole": "Value", "ValueType": "number", "UOM": "Sm3/Sm3"},
    ],
    "file_ref": "share/results/tables/pvt.csv",
}

SUMMARY_TABLE = {
    "name": "summary",
    "title": "Drogon DG2 - Eclipse Summary Vectors (timeseries)",
    "description": (
        "Simulator summary vectors (field and per-well rates, cumulatives, "
        "pressures, ratios, tracers) exported by RES2CSV:summary as Apache Arrow. "
        "Vectors: FOPR, FGPR, FWPR, FOPT, FGPT, FPR, FWCT, FGOR, WOPR, WBHP, "
        "RPR, ROIP, tracers (WTPRWT1/2). 31 monthly timesteps 2018-01 to 2020-07."
    ),
    "fmu_content": "timeseries",
    "key_columns": [
        {"ColumnName": "DATE", "ColumnRole": "Key", "ValueType": "datetime"},
    ],
    "value_columns": [
        {"ColumnName": "FOPR", "ColumnRole": "Value", "ValueType": "number", "UOM": "Sm3/d"},
        {"ColumnName": "FGPR", "ColumnRole": "Value", "ValueType": "number", "UOM": "Sm3/d"},
        {"ColumnName": "FWPR", "ColumnRole": "Value", "ValueType": "number", "UOM": "Sm3/d"},
        {"ColumnName": "FWIR", "ColumnRole": "Value", "ValueType": "number", "UOM": "Sm3/d"},
        {"ColumnName": "FOPT", "ColumnRole": "Value", "ValueType": "number", "UOM": "Sm3"},
        {"ColumnName": "FGPT", "ColumnRole": "Value", "ValueType": "number", "UOM": "Sm3"},
        {"ColumnName": "FWPT", "ColumnRole": "Value", "ValueType": "number", "UOM": "Sm3"},
        {"ColumnName": "FPR",  "ColumnRole": "Value", "ValueType": "number", "UOM": "bar"},
        {"ColumnName": "FWCT", "ColumnRole": "Value", "ValueType": "number", "UOM": "Euc"},
        {"ColumnName": "FGOR", "ColumnRole": "Value", "ValueType": "number", "UOM": "Sm3/Sm3"},
    ],
    "file_ref": "share/results/tables/ecl_summary/DROGON.arrow",
}

WELL_COMPLETIONS_TABLE = {
    "name": "wellcompletiondata",
    "title": "Drogon DG2 - Well Completion Data",
    "description": (
        "Well completion intervals, connection factors, skin, and transmissibility "
        "per well per timestep. Exported by RES2CSV:wellcompletiondata as Arrow. "
        "Wells: 55_33-1 (appraisal), A1-A4 (producers), A5-A6 (injectors)."
    ),
    "fmu_content": "well_completions",
    "key_columns": [
        {"ColumnName": "WELL",  "ColumnRole": "Key", "ValueType": "string"},
        {"ColumnName": "DATE",  "ColumnRole": "Key", "ValueType": "datetime"},
        {"ColumnName": "I",     "ColumnRole": "Key", "ValueType": "integer"},
        {"ColumnName": "J",     "ColumnRole": "Key", "ValueType": "integer"},
        {"ColumnName": "K",     "ColumnRole": "Key", "ValueType": "integer"},
    ],
    "value_columns": [
        {"ColumnName": "OP/SH", "ColumnRole": "Value", "ValueType": "string"},
        {"ColumnName": "CF",    "ColumnRole": "Value", "ValueType": "number", "UOM": "m3/d/bar"},
        {"ColumnName": "KH",    "ColumnRole": "Value", "ValueType": "number", "UOM": "mD.m"},
        {"ColumnName": "SKIN",  "ColumnRole": "Value", "ValueType": "number", "UOM": "Euc"},
    ],
    "file_ref": "share/results/tables/wellcompletiondata.arrow",
}

GRUPTREE_TABLE = {
    "name": "gruptree",
    "title": "Drogon DG2 - Group Tree (well hierarchy)",
    "description": (
        "Eclipse group/well hierarchy per timestep. "
        "Exported by RES2CSV:gruptree as CSV."
    ),
    "fmu_content": "table",
    "key_columns": [
        {"ColumnName": "DATE",   "ColumnRole": "Key", "ValueType": "datetime"},
        {"ColumnName": "CHILD",  "ColumnRole": "Key", "ValueType": "string"},
    ],
    "value_columns": [
        {"ColumnName": "PARENT",  "ColumnRole": "Value", "ValueType": "string"},
        {"ColumnName": "KEYWORD", "ColumnRole": "Value", "ValueType": "string"},
    ],
    "file_ref": "share/results/tables/gruptree.csv",
}

ALL_TABLES = [RELPERM_TABLE, PVT_TABLE, SUMMARY_TABLE, WELL_COMPLETIONS_TABLE, GRUPTREE_TABLE]


def main():
    ap = argparse.ArgumentParser(description="Generate DG2 simulator table WPC records")
    ap.add_argument("--masterwp",  default=str(DG1_DIR / "manifest_masterwp_drogon.json"))
    ap.add_argument("--manifest",  default=str(SCRIPT_DIR / "manifest_simtables_dg2.json"))
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

    for tbl in ALL_TABLES:
        tab_id = f"{pfx}:work-product-component--ColumnBasedTable:{_tab_uuid(tbl['name'])}:1"

        all_columns = tbl["key_columns"] + [
            {k: v for k, v in col.items() if k != "UOM"}
            | ({"UnitOfMeasureID": f"{pfx}:reference-data--UnitOfMeasure:{col['UOM']}:"} if "UOM" in col else {})
            for col in tbl["value_columns"]
        ]

        record: Dict[str, Any] = {
            "id":   tab_id,
            "kind": "osdu:wks:work-product-component--ColumnBasedTable:1.4.0",
            "acl":  acl,
            "legal": legal,
            "data": {
                "Name": tbl["title"],
                "Description": tbl["description"],
                "ReservoirID": reservoir_id,
                "ColumnBasedTableTypeID": f"{pfx}:reference-data--ColumnBasedTableType:AdHoc:",
                "Columns": all_columns,
                "DDMSDatasets": [
                    f"{RDDMS_BASE}/{tbl['file_ref']}"
                ],
                "FMU": {
                    "Content": tbl["fmu_content"],
                    "FileReference": tbl["file_ref"],
                },
                "data.ancestry.inputs": [dataspace_id],
            },
        }
        records.append(record)

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
    print(f"DG2 Simulator tables manifest written → {args.manifest}")
    print(f"  Tables: {len(records)}")
    for tbl in ALL_TABLES:
        print(f"    - {tbl['name']}: {tbl['title']}")


if __name__ == "__main__":
    main()
