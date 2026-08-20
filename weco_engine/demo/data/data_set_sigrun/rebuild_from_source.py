#!/usr/bin/env python3
"""
Rebuild the Sigrun dataset from RMS well exports + biostrat sources.
====================================================================

Philosophy:
  - ZONELOG = one existing interpretation → stored for VALIDATION, NOT as input
  - Biozones = objective (biostratigraphic dating) → legitimate no-crossing constraint
  - Facies = interpretive → offer multiple consolidation levels, test which helps
  - GR/PHIT = raw signal → primary correlation data
  - Picks = flooding surfaces → define interval boundaries + validation

Source data (tmp/sigrun/sigrun_wells/*.rmswell):
  All wells:     TVD, GR
  3-4, 3-5:     + PHIT, GENETIC FACIES, ZONELOG
  3-9_T2:       + PHIT, ZONELOG

Additional sources:
  pickst.txt                          - flooding surface picks (MD)
  Biozones_and_bioconfidence_edt.xlsx - biozone intervals per well
  depofacies.xlsx                     - facies IDs for wells 3-4, 3-5

Output wells (6):
  15/3-4, 15/3-5, 15/3-9 T2, 15/3-3, 15/3-7, 15/3-1 S
"""

import os
import re
import sys
import json

import openpyxl

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

SRC_DIR = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'tmp', 'sigrun')
OUT_DIR = os.path.dirname(__file__)

# ═══════════════════════════════════════════════════════════════════════════
#  Constants
# ═══════════════════════════════════════════════════════════════════════════

# Wells in order (proximal → distal)
WELL_ORDER = ['15_3-4', '15_3-5', '15_3-9_T2', '15_3-7', '15_3-3', '15_3-1_S']

# Per-well distality (1=proximal tidal, 2=intermediate, 3=distal delta, 4=most distal)
WELL_DISTALITY = {
    '15_3-4': 1,
    '15_3-5': 2,
    '15_3-9_T2': 3,
    '15_3-7': 3,
    '15_3-3': 3,
    '15_3-1_S': 4,
}

# ── Facies consolidation: GENETIC FACIES code → group ID ──
# Three consolidation levels tested; Level B (5-class) is default.

# Level A - 8 classes (finest, from RMS, per-well specific codes)
# Stored as-is from rmswell (different numbering per well - normalized below)

# Level B - 5 classes (depositional environment)
FACIES_B = {
    # 15/3-4 GENETIC FACIES codes
    'F-TIDAL CHANNEL': 1, 'F-TIDAL CHAN AMALG': 1, 'F-TIDAL BAR': 1,
    'F-TIDAL FLAT SANDY': 2, 'F-TIDAL FLAT MIXED': 2,
    'F-LAGOON MDST': 3,
    'F-PRODELTA MDST': 4,
    'F-OFFSHORE': 4,
    # 15/3-5 GENETIC FACIES codes
    'F-CREVASSE CHANNEL': 1, 'F-CREVASSE SPLAY': 1,
    'F-BEACH DUNE': 2, 'F-TIDAL FLAT MUDDY': 2,
    'F-LAGOON MDST': 3,
    'F-MARSH': 5, 'F-FLOODPLAIN FINES': 5,
    'F-PRODELTA MDST': 4, 'F-OFFSHORE': 4,
}

FACIES_B_NAMES = {
    1: 'Channel/Bar',
    2: 'Shoreface/Flat',
    3: 'Lagoon/Bay',
    4: 'Prodelta/Offshore',
    5: 'Continental',
}

# Level C - 3 classes (log-response based, least interpretive)
FACIES_C = {
    'F-TIDAL CHANNEL': 1, 'F-TIDAL CHAN AMALG': 1, 'F-TIDAL BAR': 1,
    'F-BEACH DUNE': 1, 'F-CREVASSE CHANNEL': 1, 'F-CREVASSE SPLAY': 1,
    'F-TIDAL FLAT SANDY': 2, 'F-TIDAL FLAT MIXED': 2, 'F-TIDAL FLAT MUDDY': 2,
    'F-LAGOON MDST': 2,
    'F-PRODELTA MDST': 3, 'F-OFFSHORE': 3, 'F-MARSH': 3,
    'F-FLOODPLAIN FINES': 3,
}
FACIES_C_NAMES = {1: 'Sand', 2: 'Mixed', 3: 'Shale'}

