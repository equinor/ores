#!/usr/bin/env python3
"""
Rebuild the Bryson Canyon dataset from the original IC Discrete Export files.
============================================================================

Source: tmp/data/bryson/Bryson Canyon B*.dat (IC Discrete Export format)
Book Cliffs, Neslen Formation (Upper Cretaceous), Utah - coastal plain deposits.

Data tables in source:
  - Depositional Facies (named: Coal, Marsh, Wave influenced bayfill, etc.)
  - Lithostratigraphy (Member: Upper Neslen Fm., Middle Neslen Fm.)
  - Reservoir Zonation (Sedimentary units: 1-6)
  - Sequence Stratigraphy (Book-Cliff names: Cozzette-SB_4th, Buck MFS3_5th, etc.)

Key fix: the original demo used unnamed integer codes. This rebuild restores:
  - Named facies with proper geological meaning
  - Sequence stratigraphic boundaries with proper hierarchy (4th/5th order)
  - Distality derived from facies (Coal/Marsh=proximal, Sub-bay=distal)
  - Positive depths (converted from negative TVD-SS convention)
"""

import sys
import os
import json
import re

SRC_DIR = os.path.join(os.path.dirname(__file__), '..', '..', '..',
                       'tmp', 'data', 'bryson')

# Facies name → code mapping (preserving geological meaning)
FACIES_MAP = {
    'Coal': 1,
    'Marsh': 2,
    'Wave influenced bayfill': 3,
    'Sub-bay': 4,
    'Bayhead Delta': 5,
    'Bayhead delta': 5,
    'Crevasse splay': 6,
    'Crevasse system': 6,
    'Distributary channel': 7,
    'Fluvial channel': 7,
    'Lagoonal mud': 8,
    'Lagoon': 8,
}

FACIES_NAMES = {
    1: "Coal",
    2: "Marsh/Swamp",
    3: "Wave-influenced bayfill",
    4: "Sub-bay (central basin)",
    5: "Bayhead delta",
    6: "Crevasse splay",
    7: "Distributary channel",
    8: "Lagoonal mud",
}

# Distality: 1=proximal (channels, crevasse) ... 4=distal (sub-bay, lagoon)
FACIES_DISTALITY = {
    1: 1,   # Coal → proximal (forming in coastal plain)
    2: 1,   # Marsh → proximal
    3: 3,   # Wave-influenced bayfill → intermediate-distal
    4: 4,   # Sub-bay → distal
    5: 2,   # Bayhead delta → intermediate-proximal
    6: 2,   # Crevasse splay → intermediate
    7: 1,   # Distributary channel → proximal
    8: 4,   # Lagoonal mud → distal
}

# Sequence stratigraphy naming (4th and 5th order)
SEQSTRAT_MAP = {
    'Cozzette-SB_4th': 1,
    'Buck MFS3_5th': 2,
    'Buck FS2_5th': 3,
    'Buck FS1_5th': 4,
    'Buck_SB_4th': 5,
    'Corcoran FS3_5th': 6,
    'Corcoran MFS2_5th': 7,
    'Corcoran FS1_5th': 8,
    'Corcoran_SB_4th': 9,
}

# Member mapping
MEMBER_MAP = {
    'Upper Neslen Fm.': 1,
    'Middle Neslen Fm.': 2,
    'Lower Neslen Fm.': 3,
}


