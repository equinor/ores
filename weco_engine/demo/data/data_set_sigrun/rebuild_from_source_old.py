#!/usr/bin/env python3
"""
Rebuild the Sigrun dataset from the original LAS + picks source.
================================================================

Source: tmp/data/sigrun/sigrun_wells/ (7 LAS files from RMS)
        tmp/data/sigrun/pickst.txt (Hugin flooding surface picks)
        tmp/data/sigrun/LogatMarker.txt (biozone at marker)

Hugin Formation, Upper Jurassic, Sigrun field (block 15/3, North Sea).
Tide-dominated shallow marine to offshore - classic parasequence correlation.

Wells with full facies interpretation: 15_3-4, 15_3-5
Wells with GR only: 15_3-7, 15_3-9_T2, 15_3-3, 15_3-1_S, 15_3-8

All wells have Hugin formation flooding surface picks (Hugin_FS_f through _m).
These picks ARE the correlation truth - isochronous surfaces.
"""

import sys
import os
import re
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

SRC_DIR = os.path.join(os.path.dirname(__file__), '..', '..', '..',
                       'tmp', 'data', 'sigrun')

# Hugin flooding surface hierarchy (youngest/shallowest to oldest/deepest)
# These are the truth correlation horizons
HORIZON_ORDER = ['Hugin_FS_m', 'Hugin_FS_l', 'Hugin_FS_k', 'Hugin_FS_j',
                 'Hugin_FS_i', 'Hugin_FS_h', 'Hugin_FS_g', 'Hugin_FS_f',
                 'Hugin_FS_ E', 'TopSleipner']

# Map horizon name to sequence number (for no-crossing regions)
HORIZON_TO_SEQ = {
    'Hugin_FS_m': 1, 'Hugin_FS_l': 2, 'Hugin_FS_k': 3, 'Hugin_FS_j': 4,
    'Hugin_FS_i': 5, 'Hugin_FS_h': 6, 'Hugin_FS_g': 7, 'Hugin_FS_f': 8,
    'Hugin_FS_ E': 9, 'TopSleipner': 10,
}


def parse_las_v3(filepath):
    """Parse LAS v3 file, extract header and data within Hugin Formation."""
    with open(filepath) as f:
        content = f.read()
    
    # Extract well info
    x_match = re.search(r'X\s+\.m\s+([\d.]+)', content)
    y_match = re.search(r'Y\s+\.m\s+([\d.]+)', content)
    x = float(x_match.group(1)) if x_match else 0
    y = float(y_match.group(1)) if y_match else 0
    
    well_match = re.search(r'WELL\s+\.\s+(\S+)', content)
    well_name = well_match.group(1) if well_match else os.path.basename(filepath).replace('.las', '')
    
    # Find curve names
    lines = content.split('\n')
    curve_names = []
    in_curve = False
    in_data = False
    
    for line in lines:
        if '~CURVE' in line:
            in_curve = True
            continue
        if line.startswith('~') and in_curve:
            in_curve = False
        if in_curve and not line.startswith('#') and line.strip():
            # Parse curve name from "NAME .unit : description"
            name_match = re.match(r'(\S+(?:\s+\S+)?)\s+\.', line)
            if name_match:
                curve_names.append(name_match.group(1).strip())
        if '~ASCII' in line or '~A ' in line:
            in_data = True
            continue
    
    # Determine column indices
    # Note: In LAS v3 data section, each curve = 1 whitespace-delimited column
    # even if the curve name has spaces (e.g. "GENETIC FACIES")
    has_zonelog = 'ZONELOG' in curve_names or 'GENETIC FACIES' in curve_names
    md_idx = 0  # Always first
    
    # Build positional index (data column position, not header line position)
    col_idx = 0
    col_map = {}
    for name in curve_names:
        col_map[name] = col_idx
        col_idx += 1
    
    gr_idx = col_map.get('LFP_GR')
    phit_idx = col_map.get('LFP_PHIT')
    tvd_idx = col_map.get('TVD')
    zonelog_idx = col_map.get('ZONELOG')
    facies_idx = col_map.get('FACIES')
    genfacies_idx = col_map.get('GENETIC FACIES')
    
    # Parse data
    data_lines = []
    in_data = False
    for line in lines:
        if '~ASCII' in line or '~A ' in line:
            in_data = True
            continue
        if not in_data:
            continue
        if line.strip():
            data_lines.append(line)
    
    return {
        'well_name': well_name,
        'x': x, 'y': y,
        'curve_names': curve_names,
        'data_lines': data_lines,
        'gr_idx': gr_idx,
        'phit_idx': phit_idx,
        'tvd_idx': tvd_idx,
        'zonelog_idx': zonelog_idx,
        'facies_idx': facies_idx,
        'genfacies_idx': genfacies_idx,
        'has_zonelog': has_zonelog,
    }