# ── Biozone major groups (5) - objective chronostrat ──
# Zone 35.x→1 (Oxfordian), 36.x→2 (EKimm), 37.x→3 (LKimm), 38.x→4 (EVol), 39.x→5 (LVol)

def biozone_major(zone_str):
    """Convert detailed zone string to major group 1-5."""
    if not zone_str or zone_str == '0':
        return 0
    try:
        major = int(float(str(zone_str).strip().split('.')[0]))
        if 35 <= major <= 39:
            return major - 34
        return 0
    except (ValueError, IndexError):
        return 0


# ═══════════════════════════════════════════════════════════════════════════
#  RMS Well parser
# ═══════════════════════════════════════════════════════════════════════════

def parse_rmswell(filepath):
    """Parse RMS well format → dict with metadata, log defs, and data."""
    with open(filepath) as f:
        lines = f.readlines()

    hdr = lines[2].split()
    well_name = hdr[0]
    x, y, kb = float(hdr[1]), float(hdr[2]), float(hdr[3])
    n_logs = int(lines[3].strip())

    # Parse log definitions
    log_defs = []  # list of (name, type, codes_dict_or_None)
    for i in range(4, 4 + n_logs):
        line = lines[i].strip()
        parts = line.split()
        if 'DISC' in parts:
            disc_idx = parts.index('DISC')
            name = ' '.join(parts[:disc_idx])  # everything before DISC keyword
            # Parse code→name pairs after DISC
            codes = {}
            rest = parts[disc_idx + 1:]
            j = 0
            while j < len(rest):
                try:
                    code = int(rest[j])
                    # Collect name tokens until next integer
                    name_parts = []
                    j += 1
                    while j < len(rest):
                        try:
                            int(rest[j])
                            break
                        except ValueError:
                            name_parts.append(rest[j])
                            j += 1
                    codes[code] = ' '.join(name_parts)
                except ValueError:
                    j += 1
            log_defs.append((name, 'DISC', codes))
        else:
            name = parts[0]
            log_defs.append((name, 'lin', None))

    # Parse data rows: x y tvd val1 val2 ... valN
    data_start = 4 + n_logs
    n_cols = 3 + n_logs
    samples = []
    for line in lines[data_start:]:
        parts = line.split()
        if len(parts) >= n_cols:
            try:
                row = [float(v) for v in parts[:n_cols]]
                samples.append(row)
            except ValueError:
                pass

    return {
        'well_name': well_name,
        'x': x, 'y': y, 'kb': kb,
        'n_logs': n_logs,
        'log_defs': log_defs,
        'samples': samples,
    }


# ═══════════════════════════════════════════════════════════════════════════
#  LAS parser (for MD→TVD mapping of GR-only wells)
# ═══════════════════════════════════════════════════════════════════════════

def load_las_trajectory(filepath):
    """Load MD and TVD columns from LAS deviation survey."""
    with open(filepath) as f:
        content = f.read()
    lines = content.split('\n')

    # Curve names
    curve_names = []
    in_curve = False
    for line in lines:
        if line.strip().upper().startswith('~C'):
            in_curve = True
            continue
        if line.startswith('~') and in_curve:
            break
        if in_curve and line.strip() and not line.startswith('#'):
            m = re.match(r'\s*(\S+)', line)
            if m:
                curve_names.append(m.group(1))

    # Data
    in_data = False
    data = []
    for line in lines:
        if line.strip().upper().startswith('~A'):
            in_data = True
            continue
        if in_data and line.strip():
            parts = line.split()
            row = []
            for v in parts[:len(curve_names)]:
                try:
                    row.append(float(v))
                except ValueError:
                    row.append(None)
            if any(v is not None for v in row):
                data.append(row)

    # Extract MD and TVD
    md_idx = next((i for i, n in enumerate(curve_names) if n == 'MD'), 0)
    tvd_idx = next((i for i, n in enumerate(curve_names) if n == 'TVD'), None)
    if tvd_idx is None:
        tvd_idx = next((i for i, n in enumerate(curve_names) if 'TVD' in n.upper()), 3)

    md_tvd = []
    for row in data:
        md = row[md_idx] if md_idx < len(row) else None
        tvd = row[tvd_idx] if tvd_idx < len(row) else None
        if md is not None and tvd is not None and md != -999.25:
            md_tvd.append((md, tvd))

    return md_tvd


