#!/usr/bin/env python3
"""
WeCo Diverse Scenario Runner
==============================
Generates synthetic datasets with inherent geological ambiguity, runs
multiple realizations with varied parameters, and produces ranked PNG
snapshots showing genuinely different correlation patterns.

Philosophy:
    Instead of tuning parameters on data with one correct answer, we
    build data where multiple correlation patterns are geologically
    plausible.  The engine's k-best paths + parameter variations then
    reveal distinct "stories" (flow connectivity, facies architecture).

Ambiguity mechanisms:
    1. Thickness variation: same unit, variable thickness → "same layer?"
    2. Facies overlap: log responses shared by multiple lithologies
    3. Lateral discontinuity: layers pinch out → "gap or tie?"
    4. Stacking: similar cycles at different depths → "which to which?"
    5. Erosional truncation: missing sections create false alignments

Usage:
    source ~/.venv/bin/activate
    python bin/run_diverse_scenarios.py              # all scenarios
    python bin/run_diverse_scenarios.py --scenario 1 # single scenario
    python bin/run_diverse_scenarios.py --list       # list scenarios
"""

import math
import os
import sys
import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

# ── WeCo imports ─────────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from weco.ext import ProjectExt
from weco.data import WellList, Well, ResFile

SCRIPT_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = SCRIPT_DIR / "tmp" / "img" / "diverse"
TMP_DIR = SCRIPT_DIR / "tmp"

WELL_COLORS = plt.cm.tab10.colors


# ═══════════════════════════════════════════════════════════════════════════
#  Synthetic Data Generators - designed for AMBIGUITY
# ═══════════════════════════════════════════════════════════════════════════

def _gen_aquifer_connectivity(seed=100):
    """Quaternary aquifer: 'Are sand lenses connected or isolated?'

    6 wells through glacial deposits where:
    - Sand aquifer layers occur at similar but not identical depths
    - Some thin out between wells (connected? or separate lenses?)
    - Till thickness varies → depth offset creates alignment ambiguity
    - Two possible interpretations:
      A) Connected aquifer sheet (few thick correlated layers)
      B) Isolated sand lenses (many thin uncorrelated bodies)
    """
    rng = np.random.default_rng(seed)
    n_wells = 6
    n_markers = 80
    wl = WellList()

    # Define 5 aquifer layers with variable connectivity
    # Pre-decide which wells have which layers (per-well, not per-sample)
    layers = [
        # (base_depth, thickness, gr_sand, gr_till)
        (10, 7, 25, 115),    # L1: thick, most wells have it
        (25, 5, 30, 110),    # L2: intermediate
        (38, 4, 28, 112),    # L3: thin, patchy - KEY AMBIGUITY
        (52, 3, 32, 108),    # L4: very patchy - KEY AMBIGUITY
        (65, 8, 22, 118),    # L5: thick basal, most wells have it
    ]
    # Connectivity matrix: which wells have which layers (pre-decided)
    # This creates the geological ambiguity - layers 2,3 are partially connected
    layer_presence = [
        [True, True, True, True, True, True],     # L1: all wells
        [True, True, True, False, False, True],    # L2: left+right, gap in middle
        [False, True, True, True, False, False],   # L3: only middle wells
        [True, False, False, False, True, True],   # L4: only edges - disconnected!
        [True, True, True, True, True, True],      # L5: all wells
    ]

    for j in range(n_wells):
        # Vertical offset per well (glaciotectonics)
        z_offset = rng.normal(0, 2.5)
        gr_data = []
        rt_data = []
        depth_data = []

        # Pre-compute layer boundaries for this well
        well_layers = []  # (top, bot, gr_sand) for layers present
        for lid, (base_d, thick, gr_sand, gr_till) in enumerate(layers):
            if not layer_presence[lid][j]:
                continue
            # Per-well thickness variation ±40%
            local_thick = thick * (0.6 + 0.8 * rng.random())
            top = base_d + z_offset + rng.normal(0, 1.5)
            bot = top + local_thick
            well_layers.append((top, bot, gr_sand))

        for m in range(n_markers):
            depth_data.append(float(m))

            # Default: till (high GR, low RT)
            gr = 110 + rng.normal(0, 10)
            rt = 20 + rng.normal(0, 5)
            in_sand = False

            for top, bot, gr_sand in well_layers:
                if top <= m <= bot:
                    gr = gr_sand + rng.normal(0, 8)
                    rt = 120 + rng.normal(0, 25)
                    in_sand = True
                    break
                # Transitional zone
                elif top - 1.5 <= m < top or bot < m <= bot + 1.5:
                    gr = 70 + rng.normal(0, 15)
                    rt = 60 + rng.normal(0, 15)
                    in_sand = True
                    break

            gr_data.append(max(5.0, gr))
            rt_data.append(max(2.0, rt))

        w = wl.create_well(f"AQ_{j+1}", x=0.0, y=j * 200.0, size=n_markers)
        w.add_data("Depth", depth_data)
        w.add_data("GR", gr_data)
        w.add_data("RT", rt_data)

    return wl


