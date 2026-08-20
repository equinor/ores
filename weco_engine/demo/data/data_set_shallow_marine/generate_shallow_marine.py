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
  GR   - Natural gamma ray (API)     → lithology proxy
  RT   - Resistivity (Ohm-m)         → permeability indicator
  RHOB - Bulk density (g/cc)         → porosity proxy
  NPHI - Neutron porosity (v/v)      → porosity proxy
  DT   - Sonic transit time (µs/ft)  → compaction indicator

Geometry:
  Wells are spaced along dip (Y axis). Beds thicken downdip due to
  clinoform progradation. Each parasequence has a known thickness profile
  per well, defining the ground-truth correlation.

Biozones:
  BZ1 (base PS2), BZ2 (base PS4) - two biostratigraphic markers that
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
# Note: Adjacent facies have OVERLAPPING log responses - this is geologically
# realistic and creates genuine ambiguity for the correlation engine.
# Upper/lower shoreface GR overlap (40-65 vs 50-80), offshore/bay overlap, etc.
# ---------------------------------------------------------------------------
FACIES = {
    1: ("OffshoreMud",    115, 18, 1.8, 0.6, 2.44, 0.05, 0.31, 0.04, 92, 10),
    2: ("OffshoreTransit",  85, 18, 3.5, 1.2, 2.38, 0.05, 0.27, 0.04, 83, 9),
    3: ("LowerShoreface",   60, 16, 7.0, 2.5, 2.28, 0.05, 0.21, 0.04, 74, 8),
    4: ("UpperShoreface",   42, 14, 13., 5.0, 2.20, 0.05, 0.17, 0.04, 67, 7),
    5: ("Foreshore",        28, 12, 22., 7.0, 2.16, 0.04, 0.13, 0.03, 61, 6),
    6: ("BayFillMud",      108, 18, 2.2, 0.7, 2.48, 0.05, 0.34, 0.05, 96, 10),
    7: ("TidalChannel",     38, 14, 10., 4.0, 2.23, 0.05, 0.19, 0.04, 69, 7),
    8: ("TransgressiveLag", 48, 14, 18., 6.0, 2.52, 0.06, 0.11, 0.04, 59, 7),
}

# Lateral equivalence groups for distality cost
FACIES_GROUPS = "1,6;2,8;3,7;4,5"

# ---------------------------------------------------------------------------
# Parasequence stacking: (name, base_thickness, facies_profile_proximal,
#                          facies_profile_distal, thickening_rate)
# facies_profile = list of (facies_id, fraction) from base to top
# thickening_rate = fractional increase per well step downdip
#
# Design: PS1/PS3/PS5/PS7 are SIMILAR shoreface progradations - this creates
# the key correlation ambiguity: "which shoreface ties to which?"
# PS2/PS6 are bay-fill (muddy) - similar signature, different age.
# PS4 is a thin transgressive lag - easy to miss or miscorrelate.
# The REPEATED similar pattern forces the engine to explore multiple
# valid scenarios with different reservoir connectivity implications.
# ---------------------------------------------------------------------------
PARASEQUENCES = [
    ("PS1", 7.0,
     [(3, 0.4), (4, 0.4), (5, 0.2)],                 # proximal: shoreface
     [(1, 0.3), (2, 0.4), (3, 0.3)],                  # distal: offshore
     0.18),
    ("PS2", 5.0,
     [(7, 0.5), (4, 0.3), (5, 0.2)],                  # proximal: tidal→shore
     [(6, 0.5), (2, 0.3), (3, 0.2)],                  # distal: bay fill
     0.08),
    ("PS3", 8.0,
     [(3, 0.3), (4, 0.45), (5, 0.25)],               # proximal: shoreface (similar to PS1!)
     [(2, 0.3), (3, 0.4), (4, 0.3)],                  # distal: lower shore
     0.22),
    ("PS4", 2.5,
     [(8, 0.3), (2, 0.4), (3, 0.3)],                 # proximal: lag→offshore
     [(8, 0.1), (1, 0.5), (2, 0.4)],                  # distal: offshore (thin)
     0.03),
    ("PS5", 7.5,
     [(3, 0.2), (4, 0.5), (5, 0.3)],                  # proximal: shoreface (similar to PS1/PS3!)
     [(2, 0.2), (3, 0.4), (4, 0.4)],                  # distal: lower shore
     0.20),
    ("PS6", 4.5,
     [(6, 0.4), (7, 0.4), (4, 0.2)],                  # proximal: bay→tidal
     [(6, 0.6), (2, 0.2), (3, 0.2)],                  # distal: bay fill (similar to PS2!)
     0.06),
    ("PS7", 8.5,
     [(3, 0.15), (4, 0.5), (5, 0.35)],               # proximal: prograding (similar to PS3/PS5!)
     [(2, 0.15), (3, 0.45), (4, 0.4)],                # distal: lower shore
     0.20),
]

