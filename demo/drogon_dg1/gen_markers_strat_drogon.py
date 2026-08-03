#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_markers_strat_drogon.py  –  Generate WellboreMarkerSet WPCs and a
lithostratigraphic StratigraphicColumn (with RankInterpretation + UnitInterpretation)
for the Drogon and Volve wells.

Creates:
  - WellboreMarkerSet per wellbore (formation tops with MD/TVD)
  - StratigraphicColumn  (Drogon-Volve lithostratigraphy)
  - StratigraphicColumnRankInterpretation  (Formation / Group / Member ranks)
  - StratigraphicUnitInterpretation  (per formation unit)
  - HorizonInterpretation  (cross-referenced to RDDMS objects by UUID)

The HorizonInterpretation records bridge the catalog and RDDMS:
  - 4 stratigraphic horizons (TopVolantis, TopTherys, TopVolon, BaseVolantis)
  - 2 technical boundaries (MSL, BaseVelmodel)
  - Each record includes ResourceURI/ResourceID matching the RDDMS UUID
  - Federated GraphQL uses this to traverse:
      catalog HorizonInterp → RDDMS → Grid2D surfaces, PointSets, Marker sets

Output:
  manifest_markers_drogon.json     – WellboreMarkerSet records
  manifest_litho_strat_drogon.json – StratColumn + Rank + Unit + Horizon records

Usage:
    python demo/drogon_dg1/gen_markers_strat_drogon.py
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Dict, List

SCRIPT_DIR = Path(__file__).resolve().parent

# ── OSDU envelope defaults (same as gen_wells_drogon.py) ────────────────
ID_PREFIX   = "dev"
OWNERS      = ["data.default.owners@dev.dataservices.energy"]
VIEWERS     = ["data.office.global.viewers@dev.dataservices.energy"]
LEGAL_TAGS  = ["dev-equinor-private-default"]
COUNTRY     = ["NO"]

# Schema kinds
MARKERSET_KIND  = "osdu:wks:work-product-component--WellboreMarkerSet:1.2.0"
STRATCOL_KIND   = "osdu:wks:work-product-component--StratigraphicColumn:1.2.0"
RANK_KIND       = "osdu:wks:work-product-component--StratigraphicColumnRankInterpretation:1.3.0"
UNIT_KIND       = "osdu:wks:work-product-component--StratigraphicUnitInterpretation:1.3.0"
HORIZON_KIND    = "osdu:wks:work-product-component--HorizonInterpretation:1.0.0"

# ── RDDMS cross-reference UUIDs (from maap/drogon EPC dataset) ──────────
# These enable federated GraphQL to match catalog WPC records ↔ RDDMS objects
# by UUID, bridging OSDU metadata with RESQML object-graph relationships.
# The RESQML hierarchy in RDDMS is:
#   Grid2dRepresentation → HorizonInterpretation → GeneticBoundaryFeature
#   StratigraphicColumn → ColumnRankInterp → UnitInterp ↔ HorizonInterp
# The catalog mirrors this with WPC records cross-referenced by ResourceURI.
RDDMS_DATASPACE = "maap/drogon"

# (name, HorizonInterpretation UUID, GeneticBoundaryFeature UUID, is_strat, description)
RDDMS_HORIZONS = [
    ("TopVolantis",  "02e954a9-d7db-4b57-aef7-12b8ebf47a65", "2d66e9f5-f120-43c4-93ca-1c8220846fbb", True,
     "Top Volantis (Valysar) reservoir \u2013 main Drogon pay zone boundary"),
    ("TopTherys",    "6c6eeb68-bb4d-4fa4-9eb4-b880b5bd7086", "49cd1075-1eef-4950-8e50-2bec81ca4275", True,
     "Top Therys source rock \u2013 organic-rich shale boundary"),
    ("TopVolon",     "db54a781-84ad-41e5-8bdd-c510246375cd", "e185b471-9f88-446d-b36e-00c77a7cf0b8", True,
     "Top Volon lower reservoir formation boundary"),
    ("BaseVolantis", "3657ca0b-d21f-41ca-801b-4a6a7eb1f426", "67349b6a-2004-43ed-94bc-43e90b584aad", True,
     "Base Volantis (Valysar) reservoir \u2013 seal contact"),
    ("MSL",          "7da0e4d7-1955-4031-8eaf-68a93515414d", "0c402b9f-fa0e-4c36-a08f-37f292115e01", False,
     "Mean Sea Level datum \u2013 technical reference surface (not stratigraphic)"),
    ("BaseVelmodel", "011ae8ee-bfa5-4804-a675-1f4704b1730c", "d9593949-6e2a-4514-802f-001d0a6c3708", False,
     "Base of velocity model \u2013 geophysical boundary (not stratigraphic)"),
]

