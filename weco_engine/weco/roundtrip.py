"""
weco.roundtrip — Round-trip validation framework
=================================================

Build synthetic well data with known truth, run the WeCo engine,
and measure how well the correlation recovers the ground truth.

Generators produce a ``TruthModel`` containing wells + the known
correlation.  The ``roundtrip_test()`` function runs the engine and
computes metrics (truth rank, marker MAE, recall@k).

Usage::

    from weco.roundtrip import generate_parallel, roundtrip_test

    model = generate_parallel(n_wells=5, n_markers=30, seed=42)
    result = roundtrip_test(model)
    print(result)   # {'truth_rank': 0, 'marker_mae': 0.0, ...}
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from .data import WellList, Well


# ---------------------------------------------------------------------------
# Truth model container
# ---------------------------------------------------------------------------

@dataclass
class TruthModel:
    """Synthetic well data with known ground-truth correlation.

    Attributes
    ----------
    well_list : WellList
        The synthetic wells.
    truth : list[tuple[int, ...]]
        Ground-truth correlation path.  Each element is a tuple of
        marker indices (one per well) representing one horizon.
    name : str
        Model name for reporting.
    options : dict
        Engine option overrides for this model.
    """
    well_list: WellList
    truth: list[tuple[int, ...]]
    name: str = ""
    options: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Generator A: Parallel layers (trivial baseline)
# ---------------------------------------------------------------------------

def generate_parallel(
    n_wells: int = 5,
    n_markers: int = 30,
    spacing: float = 100.0,
    wave_length: float = 10.0,
    noise: float = 0.0,
    seed: int = 42,
) -> TruthModel:
    """Flat, uniform-thickness parallel layers.

    All wells see the same signal (optionally + noise).
    Truth = perfect 1-to-1 diagonal correlation.
    """
    rng = random.Random(seed)
    np_rng = np.random.default_rng(seed)

    wl = WellList()
    depth = [float(i) for i in range(n_markers)]
    base_signal = [math.sin(2 * math.pi * i / wave_length) for i in range(n_markers)]

    for j in range(n_wells):
        w = wl.create_well(f"W{j}", x=0.0, y=j * spacing, size=n_markers)
        w.add_data("depth", depth)
        signal = [v + np_rng.normal(0, noise) for v in base_signal] if noise > 0 else list(base_signal)
        w.add_data("GR", signal)

    # Truth: diagonal — sample i in every well
    truth = [tuple(i for _ in range(n_wells)) for i in range(n_markers)]

    return TruthModel(
        well_list=wl,
        truth=truth,
        name=f"parallel_{n_wells}w_{n_markers}m_noise{noise:.2f}",
        options={"var-data": "GR", "var-weight": "1.0"},
    )


# ---------------------------------------------------------------------------
# Generator B: Clinoform wedge
# ---------------------------------------------------------------------------

def generate_clinoform(
    n_wells: int = 5,
    n_markers: int = 40,
    spacing: float = 200.0,
    max_shift: int = 8,
    wave_length: float = 12.0,
    noise: float = 0.0,
    seed: int = 42,
) -> TruthModel:
    """Thickening/thinning wedge with known vertical shifts.

    Wells are spaced along dip.  Each well's stratigraphy is shifted
    vertically by a linearly increasing offset, simulating a
    clinoform geometry where beds thicken downdip.

    The truth correlation maps each marker to its shifted position.
    """
    rng = random.Random(seed)
    np_rng = np.random.default_rng(seed)

    # Build a long reference signal and slice per well
    pad = max_shift * 2
    full_len = n_markers + pad
    full_signal = [math.sin(2 * math.pi * i / wave_length) for i in range(full_len)]

    shifts = [int(round(max_shift * j / max(n_wells - 1, 1))) for j in range(n_wells)]

    wl = WellList()
    truth_map = {}  # {well_idx: {ref_sample: local_sample}}

    for j, shift in enumerate(shifts):
        start = pad // 2 + shift
        end = start + n_markers
        segment = full_signal[start:end]
        if noise > 0:
            segment = [v + np_rng.normal(0, noise) for v in segment]
        depth = [float(i) for i in range(len(segment))]

        w = wl.create_well(f"W{j}", x=0.0, y=j * spacing, size=len(segment))
        w.add_data("depth", depth)
        w.add_data("GR", segment)

        # Map: reference index → local index
        truth_map[j] = {}
        for ref_idx in range(n_markers):
            local = ref_idx + pad // 2 - start + pad // 2
            # Simpler: local = ref_idx - shift + shifts[0]
            local = ref_idx + shifts[0] - shift
            if 0 <= local < len(segment):
                truth_map[j][ref_idx] = local

    # Build truth path: for each reference marker, get local index per well
    truth = []
    for ref_idx in range(n_markers):
        node = []
        valid = True
        for j in range(n_wells):
            local = truth_map[j].get(ref_idx)
            if local is None:
                valid = False
                break
            node.append(local)
        if valid:
            truth.append(tuple(node))

    return TruthModel(
        well_list=wl,
        truth=truth,
        name=f"clinoform_{n_wells}w_{n_markers}m_shift{max_shift}_noise{noise:.2f}",
        options={"var-data": "GR", "var-weight": "1.0"},
    )


# ---------------------------------------------------------------------------
# Noise injection utility
# ---------------------------------------------------------------------------

def inject_noise(model: TruthModel, noise_level: float, seed: int = 0) -> TruthModel:
    """Return a copy of *model* with Gaussian noise added to all data channels.

    The truth path is unchanged — this tests how robust the engine is
    to noisy input.
    """
    np_rng = np.random.default_rng(seed)

    wl = WellList()
    for w in model.well_list.wells:
        new_w = wl.create_well(w.name, x=getattr(w, 'x', 0.0),
                               y=getattr(w, 'y', 0.0), size=w.size)
        for dname, values in w.data.items():
            if dname.lower() == "depth":
                new_w.add_data(dname, list(values))
            else:
                noisy = [v + np_rng.normal(0, noise_level) for v in values]
                new_w.add_data(dname, noisy)
        for rname in (w.get_region_names() if hasattr(w, 'get_region_names') else []):
            new_w.add_region(rname, w.region[rname])

    return TruthModel(
        well_list=wl,
        truth=model.truth,
        name=f"{model.name}+noise{noise_level:.2f}",
        options=dict(model.options),
    )


# ---------------------------------------------------------------------------
# Round-trip test runner
# ---------------------------------------------------------------------------

def roundtrip_test(
    model: TruthModel,
    *,
    k: int = 10,
    extra_options: Optional[dict] = None,
) -> dict:
    """Run the engine on a TruthModel and compute validation metrics.

    Parameters
    ----------
    model : TruthModel
        Synthetic data with ground-truth correlation.
    k : int
        Number of n-best paths to examine for recall/rank metrics.
    extra_options : dict, optional
        Additional engine options (override model defaults).

    Returns
    -------
    dict
        ``truth_rank``: 0-based rank of truth among n-best (or -1 if not found).
        ``top1_match``: bool — does the best path match truth exactly?
        ``marker_mae``: mean absolute marker offset between best path and truth.
        ``recall_at_k``: fraction of truth horizons present in top-k results.
        ``best_cost``: cost of the best correlation.
        ``model_name``: name of the model.
    """
    from .ext import ProjectExt

    engine = ProjectExt()
    opts = {
        "cost-function": "composite",
        "order": "pyramidal",
        "nbr-cor": str(max(k * 5, 50)),
        "out-nbr-cor": str(max(k, 10)),
        "max-cor": str(max(len(model.truth) * 2, 100)),
    }
    opts.update(model.options)
    if extra_options:
        opts.update(extra_options)

    for key, val in opts.items():
        engine.set_option_ext(key, str(val))

    success = engine.run(model.well_list)
    if not success:
        return {
            "truth_rank": -1,
            "top1_match": False,
            "marker_mae": float("inf"),
            "recall_at_k": 0.0,
            "best_cost": float("inf"),
            "model_name": model.name,
            "error": "engine run failed",
        }

    res = engine.get_res_file()
    n_results = min(k, res.get_nbr_results())
    n_wells = res.nbr_well()

    # Extract n-best paths
    paths = []
    for i in range(n_results):
        paths.append(res.get_result_full_path(i))

    # Best path
    best_path = paths[0] if paths else []
    best_cost = float(res.get_result_cost(0)) if paths else float("inf")

    # Convert truth to set of tuples for comparison
    truth_set = set(model.truth)

    # Top-1 exact match
    best_set = set(tuple(node) for node in best_path)
    top1_match = truth_set == best_set

    # Marker MAE: for each truth horizon, find the closest match in best path
    mae_sum = 0.0
    mae_count = 0
    for t_node in model.truth:
        best_dist = float("inf")
        for p_node in best_path:
            dist = sum(abs(t - p) for t, p in zip(t_node, p_node)) / n_wells
            best_dist = min(best_dist, dist)
        mae_sum += best_dist
        mae_count += 1
    marker_mae = mae_sum / max(mae_count, 1)

    # Truth rank: check which n-best path best matches the truth
    truth_rank = -1
    best_match_score = -1
    for rank, path in enumerate(paths):
        path_set = set(tuple(node) for node in path)
        overlap = len(truth_set & path_set)
        if overlap > best_match_score:
            best_match_score = overlap
            truth_rank = rank

    # Recall@k: fraction of truth horizons found in any of the top-k paths
    all_nodes = set()
    for path in paths:
        for node in path:
            all_nodes.add(tuple(node))
    recall_hits = len(truth_set & all_nodes)
    recall_at_k = recall_hits / max(len(truth_set), 1)

    return {
        "truth_rank": truth_rank,
        "top1_match": top1_match,
        "marker_mae": round(marker_mae, 4),
        "recall_at_k": round(recall_at_k, 4),
        "best_cost": round(best_cost, 6),
        "model_name": model.name,
    }


# ---------------------------------------------------------------------------
# Dataset generator integration (Quaternary, Coal, Shallow Marine)
# ---------------------------------------------------------------------------

def _load_generator(gen_file: str):
    """Dynamically import a generator module from data/."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("_gen", gen_file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def generate_from_dataset(
    dataset: str,
    *,
    seed: int = 42,
    n_wells: int = 0,
    output_dir: Optional[str] = None,
) -> tuple:
    """Run a dataset generator and return (wells_path, options_path).

    Parameters
    ----------
    dataset : str
        One of ``"quaternary"``, ``"coal"``, ``"shallow_marine"``.
    seed : int
        Random seed for reproducibility.
    n_wells : int
        Number of wells (0 = use generator default).
    output_dir : str or None
        Directory for output files. If None, uses a temporary directory.

    Returns
    -------
    (wells_path, options_path) : tuple[str, str]
        Absolute paths to the generated welllist and options file.
    """
    import os
    import tempfile
    import inspect

    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    generators = {
        "quaternary": (
            os.path.join(root, "data", "data_set_quaternary",
                         "generate_quaternary.py"),
            "options_basic.txt",
        ),
        "coal": (
            os.path.join(root, "data", "data_set_coal",
                         "generate_coal.py"),
            "options_basic.txt",
        ),
        "shallow_marine": (
            os.path.join(root, "data", "data_set_shallow_marine",
                         "generate_shallow_marine.py"),
            "options.txt",
        ),
    }

    if dataset not in generators:
        raise ValueError(
            f"Unknown dataset '{dataset}'. Choose from: "
            + ", ".join(generators))

    gen_file, opts_name = generators[dataset]
    mod = _load_generator(gen_file)

    if output_dir is None:
        output_dir = tempfile.mkdtemp(prefix=f"weco_rt_{dataset}_")

    kwargs = {"seed": seed, "output_dir": output_dir}
    if n_wells > 0:
        params = inspect.signature(mod.main).parameters
        if "n_grid" in params:
            kwargs["n_grid"] = max(2, int(n_wells ** 0.5))
        elif "n_wells" in params:
            kwargs["n_wells"] = n_wells

    mod.main(**kwargs)

    wells_path = os.path.join(output_dir, "wells.txt")
    opts_path = os.path.join(output_dir, opts_name)
    if not os.path.exists(wells_path):
        raise FileNotFoundError(f"Generator did not produce {wells_path}")
    if not os.path.exists(opts_path):
        raise FileNotFoundError(f"Generator did not produce {opts_path}")

    return wells_path, opts_path


