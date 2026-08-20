#!/usr/bin/env python3
"""
Run ALL WeCo demo datasets with multiple configurations and produce
a comprehensive results analysis.

For each dataset, runs:
  A) Default/recommended parameters (from _DEMO_CATALOGUE)
  B) Variant configurations (different orders, gap costs, weights, constraints)

Outputs:
  - Per-dataset summary (costs, n_horizons, n_gaps, diversity)
  - Cross-scenario comparison (do results differ substantially?)
  - Connectivity/flow-pattern implications
  - Recommendations for improvement
"""

import sys
import os
import json
import time
import traceback
from pathlib import Path
from collections import defaultdict
from copy import deepcopy

# Ensure weco package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from weco.ext import ProjectExt
from weco.data import WellList, ResFile, ResAndWL
from weco.export import correlation_summary

# Demo data root
DATA_DIR = Path(__file__).resolve().parent.parent / "demo" / "data"


# ============================================================================
# DEMO CATALOGUE (from api.py - ground truth working parameters)
# ============================================================================

DEMO_CATALOGUE = {
    "distality": {
        "wells": "data_set_distality/wells.txt",
        "geology": "concept",
        "description": "2 wells - distality cost (Walther's Law)",
        "opts": {"dist-distal": "DISTAL", "dist-facies": "FACIES_1",
                 "dist-scaling": "1.0", "order": "distality",
                 "max-cor": "50", "nbr-cor": "30", "out-nbr-cor": "10",
                 "min-dist": "0.3", "out-min-dist": "0.15"},
    },
    "biozone_distality": {
        "wells": "data_set_biozone_distality/wells.txt",
        "geology": "concept",
        "description": "2 wells - biozone no-crossing + distality",
        "opts": {"dist-distal": "DISTAL", "dist-facies": "FACIES_1",
                 "no-crossing": "BIOZONES", "order": "distality",
                 "max-cor": "50", "nbr-cor": "30", "out-nbr-cor": "10",
                 "min-dist": "0.3", "out-min-dist": "0.15"},
    },
    "coal": {
        "wells": "data_set_coal/wells_10.txt",
        "geology": "coal",
        "description": "10 coal boreholes - gap cost + multi-log (DEN+GR+SON)",
        "opts": {"var-data": "DEN", "var-weight": "0.5",
                 "var-data2": "GR", "var-weight2": "0.3",
                 "var-data3": "SON", "var-weight3": "0.2",
                 "max-cor": "50", "nbr-cor": "20", "out-nbr-cor": "5",
                 "min-dist": "0.4", "out-min-dist": "0.15",
                 "const-gap-cost": "3.0", "band-width": "30"},
    },
    "quaternary": {
        "wells": "data_set_quaternary/wells_20.txt",
        "geology": "quaternary",
        "description": "20 Quaternary wells - gap cost + GR+RT",
        "opts": {"var-data": "GR", "var-weight": "0.7",
                 "var-data2": "RT", "var-weight2": "0.3",
                 "max-cor": "20", "nbr-cor": "10", "out-nbr-cor": "10",
                 "min-dist": "0.2", "out-min-dist": "0.1",
                 "const-gap-cost": "1.5", "band-width": "20"},
    },
    "shallow_marine": {
        "wells": "data_set_shallow_marine/wells.txt",
        "geology": "shallow_marine",
        "description": "10 wells - 3-log shoreface (GR+RHOB+DT)",
        "opts": {"var-data": "GR", "var-weight": "0.5",
                 "var-data2": "RHOB", "var-weight2": "0.3",
                 "var-data3": "DT", "var-weight3": "0.2",
                 "no-crossing": "BIOZONE",
                 "max-cor": "50", "nbr-cor": "20", "out-nbr-cor": "5",
                 "min-dist": "0.4", "out-min-dist": "0.2",
                 "const-gap-cost": "2.0", "band-width": "30"},
    },
    "bryson": {
        "wells": "data_set_bryson/wells.txt",
        "geology": "fluvial",
        "description": "7 Appalachian wells - categorical FACIES + ZONE no-crossing",
        "opts": {"var-data": "FACIES", "no-crossing": "ZONE",
                 "max-cor": "50", "nbr-cor": "30", "out-nbr-cor": "10",
                 "min-dist": "0.5", "out-min-dist": "0.25"},
    },
    "bryson_distality": {
        "wells": "data_set_bryson/wells.txt",
        "geology": "fluvial",
        "description": "7 Appalachian wells - distality ordering + ZONE no-crossing",
        "opts": {"var-data": "DISTALITY", "order": "distality",
                 "no-crossing": "ZONE",
                 "max-cor": "80", "nbr-cor": "50", "out-nbr-cor": "10",
                 "min-dist": "0.5", "out-min-dist": "0.25"},
    },
    "fluvial": {
        "wells": "data_set_fluvial/wells.txt",
        "geology": "fluvial",
        "description": "12 wells - discontinuous channel sandbodies",
        "opts": {"var-data": "GR", "var-weight": "1.0",
                 "max-cor": "50", "nbr-cor": "20", "out-nbr-cor": "5",
                 "min-dist": "0.5", "out-min-dist": "0.2",
                 "const-gap-cost": "1.0", "band-width": "30"},
    },
    "delta": {
        "wells": "data_set_delta/wells.txt",
        "geology": "deltaic",
        "description": "8 wells - prograding delta (GR+DEN)",
        "opts": {"var-data": "GR", "var-weight": "0.6",
                 "var-data2": "DEN", "var-weight2": "0.4",
                 "no-crossing": "SEQSTRAT",
                 "max-cor": "50", "nbr-cor": "20", "out-nbr-cor": "5",
                 "min-dist": "0.4", "out-min-dist": "0.2",
                 "const-gap-cost": "1.5", "band-width": "30"},
    },
    "sigrun": {
        "wells": "data_set_sigrun/wells.txt",
        "geology": "shallow_marine",
        "description": "2 North Sea wells - GR+NPHI",
        "opts": {"var-data": "GR", "var-weight": "0.6",
                 "var-data2": "NPHI", "var-weight2": "0.4",
                 "max-cor": "50", "nbr-cor": "30", "out-nbr-cor": "10",
                 "min-dist": "0.3", "out-min-dist": "0.15"},
    },
    "troll": {
        "wells": "data_set_troll/wells.txt",
        "geology": "shallow_marine",
        "description": "5 Troll wells - categorical FACIES only",
        "opts": {"var-data": "FACIES",
                 "max-cor": "50", "nbr-cor": "30", "out-nbr-cor": "10",
                 "min-dist": "0.5", "out-min-dist": "0.25"},
    },
    "troll_distality": {
        "wells": "data_set_troll/wells.txt",
        "geology": "shallow_marine",
        "description": "23 Troll wells - distality ordering + biozone",
        "opts": {"var-data": "DISTALITY", "order": "distality",
                 "no-crossing": "BIOZONE",
                 "max-cor": "50", "nbr-cor": "30", "out-nbr-cor": "15",
                 "min-dist": "0.3", "out-min-dist": "0.15"},
    },
    "hugin_tidal": {
        "wells": "data_set_hugin_tidal/facies.wells.txt",
        "geology": "shallow_marine",
        "description": "2 real North Sea wells - tidal distality",
        "opts": {"dist-distal": "DISTALITY", "dist-facies": "FACIES_1",
                 "dist-scaling": "1.0", "order": "distality",
                 "max-cor": "50", "nbr-cor": "30", "out-nbr-cor": "10",
                 "min-dist": "0.3", "out-min-dist": "0.15"},
    },
}


