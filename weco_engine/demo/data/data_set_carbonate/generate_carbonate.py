#!/usr/bin/env python3
"""
Generate a synthetic Carbonate Platform well dataset for WeCo (§D6).
=====================================================================

Geological setting: Tropical carbonate platform (Jurassic/Cretaceous
or Permian style).  Modelled on the Arabian Plate / Bahamas / Permian
Basin reef complexes.

Wells: 20 boreholes through a prograding/aggrading carbonate platform.
The platform shows metre-scale (parasequence) and large-scale (3rd order
sequence) cyclicity.

Facies (proximal → distal):

  1. Supratidal — anhydrite/sabkha (GR high, DEN high, SON low)
  2. Intertidal — microbial laminite / fenestral mudstone (GR med)
  3. Lagoon — wackestone/packstone (GR low-med, DEN 2.5-2.65)
  4. Shoal — oolitic/bioclastic grainstone (GR very low, DEN 2.6, high poro)
  5. Fore-reef — rudstone/breccia (GR low, DEN variable, SON variable)
  6. Slope — argillaceous mudstone (GR high, DEN 2.55)
  7. Basin — pelagic lime-mudstone/marl (GR med-high, DEN 2.4)

Logs:
  GR   — Natural gamma (API): grainstone=10, mudstone=30, marl=60, shale=100
  DEN  — Bulk density (g/cc): grainstone=2.3-2.5 (porous), mud=2.65, anhy=2.95
  SON  — Sonic (µs/ft): grainstone=55-70, mudstone=50, anhydrite=50
  NEU  — Neutron porosity (%): grainstone=15-25, mudstone=5, anhydrite=0
  RT   — Resistivity (Ohm-m): tight carbonates 200+, porous 20-50
  PEF  — Photoelectric factor: limestone=5.1, dolomite=3.1, anhydrite=5.1

Reference:
  - Schlager (2005) Carbonate Sedimentology and Sequence Stratigraphy
  - Tucker & Wright (1990) Carbonate Sedimentology
  - Lucia (1999) Carbonate Reservoir Characterization
  - Read (1985) Carbonate platform facies models
"""

import math
import os
import numpy as np

# ───────────────────────────────────────────────────────────────────
# Facies definitions (id, name, log_responses)
# ───────────────────────────────────────────────────────────────────

FACIES = {
    1: {"name": "supratidal",   "GR": 55, "DEN": 2.90, "SON": 50, "NEU": 1, "RT": 500, "PEF": 5.1},
    2: {"name": "intertidal",   "GR": 35, "DEN": 2.68, "SON": 55, "NEU": 5, "RT": 200, "PEF": 5.1},
    3: {"name": "lagoon",       "GR": 25, "DEN": 2.58, "SON": 60, "NEU": 12, "RT": 80, "PEF": 5.1},
    4: {"name": "shoal",        "GR": 10, "DEN": 2.40, "SON": 65, "NEU": 20, "RT": 30, "PEF": 5.1},
    5: {"name": "fore_reef",    "GR": 15, "DEN": 2.50, "SON": 58, "NEU": 15, "RT": 50, "PEF": 4.5},
    6: {"name": "slope",        "GR": 50, "DEN": 2.55, "SON": 70, "NEU": 10, "RT": 40, "PEF": 4.8},
    7: {"name": "basin",        "GR": 70, "DEN": 2.45, "SON": 80, "NEU": 8, "RT": 20, "PEF": 4.0},
}


