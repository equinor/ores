# Seismic Tiles Constraint — Algorithm & User Guide

> **Module:** `weco.seistiles_constraint`
> **API route:** `POST /run/seistiles`
> **Demo:** `examples/python/demo_seistiles.py`

## Overview

The Seismic Tiles constraint honours piecewise-planar seismic reflector segments
("tiles") during well-to-well correlation. Each tile carries **dip**, **azimuth**,
**amplitude**, and **frequency** attributes at a spatial (x, y, z) location.

The constraint adds a soft cost penalty to the DTW correlation matrix,
penalising marker ties whose implied inter-well geometry contradicts the local
seismic tile dip and azimuth. This is analogous to how the distality/facies cost
(`ccf_distal.cpp`) penalises geologically inconsistent lateral transitions.

## Background — Seismic Tiles

Seismic Tiles represent seismic data as tables of piecewise planar reflector
segments rather than as images. The concept was developed by Equinor and is
described in:

> Øyvind Skjæveland and Sondre Torset, "Seismic Tiles, a data format to
> facilitate analytics on seismic reflectors", *Geophysics*, Vol. 88, No. 3, 2023.

The SeisTiles consortium (2024–) is hosted by Norsk Regnesentral, sponsored by
Equinor, Aker BP, Harbour Energy, and OMV. See https://www.seistiles.com/

Each tile has:
| Attribute   | Unit    | Description                                    |
|-------------|---------|------------------------------------------------|
| x, y, z     | metres  | Tile centre (easting, northing, depth or TWT)  |
| dip          | degrees | Dip angle (0 = horizontal, 90 = vertical)      |
| azimuth      | degrees | Azimuth of maximum dip (0 = north, clockwise)  |
| amplitude    | -       | Seismic amplitude (reflection strength)        |
| frequency    | Hz      | Dominant frequency                              |

## Algorithm

For each candidate marker tie `(i_a, i_b)` connecting well A (depth `z_a`) to
well B (depth `z_b`):

### Step 1 — Tile Lookup

Find the nearest tile to each well at the marker depth using spatial binning:

```
tile_a = find_nearest(well_a.x, well_a.y, z_a, max_h_dist, max_v_dist)
tile_b = find_nearest(well_b.x, well_b.y, z_b, max_h_dist, max_v_dist)
```

The lookup uses a 2-D grid index (binned by x, y) for O(1) horizontal lookup
plus a depth filter within each bin.

### Step 2 — Dip Consistency Penalty

The expected depth shift between wells is derived from the tile's dip (θ)
and azimuth (φ):

$$
\Delta z_{\text{expected}} = (dx \sin \phi + dy \cos \phi) \tan \theta
$$

where `(dx, dy)` is the horizontal vector from well A to well B.

The penalty is the squared normalised deviation:

$$
c_{\text{dip}} = w_{\text{dip}} \left(\frac{\Delta z_{\text{actual}} - \Delta z_{\text{expected}}}{\sigma_{\text{dip}}}\right)^2
$$

**Interpretation:** If tiles indicate a gently dipping reflector and the
correlation tries to tie shallow markers in well A to deep markers in well B
(against the dip), this penalty increases.

### Step 3 — Azimuth Consistency Penalty

If tiles at both wells have azimuth data, a penalty for angular mismatch
is added:

$$
c_{\text{az}} = w_{\text{az}} \left(\frac{\Delta\phi}{\sigma_{\text{az}}}\right)^2
$$

where Δφ is the minimum angular difference (wrapping at 360°).

**Interpretation:** Continuous reflectors should have similar dip azimuth
at both well locations. A large azimuth difference suggests a fault,
unconformity, or different reflector.

### Step 4 — Amplitude Similarity Penalty

Matched reflectors should have comparable amplitude:

$$
c_{\text{amp}} = w_{\text{amp}} \left(\frac{A_a - A_b}{\sigma_{\text{amp}}}\right)^2
$$

**Interpretation:** Ties between high-amplitude and low-amplitude
reflectors are penalised.

### Combined Penalty

The total penalty for cell `(i, j)` is:

$$
\text{penalty}[i, j] = c_{\text{dip}} + c_{\text{az}} + c_{\text{amp}}
$$

This additive penalty matrix is added to the base DTW cost matrix.

## Parameters

| Parameter           | Default | Type  | Description                                              |
|---------------------|---------|-------|----------------------------------------------------------|
| `dip_weight`        | 1.0     | float | Weight for dip-consistency penalty                       |
| `dip_sigma`         | 10.0    | float | Depth-error normalisation (metres)                       |
| `azimuth_weight`    | 0.5     | float | Weight for azimuth-consistency penalty                   |
| `azimuth_sigma`     | 30.0    | float | Azimuth-error normalisation (degrees)                    |
| `amplitude_weight`  | 0.3     | float | Weight for amplitude-similarity penalty                  |
| `amplitude_sigma`   | 0.2     | float | Amplitude-error normalisation                            |
| `max_horizontal_dist` | 500.0 | float | Max horizontal distance for tile lookup (metres)        |
| `max_vertical_dist` | 50.0    | float | Max vertical distance for tile lookup (metres)          |

