
from __future__ import annotations
import asyncio
import logging
import os
import urllib.parse
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from . import osdu
from .schemahandler import extract_osdu_links

log = logging.getLogger("explorer")

router = APIRouter()
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))

# ──────────────────────────────────────────────────────────────────────────────
# Prepopulated OSDU types for the search dropdown
# ──────────────────────────────────────────────────────────────────────────────
EXPLORER_TYPES = [
    {"label": "Reservoir",                "kind": "osdu:wks:master-data--Reservoir:*"},
    {"label": "Reservoir Segment",        "kind": "osdu:wks:master-data--ReservoirSegment:*"},
    {"label": "Work Product",             "kind": "osdu:wks:work-product:*"},
    {"label": "Estimated Volumes (REV)",  "kind": "osdu:wks:work-product-component--ReservoirEstimatedVolumes:*"},
    {"label": "Column-Based Table",       "kind": "osdu:wks:work-product-component--ColumnBasedTable:*"},
    {"label": "Risk",                     "kind": "osdu:wks:master-data--Risk:*"},
    {"label": "Business Decision",        "kind": "osdu:wks:master-data--BusinessDecision:*"},
    {"label": "Stratigraphic Column",     "kind": "osdu:wks:work-product-component--StratigraphicColumn:*"},
]


# ──────────────────────────────────────────────────────────────────────────────
# Utilities
# ──────────────────────────────────────────────────────────────────────────────

def _access_token(request: Request) -> str:
    at = getattr(request.state, "access_token", None)
    if not at:
        raise HTTPException(401, "Authentication failed")
    return at


def _short_kind(kind: str) -> str:
    """Extract short type name from OSDU kind string.

    "osdu:wks:master-data--Reservoir:2.0.0" → "Reservoir"
    "osdu:wks:work-product:1.0.0"           → "work-product"
    """
    if not kind:
        return ""
    parts = kind.split(":")
    if len(parts) >= 3:
        type_part = parts[2]
        if "--" in type_part:
            return type_part.split("--", 1)[1]
        return type_part
    return kind


