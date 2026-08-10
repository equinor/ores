"""
Search router – extracted from main.py for maintainability.

Handles:
  GET  /search              – render search form
  POST /search/run          – OSDU record search (kinds)
  POST /search/schemas      – OSDU Schema Service search
  POST /search/refdata      – Reference-data record search
  GET  /search/view/{id}    – single record detail view
  GET  /api/queries         – list saved queries for current user
  POST /api/queries         – save a query
  DELETE /api/queries/{id}  – delete a saved query
"""

from __future__ import annotations
import asyncio
import logging
import os
import re
from typing import Any, Dict, List, Set

import httpx
from httpx import HTTPStatusError
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from . import osdu
from .cache import cached_call
from .common import access_token as _access_token, friendly_value as _friendly_value, friendly_list as _friendly_list, pretty_val as _jinja_pretty_val
from .schemahandler import extract_osdu_links, extract_metadata_generic
from .tokenstore import (
    save_query as _ts_save_query,
    list_queries as _ts_list_queries,
    delete_query as _ts_delete_query,
)

log = logging.getLogger("rddms-admin.search")

router = APIRouter()

_KIND_CACHE_TTL = 300  # 5 minutes – used by cached_call for kind resolution
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))

templates.env.filters["pretty_val"] = _jinja_pretty_val


def _jinja_linkify(text: str) -> str:
    """Auto-link URLs and OSDU record IDs in text.

    - https://... → clickable <a> link
    - OSDU IDs (partition:namespace--Type:id:version) → /search/view/ link
    """
    import markupsafe
    if not text:
        return ""
    t = markupsafe.escape(text)
    # Linkify URLs (http/https)
    t = re.sub(
        r'(https?://[^\s"\'>< ]+)',
        r'<a href="\1" target="_blank" rel="noopener" style="color:#2b6cb0;">\1</a>',
        str(t),
    )
    # Linkify OSDU record IDs (e.g. dev:master-data--Well:abc123:1)
    t = re.sub(
        r'(?<!["\'/])(\w+:(?:master-data|work-product-component|dataset|reference-data)--[\w]+:[\w\-]+:\d+)',
        r'<a href="/search/view/\1" style="color:#2b6cb0;">\1</a>',
        t,
    )
    return markupsafe.Markup(t)


templates.env.filters["linkify"] = _jinja_linkify
# init.  We no longer duplicate it here to avoid capturing a stale value
# (the import would snapshot AUTH_MODE before instances are loaded).


# ──────────────────────────────────────────────────────────────────────────────
# Utilities (private to this module)
# ──────────────────────────────────────────────────────────────────────────────


def _dataspace_label(data: Dict[str, Any]) -> str | None:
    """Extract a human-friendly source label from DDMSDatasets URI dataspace.

    E.g. 'eml:///dataspace(\"drogon/sor\")/...' → 'drogon'
    Returns the first path segment of the dataspace (the project name).
    """
    for duri in (data.get("DDMSDatasets") or []):
        if not isinstance(duri, str):
            continue
        m = re.search(r"dataspace\(['\"]?([^'\"\)\s]+)['\"]?\)", duri)
        if m:
            ds = m.group(1)
            # Take the first path component as the project name
            # e.g. "drogon/sor" → "drogon", "norway" → "norway"
            label = ds.split("/")[0].strip()
            if label:
                return label
    return None


def _best_name(data: Dict[str, Any], kind: str = "") -> str | None:
    """Best human-readable name for an OSDU record, across record kinds.

    Many kinds carry their title in a field other than ``Name`` – e.g.
    ``FeatureName`` for *Feature master-data, ``FacilityName`` for wells,
    or ``Citation.Title`` for RESQML-derived work-product-components.
    Returns ``None`` when nothing usable is found so the caller can fall
    back to the record id.
    """
    if not isinstance(data, dict):
        return None
    name = data.get("Name")
    if isinstance(name, str):
        name = name.strip()
        if name and name != "|UNNAMED|":
            return name
    for key in ("FacilityName", "FeatureName", "InterpretationName"):
        v = data.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    cit = data.get("Citation")
    if isinstance(cit, dict):
        t = cit.get("Title")
        if isinstance(t, str) and t.strip():
            return t.strip()
    t = data.get("Title")
    if isinstance(t, str) and t.strip():
        return t.strip()
    # SeismicBinGrid / SeismicTraceData: try survey-related fields
    for key in ("SeismicAcquisitionSurveyName", "SurveyName"):
        v = data.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    # ETPDataspace dataset records: derive a label from the dataspace URI
    dp = data.get("DatasetProperties")
    if isinstance(dp, dict):
        uri = dp.get("URI")
        if isinstance(uri, str):
            m = re.search(r"dataspace\(['\"]?([^'\"\)\s]+)['\"]?\)", uri)
            if m:
                return m.group(1)
    # Last resort: derive project name from DDMSDatasets dataspace
    ds_label = _dataspace_label(data)
    if ds_label:
        return ds_label
    return None


def _display_name(data: Dict[str, Any], kind: str = "", rid: str = "") -> str:
    """Human-readable display name with id fallback (never empty)."""
    return _best_name(data, kind) or rid or "-"


def _best_description(data: Dict[str, Any]) -> str | None:
    """Best human-readable description for an OSDU record.

    Checks top-level Description, then Citation.Description, then
    synthesises a FIRP-based semantic summary from relationships.
    """
    if not isinstance(data, dict):
        return None
    desc = data.get("Description")
    if isinstance(desc, str) and desc.strip():
        return desc.strip()
    cit = data.get("Citation")
    if isinstance(cit, dict):
        d = cit.get("Description")
        if isinstance(d, str) and d.strip():
            return d.strip()
    # Synthesise from FIRP hierarchy relationships
    return _firp_summary(data)


def _firp_summary(data: Dict[str, Any]) -> str | None:
    """Synthesise a description from RESQML FIRP hierarchy fields.

    FIRP = Feature → Interpretation → Representation → Property.
    Extracts semantic meaning from relationship fields present in the record.
    """
    parts: list[str] = []
    # Representation-level: linked interpretation
    interp_name = data.get("InterpretationName")
    if isinstance(interp_name, str) and interp_name.strip():
        parts.append(f"Interpretation: {interp_name.strip()}")
    # Role / Type (GenericRepresentation, HorizonControlPoints)
    role = data.get("Role") or data.get("RepresentationRole")
    rtype = data.get("Type") or data.get("RepresentationType")
    if isinstance(role, str) and role.strip():
        parts.append(f"Role: {role.strip()}")
    if isinstance(rtype, str) and rtype.strip():
        parts.append(f"Type: {rtype.strip()}")
    # Domain
    domain = data.get("DomainTypeID")
    if isinstance(domain, str) and domain.strip():
        parts.append(f"Domain: {domain.strip()}")
    # Grid geometry summary (SeismicBinGrid / StructureMap)
    for axis_label, i_key, j_key in [
        ("Nodes", "NodeCountOnIAxis", "NodeCountOnJAxis"),
        ("Inline/Xline", "InlineMin", "CrosslineMin"),
    ]:
        iv = data.get(i_key)
        jv = data.get(j_key)
        if iv is not None and jv is not None:
            if axis_label == "Nodes":
                parts.append(f"{iv}×{jv} nodes")
            else:
                i_max = data.get("InlineMax")
                x_max = data.get("CrosslineMax")
                if i_max is not None and x_max is not None:
                    parts.append(f"IL {iv}–{i_max}, XL {jv}–{x_max}")
            break
    # Seismic acquisition survey reference
    survey = data.get("SeismicAcquisitionSurveyName") or data.get("SurveyName")
    if isinstance(survey, str) and survey.strip():
        parts.append(f"Survey: {survey.strip()}")
    # Source / project name from DDMSDatasets URI dataspace or Source field
    source = data.get("Source")
    if isinstance(source, str) and source.strip():
        parts.append(f"Source: {source.strip()}")
    else:
        # Derive project/source from DDMSDatasets dataspace name (e.g. "drogon/sor" → "drogon")
        ds_name = _dataspace_label(data)
        if ds_name:
            parts.append(f"Source: {ds_name}")
    # ExistenceKind
    ek = data.get("ExistenceKind")
    if isinstance(ek, str) and ek.strip() and ek.strip().lower() not in ("actual",):
        parts.append(ek.strip())
    return " · ".join(parts) if parts else None