def md_to_tvd(md_val, md_tvd_table):
    """Convert a single MD value to TVD using interpolation."""
    if not md_tvd_table:
        return md_val
    # Find bracketing entries
    for i in range(len(md_tvd_table) - 1):
        md0, tvd0 = md_tvd_table[i]
        md1, tvd1 = md_tvd_table[i + 1]
        if md0 <= md_val <= md1:
            frac = (md_val - md0) / (md1 - md0) if md1 != md0 else 0
            return tvd0 + frac * (tvd1 - tvd0)
    # Extrapolate from last segment
    if md_val > md_tvd_table[-1][0]:
        md0, tvd0 = md_tvd_table[-2]
        md1, tvd1 = md_tvd_table[-1]
        frac = (md_val - md0) / (md1 - md0) if md1 != md0 else 0
        return tvd0 + frac * (tvd1 - tvd0)
    return md_val


# ═══════════════════════════════════════════════════════════════════════════
#  External data loaders
# ═══════════════════════════════════════════════════════════════════════════

def normalize_well_name(name):
    """Normalize to our convention: 15_3-4, 15_3-1_S, etc."""
    name = name.strip().replace('/', '_').replace(' ', '_')
    if '15_3-1' in name and 'S' in name.upper():
        return '15_3-1_S'
    if '15_3-9' in name:
        return '15_3-9_T2'
    m = re.search(r'15[_/]3-(\d+)', name)
    if m:
        return f'15_3-{m.group(1)}'
    return name


def load_picks():
    """Load flooding surface picks from pickst.txt (MD values)."""
    picks = {}
    filepath = os.path.join(SRC_DIR, 'pickst.txt')
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('Well name'):
                continue
            parts = line.split('\t')
            if len(parts) >= 3:
                well = normalize_well_name(parts[0])
                surface = parts[1].strip()
                md = float(parts[2])
                picks.setdefault(well, []).append((surface, md))
    return picks


def load_biozones():
    """Load biozone intervals from spreadsheet (MD-based)."""
    biozones = {}
    filepath = os.path.join(SRC_DIR, 'Biozones_and_bioconfidence_edt.xlsx')
    if not os.path.exists(filepath):
        return biozones
    wb = openpyxl.load_workbook(filepath, data_only=True)
    ws = wb['Biozones']

    current_well = None
    for row in ws.iter_rows(min_row=2, values_only=True):
        well = str(row[0]).strip() if row[0] else ''
        if well and well != 'None':
            current_well = normalize_well_name(well)
        top = row[1]
        base = row[3]
        legend = str(row[5]).strip() if row[5] else ''
        if current_well and top is not None and legend:
            try:
                top_f = float(top)
                base_f = float(base) if base else top_f
                biozones.setdefault(current_well, []).append((top_f, base_f, legend))
            except (ValueError, TypeError):
                pass
    return biozones


# ═══════════════════════════════════════════════════════════════════════════
#  Well assembly
# ═══════════════════════════════════════════════════════════════════════════

def extract_hugin_interval(rmswell, picks_md, md_tvd_table):
    """Extract samples within Hugin Formation using TVD bounds from picks."""
    samples = rmswell['samples']
    n_logs = rmswell['n_logs']
    log_defs = rmswell['log_defs']

    # Determine Hugin TVD bounds
    has_zonelog = any(ld[0] == 'ZONELOG' for ld in log_defs)

    if has_zonelog:
        # Use ZONELOG to find Hugin: values 1-5 are in-Hugin
        zl_idx = next(i for i, ld in enumerate(log_defs) if ld[0] == 'ZONELOG')
        col = 3 + zl_idx
        hugin_samples = [s for s in samples if 1 <= s[col] <= 5]
        if not hugin_samples:
            return None, None, None
        tvd_top = hugin_samples[0][2]
        tvd_base = hugin_samples[-1][2]
    else:
        # Convert pick MDs to TVD
        if not picks_md:
            return None, None, None
        pick_tvds = [md_to_tvd(md, md_tvd_table) for _, md in picks_md]
        tvd_top = min(pick_tvds) - 3.0
        tvd_base = max(pick_tvds) + 3.0

    # Extract samples in TVD range, keep only valid GR
    gr_idx = 0  # GR is always first log (LFP_GR)
    extracted = []
    for s in samples:
        tvd = s[2]
        if tvd < tvd_top or tvd > tvd_base:
            continue
        gr = s[3 + gr_idx]
        if gr == -999.0:
            continue
        extracted.append(s)

    return extracted, tvd_top, tvd_base


