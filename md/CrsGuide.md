# CRS Guide: RESQML (RDDMS) → OSDU

Practical guide for mapping coordinate reference systems from **RESQML 2.0.1** (as stored in **RDDMS**) into **OSDU**, as the ETP client does when building an M27 manifest. Focused on the NCS / Equinor case.

**The one rule:** OSDU keeps the CRS *record* pure (just the geodetic system); every local-frame parameter - offsets, rotation, axis order, units, Z direction - goes on the **dataset metadata**. RESQML keeps both on the `LocalDepth3dCrs`. Mapping = split them apart.

---

## Part 1 - Guide

### Do I need a Bound CRS?

OSDU prefers a **Bound CRS** (projected CRS pinned to an explicit datum transform / CT) so there is no datum-shift ambiguity.

| Your projected CRS | Action |
|--------------------|--------|
| ETRS89-based (EPSG 25831–25836) | Plain `Projected` - already WGS84-aligned, no shift |
| ED50 / WGS72 / WKT+`TOWGS84` | **`BoundProjected`** - add the CT (e.g. ED50→WGS84 EPSG:1612) |
| Operator code, no EPSG | Register in OSDU CRS Catalog as `Projected:LocalAuthority::<code>` |

> NCS rule of thumb: anything **ED50** needs a Bound CRS; modern **ETRS89** does not.

### 3-step recipe

1. **Read** `LocalDepth3dCrs` / `LocalTime3dCrs` from the dataspace.
2. **Resolve** projected + vertical CRS to OSDU IDs (Bound if a datum shift applies).
3. **Emit** `coordinateReferenceSystemID`, `verticalCRSID`, and `rddms/localFrame/*`. The ETP client does all three automatically.

### Common NCS mappings

| RESQML CRS | Usage | OSDU CRS ID | Bound? |
|------------|-------|-------------|:------:|
| EPSG:25831 / 25832 | ETRS89 UTM 31N/32N | `Projected:EPSG::25832` | no |
| EPSG:23031 / 23032 | ED50 UTM 31N/32N | `BoundProjected:EPSG::23031_EPSG::1612` | **yes** |
| EPSG:23037 | ED50 UTM 37S (Drogon) | `BoundProjected:EPSG::23037_EPSG::1612` | **yes** |
| EPSG:5714 | MSL height | `Vertical:EPSG::5714` | - |
| WKT + `TOWGS84[...]` | legacy ED50 | extract shift → match EPSG CT → BoundProjected | **yes** |
| `VerticalUnknownCrs` (no WKT) | old models | `verticalCRSID: null` (keep uom/direction in localFrame) | - |
| `VerticalUnknownCrs` (with WKT) | WKT in Unknown field | `VerticalCRS:WKT:<title>` + raw WKT as persistableRef | - |

### Worked example - Drogon (`maap/drogon2`)

The curated Drogon EPC uses **ED50 / UTM zone 37S (EPSG:23037)**, vertical **MSL**. M27 emits two CRS work-product-components:

```
work-product-component--LocalModelCompoundCrs:1.2.0
  ├─ Local Depth CRS → resqml20.obj_LocalDepth3dCrs  "Projected CRS: ED50 / UTM zone 37S (EPSG:23037). Vertical: MSL."
  └─ Local Time CRS  → resqml20.obj_LocalTime3dCrs   "Projected CRS: ED50 / UTM zone 37S (EPSG:23037). Vertical: Two-way time."
```

Because EPSG:23037 is ED50, geometry points get a **BoundProjected** frame-of-reference, not a plain projected one.

### Pitfalls

| Issue | Consequence | Fix |
|-------|-------------|-----|
| Plain Projected used for ED50 | Coords off 50–200 m | Always Bound non-ETRS89 data |
| Axis order EN vs NE | X/Y swapped | Check `ProjectedAxisOrder`, normalize to `easting northing` |
| Z direction ambiguity | Depths inverted | Preserve `ZIncreasingDownward` |
| Local frame written into CRS record | OSDU misinterprets | Offsets/rotation go on dataset metadata only |
| `ArealRotation` unit | Rotation wrong | RESQML stores `dega` or `rad`; output normalized to degrees |
| >1 projected CRS per dataspace | Undefined local frames | One projected CRS per RDDMS dataspace |

---

## Part 2 - Technical

### RESQML 2.0.1 CRS model

Two levels, **one projected CRS per dataspace**:

| Level | Object | Holds |
|-------|--------|-------|
| Global | Projected 2D CRS | EPSG/WKT/GML/LocalAuthority geodetic reference |
| Local | `LocalDepth3dCrs` / `LocalTime3dCrs` | `XOffset`/`YOffset`/`ZOffset`, `ArealRotation`, `ProjectedAxisOrder`, units, `ZIncreasingDownward` + refs to projected & vertical CRS |

