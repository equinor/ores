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
    # Log responses: adjacent facies OVERLAP significantly - this is realistic
    # for deltaic settings where gradational contacts dominate and diagenesis
    # creates additional log variability.
    FACIES = {
        0: {"GR": 125, "GR_std": 15, "DEN": 2.52, "DEN_std": 0.04, "NPHI": 0.34, "NPHI_std": 0.04},
        1: {"GR": 95,  "GR_std": 18, "DEN": 2.46, "DEN_std": 0.05, "NPHI": 0.29, "NPHI_std": 0.04},
        2: {"GR": 62,  "GR_std": 16, "DEN": 2.36, "DEN_std": 0.05, "NPHI": 0.23, "NPHI_std": 0.04},
        3: {"GR": 38,  "GR_std": 14, "DEN": 2.27, "DEN_std": 0.04, "NPHI": 0.17, "NPHI_std": 0.03},
        4: {"GR": 28,  "GR_std": 12, "DEN": 2.21, "DEN_std": 0.04, "NPHI": 0.14, "NPHI_std": 0.03},
        5: {"GR": 108, "GR_std": 16, "DEN": 2.49, "DEN_std": 0.04, "NPHI": 0.31, "NPHI_std": 0.04},
        6: {"GR": 115, "GR_std": 14, "DEN": 2.50, "DEN_std": 0.04, "NPHI": 0.33, "NPHI_std": 0.04},
        7: {"GR": 90,  "GR_std": 18, "DEN": 2.43, "DEN_std": 0.05, "NPHI": 0.27, "NPHI_std": 0.04},
    }

    # Variable parasequence thickness per well - creates "which clinoform
    # ties to which?" ambiguity. Adjacent parasequences look similar in log
    # response (all coarsening-upward) and with variable thickness, the
    # engine must decide if thin sections represent condensation/erosion
    # or simply lateral thinning of a different parasequence.
    n_per_para_base = n_markers // n_parasequences

    wells_data = []

    for j in range(n_wells):
        distality = j / max(n_wells - 1, 1)  # 0=proximal, 1=distal
        x_pos = j * spacing
        y_pos = 0.0

        gr, den, nphi, depth = [], [], [], []
        facies_list = []
        ps_starts = []  # track parasequence start indices

        for ps in range(n_parasequences):
            ps_starts.append(len(depth))
            prograde_shift = ps / max(n_parasequences - 1, 1)
            # Per-well, per-parasequence thickness variation (±30%)
            # Creates genuine "is this the same PS or a different one?" ambiguity
            thickness_factor = 1.0 + rng.uniform(-0.30, 0.30)
            # Distal wells: some PS may be condensed (thin) or absent
            if distality > 0.6 and rng.random() < 0.15:
                thickness_factor *= 0.3  # condensed section
            n_per_para = max(3, int(round(n_per_para_base * thickness_factor)))

            for k in range(n_per_para):
                m = len(depth)
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
                gr.append(props["GR"] + np_rng.normal(0, props["GR_std"]))
                den.append(props["DEN"] + np_rng.normal(0, props["DEN_std"]))
                nphi.append(props["NPHI"] + np_rng.normal(0, props["NPHI_std"]))

        n_actual = len(depth)

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

        # SEQSTRAT region: one zone per parasequence (boundaries = sequence boundaries)
        # These are the KEY geological surfaces a geologist would pick first.
        seqstrat_intervals = []
        for si in range(len(ps_starts)):
            start = ps_starts[si]
            end = ps_starts[si + 1] if si + 1 < len(ps_starts) else n_actual
            if end > start:
                seqstrat_intervals.append((si, start, end - start))

        wells_data.append({
            "name": f"W{j}", "n": n_actual,
            "x": x_pos, "y": y_pos, "z": 0.0, "h": 1.0,
            "depth": depth, "GR": gr, "DEN": den, "NPHI": nphi,
            "facies_intervals": intervals,
            "seqstrat_intervals": seqstrat_intervals,
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
            # 4 data columns: DEPTH, GR, DEN, NPHI
            f.write("4\n")
            f.write(f"DEPTH {n}\n")
            for v in w["depth"]:
                f.write(f"{v:.5f}\n")
            f.write(f"GR {n}\n")
            for v in w["GR"]:
                f.write(f"{v:.5f}\n")
            f.write(f"DEN {n}\n")
            for v in w["DEN"]:
                f.write(f"{v:.5f}\n")
            f.write(f"NPHI {n}\n")
            for v in w["NPHI"]:
                f.write(f"{v:.5f}\n")
            # 2 regions: facies + SEQSTRAT
            f.write("2\n")
            f.write(f"FACIES {len(w['facies_intervals'])}\n")
            for rid, rstart, rlen in w["facies_intervals"]:
                f.write(f"{rid} {rstart} {rlen}\n")
            f.write(f"SEQSTRAT {len(w['seqstrat_intervals'])}\n")
            for rid, rstart, rlen in w["seqstrat_intervals"]:
                f.write(f"{rid} {rstart} {rlen}\n")
        f.write("END\n")

    # Options file - use no_crossing to force boundaries at sequence boundaries
    opts_path = os.path.join(output_dir, "options.txt")
    with open(opts_path, "w") as f:
        f.write("# Prograding delta correlation options\n")
        f.write("# no-crossing SEQSTRAT ensures key parasequence boundaries\n")
        f.write("# are honoured - the most geologically important surfaces.\n")
        f.write("cost-function=composite\n")
        f.write("var-data=GR\n")
        f.write("var-weight=0.6\n")
        f.write("var-data2=DEN\n")
        f.write("var-weight2=0.4\n")
        f.write("order=pyramidal\n")
        f.write("nbr-cor=50\n")
        f.write("out-nbr-cor=5\n")
        f.write("max-cor=200\n")
        f.write("no-crossing=SEQSTRAT\n")
        f.write("const-gap-cost=1.0\n")
        f.write("min-dist=0.3\n")
        f.write("out-min-dist=0.1\n")

    # Distality options
    opts_dist = os.path.join(output_dir, "options_distality.txt")
    with open(opts_dist, "w") as f:
        f.write("# Delta with distality cost + sequence boundary constraints\n")
        f.write("cost-function=composite\n")
        f.write("var-data=GR\n")
        f.write("var-weight=0.6\n")
        f.write("var-data2=DEN\n")
        f.write("var-weight2=0.4\n")
        f.write("dist-on=1\n")
        f.write("order=pyramidal\n")
        f.write("nbr-cor=50\n")
        f.write("out-nbr-cor=5\n")
        f.write("max-cor=200\n")
        f.write("no-crossing=SEQSTRAT\n")
        f.write("const-gap-cost=1.0\n")
        f.write("min-dist=0.3\n")
        f.write("out-min-dist=0.1\n")

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
    parser = ArgumentParser(description="Generate prograding delta dataset")
    parser.add_argument("--n_wells", type=int, default=8)
    parser.add_argument("--n_markers", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output_dir", default=".")
    args = parser.parse_args()
    main(n_wells=args.n_wells, n_markers=args.n_markers,
         seed=args.seed, output_dir=args.output_dir)
