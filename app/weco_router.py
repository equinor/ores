"""
ORES ↔ WeCo integration router  (in-process)
==============================================

Direct in-process calls to the WeCo correlation engine.
WeCo is installed as a Python package (with compiled C++ engine)
inside the ORES container - no separate microservice needed.

WeCo remains a separate git repository; it is pip-installed into
the ORES Docker image at build time (via git submodule or wheel).

Usage in ORES main.py::

    from .weco_router import router as weco_router
    app.include_router(weco_router, prefix="/weco", tags=["weco"])
"""

from __future__ import annotations

import json
import os
import logging
import tempfile
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .tokenstore import (
    save_workflow as _ts_save_workflow,
    list_workflows as _ts_list_workflows,
    get_workflow as _ts_get_workflow,
    delete_workflow as _ts_delete_workflow,
)

log = logging.getLogger("ores.weco")

router = APIRouter()

# Session directory for WeCo temp files (well lists, results)
WECO_SESSION_DIR = os.getenv("WECO_SESSION_DIR", tempfile.mkdtemp(prefix="weco_"))
os.makedirs(WECO_SESSION_DIR, exist_ok=True)


# ═══════════════════════════════════════════════════════════════════════════
#  Request / Response models
# ═══════════════════════════════════════════════════════════════════════════

class WecoImportRequest(BaseModel):
    """Import wells from RDDMS into WeCo."""
    well_ids: Optional[List[str]] = None
    filter_name: Optional[str] = None
    dataspace: Optional[str] = None


class WecoRunRequest(BaseModel):
    """Run correlation on previously imported wells."""
    options: Dict[str, Any] = Field(default_factory=dict)
    n_best: int = Field(5, ge=1, le=100)
    well_names: Optional[List[str]] = None  # subset of wells to correlate


class WecoFullRequest(BaseModel):
    """Import + correlate + export in one call."""
    well_ids: Optional[List[str]] = None
    filter_name: Optional[str] = None
    dataspace: Optional[str] = None
    options: Dict[str, Any] = Field(default_factory=dict)
    n_best: int = Field(5, ge=1, le=100)
    export_markers: bool = True


class WecoStatusResponse(BaseModel):
    """WeCo engine health."""
    connected: bool
    version: str = ""
    engine: bool = False


# ═══════════════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════════════

def _get_token(request: Request) -> str:
    """Extract access token from the ORES request state."""
    token = getattr(request.state, "access_token", None)
    if not token:
        token = os.environ.get("OSDU_TOKEN", "")
    return token or ""


def _session_well_file() -> str:
    """Path to the session well list file."""
    return os.path.join(WECO_SESSION_DIR, "wells.txt")


# Cached well list and result file (server process memory - single worker)
_cached_well_list = None
_cached_res_file = None

# R3: Result cache - avoids re-running if same wells+options
_result_cache = {}  # key: (wells_hash, options_hash) → response dict
_RESULT_CACHE_MAX = 5


def _cache_key(wl, options: dict) -> str:
    """Compute a deterministic key from wells + options."""
    import hashlib
    well_sig = "|".join(f"{w.name}:{w.size}" for w in wl.wells)
    opts_sig = "&".join(f"{k}={v}" for k, v in sorted(options.items()) if v)
    return hashlib.md5(f"{well_sig}#{opts_sig}".encode()).hexdigest()


# ═══════════════════════════════════════════════════════════════════════════
#  RDDMS → WeCo Well conversion (uses ORES native osdu.py, no gocad)
# ═══════════════════════════════════════════════════════════════════════════

import re as _re
import urllib.parse
import uuid as uuid_mod
import numpy as np

# WeCo-specific default dataspace (falls back to global DEFAULT_DATASPACE)
WECO_DEFAULT_DATASPACE = os.environ.get(
    "WECO_DEFAULT_DATASPACE",
    os.environ.get("DEFAULT_DATASPACE", "maap/weco")
)

# Deterministic UUID namespace - must match demo/ingest_weco_demos.py
_WECO_NS = uuid_mod.UUID("a3f8c1e0-7b2d-4e5f-9a1c-6d8e0f2b4a7c")


def _demo_uuid(demo_key: str, well_name: str, suffix: str = "") -> str:
    """Deterministic UUID5 for a demo object (same as ingestion script)."""
    seed = f"{demo_key}/{well_name}"
    if suffix:
        seed += f"/{suffix}"
    return str(uuid_mod.uuid5(_WECO_NS, seed))


def _uuid_from_uri(uri: str) -> str:
    """Extract UUID from an EML resource URI.

    'eml:///dataspace('x')/resqml20.obj_Foo(uuid-here)' → 'uuid-here'
    """
    m = _re.search(r"\(([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\)", uri)
    return m.group(1) if m else ""


def _normalize_summaries(summaries: list) -> list:
    """Normalize RDDMS resource summaries to have 'uuid' and 'title' keys.

    list_resources returns: {uri, name, lastChanged, ...}
    We add: uuid (parsed from uri), title (from name field).
    """
    for s in summaries:
        if "uuid" not in s and "Uuid" not in s and "UUID" not in s:
            s["uuid"] = _uuid_from_uri(s.get("uri", ""))
        if "title" not in s:
            s["title"] = s.get("name", "")
    return summaries


def _get_uuid(res: dict) -> str:
    """Get UUID from a resource (works for both summaries and full objects)."""
    return (res.get("uuid") or res.get("Uuid") or res.get("UUID")
            or _uuid_from_uri(res.get("uri", "")))


def _get_title(res: dict) -> str:
    """Get title from a resource (works for both summaries and full objects)."""
    return (res.get("title") or res.get("name")
            or (res.get("Citation") or {}).get("Title") or "")


def _arr_path(arr_meta: dict) -> str:
    """Extract pathInResource from an array metadata entry.

    list_arrays returns: {uid: {uri, pathInResource}, dimensions, ...}
    """
    uid = arr_meta.get("uid") or {}
    if isinstance(uid, dict):
        return uid.get("pathInResource", "")
    return arr_meta.get("PathInResource") or arr_meta.get("path") or ""


def _arr_values(arr_data: dict) -> list:
    """Extract flat values from a read_array response.

    read_array returns: {uid: {...}, data: {data: [values...]}}
    """
    # New format: {data: {data: [...]}}
    data_wrapper = arr_data.get("data")
    if isinstance(data_wrapper, dict):
        vals = data_wrapper.get("data")
        if vals is not None:
            return vals
    # Fallback: direct keys
    return arr_data.get("values") or arr_data.get("Values") or []


async def _rddms_import_wells(token: str, dataspace: str):
    """Fetch wells from RDDMS using ORES's own osdu client → WeCo WellList.

    Flow:
    1. List WellboreTrajectoryRepresentation → geometry (MD, XYZ)
    2. List WellboreFrameRepresentation → log frames (MD sample grid)
    3. List ContinuousProperty → log data (GR, RT, DEN, etc.)
    4. List DiscreteProperty → regions (facies, seam, biozone)
    5. Build WeCo Well objects with all data/regions
    """
    from . import osdu
    from weco.data import Well, WellList

    ds_enc = urllib.parse.quote(dataspace, safe="")

    # RESQML object types
    TRAJ_TYPE = "resqml20.obj_WellboreTrajectoryRepresentation"
    FRAME_TYPE = "resqml20.obj_WellboreFrameRepresentation"
    CONT_PROP_TYPE = "resqml20.obj_ContinuousProperty"
    DISC_PROP_TYPE = "resqml20.obj_DiscreteProperty"

    # Step 1: list trajectories (defines well geometry)
    trajectories = _normalize_summaries(await osdu.list_resources(token, ds_enc, TRAJ_TYPE))
    if not trajectories:
        raise HTTPException(404, f"No wells found in dataspace '{dataspace}'")

    # Step 2: list frames & properties (will be matched to wells by reference)
    frames = _normalize_summaries(await osdu.list_resources(token, ds_enc, FRAME_TYPE))
    cont_props = _normalize_summaries(await osdu.list_resources(token, ds_enc, CONT_PROP_TYPE))
    disc_props = _normalize_summaries(await osdu.list_resources(token, ds_enc, DISC_PROP_TYPE))

    # Build lookup: trajectory UUID → frame UUIDs
    # Match by title convention: frame "Well_01_Logs" → traj "Well_01"
    traj_to_frames: dict = {}
    frame_by_uuid: dict = {}
    for fr in frames:
        fr_uuid = _get_uuid(fr)
        frame_by_uuid[fr_uuid] = fr
        # Try explicit parent ref (only available in full objects)
        parent_ref = _extract_parent_uuid(fr)
        if parent_ref:
            traj_to_frames.setdefault(parent_ref, []).append(fr_uuid)

    # Build lookup: frame UUID → property UUIDs
    frame_to_cont: dict = {}
    frame_to_disc: dict = {}
    for prop in cont_props:
        p_uuid = _get_uuid(prop)
        parent = _extract_parent_uuid(prop)
        if parent:
            frame_to_cont.setdefault(parent, []).append((p_uuid, prop))
    for prop in disc_props:
        p_uuid = _get_uuid(prop)
        parent = _extract_parent_uuid(prop)
        if parent:
            frame_to_disc.setdefault(parent, []).append((p_uuid, prop))

    # Always use title-matching for summaries (they don't have parent refs)
    _match_by_title(trajectories, frames, traj_to_frames, frame_by_uuid)
    _match_props_by_title(frames, cont_props, disc_props, frame_to_cont, frame_to_disc)

    wells = []
    for res in trajectories:
        traj_uuid = _get_uuid(res)
        name = _get_title(res) or traj_uuid[:8]

        try:
            # Read trajectory arrays (geometry)
            arrays_meta = await osdu.list_arrays(token, ds_enc, TRAJ_TYPE, traj_uuid)

            points = None
            mds = None
            for arr in arrays_meta:
                path = _arr_path(arr)
                # Check MD/parameters first (more specific match)
                if "controlPointParameters" in path or "MdValues" in path or "mdValues" in path:
                    arr_data = await osdu.read_array(
                        token, ds_enc, TRAJ_TYPE, traj_uuid, path_in_resource=path)
                    values = _arr_values(arr_data)
                    if values:
                        mds = np.array(values, dtype=np.float64)
                elif "controlPoints" in path or "ControlPoints" in path or "Geometry" in path:
                    arr_data = await osdu.read_array(
                        token, ds_enc, TRAJ_TYPE, traj_uuid, path_in_resource=path)
                    values = _arr_values(arr_data)
                    if values:
                        points = np.array(values, dtype=np.float64).reshape(-1, 3)

            # Build Well geometry
            w = Well()
            w.name = name
            w.meta["uuid"] = traj_uuid
            w.meta["dataspace"] = dataspace

            if points is not None and len(points) > 0:
                w.size = len(points)
                w.x = float(points[0, 0])
                w.y = float(points[0, 1])
                w.z = float(points[0, 2])
                diffs = np.diff(points, axis=0)
                w.h = float(np.sum(np.sqrt(np.sum(diffs ** 2, axis=1))))
                w.data["X"] = list(points[:, 0])
                w.data["Y"] = list(points[:, 1])
                w.data["Z"] = list(points[:, 2])
            elif mds is not None and len(mds) > 0:
                w.size = len(mds)
                w.x = w.y = w.z = w.h = 0.0
            else:
                log.warning(f"Well '{name}' has no geometry, skipping")
                continue

            if mds is not None:
                w.data["Depth"] = list(mds[:w.size])
            elif points is not None:
                diffs = np.diff(points, axis=0)
                segs = np.sqrt(np.sum(diffs ** 2, axis=1))
                w.data["Depth"] = list(np.concatenate([[0.0], np.cumsum(segs)]))

            # Step 3: Read log data (ContinuousProperty) from associated frames
            frame_uuids = traj_to_frames.get(traj_uuid, [])
            for fr_uuid in frame_uuids:
                # Read frame MD values (the sample grid for properties)
                frame_mds = await _read_frame_mds(token, ds_enc, FRAME_TYPE, fr_uuid)

                # Read continuous properties (log curves)
                for p_uuid, prop_meta in frame_to_cont.get(fr_uuid, []):
                    prop_name = _get_title(prop_meta) or p_uuid[:8]
                    # Strip well name prefix: "Well_01_GR" → "GR"
                    if '_' in prop_name and prop_name.startswith(name):
                        prop_name = prop_name[len(name)+1:]
                    try:
                        p_arrays = await osdu.list_arrays(
                            token, ds_enc, CONT_PROP_TYPE, p_uuid)
                        for pa in p_arrays:
                            pa_path = _arr_path(pa)
                            if "values" in pa_path.lower() or "patch" in pa_path.lower():
                                arr_data = await osdu.read_array(
                                    token, ds_enc, CONT_PROP_TYPE, p_uuid,
                                    path_in_resource=pa_path)
                                vals = _arr_values(arr_data)
                                if vals:
                                    log_vals = _resample_to_well(
                                        vals, frame_mds, w.size, w.data.get("Depth"))
                                    w.data[prop_name] = log_vals
                                    break
                    except Exception as e:
                        log.debug(f"  Skip property '{prop_name}' for '{name}': {e}")

                # Read discrete properties (regions)
                for p_uuid, prop_meta in frame_to_disc.get(fr_uuid, []):
                    prop_name = _get_title(prop_meta) or p_uuid[:8]
                    if '_' in prop_name and prop_name.startswith(name):
                        prop_name = prop_name[len(name)+1:]
                    try:
                        p_arrays = await osdu.list_arrays(
                            token, ds_enc, DISC_PROP_TYPE, p_uuid)
                        for pa in p_arrays:
                            pa_path = _arr_path(pa)
                            if "values" in pa_path.lower() or "patch" in pa_path.lower():
                                arr_data = await osdu.read_array(
                                    token, ds_enc, DISC_PROP_TYPE, p_uuid,
                                    path_in_resource=pa_path)
                                vals = _arr_values(arr_data)
                                if vals:
                                    regions = _discrete_to_regions(
                                        vals, frame_mds, w.size, w.data.get("Depth"))
                                    if regions:
                                        w.region[prop_name] = tuple(regions)
                                    break
                    except Exception as e:
                        log.debug(f"  Skip region '{prop_name}' for '{name}': {e}")

            wells.append(w)
            data_names = [k for k in w.data if k not in ("X", "Y", "Z", "Depth")]
            log.info(f"  Imported well '{name}': {w.size} pts, "
                     f"{len(data_names)} logs, {len(w.region)} regions")

        except Exception as e:
            log.warning(f"  Skipping well '{name}': {e}")
            continue

    if not wells:
        raise HTTPException(404, "No valid wells could be imported")

    # Build WellList
    wl = WellList.__new__(WellList)
    wl.wells = wells
    log.info(f"Imported {len(wells)} wells from RDDMS '{dataspace}'")
    return wl


