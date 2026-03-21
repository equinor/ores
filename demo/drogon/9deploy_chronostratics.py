#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
9deploy_chronostratics.py

Split the ChronoStratigraphy reference-data manifest into individual record
files in demo/strat/chronostrat_records/, then optionally ingest via osducli.

Records are ingested in dependency order:
  1. reference-data--ChronoStratigraphicScheme (scheme)
  2. reference-data--ChronoStratigraphy (roots first, children later)
  3. work-product-component--StratigraphicColumnRankInterpretation (WPC)

Usage (PowerShell, from repo root):
  py .\demo\py\9deploy_chronostratics.py --verbose
  py .\demo\py\9deploy_chronostratics.py --ingest --verbose
  py .\demo\py\9deploy_chronostratics.py --filter-scheme ICS2017 --ingest --verbose
  py .\demo\py\9deploy_chronostratics.py --dry-run --verbose

Manual ingestion after writing record files:
  Get-ChildItem ".\demo\strat\chronostrat_records" -Filter *.json |
    ForEach-Object { py -m osducli storage add -p $_.FullName }
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

# ── defaults ──────────────────────────────────────────────────────────────── #

SCRIPT_DIR  = Path(__file__).resolve().parent           # demo/py
STRAT_DIR   = SCRIPT_DIR.parent / "strat"               # demo/strat
RECORDS_DIR = STRAT_DIR / "chronostrat_records"          # demo/strat/chronostrat_records
MANIFEST    = STRAT_DIR / "manifest_chronostratics.json"

# ── helpers ───────────────────────────────────────────────────────────────── #

def id_to_filename(record_id: str) -> str:
    """Convert an OSDU record id to a safe filename."""
    name = record_id.replace(":", "_").replace("/", "_")
    name = re.sub(r"_+", "_", name)
    if not name.endswith(".json"):
        name += ".json"
    return name


def _replace_namespace(obj: Any, namespace: str) -> Any:
    """Recursively replace {{NAMESPACE}} in all string values."""
    if isinstance(obj, str):
        return obj.replace("{{NAMESPACE}}", namespace)
    if isinstance(obj, list):
        return [_replace_namespace(x, namespace) for x in obj]
    if isinstance(obj, dict):
        return {k: _replace_namespace(v, namespace) for k, v in obj.items()}
    return obj


def extract_records(manifest: dict) -> List[dict]:
    """Pull all records from a Manifest envelope."""
    records: List[dict] = []
    for key in ("ReferenceData", "MasterData"):
        for rec in manifest.get(key) or []:
            if isinstance(rec, dict) and rec.get("id"):
                records.append(rec)
    data = manifest.get("Data") or {}
    for key in ("WorkProductComponents", "WorkProducts", "Datasets"):
        for rec in data.get(key) or []:
            if isinstance(rec, dict) and rec.get("id"):
                records.append(rec)
    return records


def _chrono_depth(rec: dict) -> int:
    """Return the depth of a chrono record's Code (dot-segment count).
    Roots have depth 0, children have progressively higher depth."""
    code = rec.get("data", {}).get("Code", "")
    return code.count(".") if code else 999


def _sort_key(rec: dict) -> Tuple[int, int, str]:
    """Sort key for dependency-ordered ingestion.
    Order: scheme → chrono (roots first by depth) → WPC
    """
    kind = rec.get("kind", "")
    rid = rec.get("id", "")
    if "ChronoStratigraphicScheme" in kind:
        return (0, 0, rid)
    if "ChronoStratigraphy" in kind:
        return (1, _chrono_depth(rec), rid)
    if "ColumnRankInterpretation" in kind or "WorkProduct" in kind.lower():
        return (3, 0, rid)
    return (2, 0, rid)


def write_records(records: List[dict], out_dir: Path, verbose: bool) -> List[Path]:
    """Write each record to its own JSON file, return list of paths."""
    written: List[Path] = []
    for rec in records:
        rid = rec.get("id", "unknown")
        fname = id_to_filename(rid)
        fpath = out_dir / fname
        fpath.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        written.append(fpath)
        if verbose:
            print(f"  wrote {fname}")
    return written


def ingest_file(path: Path, verbose: bool, dry_run: bool) -> bool:
    """Ingest a single record file via osducli storage add. Returns True on success."""
    cmd = [sys.executable, "-m", "osducli", "storage", "add", "-p", str(path)]
    if verbose:
        print(f"  $ {' '.join(cmd)}")
    if dry_run:
        print(f"  [dry-run] would ingest {path.name}")
        return True
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode == 0:
            if verbose and result.stdout.strip():
                print(f"    {result.stdout.strip()[:200]}")
            return True
        else:
            err = (result.stderr or result.stdout or "").strip()[:300]
            print(f"  ERROR ingesting {path.name}: {err}", file=sys.stderr)
            return False
    except subprocess.TimeoutExpired:
        print(f"  TIMEOUT ingesting {path.name}", file=sys.stderr)
        return False
    except FileNotFoundError:
        print("  ERROR: osducli not found. Install with: pip install osdu-cli", file=sys.stderr)
        return False


# ── main ──────────────────────────────────────────────────────────────────── #

