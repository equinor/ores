#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
split_valysar.py  –  Drogon / Valysar uncertainty‑volume table splitter

Split the raw Valysar uncertainty‑volume CSV into two OSDU‑canonical CSVs:

  1. **valysar_volumes.csv**   – output Sm³ volume data (per cell)
  2. **valysar_parameters.csv** – input scenario parameters (wide: one column per parameter)

Column names follow OSDU canonical conventions:
  - Volume property names  = ReservoirEstimatedVolumePropertyType codes
      (Bulk, Pore, HydrocarbonPore, Oil, Gas, AssociatedGas …)
  - Unit (Sm³ / m³) is NOT in the column name — it is defined per property
    in the OSDU reference data (UnitOfMeasureID).
  - Key columns use OSDU entity names: RealizationID, ZoneID, SegmentID, FaciesID.

"Totals" aggregate rows are excluded.

Usage (PowerShell, from repo root):
  py .\demo\drogon\split_valysar.py --verbose
  py .\demo\drogon\split_valysar.py --dry-run --verbose
"""

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

SCRIPT_DIR = Path(__file__).resolve().parent          # demo/drogon
DEMO_DIR   = SCRIPT_DIR.parent                        # demo
DATA_DIR   = DEMO_DIR / "data"                        # demo/data
INPUT_CSV  = DATA_DIR / "unc_vol_table_valysar.csv"

# ═══════════════════════════════════════════════════════════════════════════
#  MAPPING DICTIONARIES
# ═══════════════════════════════════════════════════════════════════════════

# ── Key column renames ────────────────────────────────────────────────────
#     Source CSV header  →  OSDU canonical key name
KEY_RENAME = {
    "Proj. real.": "Realisation",
    "Zone":        "Zone",
    "Segment":     "SegmentID",
    "Facies":      "Facies",
}

# ── Volume column renames ────────────────────────────────────────────────
#     Source CSV header             →  OSDU canonical property name
#     (unit is NOT in name; sm3 is defined by ReservoirEstimatedVolumePropertyType)
VOLUME_RENAME = {
    "BulkOil [m³]":            "BulkOil",
    "PoreOil [m³]":            "PoreOil",
    "HCPVOil [m³]":            "HydrocarbonPoreOil",
    "STOIIP [Sm³]":            "Oil",              # Stock‑Tank Oil Initially In Place
    "AssociatedGas [Sm³]":     "AssociatedGas",
    "BulkGas [m³]":            "BulkGas",
    "PoreGas [m³]":            "PoreGas",
    "HCPVGas [m³]":            "HydrocarbonPoreGas",
    "GIIP [Sm³]":              "Gas",              # Gas Initially In Place
    "AssociatedLiquid [Sm³]":  "AssociatedLiquid",
    "Bulk [m³]":               "Bulk",             # Total bulk
    "Pore [m³]":               "Pore",             # Total pore
}

# ── Parameter column renames (wide: one column per parameter) ────────────
#     Source CSV header  →  OSDU canonical parameter name
#     OWC columns carry per‑segment oil‑water‑contact depth.
#     PHIT columns carry per‑facies porosity scenario means.
PARAM_RENAME = {
    "OWC 1": "OilWaterContact_WestLowland",
    "OWC 2": "OilWaterContact_CentralSouth",
    "OWC 3": "OilWaterContact_CentralNorth",
    "OWC 4": "OilWaterContact_NorthHorst",
    "OWC 5": "OilWaterContact_CentralRamp",
    "OWC 6": "OilWaterContact_CentralHorst",
    "OWC 7": "OilWaterContact_EastLowland",
    "std_valysar. Floodplain. PHIT. expected mean": "Porosity_Floodplain",
    "std_valysar. Channel. PHIT. expected mean":    "Porosity_Channel",
    "std_valysar. Crevasse. PHIT. expected mean":   "Porosity_Crevasse",
}

# ── OWC column → Segment mapping (for reference / future use) ───────────
OWC_SEGMENT_MAP = {
    "OWC 1": "WestLowland",
    "OWC 2": "CentralSouth",
    "OWC 3": "CentralNorth",
    "OWC 4": "NorthHorst",
    "OWC 5": "CentralRamp",
    "OWC 6": "CentralHorst",
    "OWC 7": "EastLowland",
}

# ── PHIT column → Facies mapping (for reference / future use) ────────────
PHIT_FACIES_MAP = {
    "std_valysar. Floodplain. PHIT. expected mean": "Floodplain",
    "std_valysar. Channel. PHIT. expected mean":    "Channel",
    "std_valysar. Crevasse. PHIT. expected mean":   "Crevasse",
}

# ── OSDU Reference Data IDs (matching dev OSDU instance) ────────────────
#    Mapping from canonical volume name → OSDU ReservoirEstimatedVolumePropertyType ID
VOLUME_PROPERTY_TYPE_IDS = {
    "Bulk":              "dev:reference-data--ReservoirEstimatedVolumePropertyType:Bulk:",
    "Pore":              "dev:reference-data--ReservoirEstimatedVolumePropertyType:Pore:",
    "HydrocarbonPore":   "dev:reference-data--ReservoirEstimatedVolumePropertyType:HydrocarbonPore:",
    "Oil":               "dev:reference-data--ReservoirEstimatedVolumePropertyType:Oil:",
    "Gas":               "dev:reference-data--ReservoirEstimatedVolumePropertyType:Gas:",
    "AssociatedGas":     "dev:reference-data--ReservoirEstimatedVolumePropertyType:AssociatedGas:",
    # Phase‑qualified names inherit from parent type
    "BulkOil":           "dev:reference-data--ReservoirEstimatedVolumePropertyType:Bulk:",
    "PoreOil":           "dev:reference-data--ReservoirEstimatedVolumePropertyType:Pore:",
    "HydrocarbonPoreOil":"dev:reference-data--ReservoirEstimatedVolumePropertyType:HydrocarbonPore:",
    "BulkGas":           "dev:reference-data--ReservoirEstimatedVolumePropertyType:Bulk:",
    "PoreGas":           "dev:reference-data--ReservoirEstimatedVolumePropertyType:Pore:",
    "HydrocarbonPoreGas":"dev:reference-data--ReservoirEstimatedVolumePropertyType:HydrocarbonPore:",
    "AssociatedLiquid":  "dev:reference-data--ReservoirEstimatedVolumePropertyType:AssociatedLiquid:",
}

# ── Segment IDs for MasterData ReservoirSegment references ──────────────
DROGON_SEGMENTS = [
    "WestLowland", "CentralSouth", "CentralNorth",
    "NorthHorst", "CentralRamp", "CentralHorst", "EastLowland",
]

# ═══════════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def read_source(path: Path) -> List[Dict[str, str]]:
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return list(reader)


def is_totals_row(row: Dict[str, str]) -> bool:
    seg = (row.get("Segment") or "").strip()
    fac = (row.get("Facies") or "").strip()
    return seg.lower() == "totals" or fac.lower() == "totals"


def rename_keys(row: Dict[str, str], mapping: Dict[str, str]) -> Dict[str, str]:
    """Pick columns from row using mapping {src_col: dst_col}."""
    out = {}
    for src, dst in mapping.items():
        out[dst] = (row.get(src) or "").strip()
    return out


def write_csv(path: Path, rows: List[Dict[str, str]], fieldnames: List[str],
              dry_run: bool, verbose: bool) -> None:
    if dry_run:
        print(f"[dry-run] Would write {len(rows)} rows to {path.name}")
        if verbose and rows:
            print(f"  Header: {','.join(fieldnames)}")
            print(f"  Row[0]: {','.join(rows[0].get(c,'') for c in fieldnames)}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} rows → {path}")


# ═══════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(
        description="Split Valysar uncertainty‑volume table into OSDU‑canonical volumes + parameters CSVs"
    )
    ap.add_argument("--input", default=str(INPUT_CSV),
                    help=f"Source CSV (default: {INPUT_CSV})")
    ap.add_argument("--out-dir", default=str(SCRIPT_DIR),
                    help=f"Output directory for CSVs (default: {SCRIPT_DIR})")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    verbose  = args.verbose
    src_path = Path(args.input)

    if not src_path.exists():
        print(f"Source CSV not found: {src_path}", file=sys.stderr)
        sys.exit(1)

    rows = read_source(src_path)
    if verbose:
        print(f"Read {len(rows)} rows from {src_path.name}")
        if rows:
            print(f"  Columns: {list(rows[0].keys())}")

    # Filter out Totals rows
    data_rows = [r for r in rows if not is_totals_row(r)]
    dropped = len(rows) - len(data_rows)
    if verbose:
        print(f"Kept {len(data_rows)} data rows ({dropped} totals rows dropped)")

    # ── Build volumes table ─────────────────────────────────────────────
    vol_rows = []
    for r in data_rows:
        out = rename_keys(r, KEY_RENAME)
        out.update(rename_keys(r, VOLUME_RENAME))
        vol_rows.append(out)

    vol_fields = list(KEY_RENAME.values()) + list(VOLUME_RENAME.values())

    # ── Build parameters table (wide: one column per parameter) ─────────
    param_rows = []
    for r in data_rows:
        out = rename_keys(r, KEY_RENAME)
        out.update(rename_keys(r, PARAM_RENAME))
        param_rows.append(out)

    param_fields = list(KEY_RENAME.values()) + list(PARAM_RENAME.values())

    # ── Summary ─────────────────────────────────────────────────────────
    out_dir = Path(args.out_dir)

    if verbose:
        real_ids = sorted(set(r["Realisation"] for r in vol_rows))
        zones    = sorted(set(r["Zone"] for r in vol_rows))
        segments = sorted(set(r["SegmentID"] for r in vol_rows))
        facies   = sorted(set(r["Facies"] for r in vol_rows))
        print(f"\n  Realizations: {real_ids}")
        print(f"  Zones:        {zones}")
        print(f"  Segments:     {segments}")
        print(f"  Facies:       {facies}")
        print(f"\n  Volume columns ({len(VOLUME_RENAME)}):")
        for src, dst in VOLUME_RENAME.items():
            print(f"    {src:30s} → {dst}")
        print(f"\n  Parameter columns ({len(PARAM_RENAME)}):")
        for src, dst in PARAM_RENAME.items():
            print(f"    {src:55s} → {dst}")

    # ── Write ───────────────────────────────────────────────────────────
    write_csv(out_dir / "valysar_volumes.csv",    vol_rows,   vol_fields,   args.dry_run, verbose)
    write_csv(out_dir / "valysar_parameters.csv", param_rows, param_fields, args.dry_run, verbose)

    if verbose:
        print(f"\nMapping dicts available for downstream scripts:")
        print(f"  VOLUME_RENAME          ({len(VOLUME_RENAME)} entries)")
        print(f"  PARAM_RENAME           ({len(PARAM_RENAME)} entries)")
        print(f"  OWC_SEGMENT_MAP        ({len(OWC_SEGMENT_MAP)} entries)")
        print(f"  PHIT_FACIES_MAP        ({len(PHIT_FACIES_MAP)} entries)")
        print(f"  VOLUME_PROPERTY_TYPE_IDS ({len(VOLUME_PROPERTY_TYPE_IDS)} entries)")

    print("\nDone.")


if __name__ == "__main__":
    main()
