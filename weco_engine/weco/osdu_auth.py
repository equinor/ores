"""
weco.osdu_auth — OSDU / RDDMS authentication helper
=====================================================

Provides ``get_token()`` for acquiring an access token from an OSDU
platform.  Secrets are resolved in order:

1. Environment variables (``OSDU_TOKEN``, ``OSDU_CLIENT_ID``,
   ``OSDU_CLIENT_SECRET``, ``OSDU_REFRESH_TOKEN``, ``OSDU_TOKEN_URL``).
2. Azure CLI token cache (``az account get-access-token``).

Usage::

    from weco.osdu_auth import get_token, osdu_headers

    token = get_token()
    headers = osdu_headers(token, data_partition="equinor-eqndev")
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ── token cache ──────────────────────────────────────────────────────────
_token_cache: Dict[str, tuple] = {}  # key → (token, expiry_ts)
_CACHE_MARGIN = 120  # seconds before expiry to trigger refresh


def get_token(
    *,
    token_url: Optional[str] = None,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
    refresh_token: Optional[str] = None,
    scope: Optional[str] = None,
) -> str:
    """Acquire an OSDU access token.

    Parameters are resolved from environment variables if not provided:

    * ``OSDU_TOKEN`` — static bearer token (skips grant flow)
    * ``OSDU_TOKEN_URL`` / ``OSDU_CLIENT_ID`` / ``OSDU_CLIENT_SECRET``
    * ``OSDU_REFRESH_TOKEN``
    * ``OSDU_SCOPE``

    Fallback: Azure CLI ``az account get-access-token``.
    """
    # 1. Static token
    static = os.environ.get("OSDU_TOKEN", "")
    if static:
        return static

    # 2. OAuth2 grant
    tok_url = token_url or os.environ.get("OSDU_TOKEN_URL", "")
    cid = client_id or os.environ.get("OSDU_CLIENT_ID", "")
    csec = client_secret or os.environ.get("OSDU_CLIENT_SECRET", "")
    rtok = refresh_token or os.environ.get("OSDU_REFRESH_TOKEN", "")
    scp = scope or os.environ.get("OSDU_SCOPE", "")

    if tok_url and cid:
        cache_key = f"{tok_url}:{cid}"
        cached = _token_cache.get(cache_key)
        if cached:
            tok, exp = cached
            if time.time() < exp - _CACHE_MARGIN:
                return tok

        try:
            import httpx
        except ImportError:
            raise ImportError("httpx is required for OSDU auth — pip install httpx")

        data: Dict[str, str] = {"client_id": cid}
        if scp:
            data["scope"] = scp

        if rtok:
            data["grant_type"] = "refresh_token"
            data["refresh_token"] = rtok
        elif csec:
            data["grant_type"] = "client_credentials"
            data["client_secret"] = csec
        else:
            raise ValueError(
                "OSDU auth requires either OSDU_CLIENT_SECRET or "
                "OSDU_REFRESH_TOKEN"
            )

        resp = httpx.post(tok_url, data=data, timeout=30)
        resp.raise_for_status()
        body = resp.json()
        tok = body["access_token"]
        exp = time.time() + body.get("expires_in", 3600)
        _token_cache[cache_key] = (tok, exp)
        return tok

    # 3. Azure CLI fallback
    try:
        result = subprocess.run(
            ["az", "account", "get-access-token", "--output", "json"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            body = json.loads(result.stdout)
            return body.get("accessToken", "")
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
        pass

    raise RuntimeError(
        "Cannot acquire OSDU token.  Set OSDU_TOKEN, or configure "
        "OSDU_TOKEN_URL + OSDU_CLIENT_ID + OSDU_CLIENT_SECRET, or "
        "log in via 'az login'."
    )


def osdu_headers(
    token: str,
    data_partition: str = "",
    content_type: str = "application/json",
) -> Dict[str, str]:
    """Build standard OSDU request headers."""
    h: Dict[str, str] = {
        "Authorization": f"Bearer {token}",
        "Content-Type": content_type,
    }
    if data_partition:
        h["data-partition-id"] = data_partition
    return h


def osdu_config_from_env() -> Dict[str, Any]:
    """Return an OSDU connection config dict from environment variables.

    Environment variables:
        ``OSDU_URL``, ``OSDU_DATA_PARTITION``, ``OSDU_DATASPACE``
    """
    return {
        "url": os.environ.get("OSDU_URL", ""),
        "data_partition": os.environ.get("OSDU_DATA_PARTITION", ""),
        "dataspace": os.environ.get("OSDU_DATASPACE", ""),
        "token_url": os.environ.get("OSDU_TOKEN_URL", ""),
        "client_id": os.environ.get("OSDU_CLIENT_ID", ""),
    }
