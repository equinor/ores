
from __future__ import annotations
import os
import re
import urllib.parse
import logging
import json
from typing import List, Dict, Any, Optional, Tuple, Set

import httpx
from httpx import HTTPStatusError
from fastapi import FastAPI, Request, Form, HTTPException, Query, Body
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.responses import Response

# App modules
from .schemahandler import extract_osdu_links
from .schemahandler import extract_metadata_generic
from app.ingest_router import router as ingest_router
from . import osdu
from .auth import (
    router as auth_router,
    tokens_from_env,
)
from .strat import router as strat_router

# ──────────────────────────────────────────────────────────────────────────────
# App setup & logging
# ──────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
)
log = logging.getLogger("rddms-admin")

app = FastAPI(title="RDDMS Admin")

# Security headers & cache hardening
@app.middleware("http")
async def no_transform_headers(request: Request, call_next):
    resp: Response = await call_next(request)
    resp.headers.setdefault("Cache-Control", "no-store, no-transform")
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    return resp

# Auth: server-side refresh-token minting (no cookies)
@app.middleware("http")
async def inject_access_token(request: Request, call_next):
    """
    Mint a fresh access_token from REFRESH_TOKEN and attach to request.state.
    Fails fast with 401 if unavailable.
    """
    try:
        tokens = await tokens_from_env()
        if not tokens or not tokens.get("access_token"):
            log.error("Auth failed: missing/invalid refresh_token")
            return JSONResponse({"error": "Authentication failed: missing/invalid refresh_token"}, status_code=401)
        request.state.access_token = tokens["access_token"]
    except Exception as e:
        log.error("Failed to mint access token: %s", e)
        return JSONResponse({"error": f"Authentication failed: {e}"}, status_code=401)
    return await call_next(request)

# Attach routers & static
app.include_router(auth_router)  # keeps /auth diagnostics
app.include_router(ingest_router, prefix="/api")
app.include_router(strat_router)

app.mount(
    "/static",
    StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")),
    name="static",
)
templates = Jinja2Templates(
    directory=os.path.join(os.path.dirname(__file__), "templates")
)

# Log routes at startup (helps when a route goes missing)
log.info("Routes registered: %s", [getattr(r, "path", str(r)) for r in app.routes])

# ──────────────────────────────────────────────────────────────────────────────
# Utilities
# ──────────────────────────────────────────────────────────────────────────────

def _access_token(request: Request) -> str:
    at = getattr(request.state, "access_token", None)
    if not at:
        raise HTTPException(401, "Authentication failed")
    return at

