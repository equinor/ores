#!/usr/bin/env python3
"""
copy_dataspace.py – Copy all objects from one RDDMS dataspace to another
via the REST transactional API.

Usage:
    cd demo/drogonresqml && python3 copy_dataspace.py [--src maap/drogon_dg] [--dst maap/drogon2]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
from pathlib import Path

import httpx

# ── Defaults ──────────────────────────────────────────────────────────────── #
BASE = "https://equinorswedev.energy.azure.com/api/reservoir-ddms/v2"
BATCH_SIZE = 10
TIMEOUT_GET = 60
TIMEOUT_PUT = 120
TIMEOUT_COMMIT = 600

URI_RE = re.compile(r"(?P<type>[\w.]+)\((?P<uuid>[0-9a-fA-F-]{36})\)")


def _enc(path: str) -> str:
    return urllib.parse.quote(path, safe="")


def main():
    parser = argparse.ArgumentParser(description="Copy RDDMS dataspace objects via REST")
    parser.add_argument("--src", default="maap/drogon_dg", help="Source dataspace path")
    parser.add_argument("--dst", default="maap/drogon2", help="Destination dataspace path")
    parser.add_argument("--batch", type=int, default=BATCH_SIZE, help="Batch size for PUT")
    parser.add_argument("--dry-run", action="store_true", help="List objects without copying")
    args = parser.parse_args()

    SRC, DST = args.src, args.dst
    SRC_ENC, DST_ENC = _enc(SRC), _enc(DST)
    batch_size = args.batch

    # ── Auth ──────────────────────────────────────────────────────────────
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from _auth import get_token
    token = get_token("eqndev")
    h = {
        "Authorization": f"Bearer {token}",
        "data-partition-id": "dev",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    # ── 1. List types in source ───────────────────────────────────────────
    print(f"\n=== 1. List types in {SRC} ===")
    r = httpx.get(f"{BASE}/dataspaces/{SRC_ENC}/resources", headers=h, timeout=30)
    if r.status_code != 200:
        sys.exit(f"Failed to list types: {r.status_code} {r.text[:300]}")
    type_list = r.json() or []
    type_names = []
    for t in type_list:
        name = t.get("name", "") or t.get("uri", "")
        if name:
            type_names.append(name)
    print(f"  {len(type_names)} types found")

    # ── 2. Fetch all objects ──────────────────────────────────────────────
    print(f"\n=== 2. Fetch objects from {SRC} ===")
    all_objects = []
    skipped_types = []
    for typ in sorted(type_names):
        url = f"{BASE}/dataspaces/{SRC_ENC}/resources/{typ}"
        r = httpx.get(url, headers=h, timeout=30)
        if r.status_code != 200:
            print(f"  {typ}: SKIP (listing failed {r.status_code})")
            skipped_types.append(typ)
            continue
        entries = r.json() or []
        print(f"  {typ}: {len(entries)} objects")

        for entry in entries:
            uri = entry.get("uri", "")
            m = URI_RE.search(uri)
            if not m:
                print(f"    SKIP (bad URI): {uri}")
                continue
            obj_type = m.group("type")
            obj_uuid = m.group("uuid")

            # GET full object
            obj_url = f"{BASE}/dataspaces/{SRC_ENC}/resources/{obj_type}/{obj_uuid}"
            r2 = httpx.get(obj_url, headers=h, timeout=TIMEOUT_GET)
            if r2.status_code != 200:
                print(f"    SKIP {obj_type}/{obj_uuid}: GET {r2.status_code}")
                continue
            obj_data = r2.json()
            # Unwrap list-wrapped response
            if isinstance(obj_data, list) and len(obj_data) == 1:
                obj_data = obj_data[0]
            if isinstance(obj_data, dict):
                all_objects.append(obj_data)

    print(f"\n  Total fetched: {len(all_objects)} objects")
    if args.dry_run:
        print("  (dry run - not copying)")
        return

    # ── 3. Begin transaction on destination ───────────────────────────────
    print(f"\n=== 3. Begin transaction on {DST} ===")
    r = httpx.post(f"{BASE}/dataspaces/{DST_ENC}/transactions", headers=h, timeout=30)
    if r.status_code != 201:
        sys.exit(f"Failed to begin tx: {r.status_code} {r.text[:300]}")
    tx_id = r.text.strip().strip('"')
    print(f"  tx: {tx_id}")

    # ── 4. PUT objects in batches ─────────────────────────────────────────
    print(f"\n=== 4. PUT {len(all_objects)} objects (batch={batch_size}) ===")
    success = 0
    errors = 0
    t0 = time.time()

    for i in range(0, len(all_objects), batch_size):
        batch = all_objects[i:i + batch_size]
        batch_types = set(o.get("$type", "?") for o in batch)
        try:
            r = httpx.put(
                f"{BASE}/dataspaces/{DST_ENC}/resources",
                headers=h,
                params={"transactionId": tx_id},
                json=batch,
                timeout=TIMEOUT_PUT,
            )
            if r.status_code < 300:
                success += len(batch)
                print(f"  [{i}:{i+len(batch)}] OK  ({', '.join(sorted(batch_types))})")
            else:
                print(f"  [{i}:{i+len(batch)}] FAIL {r.status_code}: {r.text[:300]}")
                # Retry one-by-one
                for obj in batch:
                    r2 = httpx.put(
                        f"{BASE}/dataspaces/{DST_ENC}/resources",
                        headers=h,
                        params={"transactionId": tx_id},
                        json=[obj],
                        timeout=TIMEOUT_PUT,
                    )
                    if r2.status_code < 300:
                        success += 1
                        print(f"    ok {obj.get('$type','?')}/{obj.get('Uuid','?')}")
                    else:
                        errors += 1
                        print(f"    FAIL {obj.get('$type','?')}/{obj.get('Uuid','?')}: {r2.status_code}")
        except Exception as e:
            errors += len(batch)
            print(f"  [{i}:{i+len(batch)}] EXCEPTION: {e}")

    elapsed = time.time() - t0
    print(f"\n  Results: {success} ok, {errors} errors ({elapsed:.1f}s)")

    # ── 5. Commit or rollback ─────────────────────────────────────────────
    if errors == 0 or success > errors * 3:
        print(f"\n=== 5. Commit ===")
        r = httpx.put(f"{BASE}/dataspaces/{DST_ENC}/transactions/{tx_id}",
                      headers=h, timeout=TIMEOUT_COMMIT)
        if r.status_code < 300:
            print(f"  COMMITTED ({r.status_code})")
        else:
            print(f"  COMMIT FAILED: {r.status_code} {r.text[:500]}")
            sys.exit(1)
    else:
        print(f"\n=== 5. Rollback ===")
        httpx.delete(f"{BASE}/dataspaces/{DST_ENC}/transactions/{tx_id}",
                     headers=h, timeout=30)
        print(f"  Rolled back")
        sys.exit(1)

    # ── 6. Verify ─────────────────────────────────────────────────────────
    print(f"\n=== 6. Verify {DST} ===")
    r = httpx.get(f"{BASE}/dataspaces/{DST_ENC}/resources/all",
                  headers=h, timeout=30)
    if r.status_code == 200:
        items = r.json() or []
        print(f"  Total: {len(items)} objects")
    else:
        print(f"  Verify failed: {r.status_code}")

    print("\nDone.")


if __name__ == "__main__":
    main()
