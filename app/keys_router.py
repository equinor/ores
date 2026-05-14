"""
Keys / RDDMS explorer - browse dataspaces, types, objects, graphs, tables,
and build OSDU manifests from selected RESQML/EML resources.

Provides:
  GET  /keys                                → render the keys.html template
  GET  /keys/dataspaces.json                → JSON: list dataspaces
  GET  /keys/types.json                     → JSON: list types in a dataspace
  GET  /keys/object.json                    → JSON: single object detail
  GET  /keys/objects.json                   → JSON: aggregated object list
  GET  /keys/object/table.json              → JSON: Grid2d table reconstruction
  GET  /keys/object/graph.json              → JSON: object graph (refs)
  POST /dataspaces/create                   → (remains in main.py - home page)
  POST /dataspaces/delete                   → JSON: delete a dataspace
  POST /dataspaces/lock                     → JSON: lock a dataspace
  POST /dataspaces/unlock                   → JSON: unlock a dataspace
  POST /dataspaces/manifest                 → JSON: build manifest (full dataspace)
  POST /dataspaces/manifest/build-uris      → JSON: build manifest (single object)
  POST /dataspaces/manifest/build-from-selection → JSON: build manifest (multi-select)
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
import urllib.parse
from typing import Any, Dict, List, Optional, Set, Tuple

from httpx import HTTPStatusError
from fastapi import APIRouter, Body, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from . import osdu
from . import resqml_viz
from . import structuremap as smap_mod
from .common import access_token as _access_token, normalize_obj as _normalize_resource_obj, http_error_response, safe_error_detail
from .schemahandler import extract_metadata_generic

router = APIRouter()
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))
log = logging.getLogger("rddms-admin.keys")


# ──────────────────────────────────────────────────────────────────────────────
# KEYS page: dataspace -> type -> object
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/keys", response_class=HTMLResponse)
async def keys_page(request: Request):
    # Render immediately - dataspaces loaded async via JS /keys/dataspaces.json
    return templates.TemplateResponse(
        request, "keys.html",
        {"prefill_ds": []},
        media_type="text/html",
    )

@router.get("/keys/dataspaces.json")
async def keys_dataspaces(request: Request):
    """Merge dataspaces from local PG + remote OSDU RDDMS, tagged with source.

    Both sources are fetched in parallel for speed.
    Query params:
      ?source=local  → only local PG (instant)
      ?source=remote → only remote RDDMS
      (default)      → both merged
    """
    at = _access_token(request)
    items: List[Dict[str, Any]] = []
    seen_paths: set = set()

    source_filter = (request.query_params.get("source") or "").lower()

    # --- Fetch functions ---
    async def _fetch_local() -> List[Dict[str, Any]]:
        try:
            from .pg_backend import get_pool, pg_list_dataspaces
            pool = await get_pool()
            if pool:
                return await pg_list_dataspaces(pool)
        except Exception as e:
            log.debug("keys_dataspaces local PG failed: %s", e)
        return []

    async def _fetch_remote() -> List[Dict[str, Any]]:
        try:
            return await osdu.list_dataspaces(at)
        except Exception as e:
            log.debug("keys_dataspaces remote RDDMS failed with user token: %s", e)
        # Fallback: use instance-level token (client_credentials / env RT)
        try:
            from .instances import get_active
            inst = get_active()
            fallback_at = await inst.get_access_token()
            if fallback_at and fallback_at != at:
                return await osdu.list_dataspaces(fallback_at)
        except Exception as e2:
            log.warning("keys_dataspaces remote RDDMS fallback also failed: %s", e2)
        return []

    # --- Choose what to fetch based on ?source= ---
    if source_filter == "local":
        pg_rows = await _fetch_local()
        remote_rows = []
    elif source_filter == "remote":
        pg_rows = []
        remote_rows = await _fetch_remote()
    else:
        pg_rows, remote_rows = await asyncio.gather(_fetch_local(), _fetch_remote())

    # 1. Local PG dataspaces
    for x in pg_rows:
        p = x.get("path", "")
        if p and p not in seen_paths:
            items.append({"path": p, "uri": x.get("uri", ""), "source": "local"})
            seen_paths.add(p)

    # 2. Remote OSDU RDDMS dataspaces
    for x in remote_rows:
        p = x.get("path") or x.get("Path") or x.get("DataspaceId") or ""
        if p and p not in seen_paths:
            items.append({"path": p, "uri": x.get("uri", ""), "source": "remote"})
            seen_paths.add(p)

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
        # Try local PG first (instant, no network), fall back to REST
        pg_done = False
        try:
            from .pg_backend import get_pool, pg_list_types
            pool = await get_pool()
            if pool:
                pg_items = await pg_list_types(pool, ds)
                if pg_items:
                    items = pg_items
                    pg_done = True
        except Exception as e:
            log.debug("keys_types PG failed for %s: %s", ds, e)

        if not pg_done:
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
            "resqml20.obj_TriangulatedSetRepresentation",
            "resqml20.obj_PointSetRepresentation",
            "resqml20.obj_HorizonInterpretation",
            "resqml20.obj_GeneticBoundaryFeature",
            "resqml20.obj_IjkGridRepresentation",
            "resqml20.obj_WellboreTrajectoryRepresentation",
            "resqml20.obj_WellboreMarkerFrameRepresentation",
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
        from .cache import cache_invalidate
        cache_invalidate("list_dataspaces")
    except HTTPStatusError as e:
        return http_error_response(e)
    return JSONResponse({"status": "ok"})

@router.post("/dataspaces/lock", summary="Lock a dataspace")
async def dataspaces_lock(request: Request, path: str = Form(...)):
    at = _access_token(request)
    try:
        await osdu.lock_dataspace(at, path)
    except HTTPStatusError as e:
        return http_error_response(e)
    return JSONResponse({"status": "ok"})

@router.post("/dataspaces/unlock", summary="Unlock a dataspace")
async def dataspaces_unlock(request: Request, path: str = Form(...)):
    at = _access_token(request)
    try:
        await osdu.unlock_dataspace(at, path)
    except HTTPStatusError as e:
        return http_error_response(e)
    return JSONResponse({"status": "ok"})

@router.post("/dataspaces/import", summary="Import (copy) content from a locked dataspace into another")
async def dataspaces_import(request: Request, src: str = Form(...), dst: str = Form(...)):
    at = _access_token(request)
    try:
        result = await osdu.import_dataspace(at, src, dst)
    except HTTPStatusError as e:
        return http_error_response(e)
    return JSONResponse({"status": "ok", **result})

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
        return http_error_response(e)
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
    if "dataspace('" in uri and ")/" in uri:
        try:
            after = uri.split(")/", 1)[1]
            # Strip UUID suffix: resqml20.obj_TypeName(uuid) -> resqml20.obj_TypeName
            type_part = after.split("(", 1)[0].strip()
            if type_part:
                return type_part
        except Exception:
            pass
    return ""


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

    obj = None
    arrays: list = []

    # ── Try local PG first (fast, no network) ─────────────────────────
    try:
        from .pg_backend import get_pool
        pool = await get_pool()
        if pool:
            pg_obj, pg_arrays = await resqml_viz.pg_get_object_and_arrays(
                pool, ds, typ_s, uuid_s,
            )
            if pg_obj is not None:
                obj = pg_obj
                arrays = pg_arrays or []
                log.info("keys_object_json: served from PG ds=%s uuid=%s", ds, uuid_s)
    except Exception as e:
        log.debug("keys_object_json: PG failed, falling back to REST: %s", e)

    # ── REST fallback ─────────────────────────────────────────────────
    if obj is None:
        try:
            obj_raw = await osdu.get_resource(at, enc, typ_s, uuid_s)
            obj = _normalize_resource_obj(obj_raw, uuid_s)
        except HTTPStatusError as exc:
            return http_error_response(exc)
        try:
            arrays = await osdu.list_arrays(at, enc, typ_s, uuid_s)
        except Exception as e:
            log.warning("keys_object_json: list_arrays failed: %s", e)
            arrays = []

    primary = {
        "uuid": uuid_s,
        "typePath": typ_s,
        "title": (obj.get("Citation") or {}).get("Title") or uuid_s,
        "uri": obj.get("uri") or osdu._eml_uri_from_parts(ds, typ_s, uuid_s),
        "contentType": obj.get("$type") or obj.get("contentType") or "",
    }

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
    - Try local PG first (fast), fall back to RDDMS REST.
    - If 'typ' provided -> list via RDDMS /resources/{type}
    - If 'typ' omitted  -> try RDDMS /resources/all; on failure/empty, fall back to
      enumerating types via /resources and aggregating /resources/{type}.
    Supports 'q' as contains filter on title/uuid ('*' means no filter).
    """
    at = _access_token(request)
    enc = urllib.parse.quote(ds, safe="")
    rows: List[Dict[str, Any]] = []

    # --- Try local PG first (instant, no network) ---
    pg_done = False
    try:
        from .pg_backend import get_pool, pg_list_resources, pg_list_types
        pool = await get_pool()
        if pool:
            if typ:
                pg_rows = await pg_list_resources(pool, ds, typ, limit=500)
            else:
                # Get all types then aggregate
                pg_types = await pg_list_types(pool, ds)
                if pg_types:
                    parts = await asyncio.gather(
                        *[pg_list_resources(pool, ds, t["name"], limit=500) for t in pg_types if t.get("name")]
                    )
                    pg_rows = []
                    for part in parts:
                        pg_rows.extend(part)
                else:
                    pg_rows = []
            if pg_rows:
                rows = pg_rows
                pg_done = True
    except Exception as e:
        log.debug("keys_objects PG failed for %s: %s", ds, e)

    # --- Fall back to RDDMS REST ---
    if not pg_done:
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
                # Fallback: enumerate types and aggregate (parallel)
                if not rows:
                    try:
                        types = await osdu.list_types(at, enc) or []
                        names = [t.get("name") if isinstance(t, dict) else t for t in types if t]
                        names = [n for n in names if n]

                        async def _fetch_type(name):
                            try:
                                return await osdu.list_resources(at, enc, name) or []
                            except Exception as e_type:
                                log.warning("keys_objects: list_resources(%s) failed: %s", name, e_type)
                                return []

                        parts = await asyncio.gather(*[_fetch_type(n) for n in names])
                        agg: List[Dict[str, Any]] = []
                        for part in parts:
                            agg.extend(part)
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
        # When listing by specific type and inference fails, use the requested type
        if not type_path and typ:
            type_path = _sanitize_type(typ)

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

