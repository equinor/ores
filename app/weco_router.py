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

import os
import logging
import tempfile
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

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

import urllib.parse
import numpy as np


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
    trajectories = await osdu.list_resources(token, ds_enc, TRAJ_TYPE)
    if not trajectories:
        raise HTTPException(404, f"No wells found in dataspace '{dataspace}'")

    # Step 2: list frames & properties (will be matched to wells by reference)
    frames = await osdu.list_resources(token, ds_enc, FRAME_TYPE)
    cont_props = await osdu.list_resources(token, ds_enc, CONT_PROP_TYPE)
    disc_props = await osdu.list_resources(token, ds_enc, DISC_PROP_TYPE)

    # Build lookup: trajectory UUID → frame UUIDs
    # Frames reference their parent trajectory via RepresentedInterpretation or SupportingRepresentation
    traj_to_frames: dict = {}
    frame_by_uuid: dict = {}
    for fr in frames:
        fr_uuid = fr.get("UUID") or fr.get("Uuid") or ""
        frame_by_uuid[fr_uuid] = fr
        # RESQML links frame→trajectory via title naming convention or reference
        # Common patterns: frame title = "well_name frame" or explicit ref
        parent_ref = _extract_parent_uuid(fr)
        if parent_ref:
            traj_to_frames.setdefault(parent_ref, []).append(fr_uuid)

    # Build lookup: frame UUID → property UUIDs
    frame_to_cont: dict = {}
    frame_to_disc: dict = {}
    for prop in cont_props:
        p_uuid = prop.get("UUID") or prop.get("Uuid") or ""
        parent = _extract_parent_uuid(prop)
        if parent:
            frame_to_cont.setdefault(parent, []).append((p_uuid, prop))
    for prop in disc_props:
        p_uuid = prop.get("UUID") or prop.get("Uuid") or ""
        parent = _extract_parent_uuid(prop)
        if parent:
            frame_to_disc.setdefault(parent, []).append((p_uuid, prop))

    # If no explicit parent references found, try matching by title prefix
    if not traj_to_frames:
        _match_by_title(trajectories, frames, traj_to_frames, frame_by_uuid)
    if not frame_to_cont and not frame_to_disc:
        _match_props_by_title(frames, cont_props, disc_props, frame_to_cont, frame_to_disc)

    wells = []
    for res in trajectories:
        traj_uuid = res.get("UUID") or res.get("Uuid") or ""
        name = res.get("Citation", {}).get("Title") or res.get("Title") or traj_uuid[:8]

        try:
            # Read trajectory arrays (geometry)
            arrays_meta = await osdu.list_arrays(token, ds_enc, TRAJ_TYPE, traj_uuid)

            points = None
            mds = None
            for arr in arrays_meta:
                path = arr.get("PathInResource") or arr.get("path") or ""
                if "Geometry" in path or "ControlPoints" in path or "controlPoints" in path:
                    arr_data = await osdu.read_array(
                        token, ds_enc, TRAJ_TYPE, traj_uuid, path_in_resource=path)
                    values = arr_data.get("values") or arr_data.get("Values") or []
                    if values:
                        points = np.array(values, dtype=np.float64).reshape(-1, 3)
                elif "MdValues" in path or "md" in path.lower():
                    arr_data = await osdu.read_array(
                        token, ds_enc, TRAJ_TYPE, traj_uuid, path_in_resource=path)
                    values = arr_data.get("values") or arr_data.get("Values") or []
                    if values:
                        mds = np.array(values, dtype=np.float64)

            # Build Well geometry
            w = Well()
            w.name = name

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
                    prop_name = (prop_meta.get("Citation", {}).get("Title")
                                 or prop_meta.get("Title") or p_uuid[:8])
                    try:
                        p_arrays = await osdu.list_arrays(
                            token, ds_enc, CONT_PROP_TYPE, p_uuid)
                        for pa in p_arrays:
                            pa_path = pa.get("PathInResource") or pa.get("path") or ""
                            if "Values" in pa_path or "values" in pa_path or "PatchOf" in pa_path:
                                arr_data = await osdu.read_array(
                                    token, ds_enc, CONT_PROP_TYPE, p_uuid,
                                    path_in_resource=pa_path)
                                vals = arr_data.get("values") or arr_data.get("Values") or []
                                if vals:
                                    # Resample to well grid if lengths differ
                                    log_vals = _resample_to_well(
                                        vals, frame_mds, w.size, w.data.get("Depth"))
                                    w.data[prop_name] = log_vals
                                    break
                    except Exception as e:
                        log.debug(f"  Skip property '{prop_name}' for '{name}': {e}")

                # Read discrete properties (regions)
                for p_uuid, prop_meta in frame_to_disc.get(fr_uuid, []):
                    prop_name = (prop_meta.get("Citation", {}).get("Title")
                                 or prop_meta.get("Title") or p_uuid[:8])
                    try:
                        p_arrays = await osdu.list_arrays(
                            token, ds_enc, DISC_PROP_TYPE, p_uuid)
                        for pa in p_arrays:
                            pa_path = pa.get("PathInResource") or pa.get("path") or ""
                            if "Values" in pa_path or "values" in pa_path or "PatchOf" in pa_path:
                                arr_data = await osdu.read_array(
                                    token, ds_enc, DISC_PROP_TYPE, p_uuid,
                                    path_in_resource=pa_path)
                                vals = arr_data.get("values") or arr_data.get("Values") or []
                                if vals:
                                    # Convert discrete values to WeCo region format
                                    # (start_idx, end_idx, value) tuples
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
    """Fallback: match frames to trajectories by title prefix."""
    traj_names = {}
    for t in trajectories:
        uid = t.get("UUID") or t.get("Uuid") or ""
        title = t.get("Citation", {}).get("Title") or t.get("Title") or ""
        if title:
            traj_names[title.lower().split()[0]] = uid

    for fr in frames:
        fr_uuid = fr.get("UUID") or fr.get("Uuid") or ""
        fr_title = fr.get("Citation", {}).get("Title") or fr.get("Title") or ""
        prefix = fr_title.lower().split()[0] if fr_title else ""
        if prefix in traj_names:
            traj_to_frames.setdefault(traj_names[prefix], []).append(fr_uuid)


