"""
app/graphql_refdata.py - RESQML reference data and alias resolution.

Static reference tables (property kinds, RESQML types, operators) and
simple REST endpoints for the GraphQL query builder UI.
Extracted from graphql_router.py for clarity.
"""
from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()

# ──────────────────────────────────────────────────────────────────────────────
# RESQML Standard Property Kinds (Energistics RESQML 2.0.1 spec)
# ──────────────────────────────────────────────────────────────────────────────

STANDARD_PROPERTY_KINDS: List[Dict[str, Any]] = [
    {"name": "porosity", "aliases": ["poro", "phit", "phi", "nphi"], "description": "Fraction of void space in rock", "uom": "v/v"},
    {"name": "rock permeability", "aliases": ["perm", "permx", "permy", "permz", "klogh", "kh", "permeability"], "description": "Ability of rock to transmit fluids", "uom": "mD"},
    {"name": "saturation", "aliases": ["sw", "so", "sg", "swat", "swatinit", "swl", "swcr", "sgas", "soil", "water saturation", "oil saturation", "gas saturation"], "description": "Fraction of pore space filled with fluid", "uom": "v/v"},
    {"name": "net-to-gross", "aliases": ["ntg", "net_fraction", "netfrac", "ntg_pem", "netfrac_pem"], "description": "Net-to-gross ratio", "uom": "v/v"},
    {"name": "depth", "aliases": ["tvd", "tvdss", "z", "cell_z", "md"], "description": "Vertical depth (TVD or TVDSS)", "uom": "m"},
    {"name": "pressure", "aliases": ["pres", "pressure", "bhp", "pp"], "description": "Formation or fluid pressure", "uom": "bar"},
    {"name": "temperature", "aliases": ["temp", "temperature"], "description": "Formation temperature", "uom": "degC"},
    {"name": "volume", "aliases": ["vol", "bulk", "total_bulk", "pore", "total_pore"], "description": "Cell or pore volume", "uom": "m3"},
    {"name": "velocity", "aliases": ["vp", "vs", "velocity", "velmod"], "description": "Seismic P/S-wave velocity", "uom": "m/s"},
    {"name": "density", "aliases": ["dens", "rhob", "density", "bulk_density"], "description": "Rock or fluid density", "uom": "g/cm3"},
    {"name": "acoustic impedance", "aliases": ["ai", "impedance"], "description": "Product of velocity × density", "uom": "kg/m2/s"},
    {"name": "gamma ray", "aliases": ["gr", "gamma", "gamma_ray", "sgr", "cgr"], "description": "Natural gamma radiation log", "uom": "API"},
    {"name": "shale volume", "aliases": ["vsh", "vphyl", "vclay", "vshale", "volume of shale"], "description": "Volume fraction of shale/clay", "uom": "v/v"},
    {"name": "facies", "aliases": ["facies", "lithology", "lith"], "description": "Discrete rock type classification", "uom": "unitless"},
    {"name": "zone", "aliases": ["zone", "region", "fipnum", "fipzon", "eqlnum", "pvtnum", "satnum", "multnum", "general discrete"], "description": "Integer zone/region identifier", "uom": "unitless"},
    {"name": "fault block", "aliases": ["faultblock", "fault_block", "faultblk"], "description": "Fault-bounded compartment index", "uom": "unitless"},
    {"name": "free water level", "aliases": ["fwl", "fwl_wg", "owc", "goc"], "description": "Oil/Water or Gas/Oil contact depth", "uom": "m"},
    {"name": "relative permeability", "aliases": ["krw", "kro", "krg", "krel"], "description": "Relative permeability curves", "uom": "fraction"},
    {"name": "capillary pressure", "aliases": ["pc", "pcow", "pcgo"], "description": "Capillary pressure", "uom": "bar"},
]

# ──────────────────────────────────────────────────────────────────────────────
# RESQML 2.0 object types (most common in OSDU/RDDMS)
# ──────────────────────────────────────────────────────────────────────────────