def _gen_channel_stacking(seed=200):
    """Fluvial: 'One amalgamated channel belt or separate avulsion events?'

    5 wells through stacked channel sands where:
    - Channels occur at nearly the same depth in adjacent wells
    - Some are the SAME channel body (laterally connected)
    - Others are SEPARATE avulsion events at similar depth (disconnected)
    - Log response is identical - only lateral extent distinguishes them
    - Two interpretations:
      A) Connected sand fairway (low gap cost, wide band)
      B) Separate channel events stacked by coincidence (high gap cost)
    """
    rng = np.random.default_rng(seed)
    n_wells = 5
    n_markers = 80
    wl = WellList()

    # Channel bodies: some span multiple wells, some don't
    # Format: (center_depth, wells_present_set, gr_channel)
    channels = [
        (12, {0, 1, 2, 3, 4}, 28),      # Wide connected belt
        (25, {0, 1, 2}, 32),             # Left-side only
        (27, {3, 4}, 30),                # Right-side only - SAME depth!
        (40, {1, 2, 3}, 26),             # Middle cluster
        (42, {0}, 34),                   # Isolated at similar depth to above
        (41, {4}, 31),                   # Another isolate - connected or not?
        (58, {0, 1, 2, 3, 4}, 25),       # Another wide belt
        (70, {0, 1}, 33),                # Partial - left
        (71, {2, 3, 4}, 29),             # Partial - right (same event or not?)
    ]

    for j in range(n_wells):
        gr_data = []
        depth_data = []
        rt_data = []

        for m in range(n_markers):
            depth_data.append(float(m))
            # Default: floodplain (high GR, low RT)
            gr = 115 + rng.normal(0, 10)
            rt = 15 + rng.normal(0, 4)
            facies_hit = False

            for center_d, wells_set, gr_ch in channels:
                if j not in wells_set:
                    continue
                # Channel thickness varies per well
                half_thick = 3 + rng.normal(0, 0.8)
                if abs(m - center_d) <= half_thick:
                    # Within channel
                    gr = gr_ch + rng.normal(0, 8)
                    rt = 80 + rng.normal(0, 20)
                    facies_hit = True
                    break
                # Transition zone (levee/crevasse splay)
                elif abs(m - center_d) <= half_thick + 2:
                    gr = 70 + rng.normal(0, 15)
                    rt = 40 + rng.normal(0, 10)
                    facies_hit = True
                    break

            gr_data.append(max(5.0, gr))
            rt_data.append(max(2.0, rt))

        w = wl.create_well(f"CH_{j+1}", x=0.0, y=j * 150.0, size=n_markers)
        w.add_data("Depth", depth_data)
        w.add_data("GR", gr_data)
        w.add_data("RT", rt_data)

    return wl


def _gen_parasequence_ambiguity(seed=300):
    """Marine: 'Which coarsening-upward cycle ties to which?'

    6 wells through prograding parasequences where:
    - All cycles look similar (coarsening-up GR motif)
    - Variable thickness creates "miscorrelation" opportunities
    - Some condensed sections look like thin PS or like gaps
    - Distal wells have fewer/thinner PS than proximal ones
    - Interpretations:
      A) Layer-cake: all wells have same number of PS (high gap cost)
      B) Wedge: distal condensation → PS pinch out (low gap cost)
      C) Offset: allow cross-cycle miscorrelation (wide band)
    """
    rng = np.random.default_rng(seed)
    n_wells = 6
    wl = WellList()

    for j in range(n_wells):
        distality = j / (n_wells - 1)  # 0=proximal, 1=distal
        # Proximal: 5 thick PS; Distal: 3-4 thin PS with gaps
        n_ps = 5 if distality < 0.5 else (4 if distality < 0.8 else 3)
        ps_base_thick = int(18 * (1.0 - 0.4 * distality))

        gr_data = []
        den_data = []
        depth_data = []
        sample_idx = 0

        for ps in range(n_ps):
            # Variable thickness ±35%
            ps_thick = max(6, int(ps_base_thick * (1.0 + rng.uniform(-0.35, 0.35))))

            # Coarsening-upward motif
            for k in range(ps_thick):
                frac = k / max(ps_thick - 1, 1)  # 0=base (shale), 1=top (sand)
                # GR decreases upward (coarsening up)
                gr = 120 * (1 - frac) + 30 * frac + rng.normal(0, 12)
                den = 2.55 - 0.25 * frac + rng.normal(0, 0.04)
                gr_data.append(max(5.0, gr))
                den_data.append(max(1.8, den))
                depth_data.append(float(sample_idx))
                sample_idx += 1

            # Flooding surface between PS (thin shale)
            if ps < n_ps - 1:
                flood_thick = rng.integers(1, 4)
                for k in range(flood_thick):
                    gr_data.append(130 + rng.normal(0, 8))
                    den_data.append(2.58 + rng.normal(0, 0.03))
                    depth_data.append(float(sample_idx))
                    sample_idx += 1

        n_total = len(gr_data)
        w = wl.create_well(f"PS_{j+1}", x=0.0, y=j * 300.0, size=n_total)
        w.add_data("Depth", depth_data)
        w.add_data("GR", gr_data)
        w.add_data("DEN", den_data)

    return wl


