"""
app/common.py - Shared helpers used across app modules.

Consolidates duplicated utilities (access_token extraction,
reservoir search, display formatting, RDDMS response normalisation)
into a single importable location.
"""
from __future__ import annotations

import asyncio
import json
import logging
import urllib.parse
from typing import Any, Dict, List

import httpx
from fastapi import HTTPException, Request

from fastapi.responses import JSONResponse as _JSONResponse

from . import osdu
from .cache import cached_call

log = logging.getLogger("rddms-admin.common")


# ──────────────────────────────────────────────────────────────────────────────
# Auth helper
# ──────────────────────────────────────────────────────────────────────────────

def access_token(request: Request) -> str:
    """Extract the access token set by the auth middleware.

    Raises 401 if no token is available - use only in routes
    that require authentication (not in public paths).
    """
    at = getattr(request.state, "access_token", None)
    if not at:
        raise HTTPException(401, "Authentication required")
    return at


# ──────────────────────────────────────────────────────────────────────────────
# Display formatting (shared by Jinja templates + search/keys routers)
# ──────────────────────────────────────────────────────────────────────────────

def friendly_value(v: Any, max_str: int = 400) -> str:
    """Convert a single value to a human-friendly string."""
    if v is None:
        return ""
    if isinstance(v, (str, int, float, bool)):
        s = str(v)
        return s if len(s) <= max_str else s[:max_str] + "…"
    if isinstance(v, dict):
        parts = []
        for dk, dv in v.items():
            sv = friendly_value(dv, max_str=80)
            parts.append(f"{dk}: {sv}")
        s = "; ".join(parts)
        return s if len(s) <= max_str else s[:max_str] + "…"
    if isinstance(v, list):
        return friendly_list(v, max_str)
    return str(v)[:max_str]


def friendly_list(lst: list, max_str: int = 400) -> str:
    """Format a list for display."""
    if not lst:
        return ""
    if all(isinstance(x, (str, int, float, bool, type(None))) for x in lst):
        return ", ".join(str(x) for x in lst)
    if all(isinstance(x, dict) for x in lst):
        items = []
        for d in lst:
            parts = [f"{k}: {friendly_value(dv, 80)}" for k, dv in d.items()]
            items.append("; ".join(parts))
        s = " │ ".join(items)
        return s if len(s) <= max_str else s[:max_str] + "…"
    s = ", ".join(friendly_value(x, 80) for x in lst)
    return s if len(s) <= max_str else s[:max_str] + "…"


def pretty_val(val: Any) -> str:
    """Jinja filter: prettify metadata values that may contain JSON."""
    if val is None:
        return "-"
    s = str(val)
    if s.startswith(("[", "{")):
        try:
            obj = json.loads(s)
            return friendly_value(obj, 600)
        except (json.JSONDecodeError, ValueError):
            pass
    return s


# ──────────────────────────────────────────────────────────────────────────────
# RDDMS response normalisation
# ──────────────────────────────────────────────────────────────────────────────

def normalize_obj(raw: Any, uuid: str) -> Dict[str, Any]:
    """Pick the right dict when the RDDMS returns a list.

    Warns when the exact UUID isn't found and a fallback is used.
    """
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, list):
        for it in raw:
            if isinstance(it, dict):
                uid = it.get("Uuid") or it.get("UUID") or it.get("uuid")
                if uid and str(uid).lower() == (uuid or "").lower():
                    return it
        for it in raw:
            if isinstance(it, dict):
                log.warning("normalize_obj: UUID %s not found, using first dict", uuid)
                return it
    return {}


def sanitize_upstream_error(response) -> str:
    """Extract a clean, user-safe error message from an upstream HTTP response.

    Tries to parse a JSON body and extract ``message``, ``detail``, or
    ``error`` fields.  Falls back to the HTTP reason phrase if the body
    is HTML or unparseable.  Never returns raw HTML.
    """
    body = response.text or ""
    # Try JSON first
    if body.strip().startswith("{"):
        try:
            import json as _json
            j = _json.loads(body)
            msg = (
                j.get("message")
                or j.get("detail")
                or j.get("error")
                or j.get("reason")
                or ""
            )
            if isinstance(msg, dict):
                msg = msg.get("message") or msg.get("detail") or str(msg)
            if msg:
                return str(msg)[:500]
        except Exception:
            pass
    # Reject HTML bodies
    if "<html" in body[:200].lower() or "<!doctype" in body[:200].lower():
        return f"{response.status_code} {response.reason_phrase}"
    # Plain text fallback (capped)
    clean = body.strip()[:300]
    return clean if clean else f"{response.status_code} {response.reason_phrase}"