def _shallowing_up_cycle(rng, n_samples, proximal_facies=1, distal_facies=6):
    """Generate a single shallowing-upward parasequence."""
    facies_ids = list(range(distal_facies, proximal_facies - 1, -1))
    n_facies = len(facies_ids)
    samples_per = max(1, n_samples // n_facies)
    cycle = []
    for i, fid in enumerate(facies_ids):
        n = samples_per if i < n_facies - 1 else n_samples - len(cycle)
        cycle.extend([fid] * max(n, 1))
    return cycle[:n_samples]


def _make_logs(facies_column, rng, noise_level=0.05):
    """Convert a facies column to synthetic log curves."""
    n = len(facies_column)
    logs = {k: np.zeros(n) for k in ("GR", "DEN", "SON", "NEU", "RT", "PEF")}

    for i, fid in enumerate(facies_column):
        props = FACIES.get(fid, FACIES[7])
        for key in logs:
            base = props[key]
            noise = rng.normal(0, base * noise_level)
            logs[key][i] = base + noise

    # Smooth slightly (simulates tool resolution)
    for key in logs:
        kernel = np.array([0.15, 0.7, 0.15])
        logs[key] = np.convolve(logs[key], kernel, mode="same")

    return logs


def generate_carbonate(
    n_wells=20,
    n_cycles=8,
    samples_per_cycle=15,
    seed=42,
    output_dir=None,
):
    """Generate a synthetic carbonate platform dataset.

    Parameters
    ----------
    n_wells : int
        Number of wells.
    n_cycles : int
        Number of parasequence cycles (metre-scale).
    samples_per_cycle : int
        Samples per cycle.
    seed : int
        Random seed.
    output_dir : str or None
        If given, write wells.txt to this directory.

    Returns
    -------
    dict
        Keys: 'wells' (list of dicts), 'truth' (list of horizon indices).
    """
    rng = np.random.RandomState(seed)
    n_samples = n_cycles * samples_per_cycle

    wells = []
    truth_horizons = list(range(0, n_samples, samples_per_cycle))

    for w in range(n_wells):
        # Proximal-to-distal gradient across wells
        distality = w / max(n_wells - 1, 1)  # 0 = proximal, 1 = distal
        prox_facies = max(1, int(1 + distality * 3))
        dist_facies = min(7, int(4 + distality * 3))

        facies_col = []
        for c in range(n_cycles):
            # Vary cycle thickness ±30%
            n_samp = max(5, int(samples_per_cycle * (0.7 + 0.6 * rng.random())))
            cycle = _shallowing_up_cycle(rng, n_samp, prox_facies, dist_facies)
            facies_col.extend(cycle)

        # Truncate/pad to n_samples
        if len(facies_col) > n_samples:
            facies_col = facies_col[:n_samples]
        while len(facies_col) < n_samples:
            facies_col.append(facies_col[-1])

        logs = _make_logs(facies_col, rng)
        depth = np.arange(n_samples, dtype=float) * 0.5  # 0.5m sample interval

        well_data = {
            "well_id": w,
            "name": f"CARB-{w:02d}",
            "x": float(w * 500),
            "y": 0.0,
            "depth": depth.tolist(),
            "facies": facies_col,
        }
        well_data.update({k: v.tolist() for k, v in logs.items()})
        wells.append(well_data)

    result = {"wells": wells, "truth": truth_horizons, "n_samples": n_samples}

    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        _write_wells_file(wells, os.path.join(output_dir, "wells.txt"))

    return result


def _write_wells_file(wells, filepath):
    """Write wells in WeCo text format."""
    with open(filepath, "w") as f:
        f.write(f"{len(wells)}\n")
        for w in wells:
            n = len(w["depth"])
            f.write(f'{w["name"]} {w["x"]:.1f} {w["y"]:.1f} {n}\n')
            log_names = [k for k in w if k not in ("well_id", "name", "x", "y", "facies")]
            f.write(" ".join(log_names) + "\n")
            for i in range(n):
                vals = " ".join(f"{w[k][i]:.4f}" for k in log_names)
                f.write(vals + "\n")


if __name__ == "__main__":
    out = os.path.dirname(os.path.abspath(__file__))
    result = generate_carbonate(output_dir=out, seed=42)
    print(f"Generated {len(result['wells'])} carbonate wells, "
          f"{result['n_samples']} samples, {len(result['truth'])} horizons")
