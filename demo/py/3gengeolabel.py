
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
3genwpcgeolabelset.py — Generate GeoLabelSet WorkProductComponent manifest from a statistics manifest.

Updates:
- Keys now mirror the STAT Volumes keys: SegmentID, Zone, Phases, and (optional) Facies.
- Values pulled for selected facets for all properties that have matching GeoLabelTypes.
- Inherit acl/legal from the statistics WPC (not manifest-level).
- UOM is configurable (default 'sm3' to align with geolabel type defaults).
"""

import argparse
import json
import uuid
from typing import Any, Dict, List, Tuple

def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def ref_id(prefix: str, entity: str, name: str) -> str:
    return f"{prefix}:reference-data--{entity}:{name}"

def wpc_id(prefix: str, entity: str, name: str) -> str:
    return f"{prefix}:work-product-component--{entity}:{name}:1"

def parse_facets(facet_str: str, default_facets: List[str]) -> List[str]:
    if not facet_str:
        return default_facets
    return [f.strip() for f in facet_str.replace(";", ",").split(",") if f.strip()]

def _extract_stat_wpc(manifest: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Return (wpc, wpc_data, volumes) for the REV statistics WPC."""
    wpcs = manifest.get("Data", {}).get("WorkProductComponents", [])
    wpc = next((w for w in wpcs if w.get("kind", "").startswith(
        "osdu:wks:work-product-component--ReservoirEstimatedVolumes:")), None)
    if not wpc:
        raise ValueError("Statistics WPC not found in manifest.")
    wpc_data = wpc.get("data", {})
    volumes = wpc_data.get("Volumes", {})
    return wpc, wpc_data, volumes

def build_geolabel_manifest(
    stat_manifest: Dict[str, Any],
    geolabel_ref: Dict[str, Any],
    facet_ref: Dict[str, Any],
    facets: List[str],
    id_prefix: str,
    use_uuid: bool,
    uom_code: str
) -> Dict[str, Any]:

    # Extract WPC from statistics manifest (and its Volumes table)
    stat_wpc, stat_wpc_data, volumes = _extract_stat_wpc(stat_manifest)
    colvals = volumes.get("ColumnValues", {})
    columns_stat = volumes.get("Columns", [])

    # Determine which label properties are present in the stats manifest (e.g., Oil.P50 -> 'Oil')
    present_props = set()
    for col in columns_stat:
        cname = col.get("ColumnName", "")
        if "." in cname:
            p, _ = cname.split(".", 1)
            if p:
                present_props.add(p)

    # Map GeoLabelTypes by Name from the reference file
    geolabel_map = {
        ref["data"]["Name"]: ref["id"]
        for ref in geolabel_ref.get("ReferenceData", [])
        if ref.get("kind", "").startswith("osdu:wks:reference-data--GeoLabelType:")
    }

    # Facet roles map (FacetType='statistics')
    facet_map = {
        ref["data"]["Code"]: ref["id"]
        for ref in facet_ref.get("ReferenceData", [])
        if ref["data"].get("FacetType") == "statistics"
    }
    facet_type_id = ref_id(id_prefix, "FacetType", "statistics")

    # Choose only GeoLabelTypes that are present in the stats table
    props_to_include = [p for p in sorted(present_props) if p in geolabel_map]

    # Key columns present in stats manifest: Zone, SegmentID, Phases, optional Facies
    has_phases = "Phases" in colvals
    has_facies = "Facies" in colvals

    key_names = ["Zone", "SegmentID"]
    if has_phases:
        key_names.append("Phases")
    if has_facies:
        key_names.append("Facies")

    # Prepare ColumnValues for GeoLabelSet
    # Re-use the same row-order as in the stats manifest (use length of the first key we have)
    row_count = 0
    for kn in key_names:
        row_count = len(colvals.get(kn, []))
        if row_count:
            break

    geo_colvals: Dict[str, List[Any]] = {kn: colvals.get(kn, [""] * row_count) for kn in key_names}
    for p in props_to_include:
        for f in facets:
            geo_colvals[f"{p}.{f}"] = [None] * row_count

    # Pull values from stats 'ColumnValues'
    for i in range(row_count):
        for p in props_to_include:
            for f in facets:
                key = f"{p}.{f}"
                src = colvals.get(key, [None] * row_count)
                geo_colvals[key][i] = src[i] if i < len(src) else None

    # Build Columns metadata (values)
    columns_meta: List[Dict[str, Any]] = []
    for p in props_to_include:
        for f in facets:
            col_name = f"{p}.{f}"
            columns_meta.append({
                "ColumnName": col_name,
                "ColumnRole": "Value",
                "ValueType": "number",
                "GeoLabelTypeID": geolabel_map[p],
                "UnitOfMeasureID": ref_id(id_prefix, "UnitOfMeasure", uom_code),
                "FacetIDs": [{
                    "FacetTypeID": facet_type_id,
                    "FacetRoleID": facet_map.get(f, ref_id(id_prefix, "FacetRole", f))
                }]
            })

    # Build KeyColumns metadata; SegmentID carries a KindID
    key_columns: List[Dict[str, Any]] = []
    for kn in key_names:
        kd = {"ColumnName": kn, "ColumnRole": "Key", "ValueType": "string"}
        if kn == "SegmentID":
            kd["KindID"] = "osdu:wks:master-data--ReservoirSegment:2.0.0"
        key_columns.append(kd)

    # Compliance tags from the statistics WPC (not manifest-level)
    wpc_acl = stat_wpc.get("acl") or {"owners": ["data.default.owners@dev.dataservices.energy"], "viewers": ["data.office.global.viewers@dev.dataservices.energy"]}
    wpc_legal = stat_wpc.get("legal") or {"legaltags": ["dev-equinor-osdu-private-default"], "otherRelevantDataCountries": ["NO"]}
    ancestry = stat_wpc_data.get("ancestry") or {"parents": [], "children": []}

    # IDs
    wpc_id_value = str(uuid.uuid4()) if use_uuid else "GeoLabelSet"
    wpc_record_id = wpc_id(id_prefix, "GeoLabelSet", wpc_id_value)

    manifest = {
        "kind": "osdu:wks:Manifest:1.0.0",
        "ReferenceData": [],
        "MasterData": [],
        "Data": {
            "Datasets": [],
            "WorkProductComponents": [{
                "id": wpc_record_id,
                "kind": "osdu:wks:work-product-component--GeoLabelSet:1.0.0",
                "acl": wpc_acl,
                "legal": wpc_legal,
                "data": {
                    "Name": "GeoLabelSet",
                    "Description": "GeoLabelSet derived from statistics manifest",
                    "ParentObjectID": stat_wpc_data.get("ParentObjectID"),
                    "ParentWorkProductID": stat_wpc_data.get("ParentWorkProductID"),
                    "ancestry": ancestry,
                    "GeoLabels": {
                        "ColumnBasedTableTypeID": ref_id(id_prefix, "ColumnBasedTableType", "AdHoc"),
                        "KeyColumns": key_columns,
                        "Columns": columns_meta,
                        "ColumnValues": geo_colvals
                    }
                }
            }],
            "WorkProducts": []
        }
    }
    return manifest

