#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
manifest2records_dg2.py — Split DG2 manifests into individual JSON record
files under demo/drogon_dg2/records/.

DG2 shares only master data (Reservoir, Segments, RefData) and GeoModel
dataspace with DG1. All volume tables, parameters, activity, risks,
documents and BD are DG2-specific (porosity ×0.8).

Usage:
  py demo/drogon_dg2/manifest2records_dg2.py
  py demo/drogon_dg2/manifest2records_dg2.py --outdir demo/drogon_dg2/records
"""

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List

SCRIPT_DIR = Path(__file__).resolve().parent        # demo/drogon_dg2
DG1_DIR    = SCRIPT_DIR.parent / "drogon"            # demo/drogon

# Ingestion order: DG1 shared master/ref data first, then DG2-specific records.
# Tuples of (directory, filename).
MANIFEST_ORDER = [
    # DG1 shared reference & master data (Reservoir, Segments, WP)
    (DG1_DIR, "reftypes_associatedliquid.json"),
    (DG1_DIR, "manifest_masterwp_drogon.json"),
    # DG2-specific volume tables (porosity ×0.8)
    (SCRIPT_DIR, "manifest_wpcparams_dg2.json"),
    (SCRIPT_DIR, "manifest_wpcraw_dg2.json"),
    (SCRIPT_DIR, "manifest_wpcstat_dg2.json"),
    # DG2-specific Production Forecast
    (SCRIPT_DIR, "manifest_wpc_production_dg2.json"),
    # DG2-specific activity (links to DG2 WPCs)
    (SCRIPT_DIR, "manifest_activity_dg2.json"),
    # DG2-specific risks, documents, BD
    (SCRIPT_DIR, "manifest_risk_dg2.json"),
    (SCRIPT_DIR, "manifest_documents_dg2.json"),
    (SCRIPT_DIR, "manifest_bd_dg2.json"),
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
    wp = data.get("WorkProduct")
    if isinstance(wp, dict) and wp.get("data"):
        out.append(wp)
    return out


def split_all(out_dir: Path, namespace: str) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    total = 0
    seq = 0

    for mf_dir, mf_name in MANIFEST_ORDER:
        mf_path = mf_dir / mf_name
        if not mf_path.exists():
            print(f"[skip] {mf_name} not found in {mf_dir}")
            continue

        text = mf_path.read_text(encoding="utf-8")
        obj = json.loads(text)
        records = _flatten_manifest(obj) if isinstance(obj, dict) else obj

        count = 0
        for rec in records:
            if not isinstance(rec, dict) or "data" not in rec:
                continue

            rid = rec.get("id", f"rec_{total}")
            if isinstance(rid, str) and ":" in rid:
                parts = rid.split(":", 1)
                rid_ns = f"{namespace}:{parts[1]}"
                rec["id"] = rid_ns
            else:
                rid_ns = rid

            fname = f"{seq:03d}_{_sanitize(rid_ns)}.json"
            (out_dir / fname).write_text(
                json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            seq += 1
            count += 1

        total += count
        print(f"  {mf_name:50s} → {count} records")

    print(f"\nTotal: {total} record files in {out_dir}")
    return total


def main():
    ap = argparse.ArgumentParser(description="Split DG2 manifests into individual record JSONs")
    ap.add_argument("--outdir", default=str(SCRIPT_DIR / "records"))
    ap.add_argument("--namespace", default="dev")
    args = ap.parse_args()

    split_all(Path(args.outdir), args.namespace)


if __name__ == "__main__":
    main()