# Types whose URIs crash the RDDMS manifests/build endpoint (server 500).
# EpcExternalPartReference is an internal EPC packaging artefact (array
# data references) with no OSDU WPC mapping - the builder cannot handle it.
_MANIFEST_SKIP_TYPES = {
    "obj_EpcExternalPartReference",
}

def _uri_has_skip_type(uri: str) -> bool:
    """Return True if *uri* contains a type known to crash manifests/build."""
    for t in _MANIFEST_SKIP_TYPES:
        if t in uri:
            return True
    return False

def _filter_manifest_uris(uris: Set[str]) -> tuple[Set[str], Set[str]]:
    """Partition *uris* into (safe, skipped) sets."""
    safe: Set[str] = set()
    skipped: Set[str] = set()
    for u in uris:
        if _uri_has_skip_type(u):
            skipped.add(u)
        else:
            safe.add(u)
    return safe, skipped

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
    t0 = time.monotonic()

    # Expand refs via graph endpoints (parallel)
    if include_refs:
        async def _get_sources():
            try:
                return await osdu.list_sources(at, enc, typ_s, uuid_s)
            except Exception as e:
                log.warning("build-uris: list_sources failed: %s", e)
                return []

        async def _get_targets():
            try:
                return await osdu.list_targets(at, enc, typ_s, uuid_s)
            except Exception as e:
                log.warning("build-uris: list_targets failed: %s", e)
                return []

        sources, targets = await asyncio.gather(_get_sources(), _get_targets())
        log.info("build-uris: refs resolved in %.1fs (sources=%d, targets=%d)",
                 time.monotonic() - t0, len(sources or []), len(targets or []))

        for node in (sources or []):
            if isinstance(node, dict): _add_node_uri(node, uris, ds)
        for node in (targets or []):
            if isinstance(node, dict): _add_node_uri(node, uris, ds)

    safe_uris, skipped = _filter_manifest_uris(uris)
    if not safe_uris:
        skipped_types = {u.split("/")[-1].split("(")[0] for u in skipped}
        return JSONResponse(
            {"status": "error", "code": 422,
             "reason": "No buildable URIs",
             "detail": (f"All {len(skipped)} URI(s) were skipped because their types "
                        f"({', '.join(sorted(skipped_types))}) are not supported by "
                        "the RDDMS manifests/build endpoint.")},
            status_code=422,
        )

    t1 = time.monotonic()
    try:
        manifest = await osdu.build_manifest_for_uris(
            at,
            sorted(safe_uris),
            legal_tag=legal or osdu.DEFAULT_LEGAL_TAG,
            owners=[x.strip() for x in owners.split(",") if x.strip()],
            viewers=[x.strip() for x in viewers.split(",") if x.strip()],
            countries=[x.strip() for x in countries.split(",") if x.strip()],
            create_missing_refs=bool(create_missing),
        )
    except HTTPStatusError as e:
        return http_error_response(e)
    log.info("build-uris: manifest built in %.1fs (uris=%d, total=%.1fs)",
             time.monotonic() - t1, len(safe_uris), time.monotonic() - t0)
    result: Dict[str, Any] = {"status": "ok", "countUris": len(safe_uris), "manifest": manifest}
    if skipped:
        result["skippedUris"] = len(skipped)
        result["skippedTypes"] = sorted({u.split("/")[-1].split("(")[0] for u in skipped})
    return JSONResponse(result)

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
    ref_tasks = []
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
            async def _expand(ds_=ds, enc_=enc, typ_=typ, uid_=uid):
                nodes = []
                try:
                    nodes += await osdu.list_sources(at, enc_, typ_, uid_) or []
                except Exception as e:
                    log.warning("build-from-selection: list_sources failed: %s", e)
                try:
                    nodes += await osdu.list_targets(at, enc_, typ_, uid_) or []
                except Exception as e:
                    log.warning("build-from-selection: list_targets failed: %s", e)
                return ds_, nodes
            ref_tasks.append(_expand())

    if ref_tasks:
        t_ref = time.monotonic()
        ref_results = await asyncio.gather(*ref_tasks)
        for ds_r, nodes in ref_results:
            for node in nodes:
                if isinstance(node, dict): _add_node_uri(node, uris, ds_r)
        log.info("build-from-selection: refs resolved in %.1fs (%d items)",
                 time.monotonic() - t_ref, len(ref_tasks))

    # 4) Filter out types that crash manifests/build
    safe_uris, skipped = _filter_manifest_uris(uris)
    if not safe_uris:
        skipped_types = {u.split("/")[-1].split("(")[0] for u in skipped}
        return JSONResponse(
            {"status": "error", "code": 422,
             "reason": "No buildable URIs",
             "detail": (f"All {len(skipped)} URI(s) were skipped because their types "
                        f"({', '.join(sorted(skipped_types))}) are not supported by "
                        "the RDDMS manifests/build endpoint.")},
            status_code=422,
        )

    # 5) Call the manifest builder
    try:
        manifest = await osdu.build_manifest_for_uris(
            at,
            sorted(safe_uris),
            legal_tag=legal,
            owners=owners,
            viewers=viewers,
            countries=countries,
            create_missing_refs=create_missing,
        )
    except HTTPStatusError as e:
        return http_error_response(e)

    log.info("Manifest build: ds_paths=%d items=%d raw_uris=%d → safe=%d skipped=%d",
             len(ds_paths), len(items), len(raw_uris), len(safe_uris), len(skipped))
    result: Dict[str, Any] = {"status": "ok", "countUris": len(safe_uris), "manifest": manifest}
    if skipped:
        result["skippedUris"] = len(skipped)
        result["skippedTypes"] = sorted({u.split("/")[-1].split("(")[0] for u in skipped})
    return JSONResponse(result)


