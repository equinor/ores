#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_wells_drogon.py  –  Generate Well + Wellbore master-data for the Drogon
synthetic field plus a small Volve well set.

Creates proper OSDU hierarchy:
  Well  →  Wellbore  →  (WellLog / WellboreTrajectory / WellboreMarkerSet)

Output:  manifest_wells_drogon.json

Usage:
    python demo/drogon_dg1/gen_wells_drogon.py
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Dict, List

SCRIPT_DIR = Path(__file__).resolve().parent

# ── OSDU envelope defaults ──────────────────────────────────────────────
ID_PREFIX   = "dev"
OWNERS      = ["data.default.owners@dev.dataservices.energy"]
VIEWERS     = ["data.office.global.viewers@dev.dataservices.energy"]
LEGAL_TAGS  = ["dev-equinor-private-default"]
COUNTRY     = ["NO"]

WELL_KIND     = "osdu:wks:master-data--Well:1.0.0"
WELLBORE_KIND = "osdu:wks:master-data--Wellbore:1.0.0"


def _uid() -> str:
    return str(uuid.uuid4())


def _acl() -> Dict[str, Any]:
    return {"owners": OWNERS, "viewers": VIEWERS}


def _legal() -> Dict[str, Any]:
    return {"legaltags": LEGAL_TAGS, "otherRelevantDataCountries": COUNTRY}


# ── Well definitions ────────────────────────────────────────────────────
# Drogon: 3 exploration/appraisal wells typical for a North-Sea-style field
# Volve: 6 key production / injection wells from the real Volve dataset
WELLS: List[Dict[str, Any]] = [
    # ── Drogon wells ─────────────────────────────────────────────────
    {
        "name": "55/33-A-1",
        "facility": "55/33-A-1",
        "field": "Drogon",
        "description": "Drogon exploration well - discovery well targeting Valysar Fm.",
        "wellbores": [
            {"name": "55/33-A-1",   "facility": "55/33-A-1",
             "desc": "Main bore of discovery well 55/33-A-1",
             "target": "Valysar Fm", "seq": 1},
        ],
    },
    {
        "name": "55/33-A-2",
        "facility": "55/33-A-2",
        "field": "Drogon",
        "description": "Drogon appraisal well - delineation of Central Horst compartment.",
        "wellbores": [
            {"name": "55/33-A-2",   "facility": "55/33-A-2",
             "desc": "Main bore of appraisal well 55/33-A-2",
             "target": "Valysar Fm", "seq": 1},
            {"name": "55/33-A-2 T2", "facility": "55/33-A-2 T2",
             "desc": "Side-track targeting West Lowland segment",
             "target": "Valysar Fm", "seq": 2},
        ],
    },
    {
        "name": "55/33-A-3",
        "facility": "55/33-A-3",
        "field": "Drogon",
        "description": "Drogon appraisal well - delineation of East Lowland compartment.",
        "wellbores": [
            {"name": "55/33-A-3",   "facility": "55/33-A-3",
             "desc": "Main bore of appraisal well 55/33-A-3",
             "target": "Valysar Fm", "seq": 1},
        ],
    },
    # ── Volve wells ──────────────────────────────────────────────────
    {
        "name": "15/9-F-1",
        "facility": "15/9-F-1",
        "field": "Volve",
        "description": "Volve production well - Hugin Fm, NCS licence PL 252.",
        "wellbores": [
            {"name": "15/9-F-1 C",  "facility": "15/9-F-1 C",
             "desc": "Re-entry wellbore-C, Hugin Fm producer",
             "target": "Hugin Fm", "seq": 1},
        ],
    },
    {
        "name": "15/9-F-4",
        "facility": "15/9-F-4",
        "field": "Volve",
        "description": "Volve production well - Hugin Fm, NCS licence PL 252.",
        "wellbores": [
            {"name": "15/9-F-4",    "facility": "15/9-F-4",
             "desc": "Main bore, Hugin Fm producer",
             "target": "Hugin Fm", "seq": 1},
        ],
    },
    {
        "name": "15/9-F-5",
        "facility": "15/9-F-5",
        "field": "Volve",
        "description": "Volve water injection well - Hugin Fm, NCS licence PL 252.",
        "wellbores": [
            {"name": "15/9-F-5",    "facility": "15/9-F-5",
             "desc": "Main bore, Hugin Fm water injector",
             "target": "Hugin Fm", "seq": 1},
        ],
    },
    {
        "name": "15/9-F-7",
        "facility": "15/9-F-7",
        "field": "Volve",
        "description": "Volve production well - Hugin Fm, NCS licence PL 252.",
        "wellbores": [
            {"name": "15/9-F-7",    "facility": "15/9-F-7",
             "desc": "Main bore, Hugin Fm producer",
             "target": "Hugin Fm", "seq": 1},
        ],
    },
    {
        "name": "15/9-F-11",
        "facility": "15/9-F-11",
        "field": "Volve",
        "description": "Volve production well - Hugin Fm, NCS licence PL 252.",
        "wellbores": [
            {"name": "15/9-F-11 A", "facility": "15/9-F-11 A",
             "desc": "Bore A, Hugin Fm producer",
             "target": "Hugin Fm", "seq": 1},
        ],
    },
    {
        "name": "15/9-F-15",
        "facility": "15/9-F-15",
        "field": "Volve",
        "description": "Volve production / injection well - Hugin Fm, NCS licence PL 252.",
        "wellbores": [
            {"name": "15/9-F-15 D", "facility": "15/9-F-15 D",
             "desc": "Re-entry D, Hugin Fm producer/injector",
             "target": "Hugin Fm", "seq": 1},
            {"name": "15/9-F-15 S", "facility": "15/9-F-15 S",
             "desc": "Side-track S, Hugin Fm",
             "target": "Hugin Fm", "seq": 2},
        ],
    },
]