async def _resolve_wildcard_kind(
    client: httpx.AsyncClient, search_url: str, hdr: dict, wildcard_kind: str,
) -> List[str]:
    """Discover concrete kind versions for a wildcard kind pattern.

    Returns a sorted list of concrete kinds, or [] if the probe fails.
    Used as the backend function for ``cached_call``.
    """
    probe_kinds: Set[str] = set()
    probe_payload = {
        "kind": wildcard_kind,
        "query": "*",
        "limit": 1,
        "returnedFields": ["kind"],
        "trackTotalCount": True,
    }
    try:
        pr = await client.post(search_url, headers=hdr, json=probe_payload)
        pr.raise_for_status()
        probe_res = pr.json()
        for prec in probe_res.get("results", []):
            pk = prec.get("kind")
            if pk:
                probe_kinds.add(pk)
        # Wider probe when first page returned few distinct kinds
        probe_total = int(probe_res.get("totalCount") or 0)
        if probe_total > 1 and len(probe_kinds) < 5:
            probe_payload["limit"] = min(probe_total, 50)
            pr2 = await client.post(search_url, headers=hdr, json=probe_payload)
            if pr2.status_code == 200:
                for prec in pr2.json().get("results", []):
                    pk = prec.get("kind")
                    if pk:
                        probe_kinds.add(pk)
        if probe_kinds:
            log.info("[SEARCH] Resolved %s to versions: %s", wildcard_kind, probe_kinds)
        else:
            log.info("[SEARCH] Probe for %s returned 0 records", wildcard_kind)
    except Exception as e:
        log.warning("[SEARCH] Version probe failed for %s: %s", wildcard_kind, e)

    return sorted(probe_kinds)


def _parse_kind_inputs(kind: str, kinds_extra: str) -> List[str]:
    """Build an ordered, de-duplicated list of kinds from primary + extra inputs."""
    out: List[str] = []
    seen: Set[str] = set()
    candidates: List[str] = []
    if kind:
        candidates.append(kind)
    if kinds_extra:
        for token in re.split(r"[\n,;]+", kinds_extra):
            token = token.strip()
            if token:
                candidates.append(token)
    for k in candidates:
        if k and k not in seen:
            out.append(k)
            seen.add(k)
    return out


def _collect_manifest_kinds() -> List[Dict[str, Any]]:
    """Return a grouped list of OSDU kinds for the search dropdown.

    Uses wildcard versions (``*``) so the dropdown matches all indexed
    versions of each entity type.  The user can manually edit the
    version in the text input if a specific one is needed.

    Kinds are grouped by category (Dataset, Master Data, WPC) for better UX
    in the dropdown. Each entry has 'kind', 'label', and 'group'.
    """
    _KINDS_GROUPED: list[tuple[str, str]] = [
        # (group_label, kind)
        ("Dataset", "osdu:wks:dataset--ETPDataspace:*"),
        ("Dataset", "osdu:wks:dataset--FileCollection.Bluware.OpenVDS:*"),
        ("Dataset", "osdu:wks:dataset--FileCollection.SEGY:*"),
        ("Master Data", "osdu:wks:master-data--BusinessDecision:*"),
        ("Master Data", "osdu:wks:master-data--CollaborationProject:*"),
        ("Master Data", "osdu:wks:master-data--Field:*"),
        ("Master Data", "osdu:wks:master-data--LocalBoundaryFeature:*"),
        ("Master Data", "osdu:wks:master-data--Organisation:*"),
        ("Master Data", "osdu:wks:master-data--Reservoir:*"),
        ("Master Data", "osdu:wks:master-data--ReservoirSegment:*"),
        ("Master Data", "osdu:wks:master-data--Risk:*"),
        ("Master Data", "osdu:wks:master-data--Well:*"),
        ("Master Data", "osdu:wks:master-data--Wellbore:*"),
        ("WPC – Subsurface", "osdu:wks:work-product-component--Activity:*"),
        ("WPC – Subsurface", "osdu:wks:work-product-component--ActivityTemplate:*"),
        ("WPC – Subsurface", "osdu:wks:work-product-component--ColumnBasedTable:*"),
        ("WPC – Subsurface", "osdu:wks:work-product-component--DevelopmentConcept:*"),
        ("WPC – Subsurface", "osdu:wks:work-product-component--GeoLabelSet:*"),
        ("WPC – Subsurface", "osdu:wks:work-product-component--GenericRepresentation:*"),
        ("WPC – Subsurface", "osdu:wks:work-product-component--ReservoirEstimatedVolumes:*"),
        ("WPC – Subsurface", "osdu:wks:work-product-component--StructureMap:*"),
        ("WPC – Geo Model", "osdu:wks:work-product-component--GenericBinGrid:*"),
        ("WPC – Geo Model", "osdu:wks:work-product-component--HorizonControlPoints:*"),
        ("WPC – Geo Model", "osdu:wks:work-product-component--HorizonInterpretation:*"),
        ("WPC – Geo Model", "osdu:wks:work-product-component--IjkGridRepresentation:*"),
        ("WPC – Geo Model", "osdu:wks:work-product-component--LocalBoundaryFeature:*"),
        ("WPC – Geo Model", "osdu:wks:work-product-component--LocalModelCompoundCrs:*"),
        ("WPC – Geo Model", "osdu:wks:work-product-component--StratigraphicColumn:*"),
        ("WPC – Geo Model", "osdu:wks:work-product-component--StratigraphicColumnRankInterpretation:*"),
        ("WPC – Geo Model", "osdu:wks:work-product-component--StratigraphicUnitInterpretation:*"),
        ("WPC – Wells", "osdu:wks:work-product-component--WellLog:*"),
        ("WPC – Wells", "osdu:wks:work-product-component--WellboreMarkerSet:*"),
        ("WPC – Wells", "osdu:wks:work-product-component--WellboreTrajectory:*"),
        ("WPC – Seismic", "osdu:wks:work-product-component--SeismicBinGrid:*"),
        ("WPC – Seismic", "osdu:wks:work-product-component--SeismicFault:*"),
        ("WPC – Seismic", "osdu:wks:work-product-component--SeismicHorizon:*"),
        ("WPC – Seismic", "osdu:wks:work-product-component--SeismicTraceData:*"),
        ("WPC – Collections", "osdu:wks:work-product-component--CollaborationProjectCollection:*"),
        ("WPC – Collections", "osdu:wks:work-product-component--Document:*"),
        ("WPC – Collections", "osdu:wks:work-product-component--PersistedCollection:*"),
    ]
    return [
        {"kind": k, "label": re.sub(r"^.*--", "", k).replace(":*", ""), "group": g}
        for g, k in _KINDS_GROUPED
    ]


