#!/usr/bin/env python3
"""
Generate a synthetic Coal Geology well dataset for WeCo.
=========================================================

Geological setting: Intracratonic coal basin (Carboniferous/Permian
or Cenozoic brown coal). Modelled on the Ruhr Basin (Germany) / Upper
Silesian Basin (Poland) / Bowen Basin (Australia) style cyclothems.

Wells: 30 exploration boreholes, 50-250 m deep, through cyclic
coal-bearing sequences (cyclothems). Goal: seam correlation across
the basin for mine planning and resource estimation.

Cyclothems (repeating cycle, top to bottom):
  1. Marine/lacustrine shale (roof)   -- GR high, RT low, DEN high
  2. Coal seam                        -- GR very low, RT very high, DEN very low
  3. Seat earth / underclay           -- GR medium, RT medium
  4. Sandstone (channel)              -- GR low, RT high, DEN medium
  5. Siltstone (floodplain)           -- GR medium-high, RT medium

Key features:
  - Coal seams 0.3-5 m thick (economic threshold ~0.6 m)
  - Seam splitting: thick seam splits into 2 thinner seams with parting
  - Washout zones: fluvial channel erosion removes seam locally
  - Rider seams: thin coal stringers ~0.3 m above/below main seam
  - Tonstein (volcanic ash): thin clay marker bed within coal (perfect
    isochronous correlation horizon)
  - Marine bands (Goniatitenschicht): thin shale with marine fauna above
    major seams -- excellent basin-wide correlation markers
  - Brandschiefer (burnt shale): thermally altered roof from ancient
    seam fires -- high RT, low DEN, distinctive red/purple colour
  - Ironstone nodules (Toneisenstein): siderite concretions in shale/
    mudstone, producing RT/DEN spikes in clay sequences
  - Rootlet beds (Wurzelboden): seat earths with in-situ root traces
    immediately below coal -- diagnostic of coal-forming paleosol

Logs:
  GR   -- Natural gamma (API):  coal=20, sand=40, silt=70, shale=110
  RT   -- Resistivity (Ohm-m): coal=500+, sand=80, shale=10
  DEN  -- Bulk density (g/cc):  coal=1.3, sand=2.35, shale=2.5
  CAL  -- Caliper (inches):     coal=wash (8-14), stable=6
  SON  -- Sonic slowness (µs/ft): coal=120, sand=60, shale=90
  NEU  -- Neutron porosity (%):  coal=50+, sand=25, shale=40

Reference:
  - Diessel (1992) Coal-Bearing Depositional Systems
  - Thomas (2002) Coal Geology
  - Flores (2014) Coal and Coalbed Gas
  - Hower & Gayer (2002) cyclothem correlation
  - Ward (2016) coal seam correlation using geophysical logs
  - Cairncross (2001) An overview of the Permian coal deposits of SA
  - Strehlau (1990) Facies and genesis of Carboniferous coal seams
  - Juch (1994) Geophysical well logging in coal exploration (Ruhr)
"""

import math
import os
import numpy as np

# ---------------------------------------------------------------------------
#  Lithology definitions
#  ID -> (name, GR_mean, GR_std, RT_mean, RT_std, DEN_mean, DEN_std, CAL_mean)
# ---------------------------------------------------------------------------
LITHOLOGY = {
    1: ("Coal",          20,  8, 500, 200, 1.30, 0.08,  9.0, 120, 15, 55, 8),
    2: ("Tonstein",     140, 20,   8,   3, 2.60, 0.05,  6.2,  80, 10, 35, 5),
    3: ("SeatEarth",     65, 12,  25,  10, 2.40, 0.08,  6.5,  75, 10, 30, 6),
    4: ("Sandstone",     35, 10,  80,  25, 2.35, 0.06,  6.2,  58,  8, 22, 5),
    5: ("Siltstone",     72, 12,  40,  15, 2.55, 0.05,  6.3,  78,  8, 32, 5),
    6: ("Shale",        110, 15,  10,   5, 2.60, 0.06,  6.3,  90, 10, 40, 6),
    7: ("Mudstone",      95, 12,  15,   6, 2.55, 0.05,  6.4,  85,  8, 38, 5),
    8: ("MarineBand",   130, 18,  12,   4, 2.65, 0.04,  6.2,  95, 10, 42, 5),
    9: ("Brandschiefer", 80, 20, 150,  60, 2.20, 0.10,  7.0,  70, 12, 15, 5),
    10:("Ironstone",     45, 10, 100,  40, 3.50, 0.15,  6.1,  55,  8,  8, 3),
}

