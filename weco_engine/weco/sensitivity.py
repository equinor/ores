"""
WeCo Well Order Sensitivity Analysis
=====================================

The PhD thesis (Baville 2022, §3.4.1, §4.5.3) demonstrates that the
order in which wells are merged has a **strong impact** on correlation
outcomes because "only a limited set of scenarios can be propagated
through the multi-well correlation process".

This module provides tools to:
- Run correlation with multiple well orders and aggregate results
- Identify which correlation lines are order-sensitive vs robust
- Quantify the variability introduced by order choice
- Configure well ordering via the ``well_order`` option (§13.3.1)

Built-in engine order keys (C++ TaskOrderFactory):
  ``pyramidal``, ``linear``, ``position``, ``distality``, ``inverse``

Python-side additional strategies:
  ``proximal_first``, ``distal_first``, ``random``

Reference: Baville (2022) §3.4.1 "Order of wells and correlation path"
"""

from __future__ import annotations

import random
from typing import Optional, Union

import numpy as np

from .data import ResFile, WellList, ResAndWL
from .ext import ProjectExt

# Engine-native order keys (read-only)
BUILTIN_ORDER_KEYS = ["pyramidal", "linear", "position", "distality", "inverse"]

# Python-side extended order keys
EXTENDED_ORDER_KEYS = ["proximal_first", "distal_first", "random", "auto"]

# All supported order keys
ALL_ORDER_KEYS = BUILTIN_ORDER_KEYS + EXTENDED_ORDER_KEYS


# ---------------------------------------------------------------------------
# Well order strategies
# ---------------------------------------------------------------------------

def _reverse_wells(wells: list, create_task) -> None:
    """Correlate wells in reverse order (linear)."""
    task = create_task(wells[-1], wells[-2])
    for i in range(len(wells) - 3, -1, -1):
        task = create_task(task, wells[i])


def _random_linear(wells: list, create_task) -> None:
    """Correlate wells in a random linear order."""
    indices = list(range(len(wells)))
    random.shuffle(indices)
    task = create_task(wells[indices[0]], wells[indices[1]])
    for i in range(2, len(wells)):
        task = create_task(task, wells[indices[i]])


def _proximal_first(wells: list, create_task) -> None:
    """Order wells from most proximal (highest distality ID) to most distal.

    This aligns the merge tree so the most proximal (land-ward) wells
    are correlated first, adding progressively more distal wells.
    Requires a ``DISTAL`` or ``DISTALITY`` region on each well.
    Falls back to position order (west→east) if no distality region.
    """
    def _dist_value(w):
        for rname in ("DISTAL", "DISTALITY", "distal", "distality"):
            if w.region_list_exists(rname):
                rl = w.get_region_list(rname)
                if rl.nbr_regions() > 0:
                    return rl.get_region(0)  # first region ID
        return w.x  # fallback to x-coordinate

    indexed = [(i, _dist_value(wells[i])) for i in range(len(wells))]
    indexed.sort(key=lambda t: -t[1])  # highest distality first (proximal)
    task = create_task(wells[indexed[0][0]], wells[indexed[1][0]])
    for k in range(2, len(indexed)):
        task = create_task(task, wells[indexed[k][0]])


def _distal_first(wells: list, create_task) -> None:
    """Order wells from most distal (lowest distality ID) to most proximal.

    Reverse of ``proximal_first``.
    """
    def _dist_value(w):
        for rname in ("DISTAL", "DISTALITY", "distal", "distality"):
            if w.region_list_exists(rname):
                rl = w.get_region_list(rname)
                if rl.nbr_regions() > 0:
                    return rl.get_region(0)
        return w.x

    indexed = [(i, _dist_value(wells[i])) for i in range(len(wells))]
    indexed.sort(key=lambda t: t[1])  # lowest distality first (distal)
    task = create_task(wells[indexed[0][0]], wells[indexed[1][0]])
    for k in range(2, len(indexed)):
        task = create_task(task, wells[indexed[k][0]])


