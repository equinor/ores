"""
Analyse page - Reservoir → BusinessDecision comparison across decision gates.

Provides:
  GET  /analyse              → render the analyse.html template
  GET  /analyse/reservoirs   → JSON list of Reservoir master-data records
  POST /analyse/compare      → JSON comparison payload for a selected reservoir
"""
from __future__ import annotations

import asyncio
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
    from .common import access_token as _at
    return _at(request)


# ──────────────────────────────────────────────────────────────────────────────
# Lazy import helpers - main.py owns the enrichment machinery.
# We import at call time to avoid circular imports.
# ──────────────────────────────────────────────────────────────────────────────


async def _enrich_geolabel(
    data_block: Dict[str, Any],
    client: httpx.AsyncClient,
    storage_url: str,
    hdr: dict,
) -> Dict[str, Any]:
    from .bd_enrichment import _enrich_bd_geolabel
    return await _enrich_bd_geolabel(data_block, client, storage_url, hdr)


# ──────────────────────────────────────────────────────────────────────────────
# Pages
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/analyse", response_class=HTMLResponse, summary="Analyse: compare BDs for a reservoir")
async def analyse_page(request: Request):
    """Render the Analyse page with an auto-loaded reservoir list."""
    reservoirs = await _search_reservoirs(request, query="*", limit=50)
    return templates.TemplateResponse(
        request, "analyse.html",
        {"reservoirs": reservoirs},
    )


# ──────────────────────────────────────────────────────────────────────────────
# JSON APIs
# ──────────────────────────────────────────────────────────────────────────────

async def _search_reservoirs(
    request: Request, query: str = "*", limit: int = 50,
) -> List[Dict[str, str]]:
    """Shared helper via common.search_reservoirs."""
    at = _access_token(request)
    from .common import search_reservoirs
    return await search_reservoirs(at, query=query, limit=limit)


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
    """Pull a flat metrics dict from a BD data block + its GeoLabelSet.

    Sources (all OSDU-native):
      - Volumes:   GeoLabelSet volumes_by_segment (canonical FMU labels)
      - Economics:  data.ProjectSpecifications[] (ParameterTypeID → value)
      - Volumes fallback: ext.equinor.UncertaintySummary (inline P10/P50/P90)
    """
    ext_eq = ((data or {}).get("ext") or {}).get("equinor") or {}

    gls_vols = gls.get("volumes_by_segment") or {}
    gls_unc = gls.get("uncertainty") or {}
    total = gls_vols.get("TOTAL") or {}

    m: Dict[str, Any] = {}

    # ── Volumes from GeoLabelSet ──
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

    # Volumes from UncertaintySummary when GeoLabelSet is absent
    if not any(k.startswith("stoiip_") for k in m):
        usumm = ext_eq.get("UncertaintySummary") or {}
        stoiip = usumm.get("StaticInPlace_Oil_MSm3") or {}
        recov = usumm.get("Recoverable_Oil_MSm3") or {}
        rf = usumm.get("RecoveryFactor_pct") or {}
        for stat in ("P90", "P50", "P10"):
            v = stoiip.get(stat)
            if v is not None:
                m[f"stoiip_{stat.lower()}"] = float(v) * 1_000_000
        for stat in ("P90", "P50", "P10"):
            v = recov.get(stat)
            if v is not None:
                m[f"recoverable_{stat.lower()}"] = float(v) * 1_000_000
        for stat in ("P90", "P50", "P10"):
            v = rf.get(stat)
            if v is not None:
                m[f"rf_{stat.lower()}"] = float(v)

    # ── Economics from ProjectSpecifications[] (OSDU-native) ──
    _SPEC_MAP = {
        "NPV_10pct":    "npv",
        "IRR":          "irr",
        "CAPEX":        "capex",
        "OPEX_pa":      "opex",
        "BreakevenOil": "breakeven",
        "Payback":      "payback",
    }
    for spec in (data or {}).get("ProjectSpecifications") or []:
        type_id = spec.get("ParameterTypeID") or ""
        # Extract the code from …ParameterType:<code>:
        parts = type_id.split(":")
        code = parts[-2] if len(parts) >= 2 and parts[-1] == "" else parts[-1]
        metric_key = _SPEC_MAP.get(code)
        if metric_key and spec.get("DataQuantityParameter") is not None:
            m[metric_key] = spec["DataQuantityParameter"]

    # ── Wells from ActivityTemplate or DevelopmentConcept ──
    # Try canonical Parameters first (look for WellCount-like data)
    dcon = ext_eq.get("DevelopmentConcept") or {}
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
        ("payback", "Payback"),
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


