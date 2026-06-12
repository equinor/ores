# WeCo Usage Guide - From Data to Interpretation

> Practical workflow guide for setting up well correlation projects.
> Covers data preparation, parameter selection by depositional environment,
> sampling strategy, and interpreting uncertainty.

---

## Table of Contents

1. [Philosophy: Signal vs Noise](#1-philosophy-signal-vs-noise)
2. [Data Preparation Workflow](#2-data-preparation-workflow)
3. [Sampling & Resolution](#3-sampling--resolution)
4. [Data Types by Depositional Environment](#4-data-types-by-depositional-environment)
5. [Constraint Selection](#5-constraint-selection)
6. [Parameter Tuning Strategy](#6-parameter-tuning-strategy)
7. [Scenario Design & Uncertainty](#7-scenario-design--uncertainty)
8. [Interpretation Checklist](#8-interpretation-checklist)
9. [Quick Reference Table](#9-quick-reference-table)

---

## 1. Philosophy: Signal vs Noise

The key principle: **more data ≠ better correlation**.

Over-detailed or over-interpreted input data adds noise that degrades
correlation quality. Every input channel should carry **independent
stratigraphic signal** - if it doesn't, it's noise.

### Rules of thumb

| Principle | Rationale |
|-----------|-----------|
| Start simple, add complexity | GR-only baseline first; add channels/constraints one at a time |
| Every addition must improve | If adding facies makes results LESS plausible → remove it |
| Consolidate before correlating | 15 facies classes → 3-5 meaningful groups |
| Validate, don't constrain with interpretations | Existing zone logs = check output, not input |
| Prefer objective data over interpretations | Measured logs > interpreted facies > published zones |
| Resolution should match the correlation target | Correlating sequences (10-50m) doesn't need 0.15m sampling |

### What causes autocorrelation (spurious signal)

- **Too-fine sampling** → adjacent samples nearly identical → DTW
  finds trivial local matches instead of structural alignment
- **Redundant channels** → GR + Vshale + CGR all measure the same thing;
  they triple-count clay content, not add information
- **Over-classified regions** → 15 biozone subdivisions where only 4
  are reliably distinct → many boundaries = many false constraints

---

## 2. Data Preparation Workflow

### Step 1: Inventory available data

For each well, catalogue:

| Category | Examples | Role in correlation |
|----------|----------|-------------------|
| **Measured logs** | GR, RHOB, DT, NPHI, RT | Primary correlation signal |
| **Derived curves** | AI, Vshale, Sw, PHIE | Only if independent from primary |
| **Picks/markers** | Flooding surfaces, sequence boundaries | Hard constraints (no-crossing) |
| **Biostratigraphy** | Biozone assignments by interval | Soft/hard constraint |
| **Facies** | Core facies, electrofacies, seismic facies | Distality cost |
| **Existing interpretations** | Zone logs, formation tops | Validation only |

### Step 2: Select independent channels

**Rule**: Don't use two channels that measure the same property.

| Redundant combination | Use instead |
|----------------------|-------------|
| GR + Vshale + CGR | GR only |
| RHOB + NPHI + PHIE | RHOB + NPHI (complementary; PHIE is derived from both) |
| AI + DT + RHOB | AI only (combines DT + RHOB) |
| DT + DTS | DT only (unless Vp/Vs ratio is the target) |

**Good combinations** (each adds independent information):

| Combination | Why it works |
|-------------|-------------|
| GR + RHOB | Clay vs density - different physics |
| GR + NPHI | Clay vs hydrogen index - orthogonal in crossplot |
| GR + DT | Clay vs compaction/fluid - different scales |
| GR + RT | Clay vs fluid saturation |

### Step 3: Consolidate categorical data

Raw data often has too many classes. Consolidate to capture **process, not detail**:

| Raw input | Problem | Consolidated version |
|-----------|---------|---------------------|
| 12 biozone subdivisions | Only 4 reliably identified in all wells | 4 biozone groups |
| 15 core facies codes | Many are sub-environments of the same process | 3-5 depositional associations |
| Named formation tops (40 picks) | Most are local, not regional | 3-5 sequence boundaries present in ALL wells |

**Critical rule for no-crossing constraints**: A zone boundary used in
`no-crossing` MUST exist in ALL wells. If well A has boundary X→Y but
well B doesn't, correlation between those wells is impossible.

### Step 4: Ensure consistency across wells

Before running WeCo, verify:

- [ ] All wells have the **same data channels** (use -999.25 for missing values)
- [ ] Channel names are **identical** across wells (case-sensitive)
- [ ] Region names used in constraints exist in **every well**
- [ ] Coordinate system is consistent (same CRS, same units)
- [ ] Depth reference is consistent (TVD from same datum, or MD with trajectory)

### Step 5: Choose sampling resolution

See [§3 Sampling & Resolution](#3-sampling--resolution).

---

## 3. Sampling & Resolution

### The right resolution depends on your target

| Correlation target | Thickness scale | Recommended sampling | Example |
|-------------------|-----------------|---------------------|---------|
| Parasequences | 2–10 m | 0.5–1.0 m | Coal seams, shoreface cycles |
| Sequences / systems tracts | 10–50 m | 1.0–2.0 m | Flooding surfaces |
| Regional formations | 50–200 m | 2.0–5.0 m | Basin-scale framework |
| Metre-scale cyclicity | 0.5–2 m | 0.1–0.3 m | Milankovitch cycles |

### Why coarser is often better

| Finer (0.15m) | Coarser (1.5m) |
|---------------|----------------|
| 549 samples / 80m interval | 53 samples / 80m interval |
| DTW: ~90 seconds per pair | DTW: ~5 seconds per pair |
| Captures bed-scale detail (noise) | Captures sequence-scale signal |
| Many local optima in cost landscape | Smoother cost landscape, clearer global minimum |
| Autocorrelation between adjacent samples | Each sample is quasi-independent |

### How to resample

```python
# In rebuild scripts: skip samples closer than threshold
resampled = [samples[0]]
for s in samples[1:]:
    if s.tvd - resampled[-1].tvd >= RESAMPLE_INTERVAL:
        resampled.append(s)
```

For continuous logs (GR, RHOB), use **block-average** or **median** over the
resampling interval to suppress spike noise. For categorical data (facies),
use **majority vote** within each block.

### Performance rule of thumb

DTW complexity scales as O(n × m) per well pair, where n and m are sample
counts. With n-best paths (`max_cor`), effective cost is O(n × m × max_cor).

| Wells | Samples/well | max_cor | Approx time |
|-------|-------------|---------|-------------|
| 6 | 50 | 50 | 2–5 s |
| 6 | 150 | 100 | 30–90 s |
| 6 | 500 | 100 | 5–15 min |
| 20 | 100 | 50 | 1–3 min |
| 20 | 100 | 200 | 5–10 min |

**Target: < 10 seconds** for interactive exploration.
Reduce samples or `max_cor` to stay responsive.

---

## 4. Data Types by Depositional Environment

### Which data drives correlation in each setting

| Environment | Primary signal | Secondary | Constraint | Notes |
|-------------|---------------|-----------|------------|-------|
| **Shallow marine (clastic)** | GR | RHOB or NPHI | Biozones, flooding surfaces | Facies-distality adds value if well-calibrated |
| **Deep marine (turbidites)** | GR | DT or AI | Biostratigraphy | High condensation in basin → allow gaps |
| **Fluvial / alluvial** | GR | - | None (channels are discontinuous) | Wide band-width; accept high uncertainty |
| **Deltaic** | GR | DEN | Flooding surfaces | Position-ordered along dip direction |
| **Carbonate platform** | GR + DEN | SON or PEF | Sequence boundaries | DEN is more diagnostic than GR in carbonates |
| **Coal measures** | DEN | GR | Marine bands | DEN separates coal (1.3) from rock (2.5) |
| **Evaporites** | GR + SON | DEN | Formation tops | Anhydrite/halite have extreme log responses |
| **Glacial / Quaternary** | GR | RT | Unit boundaries | Lateral variability is extreme |

### Data quality checklist per environment

**Shallow marine**: GR is king. RHOB adds porosity info (sand vs cemented
sand). Biozone constraints dramatically reduce uncertainty IF consistently
identified. Facies-distality works when you have 3+ wells in a
proximal-to-distal transect.

**Carbonates**: GR alone is insufficient (low-GR carbonates look alike).
DEN or SON differentiates facies (grain-supported vs mud-supported).
PEF distinguishes limestone from dolomite from anhydrite. Cycle stacking
patterns are the real signal - resample to capture cycle scale.

**Fluvial**: The hardest setting. Channel sandbodies are laterally
discontinuous by nature. Expect multiple valid solutions. Use:
- Low `const_gap_cost` (channels pinch out)
- Wide `band_width` (channels jump stratigraphic position)
- Many output solutions (`out_nbr_cor` = 10–20)
- Hierarchical approach: lock regional markers first

**Coal**: The easiest setting. DEN + GR gives near-unique solutions
because coal has extreme density contrast (1.3 vs 2.5 g/cc).
Marine bands are laterally continuous → strong no-crossing constraint.

### Preprocessing per data type

| Data type | Preprocessing | Why |
|-----------|--------------|-----|
| GR | Normalize to 0–1 per well (or use Vshale formula) | Different tool calibrations; removes baseline offset |
| RHOB | Remove washout zones (caliper-based QC) | Bad hole = meaningless density |
| DT | Remove cycle skipping | Spikes destroy correlation |
| NPHI | Gas correction if needed | Gas effect mimics high porosity |
| Facies | Consolidate to 3–5 meaningful classes | Too many classes = noise |
| Biozones | Keep only zones identified in ALL wells | Missing = broken constraint |
| Picks | Use only regional markers (present in all wells) | Local picks create impossible constraints |

---

## 5. Constraint Selection

### Hard constraints (no-crossing)

`no-crossing` = a region whose boundaries CANNOT be crossed by
correlation lines. Use for:

- Biostratigraphic boundaries (age-diagnostic)
- Widely-agreed flooding surfaces / sequence boundaries
- Volcanic ash beds (isochronous markers)

**Requirements**:
- Must be a REGION (not a data channel)
- Zone boundaries must exist in ALL wells
- 3–5 boundaries is ideal; more = over-constrained

**Common mistake**: Using formation tops or zone logs with 10+
boundaries. If any boundary is missing in one well → 0 correlations.
Reduce to the few most reliable, regionally-correlated markers.

### Soft constraints (distality, same-region)

`dist-facies` + `dist-distal` = penalise correlating dissimilar
facies-distality combinations. Adds cost but doesn't forbid.

Best when:
- Wells span a proximal-to-distal gradient
- Facies are consolidated to 3–5 depositional associations
- Distality is well-calibrated (e.g., from palaeogeographic maps)

`same-region` = penalise correlating across different regions.
Softer than no-crossing (adds cost vs. forbids).

### When constraints hurt

| Symptom | Probable cause | Fix |
|---------|---------------|-----|
| 0 correlations | Missing zone boundary in some wells | Remove that boundary, use fewer zones |
| All scenarios identical | Over-constrained (hard constraints + facies) | Remove one constraint level |
| Results worse with constraint | Constraint data is wrong/inconsistent | Remove it; use as validation instead |
| Very few correlations (< 10) | Hard + soft constraints combine to eliminate most paths | Reduce to hard OR soft, not both |

---

## 6. Parameter Tuning Strategy

### The 3-stage approach

```
Stage 1: BASELINE (simple, fast, unconstrained)
  → Establishes what DTW finds from log signal alone

Stage 2: ADD ONE THING AT A TIME
  → Each addition should visibly improve or change results
  → If no improvement → remove it (it's noise)

Stage 3: FINE-TUNE DIVERSITY
  → Adjust min_dist, out_nbr_cor for meaningful alternatives
```

### Stage 1: Baseline recipe

```
var-data=GR
var-weight=1.0
order=position
max-cor=50
nbr-cor=30
out-nbr-cor=10
min-dist=0.1
```

Run this first. It gives you the "what does GR alone say?" answer.
This is your **reference uncertainty envelope**.

### Stage 2: Controlled additions

Test each addition separately against the baseline:

| Addition | What to check |
|----------|--------------|
| `var-data2=RHOB, var-weight=0.6, var-weight2=0.4` | Do results become more geologically plausible? |
| `no-crossing=SEQUENCE` | Does it reduce uncertainty to a useful range? |
| `dist-facies=FACIES, dist-distal=DISTALITY` | Do facies-inconsistent correlations disappear? |
| `const-gap-cost=0.5` | Are unreasonable hiatuses removed? |

**Decision rule**: If adding X makes correlations LESS plausible than
the baseline → X is adding noise. Remove it.

### Stage 3: Diversity tuning

| Parameter | Effect | Typical range |
|-----------|--------|---------------|
| `min-dist` | Higher = more structurally different solutions | 0.05–0.5 |
| `out-nbr-cor` | How many alternatives to keep | 5–15 |
| `out-min-dist` | Minimum difference between output scenarios | 0.02–0.1 |
| `max-cor` | Internal search width (more = finds rarer solutions) | 50–200 |

### Parameters by depositional environment

| Environment | max-cor | nbr-cor | min-dist | gap-cost | band-width |
|-------------|---------|---------|----------|----------|------------|
| Shallow marine | 50–100 | 30 | 0.1–0.2 | 1.0–2.0 | default |
| Deep marine | 100–200 | 50 | 0.1 | 0.5–1.0 | default |
| Fluvial | 100 | 30 | 0.3–0.5 | 0.3–0.5 | 40–80 |
| Carbonate | 50–100 | 30 | 0.1 | 1.5–3.0 | default |
| Coal | 30–50 | 20 | 0.05 | 3.0–5.0 | 10–20 |
| Glacial | 100 | 50 | 0.3 | 0.5 | 40+ |

---

## 7. Scenario Design & Uncertainty

### How to structure scenarios

Design scenarios as a **progressive chain** from unconstrained to
most-constrained:

```
Scenario 1: Baseline (GR only, no constraints)
   → Full uncertainty envelope

Scenario 2: + hard constraint (e.g., sequence boundaries)
   → Removes impossible solutions

Scenario 3: + soft constraint (e.g., facies-distality)
   → Prefers geologically reasonable solutions

Scenario 4: + second data channel
   → Tests if additional log adds signal

Scenario 5: Combined best from 2–4
   → Final "recommended" result set
```

### NEW: Automated Diversity Analysis

The `weco.diversity` module automates scenario diversity assessment:

```python
from weco.workflow import CorrelationWorkflow

wf = CorrelationWorkflow("my_project")
wf.import_wells("wells.txt")

# Screen logs BEFORE choosing cost function
log_scores = wf.screen_logs()
# → [{"log": "GR", "score": 0.82, "relevant": True},
#    {"log": "NPHI", "score": 0.03, "relevant": False, "reason": "flat"}]

wf.configure(
    preset="shallow_marine",
    cost_logs=["GR", "RHOB"],  # only relevant logs
    custom_options={
        "normalize-mode": "percentile",   # equalise log scales
        "diversity-mode": "topology",      # topology-aware filtering
    },
)
wf.run()

# Analyse diversity of results
report = wf.analyse_diversity(
    cross_validate=True,       # LOO-CV for robustness
    enumerate_architectures=True,  # multiple gap costs
    gap_cost_range=(0.0, 8.0, 1.0),
)
print(report["diagnosis"])
# → "ALGORITHM_LIMITED: Multiple scenarios but same architecture..."
print(report["recommendations"])
# → ["Run enumerate_architectures() with gap_cost_range=(0, 8, 1)..."]
```

### Key parameters that create genuinely different scenarios

Based on comprehensive testing across 10 demo datasets:

| Parameter | Effect on Architecture | Impact Level |
|-----------|----------------------|--------------|
| `const_gap_cost` | Controls horizon count and lateral continuity | **HIGH** - most impactful single dial |
| Log choice (`var_data`) | Fundamentally different correlations with different logs | **HIGH** - but only if logs carry independent signal |
| `order` (distality) | Enforces depositional model, constrains solution space | **MEDIUM** |
| `no_crossing` constraints | Removes geologically impossible solutions | **MEDIUM** |
| `min_dist` / `out_min_dist` | Path-space diversity (local variations only) | **LOW** - does not guarantee architectural change |
| `classification` (FACIES) | Often zero impact (already implicit in log response) | **LOW** |
| `multiscale` | Convergence to same solution at both scales | **LOW** |

### Fine-Tuning Parameters Automatically

The **Fine-Tune** feature uses differential evolution to optimise log
weights and gap cost against your current result:

```python
from weco.ai.auto_tune import AutoTuner

tuner = AutoTuner(
    well_list=wl,
    reference=current_res_file,         # your current best result
    param_bounds={
        "var-weight": (0.1, 5.0),       # log weight range
        "var-weight2": (0.0, 5.0),
        "const-gap-cost": (0.0, 8.0),   # gap cost range
        "min-dist": (0.1, 0.8),
    },
    base_options=current_options,
)
best = tuner.optimise(max_iter=20)
# → {'var-weight': 1.55, 'const-gap-cost': 2.75, ...}
```

In both GUIs, click **🔧 Fine-Tune** on the Run page. The system runs
~20 engine iterations and presents optimal parameters with an
"Apply & Re-run" button.

**When to use Fine-Tune:**
- After selecting logs and initial gap cost
- When you have a reasonable baseline but want to refine
- Before final export (to minimise misfit)

**When NOT to use:**
- On first run (use Quick Run or AI Suggest first)
- If you need architecturally different scenarios (use architecture enumeration)

### Complete Intelligent Workflow

The recommended workflow from raw data to export:

```
┌─────────────────────────────────────────────────┐
│  1. Import wells (file or RDDMS)                │
│  2. AI Suggest → screen logs + recommend preprocessing │
│  3. Apply Conditioning (normalise, Vshale, QC)  │
│  4. ⚡ Quick Run (or manual configure + Run)     │
│  5. Diversity Analysis → diagnose conclusive/limited │
│  6. If limited: Apply Recommendations → Re-run  │
│  7. Fine-Tune → optimise weights                 │
│  8. Architecture Enumeration → vary gap cost     │
│  9. Export best scenarios to RDDMS               │
└─────────────────────────────────────────────────┘
```

Each step has a one-click button in both web and desktop GUIs.

### Evaluating scenario quality

For each scenario, check:

| Criterion | Good sign | Bad sign |
|-----------|-----------|----------|
| **Number of correlations** | 50–500 (rich uncertainty) | 0 (broken) or 50000+ (meaningless) |
| **Structural diversity** | Scenarios differ in 2–3 key zones | All identical (over-constrained) or all random (under-constrained) |
| **Consistency with known markers** | Matches published correlations in well-constrained intervals | Contradicts biostratigraphy or known markers |
| **Geological plausibility** | Thickness changes are gradual; facies transitions follow Walther's law | Extreme thickness jumps; facies inversions |
| **Sensitivity** | Small parameter changes → small result changes | Chaotic (tiny change → completely different result = noise-dominated) |

### The over-interpretation trap

**Symptom**: Adding more data/constraints makes results LESS plausible.

**Cause**: Input data is inconsistent. Common culprits:
- Facies classification from different interpreters / standards
- Biozone boundaries placed at different confidence levels
- Zone logs that embed one old interpretation as "ground truth"

**Fix**: Consolidate, simplify, or demote to validation-only.

### Using existing interpretations

| Data | Role | Why |
|------|------|-----|
| Existing zone log | **Validation** (compare output against it) | It's ONE interpretation; using it as input just reproduces it |
| Published correlation panels | **Validation** (do we find their solution among our scenarios?) | They chose ONE of many possible solutions |
| Biostratigraphy picks | **Input** (constraint) if consistent across wells | Age-diagnostic, objective, independent |
| Seismic horizons | **Input** (no-crossing) if reliably tied | Provides spatial continuity not in well data |

---

## 8. Interpretation Checklist

After running scenarios, work through:

- [ ] **Baseline check**: Does the unconstrained result make geological sense?
- [ ] **Constraint benefit**: Does each constraint narrow uncertainty without creating artefacts?
- [ ] **Scenario comparison**: Which scenarios agree? Where do they disagree?
- [ ] **Disagreement zones**: Where scenarios diverge → that's the true uncertainty
- [ ] **Validation**: Do results honour known age data, published correlations?
- [ ] **Transport direction**: Are wells arranged in dip direction (max heterogeneity) or strike (similarity)?
- [ ] **Missing wells**: Would adding a well in the disagreement zone resolve ambiguity?
- [ ] **Sensitivity**: Is the result stable to small parameter perturbations?

### Common pitfalls

| Pitfall | Detection | Fix |
|---------|-----------|-----|
| Noise-driven correlation | Result changes drastically with ±5% parameter change | Coarser sampling; fewer channels |
| Redundant data | Adding 2nd channel doesn't change result at all | Remove it (it's just weight on the same signal) |
| Broken constraints | 0 correlations or "*ERR* region list X missing" | Check zone boundaries exist in all wells |
| Over-constrained | Only 1–2 scenarios, all identical | Remove softest constraint |
| Under-constrained | 10000+ scenarios, all meaningless | Add constraint or increase min-dist |
| Wrong well ordering | Correlations cross wildly | Reorder wells in transport direction |

---

## 9. Quick Reference Table

### Data preparation checklist

```
□ Identify target correlation scale (parasequence / sequence / formation)
□ Choose sampling interval (0.5m / 1.5m / 3m) matching target
□ Select 1–2 independent log channels
□ Consolidate facies to 3–5 classes (if using distality)
□ Identify 3–5 regional markers present in ALL wells (if using no-crossing)
□ Verify all wells have same channels and consistent naming
□ Set existing interpretations aside for validation only
□ Arrange wells in depositional transport direction for display
```

### Parameter cheat sheet by goal

| Goal | Key parameters |
|------|---------------|
| Fast interactive exploration | `max-cor=30, nbr-cor=20, out-nbr-cor=5` + coarse sampling |
| Maximum diversity (explore uncertainty) | `max-cor=200, nbr-cor=100, min-dist=0.3, out-nbr-cor=15` |
| Honour known stratigraphy | `no-crossing=SEQUENCE` (reduce to 3–5 boundaries) |
| Proximal-distal transect | `dist-facies=FACIES, dist-distal=DISTALITY, order=distality` |
| Discontinuous bodies (fluvial) | `const-gap-cost=0.3, band-width=60, min-dist=0.4` |
| High-confidence (coal / evaporite) | `const-gap-cost=3.0, band-width=15, max-cor=30` |

### From raw data to WeCo in 5 steps

```
1. Export wells from RMS/Petrel (RMS well format or LAS)
2. Identify common channels + regional picks
3. Resample to target resolution (1–2m for sequence-scale)
4. Consolidate facies/biozones to 3–5 groups
5. Write WeCo wells.txt (or .weco.json) with channels + regions
```

---

## 10. RDDMS Demo Data

Eleven demo datasets are pre-loaded in three RDDMS (OSDU) instances for
testing and training:

| Instance | URL | Dataspace |
|----------|-----|-----------|
| eqndev | equinorswedev.energy.azure.com | `maap/weco` |
| interop | admeinterop.energy.azure.com | `maap/weco` |
| preship | osdu-ship.msft-osdu-test.org | `maap/weco` |

**Available datasets:**

| Dataset | Wells | Logs | Description |
|---------|-------|------|-------------|
| shallow_marine | 6 | GR, RT, RHOB, NPHI, DT, FACIES | North Sea shelf |
| coal | 6 | GR, DEN, FACIES | Coal measures |
| sigrun | 6 | GR | Deep marine turbidites |
| delta | 6 | GR, DEN, NPHI | Deltaic sequence |
| fluvial | 20 | GR, FACIES | Channel-belt complex |
| bryson | 5 | GR | Synthetic (with constraints) |
| troll | 5 | FACIES | Categorical-only |
| hugin | 5 | GR, RT | Shallow marine w/ distality |
| quaternary | 4 | GR | Glacial sequence |
| chalk | 4 | GR, RT | Pelagic carbonates |
| barents_sea | 5 | GR, RT, NPHI | Arctic shelf |

**Loading demo data in the web GUI:**
1. Go to Data tab → "Import from RDDMS"
2. Select instance (eqndev/interop/preship)
3. Browse dataspace `maap/weco` → choose dataset
4. Wells and logs are loaded automatically

**Loading from Python:**
```python
from weco.rddms_interface import RddmsInterface

rddms = RddmsInterface(instance="eqndev")
wl = rddms.load_wells(dataspace="maap/weco", dataset="shallow_marine")
```

---

## See Also

- [Parameter Reference](parameters.md) - exhaustive parameter documentation
- [Domain Strategies](domain_strategies.md) - per-environment recipes
- [Geology Primer](geology_primer.md) - introduction to DTW correlation
- [Formats](formats.md) - file format specifications
- [Sigrun Demo](../demo/data/data_set_sigrun/) - real-world example with 6 scenarios
- [Demo Results Analysis](demo_results_analysis.md) - quantitative analysis of all demo runs
