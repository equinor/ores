#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
register_schema_devconcept.py - Register the custom DevelopmentConcept WPC
schema with the OSDU Schema Service.

The schema definition lives in ``schema_devconcept.json`` (same directory).
It creates the kind:

    dev:wks:work-product-component--DevelopmentConcept:3.0.0

This must be run ONCE before ingesting DevelopmentConcept WPC records.
Re-running is safe - the Schema Service will return 409 if the version
already exists.

Usage:
  py demo/drogon_dg1/register_schema_devconcept.py
  py demo/drogon_dg1/register_schema_devconcept.py --env-file .env
  py demo/drogon_dg1/register_schema_devconcept.py --dry-run
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict

import httpx

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT  = SCRIPT_DIR.parent.parent

import sys as _sys
_sys.path.insert(0, str(REPO_ROOT / "demo"))
from _auth import load_env, mint_from_env as get_access_token  # noqa: E402


def register_schema(env: Dict[str, str], token: str, payload: dict,
                    *, dry_run: bool = False) -> None:
    """PUT schema to the OSDU Schema Service."""
    url = f"{env['host']}/api/schema-service/v1/schema"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json",
        "data-partition-id": env["partition"],
    }

    kind = (
        f"{payload['schemaInfo']['schemaIdentity']['authority']}:"
        f"{payload['schemaInfo']['schemaIdentity']['source']}:"
        f"{payload['schemaInfo']['schemaIdentity']['entityType']}:"
        f"{payload['schemaInfo']['schemaIdentity']['schemaVersionMajor']}."
        f"{payload['schemaInfo']['schemaIdentity']['schemaVersionMinor']}."
        f"{payload['schemaInfo']['schemaIdentity']['schemaVersionPatch']}"
    )

    print(f"\n  Schema kind : {kind}")
    print(f"  Target URL  : {url}")
    print(f"  Status      : {payload['schemaInfo']['status']}")

    if dry_run:
        print("\n  [DRY-RUN] Would PUT schema – skipping.")
        print(json.dumps(payload, indent=2)[:2000])
        return

    # Try PUT (create)
    r = httpx.put(url, headers=headers, json=payload, timeout=60)

    if r.status_code == 201:
        print(f"\n  ✓ Schema registered successfully ({r.status_code})")
    elif r.status_code == 409:
        print(f"\n  ⚠ Schema already exists ({r.status_code}) - no action needed.")
    elif r.status_code == 200:
        print(f"\n  ✓ Schema updated ({r.status_code})")
    else:
        corr = r.headers.get("x-correlation-id") or r.headers.get("x-request-id") or ""
        print(f"\n  ✗ Registration failed ({r.status_code}) corr={corr}")
        print(f"    {r.text[:1000]}")
        sys.exit(1)


def main():
    ap = argparse.ArgumentParser(description="Register DevelopmentConcept custom schema")
    ap.add_argument("--schema", default=str(SCRIPT_DIR / "schema_devconcept.json"),
                    help="Path to the schema registration JSON payload.")
    ap.add_argument("--env-file", nargs="*", default=[str(REPO_ROOT / ".env")],
                    help="One or more .env files (merged left-to-right).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the payload instead of sending it.")
    args = ap.parse_args()

    # Load auth + host
    env = load_env(args.env_file)
    print(f"  host      : {env['host']}")
    print(f"  partition : {env['partition']}")

    # Load schema payload
    schema_path = Path(args.schema)
    if not schema_path.exists():
        raise SystemExit(f"Schema file not found: {schema_path}")
    with open(schema_path, encoding="utf-8") as f:
        payload = json.load(f)

    # Auth
    token = get_access_token(env)

    # Register
    register_schema(env, token, payload, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
