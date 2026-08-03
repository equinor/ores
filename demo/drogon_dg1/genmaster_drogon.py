#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
genmaster_drogon.py - Generate Reservoir + ReservoirSegment MasterData + WorkProduct
for Drogon / Valysar, reading segment names from valysar_volumes.csv.

Output: manifest_masterwp_drogon.json

Usage:
  py demo/drogon_dg1/genmaster_drogon.py
  py demo/drogon_dg1/genmaster_drogon.py --reservoir-name "Drogon" --is-segmented
"""

import argparse
import csv
import json
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Dict, List

SCRIPT_DIR = Path(__file__).resolve().parent  # demo/drogon

# ── Defaults ────────────────────────────────────────────────────────────
DEFAULT_OWNERS  = ["data.default.owners@dev.dataservices.energy"]
DEFAULT_VIEWERS = ["data.office.global.viewers@dev.dataservices.energy"]
DEFAULT_LEGAL   = ["dev-equinor-private-default"]
DEFAULT_COUNTRY = ["NO"]

# ── ID helpers ──────────────────────────────────────────────────────────
def md_id(prefix: str, entity: str, uid: str) -> str:
    return f"{prefix}:master-data--{entity}:{uid}:1"

def wp_id(prefix: str, uid: str) -> str:
    return f"{prefix}:work-product:{uid}:1"

def acl_block() -> Dict:
    return {"owners": DEFAULT_OWNERS, "viewers": DEFAULT_VIEWERS}

def legal_block() -> Dict:
    return {"legaltags": DEFAULT_LEGAL, "otherRelevantDataCountries": DEFAULT_COUNTRY}

from _shared import SEGMENT_NAMES  # noqa: E402
SEGMENT_DESCRIPTIONS = {
    "WestLowland":  "Western lowland fault block of the Valysar formation, Drogon field",
    "CentralSouth": "Central-south structural compartment of the Valysar formation, Drogon field",
    "CentralNorth": "Central-north structural compartment of the Valysar formation, Drogon field",
    "NorthHorst":   "Northern horst block of the Valysar formation, Drogon field - contains gas cap",
    "CentralRamp":  "Central ramp structure of the Valysar formation, Drogon field",
    "CentralHorst": "Central horst block of the Valysar formation, Drogon field - largest oil accumulation",
    "EastLowland":  "Eastern lowland fault block of the Valysar formation, Drogon field",
}


def generate(csvfile: str, outfile: str, id_prefix: str,
             reservoir_name: str, reservoir_description: str,
             is_segmented: bool) -> None:

    with open(csvfile, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ValueError("CSV is empty.")

    # Discover unique segments (preserving order)
    segments: Dict[str, None] = OrderedDict()
    for r in rows:
        seg = r.get("SegmentID", "").strip()
        if seg:
            segments.setdefault(seg, None)

    # Generate IDs
    reservoir_id   = md_id(id_prefix, "Reservoir", str(uuid.uuid4()))
    workproduct_id = wp_id(id_prefix, str(uuid.uuid4()))

    # Build ReservoirSegments
    master_data: List[Dict] = []
    reservoir_children = []

    for seg in segments:
        seg_id = md_id(id_prefix, "ReservoirSegment", str(uuid.uuid4()))
        reservoir_children.append(seg_id)
        display_name = SEGMENT_NAMES.get(seg, seg)
        description  = SEGMENT_DESCRIPTIONS.get(seg, f"Reservoir segment {display_name} of {reservoir_name}")
        master_data.append({
            "id": seg_id,
            "kind": "osdu:wks:master-data--ReservoirSegment:2.0.0",
            "acl": acl_block(),
            "legal": legal_block(),
            "data": {
                "Name": display_name,
                "Description": description,
                "ancestry": {"parents": [reservoir_id], "children": []}
            }
        })

    # Build Reservoir
    reservoir_data: Dict = {
        "Name": reservoir_name,
        "Description": reservoir_description or f"Reservoir {reservoir_name}",
        "ancestry": {"parents": [], "children": reservoir_children},
    }
    # Note: IsSegmented is not in the Reservoir:2.0.0 schema.
    # Segmentation is implied by the presence of ReservoirSegment children.

    master_data.insert(0, {
        "id": reservoir_id,
        "kind": "osdu:wks:master-data--Reservoir:2.0.0",
        "acl": acl_block(),
        "legal": legal_block(),
        "data": reservoir_data,
    })

    # Build WorkProduct
    workproduct = {
        "id": workproduct_id,
        "kind": "osdu:wks:work-product:1.0.0",
        "acl": acl_block(),
        "legal": legal_block(),
        "data": {
            "Name": f"{reservoir_name} Reservoir Study",
            "Description": f"Parent WorkProduct for {reservoir_name} estimated volumes",
            "WorkflowStatus": "Active",
            "ancestry": {"parents": [reservoir_id], "children": []}
        }
    }

    manifest = {
        "kind": "osdu:wks:Manifest:1.0.0",
        "ReferenceData": [],
        "MasterData": master_data,
        "Data": {
            "Datasets": [],
            "WorkProductComponents": [],
            "WorkProducts": [workproduct],
        },
    }

    Path(outfile).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Manifest written → {outfile}")
    print(f"  Reservoir ID   : {reservoir_id}")
    print(f"  WorkProduct ID : {workproduct_id}")
    print(f"  Segments ({len(segments)}): {list(segments.keys())}")


def main():
    ap = argparse.ArgumentParser(description="Generate Drogon MasterData + WorkProduct")
    ap.add_argument("--csvfile", default=str(SCRIPT_DIR / "valysar_volumes.csv"))
    ap.add_argument("--manifest", default=str(SCRIPT_DIR / "manifest_masterwp_drogon.json"))
    ap.add_argument("--id-prefix", default="dev")
    ap.add_argument("--reservoir-name", default="Drogon")
    ap.add_argument("--reservoir-description", default="Drogon field - Valysar formation")
    ap.add_argument("--is-segmented", action="store_true", default=True)
    args = ap.parse_args()

    generate(
        args.csvfile, args.manifest, args.id_prefix,
        args.reservoir_name, args.reservoir_description, args.is_segmented,
    )


if __name__ == "__main__":
    main()
