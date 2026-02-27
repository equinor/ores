#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
manifest2records_drogon.py — Split all Drogon manifests into individual
JSON record files under demo/drogon/records/.

One file per record, named from the record id.

Usage:
  py demo/drogon/manifest2records_drogon.py
  py demo/drogon/manifest2records_drogon.py --outdir demo/drogon/records --namespace dev
"""

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List

SCRIPT_DIR = Path(__file__).resolve().parent  # demo/drogon

# Ingestion order matters: ref data first, then master data, then WPCs, then BD last
MANIFEST_ORDER = [
    "reftypes_associatedliquid.json",      # new ref value
    "manifest_masterwp_drogon.json",        # Reservoir + Segments + WP
    "manifest_wpcraw_drogon.json",          # RAW volumes
    "manifest_wpcstat_drogon.json",         # statistics
    "manifest_wpcparams_drogon.json",       # input parameters (ColumnBasedTable)
    "manifest_activity_drogon.json",        # ActivityTemplate + Activity (merged workflow)
    "manifest_risk_drogon.json",            # Risk
    "manifest_bd_drogon.json",              # BusinessDecision (references everything)
]


def _sanitize(s: str) -> str:
    return re.sub(r'[^A-Za-z0-9._-]+', '_', s)[:200]


def _flatten_manifest(man: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract all records from a Manifest envelope."""
    out: List[Dict[str, Any]] = []
    for grp_key in ("ReferenceData", "MasterData"):
        for r in man.get(grp_key, []):
            if isinstance(r, dict) and "data" in r:
                out.append(r)
    data = man.get("Data", {})
    for grp_key in ("Datasets", "WorkProductComponents", "WorkProducts"):
        for r in data.get(grp_key, []):
            if isinstance(r, dict) and "data" in r:
                out.append(r)
    # single WorkProduct (dict, not list)
    wp = data.get("WorkProduct")
    if isinstance(wp, dict) and wp.get("data"):
        out.append(wp)
    return out


def split_all(manifest_dir: Path, out_dir: Path, namespace: str) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    total = 0
    seq = 0  # global sequence for ordering

    for mf_name in MANIFEST_ORDER:
        mf_path = manifest_dir / mf_name
        if not mf_path.exists():
            print(f"[skip] {mf_name} not found")
            continue

        text = mf_path.read_text(encoding="utf-8")
        obj = json.loads(text)
        records = _flatten_manifest(obj) if isinstance(obj, dict) else obj

        count = 0
        for rec in records:
            if not isinstance(rec, dict) or "data" not in rec:
                continue

            # Replace namespace prefix in id if needed
            rid = rec.get("id", f"rec_{total}")
            if isinstance(rid, str) and ":" in rid:
                parts = rid.split(":", 1)
                rid_ns = f"{namespace}:{parts[1]}"
                rec["id"] = rid_ns
            else:
                rid_ns = rid

            # Keep data.ancestry as-is for Storage API records.
            # The OSDU indexer mirrors data.ancestry → top-level ancestry.*,
            # so both paths appear in the search index (expected behaviour).
            # Top-level "ancestry" requires recordId:numericTimestampVersion
            # which isn't available at generation time, so we leave it in
            # data.ancestry only.

            # Prefix filename with sequence for ingestion order
            fname = f"{seq:03d}_{_sanitize(rid_ns)}.json"
            (out_dir / fname).write_text(
                json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            seq += 1
            count += 1

        total += count
        print(f"  {mf_name:45s} → {count} records")

    print(f"\nTotal: {total} record files in {out_dir}")
    return total


def main():
    ap = argparse.ArgumentParser(description="Split Drogon manifests into individual record JSONs")
    ap.add_argument("--manifest-dir", default=str(SCRIPT_DIR))
    ap.add_argument("--outdir", default=str(SCRIPT_DIR / "records"))
    ap.add_argument("--namespace", default="dev")
    args = ap.parse_args()

    split_all(Path(args.manifest_dir), Path(args.outdir), args.namespace)


if __name__ == "__main__":
    main()