# ── StructureMap:1.0.0 endpoints (M27) ───────────────────────────────────────

@router.get("/keys/structuremaps/surfaces.json",
            summary="List Grid2dRepresentations classified by domain")
async def keys_structuremap_surfaces(
    request: Request,
    ds: str = Query(..., description="Dataspace path, e.g. maap/drogon"),
):
    """Discover and classify all Grid2dRepresentations in a dataspace.

    Returns {items: [{uuid, title, domain, dims, crs_title, interpretation, uri}, ...]}
    where domain is 'depth', 'time', or 'unknown'.
    """
    at = _access_token(request)
    try:
        surfaces = await smap_mod.discover_surfaces(at, ds)
    except HTTPStatusError as e:
        return http_error_response(e)
    except Exception as e:
        log.exception("structuremap_surfaces failed: %s", e)
        return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)

    depth = [s for s in surfaces if s.get("domain") == "depth"]
    time_ = [s for s in surfaces if s.get("domain") == "time"]
    return JSONResponse({
        "items": surfaces,
        "summary": {
            "total": len(surfaces),
            "depth": len(depth),
            "time": len(time_),
        },
    })


@router.get("/keys/structuremaps.json",
            summary="Generate StructureMap:1.0.0 records from RDDMS surfaces")
async def keys_structuremaps(
    request: Request,
    ds: str = Query(..., description="Dataspace path, e.g. maap/drogon"),
    prefix: str = Query("dev", description="OSDU namespace prefix"),
    uuids: Optional[str] = Query(
        None,
        description="Comma-separated Grid2d UUIDs to convert (omit for all depth surfaces)",
    ),
):
    """Discover depth-domain Grid2dRepresentations and generate
    StructureMap:1.0.0 records (OSDU M27 schema).

    Returns:
    {
      "dataspace": "maap/drogon",
      "grid2d_count": 12,
      "depth_count": 8,
      "structuremaps": [ {id, kind, acl, legal, data}, ... ],
      "surfaces": [ {uuid, title, domain, dims}, ... ]
    }
    """
    at = _access_token(request)
    uuid_list = None
    if uuids:
        uuid_list = [u.strip() for u in uuids.split(",") if u.strip()]

    try:
        result = await smap_mod.generate_structuremaps(
            at, ds, prefix=prefix, uuids=uuid_list,
        )
    except HTTPStatusError as e:
        return http_error_response(e)
    except Exception as e:
        log.exception("structuremaps generation failed: %s", e)
        return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)

    return JSONResponse(result)