# Erosional surfaces: some parasequences are partially eroded in certain
# wells, creating "is this sand connected or is it a separate body?" ambiguity.
# Format: {ps_index: (wells_affected_fraction, max_erosion_fraction)}
# e.g. PS4 (thin lag) is completely eroded in 30% of wells (proximal ravinement)
# PS2 is partially eroded at top in 20% of wells (channel incision)
EROSION = {
    3: (0.30, 1.0),   # PS4: thin lag often eroded entirely (proximal wells)
    1: (0.20, 0.4),   # PS2: top-cut by channel in some wells
    5: (0.15, 0.5),   # PS6: second bay-fill partially removed in some wells
}

# Biozone boundaries (between parasequences, 0-indexed)
BIOZONES = {
    "BZ1": 2,   # base of PS3
    "BZ2": 5,   # base of PS6
}


def _interp_profile(proximal, distal, t):
    """Interpolate facies profile between proximal (t=0) and distal (t=1).

    Each layer blends the proximal and distal facies fractions, and
    selects the facies ID probabilistically based on t - producing
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

    Noise is deliberately high to create log-response ambiguity between
    adjacent facies - realistic for subsurface data where measurement
    uncertainty + diagenesis + cementation create overlap.
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
            # Higher noise: full σ (not 0.7σ) - creates genuine ambiguity
            values.append(float(rng.normal(mean + trend, std)))
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

    Applies erosional truncation to create connectivity ambiguity:
    some parasequences are partially or fully removed in certain wells,
    making it genuinely uncertain whether sand bodies connect laterally.
    """
    t = well_idx / max(n_wells - 1, 1)  # 0=proximal, 1=distal

    all_facies = []
    all_depth = []
    ps_boundaries = [0]  # marker index of each PS boundary
    depth_cursor = 0.0
    sample_spacing = 0.5  # metres

    for ps_idx, (ps_name, base_thick, prox, dist, thick_rate) in enumerate(PARASEQUENCES):
        # Thickness increases downdip
        thickness = base_thick * (1.0 + thick_rate * well_idx)

        # Apply erosion: remove part/all of this PS in some wells
        if ps_idx in EROSION:
            frac_wells_affected, max_erode = EROSION[ps_idx]
            # Erosion preferentially affects proximal wells (ravinement)
            # or random wells (channel incision)
            erode_threshold = frac_wells_affected
            well_hash = rng.random()
            if well_hash < erode_threshold:
                erosion_frac = rng.uniform(0.5, 1.0) * max_erode
                thickness *= (1.0 - erosion_frac)

        # Add per-well random thickness variation (±20%) to create ambiguity
        thickness *= rng.uniform(0.80, 1.20)

        n_samples = max(2, int(round(thickness / sample_spacing)))

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


