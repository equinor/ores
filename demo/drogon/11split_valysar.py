#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
11split_valysar.py

Split the raw Valysar uncertainty‑volume table into two OSDU‑canonical CSVs:

  1. **valysar_volumes.csv**  – output Sm³ volume data
     Keys: RealizationID, ZoneID, SegmentID, FaciesID
     Values (OSDU ReservoirEstimatedVolumePropertyType codes):
       BulkOil_m3, PoreOil_m3, HydrocarbonPoreOil_m3, Oil_Sm3,
       AssociatedGas_Sm3, BulkGas_m3, PoreGas_m3, HydrocarbonPoreGas_m3,
       Gas_Sm3, AssociatedLiquid_Sm3, Bulk_m3, Pore_m3

  2. **valysar_parameters.csv** – input scenario parameters
     Keys: RealizationID, ZoneID, SegmentID, FaciesID
     Values:
       OilWaterContact_m   – the OWC depth [m] for this row's segment
       Porosity             – the PHIT expected‑mean for this row's facies

"Totals" aggregate rows are excluded. Only per‑cell (zone × segment × facies)
rows are kept so the key tuple is unique per realization.

Usage (PowerShell):
  py .\demo\py\11split_valysar.py --verbose
  py .\demo\py\11split_valysar.py --dry-run --verbose
