# WeCo — Multi-Well Stratigraphic Correlation

**Authors:** Christophe Antoine, Guillaume Caumon, Paul Baville  
**Affiliation:** ASGA — Université de Lorraine  
**Version:** 0.9.31  
**License:** [ASGA Proprietary](doc/license.txt)

WeCo is a stratigraphic correlation engine that finds the *n*-best correlation
scenarios between wells using graph-based Dynamic Time Warping (DTW).
Unlike single-answer approaches, WeCo explores the full solution space —
honouring log similarity, facies architecture, structural dip, biostratigraphy,
and depositional constraints simultaneously.

The C++ engine is exposed to Python via pybind11 and can run headless (API/CLI),
inside a PyQt6 desktop GUI (WeCo Studio), or deployed as a cloud service on
Equinor Radix integrated with [ORES](https://github.com/equinor/ores).

---

## Installation

**Requirements:** Python ≥ 3.8, C++ compiler (g++ ≥ 7 / MSVC 2017+ / Apple Clang 12+), CMake ≥ 3.15

```bash
python3 -m venv .venv && source .venv/bin/activate

pip install .              # core (C++ engine + CLI)
pip install .[gui]         # + PyQt6 Studio GUI
pip install .[ai]          # + scikit-learn (auto-tune, facies, QC)
pip install .[api]         # + FastAPI REST endpoint
pip install .[gui,ai,api]  # everything
```

Helper script (Linux/macOS):
```bash
./weco.sh setup     # venv + full install
./weco.sh test      # pytest suite
./weco.sh studio    # launch Studio GUI
```

### Docker

```bash
docker build -t weco .
docker run --rm -p 8000:8000 weco
```

---

## Quick Start

### Python API

```python
from weco.workflow import CorrelationWorkflow

wf = (CorrelationWorkflow()
      .import_wells("data/data_set_1.1/wells.txt")
      .configure("simple")
      .run())

# Access results
for i in range(wf.res_file.get_nbr_results()):
    print(f"Correlation {i}: cost={wf.res_file.get_result_cost(i):.4f}")

wf.export_csv("/tmp/result")
```

### Studio GUI

```bash
WeCoStudio
```

Six-page workflow: Data Import → Log Preview → Parameters → Run → Results → Export.
Includes 16 built-in demos across coal, fluvial, shallow marine, carbonate, and glacial basins.

### Command Line

```bash
WeCoRun -w data/data_set_1.1/wells.txt -o output/ --cost-function composite \
        --var-data GR --max-cor 30
```

### REST API

```bash
pip install .[api]
uvicorn weco.api:app --port 8000
# POST /run with JSON options → n-best correlation results
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Python Layer                                           │
│  ┌──────────┐  ┌───────────┐  ┌──────────────────────┐ │
│  │ Studio   │  │ Workflow  │  │ FastAPI / ORES       │ │
│  │ (PyQt6)  │  │ API       │  │ integration          │ │
│  └────┬─────┘  └─────┬─────┘  └──────────┬───────────┘ │
│       │               │                   │             │
│       └───────────────┼───────────────────┘             │
│                       ▼                                 │
│  ┌─────────────────────────────────────────────────┐    │
│  │  pybind11 bridge (binding/)                     │    │
│  └──────────────────────┬──────────────────────────┘    │
└─────────────────────────┼───────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────┐
│  C++ Engine (src/ + include/)                           │
│                                                         │
│  • Graph-DTW correlator with Sakoe-Chiba band          │
│  • 12 cost functions (variance, gap, distality,        │
│    B3D, polarity, region, thickness, …)                │
│  • Multi-threaded scheduler (OpenMP)                   │
│  • Beam search pruning for large datasets              │
│  • Sparse path buffer for memory efficiency            │
└─────────────────────────────────────────────────────────┘
```

---

## Cost Functions

The engine combines multiple geological cost functions into a composite score:

| Function | Measures | Typical Use |
|----------|----------|-------------|
| **Variance** | Log waveform similarity (DTW distance) | Primary signal matching |
| **Gap** | Penalty for missing intervals / unconformities | Prevents over-stretching |
| **Distality** | Proximal→distal trend preservation | Lateral facies changes |
| **B3D** | 3D structural consistency (dip/azimuth) | Structurally complex areas |
| **Region** | Same-facies / same-zone constraint | Honour known boundaries |
| **No-crossing** | Prevents chronostratigraphic violations | Marker-constrained correlation |
| **Polarity** | Log polarity matching (fining/coarsening) | Sequence stratigraphy |
| **Thickness** | Interval thickness consistency | Uniform deposition areas |

---

## Datasets

WeCo includes 19 datasets in `data/`:

| Dataset | Wells | Geology | Key Challenge |
|---------|-------|---------|---------------|
| `data_set_1.1`–`1.5` | 5 | Synthetic | Unit tests for individual cost functions |
| `data_set_2` | 10 | Synthetic | Multi-well scaling |
| `data_set_3` | 50 | Synthetic | Performance benchmark |
| `data_set_4` | 150 | Synthetic | Large-scale stress test |
| `data_set_coal` | 10–30 | Coal basin | Cyclothems, seam splitting, marine bands |
| `data_set_fluvial` | 20 | Fluvial | Channel stacking, avulsion |
| `data_set_shallow_marine` | 20 | Shelf | Parasequences, flooding surfaces |
| `data_set_carbonate` | 15 | Carbonate | Platform-to-basin transitions |
| `data_set_delta` | 20 | Deltaic | Clinoforms, prodelta-to-topset |
| `data_set_quaternary` | 20–100 | Glacial | Periglacial features, aquifer layers |
| `data_set_bryson` | 8 | Real (Appalachian) | Published reference correlation |
| `data_set_sigrun` | 12 | Real (North Sea) | Biostratigraphic constraints |
| `data_set_troll` | 10 | Real (North Sea) | Thick sand bodies |
| `data_set_eage2024` | 8 | Real (LAS) | Conference demo dataset |

---

## Key Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `cost-function` | `composite` | Cost function type |
| `var-data` | — | Primary log variable (GR, RT, DEN, …) |
| `var-weight` | 1.0 | Primary log weight |
| `max-cor` | 50 | Max correlation paths to track per cell |
| `nbr-cor` | 10 | Number of correlations in output |
| `out-nbr-cor` | 5 | Best results to keep |
| `order` | `position` | Well ordering strategy |
| `same-region` | — | Constrain to same facies zone |
| `no-crossing` | — | Prevent marker crossing |
| `band-width` | 0 | Sakoe-Chiba band (0 = unlimited) |
| `thread` | 0 | Thread count (0 = auto) |
| `const-gap-cost` | 1.0 | Gap penalty weight |

Full reference: [doc/parameters.md](doc/parameters.md)

---

## Cloud Deployment (Equinor Radix)

WeCo integrates with [ORES](https://github.com/equinor/ores) as an in-process engine:

```
ORES web container (2Gi)          WeCo job pod (8Gi)
┌─────────────────────┐           ┌──────────────────────┐
│ /weco/run           │──>15 wells──>│ Heavy correlation    │
│ /weco/import        │           │ max_cor=50, 4 threads│
│ /weco/suggest       │           │ band_width=30        │
│ Memory guards:      │           └──────────────────────┘
│  ≤10w: max_cor=50   │
│  11-15w: max_cor=30 │
│  thread=1           │
└─────────────────────┘
```

- Small datasets (≤15 wells): in-process, sub-second response
- Large datasets (>15 wells): auto-routed to dedicated 8Gi job pod
- Server-side parameter guards prevent OOM regardless of user input

See [doc/ores_integration.md](doc/ores_integration.md) for deployment details.

---

## Project Structure

```
weco/                    Python package
  studio.py                WeCo Studio (PyQt6 GUI)
  workflow.py              CorrelationWorkflow high-level API
  api.py                   FastAPI REST endpoint
  data.py                  WellList, Well, ResFile data classes
  decision_tree.py         Auto-parameter recommendation
  correlation_plot.py      Matplotlib correlation viewer
  ai/                      AI modules (log QC, facies, uncertainty, auto-tune)
  formats/                 Format registry (LAS, RESQML, CSV, GOCAD, JSON)
  preprocessing.py         Data conditioning (Vshale, electrofacies, biozones)
src/                     C++ engine
  correlator.cpp           DTW correlator with sparse/dense path buffer
  scheduler.cpp            Multi-threaded task scheduler
  project_ccf.cpp          Composite cost function dispatch
  corgraph.cpp             Correlation graph (nodes = samples, edges = paths)
  dtw_distance.cpp         DTW distance metrics
include/weco.h           C++ public header (CorGraph, Correlator, Project)
binding/                 pybind11 bridge (main.cpp + cost_function wrappers)
data/                    19 datasets (synthetic + real basins)
examples/                7 Python API examples
pytest/                  24 test files (400+ tests)
doc/                     Documentation
bin/                     Scripts (batch runner, GUI demo, benchmarks)
```

---

## Testing

```bash
pip install .[devel]
pytest pytest/ -v                    # full suite
pytest pytest/test_engine.py -v      # engine only
pytest pytest/ -k "coal" -v          # specific dataset
```

---

## Building from Source (C++ engine)

```bash
mkdir build && cd build
cmake .. -DGEN_PYBINDING=ON -DCMAKE_BUILD_TYPE=Release
make -j$(nproc)
```

For development iteration without reinstalling:
```bash
pip install -e . --no-build-isolation
```

---

## Citation

If you use WeCo in academic work, please cite:

> Antoine, C., Caumon, G., & Baville, P. (2024). *WeCo: Graph-based dynamic time
> warping for multi-well stratigraphic correlation.* ASGA, Université de Lorraine.

---

## License

© ASGA — Université de Lorraine. See [doc/license.txt](doc/license.txt).