Every geometry object references a Local 3D CRS → which references the global projected CRS. This keeps coordinates numerically stable in a local frame while preserving geodetic traceability.

Projected/vertical identification forms (EnergyML Common): `ProjectedEpsgCrs` (preferred), `ProjectedWktCrs`, `ProjectedGmlCrs` (rare), `ProjectedLocalAuthorityCrs` (e.g. NPD codes), `ProjectedUnknownCrs` (legacy; may hold WKT).

### RESQML peculiarities (watch these)

- **`ArealRotation` is a measure, not a number** - `{ "_": 15, "Uom": "dega" }` or `Uom: "rad"`. Always read the `Uom`.
- **Z is positive-down when `ZIncreasingDownward: true`** (the usual depth case). Do not assume math convention.
- **Vertical CRS is often `VerticalUnknownCrs`** - if the `Unknown` field contains WKT (`VERTCRS[` for WKT2, `VERT_CS[` for WKT1) it is now extracted as `persistableReferenceVerticalCrs`; otherwise `verticalCRSID: null`.
- **WKT can hide in `ProjectedUnknownCrs.Unknown`** - detected only if it matches `/^PROJC(RS|S)\[/`; other strings are ignored.
- **WKT can hide in `VerticalUnknownCrs.Unknown`** - detected only if it matches `/^VERT(CRS|_CS)\[/`; other strings are ignored.
- **`TOWGS84[...]` inside WKT is the datum shift** - it is what justifies a BoundProjected ID.
- **Offsets keep coordinates small** - global = offset + rotated local; never store the offset in the OSDU CRS record.

### What M27 manifest generation emits

For each `Local*3dCrs` the ETP client produces a **`LocalModelCompoundCrs:1.2.0`** WPC (auto-described with the resolved projected + vertical names). For each geometry object it builds spatial info via `createSpatialInfoFrom2dPoints`, filling:

| OSDU field | Source | Example |
|------------|--------|---------|
| `FrameOfReferenceCRS.coordinateReferenceSystemID` | projected CRS | `...:Projected:EPSG::25832` / `...:BoundProjected:EPSG::23037_EPSG::1612` / `...Projected:WKT:<title>` |
| `FrameOfReferenceCRS.persistableReference` | raw WKT or `""` | `PROJCS["ED50 / UTM zone 31N",...]` |
| `SpatialPoint.AsIngestedCoordinates.VerticalCoordinateReferenceSystemID` | vertical CRS | `...:Vertical:EPSG::5714` / `VerticalCRS:WKT:<title>` |
| `SpatialPoint.AsIngestedCoordinates.persistableReferenceVerticalCrs` | vertical EPSG or WKT | `{"authCode":{"auth":"EPSG","code":5714}}` / raw VERTCRS WKT |

A missing vertical CRS is left **undefined** (not an error).

### localFrame keys (lossless round-trip)

| Key | RESQML source | Type |
|-----|---------------|------|
| `rddms/localFrame/xOffset` / `yOffset` / `zOffset` | `XOffset` / `YOffset` / `ZOffset` | number |
| `rddms/localFrame/arealRotationDeg` | `ArealRotation` → degrees | number |
| `rddms/localFrame/projectedAxisOrder` | `ProjectedAxisOrder` | string |
| `rddms/localFrame/projectedUom` / `verticalUom` | `ProjectedUom` / `VerticalUom` | string |
| `rddms/localFrame/zIncreasingDownward` | `ZIncreasingDownward` | boolean |
| `rddms/localFrame/crsVersion` | `"eml20"` (2.0.1) / `"eml23"` (2.2) | string |

These keys let you reconstruct the RESQML CRS from OSDU metadata with no data loss.

### Coordinate transform (offset + rotation)

θ = `ArealRotation` normalized to radians:

```
x_global = XOffset + x_local·cos(θ) + y_local·sin(θ)
y_global = YOffset − x_local·sin(θ) + y_local·cos(θ)
```

### Examples - RESQML JSON → OSDU

