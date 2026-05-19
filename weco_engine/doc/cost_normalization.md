# Cost Function Normalization Guide

> Reference: Baville (2022) §6.3.5 — *"The proposed correlation cost normalization, 0 ≤ c ≤ 1,
> makes it possible to define multi-criteria correlation costs."*

## Principle

For WeCo's multi-criteria cost function to work correctly, **all cost components must be
normalized to the same range** [0, 1] before combination.  When costs have incompatible
scales, the component with the largest magnitude dominates and effectively "blinds" the
others.

## Current Normalization Status

### Built-in C++ Cost Functions

| Component | Option(s) | Normalized? | Range | Notes |
|-----------|-----------|:-----------:|-------|-------|
| **Variance** (`_CCFPartVariance`) | `var-data`, `var-weight` | **Yes** | [0, 1] | Divides by total data variance (`dest_var()` normalizer) |
| **Gap** (transition cost) | `const-gap-cost`, `func-gap-cost`, `gap-polarity` | **Yes** | [0, const_gap_cost] | User-controlled constant; typically 0.0–1.0 |
| **Same Region** | `same-region`, `same-region-weight` | **Yes** | [0, weight] | Binary: 0 if same region, weight if different |
| **No Crossing** | `no-crossing` | **Yes** | {0, ∞} | Binary hard constraint: 0 or infinite cost |
| **Distality** (`_CCFPartDistal`) | `dist-facies`, `dist-distal`, `dist-scaling` | **Yes** | [0, 0.9] | Eq. 3.19 in thesis: `0.9 × (scaled_Δdistal − Δfacies)²` |
| **Multi-Distality** | multiple dist slots | **Yes** | [0, 0.9] per slot | Same formula as single distality |
| **B3D Curve** (`_CCFPartB3DCurve`) | `b3d-*` | **YES** ✅ | [0, ∞) | Normalized by characteristic area $A_0 = (h_1+h_2) \cdot d/2$ via `b3d-curve-normalize` (default: true) |
| **B3D Patch** (`_CCFPartB3DPatch`) | `b3d-*` | **YES** ✅ | [0, ∞) | Normalized by characteristic volume $(h_1+h_2+h_3) \cdot S/3$ via `b3d-patch-normalize` (default: true) |

### Python Cost Function Plugins

| Component | Module | Normalized? | Range | Notes |
|-----------|--------|:-----------:|-------|-------|
| **BiozonAgeCost** | `weco.cost_functions` | **Yes** | [0, weight] | Squared normalized age difference |
| **FaciesGroupCost** | `weco.cost_functions` | **Yes** | [0, weight] | Normalized group distance |
| **TransportDirectionCost** | `weco.cost_functions` | **Yes** | [0, weight] | Distality variance ratio |

## Known Issues

### B3D Cost Normalization (§13.4) — RESOLVED

The B3D (Bézier-3D) curve and patch cost functions compute a geometric
integral — the area (2D) or volume (3D) between the actual and ideal B3D profile.

Normalization is now implemented via engine options:
- `b3d-curve-normalize` (default: `true`) — divides by $A_0 = (h_1 + h_2) \cdot d / 2$
- `b3d-patch-normalize` (default: `true`) — divides by $V_0 = (h_1 + h_2 + h_3) \cdot S / 3$

This brings B3D costs into a comparable range with other normalized cost functions.

**Status:** ✅ Implemented in C++ engine (`src/ccf_b3d.cpp`).

## Best Practices

1. **Check cost magnitudes:** After a run, compare the per-component costs in the debug
   output (`debug-cor-info = 1`).  If one component is 10× larger than others, it
   dominates.

2. **Use weights judiciously:** The `var-weight`, `same-region-weight` etc. should be
   used for *relative importance*, not for scale correction.  If you're using weights
   > 5 to compensate for scale mismatch, the underlying cost is probably not normalized.

3. **Python plugins are pre-normalized:** The `BiozonAgeCost`, `FaciesGroupCost`, and
   `TransportDirectionCost` plugins are designed to output costs in [0, weight], so they
   combine safely with the built-in variance and gap costs.

4. **Avoid mixing B3D with distality** until B3D normalization is fixed (§13.4).

## Combination Modes

Currently the engine **sums** all cost components.  The weighted-average mode proposed
in the thesis (§13.8.2) is not yet implemented:

| Mode | Formula | Status |
|------|---------|--------|
| **Sum** (default) | $c = \sum_i w_i \cdot c_i$ | ✅ Implemented |
| **Weighted average** | $c = \frac{\sum_i w_i \cdot c_i}{\sum_i w_i}$ | ⬜ Proposed |
| **Product** | $c = \prod_i c_i^{w_i}$ | ⬜ Proposed |

For the sum mode, normalization is essential to prevent one component from dominating.
For weighted average, it would also ensure that the total cost stays in [0, 1].

---

## Extended Theory — Thesis Reference

### Distality Parameter Audit

| Parameter | Thesis Ref | Equation | Description |
|-----------|-----------|----------|-------------|
| `Δf` | Eq. 3.15 | $\Delta f_{ij} = \|f_i - f_j\|$ | Facies distance (integer difference) |
| `Δd` | Eq. 3.16 | $\Delta d_{ij} = \|d_i - d_j\| / d_{\max}$ | Normalised distality difference |
| `scaling` | Eq. 3.17 | $s = \text{dist\_scaling}$ | User scaling factor |
| Cost | Eq. 3.19 | $c = 0.9 \times (s \cdot \Delta d - \Delta f)^2$ | Final distality cost |
| `facies-groups` | New | Group-aware Δf | Groups similar facies to reduce penalty |

### Facies Clustering Theory (Electrofacies)

WeCo uses K-means clustering on multi-log data to derive discrete
electrofacies zones.  This is justified because:

- Log curves respond to bulk rock properties (porosity, clay content)
- K-means clusters in log space approximate depositional facies
- Clusters become input regions for the distality cost function

**Preprocessing chain:** raw logs → normalise → K-means(k=3–8) → assign
region → use as `dist-facies` in correlation.

### Thickness Constraint Equation

From Baville (2022) §6.3.2 — proposed but not yet in C++ engine:

$$c_{\text{thick}} = w_t \cdot \left(\frac{|\Delta h_{ij} - \Delta h_{\text{exp}}|}{\Delta h_{\text{exp}}}\right)^2$$

Where $\Delta h_{ij}$ is the correlated thickness between wells $i$ and $j$,
and $\Delta h_{\text{exp}}$ is the expected thickness ratio from the conceptual
depositional model.  This cost penalises correlations that produce geologically
implausible thickness changes.

### Multi-Criteria Combination Framework

The composite cost function combines N terms:

$$c_{\text{total}} = \sum_{k=1}^{N} w_k \cdot c_k(i, j)$$

Where each $c_k$ is normalized to [0, 1] and $w_k$ is the user weight.
Current terms: variance, gap, distality, B3D, same-region, no-crossing,
polarity, biozone age, facies group, transport direction, rate decline.

### Production Data Integration

`RateDeclineCost` penalises correlating reservoir intervals whose
decline-curve parameters differ significantly:

$$c_{\text{rate}} = w_r \cdot \frac{|q_i(t) - q_j(t)|}{q_{\max}}$$

This is available as a Python `CCFPartExt` plugin and does not require
C++ engine changes.
