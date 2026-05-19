from __future__ import annotations

import asyncio
import os
import json
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator
import urllib.parse
import httpx

from .cache import cached_call

log = logging.getLogger("rddms-admin.osdu")

# ── Global concurrency limiter ───────────────────────────────────────────────
# Limits how many simultaneous HTTP requests the app sends to external APIs.
# Prevents saturating the OSDU backend during fan-out operations like search
# enrichment.  Default 20; override via OSDU_MAX_CONCURRENT env var.
_MAX_CONCURRENT = int(os.getenv("OSDU_MAX_CONCURRENT", "20"))
API_SEMAPHORE = asyncio.Semaphore(_MAX_CONCURRENT)

# ----------------------------------------------------------------------
# Environment & defaults
#
# NOTE: These module-level globals are overwritten by instances.py
#       _apply_instance() at startup and on every instance switch.
#       Initial values are populated from env as a safe fallback.
# ----------------------------------------------------------------------

# Base DNS name of your ADME/OSDU instance (no scheme).
OSDU_BASE_URL: str = os.getenv("OSDU_BASE_URL", "")

# SSL certificate verification for the OSDU backend.  Disabled for test/
# pre-ship environments whose TLS certificates are not in the default CA
# bundle.  Overridden per-instance by INSTANCE_<NAME>_SSL_VERIFY.
SSL_VERIFY: bool = True

# Required header for all ADME/OSDU calls.
DATA_PARTITION_ID: str = os.getenv("DATA_PARTITION_ID", "").strip()

def _partition_suffix() -> str:
    """E.g. 'dev.dataservices.energy'.  Returns empty string when unset."""
    return f"{DATA_PARTITION_ID}.dataservices.energy" if DATA_PARTITION_ID else ""

# Sensible defaults for the "Create Dataspace" form (can be overridden in env)
DEFAULT_LEGAL_TAG: str = os.getenv(
    "DEFAULT_LEGAL_TAG",
    f"{DATA_PARTITION_ID}-equinor-private-default" if DATA_PARTITION_ID else "dev-equinor-private-default",
)

_default_owners = os.getenv("DEFAULT_OWNERS", f"data.default.owners@{_partition_suffix()}" if _partition_suffix() else "")
DEFAULT_OWNERS: list[str] = [x.strip() for x in _default_owners.split(",") if x.strip()]

_default_viewers = os.getenv("DEFAULT_VIEWERS", f"data.default.viewers@{_partition_suffix()}" if _partition_suffix() else "")
DEFAULT_VIEWERS: list[str] = [x.strip() for x in _default_viewers.split(",") if x.strip()]

_default_countries = os.getenv("DEFAULT_COUNTRIES", "NO")
DEFAULT_COUNTRIES: list[str] = [x.strip() for x in _default_countries.split(",") if x.strip()]

# ----------------------------------------------------------------------
# HTTP helpers
# ----------------------------------------------------------------------

# Module-level shared client (created lazily, reused across calls)
_shared_client: httpx.AsyncClient | None = None


@asynccontextmanager
async def _http(timeout: float = 60) -> AsyncIterator[httpx.AsyncClient]:
    """Yield a shared :class:`httpx.AsyncClient`.

    Re-uses a module-level client so TCP connections are pooled across
    calls instead of opening a fresh connection per request.
    The *timeout* is applied per-request via the client, not at creation
    time, so callers that need longer deadlines get them.
    """
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        _shared_client = httpx.AsyncClient(timeout=timeout, verify=SSL_VERIFY)
    else:
        # Update timeout for this call if different from the client default
        _shared_client.timeout = httpx.Timeout(timeout)
    yield _shared_client


async def close_shared_client() -> None:
    """Close the module-level HTTP client. Called on app shutdown (#9)."""
    global _shared_client
    if _shared_client is not None and not _shared_client.is_closed:
        await _shared_client.aclose()
        _shared_client = None
        log.info("Shared httpx client closed")


def http_client(timeout: float = 60, **kwargs) -> httpx.AsyncClient:
    """Create an httpx.AsyncClient with the active instance's SSL settings.

    Use this instead of ``httpx.AsyncClient(...)`` directly so that
    per-instance SSL_VERIFY is respected (needed for test/pre-ship envs).
    Extra kwargs (e.g. http2=True) are forwarded to AsyncClient.
    """
    return httpx.AsyncClient(timeout=timeout, verify=SSL_VERIFY, **kwargs)


