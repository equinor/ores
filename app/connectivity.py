"""
connectivity.py - Connectivity query engine for field development workflows.

Provides a high-level query that combines:
  1. Stratigraphic correlation (are wells in the same zone?)
  2. Structural analysis (are there faults between them?)
  3. Property quality assessment (NTG, permeability along corridor)
  4. Business decision evidence (risk records, 4D results)
  5. Production response (per-well performance comparison)

This is the backend for the Connectivity Explorer UI.

Usage via API:
  POST /api/connectivity/query
  {
    "well_a": "55/33-A-2",
    "well_b": "55/33-A-3",
    "zone": "Valysar",
    "property_filters": {"ntg_min": 0.5, "kh_min": 100, "sw_max": 0.6},
    "include_faults": true,
    "include_production": true,
    "include_bd_evidence": true
  }
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import os

from . import osdu
from .common import access_token as _access_token

router = APIRouter()
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))
log = logging.getLogger("rddms-admin.connectivity")


# ──────────────────────────────────────────────────────────────────────────────
# Data model
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
    transmissibility: float
    seal_quality: str  # "open", "moderate", "baffle", "seal"
    segments_connected: List[str]
    description: str


class PropertyCorridor(BaseModel):
    zone: str
    mean_porosity: Optional[float] = None
    mean_permeability: Optional[float] = None
    mean_ntg: Optional[float] = None
    mean_sw: Optional[float] = None
    quality_assessment: str  # "excellent", "good", "moderate", "poor"


class ProductionComparison(BaseModel):
    well: str
    segment: str
    peak_oil_rate: Optional[float] = None
    current_water_cut: Optional[float] = None
    cumulative_oil: Optional[float] = None
    performance_rating: str  # "good", "average", "poor"


class BDEvidence(BaseModel):
    record_type: str  # "Risk", "DevelopmentConcept", "Activity"
    name: str
    status: str
    description: str
    relevance: str  # Why this is relevant to the connectivity question


class ConnectivityResult(BaseModel):
    # Summary
    connected: Optional[bool] = None  # True/False/None(uncertain)
    confidence: str = "low"  # "high", "medium", "low"
    summary: str = ""

    # Stratigraphic assessment
    same_zone: bool = False
    zone_detail: str = ""

    # Structural assessment
    faults_between: List[FaultAssessment] = []
    structural_summary: str = ""

    # Property corridor
    property_corridor: Optional[PropertyCorridor] = None

    # Production evidence
    production: List[ProductionComparison] = []
    production_summary: str = ""

    # BD evidence chain
    bd_evidence: List[BDEvidence] = []

    # Recommendations
    recommendations: List[str] = []


# ──────────────────────────────────────────────────────────────────────────────
# Well / segment registry (from Drogon model)
# ──────────────────────────────────────────────────────────────────────────────

WELL_SEGMENTS = {
    "55/33-A-1": "CentralHorst",
    "55/33-A-2": "CentralHorst",
    "55/33-A-3": "EastLowland",
    "55/33-A-4": "WestLowland",
    "55/33-A-5": "CentralHorst",
    "55/33-A-6": "EastLowland",
    # Short names
    "A-1": "CentralHorst",
    "A-2": "CentralHorst",
    "A-3": "EastLowland",
    "A-4": "WestLowland",
    "A-5": "CentralHorst",
    "A-6": "EastLowland",
}

WELL_ZONES = {
    "55/33-A-1": ["Valysar", "Therys"],
    "55/33-A-2": ["Valysar"],
    "55/33-A-3": ["Valysar"],
    "55/33-A-4": ["Valysar", "Volon"],
    "55/33-A-5": ["Valysar"],
    "55/33-A-6": ["Valysar", "Therys"],
}

# Fault connectivity matrix: (segA, segB) → fault info
FAULT_MATRIX = {
    ("CentralHorst", "WestLowland"): {
        "name": "F1", "trans": 0.80, "quality": "open",
        "desc": "Good communication - 4D confirms pressure support",
    },
    ("CentralHorst", "EastLowland"): {
        "name": "F2", "trans": 0.15, "quality": "baffle",
        "desc": "Partial baffle - shale smear in Therys, conduit in Valysar",
    },
    ("CentralNorth", "EastLowland"): {
        "name": "F3", "trans": 0.10, "quality": "baffle",
        "desc": "Strong baffle - juxtaposition seal (Valysar vs Therys shale)",
    },
    ("WestLowland", "CentralSouth"): {
        "name": "F4", "trans": 0.45, "quality": "moderate",
        "desc": "Moderate - partial juxtaposition, some sand-on-sand windows",
    },
    ("NorthHorst", "CentralRamp"): {
        "name": "F5", "trans": 0.60, "quality": "moderate",
        "desc": "Moderate-good - tracer detected across fault",
    },
    ("CentralRamp", "CentralHorst"): {
        "name": "F6", "trans": 0.95, "quality": "open",
        "desc": "Essentially open - relay ramp with full sand juxtaposition",
    },
}

# Segment-level property averages (from grid properties)
SEGMENT_PROPERTIES = {
    "CentralHorst": {"porosity": 0.24, "permeability": 320.0, "ntg": 0.68, "sw": 0.28},
    "EastLowland": {"porosity": 0.19, "permeability": 85.0, "ntg": 0.42, "sw": 0.45},
    "WestLowland": {"porosity": 0.22, "permeability": 210.0, "ntg": 0.58, "sw": 0.32},
    "CentralSouth": {"porosity": 0.21, "permeability": 180.0, "ntg": 0.55, "sw": 0.35},
    "CentralNorth": {"porosity": 0.23, "permeability": 250.0, "ntg": 0.62, "sw": 0.30},
    "NorthHorst": {"porosity": 0.20, "permeability": 150.0, "ntg": 0.50, "sw": 0.38},
    "CentralRamp": {"porosity": 0.22, "permeability": 200.0, "ntg": 0.60, "sw": 0.33},
}

# Per-well production summary (from gen_well_production_dg2.py profiles)
WELL_PRODUCTION = {
    "55/33-A-1": {"peak_oil": 3500, "current_wcut": 0.35, "cum_oil": 2.8e6, "rating": "good"},
    "55/33-A-2": {"peak_oil": 3400, "current_wcut": 0.32, "cum_oil": 2.6e6, "rating": "good"},
    "55/33-A-3": {"peak_oil": 2100, "current_wcut": 0.58, "cum_oil": 1.4e6, "rating": "poor"},
    "55/33-A-4": {"peak_oil": 2700, "current_wcut": 0.42, "cum_oil": 2.0e6, "rating": "average"},
}

# BD evidence records relevant to connectivity
BD_EVIDENCE_RECORDS = [
    {
        "type": "Risk",
        "name": "Drogon-FaultCompartment",
        "status": "Mitigated (High → Low)",
        "desc": "Fault transmissibility and reservoir compartmentalization risk. 4D seismic confirms communication across F1, F5, F6. F2/F3 remain as partial baffles.",
        "relevance": "Directly addresses inter-segment connectivity uncertainty",
    },
    {
        "type": "DevelopmentConcept",
        "name": "Drogon-DG2-InfillWells",
        "status": "Contingent (Phase 2)",
        "desc": "Infill wells targeting isolated fault compartments. Trigger: confirmed isolation by 4D/tracer. Candidate: East Lowland (poor sweep via A-3).",
        "relevance": "Poor A-3 performance attributed to F2/F3 baffling",
    },
    {
        "type": "Activity",
        "name": "4D Seismic Acquisition (planned)",
        "status": "Planned Q3 2021",
        "desc": "4D seismic to confirm/deny inter-segment pressure communication. Priority: East Lowland isolation hypothesis.",
        "relevance": "Will resolve remaining connectivity uncertainty for F2/F3",
    },
    {
        "type": "Activity",
        "name": "Water Tracer Injection (A-5)",
        "status": "Completed Q2 2020",
        "desc": "Tracer injected in A-5 (CentralHorst). Detected in A-1 (same segment, 3 months) and A-4 (WestLowland via F1, 8 months). NOT detected in A-3 (EastLowland).",
        "relevance": "Confirms F2 acts as baffle — no tracer communication to East Lowland",
    },
]


def _resolve_well_name(name: str) -> str:
    """Normalize well name to full form."""
    name = name.strip()
    if name in WELL_SEGMENTS:
        return name
    # Try matching short form
    for full_name in WELL_SEGMENTS:
        if full_name.endswith(name) or name in full_name:
            return full_name
    return name


def _find_faults_between(seg_a: str, seg_b: str) -> List[Dict]:
    """Find faults separating two segments (check both orderings)."""
    faults = []
    for (s1, s2), info in FAULT_MATRIX.items():
        if (s1 == seg_a and s2 == seg_b) or (s1 == seg_b and s2 == seg_a):
            faults.append(info)
    return faults


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
    else:
        return "poor"


def _compute_corridor_properties(seg_a: str, seg_b: str) -> Dict[str, float]:
    """Average properties along the corridor between two segments."""
    props_a = SEGMENT_PROPERTIES.get(seg_a, {})
    props_b = SEGMENT_PROPERTIES.get(seg_b, {})
    if not props_a or not props_b:
        return {}
    return {
        "porosity": (props_a["porosity"] + props_b["porosity"]) / 2,
        "permeability": (props_a["permeability"] + props_b["permeability"]) / 2,
        "ntg": (props_a["ntg"] + props_b["ntg"]) / 2,
        "sw": (props_a["sw"] + props_b["sw"]) / 2,
    }


def _filter_relevant_bd(seg_a: str, seg_b: str, faults: List[Dict]) -> List[BDEvidence]:
    """Select BD records relevant to this connectivity question."""
    fault_names = {f["name"] for f in faults}
    results = []
    for bd in BD_EVIDENCE_RECORDS:
        # Include if mentions relevant faults or segments
        text = bd["desc"].lower()
        relevant = False
        if any(fn.lower() in text for fn in fault_names):
            relevant = True
        if seg_a.lower() in text or seg_b.lower() in text:
            relevant = True
        if "compartment" in text or "connectivity" in text:
            relevant = True
        if relevant:
            results.append(BDEvidence(
                record_type=bd["type"],
                name=bd["name"],
                status=bd["status"],
                description=bd["desc"],
                relevance=bd["relevance"],
            ))
    return results


# ──────────────────────────────────────────────────────────────────────────────
# Main query engine
# ──────────────────────────────────────────────────────────────────────────────

def run_connectivity_query(req: ConnectivityRequest) -> ConnectivityResult:
    """Execute the full connectivity assessment."""
    result = ConnectivityResult()

    well_a = _resolve_well_name(req.well_a)
    well_b = _resolve_well_name(req.well_b)

    seg_a = WELL_SEGMENTS.get(well_a)
    seg_b = WELL_SEGMENTS.get(well_b)

    if not seg_a:
        result.summary = f"Unknown well: {req.well_a}"
        return result
    if not seg_b:
        result.summary = f"Unknown well: {req.well_b}"
        return result

    # ── 1. Stratigraphic assessment ──────────────────────────────────────
    zones_a = WELL_ZONES.get(well_a, [])
    zones_b = WELL_ZONES.get(well_b, [])
    target_zone = req.zone or "Valysar"

    if target_zone in zones_a and target_zone in zones_b:
        result.same_zone = True
        result.zone_detail = f"Both wells penetrate {target_zone} Fm (shallow marine)"
    elif set(zones_a) & set(zones_b):
        common = set(zones_a) & set(zones_b)
        result.same_zone = True
        result.zone_detail = f"Wells share zone(s): {', '.join(common)}"
    else:
        result.same_zone = False
        result.zone_detail = f"No common zone: {well_a}={zones_a}, {well_b}={zones_b}"

    # ── 2. Structural assessment (faults) ────────────────────────────────
    if req.include_faults:
        if seg_a == seg_b:
            result.structural_summary = f"Same segment ({seg_a}) — no bounding faults"
        else:
            faults = _find_faults_between(seg_a, seg_b)
            for f in faults:
                result.faults_between.append(FaultAssessment(
                    fault_name=f["name"],
                    transmissibility=f["trans"],
                    seal_quality=f["quality"],
                    segments_connected=[seg_a, seg_b],
                    description=f["desc"],
                ))
            if faults:
                worst = min(faults, key=lambda x: x["trans"])
                result.structural_summary = (
                    f"Fault {worst['name']} between {seg_a} ↔ {seg_b} "
                    f"(trans={worst['trans']:.2f}, {worst['quality']})"
                )
            else:
                result.structural_summary = (
                    f"No direct fault boundary between {seg_a} and {seg_b} — "
                    f"may require multi-hop path"
                )

    # ── 3. Property corridor ─────────────────────────────────────────────
    corridor_props = _compute_corridor_properties(seg_a, seg_b)
    if corridor_props:
        quality = _assess_property_quality(corridor_props)
        result.property_corridor = PropertyCorridor(
            zone=target_zone,
            mean_porosity=round(corridor_props["porosity"], 3),
            mean_permeability=round(corridor_props["permeability"], 1),
            mean_ntg=round(corridor_props["ntg"], 3),
            mean_sw=round(corridor_props["sw"], 3),
            quality_assessment=quality,
        )

        # Apply user property filters
        if req.property_filters:
            filters = req.property_filters
            passes = True
            if "ntg_min" in filters and corridor_props["ntg"] < filters["ntg_min"]:
                passes = False
            if "kh_min" in filters and corridor_props["permeability"] < filters["kh_min"]:
                passes = False
            if "sw_max" in filters and corridor_props["sw"] > filters["sw_max"]:
                passes = False
            if not passes:
                result.property_corridor.quality_assessment = "poor (below filter thresholds)"

    # ── 4. Production response ───────────────────────────────────────────
    if req.include_production:
        for wname in [well_a, well_b]:
            prod = WELL_PRODUCTION.get(wname)
            if prod:
                result.production.append(ProductionComparison(
                    well=wname,
                    segment=WELL_SEGMENTS[wname],
                    peak_oil_rate=prod["peak_oil"],
                    current_water_cut=prod["current_wcut"],
                    cumulative_oil=prod["cum_oil"],
                    performance_rating=prod["rating"],
                ))

        # Compare performance
        if len(result.production) == 2:
            p1, p2 = result.production
            if p1.performance_rating != p2.performance_rating:
                poor_well = p1 if p1.performance_rating == "poor" else p2
                good_well = p2 if p1.performance_rating == "poor" else p1
                result.production_summary = (
                    f"{poor_well.well} ({poor_well.segment}) underperforms vs "
                    f"{good_well.well} ({good_well.segment}): "
                    f"WCT {poor_well.current_water_cut:.0%} vs {good_well.current_water_cut:.0%}, "
                    f"Cum.Oil {poor_well.cumulative_oil/1e6:.1f} vs {good_well.cumulative_oil/1e6:.1f} MSm³"
                )
            else:
                result.production_summary = "Similar production performance"

    # ── 5. BD evidence ───────────────────────────────────────────────────
    if req.include_bd_evidence:
        faults_info = [{"name": f.fault_name} for f in result.faults_between]
        result.bd_evidence = _filter_relevant_bd(seg_a, seg_b, faults_info)

    # ── 6. Synthesis: connected or not? ──────────────────────────────────
    if seg_a == seg_b:
        result.connected = True
        result.confidence = "high"
        result.summary = (
            f"Wells {well_a} and {well_b} are in the same segment ({seg_a}) "
            f"with no intervening faults — high confidence connectivity."
        )
    elif result.faults_between:
        best_trans = max(f.transmissibility for f in result.faults_between)
        if best_trans > 0.7:
            result.connected = True
            result.confidence = "high"
        elif best_trans > 0.3:
            result.connected = True
            result.confidence = "medium"
        else:
            result.connected = None  # Uncertain
            result.confidence = "low"

        trans_desc = f"trans={best_trans:.2f}"
        prop_desc = ""
        if result.property_corridor:
            prop_desc = f", corridor {result.property_corridor.quality_assessment} quality"

        result.summary = (
            f"{'Connected' if result.connected else 'Uncertain connectivity'} "
            f"between {well_a} ({seg_a}) and {well_b} ({seg_b}). "
            f"Fault barrier: {result.faults_between[0].fault_name} ({trans_desc}){prop_desc}."
        )
    else:
        result.connected = None
        result.confidence = "low"
        result.summary = (
            f"No direct structural connection found between {seg_a} and {seg_b}. "
            f"Multi-segment path analysis needed."
        )

    # ── 7. Recommendations ───────────────────────────────────────────────
    if result.connected is None or result.confidence == "low":
        result.recommendations.append("Acquire 4D seismic to resolve connectivity uncertainty")
        result.recommendations.append("Consider inter-well tracer test")
    if result.faults_between and any(f.seal_quality == "baffle" for f in result.faults_between):
        result.recommendations.append("Evaluate infill well in isolated segment")
        result.recommendations.append("Consider fault reactivation pressure analysis")
    if result.property_corridor and "poor" in result.property_corridor.quality_assessment:
        result.recommendations.append("Review depositional model — low NTG may indicate channel pinch-out")
    if any(p.performance_rating == "poor" for p in result.production):
        result.recommendations.append("Investigate poor producer — possible completion or sweep issue")

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
async def connectivity_query(req: ConnectivityRequest):
    """Execute a connectivity query and return structured results."""
    try:
        result = run_connectivity_query(req)
        return JSONResponse(content=result.model_dump())
    except Exception as e:
        log.exception("Connectivity query failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/connectivity/wells")
async def connectivity_wells():
    """Return available wells for the connectivity query UI."""
    wells = []
    for name, segment in WELL_SEGMENTS.items():
        if "/" in name:  # Only full names
            zones = WELL_ZONES.get(name, [])
            wells.append({
                "name": name,
                "segment": segment,
                "zones": zones,
                "type": "injector" if name in ("55/33-A-5", "55/33-A-6") else "producer",
            })
    return JSONResponse(content={"wells": wells})


@router.get("/api/connectivity/segments")
async def connectivity_segments():
    """Return segment properties for the connectivity query UI."""
    return JSONResponse(content={
        "segments": SEGMENT_PROPERTIES,
        "faults": [
            {
                "name": info["name"],
                "segments": list(segs),
                "transmissibility": info["trans"],
                "quality": info["quality"],
            }
            for segs, info in FAULT_MATRIX.items()
        ],
    })
