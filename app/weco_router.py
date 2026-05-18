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
    1. List WellboreTrajectoryRepresentation resources in dataspace
    2. For each trajectory: get arrays (XYZ, MD, properties)
    3. Build WeCo Well objects
    4. Return WellList
    """
    from . import osdu
    from weco.data import Well, WellList

    ds_enc = urllib.parse.quote(dataspace, safe="")
    traj_type = "resqml20.obj_WellboreTrajectoryRepresentation"

    # Step 1: list trajectories
    resources = await osdu.list_resources(token, ds_enc, traj_type)
    if not resources:
        raise HTTPException(404, f"No wells found in dataspace '{dataspace}'")

    wells = []
    for res in resources:
        uuid = res.get("UUID") or res.get("Uuid") or ""
        name = res.get("Citation", {}).get("Title") or res.get("Title") or uuid[:8]

        try:
            # Step 2: get array data for this trajectory
            arrays_meta = await osdu.list_arrays(token, ds_enc, traj_type, uuid)
            
            # Read the geometry (control points)
            points = None
            mds = None
            for arr in arrays_meta:
                path = arr.get("PathInResource") or arr.get("path") or ""
                if "Geometry" in path or "ControlPoints" in path or "controlPoints" in path:
                    arr_data = await osdu.read_array(
                        token, ds_enc, traj_type, uuid, path_in_resource=path)
                    values = arr_data.get("values") or arr_data.get("Values") or []
                    if values:
                        points = np.array(values, dtype=np.float64).reshape(-1, 3)
                elif "MdValues" in path or "md" in path.lower():
                    arr_data = await osdu.read_array(
                        token, ds_enc, traj_type, uuid, path_in_resource=path)
                    values = arr_data.get("values") or arr_data.get("Values") or []
                    if values:
                        mds = np.array(values, dtype=np.float64)

            # Build WeCo Well
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
                # Compute MD from cumulative distance
                diffs = np.diff(points, axis=0)
                segs = np.sqrt(np.sum(diffs ** 2, axis=1))
                w.data["Depth"] = list(np.concatenate([[0.0], np.cumsum(segs)]))

            wells.append(w)
            log.info(f"  Imported well '{name}': {w.size} pts")

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
def weco_run(req: WecoRunRequest, request: Request):
    """Run correlation on previously imported wells (in-process C++ engine)."""
    global _cached_well_list

    if _cached_well_list is None:
        raise HTTPException(400, "No wells loaded. Call /weco/import first.")

    try:
        from weco.api import _run_engine, _extract_results
        safe_opts = _apply_memory_guards(req.options, len(_cached_well_list.wells))
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