def assign_zonelog_validation(samples, log_defs):
    """Extract ZONELOG values as validation channel (NOT input)."""
    has_zonelog = any(ld[0] == 'ZONELOG' for ld in log_defs)
    if not has_zonelog:
        return [0] * len(samples)
    zl_idx = next(i for i, ld in enumerate(log_defs) if ld[0] == 'ZONELOG')
    col = 3 + zl_idx
    return [int(s[col]) if s[col] != -999.0 else 0 for s in samples]


def assign_genetic_facies(samples, log_defs, level='B'):
    """Extract and consolidate GENETIC FACIES → group IDs.

    For wells without a GENETIC FACIES log, derive facies from GR thresholds
    so that the FACIES region is never empty (required by dist-facies).
    """
    gf_idx = None
    gf_codes = None
    for i, ld in enumerate(log_defs):
        if 'GENETIC' in ld[0]:
            gf_idx = i
            gf_codes = ld[2]  # {code: name}
            break

    if gf_idx is not None and gf_codes is not None:
        mapping = FACIES_B if level == 'B' else FACIES_C
        col = 3 + gf_idx
        result = []
        for s in samples:
            code = int(s[col]) if s[col] != -999.0 else -1
            name = gf_codes.get(code, '')
            group = mapping.get(name, 0)
            result.append(group)
        return result

    # Fallback: derive facies from GR (always col index 0 → column 3)
    gr_col = 3
    result = []
    for s in samples:
        gr = s[gr_col]
        if gr == -999.0:
            result.append(0)
            continue
        if level == 'B':
            # 5-class: Channel/Bar=1, Shoreface=2, Lagoon=3, Prodelta=4
            if gr < 45:
                result.append(2)    # clean sand → Shoreface/Flat
            elif gr < 75:
                result.append(1)    # sand-dominated → Channel/Bar
            elif gr < 105:
                result.append(3)    # mixed → Lagoon/Bay
            else:
                result.append(4)    # shaly → Prodelta/Offshore
        else:
            # 3-class: Sand=1, Mixed=2, Shale=3
            if gr < 60:
                result.append(1)
            elif gr < 90:
                result.append(2)
            else:
                result.append(3)
    return result


def assign_biozones(samples, biozones_md, md_tvd_table):
    """Assign biozone major group using MD→TVD converted intervals."""
    if not biozones_md:
        return [0] * len(samples)

    # Convert biozone MD intervals to TVD
    bio_tvd = []
    for top_md, base_md, zone_str in biozones_md:
        top_tvd = md_to_tvd(top_md, md_tvd_table)
        base_tvd = md_to_tvd(base_md, md_tvd_table)
        major = biozone_major(zone_str)
        if major > 0:
            bio_tvd.append((top_tvd, base_tvd, major))
    bio_tvd.sort(key=lambda x: x[0])

    result = []
    for s in samples:
        tvd = s[2]
        bz = 0
        for top, base, major in bio_tvd:
            if top <= tvd <= base:
                bz = major
                break
        # If not in interval, inherit from nearest above
        if bz == 0:
            for top, base, major in bio_tvd:
                if tvd >= top:
                    bz = major
        result.append(bz)
    return result


