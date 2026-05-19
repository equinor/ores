#!/usr/bin/env python3
"""
Generate a synthetic Quaternary hydrogeological well dataset for WeCo.
=====================================================================

Geological setting: Northern European glacial lowland (Pleistocene).
100 shallow wells (10-60 m) through 5 lithostratigraphic units in
glacial/interglacial deposits -- for aquifer/aquitard mapping.

Units (top -> bottom):
  U1  Holocene cover (peat, clay, sand)
  U2  Weichselian till / outwash
  U3  Eemian interglacial (clay, peat) -- often missing
  U4  Saalian till / outwash sand
  U5  Elsterian deposits / tunnel-valley fill

Facies:
  1=Gravel  2=Sand  3=SiltySand  4=Till  5=Clay  6=Peat
  7=IceWedge  8=Cryoturbate  9=Dropstone

Logs:
  GR   -- Natural gamma ray (API)              -> lithology proxy
  RT   -- Resistivity (Ohm-m)                  -> porosity/permeability proxy
  SPT  -- Standard Penetration Test (blows/30cm)-> geotechnical hardness
  COND -- Hydraulic conductivity estimate (m/s) -> hydrogeological target
  MS   -- Magnetic susceptibility (SI×1e-5)     -> provenance/till indicator
  WC   -- Water content (% by weight)           -> geotechnical parameter

Periglacial features:
  - Eiskeil (ice-wedge casts) in U2/U4 till: vertical gravel/sand-filled
    fractures 1-3 m deep, producing anomalous GR lows and high RT/COND
    spikes in otherwise uniform till.  Common in permafrost zone (y>3000).
  - Cryoturbation (Kryoturbation): frost-heave mixing of sediment layers,
    producing disturbed zones 0.5-2 m thick with mixed facies signatures.
    Recognised by erratic GR/RT fluctuations in otherwise uniform till.
  - Dropstones (Geschiebe): isolated boulders/cobbles in fine sediment,
    producing single-sample GR lows and RT/SPT spikes in clay/silt.
  - Frost cracks (Frostspalten): thin vertical fractures filled with sand,
    smaller than Eiskeil, 0.3-1 m deep.

Reference:
  - TNO/DINO borehole database (Netherlands)
  - GEUS Jupiter database (Denmark)
  - Ehlers & Gibbard (2004) Quaternary Glaciations
  - Keys (1990) Borehole Geophysics Applied to Groundwater Investigations
  - Vandenberghe (2003) Ice-wedge casts in Weichselian deposits
  - Van Vliet-Lanoë (2010) Frost action in soils
  - Murton & French (1994) Cryostructures and ice-bonded permafrost
  - Ehlers et al. (2011) Quaternary Glaciations – extent and chronology
"""

import math
import os
import numpy as np

# ---------------------------------------------------------------------------
#  Facies definitions
#  ID -> (name, GR_mean, GR_std, RT_mean, RT_std, SPT_mean, SPT_std, logK)
#  logK = log10(hydraulic conductivity in m/s)
# ---------------------------------------------------------------------------
# ID -> (name, GR_mean, GR_std, RT_mean, RT_std, SPT_mean, SPT_std, logK, MS_mean, MS_std, WC_mean, WC_std)
FACIES = {
    1: ("Gravel",      20,  5, 150, 60, 55, 15, -1.5,  15,  8, 5, 2),
    2: ("Sand",        38, 10,  90, 30, 25, 10, -3.5,  25, 10, 12, 4),
    3: ("SiltySand",   58, 10,  50, 18, 15,  6, -5.0,  40, 12, 18, 5),
    4: ("Till",        95, 15,  30, 12, 42, 12, -7.0, 120, 30, 22, 6),
    5: ("Clay",       115, 12,  15,  8,  5,  3, -8.5,  50, 15, 35, 8),
    6: ("Peat",        22,  8,  12,  5,  2,  1, -5.5,  10,  5, 80, 15),
    7: ("IceWedge",    25,  8, 120, 40, 35, 10, -2.0,  20,  8, 8, 3),
    8: ("Cryoturbate", 70, 25,  45, 20, 30, 15, -5.5,  80, 35, 25, 10),
    9: ("Dropstone",   30, 12, 200, 80, 60, 20, -3.0,  60, 25, 10, 4),
}