### Tuning Guidance

| Scenario                          | Recommendation                              |
|-----------------------------------|---------------------------------------------|
| Strong, continuous reflectors     | `dip_weight=2, dip_sigma=5`                 |
| Noisy / discontinuous reflectors  | `dip_weight=0.5, dip_sigma=20`              |
| Good amplitude calibration        | `amplitude_weight=1.0, amplitude_sigma=0.1` |
| Azimuth uncertainty               | `azimuth_weight=0.2, azimuth_sigma=45`      |
| Sparse tile coverage              | `max_horizontal_dist=1000, max_vertical_dist=100` |
| Dense tile coverage               | `max_horizontal_dist=200, max_vertical_dist=30`   |

## Data Format

### CSV (recommended)

```csv
x,y,z,dip,azimuth,amplitude,frequency
460100,6780200,1500.0,5.2,135.0,0.85,25
460100,6780200,1520.0,4.8,138.0,0.82,25
460200,6780300,1510.0,5.0,136.0,0.80,25
```

Columns are case-insensitive. Only `x, y, z` are required; others default to 0.

### JSON

```json
[
  {"x": 460100, "y": 6780200, "z": 1500, "dip": 5.2, "azimuth": 135.0, "amplitude": 0.85},
  {"x": 460100, "y": 6780200, "z": 1520, "dip": 4.8, "azimuth": 138.0, "amplitude": 0.82}
]
```

## API Routes

### `POST /run/seistiles`

Run correlation with Seismic Tiles constraint.

**Request:**
```json
{
  "well_file": "/path/to/wells.txt",
  "tiles_file": "/path/to/tiles.csv",
  "options": {"var-data": "GR", "max-cor": 50},
  "n_best": 1,
  "dip_weight": 1.0,
  "dip_sigma": 10.0,
  "azimuth_weight": 0.5,
  "azimuth_sigma": 30.0,
  "amplitude_weight": 0.3,
  "amplitude_sigma": 0.2
}
```

**Response:** Same as `POST /run`, plus:
```json
{
  "tile_coverage": [
    {"well": "Well_A", "total_markers": 50, "covered": 45, "coverage_pct": 90.0},
    {"well": "Well_B", "total_markers": 50, "covered": 42, "coverage_pct": 84.0}
  ],
  "n_tiles": 120
}
```

### `POST /seistiles/info`

Return summary statistics for a tile file.

**Request:**
```json
{"tiles_file": "/path/to/tiles.csv"}
```

**Response:**
```json
{
  "n_tiles": 120,
  "dip_min": 2.1, "dip_max": 8.5, "dip_mean": 5.2,
  "azimuth_min": 130.0, "azimuth_max": 142.0,
  "amplitude_min": 0.65, "amplitude_max": 0.92,
  "x_range": [460000, 461000],
  "y_range": [6780000, 6781000],
  "z_range": [1000, 1500]
}
```

## Python Usage

```python
from weco.seistiles_constraint import SeisTilesConstraint

# Load tiles
sc = SeisTilesConstraint.from_csv(
    "tiles.csv",
    dip_weight=1.0,
    dip_sigma=5.0,
    azimuth_weight=0.5,
    azimuth_sigma=20.0,
)

# Check coverage
well_positions = {"W1": (460100, 6780200), "W2": (460500, 6780200)}
well_depths = {"W1": depths_w1, "W2": depths_w2}
report = sc.coverage_report(well_positions, well_depths)
print(f"W1: {report['W1']['coverage_pct']:.0f}% tile coverage")

# Build penalty matrix
penalty = sc.build_cost_matrix_modifier(
    "W1", "W2", well_positions, depths_w1, depths_w2
)
# Add to DTW cost matrix
cost_matrix += penalty
```

## Comparison with Existing Constraints

| Feature                  | Horizon Picks (`seismic_constraint`) | Seismic Tiles (`seistiles_constraint`) | Distality (`ccf_distal`) |
|--------------------------|--------------------------------------|----------------------------------------|--------------------------|
| Data source              | Interpreted horizon picks            | Piecewise-planar reflector segments    | Facies + distality regions |
| Geometry used            | Depth at well                        | Dip, azimuth, amplitude               | Facies ID, distality ID  |
| Spatial coverage         | Only at picked horizons              | Dense, between wells too               | Only at well markers     |
| Penalty type             | Quadratic deviation from pick        | Quadratic dip/azimuth/amplitude        | Normalised transition cost |
| Hard/soft constraint     | Soft                                 | Soft                                   | Soft (can reject paths)  |
| Implementation           | Python                               | Python                                 | C++                      |

## Demo

```bash
python examples/python/demo_seistiles.py --output output/seistiles_demo
```

This generates:
- `wells.txt` — 4-well synthetic transect
- `tiles.csv` — synthetic tiles along the transect
- `summary.txt` — penalty statistics and coverage