def parse_ic_export(filepath):
    """Parse IC Discrete Export file for one well."""
    with open(filepath) as f:
        lines = f.readlines()
    
    # Skip header lines (starting with #)
    header_line = None
    data_start = 0
    for i, line in enumerate(lines):
        if not line.startswith('#') and '\t' in line and 'Well' in line:
            header_line = line.strip().split('\t')
            data_start = i + 1
            break
        elif not line.startswith('#'):
            data_start = i
            break
    
    well_name = None
    x, y = 0, 0
    
    # Group rows by Data Table
    facies_rows = []
    member_rows = []
    zone_rows = []
    seqstrat_rows = []
    
    for line in lines[data_start:]:
        if not line.strip():
            continue
        parts = line.strip().split('\t')
        if len(parts) < 14:
            continue
        
        well = parts[0]
        if well_name is None:
            well_name = well
        
        data_table = parts[2]
        top_depth = float(parts[4])
        top_x = float(parts[5])
        top_y = float(parts[6])
        base_depth = float(parts[8])
        legend = parts[12] if len(parts) > 12 else ''
        
        if x == 0:
            x, y = top_x, top_y
        
        if data_table == 'Depositional Facies':
            facies_rows.append((top_depth, base_depth, legend))
        elif data_table == 'Lithostratigraphy':
            member_rows.append((top_depth, base_depth, legend))
        elif data_table == 'Reservoir Zonation':
            zone_rows.append((top_depth, base_depth, legend))
        elif data_table == 'Sequence Stratigraphy':
            seqstrat_rows.append((top_depth, base_depth, legend))
    
    return {
        'well_name': well_name,
        'x': x, 'y': y,
        'facies': facies_rows,
        'member': member_rows,
        'zone': zone_rows,
        'seqstrat': seqstrat_rows,
    }


def build_well_samples(well_data):
    """Build unified samples from parsed well data."""
    # Source depths are NEGATIVE (TVD below sea level), convert to positive for WeCo
    # Collect all depth boundaries from facies intervals
    depths = set()
    for top, base, _ in well_data['facies']:
        depths.add(top)
        depths.add(base)
    
    if not depths:
        return None
    
    # Sort depths (they're negative, most negative = deepest)
    # Convert: negate to make positive & increasing downward
    sorted_depths = sorted(depths)  # Most negative first = shallowest
    
    # Create samples at midpoints of facies intervals
    samples = []
    for top, base, legend in well_data['facies']:
        mid = (top + base) / 2.0
        # Convert to positive depth (negate)
        md = -mid
        
        facies_code = FACIES_MAP.get(legend, 0)
        distality = FACIES_DISTALITY.get(facies_code, 0)
        
        # Find member at this depth
        member = 0
        for m_top, m_base, m_legend in well_data['member']:
            if m_top <= mid <= m_base or m_base <= mid <= m_top:
                member = MEMBER_MAP.get(m_legend, 0)
                break
        
        # Find zone at this depth
        zone = 0
        for z_top, z_base, z_legend in well_data['zone']:
            if z_top <= mid <= z_base or z_base <= mid <= z_top:
                try:
                    zone = int(z_legend)
                except ValueError:
                    pass
                break
        
        # Find sequence at this depth
        seqstrat = 0
        for s_top, s_base, s_legend in well_data['seqstrat']:
            if s_top <= mid <= s_base or s_base <= mid <= s_top:
                seqstrat = SEQSTRAT_MAP.get(s_legend, 0)
                break
        
        samples.append({
            'md': md,
            'facies': facies_code,
            'distality': distality,
            'member': member,
            'zone': zone,
            'seqstrat': seqstrat,
            'facies_name': legend,
        })
    
    # Sort by positive depth (increasing)
    samples.sort(key=lambda s: s['md'])
    return samples