def _rddms_url(path: str = "") -> str:
    """Build a Reservoir-DDMS v2 URL.  *path* is appended after the base."""
    return f"https://{OSDU_BASE_URL}/api/reservoir-ddms/v2{path}"


def headers(access_token: str) -> dict[str, str]:
    if not DATA_PARTITION_ID:
        log.warning("DATA_PARTITION_ID env var is not set; calls may fail")
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "data-partition-id": DATA_PARTITION_ID,
    }

# ----------------------------------------------------------------------
# Dataspaces
# ----------------------------------------------------------------------

async def list_dataspaces(access_token: str) -> list[dict[str, Any]]:
    """GET /api/reservoir-ddms/v2/dataspaces  (cached 600 s, per instance)"""
    async def _fetch(at: str) -> list[dict[str, Any]]:
        async with _http() as client:
            r = await client.get(_rddms_url("/dataspaces"), headers=headers(at))
            r.raise_for_status()
            return r.json() or []
    # Include hostname in cache key so instance switches don't serve stale data
    cache_key = f"list_dataspaces:{OSDU_BASE_URL}"
    return await cached_call(cache_key, 600, _fetch, access_token)

async def create_dataspace(
    access_token: str,
    path: str,
    *,
    legal_tag: str,
    owners: list[str],
    viewers: list[str],
    countries: list[str],
    extra_custom: dict[str, Any] | None = None,
) -> Any:
    """POST /api/reservoir-ddms/v2/dataspaces"""
    url = _rddms_url("/dataspaces")

    custom: dict[str, Any] = {
        "legaltags": [legal_tag],
        "otherRelevantDataCountries": countries,
        "viewers": viewers,
        "owners": owners,
    }
    if extra_custom:
        # Do not let extra keys override reserved compliance ACL fields
        for k in ("legaltags", "otherRelevantDataCountries", "viewers", "owners"):
            extra_custom.pop(k, None)
        custom.update(extra_custom)

    payload = [
        {
            "DataspaceId": path,
            "Path": path,
            "CustomData": custom,
        }
    ]

    hdr = headers(access_token)
    async with _http() as client:
        r = await client.post(url, headers=hdr, json=payload)

    try:
        r.raise_for_status()
    except httpx.HTTPStatusError:
        corr = r.headers.get("x-correlation-id") or r.headers.get("x-request-id")
        log.error(
            "Dataspace create failed (%s) corr=%s\nURL=%s\nPayload=%s\nBody=%s",
            r.status_code, corr, url, json.dumps(payload, indent=2), r.text,
        )
        raise
    return r.json()

# ----------------------------------------------------------------------
# Types & resources
# ----------------------------------------------------------------------

async def list_types(access_token: str, ds_enc: str) -> list[dict[str, Any]]:
    """GET /dataspaces/{dataspaceId}/resources -> list of {'name','count'}"""
    async with _http() as client:
        r = await client.get(_rddms_url(f"/dataspaces/{ds_enc}/resources"), headers=headers(access_token))
        r.raise_for_status()
        return r.json() or []

async def list_resources(access_token: str, ds_enc: str, typ: str) -> list[dict[str, Any]]:
    """GET /dataspaces/{dataspaceId}/resources/{dataObjectType}"""
    async with _http() as client:
        r = await client.get(_rddms_url(f"/dataspaces/{ds_enc}/resources/{typ}"), headers=headers(access_token))
        r.raise_for_status()
        return r.json() or []

async def get_resource(
    access_token: str,
    ds_enc: str,
    typ: str,
    uuid: str,
    *,
    as_json: bool = True,
) -> dict[str, Any]:
    """GET /dataspaces/{dataspaceId}/resources/{dataObjectType}/{guid}

    By default requests ``$format=json`` so the RDDMS returns JSON
    instead of XML.
    """
    params: dict[str, str] = {}
    if as_json:
        params["$format"] = "json"
    async with _http() as client:
        r = await client.get(
            _rddms_url(f"/dataspaces/{ds_enc}/resources/{typ}/{uuid}"),
            headers=headers(access_token), params=params,
        )
        r.raise_for_status()
        return r.json() or {}