def configure_well_order(proj: ProjectExt, order: str, seed: int = 42) -> None:
    """Configure well ordering on a ProjectExt instance.

    Supports both engine-native and Python-side order strategies.

    Parameters
    ----------
    proj : ProjectExt
        The project to configure.
    order : str
        One of: ``"auto"`` (pyramidal), ``"pyramidal"``, ``"linear"``,
        ``"position"``, ``"distality"``, ``"inverse"``,
        ``"proximal_first"``, ``"distal_first"``, ``"random"``.
    seed : int
        Random seed (used only for ``"random"``).

    Reference
    ---------
    Baville (2022) §3.4.1 — well order sensitivity.
    """
    order = order.lower().strip()

    if order == "auto":
        order = "pyramidal"

    if order in BUILTIN_ORDER_KEYS:
        proj.clear_order_func()
        proj.set_option_ext("order", order)
        return

    if order == "proximal_first":
        proj.set_order_func(_proximal_first)
    elif order == "distal_first":
        proj.set_order_func(_distal_first)
    elif order == "random":
        random.seed(seed)
        proj.set_order_func(_random_linear)
    else:
        raise ValueError(
            f"Unknown well order '{order}'.  "
            f"Available: {ALL_ORDER_KEYS}"
        )


# ---------------------------------------------------------------------------
# Multi-order runner
# ---------------------------------------------------------------------------

def run_order_sensitivity(
    well_list: Union[str, WellList],
    options: Optional[dict] = None,
    options_file: Optional[str] = None,
    n_random: int = 5,
    strategies: Optional[list[str]] = None,
    seed: int = 42,
) -> dict:
    """Run correlation with multiple well orders and compare results.

    Parameters
    ----------
    well_list : str or WellList
        Well data.
    options : dict, optional
        Engine options as key-value pairs.
    options_file : str, optional
        Path to options file.
    n_random : int
        Number of random linear orderings to try.
    strategies : list[str], optional
        Built-in strategies to test.  Default: ["pyramidal", "linear"].
    seed : int
        Random seed for reproducibility.

    Returns
    -------
    dict
        ``{"runs": [{"strategy": str, "cost": float, "n_results": int,
        "path": list, ...}, ...],
        "robustness": dict, "summary": dict}``
    """
    if isinstance(well_list, str):
        well_list = WellList(well_list)

    if strategies is None:
        strategies = ["pyramidal", "linear"]

    random.seed(seed)
    runs = []

    # 1. Built-in strategies
    for strat in strategies:
        proj = _make_project(options, options_file)
        proj.set_option_ext("order", strat)
        proj.run(well_list)
        rf = proj.get_res_file()
        runs.append(_extract_run_info(rf, well_list, f"builtin:{strat}"))

    # 2. Reverse order (linear)
    proj = _make_project(options, options_file)
    proj.set_order_func(_reverse_wells)
    proj.run(well_list)
    rf = proj.get_res_file()
    runs.append(_extract_run_info(rf, well_list, "reverse"))
    proj.clear_order_func()

    # 3. Random orderings
    for i in range(n_random):
        random.seed(seed + i + 100)
        proj = _make_project(options, options_file)
        proj.set_order_func(_random_linear)
        proj.run(well_list)
        rf = proj.get_res_file()
        runs.append(_extract_run_info(rf, well_list, f"random:{i+1}"))
        proj.clear_order_func()

    # Robustness analysis: for each correlation line, how many runs agree?
    robustness = _compute_robustness(runs)

    # Summary
    costs = [r["cost"] for r in runs]
    summary = {
        "n_runs": len(runs),
        "cost_mean": float(np.mean(costs)),
        "cost_std": float(np.std(costs)),
        "cost_min": float(np.min(costs)),
        "cost_max": float(np.max(costs)),
        "cost_range": float(np.max(costs) - np.min(costs)),
        "strategies": [r["strategy"] for r in runs],
    }

    return {
        "runs": runs,
        "robustness": robustness,
        "summary": summary,
    }


def _make_project(
    options: Optional[dict],
    options_file: Optional[str],
) -> ProjectExt:
    """Create and configure a ProjectExt."""
    proj = ProjectExt()
    if options_file:
        proj.set_option_ext("read-options", options_file)
    if options:
        proj.set_options_ext(options)
    return proj


def _extract_run_info(
    rf: ResFile,
    wl: WellList,
    strategy: str,
) -> dict:
    """Extract summary info from a run."""
    data = ResAndWL(rf, wl)
    n_wells = rf.nbr_well()
    well_names = data.well_names()

    path = rf.get_result_full_path(0)
    cost = rf.get_result_cost(0)

    # Deduplicated ties
    ties = []
    prev = None
    for step in path:
        if step != prev:
            tie = tuple(step[wi] for wi in range(n_wells))
            ties.append(tie)
            prev = step

    # Count gaps
    n_gaps = 0
    prev = path[0]
    for step in path[1:]:
        if step != prev:
            advancing = sum(1 for w in range(n_wells) if step[w] != prev[w])
            if advancing < n_wells:
                n_gaps += 1
        prev = step

    return {
        "strategy": strategy,
        "cost": float(cost),
        "n_results": rf.get_nbr_results(),
        "n_ties": len(ties),
        "n_gaps": n_gaps,
        "ties": ties,
        "well_names": well_names,
    }


