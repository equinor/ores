"""
Add DG page — Create and ingest a new BusinessDecision for an existing Reservoir.

Provides:
  GET  /add-dg               → render the addgate.html template
  GET  /add-dg/reservoirs    → JSON: list of Reservoir master-data records
  GET  /add-dg/wpc-search    → JSON: search for WPC records to link
  POST /add-dg/create        → JSON: build BD record, PUT to Storage API
"""
from __future__ import annotations

import logging
import os
import uuid
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from . import osdu

log = logging.getLogger("rddms-admin.addgate")

router = APIRouter()
templates = Jinja2Templates(
    directory=os.path.join(os.path.dirname(__file__), "templates"),
)


def _access_token(request: Request) -> str:
    at = getattr(request.state, "access_token", None)
    if not at:
        raise HTTPException(401, "Authentication required")
    return at


# ──────────────────────────────────────────────────────────────────────────────
# Page
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/add-dg", response_class=HTMLResponse, summary="Add DG: create new BusinessDecision")
async def add_dg_page(request: Request):
    """Render the Add DG form page."""
    reservoirs = await _search_reservoirs(request)
    return templates.TemplateResponse(
        "addgate.html",
        {"request": request, "reservoirs": reservoirs},
    )


# ──────────────────────────────────────────────────────────────────────────────
# JSON APIs
# ──────────────────────────────────────────────────────────────────────────────

