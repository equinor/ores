
from __future__ import annotations
import asyncio
import json
import logging
import os
import sys
import urllib.parse
import uuid as _uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import httpx
from fastapi import APIRouter, HTTPException, Query, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from . import osdu
from . import auth as _auth

log = logging.getLogger("rddms-admin.strat")

# SMDA API key (Ocp-Apim-Subscription-Key) - used when PKCE login is unavailable
SMDA_API_KEY: str = os.getenv("SMDA_API_KEY", "")

# Import the stratcolumnhandler from demo/strat/
_handler_dir = os.path.join(os.path.dirname(__file__), "..", "demo", "strat")
if _handler_dir not in sys.path:
    sys.path.insert(0, os.path.abspath(_handler_dir))
try:
    from stratcolumnhandler import StratColumn as _StratColumn
except ImportError:
    _StratColumn = None

router = APIRouter()
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))

def _access_token(request: Request) -> str:
    from .common import access_token as _at
    return _at(request)

def _sanitize(r) -> str:
    from .common import sanitize_upstream_error
    return sanitize_upstream_error(r)

def _safe_detail(e: Exception) -> str:
    from .common import safe_error_detail
    return safe_error_detail(e)

async def _osdu_get_record(request: Request, record_id: str) -> dict:
    at = _access_token(request)
    base = f"https://{osdu.OSDU_BASE_URL}/api/storage/v2/records"
    url = f"{base}/{urllib.parse.quote(record_id, safe='')}"
    hdr = osdu.headers(at)
    async with osdu.http_client(timeout=30) as client:
        r = await client.get(url, headers=hdr)
        log.debug("Storage GET %s → %d", record_id, r.status_code)
        if r.status_code == 200:
            return r.json() or {}
        if r.status_code == 404:
            log.info("Storage GET %s → 404 (not found)", record_id)
            return {}
        log.warning("Storage GET %s → %d: %s", record_id, r.status_code, r.text[:200])
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
    Returns the ID as-is (no trailing-colon stripping) because some OSDU records
    (e.g. ICS2017 chrono) store the trailing ':' as part of their canonical ID.
    """
    if isinstance(x, str):
        return x.strip()
    if isinstance(x, dict):
        raw = x.get("id") or x.get("recordId") or x.get("$ref") or ""
        return raw.strip()
    return ""



def _get_data(rec):
    return rec.get("data") or {}

def _extract_ages(unit_rec: dict, chrono_rec: dict):
    """Return (topMa, baseMa) as floats, or (None, None)."""
    cd = _get_data(chrono_rec) if chrono_rec else {}
    ud = _get_data(unit_rec) if unit_rec else {}

    # Use `is not None` checks - 0.0 is a valid age (present day) but falsy
    def _first(*vals):
        for v in vals:
            if v is not None:
                return v
        return None

    top = _first(
        cd.get("AgeBegin"), cd.get("TopMa"), cd.get("AgeBeginMa"),
        ud.get("OlderPossibleAge"), ud.get("TopMa"),
        (ud.get("TimeRange") or {}).get("TopAgeMa"),
        (ud.get("VendorMetadata") or {}).get("Raw", {}).get("TopAgeMa"),
        (ud.get("VendorMetadata") or {}).get("Raw", {}).get("top_age"),
    )
    base = _first(
        cd.get("AgeEnd"), cd.get("BaseMa"), cd.get("AgeEndMa"),
        ud.get("YoungerPossibleAge"), ud.get("BaseMa"),
        (ud.get("TimeRange") or {}).get("BaseAgeMa"),
        (ud.get("VendorMetadata") or {}).get("Raw", {}).get("BaseAgeMa"),
        (ud.get("VendorMetadata") or {}).get("Raw", {}).get("base_age"),
    )
    try:
        return (float(top), float(base))
    except (TypeError, ValueError):
        return (None, None)

def _flat_unit_fields(unit_rec: dict, chrono_rec: dict,
                      horizons_by_id: Optional[Dict[str, dict]] = None) -> dict:
    """Extract flat convenience fields from a unit + chrono pair,
    including horizon boundary references when available."""
    ud = _get_data(unit_rec) if unit_rec else {}
    cd = _get_data(chrono_rec) if chrono_rec else {}
    top, base = _extract_ages(unit_rec, chrono_rec)
    name = ud.get("Name") or cd.get("Name") or ""
    # Colour: chrono first, then unit Rendering.ColorHtml, then VendorMetadata.Raw
    color = (
        cd.get("Colour") or cd.get("Color")
        or (ud.get("Rendering") or {}).get("ColorHtml")
        or (ud.get("VendorMetadata") or {}).get("Raw", {}).get("ColorHtml")
        or (ud.get("VendorMetadata") or {}).get("Raw", {}).get("color_html")
        or None
    )
    code = cd.get("Code") or ""

    # Normalize ages: olderMa = bigger number, youngerMa = smaller number.
    # SMDA stores top_age=younger (<) and base_age=older (>), while ICS chrono
    # uses topMa=older (>) and baseMa=younger (<).  Always expose both the raw
    # values (for display) and the normalized ones (for containment / sorting).
    older_ma = None
    younger_ma = None
    if top is not None and base is not None:
        older_ma = max(top, base)
        younger_ma = min(top, base)
    elif top is not None:
        older_ma = younger_ma = top
    elif base is not None:
        older_ma = younger_ma = base

    result: Dict[str, Any] = {
        "name": name, "topMa": top, "baseMa": base,
        "olderMa": older_ma, "youngerMa": younger_ma,
        "color": color, "code": code,
    }

    # ParentName - used by litho columns to establish hierarchy.
    # Check structured field first, then VendorMetadata fallbacks (SMDA origin).
    parent_name = (
        ud.get("ParentName")
        or ((ud.get("Relationships") or {}).get("Parent") or {}).get("Name")
        or (ud.get("VendorMetadata") or {}).get("Raw", {}).get("ParentName")
        or (ud.get("VendorMetadata") or {}).get("Raw", {}).get("strat_unit_parent")
        or ""
    )
    if isinstance(parent_name, str):
        parent_name = parent_name.strip()
    if parent_name and str(parent_name).lower() not in ("", "null", "none"):
        result["parentName"] = str(parent_name)

    # Attach horizon boundary info if the unit references HorizonInterpretation records
    hmap = horizons_by_id or {}
    htop_id = _as_id(ud.get("ColumnStratigraphicHorizonTopID") or "")
    hbase_id = _as_id(ud.get("ColumnStratigraphicHorizonBaseID") or "")
    if htop_id and htop_id in hmap:
        hd = _get_data(hmap[htop_id])
        result["horizonTop"] = {
            "id": htop_id, "name": hd.get("Name", ""),
            "ageMa": hd.get("MeanPossibleAge"),
            "conformableBelow": hd.get("isConformableBelow"),
        }
    if hbase_id and hbase_id in hmap:
        hd = _get_data(hmap[hbase_id])
        result["horizonBase"] = {
            "id": hbase_id, "name": hd.get("Name", ""),
            "ageMa": hd.get("MeanPossibleAge"),
            "conformableAbove": hd.get("isConformableAbove"),
        }
    return result

def _label_from_ref_id(val: str) -> str:
    if not val:
        return ""
    parts = val.strip().split(":")
    if len(parts) >= 2 and parts[-1] == "":
        return parts[-2]
    return parts[-1] if parts else val


def _fmt_ma(v) -> str:
    """Format an age in Ma for display in synthetic unit labels."""
    if v is None:
        return "?"
    f = float(v)
    if f == int(f):
        return str(int(f))
    return f"{f:.2f}".rstrip("0").rstrip(".")

@router.get("/strat", response_class=HTMLResponse)
async def strat_page(request: Request):
    return templates.TemplateResponse(request, "strat.html", {
        "partition": osdu.DATA_PARTITION_ID or "data",
    })


# ── Helpers: discover un-indexed StratigraphicColumn via child Rank records ──

_RANK_PREFIX = "work-product-component--StratigraphicColumnRankInterpretation:"
_COL_TYPE = "work-product-component--StratigraphicColumn:"
_RANK_SEPS = ("-Chrono-", "-Litho-", "-Bio-", "-Magneto-")


def _derive_column_ids_from_ranks(rank_ids: List[str]) -> List[str]:
    """Derive candidate parent StratigraphicColumn IDs from Rank record IDs.

    Rank IDs follow the pattern:
      <partition>:wpc--..RankInterpretation:<ColumnName>-<RolePrefix>-<RankName>:
    We split on the first role separator to recover the column name portion.
    If no separator matches, the full suffix is treated as a column name
    (covers standalone-rank patterns like "Global-ICS-Column").
    """
    col_ids: dict[str, None] = {}  # ordered set
    for rid in rank_ids:
        idx = rid.find(_RANK_PREFIX)
        if idx < 0:
            continue
        partition_part = rid[:idx]           # e.g. "dev:"
        suffix = rid[idx + len(_RANK_PREFIX):]  # e.g. "ColName-Chrono-Stage:"
        suffix = suffix.rstrip(":")
        matched = False
        for sep in _RANK_SEPS:
            if sep in suffix:
                col_suffix = suffix.split(sep)[0]
                col_ids[f"{partition_part}{_COL_TYPE}{col_suffix}:"] = None
                matched = True
                break
        if not matched and suffix:
            # Treat entire suffix as candidate column name
            col_ids[f"{partition_part}{_COL_TYPE}{suffix}:"] = None
    return list(col_ids)


async def _verify_column_from_storage(
    client: httpx.AsyncClient,
    storage_url: str,
    hdr: dict,
    record_id: str,
) -> Optional[Dict[str, Any]]:
    """Verify a StratigraphicColumn record exists in OSDU Storage.

    Returns an item dict suitable for the search response, or None.
    """
    try:
        encoded = urllib.parse.quote(record_id, safe="")
        r = await client.get(f"{storage_url}/{encoded}", headers=hdr)
        if r.status_code != 200:
            return None
        full = r.json() or {}
        kind = full.get("kind") or ""
        if "StratigraphicColumn" not in kind:
            return None
        name = (full.get("data") or {}).get("Name") or record_id
        return {
            "id": record_id,
            "name": name,
            "kind": kind,
            "version": full.get("version"),
            "source": "storage",
        }
    except Exception:
        return None


@router.get("/api/strat/search.json")
async def strat_search(
    request: Request,
    q: str = Query("*"),
    limit: int = Query(50, ge=1, le=1000),
    type: str = Query("all", description="Filter: all | column | rank | unit"),
):
    at = _access_token(request)
    search_url = f"https://{osdu.OSDU_BASE_URL}/api/search/v2/query"
    storage_url = f"https://{osdu.OSDU_BASE_URL}/api/storage/v2/records"
    hdr = osdu.headers(at)
    search_type = (type or "all").strip().lower()

    items: List[Dict[str, Any]] = []
    total = 0
    seen_ids: set[str] = set()

    async with osdu.http_client(timeout=60) as client:

        # ── Helper: run one search query and collect results ──
        async def _search_kind(kind: str, item_type: str, extra_fields=None):
            nonlocal total
            fields = ["id", "kind", "version", "data.Name"]
            if extra_fields:
                fields.extend(extra_fields)
            payload = {
                "kind": kind,
                "query": q or "*",
                "limit": int(limit),
                "returnedFields": fields,
                "trackTotalCount": True,
            }
            r = await client.post(search_url, headers=hdr, json=payload)
            log.info("Search %s q='%s' → %d", kind.split("--")[-1].split(":")[0], q, r.status_code)
            if r.status_code >= 400:
                log.warning("Search failed (%d): %s", r.status_code, r.text[:300])
                return []
            res = r.json() or {}
            found = res.get("totalCount") or len(res.get("results") or [])
            results = []
            for rec in res.get("results") or []:
                rid = rec.get("id")
                if not rid or rid in seen_ids:
                    continue
                seen_ids.add(rid)
                rd = rec.get("data") or {}
                name = rd.get("Name") or ""
                if item_type == "rank" and not name:
                    name = _label_from_ref_id(rd.get("StratigraphicColumnRankUnitType") or "") or rid
                results.append({
                    "id": rid,
                    "name": name or rid,
                    "kind": rec.get("kind") or "",
                    "version": rec.get("version"),
                    "type": item_type,
                })
                total += 1
            return results

        # ── 1. Columns ──
        if search_type in ("all", "column"):
            col_items = await _search_kind(
                "osdu:wks:work-product-component--StratigraphicColumn:*", "column")
            items.extend(col_items)

            # Discovery: find un-indexed columns via their Rank children
            if search_type == "all":
                try:
                    rank_disc = await _search_kind(
                        "osdu:wks:work-product-component--StratigraphicColumnRankInterpretation:*",
                        "rank",
                        extra_fields=["data.StratigraphicColumnRankUnitType"],
                    )
                    rank_ids_found = [r2["id"] for r2 in rank_disc]
                    candidate_col_ids = _derive_column_ids_from_ranks(rank_ids_found)
                    verify_tasks = []
                    for cid in candidate_col_ids:
                        if cid not in seen_ids:
                            verify_tasks.append(_verify_column_from_storage(
                                client, storage_url, hdr, cid
                            ))
                    if verify_tasks:
                        verified = await asyncio.gather(*verify_tasks)
                        for item in verified:
                            if item and item["id"] not in seen_ids:
                                seen_ids.add(item["id"])
                                items.append(item)
                                total += 1
                    # Include discovered ranks in results
                    items.extend(rank_disc)
                except Exception:
                    pass  # Rank discovery is best-effort

        # ── 2. Ranks (standalone search) ──
        if search_type == "rank":
            rank_items = await _search_kind(
                "osdu:wks:work-product-component--StratigraphicColumnRankInterpretation:*",
                "rank",
                extra_fields=["data.StratigraphicColumnRankUnitType"],
            )
            items.extend(rank_items)

        # ── 3. Units ──
        if search_type == "unit":
            unit_items = await _search_kind(
                "osdu:wks:work-product-component--StratigraphicUnitInterpretation:*",
                "unit",
            )
            items.extend(unit_items)

    items.sort(key=lambda x: (x.get("name") or "").lower())

    log.info("Search complete: %d items (total=%d, q='%s', type='%s')",
             len(items), total, q, search_type)
    return JSONResponse({"items": items, "total": total})


def _ids(val: Any) -> List[str]:
    """Extract a list of record IDs from heterogeneous inputs."""
    if isinstance(val, list):
        out = []
        for item in val:
            s = _as_id(item)
            if s:
                out.append(s)
        return out
    s = _as_id(val)
    return [s] if s else []

async def _storage_fetch_many(request: Request, ids: List[str]) -> Dict[str, dict]:
    """Batch-fetch records.  Handles both UUID IDs (no trailing ':') and named IDs
    (trailing ':' is canonical).  After the first pass, any not-found IDs are retried
    with the colon toggled.  Results are keyed under both forms for easy lookup."""
    at = _access_token(request)
    base = f"https://{osdu.OSDU_BASE_URL}/api/storage/v2"
    hdr = osdu.headers(at)

    # Normalize heterogeneous inputs (str | dict) -> str ids
    norm_ids: List[str] = []
    for i in ids or []:
        s = _as_id(i)
        if s:
            norm_ids.append(s)

    # Dedupe while preserving order
    uniq = list(dict.fromkeys(norm_ids))
    if not uniq:
        return {}

    results: Dict[str, dict] = {}

    async def post_batch(client: httpx.AsyncClient, chunk: List[str]) -> List[str]:
        url = f"{base}/query/records:batch"
        r = await client.post(url, headers=hdr, json={"records": chunk})
        if r.status_code == 404:
            raise FileNotFoundError("records:batch not available")
        log.debug("Storage batch POST %d ids → %d", len(chunk), r.status_code)
        if r.status_code >= 400:
            log.warning("Storage batch POST failed (%d): %s", r.status_code, r.text[:300])
        r.raise_for_status()
        data = r.json() or {}
        recs = data.get("records")
        not_found: List[str] = data.get("notFound") or []
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
        return not_found

    async def get_one(client: httpx.AsyncClient, rid: str, sem: asyncio.Semaphore) -> None:
        url = f"{base}/records/{urllib.parse.quote(rid, safe='')}"
        async with sem:
            r = await client.get(url, headers=hdr)
            log.debug("Storage GET %s → %d", rid, r.status_code)
            if r.status_code == 200:
                results[rid] = r.json() or {}
            elif r.status_code != 404:
                log.warning("Storage GET %s → %d: %s", rid, r.status_code, r.text[:200])
                r.raise_for_status()

    async with osdu.http_client(timeout=30, http2=True) as client:
        chunks = [uniq[i:i+20] for i in range(0, len(uniq), 20)]
        try:
            # Pass 1: try all IDs as-is
            nf_lists = await asyncio.gather(*(post_batch(client, c) for c in chunks))
            all_not_found = [nf for sublist in nf_lists for nf in sublist]

            # Pass 2: retry not-found IDs with toggled trailing colon
            retry = []
            for nf_id in all_not_found:
                alt = nf_id[:-1] if nf_id.endswith(":") else nf_id + ":"
                if alt not in results:
                    retry.append(alt)
            if retry:
                retry_chunks = [retry[i:i+20] for i in range(0, len(retry), 20)]
                await asyncio.gather(*(post_batch(client, c) for c in retry_chunks))

        except FileNotFoundError:
            # Fallback: individual GET for each ID
            sem = asyncio.Semaphore(12)
            await asyncio.gather(*(get_one(client, rid, sem) for rid in uniq))
            # Retry with toggled colon for missing
            missing = [rid for rid in uniq if rid not in results]
            retry2 = []
            for rid in missing:
                alt = rid[:-1] if rid.endswith(":") else rid + ":"
                if alt not in results:
                    retry2.append(alt)
            if retry2:
                await asyncio.gather(*(get_one(client, rid, sem) for rid in retry2))

    # Store results under both colon forms for easy caller lookups
    for rid in list(results.keys()):
        body = results[rid]
        alt = rid[:-1] if rid.endswith(":") else rid + ":"
        if alt not in results:
            results[alt] = body

    fetched = len({k for k, v in results.items() if v})
    log.info("Storage fetch: %d requested, %d fetched", len(uniq), fetched // 2 if fetched else 0)
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
    # 1) Fetch the record (could be Column or Rank)
    col = await _osdu_get_record(request, id)
    if not col or not isinstance(col, dict):
        raise HTTPException(404, detail="Record not found")

    kind = col.get("kind", "")

    # ── Handle StratigraphicColumnRankInterpretation directly ──
    # Wrap it as a single-rank synthetic column so the rest of the pipeline
    # (unit/chrono fetching, gap-fill, horizon collection) works unchanged.
    if "StratigraphicColumnRankInterpretation" in kind:
        drk = _get_data(col)
        rank_name = (
            drk.get("Name")
            or _label_from_ref_id(drk.get("StratigraphicColumnRankUnitType") or "")
            or "Unspecified"
        )
        # Build a synthetic Column wrapper
        col_wrapper = {
            "id": id,
            "kind": "osdu:wks:work-product-component--StratigraphicColumn:1.2.0",
            "data": {"Name": f"(Single Rank) {rank_name}"},
            "_singleRank": True,
        }
        rank_ids = [id]
        ranks_by_id = {id: col}
        # Update col to the wrapper for the rest of the function
        col = col_wrapper
    elif kind.startswith("osdu:wks:work-product-component--StratigraphicColumn:"):
        dcol = _get_data(col)
        # 2) Read ordered rank IDs
        rank_ids = _ids(
            dcol.get("StratigraphicColumnRankInterpretationSet")
            or dcol.get("RankInterpretationSet")
            or []
        )
        if not rank_ids:
            return JSONResponse({"column": col, "ranks": []})
        # 3) Fetch all ranks in one go
        ranks_by_id = await _storage_fetch_many(request, rank_ids)
    else:
        raise HTTPException(400, detail="Record is not a StratigraphicColumn or RankInterpretation")

    dcol = _get_data(col)

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
    horizon_ids_all: List[str] = []
    for u in units_by_id.values():
        ud = _get_data(u)
        cid = _as_id(ud.get("ChronoStratigraphyID") or ud.get("ChronostratigraphyID") or "")
        if cid:
            chrono_ids_all.append(cid)
        # Collect horizon boundary references from units
        for hkey in ("ColumnStratigraphicHorizonTopID", "ColumnStratigraphicHorizonBaseID"):
            hid = _as_id(ud.get(hkey) or "")
            if hid:
                horizon_ids_all.append(hid)

    # 6) Fetch all chrono records and horizon records (deduped by the batched helper)
    chron_by_id = await _storage_fetch_many(request, chrono_ids_all) if chrono_ids_all else {}
    horizons_by_id = await _storage_fetch_many(request, horizon_ids_all) if horizon_ids_all else {}

    # 7) Assemble ranks in the original order with:
    #      - rankName: from data.Name or the StratigraphicColumnRankUnitType label (System/Series/Group/Formation/…)
    #      - isChrono: True if rank lists chrono refs and has no unit interpretations (as per OSDU usage)
    #      - units:    ordered older→younger; rank-level Chrono entries first, then unit interpretations
    ranks_model: List[Dict[str, Any]] = []

    def _age_key(u: Dict[str, Any]):
        """Sort key: older units first (bigger Ma value first).

        Uses normalized olderMa / youngerMa which are convention-agnostic
        (handles both SMDA top<base and ICS top>base).
        """
        older = u.get("olderMa")
        younger = u.get("youngerMa")
        if older is not None and younger is not None:
            return (-older, younger)
        # Fallback: normalize raw topMa/baseMa
        top = u.get("topMa")
        base = u.get("baseMa")
        if top is not None and base is not None:
            return (-max(top, base), min(top, base))
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
                ff = _flat_unit_fields(None, crec, horizons_by_id)
                units_model.append({"unit": {}, "chrono": crec, **ff})

        # B) Rank-level unit interpretations: attach chrono if the unit points to one (ChronoStratigraphyID)
        for oidx, uid in enumerate(unit_ids):
            urec = units_by_id.get(uid)
            if not urec:
                continue
            ud = _get_data(urec)
            cid = _as_id(ud.get("ChronoStratigraphyID") or ud.get("ChronostratigraphyID") or "")
            cobj = chron_by_id.get(cid) if cid else {}
            ff = _flat_unit_fields(urec, cobj, horizons_by_id)
            ff["_origIdx"] = oidx  # preserve OSDU record order
            units_model.append({"unit": urec, "chrono": cobj, **ff})

        # C) Order: for chrono ranks use age, for litho preserve the OSDU
        #    StratigraphicUnitInterpretationSet order - that IS the
        #    authoritative stratigraphic ordering.  Litho formations can
        #    cross chronostratigraphic boundaries so age-sorting is wrong.
        if is_chrono_rank:
            units_model.sort(key=_age_key)
        else:
            units_model.sort(key=lambda u: u.get("_origIdx", 0))

        ranks_model.append({
            "rankName": rank_name,
            "isChrono": is_chrono_rank,
            "rank": rk,
            "unitCount": len(units_model),
            "units": units_model
        })

    # 8) Fill gaps: for each consecutive pair of ranks, if a unit at rank N
    #    has no children at rank N+1 (i.e. no unit at N+1 whose age range
    #    is contained within the N-unit), insert a synthetic placeholder
    #    unit at rank N+1. This ensures the hierarchical table has no
    #    undefined white cells - missing data is visually declared.
    #
    #    The OSDU / ICS chrono model is inherently hierarchical and
    #    non-overlapping per rank.  Gaps in the data therefore represent
    #    missing information (not geological gaps) and should be declared.
    #
    #    Synthetic placeholders cascade through subsequent ranks: if Eonothem
    #    "Hadean" has no Erathem children, the synthetic Erathem entry itself
    #    propagates to System, SubSystem, Series, etc. - ensuring every cell
    #    in the table is accounted for.  The `_originalName` field preserves
    #    the real ancestor name so labels stay clean (no nested nesting).
    def _norm_name(s: str) -> str:
        """Normalize a name for fuzzy matching: lowercase, strip trailing
        punctuation (.,-) and extra whitespace."""
        return (s or "").strip().lower().rstrip(".,- ").strip()

    def _is_age_contained(child_unit, parent_unit, tol=0.5):
        """True if child's normalized age range fits within parent's.

        Uses olderMa/youngerMa which are convention-agnostic (handles both
        SMDA top<base and ICS top>base).  0.5 Ma tolerance for boundary
        rounding between geological schemes.
        """
        co = child_unit.get("olderMa")
        cy = child_unit.get("youngerMa")
        po = parent_unit.get("olderMa")
        py = parent_unit.get("youngerMa")
        if None in (co, cy, po, py):
            return False
        return co <= po + tol and cy >= py - tol

    def _child_of(child_unit, parent_unit):
        """True if child belongs to parent - by parentName or age containment.

        ParentName (fuzzy-matched) is checked first; when it's set but doesn't
        match, falls back to age containment (handles data inconsistencies
        like 'Alke Fm' vs 'Alke Fm.').  When parentName is absent, uses
        normalized-age containment directly.
        """
        pn = _norm_name(child_unit.get("parentName") or "")
        if pn:
            nn = _norm_name(parent_unit.get("name") or "")
            if pn == nn:
                return True
            # parentName set but no name match - fall through to age
        return _is_age_contained(child_unit, parent_unit)

    for ri in range(len(ranks_model) - 1):
        parent_rank = ranks_model[ri]
        child_rank = ranks_model[ri + 1]
        child_units = child_rank["units"]

        # For ranks where ALL children use parentName hierarchy, skip
        # age-based gap-fill (litho formations cross age boundaries).
        # When only some children have parentName, still do age gap-fill
        # for the rest (mixed columns like biozonation).
        all_have_parent = all(cu.get("parentName") for cu in child_units) if child_units else False
        if all_have_parent:
            continue

        new_children: List[Dict[str, Any]] = []
        for pu in parent_rank["units"]:
            p_older = pu.get("olderMa")
            p_younger = pu.get("youngerMa")
            # Use original ancestor name for clean labels (avoid nested "((...) - undifferentiated)")
            p_name = pu.get("_originalName") or pu.get("name") or ""

            # Find existing children at the next rank contained in this parent
            # (by age containment OR parentName match)
            kids = [cu for cu in child_units if _child_of(cu, pu)]

            # Age-based gap-fill only possible when parent has age range
            if p_older is None or p_younger is None:
                continue

            if not kids:
                # No children at all → insert one synthetic placeholder
                # covering the full parent age range
                new_children.append({
                    "unit": {},
                    "chrono": {},
                    "name": f"({p_name} - undifferentiated)",
                    "_originalName": p_name,
                    "topMa": p_older,
                    "baseMa": p_younger,
                    "olderMa": p_older,
                    "youngerMa": p_younger,
                    "color": None,
                    "code": "",
                    "_synthetic": True,
                })
            else:
                # Children exist but may not tile the full parent range.
                # Sort kids older-first and look for age gaps.
                # Only consider non-synthetic units for gap detection
                # (synthetics already placed from earlier rounds shouldn't
                # count as real coverage)
                real_kids = [k for k in kids if not k.get("_synthetic")]
                if not real_kids:
                    # All children are synthetic from earlier rounds - skip
                    continue
                # Sort by normalized olderMa descending (oldest first)
                kids_sorted = sorted(real_kids, key=lambda c: -(c.get("olderMa") or 0))
                # Gap at older end: parent.olderMa → first child.olderMa
                first_older = kids_sorted[0].get("olderMa")
                if first_older is not None and p_older - first_older > 0.5:
                    new_children.append({
                        "unit": {}, "chrono": {},
                        "name": f"(not defined, {_fmt_ma(p_older)}–{_fmt_ma(first_older)} Ma)",
                        "_originalName": f"not defined {_fmt_ma(p_older)}–{_fmt_ma(first_older)} Ma",
                        "topMa": p_older, "baseMa": first_older,
                        "olderMa": p_older, "youngerMa": first_older,
                        "color": None, "code": "", "_synthetic": True,
                    })
                # Gaps between consecutive children
                for ci in range(len(kids_sorted) - 1):
                    cur_younger = kids_sorted[ci].get("youngerMa")
                    nxt_older = kids_sorted[ci + 1].get("olderMa")
                    if cur_younger is not None and nxt_older is not None and cur_younger - nxt_older > 0.5:
                        new_children.append({
                            "unit": {}, "chrono": {},
                            "name": f"(not defined, {_fmt_ma(cur_younger)}–{_fmt_ma(nxt_older)} Ma)",
                            "_originalName": f"not defined {_fmt_ma(cur_younger)}–{_fmt_ma(nxt_older)} Ma",
                            "topMa": cur_younger, "baseMa": nxt_older,
                            "olderMa": cur_younger, "youngerMa": nxt_older,
                            "color": None, "code": "", "_synthetic": True,
                        })
                # Gap at younger end: last child.youngerMa → parent.youngerMa
                last_younger = kids_sorted[-1].get("youngerMa")
                if last_younger is not None and last_younger - p_younger > 0.5:
                    new_children.append({
                        "unit": {}, "chrono": {},
                        "name": f"(not defined, {_fmt_ma(last_younger)}–{_fmt_ma(p_younger)} Ma)",
                        "_originalName": f"not defined {_fmt_ma(last_younger)}–{_fmt_ma(p_younger)} Ma",
                        "topMa": last_younger, "baseMa": p_younger,
                        "olderMa": last_younger, "youngerMa": p_younger,
                        "color": None, "code": "", "_synthetic": True,
                    })

        if new_children:
            # Deduplicate synthetic entries that cover overlapping age ranges
            # (can happen when umbrella units like "Precambrian" overlap real units)
            deduped: List[Dict[str, Any]] = []
            seen_ranges: set = set()
            for nc in new_children:
                key = (round(nc.get("topMa", 0), 2), round(nc.get("baseMa", 0), 2))
                if key not in seen_ranges:
                    seen_ranges.add(key)
                    deduped.append(nc)
            child_rank["units"] = child_rank["units"] + deduped
            child_rank["units"].sort(key=_age_key)
            child_rank["unitCount"] = len(child_rank["units"])

    # 9) Collect fetched horizon records for inclusion in the model
    horizon_list = [
        {"id": rec.get("id", hid), **_get_data(rec)}
        for hid, rec in horizons_by_id.items() if rec
    ] if horizons_by_id else []

    # 10) Return column model
    return JSONResponse({
        "column": col,
        "ranks": ranks_model,
        "horizons": horizon_list,
        "horizonCount": len(horizon_list),
    })


# =====================================================================
# IMPORT / CONVERT / INGEST endpoints
# =====================================================================

# ── Chrono reference index (for resolving chrono names → OSDU SRNs) ──

async def _build_chrono_index(request: Request) -> Dict[str, str]:
    """Query OSDU Search for ChronoStratigraphy reference-data records
    and build a lookup: lower(Name/AliasName/Code) → record ID.

    This is the runtime equivalent of ``load_reference_index()`` in
    stratcolumnhandler.py, but instead of reading local JSON files it
    queries the Search API.
    """
    at = _access_token(request)
    search_url = f"https://{osdu.OSDU_BASE_URL}/api/search/v2/query"
    hdr = osdu.headers(at)

    idx: Dict[str, str] = {}
    cursor: Optional[str] = None
    page = 0

    async with osdu.http_client(timeout=60) as client:
        while True:
            payload: Dict[str, Any] = {
                "kind": "osdu:wks:reference-data--ChronoStratigraphy:*",
                "query": "*",
                "limit": 1000,
                "returnedFields": ["id", "data.Name", "data.AliasNames", "data.Code", "data.CodeAsNumber"],
            }
            if cursor:
                payload["cursor"] = cursor
            r = await client.post(search_url, headers=hdr, json=payload)
            if not r.is_success:
                log.warning("Chrono index search failed (%s): %s",
                            r.status_code, r.text[:300])
                break
            res = r.json() or {}
            results = res.get("results") or []
            for rec in results:
                rid = rec.get("id")
                if not rid:
                    continue
                data = rec.get("data") or {}
                names: List[str] = []
                if data.get("Name"):
                    names.append(str(data["Name"]))
                for a in (data.get("AliasNames") or []):
                    if a:
                        names.append(str(a))
                for k in ("Code", "CodeAsNumber"):
                    if data.get(k) is not None:
                        names.append(str(data[k]))
                for val in names:
                    key = val.lower().strip()
                    if key:
                        idx[key] = rid
            cursor = res.get("cursor")
            page += 1
            if not cursor or not results or page > 20:
                break

    log.info("Chrono reference index: %d names from OSDU", len(idx))
    return idx

@router.post("/api/strat/import/ow")
async def import_ow_json(
    request: Request,
    file: UploadFile = File(...),
    partition: str = Form("data"),
):
    """Upload an OpenWorks JSON file; convert it to an OSDU WPC bundle.

    Returns the OSDU bundle JSON (ready for ingestion via /api/strat/ingest).
    """
    if _StratColumn is None:
        raise HTTPException(500, "stratcolumnhandler not available on this deployment")

    try:
        raw = await file.read()
        doc = json.loads(raw)
    except Exception as e:
        raise HTTPException(400, f"Invalid JSON file: {e}")

    try:
        col = _StratColumn.from_openworks_json(doc)
    except Exception as e:
        raise HTTPException(422, f"Conversion error: {e}")

    # If the column has chrono ranks, resolve names via OSDU reference data
    has_chrono = any(r.kind != "litho" for r in col.ranks)
    chrono_idx: Optional[Dict[str, str]] = None
    if has_chrono:
        try:
            chrono_idx = await _build_chrono_index(request)
        except Exception as exc:
            log.warning("Could not build chrono index from OSDU: %s", exc)

    try:
        bundle = col.to_osdu_bundle(partition=partition, chrono_rd_index=chrono_idx)
    except Exception as e:
        raise HTTPException(422, f"Conversion error: {e}")

    return JSONResponse({
        "source": "openworks",
        "columnName": col.name,
        "rankCount": len(col.ranks),
        "unitCount": sum(len(r.units) for r in col.ranks if r.kind == "litho"),
        "bundle": bundle,
    })


async def _smda_auth(request: Request) -> dict:
    """Return SMDA auth kwargs for stratcolumnhandler calls.

    Returns a dict with access_token and/or api_key.
    The API Gateway needs both a Bearer token (targeting the SMDA resource)
    and an Ocp-Apim-Subscription-Key.
    """
    kw: dict = {}
    token = await _auth.smda_access_token(request)
    if token:
        kw["access_token"] = token
    if SMDA_API_KEY:
        kw["api_key"] = SMDA_API_KEY
    if not kw:
        raise HTTPException(
            403,
            "SMDA auth not available. Set SMDA_API_KEY in .env, "
            "or run 'az login' to authenticate.",
        )
    if not kw.get("access_token"):
        raise HTTPException(
            403,
            "SMDA Bearer token not available. Run 'az login' to authenticate "
            "with your Equinor Entra ID.",
        )
    return kw


@router.post("/api/strat/import/smda")
async def import_smda_api(
    request: Request,
    column: str = Form(...),
    smda_url: str = Form("https://api.gateway.equinor.com"),
    partition: str = Form("data"),
):
    """Fetch a strat column from SMDA API and convert to OSDU WPC bundle."""
    if _StratColumn is None:
        raise HTTPException(500, "stratcolumnhandler not available")

    auth_kw = await _smda_auth(request)

    try:
        col = _StratColumn.from_smda_api(
            column,
            base_url=smda_url,
            **auth_kw,
            verify_ssl=False,
        )
    except Exception as e:
        raise HTTPException(422, f"SMDA fetch/convert error: {e}")

    # If the column has chrono ranks, build a chrono reference index from OSDU
    has_chrono = any(r.kind != "litho" for r in col.ranks)
    chrono_idx: Optional[Dict[str, str]] = None
    if has_chrono:
        try:
            chrono_idx = await _build_chrono_index(request)
        except Exception as exc:
            log.warning("Could not build chrono index from OSDU: %s", exc)

    try:
        bundle = col.to_osdu_bundle(
            partition=partition,
            chrono_rd_index=chrono_idx,
        )
    except Exception as e:
        raise HTTPException(422, f"SMDA fetch/convert error: {e}")

    return JSONResponse({
        "source": "smda",
        "columnName": col.name,
        "rankCount": len(col.ranks),
        "unitCount": sum(len(r.units) for r in col.ranks if r.kind == "litho"),
        "bundle": bundle,
    })


@router.get("/api/strat/smda/columns.json")
async def list_smda_columns(
    request: Request,
    smda_url: str = Query("https://api.gateway.equinor.com"),
):
    """List available strat column identifiers from the SMDA API Gateway.

    Calls GET /smda/v2.0/smda-api/strat-column with pagination and returns
    a de-duplicated, sorted list of column identifiers.
    """
    auth_kw = await _smda_auth(request)

    url = f"{smda_url.rstrip('/')}/smda/v2.0/smda-api/strat-column"
    headers: dict[str, str] = {
        "Accept": "application/json",
        "Cache-Control": "no-cache",
    }
    if auth_kw.get("access_token"):
        headers["Authorization"] = f"Bearer {auth_kw['access_token']}"
    if auth_kw.get("api_key"):
        headers["Ocp-Apim-Subscription-Key"] = auth_kw["api_key"]

    all_rows: list[dict] = []
    page = 1
    items_per_page = 100

    try:
        async with httpx.AsyncClient(timeout=60, verify=False) as client:
            while True:
                params = {
                    "_page": page,
                    "_items": items_per_page,
                    "_order": "asc",
                    "_aggregation_include_buckets": "true",
                }
                r = await client.get(url, params=params, headers=headers)
                if not r.is_success:
                    body = r.text[:400].strip()
                    log.warning("SMDA strat-column list failed (%s): %s",
                                r.status_code, body or "(empty body)")
                    if r.status_code == 401:
                        detail = (
                            "SMDA API returned 401 Unauthorized. "
                            "The Bearer token may have expired or target the wrong audience. "
                            "Run 'az login' to re-authenticate."
                        )
                        if body:
                            detail += f" Gateway response: {body[:200]}"
                        raise HTTPException(401, detail)
                    raise HTTPException(r.status_code,
                                        f"SMDA API error: {body or '(empty response)'}")

                data = r.json()
                # SMDA gateway returns {"data": {"pages":N, "hits":N, "results":[...]}}
                inner = data.get("data", data) if isinstance(data, dict) else data
                if isinstance(inner, dict):
                    rows = inner.get("results", inner.get("value", []))
                    if not isinstance(rows, list):
                        rows = []
                elif isinstance(inner, list):
                    rows = inner
                else:
                    rows = []

                all_rows.extend(rows)

                # Check if there are more pages
                total = None
                if isinstance(inner, dict):
                    total = inner.get("hits", inner.get("total",
                            inner.get("totalCount", inner.get("_total"))))
                if total is not None:
                    try:
                        total = int(total)
                    except (TypeError, ValueError):
                        total = None

                if total is not None and len(all_rows) >= total:
                    break
                if len(rows) < items_per_page:
                    break  # last page
                page += 1
                if page > 50:  # safety limit
                    break
    except httpx.HTTPError as exc:
        log.warning("SMDA strat-column request error: %s", exc)
        raise HTTPException(502, f"SMDA API request failed: {exc}")

    # Extract unique column identifiers - include type & area metadata
    # Group by identifier, keep the richest metadata row per column
    columns_map: Dict[str, Dict[str, str]] = {}
    for row in all_rows:
        name = str(
            row.get("strat_column_identifier", "") or row.get("identifier", "")
        ).strip()
        if not name:
            continue
        existing = columns_map.get(name)
        col_type = str(row.get("strat_column_type") or "").strip()
        area = str(row.get("area") or row.get("strat_column_area_type") or "").strip()
        status = str(row.get("strat_column_status") or "").strip()
        # Keep the entry with the most metadata
        if not existing or (col_type and not existing.get("type")):
            columns_map[name] = {
                "name": name,
                "type": col_type,
                "area": area,
                "status": status,
            }

    # Sort alphabetically, but group "column" types before "rank" types.
    # Within each group, sort by name (case-insensitive).
    def _sort_key(c):
        t = (c.get("type") or "").upper()
        # 0 = COLUMN (first), 1 = anything else / RANK (second)
        group = 0 if "RANK" not in t else 1
        return (group, c["name"].lower())

    columns_list = sorted(columns_map.values(), key=_sort_key)

    log.info("SMDA strat-column list: %d columns from %d rows (%d pages)",
             len(columns_list), len(all_rows), page)

    return JSONResponse({
        "columns": [c["name"] for c in columns_list],
        "details": columns_list,
        "total": len(columns_list),
    })


@router.post("/api/strat/storage/put")
async def storage_put_strat_records(
    request: Request,
):
    """Directly PUT strat column records to OSDU Storage (bypassing workflow).

    Body:
    {
      "bundle": {"records": [...]},
      "partition": "data"
    }
    """
    at = _access_token(request)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    bundle = body.get("bundle")
    if not isinstance(bundle, dict) or "records" not in bundle:
        raise HTTPException(400, "Body must include 'bundle' with 'records' array")

    records = bundle["records"]
    base = f"https://{osdu.OSDU_BASE_URL}"
    url = f"{base}/api/storage/v2/records"
    hdr = osdu.headers(at)

    # ── Inject default ACL + legal into records that lack them ──
    # Without these, Storage accepts the record but the Indexer silently
    # skips it → record exists in Storage but never appears in Search.
    default_acl = {
        "viewers": osdu.DEFAULT_VIEWERS,
        "owners": osdu.DEFAULT_OWNERS,
    }
    default_legal = {
        "legaltags": [osdu.DEFAULT_LEGAL_TAG],
        "otherRelevantDataCountries": osdu.DEFAULT_COUNTRIES,
    }
    for rec in records:
        if not rec.get("acl"):
            rec["acl"] = default_acl
        if not rec.get("legal"):
            rec["legal"] = default_legal

    results = {"created": 0, "errors": []}
    # Upload in batches of 20
    log.info("Storage PUT %d records in batches of 20", len(records))
    async with osdu.http_client(timeout=60) as client:
        for i in range(0, len(records), 20):
            batch = records[i:i + 20]
            try:
                r = await client.put(url, headers=hdr, json=batch)
                if r.status_code < 300:
                    resp = r.json()
                    cnt = resp.get("recordCount", len(batch))
                    results["created"] += cnt
                    log.debug("Storage PUT batch %d \u2192 %d (%d records)", i, r.status_code, cnt)
                else:
                    log.warning("Storage PUT batch %d \u2192 %d: %s", i, r.status_code, r.text[:300])
                    results["errors"].append({
                        "batch": i,
                        "httpStatus": r.status_code,
                        "detail": _sanitize(r),
                    })
            except Exception as e:
                log.error("Storage PUT batch %d exception: %s", i, e)
                results["errors"].append({"batch": i, "error": _safe_detail(e)})

    log.info("Storage PUT done: %d created, %d errors", results["created"], len(results["errors"]))

    status = "ok" if not results["errors"] else "partial"
    return JSONResponse({
        "status": status,
        "totalRecords": len(records),
        **results,
    })


# =====================================================================
# HORIZON GENERATION - derive HorizonInterpretation records from
# unit/chrono boundary ages in a loaded column model.
# =====================================================================

_KIND_HORIZON = "osdu:wks:work-product-component--HorizonInterpretation:1.2.0"


def _age_token(age: float) -> str:
    """538.8 -> '538p8', 66.0 -> '66p0' - safe for OSDU record IDs."""
    s = f"{age:g}"
    return s.replace(".", "p").replace("-", "m")


def _generate_horizons_for_column(
    model: dict,
    partition: str = "data",
) -> dict:
    """Derive HorizonInterpretation WPC records from boundary ages in a column model.

    **Complement-aware**: skips ages that already have a real HorizonInterpretation
    record linked from a unit (``horizonTop`` / ``horizonBase`` in the model).
    Only creates horizons for ages that are *missing* a boundary record.

    Returns:
      {
        "horizons":  [<OSDU WPC record>, ...],          # new (to be created)
        "unitPatches": [{"unitId": "...", "patch": {...}}, ...],
        "stats": {"uniqueAges": N, "horizonCount": N, "unitsPatchable": N,
                  "existingHorizons": N, "skippedAges": N}
      }
    """
    column = model.get("column") or {}
    col_data = _get_data(column) if isinstance(column, dict) else {}
    col_name = col_data.get("Name") or "Column"

    import re as _re
    col_token = _re.sub(r"[^A-Za-z0-9._-]+", "-", col_name.strip())[:200]
    if not col_token:
        col_token = "Column"

    role_type_id = f"{partition}:reference-data--StratigraphicRoleType:Chronostratigraphic:"

    # ── Inventory existing horizons already linked from units ─────────
    # Build a set of ages that already have real horizon records so we
    # can skip them (complement, not duplicate).
    existing_horizon_ages: Dict[float, str] = {}   # age → existing horizon id
    for rank in model.get("ranks") or []:
        for unit in rank.get("units") or []:
            if unit.get("_synthetic"):
                continue
            for hkey in ("horizonTop", "horizonBase"):
                h = unit.get(hkey)
                if h and isinstance(h, dict) and h.get("id"):
                    age = h.get("ageMa")
                    if age is not None:
                        existing_horizon_ages[float(age)] = h["id"]

    # 1) Walk all units across all ranks, collect distinct boundary ages
    age_info: Dict[float, List[tuple]] = {}
    unit_ages: Dict[str, tuple] = {}

    for ri, rank in enumerate(model.get("ranks") or []):
        for ui, unit in enumerate(rank.get("units") or []):
            if unit.get("_synthetic"):
                continue
            # Use normalized ages (convention-agnostic: works for both
            # ICS chrono where topMa=older and SMDA litho where topMa=younger).
            older = unit.get("olderMa")
            younger = unit.get("youngerMa")
            name = unit.get("name") or f"Unit_{ui}"
            key = f"{ri}:{ui}"

            if older is not None and younger is not None:
                unit_ages[key] = (older, younger)
                # olderMa = base of unit (stratigraphically deeper)
                # youngerMa = top of unit (stratigraphically shallower)
                age_info.setdefault(older, []).append((name, "base"))
                age_info.setdefault(younger, []).append((name, "top"))

    # 2) Generate a HorizonInterpretation record per distinct age
    #    SKIP ages that already have a real horizon linked.
    horizons: List[dict] = []
    horizon_id_by_age: Dict[float, str] = {}
    skipped_ages = 0

    default_acl = {"viewers": osdu.DEFAULT_VIEWERS, "owners": osdu.DEFAULT_OWNERS}
    default_legal = {
        "legaltags": [osdu.DEFAULT_LEGAL_TAG],
        "otherRelevantDataCountries": osdu.DEFAULT_COUNTRIES,
    }

    for age in sorted(age_info.keys()):
        # If a real horizon already covers this age, reuse its ID for patches
        if age in existing_horizon_ages:
            horizon_id_by_age[age] = existing_horizon_ages[age]
            skipped_ages += 1
            continue

        entries = age_info[age]
        tops = [n for n, side in entries if side == "top"]
        bases = [n for n, side in entries if side == "base"]
        if tops:
            label = f"Top {tops[0]}"
            if len(tops) > 1:
                label += f" (+{len(tops) - 1})"
        elif bases:
            label = f"Base {bases[0]}"
            if len(bases) > 1:
                label += f" (+{len(bases) - 1})"
        else:
            label = f"{age} Ma"

        hid = f"{partition}:work-product-component--HorizonInterpretation:{col_token}-H-{_age_token(age)}Ma:"
        horizon_id_by_age[age] = hid

        horizons.append({
            "id": hid,
            "kind": _KIND_HORIZON,
            "acl": default_acl,
            "legal": default_legal,
            "data": {
                "Name": label,
                "Description": f"Stratigraphic boundary at {age} Ma",
                "MeanPossibleAge": age,
                "OlderPossibleAge": age,
                "YoungerPossibleAge": age,
                "StratigraphicRoleTypeID": role_type_id,
                "isConformableAbove": True,
                "isConformableBelow": True,
                "IsDiscoverable": True,
            },
        })

    # 3) Build patches: only for units that don't already have horizon links
    unit_patches: List[dict] = []
    for ri, rank in enumerate(model.get("ranks") or []):
        for ui, unit in enumerate(rank.get("units") or []):
            key = f"{ri}:{ui}"
            if key not in unit_ages:
                continue
            older_age, younger_age = unit_ages[key]
            # Check which links the unit already has
            has_base = bool(unit.get("horizonBase"))
            has_top = bool(unit.get("horizonTop"))
            patch: Dict[str, Any] = {}
            # Base = stratigraphically deeper = older boundary
            if not has_base and older_age in horizon_id_by_age:
                patch["ColumnStratigraphicHorizonBaseID"] = horizon_id_by_age[older_age]
            # Top = stratigraphically shallower = younger boundary
            if not has_top and younger_age in horizon_id_by_age:
                patch["ColumnStratigraphicHorizonTopID"] = horizon_id_by_age[younger_age]
            if older_age is not None and not has_base:
                patch["OlderPossibleAge"] = older_age
            if younger_age is not None and not has_top:
                patch["YoungerPossibleAge"] = younger_age
            unit_rec = unit.get("unit") or {}
            unit_id = unit_rec.get("id", "")
            if patch:
                unit_patches.append({"unitId": unit_id, "name": unit.get("name", ""), "patch": patch})

    return {
        "horizons": horizons,
        "unitPatches": unit_patches,
        "stats": {
            "uniqueAges": len(age_info),
            "horizonCount": len(horizons),
            "unitsPatchable": len(unit_patches),
            "existingHorizons": len(existing_horizon_ages),
            "skippedAges": skipped_ages,
        },
    }


@router.post("/api/strat/generate-horizons")
async def generate_horizons(request: Request):
    """Generate HorizonInterpretation records from unit/chrono boundary ages.

    Body:
    {
      "columnId": "<OSDU StratigraphicColumn record id>",
      "partition": "data",
      "ingest": false   // if true, also PUT the horizons to OSDU Storage
    }

    Returns the generated horizons, unit patches, and stats.
    If ingest=true, also sends the horizon records to OSDU Storage.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    column_id = (body.get("columnId") or "").strip()
    partition = (body.get("partition") or osdu.DATA_PARTITION_ID or "data").strip()
    do_ingest = body.get("ingest", False)

    if not column_id:
        raise HTTPException(400, "columnId is required")

    # 1) Fetch the column model
    model = await _fetch_column_model(request, column_id)

    # 2) Generate horizons
    result = _generate_horizons_for_column(model, partition=partition)
    horizons = result["horizons"]

    log.info("[Horizons] Generated %d horizons for column %s (%d unit patches)",
             len(horizons), column_id, len(result["unitPatches"]))

    # 3) Optionally ingest to OSDU Storage
    ingest_result = None
    if do_ingest and horizons:
        at = _access_token(request)
        base = f"https://{osdu.OSDU_BASE_URL}"
        url = f"{base}/api/storage/v2/records"
        hdr = osdu.headers(at)

        ingest_result = {"created": 0, "errors": []}
        async with osdu.http_client(timeout=60) as client:
            for i in range(0, len(horizons), 20):
                batch = horizons[i:i + 20]
                try:
                    r = await client.put(url, headers=hdr, json=batch)
                    if r.status_code < 300:
                        resp = r.json()
                        ingest_result["created"] += resp.get("recordCount", len(batch))
                    else:
                        ingest_result["errors"].append({
                            "batch": i, "httpStatus": r.status_code,
                            "detail": _sanitize(r),
                        })
                except Exception as e:
                    ingest_result["errors"].append({"batch": i, "error": _safe_detail(e)})

    return JSONResponse({
        **result,
        "ingest": ingest_result,
    })


