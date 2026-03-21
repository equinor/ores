#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ingest_records_batch.py — Fast batch ingestion of Drogon records via
Storage API (PUT /api/storage/v2/records).

Authenticates ONCE via refresh_token (httpx + authlib, same as app/auth.py),
then sends all records in a single HTTP PUT call.

Reads config from .env (same as 4ingest.py).  Falls back to .env.template
values for non-secret fields.

Usage:
  py demo/drogon/ingest_records_batch.py --env-file .env
  py demo/drogon/ingest_records_batch.py --env-file .env --dry-run
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

SCRIPT_DIR = Path(__file__).resolve().parent
RECORDS_DIR = SCRIPT_DIR / "records"
REPO_ROOT = SCRIPT_DIR.parent.parent  # ores/


# ──────────────── .env loader (reuses _shared) ──────────────── #
from _shared import parse_dotenv as _parse_dotenv, first_env as _first, load_env  # noqa: E402


# ──────────────── Auth (httpx — same transport as app/auth.py) ──────────────── #
def get_access_token(env: Dict[str, str]) -> str:
    """
    Mint an access_token via AAD v2 refresh_token grant using httpx
    (avoids the requests timeout issue on this network).
    """
    url = f"https://login.microsoftonline.com/{env['tenant']}/oauth2/v2.0/token"
    form = {
        "grant_type":    "refresh_token",
        "client_id":     env["client_id"],
        "refresh_token": env["refresh_token"],
        "scope":         env["scope"],
    }
    r = httpx.post(url, data=form, timeout=30)
    if not r.is_success:
        raise RuntimeError(f"Auth failed ({r.status_code}): {r.text[:600]}")
    data = r.json()
    token = data.get("access_token")
    if not token:
        raise RuntimeError(f"No access_token in response: {list(data.keys())}")
    print(f"  token acquired (expires_in={data.get('expires_in', '?')}s)")
    return token


# ──────────────── Record helpers ──────────────── #
def load_records(records_dir: Path) -> List[Dict[str, Any]]:
    """Load all JSON record files in sorted order."""
    files = sorted(records_dir.glob("*.json"))
    records: List[Dict[str, Any]] = []
    for f in files:
        rec = json.loads(f.read_text(encoding="utf-8"))
        records.append(rec)
        print(f"  loaded {f.name}")
    return records


# ──────────────── Storage API ──────────────── #
MAX_RETRIES = 4          # retry up to 4 times on transient 404 (eventual consistency)
RETRY_BACKOFF = [3, 6, 10, 15]  # seconds between retries


def put_records_batch(env: Dict[str, str], records: List[Dict[str, Any]],
                      client: httpx.Client) -> Dict[str, Any]:
    """PUT all records in a single call (up to 500 per OSDU limit)."""
    url = f"{env['host']}/api/storage/v2/records"
    r = client.put(url, json=records, timeout=120)
    if r.is_success:
        return r.json()
    raise RuntimeError(f"Batch PUT failed ({r.status_code}): {r.text[:1000]}")


def put_one_record(env: Dict[str, str], record: Dict[str, Any],
                   client: httpx.Client) -> Dict[str, Any]:
    """PUT a single record, retrying on 404 (parent not yet indexed)."""
    url = f"{env['host']}/api/storage/v2/records"
    for attempt in range(MAX_RETRIES + 1):
        r = client.put(url, json=[record], timeout=60)
        if r.is_success:
            return r.json()
        # Retry only on 404 (ancestry parent not found yet — eventual consistency)
        if r.status_code == 404 and attempt < MAX_RETRIES:
            wait = RETRY_BACKOFF[attempt]
            print(f"        ↳ 404 parent not indexed yet — retry in {wait}s …")
            time.sleep(wait)
            continue
        raise RuntimeError(f"PUT failed ({r.status_code}): {r.text[:1000]}")
    raise RuntimeError("Unreachable")