RESQML_TYPES: List[Dict[str, Any]] = [
    {"name": "resqml20.obj_IjkGridRepresentation", "short": "IjkGrid", "category": "Grid", "description": "3D geocellular grid (corner-point or parametric)"},
    {"name": "resqml20.obj_Grid2dRepresentation", "short": "Grid2D", "category": "Surface", "description": "2D regular grid (depth/time surface maps)"},
    {"name": "resqml20.obj_PolylineSetRepresentation", "short": "PolylineSet", "category": "Surface", "description": "Fault traces, contour lines, polygon boundaries"},
    {"name": "resqml20.obj_PointSetRepresentation", "short": "PointSet", "category": "Surface", "description": "Scattered point cloud (e.g. well picks, seismic picks)"},
    {"name": "resqml20.obj_WellboreFeature", "short": "WellboreFeature", "category": "Well", "description": "Well identity (top-level wellbore)"},
    {"name": "resqml20.obj_WellboreInterpretation", "short": "WellboreInterp", "category": "Well", "description": "Geological interpretation of a wellbore"},
    {"name": "resqml20.obj_WellboreTrajectoryRepresentation", "short": "Trajectory", "category": "Well", "description": "Well path in 3D space (MD, inclination, azimuth)"},
    {"name": "resqml20.obj_DeviationSurveyRepresentation", "short": "DeviationSurvey", "category": "Well", "description": "Measured deviation survey data"},
    {"name": "resqml20.obj_WellboreFrameRepresentation", "short": "WellFrame", "category": "Well", "description": "Sampling frame for well logs (MD stations)"},
    {"name": "resqml20.obj_WellboreMarkerFrameRepresentation", "short": "WellMarkers", "category": "Well", "description": "Formation tops / horizon picks along wellbore"},
    {"name": "resqml20.obj_MdDatum", "short": "MdDatum", "category": "Well", "description": "Measured depth reference point (kelly bushing, etc.)"},
    {"name": "resqml20.obj_ContinuousProperty", "short": "ContinuousProp", "category": "Property", "description": "Floating-point values (porosity, perm, sat, etc.)"},
    {"name": "resqml20.obj_DiscreteProperty", "short": "DiscreteProp", "category": "Property", "description": "Integer values (facies, zone, region, etc.)"},
    {"name": "resqml20.obj_HorizonInterpretation", "short": "HorizonInterp", "category": "Stratigraphy", "description": "Geological interpretation of a horizon boundary"},
    {"name": "resqml20.obj_FaultInterpretation", "short": "FaultInterp", "category": "Stratigraphy", "description": "Geological interpretation of a fault"},
    {"name": "resqml20.obj_GeneticBoundaryFeature", "short": "GeneticBoundary", "category": "Stratigraphy", "description": "Horizon or unconformity as a geological feature"},
    {"name": "resqml20.obj_TectonicBoundaryFeature", "short": "TectonicBoundary", "category": "Stratigraphy", "description": "Fault as a geological feature"},
    {"name": "resqml20.obj_StratigraphicColumn", "short": "StratColumn", "category": "Stratigraphy", "description": "Ordered set of stratigraphic units"},
    {"name": "resqml20.obj_StratigraphicColumnRankInterpretation", "short": "StratRank", "category": "Stratigraphy", "description": "Ranked stratigraphic units (formations, groups)"},
    {"name": "resqml20.obj_StratigraphicUnitFeature", "short": "StratUnit", "category": "Stratigraphy", "description": "Named geological time unit (formation)"},
    {"name": "resqml20.obj_StratigraphicUnitInterpretation", "short": "StratUnitInterp", "category": "Stratigraphy", "description": "Interpretation of a stratigraphic unit"},
    {"name": "resqml20.obj_OrganizationFeature", "short": "OrgFeature", "category": "Organization", "description": "Structural/stratigraphic organization"},
    {"name": "resqml20.obj_GridConnectionSetRepresentation", "short": "GridConnSet", "category": "Grid", "description": "Non-neighbour connections between grid cells (faults)"},
    {"name": "resqml20.obj_LocalDepth3dCrs", "short": "DepthCRS", "category": "CRS", "description": "Local coordinate reference system (depth)"},
    {"name": "resqml20.obj_LocalTime3dCrs", "short": "TimeCRS", "category": "CRS", "description": "Local coordinate reference system (time)"},
    {"name": "resqml20.obj_PropertyKind", "short": "PropertyKind", "category": "Property", "description": "Custom property kind definition"},
    {"name": "resqml20.obj_Activity", "short": "Activity", "category": "Provenance", "description": "Workflow activity that created/modified objects"},
    {"name": "resqml20.obj_ActivityTemplate", "short": "ActivityTemplate", "category": "Provenance", "description": "Template for activity parameterization"},
]

# ──────────────────────────────────────────────────────────────────────────────
# Comparison operators
# ──────────────────────────────────────────────────────────────────────────────

OPERATORS: List[Dict[str, str]] = [
    {"value": "GT", "label": "> (greater than)", "symbol": ">"},
    {"value": "GTE", "label": "≥ (greater or equal)", "symbol": "≥"},
    {"value": "LT", "label": "< (less than)", "symbol": "<"},
    {"value": "LTE", "label": "≤ (less or equal)", "symbol": "≤"},
    {"value": "EQ", "label": "= (equal)", "symbol": "="},
    {"value": "BETWEEN", "label": "between (range)", "symbol": "↔"},
]

# Build alias → canonical lookup
ALIAS_TO_CANONICAL: Dict[str, str] = {}
for _pk in STANDARD_PROPERTY_KINDS:
    for _a in _pk["aliases"]:
        ALIAS_TO_CANONICAL[_a.lower()] = _pk["name"]
    ALIAS_TO_CANONICAL[_pk["name"].lower()] = _pk["name"]


# ──────────────────────────────────────────────────────────────────────────────
# REST endpoints
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/api/graphql/reference")
async def graphql_reference():
    """
    Return reference data for the query builder:
    - Standard RESQML property kinds with aliases
    - RESQML object types with categories
    - Comparison operators
    - Alias → canonical name lookup
    """
    return JSONResponse({
        "propertyKinds": STANDARD_PROPERTY_KINDS,
        "resqmlTypes": RESQML_TYPES,
        "operators": OPERATORS,
        "aliasMap": ALIAS_TO_CANONICAL,
    })


@router.get("/api/graphql/resolve-alias")
async def graphql_resolve_alias(term: str = ""):
    """
    Resolve a property term to canonical name(s).
    Supports loose matching: 'poro' → porosity, 'sw' → water saturation
    """
    term_lower = term.lower().strip()
    if not term_lower:
        return JSONResponse({"matches": [], "mode": "empty"})

    # Exact alias match
    if term_lower in ALIAS_TO_CANONICAL:
        canonical = ALIAS_TO_CANONICAL[term_lower]
        pk = next((p for p in STANDARD_PROPERTY_KINDS if p["name"] == canonical), None)
        return JSONResponse({"matches": [pk] if pk else [], "mode": "exact"})

    # Substring match across aliases and names
    matches = []
    for pk in STANDARD_PROPERTY_KINDS:
        if term_lower in pk["name"].lower():
            matches.append(pk)
        elif any(term_lower in a for a in pk["aliases"]):
            matches.append(pk)
    return JSONResponse({"matches": matches, "mode": "fuzzy"})
