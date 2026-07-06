#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_volumes_omegas.py - Generate OSDU ReservoirEstimatedVolumes manifest for
Omega Sør using OSDU canonical property kinds and the volume data from the
SSVP presentation (FMU Monte Carlo ensemble, 65 realisations).

Produces two WPCs:
  1. Statistical volumes (P90/P50/P10) - from SSVP slide 9 / 98
  2. In-place summary (ColumnBasedTable) with OSDU property types

Uses canonical OSDU PropertyType codes:
  - Bulk, Net, Pore, HydrocarbonPore, Oil (STOIIP), AssociatedGas
  - UoM: m3, Sm3 (standard cubic metres for STOIIP/gas)

Output: manifest_volumes_omegas.json

Usage:
  python demo/omegas/gen_volumes_omegas.py
"""
from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path
from typing import Any, Dict, List

from demo.eqn.omegas._shared import (
    SCRIPT_DIR, DEFAULT_ACL, DEFAULT_LEGAL, ID_PREFIX,
    ZONE_NAMES, SPATIAL_AREA_WGS84, PROJECT_CRS_ID,
)


def _uid() -> str:
    return str(uuid.uuid4())


def _wpc_id(pfx: str, entity: str, name: str) -> str:
    return f"{pfx}:work-product-component--{entity}:{name}:1"


def _ref_id(pfx: str, entity: str, code: str) -> str:
    return f"{pfx}:reference-data--{entity}:{code}:"


# ── Volume data from SSVP (Monte Carlo ensemble, 65 realisations) ──────
# Source: PPTX slide 9, 98, 99
# Units: MSm³ for oil, 10⁹ Sm³ for gas
VOLUMES_STATISTICAL = {
    "Field": {
        "InPlaceOil_MSm3": {"P90": 15.8, "P50": 19.3, "P10": 22.9},
        "RecoverableOil_MSm3": {"P90": 3.3, "P50": 5.4, "P10": 8.0},
        "RecoveryFactor_pct": {"P90": 16.3, "P50": 28.5, "P10": 43.1},
        "AssociatedGas_GSm3": {"P90": 3.9, "P50": 5.0, "P10": 6.0},
    },
    "Tarbert": {
        "InPlaceOil_MSm3": {"P90": None, "P50": 7.7, "P10": None},
        "AssociatedGas_GSm3": {"P90": None, "P50": 2.0, "P10": None},
    },
    "Rannoch": {
        "InPlaceOil_MSm3": {"P90": None, "P50": 11.6, "P10": None},
        "AssociatedGas_GSm3": {"P90": None, "P50": 3.0, "P10": None},
    },
}


def _build_stat_volume_wpc(pfx: str) -> Dict[str, Any]:
    """Build the statistical REV WPC (P90/P50/P10 summary)."""
    wpc_id = _wpc_id(pfx, "ReservoirEstimatedVolumes", "OmegaSor-SSVP-Statistics")

    # Build ColumnValues for the stat table
    zones = []
    percentiles = []
    stoiip_values = []
    recoverable_values = []
    rf_values = []
    assoc_gas_values = []

    for zone, data in VOLUMES_STATISTICAL.items():
        for pct in ["P90", "P50", "P10"]:
            zones.append(zone)
            percentiles.append(pct)
            stoiip_val = data.get("InPlaceOil_MSm3", {}).get(pct)
            stoiip_values.append(stoiip_val if stoiip_val is not None else None)
            rec_val = data.get("RecoverableOil_MSm3", {}).get(pct)
            recoverable_values.append(rec_val if rec_val is not None else None)
            rf_val = data.get("RecoveryFactor_pct", {}).get(pct)
            rf_values.append(rf_val if rf_val is not None else None)
            gas_val = data.get("AssociatedGas_GSm3", {}).get(pct)
            assoc_gas_values.append(gas_val if gas_val is not None else None)

    key_columns = [
        {"ColumnName": "Zone", "ColumnRole": "Key", "ValueType": "string",
         "KindID": "osdu:wks:master-data--ReservoirSegment:2.0.0"},
        {"ColumnName": "Percentile", "ColumnRole": "Key", "ValueType": "string"},
    ]

    value_columns = [
        {
            "ColumnName": "STOIIP",
            "ColumnRole": "Value",
            "ValueType": "number",
            "PropertyTypeID": _ref_id(pfx, "ReservoirEstimatedVolumePropertyType", "Oil"),
            "UnitOfMeasureID": _ref_id(pfx, "UnitOfMeasure", "MSm3"),
        },
        {
            "ColumnName": "RecoverableOil",
            "ColumnRole": "Value",
            "ValueType": "number",
            "PropertyTypeID": _ref_id(pfx, "ReservoirEstimatedVolumePropertyType", "RecoverableOil"),
            "UnitOfMeasureID": _ref_id(pfx, "UnitOfMeasure", "MSm3"),
        },
        {
            "ColumnName": "RecoveryFactor",
            "ColumnRole": "Value",
            "ValueType": "number",
            "PropertyTypeID": _ref_id(pfx, "ReservoirEstimatedVolumePropertyType", "RecoveryFactor"),
            "UnitOfMeasureID": _ref_id(pfx, "UnitOfMeasure", "percent"),
        },
        {
            "ColumnName": "AssociatedGas",
            "ColumnRole": "Value",
            "ValueType": "number",
            "PropertyTypeID": _ref_id(pfx, "ReservoirEstimatedVolumePropertyType", "AssociatedGas"),
            "UnitOfMeasureID": _ref_id(pfx, "UnitOfMeasure", "GSm3"),
        },
    ]

    column_values = {
        "Zone": zones,
        "Percentile": percentiles,
        "STOIIP": stoiip_values,
        "RecoverableOil": recoverable_values,
        "RecoveryFactor": rf_values,
        "AssociatedGas": assoc_gas_values,
    }

    return {
        "id": wpc_id,
        "kind": "osdu:wks:work-product-component--ReservoirEstimatedVolumes:1.1.0",
        "acl": DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": "Omega Sør Alfa – SSVP Statistical Volumes (P90/P50/P10)",
            "Description": (
                "Aggregated volume statistics from 65-realisation Monte Carlo FMU "
                "ensemble for the Omega Sør Alfa structure. Brent Group: Tarbert Fm "
                "and Rannoch Fm. Based on SSVP model (June 2026). "
                "STOIIP P50 19.3 MSm³, Recoverable P50 5.4 MSm³, RF mean 28.5%."
            ),
            "EstimatedVolumeTypeID": _ref_id(
                pfx, "ReservoirEstimatedVolumeType", "EstimatedInPlaceVolumes"
            ),
            "ParentObjectID": f"{pfx}:master-data--Reservoir:OmegaSorAlfa:1",
            "SpatialArea": SPATIAL_AREA_WGS84,
            "CoordinateReferenceSystemID": PROJECT_CRS_ID,
            "Volumes": {
                "ColumnBasedTableTypeID": _ref_id(pfx, "ColumnBasedTableType", "Statistics"),
                "KeyColumns": key_columns,
                "Columns": value_columns,
                "ColumnValues": column_values,
            },
            "ancestry": {
                "parents": [f"{pfx}:master-data--Reservoir:OmegaSorAlfa:1"],
                "children": [
                    f"{pfx}:master-data--ReservoirSegment:OmegaSor-Tarbert:1",
                    f"{pfx}:master-data--ReservoirSegment:OmegaSor-Rannoch:1",
                ],
            },
        },
    }


def _build_inplace_summary_wpc(pfx: str) -> Dict[str, Any]:
    """Build an in-place volume summary ColumnBasedTable with zone breakdown."""
    wpc_id = _wpc_id(pfx, "ColumnBasedTable", "OmegaSor-SSVP-InPlace")

    # From the RMS volume table and PPTX slide 98
    # Static model values (single best estimate)
    key_columns = [
        {"ColumnName": "Zone", "ColumnRole": "Key", "ValueType": "string",
         "KindID": "osdu:wks:master-data--ReservoirSegment:2.0.0"},
    ]

    value_columns = [
        {
            "ColumnName": "BulkVolume",
            "ColumnRole": "Value",
            "ValueType": "number",
            "PropertyTypeID": _ref_id(pfx, "ReservoirEstimatedVolumePropertyType", "Bulk"),
            "UnitOfMeasureID": _ref_id(pfx, "UnitOfMeasure", "1e6m3"),
        },
        {
            "ColumnName": "NetVolume",
            "ColumnRole": "Value",
            "ValueType": "number",
            "PropertyTypeID": _ref_id(pfx, "ReservoirEstimatedVolumePropertyType", "Net"),
            "UnitOfMeasureID": _ref_id(pfx, "UnitOfMeasure", "1e6m3"),
        },
        {
            "ColumnName": "PoreVolume",
            "ColumnRole": "Value",
            "ValueType": "number",
            "PropertyTypeID": _ref_id(pfx, "ReservoirEstimatedVolumePropertyType", "Pore"),
            "UnitOfMeasureID": _ref_id(pfx, "UnitOfMeasure", "1e6m3"),
        },
        {
            "ColumnName": "HCPV",
            "ColumnRole": "Value",
            "ValueType": "number",
            "PropertyTypeID": _ref_id(pfx, "ReservoirEstimatedVolumePropertyType", "HydrocarbonPore"),
            "UnitOfMeasureID": _ref_id(pfx, "UnitOfMeasure", "1e6m3"),
        },
        {
            "ColumnName": "STOIIP",
            "ColumnRole": "Value",
            "ValueType": "number",
            "PropertyTypeID": _ref_id(pfx, "ReservoirEstimatedVolumePropertyType", "Oil"),
            "UnitOfMeasureID": _ref_id(pfx, "UnitOfMeasure", "MSm3"),
        },
        {
            "ColumnName": "AssociatedGas",
            "ColumnRole": "Value",
            "ValueType": "number",
            "PropertyTypeID": _ref_id(pfx, "ReservoirEstimatedVolumePropertyType", "AssociatedGas"),
            "UnitOfMeasureID": _ref_id(pfx, "UnitOfMeasure", "GSm3"),
        },
    ]

    # Values from static model (slide 98)
    column_values = {
        "Zone": ["Tarbert", "Rannoch", "Total"],
        "BulkVolume": [None, None, None],  # Not disclosed in PPTX
        "NetVolume": [None, None, None],
        "PoreVolume": [None, None, None],
        "HCPV": [None, None, None],
        "STOIIP": [7.2, 10.8, 18.0],
        "AssociatedGas": [2.0, 3.0, 5.0],
    }

    return {
        "id": wpc_id,
        "kind": "osdu:wks:work-product-component--ColumnBasedTable:1.0.0",
        "acl": DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": "Omega Sør Alfa – SSVP In-Place Volumes (static model)",
            "Description": (
                "Static model in-place volumes per zone from the SSVP RMS model. "
                "Brent Group: Tarbert 7.2 MSm³ oil, Rannoch 10.8 MSm³ oil. "
                "Total field STOIIP 18 MSm³, associated gas 5 GSm³."
            ),
            "SpatialArea": SPATIAL_AREA_WGS84,
            "CoordinateReferenceSystemID": PROJECT_CRS_ID,
            "Volumes": {
                "ColumnBasedTableTypeID": _ref_id(pfx, "ColumnBasedTableType", "AdHoc"),
                "KeyColumns": key_columns,
                "Columns": value_columns,
                "ColumnValues": column_values,
            },
        },
    }


def main():
    ap = argparse.ArgumentParser(description="Generate Omega Sør volume manifests")
    ap.add_argument("--manifest", default=str(SCRIPT_DIR / "manifest_volumes_omegas.json"))
    ap.add_argument("--id-prefix", default=ID_PREFIX)
    args = ap.parse_args()

    pfx = args.id_prefix

    stat_wpc = _build_stat_volume_wpc(pfx)
    inplace_wpc = _build_inplace_summary_wpc(pfx)

    manifest = {
        "kind": "osdu:wks:Manifest:1.0.0",
        "ReferenceData": [],
        "MasterData": [],
        "Data": {
            "Datasets": [],
            "WorkProductComponents": [stat_wpc, inplace_wpc],
            "WorkProducts": [],
        },
    }

    out = Path(args.manifest)
    out.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Volumes manifest written → {out}")
    print(f"  Stat REV WPC : {stat_wpc['id']}")
    print(f"  InPlace WPC  : {inplace_wpc['id']}")


if __name__ == "__main__":
    main()