# ---------------------------------------------------------------------------
# Generator C: Prograding delta
# ---------------------------------------------------------------------------

def generate_prograding_delta(
    n_wells: int = 8,
    n_markers: int = 60,
    n_parasequences: int = 5,
    spacing: float = 300.0,
    noise: float = 0.0,
    seed: int = 42,
) -> TruthModel:
    """Prograding delta with shingled parasequences.

    Wells are spaced along dip.  Each parasequence progrades
    (shifts basinward), creating lateral facies changes.
    GR and DEN logs are generated from a facies model.

    Extends data_set_eage2024 concept.
    """
    rng = random.Random(seed)
    np_rng = np.random.default_rng(seed)

    wl = WellList()
    n_per_para = n_markers // n_parasequences

    # Facies model: each parasequence progrades further
    # Facies: 0=shale, 1=silt, 2=fine_sand, 3=medium_sand
    facies_gr = {0: 120.0, 1: 80.0, 2: 40.0, 3: 20.0}
    facies_den = {0: 2.5, 1: 2.4, 2: 2.3, 3: 2.2}

    truth_horizons = []

    for j in range(n_wells):
        x_pos = j * spacing
        gr_values = []
        den_values = []
        facies_values = []
        depth = []

        marker = 0
        for ps in range(n_parasequences):
            # Prograde shift: distal wells see shale-dominated,
            # proximal wells see sand-dominated
            prox_frac = 1.0 - (j / max(n_wells - 1, 1))
            ps_shift = ps / max(n_parasequences - 1, 1)

            for k in range(n_per_para):
                depth.append(float(marker))
                pos_in_para = k / max(n_per_para - 1, 1)
                # Coarsening upward within parasequence
                facies_prob = pos_in_para * prox_frac * (0.5 + 0.5 * ps_shift)
                if facies_prob > 0.75:
                    f = 3
                elif facies_prob > 0.5:
                    f = 2
                elif facies_prob > 0.25:
                    f = 1
                else:
                    f = 0

                gr_val = facies_gr[f] + (np_rng.normal(0, noise) if noise > 0 else 0)
                den_val = facies_den[f] + (np_rng.normal(0, noise * 0.01) if noise > 0 else 0)

                gr_values.append(gr_val)
                den_values.append(den_val)
                facies_values.append(f)
                marker += 1

        n_actual = len(depth)
        w = wl.create_well(f"W{j}", x=x_pos, y=0.0, size=n_actual)
        w.add_data("depth", depth)
        w.add_data("GR", gr_values)
        w.add_data("DEN", den_values)

        # Add facies as region
        intervals = []
        if facies_values:
            cur_f = facies_values[0]
            cur_start = 0
            cur_len = 1
            for m in range(1, len(facies_values)):
                if facies_values[m] == cur_f:
                    cur_len += 1
                else:
                    intervals.append((cur_f, cur_start, cur_len))
                    cur_f = facies_values[m]
                    cur_start = m
                    cur_len = 1
            intervals.append((cur_f, cur_start, cur_len))
        w.add_region("facies", intervals)

    # Truth: diagonal (same stratigraphy in all wells)
    n_actual = min(w.size for w in wl.wells)
    truth = [tuple(i for _ in range(n_wells)) for i in range(n_actual)]

    return TruthModel(
        well_list=wl,
        truth=truth,
        name=f"prograding_delta_{n_wells}w_{n_markers}m_noise{noise:.2f}",
        options={"var-data": "GR", "var-weight": "1.0"},
    )


