"""
ORES ↔ WeCo integration router  (in-process)
==============================================

Direct in-process calls to the WeCo correlation engine.
WeCo is installed as a Python package (with compiled C++ engine)
inside the ORES container — no separate microservice needed.

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


# Cached well list (server process memory — single worker)
_cached_well_list = None


# ═══════════════════════════════════════════════════════════════════════════
#  RDDMS → WeCo Well conversion (uses ORES native osdu.py, no gocad)
# ═══════════════════════════════════════════════════════════════════════════

import re as _re
import urllib.parse
import uuid as uuid_mod
import numpy as np

# Deterministic UUID namespace — must match demo/ingest_weco_demos.py
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
    dataspace = os.environ.get("DEFAULT_DATASPACE", "maap/drogon")
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

    dataspace = req.dataspace or os.environ.get("DEFAULT_DATASPACE", "default")

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


def _apply_memory_guards(options: dict, n_wells: int) -> dict:
    """Enforce safe parameter limits to prevent OOM on Radix (2Gi container)."""
    opts = dict(options)
    # Force single-thread to limit peak memory (one correlator buffer at a time)
    opts.setdefault("thread", 1)
    # Scale limits by dataset size
    if n_wells > 50:
        opts["max-cor"] = min(int(opts.get("max-cor", 20)), 20)
        opts["nbr-cor"] = min(int(opts.get("nbr-cor", 3)), 5)
        opts.setdefault("band-width", 30)
    elif n_wells > 10:
        opts["max-cor"] = min(int(opts.get("max-cor", 30)), 30)
        opts["nbr-cor"] = min(int(opts.get("nbr-cor", 5)), 10)
        opts.setdefault("band-width", 30)
    else:
        opts["max-cor"] = min(int(opts.get("max-cor", 50)), 50)
        opts["nbr-cor"] = min(int(opts.get("nbr-cor", 10)), 20)
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
        # Region/zone data — expand RLE (value, start, count) to per-sample
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


@router.post("/run")
async def weco_run(req: WecoRunRequest, request: Request):
    """Run correlation on previously imported wells.

    Auto-routes to Radix job component for large datasets (>WECO_JOB_WELL_THRESHOLD wells).
    """
    global _cached_well_list

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
        return await weco_run_job(req, request)

    try:
        from weco.api import _run_engine, _extract_results
        safe_opts = _apply_memory_guards(req.options, n_wells)
        log.info(f"Running correlation: {n_wells} wells, options={safe_opts}, n_best={req.n_best}")
        rf, data, elapsed = _run_engine(wl, safe_opts)
        results = _extract_results(rf, data, req.n_best)
    except HTTPException:
        raise
    except Exception as e:
        log.exception(f"Correlation engine error: options={req.options}, n_wells={n_wells}")
        raise HTTPException(500, f"Correlation engine error: {e}")

    well_names = [w.name for w in wl.wells]

    # Include plot data for visualization
    wells_plot_data = _build_wells_plot_data(wl)

    return {
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
async def weco_run_job(req: WecoRunRequest, request: Request):
    """Submit correlation to the Radix job component (async, for large datasets).

    Automatically used when well count exceeds threshold, or can be called
    explicitly for heavy workloads that need more memory/CPU.
    """
    global _cached_well_list

    if _cached_well_list is None:
        raise HTTPException(400, "No wells loaded. Call /weco/import first.")

    n_wells = len(_cached_well_list.wells)

    try:
        import json
        import httpx

        # Serialize well data for the job
        wells_json = json.dumps(_cached_well_list.to_dict())

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
        # Job component not available — fall back to in-process with guards
        log.warning(f"Job scheduler unavailable ({e}), falling back to in-process")
        from weco.api import _run_engine, _extract_results
        safe_opts = _apply_memory_guards(req.options, n_wells)
        rf, data, elapsed = _run_engine(_cached_well_list, safe_opts)
        results = _extract_results(rf, data, req.n_best)
        return {
            "status": "ok",
            "mode": "in-process-fallback",
            "n_wells": n_wells,
            "elapsed_ms": round(elapsed, 2),
            "n_results": len(results),
            "results": [r.model_dump() if hasattr(r, "model_dump") else r.dict()
                        for r in results],
            "options_used": safe_opts,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Job dispatch error: {e}")


@router.post("/export")
async def weco_export(request: Request):
    """Export last correlation results back to RDDMS as WellboreMarkerFrame.

    Uses ORES's native osdu.py (no gocad dependency).
    """
    global _cached_well_list

    token = _get_token(request)
    if not token:
        raise HTTPException(400, "No auth token. Log in first.")

    if _cached_well_list is None:
        raise HTTPException(400, "No correlation results. Run correlation first.")

    # TODO: implement RDDMS export using app/osdu.py put_resources()
    # For now, return a placeholder acknowledging the limitation
    return {
        "status": "pending",
        "message": "Export to RDDMS not yet implemented via native client. "
                   "Results are available in the response of /weco/run.",
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

    dataspace = req.dataspace or os.environ.get("DEFAULT_DATASPACE", "default")

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

    Returns wells with their available logs, regions, sizes — so the UI can
    present a well/log selection matrix before running.
    """
    global _cached_well_list
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

        return {
            "demo_id": demo_id,
            "title": demo.title,
            "n_wells": len(wells),
            "wells": wells,
            "all_data_names": all_data_names,
            "all_region_names": all_region_names,
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
    global _cached_well_list
    try:
        from weco.api import run_demo, DemoRunRequest, _load_well_list, list_demos
        from weco.api import _suggest_defaults_for_wells, _run_engine, _extract_results

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

        # Suggest + run
        options, reasoning = _suggest_defaults_for_wells(wl)
        rf, data, elapsed = _run_engine(wl, options)
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
