#!/usr/bin/env python3
"""
Generate revised synthetic demo datasets with genuine correlation ambiguity.

Each dataset is designed so that multiple geologically plausible correlation
patterns exist - the DTW engine should find 30-60% stable lines across
the n-best solutions.

Geological basis:
  - Fluvial: Book Cliffs Neslen/Farrer Fms (Cole 2008) + incised valleys (Boyd 2006)
    Multi-story channel sands with similar fining-upward GR cycles, laterally
    discontinuous sandbodies, channels that pinch out between wells.

  - Shallow marine: Book Cliffs Blackhawk Fm (Arnot & Good) + Ainsworth 2017
    Repeating parasequences (coarsening-upward), similar flooding surfaces,
    lateral facies variation along depositional dip.

  - Coal: Neslen Fm type (Cole 2008) - repeating coal-shale-sand cycles where
    seams split and merge laterally; similar log signatures at multiple levels.

  - Quaternary: Glacial-interglacial cycles with similar conductivity patterns,
    unconformities that remove different amounts of section in each borehole.

  - Delta: Prograding clinoforms (Ainsworth 2017, Baville PhD) with lateral
    facies change, condensed offshore sections, and thickness variation.

Output: WeCo well files in demo/data/data_set_<name>/wells.txt
"""

import math
import os
import random
import sys

import numpy as np

# Path to write output
DEMO_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "demo", "data")


# ═══════════════════════════════════════════════════════════════════════════
# Utility: write WeCo well file
# ═══════════════════════════════════════════════════════════════════════════

def write_wells(filepath, wells):
    """
    Write wells in WeCo WellList format version 2.

    wells: list of dict with keys:
        name, x, y, z, h, size,
        data: dict of {name: [values...]},
        regions: dict of {name: [(id, start, length), ...]}
    """
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    n_wells = len(wells)

    with open(filepath, "w") as f:
        # Header
        f.write(f"WeCo WellList 2\n{n_wells}\n")

        for w in wells:
            size = w["size"]
            x, y, z, h = w.get("x", 0), w.get("y", 0), w.get("z", 0), w.get("h", float(size))
            n_data_cols = len(w["data"])
            regions = w.get("regions", {})

            f.write(f"{w['name']}\n")
            f.write(f"{size}\n")
            f.write(f"{x:.6f} {y:.6f} {z:.6f} {h:.6f}\n")
            f.write(f"{n_data_cols}\n")

            # Data columns
            for dname, values in w["data"].items():
                f.write(f"{dname} {size}\n")
                for v in values:
                    f.write(f"{v:.6f}\n")

            # Region columns (separate section in v2)
            f.write(f"{len(regions)}\n")
            for rname, intervals in regions.items():
                f.write(f"{rname} {len(intervals)}\n")
                for rid, start, length in intervals:
                    f.write(f"{rid} {start} {length}\n")

        f.write("END\n")


# ═══════════════════════════════════════════════════════════════════════════
# Signal generation helpers
# ═══════════════════════════════════════════════════════════════════════════

def fining_upward_cycle(length, base_gr=120, top_gr=30, noise=5.0, rng=None):
    """Generate a fining-upward (channel) GR cycle: high at base, low at top."""
    if rng is None:
        rng = np.random.default_rng()
    t = np.linspace(0, 1, length)
    # Concave-up decrease (fast initial fining, slow towards top)
    gr = base_gr - (base_gr - top_gr) * (1 - np.exp(-3 * t)) / (1 - np.exp(-3))
    return gr + rng.normal(0, noise, length)


def coarsening_upward_cycle(length, base_gr=100, top_gr=25, noise=5.0, rng=None):
    """Generate a coarsening-upward (prograding) GR cycle: high at base, low at top."""
    if rng is None:
        rng = np.random.default_rng()
    t = np.linspace(0, 1, length)
    # Convex-up (slow initial cleaning, rapid at top = prograding shoreface)
    gr = base_gr - (base_gr - top_gr) * t**1.8
    return gr + rng.normal(0, noise, length)


def shale_interval(length, mean_gr=110, noise=8.0, rng=None):
    """Generate a shale/mudstone interval with high GR."""
    if rng is None:
        rng = np.random.default_rng()
    return np.full(length, mean_gr) + rng.normal(0, noise, length)