# ---------------------------------------------------------------------------
# Generator F: Shallow marine / bay fill (Hugin Fm analogue)
# ---------------------------------------------------------------------------

def generate_shallow_marine(
    n_wells: int = 8,
    n_markers: int = 80,
    spacing: float = 500.0,
    noise: float = 0.0,
    seed: int = 42,
) -> TruthModel:
    """Shallow marine bay fill analogue of Hugin Formation.

    8 facies: offshore shale, lower shoreface, upper shoreface,
    foreshore, bay fill, lagoonal, tidal channel, floodplain.
    Clinoform geometry with lateral facies changes.

    Reference: Baville (2022) Fig 6.2 — Hugin Formation.
    """
    rng = random.Random(seed)
    np_rng = np.random.default_rng(seed)

    # Facies definitions
    FACIES = {
        0: {"name": "offshore_shale", "GR": 130.0, "DEN": 2.55, "NPHI": 0.35},
        1: {"name": "lower_shoreface", "GR": 90.0, "DEN": 2.45, "NPHI": 0.28},
        2: {"name": "upper_shoreface", "GR": 50.0, "DEN": 2.35, "NPHI": 0.22},
        3: {"name": "foreshore", "GR": 25.0, "DEN": 2.25, "NPHI": 0.18},
        4: {"name": "bay_fill", "GR": 100.0, "DEN": 2.50, "NPHI": 0.30},
        5: {"name": "lagoonal", "GR": 110.0, "DEN": 2.48, "NPHI": 0.32},
        6: {"name": "tidal_channel", "GR": 40.0, "DEN": 2.30, "NPHI": 0.20},
        7: {"name": "floodplain", "GR": 115.0, "DEN": 2.52, "NPHI": 0.33},
    }

    wl = WellList()

    for j in range(n_wells):
        distality = j / max(n_wells - 1, 1)  # 0=proximal, 1=distal
        x_pos = j * spacing

        gr_values = []
        den_values = []
        nphi_values = []
        depth = []
        facies_values = []

        for m in range(n_markers):
            depth.append(float(m))
            cycle_pos = (m % 20) / 20.0  # Within-parasequence position

            # Determine facies based on distality and cycle position
            if distality > 0.7:
                # Distal: mostly offshore shale with lower shoreface
                if cycle_pos > 0.8:
                    f = 1  # lower shoreface
                else:
                    f = 0  # offshore shale
            elif distality > 0.4:
                # Mid: shoreface-dominated coarsening-upward
                if cycle_pos > 0.8:
                    f = 2  # upper shoreface
                elif cycle_pos > 0.5:
                    f = 1  # lower shoreface
                else:
                    f = 0  # offshore shale
            else:
                # Proximal: bay fill and tidal
                if cycle_pos > 0.8:
                    f = 3  # foreshore
                elif cycle_pos > 0.6:
                    f = 6  # tidal channel
                elif cycle_pos > 0.4:
                    f = 4  # bay fill
                elif cycle_pos > 0.2:
                    f = 5  # lagoonal
                else:
                    f = 7  # floodplain

            facies_values.append(f)
            props = FACIES[f]
            gr_values.append(props["GR"] + (np_rng.normal(0, noise * 5) if noise > 0 else 0))
            den_values.append(props["DEN"] + (np_rng.normal(0, noise * 0.02) if noise > 0 else 0))
            nphi_values.append(props["NPHI"] + (np_rng.normal(0, noise * 0.02) if noise > 0 else 0))

        w = wl.create_well(f"W{j}", x=x_pos, y=0.0, size=n_markers)
        w.add_data("depth", depth)
        w.add_data("GR", gr_values)
        w.add_data("DEN", den_values)
        w.add_data("NPHI", nphi_values)

        # Facies region
        intervals = []
        if facies_values:
            cur_f = facies_values[0]
            cur_start = 0
            cur_len = 1
            for mi in range(1, len(facies_values)):
                if facies_values[mi] == cur_f:
                    cur_len += 1
                else:
                    intervals.append((cur_f, cur_start, cur_len))
                    cur_f = facies_values[mi]
                    cur_start = mi
                    cur_len = 1
            intervals.append((cur_f, cur_start, cur_len))
        w.add_region("facies", intervals)

    # Truth: diagonal
    truth = [tuple(i for _ in range(n_wells)) for i in range(n_markers)]

    return TruthModel(
        well_list=wl,
        truth=truth,
        name=f"shallow_marine_{n_wells}w_{n_markers}m_noise{noise:.2f}",
        options={"var-data": "GR", "var-weight": "1.0"},
    )


