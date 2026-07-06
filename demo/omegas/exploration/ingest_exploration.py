#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ingest_exploration.py – Ingest the Omega Sør exploration well decision to eqndev.

Pipeline:
  1. Generate exploration-specific manifests (risks, drilling, collections, BD)
  2. Push custom manifest records to OSDU catalog via Storage API

The EPC/RDDMS data (trajectory, horizons, faults) is shared with the parent
Omega Sør dataset – already ingested via demo/omegas/ingest_omegas.py.
This pipeline only handles the exploration BD metadata layer.

The exploration BD reuses:
  - Same CollaborationProject as WPC development BD
  - Same Reservoir/Segment master data
  - Same RDDMS dataspace (maap/omegas)
  - 2 shared Risk records (VolumeUncertainty, DrillingCompletion)

Usage:
  python demo/omegas/exploration/ingest_exploration.py              # full pipeline
  python demo/omegas/exploration/ingest_exploration.py --generate-only  # manifests only
  python demo/omegas/exploration/ingest_exploration.py --dry-run    # no remote changes
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

SCRIPT_DIR = Path(__file__).resolve().parent          # demo/omegas/exploration/
PARENT_DIR = SCRIPT_DIR.parent                        # demo/omegas/
DEMO_DIR = PARENT_DIR.parent                          # demo/
REPO_ROOT = DEMO_DIR.parent                           # ores/

sys.path.insert(0, str(DEMO_DIR))
sys.path.insert(0, str(PARENT_DIR))
sys.path.insert(0, str(SCRIPT_DIR))

from _auth import get_token, load_instance  # noqa: E402
from demo.eqn.omegas.exploration._shared_expl import (  # noqa: E402
    DEFAULT_ACL, DEFAULT_LEGAL, DATASPACE,
    SPATIAL_AREA_WGS84, PROJECT_CRS_ID, CP_ID,
)

try:
    import httpx
except ImportError:
    sys.exit("pip install httpx")


# ═══════════════════════════════════════════════════════════════════════════
# Instance config (same as parent ingest_omegas.py)
# ═══════════════════════════════════════════════════════════════════════════

class InstanceConfig:
    def __init__(self, name: str = "eqndev"):
        inst = load_instance(name)
        self.name = name
        self.host = inst["host"].replace("https://", "").replace("http://", "").rstrip("/")
        self.partition = inst.get("partition") or "opendes"
        self.legal_tag = inst.get("legal_tag") or f"{self.partition}-default-legal-tag"
        owners = inst.get("owners")
        self.owners = owners if isinstance(owners, list) else [owners] if owners else DEFAULT_ACL["owners"]
        viewers = inst.get("viewers")
        self.viewers = viewers if isinstance(viewers, list) else [viewers] if viewers else DEFAULT_ACL["viewers"]
        self.countries = inst.get("countries", ["NO"])
        self.base_storage = f"https://{self.host}/api/storage/v2"

    def headers(self, token: str) -> dict:
        return {
            "Authorization": f"Bearer {token}",
            "data-partition-id": self.partition,
            "Content-Type": "application/json",
        }


# ═══════════════════════════════════════════════════════════════════════════
# Generator scripts (ordered – dependencies first)
# ═══════════════════════════════════════════════════════════════════════════

GENERATOR_SCRIPTS = [
    ("1. Risks (5: 2 shared + 3 exploration-specific)", "gen_risk_exploration.py"),
    ("2. Drilling (trajectory, logs, markers, activities, tubulars, fluids, docs)", "gen_drilling_exploration.py"),
    ("3. Collections (geoscience + main evidence package)", "gen_collection_exploration.py"),
    ("4. BusinessDecision (Exploration well)", "gen_businessdecision_exploration.py"),
]


def run_generators(dry_run: bool = False) -> bool:
    """Run all manifest generator scripts in order."""
    print("\n═══ Generate Exploration OSDU Manifests ═══")
    for label, script in GENERATOR_SCRIPTS:
        script_path = SCRIPT_DIR / script
        if not script_path.exists():
            print(f"  ⚠ Missing: {script}")
            continue
        print(f"\n  ── {label} ──")
        if dry_run:
            print(f"    [dry-run] Would run: {script}")
            continue
        result = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=str(SCRIPT_DIR),
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(f"    ✗ FAILED (rc={result.returncode}):")
            print(f"    {result.stderr[-400:]}")
            return False
        for line in result.stdout.strip().split("\n"):
            print(f"    {line}")
    return True