# Groups for correlation: Coal-bearing (1,2,3) vs Clastic (4,5) vs Marine/other (6,7,8,9,10)
LITH_GROUPS = "1,2,3;4,5;6,7,8,9,10"

# Seam definitions: (name, base_thickness, sigma, p_present, p_split, p_tonstein)
SEAMS = [
    ("Katharina",   3.0, 0.8, 1.00, 0.20, 0.60),   # thick, persistent
    ("Sonnenschein",1.5, 0.5, 0.90, 0.15, 0.30),
    ("Prasident",   2.5, 0.7, 0.95, 0.25, 0.50),
    ("Zollverein",  1.8, 0.5, 0.85, 0.10, 0.20),
    ("Floez_9",     1.2, 0.4, 0.80, 0.05, 0.15),
    ("Floez_10",    0.8, 0.3, 0.70, 0.05, 0.10),
]

SAMPLE_DZ = 0.2  # 20 cm sample spacing (coal needs fine resolution)


def basin_depth_factor(x, y):
    """Basin deepens towards centre (NE corner)."""
    return 1.0 + 0.4 * (x / 5000) + 0.3 * (y / 5000)


def in_channel_belt(x, y, seam_idx):
    """Fluvial channel belt removes seam locally (washout)."""
    # Different channel belt positions for different seams
    cx = 1500 + seam_idx * 800
    cy = 2000 + seam_idx * 500
    dx = x - cx
    dy = y - cy
    return math.sqrt(dx**2 + dy**2) < 600


def generate_cyclothem(rng, seam_idx, x, y, depth_factor):
    """Generate one cyclothem (roof shale -> coal -> seat earth -> sandstone).

    Returns list of (lithology_id, thickness_m).

    Enhanced features:
      - Marine bands (Goniatitenschicht) above major seams
      - Brandschiefer (burnt shale) from ancient seam fires
      - Ironstone nodule horizons (Toneisenstein) in shale
      - Rootlet bed (Wurzelboden) at top of seat earth
    """
    seam_name, base_h, sigma, p_present, p_split, p_tonstein = SEAMS[seam_idx]

    layers = []

    # Roof shale/mudstone (1-8 m)
    roof_h = max(0.5, rng.normal(3.0 * depth_factor, 1.5))
    if rng.random() < 0.6:
        layers.append((6, roof_h))  # shale
    else:
        layers.append((7, roof_h))  # mudstone

    # Ironstone nodule horizon in roof shale (15% of cyclothems)
    if rng.random() < 0.15:
        layers.append((10, max(0.1, rng.normal(0.2, 0.08))))  # 10-30 cm

    # Marine band (Goniatitenschicht) -- excellent correlation marker
    # More likely above major (thick) seams; probability scales with seam index
    p_marine = 0.35 if seam_idx < 2 else 0.15
    if rng.random() < p_marine:
        layers.append((8, max(0.2, rng.normal(0.5, 0.2))))  # 20-80 cm

    # Brandschiefer (burnt shale) -- ancient seam fire thermally alters roof
    # Only where seam is present AND thick; spatially clustered
    p_brand = 0.0
    if seam_idx <= 2 and x < 2500 and y > 2000:
        p_brand = 0.20
    if rng.random() < p_brand:
        layers.append((9, max(0.1, rng.normal(0.3, 0.1))))  # 10-40 cm

    # Coal seam
    if rng.random() < p_present and not in_channel_belt(x, y, seam_idx):
        coal_h = max(0.1, rng.normal(base_h, sigma))

        # Seam splitting
        if rng.random() < p_split and coal_h > 1.0:
            upper_h = coal_h * rng.uniform(0.3, 0.5)
            lower_h = coal_h - upper_h
            parting_h = max(0.1, rng.normal(0.3, 0.15))
            layers.append((1, upper_h))  # upper split
            layers.append((7, parting_h))  # dirt parting
            layers.append((1, lower_h))  # lower split
        else:
            # Tonstein within coal
            if rng.random() < p_tonstein and coal_h > 0.5:
                pos = rng.uniform(0.3, 0.7)  # position within seam
                upper = coal_h * pos
                lower = coal_h * (1 - pos)
                layers.append((1, upper))
                layers.append((2, max(0.04, rng.normal(0.08, 0.03))))  # 2-15 cm
                layers.append((1, lower))
            else:
                layers.append((1, coal_h))

        # Rider seam (thin coal above/below main in 15% of cases)
        if rng.random() < 0.15:
            layers.append((7, max(0.1, rng.normal(0.3, 0.1))))
            layers.append((1, max(0.1, rng.normal(0.3, 0.1))))
    else:
        # Seam absent — washout: sandstone replaces coal
        if in_channel_belt(x, y, seam_idx):
            layers.append((4, max(1.0, rng.normal(3.0, 1.0))))
        else:
            # Thin dirt band where seam would be
            layers.append((7, max(0.1, rng.normal(0.3, 0.15))))

    # Seat earth / rootlet bed (0.3-2 m)
    layers.append((3, max(0.2, rng.normal(0.8, 0.3))))

    # Sandstone (channel/crevasse splay: 0-15 m)
    if rng.random() < 0.5:
        ss_h = max(0.5, rng.normal(4.0 * depth_factor, 2.0))
        layers.append((4, ss_h))

    # Siltstone/mudstone (floodplain: 2-10 m)
    fp_h = max(1.0, rng.normal(5.0 * depth_factor, 2.0))
    if rng.random() < 0.5:
        layers.append((5, fp_h))
    else:
        layers.append((7, fp_h))

    return layers


