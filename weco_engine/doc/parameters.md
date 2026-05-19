# WeCo Parameter Reference

> **WeCo v0.9.31** — Multi-well correlation engine  
> Comprehensive guide to all parameters, their geological meaning, and recommended settings.

---

## Table of Contents

1. [Quick-Start Recipes](#quick-start-recipes)
2. [Parameter Importance Ranking](#parameter-importance-ranking)
3. [Global Options](#1-global-options)
4. [Graph / DTW Options](#2-graph--dtw-options)
5. [Variance Cost](#3-variance-cost)
6. [Constraints](#4-constraints)
7. [Gap Cost](#5-gap-cost)
8. [Distality / Walther's Law](#6-distality--walthers-law)
9. [Polarity](#7-polarity)
10. [Multi-Distality](#8-multi-distality)
11. [B3D Curve / Patch](#9-b3d-curve--patch)
12. [Output & Debug](#10-output--debug)
13. [Multiscale (Python)](#11-multiscale-python)
14. [Ordering Strategies](#12-ordering-strategies)
15. [Cost Function Architecture](#13-cost-function-architecture)
16. [Option File Format](#14-option-file-format)
17. [Test Generation](#15-test-generation)

---

## Quick-Start Recipes

### Recipe A — Simple log correlation (2–6 wells, one log curve)

```
cost_function = composite
order         = pyramidal
var_data      = GR
var_weight    = 1.0
max_cor       = 50
nbr_cor       = 50
out_nbr_cor   = 5
```

### Recipe B — Two-log correlation with no-crossing constraint

```
cost_function  = composite
order          = pyramidal
var_data       = GR
var_weight     = 0.7
var_data2      = RHOB
var_weight2    = 0.3
no_crossing    = ZONES
max_cor        = 100
nbr_cor        = 50
out_nbr_cor    = 10
```

### Recipe C — Facies-distality (Walther's Law) correlation

```
cost_function = composite
order         = distality
dist_distal   = DISTALITY
dist_facies   = FACIES
dist_scaling  = 0.8
max_cor       = 200
nbr_cor       = 100
out_nbr_cor   = 10
```

### Recipe D — Full kitchen sink (variance + constraints + gap + distality)

```
cost_function    = composite
order            = position
var_data         = GR
var_weight       = 0.5
var_data2        = AI
var_weight2      = 0.5
no_crossing      = SEQUENCE
same_region      = FACIES
dist_distal      = DISTALITY
dist_facies      = PALEO_BATHY
dist_scaling     = 0.7
const_gap_cost   = 0.3
max_cor          = 200
nbr_cor          = 100
out_nbr_cor      = 10
thread           = 0
```

---

## Parameter Importance Ranking

Parameters ranked by how much they affect correlation quality:

| Rank | Parameter | Impact | When to Tune |
|------|-----------|--------|--------------|
| ★★★★★ | `var_data` | **Critical** | Always — this is what drives the correlation |
| ★★★★★ | `order` | **Critical** | Always — wrong order = bad merge tree |
| ★★★★☆ | `max_cor` | **High** | If best cost is suspiciously high |
| ★★★★☆ | `no_crossing` | **High** | When you have known stratigraphic markers |
| ★★★★☆ | `dist_distal` + `dist_facies` | **High** | For basin transects with palaeo-geography |
| ★★★☆☆ | `var_weight` / `var_weight2` | **Medium** | When using 2+ logs |
| ★★★☆☆ | `const_gap_cost` | **Medium** | When too many/few hiatuses appear |
| ★★★☆☆ | `dist_scaling` | **Medium** | Tuning wedge vs. tabular geometry |
| ★★☆☆☆ | `nbr_cor` | **Low-Med** | If memory is an issue; usually = max_cor |
| ★★☆☆☆ | `same_region` | **Low-Med** | When lithostratigraphic units are well-known |
| ★★☆☆☆ | `out_nbr_cor` | **Low** | Only affects output count, not quality |
| ★☆☆☆☆ | `thread` | **Negligible** | Performance only; 0 = auto |
| ★☆☆☆☆ | `min_dist` | **Negligible** | Rarely needed |

---

## 1. Global Options

| Parameter | Type | Default | Range | Description |
|-----------|------|---------|-------|-------------|
| `cost_function` | select | `"composite"` | `composite` | Cost framework. Only "composite" is built-in. Custom plugins can register alternatives via the C ABI. |
| `order` | select | `"pyramidal"` | `linear`, `pyramidal`, `position`, `distality`, `inverse` | How wells are paired and merged. See [Ordering Strategies](#12-ordering-strategies). |
| `thread` | int | `0` | 0–128 | CPU threads. **0** = auto-detect all cores. **1** = deterministic single-threaded. |

### Geological guidance

- **`order`** is often the single most impactful choice after selecting your data.
  Merging geologically adjacent wells first yields better results because the DTW
  has access to more similar data in early merge steps.
- For a **linear transect** (wells in a line), use `linear` or `inverse`.
- For **scattered wells**, use `position` (nearest-pair by coordinates).
- For **basin cross-sections** with known proximal-distal gradient, use `distality`.
- For **4+ wells** without strong spatial bias, `pyramidal` is the safest default.

---

## 2. Graph / DTW Options

These control the n-best DTW algorithm's quality–speed trade-off.

| Parameter | Type | Default | Range | Description |
|-----------|------|---------|-------|-------------|
| `max_cor` | int | `50` | 1–10000 | Maximum n-best paths kept **during** each DTW merge step. The "k" in k-best DTW. |
| `nbr_cor` | int | `50` | 1–10000 | Paths kept **after** a merge step for the next step. Must be ≤ `max_cor`. |
| `min_dist` | float | `0.0` | 0–∞ | Minimum cost-distance between two kept paths (diversity filter). 0 = disabled. |
| `out_nbr_cor` | int | `5` | 1–1000 | Number of alternative correlations in the **final output**. |
| `out_min_dist` | float | `0.0` | 0–∞ | Minimum cost-distance between output correlations. |

### How they relate

```
DTW step:  explore max_cor paths  →  prune to nbr_cor  →  pass to next merge
                                                              ↓
Final:     pick out_nbr_cor cheapest (min out_min_dist apart)
```

### Tuning guide

| Scenario | `max_cor` | `nbr_cor` | Typical runtime |
|----------|-----------|-----------|----------------|
| Quick demo | 10–20 | 10–20 | < 1 sec |
| Good default | 50 | 50 | ~0.1 sec (3 wells × 100 markers) |
| Production quality | 200–500 | 100–200 | 1–5 sec |
| Exhaustive search | 1000+ | 500+ | 10+ sec |

**Rule of thumb:** If your best correlation cost seems high, double `max_cor` before
changing any other parameter. If it doesn't improve, the problem is in costs, not search depth.

---

## 3. Variance Cost

Minimises the variance of selected well-log curves across correlated positions.
This is the most common primary cost function for log-based correlation.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `var_data` | data | `""` | Primary log name (e.g. `GR`, `RHOB`, `AI`). **Required** to activate variance. |
| `var_weight` | float | `1.0` | Weight for log 1. Range 0–100. |
| `var_data2` | data | `""` | Second log (optional). |
| `var_weight2` | float | `1.0` | Weight for log 2. |
| `var_data3` | data | `""` | Third log (optional). |
| `var_weight3` | float | `1.0` | Weight for log 3. |
| `var_data4` | data | `""` | Fourth log (optional). |
| `var_weight4` | float | `1.0` | Weight for log 4. |
| `var_data5` | data | `""` | Fifth log (optional). |
| `var_weight5` | float | `1.0` | Weight for log 5. |
| `var_region` | region | `""` | Region providing cost bonus at matching boundaries. |

### Algorithm

For each candidate correlation position, the cost is:

$$\text{cost} = \sum_{i=1}^{5} w_i \cdot \text{Var}(x_{i,1}, x_{i,2}, \ldots, x_{i,n})$$

where $x_{i,j}$ is the value of log $i$ in well $j$ at the correlated depth,
and only non-gap wells contribute.

This is a **dest-only** cost (depends only on the destination node, not the
transition), which enables a faster DTW variant.

### Geological meaning

- **Gamma Ray (GR):** Good general-purpose log. High GR = shale, low GR = sand.
  Correlating on GR implicitly matches lithological boundaries.
- **Acoustic Impedance (AI):** Excellent for seismic-tied wells. Correlates
  reflector-equivalent surfaces.
- **Resistivity:** Good for fluid-contact correlation but affected by locally
  varying fluid saturation.
- **Multiple logs:** Using 2–3 complementary logs (e.g. GR + density + sonic)
  produces more robust correlations than a single curve. Weight the most reliable
  log higher.

### Weight tuning

When using two logs with very different amplitude ranges, normalise them first
or adjust weights so that neither dominates. The variance is computed on raw
values, so a curve with range 0–200 will dominate one with range 2.0–2.8 unless weights compensate.

---

## 4. Constraints

### No-Crossing (hard constraint)

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `no_crossing` | region | `""` | Region 1 whose zone boundaries cannot be crossed. |
| `no_crossing2` | region | `""` | Region 2 (independent hierarchy). |
| `no_crossing3` | region | `""` | Region 3. |

**Algorithm:** Returns `false` (infinite cost → path eliminated) if any correlation line
would cross a zone boundary. This is a **dest-only** hard constraint.

**Geological meaning:** Think of this as "dated tie-points" or "known horizons."
If you've identified biostratigraphic datum planes, sequence boundaries, or
volcanic ash beds that are definitely time-equivalent across wells, encode them
as region boundaries and set `no_crossing` to enforce them.

**⚠ Important:** Region IDs must be consistent across wells. Region 3 in Well A
must correspond to the same geological unit as Region 3 in Well B.

### Same-Region (soft constraint)

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `same_region` | region | `""` | Region 1 — correlated positions must share the same label. |
| `same_region2` | region | `""` | Region 2. |
| `same_region3` | region | `""` | Region 3. |

**Algorithm:** Returns `false` if the non-gap wells at a destination position don't
all share the same region value. Unlike `no_crossing`, this checks the region
**identity** at the destination (not boundary ordering).

**Geological meaning:** "These wells must correlate within the same lithostratigraphic
unit." Appropriate when you're confident in your facies interpretation but don't want
to fully constrain boundary positions.

**Caution:** `same_region` can be very restrictive. If your region assignments are
slightly inconsistent (e.g. one well has an extra thin zone), it can cause "no
correlation possible." Start without it and add it only if you trust the region picks.

---

## 5. Gap Cost

Controls how the engine penalises stratigraphic gaps (hiatuses, condensation, erosion).

### Constant Gap Cost

| Parameter | Type | Default | Range | Description |
|-----------|------|---------|-------|-------------|
| `const_gap_cost` | float | `0.0` | 0–100 | Flat penalty per gap. **0 = gaps are free.** |
| `const_gap_cost_start` | float | `-1.0` | -1–100 | Gap cost at well top. -1 = use `const_gap_cost`. |
| `const_gap_cost_end` | float | `-1.0` | -1–100 | Gap cost at well base. -1 = use `const_gap_cost`. |

### Data-Driven Gap Cost

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `gap_cost_func` | data | `""` | Data property providing per-sample gap cost. |
| `gap_cost_func_mult` | float | `1.0` | Multiplier applied to gap cost values. |

### Geological interpretation

| `const_gap_cost` | Effect | Geological scenario |
|-------------------|--------|---------------------|
| `0.0` | Gaps are free | Only log similarity matters (exploratory) |
| `0.05–0.2` | Mild penalty | Allow gaps where needed (normal sedimentary sections) |
| `0.5–1.0` | Moderate penalty | Prefer continuous correlation (aggradational sections) |
| `5.0–10.0` | Strong penalty | Force "layer-cake" correlation (tabular stratigraphy) |

**When to use `gap_cost_func`:** If you have a compaction or sedimentation-rate curve,
use it to make gaps cheaper in expanded intervals (high sed-rate zones where erosion
is more likely) and expensive in condensed sections.

**Start/end gap cost:** Set a lower `const_gap_cost_start` / `_end` when the top/base
of wells are poorly constrained (e.g. unconformity at top, TD at base). Set higher
when you have firm picks at the section boundaries.

---

## 6. Distality / Walther's Law

Models lateral facies belt thickness variation as a function of palaeo-geographic
position. This is the key cost function for **sequence-stratigraphic correlation**.

| Parameter | Type | Default | Range | Description |
|-----------|------|---------|-------|-------------|
| `dist_distal` | region | `""` | — | Palaeo-distality of well position. Values: distal(1) → proximal(n). **Both `dist_distal` and `dist_facies` required.** |
| `dist_facies` | region | `""` | — | Palaeo-bathymetric facies. Values: deepest(1) → shallowest(n). |
| `dist_scaling` | float | `1.0` | -1.0 to 1.0 | Scaling coefficient for the wedge model. |

### Algorithm

For the two rightmost wells being merged, the cost is:

$$\text{cost} = 0.9 \times \left(\text{scaling} \times \frac{|\Delta\text{distal}|}{d_0} - \frac{|\Delta\text{facies}|}{f_0}\right)^2$$

Where:
- $\Delta\text{distal}$ = difference in distality values between wells
- $\Delta\text{facies}$ = difference in facies values between correlated positions
- $d_0$, $f_0$ = normalisation factors

Transitions that violate Walther's Law (facies increase but distality decreases)
are **rejected** (infinite cost).

Gap cost = 1.0 (full penalty for every gap).

### Geological meaning

**Walther's Law** states that the vertical succession of facies in a well corresponds
to the lateral arrangement of depositional environments. In a regressive sequence:
- Proximal wells have thick shallow-water facies, thin deep-water facies.
- Distal wells have thick deep-water facies, thin shallow-water facies.

The distality cost models this as **thickness wedging**: facies far from the well's
palaeo-position are expected to be thinner.

### `dist_scaling` tuning

| Value | Geometry | When to use |
|-------|----------|-------------|
| `1.0` | Strong wedge (clinoforms) | Progradational margins, shelf-to-basin transects |
| `0.5` | Moderate wedge | Mixed prog/aggradation |
| `0.0` | Tabular (no wedging) | Aggradational stacking, platform interiors |
| `-1.0` | Inverse wedge | Testing only |

### Data preparation

1. **Distality region:** Assign each well a relative position from distal (1) to proximal (n).
   This can come from palaeo-geographic reconstructions, biostratigraphic data,
   or seismic facies interpretation.
2. **Facies region:** Assign each sample an environment code from deepest (1) to shallowest (n).
   Example: 1=basinal, 2=outer shelf, 3=inner shelf, 4=coastal.

---

## 7. Polarity

Penalises gaps based on magnetic/stratigraphic polarity matching.

| Parameter | Type | Default | Range | Description |
|-----------|------|---------|-------|-------------|
| `polarity_region` | region | `""` | — | Region encoding polarity. **Required** to activate. |
| `polarity_cost_diff` | float | `0.5` | 0–100 | Gap cost when polarity **differs** between sides. |
| `polarity_cost_same` | float | `0.5` | 0–100 | Gap cost when polarity is the **same**. |
| `polarity_cost_start` | float | `0.5` | 0–100 | Gap cost at well top. |
| `polarity_cost_end` | float | `0.5` | 0–100 | Gap cost at well base. |

### Algorithm

Full cost (not dest-only). All non-gap wells at the destination must share the
same polarity value. For gap wells, cost depends on whether the polarity matches.

### Geological meaning

Used for **magnetostratigraphic** or **chemostratigraphic** polarity matching.
Set `polarity_cost_diff` > `polarity_cost_same` to penalise gaps that cross
polarity reversals more than gaps within the same polarity zone.

---

## 8. Multi-Distality

Explores multiple palaeo-geographic scenarios when the distality ranking is uncertain.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `multi_dist_distal` | string | `""` | File path with N distality scenarios. |
| `multi_dist_facies` | region | `""` | Facies log (same semantics as `dist_facies`). |
| `multi_dist_scaling` | float | `1.0` | Scaling coefficient. |

### Scenario file format

```
3                   # number of scenarios
1 2 3 4             # scenario 1: well distalities (distal→proximal)
1 3 2 4             # scenario 2: alternative ordering
2 1 3 4             # scenario 3: another alternative
```

The engine evaluates all scenarios and picks the combination yielding the lowest total cost.

### When to use

When you don't know the palaeo-geography with certainty. For example, if wells A
and B could be in either distal or proximal position, provide both orderings and let
the DTW find which fits the data better.

---

## 9. B3D Curve / Patch

Advanced structural cost function using 3D Bézier curve/surface fitting.

### B3D Curve (2-well)

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `b3d_curve_dip` | data | `""` | Dip angle (degrees). All 4 data required to activate. |
| `b3d_curve_azimuth` | data | `""` | Strike orientation (degrees). |
| `b3d_curve_depth` | data | `""` | True vertical depth (TVD). |
| `b3d_curve_facies` | data | `""` | Palaeo-depth environmental facies. |
| `b3d_curve_write_bezier` | bool | `false` | Generate Bézier curve point sets. |
| `b3d_curve_write_profile` | bool | `false` | Generate depositional profile files. |
| `b3d_curve_bezier_folder` | string | `""` | Output folder for Bézier files. |
| `b3d_curve_profile_folder` | string | `""` | Output folder for profile files. |
| `b3d_curve_dep_facies_file` | string | `""` | Facies configuration file. |
| `b3d_curve_dep_profile_file` | string | `""` | Depositional profile config. |

### B3D Patch (3-well surface fitting)

Same parameter structure with `b3d_patch_` prefix instead of `b3d_curve_`.

### Geological meaning

B3D fits smooth 3D surfaces (Bézier interpolation) to the correlated horizons using
measured structural dip and azimuth. The cost penalises correlations that would produce
geologically implausible surface geometries. This is the most advanced cost function
and requires high-quality dipmeter or image log data.

---

## 10. Output & Debug

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `out_file` | string | `"out.txt"` | Result file path (WeCo DAG format). |
| `out_dot` | string | `""` | Result as Graphviz DOT graph. |
| `step_dot` | string | `""` | Per-step DOT files (base name). |
| `step_file` | string | `""` | Per-step WeCo result files (base name). |
| `cost_matrix` | string | `""` | Cost matrix file. ⚠ Expensive. |
| `order_dot` | string | `""` | Merge-tree as DOT graph. |
| `order_only` | bool | `false` | Stop after ordering (no DTW). |
| `debug_cor_info` | bool | `false` | Print per-step statistics. |

### DOT visualisation

```bash
# Generate and view merge tree
weco ... order_dot=tree.dot
dot -Tpng tree.dot -o tree.png
```

---

## 11. Multiscale (Python)

These parameters are set on `MultiScaleProject`, not on the C++ engine options.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `ms_max_cor_per_scenario` | int | `5` | Max sub-correlations kept per coarse-level scenario. |
| `ms_one_well_cost` | float | `0.0` | Cost for single-well sub-problems. |
| `ms_out_res` | string | `"res.txt"` | Final multiscale result path. |

### Concept

Multiscale correlation divides the section vertically by a coarse region
(e.g. biozone), correlates within each zone independently, then combines
the per-zone solutions. This reduces the search space exponentially for long
sections with well-defined zonation.

**Workflow:**
1. Define a coarse region (e.g. `BIOZONES`) with 5–20 zones per well.
2. Run multiscale: engine correlates within each zone, then stitches results.
3. The final result honours zone boundaries identically to `no_crossing`.

---

## 12. Ordering Strategies

| Strategy | Function | Best for | How it works |
|----------|----------|----------|--------------|
| `linear` | Left-to-right sequential | Simple transects with wells in spatial order | W0+W1 → (W0-W1)+W2 → (W0-W2)+W3 → … |
| `pyramidal` | Balanced binary tree | **Default.** 4+ wells without strong spatial bias | (W0+W1) + (W2+W3) → merge |
| `position` | Nearest-pair by (x,y) | Scattered wells with spatial coordinates | BSP-tree clustering, merge nearest first |
| `distality` | Ordered by palaeo-distality | Basin transects with dist_distal | Most-distal wells first |
| `inverse` | Right-to-left sequential | When the rightmost wells are more similar | W(n-1)+Wn → (W(n-2))+(W(n-1)-Wn) → … |

### Why order matters

The merge-tree structure determines which information is available at each DTW step.
When nearby wells are merged first, the DTW sees similar data and produces a better
intermediate correlation. This "good foundation" propagates quality through subsequent
merge steps.

**Example:** For 6 wells in a west-to-east transect:
- `linear` merges W→E: good if the section is laterally continuous.
- `position` merges the two nearest wells first, which may skip a well.
- `pyramidal` merges (W0+W1)+(W2+W3) → (W4+W5) → final: balanced quality.

---

## 13. Cost Function Architecture

The **composite** cost function combines independent "parts" (components).
Each part independently returns a cost and a valid/invalid flag:

```
                              ┌── Variance (dest-only)
                              ├── Same-Region (dest-only)
Composite Cost = Σ of all  →  ├── No-Crossing (dest-only)
  active parts                ├── Polarity (full)
                              ├── Gap Cost (full)
                              ├── Const Gap Cost (full)
                              ├── Distal (full)
                              ├── Multi-Distal (full)
                              └── B3D Curve/Patch (full)
```

### Part types

- **dest-only** (`dest_cost`): Depends only on the destination node. Enables a
  faster DTW variant. Used as a pre-filter when mixed with full parts.
- **full** (`full_cost`): Depends on both source and destination (the transition).
  Required for gap penalties and structural costs.

### Activation rules

Each part activates **only if its required data exists** in the project well list:
- Variance activates if `var_data` names a property that exists.
- No-Crossing activates if `no_crossing` names a region that exists.
- Distal activates if **both** `dist_distal` and `dist_facies` name existing regions.

Parts whose data is missing are silently skipped (zero cost contribution).

### Cost combination

Costs are **additive**. A valid correlation node's total cost is the sum of all
active parts' costs. If **any** part returns `false` (infinite cost), the entire
node is eliminated.

### Plugin system

Custom cost functions can be registered via the C ABI plugin interface:
```c
// plugin .so exports:
WeCoPluginInfo* weco_plugin_info();
double weco_plugin_cost(int* positions, int n_wells, void* user_data);
```

---

## 14. Option File Format

Options can be set in three ways:

### Text files

```
# comment
cost-function = composite
var-data      = GR
max-cor       = 100
```

Hyphen-separated names. One option per line.

### Python API

```python
from weco import ProjectExt
p = ProjectExt()
p.set_options_ext(
    cost_function="composite",
    var_data="GR",
    max_cor=100,
)
p.run("wells.txt")
```

Underscore-separated names. `set_options_ext(**kwargs)` or
`set_option_ext("option-name", "value")`.

### Command line

```bash
weco --cost-function=composite --var-data=GR --max-cor=100 wells.txt
```

Hyphen-separated, prefixed with `--`.

### Name mapping

| Option file / CLI | Python API |
|-------------------|------------|
| `cost-function` | `cost_function` |
| `var-data` | `var_data` |
| `no-crossing` | `no_crossing` |
| `const-gap-cost` | `const_gap_cost` |
| `dist-distal` | `dist_distal` |

Simple rule: **hyphens ↔ underscores**.

---

## 15. Test Generation

The `TestBuilder` class creates synthetic well data for testing:

```python
from weco import TestBuilder

tb = TestBuilder(nbr_wells=4, size=50)
tb.add_sin_data("GR", wave_length=10, amplitude=1.0, noise=0.1, shift=0.5)
tb.add_depth_data("DEPTH")
tb.add_region1("ZONES", _max=5, _min=3)
tb.erode_start(_max=3, _min=1)
tb.erode_end(_max=5, _min=2)
wl = tb.build()
wl.write("test_wells.txt")
```

### Methods

| Method | Description |
|--------|-------------|
| `add_sin_data(name, λ, amp, noise, shift)` | Sinusoidal log (emulates cyclic stratigraphy) |
| `add_depth_data(name)` | Linear 0..size-1 depth curve |
| `add_region1(name, max, min)` | Random contiguous regions |
| `erode_start(max, min)` | Remove up to N samples from well tops |
| `erode_end(max, min)` | Remove up to N samples from well bases |
| `erode_parts(nbr, max, min)` | Remove random interior sections |
| `multiscale_from_region(region)` | Convert region to multiscale format |
| `multiscale_data(region, name, src)` | Create coarse data from fine region |

---

## Appendix: Complete Parameter Table

| Parameter | Type | Default | Category |
|-----------|------|---------|----------|
| `cost_function` | select | `composite` | Global |
| `order` | select | `pyramidal` | Global |
| `thread` | int | `0` | Global |
| `max_cor` | int | `50` | Graph |
| `nbr_cor` | int | `50` | Graph |
| `min_dist` | float | `0.0` | Graph |
| `out_nbr_cor` | int | `5` | Graph |
| `out_min_dist` | float | `0.0` | Graph |
| `var_data` | data | `""` | Variance |
| `var_weight` | float | `1.0` | Variance |
| `var_data2` | data | `""` | Variance |
| `var_weight2` | float | `1.0` | Variance |
| `var_data3` | data | `""` | Variance |
| `var_weight3` | float | `1.0` | Variance |
| `var_data4` | data | `""` | Variance |
| `var_weight4` | float | `1.0` | Variance |
| `var_data5` | data | `""` | Variance |
| `var_weight5` | float | `1.0` | Variance |
| `var_region` | region | `""` | Variance |
| `no_crossing` | region | `""` | Constraints |
| `no_crossing2` | region | `""` | Constraints |
| `no_crossing3` | region | `""` | Constraints |
| `same_region` | region | `""` | Constraints |
| `same_region2` | region | `""` | Constraints |
| `same_region3` | region | `""` | Constraints |
| `polarity_region` | region | `""` | Polarity |
| `polarity_cost_diff` | float | `0.5` | Polarity |
| `polarity_cost_same` | float | `0.5` | Polarity |
| `polarity_cost_start` | float | `0.5` | Polarity |
| `polarity_cost_end` | float | `0.5` | Polarity |
| `gap_cost_func` | data | `""` | Gap |
| `gap_cost_func_mult` | float | `1.0` | Gap |
| `const_gap_cost` | float | `0.0` | Gap |
| `const_gap_cost_start` | float | `-1.0` | Gap |
| `const_gap_cost_end` | float | `-1.0` | Gap |
| `dist_distal` | region | `""` | Distality |
| `dist_facies` | region | `""` | Distality |
| `dist_scaling` | float | `1.0` | Distality |
| `multi_dist_distal` | string | `""` | Multi-Distality |
| `multi_dist_facies` | region | `""` | Multi-Distality |
| `multi_dist_scaling` | float | `1.0` | Multi-Distality |
| `b3d_curve_dip` | data | `""` | B3D Curve |
| `b3d_curve_azimuth` | data | `""` | B3D Curve |
| `b3d_curve_depth` | data | `""` | B3D Curve |
| `b3d_curve_facies` | data | `""` | B3D Curve |
| `b3d_curve_write_bezier` | bool | `false` | B3D Curve |
| `b3d_curve_write_profile` | bool | `false` | B3D Curve |
| `b3d_curve_bezier_folder` | string | `""` | B3D Curve |
| `b3d_curve_profile_folder` | string | `""` | B3D Curve |
| `b3d_curve_dep_facies_file` | string | `""` | B3D Curve |
| `b3d_curve_dep_profile_file` | string | `""` | B3D Curve |
| `out_file` | string | `"out.txt"` | Output |
| `out_dot` | string | `""` | Output |
| `step_dot` | string | `""` | Output |
| `step_file` | string | `""` | Output |
| `cost_matrix` | string | `""` | Output |
| `order_dot` | string | `""` | Output |
| `order_only` | bool | `false` | Output |
| `debug_cor_info` | bool | `false` | Debug |
