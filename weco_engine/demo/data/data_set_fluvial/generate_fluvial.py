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
    """Generate fluvial channel belt wells and write to files.

    Key design for correlation ambiguity:
    - Channels at SIMILAR depths but NOT connected → "same channel or different?"
    - Some channels barely extend between adjacent wells → marginal connectivity
    - Stacked channels (avulsion) at same location → "one amalgamated body or two?"
    - Higher GR noise so channel/floodplain boundary is ambiguous in log response
    """
    rng = random.Random(seed)
    np_rng = np.random.default_rng(seed)
    spacing = 150.0

    os.makedirs(output_dir, exist_ok=True)

    # Facies: 0=floodplain, 1=crevasse_splay, 2=channel_fill,
    #         3=channel_lag, 4=levee, 5=oxbow_lake
    # GR values with OVERLAP: channel fill (30±15) overlaps with levee (85±20)
    # and crevasse splay (70±18) - realistic subsurface ambiguity
    FACIES_GR = {0: 118.0, 1: 70.0, 2: 32.0, 3: 18.0, 4: 85.0, 5: 108.0}
    FACIES_GR_STD = {0: 12.0, 1: 18.0, 2: 15.0, 3: 8.0, 4: 20.0, 5: 14.0}

    # Generate channels with deliberate ambiguity:
    # - Paired channels at similar depths (connected? or separate avulsion events?)
    # - Variable lateral extent (some wide, some narrow → pinch-out uncertainty)
    n_channels = n_markers // 5  # more channels than before
    channels = []
    for i in range(n_channels):
        y_centre = rng.uniform(0, (n_wells - 1) * spacing)
        z_centre = rng.randint(5, n_markers - 5)
        # Bimodal width distribution: some wide (connected), some narrow (isolated)
        if rng.random() < 0.4:
            width = rng.uniform(0.5, 0.8) * (n_wells - 1) * spacing  # wide
        else:
            width = rng.uniform(0.10, 0.25) * (n_wells - 1) * spacing  # narrow
        thickness = rng.randint(3, 9)
        sinuosity = rng.uniform(spacing * 0.5, spacing * 3)

        channels.append((y_centre, z_centre, width, thickness, sinuosity))

        # 30% chance: add a paired channel at similar depth (avulsion/stacking)
        # This creates "same body or separate?" ambiguity
        if rng.random() < 0.3:
            y_offset = rng.uniform(-spacing * 2, spacing * 2)
            z_offset = rng.randint(-2, 2)  # nearly same depth!
            width2 = rng.uniform(0.12, 0.30) * (n_wells - 1) * spacing
            channels.append((y_centre + y_offset, z_centre + z_offset,
                             width2, thickness - 1, sinuosity * 0.7))

    wells_data = []

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
            # Higher noise per facies - creates genuine log ambiguity
            gr_val = FACIES_GR[facies] + np_rng.normal(0, FACIES_GR_STD[facies])
            gr.append(gr_val)

        # Facies region intervals
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

        wells_data.append({
            "name": f"W{j}", "n": n_markers,
            "x": x_pos, "y": y_pos, "z": 0.0, "h": 1.0,
            "depth": depth, "GR": gr, "facies_intervals": intervals,
        })

    # Write WeCo WellList v2 format
    wells_path = os.path.join(output_dir, "wells.txt")
    with open(wells_path, "w") as f:
        f.write("WeCo WellList 2\n")
        f.write(f"{len(wells_data)}\n")
        for w in wells_data:
            n = w["n"]
            f.write(f"\n{w['name']}\n")
            f.write(f"{n}\n")
            f.write(f"{w['x']:.5f} {w['y']:.5f} {w['z']:.5f} {w['h']:.5f}\n")
            # 2 data columns: DEPTH, GR
            f.write("2\n")
            f.write(f"DEPTH {n}\n")
            for v in w["depth"]:
                f.write(f"{v:.5f}\n")
            f.write(f"GR {n}\n")
            for v in w["GR"]:
                f.write(f"{v:.5f}\n")
            # 1 region: facies
            f.write("1\n")
            f.write(f"FACIES {len(w['facies_intervals'])}\n")
            for rid, rstart, rlen in w["facies_intervals"]:
                f.write(f"{rid} {rstart} {rlen}\n")
        f.write("END\n")

    opts_path = os.path.join(output_dir, "options.txt")
    with open(opts_path, "w") as f:
        f.write("# Fluvial channel belt correlation options\n")
        f.write("# Low gap cost: channels don't connect everywhere.\n")
        f.write("# min-dist ensures genuinely different scenario geometries.\n")
        f.write("cost-function=composite\n")
        f.write("var-data=GR\n")
        f.write("var-weight=1.0\n")
        f.write("order=pyramidal\n")
        f.write("nbr-cor=30\n")
        f.write("out-nbr-cor=5\n")
        f.write("max-cor=100\n")
        f.write("const-gap-cost=0.5\n")
        f.write("min-dist=0.4\n")
        f.write("out-min-dist=0.15\n")

    # Export JSON
    import json as _json
    from weco.data import WellList
    from weco.json_format import welllist_to_json
    wl = WellList(wells_path)
    doc = welllist_to_json(wl)
    json_path = os.path.join(output_dir, "wells.weco.json")
    with open(json_path, "w") as f:
        _json.dump(doc, f, indent=2)
    print(f"Wrote: {json_path}")

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