def _collect_refdata_kinds() -> List[Dict[str, Any]]:
    """Return an alphabetically sorted list of reference-data kinds.

    This is a comprehensive static list of known OSDU reference-data types.
    Additional types will be discovered dynamically via /search/api/refdata-kinds.
    """
    _REFDATA_KINDS: list[str] = [
        "osdu:wks:reference-data--AliasNameType:1.0.0",
        "osdu:wks:reference-data--BasinType:1.0.0",
        "osdu:wks:reference-data--ChronoStratigraphicScheme:1.0.0",
        "osdu:wks:reference-data--ChronoStratigraphy:1.0.0",
        "osdu:wks:reference-data--ColumnBasedTableType:1.0.0",
        "osdu:wks:reference-data--CoordinateReferenceSystem:1.0.0",
        "osdu:wks:reference-data--DecisionApprovalStatus:1.0.0",
        "osdu:wks:reference-data--DecisionLevel:1.0.0",
        "osdu:wks:reference-data--DocumentType:1.0.0",
        "osdu:wks:reference-data--ExplorationPhaseType:1.0.0",
        "osdu:wks:reference-data--FacetRole:1.1.0",
        "osdu:wks:reference-data--FieldDevelopmentPhaseType:1.0.0",
        "osdu:wks:reference-data--FluidType:1.0.0",
        "osdu:wks:reference-data--GeoLabelType:1.0.0",
        "osdu:wks:reference-data--GeologicTimePeriod:1.0.0",
        "osdu:wks:reference-data--IndexableElement:1.0.0",
        "osdu:wks:reference-data--LithoStratigraphicRank:1.0.0",
        "osdu:wks:reference-data--LithoStratigraphy:1.0.0",
        "osdu:wks:reference-data--LogCurveFamily:1.0.0",
        "osdu:wks:reference-data--LogCurveType:1.0.0",
        "osdu:wks:reference-data--MeasurementType:1.0.0",
        "osdu:wks:reference-data--OperatingEnvironment:1.0.0",
        "osdu:wks:reference-data--OrganisationType:1.0.0",
        "osdu:wks:reference-data--ParameterType:1.0.0",
        "osdu:wks:reference-data--PlayType:1.0.0",
        "osdu:wks:reference-data--PropertyType:1.0.0",
        "osdu:wks:reference-data--RepresentationType:1.0.0",
        "osdu:wks:reference-data--ReservoirEstimatedVolumePropertyType:1.0.0",
        "osdu:wks:reference-data--ResourceLifecycleStatus:1.0.0",
        "osdu:wks:reference-data--RiskAcceptanceCriteria:1.0.0",
        "osdu:wks:reference-data--RiskCategory:1.0.0",
        "osdu:wks:reference-data--RiskDiscipline:1.0.0",
        "osdu:wks:reference-data--RiskImpactType:1.0.0",
        "osdu:wks:reference-data--RiskProbabilityScale:1.0.0",
        "osdu:wks:reference-data--RiskSeverityScale:1.0.0",
        "osdu:wks:reference-data--RoleType:1.0.0",
        "osdu:wks:reference-data--SeismicAcquisitionType:1.0.0",
        "osdu:wks:reference-data--SeismicDimensionType:1.0.0",
        "osdu:wks:reference-data--SeismicDomainType:1.0.0",
        "osdu:wks:reference-data--SeismicProcessingType:1.0.0",
        "osdu:wks:reference-data--StratigraphicRoleType:1.0.0",
        "osdu:wks:reference-data--TrappingType:1.0.0",
        "osdu:wks:reference-data--UnitOfMeasure:1.0.0",
        "osdu:wks:reference-data--VerticalMeasurementType:1.0.0",
        "osdu:wks:reference-data--WellActivityType:1.0.0",
        "osdu:wks:reference-data--WellBoreStatusType:1.0.0",
        "osdu:wks:reference-data--WellStatusType:1.0.0",
        "osdu:wks:reference-data--WellType:1.0.0",
    ]
    return [{"kind": k} for k in _REFDATA_KINDS]

# Pre-compute static kind lists (pure data - no reason to rebuild per request)
_MANIFEST_KINDS = _collect_manifest_kinds()
_REFDATA_KINDS_LIST = _collect_refdata_kinds()


# ──────────────────────────────────────────────────────────────────────────────
# Record enrichment helpers (moved from main.py)
# ──────────────────────────────────────────────────────────────────────────────

# Keys whose values are large arrays / blobs - shown separately
_HEAVY_DATA_KEYS = frozenset({
    "ColumnBasedTable", "Columns", "ColumnValues", "ColumnNames",
    "SpatialPoint.AsIngestedCoordinates.persistableReferenceCrs",
    "VirtualProperties.DefaultLocation.AsIngestedCoordinates.persistableReferenceCrs",
    "SpatialPoint.Wgs84Coordinates",
    "VirtualProperties.DefaultLocation.Wgs84Coordinates",
})


def _flatten_osdu_data(data: Dict[str, Any], max_str: int = 400) -> list:
    """Flatten an OSDU data{} block into [{name, value}, ...] pairs."""
    pairs = []
    for k in sorted(data.keys()):
        if k in _HEAVY_DATA_KEYS:
            continue
        v = data[k]
        if v is None:
            pairs.append({"name": k, "value": None})
        else:
            pairs.append({"name": k, "value": _friendly_value(v, max_str)})
    return pairs


async def _reverse_lookup(
    record_id: str,
    client: httpx.AsyncClient,
    search_url: str,
    hdr: Dict[str, str],
) -> List[Dict[str, Any]]:
    """Find records that reference *record_id* (reverse relationships)."""
    try:
        payload = {
            "kind": "*:*:*:*",
            "query": f'"{record_id}"',
            "limit": 20,
            "returnedFields": ["id", "kind"],
        }
        r = await client.post(search_url, headers=hdr, json=payload)
        if r.status_code != 200:
            log.debug("[REV-LOOKUP] search returned %d for %s", r.status_code, record_id)
            return []
        hits = r.json().get("results") or []
        refs: List[Dict[str, Any]] = []
        for h in hits:
            hid = h.get("id", "")
            if hid == record_id:
                continue
            if "reference-data--" in hid:
                continue
            refs.append({
                "id": hid,
                "role": "referenced-by",
                "source_path": "(reverse lookup)",
            })
        if refs:
            log.info("[REV-LOOKUP] %s referenced by %d records", record_id, len(refs))
        return refs
    except Exception as e:
        log.debug("[REV-LOOKUP] Failed for %s: %s", record_id, e)
        return []


async def _enrich_record_light(
    full: Dict[str, Any],
    client: httpx.AsyncClient,
    storage_url: str,
    search_url: str,
    hdr: dict,
) -> Dict[str, Any]:
    """Lightweight enrichment for the search results list.

    For most record types, does NOT call external APIs.
    For BusinessDecision records, fetches GeoLabelSet + stat REV volumes
    (2-3 targeted calls) so headline KPIs render in the list view.
    """
    from .bd_enrichment import (
        _normalize_volumes,
        _enrich_bd_volumes,
        _enrich_bd_geolabel,
        _enrich_bd_production,
    )

    rid = full.get("id", "")
    data_block = full.get("data", {}) or {}
    volumes = _normalize_volumes(data_block)

    # Extract links from within the record (no external fetches)
    try:
        links = extract_osdu_links(data_block) or []
    except Exception as e:
        log.warning("[ENRICH-LIGHT] extract_osdu_links failed for %s: %s", rid, e)
        links = []

    # Compact metadata pairs from data{}
    metadata_pairs: list = []
    try:
        if "Citation" in data_block or "$type" in data_block:
            md = extract_metadata_generic(
                data_block, ds="",
                typ=full.get("kind", "") or "",
                uuid=full.get("id", "") or "",
                arrays=None, max_string_len=300, max_preview_items=5,
            )
            metadata_pairs = [
                p for p in (md.get("pairs", []) or [])
                if not (str(p.get("name")).lower() == "uri"
                        and str(p.get("value") or "").startswith("eml:///"))
            ]
        else:
            metadata_pairs = _flatten_osdu_data(data_block)
    except Exception as e:
        log.warning("[ENRICH-LIGHT] metadata_pairs extraction failed for %s: %s", rid, e)

    result = dict(full)
    result["display_name"] = _display_name(data_block, full.get("kind") or "", rid)
    result["display_description"] = _best_description(data_block) or ""
    result["volumes"] = volumes
    result["links"] = links
    result["linked_labels"] = {}
    result["metadata_pairs"] = metadata_pairs
    # Parse DDMSDatasets URIs for direct RDDMS visualisation (string-only, no API calls)
    ddms_refs: list[dict[str, str]] = []
    for duri in (data_block.get("DDMSDatasets") or []):
        if not isinstance(duri, str):
            continue
        ds_m = re.search(r"dataspace\(['\"]?([^'\"\)\s]+)['\"]?\)", duri)
        uuid_m = re.search(r"\(['\"]?([0-9a-f-]{36})['\"]?\)", duri)
        if ds_m and uuid_m:
            rtype = "map" if "Grid2dRepresentation" in duri else "other"
            ddms_refs.append({
                "ds": ds_m.group(1),
                "uuid": uuid_m.group(1),
                "uri": duri,
                "rtype": rtype,
            })
    result["ddms_refs"] = ddms_refs
    # BD-specific enrichment: fetch GeoLabelSet + stat REV + production
    # for headline volumes (2-3 targeted calls, fast enough for list view)
    bd_geolabel: Dict[str, Any] = {}
    bd_production: Dict[str, Any] = {}
    bd_activity: Dict[str, Any] = {}
    if "businessdecision" in (full.get("kind") or "").lower():
        try:
            vol_task = _enrich_bd_volumes(data_block, client, storage_url, hdr) \
                if not (volumes or {}).get("ColumnValues") else asyncio.sleep(0)
            gl_task = _enrich_bd_geolabel(data_block, client, storage_url, hdr)
            prod_task = _enrich_bd_production(data_block, client, storage_url, hdr)
            vol_r, gl_r, prod_r = await asyncio.gather(
                vol_task, gl_task, prod_task,
                return_exceptions=True,
            )
            if isinstance(vol_r, dict) and vol_r.get("ColumnValues"):
                volumes = vol_r
                result["volumes"] = volumes
            if isinstance(gl_r, dict):
                bd_geolabel = gl_r
            if isinstance(prod_r, dict):
                bd_production = prod_r
        except Exception as e:
            log.warning("[ENRICH-LIGHT] BD enrichment failed for %s: %s", rid, e)
    result["bd_geolabel"] = bd_geolabel
    result["bd_production"] = bd_production
    result["bd_activity"] = bd_activity
    result["bd_maps"] = {"maps": [], "all": []}
    return result


