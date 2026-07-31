#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_token_oresdev.py - Fetch an access token for the ores-dev app (client_credentials).

This uses the new ores-dev app registration which authenticates via
client_id + client_secret (no refresh_token needed).

App details:
  Display name:  ores-dev
  Client ID:     21b442a9-6c1c-4551-b234-afdf010dd3be
  Tenant:        3aa4a235-b6e2-48d5-9195-7fcf05b459b0 (Equinor)
  Object ID:     3d7bd7a7-756c-4558-9209-e4b802be47cc
  Grant:         client_credentials (app-only, no user interaction)
  Target API:    7daee810-3f78-40c4-84c2-7a199428de18 (OSDU platform)

Usage:
  python demo/fetch_token_oresdev.py                  # print token
  python demo/fetch_token_oresdev.py --quiet          # token only (for $(...))
  python demo/fetch_token_oresdev.py --export bash    # export TOKEN=...
  python demo/fetch_token_oresdev.py --export pwsh    # $env:TOKEN = "..."
  python demo/fetch_token_oresdev.py --json           # full JSON response

Bash one-liner:
  export TOKEN=$(python demo/fetch_token_oresdev.py --quiet)

PowerShell:
  $env:TOKEN = (python demo/fetch_token_oresdev.py --quiet)

Note:
  client_credentials does NOT return a refresh_token.
  Tokens are minted fresh each time (valid ~60 min).
  The client_secret itself is valid until its Azure Portal expiry date.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# ── Wire up _auth.py ─────────────────────────────────────────────────────
_DEMO_DIR = str(Path(__file__).resolve().parent)
if _DEMO_DIR not in sys.path:
    sys.path.insert(0, _DEMO_DIR)

from _auth import load_instance, get_token  # noqa: E402

INSTANCE_NAME = "oresdev"


def _fetch_full_response() -> dict:
    """Mint token and return the full Azure AD response."""
    import httpx

    inst = load_instance(INSTANCE_NAME)
    url = f"https://login.microsoftonline.com/{inst['tenant']}/oauth2/v2.0/token"
    form = {
        "grant_type": "client_credentials",
        "client_id": inst["client_id"],
        "client_secret": inst["client_secret"],
        "scope": inst["scope"],
    }
    r = httpx.post(url, data=form, timeout=30)
    if not r.is_success:
        raise RuntimeError(f"Auth failed ({r.status_code}): {r.text[:500]}")
    return r.json()


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Fetch access token for ores-dev (client_credentials)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Print only the access token (for scripting)",
    )
    ap.add_argument(
        "--export", "-e",
        choices=["bash", "pwsh"],
        help="Print shell export statement",
    )
    ap.add_argument(
        "--json", "-j",
        action="store_true",
        help="Print full token response as JSON",
    )
    ap.add_argument(
        "--instance", "-i",
        default=INSTANCE_NAME,
        help=f"Instance name (default: {INSTANCE_NAME})",
    )
    args = ap.parse_args()

    instance = args.instance

    try:
        if args.json:
            data = _fetch_full_response()
            print(json.dumps(data, indent=2))
            return

        token = get_token(instance, verbose=not args.quiet)

        if args.quiet:
            print(token)
        elif args.export == "bash":
            print(f'export TOKEN="{token}"')
        elif args.export == "pwsh":
            print(f'$env:TOKEN = "{token}"')
        else:
            inst = load_instance(instance)
            print(f"Instance:     {instance}", file=sys.stderr)
            print(f"Client ID:    {inst['client_id']}", file=sys.stderr)
            print(f"Tenant:       {inst['tenant']}", file=sys.stderr)
            print(f"Scope:        {inst['scope']}", file=sys.stderr)
            print(f"Grant:        {inst['grant']}", file=sys.stderr)
            print(f"Token length: {len(token)}", file=sys.stderr)
            print(file=sys.stderr)
            print(token)

    except (RuntimeError, SystemExit) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
