#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
8deploy_stratcolumn.py

Split the StratigraphicColumn manifest into individual record files
in demo/strat/stratcolumn_records/, then ingest them via the osducli.

Steps:
  1. Read manifest_stratcolumn.json (+ optionally manifest_chronostratics.json)
  2. Clear and re-populate stratcolumn_records/ with one JSON file per record
  3. Ingest via:  py -m osducli storage add -p <file> --batch <n>

Usage (PowerShell, from repo root):
  py .\demo\py\8deploy_stratcolumn.py --verbose
  py .\demo\py\8deploy_stratcolumn.py --include-chrono --ingest --batch 20 --verbose
  py .\demo\py\8deploy_stratcolumn.py --records-only          # just write files, no ingest
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

# ── defaults ──────────────────────────────────────────────────────────────── #

SCRIPT_DIR  = Path(__file__).resolve().parent           # demo/py
STRAT_DIR   = SCRIPT_DIR.parent / "strat"               # demo/strat
RECORDS_DIR = STRAT_DIR / "stratcolumn_records"          # demo/strat/stratcolumn_records
MANIFEST_SC = STRAT_DIR / "manifest_stratcolumn.json"
MANIFEST_CH = STRAT_DIR / "manifest_chronostratics.json"

# ── helpers ───────────────────────────────────────────────────────────────── #

def id_to_filename(record_id: str) -> str:
    """
    Convert an OSDU record id to a safe filename.
    Example: 'dev:reference-data--StratigraphicRoleType:Chronostratigraphic:'
           → 'dev_reference-data--StratigraphicRoleType_Chronostratigraphic_.json'
    """
    name = record_id.replace(":", "_").replace("/", "_")
    # collapse multiple underscores
    name = re.sub(r"_+", "_", name)
    if not name.endswith(".json"):
        name += ".json"
    return name


def extract_records(manifest: dict) -> List[dict]:
    """Pull all records from a Manifest envelope (ReferenceData + WPCs + MasterData)."""
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


def _replace_namespace(obj: Any, namespace: str) -> Any:
    """Recursively replace {{NAMESPACE}} in all string values."""
    if isinstance(obj, str):
        return obj.replace("{{NAMESPACE}}", namespace)
    if isinstance(obj, list):
        return [_replace_namespace(x, namespace) for x in obj]
    if isinstance(obj, dict):
        return {k: _replace_namespace(v, namespace) for k, v in obj.items()}
    return obj


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
        description="Deploy StratigraphicColumn records: split manifest → record files → ingest via osducli"
    )
    ap.add_argument("--manifest", default=str(MANIFEST_SC),
                    help=f"Path to stratcolumn manifest (default: {MANIFEST_SC})")
    ap.add_argument("--include-chrono", action="store_true",
                    help="Also include records from manifest_chronostratics.json")
    ap.add_argument("--chrono-manifest", default=str(MANIFEST_CH),
                    help=f"Path to chrono manifest (default: {MANIFEST_CH})")
    ap.add_argument("--namespace", default="dev",
                    help="Data partition / namespace to replace {{NAMESPACE}} placeholders (default: dev)")
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

    # ── 1. Load manifests ────────────────────────────────────────────────── #
    all_records: List[dict] = []

    sc_path = Path(args.manifest)
    if not sc_path.exists():
        print(f"Manifest not found: {sc_path}", file=sys.stderr)
        sys.exit(1)
    sc_manifest = json.loads(sc_path.read_text(encoding="utf-8"))
    sc_records = extract_records(sc_manifest)
    all_records.extend(sc_records)
    if verbose:
        print(f"Loaded {len(sc_records)} records from {sc_path.name}")

    if args.include_chrono:
        ch_path = Path(args.chrono_manifest)
        if ch_path.exists():
            ch_manifest = json.loads(ch_path.read_text(encoding="utf-8"))
            ch_records = extract_records(ch_manifest)
            all_records.extend(ch_records)
            if verbose:
                print(f"Loaded {len(ch_records)} records from {ch_path.name}")
        else:
            print(f"Warning: chrono manifest not found: {ch_path}", file=sys.stderr)

    # Replace {{NAMESPACE}} placeholders
    all_records = [_replace_namespace(r, args.namespace) for r in all_records]

    # Deduplicate by id (last wins)
    by_id: Dict[str, dict] = {}
    for rec in all_records:
        by_id[rec["id"]] = rec
    all_records = list(by_id.values())

    if verbose:
        # Summarize by kind
        kinds: Dict[str, int] = {}
        for rec in all_records:
            k = rec.get("kind", "unknown")
            # Shorten kind for display
            short = k.split("--")[-1] if "--" in k else k
            kinds[short] = kinds.get(short, 0) + 1
        print(f"Total unique records: {len(all_records)}")
        for k, n in sorted(kinds.items()):
            print(f"  {k}: {n}")

    # ── 2. Write record files ────────────────────────────────────────────── #
    if not args.no_clean and out_dir.exists():
        # Remove old .json files but keep non-json (like READMEs)
        removed = 0
        for f in out_dir.glob("*.json"):
            f.unlink()
            removed += 1
        if verbose:
            print(f"Cleaned {removed} old .json files from {out_dir.name}/")

    out_dir.mkdir(parents=True, exist_ok=True)
    written = write_records(all_records, out_dir, verbose)
    print(f"Wrote {len(written)} record files to {out_dir}")

    if args.records_only:
        print("Done (--records-only)")
        return

    # ── 3. Ingest ────────────────────────────────────────────────────────── #
    if not args.ingest:
        print("Record files written. Use --ingest to upload via osducli, or ingest manually (PowerShell):")
        print(f'  Get-ChildItem "{out_dir}" -Filter *.json | ForEach-Object {{ py -m osducli storage add -p $_.FullName }}')
        return

    # Ingest individual files in dependency order:
    # ref-data → units → horizons → ranks → columns
    def sort_key(rec: dict) -> int:
        k = rec.get("kind", "")
        if "reference-data--" in k:
            return 0
        if "UnitInterpretation" in k:
            return 1
        if "HorizonInterpretation" in k:
            return 2
        if "ColumnRankInterpretation" in k:
            return 3
        if "StratigraphicColumn:" in k:
            return 4
        return 5
    sorted_records = sorted(all_records, key=sort_key)

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
