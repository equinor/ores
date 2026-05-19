"""
WeCo Validation Module
======================

Compare WeCo correlation results against reference (manual/expert)
correlations to measure quality and identify discrepancies.

Inspired by the PhD thesis discussion (§6.3.5) on evaluating correlation
outcomes against biostratigraphic and expert interpretations, and the
Phase II proposal requirement for "ground-truthing".

Reference: Baville (2022) §6.3.5, Phase II Postdoc Proposal (2022)
"""

from __future__ import annotations

import csv
from typing import Optional, Union

import numpy as np

from .data import ResFile, WellList, ResAndWL


# ---------------------------------------------------------------------------
# Reference correlation loader
# ---------------------------------------------------------------------------

def load_reference_csv(
    filepath: str,
    well_list: Union[str, WellList] = None,
) -> list[dict[str, int]]:
    """Load a reference correlation from CSV.

    Expected format (one row per correlation line)::

        Well_01,Well_02,Well_03
        5,3,7
        10,8,12
        ...

    Each row maps a marker index in each well. Columns are well names.
    Alternatively, columns can be well indices (0-indexed).

    Parameters
    ----------
    filepath : str
        Path to CSV file.
    well_list : str or WellList, optional
        If provided, validates well names against the well list.

    Returns
    -------
    list[dict[str, int]]
        Each element: ``{well_name: marker_index, ...}``
    """
    if isinstance(well_list, str):
        well_list = WellList(well_list)

    lines = []
    with open(filepath, "r") as f:
        reader = csv.reader(f)
        header = next(reader)
        well_names = [h.strip() for h in header]

        for row in reader:
            if not row or not row[0].strip():
                continue
            tie = {}
            for name, val in zip(well_names, row):
                try:
                    tie[name] = int(val.strip())
                except ValueError:
                    pass
            if tie:
                lines.append(tie)

    return lines


def load_reference_from_resfile(
    res_file: Union[str, ResFile],
    well_list: Union[str, WellList],
    cor_num: int = 0,
) -> list[dict[str, int]]:
    """Load a reference correlation from another ResFile.

    Useful for comparing two WeCo runs or against an outcome reference.

    Parameters
    ----------
    res_file : str or ResFile
        Reference result file.
    well_list : str or WellList
        Well list for well name mapping.
    cor_num : int
        Which path to extract from the reference.

    Returns
    -------
    list[dict[str, int]]
        Each element: ``{well_name: marker_index, ...}``
    """
    data = ResAndWL(res_file, well_list)
    if not data.check():
        raise ValueError("Invalid reference ResFile / WellList")

    n = data.res_file.get_nbr_results()
    if cor_num < 0 or cor_num >= n:
        raise IndexError(f"Correlation {cor_num} out of range (0..{n-1})")

    path = data.res_file.get_result_full_path(cor_num)
    well_names = data.well_names()
    n_wells = data.res_file.nbr_well()

    lines = []
    prev = None
    for step in path:
        if step != prev:
            tie = {well_names[wi]: step[wi] for wi in range(n_wells)}
            lines.append(tie)
            prev = step

    return lines


# ---------------------------------------------------------------------------
# Comparison metrics
# ---------------------------------------------------------------------------

