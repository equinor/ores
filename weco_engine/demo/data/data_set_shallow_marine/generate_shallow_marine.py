#!/usr/bin/env python3
"""
Generate a synthetic shallow marine dataset for WeCo.
=====================================================

Geological setting: Hugin Formation analogue (Upper Jurassic, North Sea).
Prograding wave-dominated shoreface / bay-fill system with 10 wells along
depositional dip, producing clinoform geometry with lateral facies change.

Parasequences:
  PS1  Lower shoreface (distal) → upper shoreface (proximal)
  PS2  Bay-fill (muddy) → tidal channel (sandy)
  PS3  Upper shoreface → foreshore
  PS4  Transgressive lag → offshore transition
  PS5  Upper shoreface → foreshore (progradational cap)

Facies (8):
  1=Offshore mud       2=Offshore transition   3=Lower shoreface
  4=Upper shoreface    5=Foreshore             6=Bay-fill mud
  7=Tidal channel      8=Transgressive lag

Logs:
  GR   — Natural gamma ray (API)     → lithology proxy
  RT   — Resistivity (Ohm-m)         → permeability indicator
  RHOB — Bulk density (g/cc)         → porosity proxy
  NPHI — Neutron porosity (v/v)      → porosity proxy
  DT   — Sonic transit time (µs/ft)  → compaction indicator

Geometry:
  Wells are spaced along dip (Y axis). Beds thicken downdip due to
  clinoform progradation. Each parasequence has a known thickness profile
  per well, defining the ground-truth correlation.

Biozones:
  BZ1 (base PS2), BZ2 (base PS4) — two biostratigraphic markers that
  can be used as no_crossing constraints.

Reference:
  - Baville (2022) PhD Thesis, §6 (Hugin Formation case study)
  - Kieft et al. (2010) Hugin Formation sedimentology
  - Ainsworth (2005) Sequence stratigraphy of shoreline regression
  - Catuneanu (2006) Principles of Sequence Stratigraphy
"""

import math
import os
import numpy as np

# ---------------------------------------------------------------------------
# Facies definitions: ID -> (name, GR, GR_std, RT, RT_std, RHOB, RHOB_std,
#                            NPHI, NPHI_std, DT, DT_std)
# ---------------------------------------------------------------------------
FACIES = {
    1: ("OffshoreMud",    120, 12, 1.5, 0.4, 2.45, 0.03, 0.32, 0.03, 95, 8),
    2: ("OffshoreTransit",  90, 15, 3.0, 0.8, 2.40, 0.04, 0.28, 0.03, 85, 7),
    3: ("LowerShoreface",   65, 12, 8.0, 2.0, 2.30, 0.04, 0.22, 0.03, 75, 6),
    4: ("UpperShoreface",   40, 10, 15., 4.0, 2.20, 0.03, 0.18, 0.02, 68, 5),
    5: ("Foreshore",        25,  8, 25., 6.0, 2.15, 0.03, 0.14, 0.02, 62, 4),
    6: ("BayFillMud",      110, 15, 2.0, 0.5, 2.50, 0.04, 0.35, 0.04, 98, 9),
    7: ("TidalChannel",     35, 10, 12., 3.0, 2.22, 0.04, 0.20, 0.03, 70, 6),
    8: ("TransgressiveLag", 45, 12, 20., 5.0, 2.55, 0.05, 0.12, 0.03, 60, 5),
}

# Lateral equivalence groups for distality cost
FACIES_GROUPS = "1,6;2,8;3,7;4,5"