async def _search_reservoirs(
    request: Request, query: str = "*", limit: int = 50,
) -> List[Dict[str, str]]:
    """Search for Reservoir master-data records, de-dupe by base ID."""
    at = _access_token(request)
    search_url = f"https://{osdu.OSDU_BASE_URL}/api/search/v2/query"
    storage_url = f"https://{osdu.OSDU_BASE_URL}/api/storage/v2/records"
    hdr = osdu.headers(at)

    payload = {
        "kind": "osdu:wks:master-data--Reservoir:2.0.0",
        "query": query,
        "limit": min(int(limit), 100),
        "returnedFields": ["id", "kind", "version"],
        "trackTotalCount": True,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(search_url, json=payload, headers=hdr)
        if not r.is_success:
            log.warning("Reservoir search failed: %s", r.text[:300])
            return []
        results = r.json().get("results", [])

    # De-dupe by base ID (strip version suffix), keep highest version
    seen: Dict[str, Dict] = {}
    for rec in results:
        rid = rec.get("id", "")
        base = rid.rsplit(":", 1)[0] if ":" in rid else rid
        ver = rec.get("version", 0)
        if base not in seen or ver > seen[base].get("version", 0):
            seen[base] = rec

    out = []
    for rec in seen.values():
        rid = rec.get("id", "")
        # Fetch the name from storage
        name = rid.split("--Reservoir:")[-1].split(":")[0] if "--Reservoir:" in rid else rid
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                sr = await client.get(f"{storage_url}/{rid}", headers=hdr)
                if sr.is_success:
                    sdata = sr.json()
                    name = sdata.get("data", {}).get("Name", name)
        except Exception:
            pass
        out.append({"id": rid, "name": name})

    out.sort(key=lambda x: x["name"])
    return out


@router.get("/add-dg/reservoirs", summary="JSON: reservoir list")
async def reservoirs_json(request: Request):
    reservoirs = await _search_reservoirs(request)
    return JSONResponse(reservoirs)


@router.get("/add-dg/wpc-search", summary="JSON: search WPCs by kind")
async def wpc_search(
    request: Request,
    kind: str = Query("", description="Kind to search for"),
    q: str = Query("*", description="Search query"),
    limit: int = Query(20),
):
    """Search for WPC records of a given kind — used to populate link dropdowns."""
    at = _access_token(request)
    search_url = f"https://{osdu.OSDU_BASE_URL}/api/search/v2/query"
    storage_url = f"https://{osdu.OSDU_BASE_URL}/api/storage/v2/records"
    hdr = osdu.headers(at)

    if not kind:
        return JSONResponse([])

    payload = {
        "kind": kind,
        "query": q,
        "limit": min(int(limit), 50),
        "returnedFields": ["id", "kind", "version", "data.Name", "data.Description"],
    }

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(search_url, json=payload, headers=hdr)
        if not r.is_success:
            return JSONResponse([])
        results = r.json().get("results", [])

    out = []
    for rec in results:
        rid = rec.get("id", "")
        data = rec.get("data", {})
        name = data.get("Name", "") or data.get("Description", "") or rid
        out.append({"id": rid, "name": name, "kind": rec.get("kind", "")})

    return JSONResponse(out)


@router.post("/add-dg/create", summary="Create and ingest a new BusinessDecision")
async def create_bd(request: Request):
    """
    Build a BusinessDecision record from form data, PUT it to Storage API.

    Expects JSON body with fields:
      reservoir_id, name, description, decision_level, approval_status,
      decision_date, decision_due_date, decision_summary,
      rev_stats_id, rev_raw_id, geolabelset_id, activity_id, risk_ids[],
      params_id, dataspace_id
    """
    at = _access_token(request)
    body = await request.json()

    reservoir_id = body.get("reservoir_id", "").strip()
    if not reservoir_id:
        raise HTTPException(400, "reservoir_id is required")

    name = body.get("name", "").strip()
    if not name:
        raise HTTPException(400, "name is required")

    # ID prefix from the reservoir_id (e.g. "dev")
    id_prefix = reservoir_id.split(":")[0] if ":" in reservoir_id else "dev"

    # Generate a deterministic-ish BD ID from the name
    bd_slug = name.replace(" ", "-").replace("—", "-")[:80]
    bd_id = f"{id_prefix}:master-data--BusinessDecision:{bd_slug}:1"

    decision_level = body.get("decision_level", "DG1")
    approval_status = body.get("approval_status", "Pending")
    description = body.get("description", "")
    decision_date = body.get("decision_date", "")
    decision_due_date = body.get("decision_due_date", "")
    decision_summary = body.get("decision_summary", "")
    project_name = body.get("project_name", "")

    # Optional linked record IDs
    rev_stats_id = body.get("rev_stats_id", "").strip()
    rev_raw_id = body.get("rev_raw_id", "").strip()
    geolabelset_id = body.get("geolabelset_id", "").strip()
    activity_id = body.get("activity_id", "").strip()
    params_id = body.get("params_id", "").strip()
    dataspace_id = body.get("dataspace_id", "").strip()
    risk_ids = [r.strip() for r in body.get("risk_ids", []) if r.strip()]

    # ACL and legal from OSDU defaults
    acl = {
        "owners": osdu.DEFAULT_OWNERS,
        "viewers": osdu.DEFAULT_VIEWERS,
    }
    legal = {
        "legaltags": [osdu.DEFAULT_LEGAL_TAG],
        "otherRelevantDataCountries": osdu.DEFAULT_COUNTRIES,
    }

    # Build Parameters[] array
    parameters: List[Dict[str, Any]] = []

    if rev_raw_id:
        parameters.append({
            "Title": "Raw volumes (per realisation)",
            "Selection": "Raw per-realisation volumes",
            "ParameterKindID": f"{id_prefix}:reference-data--ParameterKind:DataObject:1",
            "ParameterRoleID": f"{id_prefix}:reference-data--ParameterRole:Input:1",
            "DataObjectParameter": rev_raw_id,
            "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "REV-raw"}],
        })

    if rev_stats_id:
        parameters.append({
            "Title": "Statistical volumes (P10/P50/P90)",
            "Selection": "Aggregated statistics for the assessment",
            "ParameterKindID": f"{id_prefix}:reference-data--ParameterKind:DataObject:1",
            "ParameterRoleID": f"{id_prefix}:reference-data--ParameterRole:Input:1",
            "DataObjectParameter": rev_stats_id,
            "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "REV-stats"}],
        })

    if geolabelset_id:
        parameters.append({
            "Title": "GeoLabelSet",
            "Selection": "Headline KPI values per segment",
            "ParameterKindID": f"{id_prefix}:reference-data--ParameterKind:DataObject:1",
            "ParameterRoleID": f"{id_prefix}:reference-data--ParameterRole:Input:1",
            "DataObjectParameter": geolabelset_id,
            "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "GeoLabelSet"}],
        })

    if params_id:
        parameters.append({
            "Title": "Input parameters",
            "Selection": "Per-segment input parameters",
            "ParameterKindID": f"{id_prefix}:reference-data--ParameterKind:DataObject:1",
            "ParameterRoleID": f"{id_prefix}:reference-data--ParameterRole:Input:1",
            "DataObjectParameter": params_id,
            "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "ColumnBasedTable-params"}],
        })

    if dataspace_id:
        parameters.append({
            "Title": "GeoModelDataspace",
            "Selection": "RDDMS ETP dataspace with geomodel EPC files",
            "ParameterKindID": f"{id_prefix}:reference-data--ParameterKind:DataObject:1",
            "ParameterRoleID": f"{id_prefix}:reference-data--ParameterRole:InputReference:1",
            "DataObjectParameter": dataspace_id,
            "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "ETPDataspace"}],
        })

    # Reservoir is always added as a parameter
    parameters.append({
        "Title": "Reservoir scope",
        "Selection": "Master-data context for the decision",
        "ParameterKindID": f"{id_prefix}:reference-data--ParameterKind:DataObject:1",
        "ParameterRoleID": f"{id_prefix}:reference-data--ParameterRole:InputReference:1",
        "DataObjectParameter": reservoir_id,
    })

    # Build PriorActivityIDs
    prior_activity_ids: List[str] = []
    if activity_id:
        prior_activity_ids.append(activity_id)
    elif rev_raw_id or rev_stats_id or params_id:
        prior_activity_ids = [x for x in [rev_raw_id, rev_stats_id, params_id] if x]

    # Build the record
    bd_data: Dict[str, Any] = {
        "Name": name,
        "Description": description,
        "ProjectName": project_name,
        "DecisionLevelID": f"{id_prefix}:reference-data--DecisionLevel:{decision_level}:1",
        "ApprovalStatusID": f"{id_prefix}:reference-data--DecisionApprovalStatus:{approval_status}:1",
        "RiskIDs": risk_ids,
        "PriorActivityIDs": prior_activity_ids,
        "Parameters": parameters,
        "ancestry": {
            "parents": [activity_id] if activity_id else [],
            "children": [],
        },
    }

    if decision_date:
        bd_data["DecisionDate"] = decision_date
    if decision_due_date:
        bd_data["DecisionDueDate"] = decision_due_date
    if decision_summary:
        bd_data["DecisionSummary"] = decision_summary

    bd_record = {
        "id": bd_id,
        "kind": "osdu:wks:master-data--BusinessDecision:1.0.0",
        "acl": acl,
        "legal": legal,
        "data": bd_data,
    }

    # PUT to Storage API
    storage_url = f"https://{osdu.OSDU_BASE_URL}/api/storage/v2/records"
    hdr = osdu.headers(at)

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.put(storage_url, json=[bd_record], headers=hdr)
            status = r.status_code
            resp_body = r.text[:2000]
    except Exception as e:
        log.error("Storage API PUT failed: %s", e)
        return JSONResponse(
            {"ok": False, "error": str(e)},
            status_code=502,
        )

    if status in (200, 201):
        log.info("BD created: %s (status=%d)", bd_id, status)
        return JSONResponse({
            "ok": True,
            "bd_id": bd_id,
            "status": status,
            "parameters_count": len(parameters),
            "risk_count": len(risk_ids),
            "response": resp_body,
        })
    else:
        log.warning("BD ingest failed (%d): %s", status, resp_body)
        return JSONResponse(
            {"ok": False, "bd_id": bd_id, "status": status, "response": resp_body},
            status_code=status,
        )
