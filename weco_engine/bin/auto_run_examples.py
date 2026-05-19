#!/usr/bin/env python3
"""
WeCo Auto-Run Examples with Plots
==================================
Runs all included data sets through the WeCo engine via the Python API,
generates correlation plots using matplotlib, and saves PNG outputs.

Usage:
    source ~/.venv/bin/activate
    python auto_run_examples.py              # run all
    python auto_run_examples.py --dataset 1  # run dataset 1 only
    python auto_run_examples.py --list       # list available datasets
"""

import os
import sys
import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # non-interactive backend for headless rendering
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

# ── WeCo imports ─────────────────────────────────────────────────────────
from weco.ext import ProjectExt
from weco.data import WellList, ResFile, ResAndWL

SCRIPT_DIR = Path(__file__).resolve().parent.parent  # bin/ → project root
DATA_DIR = SCRIPT_DIR / "data"
OUTPUT_DIR = SCRIPT_DIR / "output"


# ═══════════════════════════════════════════════════════════════════════════
#  Dataset definitions
# ═══════════════════════════════════════════════════════════════════════════

DATASETS = {
    # ── 1: Variance cost – weight sweep on 3 synthetic wells ──────────
    "1_variance_weights": {
        "title": "Dataset 1.1 – Variance Cost Weight Sweep (3 wells)",
        "description": (
            "Three synthetic wells with two data properties (VarData1, VarData2).\n"
            "Five runs sweep the relative weight between the two properties.\n"
            "Demonstrates how changing var-weight steers the correlation."
        ),
        "wells": DATA_DIR / "data_set_1.1" / "wells.txt",
        "runs": [
            {"name": "VarData1_only",  "opts": {"var_data": "VarData1", "var_weight": 1.0,
                                                 "var_data2": "VarData2", "var_weight2": 0.0}},
            {"name": "VarData2_only",  "opts": {"var_data": "VarData1", "var_weight": 0.0,
                                                 "var_data2": "VarData2", "var_weight2": 1.0}},
            {"name": "Equal_50_50",    "opts": {"var_data": "VarData1", "var_weight": 0.5,
                                                 "var_data2": "VarData2", "var_weight2": 0.5}},
            {"name": "Favor1_70_30",   "opts": {"var_data": "VarData1", "var_weight": 0.7,
                                                 "var_data2": "VarData2", "var_weight2": 0.3}},
            {"name": "Favor2_30_70",   "opts": {"var_data": "VarData1", "var_weight": 0.3,
                                                 "var_data2": "VarData2", "var_weight2": 0.7}},
        ],
        "common_opts": {"cost_function": "composite", "order": "linear",
                        "max_cor": 10, "nbr_cor": 10, "out_nbr_cor": 10},
    },

    # ── 2: No-crossing constraint ─────────────────────────────────────
    "2_no_crossing": {
        "title": "Dataset 1.2 – No-Crossing Region Constraint",
        "description": (
            "Adds no-crossing constraint on region 'NoCrossing' which forces\n"
            "correlation lines to respect zone ordering (e.g. stratigraphic units)."
        ),
        "wells": DATA_DIR / "data_set_1.2" / "wells.txt",
        "runs": [
            {"name": "with_no_crossing", "opts": {"var_data": "VarData1", "no_crossing": "NoCrossing"}},
        ],
        "common_opts": {"cost_function": "composite", "order": "linear",
                        "max_cor": 10, "nbr_cor": 10, "out_nbr_cor": 10},
    },

    # ── 3: Distal facies cost (geological) ────────────────────────────
    "3_distality": {
        "title": "Dataset 3 – Distality-Facies Cost (Real Well Data)",
        "description": (
            "Two wells (A, B) with DEPTH, DISTAL, FACIES properties and\n"
            "regions (BIOZONES, SEQUENCE). Uses dist-distal/dist-facies cost\n"
            "to penalise inconsistent facies vs. distality relationships.\n"
            "Order = distality (sorts wells most-distal first)."
        ),
        "wells": DATA_DIR / "data_set_3" / "wells.txt",
        "runs": [
            {"name": "distality_facies1", "opts": {
                "dist_distal": "DISTAL", "dist_facies": "FACIES_1", "dist_scaling": 1.0}},
        ],
        "common_opts": {"cost_function": "composite", "order": "distality",
                        "max_cor": 50, "nbr_cor": 50, "out_nbr_cor": 50},
    },

    # ── 4: Gap cost exploration ───────────────────────────────────────
    "4_gap_cost": {
        "title": "Dataset 4 – Gap Cost Exploration",
        "description": (
            "Same wells as dataset 3. Explores the effect of const-gap-cost\n"
            "which penalises gaps (where a marker in one well has no match).\n"
            "Higher gap cost forces more 1-to-1 matching; lower allows more gaps."
        ),
        "wells": DATA_DIR / "data_set_4" / "wells.txt",
        "runs": [
            {"name": "gap0_distality",    "opts": {"const_gap_cost": 0.0,
                                                     "dist_distal": "DISTAL", "dist_facies": "FACIES_1"}},
            {"name": "gap5_distality",    "opts": {"const_gap_cost": 5.0,
                                                     "dist_distal": "DISTAL", "dist_facies": "FACIES_1"}},
            {"name": "gap8_distality",    "opts": {"const_gap_cost": 8.0,
                                                     "dist_distal": "DISTAL", "dist_facies": "FACIES_1"}},
        ],
        "common_opts": {"cost_function": "composite", "order": "distality",
                        "max_cor": 50, "nbr_cor": 50, "out_nbr_cor": 50},
    },

    # ── 5: Ordering strategies ────────────────────────────────────────
    "5_ordering": {
        "title": "Dataset 1.1 – Ordering Strategy Comparison",
        "description": (
            "Same 3 wells, same variance cost, but different ordering:\n"
            "linear, pyramidal, inverse. Shows how task ordering affects\n"
            "the best correlation when wells are correlated in different sequences."
        ),
        "wells": DATA_DIR / "data_set_1.1" / "wells.txt",
        "runs": [
            {"name": "order_linear",    "opts": {"order": "linear"}},
            {"name": "order_pyramidal", "opts": {"order": "pyramidal"}},
            {"name": "order_inverse",   "opts": {"order": "inverse"}},
        ],
        "common_opts": {"cost_function": "composite", "var_data": "VarData1",
                        "var_weight": 1.0, "max_cor": 10, "nbr_cor": 10,
                        "out_nbr_cor": 10},
    },
}


