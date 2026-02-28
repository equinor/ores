
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2genstatmanifest.py — Aggregate ReservoirEstimatedVolumes RAW manifest to a statistics ReservoirEstimatedVolumes manifest.
Includes compliance tags: acl, legal, ancestry.
"""
import argparse
import json
import uuid
import numpy as np
from typing import Any, Dict, List, Tuple

def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def ref_id(prefix: str, entity: str, name: str) -> str:
    return f"{prefix}:reference-data--{entity}:{name}"

def wpc_id(prefix: str, entity: str, name: str) -> str:
    return f"{prefix}:work-product-component--{entity}:{name}:1"

def _percentile(arr: List[float], q: float) -> float:
    a = np.array(arr, dtype=float)
    a = a[~np.isnan(a)]
    return float(np.percentile(a, q)) if a.size else float("nan")

def _safe_mean(arr: List[float]) -> float:
    a = np.array(arr, dtype=float)
    a = a[~np.isnan(a)]
    return float(a.mean()) if a.size else float("nan")

def _safe_std(arr: List[float]) -> float:
    a = np.array(arr, dtype=float)
    a = a[~np.isnan(a)]
    return float(a.std(ddof=1)) if a.size > 1 else (0.0 if a.size == 1 else float("nan"))

def _extract_raw_table(manifest: Dict[str, Any]) -> Tuple[Dict[str, List[Any]], List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    data = manifest.get("Data", {})
    wpcs = data.get("WorkProductComponents", [])
    wpc = next((w for w in wpcs if w.get("kind", "").startswith("osdu:wks:work-product-component--ReservoirEstimatedVolumes:")), None)
    if not wpc:
        raise ValueError("RAW ReservoirEstimatedVolumes WPC not found.")
    wpc_data = wpc.get("data", {})
    volumes = wpc_data.get("Volumes", {})
    return volumes.get("ColumnValues", {}), volumes.get("KeyColumns", []), volumes.get("Columns", []), wpc_data

def _compute_stats(rows: List[Dict[str, Any]], properties: List[str]) -> Dict[str, float]:
    stats = {}
    for p in properties:
        arr = [float(r.get(p, float("nan"))) for r in rows if r.get(p) is not None]
        stats[f"{p}.P10"] = _percentile(arr, 10)
        stats[f"{p}.P50"] = _percentile(arr, 50)
        stats[f"{p}.P90"] = _percentile(arr, 90)
        stats[f"{p}.ArithmeticMean"] = _safe_mean(arr)
        stats[f"{p}.Minimum"] = min(arr) if arr else float("nan")
        stats[f"{p}.Maximum"] = max(arr) if arr else float("nan")
        stats[f"{p}.StandardDeviation"] = _safe_std(arr)
    return stats

def build_statistics_manifest(raw_manifest: Dict[str, Any], facet_roles: Dict[str, Any], id_prefix: str, use_uuid: bool) -> Dict[str, Any]:
    colvals, _, val_decls, raw_wpc_data = _extract_raw_table(raw_manifest)
    properties = [d.get("ColumnName") for d in val_decls if d.get("ColumnName") in colvals]
    prop_type_map = {d.get("ColumnName"): d.get("PropertyTypeID") for d in val_decls}
    uom_id = next((d.get("UnitOfMeasureID") for d in val_decls if d.get("UnitOfMeasureID")), ref_id(id_prefix, "UnitOfMeasure", "m3"))

    # Flatten rows
    n = len(colvals.get("Zone", []))
    rows = [{k: colvals[k][i] for k in colvals} for i in range(n)]

    # Group by SegmentID, Zone
    groups = {}
    for r in rows:
        key = (r.get("SegmentID"), r.get("Zone"))
        groups.setdefault(key, []).append(r)

    agg_rows = []
    for (seg, zone), grp in groups.items():
        rec = {"SegmentID": seg, "Zone": zone}
        rec.update(_compute_stats(grp, properties))
        agg_rows.append(rec)
    # NOTE: No need to generate synthetic TOTAL rows — the raw manifest
    # already contains "Totals" rows per segment and overall, with 11
    # per-realisation values each.  Percentiles of those 11 values are the
    # correct TOTAL statistics.

    # ColumnValues
    stat_colvals = {"SegmentID": [], "Zone": []}
    for facet in ("P10", "P50", "P90", "ArithmeticMean", "Minimum", "Maximum", "StandardDeviation"):
        for p in properties:
            stat_colvals[f"{p}.{facet}"] = []
    for rec in agg_rows:
        stat_colvals["SegmentID"].append(rec["SegmentID"])
        stat_colvals["Zone"].append(rec["Zone"])
        for facet in ("P10", "P50", "P90", "ArithmeticMean", "Minimum", "Maximum", "StandardDeviation"):
            for p in properties:
                stat_colvals[f"{p}.{facet}"].append(rec.get(f"{p}.{facet}"))

    # Columns metadata
    columns = []
    facet_type_id = ref_id(id_prefix, "FacetType", "statistics")
    facet_map = {ref["data"]["Code"]: ref["id"] for ref in facet_roles.get("ReferenceData", []) if ref["data"].get("FacetType") == "statistics"}
    for facet in ("P10", "P50", "P90", "ArithmeticMean", "Minimum", "Maximum", "StandardDeviation"):
        for p in properties:
            col_name = f"{p}.{facet}"
            columns.append({
                "ColumnName": col_name,
                "ColumnRole": "Value",
                "ValueType": "number",
                "PropertyTypeID": prop_type_map.get(p, ref_id(id_prefix, "ReservoirEstimatedVolumePropertyType", p)),
                "UnitOfMeasureID": uom_id,
                "FacetIDs": [{"FacetTypeID": facet_type_id, "FacetRoleID": facet_map.get(facet, ref_id(id_prefix, "FacetRole", facet))}]
            })

    # Compliance tags
    acl = raw_manifest.get("acl") or {"owners": ["data.default.owners@dev.dataservices.energy"], "viewers": ["data.office.global.viewers@dev.dataservices.energy"]}
    legal = raw_manifest.get("legal") or {"legaltags": ["dev-equinor-private-default"], "otherRelevantDataCountries": ["NO"]}
    ancestry = raw_wpc_data.get("ancestry") or {"parents": [], "children": []}

    wpc_id_value = str(uuid.uuid4()) if use_uuid else "ReservoirEstimatedVolumes_Stats"
    wpc_record_id = wpc_id(id_prefix, "ReservoirEstimatedVolumes", wpc_id_value)

    return {
        "kind": "osdu:wks:Manifest:1.0.0",
        "acl": acl,
        "legal": legal,
        "ReferenceData": [],
        "MasterData": [],
        "Data": {
            "Datasets": [],
            "WorkProductComponents": [{
                "id": wpc_record_id,
                "kind": "osdu:wks:work-product-component--ReservoirEstimatedVolumes:1.1.0",
                "acl": acl,
                "legal": legal,
                "data": {
                    "Name": "Reservoir Estimated Volumes — statistics",
                    "Description": "Aggregated statistics across Realisations by Segment & Zone (plus TOTALs)",
                    "EstimatedVolumeTypeID": ref_id(id_prefix, "ReservoirEstimatedVolumeType", "EstimatedInPlaceVolumes"),
                    "ParentObjectID": raw_wpc_data.get("ParentObjectID"),
                    "ParentWorkProductID": raw_wpc_data.get("ParentWorkProductID"),
                    "ancestry": ancestry,
                    "Volumes": {
                        "ColumnBasedTableTypeID": ref_id(id_prefix, "ColumnBasedTableType", "AdHoc"),
                        "KeyColumns": [
                            {"ColumnName": "Zone", "ColumnRole": "Key", "ValueType": "string"},
                            {"ColumnName": "SegmentID", "ColumnRole": "Key", "ValueType": "string", "KindID": "osdu:wks:master-data--ReservoirSegment:2.0.0"}
                        ],
                        "Columns": columns,
                        "ColumnValues": stat_colvals
                    }
                }
            }],
            "WorkProducts": []
        }
    }

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rawvol_manifest", default="manifest_wpcraw.json")
    ap.add_argument("--statvol_manifest", default="manifest_wpcstat.json")
    ap.add_argument("--facetroles", default="reftypes_facetroles.json")
    ap.add_argument("--id-prefix", default="dev")
    ap.add_argument("--uuid", action="store_true", default=True)
    args = ap.parse_args()

    raw_manifest = load_json(args.rawvol_manifest)
    facet_roles = load_json(args.facetroles)
    stat_manifest = build_statistics_manifest(raw_manifest, facet_roles, args.id_prefix, args.uuid)

    with open(args.statvol_manifest, "w", encoding="utf-8") as f:
        json.dump(stat_manifest, f, indent=2)
    print(f"Statistics manifest written: {args.statvol_manifest}")

if __name__ == "__main__":
    main()