@router.post("/dataspaces/manifest/structuremaps",
             summary="Build M27 StructureMap manifest from RDDMS surfaces")
async def dataspaces_manifest_structuremaps(
    request: Request,
    payload: Dict[str, Any] = Body(
        ...,
        description=(
            "JSON: { ds: 'maap/drogon', prefix?: 'dev', "
            "uuids?: ['uuid1','uuid2'] }"
        ),
    ),
):
    """Generate StructureMap:1.0.0 records and wrap them in an OSDU manifest.

    If 'uuids' is provided, only those Grid2d surfaces are converted.
    Otherwise, all depth-domain surfaces in the dataspace are converted.

    Returns a complete OSDU manifest ready for ingestion.
    """
    at = _access_token(request)
    ds = str(payload.get("ds") or "").strip()
    if not ds:
        return JSONResponse(
            {"status": "error", "detail": "Missing 'ds' (dataspace path)"},
            status_code=400,
        )
    prefix = str(payload.get("prefix") or "dev").strip()
    uuids = payload.get("uuids")
    if isinstance(uuids, str):
        uuids = [u.strip() for u in uuids.split(",") if u.strip()]

    try:
        result = await smap_mod.generate_structuremaps(
            at, ds, prefix=prefix, uuids=uuids,
        )
    except HTTPStatusError as e:
        return http_error_response(e)
    except Exception as e:
        log.exception("structuremap manifest failed: %s", e)
        return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)

    # Strip _source metadata before wrapping in manifest
    smaps = result.get("structuremaps", [])
    clean_smaps = []
    for s in smaps:
        rec = {k: v for k, v in s.items() if not k.startswith("_")}
        clean_smaps.append(rec)

    manifest = smap_mod.wrap_as_manifest(clean_smaps, dataspace=ds)

    return JSONResponse({
        "status": "ok",
        "dataspace": ds,
        "depth_count": result.get("depth_count", 0),
        "time_count": result.get("time_count", 0),
        "skipped_count": result.get("skipped_count", 0),
        "structuremap_count": len(clean_smaps),
        "manifest": manifest,
    })


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
    try:
        obj_raw = await osdu.get_resource(at, enc, typ_s, uuid_s)
        obj = _normalize_resource_obj(obj_raw, uuid_s)
    except HTTPStatusError as exc:
        return http_error_response(exc)

    ctype = obj.get("$type") or obj.get("contentType") or ""
    if "Grid2dRepresentation" not in ctype and "Grid2dRepresentation" not in typ_s:
        return JSONResponse({"error": "Not a Grid2dRepresentation"}, status_code=400)

    grid_patch = obj.get("Grid2dPatch") or {}
    n_cols = int(grid_patch.get("FastestAxisCount", 0))
    n_rows = int(grid_patch.get("SlowestAxisCount", 0))

    # 2. Read the zvalues array - first discover the actual path via list_arrays
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
    #              (c) Fallback - scan all STLs in dataspace, match by entry-count.
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


