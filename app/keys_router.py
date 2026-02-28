"""
Keys / RDDMS explorer — browse dataspaces, types, objects, graphs, tables,
and build OSDU manifests from selected RESQML/EML resources.

Provides:
  GET  /keys                                → render the keys.html template
  GET  /keys/dataspaces.json                → JSON: list dataspaces
  GET  /keys/types.json                     → JSON: list types in a dataspace
  GET  /keys/object.json                    → JSON: single object detail
  GET  /keys/objects.json                   → JSON: aggregated object list
  GET  /keys/object/table.json              → JSON: Grid2d table reconstruction
  GET  /keys/object/graph.json              → JSON: object graph (refs)
  POST /dataspaces/create                   → (remains in main.py — home page)
  POST /dataspaces/delete                   → JSON: delete a dataspace
  POST /dataspaces/lock                     → JSON: lock a dataspace
  POST /dataspaces/unlock                   → JSON: unlock a dataspace
  POST /dataspaces/manifest                 → JSON: build manifest (full dataspace)
  POST /dataspaces/manifest/build-uris      → JSON: build manifest (single object)
  POST /dataspaces/manifest/build-from-selection → JSON: build manifest (multi-select)
"""
from __future__ import annotations

import logging
import os
import re
import urllib.parse
from typing import Any, Dict, List, Optional, Set, Tuple

from httpx import HTTPStatusError
from fastapi import APIRouter, Body, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from . import osdu
from .schemahandler import extract_metadata_generic

router = APIRouter()
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))
log = logging.getLogger("rddms-admin.keys")


# ──────────────────────────────────────────────────────────────────────────────
# Utilities
# ──────────────────────────────────────────────────────────────────────────────

def _access_token(request: Request) -> str:
    at = getattr(request.state, "access_token", None)
    if not at:
        raise HTTPException(401, "Authentication failed")
    return at


# ──────────────────────────────────────────────────────────────────────────────
# KEYS page: dataspace -> type -> object
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/keys", response_class=HTMLResponse)
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

@router.get("/keys/dataspaces.json")
async def keys_dataspaces(request: Request):
    at = _access_token(request)
    try:
        rows = await osdu.list_dataspaces(at)
    except Exception as e:
        log.warning("keys_dataspaces failed: %s", e)
        rows = []
    items = [{"path": x.get("path"), "uri": x.get("uri")} for x in rows if x.get("path")]
    return JSONResponse({"items": items})

@router.get("/keys/types.json")
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

@router.post("/dataspaces/delete", summary="Delete a dataspace")
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

@router.post("/dataspaces/lock", summary="Lock a dataspace")
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

@router.post("/dataspaces/unlock", summary="Unlock a dataspace")
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

@router.post("/dataspaces/manifest", summary="Build OSDU manifest for a dataspace")
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


# ──────────────────────────────────────────────────────────────────────────────
# Object detail
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/keys/object.json")
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
    metadata = None
    try:
        metadata = extract_metadata_generic(
            obj,
            ds=ds, typ=typ_s, uuid=uuid_s,
            arrays=arrays,
            max_string_len=300,
            max_preview_items=5,
        )
    except Exception as e:
        log.exception("keys_object_json: extract_metadata_generic FAILED: %s", e)
        metadata = {"error": str(e), "pairs": []}
    return JSONResponse({
        "primary": primary,
        "content": obj,
        "arrays": arrays,
        "metadata": metadata,
    })


@router.get("/keys/objects.json")
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


# ── route: manifest building ──────────────────────────────────────────────────

def _add_node_uri(node: Dict[str, Any], uris: Set[str], ds: str) -> None:
    """Extract the EML URI from a RDDMS graph node and add it to *uris*."""
    uri = node.get("uri") or ""
    if uri:
        uris.add(uri)
        return
    # Fallback: construct the URI from type + uuid
    uid = _node_uuid(node)
    tpath = _infer_type_path(node)
    if uid and tpath:
        uris.add(osdu._eml_uri_from_parts(ds, tpath, uid))

