# WeCo Developer Guide

## Requirements

- **C++ compiler:** gcc ≥ 7 (c++17) or MSVC ≥ 2017
- **CMake** ≥ 3.12 (for C++ engine build)
- **Python** ≥ 3.8 (for bindings and all Python tooling)
- **pybind11** (installed automatically via scikit-build-core)
- **doxygen** (optional, for C++ API docs)

## Python Package (Recommended)

The project uses **scikit-build-core** as the build backend (configured in
`pyproject.toml`). This handles CMake, pybind11, and wheel creation automatically.

### 1. Create & activate a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\activate    # Windows
```

### 2. Install in editable mode with development tools

```bash
pip install -e .[devel]
```

This installs WeCo in editable mode **plus** Sphinx, pytest, pybind11-stubgen.

### 3. Optional install groups

```bash
pip install -e .[gui]     # PyQt6 for GUI / Studio
pip install -e .[ai]      # scikit-learn for AI modules
pip install -e .[api]     # FastAPI / Uvicorn for REST API
```

### 4. Verify installation

```bash
WeCoCheck
```

## Running Tests

```bash
pytest pytest/ -v              # full suite (~440 tests)
pytest pytest/test_utils.py    # single file
pytest pytest/ -k "workflow"   # by keyword
```

## Project Structure

```
weco/                   # Python package
├── studio.py           # WeCo Studio GUI (main application)
├── ai/                 # AI modules (log_qc, facies_predict, uncertainty, ...)
├── formats/            # Format registry + GOCAD readers/writers
├── api.py              # FastAPI REST endpoints
├── correlation_plot.py # Professional well-log correlation viewer
├── cost_functions.py   # Python-side cost function definitions
├── data.py             # Well, WellList, ResFile core data model
├── export.py           # Zonation log + horizon pick + CSV/JSON/LAS export
├── ext.py              # ProjectExt — Python engine wrapper
├── preprocessing.py    # Data conditioning (Vshale, biozones, electrofacies, ...)
├── rddms.py            # Universal data bridge (RESQML, LAS, CSV, RMS)
├── sensitivity.py      # Well-order sensitivity analysis
├── validate.py         # Reference comparison & quality scoring
└── workflow.py         # CorrelationWorkflow high-level API

bin/                    # User-facing scripts (demos, GOCAD extract)
binding/                # C++ ↔ Python pybind11 bridge
src/                    # C++ engine source
include/                # C++ headers
pytest/                 # Test suite (16 files)
data/                   # Example datasets
examples/               # Python API examples
output/                 # Generated outputs (gitignored)
```

## Building Documentation

```bash
# Python docs (Sphinx)
./weco.sh doc