def main():
    ap = argparse.ArgumentParser(description="Generate GeoLabelSet WPC manifest from statistics manifest")
    ap.add_argument("--manifest_stat", default="manifest_wpcstat.json")
    ap.add_argument("--manifest_geolabel", default="manifest_wpcgeolabelset.json")
    ap.add_argument("--geolabeltypes", default="reftypes_geolabeltypes.json")
    ap.add_argument("--facetroles", default="reftypes_facetroles.json")
    ap.add_argument("--facets", default="")
    ap.add_argument("--id-prefix", default="dev")
    ap.add_argument("--uuid", action="store_true", default=True)
    ap.add_argument("--uom", default="sm3")  # align with geolabel types default
    args = ap.parse_args()

    stat_manifest = load_json(args.manifest_stat)
    geolabel_ref = load_json(args.geolabeltypes)
    facet_ref = load_json(args.facetroles)
    default_facets = ["P10", "P50", "P90", "ArithmeticMean", "Minimum", "Maximum", "StandardDeviation"]
    facets = parse_facets(args.facets, default_facets)

    manifest = build_geolabel_manifest(
        stat_manifest, geolabel_ref, facet_ref, facets, args.id_prefix, args.uuid, args.uom
    )
    with open(args.manifest_geolabel, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    rows = len(manifest["Data"]["WorkProductComponents"][0]["data"]["GeoLabels"]["ColumnValues"][facets and f"{sorted(set(k.split('.')[0] for k in manifest['Data']['WorkProductComponents'][0]['data']['GeoLabels']['ColumnValues'].keys() if '.' in k))[0]}.{facets[0]}" or "Zone"])
    cols = len(manifest["Data"]["WorkProductComponents"][0]["data"]["GeoLabels"]["Columns"])
    print(f"GeoLabelSet manifest written: {args.manifest_geolabel}\nRows: {rows}, Columns: {cols}")

if __name__ == "__main__":
    main()