async def list_arrays(access_token: str, ds_enc: str, typ: str, uuid: str) -> list[dict[str, Any]]:
    """GET arrays metadata list for an object."""
    async with _http() as client:
        r = await client.get(
            _rddms_url(f"/dataspaces/{ds_enc}/resources/{typ}/{uuid}/arrays"),
            headers=headers(access_token),
        )
        if r.status_code in (404, 405, 412):
            log.warning("list_arrays: HTTP %d for %s/%s – arrays not available via REST",
                        r.status_code, typ, uuid)
            return []
        r.raise_for_status()
        return r.json() or []

async def read_array(
    access_token: str,
    ds_enc: str,
    typ: str,
    uuid: str,
    *,
    path_in_resource: str,
) -> dict[str, Any]:
    """GET content of an array."""
    import urllib.parse
    encoded_path = urllib.parse.quote(path_in_resource, safe="")
    async with _http() as client:
        r = await client.get(
            _rddms_url(f"/dataspaces/{ds_enc}/resources/{typ}/{uuid}/arrays/{encoded_path}"),
            headers=headers(access_token),
        )
        r.raise_for_status()
        return r.json() or {}


async def write_array(
    access_token: str,
    ds_enc: str,
    typ: str,
    uuid: str,
    *,
    path_in_resource: str,
    values: list,
    tx_id: str,
) -> dict[str, Any]:
    """PUT array data for a resource (within a transaction)."""
    async with _http(timeout=120) as client:
        r = await client.put(
            _rddms_url(f"/dataspaces/{ds_enc}/resources/{typ}/{uuid}/arrays/{path_in_resource}"),
            headers=headers(access_token),
            json={"values": values},
            params={"transactionId": tx_id},
        )
        r.raise_for_status()
        try:
            return r.json() or {}
        except Exception:
            return {"status": r.status_code}


# ----------------------------------------------------------------------
# Helpers for UI features
# ----------------------------------------------------------------------

def extract_refs(obj: dict[str, Any]) -> list[dict[str, str]]:
    """Very lightweight scan for DataObjectReference-like dicts."""
    edges: list[dict[str, str]] = []

    def _walk(x: Any):
        if isinstance(x, dict):
            ct = x.get("ContentType")
            uid = x.get("UUID") or x.get("Uuid")
            if ct and uid:
                edges.append({"contentType": ct, "uuid": str(uid)})
            for v in x.values():
                _walk(v)
        elif isinstance(x, list):
            for v in x:
                _walk(v)

    _walk(obj)
    return edges


async def lock_dataspace(access_token: str, path: str) -> None:
    """POST /api/reservoir-ddms/v2/dataspaces/{dataspaceId}/lock"""
    enc = urllib.parse.quote(path, safe="")
    hdr = headers(access_token)
    async with _http() as client:
        r = await client.post(_rddms_url(f"/dataspaces/{enc}/lock"), headers=hdr)
    try:
        r.raise_for_status()
    except httpx.HTTPStatusError:
        log.error("Dataspace lock failed (%s) path=%s body=%s", r.status_code, path, r.text)
        raise

async def unlock_dataspace(access_token: str, path: str) -> None:
    """DELETE /api/reservoir-ddms/v2/dataspaces/{dataspaceId}/lock"""
    enc = urllib.parse.quote(path, safe="")
    hdr = headers(access_token)
    async with _http() as client:
        r = await client.delete(_rddms_url(f"/dataspaces/{enc}/lock"), headers=hdr)
    try:
        r.raise_for_status()
    except httpx.HTTPStatusError:
        log.error("Dataspace unlock failed (%s) path=%s body=%s", r.status_code, path, r.text)
        raise

async def delete_dataspace(access_token: str, path: str) -> None:
    """DELETE /api/reservoir-ddms/v2/dataspaces/{dataspaceId}"""
    enc = urllib.parse.quote(path, safe="")
    hdr = headers(access_token)
    async with _http() as client:
        r = await client.delete(_rddms_url(f"/dataspaces/{enc}"), headers=hdr)
    try:
        r.raise_for_status()
    except httpx.HTTPStatusError:
        log.error("Dataspace delete failed (%s) path=%s body=%s", r.status_code, path, r.text)
        raise


