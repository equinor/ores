# Tutorial: Exporting WeCo Results to GOCAD / RESQML / RMS

## Overview

WeCo supports multiple export formats for integration with geomodelling
software.  This tutorial covers each format and when to use it.

## Quick Start

```python
from weco.workflow import CorrelationWorkflow

wf = CorrelationWorkflow("Export_Demo")
wf.import_las("wells/*.las")
wf.configure(preset="shallow_marine")
wf.run()

# RMS package
wf.export_rms("output/rms/")

# Or individual exports
from weco.export import (
    export_correlation_surfaces,
    export_zonation_csv,
    export_zonation_las,
    export_seam_table,
    export_modflow_layers,
    export_continuous_logs,
    export_blocked_well_log,
    export_irap_surfaces,
)
```

## Format Guide

### 1. GOCAD (.ts, .wl, .vs)

**When**: Importing into GOCAD/SKUA for 3D structural modelling.

```python
# Triangulated horizon surfaces
export_correlation_surfaces(res_file, wells_file, "output/surfaces/")

# Well logs with strat column
from weco.formats.gocad_well import write_gocad_well, write_gocad_vset
write_gocad_well(well, "well.wl",
                 strat_column={0: {"name": "HST", "age_top": 0.1}},
                 zone_colours={"HST": (255, 200, 0)})

# Horizon control points
write_gocad_vset(wells, "picks.vs")
```

### 2. RESQML (.epc + .h5)

**When**: Exchanging data via OSDU/RDDMS or with Petrel/ECLIPSE.

```python
# Via GOCAD RESQML library (preferred)
from weco.rddms import epc_export_wells, epc_export_results
epc_export_wells("wells.epc", well_list)
epc_export_results("results.epc", res_file, well_list)

# Pure Python fallback (§4.6 — no external dependencies)
from weco.formats.epc_writer import write_epc_wells, write_epc_results
write_epc_wells("wells.epc", well_list)
write_epc_results("results.epc", res_file, wells_file)
```

### 3. RMS Package

**When**: Direct import into Roxar RMS.

```python
# Zonation + picks as CSV
wf.export_rms("output/rms/")

# Extended: blocked well logs
export_blocked_well_log(res_file, well_list, "output/rms/blocked/")

# IRAP surfaces
export_irap_surfaces(res_file, well_list, "output/rms/surfaces/")
```

### 4. Coal / Hydrogeology Specific

```python
# Coal seam table
export_seam_table(res_file, wells_file, "seams.csv")

# MODFLOW layers
export_modflow_layers(res_file, wells_file, "modflow_layers.csv")
```

### 5. Continuous Logs

```python
# Export raw + derived curves
export_continuous_logs(well_list, "output/logs/", fmt="las")  # or "csv", "gocad"
```

## RDDMS (Real-Time)

For live OSDU/RDDMS integration, see `demo_rddms.py`:

```python
from weco.rddms import (
    rddms_export_markers,
    rddms_export_zonation,
    rddms_export_horizons,
    rddms_export_strat_column,
)
```

## Studio Export Wizard

In WeCo Studio, go to Results → Export to access the graphical
export wizard that lets you select artifacts, choose formats, and
preview the output structure.
