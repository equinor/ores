#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generate MasterData (Reservoir + ReservoirSegments) and WorkProduct manifest from CSV.

- ReferenceData: []
- MasterData:
  * Reservoir (2.0.0) with ancestry.children listing all ReservoirSegment IDs
  * ReservoirSegment (2.0.0) with ancestry.parents pointing to Reservoir ID
- Data.WorkProducts:
  * WorkProduct (1.0.0) with ancestry {parents: [Reservoir], children: []}

CLI:
  --csvfile            Input CSV (default: volume_raw.csv)
  --manifest           Output manifest JSON (default: manifest_masterwp.json)
  --id-prefix          dev|srn (default: dev)

Added (OSDU Reservoir metadata; read from CLI):
  --reservoir-name (required)              -> data.Name            (Reservoir 2.0.0 / AbstractGenericReservoirUnit 2.0.0)
  --reservoir-description                  -> data.Description
  --reservoir-type-id                      -> data.ReservoirTypeID (reference-data--ReservoirType)
  --lifecycle-status-id                    -> data.CurrentLifeCycleStatusID
  --first-production-date                  -> data.FirstProductionDate (YYYY-MM-DD)
  --vertical-crs-id                        -> data.VerticalCRSID
  --is-segmented (flag)                    -> data.IsSegmented
  --area                                   -> data.ReservoirUnitArea (float)
  --ohpv                                   -> data.OriginalHydrocarbonPoreVolume (float)