async def import_dataspace(access_token: str, src_path: str, dst_path: str) -> dict[str, Any]:
    """Copy content from a locked source dataspace into destination.

    Uses PUT /dataspaces/{dst}/copy with sourceDataspace in body.
    Source must be locked; destination must exist and be unlocked.
    Creates a reference copy (same UUIDs, resolved from source).
    """
    dst_enc = urllib.parse.quote(dst_path, safe="")
    hdr = headers(access_token)
    body = {"sourceDataspace": src_path}
    async with _http(timeout=120) as client:
        r = await client.put(
            _rddms_url(f"/dataspaces/{dst_enc}/copy"),
            headers=hdr,
            json=body,
        )
    try:
        r.raise_for_status()
    except httpx.HTTPStatusError:
        log.error(
            "Import dataspace failed (%s) src=%s dst=%s body=%s",
            r.status_code, src_path, dst_path, r.text,
        )
        raise
    # Return whatever the server gives us (may be summary or empty)
    try:
        return r.json()
    except Exception:
        return {"status": "ok"}


def _dataspace_uri(path: str) -> str:
    """Canonical EML dataspace URI."""
    return f"eml:///dataspace('{path}')"


def _eml_uri_from_parts(path: str, typ: str, uuid: str) -> str:
    """Canonical EML URI fallback if object lacks 'uri'."""
    return f"eml:///dataspace('{path}')/{typ}('{uuid}')"


async def build_manifest_for_uris(
    access_token: str,
    uris: list[str],
    *,
    legal_tag: str | None = None,
    owners: list[str] | None = None,
    viewers: list[str] | None = None,
    countries: list[str] | None = None,
    create_missing_refs: bool = True,
) -> dict:
    """POST /api/reservoir-ddms/v2/manifests/build for arbitrary URIs.

    Pass a single ``eml:///dataspace('...')`` URI to build a whole-dataspace
    manifest, or multiple object URIs for a targeted build.
    """
    hdr = headers(access_token)
    legal_tag = legal_tag or DEFAULT_LEGAL_TAG
    owners = owners or DEFAULT_OWNERS
    viewers = viewers or DEFAULT_VIEWERS
    countries = countries or DEFAULT_COUNTRIES
    body = {
        "uris": list(uris),
        "acl": {"owners": owners, "viewers": viewers},
        "legal": {"legaltags": [legal_tag], "otherRelevantDataCountries": countries},
        "createMissingReferences": bool(create_missing_refs),
    }
    async with _http(timeout=120) as client:
        r = await client.post(_rddms_url("/manifests/build"), headers=hdr, json=body)
    try:
        r.raise_for_status()
    except httpx.HTTPStatusError:
        log.error("Build manifest failed (%s) uris=%s body=%s", r.status_code, uris[:3], r.text[:2000])
        raise
    return r.json() or {}


async def build_manifest(
    access_token: str,
    path: str,
    *,
    legal_tag: str | None = None,
    owners: list[str] | None = None,
    viewers: list[str] | None = None,
    countries: list[str] | None = None,
    create_missing_refs: bool = True,
) -> dict:
    """Convenience wrapper: build manifest for an entire dataspace."""
    return await build_manifest_for_uris(
        access_token,
        [_dataspace_uri(path)],
        legal_tag=legal_tag,
        owners=owners,
        viewers=viewers,
        countries=countries,
        create_missing_refs=create_missing_refs,
    )


async def list_all_resources(access_token: str, ds_enc: str) -> list[dict]:
    """GET /dataspaces/{dataspaceId}/resources/all"""
    async with _http(timeout=90) as client:
        r = await client.get(_rddms_url(f"/dataspaces/{ds_enc}/resources/all"), headers=headers(access_token))
        r.raise_for_status()
        return r.json() or []

async def list_sources(access_token: str, ds_enc: str, typ: str, uuid: str) -> list[dict]:
    """GET /dataspaces/{dataspaceId}/resources/{type}/{uuid}/sources"""
    async with _http(timeout=90) as client:
        r = await client.get(
            _rddms_url(f"/dataspaces/{ds_enc}/resources/{typ}/{uuid}/sources"),
            headers=headers(access_token),
        )
        r.raise_for_status()
        return r.json() or []

