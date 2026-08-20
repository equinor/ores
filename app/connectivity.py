"""
connectivity.py - Connectivity query engine for field development workflows.

Queries LIVE data from OSDU catalog + RDDMS to assess reservoir connectivity
between any two wells in any field/dataspace. No hardcoded field data.

Combines:
  1. Stratigraphic correlation (markers from RDDMS WellboreMarkerFrameRepresentation)
  2. Structural analysis (faults from FaultInterpretation + GridConnectionSet)
  3. Property quality assessment (grid/well properties via deepSearch)
  4. Business decision evidence (Risk/DevConcept WPCs from OSDU catalog)
  5. Production response (ColumnBasedTable WPCs from OSDU catalog)

Usage via API:
  POST /api/connectivity/query
  {
    "well_a": "55/33-A-2",
    "well_b": "55/33-A-3",
    "zone": "Valysar",
    "dataspace": "maap/drogon",
    "property_filters": {"ntg_min": 0.5, "kh_min": 100, "sw_max": 0.6},
    "include_faults": true,
    "include_production": true,
    "include_bd_evidence": true
  }
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import os

from . import osdu
from .common import access_token as _access_token
from .pg_backend import get_pool as _get_pool

router = APIRouter()
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))
log = logging.getLogger("rddms-admin.connectivity")


# ──────────────────────────────────────────────────────────────────────────────
# Data model (request/response)
# ──────────────────────────────────────────────────────────────────────────────

class ConnectivityRequest(BaseModel):
    well_a: str
    well_b: str
    zone: Optional[str] = None
    dataspace: str = "maap/drogon"
    property_filters: Optional[Dict[str, float]] = None
    include_faults: bool = True
    include_production: bool = True
    include_bd_evidence: bool = True


class FaultAssessment(BaseModel):
    fault_name: str
    transmissibility: Optional[float] = None
    seal_quality: str = "unknown"
    segments_connected: List[str] = []
    description: str = ""


class PropertyCorridor(BaseModel):
    zone: str
    mean_porosity: Optional[float] = None
    mean_permeability: Optional[float] = None
    mean_ntg: Optional[float] = None
    mean_sw: Optional[float] = None
    quality_assessment: str = "unknown"


class ProductionComparison(BaseModel):
    well: str
    segment: str = ""
    peak_oil_rate: Optional[float] = None
    current_water_cut: Optional[float] = None
    cumulative_oil: Optional[float] = None
    performance_rating: str = "unknown"


class BDEvidence(BaseModel):
    record_type: str
    name: str
    status: str = ""
    description: str = ""
    relevance: str = ""


class ConnectivityResult(BaseModel):
    connected: Optional[bool] = None
    confidence: str = "low"
    summary: str = ""
    same_zone: bool = False
    zone_detail: str = ""
    faults_between: List[FaultAssessment] = []
    structural_summary: str = ""
    property_corridor: Optional[PropertyCorridor] = None
    production: List[ProductionComparison] = []
    production_summary: str = ""
    bd_evidence: List[BDEvidence] = []
    recommendations: List[str] = []


# ──────────────────────────────────────────────────────────────────────────────
# Live data queries - fetch from RDDMS (via internal GraphQL) + OSDU catalog
# ──────────────────────────────────────────────────────────────────────────────

async def _run_deep_search(token: str, dataspace: str, type_name: str = None,
                           category: str = None, include_relations: bool = True,
                           include_statistics: bool = False, property_filter=None,
                           limit: int = 30) -> List[Dict[str, Any]]:
    """Run a deep search via the internal GraphQL schema (same as /api/graphql/query)."""
    from .graphql_search import deep_search_impl
    result = await deep_search_impl(
        token=token,
        dataspace=dataspace,
        dataspaces=None,
        type_name=type_name,
        category=category,
        title_contains=None,
        property_filter=property_filter,
        include_relations=include_relations,
        relation_filter=None,
        include_statistics=include_statistics,
        include_sample_values=False,
        sample_size=0,
        limit=limit,
    )
    # Result is a DeepSearchResult strawberry type - extract objects
    objects = []
    for obj in (result.objects or []):
        o = {"uuid": obj.uuid, "title": obj.title, "typeName": obj.type_name}
        if obj.relations:
            o["relations"] = [
                {"uuid": r.uuid, "name": r.name, "typeName": r.type_name, "direction": r.direction}
                for r in obj.relations
            ]
        if obj.properties:
            o["properties"] = []
            for p in obj.properties:
                prop = {"title": p.title, "kind": p.kind, "uom": p.uom}
                if p.statistics:
                    prop["statistics"] = {
                        "count": p.statistics.count, "mean": p.statistics.mean,
                        "minValue": p.statistics.min_value, "maxValue": p.statistics.max_value,
                    }
                if p.matching_cells:
                    prop["matchingCells"] = {
                        "count": p.matching_cells.count, "total": p.matching_cells.total,
                        "fraction": p.matching_cells.fraction,
                    }
                o["properties"].append(prop)
        objects.append(o)
    return objects


async def _search_catalog(token: str, kind: str, query: str, limit: int = 20) -> List[Dict]:
    """Search OSDU catalog via the Search v2 API."""
    try:
        search_url = f"https://{osdu.OSDU_BASE_URL}/api/search/v2/query"
        hdr = osdu.headers(token)
        payload = {"kind": kind, "query": query, "limit": limit}
        async with osdu.http_client(timeout=30) as client:
            resp = await client.post(search_url, json=payload, headers=hdr)
            resp.raise_for_status()
            data = resp.json()
            return data.get("results", [])
    except Exception as e:
        log.debug("Catalog search failed (kind=%s, q=%s): %s", kind, query, e)
        return []


async def _fetch_wells(token: str, dataspace: str) -> List[Dict[str, Any]]:
    """Fetch well features from RDDMS via deep search."""
    return await _run_deep_search(token, dataspace, category="well", limit=50)


async def _fetch_markers(token: str, dataspace: str) -> List[Dict[str, Any]]:
    """Fetch wellbore marker frames (formation tops per well)."""
    return await _run_deep_search(
        token, dataspace,
        type_name="resqml20.obj_WellboreMarkerFrameRepresentation",
        limit=50,
    )


async def _fetch_faults(token: str, dataspace: str) -> List[Dict[str, Any]]:
    """Fetch fault interpretations with relations."""
    return await _run_deep_search(
        token, dataspace,
        type_name="resqml20.obj_FaultInterpretation",
        include_statistics=True,
        limit=20,
    )


async def _fetch_grid_properties(token: str, dataspace: str) -> List[Dict[str, Any]]:
    """Fetch grid property statistics (porosity, permeability, NTG, Sw)."""
    return await _run_deep_search(
        token, dataspace,
        type_name="resqml20.obj_IjkGridRepresentation",
        include_statistics=True,
        limit=5,
    )


async def _fetch_production_records(token: str, well_names: List[str]) -> List[Dict[str, Any]]:
    """Fetch per-well production WPC records from OSDU catalog."""
    results = []
    for name in well_names:
        short = name.split("-")[-1] if "-" in name else name
        hits = await _search_catalog(
            token,
            kind="osdu:wks:work-product-component--ColumnBasedTable:*",
            query=f"WellProd AND {short}",
            limit=5,
        )
        for hit in hits:
            data = hit.get("data", {})
            results.append({
                "well": name,
                "name": data.get("Name", ""),
                "segment": data.get("ReservoirSegment", ""),
                "well_type": data.get("WellType", ""),
                "table": data.get("Table", {}),
            })
    return results


async def _fetch_bd_records(token: str, field_name: str) -> List[Dict[str, Any]]:
    """Fetch Risk + DevelopmentConcept + Activity records from OSDU catalog."""
    results = []
    for kind_suffix in ("Risk", "DevelopmentConcept", "Activity"):
        hits = await _search_catalog(
            token,
            kind=f"osdu:wks:work-product-component--{kind_suffix}:*",
            query=field_name,
            limit=20,
        )
        for hit in hits:
            data = hit.get("data", {})
            results.append({
                "type": kind_suffix,
                "name": data.get("Name", hit.get("id", "")),
                "description": data.get("Description", ""),
                "status": data.get("Status", data.get("RiskStatus", "")),
            })
    return results


async def _fetch_fault_connectivity(token: str, field_name: str) -> List[Dict[str, Any]]:
    """Fetch fault transmissibility / connectivity WPCs from OSDU catalog."""
    hits = await _search_catalog(
        token,
        kind="osdu:wks:work-product-component--GenericRepresentation:*",
        query=f"({field_name}) AND (FaultTrans OR ConnectivityMatrix OR Transmissibility)",
        limit=20,
    )
    results = []
    for hit in hits:
        data = hit.get("data", {})
        results.append({
            "name": data.get("Name", ""),
            "fault_name": data.get("FaultName", ""),
            "transmissibility": data.get("TransmissibilityMultiplier"),
            "segments": data.get("SegmentsConnected", []),
            "seal_desc": data.get("SealDescription", ""),
            "connectivity_matrix": data.get("ConnectivityMatrix"),
        })
    return results


# ──────────────────────────────────────────────────────────────────────────────
# Analysis helpers
# ──────────────────────────────────────────────────────────────────────────────

def _match_well(objects: List[Dict], well_name: str) -> List[Dict]:
    """Find RDDMS objects whose title matches a well name (fuzzy)."""
    name_lower = well_name.lower().replace(" ", "")
    matches = []
    for obj in objects:
        title = (obj.get("title") or "").lower().replace(" ", "")
        if name_lower in title or title in name_lower:
            matches.append(obj)
            continue
        # Match short form: "A-2" matches "55/33-A-2"
        parts = well_name.split("-")
        if len(parts) >= 2:
            short = parts[-1]
            if short.lower() in title:
                matches.append(obj)
    return matches


def _extract_zones_from_markers(marker_objects: List[Dict], well_name: str) -> List[str]:
    """Extract zone names from marker frame relations for a specific well."""
    well_markers = _match_well(marker_objects, well_name)
    zones = set()
    for m in well_markers:
        for rel in m.get("relations", []):
            rel_name = rel.get("name", "")
            rel_type = rel.get("typeName", "")
            if "Horizon" in rel_type or "Stratigraphic" in rel_type:
                zones.add(rel_name)
        # Also extract from title patterns (e.g. "A-2 Markers: Valysar, Therys")
        title = m.get("title", "")
        # Common formation names
        for token in re.split(r'[\s,;/|]+', title):
            if len(token) > 3 and token[0].isupper() and token.isalpha():
                zones.add(token)
    return sorted(zones) if zones else []


def _find_faults_between_wells(
    fault_objects: List[Dict],
    fault_connectivity: List[Dict],
    well_a_segment: str,
    well_b_segment: str,
) -> List[FaultAssessment]:
    """Find faults separating two segments using catalog connectivity data."""
    faults = []

    # Try catalog connectivity records (have transmissibility values)
    for fc in fault_connectivity:
        segments = fc.get("segments", [])
        if not segments:
            continue
        segs_lower = [s.lower() for s in segments]
        if (well_a_segment.lower() in segs_lower and
                well_b_segment.lower() in segs_lower):
            trans = fc.get("transmissibility")
            quality = "unknown"
            if trans is not None:
                quality = ("open" if trans > 0.7 else "moderate" if trans > 0.3
                           else "baffle" if trans > 0.05 else "seal")
            faults.append(FaultAssessment(
                fault_name=fc.get("fault_name") or fc.get("name", "?"),
                transmissibility=trans,
                seal_quality=quality,
                segments_connected=segments,
                description=fc.get("seal_desc", ""),
            ))

    # If no catalog connectivity records matched, list RDDMS faults
    if not faults and fault_objects:
        for fo in fault_objects[:5]:
            faults.append(FaultAssessment(
                fault_name=fo.get("title", "Unknown Fault"),
                transmissibility=None,
                seal_quality="unknown",
                description="Fault in RDDMS - transmissibility not yet quantified. "
                            "Ingest fault property records for seal assessment.",
            ))

    return faults


def _extract_property_stats(grid_objects: List[Dict]) -> Dict[str, float]:
    """Extract average property values from grid deepSearch results."""
    props = {}
    for grid in grid_objects:
        for p in grid.get("properties", []):
            title = (p.get("title") or "").lower()
            stats = p.get("statistics") or {}
            mean = stats.get("mean")
            if mean is None:
                continue
            if "phit" in title or "poro" in title:
                props.setdefault("porosity", mean)
            elif "klogh" in title or "perm" in title:
                props.setdefault("permeability", mean)
            elif "ntg" in title or "net" in title:
                props.setdefault("ntg", mean)
            elif title.startswith("sw") or "saturation" in title:
                props.setdefault("sw", mean)
    return props


def _assess_property_quality(props: Dict[str, float]) -> str:
    """Rate property quality for reservoir connectivity."""
    score = 0
    if props.get("porosity", 0) > 0.20:
        score += 1
    if props.get("permeability", 0) > 200:
        score += 1
    if props.get("ntg", 0) > 0.55:
        score += 1
    if props.get("sw", 1.0) < 0.35:
        score += 1
    if score >= 4:
        return "excellent"
    elif score >= 3:
        return "good"
    elif score >= 2:
        return "moderate"
    return "poor"


def _extract_production_summary(
    prod_records: List[Dict], well_name: str
) -> Optional[ProductionComparison]:
    """Extract production KPIs from a ColumnBasedTable record."""
    for rec in prod_records:
        if rec.get("well") != well_name:
            continue
        table = rec.get("table", {})
        col_values = table.get("ColumnValues", [])
        columns = table.get("Columns", [])

        col_map = {}
        for i, col_def in enumerate(columns):
            col_name = col_def.get("ColumnName", "")
            idx = i + 1  # +1 because first ColumnValues is the key column
            if idx < len(col_values):
                values = (col_values[idx].get("NumberColumn") or
                          col_values[idx].get("StringColumn") or [])
                col_map[col_name] = values

        peak_oil = max(col_map["WOPR"]) if col_map.get("WOPR") else None
        wcut_values = col_map.get("WWCT", [])
        current_wcut = wcut_values[-1] if wcut_values else None
        cum_values = col_map.get("WOPT", [])
        cum_oil = cum_values[-1] if cum_values else None

        rating = "unknown"
        if current_wcut is not None:
            rating = "good" if current_wcut < 0.35 else "average" if current_wcut < 0.50 else "poor"

        return ProductionComparison(
            well=well_name,
            segment=rec.get("segment", ""),
            peak_oil_rate=peak_oil,
            current_water_cut=current_wcut,
            cumulative_oil=cum_oil,
            performance_rating=rating,
        )
    return None


def _filter_relevant_bd(
    bd_records: List[Dict], well_names: List[str], fault_names: List[str]
) -> List[BDEvidence]:
    """Filter BD records to those relevant to the connectivity question."""
    results = []
    keywords = [w.lower() for w in well_names + fault_names]
    keywords += ["compartment", "connectivity", "seal", "baffle", "communication"]

    for bd in bd_records:
        desc = (bd.get("description") or "").lower()
        name = (bd.get("name") or "").lower()
        text = desc + " " + name

        if any(kw in text for kw in keywords):
            relevance = "Related to inter-segment connectivity"
            matching_faults = [f for f in fault_names if f.lower() in text]
            if matching_faults:
                relevance = f"Mentions fault(s): {', '.join(matching_faults)}"
            elif any(w.lower() in text for w in well_names):
                relevance = "Mentions well(s) in query"

            results.append(BDEvidence(
                record_type=bd.get("type", ""),
                name=bd.get("name", ""),
                status=bd.get("status", ""),
                description=bd.get("description", "")[:300],
                relevance=relevance,
            ))
    return results


def _infer_segment(well_objects: List[Dict], well_name: str) -> str:
    """Infer the well's reservoir segment from RDDMS relations or title."""
    matched = _match_well(well_objects, well_name)
    for obj in matched:
        for rel in obj.get("relations", []):
            name = rel.get("name", "")
            if any(kw in name.lower() for kw in ("segment", "region", "block", "compartment")):
                return name
        # Check title for segment keywords
        title = obj.get("title", "")
        # Generic pattern: pick up CamelCase segment names
        segments = re.findall(r'[A-Z][a-z]+(?:[A-Z][a-z]+)+', title)
        if segments:
            return segments[0]
    return "unknown"


