# Per-Domain Correlation Strategy Guide

## 1. Hydrogeology (Quaternary)

**Setting**: Shallow glacial deposits, 3 aquifer zones separated by till/clay aquitards.

**Recommended Options**:
- `var_data`: GR (gamma ray distinguishes sand from clay)
- `var_data2`: RT (resistivity separates saturated aquifer from aquitard)
- `var_weight / var_weight2`: 0.7 / 0.3
- `order`: position (wells correlated in geographic order)
- `const_gap_cost`: 1.5 (moderate - some units pinch out)
- `no_crossing`: UNIT (if lithostratigraphy available)

**Expected Results**: Clear aquifer/aquitard layering. Watch for:
- Glaciotectonic disturbance (folded/thrusted units)
- Channel-fill sand lenses in till
- Periglacial features (ice wedges) that disrupt continuity

---

## 2. Coal Basin

**Setting**: Multiple coal seams with clastic interbeds, marine bands as regional markers.

**Recommended Options**:
- `var_data`: GR (coal = very low GR, marine band = high GR)
- `var_data2`: DEN (coal ≈ 1.3 g/cc vs rock ≈ 2.5 - the strongest signal)
- `var_weight / var_weight2`: 0.4 / 0.6 (DEN is more diagnostic)
- `order`: position
- `const_gap_cost`: 3.0 (seams should not be skipped easily)
- `band_width`: 10 (coal seams are thin markers in long boreholes - tight
  band-width reflects the layer-cake geometry)
- `no_crossing`: MARINE_BAND (marine bands are laterally continuous)

**Expected Results**: Seam-to-seam correlation with high confidence. Coal
datasets often have a **single optimal solution** because DEN contrast is
so diagnostic that there's no ambiguity. Watch for:
- Seam splits (one seam becomes two - increase `max_cor`)
- Washout zones (missing coal - allow moderate gaps)
- Marine bands provide the strongest constraints

---

## 3. Shallow Marine (Oil Reservoir)

**Setting**: Hugin Fm analogue, 8 facies, clinoform geometry with lateral distality change.

**Recommended Options**:
- `var_data`: GR, `var_data2`: RHOB, `var_data3`: DT
- Weights: 0.5 / 0.3 / 0.2
- `order`: distality (correlate from proximal to distal)
- `dist_distal`: DISTAL region
- `dist_facies`: FACIES region
- `const_gap_cost`: 2.0
- `no_crossing`: BIOZONE (if available)

**Expected Results**: Parasequence-scale correlation. Watch for:
- Shingling at clinoform toes
- Condensation in distal wells
- Facies transitions within time-equivalent packages

---

## 4. Delta Front / Prodelta

**Setting**: Prograding parasequences with GR/DEN/NPHI.

**Recommended Options**:
- `var_data`: GR, `var_data2`: DEN
- Weights: 0.6 / 0.4
- `order`: position (dip-direction geographic order)
- `const_gap_cost`: 1.0 (allow some condensation)

**Expected Results**: Clinoform surfaces and flooding surfaces.

---

## 5. Fluvial Channel Belt

**Setting**: Laterally discontinuous sandbodies, meandering channels.

**Recommended Options**:
- `var_data`: GR
- `var_weight`: 1.0
- `order`: position
- `const_gap_cost`: 0.5 (low - channels are often not laterally continuous)
- `band_width`: 60 (wide - channel bodies can be at very different
  depths in adjacent wells due to avulsion/lateral migration)
- `min_dist`: 0.4 (moderate forcing - fluvial has inherent ambiguity
  but strong global optima with many wells)

**Expected Results**: This is the hardest setting for DTW-based correlation.
With 20+ wells the combinatorial constraints narrow solutions significantly;
expect 2–3 genuinely distinct scenarios. The wide band-width allows the
algorithm to find channels that jump stratigraphic position between wells.

**Tip**: Consider using `hierarchical_correlate()` with MFS/SB detection
to lock major flooding surfaces before resolving within intervals.