async def _enrich_record(
    full: Dict[str, Any],
    client: httpx.AsyncClient,
    storage_url: str,
    search_url: str,
    hdr: dict,
) -> Dict[str, Any]:
    """Enrich a raw OSDU Storage record with volumes, links, labels, metadata.

    Returns a dict ready for template rendering.
    """
    # Import BD enrichment helpers from main lazily (they depend on heavy logic there)
    from .bd_enrichment import (
        _normalize_volumes,
        _enrich_bd_volumes,
        _enrich_bd_geolabel,
        _enrich_bd_production,
        _enrich_bd_developmentconcept,
        _enrich_bd_activity,
        _enrich_bd_maps,
        _enrich_bd_collaboration,
    )

    rid = full.get("id", "")
    data_block = full.get("data", {}) or {}
    ancestry = data_block.get("ancestry", {}) or {}
    volumes = _normalize_volumes(data_block)

    # BusinessDecision: pull headline volumes + linked WPC data
    bd_geolabel: Dict[str, Any] = {}
    bd_production: Dict[str, Any] = {}
    bd_activity: Dict[str, Any] = {}
    bd_maps: Dict[str, Any] = {"maps": [], "all": []}
    bd_collab: Dict[str, Any] = {}
    if "businessdecision" in (full.get("kind") or "").lower():
        data_block["_record_id"] = rid  # needed by _enrich_bd_collaboration
        vol_task = _enrich_bd_volumes(data_block, client, storage_url, hdr) \
            if not (volumes or {}).get("ColumnValues") else asyncio.sleep(0)
        gl_task = _enrich_bd_geolabel(data_block, client, storage_url, hdr)
        prod_task = _enrich_bd_production(data_block, client, storage_url, hdr)
        dc_task = _enrich_bd_developmentconcept(data_block, client, storage_url, hdr)
        act_task = _enrich_bd_activity(data_block, client, storage_url, hdr)
        map_task = _enrich_bd_maps(data_block, client, storage_url, hdr)
        collab_task = _enrich_bd_collaboration(data_block, client, search_url, storage_url, hdr)
        vol_r, gl_r, prod_r, _, act_r, map_r, collab_r = await asyncio.gather(
            vol_task, gl_task, prod_task, dc_task, act_task, map_task, collab_task,
            return_exceptions=True,
        )
        if isinstance(vol_r, dict) and vol_r.get("ColumnValues"):
            volumes = vol_r
        if isinstance(gl_r, dict):
            bd_geolabel = gl_r
        if isinstance(prod_r, dict):
            bd_production = prod_r
        if isinstance(act_r, dict):
            bd_activity = act_r
        if isinstance(map_r, dict):
            bd_maps = map_r
        if isinstance(collab_r, dict):
            bd_collab = collab_r

    # Generic WPC/master-data links (exclude reference-data)
    try:
        links = extract_osdu_links(data_block) or []
    except Exception as e:
        log.warning("[ENRICH] extract_osdu_links failed for %s: %s", rid, e)
        links = []

    # Reverse-lookup: find records that reference this one
    rev_links = await _reverse_lookup(rid, client, search_url, hdr)
    fwd_ids = {l["id"] for l in links}
    for rl in rev_links:
        if rl["id"] not in fwd_ids:
            links.append(rl)

    # Hydrate labels for linked records (bounded, parallel)
    linked_labels: Dict[str, Dict[str, Any]] = {}
    try:
        unique_lids = []
        for l in links[:200]:
            lid = l.get("id")
            if lid and lid not in linked_labels:
                unique_lids.append(lid)
                linked_labels[lid] = {}

        async def _fetch_label(lid: str):
            try:
                r_link = await client.get(f"{storage_url}/{lid}", headers=hdr)
                if r_link.status_code == 200:
                    rr = r_link.json()
                    nm = _best_name(rr.get("data") or {}, rr.get("kind") or "")
                    entry: Dict[str, Any] = {
                        "name": nm or None,
                        "kind": rr.get("kind"),
                        "version": rr.get("version"),
                    }
                    if "ETPDataspace" in (rr.get("kind") or ""):
                        entry["data"] = rr.get("data") or {}
                    return (lid, entry)
            except Exception:
                pass
            return (lid, {})

        results = await asyncio.gather(*[_fetch_label(lid) for lid in unique_lids])
        for lid, entry in results:
            linked_labels[lid] = entry
    except Exception as e:
        log.warning("[ENRICH] Linked record name hydration failed: %s", e)

    # Compact metadata pairs from data{}
    metadata_pairs: list = []
    try:
        if "Citation" in data_block or "$type" in data_block:
            md = extract_metadata_generic(
                data_block, ds="",
                typ=full.get("kind", "") or "",
                uuid=full.get("id", "") or "",
                arrays=None, max_string_len=300, max_preview_items=5,
            )
            metadata_pairs = [
                p for p in (md.get("pairs", []) or [])
                if not (str(p.get("name")).lower() == "uri"
                        and str(p.get("value") or "").startswith("eml:///"))
            ]
        else:
            metadata_pairs = _flatten_osdu_data(data_block)
    except Exception as e:
        log.warning("[ENRICH] metadata_pairs extraction failed for %s: %s", rid, e)

    # Parse DDMSDatasets URIs for direct RDDMS visualisation
    ddms_refs: list[dict[str, str]] = []
    for duri in (data_block.get("DDMSDatasets") or []):
        if not isinstance(duri, str):
            continue
        ds_m = re.search(r"dataspace\(['\"]?([^'\")\s]+)['\"]?\)", duri)
        uuid_m = re.search(r"\(['\"]?([0-9a-f-]{36})['\"]?\)", duri)
        if ds_m and uuid_m:
            rtype = "map" if "Grid2dRepresentation" in duri else "other"
            ddms_refs.append({
                "ds": ds_m.group(1),
                "uuid": uuid_m.group(1),
                "uri": duri,
                "rtype": rtype,
            })

    return {
        "id": full.get("id"),
        "kind": full.get("kind"),
        "version": full.get("version"),
        "display_name": _display_name(data_block, full.get("kind") or "", full.get("id") or ""),
        "display_description": _best_description(data_block) or "",
        "data": data_block,
        "ancestry_parents": ancestry.get("parents", []) or [],
        "ancestry_children": ancestry.get("children", []) or [],
        "volumes": volumes,
        "links": links,
        "linked_labels": linked_labels,
        "metadata_pairs": metadata_pairs,
        "bd_geolabel": bd_geolabel,
        "bd_production": bd_production,
        "bd_activity": bd_activity,
        "bd_maps": bd_maps,
        "bd_collab": bd_collab,
        "ddms_refs": ddms_refs,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/search", response_class=HTMLResponse, summary="Search form (OSDU search v2)")
async def search_page(request: Request):
    return templates.TemplateResponse(
        request, "search.html",
        {
            "kind": "",
            "kinds_extra": "",
            "kind_options": _MANIFEST_KINDS,
            "refdata_kinds": _REFDATA_KINDS_LIST,
            "q": "",
            "limit": 50,
            "returnedFields": "id,kind,version",
        },
    )


@router.post("/search/run")
async def search_run_post(
    request: Request,
    kind: str = Form(""),
    kinds_extra: str = Form(""),
    query: str = Form("*"),
    limit: int = Form(50),
):
    """POST variant – redirect to GET to implement Post/Redirect/Get pattern."""
    from urllib.parse import urlencode
    params = urlencode({"kind": kind, "kinds_extra": kinds_extra, "query": query, "limit": limit})
    return RedirectResponse(url=f"/search/run?{params}", status_code=303)


@router.get("/search/run", response_class=HTMLResponse)
async def search_run(
    request: Request,
    kind: str = "",
    kinds_extra: str = "",
    query: str = "*",
    limit: int = 50,
):
    """Run an OSDU Search v2 query, then enrich each hit."""
    at = _access_token(request)
    search_url = f"https://{osdu.OSDU_BASE_URL}/api/search/v2/query"
    storage_url = f"https://{osdu.OSDU_BASE_URL}/api/storage/v2/records"
    hdr = osdu.headers(at)

    search_kinds = _parse_kind_inputs(kind, kinds_extra)
    if not search_kinds or all(not k.strip() for k in search_kinds):
        return templates.TemplateResponse(
            request, "search.html",
            {
                "error": "Please select a Kind before searching. Use the dropdown or type a kind like osdu:wks:master-data--BusinessDecision:1.0.0",
                "search_mode": "records",
                "kind": kind,
                "kinds_extra": kinds_extra,
                "kind_options": _MANIFEST_KINDS,
                "refdata_kinds": _REFDATA_KINDS_LIST,
                "q": query,
                "limit": limit,
            },
        )

    try:
        enriched_results: List[Dict[str, Any]] = []
        seen_record_ids: Set[str] = set()
        merged_total_count = 0
        async with osdu.http_client(timeout=60) as client:
            # Phase 1: Search all kinds
            all_hit_ids: List[str] = []
            for current_kind in search_kinds:
                payload = {
                    "kind": current_kind,
                    "query": query,
                    "limit": int(limit),
                    "returnedFields": ["id", "kind", "version"],
                    "trackTotalCount": True,
                }

                # ADME rejects wildcard kind + leading-wildcard query.
                # Detect this and resolve to concrete versions first.
                _has_wildcard_kind = current_kind.endswith(":*")
                _has_leading_wildcard = bool(
                    re.search(r':\s*\*[^\s]', query)
                ) if query and query.strip() != "*" else False

                if _has_wildcard_kind and _has_leading_wildcard:
                    # Resolve wildcard kind to concrete versions (cached)
                    probe_kinds_list: List[str] = await cached_call(
                        f"kind_resolve:{current_kind}",
                        _KIND_CACHE_TTL,
                        _resolve_wildcard_kind, client, search_url, hdr, current_kind,
                    )
                    probe_kinds: Set[str] = set(probe_kinds_list)

                    # Use resolved kinds (from cache or fresh probe)
                    if probe_kinds:
                        for concrete_kind in sorted(probe_kinds):
                            payload["kind"] = concrete_kind
                            r = await client.post(search_url, headers=hdr, json=payload)
                            r.raise_for_status()
                            res = r.json()
                            hit_count = int(res.get("totalCount") or len(res.get("results", [])))
                            merged_total_count += hit_count
                            log.info("[SEARCH] kind=%s status=%d hits=%d", concrete_kind, r.status_code, len(res.get("results", [])))
                            for rec in res.get("results", []):
                                rid = rec.get("id")
                                if rid and rid not in seen_record_ids:
                                    seen_record_ids.add(rid)
                                    all_hit_ids.append(rid)
                                if len(all_hit_ids) >= int(limit):
                                    break
                            if len(all_hit_ids) >= int(limit):
                                break
                        continue  # skip the normal search for this kind

                r = await client.post(search_url, headers=hdr, json=payload)
                r.raise_for_status()
                res = r.json()
                hit_count = int(res.get("totalCount") or len(res.get("results", [])))

                # Auto-retry with wildcard version when exact version returns 0
                if hit_count == 0 and not current_kind.endswith(":*"):
                    wildcard_kind = re.sub(r":[^:]+$", ":*", current_kind)
                    if wildcard_kind != current_kind:
                        log.info("[SEARCH] kind=%s returned 0 hits, retrying with %s", current_kind, wildcard_kind)
                        payload["kind"] = wildcard_kind
                        r = await client.post(search_url, headers=hdr, json=payload)
                        r.raise_for_status()
                        res = r.json()
                        hit_count = int(res.get("totalCount") or len(res.get("results", [])))
                        if hit_count > 0:
                            current_kind = wildcard_kind

                merged_total_count += hit_count
                log.info(
                    "[SEARCH] kind=%s status=%d hits=%d",
                    current_kind, r.status_code, len(res.get("results", [])),
                )
                for rec in res.get("results", []):
                    rid = rec.get("id")
                    if rid and rid not in seen_record_ids:
                        seen_record_ids.add(rid)
                        all_hit_ids.append(rid)
                    if len(all_hit_ids) >= int(limit):
                        break
                if len(all_hit_ids) >= int(limit):
                    break

            # Phase 2: Fetch full storage records in parallel
            _sem = osdu.API_SEMAPHORE

            async def _fetch_full(rid: str):
                async with _sem:
                    try:
                        r_full = await client.get(f"{storage_url}/{rid}", headers=hdr)
                        if r_full.status_code == 200:
                            return r_full.json()
                        log.warning("[SEARCH] Full record fetch failed for %s: %d", rid, r_full.status_code)
                    except Exception as e:
                        log.warning("[SEARCH] Exception fetching %s: %s", rid, e)
                    return None

            full_records = await asyncio.gather(*[_fetch_full(rid) for rid in all_hit_ids])
            valid_records = [
                f for f in full_records
                if f is not None
                and (f.get("data") or {}).get("IsDiscoverable") is not False
                and (f.get("data") or {}).get("Name") not in (".", "")
            ]

            # Phase 3: Light enrichment for the result list (no deep BD
            # enrichment - that happens on individual record view only).
            # This avoids 6+ extra API calls per record during search.
            enriched_results = []
            for full in valid_records:
                try:
                    enriched_results.append(await _enrich_record_light(full, client, storage_url, search_url, hdr))
                except Exception as e:
                    log.warning("[SEARCH] enrich_record_light failed for %s: %s", full.get("id", "?"), e)
                    # Fall back to a minimal result so the record still appears
                    enriched_results.append({
                        "id": full.get("id"),
                        "kind": full.get("kind"),
                        "version": full.get("version"),
                        "display_name": (full.get("data") or {}).get("Name") or full.get("id", ""),
                        "display_description": "",
                        "data": full.get("data", {}),
                        "volumes": {},
                        "links": [],
                        "linked_labels": {},
                        "metadata_pairs": [],
                        "bd_geolabel": {},
                        "bd_production": {},
                        "bd_activity": {},
                        "bd_maps": {"maps": [], "all": []},
                        "ddms_refs": [],
                    })

            enriched_results.sort(
                key=lambda r: (r.get("display_name") or r.get("id") or "").lower()
            )

        return templates.TemplateResponse(
            request, "search.html",
            {
                "results": {
                    "results": enriched_results,
                    "totalCount": merged_total_count or len(enriched_results),
                },
                "kind": kind,
                "kinds_extra": kinds_extra,
                "kind_options": _MANIFEST_KINDS,
                "refdata_kinds": _REFDATA_KINDS_LIST,
                "selected_kinds": search_kinds,
                "q": query,
                "limit": limit,
            },
        )
    except httpx.HTTPStatusError as e:
        r = e.response
        log.warning("[SEARCH] HTTP error: %s %s", r.status_code, r.text[:512] if r.text else "")
        from .common import sanitize_upstream_error
        error_detail = sanitize_upstream_error(r)
        return templates.TemplateResponse(
            request, "search.html",
            {
                "error": f"Search failed: {r.status_code} {r.reason_phrase}",
                "error_detail": error_detail,
                "kind": kind,
                "kinds_extra": kinds_extra,
                "kind_options": _MANIFEST_KINDS,
                "refdata_kinds": _REFDATA_KINDS_LIST,
                "q": query,
                "limit": limit,
            },
            status_code=r.status_code or 500,
        )
    except Exception as e:
        log.exception("[SEARCH] Unexpected error: %s", e)
        return templates.TemplateResponse(
            request, "search.html",
            {
                "error": "Unexpected error",
                "error_detail": "See server logs",
                "kind": kind,
                "kinds_extra": kinds_extra,
                "kind_options": _MANIFEST_KINDS,
                "refdata_kinds": _REFDATA_KINDS_LIST,
                "q": query,
                "limit": limit,
            },
            status_code=500,
        )


# ──────────────────────────────────────────────────────────────────────────────
# Schema search (OSDU Schema Service)
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/search/schemas")
async def search_schemas_post(
    request: Request,
    query: str = Form("*"),
    limit: int = Form(50),
):
    """POST variant – redirect to GET (PRG pattern)."""
    from urllib.parse import urlencode
    params = urlencode({"query": query, "limit": limit})
    return RedirectResponse(url=f"/search/schemas?{params}", status_code=303)


@router.get("/search/schemas", response_class=HTMLResponse)
async def search_schemas(
    request: Request,
    query: str = "*",
    limit: int = 50,
):
    """Search the OSDU Schema Service for registered schemas."""
    at = _access_token(request)
    schema_url = f"https://{osdu.OSDU_BASE_URL}/api/schema-service/v1/schema"
    hdr = osdu.headers(at)

    try:
        params: Dict[str, Any] = {"limit": min(int(limit), 500)}
        # The OSDU Schema Service only supports exact-match parameters.
        # For bare keywords and entity: prefix, we fetch a broad set and
        # filter locally (substring match) since the API doesn't do wildcards.
        local_filter_keyword = ""
        if query and query.strip() != "*":
            tokens = query.strip().split()
            for tok in tokens:
                if tok.startswith("authority:"):
                    params["authority"] = tok.split(":", 1)[1]
                elif tok.startswith("source:"):
                    params["source"] = tok.split(":", 1)[1]
                elif tok.startswith("entity:"):
                    # Use as local filter (service needs exact full entityType
                    # like "master-data--BusinessDecision", not just short name)
                    local_filter_keyword = tok.split(":", 1)[1].lower()
                elif tok.startswith("status:"):
                    params["status"] = tok.split(":", 1)[1].upper()
                elif tok.startswith("scope:"):
                    params["scope"] = tok.split(":", 1)[1].upper()
                else:
                    # Bare keyword – use as local substring filter
                    local_filter_keyword = tok.lower()

        # When doing local keyword filtering, fetch a large set from the API
        # (the keyword might not be in the first N results).
        # Paginate through all pages to ensure we find every match.
        if local_filter_keyword:
            params["limit"] = 1000
            schema_list: list = []
            offset = 0
            async with osdu.http_client(timeout=60) as client:
                while True:
                    params["offset"] = offset
                    r = await client.get(schema_url, headers=hdr, params=params)
                    r.raise_for_status()
                    data = r.json()
                    page = data.get("schemaInfos") or data.get("schemas") or []
                    if isinstance(data, list):
                        page = data
                    if not page:
                        break
                    schema_list.extend(page)
                    # Stop if we got fewer than requested (last page)
                    if len(page) < params["limit"]:
                        break
                    offset += len(page)
        else:
            async with osdu.http_client(timeout=60) as client:
                r = await client.get(schema_url, headers=hdr, params=params)
                r.raise_for_status()
                data = r.json()

            schema_list = data.get("schemaInfos") or data.get("schemas") or []
            if isinstance(data, list):
                schema_list = data

        # Apply local keyword filter if needed (substring match on entityType/kind)
        if local_filter_keyword:
            schema_list = [
                s for s in schema_list
                if local_filter_keyword in (
                    (s.get("schemaIdentity") or {}).get("entityType", "")
                ).lower()
            ]

        # Sort alphabetically by entityType
        schema_list.sort(
            key=lambda s: ((s.get("schemaIdentity") or {}).get("entityType", "")).lower()
        )

        table_rows = []
        for s in schema_list[:int(limit)]:
            identity = s.get("schemaIdentity") or {}
            table_rows.append({
                "authority": identity.get("authority", ""),
                "source": identity.get("source", ""),
                "entityType": identity.get("entityType", ""),
                "version": (
                    f"{identity.get('schemaVersionMajor', '')}"
                    f".{identity.get('schemaVersionMinor', '')}"
                    f".{identity.get('schemaVersionPatch', '')}"
                ),
                "status": s.get("status", ""),
                "scope": s.get("scope", ""),
                "kind": (
                    f"{identity.get('authority', '')}:"
                    f"{identity.get('source', '')}:"
                    f"{identity.get('entityType', '')}:"
                    f"{identity.get('schemaVersionMajor', '')}"
                    f".{identity.get('schemaVersionMinor', '')}"
                    f".{identity.get('schemaVersionPatch', '')}"
                ),
            })

        return templates.TemplateResponse(
            request, "search.html",
            {
                "search_mode": "schemas",
                "schema_results": table_rows,
                "schema_total": len(table_rows),
                "kind": "",
                "kinds_extra": "",
                "kind_options": _MANIFEST_KINDS,
                "refdata_kinds": _REFDATA_KINDS_LIST,
                "schema_q": query,
                "limit": limit,
            },
        )
    except httpx.HTTPStatusError as e:
        r = e.response
        from .common import sanitize_upstream_error
        return templates.TemplateResponse(
            request, "search.html",
            {
                "error": f"Schema search failed: {r.status_code} {r.reason_phrase}",
                "error_detail": sanitize_upstream_error(r),
                "search_mode": "schemas",
                "kind": "",
                "kinds_extra": "",
                "kind_options": _MANIFEST_KINDS,
                "refdata_kinds": _REFDATA_KINDS_LIST,
                "schema_q": query,
                "limit": limit,
            },
            status_code=r.status_code or 500,
        )
    except Exception as e:
        log.exception("[SCHEMA-SEARCH] Unexpected error: %s", e)
        return templates.TemplateResponse(
            request, "search.html",
            {
                "error": "Unexpected error searching schemas",
                "error_detail": str(e),
                "search_mode": "schemas",
                "kind": "",
                "kinds_extra": "",
                "kind_options": _MANIFEST_KINDS,
                "refdata_kinds": _REFDATA_KINDS_LIST,
                "schema_q": query,
                "limit": limit,
            },
            status_code=500,
        )


# ──────────────────────────────────────────────────────────────────────────────
# Reference Data search
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/search/refdata")
async def search_refdata_post(
    request: Request,
    kind: str = Form("osdu:wks:reference-data--*:*"),
    query: str = Form(""),
    limit: int = Form(50),
):
    """POST variant – redirect to GET (PRG pattern)."""
    from urllib.parse import urlencode
    params = urlencode({"kind": kind, "query": query, "limit": limit})
    return RedirectResponse(url=f"/search/refdata?{params}", status_code=303)


@router.get("/search/refdata", response_class=HTMLResponse)
async def search_refdata(
    request: Request,
    kind: str = "osdu:wks:reference-data--*:*",
    query: str = "",
    limit: int = 50,
):
    """Search for reference-data records in OSDU."""
    at = _access_token(request)
    search_url = f"https://{osdu.OSDU_BASE_URL}/api/search/v2/query"
    hdr = osdu.headers(at)
    search_kind = kind.strip() if kind.strip() else "osdu:wks:reference-data--*:*"

    # Require a specific kind OR a non-wildcard query to avoid huge result sets
    q = query.strip() if query else ""
    if search_kind == "osdu:wks:reference-data--*:*" and (not q or q == "*"):
        return templates.TemplateResponse(
            request, "search.html",
            {
                "error": "Please select a specific reference-data kind or provide a query filter. Listing all reference data is too large.",
                "search_mode": "refdata",
                "kind": search_kind,
                "kinds_extra": "",
                "kind_options": _MANIFEST_KINDS,
                "refdata_kinds": _REFDATA_KINDS_LIST,
                "refdata_q": query,
                "limit": limit,
            },
        )

    try:
        payload = {
            "kind": search_kind,
            "query": q if q else "*",
            "limit": min(int(limit), 500),
            "returnedFields": ["id", "kind", "version", "data.Name", "data.Code", "data.Description"],
            "trackTotalCount": True,
        }

        async with osdu.http_client(timeout=60) as client:
            r = await client.post(search_url, headers=hdr, json=payload)
            r.raise_for_status()
            res = r.json()

        total_count = int(res.get("totalCount") or 0)
        hits = res.get("results") or []

        table_rows = []
        for rec in hits:
            d = rec.get("data") or {}
            rec_kind = rec.get("kind") or ""
            entity_type = ""
            if "reference-data--" in rec_kind:
                entity_type = rec_kind.split("reference-data--")[1].split(":")[0]
            table_rows.append({
                "id": rec.get("id", ""),
                "kind": rec_kind,
                "entityType": entity_type,
                "name": d.get("Name", ""),
                "code": d.get("Code", ""),
                "description": d.get("Description", ""),
                "version": rec.get("version", ""),
            })

        # Sort alphabetically by name, then code
        table_rows.sort(key=lambda r: (r["name"].lower(), r["code"].lower()))

        return templates.TemplateResponse(
            request, "search.html",
            {
                "search_mode": "refdata",
                "refdata_results": table_rows,
                "refdata_total": total_count,
                "kind": search_kind,
                "kinds_extra": "",
                "kind_options": _MANIFEST_KINDS,
                "refdata_kinds": _REFDATA_KINDS_LIST,
                "refdata_q": query,
                "limit": limit,
            },
        )
    except httpx.HTTPStatusError as e:
        r = e.response
        from .common import sanitize_upstream_error
        return templates.TemplateResponse(
            request, "search.html",
            {
                "error": f"Reference data search failed: {r.status_code} {r.reason_phrase}",
                "error_detail": sanitize_upstream_error(r),
                "search_mode": "refdata",
                "kind": search_kind,
                "kinds_extra": "",
                "kind_options": _MANIFEST_KINDS,
                "refdata_kinds": _REFDATA_KINDS_LIST,
                "refdata_q": query,
                "limit": limit,
            },
            status_code=r.status_code or 500,
        )
    except Exception as e:
        log.exception("[REFDATA-SEARCH] Unexpected error: %s", e)
        return templates.TemplateResponse(
            request, "search.html",
            {
                "error": "Unexpected error searching reference data",
                "error_detail": str(e),
                "search_mode": "refdata",
                "kind": search_kind,
                "kinds_extra": "",
                "kind_options": _MANIFEST_KINDS,
                "refdata_kinds": _REFDATA_KINDS_LIST,
                "refdata_q": query,
                "limit": limit,
            },
            status_code=500,
        )


# ──────────────────────────────────────────────────────────────────────────────
# JSON API endpoints for inline detail rendering (schema & record)
# ──────────────────────────────────────────────────────────────────────────────

from fastapi.responses import JSONResponse


@router.get("/search/api/schema/{kind:path}")
async def api_schema_detail(request: Request, kind: str):
    """Return the full schema definition JSON for a given kind."""
    at = _access_token(request)
    schema_url = f"https://{osdu.OSDU_BASE_URL}/api/schema-service/v1/schema/{kind}"
    hdr = osdu.headers(at)
    try:
        async with osdu.http_client(timeout=60) as client:
            r = await client.get(schema_url, headers=hdr)
            r.raise_for_status()
            return JSONResponse(r.json())
    except httpx.HTTPStatusError as e:
        return JSONResponse(
            {"error": f"{e.response.status_code} {e.response.reason_phrase}"},
            status_code=e.response.status_code or 500,
        )
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/search/api/record/{record_id:path}")
async def api_record_detail(request: Request, record_id: str):
    """Return the full record JSON for a given record ID."""
    at = _access_token(request)
    storage_url = f"https://{osdu.OSDU_BASE_URL}/api/storage/v2/records/{record_id}"
    hdr = osdu.headers(at)
    try:
        async with osdu.http_client(timeout=60) as client:
            r = await client.get(storage_url, headers=hdr)
            r.raise_for_status()
            return JSONResponse(r.json())
    except httpx.HTTPStatusError as e:
        return JSONResponse(
            {"error": f"{e.response.status_code} {e.response.reason_phrase}"},
            status_code=e.response.status_code or 500,
        )
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/search/api/refdata-kinds")
async def api_refdata_kinds(request: Request):
    """Discover all reference-data kinds from the OSDU schema service.

    Returns a sorted list that the frontend can use to populate the kind picker.
    Falls back to the static list if the schema service is unavailable.
    """
    at = _access_token(request)
    schema_url = f"https://{osdu.OSDU_BASE_URL}/api/schema-service/v1/schema"
    hdr = osdu.headers(at)
    try:
        params = {"authority": "*", "source": "*", "entityType": "*", "limit": 1000}
        async with osdu.http_client(timeout=30) as client:
            r = await client.get(schema_url, headers=hdr, params=params)
            r.raise_for_status()
            data = r.json()

        schema_list = data.get("schemaInfos") or data.get("schemas") or []
        if isinstance(data, list):
            schema_list = data

        # Extract unique reference-data kinds
        refdata_kinds: set[str] = set()
        for s in schema_list:
            identity = s.get("schemaIdentity") or {}
            entity_type = identity.get("entityType", "")
            if entity_type.startswith("reference-data--"):
                kind_str = (
                    f"{identity.get('authority', 'osdu')}:"
                    f"{identity.get('source', 'wks')}:"
                    f"{entity_type}:"
                    f"{identity.get('schemaVersionMajor', '1')}"
                    f".{identity.get('schemaVersionMinor', '0')}"
                    f".{identity.get('schemaVersionPatch', '0')}"
                )
                refdata_kinds.add(kind_str)

        # Merge with static list
        static_kinds = {k["kind"] for k in _REFDATA_KINDS_LIST}
        all_kinds = sorted(refdata_kinds | static_kinds)
        return JSONResponse({"kinds": all_kinds})
    except Exception as e:
        # Fall back to static list
        log.warning("[REFDATA-KINDS] Schema service fetch failed: %s", e)
        return JSONResponse({"kinds": [k["kind"] for k in _REFDATA_KINDS_LIST]})


# ──────────────────────────────────────────────────────────────────────────────
# Provenance DAG — walk PriorDecisionID chains
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/search/api/provenance-dag/{record_id:path}")
async def provenance_dag(request: Request, record_id: str):
    """
    Walk PriorDecisionID chain from a BD record and return the full DAG.

    Returns JSON: {nodes: [{id, name, decision_level, date, status}], edges: [{from, to, label}]}
    Walks both backwards (PriorDecisionID) and forwards (search for BDs that reference this one).
    Max depth: 10.
    """
    at = _access_token(request)
    storage_url = f"https://{osdu.OSDU_BASE_URL}/api/storage/v2/records"
    search_url = f"https://{osdu.OSDU_BASE_URL}/api/search/v2/query"
    hdr = osdu.headers(at)

    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    visited: set[str] = set()

    def _node_from_record(rec: dict) -> dict:
        data = rec.get("data", {})
        # DecisionLevel: prefer plain field, else extract from DecisionLevelID ref-data ID
        dl = data.get("DecisionLevel", "")
        if not dl:
            dl_id = data.get("DecisionLevelID", "")
            if dl_id:
                # e.g. "dev:reference-data--DecisionLevel:DG2:" → "DG2"
                parts = dl_id.split(":")
                dl = parts[-2] if len(parts) >= 2 and parts[-2] else parts[-1]
        return {
            "id": rec.get("id", ""),
            "name": data.get("Name", ""),
            "decision_level": dl,
            "date": data.get("DecisionDate", data.get("DecisionDueDate", "")),
            "status": data.get("ApprovalStatus", ""),
        }

    def _extract_prior_bd(data: dict) -> str | None:
        """Extract prior BD ID from either top-level PriorDecisionID or Parameters[]."""
        # 1. Explicit field
        prior = data.get("PriorDecisionID", "")
        if prior:
            return prior
        # 2. Parameters[] with DataObjectParameter pointing to a BD record
        for param in data.get("Parameters") or []:
            obj = param.get("DataObjectParameter", "")
            if "master-data--BusinessDecision:" in obj:
                # Confirm it's a prior-gate reference (key or title hint)
                keys = param.get("Keys") or []
                title = (param.get("Title") or "").lower()
                if "prior" in title or "gate" in title or any(
                    (k.get("ParameterKey") or "").lower() == "gate" for k in keys
                ):
                    return obj
        return None

    async def _fetch(client, rid: str) -> dict | None:
        try:
            r = await client.get(f"{storage_url}/{rid}", headers=hdr)
            return r.json() if r.is_success else None
        except Exception:
            return None

    async def _walk_back(client, rid: str, depth: int = 0):
        """Walk backwards via PriorDecisionID or Parameters[] BD reference."""
        if depth > 10 or rid in visited:
            return
        visited.add(rid)
        rec = await _fetch(client, rid)
        if not rec:
            return
        nodes[rid] = _node_from_record(rec)
        prior = _extract_prior_bd(rec.get("data", {}))
        if prior:
            edges.append({"from": rid, "to": prior, "label": "supersedes"})
            await _walk_back(client, prior, depth + 1)

    async def _find_forward(client, rid: str):
        """Find BDs that reference this record as prior gate (PriorDecisionID or Parameters)."""
        # Search for explicit PriorDecisionID
        payload = {
            "kind": "osdu:wks:master-data--BusinessDecision:*",
            "query": f"data.PriorDecisionID:\"{rid}\"",
            "limit": 20,
            "returnedFields": ["id", "data.Name", "data.DecisionLevel",
                               "data.DecisionLevelID", "data.DecisionDate",
                               "data.DecisionDueDate", "data.ApprovalStatus",
                               "data.PriorDecisionID", "data.Parameters"],
        }
        try:
            r = await client.post(search_url, json=payload, headers=hdr)
            if r.is_success:
                for rec in r.json().get("results", []):
                    child_id = rec.get("id", "")
                    if child_id and child_id not in nodes:
                        nodes[child_id] = _node_from_record(rec)
                        prior = _extract_prior_bd(rec.get("data", {}))
                        if prior:
                            edges.append({"from": child_id, "to": prior, "label": "supersedes"})
        except Exception:
            pass
        # Search for Parameters[].DataObjectParameter reference
        payload2 = {
            "kind": "osdu:wks:master-data--BusinessDecision:*",
            "query": f"data.Parameters.DataObjectParameter:\"{rid}\"",
            "limit": 20,
            "returnedFields": ["id", "data.Name", "data.DecisionLevel",
                               "data.DecisionLevelID", "data.DecisionDate",
                               "data.DecisionDueDate", "data.ApprovalStatus",
                               "data.PriorDecisionID", "data.Parameters"],
        }
        try:
            r = await client.post(search_url, json=payload2, headers=hdr)
            if r.is_success:
                for rec in r.json().get("results", []):
                    child_id = rec.get("id", "")
                    if child_id and child_id not in nodes:
                        nodes[child_id] = _node_from_record(rec)
                        prior = _extract_prior_bd(rec.get("data", {}))
                        if prior:
                            edges.append({"from": child_id, "to": prior, "label": "supersedes"})
        except Exception:
            pass

    try:
        async with osdu.http_client(timeout=30) as client:
            await _walk_back(client, record_id)
            # Also find forward successors for all nodes in the chain
            for nid in list(nodes.keys()):
                await _find_forward(client, nid)
    except Exception as exc:
        log.warning("Provenance DAG error: %s", exc)

    return JSONResponse({
        "nodes": list(nodes.values()),
        "edges": edges,
        "root": record_id,
    })


# ──────────────────────────────────────────────────────────────────────────────
# View single record
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/search/view/{record_id}", response_class=HTMLResponse)
async def view_record(request: Request, record_id: str):
    """Fetch a single record by ID and render it through the search template."""
    at = _access_token(request)
    storage_url = f"https://{osdu.OSDU_BASE_URL}/api/storage/v2/records"
    search_url = f"https://{osdu.OSDU_BASE_URL}/api/search/v2/query"
    hdr = osdu.headers(at)

    try:
        async with osdu.http_client(timeout=60) as client:
            r = await client.get(f"{storage_url}/{record_id}", headers=hdr)
            r.raise_for_status()
            full = r.json()

            enriched = await _enrich_record(full, client, storage_url, search_url, hdr)

        return templates.TemplateResponse(
            request, "search.html",
            {
                "results": {"results": [enriched], "totalCount": 1},
                "kind": full.get("kind", ""),
                "kinds_extra": "",
                "kind_options": _MANIFEST_KINDS,
                "refdata_kinds": _REFDATA_KINDS_LIST,
                "q": record_id,
                "limit": 1,
            },
        )
    except HTTPStatusError as e:
        from .common import sanitize_upstream_error
        status = e.response.status_code or 500
        if status == 404:
            # Extract entity type from ID for a helpful message
            etype = record_id.split("--")[1].split(":")[0] if "--" in record_id else "Record"
            error_msg = f"{etype} not found"
            detail = (
                f"The record <code>{record_id}</code> is referenced "
                "but does not exist in this OSDU instance. "
                "It may not have been ingested yet."
            )
        else:
            error_msg = f"Record fetch failed: {status}"
            detail = sanitize_upstream_error(e.response)
        return templates.TemplateResponse(
            request, "search.html",
            {
                "error": error_msg,
                "error_detail": detail,
                "kind": "",
                "kinds_extra": "",
                "kind_options": _MANIFEST_KINDS,
                "refdata_kinds": _REFDATA_KINDS_LIST,
                "q": record_id,
                "limit": 1,
            },
            status_code=status,
        )
    except Exception as e:
        log.exception("[VIEW] Unexpected error: %s", e)
        return templates.TemplateResponse(
            request, "search.html",
            {
                "error": "Unexpected error",
                "error_detail": "See server logs",
                "kind": "",
                "kinds_extra": "",
                "kind_options": _MANIFEST_KINDS,
                "refdata_kinds": _REFDATA_KINDS_LIST,
                "q": record_id,
                "limit": 1,
            },
            status_code=500,
        )


# ──────────────────────────────────────────────────────────────────────────────
# Saved queries API
# ──────────────────────────────────────────────────────────────────────────────

def _user_ctx(request: Request) -> tuple[str, str]:
    """Return (oid, instance_name) from the session, or empty strings."""
    if not hasattr(request, "session"):
        return "", ""
    return request.session.get("oid", ""), request.session.get("instance_name", "")


@router.get("/api/queries")
async def api_list_queries(request: Request, source: str = ""):
    """List saved queries for the current user.  ?source=search|graphql."""
    oid, inst = _user_ctx(request)
    all_q = _ts_list_queries(oid, inst)
    if source == "search":
        return [q for q in all_q if q["kind"] != "__graphql__"]
    if source == "graphql":
        return [q for q in all_q if q["kind"] == "__graphql__"]
    return all_q


@router.post("/api/queries")
async def api_save_query(request: Request):
    """Save a search query. Body: {name, kind, query}."""
    oid, inst = _user_ctx(request)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)
    name = (body.get("name") or "").strip()
    kind = (body.get("kind") or "").strip()
    query = (body.get("query") or "*").strip()
    if not name:
        return JSONResponse({"error": "name is required"}, status_code=400)
    row_id = _ts_save_query(oid, inst, name, kind, query)
    if row_id is None:
        return JSONResponse({"error": "Failed to save"}, status_code=500)
    return {"id": row_id, "name": name, "kind": kind, "query": query}


@router.delete("/api/queries/{query_id}")
async def api_delete_query(request: Request, query_id: int):
    """Delete a saved query by id."""
    oid, _ = _user_ctx(request)
    ok = _ts_delete_query(query_id, oid=oid)
    if not ok:
        return JSONResponse({"error": "Failed to delete"}, status_code=500)
    return {"deleted": query_id}