def load_picks():
    """Load Hugin flooding surface picks from pickst.txt."""
    picks = {}  # well_name -> [(surface_name, md, tvdss)]
    filepath = os.path.join(SRC_DIR, 'pickst.txt')
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('Well name'):
                continue
            parts = line.split('\t')
            if len(parts) >= 3:
                well = parts[0].strip().replace('/', '_')
                surface = parts[1].strip()
                md = float(parts[2])
                picks.setdefault(well, []).append((surface, md))
    return picks


def load_biozones_at_markers():
    """Load biozone assignments at markers from LogatMarker.txt."""
    biozones = {}  # well_name -> [(marker, md, biozone_id)]
    filepath = os.path.join(SRC_DIR, 'LogatMarker.txt')
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('WellName'):
                continue
            parts = line.split()
            if len(parts) >= 4:
                well = parts[0].replace('/', '_')
                marker = parts[1]
                md = float(parts[2])
                bz = int(parts[3])
                biozones.setdefault(well, []).append((marker, md, bz))
    return biozones


def extract_hugin_interval(las_data, picks_for_well):
    """Extract the Hugin Formation interval from a well's data."""
    if not picks_for_well:
        return None
    
    # Find top and base of Hugin from picks
    pick_depths = [md for _, md in picks_for_well]
    hugin_top = min(pick_depths) - 5.0  # 5m above shallowest pick
    hugin_base = max(pick_depths) + 5.0  # 5m below deepest pick
    
    # For wells with zonelog, use zone boundaries instead
    if las_data['has_zonelog'] and las_data['zonelog_idx'] is not None:
        # Already know the interval from zone parsing
        pass
    
    # Extract GR data in the Hugin interval, resample to ~0.5m
    samples = []
    target_step = 0.5  # m
    last_md = None
    
    for line in las_data['data_lines']:
        parts = line.split()
        if len(parts) <= (las_data['gr_idx'] or 0):
            continue
        
        try:
            md = float(parts[0])
        except (ValueError, IndexError):
            continue
        
        if md < hugin_top or md > hugin_base:
            continue
        
        # Subsample to ~0.5m
        if last_md is not None and (md - last_md) < target_step * 0.8:
            continue
        last_md = md
        
        gr = None
        if las_data['gr_idx'] is not None:
            try:
                gr_val = float(parts[las_data['gr_idx']])
                if gr_val != -999.25:
                    gr = gr_val
            except (ValueError, IndexError):
                pass
        
        phit = None
        if las_data['phit_idx'] is not None:
            try:
                phit_val = float(parts[las_data['phit_idx']])
                if phit_val != -999.25:
                    phit = phit_val
            except (ValueError, IndexError):
                pass
        
        # Facies - in 15_3-4/15_3-5, the "GENETIC FACIES" column (with space)
        # gets parsed at zonelog_idx position. It contains values like "F-TIDAL".
        # The actual ZONELOG is one column later.
        facies = None
        if las_data['zonelog_idx'] is not None and len(parts) > las_data['zonelog_idx']:
            val = parts[las_data['zonelog_idx']]
            if val.startswith('F-'):
                # This is actually GENETIC FACIES (naming collision due to LAS v3 spaces)
                facies = val
        
        # Also check explicit genfacies_idx
        if facies is None and las_data['genfacies_idx'] is not None and len(parts) > las_data['genfacies_idx']:
            gf = parts[las_data['genfacies_idx']]
            if gf.startswith('F-'):
                facies = gf
        
        samples.append({
            'md': md,
            'gr': gr,
            'phit': phit,
            'facies': facies,
            'zonelog': None,
        })
    
    return samples


def assign_sequences_from_picks(samples, picks_for_well):
    """Assign sequence IDs based on flooding surface picks."""
    if not picks_for_well or not samples:
        return
    
    # Sort picks by depth
    sorted_picks = sorted(picks_for_well, key=lambda p: p[1])
    
    for s in samples:
        # Find which parasequence this sample falls in
        seq = 0
        for i, (surface, md) in enumerate(sorted_picks):
            if s['md'] >= md:
                seq_id = HORIZON_TO_SEQ.get(surface, 0)
                if seq_id > 0:
                    seq = seq_id
        s['sequence'] = seq