@router.post("/dataspaces/manifest/build-uris", summary="Build manifest for one object (+ optional refs)")
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

        for node in (sources or []):
            if isinstance(node, dict): _add_node_uri(node, uris, ds)
        for node in (targets or []):
            if isinstance(node, dict): _add_node_uri(node, uris, ds)

    try:
        manifest = await osdu.build_manifest_for_uris(
            at,
            sorted(uris),
            legal_tag=legal or osdu.DEFAULT_LEGAL_TAG,
            owners=[x.strip() for x in owners.split(",") if x.strip()],
            viewers=[x.strip() for x in viewers.split(",") if x.strip()],
            countries=[x.strip() for x in countries.split(",") if x.strip()],
            create_missing_refs=bool(create_missing),
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
    request.app.state.last_manifest = manifest
    return JSONResponse({"status": "ok", "countUris": len(uris), "manifest": manifest})

@router.post("/dataspaces/manifest/build-from-selection",
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

            for node in (sources or []):
                if isinstance(node, dict): _add_node_uri(node, uris, ds)
            for node in (targets or []):
                if isinstance(node, dict): _add_node_uri(node, uris, ds)

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

    request.app.state.last_manifest = manifest
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


# ── Table reconstruction for Grid2dRepresentation (resqpy DataFrame) ──────────

MAX_TABLE_ROWS = 1000  # safety cutoff for huge tables

@router.get("/keys/object/table.json")
async def keys_object_table(
    request: Request,
    ds: str = Query(..., description="Dataspace path"),
    typ: str = Query(..., description="RESQML/EML type"),
    uuid: str = Query(..., description="UUID of Grid2dRepresentation"),
    max_rows: int = Query(MAX_TABLE_ROWS, description="Row cutoff"),
):
    """Reconstruct a tabular view from a Grid2dRepresentation (resqpy DataFrame).

    Returns:
    {
      "columns": ["col1","col2",...],
      "uoms":    ["Euc","m3",...],
      "rows":    [[val,val,...], ...],
      "n_rows": int, "n_cols": int,
      "truncated": bool, "max_rows": int,
      "string_lookups": {"col_name": {0:"A",1:"B",...}, ...}
    }
    """
    at = _access_token(request)
    enc = urllib.parse.quote(ds, safe="")
    typ_s = _sanitize_type(typ)
    uuid_s = _sanitize_uuid(uuid)

    # 1. Get the Grid2d object to extract shape
    obj_raw = await osdu.get_resource(at, enc, typ_s, uuid_s)
    obj = _normalize_resource_obj(obj_raw, uuid_s)

    ctype = obj.get("$type") or obj.get("contentType") or ""
    if "Grid2dRepresentation" not in ctype and "Grid2dRepresentation" not in typ_s:
        return JSONResponse({"error": "Not a Grid2dRepresentation"}, status_code=400)

    grid_patch = obj.get("Grid2dPatch") or {}
    n_cols = int(grid_patch.get("FastestAxisCount", 0))
    n_rows = int(grid_patch.get("SlowestAxisCount", 0))

    # 2. Read the zvalues array — first discover the actual path via list_arrays
    zvalues_data = {}
    zvalues_path = "zvalues"  # fallback
    try:
        arr_list = await osdu.list_arrays(at, enc, typ_s, uuid_s)
        for arr_item in (arr_list or []):
            uid = arr_item.get("uid") or {}
            pir = uid.get("pathInResource") or ""
            if pir.endswith("/zvalues") or pir == "zvalues":
                zvalues_path = pir
                break
    except Exception as e:
        log.warning("table: list_arrays failed: %s", e)

    try:
        zvalues_data = await osdu.read_array(
            at, enc, typ_s, uuid_s,
            path_in_resource=urllib.parse.quote(zvalues_path, safe=""),
        )
    except Exception as e:
        log.warning("table: read_array(%s) failed: %s", zvalues_path, e)
        return JSONResponse({"error": f"Failed to read zvalues at path '{zvalues_path}': {e}"}, status_code=502)

    # Parse the flat array into rows
    flat = zvalues_data.get("data") or zvalues_data.get("values") or zvalues_data
    if isinstance(flat, dict) and "data" in flat:
        flat = flat["data"]
    if isinstance(flat, dict) and "values" in flat:
        flat = flat["values"]
    if not isinstance(flat, list):
        return JSONResponse({"error": "Unexpected zvalues format", "raw_keys": list(zvalues_data.keys()) if isinstance(zvalues_data, dict) else []}, status_code=502)

    # Reshape flat array into 2D: (n_rows, n_cols)
    truncated = False
    if n_cols > 0 and len(flat) >= n_cols:
        actual_rows = len(flat) // n_cols
        if actual_rows > max_rows:
            actual_rows = max_rows
            truncated = True
        rows = []
        for i in range(actual_rows):
            rows.append(flat[i * n_cols:(i + 1) * n_cols])
    else:
        rows = [flat]

    # 3. Resolve StringTableLookups for column names, UoMs, and string decode maps.
    #    Strategy: (a) ExtraMetadata stl_columns/stl_uoms UUIDs (future-proof),
    #              (b) RDDMS graph targets (works if RDDMS exposes .rels),
    #              (c) Fallback — scan all STLs in dataspace, match by entry-count.
    columns = [f"col_{i}" for i in range(n_cols)]
    uoms = ["" for _ in range(n_cols)]
    string_lookups: dict[str, dict] = {}

    stl_type = "resqml20.obj_StringTableLookup"

    async def _fetch_stl(stl_uuid: str) -> dict | None:
        try:
            raw = await osdu.get_resource(at, enc, stl_type, str(stl_uuid))
            return _normalize_resource_obj(raw, str(stl_uuid))
        except Exception as e:
            log.warning("table: get STL %s failed: %s", stl_uuid, e)
            return None

    def _parse_stl_entries(stl_obj: dict) -> dict[int, str]:
        entries = stl_obj.get("Value") or []
        if not isinstance(entries, list):
            return {}
        lookup: dict[int, str] = {}
        for entry in entries:
            if isinstance(entry, dict):
                idx = entry.get("Key")
                val = entry.get("Value") or entry.get("value") or entry.get("StringValue")
                if idx is not None and val is not None:
                    lookup[int(idx)] = str(val)
        return lookup

    def _classify_stl(stl_obj: dict, lookup: dict[int, str]) -> str:
        """Classify an STL as 'columns', 'uoms', or 'decode'."""
        title = ((stl_obj.get("Citation") or {}).get("Title") or "").lower()
        if "column" in title or "name" in title:
            return "columns"
        if "uom" in title or "unit" in title:
            return "uoms"
        return "decode"

    def _apply_stl(stl_obj: dict, lookup: dict[int, str], role: str) -> None:
        if role == "columns":
            for i in range(min(len(lookup), n_cols)):
                if i in lookup:
                    columns[i] = lookup[i]
        elif role == "uoms":
            for i in range(min(len(lookup), n_cols)):
                if i in lookup:
                    uoms[i] = lookup[i]
        else:
            label = (stl_obj.get("Citation") or {}).get("Title") or "unknown"
            string_lookups[label] = {str(k): v for k, v in lookup.items()}

    stl_resolved = False

    # --- Strategy (a): ExtraMetadata with explicit STL UUIDs -----------
    extra = obj.get("ExtraMetadata") or []
    em_map: dict[str, str] = {}
    for em in extra:
        if isinstance(em, dict):
            k = em.get("Name") or em.get("name") or ""
            v = em.get("Value") or em.get("value") or ""
            if k and v:
                em_map[k] = v

    em_stl_uuids: list[str] = []
    for key in ("stl_columns", "stl_uoms", "stl_decode"):
        if key in em_map:
            for u in em_map[key].split(","):
                u = u.strip()
                if u:
                    em_stl_uuids.append(u)

    if em_stl_uuids:
        log.info("table: using ExtraMetadata STL UUIDs: %s", em_stl_uuids)
        for stl_uuid in em_stl_uuids:
            stl_obj = await _fetch_stl(stl_uuid)
            if not stl_obj:
                continue
            lookup = _parse_stl_entries(stl_obj)
            role = _classify_stl(stl_obj, lookup)
            _apply_stl(stl_obj, lookup, role)
        stl_resolved = columns[0] != "col_0"

    # --- Strategy (b): RDDMS graph targets ----------------------------
    if not stl_resolved:
        try:
            targets = await osdu.list_targets(at, enc, typ_s, uuid_s)
        except Exception:
            targets = []

        stl_targets = []
        for t in (targets or []):
            if not isinstance(t, dict):
                continue
            # Check for STL type in $type, contentType, or URI
            t_type = t.get("$type") or t.get("contentType") or t.get("type") or ""
            t_uri = t.get("uri") or ""
            if stl_type in t_type or stl_type in t_uri:
                uid = t.get("Uuid") or t.get("UUID") or t.get("uuid") or ""
                if not uid and t_uri:
                    # Extract UUID from URI like eml:///dataspace('...')/resqml20.obj_StringTableLookup('uuid')
                    m = re.search(r"StringTableLookup\('?([0-9a-f-]+)'?\)", t_uri)
                    if m:
                        uid = m.group(1)
                if uid:
                    stl_targets.append(uid)

        for stl_uuid in stl_targets:
            stl_obj = await _fetch_stl(stl_uuid)
            if not stl_obj:
                continue
            lookup = _parse_stl_entries(stl_obj)
            role = _classify_stl(stl_obj, lookup)
            _apply_stl(stl_obj, lookup, role)
        if stl_targets:
            stl_resolved = columns[0] != "col_0"

    # --- Strategy (c): Scan all STLs in the dataspace, match by count --
    if not stl_resolved and n_cols > 0:
        log.info("table: falling back to STL scan for n_cols=%d", n_cols)
        try:
            all_stls = await osdu.list_resources(at, enc, stl_type)
        except Exception:
            all_stls = []

        # Fetch the Grid2d's storeCreated for proximity tie-breaking
        grid_created = obj_raw.get("storeCreated") if isinstance(obj_raw, dict) else ""

        # Fetch each STL and classify
        col_candidates: list[tuple[dict, dict[int, str], str]] = []  # (obj, lookup, ts)
        uom_candidates: list[tuple[dict, dict[int, str], str]] = []
        decode_candidates: list[tuple[dict, dict[int, str], str]] = []

        for stl_node in (all_stls or []):
            if not isinstance(stl_node, dict):
                continue
            stl_uuid = stl_node.get("Uuid") or stl_node.get("UUID") or stl_node.get("uuid") or ""
            if not stl_uuid:
                # Try extracting UUID from uri
                uri = stl_node.get("uri") or ""
                m = re.search(r"\(([0-9a-f-]+)\)", uri)
                if m:
                    stl_uuid = m.group(1)
            if not stl_uuid:
                continue

            stl_obj = await _fetch_stl(stl_uuid)
            if not stl_obj:
                continue

            lookup = _parse_stl_entries(stl_obj)
            if not lookup:
                continue

            role = _classify_stl(stl_obj, lookup)
            ts = stl_node.get("storeCreated") or ""

            if role == "columns" and len(lookup) == n_cols:
                col_candidates.append((stl_obj, lookup, ts))
            elif role == "uoms" and len(lookup) == n_cols:
                uom_candidates.append((stl_obj, lookup, ts))
            elif role == "decode" and len(lookup) < n_cols:
                decode_candidates.append((stl_obj, lookup, ts))

        # Pick best candidate by timestamp proximity to Grid2d
        def _pick_closest(candidates: list, grid_ts: str) -> tuple | None:
            if not candidates:
                return None
            if len(candidates) == 1:
                return candidates[0]
            if not grid_ts:
                return candidates[-1]  # latest
            # Sort by absolute time distance to grid_ts
            try:
                from datetime import datetime
                gt = datetime.fromisoformat(grid_ts.replace("Z", "+00:00"))
                scored = []
                for c in candidates:
                    try:
                        ct = datetime.fromisoformat(c[2].replace("Z", "+00:00"))
                        scored.append((abs((ct - gt).total_seconds()), c))
                    except Exception:
                        scored.append((9999999, c))
                scored.sort(key=lambda x: x[0])
                return scored[0][1]
            except Exception:
                return candidates[-1]

        best_cols = _pick_closest(col_candidates, grid_created)
        if best_cols:
            _apply_stl(best_cols[0], best_cols[1], "columns")

        best_uoms = _pick_closest(uom_candidates, grid_created)
        if best_uoms:
            _apply_stl(best_uoms[0], best_uoms[1], "uoms")

        for dec_obj, dec_lookup, _ in decode_candidates:
            _apply_stl(dec_obj, dec_lookup, "decode")

    # 4. Decode string-encoded columns: if column values are all integers
    #    and a StringTableLookup matches, replace codes with strings
    for col_idx, col_name in enumerate(columns):
        for stl_label, stl_map in string_lookups.items():
            # Match by column name appearing in the STL title
            if col_name.lower() not in stl_label.lower():
                continue
            # Decode: replace float codes in rows with string values
            for row in rows:
                if col_idx < len(row):
                    code = row[col_idx]
                    if isinstance(code, (int, float)):
                        s_code = str(int(code))
                        if s_code in stl_map:
                            row[col_idx] = stl_map[s_code]
            break

    return JSONResponse({
        "columns": columns,
        "uoms": uoms,
        "rows": rows,
        "n_rows": n_rows,
        "n_cols": n_cols,
        "truncated": truncated,
        "max_rows": max_rows,
        "string_lookups": string_lookups,
    })


# ── Object graph ──────────────────────────────────────────────────────────────

@router.get("/keys/object/graph.json")
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