# ──────────────────────────────────────────────────────────────────────────────
# Main query engine - orchestrates live data fetches
# ──────────────────────────────────────────────────────────────────────────────

async def run_connectivity_query(req: ConnectivityRequest, token: str) -> ConnectivityResult:
    """Execute connectivity assessment using live OSDU/RDDMS data from any dataspace."""
    result = ConnectivityResult()
    dataspace = req.dataspace

    # Extract field name for catalog queries: "maap/drogon" → "Drogon"
    field_name = dataspace.split("/")[-1].replace("_", " ").replace("-", " ").title()

    # ── Parallel data fetch from RDDMS + catalog ─────────────────────────
    fetch_results = await asyncio.gather(
        _fetch_wells(token, dataspace),
        _fetch_markers(token, dataspace),
        _fetch_faults(token, dataspace),
        _fetch_grid_properties(token, dataspace),
        _fetch_fault_connectivity(token, field_name),
        _fetch_bd_records(token, field_name),
        return_exceptions=True,
    )

    wells, markers, faults, grid_props, fault_conn, bd_records = fetch_results

    # Gracefully handle individual failures
    if isinstance(wells, Exception):
        log.warning("Well fetch failed: %s", wells); wells = []
    if isinstance(markers, Exception):
        log.warning("Marker fetch failed: %s", markers); markers = []
    if isinstance(faults, Exception):
        log.warning("Fault fetch failed: %s", faults); faults = []
    if isinstance(grid_props, Exception):
        log.warning("Grid prop fetch failed: %s", grid_props); grid_props = []
    if isinstance(fault_conn, Exception):
        log.warning("Fault conn fetch failed: %s", fault_conn); fault_conn = []
    if isinstance(bd_records, Exception):
        log.warning("BD fetch failed: %s", bd_records); bd_records = []

    # Production (sequential - depends on well names)
    prod_records = []
    if req.include_production:
        try:
            prod_records = await _fetch_production_records(token, [req.well_a, req.well_b])
        except Exception as e:
            log.debug("Production fetch failed: %s", e)

    # ── 1. Stratigraphic assessment ──────────────────────────────────────
    zones_a = _extract_zones_from_markers(markers, req.well_a)
    zones_b = _extract_zones_from_markers(markers, req.well_b)
    target_zone = req.zone

    if target_zone and target_zone in zones_a and target_zone in zones_b:
        result.same_zone = True
        result.zone_detail = f"Both wells penetrate {target_zone}"
    elif zones_a and zones_b and (set(zones_a) & set(zones_b)):
        common = sorted(set(zones_a) & set(zones_b))
        result.same_zone = True
        result.zone_detail = f"Wells share zone(s): {', '.join(common)}"
    elif not zones_a and not zones_b:
        result.zone_detail = "No marker data found - cannot assess stratigraphy"
    else:
        result.same_zone = False
        result.zone_detail = f"No common zone: {req.well_a}={zones_a or '?'}, {req.well_b}={zones_b or '?'}"

    # ── 2. Structural assessment (faults) ────────────────────────────────
    seg_a = _infer_segment(wells, req.well_a)
    seg_b = _infer_segment(wells, req.well_b)

    if req.include_faults:
        if seg_a == seg_b and seg_a != "unknown":
            result.structural_summary = f"Same segment ({seg_a}) - no bounding faults"
        elif seg_a == "unknown" or seg_b == "unknown":
            if faults:
                result.structural_summary = (
                    f"Segment assignment uncertain. "
                    f"{len(faults)} fault(s) in {dataspace} - listed for reference."
                )
                for fo in faults[:5]:
                    result.faults_between.append(FaultAssessment(
                        fault_name=fo.get("title", "?"),
                        seal_quality="unknown",
                        description="Segment membership undetermined",
                    ))
            else:
                result.structural_summary = "No fault data found in RDDMS"
        else:
            found_faults = _find_faults_between_wells(faults, fault_conn, seg_a, seg_b)
            result.faults_between = found_faults
            if found_faults:
                with_trans = [f for f in found_faults if f.transmissibility is not None]
                if with_trans:
                    worst = min(with_trans, key=lambda x: x.transmissibility)
                    result.structural_summary = (
                        f"Fault {worst.fault_name} between {seg_a} ↔ {seg_b} "
                        f"(trans={worst.transmissibility:.2f}, {worst.seal_quality})"
                    )
                else:
                    result.structural_summary = (
                        f"{len(found_faults)} fault(s) between {seg_a} ↔ {seg_b} "
                        f"(transmissibility not quantified)"
                    )
            else:
                result.structural_summary = f"No direct fault found between {seg_a} and {seg_b}"

    # ── 3. Property corridor ─────────────────────────────────────────────
    props = _extract_property_stats(grid_props)
    if props:
        quality = _assess_property_quality(props)
        result.property_corridor = PropertyCorridor(
            zone=target_zone or "all",
            mean_porosity=round(props["porosity"], 3) if "porosity" in props else None,
            mean_permeability=round(props["permeability"], 1) if "permeability" in props else None,
            mean_ntg=round(props["ntg"], 3) if "ntg" in props else None,
            mean_sw=round(props["sw"], 3) if "sw" in props else None,
            quality_assessment=quality,
        )
        # Apply user thresholds
        if req.property_filters:
            f = req.property_filters
            passes = True
            if "ntg_min" in f and props.get("ntg", 1.0) < f["ntg_min"]:
                passes = False
            if "kh_min" in f and props.get("permeability", 9999) < f["kh_min"]:
                passes = False
            if "sw_max" in f and props.get("sw", 0.0) > f["sw_max"]:
                passes = False
            if not passes:
                result.property_corridor.quality_assessment = "poor (below filter thresholds)"
    else:
        result.property_corridor = PropertyCorridor(
            zone=target_zone or "all",
            quality_assessment="no data - grid properties not found in RDDMS",
        )

    # ── 4. Production response ───────────────────────────────────────────
    if req.include_production and prod_records:
        for wname in [req.well_a, req.well_b]:
            prod = _extract_production_summary(prod_records, wname)
            if prod:
                result.production.append(prod)
        if len(result.production) == 2:
            p1, p2 = result.production
            if p1.performance_rating != p2.performance_rating:
                poor = p1 if p1.performance_rating == "poor" else p2
                good = p2 if p1.performance_rating == "poor" else p1
                wcut_str = ""
                if poor.current_water_cut is not None and good.current_water_cut is not None:
                    wcut_str = f"WCT {poor.current_water_cut:.0%} vs {good.current_water_cut:.0%}"
                result.production_summary = f"{poor.well} underperforms vs {good.well}: {wcut_str}"
            else:
                result.production_summary = "Similar production performance"
    elif req.include_production:
        result.production_summary = "No per-well production records found in catalog"

    # ── 5. BD evidence ───────────────────────────────────────────────────
    if req.include_bd_evidence and bd_records:
        fault_names = [f.fault_name for f in result.faults_between]
        result.bd_evidence = _filter_relevant_bd(
            bd_records, [req.well_a, req.well_b], fault_names
        )

    # ── 6. Synthesis ─────────────────────────────────────────────────────
    if seg_a == seg_b and seg_a != "unknown":
        result.connected = True
        result.confidence = "high"
        result.summary = (
            f"Wells {req.well_a} and {req.well_b} are in the same segment ({seg_a}) "
            f"- high confidence connectivity."
        )
    elif result.faults_between:
        with_trans = [f for f in result.faults_between if f.transmissibility is not None]
        if with_trans:
            best_trans = max(f.transmissibility for f in with_trans)
            if best_trans > 0.7:
                result.connected = True
                result.confidence = "high"
            elif best_trans > 0.3:
                result.connected = True
                result.confidence = "medium"
            else:
                result.connected = None
                result.confidence = "low"
            result.summary = (
                f"{'Connected' if result.connected else 'Uncertain connectivity'} "
                f"between {req.well_a} and {req.well_b} via "
                f"{result.faults_between[0].fault_name} (trans={best_trans:.2f})."
            )
        else:
            result.connected = None
            result.confidence = "low"
            result.summary = (
                f"Faults detected but transmissibility not quantified. "
                f"Ingest fault property records for definitive assessment."
            )
    else:
        result.connected = None
        result.confidence = "low"
        result.summary = (
            f"Insufficient structural data in {dataspace}. "
            f"Ensure wells, faults, and properties are ingested."
        )

    # ── 7. Recommendations ───────────────────────────────────────────────
    if result.connected is None or result.confidence == "low":
        if not fault_conn:
            result.recommendations.append("Ingest fault transmissibility records to quantify seal")
        if not prod_records:
            result.recommendations.append("Ingest per-well production for performance comparison")
        result.recommendations.append("Consider 4D seismic or inter-well tracer for confirmation")
    if any(f.seal_quality == "baffle" for f in result.faults_between):
        result.recommendations.append("Evaluate infill well in isolated segment")
    if result.property_corridor and "poor" in result.property_corridor.quality_assessment:
        result.recommendations.append("Review depositional model - low NTG may indicate pinch-out")
    if any(p.performance_rating == "poor" for p in result.production):
        result.recommendations.append("Investigate poor producer - possible connectivity/sweep issue")

    return result


