# WeCo File Format Support — Status & Roadmap

> **WeCo v0.9.31** — Current support, detailed capabilities, and planned extensions.

---

## Current Format Support Matrix

### READ

| Format | Module | Logs | Regions | Markers | XY coords | Dip/Azi | Trajectory |
|--------|--------|:----:|:-------:|:-------:|:---------:|:-------:|:----------:|
| **WeCo native** `.txt` | `data.py` | ✅ | ✅ | — | ✅ | as data | ❌ |
| **LAS 2.0** `.las` | `lasfile.py` → `las2welllist.py` | ✅ | ✅ (auto-detect) | ✅ (~Tops) | ✅ (XCOORD/YCOORD) | ✅ (DIP/AZIM) | ❌ |
| **LAS 3.0** `.las` | `lasfile.py` | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| **RESQML v2** `.epc+.h5` | `resqml.py` | ✅ Continuous | ✅ Discrete | ✅ WellboreMarkerFrame | via MdDatum | ❌ | ✅ |
| **CSV/space-sep** | `data_import.py` | ✅ | ✅ (from column) | ✅ | ✅ (auto-detect) | ✅ | ❌ |
| **GOCAD** `.wl` | `formats/gocad_well.py` | ✅ (REC) | ✅ (MRKR) | ✅ | ✅ (WREF) | ✅ (NORM) | ✅ (VRTX) |

### WRITE

| Format | Module | What |
|--------|--------|------|
| **WeCo native** | `WellList.write()` | Full well list (data + regions) |
| **LAS 2.0** | `lasfile.las_write()` + `Res2LAS` | DEPTH/RGTMI/RGTMA result export |
| **CSV** | `Res2CSV` | Correlation result (well, marker, depth), regions |
| **JSON** | `export.py` | Well tops, correlation metadata |
| **GOCAD .wl** | `formats/gocad_well.py` | Wells with strat column + zone colours |
| **GOCAD .vs** | `formats/gocad_well.py` | Horizon pick control points |
| **GOCAD .ts** | `export.py` | Interpolated correlation surfaces |
| **GOCAD .pl** | `export.py` | Correlation polylines |
| **RESQML .epc** | `formats/epc_writer.py` | Wells + results (pure Python, no ext deps) |
| **RESQML (RDDMS)** | `rddms.py` | Wells + results via REST/cloud |
| **RMS package** | `export.py` | Blocked wells, IRAP surfaces |
| **Petrel well tops** | `export.py` | Formation tops CSV |
| **MODFLOW layers** | `flow_interface.py` | FloPy layer definitions |
| **PNG/SVG/PDF** | `correlation_plot.py` | Publication-quality correlation plots |

---

## Internal Data Model

```
WellList
└── wells: List[Well]
    ├── name: str
    ├── size: int              # marker/sample count
    ├── x, y, z, h: float     # position & length
    ├── data: Dict[str, float[]]    # continuous arrays (length = size)
    └── region: Dict[str, Tuple[(id, start, length), ...]]  # discrete zones
```

Key: wells are **marker-indexed**. All data arrays have length `well.size`.
Regions segment the well into named intervals.

---

## Roadmap

### Phase 1 — GOCAD Well Import (`.wl`)

**Priority: HIGH** (enables the GOCAD plugin workflow)

| Task | Effort | Notes |
|------|--------|-------|
| Parse GOCAD `.wl` header (HEADER, WREF) | Low | Extract well name, WREF → x,y,z |
| Parse trajectory (VRTX) | Medium | Deviation survey → MD/TVD trajectory |
| Parse markers (MRKR + NORM) | Medium | MRKR → region boundaries, NORM → dip/azimuth data |
| Parse log curves (WELL_CURVE/REC) | Medium | REC depth-value pairs → resample onto marker grid |
| Multi-well `.wl` files | Low | Multiple `GOCAD Well...END` blocks |
| Create `gocad2welllist.py` module | Medium | GOCAD `.wl` → WeCo `WellList` converter |

**Challenge:** Resampling — GOCAD logs at arbitrary MD vs WeCo marker-indexed arrays.
Strategy: Interpolate log values onto the marker/sample grid (linear or nearest).

### Phase 2 — Enhanced LAS Support

**Priority: MEDIUM**

