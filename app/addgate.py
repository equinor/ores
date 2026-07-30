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
  POST /add-dg/create-package       → JSON: batch-create BD + linked records in one shot
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from . import osdu

# ── ActivityStateTemplates (loaded once from bundled JSON) ──────────────────
_TEMPLATES_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "demo", "activity_state_templates.json"
)
_ACTIVITY_STATE_TEMPLATES: List[Dict[str, Any]] = []
if os.path.isfile(_TEMPLATES_PATH):
    with open(_TEMPLATES_PATH, "r") as _f:
        _ACTIVITY_STATE_TEMPLATES = json.load(_f)

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


# ── ActivityStateTemplates endpoint ──────────────────────────────────────────

@router.get("/add-dg/schedule-templates", summary="JSON: ActivityStateTemplate list")
async def schedule_templates_json(request: Request):
    """Return all ActivityStateTemplate WPCs for the schedule/milestone UI."""
    out = []
    for tpl in _ACTIVITY_STATE_TEMPLATES:
        data = tpl.get("data", {})
        out.append({
            "id": tpl.get("id", ""),
            "name": data.get("Name", ""),
            "description": data.get("Description", ""),
            "project_type_id": data.get("ProjectTypeID", ""),
            "milestones": data.get("Milestones", []),
        })
    return JSONResponse(out)


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

    # Well-specific linked records (WPC / Dev Well / Exploration presets)
    well_prod_id = body.get("well_prod_id", "").strip()
    well_inj_id = body.get("well_inj_id", "").strip()
    wellbore_id = body.get("wellbore_id", "").strip()
    trajectory_id = body.get("trajectory_id", "").strip()
    devconcept_id = body.get("devconcept_id", "").strip()
    wellcost_id = body.get("wellcost_id", "").strip()
    tubular_id = body.get("tubular_id", "").strip()
    drilling_collection_id = body.get("drilling_collection_id", "").strip()
    collab_project_id = body.get("collab_project_id", "").strip()

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

    # ── Well-specific parameters (WPC / Dev Well / Exploration) ──
    if well_prod_id:
        parameters.append({
            "Title": "Planned producer well",
            "Selection": "Development/production well subject of this decision",
            "ParameterKindID": f"{id_prefix}:reference-data--ParameterKind:DataObject:1",
            "ParameterRoleID": f"{id_prefix}:reference-data--ParameterRole:Output:1",
            "DataObjectParameter": well_prod_id,
            "Keys": [{"ParameterKey": "wellType", "StringParameterKey": "Producer"}],
        })

    if well_inj_id:
        parameters.append({
            "Title": "Planned injector well",
            "Selection": "Injection well subject of this decision",
            "ParameterKindID": f"{id_prefix}:reference-data--ParameterKind:DataObject:1",
            "ParameterRoleID": f"{id_prefix}:reference-data--ParameterRole:Output:1",
            "DataObjectParameter": well_inj_id,
            "Keys": [{"ParameterKey": "wellType", "StringParameterKey": "Injector"}],
        })

    if wellbore_id:
        parameters.append({
            "Title": "Target wellbore",
            "Selection": "Wellbore reference for well decision",
            "ParameterKindID": f"{id_prefix}:reference-data--ParameterKind:DataObject:1",
            "ParameterRoleID": f"{id_prefix}:reference-data--ParameterRole:Output:1",
            "DataObjectParameter": wellbore_id,
            "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "Wellbore"}],
        })

    if trajectory_id:
        parameters.append({
            "Title": "Wellbore trajectory",
            "Selection": "Planned or as-drilled wellbore trajectory",
            "ParameterKindID": f"{id_prefix}:reference-data--ParameterKind:DataObject:1",
            "ParameterRoleID": f"{id_prefix}:reference-data--ParameterRole:Input:1",
            "DataObjectParameter": trajectory_id,
            "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "WellboreTrajectory"}],
        })

    if devconcept_id:
        parameters.append({
            "Title": "Development Concept",
            "Selection": "Well plan, facilities, drainage strategy for this decision",
            "ParameterKindID": f"{id_prefix}:reference-data--ParameterKind:DataObject:1",
            "ParameterRoleID": f"{id_prefix}:reference-data--ParameterRole:Input:1",
            "DataObjectParameter": devconcept_id,
            "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "DevelopmentConcept"}],
        })

    if wellcost_id:
        parameters.append({
            "Title": "Well Cost AFE",
            "Selection": "Cost breakdown per phase (AFE estimate)",
            "ParameterKindID": f"{id_prefix}:reference-data--ParameterKind:DataObject:1",
            "ParameterRoleID": f"{id_prefix}:reference-data--ParameterRole:Input:1",
            "DataObjectParameter": wellcost_id,
            "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "WellCostAFE"}],
        })

    if tubular_id:
        parameters.append({
            "Title": "Completion design (TubularAssembly)",
            "Selection": "Casing, completion, tubing design for well",
            "ParameterKindID": f"{id_prefix}:reference-data--ParameterKind:DataObject:1",
            "ParameterRoleID": f"{id_prefix}:reference-data--ParameterRole:Input:1",
            "DataObjectParameter": tubular_id,
            "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "TubularAssembly"}],
        })

    if drilling_collection_id:
        parameters.append({
            "Title": "Drilling evidence package",
            "Selection": "Trajectories, drilling programs, wellbore reports",
            "ParameterKindID": f"{id_prefix}:reference-data--ParameterKind:DataObject:1",
            "ParameterRoleID": f"{id_prefix}:reference-data--ParameterRole:InputReference:1",
            "DataObjectParameter": drilling_collection_id,
            "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "DrillingCollection"}],
        })

    if collab_project_id:
        parameters.append({
            "Title": "Collaboration project",
            "Selection": "Long-lived project namespace for this field development",
            "ParameterKindID": f"{id_prefix}:reference-data--ParameterKind:DataObject:1",
            "ParameterRoleID": f"{id_prefix}:reference-data--ParameterRole:InputReference:1",
            "DataObjectParameter": collab_project_id,
            "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "CollaborationProject"}],
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

    # ── Well references (for WPC / Dev Well / Exploration) ──
    if collab_project_id:
        bd_data["CollaborationProjectID"] = collab_project_id
    if collection_id:
        bd_data["EvidenceCollectionID"] = collection_id
    if drilling_collection_id:
        bd_data["DrillingEvidenceCollectionID"] = drilling_collection_id

    # ancestry.children → wells being created by this decision
    well_children = [w for w in [well_prod_id, well_inj_id, wellbore_id] if w]
    if well_children:
        bd_data["ancestry"]["children"] = well_children

    # ── ActivityStates from schedule template ──
    activity_states: List[Dict[str, Any]] = body.get("activity_states", [])
    if activity_states:
        bd_data["ActivityStates"] = activity_states
        # Set ext.equinor.ActivityStateTemplateID if a template was used
        template_id = body.get("activity_state_template_id", "").strip()
        project_type_id = body.get("project_type_id", "").strip()
        if template_id or project_type_id:
            ext_eq: Dict[str, Any] = bd_data.setdefault("ext", {}).setdefault("equinor", {})
            if template_id:
                ext_eq["ActivityStateTemplateID"] = template_id
            if project_type_id:
                ext_eq["ProjectTypeID"] = project_type_id

    # ── Alternatives (ext.equinor.Alternatives[]) ──
    alternatives: List[Dict[str, Any]] = body.get("alternatives", [])
    if alternatives:
        ext_eq = bd_data.setdefault("ext", {}).setdefault("equinor", {})
        ext_eq["Alternatives"] = [
            {
                "Name": a.get("name", ""),
                "Rank": a.get("rank", i + 1),
                "Rationale": a.get("rationale", ""),
                "RecommendedAction": a.get("action", "Consider"),
            }
            for i, a in enumerate(alternatives) if a.get("name")
        ]

    # ── Economics (ProjectSpecifications[]) ──
    economics: List[Dict[str, Any]] = body.get("economics", [])
    if economics:
        bd_data["ProjectSpecifications"] = [
            {
                "ParameterTypeID": f"{id_prefix}:reference-data--ParameterType:{e['type']}:",
                "DataQuantityParameter": float(e["value"]) if e.get("value") else 0,
                "UnitOfMeasureID": f"{id_prefix}:reference-data--UnitOfMeasure:{e.get('unit', '')}:",
            }
            for e in economics if e.get("type") and e.get("value")
        ]

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
# Create ActivityStateTemplate (Schedule Template)
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/add-dg/create-schedule-template", summary="Create ActivityStateTemplate WPC")
async def create_schedule_template(request: Request):
    """Build and ingest an ActivityStateTemplate WPC record.

    Expects JSON body:
      name, description, project_type_id,
      milestones[{Sequence, MilestoneID, Name, TypicalDurationMonths}]
    """
    at = _access_token(request)
    body = await request.json()

    name = body.get("name", "").strip()
    if not name:
        raise HTTPException(400, "name is required")

    description = body.get("description", "").strip()
    project_type_id = body.get("project_type_id", "").strip()
    milestones: List[Dict[str, Any]] = body.get("milestones", [])

    if not milestones:
        raise HTTPException(400, "At least one milestone is required")

    # Derive ID prefix
    id_prefix = "dev"
    if project_type_id and ":" in project_type_id:
        id_prefix = project_type_id.split(":")[0]

    # Generate ID from name
    slug = name.replace(" ", "-").replace("/", "-")[:60]
    record_id = f"{id_prefix}:work-product-component--ActivityStateTemplate:{slug}:1"

    acl = {"owners": osdu.DEFAULT_OWNERS, "viewers": osdu.DEFAULT_VIEWERS}
    legal = {
        "legaltags": [osdu.DEFAULT_LEGAL_TAG],
        "otherRelevantDataCountries": osdu.DEFAULT_COUNTRIES,
    }

    data: Dict[str, Any] = {
        "Name": name,
        "Description": description or f"Schedule milestone template: {name}",
        "Milestones": milestones,
    }
    if project_type_id:
        data["ProjectTypeID"] = project_type_id

    record = {
        "id": record_id,
        "kind": "osdu:wks:work-product-component--ActivityStateTemplate:1.0.0",
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
            from .common import sanitize_upstream_error
            resp_body = sanitize_upstream_error(r) if status >= 400 else r.text[:2000]
    except Exception as e:
        log.error("Storage API PUT (ScheduleTemplate) failed: %s", e)
        from .common import safe_error_detail
        return JSONResponse({"ok": False, "error": safe_error_detail(e)}, status_code=502)

    if status in (200, 201):
        log.info("ActivityStateTemplate created: %s (status=%d)", record_id, status)
        # Also add to in-memory templates list for immediate availability
        _ACTIVITY_STATE_TEMPLATES.append(record)
        return JSONResponse({
            "ok": True,
            "record_id": record_id,
            "status": status,
            "milestone_count": len(milestones),
            "response": resp_body,
        })
    else:
        log.warning("ActivityStateTemplate ingest failed (%d): %s", status, resp_body)
        return JSONResponse(
            {"ok": False, "record_id": record_id, "status": status, "response": resp_body},
            status_code=status,
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


# ──────────────────────────────────────────────────────────────────────────────
# Batch Create Package - create BD + standard linked records in one shot
# ──────────────────────────────────────────────────────────────────────────────

# Default risk scaffolds per preset type
_WPC_DEFAULT_RISKS = [
    {"Name": "Geological uncertainty – target zone presence/quality",
     "Description": "Risk that target formation is absent, thinner, or lower quality than predicted from offset wells.",
     "RiskCategoryID": "Subsurface", "InherentProbability": "Medium", "InherentSeverity": "High",
     "MitigationPlan": "Pilot well data acquisition; real-time LWD evaluation during drilling."},
    {"Name": "Drilling hazard – shallow gas / HP zone",
     "Description": "Risk of encountering shallow gas or abnormal pressure during drilling operations.",
     "RiskCategoryID": "Drilling", "InherentProbability": "Low", "InherentSeverity": "High",
     "MitigationPlan": "Detailed well planning; managed pressure drilling capability on standby."},
    {"Name": "Well cost overrun (>20% AFE)",
     "Description": "Risk of significant cost overrun due to operational issues, weather, or subsurface surprises.",
     "RiskCategoryID": "Commercial", "InherentProbability": "Medium", "InherentSeverity": "Medium",
     "MitigationPlan": "Contingency budget included; clear decision tree for non-productive time."},
    {"Name": "HSE – environmental / personnel safety",
     "Description": "Risk of HSE incident during drilling and completion operations.",
     "RiskCategoryID": "HSE", "InherentProbability": "Low", "InherentSeverity": "Critical",
     "MitigationPlan": "Full HAZOP and HAZID completed; bridging document with rig operator."},
    {"Name": "Formation water incompatibility (scale/barium)",
     "Description": "Risk that formation water chemistry prevents water injection strategy.",
     "RiskCategoryID": "Subsurface", "InherentProbability": "Medium", "InherentSeverity": "Medium",
     "MitigationPlan": "Formation water sampling in pilot well; alternative drainage strategies prepared."},
]

_EXPLORATION_DEFAULT_RISKS = [
    {"Name": "Trap / seal integrity",
     "Description": "Risk that the trapping mechanism is breached or the seal is insufficient to retain hydrocarbons.",
     "RiskCategoryID": "Subsurface", "InherentProbability": "Low", "InherentSeverity": "High",
     "MitigationPlan": "Seismic amplitude analysis and fault seal assessment completed."},
    {"Name": "Reservoir presence / quality",
     "Description": "Risk that target reservoir is absent or has insufficient quality for commercial flow rates.",
     "RiskCategoryID": "Subsurface", "InherentProbability": "Medium", "InherentSeverity": "High",
     "MitigationPlan": "Offset well analogues and seismic inversion support presence prediction."},
    {"Name": "Hydrocarbon charge / migration",
     "Description": "Risk that hydrocarbons have not migrated to or been retained in the prospect.",
     "RiskCategoryID": "Subsurface", "InherentProbability": "Low", "InherentSeverity": "Critical",
     "MitigationPlan": "Basin modelling shows viable migration pathway; DHI indicators present on seismic."},
    {"Name": "Drilling operations risk",
     "Description": "Risk of operational issues during exploration well drilling.",
     "RiskCategoryID": "Drilling", "InherentProbability": "Medium", "InherentSeverity": "Medium",
     "MitigationPlan": "Detailed well design with offset well learnings; contingency plans for key scenarios."},
]


@router.post("/add-dg/create-package", summary="Batch-create BD + linked records")
async def create_package(request: Request):
    """
    One-click full package creation: creates standard linked records
    (Risks, PersistedCollection, optionally CollaborationProject) and then
    creates the BusinessDecision record linking everything together.

    This reduces the manual work of creating records one-by-one across
    multiple tabs and copying IDs back and forth.

    Expects JSON body with all standard BD fields PLUS:
      preset_type      - "wpc" | "exploration" | "dev_well" | "field_dev" | ""
      create_risks     - bool: auto-create standard risks for this preset
      create_collection - bool: auto-create PersistedCollection evidence package
      create_collab_project - bool: auto-create CollaborationProject
      risk_overrides   - [{Name, Description, ...}] optional custom risk list
    """
    at = _access_token(request)
    body = await request.json()

    preset_type = body.get("preset_type", "").strip()
    create_risks = body.get("create_risks", True)
    create_collection = body.get("create_collection", True)
    create_collab_project = body.get("create_collab_project", False)

    reservoir_id = body.get("reservoir_id", "").strip()
    name = body.get("name", "").strip()
    if not reservoir_id:
        raise HTTPException(400, "reservoir_id is required")
    if not name:
        raise HTTPException(400, "name is required")

    id_prefix = reservoir_id.split(":")[0] if ":" in reservoir_id else "dev"
    bd_slug = name.replace(" ", "-").replace("/", "-")[:80]

    storage_url = f"https://{osdu.OSDU_BASE_URL}/api/storage/v2/records"
    hdr = osdu.headers(at)
    acl = {"owners": osdu.DEFAULT_OWNERS, "viewers": osdu.DEFAULT_VIEWERS}
    legal = {
        "legaltags": [osdu.DEFAULT_LEGAL_TAG],
        "otherRelevantDataCountries": osdu.DEFAULT_COUNTRIES,
    }

    created_records: List[Dict[str, Any]] = []
    errors: List[str] = []

    # ── 1. Create Risks ─────────────────────────────────────────────────
    created_risk_ids: List[str] = []
    if create_risks:
        risk_overrides = body.get("risk_overrides", [])
        if risk_overrides:
            risk_defs = risk_overrides
        elif preset_type == "exploration":
            risk_defs = _EXPLORATION_DEFAULT_RISKS
        else:
            risk_defs = _WPC_DEFAULT_RISKS

        risk_records = []
        for i, rdef in enumerate(risk_defs):
            risk_name = rdef.get("Name", f"Risk-{i+1}")
            risk_slug = risk_name.replace(" ", "-").replace("/", "-")[:50]
            risk_id = f"{id_prefix}:master-data--Risk:{bd_slug}-{risk_slug}:1"
            created_risk_ids.append(risk_id)

            cat_id = rdef.get("RiskCategoryID", "General")
            risk_records.append({
                "id": risk_id,
                "kind": "osdu:wks:master-data--Risk:1.2.0",
                "acl": acl,
                "legal": legal,
                "data": {
                    "Name": risk_name,
                    "Description": rdef.get("Description", ""),
                    "RiskCategoryID": f"{id_prefix}:reference-data--RiskCategory:{cat_id}:",
                    "InherentRiskProbabilityID": f"{id_prefix}:reference-data--RiskProbabilityScale:{rdef.get('InherentProbability', 'Medium')}:",
                    "InherentRiskSeverityID": f"{id_prefix}:reference-data--RiskSeverityScale:{rdef.get('InherentSeverity', 'Medium')}:",
                    "MitigationPlan": rdef.get("MitigationPlan", ""),
                    "RiskOwner": rdef.get("RiskOwner", ""),
                },
            })

        try:
            async with osdu.http_client(timeout=30) as client:
                r = await client.put(storage_url, json=risk_records, headers=hdr)
                if r.status_code in (200, 201):
                    created_records.append({"type": "Risk", "count": len(risk_records), "ids": created_risk_ids})
                else:
                    errors.append(f"Risk creation failed ({r.status_code}): {r.text[:300]}")
                    created_risk_ids = []
        except Exception as e:
            errors.append(f"Risk creation error: {e}")
            created_risk_ids = []

    # ── 2. Create PersistedCollections (hierarchical evidence package) ──
    # Structure differs by preset:
    #   WPC / Dev Well / Exploration → well-focused sub-collections:
    #     1. Undergrunn (subsurface: volumes, geomodel, GeoLabelSet)
    #     2. Brønn & Boring (well & drilling: trajectory, completion, cost, wellbore)
    #     3. Risiko & Beslutning (risks, DevConcept, activity)
    #     → Top-level evidence package referencing sub-collections
    #
    #   Field Dev DG1/DG2 → domain sub-collections (Drogon pattern):
    #     1. Geomodell (grid, maps, polygons, dataspace)
    #     2. Simulering & Volum (volumes raw/stat, params, production)
    #     3. Dokumenter & Risiko (risks, documents, activity)
    #     → Top-level evidence package referencing sub-collections

    collection_id_created = ""
    if create_collection:
        main_pc_id = f"{id_prefix}:work-product-component--PersistedCollection:{bd_slug}-Evidenspakke:1"

        # Categorize all linked record IDs into domain buckets
        rev_stats = body.get("rev_stats_id", "").strip()
        rev_raw = body.get("rev_raw_id", "").strip()
        production_id = body.get("production_profile_id", "").strip()
        geolabelset = body.get("geolabelset_id", "").strip()
        params = body.get("params_id", "").strip()
        activity = body.get("activity_id", "").strip()
        dataspace = body.get("dataspace_id", "").strip()
        well_prod = body.get("well_prod_id", "").strip()
        well_inj = body.get("well_inj_id", "").strip()
        wellbore = body.get("wellbore_id", "").strip()
        trajectory = body.get("trajectory_id", "").strip()
        devconcept = body.get("devconcept_id", "").strip()
        wellcost = body.get("wellcost_id", "").strip()
        tubular = body.get("tubular_id", "").strip()
        drilling_coll = body.get("drilling_collection_id", "").strip()

        sub_collection_records: List[Dict[str, Any]] = []
        sub_collection_ids: List[str] = []

        is_well_preset = preset_type in ("wpc", "dev_well", "exploration")

        if is_well_preset:
            # ── WPC / Dev Well / Exploration: well-focused structure ──

            # Sub 1: Undergrunn (Subsurface)
            undergrunn_refs = [r for r in [
                rev_stats, rev_raw, production_id, geolabelset, params, dataspace,
            ] if r]
            if undergrunn_refs:
                sub1_id = f"{id_prefix}:work-product-component--PersistedCollection:{bd_slug}-Undergrunn:1"
                sub_collection_ids.append(sub1_id)
                sub_collection_records.append({
                    "id": sub1_id,
                    "kind": "osdu:wks:work-product-component--PersistedCollection:1.0.0",
                    "acl": acl, "legal": legal,
                    "data": {
                        "Name": f"{name} – Undergrunn",
                        "Description": (
                            "Undergrunnsdata: volumestimater (rå + statistikk), "
                            "produksjonsprofil, GeoLabelSet, designmatrise, "
                            "og RDDMS geomodell-dataspace."
                        ),
                        "DataReferences": undergrunn_refs,
                        "Tags": ["undergrunn", "volum", "geomodell", preset_type],
                    },
                })

            # Sub 2: Brønn & Boring (Well & Drilling)
            bronn_refs = [r for r in [
                well_prod, well_inj, wellbore, trajectory,
                wellcost, tubular, drilling_coll,
            ] if r]
            if bronn_refs:
                sub2_id = f"{id_prefix}:work-product-component--PersistedCollection:{bd_slug}-Bronn:1"
                sub_collection_ids.append(sub2_id)
                sub_collection_records.append({
                    "id": sub2_id,
                    "kind": "osdu:wks:work-product-component--PersistedCollection:1.0.0",
                    "acl": acl, "legal": legal,
                    "data": {
                        "Name": f"{name} – Brønn & Boring",
                        "Description": (
                            "Brønnrelatert evidens: planlagte brønner (produsent/injektor), "
                            "brønnbane (trajectory), kompletteringsdesign (TubularAssembly), "
                            "brønnkostnad (AFE), og borepakke."
                        ),
                        "DataReferences": bronn_refs,
                        "Tags": ["brønn", "boring", "komplettering", "trajectory", preset_type],
                    },
                })

            # Sub 3: Risiko & Beslutning (Risks & Decision context)
            risiko_refs = created_risk_ids + [r for r in [devconcept, activity] if r]
            if risiko_refs:
                sub3_id = f"{id_prefix}:work-product-component--PersistedCollection:{bd_slug}-Risiko:1"
                sub_collection_ids.append(sub3_id)
                sub_collection_records.append({
                    "id": sub3_id,
                    "kind": "osdu:wks:work-product-component--PersistedCollection:1.0.0",
                    "acl": acl, "legal": legal,
                    "data": {
                        "Name": f"{name} – Risiko & Beslutning",
                        "Description": (
                            "Risikoregisteret og beslutningskontekst: "
                            "identifiserte risikoer, utbyggingskonsept "
                            "(DevelopmentConcept), og aktivitetshistorikk."
                        ),
                        "DataReferences": risiko_refs,
                        "Tags": ["risiko", "beslutning", "konsept", preset_type],
                    },
                })

        else:
            # ── Field Dev DG1/DG2 / CCS: domain-focused structure ──

            # Sub 1: Geomodell (Geomodel)
            geo_refs = [r for r in [dataspace, geolabelset] if r]
            if geo_refs:
                sub1_id = f"{id_prefix}:work-product-component--PersistedCollection:{bd_slug}-Geomodell:1"
                sub_collection_ids.append(sub1_id)
                sub_collection_records.append({
                    "id": sub1_id,
                    "kind": "osdu:wks:work-product-component--PersistedCollection:1.0.0",
                    "acl": acl, "legal": legal,
                    "data": {
                        "Name": f"{name} – Geomodell",
                        "Description": (
                            "Statisk geomodell: RDDMS dataspace (EPC-objekter), "
                            "GeoLabelSet (nøkkeltall per segment), flater og grid."
                        ),
                        "DataReferences": geo_refs,
                        "Tags": ["geomodell", "RDDMS", "GeoLabelSet", preset_type],
                    },
                })

            # Sub 2: Simulering & Volum (Simulation & Volumes)
            sim_refs = [r for r in [rev_stats, rev_raw, params, production_id] if r]
            if sim_refs:
                sub2_id = f"{id_prefix}:work-product-component--PersistedCollection:{bd_slug}-Simulering:1"
                sub_collection_ids.append(sub2_id)
                sub_collection_records.append({
                    "id": sub2_id,
                    "kind": "osdu:wks:work-product-component--PersistedCollection:1.0.0",
                    "acl": acl, "legal": legal,
                    "data": {
                        "Name": f"{name} – Simulering & Volum",
                        "Description": (
                            "Dynamisk simulering og volumestimater: "
                            "råvolum per realisering, P10/P50/P90 statistikk, "
                            "designmatrise, og produksjonsprofil."
                        ),
                        "DataReferences": sim_refs,
                        "Tags": ["simulering", "volum", "FMU", "statistikk", preset_type],
                    },
                })

            # Sub 3: Risiko, Dokumenter & Aktivitet
            risk_doc_refs = created_risk_ids + [r for r in [devconcept, activity] if r]
            if risk_doc_refs:
                sub3_id = f"{id_prefix}:work-product-component--PersistedCollection:{bd_slug}-RisikoDok:1"
                sub_collection_ids.append(sub3_id)
                sub_collection_records.append({
                    "id": sub3_id,
                    "kind": "osdu:wks:work-product-component--PersistedCollection:1.0.0",
                    "acl": acl, "legal": legal,
                    "data": {
                        "Name": f"{name} – Risiko & Dokumenter",
                        "Description": (
                            "Risikoregisteret, utbyggingskonsept, og "
                            "aktivitetshistorikk (provenance)."
                        ),
                        "DataReferences": risk_doc_refs,
                        "Tags": ["risiko", "dokumenter", "aktivitet", preset_type],
                    },
                })

        # ── Top-level evidence package (references sub-collections + reservoir) ──
        # Ordered: sub-collections first (logical grouping), then reservoir context
        all_top_refs = sub_collection_ids + [
            r for r in [reservoir_id] if r
        ]

        # Also include any custom_records the user added
        custom_recs: List[Dict[str, str]] = body.get("custom_records", [])
        for cr in custom_recs:
            cid = cr.get("id", "").strip()
            if cid:
                all_top_refs.append(cid)

        main_pc_record = {
            "id": main_pc_id,
            "kind": "osdu:wks:work-product-component--PersistedCollection:1.0.0",
            "acl": acl, "legal": legal,
            "data": {
                "Name": f"{name} – Evidenspakke",
                "Description": (
                    f"Samlet evidenspakke for beslutningen «{name}». "
                    f"Inneholder {len(sub_collection_ids)} underpakker "
                    f"organisert etter fagområde, pluss reservoar-kontekst. "
                    f"Totalt {sum(len(r.get('data',{}).get('DataReferences',[])) for r in sub_collection_records)} "
                    f"individuelle datareferanser."
                ),
                "DataReferences": all_top_refs,
                "Tags": [preset_type or "beslutningsgate", "evidenspakke", "auto-generert"],
            },
        }

        # Ingest all: sub-collections first, then main package
        all_pc_records = sub_collection_records + [main_pc_record]

        try:
            async with osdu.http_client(timeout=30) as client:
                r = await client.put(storage_url, json=all_pc_records, headers=hdr)
                if r.status_code in (200, 201):
                    collection_id_created = main_pc_id
                    created_records.append({
                        "type": "Evidenspakke (hierarkisk)",
                        "id": main_pc_id,
                        "sub_collections": [
                            {"id": rec["id"], "name": rec["data"]["Name"],
                             "refs": len(rec["data"]["DataReferences"])}
                            for rec in sub_collection_records
                        ],
                        "total_refs": sum(
                            len(r2.get("data", {}).get("DataReferences", []))
                            for r2 in all_pc_records
                        ),
                    })
                else:
                    errors.append(f"Collection creation failed ({r.status_code}): {r.text[:300]}")
        except Exception as e:
            errors.append(f"Collection creation error: {e}")

    # ── 3. Create CollaborationProject (if requested) ───────────────────
    cp_id_created = ""
    if create_collab_project:
        project_name = body.get("project_name", "").strip() or name
        cp_slug = project_name.replace(" ", "-")[:60]
        cp_id = f"{id_prefix}:master-data--CollaborationProject:{cp_slug}:1"

        cp_record = {
            "id": cp_id,
            "kind": "osdu:wks:master-data--CollaborationProject:1.0.0",
            "acl": acl,
            "legal": legal,
            "data": {
                "ProjectName": project_name,
                "Description": f"Field development project for {project_name}. Long-lived namespace bridging collaboration (SoE) and trusted data (SoR).",
                "Namespace": f"project-{cp_slug.lower()}",
                "LifecycleStatusID": f"{id_prefix}:reference-data--CollaborationProjectLifecycleStatus:Open:",
                "Parameters": [{
                    "Title": "Reservoir scope",
                    "ParameterKindID": f"{id_prefix}:reference-data--ParameterKind:DataObject:",
                    "ParameterRoleID": f"{id_prefix}:reference-data--ParameterRole:InputReference:",
                    "DataObjectParameter": reservoir_id,
                }],
            },
        }
        if collection_id_created:
            cp_record["data"]["TrustedCollectionID"] = collection_id_created

        try:
            async with osdu.http_client(timeout=30) as client:
                r = await client.put(storage_url, json=[cp_record], headers=hdr)
                if r.status_code in (200, 201):
                    cp_id_created = cp_id
                    created_records.append({"type": "CollaborationProject", "id": cp_id})
                else:
                    errors.append(f"CP creation failed ({r.status_code}): {r.text[:300]}")
        except Exception as e:
            errors.append(f"CP creation error: {e}")

    # ── 4. Now create the BD, merging all auto-created IDs ──────────────
    # Merge auto-created risk IDs with any user-supplied ones
    existing_risk_ids = [r.strip() for r in body.get("risk_ids", []) if r.strip()]
    all_risk_ids = existing_risk_ids + created_risk_ids

    # Override collection/cp IDs if we created them
    if collection_id_created:
        body["collection_id"] = collection_id_created
    if cp_id_created:
        body["collab_project_id"] = cp_id_created
    body["risk_ids"] = all_risk_ids

    # Delegate to the standard create_bd logic via internal call
    # Re-inject the modified body so create_bd picks up all auto-created IDs
    from starlette.requests import Request as StarletteRequest

    # Build a new request-like object with updated body
    class _PatchedRequest:
        def __init__(self, original, new_body):
            self._original = original
            self._body = new_body
        def __getattr__(self, name):
            return getattr(self._original, name)
        async def json(self):
            return self._body

    patched = _PatchedRequest(request, body)
    bd_response = await create_bd(patched)

    # Parse BD response
    bd_result = json.loads(bd_response.body.decode("utf-8"))

    return JSONResponse({
        "ok": bd_result.get("ok", False),
        "bd_id": bd_result.get("bd_id", ""),
        "created_records": created_records,
        "errors": errors,
        "bd_response": bd_result,
        "summary": {
            "risks_created": len(created_risk_ids),
            "collection_created": bool(collection_id_created),
            "collab_project_created": bool(cp_id_created),
            "total_records": len(created_records) + (1 if bd_result.get("ok") else 0),
        },
    })


# ──────────────────────────────────────────────────────────────────────────────
# Helpers for create_generic
# ──────────────────────────────────────────────────────────────────────────────

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