"""
import argparse
import csv
import json
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Dict, List

# Defaults
DEFAULT_OWNERS = ["data.default.owners@dev.dataservices.energy"]
DEFAULT_VIEWERS = ["data.office.global.viewers@dev.dataservices.energy"]
DEFAULT_LEGAL_TAGS = ["dev-equinor-private-default"]
DEFAULT_COUNTRIES = ["NO"]

# ID helpers
def md_id(prefix: str, entity: str, uid: str) -> str:
    return f"{prefix}:master-data--{entity}:{uid}:1"

def wp_id(prefix: str, uid: str) -> str:
    return f"{prefix}:work-product:{uid}:1"

# ACL/legal blocks
def acl_block() -> Dict:
    return {"owners": DEFAULT_OWNERS, "viewers": DEFAULT_VIEWERS}

def legal_block() -> Dict:
    return {"legaltags": DEFAULT_LEGAL_TAGS, "otherRelevantDataCountries": DEFAULT_COUNTRIES}

# Core generator
def generate_master_manifest(
    csvfile: str,
    outfile: str,
    id_prefix: str,
    reservoir_name: str,
    reservoir_description: str = None,
    reservoir_type_id: str = None,
    lifecycle_status_id: str = None,
    first_production_date: str = None,
    vertical_crs_id: str = None,
    is_segmented: bool = False,
    area: float = None,
    ohpv: float = None,
) -> None:
    # Read CSV
    with open(csvfile, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    if not rows:
        raise ValueError("CSV contains no data rows.")

    # Collect unique segments
    segments_ordered: Dict[str, None] = OrderedDict()
    for row in rows:
        seg = str(row["SEGMENT_ID"]).strip()
        if seg:
            segments_ordered.setdefault(seg, None)

    # Generate IDs
    reservoir_id = md_id(id_prefix, "Reservoir", str(uuid.uuid4()))
    workproduct_id = wp_id(id_prefix, str(uuid.uuid4()))

    # Build MasterData
    master_data: List[Dict] = []
    reservoir_children = []

    for seg in segments_ordered.keys():
        seg_id = md_id(id_prefix, "ReservoirSegment", str(uuid.uuid4()))
        reservoir_children.append(seg_id)
        master_data.append({
            "id": seg_id,
            "kind": "osdu:wks:master-data--ReservoirSegment:2.0.0",
            "acl": acl_block(),
            "legal": legal_block(),
            "data": {
                "Name": seg,
                "Description": f"Reservoir segment ({seg})",
                "ancestry": {"parents": [reservoir_id], "children": []}
            }
        })

    # Reservoir data from CLI (aligned to OSDU schema 2.0.0)
    reservoir_data = {
        "Name": reservoir_name,
        "Description": reservoir_description or f"Reservoir {reservoir_name}",
        "ancestry": {"parents": [], "children": reservoir_children}
    }
    # Optional schema-aligned enrichments
    if reservoir_type_id:
        reservoir_data["ReservoirTypeID"] = reservoir_type_id
    if lifecycle_status_id:
        reservoir_data["CurrentLifeCycleStatusID"] = lifecycle_status_id
    if first_production_date:
        reservoir_data["FirstProductionDate"] = first_production_date
    if vertical_crs_id:
        reservoir_data["VerticalCRSID"] = vertical_crs_id
    if is_segmented:
        reservoir_data["IsSegmented"] = True
    if area is not None:
        reservoir_data["ReservoirUnitArea"] = float(area)
    if ohpv is not None:
        reservoir_data["OriginalHydrocarbonPoreVolume"] = float(ohpv)

    master_data.insert(0, {
        "id": reservoir_id,
        "kind": "osdu:wks:master-data--Reservoir:2.0.0",
        "acl": acl_block(),
        "legal": legal_block(),
        "data": reservoir_data
    })

    # WorkProduct (unchanged)
    workproduct = {
        "id": workproduct_id,
        "kind": "osdu:wks:work-product:1.0.0",
        "acl": acl_block(),
        "legal": legal_block(),
        "data": {
            "Name": "Reservoir Management Study",
            "Description": "Parent WorkProduct for estimated volumes",
            "WorkflowStatus": "Active",
            "ancestry": {"parents": [reservoir_id], "children": []}
        }
    }

    # Manifest
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
    print(f"Manifest written to {outfile}")
    print(f"Reservoir ID: {reservoir_id}\nWorkProduct ID: {workproduct_id}\nSegments: {len(segments_ordered)}")

# CLI
def main():
    ap = argparse.ArgumentParser(description="Generate MasterData + WorkProduct manifest from CSV")
    ap.add_argument("--csvfile", default="volume_raw.csv", help="Input CSV file")
    ap.add_argument("--manifest", default="manifest_masterwp.json", help="Output manifest JSON file")
    ap.add_argument("--id-prefix", choices=["dev", "srn"], default="dev", help="ID prefix for records")

    # New: Reservoir metadata params (OSDU-aligned)
    ap.add_argument("--reservoir-name", required=True, help="Reservoir Name (OSDU data.Name)")
    ap.add_argument("--reservoir-description", help="Reservoir Description")
    ap.add_argument("--reservoir-type-id", help="Reference ID for ReservoirType (e.g., dev:reference-data--ReservoirType:Conventional:1)")
    ap.add_argument("--lifecycle-status-id", help="Reference ID for CurrentLifeCycleStatus (e.g., dev:reference-data--ReservoirLifeCycleStatus:Active:1)")
    ap.add_argument("--first-production-date", help="First production date YYYY-MM-DD")
    ap.add_argument("--vertical-crs-id", help="Reference ID for Vertical CRS (e.g., dev:reference-data--CoordinateReferenceSystem:EPSG-5714:1)")
    ap.add_argument("--is-segmented", action="store_true", help="Flag to set data.IsSegmented=true")
    ap.add_argument("--area", type=float, help="ReservoirUnitArea (numeric)")
    ap.add_argument("--ohpv", type=float, help="OriginalHydrocarbonPoreVolume (numeric)")

    args = ap.parse_args()
    generate_master_manifest(
        args.csvfile,
        args.manifest,
        args.id_prefix,
        reservoir_name=args.reservoir_name,
        reservoir_description=args.reservoir_description,
        reservoir_type_id=args.reservoir_type_id,
        lifecycle_status_id=args.lifecycle_status_id,
        first_production_date=args.first_production_date,
        vertical_crs_id=args.vertical_crs_id,
        is_segmented=args.is_segmented,
        area=args.area,
        ohpv=args.ohpv,
    )

if __name__ == "__main__":
    main()

