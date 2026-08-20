# Querying OSDU & Reservoir Data

ORES provides multiple ways to search and explore reservoir data - from a visual point-and-click builder to raw GraphQL queries. This guide starts with common tasks and works down to technical details.

---

## Choosing the Right Approach

| I want to… | Recommended path |
|------------|-----------------|
| Search without writing code | [Easy Mode](#easy-mode--visual-query-builder) on the `/keys` page |
| Find OSDU records by keyword or area | [OSDU Search](#osdu-search) |
| Browse dataspaces, list objects | [GraphQL Browse](#browsing--exploration) |
| Find grids/wells by property value (e.g. porosity > 0.25) | [Deep Search](#deep-search--property-filtering) |
| Traverse relationships between objects | [Graph Traversal](#relationships-graph-traversal) |
| Search across multiple dataspaces at once | [Multi-dataspace Search](#deep-search--multiple-dataspaces) |
| Search OSDU catalog + RDDMS together | [Federated Search](#federated-search-osdu--rddms) |
| Inspect array data (depths, values, stats) | [Array Statistics](#array-statistics--samples) |
| Batch graph traversal (many objects at once) | [Discovery Graph Search](#i-discovery-batch-graph-search) |
| Get full XML of a single object | [RDDMS REST](#rddms-rest-api) |
| Bulk import/export EPC files | ETP CLI |

> **Rule of thumb:** Use GraphQL for anything involving filtering, relations, or multiple objects. Use OSDU Search for metadata/spatial lookups. Use REST only when you need raw XML.

---

## Easy Mode – Visual Query Builder

The `/keys` page offers an **Easy Mode** tab that builds GraphQL queries without writing raw syntax.

### How it works

1. Select **Query type** (Deep Search, Browse, Relations, Federated)
2. Pick an **Object type** from categorized dropdown (Grid, Well, Surface, Property, …)
3. Optionally enter a **Property** name/alias (e.g. `poro`, `sw`, `perm`)
4. Set an **operator + threshold** filter (e.g. `> 0.25`)
5. Toggle **Statistics**, **Relations**, **Sample values**
6. Click **▶ Run Query**

Results render as **colored cards** with type-category badges, sparkline statistics bars, and matching-cell percentages.

### Query types in Easy Mode

| Action | What it does | Use case |
|--------|--------------|----------|
| Deep Search | Filter objects by type + numerical property | "Show grids with porosity > 0.25" |
| Browse | List objects of a type (no filter) | "What IjkGrids exist in this dataspace?" |
| Relations | Graph traversal from a specific UUID | "What references this grid?" |
| Federated | Search OSDU catalog + RDDMS simultaneously | "Find all Drogon objects everywhere" |

### Match modes

| Mode | Behaviour |
|------|-----------|
| **Loose** (default) | Substring match - `poro` finds "PORO", "porosity_v1", etc. |
| **Strict** | Exact match on canonical RESQML property kind |

Click **"Show generated GraphQL"** to see the raw query and switch to Advanced Mode for tweaking.

---

## Common Use Cases

### Browsing & Exploration

Start here to understand what data is available:

```graphql
{ status }                                          # Check backend connectivity
{ dataspaces { path uri } }                         # List all dataspaces
{ resqmlCategories { name count } }                 # What type groups exist?
{ resourceTypes(dataspace: "maap/drogon") { name count } }  # Types in a dataspace
```

```graphql
# List objects of a specific type
{
  resqmlObjects(
    dataspace: "maap/drogon"
    typeName: "resqml20.obj_IjkGridRepresentation"
    limit: 10
  ) { uuid title typeName }
}
```

> **Tip:** Use `category` to search all related types at once - e.g. `category: "well"` covers WellboreFeature, Trajectory, Frame, MarkerFrame, DeviationSurvey, BlockedWellbore (10 types).

---

### Deep Search – Property Filtering

Find objects where a numerical property meets a threshold:

```graphql
# Grids where porosity > 0.25
{
  deepSearch(
    dataspace: "maap/drogon"
    typeName: "resqml20.obj_IjkGridRepresentation"
    propertyFilter: {
      titleContains: "PORO"
      arrayFilter: { threshold: 0.25, operator: GT }
    }
    includeStatistics: true
    limit: 5
  ) {
    backend totalScanned totalMatched queryDescription
    objects {
      uuid title
      properties {
        title kind uom
        statistics { count minValue maxValue mean }
        matchingCells { count total fraction }
      }
    }
  }
}
```

**Common filter recipes** (same query structure - swap `titleContains`, `threshold`, `operator`):

| Use case | titleContains | threshold | operator |
|----------|--------------|-----------|----------|
| High porosity zones | `"PORO"` | 0.25 | GT |
| High-perm streaks | `"PERMX"` | 500.0 | GT |
| Hydrocarbon zones (low Sw) | `"SWATINIT"` | 0.3 | LT |
| Tight zones (low perm) | `"PERMX"` | 1.0 | LT |
| Net-to-gross cutoff | `"ntg_pem"` | 0.5 | GT |
| Well log porosity | `"PHIT"` | 0.25 | GT |
| Well log permeability | `"KLOGH"` | 100.0 | GT |

For **well logs**, use `typeName: "resqml20.obj_WellboreFrameRepresentation"` with the same pattern.

```graphql
# Browse ALL properties on grids (omit propertyFilter)
{
  deepSearch(
    dataspace: "maap/drogon"
    typeName: "resqml20.obj_IjkGridRepresentation"
    includeStatistics: true
    limit: 2
  ) {
    objects { uuid title properties { title kind uom statistics { count minValue maxValue mean } } }
  }
}
```

```graphql
# Search by category - find all structural objects with relations
{
  deepSearch(
    dataspace: "demo/drogon"
    category: "structural"
    includeRelations: true
    limit: 10
  ) {
    backend totalScanned totalMatched
    objects {
      title typeName
      relations { name typeName direction }
    }
  }
}
```

---

### Deep Search – Multiple Dataspaces

```graphql
# Search wells across two dataspaces
{
  deepSearch(
    dataspaces: ["demo/drogon", "maap/weco"]
    category: "well"
    includeStatistics: true
    limit: 10
  ) {
    backend totalScanned totalMatched queryDescription
    objects { title typeName properties { title kind statistics { count minValue maxValue } } }
  }
}
```

```graphql
# Porosity comparison across dataspaces
{
  deepSearch(
    dataspaces: ["maap/drogon", "maap/volve"]
    typeName: "resqml20.obj_IjkGridRepresentation"
    propertyFilter: { titleContains: "PORO", arrayFilter: { threshold: 0.2, operator: GT } }
    includeStatistics: true
    limit: 10
  ) {
    backend totalScanned totalMatched queryDescription
    objects { uuid title properties { title statistics { minValue maxValue } matchingCells { count total fraction } } }
  }
}
```

---

### Relationships (Graph Traversal)

Every RESQML object has typed links to other objects. Use `objectRelations` to traverse:

```graphql
# Forward refs (targets): what does this grid reference?
{
  objectRelations(
    dataspace: "maap/drogon"
    typeName: "resqml20.obj_IjkGridRepresentation"
    uuid: "2c6de928-7e08-4601-b979-34048bd68c02"
    direction: "targets"
  ) { uuid name typeName direction contentType }
}
```

```graphql
# Reverse refs (sources): what properties/representations point to this object?
{
  objectRelations(
    dataspace: "maap/drogon"
    typeName: "resqml20.obj_IjkGridRepresentation"
    uuid: "2c6de928-7e08-4601-b979-34048bd68c02"
    direction: "sources"
  ) { uuid name typeName direction contentType }
}
```

**Common traversal patterns** (swap `typeName`, `uuid`, `direction`):

| Pattern | typeName | direction | What you get |
|---------|----------|-----------|--------------|
| Grid → CRS + StratColumn | `obj_IjkGridRepresentation` | targets | Referenced objects |
| Grid → all properties | `obj_IjkGridRepresentation` | sources | Attached ContinuousProperty/DiscreteProperty |
| Well Feature → Interp → Traj | `obj_WellboreFeature` | sources | Chain of representations |
| Horizon → surfaces | `obj_HorizonInterpretation` | sources | Grid2D representations |
| Surface → horizon | `obj_Grid2dRepresentation` | targets | Which horizon it represents |
| Well frame → log curves | `obj_WellboreFrameRepresentation` | both | All attached properties |

---

### Federated Search (OSDU + RDDMS)

Search the OSDU catalog and RDDMS simultaneously - results are merged by UUID:

```graphql
# Search both catalog and RDDMS for "grid"
{
  federatedSearch(
    text: "grid"
    searchCatalog: true
    searchRddms: true
    dataspaces: ["maap/drogon"]
    limit: 10
  ) {
    totalCatalog totalRddms totalMerged sources queryDescription
    hits {
      uuid title typeName dataspace
      foundInCatalog foundInRddms
      osduId osduKind
    }
  }
}
```

```graphql
# RDDMS-only with enrichment (relations + property statistics)
{
  federatedSearch(
    text: "Geogrid"
    searchCatalog: false
    searchRddms: true
    dataspaces: ["maap/drogon"]
    includeRelations: true
    includeProperties: true
    includeStatistics: true
    limit: 5
  ) {
    totalRddms totalMerged
    hits {
      uuid title typeName dataspace
      relations { uuid name typeName direction }
      properties {
        uuid title kind
        statistics { count minValue maxValue mean }
      }
    }
  }
}
```

```graphql
# Catalog-only - search by OSDU kind
{
  federatedSearch(
    text: "Drogon"
    kind: "osdu:wks:work-product-component--GenericRepresentation:*"
    searchCatalog: true
    searchRddms: false
    limit: 20
  ) {
    totalCatalog
    hits { uuid title typeName dataspace osduId osduKind foundInCatalog }
  }
}
```

**When to use which mode:**

| Scenario | Settings |
|----------|----------|
| Browse local un-indexed data (fast, offline) | `searchRddms:true`, others `false` |
| Check what's in the OSDU catalog | `searchCatalog:true`, others `false` |
| Verify catalog records exist in RDDMS | All three `true`, compare flags |
| Search remote + local RDDMS together | `searchRddms:true, searchRemoteRddms:true`, catalog off |
| Full discovery across everything | All three `true` (default) |
| Enrich results with relations/properties | Add `includeRelations`, `includeProperties`, `includeStatistics` |

---

### OSDU Search

For metadata lookups, spatial queries, and kind-based searches:

```json
{
  "kind": "osdu:wks:work-product-component--BusinessDecision:*",
  "query": "Drogon AND DG2",
  "limit": 50
}
```

```json
{
  "kind": "osdu:wks:work-product-component--SeismicHorizon:*",
  "spatialFilter": {
    "field": "data.SpatialArea.Wgs84Coordinates",
    "byBoundingBox": {
      "topLeft": { "latitude": 62.0, "longitude": 1.5 },
      "bottomRight": { "latitude": 58.0, "longitude": 3.5 }
    }
  }
}
```

---

### Array Statistics & Samples

```graphql
# Get array metadata, statistics, and sample values for any object
{
  objectArrays(
    dataspace: "maap/drogon"
    typeName: "resqml20.obj_Grid2dRepresentation"
    uuid: "02a9d0b6-1f7c-4553-994b-5060cd725d6d"
    includeStatistics: true
    includeSampleValues: true
    sampleSize: 10
  ) { path dataType dimensions totalElements statistics { count minValue maxValue mean stdDev } sampleValues }
}
```

Works with any object type - swap `typeName` + `uuid` for IjkGrids, WellboreFrames, etc.

---

## Property Aliases

You can use shorthand names instead of full RESQML property kinds. ORES resolves them automatically.

| Canonical name | Aliases | Unit |
|---|---|---|
| porosity | poro, phit, phi, nphi | v/v |
| permeability | perm, permx, permy, permz, kh | mD |
| water saturation | sw, swat, swatinit | v/v |
| oil saturation | so, soil | v/v |
| gas saturation | sg, sgas | v/v |
| net-to-gross | ntg, n2g | ratio |
| depth | tvd, tvdss, z | m |
| pressure | pres, pressure, bhp | bar |
| temperature | temp | °C |
| bulk density | rhob, den | g/cm³ |
| gamma ray | gr, gamma | API |
| resistivity | rt, res, ild | ohm·m |
| acoustic impedance | ai, imp | (m/s)·(g/cm³) |
| velocity | vp, vs, vel | m/s |
| facies | facies, lith, litho | - |
| zone | zone, region, segment | - |
| thickness | thick, dz, isochore | m |
| volume | vol, bulk_vol, bv | m³ |
| age | age, chrono | Ma |
| displacement | throw, heave | m |

Use the resolve endpoint to check an alias: `GET /api/graphql/resolve-alias?term=poro`

---

---

# Field Development Queries

ORES supports high-level queries that combine **spatial topology** (well locations, faults, stratigraphic correlation), **reservoir properties** (NTG, permeability, porosity), **production data** (per-well rates and cumulative), and **business decision records** (risks, development concepts, activities) into a single assessment.

These queries address common field development questions that cannot be answered by any single data source alone  they require traversing the RESQML object graph, evaluating array-level properties, and cross-referencing the OSDU catalog.

---

## Connectivity Explorer (`/connectivity`)

The Connectivity Explorer is a purpose-built UI that answers the fundamental field development question:

> **"Are two well intervals connected by good reservoir properties, or are they isolated by faults / poor rock quality?"**

### How it works

1. Select **Well A** and **Well B** from the Drogon wells
2. Choose the **target zone** (Valysar, Therys, Volon)
3. Set **property thresholds** (NTG min, Kh min, Sw max)
4. Toggle evidence sources (faults, production, BD records)
5. Click **Run Connectivity Query**

The engine performs a multi-step assessment:

| Step | Analysis | Data sources |
|------|----------|--------------|
| 1. Stratigraphic | Are both wells in the same zone? | WellboreMarkerSet, StratigraphicColumn |
| 2. Structural | Are there faults between segments? | TectonicBoundaryFeature, GridConnectionSet, StructuralOrganization |
| 3. Property corridor | Is the connecting rock good quality? | Grid ContinuousProperty (PHIT, KLOGH, NTG, Sw) per segment |
| 4. Production | Does performance confirm connectivity? | Per-well ColumnBasedTable (WOPR, WWCT) |
| 5. BD evidence | What do risk records and activities say? | Risk, DevelopmentConcept, Activity WPCs |
| 6. Synthesis | Connected / uncertain / isolated? | All of the above + recommendations |

### API

```http
POST /api/connectivity/query
Content-Type: application/json

{
  "well_a": "55/33-A-2",
  "well_b": "55/33-A-3",
  "zone": "Valysar",
  "dataspace": "maap/drogon",
  "property_filters": {"ntg_min": 0.5, "kh_min": 100, "sw_max": 0.6},
  "include_faults": true,
  "include_production": true,
  "include_bd_evidence": true
}
```

### Example Results

#### Example 1: A-2 vs A-3 (different segments, fault-baffled)

```
✗ UNCERTAIN CONNECTIVITY  (confidence: low)

Stratigraphic: ✓ Both wells penetrate Valysar Fm (shallow marine)
Structural:    ⚠ Fault F2 between CentralHorst ↔ EastLowland (trans=0.15, baffle)
Properties:    Corridor: porosity 0.215, perm 203 mD, NTG 0.55, Sw 0.37  moderate quality
Production:    A-3 underperforms vs A-2: WCT 58% vs 32%, Cum.Oil 1.4 vs 2.6 MSm³
BD Evidence:   Risk "FaultCompartment" mitigated for F1/F5/F6 but F2/F3 remain baffles
               Tracer from A-5: NOT detected in A-3 (confirms F2 barrier)
               Infill wells targeting East Lowland planned (Phase 2)

Recommendations:
  → Acquire 4D seismic to resolve connectivity uncertainty
  → Consider inter-well tracer test
  → Evaluate infill well in isolated segment
  → Investigate poor producer  possible completion or sweep issue
```

#### Example 2: A-1 vs A-2 (same segment, well-connected)

```
✓ CONNECTED  (confidence: high)

Stratigraphic: ✓ Both wells penetrate Valysar Fm (shallow marine)
Structural:    No bounding faults  same segment (CentralHorst)
Properties:    Corridor: porosity 0.240, perm 320 mD, NTG 0.68, Sw 0.28  excellent quality
Production:    Similar performance  both rated "good"
BD Evidence:   4D confirms communication, tracer detected A-5→A-1 (3 months)
```

---

## Compound Filter  Multi-Property Cell-Level AND

The `compoundFilter` extends `deepSearch` to apply **multiple property thresholds simultaneously at cell level**. Instead of asking "which grids have porosity > 0.25?" (single filter), you can ask "which cells have porosity > 0.25 AND permeability > 100 AND Sw < 0.4?"  only cells satisfying ALL conditions count.

### How it works

1. Each condition is evaluated independently as a bitmask over the property array
2. Bitmasks are ANDed together → only cells passing ALL conditions survive
3. The result reports the intersection count/fraction via `compoundMatch`
4. Memory-efficient: loads one array at a time (~7 MB), ANDs into a running bytearray mask

> **Backend:** PG-only. Degrades gracefully on REST backends with a warning in `queryDescription`.

### Syntax

```graphql
{
  deepSearch(
    dataspace: "maap/drogon"
    typeName: "resqml20.obj_IjkGridRepresentation"
    compoundFilter: [
      { titleContains: "PORO", operator: GT, threshold: 0.25 }
      { titleContains: "PERMX", operator: GT, threshold: 100.0 }
      { titleContains: "SWATINIT", operator: LT, threshold: 0.4 }
    ]
    includeStatistics: true
    limit: 5
  ) {
    backend totalScanned totalMatched queryDescription
    objects {
      uuid title
      compoundMatch { count total fraction }
      properties { title statistics { mean minValue maxValue } }
    }
  }
}
```

### Reading the results

| Field | Meaning |
|-------|---------|
| `compoundMatch.count` | Number of cells passing ALL conditions simultaneously |
| `compoundMatch.total` | Total active cells in the grid |
| `compoundMatch.fraction` | `count / total`  the "sweet spot" fraction |

A grid with `fraction: 0.12` means 12% of active cells have good porosity AND good permeability AND low water saturation  potential infill targets.

### Demo: Bypassed Oil (compound)

```graphql
# "Where is there good rock that still has oil?"
# Combines: high porosity + high perm + high remaining oil (So = 1 - Sw)
{
  deepSearch(
    dataspace: "maap/drogon"
    typeName: "resqml20.obj_IjkGridRepresentation"
    compoundFilter: [
      { titleContains: "PORO", operator: GT, threshold: 0.2 }
      { titleContains: "PERMX", operator: GT, threshold: 50.0 }
      { titleContains: "SWATINIT", operator: LT, threshold: 0.5 }
    ]
    includeStatistics: true
    limit: 5
  ) {
    objects { uuid title compoundMatch { count total fraction } }
  }
}
```

---

## Easy Mode  Field Development Buttons

The `/keys` Easy Mode tab includes **5 one-click field development buttons** that run full GraphQL preset queries without leaving Easy Mode:

| Button | What it runs | Key output |
|--------|-------------|------------|
| **Markers** | `markers_by_horizon`  lists wellbore markers grouped by horizon name | Horizon picks per well, depths, formation tops |
| **Bypassed Oil** | `field_bypassed_oil`  compound filter (PORO > 0.2 AND PERM > 50 AND Sw < 0.5) | Sweet-spot cell fraction per grid |
| **Water Breakthrough** | `field_water_breakthrough`  3 sub-queries (high-Sw zones, high-perm streaks, production anomalies) | Multi-alias result with explanation per sub-query |
| **Completion Pay** | `field_completion_ntg`  3 sub-queries (NTG, Kh product, Sw above OWC) | Best interval identification per well |
| **Segment Overview** | `field_segment_ranking`  4 sub-queries ranking segments by property quality | Segment-by-segment comparison table |

### How to use

1. Navigate to `/keys` → select **Easy Mode** tab
2. Click any **Field Dev** button (blue row below the standard query builder)
3. Results render as colored cards with explanation banners describing each sub-query
4. Click **"Show generated GraphQL"** to see the raw multi-alias query
5. For 3D visualisation, objects from all aliases are automatically extracted for the viewer

### Multi-alias result rendering

Compound preset queries return multiple named `deepSearch` aliases (e.g. `highSw`, `highPerm`, `production`). The Easy Mode renderer:
- Groups results by alias with a header banner explaining each sub-query's purpose
- Shows per-alias match counts and statistics
- Merges all alias objects for 3D rendering via `extractRenderableObjects()`

---

## Common Field Development Query Patterns

These queries combine multiple data sources to answer real field development questions. Each can be run via GraphQL presets on the `/keys` page.

### 1. Bypassed Oil Identification

> "Which fault block has high remaining saturation and enough permeability for an infill well?"

```graphql
# Step 1: Find grid segments with high Sw (remaining oil = 1 - Sw)
{
  deepSearch(
    dataspace: "maap/drogon"
    typeName: "resqml20.obj_IjkGridRepresentation"
    includeStatistics: true
    propertyFilter: {
      titleContains: "Sw"
      arrayFilter: { operator: GT, threshold: 0.5 }
    }
    limit: 5
  ) {
    objects {
      uuid title
      properties {
        title kind uom
        statistics { count minValue maxValue mean }
        matchingCells { count total fraction }
      }
    }
  }
}
```

Combined with segment volumetrics and well drainage patterns, this identifies bypassed compartments.

### 2. Water Breakthrough Diagnosis

> "Why did water cut rise faster than expected in A-3?"

```graphql
# Find high-perm streaks (potential water conduits) in well logs
{
  deepSearch(
    dataspace: "maap/drogon"
    typeName: "resqml20.obj_WellboreFrameRepresentation"
    includeStatistics: true
    propertyFilter: {
      titleContains: "KLOGH"
      arrayFilter: { operator: GT, threshold: 500.0 }
    }
    limit: 10
  ) {
    objects {
      uuid title
      properties {
        title kind uom
        statistics { mean maxValue }
        matchingCells { count total fraction }
      }
    }
  }
}
```

Cross-reference with:
- Fault seal quality (F2 transmissibility = 0.15 → partial conduit)
- Per-well production (A-3 WWCT rising at 2.5%/month vs expected 1.5%)
- BD risk record (compartment isolation confirms poor sweep)

### 3. Infill Well Targeting

> "Rank undrained segments by risk-weighted recoverable volume"

```graphql
# Step 1: Get volumetrics per segment (STOIIP from catalog)
{
  federatedSearch(
    text: "volume"
    kind: "osdu:wks:work-product-component--ColumnBasedTable:*"
    dataspaces: ["maap/drogon_dg"]
    searchCatalog: true
    searchRddms: false
    limit: 20
  ) {
    hits { uuid title osduKind }
  }
}
```

```graphql
# Step 2: Get property quality per segment from grid
{
  deepSearch(
    dataspace: "maap/drogon"
    typeName: "resqml20.obj_IjkGridRepresentation"
    includeStatistics: true
    propertyFilter: { titleContains: "NTG" }
    limit: 5
  ) {
    objects {
      uuid title
      properties {
        title statistics { mean minValue maxValue }
        matchingCells { count total fraction }
      }
    }
  }
}
```

Combine: STOIIP × NTG × (1 - risk_factor) → segment ranking for infill.

### 4. Injection Support Verification

> "Is injection from A-5 reaching producer A-2, or is a fault blocking sweep?"

```graphql
# Check fault connectivity between injector and producer segments
{
  faults: deepSearch(
    dataspace: "maap/drogon"
    typeName: "resqml20.obj_FaultInterpretation"
    includeRelations: true
    limit: 10
  ) {
    objects {
      uuid title
      relations { uuid name typeName direction }
    }
  }
  gridConn: deepSearch(
    dataspace: "maap/drogon"
    typeName: "resqml20.obj_GridConnectionSetRepresentation"
    includeRelations: true
    includeStatistics: true
    limit: 5
  ) {
    objects {
      uuid title
      relations { name typeName direction }
      properties { title kind statistics { mean } }
    }
  }
}
```

Cross-reference with per-well production:
- A-5 WWIR = 6,500 Sm³/d (full injection target)
- A-2 pressure stable at 270 bar (injection support confirmed)
- A-3 pressure declining at 2 bar/month (injection not reaching East Lowland)

### 5. Completion Optimization

> "Which interval in well A-3 has the best NTG × Kh product away from OWC?"

```graphql
# Well log properties for A-3
{
  deepSearch(
    dataspace: "maap/drogon"
    category: "well"
    titleContains: "A-3"
    includeStatistics: true
    includeRelations: true
    limit: 10
  ) {
    objects {
      uuid title typeName
      properties {
        title kind uom
        statistics { count minValue maxValue mean }
      }
      relations { name typeName direction }
    }
  }
}
```

Use well log PHIT, KLOGH, Sw curves to identify the best net interval above the OWC (from markers at 1,892m TVDSS in East Lowland).

---

## Per-Well Production Data

Individual well production vectors are available as `ColumnBasedTable` WPC records:

| Well | Type | Segment | Vectors |
|------|------|---------|---------|
| 55/33-A-1 | Producer | CentralHorst | WOPR, WWPR, WWCT, WBHP, WOPT |
| 55/33-A-2 | Producer | CentralHorst | WOPR, WWPR, WWCT, WBHP, WOPT |
| 55/33-A-3 | Producer | EastLowland | WOPR, WWPR, WWCT, WBHP, WOPT |
| 55/33-A-4 | Producer | WestLowland | WOPR, WWPR, WWCT, WBHP, WOPT |
| 55/33-A-5 | Injector | CentralHorst | WWIR, WBHP |
| 55/33-A-6 | Injector | EastLowland | WWIR, WBHP |

Each record includes a `Segment` column (fault compartment) and `Phase` column (History/Prediction), enabling queries like:

```json
{
  "kind": "osdu:wks:work-product-component--ColumnBasedTable:*",
  "query": "WellProd AND EastLowland"
}
```

### Key performance indicators (from production profiles)

| Well | Segment | Peak Oil (Sm³/d) | Final WCT | Cum. Oil (MSm³) | Rating |
|------|---------|------------------|-----------|------------------|--------|
| A-1 | CentralHorst | 3,500 | 35% | 2.8 | Good |
| A-2 | CentralHorst | 3,400 | 32% | 2.6 | Good |
| A-3 | EastLowland | 2,100 | 58% | 1.4 | Poor |
| A-4 | WestLowland | 2,700 | 42% | 2.0 | Average |

**A-3's poor performance** is explained by:
- Fault F2 baffling (trans = 0.15) → poor injection support from A-5
- Earlier water breakthrough (onset at 10 months vs 18 for CentralHorst wells)
- Lower NTG in East Lowland segment (0.42 vs 0.68 in CentralHorst)

---

## Fault Connectivity Data

Fault transmissibility multipliers are available as catalog records:

| Fault | Segments Connected | Transmissibility | Seal Quality |
|-------|-------------------|------------------|--------------|
| F1 | CentralHorst ↔ WestLowland | 0.80 | Open |
| F2 | CentralHorst ↔ EastLowland | 0.15 | Baffle |
| F3 | CentralNorth ↔ EastLowland | 0.10 | Baffle |
| F4 | WestLowland ↔ CentralSouth | 0.45 | Moderate |
| F5 | NorthHorst ↔ CentralRamp | 0.60 | Moderate |
| F6 | CentralRamp ↔ CentralHorst | 0.95 | Open |

A **Connectivity Matrix** summary record aggregates all fault properties:
- 2 open faults (F1, F6)  confirmed by 4D and tracer
- 2 moderate faults (F4, F5)  partially confirmed
- 2 baffles (F2, F3)  isolate East Lowland segment

### Ingestion options

| Method | When to use | API |
|--------|-------------|-----|
| REST array write | Update existing trans values on GridConnectionSet | `begin_transaction()` → `write_array()` → `commit()` |
| EPC re-upload | Add new fault objects or structural changes | ETP import CLI |
| WPC catalog record | Store seal assessment / connectivity matrix | OSDU Storage manifest ingest |

---

---

# Technical Appendix

---

## A. Architecture

```mermaid
graph LR
  C["ORES Client"] --> OSDU["OSDU Search API<br/><i>metadata, spatial, kind-based</i>"]
  C --> REST["RDDMS REST API<br/><i>browse dataspaces/types/objects/graph/arrays</i>"]
  C --> ETP["ETP WebSocket<br/><i>bulk import/export, streaming</i>"]
  C --> GQL["GraphQL /api/graphql/query<br/><i>deep search + arrays + graph</i>"]
  GQL --> A["Path A: OSDU Catalog · ES<br/>kind + text search"]
  GQL --> B["Path B: Local PG · asyncpg<br/>fastest, un-indexed data"]
  GQL --> Cr["Path C: Remote RDDMS · REST<br/>Azure-hosted dataspaces"]
  GQL --> D["Path D: Discovery · batch graph<br/>ETP Protocol 3 via REST"]
  A --> F["FederatedSearchResult<br/><i>merge by UUID</i>"]
  B --> F
  Cr --> F
  D --> F
```

| Path | Best for | Speed |
|------|----------|-------|
| OSDU Search | Records by kind, metadata keywords, spatial | Fast (metadata only) |
| RDDMS REST | Browse dataspaces, single objects, full XML | Medium |
| ETP WebSocket | Bulk EPC import/export, streaming | Fast |
| GraphQL (PG) | Deep filtering, array predicates, multi-dataspace | Fastest (10–50× vs REST) |
| GraphQL (Discovery) | Deep search on ADME/remote without PG access | Fast (1 call vs N+1) |
| GraphQL federated | OSDU + RDDMS simultaneously, UUID dedup | Fast (parallel) |

### Backend Selection Order

All query paths (GraphQL `deepSearch`, keys routes, manifest build) follow the same priority chain:

```
1. PostgreSQL    (GRAPHQL_PG_CONN_STRING set)      → SQL JOINs, batch queries  (fastest, local only)
   ↓ fallback if dataspace not in PG
2. Discovery     (RDDMS server ≥ 1.3.0 / M27)     → POST /query/graph/search  (1 batch call)
   ↓ fallback if server is pre-M27 or endpoint fails
3. REST N+1      (always available)                → individual list_sources / list_targets per object
```

Discovery support is **auto-detected** at runtime via `GET /health/info` (version ≥ 1.3.0).
Override with `RDDMS_DISCOVERY=1` (force on) or `RDDMS_DISCOVERY=0` (force off).

The `backend` field in `DeepSearchResult` tells you which path was used:
`"Discovery"`, `"PostgreSQL"`, or `"REST"`.

---

## B. RDDMS REST API

| Endpoint | Purpose | Min Version |
|----------|---------|-------------|
| `GET /dataspaces` | List all dataspaces | any |
| `GET /dataspaces/{ds}/resources` | Types with counts | any |
| `GET /dataspaces/{ds}/resources/{type}` | List objects | any |
| `GET /dataspaces/{ds}/resources/{type}/{uuid}` | Single object (XML) | any |
| `GET .../resources/{type}/{uuid}/targets` | Forward references | any |
| `GET .../resources/{type}/{uuid}/sources` | Reverse references | any |
| `GET .../resources/{type}/{uuid}/arrays` | List arrays | any |
| `GET .../resources/{type}/{uuid}/arrays/{path}` | Read array data | any |
| `POST /query/graph/search` | **Batch graph traversal** (multi-URI, configurable depth) | 1.3.0 (M27) |
| `POST /query/resources/find` | Flat resource enumeration (DiscoveryQuery) | 1.3.0 (M27) |
| `POST /query/objects/find` | Search + fetch full XML content | 1.3.0 (M27) |
| `GET /dataspaces/{ds}/deleted` | List deleted resources since timestamp | 1.3.0 (M27) |
| `POST /manifests/build` | Build OSDU manifest from ETP dataspace/URIs | any |
| `GET /health/info` | Server version, commit, build time | any |
| `GET /health/readiness` | ETP server reachability check | any |

> **Performance note:** Each REST call carries ~40–100 ms overhead (TLS, Azure gateway, JSON serialization). Deep queries that touch N objects × M properties × K arrays result in (N+M+K) serial HTTP calls - the _N+1 problem_. Prefer GraphQL+PG when available.

---

## C. GraphQL Query Reference

### All Available Queries

| Query | Purpose |
|-------|---------|
| `status` | Backend check (PG version or REST info) |
| `dataspaces { path uri }` | List dataspaces |
| `resqmlCategories { name count }` | List type categories (grid, well, surface, …) |
| `resourceTypes(dataspace)` | Types + counts |
| `resqmlObjects(dataspace, typeName)` | Browse objects |
| `objectRelations(dataspace, typeName, uuid, direction)` | Graph traversal |
| `objectArrays(dataspace, typeName, uuid)` | Arrays + statistics |
| `deepSearch(dataspace, typeName, propertyFilter)` | Combined filter |
| `deepSearch(dataspaces: [...])` | Multi-dataspace |
| `deepSearch(category: "well")` | Search by category (all types in group) |
| `federatedSearch(text, dataspaces, kind)` | OSDU catalog + RDDMS dual-path |

### PropertyFilter Fields

| Field | Type | Example |
|-------|------|---------|
| `kind` | String | `"General continuous"` |
| `titleContains` | String | `"PORO"`, `"PERMX"` |
| `arrayFilter.threshold` | Float | `0.25`, `500.0` |
| `arrayFilter.operator` | Enum | `GT`, `LT`, `GTE`, `LTE`, `EQ` |

### Federated Search Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `text` | String | `"*"` | Free-text filter (title match for RDDMS, query string for catalog) |
| `kind` | String | `*:*` | OSDU kind filter (catalog path only) |
| `typeName` | String | - | RESQML type filter (RDDMS paths only) |
| `dataspaces` | [String] | auto-discover | Which dataspaces to search |
| `searchCatalog` | Boolean | true | Enable OSDU catalog path |
| `searchRddms` | Boolean | true | Enable local PG path |
| `searchRemoteRddms` | Boolean | true | Enable remote RDDMS REST path |
| `includeRelations` | Boolean | false | Enrich hits with graph edges |
| `includeProperties` | Boolean | false | Enrich hits with attached properties |
| `includeStatistics` | Boolean | false | Compute array min/max/mean for properties |
| `propertyFilter` | PropertyFilter | - | Filter results by property name/threshold |
| `limit` | Int | 30 | Max results returned |

### How Federated Routing Works

1. Selected dataspaces are classified as _local_ (present in PG) or _remote_ (only on OSDU RDDMS).
2. Local dataspaces are queried via direct PostgreSQL; remote ones go through the REST API.
3. The OSDU catalog is searched independently (by `kind` + free-text).
4. Results are **merged by UUID** - if the same object appears in multiple sources, flags indicate where it was found: `foundInCatalog`, `foundInLocalRddms`, `foundInRemoteRddms`.

---

## D. RESQML Type Categories

| Category | Example types | GraphQL `category` |
|---|---|---|
| Grid | IjkGrid, UnstructuredGrid, Grid2d, GridConnectionSet | `"grid"` |
| Surface | TriangulatedSet, PolylineSet, PointSet, Grid2d | `"surface"` |
| Well | WellboreFeature, Trajectory, Frame, MarkerFrame, DeviationSurvey, BlockedWellbore | `"well"` |
| Structural | FaultInterpretation, HorizonInterpretation, GeobodyBoundary, BoundaryFeature, TectonicBoundary | `"structural"` |
| Stratigraphic | StratigraphicColumn, ColumnRankInterp, UnitInterp, OccurrenceInterp | `"stratigraphic"` |
| Property | ContinuousProperty, DiscreteProperty, CategoricalProperty, PointsProperty | `"property"` |
| Seismic | SeismicLatticeFeature, SeismicLineFeature | `"seismic"` |
| CRS | LocalDepth3dCrs, LocalTime3dCrs | `"crs"` |
| Representation | IjkGrid, UnstructuredGrid, Grid2d, TriangulatedSet, PolylineSet, PointSet, Trajectory, Frame | `"representation"` |
| Provenance | Activity, ActivityTemplate | - |
| Container | EpcExternalPartReference | - |

> `typeName` also accepts wildcards: `"*Grid*"` matches all grid types.

---

## E. Reference Data Endpoints

### `/api/graphql/reference`

Returns the full reference dataset used by Easy Mode:

```json
{
  "propertyKinds": [
    { "name": "porosity", "aliases": ["poro", "phit", "phi", "nphi"],
      "description": "Fraction of void space in rock", "uom": "v/v" },
    ...
  ],
  "resqmlTypes": [
    { "name": "resqml20.obj_IjkGridRepresentation", "short": "IjkGrid",
      "category": "Grid", "description": "3D geocellular grid (corner-point or parametric)" },
    ...
  ],
  "operators": [
    { "value": "GT", "label": "> (greater than)", "symbol": ">" },
    ...
  ],
  "aliasMap": { "poro": "porosity", "sw": "water saturation", "perm": "permeability", ... }
}
```

**Counts:** 20 property kinds, 29 RESQML types (9 categories), 5 operators, 90 alias entries.

### `/api/graphql/resolve-alias?term=<term>`

```bash
# Exact match
curl /api/graphql/resolve-alias?term=poro
# → { "matches": [{ "name": "porosity", "aliases": [...], "uom": "v/v" }], "mode": "exact" }

# Fuzzy match (multiple candidates)
curl /api/graphql/resolve-alias?term=sat
# → { "matches": [{ "name": "water saturation" }, { "name": "oil saturation" }, ...], "mode": "fuzzy" }
```

---

## F. Performance

_Measured on `maap/drogon` data (swedev). ETP values are reasoned estimates._

### Benchmark Summary

| Operation | REST API | Discovery | GraphQL + PG | ETP (est.) |
|-----------|----------|-----------|-------------|------------|
| **Simple listing** (50 objects) | 80–200 ms | 60–150 ms | **5–15 ms** | 10–30 ms |
| **Object + relations + arrays** | 300–600 ms | 100–200 ms | **10–30 ms** | 15–50 ms |
| **Deep search** (10 grids, PORO > 0.25) | 5–15 s | **0.3–1 s** | **0.1–0.3 s** | 0.1–0.4 s |
| **Large array read** (500K float64) | 1–3 s | 1–3 s | **0.1–0.3 s** | 0.05–0.2 s |
| **Setup complexity** | None (just URL) | `RDDMS_DISCOVERY=1` | PG access needed | ETP client |
| **Portability** | Any OSDU | Any OSDU (MR 271+) | Co-located only | Any ETP server |
| **Standard** | RDDMS REST v2 | ETP Discovery via REST | Internal | Energistics ETP 1.2 |

### Why PG is 10–50× Faster

| Factor | REST | GraphQL + PG |
|--------|------|-------------|
| **N+1 queries** | Deep search = `O(G × P × A)` serial HTTP calls | `O(1)` - batch SQL with `ANY($1::int[])` on the `rel` adjacency table |
| **Array transfer** | JSON text (`[0.123, …]`) ~1.5 MB per 100K floats | Binary `bytea` ~800 KB, decoded via `struct.unpack` in ~5 ms |
| **Network hops** | 2–3 (TLS → Azure Front Door → NestJS → PG) | 0 (co-located asyncpg → PG, binary wire protocol) |
| **Per-call overhead** | ~40–100 ms (TLS amortised, gateway, JSON serialization) | ~1–5 ms (binary protocol, connection pool) |

### Performance Tips

1. **Always prefer GraphQL + PG** when `GRAPHQL_PG_CONN_STRING` is set - the resolver auto-selects the fastest backend.
2. **Discovery is auto-detected** - on M27+ RDDMS servers (≥ 1.3.0), ORES automatically uses batch `graph_search` instead of N+1 REST calls. No env var needed.
3. **Force-override** with `RDDMS_DISCOVERY=1` (always use) or `RDDMS_DISCOVERY=0` (never use) if auto-detection gets it wrong.
4. **Use `category` for broad searches** - `category: "well"` searches all 10 well-related types in one query.
4. **Avoid REST for deep queries** - 10 grids × 3 properties = ~80 serial HTTP calls (~5 s). Discovery: ~0.5 s. PG: ~0.2 s.
5. **Batch optimization (PG):** Deep search of 20 objects with properties requires ~6 SQL round-trips instead of ~80.
6. **Batch optimization (Discovery):** `POST /query/graph/search` sends all candidate URIs in a single ETP session - no N+1.
7. **Concurrent REST:** The REST fallback fetches sources for up to 10 objects in parallel via `asyncio.gather`.
8. **Schema cache:** Dataspace→schema lookups are cached in-memory. Use `limit` and `dataspaces:[...]` instead of per-object loops.
9. **Large arrays:** PG binary transfer is 5–10× faster than JSON. Avoid reading arrays > 100K elements in tight loops via REST.
10. **Federated search** runs sources in parallel - enable only the ones you need to cut latency.
11. **Connection pooling** is automatic: `httpx.AsyncClient` for REST/Discovery, `asyncpg` pool (min=2, max=10) for PG.

---

## G. Setup – Local PostgreSQL

```bash
# 1. Start Docker (PG on 5433, ETP on 9002)
cd demo/drogonresqml && docker compose up -d

# 2. Import Drogon
./demo/drogonresqml/ingest.sh

# 3. Set env var (add to ~/.bashrc)
export GRAPHQL_PG_CONN_STRING="host=localhost port=5433 dbname=rddms user=foo password=bar"

# 4. Start ORES
ores   # or: uvicorn app.main:app --reload --port 8000

# 5. Verify
curl http://localhost:8000/api/graphql/info
curl -X POST http://localhost:8000/api/graphql/query \
  -H 'Content-Type: application/json' \
  -d '{"query":"{ status dataspaces { path } }"}'
```

| Environment | PG conn string location | Target |
|-------------|-------------------------|--------|
| Local dev | `~/.bashrc` export | Docker PG (`localhost:5433`) |
| k8s | `k8s/secret.yaml` | Azure PG (`rddms-pg.database.azure.com`) |

### PostgreSQL Schema (openkv)

| Table | Content |
|-------|---------|
| `res` | Resource metadata (obj_id, guid, name) |
| `obj` | XML content |
| `rel` | Relationship edges |
| `ary` | Array metadata (path, type, dimensions) |
| `bin` | Array binary data (chunks) |
| `typ` | Type registry |

---

## I. Discovery Batch Graph Search

The `POST /query/graph/search` endpoint (available on RDDMS ≥ 1.3.0 / M27) wraps ETP Discovery Protocol 3 in a single REST call. It replaces the N+1 pattern of calling `/sources` and `/targets` per object.

### Request

```http
POST /api/reservoir-ddms/v2/query/graph/search
Authorization: Bearer <token>
Content-Type: application/json
data-partition-id: <partition>

{
  "uris": [
    "eml:///dataspace('demo/drogon')/resqml20.obj_IjkGridRepresentation('uuid1')",
    "eml:///dataspace('demo/drogon')/resqml20.obj_IjkGridRepresentation('uuid2')"
  ],
  "scope": "targets",
  "depth": 1,
  "dataObjectTypes": ["resqml20.obj_ContinuousProperty"],
  "countObjects": true,
  "includeSecondaryTargets": false,
  "includeSecondarySources": false
}
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `uris` | string[] | required | EML URIs of root objects to traverse from |
| `scope` | string | `"targets"` | `self`, `sources`, `targets`, `sourcesOrSelf`, `targetsOrSelf` |
| `depth` | int | 1 | Graph traversal depth (1 = immediate neighbours) |
| `dataObjectTypes` | string[] | `[]` | Filter results to these types only (empty = all) |
| `countObjects` | bool | false | Include source/target counts per resource |
| `includeSecondaryTargets` | bool | false | Follow secondary target edges |
| `includeSecondarySources` | bool | false | Follow secondary source edges |

### Response

```json
{
  "resources": [
    { "uri": "eml:///dataspace('demo/drogon')/resqml20.obj_ContinuousProperty('uuid3')",
      "name": "PORO", "contentType": "resqml20.obj_ContinuousProperty",
      "uuid": "uuid3", "sourceCount": 0, "targetCount": 1 }
  ],
  "links": [
    { "source": "eml:///...uuid3...", "target": "eml:///...uuid1..." }
  ]
}
```

### Version Detection

ORES auto-detects M27+ support by probing `GET /health/info` on first use:

```python
# app/osdu.py
await osdu.rddms_supports_discovery(access_token)  # True if version >= 1.3.0
```

The result is cached for the process lifetime. Override with env:
- `RDDMS_DISCOVERY=1` - force enable (skip probe)
- `RDDMS_DISCOVERY=0` - force disable (never use graph/search)
- unset - auto-detect at runtime

---

## J. Keys Routes - Backend Selection Design

The `/keys` endpoints serve the keys.html explorer page. Each endpoint follows the same three-tier fallback:

### Route Map

| Route | Purpose | PG query | Discovery (M27+) | REST fallback |
|-------|---------|----------|-------------------|---------------|
| `GET /keys/dataspaces.json` | List dataspaces | `pg_list_dataspaces` | - | `GET /dataspaces` |
| `GET /keys/types.json` | Types in dataspace | `pg_list_types` | - | `GET /dataspaces/{ds}/resources` |
| `GET /keys/objects.json` | List objects + labels | `pg_list_resources` + `pg_batch_relations` | `POST /query/graph/search` (label enrichment) | N × `GET .../targets` |
| `GET /keys/object.json` | Single object detail | `pg_get_object_and_arrays` | - | `GET .../resources/{type}/{uuid}` |
| `GET /keys/object/graph.json` | Object graph (sources+targets) | `pg_list_relations` | `POST /query/graph/search` (×2: targets+sources) | `GET .../sources` + `GET .../targets` |
| `GET /keys/object/array.json` | Array values + stats | `pg_read_array` | - | `GET .../arrays/{path}` |
| `POST /dataspaces/manifest/build-uris` | Manifest ref expansion | - | `POST /query/graph/search` (depth=2, both scopes) | `GET .../sources` + `GET .../targets` |
| `POST /dataspaces/manifest/build-from-selection` | Multi-object manifest | - | `POST /query/graph/search` (batch) | N × `GET .../sources/targets` |

### Fallback Logic

```
┌─────────────────────────────────────────────────────────────────┐
│  keys/objects.json  (relation enrichment for representation     │
│  labels - e.g. disambiguate "TopVolantis Depth" vs "Time")      │
├─────────────────────────────────────────────────────────────────┤
│  1. PG available + rows have obj_id?                            │
│     → pg_batch_relations(pool, ds, obj_ids)   [1 SQL, ~5ms]    │
│                                                                 │
│  2. rddms_supports_discovery(token)?                            │
│     → graph_search(uris, scope="targets", depth=1)   [1 call]  │
│     ← parse links[] → rel_types_by_uuid                        │
│                                                                 │
│  3. Legacy fallback                                             │
│     → asyncio.gather(list_targets(u) for u in uuids[:200])     │
│       [N calls, semaphore=8]                                    │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  keys/object/graph.json  (full source+target graph)             │
├─────────────────────────────────────────────────────────────────┤
│  1. PG available?                                               │
│     → pg_list_relations(pool, ds, typ, uuid, "both")            │
│                                                                 │
│  2. rddms_supports_discovery(token)?                            │
│     → graph_search([uri], scope="targetsOrSelf", depth=1)       │
│     → graph_search([uri], scope="sources", depth=1)             │
│     ← merge into sources[] + targets[]                          │
│                                                                 │
│  3. Legacy fallback                                             │
│     → list_sources(at, enc, typ, uuid)                          │
│     → list_targets(at, enc, typ, uuid)                          │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  dataspaces/manifest/build-uris  (ref expansion before build)   │
├─────────────────────────────────────────────────────────────────┤
│  1. rddms_supports_discovery(token)?                            │
│     → graph_search([primary_uri], scope="targetsOrSelf", d=2)   │
│     → graph_search([primary_uri], scope="sources", depth=1)     │
│     ← collect all resource URIs + link endpoints into uris set  │
│                                                                 │
│  2. Legacy fallback                                             │
│     → asyncio.gather(list_sources, list_targets)                │
│     ← parse nodes into uris set                                 │
│                                                                 │
│  Then: filter out _MANIFEST_SKIP_TYPES                          │
│  Then: POST /manifests/build with safe_uris                     │
└─────────────────────────────────────────────────────────────────┘
```

### Performance Impact

| Scenario (remote dataspace, 50 objects) | Before (REST N+1) | After (Discovery) | Improvement |
|----------------------------------------|--------------------|--------------------|-------------|
| Object listing with labels | 50 × 80ms = ~4s | 1 × 150ms = ~0.15s | **~25× faster** |
| Object graph (1 object) | 2 × 80ms = ~160ms | 2 × 100ms = ~200ms | ~same (small N) |
| Manifest ref expansion | 2 × 80ms = ~160ms | 2 × 120ms = ~240ms (but depth=2) | More refs found |

The biggest win is in object listing (N=50+). Single-object graph is similar in latency but gains configurable depth for manifest builds.

---

## I. Native RDDMS GraphQL Endpoint

The Reservoir DDMS etp-client (v1.3+) exposes a **native GraphQL endpoint** at `/graphql`. This is a direct NestJS/Apollo Server implementation that operates on the ETP protocol with:

- **Single ETP session per request**  no N+1 WebSocket connections
- **DataLoader batching**  all field resolves in the same tick coalesced
- **Lazy field resolution**  `content`, `arrays`, `targets`, `sources` only fetched when selected

### Endpoint URLs

| Environment | URL |
|-------------|-----|
| Local (ores3 stack) | `http://localhost:8080/graphql` |
| ADME/OSDU | `https://<hostname>/api/reservoir-ddms/v2/graphql` |

### How ORES uses it

ORES automatically probes the native GraphQL endpoint on startup. If available:
- **Graph traversals** (targets, sources) use a single GQL call instead of individual REST calls
- **Batch graph search** replaces N individual REST requests with one GraphQL `graphSearch` query
- **Dataspaces listing** goes through GQL when PG is unavailable

If the endpoint is not available (older etp-client, or ADME without the module), ORES **falls back transparently to REST**  no user action needed.

### Native GraphQL Schema

```graphql
type Query {
  dataspaces: [GqlDataspace!]!
  resources(dataspaceUri: String!, dataObjectTypes: [String!]): [GqlResource!]!
  resource(uri: String!): GqlResource
  graphSearch(uris: [String!]!, depth: Int = 1): GqlGraph!
}

type GqlDataspace {
  uri: ID!
  name: String!
  storeLastWrite: String
  storeCreated: String
}

type GqlResource {
  uri: ID!
  name: String!
  dataObjectType: String
  sourceCount: Int
  targetCount: Int
  lastChanged: String
  storeLastWrite: String
  activeStatus: String
  targets(depth: Int = 1): [GqlResource!]!    # lazy - only fetched when selected
  sources: [GqlResource!]!                     # lazy
  content: GqlObjectContent                    # lazy - expensive (Store protocol)
  arrays: [GqlArrayMeta!]!                     # lazy - metadata only
}

type GqlGraph {
  resources: [GqlResource!]!
  edges: [GqlEdge!]!
}

type GqlEdge {
  sourceUri: String!
  targetUri: String!
  path: String
}

type GqlObjectContent {
  uri: ID!
  dataObjectType: String
  data: JSON                                   # Full parsed EML/RESQML/WITSML object
}

type GqlArrayMeta {
  uri: String!
  pathInResource: String!
  dimensions: [Int!]
  logicalArrayType: String
  transportArrayType: String
  storeLastWrite: String
}
```

### Example: Batch graph in one call

```graphql
# Get the full subgraph for 3 objects at once (single ETP session)
{
  graphSearch(
    uris: [
      "eml:///dataspace('maap/drogon')/resqml20.obj_IjkGridRepresentation(2c6de928-7e08-4601-b979-34048bd68c02)",
      "eml:///dataspace('maap/drogon')/resqml20.obj_WellboreFeature(50495987-88f4-4e39-95c8-0b2624298c47)"
    ]
    depth: 2
  ) {
    resources { uri name dataObjectType }
    edges { sourceUri targetUri }
  }
}
```

### Configuration

| Env var | Purpose | Default |
|---------|---------|---------|
| `RDDMS_GRAPHQL_URL` | Override native GQL endpoint URL | Auto-derived from `OSDU_BASE_URL` |

### Performance: GQL vs REST for graph traversal

| Scenario | REST (N+1 calls) | Native GraphQL | Improvement |
|----------|------------------|----------------|-------------|
| 10 objects, targets + sources | 20 HTTP calls × 80ms | 1 call × 120ms | **~13× faster** |
| Batch graph (5 roots, depth=2) | 5 × (2 × 80ms) = 800ms | 1 × 200ms | **~4× faster** |
| List resources + check targets exist | 1 + N calls | 1 call (lazy fields) | **N× fewer calls** |

---

## J. Links

| Resource | URL |
|----------|-----|
| OSDU Search | [community.opengroup.org](https://community.opengroup.org/osdu/platform/system/search-service) |
| RDDMS / OpenETPServer | [community.opengroup.org](https://community.opengroup.org/osdu/platform/domain-data-mgmt-services/reservoir/open-etp-server) |
| ETP 1.2 Spec | [energistics.org](https://www.energistics.org/energistics-transfer-protocol/) |
| RESQML 2.0/2.2 | [energistics.org](https://www.energistics.org/resqml/) |
| Strawberry GraphQL | [strawberry.rocks](https://strawberry.rocks/) |
| GraphQL language reference | [graphql.org/learn](https://graphql.org/learn/) |
| ORES GraphQL module | `app/graphql_router.py` |
| ORES source & issues | [github.com/equinor/ores](https://github.com/equinor/ores) |
