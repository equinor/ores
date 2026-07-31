#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rotate_token.py - Rotate the Azure AD refresh token before it expires.

Exchanges the current refresh_token for a fresh access_token + new refresh_token,
then persists the new refresh_token to all configured storage locations:
  - /home/maap/ores/k8s/secret.yaml    (INSTANCE_EQNDEV_REFRESH_TOKEN)
  - /home/maap/gocad/lib/app-defaults/.env  (REFRESH_TOKEN)

Usage:
  python demo/rotate_token.py                     # rotate default (eqndev)
  python demo/rotate_token.py --instance eqndev   # explicit instance
  python demo/rotate_token.py --dry-run            # show what would change

Run this periodically (e.g. monthly) to keep the refresh token alive.
Azure AD refresh tokens expire after ~90 days of inactivity.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# ── Wire up _auth.py ─────────────────────────────────────────────────────
_DEMO_DIR = str(Path(__file__).resolve().parent)
if _DEMO_DIR not in sys.path:
    sys.path.insert(0, _DEMO_DIR)

from _auth import rotate_token, load_instance  # noqa: E402

# ── Storage locations ────────────────────────────────────────────────────
ORES_K8S_SECRET = Path("/home/maap/ores/k8s/secret.yaml")
GOCAD_ENV       = Path("/home/maap/gocad/lib/app-defaults/.env")


def _update_k8s_secret(new_rt: str, instance: str = "eqndev", dry_run: bool = False) -> bool:
    """Update INSTANCE_<NAME>_REFRESH_TOKEN in k8s/secret.yaml."""
    if not ORES_K8S_SECRET.exists():
        print(f"  SKIP {ORES_K8S_SECRET} (not found)", file=sys.stderr)
        return False

    key = f"INSTANCE_{instance.upper()}_REFRESH_TOKEN"
    text = ORES_K8S_SECRET.read_text(encoding="utf-8")

    # Match:   INSTANCE_EQNDEV_REFRESH_TOKEN: "..."  (possibly multi-line with trailing spaces)
    pattern = rf'({key}:\s*)"[^"]*"'
    if not re.search(pattern, text):
        # Try without quotes
        pattern_nq = rf'({key}:\s*)\S+'
        if not re.search(pattern_nq, text):
            print(f"  SKIP {ORES_K8S_SECRET} (key {key} not found)", file=sys.stderr)
            return False
        replacement = rf'\g<1>"{new_rt}"'
        new_text = re.sub(pattern_nq, replacement, text, count=1)
    else:
        replacement = rf'\g<1>"{new_rt}"'
        new_text = re.sub(pattern, replacement, text, count=1)

    if dry_run:
        print(f"  DRY-RUN would update {ORES_K8S_SECRET} ({key})", file=sys.stderr)
        return True

    ORES_K8S_SECRET.write_text(new_text, encoding="utf-8")
    print(f"  ✓ Updated {ORES_K8S_SECRET} ({key})", file=sys.stderr)
    return True


def _update_gocad_env(new_rt: str, dry_run: bool = False) -> bool:
    """Update REFRESH_TOKEN in gocad .env file."""
    if not GOCAD_ENV.exists():
        print(f"  SKIP {GOCAD_ENV} (not found)", file=sys.stderr)
        return False

    text = GOCAD_ENV.read_text(encoding="utf-8")

    # Match: REFRESH_TOKEN="..." or REFRESH_TOKEN=...
    pattern = r'(REFRESH_TOKEN\s*=\s*)"[^"]*"'
    if not re.search(pattern, text):
        # Try unquoted (single-line value)
        pattern = r'(REFRESH_TOKEN\s*=\s*)\S+'
        if not re.search(pattern, text):
            print(f"  SKIP {GOCAD_ENV} (REFRESH_TOKEN key not found)", file=sys.stderr)
            return False

    replacement = rf'\g<1>"{new_rt}"'
    new_text = re.sub(pattern, replacement, text, count=1)

    if dry_run:
        print(f"  DRY-RUN would update {GOCAD_ENV}", file=sys.stderr)
        return True

    GOCAD_ENV.write_text(new_text, encoding="utf-8")
    print(f"  ✓ Updated {GOCAD_ENV}", file=sys.stderr)
    return True


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Rotate Azure AD refresh token and persist to config files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument(
        "--instance", "-i",
        default="eqndev",
        help="Instance name (default: eqndev)",
    )
    ap.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="Show what would be updated without writing",
    )
    ap.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Print only the new refresh token (for scripting)",
    )
    args = ap.parse_args()

    verbose = not args.quiet

    if verbose:
        print(f"Rotating token for instance: {args.instance}", file=sys.stderr)

    try:
        result = rotate_token(args.instance, verbose=verbose)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    new_rt = result["refresh_token"]
    rotated = result["rotated"] == "true"

    if verbose:
        if rotated:
            print(f"  Azure AD issued a NEW refresh token (rotated)", file=sys.stderr)
        else:
            print(f"  Azure AD returned same refresh token (no rotation)", file=sys.stderr)
        print(f"  New RT prefix: {new_rt[:40]}...", file=sys.stderr)
        print(f"  access_token expires_in: {result['expires_in']}s", file=sys.stderr)
        print(file=sys.stderr)

    # Persist to storage
    if not args.dry_run and not rotated:
        if verbose:
            print("  Token unchanged - no files to update.", file=sys.stderr)
    else:
        _update_k8s_secret(new_rt, instance=args.instance, dry_run=args.dry_run)
        _update_gocad_env(new_rt, dry_run=args.dry_run)

    if args.quiet:
        # Print just the new RT for scripting
        print(new_rt)
    elif verbose:
        print(file=sys.stderr)
        print("Done. The new token is valid - use it within 90 days to keep it alive.", file=sys.stderr)


if __name__ == "__main__":
    main()