def assign_sequence_from_picks(samples, picks_md, md_tvd_table):
    """Assign sequence zones using ONLY the 3 flooding surfaces shared by all wells
    with sufficient material above and below.

    FS_i, FS_h, FS_g are universally present → 4 zones that ALL 6 wells share.
    (FS_j is too close to formation top in 15/3-9 T2 → excluded)
    """
    if not picks_md:
        return [0] * len(samples)

    # 3 boundaries → 4 zones
    SEQUENCE_MAP = {
        'Hugin_FS_i': 1,   # shallowest boundary
        'Hugin_FS_h': 2,
        'Hugin_FS_g': 3,   # deepest boundary
    }

    # Convert picks to TVD
    pick_tvds = []
    for surf, md in picks_md:
        seq = SEQUENCE_MAP.get(surf, 0)
        if seq > 0:
            tvd = md_to_tvd(md, md_tvd_table)
            pick_tvds.append((tvd, seq))
    pick_tvds.sort(key=lambda x: x[0])

    # Assign: zone 1 = above FS_i, zone 2 = i→h, zone 3 = h→g, zone 4 = below g
    result = []
    for s in samples:
        tvd = s[2]
        seq = 1  # default: above first boundary
        for pick_tvd, pick_seq in pick_tvds:
            if tvd >= pick_tvd:
                seq = pick_seq + 1  # below this boundary
        result.append(seq)
    return result


def make_regions(values):
    """Create WeCo region list from value array. Only non-zero values."""
    regions = []
    cur_id = None
    start = 0
    length = 0
    for i, v in enumerate(values):
        if v != cur_id:
            if cur_id is not None and cur_id > 0:
                regions.append((cur_id, start, length))
            cur_id = v
            start = i
            length = 1
        else:
            length += 1
    if cur_id is not None and cur_id > 0:
        regions.append((cur_id, start, length))
    return regions


# ═══════════════════════════════════════════════════════════════════════════
#  Output writers
# ═══════════════════════════════════════════════════════════════════════════

def write_wells_txt(wells, filepath):
    """Write WeCo WellList 2 format."""
    active = [w for w in WELL_ORDER if w in wells]
    with open(filepath, 'w') as f:
        f.write("WeCo WellList 2\n")
        f.write(f"{len(active)}\n")

        for wn in active:
            w = wells[wn]
            samples = w['samples_extracted']
            n = len(samples)
            tvd_top = samples[0][2]
            tvd_base = samples[-1][2]
            h = tvd_base - tvd_top

            f.write(f"{wn}\n")
            f.write(f"{n}\n")
            f.write(f"{w['x']:.3f} {w['y']:.3f} {tvd_top:.3f} {h:.3f}\n")

            # Data channels: GR, NPHI, BIOZONE, SEQUENCE, FACIES, FACIES3, ZONELOG_REF
            f.write("7\n")

            # GR
            f.write(f"GR {n}\n")
            for s in samples:
                gr = s[3]
                f.write(f"{gr:.4f}\n" if gr != -999.0 else "-999.25\n")

            # NPHI (always written; -999.25 for wells without)
            f.write(f"NPHI {n}\n")
            if w.get('has_phit'):
                phit_idx = w['phit_col']
                for s in samples:
                    v = s[phit_idx]
                    f.write(f"{v:.4f}\n" if v != -999.0 else "-999.25\n")
            else:
                for _ in range(n):
                    f.write("-999.25\n")

            # BIOZONE as data channel (for reference/soft constraint)
            f.write(f"BIOZONE {n}\n")
            for v in w['biozone']:
                f.write(f"{float(v):.1f}\n")

            # SEQUENCE as data channel (for no-crossing)
            f.write(f"SEQUENCE {n}\n")
            for v in w['sequence']:
                f.write(f"{float(v):.1f}\n")

            # FACIES_B (5-class consolidation) as data channel
            f.write(f"FACIES {n}\n")
            for v in w['facies_b']:
                f.write(f"{float(v):.1f}\n")

            # FACIES_C (3-class: Sand/Mixed/Shale) as data channel
            f.write(f"FACIES3 {n}\n")
            for v in w['facies_c']:
                f.write(f"{float(v):.1f}\n")

            # ZONELOG_REF - validation only (existing interpretation)
            f.write(f"ZONELOG_REF {n}\n")
            for v in w['zonelog_ref']:
                f.write(f"{float(v):.1f}\n")

            # Regions: SEQUENCE, BIOZONE, FACIES, FACIES3, DISTALITY
            reg_seq = make_regions(w['sequence'])
            reg_bio = make_regions(w['biozone'])
            reg_fb = make_regions(w['facies_b'])
            reg_fc = make_regions(w['facies_c'])
            reg_dist = [(WELL_DISTALITY[wn], 0, n)]

            n_reg = 5
            f.write(f"{n_reg}\n")
            f.write(f"SEQUENCE {len(reg_seq)}\n")
            for rid, start, length in reg_seq:
                f.write(f"{rid} {start} {length}\n")
            f.write(f"BIOZONE {len(reg_bio)}\n")
            for rid, start, length in reg_bio:
                f.write(f"{rid} {start} {length}\n")
            f.write(f"FACIES {len(reg_fb)}\n")
            for rid, start, length in reg_fb:
                f.write(f"{rid} {start} {length}\n")
            f.write(f"FACIES3 {len(reg_fc)}\n")
            for rid, start, length in reg_fc:
                f.write(f"{rid} {start} {length}\n")
            f.write(f"DISTALITY {len(reg_dist)}\n")
            for rid, start, length in reg_dist:
                f.write(f"{rid} {start} {length}\n")

        f.write("END\n")