def coal_spike(length=3, gr_value=10, noise=2.0, rng=None):
    """Generate a coal seam: very low GR, very high DEN anomaly."""
    if rng is None:
        rng = np.random.default_rng()
    gr = np.full(length, gr_value) + rng.normal(0, noise, length)
    return gr


def sand_interval(length, mean_gr=30, noise=5.0, rng=None):
    """Generate a clean sand interval with low GR."""
    if rng is None:
        rng = np.random.default_rng()
    return np.full(length, mean_gr) + rng.normal(0, noise, length)


# ═══════════════════════════════════════════════════════════════════════════
# FLUVIAL DATASET
# Based on: Cole 2008 (Neslen/Farrer Fms), Boyd 2006 (incised valleys)
#
# Ambiguity source: Multiple similar fining-upward channel sand cycles
# that pinch out laterally. A channel in Well A could correlate with
# either of two similar channels in Well B.
# ═══════════════════════════════════════════════════════════════════════════

def generate_fluvial(n_wells=5, seed=2024):
    """
    Fluvial system: stacked channel sands in a floodplain mudrock.

    Key to ambiguity: ALL channels have identical GR signatures (same
    base_gr=120, top_gr=30, same thickness range). Only noise differs.
    Channels are laterally discontinuous - Well A sees channels at
    positions 1,3,5 while Well B sees channels at 2,3,4 - but they all
    look the same on the log. The DTW can match channel 1 in Well A
    with either channel 2 or 3 in Well B.

    Based on: Cole 2008 (Neslen Fm), Boyd 2006 (incised valleys)
    """
    rng = np.random.default_rng(seed)
    wells = []

    # 8 channel events - ALL identical GR signature!
    n_channels = 8
    # Each channel has same signature but different lateral extent
    # Presence probability varies per channel to create correlation ambiguity
    presence_pattern = [
        [1, 1, 0, 1, 0],  # ch0: wells 0,1,3
        [0, 1, 1, 0, 1],  # ch1: wells 1,2,4
        [1, 0, 1, 1, 0],  # ch2: wells 0,2,3
        [1, 1, 1, 0, 1],  # ch3: wells 0,1,2,4
        [0, 1, 0, 1, 1],  # ch4: wells 1,3,4
        [1, 0, 1, 1, 0],  # ch5: wells 0,2,3
        [0, 1, 1, 0, 1],  # ch6: wells 1,2,4
        [1, 1, 0, 1, 1],  # ch7: wells 0,1,3,4
    ]

    # Uniform overbank
    overbank_thick = 4  # short, uniform - no distinguishing features

    for wi in range(n_wells):
        gr_signal = []
        facies_regions = []
        pos = 0

        for ci in range(n_channels):
            present = presence_pattern[ci][wi]

            if present:
                # ALL channels: same GR signature (120→30), same thickness (8 samples)
                thick = 8
                gr_signal.extend(fining_upward_cycle(thick, 120, 30, noise=8, rng=rng))
                facies_regions.append((1, pos, thick))
                pos += thick
            # else: channel absent, no record (no condensed section either)

            # Short uniform overbank
            ob = overbank_thick
            gr_signal.extend(shale_interval(ob, mean_gr=105, noise=8, rng=rng))
            facies_regions.append((0, pos, ob))
            pos += ob

        size = len(gr_signal)
        depth = [float(i) * 0.5 for i in range(size)]

        wells.append({
            "name": f"FW_{wi+1:02d}",
            "x": float(wi * 500),
            "y": 0.0,
            "z": 0.0,
            "h": depth[-1],
            "size": size,
            "data": {"DEPTH": depth, "GR": list(np.clip(gr_signal, 0, 180))},
            "regions": {"FACIES": facies_regions},
        })

    return wells


# ═══════════════════════════════════════════════════════════════════════════
# SHALLOW MARINE DATASET
# Based on: Book Cliffs Blackhawk Fm, Ainsworth 2017
#
# Ambiguity source: Repeating coarsening-upward parasequences with
# similar flooding surfaces. In distal wells, parasequences thin and
# become indistinguishable. Number of parasequences varies per well.
# ═══════════════════════════════════════════════════════════════════════════

