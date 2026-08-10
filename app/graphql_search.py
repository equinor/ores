"""
GraphQL deep search & federated search - implementation module.

Extracted from graphql_router.py (P6b refactoring) to keep the
GraphQL router focused on schema wiring and basic resolvers.

Contains:
  • Strawberry types (output + input) shared across the schema
  • REST wrappers for RDDMS API calls
  • Deep search: PG-native and REST-based implementations
  • Federated search: OSDU catalog + local PG + remote RDDMS
  • Analysis helpers: statistics, thresholds, property kind extraction
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import re as _re
import urllib.parse
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import strawberry

from . import osdu
from .pg_backend import (
    get_pool as _get_pool,
    get_rddms_pool as _get_rddms_pool,
    ARY_TYPE_FMT as _ARY_TYPE_FMT,
    pg_schema_for_dataspace as _pg_schema_for_dataspace,
    pg_list_dataspaces as _pg_list_dataspaces,
    pg_list_types as _pg_list_types,
    pg_list_resources as _pg_list_resources,
    pg_list_relations as _pg_list_relations,
    pg_list_arrays as _pg_list_arrays,
    pg_read_array as _pg_read_array,
    pg_batch_property_sources as _pg_batch_property_sources,
    pg_batch_relations as _pg_batch_relations,
    pg_batch_arrays_for_objects as _pg_batch_arrays_for_objects,
    pg_read_array_by_id as _pg_read_array_by_id,
)

log = logging.getLogger("rddms-admin.graphql")


# ──────────────────────────────────────────────────────────────────────────────
# RESQML type registry - categories and common types
# ──────────────────────────────────────────────────────────────────────────────

# Mapping: category → list of RESQML types in that category
RESQML_TYPE_CATEGORIES: Dict[str, List[str]] = {
    "grid": [
        "resqml20.obj_IjkGridRepresentation",
        "resqml20.obj_UnstructuredGridRepresentation",
        "resqml20.obj_Grid2dRepresentation",
        "resqml20.obj_GridConnectionSetRepresentation",
        "resqml22.obj_IjkGridRepresentation",
        "resqml22.obj_Grid2dRepresentation",
    ],
    "surface": [
        "resqml20.obj_TriangulatedSetRepresentation",
        "resqml20.obj_PolylineSetRepresentation",
        "resqml20.obj_PointSetRepresentation",
        "resqml20.obj_Grid2dRepresentation",
        "resqml22.obj_TriangulatedSetRepresentation",
        "resqml22.obj_PolylineSetRepresentation",
    ],
    "well": [
        "resqml20.obj_WellboreFeature",
        "resqml20.obj_WellboreTrajectoryRepresentation",
        "resqml20.obj_WellboreFrameRepresentation",
        "resqml20.obj_WellboreMarkerFrameRepresentation",
        "resqml20.obj_DeviationSurveyRepresentation",
        "resqml20.obj_WellboreInterpretation",
        "resqml20.obj_BlockedWellboreRepresentation",
        "resqml22.obj_WellboreFeature",
        "resqml22.obj_WellboreTrajectoryRepresentation",
        "resqml22.obj_WellboreFrameRepresentation",
    ],
    "structural": [
        "resqml20.obj_FaultInterpretation",
        "resqml20.obj_HorizonInterpretation",
        "resqml20.obj_GeobodyBoundaryInterpretation",
        "resqml20.obj_GeobodyInterpretation",
        "resqml20.obj_StructuralOrganizationInterpretation",
        "resqml20.obj_BoundaryFeature",
        "resqml20.obj_GeneticBoundaryFeature",
        "resqml20.obj_TectonicBoundaryFeature",
        "resqml22.obj_FaultInterpretation",
        "resqml22.obj_HorizonInterpretation",
    ],
    "stratigraphic": [
        "resqml20.obj_StratigraphicColumn",
        "resqml20.obj_StratigraphicColumnRankInterpretation",
        "resqml20.obj_StratigraphicUnitInterpretation",
        "resqml20.obj_StratigraphicOccurrenceInterpretation",
        "resqml22.obj_StratigraphicColumn",
        "resqml22.obj_StratigraphicColumnRankInterpretation",
    ],
    "property": [
        "resqml20.obj_ContinuousProperty",
        "resqml20.obj_DiscreteProperty",
        "resqml20.obj_CategoricalProperty",
        "resqml20.obj_PointsProperty",
        "resqml20.obj_CommentProperty",
        "resqml22.obj_ContinuousProperty",
        "resqml22.obj_DiscreteProperty",
        "resqml22.obj_CategoricalProperty",
    ],
    "seismic": [
        "resqml20.obj_SeismicLatticeFeature",
        "resqml20.obj_SeismicLineFeature",
        "resqml20.obj_Grid2dRepresentation",
    ],
    "crs": [
        "resqml20.obj_LocalDepth3dCrs",
        "resqml20.obj_LocalTime3dCrs",
        "resqml22.obj_LocalDepth3dCrs",
        "resqml22.obj_LocalTime3dCrs",
    ],
    "representation": [
        "resqml20.obj_IjkGridRepresentation",
        "resqml20.obj_UnstructuredGridRepresentation",
        "resqml20.obj_Grid2dRepresentation",
        "resqml20.obj_TriangulatedSetRepresentation",
        "resqml20.obj_PolylineSetRepresentation",
        "resqml20.obj_PointSetRepresentation",
        "resqml20.obj_WellboreTrajectoryRepresentation",
        "resqml20.obj_WellboreFrameRepresentation",
    ],
    "witsml": [
        "witsml21.Well",
        "witsml21.Wellbore",
        "witsml21.Log",
        "witsml21.ChannelSet",
        "witsml21.Trajectory",
    ],
}

# Flat list of all commonly-used types (for default scanning)
ALL_COMMON_RESQML_TYPES: List[str] = sorted(set(
    t for types in RESQML_TYPE_CATEGORIES.values() for t in types
    if t.startswith("resqml20.")  # default to v2.0 unless user specifies v2.2
))


def resolve_type_names(type_name: Optional[str] = None, category: Optional[str] = None) -> List[str]:
    """Resolve a type_name or category to a list of concrete RESQML types.

    - If type_name is given and is a known category key, expand it.
    - If type_name contains a wildcard (*), match against all known types.
    - Otherwise return [type_name] as-is.
    """
    if category:
        return RESQML_TYPE_CATEGORIES.get(category.lower(), [])
    if not type_name:
        return []
    # Check if type_name is a category alias
    if type_name.lower() in RESQML_TYPE_CATEGORIES:
        return RESQML_TYPE_CATEGORIES[type_name.lower()]
    # Wildcard match
    if "*" in type_name:
        import fnmatch
        return [t for t in ALL_COMMON_RESQML_TYPES if fnmatch.fnmatch(t, type_name)]
    return [type_name]


# ──────────────────────────────────────────────────────────────────────────────
# REST-based helpers (thin wrappers around osdu.* with URI parsing)
# ──────────────────────────────────────────────────────────────────────────────

_EML_URI_RE = _re.compile(
    r"(?:eml:///)?(?:dataspace\(['\"]?[^)]+['\"]?\)/)?"
    r"(?P<type>[\w.]+)\((?P<uuid>[0-9a-fA-F-]{36})\)"
)


def _parse_eml_entry(r: Dict[str, Any]) -> Dict[str, str]:
    """Extract uuid, name, and contentType from an RDDMS REST listing entry.

    The RDDMS REST API returns entries like::

        {"uri": "eml:///dataspace('ds')/resqml20.obj_Foo(uuid)", "name": "..."}

    There is **no** top-level ``UUID``, ``ContentType``, or ``Title`` key.
    This helper parses ``uri`` to fill those gaps.
    """
    uid = r.get("UUID") or r.get("Uuid") or r.get("uuid") or ""
    ct = r.get("ContentType") or r.get("contentType") or ""
    name = r.get("Title") or r.get("title") or r.get("name") or ""
    uri = r.get("uri") or ""

    if uri and (not uid or not ct):
        m = _EML_URI_RE.search(uri)
        if m:
            if not uid:
                uid = m.group("uuid")
            if not ct:
                ct = m.group("type")  # e.g. "resqml20.obj_ContinuousProperty"
    return {"uuid": uid, "contentType": ct, "name": name, "uri": uri}


async def _rest_list_dataspaces(token: str) -> List[Dict[str, Any]]:
    rows = await osdu.list_dataspaces(token)
    return [
        {"path": r.get("path") or r.get("Path") or r.get("DataspaceId") or "", "uri": r.get("uri", "")}
        for r in rows if (r.get("path") or r.get("Path") or r.get("DataspaceId"))
    ]


async def _rest_list_types(token: str, ds: str) -> List[Dict[str, Any]]:
    enc = urllib.parse.quote(ds, safe="")
    types = await osdu.list_types(token, enc)
    result = []
    for t in types or []:
        if isinstance(t, dict):
            result.append({"name": t.get("name") or "", "count": int(t.get("count") or 0)})
        elif isinstance(t, str):
            result.append({"name": t, "count": 0})
    return result


async def _rest_list_resources(token: str, ds: str, typ: str, limit: int = 100) -> List[Dict[str, Any]]:
    enc = urllib.parse.quote(ds, safe="")
    resources = await osdu.list_resources(token, enc, typ)
    items = []
    for r in (resources or [])[:limit]:
        parsed = _parse_eml_entry(r)
        uid = parsed["uuid"]
        title = parsed["name"] or (r.get("Citation") or {}).get("Title", "")
        if not uid:
            continue  # skip entries we can't identify
        items.append({"uuid": str(uid), "title": title, "type_name": typ, "raw": r})
    return items


async def _rest_get_resource(token: str, ds: str, typ: str, uuid: str) -> Dict[str, Any]:
    enc = urllib.parse.quote(ds, safe="")
    result = await osdu.get_resource(token, enc, typ, uuid)
    # RDDMS returns [{ … }] for single objects; unwrap the list.
    if isinstance(result, list) and len(result) == 1:
        return result[0]
    if isinstance(result, list) and len(result) > 1:
        return result[0]
    return result if isinstance(result, dict) else {}


async def _rest_list_targets(token: str, ds: str, typ: str, uuid: str) -> List[Dict[str, Any]]:
    enc = urllib.parse.quote(ds, safe="")
    return await osdu.list_targets(token, enc, typ, uuid)


async def _rest_list_sources(token: str, ds: str, typ: str, uuid: str) -> List[Dict[str, Any]]:
    enc = urllib.parse.quote(ds, safe="")
    return await osdu.list_sources(token, enc, typ, uuid)


async def _rest_list_arrays(token: str, ds: str, typ: str, uuid: str) -> List[Dict[str, Any]]:
    enc = urllib.parse.quote(ds, safe="")
    return await osdu.list_arrays(token, enc, typ, uuid)


async def _rest_read_array(token: str, ds: str, typ: str, uuid: str, path: str) -> List[float]:
    enc = urllib.parse.quote(ds, safe="")
    arr_data = await osdu.read_array(token, enc, typ, uuid, path_in_resource=path)
    inner = arr_data.get("data") or arr_data
    if isinstance(inner, dict):
        values = inner.get("data") or inner.get("values") or []
    elif isinstance(inner, list):
        values = inner
    else:
        values = []
    return [float(v) for v in values if v is not None]


# ──────────────────────────────────────────────────────────────────────────────
# Native GraphQL wrappers (GQL-first with REST fallback)
# These try the etp-client /graphql endpoint first. If unavailable or failing,
# they transparently fall back to the REST wrappers above.
# ──────────────────────────────────────────────────────────────────────────────

from .rddms_gql import gql_available, gql_query, Q_DATASPACES, Q_RESOURCES, Q_GRAPH_SEARCH, Q_TARGETS, Q_SOURCES, Q_ARRAYS


async def _gql_or_rest_list_dataspaces(token: str) -> List[Dict[str, Any]]:
    """List dataspaces: native GQL → REST fallback."""
    if await gql_available(token):
        try:
            result = await gql_query(token, Q_DATASPACES)
            data = result.get("data", {}).get("dataspaces") or []
            return [{"path": d.get("name", ""), "uri": d.get("uri", "")} for d in data]
        except Exception as e:
            log.debug("gql dataspaces failed, falling back to REST: %s", e)
    return await _rest_list_dataspaces(token)


async def _gql_or_rest_list_resources(token: str, ds: str, typ: str, limit: int = 50) -> List[Dict[str, Any]]:
    """List resources by type: native GQL → REST fallback."""
    if await gql_available(token):
        ds_uri = f"eml:///dataspace('{ds}')"
        try:
            result = await gql_query(token, Q_RESOURCES, {"uri": ds_uri, "types": [typ]})
            data = (result.get("data") or {}).get("resources") or []
            resources = []
            for r in data[:limit]:
                uri = r.get("uri", "")
                # Parse UUID and type from ETP URI
                parsed = _parse_eml_entry(uri)
                resources.append({
                    "uuid": parsed.get("uuid", ""),
                    "title": r.get("name", ""),
                    "type_name": parsed.get("type_name", r.get("dataObjectType", "")),
                })
            return resources
        except Exception as e:
            log.debug("gql resources failed, falling back to REST: %s", e)
    return await _rest_list_resources(token, ds, typ, limit)


async def _gql_or_rest_list_targets(token: str, ds: str, typ: str, uuid: str) -> List[Dict[str, Any]]:
    """List targets via native GQL graph → REST fallback."""
    if await gql_available(token):
        uri = _build_etp_uri(ds, typ, uuid)
        try:
            result = await gql_query(token, Q_TARGETS, {"uri": uri})
            resource = (result.get("data") or {}).get("resource")
            if resource:
                targets = resource.get("targets") or []
                return [
                    {"uri": t["uri"], "name": t.get("name", ""), "dataObjectType": t.get("dataObjectType", "")}
                    for t in targets
                ]
        except Exception as e:
            log.debug("gql targets failed, falling back to REST: %s", e)
    return await _rest_list_targets(token, ds, typ, uuid)


async def _gql_or_rest_list_sources(token: str, ds: str, typ: str, uuid: str) -> List[Dict[str, Any]]:
    """List sources via native GQL graph → REST fallback."""
    if await gql_available(token):
        uri = _build_etp_uri(ds, typ, uuid)
        try:
            result = await gql_query(token, Q_SOURCES, {"uri": uri})
            resource = (result.get("data") or {}).get("resource")
            if resource:
                sources = resource.get("sources") or []
                return [
                    {"uri": s["uri"], "name": s.get("name", ""), "dataObjectType": s.get("dataObjectType", "")}
                    for s in sources
                ]
        except Exception as e:
            log.debug("gql sources failed, falling back to REST: %s", e)
    return await _rest_list_sources(token, ds, typ, uuid)


async def _gql_or_rest_graph_search(token: str, uris: List[str], depth: int = 1) -> Dict[str, Any]:
    """Batch graph search: single GQL call for multiple URIs → individual REST calls fallback."""
    if await gql_available(token):
        try:
            result = await gql_query(token, Q_GRAPH_SEARCH, {"uris": uris, "depth": depth})
            return (result.get("data") or {}).get("graphSearch") or {"resources": [], "edges": []}
        except Exception as e:
            log.debug("gql graphSearch failed, falling back to REST: %s", e)
    # REST fallback: no batch endpoint, return empty (caller handles individually)
    return {"resources": [], "edges": []}


def _build_etp_uri(ds: str, typ: str, uuid: str) -> str:
    """Construct an ETP URI from dataspace/type/uuid components."""
    # Escape single quotes in dataspace per ETP spec
    ds_escaped = ds.replace("'", "''")
    return f"eml:///dataspace('{ds_escaped}')/{typ}({uuid})"


async def _gql_or_rest_list_arrays(token: str, ds: str, typ: str, uuid: str) -> List[Dict[str, Any]]:
    """List array metadata: native GQL → REST fallback."""
    if await gql_available(token):
        uri = _build_etp_uri(ds, typ, uuid)
        try:
            result = await gql_query(token, Q_ARRAYS, {"uri": uri})
            resource = (result.get("data") or {}).get("resource")
            if resource:
                arrays = resource.get("arrays") or []
                return [
                    {
                        "uid": {"pathInResource": a.get("pathInResource", "")},
                        "dimensions": a.get("dimensions") or [],
                        "totalCount": 0,
                    }
                    for a in arrays
                ]
        except Exception as e:
            log.debug("gql arrays failed, falling back to REST: %s", e)
    return await _rest_list_arrays(token, ds, typ, uuid)


# ──────────────────────────────────────────────────────────────────────────────
# Strawberry GraphQL Types
# ──────────────────────────────────────────────────────────────────────────────


@strawberry.enum
class ComparisonOperator(Enum):
    GT = "GT"
    GTE = "GTE"
    LT = "LT"
    LTE = "LTE"
    EQ = "EQ"
    BETWEEN = "BETWEEN"


@strawberry.type
class ArrayStatistics:
    """Statistics computed from array data."""
    count: int
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    mean: Optional[float] = None
    std_dev: Optional[float] = None
    nan_count: int = 0


@strawberry.type
class CellMatch:
    """Result of a cell-value threshold filter on array data."""
    count: int
    total: int
    fraction: float


@strawberry.type
class ArrayInfo:
    """A numerical array attached to a RESQML object."""
    path: str
    data_type: str = "unknown"
    dimensions: Optional[List[int]] = None
    total_elements: int = 0
    statistics: Optional[ArrayStatistics] = None
    sample_values: Optional[List[float]] = None


@strawberry.type
class PropertyInfo:
    """A RESQML property (Continuous/Discrete) attached to a representation."""
    uuid: str
    title: str
    type_name: str
    kind: str
    uom: Optional[str] = None
    arrays: Optional[List[ArrayInfo]] = None
    statistics: Optional[ArrayStatistics] = None
    matching_cells: Optional[CellMatch] = None


@strawberry.type
class RelationInfo:
    """A relationship edge in the RESQML object graph."""
    uuid: str
    name: str
    type_name: str
    direction: str  # "target" or "source"
    content_type: str = ""


# ── Default noise types filtered from relation results ────────────────────────
# Activities reference every object in a scenario and are rarely useful.
_RELATION_NOISE_TYPES = {"obj_Activity"}


def _filter_relations(
    rels: List[RelationInfo],
    relation_filter: Optional[List[str]] = None,
) -> List[RelationInfo]:
    """Filter relation results.

    When *relation_filter* is provided, only relations whose type_name contains
    one of the given substrings are kept.  Otherwise, default noise types
    (Activity) are removed.  To include Activity explicitly, pass
    ``relationFilter: ["Activity"]``.
    """
    if relation_filter:
        return [
            r for r in rels
            if any(f.lower() in r.type_name.lower() for f in relation_filter)
        ]
    # Default: strip noise
    return [r for r in rels if not any(n in r.type_name for n in _RELATION_NOISE_TYPES)]


@strawberry.type
class ResqmlObject:
    """A RESQML object from the Reservoir DDMS store."""
    uuid: str
    title: str
    type_name: str
    relations: Optional[List[RelationInfo]] = None
    properties: Optional[List[PropertyInfo]] = None


@strawberry.type
class DataspaceInfo:
    """A Reservoir DDMS dataspace."""
    path: str
    uri: str = ""


@strawberry.type
class TypeSummary:
    """Count of a resource type within a dataspace."""
    name: str
    count: int


@strawberry.type
class DeepSearchResult:
    """Result of a deep search with optional array-level filtering."""
    objects: List[ResqmlObject]
    total_scanned: int
    total_matched: int
    query_description: str
    backend: str  # "REST" or "PostgreSQL"
    warnings: Optional[List[str]] = None  # surfaced errors / hints


@strawberry.type
class FederatedHit:
    """A single unified result from federated search (OSDU catalog + local RDDMS + remote RDDMS)."""
    uuid: str
    title: str
    type_name: str = ""
    dataspace: str = ""
    # Source flags
    found_in_catalog: bool = False
    found_in_rddms: bool = False          # True if found in either local or remote RDDMS
    found_in_local_rddms: bool = False     # Local PostgreSQL
    found_in_remote_rddms: bool = False    # Remote OSDU RDDMS (REST)
    # OSDU catalog metadata (if found there)
    osdu_id: Optional[str] = None
    osdu_kind: Optional[str] = None
    data_json: Optional[str] = None
    # RESQML deep data (if found in RDDMS)
    relations: Optional[List[RelationInfo]] = None
    properties: Optional[List[PropertyInfo]] = None


@strawberry.type
class FederatedSearchResult:
    """
    Combined search across OSDU catalog + local RDDMS (PG) + remote RDDMS (REST).
    Searches all sources in parallel, merges by UUID, deduplicates.
    """
    hits: List[FederatedHit]
    total_catalog: int
    total_rddms: int           # Combined local + remote
    total_local_rddms: int = 0
    total_remote_rddms: int = 0
    total_merged: int
    query_description: str
    sources: List[str]  # e.g. ["OSDU catalog", "PostgreSQL", "Remote RDDMS"]
    warnings: Optional[List[str]] = None  # surfaced errors / hints


# ──────────────────────────────────────────────────────────────────────────────
# Input types
# ──────────────────────────────────────────────────────────────────────────────


@strawberry.input
class ArrayFilter:
    """Filter on array values (deep search into numerical data).

    For BETWEEN, supply both *threshold* (low) and *threshold_high* (high).
    Matches values where  threshold <= v <= threshold_high.
    """
    threshold: float
    operator: ComparisonOperator = ComparisonOperator.GT
    threshold_high: Optional[float] = None


@strawberry.input
class PropertyFilter:
    """Filter for properties attached to representations."""
    kind: Optional[str] = None
    title_contains: Optional[str] = None
    array_filter: Optional[ArrayFilter] = None


# ──────────────────────────────────────────────────────────────────────────────
# Computation helpers
# ──────────────────────────────────────────────────────────────────────────────


def _compute_statistics(values: List[float]) -> ArrayStatistics:
    finite = [v for v in values if math.isfinite(v)]
    nan_count = len(values) - len(finite)
    if not finite:
        return ArrayStatistics(count=len(values), nan_count=nan_count)
    min_v = min(finite)
    max_v = max(finite)
    mean = sum(finite) / len(finite)
    variance = sum((v - mean) ** 2 for v in finite) / len(finite) if len(finite) > 1 else 0
    return ArrayStatistics(
        count=len(values), min_value=min_v, max_value=max_v,
        mean=mean, std_dev=variance ** 0.5, nan_count=nan_count,
    )


def _check_threshold(
    values: List[float],
    threshold: float,
    op: ComparisonOperator,
    threshold_high: Optional[float] = None,
) -> CellMatch:
    total = len(values)
    if total == 0:
        return CellMatch(count=0, total=0, fraction=0.0)
    ops = {
        ComparisonOperator.GT: lambda v: v > threshold,
        ComparisonOperator.GTE: lambda v: v >= threshold,
        ComparisonOperator.LT: lambda v: v < threshold,
        ComparisonOperator.LTE: lambda v: v <= threshold,
        ComparisonOperator.EQ: lambda v: abs(v - threshold) < 1e-9,
        ComparisonOperator.BETWEEN: lambda v: threshold <= v <= (threshold_high if threshold_high is not None else threshold),
    }
    check = ops[op]
    count = sum(1 for v in values if math.isfinite(v) and check(v))
    return CellMatch(count=count, total=total, fraction=count / total if total else 0.0)


def _enrich_arrays_from_values(
    values: List[float],
    ai: ArrayInfo,
    prop_info: PropertyInfo,
    property_filter: Optional[PropertyFilter],
    include_statistics: bool,
    include_sample_values: bool,
    sample_size: int,
) -> bool:
    """Apply stats/threshold/sampling to array values. Returns True if threshold passes."""
    passes = False
    if not values:
        return passes
    ai.total_elements = len(values)
    if include_statistics:
        ai.statistics = _compute_statistics(values)
        prop_info.statistics = ai.statistics
    if include_sample_values:
        ai.sample_values = values[:sample_size]
    if property_filter and property_filter.array_filter:
        af = property_filter.array_filter
        match = _check_threshold(values, af.threshold, af.operator, af.threshold_high)
        prop_info.matching_cells = match
        if match.count > 0:
            passes = True
    return passes


async def _enrich_property_via_rest(
    token: str,
    dataspace: str,
    p_type: str,
    p_uuid: str,
    prop_info: PropertyInfo,
    property_filter: Optional[PropertyFilter],
    include_statistics: bool,
    include_sample_values: bool,
    sample_size: int,
) -> Tuple[Optional[List[ArrayInfo]], bool]:
    """Load arrays via REST and enrich a PropertyInfo. Returns (array_infos, passes_filter)."""
    try:
        p_arrays = await _rest_list_arrays(token, dataspace, p_type, p_uuid)
    except Exception:
        p_arrays = []

    array_infos: List[ArrayInfo] = []
    passes = False
    for pa in p_arrays:
        pa_uid = pa.get("uid") or {}
        pa_path = pa_uid.get("pathInResource", "") if isinstance(pa_uid, dict) else ""
        if not pa_path:
            continue
        ai = ArrayInfo(path=pa_path)
        try:
            values = await _rest_read_array(token, dataspace, p_type, p_uuid, pa_path)
        except Exception:
            values = []
        if _enrich_arrays_from_values(
            values, ai, prop_info, property_filter,
            include_statistics, include_sample_values, sample_size,
        ):
            passes = True
        array_infos.append(ai)
    return (array_infos if array_infos else None, passes)


def _extract_property_kind(obj: Dict[str, Any]) -> str:
    """Extract property kind from a RESQML property object JSON.

    RDDMS REST returns two flavours:
      StandardPropertyKind:  {"PropertyKind": {"$type": "resqml20.StandardPropertyKind", "Kind": "porosity"}}
      LocalPropertyKind:     {"PropertyKind": {"$type": "resqml20.LocalPropertyKind",
                               "LocalPropertyKind": {"$type": "eml20.DataObjectReference", "Title": "General discrete", ...}}}
    """
    pk = obj.get("PropertyKind") or {}
    # StandardPropertyKind → {"Kind": "porosity"}
    kind = pk.get("Kind") or ""
    if kind:
        return kind
    # LocalPropertyKind → DataObjectReference with Title
    lpk = pk.get("LocalPropertyKind")
    if isinstance(lpk, dict):
        kind = lpk.get("Title") or ""
        if kind:
            return kind
    elif isinstance(lpk, str):
        return lpk
    # Fallback: StandardPropertyKind string
    kind = obj.get("StandardPropertyKind") or ""
    if kind:
        return kind
    # Last resort: Citation title of the PropertyKind reference
    kind = pk.get("Title") or ""
    return kind or "Unknown"


def _extract_refs(obj: Dict[str, Any]) -> List[Dict[str, str]]:
    """Extract DataObjectReferences from a RESQML JSON object (all levels)."""
    refs: List[Dict[str, str]] = []
    def _walk(x: Any) -> None:
        if isinstance(x, dict):
            ct = x.get("ContentType") or ""
            uid = x.get("UUID") or x.get("Uuid") or ""
            title = x.get("Title") or ""
            if ct and uid:
                refs.append({"content_type": ct, "uuid": str(uid), "title": title})
            for v in x.values():
                _walk(v)
        elif isinstance(x, list):
            for v in x:
                _walk(v)
    _walk(obj)
    return refs


# ──────────────────────────────────────────────────────────────────────────────
# Deep search - PG native implementation
# ──────────────────────────────────────────────────────────────────────────────


async def _deep_search_pg(
    pool,
    dataspace: str,
    type_name: str,
    title_contains: Optional[str],
    property_filter: Optional[PropertyFilter],
    include_relations: bool,
    include_statistics: bool,
    include_sample_values: bool,
    sample_size: int,
    limit: int,
    relation_filter: Optional[List[str]] = None,
) -> DeepSearchResult:
    """Deep search using direct PostgreSQL access - batch-optimised.

    Strategy: Fetch objects in bulk, then use batch queries for properties
    and relations instead of N+1 individual queries.
    """
    pg_schema = await _pg_schema_for_dataspace(pool, dataspace)
    if not pg_schema:
        return DeepSearchResult(
            objects=[], total_scanned=0, total_matched=0,
            query_description=f"Dataspace '{dataspace}' not found in PG",
            backend="PostgreSQL",
        )

    # Resolve type_name (may be a category or wildcard)
    type_names = resolve_type_names(type_name)
    if not type_names:
        type_names = [type_name]

    async with pool.acquire() as conn:
        # Step 1: List objects of type_name(s) in batch
        all_resources = []
        for tn in type_names:
            parts = tn.split(".", 1)
            if len(parts) == 2:
                resources = await conn.fetch(f"""
                    SELECT r.obj_id, r.guid, r.name, t.xml as typ_xml, u.ml
                    FROM {pg_schema}.res r
                    JOIN {pg_schema}.typ t ON r.typ_id = t.id
                    JOIN {pg_schema}.uri u ON t.uri_id = u.id
                    WHERE u.ml = $1 AND t.xml = $2
                    ORDER BY r.obj_id
                """, parts[0], parts[1])
            else:
                resources = await conn.fetch(f"""
                    SELECT r.obj_id, r.guid, r.name, t.xml as typ_xml, u.ml
                    FROM {pg_schema}.res r
                    JOIN {pg_schema}.typ t ON r.typ_id = t.id
                    JOIN {pg_schema}.uri u ON t.uri_id = u.id
                    WHERE t.xml ILIKE '%' || $1 || '%'
                    ORDER BY r.obj_id
                """, tn)
            for r in resources:
                all_resources.append((r, f"{r['ml']}.{r['typ_xml']}"))

        total_scanned = len(all_resources)

        # Apply title filter early
        if title_contains:
            all_resources = [
                (r, tn) for r, tn in all_resources
                if title_contains.lower() in r["name"].lower()
            ]

        # Cap candidates for batch processing
        candidates = all_resources[:limit * 3]
        candidate_obj_ids = [r["obj_id"] for r, _ in candidates]

        # Step 2: Batch-fetch property sources for all candidates
        prop_sources_map = await _pg_batch_property_sources(pool, dataspace, candidate_obj_ids)

        # Step 3: If property filter requires kind, batch-fetch XML for property objects
        # to determine kind (only for properties that need it)
        kind_cache: Dict[int, str] = {}
        if property_filter and (property_filter.kind or property_filter.title_contains):
            all_prop_obj_ids = [
                ps["p_obj_id"]
                for sources in prop_sources_map.values()
                for ps in sources
            ]
            if all_prop_obj_ids:
                xml_rows = await conn.fetch(f"""
                    SELECT id, xml FROM {pg_schema}.obj
                    WHERE id = ANY($1::int[])
                """, all_prop_obj_ids)
                import xml.etree.ElementTree as ET
                for xr in xml_rows:
                    kind = "Unknown"
                    xml_str = str(xr["xml"]) if xr["xml"] else ""
                    if "PropertyKind" in xml_str or "LocalPropertyKind" in xml_str:
                        try:
                            root = ET.fromstring(xml_str)
                            for elem in root.iter():
                                tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
                                if "PropertyKind" in tag:
                                    title_elem = elem.find(
                                        ".//{http://www.energistics.org/energyml/data/commonv2}Title"
                                    )
                                    if title_elem is not None and title_elem.text:
                                        kind = title_elem.text
                                        break
                        except ET.ParseError:
                            pass
                    kind_cache[xr["id"]] = kind

        # Step 4: Batch-fetch arrays for property objects (if needed)
        need_arrays = include_statistics or include_sample_values or (
            property_filter and property_filter.array_filter
        )
        arrays_map: Dict[int, List[Dict[str, Any]]] = {}
        if need_arrays:
            all_prop_ids = [
                ps["p_obj_id"]
                for sources in prop_sources_map.values()
                for ps in sources
            ]
            # Also include WITSML objects that have their own arrays (channels)
            witsml_obj_ids = [
                r["obj_id"] for r, tn in candidates
                if "witsml" in tn.lower() and not prop_sources_map.get(r["obj_id"])
            ]
            all_ids_for_arrays = list(set(all_prop_ids + witsml_obj_ids))
            if all_ids_for_arrays:
                arrays_map = await _pg_batch_arrays_for_objects(pool, dataspace, all_ids_for_arrays)

        # Step 5: Batch-fetch relations (if needed)
        relations_map: Dict[int, List[Dict[str, Any]]] = {}
        if include_relations:
            relations_map = await _pg_batch_relations(pool, dataspace, candidate_obj_ids)

        # Step 6: Assemble results
        matched: List[ResqmlObject] = []
        for res, res_type_name in candidates:
            if len(matched) >= limit:
                break

            obj_id = res["obj_id"]
            uuid = str(res["guid"])
            title = res["name"]

            # Process properties for this object
            prop_sources = prop_sources_map.get(obj_id, [])

            if property_filter and property_filter.kind and not prop_sources:
                # For WITSML objects, channels act as properties
                if "witsml" not in res_type_name.lower():
                    continue

            property_results: List[PropertyInfo] = []
            passes_filter = not (property_filter and property_filter.array_filter)

            # WITSML channel-as-property: treat the object's own arrays as channels
            if not prop_sources and "witsml" in res_type_name.lower():
                obj_arrays = arrays_map.get(obj_id, [])
                for pa in obj_arrays:
                    mnemonic = pa["path"].rsplit("/", 1)[-1] if "/" in pa["path"] else pa["path"]
                    # Title filter on channel mnemonic
                    if property_filter and property_filter.title_contains:
                        if property_filter.title_contains.lower() not in mnemonic.lower():
                            continue
                    # Kind filter on mnemonic
                    if property_filter and property_filter.kind:
                        if property_filter.kind.lower() not in mnemonic.lower():
                            continue
                    pi = PropertyInfo(
                        uuid=uuid, title=mnemonic, type_name="Channel", kind=mnemonic,
                    )
                    if need_arrays:
                        try:
                            values = await _pg_read_array_by_id(
                                pool, dataspace, pa["ary_id"], pa["type"]
                            )
                        except Exception:
                            values = []
                        ai = ArrayInfo(path=pa["path"])
                        if _enrich_arrays_from_values(
                            values, ai, pi, property_filter,
                            include_statistics, include_sample_values, sample_size,
                        ):
                            passes_filter = True
                        pi.arrays = [ai]
                    property_results.append(pi)
            else:
                for ps in prop_sources:
                    p_name = ps["p_name"]
                    p_uuid = ps["p_guid"]
                    p_type = f"{ps['p_ml']}.{ps['p_typ_xml']}"
                    p_obj_id = ps["p_obj_id"]

                    # Title filter on property
                    if property_filter and property_filter.title_contains:
                        if property_filter.title_contains.lower() not in p_name.lower():
                            continue

                    # Kind from batch cache
                    kind = kind_cache.get(p_obj_id, "Unknown")

                    # Kind filter
                    if property_filter and property_filter.kind:
                        if property_filter.kind.lower() not in kind.lower() and \
                           property_filter.kind.lower() not in p_name.lower():
                            continue

                    prop_info = PropertyInfo(
                        uuid=p_uuid, title=p_name, type_name=p_type, kind=kind,
                    )

                    # Arrays (from batch cache)
                    if need_arrays:
                        p_arrays = arrays_map.get(p_obj_id, [])
                        array_infos: List[ArrayInfo] = []
                        for pa in p_arrays:
                            ai = ArrayInfo(path=pa["path"])
                            try:
                                values = await _pg_read_array_by_id(
                                    pool, dataspace, pa["ary_id"], pa["type"]
                                )
                            except Exception:
                                values = []
                            if _enrich_arrays_from_values(
                                values, ai, prop_info, property_filter,
                                include_statistics, include_sample_values, sample_size,
                            ):
                                passes_filter = True
                            array_infos.append(ai)
                        prop_info.arrays = array_infos if array_infos else None

                    property_results.append(prop_info)

            if property_filter and property_filter.kind and not property_results:
                continue
            if property_filter and property_filter.array_filter and not passes_filter:
                continue

            # Relations (from batch cache)
            relation_results: Optional[List[RelationInfo]] = None
            if include_relations:
                raw_rels = [
                    RelationInfo(
                        uuid=r["uuid"], name=r["name"],
                        type_name=r["type_name"],
                        direction=r["direction"],
                        content_type=r["content_type"],
                    )
                    for r in relations_map.get(obj_id, [])
                ]
                relation_results = _filter_relations(raw_rels, relation_filter)

            matched.append(ResqmlObject(
                uuid=uuid, title=title, type_name=res_type_name,
                relations=relation_results,
                properties=property_results if property_results else None,
            ))

    # Build description
    desc_parts = [f"type={type_name}"]
    if title_contains:
        desc_parts.append(f"title~'{title_contains}'")
    if property_filter:
        if property_filter.kind:
            desc_parts.append(f"property.kind='{property_filter.kind}'")
        if property_filter.array_filter:
            af = property_filter.array_filter
            desc_parts.append(f"cellValue {af.operator.value} {af.threshold}")

    return DeepSearchResult(
        objects=matched,
        total_scanned=total_scanned,
        total_matched=len(matched),
        query_description=" AND ".join(desc_parts),
        backend="PostgreSQL",
    )


# ──────────────────────────────────────────────────────────────────────────────
# Deep search - REST implementation
# ──────────────────────────────────────────────────────────────────────────────


def _merge_deep_results(results: list, ds_list: List[str], limit: int) -> DeepSearchResult:
    """Merge DeepSearchResult from multiple dataspaces."""
    all_objects: List[ResqmlObject] = []
    total_scanned = 0
    total_matched = 0
    backends = set()
    all_warnings: List[str] = []
    for r in results:
        total_scanned += r.total_scanned
        total_matched += r.total_matched
        all_objects.extend(r.objects)
        backends.add(r.backend)
        if r.warnings:
            all_warnings.extend(r.warnings)
    all_objects = all_objects[:limit]
    backend = " + ".join(sorted(backends))
    desc = f"Searched {len(ds_list)} dataspaces: {', '.join(ds_list)}"
    return DeepSearchResult(
        objects=all_objects,
        total_scanned=total_scanned,
        total_matched=total_matched,
        query_description=desc,
        backend=backend,
        warnings=all_warnings or None,
    )


async def _deep_search_rest(
        token: str,
        dataspace: str,
        type_name: str,
        title_contains: Optional[str],
        property_filter: Optional[PropertyFilter],
        include_relations: bool,
        include_statistics: bool,
        include_sample_values: bool,
        sample_size: int,
        limit: int,
        relation_filter: Optional[List[str]] = None,
) -> DeepSearchResult:
    """REST-based deep search for a single dataspace (concurrent enrichment)."""
    backend = "REST"
    warnings: List[str] = []

    # Property kind cache: uuid → kind string (avoids re-fetching same property)
    _kind_cache: Dict[str, str] = {}

    # Resolve type names (supports categories/wildcards)
    type_names = resolve_type_names(type_name)
    if not type_names:
        type_names = [type_name]

    # Step 1: List target objects (across resolved types)
    all_resources: List[Dict[str, Any]] = []
    for tn in type_names:
        try:
            resources = await _rest_list_resources(token, dataspace, tn, limit * 3)
            for r in resources:
                r["_resolved_type"] = tn
            all_resources.extend(resources)
        except Exception as e:
            warnings.append(f"Failed to list {tn}: {e}")

    if not all_resources:
        return DeepSearchResult(
            objects=[], total_scanned=0, total_matched=0,
            query_description=f"ERROR listing {type_name}: no results",
            backend=backend, warnings=warnings or None,
        )

    total_scanned = len(all_resources)

    # Pre-filter by title
    if title_contains:
        all_resources = [
            r for r in all_resources
            if title_contains.lower() in r["title"].lower()
        ]

    # Limit candidates
    candidates = [r for r in all_resources if r["uuid"]][:limit * 2]

    # Step 2: Concurrent source fetching (batch of up to 10 at a time)
    _CONCURRENCY = 10

    async def _fetch_sources(r: Dict[str, Any]) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        tn = r["_resolved_type"]
        try:
            sources = await _gql_or_rest_list_sources(token, dataspace, tn, r["uuid"])
            return (r, sources)
        except Exception as e:
            warnings.append(f"{r['title']}: sources failed: {e}")
            return (r, [])

    # Process in batches for controlled concurrency
    source_results: List[Tuple[Dict[str, Any], List[Dict[str, Any]]]] = []
    for i in range(0, len(candidates), _CONCURRENCY):
        batch = candidates[i:i + _CONCURRENCY]
        batch_results = await asyncio.gather(*[_fetch_sources(r) for r in batch])
        source_results.extend(batch_results)
        if sum(1 for _ in source_results if _[1]) >= limit:
            break  # have enough candidates with properties

    matched: List[ResqmlObject] = []

    for r, sources in source_results:
        if len(matched) >= limit:
            break

        uuid = r["uuid"]
        title = r["title"]
        tn = r["_resolved_type"]

        # Parse each source to extract uuid/type from URI
        parsed_sources = [_parse_eml_entry(s) for s in sources]

        # Filter to property types
        prop_sources = [
            ps for ps in parsed_sources
            if any(k in ps["contentType"]
                   for k in ("ContinuousProperty", "DiscreteProperty",
                             "CategoricalProperty", "PointsProperty"))
        ]

        if property_filter and property_filter.kind and not prop_sources:
            continue

        # Step 3: fetch property details and filter by kind
        property_results: List[PropertyInfo] = []
        passes_filter = not (property_filter and property_filter.array_filter)

        for ps in prop_sources:
            p_ct = ps["contentType"]
            p_uuid = ps["uuid"]
            p_name = ps["name"]
            if not p_uuid:
                continue

            # Determine property type for API call
            if "ContinuousProperty" in p_ct:
                p_type = "resqml20.obj_ContinuousProperty"
            elif "DiscreteProperty" in p_ct:
                p_type = "resqml20.obj_DiscreteProperty"
            elif "CategoricalProperty" in p_ct:
                p_type = "resqml20.obj_CategoricalProperty"
            elif "PointsProperty" in p_ct:
                p_type = "resqml20.obj_PointsProperty"
            else:
                continue

            # Fetch property object to get kind (with cache)
            if p_uuid in _kind_cache:
                kind = _kind_cache[p_uuid]
                p_obj: Dict[str, Any] = {}
                uom = None
            else:
                try:
                    p_obj = await _rest_get_resource(token, dataspace, p_type, p_uuid)
                except Exception as e:
                    warnings.append(f"Failed to fetch property {p_uuid[:8]}…: {e}")
                    continue

                kind = _extract_property_kind(p_obj)
                _kind_cache[p_uuid] = kind
                uom = p_obj.get("UOM") or p_obj.get("Uom") or None

            # Kind filter
            if property_filter and property_filter.kind:
                if property_filter.kind.lower() not in kind.lower():
                    continue

            # Title filter on property
            if property_filter and property_filter.title_contains:
                p_title = (p_obj.get("Citation") or {}).get("Title", "") or p_name
                if property_filter.title_contains.lower() not in p_title.lower():
                    continue

            prop_info = PropertyInfo(
                uuid=p_uuid,
                title=(p_obj.get("Citation") or {}).get("Title", "") or p_name,
                type_name=p_type,
                kind=kind,
                uom=uom,
            )

            # Step 4: optionally load array data for statistics/filtering
            if include_statistics or include_sample_values or (property_filter and property_filter.array_filter):
                arr_result, arr_passes = await _enrich_property_via_rest(
                    token, dataspace, p_type, p_uuid, prop_info,
                    property_filter, include_statistics, include_sample_values, sample_size,
                )
                prop_info.arrays = arr_result
                if arr_passes:
                    passes_filter = True

                if not arr_result and (include_statistics or (property_filter and property_filter.array_filter)):
                    _no_array_msg = "REST backend: array values not available (statistics/threshold need PG or ETP)"
                    if _no_array_msg not in warnings:
                        warnings.append(_no_array_msg)

            property_results.append(prop_info)

        # If we had a property kind filter and no properties matched, skip
        if property_filter and property_filter.kind and not property_results:
            continue
        # If array filter active but nothing passed, skip
        if property_filter and property_filter.array_filter and not passes_filter:
            continue

        # Relations (via REST targets/sources)
        relation_results: Optional[List[RelationInfo]] = None
        if include_relations:
            relation_results = []
            try:
                targets = await _gql_or_rest_list_targets(token, dataspace, type_name, uuid)
                for t in targets:
                    parsed = _parse_eml_entry(t)
                    if parsed["uuid"]:
                        relation_results.append(RelationInfo(
                            uuid=parsed["uuid"], name=parsed["name"],
                            type_name=parsed["contentType"],
                            direction="target", content_type=parsed["contentType"],
                        ))
            except Exception as e:
                warnings.append(f"{title}: targets failed: {e}")
            try:
                src_all = await _gql_or_rest_list_sources(token, dataspace, type_name, uuid)
                for s in src_all:
                    parsed = _parse_eml_entry(s)
                    if parsed["uuid"]:
                        relation_results.append(RelationInfo(
                            uuid=parsed["uuid"], name=parsed["name"],
                            type_name=parsed["contentType"],
                            direction="source", content_type=parsed["contentType"],
                        ))
            except Exception as e:
                warnings.append(f"{title}: sources failed: {e}")

        # Apply relation filter
        if relation_results is not None:
            relation_results = _filter_relations(relation_results, relation_filter)

        matched.append(ResqmlObject(
            uuid=uuid, title=title, type_name=type_name,
            relations=relation_results,
            properties=property_results if property_results else None,
        ))

    # Build description
    desc_parts = [f"type={type_name}"]
    if title_contains:
        desc_parts.append(f"title~'{title_contains}'")
    if property_filter:
        if property_filter.kind:
            desc_parts.append(f"property.kind='{property_filter.kind}'")
        if property_filter.array_filter:
            af = property_filter.array_filter
            if af.operator == ComparisonOperator.BETWEEN and af.threshold_high is not None:
                desc_parts.append(f"cellValue BETWEEN {af.threshold} AND {af.threshold_high}")
            else:
                desc_parts.append(f"cellValue {af.operator.value} {af.threshold}")

    # Add summary warning when objects were scanned & kind-matched but array filter rejected all
    if property_filter and property_filter.array_filter and total_scanned > 0 and len(matched) == 0:
        warnings.append(
            f"All {total_scanned} objects skipped by arrayFilter "
            f"(threshold {property_filter.array_filter.operator.value} {property_filter.array_filter.threshold}) - "
            f"remove arrayFilter to see kind-matched results on REST backend"
        )

    return DeepSearchResult(
        objects=matched,
        total_scanned=total_scanned,
        total_matched=len(matched),
        query_description=" AND ".join(desc_parts),
        backend=backend,
        warnings=warnings or None,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Deep search - discovery backend (MR 271 batch graph, gated by RDDMS_DISCOVERY)
# ──────────────────────────────────────────────────────────────────────────────


async def _deep_search_discovery(
        token: str,
        dataspace: str,
        type_name: str,
        title_contains: Optional[str],
        property_filter: Optional[PropertyFilter],
        include_relations: bool,
        include_statistics: bool,
        include_sample_values: bool,
        sample_size: int,
        limit: int,
        relation_filter: Optional[List[str]] = None,
) -> DeepSearchResult:
    """Discovery-based deep search using POST /query/graph/search (MR 271).

    Instead of N+1 REST calls per object, this backend:
      1) Lists resources of the target type in the dataspace
      2) Sends all candidate URIs to POST /query/graph/search in one call
      3) Builds ResqmlObject results from the merged graph

    Falls back to _deep_search_rest on any error (endpoint not available yet).
    """
    backend = "Discovery"
    warnings: List[str] = []

    # Resolve type names (supports categories/wildcards)
    type_names = resolve_type_names(type_name)
    if not type_names:
        type_names = [type_name]

    enc = urllib.parse.quote(dataspace, safe="")

    # Step 1: List candidate objects (same as REST path)
    all_resources: List[Dict[str, Any]] = []
    for tn in type_names:
        try:
            resources = await _rest_list_resources(token, dataspace, tn, limit * 3)
            for r in resources:
                r["_resolved_type"] = tn
            all_resources.extend(resources)
        except Exception as e:
            warnings.append(f"Failed to list {tn}: {e}")

    if not all_resources:
        return DeepSearchResult(
            objects=[], total_scanned=0, total_matched=0,
            query_description=f"type={type_name}: no resources found",
            backend=backend, warnings=warnings or None,
        )

    total_scanned = len(all_resources)

    # Pre-filter by title
    if title_contains:
        all_resources = [
            r for r in all_resources
            if title_contains.lower() in r["title"].lower()
        ]

    candidates = [r for r in all_resources if r["uuid"]][:limit * 2]

    if not candidates:
        return DeepSearchResult(
            objects=[], total_scanned=total_scanned, total_matched=0,
            query_description=f"type={type_name}: no candidates after filter",
            backend=backend, warnings=warnings or None,
        )

    # Step 2: Batch graph search — one call for ALL candidates
    candidate_uris = [r.get("uri", "") for r in candidates if r.get("uri")]

    # Property types we're interested in as sources of representations
    prop_types = [
        "resqml20.obj_ContinuousProperty",
        "resqml20.obj_DiscreteProperty",
        "resqml20.obj_CategoricalProperty",
        "resqml20.obj_PointsProperty",
        "resqml22.ContinuousProperty",
        "resqml22.DiscreteProperty",
        "resqml22.CategoricalProperty",
    ]

    graph: Dict[str, Any] = {"resources": [], "links": []}
    try:
        graph = await osdu.graph_search(
            token,
            candidate_uris,
            scope="sources",
            depth=1 if not include_relations else 2,
            data_object_types=prop_types if (property_filter or include_statistics) else [],
            count_objects=include_relations,
        )
    except Exception as e:
        warnings.append(f"graph_search failed ({e}); falling back to REST")
        # Return a sentinel so the caller knows to fall back
        return DeepSearchResult(
            objects=[], total_scanned=total_scanned, total_matched=0,
            query_description=f"Discovery graph_search unavailable: {e}",
            backend="Discovery-FALLBACK",
            warnings=warnings,
        )

    # Build lookup structures from graph
    graph_resources_by_uri: Dict[str, Dict[str, Any]] = {}
    for gr in graph.get("resources", []):
        uri = gr.get("uri", "")
        if uri:
            graph_resources_by_uri[uri] = gr

    # Build edge index: target_uri → [source resources]
    # In RESQML, properties are *sources* of their representation (target)
    sources_of: Dict[str, List[Dict[str, Any]]] = {}
    targets_of: Dict[str, List[Dict[str, Any]]] = {}
    for link in graph.get("links", []):
        src_uri = link.get("source", "")
        tgt_uri = link.get("target", "")
        if src_uri and tgt_uri:
            sources_of.setdefault(tgt_uri, []).append(
                graph_resources_by_uri.get(src_uri, {"uri": src_uri})
            )
            targets_of.setdefault(src_uri, []).append(
                graph_resources_by_uri.get(tgt_uri, {"uri": tgt_uri})
            )

    # Step 3: Build results from graph
    matched: List[ResqmlObject] = []

    for r in candidates:
        if len(matched) >= limit:
            break

        uuid = r["uuid"]
        title = r["title"]
        tn = r["_resolved_type"]
        r_uri = r.get("uri", "")

        # Extract property sources from graph edges
        source_entries = sources_of.get(r_uri, [])

        # Filter to property types
        prop_entries = []
        for se in source_entries:
            parsed = _parse_eml_entry(se)
            if any(k in parsed["contentType"]
                   for k in ("ContinuousProperty", "DiscreteProperty",
                             "CategoricalProperty", "PointsProperty")):
                prop_entries.append(parsed)

        if property_filter and property_filter.kind and not prop_entries:
            continue

        # Build PropertyInfo from graph data (no extra REST calls needed for basic info)
        property_results: List[PropertyInfo] = []
        passes_filter = not (property_filter and property_filter.array_filter)

        for pe in prop_entries:
            p_uuid = pe["uuid"]
            p_name = pe["name"]
            if not p_uuid:
                continue

            p_type = pe["contentType"]

            # We don't have property kind from graph metadata alone —
            # would need a follow-up GetDataObjects call. For now, use type name as proxy.
            kind = "unknown"
            if "Continuous" in p_type:
                kind = "continuous"
            elif "Discrete" in p_type:
                kind = "discrete"
            elif "Categorical" in p_type:
                kind = "categorical"
            elif "Points" in p_type:
                kind = "points"

            # Kind filter
            if property_filter and property_filter.kind:
                if property_filter.kind.lower() not in kind.lower():
                    # If we have a kind filter but only type-inferred kind,
                    # try to fetch the actual object for precise kind (lazy)
                    try:
                        p_obj = await _rest_get_resource(token, dataspace, p_type, p_uuid)
                        kind = _extract_property_kind(p_obj)
                        if property_filter.kind.lower() not in kind.lower():
                            continue
                    except Exception:
                        continue

            # Title filter on property
            if property_filter and property_filter.title_contains:
                if property_filter.title_contains.lower() not in p_name.lower():
                    continue

            prop_info = PropertyInfo(
                uuid=p_uuid,
                title=p_name,
                type_name=p_type,
                kind=kind,
                uom=None,
            )

            # Array statistics/filtering still requires individual array calls
            # (graph search doesn't return array data)
            if include_statistics or include_sample_values or (property_filter and property_filter.array_filter):
                arr_result, arr_passes = await _enrich_property_via_rest(
                    token, dataspace, p_type, p_uuid, prop_info,
                    property_filter, include_statistics, include_sample_values, sample_size,
                )
                prop_info.arrays = arr_result
                if arr_passes:
                    passes_filter = True

            property_results.append(prop_info)

        if property_filter and property_filter.kind and not property_results:
            continue
        if property_filter and property_filter.array_filter and not passes_filter:
            continue

        # Relations from graph edges (no extra REST calls!)
        relation_results: Optional[List[RelationInfo]] = None
        if include_relations:
            relation_results = []
            for te in targets_of.get(r_uri, []):
                parsed = _parse_eml_entry(te)
                if parsed["uuid"]:
                    relation_results.append(RelationInfo(
                        uuid=parsed["uuid"], name=parsed["name"],
                        type_name=parsed["contentType"],
                        direction="target", content_type=parsed["contentType"],
                    ))
            for se in source_entries:
                parsed = _parse_eml_entry(se)
                if parsed["uuid"]:
                    relation_results.append(RelationInfo(
                        uuid=parsed["uuid"], name=parsed["name"],
                        type_name=parsed["contentType"],
                        direction="source", content_type=parsed["contentType"],
                    ))
            relation_results = _filter_relations(relation_results, relation_filter)

        matched.append(ResqmlObject(
            uuid=uuid, title=title, type_name=type_name,
            relations=relation_results,
            properties=property_results if property_results else None,
        ))

    # Build description
    desc_parts = [f"type={type_name}"]
    if title_contains:
        desc_parts.append(f"title~'{title_contains}'")
    if property_filter and property_filter.kind:
        desc_parts.append(f"property.kind='{property_filter.kind}'")

    return DeepSearchResult(
        objects=matched,
        total_scanned=total_scanned,
        total_matched=len(matched),
        query_description=" AND ".join(desc_parts),
        backend=backend,
        warnings=warnings or None,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Deep search - resolver implementation (called from Query.deep_search)
# ──────────────────────────────────────────────────────────────────────────────


async def deep_search_impl(
    token: str,
    dataspace: Optional[str],
    dataspaces: Optional[List[str]],
    type_name: str,
    title_contains: Optional[str],
    property_filter: Optional[PropertyFilter],
    include_relations: bool,
    include_statistics: bool,
    include_sample_values: bool,
    sample_size: int,
    limit: int,
    relation_filter: Optional[List[str]] = None,
    category: Optional[str] = None,
) -> DeepSearchResult:
    """Core deep_search implementation, independent of Strawberry context.

    When *category* is provided, it overrides *type_name* and searches all
    types in that category (e.g. "grid", "well", "structural").
    type_name also supports category names and wildcards (e.g. "*Grid*").
    """
    # Resolve effective type_name: category takes priority
    effective_type = type_name
    if category:
        # Use category as the type_name (resolve_type_names handles expansion)
        effective_type = category

    # Resolve dataspace list (backwards-compatible: single 'dataspace' still works)
    ds_list: List[str] = []
    if dataspaces:
        ds_list = list(dataspaces)
    elif dataspace:
        ds_list = [dataspace]
    else:
        # Fall back to listing available dataspaces
        pool = await _get_pool()
        if pool:
            all_ds = await _pg_list_dataspaces(pool)
            ds_list = [d["path"] for d in all_ds][:5]  # cap at 5

    if not ds_list:
        return DeepSearchResult(
            objects=[], total_scanned=0, total_matched=0,
            query_description="No dataspace specified and none found",
            backend="PostgreSQL" if await _get_pool() else "REST",
        )

    # Single dataspace: use existing path
    if len(ds_list) == 1:
        # Route 1: Discovery batch graph (MR 271) — tried first when enabled
        if osdu.RDDMS_DISCOVERY_ENABLED:
            disc_result = await _deep_search_discovery(
                token, ds_list[0], effective_type, title_contains,
                property_filter, include_relations, include_statistics,
                include_sample_values, sample_size, limit, relation_filter,
            )
            # If discovery succeeded (not a fallback sentinel), use it
            if disc_result.backend != "Discovery-FALLBACK":
                return disc_result
            # Otherwise fall through to PG / REST

        # Route 2: PostgreSQL direct (local co-located with ETP server)
        pool = await _get_pool()
        if pool:
            result = await _deep_search_pg(
                pool, ds_list[0], effective_type, title_contains,
                property_filter, include_relations, include_statistics,
                include_sample_values, sample_size, limit, relation_filter,
            )
            # Fall back to REST if this dataspace isn't in PG
            # but only for remote dataspaces — local ones (maap/*) are authoritative in PG
            if result.total_scanned == 0 and "not found in PG" in result.query_description \
                    and not ds_list[0].startswith("maap/"):
                return await _deep_search_rest(
                    token, ds_list[0], effective_type, title_contains,
                    property_filter, include_relations, include_statistics,
                    include_sample_values, sample_size, limit, relation_filter,
                )
            return result

        # Route 3: REST N+1 fallback (always available)
        return await _deep_search_rest(
            token, ds_list[0], effective_type, title_contains,
            property_filter, include_relations, include_statistics,
            include_sample_values, sample_size, limit, relation_filter,
        )

    # Multiple dataspaces: try Discovery → PG → REST per-ds
    pool = await _get_pool()
    use_discovery = osdu.RDDMS_DISCOVERY_ENABLED

    async def _search_one_ds(ds: str) -> DeepSearchResult:
        """Search a single dataspace: Discovery → PG → REST."""
        # Try discovery first
        if use_discovery:
            disc_result = await _deep_search_discovery(
                token, ds, effective_type, title_contains,
                property_filter, include_relations, include_statistics,
                include_sample_values, sample_size, limit, relation_filter,
            )
            if disc_result.backend != "Discovery-FALLBACK":
                return disc_result

        # PG
        if pool:
            pg_result = await _deep_search_pg(
                pool, ds, effective_type, title_contains,
                property_filter, include_relations, include_statistics,
                include_sample_values, sample_size, limit, relation_filter,
            )
            if pg_result.total_scanned > 0 or "not found in PG" not in pg_result.query_description:
                return pg_result
            # Dataspace not in PG → try REST

        # REST fallback
        return await _deep_search_rest(
            token, ds, effective_type, title_contains,
            property_filter, include_relations, include_statistics,
            include_sample_values, sample_size, limit, relation_filter,
        )

    results = await asyncio.gather(*[_search_one_ds(ds) for ds in ds_list])
    return _merge_deep_results(results, ds_list, limit)


# ──────────────────────────────────────────────────────────────────────────────
# Federated search - helpers
# ──────────────────────────────────────────────────────────────────────────────


def _extract_uuid(data: Dict[str, Any], rid: str) -> Optional[str]:
    """Extract a RESQML UUID from OSDU record data or ID."""
    # From data.ResourceURI: eml:///dataspace('x/y')/resqml20.obj_Type('uuid')
    uri = data.get("ResourceURI") or data.get("DataObjectURI") or ""
    m = _re.search(r"\(([0-9a-f-]{36})\)", uri)
    if m:
        return m.group(1)
    # Check data fields
    for key in ("ResourceID", "UUID", "Uuid", "uuid", "NativeIdentifier"):
        val = data.get(key)
        if val and _re.match(r"^[0-9a-f-]{36}$", str(val)):
            return str(val)
    # Try from record ID (often: ...--TypeName:UUID:version)
    parts = rid.split(":")
    for p in parts:
        if _re.match(r"^[0-9a-f-]{36}$", p):
            return p
    return None


def _extract_dataspace(data: Dict[str, Any], rid: str) -> Optional[str]:
    """Extract dataspace from OSDU record ResourceURI."""
    # eml:///dataspace('maap/drogon')/resqml20.obj_Grid2dRepresentation(...)
    uri = data.get("ResourceURI") or data.get("DataObjectURI") or ""
    m = _re.search(r"dataspace\(['\"]?([^'\")\s]+)['\"]?\)", uri)
    if m:
        return m.group(1)
    return None


def _extract_resqml_type(kind: str, data: Dict[str, Any]) -> Optional[str]:
    """Infer RESQML type from ResourceURI or OSDU kind."""
    # From ResourceURI: eml:///dataspace('x')/resqml20.obj_Grid2dRepresentation('uuid')
    uri = data.get("ResourceURI") or data.get("DataObjectURI") or ""
    m = _re.search(r"(resqml\d+\.obj_\w+)", uri)
    if m:
        return m.group(1)
    # From OSDU kind: work-product-component--IjkGridRepresentation:1.0.0
    kind_type = kind.rsplit("--", 1)[-1].split(":")[0] if "--" in kind else ""
    type_map = {
        "IjkGridRepresentation": "resqml20.obj_IjkGridRepresentation",
        "Grid2dRepresentation": "resqml20.obj_Grid2dRepresentation",
        "WellboreFeature": "resqml20.obj_WellboreFeature",
        "WellboreTrajectory": "resqml20.obj_WellboreTrajectoryRepresentation",
        "HorizonInterpretation": "resqml20.obj_HorizonInterpretation",
        "FaultInterpretation": "resqml20.obj_FaultInterpretation",
        "ContinuousProperty": "resqml20.obj_ContinuousProperty",
        "DiscreteProperty": "resqml20.obj_DiscreteProperty",
        "WellboreFrameRepresentation": "resqml20.obj_WellboreFrameRepresentation",
        "GenericRepresentation": "resqml20.obj_Grid2dRepresentation",
    }
    if kind_type in type_map:
        return type_map[kind_type]
    # From data.SchemaFormatTypeID
    ct = data.get("SchemaFormatTypeID") or data.get("ContentType") or ""
    m = _re.search(r"(resqml\d+\.obj_\w+)", ct)
    if m:
        return m.group(1)
    return kind_type if kind_type else None


# ──────────────────────────────────────────────────────────────────────────────
# Federated search - resolver implementation
# ──────────────────────────────────────────────────────────────────────────────

# Default RESQML types to search when no type_name is specified
_FEDERATED_TYPES = [
    # Grids
    "resqml20.obj_IjkGridRepresentation",
    "resqml20.obj_UnstructuredGridRepresentation",
    "resqml20.obj_Grid2dRepresentation",
    # Wells
    "resqml20.obj_WellboreFeature",
    "resqml20.obj_WellboreTrajectoryRepresentation",
    "resqml20.obj_WellboreFrameRepresentation",
    "resqml20.obj_WellboreMarkerFrameRepresentation",
    "resqml20.obj_DeviationSurveyRepresentation",
    # Surfaces
    "resqml20.obj_TriangulatedSetRepresentation",
    "resqml20.obj_PolylineSetRepresentation",
    "resqml20.obj_PointSetRepresentation",
    # Structural
    "resqml20.obj_HorizonInterpretation",
    "resqml20.obj_FaultInterpretation",
    "resqml20.obj_GeobodyBoundaryInterpretation",
    "resqml20.obj_StructuralOrganizationInterpretation",
    # Stratigraphic
    "resqml20.obj_StratigraphicColumn",
    "resqml20.obj_StratigraphicColumnRankInterpretation",
    "resqml20.obj_StratigraphicUnitInterpretation",
    # Properties
    "resqml20.obj_ContinuousProperty",
    "resqml20.obj_DiscreteProperty",
    "resqml20.obj_CategoricalProperty",
]


async def federated_search_impl(
    token: str,
    text: str,
    kind: Optional[str],
    type_name: Optional[str],
    dataspaces: Optional[List[str]],
    search_catalog: bool,
    search_rddms: bool,
    search_remote_rddms: bool,
    include_relations: bool,
    include_properties: bool,
    include_statistics: bool,
    property_filter: Optional[PropertyFilter],
    limit: int,
    relation_filter: Optional[List[str]] = None,
) -> FederatedSearchResult:
    """Core federated_search implementation, independent of Strawberry context."""
    import httpx

    hits_by_uuid: Dict[str, FederatedHit] = {}
    total_catalog = 0
    total_rddms = 0
    sources: List[str] = []

    # ── Path A: OSDU Catalog ──────────────────────────────────────────────
    if search_catalog and osdu.OSDU_BASE_URL:
        search_url = f"https://{osdu.OSDU_BASE_URL}/api/search/v2/query"
        hdr = osdu.headers(token)
        osdu_kind = kind or "osdu:wks:work-product-component--*:*"

        # Build query: include type_name in search text so catalog
        # filters by RESQML type (e.g. "IjkGridRepresentation")
        query_text = text if text != "*" else "*"
        if type_name and query_text == "*":
            short_type = type_name.rsplit(".", 1)[-1].replace("obj_", "")
            query_text = f"\"{short_type}\""
        elif type_name and query_text != "*":
            short_type = type_name.rsplit(".", 1)[-1].replace("obj_", "")
            query_text = f"{query_text} AND \"{short_type}\""

        payload: Dict[str, Any] = {
            "kind": osdu_kind,
            "query": query_text,
            "limit": min(limit, 100),
            "returnedFields": ["id", "kind", "version", "data"],
            "trackTotalCount": True,
        }
        try:
            async with osdu.http_client(timeout=30) as client:
                r = await client.post(search_url, headers=hdr, json=payload)
                r.raise_for_status()
                resp = r.json()
                total_catalog = int(resp.get("totalCount") or 0)
                sources.append("OSDU catalog")

                for hit in resp.get("results", [])[:limit]:
                    rid = hit.get("id", "")
                    rkind = hit.get("kind", "")
                    data = hit.get("data") or {}
                    name = (
                        data.get("Name") or data.get("FacilityName")
                        or data.get("Description") or data.get("ProjectName")
                        or (rid.rsplit(":", 1)[0].rsplit("--", 1)[-1] if rid else "")
                    )
                    uuid = _extract_uuid(data, rid)
                    ds = _extract_dataspace(data, rid)
                    rtype = _extract_resqml_type(rkind, data)

                    # Post-filter: skip catalog hits that don't match the
                    # requested type_name (if one was specified)
                    if type_name and rtype:
                        short_requested = type_name.rsplit(".", 1)[-1].replace("obj_", "").lower()
                        short_actual = rtype.rsplit(".", 1)[-1].replace("obj_", "").lower()
                        if short_requested != short_actual:
                            continue

                    fh = FederatedHit(
                        uuid=uuid or rid,
                        title=name,
                        type_name=rtype or "",
                        dataspace=ds or "",
                        found_in_catalog=True,
                        osdu_id=rid,
                        osdu_kind=rkind,
                        data_json=json.dumps(data) if data else None,
                    )
                    key = uuid or rid
                    hits_by_uuid[key] = fh

        except Exception as e:
            log.warning("federated_search catalog path failed: %s", e)
            sources.append(f"OSDU catalog (error: {e})")

    # ── Determine RESQML types to search ──────────────────────────────────
    target_types: List[str] = [type_name] if type_name else list(_FEDERATED_TYPES)

    # `text` is the OSDU Search query string (used for catalog full-text search).
    # For RDDMS, apply it as a title filter ONLY when no dataspaces are given;
    # when dataspaces are specified they already scope the RDDMS results and the
    # text parameter is likely a project name (e.g. "Drogon") that won't match
    # individual RESQML object titles (e.g. "Simgrid", "TopVolantis").
    title_filter = text if text != "*" and not dataspaces else None
    total_local_rddms = 0
    total_remote_rddms = 0

    # RDDMS scanning uses a higher internal limit so catalog hits won't
    # starve the RDDMS side.  The final result is truncated to `limit`.
    _rddms_scan_limit = limit * 3

    # ── Path B: Local RDDMS (PostgreSQL direct) ───────────────────────────
    if search_rddms:
        pool = await _get_pool()
        if pool:
            # Discover which of the requested dataspaces are in local PG
            local_ds_set: set = set()
            all_local = await _pg_list_dataspaces(pool)
            local_ds_set = {d["path"] for d in all_local}

            ds_list = list(dataspaces) if dataspaces else []
            if not ds_list:
                ds_list = list(local_ds_set)[:50]

            # Only search local dataspaces via PG
            local_dataspaces = [d for d in ds_list if d in local_ds_set]

            if local_dataspaces:
                sources.append("PostgreSQL")
                for ds in local_dataspaces:
                    for ttype in target_types:
                        try:
                            resources = await _pg_list_resources(pool, ds, ttype, limit)
                            for r in resources:
                                uid = r["uuid"]
                                rtitle = r["title"]
                                if title_filter and title_filter.lower() not in rtitle.lower():
                                    continue
                                total_local_rddms += 1
                                key = uid or f"{ds}::{ttype}::{rtitle}"

                                if key in hits_by_uuid:
                                    hits_by_uuid[key].found_in_rddms = True
                                    hits_by_uuid[key].found_in_local_rddms = True
                                    if not hits_by_uuid[key].dataspace:
                                        hits_by_uuid[key].dataspace = ds
                                    if not hits_by_uuid[key].type_name:
                                        hits_by_uuid[key].type_name = ttype
                                else:
                                    hits_by_uuid[key] = FederatedHit(
                                        uuid=uid or key, title=rtitle,
                                        type_name=ttype, dataspace=ds,
                                        found_in_rddms=True,
                                        found_in_local_rddms=True,
                                    )
                        except Exception:
                            pass
                        if len(hits_by_uuid) >= _rddms_scan_limit:
                            break
                    if len(hits_by_uuid) >= _rddms_scan_limit:
                        break

    # ── Path C: Remote RDDMS (REST API) ──────────────────────────────────
    if search_remote_rddms and osdu.OSDU_BASE_URL:
        pool = await _get_pool()
        ds_list = list(dataspaces) if dataspaces else []

        # Determine which dataspaces are remote (not in local PG)
        local_ds_set_c: set = set()
        if pool:
            all_local_c = await _pg_list_dataspaces(pool)
            local_ds_set_c = {d["path"] for d in all_local_c}

        remote_dataspaces = [d for d in ds_list if d not in local_ds_set_c]

        # If no specific dataspaces given, try to list from remote RDDMS
        if not ds_list:
            try:
                remote_rows = await _rest_list_dataspaces(token)
                remote_dataspaces = [d["path"] for d in remote_rows
                                    if d["path"] not in local_ds_set_c][:50]
            except Exception:
                remote_dataspaces = []

        if remote_dataspaces:
            sources.append("Remote RDDMS")
            for ds in remote_dataspaces:
                for ttype in target_types:
                    try:
                        resources = await _rest_list_resources(token, ds, ttype, limit)
                        for r in resources:
                            uid = r["uuid"]
                            rtitle = r["title"]
                            if title_filter and title_filter.lower() not in rtitle.lower():
                                continue
                            total_remote_rddms += 1
                            key = uid or f"{ds}::{ttype}::{rtitle}"

                            if key in hits_by_uuid:
                                hits_by_uuid[key].found_in_rddms = True
                                hits_by_uuid[key].found_in_remote_rddms = True
                                if not hits_by_uuid[key].dataspace:
                                    hits_by_uuid[key].dataspace = ds
                                if not hits_by_uuid[key].type_name:
                                    hits_by_uuid[key].type_name = ttype
                            else:
                                hits_by_uuid[key] = FederatedHit(
                                    uuid=uid or key, title=rtitle,
                                    type_name=ttype, dataspace=ds,
                                    found_in_rddms=True,
                                    found_in_remote_rddms=True,
                                )
                    except Exception:
                        pass
                    if len(hits_by_uuid) >= _rddms_scan_limit:
                        break
                if len(hits_by_uuid) >= _rddms_scan_limit:
                    break

    total_rddms = total_local_rddms + total_remote_rddms

    # ── Enrichment phase: relations + properties ──────────────────────────
    if include_relations or include_properties or property_filter:
        pool = await _get_pool()
        for fh in list(hits_by_uuid.values())[:limit]:
            if not fh.dataspace or not fh.type_name or not fh.uuid:
                continue
            try:
                if pool and include_relations:
                    rels = await _pg_list_relations(pool, fh.dataspace, fh.type_name, fh.uuid, "both")
                    raw_rels = [
                        RelationInfo(
                            uuid=r["uuid"], name=r["name"], type_name=r["type_name"],
                            direction=r["direction"], content_type=r["content_type"],
                        ) for r in rels
                    ]
                    fh.relations = _filter_relations(raw_rels, relation_filter)
                elif not pool and include_relations:
                    try:
                        targets = await _gql_or_rest_list_targets(token, fh.dataspace, fh.type_name, fh.uuid)
                        sources_r = await _gql_or_rest_list_sources(token, fh.dataspace, fh.type_name, fh.uuid)
                        rels_list: List[RelationInfo] = []
                        for t in targets:
                            ct = t.get("ContentType") or ""
                            rels_list.append(RelationInfo(
                                uuid=t.get("UUID") or t.get("uuid") or "",
                                name=t.get("Title") or t.get("name") or "",
                                type_name=ct, direction="target", content_type=ct,
                            ))
                        for s in sources_r:
                            ct = s.get("ContentType") or ""
                            rels_list.append(RelationInfo(
                                uuid=s.get("UUID") or s.get("uuid") or "",
                                name=s.get("Title") or s.get("name") or "",
                                type_name=ct, direction="source", content_type=ct,
                            ))
                        fh.relations = _filter_relations(rels_list, relation_filter)
                    except Exception:
                        pass

                if pool and (include_properties or property_filter):
                    # Find property sources
                    if not fh.relations:
                        rels = await _pg_list_relations(pool, fh.dataspace, fh.type_name, fh.uuid, "sources")
                        all_rels = rels
                    else:
                        all_rels = [{"uuid": r.uuid, "name": r.name, "type_name": r.type_name, "direction": r.direction}
                                   for r in (fh.relations or [])]
                    prop_rels = [
                        r for r in all_rels
                        if r.get("direction", "") == "source" and "Property" in r.get("type_name", "")
                    ]
                    if prop_rels:
                        props: List[PropertyInfo] = []
                        passes_filter = not property_filter
                        for pr in prop_rels[:20]:
                            pi = PropertyInfo(
                                uuid=pr["uuid"], title=pr["name"],
                                type_name=pr["type_name"], kind="",
                            )
                            if include_statistics or property_filter:
                                try:
                                    arrays = await _pg_list_arrays(pool, fh.dataspace, pr["uuid"])
                                    if arrays:
                                        values = await _pg_read_array(pool, fh.dataspace, pr["uuid"], arrays[0]["path"])
                                        if values:
                                            pi.statistics = _compute_statistics(values)
                                            if property_filter and property_filter.array_filter:
                                                af = property_filter.array_filter
                                                match = _check_threshold(values, af.threshold, af.operator, af.threshold_high)
                                                pi.matching_cells = match
                                                if match.count > 0:
                                                    passes_filter = True
                                except Exception:
                                    pass

                            # Title filter on property
                            if property_filter and property_filter.title_contains:
                                if property_filter.title_contains.lower() not in pi.title.lower():
                                    continue
                            props.append(pi)

                        if property_filter and not passes_filter:
                            # Remove this hit - doesn't pass filter
                            del hits_by_uuid[fh.uuid]
                            continue
                        fh.properties = props if props else None
            except Exception as e:
                log.debug("federated enrichment failed for %s: %s", fh.uuid, e)

    # ── Build result ──────────────────────────────────────────────────────
    # Fair merge: cross-referenced hits first (found in both systems),
    # then round-robin RDDMS-only and catalog-only so both sides get
    # equal representation within the limit.
    all_hits = list(hits_by_uuid.values())
    cross_refs = [h for h in all_hits
                  if h.found_in_catalog and (h.found_in_local_rddms or h.found_in_remote_rddms)]
    rddms_only = [h for h in all_hits
                  if not h.found_in_catalog and (h.found_in_local_rddms or h.found_in_remote_rddms)]
    cat_only = [h for h in all_hits
                if h.found_in_catalog and not h.found_in_local_rddms and not h.found_in_remote_rddms]

    merged: List[FederatedHit] = list(cross_refs)
    it_r, it_c = iter(rddms_only), iter(cat_only)
    while len(merged) < limit:
        added = False
        for it in (it_r, it_c):
            try:
                merged.append(next(it))
                added = True
            except StopIteration:
                pass
        if not added:
            break
    merged = merged[:limit]
    desc_parts = []
    if text != "*":
        desc_parts.append(f"text='{text}'")
    if kind:
        desc_parts.append(f"kind={kind}")
    if type_name:
        desc_parts.append(f"type={type_name}")
    if dataspaces:
        desc_parts.append(f"dataspaces={dataspaces}")
    desc_parts.append(f"sources: {', '.join(sources)}")

    return FederatedSearchResult(
        hits=merged,
        total_catalog=total_catalog,
        total_rddms=total_rddms,
        total_local_rddms=total_local_rddms,
        total_remote_rddms=total_remote_rddms,
        total_merged=len(merged),
        query_description=" | ".join(desc_parts),
        sources=sources,
    )