def write_options(dirpath):
    """Write option files for plausible correlation scenarios."""

    scenarios = {
        # 1. Pure GR - baseline uncertainty envelope
        'options_1_gr_baseline.txt': """\
# Scenario 1: GR baseline - no constraints
# Shows full uncertainty envelope. Reference for how much
# constraints reduce vs. over-constrain.
cost-function=composite
var-data=GR
var-weight=1.0
order=position
max-cor=100
nbr-cor=30
out-nbr-cor=15
min-dist=0.2
out-min-dist=0.05
""",
        # 2. GR + sequence no-crossing (known flooding surfaces)
        'options_2_gr_sequence.txt': """\
# Scenario 2: GR + sequence no-crossing
# Uses 4 flooding surfaces (FS_j, i, h, g) present in ALL wells
# as hard tie-points. These are widely agreed correlation markers.
# Should narrow uncertainty while remaining geologically sound.
cost-function=composite
var-data=GR
var-weight=1.0
no-crossing=SEQUENCE
order=position
max-cor=100
nbr-cor=30
out-nbr-cor=15
min-dist=0.2
out-min-dist=0.05
""",
        # 3. GR + 5-class facies (moderate consolidation)
        'options_3_gr_facies5.txt': """\
# Scenario 3: GR + 5-class facies distality
# Tests if depositional facies (Channel, Shoreface, Lagoon,
# Prodelta, Continental) adds signal. Compare to scenario 1:
# if results are LESS geologically plausible → over-interpretation.
cost-function=composite
var-data=GR
var-weight=0.8
dist-facies=FACIES
dist-distal=DISTALITY
order=position
max-cor=100
nbr-cor=30
out-nbr-cor=15
min-dist=0.2
out-min-dist=0.05
""",
        # 4. GR + 3-class facies (coarsest - log-response based)
        'options_4_gr_facies3.txt': """\
# Scenario 4: GR + 3-class facies (Sand/Mixed/Shale)
# Most conservative facies scheme. Less interpretive → less noise.
# Compare vs scenario 3: if similar → finer scheme adds only noise.
cost-function=composite
var-data=GR
var-weight=0.8
dist-facies=FACIES3
dist-distal=DISTALITY
order=position
max-cor=100
nbr-cor=30
out-nbr-cor=15
min-dist=0.2
out-min-dist=0.05
""",
        # 5. GR+NPHI composite + sequence (multi-signal + tie-points)
        'options_5_composite_sequence.txt': """\
# Scenario 5: GR+NPHI + sequence no-crossing
# Two independent log curves for better discrimination.
# Sequence (flooding surfaces) as hard tie-points.
# Best balance of signal and constraint for these wells.
cost-function=composite
var-data=GR
var-weight=0.6
var-data2=NPHI
var-weight2=0.4
no-crossing=SEQUENCE
order=position
max-cor=100
nbr-cor=30
out-nbr-cor=15
min-dist=0.2
out-min-dist=0.05
""",
        # 6. Full soft constraints (facies + gap, no hard no-crossing)
        'options_6_full.txt': """\
# Scenario 6: GR + facies + distality + gap cost (max soft constraints)
# Most constrained soft scenario. Uses facies-distality cost
# plus gap penalty without hard no-crossing boundaries.
# Compare to scenario 2 (hard only) and scenario 3 (facies only):
# demonstrates whether additional soft penalties help or over-interpret.
cost-function=composite
var-data=GR
var-weight=0.6
dist-facies=FACIES
dist-distal=DISTALITY
const-gap-cost=0.3
order=position
max-cor=100
nbr-cor=30
out-nbr-cor=10
min-dist=0.2
out-min-dist=0.05
""",
    }

    for fname, content in scenarios.items():
        with open(os.path.join(dirpath, fname), 'w') as f:
            f.write(content)


