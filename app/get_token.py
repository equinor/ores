#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
get_token.py - Mint an access token from the active instance's credentials
and print it (plus shell-eval snippets so you can export it directly).

Delegates the actual token exchange to ``demo/_auth.py`` so the logic
lives in a single place.

Usage:
  python get_token.py                  # print token only
  python get_token.py --shell bash     # print:  export TOKEN=...
  python get_token.py --shell pwsh     # print:  $env:TOKEN = "..."
  python get_token.py --shell pwsh --quiet   # token value only (for $(...))
  python get_token.py --instance prod  # use a specific instance

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

# ── Wire up demo/_auth.py (single source of truth for token minting) ─────
_DEMO_DIR = str(Path(__file__).resolve().parent.parent / "demo")
if _DEMO_DIR not in sys.path:
    sys.path.insert(0, _DEMO_DIR)

from _auth import get_token as _auth_get_token  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent


# ── env loader (kept for backward compat) ────────────────────────────────

def load_env() -> Dict[str, str]:
    """Return current environment variables."""
    return {k: v for k, v in os.environ.items() if v}


def _resolve_instance_env(env: Dict[str, str], instance: str | None = None) -> Dict[str, str]:
    """Map INSTANCE_<NAME>_* vars to the canonical auth keys."""
    inst = (instance or env.get("DEFAULT_INSTANCE", "interop")).upper()
    prefix = f"INSTANCE_{inst}_"

    return {
        "AZURE_TENANT_ID": env.get(f"{prefix}TENANT_ID") or env.get("AZURE_TENANT_ID", ""),
        "AZURE_CLIENT_ID": env.get(f"{prefix}CLIENT_ID") or env.get("AZURE_CLIENT_ID", ""),
        "AZURE_SCOPE":     env.get(f"{prefix}SCOPE")     or env.get("AZURE_SCOPE", ""),
        "REFRESH_TOKEN":   env.get(f"{prefix}REFRESH_TOKEN") or env.get("REFRESH_TOKEN", ""),
    }


# ── Token exchange ───────────────────────────────────────────────────────
def get_access_token(env: Dict[str, str], instance: str | None = None) -> Dict[str, str]:
    """Mint an access token via _auth.get_token().

    Returns a dict with ``access_token``, ``expires_in``, ``token_type``
    for backward compatibility with the original interface.
    """
    inst_name = (instance or env.get("DEFAULT_INSTANCE", "interop")).lower()
    token = _auth_get_token(inst_name, verbose=False)
    return {
        "access_token": token,
        "expires_in":   "3600",
        "token_type":   "Bearer",
    }


# ── Main ─────────────────────────────────────────────────────────────────
def main() -> None:
    ap = argparse.ArgumentParser(description="Mint access token from instance credentials")
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
    ap.add_argument(
        "--instance", "-i",
        default=None,
        help="Instance name to use (default: DEFAULT_INSTANCE or interop)",
    )
    args = ap.parse_args()

    env = load_env()

    try:
        result = get_access_token(env, instance=args.instance)
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
        print(f'# expires_in={expires_in}s  -  eval $(python get_token.py --shell bash)')
    elif args.shell == "pwsh":
        print(f'$env:{var} = "{token}"')
        print(f'# expires_in={expires_in}s  -  run: Invoke-Expression (python get_token.py --shell pwsh)')
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
