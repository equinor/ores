from __future__ import annotations

import os
import json
import logging
from typing import Any, Dict, List, Optional
import urllib.parse  
import httpx

log = logging.getLogger("rddms-admin.osdu")

# ----------------------------------------------------------------------
# Environment & defaults
# ----------------------------------------------------------------------

# Base DNS name of your ADME/OSDU instance (no scheme).
OSDU_BASE_URL: str = os.getenv("OSDU_BASE_URL", "equinordev.energy.azure.com")

# Required header for all ADME/OSDU calls.
DATA_PARTITION_ID: str = os.getenv("DATA_PARTITION_ID", "").strip()

def _partition_suffix() -> str:
    # e.g., "dp1.dataservices.energy"
    return f"{DATA_PARTITION_ID}.dataservices.energy" if DATA_PARTITION_ID else "partition.dataservices.energy"

# Sensible defaults for the "Create Dataspace" form (can be overridden in env)
DEFAULT_LEGAL_TAG: str = os.getenv("DEFAULT_LEGAL_TAG", f"{DATA_PARTITION_ID}-RDDMS-Legal-Tag" if DATA_PARTITION_ID else "dp1-RDDMS-Legal-Tag")

_default_owners = os.getenv("DEFAULT_OWNERS", f"data.default.owners@{_partition_suffix()}")
DEFAULT_OWNERS: List[str] = [x.strip() for x in _default_owners.split(",") if x.strip()]

_default_viewers = os.getenv("DEFAULT_VIEWERS", f"data.default.viewers@{_partition_suffix()}")
DEFAULT_VIEWERS: List[str] = [x.strip() for x in _default_viewers.split(",") if x.strip()]

_default_countries = os.getenv("DEFAULT_COUNTRIES", "US")
DEFAULT_COUNTRIES: List[str] = [x.strip() for x in _default_countries.split(",") if x.strip()]

# ----------------------------------------------------------------------
# HTTP utils
# ----------------------------------------------------------------------

def headers(access_token: str) -> Dict[str, str]:
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

async def list_dataspaces(access_token: str) -> List[Dict[str, Any]]:
    """GET /api/reservoir-ddms/v2/dataspaces"""
    url = f"https://{OSDU_BASE_URL}/api/reservoir-ddms/v2/dataspaces"
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(url, headers=headers(access_token))
        r.raise_for_status()
        return r.json() or []