def compare_correlations(
    computed: Union[str, ResFile],
    reference: list[dict[str, int]],
    well_list: Union[str, WellList],
    cor_num: int = 0,
    depth_prop: Optional[str] = None,
) -> dict:
    """Compare a WeCo result against a reference correlation.

    Parameters
    ----------
    computed : str or ResFile
        WeCo result to evaluate.
    reference : list[dict[str, int]]
        Reference correlation lines (from :func:`load_reference_csv`).
    well_list : str or WellList
        Well list for depth data.
    cor_num : int
        Which n-best path to compare.
    depth_prop : str, optional
        Name of depth data channel.

    Returns
    -------
    dict
        Metrics dictionary with:

        - **marker_offset_mean**: Mean absolute marker offset across
          matched ties.
        - **marker_offset_max**: Max absolute marker offset.
        - **depth_offset_mean**: Mean absolute depth offset (if depth
          available).
        - **depth_offset_max**: Max absolute depth offset.
        - **match_rate**: Fraction of reference ties found (within
          tolerance) in computed result.
        - **gap_diff**: Difference in number of gaps.
        - **n_reference**: Number of reference correlation lines.
        - **n_computed**: Number of computed correlation lines.
        - **per_well**: Per-well statistics.
        - **matched_lines**: List of (ref_tie, computed_tie, offset) tuples.
        - **unmatched_lines**: Reference ties not found in computed result.
    """
    data = ResAndWL(computed, well_list)
    if not data.check():
        raise ValueError("Invalid computed ResFile / WellList")

    n = data.res_file.get_nbr_results()
    if cor_num < 0 or cor_num >= n:
        raise IndexError(f"Correlation {cor_num} out of range (0..{n-1})")

    path = data.res_file.get_result_full_path(cor_num)
    well_names = data.well_names()
    n_wells = data.res_file.nbr_well()
    depths = data.get_zdatas(depth_prop)

    # Extract computed ties (deduplicated)
    computed_ties = []
    prev = None
    for step in path:
        if step != prev:
            tie = {well_names[wi]: step[wi] for wi in range(n_wells)}
            computed_ties.append(tie)
            prev = step

    # Build lookup: well_name → column index
    name_to_col = {well_names[wi]: wi for wi in range(n_wells)}

    # Match each reference line to the nearest computed line
    matched = []
    unmatched = []
    used_computed = set()

    for ref_tie in reference:
        # Find closest computed tie (by sum of absolute marker offsets)
        best_idx = None
        best_offset = float("inf")
        for ci, comp_tie in enumerate(computed_ties):
            if ci in used_computed:
                continue
            total_off = 0
            n_match = 0
            for wn, rm in ref_tie.items():
                if wn in comp_tie:
                    total_off += abs(comp_tie[wn] - rm)
                    n_match += 1
            if n_match > 0:
                avg_off = total_off / n_match
                if avg_off < best_offset:
                    best_offset = avg_off
                    best_idx = ci

        if best_idx is not None and best_offset < 50:  # tolerance
            matched.append((ref_tie, computed_ties[best_idx], best_offset))
            used_computed.add(best_idx)
        else:
            unmatched.append(ref_tie)

    # Compute per-well statistics
    per_well = {}
    for wn in well_names:
        offsets_marker = []
        offsets_depth = []
        col = name_to_col.get(wn)
        for ref_tie, comp_tie, _ in matched:
            if wn in ref_tie and wn in comp_tie:
                m_off = abs(comp_tie[wn] - ref_tie[wn])
                offsets_marker.append(m_off)
                if col is not None and depths:
                    d_ref = depths[col][ref_tie[wn]]
                    d_comp = depths[col][comp_tie[wn]]
                    offsets_depth.append(abs(d_comp - d_ref))

        per_well[wn] = {
            "marker_offset_mean": float(np.mean(offsets_marker))
            if offsets_marker else 0.0,
            "marker_offset_max": int(max(offsets_marker))
            if offsets_marker else 0,
            "depth_offset_mean": float(np.mean(offsets_depth))
            if offsets_depth else 0.0,
            "n_matched": len(offsets_marker),
        }

    # Aggregate
    all_marker_off = [m[2] for m in matched]
    all_depth_off = []
    for ref_tie, comp_tie, _ in matched:
        for wn in ref_tie:
            col = name_to_col.get(wn)
            if col is not None and wn in comp_tie and depths:
                d_ref = depths[col][ref_tie[wn]]
                d_comp = depths[col][comp_tie[wn]]
                all_depth_off.append(abs(d_comp - d_ref))

    # Count gaps in computed
    n_gaps_computed = 0
    prev = path[0]
    for step in path[1:]:
        if step != prev:
            advancing = sum(1 for w in range(n_wells) if step[w] != prev[w])
            if advancing < n_wells:
                n_gaps_computed += 1
        prev = step

    return {
        "marker_offset_mean": float(np.mean(all_marker_off))
        if all_marker_off else 0.0,
        "marker_offset_max": float(np.max(all_marker_off))
        if all_marker_off else 0.0,
        "depth_offset_mean": float(np.mean(all_depth_off))
        if all_depth_off else 0.0,
        "depth_offset_max": float(np.max(all_depth_off))
        if all_depth_off else 0.0,
        "match_rate": len(matched) / max(len(reference), 1),
        "n_gaps_computed": n_gaps_computed,
        "n_reference": len(reference),
        "n_computed": len(computed_ties),
        "n_matched": len(matched),
        "n_unmatched": len(unmatched),
        "per_well": per_well,
        "matched_lines": matched,
        "unmatched_lines": unmatched,
    }


# ---------------------------------------------------------------------------
# Quality scoring (from thesis §6.3.4 — minor cost changes → big effects)
# ---------------------------------------------------------------------------