# ═══════════════════════════════════════════════════════════════════════════
#  Plotting helpers
# ═══════════════════════════════════════════════════════════════════════════

WELL_COLORS = plt.cm.tab10.colors

def plot_correlation(well_list: WellList, res_file: ResFile,
                     title: str, out_path: Path, cor_index: int = 0,
                     data_name: str = None, depth_name: str = None):
    """
    Plot well logs side-by-side with correlation lines for a single result.

    Parameters
    ----------
    well_list : WellList
    res_file  : ResFile
    title     : plot title
    out_path  : output PNG path
    cor_index : which correlation result to plot (0 = best)
    data_name : optional data property to plot as a curve
    depth_name: optional depth property name (default: marker index)
    """
    if res_file.get_nbr_results() == 0:
        print(f"  [WARN] No results for {title}")
        return

    n_wells = len(res_file.well_id)
    well_map = res_file.well_id_map()

    # Get wells referenced in result
    wells = [well_list.wells[wid] for wid in res_file.well_id]
    well_names = [w.name for w in wells]

    # Determine depth axis for each well
    def get_depth(well):
        if depth_name and depth_name in well.data:
            return list(well.data[depth_name])
        # fallback: use marker index
        return list(range(well.size))

    depths = [get_depth(w) for w in wells]

    # Detect a plottable data property
    if data_name is None:
        # pick first non-depth data property
        for dname in wells[0].data:
            if dname.upper() not in ("DEPTH", "MD", "TVD", "TVDSS"):
                data_name = dname
                break

    # ── Create figure ─────────────────────────────────────────────
    fig_width = max(8, 2 * n_wells + 3)
    fig, axes = plt.subplots(1, n_wells, figsize=(fig_width, 8),
                              sharey=False)
    if n_wells == 1:
        axes = [axes]

    fig.suptitle(title, fontsize=12, fontweight="bold")

    # Plot each well log
    for i, (well, ax, depth) in enumerate(zip(wells, axes, depths)):
        ax.set_title(well.name, fontsize=10, color=WELL_COLORS[i % 10])
        ax.invert_yaxis()
        ax.set_ylabel("Depth / Marker Index")

        if data_name and data_name in well.data:
            vals = list(well.data[data_name])[:len(depth)]
            ax.plot(vals, depth[:len(vals)], color=WELL_COLORS[i % 10],
                    linewidth=1.2, label=data_name)
            ax.set_xlabel(data_name)
            ax.legend(fontsize=7, loc="lower right")
        else:
            ax.set_xlim(-0.5, 0.5)
            ax.axvline(0, color=WELL_COLORS[i % 10], linewidth=2)
            ax.set_xlabel("Well Stick")

        ax.grid(True, alpha=0.3)

    # ── Draw correlation lines ────────────────────────────────────
    cid = min(cor_index, res_file.get_nbr_results() - 1)
    path = res_file.get_result_full_path(cid)
    cost = res_file.get_result_cost(cid)

    # Draw lines between adjacent well pairs
    for step, node in enumerate(path):
        for j in range(n_wells - 1):
            marker_left = node[j]
            marker_right = node[j + 1]
            if marker_left < len(depths[j]) and marker_right < len(depths[j + 1]):
                y_left = depths[j][marker_left]
                y_right = depths[j + 1][marker_right]
                # Use figure-level coordinates via ConnectionPatch
                con = matplotlib.patches.ConnectionPatch(
                    xyA=(1.0, y_left), coordsA=axes[j].get_yaxis_transform(),
                    xyB=(0.0, y_right), coordsB=axes[j + 1].get_yaxis_transform(),
                    color="gray", alpha=0.4, linewidth=0.6)
                fig.add_artist(con)

    fig.text(0.5, 0.01,
             f"Correlation #{cid}  |  Total cost: {cost:.4f}  |  "
             f"Nodes: {res_file.size}  |  Wells: {n_wells}",
             ha="center", fontsize=9, style="italic")

    plt.tight_layout(rect=[0, 0.03, 1, 0.95])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  [PLOT] {out_path}")


