"""
Create Record page - Create and ingest OSDU records.

Tabs:
  1. Decision Gate       → BusinessDecision (master-data)
  2. Collaboration Project → CollaborationProject (master-data)
  3. Persisted Collection → PersistedCollection (work-product-component)
  4. Activity            → ActivityTemplate + Activity (work-product-component)
  5. Generic Record      → any kind (WPC / master-data / reference-data)

Provides:
  GET  /add-dg                      → render the addgate.html template
  GET  /add-dg/reservoirs           → JSON: list of Reservoir master-data records
  GET  /add-dg/wpc-search           → JSON: search for WPC records to link
  GET  /add-dg/fetch-record         → JSON: fetch a single record by ID
  POST /add-dg/create               → JSON: build BD record, PUT to Storage API
  POST /add-dg/create-cp            → JSON: build CP record, PUT to Storage API
  POST /add-dg/create-pc            → JSON: build PersistedCollection, PUT to Storage API
  POST /add-dg/create-activity-template → JSON: build ActivityTemplate, PUT to Storage API
  POST /add-dg/create-activity      → JSON: build Activity record, PUT to Storage API
  POST /add-dg/create-generic       → JSON: build any record, PUT to Storage API
"""
from __future__ import annotations

import asyncio
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
    from .common import access_token as _at
    return _at(request)


# ──────────────────────────────────────────────────────────────────────────────
# Page
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/add-dg", response_class=HTMLResponse, summary="Add DG: create new BusinessDecision")
async def add_dg_page(request: Request):
    """Render the Add DG form page."""
    reservoirs, decision_levels = await asyncio.gather(
        _search_reservoirs(request),
        _search_decision_levels(request),
    )
    return templates.TemplateResponse(
        request, "addgate.html",
        {"reservoirs": reservoirs, "decision_levels": decision_levels},
    )


# ──────────────────────────────────────────────────────────────────────────────
# JSON APIs
# ──────────────────────────────────────────────────────────────────────────────

# ── Decision-level reference data ──────────────────────────────────────────

_FALLBACK_LEVELS = [
    {"id": "DG1", "name": "DG1 - Identify & Assess"},
    {"id": "DG2", "name": "DG2 - Concept Select"},
    {"id": "DG3", "name": "DG3 - Define & Execute"},
    {"id": "DG4", "name": "DG4 - Operate & Improve"},
]


async def _search_decision_levels(
    request: Request,
) -> List[Dict[str, str]]:
    """Fetch reference-data--DecisionLevel records from OSDU.

    Returns a list of {"id": "<code>", "name": "<display label>", "record_id": "<full OSDU id>"}.
    Falls back to a hard-coded list when the search returns nothing.
    """
    at = _access_token(request)
    search_url = f"https://{osdu.OSDU_BASE_URL}/api/search/v2/query"
    hdr = osdu.headers(at)

    payload = {
        "kind": "osdu:wks:reference-data--DecisionLevel:*",
        "query": "*",
        "limit": 50,
        "returnedFields": ["id", "data.Code", "data.Name", "data.Description"],
    }

    try:
        async with osdu.http_client(timeout=20) as client:
            r = await client.post(search_url, json=payload, headers=hdr)
            if not r.is_success:
                log.warning("DecisionLevel search failed (%s): %s", r.status_code, r.text[:300])
                return _FALLBACK_LEVELS
            results = r.json().get("results", [])
    except Exception as exc:
        log.warning("DecisionLevel search error: %s", exc)
        return _FALLBACK_LEVELS

    if not results:
        return _FALLBACK_LEVELS

    out: List[Dict[str, str]] = []
    for rec in results:
        data = rec.get("data", {})
        code = data.get("Code", "") or data.get("Name", "")
        name = data.get("Name", "") or code
        desc = data.get("Description", "")
        display = f"{code} - {desc}" if desc and desc != name else name
        out.append({"id": code, "name": display, "record_id": rec.get("id", "")})

    out.sort(key=lambda x: x["id"])
    return out