# ── Depth-map PNG rendering for surface types ───────────────────────────────

from fastapi.responses import Response

# Surface types that support 2D depth-map rendering
_MAP_SURFACE_TYPES = {"triangulatedsetrepresentation"}


def _is_map_surface(typ: str) -> bool:
    """Return True if *typ* is a non-Grid2d surface that supports 2D map."""
    return any(k in (typ or "").lower() for k in _MAP_SURFACE_TYPES)


@router.get("/keys/object/map.png")
async def keys_object_map_png(
    request: Request,
    ds: str = Query(..., description="Dataspace path"),
    uuid: str = Query(..., description="UUID of the object"),
    typ: str = Query("", description="RESQML type (omit for Grid2d)"),
    cmap: str = Query("viridis_r", description="Matplotlib colormap"),
    dpi: int = Query(120, ge=72, le=300, description="Image DPI"),
    w: int = Query(10, ge=4, le=20, description="Figure width (inches)"),
    h: int = Query(8, ge=4, le=16, description="Figure height (inches)"),
):
    """
    Render a surface as a depth-map PNG.

    Supports Grid2dRepresentation (regular lattice) and
    TriangulatedSetRepresentation (irregular triangulated mesh).
    """
    at = _access_token(request)
    uuid_s = _sanitize_uuid(uuid)

    # ── Non-Grid2d surface types (TriangulatedSet etc.) ───────────────
    if typ and _is_map_surface(typ):
        typ_s = _sanitize_type(typ)
        try:
            _t0 = time.monotonic()
            geo = await resqml_viz.fetch_geometry_3d(at, ds, typ_s, uuid_s)
            _t1 = time.monotonic()
            log.info("map.png(triset): fetch %s uuid=%s took %.1fs",
                     typ_s, uuid_s, _t1 - _t0)
        except Exception as e:
            log.exception("map.png(triset): fetch_geometry_3d failed: %s", e)
            raise HTTPException(502, f"Failed to fetch geometry: {safe_error_detail(e)}")

        positions = geo.get("positions") or []
        indices = geo.get("indices") or []
        title = geo.get("title") or uuid_s
        if not positions:
            raise HTTPException(404, "No geometry data available for this surface")

        try:
            _t2 = time.monotonic()
            png_bytes = resqml_viz.render_triset_png(
                positions, indices,
                title=title, cmap=cmap, figsize=(w, h), dpi=dpi,
            )
            _t3 = time.monotonic()
            n_verts = len(positions) // 3
            log.info("map.png(triset): render %d verts took %.1fs (%d bytes)",
                     n_verts, _t3 - _t2, len(png_bytes))
        except Exception as e:
            log.exception("map.png(triset): render failed: %s", e)
            raise HTTPException(500, f"Render failed: {safe_error_detail(e)}")

        return Response(content=png_bytes, media_type="image/png")

    # ── Grid2d (original path) ────────────────────────────────────────
    try:
        _t0 = time.monotonic()
        surface = await resqml_viz.fetch_grid2d_surface(at, ds, uuid_s)
        _t1 = time.monotonic()
        log.info("map.png: fetch ds=%s uuid=%s took %.1fs", ds, uuid, _t1 - _t0)
    except Exception as e:
        log.exception("map.png: fetch_grid2d_surface failed for ds=%s uuid=%s: %s", ds, uuid, e)
        raise HTTPException(502, f"Failed to fetch surface from RDDMS: {safe_error_detail(e)}")

    grid = surface["grid"]
    title = (grid.get("Citation") or {}).get("Title") or uuid

    # Resolve horizon name from RepresentedInterpretation if available
    interp = grid.get("RepresentedInterpretation") or {}
    interp_title = interp.get("Title") or ""
    if interp_title and interp_title != title:
        title = f"{title} - {interp_title}"

    zvalues = surface["zvalues"]
    dims = surface["dims"]
    geometry = surface["geometry"]
    crs = surface["crs"]

    if not zvalues:
        raise HTTPException(404, "No z-values array found for this surface")
    if dims[0] == 0 or dims[1] == 0:
        raise HTTPException(400, "Grid has zero dimensions")

    # Determine depth unit from CRS
    unit = "m"
    if crs:
        unit = crs.get("VerticalUom") or crs.get("ProjectedUom") or "m"

    try:
        _t2 = time.monotonic()
        png_bytes = resqml_viz.render_grid2d_png(
            zvalues, dims, geometry, crs,
            title=title,
            cmap=cmap,
            figsize=(w, h),
            dpi=dpi,
            unit=unit,
        )
        _t3 = time.monotonic()
        log.info("map.png: render %dx%d took %.1fs (%d bytes)", dims[0], dims[1], _t3 - _t2, len(png_bytes))
    except Exception as e:
        log.exception("map.png: render failed for %dx%d grid: %s", dims[0], dims[1], e)
        raise HTTPException(500, f"Render failed ({dims[0]}x{dims[1]} grid): {safe_error_detail(e)}")

    return Response(content=png_bytes, media_type="image/png")