# ──────────────────────────────────────────────────────────────────────────────
# FastAPI routes
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/connectivity", response_class=HTMLResponse)
async def connectivity_page(request: Request):
    """Render the Connectivity Explorer UI."""
    return templates.TemplateResponse(
        request, "connectivity.html", {},
        media_type="text/html",
    )


@router.post("/api/connectivity/query")
async def connectivity_query(request: Request, req: ConnectivityRequest):
    """Execute a connectivity query using live OSDU + RDDMS data."""
    try:
        token = _access_token(request)
        result = await run_connectivity_query(req, token)
        return JSONResponse(content=result.model_dump())
    except Exception as e:
        log.exception("Connectivity query failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/connectivity/wells")
async def connectivity_wells(request: Request, dataspace: str = "maap/drogon"):
    """Return available wells by querying RDDMS for the given dataspace."""
    try:
        token = _access_token(request)
        wells = await _fetch_wells(token, dataspace)
        result = []
        seen = set()
        for w in wells:
            title = w.get("title", "")
            tname = w.get("typeName", "")
            if "WellboreFeature" in tname or "WellboreTrajectory" in tname:
                if title not in seen:
                    seen.add(title)
                    result.append({"name": title, "uuid": w.get("uuid", ""), "type": tname})
        return JSONResponse(content={"wells": result, "dataspace": dataspace})
    except Exception as e:
        log.debug("Wells fetch error: %s", e)
        return JSONResponse(content={"wells": [], "dataspace": dataspace, "error": str(e)})


@router.get("/api/connectivity/segments")
async def connectivity_segments(request: Request, dataspace: str = "maap/drogon"):
    """Return fault connectivity data from OSDU catalog + RDDMS."""
    try:
        token = _access_token(request)
        field_name = dataspace.split("/")[-1].replace("_", " ").title()
        fault_conn, faults_rddms = await asyncio.gather(
            _fetch_fault_connectivity(token, field_name),
            _fetch_faults(token, dataspace),
        )
        return JSONResponse(content={
            "dataspace": dataspace,
            "faults_catalog": fault_conn,
            "faults_rddms": [{"name": f.get("title"), "uuid": f.get("uuid")} for f in faults_rddms],
        })
    except Exception as e:
        log.debug("Segments fetch error: %s", e)
        return JSONResponse(content={"dataspace": dataspace, "error": str(e)})
