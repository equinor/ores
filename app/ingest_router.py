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
import uuid
import json
from typing import Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse
import httpx

router = APIRouter()

# Simple in-memory manifest store (last N manifests). Not for production.
_MAX_ITEMS = 100
_MANIFESTS: Dict[str, Dict[str, Any]] = {}


def _get_env(name: str, default: Optional[str] = None) -> Optional[str]:
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

    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, read=60.0)) as client:
        r = await client.post(url, headers=headers, content=json.dumps(payload))
        if r.status_code >= 400:
            detail = {
                "status": r.status_code,
                "reason": r.reason_phrase,
                "text": r.text[:2000],  # cap for safety
                "url": url,
            }
            raise HTTPException(status_code=502, detail={"message": "Workflow run failed", **detail})
        try:
            return r.json()
        except Exception:
            return {"status_code": r.status_code, "text": r.text}


def _find_access_token(request: Request) -> Optional[str]:
    """Try to retrieve the access_token from common places used in the app.

    We DO NOT mint new tokens here to keep the existing auth workflow intact.
    """
    # 1) Starlette session (requires SessionMiddleware configured in main.py)
    access_token = None
    try:
        session = getattr(request, 'session', None)
        if isinstance(session, dict):
            access_token = session.get('access_token') or session.get('token')
    except Exception:
        access_token = None

    # 2) Request state (some apps stash tokens here)
    if not access_token:
        try:
            access_token = getattr(request.state, 'access_token', None)
        except Exception:
            access_token = None

    # 3) Authorization header forwarded from the browser (if UI passes it)
    if not access_token:
        auth = request.headers.get('Authorization')
        if auth and auth.lower().startswith('bearer '):
            access_token = auth.split(' ', 1)[1]

    # 4) Cookie (if app sets a cookie named 'access_token')
    if not access_token:
        access_token = request.cookies.get('access_token')

    return access_token


@router.post("/manifest/ingest")
async def ingest_manifest(
    request: Request,
    background_tasks: BackgroundTasks,
) -> JSONResponse:
    """Accepts a manifest (JSON) and immediately triggers Osdu_ingest workflow.

    Body schema:
    {
      "manifest": { ... },            # required manifest JSON
      "runId": "optional-guid",      # optional
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

    # Store manifest in memory (cap to last N items)
    manifest_id = str(uuid.uuid4())
    _MANIFESTS[manifest_id] = manifest
    if len(_MANIFESTS) > _MAX_ITEMS:
        # remove oldest
        try:
            oldest_key = next(iter(_MANIFESTS.keys()))
            _MANIFESTS.pop(oldest_key, None)
        except StopIteration:
            pass

    # Resolve configuration
    base_url = _get_env("OSDU_BASE_URL")
    if not base_url:
        raise HTTPException(status_code=500, detail="OSDU_BASE_URL is not configured in the environment")
    partition = body.get("partition") or _get_env("DATA_PARTITION_ID", "data")
    app_key = body.get("appKey") or _get_env("APP_KEY")
    run_id = body.get("runId") or str(uuid.uuid4())

    # Fetch access_token from existing session/auth flow
    access_token = _find_access_token(request)
    if not access_token:
        raise HTTPException(status_code=401, detail="access_token not found in session/headers/cookies")

    # Fire workflow call immediately
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

    return JSONResponse(
        {
            "status": "submitted",
            "manifestId": manifest_id,
            "runId": run_id,
            "workflowResponse": workflow_response,
        }
    )


@router.get("/manifest/last")
async def get_last_manifest() -> JSONResponse:
    """Returns the latest stored manifest (debug/helper)."""
    if not _MANIFESTS:
        raise HTTPException(status_code=404, detail="No manifests stored yet")
    # return the most recently inserted manifest
    last_key = list(_MANIFESTS.keys())[-1]