FACIES_GROUPS = "1,2,7;3,8,9;4,5,6"

UNITS = {
    1: ("Holocene",     2.0, 1.5, 0,  5, 0.20),
    2: ("Weichselian", 15.0, 5.0, 5, 25, 0.00),
    3: ("Eemian",       4.0, 2.5, 0,  8, 0.30),
    4: ("Saalian",     12.0, 4.0, 3, 20, 0.05),
    5: ("Elsterian",    8.0, 3.0, 0, 30, 0.15),
}

SAMPLE_DZ = 0.5


def surface_elevation(x, y):
    return (25
            + 10 * math.sin(2 * math.pi * x / 4000)
                 * math.cos(2 * math.pi * y / 5000)
            + 5 * math.sin(2 * math.pi * (x + y) / 3000))


def tunnel_valley_depth(x, y):
    a, b, c = 0.6, -1.0, 1000.0
    d = abs(a * x + b * y + c) / math.sqrt(a**2 + b**2)
    return 20 * math.exp(-d**2 / (2 * 200**2))


def in_moraine_zone(x, y):
    return 2000 < x < 3500 and 1500 < y < 4000


def in_outwash_fan(x, y):
    dx = x - 3500
    dy = y - 1500
    return math.sqrt(dx**2 + dy**2) < 2000


def in_permafrost_zone(x, y):
    return y > 3000


def generate_unit_thickness(rng, unit_id, x, y, z_surf):
    name, base_h, sigma, h_min, h_max, p_missing = UNITS[unit_id]
    if unit_id == 1 and z_surf > 40:
        return 0.0
    if unit_id == 3 and z_surf > 35:
        return 0.0
    if rng.random() < p_missing:
        return 0.0
    h = base_h + rng.normal(0, sigma)
    if unit_id == 5:
        tv = tunnel_valley_depth(x, y)
        if tv > 5:
            h = 25 + rng.normal(0, 5)
        else:
            h = max(h, 3)
    if unit_id == 2 and in_moraine_zone(x, y):
        h += 3
    if unit_id == 4 and in_outwash_fan(x, y):
        h += 4
    return float(np.clip(h, h_min, h_max))