def _risk_topic(name: str) -> str:
    """Extract the common topic from a risk name (part after ' - ')."""
    parts = name.split(" - ", 1)
    return parts[1].strip().lower() if len(parts) > 1 else name.strip().lower()


def _sev_num(s: str) -> int:
    """Parse 'S3' → 3, 'P4' → 4 etc. Return 0 if unparseable."""
    if s and len(s) >= 2 and s[0] in "SPsp" and s[1:].isdigit():
        return int(s[1:])
    return 0


def _diff_risks(gates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """For each gate, match risks by topic name and track severity changes."""
    result: List[Dict[str, Any]] = []
    prev_by_topic: Dict[str, Dict[str, Any]] = {}

    for g in gates:
        curr_ids = g.get("risk_ids") or []
        curr_details = g.get("risk_details") or {}
        curr_by_topic: Dict[str, Dict[str, Any]] = {}
        for rid in curr_ids:
            det = curr_details.get(rid, {})
            topic = _risk_topic(det.get("name", rid))
            curr_by_topic[topic] = {"id": rid, **det}

        prev_topics = set(prev_by_topic.keys())
        curr_topics = set(curr_by_topic.keys())

        added_topics = curr_topics - prev_topics
        removed_topics = prev_topics - curr_topics
        kept_topics = curr_topics & prev_topics

        added = [curr_by_topic[t]["id"] for t in sorted(added_topics)]
        removed = [prev_by_topic[t]["id"] for t in sorted(removed_topics)]
        kept = [curr_by_topic[t]["id"] for t in sorted(kept_topics)]

        # Compute severity changes for kept risks
        changes: List[Dict[str, Any]] = []
        for t in sorted(kept_topics):
            prev_d = prev_by_topic[t]
            curr_d = curr_by_topic[t]
            ps = _sev_num(prev_d.get("residual_severity", ""))
            cs = _sev_num(curr_d.get("residual_severity", ""))
            pp = _sev_num(prev_d.get("residual_probability", ""))
            cp = _sev_num(curr_d.get("residual_probability", ""))
            old_status = prev_d.get("status", "")
            new_status = curr_d.get("status", "")
            direction = ""
            if (cs < ps) or (cp < pp):
                direction = "reduced"
            elif (cs > ps) or (cp > pp):
                direction = "increased"
            if old_status != new_status and new_status.lower() == "mitigated":
                direction = "mitigated"
            if direction:
                changes.append({
                    "id": curr_d["id"],
                    "topic": t,
                    "name": curr_d.get("name", ""),
                    "prev_sev": f"{prev_d.get('residual_severity','')}/{prev_d.get('residual_probability','')}",
                    "curr_sev": f"{curr_d.get('residual_severity','')}/{curr_d.get('residual_probability','')}",
                    "prev_status": old_status,
                    "curr_status": new_status,
                    "direction": direction,
                })

        result.append({
            "added": added,
            "removed": removed,
            "kept": kept,
            "severity_changes": changes,
        })
        prev_by_topic = curr_by_topic
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
        async with osdu.http_client(timeout=60) as client:
            rr = await client.get(f"{storage_url}/{reservoir_id}", headers=hdr)
            if rr.status_code == 200:
                reservoir_name = (
                    (rr.json() or {}).get("data", {}).get("Name") or reservoir_id
                )
    except Exception:
        pass

    # 2. Fetch ALL BDs and filter in-memory by reservoir reference.
    # This is the most reliable approach for small partitions — avoids OSDU
    # search index gaps where nested fields (ReservoirIDs,
    # Parameters[].DataObjectParameter) may not be fully indexed.
    bd_kind = "osdu:wks:master-data--BusinessDecision:*"

    gates: List[Dict[str, Any]] = []
    try:
        async with osdu.http_client(timeout=120) as client:
            # Fetch all BDs – typically a small number in any partition
            all_bd_ids: list = []
            seen_ids: set = set()
            try:
                payload = {
                    "kind": bd_kind,
                    "query": "*",
                    "limit": 200,
                    "returnedFields": ["id", "kind", "version"],
                    "trackTotalCount": True,
                }
                r = await client.post(search_url, headers=hdr, json=payload)
                if r.status_code == 200:
                    for h in r.json().get("results", []):
                        bid = h.get("id")
                        if bid and bid not in seen_ids:
                            all_bd_ids.append(bid)
                            seen_ids.add(bid)
            except Exception as e:
                log.warning("[ANALYSE] BD fetch-all search failed: %s", e)

            log.info(
                "[ANALYSE] Found %d BD candidates for reservoir %s",
                len(all_bd_ids), reservoir_id,
            )

            # Process all BDs in parallel (was sequential)
            async def _process_bd(bid):
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
                        return None

                    # Skip superseded / hidden records
                    if data_block.get("IsDiscoverable") is False:
                        return None
                    if (data_block.get("Name") or "") in (".", ""):
                        return None

                    # Post-filter: verify this BD actually references the
                    # selected reservoir.  Check multiple locations:
                    #   1. data.ReservoirIDs[] (OSDU canonical top-level field)
                    #   2. data.Parameters[].DataObjectParameter (typed ref)
                    #   3. data.ancestry (parent/child links)
                    #   4. BD name contains reservoir name (implicit association)
                    #   5. Reservoir ID slug appears anywhere in the data JSON
                    reservoir_ids_field = data_block.get("ReservoirIDs") or []
                    refs_via_top_level = reservoir_id in reservoir_ids_field

                    params = data_block.get("Parameters") or []
                    refs_via_params = any(
                        isinstance(p, dict)
                        and reservoir_id in (p.get("DataObjectParameter") or "")
                        for p in params
                    )

                    ancestry = data_block.get("ancestry") or {}
                    ancestry_all = (ancestry.get("parents") or []) + (ancestry.get("children") or [])
                    refs_via_ancestry = reservoir_id in ancestry_all

                    # Name-based: BD name contains the reservoir name
                    bd_name = (data_block.get("Name") or "").lower()
                    res_name_lower = reservoir_name.lower() if reservoir_name else ""
                    refs_via_name = bool(
                        res_name_lower and len(res_name_lower) >= 3
                        and res_name_lower in bd_name
                    )

                    # Slug-based: reservoir ID slug anywhere in serialised data
                    _res_slug = reservoir_id.split(":")[-2] if reservoir_id.count(":") >= 3 else ""
                    refs_via_slug = bool(
                        _res_slug and len(_res_slug) >= 4
                        and _res_slug in str(data_block)
                    )

                    if not (refs_via_top_level or refs_via_params or refs_via_ancestry or refs_via_name or refs_via_slug):
                        log.info(
                            "[ANALYSE] BD %s (%s) does not reference reservoir %s - skipping",
                            bid, data_block.get("Name", "?"), reservoir_id,
                        )
                        return None

                    log.info(
                        "[ANALYSE] BD %s (%s) matched reservoir %s via: IDs=%s Params=%s Ancestry=%s Name=%s Slug=%s",
                        bid, data_block.get("Name", "?"), reservoir_id,
                        refs_via_top_level, refs_via_params, refs_via_ancestry, refs_via_name, refs_via_slug,
                    )

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
                    return gate
                except Exception as e:
                    log.warning(
                        "[ANALYSE] Failed to process BD %s: %s", bid, e
                    )
                    return None

            # Process all BDs in parallel
            bd_results = await asyncio.gather(*[_process_bd(bid) for bid in all_bd_ids])
            gates = [g for g in bd_results if g is not None]

            gates.sort(key=lambda g: g.pop("_sort_key"))

            # Hydrate risk names + details (parallel)
            all_risk_ids: set = set()
            for g in gates:
                g.setdefault("risk_details", {})
                all_risk_ids.update(g.get("risk_ids") or [])

            async def _fetch_risk(rid):
                rname = rid
                rdata: Dict[str, Any] = {}
                try:
                    rr = await client.get(
                        f"{storage_url}/{rid}", headers=hdr
                    )
                    if rr.status_code == 200:
                        rdata = (rr.json() or {}).get("data", {})
                        rname = rdata.get("Name") or rid
                except Exception:
                    pass
                eq = (rdata.get("ext") or {}).get("equinor") or {}
                detail = {
                    "name": rname,
                    "inherent_severity": eq.get("InherentSeverity", ""),
                    "inherent_probability": eq.get("InherentProbability", ""),
                    "residual_severity": eq.get("ResidualSeverity", ""),
                    "residual_probability": eq.get("ResidualProbability", ""),
                    "status": eq.get("Status", ""),
                    "category": eq.get("RiskCategoryID", ""),
                }
                return (rid, rname, detail)

            risk_results = await asyncio.gather(*[_fetch_risk(rid) for rid in all_risk_ids])
            for rid, rname, detail in risk_results:
                for g in gates:
                    if rid in (g.get("risk_ids") or []):
                        g["risk_names"][rid] = rname
                        g["risk_details"][rid] = detail

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
