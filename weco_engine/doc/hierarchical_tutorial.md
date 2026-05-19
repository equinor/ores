# Why Hierarchical? Sequence Stratigraphy Meets Graph-DTW

## Introduction

Traditional well correlation via graph-DTW treats all markers equally —
it finds the globally optimal n-best paths through a cost graph where
every transition has the same structural weight.  This works well for
sub-seismic correlations where intervals are relatively uniform, but
breaks down when:

- **Noise** in log data creates false minima that attract the DTW path
- **Scale mixing** causes thin beds to dominate over significant surfaces
- **Geological unconformities** cross boundaries that should be locked

Hierarchical correlation solves this by borrowing the key insight from
sequence stratigraphy: *surfaces of different hierarchical order exist,
and higher-order surfaces should be established first*.

## How It Works in WeCo

### Step 1: Detect Sequence-Stratigraphic Surfaces

Using GR log patterns, WeCo automatically detects:

- **MFS** (Maximum Flooding Surfaces) — GR peaks (high gamma = shale)
- **SB** (Sequence Boundaries) — GR troughs with sharp base (low gamma)
- **TS** (Transgressive Surfaces) — GR inflection points

```python
from weco.sequence_strat import detect_mfs, detect_sb, add_sequence_boundaries

add_sequence_boundaries(well_list, "GR", window=10,
                        mfs_prominence=20, sb_prominence=15)
```

### Step 2: Lock Surfaces as Constraints

Detected surfaces become `no_crossing` region boundaries.  The DTW
search space is now partitioned into intervals bounded by these surfaces.

### Step 3: Run Constrained Correlation

```python
from weco.sequence_strat import hierarchical_correlate

result = hierarchical_correlate(
    well_list, "GR", "GR",
    coarse_window=20,
    mfs_prominence=25,
    sb_prominence=20,
)
```

## Key Options

| Option | Description | Default |
|--------|-------------|---------|
| `var-window-size` | Windowed variance cost window (§12.3) | = coarse_window |
| `min-bed-thickness` | Post-filter: warn about thin beds (§12.4) | 0 (off) |
| `cost-floor` | Minimum cost to suppress noise paths (§12.7) | 0.01 |

## Why It Matters

Without hierarchical constraints, DTW on noisy logs produces:

1. Path "shortcuts" through noisy intervals
2. Geologically implausible correlations across unconformities
3. Over-sensitive results that change with small parameter tweaks

With hierarchical constraints:

1. Major surfaces are locked → DTW resolves detail within intervals
2. Noise cannot propagate across locked boundaries
3. Results are more robust and geologically consistent

## Reference

- Baville (2022) §6.3.5 — Multi-scale correlation
- Catuneanu (2006) — *Principles of Sequence Stratigraphy*
- Van Wagoner et al. (1990) — *Siliciclastic Sequence Stratigraphy*