def _insert_ice_wedge(rng, seq, n_samples, x, y):
    """Insert Eiskeil (ice-wedge cast) features into till-dominated sequences.

    Ice-wedge casts (Eiskeil) are the most diagnostic periglacial feature
    in Quaternary boreholes.  They appear as vertical gravel/sand-filled
    fracture networks in till, producing sharp GR lows and RT/COND spikes.
    Typical dimensions: 1-3 m deep, 0.1-0.5 m wide, polygonal spacing
    10-30 m (so a borehole may or may not intersect one).
    """
    if not in_permafrost_zone(x, y):
        return seq
    if n_samples < 8:
        return seq
    n_wedges = 0
    if rng.random() < 0.30:
        n_wedges = 1
    if rng.random() < 0.10:
        n_wedges = 2
    for _ in range(n_wedges):
        wedge_len = rng.randint(2, min(7, n_samples // 3))
        wedge_start = rng.randint(1, max(2, n_samples // 2))
        for k in range(wedge_start, min(wedge_start + wedge_len, n_samples)):
            seq[k] = 7
    return seq


def _insert_cryoturbation(rng, seq, n_samples, x, y):
    """Insert cryoturbation (Kryoturbation) zones into near-surface sequences.

    Cryoturbation produces chaotic mixing of lithologies in the active layer
    (uppermost 1-3 m subject to seasonal freeze/thaw).  In boreholes it
    appears as disturbed zones with erratic log responses -- mixed till,
    sand, and silt producing intermediate/fluctuating GR values.
    """
    if not in_permafrost_zone(x, y):
        return seq
    if n_samples < 4:
        return seq
    if rng.random() < 0.25:  # 25% of permafrost-zone wells
        cryo_len = rng.randint(2, min(5, n_samples // 2))
        # Always at top of unit (active layer)
        for k in range(min(cryo_len, n_samples)):
            seq[k] = 8  # Cryoturbate
    return seq


def _insert_dropstones(rng, seq, n_samples, x, y):
    """Insert dropstones (Geschiebe) into fine-grained sequences.

    Dropstones are isolated erratics (boulders, cobbles) released from
    floating ice into fine lacustrine/marine sediment.  In a borehole
    they produce single-sample anomalies: sudden GR drop and RT/SPT spike
    in otherwise uniform clay or silt.
    """
    if n_samples < 6:
        return seq
    # Only in fine-grained sequences
    fine_indices = [i for i in range(n_samples) if seq[i] in (5, 3)]  # clay, silty sand
    if not fine_indices or rng.random() > 0.15:  # 15% of suitable wells
        return seq
    n_drops = rng.randint(1, max(2, min(4, len(fine_indices))))
    chosen = rng.choice(fine_indices, size=min(n_drops, len(fine_indices)), replace=False)
    for idx in chosen:
        seq[idx] = 9  # Dropstone
    return seq


def _insert_frost_cracks(rng, seq, n_samples, x, y):
    """Insert small frost cracks (Frostspalten) -- thinner than Eiskeil.

    Frost cracks are narrow (cm-scale) vertical fractures filled with sand,
    typically 0.3-1 m deep.  They produce brief GR anomalies (1-2 samples)
    but are less dramatic than ice-wedge casts.
    """
    if not in_permafrost_zone(x, y):
        return seq
    if n_samples < 6 or rng.random() > 0.20:
        return seq
    n_cracks = rng.randint(1, 3)
    for _ in range(n_cracks):
        pos = rng.randint(0, n_samples - 1)
        if seq[pos] in (4, 5):  # only in cohesive sediments
            seq[pos] = 7  # Same log signature as small ice wedge
    return seq


def generate_facies_sequence(rng, unit_id, n_samples, x, y):
    if n_samples <= 0:
        return []
    if unit_id == 1:
        seq = []
        for i in range(n_samples):
            frac = i / max(n_samples - 1, 1)
            if frac < 0.3:
                seq.append(6)
            elif frac < 0.7:
                seq.append(5)
            else:
                seq.append(rng.choice([2, 3]))
        return seq
    if unit_id == 2:
        if in_moraine_zone(x, y):
            seq = [4] * n_samples
            if n_samples > 6 and rng.random() < 0.25:
                ch_len = min(rng.randint(4, 10), n_samples - 2)
                ch_start = rng.randint(1, max(1, n_samples - ch_len - 1))
                for k in range(ch_start, ch_start + ch_len):
                    seq[k] = 2
            seq = _insert_ice_wedge(rng, seq, n_samples, x, y)
            seq = _insert_cryoturbation(rng, seq, n_samples, x, y)
            seq = _insert_frost_cracks(rng, seq, n_samples, x, y)
            return seq
        else:
            seq = []
            for i in range(n_samples):
                frac = i / max(n_samples - 1, 1)
                if frac < 0.3:
                    seq.append(rng.choice([3, 4]))
                elif frac < 0.6:
                    seq.append(2)
                else:
                    seq.append(rng.choice([1, 2]))
            return seq
    if unit_id == 3:
        seq = []
        for i in range(n_samples):
            frac = i / max(n_samples - 1, 1)
            if frac < 0.2:
                seq.append(6)
            elif frac < 0.7:
                seq.append(5)
            else:
                seq.append(rng.choice([2, 3]))
        return seq
    if unit_id == 4:
        if in_outwash_fan(x, y):
            seq = []
            for i in range(n_samples):
                frac = i / max(n_samples - 1, 1)
                if frac < 0.2:
                    seq.append(rng.choice([3, 4]))
                else:
                    seq.append(rng.choice([1, 2]))
            return seq
        else:
            seq = []
            for i in range(n_samples):
                frac = i / max(n_samples - 1, 1)
                if frac < 0.7:
                    seq.append(4)
                else:
                    seq.append(rng.choice([2, 3]))
            seq = _insert_ice_wedge(rng, seq, n_samples, x, y)
            seq = _insert_cryoturbation(rng, seq, n_samples, x, y)
            seq = _insert_dropstones(rng, seq, n_samples, x, y)
            return seq
    if unit_id == 5:
        tv = tunnel_valley_depth(x, y)
        if tv > 5:
            return [rng.choice([1, 1, 2]) for _ in range(n_samples)]
        else:
            return [rng.choice([4, 5]) for _ in range(n_samples)]
    return [4] * n_samples


def generate_log_values(rng, facies_seq, gr_shift=0.0, rt_shift=1.0):
    gr_vals, rt_vals, spt_vals, cond_vals = [], [], [], []
    ms_vals, wc_vals = [], []
    for fid in facies_seq:
        _, gr_mu, gr_sig, rt_mu, rt_sig, spt_mu, spt_sig, logK, ms_mu, ms_sig, wc_mu, wc_sig = FACIES[fid]
        gr = max(0.0, rng.normal(gr_mu + gr_shift, gr_sig))
        rt = max(1.0, rng.normal(rt_mu * rt_shift, rt_sig))
        spt = max(0.0, rng.normal(spt_mu, spt_sig))
        cond = 10 ** (logK + rng.normal(0, 0.3))
        ms = max(0.0, rng.normal(ms_mu, ms_sig))
        wc = min(100.0, max(0.0, rng.normal(wc_mu, wc_sig)))
        gr_vals.append(gr)
        rt_vals.append(rt)
        spt_vals.append(spt)
        cond_vals.append(cond)
        ms_vals.append(ms)
        wc_vals.append(wc)
    return gr_vals, rt_vals, spt_vals, cond_vals, ms_vals, wc_vals


def facies_to_regions(facies_seq):
    if not facies_seq:
        return []
    regions = []
    cur_id = facies_seq[0]
    cur_start = 0
    cur_len = 1
    for i in range(1, len(facies_seq)):
        if facies_seq[i] == cur_id:
            cur_len += 1
        else:
            regions.append((cur_id, cur_start, cur_len))
            cur_id = facies_seq[i]
            cur_start = i
            cur_len = 1
    regions.append((cur_id, cur_start, cur_len))
    return regions


def hydro_regions(facies_seq):
    mapping = {1: 1, 2: 1, 7: 1, 9: 1, 3: 2, 8: 2, 4: 3, 5: 3, 6: 3}
    hydro_seq = [mapping.get(f, 3) for f in facies_seq]
    return facies_to_regions(hydro_seq)


def generate_well(rng, name, x, y):
    z_surf = surface_elevation(x, y)
    unit_thicknesses = {}
    for uid in range(1, 6):
        unit_thicknesses[uid] = generate_unit_thickness(rng, uid, x, y, z_surf)
    total_depth_m = sum(unit_thicknesses.values())
    if total_depth_m < 3:
        total_depth_m = 3
    all_facies = []
    all_units = []
    for uid in range(1, 6):
        h = unit_thicknesses[uid]
        n_unit = int(round(h / SAMPLE_DZ))
        if n_unit <= 0:
            continue
        facies_seq = generate_facies_sequence(rng, uid, n_unit, x, y)
        for k in range(len(facies_seq)):
            if rng.random() < 0.08:
                fid = facies_seq[k]
                if fid == 1:
                    facies_seq[k] = 2
                elif fid in (6, 7, 8, 9):
                    pass  # Don't perturb special facies
                else:
                    new_fid = fid + rng.choice([-1, 1])
                    if new_fid in FACIES:
                        facies_seq[k] = new_fid
        all_facies.extend(facies_seq)
        all_units.extend([uid] * n_unit)
    n_total = len(all_facies)
    if n_total < 6:
        all_facies.extend([4] * (6 - n_total))
        all_units.extend([2] * (6 - n_total))
        n_total = 6
    gr_shift = rng.normal(0, 5)
    rt_shift = max(0.5, rng.normal(1.0, 0.1))
    gr_vals, rt_vals, spt_vals, cond_vals, ms_vals, wc_vals = generate_log_values(
        rng, all_facies, gr_shift, rt_shift)
    depth_vals = [i * SAMPLE_DZ for i in range(n_total)]
    total_depth = depth_vals[-1] + SAMPLE_DZ
    facies_data = [float(f) for f in all_facies]
    facies_regions = facies_to_regions(all_facies)
    strat_regions = facies_to_regions(all_units)
    hydro_regs = hydro_regions(all_facies)
    return {
        "name": name, "n_samples": n_total,
        "x": x, "y": y, "z": z_surf, "h": total_depth,
        "DEPTH": depth_vals, "GR": gr_vals, "RT": rt_vals,
        "SPT": spt_vals, "COND": cond_vals, "MS": ms_vals, "WC": wc_vals,
        "FACIES_data": facies_data,
        "facies_regions": facies_regions,
        "strat_regions": strat_regions,
        "hydro_regions": hydro_regs,
        "unit_thicknesses": unit_thicknesses,
    }


def write_welllist(wells, filepath):
    with open(filepath, "w") as f:
        f.write("WeCo WellList 2\n")
        f.write(f"{len(wells)}\n")
        for w in wells:
            n = w["n_samples"]
            f.write(f"\n{w['name']}\n")
            f.write(f"{n}\n")
            f.write(f"{w['x']:.5f} {w['y']:.5f} {w['z']:.5f} {w['h']:.5f}\n")
            f.write("8\n")
            for log_name in ("DEPTH", "GR", "RT", "SPT", "COND", "MS", "WC"):
                f.write(f"{log_name} {n}\n")
                for v in w[log_name]:
                    f.write(f"{v:.5f}\n")
            f.write(f"FACIES {n}\n")
            for v in w["FACIES_data"]:
                f.write(f"{v:.5f}\n")
            f.write("3\n")
            f.write(f"FACIES {len(w['facies_regions'])}\n")
            for (rid, start, length) in w["facies_regions"]:
                f.write(f"{rid} {start} {length}\n")
            f.write(f"STRAT {len(w['strat_regions'])}\n")
            for (rid, start, length) in w["strat_regions"]:
                f.write(f"{rid} {start} {length}\n")
            f.write(f"HYDRO {len(w['hydro_regions'])}\n")
            for (rid, start, length) in w["hydro_regions"]:
                f.write(f"{rid} {start} {length}\n")
        f.write("END\n")


def write_options(filepath, opts_dict, comment_lines):
    with open(filepath, "w") as f:
        for line in comment_lines:
            f.write(f"# {line}\n")
        f.write("#\n")
        for k, v in opts_dict.items():
            f.write(f"{k} {v}\n")


def main(seed=2026, n_grid=10, output_dir=None):
    rng = np.random.RandomState(seed)
    if output_dir is None:
        output_dir = os.path.dirname(os.path.abspath(__file__))
    os.makedirs(output_dir, exist_ok=True)
    wells = []
    well_idx = 0
    for ix in range(n_grid):
        for iy in range(n_grid):
            x = 250 + 500 * ix + rng.uniform(-100, 100)
            y = 250 + 500 * iy + rng.uniform(-100, 100)
            name = f"QW_{well_idx + 1:03d}"
            w = generate_well(rng, name, x, y)
            wells.append(w)
            well_idx += 1
    n_wells = len(wells)
    write_welllist(wells, os.path.join(output_dir, "wells.txt"))
    write_welllist(wells[:20], os.path.join(output_dir, "wells_20.txt"))

    configs = {
        "options_basic.txt": (
            ["Config: BASIC -- GR+RT variance only (fastest, no constraints)",
             "Use case: quick overview, first-pass aquifer mapping",
             "Logs: GR (70%), RT (30%)"],
            {"var-data": "GR", "var-weight": "0.7",
             "var-data2": "RT", "var-weight2": "0.3",
             "order": "position", "max-cor": "50",
             "const-gap-cost": "1.5"}
        ),
        "options_hydro.txt": (
            ["Config: HYDRO -- three logs + gap cost for aquifer mapping",
             "Use case: hydrogeological aquifer/aquitard bed tracing",
             "Logs: GR (50%), RT (25%), SPT (25%)  +  gap cost"],
            {"var-data": "GR", "var-weight": "0.50",
             "var-data2": "RT", "var-weight2": "0.25",
             "var-data3": "SPT", "var-weight3": "0.25",
             "order": "position", "max-cor": "80",
             "const-gap-cost": "2.0",
             "const-gap-cost-start": "0.0",
             "const-gap-cost-end": "0.5"}
        ),
        "options_constrained.txt": (
            ["Config: CONSTRAINED -- GR+RT + HYDRO region as same-region",
             "Use case: enforce aquifer/aquitard grouping",
             "NB: same-region requires matching HYDRO IDs across wells.",
             "     This works because HYDRO has only 3 broad classes."],
            {"var-data": "GR", "var-weight": "0.50",
             "var-data2": "RT", "var-weight2": "0.30",
             "var-data3": "SPT", "var-weight3": "0.20",
             "same-region": "HYDRO",
             "order": "position", "max-cor": "80",
             "const-gap-cost": "2.0"}
        ),
    }
    for fname, (comments, opts) in configs.items():
        write_options(os.path.join(output_dir, fname), opts, comments)
    write_options(os.path.join(output_dir, "options.txt"),
                  configs["options_hydro.txt"][1],
                  configs["options_hydro.txt"][0])

    depths = [w["h"] for w in wells]
    samples = [w["n_samples"] for w in wells]
    n_ice = sum(1 for w in wells for f in w["FACIES_data"] if f == 7.0)
    n_cryo = sum(1 for w in wells for f in w["FACIES_data"] if f == 8.0)
    n_drop = sum(1 for w in wells for f in w["FACIES_data"] if f == 9.0)
    print(f"Generated {n_wells} wells in {output_dir}")
    print(f"  Depth range: {min(depths):.1f} - {max(depths):.1f} m  (median {np.median(depths):.1f})")
    print(f"  Samples/well: {min(samples)} - {max(samples)}  (median {int(np.median(samples))})")
    print(f"  Total samples: {sum(samples)}")
    print(f"  Periglacial features:")
    print(f"    Eiskeil (ice-wedge) samples: {n_ice}")
    print(f"    Cryoturbation samples:       {n_cryo}")
    print(f"    Dropstone samples:           {n_drop}")
    facies_arr = np.array([f for w in wells for f in w["FACIES_data"]], dtype=int)
    print("  Facies distribution:")
    for fid in sorted(FACIES.keys()):
        count = np.sum(facies_arr == fid)
        pct = 100 * count / len(facies_arr)
        print(f"    {fid} ({FACIES[fid][0]:>10s}): {count:5d} ({pct:5.1f}%)")
    missing = {uid: 0 for uid in range(1, 6)}
    for w in wells:
        for uid in range(1, 6):
            if w["unit_thicknesses"][uid] == 0:
                missing[uid] += 1
    print("  Unit presence:")
    for uid in range(1, 6):
        pct_present = 100 * (n_wells - missing[uid]) / n_wells
        print(f"    U{uid} ({UNITS[uid][0]:>12s}): {n_wells - missing[uid]:3d}/{n_wells} ({pct_present:.0f}%)")
    return wells


# §14.4 — Explicit 3-aquifer zonation and pump-test constraints
AQUIFER_ZONES = {
    1: {"name": "Upper_Sand", "unit": 1, "kh_range": (5.0, 50.0)},
    2: {"name": "Middle_Gravel", "unit": 3, "kh_range": (50.0, 500.0)},
    3: {"name": "Lower_Sand", "unit": 5, "kh_range": (10.0, 100.0)},
}


def add_aquifer_zonation(wells, rng=None):
    """Add explicit aquifer zone region and pump-test derived properties."""
    if rng is None:
        rng = np.random.default_rng(42)

    for w in wells:
        aquifer_regions = []
        pump_test_kh = []
        n = len(w["Depth"])
        kh_log = [0.0] * n

        for aq_id, aq_info in AQUIFER_ZONES.items():
            unit_id = aq_info["unit"]
            kh_min, kh_max = aq_info["kh_range"]

            # Find samples belonging to this aquifer unit
            for i in range(n):
                if w.get("UNIT_data") and i < len(w["UNIT_data"]):
                    if w["UNIT_data"][i] == unit_id:
                        kh_log[i] = rng.uniform(kh_min, kh_max)
                        if not aquifer_regions or aquifer_regions[-1][0] != aq_id:
                            aquifer_regions.append((aq_id, i, 1))
                        else:
                            prev = aquifer_regions[-1]
                            aquifer_regions[-1] = (prev[0], prev[1], i - prev[1] + 1)

        w["AQUIFER_regions"] = aquifer_regions
        w["KH_data"] = kh_log
        # Pump-test constraint: wells in same aquifer should connect
        w["pump_test_connected"] = True  # flag for production data cost

    return wells


if __name__ == "__main__":
    main()