def _extract_parent_uuid(resource: dict) -> str:
    """Extract parent object UUID from RESQML resource references."""
    # Check common RESQML reference patterns
    for key in ("SupportingRepresentation", "RepresentedInterpretation",
                "Representation", "Frame"):
        ref = resource.get(key)
        if isinstance(ref, dict):
            uid = ref.get("UUID") or ref.get("Uuid") or ref.get("uuid")
            if uid:
                return uid
    # Check nested Citation or References
    refs = resource.get("References") or resource.get("DataObjectReference") or []
    if isinstance(refs, list):
        for r in refs:
            if isinstance(r, dict):
                uid = r.get("UUID") or r.get("Uuid")
                if uid:
                    return uid
    return ""


def _match_by_title(trajectories, frames, traj_to_frames, frame_by_uuid):
    """Fallback: match frames to trajectories by title prefix.

    Frame title "Well_01_Logs" matches traj title "Well_01".
    """
    traj_names = {}
    for t in trajectories:
        uid = _get_uuid(t)
        title = _get_title(t)
        if title and uid:
            # Use full title as key (lowered) for matching
            traj_names[title.lower()] = uid

    for fr in frames:
        fr_uuid = _get_uuid(fr)
        if not fr_uuid or fr_uuid in [u for uuids in traj_to_frames.values() for u in uuids]:
            continue  # already matched
        fr_title = _get_title(fr)
        if not fr_title:
            continue
        # Strip common suffixes: "_Logs", "_Frame", " frame", etc.
        base = _re.sub(r'[_\s](?:Logs|Frame|frame|logs)$', '', fr_title).lower()
        if base in traj_names:
            traj_to_frames.setdefault(traj_names[base], []).append(fr_uuid)


def _match_props_by_title(frames, cont_props, disc_props, frame_to_cont, frame_to_disc):
    """Fallback: match properties to frames by title prefix.

    Property title "Well_01_GR" matches frame title "Well_01_Logs" via common prefix "Well_01".
    """
    frame_names = {}
    for fr in frames:
        uid = _get_uuid(fr)
        title = _get_title(fr)
        if title and uid:
            # Strip "_Logs" suffix to get well name
            base = _re.sub(r'[_\s](?:Logs|Frame|frame|logs)$', '', title).lower()
            frame_names[base] = uid

    for prop in cont_props:
        p_uuid = _get_uuid(prop)
        if not p_uuid:
            continue
        title = _get_title(prop)
        if not title:
            continue
        # Property title "Well_01_GR" → prefix "well_01"
        parts = title.rsplit('_', 1)
        prefix = parts[0].lower() if len(parts) > 1 else title.lower()
        if prefix in frame_names:
            frame_to_cont.setdefault(frame_names[prefix], []).append((p_uuid, prop))

    for prop in disc_props:
        p_uuid = _get_uuid(prop)
        if not p_uuid:
            continue
        title = _get_title(prop)
        if not title:
            continue
        parts = title.rsplit('_', 1)
        prefix = parts[0].lower() if len(parts) > 1 else title.lower()
        if prefix in frame_names:
            frame_to_disc.setdefault(frame_names[prefix], []).append((p_uuid, prop))


async def _read_frame_mds(token: str, ds_enc: str, frame_type: str, frame_uuid: str):
    """Read MD values from a WellboreFrameRepresentation."""
    from . import osdu
    try:
        arrays = await osdu.list_arrays(token, ds_enc, frame_type, frame_uuid)
        for arr in arrays:
            path = _arr_path(arr)
            if "nodeMd" in path or "NodeMd" in path or "MdValues" in path or "md" in path.lower():
                arr_data = await osdu.read_array(
                    token, ds_enc, frame_type, frame_uuid, path_in_resource=path)
                vals = _arr_values(arr_data)
                if vals:
                    return np.array(vals, dtype=np.float64)
    except Exception:
        pass
    return None


def _resample_to_well(values, frame_mds, well_size: int, well_depth) -> list:
    """Resample property values to the well's depth grid.

    If frame has same size as well, use directly. Otherwise interpolate.
    """
    vals = np.array(values, dtype=np.float64)
    if len(vals) == well_size:
        return list(vals)

    # Need interpolation
    if frame_mds is not None and well_depth is not None:
        well_md = np.array(well_depth, dtype=np.float64)
        # Interpolate property onto well depth grid
        resampled = np.interp(well_md, frame_mds[:len(vals)], vals,
                              left=vals[0], right=vals[-1])
        return list(resampled)

    # Fallback: truncate or pad
    if len(vals) > well_size:
        return list(vals[:well_size])
    padded = np.full(well_size, vals[-1] if len(vals) > 0 else 0.0)
    padded[:len(vals)] = vals
    return list(padded)


def _discrete_to_regions(values, frame_mds, well_size: int, well_depth) -> list:
    """Convert discrete property array to WeCo region format.

    WeCo regions are tuples of (start_idx, end_idx, value).
    """
    # Resample to well grid first
    vals = np.array(values, dtype=np.int32)
    if len(vals) != well_size:
        if frame_mds is not None and well_depth is not None:
            well_md = np.array(well_depth, dtype=np.float64)
            # Nearest-neighbor interpolation for discrete values
            indices = np.searchsorted(frame_mds[:len(vals)], well_md, side="right") - 1
            indices = np.clip(indices, 0, len(vals) - 1)
            vals = vals[indices]
        elif len(vals) > well_size:
            vals = vals[:well_size]
        else:
            padded = np.full(well_size, vals[-1] if len(vals) > 0 else 0, dtype=np.int32)
            padded[:len(vals)] = vals
            vals = padded

    # Run-length encode into (start, end, value) tuples
    regions = []
    if len(vals) == 0:
        return regions
    start = 0
    current = int(vals[0])
    for i in range(1, len(vals)):
        if int(vals[i]) != current:
            regions.append((start, i - 1, current))
            start = i
            current = int(vals[i])
    regions.append((start, len(vals) - 1, current))
    return regions


# ═══════════════════════════════════════════════════════════════════════════
#  Page route
# ═══════════════════════════════════════════════════════════════════════════

from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

_templates = Jinja2Templates(
    directory=os.path.join(os.path.dirname(__file__), "templates")
)


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def weco_page(request: Request):
    """Serve the WeCo correlation web UI."""
    dataspace = WECO_DEFAULT_DATASPACE
    return _templates.TemplateResponse(request, "weco.html", {
        "dataspace": dataspace,
    })


# ═══════════════════════════════════════════════════════════════════════════
#  API Endpoints
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/health", response_model=WecoStatusResponse)
def weco_health():
    """Check if WeCo correlation engine is available (in-process)."""
    try:
        from importlib.metadata import version as pkg_version
        from weco.ext import ProjectExt
        # Quick sanity: can we instantiate the engine?
        _p = ProjectExt()
        return WecoStatusResponse(connected=True, version=pkg_version("weco"), engine=True)
    except Exception as e:
        log.warning(f"WeCo engine not available: {e}")
        return WecoStatusResponse(connected=False)


@router.post("/import")
async def weco_import(req: WecoImportRequest, request: Request):
    """Import wells from the active RDDMS instance into WeCo.

    Uses ORES's native osdu.py RDDMS client (no gocad/resqml dependency).
    """
    global _cached_well_list

    token = _get_token(request)
    if not token:
        raise HTTPException(401, "No access token. Log in to OSDU first.")

    dataspace = req.dataspace or WECO_DEFAULT_DATASPACE

    try:
        wl = await _rddms_import_wells(token, dataspace)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"RDDMS import failed: {e}")

    _cached_well_list = wl

    # Collect metadata
    all_meta = {}
    for w in wl.wells:
        if hasattr(w, "meta") and w.meta:
            all_meta[w.name] = w.meta

    return {
        "well_count": len(wl.wells),
        "well_names": [w.name for w in wl.wells],
        "data_names": list(wl.get_data_names()) if hasattr(wl, "get_data_names") else [],
        "region_names": list(wl.get_region_names()) if hasattr(wl, "get_region_names") else [],
        "meta": all_meta if all_meta else None,
    }


