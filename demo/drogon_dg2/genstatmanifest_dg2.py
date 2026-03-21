#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
genstatmanifest_dg2.py — Aggregate DG2 RAW REV into statistics manifest.

Reads manifest_wpcraw_dg2.json (already scaled by 0.8) and computes
P10/P50/P90/Mean/Min/Max/StdDev, identical logic to genstatmanifest_drogon.py.

Output:
  manifest_wpcstat_dg2.json

Usage:
  py demo/drogon_dg2/genstatmanifest_dg2.py
"""

import argparse
import json
import uuid
import numpy as np
from pathlib import Path
from typing import Any, Dict, List, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
DG1_DIR    = SCRIPT_DIR.parent / "drogon"
JSON_DIR   = SCRIPT_DIR.parent / "drogon"             # demo/drogon (shared ref data)

import sys
if str(DG1_DIR) not in sys.path:
    sys.path.insert(0, str(DG1_DIR))
from _shared import load_json  # noqa: E402


def ref_id(prefix: str, entity: str, name: str) -> str:
    return f"{prefix}:reference-data--{entity}:{name}:"

def std_ref_id(prefix: str, entity: str, name: str) -> str:
    return f"{prefix}:reference-data--{entity}:{name}"

def wpc_id(prefix: str, entity: str, uid: str) -> str:
    return f"{prefix}:work-product-component--{entity}:{uid}:1"

def _pct(arr, q):
    a = np.array(arr, dtype=float); a = a[~np.isnan(a)]
    return float(np.percentile(a, q)) if a.size else float("nan")

def _mean(arr):
    a = np.array(arr, dtype=float); a = a[~np.isnan(a)]
    return float(a.mean()) if a.size else float("nan")

def _std(arr):
    a = np.array(arr, dtype=float); a = a[~np.isnan(a)]
    return float(a.std(ddof=1)) if a.size > 1 else (0.0 if a.size == 1 else float("nan"))

FACETS = ("P10", "P50", "P90", "ArithmeticMean", "Minimum", "Maximum", "StandardDeviation")


def _compute_stats(rows: List[Dict], properties: List[str]) -> Dict[str, float]:
    """Compute P10/P50/P90/Mean/Min/Max/Std across rows (one value per row)."""
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
    """Compute statistics for TOTAL rows: SUM per-realisation first, then
    compute P10/P50/P90 across those realisation-level sums."""
    reals: Dict[Any, List[Dict]] = {}
    for r in rows:
        reals.setdefault(r.get("Realisation"), []).append(r)

    real_sums: List[Dict] = []
    for real_id, grp in sorted(reals.items()):
        summed: Dict[str, float] = {}
        for p in properties:
            vals = [r.get(p, 0.0) or 0.0 for r in grp]
            summed[p] = sum(vals)
        real_sums.append(summed)

    return _compute_stats(real_sums, properties)


def build_statistics(raw_manifest: Dict, facet_roles: Dict, id_prefix: str) -> Dict:
    wpc_list = raw_manifest["Data"]["WorkProductComponents"]
    raw_wpc  = next(w for w in wpc_list
                    if "ReservoirEstimatedVolumes" in w.get("kind", ""))
    raw_data = raw_wpc["data"]
    volumes  = raw_data["Volumes"]
    colvals  = volumes["ColumnValues"]
    val_decls = volumes["Columns"]

    properties = [d["ColumnName"] for d in val_decls if d["ColumnName"] in colvals]
    prop_type_map = {d["ColumnName"]: d.get("PropertyTypeID") for d in val_decls}
    uom_map       = {d["ColumnName"]: d.get("UnitOfMeasureID") for d in val_decls}

    n = len(colvals.get("Zone", []))
    rows = [{k: colvals[k][i] for k in colvals} for i in range(n)]

    groups: Dict[Tuple, List[Dict]] = {}
    for r in rows:
        key = (r.get("SegmentID"), r.get("Zone"), r.get("Facies"))
        groups.setdefault(key, []).append(r)

    agg_rows: List[Dict[str, Any]] = []

    for (seg, zone, fac), grp in sorted(groups.items()):
        rec = {"SegmentID": seg, "Zone": zone, "Facies": fac}
        rec.update(_compute_stats(grp, properties))
        agg_rows.append(rec)

    seg_set = sorted(set(k[0] for k in groups))
    for seg in seg_set:
        grp = [r for k, v in groups.items() if k[0] == seg for r in v]
        rec = {"SegmentID": seg, "Zone": "TOTAL", "Facies": "TOTAL"}
        rec.update(_compute_total_stats(grp, properties))
        agg_rows.append(rec)

    fac_set = sorted(set(k[2] for k in groups))
    for fac in fac_set:
        grp = [r for k, v in groups.items() if k[2] == fac for r in v]
        rec = {"SegmentID": "TOTAL", "Zone": "TOTAL", "Facies": fac}
        rec.update(_compute_total_stats(grp, properties))
        agg_rows.append(rec)

    rec = {"SegmentID": "TOTAL", "Zone": "TOTAL", "Facies": "TOTAL"}
    rec.update(_compute_total_stats(rows, properties))
    agg_rows.append(rec)

    stat_colvals: Dict[str, List] = {"Zone": [], "SegmentID": [], "Facies": []}
    for facet in FACETS:
        for p in properties:
            cn = f"{p}.{facet}"
            stat_colvals[cn] = []

    for rec in agg_rows:
        stat_colvals["Zone"].append(rec["Zone"])
        stat_colvals["SegmentID"].append(rec["SegmentID"])
        stat_colvals["Facies"].append(rec["Facies"])
        for facet in FACETS:
            for p in properties:
                stat_colvals[f"{p}.{facet}"].append(rec.get(f"{p}.{facet}"))

    facet_type_id = std_ref_id(id_prefix, "FacetType", "statistics")
    facet_map = {}
    for ref in facet_roles.get("ReferenceData", []):
        if ref["data"].get("FacetType") == "statistics":
            facet_map[ref["data"]["Code"]] = ref["id"]

    stat_columns = []
    for facet in FACETS:
        for p in properties:
            stat_columns.append({
                "ColumnName":     f"{p}.{facet}",
                "ColumnRole":     "Value",
                "ValueType":      "number",
                "PropertyTypeID": prop_type_map.get(p, ref_id(id_prefix, "ReservoirEstimatedVolumePropertyType", p)),
                "UnitOfMeasureID": uom_map.get(p, std_ref_id(id_prefix, "UnitOfMeasure", "m3")),
                "FacetIDs": [{
                    "FacetTypeID": facet_type_id,
                    "FacetRoleID": facet_map.get(facet, ref_id(id_prefix, "FacetRole", facet)),
                }],
            })

    key_columns = [
        {"ColumnName": "Zone",      "ColumnRole": "Key", "ValueType": "string"},
        {"ColumnName": "SegmentID", "ColumnRole": "Key", "ValueType": "string",
         "KindID": "osdu:wks:master-data--ReservoirSegment:2.0.0"},
        {"ColumnName": "Facies",    "ColumnRole": "Key", "ValueType": "string"},
    ]

    acl   = raw_wpc.get("acl", {"owners": [], "viewers": []})
    legal = raw_wpc.get("legal", {"legaltags": [], "otherRelevantDataCountries": []})
    ancestry = raw_data.get("ancestry", {"parents": [], "children": []})

    wpc_record_id = wpc_id(id_prefix, "ReservoirEstimatedVolumes", str(uuid.uuid4()))

    return {
        "kind": "osdu:wks:Manifest:1.0.0",
        "ReferenceData": [],
        "MasterData": [],
        "Data": {
            "Datasets": [],
            "WorkProductComponents": [{
                "id":    wpc_record_id,
                "kind":  "osdu:wks:work-product-component--ReservoirEstimatedVolumes:1.1.0",
                "acl":   acl,
                "legal": legal,
                "data": {
                    "Name": "Drogon Valysar — DG2 Reservoir Estimated Volumes (statistics, ×0.8)",
                    "Description": (
                        "DG2 statistics aggregated from DG2 RAW realisations (volumes ×0.8). "
                        "Grouped by SegmentID, Zone, Facies. "
                        "Includes per-segment totals, per-facies totals, and grand total."
                    ),
                    "EstimatedVolumeTypeID": std_ref_id(
                        id_prefix, "ReservoirEstimatedVolumeType", "EstimatedInPlaceVolumes"
                    ),
                    "ParentObjectID":      raw_data.get("ParentObjectID"),
                    "ParentWorkProductID": raw_data.get("ParentWorkProductID"),
                    "ancestry": ancestry,
                    "Volumes": {
                        "ColumnBasedTableTypeID": std_ref_id(
                            id_prefix, "ColumnBasedTableType", "AdHoc"
                        ),
                        "KeyColumns":   key_columns,
                        "Columns":      stat_columns,
                        "ColumnValues": stat_colvals,
                    },
                },
            }],
            "WorkProducts": [],
        },
    }


def main():
    ap = argparse.ArgumentParser(description="Generate DG2 statistics REV manifest")
    ap.add_argument("--rawvol-manifest", default=str(SCRIPT_DIR / "manifest_wpcraw_dg2.json"))
    ap.add_argument("--facetroles",      default=str(JSON_DIR / "reftypes_facetroles.json"))
    ap.add_argument("--manifest",        default=str(SCRIPT_DIR / "manifest_wpcstat_dg2.json"))
    ap.add_argument("--id-prefix",       default="dev")
    args = ap.parse_args()

    raw    = load_json(args.rawvol_manifest)
    facets = load_json(args.facetroles)
    stat   = build_statistics(raw, facets, args.id_prefix)

    Path(args.manifest).write_text(json.dumps(stat, indent=2), encoding="utf-8")
    print(f"DG2 statistics manifest written → {args.manifest}")
    n_rows = len(stat["Data"]["WorkProductComponents"][0]["data"]["Volumes"]["ColumnValues"]["Zone"])
    n_cols = len(stat["Data"]["WorkProductComponents"][0]["data"]["Volumes"]["Columns"])
    print(f"  Rows: {n_rows}  Stat columns: {n_cols}")


if __name__ == "__main__":
    main()
