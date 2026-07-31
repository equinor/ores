"""
gen_grid.py - Generic IjkGridRepresentation WPC catalog generator.

Spec format:
{
  "generator": "grid",
  "project": "Drogon DG2",
  "rddms_dataspace": "maap/drogon_dg",
  "crs": "ST_WGS84_UTM37N_P32637",
  "uuid_prefix": "dg2-geogrid",
  "grid": {
    "ni": 92, "nj": 146, "nk": 69,
    "k_direction": "down",
    "handedness": "right",
    "description": "Corner-point grid exported from RMS ...",
    "standard_result": "grid_model_static",
    "fmu": {"CaseName": "drogon_design", ...},
    "zones": [
      {"Name": "Valysar", "KStart": 0, "KEnd": 19}, ...
    ]
  },
  "properties": [
    {"name": "phit", "attribute": "porosity", "uom": "Euc",
     "is_discrete": false, "description": "Total porosity (PHIT)"},
    ...
  ],
  "masterwp_manifest": "path/to/manifest_masterwp.json",
  "activity_manifest": "path/to/manifest_activity.json"
}
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from ._common import (
    load_ref,
    det_uuid, find_id, load_json,
    resolve_acl_legal, resolve_reservoir_id,
)
from ._registry import register


@register("grid")
def generate(
    spec: Dict[str, Any],
    pfx: str,
    base_dir: Path,
    refs: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Generate IjkGridRepresentation WPC records for grid + properties."""
    project = spec.get("project", "")
    rddms_ds = spec.get("rddms_dataspace", "")
    rddms_base = f"eml:///dataspace('{rddms_ds}')" if rddms_ds else ""
    crs = spec.get("crs", "")
    uuid_pfx = spec.get("uuid_prefix", "geogrid")
    grid = spec["grid"]

    # Load cross-references
    masterwp = load_ref(spec, refs, "masterwp_manifest", "masterwp", base_dir)
    activity = load_ref(spec, refs, "activity_manifest", "activity", base_dir)

    acl, legal = resolve_acl_legal(spec, pfx, masterwp)
    reservoir_id = resolve_reservoir_id(masterwp)
    activity_id = find_id(activity, "Activity") if activity else ""

    # Dataspace dataset ID
    ds_slug = rddms_ds.replace("/", "-") if rddms_ds else "dataspace"
    dataspace_id = f"{pfx}:dataset--ETPDataspace:{ds_slug}:1" if rddms_ds else ""

    grid_uuid = det_uuid(uuid_pfx)
    grid_id = f"{pfx}:work-product-component--IjkGridRepresentation:{grid_uuid}:1"

    ni, nj, nk = grid["ni"], grid["nj"], grid["nk"]

    grid_record: Dict[str, Any] = {
        "id": grid_id,
        "kind": "osdu:wks:work-product-component--IjkGridRepresentation:1.0.0",
        "acl": acl,
        "legal": legal,
        "data": {
            "Name": f"{project} - Geogrid (static geomodel)" if project else "Geogrid",
            "Description": grid.get("description", f"{ni}×{nj}×{nk} grid"),
            "Ni": ni,
            "Nj": nj,
            "Nk": nk,
            "KDirection": grid.get("k_direction", "down"),
            "Handedness": grid.get("handedness", "right"),
        },
    }

    data = grid_record["data"]
    if crs:
        data["CoordinateReferenceSystemID"] = f"{pfx}:reference-data--CoordinateReferenceSystem:{crs}:"
    if reservoir_id:
        data["ReservoirID"] = reservoir_id
    if rddms_base:
        data["DDMSDatasets"] = [f"{rddms_base}/resqml22.IjkGridRepresentation('{grid_uuid}')"]
    if grid.get("zones"):
        data["Zones"] = [{"Name": z["Name"], "KStart": z["KStart"], "KEnd": z["KEnd"]} for z in grid["zones"]]
    if grid.get("standard_result"):
        data["StandardResult"] = grid["standard_result"]
    if grid.get("fmu"):
        data["FMU"] = grid["fmu"]
    if dataspace_id:
        data["data.ancestry.inputs"] = [dataspace_id]

    records = [grid_record]

    # Build property WPCs
    for prop in spec.get("properties", []):
        prop_name = prop["name"]
        prop_uuid = det_uuid(f"{uuid_pfx}-{prop_name}")
        prop_id = f"{pfx}:work-product-component--IjkGridRepresentation:{prop_uuid}:1"
        is_disc = prop.get("is_discrete", False)

        prop_data: Dict[str, Any] = {
            "Name": f"{project} - geogrid {prop_name}" if project else prop_name,
            "Description": prop.get("description", ""),
            "SupportedByID": grid_id,
            "PropertyAttribute": prop["attribute"],
            "IsDiscrete": is_disc,
        }

        if prop.get("uom"):
            prop_data["UnitOfMeasureID"] = f"{pfx}:reference-data--UnitOfMeasure:{prop['uom']}:"
        if crs:
            prop_data["CoordinateReferenceSystemID"] = f"{pfx}:reference-data--CoordinateReferenceSystem:{crs}:"
        if reservoir_id:
            prop_data["ReservoirID"] = reservoir_id
        if rddms_base:
            resqml_type = "DiscreteProperty" if is_disc else "ContinuousProperty"
            prop_data["DDMSDatasets"] = [f"{rddms_base}/resqml22.{resqml_type}('{prop_uuid}')"]
        if prop.get("fmu") or grid.get("fmu"):
            fmu = dict(prop.get("fmu", {}))
            fmu.setdefault("Content", "property")
            fmu.setdefault("PropertyAttribute", prop["attribute"])
            fmu.setdefault("IsDiscrete", is_disc)
            if grid.get("standard_result"):
                fmu.setdefault("StandardResult", grid["standard_result"])
            prop_data["FMU"] = fmu

        ancestry = []
        if grid_id:
            ancestry.append(grid_id)
        if dataspace_id:
            ancestry.append(dataspace_id)
        if ancestry:
            prop_data["data.ancestry.inputs"] = ancestry

        records.append({
            "id": prop_id,
            "kind": "osdu:wks:work-product-component--IjkGridRepresentation:1.0.0",
            "acl": acl,
            "legal": legal,
            "data": prop_data,
        })

    return records