@router.post("/suggest-defaults")
def weco_suggest_defaults(request: Request):
    """Get auto-suggested parameters based on imported wells."""
    global _cached_well_list

    if _cached_well_list is None:
        return {"options": {}, "reasoning": {"note": "Import wells first"}}

    try:
        from weco.api import _suggest_defaults_for_wells
        options, reasoning = _suggest_defaults_for_wells(_cached_well_list)
        return {"options": options, "reasoning": reasoning}
    except Exception as e:
        log.warning(f"Suggest defaults failed: {e}")
        return {"options": {}, "reasoning": {"error": str(e)}}


@router.post("/suggest-preprocessing")
def weco_suggest_preprocessing(request: Request):
    """AI-driven preprocessing recommendation based on loaded wells."""
    global _cached_well_list

    if _cached_well_list is None:
        return {"steps": {}, "environment": "unknown", "parameters": {}}

    try:
        from weco.decision_tree import recommend_preprocessing
        rec = recommend_preprocessing(_cached_well_list)
        return {
            "environment": rec.environment,
            "steps": {
                "normalise": rec.normalise,
                "vshale": rec.vshale,
                "stacking_pattern": rec.stacking_pattern,
                "electrofacies": rec.electrofacies,
                "smooth": rec.smooth,
                "log_qc": rec.log_qc,
                "ai_facies": rec.ai_facies,
            },
            "parameters": {
                "smooth_window": rec.smooth_window,
                "electrofacies_k": rec.electrofacies_k,
            },
            "reasoning": rec.reasoning,
        }
    except Exception as e:
        log.warning(f"Suggest preprocessing failed: {e}")
        return {"steps": {}, "environment": "unknown", "parameters": {},
                "reasoning": {"error": str(e)}}


@router.post("/preprocess")
async def weco_preprocess(request: Request):
    """Apply preprocessing steps to loaded wells.

    Body: { "steps": ["resample", "normalise", ...], "resample_interval": 1.0 }
    """
    global _cached_well_list

    if _cached_well_list is None:
        raise HTTPException(400, "No wells loaded. Call /weco/import first.")

    body = await request.json()
    steps = body.get("steps", [])
    resample_interval = body.get("resample_interval", 1.0)

    try:
        from weco.preprocessing import auto_preprocess
        result = auto_preprocess(
            _cached_well_list,
            steps=steps,
            resample_interval=resample_interval,
        )
        wells_plot_data = _build_wells_plot_data(_cached_well_list)
        # Detect new logs created by preprocessing
        new_logs = []
        if _cached_well_list.wells:
            w0 = _cached_well_list.wells[0]
            all_logs = list(w0.data.keys()) if hasattr(w0, 'data') else []
            known_derived = ['VSHALE', 'STACK', 'EFACIES', 'AI_FACIES',
                             'ANOMALY', 'GR_smooth', 'GR_norm']
            new_logs = [l for l in all_logs if any(d in l for d in known_derived)]
        return {
            "status": "ok",
            "well_count": len(_cached_well_list.wells),
            "applied": result.get("applied", result.get("steps_applied", steps)),
            "new_logs": new_logs,
            "wells_plot_data": wells_plot_data,
        }
    except Exception as e:
        log.warning(f"Preprocess failed: {e}")
        raise HTTPException(500, f"Preprocessing failed: {e}")


@router.get("/facies-dict/{region_name}")
def weco_facies_dict(region_name: str):
    """Get auto-detected facies dictionary for a region channel.

    Returns zone→colour/label mappings based on values observed in the
    loaded wells. Uses standard lithology code tables for auto-detection.
    """
    global _cached_well_list

    if _cached_well_list is None:
        raise HTTPException(400, "No wells loaded. Call /weco/import first.")

    try:
        from weco.facies_dict import FaciesDictionary
        fd = FaciesDictionary.from_region_auto(region_name, _cached_well_list.wells)
        return {
            "region_name": fd.region_name,
            "entries": {
                str(zid): {
                    "name": e.name,
                    "color": e.color,
                    "lithology": e.lithology,
                }
                for zid, e in fd.entries.items()
            },
        }
    except Exception as e:
        raise HTTPException(500, f"Facies dict error: {e}")


# Cached strat column (loaded from JSON or OSDU)
_cached_strat_column = None


@router.post("/strat-column")
def weco_load_strat_column(payload: dict):
    """Load a stratigraphic column from JSON for rendering alongside wells.

    Expected payload: {"name": "...", "ranks": [...], "horizons": [...]}
    See StratColumn.from_dict() for format details.
    """
    global _cached_strat_column
    try:
        from weco.strat_column import StratColumn
        col = StratColumn.from_dict(payload)
        _cached_strat_column = col
        # Return serialised for confirmation
        units_count = sum(len(r.units) for r in col.ranks)
        return {
            "status": "ok",
            "name": col.name,
            "n_ranks": len(col.ranks),
            "n_units": units_count,
            "n_horizons": len(col.horizons),
        }
    except Exception as e:
        raise HTTPException(400, f"Invalid strat column: {e}")


@router.get("/strat-column")
def weco_get_strat_column():
    """Get the currently loaded strat column for plot rendering.

    Returns units with colours and age ranges for canvas drawing.
    """
    global _cached_strat_column
    if _cached_strat_column is None:
        return {"loaded": False}

    col = _cached_strat_column
    ranks_data = []
    for rank in col.ranks:
        units_data = []
        for u in rank.units:
            units_data.append({
                "name": u.name,
                "color": u.color_html or "#CCCCCC",
                "top_age_ma": u.top_age_ma,
                "base_age_ma": u.base_age_ma,
                "environment": u.depositional_environment,
            })
        ranks_data.append({
            "name": rank.name,
            "kind": rank.kind,
            "units": units_data,
        })
    return {
        "loaded": True,
        "name": col.name,
        "ranks": ranks_data,
        "horizons": [{"name": h.name, "age_ma": h.age_ma} for h in col.horizons],
    }


@router.post("/strat-column/import")
async def weco_import_strat_column(request: Request):
    """Import a lithostratigraphic column from OSDU/RDDMS.

    Queries for StratigraphicColumn or LocalStratigraphicColumn resources
    in the specified (or default) dataspace and builds a StratColumn.

    Body (optional): {"dataspace": "some/dataspace"}
    """
    global _cached_strat_column

    token = _get_token(request)
    if not token:
        raise HTTPException(401, "No access token. Log in to OSDU first.")

    # Accept dataspace from request body, fall back to default
    try:
        body = await request.json()
    except Exception:
        body = {}
    dataspace = body.get("dataspace") or WECO_DEFAULT_DATASPACE
    ds_enc = dataspace.replace("/", "%2F")

    try:
        from . import osdu
        from weco.strat_column import StratColumn, StratRank, StratUnit

        # Try RESQML StratigraphicColumn type first
        STRAT_TYPES = [
            "resqml20.obj.StratigraphicColumn",
            "resqml20.obj.StratigraphicColumnRankInterpretation",
        ]

        all_units = []
        for stype in STRAT_TYPES:
            try:
                resources = await osdu.list_resources(token, ds_enc, stype)
                for res in resources:
                    data = res.get("data", res)
                    name = data.get("Name", data.get("Citation", {}).get("Title", ""))
                    age_top = data.get("OlderAge") or data.get("TopAge")
                    age_base = data.get("YoungerAge") or data.get("BaseAge")
                    color = data.get("ColorCode")
                    env = data.get("DepositionEnvironment") or data.get("GeologicUnitComposition")
                    all_units.append(StratUnit(
                        name=name or "Unknown",
                        top_age_ma=float(age_top) if age_top else None,
                        base_age_ma=float(age_base) if age_base else None,
                        color_html=color,
                        depositional_environment=env,
                    ))
            except Exception:
                continue

        if not all_units:
            return {"status": "empty", "message": "No stratigraphic column data found in RDDMS"}

        # Build column
        rank = StratRank(name="Lithostratigraphy", kind="litho", units=all_units)
        col = StratColumn(name=f"OSDU ({dataspace})", ranks=[rank])
        _cached_strat_column = col

        return {
            "status": "ok",
            "name": col.name,
            "n_units": len(all_units),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Strat column import error: {e}")


@router.get("/strat-column/list")
async def weco_list_strat_columns(request: Request, dataspace: str = ""):
    """List available stratigraphic columns in a dataspace.

    Returns a lightweight list of column IDs and names for the picker UI.
    Uses the OSDU Search API to find StratigraphicColumn resources.
    """
    token = _get_token(request)
    if not token:
        raise HTTPException(401, "No access token.")

    ds = dataspace or WECO_DEFAULT_DATASPACE

    try:
        from . import osdu
        search_url = f"https://{osdu.OSDU_BASE_URL}/api/search/v2/query"
        hdr = osdu.headers(token)

        kinds = [
            "resqml20.obj.StratigraphicColumn",
            "resqml20.obj.LocalStratigraphicColumn",
        ]
        columns = []

        async with osdu.http_client(timeout=30) as client:
            for kind in kinds:
                payload = {
                    "kind": f"*:*:{kind}:*",
                    "query": f'data.DataspaceID:"{ds}"' if ds else "*",
                    "limit": 50,
                    "returnedFields": ["id", "data.Name", "data.Citation.Title",
                                       "data.Description", "kind"],
                }
                r = await client.post(search_url, headers=hdr, json=payload)
                if r.status_code != 200:
                    continue
                for rec in (r.json() or {}).get("results", []):
                    rd = rec.get("data", {})
                    name = rd.get("Name") or rd.get("Citation", {}).get("Title") or rec.get("id", "")
                    columns.append({
                        "id": rec.get("id"),
                        "name": name,
                        "kind": rec.get("kind", ""),
                        "description": rd.get("Description", ""),
                    })

        return {"status": "ok", "dataspace": ds, "columns": columns}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"List strat columns error: {e}")


