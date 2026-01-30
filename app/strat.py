
from __future__ import annotations
import os
import urllib.parse
from typing import Any, Dict, List
import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from . import osdu

router = APIRouter()
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))

def _access_token(request: Request) -> str:
    at = getattr(request.state, "access_token", None)
    if not at:
        raise HTTPException(401, "Authentication failed")
    return at

async def _osdu_get_record(request: Request, record_id: str) -> dict:
    at = _access_token(request)
    base = f"https://{osdu.OSDU_BASE_URL}/api/storage/v2/records"
    url = f"{base}/{urllib.parse.quote(record_id, safe='')}"
    hdr = osdu.headers(at)
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(url, headers=hdr)
        if r.status_code == 200:
            return r.json() or {}
        if r.status_code == 404:
            return {}
        r.raise_for_status()
    return {}

def _safe(lst):
    return lst if isinstance(lst, list) else []

def _as_id(x: Any) -> str:
    """
    Normalize inputs that can be:
      - a string id, or
      - an object with 'id' (Storage record ref), or
      - an object with '$ref'/'recordId' (defensive)
    """
    if isinstance(x, str):
        return x
    if isinstance(x, dict):
        return x.get("id") or x.get("recordId") or x.get("$ref") or ""
    return ""

def _ids(val: Any) -> List[str]:
    """Return a list of string ids from a heterogeneous array or a string."""
    if isinstance(val, list):
        out = []
        for item in val:
            s = _as_id(item)
            if s:
                out.append(s)
        return out
    s = _as_id(val)
    return [s] if s else []

def _get_data(rec):
    return rec.get("data") or {}

def _label_from_ref_id(val: str) -> str:
    if not val:
        return ""
    parts = val.strip().split(":")
    if len(parts) >= 2 and parts[-1] == "":
        return parts[-2]
    return parts[-1] if parts else val

@router.get("/strat", response_class=HTMLResponse)
async def strat_page(request: Request):
    return templates.TemplateResponse("strat.html", {"request": request})

