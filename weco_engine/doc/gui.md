# WeCo GUI Documentation

> Two front-ends - **PyQt desktop** and **Web client** - sharing the same
> correlation engine, API layer, demo datasets, and result semantics.

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────┐
│                     WeCo Engine (C++)                         │
│         DTW graph-search · n-best · composite cost           │
└───────────────────────────┬──────────────────────────────────┘
                            │ ProjectExt (pybind11)
┌───────────────────────────┴──────────────────────────────────┐
│                  Python API Layer (weco/api.py)               │
│  _suggest_defaults · _run_engine · _extract_results          │
│  _diverse_results · _topology_signature · _label_scenario    │
└──────────┬──────────────────────────────────────┬────────────┘
           │ Direct in-process                    │ FastAPI REST
┌──────────┴──────────────┐        ┌─────────────┴────────────┐
│  PyQt Desktop GUI       │        │  Web Client              │
│  bin/demo_gui.py        │        │  weco_router.py (API)    │
│  PyQt6 + Matplotlib     │        │  weco.js + weco.html     │
│  1692 lines             │        │  Canvas 2D + fetch()     │
└─────────────────────────┘        └──────────────────────────┘
```

---

## Shared Capabilities

Both GUIs expose the full WeCo feature set:

| Feature | PyQt | Web |
|---------|:----:|:---:|
| Multi-well correlation (2–100+ wells) | ✓ | ✓ |
| K-best results (configurable n=5–100) | ✓ | ✓ |
| Multi-log weighting (up to 5 logs) | ✓ | ✓ |
| No-crossing constraints (3 slots) | ✓ | ✓ |
| Same-region constraints | ✓ | ✓ |
| Distality cost function | ✓ | ✓ |
| Gap cost (const + func + polarity) | ✓ | ✓ |
| Band-width DTW pruning | ✓ | ✓ |
| Minimum distance (diversity) | ✓ | ✓ |
| Boundary/gap/framework line classification | ✓ | ✓ |
| Uncertainty overlay (n-best alpha blending) | ✓ | ✓ |
| Region/facies coloring | ✓ | ✓ |
| AI quality scoring | ✓ | ✓ |
| AI anomaly detection | ✓ | ✓ |
| AI uncertainty analysis | ✓ | ✓ |

---

## Demo Dataset Handling

Both GUIs load the same demo datasets from `demo/data/`:

```
demo/data/
├── data_set_variance_weights/    (3 wells - simple distality)
├── data_set_polarity_dip/    (4 wells - marker-only)
├── data_set_gap_cost/      (5 wells - gap cost exploration)
├── data_set_distality/      (6 wells - coal basin cyclothems)
├── data_set_biozone_distality/      (2 wells - constrained crossing)
├── data_set_bryson/ (7 wells - Appalachian biostratigraphy)
├── data_set_coal/   (30 wells - large coal deposit)
├── data_set_delta/  (8 wells - deltaic sequences)
├── data_set_shallow_marine/ (10 wells - parasequences)
├── data_set_sigrun/ (2 wells - Hugin Fm shallow marine)
└── data_set_troll/  (5 wells - Troll field)
```

### PyQt: Embedded Dataset Dictionary

```python
DATASETS = {
    "1_distality": {
        "title": "...", "wells": "demo/data/data_set_variance_weights/wells.txt",
        "runs": [...], "common_opts": {...}, "ai": {...}
    },
    ...
}
```

- 10 curated demos with geological context descriptions
- Tree widget: parent = dataset, children = run variants (2–5 each)
- Click run item → populate parameters → execute

### Web: REST-Driven Demo Loading

```
GET  /demos              → list demo metadata
POST /demos/{id}/wells   → load wells + return recommended_options
```

- Demo grid with cards (name, well count, description)
- **Auto-run on click**: Select card → fetch wells → call `quickRun()` → switch to Results tab
- Returns AI settings + environment preset per demo

### Consistency

| Aspect | Same? | Notes |
|--------|:-----:|-------|
| Dataset files | ✓ | Both read `demo/data/*/wells.txt` |
| Default parameters | ✓ | Via `_suggest_defaults_for_wells()` or per-dataset dict |
| Option reset between runs | ✓ | `RESET_OPTS` in PyQt; fresh options dict per request in web |
| Demo-specific AI toggles | ✓ | `AI_DEFAULTS` dict (PyQt) ↔ `ai_settings` payload (web) |

---

## Parameter Controls

### Common Parameter Set

| Parameter | PyQt Widget | Web Element | Engine Mapping |
|-----------|-------------|-------------|----------------|
| `var-data` | QComboBox (log names) | `<select #p-var-data>` | Primary log curve |
| `var-weight` | QDoubleSpinBox | `<input #p-var-weight>` | Primary log weight |
| `var-data2..5` | QComboBox × 4 | `<select>` × 4 | Additional logs |
| `no-crossing` | QComboBox (region names) | `<select #p-no-crossing>` | Hard boundary constraint |
| `same-region` | QComboBox | `<select #p-same-region>` | Zone constraint |
| `dist-distal` | QComboBox | `<select #p-dist-distal>` | Distality log |
| `dist-facies` | QComboBox | `<select #p-dist-facies>` | Facies for distality |
| `gap-cost-func` | QLineEdit | `<input #p-gap-cost>` | Gap cost function |
| `const-gap-cost` | QDoubleSpinBox | `<input>` | Constant gap penalty |
| `band-width` | QSpinBox | `<input #p-band-width>` | DTW band constraint |
| `max-cor` | QSpinBox | `<input #p-max-cor>` | Max results to keep |
| `nbr-cor` | QSpinBox | - | Number of results |
| `min-dist` | QDoubleSpinBox | - | Diversity filter |
| `n-best` | QSpinBox | `<input #p-n-best>` | Output count |

### Auto-Suggest

| | PyQt | Web |
|--|------|-----|
| **Trigger** | Implicit (from dataset `common_opts`) | "Auto-suggest" button → `POST /suggest-defaults` |
| **Backend** | `_suggest_defaults_for_wells(wl)` | Same function via REST |
| **Output** | Populates widgets directly | Populates form + shows reasoning text |
| **Presets** | Per-dataset run variants | Dropdown: simple / constrained / distality / multi-log |

---

## Run Workflows

### PyQt Run Flow

```
User clicks "Run Selected" or "Run All"
  → Read widget parameters
  → Merge: RESET_OPTS + common_opts + run.opts + widget overrides
  → Spawn CorrelationWorker(QThread)
    → ProjectExt.set_options() → run()
    → Capture stdout/stderr to StringIO
  → Signal finished(res_file, well_list, log_text)
  → Display result in Results tab
  → Queue next run (if batch)
```

### Web Quick-Run Flow (⚡)

```
User clicks demo card or "Quick Run" button
  → POST /auto
    → _suggest_defaults_for_wells(wl)
    → detect_environment() → suggest_options(env_key)
    → _apply_memory_guards() (cap max-cor for container RAM)
    → Check result cache (MD5 of wells + options)
    → _run_engine(wl, options)
    → _diverse_results(rf, data, n_best=5, n_diverse=3)
    → _topology_signature() + _label_scenario() per result
  → Return {results, suggested_options, reasoning, elapsed_ms}
  → Switch to Results tab
```

### Web Manual Run Flow

```
User configures parameters in Params tab → clicks "Run"
  → POST /run {options, n_best, well_names}
    → _apply_memory_guards()
    → _run_engine(wl, options)
    → _extract_results(rf, data, n_best)
  → Return results
```

### Error Recovery (R2)

The web `/auto` endpoint implements a fallback strategy:

1. Try full options (with distality, constraints, etc.)
2. On engine failure → strip to minimal options (`var-data`, `max-cor`, `min-dist`)
3. Retry with simplified correlation
4. If both fail → HTTP 500 with diagnostic detail

PyQt catches `Exception` in the worker thread and renders error in the Engine Log tab.

### Result Caching (R3)

Web only: MD5-based cache keyed on `sorted(well_names) + sorted(options.items())`.
- 5-entry FIFO eviction
- Cache checked after memory guards applied
- Avoids re-running identical correlations (e.g., toggling between results)

---

## Result Visualization

### Plot Layout (Both GUIs)

```
┌─────┬─────┬───┬─────┬─────┬───┬─────┬─────┐
│Facies│Logs │Gap│Facies│Logs │Gap│Facies│Logs │
│Strip │Trace│   │Strip │Trace│   │Strip │Trace│
│     │     │   │     │     │   │     │     │
│ W1  │ W1  │↔ │ W2  │ W2  │↔ │ W3  │ W3  │
└─────┴─────┴───┴─────┴─────┴───┴─────┴─────┘
```

Gap corridors between wells contain correlation lines:
- **Boundary** (red solid): matched marker positions
- **Gap/hiatus** (blue dotted): missing section
- **Framework** (gray thin): additional structural ties

### Rendering Differences

| Aspect | PyQt (Matplotlib) | Web (Canvas 2D) |
|--------|-------------------|-----------------|
| Log traces | Up to 3 curves, auto-color | Priority-ordered (GR, RT, DEN...) |
| Facies strips | Discrete colored bands | Narrow left-margin strip |
| Depth axis | MD on left per well | MD and/or TVDSS (toggle) |
| Alignment | Fixed (absolute) | Marker-aligned or absolute (toggle) |
| Uncertainty | Alpha-blended top-N overlay | Ranking panel (no overlay) |
| Stratcolumn | - | Left-side global reference band |
| Output format | PNG to `tmp/img/` | Canvas → PNG download button |
| Plot size | Figure(20, 12) fixed | Responsive (fills container) |

### View Modes (Web Only)

1. **Single**: One result at a time with prev/next navigation
2. **Composite**: Top-3 results side-by-side (3-panel)
3. **Table**: Correlation matrix cards with cost values

---

## AI Integration

### Quality Scoring

Both GUIs invoke `CorrelationQuality(rf, wl)`:
- Multi-criteria score (0–100): cost gradient, gap ratio, monotonicity, consistency
- PyQt: Appended to ranking label (★ stars)
- Web: Styled panel with component breakdown

### Anomaly Detection

`CorrelationAnomalyDetector(rf, wl)`:
- Isolation Forest on correlation features
- Flags unusual results (potential geological anomalies vs. errors)
- PyQt: Warning icon in ranking
- Web: Orange panel with flag count + details

### Uncertainty Analysis

`CorrelationUncertainty(rf, wl)`:
- Spread analysis across n-best results
- Mean/max marker uncertainty per well
- PyQt: Uncertainty bars on plot
- Web: Numeric display (mean ± max spread in markers)

### Log QC (PyQt Only)

`LogQC` preprocessing:
- Washout detection + removal
- Missing value imputation
- Log normalization
- Toggled via checkbox in AI Features panel

---

## Export Capabilities

| Export Type | PyQt | Web |
|------------|:----:|:---:|
| PNG plot | ✓ (auto-save to `tmp/img/`) | ✓ (download button) |
| RDDMS markers | ✓ (Export tab) | ✓ (`POST /rddms/export-results`) |
| RDDMS zone log | ✓ (Export tab) | ✓ (`POST /rddms/export-results`) |
| RDDMS strat column | ✓ (Export tab) | ✓ (`POST /rddms/export-results`) |
| JSON result | - | ✓ (download) |
| CSV marker table | - | ✓ (download) |
| Workflow save/load | - | ✓ (tokenstore SQLite) |

### RDDMS Export (Both GUIs)

Both front-ends use the same `weco.rddms` functions underneath:

| What | Function | RESQML type |
|------|----------|-------------|
| Markers | `rddms_export_markers()` | `WellboreMarkerFrameRepresentation` |
| Zone log | `rddms_export_zonation()` | `DiscreteProperty` on `WellboreFrame` |
| Strat column | `rddms_export_strat_column()` | `StratigraphicColumn` |

Each realisation (`cor_num`) produces a fresh set of UUIDs so multiple
n-best results can coexist in the same dataspace.

**PyQt:** "RDDMS Export" tab → fill URL + dataspace → click "Export to RDDMS"

**Web:** Export button calls `POST /rddms/export-results` which delegates to the same functions.

Authentication: both resolve token via `weco.osdu_auth.get_token()` (env var / Azure CLI / ORES session).

---

## Deployment & Access

| | PyQt | Web |
|--|------|-----|
| **Launch** | `python bin/demo_gui.py` | Docker (Radix) → `https://ores.radix.equinor.com/weco` |
| **Dependencies** | PyQt6, matplotlib, numpy | FastAPI, uvicorn, weco (pip) |
| **Network** | Offline capable | Requires RDDMS for real data; demos bundled |
| **Scaling** | Single user, local process | Multi-user, memory-guarded, job component for large runs |
| **Persistence** | None (session only) | Workflow save/load, result cache |

---

## Performance & Robustness

### Memory Guards (Web)

The web API caps parameters to fit Radix container (2 GiB):
- `max-cor` capped at 200
- `nbr-cor` capped at 100
- Large datasets (>20 wells) routed to async job component

### Benchmarks (R1)

Automated timing via `pytest/test_benchmark.py`:

| Dataset | Wells | Engine (ms) | Total (ms) |
|---------|------:|------------:|------------:|
| data_set_variance_weights | 3 | ~370 | ~370 |
| data_set_biozone_distality | 2 | ~30 | ~31 |
| data_set_bryson | 7 | ~800 | ~800 |
| data_set_delta | 8 | ~3000 | ~3000 |
| data_set_shallow_marine | 10 | ~15000 | ~15000 |

### Integration Testing (Q1)

`pytest/test_auto_pipeline.py` - parametrized over all demos ≤10 wells:
- `test_suggest_defaults`: options dict non-empty
- `test_full_pipeline`: suggest → run → extract → diversify → label
- `test_pipeline_result_structure`: verify result fields (cost, wells, boundaries)

---

## GUI Consistency Principles

1. **Same engine, same results**: Both GUIs produce identical correlation outputs for the same input wells and parameters
2. **Same demo data**: Both load from `demo/data/` - results are reproducible across front-ends
3. **Same API functions**: Both ultimately call `_suggest_defaults_for_wells`, `_run_engine`, `_extract_results`, `_diverse_results`
4. **Same AI scoring**: Quality/anomaly/uncertainty implementations shared in `weco/ai/`
5. **Consistent line classification**: Boundary (red) / gap (blue dotted) / framework (gray) in both renderers
6. **Same diversity guarantee**: `min_dist=0.1, out_min_dist=0.05` set by default in both

### Known Differences (Intentional)

| Difference | Reason |
|-----------|--------|
| Parameter naming (snake_case vs kebab-case) | PyQt uses Python dict keys directly; web uses HTTP query convention |
| Log QC only in PyQt | Web preprocessing happens server-side before data reaches client |
| Export only in web | Desktop users export manually; web needs RDDMS integration for dataspace workflows |
| Workflow persistence only in web | Desktop is ephemeral demo tool; web supports team collaboration |
| Batch run only in PyQt | Web equivalent is the async job component for large datasets |
