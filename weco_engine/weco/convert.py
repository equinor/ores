"""
WeCoConvert — CLI for converting well-data between formats.

Usage::

    WeCoConvert input.wells.txt output.las
    WeCoConvert input.las output.csv
    WeCoConvert input.epc output.wells.txt --fmt-in resqml --fmt-out weco

Supported formats: weco, las, csv, gocad_well, resqml, rms_well
"""

import argparse
import sys
import time


def main(argv=None):
    """Entry point for the WeCoConvert CLI."""
    parser = argparse.ArgumentParser(
        prog="WeCoConvert",
        description="Convert well-data files between formats supported by WeCo.",
    )
    parser.add_argument("input", help="Input file path")
    parser.add_argument("output", help="Output file path")
    parser.add_argument(
        "--fmt-in", default=None,
        help="Force input format (auto-detected from extension if omitted). "
             "Choices: weco, las, las_discrete, csv, gocad_well, resqml, rms_well, rddms",
    )
    parser.add_argument(
        "--fmt-out", default=None,
        help="Force output format (auto-detected from extension if omitted). "
             "Choices: weco, las, csv, gocad_well, resqml",
    )
    parser.add_argument(
        "--wells", nargs="*", default=None,
        help="Subset of well names to convert (default: all wells)",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Print progress details",
    )
    args = parser.parse_args(argv)

    from weco.formats import read_wells, write_wells, detect_format

    # Input ----------------------------------------------------------------
    fmt_in = args.fmt_in or detect_format(args.input)
    if fmt_in is None:
        print(f"Error: cannot detect format of '{args.input}'. "
              f"Use --fmt-in to specify.", file=sys.stderr)
        return 1

    if args.verbose:
        print(f"Reading '{args.input}' (format: {fmt_in}) …")

    t0 = time.time()
    try:
        wl = read_wells(args.input, fmt=fmt_in)
    except Exception as exc:
        print(f"Error reading input: {exc}", file=sys.stderr)
        return 1

    nw = len(wl.wells) if hasattr(wl, "wells") else 0
    if args.verbose:
        print(f"  → {nw} well(s) loaded in {time.time() - t0:.2f}s")

    # Optional well subset -------------------------------------------------
    if args.wells and hasattr(wl, "wells"):
        keep = {n.lower() for n in args.wells}
        wl.wells = [w for w in wl.wells if w.name.lower() in keep]
        if args.verbose:
            print(f"  → {len(wl.wells)} well(s) after --wells filter")

    # Output ---------------------------------------------------------------
    fmt_out = args.fmt_out or detect_format(args.output)
    if fmt_out is None:
        print(f"Error: cannot detect output format of '{args.output}'. "
              f"Use --fmt-out to specify.", file=sys.stderr)
        return 1

    if args.verbose:
        print(f"Writing '{args.output}' (format: {fmt_out}) …")

    t1 = time.time()
    try:
        write_wells(wl, args.output, fmt=fmt_out)
    except Exception as exc:
        print(f"Error writing output: {exc}", file=sys.stderr)
        return 1

    if args.verbose:
        print(f"  → done in {time.time() - t1:.2f}s")

    print(f"Converted {nw} well(s): {args.input} ({fmt_in}) → {args.output} ({fmt_out})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
