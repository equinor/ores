"""
auth.py - Self-contained authentication for OSDU instances.

Supports multiple instances with full secret resolution chain:
  1. Explicit token (--token or OSDU_TOKEN env var)
  2. k8s/secret.yaml + k8s/configmap.yaml (ores repo)
  3. Environment variables (INSTANCE_<NAME>_*)
  4. ~/.osdu/config.json (multi-instance config file)

Grant types (auto-detected):
  - refresh_token  (when refresh_token is available)
  - client_credentials (when client_secret is available)

Token caching within process lifetime (avoids re-minting on every call).

Usage:
    from demo.scripts.auth import get_token, get_headers, list_instances

    # One-call token
    token = get_token("eqndev")

    # Ready-to-use headers
    headers = get_headers("eqndev")

    # Full instance config (for OsduClient)
    from demo.scripts.auth import resolve_instance
    instance = resolve_instance("eqndev")
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import httpx
except ImportError:
    sys.exit("Missing httpx - pip install httpx")

from .config import OsduInstance, load_config, _parse_k8s_yaml


# ── Paths ────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent  # ores/
K8S_DIR = REPO_ROOT / "k8s"
DEFAULT_CONFIG = Path.home() / ".osdu" / "config.json"

# ── Instance aliases (match existing ores conventions) ───────────────────
ALIASES: Dict[str, str] = {
    "eqndev": "eqndev",
    "swedev": "eqndev",
    "preship": "preship",
    "oresdev": "oresdev",
}

# ── Token cache (per-process, keyed by instance name) ────────────────────
_token_cache: Dict[str, Tuple[str, float]] = {}
TOKEN_CACHE_BUFFER = 300  # renew 5 min before expiry


# ═══════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════

def get_token(
    instance_name: str = "eqndev",
    *,
    token: Optional[str] = None,
    verbose: bool = True,
) -> str:
    """
    Get an access token for the named instance. Cached within process.

    Priority:
      1. Explicit token argument
      2. OSDU_TOKEN env var
      3. Mint via configured credentials (refresh_token or client_credentials)
    """
    # Explicit token
    if token:
        return token
    env_token = os.environ.get("OSDU_TOKEN", "").strip()
    if env_token:
        return env_token

    # Check cache
    canonical = ALIASES.get(instance_name.lower(), instance_name.lower())
    cached = _token_cache.get(canonical)
    if cached and time.time() < cached[1]:
        return cached[0]

    # Resolve instance and mint
    inst_cfg = _resolve_instance_config(canonical)
    access_token = _mint_token(inst_cfg, verbose=verbose)

    # Cache
    _token_cache[canonical] = (access_token, time.time() + 3000)
    return access_token


def get_headers(
    instance_name: str = "eqndev",
    *,
    token: Optional[str] = None,
) -> Dict[str, str]:
    """Return ready-to-use OSDU API headers with fresh Bearer token."""
    inst_cfg = _resolve_instance_config(
        ALIASES.get(instance_name.lower(), instance_name.lower())
    )
    tok = get_token(instance_name, token=token)
    return {
        "Authorization": f"Bearer {tok}",
        "Content-Type": "application/json",
        "data-partition-id": inst_cfg.get("partition", ""),
    }


def resolve_instance(
    instance_name: str = "eqndev",
    *,
    token: Optional[str] = None,
) -> OsduInstance:
    """
    Resolve a fully-populated OsduInstance ready for use with OsduClient.

    Combines config resolution + token minting into one call.
    """
    canonical = ALIASES.get(instance_name.lower(), instance_name.lower())
    cfg = _resolve_instance_config(canonical)

    return OsduInstance(
        name=canonical,
        host=cfg.get("host", ""),
        partition=cfg.get("partition", ""),
        legal_tag=cfg.get("legal_tag", ""),
        owners=cfg.get("owners", []),
        viewers=cfg.get("viewers", []),
        countries=cfg.get("countries", ["NO"]),
        tenant_id=cfg.get("tenant_id", ""),
        client_id=cfg.get("client_id", ""),
        scope=cfg.get("scope", ""),
        refresh_token=cfg.get("refresh_token", ""),
        client_secret=cfg.get("client_secret", ""),
    )


def list_instances() -> List[str]:
    """List available instance names from all config sources."""
    instances: set = set()

    # From k8s YAML
    if K8S_DIR.exists():
        env = {}
        for f in ("configmap.yaml", "secret.yaml"):
            p = K8S_DIR / f
            if p.exists():
                env.update(_parse_k8s_yaml(p))
        for key in env:
            if key.startswith("INSTANCE_") and key.count("_") >= 2:
                # INSTANCE_EQNDEV_HOSTNAME → eqndev
                parts = key.split("_")
                instances.add(parts[1].lower())

    # From env vars
    for key in os.environ:
        if key.startswith("INSTANCE_") and key.count("_") >= 2:
            parts = key.split("_")
            instances.add(parts[1].lower())

    # From config file
    import json
    if DEFAULT_CONFIG.exists():
        try:
            data = json.loads(DEFAULT_CONFIG.read_text("utf-8"))
            for name in data.get("instances", {}):
                instances.add(name.lower())
        except (json.JSONDecodeError, OSError):
            pass

    # Add aliases
    instances.update(ALIASES.keys())
    return sorted(instances)


# ═══════════════════════════════════════════════════════════════════════════
# Internal: Instance config resolution
# ═══════════════════════════════════════════════════════════════════════════

def _resolve_instance_config(name: str) -> Dict[str, Any]:
    """
    Resolve instance config from all available sources.

    Chain: k8s YAML → env vars (INSTANCE_<NAME>_*) → config file
    """
    # 1. k8s YAML (ores repo)
    fields = _resolve_from_k8s(name)
    if fields:
        return _normalize_fields(fields, source="k8s", name=name)

    # 2. Environment variables (INSTANCE_<NAME>_*)
    fields = _resolve_from_instance_env(name)
    if fields:
        return _normalize_fields(fields, source="env", name=name)

    # 3. Config JSON file (~/.osdu/config.json)
    fields = _resolve_from_config_file(name)
    if fields:
        return _normalize_fields(fields, source="config-file", name=name)

    raise RuntimeError(
        f"No config found for instance '{name}'.\n"
        f"Configure via:\n"
        f"  • k8s/secret.yaml + k8s/configmap.yaml\n"
        f"  • INSTANCE_{name.upper()}_* env vars\n"
        f"  • ~/.osdu/config.json\n"
        f"\nOr pass --token directly."
    )


def _resolve_from_k8s(name: str) -> Optional[Dict[str, str]]:
    """Try k8s YAML files."""
    if not K8S_DIR.exists():
        return None
    env: Dict[str, str] = {}
    for f in ("configmap.yaml", "secret.yaml"):
        p = K8S_DIR / f
        if p.exists():
            env.update(_parse_k8s_yaml(p))

    prefix = f"INSTANCE_{name.upper()}_"
    fields = {k[len(prefix):].lower(): v for k, v in env.items()
              if k.startswith(prefix) and v}
    if not fields.get("tenant_id") and not fields.get("client_id"):
        return None
    return fields


def _resolve_from_instance_env(name: str) -> Optional[Dict[str, str]]:
    """Try INSTANCE_<NAME>_* environment variables."""
    prefix = f"INSTANCE_{name.upper()}_"
    fields = {k[len(prefix):].lower(): v for k, v in os.environ.items()
              if k.startswith(prefix) and v}
    if not fields.get("tenant_id") and not fields.get("client_id"):
        return None
    return fields


def _resolve_from_config_file(name: str) -> Optional[Dict[str, Any]]:
    """Try ~/.osdu/config.json."""
    import json
    if not DEFAULT_CONFIG.exists():
        return None
    try:
        data = json.loads(DEFAULT_CONFIG.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    instances = data.get("instances", {})
    if name in instances:
        return instances[name]
    # Flat config as fallback for "default"
    if name == "default" and "host" in data:
        return {k: v for k, v in data.items() if k != "instances"}
    return None


def _normalize_fields(fields: Dict[str, Any], source: str, name: str) -> Dict[str, Any]:
    """Normalize raw config fields into a consistent structure."""
    # Host
    host = fields.get("hostname") or fields.get("host", "")
    if host and not host.startswith("http"):
        host = f"https://{host}"

    # Partition
    partition = fields.get("data_partition_id") or fields.get("partition", "")

    # Auth fields
    tenant_id = fields.get("tenant_id", "")
    client_id = fields.get("client_id", "")
    scope = fields.get("scope", "")
    refresh_token = fields.get("refresh_token", "")
    client_secret = fields.get("client_secret", "")

    # Grant type detection
    grant = "none"
    if refresh_token:
        grant = "refresh_token"
    elif client_secret:
        grant = "client_credentials"

    # Governance
    legal_tag = fields.get("default_legal_tag") or fields.get("legal_tag", "")
    owners_raw = fields.get("default_owners") or fields.get("owners", "")
    viewers_raw = fields.get("default_viewers") or fields.get("viewers", "")
    countries_raw = fields.get("default_countries") or fields.get("countries", "NO")

    if isinstance(owners_raw, str):
        owners = [x.strip() for x in owners_raw.split(",") if x.strip()]
    else:
        owners = owners_raw or []
    if isinstance(viewers_raw, str):
        viewers = [x.strip() for x in viewers_raw.split(",") if x.strip()]
    else:
        viewers = viewers_raw or []
    if isinstance(countries_raw, str):
        countries = [x.strip() for x in countries_raw.split(",") if x.strip()]
    else:
        countries = countries_raw or ["NO"]

    return {
        "name": name,
        "source": source,
        "host": host,
        "partition": partition,
        "tenant_id": tenant_id,
        "client_id": client_id,
        "scope": scope,
        "refresh_token": refresh_token,
        "client_secret": client_secret,
        "grant": grant,
        "legal_tag": legal_tag,
        "owners": owners,
        "viewers": viewers,
        "countries": countries,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Internal: Token minting
# ═══════════════════════════════════════════════════════════════════════════

def _mint_token(inst_cfg: Dict[str, Any], *, verbose: bool = True) -> str:
    """Mint an access token using the resolved instance config."""
    tenant = inst_cfg.get("tenant_id", "")
    if not tenant:
        raise RuntimeError(
            f"No tenant_id for instance '{inst_cfg.get('name', '?')}'.\n"
            f"Source: {inst_cfg.get('source', '?')}"
        )

    url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
    grant = inst_cfg.get("grant", "none")
    client_id = inst_cfg["client_id"]

    if grant == "refresh_token":
        form = {
            "grant_type": "refresh_token",
            "client_id": client_id,
            "refresh_token": inst_cfg["refresh_token"],
            "scope": inst_cfg.get("scope") or f"{client_id}/.default openid offline_access",
        }
        # Confidential clients require client_secret even for refresh_token
        if inst_cfg.get("client_secret"):
            form["client_secret"] = inst_cfg["client_secret"]
    elif grant == "client_credentials":
        form = {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": inst_cfg["client_secret"],
            "scope": inst_cfg.get("scope") or f"{client_id}/.default",
        }
    else:
        raise RuntimeError(
            f"No usable credentials for '{inst_cfg.get('name', '?')}' (grant={grant}).\n"
            f"Set refresh_token or client_secret."
        )

    resp = httpx.post(url, data=form, timeout=30)
    if not resp.is_success:
        raise RuntimeError(
            f"Token mint failed ({resp.status_code}) for '{inst_cfg.get('name', '?')}':\n"
            f"  {resp.text[:300]}"
        )

    data = resp.json()
    access_token = data.get("access_token")
    if not access_token:
        raise RuntimeError(f"No access_token in response: {list(data.keys())}")

    if verbose:
        exp = data.get("expires_in", "?")
        print(
            f"  ✓ token ({inst_cfg.get('source', '?')}/{inst_cfg['name']}, "
            f"{grant}) expires_in={exp}s",
            file=sys.stderr,
        )

    return access_token


def _mint_full(inst_cfg: Dict[str, Any], *, verbose: bool = True) -> Dict[str, Any]:
    """Mint token and return full response (for token rotation)."""
    tenant = inst_cfg.get("tenant_id", "")
    if not tenant:
        raise RuntimeError(f"No tenant_id for instance '{inst_cfg.get('name', '?')}'")

    url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
    grant = inst_cfg.get("grant", "none")
    if grant != "refresh_token":
        raise RuntimeError("Token rotation only works with refresh_token grant")

    form = {
        "grant_type": "refresh_token",
        "client_id": inst_cfg["client_id"],
        "refresh_token": inst_cfg["refresh_token"],
        "scope": inst_cfg.get("scope") or f"{inst_cfg['client_id']}/.default openid offline_access",
    }
    if inst_cfg.get("client_secret"):
        form["client_secret"] = inst_cfg["client_secret"]

    resp = httpx.post(url, data=form, timeout=30)
    if not resp.is_success:
        raise RuntimeError(f"Token rotation failed ({resp.status_code}): {resp.text[:300]}")

    data = resp.json()
    if not data.get("access_token"):
        raise RuntimeError(f"No access_token in response: {list(data.keys())}")

    if verbose:
        exp = data.get("expires_in", "?")
        has_new_rt = "refresh_token" in data
        print(
            f"  ✓ token ({inst_cfg.get('source', '?')}/{inst_cfg['name']}, "
            f"{grant}) expires_in={exp}s  new_rt={'yes' if has_new_rt else 'no'}",
            file=sys.stderr,
        )
    return data


# ═══════════════════════════════════════════════════════════════════════════
# Public: Token rotation
# ═══════════════════════════════════════════════════════════════════════════

def rotate_token(
    instance_name: str = "eqndev",
    *,
    verbose: bool = True,
) -> Dict[str, str]:
    """
    Exchange current refresh_token for new access_token + refresh_token.

    Returns dict: {access_token, refresh_token (new), expires_in, rotated}.
    Caller must persist the new refresh_token.
    """
    canonical = ALIASES.get(instance_name.lower(), instance_name.lower())
    cfg = _resolve_instance_config(canonical)
    data = _mint_full(cfg, verbose=verbose)

    new_rt = data.get("refresh_token", cfg.get("refresh_token", ""))
    return {
        "access_token": data["access_token"],
        "refresh_token": new_rt,
        "expires_in": str(data.get("expires_in", "3600")),
        "rotated": str(new_rt != cfg.get("refresh_token", "")).lower(),
    }