def _normalize_table_data(data_block: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Normalize ColumnBasedTable data from Volumes or Table property."""
    for key in ("Volumes", "Table"):
        vol = (data_block or {}).get(key, {}) or {}
        if not vol:
            continue
        key_cols = vol.get("KeyColumns", []) or []
        value_cols = vol.get("Columns", []) or []
        raw_vals = vol.get("ColumnValues", {}) or {}

        # Normalize ColumnValues
        if isinstance(raw_vals, dict):
            col_values = raw_vals
        elif isinstance(raw_vals, list):
            if raw_vals and all(isinstance(x, dict) for x in raw_vals):
                out: Dict[str, list] = {}
                for x in raw_vals:
                    name = x.get("ColumnName") or x.get("name")
                    vals = (
                        x.get("Values") or x.get("values")
                        or x.get("Data") or x.get("data") or []
                    )
                    if name:
                        out[name] = vals if isinstance(vals, list) else [vals]
                col_values = out
            else:
                col_values = raw_vals
        else:
            col_values = raw_vals

        if not col_values:
            continue

        # Build ordered header list
        key_names = [k.get("ColumnName", "") for k in key_cols if k.get("ColumnName")]
        value_names: List[str] = []
        for c in value_cols:
            cn = c.get("ColumnName", "")
            if cn:
                value_names.append(cn)
        # Fallback: any column not in key_names is a value column
        if not value_names:
            for cname in col_values:
                if cname not in key_names:
                    value_names.append(cname)

        headers = key_names + value_names
        sample = next(((col_values.get(h) or []) for h in headers if h), [])
        nrows = len(sample)

        if headers and nrows > 0:
            return {
                "source": key,
                "KeyColumns": key_cols,
                "Columns": value_cols,
                "ColumnValues": col_values,
                "headers": headers,
                "key_names": key_names,
                "value_names": value_names,
                "nrows": nrows,
            }
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Batch record fetch (reusable)
# ──────────────────────────────────────────────────────────────────────────────

async def _storage_fetch_many(request: Request, ids: List[str]) -> Dict[str, dict]:
    """
    Batch-fetch OSDU records.
    Fast path: POST /api/storage/v2/query/records:batch (20 IDs per call).
    Fallback:  parallel GET /api/storage/v2/records/{id} (bounded concurrency).
    """
    at = _access_token(request)
    base = f"https://{osdu.OSDU_BASE_URL}/api/storage/v2"
    hdr = osdu.headers(at)

    uniq = [x for x in dict.fromkeys([i.strip() for i in ids if i and i.strip()])]
    if not uniq:
        return {}

    results: Dict[str, dict] = {}

    async def post_batch(client: httpx.AsyncClient, chunk: List[str]) -> None:
        url = f"{base}/query/records:batch"
        payload = {"records": chunk}
        r = await client.post(url, headers=hdr, json=payload)
        if r.status_code == 404:
            raise FileNotFoundError("records:batch not available")
        r.raise_for_status()
        data = r.json() or {}
        recs = data.get("records")
        if isinstance(recs, list):
            for item in recs:
                if isinstance(item, dict):
                    rid = item.get("id") or (item.get("record") or {}).get("id")
                    body = item.get("record") or item
                    if rid and isinstance(body, dict):
                        results[rid] = body
        elif isinstance(data, list):
            for body in data:
                if isinstance(body, dict) and body.get("id"):
                    results[body["id"]] = body

    async def get_one(client: httpx.AsyncClient, rid: str, sem: asyncio.Semaphore) -> None:
        url = f"{base}/records/{urllib.parse.quote(rid, safe='')}"
        async with sem:
            r = await client.get(url, headers=hdr)
            if r.status_code == 200:
                results[rid] = r.json() or {}
            elif r.status_code == 404:
                alt = rid.rstrip(":") if rid.endswith(":") else (rid + ":")
                url2 = f"{base}/records/{urllib.parse.quote(alt, safe='')}"
                r2 = await client.get(url2, headers=hdr)
                if r2.status_code == 200:
                    body = r2.json() or {}
                    results[rid] = body
                    results[alt] = body
                else:
                    results[rid] = {}
            else:
                r.raise_for_status()

    def _alias_colon_variants() -> None:
        for key in list(results.keys()):
            body = results[key]
            if not body:
                continue
            stripped = key.rstrip(":")
            if stripped != key:
                results.setdefault(stripped, body)
            else:
                results.setdefault(key + ":", body)

    try:
        _client_kw: dict = {"timeout": 30, "http2": True}
        httpx.AsyncClient(**_client_kw)
    except Exception:
        _client_kw = {"timeout": 30}

    async with httpx.AsyncClient(**_client_kw) as client:
        chunks = [uniq[i:i + 20] for i in range(0, len(uniq), 20)]
        use_batch = True
        try:
            await asyncio.gather(*(post_batch(client, c) for c in chunks))
            _alias_colon_variants()
        except FileNotFoundError:
            use_batch = False

        still_missing = [rid for rid in uniq
                         if rid not in results or not results[rid]]
        if still_missing:
            alts: List[str] = []
            for rid in still_missing:
                alt = rid.rstrip(":") if rid.endswith(":") else (rid + ":")
                if alt not in results or not results[alt]:
                    alts.append(alt)
            to_retry = list(dict.fromkeys(still_missing + alts))

            if use_batch and to_retry:
                retry_chunks = [to_retry[i:i + 20] for i in range(0, len(to_retry), 20)]
                try:
                    await asyncio.gather(*(post_batch(client, c) for c in retry_chunks))
                    _alias_colon_variants()
                except FileNotFoundError:
                    use_batch = False

            final_missing = [rid for rid in uniq
                             if rid not in results or not results[rid]]
            if final_missing:
                sem = asyncio.Semaphore(12)
                await asyncio.gather(*(get_one(client, rid, sem) for rid in final_missing))
                _alias_colon_variants()

    return results


# ──────────────────────────────────────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/strat", response_class=HTMLResponse)
async def explorer_page(request: Request):
    return templates.TemplateResponse("strat.html", {
        "request": request,
        "types": EXPLORER_TYPES,
    })


@router.get("/api/strat/search.json")
async def explorer_search(
    request: Request,
    kind: str = Query("osdu:wks:master-data--Reservoir:*"),
    q: str = Query("*"),
    limit: int = Query(50, ge=1, le=500),
):
    """Generic OSDU search by kind + query string."""
    at = _access_token(request)
    search_url = f"https://{osdu.OSDU_BASE_URL}/api/search/v2/query"
    storage_url = f"https://{osdu.OSDU_BASE_URL}/api/storage/v2/records"
    hdr = osdu.headers(at)

    payload = {
        "kind": kind,
        "query": q or "*",
        "limit": int(limit),
        "returnedFields": ["id", "kind", "version"],
        "trackTotalCount": True,
    }

    items: List[Dict[str, Any]] = []
    total = 0
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(search_url, headers=hdr, json=payload)
        r.raise_for_status()
        res = r.json() or {}
        total = res.get("totalCount") or len(res.get("results") or [])

        for rec in (res.get("results") or []):
            rid = rec.get("id")
            if not rid:
                continue
            name = ""
            try:
                rf = await client.get(f"{storage_url}/{rid}", headers=hdr)
                if rf.status_code == 200:
                    full = rf.json() or {}
                    d = full.get("data") or {}
                    name = d.get("Name") or d.get("ProjectName") or ""
            except Exception:
                pass
            items.append({
                "id": rid,
                "name": name or rid,
                "kind": rec.get("kind") or "",
                "short_kind": _short_kind(rec.get("kind") or ""),
                "version": rec.get("version"),
            })

    return JSONResponse({"items": items, "total": total})


@router.get("/api/strat/record.json")
async def explorer_record(request: Request, id: str = Query(...)):
    """Fetch and enrich a single OSDU record for the explorer view."""
    at = _access_token(request)
    storage_url = f"https://{osdu.OSDU_BASE_URL}/api/storage/v2/records"
    hdr = osdu.headers(at)

    rid = id.strip()
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(
            f"{storage_url}/{urllib.parse.quote(rid, safe='')}",
            headers=hdr,
        )
        if r.status_code == 404:
            raise HTTPException(404, "Record not found")
        r.raise_for_status()
        full = r.json() or {}

    data_block = full.get("data", {}) or {}
    name = data_block.get("Name") or data_block.get("ProjectName") or rid

    # Ancestry
    ancestry = data_block.get("ancestry", {}) or {}
    ancestry_parents = ancestry.get("parents", []) or []
    ancestry_children = ancestry.get("children", []) or []

    # Links extracted from data block
    links = extract_osdu_links(data_block) or []

    # Collect all referenced IDs for label hydration
    all_ids: set = set()
    for lnk in links:
        lid = lnk.get("id")
        if lid:
            all_ids.add(lid)
    for p in ancestry_parents:
        if isinstance(p, str):
            all_ids.add(p)
    for c in ancestry_children:
        if isinstance(c, str):
            all_ids.add(c)

    # Batch-fetch referenced records for names/kinds
    linked_labels: Dict[str, Dict[str, Any]] = {}
    if all_ids:
        fetched = await _storage_fetch_many(request, list(all_ids))
        for lid, rec in fetched.items():
            if rec and isinstance(rec, dict):
                rec_data = rec.get("data") or {}
                nm = rec_data.get("Name") or rec_data.get("ProjectName") or ""
                linked_labels[lid] = {
                    "name": nm or lid,
                    "kind": rec.get("kind") or "",
                    "short_kind": _short_kind(rec.get("kind") or ""),
                }

    # Table data (Volumes or Table property)
    table_data = _normalize_table_data(data_block)

    return JSONResponse({
        "id": full.get("id"),
        "kind": full.get("kind"),
        "short_kind": _short_kind(full.get("kind") or ""),
        "version": full.get("version"),
        "name": name,
        "data": data_block,
        "ancestry_parents": ancestry_parents,
        "ancestry_children": ancestry_children,
        "links": links,
        "linked_labels": linked_labels,
        "table_data": table_data,
    })
