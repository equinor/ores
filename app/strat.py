
from __future__ import annotations
import asyncio
import logging
import os
import re
import sys
import urllib.parse
from typing import Any, Dict, List
import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from . import osdu

log = logging.getLogger("strat")

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
        return x.strip()
    if isinstance(x, dict):
        s = x.get("id") or x.get("recordId") or x.get("$ref") or ""
        return s.strip()
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

# Known geological root names (top-level eonothems) — used to detect
# scheme-prefixed chrono codes like "GTS2020.Phanerozoic.Paleozoic.Cambrian"
_CHRONO_ROOTS = {"Phanerozoic", "Proterozoic", "Archean", "Hadean", "Precambrian"}

def _chrono_code_for(um: dict) -> str:
    """
    Return a dot-separated hierarchy code for decomposition.
    Priority:
      1) unit's ChronoStratigraphyID SRN path — always a full hierarchical path
      2) chrono record data.Code — may be a short name (fallback)
    Scheme prefixes (GTS2020, Harland1989, …) are stripped so the result
    always starts with a geological root like "Phanerozoic".
    """
    # Source 1 (preferred): unit's ChronoStratigraphyID  →  SRN path
    # This is ALWAYS a full hierarchical path, unlike data.Code which can be
    # a short name ("Cambrian") instead of the full path
    # ("Phanerozoic.Paleozoic.Cambrian").
    udata = _get_data(um.get("unit") or {})
    cid = udata.get("ChronoStratigraphyID") or udata.get("ChronostratigraphyID") or ""
    if cid:
        # SRN: "dev:reference-data--ChronoStratigraphy:SchemeName.Path.Hierarchy:"
        segs = cid.split(":")
        for i, s in enumerate(segs):
            if "ChronoStratigraphy" in s and i + 1 < len(segs) and segs[i + 1]:
                raw = segs[i + 1]
                # Strip scheme prefix (e.g. "GTS2020.Phanerozoic…" → "Phanerozoic…")
                parts = raw.split(".")
                if parts and parts[0] not in _CHRONO_ROOTS and len(parts) > 1:
                    return ".".join(parts[1:])
                return raw

    # Source 2 (fallback): attached chrono record data.Code
    # Used for rank-level chrono items (no unit object) or when SRN is absent.
    cdata = _get_data(um.get("chrono") or {})
    return cdata.get("Code") or ""

def _chrono_depth(code: str) -> int:
    """
    Hierarchical depth from a (scheme-stripped) chrono code path.
    "Phanerozoic" → 0  (Eonothem)
    "Phanerozoic.Paleozoic" → 1  (Erathem)
    "Phanerozoic.Paleozoic.Cambrian" → 2  (System)
    """
    parts = [p for p in code.split(".") if p]
    if not parts:
        return -1
    return len(parts) - 1

@router.get("/strat", response_class=HTMLResponse)
async def strat_page(request: Request):
    return templates.TemplateResponse("strat.html", {"request": request})

@router.get("/api/strat/record.json")
async def strat_debug_record(request: Request, id: str = Query(...)):
    """Debug: fetch a single OSDU record and return its raw JSON + HTTP status."""
    at = _access_token(request)
    rid = id.strip()
    base = f"https://{osdu.OSDU_BASE_URL}/api/storage/v2/records"
    url_encoded = f"{base}/{urllib.parse.quote(rid, safe='')}"
    url_plain = f"{base}/{rid}"
    hdr = osdu.headers(at)
    results = {}
    async with httpx.AsyncClient(timeout=30) as client:
        # Try encoded first
        r1 = await client.get(url_encoded, headers=hdr)
        results["encoded_url"] = url_encoded
        results["encoded_status"] = r1.status_code
        if r1.status_code == 200:
            results["record"] = r1.json()
        else:
            # Try unencoded as fallback
            try:
                r2 = await client.get(url_plain, headers=hdr)
                results["plain_url"] = url_plain
                results["plain_status"] = r2.status_code
                if r2.status_code == 200:
                    results["record"] = r2.json()
            except Exception as e:
                results["plain_error"] = str(e)
    return JSONResponse(results)

