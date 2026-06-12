# WeCo Examples & Use-Case Guide

> **WeCo v0.9.31** - How to run examples, use the datasets, and set up
> your own correlation project.

---

## Table of Contents

1. [Three Ways to Run WeCo](#three-ways-to-run-weco)
2. [WeCo Studio (GUI)](#weco-studio-gui)
3. [Python API Examples](#python-api-examples)
4. [Datasets](#datasets)
5. [Use Cases](#use-cases)
6. [Writing Your Own Project](#writing-your-own-project)

---

## Three Ways to Run WeCo

| Method | Best for | Entry point |
|--------|---------|-------------|
| **WeCo Studio** | Interactive exploration, demos, parameter tuning | `WeCoStudio` or `./weco.sh studio` |
| **Python API** | Scripted workflows, batch runs, custom cost functions | `from weco.workflow import CorrelationWorkflow` |
| **CLI (WeCoRun)** | Quick runs from option + well files, shell scripts | `WeCoRun options.txt wells.txt` |

---

## WeCo Studio (GUI)

Launch:
```bash
WeCoStudio                                  # opens Welcome page
WeCoStudio --demo quaternary_basic          # jump to a specific demo
WeCoStudio --well-list data/data_set_coal/wells.txt  # load custom data
```

### Pages

| Page | What it does |
|------|-------------|
| **0 - Welcome** | Pick a demo dataset from the tree (toy, Quaternary, Coal). Click → loads data + recommended parameters. |
| **1 - Data** | Inspect wells: well table, data/region lists, log preview plots, data conditioning (Vshale, biozones, electrofacies). |
| **2 - Parameters** | Edit all engine parameters in 7 categories. Contextual help panel explains each parameter. Presets and undo/redo. |
| **3 - Run** | Execute the engine. Live log, progress bar. Threaded - GUI stays responsive. |
| **4 - Results** | Professional correlation plot (multi-log tracks, region strips, correlation lines). Navigate n-best results. Export PNG/SVG/PDF. |
| **5 - Help** | Built-in reference: workflow guide, parameter docs, format support, interpretation tips. |

### Built-in Demos

Studio ships with demos covering the main WeCo constraint types:

| # | Demo ID | Dataset | Wells | Constraints Demonstrated |
|---|---------|---------|------:|--------------------------|
| 1 | `distality` | data_set_distality | 2 | **Distality cost** (Walther's Law facies-belt penalty) |
| 2 | `biozone_distality` | data_set_biozone_distality | 2 | **No-crossing** + distality (biozone datums lock order) |
| 3 | `coal` | data_set_coal | 10 | **Gap cost** + multi-log (DEN+GR) + tight band-width |
| 4 | `quaternary` | data_set_quaternary | 20 | **Gap cost** + multi-log (GR+RT) + band-width |
| 5 | `shallow_marine` | data_set_shallow_marine | 10 | **3-log variance** (GR+RHOB+DT) + gap cost + band-width |
| 6 | `fluvial` | data_set_fluvial | 20 | **Gap cost** (channel pinch-out) + wide band-width |
| 7 | `delta` | data_set_delta | 8 | **Multi-log** (GR+DEN) + high diversity forcing |
| 8 | `bryson` | data_set_bryson | 7 | **No-crossing** (ZONE) + categorical FACIES cost |
| 9 | `sigrun` | data_set_sigrun | 2 | **Multi-log** (GR+NPHI) - North Sea well-tie |
| 10 | `troll` | data_set_troll | 5 | **Categorical** + distality ordering (Walther's Law) |

Each demo uses **geology-aware diversity parameters** scaled to dataset
complexity:

- **Small datasets** (2–3 wells): 30 internal paths, min-dist 0.3
  → explore the full solution space freely
- **Medium datasets** (4–10 wells): 15–20 paths, min-dist 0.4–1.0
  → pair diversity already constrains; higher forcing for clinoform ambiguity
- **Large datasets** (15+ wells): 5 paths, min-dist 0.4
  → combinatorics dominate; minimal internal search needed
- **Categorical data**: min-dist 0.5+ (discrete cost landscape needs
  stronger forcing to find distinct correlations)

---

## Python API Examples

All examples are in `demo/`. Run from within that directory
(they reference `test_wells.txt` locally):

```bash
cd demo
python ex1_run_weco_from_python.py
```

Or run the batch demo runner:
```bash
python bin/auto_run_examples.py
```

### ex1 - Basic Correlation from Python

The simplest possible WeCo run: set options, run on a well file.

```python
from weco.ext import ProjectExt

project = ProjectExt()
project.set_options_ext(
    var_data="data",
    cost_function="composite",
    max_cor=1,
)
project.run("test_wells.txt")
```

**What it shows:** `ProjectExt` API, setting options via keyword arguments,
running the engine on a WeCo well file.

### ex2 - Custom Python Cost Function

Define your own cost function in Python and plug it into the engine.

```python
from weco.ext import ProjectExt, CCFPartExt

class MyCost(CCFPartExt):
    def init(self):
        self.data = self.data_helper("data")

    def full_cost(self, prev_cost):
        cost = max(abs(self.data.src(i) - self.data.dest(i))
                   for i in range(self.size()))
        return True, prev_cost + cost

project = ProjectExt()
project.add_ccf_ext(MyCost)
project.set_options_ext(var_data="data", cost_function="composite")
project.run("test_wells.txt")
```

**What it shows:** `CCFPartExt` subclassing, `data_helper` / `region_helper`
accessors, `full_cost()` vs `dest_cost()` methods, registering custom costs.

### ex4 - Test Data Generation & Multiscale

Generate synthetic well data programmatically and run a multiscale
(hierarchical) correlation.

```python
from weco.testgen import TestBuilder
from weco.multiscale import MultiScaleProject

test_builder = TestBuilder(8, 100)           # 8 wells, 100 markers each
(test_builder
    .add_sin_data("data1", wave_length=10., noise=.2)
    .add_sin_data("data2", wave_length=50., noise=.1)
    .add_depth_data()
    .add_region1("zone1", 30, 10)
    .erode_start(20)
    .erode_end(20)
    .build()
    .multiscale_from_region("zone1")
    .multiscale_data("zone1", "msdata1", "data2")
    .write("wells.txt"))

msp = MultiScaleProject(test_builder.well_list)
msp.level("zone1", ("data1",), var_data="data1")
msp.final(("data2",), var_data="data2")
msp.run()
```

**What it shows:** `TestBuilder` for synthetic data, `MultiScaleProject` for
two-pass coarse-to-fine correlation, erosion simulation.

### ex6 - Custom Well Merge Order (DAG)

Control the order in which wells are merged using a Python callback.

```python
from weco.ext import ProjectExt

def order_function(wells, create_task):
    t1 = create_task(wells[0], wells[1])    # merge well 0 + 1
    t2 = create_task(t1, wells[2])          # merge result + well 2

project = ProjectExt()
project.set_order_func(order_function)
project.set_options_ext(order_dot="order.dot", order_only=1)
project.run("test_wells.txt")
```

**What it shows:** `set_order_func()`, DAG task graph construction,
DOT export for visualisation.

### ex8 - Multiscale Correlation

Simplified multiscale example with 3 wells, demonstrating the
`MultiScaleProject` and `MultiScaleChecker` APIs.

**What it shows:** Region-based level definition, per-level options,
multiscale validation.

### show_cost_matrix - Cost Matrix Visualisation

```python
from weco.data import CostMatrix
import matplotlib.pyplot as plt

cm = CostMatrix("cm_0_1.txt")
arr = cm.get_array_dest(0, 1)
plt.pcolormesh(arr)
plt.gca().invert_yaxis()
plt.colorbar()
plt.show()
```

### EAGE2024.ipynb - Jupyter Notebook

Interactive notebook from the EAGE 2024 conference demo, using real LAS
well data from `data/data_set_hugin_tidal/`.

### High-Level Workflow API

For production use, prefer `CorrelationWorkflow` over raw `ProjectExt`:

```python
from weco.workflow import CorrelationWorkflow

wf = CorrelationWorkflow("MyStudy")
wf.import_las("wells/*.las")
wf.condition(vshale=True, normalize=True, biozones="biozones.csv")
wf.configure(preset="shallow_marine")
wf.run()
wf.export_rms("output/rms_package/")
```

---

## Datasets

All datasets live in `demo/data/`. Each folder contains:
- `wells.txt` - WeCo WellList v2 file
- `options.txt` - default engine parameters
- `generate_*.py` - regeneration script (synthetic datasets)

### Concept Datasets (data_set_distality, data_set_biozone_distality)

| Dataset | Wells | Purpose | Key Constraint |
|---------|------:|---------|----------------|
| **data_set_distality** | 2 | Distality cost (Walther's Law) | `dist-distal`, `dist-facies`, `dist-scaling` |
| **data_set_biozone_distality** | 2 | Biozone no-crossing + distality | `no-crossing=BIOZONES` + distality |

**Use these to learn how distality and no-crossing constraints work.**

### Domain Datasets (geologically realistic)

| Dataset | Wells | Environment | Logs | Key Constraints | Generated by |
|---------|------:|-------------|------|-----------------|-------------|
| **data_set_coal** | 30 (10 used) | Coal basin, 6 seams, splitting/absence | DEN, GR, RT, CAL, SON, NEU | Gap cost (3.0) + band-width (15) + 2-log | `generate_coal.py` |
| **data_set_quaternary** | 100 (20 used) | Glacial lowland, 5 units, periglacial | GR, RT, SPT, COND, MS, WC | Gap cost (1.5) + band-width (20) + 2-log | `generate_quaternary.py` |
| **data_set_shallow_marine** | 10 | Shoreface parasequences, erosion surfaces | GR, RHOB, DT | Gap cost (2.0) + band-width (20) + **3-log** | `generate_shallow_marine.py` |
| **data_set_fluvial** | 20 | Channel belt, pinch-out uncertainty | GR | Gap cost (0.5) + band-width (20) + high diversity (min-dist=0.15) | `generate_fluvial.py` |
| **data_set_delta** | 8 | Prograding delta, clinoform ambiguity | GR, DEN, NPHI | Band-width (20) + 2-log | `generate_delta.py` |
| **data_set_bryson** | 7 | Appalachian Basin (categorical only) | FACIES | **No-crossing** (ZONE) - categorical correlation | Real data |
| **data_set_sigrun** | 2 | North Sea marine shale/sand | GR, NPHI | 2-log well-tie | Real data |
| **data_set_troll** | 5 | Troll field (categorical) | FACIES, DISTALITY | Categorical + distality (Walther's Law) | Real data |

### Relationship Between `data/` and `demo/`

| Folder | Purpose | Used by |
|--------|---------|--------|
| `demo/data/` | **Datasets** - geological input files (wells, options, results) | Studio demos, `bin/auto_run_examples.py`, your own scripts |
| `demo/` | **Code examples** - Python scripts showing API usage | Learning the API, extending WeCo |

They serve complementary purposes. `demo/data/` is the input; `demo/ex*.py` shows
how to *process* that input. Studio can load any dataset from `demo/data/`
directly via its demo picker.

---

## Use Cases

### Quaternary Hydrogeology - Aquifer Mapping

**Goal:** Correlate 3 aquifer units (sand/gravel) separated by 2 aquitards
(till/clay) across a borehole survey for groundwater flow modelling.

```bash
# Studio
WeCoStudio --demo quaternary_hydro

# Python
from weco.workflow import CorrelationWorkflow
wf = (CorrelationWorkflow()
      .import_wells("data/data_set_quaternary/wells_20.txt")
      .configure("quaternary")
      .run()
      .export_csv("/tmp/aquifer_zones"))
```

**Key parameters:**
- `var_data=GR`, `var_data2=RT` - primary correlation logs
- `same_region=Lithofacies` - prefer sand-to-sand, till-to-till
- `no_crossing=AquiferZone` - don't cross aquifer/aquitard boundaries
- `max_cor=50` - keep many alternatives for uncertainty

**Output:** Per-well zonation (A1/T1/A2/T2/A3) for MODFLOW input.

### Coal Seam Correlation - Mine Planning

**Goal:** Correlate named coal seams across a borehole grid for resource
estimation and mine planning.

```bash
WeCoStudio --demo coal_seam_constrained
```

**Key parameters:**
- `var_data=GR`, `var_data2=DEN` - coal has extreme GR lows + DEN lows
- `same_region=Lithofacies` - correlate coal-to-coal
- `no_crossing=MarineBand` - isochronous markers as hard constraints

**Output:** Seam correlation table → seam thickness maps.

### Oil Reservoir - Shallow Marine / Delta

**Goal:** Correlate reservoir zones in a prograding shoreface/delta
environment for 3D geomodel construction.

```python
from weco.workflow import CorrelationWorkflow

wf = CorrelationWorkflow("Hugin_Analogue")
wf.import_las("wells/*.las")
wf.condition(vshale=True, electrofacies=5, biozones="zones.csv")
wf.configure(preset="shallow_marine")
wf.run()
wf.export_rms("output/")
```

**Key parameters:**
- `var_data=GR`, `var_data2=DEN`, `var_data3=NPHI` - full log suite
- `dist_facies=electrofacies`, `dist_distal=Distality` - lateral facies control
- `transport_direction=135` - NW→SE progradation
- `no_crossing=Biozone` - age constraints

**Output:** Reservoir zonation + horizon picks for Petrel/RMS import.

### Intelligent Workflow - Zero-Config Correlation

**Goal:** Run a complete correlation from raw data with zero manual
parameter selection using the intelligent pipeline:

```python
from weco.workflow import CorrelationWorkflow

wf = CorrelationWorkflow("AutoPilot")
wf.import_las("wells/*.las")

# Screen logs, normalise, auto-configure
wf.screen_logs()                    # ranks logs by correlation relevance
wf.condition(normalize="percentile")  # equalise scales
wf.configure(preset="auto")         # AI-chosen parameters

# Run with diversity analysis
wf.run()
diversity = wf.analyse_diversity()  # topology metrics

# Fine-tune if needed
from weco.ai.auto_tune import AutoTuner
tuner = AutoTuner(wf.well_list, wf.res_file,
                  param_bounds={"var-weight": (0.1, 5.0),
                                "const-gap-cost": (0.0, 8.0)})
best = tuner.optimise(max_iter=20)

# Re-run with optimal params and export
wf.configure(**best)
wf.run()
wf.export_rms("output/")
```

**In the GUI:** Click ⚡ **Quick Run** (does steps 1–4 automatically),
then 🔧 **Fine-Tune** to optimise, then **Export**.

### RDDMS Round-Trip - Cloud Workflow

**Goal:** Load demo data from RDDMS, correlate, push results back:

```python
from weco.rddms_interface import RddmsInterface
from weco.workflow import CorrelationWorkflow

# Load from RDDMS
rddms = RddmsInterface(instance="eqndev")
wl = rddms.load_wells(dataspace="maap/weco", dataset="shallow_marine")

# Correlate
wf = CorrelationWorkflow("RDDMS_Demo")
wf.set_well_list(wl)
wf.configure(preset="shallow_marine")
wf.run()

# Push results back as StratigraphicColumn
rddms.push_results(wf.res_file, dataspace="maap/weco")
```

---

## Writing Your Own Project

### Step 1: Prepare well data

WeCo accepts LAS, CSV, RESQML, or native `.wells.txt` format:

```python
from weco.formats import read_wells

# Auto-detect format
wl = read_wells("my_wells.las")
wl = read_wells("my_wells.csv", columns=["WELL", "DEPTH", "GR", "RT"])
wl = read_wells("my_wells.wells.txt")
```

Or build programmatically:

```python
from weco.data import WellList

wl = WellList()
w1 = wl.create_well("Well_A", size=100, x=0, y=0)
w1.add_data("GR", gr_values)
w1.add_data("RT", rt_values)
w1.add_region("facies", [(1, 0, 30), (2, 30, 40), (3, 70, 30)])
```

### Step 2: Configure parameters

```python
from weco.ext import ProjectExt

proj = ProjectExt()

# Option A: load from file
proj.option_load("options.txt")

# Option B: set programmatically
proj.set_options_ext(
    var_data="GR",
    var_weight=1.0,
    var_data2="RT",
    var_weight2=0.5,
    same_region="facies",
    max_cor=50,
)
```

See [parameters.md](parameters.md) for the full parameter reference.

### Step 3: Run

```python
proj.run(wl)    # pass WellList object
# or
proj.run("wells.txt")  # pass file path
```

### Step 4: Export results

```python
from weco.export import (
    res_to_zonation_log,
    res_to_horizon_picks,
    export_horizon_picks_csv,
    export_zonation_las,
)

res = proj.get_res_file()
zonation = res_to_zonation_log(res, wl)
picks = res_to_horizon_picks(res, wl, max_horizons=10)

export_horizon_picks_csv(picks, "horizon_picks.csv")
export_zonation_las(zonation, "output_las/")
```

### Step 5: Visualise

```python
# In Studio (recommended)
WeCoStudio --well-list wells.txt

# Programmatically
from weco.correlation_plot import CorrelationPlotWindow
viewer = CorrelationPlotWindow(wl, res)
viewer.show()
```

---

## Script Reference

| Script | Location | Purpose |
|--------|----------|---------|
| `weco.sh` | root | Build, test, run helper (all-in-one) |
| `auto_run_examples.py` | `bin/` | Run all demo/ examples headless (batch) |
| `demo_rddms.py` | `bin/` | OSDU/RDDMS live demo |
| `gocad_extract.py` | `bin/` | GOCAD .wl → WeCo converter |
| `generate_quaternary.py` | `demo/data/data_set_quaternary/` | Generate synthetic Quaternary dataset |
| `generate_coal.py` | `demo/data/data_set_coal/` | Generate synthetic coal dataset |
| `generate_shallow_marine.py` | `demo/data/data_set_shallow_marine/` | Generate synthetic shallow marine dataset |
| `generate_fluvial.py` | `demo/data/data_set_fluvial/` | Generate synthetic fluvial dataset |
| `generate_delta.py` | `demo/data/data_set_delta/` | Generate synthetic delta dataset |

### weco.sh Commands

```bash
./weco.sh setup              # create venv + install WeCo
./weco.sh build              # build C++ engine
./weco.sh test               # run pytest suite
./weco.sh check              # WeCoCheck health test
./weco.sh run OPT WELLS      # WeCoRun with given files
./weco.sh studio             # launch WeCoStudio
./weco.sh resview RES WELLS  # launch WeCoResView
./weco.sh demo               # run batch demo runner
./weco.sh stubs              # regenerate engine.pyi
./weco.sh doc                # build Python docs (Sphinx)
./weco.sh cppdoc             # build C++ docs (Doxygen)
./weco.sh info               # show install info
./weco.sh clean              # remove build artifacts
```