| Task | Effort | Notes |
|------|--------|-------|
| LAS 2.0 region import | Low | Detect integer/categorical curves → auto-create regions |
| LAS 3.0 support | Medium | Block sections, multiple arrays per curve |
| LAS marker import | Low | Read `~Tops` section if present |
| LAS dip/azimuth | Low | Detect DIP/DAZI/AZIM curves → map to WeCo data |
| Multi-file batch import | Low | Glob pattern → WellList |

### Phase 3 — Enhanced CSV Support

**Priority: MEDIUM**

| Task | Effort | Notes |
|------|--------|-------|
| CSV header auto-detect | Low | Match column names to known log types |
| CSV marker/tops import | Low | `well, marker_name, depth` format |
| CSV dip/direction import | Low | `well, depth, dip, azimuth` format |
| CSV pointset import | Low | `x, y, z, property1, property2, ...` |
| CSV region export | Low | Export regions alongside results |

### Phase 4 — GOCAD Export

**Priority: LOW** (for feeding results back to GOCAD)

| Task | Effort | Notes |
|------|--------|-------|
| Write correlation as GOCAD markers | Medium | Result markers → MRKR entries in `.wl` |
| Write correlation as GOCAD polylines | Medium | Correlation lines → `.pl` (PLine) |
| Write correlation as GOCAD surfaces | High | Interpolated horizons → `.ts` (TSurf) |
| Export Bézier curves as GOCAD VSet | Low | B3D output → `.vs` point sets |

### Phase 5 — GOCAD Plugin Integration

**Priority: FUTURE** (depends on Phase 1 + GOCAD build setup)

| Task | Effort | Notes |
|------|--------|-------|
| GOCAD plugin skeleton | Medium | Register WeCo as GOCAD plugin (.so) |
| In-process data transfer | High | Read GOCAD Well objects directly (no file I/O) |
| GUI panel in GOCAD | High | Qt panel embedded in GOCAD viewer |
| Result display in GOCAD 3D | Medium | Correlation surfaces in GOCAD scene |

---

## GOCAD `.wl` Format Reference

```
GOCAD Well 0.01
HEADER { name:Well_A }
WREF 500000.0 6200000.0 0.0        # well head (x y z)
DPLN 0.0                            # datum plane
VRTX 1 0.0 0.0 100.0               # deviation: dx dy md
VRTX 2 0.5 0.1 200.0
MRKR TopCretaceous 0 150.2         # marker: name flag md
NORM 0.0 0.0 1.0                   # normal vector for preceding marker
MRKR TopJurassic 0 280.5
NORM 0.1 0.0 0.99
WELL_CURVE                          # log curve
  PROPERTY GR
  UNITS m gAPI
  REC 100.0 45.2                    # md value
  REC 100.5 52.1
  REC 101.0 38.7
END
END
```

## GOCAD `.vs` (VSet/PointSet) Format Reference

```
GOCAD VSet 1
HEADER { name:MyPointSet }
PROPERTIES Porosity Facies
PVRTX 1 500000.0 6200000.0 -1500.0 0.22 3
PVRTX 2 500100.0 6200050.0 -1510.0 0.18 2
END
```

---

## Implementation Notes

### GOCAD Well → WeCo WellList Conversion Strategy

1. **Trajectory:** VRTX deviation points → compute TVD at each MRKR depth
2. **Markers → Regions:** Consecutive markers define region boundaries.
   E.g., markers at MD 150, 280, 400 → 3 regions for samples between them.
3. **Logs → Data arrays:** Interpolate WELL_CURVE REC values onto the sample grid.
   Use the marker positions to define the sample depths, then interpolate log values.
4. **Dip/Azimuth:** MRKR NORM vectors → convert to dip angle + azimuth → data arrays.
5. **Position:** WREF → `well.x`, `well.y`, `well.z`.

### Resampling Strategy

GOCAD logs are sampled at arbitrary MD values. WeCo needs marker-indexed arrays:

```python
# Option A: Regular sample grid (similar to LAS import)
sample_depths = np.linspace(top_md, base_md, n_samples)
log_values = np.interp(sample_depths, rec_depths, rec_values)

# Option B: Marker-based grid (one sample per marker interval)
# Average log values within each marker-to-marker interval
for i, (top, base) in enumerate(marker_intervals):
    mask = (rec_depths >= top) & (rec_depths < base)
    data[i] = np.mean(rec_values[mask]) if mask.any() else np.nan
```

Prefer Option A for dense logs, Option B for sparse/categorical data.

---

## Detailed Capabilities by Format

### WeCo Native (`.wells.txt`)