def write_truth_model(wells, filepath):
    """Export the ground-truth correlation as a JSON file.

    The truth model defines:
    - Parasequence boundaries (isochronous surfaces) across all wells
    - Expected correlation lines between equivalent horizons
    - Erosion events (missing/condensed parasequences in specific wells)

    This allows validation: does WeCo find the truth among its N-best?
    And does it produce genuinely different alternatives that span the
    geological uncertainty space?
    """
    import json

    truth = {
        "description": "Ground-truth correlation model for shallow marine dataset",
        "parasequences": [ps[0] for ps in PARASEQUENCES],
        "wells": [],
        "correlation_lines": [],
    }

    # For each well, record the depth of each parasequence boundary
    for w in wells:
        well_truth = {
            "name": w["name"],
            "ps_boundaries_sample_idx": w["ps_boundaries"],
            "ps_boundaries_depth": [w["DEPTH"][min(idx, len(w["DEPTH"])-1)]
                                    for idx in w["ps_boundaries"]],
        }
        truth["wells"].append(well_truth)

    # Generate correlation lines: each PS boundary connects across wells
    n_ps = len(PARASEQUENCES)
    for ps_idx in range(n_ps + 1):  # n_ps+1 boundaries (top of each + base)
        horizon_name = f"Base_PS{ps_idx+1}" if ps_idx < n_ps else "Top"
        if ps_idx == 0:
            horizon_name = "Base"

        line = {
            "name": horizon_name,
            "type": "isochronous_surface",
            "wells": {}
        }
        for w in wells:
            if ps_idx < len(w["ps_boundaries"]):
                idx = w["ps_boundaries"][ps_idx]
                if idx < len(w["DEPTH"]):
                    line["wells"][w["name"]] = {
                        "sample_idx": idx,
                        "depth": w["DEPTH"][idx],
                    }
        truth["correlation_lines"].append(line)

    # Document expected ambiguity scenarios
    truth["ambiguity_scenarios"] = [
        {
            "description": "PS1/PS3/PS5/PS7 shoreface miscorrelation",
            "explanation": "These four parasequences have nearly identical "
                          "shoreface facies profiles. Without biozone constraints, "
                          "correlating PS1 in well A to PS3 in well B is equally "
                          "valid from a log-response perspective.",
            "affected_parasequences": ["PS1", "PS3", "PS5", "PS7"],
        },
        {
            "description": "PS2/PS6 bay-fill miscorrelation",
            "explanation": "Two bay-fill units with similar muddy signatures. "
                          "Without biozones, these could be swapped.",
            "affected_parasequences": ["PS2", "PS6"],
        },
        {
            "description": "PS4 thin lag erosion",
            "explanation": "PS4 (transgressive lag) is eroded in some proximal "
                          "wells. The correlator must decide: is the thin sand "
                          "PS4 or part of PS3/PS5? Gap cost vs. correlation cost.",
            "affected_parasequences": ["PS4"],
        },
    ]

    with open(filepath, 'w') as f:
        json.dump(truth, f, indent=2)


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
            ["Config: DEFAULT - GR+RHOB+DT variance for shoreface correlation",
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
            ["Config: DISTALITY - GR+RHOB+DT with distality cost",
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
            ["Config: BIOZONES - GR+RHOB+DT constrained by biozone markers",
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

    # Export ground-truth correlation model
    write_truth_model(wells, os.path.join(output_dir, "truth_correlation.json"))

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


def _export_json(output_dir):
    """Export wells.weco.json from the generated wells.txt."""
    import json
    from weco.data import WellList
    from weco.json_format import welllist_to_json
    wl = WellList(os.path.join(output_dir, "wells.txt"))
    doc = welllist_to_json(wl)
    json_path = os.path.join(output_dir, "wells.weco.json")
    with open(json_path, "w") as f:
        json.dump(doc, f, indent=2)
    print(f"Wrote: {json_path}")


if __name__ == "__main__":
    main()
    _export_json(os.path.dirname(os.path.abspath(__file__)))