def safe_error_detail(e: Exception) -> str:
    """Return a clean, user-safe string from *any* exception.

    * ``httpx.HTTPStatusError`` → delegates to :func:`sanitize_upstream_error`
      so that raw HTML / huge JSON bodies are never surfaced.
    * Other exceptions → ``str(e)`` capped at 300 chars.
    """
    if isinstance(e, httpx.HTTPStatusError) and hasattr(e, "response"):
        return sanitize_upstream_error(e.response)
    msg = str(e)
    if "<html" in msg[:200].lower() or "<!doctype" in msg[:200].lower():
        return type(e).__name__
    return msg[:300] if msg else type(e).__name__


def http_error_response(e) -> _JSONResponse:
    """Build a standard JSON error response from an ``httpx.HTTPStatusError``.

    Used by route handlers to avoid repeating the same 5-line
    ``except HTTPStatusError`` block.  Always returns a clean,
    user-safe error message (no raw HTML from upstream).
    """
    r = e.response
    detail = sanitize_upstream_error(r)
    return _JSONResponse(
        {
            "status": "error",
            "code": r.status_code,
            "reason": r.reason_phrase,
            "detail": detail,
        },
        status_code=r.status_code or 500,
    )


async def search_reservoirs(
    at: str,
    query: str = "*",
    limit: int = 50,
) -> List[Dict[str, str]]:
    """Search for Reservoir master-data records, de-dupe, and fetch names.

    Uses parallel storage-record fetches to resolve human-readable names.
    Returns ``[{id, name, version}]`` sorted by name.  Cached 90 s.
    """
    async def _do_search(at_: str, query_: str, limit_: int) -> List[Dict[str, str]]:
        search_url = f"https://{osdu.OSDU_BASE_URL}/api/search/v2/query"
        storage_url = f"https://{osdu.OSDU_BASE_URL}/api/storage/v2/records"
        hdr = osdu.headers(at_)

        payload = {
            "kind": "osdu:wks:master-data--Reservoir:2.0.0",
            "query": query_,
            "limit": min(int(limit_), 100),
            "returnedFields": ["id", "kind", "version"],
            "trackTotalCount": True,
        }

        try:
            async with osdu.http_client(timeout=60) as client:
                r = await client.post(search_url, headers=hdr, json=payload)
                r.raise_for_status()
                results = r.json().get("results", [])

                # De-dupe by base ID (strip version suffix), keep highest version
                best: Dict[str, Dict[str, Any]] = {}
                for rec in results:
                    rid = rec.get("id", "")
                    if not rid:
                        continue
                    parts = rid.rsplit(":", 1)
                    base = parts[0] if len(parts) == 2 and parts[1].isdigit() else rid
                    ver = int(rec.get("version") or 0)
                    existing = best.get(base)
                    if existing is None or ver > int(existing.get("version") or 0):
                        best[base] = {**rec, "version": str(ver)}

                # Parallel fetch names
                async def _fetch_name(rec: Dict[str, Any]) -> Dict[str, str]:
                    rid = rec.get("id", "")
                    name = rid
                    try:
                        rf = await client.get(f"{storage_url}/{rid}", headers=hdr)
                        if rf.status_code == 200:
                            d = (rf.json() or {}).get("data", {}) or {}
                            name = d.get("Name") or d.get("Description") or rid
                    except Exception:
                        pass
                    return {"id": rid, "name": name, "version": rec.get("version", "")}

                out = list(await asyncio.gather(*[_fetch_name(rec) for rec in best.values()]))
                return sorted(out, key=lambda x: x.get("name", ""))

        except Exception as e:
            log.warning("Reservoir search failed: %s", e)
            return []

    cache_key = f"search_reservoirs:{query}:{limit}"
    return await cached_call(cache_key, 90, _do_search, at, query, limit)
