#!/usr/bin/env python3
"""Flush (delete) ALL objects from an OSDU Reservoir DDMS dataspace.

Connection parameters can be supplied via CLI flags or a .env file.

Usage:
  python flushDataspace.py maap/drogon_dg
  python flushDataspace.py maap/drogon_dg --dry-run
  python flushDataspace.py maap/drogon_dg --host equinorswedev.energy.azure.com --partition dev
  python flushDataspace.py maap/drogon_dg --env-file /path/to/.env
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from urllib.parse import quote

import requests

# ── Central auth module ──────────────────────────────────────────────
_SCRIPT_DIR = Path(__file__).resolve().parent
_DEMO_DIR = _SCRIPT_DIR.parent.parent
sys.path.insert(0, str(_DEMO_DIR))
from _auth import mint_from_env as _mint  # noqa: E402

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def get_token(tenant: str, client_id: str, refresh_token: str, scope: str) -> str:
    """Mint an access token via the central _auth module."""
    env = {
        "tenant": tenant,
        "client_id": client_id,
        "refresh_token": refresh_token,
        "scope": scope,
    }
    return _mint(env)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def rddms_headers(token: str, partition: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "data-partition-id": partition,
    }


def extract_uuid(uri: str) -> str | None:
    m = re.search(r"\(([0-9a-f-]{36})\)", uri)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def flush(
    dataspace: str,
    host: str,
    partition: str,
    token: str,
    *,
    dry_run: bool = False,
    retries: int = 2,
) -> tuple[int, int]:
    """Delete every object in *dataspace*. Returns (deleted, failed)."""

    base = f"https://{host}/api/reservoir-ddms/v2"
    h = rddms_headers(token, partition)
    enc = quote(dataspace, safe="")

    # List resource types
    r = requests.get(f"{base}/dataspaces/{enc}/resources", headers=h)
    r.raise_for_status()
    types = r.json()
    total = sum(t["count"] for t in types)
    print(f"Dataspace '{dataspace}': {total} objects across {len(types)} types\n")

    if total == 0:
        print("Nothing to delete.")
        return 0, 0

    deleted = 0
    failed = 0

    for t in types:
        tname = t["name"]
        r2 = requests.get(f"{base}/dataspaces/{enc}/resources/{tname}", headers=h)
        r2.raise_for_status()
        objs = r2.json()

        for obj in objs:
            uid = extract_uuid(obj.get("uri", ""))
            if not uid:
                continue
            name = obj.get("name", "")[:50]

            if dry_run:
                print(f"  [DRY-RUN] {tname}/{uid}  {name}")
                deleted += 1
                continue

            ok = False
            for attempt in range(1, retries + 1):
                rd = requests.delete(
                    f"{base}/dataspaces/{enc}/resources/{tname}/{uid}",
                    headers=h,
                )
                if rd.status_code in (200, 204):
                    deleted += 1
                    ok = True
                    break
                if rd.status_code == 412 and attempt < retries:
                    # FK constraint - retry after other dependents are removed
                    continue
                failed += 1
                print(f"  FAIL {tname}/{uid}: HTTP {rd.status_code} {rd.text[:120]}")
                break

        tag = "[DRY-RUN] " if dry_run else ""
        print(f"  {tag}{tname}: {len(objs)} processed")

    # Second pass: retry FK failures (objects that had dependents)
    if failed > 0 and not dry_run:
        print(f"\n--- Retry pass (FK cleanup) ---")
        r = requests.get(f"{base}/dataspaces/{enc}/resources", headers=h)
        r.raise_for_status()
        remaining = r.json()
        rem_total = sum(t["count"] for t in remaining)
        if rem_total > 0:
            print(f"  {rem_total} objects remaining, retrying...")
            for t in remaining:
                tname = t["name"]
                r2 = requests.get(f"{base}/dataspaces/{enc}/resources/{tname}", headers=h)
                r2.raise_for_status()
                for obj in r2.json():
                    uid = extract_uuid(obj.get("uri", ""))
                    if not uid:
                        continue
                    rd = requests.delete(
                        f"{base}/dataspaces/{enc}/resources/{tname}/{uid}",
                        headers=h,
                    )
                    if rd.status_code in (200, 204):
                        deleted += 1
                        failed -= 1
                    else:
                        print(f"  STILL FAIL {tname}/{uid}: HTTP {rd.status_code}")

    return deleted, failed


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def load_env_file(path: str) -> None:
    """Minimal .env loader - delegates to central _auth module."""
    from _auth import parse_dotenv as _pd
    from pathlib import Path as _P
    for k, v in _pd(_P(path)).items():
        os.environ.setdefault(k, v)


def main():
    ap = argparse.ArgumentParser(
        description="Flush (delete) all objects from an OSDU Reservoir DDMS dataspace.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("dataspace", help="Dataspace path, e.g. maap/drogon_dg")
    ap.add_argument("--host", default=None, help="OSDU host (default: from .env OSDU_BASE_URL)")
    ap.add_argument("--partition", default=None, help="Data partition (default: from .env DATA_PARTITION_ID)")
    ap.add_argument("--tenant", default=None, help="Azure AD tenant ID")
    ap.add_argument("--client-id", default=None, help="Azure AD client ID")
    ap.add_argument("--refresh-token", default=None, help="Azure AD refresh token")
    ap.add_argument("--scope", default=None, help="Azure AD scope")
    ap.add_argument("--env-file", default=".env", help="Path to .env file (default: .env)")
    ap.add_argument("--dry-run", action="store_true", help="List objects without deleting")
    args = ap.parse_args()

    # Load .env (CLI flags override)
    load_env_file(args.env_file)

    host = args.host or os.getenv("OSDU_BASE_URL", os.getenv("OSDU_HOST", ""))
    partition = args.partition or os.getenv("DATA_PARTITION_ID", os.getenv("OSDU_PARTITION", ""))
    tenant = args.tenant or os.getenv("AZURE_TENANT_ID", "")
    client_id = args.client_id or os.getenv("AZURE_CLIENT_ID", "")
    rt = args.refresh_token or os.getenv("REFRESH_TOKEN", os.getenv("refresh_token", ""))
    scope = args.scope or os.getenv("AZURE_SCOPE", "")

    missing = []
    if not host:        missing.append("--host / OSDU_BASE_URL")
    if not partition:   missing.append("--partition / DATA_PARTITION_ID")
    if not tenant:      missing.append("--tenant / AZURE_TENANT_ID")
    if not client_id:   missing.append("--client-id / AZURE_CLIENT_ID")
    if not rt:          missing.append("--refresh-token / REFRESH_TOKEN")
    if not scope:       missing.append("--scope / AZURE_SCOPE")
    if missing:
        print(f"ERROR: Missing required parameters: {', '.join(missing)}", file=sys.stderr)
        print("Supply via CLI flags or .env file.", file=sys.stderr)
        sys.exit(1)

    print(f"Host:       {host}")
    print(f"Partition:  {partition}")
    print(f"Dataspace:  {args.dataspace}")
    print(f"Dry-run:    {args.dry_run}")
    print()

    token = get_token(tenant, client_id, rt, scope)
    print("Token acquired.\n")

    deleted, failed = flush(args.dataspace, host, partition, token, dry_run=args.dry_run)
    print(f"\nResult: {deleted} deleted, {failed} failed")
    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
