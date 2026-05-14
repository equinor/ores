"""
FastAPI router that stores a generated manifest in memory and immediately
POSTs it to the OSDU Workflow Service endpoint:
    /api/workflow/v1/workflow/Osdu_ingest/workflowRun

This keeps existing logic intact by adding a new handler that can be called
right after the manifest is created in the UI. It reuses the existing
access_token (obtained via refresh_token) from the session/cookies if present.

Environment variables expected (all optional, but recommended):
- OSDU_BASE_URL        e.g. https://equinordev.energy.azure.com
- DATA_PARTITION_ID    e.g. data
- APP_KEY              e.g. test-app or your app registration name

To register this router, add to your main app:
    from app.ingest_router import router as ingest_router
    app.include_router(ingest_router, prefix="/api")

No existing endpoints need to be modified; the UI can call POST /api/manifest/ingest
with the manifest JSON to trigger immediate ingestion.
"""
from __future__ import annotations

import os
import time
import uuid
import json
from typing import Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse
import httpx
from . import osdu as _osdu_mod
from .common import sanitize_upstream_error

router = APIRouter()

# Simple in-memory manifest store (last N manifests, with TTL eviction).
_MAX_ITEMS = 200
_MAX_AGE_S = 14400  # 4 hours
_MANIFESTS: Dict[str, Dict[str, Any]] = {}
_MANIFEST_TS: Dict[str, float] = {}


def _store_manifest(manifest_id: str, manifest: Dict[str, Any]) -> None:
    """Store a manifest with TTL-based and size-based eviction."""
    now = time.time()
    # Evict expired entries
    expired = [k for k, ts in _MANIFEST_TS.items() if now - ts > _MAX_AGE_S]
    for k in expired:
        _MANIFESTS.pop(k, None)
        _MANIFEST_TS.pop(k, None)
    # Evict oldest if still over limit
    while len(_MANIFESTS) >= _MAX_ITEMS and _MANIFEST_TS:
        oldest = min(_MANIFEST_TS, key=_MANIFEST_TS.get)  # type: ignore[arg-type]
        _MANIFESTS.pop(oldest, None)
        _MANIFEST_TS.pop(oldest, None)
    _MANIFESTS[manifest_id] = manifest
    _MANIFEST_TS[manifest_id] = now


def _get_env(name: str, default: Optional[str] = None) -> Optional[str]:
    """Read config: prefer osdu module globals (set by active instance), fall back to os.getenv."""
    # Module globals that are kept in sync by instances._apply_instance()
    _MODULE_GLOBALS = {
        "OSDU_BASE_URL": lambda: _osdu_mod.OSDU_BASE_URL,
        "DATA_PARTITION_ID": lambda: _osdu_mod.DATA_PARTITION_ID,
    }
    if name in _MODULE_GLOBALS:
        val = _MODULE_GLOBALS[name]()
        if val:
            return val
    v = os.getenv(name)
    return v if v is not None and v != "" else default