def extract_all_wells():
    """Extract all wells from IC Discrete Export files."""
    wells = {}
    
    for filename in sorted(os.listdir(SRC_DIR)):
        if not filename.endswith('.dat'):
            continue
        
        filepath = os.path.join(SRC_DIR, filename)
        well_data = parse_ic_export(filepath)
        
        if well_data['well_name'] is None:
            continue
        
        samples = build_well_samples(well_data)
        if not samples or len(samples) < 5:
            continue
        
        well_name = well_data['well_name']
        wells[well_name] = {
            'x': well_data['x'],
            'y': well_data['y'],
            'samples': samples,
        }
    
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
            
            # Channels: MD, FACIES, DISTALITY, ZONE, SEQSTRAT
            f.write("5\n")
            
            f.write(f"MD {n}\n")
            for s in samples:
                f.write(f"{s['md']:.6f}\n")
            
            f.write(f"FACIES {n}\n")
            for s in samples:
                f.write(f"{float(s['facies']):.6f}\n")
            
            f.write(f"DISTALITY {n}\n")
            for s in samples:
                f.write(f"{float(s['distality']):.6f}\n")
            
            f.write(f"ZONE {n}\n")
            for s in samples:
                f.write(f"{float(s['zone']):.6f}\n")
            
            f.write(f"SEQSTRAT {n}\n")
            for s in samples:
                f.write(f"{float(s['seqstrat']):.6f}\n")
            
            # Regions
            f.write("3\n")
            
            # ZONE regions (reservoir zonation = no-crossing constraint)
            zone_regions = _make_regions(samples, 'zone')
            f.write(f"ZONE {len(zone_regions)}\n")
            for reg_id, start, length in zone_regions:
                f.write(f"{reg_id} {start} {length}\n")
            
            # FACIES regions
            fac_regions = _make_regions(samples, 'facies')
            f.write(f"FACIES {len(fac_regions)}\n")
            for reg_id, start, length in fac_regions:
                f.write(f"{reg_id} {start} {length}\n")
            
            # SEQSTRAT regions
            seq_regions = _make_regions(samples, 'seqstrat')
            f.write(f"SEQSTRAT {len(seq_regions)}\n")
            for reg_id, start, length in seq_regions:
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
                {'name': 'FACIES', 'values': [float(s['facies']) for s in samples]},
                {'name': 'DISTALITY', 'values': [float(s['distality']) for s in samples]},
                {'name': 'ZONE', 'values': [float(s['zone']) for s in samples]},
                {'name': 'SEQSTRAT', 'values': [float(s['seqstrat']) for s in samples]},
            ],
            'regions': []
        }
        
        # Regions
        for rname, key in [('ZONE', 'zone'), ('FACIES', 'facies'), ('SEQSTRAT', 'seqstrat')]:
            intervals = [{'id': r[0], 'start': r[1], 'length': r[2]}
                         for r in _make_regions(samples, key)]
            well_obj['regions'].append({'name': rname, 'intervals': intervals})
        
        well_list.append(well_obj)
    
    output = {
        'kind': 'weco:wbs:WellList:1.0.0',
        'meta': {
            'dataChannels': ['MD', 'FACIES', 'DISTALITY', 'ZONE', 'SEQSTRAT'],
            'regionNames': ['ZONE', 'FACIES', 'SEQSTRAT'],
            'wellCount': len(well_list),
            'source': 'Bryson Canyon, Neslen Formation (Upper Cretaceous), Book Cliffs, Utah',
            'faciesDictionary': FACIES_NAMES,
            'sequenceStratigraphy': {str(v): k for k, v in SEQSTRAT_MAP.items()},
        },
        'wells': well_list
    }
    
    with open(filepath, 'w') as f:
        json.dump(output, f, indent=2)


def _make_regions(samples, key):
    """Create region intervals."""
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
    
    # Option 1: Distal CCF with zone constraints
    with open(os.path.join(dirpath, 'options_distal.txt'), 'w') as f:
        f.write("""# Config: BRYSON - Distal CCF for coastal plain correlation
# Neslen Formation (Cretaceous): coal-bearing coastal plain to estuarine
# FACIES encodes depositional environment; DISTALITY derived from it
# ZONE (reservoir zonation) provides no-crossing constraint
#
cost-function=distal
dist-distal=DISTALITY
dist-facies=FACIES
dist-scaling=1.0
no-crossing=ZONE
order=position
max-cor=80
nbr-cor=30
out-nbr-cor=5
min-dist=0.2
out-min-dist=0.1
out-file=result_distal.txt
""")
    
    # Option 2: Variance on facies with sequence constraint
    with open(os.path.join(dirpath, 'options_seqstrat.txt'), 'w') as f:
        f.write("""# Config: BRYSON - Facies variance constrained by sequence stratigraphy
# Uses SEQSTRAT boundaries (4th/5th order) as same-region constraints
# ZONE as no-crossing (keeps correlation within reservoir units)
#
cost-function=varsr
var-data=FACIES
same-region=SEQSTRAT
no-crossing=ZONE
order=position
max-cor=80
nbr-cor=30
out-nbr-cor=5
min-dist=0.2
out-min-dist=0.1
out-file=result_seqstrat.txt
""")
    
    # Option 3: Unconstrained
    with open(os.path.join(dirpath, 'options_basic.txt'), 'w') as f:
        f.write("""# Config: BRYSON - Basic facies variance (unconstrained)
# No stratigraphic constraints - shows correlation ambiguity
# Coal seams create strong markers but lateral facies changes cause ambiguity
#
cost-function=var
var-data=FACIES
order=position
max-cor=80
nbr-cor=30
out-nbr-cor=5
min-dist=0.3
out-min-dist=0.1
out-file=result_basic.txt
""")


