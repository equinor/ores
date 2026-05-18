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


def _rddms_url(request: Request) -> str:
    """Get the RDDMS/OSDU base URL from session or env."""
    try:
        from .instances import get_active
        instance = get_active(request)
        if instance:
            return instance.get("base_url", "") + "/api/reservoir-ddms/v2"
    except Exception:
        pass
    return os.environ.get("RDDMS_URL", "")


def _session_well_file() -> str:
    """Path to the session well list file."""
    return os.path.join(WECO_SESSION_DIR, "wells.txt")


# Cached well list (server process memory — single worker)
_cached_well_list = None


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
def weco_import(req: WecoImportRequest, request: Request):
    """Import wells from the active RDDMS instance into WeCo (in-process)."""
    global _cached_well_list

    token = _get_token(request)
    rddms_url = _rddms_url(request)

    if not rddms_url:
        raise HTTPException(400, "No RDDMS URL configured. Set active instance first.")
    if not token:
        raise HTTPException(401, "No access token. Log in to OSDU first.")

    try:
        from weco.rddms import rddms_import_wells
        wl = rddms_import_wells(rddms_url, token, req.dataspace or "default")
    except ImportError as e:
        raise HTTPException(501, f"RESQML support not available: {e}")
    except Exception as e:
        raise HTTPException(500, f"RDDMS import failed: {e}")

    _cached_well_list = wl

    # Collect metadata
    all_meta = {}
    for w in wl.wells:
        if hasattr(w, "meta") and w.meta:
            all_meta[w.name] = w.meta

    return {
        "well_count": wl.nbr_wells(),
        "well_names": [w.name for w in wl.wells],
        "data_names": list(wl.get_data_names()),
        "region_names": list(wl.get_region_names()),
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


@router.post("/run")
def weco_run(req: WecoRunRequest, request: Request):
    """Run correlation on previously imported wells (in-process C++ engine)."""
    global _cached_well_list

    if _cached_well_list is None:
        raise HTTPException(400, "No wells loaded. Call /weco/import first.")

    try:
        from weco.api import _run_engine, _extract_results
        rf, data, elapsed = _run_engine(_cached_well_list, req.options)
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
def weco_export(request: Request):
    """Export last correlation results back to RDDMS."""
    token = _get_token(request)
    rddms_url = _rddms_url(request)

    if not rddms_url or not token:
        raise HTTPException(400, "No RDDMS connection. Log in first.")

    try:
        from weco.rddms import rddms_export_results
        summary = rddms_export_results(
            rddms_url, token, "default",
            project_path=WECO_SESSION_DIR,
            export_markers=True,
            export_zonation=True,
        )
        return {"status": "ok", "export": summary}
    except ImportError as e:
        raise HTTPException(501, f"RESQML support not available: {e}")
    except Exception as e:
        raise HTTPException(500, f"Export failed: {e}")


@router.post("/correlate")
def weco_full_workflow(req: WecoFullRequest, request: Request):
    """Full workflow: import → suggest → correlate → export (all in-process)."""
    global _cached_well_list

    token = _get_token(request)
    rddms_url = _rddms_url(request)

    if not rddms_url:
        raise HTTPException(400, "No RDDMS URL. Set active OSDU instance.")
    if not token:
        raise HTTPException(401, "Not authenticated.")

    # Step 1: Import wells
    try:
        from weco.rddms import rddms_import_wells, rddms_export_results
        from weco.api import _suggest_defaults_for_wells, _run_engine, _extract_results

        wl = rddms_import_wells(rddms_url, token, req.dataspace or "default")
        _cached_well_list = wl
    except ImportError as e:
        raise HTTPException(501, f"RESQML support not available: {e}")
    except Exception as e:
        raise HTTPException(500, f"RDDMS import failed: {e}")

    import_summary = {
        "well_count": wl.nbr_wells(),
        "well_names": [w.name for w in wl.wells],
    }

    # Step 2: Suggest defaults + merge with user options
    try:
        suggested, reasoning = _suggest_defaults_for_wells(wl)
        merged_options = {**suggested, **req.options}
    except Exception:
        merged_options = req.options

    # Step 3: Run correlation
    try:
        rf, data, elapsed = _run_engine(wl, merged_options)
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

    # Step 4: Export back to RDDMS
    export_summary = {}
    if req.export_markers:
        try:
            export_summary = rddms_export_results(
                rddms_url, token, req.dataspace or "default",
                project_path=WECO_SESSION_DIR,
                export_markers=True,
                export_zonation=True,
            )
        except Exception as e:
            log.warning(f"Export failed (non-fatal): {e}")
            export_summary = {"error": str(e)}

    return {
        "import": import_summary,
        "correlation": run_summary,
        "export": export_summary,
        "options_used": merged_options,
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
def weco_strat_column(request: Request):
    """Fetch stratigraphic column from active RDDMS instance."""
    token = _get_token(request)
    rddms_url = _rddms_url(request)

    if not rddms_url or not token:
        raise HTTPException(400, "No RDDMS connection.")

    try:
        from weco.rddms import rddms_import_strat_column
        result = rddms_import_strat_column(rddms_url, token, "default")
        return result
    except ImportError as e:
        raise HTTPException(501, f"RESQML not available: {e}")
    except Exception as e:
        raise HTTPException(500, str(e))


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
