
# -*- coding: utf-8 -*-
"""
Generate OSDU-compliant RAW manifest for ReservoirEstimatedVolumes (ColumnBasedTable)
from a CSV file. Implements key synonyms & new key columns:
  - Real/REALISATION/Realisation  -> Realisation (int)
  - SEGMENT_ID/SegmentID/SEGMENT/REGION/Region/'Region index' -> SegmentID (str)
  - Zone/ZONE -> Zone (str)
  - Column/Phase/PHASE/Phases -> Phases (str)
  - Facies/FACIES -> Facies (optional str)
Numeric columns are mapped to OSDU canonical property names.
"""

import argparse
import csv
import json
import uuid
import os

# ------------------------ Helpers ------------------------
def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def ref_id(prefix, entity, name):
    return f"{prefix}:reference-data--{entity}:{name}"

def wpc_id(prefix, entity, name):
    return f"{prefix}:work-product-component--{entity}:{name}:1"

def get_first(row: dict, candidates):
    # case-insensitive fetch with fallback; returns '' if not found
    for c in candidates:
        for k in row.keys():
            if k.strip().lower() == c.strip().lower():
                return row.get(k, "")
    return ""

# ------------------------ Main ------------------------
def main():
    parser = argparse.ArgumentParser(description="Generate OSDU ReservoirEstimatedVolumes RAW manifest")
    parser.add_argument("--csvfile", default="volumes_drogon_combined.csv")
    parser.add_argument("--manifest", default="manifest_wpcraw.json")
    parser.add_argument("--masterwp", default="manifest_masterwp.json")
    parser.add_argument("--reftypes", default="reftypes_revpropertytypes.json")
    parser.add_argument("--id-prefix", default="dev")
    parser.add_argument("--uuid", action="store_true", default=True)
    args = parser.parse_args()

    # Load masterwp and reftypes
    masterwp = load_json(args.masterwp)
    reftypes = load_json(args.reftypes)

    # Extract Reservoir and WorkProduct IDs & ACL/Legal (from your existing Master WP)
    reservoir_id = ""
    workproduct_id = ""
    acl = {"owners": [], "viewers": []}
    legal = {"legaltags": [], "otherRelevantDataCountries": []}

    for md in masterwp.get("MasterData", []):
        if md.get("kind", "").startswith("osdu:wks:master-data--Reservoir:"):
            reservoir_id = md["id"]
            acl = md["acl"]
            legal = md["legal"]

    for wp in masterwp.get("Data", {}).get("WorkProducts", []):
        workproduct_id = wp.get("id", "")

    # Build property type map from reftypes: Name -> id
    property_type_map = {}
    for ref in reftypes.get("ReferenceData", []):
        if "ReservoirEstimatedVolumePropertyType" in ref.get("kind", ""):
            name = ref["data"]["Name"]
            property_type_map[name] = ref["id"]

    # Canonical mapping: CSV header -> OSDU canonical property name (data.Volumes.Columns[].ColumnName)
    # Case-insensitive lookup when reading values.
    CSV_TO_PROPERTY = {
        "Bulk": "Bulk",
        "Net": "Net",
        "Pore": "Pore",                          # keep as-is if you use "Pore" in your reftypes
        "Hcpv": "HydrocarbonPore",               # synonym commonly used
        "Stoiip": "Oil",
        "Assoc.Gas": "AssociatedGas",
        "Giip": "Gas",
    }

    # Read CSV
    if not os.path.exists(args.csvfile):
        raise FileNotFoundError(f"CSV file not found: {args.csvfile}")

    with open(args.csvfile, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    if not rows:
        raise ValueError("CSV contains no data rows.")

    # Prepare ColumnValues with canonical names
    column_values = {
        "Realisation": [],
        "Zone": [],
        "SegmentID": [],
        "Phase": [],
        # "Facies": []  # will add conditionally if any non-empty appears
    }

    # For numeric properties
    for _, prop_name in CSV_TO_PROPERTY.items():
        column_values[prop_name] = []

    saw_facies = False

    # Populate ColumnValues
    for row in rows:
        # ----- Keys -----
        # Realisation (int) from Real/REALISATION/Realisation
        real_raw = get_first(row, ["Real", "REALISATION", "Realisation"])
        try:
            column_values["Realisation"].append(int(float(real_raw)))
        except (TypeError, ValueError):
            column_values["Realisation"].append(0)

        # Zone
        zone = get_first(row, ["Zone", "ZONE"])
        column_values["Zone"].append(zone)

        # SegmentID from SEGMENT_ID/SegmentID/SEGMENT/REGION/Region/'Region index'
        segment = get_first(row, ["SEGMENT_ID", "SegmentID", "SEGMENT", "REGION", "Region", "Region index"])
        column_values["SegmentID"].append(segment)

        # Phases from Column/Phase/PHASE/Phases
        phase = get_first(row, ["Column", "Phase"])
        column_values["Phase"].append(phase)

        # Facies (optional)
        facies = get_first(row, ["Facies", "FACIES"])
        if facies != "":
            if "Facies" not in column_values:
                column_values["Facies"] = []
            column_values["Facies"].append(facies)
            saw_facies = True
        else:
            if "Facies" in column_values:
                column_values["Facies"].append("")  # align lengths

        # ----- Values (numeric) using canonical property names -----
        for csv_col, prop_name in CSV_TO_PROPERTY.items():
            val_raw = get_first(row, [csv_col])
            if val_raw is not None and str(val_raw).strip() != "":
                try:
                    column_values[prop_name].append(float(val_raw))
                except ValueError:
                    column_values[prop_name].append(float("nan"))
            else:
                column_values[prop_name].append(float("nan"))

    # Remove empty value columns (keep key columns even if empty)
    for key in list(column_values.keys()):
        if key in ("Realisation", "Zone", "SegmentID", "Phases", "Facies"):
            continue
        # if all values are NaN or empty, drop the value column
        vals = column_values[key]
        if all((v != v) for v in vals):  # NaN check: NaN != NaN
            del column_values[key]

    # ----- Column Declarations -----
    key_columns = [
        {"ColumnName": "Realisation", "ColumnRole": "Key", "ValueType": "integer"},
        {"ColumnName": "SegmentID", "ColumnRole": "Key", "ValueType": "string", "KindID": "osdu:wks:master-data--ReservoirSegment:2.0.0"},
        {"ColumnName": "Zone", "ColumnRole": "Key", "ValueType": "string"},
        {"ColumnName": "Phases", "ColumnRole": "Key", "ValueType": "string"},
    ]
    if saw_facies:
        key_columns.append({"ColumnName": "Facies", "ColumnRole": "Key", "ValueType": "string"})

    columns = []
    for _, prop_name in CSV_TO_PROPERTY.items():
        if prop_name in column_values:
            columns.append({
                "ColumnName": prop_name,
                "ColumnRole": "Value",
                "ValueType": "number",
                "PropertyTypeID": property_type_map.get(
                    prop_name,
                    ref_id(args.id_prefix, "ReservoirEstimatedVolumePropertyType", prop_name)
                ),
                "UnitOfMeasureID": ref_id(args.id_prefix, "UnitOfMeasure", "m3"),
            })

    # Generate WPC ID
    wpc_id_value = str(uuid.uuid4()) if args.uuid else "ReservoirEstimatedVolumes"
    wpc_record_id = wpc_id(args.id_prefix, "ReservoirEstimatedVolumes", wpc_id_value)

    # Ancestry from masterwp: parents = Reservoir, children = ReservoirSegments (if provided in masterwp)
    ancestry = {"parents": [], "children": []}
    if reservoir_id:
        ancestry["parents"].append(reservoir_id)
    for md in masterwp.get("MasterData", []):
        if md.get("kind", "").startswith("osdu:wks:master-data--ReservoirSegment:"):
            ancestry["children"].append(md["id"])

    # Build manifest
    manifest = {
        "kind": "osdu:wks:Manifest:1.0.0",
        "ReferenceData": [],
        "MasterData": [],
        "Data": {
            "Datasets": [],
            "WorkProductComponents": [
                {
                    "id": wpc_record_id,
                    "kind": "osdu:wks:work-product-component--ReservoirEstimatedVolumes:1.1.0",
                    "acl": acl,
                    "legal": legal,
                    "data": {
                        "Name": "Reservoir Estimated Volumes — RAW",
                        "Description": "Generated from CSV with keys: Realisation, SegmentID, Zone, Phases" + (", Facies" if saw_facies else ""),
                        "EstimatedVolumeTypeID": ref_id(args.id_prefix, "ReservoirEstimatedVolumeType", "EstimatedInPlaceVolumes"),
                        "ParentObjectID": reservoir_id,
                        "ParentWorkProductID": workproduct_id,
                        "ancestry": ancestry,
                        "Volumes": {
                            "ColumnBasedTableTypeID": ref_id(args.id_prefix, "ColumnBasedTableType", "AdHoc"),
                            "KeyColumns": key_columns,
                            "Columns": columns,
                            "ColumnValues": column_values
                        }
                    }
                }
            ],
            "WorkProducts": []
        }
    }

    with open(args.manifest, "w", encoding="utf-8") as mf:
        json.dump(manifest, mf, indent=2)
    print(f"Manifest generated successfully: {args.manifest}\nRows: {len(rows)}, ValueColumns: {len(columns)}")

if __name__ == "__main__":
    main()