# Catalog formation name → (RDDMS StratigraphicUnitInterpretation UUID, zone alias)
# In RDDMS the Drogon EPC uses zone names; the catalog uses formal formation names.
RDDMS_UNIT_XREFS: Dict[str, tuple] = {
    "Volantis Formation": ("0b257a04-c38c-4c56-9e18-987b03583830", "Valysar"),
    "Therys Formation":   ("7c70894a-2442-4735-a219-c954f87ba07d", "Therys"),
    "Volon Formation":    ("e3be3316-0ea0-4c20-9722-14a2174ce7ab", "Volon"),
}


def _uid() -> str:
    return str(uuid.uuid4())


def _acl() -> Dict[str, Any]:
    return {"owners": OWNERS, "viewers": VIEWERS}


def _legal() -> Dict[str, Any]:
    return {"legaltags": LEGAL_TAGS, "otherRelevantDataCountries": COUNTRY}


# ═════════════════════════════════════════════════════════════════════════
#  Wellbore IDs from the generated wells manifest
#  (must match manifest_wells_drogon.json)
# ═════════════════════════════════════════════════════════════════════════
def _load_wellbore_ids() -> Dict[str, str]:
    """Load wellbore name → ID mapping from the wells manifest."""
    manifest_path = SCRIPT_DIR / "manifest_wells_drogon.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Run gen_wells_drogon.py first: {manifest_path}")
    with open(manifest_path) as f:
        manifest = json.load(f)
    mapping: Dict[str, str] = {}
    for rec in manifest.get("MasterData", []):
        if "Wellbore:" in rec.get("kind", ""):
            name = rec["data"].get("Name", rec["data"].get("FacilityName", ""))
            mapping[name] = rec["id"]
    return mapping


# ═════════════════════════════════════════════════════════════════════════
#  Formation tops per wellbore
#  (synthetic but geologically plausible depths)
# ═════════════════════════════════════════════════════════════════════════

# Drogon formations (Valysar zone, North-Sea-like Jurassic play)
DROGON_FORMATIONS = [
    # (MarkerName, typical MD range min, max, TVD offset from MD)
    ("Seabed",           400,  450,  0),
    ("TopNordland",     1200, 1350, -5),
    ("TopShetland",     1800, 1950, -10),
    ("TopTherys",       2650, 2800, -15),
    ("TopVolon",        2850, 3000, -18),
    ("TopVolantis",     3050, 3200, -20),
    ("BaseVolantis",    3250, 3400, -22),
    ("BaseVolon",       3350, 3500, -24),
    ("TopPre-Jurassic", 3600, 3800, -28),
]

# Volve formations (Hugin Fm, North Sea – 15/9 area)
VOLVE_FORMATIONS = [
    ("Seabed",          100,  120,   0),
    ("TopNordland",     900, 1000,  -3),
    ("TopShetland",    2400, 2550,  -8),
    ("TopDraupne",     2800, 2900, -12),
    ("TopHeather",     2950, 3050, -14),
    ("TopHugin",       3100, 3200, -16),
    ("BaseHugin",      3250, 3350, -18),
    ("TopSleipner",    3350, 3450, -20),
    ("TopSkagerrak",   3500, 3600, -22),
    ("TopBasement",    3700, 3850, -25),
]

# Per-wellbore depth offsets (to make each well unique)
WELLBORE_DEPTH_SEEDS = {
    # Drogon – deeper target = deeper structure
    "55/33-A-1":     0,
    "55/33-A-2":    40,
    "55/33-A-2 T2": 80,
    "55/33-A-3":   -20,
    # Volve – slight depth variations per slot
    "15/9-F-1 C":    0,
    "15/9-F-4":     15,
    "15/9-F-5":    -10,
    "15/9-F-7":     25,
    "15/9-F-11 A":  35,
    "15/9-F-15 D":  50,
    "15/9-F-15 S":  65,
}


