#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gettoken.py - Mint an OSDU access token for any configured instance.

Thin CLI wrapper.  Core k8s-loading and token-minting lives in
:mod:`_auth`; this module adds the rich CLI (``--list``, ``--export``,
``--json``, ``--from-k8s``) and the hard-coded INSTANCES dict for
legacy ``etp_url()`` / ``partition()`` helpers.

Secret sources (checked in order):
  1. ``k8s/secret.yaml`` + ``k8s/configmap.yaml`` (``--from-k8s``, or auto)
  2. Environment variables (``INSTANCE_<NAME>_*`` pattern, or legacy names)
  3. Hard-coded defaults for known instances (swedev, preship)

Usage:
  python demo/gettoken.py swedev              # env vars (legacy)
  python demo/gettoken.py eqndev --from-k8s   # read from k8s YAMLs
  python demo/gettoken.py --list               # show available instances

  # bash one-liners
  export TOKEN=$(python demo/gettoken.py swedev)
  eval "$(python demo/gettoken.py --export)"

  # verbose (shows expiry etc. on stderr, token on stdout)
  python demo/gettoken.py swedev -v
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import httpx
except ImportError:
    sys.exit("Missing httpx - pip install httpx")

# _auth.py is the single source of truth for k8s YAML loading.
# Re-export so ``gettoken._load_k8s_yaml`` / ``gettoken.load_k8s_env``
# keep working (tests and dataspacecopy.py rely on the names).
from _auth import (                                      # noqa: E402
    _load_k8s_yaml,
    load_k8s_env,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
K8S_DIR = REPO_ROOT / "k8s"


# ── Instance defaults (non-secret, fallback for legacy env vars) ─────── #

INSTANCES: Dict[str, Dict[str, Any]] = {
    "swedev": {
        "label":     "Equinor SWE dev",
        "tenant_id": "3aa4a235-b6e2-48d5-9195-7fcf05b459b0",
        "client_id": "ebd2bfee-ecba-47b7-a33c-017d0131879d",
        "scope":     "7daee810-3f78-40c4-84c2-7a199428de18/.default openid offline_access",
        "grant":     "refresh_token",
        "hostname":  "equinorswedev.energy.azure.com",
        "partition": "dev",
        "legal_tag": "dev-equinor-private-default",
        "owners":    "data.default.owners@dev.dataservices.energy",
        "viewers":   "data.default.viewers@dev.dataservices.energy",
        "countries": "NO",
    },
    "preship": {
        "label":     "MS pre-ship M26",
        "tenant_id": "58975fd3-4977-44d0-bea8-37af0baac100",
        "client_id": None,   # from env: PRESHIP_CLIENT_ID
        "scope":     None,   # derived from client_id
        "grant":     "client_credentials",
        "hostname":  "osdu-ship.msft-osdu-test.org",
        "partition": "opendes",
        "legal_tag": "opendes-RDDMS-LegalTag",
        "owners":    "data.default.owners@opendes.contoso.com",
        "viewers":   "data.default.viewers@opendes.contoso.com",
        "countries": "US",
    },
}

# Aliases so existing INSTANCE_ names work too
ALIASES = {"eqndev": "swedev"}


def discover_k8s_instances(k8s_env: Dict[str, str]) -> Dict[str, Dict[str, str]]:
    """Discover INSTANCE_<NAME>_* entries from the k8s env dict.

    Returns a dict keyed by lowercase instance name, with sub-dict of fields:
      tenant_id, client_id, client_secret, scope, refresh_token, hostname, ...
    """
    seen: set[str] = set()
    for key in k8s_env:
        if key.startswith("INSTANCE_") and key.count("_") >= 2:
            parts = key.split("_", 2)  # INSTANCE, NAME, FIELD
            seen.add(parts[1].lower())

    instances: Dict[str, Dict[str, str]] = {}
    for name in sorted(seen):
        prefix = f"INSTANCE_{name.upper()}_"
        entry: Dict[str, str] = {}
        for k, v in k8s_env.items():
            if k.startswith(prefix) and v:
                field = k[len(prefix):].lower()
                entry[field] = v
        if entry:
            instances[name] = entry

    return instances


def _resolve_k8s_instance(name: str, k8s_env: Dict[str, str]) -> Optional[Dict[str, str]]:
    """Resolve a single instance from k8s env. Returns None if not found."""
    instances = discover_k8s_instances(k8s_env)
    inst = instances.get(name.lower())
    if not inst:
        return None

    # Determine grant type from available credentials
    has_rt = bool(inst.get("refresh_token"))
    has_cs = bool(inst.get("client_secret"))

    return {
        "tenant_id":     inst.get("tenant_id", ""),
        "client_id":     inst.get("client_id", ""),
        "client_secret": inst.get("client_secret", ""),
        "scope":         inst.get("scope", ""),
        "refresh_token": inst.get("refresh_token", ""),
        "hostname":      inst.get("hostname", ""),
        "partition":     inst.get("data_partition_id", ""),
        "grant":         "refresh_token" if has_rt else ("client_credentials" if has_cs else "none"),
        "label":         f"k8s/{name}",
    }


# ── Token minting ────────────────────────────────────────────────────────── #

def _mint_from_config(inst: Dict[str, Any], *, verbose: bool = False) -> str:
    """Mint a token from a resolved instance config dict (grant-agnostic)."""
    tenant = inst["tenant_id"]
    if not tenant:
        raise RuntimeError("No tenant_id configured")
    url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"

    grant = inst.get("grant", "none")

    if grant == "refresh_token":
        rt = inst.get("refresh_token", "")
        if not rt:
            raise RuntimeError("refresh_token grant selected but no refresh_token available")
        scope = inst.get("scope") or f"{inst['client_id']}/.default openid offline_access"
        form = {
            "grant_type":    "refresh_token",
            "client_id":     inst["client_id"],
            "refresh_token": rt,
            "scope":         scope,
        }
        label = "refresh_token"

    elif grant == "client_credentials":
        client_id = inst.get("client_id", "")
        secret    = inst.get("client_secret", "")
        if not client_id or not secret:
            raise RuntimeError("client_credentials grant but missing client_id or client_secret")
        scope = inst.get("scope") or f"{client_id}/.default"
        form = {
            "grant_type":    "client_credentials",
            "client_id":     client_id,
            "client_secret": secret,
            "scope":         scope,
        }
        label = "client_credentials"
    else:
        raise RuntimeError(f"No usable credentials (grant={grant})")

    r = httpx.post(url, data=form, timeout=30)
    if not r.is_success:
        raise RuntimeError(f"Auth failed ({label}): {r.status_code}\n{r.text[:500]}")

    data = r.json()
    token = data.get("access_token")
    if not token:
        raise RuntimeError(f"No access_token in response: {list(data.keys())}")

    if verbose:
        exp = data.get("expires_in", "?")
        lbl = inst.get("label", "?")
        print(f"# {lbl} ({label}) - expires_in={exp}s", file=sys.stderr)

    return token


def mint_token(name: str, *, verbose: bool = False, from_k8s: bool = False,
               k8s_dir: Optional[Path] = None) -> str:
    """Mint an access token for the named instance.

    Resolution order:
      1. If ``from_k8s`` - read k8s/secret.yaml + configmap.yaml
      2. Env vars with INSTANCE_<NAME>_* pattern
      3. Legacy hard-coded INSTANCES dict + old env var names
    """
    canonical = ALIASES.get(name.lower(), name.lower())

    # ── 1. k8s YAML source ──
    if from_k8s:
        k8s_env = load_k8s_env(k8s_dir)
        resolved = _resolve_k8s_instance(canonical, k8s_env)
        # Also try the original name if alias didn't match
        if not resolved and canonical != name.lower():
            resolved = _resolve_k8s_instance(name.lower(), k8s_env)
        if resolved:
            return _mint_from_config(resolved, verbose=verbose)
        # Fall through to env vars
        if verbose:
            print(f"# k8s: no INSTANCE_{canonical.upper()}_* found, trying env", file=sys.stderr)

    # ── 2. Env vars with INSTANCE_<NAME>_* pattern ──
    prefix = f"INSTANCE_{canonical.upper()}_"
    env_tenant = os.environ.get(f"{prefix}TENANT_ID", "")
    env_client = os.environ.get(f"{prefix}CLIENT_ID", "")
    if env_tenant and env_client:
        env_inst = {
            "tenant_id":     env_tenant,
            "client_id":     env_client,
            "client_secret": os.environ.get(f"{prefix}CLIENT_SECRET", ""),
            "scope":         os.environ.get(f"{prefix}SCOPE", ""),
            "refresh_token": os.environ.get(f"{prefix}REFRESH_TOKEN", ""),
            "hostname":      os.environ.get(f"{prefix}HOSTNAME", ""),
            "partition":     os.environ.get(f"{prefix}DATA_PARTITION_ID", ""),
            "label":         f"env/{canonical}",
        }
        has_rt = bool(env_inst["refresh_token"])
        has_cs = bool(env_inst["client_secret"])
        env_inst["grant"] = "refresh_token" if has_rt else ("client_credentials" if has_cs else "none")
        return _mint_from_config(env_inst, verbose=verbose)

    # ── 3. Legacy hard-coded defaults ──
    if canonical not in INSTANCES:
        available = list(INSTANCES.keys())
        # Also show k8s instances if available
        try:
            k8s_names = list(discover_k8s_instances(load_k8s_env()).keys())
            available.extend(k8s_names)
        except Exception:
            pass
        sys.exit(f"Unknown instance '{name}'. Available: {', '.join(sorted(set(available)))}")

    inst = dict(INSTANCES[canonical])  # copy

    if inst["grant"] == "refresh_token":
        refresh = os.environ.get("SWEDEV_REFRESH_TOKEN", "")
        if not refresh:
            sys.exit("ERROR: SWEDEV_REFRESH_TOKEN not set.\n"
                     "  Add to ~/.bashrc:  export SWEDEV_REFRESH_TOKEN='...'\n"
                     "  Or use:  python demo/gettoken.py eqndev --from-k8s")
        inst["refresh_token"] = refresh

    elif inst["grant"] == "client_credentials":
        client_id = os.environ.get("PRESHIP_CLIENT_ID", inst["client_id"] or "")
        secret    = os.environ.get("PRESHIP_CLIENT_SECRET", "")
        if not client_id or not secret:
            sys.exit("ERROR: PRESHIP_CLIENT_ID and/or PRESHIP_CLIENT_SECRET not set.\n"
                     "  Add to ~/.bashrc:\n"
                     "    export PRESHIP_CLIENT_ID='...'\n"
                     "    export PRESHIP_CLIENT_SECRET='...'\n"
                     "  Or use:  python demo/gettoken.py preship --from-k8s")
        inst["client_id"] = client_id
        inst["scope"] = inst["scope"] or f"{client_id}/.default"
        inst["client_secret"] = secret

    return _mint_from_config(inst, verbose=verbose)


# ── ETP URL helper ───────────────────────────────────────────────────────── #

def etp_url(name: str) -> str:
    """Return the wss:// ETP endpoint for the named instance."""
    name = ALIASES.get(name.lower(), name.lower())
    host = INSTANCES[name]["hostname"]
    return f"wss://{host}/api/reservoir-ddms-etp/v2/"


def partition(name: str) -> str:
    """Return the data partition for the named instance."""
    name = ALIASES.get(name.lower(), name.lower())
    return INSTANCES[name]["partition"]


# ── CLI ──────────────────────────────────────────────────────────────────── #

def list_instances(k8s_dir: Optional[Path] = None) -> List[Dict[str, str]]:
    """Return a list of all discoverable instances with their source."""
    result: List[Dict[str, str]] = []

    # Hard-coded
    for name in sorted(INSTANCES):
        result.append({"name": name, "source": "builtin", "grant": INSTANCES[name]["grant"]})

    # k8s YAML
    try:
        k8s_env = load_k8s_env(k8s_dir)
        for name, fields in discover_k8s_instances(k8s_env).items():
            has_rt = bool(fields.get("refresh_token"))
            has_cs = bool(fields.get("client_secret"))
            grant = "refresh_token" if has_rt else ("client_credentials" if has_cs else "none")
            result.append({"name": name, "source": "k8s", "grant": grant})
    except Exception:
        pass

    # Env vars
    seen: set[str] = set()
    for key in os.environ:
        if key.startswith("INSTANCE_") and key.count("_") >= 2:
            parts = key.split("_", 2)
            seen.add(parts[1].lower())
    for name in sorted(seen):
        prefix = f"INSTANCE_{name.upper()}_"
        has_rt = bool(os.environ.get(f"{prefix}REFRESH_TOKEN"))
        has_cs = bool(os.environ.get(f"{prefix}CLIENT_SECRET"))
        grant = "refresh_token" if has_rt else ("client_credentials" if has_cs else "none")
        result.append({"name": name, "source": "env", "grant": grant})

    # Deduplicate by name (prefer k8s > env > builtin)
    priority = {"k8s": 0, "env": 1, "builtin": 2}
    seen_names: Dict[str, Dict[str, str]] = {}
    for item in result:
        n = item["name"]
        if n not in seen_names or priority.get(item["source"], 9) < priority.get(seen_names[n]["source"], 9):
            seen_names[n] = item
    return sorted(seen_names.values(), key=lambda x: x["name"])


def main():
    ap = argparse.ArgumentParser(
        description="Mint an OSDU access token (env, k8s secrets, or built-in config)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  python demo/gettoken.py swedev                  # using env vars
  python demo/gettoken.py eqndev --from-k8s      # using k8s/secret.yaml
  python demo/gettoken.py --list                  # show all instances
  export TOKEN=$(python demo/gettoken.py swedev)
  eval "$(python demo/gettoken.py --export)"
""",
    )
    ap.add_argument("instance", nargs="?", default=None,
                    help="Instance name: swedev | preship | eqndev | ... (default: swedev)")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="Print metadata to stderr")
    ap.add_argument("--from-k8s", action="store_true",
                    help="Read secrets from k8s/secret.yaml + configmap.yaml")
    ap.add_argument("--k8s-dir", type=Path, default=None,
                    help="Override k8s directory path (default: repo/k8s/)")
    ap.add_argument("--list", action="store_true",
                    help="List all discoverable instances and exit")
    ap.add_argument("--export", action="store_true",
                    help="Print bash export lines for ALL instances "
                         "(eval-friendly)")
    ap.add_argument("--json", action="store_true",
                    help="Print JSON with token + metadata")
    args = ap.parse_args()

    if args.list:
        instances = list_instances(args.k8s_dir)
        if not instances:
            print("No instances found.", file=sys.stderr)
            sys.exit(1)
        print(f"{'NAME':<16} {'SOURCE':<10} {'GRANT'}")
        print(f"{'─'*16} {'─'*10} {'─'*20}")
        for inst in instances:
            print(f"{inst['name']:<16} {inst['source']:<10} {inst['grant']}")
        return

    if args.export:
        lines = []
        for name in INSTANCES:
            try:
                tok = mint_token(name, verbose=True, from_k8s=args.from_k8s,
                                 k8s_dir=args.k8s_dir)
                var = f"{name.upper()}_TOKEN"
                lines.append(f"export {var}='{tok}'")
            except (SystemExit, RuntimeError) as e:
                print(f"# skip {name}: {e}", file=sys.stderr)
        print("\n".join(lines))
        return

    inst_name = args.instance or "swedev"
    try:
        token = mint_token(inst_name, verbose=args.verbose,
                           from_k8s=args.from_k8s, k8s_dir=args.k8s_dir)
    except RuntimeError as e:
        sys.exit(f"ERROR: {e}")

    if args.json:
        canonical = ALIASES.get(inst_name.lower(), inst_name.lower())
        print(json.dumps({
            "instance":  canonical,
            "token":     token,
            "etp_url":   etp_url(canonical),
            "partition": partition(canonical),
        }, indent=2))
    else:
        print(token)


if __name__ == "__main__":
    main()