def _gen_carbonate_cycles(seed=400):
    """Carbonate platform: 'Correlate by cycle count or by log character?'

    5 wells through cyclic carbonate-evaporite succession where:
    - High-frequency cycles (shallowing-upward) repeat many times
    - Similar log character between different cycles
    - Some wells have extra cycles (local accommodation space)
    - Thickness ratios change with facies belt position
    - Interpretations:
      A) One-to-one cycle matching (strict, no gaps)
      B) Missing cycles in some wells (gaps allowed)
      C) Amalgamation of thin cycles = one thick cycle elsewhere
    """
    rng = np.random.default_rng(seed)
    n_wells = 5
    wl = WellList()

    # Each well has 6-9 cycles depending on position
    base_cycles = [7, 8, 6, 9, 7]  # variable n_cycles per well

    for j in range(n_wells):
        n_cycles = base_cycles[j]
        gr_data = []
        nphi_data = []
        depth_data = []
        sample_idx = 0

        for cyc in range(n_cycles):
            # Shallowing-upward: subtidal → intertidal → supratidal
            cyc_thick = rng.integers(8, 16)

            for k in range(cyc_thick):
                frac = k / max(cyc_thick - 1, 1)
                # Subtidal (low GR, high porosity) → supratidal (high GR, tight)
                if frac < 0.5:
                    # Subtidal limestone/grainstone
                    gr = 20 + 30 * frac + rng.normal(0, 8)
                    nphi = 0.20 - 0.06 * frac + rng.normal(0, 0.02)
                elif frac < 0.8:
                    # Intertidal (mudstone/wackestone)
                    gr = 50 + 30 * (frac - 0.5) / 0.3 + rng.normal(0, 10)
                    nphi = 0.12 + rng.normal(0, 0.02)
                else:
                    # Supratidal (evaporite/anhydrite cap)
                    gr = 15 + rng.normal(0, 6)  # anhydrite = low GR!
                    nphi = 0.02 + rng.normal(0, 0.01)

                gr_data.append(max(2.0, gr))
                nphi_data.append(max(0.0, min(0.40, nphi)))
                depth_data.append(float(sample_idx))
                sample_idx += 1

        n_total = len(gr_data)
        w = wl.create_well(f"CB_{j+1}", x=0.0, y=j * 250.0, size=n_total)
        w.add_data("Depth", depth_data)
        w.add_data("GR", gr_data)
        w.add_data("NPHI", nphi_data)

    return wl