def main():
    ap = argparse.ArgumentParser(
        description="Deploy ChronoStratigraphy records: split manifest → record files → ingest via osducli"
    )
    ap.add_argument("--manifest", default=str(MANIFEST),
                    help=f"Path to chrono manifest (default: {MANIFEST})")
    ap.add_argument("--namespace", default="dev",
                    help="Data partition / namespace to replace {{NAMESPACE}} placeholders (default: dev)")
    ap.add_argument("--filter-scheme", default="",
                    help="Only include records from this scheme (e.g. ICS2017, GTS2020). Default: all schemes")
    ap.add_argument("--out-dir", default=str(RECORDS_DIR),
                    help=f"Output directory for record files (default: {RECORDS_DIR})")
    ap.add_argument("--records-only", action="store_true",
                    help="Write record files only, do not ingest")
    ap.add_argument("--ingest", action="store_true",
                    help="Ingest records via osducli storage add (one call per file)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Show what would be ingested without actually calling osducli")
    ap.add_argument("--no-clean", action="store_true",
                    help="Do not clear the output directory before writing")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    verbose = args.verbose
    out_dir = Path(args.out_dir)

    # ── 1. Load manifest ─────────────────────────────────────────────────── #
    mpath = Path(args.manifest)
    if not mpath.exists():
        print(f"Manifest not found: {mpath}", file=sys.stderr)
        sys.exit(1)

    manifest = json.loads(mpath.read_text(encoding="utf-8"))
    all_records = extract_records(manifest)
    if verbose:
        print(f"Loaded {len(all_records)} records from {mpath.name}")

    # ── 2. Replace {{NAMESPACE}} ─────────────────────────────────────────── #
    all_records = [_replace_namespace(r, args.namespace) for r in all_records]

    # ── 3. Deduplicate by id (last wins) ─────────────────────────────────── #
    by_id: Dict[str, dict] = {}
    for rec in all_records:
        by_id[rec["id"]] = rec
    deduped = list(by_id.values())

    if verbose and len(deduped) != len(all_records):
        print(f"Deduplicated: {len(all_records)} → {len(deduped)} unique records")

    # ── 4. Optional scheme filter ─────────────────────────────────────────── #
    filter_scheme = (args.filter_scheme or "").strip()
    if filter_scheme:
        before = len(deduped)
        deduped = [
            r for r in deduped
            if filter_scheme in r.get("data", {}).get("ChronoStratigraphicSchemeID", "")
            or "ChronoStratigraphicScheme" in r.get("kind", "")    # keep scheme records
            or "ColumnRankInterpretation" in r.get("kind", "")       # keep WPC
        ]
        # Rebuild WPC's ChronoStratigraphySet to only reference kept IDs
        kept_chrono_ids = set(
            r["id"] for r in deduped
            if "ChronoStratigraphy:" in r.get("kind", "")
        )
        for r in deduped:
            d = r.get("data", {})
            if "ChronoStratigraphySet" in d:
                d["ChronoStratigraphySet"] = [
                    cid for cid in d["ChronoStratigraphySet"]
                    if cid in kept_chrono_ids
                ]
        if verbose:
            print(f"Filtered to scheme '{filter_scheme}': {before} -> {len(deduped)}")

    # ── 5. Per-scheme summary ─────────────────────────────────────────────── #
    from collections import Counter
    scheme_counts: Counter = Counter()
    kind_counts: Counter = Counter()
    for rec in deduped:
        kind = rec.get("kind", "?")
        short = kind.split("--")[-1] if "--" in kind else kind
        kind_counts[short] += 1
        sid = rec.get("data", {}).get("ChronoStratigraphicSchemeID", "")
        if "ChronoStratigraphicScheme:" in sid:
            scheme = sid.split("ChronoStratigraphicScheme:")[1].rstrip(":")
            scheme_counts[scheme] += 1

    print(f"\nTotal unique records: {len(deduped)}")
    for k, n in sorted(kind_counts.items()):
        print(f"  {k}: {n}")
    if scheme_counts:
        print("By scheme:")
        for s, n in scheme_counts.most_common():
            print(f"  {s}: {n}")

    # ── 6. Write record files ─────────────────────────────────────────────── #
    if not args.no_clean and out_dir.exists():
        removed = 0
        for f in out_dir.glob("*.json"):
            f.unlink()
            removed += 1
        if verbose:
            print(f"Cleaned {removed} old .json files from {out_dir.name}/")

    out_dir.mkdir(parents=True, exist_ok=True)

    # Sort by dependency: scheme → chrono roots → chrono children → WPC
    sorted_records = sorted(deduped, key=_sort_key)

    written = write_records(sorted_records, out_dir, verbose)
    print(f"Wrote {len(written)} record files to {out_dir}")

    if args.records_only:
        print("Done (--records-only)")
        return

    # ── 7. Ingest ─────────────────────────────────────────────────────────── #
    if not args.ingest:
        print("Record files written. Use --ingest to upload via osducli, or ingest manually (PowerShell):")
        print(f'  Get-ChildItem "{out_dir}" -Filter *.json | ForEach-Object {{ py -m osducli storage add -p $_.FullName }}')
        return

    print(f"\nIngesting {len(sorted_records)} records (one per osducli call)...")
    ok = 0
    fail = 0
    for i, rec in enumerate(sorted_records, 1):
        fname = id_to_filename(rec["id"])
        fpath = out_dir / fname
        if verbose:
            print(f"[{i}/{len(sorted_records)}] {fname}")
        if ingest_file(fpath, verbose, args.dry_run):
            ok += 1
        else:
            fail += 1
    print(f"\nIngest complete: {ok} OK, {fail} failed")


if __name__ == "__main__":
    main()