"""

import argparse
import csv
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR   = SCRIPT_DIR.parent / "data"
INPUT_CSV  = DATA_DIR / "unc_vol_table_valysar.csv"

# ── OWC column → segment mapping ──────────────────────────────────────────
# The 7 OWC columns in the source CSV map 1‑to‑1 to the 7 Drogon segments.
# Order verified from the Drogon model geometry & OWC value patterns.
OWC_COL_TO_SEGMENT = {
    "OWC 1": "WestLowland",
    "OWC 2": "CentralSouth",
    "OWC 3": "CentralNorth",
    "OWC 4": "NorthHorst",
    "OWC 5": "CentralRamp",
    "OWC 6": "CentralHorst",
    "OWC 7": "EastLowland",
}
SEGMENT_TO_OWC_COL = {v: k for k, v in OWC_COL_TO_SEGMENT.items()}

# ── PHIT column → facies mapping ──────────────────────────────────────────
PHIT_COL_TO_FACIES = {
    "std_valysar. Floodplain. PHIT. expected mean": "Floodplain",
    "std_valysar. Channel. PHIT. expected mean":    "Channel",
    "std_valysar. Crevasse. PHIT. expected mean":   "Crevasse",
}
FACIES_TO_PHIT_COL = {v: k for k, v in PHIT_COL_TO_FACIES.items()}

# ── OSDU‑canonical column renames ─────────────────────────────────────────
# Source CSV column → OSDU canonical output column
VOLUME_RENAME = {
    "BulkOil [m³]":         "BulkOil_m3",
    "PoreOil [m³]":         "PoreOil_m3",
    "HCPVOil [m³]":         "HydrocarbonPoreOil_m3",
    "STOIIP [Sm³]":         "Oil_Sm3",
    "AssociatedGas [Sm³]":  "AssociatedGas_Sm3",
    "BulkGas [m³]":         "BulkGas_m3",
    "PoreGas [m³]":         "PoreGas_m3",
    "HCPVGas [m³]":         "HydrocarbonPoreGas_m3",
    "GIIP [Sm³]":           "Gas_Sm3",
    "AssociatedLiquid [Sm³]": "AssociatedLiquid_Sm3",
    "Bulk [m³]":            "Bulk_m3",
    "Pore [m³]":            "Pore_m3",
}

KEY_COLS_OUT = ["RealizationID", "ZoneID", "SegmentID", "FaciesID"]

# ── helpers ───────────────────────────────────────────────────────────────

def read_source(path: Path) -> List[Dict[str, str]]:
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return list(reader)


def is_totals_row(row: Dict[str, str]) -> bool:
    """Exclude summary/totals rows."""
    seg = (row.get("Segment") or "").strip()
    fac = (row.get("Facies") or "").strip()
    return seg.lower() == "totals" or fac.lower() == "totals"


def build_key(row: Dict[str, str]) -> Dict[str, str]:
    return {
        "RealizationID": (row.get("Proj. real.") or "").strip(),
        "ZoneID":        (row.get("Zone") or "").strip(),
        "SegmentID":     (row.get("Segment") or "").strip(),
        "FaciesID":      (row.get("Facies") or "").strip(),
    }


def build_volumes_row(row: Dict[str, str]) -> Dict[str, str]:
    out = build_key(row)
    for src_col, dst_col in VOLUME_RENAME.items():
        out[dst_col] = (row.get(src_col) or "").strip()
    return out


def build_params_row(row: Dict[str, str]) -> Optional[Dict[str, str]]:
    out = build_key(row)
    segment = out["SegmentID"]
    facies  = out["FaciesID"]

    # OWC for this segment
    owc_col = SEGMENT_TO_OWC_COL.get(segment)
    out["OilWaterContact_m"] = (row.get(owc_col) or "").strip() if owc_col else ""

    # PHIT for this facies
    phit_col = FACIES_TO_PHIT_COL.get(facies)
    out["Porosity"] = (row.get(phit_col) or "").strip() if phit_col else ""

    return out


def write_csv(path: Path, rows: List[Dict[str, str]], fieldnames: List[str],
              dry_run: bool, verbose: bool) -> None:
    if dry_run:
        print(f"[dry-run] Would write {len(rows)} rows to {path.name}")
        if verbose and rows:
            print(f"  Header: {','.join(fieldnames)}")
            print(f"  First:  {','.join(rows[0].get(c,'') for c in fieldnames)}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} rows → {path}")


# ── main ──────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description="Split Valysar uncertainty‑volume table into OSDU‑canonical volumes + parameters CSVs"
    )
    ap.add_argument("--input", default=str(INPUT_CSV),
                    help=f"Source CSV (default: {INPUT_CSV})")
    ap.add_argument("--out-dir", default=str(DATA_DIR),
                    help=f"Output directory (default: {DATA_DIR})")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    verbose = args.verbose
    src_path = Path(args.input)

    if not src_path.exists():
        print(f"Source CSV not found: {src_path}", file=sys.stderr)
        sys.exit(1)

    rows = read_source(src_path)
    if verbose:
        print(f"Read {len(rows)} rows from {src_path.name}")
        # Show columns
        if rows:
            print(f"  Columns: {list(rows[0].keys())}")

    # Filter out Totals rows
    data_rows = [r for r in rows if not is_totals_row(r)]
    dropped = len(rows) - len(data_rows)
    if verbose:
        print(f"Kept {len(data_rows)} data rows ({dropped} totals rows dropped)")

    # ── Build volumes table ─────────────────────────────────────────────
    vol_rows = [build_volumes_row(r) for r in data_rows]
    vol_fields = KEY_COLS_OUT + list(VOLUME_RENAME.values())

    # ── Build parameters table ──────────────────────────────────────────
    param_rows = [build_params_row(r) for r in data_rows]
    param_rows = [r for r in param_rows if r is not None]
    param_fields = KEY_COLS_OUT + ["OilWaterContact_m", "Porosity"]

    # ── Summary ─────────────────────────────────────────────────────────
    out_dir = Path(args.out_dir)

    if verbose:
        real_ids = sorted(set(r["RealizationID"] for r in vol_rows))
        zones    = sorted(set(r["ZoneID"] for r in vol_rows))
        segments = sorted(set(r["SegmentID"] for r in vol_rows))
        facies   = sorted(set(r["FaciesID"] for r in vol_rows))
        print(f"\n  Realizations: {real_ids}")
        print(f"  Zones:        {zones}")
        print(f"  Segments:     {segments}")
        print(f"  Facies:       {facies}")
        print(f"  Volume cols:  {list(VOLUME_RENAME.values())}")
        print(f"  Param cols:   OilWaterContact_m, Porosity")

    # ── Write ───────────────────────────────────────────────────────────
    write_csv(out_dir / "valysar_volumes.csv",    vol_rows,   vol_fields,   args.dry_run, verbose)
    write_csv(out_dir / "valysar_parameters.csv", param_rows, param_fields, args.dry_run, verbose)

    print("\nDone.")


if __name__ == "__main__":
    main()