# ---------------------------------------------------------------------------
# Generator G: Fluvial channel system
# ---------------------------------------------------------------------------

def generate_fluvial(
    n_wells: int = 10,
    n_markers: int = 50,
    spacing: float = 200.0,
    channel_width_frac: float = 0.3,
    noise: float = 0.0,
    seed: int = 42,
) -> TruthModel:
    """Fluvial channel belt — laterally discontinuous sandbodies.

    Channels are randomly positioned and have limited lateral extent.
    This makes correlation inherently difficult: not all horizons
    can be correlated between all wells.

    Facies: 0=floodplain, 1=crevasse splay, 2=channel sand, 3=channel lag.
    """
    rng = random.Random(seed)
    np_rng = np.random.default_rng(seed)

    facies_gr = {0: 120.0, 1: 70.0, 2: 30.0, 3: 20.0}
    n_channels = n_markers // 10

    # Define channel positions (random y-centres)
    channels = []
    for c in range(n_channels):
        y_centre = rng.uniform(0, (n_wells - 1) * spacing)
        z_centre = rng.randint(5, n_markers - 5)
        width = channel_width_frac * (n_wells - 1) * spacing
        thickness = rng.randint(3, 8)
        channels.append((y_centre, z_centre, width, thickness))

    wl = WellList()
    for j in range(n_wells):
        y_pos = j * spacing
        gr_values = []
        depth = []

        for m in range(n_markers):
            depth.append(float(m))
            facies = 0  # default floodplain

            for y_c, z_c, w, t in channels:
                if abs(y_pos - y_c) < w / 2 and abs(m - z_c) < t / 2:
                    dist_from_centre = abs(y_pos - y_c) / (w / 2)
                    if dist_from_centre < 0.3:
                        facies = 3  # channel lag
                    elif dist_from_centre < 0.6:
                        facies = 2  # channel sand
                    else:
                        facies = 1  # crevasse splay
                    break

            gr_val = facies_gr[facies] + (np_rng.normal(0, noise * 5) if noise > 0 else 0)
            gr_values.append(gr_val)

        w = wl.create_well(f"W{j}", x=0.0, y=y_pos, size=n_markers)
        w.add_data("depth", depth)
        w.add_data("GR", gr_values)

    # Truth: diagonal (floodplain layers are continuous)
    truth = [tuple(i for _ in range(n_wells)) for i in range(n_markers)]

    return TruthModel(
        well_list=wl,
        truth=truth,
        name=f"fluvial_{n_wells}w_{n_markers}m_noise{noise:.2f}",
        options={"var-data": "GR", "var-weight": "1.0"},
    )