# ---------------------------------------------------------------------------
# Parasequence stacking: (name, base_thickness, facies_profile_proximal,
#                          facies_profile_distal, thickening_rate)
# facies_profile = list of (facies_id, fraction) from base to top
# thickening_rate = fractional increase per well step downdip
# ---------------------------------------------------------------------------
PARASEQUENCES = [
    ("PS1", 8.0,
     [(3, 0.4), (4, 0.4), (5, 0.2)],                # proximal: shoreface
     [(1, 0.3), (2, 0.4), (3, 0.3)],                 # distal: offshore
     0.15),
    ("PS2", 6.0,
     [(7, 0.5), (4, 0.3), (5, 0.2)],                 # proximal: tidal→shore
     [(6, 0.5), (2, 0.3), (3, 0.2)],                  # distal: bay fill
     0.10),
    ("PS3", 10.0,
     [(3, 0.2), (4, 0.5), (5, 0.3)],                 # proximal: upper shore
     [(2, 0.3), (3, 0.4), (4, 0.3)],                  # distal: lower shore
     0.20),
    ("PS4", 3.0,
     [(8, 0.3), (2, 0.4), (3, 0.3)],                 # proximal: lag→offshore
     [(8, 0.1), (1, 0.5), (2, 0.4)],                  # distal: offshore
     0.05),
    ("PS5", 9.0,
     [(3, 0.15), (4, 0.45), (5, 0.4)],               # proximal: prograding
     [(2, 0.2), (3, 0.4), (4, 0.4)],                  # distal: lower shore
     0.18),
]

# Biozone boundaries (between parasequences, 0-indexed)
BIOZONES = {
    "BZ1": 1,   # base of PS2
    "BZ2": 3,   # base of PS4
}


def _interp_profile(proximal, distal, t):
    """Interpolate facies profile between proximal (t=0) and distal (t=1).

    Each layer blends the proximal and distal facies fractions, and
    selects the facies ID probabilistically based on t — producing
    a gradual lateral facies change instead of an abrupt switch.
    """
    result = []
    for (fp, fracp), (fd, fracd) in zip(proximal, distal):
        frac = fracp * (1 - t) + fracd * t
        # Pick facies probabilistically: weight toward proximal at low t
        fid = fp if t < 0.5 else fd
        result.append((fp, fd, frac, t))
    return result


def _sample_facies(rng, profile, n_samples):
    """Generate a facies sequence from a blended profile.

    Each profile entry is (facies_proximal, facies_distal, fraction, t).
    Within each entry, individual samples randomly pick between proximal
    and distal facies based on t, producing heterogeneity.
    """
    seq = []
    for fp, fd, frac, t in profile:
        count = max(1, int(round(frac * n_samples)))
        for _ in range(count):
            # Probabilistic facies assignment based on dip position
            seq.append(fd if rng.random() < t else fp)
    # Trim or pad to n_samples
    if len(seq) > n_samples:
        seq = seq[:n_samples]
    while len(seq) < n_samples:
        seq.append(seq[-1] if seq else 1)
    return seq


def _log_from_facies(rng, facies_seq, log_idx, trend_sign=0.0):
    """Generate a log curve from facies sequence with vertical trend.

    log_idx: 0=GR, 1=RT, 2=RHOB, 3=NPHI, 4=DT
    trend_sign: applied as a linear gradient within each run of the
        same facies (>0 = upward-increasing, <0 = upward-decreasing).
        For shoreface PS: GR gets trend_sign=-1 (upward-coarsening),
        RT gets +1 (upward-cleaning).
    """
    n = len(facies_seq)
    values = []
    # Identify facies runs for trend application
    i = 0
    while i < n:
        fid = facies_seq[i]
        run_start = i
        while i < n and facies_seq[i] == fid:
            i += 1
        run_len = i - run_start
        f = FACIES[fid]
        mean = f[1 + log_idx * 2]
        std = f[2 + log_idx * 2]
        for k in range(run_len):
            # Vertical trend: linear gradient from -0.5σ to +0.5σ
            frac = k / max(run_len - 1, 1)  # 0→1 from base to top
            trend = trend_sign * std * 0.5 * (frac - 0.5)
            values.append(float(rng.normal(mean + trend, std * 0.7)))
    return values


def _smooth_log(values, window=3):
    """Apply a simple moving-average smoother to simulate wireline response."""
    if len(values) <= window:
        return values
    out = list(values)
    half = window // 2
    for i in range(half, len(values) - half):
        out[i] = sum(values[i - half:i + half + 1]) / window
    return out


