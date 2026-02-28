"""
Analyse page — Reservoir → BusinessDecision comparison across decision gates.

Provides:
  GET  /analyse              → render the analyse.html template
  GET  /analyse/reservoirs   → JSON list of Reservoir master-data records
  POST /analyse/compare      → JSON comparison payload for a selected reservoir
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

import httpx
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from . import osdu

log = logging.getLogger("rddms-admin.analyse")

router = APIRouter()
templates = Jinja2Templates(
    directory=os.path.join(os.path.dirname(__file__), "templates"),
)


def _access_token(request: Request) -> str:
    at = getattr(request.state, "access_token", None)
    if not at:
        raise HTTPException(401, "Authentication failed")
    return at


# ──────────────────────────────────────────────────────────────────────────────
# Lazy import helpers — main.py owns the enrichment machinery & local cache.
# We import at call time to avoid circular imports.
# ──────────────────────────────────────────────────────────────────────────────

def _local_records() -> Dict[str, Dict[str, Any]]:
    from .main import _LOCAL_RECORDS
    return _LOCAL_RECORDS


def _apply_enrichment(data_block: Dict[str, Any], record_id: str) -> None:
    from .main import _apply_bd_local_enrichment
    _apply_bd_local_enrichment(data_block, record_id)


async def _enrich_geolabel(
    data_block: Dict[str, Any],
    client: httpx.AsyncClient,
    storage_url: str,
    hdr: dict,
) -> Dict[str, Any]:
    from .main import _enrich_bd_geolabel
    return await _enrich_bd_geolabel(data_block, client, storage_url, hdr)


# ──────────────────────────────────────────────────────────────────────────────
# Pages
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/analyse", response_class=HTMLResponse, summary="Analyse: compare BDs for a reservoir")
async def analyse_page(request: Request):
    """Render the Analyse page with an auto-loaded reservoir list."""
    reservoirs = await _search_reservoirs(request, query="*", limit=50)
    return templates.TemplateResponse(
        "analyse.html",
        {"request": request, "reservoirs": reservoirs},
    )


# ──────────────────────────────────────────────────────────────────────────────
# JSON APIs
# ──────────────────────────────────────────────────────────────────────────────

async def _search_reservoirs(
    request: Request, query: str = "*", limit: int = 50,
) -> List[Dict[str, str]]:
    """Shared helper: search for Reservoir master-data records.

    De-duplicates on record-id base (ignoring version suffix) and keeps
    only the newest version so callers never see stale copies.
    """
    at = _access_token(request)
    search_url = f"https://{osdu.OSDU_BASE_URL}/api/search/v2/query"
    storage_url = f"https://{osdu.OSDU_BASE_URL}/api/storage/v2/records"
    hdr = osdu.headers(at)

    payload = {
        "kind": "osdu:wks:master-data--Reservoir:2.0.0",
        "query": query,
        "limit": min(int(limit), 100),
        "returnedFields": ["id", "kind", "version"],
        "trackTotalCount": True,
    }

    raw: List[Dict[str, str]] = []
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(search_url, headers=hdr, json=payload)
            r.raise_for_status()
            res = r.json()
            for hit in res.get("results", []):
                rid = hit.get("id")
                if not rid:
                    continue
                name = rid
                version = str(hit.get("version") or "")
                try:
                    rf = await client.get(f"{storage_url}/{rid}", headers=hdr)
                    if rf.status_code == 200:
                        d = (rf.json() or {}).get("data", {}) or {}
                        name = d.get("Name") or d.get("Description") or rid
                        version = version or str((rf.json() or {}).get("version") or "")
                except Exception:
                    pass
                raw.append({"id": rid, "name": name, "version": version})
    except Exception as e:
        log.warning("[ANALYSE] Reservoir search failed: %s", e)

    # De-duplicate: strip trailing ":N" version to get a stable base id,
    # then keep only the entry whose version number is highest.
    best: Dict[str, Dict[str, str]] = {}
    for entry in raw:
        rid = entry["id"]
        # base id = everything up to (but not including) the last colon-number
        parts = rid.rsplit(":", 1)
        base = parts[0] if len(parts) == 2 and parts[1].isdigit() else rid
        existing = best.get(base)
        if existing is None or int(entry.get("version") or 0) > int(existing.get("version") or 0):
            best[base] = entry

    return list(best.values())


@router.get("/analyse/reservoirs", response_class=JSONResponse)
async def analyse_reservoir_search(
    request: Request,
    query: str = "*",
    limit: int = 50,
):
    """Search for Reservoir master-data records (JSON API for the analyse page)."""
    try:
        results = await _search_reservoirs(request, query=query, limit=limit)
    except Exception as e:
        return JSONResponse({"error": str(e), "reservoirs": []}, status_code=500)
    return JSONResponse({"reservoirs": results, "totalCount": len(results)})


# ──────────────────────────────────────────────────────────────────────────────
# Comparison helpers
# ──────────────────────────────────────────────────────────────────────────────

def _extract_dg_sort_key(data: Dict[str, Any]) -> Tuple[int, str]:
    """Return (numeric_gate, date) for sorting BDs chronologically."""
    level = (data.get("DecisionLevelID") or "").lower()
    dg_num = 99
    for token in level.replace(":", " ").replace("-", " ").split():
        if token.startswith("dg") and len(token) > 2:
            try:
                dg_num = int(token[2:])
            except ValueError:
                pass
    date = data.get("DecisionDate") or data.get("DecisionDueDate") or "9999"
    return (dg_num, date)


def _extract_bd_metrics(
    data: Dict[str, Any],
    gls: Dict[str, Any],
) -> Dict[str, Any]:
    """Pull a flat metrics dict from a BD data block + its GeoLabelSet."""
    ext_eq = ((data or {}).get("ext") or {}).get("equinor") or {}
    econ = ext_eq.get("KeyEconomics") or {}
    dcon = ext_eq.get("DevelopmentConcept") or {}

    gls_vols = gls.get("volumes_by_segment") or {}
    gls_unc = gls.get("uncertainty") or {}
    total = gls_vols.get("TOTAL") or {}

    m: Dict[str, Any] = {}

    # Volumes from GeoLabelSet
    for stat in ("P90", "P50", "P10"):
        v = total.get(f"Oil.{stat}")
        if v is not None:
            m[f"stoiip_{stat.lower()}"] = v
    for stat in ("P90", "P50", "P10"):
        v = gls_unc.get(f"Recoverable.{stat}")
        if v is not None:
            m[f"recoverable_{stat.lower()}"] = v
    for stat in ("P90", "P50", "P10"):
        v = gls_unc.get(f"RecoveryFactor.{stat}")
        if v is not None:
            m[f"rf_{stat.lower()}"] = v

    # Economics
    if econ.get("NPV_10pct_MUSD") is not None:
        m["npv"] = econ["NPV_10pct_MUSD"]
    if econ.get("CAPEX_MNOK") is not None:
        m["capex"] = econ["CAPEX_MNOK"]
    if econ.get("OPEX_MNOK_pa") is not None:
        m["opex"] = econ["OPEX_MNOK_pa"]
    if econ.get("IRR_pct") is not None:
        m["irr"] = econ["IRR_pct"]
    if econ.get("BreakevenOilPrice_USDperbbl") is not None:
        m["breakeven"] = econ["BreakevenOilPrice_USDperbbl"]

    # Dev concept
    if dcon.get("WellCount") is not None:
        m["wells"] = dcon["WellCount"]

    return m


def _compute_deltas(gates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """For each consecutive pair of gates, compute deltas for numeric values.

    Returns a list (len = len(gates)) where index 0 has no deltas, and each
    subsequent index has deltas relative to the previous gate.
    """
    deltas: List[Dict[str, Any]] = [{}]
    metric_keys = [
        ("stoiip_p90", "STOIIP P90"),
        ("stoiip_p50", "STOIIP P50"),
        ("stoiip_p10", "STOIIP P10"),
        ("recoverable_p90", "Recoverable P90"),
        ("recoverable_p50", "Recoverable P50"),
        ("recoverable_p10", "Recoverable P10"),
        ("rf_p90", "Recovery Factor P90"),
        ("rf_p50", "Recovery Factor P50"),
        ("rf_p10", "Recovery Factor P10"),
        ("npv", "NPV"),
        ("capex", "CAPEX"),
        ("opex", "OPEX"),
        ("irr", "IRR"),
        ("breakeven", "Breakeven"),
        ("wells", "Wells"),
    ]
    for i in range(1, len(gates)):
        prev = gates[i - 1].get("metrics", {})
        curr = gates[i].get("metrics", {})
        d: Dict[str, Any] = {}
        for key, label in metric_keys:
            pv = prev.get(key)
            cv = curr.get(key)
            if pv is not None and cv is not None:
                try:
                    pf = float(pv)
                    cf = float(cv)
                    abs_d = cf - pf
                    pct_d = ((cf - pf) / pf * 100) if pf != 0 else None
                    d[key] = {
                        "abs": round(abs_d, 2),
                        "pct": round(pct_d, 1) if pct_d is not None else None,
                        "label": label,
                    }
                except (ValueError, TypeError):
                    pass
            elif pv is None and cv is not None:
                d[key] = {"abs": None, "pct": None, "label": label, "new": True}
        deltas.append(d)
    return deltas


def _diff_risks(gates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """For each gate, annotate risk IDs as added/removed/kept vs previous gate."""
    result: List[Dict[str, Any]] = []
    prev_set: set = set()
    for g in gates:
        curr_ids = set(g.get("risk_ids") or [])
        added = curr_ids - prev_set
        removed = prev_set - curr_ids
        kept = curr_ids & prev_set
        result.append({
            "added": sorted(added),
            "removed": sorted(removed),
            "kept": sorted(kept),
        })
        prev_set = curr_ids
    return result


def _diff_properties(gates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """For each gate, compute property deltas vs the previous gate."""
    result: List[Dict[str, Any]] = [{}]
    for i in range(1, len(gates)):
        prev_props = gates[i - 1].get("properties") or {}
        curr_props = gates[i].get("properties") or {}
        d: Dict[str, Any] = {}
        all_keys = set(list(prev_props.keys()) + list(curr_props.keys()))
        for k in sorted(all_keys):
            pv = prev_props.get(k)
            cv = curr_props.get(k)
            if isinstance(pv, dict) or isinstance(cv, dict):
                pv_d = pv if isinstance(pv, dict) else {}
                cv_d = cv if isinstance(cv, dict) else {}
                sub_d = {}
                for sk in set(list(pv_d.keys()) + list(cv_d.keys())):
                    spv, scv = pv_d.get(sk), cv_d.get(sk)
                    if spv is not None and scv is not None:
                        try:
                            diff = float(scv) - float(spv)
                            pct = (diff / float(spv)) * 100 if float(spv) != 0 else None
                            sub_d[sk] = {
                                "abs": round(diff, 4),
                                "pct": round(pct, 1) if pct is not None else None,
                            }
                        except (ValueError, TypeError):
                            pass
                if sub_d:
                    d[k] = sub_d
            elif pv is not None and cv is not None:
                try:
                    diff = float(cv) - float(pv)
                    pct = (diff / float(pv)) * 100 if float(pv) != 0 else None
                    d[k] = {
                        "abs": round(diff, 4),
                        "pct": round(pct, 1) if pct is not None else None,
                    }
                except (ValueError, TypeError):
                    pass
            elif pv is None and cv is not None:
                d[k] = {"new": True}
        result.append(d)
    return result


# ──────────────────────────────────────────────────────────────────────────────
# Main comparison endpoint
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/analyse/compare", response_class=JSONResponse)
async def analyse_compare(
    request: Request,
    reservoir_id: str = Form(...),
):
    """Given a Reservoir record ID, find all BDs referencing it,
    enrich each with GeoLabelSet/economics/risks, and return a
    comparison structure for the template to render."""
    at = _access_token(request)
    search_url = f"https://{osdu.OSDU_BASE_URL}/api/search/v2/query"
    storage_url = f"https://{osdu.OSDU_BASE_URL}/api/storage/v2/records"
    hdr = osdu.headers(at)

    # 1. Fetch reservoir record name
    reservoir_name = reservoir_id
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            rr = await client.get(f"{storage_url}/{reservoir_id}", headers=hdr)
            if rr.status_code == 200:
                reservoir_name = (
                    (rr.json() or {}).get("data", {}).get("Name") or reservoir_id
                )
    except Exception:
        pass

    # 2. Search for BDs that reference this reservoir.
    # OSDU search v2 uses Lucene full-text; nested array field paths are
    # not supported.  We use a plain full-text query containing the
    # reservoir id (which is embedded in Parameters[].DataObjectParameter)
    # and then filter the results in-memory to ensure the match is real.
    # We also always scan _LOCAL_RECORDS so demo/manifest BDs are found
    # even before they are ingested.
    LOCAL = _local_records()

    # Build a short search token from the reservoir id — use the UUID
    # portion so we don't hit Lucene special-char issues with colons.
    _rid_parts = reservoir_id.split(":")
    # Typical id: dev:master-data--Reservoir:<uuid>:<ver>
    search_token = _rid_parts[-2] if len(_rid_parts) >= 3 else reservoir_id
    bd_query = f'"{search_token}"'
    payload = {
        "kind": "osdu:wks:master-data--BusinessDecision:1.0.0",
        "query": bd_query,
        "limit": 50,
        "returnedFields": ["id", "kind", "version"],
        "trackTotalCount": True,
    }

    gates: List[Dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            # OSDU search (may return false positives — filtered below)
            osdu_hit_ids: set = set()
            try:
                r = await client.post(search_url, headers=hdr, json=payload)
                r.raise_for_status()
                osdu_hit_ids = {
                    h.get("id") for h in r.json().get("results", []) if h.get("id")
                }
            except Exception as e:
                log.warning("[ANALYSE] BD OSDU search failed (continuing with local): %s", e)

            # Local manifest BDs
            local_bd_ids: set = set()
            for rec in LOCAL.values():
                if "BusinessDecision" not in (rec.get("kind") or ""):
                    continue
                params = (rec.get("data") or {}).get("Parameters") or []
                for p in params:
                    if isinstance(p, dict) and reservoir_id in (
                        p.get("DataObjectParameter") or ""
                    ):
                        local_bd_ids.add(rec.get("id"))

            all_bd_ids = list(osdu_hit_ids | local_bd_ids)
            log.info(
                "[ANALYSE] Found %d BD candidates (%d OSDU + %d local) for reservoir %s",
                len(all_bd_ids), len(osdu_hit_ids), len(local_bd_ids), reservoir_id,
            )

            for bid in all_bd_ids:
                try:
                    data_block: Optional[Dict[str, Any]] = None
                    full: Dict[str, Any] = {}
                    try:
                        rf = await client.get(
                            f"{storage_url}/{bid}", headers=hdr
                        )
                        if rf.status_code == 200:
                            full = rf.json() or {}
                            data_block = full.get("data", {}) or {}
                    except Exception:
                        pass
                    if not data_block:
                        local_rec = LOCAL.get(bid)
                        if local_rec:
                            full = local_rec
                            data_block = local_rec.get("data") or local_rec
                    if not data_block:
                        continue

                    _apply_enrichment(data_block, bid)

                    # Post-filter: verify this BD actually references the
                    # selected reservoir via Parameters[].DataObjectParameter.
                    # The full-text search may return false positives.
                    params = data_block.get("Parameters") or []
                    refs_reservoir = any(
                        isinstance(p, dict)
                        and reservoir_id in (p.get("DataObjectParameter") or "")
                        for p in params
                    )
                    if not refs_reservoir:
                        log.debug(
                            "[ANALYSE] BD %s does not reference reservoir %s — skipping",
                            bid, reservoir_id,
                        )
                        continue

                    gls = await _enrich_geolabel(
                        data_block, client, storage_url, hdr
                    )

                    ext_eq = (
                        (data_block or {}).get("ext") or {}
                    ).get("equinor") or {}
                    level_raw = data_block.get("DecisionLevelID") or ""
                    gate_label = level_raw
                    for token in (
                        level_raw.replace(":", " ").replace("-", " ").split()
                    ):
                        if token.upper().startswith("DG") and len(token) <= 4:
                            gate_label = token.upper()
                            break

                    metrics = _extract_bd_metrics(data_block, gls)

                    gate = {
                        "id": bid,
                        "name": data_block.get("Name") or bid,
                        "gate_label": gate_label,
                        "decision_date": (
                            data_block.get("DecisionDate")
                            or data_block.get("DecisionDueDate")
                            or ""
                        ),
                        "status": (
                            (data_block.get("ApprovalStatusID") or "")
                            .split(":")[-2]
                            if ":"
                            in (data_block.get("ApprovalStatusID") or "")
                            else data_block.get("ApprovalStatusID") or ""
                        ),
                        "summary": (
                            data_block.get("DecisionSummary")
                            or data_block.get("Description")
                            or ""
                        ),
                        "risk_ids": data_block.get("RiskIDs") or [],
                        "risk_names": {},
                        "metrics": metrics,
                        "properties": gls.get("properties") or {},
                        "key_uncertainties": ext_eq.get("KeyUncertainties")
                        or [],
                        "development_concept": ext_eq.get("DevelopmentConcept")
                        or {},
                        "economics": ext_eq.get("KeyEconomics") or {},
                        "alternatives": ext_eq.get("Alternatives") or [],
                        "schedule": ext_eq.get("ScheduleMilestones") or [],
                        "gls_volumes": gls.get("volumes_by_segment") or {},
                        "gls_uncertainty": gls.get("uncertainty") or {},
                        "_sort_key": _extract_dg_sort_key(data_block),
                    }
                    gates.append(gate)
                except Exception as e:
                    log.warning(
                        "[ANALYSE] Failed to process BD %s: %s", bid, e
                    )

            gates.sort(key=lambda g: g.pop("_sort_key"))

            # Hydrate risk names
            all_risk_ids: set = set()
            for g in gates:
                all_risk_ids.update(g.get("risk_ids") or [])
            for rid in all_risk_ids:
                rname = rid
                try:
                    rr = await client.get(
                        f"{storage_url}/{rid}", headers=hdr
                    )
                    if rr.status_code == 200:
                        rname = (
                            (rr.json() or {}).get("data", {}).get("Name")
                            or rid
                        )
                    else:
                        lr = LOCAL.get(rid)
                        if lr:
                            rname = (
                                (lr.get("data") or {}).get("Name") or rid
                            )
                except Exception:
                    pass
                for g in gates:
                    if rid in (g.get("risk_ids") or []):
                        g["risk_names"][rid] = rname

    except Exception as e:
        log.exception("[ANALYSE] Compare failed: %s", e)
        return JSONResponse({"error": str(e)}, status_code=500)

    metric_deltas = _compute_deltas(gates)
    risk_diffs = _diff_risks(gates)
    prop_diffs = _diff_properties(gates)

    return JSONResponse({
        "reservoir_id": reservoir_id,
        "reservoir_name": reservoir_name,
        "gates": gates,
        "metric_deltas": metric_deltas,
        "risk_diffs": risk_diffs,
        "property_diffs": prop_diffs,
    })
