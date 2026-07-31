"""
gen_volumes_stat.py - Aggregate RAW ReservoirEstimatedVolumes into statistics.

Groups by key columns (excluding Realisation), computes P10/P50/P90/Mean/Min/Max/StdDev
across realisations.  Adds segment-level and grand TOTALs.

Spec format:
{
  "generator": "volumes_stat",
  "raw_manifest": "manifest_wpcraw.json",
  "name": "Reservoir Estimated Volumes (STAT)",
  "description": "...",
  "group_by": ["SegmentID", "Zone", "Facies"],
  "total_columns": ["SegmentID", "Zone", "Facies"],
  "masterwp_manifest": "..."
}
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np

from ._common import (
    load_ref,
    load_json, det_uuid, ref_id,
    resolve_acl_legal, resolve_reservoir_id, find_id, find_all_ids,
)
from ._registry import register

FACETS = ("P10", "P50", "P90", "ArithmeticMean", "Minimum", "Maximum", "StandardDeviation")


def _pct(arr, q):
    a = np.array(arr, dtype=float); a = a[~np.isnan(a)]
    return float(np.percentile(a, q)) if a.size else float("nan")

def _mean(arr):
    a = np.array(arr, dtype=float); a = a[~np.isnan(a)]
    return float(a.mean()) if a.size else float("nan")

def _std(arr):
    a = np.array(arr, dtype=float); a = a[~np.isnan(a)]
    return float(a.std(ddof=1)) if a.size > 1 else (0.0 if a.size == 1 else float("nan"))


def _compute_stats(rows: List[Dict], properties: List[str]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for p in properties:
        arr = [r.get(p, float("nan")) for r in rows]
        out[f"{p}.P10"]               = _pct(arr, 10)
        out[f"{p}.P50"]               = _pct(arr, 50)
        out[f"{p}.P90"]               = _pct(arr, 90)
        out[f"{p}.ArithmeticMean"]    = _mean(arr)
        out[f"{p}.Minimum"]           = float(min(arr)) if arr else float("nan")
        out[f"{p}.Maximum"]           = float(max(arr)) if arr else float("nan")
        out[f"{p}.StandardDeviation"] = _std(arr)
    return out


def _compute_total_stats(rows: List[Dict], properties: List[str]) -> Dict[str, float]:
    """Sum per-realisation first, then compute stats across sums."""
    reals: Dict[Any, List[Dict]] = {}
    for r in rows:
        reals.setdefault(r.get("Realisation"), []).append(r)
    real_sums: List[Dict] = []
    for _, grp in sorted(reals.items()):
        summed = {p: sum(r.get(p, 0.0) or 0.0 for r in grp) for p in properties}
        real_sums.append(summed)
    return _compute_stats(real_sums, properties)


@register("volumes_stat")
def generate(
    spec: Dict[str, Any],
    pfx: str,
    base_dir: Path,
    refs: Dict[str, Any],
) -> List[Dict[str, Any]]:
    # Load RAW manifest
    raw_manifest = load_ref(spec, refs, "raw_manifest", "volumes_raw", base_dir)
    if not raw_manifest:
        raise ValueError("volumes_stat needs 'raw_manifest' path or 'volumes_raw' in refs")

    masterwp = load_ref(spec, refs, "masterwp_manifest", "masterwp", base_dir)
    acl, legal = resolve_acl_legal(spec, pfx, masterwp)
    reservoir_id = resolve_reservoir_id(masterwp)
    wp_id = find_id(masterwp, "work-product:") if masterwp else ""
    segment_ids = find_all_ids(masterwp, "ReservoirSegment:") if masterwp else []

    # Extract RAW data
    wpc_list = raw_manifest["Data"]["WorkProductComponents"]
    raw_wpc = next(w for w in wpc_list if "ReservoirEstimatedVolumes" in w.get("kind", ""))
    volumes = raw_wpc["data"]["Volumes"]
    colvals = volumes["ColumnValues"]
    val_decls = volumes["Columns"]

    properties = [
        d["ColumnName"] for d in val_decls
        if d.get("ColumnRole") == "Value" and d["ColumnName"] in colvals
    ]
    prop_type_map = {d["ColumnName"]: d.get("PropertyTypeID") for d in val_decls}
    uom_map = {d["ColumnName"]: d.get("UnitOfMeasureID") for d in val_decls}

    group_by = spec.get("group_by", ["SegmentID", "Zone", "Facies"])
    total_cols = spec.get("total_columns", group_by)

    # Flatten rows
    n = len(next(iter(colvals.values())))
    rows = [{k: colvals[k][i] for k in colvals} for i in range(n)]

    # Group by specified columns
    groups: Dict[Tuple, List[Dict]] = {}
    for r in rows:
        key = tuple(r.get(c) for c in group_by)
        groups.setdefault(key, []).append(r)

    agg_rows: List[Dict[str, Any]] = []

    # Per-group stats
    for key, grp in sorted(groups.items()):
        rec = dict(zip(group_by, key))
        rec.update(_compute_stats(grp, properties))
        agg_rows.append(rec)

    # Per-column TOTALs
    for i, col in enumerate(group_by):
        if col == "Realisation":
            continue
        other_vals = sorted(set(k[i] for k in groups))
        for val in other_vals:
            matching = [r for k, v in groups.items() if k[i] == val for r in v]
            rec = {c: "TOTAL" for c in group_by}
            rec[col] = val
            rec.update(_compute_total_stats(matching, properties))
            agg_rows.append(rec)

    # Grand TOTAL
    rec = {c: "TOTAL" for c in group_by}
    rec.update(_compute_total_stats(rows, properties))
    agg_rows.append(rec)

    # Build stat ColumnValues
    stat_colvals: Dict[str, List] = {c: [] for c in group_by if c != "Realisation"}
    for facet in FACETS:
        for p in properties:
            stat_colvals[f"{p}.{facet}"] = []

    key_cols_out = [c for c in group_by if c != "Realisation"]
    for rec in agg_rows:
        for c in key_cols_out:
            stat_colvals[c].append(rec.get(c, ""))
        for facet in FACETS:
            for p in properties:
                stat_colvals[f"{p}.{facet}"].append(rec.get(f"{p}.{facet}"))

    # Column declarations
    key_col_decls = [
        d for d in val_decls
        if d.get("ColumnRole") == "Key" and d["ColumnName"] != "Realisation"
    ]
    stat_columns = []
    facet_type_id = f"{pfx}:reference-data--FacetType:statistics:"
    for facet in FACETS:
        for p in properties:
            stat_columns.append({
                "ColumnName": f"{p}.{facet}",
                "ColumnRole": "Value",
                "ValueType": "number",
                "PropertyTypeID": prop_type_map.get(p, ref_id(pfx, "ReservoirEstimatedVolumePropertyType", p)),
                "UnitOfMeasureID": uom_map.get(p, f"{pfx}:reference-data--UnitOfMeasure:m3:"),
                "FacetIDs": [{
                    "FacetTypeID": facet_type_id,
                    "FacetRoleID": f"{pfx}:reference-data--FacetRole:{facet}:",
                }],
            })

    uid_pfx = spec.get("uuid_prefix", "volstat")
    wpc_id = f"{pfx}:work-product-component--ReservoirEstimatedVolumes:{det_uuid(f'{uid_pfx}-rev')}:1"

    data: Dict[str, Any] = {
        "Name": spec.get("name", "Reservoir Estimated Volumes (STAT)"),
        "Description": spec.get("description", ""),
        "EstimatedVolumeTypeID": f"{pfx}:reference-data--ReservoirEstimatedVolumeType:EstimatedInPlaceVolumes:",
        "ParentObjectID": reservoir_id,
        "ParentWorkProductID": wp_id,
        "ancestry": {
            "parents": [reservoir_id] if reservoir_id else [],
            "children": segment_ids,
        },
        "Volumes": {
            "Columns": key_col_decls + stat_columns,
            "ColumnValues": stat_colvals,
        },
    }

    return [{
        "id": wpc_id,
        "kind": "osdu:wks:work-product-component--ReservoirEstimatedVolumes:1.1.0",
        "acl": acl, "legal": legal, "data": data,
    }]