# ---------------------------------------------------------------------------
# Dataset round-trip integration (§13.7)
# ---------------------------------------------------------------------------

def roundtrip_from_dataset(
    dataset: str,
    *,
    seed: int = 42,
    n_wells: int = 0,
    k: int = 10,
) -> dict:
    """Run a round-trip test using an existing dataset generator.

    Generates data, runs the engine, and returns metrics.
    Unlike :func:`roundtrip_test`, this works with file-based generators
    that produce wells.txt + options.txt (no TruthModel).

    Returns a simplified result since ground truth is not available
    for file-based generators (reports cost and structure only).
    """
    from .ext import ProjectExt

    wells_path, opts_path = generate_from_dataset(dataset, seed=seed, n_wells=n_wells)

    proj = ProjectExt()
    proj.set_option_ext("read-options", opts_path)
    proj.set_option_ext("out-nbr-cor", str(max(k, 10)))

    wl = WellList(wells_path)
    success = proj.run(wl)

    if not success:
        return {
            "dataset": dataset,
            "success": False,
            "error": "engine run failed",
        }

    res = proj.get_res_file()
    n_results = res.get_nbr_results()
    best_cost = float(res.get_result_cost(0)) if n_results > 0 else float("inf")

    return {
        "dataset": dataset,
        "success": True,
        "n_wells": wl.nbr_wells(),
        "n_results": n_results,
        "best_cost": round(best_cost, 6),
        "wells_path": wells_path,
        "options_path": opts_path,
    }