# ──────────────── Main ──────────────── #
def main():
    ap = argparse.ArgumentParser(description="Fast batch-ingest Drogon records via Storage API")
    ap.add_argument("--env-file", action="append", default=[],
                    help=".env file(s) with auth credentials (repeatable)")
    ap.add_argument("--records-dir", default=str(RECORDS_DIR))
    ap.add_argument("--dry-run", action="store_true", help="Load and validate without sending")
    ap.add_argument("--start", type=int, default=0,
                    help="Skip records before this index (0-based, default 0)")
    ap.add_argument("--delay", type=float, default=3,
                    help="Seconds to wait between records (default 3, for indexing)")
    args = ap.parse_args()

    # Default to REPO_ROOT/.env if nothing specified
    env_files = args.env_file or [str(REPO_ROOT / ".env")]

    print("Loading env …")
    env = load_env(env_files)
    print(f"  host={env['host']}  partition={env['partition']}")

    records_dir = Path(args.records_dir)
    print(f"\nLoading records from {records_dir}:")
    records = load_records(records_dir)
    print(f"\n{len(records)} records loaded")

    if args.dry_run:
        print("\n[dry-run] Would PUT these records — exiting.")
        return

    print("\nAuthenticating …")
    token = get_access_token(env)

    # Send records one at a time in dependency order (files are already sorted).
    # This ensures parents exist before children that reference them via ancestry.
    # A delay between each PUT gives the index time to catch up.
    headers = {
        "Authorization":     f"Bearer {token}",
        "data-partition-id": env["partition"],
        "Content-Type":      "application/json",
    }
    created: List[str] = []
    skipped: List[str] = []
    failed:  List[str] = []

    active = records[args.start:]
    print(f"\nIngesting {len(active)} records …")
    with httpx.Client(headers=headers) as client:
        # ── Try a single batch PUT first ──────────────────────────────────────
        if args.start == 0:
            print(f"  Attempting single batch PUT ({len(active)} records) …")
            try:
                resp = put_records_batch(env, active, client)
                created.extend(resp.get("recordIds", []))
                skipped.extend(resp.get("skippedRecordIds", []))
                print(f"  Batch OK — created={len(resp.get('recordIds',[]))}  "
                      f"skipped={len(resp.get('skippedRecordIds',[]))}")
            except RuntimeError as e:
                print(f"  Batch PUT failed ({e}); falling back to sequential …")
                # Fall through to sequential below
                args.start = 0   # reset so sequential loop covers all
                for i, rec in enumerate(active):
                    rid = rec.get("id", "?")
                    short = rid.split(":")[-1][:30] if ":" in rid else rid[:40]
                    try:
                        r = put_one_record(env, rec, client)
                        ids = r.get("recordIds", [])
                        sk  = r.get("skippedRecordIds", [])
                        created.extend(ids)
                        skipped.extend(sk)
                        tag = "OK  " if ids else "SKIP"
                        print(f"  [{i+1:02d}/{len(active)}] {tag} {short}")
                    except RuntimeError as e2:
                        failed.append(f"{rid}: {e2}")
                        print(f"  [{i+1:02d}/{len(active)}] FAIL {short}: {e2}")
                    if i < len(active) - 1:
                        time.sleep(args.delay)
        else:
            # --start was specified: sequential only
            print(f"  Sequential mode (--start {args.start}, delay={args.delay}s) …")
            for i, rec in enumerate(records):
                rid = rec.get("id", "?")
                short = rid.split(":")[-1][:30] if ":" in rid else rid[:40]
                if i < args.start:
                    print(f"  [{i+1:02d}/{len(records)}] SKIP (--start) {short}")
                    continue
                try:
                    r = put_one_record(env, rec, client)
                    ids = r.get("recordIds", [])
                    sk  = r.get("skippedRecordIds", [])
                    created.extend(ids)
                    skipped.extend(sk)
                    tag = "OK  " if ids else "SKIP"
                    print(f"  [{i+1:02d}/{len(records)}] {tag} {short}")
                except RuntimeError as e:
                    failed.append(f"{rid}: {e}")
                    print(f"  [{i+1:02d}/{len(records)}] FAIL {short}: {e}")
                if i < len(records) - 1:
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


if __name__ == "__main__":
    main()
