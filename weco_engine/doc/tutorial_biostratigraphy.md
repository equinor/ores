# Tutorial: Adding Biostratigraphy to a Correlation

## Overview

Biostratigraphic data provides independent age control that can dramatically
improve well correlation accuracy. This tutorial shows how to integrate
biozone picks into a WeCo correlation workflow.

## What Are Biozones?

Biozones are depth intervals in wells defined by the presence of specific
fossils (foraminifera, nannoplankton, palynomorphs).  Each biozone has a
known age range.  Correlating markers *across* a biozone boundary implies
a time gap — which WeCo can penalise via the `BiozonAgeCost`.

## Step 1: Prepare Biozone Data

Create a CSV file with biozone picks:

```csv
well,depth_top,depth_base,biozone,age_top_Ma,age_base_Ma
W1,1500.0,1520.0,N.pachyderma,0.12,0.40
W1,1520.0,1570.0,G.inflata,0.40,1.80
W2,1480.0,1510.0,N.pachyderma,0.12,0.40
W2,1510.0,1560.0,G.inflata,0.40,1.80
```

## Step 2: Load Wells and Assign Biozones

```python
import csv
from weco.data import WellList

wl = WellList("wells.txt")

# Read biozone CSV
with open("biozones.csv") as f:
    reader = csv.DictReader(f)
    for row in reader:
        well_name = row["well"]
        # Find matching well
        for well in wl.wells:
            if well.name == well_name:
                # Add biozone as a region
                d_top = float(row["depth_top"])
                d_base = float(row["depth_base"])
                age_top = float(row["age_top_Ma"])

                depths = well.data.get("Depth", [])
                i_top = min(range(len(depths)), key=lambda i: abs(depths[i] - d_top))
                length = max(1, int((d_base - d_top) / (depths[1] - depths[0])))

                zone_id = hash(row["biozone"]) % 10000
                if "Biozone" not in well.region:
                    well.region["Biozone"] = []
                well.region["Biozone"].append((zone_id, i_top, length))
                break
```

## Step 3: Configure BiozonAgeCost

```python
from weco.ext import ProjectExt
from weco.cost_functions import BiozonAgeCost

# Set up biozone age mapping
BiozonAgeCost.BIOZONE_AGES = {
    hash("N.pachyderma") % 10000: 0.26,   # midpoint age
    hash("G.inflata") % 10000: 1.10,
}
BiozonAgeCost.AGE_WEIGHT = 10.0
BiozonAgeCost.REGION_NAME = "Biozone"

project = ProjectExt()
project.add_ccf_part(BiozonAgeCost)
project.set_options_ext(
    cost_function="composite",
    var_data="GR",
    var_weight=1.0,
)
project.run(wl)
```

## Step 4: Interpret Results

The `BiozonAgeCost` penalises correlations that pair different biozones.
Horizons will preferentially stay within the same biozone, honouring
the age constraints while still finding optimal log-shape matches.

## Tips

- **Weight tuning**: Start with `AGE_WEIGHT = 5.0` and increase if biozones
  are still being crossed.
- **Combine with distality**: The biozone constraint works well alongside
  distality cost for shallow marine settings.
- **Missing data**: Wells without biozone picks are unpenalised — the cost
  gracefully degrades.

## Workflow Integration

```python
from weco.workflow import CorrelationWorkflow

wf = CorrelationWorkflow("Bio_Study")
wf.import_las("wells/*.las")
wf.condition(biozones="biozones.csv")
wf.configure(preset="shallow_marine",
             custom_options={"biozone-weight": "10.0"})
wf.run()
wf.export_rms("output/")
```