@router.get("/wheeler/{result_idx}")
def weco_wheeler(result_idx: int):
    """Get Wheeler-style gap analysis for a correlation result.

    Returns per-well gap/presence data for rendering a stratigraphic
    gap diagram (which units are missing where).
    """
    global _cached_well_list, _cached_res_file

    if _cached_well_list is None or _cached_res_file is None:
        raise HTTPException(400, "No results available. Run correlation first.")

    try:
        from weco.api import _extract_results, _wheeler_gap_analysis

        results = _extract_results(_cached_res_file, None, result_idx + 1)
        if result_idx >= len(results):
            raise HTTPException(404, f"Result #{result_idx} not found")

        result = results[result_idx]
        well_names = [w.name for w in _cached_well_list.wells]
        analysis = _wheeler_gap_analysis(result, well_names)

        # Include strat column if loaded
        strat_info = None
        if _cached_strat_column:
            units = []
            for rank in _cached_strat_column.ranks:
                for u in rank.units:
                    units.append({
                        "name": u.name,
                        "top_age_ma": u.top_age_ma,
                        "base_age_ma": u.base_age_ma,
                        "color": u.color_html or "#ccc",
                        "environment": u.depositional_environment,
                        "rank": rank.name,
                    })
            strat_info = {
                "name": _cached_strat_column.name,
                "units": units,
                "horizons": [{"name": h.name, "age_ma": h.age_ma}
                             for h in _cached_strat_column.horizons],
            }

        return {
            "result_idx": result_idx,
            "cost": result.cost,
            **analysis,
            "strat_column": strat_info,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Wheeler analysis error: {e}")


def _apply_memory_guards(options: dict, n_wells: int) -> dict:
    """Enforce safe parameter limits to prevent OOM on Radix (2Gi container).

    max-cor (path length) must be >= well depth to get full correlation.
    nbr-cor (number of results) is the main memory driver - scale by well count.
    """
    opts = dict(options)
    # Force single-thread to limit peak memory (one correlator buffer at a time)
    opts.setdefault("thread", 1)
    # Scale nbr-cor (result count) by dataset size - this is the memory driver
    if n_wells > 50:
        opts["nbr-cor"] = min(int(opts.get("nbr-cor", 3)), 5)
        # Only add band-width as perf optimization for very large datasets
        opts.setdefault("band-width", 30)
    elif n_wells > 10:
        opts["nbr-cor"] = min(int(opts.get("nbr-cor", 5)), 10)
    else:
        opts["nbr-cor"] = min(int(opts.get("nbr-cor", 20)), 30)
    # max-cor (path length) - must cover the full well depth; cap at 200
    opts["max-cor"] = min(int(opts.get("max-cor", 80)), 200)
    return opts


def _build_wells_plot_data(wl) -> list:
    """Build rich plot data including all logs and region bands for visualization."""
    _SKIP = {"Depth", "DEPTH", "X", "Y", "Z", "MD", "TVD", "TVDSS"}
    wells_plot_data = []
    for w in wl.wells:
        depth = list(w.data.get("Depth", w.data.get("DEPTH", range(w.size))))[:w.size]
        # All log channels (up to 5)
        logs = {}
        for k, v in w.data.items():
            if k not in _SKIP and len(logs) < 5:
                logs[k] = list(v)[:w.size]
        # First log for backward-compat "log_values" field
        log_values = list(logs.values())[0] if logs else None
        # Region/zone data - expand RLE (value, start, count) to per-sample
        regions = {}
        if hasattr(w, 'region') and w.region:
            for rname, rvals in w.region.items():
                expanded = [None] * w.size
                for entry in rvals:
                    if isinstance(entry, (list, tuple)) and len(entry) >= 3:
                        val, start, count = entry[0], entry[1], entry[2]
                        for s in range(start, min(start + count, w.size)):
                            expanded[s] = val
                    else:
                        break  # not RLE format, skip
                regions[rname] = expanded
        wells_plot_data.append({
            "name": w.name, "size": w.size, "depth": depth,
            "log_values": log_values,
            "logs": logs,
            "log_names": list(logs.keys()),
            "regions": regions,
            "region_names": list(regions.keys()),
            "x": w.x, "y": w.y,
        })
    return wells_plot_data


@router.post("/cancel")
async def weco_cancel():
    """Cancel a running correlation (if any)."""
    from weco.api import cancel_running_engine
    aborted = cancel_running_engine()
    return {"cancelled": aborted}


@router.post("/run")
async def weco_run(req: WecoRunRequest, request: Request):
    """Run correlation on previously imported wells.

    Auto-routes to Radix job component for large datasets (>WECO_JOB_WELL_THRESHOLD wells).
    """
    global _cached_well_list, _cached_res_file

    if _cached_well_list is None:
        raise HTTPException(400, "No wells loaded. Call /weco/import first.")

    # Filter wells by selection (if provided)
    wl = _cached_well_list
    if req.well_names:
        from weco.data import WellList
        selected = set(req.well_names)
        filtered = [w for w in wl.wells if w.name in selected]
        if not filtered:
            raise HTTPException(400, "No matching wells found in selection.")
        wl = WellList.__new__(WellList)
        wl.wells = filtered

    n_wells = len(wl.wells)

    # Auto-route large datasets to job component
    if n_wells > _JOB_WELL_THRESHOLD:
        log.info(f"Auto-routing {n_wells} wells to job component (threshold={_JOB_WELL_THRESHOLD})")
        return await weco_run_job(req, request, well_list=wl)

    try:
        from weco.api import _run_engine, _extract_results
        safe_opts = _apply_memory_guards(req.options, n_wells)
        # Apply preprocessing steps if requested
        pp_steps = safe_opts.pop("preprocessing", None)
        if pp_steps and isinstance(pp_steps, list):
            try:
                from weco.preprocessing import auto_preprocess
                auto_preprocess(wl, steps=pp_steps)
                log.info(f"Preprocessing applied: {pp_steps}")
            except Exception as pp_err:
                log.warning(f"Preprocessing failed (continuing): {pp_err}")

        # Log normalisation (pre-engine)
        norm_mode = safe_opts.pop("normalize-mode", None)
        if norm_mode and norm_mode in ("percentile", "zscore", "minmax"):
            try:
                from weco.preprocessing import normalise_log
                var_data = safe_opts.get("var-data", "")
                logs_to_norm = [var_data] if var_data else []
                for i in range(2, 6):
                    vd = safe_opts.get(f"var-data{i}", "")
                    if vd:
                        logs_to_norm.append(vd)
                for lname in logs_to_norm:
                    normalise_log(wl, lname, output_name=f"{lname}_norm", method=norm_mode)
                    # Replace in options with normalised name
                    if safe_opts.get("var-data") == lname:
                        safe_opts["var-data"] = f"{lname}_norm"
                    for i in range(2, 6):
                        if safe_opts.get(f"var-data{i}") == lname:
                            safe_opts[f"var-data{i}"] = f"{lname}_norm"
                log.info(f"Log normalisation applied: {logs_to_norm} ({norm_mode})")
            except Exception as ne:
                log.warning(f"Log normalisation failed (continuing): {ne}")

        # Log screening (pre-engine)
        log_screen = safe_opts.pop("log-screening", None)
        screening_report = None
        if log_screen in ("auto", "report"):
            try:
                from weco.diversity import screen_logs
                screening_report = screen_logs(wl)
                if log_screen == "auto":
                    relevant = {r["log"] for r in screening_report if r["relevant"]}
                    var_data = safe_opts.get("var-data", "")
                    if var_data and var_data not in relevant and relevant:
                        # Replace with best relevant log
                        best = screening_report[0]["log"] if screening_report else var_data
                        safe_opts["var-data"] = best
                        log.info(f"Log screening: replaced {var_data} with {best}")
                log.info(f"Log screening: {[r['log'] for r in (screening_report or []) if r['relevant']]}")
            except Exception as se:
                log.warning(f"Log screening failed (continuing): {se}")

        # Diversity mode (post-engine)
        diversity_mode = safe_opts.pop("diversity-mode", None)

        log.info(f"Running correlation: {n_wells} wells, options={safe_opts}, n_best={req.n_best}")
        rf, data, elapsed = _run_engine(wl, safe_opts)
        _cached_res_file = rf
        results = _extract_results(rf, data, req.n_best)

        # Post-run diversity filtering
        diversity_info = None
        if diversity_mode == "topology" and rf:
            try:
                from weco.diversity import filter_diverse_scenarios
                diversity_info = filter_diverse_scenarios(rf, wl, max_scenarios=req.n_best)
            except Exception as de:
                log.warning(f"Diversity filtering failed: {de}")
    except HTTPException:
        raise
    except Exception as e:
        log.exception(f"Correlation engine error: options={req.options}, n_wells={n_wells}")
        raise HTTPException(500, f"Correlation engine error: {e}")

    well_names = [w.name for w in wl.wells]

    # Include plot data for visualization
    wells_plot_data = _build_wells_plot_data(wl)

    response = {
        "status": "ok",
        "elapsed_ms": round(elapsed, 2),
        "n_wells": len(well_names),
        "well_names": well_names,
        "n_results": len(results),
        "results": [r.model_dump() if hasattr(r, "model_dump") else r.dict()
                    for r in results],
        "wells_plot_data": wells_plot_data,
        "options_used": safe_opts,
    }

    # Include diversity and screening info if available
    if diversity_info:
        response["diversity"] = diversity_info
    if screening_report:
        response["log_screening"] = screening_report

    return response


@router.post("/analyse-diversity")
async def weco_analyse_diversity(request: Request):
    """Analyse scenario diversity using topology-aware metrics.

    Post-processes cached results to identify architecturally distinct
    scenarios, screen logs for relevance, and optionally run cross-validation.

    Request body (optional):
        {"cross_validate": bool, "enumerate_architectures": bool,
         "gap_cost_range": [start, stop, step], "options": {...}}
    """
    global _cached_well_list, _cached_res_file

    if _cached_res_file is None:
        raise HTTPException(400, "No results cached. Run /weco/run first.")
    if _cached_well_list is None:
        raise HTTPException(400, "No wells loaded.")

    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    try:
        from weco.diversity import analyse_scenario_diversity
        report = analyse_scenario_diversity(
            _cached_res_file,
            _cached_well_list,
            options=body.get("options"),
            run_cross_validation=body.get("cross_validate", False),
            run_architecture_enum=body.get("enumerate_architectures", False),
            gap_cost_range=tuple(body.get("gap_cost_range", [0.0, 5.0, 1.0])),
        )
        return {"status": "ok", **report}
    except Exception as e:
        log.exception(f"Diversity analysis error: {e}")
        raise HTTPException(500, f"Diversity analysis error: {e}")


@router.post("/screen-logs")
async def weco_screen_logs(request: Request):
    """Screen available logs for correlation relevance.

    Returns logs ranked by their suitability for correlation, with scores
    and recommendations on which to use/avoid.
    """
    global _cached_well_list

    if _cached_well_list is None:
        raise HTTPException(400, "No wells loaded. Call /weco/import first.")

    try:
        from weco.diversity import screen_logs
        results = screen_logs(_cached_well_list)
        return {
            "status": "ok",
            "logs": results,
            "recommended": [r["log"] for r in results if r["relevant"]],
            "not_recommended": [r["log"] for r in results if not r["relevant"]],
        }
    except Exception as e:
        log.exception(f"Log screening error: {e}")
        raise HTTPException(500, f"Log screening error: {e}")


@router.post("/auto")
async def weco_auto(request: Request):
    """Quick Run: auto-suggest params → run → quality-gate → diverse results.

    Uses cached wells from /import or a demo selection. Zero-config correlation.
    Accepts optional {demo_id: "..."} to apply demo-specific options.
    """
    global _cached_well_list, _cached_res_file

    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    demo_id = body.get("demo_id") if body else None

    # If a demo_id is provided and no wells are cached, load the demo wells
    if demo_id and _cached_well_list is None:
        from weco.api import list_demos, _load_well_list
        demo_list = list_demos().demos
        for d in demo_list:
            if d.id == demo_id:
                _cached_well_list = _load_well_list(d.wells)
                break

    if _cached_well_list is None:
        raise HTTPException(400, "No wells loaded. Call /weco/import first.")

    wl = _cached_well_list
    n_wells = len(wl.wells)

    try:
        from weco.api import (_suggest_defaults_for_wells, _run_engine,
                              _extract_results, _diverse_results,
                              _topology_signature, _label_scenario,
                              _get_demo_opts)
        from weco.depenv import (detect_environment_from_logs,
                                 detect_environment_from_metadata, suggest_options)

        # 1. Suggest defaults - use demo-specific options if available
        if demo_id:
            demo_opts = _get_demo_opts(demo_id)
            if demo_opts:
                options = dict(demo_opts)
                reasoning = {"source": "demo", "demo_id": demo_id}
            else:
                options, reasoning = _suggest_defaults_for_wells(wl)
        else:
            options, reasoning = _suggest_defaults_for_wells(wl)

        # 2. Detect environment (only for non-demo runs - demos have curated opts)
        if reasoning.get("source") != "demo":
            try:
                env_key = detect_environment_from_metadata(wl)
                if env_key:
                    reasoning["env_source"] = "metadata"
                else:
                    env_key = detect_environment_from_logs(wl)
                    if env_key:
                        reasoning["env_source"] = "logs"
                if env_key:
                    env_opts = suggest_options(env_key, data_names=wl.get_data_names())
                    for k, v in env_opts.items():
                        norm_k = k.replace("_", "-")
                        if norm_k not in options:
                            options[norm_k] = v
                    reasoning["detected_environment"] = env_key
            except Exception:
                pass

        # 3. Memory guards + ensure diversity
        options = _apply_memory_guards(options, n_wells)
        options.setdefault("min-dist", 0.1)
        options.setdefault("out-min-dist", 0.05)
        options.setdefault("nbr-cor", 100)
        options.setdefault("out-nbr-cor", 20)

        # R3: Check result cache
        cache_k = _cache_key(wl, options)
        if cache_k in _result_cache:
            log.info(f"Auto-correlate: cache hit ({cache_k[:8]})")
            return _result_cache[cache_k]

        log.info(f"Auto-correlate: {n_wells} wells, env={reasoning.get('detected_environment','?')}")

        # 4. Run engine (with fallback on failure)
        engine_error = None
        try:
            rf, data, elapsed = _run_engine(wl, options)
            _cached_res_file = rf
        except Exception as engine_exc:
            engine_error = str(engine_exc)
            log.warning(f"Auto-correlate: primary run failed ({engine_error}), trying fallback")
            # Fallback: strip advanced options that may cause failure
            fallback_opts = {k: v for k, v in options.items()
                            if k in ("var-data", "var-weight", "max-cor",
                                     "min-dist", "out-min-dist", "nbr-cor",
                                     "out-nbr-cor", "order")}
            fallback_opts.setdefault("var-data", "GR")
            fallback_opts.setdefault("max-cor", 80)
            try:
                rf, data, elapsed = _run_engine(wl, fallback_opts)
                _cached_res_file = rf
                options = fallback_opts
                reasoning["fallback"] = f"Primary run failed: {engine_error}. Used simplified options."
            except Exception as fallback_exc:
                log.exception(f"Auto-correlate: fallback also failed: {fallback_exc}")
                raise HTTPException(500, f"Correlation failed: {engine_error} (fallback: {fallback_exc})")

        # 5. Extract diverse results
        # For small datasets (≤5 wells), use multi-config force-diverse for
        # structural diversity. For larger datasets, use single-run diversity
        # to avoid timeouts (force-diverse would run 4 extra engine calls).
        from weco.api import _force_diverse_run
        if n_wells <= 5:
            force_diverse = _force_diverse_run(wl, options, n_diverse=5)
        else:
            force_diverse = None

        if force_diverse:
            # _force_diverse_run returns [(RunResult, config_name, topology_sig), ...]
            diverse_results = []
            for r, config_name, sig in force_diverse:
                scenario = _label_scenario(sig) if sig else config_name
                entry = r.model_dump() if hasattr(r, "model_dump") else r.dict()
                entry["topology"] = "-".join(str(s) for s in sig) if sig else config_name
                entry["scenario"] = scenario
                entry["config"] = config_name
                diverse_results.append(entry)
        else:
            # Fallback: use single-run diversity
            diverse_indices = _diverse_results(rf, data, n_best=50, n_diverse=5)
            results = _extract_results(rf, data, 50)
            result_map = {r.index: r for r in results}

            diverse_results = []
            for idx in diverse_indices:
                r = result_map.get(idx)
                if r:
                    sig = _topology_signature(rf, idx, rf.nbr_well())
                    scenario = _label_scenario(sig)
                    diverse_results.append({
                        **(r.model_dump() if hasattr(r, "model_dump") else r.dict()),
                        "topology": "-".join(str(s) for s in sig),
                        "scenario": scenario,
                    })

        wells_plot_data = _build_wells_plot_data(wl)

    except HTTPException:
        raise
    except Exception as e:
        log.exception(f"Auto-correlate error: {e}")
        raise HTTPException(500, f"Auto-correlate error: {e}")

    response = {
        "status": "ok",
        "elapsed_ms": round(elapsed, 2),
        "iterations": 1,
        "n_wells": n_wells,
        "well_names": [w.name for w in wl.wells],
        "suggested_options": options,
        "reasoning": reasoning,
        "n_results": len(diverse_results),
        "results": diverse_results,
        "wells_plot_data": wells_plot_data,
    }

    # R3: Store in cache (evict oldest if full)
    if len(_result_cache) >= _RESULT_CACHE_MAX:
        _result_cache.pop(next(iter(_result_cache)))
    _result_cache[cache_k] = response

    return response


# ═══════════════════════════════════════════════════════════════════════════
#  Radix Job dispatch (heavy correlations → dedicated 8Gi pod)
# ═══════════════════════════════════════════════════════════════════════════

# Radix job scheduler URL (internal service discovery)
_RADIX_JOB_URL = os.getenv(
    "WECO_JOB_SCHEDULER_URL",
    "http://weco-correlation:8001"
)
# Threshold: datasets above this go to job component
_JOB_WELL_THRESHOLD = int(os.getenv("WECO_JOB_WELL_THRESHOLD", "15"))


@router.post("/run-job")
async def weco_run_job(req: WecoRunRequest, request: Request, well_list=None):
    """Submit correlation to the Radix job component (async, for large datasets).

    Automatically used when well count exceeds threshold, or can be called
    explicitly for heavy workloads that need more memory/CPU.
    """
    global _cached_well_list

    wl = well_list or _cached_well_list
    if wl is None:
        raise HTTPException(400, "No wells loaded. Call /weco/import first.")

    n_wells = len(wl.wells)

    try:
        import json
        import httpx

        # Serialize well data for the job
        wells_json = json.dumps(wl.to_dict())

        payload = {
            "wells_json": wells_json,
            "options": req.options,
            "n_best": req.n_best,
        }

        async with httpx.AsyncClient(timeout=600.0) as client:
            resp = await client.post(f"{_RADIX_JOB_URL}/run", json=payload)
            resp.raise_for_status()
            result = resp.json()

        if result.get("status") == "error":
            raise HTTPException(500, f"Job failed: {result.get('error')}")

        return {
            "status": "ok",
            "mode": "job",
            "n_wells": n_wells,
            "elapsed_ms": result.get("elapsed_ms", 0),
            "n_results": result.get("n_results", 0),
            "results": result.get("results", []),
            "options_used": result.get("options_used", {}),
        }

    except httpx.HTTPError as e:
        # Job component not available - fall back to in-process with guards
        log.warning(f"Job scheduler unavailable ({e}), falling back to in-process")
        from weco.api import _run_engine, _extract_results
        safe_opts = _apply_memory_guards(req.options, n_wells)
        rf, data, elapsed = _run_engine(wl, safe_opts)
        results = _extract_results(rf, data, req.n_best)
        wells_plot_data = _build_wells_plot_data(wl)
        return {
            "status": "ok",
            "mode": "in-process-fallback",
            "n_wells": n_wells,
            "elapsed_ms": round(elapsed, 2),
            "n_results": len(results),
            "results": [r.model_dump() if hasattr(r, "model_dump") else r.dict()
                        for r in results],
            "options_used": safe_opts,
            "wells_plot_data": wells_plot_data,
            "well_names": [w.name for w in wl.wells],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Job dispatch error: {e}")


@router.post("/export")
async def weco_export(request: Request):
    """Export last correlation results back to RDDMS as WellboreMarkerFrame.

    Uses ORES's native osdu.py transactional API.
    Exports boundary lines from result #0 (best) as marker frames per well.
    """
    global _cached_well_list, _cached_res_file

    token = _get_token(request)
    if not token:
        raise HTTPException(400, "No auth token. Log in first.")

    if _cached_well_list is None or _cached_res_file is None:
        raise HTTPException(400, "No correlation results. Run correlation first.")

    import uuid as _uuid
    from weco.api import _extract_results

    # Get the best result (index 0)
    results = _extract_results(_cached_res_file, None, 1)
    if not results:
        raise HTTPException(400, "No results to export.")
    result = results[0]

    wells = _cached_well_list.wells
    well_names = [w.name for w in wells]

    # Extract boundary lines only (these are the stratigraphic correlations)
    boundary_lines = [l for l in result.lines if l.line_type == "boundary"]
    if not boundary_lines:
        # Fall back to all lines if no boundaries classified
        boundary_lines = result.lines

    # Determine dataspace from well metadata
    dataspace = None
    for w in wells:
        if hasattr(w, "meta") and w.meta and w.meta.get("dataspace"):
            dataspace = w.meta["dataspace"]
            break
    if not dataspace:
        dataspace = WECO_DEFAULT_DATASPACE

    # Build WellboreMarkerFrame RESQML objects per well
    marker_frames = []
    for wi, well in enumerate(wells):
        rddms_id = ""
        if hasattr(well, "meta") and well.meta:
            rddms_id = well.meta.get("rddms_id", "")

        depth_array = well.data.get("Depth") or well.data.get("MD")
        if not depth_array:
            continue

        # Collect marker depths for this well from all boundary lines
        markers = []
        for li, line in enumerate(boundary_lines):
            if wi < len(line.markers):
                idx = line.markers[wi]
                if 0 <= idx < len(depth_array):
                    markers.append({
                        "MdValue": depth_array[idx],
                        "Label": f"H{li + 1}",
                        "Interpretation": "WeCo boundary",
                    })

        if not markers:
            continue

        frame_uuid = str(_uuid.uuid4())
        frame_obj = {
            "Uuid": frame_uuid,
            "SchemaVersion": "2.0",
            "ObjectType": "resqml20.obj_WellboreMarkerFrameRepresentation",
            "Citation": {
                "Title": f"WeCo Correlation - {well.name}",
                "Originator": "WeCo Engine",
                "Description": f"Exported from WeCo correlation (cost={result.cost:.4f})",
            },
            "WellboreName": well.name,
            "WellboreId": rddms_id,
            "WellboreMarker": [
                {
                    "Uuid": str(_uuid.uuid4()),
                    "FluidContact": None,
                    "GeologicBoundaryKind": "horizon",
                    "Interpretation": m["Interpretation"],
                    "Label": m["Label"],
                }
                for m in markers
            ],
            "NodeMd": {
                "Values": [m["MdValue"] for m in markers],
                "UOM": "m",
            },
        }
        marker_frames.append(frame_obj)

    if not marker_frames:
        raise HTTPException(400, "No marker data to export (wells have no depth data).")

    # Write to RDDMS via transactional API
    from app.osdu import begin_transaction, put_resources, commit_transaction, cancel_transaction
    try:
        tx_id = await begin_transaction(token, dataspace)
        await put_resources(token, dataspace, marker_frames, tx_id)
        await commit_transaction(token, dataspace, tx_id)
    except Exception as e:
        # Attempt rollback
        try:
            await cancel_transaction(token, dataspace, tx_id)
        except Exception:
            pass
        log.error(f"RDDMS export failed: {e}")
        raise HTTPException(500, f"RDDMS export failed: {e}")

    return {
        "status": "ok",
        "n_wells_exported": len(marker_frames),
        "n_markers_per_well": len(boundary_lines),
        "dataspace": dataspace,
        "well_names": [w.name for w in wells if any(
            f["WellboreName"] == w.name for f in marker_frames
        )],
    }


@router.post("/correlate")
async def weco_full_workflow(req: WecoFullRequest, request: Request):
    """Full workflow: import → suggest → correlate → export.

    Uses ORES native RDDMS client + WeCo engine (no gocad).
    """
    global _cached_well_list

    token = _get_token(request)
    if not token:
        raise HTTPException(401, "Not authenticated.")

    dataspace = req.dataspace or WECO_DEFAULT_DATASPACE

    # Step 1: Import wells via ORES osdu client
    try:
        wl = await _rddms_import_wells(token, dataspace)
        _cached_well_list = wl
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"RDDMS import failed: {e}")

    import_summary = {
        "well_count": len(wl.wells),
        "well_names": [w.name for w in wl.wells],
    }

    # Step 2: Suggest defaults + merge with user options
    from weco.api import _suggest_defaults_for_wells, _run_engine, _extract_results
    try:
        suggested, reasoning = _suggest_defaults_for_wells(wl)
        merged_options = {**suggested, **req.options}
    except Exception:
        merged_options = req.options

    # Step 3: Apply memory guards and run correlation
    safe_opts = _apply_memory_guards(merged_options, len(wl.wells))
    try:
        rf, data, elapsed = _run_engine(wl, safe_opts)
        results = _extract_results(rf, data, req.n_best)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Correlation engine error: {e}")

    run_summary = {
        "status": "ok",
        "elapsed_ms": round(elapsed, 2),
        "n_results": len(results),
        "results": [r.model_dump() if hasattr(r, "model_dump") else r.dict()
                    for r in results],
    }

    return {
        "import": import_summary,
        "correlation": run_summary,
        "options_used": safe_opts,
    }


@router.get("/options")
def weco_options():
    """Get all available WeCo engine options with help text."""
    try:
        from weco.api import options_help
        return options_help()
    except Exception as e:
        raise HTTPException(500, f"Cannot load options: {e}")


@router.get("/demos")
def weco_demos():
    """List available demo datasets with well counts for the GUI."""
    try:
        from weco.api import list_demos, _load_well_list
        demo_resp = list_demos()
        # Enrich with well counts
        enriched = []
        for d in demo_resp.demos:
            info = {
                "id": d.id,
                "title": d.title,
                "group": d.group,
                "geology": d.geology,
            }
            try:
                wl = _load_well_list(d.wells)
                info["n_wells"] = wl.nbr_wells()
                info["data_names"] = list(wl.get_data_names())[:5]
                info["region_names"] = list(wl.get_region_names())[:3]
            except Exception:
                info["n_wells"] = "?"
            enriched.append(info)
        return {"demos": enriched}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/demos/{demo_id}/wells")
def weco_demo_wells(demo_id: str):
    """Load a demo dataset and return well metadata (without running correlation).

    Returns wells with their available logs, regions, sizes - so the UI can
    present a well/log selection matrix before running.
    Also returns demo-specific recommended options for the Parameters form.
    """
    global _cached_well_list
    try:
        from weco.api import list_demos, _load_well_list, _get_demo_opts
        from weco.api import _suggest_defaults_for_wells, _get_demo_ai_opts

        demo_list = list_demos().demos
        demo = None
        for d in demo_list:
            if d.id == demo_id:
                demo = d
                break
        if demo is None:
            raise HTTPException(404, f"Demo '{demo_id}' not found")

        wl = _load_well_list(demo.wells)
        _cached_well_list = wl  # cache for subsequent /run calls

        # All unique log/region names across all wells
        all_data_names = sorted(set(
            name for w in wl.wells for name in w.data.keys()
        ))
        all_region_names = sorted(set(
            name for w in wl.wells for name in w.region.keys()
        ))

        wells = []
        for w in wl.wells:
            wells.append({
                "name": w.name,
                "size": w.size,
                "x": w.x, "y": w.y, "z": w.z, "h": w.h,
                "data_names": sorted(w.data.keys()),
                "region_names": sorted(w.region.keys()),
            })

        # Get demo-specific recommended options (or auto-suggest)
        recommended_options = _get_demo_opts(demo_id)
        if not recommended_options:
            recommended_options, _ = _suggest_defaults_for_wells(wl)

        return {
            "demo_id": demo_id,
            "title": demo.title,
            "n_wells": len(wells),
            "wells": wells,
            "all_data_names": all_data_names,
            "all_region_names": all_region_names,
            "recommended_options": recommended_options,
            "ai_settings": _get_demo_ai_opts(demo_id),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/run/demo")
def weco_run_demo(demo_id: str, n_best: int = 5):
    """Run a demo dataset on the WeCo engine (in-process).

    Returns full correlation results including well data for plotting.
    """
    global _cached_well_list, _cached_res_file
    try:
        from weco.api import run_demo, DemoRunRequest, _load_well_list, list_demos
        from weco.api import _suggest_defaults_for_wells, _run_engine, _extract_results
        from weco.api import _get_demo_opts

        # Find the demo
        demo_list = list_demos().demos
        demo = None
        for d in demo_list:
            if d.id == demo_id:
                demo = d
                break
        if demo is None:
            raise HTTPException(404, f"Demo '{demo_id}' not found")

        # Load wells
        wl = _load_well_list(demo.wells)
        _cached_well_list = wl  # cache for subsequent operations

        # Use per-demo tested options first, fallback to auto-suggest
        options = _get_demo_opts(demo_id)
        if not options:
            options, reasoning = _suggest_defaults_for_wells(wl)

        rf, data, elapsed = _run_engine(wl, options)
        _cached_res_file = rf
        results = _extract_results(rf, data, n_best)

        well_names = [w.name for w in wl.wells]

        # Build well data for plotting
        wells_plot_data = _build_wells_plot_data(wl)

        return {
            "status": "ok",
            "demo_id": demo_id,
            "elapsed_ms": round(elapsed, 2),
            "n_wells": len(well_names),
            "well_names": well_names,
            "n_results": len(results),
            "results": [r.model_dump() if hasattr(r, "model_dump") else r.dict()
                        for r in results],
            "options_used": options,
            "wells_plot_data": wells_plot_data,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/import/demo")
async def weco_import_demo_from_rddms(demo_id: str, request: Request,
                                       dataspace: str = "maap/weco"):
    """Import a specific demo's wells from RDDMS using deterministic UUIDs.

    The ingestion script writes wells with deterministic UUID5 keys based
    on (demo_key + well_name). This endpoint uses the same formula to
    directly fetch the correct objects without searching.
    """
    global _cached_well_list

    token = _get_token(request)
    if not token:
        raise HTTPException(401, "Not authenticated.")

    # Get demo well names from the WeCo catalogue
    try:
        from weco.api import list_demos, _load_well_list
        demo_list = list_demos().demos
        demo = None
        for d in demo_list:
            if d.id == demo_id:
                demo = d
                break
        if demo is None:
            raise HTTPException(404, f"Demo '{demo_id}' not found")

        # Load from local file to get well names
        wl_local = _load_well_list(demo.wells)
        well_names = [w.name for w in wl_local.wells]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Cannot load demo catalogue: {e}")

    # Import each well from RDDMS using deterministic UUIDs
    from . import osdu
    from weco.data import Well, WellList

    ds_enc = urllib.parse.quote(dataspace, safe="")
    TRAJ_TYPE = "resqml20.obj_WellboreTrajectoryRepresentation"
    FRAME_TYPE = "resqml20.obj_WellboreFrameRepresentation"
    CONT_PROP_TYPE = "resqml20.obj_ContinuousProperty"

    wells = []
    for wname in well_names:
        traj_uuid = _demo_uuid(demo_id, wname, "traj")
        frame_uuid = _demo_uuid(demo_id, wname, "frame")

        try:
            # Read trajectory (geometry + MD)
            arrays_meta = await osdu.list_arrays(token, ds_enc, TRAJ_TYPE, traj_uuid)
            mds = None
            points = None
            for arr in arrays_meta:
                path = _arr_path(arr)
                if "controlPointParameters" in path or "MdValues" in path or "mdValues" in path:
                    arr_data = await osdu.read_array(
                        token, ds_enc, TRAJ_TYPE, traj_uuid, path_in_resource=path)
                    values = _arr_values(arr_data)
                    if values:
                        mds = np.array(values, dtype=np.float64)
                elif "controlPoints" in path or "ControlPoints" in path or "Geometry" in path:
                    arr_data = await osdu.read_array(
                        token, ds_enc, TRAJ_TYPE, traj_uuid, path_in_resource=path)
                    values = _arr_values(arr_data)
                    if values:
                        points = np.array(values, dtype=np.float64).reshape(-1, 3)

            w = Well()
            w.name = wname
            w.meta["uuid"] = traj_uuid
            w.meta["demo"] = demo_id
            w.meta["dataspace"] = dataspace
            if points is not None and len(points) > 0:
                w.size = len(points)
                w.x = float(points[0, 0])
                w.y = float(points[0, 1])
                w.z = float(points[0, 2])
            elif mds is not None:
                w.size = len(mds)
                w.x = w.y = w.z = 0.0
            else:
                log.warning(f"  Demo RDDMS: '{wname}' has no geometry, skipping")
                continue

            if mds is not None:
                w.data["Depth"] = list(mds[:w.size])
            elif points is not None:
                diffs = np.diff(points, axis=0)
                segs = np.sqrt(np.sum(diffs ** 2, axis=1))
                w.data["Depth"] = list(np.concatenate([[0.0], np.cumsum(segs)]))

            # Read log properties from frame
            frame_arrays = await osdu.list_arrays(token, ds_enc, FRAME_TYPE, frame_uuid)
            # Read all continuous properties for this well
            for log_name in wl_local.get_data_names():
                if log_name in ("Depth", "DEPTH", "X", "Y", "Z", "MD"):
                    continue
                prop_uuid = _demo_uuid(demo_id, wname, f"cont_{log_name}")
                try:
                    p_arrays = await osdu.list_arrays(
                        token, ds_enc, CONT_PROP_TYPE, prop_uuid)
                    for pa in p_arrays:
                        pa_path = _arr_path(pa)
                        if "values" in pa_path.lower() or "patch" in pa_path.lower():
                            arr_data = await osdu.read_array(
                                token, ds_enc, CONT_PROP_TYPE, prop_uuid,
                                path_in_resource=pa_path)
                            vals = _arr_values(arr_data)
                            if vals:
                                w.data[log_name] = list(np.array(vals, dtype=np.float64)[:w.size])
                                break
                except Exception:
                    pass

            wells.append(w)
            log.info(f"  RDDMS demo import: '{wname}' OK ({w.size} pts, {len(w.data)-1} logs)")

        except Exception as e:
            log.warning(f"  RDDMS demo import: '{wname}' failed: {e}")
            continue

    if not wells:
        raise HTTPException(404,
            f"Demo '{demo_id}' not found in RDDMS dataspace '{dataspace}'. "
            "Run the ingestion script first: python demo/ingest_weco_demos.py")

    wl = WellList.__new__(WellList)
    wl.wells = wells
    _cached_well_list = wl

    return {
        "status": "ok",
        "source": "rddms",
        "demo_id": demo_id,
        "dataspace": dataspace,
        "well_count": len(wells),
        "well_names": [w.name for w in wells],
        "data_names": list(wl.get_data_names()) if hasattr(wl, "get_data_names") else [],
        "region_names": list(wl.get_region_names()) if hasattr(wl, "get_region_names") else [],
    }


@router.get("/strat-column")
async def weco_strat_column(request: Request):
    """Fetch stratigraphic column from active RDDMS instance."""
    token = _get_token(request)
    if not token:
        raise HTTPException(400, "Not authenticated.")
    return {"redirect": "/strat", "note": "Use the Stratigraphy tab for column browsing"}


@router.post("/depenv/suggest")
def weco_depenv_suggest(environment: Optional[str] = None):
    """Suggest WeCo parameters based on depositional environment."""
    try:
        from weco.api import depenv_suggest, DepenvSuggestRequest
        req = DepenvSuggestRequest(environment=environment)
        return depenv_suggest(req)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/dataspaces")
async def weco_dataspaces(request: Request):
    """List available dataspaces from the RDDMS instance."""
    token = _get_token(request)
    if not token:
        raise HTTPException(401, "Not authenticated.")
    try:
        from . import osdu
        dataspaces = await osdu.list_dataspaces(token)
        return {"dataspaces": dataspaces}
    except Exception as e:
        raise HTTPException(500, f"Cannot list dataspaces: {e}")


# RESQML types relevant for WeCo correlation workflows
WECO_OBJECT_TYPES = [
    {"type": "resqml20.obj_WellboreTrajectoryRepresentation", "label": "Trajectories", "group": "wells"},
    {"type": "resqml20.obj_WellboreFrameRepresentation", "label": "Log Frames", "group": "wells"},
    {"type": "resqml20.obj_ContinuousProperty", "label": "Continuous Logs", "group": "wells"},
    {"type": "resqml20.obj_DiscreteProperty", "label": "Discrete/Facies", "group": "wells"},
    {"type": "resqml20.obj_WellboreMarkerFrameRepresentation", "label": "Markers", "group": "strat"},
    {"type": "resqml20.obj_StratigraphicColumn", "label": "Strat Columns", "group": "strat"},
    {"type": "resqml20.obj_StratigraphicColumnRankInterpretation", "label": "Strat Ranks", "group": "strat"},
    {"type": "resqml20.obj_WellboreFeature", "label": "Wellbore Features", "group": "meta"},
    {"type": "resqml20.obj_WellboreInterpretation", "label": "Wellbore Interp.", "group": "meta"},
    {"type": "resqml20.obj_MdDatum", "label": "MD Datums", "group": "meta"},
    {"type": "resqml20.obj_LocalDepth3dCrs", "label": "CRS", "group": "meta"},
    {"type": "eml20.obj_EpcExternalPartReference", "label": "HDF Proxy", "group": "meta"},
]


@router.get("/objects/types")
async def weco_object_types():
    """Return the list of supported RESQML/EML types for the object browser."""
    return {"types": WECO_OBJECT_TYPES}


@router.get("/objects")
async def weco_list_objects(request: Request, dataspace: str, type: str):
    """List RESQML objects of a given type in a dataspace.

    Returns name, uuid, lastChanged for multi-select in the UI.
    """
    token = _get_token(request)
    if not token:
        raise HTTPException(401, "Not authenticated.")
    from . import osdu
    ds_enc = urllib.parse.quote(dataspace, safe="")
    try:
        raw = await osdu.list_resources(token, ds_enc, type)
    except Exception as e:
        raise HTTPException(502, f"RDDMS error: {e}")
    objects = []
    for r in raw:
        uuid = _uuid_from_uri(r.get("uri", "")) if r.get("uri") else r.get("Uuid", "")
        name = r.get("name") or r.get("title") or (r.get("Citation") or {}).get("Title") or uuid[:12]
        objects.append({
            "uuid": uuid,
            "name": name,
            "lastChanged": r.get("lastChanged", ""),
            "storeCreated": r.get("storeCreated", ""),
        })
    objects.sort(key=lambda o: o["name"])
    return {"type": type, "count": len(objects), "objects": objects}


@router.get("/wells")
async def weco_wells_info():
    """Return info about currently loaded wells (without re-importing)."""
    if _cached_well_list is None:
        return {"loaded": False, "well_count": 0}

    wl = _cached_well_list
    return {
        "loaded": True,
        "well_count": len(wl.wells),
        "well_names": [w.name for w in wl.wells],
        "data_names": list(wl.get_data_names()) if hasattr(wl, "get_data_names") else [],
        "region_names": list(wl.get_region_names()) if hasattr(wl, "get_region_names") else [],
        "wells": [
            {
                "name": w.name,
                "size": w.size,
                "x": w.x, "y": w.y, "z": w.z, "h": w.h,
                "data_names": list(w.data.keys()),
                "region_names": list(w.region.keys()),
                "uuid": (w.meta or {}).get("uuid", ""),
                "demo": (w.meta or {}).get("demo", ""),
            }
            for w in wl.wells
        ],
    }


@router.post("/wells/order")
async def weco_wells_order(req: dict):
    """Compute well display ordering by spatial criteria.

    Methods: input, x, y, azimuth, distality, pca, nearest.
    """
    if _cached_well_list is None:
        raise HTTPException(400, "No wells loaded. Import wells first.")

    import math
    import numpy as np

    wl = _cached_well_list
    n = len(wl.wells)
    method = req.get("method", "input").lower().strip()
    azimuth_deg = req.get("azimuth_deg", 90.0)
    projections = None

    if method == "x":
        order = sorted(range(n), key=lambda i: wl.wells[i].x)
        projections = [wl.wells[i].x for i in order]
    elif method == "y":
        order = sorted(range(n), key=lambda i: wl.wells[i].y)
        projections = [wl.wells[i].y for i in order]
    elif method == "azimuth":
        theta = math.radians(azimuth_deg)
        dx, dy = math.sin(theta), math.cos(theta)
        projs = [(wl.wells[i].x * dx + wl.wells[i].y * dy, i) for i in range(n)]
        projs.sort()
        order = [i for _, i in projs]
        projections = [p for p, _ in projs]
    elif method == "distality":
        distality_vals = []
        for i, w in enumerate(wl.wells):
            d = 0.5
            if hasattr(w, 'region') and isinstance(w.region, dict):
                for rname in ('DISTALITY', 'DISTAL', 'distality', 'Distality'):
                    reg = w.region.get(rname)
                    if reg and len(reg) > 0:
                        d = reg[0][0] if isinstance(reg[0], (list, tuple)) else reg[0]
                        break
            distality_vals.append((d, i))
        distality_vals.sort()
        order = [i for _, i in distality_vals]
        projections = [d for d, _ in distality_vals]
    elif method == "pca":
        coords = np.array([[w.x, w.y] for w in wl.wells])
        if coords.std() < 1e-6:
            order = list(range(n))
        else:
            centered = coords - coords.mean(axis=0)
            _, _, Vt = np.linalg.svd(centered, full_matrices=False)
            proj_vals = centered @ Vt[0]
            order = list(np.argsort(proj_vals).tolist())
            projections = [float(proj_vals[i]) for i in order]
    elif method == "nearest":
        try:
            from weco.order import compute_nearest_ordering
            coords = [(w.x, w.y) for w in wl.wells]
            order = compute_nearest_ordering(coords, first=0)
        except Exception:
            order = list(range(n))
    else:
        order = list(range(n))

    return {
        "method": method,
        "order": order,
        "well_names": [wl.wells[i].name for i in order],
        "projections": projections,
    }


@router.get("/well-data/{well_idx}")
async def weco_well_data(well_idx: int, channel: Optional[str] = None):
    """Return actual log values for a loaded well (for plotting).

    If channel is specified, returns only that channel.
    Otherwise returns all channels (for correlation plot).
    """
    if _cached_well_list is None:
        raise HTTPException(400, "No wells loaded")
    if well_idx < 0 or well_idx >= len(_cached_well_list.wells):
        raise HTTPException(404, f"Well index {well_idx} out of range")

    w = _cached_well_list.wells[well_idx]
    skip = {"X", "Y", "Z"}

    if channel:
        if channel not in w.data:
            raise HTTPException(404, f"Channel '{channel}' not found in well '{w.name}'")
        return {
            "name": w.name,
            "size": w.size,
            "channel": channel,
            "values": list(w.data[channel])[:w.size],
            "depth": list(w.data.get("Depth", w.data.get("DEPTH", range(w.size))))[:w.size],
        }

    # Return all channels
    data = {}
    for k, v in w.data.items():
        if k not in skip:
            data[k] = list(v)[:w.size]

    return {
        "name": w.name,
        "size": w.size,
        "data": data,
        "regions": {k: list(v) for k, v in w.region.items()},
    }


@router.get("/plot-data")
async def weco_plot_data():
    """Return all data needed to render the correlation plot.

    Includes: well depths, all log values, regions/zones, and correlation lines
    from the last run. This is the single endpoint the JS plot needs.
    """
    if _cached_well_list is None:
        raise HTTPException(400, "No wells loaded")

    wl = _cached_well_list
    wells_data = _build_wells_plot_data(wl)

    # Determine available data/region names
    _SKIP = {"Depth", "DEPTH", "X", "Y", "Z", "MD", "TVD", "TVDSS"}
    data_names = []
    if hasattr(wl, "get_data_names"):
        data_names = [n for n in wl.get_data_names() if n not in _SKIP]
    elif wl.wells:
        data_names = [n for n in wl.wells[0].data.keys() if n not in _SKIP]

    region_names = []
    if wl.wells and hasattr(wl.wells[0], 'region') and wl.wells[0].region:
        region_names = list(wl.wells[0].region.keys())

    return {
        "n_wells": len(wl.wells),
        "well_names": [w.name for w in wl.wells],
        "primary_log": data_names[0] if data_names else None,
        "data_names": data_names,
        "region_names": region_names,
        "wells": wells_data,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  Per-user workflow storage (save/load named correlation configurations)
# ══════════════════════════════════════════════════════════════════════════════

def _weco_user_oid(request: Request) -> str:
    """Extract user OID from the session (same pattern as search_router)."""
    if hasattr(request, "session"):
        return request.session.get("oid", "")
    return ""


@router.get("/workflows")
async def weco_list_workflows(request: Request):
    """List all saved workflows for the current user."""
    oid = _weco_user_oid(request)
    workflows = _ts_list_workflows(oid)
    # Parse JSON fields for the response
    for wf in workflows:
        try:
            wf["options"] = json.loads(wf["options"])
        except (json.JSONDecodeError, TypeError):
            wf["options"] = {}
        try:
            wf["well_ids"] = json.loads(wf["well_ids"])
        except (json.JSONDecodeError, TypeError):
            wf["well_ids"] = []
    return workflows


@router.post("/workflows")
async def weco_save_workflow(request: Request):
    """Save or update a workflow configuration.

    Body: {name, demo_id?, dataspace?, options?, n_best?, well_ids?, notes?, id?}
    If 'id' is provided, updates existing workflow; otherwise creates new.
    """
    oid = _weco_user_oid(request)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    name = (body.get("name") or "").strip()
    if not name:
        return JSONResponse({"error": "name is required"}, status_code=400)

    demo_id = (body.get("demo_id") or "").strip()
    dataspace = (body.get("dataspace") or "").strip()
    options = json.dumps(body.get("options") or {})
    n_best = int(body.get("n_best", 5))
    well_ids = json.dumps(body.get("well_ids") or [])
    notes = (body.get("notes") or "").strip()
    workflow_id = body.get("id")

    row_id = _ts_save_workflow(
        oid=oid, name=name, demo_id=demo_id, dataspace=dataspace,
        options=options, n_best=n_best, well_ids=well_ids, notes=notes,
        workflow_id=int(workflow_id) if workflow_id else None,
    )
    if row_id is None:
        return JSONResponse({"error": "Failed to save"}, status_code=500)
    return {"id": row_id, "name": name, "demo_id": demo_id}


@router.get("/workflows/{workflow_id}")
async def weco_get_workflow(workflow_id: int, request: Request):
    """Get a single saved workflow by id."""
    oid = _weco_user_oid(request)
    wf = _ts_get_workflow(workflow_id, oid)
    if not wf:
        raise HTTPException(404, "Workflow not found")
    try:
        wf["options"] = json.loads(wf["options"])
    except (json.JSONDecodeError, TypeError):
        wf["options"] = {}
    try:
        wf["well_ids"] = json.loads(wf["well_ids"])
    except (json.JSONDecodeError, TypeError):
        wf["well_ids"] = []
    return wf


@router.delete("/workflows/{workflow_id}")
async def weco_delete_workflow(workflow_id: int, request: Request):
    """Delete a saved workflow by id."""
    oid = _weco_user_oid(request)
    ok = _ts_delete_workflow(workflow_id, oid=oid)
    if not ok:
        return JSONResponse({"error": "Failed to delete"}, status_code=500)
    return {"deleted": workflow_id}


# ═══════════════════════════════════════════════════════════════════════════
#  AI Analysis Endpoints
# ═══════════════════════════════════════════════════════════════════════════

class AiAnalysisRequest(BaseModel):
    """Request body for AI post-processing of correlation results."""
    quality: bool = True
    anomaly: bool = False
    uncertainty: bool = False
    cor_index: int = 0


@router.post("/ai/analyse")
def weco_ai_analyse(req: AiAnalysisRequest):
    """Run AI analysis on the cached correlation results.

    Call this after /run or /run/demo. Returns quality scores,
    anomaly flags, and uncertainty metrics for the specified result.
    """
    global _cached_res_file, _cached_well_list
    if _cached_res_file is None or _cached_well_list is None:
        raise HTTPException(400, "No correlation results cached. Run /run or /run/demo first.")

    result = {}
    try:
        n_cor = _cached_res_file.get_nbr_results()
        if req.cor_index >= n_cor:
            raise HTTPException(400, f"cor_index {req.cor_index} >= n_results {n_cor}")

        if req.quality:
            from weco.ai.quality import CorrelationQuality
            cq = CorrelationQuality()
            scores = cq.score_correlations(_cached_res_file, _cached_well_list)
            if req.cor_index < len(scores):
                s = scores[req.cor_index]
                result["quality"] = {
                    "overall": round(s["total"], 4),
                    "cost_score": round(1.0 - s.get("gap_fraction", 0), 4),
                    "gap_score": round(1.0 - s.get("gap_fraction", 0), 4),
                    "similarity_score": round(s.get("similarity", 0), 4),
                }
            # Include ranking of all results
            result["quality_ranking"] = [
                {"index": sc["index"], "overall": round(sc["total"], 4)}
                for sc in scores[:20]
            ]

        if req.anomaly:
            from weco.ai.anomaly import CorrelationAnomalyDetector
            det = CorrelationAnomalyDetector()
            flags = det.flag_anomalies(_cached_res_file, _cached_well_list)
            anomalies = [
                {"line_idx": f["index"], "score": round(f["score"], 4), "reason": "anomaly" if f["anomaly"] else "normal"}
                for f in flags if f.get("anomaly")
            ]
            result["anomaly"] = {
                "n_flagged": len(anomalies),
                "flags": anomalies[:20],
            }

        if req.uncertainty and n_cor > 1:
            from weco.ai.uncertainty import CorrelationUncertainty
            unc_map = CorrelationUncertainty.from_n_best(_cached_res_file, n_paths=min(n_cor, 10))
            if unc_map:
                all_stds = np.concatenate([v for v in unc_map.values() if len(v) > 0])
                result["uncertainty"] = {
                    "mean_spread": round(float(np.nanmean(all_stds)), 4),
                    "max_spread": round(float(np.nanmax(all_stds)), 4),
                }
            else:
                result["uncertainty"] = {"mean_spread": 0.0, "max_spread": 0.0}

    except HTTPException:
        raise
    except ImportError as e:
        raise HTTPException(501, f"AI module not available: {e}")
    except Exception as e:
        log.exception("AI analysis failed")
        raise HTTPException(500, f"AI analysis error: {e}")

    return result


# ═══════════════════════════════════════════════════════════════════════════
#  Presets
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/presets")
async def weco_get_presets():
    """Return all geological presets from the engine."""
    try:
        from weco.api import list_presets
        resp = list_presets()
        return resp.model_dump() if hasattr(resp, "model_dump") else resp.dict()
    except Exception as e:
        log.warning(f"Presets load failed: {e}")
        # Return empty so frontend falls back to hardcoded
        return {"presets": []}


# ═══════════════════════════════════════════════════════════════════════════
#  Parameter Sweep
# ═══════════════════════════════════════════════════════════════════════════

@router.post("/sweep")
async def weco_sweep(request: Request):
    """Run a parameter sweep on the loaded wells."""
    global _cached_well_list

    if _cached_well_list is None:
        raise HTTPException(400, "No wells loaded. Call /weco/import first.")

    body = await request.json()
    parameter = body.get("parameter")
    values = body.get("values", [])
    base_options = body.get("base_options", {})

    if not parameter or not values:
        raise HTTPException(400, "Must provide 'parameter' and 'values'.")

    try:
        from weco.api import _run_engine, _extract_results

        results = []
        for val in values:
            opts = dict(base_options)
            opts[parameter] = val
            safe_opts = _apply_memory_guards(opts, len(_cached_well_list.wells))
            rf, data, elapsed = _run_engine(_cached_well_list, safe_opts)
            extracted = _extract_results(rf, data, 1)
            cost = extracted[0].cost if extracted else float("inf")
            results.append({"value": val, "cost": cost, "elapsed_ms": round(elapsed, 2)})

        results.sort(key=lambda r: r["cost"])
        best = results[0] if results else {"value": values[0], "cost": 0}

        return {
            "status": "ok",
            "parameter": parameter,
            "best_value": best["value"],
            "best_cost": best["cost"],
            "results": results,
        }
    except HTTPException:
        raise
    except Exception as e:
        log.exception(f"Sweep failed: parameter={parameter}")
        raise HTTPException(500, f"Sweep error: {e}")


# ═══════════════════════════════════════════════════════════════════════════
#  Sensitivity (merge-order robustness)
# ═══════════════════════════════════════════════════════════════════════════

@router.post("/sensitivity")
async def weco_sensitivity(request: Request):
    """Test sensitivity to merge order."""
    global _cached_well_list

    if _cached_well_list is None:
        raise HTTPException(400, "No wells loaded. Call /weco/import first.")

    body = await request.json()
    base_options = body.get("base_options", {})

    try:
        from weco.api import _run_engine, _extract_results

        orders = ["linear", "nearest", "mst", "random"]
        costs = {}

        for order in orders:
            opts = dict(base_options)
            opts["order"] = order
            safe_opts = _apply_memory_guards(opts, len(_cached_well_list.wells))
            try:
                rf, data, elapsed = _run_engine(_cached_well_list, safe_opts)
                extracted = _extract_results(rf, data, 1)
                costs[order] = extracted[0].cost if extracted else float("inf")
            except Exception:
                costs[order] = float("inf")

        finite_costs = [c for c in costs.values() if c < float("inf")]
        if len(finite_costs) >= 2:
            spread = max(finite_costs) - min(finite_costs)
            mean = sum(finite_costs) / len(finite_costs)
            robustness = 1.0 - (spread / mean) if mean > 0 else 1.0
        else:
            robustness = 1.0

        best_order = min(costs, key=costs.get)
        if robustness > 0.9:
            recommendation = "Very robust - result stable across merge orders."
        elif robustness > 0.7:
            recommendation = f"Moderately robust. Consider using '{best_order}' order."
        else:
            recommendation = f"Sensitive to merge order! '{best_order}' gives lowest cost."

        return {
            "status": "ok",
            "costs": costs,
            "best_order": best_order,
            "robustness": round(robustness, 4),
            "recommendation": recommendation,
        }
    except HTTPException:
        raise
    except Exception as e:
        log.exception("Sensitivity test failed")
        raise HTTPException(500, f"Sensitivity error: {e}")


# ═══════════════════════════════════════════════════════════════════════════
#  Auto-Tune (parameter optimisation)
# ═══════════════════════════════════════════════════════════════════════════

@router.post("/auto-tune")
async def weco_auto_tune(request: Request):
    """Optimise correlation parameters using differential evolution.

    Body: {
      "base_options": {...},          // fixed options
      "param_bounds": {"var-weight": [0,5], ...},  // optional overrides
      "max_iter": 20,                 // generations (default 20)
      "method": "de",                 // "de" | "nelder"
      "reference_result_idx": 0       // use current result N as reference
    }

    Returns optimised parameter values and convergence info.
    """
    global _cached_well_list, _cached_res_file

    if _cached_well_list is None:
        raise HTTPException(400, "No wells loaded. Call /weco/import first.")

    body = await request.json()
    base_options = body.get("base_options", {})
    param_bounds = body.get("param_bounds", None)
    max_iter = min(body.get("max_iter", 20), 100)  # cap at 100
    method = body.get("method", "de")
    ref_idx = body.get("reference_result_idx", None)

    try:
        from weco.ai.auto_tune import AutoTuner, DEFAULT_PARAM_BOUNDS

        # Build param bounds from active cost logs
        if param_bounds:
            bounds = {k: tuple(v) for k, v in param_bounds.items()}
        else:
            # Auto-detect: tune weights for active logs + gap cost
            bounds = {}
            if base_options.get("var-data"):
                bounds["var-weight"] = (0.1, 5.0)
            if base_options.get("var-data2"):
                bounds["var-weight2"] = (0.0, 5.0)
            if base_options.get("var-data3"):
                bounds["var-weight3"] = (0.0, 5.0)
            bounds["const-gap-cost"] = (0.0, 8.0)
            bounds["min-dist"] = (0.1, 0.8)
            if not bounds:
                bounds = dict(DEFAULT_PARAM_BOUNDS)

        # Reference: use current best result, or run a baseline
        reference = None
        if ref_idx is not None and _cached_res_file is not None:
            reference = _cached_res_file
        elif _cached_res_file is not None:
            reference = _cached_res_file
        else:
            # Run baseline to create reference
            from weco.ext import ProjectExt
            p = ProjectExt()
            safe_opts = _apply_memory_guards(
                dict(base_options), len(_cached_well_list.wells))
            for k, v in safe_opts.items():
                try:
                    p.set_option_ext(k, str(v))
                except (ValueError, TypeError):
                    pass
            p.run(_cached_well_list)
            reference = p.get_res_file()

        tuner = AutoTuner(
            well_list=_cached_well_list,
            reference=reference,
            param_bounds=bounds,
            base_options=base_options,
            misfit_fn=None,  # default marker_offset_misfit
        )

        best_params = tuner.optimise(max_iter=max_iter, method=method)

        # Sensitivity from history
        sensitivity = tuner.parameter_sensitivity()

        # Best misfit
        best_entry = tuner.best_result()
        convergence = []
        if tuner.history:
            _, cum_best = tuner.convergence_curve()
            convergence = cum_best.tolist()[-10:]  # last 10 points

        return {
            "status": "ok",
            "best_params": best_params,
            "best_misfit": best_entry["misfit"] if best_entry else None,
            "sensitivity": sensitivity,
            "convergence_tail": convergence,
            "iterations": len(tuner.history),
            "recommendation": (
                f"Optimal: " + ", ".join(
                    f"{k}={v:.3f}" for k, v in best_params.items()
                )
            ),
        }
    except HTTPException:
        raise
    except Exception as e:
        log.exception("Auto-tune failed")
        raise HTTPException(500, f"Auto-tune error: {e}")