def generate_well(rng, name, x, y):
    """Generate a complete coal exploration borehole."""
    depth_factor = basin_depth_factor(x, y)

    # Surface cover (alluvium/soil)
    all_layers = [(5, max(0.5, rng.normal(2.0, 1.0)))]

    # Generate cyclothems top to bottom
    seam_present = {}
    for si in range(len(SEAMS)):
        cyclothem = generate_cyclothem(rng, si, x, y, depth_factor)
        all_layers.extend(cyclothem)
        # Track which seams are present
        seam_present[si] = any(lid == 1 for lid, _ in cyclothem)

    # Convert layers to per-sample arrays
    all_lith = []
    all_seam_id = []  # seam index region (0 = non-coal, 1-6 = seam number)
    current_seam = 0
    seam_counter = 0

    for lid, thickness in all_layers:
        n_samples = max(1, int(round(thickness / SAMPLE_DZ)))
        all_lith.extend([lid] * n_samples)
        if lid == 1:  # coal
            seam_counter += 1
            all_seam_id.extend([seam_counter] * n_samples)
        elif lid == 2:  # tonstein (within coal)
            all_seam_id.extend([seam_counter] * n_samples)
        else:
            all_seam_id.extend([0] * n_samples)

    n_total = len(all_lith)
    if n_total < 6:
        all_lith.extend([5] * (6 - n_total))
        all_seam_id.extend([0] * (6 - n_total))
        n_total = 6

    # Generate log values
    gr_shift = rng.normal(0, 3)
    gr_vals, rt_vals, den_vals, cal_vals = [], [], [], []
    son_vals, neu_vals = [], []
    for lid in all_lith:
        _, gr_mu, gr_sig, rt_mu, rt_sig, den_mu, den_sig, cal_base, son_mu, son_sig, neu_mu, neu_sig = LITHOLOGY[lid]
        gr = max(0.0, rng.normal(gr_mu + gr_shift, gr_sig))
        rt = max(1.0, rng.lognormal(math.log(rt_mu), 0.3))
        den = max(1.0, rng.normal(den_mu, den_sig))
        # Caliper: coal often washes out
        cal = cal_base + rng.normal(0, 0.3)
        if lid == 1:
            cal += rng.uniform(0, 3)  # coal breakout
        cal = max(5.5, cal)
        son = max(30.0, rng.normal(son_mu, son_sig))
        neu = min(80.0, max(0.0, rng.normal(neu_mu, neu_sig)))
        gr_vals.append(gr)
        rt_vals.append(rt)
        den_vals.append(den)
        cal_vals.append(cal)
        son_vals.append(son)
        neu_vals.append(neu)

    depth_vals = [i * SAMPLE_DZ for i in range(n_total)]
    total_depth = depth_vals[-1] + SAMPLE_DZ
    lith_data = [float(lid) for lid in all_lith]

    lith_regions = _to_regions(all_lith)
    seam_regions = _to_regions(all_seam_id)

    return {
        "name": name, "n_samples": n_total,
        "x": x, "y": y, "z": 0.0, "h": total_depth,
        "DEPTH": depth_vals, "GR": gr_vals, "RT": rt_vals,
        "DEN": den_vals, "CAL": cal_vals, "SON": son_vals, "NEU": neu_vals,
        "LITH_data": lith_data,
        "lith_regions": lith_regions,
        "seam_regions": seam_regions,
        "seam_present": seam_present,
    }