def generate_shallow_marine(n_wells=6, seed=2025):
    """
    Shallow marine: stacked prograding parasequences.

    Key to ambiguity: 7 parasequences with IDENTICAL CU signature
    (same base/top GR, same thickness). Wells along depositional dip
    see different numbers of parasequences (some condense/disappear
    basinward). When Well A has 5 PS and Well B has 4 PS, which PS
    in A correlates with which in B?

    Based on: Book Cliffs Blackhawk Fm, Ainsworth 2017
    """
    rng = np.random.default_rng(seed)
    wells = []

    n_ps = 7  # parasequences

    # Which PS are present per well (1=full, 0=condensed to thin shale)
    # Wells progress from proximal (all present) to distal (some missing)
    presence = [
        [1, 1, 1, 1, 1, 1, 1],  # W0: proximal, all present
        [1, 1, 1, 1, 1, 1, 0],  # W1: miss top
        [1, 1, 0, 1, 1, 0, 1],  # W2: miss 2 and 5
        [1, 0, 1, 1, 0, 1, 1],  # W3: miss 1 and 4
        [0, 1, 1, 0, 1, 1, 0],  # W4: miss 0,3,6
        [1, 0, 1, 0, 1, 0, 1],  # W5: distal, only odds
    ]

    for wi in range(n_wells):
        gr_signal = []
        facies_regions = []
        pos = 0

        for psi in range(n_ps):
            if presence[wi][psi]:
                # Flooding surface shale (uniform)
                fs_thick = 3
                gr_signal.extend(shale_interval(fs_thick, mean_gr=115, noise=6, rng=rng))
                facies_regions.append((2, pos, fs_thick))
                pos += fs_thick

                # Coarsening-upward parasequence - ALL IDENTICAL signature
                cu_thick = 7
                gr_signal.extend(coarsening_upward_cycle(cu_thick, 110, 28, noise=7, rng=rng))
                facies_regions.append((1, pos, cu_thick))
                pos += cu_thick
            else:
                # Condensed: thin shale only (no sand)
                cond_thick = 3
                gr_signal.extend(shale_interval(cond_thick, mean_gr=108, noise=8, rng=rng))
                facies_regions.append((3, pos, cond_thick))
                pos += cond_thick

        size = len(gr_signal)
        depth = [float(i) * 0.5 for i in range(size)]

        wells.append({
            "name": f"SM_{wi+1:02d}",
            "x": float(wi * 800),
            "y": 0.0,
            "z": 0.0,
            "h": depth[-1] if depth else 0,
            "size": size,
            "data": {
                "DEPTH": depth,
                "GR": list(np.clip(gr_signal, 0, 180)),
            },
            "regions": {"FACIES": facies_regions},
        })

    return wells


# ═══════════════════════════════════════════════════════════════════════════
# COAL DATASET
# Based on: Cole 2008 (coal-bearing Neslen Fm), typical coal measure sequences
#
# Ambiguity source: Coal seams split and merge laterally. A single thick
# seam in Well A may correspond to two thin seams in Well B, or to a
# different seam entirely. Similar interseam intervals.
# ═══════════════════════════════════════════════════════════════════════════

def generate_coal(n_wells=6, seed=2026):
    """
    Coal measures: repeating coal-shale cycles.

    Key to ambiguity: ALL coal seams have identical GR/DEN signature
    (low GR spike). Seams split and merge laterally - one thick seam
    in Well A can be two thin seams in Well B. Interseam sediments
    are uniform shale with identical log character. Which seam is which?

    Based on: Cole 2008 (Neslen Fm), standard coal measure splitting
    """
    rng = np.random.default_rng(seed)
    wells = []

    # 6 "seam events" - but wells see different numbers of seams
    # due to splitting/merging
    n_seam_events = 6

    # Wells see different numbers of seams: splitting/merging
    # Format: list of (seam_thick, gap_after) per well
    # Some wells merge adjacent events into thick seams
    well_seam_configs = [
        # W0: sees all 6 as thin individual seams
        [(3, 6), (3, 6), (3, 6), (3, 6), (3, 6), (3, 6)],
        # W1: events 1+2 merge, 4+5 merge → 4 seams
        [(3, 6), (7, 0), (0, 6), (3, 6), (7, 0), (0, 6)],
        # W2: sees 5 seams (event 2 absent)
        [(3, 6), (3, 6), (0, 3), (3, 6), (3, 6), (3, 6)],
        # W3: events 0+1 merge, 3+4+5 merge → 3 seams
        [(7, 0), (0, 6), (3, 6), (10, 0), (0, 0), (0, 6)],
        # W4: sees all 6 as thin (like W0 - creates inter-well ambiguity)
        [(3, 6), (3, 6), (3, 6), (3, 6), (3, 6), (3, 6)],
        # W5: events 2+3 merge → 5 seams
        [(3, 6), (3, 6), (7, 0), (0, 6), (3, 6), (3, 6)],
    ]

    interseam_gr = 100  # uniform

    for wi in range(n_wells):
        gr_signal = []
        facies_regions = []
        pos = 0

        # Initial overburden
        ob = 5
        gr_signal.extend(shale_interval(ob, mean_gr=interseam_gr, noise=8, rng=rng))
        facies_regions.append((2, pos, ob))
        pos += ob

        for seam_thick, gap_after in well_seam_configs[wi]:
            if seam_thick > 0:
                # Coal seam (identical signature for all)
                gr_signal.extend(list(coal_spike(seam_thick, gr_value=15, noise=3, rng=rng)))
                facies_regions.append((1, pos, seam_thick))
                pos += seam_thick

            if gap_after > 0:
                # Interseam shale (uniform, indistinguishable)
                gr_signal.extend(shale_interval(gap_after, mean_gr=interseam_gr, noise=8, rng=rng))
                facies_regions.append((2, pos, gap_after))
                pos += gap_after

        size = len(gr_signal)
        depth = [float(i) * 0.2 for i in range(size)]

        wells.append({
            "name": f"CB_{wi+1:03d}",
            "x": float(wi * 300),
            "y": 0.0,
            "z": 0.0,
            "h": depth[-1] if depth else 0,
            "size": size,
            "data": {
                "DEPTH": depth,
                "GR": list(np.clip(gr_signal, 0, 180)),
            },
            "regions": {"FACIES": facies_regions},
        })

    return wells