def _gen_fault_block_offset(seed=500):
    """Rift basin: 'Which layers are juxtaposed across the fault?'

    6 wells across a normal fault zone where:
    - Hanging wall has repeated section (growth strata)
    - Footwall is condensed / eroded
    - Same log character on both sides at different stratigraphic levels
    - Gap cost controls whether engine allows "missing" sections
    - Interpretations:
      A) Continuous correlation across fault (ignores offset)
      B) Two domains with internal correlation only
      C) Partial correlation with large gaps at fault
    """
    rng = np.random.default_rng(seed)
    n_wells = 6
    wl = WellList()

    # Base stratigraphy: 5 units with distinct GR signatures
    units = [
        # (gr_mean, gr_std, base_thick)
        (30, 8, 12),    # U1: sand
        (110, 10, 8),   # U2: shale
        (45, 12, 10),   # U3: silty sand
        (95, 10, 6),    # U4: mudstone
        (25, 6, 15),    # U5: clean sand (reservoir)
    ]

    for j in range(n_wells):
        gr_data = []
        depth_data = []
        sample_idx = 0

        # Wells 0-2: footwall (condensed, possibly eroded top)
        # Wells 3-5: hanging wall (expanded, with growth strata)
        is_hanging_wall = j >= 3

        for uid, (gr_mean, gr_std, base_thick) in enumerate(units):
            if is_hanging_wall:
                # Expanded section: thicker, with possible repeated interval
                thick = int(base_thick * (1.3 + 0.3 * rng.random()))
                # Growth strata: extra thickness in lower units
                if uid >= 3:
                    thick = int(thick * 1.5)
            else:
                # Condensed: thinner, top units may be eroded
                thick = int(base_thick * (0.5 + 0.4 * rng.random()))
                if uid == 0 and j == 0:
                    thick = max(2, thick // 2)  # Most eroded

            for k in range(max(2, thick)):
                gr = gr_mean + rng.normal(0, gr_std)
                # Add subtle trend within unit
                frac = k / max(thick - 1, 1)
                gr += 10 * math.sin(math.pi * frac)  # bell shape
                gr_data.append(max(5.0, gr))
                depth_data.append(float(sample_idx))
                sample_idx += 1

        n_total = len(gr_data)
        w = wl.create_well(f"FB_{j+1}", x=0.0, y=j * 180.0, size=n_total)
        w.add_data("Depth", depth_data)
        w.add_data("GR", gr_data)

    return wl


# ═══════════════════════════════════════════════════════════════════════════
#  Scenario Definitions - each explores a different source of ambiguity
# ═══════════════════════════════════════════════════════════════════════════

SCENARIOS = {
    "1_aquifer_connectivity": {
        "title": "Aquifer Connectivity - Connected sheet vs isolated lenses",
        "generator": _gen_aquifer_connectivity,
        "description": (
            "Glacial aquifers: sand layers at similar depths may be ONE\n"
            "connected aquifer or SEPARATE lenses. Critical for groundwater\n"
            "flow modelling - connected = large resource, isolated = compartments."
        ),
        "param_sets": [
            {"name": "connected_sheet",
             "desc": "Low gap cost, wide band → favours continuous layers",
             "opts": {"var_data": "GR", "var_weight": 0.6,
                      "var_data2": "RT", "var_weight2": 0.4,
                      "const_gap_cost": 0.3, "band_width": 30,
                      "min_dist": 0.08}},
            {"name": "isolated_lenses",
             "desc": "High gap cost → penalises gaps, forces 1-to-1 matching",
             "opts": {"var_data": "GR", "var_weight": 0.6,
                      "var_data2": "RT", "var_weight2": 0.4,
                      "const_gap_cost": 5.0, "band_width": 12,
                      "min_dist": 0.1}},
            {"name": "RT_dominant",
             "desc": "Resistivity-led: highlights permeable vs impermeable",
             "opts": {"var_data": "RT", "var_weight": 0.85,
                      "var_data2": "GR", "var_weight2": 0.15,
                      "const_gap_cost": 2.0, "band_width": 20,
                      "min_dist": 0.08}},
            {"name": "narrow_band_strict",
             "desc": "Tight Sakoe-Chiba band → only near-horizontal ties",
             "opts": {"var_data": "GR", "var_weight": 0.6,
                      "var_data2": "RT", "var_weight2": 0.4,
                      "const_gap_cost": 1.5, "band_width": 6,
                      "cost_floor": 0.2, "min_dist": 0.06}},
        ],
        "common_opts": {"cost_function": "composite", "order": "pyramidal",
                        "max_cor": 60, "nbr_cor": 40, "out_nbr_cor": 20,
                        "out_min_dist": 0.05},
    },

    "2_channel_stacking": {
        "title": "Channel Belt Stacking - Amalgamated vs separate events",
        "generator": _gen_channel_stacking,
        "description": (
            "Fluvial channels at the same depth in adjacent wells: same\n"
            "channel belt (lateral extent) or coincidental stacking of\n"
            "separate avulsion events? Controls reservoir connectivity."
        ),
        "param_sets": [
            {"name": "wide_connected",
             "desc": "No gap cost, wide band → maximise lateral connectivity",
             "opts": {"var_data": "GR", "var_weight": 0.7,
                      "var_data2": "RT", "var_weight2": 0.3,
                      "const_gap_cost": 0.0, "band_width": 30}},
            {"name": "gap_penalised",
             "desc": "Gap cost forces every channel to correlate somewhere",
             "opts": {"var_data": "GR", "var_weight": 0.7,
                      "var_data2": "RT", "var_weight2": 0.3,
                      "const_gap_cost": 3.5, "band_width": 20}},
            {"name": "RT_dominant",
             "desc": "Resistivity-dominated: separates channel from floodplain",
             "opts": {"var_data": "RT", "var_weight": 0.8,
                      "var_data2": "GR", "var_weight2": 0.2,
                      "const_gap_cost": 1.0, "band_width": 20}},
            {"name": "narrow_strict",
             "desc": "Very tight band → only near-horizontal correlations",
             "opts": {"var_data": "GR", "var_weight": 0.7,
                      "var_data2": "RT", "var_weight2": 0.3,
                      "const_gap_cost": 2.0, "band_width": 6,
                      "cost_floor": 0.15}},
        ],
        "common_opts": {"cost_function": "composite", "order": "pyramidal",
                        "max_cor": 50, "nbr_cor": 30, "out_nbr_cor": 20,
                        "out_min_dist": 0.02, "min_dist": 0.05},
    },

    "3_parasequence_wedge": {
        "title": "Parasequence Geometry - Layer-cake vs clinoform wedge",
        "generator": _gen_parasequence_ambiguity,
        "description": (
            "Prograding shoreface: coarsening-up cycles repeat and look\n"
            "similar. Proximal wells have more/thicker PS than distal.\n"
            "Layer-cake interpretation (all PS continuous) vs wedge\n"
            "(some PS pinch out distally) → different volume estimates."
        ),
        "param_sets": [
            {"name": "layer_cake",
             "desc": "High gap cost → force all PS to correlate (layer-cake)",
             "opts": {"var_data": "GR", "var_weight": 0.6,
                      "var_data2": "DEN", "var_weight2": 0.4,
                      "const_gap_cost": 5.0, "band_width": 25}},
            {"name": "wedge_model",
             "desc": "Low gap cost → allow PS pinch-out (wedge geometry)",
             "opts": {"var_data": "GR", "var_weight": 0.6,
                      "var_data2": "DEN", "var_weight2": 0.4,
                      "const_gap_cost": 0.3, "band_width": 30}},
            {"name": "GR_only_tight",
             "desc": "GR only + tight band → miscorrelation across cycles",
             "opts": {"var_data": "GR", "var_weight": 1.0,
                      "const_gap_cost": 2.0, "band_width": 10}},
            {"name": "DEN_dominant",
             "desc": "Density-dominated: distinguishes cemented from porous",
             "opts": {"var_data": "DEN", "var_weight": 0.8,
                      "var_data2": "GR", "var_weight2": 0.2,
                      "const_gap_cost": 1.5, "band_width": 20}},
        ],
        "common_opts": {"cost_function": "composite", "order": "linear",
                        "max_cor": 50, "nbr_cor": 30, "out_nbr_cor": 20,
                        "out_min_dist": 0.02, "min_dist": 0.05},
    },

    "4_carbonate_cycles": {
        "title": "Carbonate Cycles - Cycle counting vs log character",
        "generator": _gen_carbonate_cycles,
        "description": (
            "Repeated shallowing-up cycles on a carbonate platform. All\n"
            "cycles have similar log character but DIFFERENT wells have\n"
            "DIFFERENT numbers of cycles. One-to-one matching is impossible;\n"
            "the engine must decide which cycles are 'missing'."
        ),
        "param_sets": [
            {"name": "one_to_one_strict",
             "desc": "High gap cost + tight band → force 1:1 matching",
             "opts": {"var_data": "GR", "var_weight": 0.5,
                      "var_data2": "NPHI", "var_weight2": 0.5,
                      "const_gap_cost": 5.0, "band_width": 12}},
            {"name": "allow_gaps",
             "desc": "Low gap cost → allow 'missing' cycles",
             "opts": {"var_data": "GR", "var_weight": 0.5,
                      "var_data2": "NPHI", "var_weight2": 0.5,
                      "const_gap_cost": 0.5, "band_width": 25}},
            {"name": "porosity_led",
             "desc": "NPHI-dominant → tie reservoir zones regardless of GR",
             "opts": {"var_data": "NPHI", "var_weight": 0.9,
                      "var_data2": "GR", "var_weight2": 0.1,
                      "const_gap_cost": 1.5, "band_width": 20}},
            {"name": "wide_open",
             "desc": "Maximum freedom: no gap cost, wide band, high k-best",
             "opts": {"var_data": "GR", "var_weight": 0.5,
                      "var_data2": "NPHI", "var_weight2": 0.5,
                      "const_gap_cost": 0.0, "band_width": 40}},
        ],
        "common_opts": {"cost_function": "composite", "order": "pyramidal",
                        "max_cor": 60, "nbr_cor": 40, "out_nbr_cor": 20,
                        "out_min_dist": 0.03, "min_dist": 0.05},
    },

    "5_fault_juxtaposition": {
        "title": "Fault Block - Which layers juxtapose across the fault?",
        "generator": _gen_fault_block_offset,
        "description": (
            "Normal fault: hanging wall expanded (growth strata), footwall\n"
            "condensed/eroded. Same log character at different stratigraphic\n"
            "levels across the fault. Which sand in the HW connects to which\n"
            "sand in the FW? Critical for across-fault flow."
        ),
        "param_sets": [
            {"name": "continuous_across",
             "desc": "Ignore offset - correlate all as one domain",
             "opts": {"var_data": "GR", "var_weight": 1.0,
                      "const_gap_cost": 4.0, "band_width": 40}},
            {"name": "honour_offset",
             "desc": "Allow large gaps at fault (band allows big depth shift)",
             "opts": {"var_data": "GR", "var_weight": 1.0,
                      "const_gap_cost": 0.5, "band_width": 50,
                      "min_dist": 0.08}},
            {"name": "strict_layer_match",
             "desc": "Tight band → only correlate near-depth equivalents",
             "opts": {"var_data": "GR", "var_weight": 1.0,
                      "const_gap_cost": 3.0, "band_width": 10,
                      "cost_floor": 0.1}},
            {"name": "cost_floor_denoise",
             "desc": "Cost floor suppresses minor wiggles → matches major units",
             "opts": {"var_data": "GR", "var_weight": 1.0,
                      "const_gap_cost": 1.5, "band_width": 25,
                      "cost_floor": 0.3}},
        ],
        "common_opts": {"cost_function": "composite", "order": "linear",
                        "max_cor": 50, "nbr_cor": 30, "out_nbr_cor": 20,
                        "out_min_dist": 0.03, "min_dist": 0.05},
    },
}


# ═══════════════════════════════════════════════════════════════════════════
#  Engine runner
# ═══════════════════════════════════════════════════════════════════════════

def _reset_engine(project):
    """Clear all sticky global options."""
    resets = {
        "no_crossing": "", "no_crossing2": "", "no_crossing3": "",
        "same_region": "", "same_region2": "", "same_region3": "",
        "polarity_region": "", "var_region": "",
        "var_data": "", "var_data2": "", "var_data3": "",
        "var_data4": "", "var_data5": "",
        "var_weight": "1.0", "var_weight2": "0", "var_weight3": "0",
        "var_weight4": "0", "var_weight5": "0",
        "dist_distal": "", "dist_facies": "",
        "gap_cost_func": "", "const_gap_cost": "0",
        "const_gap_cost_start": "-1", "const_gap_cost_end": "-1",
        "multi_dist_distal": "", "multi_dist_facies": "",
        "band_width": "0", "beam_width": "0",
        "cost_floor": "0", "cost_weighted_avg": "0",
        "min_dist": "0", "out_min_dist": "0",
    }
    project.set_options_ext(**resets)


def run_single(well_list, opts, out_file):
    """Run the engine once, return ResFile or None."""
    project = ProjectExt()
    _reset_engine(project)
    full_opts = dict(opts)
    full_opts["out_file"] = str(out_file)
    project.set_options_ext(**full_opts)

    # Write well list to temp file for engine
    tmp_wells = out_file.parent / f"{out_file.stem}_wells.txt"
    well_list.write(str(tmp_wells))
    success = project.run(str(tmp_wells))

    if not success or not out_file.exists():
        return None

    try:
        res = ResFile(str(out_file), build_list=True, reorder=True)
        if res.get_nbr_results() == 0:
            return None
        return res
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════════
#  Plotting - side-by-side well logs with correlation lines
# ═══════════════════════════════════════════════════════════════════════════

def plot_realization(well_list, res_file, cor_index, title, subtitle, out_path,
                     data_name="GR"):
    """Plot a single correlation realization."""
    n_results = res_file.get_nbr_results()
    if cor_index >= n_results:
        return

    n_wells = len(res_file.well_id)
    wells = [well_list.wells[wid] for wid in res_file.well_id]

    # Get depths
    def get_depth(well):
        for dname in ("Depth", "DEPTH", "MD"):
            if dname in well.data:
                return list(well.data[dname])
        return list(range(well.size))

    depths = [get_depth(w) for w in wells]

    fig_width = max(8, 2.5 * n_wells)
    fig, axes = plt.subplots(1, n_wells, figsize=(fig_width, 9), sharey=False)
    if n_wells == 1:
        axes = [axes]

    fig.suptitle(title, fontsize=11, fontweight="bold", y=0.98)

    for i, (well, ax, depth) in enumerate(zip(wells, axes, depths)):
        ax.set_title(well.name, fontsize=9, color=WELL_COLORS[i % 10])
        ax.invert_yaxis()

        if data_name and data_name in well.data:
            vals = list(well.data[data_name])[:len(depth)]
            ax.plot(vals, depth[:len(vals)], color=WELL_COLORS[i % 10],
                    linewidth=1.0, alpha=0.9)
            ax.fill_betweenx(depth[:len(vals)], vals, alpha=0.15,
                             color=WELL_COLORS[i % 10])
            ax.set_xlabel(data_name, fontsize=8)
        else:
            ax.axvline(0, color=WELL_COLORS[i % 10], linewidth=2)

        if i == 0:
            ax.set_ylabel("Depth", fontsize=9)
        ax.grid(True, alpha=0.2)
        ax.tick_params(labelsize=7)

    # Draw correlation lines - subsample for clarity
    path = res_file.get_result_full_path(cor_index)
    cost = res_file.get_result_cost(cor_index)

    # Show at most 30 correlation lines (evenly spaced through path)
    n_lines = min(30, len(path))
    step = max(1, len(path) // n_lines)
    shown_nodes = path[::step]

    for node in shown_nodes:
        for k in range(n_wells - 1):
            m_left = node[k]
            m_right = node[k + 1]
            if m_left < len(depths[k]) and m_right < len(depths[k + 1]):
                y_left = depths[k][m_left]
                y_right = depths[k + 1][m_right]
                con = matplotlib.patches.ConnectionPatch(
                    xyA=(1.0, y_left), coordsA=axes[k].get_yaxis_transform(),
                    xyB=(0.0, y_right), coordsB=axes[k + 1].get_yaxis_transform(),
                    color="darkblue", alpha=0.5, linewidth=0.8)
                fig.add_artist(con)

    fig.text(0.5, 0.01,
             f"{subtitle}  |  Realization #{cor_index+1}  |  Cost: {cost:.4f}  |  "
             f"Path nodes: {len(path)}",
             ha="center", fontsize=8, style="italic", color="gray")

    plt.tight_layout(rect=[0, 0.03, 1, 0.95])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_summary_grid(results_dict, scenario_title, out_path):
    """Plot a summary grid: best realization from each param_set."""
    n_sets = len(results_dict)
    if n_sets == 0:
        return

    fig, axes = plt.subplots(1, n_sets, figsize=(5 * n_sets, 4))
    if n_sets == 1:
        axes = [axes]

    fig.suptitle(f"{scenario_title} - Cost Comparison", fontsize=12, fontweight="bold")

    names = list(results_dict.keys())
    costs_all = []
    for i, name in enumerate(names):
        info = results_dict[name]
        n_res = info["n_results"]
        costs = [info["res_file"].get_result_cost(j) for j in range(n_res)]
        costs_all.append(costs)

        ax = axes[i]
        ax.barh(range(len(costs)), costs, color=WELL_COLORS[i % 10], alpha=0.7)
        ax.set_title(f"{name}\n({n_res} results)", fontsize=8)
        ax.set_xlabel("Cost", fontsize=8)
        ax.set_ylabel("Rank", fontsize=8)
        ax.invert_yaxis()
        ax.tick_params(labelsize=7)
        ax.grid(axis="x", alpha=0.3)

    plt.tight_layout(rect=[0, 0, 1, 0.92])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


# ═══════════════════════════════════════════════════════════════════════════
#  Main orchestrator
# ═══════════════════════════════════════════════════════════════════════════

def run_scenario(key, scenario, output_dir, n_top=5):
    """Run one scenario: generate data, run all param sets, plot ranked results."""
    print(f"\n{'='*72}")
    print(f"  SCENARIO: {scenario['title']}")
    print(f"{'='*72}")
    print(f"  {scenario['description']}")
    print()

    # Generate the ambiguous dataset
    gen_func = scenario["generator"]
    well_list = gen_func()
    print(f"  Generated: {well_list.nbr_wells()} wells, "
          f"{well_list.wells[0].size} samples/well (first)")

    sc_output = output_dir / key
    sc_output.mkdir(parents=True, exist_ok=True)

    # Detect primary plot data
    w0 = well_list.wells[0]
    plot_data = None
    for dname in w0.data:
        if dname.upper() not in ("DEPTH", "MD", "TVD", "TVDSS", "FACIES"):
            plot_data = dname
            break

    results_dict = {}
    total_realizations = 0
    n_param_sets = len(scenario["param_sets"])

    for ps_idx, ps in enumerate(scenario["param_sets"]):
        ps_name = ps["name"]
        ps_desc = ps["desc"]
        print(f"\n  [{ps_idx+1}/{n_param_sets}] {ps_name}: {ps_desc}")

        # Merge options
        opts = dict(scenario.get("common_opts", {}))
        opts.update(ps["opts"])

        # Run engine
        res_path = sc_output / f"{ps_name}_result.txt"
        res_file = run_single(well_list, opts, res_path)

        if res_file is None:
            print(f"    FAILED - no results")
            continue

        n_results = res_file.get_nbr_results()
        best_cost = res_file.get_result_cost(0)
        worst_cost = res_file.get_result_cost(n_results - 1) if n_results > 1 else best_cost
        print(f"    {n_results} realizations | cost range: {best_cost:.4f} – {worst_cost:.4f}")

        results_dict[ps_name] = {
            "res_file": res_file,
            "n_results": n_results,
            "best_cost": best_cost,
            "opts": opts,
        }

        # Plot top-N ranked realizations for this param set
        n_plot = min(n_top, n_results)
        for rank in range(n_plot):
            cost_i = res_file.get_result_cost(rank)
            img_path = sc_output / f"{ps_name}_rank{rank+1:02d}.png"
            plot_realization(
                well_list, res_file, rank,
                title=f"{scenario['title']}",
                subtitle=f"{ps_name} (rank {rank+1}/{n_results}, cost={cost_i:.4f})",
                out_path=img_path,
                data_name=plot_data,
            )
            total_realizations += 1

        # Progress
        print(f"    Plotted {n_plot} ranked realizations → {sc_output.name}/{ps_name}_rank*.png")

    # Summary comparison across param sets
    if len(results_dict) > 1:
        plot_summary_grid(results_dict, scenario["title"],
                          sc_output / "00_summary_comparison.png")
        print(f"\n  Summary plot → {sc_output.name}/00_summary_comparison.png")

    print(f"\n  Total realizations plotted for {key}: {total_realizations}")
    return results_dict


def main():
    parser = argparse.ArgumentParser(
        description="WeCo Diverse Scenario Runner - ambiguous geology, multiple interpretations")
    parser.add_argument("--scenario", "-s", type=str, default=None,
                        help="Run only a specific scenario (number or key)")
    parser.add_argument("--list", "-l", action="store_true",
                        help="List available scenarios")
    parser.add_argument("--output", "-o", type=str, default=str(OUTPUT_DIR),
                        help="Output directory")
    parser.add_argument("--top", "-n", type=int, default=5,
                        help="Number of top-ranked realizations to plot per param set")
    args = parser.parse_args()

    if args.list:
        print("Available scenarios:")
        for key, sc in SCENARIOS.items():
            print(f"  {key}: {sc['title']}")
        return

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.scenario:
        matched = {k: v for k, v in SCENARIOS.items()
                   if args.scenario in k or k.startswith(args.scenario)}
        if not matched:
            print(f"No scenario matching '{args.scenario}'. Use --list.")
            sys.exit(1)
        targets = matched
    else:
        targets = SCENARIOS

    print(f"WeCo Diverse Scenario Runner")
    print(f"Output: {output_dir}")
    print(f"Scenarios: {len(targets)} | Top-N per param set: {args.top}")
    print(f"Total param sets: {sum(len(s['param_sets']) for s in targets.values())}")
    total_expected = sum(len(s['param_sets']) * args.top for s in targets.values())
    print(f"Expected plots: up to {total_expected}")
    print()

    all_results = {}
    for i, (key, sc) in enumerate(targets.items()):
        print(f"\n{'─'*72}")
        print(f"  Progress: scenario {i+1}/{len(targets)}")
        print(f"{'─'*72}")
        all_results[key] = run_scenario(key, sc, output_dir, n_top=args.top)

    print(f"\n{'═'*72}")
    print(f"  DONE - all scenarios complete")
    print(f"  Output directory: {output_dir}")
    print(f"{'═'*72}")


if __name__ == "__main__":
    main()