def _to_regions(seq):
    if not seq:
        return []
    regions = []
    cur = seq[0]
    start = 0
    length = 1
    for i in range(1, len(seq)):
        if seq[i] == cur:
            length += 1
        else:
            regions.append((cur, start, length))
            cur = seq[i]
            start = i
            length = 1
    regions.append((cur, start, length))
    return regions


def write_welllist(wells, filepath):
    with open(filepath, "w") as f:
        f.write("WeCo WellList 2\n")
        f.write(f"{len(wells)}\n")
        for w in wells:
            n = w["n_samples"]
            f.write(f"\n{w['name']}\n")
            f.write(f"{n}\n")
            f.write(f"{w['x']:.5f} {w['y']:.5f} {w['z']:.5f} {w['h']:.5f}\n")
            # Data: DEPTH, GR, RT, DEN, CAL, SON, NEU, LITH
            f.write("8\n")
            for log_name in ("DEPTH", "GR", "RT", "DEN", "CAL", "SON", "NEU"):
                f.write(f"{log_name} {n}\n")
                for v in w[log_name]:
                    f.write(f"{v:.5f}\n")
            f.write(f"LITH {n}\n")
            for v in w["LITH_data"]:
                f.write(f"{v:.5f}\n")
            # Regions: LITH + SEAM
            f.write("2\n")
            f.write(f"LITH {len(w['lith_regions'])}\n")
            for (rid, start, length) in w["lith_regions"]:
                f.write(f"{rid} {start} {length}\n")
            f.write(f"SEAM {len(w['seam_regions'])}\n")
            for (rid, start, length) in w["seam_regions"]:
                f.write(f"{rid} {start} {length}\n")
        f.write("END\n")


def write_options(filepath, opts_dict, comment_lines):
    with open(filepath, "w") as f:
        for line in comment_lines:
            f.write(f"# {line}\n")
        f.write("#\n")
        for k, v in opts_dict.items():
            f.write(f"{k} {v}\n")


