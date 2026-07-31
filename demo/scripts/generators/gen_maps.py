"""
gen_maps.py - Generic StructureMap + GenericRepresentation WPC catalog generator.

Spec format:
{
  "generator": "maps",
  "project": "Drogon DG2",
  "rddms_dataspace": "maap/drogon_dg",
  "crs": "ST_WGS84_UTM37N_P32637",
  "uuid_prefix": "dg2-map",
  "grid_geometry": {"ni": 280, "nj": 440, "increment": 25.0},
  "depth_surfaces": {
    "horizons": ["TopVolantis", "TopTherys", ...],
    "sources": ["ds_extract_geogrid", "ds_extract_postprocess"],
    "standard_results": {
      "ds_extract_geogrid": "grid_extracted_depth_surface",
      "ds_extract_postprocess": "structure_depth_surface"
    }
  },
  "amplitude_maps": {
    "horizons": ["TopVolantis", "TopTherys", ...],
    "attributes": ["near", "far"],
    "vintage": "2018"
  },
  "facies_fraction_maps": {
    "Valysar": ["channel", "crevasse", "floodplain", "coal"],
    "Therys":  ["uppershoreface", "lowershoreface", "offshore", "calcite"],
    "Volon":   ["channel", "floodplain", "calcite", "coal"]
  },
  "average_property_maps": {
    "zones": ["Valysar", "Therys", "Volon"],
    "properties": [
      {"name": "phit", "attribute": "porosity"},
      {"name": "klogh", "attribute": "permeability"}
    ]
  },
  "probability_maps": {
    "Valysar": ["channel", "crevasse", "floodplain"],
    "Therys":  ["uppershoreface", "lowershoreface", "offshore"],
    "Volon":   ["channel", "floodplain", "calcite"]
  },
  "masterwp_manifest": "...",
  "grid_manifest": "..."
}
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from ._common import (
    load_ref,
    det_uuid, find_id, load_json,
    resolve_acl_legal, resolve_reservoir_id,
)
from ._registry import register


def _surface_record(
    pfx: str,
    project: str,
    name: str,
    description: str,
    content: str,
    attribute: str,
    osdu_kind: str,
    uuid_prefix: str,
    acl: dict,
    legal: dict,
    *,
    reservoir_id: str = "",
    grid_id: str = "",
    dataspace_id: str = "",
    rddms_base: str = "",
    crs: str = "",
    ni: int = 0,
    nj: int = 0,
    increment: float = 0.0,
    horizon: str = "",
    zone: str = "",
    domain: str = "Depth",
    standard_result: str = "",
    facet_statistics: str = "",
) -> Dict[str, Any]:
    map_uuid = det_uuid(f"{uuid_prefix}-{name}")
    map_id = f"{pfx}:work-product-component--{osdu_kind}:{map_uuid}:1"

    data: Dict[str, Any] = {
        "Name": f"{project} - {name}" if project else name,
        "Description": description,
    }
    if crs:
        data["CoordinateReferenceSystemID"] = f"{pfx}:reference-data--CoordinateReferenceSystem:{crs}:"
    if reservoir_id:
        data["ReservoirID"] = reservoir_id
    if ni:
        data["NodeCountOnIAxis"] = ni
    if nj:
        data["NodeCountOnJAxis"] = nj
    if increment:
        data["BinWidthOnIaxis"] = increment
        data["BinWidthOnJaxis"] = increment
    if rddms_base:
        data["DDMSDatasets"] = [f"{rddms_base}/resqml22.Grid2dRepresentation('{map_uuid}')"]
    if domain:
        data["DomainTypeID"] = f"{pfx}:reference-data--DomainType:{domain}:"

    fmu: Dict[str, Any] = {"Content": content, "PropertyAttribute": attribute}
    if horizon:
        data["HorizonName"] = horizon
        fmu["StratigraphicReference"] = horizon
    if zone:
        data["ZoneName"] = zone
        fmu["StratigraphicReference"] = zone
    if standard_result:
        fmu["StandardResult"] = standard_result
    data["FMU"] = fmu

    if facet_statistics:
        data["FacetIDs"] = [
            f"{pfx}:reference-data--FacetType:statistics:",
            f"{pfx}:reference-data--FacetRole:{facet_statistics}:",
        ]

    ancestry = []
    if grid_id:
        ancestry.append(grid_id)
    if dataspace_id:
        ancestry.append(dataspace_id)
    if ancestry:
        data["data.ancestry.inputs"] = ancestry

    return {
        "id": map_id,
        "kind": f"osdu:wks:work-product-component--{osdu_kind}:1.0.0",
        "acl": acl,
        "legal": legal,
        "data": data,
    }


@register("maps")
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
    uuid_pfx = spec.get("uuid_prefix", "map")
    geom = spec.get("grid_geometry", {})
    ni = geom.get("ni", 0)
    nj = geom.get("nj", 0)
    increment = geom.get("increment", 0.0)

    # Load cross-references
    masterwp = load_ref(spec, refs, "masterwp_manifest", "masterwp", base_dir)
    grid_man = load_ref(spec, refs, "grid_manifest", "grid", base_dir)

    acl, legal = resolve_acl_legal(spec, pfx, masterwp)
    reservoir_id = resolve_reservoir_id(masterwp)
    grid_id = find_id(grid_man, "IjkGridRepresentation") if grid_man else ""
    ds_slug = rddms_ds.replace("/", "-") if rddms_ds else ""
    dataspace_id = f"{pfx}:dataset--ETPDataspace:{ds_slug}:1" if rddms_ds else ""

    common = dict(
        pfx=pfx, project=project, uuid_prefix=uuid_pfx,
        acl=acl, legal=legal, reservoir_id=reservoir_id,
        grid_id=grid_id, dataspace_id=dataspace_id,
        rddms_base=rddms_base, crs=crs, ni=ni, nj=nj, increment=increment,
    )

    records: List[Dict[str, Any]] = []

    # 1. Depth surfaces
    ds_cfg = spec.get("depth_surfaces", {})
    std_results = ds_cfg.get("standard_results", {})
    for hz in ds_cfg.get("horizons", []):
        for src in ds_cfg.get("sources", []):
            name = f"{hz.lower()}--{src}"
            records.append(_surface_record(
                name=name,
                description=f"Grid-extracted depth surface for {hz} ({src})",
                content="depth", attribute="depth",
                osdu_kind="StructureMap", horizon=hz,
                standard_result=std_results.get(src, ""),
                facet_statistics="P50",
                **common,
            ))

    # 2. Amplitude maps
    amp_cfg = spec.get("amplitude_maps", {})
    vintage = amp_cfg.get("vintage", "")
    for hz in amp_cfg.get("horizons", []):
        for attr in amp_cfg.get("attributes", []):
            suffix = f"_{vintage}" if vintage else ""
            name = f"{hz.lower()}--amplitude_{attr}{suffix}"
            records.append(_surface_record(
                name=name,
                description=f"Seismic amplitude extraction ({attr} offset{', ' + vintage + ' vintage' if vintage else ''}) at {hz}",
                content="seismic", attribute=f"amplitude_{attr}",
                osdu_kind="GenericRepresentation", horizon=hz,
                facet_statistics="P50",
                **common,
            ))

    # 3. Facies fraction maps
    for zone, facies_list in spec.get("facies_fraction_maps", {}).items():
        for facies in facies_list:
            name = f"{zone.lower()}--facies_fraction_{facies}"
            records.append(_surface_record(
                name=name,
                description=f"Facies fraction map: {facies} in {zone} zone",
                content="property", attribute=f"facies_fraction_{facies}",
                osdu_kind="GenericRepresentation", zone=zone,
                facet_statistics="P50",
                **common,
            ))

    # 4. Average property maps
    avg_cfg = spec.get("average_property_maps", {})
    for zone in avg_cfg.get("zones", []):
        for prop in avg_cfg.get("properties", []):
            name = f"{zone.lower()}--{prop['name']}_average"
            records.append(_surface_record(
                name=name,
                description=f"Zone-averaged {prop['attribute']} map for {zone}",
                content="property", attribute=prop["attribute"],
                osdu_kind="GenericRepresentation", zone=zone,
                facet_statistics="P50",
                **common,
            ))

    # 5. Probability maps
    for zone, facies_list in spec.get("probability_maps", {}).items():
        for facies in facies_list:
            name = f"{zone.lower()}--aps_probability_{facies}"
            records.append(_surface_record(
                name=name,
                description=f"APS facies probability map: {facies} in {zone}",
                content="property", attribute=f"aps_probability_{facies}",
                osdu_kind="GenericRepresentation", zone=zone,
                facet_statistics="P50",
                **common,
            ))

    # 6. Custom surfaces (catch-all)
    for surf in spec.get("surfaces", []):
        records.append(_surface_record(
            name=surf["name"],
            description=surf.get("description", ""),
            content=surf.get("content", "property"),
            attribute=surf.get("attribute", ""),
            osdu_kind=surf.get("osdu_kind", "GenericRepresentation"),
            horizon=surf.get("horizon", ""),
            zone=surf.get("zone", ""),
            standard_result=surf.get("standard_result", ""),
            facet_statistics=surf.get("facet_statistics", ""),
            **common,
        ))

    return records