def assign_biozones(samples, biozones_for_well):
    """Assign biozone IDs from marker data."""
    if not biozones_for_well or not samples:
        return
    
    sorted_bz = sorted(biozones_for_well, key=lambda b: b[1])
    
    for s in samples:
        s['biozone'] = 0
        for marker, md, bz_id in sorted_bz:
            if bz_id > 0 and s['md'] >= md:
                s['biozone'] = bz_id


# Facies name to code mapping for Sigrun
FACIES_MAP = {
    'F-TIDAL': 1,
    'F-LAGOON': 2,
    'F-BEACH': 3,
    'F-PRODELTA': 4,
    'F-FLOODPLAIN': 5,
    'F-MARSH': 6,
    'F-CREVASSE': 7,
    'F-CHANNEL': 8,
}

FACIES_NAMES = {
    1: "Tidal",
    2: "Lagoon",
    3: "Beach/Shoreface",
    4: "Prodelta",
    5: "Floodplain",
    6: "Marsh",
    7: "Crevasse splay",
    8: "Channel",
}

# Distality for facies (1=proximal, higher=more distal)
FACIES_DISTALITY = {
    1: 2,   # Tidal → intermediate
    2: 3,   # Lagoon → intermediate-distal
    3: 1,   # Beach → proximal
    4: 5,   # Prodelta → distal
    5: 2,   # Floodplain → intermediate
    6: 2,   # Marsh → intermediate
    7: 2,   # Crevasse → intermediate
    8: 1,   # Channel → proximal
}


def build_dataset():
    """Build the complete Sigrun dataset."""
    picks = load_picks()
    biozones = load_biozones_at_markers()
    
    las_dir = os.path.join(SRC_DIR, 'sigrun_wells')
    las_files = sorted(f for f in os.listdir(las_dir) if f.endswith('.las'))
    
    wells = {}
    
    for las_file in las_files:
        filepath = os.path.join(las_dir, las_file)
        las_data = parse_las_v3(filepath)
        
        # Normalize well name for pick lookup
        well_name = las_file.replace('.las', '')
        pick_key = well_name
        
        picks_for_well = picks.get(pick_key, [])
        biozones_for_well = biozones.get(pick_key, [])
        
        if not picks_for_well:
            print(f"  {well_name}: no picks, skipping")
            continue
        
        samples = extract_hugin_interval(las_data, picks_for_well)
        if not samples or len(samples) < 5:
            print(f"  {well_name}: only {len(samples) if samples else 0} samples in Hugin, skipping")
            continue
        
        # Assign sequences and biozones
        assign_sequences_from_picks(samples, picks_for_well)
        assign_biozones(samples, biozones_for_well)
        
        # Assign facies codes
        for s in samples:
            if s['facies'] and s['facies'] in FACIES_MAP:
                s['facies_code'] = FACIES_MAP[s['facies']]
            else:
                s['facies_code'] = 0
        
        wells[well_name] = {
            'x': las_data['x'],
            'y': las_data['y'],
            'samples': samples,
        }
        print(f"  {well_name}: {len(samples)} samples, "
              f"GR={'yes' if any(s['gr'] for s in samples) else 'no'}, "
              f"facies={'yes' if any(s['facies_code'] for s in samples) else 'no'}")
    
    return wells