@router.get("/keys/object/map.json")
async def keys_object_map_json(
    request: Request,
    ds: str = Query(..., description="Dataspace path"),
    uuid: str = Query(..., description="UUID of the object"),
    typ: str = Query("", description="RESQML type (omit for Grid2d)"),
):
    """
    Return surface metadata (geometry, CRS, dims, stats) as JSON.

    Supports Grid2dRepresentation and TriangulatedSetRepresentation.
    """
    at = _access_token(request)
    uuid_s = _sanitize_uuid(uuid)

    # ── Non-Grid2d surface types ──────────────────────────────────────
    if typ and _is_map_surface(typ):
        typ_s = _sanitize_type(typ)
        try:
            geo = await resqml_viz.fetch_geometry_3d(at, ds, typ_s, uuid_s)
        except Exception as e:
            raise HTTPException(502, f"Failed to fetch geometry: {safe_error_detail(e)}")

        positions = geo.get("positions") or []
        indices = geo.get("indices") or []
        n_verts = len(positions) // 3
        n_tris = len(indices) // 3
        title = geo.get("title") or uuid_s
        zmin = geo.get("zmin", 0)
        zmax = geo.get("zmax", 1)

        stats = {}
        if n_verts > 0:
            stats = {
                "min": round(zmin, 2), "max": round(zmax, 2),
                "count": n_verts,
            }

        return JSONResponse({
            "title": title,
            "dims": [n_verts, n_tris],
            "geometry": None,
            "crs": None,
            "stats": stats,
            "kind": "triset",
        })

    # ── Grid2d (original path) ────────────────────────────────────────
    try:
        surface = await resqml_viz.fetch_grid2d_surface(at, ds, uuid_s)
    except Exception as e:
        raise HTTPException(502, f"Failed to fetch surface: {safe_error_detail(e)}")

    grid = surface["grid"]
    zvalues = surface["zvalues"]
    dims = surface["dims"]
    geo = surface["geometry"]
    crs = surface["crs"]

    # Stats
    z_arr = [v for v in zvalues if v is not None and abs(v) < 1e30]
    stats = {}
    if z_arr:
        stats = {
            "min": round(min(z_arr), 2),
            "max": round(max(z_arr), 2),
            "mean": round(sum(z_arr) / len(z_arr), 2),
            "count": len(z_arr),
            "nan_count": len(zvalues) - len(z_arr),
        }

    crs_info = None
    if crs:
        rot_obj = crs.get("ArealRotation") or {}
        wkt = ""
        for em in (crs.get("ExtraMetadata") or []):
            if isinstance(em, dict) and "Wkt" in (em.get("Name") or ""):
                wkt = em.get("Value", "")
                break
        crs_info = {
            "title": (crs.get("Citation") or {}).get("Title", ""),
            "projectedUom": crs.get("ProjectedUom", ""),
            "verticalUom": crs.get("VerticalUom", ""),
            "axisOrder": crs.get("ProjectedAxisOrder", ""),
            "zIncreasingDownward": crs.get("ZIncreasingDownward", True),
            "arealRotation_deg": float(rot_obj.get("_", 0) or rot_obj.get("Value", 0) or 0),
            "xOffset": float(crs.get("XOffset", 0) or 0),
            "yOffset": float(crs.get("YOffset", 0) or 0),
            "wkt": wkt[:200] if wkt else "",
        }

    title = (grid.get("Citation") or {}).get("Title", uuid)

    return JSONResponse({
        "title": title,
        "dims": dims,
        "geometry": {
            "origin": list(geo["origin"]),
            "u_vec": list(geo["u_vec"]),
            "v_vec": list(geo["v_vec"]),
            "u_space": geo["u_space"],
            "v_space": geo["v_space"],
        },
        "crs": crs_info,
        "stats": stats,
    })