# C++ docs (Doxygen) — requires doxygen
./weco.sh cppdoc
```

## Extra Commands

```bash
python -m build         # create wheel + source package
./weco.sh stubs         # regenerate engine.pyi stubs
```

## CMake Build (Standalone C++ Engine)

Requires pybind11: `python -m pip install pybind11[global]`
and CMake ≥ 3.12.

### Linux

```bash
mkdir build && cd build
cmake ..
make
```

### Windows

```
cmake -G "Visual Studio 17 2022 Win64" .
cmake --build . --config Release
```

---

## Architecture

See [architecture.md](architecture.md) for system diagrams, data model,
complexity analysis, and format/output artifact matrices.

---

## Changelog — Completed Work (v0.9.31)

### Codebase (11 items)

- PyQt5 → PyQt6 port, editable install, all tests passing.

### Scripts (4 items)

- `weco.sh`, `auto_run_examples.py`, `demo_gui.py`, global option reset.

### Data Conditioning

- `weco/preprocessing.py`: Vshale, stacking pattern, electrofacies, biozones,
  facies map projection, structural domain regions.

### AI

- `weco/ai/` package: log QC, facies prediction, uncertainty quantification,
  anomaly detection, auto-parameter tuning, quality scoring.
- `BiozonAgeCost` Python CCFPartExt.
- Studio data conditioning tab, scikit-learn optional dependency.

### GUI (45 items)

- Studio 6-page workflow, correlation plot viewer, demo datasets
  (Quaternary + Coal), presets, undo/redo, data conditioning tab,
  multi-run comparison, dark mode, drag-and-drop, plugin manager.
- Facies group editor dialog, well order sensitivity button, erosion
  surface picker, transport direction compass, hierarchical mode toggle,
  systems tract overlay toggle.

### C++ Engine Optimisations

- Sakoe-Chiba band constraint (`band-width` option, `include/weco.h`).
- Graph compaction (`CorGraph::compact()` in `src/corgraph.cpp`).
- Sparse path buffer (`std::unordered_map` when band active).
- Beam search (`beam-width` option, `finish_path()` pruning).
- Wavefront parallel correlator (`Correlator::run_wavefront()`).
- SIMD variance annotation (`src/correlator.cpp`).
- Cost-floor option for noise suppression.

### C++ Cost Functions

- Group-aware Δf in `_CCFPartDistal` (`dist-facies-groups` option).
- GIL batching protocol (`batch_full_cost()` in `binding/ccf_part.h`).
- B3D normalization and symmetry review.

### Python Port

- Numba JIT correlator (`weco/correlator_numba.py`).
- Cython fallback (`weco/_correlator.pyx`).
- C++ optional at import time → pure Python slow mode.

**Assessment:** 50-200× slowdown for naive Python on the hot loop.
Small projects (2-3 wells, <100 markers, k=50): ~7 s — acceptable for
prototyping. Production (10+ wells, 200+ markers, k=200): minutes — too slow.
The hybrid approach (C++ kernel + Python everything else) is optimal.

### Python Modules

- `WellScheduleExt` declarative merger order (`weco/ext.py`).
- `RateDeclineCost` CCFPartExt (`weco/cost_functions.py`).
- `CorrelationToModflow` FloPy interface (`weco/flow_interface.py`).
- Thickness ratios from sequence stratigraphy (`weco/sequence_strat.py`).
- MultiScaleProject temp-file elimination (`weco/multiscale.py`).

### Export Pipeline

- Zonation logs, horizon picks, CSV/JSON/LAS export.
- `weco/validate.py`, `weco/sensitivity.py`.
- GOCAD `.wl`/`.vs`/`.ts`/`.pl` writers.
- RESQML EPC + RDDMS REST export for all artifact types.
- RMS package export (blocked wells, IRAP surfaces).
- Seam table, MODFLOW layers, n-best ensemble export.

### Documentation

- All docs consolidated in `doc/`.
- `ReadMe.md` rewritten, `~/bin/weco` launcher.
- Geology primer, hierarchical tutorial, export tutorial,
  biostratigraphy tutorial, validation report, domain strategies.

### Bugs Fixed (10)

- Option state leakage, `ResFile.write()`, `MinMax`, `_write_las`,
  icon path, old code cleanup, well name spaces, CorResView ordering,
  GIL overhead per call.

### Deployment

- Radix job component (`radixconfig.yaml`).
- Pre-built wheels via cibuildwheel.
- WebAssembly/Pyodide build (Emscripten).

### Tests & Data

- `TestDistalityB3D`, `TestThicknessValidation`, `TestNoiseValidation`
  in `pytest/test_truth.py`.
- Carbonate platform generator (`data/data_set_carbonate/generate_carbonate.py`).
- Shallow marine, delta, fluvial dataset generators.
- OSDU/RDDMS live demo (`demo_rddms.py`).

---

## Document Library Index

| Category | Documents | Key Insights |
|----------|-----------|-------------|
| **Core Theory** | Baville PhD Thesis (234p) | Distality cost math, B3D method, facies clustering, well order sensitivity |
| **Planning** | Phase II proposal, PoC proposal | Thickness constraint, dip regions, ground-truthing, RMS integration pipeline |
| **RING Papers** | Lallier, Edwards, Caumon, Julio (15+) | DTW foundations, hierarchical correlation, uncertainty |
| **Sedimentology** | Ainsworth, Aschoff, Boyd, Catuneanu, Kieft | Facies models, depositional environments |
| **Field Data** | Gudrun/Sigrun reports, correlation panels | Hugin Fm, shallow marine deltaic |
| **Presentations** | 12 PPTX files (ASC, geoseminar, NPF) | Workflow, results, value proposition |

## cmake options

* -DPYTHON_EXECUTABLE:FILEPATH=path can select python executable 
* -DGEN_PYBINDING=OFF if you don't want to generate the python bindings
* -DGEN_WECORUN=OFF  if you don't want to generate teh executable WeCoRun
* -DGEN_TEST_EXEC=ON to generate test executables
* -DGEN_TEST_COST_FUNCTION=ON to generate the test cost function (src/project_test.cpp)
* -DGEN_PLUGIN=OFF if you don't want to activate the plugin functionalities
* -DGEN_PLUGIN_EXAMPLE=ON if you want to generate the example plugin
* -DGEN_CPP_DOC=ON if you want to generate the c++ doc with doxygen
* -DGEN_B3D=OFF to remove B3D cost functions
* -DB3D_INTERPOLATION=OFF to remove Bézier 3D cubic interpolation

## weco_test
If the file **test.cpp** exists (in the same directory as CMakeLists.txt) an executable named **weco_test** 
will be generated with this file. 
