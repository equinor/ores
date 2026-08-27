#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_well_production_dg2.py - Generate per-well production WPC records
(ColumnBasedTable) for the Drogon DG2 field development dataset.

Adds individual well vectors (WOPR, WWPR, WWCT, WBHP, WOPT) per
producing/injecting wellbore. This enables queries like:
  - "Which well has the highest water cut?"
  - "Show production profile for A-2 vs A-3"
  - "Identify wells with poor performance due to connectivity"

Wells:
  Producers: 55/33-A-1, 55/33-A-2, 55/33-A-3, 55/33-A-4
  Injectors: 55/33-A-5, 55/33-A-6

Source: OPM Flow drogon tutorial (realization-0) + synthetic prediction.

Output:
  manifest_well_production_dg2.json

Usage:
  python demo/drogon_dg2/gen_well_production_dg2.py
"""
from __future__ import annotations

import json
import math
import random
import uuid
from pathlib import Path
from typing import Any, Dict, List

SCRIPT_DIR = Path(__file__).resolve().parent

_NS = uuid.UUID("a0000000-d509-4e00-8000-000000000002")

DATASPACE_NAME = "maap/drogon_dg"

DEFAULT_ACL = {
    "owners": ["data.default.owners@dev.dataservices.energy"],
    "viewers": ["data.default.viewers@dev.dataservices.energy"],
}
DEFAULT_LEGAL = {
    "legaltags": ["opendes-private-usa-default"],
    "otherRelevantDataCountries": ["NO"],
}

# ── Well definitions ─────────────────────────────────────────────────────
# Each well has a segment assignment (for connectivity analysis)
PRODUCERS = [
    {"name": "55/33-A-1", "short": "A1", "segment": "CentralHorst",
     "start": "2018-01-01", "target_zone": "Valysar"},
    {"name": "55/33-A-2", "short": "A2", "segment": "CentralHorst",
     "start": "2018-04-01", "target_zone": "Valysar"},
    {"name": "55/33-A-3", "short": "A3", "segment": "EastLowland",
     "start": "2018-07-01", "target_zone": "Valysar"},
    {"name": "55/33-A-4", "short": "A4", "segment": "WestLowland",
     "start": "2018-10-01", "target_zone": "Valysar"},
]

INJECTORS = [
    {"name": "55/33-A-5", "short": "A5", "segment": "CentralHorst",
     "start": "2018-06-01", "target_zone": "Valysar"},
    {"name": "55/33-A-6", "short": "A6", "segment": "EastLowland",
     "start": "2018-12-01", "target_zone": "Valysar"},
]

# ── Date range (same as field-level production) ──────────────────────────
def _monthly_dates(start: str, end: str) -> List[str]:
    """Generate first-of-month dates from start to end (inclusive)."""
    from datetime import date
    y0, m0, _ = (int(x) for x in start.split("-"))
    y1, m1, _ = (int(x) for x in end.split("-"))
    dates = []
    y, m = y0, m0
    while (y, m) <= (y1, m1):
        dates.append(f"{y:04d}-{m:02d}-01")
        m += 1
        if m > 12:
            m = 1
            y += 1
    return dates

ALL_DATES = _monthly_dates("2018-01-01", "2025-01-01")  # 85 months
HISTORY_END = "2020-07-01"  # index 30


def _well_uuid(well_short: str) -> str:
    return str(uuid.uuid5(_NS, f"dg2-wellprod-{well_short}"))


def _generate_producer_profile(well: Dict, all_dates: List[str]) -> Dict[str, List]:
    """Generate realistic production profile for a producer.

    Models:
    - Ramp-up period (2 months)
    - Plateau (rate limited at LRAT)
    - Decline with rising water cut
    - Segment-dependent connectivity (EastLowland gets earlier water breakthrough)
    """
    random.seed(hash(well["short"]))  # Reproducible per well

    start_idx = all_dates.index(well["start"])
    segment = well["segment"]

    # Segment-specific behaviour (connectivity controls production)
    if segment == "CentralHorst":
        plateau_rate = 3500.0  # Good connectivity, high rate
        wcut_onset_months = 18  # Late water breakthrough
        wcut_slope = 0.015  # Slow rise
        decline_rate = 0.005  # Gentle decline
    elif segment == "EastLowland":
        plateau_rate = 2200.0  # Poorer connectivity (fault-bounded)
        wcut_onset_months = 10  # Early water breakthrough (fault conduit)
        wcut_slope = 0.025  # Fast water cut rise
        decline_rate = 0.012  # Steeper decline
    else:  # WestLowland
        plateau_rate = 2800.0  # Moderate
        wcut_onset_months = 14
        wcut_slope = 0.018
        decline_rate = 0.008

    wopr, wwpr, wwct, wbhp, wopt = [], [], [], [], []
    cum_oil = 0.0

    for i, dt in enumerate(all_dates):
        if i < start_idx:
            wopr.append(0.0)
            wwpr.append(0.0)
            wwct.append(0.0)
            wbhp.append(0.0)
            wopt.append(0.0)
            continue

        months_online = i - start_idx
        # Ramp-up
        if months_online < 2:
            qo = plateau_rate * (months_online + 1) / 3.0
            wc = 0.0
        else:
            # Decline from plateau
            prod_months = months_online - 2
            qo = plateau_rate * math.exp(-decline_rate * prod_months)
            # Water cut onset
            if prod_months > wcut_onset_months:
                wc_months = prod_months - wcut_onset_months
                wc = min(0.92, wcut_slope * wc_months)
            else:
                wc = 0.0

        # Add some noise
        noise = 1.0 + random.uniform(-0.03, 0.03)
        qo = max(0.0, qo * noise)
        qw = qo * wc / max(1.0 - wc, 0.08)  # water rate from water cut

        # BHP declines with depletion
        bhp = 280.0 - 2.0 * months_online + random.uniform(-3, 3)
        bhp = max(150.0, bhp)

        cum_oil += qo * 30.44  # ~days per month

        wopr.append(round(qo, 1))
        wwpr.append(round(qw, 1))
        wwct.append(round(wc, 4))
        wbhp.append(round(bhp, 1))
        wopt.append(round(cum_oil, 0))

    return {
        "WOPR": wopr, "WWPR": wwpr, "WWCT": wwct,
        "WBHP": wbhp, "WOPT": wopt,
    }


def _generate_injector_profile(well: Dict, all_dates: List[str]) -> Dict[str, List]:
    """Generate injection profile for a water injector."""
    random.seed(hash(well["short"]) + 999)

    start_idx = all_dates.index(well["start"])
    segment = well["segment"]

    target_rate = 6500.0 if segment == "CentralHorst" else 5500.0

    wwir, wbhp = [], []
    for i, dt in enumerate(all_dates):
        if i < start_idx:
            wwir.append(0.0)
            wbhp.append(0.0)
            continue

        months_online = i - start_idx
        # Ramp to target
        if months_online < 2:
            qi = target_rate * (months_online + 1) / 3.0
        else:
            qi = target_rate + random.uniform(-200, 200)

        bhp = 350.0 + 1.5 * months_online + random.uniform(-5, 5)
        bhp = min(500.0, bhp)

        wwir.append(round(qi, 1))
        wbhp.append(round(bhp, 1))

    return {"WWIR": wwir, "WBHP": wbhp}


def _make_wpc_record(well: Dict, vectors: Dict[str, List], is_injector: bool) -> Dict[str, Any]:
    """Build a WPC ColumnBasedTable record for one well."""
    uid = _well_uuid(well["short"])
    well_type = "injector" if is_injector else "producer"

    columns = []
    col_values = [{"StringColumn": ALL_DATES}]  # Date key column

    if is_injector:
        col_defs = [
            ("WWIR", "number", "Sm3/d", "Well water injection rate"),
            ("WBHP", "number", "barsa", "Well bottom-hole pressure"),
        ]
    else:
        col_defs = [
            ("WOPR", "number", "Sm3/d", "Well oil production rate"),
            ("WWPR", "number", "Sm3/d", "Well water production rate"),
            ("WWCT", "number", "Euc", "Well water cut"),
            ("WBHP", "number", "barsa", "Well bottom-hole pressure"),
            ("WOPT", "number", "Sm3", "Well oil production total (cumulative)"),
        ]

    for cname, vtype, uom, desc in col_defs:
        columns.append({
            "ColumnName": cname,
            "ValueType": vtype,
            "UnitOfMeasureID": f"dev:reference-data--UnitOfMeasure:{uom}:",
            "Description": desc,
        })
        col_values.append({"NumberColumn": vectors[cname]})

    # Phase column
    phase_col = []
    hist_end_idx = ALL_DATES.index(HISTORY_END)
    for i in range(len(ALL_DATES)):
        phase_col.append("History" if i <= hist_end_idx else "Prediction")
    columns.append({
        "ColumnName": "Phase",
        "ValueType": "string",
        "Description": "History or Prediction",
    })
    col_values.append({"StringColumn": phase_col})

    # Segment column (constant per well - for connectivity queries)
    columns.append({
        "ColumnName": "Segment",
        "ValueType": "string",
        "Description": "Reservoir segment (fault compartment)",
    })
    col_values.append({"StringColumn": [well["segment"]] * len(ALL_DATES)})

    description = (
        f"Per-well production profile for {well['name']} ({well_type}) in "
        f"Drogon DG2. Segment: {well['segment']}, Target zone: {well['target_zone']}. "
        f"Start: {well['start']}. "
    )
    if not is_injector:
        peak_rate = max(vectors["WOPR"])
        final_wcut = vectors["WWCT"][-1]
        cum_oil = vectors["WOPT"][-1]
        description += (
            f"Peak oil rate: {peak_rate:.0f} Sm³/d. "
            f"Final water cut: {final_wcut:.2f}. "
            f"Cumulative oil: {cum_oil/1e6:.2f} MSm³."
        )

    return {
        "id": f"dev:work-product-component--ColumnBasedTable:Drogon-DG2-WellProd-{well['short']}:1",
        "kind": "osdu:wks:work-product-component--ColumnBasedTable:1.4.0",
        "acl": DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": f"Drogon DG2 – Well Production: {well['name']} ({well_type})",
            "Description": description,
            "WellboreID": f"dev:master-data--Wellbore:{well['name'].replace('/', '-')}:",
            "ReservoirSegment": well["segment"],
            "TargetZone": well["target_zone"],
            "WellType": well_type,
            "StartDate": well["start"],
            "ColumnBasedTableTypeID": "dev:reference-data--ColumnBasedTableType:WellProduction:",
            "DDMSDatasets": [
                f"eml:///dataspace('{DATASPACE_NAME}')/resqml22.TableRepresentation('Drogon-DG2-WellProd-{well['short']}')"
            ],
            "Table": {
                "ColumnBasedTableTypeID": "dev:reference-data--ColumnBasedTableType:WellProduction:",
                "KeyColumns": [
                    {
                        "ColumnName": "Date",
                        "ValueType": "string",
                        "Description": "Reporting date (ISO 8601)",
                    }
                ],
                "Columns": columns,
                "ColumnValues": col_values,
            },
        },
    }


def main():
    records: List[Dict[str, Any]] = []

    # Generate producer records
    for well in PRODUCERS:
        vectors = _generate_producer_profile(well, ALL_DATES)
        records.append(_make_wpc_record(well, vectors, is_injector=False))

    # Generate injector records
    for well in INJECTORS:
        vectors = _generate_injector_profile(well, ALL_DATES)
        records.append(_make_wpc_record(well, vectors, is_injector=True))

    # Build manifest
    manifest = {
        "kind": "osdu:wks:Manifest:1.0.0",
        "ReferenceData": [],
        "MasterData": [],
        "Data": {
            "Datasets": [],
            "WorkProductComponents": records,
        },
    }

    out_path = SCRIPT_DIR / "manifest_well_production_dg2.json"
    with open(out_path, "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"Generated {len(records)} well production records:")
    for r in records:
        well_type = r["data"]["WellType"]
        name = r["data"]["Name"]
        print(f"  {well_type:8s}  {name}")
    print(f"\nOutput: {out_path}")


if __name__ == "__main__":
    main()