def write_json(wells, filepath):
    """Write wells.weco.json for web API."""
    active = [w for w in WELL_ORDER if w in wells]
    well_list = []
    for wn in active:
        w = wells[wn]
        samples = w['samples_extracted']
        n = len(samples)

        well_obj = {
            'name': wn,
            'size': n,
            'location': {
                'x': w['x'], 'y': w['y'],
                'z': round(samples[0][2], 2),
                'h': round(samples[-1][2] - samples[0][2], 2),
            },
            'data': [
                {'name': 'GR', 'values': [round(s[3], 2) if s[3] != -999.0 else -999.25
                                           for s in samples]},
                {'name': 'FACIES', 'values': w['facies_b']},
                {'name': 'FACIES3', 'values': w['facies_c']},
                {'name': 'ZONELOG_REF', 'values': w['zonelog_ref']},
            ],
            'regions': [
                {'name': 'BIOZONE',
                 'intervals': [{'id': r[0], 'start': r[1], 'length': r[2]}
                               for r in make_regions(w['biozone'])]},
                {'name': 'FACIES',
                 'intervals': [{'id': r[0], 'start': r[1], 'length': r[2]}
                               for r in make_regions(w['facies_b'])]},
                {'name': 'FACIES3',
                 'intervals': [{'id': r[0], 'start': r[1], 'length': r[2]}
                               for r in make_regions(w['facies_c'])]},
                {'name': 'DISTALITY',
                 'intervals': [{'id': WELL_DISTALITY[wn], 'start': 0, 'length': n}]},
            ],
        }
        if w.get('has_phit'):
            phit_idx = w['phit_col']
            well_obj['data'].insert(1, {
                'name': 'NPHI',
                'values': [round(s[phit_idx], 4) if s[phit_idx] != -999.0 else -999.25
                           for s in samples]
            })
        well_list.append(well_obj)

    output = {
        'kind': 'weco:wbs:WellList:1.0.0',
        'meta': {
            'source': 'Sigrun field, Hugin Fm (Upper Jurassic, block 15/3)',
            'wells': len(well_list),
            'note': 'ZONELOG_REF is an existing interpretation for validation, NOT input.',
            'facies_B': FACIES_B_NAMES,
            'facies_C': FACIES_C_NAMES,
            'biozone_groups': {
                '1': 'Oxfordian (zone 35)',
                '2': 'Early Kimmeridgian (zone 36)',
                '3': 'Late Kimmeridgian (zone 37)',
                '4': 'Early Volgian (zone 38)',
                '5': 'Late Volgian (zone 39)',
            },
            'distality': WELL_DISTALITY,
        },
        'wells': well_list,
    }

    with open(filepath, 'w') as f:
        json.dump(output, f, indent=2)


# ═══════════════════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════════════════