async def _search_reservoirs(
    request: Request, query: str = "*", limit: int = 50,
) -> List[Dict[str, str]]:
    """Shared helper via common.search_reservoirs (parallel fetches, no N+1)."""
    at = _access_token(request)
    from .common import search_reservoirs
    return await search_reservoirs(at, query=query, limit=limit)


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
    """Search for WPC records of a given kind - used to populate link dropdowns."""
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

    async with osdu.http_client(timeout=30) as client:
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
      rev_stats_id, rev_raw_id, production_profile_id,
      geolabelset_id, activity_id, risk_ids[], params_id, dataspace_id,
      custom_records[{label, id}]
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
    bd_slug = name.replace(" ", "-").replace("-", "-")[:80]
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
    production_profile_id = body.get("production_profile_id", "").strip()
    geolabelset_id = body.get("geolabelset_id", "").strip()
    activity_id = body.get("activity_id", "").strip()
    params_id = body.get("params_id", "").strip()
    dataspace_id = body.get("dataspace_id", "").strip()
    collection_id = body.get("collection_id", "").strip()
    risk_ids = [r.strip() for r in body.get("risk_ids", []) if r.strip()]
    custom_records: List[Dict[str, str]] = body.get("custom_records", [])

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
            "Title": "In-place volumes raw (per realisation)",
            "Selection": "Raw per-realisation volumes",
            "ParameterKindID": f"{id_prefix}:reference-data--ParameterKind:DataObject:1",
            "ParameterRoleID": f"{id_prefix}:reference-data--ParameterRole:Input:1",
            "DataObjectParameter": rev_raw_id,
            "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "InPlaceVol-raw"}],
        })

    if rev_stats_id:
        parameters.append({
            "Title": "In-place volume statistics (P10/P50/P90)",
            "Selection": "Aggregated statistics for the assessment",
            "ParameterKindID": f"{id_prefix}:reference-data--ParameterKind:DataObject:1",
            "ParameterRoleID": f"{id_prefix}:reference-data--ParameterRole:Input:1",
            "DataObjectParameter": rev_stats_id,
            "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "InPlaceVol-stats"}],
        })

    if production_profile_id:
        parameters.append({
            "Title": "Production profile",
            "Selection": "Production forecast / profile linked to the decision",
            "ParameterKindID": f"{id_prefix}:reference-data--ParameterKind:DataObject:1",
            "ParameterRoleID": f"{id_prefix}:reference-data--ParameterRole:Input:1",
            "DataObjectParameter": production_profile_id,
            "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "ProductionProfile"}],
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

    if collection_id:
        parameters.append({
            "Title": "PersistedCollection",
            "Selection": "Persisted collection of related records",
            "ParameterKindID": f"{id_prefix}:reference-data--ParameterKind:DataObject:1",
            "ParameterRoleID": f"{id_prefix}:reference-data--ParameterRole:InputReference:1",
            "DataObjectParameter": collection_id,
            "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "PersistedCollection"}],
        })

    # User-defined arbitrary records
    for crec in custom_records:
        clabel = crec.get("label", "").strip()
        cid = crec.get("id", "").strip()
        if clabel and cid:
            parameters.append({
                "Title": clabel,
                "Selection": f"User-defined record: {clabel}",
                "ParameterKindID": f"{id_prefix}:reference-data--ParameterKind:DataObject:1",
                "ParameterRoleID": f"{id_prefix}:reference-data--ParameterRole:Input:1",
                "DataObjectParameter": cid,
                "Keys": [{"ParameterKey": "artifact", "StringParameterKey": clabel.replace(' ', '-')}],
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
        async with osdu.http_client(timeout=30) as client:
            r = await client.put(storage_url, json=[bd_record], headers=hdr)
            status = r.status_code
            from .common import sanitize_upstream_error
            resp_body = sanitize_upstream_error(r) if status >= 400 else r.text[:2000]
    except Exception as e:
        log.error("Storage API PUT failed: %s", e)
        from .common import safe_error_detail
        return JSONResponse(
            {"ok": False, "error": safe_error_detail(e)},
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


# ──────────────────────────────────────────────────────────────────────────────
# Create Collaboration Project
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/add-dg/create-cp", summary="Create and ingest a new CollaborationProject")
async def create_cp(request: Request):
    """
    Build a CollaborationProject record from form data, PUT it to Storage API.

    Schema: osdu:wks:master-data--CollaborationProject:1.0.0
    Inherits: AbstractProject, AbstractProjectActivity (Parameters[]).

    Expects JSON body with fields:
      name, description, purpose, lifecycle_status, begin_date, end_date,
      namespace, parent_bd_id, dataspace_id, reservoir_id, collection_id,
      activity_id, contributor_owners, contributor_viewers,
      custom_records[{label, id}]
    """
    at = _access_token(request)
    body = await request.json()

    name = body.get("name", "").strip()
    if not name:
        raise HTTPException(400, "name is required")

    description = body.get("description", "").strip()
    purpose = body.get("purpose", "").strip()
    lifecycle_status = body.get("lifecycle_status", "Open").strip()
    begin_date = body.get("begin_date", "").strip()
    end_date = body.get("end_date", "").strip()
    namespace = body.get("namespace", "").strip()
    parent_bd_id = body.get("parent_bd_id", "").strip()
    dataspace_id = body.get("dataspace_id", "").strip()
    reservoir_id = body.get("reservoir_id", "").strip()
    collection_id = body.get("collection_id", "").strip()
    activity_id = body.get("activity_id", "").strip()
    contributor_owners = body.get("contributor_owners", "").strip()
    contributor_viewers = body.get("contributor_viewers", "").strip()
    custom_records: List[Dict[str, str]] = body.get("custom_records", [])

    # Derive ID prefix
    id_prefix = "dev"
    for ref in [parent_bd_id, reservoir_id, dataspace_id, collection_id]:
        if ref and ":" in ref:
            id_prefix = ref.split(":")[0]
            break

    # Generate CP ID
    cp_slug = name.replace(" ", "-")[:80]
    cp_uuid = str(uuid.uuid4())[:8]
    cp_id = f"{id_prefix}:master-data--CollaborationProject:{cp_slug}-{cp_uuid}:1"

    # Auto-generate namespace if empty
    if not namespace:
        namespace = f"project-{uuid.uuid4()}"

    # ACL and legal from OSDU defaults
    acl = {
        "owners": osdu.DEFAULT_OWNERS,
        "viewers": osdu.DEFAULT_VIEWERS,
    }
    legal = {
        "legaltags": [osdu.DEFAULT_LEGAL_TAG],
        "otherRelevantDataCountries": osdu.DEFAULT_COUNTRIES,
    }

    # Build Parameters[] (same pattern as BusinessDecision)
    parameters: List[Dict[str, Any]] = []

    if dataspace_id:
        parameters.append({
            "Title": "GeoModelDataspace",
            "Selection": "RDDMS ETP dataspace with geomodel data",
            "ParameterKindID": f"{id_prefix}:reference-data--ParameterKind:DataObject:",
            "ParameterRoleID": f"{id_prefix}:reference-data--ParameterRole:InputReference:",
            "DataObjectParameter": dataspace_id,
            "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "ETPDataspace"}],
        })

    if reservoir_id:
        parameters.append({
            "Title": "Reservoir scope",
            "Selection": "Master-data context for the project",
            "ParameterKindID": f"{id_prefix}:reference-data--ParameterKind:DataObject:",
            "ParameterRoleID": f"{id_prefix}:reference-data--ParameterRole:InputReference:",
            "DataObjectParameter": reservoir_id,
        })

    if collection_id:
        parameters.append({
            "Title": "PersistedCollection",
            "Selection": "Persisted collection of related records",
            "ParameterKindID": f"{id_prefix}:reference-data--ParameterKind:DataObject:",
            "ParameterRoleID": f"{id_prefix}:reference-data--ParameterRole:InputReference:",
            "DataObjectParameter": collection_id,
            "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "PersistedCollection"}],
        })

    if activity_id:
        parameters.append({
            "Title": "Activity",
            "Selection": "Related workflow activity",
            "ParameterKindID": f"{id_prefix}:reference-data--ParameterKind:DataObject:",
            "ParameterRoleID": f"{id_prefix}:reference-data--ParameterRole:Input:",
            "DataObjectParameter": activity_id,
        })

    # User-defined arbitrary records
    for crec in custom_records:
        clabel = crec.get("label", "").strip()
        cid = crec.get("id", "").strip()
        if clabel and cid:
            parameters.append({
                "Title": clabel,
                "Selection": f"User-defined record: {clabel}",
                "ParameterKindID": f"{id_prefix}:reference-data--ParameterKind:DataObject:",
                "ParameterRoleID": f"{id_prefix}:reference-data--ParameterRole:Input:",
                "DataObjectParameter": cid,
                "Keys": [{"ParameterKey": "artifact", "StringParameterKey": clabel.replace(' ', '-')}],
            })

    # Build the data block
    cp_data: Dict[str, Any] = {
        "ProjectName": name,
        "Description": description,
        "Namespace": namespace,
        "LifecycleStatusID": f"{id_prefix}:reference-data--CollaborationProjectLifecycleStatus:{lifecycle_status}:",
    }

    if purpose:
        cp_data["Purpose"] = purpose
    if begin_date:
        cp_data["ProjectBeginDate"] = begin_date + "T00:00:00Z"
    if end_date:
        cp_data["ProjectEndDate"] = end_date + "T00:00:00Z"
    if parent_bd_id:
        cp_data["ParentProjectID"] = parent_bd_id

    if parameters:
        cp_data["Parameters"] = parameters

    # ProjectContributorACL (optional)
    if contributor_owners or contributor_viewers:
        owners_list = [o.strip() for o in contributor_owners.split(",") if o.strip()] if contributor_owners else osdu.DEFAULT_OWNERS
        viewers_list = [v.strip() for v in contributor_viewers.split(",") if v.strip()] if contributor_viewers else osdu.DEFAULT_VIEWERS
        cp_data["ProjectContributorACL"] = {
            "owners": owners_list,
            "viewers": viewers_list,
        }

    # TrustedCollectionID: link to collection if provided
    if collection_id:
        cp_data["TrustedCollectionID"] = collection_id

    cp_record = {
        "id": cp_id,
        "kind": "osdu:wks:master-data--CollaborationProject:1.0.0",
        "acl": acl,
        "legal": legal,
        "data": cp_data,
    }

    # PUT to Storage API
    storage_url = f"https://{osdu.OSDU_BASE_URL}/api/storage/v2/records"
    hdr = osdu.headers(at)

    try:
        async with osdu.http_client(timeout=30) as client:
            r = await client.put(storage_url, json=[cp_record], headers=hdr)
            status = r.status_code
            from .common import sanitize_upstream_error
            resp_body = sanitize_upstream_error(r) if status >= 400 else r.text[:2000]
    except Exception as e:
        log.error("Storage API PUT (CP) failed: %s", e)
        from .common import safe_error_detail
        return JSONResponse(
            {"ok": False, "error": safe_error_detail(e)},
            status_code=502,
        )

    if status in (200, 201):
        log.info("CP created: %s (status=%d)", cp_id, status)
        return JSONResponse({
            "ok": True,
            "cp_id": cp_id,
            "status": status,
            "parameters_count": len(parameters),
            "response": resp_body,
        })
    else:
        log.warning("CP ingest failed (%d): %s", status, resp_body)
        return JSONResponse(
            {"ok": False, "cp_id": cp_id, "status": status, "response": resp_body},
            status_code=status,
        )


# ──────────────────────────────────────────────────────────────────────────────
# Create Persisted Collection
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/add-dg/create-pc", summary="Create and ingest a new PersistedCollection")
async def create_pc(request: Request):
    """
    Build a PersistedCollection WPC from form data, PUT to Storage API.

    Schema: osdu:wks:work-product-component--PersistedCollection:1.0.0

    PersistedCollection is a simple WPC that bundles multiple data object
    references under a single curated collection. Primary fields:
      - Name, Description (mandatory)
      - DataReferences[] - ordered list of OSDU record IDs
      - Tags[] - freeform string tags

    Expects JSON body with:
      name, description, tags (comma-separated string),
      data_references (array of record-ID strings),
      id_prefix (optional, default derived from first DataReference or "dev"),
      custom_id (optional, override the generated ID slug)
    """
    at = _access_token(request)
    body = await request.json()

    name = body.get("name", "").strip()
    if not name:
        raise HTTPException(400, "name is required")

    description = body.get("description", "").strip()
    data_refs: List[str] = [r.strip() for r in body.get("data_references", []) if r.strip()]
    tags_raw = body.get("tags", "").strip()
    tags: List[str] = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else []

    # Derive ID prefix
    id_prefix = body.get("id_prefix", "").strip()
    if not id_prefix:
        for ref in data_refs:
            if ":" in ref:
                id_prefix = ref.split(":")[0]
                break
    if not id_prefix:
        id_prefix = osdu.DATA_PARTITION_ID or "dev"

    # Generate ID
    custom_id = body.get("custom_id", "").strip()
    if custom_id:
        pc_id = custom_id if ":" in custom_id else (
            f"{id_prefix}:work-product-component--PersistedCollection:{custom_id}:1"
        )
    else:
        slug = name.replace(" ", "-")[:60]
        pc_uuid = str(uuid.uuid4())[:8]
        pc_id = f"{id_prefix}:work-product-component--PersistedCollection:{slug}-{pc_uuid}:1"

    # ACL and legal from OSDU defaults
    acl = {"owners": osdu.DEFAULT_OWNERS, "viewers": osdu.DEFAULT_VIEWERS}
    legal = {
        "legaltags": [osdu.DEFAULT_LEGAL_TAG],
        "otherRelevantDataCountries": osdu.DEFAULT_COUNTRIES,
    }

    pc_data: Dict[str, Any] = {
        "Name": name,
        "Description": description or f"PersistedCollection: {name}",
        "DataReferences": data_refs,
    }
    if tags:
        pc_data["Tags"] = tags

    pc_record = {
        "id": pc_id,
        "kind": "osdu:wks:work-product-component--PersistedCollection:1.0.0",
        "acl": acl,
        "legal": legal,
        "data": pc_data,
    }

    # PUT to Storage API
    storage_url = f"https://{osdu.OSDU_BASE_URL}/api/storage/v2/records"
    hdr = osdu.headers(at)

    try:
        async with osdu.http_client(timeout=30) as client:
            r = await client.put(storage_url, json=[pc_record], headers=hdr)
            status = r.status_code
            resp_body = r.text[:2000]
    except Exception as e:
        log.error("Storage API PUT (PC) failed: %s", e)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=502)

    if status in (200, 201):
        log.info("PC created: %s (status=%d, refs=%d)", pc_id, status, len(data_refs))
        return JSONResponse({
            "ok": True,
            "pc_id": pc_id,
            "status": status,
            "data_references_count": len(data_refs),
            "tags": tags,
            "response": resp_body,
        })
    else:
        log.warning("PC ingest failed (%d): %s", status, resp_body)
        return JSONResponse(
            {"ok": False, "pc_id": pc_id, "status": status, "response": resp_body},
            status_code=status,
        )


# ──────────────────────────────────────────────────────────────────────────────
# Fetch a single record (used by Activity tab to load template slots)
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/add-dg/fetch-record", summary="Fetch a single OSDU record by ID")
async def fetch_record(request: Request, id: str = Query(...)):
    """Return the data portion of a single record from Storage API."""
    at = _access_token(request)
    storage_url = f"https://{osdu.OSDU_BASE_URL}/api/storage/v2/records/{id}"
    hdr = osdu.headers(at)
    try:
        async with osdu.http_client(timeout=20) as client:
            r = await client.get(storage_url, headers=hdr)
    except Exception as e:
        log.error("Fetch record %s failed: %s", id, e)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=502)

    if r.status_code == 200:
        rec = r.json()
        return JSONResponse({"ok": True, "data": rec.get("data", {}), "kind": rec.get("kind", "")})
    else:
        return JSONResponse(
            {"ok": False, "error": r.text[:800], "status": r.status_code},
            status_code=r.status_code,
        )


# ──────────────────────────────────────────────────────────────────────────────
# Create ActivityTemplate
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/add-dg/create-activity-template", summary="Create ActivityTemplate record")
async def create_activity_template(request: Request):
    """Build and ingest an ActivityTemplate WPC record.

    Expects JSON body:
      name                 - template name
      description          - optional description
      originator           - optional originator
      parameter_templates  - list of slot dicts with Title, Description,
                             IsInput, IsOutput, MinOccurs, MaxOccurs,
                             DefaultParameterKind
    """
    at = _access_token(request)
    body = await request.json()

    name = body.get("name", "").strip()
    if not name:
        raise HTTPException(400, "name is required")

    kind = "osdu:wks:work-product-component--ActivityTemplate:1.0.0"
    id_prefix = osdu.DATA_PARTITION_ID or "dev"
    rec_uuid = str(uuid.uuid4())[:12]
    record_id = f"{id_prefix}:work-product-component--ActivityTemplate:{rec_uuid}:1"

    param_templates = body.get("parameter_templates", [])

    data: Dict[str, Any] = {
        "Name": name,
    }
    if body.get("description"):
        data["Description"] = body["description"]
    if body.get("originator"):
        data["Originator"] = body["originator"]
    if param_templates:
        data["ParameterTemplates"] = param_templates

    acl = {"owners": osdu.DEFAULT_OWNERS, "viewers": osdu.DEFAULT_VIEWERS}
    legal = {
        "legaltags": [osdu.DEFAULT_LEGAL_TAG],
        "otherRelevantDataCountries": osdu.DEFAULT_COUNTRIES,
    }

    record = {
        "id": record_id,
        "kind": kind,
        "acl": acl,
        "legal": legal,
        "data": data,
    }

    storage_url = f"https://{osdu.OSDU_BASE_URL}/api/storage/v2/records"
    hdr = osdu.headers(at)

    try:
        async with osdu.http_client(timeout=30) as client:
            r = await client.put(storage_url, json=[record], headers=hdr)
            status = r.status_code
            resp_body = r.text[:2000]
    except Exception as e:
        log.error("Storage API PUT (ActivityTemplate) failed: %s", e)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=502)

    if status in (200, 201):
        log.info("ActivityTemplate created: %s (%d params, status=%d)", record_id, len(param_templates), status)
        return JSONResponse({
            "ok": True,
            "record_id": record_id,
            "kind": kind,
            "status": status,
            "param_count": len(param_templates),
            "response": resp_body,
        })
    else:
        log.warning("ActivityTemplate ingest failed (%d): %s", status, resp_body)
        return JSONResponse(
            {"ok": False, "record_id": record_id, "kind": kind,
             "status": status, "response": resp_body},
            status_code=status,
        )


# ──────────────────────────────────────────────────────────────────────────────
# Create Activity
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/add-dg/create-activity", summary="Create Activity record")
async def create_activity(request: Request):
    """Build and ingest an Activity WPC record.

    Expects JSON body:
      name              - activity name
      description       - optional description
      originator        - optional originator
      template_id       - ActivityTemplate record ID
      workflow_status   - e.g. "Completed"
      creation_datetime - ISO date/time string
      parent_object_id  - optional parent master-data ID
      parameters        - list of {title, role, kind, value, desc}
    """
    at = _access_token(request)
    body = await request.json()

    name = body.get("name", "").strip()
    if not name:
        raise HTTPException(400, "name is required")

    kind = "osdu:wks:work-product-component--Activity:1.0.0"
    id_prefix = osdu.DATA_PARTITION_ID or "dev"
    rec_uuid = str(uuid.uuid4())[:12]
    record_id = f"{id_prefix}:work-product-component--Activity:{rec_uuid}:1"

    data: Dict[str, Any] = {
        "Name": name,
    }
    if body.get("description"):
        data["Description"] = body["description"]
    if body.get("originator"):
        data["Originator"] = body["originator"]
    if body.get("template_id"):
        data["ActivityTemplateID"] = body["template_id"]
    if body.get("workflow_status"):
        data["WorkflowStatus"] = body["workflow_status"]
    if body.get("creation_datetime"):
        data["CreationDateTime"] = body["creation_datetime"]
    if body.get("parent_object_id"):
        data["ParentObjectID"] = body["parent_object_id"]

    # Build Parameters array from front-end param entries
    raw_params = body.get("parameters", [])
    parameters: List[Dict[str, Any]] = []
    for p in raw_params:
        title = p.get("title", "").strip()
        if not title:
            continue
        role = p.get("role", "input")
        pk = p.get("kind", "string")
        value = p.get("value", "")
        desc = p.get("desc", "")

        # Build the ParameterKindID and ParameterRoleID ref-data URIs
        kind_map = {"string": "String", "integer": "Integer", "DataObject": "DataObject"}
        role_map = {"input": "Input", "output": "Output"}
        pk_label = kind_map.get(pk, "String")
        role_label = role_map.get(role, "Input")

        entry: Dict[str, Any] = {
            "Title": title,
            "Description": desc,
            "ParameterKindID": f"{id_prefix}:reference-data--ParameterKind:{pk_label}:",
            "ParameterRoleID": f"{id_prefix}:reference-data--ParameterRole:{role_label}:",
        }

        # Set the typed value field
        if pk == "integer":
            try:
                entry["IntegerParameter"] = int(value)
            except (ValueError, TypeError):
                entry["StringParameter"] = value
        elif pk == "DataObject":
            entry["DataObjectParameter"] = value
        else:
            entry["StringParameter"] = value

        parameters.append(entry)

    if parameters:
        data["Parameters"] = parameters

    acl = {"owners": osdu.DEFAULT_OWNERS, "viewers": osdu.DEFAULT_VIEWERS}
    legal = {
        "legaltags": [osdu.DEFAULT_LEGAL_TAG],
        "otherRelevantDataCountries": osdu.DEFAULT_COUNTRIES,
    }

    record = {
        "id": record_id,
        "kind": kind,
        "acl": acl,
        "legal": legal,
        "data": data,
    }

    storage_url = f"https://{osdu.OSDU_BASE_URL}/api/storage/v2/records"
    hdr = osdu.headers(at)

    try:
        async with osdu.http_client(timeout=30) as client:
            r = await client.put(storage_url, json=[record], headers=hdr)
            status = r.status_code
            resp_body = r.text[:2000]
    except Exception as e:
        log.error("Storage API PUT (Activity) failed: %s", e)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=502)

    if status in (200, 201):
        log.info("Activity created: %s (template=%s, %d params, status=%d)",
                 record_id, body.get("template_id", "none"), len(parameters), status)
        return JSONResponse({
            "ok": True,
            "record_id": record_id,
            "kind": kind,
            "status": status,
            "param_count": len(parameters),
            "response": resp_body,
        })
    else:
        log.warning("Activity ingest failed (%d): %s", status, resp_body)
        return JSONResponse(
            {"ok": False, "record_id": record_id, "kind": kind,
             "status": status, "response": resp_body},
            status_code=status,
        )


# ──────────────────────────────────────────────────────────────────────────────
# Create Generic Record (WPC / master-data / reference-data)
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/add-dg/create-generic", summary="Create and ingest an arbitrary OSDU record")
async def create_generic(request: Request):
    """
    Build a generic OSDU record from user-supplied kind + data fields.

    The data block is assembled from a list of field entries, each with:
      key    - dot-separated path  (e.g. "Name", "Description", "Tags[0]")
      value  - string value (auto-converted to number/bool/null if possible)
      type   - "string" | "number" | "boolean" | "json" | "array" | "auto"

    Array and nested-object fields use dot-notation for keys:
      "Tags"       type=array  value="Drogon, EvidencePackage"
      "RiskIDs"    type=array  value="dev:master-data--Risk:foo:1, dev:..."
      "ext.custom" type=string value="hello"

    Expects JSON body with:
      kind  - full OSDU kind string (e.g. "osdu:wks:master-data--Risk:1.2.0")
      record_id - optional explicit record ID; auto-generated if empty
      fields - [{key, value, type}] list building the data block
    """
    at = _access_token(request)
    body = await request.json()

    kind = body.get("kind", "").strip()
    if not kind:
        raise HTTPException(400, "kind is required")

    record_id = body.get("record_id", "").strip()
    fields: List[Dict[str, str]] = body.get("fields", [])

    # Derive ID prefix and type fragment from kind
    # kind = "osdu:wks:master-data--Risk:1.2.0"
    # → type_frag = "master-data--Risk"
    kind_parts = kind.split(":")
    type_frag = kind_parts[2] if len(kind_parts) > 2 else "record"
    id_prefix = body.get("id_prefix", "").strip() or osdu.DATA_PARTITION_ID or "dev"

    if not record_id:
        rec_uuid = str(uuid.uuid4())[:12]
        record_id = f"{id_prefix}:{type_frag}:{rec_uuid}:1"

    # Build the data block from fields
    data: Dict[str, Any] = {}
    for f in fields:
        key = f.get("key", "").strip()
        raw_val = f.get("value", "")
        ftype = f.get("type", "auto").strip().lower()
        if not key:
            continue

        val: Any = raw_val
        if ftype == "number":
            try:
                val = float(raw_val) if "." in str(raw_val) else int(raw_val)
            except (ValueError, TypeError):
                val = raw_val
        elif ftype == "boolean":
            val = raw_val.lower() in ("true", "1", "yes")
        elif ftype == "json":
            import json as _json
            try:
                val = _json.loads(raw_val)
            except _json.JSONDecodeError:
                val = raw_val
        elif ftype == "array":
            # Comma-separated → list; try JSON parse first
            import json as _json
            try:
                val = _json.loads(raw_val)
                if not isinstance(val, list):
                    val = [val]
            except _json.JSONDecodeError:
                val = [v.strip() for v in raw_val.split(",") if v.strip()]
        elif ftype == "auto":
            val = _auto_type(raw_val)

        # Support dot-notation for nested keys (e.g. "ext.custom" → {ext: {custom: val}})
        _set_nested(data, key, val)

    # ACL and legal from OSDU defaults
    acl = {"owners": osdu.DEFAULT_OWNERS, "viewers": osdu.DEFAULT_VIEWERS}
    legal = {
        "legaltags": [osdu.DEFAULT_LEGAL_TAG],
        "otherRelevantDataCountries": osdu.DEFAULT_COUNTRIES,
    }

    record = {
        "id": record_id,
        "kind": kind,
        "acl": acl,
        "legal": legal,
        "data": data,
    }

    # PUT to Storage API
    storage_url = f"https://{osdu.OSDU_BASE_URL}/api/storage/v2/records"
    hdr = osdu.headers(at)

    try:
        async with osdu.http_client(timeout=30) as client:
            r = await client.put(storage_url, json=[record], headers=hdr)
            status = r.status_code
            resp_body = r.text[:2000]
    except Exception as e:
        log.error("Storage API PUT (generic) failed: %s", e)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=502)

    if status in (200, 201):
        log.info("Generic record created: %s kind=%s (status=%d)", record_id, kind, status)
        return JSONResponse({
            "ok": True,
            "record_id": record_id,
            "kind": kind,
            "status": status,
            "field_count": len(fields),
            "response": resp_body,
        })
    else:
        log.warning("Generic ingest failed (%d): %s", status, resp_body)
        return JSONResponse(
            {"ok": False, "record_id": record_id, "kind": kind,
             "status": status, "response": resp_body},
            status_code=status,
        )


def _auto_type(val: str) -> Any:
    """Best-effort auto-type conversion for generic field values."""
    if val == "":
        return ""
    low = val.lower()
    if low in ("true", "false"):
        return low == "true"
    if low == "null":
        return None
    try:
        return int(val)
    except ValueError:
        pass
    try:
        return float(val)
    except ValueError:
        pass
    return val


def _set_nested(d: Dict[str, Any], dotkey: str, val: Any) -> None:
    """Set a value in a nested dict using dot-notation. E.g. 'ext.custom' → d[ext][custom]."""
    parts = dotkey.split(".")
    for part in parts[:-1]:
        if part not in d or not isinstance(d[part], dict):
            d[part] = {}
        d = d[part]
    d[parts[-1]] = val