def roundtrip_dataset_test(
    dataset: str,
    *,
    seed: int = 42,
    n_wells: int = 0,
    k: int = 5,
) -> dict:
    """Run a full roundtrip test on a generated dataset.

    Generates wells, runs the engine with the dataset's default options,
    and checks structural properties of the result.

    Returns
    -------
    dict with keys:
        ``dataset``, ``n_wells``, ``n_results``, ``best_cost``,
        ``worst_cost``, ``all_monotonic``, ``costs_sorted``.
    """
    import os
    import tempfile
    import shutil

    tmp = tempfile.mkdtemp(prefix=f"weco_rt_{dataset}_")
    try:
        wells_path, opts_path = generate_from_dataset(
            dataset, seed=seed, n_wells=n_wells, output_dir=tmp)

        from .ext import ProjectExt
        engine = ProjectExt()
        engine.option_load(os.path.abspath(opts_path))
        engine.set_option_ext("out-nbr-cor", str(max(k, 5)))
        success = engine.run(os.path.abspath(wells_path))

        if not success:
            return {
                "dataset": dataset, "n_wells": 0, "n_results": 0,
                "best_cost": float("inf"), "worst_cost": float("inf"),
                "all_monotonic": False, "costs_sorted": False,
                "error": "engine run failed",
            }

        res = engine.get_res_file()
        n_results = res.get_nbr_results()
        n_wells_actual = res.nbr_well()

        costs = [res.get_result_cost(i) for i in range(n_results)]
        costs_sorted = all(
            costs[i] <= costs[i + 1] + 1e-9
            for i in range(len(costs) - 1))

        all_mono = True
        for r_idx in range(min(k, n_results)):
            path = res.get_result_full_path(r_idx)
            for w in range(n_wells_actual):
                samples = [node[w] for node in path]
                for i in range(1, len(samples)):
                    if samples[i] < samples[i - 1]:
                        all_mono = False
                        break
                if not all_mono:
                    break
            if not all_mono:
                break

        return {
            "dataset": dataset,
            "n_wells": n_wells_actual,
            "n_results": n_results,
            "best_cost": round(costs[0], 4) if costs else float("inf"),
            "worst_cost": round(costs[-1], 4) if costs else float("inf"),
            "all_monotonic": all_mono,
            "costs_sorted": costs_sorted,
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
