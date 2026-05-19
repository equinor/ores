#!/usr/bin/env python3
"""
§5.3 — gopy_extract.py (Python 3 version).

Extract well data from GOCAD objects (.wl, .vs, .ts) into WeCo format.
This replaces the legacy Python 2 ``gopy_extract.py``.

Usage::

    python gopy_extract.py input.wl -o output_wells.txt
    python gopy_extract.py *.wl --format csv -o wells/
"""

import argparse
import sys
import os
from pathlib import Path


def extract_gocad_to_weco(input_paths, output_path, fmt="weco"):
    """
    Extract GOCAD well files to WeCo format.

    Parameters
    ----------
    input_paths : list of str
    output_path : str
    fmt : str
        Output format: 'weco', 'csv', 'las'
    """
    from weco.formats.gocad_well import read_gocad_well
    from weco.data import WellList

    all_wells = []
    for path in input_paths:
        try:
            wells = read_gocad_well(path)
            all_wells.extend(wells)
            print(f"  Read {len(wells)} well(s) from {path}")
        except Exception as e:
            print(f"  WARNING: Failed to read {path}: {e}", file=sys.stderr)

    if not all_wells:
        print("No wells extracted.", file=sys.stderr)
        return 1

    print(f"Total: {len(all_wells)} wells")

    if fmt == "weco":
        wl = WellList.__new__(WellList)
        wl.wells = all_wells
        wl.write(output_path)
        print(f"Written to {output_path}")
    elif fmt == "csv":
        os.makedirs(output_path, exist_ok=True)
        for well in all_wells:
            safe_name = well.name.replace("/", "_").replace("\\", "_")
            csv_path = os.path.join(output_path, f"{safe_name}.csv")
            with open(csv_path, "w") as f:
                keys = list(well.data.keys())
                f.write(",".join(keys) + "\n")
                for i in range(well.size):
                    row = ",".join(str(well.data[k][i]) if i < len(well.data[k]) else ""
                                   for k in keys)
                    f.write(row + "\n")
            print(f"  → {csv_path}")
    elif fmt == "las":
        from weco.export import _write_las_logs
        os.makedirs(output_path, exist_ok=True)
        for well in all_wells:
            safe_name = well.name.replace("/", "_").replace("\\", "_")
            las_path = os.path.join(output_path, f"{safe_name}.las")
            _write_las_logs(well, las_path)
            print(f"  → {las_path}")

    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Extract GOCAD well files to WeCo format (Python 3)",
    )
    parser.add_argument("inputs", nargs="+", help="Input GOCAD .wl files")
    parser.add_argument("-o", "--output", required=True, help="Output path")
    parser.add_argument("--format", choices=["weco", "csv", "las"], default="weco",
                        help="Output format (default: weco)")
    args = parser.parse_args()
    sys.exit(extract_gocad_to_weco(args.inputs, args.output, args.format))


if __name__ == "__main__":
    main()