def main(seed=2026, n_wells=30, output_dir=None):
    rng = np.random.RandomState(seed)
    if output_dir is None:
        output_dir = os.path.dirname(os.path.abspath(__file__))
    os.makedirs(output_dir, exist_ok=True)

    # 6x5 grid with jitter
    wells = []
    rows, cols = 5, 6
    for ix in range(cols):
        for iy in range(rows):
            x = 500 + 800 * ix + rng.uniform(-150, 150)
            y = 500 + 800 * iy + rng.uniform(-150, 150)
            name = f"CB_{len(wells)+1:03d}"
            w = generate_well(rng, name, x, y)
            wells.append(w)

    write_welllist(wells, os.path.join(output_dir, "wells.txt"))
    write_welllist(wells[:10], os.path.join(output_dir, "wells_10.txt"))

    # Options: coal-optimised
    configs = {
        "options_basic.txt": (
            ["Config: BASIC -- GR+DEN variance for coal seam tracing",
             "Use case: quick seam correlation using two logs",
             "Coal has very low GR and very low density"],
            {"var-data": "GR", "var-weight": "0.5",
             "var-data2": "DEN", "var-weight2": "0.5",
             "order": "position", "max-cor": "50",
             "const-gap-cost": "3.0"}
        ),
        "options_coal.txt": (
            ["Config: COAL -- four logs optimised for coal seam correlation",
             "Use case: seam-by-seam correlation for mine planning",
             "Logs: GR (25%), RT (15%), DEN (35%), SON (15%), NEU (10%)",
             "DEN is the primary coal indicator (1.3 g/cc vs 2.5+ g/cc)",
             "SON (sonic) is very sensitive to coal (120 µs/ft vs 60 for sand)",
             "High gap cost penalises missing seams"],
            {"var-data": "GR", "var-weight": "0.25",
             "var-data2": "RT", "var-weight2": "0.15",
             "var-data3": "DEN", "var-weight3": "0.35",
             "var-data4": "SON", "var-weight4": "0.15",
             "var-data5": "NEU", "var-weight5": "0.10",
             "order": "position", "max-cor": "100",
             "const-gap-cost": "3.0",
             "const-gap-cost-start": "0.0",
             "const-gap-cost-end": "0.3"}
        ),
        "options_seam_constrained.txt": (
            ["Config: SEAM-CONSTRAINED -- DEN+GR with SEAM region constraint",
             "Use case: enforce seam-by-seam matching when seam IDs are known",
             "same-region=SEAM forces coal to correlate with coal",
             "High gap cost for missing seams, low at boundaries"],
            {"var-data": "DEN", "var-weight": "0.5",
             "var-data2": "GR", "var-weight2": "0.3",
             "var-data3": "SON", "var-weight3": "0.2",
             "same-region": "SEAM",
             "order": "position", "max-cor": "100",
             "const-gap-cost": "4.0",
             "const-gap-cost-start": "0.0",
             "const-gap-cost-end": "0.0"}
        ),
    }
    for fname, (comments, opts) in configs.items():
        write_options(os.path.join(output_dir, fname), opts, comments)
    write_options(os.path.join(output_dir, "options.txt"),
                  configs["options_coal.txt"][1],
                  configs["options_coal.txt"][0])

    # Statistics
    depths = [w["h"] for w in wells]
    samples = [w["n_samples"] for w in wells]
    n_coal = sum(1 for w in wells for f in w["LITH_data"] if f == 1.0)
    n_tonstein = sum(1 for w in wells for f in w["LITH_data"] if f == 2.0)
    n_marine = sum(1 for w in wells for f in w["LITH_data"] if f == 8.0)
    n_brand = sum(1 for w in wells for f in w["LITH_data"] if f == 9.0)
    n_iron = sum(1 for w in wells for f in w["LITH_data"] if f == 10.0)
    print(f"Generated {len(wells)} wells in {output_dir}")
    print(f"  Depth range: {min(depths):.1f} - {max(depths):.1f} m")
    print(f"  Samples/well: {min(samples)} - {max(samples)}")
    print(f"  Total samples: {sum(samples)}")
    print(f"  Key lithologies:")
    print(f"    Coal: {n_coal}, Tonstein: {n_tonstein}")
    print(f"    Marine bands: {n_marine}, Brandschiefer: {n_brand}, Ironstone: {n_iron}")
    lith_arr = np.array([f for w in wells for f in w["LITH_data"]], dtype=int)
    for lid in sorted(LITHOLOGY.keys()):
        c = np.sum(lith_arr == lid)
        print(f"    {lid} ({LITHOLOGY[lid][0]:>14s}): {c:5d} ({100*c/len(lith_arr):.1f}%)")

    # Seam presence
    print("  Seam presence:")
    for si, (sname, *_) in enumerate(SEAMS):
        n_present = sum(1 for w in wells if w["seam_present"].get(si, False))
        print(f"    {sname:>12s}: {n_present}/{len(wells)}")

    return wells


# §14.5 — Seam splitting + marine band no_crossing regions

def add_seam_splits(wells, split_probability=0.3, rng=None):
    """
    Add seam splitting: some seams split into two thinner layers.

    Parameters
    ----------
    wells : list
    split_probability : float
        Probability that a seam is split in a given well.
    rng : numpy.random.Generator, optional
    """
    if rng is None:
        rng = np.random.default_rng(42)

    for w in wells:
        split_regions = []
        for si, (sname, *_) in enumerate(SEAMS):
            if not w.get("seam_present", {}).get(si, False):
                continue
            if rng.random() < split_probability:
                # Find seam interval and mark as split
                for region in w.get("SEAM_regions", []):
                    if region[0] == si:
                        mid = region[1] + region[2] // 2
                        split_regions.append((si * 100, mid, 1))
                        break

        w["SPLIT_regions"] = split_regions

    return wells


def add_marine_band_constraints(wells):
    """
    Add marine band intervals as no_crossing region boundaries.

    Marine bands are laterally continuous and provide strong correlation
    markers that should not be crossed by the DTW path.
    """
    for w in wells:
        no_crossing = []
        lith_data = w.get("LITH_data", [])
        # Find marine band intervals (lithology code for marine band)
        for i, lith_id in enumerate(lith_data):
            # Marine band lithology - check LITHOLOGY dict
            if lith_id == 5:  # Marine_band
                no_crossing.append((1, i, 1))

        w["MARINE_BAND_no_crossing"] = no_crossing

    return wells


if __name__ == "__main__":
    main()