def push_to_catalog(token: str, cfg: InstanceConfig, dry_run: bool) -> bool:
    """Push all generated manifest records to OSDU Storage API."""
    print(f"\n═══ Push Exploration Records to Catalog ({cfg.name}) ═══")

    manifest_files = sorted(SCRIPT_DIR.glob("manifest_*_exploration.json"))
    if not manifest_files:
        print("  ✗ No manifest files found")
        return False

    all_records: List[Dict[str, Any]] = []
    for mf in manifest_files:
        manifest = json.loads(mf.read_text(encoding="utf-8"))
        for md in manifest.get("MasterData", []):
            all_records.append(md)
        data = manifest.get("Data", {})
        for wpc in data.get("WorkProductComponents", []):
            all_records.append(wpc)
        for wp in data.get("WorkProducts", []):
            all_records.append(wp)

    print(f"  Found {len(all_records)} records from {len(manifest_files)} manifests:")
    for mf in manifest_files:
        print(f"    {mf.name}")

    if dry_run:
        print("\n  [dry-run] Would push records to Storage API:")
        for r in all_records:
            kind_short = r.get("kind", "?").split("--")[-1].split(":")[0] if "--" in r.get("kind", "") else r.get("kind", "?")
            print(f"    {kind_short}: {r.get('id', '?')}")
        return True

    # Push in batches of 20
    batch_size = 20
    total_ok = 0
    for i in range(0, len(all_records), batch_size):
        batch = all_records[i:i + batch_size]
        r = httpx.put(
            f"{cfg.base_storage}/records",
            headers=cfg.headers(token),
            json=batch,
            timeout=60,
        )
        if r.status_code in (200, 201):
            result = r.json()
            count = result.get("recordCount", len(batch))
            total_ok += count
            print(f"  ✓ Batch {i // batch_size + 1}: {count} records ingested")
        else:
            print(f"  ✗ Batch {i // batch_size + 1} failed: {r.status_code}")
            print(f"    {r.text[:300]}")

    print(f"\n  Total: {total_ok}/{len(all_records)} records ingested to catalog")
    return total_ok > 0


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(
        description="Ingest Omega Sør exploration well BD to eqndev")
    ap.add_argument("instance", nargs="?", default="eqndev", help="Target instance")
    ap.add_argument("--generate-only", action="store_true", help="Only generate manifests")
    ap.add_argument("--dry-run", action="store_true", help="No remote changes")
    args = ap.parse_args()

    print(f"╔══════════════════════════════════════════════════════════════╗")
    print(f"║  Omega Sør Exploration Well BD → {args.instance:8s} ingestion  ║")
    print(f"╚══════════════════════════════════════════════════════════════╝")
    print(f"")
    print(f"  Exploration well     : 34/4-19 S")
    print(f"  CollaborationProject : {CP_ID}")
    print(f"  RDDMS dataspace      : {DATASPACE} (shared with WPC BD)")
    print(f"  SharePoint           : https://statoilsrm.sharepoint.com/sites/WCPNO344-19S")

    # Step 1: Generate manifests
    if not run_generators(dry_run=args.dry_run):
        sys.exit("Manifest generation failed")

    if args.generate_only:
        print("\n✓ Manifests generated successfully.")
        print("  Run without --generate-only to push to catalog.")
        return

    # Step 2: Authenticate
    print(f"\n═══ Authenticate ({args.instance}) ═══")
    if args.dry_run:
        token = "DRY_RUN_TOKEN"
        print("  [dry-run] Skipping auth")
    else:
        token = get_token(args.instance, verbose=True)
        if not token:
            sys.exit(f"Failed to authenticate to {args.instance}")

    cfg = InstanceConfig(args.instance)

    # Step 3: Push to catalog
    push_to_catalog(token, cfg, args.dry_run)

    # Summary
    print("\n═══ Summary ═══")
    print(f"  Exploration BD           : dev:master-data--BusinessDecision:OmegaSor-Exploration:1")
    print(f"  Shared risks (tracked)   :")
    print(f"    - dev:master-data--Risk:OmegaSor-VolumeUncertainty:1")
    print(f"    - dev:master-data--Risk:OmegaSor-DrillingCompletion:1")
    print(f"  Exploration-specific risks:")
    print(f"    - dev:master-data--Risk:OmegaSor-GeologicalPlay:1")
    print(f"    - dev:master-data--Risk:OmegaSor-WellControl:1")
    print(f"    - dev:master-data--Risk:OmegaSor-DataAcquisition:1")
    print(f"  Collections              :")
    print(f"    - Drilling evidence    : {len(list(SCRIPT_DIR.glob('manifest_drilling*')))} records")
    print(f"    - Geoscience evidence  : RDDMS-derived (spatial)")
    print(f"    - Main evidence        : All combined")
    print(f"  Related WPC BD           : dev:master-data--BusinessDecision:OmegaSor-WPC:1")
    print(f"\n═══ Done ═══")


if __name__ == "__main__":
    main()
