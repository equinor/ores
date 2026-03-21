"""Shared helpers for drogon demo scripts.

Centralises load_json, SEGMENT_NAMES, and .env parsing so they live in one
place rather than being copy-pasted across every generator / ingest script.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── JSON loader ─────────────────────────────────────────────────────────
def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ── Segment display names (Valysar / Drogon) ───────────────────────────
SEGMENT_NAMES: Dict[str, str] = {
    "WestLowland":  "West Lowland",
    "CentralSouth": "Central South",
    "CentralNorth": "Central North",
    "NorthHorst":   "North Horst",
    "CentralRamp":  "Central Ramp",
    "CentralHorst": "Central Horst",
    "EastLowland":  "East Lowland",
}


# ── .env file parsing (Variant A — used by drogon ingest scripts) ──────
def parse_dotenv(path: Path) -> Dict[str, str]:
    """Parse a KEY=VALUE .env file into a dict, stripping quotes."""
    vals: Dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in ('"', "'"):
            v = v[1:-1]
        vals[k] = v
    return vals


def first_env(env: Dict[str, str], keys: List[str]) -> Optional[str]:
    """Return first non-empty value for any of *keys* in *env*."""
    for k in keys:
        v = (env.get(k) or "").strip()
        if v:
            return v
    return None


def load_env(paths: List[str]) -> Dict[str, str]:
    """Merge one or more .env files and return normalised auth/host dict.

    Keys returned: refresh_token, tenant, client_id, scope, host, partition.
    Raises SystemExit if any required key is missing.
    """
    merged: Dict[str, str] = {}
    for p in paths:
        fp = Path(p).expanduser().resolve()
        if not fp.exists():
            raise SystemExit(f"env file not found: {p}")
        merged.update(parse_dotenv(fp))

    env: Dict[str, str] = {}
    env["refresh_token"] = first_env(merged, ["refresh_token", "REFRESH_TOKEN"]) or ""
    env["tenant"]        = first_env(merged, ["OSDU_TENANT_ID", "AZURE_TENANT_ID"]) or ""
    env["client_id"]     = first_env(merged, ["OSDU_CLIENT_ID", "AZURE_CLIENT_ID"]) or ""
    env["scope"]         = first_env(merged, ["OSDU_SCOPE", "AZURE_SCOPE"]) or ""
    host                 = first_env(merged, ["OSDU_HOST", "OSDU_BASE_URL"]) or ""
    if host and not host.startswith("http"):
        host = "https://" + host.lstrip("/")
    env["host"]          = host
    env["partition"]     = first_env(merged, ["OSDU_PARTITION", "DATA_PARTITION_ID"]) or ""

    missing = [k for k in ("refresh_token", "tenant", "client_id", "scope", "host", "partition") if not env[k]]
    if missing:
        raise SystemExit(f"Missing keys in .env: {', '.join(missing)}")
    return env