def _markers_for_wellbore(
    wb_name: str,
    formations: List[tuple],
    depth_seed: int,
) -> List[Dict[str, Any]]:
    """Generate a Markers array for a wellbore."""
    import hashlib
    markers: List[Dict[str, Any]] = []
    for i, (name, md_min, md_max, tvd_offset) in enumerate(formations):
        # Deterministic pseudo-random depth based on wellbore name + formation
        h = int(hashlib.md5(f"{wb_name}-{name}".encode()).hexdigest()[:8], 16)
        frac = (h % 1000) / 1000.0
        md = round(md_min + depth_seed + frac * (md_max - md_min), 1)
        tvd = round(md + tvd_offset, 1)
        markers.append({
            "MarkerName": name,
            "MarkerMeasuredDepth": md,
            "MarkerSubSeaVerticalDepth": tvd,
            "MarkerObservationNumber": i + 1,
            "Missing": "",
            "MarkerTypeID": "",
            "InterpretationID": "",
            "MarkerInterpreter": "gen_markers_strat_drogon.py",
            "GeologicalAge": "",
        })
    return markers


def _markerset_record(
    wb_name: str,
    wb_id: str,
    markers: List[Dict[str, Any]],
    strat_col_id: str,
) -> Dict[str, Any]:
    uid = _uid()
    rec_id = f"{ID_PREFIX}:work-product-component--WellboreMarkerSet:{uid}:"
    return {
        "id": rec_id,
        "kind": MARKERSET_KIND,
        "acl": _acl(),
        "legal": _legal(),
        "data": {
            "Name": f"{wb_name} – Formation Tops",
            "Description": f"Formation top picks for wellbore {wb_name}",
            "WellboreID": wb_id,
            "Markers": markers,
            "StratigraphicColumnID": strat_col_id,
            "StratigraphicColumnRankInterpretationID": "",
        },
    }


# ═════════════════════════════════════════════════════════════════════════
#  Lithostratigraphic Column  (Drogon + Volve combined)
# ═════════════════════════════════════════════════════════════════════════

# Unit definitions: (unit_name, rank, older_age_Ma, younger_age_Ma, description)
LITHO_UNITS = [
    # Group-level units
    ("Nordland Group",       "Group",     23.0,    0.0,  "Neogene–Quaternary overburden, North Sea"),
    ("Shetland Group",       "Group",     66.0,   23.0,  "Palaeocene–Eocene chalk and marl"),
    # Drogon formations
    ("Therys Formation",     "Formation", 170.0, 163.0,  "Source rock unit – organic-rich shale, Drogon area"),
    ("Volon Formation",      "Formation", 163.0, 157.0,  "Lower reservoir unit, Drogon field (Valysar zone)"),
    ("Volantis Formation",   "Formation", 157.0, 145.0,  "Main reservoir unit, Drogon field (Valysar zone)"),
    # Volve formations
    ("Draupne Formation",    "Formation", 155.0, 145.0,  "Late Jurassic source/cap rock, Viking Graben"),
    ("Heather Formation",    "Formation", 164.0, 155.0,  "Marine shale, mid-Jurassic, Viking Graben"),
    ("Hugin Formation",      "Formation", 170.0, 164.0,  "Reservoir sandstone, Volve field – Bajocian–Bathonian"),
    ("Sleipner Formation",   "Formation", 175.0, 170.0,  "Lower Jurassic marine limestone/sandstone"),
    ("Skagerrak Formation",  "Formation", 250.0, 200.0,  "Triassic red beds and evaporites"),
    # Member-level (Drogon sub-units of Volantis Fm)
    ("Upper Volantis Member",    "Member",  157.0, 152.0, "Upper reservoir sand, Drogon – good porosity"),
    ("Lower Volantis Member",    "Member",  152.0, 145.0, "Lower reservoir sand, Drogon – cemented intervals"),
]


