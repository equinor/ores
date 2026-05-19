#!/usr/bin/env python3
"""
Generate a synthetic prograding delta dataset.

Produces wells with GR, DEN, NPHI logs and facies regions
representing prograding parasequences in a deltaic environment.

Usage::

    python generate_delta.py [--n_wells 8] [--seed 42] [--output_dir .]
"""

from __future__ import annotations

import math
import os
import random
from argparse import ArgumentParser

import numpy as np


def main(
    n_wells: int = 8,
    n_markers: int = 100,
    n_parasequences: int = 6,
    seed: int = 42,
    output_dir: str = ".",
):
    """Generate prograding delta wells and write to files."""
    rng = random.Random(seed)
    np_rng = np.random.default_rng(seed)
    spacing = 400.0

    os.makedirs(output_dir, exist_ok=True)

    # Facies: 0=prodelta_shale, 1=distal_delta_front, 2=proximal_delta_front,
    #         3=distributary_mouth_bar, 4=distributary_channel, 5=interdistributary_bay,
    #         6=marsh, 7=delta_plain
    FACIES = {
        0: {"GR": 130, "DEN": 2.55, "NPHI": 0.35},
        1: {"GR": 100, "DEN": 2.48, "NPHI": 0.30},
        2: {"GR": 65,  "DEN": 2.38, "NPHI": 0.24},
        3: {"GR": 35,  "DEN": 2.28, "NPHI": 0.18},
        4: {"GR": 25,  "DEN": 2.22, "NPHI": 0.15},
        5: {"GR": 110, "DEN": 2.50, "NPHI": 0.32},
        6: {"GR": 120, "DEN": 2.52, "NPHI": 0.34},
        7: {"GR": 95,  "DEN": 2.45, "NPHI": 0.28},
    }

    n_per_para = n_markers // n_parasequences

    wells_lines = []

    for j in range(n_wells):
        distality = j / max(n_wells - 1, 1)  # 0=proximal, 1=distal
        x_pos = j * spacing
        y_pos = 0.0

        gr, den, nphi, depth = [], [], [], []
        facies_list = []

        for ps in range(n_parasequences):
            prograde_shift = ps / max(n_parasequences - 1, 1)
            for k in range(n_per_para):
                m = ps * n_per_para + k
                depth.append(float(m))
                pos_in_para = k / max(n_per_para - 1, 1)

                # Coarsening upward, modulated by distality and progradation
                sand_prob = pos_in_para * (1.0 - distality * 0.7) * (0.4 + 0.6 * prograde_shift)

                if sand_prob > 0.8:
                    f = 4
                elif sand_prob > 0.6:
                    f = 3
                elif sand_prob > 0.4:
                    f = 2
                elif sand_prob > 0.2:
                    f = 1
                else:
                    f = 0 if distality > 0.5 else 5

                facies_list.append(f)
                props = FACIES[f]
                gr.append(props["GR"] + np_rng.normal(0, 5))
                den.append(props["DEN"] + np_rng.normal(0, 0.02))
                nphi.append(props["NPHI"] + np_rng.normal(0, 0.01))

        n_actual = len(depth)
        wells_lines.append(f"WELL {f'W{j}'} {n_actual} {x_pos} {y_pos}")
        wells_lines.append(f"DATA depth {' '.join(f'{v:.2f}' for v in depth)}")
        wells_lines.append(f"DATA GR {' '.join(f'{v:.2f}' for v in gr)}")
        wells_lines.append(f"DATA DEN {' '.join(f'{v:.4f}' for v in den)}")
        wells_lines.append(f"DATA NPHI {' '.join(f'{v:.4f}' for v in nphi)}")

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

    # Options file
    opts_path = os.path.join(output_dir, "options.txt")
    with open(opts_path, "w") as f:
        f.write("# Prograding delta correlation options\n")
        f.write("cost-function composite\n")
        f.write("var-data GR\n")
        f.write("var-weight 1.0\n")
        f.write("order pyramidal\n")
        f.write("nbr-cor 50\n")
        f.write("out-nbr-cor 10\n")
        f.write("max-cor 200\n")

    # Distality options
    opts_dist = os.path.join(output_dir, "options_distality.txt")
    with open(opts_dist, "w") as f:
        f.write("# Delta with distality cost\n")
        f.write("cost-function composite\n")
        f.write("var-data GR DEN\n")
        f.write("var-weight 1.0 0.5\n")
        f.write("dist-on 1\n")
        f.write("order pyramidal\n")
        f.write("nbr-cor 50\n")
        f.write("out-nbr-cor 10\n")
        f.write("max-cor 200\n")

    print(f"Generated {n_wells} wells in {wells_path}")
    return wells_path, opts_path


if __name__ == "__main__":
    parser = ArgumentParser(description="Generate prograding delta dataset")
    parser.add_argument("--n_wells", type=int, default=8)
    parser.add_argument("--n_markers", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output_dir", default=".")
    args = parser.parse_args()
    main(n_wells=args.n_wells, n_markers=args.n_markers,
         seed=args.seed, output_dir=args.output_dir)