def write_weco_wells_txt(wells, filepath):
    """Write WeCo WellList format."""
    with open(filepath, 'w') as f:
        f.write("WeCo WellList 2\n")
        f.write(f"{len(wells)}\n")
        
        for well_name, data in sorted(wells.items()):
            samples = data['samples']
            n = len(samples)
            x, y = data['x'], data['y']
            z_top = samples[0]['md']
            h = samples[-1]['md'] - samples[0]['md']
            
            f.write(f"{well_name}\n")
            f.write(f"{n}\n")
            f.write(f"{x:.6f} {y:.6f} {z_top:.6f} {h:.6f}\n")
            
            # Channels: MD, GR, NPHI, FACIES, SEQUENCE, BIOZONE
            channels = ['MD', 'GR', 'NPHI', 'FACIES', 'SEQUENCE', 'BIOZONE']
            f.write(f"{len(channels)}\n")
            
            f.write(f"MD {n}\n")
            for s in samples:
                f.write(f"{s['md']:.6f}\n")
            
            f.write(f"GR {n}\n")
            for s in samples:
                f.write(f"{s['gr'] if s['gr'] is not None else -999.25:.6f}\n")
            
            f.write(f"NPHI {n}\n")
            for s in samples:
                f.write(f"{s['phit'] if s['phit'] is not None else -999.25:.6f}\n")
            
            f.write(f"FACIES {n}\n")
            for s in samples:
                f.write(f"{float(s['facies_code']):.6f}\n")
            
            f.write(f"SEQUENCE {n}\n")
            for s in samples:
                f.write(f"{float(s.get('sequence', 0)):.6f}\n")
            
            f.write(f"BIOZONE {n}\n")
            for s in samples:
                f.write(f"{float(s.get('biozone', 0)):.6f}\n")
            
            # Regions
            f.write("2\n")
            
            # SEQUENCE regions
            seq_regions = _make_regions(samples, 'sequence')
            f.write(f"SEQUENCE {len(seq_regions)}\n")
            for reg_id, start, length in seq_regions:
                f.write(f"{reg_id} {start} {length}\n")
            
            # BIOZONE regions
            bio_regions = _make_regions(samples, 'biozone')
            f.write(f"BIOZONE {len(bio_regions)}\n")
            for reg_id, start, length in bio_regions:
                f.write(f"{reg_id} {start} {length}\n")
        
        f.write("END\n")


def write_weco_json(wells, filepath):
    """Write wells.weco.json format."""
    well_list = []
    
    for well_name, data in sorted(wells.items()):
        samples = data['samples']
        n = len(samples)
        x, y = data['x'], data['y']
        z_top = samples[0]['md']
        h = samples[-1]['md'] - samples[0]['md']
        
        well_obj = {
            'name': well_name,
            'size': n,
            'location': {'x': x, 'y': y, 'z': z_top, 'h': h},
            'data': [
                {'name': 'MD', 'values': [s['md'] for s in samples]},
                {'name': 'GR', 'values': [s['gr'] if s['gr'] is not None else -999.25 for s in samples]},
                {'name': 'NPHI', 'values': [s['phit'] if s['phit'] is not None else -999.25 for s in samples]},
                {'name': 'FACIES', 'values': [float(s['facies_code']) for s in samples]},
                {'name': 'SEQUENCE', 'values': [float(s.get('sequence', 0)) for s in samples]},
                {'name': 'BIOZONE', 'values': [float(s.get('biozone', 0)) for s in samples]},
            ],
            'regions': []
        }
        
        # Sequence regions
        seq_intervals = [{'id': r[0], 'start': r[1], 'length': r[2]}
                         for r in _make_regions(samples, 'sequence')]
        well_obj['regions'].append({'name': 'SEQUENCE', 'intervals': seq_intervals})
        
        # Biozone regions
        bio_intervals = [{'id': r[0], 'start': r[1], 'length': r[2]}
                         for r in _make_regions(samples, 'biozone')]
        well_obj['regions'].append({'name': 'BIOZONE', 'intervals': bio_intervals})
        
        well_list.append(well_obj)
    
    output = {
        'kind': 'weco:wbs:WellList:1.0.0',
        'meta': {
            'dataChannels': ['MD', 'GR', 'NPHI', 'FACIES', 'SEQUENCE', 'BIOZONE'],
            'regionNames': ['SEQUENCE', 'BIOZONE'],
            'wellCount': len(well_list),
            'source': 'Sigrun field, Hugin Formation (Upper Jurassic, block 15/3)',
            'faciesDictionary': FACIES_NAMES,
            'horizons': HORIZON_ORDER,
        },
        'wells': well_list
    }
    
    with open(filepath, 'w') as f:
        json.dump(output, f, indent=2)


def _make_regions(samples, key):
    """Create region intervals from sample attribute."""
    regions = []
    current_id = None
    start = 0
    length = 0
    
    for i, s in enumerate(samples):
        val = s.get(key, 0)
        if val is None or val == 0:
            if current_id is not None:
                regions.append((current_id, start, length))
                current_id = None
            continue
        if val != current_id:
            if current_id is not None:
                regions.append((current_id, start, length))
            current_id = val
            start = i
            length = 1
        else:
            length += 1
    
    if current_id is not None:
        regions.append((current_id, start, length))
    return regions