# ═══════════════════════════════════════════════════════════════════════════
# QUATERNARY DATASET
# Based on: Glacial-interglacial sequences, unconformity-bounded units
#
# Ambiguity source: Glacial erosion removes variable amounts of section.
# Similar diamicton-sand-clay cycles repeat. Unconformities mean that
# the same physical horizon is at different relative positions.
# ═══════════════════════════════════════════════════════════════════════════

def generate_quaternary(n_wells=6, seed=2027):
    """
    Quaternary glacial sequence: stacked glacial-interglacial cycles.

    Key to ambiguity: ALL cycles have identical till→sand→clay signature.
    Different wells preserve different numbers of cycles due to glacial
    erosion at the top. Well with 3 cycles and well with 5 cycles -
    which 3 in the first well correspond to which 3 in the second?

    Based on: Standard glacial stratigraphy
    """
    rng = np.random.default_rng(seed)
    wells = []

    # 6 identical glacial cycles - preserved differently per well
    n_max_cycles = 6

    # Which cycles are present per well (glacial erosion removes from top)
    # But also from MIDDLE (subglacial erosion can remove older cycles)
    cycle_presence = [
        [1, 1, 1, 1, 1, 1],  # W0: all 6 preserved (deep valley)
        [1, 1, 1, 1, 0, 0],  # W1: top 2 eroded
        [1, 0, 1, 1, 1, 0],  # W2: cycle 1 eroded, top eroded
        [0, 1, 1, 1, 1, 1],  # W3: basal eroded
        [1, 1, 0, 0, 1, 1],  # W4: middle 2 eroded
        [1, 1, 1, 0, 1, 0],  # W5: patchy erosion
    ]

    for wi in range(n_wells):
        gr_signal = []
        facies_regions = []
        pos = 0

        for ci in range(n_max_cycles):
            if not cycle_presence[wi][ci]:
                continue

            # ALL cycles identical: till(5) → sand FU(6) → clay(4)
            # Till
            till_thick = 5
            gr_signal.extend(list(np.full(till_thick, 80.0) + rng.normal(0, 10, till_thick)))
            facies_regions.append((1, pos, till_thick))
            pos += till_thick

            # Outwash sand (fining up) - identical signature
            sand_thick = 6
            gr_signal.extend(fining_upward_cycle(sand_thick, 55, 30, noise=6, rng=rng))
            facies_regions.append((2, pos, sand_thick))
            pos += sand_thick

            # Lacustrine clay
            clay_thick = 4
            gr_signal.extend(shale_interval(clay_thick, mean_gr=110, noise=6, rng=rng))
            facies_regions.append((3, pos, clay_thick))
            pos += clay_thick

        size = len(gr_signal)
        depth = [float(i) * 0.5 for i in range(size)]

        wells.append({
            "name": f"QW_{wi+1:03d}",
            "x": float(wi * 200),
            "y": 0.0,
            "z": 0.0,
            "h": depth[-1] if depth else 0,
            "size": size,
            "data": {
                "DEPTH": depth,
                "GR": list(np.clip(gr_signal, 0, 180)),
            },
            "regions": {"FACIES": facies_regions},
        })

    return wells


