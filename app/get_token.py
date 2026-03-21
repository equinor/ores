#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
get_token.py — Mint an access token from the REFRESH_TOKEN in .env and
print it (plus shell-eval snippets so you can export it directly).

Usage:
  python get_token.py                  # print token only
  python get_token.py --shell bash     # print:  export TOKEN=...
  python get_token.py --shell pwsh     # print:  $env:TOKEN = "..."
  python get_token.py --shell pwsh --quiet   # token value only (for $(...))

PowerShell one-liner to set the variable in the current session:
  $env:TOKEN = (python get_token.py --quiet)

Bash one-liner:
  export TOKEN=$(python get_token.py --quiet)

  -- or --

  eval $(python get_token.py --shell bash)
"""

import argparse
import os
import sys
from pathlib import Path
from typing import Dict

import httpx

REPO_ROOT = Path(__file__).resolve().parent


# ── .env loader (no external deps) ──────────────────────────────────────
def _parse_dotenv(path: Path) -> Dict[str, str]:
    env: Dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        env[key.strip()] = val.strip()
    return env


def load_env() -> Dict[str, str]:
    """Merge OS env + .env file; OS env wins."""
    merged = _parse_dotenv(REPO_ROOT / ".env")
    merged.update({k: v for k, v in os.environ.items() if v})
    return merged


# ── Token exchange ───────────────────────────────────────────────────────
def get_access_token(env: Dict[str, str]) -> Dict[str, str]:
    tenant        = env.get("AZURE_TENANT_ID") or env.get("tenant", "")
    client_id     = env.get("AZURE_CLIENT_ID") or env.get("client_id", "")
    scope         = env.get("AZURE_SCOPE")     or env.get("scope", "")
    refresh_token = env.get("REFRESH_TOKEN")   or env.get("refresh_token", "")

    missing = [k for k, v in {
        "AZURE_TENANT_ID": tenant,
        "AZURE_CLIENT_ID": client_id,
        "AZURE_SCOPE": scope,
        "REFRESH_TOKEN": refresh_token,
    }.items() if not v]
    if missing:
        raise RuntimeError(f"Missing required env vars: {', '.join(missing)}")

    url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
    resp = httpx.post(url, data={
        "grant_type":    "refresh_token",
        "client_id":     client_id,
        "refresh_token": refresh_token,
        "scope":         scope,
    }, timeout=30)

    if not resp.is_success:
        raise RuntimeError(f"Token request failed ({resp.status_code}): {resp.text[:400]}")

    data = resp.json()
    access_token = data.get("access_token")
    if not access_token:
        raise RuntimeError(f"No access_token in response. Keys: {list(data.keys())}")

    return {
        "access_token": access_token,
        "expires_in":   str(data.get("expires_in", "?")),
        "token_type":   data.get("token_type", "Bearer"),
    }


# ── Main ─────────────────────────────────────────────────────────────────
def main() -> None:
    ap = argparse.ArgumentParser(description="Mint access token from .env REFRESH_TOKEN")
    ap.add_argument(
        "--shell",
        choices=["bash", "pwsh", "none"],
        default="none",
        help="Output shell-eval snippet instead of plain token",
    )
    ap.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Print the raw token value only (useful for command substitution)",
    )
    ap.add_argument(
        "--var",
        default="TOKEN",
        help="Variable name to use in shell snippet (default: TOKEN)",
    )
    args = ap.parse_args()

    env = load_env()

    try:
        result = get_access_token(env)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    token      = result["access_token"]
    expires_in = result["expires_in"]
    var        = args.var

    if args.quiet:
        print(token)
        return

    if args.shell == "bash":
        print(f'export {var}="{token}"')
        print(f'# expires_in={expires_in}s  —  eval $(python get_token.py --shell bash)')
    elif args.shell == "pwsh":
        print(f'$env:{var} = "{token}"')
        print(f'# expires_in={expires_in}s  —  run: Invoke-Expression (python get_token.py --shell pwsh)')
    else:
        # Default: human-readable summary
        print(f"access_token : {token}")
        print(f"expires_in   : {expires_in}s")
        print()
        print("── Quick copy ──────────────────────────────────────")
        print(f"  bash  :  export {var}=$(python get_token.py --quiet)")
        print(f"  pwsh  :  $env:{var} = (python get_token.py --quiet)")


if __name__ == "__main__":
    main()
