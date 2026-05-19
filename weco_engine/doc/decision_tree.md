# WeCo Workflow Decision Tree

A guided workflow that recommends correlation parameters based on:
- **Geological environment** (auto-detected from data channels)
- **Data availability** (wireline, facies, biozones, etc.)
- **Data quality** (signal-to-noise, cross-correlation between wells)
- **Dataset size** (memory management for large well counts)

## Quick Start

```python
from weco.data import WellList
from weco.decision_tree import recommend_workflow, format_recommendation

wl = WellList()
wl.read("my_wells.txt")  # or .weco.json

rec = recommend_workflow(wl)
print(format_recommendation(rec))

# Use recommendations programmatically
print(rec.options)          # {'var_data': 'GR', 'max_cor': 30, ...}
print(rec.primary_channel)  # 'GR'
print(rec.warnings)         # ['Large dataset...']
```

## REST API

```bash
curl -X POST http://localhost:8000/workflow/recommend \
  -F "file=@data/data_set_coal/wells.txt"
```

Returns JSON with options, warnings, and reasoning.

## Decision Nodes

### 1. Well Count → Performance Settings

| Wells | max_cor | nbr_cor | band_width | Notes |
|-------|---------|---------|------------|-------|
| ≤ 10  | 50      | 5       | —          | Full resolution safe |
| 11–50 | 30      | 5       | —          | Balanced quality/memory |
| > 50  | 20      | 3       | 30         | Memory protection essential |

### 2. Geological Environment Detection

Detected automatically from channel names and region names:

| Environment | Key Channels | Key Regions | Confidence Trigger |
|-------------|-------------|-------------|-------------------|
| Coal Basin | GR, DEN, RT, SON | SEAM, LITH | DEN + SEAM region |
| Shallow Marine | GR, NPHI, RHOB, DT, RT | FACIES, BIOZONE | Multiple wireline + BIOZONE |
| Deep Marine | GR, NPHI, RHOB, DISTALITY | FACIES, BIOZONE, SEQUENCE | DISTALITY + SEQUENCE |
| Fluvial/Deltaic | GR, FACIES, SP | FACIES, STRAT | SP + channel facies |
| Paralic/Estuarine | FACIES, ZONE | FACIES, ZONE | ZONE region dominance |
| Carbonate | GR, NPHI, RHOB, PE | FACIES, BIOZONE | PE present |
| Continental/Quaternary | GR, RT, MS, COND, SPT | FACIES, HYDRO, STRAT | MS or COND + STRAT |

### 3. Primary Channel Selection

Priority order per environment (first available non-noise channel wins):

- **Coal**: DEN > GR > RT > SON
- **Shallow Marine**: GR > NPHI > RHOB > DT > FACIES > DISTALITY
- **Deep Marine**: GR > NPHI > RHOB > FACIES > DISTALITY
- **Fluvial**: GR > FACIES > SP
- **Paralic**: FACIES > ZONE > GR
- **Carbonate**: GR > NPHI > PE > RHOB
- **Continental**: GR > MS > RT > COND

### 4. Region Constraints

Automatically detected and recommended:
- **Biozone** regions → hard chronostratigraphic boundaries
- **Sequence** regions → major depositional cycle limits
- **Facies** regions → same_region constraint for facies matching

### 5. Noise Risk Assessment

| Cross-correlation | Interpretation | Action |
|-------------------|----------------|--------|
| > 0.3 | Good signal | Proceed normally |
| 0.1 – 0.3 | Moderate | Consider adding region constraints |
| < 0.1 | Noise risk | Switch to facies, add band_width, reduce max_cor |

### 6. Lateral Variability

- **Continental/Fluvial**: min_dist=0.1 (need diverse solutions)
- **Paralic**: min_dist=0.05
- **Marine**: Default (optimizer finds best without diversity constraint)

## Example Outputs

### Coal Basin (10 wells, wireline data)
```
Strategy: Coal Basin | primary=DEN | max_cor=30 | order=position
```

### Quaternary (100 wells, shallow continental)
```
Strategy: Continental Quaternary | primary=GR | constrained by STRAT | ⚠ 1 warning
Warning: Large dataset (100 wells): using band_width=30, max_cor=20
```

### North Sea Biostratigraphy (3 wells, facies+biozone)
```
Strategy: Shallow Marine | primary=FACIES6 | constrained by BIOZONE, SEQUENCE
```