def _generate_strat_column() -> tuple:
    """Generate StratColumn + Rank + Unit records.

    Returns (strat_col_id, list_of_records).
    """
    records: List[Dict[str, Any]] = []

    # ── Unit records ────────────────────────────────────────────────
    unit_ids: Dict[str, str] = {}
    rank_units: Dict[str, List[str]] = {"Group": [], "Formation": [], "Member": []}

    for unit_name, rank, older_age, younger_age, desc in LITHO_UNITS:
        uid = _uid()
        unit_id = f"{ID_PREFIX}:work-product-component--StratigraphicUnitInterpretation:Drogon-Volve-{unit_name.replace(' ', '')}:"
        unit_ids[unit_name] = unit_id
        rank_units[rank].append(unit_id)

        data: Dict[str, Any] = {
            "Name": unit_name,
            "Description": desc,
            "StratigraphicRoleTypeID": "",
            "ChronoStratigraphyID": "",
            "OlderPossibleAge": older_age,
            "YoungerPossibleAge": younger_age,
            "ColumnStratigraphicHorizonTopID": "",
            "ColumnStratigraphicHorizonBaseID": "",
        }

        # Cross-reference to RDDMS StratigraphicUnitInterpretation
        if unit_name in RDDMS_UNIT_XREFS:
            rddms_uuid, zone_alias = RDDMS_UNIT_XREFS[unit_name]
            eml_uri = f"eml:///dataspace('{RDDMS_DATASPACE}')/resqml20.obj_StratigraphicUnitInterpretation('{rddms_uuid}')"
            data["ResourceURI"] = eml_uri
            data["ResourceID"] = rddms_uuid
            data["ExtraMetadata"] = {
                "rddms_dataspace": RDDMS_DATASPACE,
                "rddms_uuid": rddms_uuid,
                "rddms_type": "resqml20.obj_StratigraphicUnitInterpretation",
                "rddms_zone_alias": zone_alias,
                "note": f"RDDMS uses zone name '{zone_alias}' for this formation",
            }

        records.append({
            "id": unit_id,
            "kind": UNIT_KIND,
            "acl": _acl(),
            "legal": _legal(),
            "data": data,
        })

    # ── Rank records ────────────────────────────────────────────────
    rank_ids: Dict[str, str] = {}
    for rank_name in ["Group", "Formation", "Member"]:
        rank_id = f"{ID_PREFIX}:work-product-component--StratigraphicColumnRankInterpretation:Drogon-Volve-Litho-{rank_name}:"
        rank_ids[rank_name] = rank_id

        unit_set = []
        for u_id in rank_units[rank_name]:
            unit_set.append({"StratigraphicUnitInterpretationID": u_id})

        records.append({
            "id": rank_id,
            "kind": RANK_KIND,
            "acl": _acl(),
            "legal": _legal(),
            "data": {
                "Name": f"Drogon-Volve Lithostratigraphy – {rank_name}",
                "RankName": rank_name,
                "StratigraphicRoleType": "",
                "StratigraphicUnitInterpretationSet": unit_set,
            },
        })

    # ── Column record ───────────────────────────────────────────────
    strat_col_id = f"{ID_PREFIX}:work-product-component--StratigraphicColumn:Drogon-Volve-Lithostratigraphy:"

    rank_set = []
    for rank_name in ["Group", "Formation", "Member"]:
        rank_set.append({
            "StratigraphicColumnRankInterpretationID": rank_ids[rank_name],
        })

    records.append({
        "id": strat_col_id,
        "kind": STRATCOL_KIND,
        "acl": _acl(),
        "legal": _legal(),
        "data": {
            "Name": "Drogon-Volve Lithostratigraphy",
            "Description": "Lithostratigraphic column for the Drogon (Valysar zone) and Volve (Hugin Fm) fields. Covers North Sea Jurassic–Cretaceous stratigraphy from Seabed through Nordland, Shetland, Draupne/Heather, Hugin, Therys, Volon, Volantis, Sleipner and Skagerrak formations.",
            "StratigraphicColumnRankInterpretationSet": rank_set,
            "StratigraphicColumnValidityAreaType": "",
            "ValueChainStatusType": "",
        },
    })

    return strat_col_id, records


def _generate_horizon_records() -> List[Dict[str, Any]]:
    """Generate HorizonInterpretation WPC records cross-referenced to RDDMS.

    These catalog records match the RDDMS HorizonInterpretation objects by UUID,
    enabling federated GraphQL queries to bridge catalog metadata with the RDDMS
    RESQML object graph:
      Grid2dRepresentation → HorizonInterpretation → GeneticBoundaryFeature

    4 horizons are stratigraphic (part of the strat column), 2 are technical
    (MSL datum, velocity-model base) that bound surfaces but are not geological.
    """
    records: List[Dict[str, Any]] = []
    for name, interp_uuid, feature_uuid, is_strat, desc in RDDMS_HORIZONS:
        # Use the RDDMS UUID in the record ID so federated search matches by UUID
        rec_id = f"{ID_PREFIX}:work-product-component--HorizonInterpretation:{interp_uuid}:"
        eml_interp = (
            f"eml:///dataspace('{RDDMS_DATASPACE}')/"
            f"resqml20.obj_HorizonInterpretation('{interp_uuid}')"
        )
        eml_feature = (
            f"eml:///dataspace('{RDDMS_DATASPACE}')/"
            f"resqml20.obj_GeneticBoundaryFeature('{feature_uuid}')"
        )
        records.append({
            "id": rec_id,
            "kind": HORIZON_KIND,
            "acl": _acl(),
            "legal": _legal(),
            "data": {
                "Name": name,
                "Description": desc,
                "SchemaFormatTypeID": (
                    "application/x-resqml+xml;version=2.0;"
                    "type=obj_HorizonInterpretation"
                ),
                "ResourceURI": eml_interp,
                "ResourceID": interp_uuid,
                "IsStratigraphicBoundary": is_strat,
                "ExtraMetadata": {
                    "rddms_dataspace": RDDMS_DATASPACE,
                    "rddms_uuid": interp_uuid,
                    "rddms_type": "resqml20.obj_HorizonInterpretation",
                    "rddms_feature_uuid": feature_uuid,
                    "rddms_feature_type": "resqml20.obj_GeneticBoundaryFeature",
                    "rddms_feature_uri": eml_feature,
                    "boundary_class": "stratigraphic" if is_strat else "technical",
                },
            },
        })
    return records