def generate_well(rng, name, x, y, well_idx, n_wells):
    """Generate one well with all parasequences stacked.

    well_idx: 0 = most proximal, n_wells-1 = most distal.
    Returns dict with well data, regions, and truth markers.
    """
    t = well_idx / max(n_wells - 1, 1)  # 0=proximal, 1=distal

    all_facies = []
    all_depth = []
    ps_boundaries = [0]  # marker index of each PS boundary
    depth_cursor = 0.0
    sample_spacing = 0.5  # metres

    for ps_name, base_thick, prox, dist, thick_rate in PARASEQUENCES:
        # Thickness increases downdip
        thickness = base_thick * (1.0 + thick_rate * well_idx)
        n_samples = max(4, int(round(thickness / sample_spacing)))

        profile = _interp_profile(prox, dist, t)
        facies_seq = _sample_facies(rng, profile, n_samples)
        all_facies.extend(facies_seq)

        for i in range(n_samples):
            all_depth.append(depth_cursor + i * sample_spacing)
        depth_cursor += n_samples * sample_spacing
        ps_boundaries.append(len(all_facies))

    n = len(all_facies)

    # Generate logs with geological trends:
    # GR: upward-coarsening in shorefaces (trend_sign=-1)
    # RT: upward-increasing in clean sands (trend_sign=+1)
    # RHOB/NPHI/DT: mild trends
    GR = _smooth_log(_log_from_facies(rng, all_facies, 0, trend_sign=-1.0))
    RT = _smooth_log(_log_from_facies(rng, all_facies, 1, trend_sign=+0.5))
    RHOB = _smooth_log(_log_from_facies(rng, all_facies, 2, trend_sign=-0.3))
    NPHI = _smooth_log(_log_from_facies(rng, all_facies, 3, trend_sign=-0.3))
    DT = _smooth_log(_log_from_facies(rng, all_facies, 4, trend_sign=-0.5))

    # Build regions
    facies_regions = _to_regions(all_facies)

    # Biozone region: 0=below BZ1, 1=BZ1-BZ2, 2=above BZ2
    bz_seq = []
    bz1_idx = ps_boundaries[BIOZONES["BZ1"]]
    bz2_idx = ps_boundaries[BIOZONES["BZ2"]]
    for i in range(n):
        if i < bz1_idx:
            bz_seq.append(0)
        elif i < bz2_idx:
            bz_seq.append(1)
        else:
            bz_seq.append(2)
    bz_regions = _to_regions(bz_seq)

    return {
        "name": name,
        "x": x, "y": y, "z": 0.0, "h": all_depth[-1],
        "n_samples": n,
        "DEPTH": all_depth,
        "GR": GR, "RT": RT, "RHOB": RHOB, "NPHI": NPHI, "DT": DT,
        "FACIES_data": [float(f) for f in all_facies],
        "facies_regions": facies_regions,
        "bz_regions": bz_regions,
        "ps_boundaries": ps_boundaries,
    }


def _to_regions(seq):
    """Convert a sequence to (id, start, length) run-length encoding."""
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
    """Write wells in WeCo native format."""
    with open(filepath, "w") as f:
        f.write("WeCo WellList 2\n")
        f.write(f"{len(wells)}\n")
        for w in wells:
            n = w["n_samples"]
            f.write(f"\n{w['name']}\n")
            f.write(f"{n}\n")
            f.write(f"{w['x']:.5f} {w['y']:.5f} {w['z']:.5f} {w['h']:.5f}\n")
            # 6 data channels + FACIES
            f.write("7\n")
            for log_name in ("DEPTH", "GR", "RT", "RHOB", "NPHI", "DT"):
                f.write(f"{log_name} {n}\n")
                for v in w[log_name]:
                    f.write(f"{v:.5f}\n")
            f.write(f"FACIES {n}\n")
            for v in w["FACIES_data"]:
                f.write(f"{v:.5f}\n")
            # 2 regions: FACIES + BIOZONE
            f.write("2\n")
            f.write(f"FACIES {len(w['facies_regions'])}\n")
            for (rid, start, length) in w["facies_regions"]:
                f.write(f"{rid} {start} {length}\n")
            f.write(f"BIOZONE {len(w['bz_regions'])}\n")
            for (rid, start, length) in w["bz_regions"]:
                f.write(f"{rid} {start} {length}\n")
        f.write("END\n")