# ── 3-D geometry endpoint for Three.js viewer ────────────────────────────────

# Types that support 3D viewing
_3D_TYPES = {
    "grid2drepresentation", "triangulatedsetrepresentation",
    "pointsetrepresentation", "wellboretrajectoryrepresentation",
    "wellboremarkerframerepresentation", "polylinesetrepresentation",
    "deviationsurveyrepresentation",
}

def _is_3d_type(typ: str) -> bool:
    """Check if a RESQML type supports 3D viewing."""
    t = (typ or "").lower()
    return any(k in t for k in _3D_TYPES)


@router.get("/keys/object/geometry3d.json",
            summary="3D geometry for Three.js viewer")
async def keys_object_geometry3d(
    request: Request,
    ds: str = Query(..., description="Dataspace path"),
    typ: str = Query(..., description="RESQML/EML type"),
    uuid: str = Query(..., description="UUID of the object"),
):
    """
    Return vertex/index/point arrays for client-side 3D rendering.

    Tries local PostgreSQL first (fast), falls back to remote RDDMS REST API.

    Supported types:
      - Grid2dRepresentation → triangulated surface mesh
      - TriangulatedSetRepresentation → triangle mesh
      - PointSetRepresentation → 3D point cloud
      - WellboreTrajectoryRepresentation → 3D polyline
      - WellboreMarkerFrameRepresentation → 3D markers with labels
    """
    at = _access_token(request)
    typ_s = _sanitize_type(typ)
    uuid_s = _sanitize_uuid(uuid)

    if not _is_3d_type(typ_s):
        raise HTTPException(400, f"Type {typ_s} is not supported for 3D viewing")

    _t0 = time.monotonic()

    try:
        result = await resqml_viz.fetch_geometry_3d(at, ds, typ_s, uuid_s)
    except ValueError as e:
        raise HTTPException(400, safe_error_detail(e))
    except Exception as e:
        log.exception("geometry3d: fetch failed for %s/%s: %s", typ_s, uuid_s, e)
        raise HTTPException(502, f"Failed to fetch 3D geometry: {safe_error_detail(e)}")

    _t1 = time.monotonic()
    n_verts = len(result.get("positions", [])) // 3
    n_idx = len(result.get("indices", [])) // 3
    log.info("geometry3d: %s uuid=%s kind=%s verts=%d tris=%d took %.1fs",
             typ_s, uuid_s, result.get("kind"), n_verts, n_idx, _t1 - _t0)

    return JSONResponse(result)


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

    if not typ_s:
        return JSONResponse(
            {"status": "error", "code": 400,
             "reason": "Missing type",
             "detail": "Object type is required. Select a specific type instead of (All types)."},
            status_code=400,
        )

    obj = None

    # ── Try PG first ──────────────────────────────────────────────────
    try:
        from .pg_backend import get_pool
        pool = await get_pool()
        if pool:
            pg_obj, _ = await resqml_viz.pg_get_object_and_arrays(
                pool, ds, typ_s, uuid_s,
            )
            if pg_obj is not None:
                obj = pg_obj
    except Exception as e:
        log.debug("graph.json: PG content fetch failed: %s", e)

    # ── REST fallback ─────────────────────────────────────────────────
    if obj is None:
        try:
            obj_raw = await osdu.get_resource(at, enc, typ_s, uuid_s)
            obj = _normalize_resource_obj(obj_raw, uuid_s)
        except HTTPStatusError as exc:
            if exc.response.status_code == 404:
                log.info("graph.json: primary object not found via REST, continuing with minimal info")
                obj = {}
                obj_raw = {}
            else:
                return http_error_response(exc)
    else:
        obj_raw = obj

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
        pg_graph_done = False
        # ── Try PG graph first ────────────────────────────────────────
        try:
            from .pg_backend import get_pool, pg_list_relations
            pool = await get_pool()
            if pool:
                pg_rels = await pg_list_relations(pool, ds, typ_s, uuid_s, "both")
                if pg_rels:
                    for rel in pg_rels:
                        item = {
                            "$type": rel.get("type_name", ""),
                            "contentType": rel.get("content_type", ""),
                            "UUID": rel.get("uuid", ""),
                            "Citation": {"Title": rel.get("name", "")},
                        }
                        if rel.get("direction") == "source":
                            sources.append(item)
                        else:
                            targets.append(item)
                    pg_graph_done = True
        except Exception as e:
            log.debug("graph: PG relations failed: %s", e)

        if not pg_graph_done:
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