@router.get("/api/strat/search.json")
async def strat_search(request: Request,
                       q: str = Query("*"),
                       limit: int = Query(100, ge=1, le=200)):
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


async def _storage_fetch_many(request: Request, ids: List[str]) -> Dict[str, dict]:
    """
    Batch-fetch OSDU records.
    Fast path: POST /api/storage/v2/query/records:batch (20 IDs per call).
    Fallback:  parallel GET /api/storage/v2/records/{id} (bounded concurrency).
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
                # OSDU refs often end with ':' (latest version); the stored id
                # may or may not include it.  Try the opposite variant.
                alt = rid.rstrip(":") if rid.endswith(":") else (rid + ":")
                url2 = f"{base}/records/{urllib.parse.quote(alt, safe='')}"
                r2 = await client.get(url2, headers=hdr)
                if r2.status_code == 200:
                    body = r2.json() or {}
                    results[rid] = body       # keyed by original id
                    results[alt] = body       # keyed by canonical id
                else:
                    results[rid] = {}
            else:
                r.raise_for_status()

    def _alias_colon_variants() -> None:
        """
        OSDU references often end with ':' (latest-version marker), but the
        stored id may or may not include it.  After any fetch round, create
        aliases so callers find the record regardless of which form they use.
        """
        for key in list(results.keys()):
            body = results[key]
            if not body:          # skip empty / 404 placeholder
                continue
            stripped = key.rstrip(":")
            if stripped != key:
                results.setdefault(stripped, body)
            else:
                results.setdefault(key + ":", body)

    # Use HTTP/2 when the h2 package is available, fall back to HTTP/1.1
    try:
        _client_kw = {"timeout": 30, "http2": True}
        httpx.AsyncClient(**_client_kw)  # probe
    except Exception:
        _client_kw = {"timeout": 30}
    async with httpx.AsyncClient(**_client_kw) as client:
        # Try batch first (20 per chunk)
        chunks = [uniq[i:i+20] for i in range(0, len(uniq), 20)]
        use_batch = True
        try:
            await asyncio.gather(*(post_batch(client, c) for c in chunks))
            _alias_colon_variants()
        except FileNotFoundError:
            use_batch = False

        # Identify IDs still missing after batch (or if batch unavailable)
        still_missing = [rid for rid in uniq
                         if rid not in results or not results[rid]]
        if still_missing:
            # For each missing id, also try the colon-toggled variant
            alts: List[str] = []
            for rid in still_missing:
                alt = rid.rstrip(":") if rid.endswith(":") else (rid + ":")
                if alt not in results or not results[alt]:
                    alts.append(alt)

            to_retry = list(dict.fromkeys(still_missing + alts))  # dedup, order-preserving

            if use_batch and to_retry:
                # retry via batch with alternate ids
                retry_chunks = [to_retry[i:i+20] for i in range(0, len(to_retry), 20)]
                try:
                    await asyncio.gather(*(post_batch(client, c) for c in retry_chunks))
                    _alias_colon_variants()
                except FileNotFoundError:
                    use_batch = False

            # Final fallback: parallel GETs for anything still missing
            final_missing = [rid for rid in uniq
                             if rid not in results or not results[rid]]
            if final_missing:
                sem = asyncio.Semaphore(12)
                await asyncio.gather(*(get_one(client, rid, sem) for rid in final_missing))
                _alias_colon_variants()

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
    print(f"[strat] Column {id} \u2014 {len(rank_ids)} rank IDs: {rank_ids}", file=sys.stderr, flush=True)

    # 1) fetch ranks
    ranks_by_id = await _storage_fetch_many(request, rank_ids)
    print(f"[strat] Fetched {len(ranks_by_id)} / {len(rank_ids)} ranks", file=sys.stderr, flush=True)
    missing_rank_ids = [rid for rid in rank_ids if rid not in ranks_by_id or not _get_data(ranks_by_id[rid])]
    if missing_rank_ids:
        print(f"[strat]   MISSING ranks (404): {missing_rank_ids}", file=sys.stderr, flush=True)

    # 2) discover all unit ids and chrono ids (from both rank-level sets and unit-level links)
    unit_ids_all: List[str] = []
    chrono_ids_all: List[str] = []

    for rid in rank_ids:
        rk = ranks_by_id.get(rid) or {}
        drk = _get_data(rk)
        rk_name = drk.get("Name", "?")
        unit_set = _ids(drk.get("StratigraphicUnitInterpretationSet"))
        chrono_set = _ids(drk.get("ChronoStratigraphySet") or drk.get("ChronostratigraphySet"))
        # Also check for HorizonInterpretation sets on the rank itself
        horizon_set = _ids(
            drk.get("ColumnStratigraphicHorizonSet")
            or drk.get("StratigraphicHorizonInterpretationSet")
            or drk.get("HorizonInterpretationSet")
        )
        print(
            f"[strat]   Rank {rid[-8:]} '{rk_name}': {len(unit_set)} units, {len(chrono_set)} chrono, {len(horizon_set)} horizons, keys={list(drk.keys())[:15]}",
            file=sys.stderr, flush=True
        )
        unit_ids_all.extend(unit_set)
        chrono_ids_all.extend(chrono_set)

    # 3) fetch units, then scan for ChronoStratigraphyID links on each unit
    units_by_id = await _storage_fetch_many(request, unit_ids_all) if unit_ids_all else {}
    print(f"[strat] Fetched {len(units_by_id)} units, {len(chrono_ids_all)} chrono IDs so far", file=sys.stderr, flush=True)
    for u in units_by_id.values():
        ud = _get_data(u)
        # follow the unit-level chrono pointer if present (tenant-specific property name)
        cid = ud.get("ChronoStratigraphyID") or ud.get("ChronostratigraphyID")
        if cid:
            chrono_ids_all.append(cid)

    # 4) fetch all chrono records (deduped inside _storage_fetch_many)
    chron_by_id = await _storage_fetch_many(request, chrono_ids_all) if chrono_ids_all else {}

    # 4b) fetch horizon interpretations linked from units
    horizon_ids_all: List[str] = []
    for u in units_by_id.values():
        ud = _get_data(u)
        for hkey in ("ColumnStratigraphicHorizonTopID", "ColumnStratigraphicHorizonBaseID"):
            hid = ud.get(hkey) or ""
            if hid:
                horizon_ids_all.append(hid)
    horizons_by_id = await _storage_fetch_many(request, horizon_ids_all) if horizon_ids_all else {}

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
                entry = {"unit": None, "chrono": crec, "horizonTop": None, "horizonBase": None}
                entry["chronoCode"] = _chrono_code_for(entry)
                units_model.append(entry)

        # B) unit interpretations (attach chrono + horizon records)
        seen_uids: set = set()
        for uid in _ids(drk.get("StratigraphicUnitInterpretationSet")):
            if uid in seen_uids:
                continue
            seen_uids.add(uid)
            urec = units_by_id.get(uid)
            if urec:
                ud = _get_data(urec)
                cid = ud.get("ChronoStratigraphyID") or ud.get("ChronostratigraphyID")
                cobj = chron_by_id.get(cid) if cid else None
                # Treat empty records (404 → {}) as absent
                if cobj is not None and not _get_data(cobj):
                    cobj = None
                htid = ud.get("ColumnStratigraphicHorizonTopID") or ""
                hbid = ud.get("ColumnStratigraphicHorizonBaseID") or ""
                htobj = horizons_by_id.get(htid) if htid else None
                hbobj = horizons_by_id.get(hbid) if hbid else None
                entry = {"unit": urec, "chrono": cobj, "horizonTop": htobj, "horizonBase": hbobj}
                entry["chronoCode"] = _chrono_code_for(entry)
                units_model.append(entry)

        ranks_model.append({"rankName": rank_name, "rank": rk, "units": units_model})

    print(f"[strat] Assembled {len(ranks_model)} ranks: {[(rm['rankName'], len(rm['units'])) for rm in ranks_model]}", file=sys.stderr, flush=True)

    # --- AUTO-DECOMPOSE flat ranks into hierarchical levels ---
    # When a single rank contains many units with chrono Code paths,
    # split them into separate virtual ranks by hierarchical depth.
    # Code is extracted from chrono records OR from ChronoStratigraphyID SRN.
    CHRONO_RANK_NAMES: Dict[int, str] = {
        0: "Eonothem", 1: "Erathem", 2: "System",
        3: "Series", 4: "Stage", 5: "Sub-Stage", 6: "Sub-Age", 7: "Zone",
    }
    decomposed: List[Dict[str, Any]] = []
    for rm in ranks_model:
        units = rm.get("units") or []
        if len(units) > 10:
            coded: List[tuple] = []
            uncoded: List[Dict[str, Any]] = []
            for um in units:
                code = _chrono_code_for(um)
                if code:
                    coded.append((um, code))
                else:
                    uncoded.append(um)
            # Only decompose when a meaningful fraction of items have Code
            if len(coded) >= len(units) * 0.3:
                # Group by hierarchical depth (0=Eonothem, 1=Erathem, …)
                by_depth: Dict[int, List[Dict[str, Any]]] = {}
                for um, code in coded:
                    depth = _chrono_depth(code)
                    if depth < 0:
                        uncoded.append(um)
                        continue
                    by_depth.setdefault(depth, []).append(um)
                if len(by_depth) > 1:
                    for d in sorted(by_depth.keys()):
                        rname = CHRONO_RANK_NAMES.get(d, f"Rank Level {d}")
                        decomposed.append({
                            "rankName": rname,
                            "rank": rm.get("rank"),
                            "units": by_depth[d],
                        })
                    # Uncoded items go to the deepest (finest) rank
                    if uncoded and decomposed:
                        decomposed[-1]["units"].extend(uncoded)
                    continue
        decomposed.append(rm)
    ranks_model = decomposed

    # --- MERGE ranks that share the same normalized rankName ---
    # Normalize: strip common prefixes so "Chronostratigraphic Eonothem" matches "Eonothem"
    _RANK_STRIP = re.compile(r'^(?:Chronostratigraphic\s+)', re.IGNORECASE)
    def _norm_rank(name: str) -> str:
        return _RANK_STRIP.sub('', name).strip() or name

    merged_ranks: List[Dict[str, Any]] = []
    norm_pos: Dict[str, int] = {}
    for rm in ranks_model:
        nk = _norm_rank(rm["rankName"])
        if nk in norm_pos:
            target = merged_ranks[norm_pos[nk]]
            seen = set()
            for u in target["units"]:
                k = (u.get("unit") or {}).get("id") or (u.get("chrono") or {}).get("id") or ""
                if k:
                    seen.add(k)
            for u in rm["units"]:
                k = (u.get("unit") or {}).get("id") or (u.get("chrono") or {}).get("id") or ""
                if k and k in seen:
                    continue
                if k:
                    seen.add(k)
                target["units"].append(u)
        else:
            norm_pos[nk] = len(merged_ranks)
            # Use the shorter/cleaner name variant
            rm["rankName"] = nk
            merged_ranks.append(rm)
    ranks_model = [rm for rm in merged_ranks if rm["units"]]

    # --- Sort ranks by unit count ascending (coarsest → finest) ---
    # This ensures the leaf (most units) always appears last, so the
    # matrix builder's "map everything before the leaf" logic covers
    # every rank.  For ranks with equal unit counts, preserve the
    # original relative order (stable sort).
    ranks_model.sort(key=lambda rm: len(rm["units"]))

    print(f"[strat] Final model: {len(ranks_model)} ranks: {[(rm['rankName'], len(rm['units'])) for rm in ranks_model]}", file=sys.stderr, flush=True)
    resp: Dict[str, Any] = {"column": col, "scheme": scheme, "ranks": ranks_model}
    if missing_rank_ids:
        resp["missingRanks"] = missing_rank_ids
    return JSONResponse(resp)