async def create_dataspace(
    access_token: str,
    path: str,
    *,
    legal_tag: str,
    owners: List[str],
    viewers: List[str],
    countries: List[str],
    extra_custom: Optional[Dict[str, Any]] = None,
) -> Any:
    """POST /api/reservoir-ddms/v2/dataspaces"""
    url = f"https://{OSDU_BASE_URL}/api/reservoir-ddms/v2/dataspaces"

    custom: Dict[str, Any] = {
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
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(url, headers=hdr, json=payload)

    try:
        r.raise_for_status()
    except httpx.HTTPStatusError as e:
        corr = r.headers.get("x-correlation-id") or r.headers.get("x-request-id")
        log.error(
            "Dataspace create failed (%s) corr=%s\nURL=%s\nHeaders=%s\nPayload=%s\nResponseHeaders=%s\nBody=%s",
            r.status_code, corr, url, hdr, json.dumps(payload, indent=2),
            dict(r.headers), r.text
        )
        raise
    return r.json()

# ----------------------------------------------------------------------
# Types & resources
# ----------------------------------------------------------------------

async def list_types(access_token: str, ds_enc: str) -> List[Dict[str, Any]]:
    """GET /dataspaces/{dataspaceId}/resources -> list of {'name','count'}"""
    url = f"https://{OSDU_BASE_URL}/api/reservoir-ddms/v2/dataspaces/{ds_enc}/resources"
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(url, headers=headers(access_token))
        r.raise_for_status()
        return r.json() or []

async def list_resources(access_token: str, ds_enc: str, typ: str) -> List[Dict[str, Any]]:
    """GET /dataspaces/{dataspaceId}/resources/{dataObjectType}"""
    url = f"https://{OSDU_BASE_URL}/api/reservoir-ddms/v2/dataspaces/{ds_enc}/resources/{typ}"
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(url, headers=headers(access_token))
        r.raise_for_status()
        return r.json() or []

async def get_resource(
    access_token: str,
    ds_enc: str,
    typ: str,
    uuid: str,
    *,
    include_refs: bool = False,  # reserved for future expansion
) -> Dict[str, Any]:
    """GET /dataspaces/{dataspaceId}/resources/{dataObjectType}/{guid}"""
    url = f"https://{OSDU_BASE_URL}/api/reservoir-ddms/v2/dataspaces/{ds_enc}/resources/{typ}/{uuid}"
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(url, headers=headers(access_token))
        r.raise_for_status()
        return r.json() or {}

async def list_arrays(access_token: str, ds_enc: str, typ: str, uuid: str) -> List[Dict[str, Any]]:
    """GET arrays metadata list for an object."""
    url = f"https://{OSDU_BASE_URL}/api/reservoir-ddms/v2/dataspaces/{ds_enc}/resources/{typ}/{uuid}/arrays"
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(url, headers=headers(access_token))
        r.raise_for_status()
        return r.json() or []

async def read_array(
    access_token: str,
    ds_enc: str,
    typ: str,
    uuid: str,
    *,
    path_in_resource: str,
) -> Dict[str, Any]:
    """GET content of an array."""
    url = f"https://{OSDU_BASE_URL}/api/reservoir-ddms/v2/dataspaces/{ds_enc}/resources/{typ}/{uuid}/arrays/{path_in_resource}"
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(url, headers=headers(access_token))
        r.raise_for_status()
        return r.json() or {}

# ----------------------------------------------------------------------
# Helpers for UI features
# ----------------------------------------------------------------------

def extract_refs(obj: Dict[str, Any]) -> List[Dict[str, str]]:
    """Very lightweight scan for DataObjectReference-like dicts."""
    edges: List[Dict[str, str]] = []

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

def extract_grid2d_geometry(obj: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extract minimal visualization metadata from a Grid2dRepresentation."""
    if not (obj.get("$type", "") or "").endswith("Grid2dRepresentation"):
        return None
    try:
        patch = obj["Grid2dPatch"]
        fast = int(patch["FastestAxisCount"])
        slow = int(patch["SlowestAxisCount"])
        geom = patch["Geometry"]
        pts = geom["Points"]
        origin = pts["Origin"]
        offsets = pts["Offset"]
        u = offsets[0]
        v = offsets[1]
        return {
            "fast": fast,
            "slow": slow,
            "origin": {
                "x": origin.get("Coordinate1", 0.0),
                "y": origin.get("Coordinate2", 0.0),
                "z": origin.get("Coordinate3", 0.0),
            },
            "u": {
                "dx": (u.get("Offset") or {}).get("Coordinate1", 0.0),
                "dy": (u.get("Offset") or {}).get("Coordinate2", 0.0),
                "spacing": ((u.get("Spacing") or {}).get("Value", 1.0)),
            },
            "v": {
                "dx": (v.get("Offset") or {}).get("Coordinate1", 0.0),
                "dy": (v.get("Offset") or {}).get("Coordinate2", 0.0),
                "spacing": ((v.get("Spacing") or {}).get("Value", 1.0)),
            },
        }
    except Exception:
        return None


# --- add these helpers to app/osdu.py ---

async def lock_dataspace(access_token: str, path: str) -> None:
    """
    POST /api/reservoir-ddms/v2/dataspaces/{dataspaceId}/lock
    """
    enc = urllib.parse.quote(path, safe="")
    url = f"https://{OSDU_BASE_URL}/api/reservoir-ddms/v2/dataspaces/{enc}/lock"
    hdr = headers(access_token)
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(url, headers=hdr)
    try:
        r.raise_for_status()
    except httpx.HTTPStatusError as e:
        corr = r.headers.get("x-correlation-id") or r.headers.get("x-request-id")
        log.error("Dataspace lock failed (%s) corr=%s path=%s body=%s",
                  r.status_code, corr, path, r.text)
        raise

async def unlock_dataspace(access_token: str, path: str) -> None:
    """
    DELETE /api/reservoir-ddms/v2/dataspaces/{dataspaceId}/lock
    """
    enc = urllib.parse.quote(path, safe="")
    url = f"https://{OSDU_BASE_URL}/api/reservoir-ddms/v2/dataspaces/{enc}/lock"
    hdr = headers(access_token)
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.delete(url, headers=hdr)
    try:
        r.raise_for_status()
    except httpx.HTTPStatusError as e:
        corr = r.headers.get("x-correlation-id") or r.headers.get("x-request-id")
        log.error("Dataspace unlock failed (%s) corr=%s path=%s body=%s",
                  r.status_code, corr, path, r.text)
        raise

async def delete_dataspace(access_token: str, path: str) -> None:
    """
    DELETE /api/reservoir-ddms/v2/dataspaces/{dataspaceId}
    """
    enc = urllib.parse.quote(path, safe="")
    url = f"https://{OSDU_BASE_URL}/api/reservoir-ddms/v2/dataspaces/{enc}"
    hdr = headers(access_token)
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.delete(url, headers=hdr)
    try:
        r.raise_for_status()
    except httpx.HTTPStatusError as e:
        corr = r.headers.get("x-correlation-id") or r.headers.get("x-request-id")
        log.error("Dataspace delete failed (%s) corr=%s path=%s body=%s",
                  r.status_code, corr, path, r.text)
        raise

def _dataspace_uri(path: str) -> str:
    # Canonical form seen in responses: eml:///dataspace('demo/Volve')
    return f"eml:///dataspace('{path}')"

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
    """
    POST /api/reservoir-ddms/v2/manifests/build
    Body typically includes: uris[], acl{}, legal{}, createMissingReferences
    """
    url = f"https://{OSDU_BASE_URL}/api/reservoir-ddms/v2/manifests/build"
    hdr = headers(access_token)

    # Use sensible defaults if not provided
    legal_tag = legal_tag or DEFAULT_LEGAL_TAG
    owners = owners or DEFAULT_OWNERS
    viewers = viewers or DEFAULT_VIEWERS
    countries = countries or DEFAULT_COUNTRIES

    body = {
        "uris": [ _dataspace_uri(path) ],
        "acl": {
            "owners": owners,
            "viewers": viewers,
        },
        "legal": {
            "legaltags": [legal_tag],
            "otherRelevantDataCountries": countries,
        },
        "createMissingReferences": bool(create_missing_refs),
    }

    async with httpx.AsyncClient(timeout=90) as client:
        r = await client.post(url, headers=hdr, json=body)
    try:
        r.raise_for_status()
    except httpx.HTTPStatusError as e:
        corr = r.headers.get("x-correlation-id") or r.headers.get("x-request-id")
        log.error("Build manifest failed (%s) corr=%s path=%s body=%s",
                  r.status_code, corr, path, r.text)
        raise
    return r.json() or {}


# --- RDDMS v2 helpers (ADD at end of app/osdu.py) ---

async def list_all_resources(access_token: str, ds_enc: str) -> list[dict]:
    """GET /dataspaces/{dataspaceId}/resources/all"""
    url = f"https://{OSDU_BASE_URL}/api/reservoir-ddms/v2/dataspaces/{ds_enc}/resources/all"
    async with httpx.AsyncClient(timeout=90) as client:
        r = await client.get(url, headers=headers(access_token))
        r.raise_for_status()
        return r.json() or []

async def list_sources(access_token: str, ds_enc: str, typ: str, uuid: str) -> list[dict]:
    """GET /dataspaces/{dataspaceId}/resources/{type}/{uuid}/sources"""
    url = f"https://{OSDU_BASE_URL}/api/reservoir-ddms/v2/dataspaces/{ds_enc}/resources/{typ}/{uuid}/sources"
    async with httpx.AsyncClient(timeout=90) as client:
        r = await client.get(url, headers=headers(access_token))
        r.raise_for_status()
        return r.json() or []

async def list_targets(access_token: str, ds_enc: str, typ: str, uuid: str) -> list[dict]:
    """GET /dataspaces/{dataspaceId}/resources/{type}/{uuid}/targets"""
    url = f"https://{OSDU_BASE_URL}/api/reservoir-ddms/v2/dataspaces/{ds_enc}/resources/{typ}/{uuid}/targets"
    async with httpx.AsyncClient(timeout=90) as client:
        r = await client.get(url, headers=headers(access_token))
        r.raise_for_status()
        return r.json() or []

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
    """POST /api/reservoir-ddms/v2/manifests/build for arbitrary URIs."""
    url = f"https://{OSDU_BASE_URL}/api/reservoir-ddms/v2/manifests/build"
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
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(url, headers=hdr, json=body)
        r.raise_for_status()
        return r.json() or {}
