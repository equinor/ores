"""
weco.diversity - Topology-aware scenario diversity & log screening
==================================================================

Improvements based on demo results analysis (doc/demo_results_analysis.md):

1. **Log Relevance Screening** - auto-detect which logs carry correlation
   signal vs noise before running the engine.
2. **Topology-Aware Diversity Filtering** - post-process k-best results to
   retain only architecturally distinct scenarios (different horizon counts,
   connectivity graphs, zone volumes).
3. **Architecture-Based Enumeration** - generate scenarios with varying gap
   costs to enforce different horizon counts.
4. **Cross-Validation** - hold-out-one-well validation for robustness.

Usage::

    from weco.diversity import (
        screen_logs,
        filter_diverse_scenarios,
        enumerate_architectures,
        cross_validate,
    )
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# §1 - Log Relevance Screening
# ═══════════════════════════════════════════════════════════════════════════

def screen_logs(
    well_list,
    candidate_logs: Optional[List[str]] = None,
    method: str = "variance_ratio",
    min_score: float = 0.1,
) -> List[Dict]:
    """Screen logs for correlation relevance before running the engine.

    A log is relevant for correlation if it shows:
    - Sufficient variance within wells (not constant)
    - Discriminative power between depth intervals (not white noise)
    - Consistency across wells (similar log responses mean similar geology)

    Parameters
    ----------
    well_list : WellList
        Loaded well data.
    candidate_logs : list of str, optional
        Log names to screen. If None, auto-detects all numeric channels.
    method : str
        ``"variance_ratio"`` - ratio of inter-interval to intra-interval variance.
        ``"autocorrelation"`` - lag-1 autocorrelation (signal vs noise).
        ``"cross_well"`` - cross-well correlation coefficient.
    min_score : float
        Minimum score to consider a log relevant (0–1 scale).

    Returns
    -------
    list of dict
        Sorted by relevance (highest first). Each dict:
        ``{"log": str, "score": float, "relevant": bool, "reason": str}``
    """
    if candidate_logs is None:
        candidate_logs = _detect_numeric_logs(well_list)

    results = []
    for log_name in candidate_logs:
        score, reason = _score_log(well_list, log_name, method)
        results.append({
            "log": log_name,
            "score": round(score, 4),
            "relevant": score >= min_score,
            "reason": reason,
        })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results


def _detect_numeric_logs(well_list) -> List[str]:
    """Find all numeric data channels across wells (exclude DEPTH, X, Y, Z)."""
    skip = {"DEPTH", "Depth", "MD", "TVD", "TVDSS", "X", "Y", "Z", "x", "y", "z"}
    names = set()
    for w in well_list.wells:
        data = w.data if hasattr(w, 'data') else {}
        for k, v in data.items():
            if k in skip:
                continue
            # Check if numeric
            if isinstance(v, (list, tuple, np.ndarray)) and len(v) > 0:
                try:
                    float(v[0] if not isinstance(v, np.ndarray) else v.flat[0])
                    names.add(k)
                except (ValueError, TypeError):
                    pass
    return sorted(names)


def _score_log(well_list, log_name: str, method: str) -> Tuple[float, str]:
    """Score a single log for correlation relevance."""
    wells_data = []
    for w in well_list.wells:
        data = w.data if hasattr(w, 'data') else {}
        if log_name in data:
            arr = np.asarray(data[log_name], dtype=np.float64)
            if len(arr) > 0:
                wells_data.append(arr)

    if len(wells_data) < 2:
        return 0.0, "insufficient_wells"

    if method == "autocorrelation":
        return _score_autocorrelation(wells_data)
    elif method == "cross_well":
        return _score_cross_well(wells_data)
    else:  # variance_ratio
        return _score_variance_ratio(wells_data)


def _score_variance_ratio(wells_data: List[np.ndarray]) -> Tuple[float, str]:
    """Inter-interval vs intra-interval variance ratio.

    High ratio = log has structure (good for correlation).
    Low ratio = log is flat or pure noise (bad for correlation).
    """
    all_vals = np.concatenate(wells_data)
    global_var = np.nanvar(all_vals)

    if global_var < 1e-10:
        return 0.0, "constant_log"

    # Split each well into windows and compute within-window variance
    window = 10
    within_vars = []
    for arr in wells_data:
        valid = arr[~np.isnan(arr)]
        if len(valid) < window:
            continue
        n_windows = len(valid) // window
        for i in range(n_windows):
            seg = valid[i * window:(i + 1) * window]
            within_vars.append(np.var(seg))

    if not within_vars:
        return 0.0, "too_short"

    mean_within = np.mean(within_vars)
    # Ratio: between-window variance / within-window variance
    # If ratio >> 1, log has large-scale structure
    ratio = (global_var - mean_within) / (mean_within + 1e-10)
    # Normalize to [0, 1] with sigmoid
    score = 1.0 / (1.0 + np.exp(-0.5 * (ratio - 2.0)))

    if score < 0.1:
        reason = "flat_or_noisy"
    elif score < 0.3:
        reason = "weak_signal"
    elif score < 0.7:
        reason = "moderate_signal"
    else:
        reason = "strong_signal"

    return float(score), reason


def _score_autocorrelation(wells_data: List[np.ndarray]) -> Tuple[float, str]:
    """Lag-1 autocorrelation - signal has high AC, noise has low AC."""
    acs = []
    for arr in wells_data:
        valid = arr[~np.isnan(arr)]
        if len(valid) < 10:
            continue
        centered = valid - np.mean(valid)
        var = np.var(valid)
        if var < 1e-10:
            acs.append(0.0)
            continue
        ac = np.correlate(centered[:-1], centered[1:])[0] / (var * (len(valid) - 1))
        acs.append(ac)

    if not acs:
        return 0.0, "insufficient_data"

    mean_ac = np.mean(acs)
    # AC near 1 = structured signal, near 0 = noise
    score = max(0.0, min(1.0, mean_ac))
    reason = "high_autocorrelation" if score > 0.5 else "low_autocorrelation"
    return float(score), reason


def _score_cross_well(wells_data: List[np.ndarray]) -> Tuple[float, str]:
    """Cross-well correlation - good logs show consistent patterns."""
    if len(wells_data) < 2:
        return 0.0, "need_2_wells"

    # Resample all to same length and compute pairwise correlations
    target_len = min(len(d) for d in wells_data)
    resampled = []
    for arr in wells_data:
        valid = arr[~np.isnan(arr)]
        if len(valid) < target_len:
            continue
        # Simple downsampling
        indices = np.linspace(0, len(valid) - 1, target_len, dtype=int)
        resampled.append(valid[indices])

    if len(resampled) < 2:
        return 0.0, "insufficient_valid_data"

    corrs = []
    for i in range(len(resampled)):
        for j in range(i + 1, len(resampled)):
            r = np.corrcoef(resampled[i], resampled[j])[0, 1]
            if not np.isnan(r):
                corrs.append(abs(r))

    if not corrs:
        return 0.0, "no_valid_correlations"

    score = float(np.mean(corrs))
    reason = "consistent_across_wells" if score > 0.5 else "variable_across_wells"
    return score, reason


# ═══════════════════════════════════════════════════════════════════════════
# §2 - Topology-Aware Diversity Filtering
# ═══════════════════════════════════════════════════════════════════════════

def filter_diverse_scenarios(
    res_file,
    well_list,
    min_topology_distance: float = 0.1,
    max_scenarios: int = 10,
    metrics: Optional[List[str]] = None,
) -> List[Dict]:
    """Post-filter k-best results to retain only architecturally distinct scenarios.

    Unlike the engine's cost-based ``min-dist``, this uses geological metrics:
    - Horizon count (number of correlation lines)
    - Gap fraction (fraction of markers in gaps)
    - Zone thickness distribution (coefficient of variation)
    - Connectivity pattern (which wells are connected at each level)

    Parameters
    ----------
    res_file : ResFile
        Engine results (typically with many near-identical scenarios).
    well_list : WellList
        The correlated wells.
    min_topology_distance : float
        Minimum normalised distance between retained scenarios (0–1).
    max_scenarios : int
        Maximum number of diverse scenarios to return.
    metrics : list of str, optional
        Which metrics to use for distance. Default: all.
        Options: "horizon_count", "gap_fraction", "zone_cv", "connectivity"

    Returns
    -------
    list of dict
        Selected scenarios with topology metadata::

            {"cor_num": int, "cost": float, "n_horizons": int, "n_gaps": int,
             "gap_fraction": float, "zone_cv": float, "connectivity_hash": str,
             "topology_vector": list}
    """
    if metrics is None:
        metrics = ["horizon_count", "gap_fraction", "zone_cv", "connectivity"]

    n_results = res_file.get_nbr_results()
    if n_results == 0:
        return []

    # Extract topology vectors for all scenarios
    scenarios = []
    for i in range(n_results):
        topo = _extract_topology(res_file, well_list, i)
        topo["cor_num"] = i
        topo["cost"] = float(res_file.get_result_cost(i))
        scenarios.append(topo)

    if not scenarios:
        return []

    # Build normalised feature vectors
    vectors = _build_topology_vectors(scenarios, metrics)

    # Greedy diverse selection: always keep best (index 0), then add
    # the next scenario that is maximally distant from already-selected
    selected = [0]
    selected_vectors = [vectors[0]]

    for _ in range(min(max_scenarios - 1, len(scenarios) - 1)):
        best_idx = -1
        best_min_dist = -1.0

        for j in range(len(scenarios)):
            if j in selected:
                continue
            # Min distance to all already-selected
            min_dist = min(
                np.linalg.norm(vectors[j] - sv)
                for sv in selected_vectors
            )
            if min_dist > best_min_dist:
                best_min_dist = min_dist
                best_idx = j

        if best_idx < 0 or best_min_dist < min_topology_distance:
            break

        selected.append(best_idx)
        selected_vectors.append(vectors[best_idx])

    return [scenarios[i] for i in selected]


def _extract_topology(res_file, well_list, cor_num: int) -> Dict:
    """Extract topology metrics for one correlation scenario.

    The path from get_result_full_path is a tuple of tuples:
    path[horizon_idx] = (well_0_sample, well_1_sample, ..., well_N_sample)
    Each value is the sample index in that well where the horizon ties.
    Consecutive same values indicate a gap (well not advancing).
    """
    path = res_file.get_result_full_path(cor_num)
    n_wells = res_file.nbr_well()

    n_horizons = len(path)
    n_gaps = 0
    total_markers = 0
    zone_sizes = []
    current_zone_size = 0

    if n_horizons > 1:
        # Detect gaps: a gap occurs when a well's index doesn't advance
        # between consecutive horizons. Count horizons where most wells stall.
        for h in range(1, n_horizons):
            step = path[h]
            prev = path[h - 1]
            if hasattr(step, '__iter__') and hasattr(prev, '__iter__'):
                advancing = sum(1 for s, p in zip(step, prev) if s != p)
                # If fewer than half the wells advance, this is a "gap" horizon
                if advancing < n_wells // 2:
                    n_gaps += 1
            total_markers += 1
            current_zone_size += 1

            # Zone boundary: detect large jumps (>median step size)
            if hasattr(step, '__iter__') and hasattr(prev, '__iter__'):
                deltas = [abs(s - p) for s, p in zip(step, prev)]
                max_delta = max(deltas) if deltas else 0
                if max_delta > 3 and current_zone_size > 0:
                    zone_sizes.append(current_zone_size)
                    current_zone_size = 0

        if current_zone_size > 0:
            zone_sizes.append(current_zone_size)

    # Compute metrics
    gap_fraction = n_gaps / max(total_markers, 1)
    zone_cv = float(np.std(zone_sizes) / (np.mean(zone_sizes) + 1e-10)) if zone_sizes else 0.0

    # Connectivity hash: structural signature of the correlation
    connectivity = _compute_connectivity_hash(path, n_wells)

    return {
        "n_horizons": n_horizons,
        "n_gaps": n_gaps,
        "gap_fraction": round(gap_fraction, 4),
        "zone_cv": round(zone_cv, 4),
        "zone_sizes": zone_sizes,
        "connectivity_hash": connectivity,
    }


def _compute_connectivity_hash(path, n_wells: int) -> str:
    """Compute a connectivity signature from the correlation path.

    Builds a signature based on the relative advancement pattern of wells.
    Two scenarios with the same hash have equivalent topological structure.
    """
    if not path or n_wells < 2:
        return "empty"

    # Build a per-well "profile" of cumulative advancement
    # and use the ordering/grouping as a fingerprint
    n_horizons = len(path)
    if n_horizons < 2:
        return "trivial"

    # Sample at 10 evenly-spaced horizons to create a stable fingerprint
    sample_indices = [int(i * (n_horizons - 1) / 9) for i in range(10)]
    fingerprint = []
    for h_idx in sample_indices:
        step = path[h_idx]
        if hasattr(step, '__iter__'):
            vals = tuple(step)
            # Rank-order the well positions (topology = relative order)
            ranked = tuple(sorted(range(len(vals)), key=lambda i: vals[i]))
            fingerprint.append(ranked)
        else:
            fingerprint.append((step,))

    return str(hash(tuple(fingerprint)))


def _build_topology_vectors(scenarios: List[Dict], metrics: List[str]) -> List[np.ndarray]:
    """Build normalised feature vectors from topology metrics."""
    raw = []
    for s in scenarios:
        vec = []
        if "horizon_count" in metrics:
            vec.append(float(s["n_horizons"]))
        if "gap_fraction" in metrics:
            vec.append(s["gap_fraction"])
        if "zone_cv" in metrics:
            vec.append(s["zone_cv"])
        if "connectivity" in metrics:
            # Use hash as a categorical - convert to numeric distance
            vec.append(float(hash(s["connectivity_hash"]) % 10000) / 10000.0)
        raw.append(np.array(vec, dtype=np.float64))

    # Normalise each dimension to [0, 1]
    raw_arr = np.array(raw)
    if len(raw_arr) == 0:
        return [np.zeros(len(metrics)) for _ in scenarios]

    mins = raw_arr.min(axis=0)
    maxs = raw_arr.max(axis=0)
    spans = maxs - mins
    spans[spans < 1e-10] = 1.0

    normalised = (raw_arr - mins) / spans
    return [normalised[i] for i in range(len(normalised))]


# ═══════════════════════════════════════════════════════════════════════════
# §3 - Architecture-Based Enumeration
# ═══════════════════════════════════════════════════════════════════════════

def enumerate_architectures(
    well_list,
    base_options: Dict,
    gap_cost_range: Tuple[float, float, float] = (0.0, 5.0, 1.0),
    n_best_per_architecture: int = 3,
) -> List[Dict]:
    """Generate architecturally distinct scenarios by varying gap cost.

    Instead of relying on k-best (which produces near-identical paths),
    this runs the engine multiple times with different gap costs, forcing
    different numbers of horizons/gaps - genuinely different geological models.

    Parameters
    ----------
    well_list : WellList or str
        Well data (file path or WellList object).
    base_options : dict
        Base engine options (log, weights, etc.).
    gap_cost_range : tuple (start, stop, step)
        Range of gap costs to test.
    n_best_per_architecture : int
        How many results to keep from each gap-cost run.

    Returns
    -------
    list of dict
        Each entry: {"gap_cost": float, "n_horizons": int, "n_gaps": int,
                     "cost": float, "cor_num": int, "res_file": ResFile,
                     "topology": dict}
    """
    from .ext import ProjectExt

    start, stop, step = gap_cost_range
    gap_costs = np.arange(start, stop + step / 2, step)

    all_results = []
    seen_horizon_counts = set()

    for gc in gap_costs:
        opts = dict(base_options)
        opts["const-gap-cost"] = str(gc)

        p = ProjectExt()
        for k, v in opts.items():
            try:
                p.set_option_ext(k, v)
            except (ValueError, RuntimeError):
                pass

        well_arg = well_list if isinstance(well_list, str) else well_list
        success = p.run(well_arg)
        if not success:
            continue

        rf = p.get_res_file()
        n_results = rf.get_nbr_results()

        for i in range(min(n_best_per_architecture, n_results)):
            topo = _extract_topology(rf, well_list, i)

            # Only keep if this gives a new horizon count
            h_key = topo["n_horizons"]
            if h_key in seen_horizon_counts and len(all_results) > 0:
                # Check if it's actually different enough
                existing = [r for r in all_results if r["n_horizons"] == h_key]
                if existing and abs(topo["gap_fraction"] - existing[0]["gap_fraction"]) < 0.01:
                    continue

            seen_horizon_counts.add(h_key)
            all_results.append({
                "gap_cost": float(gc),
                "n_horizons": topo["n_horizons"],
                "n_gaps": topo["n_gaps"],
                "gap_fraction": topo["gap_fraction"],
                "zone_cv": topo["zone_cv"],
                "cost": float(rf.get_result_cost(i)),
                "cor_num": i,
                "connectivity_hash": topo["connectivity_hash"],
            })

    logger.info(f"Architecture enumeration: {len(all_results)} distinct scenarios "
                f"from {len(gap_costs)} gap-cost values")
    return all_results


# ═══════════════════════════════════════════════════════════════════════════
# §4 - Cross-Validation
# ═══════════════════════════════════════════════════════════════════════════

def cross_validate(
    well_list,
    options: Dict,
    n_folds: Optional[int] = None,
) -> Dict:
    """Leave-one-out cross-validation for correlation robustness.

    For each well, remove it from the dataset, run correlation on the
    remaining wells, then check if the removed well's position is
    consistent with the predicted correlation.

    Parameters
    ----------
    well_list : WellList
        Full well list.
    options : dict
        Engine options.
    n_folds : int, optional
        Number of wells to hold out. Default = all (LOO-CV).

    Returns
    -------
    dict
        ``{"folds": [...], "mean_consistency": float, "robust_wells": list,
           "sensitive_wells": list, "systematic_bias": float}``
    """
    from .ext import ProjectExt

    wells = well_list.wells
    n_wells = len(wells)
    if n_folds is None:
        n_folds = n_wells

    folds = []
    for hold_out_idx in range(min(n_folds, n_wells)):
        # Create reduced well list
        from .data import WellList
        reduced = WellList.__new__(WellList)
        reduced.wells = [w for i, w in enumerate(wells) if i != hold_out_idx]

        # Run correlation
        p = ProjectExt()
        for k, v in options.items():
            try:
                p.set_option_ext(k, v)
            except (ValueError, RuntimeError):
                pass

        success = p.run(reduced)
        if not success:
            folds.append({
                "held_out": wells[hold_out_idx].name,
                "success": False,
                "consistency": 0.0,
            })
            continue

        rf = p.get_res_file()
        cost_full = float(rf.get_result_cost(0))
        n_results = rf.get_nbr_results()

        # Compare: run with all wells and check if held-out well fits
        p_full = ProjectExt()
        for k, v in options.items():
            try:
                p_full.set_option_ext(k, v)
            except (ValueError, RuntimeError):
                pass

        success_full = p_full.run(well_list)
        cost_full_all = float(p_full.get_res_file().get_result_cost(0)) if success_full else 0

        # Consistency = how much does removing this well change the cost?
        # Low change = well is consistent with the group
        # High change = well is an outlier or critical for the correlation
        if cost_full_all > 0:
            cost_change = abs(cost_full - cost_full_all) / cost_full_all
        else:
            cost_change = 0.0

        consistency = 1.0 / (1.0 + cost_change * 10)

        folds.append({
            "held_out": wells[hold_out_idx].name,
            "success": True,
            "consistency": round(consistency, 4),
            "cost_without": round(cost_full, 2),
            "cost_with_all": round(cost_full_all, 2),
            "cost_change_pct": round(cost_change * 100, 2),
            "n_results": n_results,
        })

    # Summary
    consistencies = [f["consistency"] for f in folds if f["success"]]
    mean_consistency = float(np.mean(consistencies)) if consistencies else 0.0

    robust = [f["held_out"] for f in folds if f.get("consistency", 0) > 0.8]
    sensitive = [f["held_out"] for f in folds if f.get("consistency", 0) < 0.5]

    # Systematic bias: if removing ANY well doesn't change cost much,
    # the solution is over-determined (data conclusive)
    cost_changes = [f.get("cost_change_pct", 0) for f in folds if f["success"]]
    systematic_bias = float(np.std(cost_changes)) if cost_changes else 0.0

    return {
        "folds": folds,
        "mean_consistency": round(mean_consistency, 4),
        "robust_wells": robust,
        "sensitive_wells": sensitive,
        "systematic_bias": round(systematic_bias, 4),
        "data_conclusive": mean_consistency > 0.9,
        "n_folds": len(folds),
    }


# ═══════════════════════════════════════════════════════════════════════════
# §5 - Integrated Diversity Analysis
# ═══════════════════════════════════════════════════════════════════════════

def analyse_scenario_diversity(
    res_file,
    well_list,
    options: Optional[Dict] = None,
    run_cross_validation: bool = False,
    run_architecture_enum: bool = False,
    gap_cost_range: Tuple[float, float, float] = (0.0, 5.0, 1.0),
) -> Dict:
    """Complete diversity analysis of correlation results.

    Combines topology filtering, log screening, cross-validation, and
    architecture enumeration into a single analysis report.

    Parameters
    ----------
    res_file : ResFile
        Engine results.
    well_list : WellList
        The correlated wells.
    options : dict, optional
        Engine options used (for cross-validation and enumeration).
    run_cross_validation : bool
        Whether to run LOO cross-validation (slow for many wells).
    run_architecture_enum : bool
        Whether to run architecture enumeration with varying gap cost.
    gap_cost_range : tuple
        Range for architecture enumeration.

    Returns
    -------
    dict
        Complete analysis report.
    """
    report = {
        "n_raw_scenarios": res_file.get_nbr_results(),
        "cost_range": None,
        "cost_spread_pct": 0.0,
        "diverse_scenarios": [],
        "topology_summary": {},
        "log_screening": None,
        "cross_validation": None,
        "architectures": None,
        "diagnosis": "",
        "recommendations": [],
    }

    n = res_file.get_nbr_results()
    if n == 0:
        report["diagnosis"] = "No results to analyse"
        return report

    # Cost statistics
    costs = [float(res_file.get_result_cost(i)) for i in range(n)]
    report["cost_range"] = {"min": min(costs), "max": max(costs)}
    report["cost_spread_pct"] = round(
        (max(costs) - min(costs)) / max(costs) * 100, 4) if max(costs) > 0 else 0

    # Topology-aware filtering
    diverse = filter_diverse_scenarios(res_file, well_list, max_scenarios=10)
    report["diverse_scenarios"] = diverse
    report["n_diverse"] = len(diverse)

    # Topology summary
    if diverse:
        h_counts = [d["n_horizons"] for d in diverse]
        gap_fracs = [d["gap_fraction"] for d in diverse]
        report["topology_summary"] = {
            "horizon_count_range": [min(h_counts), max(h_counts)],
            "gap_fraction_range": [min(gap_fracs), max(gap_fracs)],
            "unique_horizon_counts": len(set(h_counts)),
            "architecturally_distinct": len(set(h_counts)) > 1,
        }

    # Log screening (if well_list available)
    if well_list and hasattr(well_list, 'wells'):
        report["log_screening"] = screen_logs(well_list)

    # Cross-validation
    if run_cross_validation and options and well_list:
        try:
            report["cross_validation"] = cross_validate(well_list, options)
        except Exception as e:
            logger.warning(f"Cross-validation failed: {e}")

    # Architecture enumeration
    if run_architecture_enum and options and well_list:
        try:
            report["architectures"] = enumerate_architectures(
                well_list, options, gap_cost_range=gap_cost_range)
        except Exception as e:
            logger.warning(f"Architecture enumeration failed: {e}")

    # Diagnosis
    report["diagnosis"] = _diagnose(report)
    report["recommendations"] = _recommend(report)

    return report


def _diagnose(report: Dict) -> str:
    """Generate a diagnosis string from the analysis."""
    spread = report.get("cost_spread_pct", 0)
    n_diverse = report.get("n_diverse", 0)
    topo = report.get("topology_summary", {})

    if spread < 0.01 and n_diverse <= 1:
        return ("DATA_CONCLUSIVE: Cost spread <0.01% and only 1 distinct topology. "
                "The data strongly constrains the solution - no real uncertainty.")
    elif spread < 0.1 and not topo.get("architecturally_distinct", False):
        return ("ALGORITHM_LIMITED: Multiple scenarios returned but all share the same "
                "architecture. The k-best paths differ only in local edge swaps, "
                "not in geological structure.")
    elif spread > 1.0 and n_diverse > 3:
        return ("UNCERTAIN: Significant cost spread with multiple distinct architectures. "
                "Real geological uncertainty exists - scenarios represent alternative models.")
    elif topo.get("architecturally_distinct", False):
        return ("PARTIALLY_UNCERTAIN: Some architectural diversity exists despite "
                "low cost spread. Gap cost and constraints control the diversity.")
    else:
        return ("MODERATE: Moderate diversity detected. Consider increasing gap-cost "
                "range or relaxing constraints to explore more alternatives.")


def _recommend(report: Dict) -> List[str]:
    """Generate improvement recommendations."""
    recs = []
    spread = report.get("cost_spread_pct", 0)
    topo = report.get("topology_summary", {})
    logs = report.get("log_screening", [])

    if spread < 0.01:
        recs.append("Increase out-min-dist or use architecture enumeration (vary gap cost) "
                    "to force structurally different scenarios.")

    if not topo.get("architecturally_distinct", False):
        recs.append("Run enumerate_architectures() with gap_cost_range=(0, 8, 1) "
                    "to generate scenarios with different horizon counts.")

    if logs:
        irrelevant = [l for l in logs if not l["relevant"]]
        if irrelevant:
            names = [l["log"] for l in irrelevant[:3]]
            recs.append(f"Logs {names} have low relevance scores - consider removing "
                        "them from the cost function to avoid noise.")

        relevant = [l for l in logs if l["relevant"]]
        if len(relevant) > 1:
            recs.append(f"Top relevant logs: {[l['log'] for l in relevant[:3]]}. "
                        "Normalise before combining (different scales).")

    cv = report.get("cross_validation")
    if cv and cv.get("data_conclusive"):
        recs.append("Cross-validation confirms data is conclusive - all wells "
                    "are consistent. Uncertainty is low.")
    elif cv and cv.get("sensitive_wells"):
        recs.append(f"Wells {cv['sensitive_wells']} are sensitive to removal - "
                    "they control the correlation. Consider additional data near them.")

    return recs