async def _post_workflow_run(
    *,
    base_url: str,
    partition: str,
    app_key: Optional[str],
    access_token: str,
    manifest: Dict[str, Any],
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """POST the manifest to the OSDU Workflow Service Osdu_ingest DAG.

    Builds the correct headers and body and returns parsed JSON response.
    """
    url = base_url.rstrip('/') + "/api/workflow/v1/workflow/Osdu_ingest/workflowRun"

    # Build headers – both header and Payload values are commonly used by providers.
    headers = {
        "Authorization": f"Bearer {access_token}",
        "data-partition-id": partition,
        "Content-Type": "application/json",
    }
    if app_key:
        headers["AppKey"] = app_key

    payload = {
        "executionContext": {
            "Payload": {
                "data-partition-id": partition,
            },
            "manifest": manifest,
        }
    }
    if app_key:
        payload["executionContext"]["Payload"]["AppKey"] = app_key
    if run_id:
        payload["runId"] = run_id

    async with _osdu_mod.http_client(timeout=httpx.Timeout(60.0, read=60.0)) as client:
        r = await client.post(url, headers=headers, content=json.dumps(payload))
        if r.status_code >= 400:
            detail = {
                "status": r.status_code,
                "reason": r.reason_phrase,
                "text": sanitize_upstream_error(r),
                "url": url,
            }
            raise HTTPException(status_code=502, detail={"message": "Workflow run failed", **detail})
        try:
            return r.json()
        except Exception:
            return {"status_code": r.status_code, "text": r.reason_phrase}


def _find_access_token(request: Request) -> Optional[str]:
    """Retrieve the access_token from the request context.

    Primary source is ``request.state`` (set by the auth middleware).
    Falls back to the ``Authorization`` header for direct API calls.
    """
    # 1) Request state (set by auth middleware for all authenticated paths)
    access_token = getattr(request.state, 'access_token', None)

    # 2) Authorization header fallback
    if not access_token:
        auth = request.headers.get('Authorization')
        if auth and auth.lower().startswith('bearer '):
            access_token = auth.split(' ', 1)[1]

    return access_token


@router.post("/manifest/ingest")
async def ingest_manifest(
    request: Request,
    background_tasks: BackgroundTasks,
) -> JSONResponse:
    """Accepts a manifest (JSON) and ingests via Workflow or Storage API.

    Body schema:
    {
      "manifest": { ... },            # required manifest JSON
      "method": "storage",            # "storage" (default) or "workflow"
      "runId": "optional-guid",      # optional (workflow only)
      "partition": "data",           # optional override of DATA_PARTITION_ID
      "appKey": "my-app"             # optional override of APP_KEY
    }
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    manifest = body.get("manifest")
    if not isinstance(manifest, dict):
        raise HTTPException(status_code=400, detail="Body must include a 'manifest' object")

    method = (body.get("method") or "storage").lower().strip()
    if method not in ("workflow", "storage"):
        raise HTTPException(status_code=400, detail="'method' must be 'workflow' or 'storage'")

    # Store manifest in memory (with TTL + size eviction)
    manifest_id = str(uuid.uuid4())
    _store_manifest(manifest_id, manifest)

    # Resolve configuration
    base_url = _get_env("OSDU_BASE_URL")
    if not base_url:
        raise HTTPException(status_code=500, detail="OSDU_BASE_URL is not configured in the environment")
    # Normalise: osdu.py stores bare hostname; ensure we have a scheme for URL construction.
    if not base_url.startswith("http"):
        base_url = f"https://{base_url}"
    partition = body.get("partition") or _get_env("DATA_PARTITION_ID", "data")
    app_key = body.get("appKey") or _get_env("APP_KEY")
    run_id = body.get("runId") or str(uuid.uuid4())

    # Fetch access_token from existing session/auth flow
    access_token = _find_access_token(request)
    if not access_token:
        raise HTTPException(status_code=401, detail="access_token not found in session/headers/cookies")

    if method == "workflow":
        # Fire workflow call
        try:
            workflow_response = await _post_workflow_run(
                base_url=base_url,
                partition=partition,
                app_key=app_key,
                access_token=access_token,
                manifest=manifest,
                run_id=run_id,
            )
        except HTTPException:
            raise
        except Exception as ex:
            raise HTTPException(status_code=502, detail={"message": "Failed to call Workflow Service", "error": str(ex)})

        return JSONResponse({
            "status": "submitted",
            "method": "workflow",
            "manifestId": manifest_id,
            "runId": run_id,
            "workflowResponse": workflow_response,
        })
    else:  # storage
        try:
            storage_response = await _ingest_via_storage(
                base_url=base_url,
                partition=partition,
                access_token=access_token,
                manifest=manifest,
            )
        except HTTPException:
            raise
        except Exception as ex:
            raise HTTPException(status_code=502, detail={"message": "Failed to call Storage API", "error": str(ex)})

        return JSONResponse({
            "status": "submitted",
            "method": "storage",
            "manifestId": manifest_id,
            "storageResponse": storage_response,
        })


@router.get("/manifest/last")
async def get_last_manifest() -> JSONResponse:
    """Returns the latest stored manifest (debug/helper)."""
    if not _MANIFESTS:
        raise HTTPException(status_code=404, detail="No manifests stored yet")
    # return the most recently inserted manifest
    last_key = list(_MANIFESTS.keys())[-1]
    return JSONResponse({"manifestId": last_key, "manifest": _MANIFESTS[last_key]})


# ======================================================================
# RDDMS → OSDU indexing endpoints
#
# These endpoints combine two steps:
#   1. Call RDDMS manifests/build to generate OSDU records from RESQML
#   2. Submit the resulting manifest to OSDU (Workflow or Storage API)
#
# Supported ingestion methods:
#   - "workflow"  → POST Osdu_ingest DAG  (default, requires workflow.creator)
#   - "storage"   → PUT  /api/storage/v2/records  (requires storage.creator)
# ======================================================================

async def _build_rddms_manifest(
    *,
    access_token: str,
    base_url: str,
    partition: str,
    dataspace: str,
    uris: Optional[list] = None,
    legal_tag: Optional[str] = None,
    owners: Optional[list] = None,
    viewers: Optional[list] = None,
    countries: Optional[list] = None,
    create_missing_refs: bool = True,
) -> Dict[str, Any]:
    """Call RDDMS manifests/build and return the generated OSDU manifest.

    If `uris` is provided, builds for those specific EML URIs.
    Otherwise builds for the entire dataspace.
    """
    url = base_url.rstrip("/") + "/api/reservoir-ddms/v2/manifests/build"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "data-partition-id": partition,
        "Content-Type": "application/json",
    }

    # Defaults matching osdu.py conventions
    partition_suffix = f"{partition}.dataservices.energy"
    legal_tag = legal_tag or f"{partition}-equinor-private-default"
    owners = owners or [f"data.default.owners@{partition_suffix}"]
    viewers = viewers or [f"data.default.viewers@{partition_suffix}"]
    countries = countries or ["NO"]

    if uris:
        body_uris = list(uris)
    else:
        body_uris = [f"eml:///dataspace('{dataspace}')"]

    body = {
        "uris": body_uris,
        "acl": {"owners": owners, "viewers": viewers},
        "legal": {"legaltags": [legal_tag], "otherRelevantDataCountries": countries},
        "createMissingReferences": create_missing_refs,
    }

    async with _osdu_mod.http_client(timeout=httpx.Timeout(120.0, read=120.0)) as client:
        r = await client.post(url, headers=headers, json=body)
        if r.status_code >= 400:
            raise HTTPException(
                status_code=r.status_code,
                detail={
                    "message": "RDDMS manifests/build failed",
                    "status": r.status_code,
                    "reason": r.reason_phrase,
                    "text": sanitize_upstream_error(r),
                },
            )
        return r.json() or {}


async def _ingest_via_storage(
    *,
    base_url: str,
    partition: str,
    access_token: str,
    manifest: Dict[str, Any],
) -> Dict[str, Any]:
    """PUT records to /api/storage/v2/records (direct Storage API).

    Extracts all WPC records from the manifest and sends them in one batch.
    Returns the Storage API response.
    """
    url = base_url.rstrip("/") + "/api/storage/v2/records"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "data-partition-id": partition,
        "Content-Type": "application/json",
    }

    # RDDMS manifests/build returns: {kind: "osdu:wks:Manifest:1.0.0", Data: {Datasets: [...], WorkProductComponents: [...]}}
    # Unwrap the Data envelope if present, then extract records from all sections.
    inner = manifest.get("Data", manifest)  # unwrap if envelope present
    records = []
    for section in ("WorkProductComponents", "Datasets", "ReferenceData", "MasterData", "WorkProducts"):
        items = inner.get(section) or []
        if isinstance(items, list):
            records.extend(items)

    if not records:
        raise HTTPException(
            status_code=400,
            detail="Manifest contains no records to ingest",
        )

    async with _osdu_mod.http_client(timeout=httpx.Timeout(120.0, read=120.0)) as client:
        r = await client.put(url, headers=headers, json=records)
        if r.status_code >= 400:
            raise HTTPException(
                status_code=502,
                detail={
                    "message": "Storage API PUT failed",
                    "status": r.status_code,
                    "reason": r.reason_phrase,
                    "text": sanitize_upstream_error(r),
                },
            )
        try:
            body = r.json()
        except Exception:
            body = {"text": sanitize_upstream_error(r)}

        # Normalise: OSDU Storage returns {"recordCount": N, "recordIds": [...], ...}
        record_ids = body.get("recordIds") or body.get("recordIdVersions") or []
        return {
            "recordCount": body.get("recordCount", len(record_ids)),
            "recordIds": record_ids,
            "recordsSent": len(records),
            "raw": body,
        }


@router.post("/rddms/build")
async def rddms_build_manifest(request: Request) -> JSONResponse:
    """Build an OSDU manifest from RDDMS dataspace content (dry-run, no ingestion).

    Body:
    {
      "dataspace": "maap/drogon",          # required
      "uris": ["eml:///..."],              # optional: specific EML URIs (default: whole dataspace)
      "legalTag": "dev-RDDMS-Legal-Tag",   # optional
      "owners": ["data.default.owners@dev.dataservices.energy"],  # optional
      "viewers": ["data.default.viewers@dev.dataservices.energy"], # optional
      "countries": ["US"],                  # optional
      "createMissingRefs": true             # optional (default true)
    }
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    dataspace = body.get("dataspace")
    if not dataspace:
        raise HTTPException(status_code=400, detail="'dataspace' is required")

    access_token = _find_access_token(request)
    if not access_token:
        raise HTTPException(status_code=401, detail="access_token not found")

    base_url = _get_env("OSDU_BASE_URL")
    if not base_url:
        raise HTTPException(status_code=500, detail="OSDU_BASE_URL not configured")
    if not base_url.startswith("http"):
        base_url = f"https://{base_url}"

    partition = body.get("partition") or _get_env("DATA_PARTITION_ID", "data")

    manifest = await _build_rddms_manifest(
        access_token=access_token,
        base_url=base_url,
        partition=partition,
        dataspace=dataspace,
        uris=body.get("uris"),
        legal_tag=body.get("legalTag"),
        owners=body.get("owners"),
        viewers=body.get("viewers"),
        countries=body.get("countries"),
        create_missing_refs=body.get("createMissingRefs", True),
    )

    # Stash for later retrieval / inspection
    manifest_id = str(uuid.uuid4())
    _store_manifest(manifest_id, manifest)

    # Count records by section
    counts = {}
    for section in ("WorkProductComponents", "ReferenceData", "MasterData", "WorkProducts"):
        items = manifest.get(section)
        if isinstance(items, list) and items:
            counts[section] = len(items)

    return JSONResponse({
        "status": "ok",
        "manifestId": manifest_id,
        "dataspace": dataspace,
        "recordCounts": counts,
        "manifest": manifest,
    })


@router.post("/rddms/index")
async def rddms_index(request: Request) -> JSONResponse:
    """Build manifest from RDDMS and ingest into OSDU in one step.

    Body:
    {
      "dataspace": "maap/drogon",          # required
      "method": "workflow",                 # "workflow" (default) or "storage"
      "uris": ["eml:///..."],              # optional: specific EML URIs
      "legalTag": "...",                    # optional
      "owners": [...],                      # optional
      "viewers": [...],                     # optional
      "countries": [...],                   # optional
      "createMissingRefs": true,            # optional
      "partition": "dev",                   # optional override
      "appKey": "..."                       # optional (workflow method only)
    }
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    dataspace = body.get("dataspace")
    if not dataspace:
        raise HTTPException(status_code=400, detail="'dataspace' is required")

    method = (body.get("method") or "workflow").lower().strip()
    if method not in ("workflow", "storage"):
        raise HTTPException(status_code=400, detail="'method' must be 'workflow' or 'storage'")

    access_token = _find_access_token(request)
    if not access_token:
        raise HTTPException(status_code=401, detail="access_token not found")

    base_url = _get_env("OSDU_BASE_URL")
    if not base_url:
        raise HTTPException(status_code=500, detail="OSDU_BASE_URL not configured")
    if not base_url.startswith("http"):
        base_url = f"https://{base_url}"

    partition = body.get("partition") or _get_env("DATA_PARTITION_ID", "data")
    app_key = body.get("appKey") or _get_env("APP_KEY")

    # Step 1: Build manifest from RDDMS
    manifest = await _build_rddms_manifest(
        access_token=access_token,
        base_url=base_url,
        partition=partition,
        dataspace=dataspace,
        uris=body.get("uris"),
        legal_tag=body.get("legalTag"),
        owners=body.get("owners"),
        viewers=body.get("viewers"),
        countries=body.get("countries"),
        create_missing_refs=body.get("createMissingRefs", True),
    )

    # Stash manifest
    manifest_id = str(uuid.uuid4())
    _store_manifest(manifest_id, manifest)
    run_id = str(uuid.uuid4())

    # Step 2: Ingest
    if method == "workflow":
        ingest_response = await _post_workflow_run(
            base_url=base_url,
            partition=partition,
            app_key=app_key,
            access_token=access_token,
            manifest=manifest,
            run_id=run_id,
        )
        return JSONResponse({
            "status": "submitted",
            "method": "workflow",
            "manifestId": manifest_id,
            "runId": run_id,
            "dataspace": dataspace,
            "workflowResponse": ingest_response,
        })
    else:  # storage
        storage_response = await _ingest_via_storage(
            base_url=base_url,
            partition=partition,
            access_token=access_token,
            manifest=manifest,
        )
        return JSONResponse({
            "status": "submitted",
            "method": "storage",
            "manifestId": manifest_id,
            "dataspace": dataspace,
            "storageResponse": storage_response,
        })


# ======================================================================
# DELETE /api/records/delete - soft-delete an OSDU record via Storage API
# ======================================================================

@router.post("/records/delete")
async def delete_record(request: Request) -> JSONResponse:
    """Delete (soft) one or more OSDU records via Storage API.

    Body:
    {
      "ids": ["dev:work-product-component--PersistedCollection:dfc7b372-..."]
    }
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    ids = body.get("ids")
    if not ids or not isinstance(ids, list):
        raise HTTPException(status_code=400, detail="'ids' must be a non-empty list of record IDs")

    access_token = _find_access_token(request)
    if not access_token:
        raise HTTPException(status_code=401, detail="access_token not found")

    base_url = _get_env("OSDU_BASE_URL")
    if not base_url:
        raise HTTPException(status_code=500, detail="OSDU_BASE_URL not configured")
    if not base_url.startswith("http"):
        base_url = f"https://{base_url}"

    partition = body.get("partition") or _get_env("DATA_PARTITION_ID", "data")
    headers = {
        "Authorization": f"Bearer {access_token}",
        "data-partition-id": partition,
        "Content-Type": "application/json",
    }

    results = []
    async with _osdu_mod.http_client(timeout=60) as client:
        for rid in ids:
            url = f"{base_url.rstrip('/')}/api/storage/v2/records/{rid}"
            r = await client.delete(url, headers=headers)
            results.append({
                "id": rid,
                "status": r.status_code,
                "ok": r.status_code < 400,
                "detail": sanitize_upstream_error(r) if r.status_code >= 400 else "deleted",
            })

    return JSONResponse({"results": results})


# ======================================================================
# POST /api/records/ingest - ingest records directly via Storage PUT
# ======================================================================

@router.post("/records/ingest")
async def ingest_records(request: Request) -> JSONResponse:
    """PUT one or more records to OSDU Storage API.

    Body:
    {
      "records": [ { "id": "...", "kind": "...", ... }, ... ]
    }
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    records = body.get("records")
    if not records or not isinstance(records, list):
        raise HTTPException(status_code=400, detail="'records' must be a non-empty list")

    access_token = _find_access_token(request)
    if not access_token:
        raise HTTPException(status_code=401, detail="access_token not found")

    base_url = _get_env("OSDU_BASE_URL")
    if not base_url:
        raise HTTPException(status_code=500, detail="OSDU_BASE_URL not configured")
    if not base_url.startswith("http"):
        base_url = f"https://{base_url}"

    partition = body.get("partition") or _get_env("DATA_PARTITION_ID", "data")
    url = f"{base_url.rstrip('/')}/api/storage/v2/records"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "data-partition-id": partition,
        "Content-Type": "application/json",
    }

    async with _osdu_mod.http_client(timeout=120) as client:
        r = await client.put(url, headers=headers, json=records)
        if r.status_code >= 400:
            raise HTTPException(
                status_code=502,
                detail={
                    "message": "Storage API PUT failed",
                    "status": r.status_code,
                    "text": sanitize_upstream_error(r),
                },
            )
        try:
            return JSONResponse(r.json())
        except Exception:
            return JSONResponse({"status_code": r.status_code, "text": sanitize_upstream_error(r)})