def main():
    print("Rebuilding Sigrun dataset from RMS well exports...")
    print(f"Source: {SRC_DIR}")
    print(f"Output: {OUT_DIR}\n")

    # Load external data
    picks = load_picks()
    biozones = load_biozones()
    print(f"Picks: {sum(len(v) for v in picks.values())} across {len(picks)} wells")
    print(f"Biozones: {sum(len(v) for v in biozones.values())} intervals across {len(biozones)} wells\n")

    wells = {}
    rmswell_dir = os.path.join(SRC_DIR, 'sigrun_wells')

    for wn in WELL_ORDER:
        # Map well name to rmswell filename
        rmswell_file = os.path.join(rmswell_dir, f'{wn}.rmswell')
        las_file = os.path.join(rmswell_dir, f'{wn}.las')

        if not os.path.exists(rmswell_file):
            print(f"  {wn}: rmswell NOT FOUND - skipping")
            continue

        rmswell = parse_rmswell(rmswell_file)

        # Load MD→TVD trajectory from LAS
        md_tvd_table = load_las_trajectory(las_file) if os.path.exists(las_file) else []

        # Get picks for this well (MD)
        well_picks = picks.get(wn, [])

        # Extract Hugin interval
        extracted, tvd_top, tvd_base = extract_hugin_interval(
            rmswell, well_picks, md_tvd_table)

        if not extracted or len(extracted) < 20:
            print(f"  {wn}: only {len(extracted) if extracted else 0} samples - skipping")
            continue

        # Resample to ~1.5m - sufficient for stratigraphic correlation
        # (finer resolution adds noise without improving correlation quality)
        resampled = [extracted[0]]
        for s in extracted[1:]:
            if s[2] - resampled[-1][2] >= 1.5:
                resampled.append(s)

        # Assign channels
        zonelog_ref = assign_zonelog_validation(resampled, rmswell['log_defs'])
        facies_b = assign_genetic_facies(resampled, rmswell['log_defs'], level='B')
        facies_c = assign_genetic_facies(resampled, rmswell['log_defs'], level='C')
        bio = assign_biozones(resampled, biozones.get(wn, []), md_tvd_table)
        seq = assign_sequence_from_picks(resampled, well_picks, md_tvd_table)

        # Detect PHIT column
        has_phit = False
        phit_col = None
        for i, ld in enumerate(rmswell['log_defs']):
            if 'PHIT' in ld[0]:
                has_phit = True
                phit_col = 3 + i
                break

        wells[wn] = {
            'x': rmswell['x'], 'y': rmswell['y'],
            'samples_extracted': resampled,
            'zonelog_ref': zonelog_ref,
            'facies_b': facies_b,
            'facies_c': facies_c,
            'biozone': bio,
            'sequence': seq,
            'has_phit': has_phit,
            'phit_col': phit_col,
        }

        n = len(resampled)
        n_fb = sum(1 for v in facies_b if v > 0)
        n_bio = sum(1 for v in bio if v > 0)
        n_zl = sum(1 for v in zonelog_ref if v > 0)
        phit_str = 'yes' if has_phit else 'no'
        print(f"  {wn:12s}: {n:4d} samples, PHIT={phit_str}, "
              f"facies={n_fb}/{n}, bio={n_bio}/{n}, zonelog_ref={n_zl}/{n}")

    print(f"\nBuilt {len(wells)}/{len(WELL_ORDER)} wells")

    # Write outputs
    wells_path = os.path.join(OUT_DIR, 'wells.txt')
    write_wells_txt(wells, wells_path)
    print(f"\nWrote: {wells_path}")

    json_path = os.path.join(OUT_DIR, 'wells.weco.json')
    write_json(wells, json_path)
    print(f"Wrote: {json_path}")

    write_options(OUT_DIR)
    print("Wrote: 6 option scenario files")

    # Summary
    print(f"\n{'='*60}")
    print("SIGRUN DEMO - SCENARIO DESIGN")
    print(f"{'='*60}")
    print("""
Scenarios test which constraints add SIGNAL vs NOISE:

  1. GR baseline         - full uncertainty envelope (reference)
  2. GR + biozone        - objective chronostrat (should help)
  3. GR + facies (5-cl)  - depositional environment (test)
  4. GR + facies (3-cl)  - sand/mixed/shale (conservative test)
  5. GR+NPHI + biozone   - multi-signal + chronostrat
  6. Full combined       - everything (risk: over-interpretation)

Evaluation: compare each vs. ZONELOG_REF (existing interpretation).
If more constrained → LESS plausible → that constraint = noise.
""")


if __name__ == '__main__':
    main()