def score_correlation_quality(
    res_file: Union[str, ResFile],
    well_list: Union[str, WellList],
    cor_num: int = 0,
    reference: Optional[list[dict[str, int]]] = None,
) -> dict:
    """Score the quality of a correlation result on [0, 1].

    Criteria (from Baville 2022 §6.3.4 and §6.3.5):

    1. **Cost** (0.25): lower cumulative cost → higher quality
    2. **Gaps** (0.25): fewer gaps → higher quality
    3. **Consistency** (0.25): correlation lines don't cross →
       monotonic marker progression
    4. **Reference match** (0.25): if reference provided, match rate

    Parameters
    ----------
    res_file, well_list, cor_num
        As for :func:`compare_correlations`.
    reference : list, optional
        If provided, includes reference match in scoring.

    Returns
    -------
    dict
        ``{"total": float, "cost_score": float, "gap_score": float,
        "consistency_score": float, "reference_score": float}``
    """
    data = ResAndWL(res_file, well_list)
    if not data.check():
        raise ValueError("Invalid ResFile / WellList")

    n = data.res_file.get_nbr_results()
    if cor_num < 0 or cor_num >= n:
        raise IndexError(f"Correlation {cor_num} out of range (0..{n-1})")

    path = data.res_file.get_result_full_path(cor_num)
    n_wells = data.res_file.nbr_well()
    cost = data.res_file.get_result_cost(cor_num)

    # 1. Cost score — normalised against worst path
    if n > 1:
        worst_cost = data.res_file.get_result_cost(n - 1)
        cost_score = 1.0 - (cost / (worst_cost + 1e-10))
    else:
        cost_score = 1.0  # only one path, it's the best

    cost_score = max(0.0, min(1.0, cost_score))

    # 2. Gap score — fewer gaps is better
    n_steps = 0
    n_gaps = 0
    prev = path[0]
    for step in path[1:]:
        if step != prev:
            n_steps += 1
            advancing = sum(1 for w in range(n_wells) if step[w] != prev[w])
            if advancing < n_wells:
                n_gaps += 1
        prev = step

    gap_score = 1.0 - (n_gaps / max(n_steps, 1))
    gap_score = max(0.0, min(1.0, gap_score))

    # 3. Consistency score — check monotonicity per well
    n_violations = 0
    for wi in range(n_wells):
        prev_m = path[0][wi]
        for step in path[1:]:
            cur_m = step[wi]
            if cur_m < prev_m:
                n_violations += 1
            prev_m = cur_m

    total_pairs = len(path) * n_wells
    consistency_score = 1.0 - (n_violations / max(total_pairs, 1))
    consistency_score = max(0.0, min(1.0, consistency_score))

    # 4. Reference match score
    reference_score = 0.0
    if reference is not None:
        well_names = ResAndWL(res_file, well_list).well_names()
        comparison = compare_correlations(res_file, reference, well_list,
                                         cor_num=cor_num)
        reference_score = comparison["match_rate"]
    else:
        reference_score = None  # not applicable

    # Weighted total
    if reference_score is not None:
        total = (0.25 * cost_score + 0.25 * gap_score
                 + 0.25 * consistency_score + 0.25 * reference_score)
    else:
        total = (cost_score + gap_score + consistency_score) / 3.0

    return {
        "total": float(total),
        "cost_score": float(cost_score),
        "gap_score": float(gap_score),
        "consistency_score": float(consistency_score),
        "reference_score": float(reference_score)
        if reference_score is not None else None,
    }


# ---------------------------------------------------------------------------
# Multi-result comparison
# ---------------------------------------------------------------------------

def compare_n_best(
    res_file: Union[str, ResFile],
    well_list: Union[str, WellList],
    n_best: int = 10,
) -> list[dict]:
    """Compare the n-best correlation paths against each other.

    Useful for understanding how much the alternatives differ
    (thesis §3.4.1, §6.3.4: "minor changes in cost → different
    connectivity").

    Parameters
    ----------
    res_file, well_list
        WeCo result and well data.
    n_best : int
        How many paths to compare.

    Returns
    -------
    list[dict]
        Per-path stats: ``{"rank": int, "cost": float, "n_horizons": int,
        "n_gaps": int, "diff_vs_best": int}``
    """
    data = ResAndWL(res_file, well_list)
    if not data.check():
        raise ValueError("Invalid ResFile / WellList")

    n = min(n_best, data.res_file.get_nbr_results())
    n_wells = data.res_file.nbr_well()

    best_path = data.res_file.get_result_full_path(0)
    results = []

    for i in range(n):
        path = data.res_file.get_result_full_path(i)
        cost = data.res_file.get_result_cost(i)

        # Count horizons and gaps
        n_horizons = 0
        n_gaps = 0
        prev = path[0]
        for step in path[1:]:
            if step != prev:
                n_horizons += 1
                advancing = sum(1 for w in range(n_wells)
                                if step[w] != prev[w])
                if advancing < n_wells:
                    n_gaps += 1
            prev = step

        # Count lines that differ from best path
        diff_count = 0
        if i > 0:
            for step_a, step_b in zip(path, best_path):
                if step_a != step_b:
                    diff_count += 1

        results.append({
            "rank": i + 1,
            "cost": float(cost),
            "n_horizons": n_horizons,
            "n_gaps": n_gaps,
            "diff_vs_best": diff_count,
        })

    return results
