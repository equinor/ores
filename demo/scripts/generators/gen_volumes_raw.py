"""
gen_volumes_raw.py - Generic ReservoirEstimatedVolumes RAW from CSV.

Reads a CSV with per-realisation volume data and builds an OSDU
ReservoirEstimatedVolumes WPC with embedded ColumnValues.

Spec format:
{
  "generator": "volumes_raw",
  "csv_file": "valysar_volumes.csv",
  "name": "Drogon Valysar - Reservoir Estimated Volumes (RAW)",
  "description": "...",
  "key_columns": [
    {"ColumnName": "Realisation", "ColumnRole": "Key", "ValueType": "integer"},
    {"ColumnName": "Zone", "ColumnRole": "Key", "ValueType": "string"},
    {"ColumnName": "SegmentID", "ColumnRole": "Key", "ValueType": "string",
     "KindID": "osdu:wks:master-data--ReservoirSegment:2.0.0"},
    {"ColumnName": "Facies", "ColumnRole": "Key", "ValueType": "string"}
  ],
  "value_columns": [
    {"ColumnName": "BulkOil", "base_type": "Bulk", "UOM": "m3"},
    ...
  ],
  "segment_names": {"WestLowland": "West Lowland", ...},
  "segment_name_column": "SegmentID",
  "scale_factor": 1.0,
  "masterwp_manifest": "..."
}
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Dict, List

from ._common import (
    load_ref,
    load_json, det_uuid, ref_id,
    resolve_acl_legal, resolve_reservoir_id, find_id,
)
from ._registry import register


@register("volumes_raw")
def generate(
    spec: Dict[str, Any],
    pfx: str,
    base_dir: Path,
    refs: Dict[str, Any],
) -> List[Dict[str, Any]]:
    csv_rel = spec["csv_file"]
    # Resolve relative to base_dir, then try repo root
    csv_path = base_dir / csv_rel
    if not csv_path.exists():
        repo_root = Path(__file__).resolve().parent.parent.parent.parent
        alt = repo_root / csv_rel
        if alt.exists():
            csv_path = alt
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ValueError(f"CSV is empty: {csv_path}")

    masterwp = load_ref(spec, refs, "masterwp_manifest", "masterwp", base_dir)
    acl, legal = resolve_acl_legal(spec, pfx, masterwp)
    reservoir_id = resolve_reservoir_id(masterwp)
    wp_id = ""
    segment_ids: List[str] = []
    if masterwp:
        wp_id = find_id(masterwp, "work-product:")
        from ._common import find_all_ids
        segment_ids = find_all_ids(masterwp, "ReservoirSegment:")

    seg_names = spec.get("segment_names", {})
    seg_col = spec.get("segment_name_column", "SegmentID")
    scale = spec.get("scale_factor", 1.0)

    key_columns = spec.get("key_columns", [])
    value_columns = spec.get("value_columns", [])

    # Build ColumnValues from CSV rows
    col_vals: Dict[str, List] = {}
    for kc in key_columns:
        col_vals[kc["ColumnName"]] = []
    for vc in value_columns:
        col_vals[vc["ColumnName"]] = []

    for row in rows:
        for kc in key_columns:
            cn = kc["ColumnName"]
            raw = row.get(cn, "")
            if kc.get("ValueType") == "integer":
                try:
                    col_vals[cn].append(int(float(raw)))
                except (TypeError, ValueError):
                    col_vals[cn].append(0)
            else:
                # Apply segment name mapping
                if cn == seg_col:
                    raw = seg_names.get(raw, raw)
                col_vals[cn].append(raw)

        for vc in value_columns:
            cn = vc["ColumnName"]
            try:
                col_vals[cn].append(float(row.get(cn, "0")) * scale)
            except (TypeError, ValueError):
                col_vals[cn].append(0.0)

    # Column declarations for the value columns
    val_decls = []
    for vc in value_columns:
        decl: Dict[str, Any] = {
            "ColumnName": vc["ColumnName"],
            "ColumnRole": "Value",
            "ValueType": "number",
        }
        base_type = vc.get("base_type", vc["ColumnName"])
        decl["PropertyTypeID"] = ref_id(pfx, "ReservoirEstimatedVolumePropertyType", base_type)
        if vc.get("UOM"):
            decl["UnitOfMeasureID"] = f"{pfx}:reference-data--UnitOfMeasure:{vc['UOM']}:"
        val_decls.append(decl)

    uid_pfx = spec.get("uuid_prefix", "volraw")
    wpc_record_id = f"{pfx}:work-product-component--ReservoirEstimatedVolumes:{det_uuid(f'{uid_pfx}-rev')}:1"

    ancestry: Dict[str, List[str]] = {
        "parents": [reservoir_id] if reservoir_id else [],
        "children": segment_ids,
    }

    data: Dict[str, Any] = {
        "Name": spec.get("name", "Reservoir Estimated Volumes (RAW)"),
        "Description": spec.get("description", ""),
        "EstimatedVolumeTypeID": f"{pfx}:reference-data--ReservoirEstimatedVolumeType:EstimatedInPlaceVolumes:",
        "ParentObjectID": reservoir_id,
        "ParentWorkProductID": wp_id,
        "ancestry": ancestry,
        "Volumes": {
            "Columns": list(key_columns) + val_decls,
            "ColumnValues": col_vals,
        },
    }

    return [{
        "id": wpc_record_id,
        "kind": "osdu:wks:work-product-component--ReservoirEstimatedVolumes:1.1.0",
        "acl": acl, "legal": legal, "data": data,
    }]


