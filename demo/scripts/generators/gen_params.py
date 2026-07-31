"""
gen_params.py - Generic ColumnBasedTable from CSV or XLSX (design matrix / parameters).

Spec format:
{
  "generator": "params",
  "data_file": "valysar_parameters.csv",
  "file_type": "csv",
  "name": "Drogon Valysar - Design Matrix Parameters",
  "description": "...",
  "columns": [
    {"ColumnName": "Realisation", "ColumnRole": "Key", "ValueType": "integer"},
    {"ColumnName": "OWCVALYSAR", "ColumnRole": "Value", "ValueType": "number", "UOM": "m"}
  ],
  "masterwp_manifest": "..."
}
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Dict, List

from ._common import (
    load_ref,
    load_json, det_uuid,
    resolve_acl_legal, resolve_reservoir_id, find_id, find_all_ids,
)
from ._registry import register


@register("params")
def generate(
    spec: Dict[str, Any],
    pfx: str,
    base_dir: Path,
    refs: Dict[str, Any],
) -> List[Dict[str, Any]]:
    data_rel = spec["data_file"]
    data_path = base_dir / data_rel
    if not data_path.exists():
        repo_root = Path(__file__).resolve().parent.parent.parent.parent
        alt = repo_root / data_rel
        if alt.exists():
            data_path = alt
    file_type = spec.get("file_type", "csv")

    if file_type == "xlsx":
        rows = _read_xlsx(data_path, spec.get("sheet_name"))
    else:
        rows = _read_csv(data_path)

    if not rows:
        raise ValueError(f"Data file is empty: {data_path}")

    columns = spec["columns"]

    masterwp = load_ref(spec, refs, "masterwp_manifest", "masterwp", base_dir)
    acl, legal = resolve_acl_legal(spec, pfx, masterwp)
    reservoir_id = resolve_reservoir_id(masterwp)
    wp_id = find_id(masterwp, "work-product:") if masterwp else ""
    segment_ids = find_all_ids(masterwp, "ReservoirSegment:") if masterwp else []

    # Build ColumnValues
    col_vals: Dict[str, List] = {}
    for col in columns:
        col_vals[col["ColumnName"]] = []

    for row in rows:
        for col in columns:
            cn = col["ColumnName"]
            raw = row.get(cn, "")
            vtype = col.get("ValueType", "string")
            if vtype == "integer":
                try:
                    col_vals[cn].append(int(float(raw)))
                except (TypeError, ValueError):
                    col_vals[cn].append(0)
            elif vtype == "number":
                try:
                    col_vals[cn].append(float(raw))
                except (TypeError, ValueError):
                    col_vals[cn].append(0.0)
            else:
                col_vals[cn].append(str(raw))

    # Build column declarations with UOM expansion
    col_decls = []
    for col in columns:
        decl = {k: v for k, v in col.items() if k != "UOM"}
        if "UOM" in col:
            decl["UnitOfMeasureID"] = f"{pfx}:reference-data--UnitOfMeasure:{col['UOM']}:"
        col_decls.append(decl)

    uid_pfx = spec.get("uuid_prefix", "params")
    wpc_id = f"{pfx}:work-product-component--ColumnBasedTable:{det_uuid(f'{uid_pfx}-cbt')}:1"

    data: Dict[str, Any] = {
        "Name": spec.get("name", "Parameters"),
        "Description": spec.get("description", ""),
        "ColumnBasedTableTypeID": f"{pfx}:reference-data--ColumnBasedTableType:AdHoc:",
        "ParentObjectID": reservoir_id,
        "ParentWorkProductID": wp_id,
        "ancestry": {
            "parents": [reservoir_id] if reservoir_id else [],
            "children": segment_ids,
        },
        "Columns": col_decls,
        "ColumnValues": col_vals,
    }

    return [{
        "id": wpc_id,
        "kind": spec.get("kind", "osdu:wks:work-product-component--ColumnBasedTable:1.4.0"),
        "acl": acl, "legal": legal, "data": data,
    }]


def _read_csv(path: Path) -> List[Dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _read_xlsx(path: Path, sheet_name=None) -> List[Dict[str, Any]]:
    try:
        import openpyxl
    except ImportError:
        raise ImportError("openpyxl required for XLSX files: pip install openpyxl")
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb[sheet_name] if sheet_name else wb.active
    rows_iter = ws.iter_rows(values_only=True)
    headers = [str(h) if h else f"col{i}" for i, h in enumerate(next(rows_iter))]
    return [dict(zip(headers, row)) for row in rows_iter]