**Read:** `WellList(path)` — header `WeCo WellList 2`  
**Write:** `WellList.write(path)`

Handles:
- ✅ Well metadata (name, size, x, y, z, h)
- ✅ Data arrays (logs — arbitrary named float arrays)
- ✅ Regions (named region lists with id + start + length)
- ✅ Derivatives (`Well.add_derivative()`)
- ✅ Region↔Data conversion (`add_data_from_region`, `add_region_from_data`)
- ❌ Well trajectories / deviation surveys
- ❌ Point sets / surfaces
- ❌ Dip/azimuth as structured objects (stored as plain data arrays)

### LAS 2.0

**Read:** `LASFile.read()` → sections (version, well, curve, param, data)  
**Write:** `las_write()` — standard LAS 2.0  
**Convert:** `las2well()` — LAS → WeCo `Well`; `LAS2WellList` — batch  
**Export:** `Res2LAS` — correlation results → per-well LAS (DEPTH, RGTMI, RGTMA)

Handles:
- ✅ All curve/log data
- ✅ Well coordinates (XCOORD, YCOORD from well section)
- ✅ Depth (STRT, STOP, STEP)
- ✅ NULL value handling
- ✅ Row filtering via Python expressions
- ❌ Markers/regions (not a LAS concept — convert via `data_import.py`)
- ❌ LAS 3.0

### RESQML v2

**Read:** `ResqmlFile(epc_path)` → wellbore interpretations, frames, properties  

Handles:
- ✅ Continuous properties (float logs on wellbore frames)
- ✅ Discrete properties (integer/categorical logs)
- ✅ Well trajectories (MD, datum, start/finish)
- ✅ Wellbore markers (geologic boundary kind + depth)
- ✅ Stratigraphic columns & unit interpretations
- ✅ Contact interpretations
- ❌ Grids / surfaces / faults
- ❌ Write (read-only)

### CSV Import (`data_import.py`)

**Read:** `DataImport.from_csv_file()`, `from_space_file()`  

Handles:
- ✅ Arbitrary columnar data (markers, logs, attributes)
- ✅ Dip / azimuth (via column specification)
- ✅ Region creation from string columns (`create_region_from_name`)
- ✅ Multi-scale region/data generation
- ❌ Well trajectories
- ❌ Point sets
- ❌ Write

### CSV Export

**Write:** `Res2CSV.run()` — correlation → (Well, Marker, Depth) CSV  
**Write:** `CostMatrix.csv_dest()`, `csv_full()` — cost matrix CSV

---

## Gap Analysis — What's Missing?

### Data Types Not Supported

| Data Type | Currently | Needed for GOCAD/RESQML workflows |
|-----------|----------|-----------------------------------|
| **Well trajectories / deviation surveys** | RESQML read only | Read/Write in LAS, CSV, GOCAD `.wl` |
| **Point sets** | ❌ | GOCAD `.vs`, CSV |
| **Surfaces** | ❌ | GOCAD `.ts`, RESQML |
| **Dip directions (structured)** | As plain data arrays | Dedicated reader for tadpole/dipmeter data |
| **Stratigraphic markers** | RESQML read, CSV import | Unified marker object with R/W across formats |
| **Properties on surfaces** | ❌ | GOCAD property on `.ts` |
| **Region labels** | Native, CSV import | GOCAD `.wl` + property, LAS discrete curves |

---

## GOCAD Format Support Plan

### Priority 1: Well-centric formats (needed for correlation)

| Format | Extension | Direction | Data Types | Complexity |
|--------|-----------|-----------|------------|------------|
| **Well header** | `.wl` | Read + Write | name, xyz, KB, trajectory, logs, markers | Medium |
| **Well log property** | (on `.wl`) | Read + Write | continuous/discrete curves | Medium |
| **Point set** | `.vs` (VSet) | Read + Write | xyz + optional properties | Low |

### Priority 2: Visualization & export

| Format | Extension | Direction | Data Types | Complexity |
|--------|-----------|-----------|------------|------------|
| **Surface** | `.ts` (TSurf) | Read + Write | triangulated mesh + properties | Medium |
| **Polyline** | `.pl` (PLine) | Read + Write | correlation lines as 3D paths | Low |

### Priority 3: Full GOCAD ecosystem

| Format | Extension | Direction | Data Types | Complexity |
|--------|-----------|-----------|------------|------------|
| **Structured grid** | `.sg` (SGrid) | Read only | grid + properties | High |
| **Group** | `.gp` | Read | container for multiple objects | Medium |