def write_options(dirpath):
    """Write correlation option files."""
    
    # Option 1: GR variance with sequence no-crossing
    with open(os.path.join(dirpath, 'options_gr.txt'), 'w') as f:
        f.write("""# Config: SIGRUN - GR log correlation with flooding surface constraints
# Hugin Formation (Upper Jurassic): tide-dominated shallow marine
# GR is the primary correlation log (shale/sand discrimination)
# SEQUENCE no-crossing locks known flooding surfaces
#
cost-function=composite
var-data=GR
var-weight=1.0
no-crossing=SEQUENCE
order=position
max-cor=100
nbr-cor=50
out-nbr-cor=10
min-dist=0.2
out-min-dist=0.1
out-file=result_gr.txt
""")
    
    # Option 2: GR + NPHI composite
    with open(os.path.join(dirpath, 'options_composite.txt'), 'w') as f:
        f.write("""# Config: SIGRUN - GR+NPHI composite correlation
# GR (lithology) + NPHI (porosity) for better discrimination
# SEQUENCE provides chronostratigraphic no-crossing constraint
#
cost-function=composite
var-data=GR
var-weight=0.6
var-data2=NPHI
var-weight2=0.4
no-crossing=SEQUENCE
order=position
max-cor=100
nbr-cor=50
out-nbr-cor=10
min-dist=0.3
out-min-dist=0.1
out-file=result_composite.txt
""")
    
    # Option 3: Unconstrained for uncertainty assessment
    with open(os.path.join(dirpath, 'options_unconstrained.txt'), 'w') as f:
        f.write("""# Config: SIGRUN - Unconstrained GR correlation
# No chronostratigraphic constraints - shows full uncertainty envelope
# Compare with constrained versions to assess biozone impact
#
cost-function=var
var-data=GR
order=position
max-cor=100
nbr-cor=50
out-nbr-cor=10
min-dist=0.3
out-min-dist=0.1
out-file=result_unconstrained.txt
""")


def write_readme(dirpath, wells):
    """Write dataset README."""
    with open(os.path.join(dirpath, 'ReadMe.md'), 'w') as f:
        f.write(f"""# Sigrun Field Dataset

## Source
Hugin Formation (Upper Jurassic), Sigrun field, block 15/3, North Sea.
Extracted from RMS LAS v3 exports + well picks.

## Wells: {len(wells)}
{', '.join(sorted(wells.keys()))}

## Data Channels
- **MD**: Measured depth (m)
- **GR**: Gamma ray log (LFP_GR, API units)
- **NPHI**: Total porosity (LFP_PHIT, v/v) - only in 15_3-4, 15_3-5
- **FACIES**: Genetic facies code (1-8) - only in 15_3-4, 15_3-5
- **SEQUENCE**: Parasequence bounded by Hugin flooding surfaces (1-10)
- **BIOZONE**: Biozone assignment at marker depths

## Flooding Surface Hierarchy (truth correlation horizons)
{chr(10).join(f'- **{h}** (Parasequence {HORIZON_TO_SEQ[h]})' for h in HORIZON_ORDER)}

## Facies Legend
| Code | Environment | Distality |
|------|-------------|-----------|
{chr(10).join(f'| {k} | {v} | {FACIES_DISTALITY[k]} |' for k, v in FACIES_NAMES.items())}

## Correlation Strategy
1. **options_gr.txt**: GR variance + flooding surface no-crossing
2. **options_composite.txt**: GR+NPHI + no-crossing
3. **options_unconstrained.txt**: Unconstrained (uncertainty baseline)

## Geological Context
The Hugin Formation is a tide-dominated shallow marine system with lateral facies
changes from tidal channels/bars (proximal) to prodelta/offshore (distal). The
flooding surfaces (Hugin_FS_m through _f) provide isochronous correlation markers.
Wells are spaced 3-8 km apart across the field.
""")


if __name__ == '__main__':
    print("Rebuilding Sigrun dataset from LAS source...")
    wells = build_dataset()
    
    if not wells:
        print("ERROR: No wells extracted. Check paths.")
        sys.exit(1)
    
    outdir = os.path.dirname(os.path.abspath(__file__))
    
    print(f"\nWriting wells.txt ({len(wells)} wells)...")
    write_weco_wells_txt(wells, os.path.join(outdir, 'wells.txt'))
    
    print("Writing wells.weco.json...")
    write_weco_json(wells, os.path.join(outdir, 'wells.weco.json'))
    
    print("Writing option files...")
    write_options(outdir)
    
    print("Writing ReadMe.md...")
    write_readme(outdir, wells)
    
    print(f"\nDone! Sigrun dataset rebuilt with {len(wells)} wells.")