def write_options(filepath, opts_dict, comment_lines):
    """Write a WeCo options file."""
    with open(filepath, "w") as f:
        for line in comment_lines:
            f.write(f"# {line}\n")
        f.write("#\n")
        for k, v in opts_dict.items():
            f.write(f"{k}={v}\n")


def main(seed=2026, n_wells=10, output_dir=None):
    rng = np.random.RandomState(seed)
    if output_dir is None:
        output_dir = os.path.dirname(os.path.abspath(__file__))
    os.makedirs(output_dir, exist_ok=True)

    # Wells along dip (Y increases downdip)
    wells = []
    for i in range(n_wells):
        x = 1000.0 + rng.uniform(-50, 50)
        y = 500.0 + i * 400.0 + rng.uniform(-30, 30)
        name = f"SM_{i+1:02d}"
        w = generate_well(rng, name, x, y, i, n_wells)
        wells.append(w)

    write_welllist(wells, os.path.join(output_dir, "wells.txt"))

    # Option configurations
    configs = {
        "options.txt": (
            ["Config: DEFAULT — GR+RHOB+DT variance for shoreface correlation",
             "Shallow marine: use GR (lithology) + RHOB (porosity) + DT (compaction)",
             "Hugin Formation analogue, 5 parasequences"],
            {"cost-function": "composite",
             "var-data": "GR", "var-weight": "0.5",
             "var-data2": "RHOB", "var-weight2": "0.3",
             "var-data3": "DT", "var-weight3": "0.2",
             "order": "position", "max-cor": "80",
             "const-gap-cost": "2.0",
             "out-file": "result.txt"}
        ),
        "options_distality.txt": (
            ["Config: DISTALITY — GR+RHOB+DT with distality cost",
             "Uses FACIES region for lateral equivalence (dist-facies)",
             "Transport direction: along Y (dip direction)"],
            {"cost-function": "composite",
             "var-data": "GR", "var-weight": "0.4",
             "var-data2": "RHOB", "var-weight2": "0.3",
             "var-data3": "DT", "var-weight3": "0.2",
             "dist-facies": "FACIES",
             "order": "position", "max-cor": "80",
             "const-gap-cost": "2.0",
             "out-file": "result_distality.txt"}
        ),
        "options_with_biozones.txt": (
            ["Config: BIOZONES — GR+RHOB+DT constrained by biozone markers",
             "no-crossing=BIOZONE prevents correlation across biozones",
             "Two biozones: BZ1 (base PS2) and BZ2 (base PS4)"],
            {"cost-function": "composite",
             "var-data": "GR", "var-weight": "0.5",
             "var-data2": "RHOB", "var-weight2": "0.3",
             "var-data3": "DT", "var-weight3": "0.2",
             "no-crossing": "BIOZONE",
             "order": "position", "max-cor": "80",
             "const-gap-cost": "2.0",
             "out-file": "result_biozones.txt"}
        ),
    }
    for fname, (comments, opts) in configs.items():
        write_options(os.path.join(output_dir, fname), opts, comments)

    # Print summary
    depths = [w["h"] for w in wells]
    samples = [w["n_samples"] for w in wells]
    print(f"Generated {len(wells)} wells in {output_dir}")
    print(f"  Depth range: {min(depths):.1f} - {max(depths):.1f} m")
    print(f"  Samples/well: {min(samples)} - {max(samples)}")
    print(f"  Total samples: {sum(samples)}")
    print(f"  Facies distribution:")
    all_f = [int(f) for w in wells for f in w["FACIES_data"]]
    for fid in sorted(FACIES.keys()):
        c = sum(1 for f in all_f if f == fid)
        print(f"    {fid} ({FACIES[fid][0]:>18s}): {c:5d} ({100*c/len(all_f):.1f}%)")

    return wells


if __name__ == "__main__":
    main()