def plot_cost_comparison(results: dict, title: str, out_path: Path):
    """Bar chart comparing best-correlation cost across runs."""
    names = list(results.keys())
    costs = [results[n]["best_cost"] for n in names]
    n_results = [results[n]["n_results"] for n in names]

    fig, ax1 = plt.subplots(figsize=(max(6, len(names) * 1.5), 5))
    x = np.arange(len(names))
    bars = ax1.bar(x, costs, color=[WELL_COLORS[i % 10] for i in range(len(names))],
                   alpha=0.8, edgecolor="black", linewidth=0.5)
    ax1.set_ylabel("Best Correlation Cost", fontsize=10)
    ax1.set_title(title, fontsize=12, fontweight="bold")
    ax1.set_xticks(x)
    ax1.set_xticklabels(names, rotation=30, ha="right", fontsize=8)

    # Annotate bars
    for bar, c, nr in zip(bars, costs, n_results):
        ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                 f"{c:.4f}\n({nr} cors)",
                 ha="center", va="bottom", fontsize=7)

    ax1.grid(axis="y", alpha=0.3)
    plt.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  [PLOT] {out_path}")


# ═══════════════════════════════════════════════════════════════════════════
#  Run engine
# ═══════════════════════════════════════════════════════════════════════════

def run_dataset(ds_key: str, ds: dict, output_dir: Path):
    """Run all configurations in a dataset and generate plots."""
    print(f"\n{'='*70}")
    print(f"  {ds['title']}")
    print(f"{'='*70}")
    print(ds["description"])
    print()

    wells_path = str(ds["wells"])
    well_list = WellList(wells_path)
    print(f"  Wells: {well_list.nbr_wells()} — "
          f"{', '.join(w.name for w in well_list.wells)}")
    if well_list.wells:
        w0 = well_list.wells[0]
        print(f"  Data props:   {list(w0.data.keys())}")
        print(f"  Region props: {list(w0.region.keys())}")
    print()

    ds_output = output_dir / ds_key
    run_results = {}

    for run in ds["runs"]:
        run_name = run["name"]
        res_path = ds_output / f"{run_name}_result.txt"
        res_path.parent.mkdir(parents=True, exist_ok=True)

        # Merge common + run-specific options
        opts = dict(ds.get("common_opts", {}))
        opts.update(run["opts"])
        opts["out_file"] = str(res_path)
        opts["debug_cor_info"] = 1

        print(f"  ── Run: {run_name}")
        active_opts = {k: v for k, v in opts.items()
                       if v not in (None, "", 0.0) or k in (
                           "const_gap_cost", "var_weight", "var_weight2",
                           "debug_cor_info")}
        for k, v in sorted(active_opts.items()):
            if k != "out_file":
                print(f"     {k} = {v}")

        # Run correlation — reset ALL region/data options to avoid global leakage
        project = ProjectExt()
        # Explicitly clear all region/data options that may persist from prior runs
        _reset_opts = {
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
        project.set_options_ext(**_reset_opts)
        project.set_options_ext(**opts)
        project.run(wells_path)

        # Read results
        if res_path.exists():
            res_file = ResFile(str(res_path), build_list=True, reorder=True)
            n_results = res_file.get_nbr_results()
            best_cost = res_file.get_result_cost(0) if n_results > 0 else float("inf")
            print(f"     → {n_results} correlations, best cost = {best_cost:.6f}")

            run_results[run_name] = {
                "best_cost": best_cost,
                "n_results": n_results,
                "res_file": res_file,
            }

            # Detect best depth and data name
            depth_name = None
            plot_data = None
            for dname in ("Depth", "DEPTH", "MD", "depth"):
                if well_list.wells_data_exists(dname):
                    depth_name = dname
                    break
            for dname in well_list.wells[0].data:
                if dname.upper() not in ("DEPTH", "MD", "TVD", "TVDSS"):
                    plot_data = dname
                    break

            # Plot best correlation
            plot_correlation(
                well_list, res_file,
                f"{ds['title']}\n{run_name}  (best correlation)",
                ds_output / f"{run_name}_correlation.png",
                cor_index=0, data_name=plot_data, depth_name=depth_name
            )
        else:
            print(f"     [WARN] No result file produced")

    # Summary comparison plot
    if len(run_results) > 1:
        plot_cost_comparison(
            run_results, f"{ds['title']} — Cost Comparison",
            ds_output / "cost_comparison.png"
        )

    return run_results


# ═══════════════════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="WeCo Auto-Run: execute all examples with plots")
    parser.add_argument("--dataset", "-d", type=str, default=None,
                        help="Run only a specific dataset (number or key)")
    parser.add_argument("--list", "-l", action="store_true",
                        help="List available datasets")
    parser.add_argument("--output", "-o", type=str, default=str(OUTPUT_DIR),
                        help="Output directory for results and plots")
    args = parser.parse_args()

    if args.list:
        print("Available datasets:")
        for key, ds in DATASETS.items():
            print(f"  {key}: {ds['title']}")
        return

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.dataset:
        # Match by key or number prefix
        matched = {k: v for k, v in DATASETS.items()
                   if args.dataset in k or k.startswith(args.dataset)}
        if not matched:
            print(f"No dataset matching '{args.dataset}'. Use --list.")
            sys.exit(1)
        targets = matched
    else:
        targets = DATASETS

    print(f"WeCo Auto-Run Examples")
    print(f"Output directory: {output_dir}")

    all_results = {}
    for key, ds in targets.items():
        all_results[key] = run_dataset(key, ds, output_dir)

    # Final summary
    print(f"\n{'='*70}")
    print("  SUMMARY")
    print(f"{'='*70}")
    for ds_key, runs in all_results.items():
        print(f"\n  {DATASETS[ds_key]['title']}:")
        for rname, rdata in runs.items():
            print(f"    {rname:30s}  cost={rdata['best_cost']:.6f}  "
                  f"({rdata['n_results']} correlations)")

    print(f"\nAll plots saved to: {output_dir}/")


if __name__ == "__main__":
    main()
