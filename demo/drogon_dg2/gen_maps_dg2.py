#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_maps_dg2.py - Generate OSDU StructureMap and GenericRepresentation WPC
catalog records for the Drogon DG2 surface/map outputs.

The actual surface arrays live in the RDDMS dataspace
(eml:///dataspace(maap/drogon_dg)), exported from RMS via fmu-dataio.
This generator creates OSDU **catalog records** that reference the
RDDMS Grid2dRepresentations, enabling OSDU search/query.

Surface categories (49 maps per realization):
  - Depth surface extracts (6 horizons × 2 sources = 12)  → StructureMap
  - Amplitude maps (5 horizons × 2 attributes = 10)        → GenericRepresentation
  - Facies fraction maps (3 zones × ~4 facies = 12)         → GenericRepresentation
  - Average property maps (3 zones × 2 props = 6)           → GenericRepresentation
  - APS probability maps (3 zones × 3 facies = 9)           → GenericRepresentation

For the demo we generate P50/aggregated representatives, not all 250 realizations.

Reads:
  ../drogon/manifest_masterwp_drogon.json  - Reservoir, acl, legal
  manifest_grid_dg2.json                   - Grid WPC ID for ancestry

Output:
  manifest_maps_dg2.json

Usage:
  python demo/drogon_dg2/gen_maps_dg2.py
"""

from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path
from typing import Any, Dict, List

SCRIPT_DIR = Path(__file__).resolve().parent
DG1_DIR    = SCRIPT_DIR.parent / "drogon"

import sys
if str(DG1_DIR) not in sys.path:
    sys.path.insert(0, str(DG1_DIR))
from _shared import load_json  # noqa: E402

# ── Deterministic UUIDs ─────────────────────────────────────────────
_NS = uuid.UUID("a0000000-d509-4e00-8000-000000000000")

def _map_uuid(name: str) -> str:
    return str(uuid.uuid5(_NS, f"dg2-map-{name}"))

# ── RDDMS dataspace ────────────────────────────────────────────────
DATASPACE_NAME = "maap/drogon_dg"
RDDMS_BASE     = f"eml:///dataspace('{DATASPACE_NAME}')"

# ── CRS / grid geometry (from fmu-dataio sidecars) ──────────────────
CRS_ID  = "ST_WGS84_UTM37N_P32637"
GRID_NI = 280          # nodes on I axis
GRID_NJ = 440          # nodes on J axis
INCREMENT = 25.0       # m

# ── Horizons & zones ────────────────────────────────────────────────
HORIZONS = ["TopVolantis", "TopTherys", "TopVolon", "BaseVolon", "BaseVolantis", "MSL"]
DEPTH_HORIZONS = ["TopVolantis", "TopTherys", "TopVolon", "BaseVolon", "BaseVolantis", "MSL"]
AMPLITUDE_HORIZONS = ["TopVolantis", "TopTherys", "TopVolon", "BaseVolon", "BaseVolantis"]
ZONES = ["Valysar", "Therys", "Volon"]

# ── Facies per zone ─────────────────────────────────────────────────
ZONE_FACIES = {
    "Valysar": ["channel", "crevasse", "floodplain", "coal"],
    "Therys":  ["uppershoreface", "lowershoreface", "offshore", "calcite"],
    "Volon":   ["channel", "floodplain", "calcite", "coal"],
}

DEFAULT_ACL = {
    "owners":  ["data.ores.owners@dev.dataservices.energy"],
    "viewers": ["data.office.global.viewers@dev.dataservices.energy"],
}
DEFAULT_LEGAL = {
    "legaltags": ["dev-equinor-private-default"],
    "otherRelevantDataCountries": ["NO"],
}


def _find_id(manifest: Dict, kind_fragment: str) -> str:
    for md in manifest.get("MasterData", []):
        if kind_fragment in md.get("kind", ""):
            return md["id"]
    for wpc in manifest.get("Data", {}).get("WorkProductComponents", []):
        if kind_fragment in wpc.get("kind", ""):
            return wpc["id"]
    return ""


def _surface_record(
    pfx: str,
    name: str,
    description: str,
    content: str,
    attribute: str,
    *,
    osdu_kind: str,
    horizon: str = "",
    zone: str = "",
    acl: dict,
    legal: dict,
    reservoir_id: str,
    grid_id: str = "",
    dataspace_id: str = "",
    domain: str = "Depth",
    standard_result: str = "",
    facet_statistics: str = "",
) -> Dict[str, Any]:
    """Build a single surface/map WPC record."""
    map_id = f"{pfx}:work-product-component--{osdu_kind}:{_map_uuid(name)}:1"

    data: Dict[str, Any] = {
        "Name": f"Drogon DG2 - {name}",
        "Description": description,
        "CoordinateReferenceSystemID": f"{pfx}:reference-data--CoordinateReferenceSystem:{CRS_ID}:",
        "ReservoirID": reservoir_id,
        "NodeCountOnIAxis": GRID_NI,
        "NodeCountOnJAxis": GRID_NJ,
        "BinWidthOnIaxis": INCREMENT,
        "BinWidthOnJaxis": INCREMENT,
        "DDMSDatasets": [
            f"{RDDMS_BASE}/resqml22.Grid2dRepresentation('{_map_uuid(name)}')"
        ],
        "FMU": {
            "Content": content,
            "PropertyAttribute": attribute,
        },
    }

    if domain:
        data["DomainTypeID"] = f"{pfx}:reference-data--DomainType:{domain}:"

    if horizon:
        data["HorizonName"] = horizon
        data["FMU"]["StratigraphicReference"] = horizon
    if zone:
        data["ZoneName"] = zone
        data["FMU"]["StratigraphicReference"] = zone

    if standard_result:
        data["FMU"]["StandardResult"] = standard_result

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
        "id":   map_id,
        "kind": f"osdu:wks:work-product-component--{osdu_kind}:1.0.0",
        "acl":  acl,
        "legal": legal,
        "data": data,
    }


def main():
    ap = argparse.ArgumentParser(description="Generate DG2 surface/map WPC catalog records")
    ap.add_argument("--masterwp",  default=str(DG1_DIR / "manifest_masterwp_drogon.json"))
    ap.add_argument("--grid",      default=str(SCRIPT_DIR / "manifest_grid_dg2.json"))
    ap.add_argument("--manifest",  default=str(SCRIPT_DIR / "manifest_maps_dg2.json"))
    ap.add_argument("--id-prefix", default="dev")
    args = ap.parse_args()

    pfx = args.id_prefix
    masterwp = load_json(args.masterwp)

    reservoir_id = ""
    acl = DEFAULT_ACL
    legal = DEFAULT_LEGAL
    for md in masterwp.get("MasterData", []):
        if "master-data--Reservoir:" in md.get("kind", ""):
            reservoir_id = md["id"]
            acl = md["acl"]
            legal = md["legal"]

    # Grid WPC ID for ancestry
    grid_id = ""
    grid_path = Path(args.grid)
    if grid_path.exists():
        grid_man = load_json(str(grid_path))
        grid_id = _find_id(grid_man, "IjkGridRepresentation")

    dataspace_id = f"{pfx}:dataset--ETPDataspace:maap-drogon_dg:1"

    common = dict(acl=acl, legal=legal, reservoir_id=reservoir_id,
                  grid_id=grid_id, dataspace_id=dataspace_id)

    records: List[Dict[str, Any]] = []

    # ── 1. Depth surface extracts (StructureMap) ─────────────────
    for hz in DEPTH_HORIZONS:
        for source in ("ds_extract_geogrid", "ds_extract_postprocess"):
            hz_lower = hz.lower()
            name = f"{hz_lower}--{source}"
            records.append(_surface_record(
                pfx, name,
                f"Grid-extracted depth surface for {hz} ({source})",
                content="depth", attribute="depth",
                osdu_kind="StructureMap",
                horizon=hz,
                standard_result="structure_depth_surface" if "postprocess" in source else "grid_extracted_depth_surface",
                facet_statistics="P50",
                **common,
            ))

    # ── 2. Amplitude maps (GenericRepresentation) ────────────────
    for hz in AMPLITUDE_HORIZONS:
        for attr in ("near", "far"):
            hz_lower = hz.lower()
            name = f"{hz_lower}--amplitude_{attr}_2018"
            records.append(_surface_record(
                pfx, name,
                f"Seismic amplitude extraction ({attr} offset, 2018 vintage) at {hz}",
                content="seismic", attribute=f"amplitude_{attr}",
                osdu_kind="GenericRepresentation",
                horizon=hz,
                facet_statistics="P50",
                **common,
            ))

    # ── 3. Facies fraction maps (GenericRepresentation) ──────────
    for zone, facies_list in ZONE_FACIES.items():
        for facies in facies_list:
            zone_lower = zone.lower()
            name = f"{zone_lower}--facies_fraction_{facies}"
            records.append(_surface_record(
                pfx, name,
                f"Facies fraction map: {facies} in {zone} zone",
                content="property", attribute=f"facies_fraction_{facies}",
                osdu_kind="GenericRepresentation",
                zone=zone,
                facet_statistics="P50",
                **common,
            ))

    # ── 4. Average property maps (GenericRepresentation) ─────────
    for zone in ZONES:
        for prop, attr in [("phit", "porosity"), ("klogh", "permeability")]:
            zone_lower = zone.lower()
            name = f"{zone_lower}--{prop}_average"
            records.append(_surface_record(
                pfx, name,
                f"Zone-averaged {attr} map for {zone}",
                content="property", attribute=attr,
                osdu_kind="GenericRepresentation",
                zone=zone,
                facet_statistics="P50",
                **common,
            ))

    # ── 5. APS probability maps (GenericRepresentation) ──────────
    aps_facies = {
        "Valysar": ["channel", "crevasse", "floodplain"],
        "Therys":  ["uppershoreface", "lowershoreface", "offshore"],
        "Volon":   ["channel", "floodplain", "calcite"],
    }
    for zone, facies_list in aps_facies.items():
        for facies in facies_list:
            zone_lower = zone.lower()
            name = f"{zone_lower}--aps_probability_{facies}"
            records.append(_surface_record(
                pfx, name,
                f"APS facies probability map: {facies} in {zone}",
                content="property", attribute=f"aps_probability_{facies}",
                osdu_kind="GenericRepresentation",
                zone=zone,
                facet_statistics="P50",
                **common,
            ))

    # ── Assemble manifest ────────────────────────────────────────
    manifest: Dict[str, Any] = {
        "kind": "osdu:wks:Manifest:1.0.0",
        "ReferenceData": [],
        "MasterData": [],
        "Data": {
            "Datasets": [],
            "WorkProductComponents": records,
            "WorkProducts": [],
        },
    }

    out = Path(args.manifest)
    out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    # Summarise
    n_smap = sum(1 for r in records if "StructureMap" in r["kind"])
    n_gen  = sum(1 for r in records if "GenericRepresentation" in r["kind"])
    print(f"DG2 Maps manifest written → {args.manifest}")
    print(f"  StructureMap WPCs       : {n_smap}")
    print(f"  GenericRepresentation   : {n_gen}")
    print(f"  Total surface records   : {len(records)}")
    print(f"  RDDMS base              : {RDDMS_BASE}")


if __name__ == "__main__":
    main()