def _normalize_volumes(data_block: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize OSDU ColumnBasedTable in data_block['Volumes'] to a structure:
    {
      "KeyColumns": [ {ColumnName, ColumnRole, ValueType, ...}, ... ],
      "Columns":    [ {ColumnName, ColumnRole, ValueType, ...}, ... ],
      "ColumnValues": { "<ColumnName>": [v0, v1, ...], ... }
    }
    Handles cases where ColumnValues may arrive as a dict or a list of objects.
    Leaves other shapes untouched (best-effort).
    """
    vol = (data_block or {}).get("Volumes", {}) or {}
    key_cols = vol.get("KeyColumns", []) or []
    value_cols = vol.get("Columns", []) or []
    raw_vals = vol.get("ColumnValues", {}) or {}

    if isinstance(raw_vals, dict):
        col_values = raw_vals
    elif isinstance(raw_vals, list):
        # list of dicts like {"ColumnName": "...", "Values": [...]}
        if raw_vals and all(isinstance(x, dict) for x in raw_vals):
            out: Dict[str, List[Any]] = {}
            for x in raw_vals:
                name = x.get("ColumnName") or x.get("name")
                vals = (
                    x.get("Values")
                    or x.get("values")
                    or x.get("Data")
                    or x.get("data")
                    or []
                )
                if name:
                    out[name] = vals if isinstance(vals, list) else [vals]
            col_values = out
        else:
            col_values = raw_vals
    else:
        col_values = raw_vals

    return {
        "KeyColumns": key_cols,
        "Columns": value_cols,
        "ColumnValues": col_values,
    }

# ──────────────────────────────────────────────────────────────────────────────
# Pages & actions
# ──────────────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse, summary="Home: list dataspaces")
async def home(request: Request):
    try:
        at = _access_token(request)
        dataspaces = await osdu.list_dataspaces(at)
    except Exception as e:
        log.warning("List dataspaces failed: %s", e)
        dataspaces = []
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "view": "home",
            "dataspaces": dataspaces,
            # Defaults for the "Create Dataspace" form (prefilled values)
            "ds_default": os.getenv("DEFAULT_DATASPACE", ""),
            "default_legal_tag": osdu.DEFAULT_LEGAL_TAG,
            "default_owners": ",".join(osdu.DEFAULT_OWNERS),
            "default_viewers": ",".join(osdu.DEFAULT_VIEWERS),
            "default_countries": ",".join(osdu.DEFAULT_COUNTRIES),
        },
    )

@app.post("/dataspaces/create", summary="Create a dataspace with default legal/ACL")
async def dataspaces_create(
    request: Request,
    path: str = Form(...),
    legal: str = Form(osdu.DEFAULT_LEGAL_TAG),
    owners: str = Form(",".join(osdu.DEFAULT_OWNERS)),
    viewers: str = Form(",".join(osdu.DEFAULT_VIEWERS)),
    countries: str = Form(",".join(osdu.DEFAULT_COUNTRIES)),
    custom_json: str = Form("", description="Optional JSON to merge into CustomData"),
):
    at = _access_token(request)

    # Parse optional JSON block
    extra_custom: Dict[str, Any] = {}
    if custom_json and custom_json.strip():
        try:
            extra_custom = json.loads(custom_json)
            if not isinstance(extra_custom, dict):
                raise ValueError("Custom data must be a JSON object")
        except Exception as ex:
            return templates.TemplateResponse(
                "index.html",
                {
                    "request": request,
                    "view": "home",
                    "dataspaces": [],
                    "ds_default": os.getenv("DEFAULT_DATASPACE", ""),
                    "default_legal_tag": osdu.DEFAULT_LEGAL_TAG,
                    "default_owners": ",".join(osdu.DEFAULT_OWNERS),
                    "default_viewers": ",".join(osdu.DEFAULT_VIEWERS),
                    "default_countries": ",".join(osdu.DEFAULT_COUNTRIES),
                    "error": "Invalid custom JSON",
                    "error_detail": str(ex),
                },
                status_code=400,
            )

    try:
        await osdu.create_dataspace(
            at,
            path,
            legal_tag=legal,
            owners=[x.strip() for x in owners.split(",") if x.strip()],
            viewers=[x.strip() for x in viewers.split(",") if x.strip()],
            countries=[x.strip() for x in countries.split(",") if x.strip()],
            extra_custom=extra_custom,
        )
    except HTTPStatusError as e:
        r = e.response
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "view": "home",
                "dataspaces": [],
                "ds_default": os.getenv("DEFAULT_DATASPACE", ""),
                "default_legal_tag": osdu.DEFAULT_LEGAL_TAG,
                "default_owners": ",".join(osdu.DEFAULT_OWNERS),
                "default_viewers": ",".join(osdu.DEFAULT_VIEWERS),
                "default_countries": ",".join(osdu.DEFAULT_COUNTRIES),
                "error": f"Create failed: {r.status_code} {r.reason_phrase}",
                "error_detail": (r.text[:2000] if r.text else ""),
            },
            status_code=400,
        )
    return RedirectResponse(url=f"/d/{urllib.parse.quote(path, safe='')}", status_code=302)

# ──────────────────────────────────────────────────────────────────────────────
# Search (OSDU search v2) — enrich with storage fetch, ancestry, links, metadata
# ──────────────────────────────────────────────────────────────────────────────

@app.get("/search", response_class=HTMLResponse, summary="Search form (OSDU search v2)")
async def search_page(request: Request):
    # Pre-fill demo values
    return templates.TemplateResponse(
        "search.html",
        {
            "request": request,
            "kind": "osdu:wks:work-product-component--ReservoirEstimatedVolumes:1.1.0",
            "q": "*",
            "limit": 10,
            "returnedFields": "id,kind,version",
        },
    )

@app.post("/search/run", response_class=HTMLResponse)
async def search_run(
    request: Request,
    kind: str = Form("osdu:wks:work-product-component--ReservoirEstimatedVolumes:1.1.0"),
    query: str = Form("*"),
    limit: int = Form(5),
):
    """
    Run an OSDU Search v2 query, then enrich each hit:
    • Fetch the full storage record (data{}).
    • Surface ancestry parents/children.
    • Normalize Volumes (ColumnBasedTable) for REV WPCs.
    • Extract WPC/master-data links from data{} (exclude reference-data).
    • Hydrate labels (Name/kind/version) for linked records (bounded).
    • Build compact metadata_pairs from data{}.
    Renders: templates/search.html with:
    results = {
      results: [{ id, kind, version, data, ancestry_parents, ancestry_children,
                  volumes, links, linked_labels, metadata_pairs }, ...],
      totalCount
    }
    """
    at = _access_token(request)
    search_url = f"https://{osdu.OSDU_BASE_URL}/api/search/v2/query"
    storage_url = f"https://{osdu.OSDU_BASE_URL}/api/storage/v2/records"
    hdr = osdu.headers(at)

    payload = {
        "kind": kind,
        "query": query,
        "limit": int(limit),
        "returnedFields": ["id", "kind", "version"],  # minimal; full fetched below
        "trackTotalCount": True,
    }

    try:
        enriched_results: List[Dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=60) as client:
            # 1) Search
            r = await client.post(search_url, headers=hdr, json=payload)
            r.raise_for_status()
            res = r.json()
            log.info("[SEARCH] Status=%d, hits=%d", r.status_code, len(res.get("results", [])))

            # 2) Enrich each hit
            for rec in res.get("results", []):
                rid = rec.get("id")
                if not rid:
                    continue
                try:
                    # Fetch full storage record
                    r_full = await client.get(f"{storage_url}/{rid}", headers=hdr)
                    if r_full.status_code != 200:
                        log.warning("[SEARCH] Full record fetch failed for %s: %d", rid, r_full.status_code)
                        continue
                    full = r_full.json()

                    # data{} block
                    data_block = full.get("data", {}) or {}

                    # Existing: ancestry & volumes normalization
                    ancestry = data_block.get("ancestry", {}) or {}
                    ancestry_parents = ancestry.get("parents", []) or []
                    ancestry_children = ancestry.get("children", []) or []
                    volumes = _normalize_volumes(data_block)

                    # Generic WPC/master-data links (exclude reference-data)
                    links = extract_osdu_links(data_block) or []

                    # Hydrate labels for linked records (bounded)
                    linked_labels: Dict[str, Dict[str, Any]] = {}
                    try:
                        for l in links[:25]:
                            lid = l.get("id")
                            if not lid or lid in linked_labels:
                                continue
                            r_link = await client.get(f"{storage_url}/{lid}", headers=hdr)
                            if r_link.status_code == 200:
                                rr = r_link.json()
                                nm = (rr.get("data") or {}).get("Name")
                                linked_labels[lid] = {
                                    "name": nm or lid,
                                    "kind": rr.get("kind"),
                                    "version": rr.get("version"),
                                }
                    except Exception as e:
                        log.warning("[SEARCH] Linked record name hydration failed: %s", e)

                    # Compact metadata pairs from data{}
                    try:
                        md = extract_metadata_generic(
                            data_block,
                            ds="",
                            typ=full.get("kind", "") or "",
                            uuid=full.get("id", "") or "",
                            arrays=None,
                            max_string_len=300,
                            max_preview_items=5,
                        )
                        metadata_pairs = md.get("pairs", []) or []
                        # Filter synthesized eml:/// URI (search page cleanliness)
                        metadata_pairs = [
                            p for p in metadata_pairs
                            if not (str(p.get("name")).lower() == "uri" and str(p.get("value") or "").startswith("eml:///"))
                        ]
                    except Exception as e:
                        log.warning("[SEARCH] metadata_pairs extraction failed for %s: %s", rid, e)
                        metadata_pairs = []

                    enriched_results.append({
                        "id": full.get("id"),
                        "kind": full.get("kind"),
                        "version": full.get("version"),
                        "data": data_block,
                        "ancestry_parents": ancestry_parents,
                        "ancestry_children": ancestry_children,
                        "volumes": volumes,
                        "links": links,
                        "linked_labels": linked_labels,
                        "metadata_pairs": metadata_pairs,
                    })
                except Exception as e:
                    log.warning("[SEARCH] Exception enriching %s: %s", rid, e)

        return templates.TemplateResponse(
            "search.html",
            {
                "request": request,
                "results": {"results": enriched_results, "totalCount": len(enriched_results)},
                "kind": kind,
                "q": query,
                "limit": limit,
            },
        )
    except httpx.HTTPStatusError as e:
        r = e.response
        log.warning("[SEARCH] HTTP error: %s %s", r.status_code, r.text[:512] if r.text else "")
        return templates.TemplateResponse(
            "search.html",
            {
                "request": request,
                "error": f"Search failed: {r.status_code} {r.reason_phrase}",
                "error_detail": (r.text[:2000] if r.text else ""),
            },
            status_code=r.status_code or 500,
        )
    except Exception as e:
        log.exception("[SEARCH] Unexpected error: %s", e)
        return templates.TemplateResponse(
            "search.html",
            {
                "request": request,
                "error": "Unexpected error",
                "error_detail": "See server logs",
            },
            status_code=500,
        )

@app.get("/search/view/{record_id}", response_class=HTMLResponse)
async def view_record(request: Request, record_id: str):
    at = _access_token(request)
    storage_url = f"https://{osdu.OSDU_BASE_URL}/api/storage/v2/records/{record_id}"
    hdr = osdu.headers(at)
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(storage_url, headers=hdr)
        r.raise_for_status()
        full = r.json()
        data_block = full.get("data", {}) or {}
        volumes = _normalize_volumes(data_block)
        return templates.TemplateResponse(
            "record.html",
            {
                "request": request,
                "record": full,
                "volumes": volumes,
            },
        )

# ──────────────────────────────────────────────────────────────────────────────
# KEYS page: dataspace -> type -> object
# ──────────────────────────────────────────────────────────────────────────────

@app.get("/keys", response_class=HTMLResponse)
async def keys_page(request: Request):
    prefill_ds = []
    try:
        at = _access_token(request)
        rows = await osdu.list_dataspaces(at)
        prefill_ds = [{"path": x.get("path", ""), "uri": x.get("uri", "")} for x in (rows or []) if x.get("path")]
    except Exception as e:
        log.warning("keys_page list_dataspaces failed: %s", e)
        prefill_ds = []
    return templates.TemplateResponse(
        "keys.html",
        {"request": request, "prefill_ds": prefill_ds},
        media_type="text/html",
    )

@app.get("/keys/dataspaces.json")
async def keys_dataspaces(request: Request):
    at = _access_token(request)
    try:
        rows = await osdu.list_dataspaces(at)
    except Exception as e:
        log.warning("keys_dataspaces failed: %s", e)
        rows = []
    items = [{"path": x.get("path"), "uri": x.get("uri")} for x in rows if x.get("path")]
    return JSONResponse({"items": items})

@app.get("/keys/types.json")
async def keys_types(
    request: Request,
    ds: str = Query(..., description="Dataspace path"),
    source: str = Query("live", description="'live' (Rddms) or 'catalog' (curated)"),
):
    at = _access_token(request)
    items: List[Dict[str, Any]] = []
    if source == "live":
        enc = urllib.parse.quote(ds, safe="")
        try:
            rows = await osdu.list_types(at, enc)
        except Exception as e:
            log.warning("keys_types list_types failed: %s", e)
            rows = []
        for r in rows or []:
            name = r.get("name") if isinstance(r, dict) else r
            count = r.get("count") if isinstance(r, dict) else None
            if name:
                items.append({"name": name, "count": count})
    else:
        # curated fallback list
        items = [{"name": x} for x in [
            "resqml20.obj_PropertyKind",
            "resqml20.obj_StringTableLookup",
            "resqml20.obj_LocalDepth3dCrs",
            "resqml20.obj_Grid2dRepresentation",
            "resqml20.obj_HorizonInterpretation",
            "resqml20.obj_GeneticBoundaryFeature",
            "resqml20.obj_IjkGridRepresentation",
            "resqml20.obj_ContinuousProperty",
            "resqml20.obj_CategoricalProperty",
            "resqml20.obj_DiscreteProperty",
            "resqml20.obj_OrganizationFeature",
            "resqml20.obj_TectonicBoundaryFeature",
            "resqml20.obj_Activity",
            "resqml20.obj_ActivityTemplate",
            "eml20.obj_EpcExternalPartReference",
        ]]
    return JSONResponse({"items": items})

# ──────────────────────────────────────────────────────────────────────────────
# Dataspace admin endpoints (delete/lock/unlock/manifest)
# ──────────────────────────────────────────────────────────────────────────────

@app.post("/dataspaces/delete", summary="Delete a dataspace")
async def dataspaces_delete(request: Request, path: str = Form(...)):
    at = _access_token(request)
    try:
        await osdu.delete_dataspace(at, path)
    except HTTPStatusError as e:
        r = e.response
        return JSONResponse(
            {
                "status": "error",
                "code": r.status_code,
                "reason": r.reason_phrase,
                "detail": (r.text[:2000] if r.text else ""),
            },
            status_code=r.status_code or 500,
        )
    return JSONResponse({"status": "ok"})

@app.post("/dataspaces/lock", summary="Lock a dataspace")
async def dataspaces_lock(request: Request, path: str = Form(...)):
    at = _access_token(request)
    try:
        await osdu.lock_dataspace(at, path)
    except HTTPStatusError as e:
        r = e.response
        return JSONResponse(
            {"status": "error", "code": r.status_code, "reason": r.reason_phrase, "detail": (r.text[:2000] if r.text else "")},
            status_code=r.status_code or 500,
        )
    return JSONResponse({"status": "ok"})

@app.post("/dataspaces/unlock", summary="Unlock a dataspace")
async def dataspaces_unlock(request: Request, path: str = Form(...)):
    at = _access_token(request)
    try:
        await osdu.unlock_dataspace(at, path)
    except HTTPStatusError as e:
        r = e.response
        return JSONResponse(
            {"status": "error", "code": r.status_code, "reason": r.reason_phrase, "detail": (r.text[:2000] if r.text else "")},
            status_code=r.status_code or 500,
        )
    return JSONResponse({"status": "ok"})

@app.post("/dataspaces/manifest", summary="Build OSDU manifest for a dataspace")
async def dataspaces_manifest(
    request: Request,
    path: str = Form(...),
    legal: str = Form(osdu.DEFAULT_LEGAL_TAG),
    owners: str = Form(",".join(osdu.DEFAULT_OWNERS)),
    viewers: str = Form(",".join(osdu.DEFAULT_VIEWERS)),
    countries: str = Form(",".join(osdu.DEFAULT_COUNTRIES)),
    create_missing: bool = Form(True),
):
    at = _access_token(request)
    try:
        manifest = await osdu.build_manifest(
            at,
            path,
            legal_tag=legal,
            owners=[x.strip() for x in owners.split(",") if x.strip()],
            viewers=[x.strip() for x in viewers.split(",") if x.strip()],
            countries=[x.strip() for x in countries.split(",") if x.strip()],
            create_missing_refs=create_missing,
        )
    except HTTPStatusError as e:
        r = e.response
        return JSONResponse(
            {"status": "error", "code": r.status_code, "reason": r.reason_phrase, "detail": (r.text[:2000] if r.text else "")},
            status_code=r.status_code or 500,
        )
    return JSONResponse({"status": "ok", "manifest": manifest})

# ── helpers ───────────────────────────────────────────────────────────────────

def _sanitize_type(typ: str) -> str:
    """Canonical dataObjectType: strip '(uuid)' suffix & quotes."""
    if not typ:
        return ""
    m = re.match(r"^([^\(\)]+)\s*\(", typ.strip())
    pure = m.group(1) if m else typ.strip()
    return pure.strip("'\"")

def _sanitize_uuid(u: str) -> str:
    """Strip quotes & trailing ')' around uuid."""
    if not u:
        return ""
    return u.strip().strip("'\"").rstrip(")")

def _node_uuid(node: dict, fallback_uri: str = "") -> str:
    uid = node.get("Uuid") or node.get("UUID") or node.get("uuid")
    if uid:
        return str(uid)
    if fallback_uri and "(" in fallback_uri and ")" in fallback_uri:
        return fallback_uri.split("(")[-1].rstrip(")")
    return ""

@app.get("/keys/object.json")
async def keys_object_json(
    request: Request,
    ds: str = Query(..., description="Dataspace path"),
    typ: str = Query(..., description="RESQML/EML type (canonical or noisy)"),
    uuid: str = Query(..., description="UUID of the selected object"),
):
    """
    Return normalized details for a single object including generic metadata:
    {
      "primary": { ... },
      "content": { ... },   # normalized object body
      "arrays": [ ... ],    # arrays metadata (if available)
      "metadata": { ... }   # generic compact metadata + 'pairs' for table rendering
    }
    """
    at = _access_token(request)
    enc = urllib.parse.quote(ds, safe="")
    typ_s = _sanitize_type(typ)
    uuid_s = _sanitize_uuid(uuid)

    # Fetch object and normalize list/dict shape
    obj_raw = await osdu.get_resource(at, enc, typ_s, uuid_s)
    obj = _normalize_resource_obj(obj_raw, uuid_s)

    primary = {
        "uuid": uuid_s,
        "typePath": typ_s,
        "title": (obj.get("Citation") or {}).get("Title") or uuid_s,
        "uri": obj.get("uri") or osdu._eml_uri_from_parts(ds, typ_s, uuid_s),
        "contentType": obj.get("$type") or obj.get("contentType") or "",
    }

    # Arrays metadata (optional)
    arrays = []
    try:
        arrays = await osdu.list_arrays(at, enc, typ_s, uuid_s)
    except Exception as e:
        log.warning("keys_object_json: list_arrays failed: %s", e)
        arrays = []

    # Generic metadata from schemahandler
    metadata = extract_metadata_generic(
        obj,
        ds=ds, typ=typ_s, uuid=uuid_s,
        arrays=arrays,
        max_string_len=300,
        max_preview_items=5,
    )
    return JSONResponse({
        "primary": primary,
        "content": obj,
        "arrays": arrays,
        "metadata": metadata,
    })

@app.get("/keys/objects.json")
async def keys_objects(
    request: Request,
    ds: str = Query(..., description="Dataspace path"),
    typ: Optional[str] = Query(None, description="resqml20.obj_* type (optional)"),
    q: Optional[str] = Query(None, description="Name/UUID contains (optional)"),
):
    """
    Aggregated list endpoint used by app.js:
    - If 'typ' provided -> list via RDDMS /resources/{type}
    - If 'typ' omitted  -> try RDDMS /resources/all; on failure/empty, fall back to
      enumerating types via /resources and aggregating /resources/{type}.
    Supports 'q' as contains filter on title/uuid ('*' means no filter).
    """
    at = _access_token(request)
    enc = urllib.parse.quote(ds, safe="")
    rows: List[Dict[str, Any]] = []
    try:
        if typ:
            rows = await osdu.list_resources(at, enc, typ)
        else:
            # Try /resources/all first
            try:
                rows = await osdu.list_all_resources(at, enc)
            except Exception as e_all:
                log.warning("keys_objects: resources/all failed: %s", e_all)
                rows = []
            # Fallback: enumerate types and aggregate
            if not rows:
                try:
                    types = await osdu.list_types(at, enc) or []
                    names = [t.get("name") if isinstance(t, dict) else t for t in types if t]
                    agg: List[Dict[str, Any]] = []
                    for name in names:
                        if not name:
                            continue
                        try:
                            part = await osdu.list_resources(at, enc, name) or []
                            agg.extend(part)
                        except Exception as e_type:
                            log.warning("keys_objects: list_resources(%s) failed: %s", name, e_type)
                    rows = agg
                except Exception as e:
                    log.warning("keys_objects: types aggregation failed: %s", e)
                    rows = []
    except Exception as e:
        log.warning("keys_objects failed: %s", e)
        rows = []

    # Normalize + server-side filter
    out = []
    qq = (q or "").strip()
    qq_norm = "" if qq in ("", "*") else qq.lower()  # '*' means no filter

    for r in rows or []:
        uid = r.get("Uuid") or r.get("UUID") or r.get("uuid")
        uri = r.get("uri") or ""
        if not uid:
            if "(" in uri and ")" in uri:
                uid = uri.split("(")[-1].rstrip(")")
            else:
                uid = uri
        title = (r.get("Citation") or {}).get("Title") or r.get("name") or uid or uri
        ct = r.get("$type") or r.get("contentType") or ""
        type_path = _infer_type_path(r)

        # contains filter on title/uuid
        if qq_norm:
            if (title or "").lower().find(qq_norm) < 0 and (uid or "").lower().find(qq_norm) < 0:
                continue

        out.append({
            "uuid": uid,
            "title": title,
            "uri": uri,
            "contentType": ct,
            "type": r.get("$type") or r.get("type") or "",
            "typePath": type_path,  # canonical for graph/manifest routes
        })
    return JSONResponse({"items": out})

def _infer_type_path(item: Dict[str, Any]) -> str:
    """
    Return a RESQML/EML type path like 'resqml20.obj_LocalDepth3dCrs'.
    Preference order:
    1) '$type' or 'type'
    2) MIME 'contentType' (e.g. application/x-resqml+xml;version=2.0;type=obj_LocalDepth3dCrs)
    3) Parse from canonical EML 'uri' (e.g. eml:///dataspace('demo/Volve')/resqml20.obj_Grid2dRepresentation('uuid'))
    """
    # (1) direct fields
    t = item.get("$type") or item.get("type")
    if t:
        return t

    # (2) MIME fallback
    ct = item.get("contentType") or ""
    if "type=obj_" in ct:
        suffix = ct.split("type=obj_")[-1].strip()
        if "resqml" in ct:
            return f"resqml20.obj_{suffix}"
        if "eml" in ct:
            return f"eml20.obj_{suffix}"

    # (3) URI fallback
    uri = item.get("uri") or ""
    if "dataspace('" in uri and ")/" in uri and "('" in uri:
        try:
            after = uri.split(")/", 1)[1]
            type_part = after.split("('", 1)[0].strip()
            if type_part:
                return type_part
        except Exception:
            pass
    return ""

# ── route: manifest building ──────────────────────────────────────────────────

@app.post("/dataspaces/manifest/build-uris", summary="Build manifest for one object (+ optional refs)")
async def dataspaces_manifest_build_uris(
    request: Request,
    ds: str = Form(...),
    typ: str = Form(...),
    uuid: str = Form(...),
    include_refs: bool = Form(True),
    legal: str = Form(osdu.DEFAULT_LEGAL_TAG),
    owners: str = Form(",".join(osdu.DEFAULT_OWNERS)),
    viewers: str = Form(",".join(osdu.DEFAULT_VIEWERS)),
    countries: str = Form(",".join(osdu.DEFAULT_COUNTRIES)),
    create_missing: bool = Form(True),
):
    at = _access_token(request)
    typ_s = _sanitize_type(typ)
    uuid_s = _sanitize_uuid(uuid)
    enc = urllib.parse.quote(ds, safe="")

    # Build canonical primary URI (no GET content)
    uris: Set[str] = { osdu._eml_uri_from_parts(ds, typ_s, uuid_s) }

    # Expand refs via graph endpoints
    if include_refs:
        try:
            sources = await osdu.list_sources(at, enc, typ_s, uuid_s)
        except Exception as e:
            log.warning("build-uris: list_sources failed: %s", e)
            sources = []
        try:
            targets = await osdu.list_targets(at, enc, typ_s, uuid_s)
        except Exception as e:
            log.warning("build-uris: list_targets failed: %s", e)
            targets = []

        def add_node_uri(node: dict):
            u = node.get("uri")
            if u:
                uris.add(u); return
            tpath = (node.get("$type") or node.get("type") or "") or _infer_type_path(node)
            nid = _node_uuid(node, fallback_uri=u or "")
            if tpath and nid:
                uris.add(osdu._eml_uri_from_parts(ds, tpath, nid))

        for node in (sources or []):
            if isinstance(node, dict): add_node_uri(node)
        for node in (targets or []):
            if isinstance(node, dict): add_node_uri(node)

    manifest = await osdu.build_manifest_for_uris(
        at,
        sorted(uris),
        legal_tag=legal or osdu.DEFAULT_LEGAL_TAG,
        owners=[x.strip() for x in owners.split(",") if x.strip()],
        viewers=[x.strip() for x in viewers.split(",") if x.strip()],
        countries=[x.strip() for x in countries.split(",") if x.strip()],
        create_missing_refs=bool(create_missing),
    )
    app.state.last_manifest = manifest
    return JSONResponse({"status": "ok", "countUris": len(uris), "manifest": manifest})

@app.post("/dataspaces/manifest/build-from-selection",
          summary="Build manifest from multiple selected objects")
async def dataspaces_manifest_build_from_selection(
    request: Request,
    payload: Dict[str, Any] = Body(
        ...,
        description=("JSON: { items:[{ds,typ,uuid}], include_refs:bool, "
                     "uris?:[eml-uri,...], dataspaces?:[path,...], "
                     "legal?, owners?, viewers?, countries?, create_missing? }")
    )
):
    """
    Build one manifest for:
    - the selected objects (items[]),
    - optional raw URIs (uris[]),
    - optional dataspace URIs (dataspaces[] -> eml:///dataspace('<path>')),
    and (optionally) expand references via RDDMS graph endpoints (sources/targets).
    NOTE: We do NOT call /resources/{type}/{uuid} here; the manifest builder
    accepts URIs only, plus ACL/legal and createMissingReferences. This matches
    the official RDDMS v2 OAS. (POST /api/reservoir-ddms/v2/manifests/build)
    """
    at = _access_token(request)

    items = payload.get("items") or []
    include_refs = bool(payload.get("include_refs", True))
    raw_uris = payload.get("uris") or []     # optional pre-resolved URIs
    ds_paths = payload.get("dataspaces") or []  # optional dataspace paths

    legal = payload.get("legal") or osdu.DEFAULT_LEGAL_TAG
    owners = [x.strip() for x in str(payload.get("owners", ",".join(osdu.DEFAULT_OWNERS))).split(",") if x.strip()]
    viewers = [x.strip() for x in str(payload.get("viewers", ",".join(osdu.DEFAULT_VIEWERS))).split(",") if x.strip()]
    countries = [x.strip() for x in str(payload.get("countries", ",".join(osdu.DEFAULT_COUNTRIES))).split(",") if x.strip()]
    create_missing = bool(payload.get("create_missing", True))

    uris: Set[str] = set()

    # 1) Add any raw URIs (trust client)
    for u in raw_uris:
        try:
            u_s = str(u).strip()
            if u_s:
                uris.add(u_s)
        except Exception:
            pass

    # 2) Add dataspace URIs (mimic full-dataspace builder)
    # eml:///dataspace('<path>')
    for path in ds_paths:
        p = str(path or "").strip()
        if p:
            uris.add(f"eml:///dataspace('{p}')")

    # 3) Add canonical object URIs for all selections and optionally expand refs
    for it in items:
        ds = str(it.get("ds") or "")
        typ = _sanitize_type(str(it.get("typ") or ""))
        uid = _sanitize_uuid(str(it.get("uuid") or ""))
        if not ds or not typ or not uid:
            continue
        enc = urllib.parse.quote(ds, safe="")

        # Primary
        uris.add(osdu._eml_uri_from_parts(ds, typ, uid))

        if include_refs:
            try:
                sources = await osdu.list_sources(at, enc, typ, uid)
            except Exception as e:
                log.warning("build-from-selection: list_sources failed: %s", e)
                sources = []
            try:
                targets = await osdu.list_targets(at, enc, typ, uid)
            except Exception as e:
                log.warning("build-from-selection: list_targets failed: %s", e)
                targets = []

            def add_node_uri(node: dict):
                u = node.get("uri")
                if u:
                    uris.add(u); return
                tpath = (node.get("$type") or node.get("type") or "") or _infer_type_path(node)
                nid = _node_uuid(node, fallback_uri=u or "")
                if tpath and nid:
                    uris.add(osdu._eml_uri_from_parts(ds, tpath, nid))

            for node in (sources or []):
                if isinstance(node, dict): add_node_uri(node)
            for node in (targets or []):
                if isinstance(node, dict): add_node_uri(node)

    # 4) Call the manifest builder
    try:
        manifest = await osdu.build_manifest_for_uris(
            at,
            sorted(uris),
            legal_tag=legal,
            owners=owners,
            viewers=viewers,
            countries=countries,
            create_missing_refs=create_missing,
        )
    except HTTPStatusError as e:
        r = e.response
        return JSONResponse(
            {
                "status": "error",
                "code": r.status_code,
                "reason": r.reason_phrase,
                "detail": (r.text[:2000] if r.text else ""),
            },
            status_code=r.status_code or 500,
        )

    app.state.last_manifest = manifest
    log.info("Manifest build: ds_paths=%d items=%d raw_uris=%d → uris=%d",
             len(ds_paths), len(items), len(raw_uris), len(uris))
    return JSONResponse({"status": "ok", "countUris": len(uris), "manifest": manifest})

# ── References graph/preview for a selected object ────────────────────────────

def _canon_uuid_and_type(ds: str, node: Dict[str, Any]) -> Tuple[str, str]:
    """Extract canonical (uuid, typePath) for a node."""
    uri = node.get("uri") or ""
    uid = node.get("Uuid") or node.get("UUID") or node.get("uuid")
    if not uid:
        if "(" in uri and ")" in uri:
            uid = uri.split("(")[-1].rstrip(")")
        else:
            uid = uri or ""
    tpath = _infer_type_path(node)
    return str(uid), tpath or ""

def _as_ref_item(ds: str, node: Dict[str, Any], role: str) -> Dict[str, Any]:
    """Normalize a RDDMS node (source/target/CRS) to a uniform item."""
    uid, tpath = _canon_uuid_and_type(ds, node)
    title = (node.get("Citation") or {}).get("Title") or node.get("name") or uid
    uri = node.get("uri") or osdu._eml_uri_from_parts(ds, tpath or (node.get("$type") or ""), uid)
    return {
        "role": role,  # 'source' | 'target' | 'crs'
        "uuid": uid,
        "typePath": tpath,
        "title": title,
        "uri": uri,
        "contentType": node.get("contentType") or (node.get("$type") or ""),
    }

def _is_crs_type(content_type: str, type_path: str) -> bool:
    ct = (content_type or "").lower()
    tp = (type_path or "").lower()
    return ("crs" in ct) or ("crs" in tp)

def _normalize_resource_obj(obj: Any, uuid: str) -> Dict[str, Any]:
    """
    Ensure we return a dict. If a list is returned by the DDMS, try to select the
    element with matching UUID; otherwise pick the first dict.
    """
    if isinstance(obj, dict):
        return obj
    if isinstance(obj, list):
        for it in obj:
            if isinstance(it, dict):
                uid = it.get("Uuid") or it.get("UUID") or it.get("uuid")
                if uid and str(uid).lower() == (uuid or "").lower():
                    return it
        for it in obj:
            if isinstance(it, dict):
                return it
    return {}

def _extract_refs_any(x: Any) -> List[Dict[str, Any]]:
    """Run osdu.extract_refs() across dict or list-of-dicts."""
    try:
        if isinstance(x, dict):
            return osdu.extract_refs(x) or []
        if isinstance(x, list):
            out: List[Dict[str, Any]] = []
            for it in x:
                if isinstance(it, dict):
                    out.extend(osdu.extract_refs(it) or [])
            return out
    except Exception:
        pass
    return []

@app.get("/keys/object/graph.json")
async def keys_object_graph(
    request: Request,
    ds: str = Query(..., description="Dataspace path"),
    typ: str = Query(..., description="RESQML/EML type (canonical or noisy)"),
    uuid: str = Query(..., description="UUID of the selected object"),
    include_refs: bool = Query(True, description="Include sources/targets/CRS"),
):
    """
    Returns BOTH legacy fields (for keys.html) and new fields (for index.html):
    {
      "uri": "<primary-uri>",
      "sources": [...], "targets": [...], "crs": {...}|null,
      "primary": {...}, "refs": [...],
      "summary": {"sources":N, "targets":M, "crs":K, "total":T}
    }
    """
    at = _access_token(request)
    enc = urllib.parse.quote(ds, safe="")
    typ_s = _sanitize_type(typ)
    uuid_s = _sanitize_uuid(uuid)

    # Primary resource (defensive against list-shaped responses)
    obj_raw = await osdu.get_resource(at, enc, typ_s, uuid_s)
    obj = _normalize_resource_obj(obj_raw, uuid_s)
    primary = {
        "uuid": uuid_s,
        "typePath": typ_s,
        "title": (obj.get("Citation") or {}).get("Title") or uuid_s,
        "uri": obj.get("uri") or osdu._eml_uri_from_parts(ds, typ_s, uuid_s),
        "contentType": obj.get("$type") or obj.get("contentType") or "",
    }

    sources = []
    targets = []
    crs_items = []

    if include_refs:
        # RDDMS graph endpoints (official API)
        try:
            sources = await osdu.list_sources(at, enc, typ_s, uuid_s)
        except Exception as e:
            log.warning("graph: list_sources failed: %s", e)
            sources = []
        try:
            targets = await osdu.list_targets(at, enc, typ_s, uuid_s)
        except Exception as e:
            log.warning("graph: list_targets failed: %s", e)
            targets = []

        # CRS: scan for DataObjectReference-like entries mentioning CRS
        for edge in _extract_refs_any(obj_raw):
            tpath = _infer_type_path(edge)
            item = {
                "$type": tpath,
                "contentType": edge.get("contentType"),
                "UUID": edge.get("uuid"),
            }
            if _is_crs_type(edge.get("contentType", ""), tpath):
                crs_items.append(_as_ref_item(ds, item, "crs"))

    # Unified refs
    refs = []
    refs.extend([_as_ref_item(ds, s, "source") for s in (sources or []) if isinstance(s, dict)])
    refs.extend([_as_ref_item(ds, t, "target") for t in (targets or []) if isinstance(t, dict)])
    refs.extend(crs_items or [])

    # Deduplicate (typePath, uuid)
    seen = set()
    uniq = []
    for r in refs:
        key = (r.get("typePath") or "", r.get("uuid") or "")
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)
    refs = uniq

    crs_legacy = next((r for r in refs if r.get("role") == "crs"), None)
    summary = {
        "sources": len([r for r in refs if r["role"] == "source"]),
        "targets": len([r for r in refs if r["role"] == "target"]),
        "crs": len([r for r in refs if r["role"] == "crs"]),
        "total": len(refs),
    }
    return JSONResponse({
        "uri": primary["uri"],
        "sources": sources,
        "targets": targets,
        "crs": crs_legacy,
        "primary": primary,
        "refs": refs,
        "summary": summary,
    })

# ── OSDU storage helper (auth-aware) ──────────────────────────────────────────

async def osdu_get_record(request: Request, record_id: str) -> dict:
    at = _access_token(request)
    base = f"https://{osdu.OSDU_BASE_URL}/api/storage/v2/records"
    url = f"{base}/{urllib.parse.quote(record_id, safe='')}"
    hdr = osdu.headers(at)
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(url, headers=hdr)
        if r.status_code == 200:
            return r.json()
        if r.status_code == 404:
            return {}
        r.raise_for_status()
    return {}

def _safe(lst):
    return lst if isinstance(lst, list) else []

def _get_data(rec):
    return rec.get("data") or {}