# =====================================================================
# UNIT GENERATION - derive StratigraphicUnitInterpretation records
# from a sorted sequence of HorizonInterpretation boundaries.
# =====================================================================

_KIND_UNIT = "osdu:wks:work-product-component--StratigraphicUnitInterpretation:1.3.0"


def _generate_units_from_horizons(
    model: dict,
    partition: str = "data",
) -> dict:
    """Derive StratigraphicUnitInterpretation WPC records from horizon boundaries.

    **Complement-aware**: skips age intervals that already have a real
    StratigraphicUnitInterpretation record in the model.  Only creates
    units for intervals between consecutive horizons that are *missing*.

    Returns:
      {
        "units":     [<OSDU WPC record>, ...],       # new (to be created)
        "stats":     {"horizonCount": N, "unitCount": N,
                      "existingUnits": N, "skippedIntervals": N}
      }
    """
    column = model.get("column") or {}
    col_data = _get_data(column) if isinstance(column, dict) else {}
    col_name = col_data.get("Name") or "Column"

    import re as _re
    col_token = _re.sub(r"[^A-Za-z0-9._-]+", "-", col_name.strip())[:200]
    if not col_token:
        col_token = "Column"

    role_type_id = f"{partition}:reference-data--StratigraphicRoleType:Chronostratigraphic:"

    # ── Inventory existing units (non-synthetic) and their age intervals ──
    existing_intervals: set = set()   # {(older_age, younger_age)} rounded
    existing_unit_count = 0
    for rank in model.get("ranks") or []:
        for unit in rank.get("units") or []:
            if unit.get("_synthetic"):
                continue
            # Use normalized ages so the interval key is always (older, younger)
            # regardless of whether the source was ICS chrono or SMDA litho.
            o = unit.get("olderMa")
            y = unit.get("youngerMa")
            if o is not None and y is not None:
                existing_intervals.add((round(float(o), 4), round(float(y), 4)))
                existing_unit_count += 1

    # ── Collect horizons ──────────────────────────────────────────────
    horizon_tuples: List[tuple] = []  # (age_ma, name, horizon_id_or_none)
    seen_ages: set = set()

    # (a) Gather from horizonTop / horizonBase on every unit
    for rank in model.get("ranks") or []:
        for unit in rank.get("units") or []:
            if unit.get("_synthetic"):
                continue
            for hkey in ("horizonTop", "horizonBase"):
                h = unit.get(hkey)
                if not h or not isinstance(h, dict):
                    continue
                age = h.get("ageMa")
                if age is None or age in seen_ages:
                    continue
                seen_ages.add(age)
                horizon_tuples.append((float(age), h.get("name", f"{age} Ma"), h.get("id")))

    # (b) Fall back: extract distinct ages from unit boundaries (no real horizon records)
    #     Use normalized olderMa/youngerMa so labels are correct regardless
    #     of whether topMa means "older" (ICS) or "younger" (SMDA).
    if not horizon_tuples:
        for rank in model.get("ranks") or []:
            for unit in rank.get("units") or []:
                if unit.get("_synthetic"):
                    continue
                name = unit.get("name") or ""
                for age_key, side in (("olderMa", "base"), ("youngerMa", "top")):
                    age = unit.get(age_key)
                    if age is not None and age not in seen_ages:
                        seen_ages.add(age)
                        label = f"Top {name}" if side == "top" else f"Base {name}"
                        horizon_tuples.append((float(age), label.strip(), None))

    if len(horizon_tuples) < 2:
        return {"units": [], "stats": {
            "horizonCount": len(horizon_tuples), "unitCount": 0,
            "existingUnits": existing_unit_count, "skippedIntervals": 0,
        }}

    # Sort older (larger Ma) → younger (smaller Ma)
    horizon_tuples.sort(key=lambda t: -t[0])

    # ── Generate one unit per consecutive pair (skip existing) ────────
    default_acl = {"viewers": osdu.DEFAULT_VIEWERS, "owners": osdu.DEFAULT_OWNERS}
    default_legal = {
        "legaltags": [osdu.DEFAULT_LEGAL_TAG],
        "otherRelevantDataCountries": osdu.DEFAULT_COUNTRIES,
    }

    units: List[dict] = []
    skipped_intervals = 0

    for i in range(len(horizon_tuples) - 1):
        older_age, older_name, older_hid = horizon_tuples[i]
        younger_age, younger_name, younger_hid = horizon_tuples[i + 1]

        # Skip if this interval already exists as a real unit
        interval_key = (round(older_age, 4), round(younger_age, 4))
        if interval_key in existing_intervals:
            skipped_intervals += 1
            continue

        # Name: use the younger horizon's name with "Top" stripped, or compose from pair
        unit_name = younger_name
        for prefix in ("Top ", "Base "):
            if unit_name.startswith(prefix):
                unit_name = unit_name[len(prefix):]
                break
        if not unit_name:
            unit_name = f"Unit {older_age}-{younger_age} Ma"

        age_tok_older = _age_token(older_age)
        age_tok_younger = _age_token(younger_age)
        uid = f"{partition}:work-product-component--StratigraphicUnitInterpretation:{col_token}-U-{age_tok_older}-{age_tok_younger}Ma:"

        unit_data: Dict[str, Any] = {
            "Name": unit_name,
            "Description": f"Stratigraphic unit from {older_age} Ma to {younger_age} Ma",
            "OlderPossibleAge": older_age,
            "YoungerPossibleAge": younger_age,
            "StratigraphicRoleTypeID": role_type_id,
            "IsDiscoverable": True,
        }
        if older_hid:
            unit_data["ColumnStratigraphicHorizonBaseID"] = older_hid
        if younger_hid:
            unit_data["ColumnStratigraphicHorizonTopID"] = younger_hid

        units.append({
            "id": uid,
            "kind": _KIND_UNIT,
            "acl": default_acl,
            "legal": default_legal,
            "data": unit_data,
        })

    return {
        "units": units,
        "stats": {
            "horizonCount": len(horizon_tuples),
            "unitCount": len(units),
            "existingUnits": existing_unit_count,
            "skippedIntervals": skipped_intervals,
        },
    }