# ═══════════════════════════════════════════════════════════════════════════
# DELTA DATASET
# Based on: Ainsworth 2017, Baville PhD (Hugin Fm, Sigrun area)
#
# Ambiguity source: Prograding delta lobes with lateral switching.
# Wells at different positions on the delta see different stacking
# patterns. Proximal = thick sands; distal = condensed shales.
# Lobe switching means a thick sand in one well could time-correlate
# with a shale in another (avulsion-driven system, Ainsworth 2017).
# ═══════════════════════════════════════════════════════════════════════════

def generate_delta(n_wells=6, seed=2028):
    """
    Delta system: prograding lobes with autogenic switching.

    Key to ambiguity: Lobes switch laterally. Each lobe has IDENTICAL
    CU GR signature (prodelta→delta front). But lobes alternate
    left/right position - so Well A sees lobes 0,2,4 while Well B
    sees lobes 1,3,5. All look the same! Which lobe in A matches
    which in B?

    Based on: Ainsworth 2017, Baville PhD (Hugin Fm)
    """
    rng = np.random.default_rng(seed)
    wells = []

    n_lobes = 7

    # Lobe presence per well (lobe switching)
    # Wells at different strike positions see different lobes
    lobe_presence = [
        [1, 0, 1, 1, 0, 1, 0],  # W0: left position
        [1, 1, 0, 1, 1, 0, 1],  # W1: left-center
        [0, 1, 1, 0, 1, 1, 0],  # W2: center
        [1, 0, 1, 0, 1, 0, 1],  # W3: right-center
        [0, 1, 0, 1, 0, 1, 1],  # W4: right
        [1, 1, 1, 0, 0, 1, 1],  # W5: far right
    ]

    for wi in range(n_wells):
        gr_signal = []
        facies_regions = []
        pos = 0

        for li in range(n_lobes):
            if lobe_presence[wi][li]:
                # Transgressive shale (thin, uniform)
                ts_thick = 3
                gr_signal.extend(shale_interval(ts_thick, mean_gr=115, noise=6, rng=rng))
                facies_regions.append((3, pos, ts_thick))
                pos += ts_thick

                # Delta front CU - ALL IDENTICAL signature
                df_thick = 8
                gr_signal.extend(coarsening_upward_cycle(df_thick, 108, 25, noise=7, rng=rng))
                facies_regions.append((1, pos, df_thick))
                pos += df_thick
            else:
                # Lobe absent: condensed offshore shale (same as transgressive)
                cond_thick = 4
                gr_signal.extend(shale_interval(cond_thick, mean_gr=112, noise=7, rng=rng))
                facies_regions.append((4, pos, cond_thick))
                pos += cond_thick

        size = len(gr_signal)
        depth = [float(i) * 0.5 for i in range(size)]

        wells.append({
            "name": f"DW_{wi+1:02d}",
            "x": float(wi * 600),
            "y": 0.0,
            "z": 0.0,
            "h": depth[-1] if depth else 0,
            "size": size,
            "data": {
                "DEPTH": depth,
                "GR": list(np.clip(gr_signal, 0, 180)),
            },
            "regions": {"FACIES": facies_regions},
        })

    return wells


# ═══════════════════════════════════════════════════════════════════════════
# Main: generate all datasets
# ═══════════════════════════════════════════════════════════════════════════

def main():
    print("Generating revised demo datasets with correlation ambiguity...\n")

    datasets = {
        "fluvial": generate_fluvial,
        "shallow_marine": generate_shallow_marine,
        "coal": generate_coal,
        "quaternary": generate_quaternary,
        "delta": generate_delta,
    }

    for name, generator in datasets.items():
        wells = generator()
        outpath = os.path.join(DEMO_DIR, f"data_set_{name}", "wells.txt")
        write_wells(outpath, wells)
        sizes = [w["size"] for w in wells]
        print(f"  {name}: {len(wells)} wells, sizes {min(sizes)}-{max(sizes)} → {outpath}")

    print("\nDone. Run with: python -m weco.api (or the studio GUI)")


if __name__ == "__main__":
    main()