async def list_targets(access_token: str, ds_enc: str, typ: str, uuid: str) -> list[dict]:
    """GET /dataspaces/{dataspaceId}/resources/{type}/{uuid}/targets"""
    async with _http(timeout=90) as client:
        r = await client.get(
            _rddms_url(f"/dataspaces/{ds_enc}/resources/{typ}/{uuid}/targets"),
            headers=headers(access_token),
        )
        r.raise_for_status()
        return r.json() or []

# ── Transactions ──────────────────────────────────────────────────────

async def begin_transaction(access_token: str, ds_path: str) -> str:
    """POST /dataspaces/{dataspaceId}/transactions → transaction ID."""
    enc = urllib.parse.quote(ds_path, safe="")
    hdr = headers(access_token)
    async with _http() as client:
        r = await client.post(_rddms_url(f"/dataspaces/{enc}/transactions"), headers=hdr)
    try:
        r.raise_for_status()
    except httpx.HTTPStatusError:
        log.error("Begin transaction failed (%s) ds=%s body=%s", r.status_code, ds_path, r.text[:2000])
        raise
    return r.text.strip().strip('"')


async def commit_transaction(access_token: str, ds_path: str, tx_id: str) -> None:
    """PUT /dataspaces/{dataspaceId}/transactions/{transactionId} → commit."""
    enc = urllib.parse.quote(ds_path, safe="")
    hdr = headers(access_token)
    async with _http(timeout=120) as client:
        r = await client.put(_rddms_url(f"/dataspaces/{enc}/transactions/{tx_id}"), headers=hdr)
    try:
        r.raise_for_status()
    except httpx.HTTPStatusError:
        log.error("Commit transaction failed (%s) ds=%s tx=%s body=%s",
                  r.status_code, ds_path, tx_id, r.text[:2000])
        raise


async def cancel_transaction(access_token: str, ds_path: str, tx_id: str) -> None:
    """DELETE /dataspaces/{dataspaceId}/transactions/{transactionId} → rollback."""
    enc = urllib.parse.quote(ds_path, safe="")
    hdr = headers(access_token)
    async with _http() as client:
        r = await client.delete(_rddms_url(f"/dataspaces/{enc}/transactions/{tx_id}"), headers=hdr)
    try:
        r.raise_for_status()
    except httpx.HTTPStatusError:
        log.warning("Cancel transaction failed (%s) ds=%s tx=%s", r.status_code, ds_path, tx_id)


# ── Write operations (within a transaction) ──────────────────────────

async def put_resources(
    access_token: str,
    ds_path: str,
    objects: list[dict],
    tx_id: str,
) -> dict:
    """PUT RESQML objects into a Reservoir DDMS v2 dataspace (transactional)."""
    enc = urllib.parse.quote(ds_path, safe="")
    hdr = headers(access_token)
    async with _http(timeout=120) as client:
        r = await client.put(
            _rddms_url(f"/dataspaces/{enc}/resources"),
            headers=hdr, json=objects, params={"transactionId": tx_id},
        )
    try:
        r.raise_for_status()
    except httpx.HTTPStatusError:
        log.error("PUT resources failed (%s) ds=%s tx=%s body=%s",
                  r.status_code, ds_path, tx_id, r.text[:2000])
        raise
    try:
        return r.json() or {}
    except Exception:
        from .common import sanitize_upstream_error
        return {"status": r.status_code, "text": sanitize_upstream_error(r)}


# ======================================================================
# Grid2dRepresentation - full surface fetch + CRS-aware PNG rendering
# ======================================================================

def normalize_obj(raw: Any, uuid: str) -> dict[str, Any]:
    """Pick the right dict when the RDDMS returns a list.

    Warns when the exact UUID isn't found and a fallback is used.
    """
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, list):
        for it in raw:
            if isinstance(it, dict):
                uid = it.get("Uuid") or it.get("UUID") or it.get("uuid")
                if uid and str(uid).lower() == uuid.lower():
                    return it
        # Exact match failed - fall back to first dict (with warning)
        for it in raw:
            if isinstance(it, dict):
                log.warning("normalize_obj: UUID %s not found, using first dict", uuid)
                return it
    return {}

# Backward-compat alias (used by structuremap, resqml_viz, bd_enrichment)
_normalize_obj = normalize_obj