def _match_props_by_title(frames, cont_props, disc_props, frame_to_cont, frame_to_disc):
    """Fallback: match properties to frames by title prefix."""
    frame_names = {}
    for fr in frames:
        uid = fr.get("UUID") or fr.get("Uuid") or ""
        title = fr.get("Citation", {}).get("Title") or fr.get("Title") or ""
        if title:
            frame_names[title.lower().split()[0]] = uid

    for prop in cont_props:
        p_uuid = prop.get("UUID") or prop.get("Uuid") or ""
        title = prop.get("Citation", {}).get("Title") or prop.get("Title") or ""
        prefix = title.lower().split()[0] if title else ""
        if prefix in frame_names:
            frame_to_cont.setdefault(frame_names[prefix], []).append((p_uuid, prop))

    for prop in disc_props:
        p_uuid = prop.get("UUID") or prop.get("Uuid") or ""
        title = prop.get("Citation", {}).get("Title") or prop.get("Title") or ""
        prefix = title.lower().split()[0] if title else ""
        if prefix in frame_names:
            frame_to_disc.setdefault(frame_names[prefix], []).append((p_uuid, prop))


async def _read_frame_mds(token: str, ds_enc: str, frame_type: str, frame_uuid: str):
    """Read MD values from a WellboreFrameRepresentation."""
    from . import osdu
    try:
        arrays = await osdu.list_arrays(token, ds_enc, frame_type, frame_uuid)
        for arr in arrays:
            path = arr.get("PathInResource") or arr.get("path") or ""
            if "NodeMd" in path or "nodeMd" in path or "MdValues" in path or "md" in path.lower():
                arr_data = await osdu.read_array(
                    token, ds_enc, frame_type, frame_uuid, path_in_resource=path)
                vals = arr_data.get("values") or arr_data.get("Values") or []
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
        from weco.api import __version__ as weco_version
        from weco.ext import ProjectExt
        # Quick sanity: can we instantiate the engine?
        _p = ProjectExt()
        return WecoStatusResponse(connected=True, version=weco_version, engine=True)
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


@router.post("/run")
async def weco_run(req: WecoRunRequest, request: Request):
    """Run correlation on previously imported wells.

    Auto-routes to Radix job component for large datasets (>WECO_JOB_WELL_THRESHOLD wells).
    """
    global _cached_well_list

    if _cached_well_list is None:
        raise HTTPException(400, "No wells loaded. Call /weco/import first.")

    n_wells = len(_cached_well_list.wells)

    # Auto-route large datasets to job component
    if n_wells > _JOB_WELL_THRESHOLD:
        log.info(f"Auto-routing {n_wells} wells to job component (threshold={_JOB_WELL_THRESHOLD})")
        return await weco_run_job(req, request)

    try:
        from weco.api import _run_engine, _extract_results
        safe_opts = _apply_memory_guards(req.options, n_wells)
        rf, data, elapsed = _run_engine(_cached_well_list, safe_opts)
        results = _extract_results(rf, data, req.n_best)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Correlation engine error: {e}")

    well_names = [w.name for w in _cached_well_list.wells]
    return {
        "status": "ok",
        "elapsed_ms": round(elapsed, 2),
        "n_wells": len(well_names),
        "well_names": well_names,
        "n_results": len(results),
        "results": [r.model_dump() if hasattr(r, "model_dump") else r.dict()
                    for r in results],
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
    """List available demo datasets."""
    try:
        from weco.api import list_demos
        return list_demos()
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/run/demo")
def weco_run_demo(demo_id: str, n_best: int = 5):
    """Run a demo dataset on the WeCo engine (in-process)."""
    try:
        from weco.api import run_demo, DemoRunRequest
        req = DemoRunRequest(demo_id=demo_id, n_best=n_best)
        return run_demo(req)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/strat-column")
async def weco_strat_column(request: Request):
    """Fetch stratigraphic column from active RDDMS instance.

    Uses ORES's existing /strat infrastructure (no gocad).
    """
    token = _get_token(request)
    if not token:
        raise HTTPException(400, "Not authenticated.")

    # Redirect to the existing ORES strat search (already implemented)
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
            }
            for w in wl.wells
        ],
    }