**Typical NCS - ETRS89, no shift (plain Projected):**
```json
// RESQML
{ "$type": "resqml20.obj_LocalDepth3dCrs",
  "XOffset": 400000.0, "YOffset": 6500000.0, "ZOffset": 0.0,
  "ProjectedAxisOrder": "easting northing", "ProjectedUom": "m", "VerticalUom": "m",
  "ZIncreasingDownward": true,
  "ProjectedCrs": { "$type": "eml20.ProjectedCrsEpsgCode", "EpsgCode": 25832 },
  "VerticalCrs":  { "$type": "eml20.VerticalUnknownCrs" } }
// OSDU
{ "coordinateReferenceSystemID": "opendes:reference-data--CoordinateReferenceSystem:Projected:EPSG::25832",
  "verticalCRSID": null,
  "rddms/localFrame/xOffset": 400000.0, "rddms/localFrame/yOffset": 6500000.0,
  "rddms/localFrame/zIncreasingDownward": true, "rddms/localFrame/crsVersion": "eml20" }
```

**Legacy ED50 - Bound CRS (projected + vertical both EPSG):**
```json
// RESQML
{ "$type": "resqml20.obj_LocalDepth3dCrs",
  "ArealRotation": { "_": 0, "Uom": "rad" },
  "ProjectedCrs": { "$type": "eml20.ProjectedCrsEpsgCode", "EpsgCode": 23031 },
  "VerticalCrs":  { "$type": "eml20.VerticalCrsEpsgCode",  "EpsgCode": 5714 } }
// OSDU
{ "coordinateReferenceSystemID": "opendes:reference-data--CoordinateReferenceSystem:BoundProjected:EPSG::23031_EPSG::1612",
  "verticalCRSID": "opendes:reference-data--CoordinateReferenceSystem:Vertical:EPSG::5714" }
```

**WKT in `Unknown` field (heuristic-detected):**
```json
// RESQML
{ "ProjectedCrs": { "$type": "eml20.ProjectedUnknownCrs",
    "Unknown": "PROJCS[\"ED50 / UTM zone 31N\", GEOGCS[\"ED50\", DATUM[\"ED50\", SPHEROID[...], TOWGS84[-87,-98,-121,0,0,0,0]]]]" } }
// OSDU → coordinateReferenceSystemID = "...Projected:WKT:<title>", persistableReference = the raw WKT
```

### OSDU CRS records

| Kind | ID pattern | Purpose |
|------|------------|---------|
| Projected | `...:Projected:EPSG::25832` | 2D projected system |
| Vertical | `...:Vertical:EPSG::5714` | vertical datum |
| BoundProjected | `...:BoundProjected:EPSG::23031_EPSG::1612` | projected + explicit CT; consumed directly by CRS Convert v3 |

For non-EPSG operator CRS: register `Projected:LocalAuthority::<code>` in the CRS Catalog with a WKT2 `definition`, then reference that ID.

### RESQML 2.2 (EML 2.3) 

v2.2 is released but not yet in production. The ETP client normalizes it to the **same OSDU output**; only `crsVersion` differs (`"eml23"`).

| Aspect | 2.0.1 | 2.2 |
|--------|-------|-----|
| CRS object | `resqml20.obj_LocalDepth3dCrs` | `eml23.LocalEngineeringCompoundCrs` |
| Projected CRS | inline `ProjectedCrs` | separate `LocalEngineering2dCrs` (resolved via DOR) |
| Offsets | `XOffset`/`YOffset`/`ZOffset` | `OriginProjectedCoordinate1/2` + `OriginVerticalCoordinate` |
| Rotation | `ArealRotation` (dega/rad) | `LocalEngineering2dCrs` azimuth |
| Encoding | XML only | full JSON (Common v2.3) |

> The only practical difference: the extra DOR hop to fetch `LocalEngineering2dCrs` before building `localFrame`.

### References

- [RESQML CRS overview][r-crs] - one-projected-CRS-per-dataspace rule
- [AbstractLocal3dCrs attributes][r-abs] - offsets, rotation, axis order, Z
- [EnergyML Common CRS classes][c-crs] - EPSG/GML/WKT/LocalAuthority/Unknown
- [OSDU CRS Catalog][os-cat] · [CRS Convert v3][os-conv] · [ADR: dynamic CRS/CT][os-adr]

[r-crs]: https://docs.energistics.org/RESQML/RESQML_TOPICS/RESQML-000-066-0-C-sv2010.html
[r-abs]: https://docs.energistics.org/RESQML/RESQML_TOPICS/RESQML-500-010-0-R-sv2010.html
[c-crs]: https://docs.energistics.org/COM/COM_TOPICS/COM-000-106-0-R-sv2100.html
[os-cat]: https://community.opengroup.org/osdu/platform/system/reference/crs-catalog-service
[os-conv]: https://community.opengroup.org/osdu/platform/system/reference/crs-conversion-service/-/blob/master/docs/v3/tutorial/CRS_Convert_Service_howto.md
[os-adr]: https://community.opengroup.org/osdu/platform/system/home/-/issues/94