def write_readme(dirpath, wells):
    """Write dataset README."""
    with open(os.path.join(dirpath, 'ReadMe.md'), 'w') as f:
        f.write(f"""# Bryson Canyon Dataset

## Source
Neslen Formation (Upper Cretaceous), Bryson Canyon, Book Cliffs, Utah.
Coastal plain to estuarine deposits - coal-bearing sequences.
Exported from IC (Integrated Correlation) software as discrete facies logs.

## Wells: {len(wells)}
{', '.join(sorted(wells.keys()))}

## Data Channels
- **MD**: Measured depth (m, positive downward, converted from TVD-SS)
- **FACIES**: Depositional facies (1-8)
- **DISTALITY**: Proximal-distal position derived from facies (1=proximal, 4=distal)
- **ZONE**: Reservoir zonation / sedimentary units (1-6)
- **SEQSTRAT**: Sequence stratigraphy boundaries (4th/5th order)

## Facies Legend
| Code | Name | Distality | Description |
|------|------|-----------|-------------|
| 1 | Coal | 1 (prox.) | Peat-forming swamp |
| 2 | Marsh | 1 (prox.) | Coastal marsh/swamp |
| 3 | Wave-influenced bayfill | 3 (dist.) | Wave-worked estuarine bay |
| 4 | Sub-bay | 4 (dist.) | Central bay/lagoon |
| 5 | Bayhead delta | 2 (int.) | Progradational bay-fill sand |
| 6 | Crevasse splay | 2 (int.) | Overbank sand sheets |
| 7 | Distributary channel | 1 (prox.) | Channel belt sand bodies |
| 8 | Lagoonal mud | 4 (dist.) | Quiet-water bay/lagoon mud |

## Sequence Stratigraphy
| Code | Name | Order |
|------|------|-------|
| 1 | Cozzette-SB | 4th |
| 2 | Buck MFS3 | 5th |
| 3 | Buck FS2 | 5th |
| 4 | Buck FS1 | 5th |
| 5 | Buck-SB | 4th |
| 6 | Corcoran FS3 | 5th |
| 7 | Corcoran MFS2 | 5th |
| 8 | Corcoran FS1 | 5th |
| 9 | Corcoran-SB | 4th |

## Correlation Strategy
1. **options_distal.txt**: Distal CCF - facies + distality (Walther's Law)
2. **options_seqstrat.txt**: Variance + SEQSTRAT same-region constraint
3. **options_basic.txt**: Unconstrained (shows ambiguity from coal seam repetition)

## Geological Context
The Neslen Formation represents tide/wave-influenced coastal-plain to estuarine
deposits. Coal seams form excellent local markers but split/merge laterally.
The challenge: repeated Coal-Marsh-Bayfill cyclicity creates ambiguity in
well-to-well correlation. Reservoir zonation (units 1-6) and 4th/5th-order
sequence boundaries constrain valid correlations.
""")


if __name__ == '__main__':
    print("Rebuilding Bryson Canyon dataset from IC export files...")
    wells = extract_all_wells()
    
    if not wells:
        print("ERROR: No wells extracted. Check paths.")
        sys.exit(1)
    
    print(f"  Found {len(wells)} wells:")
    for name, data in sorted(wells.items()):
        n = len(data['samples'])
        facies = set(s['facies_name'] for s in data['samples'])
        print(f"  {name}: {n} samples, facies: {sorted(facies)}")
    
    outdir = os.path.dirname(os.path.abspath(__file__))
    
    print(f"\nWriting wells.txt...")
    write_weco_wells_txt(wells, os.path.join(outdir, 'wells.txt'))
    
    print("Writing wells.weco.json...")
    write_weco_json(wells, os.path.join(outdir, 'wells.weco.json'))
    
    print("Writing option files...")
    write_options(outdir)
    
    print("Writing ReadMe.md...")
    write_readme(outdir, wells)
    
    print(f"\nDone! Bryson dataset rebuilt with {len(wells)} wells.")
