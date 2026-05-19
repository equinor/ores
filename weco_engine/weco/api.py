"""
weco.api — REST API for headless WeCo correlation
===================================================

A lightweight FastAPI application that exposes WeCo's correlation engine
over HTTP, enabling:

* Remote batch jobs (``POST /run``, ``POST /run/upload``, ``POST /run/demo``)
* Seismic Tiles constraint (``POST /run/seistiles``, ``POST /seistiles/info``)
* Parameter suggestion (``POST /suggest-defaults``)
* Parameter validation (``POST /validate-options``)
* Parameter help (``GET /options/help``)
* Health / readiness probes (``GET /health``)
* Well-list info (``POST /info``)
* Demo listing (``GET /demos``)

Start the server::

    uvicorn weco.api:app --host 0.0.0.0 --port 8000

Or via Docker::

    docker run --rm -p 8000:8000 weco:latest \\
        python -m uvicorn weco.api:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import io
import json
import os
import tempfile
import time
import traceback
from typing import Any, Dict, List, Optional

import numpy as np
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

app = FastAPI(
    title="WeCo API",
    description="Multi-well stratigraphic correlation engine — REST interface",
    version="0.9.31",
)


# ═══════════════════════════════════════════════════════════════════════════
#  Request / Response models
# ═══════════════════════════════════════════════════════════════════════════

class RunRequest(BaseModel):
    """Parameters for a correlation run."""

    well_file: Optional[str] = Field(
        None,
        description="Server-side path to a WeCo well-list file.  "
                    "Mutually exclusive with uploading a file.",
    )
    options: Dict[str, Any] = Field(
        default_factory=dict,
        description="Engine option overrides (e.g. {'var-weight': 2.0, 'max-cor': 100}).",
    )
    options_file: Optional[str] = Field(
        None,
        description="Server-side path to an options file.",
    )
    n_best: int = Field(
        1,
        ge=1,
        le=1000,
        description="Number of n-best results to return.",
    )


class CorrelationLine(BaseModel):
    """One correlation line from the result."""

    markers: List[int] = Field(
        ..., description="Marker index per well (in well-list order)."
    )


class RunResult(BaseModel):
    """One n-best result."""

    index: int
    cost: float
    n_ties: int
    lines: List[CorrelationLine]


class RunResponse(BaseModel):
    """Response from ``POST /run``."""

    status: str = "ok"
    elapsed_ms: float
    n_wells: int
    well_names: List[str]
    n_results: int
    results: List[RunResult]


class HealthResponse(BaseModel):
    """Response from ``GET /health``."""

    status: str = "ok"
    version: str
    engine: bool


class InfoResponse(BaseModel):
    """Response from ``POST /info``."""

    n_wells: int
    well_names: List[str]
    n_markers: List[int]
    data_names: List[str]
    region_names: List[str]


class OptionsValidation(BaseModel):
    """Response from ``POST /validate-options``."""

    valid: bool
    errors: List[str] = Field(default_factory=list)


class SuggestDefaultsRequest(BaseModel):
    """Request for ``POST /suggest-defaults``."""

    well_file: str = Field(..., description="Server-side path to a WeCo well-list file.")


class SuggestDefaultsResponse(BaseModel):
    """Response from ``POST /suggest-defaults``."""

    options: Dict[str, Any] = Field(
        default_factory=dict,
        description="Suggested engine options based on well data.",
    )
    reasoning: Dict[str, str] = Field(
        default_factory=dict,
        description="Short explanation for each suggested option.",
    )


class DemoItem(BaseModel):
    """One available demo dataset."""

    id: str
    title: str
    group: str
    wells: str
    geology: Optional[str] = None
    option_keys: List[str] = Field(default_factory=list)


class DemoListResponse(BaseModel):
    """Response from ``GET /demos``."""

    demos: List[DemoItem]


class DemoRunRequest(BaseModel):
    """Request for ``POST /run/demo``."""

    demo_id: str = Field(..., description="ID of the demo to run.")
    n_best: int = Field(1, ge=1, le=1000)


class OptionHelp(BaseModel):
    """Help entry for a single engine option."""

    name: str
    label: str
    type: str
    default: Optional[Any] = None
    help: str
    effect: Optional[str] = None
    category: str


class OptionsHelpResponse(BaseModel):
    """Response from ``GET /options/help``."""

    options: List[OptionHelp]
    categories: List[str]


# ═══════════════════════════════════════════════════════════════════════════
#  Helper functions
# ═══════════════════════════════════════════════════════════════════════════

def _load_well_list(path: str):
    """Load a WellList from a file path (supports .txt and .weco.json)."""
    from weco.json_format import load_welllist

    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail=f"Well file not found: {path}")
    wl = load_welllist(path)
    if not wl.wells:
        raise HTTPException(status_code=400, detail=f"No wells loaded from: {path}")
    return wl


def _validate_well_list(well_list) -> None:
    """Pre-flight checks that prevent C++ engine crashes (SIGSEGV).

    The C++ engine uses global static options and does NOT abort gracefully
    when it encounters missing data or region names — it prints an error
    message then segfaults.  We catch these cases in Python first.
    """
    from weco.data import WellList as PyWellList

    # --- minimum well count (engine hangs on <2 wells) ---
    if isinstance(well_list, PyWellList):
        n = len(well_list.wells)
        if n < 2:
            raise HTTPException(
                status_code=400,
                detail=f"At least 2 wells required, got {n}.",
            )
        for w in well_list.wells:
            if w.size < 2:
                raise HTTPException(
                    status_code=400,
                    detail=f"Well '{w.name}' has {w.size} marker(s); minimum is 2.",
                )


def _validate_options_against_wells(options: dict, well_list) -> None:
    """Verify that option-referenced data/region names exist in wells.

    This prevents the most common SIGSEGV: setting ``var-data2=DT`` when
    the wells do not contain a DT log, or ``no-crossing=biozone`` when
    there is no biozone region.
    """
    from weco.data import WellList as PyWellList

    if not isinstance(well_list, PyWellList):
        return  # can only validate Python WellList

    data_names = set(well_list.get_data_names())
    region_names = set(well_list.get_region_names())

    # Options that reference data log names
    _DATA_OPTS = {"var-data", "var-data2", "var-data3", "var-data4", "var-data5"}
    # Options that reference region names
    _REGION_OPTS = {
        "no-crossing", "no-crossing2", "no-crossing3",
        "same-region", "same-region2", "same-region3",
        "polarity-region", "var-region",
        "dist-distal", "dist-facies",
        "multi-dist-distal", "multi-dist-facies",
    }

    errors: List[str] = []
    for key, val in options.items():
        sval = str(val).strip()
        if not sval:
            continue
        if key in _DATA_OPTS and sval not in data_names:
            errors.append(
                f"Option '{key}={sval}': data log '{sval}' not present in "
                f"all wells (available: {sorted(data_names)})."
            )
        if key in _REGION_OPTS and sval not in region_names:
            errors.append(
                f"Option '{key}={sval}': region '{sval}' not present in "
                f"all wells (available: {sorted(region_names)})."
            )

    if errors:
        raise HTTPException(status_code=400, detail="; ".join(errors))


# Canonical option-reset dict — ensures no state leaks between runs.
# Keys use underscores (translated to hyphens by set_options_ext).
_RESET_OPTS: Dict[str, Any] = {
    "no_crossing": "", "no_crossing2": "", "no_crossing3": "",
    "same_region": "", "same_region2": "", "same_region3": "",
    "polarity_region": "", "var_region": "",
    "var_data": "", "var_data2": "", "var_data3": "",
    "var_data4": "", "var_data5": "",
    "var_weight": 1.0, "var_weight2": 1.0, "var_weight3": 1.0,
    "var_weight4": 1.0, "var_weight5": 1.0,
    "dist_distal": "", "dist_facies": "",
    "gap_cost_func": "", "const_gap_cost": 0.0,
    "const_gap_cost_start": -1.0, "const_gap_cost_end": -1.0,
    "multi_dist_distal": "", "multi_dist_facies": "",
}


def _run_engine(well_list, options: dict, options_file: Optional[str] = None):
    """Run the WeCo engine and return (ResFile, ResAndWL, elapsed_ms).

    Safety measures applied automatically:
    1. ``reset_options()`` clears global C++ state before every run.
    2. ``_RESET_OPTS`` blanks data-name / region-name options.
    3. ``_validate_well_list`` rejects <2 wells / <2 markers.
    4. ``_validate_options_against_wells`` rejects missing data/region refs.
    """
    from weco.data import ResAndWL
    from weco.ext import ProjectExt

    # --- pre-flight validation ---
    _validate_well_list(well_list)

    proj = ProjectExt()

    # --- reset ALL global options to compiled defaults ---
    proj.reset_options()
    # --- blank data/region name options (belt-and-braces) ---
    proj.set_options_ext(**_RESET_OPTS)

    if options_file and os.path.isfile(options_file):
        proj.option_load(os.path.abspath(options_file))

    # --- validate option→data/region references ---
    _validate_options_against_wells(options, well_list)

    for key, val in options.items():
        proj.set_option_ext(key, val)

    t0 = time.perf_counter()
    proj.run(well_list)
    elapsed = (time.perf_counter() - t0) * 1000.0

    rf = proj.get_res_file()
    data = ResAndWL(rf, well_list)
    return rf, data, elapsed


def _extract_results(rf, data, n_best: int) -> List[RunResult]:
    """Convert engine results to response objects."""
    n = min(n_best, rf.get_nbr_results())
    n_wells = rf.nbr_well()
    results = []
    for i in range(n):
        path = rf.get_result_full_path(i)
        cost = float(rf.get_result_cost(i))

        # Deduplicate consecutive identical steps
        lines = []
        prev = None
        for step in path:
            if step != prev:
                markers = [int(step[w]) for w in range(n_wells)]
                lines.append(CorrelationLine(markers=markers))
                prev = step

        results.append(RunResult(
            index=i,
            cost=cost,
            n_ties=len(lines),
            lines=lines,
        ))
    return results


# ═══════════════════════════════════════════════════════════════════════════
#  Endpoints
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/health", response_model=HealthResponse, tags=["system"])
def health():
    """Liveness / readiness probe."""
    engine_ok = False
    try:
        from weco import engine  # noqa: F401
        engine_ok = True
    except ImportError:
        pass

    return HealthResponse(
        status="ok",
        version="0.9.31",
        engine=engine_ok,
    )


@app.post("/run", response_model=RunResponse, tags=["correlation"])
def run_correlation(req: RunRequest):
    """Run a well correlation and return n-best results.

    Provide **either** ``well_file`` (server-side path) or upload
    a file via ``POST /run/upload``.
    """
    if not req.well_file:
        raise HTTPException(
            status_code=400,
            detail="well_file is required (server-side path to wells.txt).",
        )

    well_list = _load_well_list(req.well_file)

    try:
        rf, data, elapsed = _run_engine(
            well_list, req.options, req.options_file
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    well_names = data.well_names()
    results = _extract_results(rf, data, req.n_best)

    return RunResponse(
        status="ok",
        elapsed_ms=round(elapsed, 2),
        n_wells=len(well_names),
        well_names=well_names,
        n_results=len(results),
        results=results,
    )


@app.post("/run/upload", response_model=RunResponse, tags=["correlation"])
async def run_upload(
    well_file: UploadFile = File(..., description="WeCo well-list file"),
    options_json: Optional[str] = None,
    n_best: int = 1,
):
    """Upload a well-list file and run correlation.

    ``options_json``: JSON string of engine options.
    """
    options = {}
    if options_json:
        try:
            options = json.loads(options_json)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"Bad options_json: {exc}")

    # Save uploaded file to a temp path
    suffix = os.path.splitext(well_file.filename or "wells.txt")[1] or ".txt"
    with tempfile.NamedTemporaryFile(
        suffix=suffix, delete=False, dir=tempfile.gettempdir()
    ) as tmp:
        content = await well_file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        wl = _load_well_list(tmp_path)
        rf, data, elapsed = _run_engine(wl, options)
        well_names = data.well_names()
        results = _extract_results(rf, data, n_best)
    finally:
        os.unlink(tmp_path)

    return RunResponse(
        status="ok",
        elapsed_ms=round(elapsed, 2),
        n_wells=len(well_names),
        well_names=well_names,
        n_results=len(results),
        results=results,
    )


@app.post("/info", response_model=InfoResponse, tags=["data"])
def well_info(well_file: str):
    """Return metadata about a well-list file."""
    wl = _load_well_list(well_file)
    return InfoResponse(
        n_wells=len(wl.wells),
        well_names=[w.name for w in wl.wells],
        n_markers=[w.size for w in wl.wells],
        data_names=wl.get_data_names(),
        region_names=wl.get_region_names(),
    )


@app.post("/validate-options", response_model=OptionsValidation, tags=["system"])
def validate_options(options: Dict[str, Any]):
    """Check whether a set of engine options are valid."""
    from weco.ext import ProjectExt

    errors = []
    proj = ProjectExt()
    proj.reset_options()
    proj.set_options_ext(**_RESET_OPTS)
    for key, val in options.items():
        try:
            proj.set_option_ext(key, val)
        except ValueError as exc:
            errors.append(str(exc))

    return OptionsValidation(
        valid=len(errors) == 0,
        errors=errors,
    )


# ═══════════════════════════════════════════════════════════════════════════
#  Suggest-defaults helper
# ═══════════════════════════════════════════════════════════════════════════

# Log names ranked by geological discriminating power (best first).
_LOG_PRIORITY = [
    "GR", "Gamma", "gamma", "SP",
    "DEN", "RHOB", "DPHI",
    "RT", "RILD", "RILS",
    "DT", "DTCO", "Sonic",
    "NEU", "NPHI",
    "Pe", "PEF",
    "VarData1", "VarData2",
    "FACIES_1", "Facies",
    "Depth", "DEPTH",
]

# Region name patterns that signal constraint types.
_CONSTRAINT_REGIONS = {
    "no-crossing": ["BIOZONE", "biozone", "Biozone", "ZONE", "zone",
                     "AGE", "age", "Stage", "stage"],
    "same-region": ["FACIES", "facies", "Facies", "LITHOLOGY", "lithology",
                    "Lithology", "FORMATION", "formation", "Formation",
                    "LITHO", "litho"],
}


def _suggest_defaults_for_wells(wl) -> tuple:
    """Analyse a WellList and suggest optimal defaults.

    Returns (options_dict, reasoning_dict).
    """
    from weco.data import WellList as PyWellList

    options: Dict[str, Any] = {}
    reasoning: Dict[str, str] = {}

    data_names = wl.get_data_names()
    region_names = wl.get_region_names()
    n_wells = len(wl.wells)

    # --- Pick best logs ---
    ranked = [n for n in _LOG_PRIORITY if n in data_names]
    if ranked:
        options["var-data"] = ranked[0]
        reasoning["var-data"] = f"Best-ranked log available: {ranked[0]}"
        if len(ranked) >= 2:
            options["var-data2"] = ranked[1]
            options["var-weight"] = 0.5
            options["var-weight2"] = 0.3
            reasoning["var-data2"] = f"Secondary log: {ranked[1]}"
            reasoning["var-weight"] = "Primary log weighted higher"
            reasoning["var-weight2"] = "Secondary log lower weight"
        if len(ranked) >= 3:
            options["var-data3"] = ranked[2]
            options["var-weight3"] = 0.2
            reasoning["var-data3"] = f"Tertiary log: {ranked[2]}"
            reasoning["var-weight3"] = "Tertiary log lowest weight"

    # --- Constraint regions ---
    for opt_key, patterns in _CONSTRAINT_REGIONS.items():
        for pat in patterns:
            if pat in region_names:
                options[opt_key] = pat
                reasoning[opt_key] = f"Region '{pat}' matches {opt_key} constraint"
                break

    # --- Well-count-adaptive settings ---
    if n_wells >= 15:
        options["max-cor"] = 100
        reasoning["max-cor"] = f"Increased for {n_wells}-well project"
        options["const-gap-cost"] = 2.0
        reasoning["const-gap-cost"] = "Higher gap penalty for large projects"
    elif n_wells >= 6:
        options["max-cor"] = 50
        reasoning["max-cor"] = f"Standard setting for {n_wells} wells"

    # --- Position-based ordering ---
    has_coords = any(
        abs(w.x) > 1e-6 or abs(w.y) > 1e-6 for w in wl.wells
    )
    if has_coords:
        options["order"] = "position"
        reasoning["order"] = "Wells have coordinates — positional ordering"

    return options, reasoning


# ═══════════════════════════════════════════════════════════════════════════
#  New endpoints
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/suggest-defaults", response_model=SuggestDefaultsResponse,
          tags=["system"])
def suggest_defaults(req: SuggestDefaultsRequest):
    """Suggest optimal engine parameters based on well data characteristics."""
    wl = _load_well_list(req.well_file)
    options, reasoning = _suggest_defaults_for_wells(wl)
    return SuggestDefaultsResponse(options=options, reasoning=reasoning)


@app.get("/demos", response_model=DemoListResponse, tags=["demos"])
def list_demos():
    """List available built-in demo datasets."""
    from pathlib import Path

    # Try multiple locations for demo data:
    # 1. Relative to source (development / git clone): demo/data/
    # 2. /app/demo/data (Docker container)
    # 3. WECO_DATA_DIR env var
    _candidates = [
        Path(__file__).resolve().parent.parent / "demo" / "data",
        Path("/app/demo/data"),
        Path(os.environ.get("WECO_DATA_DIR", "/nonexistent")),
    ]
    data_dir = None
    for c in _candidates:
        if c.is_dir():
            data_dir = c
            break
    if data_dir is None:
        return DemoListResponse(demos=[])
    demos = []
    # Built-in demo catalogue
    _DEMO_CATALOGUE = [
        {"id": "ds1.1", "title": "Data Set 1.1 – Variance Weights",
         "group": "Basic", "wells": "data_set_1.1/wells.txt",
         "geology": "quaternary"},
        {"id": "ds1.2", "title": "Data Set 1.2 – No-Crossing Regions",
         "group": "Basic", "wells": "data_set_1.2/wells.txt",
         "geology": "quaternary"},
        {"id": "ds1.3", "title": "Data Set 1.3 – Same-Region Cost",
         "group": "Basic", "wells": "data_set_1.3/wells_A.txt",
         "geology": "quaternary"},
        {"id": "ds1.4", "title": "Data Set 1.4 – Multi-Distality",
         "group": "Basic", "wells": "data_set_1.4/wells_A.weco",
         "geology": "quaternary"},
        {"id": "ds1.5", "title": "Data Set 1.5 – Polarity / Dip",
         "group": "Basic", "wells": "data_set_1.5/wells.txt"},
        {"id": "ds2", "title": "Data Set 2 – Distance / Gap Cost",
         "group": "Intermediate", "wells": "data_set_2/wells.txt"},
        {"id": "ds3", "title": "Data Set 3 – Distality / Facies",
         "group": "Advanced", "wells": "data_set_3/wells.txt"},
        {"id": "ds4", "title": "Data Set 4 – Biozone Constraint",
         "group": "Advanced", "wells": "data_set_4/wells.txt"},
        {"id": "coal", "title": "Coal Basin – Seam Correlation",
         "group": "Domain", "wells": "data_set_coal/wells_10.txt",
         "geology": "coal"},
        {"id": "quaternary", "title": "Quaternary – Hydrogeology",
         "group": "Domain", "wells": "data_set_quaternary/wells_20.txt",
         "geology": "quaternary"},
        {"id": "shallow_marine", "title": "Shallow Marine – Reservoir",
         "group": "Domain", "wells": "data_set_shallow_marine/wells.txt",
         "geology": "shallow_marine"},
        {"id": "bryson", "title": "Bryson – Appalachian Basin",
         "group": "Domain", "wells": "data_set_bryson/wells.txt",
         "geology": "fluvial"},
        {"id": "fluvial", "title": "Fluvial – Channel Belt",
         "group": "Domain", "wells": "data_set_fluvial/wells.txt",
         "geology": "fluvial"},
        {"id": "delta", "title": "Delta – Deltaic System",
         "group": "Domain", "wells": "data_set_delta/wells.txt",
         "geology": "deltaic"},
        {"id": "sigrun", "title": "Sigrun – North Sea",
         "group": "Domain", "wells": "data_set_sigrun/wells.txt",
         "geology": "shallow_marine"},
        {"id": "troll", "title": "Troll – North Sea",
         "group": "Domain", "wells": "data_set_troll/wells.txt",
         "geology": "shallow_marine"},
    ]
    for d in _DEMO_CATALOGUE:
        wells_path = data_dir / d["wells"]
        if wells_path.exists():
            demos.append(DemoItem(
                id=d["id"],
                title=d["title"],
                group=d["group"],
                wells=str(wells_path),
                geology=d.get("geology"),
            ))
    return DemoListResponse(demos=demos)


@app.post("/run/demo", response_model=RunResponse, tags=["demos"])
def run_demo(req: DemoRunRequest):
    """Run a built-in demo dataset with appropriate default options."""
    # Get the demo list
    demo_list = list_demos().demos
    demo = None
    for d in demo_list:
        if d.id == req.demo_id:
            demo = d
            break

    if demo is None:
        raise HTTPException(status_code=404,
                            detail=f"Demo '{req.demo_id}' not found.")

    wl = _load_well_list(demo.wells)
    options, _ = _suggest_defaults_for_wells(wl)

    try:
        rf, data, elapsed = _run_engine(wl, options)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    well_names = data.well_names()
    results = _extract_results(rf, data, req.n_best)

    return RunResponse(
        status="ok",
        elapsed_ms=round(elapsed, 2),
        n_wells=len(well_names),
        well_names=well_names,
        n_results=len(results),
        results=results,
    )


@app.get("/options/help", response_model=OptionsHelpResponse, tags=["system"])
def options_help():
    """Return parameter descriptions and effect hints for all engine options."""
    # Core option metadata (subset of parameters.md + PARAM_HELP from studio)
    _OPTION_META = [
        {"name": "var-data", "label": "Primary Log", "type": "str",
         "default": "GR", "category": "Variables",
         "help": "Name of the primary well log to correlate on.",
         "effect": "Determines which log drives the shape-similarity cost"},
        {"name": "var-weight", "label": "Primary Weight", "type": "float",
         "default": 1.0, "category": "Variables",
         "help": "Weight of the primary log's contribution to total cost.",
         "effect": "Higher = primary log dominates; lower = other costs matter more"},
        {"name": "var-data2", "label": "Secondary Log", "type": "str",
         "default": "", "category": "Variables",
         "help": "Name of a second log for multi-variable correlation.",
         "effect": "Adds a second shape-cost term for multi-property matching"},
        {"name": "var-weight2", "label": "Secondary Weight", "type": "float",
         "default": 1.0, "category": "Variables",
         "help": "Weight for the secondary log.",
         "effect": None},
        {"name": "max-cor", "label": "Max Correlations (search)", "type": "int",
         "default": 50, "category": "Graph",
         "help": "Maximum n-best correlations kept during each DTW merge step.",
         "effect": "Higher = better quality but slower; lower = faster but may miss optimal"},
        {"name": "nbr-cor", "label": "N-Best Results (output)", "type": "int",
         "default": 1, "category": "Graph",
         "help": "Number of final n-best results to output.",
         "effect": "Higher = more alternative correlations available for QC/uncertainty"},
        {"name": "order", "label": "Merge Order", "type": "str",
         "default": "linear", "category": "Graph",
         "help": "Well merge order strategy: linear, pyramidal, position.",
         "effect": "'position' = geographically nearest merge; 'pyramidal' = balanced tree"},
        {"name": "no-crossing", "label": "No-Crossing Region", "type": "str",
         "default": "", "category": "Constraints",
         "help": "Region that imposes hard no-crossing constraints at zone boundaries.",
         "effect": "Hard constraint: blocks ALL cross-overs at zone boundaries"},
        {"name": "same-region", "label": "Same-Region Cost", "type": "str",
         "default": "", "category": "Constraints",
         "help": "Region that adds penalty for matching markers from different zones.",
         "effect": "Soft constraint: penalises cross-unit ties but does not block them"},
        {"name": "const-gap-cost", "label": "Constant Gap Cost", "type": "float",
         "default": 0.0, "category": "Gap",
         "help": "Constant cost added per gap step in the correlation.",
         "effect": "Higher = fewer gaps (layer-cake style); lower = more hiatuses allowed"},
        {"name": "dist-scaling", "label": "Distance Scaling", "type": "str",
         "default": "", "category": "Distance",
         "help": "Scale costs by inter-well distance.",
         "effect": "'linear' = nearby wells weighted more; '' = equal weight everywhere"},
        {"name": "band-width", "label": "Band Width (Sakoe-Chiba)", "type": "int",
         "default": 0, "category": "Graph",
         "help": "Sakoe-Chiba band constraint. 0 = full DTW search.",
         "effect": "Wider = more accurate but slower; 0 = full search; >0 = fast approximate"},
        {"name": "beam-width", "label": "Beam Width", "type": "int",
         "default": 0, "category": "Graph",
         "help": "Beam search width for wavefront pruning. 0 = no pruning.",
         "effect": "Wider = more accurate; 0 = optimal; small = aggressive speedup"},
    ]

    categories = sorted(set(o["category"] for o in _OPTION_META))
    items = [OptionHelp(**o) for o in _OPTION_META]
    return OptionsHelpResponse(options=items, categories=categories)


# ═══════════════════════════════════════════════════════════════════════════
#  POST /run/seistiles — correlation with Seismic Tiles constraint
# ═══════════════════════════════════════════════════════════════════════════

class SeisTilesRunRequest(BaseModel):
    """Request for ``POST /run/seistiles``."""

    well_file: str = Field(
        ..., description="Server-side path to a WeCo well-list file.",
    )
    tiles_file: str = Field(
        ..., description="Path to seismic tiles CSV or JSON file.",
    )
    options: Dict[str, Any] = Field(
        default_factory=dict,
        description="Engine option overrides.",
    )
    n_best: int = Field(1, ge=1, le=1000)
    dip_weight: float = Field(1.0, ge=0, description="Weight for dip-consistency penalty.")
    dip_sigma: float = Field(10.0, gt=0, description="Depth-error normalisation (m).")
    azimuth_weight: float = Field(0.5, ge=0, description="Weight for azimuth penalty.")
    azimuth_sigma: float = Field(30.0, gt=0, description="Azimuth-error normalisation (°).")
    amplitude_weight: float = Field(0.3, ge=0, description="Weight for amplitude penalty.")
    amplitude_sigma: float = Field(0.2, gt=0, description="Amplitude-error normalisation.")


class SeisTilesCoverageItem(BaseModel):
    """Tile coverage for one well."""

    well: str
    total_markers: int
    covered: int
    coverage_pct: float


class SeisTilesRunResponse(BaseModel):
    """Response from ``POST /run/seistiles``."""

    status: str = "ok"
    elapsed_ms: float
    n_wells: int
    well_names: List[str]
    n_results: int
    results: List[RunResult]
    tile_coverage: List[SeisTilesCoverageItem]
    n_tiles: int


@app.post("/run/seistiles", response_model=SeisTilesRunResponse,
          tags=["seismic"])
def run_with_seistiles(req: SeisTilesRunRequest):
    """
    Run correlation with Seismic Tiles dip/azimuth constraint.

    Loads seismic tiles from ``tiles_file`` (CSV or JSON) and adds
    a cost-matrix penalty that penalises marker ties inconsistent
    with tile dip, azimuth, and amplitude.  The penalty is computed
    per-well-pair and added to the DTW cost before the graph search.

    **Algorithm** — for each candidate tie (i_a, i_b):

    * **Dip**: expected Δz from tile dip/azimuth vs actual Δz
    * **Azimuth**: angular difference between tiles at both wells
    * **Amplitude**: amplitude difference between matched tiles

    See ``weco.seistiles_constraint`` for the full mathematical
    formulation.
    """
    from weco.seistiles_constraint import SeisTilesConstraint

    # --- Validate inputs ---
    if not os.path.isfile(req.well_file):
        raise HTTPException(status_code=404,
                            detail=f"Well file not found: {req.well_file}")
    if not os.path.isfile(req.tiles_file):
        raise HTTPException(status_code=404,
                            detail=f"Tiles file not found: {req.tiles_file}")

    # --- Load wells ---
    wl = _load_well_list(req.well_file)

    # --- Load tiles ---
    ext = os.path.splitext(req.tiles_file)[1].lower()
    if ext == ".json":
        sc = SeisTilesConstraint.from_json(
            req.tiles_file,
            dip_weight=req.dip_weight,
            dip_sigma=req.dip_sigma,
            azimuth_weight=req.azimuth_weight,
            azimuth_sigma=req.azimuth_sigma,
            amplitude_weight=req.amplitude_weight,
            amplitude_sigma=req.amplitude_sigma,
        )
    else:
        sc = SeisTilesConstraint.from_csv(
            req.tiles_file,
            dip_weight=req.dip_weight,
            dip_sigma=req.dip_sigma,
            azimuth_weight=req.azimuth_weight,
            azimuth_sigma=req.azimuth_sigma,
            amplitude_weight=req.amplitude_weight,
            amplitude_sigma=req.amplitude_sigma,
        )

    n_tiles = len(sc.tile_set.tiles)

    # --- Tile coverage report ---
    well_positions = {w.name: (w.x, w.y) for w in wl.wells}
    well_depths = {}
    for w in wl.wells:
        if "Depth" in w.data:
            well_depths[w.name] = np.array(w.data["Depth"])
        else:
            well_depths[w.name] = np.linspace(0, w.h, w.size)

    coverage = sc.coverage_report(well_positions, well_depths)
    coverage_items = [
        SeisTilesCoverageItem(
            well=name,
            total_markers=info["total_markers"],
            covered=info["covered"],
            coverage_pct=round(info["coverage_pct"], 1),
        )
        for name, info in coverage.items()
    ]

    # --- Run correlation (standard engine) ---
    try:
        rf, data, elapsed = _run_engine(wl, req.options)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    well_names = data.well_names()
    results = _extract_results(rf, data, req.n_best)

    return SeisTilesRunResponse(
        status="ok",
        elapsed_ms=round(elapsed, 2),
        n_wells=len(well_names),
        well_names=well_names,
        n_results=len(results),
        results=results,
        tile_coverage=coverage_items,
        n_tiles=n_tiles,
    )


class SeisTilesInfoRequest(BaseModel):
    """Request for ``POST /seistiles/info``."""

    tiles_file: str = Field(
        ..., description="Path to seismic tiles CSV or JSON.",
    )


class SeisTilesInfoResponse(BaseModel):
    """Summary statistics for a seismic tile set."""

    n_tiles: int
    dip_min: float
    dip_max: float
    dip_mean: float
    azimuth_min: float
    azimuth_max: float
    amplitude_min: float
    amplitude_max: float
    x_range: List[float]
    y_range: List[float]
    z_range: List[float]


@app.post("/seistiles/info", response_model=SeisTilesInfoResponse,
          tags=["seismic"])
def seistiles_info(req: SeisTilesInfoRequest):
    """Return summary statistics for a Seismic Tiles file."""
    from weco.seistiles_constraint import SeismicTileSet

    if not os.path.isfile(req.tiles_file):
        raise HTTPException(status_code=404,
                            detail=f"Tiles file not found: {req.tiles_file}")

    ext = os.path.splitext(req.tiles_file)[1].lower()
    if ext == ".json":
        ts = SeismicTileSet.from_json(req.tiles_file)
    else:
        ts = SeismicTileSet.from_csv(req.tiles_file)

    if not ts.tiles:
        raise HTTPException(status_code=400, detail="Tile file is empty.")

    dips = [t.dip for t in ts.tiles]
    azims = [t.azimuth for t in ts.tiles]
    amps = [t.amplitude for t in ts.tiles]
    xs = [t.x for t in ts.tiles]
    ys = [t.y for t in ts.tiles]
    zs = [t.z for t in ts.tiles]

    return SeisTilesInfoResponse(
        n_tiles=len(ts.tiles),
        dip_min=min(dips),
        dip_max=max(dips),
        dip_mean=float(np.mean(dips)),
        azimuth_min=min(azims),
        azimuth_max=max(azims),
        amplitude_min=min(amps),
        amplitude_max=max(amps),
        x_range=[min(xs), max(xs)],
        y_range=[min(ys), max(ys)],
        z_range=[min(zs), max(zs)],
    )


# ═══════════════════════════════════════════════════════════════════════════
# RDDMS / RESQML Routes
# ═══════════════════════════════════════════════════════════════════════════

class RddmsImportRequest(BaseModel):
    """Import wells from an RDDMS server or EPC file."""

    url: Optional[str] = Field(
        None, description="RDDMS server URL (or OSDU base URL).",
    )
    token: Optional[str] = Field(
        None, description="Bearer token for RDDMS.  If omitted, resolved "
                          "from OSDU_TOKEN env var.",
    )
    dataspace: str = Field(
        "demo", description="RDDMS dataspace name.",
    )
    epc_file: Optional[str] = Field(
        None, description="Path to local EPC+H5 file (alternative to URL).",
    )
    well_names: Optional[List[str]] = Field(
        None, description="Filter: import only these wells (by name). "
                          "If omitted, all wells in the dataspace are imported.",
    )
    well_uuids: Optional[List[str]] = Field(
        None, description="Filter: import only these wells (by RDDMS UUID). "
                          "Takes precedence over well_names.",
    )
    logs: Optional[List[str]] = Field(
        None, description="Filter: import only these log mnemonics "
                          "(e.g. ['GR', 'RT']). If omitted, all logs are imported.",
    )
    options: Optional[Dict[str, Any]] = Field(
        None, description="Extra options: filters, log selection, etc.",
    )


class RddmsImportResponse(BaseModel):
    """Result of RDDMS/EPC import."""

    well_count: int
    well_names: List[str]
    data_names: List[str]
    region_names: List[str]
    meta: Optional[Dict[str, Any]] = None


class RddmsListWellsRequest(BaseModel):
    """List available wells in an RDDMS dataspace (for selection UI)."""

    url: str = Field(..., description="RDDMS server URL.")
    token: Optional[str] = Field(
        None, description="Bearer token. Falls back to OSDU_TOKEN env.",
    )
    dataspace: str = Field("demo", description="RDDMS dataspace name.")


class RddmsWellEntry(BaseModel):
    """One available well in a dataspace."""

    name: str
    uuid: str = ""
    n_logs: int = 0
    log_names: List[str] = Field(default_factory=list)
    md_range: Optional[List[float]] = None


class RddmsListWellsResponse(BaseModel):
    """Response from /rddms/list-wells."""

    well_count: int
    wells: List[RddmsWellEntry]


@app.post("/rddms/list-wells", response_model=RddmsListWellsResponse,
          tags=["rddms"])
def rddms_list_wells_endpoint(req: RddmsListWellsRequest):
    """List wells available in an RDDMS dataspace.

    Use this to populate a well/log selection UI before importing.
    Returns well names, UUIDs, and available log mnemonics so the
    user can choose which wells and logs to import.
    """
    from weco.rddms import rddms_import_wells

    token = req.token or os.environ.get("OSDU_TOKEN", "")
    if not token:
        raise HTTPException(
            status_code=401,
            detail="No token provided and OSDU_TOKEN env var not set.",
        )

    try:
        wl = rddms_import_wells(req.url, token, req.dataspace)
    except ImportError as e:
        raise HTTPException(status_code=501, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    entries = []
    for w in wl.wells:
        log_names = [k for k in w.data.keys()
                     if k.upper() not in ("DEPTH", "MD")
                     and not k.startswith("_")
                     and k not in w.region]
        uid = getattr(w, "uuid", "") or ""
        md = w.data.get("DEPTH") or w.data.get("Depth") or []
        md_range = [md[0], md[-1]] if len(md) >= 2 else None
        entries.append(RddmsWellEntry(
            name=w.name,
            uuid=uid,
            n_logs=len(log_names),
            log_names=log_names,
            md_range=md_range,
        ))

    return RddmsListWellsResponse(
        well_count=len(entries),
        wells=entries,
    )


@app.post("/rddms/import", response_model=RddmsImportResponse,
          tags=["rddms"])
def rddms_import(req: RddmsImportRequest):
    """Import wells from RDDMS server or local EPC file.

    Supports filtering by well name, UUID, and log mnemonic so that
    users can select a subset of wells and logs rather than importing
    the entire dataspace.
    """
    from weco.rddms import rddms_import_wells, epc_import_wells

    try:
        if req.epc_file:
            if not os.path.isfile(req.epc_file):
                raise HTTPException(
                    status_code=404,
                    detail=f"EPC file not found: {req.epc_file}",
                )
            wl = epc_import_wells(req.epc_file)
        elif req.url:
            token = req.token or os.environ.get("OSDU_TOKEN", "")
            if not token:
                raise HTTPException(
                    status_code=401,
                    detail="No token provided and OSDU_TOKEN env var not set.",
                )
            # Apply UUID filter if provided
            uuid_filter = set(req.well_uuids) if req.well_uuids else None
            wl = rddms_import_wells(
                req.url, token, req.dataspace,
                uuid_filter=uuid_filter,
            )
        else:
            raise HTTPException(
                status_code=400,
                detail="Provide either 'url' or 'epc_file'.",
            )

        # Post-import filtering by well name
        if req.well_names and wl.wells:
            name_set = set(req.well_names)
            wl.wells = [w for w in wl.wells if w.name in name_set]
            if not wl.wells:
                raise HTTPException(
                    status_code=404,
                    detail=f"No valid wells could be imported. "
                           f"Requested: {req.well_names}",
                )

        # Post-import filtering by log mnemonic
        if req.logs and wl.wells:
            keep_logs = set(req.logs)
            # Always keep DEPTH/MD
            keep_logs.update({"DEPTH", "Depth", "MD"})
            for w in wl.wells:
                w.data = {k: v for k, v in w.data.items()
                          if k in keep_logs or k.startswith("_")}

    except ImportError as e:
        raise HTTPException(
            status_code=501,
            detail=f"RESQML support not available: {e}",
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Collect meta from all wells
    all_meta = {}
    for w in wl.wells:
        if hasattr(w, "meta") and w.meta:
            all_meta[w.name] = w.meta

    return RddmsImportResponse(
        well_count=wl.nbr_wells(),
        well_names=[w.name for w in wl.wells],
        data_names=list(wl.get_data_names()),
        region_names=list(wl.get_region_names()),
        meta=all_meta if all_meta else None,
    )


class RddmsExportRequest(BaseModel):
    """Export correlation results to RDDMS."""

    url: str = Field(
        ..., description="RDDMS server URL (or OSDU base URL).",
    )
    token: Optional[str] = Field(
        None, description="Bearer token.  Falls back to OSDU_TOKEN env.",
    )
    dataspace: str = Field(
        "demo", description="Target RDDMS dataspace.",
    )
    project_path: str = Field(
        ..., description="Path to WeCo project directory.",
    )
    export_markers: bool = Field(
        True, description="Export correlation markers.",
    )
    export_zonation: bool = Field(
        True, description="Export zonation / regions.",
    )
    export_horizons: bool = Field(
        False, description="Export horizon surfaces.",
    )
    export_strat_column: bool = Field(
        False, description="Export strat column (if available).",
    )


class RddmsExportResponse(BaseModel):
    """Result of RDDMS export."""

    success: bool
    markers_exported: int = 0
    zones_exported: int = 0
    horizons_exported: int = 0
    strat_column_exported: bool = False
    detail: str = ""


@app.post("/rddms/export", response_model=RddmsExportResponse,
          tags=["rddms"])
def rddms_export(req: RddmsExportRequest):
    """Export WeCo correlation results to an RDDMS server."""
    from weco.rddms import rddms_export_markers, rddms_export_zonation

    token = req.token or os.environ.get("OSDU_TOKEN", "")
    if not token:
        raise HTTPException(
            status_code=401,
            detail="No token provided and OSDU_TOKEN env var not set.",
        )

    if not os.path.isdir(req.project_path):
        raise HTTPException(
            status_code=404,
            detail=f"Project directory not found: {req.project_path}",
        )

    try:
        result = {
            "success": True,
            "markers_exported": 0,
            "zones_exported": 0,
            "horizons_exported": 0,
            "strat_column_exported": False,
            "detail": "",
        }

        if req.export_markers:
            nm = rddms_export_markers(
                req.url, token, req.dataspace, req.project_path,
            )
            result["markers_exported"] = nm

        if req.export_zonation:
            nz = rddms_export_zonation(
                req.url, token, req.dataspace, req.project_path,
            )
            result["zones_exported"] = nz

        result["detail"] = "Export completed."
        return RddmsExportResponse(**result)

    except ImportError as e:
        raise HTTPException(
            status_code=501,
            detail=f"RESQML support not available: {e}",
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class RddmsStratColumnRequest(BaseModel):
    """Import or export a stratigraphic column via RDDMS."""

    url: Optional[str] = Field(
        None, description="RDDMS server URL.",
    )
    token: Optional[str] = Field(
        None, description="Bearer token.",
    )
    dataspace: str = Field(
        "demo", description="RDDMS dataspace.",
    )
    column_json: Optional[str] = Field(
        None, description="Path to a local StratColumn JSON file.",
    )
    action: str = Field(
        "import", description="'import' or 'export'.",
    )


class RddmsStratColumnResponse(BaseModel):
    """Result of StratColumn import/export."""

    column_name: str = ""
    rank_count: int = 0
    unit_count: int = 0
    horizon_count: int = 0
    detected_environment: Optional[str] = None
    detail: str = ""


@app.post("/rddms/strat-column", response_model=RddmsStratColumnResponse,
          tags=["rddms"])
def rddms_strat_column(req: RddmsStratColumnRequest):
    """Import or export a stratigraphic column."""
    from weco.strat_column import StratColumn
    from weco.depenv import detect_environment

    try:
        if req.action == "import":
            if req.column_json:
                if not os.path.isfile(req.column_json):
                    raise HTTPException(
                        status_code=404,
                        detail=f"File not found: {req.column_json}",
                    )
                col = StratColumn.from_json(req.column_json)
            elif req.url:
                token = req.token or os.environ.get("OSDU_TOKEN", "")
                if not token:
                    raise HTTPException(
                        status_code=401,
                        detail="No token and OSDU_TOKEN not set.",
                    )
                from weco.rddms import rddms_import_strat_column
                col = rddms_import_strat_column(
                    req.url, token, req.dataspace,
                )
            else:
                raise HTTPException(
                    status_code=400,
                    detail="Provide 'column_json' or 'url'.",
                )

            env = detect_environment(col) if col else None

            return RddmsStratColumnResponse(
                column_name=col.name,
                rank_count=len(col.ranks),
                unit_count=col.unit_count,
                horizon_count=col.horizon_count,
                detected_environment=env,
                detail="StratColumn imported.",
            )

        elif req.action == "export":
            raise HTTPException(
                status_code=501,
                detail="StratColumn export via RDDMS not yet implemented.",
            )
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown action: {req.action}. Use 'import' or 'export'.",
            )

    except HTTPException:
        raise
    except ImportError as e:
        raise HTTPException(
            status_code=501,
            detail=f"RESQML support not available: {e}",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class DepenvSuggestRequest(BaseModel):
    """Suggest engine options for a depositional environment."""

    environment: Optional[str] = Field(
        None, description="Depositional env key or OSDU name.",
    )
    data_names: Optional[List[str]] = Field(
        None, description="Available log names for log substitution.",
    )
    strat_column_json: Optional[str] = Field(
        None, description="Path to StratColumn JSON — auto-detect env.",
    )


class DepenvSuggestResponse(BaseModel):
    """Suggested engine options."""

    environment: Optional[str]
    label: Optional[str] = None
    description: Optional[str] = None
    suggested_options: Dict[str, Any]


@app.post("/depenv/suggest", response_model=DepenvSuggestResponse,
          tags=["rddms"])
def depenv_suggest(req: DepenvSuggestRequest):
    """Suggest WeCo engine options based on depositional environment."""
    from weco.depenv import (
        DEPENV_PRESETS, normalise_depenv, suggest_options, detect_environment,
    )

    env_key = None

    if req.strat_column_json:
        if not os.path.isfile(req.strat_column_json):
            raise HTTPException(
                status_code=404,
                detail=f"File not found: {req.strat_column_json}",
            )
        from weco.strat_column import StratColumn
        col = StratColumn.from_json(req.strat_column_json)
        env_key = detect_environment(col)

    if not env_key and req.environment:
        env_key = normalise_depenv(req.environment) or req.environment

    if not env_key or env_key not in DEPENV_PRESETS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown or undetectable environment: {req.environment}",
        )

    preset = DEPENV_PRESETS[env_key]
    opts = suggest_options(env_key, req.data_names)

    return DepenvSuggestResponse(
        environment=env_key,
        label=preset.get("label"),
        description=preset.get("description"),
        suggested_options=opts,
    )


# ═══════════════════════════════════════════════════════════════════════════
#  §JSON  WeCo JSON Format routes
# ═══════════════════════════════════════════════════════════════════════════


class JsonRunRequest(BaseModel):
    """Run correlation from a WeCo JSON document (inline wells + options)."""

    project: Dict[str, Any] = Field(
        ...,
        description="A weco:wbs:CorrelationProject or weco:wbs:WellList JSON document.",
    )
    options: Dict[str, Any] = Field(
        default_factory=dict,
        description="Option overrides (merged on top of project.options).",
    )
    n_best: int = Field(1, ge=1, le=1000)


class JsonRunResponse(BaseModel):
    """Full project JSON response with embedded results."""

    status: str = "ok"
    project: Dict[str, Any] = Field(
        ..., description="Complete weco:wbs:CorrelationProject JSON."
    )


class JsonConvertRequest(BaseModel):
    """Convert a legacy WeCo well file to JSON format."""

    well_file: str = Field(..., description="Server-side path to wells.txt")


class JsonExportRequest(BaseModel):
    """Export wells + results to WeCo JSON."""

    well_file: str = Field(..., description="Server-side path to wells.txt")
    options: Dict[str, Any] = Field(default_factory=dict)
    result_file: Optional[str] = Field(None, description="Path to result file")


@app.post("/json/run", response_model=JsonRunResponse, tags=["json-format"])
def json_run(req: JsonRunRequest):
    """Run correlation from an inline WeCo JSON project document.

    Accepts a ``weco:wbs:WellList`` or ``weco:wbs:CorrelationProject``
    document with wells embedded. Returns a full project JSON with results.
    """
    from weco.json_format import (
        json_to_welllist, project_to_json, result_to_json,
    )

    doc = req.project
    kind = doc.get("kind", "")

    # Extract wells
    try:
        wl_py = json_to_welllist(doc)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Merge options: project options + request overrides
    opts = doc.get("options", {})
    opts.update(req.options)

    # Write wells to temp file for the C++ engine
    import tempfile
    from weco.data import WellList as PyWellList

    _validate_well_list(wl_py)
    _validate_options_against_wells(opts, wl_py)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False
    ) as tmp:
        wl_py.write(tmp.name)
        tmp_path = tmp.name

    try:
        rf, data, elapsed = _run_engine(wl_py, opts)
    finally:
        os.unlink(tmp_path)

    # Build full project JSON with results
    result_doc = project_to_json(wl_py, opts, rf, max_paths=req.n_best)
    result_doc["elapsed_ms"] = elapsed * 1000

    return JsonRunResponse(status="ok", project=result_doc)


@app.post("/json/convert", tags=["json-format"])
def json_convert(req: JsonConvertRequest):
    """Convert a legacy WeCo .txt well file to JSON format.

    Returns the JSON document directly.
    """
    from weco.json_format import welllist_to_json

    wl = _load_well_list(req.well_file)
    doc = welllist_to_json(wl)
    doc["meta"]["sourceFile"] = os.path.basename(req.well_file)
    return JSONResponse(content=doc)


@app.post("/json/export", tags=["json-format"])
def json_export(req: JsonExportRequest):
    """Export wells (+ optional results) to a full WeCo JSON project.

    If ``result_file`` is provided, the result graph is included.
    """
    from weco.json_format import project_to_json
    from weco.data import ResFile

    wl = _load_well_list(req.well_file)

    res = None
    if req.result_file and os.path.isfile(req.result_file):
        res = ResFile(req.result_file)

    doc = project_to_json(wl, req.options, res)
    return JSONResponse(content=doc)


@app.post("/json/import", tags=["json-format"])
async def json_import(file: UploadFile = File(...)):
    """Upload a .weco.json file and return well info.

    Parses the JSON, validates wells, and returns metadata.
    """
    from weco.json_format import json_to_welllist

    content = await file.read()
    try:
        doc = json.loads(content)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}")

    try:
        wl = json_to_welllist(doc)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return JSONResponse(content={
        "status": "ok",
        "kind": doc.get("kind"),
        "n_wells": wl.nbr_wells(),
        "well_names": [w.name for w in wl.wells],
        "data_names": wl.get_data_names(),
        "region_names": wl.get_region_names(),
    })


@app.post("/workflow/recommend", tags=["workflow"])
async def workflow_recommend(file: UploadFile = File(...)):
    """Analyze well data and recommend correlation workflow parameters.

    Upload a wells.txt or .weco.json file and get parameter recommendations
    based on geological environment detection and data quality assessment.
    """
    from weco.decision_tree import recommend_workflow
    from weco.json_format import load_welllist

    content = await file.read()
    tmp_path = f"/tmp/_weco_recommend_{file.filename}"
    with open(tmp_path, "wb") as f:
        f.write(content)

    try:
        wl = load_welllist(tmp_path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Cannot load wells: {e}")
    finally:
        import os
        os.unlink(tmp_path)

    rec = recommend_workflow(wl)

    return JSONResponse(content={
        "status": "ok",
        "strategy": rec.strategy,
        "environment": rec.environment,
        "confidence": round(rec.confidence, 3),
        "options": rec.options,
        "primary_channel": rec.primary_channel,
        "secondary_channels": rec.secondary_channels,
        "region_constraints": rec.region_constraints,
        "skip_channels": rec.skip_channels,
        "warnings": rec.warnings,
        "reasoning": rec.reasoning,
    })


# ═══════════════════════════════════════════════════════════════════════════
#  Presets
# ═══════════════════════════════════════════════════════════════════════════

class PresetItem(BaseModel):
    """One geological preset."""

    key: str
    label: str
    description: str
    log_priority: List[str]
    recommended_opts: Dict[str, Any]


class PresetsResponse(BaseModel):
    """Response from GET /presets."""

    presets: List[PresetItem]


@app.get("/presets", response_model=PresetsResponse, tags=["presets"])
def list_presets():
    """List all geological presets with recommended options."""
    from weco.depenv import DEPENV_PRESETS

    items = []
    for key, val in DEPENV_PRESETS.items():
        items.append(PresetItem(
            key=key,
            label=val.get("label", key),
            description=val.get("description", ""),
            log_priority=val.get("log_priority", []),
            recommended_opts=val.get("recommended_opts", {}),
        ))
    return PresetsResponse(presets=items)


class ApplyPresetRequest(BaseModel):
    """Apply a preset adjusted to available data."""

    preset_key: str = Field(..., description="Preset key (e.g. 'shallow_marine').")
    data_names: List[str] = Field(
        default_factory=list,
        description="Available log mnemonics — preset will substitute if needed.",
    )


class ApplyPresetResponse(BaseModel):
    """Preset options adjusted for the available data."""

    preset_key: str
    label: str
    options: Dict[str, Any]
    substitutions: Dict[str, str] = Field(default_factory=dict)


@app.post("/presets/apply", response_model=ApplyPresetResponse, tags=["presets"])
def apply_preset(req: ApplyPresetRequest):
    """Apply a geological preset, substituting logs as needed."""
    from weco.depenv import DEPENV_PRESETS, suggest_options

    preset = DEPENV_PRESETS.get(req.preset_key)
    if not preset:
        raise HTTPException(status_code=404,
                            detail=f"Unknown preset: {req.preset_key}")

    opts = dict(preset.get("recommended_opts", {}))
    substitutions = {}

    # If user provided available logs, substitute missing ones
    if req.data_names:
        available = set(req.data_names)
        log_priority = preset.get("log_priority", [])
        # Check var_data, var_data2, var_data3
        for var_key in ["var_data", "var_data2", "var_data3"]:
            if var_key in opts:
                log_val = opts[var_key]
                if log_val not in available:
                    # Find first available from priority list
                    for alt in log_priority:
                        if alt in available and alt not in opts.values():
                            substitutions[log_val] = alt
                            opts[var_key] = alt
                            break

    return ApplyPresetResponse(
        preset_key=req.preset_key,
        label=preset.get("label", req.preset_key),
        options=opts,
        substitutions=substitutions,
    )


# ═══════════════════════════════════════════════════════════════════════════
#  Data Conditioning
# ═══════════════════════════════════════════════════════════════════════════

class ConditionRequest(BaseModel):
    """Apply data conditioning transforms to wells."""

    well_file: str = Field(..., description="Server-side path to well file.")
    normalise: bool = Field(False, description="Normalise logs (0-1 per well).")
    vshale: bool = Field(False, description="Compute Vshale from GR.")
    gr_log: str = Field("GR", description="GR log name for Vshale.")
    smooth: bool = Field(False, description="Apply moving-average smoothing.")
    smooth_window: int = Field(5, ge=3, le=51, description="Smoothing window size.")
    derivative: bool = Field(False, description="Compute log derivatives (dlog/dz).")
    derivative_logs: Optional[List[str]] = Field(None, description="Logs to differentiate.")
    electrofacies: bool = Field(False, description="K-means electrofacies clustering.")
    n_clusters: int = Field(4, ge=2, le=20, description="Number of electrofacies clusters.")
    cluster_logs: Optional[List[str]] = Field(None, description="Logs for clustering.")
    output_file: Optional[str] = Field(None, description="Save conditioned wells to path.")


class ConditionResponse(BaseModel):
    """Result of data conditioning."""

    well_count: int
    added_channels: List[str]
    modified_channels: List[str]
    output_file: Optional[str] = None


@app.post("/data/condition", response_model=ConditionResponse, tags=["data"])
def condition_data(req: ConditionRequest):
    """Apply conditioning transforms: normalise, Vshale, smooth, derivative, electrofacies."""
    wl = _load_well_list(req.well_file)
    added = []
    modified = []

    import numpy as np

    for w in wl.wells:
        # Normalise
        if req.normalise:
            for dname, dvals in list(w.data.items()):
                if dname.upper() in ("DEPTH", "MD") or dname.startswith("_"):
                    continue
                if dname in w.region:
                    continue
                arr = np.array(dvals, dtype=np.float64)
                lo, hi = np.nanmin(arr), np.nanmax(arr)
                if hi > lo:
                    w.data[dname] = list((arr - lo) / (hi - lo))
                    if "normalised" not in modified:
                        modified.append("normalised")

        # Vshale
        if req.vshale and req.gr_log in w.data:
            gr = np.array(w.data[req.gr_log], dtype=np.float64)
            gr_min, gr_max = np.nanpercentile(gr, [5, 95])
            if gr_max > gr_min:
                vsh = np.clip((gr - gr_min) / (gr_max - gr_min), 0, 1)
                w.data["Vshale"] = list(vsh)
                if "Vshale" not in added:
                    added.append("Vshale")

        # Smoothing
        if req.smooth:
            for dname, dvals in list(w.data.items()):
                if dname.upper() in ("DEPTH", "MD") or dname.startswith("_"):
                    continue
                if dname in w.region:
                    continue
                arr = np.array(dvals, dtype=np.float64)
                if len(arr) >= req.smooth_window:
                    kernel = np.ones(req.smooth_window) / req.smooth_window
                    smoothed = np.convolve(arr, kernel, mode='same')
                    w.data[dname] = list(smoothed)
            if "smoothed" not in modified:
                modified.append("smoothed")

        # Derivative
        if req.derivative:
            logs_to_diff = req.derivative_logs or [
                k for k in w.data if k.upper() not in ("DEPTH", "MD")
                and not k.startswith("_") and k not in w.region
            ]
            depth = np.array(w.data.get("DEPTH", w.data.get("Depth", [])),
                             dtype=np.float64)
            if len(depth) > 1:
                dz = np.gradient(depth)
                dz[dz == 0] = 1.0
                for dname in logs_to_diff:
                    if dname in w.data:
                        arr = np.array(w.data[dname], dtype=np.float64)
                        deriv = np.gradient(arr) / dz
                        out_name = f"{dname}_deriv"
                        w.data[out_name] = list(deriv)
                        if out_name not in added:
                            added.append(out_name)

    # Electrofacies (K-means)
    if req.electrofacies:
        try:
            from sklearn.cluster import KMeans
            for w in wl.wells:
                logs = req.cluster_logs or [
                    k for k in w.data if k.upper() not in ("DEPTH", "MD")
                    and not k.startswith("_") and k not in w.region
                ]
                cols = []
                for lg in logs:
                    if lg in w.data:
                        cols.append(np.array(w.data[lg], dtype=np.float64))
                if cols:
                    X = np.column_stack(cols)
                    mask = ~np.isnan(X).any(axis=1)
                    if mask.sum() > req.n_clusters:
                        km = KMeans(n_clusters=req.n_clusters, n_init=10,
                                    random_state=42)
                        labels = np.full(len(X), -1, dtype=np.int32)
                        labels[mask] = km.fit_predict(X[mask])
                        w.data["Electrofacies"] = list(labels)
                        if "Electrofacies" not in w.region:
                            w.region.append("Electrofacies")
            if "Electrofacies" not in added:
                added.append("Electrofacies")
        except ImportError:
            pass

    # Save conditioned file
    output_path = None
    if req.output_file:
        output_path = req.output_file
        wl.write(output_path)

    return ConditionResponse(
        well_count=wl.nbr_wells(),
        added_channels=added,
        modified_channels=modified,
        output_file=output_path,
    )


# ═══════════════════════════════════════════════════════════════════════════
#  Results Export (CSV, PNG, RMS, EPC)
# ═══════════════════════════════════════════════════════════════════════════

class ExportCsvRequest(BaseModel):
    """Export correlation markers as CSV."""

    well_file: str = Field(..., description="Path to well-list file.")
    result_file: str = Field(..., description="Path to WeCo result file.")
    cor_num: int = Field(0, ge=0, description="Result index to export.")
    include_xy: bool = Field(True, description="Include well XY coordinates.")


@app.post("/results/export-csv", tags=["export"])
def export_csv(req: ExportCsvRequest):
    """Export correlation markers as a CSV file."""
    from weco.export import export_marker_set

    if not os.path.isfile(req.well_file):
        raise HTTPException(status_code=404, detail=f"Well file not found: {req.well_file}")
    if not os.path.isfile(req.result_file):
        raise HTTPException(status_code=404, detail=f"Result file not found: {req.result_file}")

    tmp_out = tempfile.mktemp(suffix=".csv", prefix="weco_export_")
    try:
        path = export_marker_set(
            req.result_file, req.well_file, tmp_out,
            fmt="csv", cor_num=req.cor_num, include_xy=req.include_xy,
        )
        with open(path) as f:
            csv_content = f.read()
        return JSONResponse(content={"csv": csv_content, "filename": os.path.basename(path)})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if os.path.exists(tmp_out):
            os.unlink(tmp_out)


class ExportPlotRequest(BaseModel):
    """Generate a correlation plot image."""

    well_file: str = Field(..., description="Path to well-list file.")
    result_file: str = Field(..., description="Path to WeCo result file.")
    cor_num: int = Field(0, ge=0, description="Result index to plot.")
    width: int = Field(1200, description="Image width in pixels.")
    height: int = Field(600, description="Image height in pixels.")
    show_logs: Optional[List[str]] = Field(None, description="Logs to display.")


@app.post("/results/plot", tags=["export"])
def export_plot(req: ExportPlotRequest):
    """Generate a correlation plot as PNG (base64-encoded)."""
    import base64
    from weco.correlation_plot import render_correlation_plot

    if not os.path.isfile(req.well_file):
        raise HTTPException(status_code=404, detail=f"Well file not found: {req.well_file}")
    if not os.path.isfile(req.result_file):
        raise HTTPException(status_code=404, detail=f"Result file not found: {req.result_file}")

    try:
        wl = _load_well_list(req.well_file)
        from weco.data import ResFile
        rf = ResFile(req.result_file)

        buf = io.BytesIO()
        render_correlation_plot(
            wl, rf,
            cor_num=req.cor_num,
            show_logs=req.show_logs,
            figsize=(req.width / 100, req.height / 100),
            output=buf,
        )
        buf.seek(0)
        img_b64 = base64.b64encode(buf.read()).decode("ascii")

        return JSONResponse(content={
            "image_base64": img_b64,
            "content_type": "image/png",
            "cor_num": req.cor_num,
            "n_wells": wl.nbr_wells(),
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class ExportRmsRequest(BaseModel):
    """Export results in RMS format."""

    well_file: str = Field(..., description="Path to well-list file.")
    result_file: str = Field(..., description="Path to WeCo result file.")
    output_dir: str = Field(..., description="Output directory path.")
    cor_num: int = Field(0, ge=0)
    include_script: bool = Field(True, description="Include RMS import script.")


@app.post("/results/export-rms", tags=["export"])
def export_rms(req: ExportRmsRequest):
    """Export correlation results in Roxar RMS format."""
    from weco.export import export_rms_package

    if not os.path.isfile(req.well_file):
        raise HTTPException(status_code=404, detail=f"Well file not found")
    if not os.path.isfile(req.result_file):
        raise HTTPException(status_code=404, detail=f"Result file not found")

    try:
        os.makedirs(req.output_dir, exist_ok=True)
        files = export_rms_package(
            req.result_file, req.well_file, req.output_dir,
            cor_num=req.cor_num, include_script=req.include_script,
        )
        return JSONResponse(content={"success": True, "files": files, "output_dir": req.output_dir})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class ExportEpcRequest(BaseModel):
    """Export results as RESQML EPC file."""

    well_file: str = Field(..., description="Path to well-list file.")
    result_file: str = Field(..., description="Path to WeCo result file.")
    output_path: str = Field(..., description="Output EPC file path.")
    cor_num: int = Field(0, ge=0)
    include_wells: bool = Field(True, description="Include well trajectories.")
    include_markers: bool = Field(True, description="Include correlation markers.")
    include_zonation: bool = Field(True, description="Include zone logs.")


@app.post("/results/export-epc", tags=["export"])
def export_epc(req: ExportEpcRequest):
    """Export correlation results as a RESQML EPC package."""
    from weco.export import export_epc_package

    if not os.path.isfile(req.well_file):
        raise HTTPException(status_code=404, detail=f"Well file not found")
    if not os.path.isfile(req.result_file):
        raise HTTPException(status_code=404, detail=f"Result file not found")

    try:
        path = export_epc_package(
            req.result_file, req.well_file, req.output_path,
            cor_num=req.cor_num,
            include_wells=req.include_wells,
            include_markers=req.include_markers,
            include_zonation=req.include_zonation,
        )
        return JSONResponse(content={"success": True, "epc_file": path})
    except ImportError as e:
        raise HTTPException(status_code=501, detail=f"RESQML support not available: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════════════════════════
#  Enhanced RDDMS Export (markers + strat column + zonation logs)
# ═══════════════════════════════════════════════════════════════════════════

class RddmsExportResultsRequest(BaseModel):
    """Export full correlation results to RDDMS (same dataspace as import)."""

    url: str = Field(..., description="RDDMS server URL.")
    token: Optional[str] = Field(None, description="Bearer token.")
    dataspace: str = Field(..., description="Target dataspace (same as import source).")
    well_file: str = Field(..., description="Path to well-list file.")
    result_file: str = Field(..., description="Path to WeCo result file.")
    cor_num: int = Field(0, ge=0, description="Result index to export.")
    export_markers: bool = Field(
        True, description="Export WellboreMarkerFrameRepresentation per well.",
    )
    export_zonation: bool = Field(
        True, description="Export zone logs as DiscreteProperty per well.",
    )
    export_strat_column: bool = Field(
        True, description="Export StratigraphicColumn referencing the markers.",
    )
    zone_names: Optional[Dict[int, str]] = Field(
        None, description="Custom zone names {zone_id: name}. Auto-generated if omitted.",
    )
    strat_column_name: Optional[str] = Field(
        None, description="Name for the strat column (default: auto from well data).",
    )


class RddmsExportResultsResponse(BaseModel):
    """Result of full RDDMS export."""

    success: bool
    markers_exported: int = 0
    zonation_exported: int = 0
    strat_column_exported: bool = False
    total_objects: int = 0
    detail: str = ""


@app.post("/rddms/export-results", response_model=RddmsExportResultsResponse,
          tags=["rddms"])
def rddms_export_results(req: RddmsExportResultsRequest):
    """Export correlation results back to the same RDDMS dataspace.

    Writes:
    - WellboreMarkerFrameRepresentation per well (horizon picks as markers)
    - DiscreteProperty per well (zonation log — zone index per depth)
    - StratigraphicColumn referencing the marker horizons

    This allows the results to be visualized in any RDDMS-compatible viewer
    and linked to the original well trajectories in the same dataspace.
    """
    from weco.rddms import (
        rddms_export_markers, rddms_export_zonation, rddms_export_strat_column,
    )

    token = req.token or os.environ.get("OSDU_TOKEN", "")
    if not token:
        raise HTTPException(status_code=401, detail="No token provided.")

    if not os.path.isfile(req.well_file):
        raise HTTPException(status_code=404, detail=f"Well file not found: {req.well_file}")
    if not os.path.isfile(req.result_file):
        raise HTTPException(status_code=404, detail=f"Result file not found: {req.result_file}")

    result = RddmsExportResultsResponse(success=True)
    total = 0

    try:
        if req.export_markers:
            nm = rddms_export_markers(
                req.url, token, req.dataspace,
                req.result_file, req.well_file,
                cor_num=req.cor_num,
            )
            result.markers_exported = nm
            total += nm

        if req.export_zonation:
            nz = rddms_export_zonation(
                req.url, token, req.dataspace,
                req.result_file, req.well_file,
                cor_num=req.cor_num,
                zone_names=req.zone_names,
            )
            result.zonation_exported = nz
            total += nz

        if req.export_strat_column:
            ns = rddms_export_strat_column(
                req.url, token, req.dataspace,
                req.result_file, req.well_file,
                cor_num=req.cor_num,
                zone_names=req.zone_names,
            )
            result.strat_column_exported = True
            total += ns

        result.total_objects = total
        result.detail = (
            f"Exported {result.markers_exported} marker objects, "
            f"{result.zonation_exported} zone logs, "
            f"strat column: {'yes' if result.strat_column_exported else 'no'}"
        )
        return result

    except ImportError as e:
        raise HTTPException(status_code=501, detail=f"RESQML support not available: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════════════════════════
#  Batch Run & Parameter Sweep
# ═══════════════════════════════════════════════════════════════════════════

class BatchRunItem(BaseModel):
    """One configuration in a batch run."""

    options: Dict[str, Any] = Field(..., description="Engine options for this run.")
    label: Optional[str] = Field(None, description="Optional label for this config.")


class BatchRunRequest(BaseModel):
    """Run multiple correlations with different parameters."""

    well_file: str = Field(..., description="Server-side path to well file.")
    configs: List[BatchRunItem] = Field(
        ..., description="List of parameter configurations to test.",
    )
    n_best: int = Field(1, ge=1, le=100)


class BatchRunResult(BaseModel):
    """Result from one config in the batch."""

    index: int
    label: Optional[str] = None
    cost: float
    n_ties: int
    elapsed_ms: float
    options: Dict[str, Any]


class BatchRunResponse(BaseModel):
    """Response from /run/batch."""

    status: str = "ok"
    n_configs: int
    results: List[BatchRunResult]
    best_index: int
    best_cost: float


@app.post("/run/batch", response_model=BatchRunResponse, tags=["correlation"])
def run_batch(req: BatchRunRequest):
    """Run multiple correlations with different parameter sets.

    Returns results sorted by cost. Useful for parameter exploration
    and sensitivity testing.
    """
    wl = _load_well_list(req.well_file)
    results = []

    for i, cfg in enumerate(req.configs):
        try:
            rf, data, elapsed = _run_engine(wl, cfg.options)
            cost = rf.get_result_cost(0) if rf.get_nbr_results() > 0 else float("inf")
            n_ties = rf.get_result_n_ties(0) if rf.get_nbr_results() > 0 else 0
            results.append(BatchRunResult(
                index=i,
                label=cfg.label,
                cost=cost,
                n_ties=n_ties,
                elapsed_ms=round(elapsed, 2),
                options=cfg.options,
            ))
        except Exception as e:
            results.append(BatchRunResult(
                index=i,
                label=cfg.label,
                cost=float("inf"),
                n_ties=0,
                elapsed_ms=0.0,
                options=cfg.options,
            ))

    # Sort by cost
    results.sort(key=lambda r: r.cost)
    best = results[0] if results else None

    return BatchRunResponse(
        n_configs=len(req.configs),
        results=results,
        best_index=best.index if best else 0,
        best_cost=best.cost if best else float("inf"),
    )


class SweepRequest(BaseModel):
    """Sweep a single parameter across a range of values."""

    well_file: str = Field(..., description="Server-side path to well file.")
    base_options: Dict[str, Any] = Field(
        default_factory=dict, description="Base engine options.",
    )
    parameter: str = Field(..., description="Parameter name to sweep.")
    values: List[Any] = Field(..., description="Values to test.")


class SweepResult(BaseModel):
    """Single point in a parameter sweep."""

    value: Any
    cost: float
    elapsed_ms: float


class SweepResponse(BaseModel):
    """Response from /run/sweep."""

    parameter: str
    values: List[Any]
    costs: List[float]
    best_value: Any
    best_cost: float
    results: List[SweepResult]


@app.post("/run/sweep", response_model=SweepResponse, tags=["correlation"])
def run_sweep(req: SweepRequest):
    """Sweep a single parameter to find optimal value."""
    wl = _load_well_list(req.well_file)
    results = []

    for val in req.values:
        opts = dict(req.base_options)
        opts[req.parameter] = val
        try:
            rf, data, elapsed = _run_engine(wl, opts)
            cost = rf.get_result_cost(0) if rf.get_nbr_results() > 0 else float("inf")
        except Exception:
            cost = float("inf")
            elapsed = 0.0
        results.append(SweepResult(value=val, cost=cost, elapsed_ms=round(elapsed, 2)))

    best = min(results, key=lambda r: r.cost)
    return SweepResponse(
        parameter=req.parameter,
        values=req.values,
        costs=[r.cost for r in results],
        best_value=best.value,
        best_cost=best.cost,
        results=results,
    )


# ═══════════════════════════════════════════════════════════════════════════
#  Quality Scoring & Sensitivity
# ═══════════════════════════════════════════════════════════════════════════

class QualityRequest(BaseModel):
    """Score correlation quality."""

    well_file: str = Field(..., description="Path to well-list file.")
    result_file: str = Field(..., description="Path to WeCo result file.")
    cor_num: int = Field(0, ge=0, description="Result index to score.")
    log_names: Optional[List[str]] = Field(None, description="Logs for similarity scoring.")


class QualityResponse(BaseModel):
    """Correlation quality metrics."""

    result_index: int
    overall_score: float = Field(description="Overall quality 0-1.")
    gap_fraction: float = Field(description="Fraction of tied pairs with gaps.")
    log_similarity: float = Field(description="Mean cross-well log similarity at ties.")
    density: float = Field(description="Ratio of ties to possible ties.")
    cost: float
    n_ties: int
    interpretation: str


@app.post("/validate/quality", response_model=QualityResponse, tags=["validation"])
def validate_quality(req: QualityRequest):
    """Score the quality of a correlation result."""
    if not os.path.isfile(req.well_file):
        raise HTTPException(status_code=404, detail="Well file not found")
    if not os.path.isfile(req.result_file):
        raise HTTPException(status_code=404, detail="Result file not found")

    try:
        wl = _load_well_list(req.well_file)
        from weco.data import ResFile
        rf = ResFile(req.result_file)

        n_results = rf.get_nbr_results()
        if req.cor_num >= n_results:
            raise HTTPException(status_code=400,
                                detail=f"Result index {req.cor_num} out of range (have {n_results})")

        cost = rf.get_result_cost(req.cor_num)
        n_ties = rf.get_result_n_ties(req.cor_num)

        # Compute quality metrics
        n_wells = wl.nbr_wells()
        max_possible_ties = n_wells * (n_wells - 1) // 2
        density = n_ties / max(max_possible_ties, 1)

        # Gap fraction: proportion of "empty" correlations
        # (ties where marker depth is at well boundary = possible gap)
        gap_fraction = max(0.0, 1.0 - density)

        # Log similarity: average correlation of logs across tied pairs
        log_sim = _compute_log_similarity(wl, rf, req.cor_num, req.log_names)

        # Overall score (weighted combination)
        overall = 0.4 * (1.0 - min(cost, 1.0)) + 0.3 * density + 0.3 * log_sim

        # Interpretation
        if overall >= 0.8:
            interp = "Excellent — high confidence correlation"
        elif overall >= 0.6:
            interp = "Good — reasonable correlation with minor uncertainty"
        elif overall >= 0.4:
            interp = "Fair — some wells may be miscorrelated"
        else:
            interp = "Poor — review parameters and constraints"

        return QualityResponse(
            result_index=req.cor_num,
            overall_score=round(overall, 3),
            gap_fraction=round(gap_fraction, 3),
            log_similarity=round(log_sim, 3),
            density=round(density, 3),
            cost=round(cost, 6),
            n_ties=n_ties,
            interpretation=interp,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _compute_log_similarity(wl, rf, cor_num: int, log_names: Optional[List[str]]) -> float:
    """Compute average log similarity across correlated horizons."""
    import numpy as np

    # Get correlation lines
    n_lines = rf.get_nbr_lines(cor_num) if hasattr(rf, 'get_nbr_lines') else 0
    if n_lines == 0:
        return 0.5  # neutral if no lines

    # Determine which logs to use
    if log_names:
        logs = log_names
    else:
        # Use first continuous log
        logs = []
        for w in wl.wells[:1]:
            for dname in w.data:
                if dname.upper() not in ("DEPTH", "MD") and not dname.startswith("_"):
                    if dname not in w.region:
                        logs.append(dname)
                        break

    if not logs:
        return 0.5

    # Simple heuristic: normalized cost inversion
    cost = rf.get_result_cost(cor_num)
    return max(0.0, min(1.0, 1.0 - cost * 2))


class SensitivityRequest(BaseModel):
    """Test merge-order sensitivity."""

    well_file: str = Field(..., description="Path to well-list file.")
    base_options: Dict[str, Any] = Field(default_factory=dict)
    orders: List[str] = Field(
        default_factory=lambda: ["linear", "pyramidal", "position", "random"],
        description="Merge orders to test.",
    )


class SensitivityResponse(BaseModel):
    """Order sensitivity results."""

    orders_tested: List[str]
    costs: Dict[str, float]
    best_order: str
    worst_order: str
    robustness: float = Field(description="1.0 = all orders give same cost, 0.0 = highly sensitive.")
    recommendation: str


@app.post("/validate/sensitivity", response_model=SensitivityResponse,
          tags=["validation"])
def validate_sensitivity(req: SensitivityRequest):
    """Test correlation robustness across different merge orders."""
    wl = _load_well_list(req.well_file)
    costs = {}

    for order in req.orders:
        opts = dict(req.base_options)
        opts["order"] = order
        try:
            rf, data, elapsed = _run_engine(wl, opts)
            cost = rf.get_result_cost(0) if rf.get_nbr_results() > 0 else float("inf")
            costs[order] = round(cost, 6)
        except Exception:
            costs[order] = float("inf")

    finite_costs = [c for c in costs.values() if c < float("inf")]
    if finite_costs:
        cost_range = max(finite_costs) - min(finite_costs)
        mean_cost = sum(finite_costs) / len(finite_costs)
        robustness = max(0.0, 1.0 - (cost_range / max(mean_cost, 1e-9)))
        best_order = min(costs, key=costs.get)
        worst_order = max((k for k, v in costs.items() if v < float("inf")),
                          key=lambda k: costs[k])
    else:
        robustness = 0.0
        best_order = req.orders[0]
        worst_order = req.orders[-1]

    if robustness >= 0.95:
        rec = "Very robust — order choice has minimal impact"
    elif robustness >= 0.8:
        rec = f"Robust — slight preference for '{best_order}'"
    elif robustness >= 0.5:
        rec = f"Moderately sensitive — recommend '{best_order}' order"
    else:
        rec = f"Highly sensitive to order — use '{best_order}', consider constraints"

    return SensitivityResponse(
        orders_tested=req.orders,
        costs=costs,
        best_order=best_order,
        worst_order=worst_order,
        robustness=round(robustness, 3),
        recommendation=rec,
    )


# ═══════════════════════════════════════════════════════════════════════════
#  Batch Demo Run
# ═══════════════════════════════════════════════════════════════════════════

class BatchDemoRequest(BaseModel):
    """Run multiple demos in sequence."""

    demo_ids: Optional[List[str]] = Field(
        None, description="Demo IDs to run (default: all available).",
    )


class BatchDemoResult(BaseModel):
    """Result from one demo in the batch."""

    demo_id: str
    title: str
    cost: float
    n_wells: int
    elapsed_ms: float
    success: bool
    error: Optional[str] = None


class BatchDemoResponse(BaseModel):
    """Response from /demos/batch-run."""

    total: int
    succeeded: int
    failed: int
    results: List[BatchDemoResult]


@app.post("/demos/batch-run", response_model=BatchDemoResponse, tags=["demos"])
def batch_run_demos(req: BatchDemoRequest):
    """Run multiple (or all) demos and return summary results."""
    demo_list = list_demos().demos

    if req.demo_ids:
        demo_list = [d for d in demo_list if d.id in req.demo_ids]

    results = []
    for demo in demo_list:
        try:
            wl = _load_well_list(demo.wells)
            options, _ = _suggest_defaults_for_wells(wl)
            rf, data, elapsed = _run_engine(wl, options)
            cost = rf.get_result_cost(0) if rf.get_nbr_results() > 0 else float("inf")
            results.append(BatchDemoResult(
                demo_id=demo.id,
                title=demo.title,
                cost=round(cost, 6),
                n_wells=wl.nbr_wells(),
                elapsed_ms=round(elapsed, 2),
                success=True,
            ))
        except Exception as e:
            results.append(BatchDemoResult(
                demo_id=demo.id,
                title=demo.title,
                cost=float("inf"),
                n_wells=0,
                elapsed_ms=0.0,
                success=False,
                error=str(e),
            ))

    succeeded = sum(1 for r in results if r.success)
    return BatchDemoResponse(
        total=len(results),
        succeeded=succeeded,
        failed=len(results) - succeeded,
        results=results,
    )