def _compute_robustness(runs: list[dict]) -> dict:
    """Compute per-tie robustness (fraction of runs that include each tie).

    Returns
    -------
    dict
        ``{"robust_ties": list, "sensitive_ties": list,
        "robustness_score": float}``

    A tie is robust if it appears in > 50% of runs.
    """
    if not runs:
        return {"robust_ties": [], "sensitive_ties": [],
                "robustness_score": 0.0}

    # Collect all unique ties across all runs
    all_ties = set()
    for run in runs:
        all_ties.update(set(run["ties"]))

    n_runs = len(runs)
    tie_counts = {}
    for tie in all_ties:
        count = sum(1 for run in runs if tie in set(run["ties"]))
        tie_counts[tie] = count

    robust = [t for t, c in tie_counts.items() if c > n_runs * 0.5]
    sensitive = [t for t, c in tie_counts.items() if c <= n_runs * 0.5]

    # Robustness score: fraction of ties that are robust
    total = len(all_ties) if all_ties else 1
    score = len(robust) / total

    return {
        "robust_ties": robust,
        "sensitive_ties": sensitive,
        "n_robust": len(robust),
        "n_sensitive": len(sensitive),
        "robustness_score": float(score),
    }


# ---------------------------------------------------------------------------
# Convenience function for quick check
# ---------------------------------------------------------------------------

def quick_order_check(
    well_list: Union[str, WellList],
    options_file: Optional[str] = None,
) -> dict:
    """Run a quick forward-vs-reverse order check (fastest sensitivity test).

    Reference: Baville (2022) Figures 3.6-3.8 — forward vs reverse
    well ordering comparison.

    Parameters
    ----------
    well_list : str or WellList
        Well data.
    options_file : str, optional
        Options file path.

    Returns
    -------
    dict
        ``{"forward_cost": float, "reverse_cost": float,
        "cost_difference": float, "n_ties_different": int,
        "sensitivity": str}``

        sensitivity: "low" if < 5% ties differ,
        "medium" if 5-20%, "high" if > 20%
    """
    if isinstance(well_list, str):
        well_list = WellList(well_list)

    # Forward (default pyramidal)
    proj_fwd = ProjectExt()
    if options_file:
        proj_fwd.set_option_ext("read-options", options_file)
    proj_fwd.run(well_list)
    rf_fwd = proj_fwd.get_res_file()

    # Reverse
    proj_rev = ProjectExt()
    if options_file:
        proj_rev.set_option_ext("read-options", options_file)
    proj_rev.set_order_func(_reverse_wells)
    proj_rev.run(well_list)
    rf_rev = proj_rev.get_res_file()
    proj_rev.clear_order_func()

    # Compare
    n_wells = rf_fwd.nbr_well()
    path_fwd = rf_fwd.get_result_full_path(0)
    path_rev = rf_rev.get_result_full_path(0)

    # Deduplicate
    def _dedup(path):
        ties = set()
        prev = None
        for step in path:
            if step != prev:
                ties.add(tuple(step[wi] for wi in range(n_wells)))
                prev = step
        return ties

    ties_fwd = _dedup(path_fwd)
    ties_rev = _dedup(path_rev)

    common = ties_fwd & ties_rev
    all_unique = ties_fwd | ties_rev
    n_diff = len(all_unique) - len(common)

    pct = n_diff / max(len(all_unique), 1)
    if pct < 0.05:
        sensitivity = "low"
    elif pct < 0.20:
        sensitivity = "medium"
    else:
        sensitivity = "high"

    return {
        "forward_cost": float(rf_fwd.get_result_cost(0)),
        "reverse_cost": float(rf_rev.get_result_cost(0)),
        "cost_difference": abs(
            rf_fwd.get_result_cost(0) - rf_rev.get_result_cost(0)
        ),
        "n_ties_forward": len(ties_fwd),
        "n_ties_reverse": len(ties_rev),
        "n_ties_common": len(common),
        "n_ties_different": n_diff,
        "sensitivity": sensitivity,
    }
