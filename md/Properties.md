# RESQML & OSDU Property Model

> Properties describe physical or categorical quantities attached to geological objects - grids, surfaces, wellbores. This guide covers how RESQML models properties, how OSDU references them, and how ORES resolves and displays them.
>
> **Source of truth:** [Properties.md (RDDMS Home)](https://community.opengroup.org/osdu/platform/domain-data-mgmt-services/reservoir/home/-/blob/main/docs/Properties.md) — this page adds ORES resolution logic and Equinor property conventions.
>
> **See also**: [RESQML Technical Reference (Energistics)](https://www.energistics.org/resqml-data-standards/) · [OSDU Property & Facet Schemas](https://community.opengroup.org/osdu/data/data-definitions/) · [Reservoir DDMS Home](https://community.opengroup.org/osdu/platform/domain-data-mgmt-services/reservoir/home/-/blob/main/README.md)

---

## 1) Property Object Types

RESQML defines properties as objects that attach to a **supporting representation** (grid, surface, wellbore frame). Each property object carries values - one per cell, node, or sample - plus metadata about what it represents.

| RESQML type | Value domain | Typical use |
|---|---|---|
| `ContinuousProperty` | Floating-point array | Porosity, permeability, saturation, pressure |
| `DiscreteProperty` | Integer array | Facies code, zone index, fault block ID |
| `CategoricalProperty` | Integer → string lookup | Lithology categories, fluid type |
| `CommentProperty` | String per element | Annotations, notes (rare) |
| `PointsProperty` | XYZ per element | Displacement vectors (rare) |

### RESQML XML skeleton (ContinuousProperty)

```xml
<resqml20:ContinuousProperty uuid="..." title="PORO">
  <resqml20:Count>1</resqml20:Count>
  <resqml20:IndexableElement>cells</resqml20:IndexableElement>
  <resqml20:SupportingRepresentation>
    <eml:ContentType>resqml20.obj_IjkGridRepresentation</eml:ContentType>
    <eml:Title>Drogon Grid</eml:Title>
    <eml:UUID>grid-uuid-here</eml:UUID>
  </resqml20:SupportingRepresentation>
  <resqml20:PropertyKind>
    <resqml20:Kind>porosity</resqml20:Kind>  <!-- StandardPropertyKind -->
  </resqml20:PropertyKind>
  <resqml20:MinimumValue>0.01</resqml20:MinimumValue>
  <resqml20:MaximumValue>0.38</resqml20:MaximumValue>
  <resqml20:UOM>v/v</resqml20:UOM>
</resqml20:ContinuousProperty>
```

Key fields:
- **SupportingRepresentation** - the grid/surface this property lives on
- **IndexableElement** - `cells`, `nodes`, `columns`, `faces`, etc.
- **PropertyKind** - what physical quantity (see §2)
- **UOM** - unit of measure

---

## 2) Property Kinds - Standard vs Local

### StandardPropertyKind

RESQML ships a fixed set of ~45 standard property kinds defined by Energistics. The most common in subsurface workflows:

| Kind | Aliases (ORES resolves these) | UoM | Domain |
|---|---|---|---|
| `porosity` | poro, phit, phi, nphi | v/v | Continuous |
| `rock permeability` | perm, permx, permy, permz | mD | Continuous |
| `saturation` | sw, so, sg, swat | v/v | Continuous |
| `net-to-gross` | ntg, netfrac | v/v | Continuous |
| `depth` | tvd, tvdss, md | m | Continuous |
| `pressure` | pres, bhp | bar | Continuous |
| `volume` | vol, bulk, pore | m³ | Continuous |
| `velocity` | vp, vs | m/s | Continuous |
| `density` | dens, rhob | g/cm³ | Continuous |
| `acoustic impedance` | ai, impedance | kg/m²/s | Continuous |
| `gamma ray` | gr, sgr, cgr | API | Continuous |
| `shale volume` | vsh, vclay | v/v | Continuous |
| `facies` | facies, lithology | unitless | Discrete |
| `zone` | zone, region, fipnum | unitless | Discrete |

ORES uses an alias table (see `graphql_refdata.py`) to resolve flexible names:
```
User types "PHIT" → alias lookup → canonical "porosity"
                                  → RDDMS deepSearch propertyFilter: {kind: "porosity"}
```

### LocalPropertyKind

When a property doesn't fit any standard kind, RESQML allows **local property kinds** - project-defined with a title and parent kind:

```json
{
  "$type": "resqml20.LocalPropertyKind",
  "Title": "Net Pay Thickness",
  "ParentPropertyKind": {
    "Kind": "thickness"
  }
}
```

ORES extracts these via `_extract_property_kind()` in `graphql_search.py`, which tries:
1. `StandardPropertyKind.Kind` (direct string)
2. `LocalPropertyKind.Title` (nested reference or string)
3. Fallback to `PropertyKind.Title`

---

## 3) OSDU PropertyType Reference Data

OSDU extends RESQML property kinds with **PropertyType** reference-data records, used in structured WPC schemas (volumes, GeoLabelSet). Three namespaces:

### 3.1 ReservoirEstimatedVolumePropertyType

For volume columns in `ReservoirEstimatedVolumes` WPC:

| PropertyType | Meaning | Typical UoM |
|---|---|---|
| `Bulk` | Gross/bulk rock volume (GRV) | m³ |
| `Net` | Net rock volume (NRV = GRV × NTG) | m³ |
| `Pore` | Pore volume (PORV = NRV × φ) | m³ |
| `HydrocarbonPore` | HC pore volume (HCPV) | m³ |
| `Oil` | Stock tank oil in place (STOIIP) | m³ |
| `Gas` | Gas initially in place (GIIP) | m³ |
| `AssociatedGas` | Solution gas from oil | m³ |
| `RecoverableOil` | Recoverable oil volume | m³ |
| `RecoveryFactor` | RF as fraction | % |

### 3.2 ReservoirPropertyType

For petrophysical columns in `GeoLabelSet`:

| PropertyType | UoM |
|---|---|
| `Porosity` | fraction |
| `Permeability` | mD |
| `PermeabilityGeometric` | mD |
| `WaterSaturation` | fraction |
| `NetToGross` | fraction |
| `NetPay` | m |

> **Convention**: OSDU uses fractions (0–1), not percentages.

### 3.3 PVT PropertyType

For fluid property tables (`ColumnBasedTable`):

| PropertyType | Typical UoM |
|---|---|
| `Pressure` | bar |
| `Temperature` | °C |
| `FormationVolumeFactor` | m³/Sm³ |
| `GasOilRatio` | Sm³/Sm³ |
| `Viscosity` | cP |
| `BubblePointPressure` | bar |

---

## 4) Facets - Qualifying Properties

Facets add a second dimension to property identity. The same PropertyType can appear multiple times, distinguished by facets:

### FacetType: statistics

| FacetRole | Meaning |
|---|---|
| `P10` | 10th percentile (pessimistic) |
| `P50` | 50th percentile (median) |
| `P90` | 90th percentile (optimistic) |
| `ArithmeticMean` | Ensemble mean |
| `Minimum` / `Maximum` | Range bounds |
| `StandardDeviation` | Spread measure |

### FacetType: scenario

| FacetRole | Meaning |
|---|---|
| `BASE` | Base case geological model |
| `LOW` / `HIGH` | Bounding scenarios |
| `OPTIMISTIC` / `PESSIMISTIC` | Risk-weighted variants |

### Column naming pattern

```
Oil.P50  →  PropertyType = Oil,  FacetType = statistics,  FacetRole = P50
Oil.BASE →  PropertyType = Oil,  FacetType = scenario,    FacetRole = BASE
```

### JSON example

```json
{
  "ColumnName": "Oil.P50",
  "PropertyTypeID": "dev:reference-data--ReservoirEstimatedVolumePropertyType:Oil:",
  "FacetIDs": [
    {
      "FacetTypeID": "dev:reference-data--FacetType:statistics",
      "FacetRoleID": "dev:reference-data--FacetRole:P50"
    }
  ],
  "UnitOfMeasureID": "dev:reference-data--UnitOfMeasure:m3"
}
```

---

## 5) Property Groups

In RESQML, properties are organized into **PropertySet** objects that group related properties on the same representation. Common groupings:

| Group | Properties | Context |
|---|---|---|
| Static model | porosity, permeability, NTG, facies, zone | Geocellular grid |
| Dynamic model | pressure, saturation, volume | Simulation timesteps |
| Seismic attributes | amplitude, coherence, AI, velocity | Horizon surfaces |
| Well logs | GR, density, sonic, resistivity | Wellbore frame |

In ORES, the GraphQL UI groups properties by RESQML type for navigation:

- **Continuous Logs / Properties** - `ContinuousProperty` objects
- **Discrete / Facies** - `DiscreteProperty` objects

RDDMS `deepSearch` can filter by property kind:
```graphql
deepSearch(
  dataspaceUri: "eml:///dataspace('project/dg1')"
  filter: {
    typeName: "resqml20.obj_ContinuousProperty"
    propertyFilter: {
      kind: "porosity"
      arrayFilter: { operator: GT, threshold: 0.15 }
    }
  }
) { ... }
```

---

## 6) RESQML → OSDU Property Mapping

How the same physical quantity appears in different contexts:

| Concept | RESQML (EPC/ETP) | OSDU (Storage/Search) |
|---|---|---|
| **Identity** | `PropertyKind.Kind = "porosity"` | `PropertyTypeID = "...ReservoirPropertyType:Porosity:"` |
| **Value type** | `ContinuousProperty` vs `DiscreteProperty` | Inferred from column `ValueType` (number / integer / string) |
| **Unit** | `UOM` attribute on property object | `UnitOfMeasureID` on column |
| **Statistics** | Not in RESQML (post-processing) | `FacetIDs` with `FacetType:statistics` |
| **Scenarios** | Separate dataspaces or property sets | `FacetIDs` with `FacetType:scenario` |
| **Attachment** | `SupportingRepresentation` reference | `ParentObjectID` + `AssociatedObjectIDs` |
| **Array data** | HDF5 dataset (via EPC or ETP) | RDDMS array store (ETP GetDataArray) |

### Alias resolution flow in ORES

```
User search term         "PHIT"
        ↓
Alias table              PHIT → "porosity"        (graphql_refdata.py)
        ↓
RDDMS deepSearch         propertyFilter: {kind: "porosity"}
        ↓
Matched objects          ContinuousProperty(PORO), ContinuousProperty(PHIT_UPSC), ...
        ↓
OSDU enrichment          PropertyTypeID lookup → "Porosity" display label
```

---

## 7) Design Considerations

### Continuous vs Discrete - choose correctly

| | Continuous | Discrete |
|---|---|---|
| Values | Floating-point | Integer codes |
| Interpolation | Meaningful (averaging, kriging) | Not meaningful |
| Examples | Porosity 0.22, Pressure 250 bar | Facies code 3, Zone index 7 |
| Display | Colour ramp (gradient) | Colour map (categorical) |

### When to use StandardPropertyKind vs LocalPropertyKind

| Use standard when… | Use local when… |
|---|---|
| The quantity is in the RESQML spec | Custom/derived quantity |
| Interoperability matters | Only used within your project |
| Example: porosity, permeability | Example: "Net Pay Thickness", "HC Column Height" |

### PropertyType naming

- OSDU PropertyType IDs are **PascalCase** (`Porosity`, `NetToGross`)
- RESQML standard kinds are **lowercase with spaces** (`porosity`, `net-to-gross`)
- ORES alias resolution handles both conventions