@router.get("/api/strat/search.json")
async def strat_search(request: Request,
                       q: str = Query("*"),
                       limit: int = Query(20, ge=1, le=200)):
    at = _access_token(request)
    search_url = f"https://{osdu.OSDU_BASE_URL}/api/search/v2/query"
    storage_url = f"https://{osdu.OSDU_BASE_URL}/api/storage/v2/records"
    hdr = osdu.headers(at)

    payload = {
        "kind": "osdu:wks:work-product-component--StratigraphicColumn:1.*.*",
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

        for rec in res.get("results") or []:
            rid = rec.get("id")
            if not rid:
                continue
            name = ""
            try:
                rf = await client.get(f"{storage_url}/{rid}", headers=hdr)
                if rf.status_code == 200:
                    full = rf.json() or {}
                    name = ((full.get("data") or {}).get("Name")) or ""
            except Exception:
                pass
            items.append({
                "id": rid,
                "name": name or rid,
                "kind": rec.get("kind") or "",
                "version": rec.get("version"),
            })
    return JSONResponse({"items": items, "total": total})


# --- add at the top of strat.py imports ---
import asyncio

# --- helpers: ID normalization unchanged from your version ---
def _ids(val: Any) -> List[str]:
    if isinstance(val, list):
        out = []
        for item in val:
            if isinstance(item, str):
                out.append(item)
            elif isinstance(item, dict):
                s = item.get("id") or item.get("recordId") or item.get("$ref") or ""
                if s: out.append(s)
        return out
    if isinstance(val, str):
        return [val]
    if isinstance(val, dict):
        s = val.get("id") or val.get("recordId") or val.get("$ref") or ""
        return [s] if s else []
    return []

# --- NEW: batch fetch via Storage query endpoint (20 IDs per call) ---
async def _storage_fetch_many(request: Request, ids: List[str]) -> Dict[str, dict]:
    """
    Fast path: POST /api/storage/v2/query/records:batch with up to 20 IDs
    Fallback: parallel GET /api/storage/v2/records/{id}
    Returns: {id: record_dict}
    """
    at = _access_token(request)
    base = f"https://{osdu.OSDU_BASE_URL}/api/storage/v2"
    hdr = osdu.headers(at)

    # normalize & dedupe
    uniq = [x for x in dict.fromkeys([i.strip() for i in ids if i and i.strip()])]
    if not uniq:
        return {}

    results: Dict[str, dict] = {}

    async def post_batch(client: httpx.AsyncClient, chunk: List[str]) -> None:
        url = f"{base}/query/records:batch"
        payload = {"records": chunk}
        r = await client.post(url, headers=hdr, json=payload)
        if r.status_code == 404:
            # Some tenants don’t expose :batch ⇒ signal caller to fallback
            raise FileNotFoundError("records:batch not available")
        r.raise_for_status()
        data = r.json() or {}
        # Many tenants return {"records":[{ "id": "...", "record": {...} }]} or just a list of records
        recs = data.get("records")
        if isinstance(recs, list):
            for item in recs:
                if isinstance(item, dict):
                    rid = item.get("id") or (item.get("record") or {}).get("id")
                    body = item.get("record") or item
                    if rid and isinstance(body, dict):
                        results[rid] = body
        else:
            # Try a forgiving path: assume the response is a list of records
            if isinstance(data, list):
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
                results[rid] = {}
            else:
                r.raise_for_status()

    # Single HTTP/2 client for all I/O
    async with httpx.AsyncClient(timeout=30, http2=True) as client:
        # Try batch first (20 per chunk)
        chunks = [uniq[i:i+20] for i in range(0, len(uniq), 20)]
        try:
            await asyncio.gather(*(post_batch(client, c) for c in chunks))
            return results
        except FileNotFoundError:
            # Fallback to parallel GETs (bounded)
            sem = asyncio.Semaphore(12)
            await asyncio.gather(*(get_one(client, rid, sem) for rid in uniq))
            return results


@router.get("/api/strat/column.json")
async def get_strat_column(request: Request, id: str, enrich: bool = True):
    """
    Build full stratigraphic column model:
      - column (WPC StratigraphicColumn)
      - ranks: ordered list; each rank contains either chrono items or unit items
      - for unit items, if data.ChronoStratigraphyID exists, resolve and attach the chrono record
    """
    col = await _osdu_get_record(request, id)
    if not col or not isinstance(col, dict):
        raise HTTPException(404, detail="Column not found")
    if not (col.get("kind", "").startswith("osdu:wks:work-product-component--StratigraphicColumn:")):
        raise HTTPException(400, detail="Record is not a StratigraphicColumn")

    dcol = _get_data(col)
    rank_ids = _ids(dcol.get("StratigraphicColumnRankInterpretationSet"))

    # 1) fetch ranks
    ranks_by_id = await _storage_fetch_many(request, rank_ids)

    # 2) discover all unit ids and chrono ids (from both rank-level sets and unit-level links)
    unit_ids_all: List[str] = []
    chrono_ids_all: List[str] = []

    for rid in rank_ids:
        rk = ranks_by_id.get(rid) or {}
        drk = _get_data(rk)
        # units under this rank?
        unit_ids_all.extend(_ids(drk.get("StratigraphicUnitInterpretationSet")))
        # chrono refs directly under the rank?
        chrono_ids_all.extend(_ids(drk.get("ChronoStratigraphySet") or drk.get("ChronostratigraphySet")))

    # 3) fetch units, then scan for ChronoStratigraphyID links on each unit
    units_by_id = await _storage_fetch_many(request, unit_ids_all) if unit_ids_all else {}
    for u in units_by_id.values():
        ud = _get_data(u)
        # follow the unit-level chrono pointer if present (tenant-specific property name)
        cid = ud.get("ChronoStratigraphyID") or ud.get("ChronostratigraphyID")
        if cid:
            chrono_ids_all.append(cid)

    # 4) fetch all chrono records (deduped inside _storage_fetch_many)
    chron_by_id = await _storage_fetch_many(request, chrono_ids_all) if chrono_ids_all else {}

    # 5) optional: get scheme once from any chrono record
    scheme = None
    if enrich and chron_by_id:
        for c in chron_by_id.values():
            d = _get_data(c)
            s_id = d.get("ChronoStratigraphicSchemeID") or d.get("ChronostratigraphicSchemeID")
            if s_id:
                maybe = await _osdu_get_record(request, s_id)
                if maybe:
                    scheme = maybe
                break

    # 6) assemble ranks in original order
    ranks_model: List[Dict[str, Any]] = []
    for rid in rank_ids:
        rk = ranks_by_id.get(rid)
        if not rk:
            continue
        drk = _get_data(rk)
        rank_name = (
            drk.get("Name")
            or _label_from_ref_id(drk.get("StratigraphicColumnRankUnitType") or "")
            or "Unspecified"
        )

        units_model: List[Dict[str, Any]] = []

        # A) rank-level chrono items (no unit objects)
        for cid in _ids(drk.get("ChronoStratigraphySet") or drk.get("ChronostratigraphySet")):
            crec = chron_by_id.get(cid)
            if crec:
                units_model.append({"unit": None, "chrono": crec})

        # B) unit interpretations (attach chrono if the unit points to one)
        for uid in _ids(drk.get("StratigraphicUnitInterpretationSet")):
            urec = units_by_id.get(uid)
            if urec:
                ud = _get_data(urec)
                cid = ud.get("ChronoStratigraphyID") or ud.get("ChronostratigraphyID")
                cobj = chron_by_id.get(cid) if cid else None
                units_model.append({"unit": urec, "chrono": cobj})

        ranks_model.append({"rankName": rank_name, "rank": rk, "units": units_model})

    return JSONResponse({"column": col, "scheme": scheme, "ranks": ranks_model})