# ═════════════════════════════════════════════════════════════════════════
#  Main
# ═════════════════════════════════════════════════════════════════════════
def generate() -> None:
    wb_ids = _load_wellbore_ids()

    # ── 1. Generate StratColumn + Horizons ──────────────────────────
    strat_col_id, strat_records = _generate_strat_column()
    horizon_records = _generate_horizon_records()
    all_strat_records = strat_records + horizon_records
    strat_manifest = {
        "kind": "osdu:wks:Manifest:1.0.0",
        "ReferenceData": [],
        "MasterData": [],
        "Data": {
            "WorkProduct": None,
            "WorkProductComponents": all_strat_records,
        },
    }
    strat_out = SCRIPT_DIR / "manifest_litho_strat_drogon.json"
    with open(strat_out, "w", encoding="utf-8") as f:
        json.dump(strat_manifest, f, indent=2)

    n_units = sum(1 for r in strat_records if "UnitInterpretation" in r["kind"])
    n_ranks = sum(1 for r in strat_records if "RankInterpretation" in r["kind"])
    n_horizons = len(horizon_records)
    n_strat_hz = sum(1 for _, _, _, s, _ in RDDMS_HORIZONS if s)
    print(f"Generated {strat_out.name}:")
    print(f"  1 StratigraphicColumn")
    print(f"  {n_ranks} RankInterpretations (Group, Formation, Member)")
    print(f"  {n_units} UnitInterpretations")
    for r in strat_records:
        if "UnitInterpretation" in r["kind"]:
            d = r["data"]
            xref = f"  ← RDDMS zone '{d['ExtraMetadata']['rddms_zone_alias']}'" if "ExtraMetadata" in d else ""
            print(f"    {d['Name']:30s}  {d['OlderPossibleAge']:6.1f}–{d['YoungerPossibleAge']:6.1f} Ma{xref}")
    print(f"  {n_horizons} HorizonInterpretations ({n_strat_hz} stratigraphic, {n_horizons - n_strat_hz} technical)")
    for r in horizon_records:
        d = r["data"]
        tag = "strat" if d.get("IsStratigraphicBoundary") else "technical"
        print(f"    {d['Name']:30s}  [{tag}]  RDDMS UUID {d['ResourceID']}")

    # ── 2. Generate WellboreMarkerSets ──────────────────────────────
    marker_records: List[Dict[str, Any]] = []

    for wb_name, wb_id in sorted(wb_ids.items()):
        # Determine which formation set to use
        if wb_name.startswith("55/33"):
            formations = DROGON_FORMATIONS
        elif wb_name.startswith("15/9"):
            formations = VOLVE_FORMATIONS
        else:
            continue

        depth_seed = WELLBORE_DEPTH_SEEDS.get(wb_name, 0)
        markers = _markers_for_wellbore(wb_name, formations, depth_seed)
        rec = _markerset_record(wb_name, wb_id, markers, strat_col_id)
        marker_records.append(rec)

    marker_manifest = {
        "kind": "osdu:wks:Manifest:1.0.0",
        "ReferenceData": [],
        "MasterData": [],
        "Data": {
            "WorkProduct": None,
            "WorkProductComponents": marker_records,
        },
    }
    markers_out = SCRIPT_DIR / "manifest_markers_drogon.json"
    with open(markers_out, "w", encoding="utf-8") as f:
        json.dump(marker_manifest, f, indent=2)

    print(f"\nGenerated {markers_out.name}:")
    print(f"  {len(marker_records)} WellboreMarkerSet records:")
    for r in marker_records:
        d = r["data"]
        n_markers = len(d["Markers"])
        print(f"    {d['Name']:40s}  {n_markers} markers")


if __name__ == "__main__":
    generate()
