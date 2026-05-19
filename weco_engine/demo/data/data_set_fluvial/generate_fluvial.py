#!/usr/bin/env python3
"""
Generate a synthetic fluvial channel belt dataset.

Produces wells with GR logs representing laterally discontinuous
channel sandbodies in a fluvial environment.  This is one of the
hardest correlation scenarios because channels do not extend
laterally across all wells.

Usage::

    python generate_fluvial.py [--n_wells 20] [--seed 42] [--output_dir .]
"""

from __future__ import annotations

import math
import os
import random
from argparse import ArgumentParser

import numpy as np


def main(
    n_wells: int = 20,
    n_markers: int = 80,
    seed: int = 42,
    output_dir: str = ".",
):
    """Generate fluvial channel belt wells and write to files."""
    rng = random.Random(seed)
    np_rng = np.random.default_rng(seed)
    spacing = 150.0

    os.makedirs(output_dir, exist_ok=True)

    # Facies: 0=floodplain, 1=crevasse_splay, 2=channel_fill,
    #         3=channel_lag, 4=levee, 5=oxbow_lake
    FACIES_GR = {0: 120.0, 1: 75.0, 2: 30.0, 3: 15.0, 4: 90.0, 5: 110.0}

    # Generate random channel positions
    n_channels = n_markers // 8
    channels = []
    for _ in range(n_channels):
        y_centre = rng.uniform(0, (n_wells - 1) * spacing)
        z_centre = rng.randint(5, n_markers - 5)
        width = rng.uniform(0.15, 0.35) * (n_wells - 1) * spacing
        thickness = rng.randint(3, 8)
        sinuosity = rng.uniform(0, spacing * 2)  # lateral offset
        channels.append((y_centre, z_centre, width, thickness, sinuosity))

    wells_lines = []

    for j in range(n_wells):
        y_pos = j * spacing
        x_pos = 0.0

        gr, depth = [], []
        facies_list = []

        for m in range(n_markers):
            depth.append(float(m))
            facies = 0  # default floodplain

            for y_c, z_c, w, t, sin_off in channels:
                # Channel meanders: effective y-centre varies with depth
                eff_y = y_c + sin_off * math.sin(2 * math.pi * m / n_markers)
                if abs(y_pos - eff_y) < w / 2 and abs(m - z_c) < t / 2:
                    dist_from_axis = abs(y_pos - eff_y) / (w / 2)
                    depth_in_channel = abs(m - z_c) / (t / 2)

                    if dist_from_axis < 0.2 and depth_in_channel > 0.7:
                        facies = 3  # channel lag (base)
                    elif dist_from_axis < 0.4:
                        facies = 2  # channel fill
                    elif dist_from_axis < 0.7:
                        facies = 1  # crevasse splay
                    else:
                        facies = 4  # levee
                    break

            facies_list.append(facies)
            gr_val = FACIES_GR[facies] + np_rng.normal(0, 5)
            gr.append(gr_val)

        wells_lines.append(f"WELL W{j} {n_markers} {x_pos} {y_pos}")
        wells_lines.append(f"DATA depth {' '.join(f'{v:.2f}' for v in depth)}")
        wells_lines.append(f"DATA GR {' '.join(f'{v:.2f}' for v in gr)}")

        # Facies region
        intervals = []
        if facies_list:
            cur_f = facies_list[0]
            cur_start = 0
            cur_len = 1
            for mi in range(1, len(facies_list)):
                if facies_list[mi] == cur_f:
                    cur_len += 1
                else:
                    intervals.append((cur_f, cur_start, cur_len))
                    cur_f = facies_list[mi]
                    cur_start = mi
                    cur_len = 1
            intervals.append((cur_f, cur_start, cur_len))

        region_parts = []
        for rid, rstart, rlen in intervals:
            region_parts.append(f"{rid} {rstart} {rlen}")
        wells_lines.append(f"REGION facies {' '.join(region_parts)}")

    wells_path = os.path.join(output_dir, "wells.txt")
    with open(wells_path, "w") as f:
        f.write("\n".join(wells_lines) + "\n")

    opts_path = os.path.join(output_dir, "options.txt")
    with open(opts_path, "w") as f:
        f.write("# Fluvial channel belt correlation options\n")
        f.write("cost-function composite\n")
        f.write("var-data GR\n")
        f.write("var-weight 1.0\n")
        f.write("order pyramidal\n")
        f.write("nbr-cor 50\n")
        f.write("out-nbr-cor 10\n")
        f.write("max-cor 200\n")
        f.write("gap-const-cost 0.2\n")

    print(f"Generated {n_wells} wells in {wells_path}")
    return wells_path, opts_path


if __name__ == "__main__":
    parser = ArgumentParser(description="Generate fluvial channel belt dataset")
    parser.add_argument("--n_wells", type=int, default=20)
    parser.add_argument("--n_markers", type=int, default=80)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output_dir", default=".")
    args = parser.parse_args()
    main(n_wells=args.n_wells, n_markers=args.n_markers,
         seed=args.seed, output_dir=args.output_dir)