### GOCAD File Format Basics

GOCAD ASCII files all follow the same pattern:

```
GOCAD <ObjectType> <version>
HEADER {
  name: <object_name>
  ...
}
PROPERTIES <prop1> <prop2> ...
PROP_LEGAL_RANGES <prop> <min> <max>
...
<BODY DATA>
END
```

Key sections:
- **VRTX / PVRTX** — vertex coordinates (3D/property-carrying)
- **TRGL** — triangles (for TSurf)
- **SEG** — segments (for PLine)
- **ATOM** — reference to another vertex (for VSet)
- **WREF** — well reference data
- **MRKR** — marker data
- **ZONE** — zone/log data

---

## Implementation Architecture

### Proposed module structure

```
weco/
├── formats/
│   ├── __init__.py          # Format registry & auto-detection
│   ├── base.py              # Abstract FormatReader / FormatWriter
│   ├── gocad_common.py      # GOCAD ASCII parser (shared header, properties)
│   ├── gocad_well.py        # .wl reader/writer (logs, markers, trajectory)
│   ├── gocad_tsurf.py       # .ts reader/writer (triangulated surfaces)
│   ├── gocad_pline.py       # .pl reader/writer (polylines)
│   ├── gocad_vset.py        # .vs reader/writer (point sets)
│   ├── las.py               # Consolidate existing lasfile.py + las2welllist.py
│   ├── resqml.py            # Move/wrap existing resqml.py
│   ├── csv_io.py            # Consolidate data_import.py + res2csv.py
│   └── welllist.py          # Native WeCo format (wrap data.py)
```

### Format auto-detection

```python
def detect_format(path: str) -> str:
    """Detect file format from extension and magic bytes."""
    ext = Path(path).suffix.lower()
    FORMAT_MAP = {
        '.las': 'las',
        '.wells.txt': 'weco',
        '.res.txt': 'weco_res',
        '.epc': 'resqml',
        '.csv': 'csv',
        '.wl': 'gocad_well',
        '.ts': 'gocad_tsurf',
        '.pl': 'gocad_pline',
        '.vs': 'gocad_vset',
    }
    # Also check first line for 'GOCAD' magic, 'LAS' version, etc.
```

### Universal Well object

The existing `Well` class in `data.py` is already the universal container.
All format readers should produce `Well` / `WellList` objects:

```python
# All these produce the same Well/WellList objects:
wl = read_wells("data.wells.txt")     # native
wl = read_wells("data.las")           # LAS
wl = read_wells("data.epc")           # RESQML
wl = read_wells("data.wl")            # GOCAD (future)
wl = read_wells("data.csv", columns=["WELL", "DEPTH", "GR"])  # CSV
```

---

## ~/gocad Integration Path

The user has a GOCAD installation at `~/gocad`. Integration strategy:

1. **Phase 1 — Standalone format support** (no GOCAD dependency)
   - Read/write GOCAD ASCII files directly
   - Pure Python, no external libraries needed
   - Works everywhere, not just on machines with GOCAD installed

2. **Phase 2 — GOCAD plugin** (optional, for live GOCAD workflow)
   - Use WeCo's C ABI plugin system (`weco_plugin.h`)
   - Plugin loads inside GOCAD's Python environment (gopy)
   - Update legacy `gopy_extract.py` to modern Python 3
   - Enables run-from-GOCAD workflow

3. **Phase 3 — GOCAD API bridge** (bidirectional)
   - Export correlation results as GOCAD objects (surfaces, markers, polylines)
   - Import GOCAD project wells directly (via gopy API if available)

---

## CLI Entry Points

| Command | Module | Status | Function |
|---------|--------|--------|----------|
| `WeCoStudio` | `weco.studio` | ✅ | WeCo Studio GUI (main application) |
| `WeCoRun` | `weco.ext` | ✅ | Run correlation from options + wells file |
| `WeCoCheck` | `weco.check` | ✅ | Validate installation |
| `WeCoResView` | `weco.resview` | ✅ | Result viewer |
| `WeCoConvert` | `weco.convert` | ✅ | Universal format converter |
| `WeCoRes2LAS` | `weco.res2las` | ✅ | Correlation → per-well LAS |
| `WeCoRes2Csv` | `weco.res2csv` | ✅ | Correlation → CSV |
| `WeCoAddRegion` | `weco.addregion` | ✅ | Add region data to wells |
