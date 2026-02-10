
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
async def strat_search(
    request: Request,
    q: str = Query("*"),
    limit: int = Query(20, ge=1, le=200),
):
    at = _access_token(request)
    search_url = f"https://{osdu.OSDU_BASE_URL}/api/search/v2/query"
    storage_url = f"https://{osdu.OSDU_BASE_URL}/api/storage/v2/records"
    hdr = osdu.headers(at)

    payload = {
        "kind": "osdu:wks:work-product-component--StratigraphicColumn:*",
        "query": q or "*",
        "limit": int(limit),
        "returnedFields": ["id", "kind", "version", "data.Name"],
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
            # prefer the projected name if present
            name = ((rec.get("data") or {}).get("Name")) or ""
            if not name:
                try:
                    rf = await client.get(f"{storage_url}/{rid}", headers=hdr)
                    if rf.status_code == 200:
                        full = rf.json() or {}
                        name = (full.get("data") or {}).get("Name") or ""
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

async def _storage_fetch_many(request: Request, ids: List[str]) -> Dict[str, dict]:
    at = _access_token(request)
    base = f"https://{osdu.OSDU_BASE_URL}/api/storage/v2"
    hdr = osdu.headers(at)

    # NEW: normalize heterogeneous inputs (str | dict) -> str ids
    norm_ids: List[str] = []
    for i in ids or []:
        s = _as_id(i)  # handles str, {"id":...}, {"recordId":...}, {"$ref":...}
        if s:
            s = s.strip()
            if s:
                norm_ids.append(s)

    # dedupe while preserving order
    uniq = [x for x in dict.fromkeys(norm_ids)]
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
        else:
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

    async with httpx.AsyncClient(timeout=30, http2=True) as client:
        chunks = [uniq[i:i+20] for i in range(0, len(uniq), 20)]
        try:
            await asyncio.gather(*(post_batch(client, c) for c in chunks))
            return results
        except FileNotFoundError:
            sem = asyncio.Semaphore(12)
            await asyncio.gather(*(get_one(client, rid, sem) for rid in uniq))
            return results
        

@router.get("/api/strat/column.json")
async def get_strat_column(
    request: Request,
    id: str = Query(..., description="StratigraphicColumn record id"),
    enrich: bool = Query(True, description="Fetch/attach full unit/chrono records"),
) -> JSONResponse:
    """
    Load a StratigraphicColumn (WPC) and return a model for a rank-by-age matrix:

      {
        "column": {...},  # the column WPC record
        "ranks": [
          {
            "rankName": "System" | "Series" | "Group" | "Formation" | ...,
            "isChrono": true|false,                # true if this rank lists Chronostratigraphy refs
            "rank": {...},                         # original rank record (optional use)
            "units": [                             # ordered (older → younger), non-overlapping per rank
              { "unit": {... or {}}, "chrono": {... or {} } },
              ...
            ]
          },
          ...
        ]
      }

    Notes:
      - A StratigraphicColumn contains an ordered list of StratigraphicColumnRankInterpretation.           (Worked Example)  [1](https://www.geeksforgeeks.org/python/fastapi-pydantic-2/)
      - Each RankInterpretation collects an ordered list of StratigraphicUnitInterpretation with the
        intention to create a column of non-overlapping intervals (base of one is top of next).            [1](https://www.geeksforgeeks.org/python/fastapi-pydantic-2/)
      - Chronostratigraphic ranks (Systems/Series) provide the time framework; we mark them as isChrono
        when rank lists ChronoStratigraphy references.                                                     (Authoring schema) [2](https://stackoverflow.com/questions/78049428/why-when-i-include-a-llama-index-module-do-i-get-pydantic-validation-errors-with)
    """
    # 1) Fetch the StratigraphicColumn WPC
    col = await _osdu_get_record(request, id)
    if not col or not isinstance(col, dict):
        raise HTTPException(404, detail="Column not found")

    kind = col.get("kind", "")
    if not kind.startswith("osdu:wks:work-product-component--StratigraphicColumn:"):
        raise HTTPException(400, detail="Record is not a StratigraphicColumn")

    dcol = _get_data(col)

    # 2) Read ordered rank IDs (use canonical key; tolerate alternates if present)
    rank_ids = _ids(
        dcol.get("StratigraphicColumnRankInterpretationSet")
        or dcol.get("RankInterpretationSet")
        or []
    )
    if not rank_ids:
        # Return minimal structure; UI will handle empty ranks
        return JSONResponse({"column": col, "ranks": []})

    # 3) Fetch all ranks in one go
    ranks_by_id = await _storage_fetch_many(request, rank_ids)

    # 4) Collect unit IDs and chrono IDs referenced by ranks (both rank-level chrono sets and unit-level pointers)
    unit_ids_all: List[str] = []
    chrono_ids_all: List[str] = []

    for rid in rank_ids:
        rk = ranks_by_id.get(rid) or {}
        drk = _get_data(rk)

        # Rank-level chrono references (Systems/Series)
        chrono_ids_all.extend(_ids(drk.get("ChronoStratigraphySet") or drk.get("ChronostratigraphySet")))

        # Rank-level unit interpretations (Groups/Formations or user-defined)
        unit_ids_all.extend(_ids(drk.get("StratigraphicUnitInterpretationSet")))

    # 5) Fetch units, then follow each unit’s chrono pointer (ChronoStratigraphyID) if present
    units_by_id = await _storage_fetch_many(request, unit_ids_all) if unit_ids_all else {}
    for u in units_by_id.values():
        ud = _get_data(u)
        cid = ud.get("ChronoStratigraphyID") or ud.get("ChronostratigraphyID")
        if cid:
            chrono_ids_all.append(cid)

    # 6) Fetch all chrono records (deduped by the batched helper)
    chron_by_id = await _storage_fetch_many(request, chrono_ids_all) if chrono_ids_all else {}

    # 7) Assemble ranks in the original order with:
    #      - rankName: from data.Name or the StratigraphicColumnRankUnitType label (System/Series/Group/Formation/…)
    #      - isChrono: True if rank lists chrono refs and has no unit interpretations (as per OSDU usage)
    #      - units:    ordered older→younger; rank-level Chrono entries first, then unit interpretations
    ranks_model: List[Dict[str, Any]] = []

    def _age_key(u: Dict[str, Any]):
        """
        Sort key: older (larger Ma) first by 'top'; ties by 'base'.
        Prefer chrono ages (AgeBegin/AgeEnd or TopMa/BaseMa) then litho fallbacks (OlderPossibleAge/YoungerPossibleAge).
        """
        cd = (u.get("chrono") or {}).get("data") or {}
        ud = (u.get("unit")   or {}).get("data") or {}
        top = (
            cd.get("AgeBegin") or cd.get("TopMa") or cd.get("AgeBeginMa")
            or ud.get("OlderPossibleAge") or ud.get("TopMa")
        )
        base = (
            cd.get("AgeEnd") or cd.get("BaseMa") or cd.get("AgeEndMa")
            or ud.get("YoungerPossibleAge") or ud.get("BaseMa")
        )
        try:
            return (-float(top), float(base))
        except Exception:
            return (float("inf"), float("inf"))

    for rid in rank_ids:
        rk = ranks_by_id.get(rid)
        if not rk:
            continue
        drk = _get_data(rk)

        # Rank name: prefer explicit Name; otherwise derive from reference value StratigraphicColumnRankUnitType
        rank_name = (
            drk.get("Name")
            or _label_from_ref_id(drk.get("StratigraphicColumnRankUnitType") or "")
            or "Unspecified"
        )

        # Chrono-vs-Unit identification at rank level
        chrono_ids = _ids(drk.get("ChronoStratigraphySet") or drk.get("ChronostratigraphySet"))
        unit_ids   = _ids(drk.get("StratigraphicUnitInterpretationSet"))
        is_chrono_rank = bool(chrono_ids) and not bool(unit_ids)

        # Units bucket
        units_model: List[Dict[str, Any]] = []

        # A) Rank-level chrono items (Systems/Series): carry ages & colour from reference data
        for cid in chrono_ids:
            crec = chron_by_id.get(cid)
            if crec:
                units_model.append({"unit": {}, "chrono": crec})

        # B) Rank-level unit interpretations: attach chrono if the unit points to one (ChronoStratigraphyID)
        for uid in unit_ids:
            urec = units_by_id.get(uid)
            if not urec:
                continue
            ud = _get_data(urec)
            cid = ud.get("ChronoStratigraphyID") or ud.get("ChronostratigraphyID")
            cobj = chron_by_id.get(cid) if cid else {}
            units_model.append({"unit": urec, "chrono": cobj})

        # C) Order units older→younger for non-overlap per rank (as intended by the OSDU model)
        units_model.sort(key=_age_key)

        ranks_model.append({
            "rankName": rank_name,
            "isChrono": is_chrono_rank,
            "rank": rk,
            "units": units_model
        })

    # 8) Return column model
    return JSONResponse({
        "column": col,
        "ranks": ranks_model
    })