# ============================================================================
# VARIANT CONFIGURATIONS (per-demo meaningful alternatives)
# ============================================================================

def get_variants(demo_id, base_opts):
    """Generate meaningful variant configurations for a given demo."""
    variants = {}

    # --- Variant 1: Higher search depth (more exploration) ---
    v = deepcopy(base_opts)
    if "max-cor" in v:
        v["max-cor"] = str(int(float(v["max-cor"])) * 2)
    if "nbr-cor" in v:
        v["nbr-cor"] = str(int(float(v["nbr-cor"])) * 2)
    variants["high_search_depth"] = v

    # --- Variant 2: Lower min-dist (accept more similar scenarios) ---
    v = deepcopy(base_opts)
    v["min-dist"] = "0.1"
    v["out-min-dist"] = "0.05"
    variants["low_min_dist"] = v

    # --- Variant 3: Higher min-dist (force divergent scenarios) ---
    v = deepcopy(base_opts)
    v["min-dist"] = "0.7"
    v["out-min-dist"] = "0.4"
    variants["high_min_dist"] = v

    # --- Variant 4: Different gap cost ---
    if "const-gap-cost" in base_opts:
        v = deepcopy(base_opts)
        current_gap = float(v["const-gap-cost"])
        v["const-gap-cost"] = str(current_gap * 2)
        variants["high_gap_cost"] = v

        v = deepcopy(base_opts)
        v["const-gap-cost"] = str(max(0.1, current_gap * 0.5))
        variants["low_gap_cost"] = v
    else:
        # Add gap cost where there is none
        v = deepcopy(base_opts)
        v["const-gap-cost"] = "1.5"
        variants["add_gap_cost"] = v

    # --- Variant 5: Different weight distribution (for multi-log) ---
    if "var-weight2" in base_opts:
        v = deepcopy(base_opts)
        # Swap primary and secondary weights
        v["var-weight"] = base_opts.get("var-weight2", "0.5")
        v["var-weight2"] = base_opts.get("var-weight", "0.5")
        variants["swapped_weights"] = v

    # --- Variant 6: Remove no-crossing constraint ---
    if "no-crossing" in base_opts:
        v = deepcopy(base_opts)
        del v["no-crossing"]
        variants["no_constraints"] = v

    # --- Variant 7: Different band-width ---
    if "band-width" in base_opts:
        v = deepcopy(base_opts)
        current_bw = int(float(v["band-width"]))
        v["band-width"] = str(current_bw * 2)
        variants["wide_bandwidth"] = v

        v2 = deepcopy(base_opts)
        v2["band-width"] = str(max(5, current_bw // 2))
        variants["narrow_bandwidth"] = v2

    # --- Variant 8: More output scenarios ---
    v = deepcopy(base_opts)
    v["out-nbr-cor"] = "15"
    variants["more_output_scenarios"] = v

    return variants


# ============================================================================
# RUNNER
# ============================================================================

def run_single(wells_path, opts, label=""):
    """Run WeCo with given options and return results dict."""
    project = ProjectExt()

    # Apply options
    for key, val in opts.items():
        try:
            project.set_option_ext(key, val)
        except ValueError as e:
            return {"error": f"Option error: {key}={val}: {e}", "label": label}

    t0 = time.time()
    try:
        success = project.run(str(wells_path))
    except Exception as e:
        return {"error": f"Run failed: {e}", "label": label}
    elapsed = time.time() - t0

    if not success:
        return {"error": "Run returned False", "label": label, "elapsed": elapsed}

    # Extract results
    try:
        res = project.get_res_file()
        n_results = res.get_nbr_results()
        costs = []
        horizons = []
        gaps = []

        for i in range(min(n_results, 20)):
            cost = res.get_result_cost(i)
            path = res.get_result_full_path(i)
            n_horizons = 0
            n_gaps = 0
            n_wells = res.nbr_well()
            prev = path[0] if path else None
            for step in path[1:]:
                if step != prev:
                    n_horizons += 1
                    advancing = sum(1 for w in range(n_wells)
                                    if step[w] != prev[w])
                    if advancing < n_wells:
                        n_gaps += 1
                prev = step
            costs.append(float(cost))
            horizons.append(n_horizons)
            gaps.append(n_gaps)

        # Compute diversity: how different are the scenarios?
        diversity = _compute_path_diversity(res, min(n_results, 10))

        return {
            "label": label,
            "success": True,
            "elapsed": elapsed,
            "n_results": n_results,
            "costs": costs,
            "cost_range": (min(costs), max(costs)) if costs else (0, 0),
            "cost_spread": (max(costs) - min(costs)) / max(costs) if costs and max(costs) > 0 else 0,
            "horizons": horizons,
            "gaps": gaps,
            "avg_horizons": sum(horizons) / len(horizons) if horizons else 0,
            "avg_gaps": sum(gaps) / len(gaps) if gaps else 0,
            "diversity": diversity,
        }
    except Exception as e:
        return {"error": f"Result extraction failed: {e}", "label": label,
                "elapsed": elapsed, "traceback": traceback.format_exc()}


def _compute_path_diversity(res, n_paths):
    """Compute pairwise Jaccard distance between correlation paths."""
    if n_paths < 2:
        return {"mean_jaccard": 0.0, "max_jaccard": 0.0, "scenario_spread": "none"}

    paths = []
    for i in range(n_paths):
        try:
            path = res.get_result_full_path(i)
            paths.append(set(path))
        except Exception:
            continue

    if len(paths) < 2:
        return {"mean_jaccard": 0.0, "max_jaccard": 0.0, "scenario_spread": "none"}

    distances = []
    for i in range(len(paths)):
        for j in range(i + 1, len(paths)):
            union = len(paths[i] | paths[j])
            inter = len(paths[i] & paths[j])
            if union > 0:
                distances.append(1.0 - inter / union)
            else:
                distances.append(0.0)

    mean_d = sum(distances) / len(distances) if distances else 0.0
    max_d = max(distances) if distances else 0.0

    if mean_d < 0.05:
        spread = "negligible"
    elif mean_d < 0.15:
        spread = "low"
    elif mean_d < 0.35:
        spread = "moderate"
    elif mean_d < 0.60:
        spread = "high"
    else:
        spread = "very_high"

    return {"mean_jaccard": round(mean_d, 4), "max_jaccard": round(max_d, 4),
            "scenario_spread": spread}


# ============================================================================
# MAIN
# ============================================================================

def main():
    print("=" * 80)
    print("  WeCo COMPREHENSIVE DEMO ANALYSIS")
    print("  Running all demos with default + variant configurations")
    print("=" * 80)
    print()

    all_results = {}

    for demo_id, demo in DEMO_CATALOGUE.items():
        wells_path = DATA_DIR / demo["wells"]
        if not wells_path.exists():
            print(f"  [SKIP] {demo_id}: {wells_path} not found")
            continue

        print(f"\n{'─' * 70}")
        print(f"  DEMO: {demo_id}")
        print(f"  Description: {demo['description']}")
        print(f"  Wells: {demo['wells']}")
        print(f"{'─' * 70}")

        demo_results = {"description": demo["description"],
                        "geology": demo["geology"],
                        "wells_file": demo["wells"],
                        "runs": {}}

        # A) Default configuration
        print(f"    [A] Default configuration...")
        result = run_single(wells_path, demo["opts"], label="default")
        demo_results["runs"]["default"] = result
        if "error" in result:
            print(f"        ERROR: {result['error']}")
        else:
            print(f"        OK: {result['n_results']} results, "
                  f"cost=[{result['cost_range'][0]:.3f}, {result['cost_range'][1]:.3f}], "
                  f"diversity={result['diversity']['scenario_spread']}, "
                  f"time={result['elapsed']:.2f}s")

        # B) Variant configurations
        variants = get_variants(demo_id, demo["opts"])
        for var_name, var_opts in variants.items():
            print(f"    [V] {var_name}...")
            result = run_single(wells_path, var_opts, label=var_name)
            demo_results["runs"][var_name] = result
            if "error" in result:
                print(f"        ERROR: {result['error']}")
            else:
                print(f"        OK: {result['n_results']} results, "
                      f"cost=[{result['cost_range'][0]:.3f}, {result['cost_range'][1]:.3f}], "
                      f"diversity={result['diversity']['scenario_spread']}, "
                      f"time={result['elapsed']:.2f}s")

        all_results[demo_id] = demo_results

    # Save raw results
    output_path = Path(__file__).resolve().parent.parent / "tmp" / "demo_analysis_results.json"
    output_path.parent.mkdir(exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\n\nRaw results saved to: {output_path}")

    # Print summary table
    print_summary(all_results)

    return all_results


def print_summary(all_results):
    """Print a structured summary of all results."""
    print("\n\n" + "=" * 80)
    print("  SUMMARY TABLE")
    print("=" * 80)
    print(f"{'Demo':<22} {'Default Cost':<14} {'N-res':<6} {'Diversity':<12} "
          f"{'Variant Δ':<12} {'Consistent?'}")
    print("-" * 80)

    for demo_id, data in all_results.items():
        runs = data["runs"]
        default = runs.get("default", {})
        if "error" in default:
            print(f"{demo_id:<22} {'ERROR':<14} {'-':<6} {'-':<12} {'-':<12} -")
            continue

        cost_str = f"{default['cost_range'][0]:.2f}-{default['cost_range'][1]:.2f}"
        diversity = default["diversity"]["scenario_spread"]
        n_res = default["n_results"]

        # Check if variants produce substantially different results
        variant_costs = []
        for vname, vres in runs.items():
            if vname == "default":
                continue
            if "error" not in vres and "costs" in vres and vres["costs"]:
                variant_costs.append(vres["costs"][0])

        if variant_costs and default["costs"]:
            cost_delta = max(abs(vc - default["costs"][0]) for vc in variant_costs)
            ref = default["costs"][0] if default["costs"][0] != 0 else 1.0
            relative_delta = cost_delta / abs(ref)
            delta_str = f"{relative_delta:.1%}"
            consistent = "YES" if relative_delta < 0.3 else "VARIES"
        else:
            delta_str = "-"
            consistent = "?"

        print(f"{demo_id:<22} {cost_str:<14} {n_res:<6} {diversity:<12} "
              f"{delta_str:<12} {consistent}")

    # Detailed cross-analysis
    print("\n\n" + "=" * 80)
    print("  CROSS-SCENARIO ANALYSIS")
    print("=" * 80)

    for demo_id, data in all_results.items():
        runs = data["runs"]
        default = runs.get("default", {})
        if "error" in default:
            continue

        print(f"\n--- {demo_id} ({data['geology']}) ---")
        print(f"  Description: {data['description']}")

        # Diversity analysis
        diversity = default.get("diversity", {})
        print(f"  Default diversity: {diversity.get('scenario_spread', '?')} "
              f"(Jaccard mean={diversity.get('mean_jaccard', 0):.3f}, "
              f"max={diversity.get('max_jaccard', 0):.3f})")
        print(f"  Default results: {default['n_results']}, "
              f"avg horizons={default['avg_horizons']:.1f}, "
              f"avg gaps={default['avg_gaps']:.1f}")

        # Compare variants
        print(f"  Variants ({len(runs) - 1} tested):")
        for vname, vres in sorted(runs.items()):
            if vname == "default":
                continue
            if "error" in vres:
                print(f"    {vname}: FAILED ({vres['error'][:60]})")
            else:
                vdiv = vres.get("diversity", {})
                print(f"    {vname}: cost={vres['cost_range'][0]:.3f}-{vres['cost_range'][1]:.3f}, "
                      f"diversity={vdiv.get('scenario_spread', '?')}, "
                      f"h={vres['avg_horizons']:.1f}, g={vres['avg_gaps']:.1f}")


if __name__ == "__main__":
    main()
