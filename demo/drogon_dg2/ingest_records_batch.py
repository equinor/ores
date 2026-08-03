#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ingest_records_batch.py - Batch ingestion of DG2 records via Storage API.

Identical logic to demo/drogon_dg1/ingest_records_batch.py but reads from
the drogon_dg2/records/ directory by default.

Usage:
  py demo/drogon_dg2/ingest_records_batch.py
  py demo/drogon_dg2/ingest_records_batch.py --instance eqndev --dry-run
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

import httpx

SCRIPT_DIR  = Path(__file__).resolve().parent
RECORDS_DIR = SCRIPT_DIR / "records"
REPO_ROOT   = SCRIPT_DIR.parent.parent

# Reuse central auth helpers
sys.path.insert(0, str(SCRIPT_DIR.parent))
from _auth import load_env, load_instance, mint_from_env as get_access_token  # noqa: E402


def load_records(records_dir: Path) -> List[Dict[str, Any]]:
    files = sorted(records_dir.glob("*.json"))
    records: List[Dict[str, Any]] = []
    for f in files:
        rec = json.loads(f.read_text(encoding="utf-8"))
        records.append(rec)
        print(f"  loaded {f.name}")
    return records


MAX_RETRIES = 4
RETRY_BACKOFF = [3, 6, 10, 15]


def put_records_batch(env: Dict[str, str], records: List[Dict[str, Any]],
                      client: httpx.Client) -> Dict[str, Any]:
    url = f"{env['host']}/api/storage/v2/records"
    headers = {
        "data-partition-id": env["partition"],
        "Content-Type": "application/json",
    }

    for attempt in range(MAX_RETRIES + 1):
        resp = client.put(url, json=records, headers=headers, timeout=120)
        if resp.status_code == 404 and attempt < MAX_RETRIES:
            wait = RETRY_BACKOFF[attempt]
            print(f"  404 on attempt {attempt+1}, retrying in {wait}s ...")
            time.sleep(wait)
            continue
        break

    if not resp.is_success:
        print(f"  PUT failed {resp.status_code}: {resp.text[:800]}")
        return {"error": resp.status_code, "body": resp.text[:800]}

    return resp.json()


def main():
    ap = argparse.ArgumentParser(description="Ingest DG2 records via Storage API")
    ap.add_argument("--instance", default="eqndev",
                    help="Instance name from k8s config (default: eqndev)")
    ap.add_argument("--records-dir", default=str(RECORDS_DIR))
    ap.add_argument("--delay", type=float, default=3,
                    help="Seconds to wait between records (default 3)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--start", type=int, default=0,
                    help="Skip records before this index (0-based)")
    args = ap.parse_args()

    print(f"Loading instance '{args.instance}' from k8s …")
    env = load_instance(args.instance)
    print(f"  source={env['source']}  host={env['host']}  partition={env['partition']}")

    records = load_records(Path(args.records_dir))

    if not records:
        print("No records found - nothing to ingest.")
        return

    print(f"\n  {len(records)} records to ingest → {env['host']}")

    if args.dry_run:
        print("  [dry-run] Skipping actual ingestion")
        return

    token = get_access_token(env)
    headers = {
        "Authorization": f"Bearer {token}",
        "data-partition-id": env["partition"],
        "Content-Type": "application/json",
    }

    created: List[str] = []
    skipped: List[str] = []
    failed:  List[str] = []
    active = records[args.start:]

    print(f"\nIngesting {len(active)} records …")
    with httpx.Client(headers=headers, timeout=120) as client:
        # Try single batch PUT first
        print(f"  Attempting single batch PUT ({len(active)} records) …")
        try:
            result = put_records_batch(env, active, client)
            created.extend(result.get("recordIds", []))
            skipped.extend(result.get("skippedRecordIds", []))
            print(f"  Batch OK - created={len(result.get('recordIds',[]))}  "
                  f"skipped={len(result.get('skippedRecordIds',[]))}")
        except Exception as e:
            print(f"  Batch PUT failed ({e}); falling back to sequential …")
            for i, rec in enumerate(active):
                rid = rec.get("id", "?")
                short = rid.split(":")[-1][:30] if ":" in rid else rid[:40]
                url = f"{env['host']}/api/storage/v2/records"
                for attempt in range(MAX_RETRIES + 1):
                    resp = client.put(url, json=[rec], timeout=60)
                    if resp.is_success:
                        r = resp.json()
                        created.extend(r.get("recordIds", []))
                        skipped.extend(r.get("skippedRecordIds", []))
                        tag = "OK  " if r.get("recordIds") else "SKIP"
                        print(f"  [{i+1:02d}/{len(active)}] {tag} {short}")
                        break
                    if resp.status_code == 404 and attempt < MAX_RETRIES:
                        wait = RETRY_BACKOFF[attempt]
                        print(f"        ↳ 404 - retry in {wait}s …")
                        time.sleep(wait)
                        continue
                    failed.append(f"{rid}: {resp.status_code} {resp.text[:200]}")
                    print(f"  [{i+1:02d}/{len(active)}] FAIL {short}")
                    break
                if i < len(active) - 1:
                    time.sleep(args.delay)

    print(f"\n--- Summary ---")
    print(f"  created/updated : {len(created)}")
    print(f"  skipped         : {len(skipped)}")
    print(f"  failed          : {len(failed)}")
    if created:
        print("\nCreated:")
        for rid in created:
            print(f"   {rid}")
    if failed:
        print("\nFailed:")
        for msg in failed:
            print(f"   {msg}")

    print("\nDG2 ingestion complete.")


if __name__ == "__main__":
    main()
