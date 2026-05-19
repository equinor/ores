#!/usr/bin/env python3
"""
benchmark_performance.py — Performance benchmark for WeCo engine (§1.1, §1.2)
===============================================================================

Measures wall-clock time and correlation quality for:
- **Sakoe-Chiba band-width** constraint  (item 1.1)
- **Beam-width** wavefront pruning       (item 1.2)

Usage::

    python bin/benchmark_performance.py                       # all datasets
    python bin/benchmark_performance.py --dataset data_set_2  # single dataset
    python bin/benchmark_performance.py --csv results.csv     # export CSV
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from pathlib import Path
from typing import List, Optional

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ── Datasets ──────────────────────────────────────────────────────────────
DEFAULT_DATASETS = [
    "data_set_1.1",
    "data_set_1.2",
    "data_set_1.3",
    "data_set_1.4",
    "data_set_1.5",
    "data_set_2",
    "data_set_3",
    "data_set_4",
]

BAND_WIDTHS = [0, 5, 10, 20, 50, 100]
BEAM_WIDTHS = [0, 3, 5, 10, 20]


def find_well_file(data_dir: Path) -> Optional[Path]:
    """Locate the well-list file inside a dataset directory."""
    for name in ("wells.txt", "well_list.txt", "test_wells.txt"):
        p = data_dir / name
        if p.exists():
            return p
    # fallback: first .txt that contains 'well' in name
    for p in sorted(data_dir.glob("*.txt")):
        if "well" in p.name.lower():
            return p
    return None


def run_benchmark(
    data_dir: Path,
    band_width: int,
    beam_width: int,
    max_cor: int = 1,
) -> dict:
    """Run WeCo on *data_dir* with given constraints and return timing info."""
    from weco.ext import ProjectExt

    well_file = find_well_file(data_dir)
    if well_file is None:
        return {"error": f"No well file in {data_dir}"}

    project = ProjectExt()
    project.set_options_ext(
        var_data=str(data_dir / "data") if (data_dir / "data").is_dir() else str(data_dir),
        cost_function="composite",
        max_cor=max_cor,
        band_width=band_width,
        beam_width=beam_width,
    )

    t0 = time.perf_counter()
    try:
        project.run(str(well_file))
    except Exception as exc:
        return {"error": str(exc)}
    elapsed = time.perf_counter() - t0

    # Extract result quality
    try:
        rf = project.get_res_file()
        best_cost = rf.cor(0).cost if rf.nbr_cor() > 0 else float("nan")
        n_wells = rf.nbr_well() if hasattr(rf, "nbr_well") else -1
    except Exception:
        best_cost = float("nan")
        n_wells = -1

    return {
        "dataset": data_dir.name,
        "band_width": band_width,
        "beam_width": beam_width,
        "time_s": round(elapsed, 4),
        "best_cost": round(best_cost, 6) if best_cost == best_cost else "NaN",
        "n_wells": n_wells,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="WeCo performance benchmarks")
    parser.add_argument("--dataset", help="Single dataset directory name")
    parser.add_argument("--csv", help="Write results to CSV file")
    parser.add_argument(
        "--data-root",
        default=str(Path(__file__).resolve().parent.parent / "data"),
        help="Root data directory (default: <project>/data)",
    )
    args = parser.parse_args()

    data_root = Path(args.data_root)
    if args.dataset:
        datasets = [args.dataset]
    else:
        datasets = [d for d in DEFAULT_DATASETS if (data_root / d).is_dir()]

    if not datasets:
        print("No datasets found.", file=sys.stderr)
        sys.exit(1)

    rows: List[dict] = []

    # ── Band-width sweep (item 1.1) ──────────────────────────────────────
    print("=== Sakoe-Chiba band-width sweep ===")
    print(f"{'Dataset':<20} {'BW':>4} {'Time(s)':>9} {'Cost':>12}")
    print("-" * 50)
    for ds in datasets:
        for bw in BAND_WIDTHS:
            row = run_benchmark(data_root / ds, band_width=bw, beam_width=0)
            rows.append(row)
            if "error" in row:
                print(f"{ds:<20} {bw:>4} {'ERROR':>9} {row['error']}")
            else:
                print(f"{ds:<20} {bw:>4} {row['time_s']:>9.4f} {row['best_cost']:>12}")

    # ── Beam-width sweep (item 1.2) ──────────────────────────────────────
    print("\n=== Beam-width (wavefront) sweep ===")
    print(f"{'Dataset':<20} {'BeW':>4} {'Time(s)':>9} {'Cost':>12}")
    print("-" * 50)
    for ds in datasets:
        for bew in BEAM_WIDTHS:
            row = run_benchmark(data_root / ds, band_width=0, beam_width=bew)
            rows.append(row)
            if "error" in row:
                print(f"{ds:<20} {bew:>4} {'ERROR':>9} {row['error']}")
            else:
                print(f"{ds:<20} {bew:>4} {row['time_s']:>9.4f} {row['best_cost']:>12}")

    # ── Export CSV ────────────────────────────────────────────────────────
    if args.csv and rows:
        keys = ["dataset", "band_width", "beam_width", "time_s", "best_cost", "n_wells"]
        with open(args.csv, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        print(f"\nResults written to {args.csv}")


if __name__ == "__main__":
    main()
