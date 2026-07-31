"""
gen_markers.py - Generic WellboreMarkerSet + StratigraphicColumn generator.

Generates:
  - WellboreMarkerSet per wellbore (formation tops with MD/TVD)
  - StratigraphicColumn + ColumnRankInterpretation + UnitInterpretation
  - HorizonInterpretation (optionally cross-referenced to RDDMS)

Spec format:
{
  "generator": "markers",
  "project": "Drogon",
  "rddms_dataspace": "maap/drogon",
  "wells_manifest": "manifest_wells.json",
  "formations": {
    "Drogon": [
      {"name": "Seabed", "md_min": 400, "md_max": 450, "tvd_offset": 0},
      {"name": "TopVolantis", "md_min": 3050, "md_max": 3200, "tvd_offset": -20},
      ...
    ]
  },
  "field_wellbore_map": {
    "Drogon": ["55/33-A-1", "55/33-A-2", ...],
    "Volve": ["15/9-F-1 C", ...]
  },
  "depth_seeds": {"55/33-A-1": 0, "55/33-A-2": 40, ...},
  "strat_column": {
    "name": "Drogon-Volve Lithostratigraphy",
    "units": [
      {"name": "Nordland Group", "rank": "Group",
       "older_age": 23.0, "younger_age": 0.0,
       "description": "Neogene overburden"},
      ...
    ]
  },
  "horizons": [
    {"name": "TopVolantis",
     "horizon_uuid": "02e954a9-...",
     "feature_uuid": "2d66e9f5-...",
     "is_stratigraphic": true,
     "description": "Top Volantis reservoir boundary"},
    ...
  ],
  "unit_xrefs": {
    "Volantis Formation": {"uuid": "0b257a04-...", "alias": "Valysar"},
    ...
  }
}
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, List

from ._common import load_json, load_ref, rand_uuid, default_acl, default_legal
from ._registry import register

ID_PREFIX = "dev"  # overridden by pfx


@register("markers")
def generate(
    spec: Dict[str, Any],
    pfx: str,
    base_dir: Path,
    refs: Dict[str, Any],
) -> List[Dict[str, Any]]:
    acl = spec.get("acl") or default_acl(pfx)
    legal = spec.get("legal") or default_legal(pfx)
    project = spec.get("project", "")
    rddms_ds = spec.get("rddms_dataspace", "")

    # Load wellbore IDs
    wells_man = load_ref(spec, refs, "wells_manifest", "wells", base_dir)
    wb_map: Dict[str, str] = {}
    if wells_man:
        for rec in wells_man.get("MasterData", []):
            if "Wellbore:" in rec.get("kind", ""):
                name = rec["data"].get("Name", rec["data"].get("FacilityName", ""))
                wb_map[name] = rec["id"]

    formations = spec.get("formations", {})
    field_wb_map = spec.get("field_wellbore_map", {})
    depth_seeds = spec.get("depth_seeds", {})

    records: List[Dict[str, Any]] = []

    # Generate strat column first (to get the ID for markers)
    strat_col_id = ""
    strat_cfg = spec.get("strat_column")
    if strat_cfg:
        strat_records, strat_col_id = _generate_strat_column(
            strat_cfg, spec, pfx, acl, legal, rddms_ds
        )
        records.extend(strat_records)

    # Generate WellboreMarkerSets
    for field, wb_names in field_wb_map.items():
        field_fms = formations.get(field, [])
        for wb_name in wb_names:
            wb_id = wb_map.get(wb_name, "")
            seed = depth_seeds.get(wb_name, 0)
            markers = _markers_for_wellbore(wb_name, field_fms, seed)
            rec_id = f"{pfx}:work-product-component--WellboreMarkerSet:{rand_uuid()}:"
            records.append({
                "id": rec_id,
                "kind": "osdu:wks:work-product-component--WellboreMarkerSet:1.2.0",
                "acl": acl, "legal": legal,
                "data": {
                    "Name": f"{wb_name} \u2013 Formation Tops",
                    "Description": f"Formation top picks for wellbore {wb_name}",
                    "WellboreID": wb_id,
                    "Markers": markers,
                    "StratigraphicColumnID": strat_col_id,
                    "StratigraphicColumnRankInterpretationID": "",
                },
            })

    return records


def _markers_for_wellbore(wb_name: str, formations: List[Dict], depth_seed: int) -> List[Dict]:
    markers = []
    for i, fm in enumerate(formations):
        name = fm["name"]
        md_min = fm.get("md_min", 0)
        md_max = fm.get("md_max", md_min + 100)
        tvd_off = fm.get("tvd_offset", 0)
        h = int(hashlib.md5(f"{wb_name}-{name}".encode()).hexdigest()[:8], 16)
        frac = (h % 1000) / 1000.0
        md = round(md_min + depth_seed + frac * (md_max - md_min), 1)
        tvd = round(md + tvd_off, 1)
        markers.append({
            "MarkerName": name,
            "MarkerMeasuredDepth": md,
            "MarkerSubSeaVerticalDepth": tvd,
            "MarkerObservationNumber": i + 1,
            "Missing": "",
            "MarkerTypeID": "",
            "InterpretationID": "",
            "MarkerInterpreter": "gen_markers",
            "GeologicalAge": "",
        })
    return markers


def _generate_strat_column(
    strat_cfg: Dict,
    spec: Dict,
    pfx: str,
    acl: dict,
    legal: dict,
    rddms_ds: str,
) -> tuple:
    records: List[Dict[str, Any]] = []
    col_name = strat_cfg.get("name", "Lithostratigraphy")
    unit_xrefs = spec.get("unit_xrefs", {})

    # Unit records
    unit_ids: Dict[str, str] = {}
    rank_units: Dict[str, List[str]] = {}

    for unit in strat_cfg.get("units", []):
        unit_name = unit["name"]
        rank = unit.get("rank", "Formation")
        slug = unit_name.replace(" ", "")
        unit_id = f"{pfx}:work-product-component--StratigraphicUnitInterpretation:{slug}:"
        unit_ids[unit_name] = unit_id
        rank_units.setdefault(rank, []).append(unit_id)

        data: Dict[str, Any] = {
            "Name": unit_name,
            "Description": unit.get("description", ""),
            "StratigraphicRoleTypeID": "",
            "ChronoStratigraphyID": "",
            "OlderPossibleAge": unit.get("older_age"),
            "YoungerPossibleAge": unit.get("younger_age"),
            "ColumnStratigraphicHorizonTopID": "",
            "ColumnStratigraphicHorizonBaseID": "",
        }

        if unit_name in unit_xrefs:
            xref = unit_xrefs[unit_name]
            rddms_uuid = xref["uuid"]
            eml_uri = f"eml:///dataspace('{rddms_ds}')/resqml20.obj_StratigraphicUnitInterpretation('{rddms_uuid}')"
            data["ResourceURI"] = eml_uri
            data["ResourceID"] = rddms_uuid

        records.append({
            "id": unit_id,
            "kind": "osdu:wks:work-product-component--StratigraphicUnitInterpretation:1.3.0",
            "acl": acl, "legal": legal, "data": data,
        })

    # Rank records
    rank_ids: Dict[str, str] = {}
    for rank_name, member_ids in rank_units.items():
        rank_id = f"{pfx}:work-product-component--StratigraphicColumnRankInterpretation:{col_name.replace(' ', '-')}-{rank_name}:"
        rank_ids[rank_name] = rank_id
        records.append({
            "id": rank_id,
            "kind": "osdu:wks:work-product-component--StratigraphicColumnRankInterpretation:1.3.0",
            "acl": acl, "legal": legal,
            "data": {
                "Name": f"{col_name} - {rank_name} Rank",
                "Description": f"{rank_name}-level ranking for {col_name}",
                "StratigraphicUnitInterpretationIDs": member_ids,
            },
        })

    # Strat column
    strat_col_id = f"{pfx}:work-product-component--StratigraphicColumn:{col_name.replace(' ', '-')}:"
    records.append({
        "id": strat_col_id,
        "kind": "osdu:wks:work-product-component--StratigraphicColumn:1.2.0",
        "acl": acl, "legal": legal,
        "data": {
            "Name": col_name,
            "Description": strat_cfg.get("description", f"Lithostratigraphic column for {col_name}"),
            "StratigraphicColumnRankInterpretationIDs": list(rank_ids.values()),
        },
    })

    # Horizon interpretations
    for hz in spec.get("horizons", []):
        hz_name = hz["name"]
        hz_id = f"{pfx}:work-product-component--HorizonInterpretation:{hz_name}:"
        data = {
            "Name": hz_name,
            "Description": hz.get("description", ""),
            "IsStratigraphic": hz.get("is_stratigraphic", True),
        }
        if hz.get("horizon_uuid") and rddms_ds:
            eml_uri = f"eml:///dataspace('{rddms_ds}')/resqml20.obj_HorizonInterpretation('{hz['horizon_uuid']}')"
            data["ResourceURI"] = eml_uri
            data["ResourceID"] = hz["horizon_uuid"]
        if hz.get("feature_uuid") and rddms_ds:
            data["GeneticBoundaryFeatureID"] = hz["feature_uuid"]

        records.append({
            "id": hz_id,
            "kind": "osdu:wks:work-product-component--HorizonInterpretation:1.0.0",
            "acl": acl, "legal": legal, "data": data,
        })

    return records, strat_col_id


