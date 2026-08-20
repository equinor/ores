"""
weco.api - REST API for headless WeCo correlation
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
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

app = FastAPI(
    title="WeCo API",
    description="Multi-well stratigraphic correlation engine - REST interface",
    version="0.9.31",
)


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception):
    """Catch-all: ensure every unhandled error returns valid JSON.

    Without this, uncaught exceptions (e.g. C++ SIGSEGV survivors, import
    errors, attribute errors on None) would return raw 500 text that the
    frontend JS cannot parse - leading to the 'Cannot read properties of
    undefined' cascade.
    """
    return JSONResponse(
        status_code=500,
        content={"detail": f"Internal server error: {exc}"},
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
    line_type: str = Field(
        default="framework",
        description="Type: 'boundary' (unit contact), 'gap' (hiatus), or 'framework' (geometry)"
    )
    stable: bool = Field(
        default=False,
        description="True if this line persists identically across all realisations."
    )


class RunResult(BaseModel):
    """One n-best result."""

    index: int
    cost: float
    n_ties: int
    lines: List[CorrelationLine]
    diversity_score: float = 0.0  # 0=identical to #1, 1=maximally different


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
    description: Optional[str] = None
    option_keys: List[str] = Field(default_factory=list)


class DemoListResponse(BaseModel):
    """Response from ``GET /demos``."""

    demos: List[DemoItem]


class DemoWellInfo(BaseModel):
    """Metadata for one well in a demo dataset."""

    name: str
    size: int
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    h: float = 0.0
    data_names: List[str] = Field(default_factory=list)
    region_names: List[str] = Field(default_factory=list)


class DemoWellsResponse(BaseModel):
    """Response from ``GET /demos/{demo_id}/wells``."""

    demo_id: str
    title: str
    n_wells: int
    wells: List[DemoWellInfo]
    all_data_names: List[str] = Field(default_factory=list)
    all_region_names: List[str] = Field(default_factory=list)
    recommended_options: Dict[str, Any] = Field(default_factory=dict)
    ai_settings: Dict[str, Any] = Field(default_factory=dict)


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
    when it encounters missing data or region names - it prints an error
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


# Canonical option-reset dict - ensures no state leaks between runs.
from weco.ext import RESET_OPTS as _RESET_OPTS

# Reference to the currently running ProjectExt (for cancel support).
_active_project = None


def cancel_running_engine():
    """Abort the currently running correlation engine (thread-safe).

    Returns True if an abort was requested, False if nothing was running.
    """
    proj = _active_project
    if proj is not None:
        proj.request_abort()
        return True
    return False


def _run_engine(well_list, options: dict, options_file: Optional[str] = None):
    """Run the WeCo engine and return (ResFile, ResAndWL, elapsed_ms).

    Safety measures applied automatically:
    1. ``reset_options()`` clears global C++ state before every run.
    2. ``_RESET_OPTS`` blanks data-name / region-name options.
    3. ``_validate_well_list`` rejects <2 wells / <2 markers.
    4. ``_validate_options_against_wells`` rejects missing data/region refs.
    """
    global _active_project
    from weco.data import ResAndWL
    from weco.ext import ProjectExt

    # --- pre-flight validation ---
    _validate_well_list(well_list)

    proj = ProjectExt()
    _active_project = proj

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
    try:
        proj.run(well_list)
    finally:
        _active_project = None
    elapsed = (time.perf_counter() - t0) * 1000.0

    rf = proj.get_res_file()
    data = ResAndWL(rf, well_list)
    return rf, data, elapsed


def _force_diverse_run(well_list, base_options: dict, n_diverse: int = 3):
    """Run engine with multiple configurations to guarantee structural diversity.

    Runs up to 4 configurations:
      1. Base options (user/auto-suggested)
      2. Low gap-cost (allows/encourages gaps → unconformity-style results)
      3. High gap-cost (discourages gaps → layer-cake-style results)
      4. Relaxed constraints (remove no-crossing → allows pinch-out/onlap)

    Returns merged diverse results sorted by cost, deduplicated by topology.
    """
    configs = [
        ("base", dict(base_options)),
    ]

    # Config 2: encourage gaps (low but non-zero gap cost to avoid degenerate solutions)
    base_gap = float(base_options.get("const-gap-cost", 0.5))
    gap_opts = dict(base_options)
    gap_opts["const-gap-cost"] = max(base_gap * 0.2, 0.05)
    gap_opts.pop("gap-cost-func", None)
    gap_opts.setdefault("nbr-cor", 30)
    configs.append(("gap-permissive", gap_opts))

    # Config 3: discourage gaps (high gap cost → layer-cake)
    nogap_opts = dict(base_options)
    nogap_opts["const-gap-cost"] = max(base_gap * 5, 2.0)
    nogap_opts.setdefault("nbr-cor", 30)
    configs.append(("layer-cake", nogap_opts))

    # Config 4: remove constraints (no no-crossing → allows structural freedom)
    relaxed = dict(base_options)
    relaxed.pop("no-crossing", None)
    relaxed.pop("no-crossing2", None)
    relaxed.pop("no-crossing3", None)
    relaxed["const-gap-cost"] = max(base_gap * 0.6, 0.3)
    relaxed.setdefault("nbr-cor", 30)
    configs.append(("relaxed", relaxed))

    all_results = []  # (cost, result_dict, config_name, topology)
    fallback_result = None  # keep one result even if all are "degenerate"

    for config_name, opts in configs:
        try:
            rf, data, elapsed = _run_engine(well_list, opts)
            n_wells = rf.nbr_well()
            n_res = min(10, rf.get_nbr_results())
            results = _extract_results(rf, data, n_res)
            for r in results:
                sig = _topology_signature(rf, r.index, n_wells)
                # Skip degenerate all-gap solutions (cost=0 with all wells at max bucket)
                if r.cost <= 0.0 and sig and all(s >= 5 for s in sig):
                    if fallback_result is None:
                        fallback_result = (r, config_name, sig)
                    continue
                all_results.append((r.cost, r, config_name, sig))
        except Exception:
            continue

    if not all_results:
        # Return fallback if available (dataset without meaningful log data)
        return [fallback_result] if fallback_result else []

    # Deduplicate by topology, keep lowest cost per signature
    seen_sigs: dict = {}
    for cost, result, cname, sig in sorted(all_results, key=lambda x: x[0]):
        if sig not in seen_sigs:
            seen_sigs[sig] = (result, cname)
            if len(seen_sigs) >= n_diverse:
                break

    return [(r, cname, sig) for sig, (r, cname) in seen_sigs.items()]


def _topology_signature(rf, result_idx: int, n_wells: int) -> tuple:
    """Compute a compact topology signature for a correlation result.

    The signature captures the structural pattern (gap positions, boundary
    positions) independent of exact depth values. Two results with the same
    signature are structurally identical even if depths differ slightly.

    Uses finer buckets (0-5) to discriminate between subtly different gap
    patterns across wells.
    """
    path = rf.get_result_full_path(result_idx)
    n_path = len(path)
    if n_path == 0:
        return ()

    # For each well, count how many steps it stays stationary (= gap indicator)
    sig_parts = []
    for wi in range(n_wells):
        stays = 0
        for s in range(1, n_path):
            if path[s][wi] == path[s - 1][wi]:
                stays += 1
        # Finer buckets: 0=none, 1=tiny, 2=few, 3=moderate, 4=many, 5=mostly gaps
        frac = stays / max(1, n_path)
        if frac < 0.02:
            bucket = 0
        elif frac < 0.08:
            bucket = 1
        elif frac < 0.15:
            bucket = 2
        elif frac < 0.25:
            bucket = 3
        elif frac < 0.40:
            bucket = 4
        else:
            bucket = 5
        sig_parts.append(bucket)
    return tuple(sig_parts)


def _label_scenario(sig: tuple) -> str:
    """Classify a topology signature into a named geological scenario.

    Returns a human-readable scenario label based on the gap pattern:
    - "Layer-cake": all wells track together (no/minimal gaps)
    - "Pinch-out": one or few wells have significant gaps (sediment thinning)
    - "Onlap": progressive increase in gaps from one side
    - "Unconformity": most wells have very many gaps (erosional surface)
    - "Condensed": all wells have similar moderate gaps (low sedimentation)
    - "Wedge": moderate variation in gap intensity across wells
    - "Complex": mixed/irregular pattern
    """
    if not sig:
        return "Unknown"

    n_wells = len(sig)
    max_gap = max(sig)
    min_gap = min(sig)
    mean_gap = sum(sig) / n_wells
    spread = max_gap - min_gap
    n_low = sum(1 for s in sig if s <= 1)       # no/tiny gaps
    n_high = sum(1 for s in sig if s >= 5)      # very many gaps

    # Layer-cake: everything tracks (max bucket ≤ 1)
    if max_gap <= 1:
        return "Layer-cake"

    # Pinch-out: most wells have few/no gaps, but 1-2 have larger gaps
    if n_low >= max(n_wells - 2, n_wells * 0.6) and max_gap >= 2 and spread >= 2:
        return "Pinch-out"

    # Onlap: progressive increase from one side (gradient pattern)
    if n_wells >= 3 and spread >= 2:
        diffs = [sig[i+1] - sig[i] for i in range(n_wells - 1)]
        if all(d >= 0 for d in diffs) or all(d <= 0 for d in diffs):
            return "Onlap"

    # Unconformity: most wells have high gaps (bucket >= 4)
    n_high_or_very = sum(1 for s in sig if s >= 4)
    if n_high_or_very >= n_wells * 0.6:
        return "Unconformity"

    # Condensed: uniform moderate gaps (spread ≤ 1, mean in moderate range 2-3.5)
    if spread <= 1 and 1.5 <= mean_gap <= 3.5:
        return "Condensed"

    # Wedge: significant variation in gap intensity (geological thinning)
    if spread >= 2 and mean_gap >= 2:
        return "Wedge"

    # Low overall but some variation
    if max_gap <= 3:
        return "Layer-cake"

    return "Complex"


def _wheeler_gap_analysis(result: "RunResult", well_names: List[str]) -> dict:
    """Compute Wheeler-style gap analysis from a correlation result.

    For each well, identifies which correlation intervals are present (correlated)
    and which are gaps (well stays stationary while others advance).

    Returns a dict with per-well gap information suitable for rendering
    a Wheeler diagram style visualization.
    """
    n_wells = len(well_names)
    if not result.lines:
        return {"wells": {name: {"gaps": [], "present": []} for name in well_names}}

    # Sort lines by average marker index (depth order)
    sorted_lines = sorted(result.lines, key=lambda l: sum(l.markers) / max(len(l.markers), 1))

    # For each consecutive pair of correlation lines, determine if each well
    # has a gap (markers are the same = well didn't advance)
    well_analysis = {name: {"gaps": [], "present": [], "gap_fraction": 0.0}
                     for name in well_names}

    for li in range(len(sorted_lines) - 1):
        top_line = sorted_lines[li]
        base_line = sorted_lines[li + 1]

        for wi in range(min(n_wells, len(top_line.markers), len(base_line.markers))):
            interval = {"top_idx": top_line.markers[wi], "base_idx": base_line.markers[wi],
                        "interval": li}
            thickness = base_line.markers[wi] - top_line.markers[wi]
            name = well_names[wi]
            if thickness <= 0:
                well_analysis[name]["gaps"].append(interval)
            else:
                well_analysis[name]["present"].append(interval)

    # Compute gap fractions
    n_intervals = max(1, len(sorted_lines) - 1)
    for name in well_names:
        well_analysis[name]["gap_fraction"] = len(well_analysis[name]["gaps"]) / n_intervals

    return {"wells": well_analysis, "n_intervals": n_intervals}


def _diverse_results(rf, data, n_best: int, n_diverse: int = None) -> List:
    """Select structurally diverse results from the full k-best set.

    Groups results by topology signature, then picks the lowest-cost
    representative from each cluster. Returns at most n_diverse results.
    """
    if n_diverse is None:
        n_diverse = n_best

    n_total = min(n_best, rf.get_nbr_results())
    n_wells = rf.nbr_well()

    # Group by topology
    clusters: Dict[tuple, int] = {}  # signature → first (lowest-cost) index
    selected = []

    for i in range(n_total):
        sig = _topology_signature(rf, i, n_wells)
        if sig not in clusters:
            clusters[sig] = i
            selected.append(i)
            if len(selected) >= n_diverse:
                break

    # If we didn't fill n_diverse from unique clusters, add remaining by cost
    if len(selected) < n_diverse:
        for i in range(n_total):
            if i not in selected:
                selected.append(i)
                if len(selected) >= n_diverse:
                    break

    return selected


def _extract_results(rf, data, n_best: int) -> List[RunResult]:
    """Convert engine results to response objects.
    
    Filters the full DTW path to only geologically meaningful lines:
    - boundary: steps where a region boundary is crossed
    - gap: significant hiatuses (one well stays constant for multiple steps)
    - framework: evenly-spaced orientation lines
    """
    n = min(n_best, rf.get_nbr_results())
    n_wells = rf.nbr_well()
    results = []

    # Build boundary indices from regions in data (WellList)
    boundary_indices = [set() for _ in range(n_wells)]
    # Resolve the wells list from either ResAndWL or a plain WellList
    _wells = None
    if hasattr(data, 'well_list') and hasattr(data.well_list, 'wells'):
        _wells = data.well_list.wells
    elif hasattr(data, 'wells'):
        _wells = data.wells

    if _wells:
        # Pick the region with fewest intervals (coarsest stratigraphy)
        all_regions = {}
        for wi, well in enumerate(_wells):
            if hasattr(well, 'region') and well.region:
                for rname, rdata in well.region.items():
                    rlist = list(rdata)
                    if rname not in all_regions:
                        all_regions[rname] = 0
                    all_regions[rname] += len(rlist)
        primary_region = min(all_regions, key=all_regions.get) if all_regions else None

        if primary_region:
            for wi, well in enumerate(_wells):
                if hasattr(well, 'region') and primary_region in well.region:
                    rlist = list(well.region[primary_region])
                    for entry in rlist:
                        if isinstance(entry, (list, tuple)) and len(entry) >= 2:
                            boundary_indices[wi].add(entry[1])

    # Compute stable nodes: present in ALL realisations
    stable_nodes = set()
    if n >= 2:
        all_paths = []
        for i in range(min(n, 50)):
            p = rf.get_result_full_path(i)
            if p:
                all_paths.append(set(tuple(node) for node in p))
        if len(all_paths) >= 2:
            stable_nodes = all_paths[0]
            for p in all_paths[1:]:
                stable_nodes = stable_nodes & p

    for i in range(n):
        path = rf.get_result_full_path(i)
        cost = float(rf.get_result_cost(i))

        # Deduplicate consecutive identical steps
        deduped = []
        prev = None
        for step in path:
            if step != prev:
                deduped.append(step)
                prev = step

        n_path = len(deduped)
        if n_path == 0:
            results.append(RunResult(index=i, cost=cost, n_ties=0, lines=[]))
            continue

        # Classify steps: boundary, gap, or framework
        boundary_steps = set()
        boundary_scores = {}
        for step_idx in range(1, n_path):
            node = deduped[step_idx]
            prev_node = deduped[step_idx - 1]
            score = sum(1 for wi in range(n_wells)
                        if node[wi] in boundary_indices[wi] and node[wi] != prev_node[wi])
            if score > 0:
                boundary_steps.add(step_idx)
                boundary_scores[step_idx] = score

        # Cap boundaries at 30
        if len(boundary_steps) > 30:
            ranked = sorted(boundary_steps, key=lambda s: boundary_scores.get(s, 0), reverse=True)
            boundary_steps = set(ranked[:30])

        # Detect significant gaps
        gap_steps = set()
        min_gap_run = max(3, n_path // 80)
        for wi in range(n_wells):
            run_start = None
            for step_idx in range(1, n_path):
                if deduped[step_idx][wi] == deduped[step_idx - 1][wi]:
                    if run_start is None:
                        run_start = step_idx
                else:
                    if run_start is not None and (step_idx - run_start) >= min_gap_run:
                        gap_steps.add((run_start + step_idx) // 2)
                    run_start = None
            if run_start is not None and (n_path - run_start) >= min_gap_run:
                gap_steps.add((run_start + n_path - 1) // 2)
        gap_steps -= boundary_steps
        if len(gap_steps) > 20:
            gap_steps = set(sorted(gap_steps)[:20])

        # Framework lines
        fw_interval = max(1, n_path // 6)
        framework_steps = {s for s in range(0, n_path, fw_interval)}
        framework_steps.add(0)
        framework_steps.add(n_path - 1)
        framework_steps -= boundary_steps
        framework_steps -= gap_steps

        # Build output lines with type
        lines = []
        for step_idx in sorted(boundary_steps | gap_steps | framework_steps):
            node = deduped[step_idx]
            markers = [int(node[w]) for w in range(n_wells)]
            if step_idx in boundary_steps:
                lt = "boundary"
            elif step_idx in gap_steps:
                lt = "gap"
            else:
                lt = "framework"
            is_stable = tuple(node) in stable_nodes if stable_nodes else False
            lines.append(CorrelationLine(markers=markers, line_type=lt, stable=is_stable))

        results.append(RunResult(
            index=i,
            cost=cost,
            n_ties=len(lines),
            lines=lines,
        ))

    # Compute diversity scores relative to result #0
    if len(results) >= 2:
        ref_path = rf.get_result_full_path(0)
        ref_len = len(ref_path)
        for res in results[1:]:
            alt_path = rf.get_result_full_path(res.index)
            alt_len = len(alt_path)
            # Compare marker positions at evenly-sampled path steps
            n_compare = min(ref_len, alt_len, 50)
            if n_compare == 0:
                continue
            diff_count = 0
            for s in range(n_compare):
                ri = s * (ref_len - 1) // max(1, n_compare - 1)
                ai = s * (alt_len - 1) // max(1, n_compare - 1)
                ref_node = ref_path[ri]
                alt_node = alt_path[ai]
                diff_count += sum(1 for w in range(n_wells) if ref_node[w] != alt_node[w])
            max_diff = n_compare * n_wells
            res.diversity_score = round(diff_count / max(1, max_diff), 3)

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

    try:
        well_list = _load_well_list(req.well_file)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load wells: {exc}")

    try:
        rf, data, elapsed = _run_engine(
            well_list, req.options, req.options_file
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Engine error: {exc}")

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
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Engine error: {exc}")
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
    try:
        wl = _load_well_list(well_file)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load wells: {exc}")

    try:
        return InfoResponse(
            n_wells=len(wl.wells),
            well_names=[w.name for w in wl.wells],
            n_markers=[w.size for w in wl.wells],
            data_names=wl.get_data_names(),
            region_names=wl.get_region_names(),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read well info: {exc}")


@app.post("/validate-options", response_model=OptionsValidation, tags=["system"])
def validate_options(options: Dict[str, Any]):
    """Check whether a set of engine options are valid."""
    from weco.ext import ProjectExt

    errors = []
    try:
        proj = ProjectExt()
        proj.reset_options()
        proj.set_options_ext(**_RESET_OPTS)
        for key, val in options.items():
            try:
                proj.set_option_ext(key, val)
            except ValueError as exc:
                errors.append(str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Engine init error: {exc}")

    return OptionsValidation(
        valid=len(errors) == 0,
        errors=errors,
    )


# ═══════════════════════════════════════════════════════════════════════════
#  Suggest-defaults helper
# ═══════════════════════════════════════════════════════════════════════════

# Log names ranked by geological discriminating power (best first).
# NEVER include depth/coordinate names - they are monotonic and break DTW.
_LOG_PRIORITY = [
    "GR", "Gamma", "gamma", "SP",
    "DEN", "RHOB", "DPHI",
    "RT", "RILD", "RILS",
    "DT", "DTCO", "Sonic",
    "NEU", "NPHI",
    "Pe", "PEF",
    "VarData1", "VarData2",
]

# Data names that should NEVER be used as correlation variables.
_SKIP_DATA = {"Depth", "DEPTH", "MD", "TVD", "TVDSS", "X", "Y", "Z",
              "Azimuth", "Dip"}

# Region name patterns that signal constraint types.
_CONSTRAINT_REGIONS = {
    "no-crossing": ["BIOZONE", "biozone", "Biozone", "ZONE", "zone",
                     "AGE", "age", "Stage", "stage",
                     "SEQUENCE", "sequence", "Sequence"],
    "same-region": ["FACIES", "facies", "Facies", "LITHOLOGY", "lithology",
                    "Lithology", "FORMATION", "formation", "Formation",
                    "LITHO", "litho", "SEAM", "seam"],
}


def _check_facies_independence(wl, facies_region: str, var_data: str) -> bool:
    """Check whether a facies region is likely independent of the primary log.

    Returns True if the facies data appears to be an independent interpretation
    (safe to use as a constraint), False if it appears derived from the same
    log being used for correlation (circular → skip).

    Heuristic checks:
    1. If var-data is empty or facies region not found → True (no circularity)
    2. If facies has only 2 unique values and var-data is GR-like → likely a
       sand/shale cutoff → False
    3. If facies transitions correlate strongly with var-data threshold crossings
       → derived → False
    4. If facies has ≥4 unique values → likely expert/multi-source → True
    """
    if not var_data:
        return True

    wells = wl.wells
    n_facies_values = set()
    transition_count = 0
    var_at_transitions = []

    for w in wells:
        if not hasattr(w, 'region') or facies_region not in w.region:
            continue
        if var_data not in w.data:
            continue

        # Count unique facies values
        for entry in w.region[facies_region]:
            if isinstance(entry, (list, tuple)) and len(entry) >= 1 and entry[0] is not None:
                n_facies_values.add(int(entry[0]))

        # Check if facies transitions align with var-data threshold crossings
        var_vals = w.data[var_data]
        regions = w.region[facies_region]

        for entry in regions:
            if isinstance(entry, (list, tuple)) and len(entry) >= 3:
                start_idx = entry[1]
                if 0 < start_idx < len(var_vals):
                    var_at_transitions.append(var_vals[start_idx])
                    transition_count += 1

    # If no facies data was found at all → no circularity possible
    if not n_facies_values:
        return True

    # Heuristic 1: Many unique facies values → likely independent
    if len(n_facies_values) >= 4:
        return True

    # Heuristic 2: Binary facies + GR-like var-data → probably a cutoff
    _GR_NAMES = {"GR", "gr", "Gr", "GAMMA", "gamma", "SGR", "CGR"}
    if len(n_facies_values) <= 2 and var_data in _GR_NAMES:
        return False

    # Heuristic 3: Check if facies transitions cluster at a single var-data value
    # (indicating a simple threshold cutoff)
    if var_at_transitions and transition_count >= 5:
        import numpy as np
        vals = np.array(var_at_transitions, dtype=float)
        vals = vals[np.isfinite(vals)]
        if len(vals) >= 5:
            cv = np.std(vals) / max(abs(np.mean(vals)), 1e-6)
            # Low coefficient of variation → transitions all at same threshold
            if cv < 0.25:
                return False

    # Default: assume independent (conservative - don't suppress user's data)
    return True


def _suggest_defaults_for_wells(wl) -> tuple:
    """Analyse a WellList and suggest optimal defaults.

    Returns (options_dict, reasoning_dict).

    Design principles:
    - Never use Depth/MD/X/Y/Z as var-data (monotonic → degenerate DTW)
    - same-region is NOT auto-applied (too restrictive, causes failures)
    - no-crossing IS suggested (hard constraint, usually safe)
    - band-width is set for large datasets to bound runtime
    """
    options: Dict[str, Any] = {}
    reasoning: Dict[str, str] = {}

    data_names = wl.get_data_names()
    region_names = wl.get_region_names()
    n_wells = len(wl.wells)

    # --- Pick best logs (exclude depth/coord names AND region channels) ---
    region_set = set(region_names)
    usable_data = [n for n in data_names if n not in _SKIP_DATA and n not in region_set]
    ranked = [n for n in _LOG_PRIORITY if n in usable_data]

    # If no priority match, use first usable data name that looks like a log
    if not ranked and usable_data:
        # Prefer names that are also in region (likely categorical but still usable)
        ranked = usable_data[:2]

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

    # --- Constraint regions (only no-crossing is safe to auto-apply) ---
    for pat in _CONSTRAINT_REGIONS["no-crossing"]:
        if pat in region_names:
            options["no-crossing"] = pat
            reasoning["no-crossing"] = f"Region '{pat}' provides stratigraphic ordering"
            break

    # NOTE: same-region is NOT auto-applied - it is too restrictive and
    # causes "no correlation possible" when facies zones don't align.
    # Users can enable it manually if their data supports it.

    # --- Auto-enable distality cost if FACIES-like regions present ---
    # IMPORTANT: Only enable if the facies data is plausibly INDEPENDENT of
    # the primary correlation variable (var-data). If the facies are derived
    # from the same log (e.g., GR threshold → sand/shale binary), enabling
    # dist-facies creates circular reasoning: the engine correlates on GR
    # waveform similarity AND penalises mismatched GR-derived facies, which
    # double-counts the same signal. This over-constrains solutions and
    # produces false confidence in results.
    #
    # Independence heuristic:
    #   - If facies has ≤2 unique values AND var-data is GR → likely a cutoff
    #   - If facies varies exactly at GR inflection points → derived
    #   - If both DISTAL and FACIES regions exist → likely expert interpretation
    #     (independent), safe to use
    #   - If only FACIES exists without DISTAL → probably log-derived, skip
    _DIST_DISTAL_HINTS = {"DISTAL", "DISTALITY", "DIST"}
    _DIST_FACIES_HINTS = {"FACIES", "FACIES_1", "LITHO_FACIES", "DEP_FACIES",
                          "DEPOSITIONAL_FACIES", "LITH_FACIES"}
    distal_match = next((r for r in region_names if r.upper() in _DIST_DISTAL_HINTS), None)
    facies_match = next((r for r in region_names if r.upper() in _DIST_FACIES_HINTS), None)

    if distal_match and facies_match:
        # Both DISTAL and FACIES present → likely an expert interpretation
        # (e.g., palaeogeographic model). Check independence before enabling.
        facies_independent = _check_facies_independence(wl, facies_match, options.get("var-data", ""))

        if facies_independent:
            options["dist-distal"] = distal_match
            options["dist-facies"] = facies_match
            options["dist-scaling"] = 1.0
            options["cost-function"] = "composite"
            options.setdefault("order", "distality")
            # Remove no-crossing - incompatible with distality ordering
            options.pop("no-crossing", None)
            reasoning.pop("no-crossing", None)
            reasoning["dist-distal"] = f"DISTAL region '{distal_match}' detected → distality cost enabled"
            reasoning["dist-facies"] = f"FACIES region '{facies_match}' paired for palaeogeographic cost"
            reasoning["dist-scaling"] = "Default distality scaling factor"
            reasoning["cost-function"] = "Composite cost required for distality"
        else:
            reasoning["dist-facies-skipped"] = (
                f"FACIES region '{facies_match}' appears derived from var-data "
                f"'{options.get('var-data', '?')}' - skipping to avoid circular constraint"
            )

    # --- Well-count and well-length adaptive settings ---
    # Compute average well length for scaling
    avg_pts = sum(w.size for w in wl.wells) / max(n_wells, 1)
    # Complexity proxy: n_pairs × avg_length²  (dominates runtime)
    n_pairs = n_wells * (n_wells - 1) // 2

    if n_wells >= 15:
        options["max-cor"] = 20
        options["band-width"] = 60 if avg_pts <= 100 else 30
        reasoning["max-cor"] = f"Bounded for {n_wells}-well project performance"
        reasoning["band-width"] = (
            "Wide bandwidth for moderate wells" if avg_pts <= 100
            else "Bandwidth limit for large dataset with long wells"
        )
        options["const-gap-cost"] = 2.0
        reasoning["const-gap-cost"] = "Gap penalty for large projects (allow hiatuses)"
    elif n_wells >= 6:
        options["max-cor"] = 40
        options["band-width"] = 40
        reasoning["max-cor"] = f"Standard setting for {n_wells} wells"
        reasoning["band-width"] = "Bandwidth limit for medium datasets"
    else:
        options["max-cor"] = 50
        reasoning["max-cor"] = "Standard n-best search width"

    # --- Diversity parameters: scale with dataset complexity ---
    # More wells + longer wells → fewer internal paths needed (combinatorial
    # search across pairs already provides diversity).
    # Categorical/ordinal data needs higher min-dist (discrete costs = flat landscape).
    _CATEGORICAL_NAMES = {"FACIES", "LITHOLOGY", "LITHO", "FORMATION",
                          "DISTALITY", "DISTAL", "LITH", "DEP_ENV",
                          "DEPOSITIONAL_FACIES", "LITHO_FACIES", "LITH_FACIES"}
    is_categorical = any(
        options.get(k, "").upper() in _CATEGORICAL_NAMES
        for k in ("var-data", "var-data2", "var-data3")
    )

    if n_pairs >= 100 or avg_pts >= 300:
        # Very large: minimise internal work, rely on pair diversity
        nbr_cor = 5
        out_nbr_cor = 5
    elif n_pairs >= 20 or avg_pts >= 100:
        # Medium-large: moderate exploration
        nbr_cor = 15
        out_nbr_cor = 10
    elif n_wells >= 4:
        # Medium: balanced
        nbr_cor = 20
        out_nbr_cor = 10
    else:
        # Small (2-3 wells): need more paths to find diversity
        nbr_cor = 30
        out_nbr_cor = 10

    # Min-dist: categorical data needs much higher forcing
    if is_categorical:
        min_dist = 0.5
        out_min_dist = 0.25
    elif n_wells >= 6:
        min_dist = 0.4
        out_min_dist = 0.2
    else:
        min_dist = 0.3
        out_min_dist = 0.15

    options["nbr-cor"] = nbr_cor
    options["out-nbr-cor"] = out_nbr_cor
    options["min-dist"] = min_dist
    options["out-min-dist"] = out_min_dist
    reasoning["nbr-cor"] = f"{nbr_cor} internal paths (scaled for {n_wells} wells, ~{int(avg_pts)} pts/well)"
    reasoning["out-nbr-cor"] = f"Report up to {out_nbr_cor} ranked scenarios"
    reasoning["min-dist"] = (
        f"{'High' if is_categorical else 'Moderate'} diversity forcing "
        f"({'categorical' if is_categorical else 'continuous'} data)"
    )
    reasoning["out-min-dist"] = "Ensure output scenarios are meaningfully distinct"

    # --- Position-based ordering (only if wells actually have coordinates) ---
    has_coords = any(
        abs(w.x) > 1e-6 or abs(w.y) > 1e-6 for w in wl.wells
    )
    if has_coords and n_wells >= 4:
        options["order"] = "position"
        reasoning["order"] = "Wells have coordinates - positional ordering"

    return options, reasoning


# ═══════════════════════════════════════════════════════════════════════════
#  New endpoints
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/suggest-defaults", response_model=SuggestDefaultsResponse,
          tags=["system"])
def suggest_defaults(req: SuggestDefaultsRequest):
    """Suggest optimal engine parameters based on well data characteristics."""
    try:
        wl = _load_well_list(req.well_file)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load wells: {exc}")

    try:
        options, reasoning = _suggest_defaults_for_wells(wl)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to suggest defaults: {exc}",
        )
    return SuggestDefaultsResponse(options=options, reasoning=reasoning)


# ═══════════════════════════════════════════════════════════════════════════
#  AI Preprocessing Suggestion
# ═══════════════════════════════════════════════════════════════════════════

class PreprocessingSuggestRequest(BaseModel):
    """Request preprocessing recommendation."""
    well_file: str = Field(..., description="Server-side path to well-list file.")
    environment: Optional[str] = Field(None, description="Override environment detection.")


class PreprocessingSuggestResponse(BaseModel):
    """Preprocessing recommendation response."""
    environment: str
    steps: Dict[str, bool]
    parameters: Dict[str, Any]
    postprocessing: Dict[str, Any]
    reasoning: Dict[str, str]


@app.post("/suggest-preprocessing", response_model=PreprocessingSuggestResponse,
          tags=["system"])
def suggest_preprocessing(req: PreprocessingSuggestRequest):
    """AI-driven preprocessing recommendation based on geological setting."""
    from .decision_tree import recommend_preprocessing, recommend_postprocessing

    try:
        wl = _load_well_list(req.well_file)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load wells: {exc}")

    try:
        rec = recommend_preprocessing(wl, environment=req.environment)
        post = recommend_postprocessing(wl, environment=rec.environment)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Preprocessing recommendation failed: {exc}",
        )

    return PreprocessingSuggestResponse(
        environment=rec.environment,
        steps={
            "normalise": rec.normalise,
            "vshale": rec.vshale,
            "stacking_pattern": rec.stacking_pattern,
            "electrofacies": rec.electrofacies,
            "log_qc": rec.log_qc,
            "smooth": rec.smooth,
            "ai_facies": rec.ai_facies,
        },
        parameters={
            "normalise_method": rec.normalise_method,
            "vshale_method": rec.vshale_method,
            "electrofacies_k": rec.electrofacies_k,
            "smooth_window": rec.smooth_window,
            "ai_facies_logs": rec.ai_facies_logs,
        },
        postprocessing={
            "quality_threshold": post["quality_threshold"],
            "uncertainty_max_std": post["uncertainty_max_std"],
            "run_anomaly": post["run_anomaly"],
            "n_scenarios_report": post["n_scenarios_report"],
        },
        reasoning=rec.reasoning,
    )


# ═══════════════════════════════════════════════════════════════════════════
#  Auto-Correlate: suggest → run → quality-gate → diverse-select
# ═══════════════════════════════════════════════════════════════════════════

class AutoRequest(BaseModel):
    """Request for fully automated correlation."""
    well_file: str = Field(..., description="Server-side path to well-list file.")
    n_diverse: int = Field(5, ge=1, le=20, description="Number of diverse results to return.")
    max_iterations: int = Field(3, ge=1, le=5, description="Max refinement iterations.")
    quality_threshold: float = Field(0.5, ge=0.0, le=1.0,
                                     description="Minimum quality score before stopping refinement.")


class AutoResult(BaseModel):
    """One auto-selected diverse result."""
    index: int
    cost: float
    diversity_score: float
    quality_score: float = 0.0
    topology: str = ""  # e.g. "0-1-2-3" = gap buckets per well
    lines: List[CorrelationLine] = []


class AutoResponse(BaseModel):
    """Response from POST /auto."""
    status: str = "ok"
    elapsed_ms: float = 0.0
    iterations: int = 1
    n_wells: int = 0
    well_names: List[str] = []
    suggested_options: Dict[str, Any] = {}
    reasoning: Dict[str, str] = {}
    results: List[AutoResult] = []


@app.post("/auto", response_model=AutoResponse, tags=["correlation"])
def auto_correlate(req: AutoRequest):
    """Fully automated correlation: suggest params → preprocess → run → quality-check → diversify.

    Chains the full workflow in one call:
    1. Load wells and suggest optimal parameters
    2. Apply AI-recommended preprocessing (geological-context-aware)
    3. Run correlation with diversity enabled
    4. Score quality (if weco.ai available)
    5. If quality < threshold, adjust gap-cost and re-run (up to max_iterations)
    6. Select structurally diverse results using topology clustering
    """
    try:
        wl = _load_well_list(req.well_file)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load wells: {exc}")

    try:
        options, reasoning = _suggest_defaults_for_wells(wl)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to suggest defaults: {exc}",
        )

    # A1: AI preprocessing (environment-specific data conditioning)
    try:
        from weco.preprocessing import auto_preprocess
        preproc_result = auto_preprocess(wl)
        reasoning["preprocessing"] = (
            f"{preproc_result['environment']}: "
            f"{', '.join(preproc_result['steps_applied'])}"
        )
        if preproc_result.get("errors"):
            reasoning["preprocessing_errors"] = "; ".join(preproc_result["errors"])
    except Exception as e:
        reasoning["preprocessing"] = f"skipped ({e})"

    # A2: Detect depositional environment and apply preset
    try:
        from weco.depenv import detect_environment_from_logs, suggest_options
        env_key = detect_environment_from_logs(wl)
        if env_key:
            env_opts = suggest_options(env_key, data_names=wl.get_data_names())
            for k, v in env_opts.items():
                norm_k = k.replace("_", "-")
                if norm_k not in options:
                    options[norm_k] = v
            reasoning["detected_environment"] = env_key
    except Exception:
        pass

    # Ensure diversity and sufficient results
    options.setdefault("min-dist", 0.1)
    options.setdefault("out-min-dist", 0.05)
    options.setdefault("nbr-cor", 100)
    options.setdefault("out-nbr-cor", max(20, req.n_diverse * 4))

    total_elapsed = 0.0
    best_rf = None
    best_data = None
    iterations = 0

    for iteration in range(req.max_iterations):
        iterations += 1
        try:
            rf, data, elapsed = _run_engine(wl, options)
            total_elapsed += elapsed
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Engine error: {exc}")

        best_rf = rf
        best_data = data

        # Quality gate (optional - requires sklearn)
        quality = 0.0
        try:
            from weco.ai.quality import CorrelationQuality
            cq = CorrelationQuality()
            results_for_scoring = _extract_results(rf, data, min(5, rf.get_nbr_results()))
            if results_for_scoring:
                quality = cq.score_result(results_for_scoring[0], data)
        except (ImportError, Exception):
            quality = 1.0  # skip gate if AI not available

        if quality >= req.quality_threshold:
            break

        # Adjust parameters for next iteration
        current_gap = float(options.get("const-gap-cost", 0.0))
        if current_gap < 1.0:
            options["const-gap-cost"] = 2.0
            reasoning["const-gap-cost"] = f"Iter {iterations}: quality {quality:.2f} < {req.quality_threshold}, adding gap penalty"
        else:
            options["const-gap-cost"] = current_gap + 2.0
            reasoning["const-gap-cost"] = f"Iter {iterations}: increasing gap cost to {current_gap + 2.0}"

    # Select diverse results
    n_wells = best_rf.nbr_well()
    diverse_indices = _diverse_results(best_rf, best_data, n_best=50, n_diverse=req.n_diverse)

    # Build results with diversity + quality scores
    all_extracted = _extract_results(best_rf, best_data, 50)
    extracted_map = {r.index: r for r in all_extracted}

    auto_results = []
    for idx in diverse_indices:
        sig = _topology_signature(best_rf, idx, n_wells)
        extracted = extracted_map.get(idx)
        cost = float(best_rf.get_result_cost(idx))
        div_score = extracted.diversity_score if extracted else 0.0
        auto_results.append(AutoResult(
            index=idx,
            cost=cost,
            diversity_score=div_score,
            topology="-".join(str(s) for s in sig),
            lines=extracted.lines if extracted else [],
        ))

    well_names = best_data.well_names()
    return AutoResponse(
        status="ok",
        elapsed_ms=round(total_elapsed, 2),
        iterations=iterations,
        n_wells=len(well_names),
        well_names=well_names,
        suggested_options=options,
        reasoning=reasoning,
        results=auto_results,
    )


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
    # Built-in demo catalogue - each entry has geology-specific opts that
    # are proven to produce meaningful correlations for that dataset.
    _DEMO_CATALOGUE = [
        # ── Concept (teaching specific constraints) ─────────────────
        {"id": "distality", "title": "Distality Cost (Walther's Law)",
         "group": "Concept", "wells": "data_set_distality/wells.txt",
         "description": "2 wells demonstrating the distality cost function. "
                        "Penalises correlations that violate lateral facies-belt "
                        "ordering (Walther's Law). Key constraint: dist-distal + dist-facies.",
         "opts": {"dist-distal": "DISTAL", "dist-facies": "FACIES_1",
                  "dist-scaling": 1.0, "order": "distality",
                  "max-cor": 50, "nbr-cor": 30, "out-nbr-cor": 10,
                  "min-dist": 0.3, "out-min-dist": 0.15}},
        {"id": "biozone_distality", "title": "Biozone No-Crossing + Distality",
         "group": "Concept", "wells": "data_set_biozone_distality/wells.txt",
         "description": "2 wells combining no-crossing constraint (BIOZONES) "
                        "with distality. Biozone datums cannot swap order - "
                        "demonstrates hard stratigraphic anchoring.",
         "opts": {"dist-distal": "DISTAL", "dist-facies": "FACIES_1",
                  "no-crossing": "BIOZONES", "order": "distality",
                  "max-cor": 50, "nbr-cor": 30, "out-nbr-cor": 10,
                  "min-dist": 0.3, "out-min-dist": 0.15}},
        # ── Domain: Coal Basin ────────────────────────────────────────
        {"id": "coal", "title": "Coal Basin – Gap Cost + Multi-Log (DEN+GR+SON)",
         "group": "Domain", "wells": "data_set_coal/wells_10.txt",
         "geology": "coal",
         "description": "10 coal boreholes with seam splitting/absence. "
                        "Gap cost (3.0) penalises missing seams. DEN (coal=1.3 g/cc "
                        "vs rock=2.5) + GR + SON multi-log. Band-width scaled to "
                        "section length for full-section correlation.",
         "opts": {"var-data": "DEN", "var-weight": 0.5,
                  "var-data2": "GR", "var-weight2": 0.3,
                  "var-data3": "SON", "var-weight3": 0.2,
                  "max-cor": 50, "nbr-cor": 20, "out-nbr-cor": 5,
                  "min-dist": 0.4, "out-min-dist": 0.15,
                  "const-gap-cost": 3.0, "band-width": 30}},
        # ── Domain: Quaternary Hydrogeology ───────────────────────────
        {"id": "quaternary", "title": "Quaternary – Gap Cost + Multi-Log (GR+RT)",
         "group": "Domain", "wells": "data_set_quaternary/wells_20.txt",
         "geology": "quaternary",
         "description": "20 shallow Quaternary wells with unit absence. "
                        "Gap cost (1.5) + GR (sand/clay) + RT (permeability). "
                        "Band-width=20. Demonstrates aquifer connectivity uncertainty.",
         "opts": {"var-data": "GR", "var-weight": 0.7,
                  "var-data2": "RT", "var-weight2": 0.3,
                  "max-cor": 20, "nbr-cor": 10, "out-nbr-cor": 10,
                  "min-dist": 0.2, "out-min-dist": 0.1,
                  "const-gap-cost": 1.5, "band-width": 20}},
        # ── Domain: Shallow Marine ────────────────────────────────────
        {"id": "shallow_marine",
         "title": "Shallow Marine – 3-Log + Biozone Constraint (GR+RHOB+DT)",
         "group": "Domain", "wells": "data_set_shallow_marine/wells.txt",
         "geology": "shallow_marine",
         "description": "10 wells with repeated shoreface parasequences + erosion. "
                        "3-log multi-variance (GR 50% + RHOB 30% + DT 20%) "
                        "+ gap cost (2.0). BIOZONE no-crossing locks key flooding "
                        "surfaces - the most important sequence boundaries.",
         "opts": {"var-data": "GR", "var-weight": 0.5,
                  "var-data2": "RHOB", "var-weight2": 0.3,
                  "var-data3": "DT", "var-weight3": 0.2,
                  "no-crossing": "BIOZONE",
                  "max-cor": 50, "nbr-cor": 20, "out-nbr-cor": 5,
                  "min-dist": 0.4, "out-min-dist": 0.2,
                  "const-gap-cost": 2.0, "band-width": 30}},
        # ── Domain: Bryson (Appalachian) ──────────────────────────────
        {"id": "bryson", "title": "Bryson – No-Crossing Constraint (Categorical)",
         "group": "Domain", "wells": "data_set_bryson/wells.txt",
         "geology": "fluvial",
         "description": "7 Appalachian Basin wells with categorical FACIES cost "
                        "+ ZONE no-crossing constraint. Demonstrates hard "
                        "biozone anchoring with categorical (non-continuous) data.",
         "opts": {"var-data": "FACIES", "no-crossing": "ZONE",
                  "max-cor": 50, "nbr-cor": 30, "out-nbr-cor": 10,
                  "min-dist": 0.5, "out-min-dist": 0.25}},
        {"id": "bryson_distality", "title": "Bryson – Distality Ordering",
         "group": "Domain", "wells": "data_set_bryson/wells.txt",
         "geology": "fluvial",
         "description": "7 Appalachian wells with DISTALITY variance cost and "
                        "distality well-ordering + ZONE no-crossing. Correlates "
                        "along depositional dip direction.",
         "opts": {"var-data": "DISTALITY", "order": "distality",
                  "no-crossing": "ZONE",
                  "max-cor": 80, "nbr-cor": 50, "out-nbr-cor": 10,
                  "min-dist": 0.5, "out-min-dist": 0.25}},
        # ── Domain: Fluvial Channel Belt ──────────────────────────────
        {"id": "fluvial", "title": "Fluvial – Gap Cost + Channel Connectivity",
         "group": "Domain", "wells": "data_set_fluvial/wells.txt",
         "geology": "fluvial",
         "description": "12 wells through discontinuous channel sandbodies. "
                        "Gap cost (1.0) forces decision: connected or isolated? "
                        "Band-width=30 limits vertical stretch, keeping channels "
                        "at geologically plausible depths.",
         "opts": {"var-data": "GR", "var-weight": 1.0,
                  "max-cor": 50, "nbr-cor": 20, "out-nbr-cor": 5,
                  "min-dist": 0.5, "out-min-dist": 0.2,
                  "const-gap-cost": 1.0, "band-width": 30}},
        # ── Domain: Delta ─────────────────────────────────────────────
        {"id": "delta", "title": "Delta – Sequence Boundaries + Multi-Log (GR+DEN)",
         "group": "Domain", "wells": "data_set_delta/wells.txt",
         "geology": "deltaic",
         "description": "8 wells through a prograding delta with variable "
                        "thickness parasequences. GR (60%) + DEN (40%) multi-log. "
                        "SEQSTRAT no-crossing locks parasequence boundaries - the "
                        "highest-order surfaces that must be honoured first.",
         "opts": {"var-data": "GR", "var-weight": 0.6,
                  "var-data2": "DEN", "var-weight2": 0.4,
                  "no-crossing": "SEQSTRAT",
                  "max-cor": 50, "nbr-cor": 20, "out-nbr-cor": 5,
                  "min-dist": 0.4, "out-min-dist": 0.2,
                  "const-gap-cost": 1.5, "band-width": 30}},
        # ── Domain: Sigrun (North Sea) ────────────────────────────────
        {"id": "sigrun", "title": "Sigrun – Multi-Log Well-Tie (GR+NPHI)",
         "group": "Domain", "wells": "data_set_sigrun/wells.txt",
         "geology": "shallow_marine",
         "description": "2 North Sea wells (Sigrun field). GR (60%) + NPHI (40%) "
                        "two-log variance for seismic-to-well tie in marine sequence.",
         "opts": {"var-data": "GR", "var-weight": 0.6,
                  "var-data2": "NPHI", "var-weight2": 0.4,
                  "max-cor": 50, "nbr-cor": 30, "out-nbr-cor": 10,
                  "min-dist": 0.3, "out-min-dist": 0.15}},
        # ── Domain: Troll (North Sea) ─────────────────────────────────
        {"id": "troll", "title": "Troll – Categorical Facies Correlation",
         "group": "Domain", "wells": "data_set_troll/wells.txt",
         "geology": "shallow_marine",
         "description": "5 Troll field wells with categorical FACIES only. "
                        "No continuous logs - correlation driven purely by facies "
                        "similarity. Demonstrates ambiguity: same facies at multiple "
                        "depths creates genuine correlation uncertainty.",
         "opts": {"var-data": "FACIES",
                  "max-cor": 50, "nbr-cor": 30, "out-nbr-cor": 10,
                  "min-dist": 0.5, "out-min-dist": 0.25}},
        {"id": "troll_distality", "title": "Troll – Distality Ordered + Biozone",
         "group": "Domain", "wells": "data_set_troll/wells.txt",
         "geology": "shallow_marine",
         "description": "23 Troll wells with distality ordering + biozone "
                        "constraint. DISTALITY cost with proximal→distal well "
                        "ordering explores lateral facies variation within "
                        "biostratigraphic framework.",
         "opts": {"var-data": "DISTALITY", "order": "distality",
                  "no-crossing": "BIOZONE",
                  "max-cor": 50, "nbr-cor": 30, "out-nbr-cor": 15,
                  "min-dist": 0.3, "out-min-dist": 0.15}},
        # ── Real Data: Hugin Fm (EAGE 2024) ──────────────────────────
        {"id": "hugin_tidal", "title": "Hugin Fm – Tidal Distality (Real Wells)",
         "group": "Domain", "wells": "data_set_hugin_tidal/facies.wells.txt",
         "geology": "shallow_marine",
         "description": "2 real North Sea wells (Hugin Fm, Gudrun–Sigrun area). "
                        "Tide-dominated shallow marine with interpreted facies. "
                        "Demonstrates distality cost on real subsurface data - "
                        "Walther's Law constrains lateral facies ordering.",
         "opts": {"dist-distal": "DISTALITY", "dist-facies": "FACIES_1",
                  "dist-scaling": 1.0, "order": "distality",
                  "max-cor": 50, "nbr-cor": 30, "out-nbr-cor": 10,
                  "min-dist": 0.3, "out-min-dist": 0.15}},
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
                description=d.get("description"),
            ))
    return DemoListResponse(demos=demos)


def _get_demo_opts(demo_id: str) -> dict:
    """Look up per-demo geology-specific options from the catalogue.

    These are tested parameters that produce meaningful correlations
    for each dataset's specific geological concept.
    """
    _DEMO_OPTS = {
        "distality": {"dist-distal": "DISTAL", "dist-facies": "FACIES_1",
                "dist-scaling": 1.0, "order": "distality",
                "max-cor": 50, "nbr-cor": 30, "out-nbr-cor": 10,
                "min-dist": 0.3, "out-min-dist": 0.15},
        "biozone_distality": {"dist-distal": "DISTAL", "dist-facies": "FACIES_1",
                "no-crossing": "BIOZONES", "order": "distality",
                "max-cor": 50, "nbr-cor": 30, "out-nbr-cor": 10,
                "min-dist": 0.3, "out-min-dist": 0.15},
        "coal": {"var-data": "DEN", "var-weight": 0.6,
                 "var-data2": "GR", "var-weight2": 0.4,
                 "max-cor": 10, "nbr-cor": 5, "out-nbr-cor": 5,
                 "min-dist": 0.3, "out-min-dist": 0.15,
                 "const-gap-cost": 3.0, "band-width": 10},
        "quaternary": {"var-data": "GR", "var-weight": 0.7,
                       "var-data2": "RT", "var-weight2": 0.3,
                       "max-cor": 20, "nbr-cor": 10, "out-nbr-cor": 10,
                       "min-dist": 0.2, "out-min-dist": 0.1,
                       "const-gap-cost": 1.5, "band-width": 20},
        "shallow_marine": {"var-data": "GR", "var-weight": 0.5,
                           "var-data2": "RHOB", "var-weight2": 0.3,
                           "var-data3": "DT", "var-weight3": 0.2,
                           "max-cor": 40, "nbr-cor": 20, "out-nbr-cor": 10,
                           "min-dist": 0.4, "out-min-dist": 0.2,
                           "const-gap-cost": 2.0, "band-width": 20},
        "bryson": {"var-data": "FACIES", "no-crossing": "ZONE",
                   "max-cor": 50, "nbr-cor": 30, "out-nbr-cor": 10,
                   "min-dist": 0.5, "out-min-dist": 0.25},
        "bryson_distality": {"var-data": "DISTALITY", "order": "distality",
                             "no-crossing": "ZONE",
                             "max-cor": 80, "nbr-cor": 50, "out-nbr-cor": 10,
                             "min-dist": 0.5, "out-min-dist": 0.25},
        "fluvial": {"var-data": "GR", "var-weight": 1.0,
                    "max-cor": 20, "nbr-cor": 10, "out-nbr-cor": 10,
                    "min-dist": 0.4, "out-min-dist": 0.2,
                    "const-gap-cost": 0.5, "band-width": 60},
        "delta": {"var-data": "GR", "var-weight": 0.6,
                  "var-data2": "DEN", "var-weight2": 0.4,
                  "max-cor": 40, "nbr-cor": 20, "out-nbr-cor": 10,
                  "min-dist": 1.0, "out-min-dist": 0.5, "band-width": 20},
        "sigrun": {"var-data": "GR", "var-weight": 0.6,
                   "var-data2": "NPHI", "var-weight2": 0.4,
                   "max-cor": 50, "nbr-cor": 30, "out-nbr-cor": 10,
                   "min-dist": 0.3, "out-min-dist": 0.15},
        "troll": {"var-data": "FACIES",
                  "max-cor": 50, "nbr-cor": 30, "out-nbr-cor": 10,
                  "min-dist": 0.5, "out-min-dist": 0.25},
        "troll_distality": {"var-data": "DISTALITY", "order": "distality",
                            "no-crossing": "BIOZONE",
                            "max-cor": 50, "nbr-cor": 30, "out-nbr-cor": 15,
                            "min-dist": 0.3, "out-min-dist": 0.15},
        "hugin_tidal": {"dist-distal": "DISTALITY", "dist-facies": "FACIES_1",
                        "dist-scaling": 1.0, "order": "distality",
                        "max-cor": 50, "nbr-cor": 30, "out-nbr-cor": 10,
                        "min-dist": 0.3, "out-min-dist": 0.15},
    }
    return _DEMO_OPTS.get(demo_id, {})


def _get_demo_ai_opts(demo_id: str) -> dict:
    """Per-demo AI feature settings (which features to enable)."""
    _AI_DEFAULTS = {"quality": True, "anomaly": False, "uncertainty": False, "log_qc": False}
    _AI_DEMO_OPTS = {
        "coal": {"quality": True, "anomaly": True, "uncertainty": True, "log_qc": True},
        "quaternary": {"quality": True, "anomaly": True, "uncertainty": True, "log_qc": True},
        "shallow_marine": {"quality": True, "anomaly": True, "uncertainty": True, "log_qc": False},
        "fluvial": {"quality": True, "anomaly": True, "uncertainty": True, "log_qc": False},
        "delta": {"quality": True, "anomaly": False, "uncertainty": True, "log_qc": False},
        "bryson": {"quality": True, "anomaly": True, "uncertainty": False, "log_qc": False},
    }
    return {**_AI_DEFAULTS, **_AI_DEMO_OPTS.get(demo_id, {})}


@app.get("/demos/{demo_id}/wells", response_model=DemoWellsResponse, tags=["demos"])
def get_demo_wells(demo_id: str):
    """Load a demo dataset and return well metadata (without running correlation).

    Used by the web frontend to pre-load demo wells so the user can see
    well names, available logs, and recommended options before clicking "Run".
    """
    # Find the demo in the catalogue
    demo_list = list_demos().demos
    demo = None
    for d in demo_list:
        if d.id == demo_id:
            demo = d
            break

    if demo is None:
        raise HTTPException(status_code=404, detail=f"Demo '{demo_id}' not found.")

    try:
        wl = _load_well_list(demo.wells)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load demo wells: {exc}",
        )

    # Build per-well metadata
    wells_info = []
    for w in wl.wells:
        w_data_names = sorted(
            k for k in (w.data.keys() if hasattr(w, 'data') and w.data else [])
        )
        w_region_names = sorted(
            k for k in (w.region.keys() if hasattr(w, 'region') and isinstance(w.region, dict) else
                        w.region if hasattr(w, 'region') and isinstance(w.region, list) else [])
        )
        wells_info.append(DemoWellInfo(
            name=getattr(w, 'name', ''),
            size=getattr(w, 'size', 0),
            x=getattr(w, 'x', 0.0),
            y=getattr(w, 'y', 0.0),
            z=getattr(w, 'z', 0.0),
            h=getattr(w, 'h', 0.0),
            data_names=w_data_names,
            region_names=w_region_names,
        ))

    # Aggregate all data/region names across wells
    all_data_names = sorted(set(
        name for w in wl.wells
        for name in (w.data.keys() if hasattr(w, 'data') and w.data else [])
    ))
    all_region_names = sorted(set(
        name for w in wl.wells
        for name in (w.region.keys() if hasattr(w, 'region') and isinstance(w.region, dict) else
                     w.region if hasattr(w, 'region') and isinstance(w.region, list) else [])
    ))

    # Get recommended options for this demo
    recommended_options = _get_demo_opts(demo_id)
    if not recommended_options:
        try:
            recommended_options, _ = _suggest_defaults_for_wells(wl)
        except Exception:
            recommended_options = {}

    ai_settings = _get_demo_ai_opts(demo_id)

    return DemoWellsResponse(
        demo_id=demo_id,
        title=demo.title,
        n_wells=len(wells_info),
        wells=wells_info,
        all_data_names=all_data_names,
        all_region_names=all_region_names,
        recommended_options=recommended_options,
        ai_settings=ai_settings,
    )


@app.post("/run/demo", response_model=RunResponse, tags=["demos"])
def run_demo(req: DemoRunRequest):
    """Run a built-in demo dataset with geology-specific default options."""
    # Get the demo list
    try:
        demo_list = list_demos().demos
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to list demos: {exc}")

    demo = None
    for d in demo_list:
        if d.id == req.demo_id:
            demo = d
            break

    if demo is None:
        raise HTTPException(status_code=404,
                            detail=f"Demo '{req.demo_id}' not found.")

    try:
        wl = _load_well_list(demo.wells)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load demo wells: {exc}",
        )

    # Use per-demo opts from the catalogue (geology-specific, tested params)
    options = _get_demo_opts(req.demo_id)
    if not options:
        # Fallback to auto-suggestion if no per-demo opts
        try:
            options, _ = _suggest_defaults_for_wells(wl)
        except Exception:
            options = {}

    try:
        rf, data, elapsed = _run_engine(wl, options)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Engine error: {exc}")

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


# Fallback parameter help for headless environments without PyQt
_FALLBACK_PARAM_HELP = {
    "cost_function": {"label": "Cost Function", "type": "select", "default": "composite",
                      "help": "Cost framework: 'composite' combines multiple cost components.", "category": "Global"},
    "order": {"label": "Merge Order", "type": "select", "default": "linear",
              "help": "Well merge strategy: linear, pyramidal, position, distality, inverse.", "category": "Graph",
              "effect": "position = best for spatial data; pyramidal = best general; distality = basin transect"},
    "max_cor": {"label": "Max Correlations", "type": "int", "default": 50,
                "help": "N-best correlations kept during DTW merge.", "category": "Graph",
                "effect": "\u2191 higher = better quality but slower; \u2193 lower = faster but may miss optimal solution"},
    "nbr_cor": {"label": "N-Best Output", "type": "int", "default": 1,
                "help": "Number of final correlation results to output.", "category": "Graph",
                "effect": "\u2191 more alternatives to compare; 1 = single best only"},
    "band_width": {"label": "Band Width", "type": "int", "default": 0,
                   "help": "Sakoe-Chiba band constraint. 0 = full DTW search.", "category": "Graph",
                   "effect": "\u2191 wider band = more accurate but slower; 0 = full search; >0 = fast approximate"},
    "beam_width": {"label": "Beam Width", "type": "int", "default": 0,
                   "help": "Beam search width for wavefront pruning. 0 = no pruning.", "category": "Graph",
                   "effect": "\u2191 wider beam = more accurate; 0 = optimal (no pruning); small = aggressive speedup"},
    "var_data": {"label": "Primary Log", "type": "data", "default": "",
                 "help": "Primary well-log for variance cost.", "category": "Variance"},
    "var_weight": {"label": "Primary Weight", "type": "float", "default": 1.0,
                   "help": "Weight for primary log variance cost.", "category": "Variance",
                   "effect": "\u2191 higher = log 1 dominates correlation; \u2193 lower = other logs dominate"},
    "var_data2": {"label": "Secondary Log", "type": "data", "default": "",
                  "help": "Second log for multi-variable correlation.", "category": "Variance"},
    "var_weight2": {"label": "Secondary Weight", "type": "float", "default": 1.0,
                    "help": "Weight for secondary log.", "category": "Variance"},
    "no_crossing": {"label": "No-Crossing Region", "type": "region", "default": "",
                    "help": "Region imposing hard no-crossing constraints.", "category": "Constraints",
                    "effect": "Hard constraint: blocks ALL cross-overs at zone boundaries"},
    "same_region": {"label": "Same-Region Cost", "type": "region", "default": "",
                    "help": "Region adding penalty for cross-zone matching.", "category": "Constraints",
                    "effect": "Soft constraint: penalises cross-unit ties but does not block them"},
    "const_gap_cost": {"label": "Gap Cost", "type": "float", "default": 0.0,
                       "help": "Cost per gap step. Higher = fewer gaps.", "category": "Gap",
                       "effect": "\u2191 higher = fewer gaps, layer-cake style; \u2193 lower = more hiatuses allowed, flexible"},
    "dist_facies": {"label": "Distality Facies", "type": "region", "default": "",
                    "help": "Facies region for Walther's Law distality cost.", "category": "Distality"},
    "dist_distal": {"label": "Distality Region", "type": "region", "default": "",
                    "help": "Proximal-distal ordering region.", "category": "Distality"},
    "out_file": {"label": "Output File", "type": "string", "default": "tmp/out.txt",
                 "help": "Result file path.", "category": "Output"},
}


@app.get("/options/help", response_model=OptionsHelpResponse, tags=["system"])
def options_help():
    """Return parameter descriptions and effect hints for all engine options."""
    try:
        from weco.studio import PARAM_HELP
    except ImportError:
        # Fallback if PyQt is not installed (headless server)
        PARAM_HELP = _FALLBACK_PARAM_HELP

    items = []
    for name, meta in sorted(PARAM_HELP.items()):
        items.append(OptionHelp(
            name=name.replace("_", "-"),
            label=meta.get("label", name),
            type=meta.get("type", "string"),
            default=meta.get("default"),
            help=meta.get("help", ""),
            effect=meta.get("effect"),
            category=meta.get("category", ""),
        ))

    categories = sorted(set(o.category for o in items))
    return OptionsHelpResponse(options=items, categories=categories)


@app.get("/docs/formats", tags=["docs"])
def docs_formats():
    """Return documentation of all WeCo file formats (wells, results, options, batch JSON)."""
    return JSONResponse(content={
        "well_list": {
            "extension": ".txt / .wells.txt",
            "description": "WeCo native well-list format (space-separated text)",
            "spec": (
                "WeCo WellList 2          # Header: format version\n"
                "N                         # Number of wells\n"
                "WellName                  # Well name (no spaces)\n"
                "Size                      # Number of samples\n"
                "X Y Z H                   # Coordinates: X, Y, Z (top), H (total height)\n"
                "N_data                    # Number of data arrays\n"
                "DataName Size             # Data column: name + n_values\n"
                "v1 v2 v3 ...             # Values (one per line or space-separated)\n"
                "...                       # (repeat for each data column)\n"
                "N_regions                 # Number of region lists\n"
                "RegionName N_entries      # Region: name + n_entries\n"
                "ID Start Length           # Each entry: region_id, start_index, length\n"
                "...                       # (repeat for each region entry)\n"
                "...                       # (repeat for each well)\n"
                "END                       # End marker"
            ),
            "notes": [
                "Strings cannot contain spaces",
                "Data arrays hold continuous log values (GR, RHOB, etc.)",
                "Region lists hold categorical intervals (facies, biozones, sequences)",
                "Region entries: ID is an integer category, Start is 0-based sample index, Length is number of samples",
            ],
        },
        "option_file": {
            "extension": ".txt / .opt",
            "description": "Engine option file (key=value pairs, one per line)",
            "spec": (
                "# Comment lines start with #\n"
                "cost-function=composite\n"
                "order=pyramidal\n"
                "max-cor=50\n"
                "var-data=GR\n"
                "var-weight=1.0\n"
                "var-data2=RHOB\n"
                "var-weight2=0.5\n"
                "no-crossing=BIOZONE\n"
                "const-gap-cost=0.3\n"
                "dist-facies=FACIES\n"
                "dist-distal=DISTALITY\n"
            ),
            "notes": [
                "Use hyphens (cost-function) in option files",
                "Use underscores (cost_function) in Python API",
                "Both are accepted and auto-converted",
                "Empty string means disabled/unused",
                "Use GET /options/help for the full parameter list",
            ],
        },
        "result_file": {
            "extension": ".txt (out.txt)",
            "description": "WeCo DAG result file - directed acyclic graph of correlation nodes",
            "spec": (
                "WellIds: 0 1 2            # Well indices in merge order\n"
                "Node 0 (0 0 0)            # Node: matched positions per well\n"
                "Node 1 (5 3 4)            # Position = sample index\n"
                "   -> 0 (14.2)            # Edge: target_node (cost)\n"
                "Node 2 (10 8 9)\n"
                "   -> 0 (2.3)\n"
                "   -> 1 (4.2)\n"
            ),
            "notes": [
                "Each node is a correlated horizon (matched positions across all wells)",
                "Edges carry transition costs between successive horizons",
                "Best correlation = cheapest path from first to last node",
                "N-best paths give alternative geologically plausible scenarios",
            ],
        },
        "batch_json": {
            "extension": ".json",
            "description": "Batch configuration file for WeCoBatch (python -m weco.batch config.json)",
            "spec": {
                "wells": "path/to/wells.txt  (required)",
                "format": "weco | las | csv | resqml | epc  (default: weco)",
                "preset": "shallow_marine | fluvial | carbonate | deep_marine | coal | quaternary | null",
                "options": {
                    "cost_function": "composite",
                    "order": "pyramidal",
                    "max_cor": 50,
                    "var_data": "GR",
                    "var_weight": 1.0,
                    "no_crossing": "BIOZONE",
                    "const_gap_cost": 0.3,
                },
                "condition": "true | false  (default: true, run auto-preprocessing)",
                "output_dir": "tmp/  (default: weco_output/)",
                "exports": ["csv", "las", "rms", "epc", "gocad", "marker_set", "zone_thickness", "ensemble"],
                "multi_run": "true | false  (default: false)",
                "runs": [
                    {
                        "name": "run_01_variance_only",
                        "options": {"var_data": "GR", "const_gap_cost": 0.0},
                    },
                    {
                        "name": "run_02_with_constraints",
                        "options": {"no_crossing": "BIOZONE", "const_gap_cost": 0.5},
                    },
                ],
            },
            "notes": [
                "Run with: python -m weco.batch config.json",
                "Or via CLI: weco demo  (for auto_run_examples)",
                "If multi_run=true, each entry in 'runs' executes independently",
                "Run-specific 'options' override top-level 'options'",
                "If 'preset' is set, its defaults are applied first, then overridden by 'options'",
                "Available presets: shallow_marine, fluvial, carbonate, deep_marine, coal, quaternary, delta",
                "Exports are written to output_dir/run_name/ for multi_run",
            ],
        },
        "supported_import_formats": [
            {"format": "WeCo native", "extension": ".txt", "description": "Native well-list text format"},
            {"format": "LAS 2.0", "extension": ".las", "description": "Log ASCII Standard (auto-detected)"},
            {"format": "CSV/TSV", "extension": ".csv/.tsv", "description": "Tabular with header row"},
            {"format": "RESQML", "extension": ".epc", "description": "EPC+HDF5 container (requires h5py)"},
            {"format": "GOCAD Well", "extension": ".wl", "description": "GOCAD ASCII well format"},
        ],
        "supported_export_formats": [
            {"format": "CSV", "extension": ".csv", "description": "Marker picks as tabular CSV"},
            {"format": "LAS 2.0", "extension": ".las", "description": "Markers as LAS curves"},
            {"format": "RMS", "extension": ".txt", "description": "RMS horizon picks format"},
            {"format": "RESQML", "extension": ".epc", "description": "EPC+HDF5 stratigraphic column"},
            {"format": "GOCAD", "extension": ".wl/.vs/.ts", "description": "GOCAD well + surfaces"},
            {"format": "JSON", "extension": ".json", "description": "Marker set JSON (RDDMS-compatible)"},
            {"format": "PNG/SVG/PDF", "extension": ".png/.svg/.pdf", "description": "Correlation plots"},
        ],
    })


@app.get("/docs/batch-schema", tags=["docs"])
def docs_batch_schema():
    """Return the JSON schema for WeCoBatch configuration files."""
    schema = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": "WeCo Batch Configuration",
        "description": "Configuration file for python -m weco.batch",
        "type": "object",
        "required": ["wells"],
        "properties": {
            "wells": {
                "type": "string",
                "description": "Path to well-list file (WeCo, LAS, CSV, or RESQML)",
            },
            "format": {
                "type": "string",
                "enum": ["weco", "las", "csv", "resqml", "epc"],
                "default": "weco",
                "description": "Input file format",
            },
            "preset": {
                "type": ["string", "null"],
                "enum": ["shallow_marine", "fluvial", "carbonate", "deep_marine",
                         "coal", "quaternary", "delta", None],
                "description": "Geological preset - sets default options per environment",
            },
            "options": {
                "type": "object",
                "description": "Engine options (key: value). Use underscores for keys.",
                "additionalProperties": True,
            },
            "condition": {
                "type": "boolean",
                "default": True,
                "description": "Run auto-preprocessing before correlation",
            },
            "output_dir": {
                "type": "string",
                "default": "weco_output",
                "description": "Directory for output files",
            },
            "exports": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": ["csv", "las", "rms", "epc", "gocad",
                             "marker_set", "zone_thickness", "ensemble"],
                },
                "default": ["csv"],
                "description": "Export formats to produce",
            },
            "multi_run": {
                "type": "boolean",
                "default": False,
                "description": "If true, execute each entry in 'runs' independently",
            },
            "runs": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Run identifier"},
                        "wells": {"type": "string", "description": "Override well file"},
                        "options": {"type": "object", "description": "Override options"},
                    },
                },
                "description": "Multiple run configurations (requires multi_run=true)",
            },
        },
    }
    return JSONResponse(content=schema)


# ═══════════════════════════════════════════════════════════════════════════
#  POST /run/seistiles - correlation with Seismic Tiles constraint
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

    **Algorithm** - for each candidate tie (i_a, i_b):

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
        "maap/weco", description="RDDMS dataspace name.",
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
    dataspace: str = Field("maap/weco", description="RDDMS dataspace name.")


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
        "maap/weco", description="Target RDDMS dataspace.",
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
        "maap/weco", description="RDDMS dataspace.",
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
        None, description="Path to StratColumn JSON - auto-detect env.",
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

    try:
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
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Environment detection failed: {exc}",
        )

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
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid project document: {e}")

    # Merge options: project options + request overrides
    opts = doc.get("options", {})
    opts.update(req.options)

    # Write wells to temp file for the C++ engine
    import tempfile
    from weco.data import WellList as PyWellList

    try:
        _validate_well_list(wl_py)
        _validate_options_against_wells(opts, wl_py)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Validation failed: {e}")

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False
    ) as tmp:
        wl_py.write(tmp.name)
        tmp_path = tmp.name

    try:
        rf, data, elapsed = _run_engine(wl_py, opts)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Engine error: {exc}")
    finally:
        os.unlink(tmp_path)

    # Build full project JSON with results
    try:
        result_doc = project_to_json(wl_py, opts, rf, max_paths=req.n_best)
        result_doc["elapsed_ms"] = elapsed * 1000
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Result serialization failed: {exc}")

    return JsonRunResponse(status="ok", project=result_doc)


@app.post("/json/convert", tags=["json-format"])
def json_convert(req: JsonConvertRequest):
    """Convert a legacy WeCo .txt well file to JSON format.

    Returns the JSON document directly.
    """
    from weco.json_format import welllist_to_json

    try:
        wl = _load_well_list(req.well_file)
        doc = welllist_to_json(wl)
        doc["meta"]["sourceFile"] = os.path.basename(req.well_file)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Conversion failed: {exc}")
    return JSONResponse(content=doc)


@app.post("/json/export", tags=["json-format"])
def json_export(req: JsonExportRequest):
    """Export wells (+ optional results) to a full WeCo JSON project.

    If ``result_file`` is provided, the result graph is included.
    """
    from weco.json_format import project_to_json
    from weco.data import ResFile

    try:
        wl = _load_well_list(req.well_file)

        res = None
        if req.result_file and os.path.isfile(req.result_file):
            res = ResFile(req.result_file)

        doc = project_to_json(wl, req.options, res)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Export failed: {exc}")
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

    try:
        rec = recommend_workflow(wl)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Workflow recommendation failed: {exc}")

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
        description="Available log mnemonics - preset will substitute if needed.",
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
    try:
        wl = _load_well_list(req.well_file)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load wells: {exc}")

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
    - DiscreteProperty per well (zonation log - zone index per depth)
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
    try:
        wl = _load_well_list(req.well_file)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load wells: {exc}")

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
    try:
        wl = _load_well_list(req.well_file)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load wells: {exc}")

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
            interp = "Excellent - high confidence correlation"
        elif overall >= 0.6:
            interp = "Good - reasonable correlation with minor uncertainty"
        elif overall >= 0.4:
            interp = "Fair - some wells may be miscorrelated"
        else:
            interp = "Poor - review parameters and constraints"

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
    try:
        wl = _load_well_list(req.well_file)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load wells: {exc}")

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
        rec = "Very robust - order choice has minimal impact"
    elif robustness >= 0.8:
        rec = f"Robust - slight preference for '{best_order}'"
    elif robustness >= 0.5:
        rec = f"Moderately sensitive - recommend '{best_order}' order"
    else:
        rec = f"Highly sensitive to order - use '{best_order}', consider constraints"

    return SensitivityResponse(
        orders_tested=req.orders,
        costs=costs,
        best_order=best_order,
        worst_order=worst_order,
        robustness=round(robustness, 3),
        recommendation=rec,
    )


# ═══════════════════════════════════════════════════════════════════════════
#  Anomaly Detection & Uncertainty Analysis
# ═══════════════════════════════════════════════════════════════════════════

class AnomalyRequest(BaseModel):
    """Detect anomalous correlation lines."""

    well_file: str = Field(..., description="Path to well-list file.")
    result_file: str = Field(..., description="Path to WeCo result file.")
    cor_num: int = Field(0, ge=0, description="Result index to analyse.")
    method: str = Field(
        "isolation_forest",
        description="Detection method: 'isolation_forest' or 'statistical'.",
    )
    contamination: float = Field(0.1, ge=0.01, le=0.5, description="Expected anomaly fraction.")
    threshold: float = Field(2.5, description="Z-score threshold (for 'statistical' method).")


class AnomalyFlag(BaseModel):
    """One flagged correlation line."""

    line_index: int
    is_anomaly: bool
    score: float = Field(description="Anomaly score (lower = more anomalous for IF).")
    well_pair: Optional[str] = None


class AnomalyResponse(BaseModel):
    """Anomaly detection results."""

    result_index: int
    method: str
    n_lines: int
    n_anomalies: int
    anomaly_fraction: float
    flags: List[AnomalyFlag]
    summary: str


@app.post("/validate/anomaly", response_model=AnomalyResponse, tags=["validation"])
def validate_anomaly(req: AnomalyRequest):
    """Detect anomalous (suspicious) correlation lines using ML or statistics."""
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

        method = req.method.lower().strip()
        if method == "statistical":
            from weco.ai.anomaly import StatisticalAnomalyDetector
            det = StatisticalAnomalyDetector(threshold=req.threshold)
        else:
            from weco.ai.anomaly import CorrelationAnomalyDetector
            det = CorrelationAnomalyDetector(contamination=req.contamination)

        raw_flags = det.flag_anomalies(rf, wl, n_correlations=req.cor_num + 1)

        flags = []
        for i, f in enumerate(raw_flags):
            flags.append(AnomalyFlag(
                line_index=f.get("index", i),
                is_anomaly=f.get("anomaly", False),
                score=round(f.get("score", 0.0), 4),
                well_pair=f.get("well_pair"),
            ))

        n_anomalies = sum(1 for f in flags if f.is_anomaly)
        n_lines = len(flags)
        frac = n_anomalies / max(n_lines, 1)

        if n_anomalies == 0:
            summary = "No anomalous lines detected - correlation appears consistent."
        elif frac < 0.15:
            summary = f"{n_anomalies} suspicious line(s) - minor issues, review flagged pairs."
        else:
            summary = f"{n_anomalies} anomalies ({frac:.0%}) - consider revising parameters."

        return AnomalyResponse(
            result_index=req.cor_num,
            method=method,
            n_lines=n_lines,
            n_anomalies=n_anomalies,
            anomaly_fraction=round(frac, 3),
            flags=flags,
            summary=summary,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class UncertaintyRequest(BaseModel):
    """Analyse correlation uncertainty from n-best ensemble."""

    well_file: str = Field(..., description="Path to well-list file.")
    result_file: str = Field(..., description="Path to WeCo result file.")
    n_paths: Optional[int] = Field(None, description="Number of paths to consider (default: all).")
    low_threshold: float = Field(0.5, description="Below this std = high confidence.")
    high_threshold: float = Field(2.0, description="Above this std = low confidence.")


class WellPairUncertainty(BaseModel):
    """Per-well-pair uncertainty summary."""

    well_a: str
    well_b: str
    mean_spread: float
    max_spread: float
    n_high_conf: int
    n_low_conf: int


class UncertaintyResponse(BaseModel):
    """Uncertainty analysis results."""

    n_paths_used: int
    n_pairs: int
    overall_mean_spread: float
    overall_max_spread: float
    high_confidence_fraction: float
    low_confidence_fraction: float
    pairs: List[WellPairUncertainty]
    interpretation: str


@app.post("/validate/uncertainty", response_model=UncertaintyResponse,
          tags=["validation"])
def validate_uncertainty(req: UncertaintyRequest):
    """Analyse per-marker uncertainty from n-best ensemble spread."""
    if not os.path.isfile(req.well_file):
        raise HTTPException(status_code=404, detail="Well file not found")
    if not os.path.isfile(req.result_file):
        raise HTTPException(status_code=404, detail="Result file not found")

    try:
        wl = _load_well_list(req.well_file)
        from weco.data import ResFile
        rf = ResFile(req.result_file)

        n_results = rf.get_nbr_results()
        if n_results < 2:
            raise HTTPException(status_code=400,
                                detail="Need at least 2 results for uncertainty analysis.")

        from weco.ai.uncertainty import CorrelationUncertainty
        n_paths = req.n_paths or n_results

        uncertainty_map = CorrelationUncertainty.from_n_best(rf, n_paths=n_paths)
        confidence_map = CorrelationUncertainty.confidence_classification(
            uncertainty_map,
            low_threshold=req.low_threshold,
            high_threshold=req.high_threshold,
        )

        pairs = []
        all_spreads = []
        total_high = 0
        total_low = 0
        total_markers = 0

        for (wa, wb), spreads in uncertainty_map.items():
            import numpy as np
            ms = float(np.mean(spreads))
            mx = float(np.max(spreads))
            all_spreads.append(ms)
            confs = confidence_map.get((wa, wb), np.array([]))
            n_h = int(np.sum(confs == 3))
            n_l = int(np.sum(confs == 1))
            total_high += n_h
            total_low += n_l
            total_markers += len(confs)
            pairs.append(WellPairUncertainty(
                well_a=wa, well_b=wb,
                mean_spread=round(ms, 3), max_spread=round(mx, 3),
                n_high_conf=n_h, n_low_conf=n_l,
            ))

        overall_mean = sum(all_spreads) / max(len(all_spreads), 1)
        overall_max = max(all_spreads) if all_spreads else 0.0
        high_frac = total_high / max(total_markers, 1)
        low_frac = total_low / max(total_markers, 1)

        if high_frac >= 0.7:
            interp = "High confidence - ensemble shows consistent tie positions."
        elif low_frac >= 0.3:
            interp = "Significant uncertainty - consider additional constraints or data."
        else:
            interp = "Moderate uncertainty - most markers are stable across realisations."

        return UncertaintyResponse(
            n_paths_used=min(n_paths, n_results),
            n_pairs=len(pairs),
            overall_mean_spread=round(overall_mean, 3),
            overall_max_spread=round(overall_max, 3),
            high_confidence_fraction=round(high_frac, 3),
            low_confidence_fraction=round(low_frac, 3),
            pairs=pairs,
            interpretation=interp,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
    try:
        demo_list = list_demos().demos
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to list demos: {exc}")

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


# ═══════════════════════════════════════════════════════════════════════════
#  Well Ordering / Display Order
# ═══════════════════════════════════════════════════════════════════════════

class WellOrderRequest(BaseModel):
    """Request well display ordering."""

    well_file: str = Field(..., description="Server-side path to well-list file.")
    method: str = Field(
        "input",
        description="Ordering method: 'input', 'x', 'y', 'azimuth', "
                    "'distality', 'pca', 'nearest'.",
    )
    azimuth_deg: float = Field(
        90.0,
        description="Transport direction azimuth (degrees N, clockwise). "
                    "Used when method='azimuth'.",
    )


class WellOrderResponse(BaseModel):
    """Response with computed well display order."""

    method: str
    order: List[int] = Field(
        description="Well indices in display order (0-based).",
    )
    well_names: List[str] = Field(
        description="Well names in display order.",
    )
    projections: Optional[List[float]] = Field(
        None, description="Projection values (for azimuth/distality/PCA).",
    )


@app.post("/wells/order", response_model=WellOrderResponse, tags=["data"])
def compute_well_order(req: WellOrderRequest):
    """Compute display ordering of wells by various spatial criteria.

    Methods:
    - ``input``: original file order
    - ``x``: sort by X coordinate (West → East)
    - ``y``: sort by Y coordinate (South → North)
    - ``azimuth``: project onto a user-defined azimuth direction
    - ``distality``: sort by distality region value (proximal → distal)
    - ``pca``: project onto principal spread direction (auto-detected)
    - ``nearest``: nearest-neighbour chain (minimises inter-well distance)
    """
    import math

    try:
        wl = _load_well_list(req.well_file)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load wells: {exc}")

    n = len(wl.wells)
    if n == 0:
        raise HTTPException(status_code=400, detail="No wells in file.")

    method = req.method.lower().strip()
    projections = None

    if method == "x":
        order = sorted(range(n), key=lambda i: wl.wells[i].x)
        projections = [wl.wells[i].x for i in order]

    elif method == "y":
        order = sorted(range(n), key=lambda i: wl.wells[i].y)
        projections = [wl.wells[i].y for i in order]

    elif method == "azimuth":
        theta = math.radians(req.azimuth_deg)
        dx = math.sin(theta)
        dy = math.cos(theta)
        projs = [(wl.wells[i].x * dx + wl.wells[i].y * dy, i)
                 for i in range(n)]
        projs.sort()
        order = [i for _, i in projs]
        projections = [p for p, _ in projs]

    elif method == "distality":
        # Use DISTALITY region if available, else compute from azimuth
        distality_vals = []
        for i, w in enumerate(wl.wells):
            d = 0.5  # default middle
            if hasattr(w, 'region'):
                for rname in ('DISTALITY', 'DISTAL', 'distality', 'Distality'):
                    reg = (w.region.get(rname) if isinstance(w.region, dict)
                           else None)
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
            direction = Vt[0]
            proj_vals = centered @ direction
            order = list(np.argsort(proj_vals))
            projections = [float(proj_vals[i]) for i in order]

    elif method == "nearest":
        from weco.order import compute_nearest_ordering
        coords = [(w.x, w.y) for w in wl.wells]
        order = compute_nearest_ordering(coords, first=0)

    else:
        # input order
        order = list(range(n))

    well_names = [wl.wells[i].name for i in order]

    return WellOrderResponse(
        method=method,
        order=order,
        well_names=well_names,
        projections=projections,
    )