@router.post("/api/strat/generate-units")
async def generate_units(request: Request):
    """Generate StratigraphicUnitInterpretation records from horizon boundaries.

    Body:
    {
      "columnId": "<OSDU StratigraphicColumn record id>",
      "partition": "data",
      "ingest": false   // if true, also PUT the units to OSDU Storage
    }

    Returns the generated units and stats.
    If ingest=true, also sends the unit records to OSDU Storage.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    column_id = (body.get("columnId") or "").strip()
    partition = (body.get("partition") or osdu.DATA_PARTITION_ID or "data").strip()
    do_ingest = body.get("ingest", False)

    if not column_id:
        raise HTTPException(400, "columnId is required")

    # 1) Fetch the column model
    model = await _fetch_column_model(request, column_id)

    # 2) Generate units from horizons
    result = _generate_units_from_horizons(model, partition=partition)
    units = result["units"]

    log.info("[Units] Generated %d units for column %s from %d horizons",
             len(units), column_id, result["stats"]["horizonCount"])

    # 3) Optionally ingest to OSDU Storage
    ingest_result = None
    if do_ingest and units:
        at = _access_token(request)
        base = f"https://{osdu.OSDU_BASE_URL}"
        url = f"{base}/api/storage/v2/records"
        hdr = osdu.headers(at)

        ingest_result = {"created": 0, "errors": []}
        async with osdu.http_client(timeout=60) as client:
            for i in range(0, len(units), 20):
                batch = units[i:i + 20]
                try:
                    r = await client.put(url, headers=hdr, json=batch)
                    if r.status_code < 300:
                        resp = r.json()
                        ingest_result["created"] += resp.get("recordCount", len(batch))
                    else:
                        ingest_result["errors"].append({
                            "batch": i, "httpStatus": r.status_code,
                            "detail": _sanitize(r),
                        })
                except Exception as e:
                    ingest_result["errors"].append({"batch": i, "error": _safe_detail(e)})

    return JSONResponse({
        **result,
        "ingest": ingest_result,
    })


# =====================================================================
# RESQML CONVERSION & RDDMS INGEST
# =====================================================================

# Namespace for deterministic UUID5 generation from OSDU record IDs
_RESQML_NS = _uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


def _det_uuid(seed: str) -> str:
    """Deterministic UUID5 from a seed string."""
    return str(_uuid.uuid5(_RESQML_NS, seed))


def _resqml_citation(title: str) -> dict:
    """Standard RESQML Citation block."""
    return {
        "$type": "eml20.Citation",
        "Title": title,
        "Originator": "ORES Strat Column Converter",
        "Creation": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "Format": "ORES [strat-to-rddms v1.0]",
    }


_CONTENT_TYPE_PREFIX = "application/x-resqml+xml;version=2.0;type="


def _resqml_ref(typ_short: str, uid: str, title: str) -> dict:
    """Build a RESQML DataObjectReference."""
    return {
        "$type": "eml20.DataObjectReference",
        "ContentType": f"{_CONTENT_TYPE_PREFIX}{typ_short}",
        "UUID": uid,
        "Title": title,
    }


def _osdu_column_to_resqml(model: dict) -> Dict[str, List[dict]]:
    """Convert a /api/strat/column.json model to RESQML 2.0.1 objects
    grouped by RDDMS type key.

    Returns a dict:  { "resqml20.obj_X": [obj, ...], ... }
    PUT order should be: features -> unit interpretations -> rank interpretations -> column
    """
    column = model.get("column") or {}
    col_data = (column.get("data") or {}) if isinstance(column, dict) else {}
    col_name = col_data.get("Name") or "Stratigraphic Column"
    col_id = column.get("id") or col_name

    by_type: Dict[str, List[dict]] = {
        "resqml20.obj_OrganizationFeature": [],
        "resqml20.obj_RockVolumeFeature": [],
        "resqml20.obj_BoundaryFeature": [],
        "resqml20.obj_HorizonInterpretation": [],
        "resqml20.obj_StratigraphicUnitInterpretation": [],
        "resqml20.obj_StratigraphicColumnRankInterpretation": [],
        "resqml20.obj_StratigraphicColumn": [],
    }

    # Collect distinct boundary ages across all units for horizon generation
    horizon_age_map: Dict[float, str] = {}  # age -> horizon_uuid
    boundary_feat_map: Dict[float, str] = {}  # age -> boundary_feature_uuid
    age_labels: Dict[float, str] = {}  # age -> display label

    # First pass: collect all boundary ages and labels
    for rank in (model.get("ranks") or []):
        for unit in (rank.get("units") or []):
            if unit.get("_synthetic"):
                continue
            name = unit.get("name") or ""
            top = unit.get("topMa")
            base = unit.get("baseMa")
            # Prefer real horizon data if present
            if unit.get("horizonTop"):
                ht = unit["horizonTop"]
                age = ht.get("ageMa") or base
                if age is not None:
                    age_labels.setdefault(age, ht.get("name") or f"Top {name}")
            elif base is not None:
                age_labels.setdefault(base, f"Top {name}")
            if unit.get("horizonBase"):
                hb = unit["horizonBase"]
                age = hb.get("ageMa") or top
                if age is not None:
                    age_labels.setdefault(age, hb.get("name") or f"Base {name}")
            elif top is not None:
                age_labels.setdefault(top, f"Base {name}")

    # Generate BoundaryFeature + HorizonInterpretation per distinct age
    for age in sorted(age_labels.keys()):
        label = age_labels[age]
        bf_uuid = _det_uuid(f"boundaryfeat:{col_id}:{age}")
        hi_uuid = _det_uuid(f"horizon:{col_id}:{age}")
        boundary_feat_map[age] = bf_uuid
        horizon_age_map[age] = hi_uuid

        by_type["resqml20.obj_BoundaryFeature"].append({
            "$type": "resqml20.obj_BoundaryFeature",
            "SchemaVersion": "2.0",
            "Uuid": bf_uuid,
            "Citation": _resqml_citation(label),
        })
        by_type["resqml20.obj_HorizonInterpretation"].append({
            "$type": "resqml20.obj_HorizonInterpretation",
            "SchemaVersion": "2.0",
            "Uuid": hi_uuid,
            "Citation": _resqml_citation(label),
            "Domain": "depth",
            "InterpretedFeature": _resqml_ref(
                "obj_BoundaryFeature", bf_uuid, label,
            ),
            "ExtraMetadata": [
                {"Name": "Age_Ma", "Value": str(age)},
            ],
        })

    rank_refs: List[dict] = []

    for ri, rank in enumerate(model.get("ranks") or []):
        rank_name = rank.get("rankName") or f"Rank_{ri}"
        rank_uuid = _det_uuid(f"rank:{col_id}:{rank_name}")
        rank_feat_uuid = _det_uuid(f"rankfeat:{col_id}:{rank_name}")

        # OrganizationFeature for this rank
        by_type["resqml20.obj_OrganizationFeature"].append({
            "$type": "resqml20.obj_OrganizationFeature",
            "SchemaVersion": "2.0",
            "Uuid": rank_feat_uuid,
            "Citation": _resqml_citation(rank_name),
            "OrganizationKind": "stratigraphic",
        })

        unit_refs: List[dict] = []

        for ui, unit in enumerate(rank.get("units") or []):
            if unit.get("_synthetic"):
                continue  # skip gap-fill placeholders

            name = unit.get("name") or f"Unit_{ui}"
            unit_uuid = _det_uuid(f"unit:{col_id}:{rank_name}:{name}:{ui}")
            feat_uuid = _det_uuid(f"feat:{col_id}:{rank_name}:{name}:{ui}")

            # RockVolumeFeature (the feature this unit interprets)
            by_type["resqml20.obj_RockVolumeFeature"].append({
                "$type": "resqml20.obj_RockVolumeFeature",
                "SchemaVersion": "2.0",
                "Uuid": feat_uuid,
                "Citation": _resqml_citation(name),
            })

            # StratigraphicUnitInterpretation
            unit_obj: Dict[str, Any] = {
                "$type": "resqml20.obj_StratigraphicUnitInterpretation",
                "SchemaVersion": "2.0",
                "Uuid": unit_uuid,
                "Citation": _resqml_citation(name),
                "Domain": "depth",
                "InterpretedFeature": _resqml_ref(
                    "obj_RockVolumeFeature", feat_uuid, name,
                ),
            }

            # Store ages and colour as ExtraMetadata (RESQML extension point)
            extra: List[dict] = []
            if unit.get("topMa") is not None:
                extra.append({"Name": "OlderPossibleAge_Ma", "Value": str(unit["topMa"])})
            if unit.get("baseMa") is not None:
                extra.append({"Name": "YoungerPossibleAge_Ma", "Value": str(unit["baseMa"])})
            if unit.get("color"):
                extra.append({"Name": "Colour", "Value": unit["color"]})
            if unit.get("code"):
                extra.append({"Name": "ChronoCode", "Value": unit["code"]})
            if extra:
                unit_obj["ExtraMetadata"] = extra

            # Link unit to horizon boundaries (top/base) if age-derived horizons exist
            top_hz_uuid = horizon_age_map.get(unit.get("baseMa"))  # younger boundary = top horizon
            base_hz_uuid = horizon_age_map.get(unit.get("topMa"))  # older boundary = base horizon
            if top_hz_uuid:
                unit_obj["TopBoundary"] = _resqml_ref(
                    "obj_HorizonInterpretation", top_hz_uuid,
                    age_labels.get(unit.get("baseMa"), ""),
                )
            if base_hz_uuid:
                unit_obj["BaseBoundary"] = _resqml_ref(
                    "obj_HorizonInterpretation", base_hz_uuid,
                    age_labels.get(unit.get("topMa"), ""),
                )

            by_type["resqml20.obj_StratigraphicUnitInterpretation"].append(unit_obj)
            unit_refs.append(_resqml_ref(
                "obj_StratigraphicUnitInterpretation", unit_uuid, name,
            ))

        # StratigraphicColumnRankInterpretation
        rank_obj: Dict[str, Any] = {
            "$type": "resqml20.obj_StratigraphicColumnRankInterpretation",
            "SchemaVersion": "2.0",
            "Uuid": rank_uuid,
            "Citation": _resqml_citation(rank_name),
            "Domain": "depth",
            "OrderingCriteria": "olderToYounger",
            "RankInStratigraphicColumn": ri,
            "InterpretedFeature": _resqml_ref(
                "obj_OrganizationFeature", rank_feat_uuid, rank_name,
            ),
            "StratigraphicUnits": unit_refs,
        }
        by_type["resqml20.obj_StratigraphicColumnRankInterpretation"].append(rank_obj)
        rank_refs.append(_resqml_ref(
            "obj_StratigraphicColumnRankInterpretation", rank_uuid, rank_name,
        ))

    # StratigraphicColumn
    col_uuid = _det_uuid(f"col:{col_id}")
    by_type["resqml20.obj_StratigraphicColumn"].append({
        "$type": "resqml20.obj_StratigraphicColumn",
        "SchemaVersion": "2.0",
        "Uuid": col_uuid,
        "Citation": _resqml_citation(col_name),
        "Ranks": rank_refs,
    })

    # Remove empty type buckets
    return {k: v for k, v in by_type.items() if v}


def _stratcol_to_model(col) -> dict:
    """Convert a StratColumn object (from stratcolumnhandler) into the model
    format expected by _osdu_column_to_resqml().

    This lets us reuse the same RESQML converter for SMDA-sourced columns
    that haven't been ingested to OSDU yet.
    """
    ranks_model = []
    for ri, r in enumerate(col.ranks):
        units_model = []
        if r.kind == "litho":
            for u in r.units:
                units_model.append({
                    "name": u.name,
                    "topMa": u.top_age_ma,
                    "baseMa": u.base_age_ma,
                    "color": u.color_html,
                    "code": None,
                    "parentName": u.parent_name or "",
                })
        elif r.kind == "chrono":
            # Chrono names are SRNs or display names - include them
            # so RESQML conversion can create unit objects for them
            for cn in r.chrono_names:
                name = cn.split(":")[-2] if cn.endswith(":") else cn
                units_model.append({
                    "name": name,
                    "topMa": None,
                    "baseMa": None,
                    "color": None,
                    "code": None,
                })
        ranks_model.append({
            "rankName": r.name,
            "isChrono": r.kind == "chrono",
            "unitCount": len(units_model),
            "units": units_model,
        })
    return {
        "column": {"id": col.name, "data": {"Name": col.name}},
        "ranks": ranks_model,
    }


async def _push_resqml_to_rddms(
    at: str,
    resqml_by_type: Dict[str, List[dict]],
    dataspace: str,
    create_ds: bool,
    column_name: str,
) -> dict:
    """Shared helper: optionally create dataspace, PUT RESQML objects via transaction, return result dict.

    Uses the RDDMS v2 transactional write flow:
    1. POST /dataspaces/{ds}/transactions → txId
    2. PUT  /dataspaces/{ds}/resources?transactionId={txId}  (body = all objects)
    3. PUT  /dataspaces/{ds}/transactions/{txId}  (commit)
    """
    total_objects = sum(len(v) for v in resqml_by_type.values())

    if total_objects == 0:
        raise HTTPException(422, "No RESQML objects generated - column may be empty")

    # Optionally create the dataspace (check existence first to avoid
    # 401 errors when the user has write-access but not PutDataspaces admin).
    if create_ds:
        ds_exists = False
        try:
            existing = await osdu.list_dataspaces(at)
            ds_exists = any(
                d.get("Path") == dataspace or d.get("DataspaceId") == dataspace
                for d in existing
            )
        except Exception as e:
            log.warning("[RDDMS] Could not list dataspaces: %s", e)

        if ds_exists:
            log.info("[RDDMS] Dataspace %s already exists - skipping creation", dataspace)
        else:
            log.info("[RDDMS] Creating dataspace %s", dataspace)
            try:
                await osdu.create_dataspace(
                    at, dataspace,
                    legal_tag=osdu.DEFAULT_LEGAL_TAG,
                    owners=osdu.DEFAULT_OWNERS,
                    viewers=osdu.DEFAULT_VIEWERS,
                    countries=osdu.DEFAULT_COUNTRIES,
                )
            except httpx.HTTPStatusError as e:
                if e.response.status_code in (400, 409):
                    log.info("[RDDMS] Dataspace %s already exists (%s)", dataspace, e.response.status_code)
                elif e.response.status_code in (401, 403):
                    log.warning(
                        "[RDDMS] No PutDataspaces permission (%s) - "
                        "continuing (dataspace may already exist)",
                        e.response.status_code,
                    )
                else:
                    raise HTTPException(
                        502,
                        f"Dataspace creation failed: {e.response.status_code} "
                        f"{e.response.text[:500]}",
                    )

    # Flatten all objects into a single list (RDDMS accepts mixed types)
    put_order = [
        "resqml20.obj_RockVolumeFeature",
        "resqml20.obj_BoundaryFeature",
        "resqml20.obj_OrganizationFeature",
        "resqml20.obj_HorizonInterpretation",
        "resqml20.obj_StratigraphicUnitInterpretation",
        "resqml20.obj_StratigraphicColumnRankInterpretation",
        "resqml20.obj_StratigraphicColumn",
    ]
    all_objects: List[dict] = []
    type_counts: Dict[str, int] = {}
    for typ in put_order:
        objects = resqml_by_type.get(typ, [])
        if objects:
            all_objects.extend(objects)
            type_counts[typ] = len(objects)

    errors: List[dict] = []
    tx_id: Optional[str] = None

    try:
        # 1) Begin transaction
        tx_id = await osdu.begin_transaction(at, dataspace)
        log.info("[RDDMS] Transaction on %s: PUT %d objects (tx=%s)",
                 dataspace, len(all_objects), tx_id)

        # 2) PUT all objects in one call within the transaction
        resp = await osdu.put_resources(at, dataspace, all_objects, tx_id)

        # 3) Commit the transaction
        await osdu.commit_transaction(at, dataspace, tx_id)
        log.info("[RDDMS] Transaction %s committed - %d objects pushed to %s",
                 tx_id, len(all_objects), dataspace)

    except httpx.HTTPStatusError as e:
        err = {
            "httpStatus": e.response.status_code,
            "detail": _sanitize(e.response),
        }
        errors.append(err)
        log.error("[RDDMS] Transaction write failed: %s", err)
        # Attempt rollback
        if tx_id:
            try:
                await osdu.cancel_transaction(at, dataspace, tx_id)
                log.info("[RDDMS] Transaction %s rolled back", tx_id)
            except Exception:
                log.warning("[RDDMS] Rollback failed for tx %s", tx_id)
    except Exception as e:
        errors.append({"error": _safe_detail(e)})
        log.error("[RDDMS] Transaction write exception: %s", e)
        if tx_id:
            try:
                await osdu.cancel_transaction(at, dataspace, tx_id)
            except Exception:
                pass

    pushed_count = total_objects if not errors else 0
    failed_count = 0 if not errors else total_objects
    status = "ok" if not errors else "error"

    return {
        "status": status,
        "dataspace": dataspace,
        "columnName": column_name,
        "totalObjects": total_objects,
        "totalPushed": pushed_count,
        "totalFailed": failed_count,
        "types": type_counts if not errors else {},
        "errors": errors,
    }


async def _fetch_column_model(request: Request, column_id: str) -> dict:
    """Fetch a strat column model (reuses the same logic as column.json)."""
    col = await _osdu_get_record(request, column_id)
    if not col:
        raise HTTPException(404, "Column not found")

    dcol = _get_data(col)
    rank_ids = _ids(
        dcol.get("StratigraphicColumnRankInterpretationSet")
        or dcol.get("RankInterpretationSet")
        or []
    )
    if not rank_ids:
        return {"column": col, "ranks": []}

    ranks_by_id = await _storage_fetch_many(request, rank_ids)

    unit_ids_all: List[str] = []
    chrono_ids_all: List[str] = []
    for rid in rank_ids:
        rk = ranks_by_id.get(rid) or {}
        drk = _get_data(rk)
        chrono_ids_all.extend(_ids(drk.get("ChronoStratigraphySet") or drk.get("ChronostratigraphySet")))
        unit_ids_all.extend(_ids(drk.get("StratigraphicUnitInterpretationSet")))

    units_by_id = await _storage_fetch_many(request, unit_ids_all) if unit_ids_all else {}
    horizon_ids_all: List[str] = []
    for u in units_by_id.values():
        ud = _get_data(u)
        cid = _as_id(ud.get("ChronoStratigraphyID") or ud.get("ChronostratigraphyID") or "")
        if cid:
            chrono_ids_all.append(cid)
        for hkey in ("ColumnStratigraphicHorizonTopID", "ColumnStratigraphicHorizonBaseID"):
            hid = _as_id(ud.get(hkey) or "")
            if hid:
                horizon_ids_all.append(hid)

    chron_by_id = await _storage_fetch_many(request, chrono_ids_all) if chrono_ids_all else {}
    horizons_by_id = await _storage_fetch_many(request, horizon_ids_all) if horizon_ids_all else {}

    def _age_key(u):
        # Use normalized ages (convention-agnostic) - handles both ICS (topMa=older)
        # and SMDA (topMa=younger) correctly.
        older = u.get("olderMa")
        younger = u.get("youngerMa")
        if older is not None and younger is not None:
            return (-older, younger)
        top = u.get("topMa")
        base = u.get("baseMa")
        if top is not None and base is not None:
            return (-max(top, base), min(top, base))
        return (float("inf"), float("inf"))

    ranks_model: List[dict] = []
    for rid in rank_ids:
        rk = ranks_by_id.get(rid)
        if not rk:
            continue
        drk = _get_data(rk)
        rank_name = drk.get("Name") or "Unspecified"
        chrono_ids = _ids(drk.get("ChronoStratigraphySet") or drk.get("ChronostratigraphySet"))
        unit_ids = _ids(drk.get("StratigraphicUnitInterpretationSet"))
        is_chrono = bool(chrono_ids) and not bool(unit_ids)

        units_model: List[dict] = []
        for cid in chrono_ids:
            crec = chron_by_id.get(cid)
            if crec:
                ff = _flat_unit_fields(None, crec, horizons_by_id)
                units_model.append({"unit": {}, "chrono": crec, **ff})
        for uid in unit_ids:
            urec = units_by_id.get(uid)
            if not urec:
                continue
            ud = _get_data(urec)
            cid_ref = _as_id(ud.get("ChronoStratigraphyID") or "")
            cobj = chron_by_id.get(cid_ref) if cid_ref else {}
            ff = _flat_unit_fields(urec, cobj, horizons_by_id)
            units_model.append({"unit": urec, "chrono": cobj, **ff})

        units_model.sort(key=_age_key)
        ranks_model.append({
            "rankName": rank_name,
            "isChrono": is_chrono,
            "rank": rk,
            "unitCount": len(units_model),
            "units": units_model,
        })

    return {"column": col, "ranks": ranks_model}


@router.post("/api/strat/ingest/rddms")
async def ingest_strat_to_rddms(request: Request):
    """Fetch a StratigraphicColumn from OSDU, convert to RESQML 2.0.1 objects,
    and PUT them into a Reservoir DDMS v2 dataspace.

    Body:
    {
      "columnId": "<OSDU StratigraphicColumn record id>",
      "dataspace": "maap/strat",
      "createDataspace": true   // optional, creates the dataspace first
    }
    """
    at = _access_token(request)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    column_id = (body.get("columnId") or "").strip()
    dataspace = (body.get("dataspace") or "").strip()
    create_ds = body.get("createDataspace", False)

    if not column_id:
        raise HTTPException(400, "columnId is required")
    if not dataspace:
        raise HTTPException(400, "dataspace is required")

    # 1) Fetch the column model from OSDU
    model = await _fetch_column_model(request, column_id)

    # 2) Convert to RESQML 2.0.1 objects
    resqml_by_type = _osdu_column_to_resqml(model)
    total_objs = sum(len(v) for v in resqml_by_type.values())
    log.info("[RDDMS] %s \u2192 %d RESQML objects (%d types) \u2192 %s",
             column_id, total_objs, len(resqml_by_type), dataspace)

    # 3) Push to RDDMS (create dataspace + PUT objects)
    col_name = ((model.get("column") or {}).get("data") or {}).get("Name", "")
    result = await _push_resqml_to_rddms(at, resqml_by_type, dataspace, create_ds, col_name)
    return JSONResponse(result)


@router.post("/api/strat/smda/push-rddms")
async def smda_push_to_rddms(request: Request):
    """Fetch a strat column from SMDA, convert to RESQML 2.0.1, and push
    directly to a Reservoir DDMS v2 dataspace.

    Body:
    {
      "column": "NCS Lithostratigraphy",
      "smdaUrl": "https://api.gateway.equinor.com",   // optional
      "dataspace": "maap/strat",
      "createDataspace": true   // optional
    }
    """
    if _StratColumn is None:
        raise HTTPException(500, "stratcolumnhandler not available")

    at = _access_token(request)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    column_name = (body.get("column") or "").strip()
    smda_url = (body.get("smdaUrl") or "https://api.gateway.equinor.com").strip()
    dataspace = (body.get("dataspace") or "").strip()
    create_ds = body.get("createDataspace", False)

    if not column_name:
        raise HTTPException(400, "column is required")
    if not dataspace:
        raise HTTPException(400, "dataspace is required")

    # 1) Get SMDA auth and fetch column
    auth_kw = await _smda_auth(request)

    log.info("[SMDA→RDDMS] Fetching '%s' from SMDA", column_name)
    try:
        col = _StratColumn.from_smda_api(
            column_name,
            base_url=smda_url,
            **auth_kw,
            verify_ssl=False,
        )
    except Exception as e:
        log.warning("[SMDA→RDDMS] Fetch failed for '%s': %s", column_name, e)
        raise HTTPException(422, f"SMDA fetch error: {e}")

    # 2) Convert StratColumn → model → RESQML
    model = _stratcol_to_model(col)
    resqml_by_type = _osdu_column_to_resqml(model)
    total_objs = sum(len(v) for v in resqml_by_type.values())
    log.info("[SMDA→RDDMS] '%s' → %d RESQML objects → %s", col.name, total_objs, dataspace)

    # 3) Push to RDDMS
    result = await _push_resqml_to_rddms(at, resqml_by_type, dataspace, create_ds, col.name)
    return JSONResponse(result)


@router.get("/api/strat/dataspaces.json")
async def list_strat_dataspaces(request: Request):
    """List available RDDMS dataspaces (for the UI picker)."""
    at = _access_token(request)
    try:
        ds = await osdu.list_dataspaces(at)
        items = []
        if isinstance(ds, list):
            for d in ds:
                if isinstance(d, dict):
                    # Try multiple possible key names
                    path = (d.get("Path") or d.get("path")
                            or d.get("DataspaceId") or d.get("dataspaceId")
                            or d.get("uri") or d.get("name") or "")
                    if path:
                        items.append({"path": path, "label": path})
                elif isinstance(d, str):
                    items.append({"path": d, "label": d})
            if not items and ds:
                # Log first element to understand the format
                log.warning("[RDDMS] Could not parse dataspace entries. First: %s",
                            str(ds[0])[:500])
        elif isinstance(ds, dict):
            # Maybe the response is wrapped
            for key in ("value", "dataspaces", "items", "data"):
                if key in ds and isinstance(ds[key], list):
                    for d in ds[key]:
                        path = (d.get("Path") or d.get("path") or str(d)) if isinstance(d, dict) else str(d)
                        if path:
                            items.append({"path": path, "label": path})
                    break
        return JSONResponse({"dataspaces": items})
    except Exception as e:
        log.warning("[RDDMS] List dataspaces failed: %s", e)
        return JSONResponse({"dataspaces": [], "error": _safe_detail(e)})


# =====================================================================
# RDDMS READ-BACK  (JSON)
# =====================================================================

@router.get("/api/strat/rddms/resources.json")
async def rddms_list_resources(
    request: Request,
    dataspace: str = Query(..., description="Dataspace path, e.g. maap/strat"),
):
    """List all resource types and their objects in an RDDMS dataspace."""
    at = _access_token(request)
    ds_enc = urllib.parse.quote(dataspace.strip(), safe="")
    try:
        types = await osdu.list_types(at, ds_enc)
    except Exception as e:
        raise HTTPException(502, f"list_types failed: {e}")

    result: List[dict] = []
    for t in (types if isinstance(types, list) else []):
        rtype = t.get("name", "")
        if not rtype:
            continue
        try:
            resources = await osdu.list_resources(at, ds_enc, rtype)
            for res in resources:
                result.append({
                    "type": rtype,
                    "uri": res.get("uri", ""),
                    "name": res.get("name", "(unnamed)"),
                })
        except Exception:
            pass

    return JSONResponse({"dataspace": dataspace, "resources": result, "count": len(result)})


@router.get("/api/strat/rddms/resource.json")
async def rddms_get_resource(
    request: Request,
    dataspace: str = Query(..., description="Dataspace path, e.g. maap/strat"),
    type: str = Query(..., description="RESQML type, e.g. resqml20.obj_StratigraphicColumn"),
    uuid: str = Query(..., description="Object UUID"),
):
    """Fetch a single RESQML object from RDDMS as JSON.

    Uses ``GET /dataspaces/{ds}/resources/{type}/{uuid}?$format=json``.
    """
    at = _access_token(request)
    ds_enc = urllib.parse.quote(dataspace.strip(), safe="")
    try:
        obj = await osdu.get_resource(at, ds_enc, type.strip(), uuid.strip())
    except httpx.HTTPStatusError as e:
        raise HTTPException(e.response.status_code,
                            f"RDDMS GET failed: {e.response.text[:500]}")
    return JSONResponse(obj)


@router.post("/api/strat/rddms/verify")
async def rddms_verify_column(request: Request):
    """Push a strat column to RDDMS then immediately fetch-back and verify.

    Body:
    {
      "columnId": "<OSDU record id>",   // option A: from OSDU
      "column": "<SMDA column name>",   // option B: from SMDA
      "smdaUrl": "...",                 // optional for option B
      "dataspace": "maap/strat",
      "createDataspace": false
    }

    Returns the push result augmented with a ``verification`` object
    containing per-object match status.
    """
    at = _access_token(request)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    dataspace = (body.get("dataspace") or "").strip()
    if not dataspace:
        raise HTTPException(400, "dataspace is required")

    create_ds = body.get("createDataspace", False)
    column_id = (body.get("columnId") or "").strip()
    column_name_smda = (body.get("column") or "").strip()

    # ── Build RESQML objects (same as the push endpoints) ──
    if column_id:
        model = await _fetch_column_model(request, column_id)
        col_name = ((model.get("column") or {}).get("data") or {}).get("Name", "")
        resqml_by_type = _osdu_column_to_resqml(model)
    elif column_name_smda:
        if _StratColumn is None:
            raise HTTPException(500, "stratcolumnhandler not available")
        smda_url = (body.get("smdaUrl") or "https://api.gateway.equinor.com").strip()
        auth_kw = await _smda_auth(request)
        try:
            col = _StratColumn.from_smda_api(column_name_smda, base_url=smda_url,
                                             **auth_kw, verify_ssl=False)
        except Exception as e:
            raise HTTPException(422, f"SMDA fetch error: {e}")
        model = _stratcol_to_model(col)
        col_name = col.name
        resqml_by_type = _osdu_column_to_resqml(model)
    else:
        raise HTTPException(400, "columnId or column (SMDA name) is required")

    # ── Push ──
    push_result = await _push_resqml_to_rddms(
        at, resqml_by_type, dataspace, create_ds, col_name)

    if push_result.get("status") != "ok":
        push_result["verification"] = {"status": "skipped", "reason": "push failed"}
        return JSONResponse(push_result)

    # ── Fetch-back & verify ──
    ds_enc = urllib.parse.quote(dataspace, safe="")
    verification: List[dict] = []
    all_ok = True

    for typ in [
        "resqml20.obj_RockVolumeFeature",
        "resqml20.obj_OrganizationFeature",
        "resqml20.obj_StratigraphicUnitInterpretation",
        "resqml20.obj_StratigraphicColumnRankInterpretation",
        "resqml20.obj_StratigraphicColumn",
    ]:
        for sent_obj in resqml_by_type.get(typ, []):
            uid = sent_obj["Uuid"]
            title = (sent_obj.get("Citation") or {}).get("Title", "?")
            entry: Dict[str, Any] = {"type": typ, "uuid": uid, "title": title}
            try:
                fetched = await osdu.get_resource(at, ds_enc, typ, uid)
                if isinstance(fetched, list):
                    fetched = fetched[0] if fetched else {}
                # Compare key fields
                mismatches: List[str] = []
                for field in ("$type", "Uuid", "SchemaVersion"):
                    if str(sent_obj.get(field)) != str(fetched.get(field)):
                        mismatches.append(f"{field}: sent={sent_obj.get(field)!r} got={fetched.get(field)!r}")
                s_cit = sent_obj.get("Citation") or {}
                r_cit = fetched.get("Citation") or {}
                for cf in ("Title", "Originator", "Format"):
                    if s_cit.get(cf) != r_cit.get(cf):
                        mismatches.append(f"Citation.{cf}: sent={s_cit.get(cf)!r} got={r_cit.get(cf)!r}")
                # ExtraMetadata count
                s_em = sent_obj.get("ExtraMetadata") or []
                r_em = fetched.get("ExtraMetadata") or []
                if len(s_em) != len(r_em):
                    mismatches.append(f"ExtraMetadata count: sent={len(s_em)} got={len(r_em)}")

                entry["match"] = len(mismatches) == 0
                if mismatches:
                    entry["mismatches"] = mismatches
                    all_ok = False
            except Exception as e:
                entry["match"] = False
                entry["error"] = str(e)
                all_ok = False
            verification.append(entry)

    push_result["verification"] = {
        "status": "ok" if all_ok else "mismatches",
        "checked": len(verification),
        "passed": sum(1 for v in verification if v.get("match")),
        "failed": sum(1 for v in verification if not v.get("match")),
        "objects": verification,
    }
    return JSONResponse(push_result)