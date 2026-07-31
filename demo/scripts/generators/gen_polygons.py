"""
gen_polygons.py - Generic GenericRepresentation (polygon/line) WPC generator.

Spec format:
{
  "generator": "polygons",
  "project": "Drogon DG2",
  "rddms_dataspace": "maap/drogon_dg",
  "crs": "ST_WGS84_UTM37N_P32637",
  "uuid_prefix": "dg2-polygon",
  "fault_lines": {
    "horizons": ["TopVolantis", "TopTherys", "TopVolon", "BaseVolantis"]
  },
  "polygons": [
    {"name": "field_outline", "title": "Field Outline",
     "description": "...", "content": "field_outline",
     "standard_result": "field_outline"},
    ...
  ],
  "masterwp_manifest": "..."
}
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from ._common import (
    load_ref,
    det_uuid, load_json,
    resolve_acl_legal, resolve_reservoir_id,
)
from ._registry import register


@register("polygons")
def generate(
    spec: Dict[str, Any],
    pfx: str,
    base_dir: Path,
    refs: Dict[str, Any],
) -> List[Dict[str, Any]]:
    project = spec.get("project", "")
    rddms_ds = spec.get("rddms_dataspace", "")
    rddms_base = f"eml:///dataspace('{rddms_ds}')" if rddms_ds else ""
    crs = spec.get("crs", "")
    uuid_pfx = spec.get("uuid_prefix", "polygon")

    masterwp = load_ref(spec, refs, "masterwp_manifest", "masterwp", base_dir)
    acl, legal = resolve_acl_legal(spec, pfx, masterwp)
    reservoir_id = resolve_reservoir_id(masterwp)
    ds_slug = rddms_ds.replace("/", "-") if rddms_ds else ""
    dataspace_id = f"{pfx}:dataset--ETPDataspace:{ds_slug}:1" if rddms_ds else ""

    records: List[Dict[str, Any]] = []

    # Fault lines per horizon
    fl = spec.get("fault_lines", {})
    for hz in fl.get("horizons", []):
        hz_lower = hz.lower()
        name = f"{hz_lower}--faultlines"
        poly_uuid = det_uuid(f"{uuid_pfx}-{name}")
        poly_id = f"{pfx}:work-product-component--GenericRepresentation:{poly_uuid}:1"

        data: Dict[str, Any] = {
            "Name": f"{project} - Fault Lines at {hz}" if project else f"Fault Lines at {hz}",
            "Description": f"Fault line polygons at {hz} horizon.",
            "FMU": {
                "Content": "polygons",
                "PropertyAttribute": "fault_lines",
                "HorizonName": hz,
                "StandardResult": "structure_depth_fault_lines",
            },
        }
        if crs:
            data["CoordinateReferenceSystemID"] = f"{pfx}:reference-data--CoordinateReferenceSystem:{crs}:"
        if reservoir_id:
            data["ReservoirID"] = reservoir_id
        if rddms_base:
            data["DDMSDatasets"] = [f"{rddms_base}/polygons/{hz_lower}--faultlines.csv"]
        if dataspace_id:
            data["data.ancestry.inputs"] = [dataspace_id]

        records.append({
            "id": poly_id,
            "kind": "osdu:wks:work-product-component--GenericRepresentation:1.0.0",
            "acl": acl, "legal": legal, "data": data,
        })

    # Named polygons
    for poly in spec.get("polygons", []):
        name = poly["name"]
        poly_uuid = det_uuid(f"{uuid_pfx}-{name}")
        poly_id = f"{pfx}:work-product-component--GenericRepresentation:{poly_uuid}:1"

        data = {
            "Name": poly.get("title", f"{project} - {name}" if project else name),
            "Description": poly.get("description", ""),
            "FMU": {
                "Content": "polygons",
                "PropertyAttribute": poly.get("content", "polygons"),
            },
        }
        if poly.get("standard_result"):
            data["FMU"]["StandardResult"] = poly["standard_result"]
        if crs:
            data["CoordinateReferenceSystemID"] = f"{pfx}:reference-data--CoordinateReferenceSystem:{crs}:"
        if reservoir_id:
            data["ReservoirID"] = reservoir_id
        if rddms_base:
            data["DDMSDatasets"] = [f"{rddms_base}/polygons/{name}.csv"]
        if dataspace_id:
            data["data.ancestry.inputs"] = [dataspace_id]

        records.append({
            "id": poly_id,
            "kind": "osdu:wks:work-product-component--GenericRepresentation:1.0.0",
            "acl": acl, "legal": legal, "data": data,
        })

    return records