# ══════════════════════════════════════════════════════════════════════════════
# 3D Viz – batch geometry endpoint (used by the 3D popup in keys.html)
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/keys/viz/batch.json",
             summary="Fetch 3D geometry for multiple objects")
async def viz_batch_geometry(
    request: Request,
    body: dict = Body(...),
):
    """
    Fetch geometry for multiple objects in a single request.

    Body: ``{ "ds": "...", "objects": [ {"typ": "...", "uuid": "..."}, ... ] }``
    Response: ``{ "results": [ {<geometry>} | {"error": "..."}, ... ] }``

    Each result matches the corresponding request entry by index.
    Max 50 objects per batch to keep response times reasonable.
    """
    at = _access_token(request)
    ds = body.get("ds", "")
    objects = body.get("objects", [])

    if not ds or not objects:
        raise HTTPException(400, "Missing 'ds' or 'objects' in request body")
    if len(objects) > 50:
        raise HTTPException(400, f"Max 50 objects per batch, got {len(objects)}")

    t0 = time.monotonic()

    async def _fetch_one(item: dict) -> dict:
        typ_s = _sanitize_type(item.get("typ", ""))
        uuid_s = _sanitize_uuid(item.get("uuid", ""))
        if not _is_3d_type(typ_s):
            return {"error": f"Type {typ_s} is not supported for 3D viewing"}
        try:
            return await resqml_viz.fetch_geometry_3d(at, ds, typ_s, uuid_s)
        except Exception as e:
            log.warning("viz batch: %s/%s failed: %s", typ_s, uuid_s, e)
            return {"error": str(e)}

    results = await asyncio.gather(*[_fetch_one(o) for o in objects])

    t1 = time.monotonic()
    ok = sum(1 for r in results if "error" not in r)
    log.info("viz batch: ds=%s objects=%d ok=%d took=%.1fs", ds, len(objects), ok, t1 - t0)

    return JSONResponse({"results": list(results)})