def _well_record(name: str, facility: str, field: str,
                 description: str, wellbore_ids: List[str]) -> Dict[str, Any]:
    uid = _uid()
    well_id = f"{ID_PREFIX}:master-data--Well:{uid}:1"
    return {
        "_well_id": well_id,            # transient – stripped before output
        "id": well_id,
        "kind": WELL_KIND,
        "acl": _acl(),
        "legal": _legal(),
        "data": {
            "Name": name,
            "FacilityName": facility,
            "Description": description,
            "FieldName": field,
            "DefaultVerticalCRSID": "",
            "DefaultVerticalMeasurementID": "",
            "InterestTypeID": "",
            "VerticalMeasurements": [],
            "ancestry": {
                "parents": [],
                "children": wellbore_ids,
            },
        },
    }


def _wellbore_record(name: str, facility: str, desc: str,
                     well_id: str, target: str, seq: int) -> Dict[str, Any]:
    uid = _uid()
    wb_id = f"{ID_PREFIX}:master-data--Wellbore:{uid}:1"
    return {
        "_wb_id": wb_id,                # transient – stripped before output
        "id": wb_id,
        "kind": WELLBORE_KIND,
        "acl": _acl(),
        "legal": _legal(),
        "data": {
            "Name": name,
            "FacilityName": facility,
            "Description": desc,
            "WellID": well_id,
            "SequenceNumber": seq,
            "TargetFormation": target,
            "DefaultVerticalMeasurementID": "",
            "DefinitiveTrajectoryID": "",
            "DrillingReasons": [],
            "KickOffWellbore": "",
            "PrimaryMaterialID": "",
            "TrajectoryTypeID": "",
            "VerticalMeasurements": [],
            "ancestry": {
                "parents": [well_id],
                "children": [],
            },
        },
    }


def generate() -> None:
    """Build the manifest JSON and write to disk."""
    master_data: List[Dict[str, Any]] = []

    # ── Generate Well + Wellbore records ────────────────────────────
    for wdef in WELLS:
        # First pass: create wellbore records to collect their IDs
        wb_records: List[Dict[str, Any]] = []
        wb_ids: List[str] = []
        placeholder_well_id = f"__WELL__{wdef['name']}"  # replaced below

        for wb in wdef["wellbores"]:
            rec = _wellbore_record(
                name=wb["name"],
                facility=wb["facility"],
                desc=wb["desc"],
                well_id=placeholder_well_id,
                target=wb.get("target", ""),
                seq=wb.get("seq", 1),
            )
            wb_records.append(rec)
            wb_ids.append(rec["_wb_id"])

        # Create well record referencing children
        well_rec = _well_record(
            name=wdef["name"],
            facility=wdef["facility"],
            field=wdef["field"],
            description=wdef["description"],
            wellbore_ids=wb_ids,
        )
        real_well_id = well_rec["_well_id"]

        # Fix wellbore WellID + ancestry with the real Well ID
        for wb_rec in wb_records:
            wb_rec["data"]["WellID"] = real_well_id
            wb_rec["data"]["ancestry"]["parents"] = [real_well_id]
            del wb_rec["_wb_id"]  # strip transient key

        del well_rec["_well_id"]  # strip transient key

        master_data.append(well_rec)
        master_data.extend(wb_records)

    # ── Assemble manifest ───────────────────────────────────────────
    manifest = {
        "kind": "osdu:wks:Manifest:1.0.0",
        "ReferenceData": [],
        "MasterData": master_data,
        "Data": {
            "WorkProduct": None,
            "WorkProductComponents": [],
        },
    }

    outfile = SCRIPT_DIR / "manifest_wells_drogon.json"
    with open(outfile, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    # ── Summary ─────────────────────────────────────────────────────
    n_wells = sum(1 for r in master_data if "Well:" in r["kind"] and "Wellbore" not in r["kind"])
    n_wellbores = sum(1 for r in master_data if "Wellbore:" in r["kind"])
    print(f"Generated {outfile.name}:")
    print(f"  {n_wells} Well records:")
    for r in master_data:
        if "Well:" in r["kind"] and "Wellbore" not in r["kind"]:
            print(f"    {r['data']['Name']:25s}  ({r['data'].get('FieldName','')})")
    print(f"  {n_wellbores} Wellbore records:")
    for r in master_data:
        if "Wellbore:" in r["kind"]:
            print(f"    {r['data']['Name']:25s}  → Well: {r['data']['WellID'][:60]}…")


if __name__ == "__main__":
    generate()
