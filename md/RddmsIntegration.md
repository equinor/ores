# RESQML-to-OSDU Integration - Approaches, Trade-offs & Practical Experience

> Response to discussion points A-D on ingestion tooling, RESQML construction, and catalog integration.
> Based on working implementations in ORES/Drogon (2.0.1 + 2.2), open-etp-client M27 generator, and operational experience on ADME.

---

## 1. Ingestion Approaches - What Exists Today

Four paths exist to get RESQML data into RDDMS + OSDU catalog. They differ in what the user deploys, what tooling parses the EPC, and where the catalog manifest is built.

```text
                                 +-----------------+
   EPC file                      |  OSDU Catalog   |
   (RESQML XML + HDF5)           |  (WPC records)  |
         |                       +--------^--------+
         |                                |
         v                       Osdu_ingest workflow
  +------+-------+                        |
  |   Path A     |               +--------+--------+
  | ETP import   +-------------->| RDDMS (ETP/PG)  |
  | (openETPServer CLI)          | owns RESQML graph|
  +--------------+               | + arrays         |
                                 +---------+--------+
  +--------------+                         |
  | Path B       |               manifest built from
  | REST import  +------------>  RDDMS content
  | (transactional XML->JSON)    (M27 generator)
  +--------------+

  +--------------+
  | Path C       |     No RDDMS
  | File/Dataset +---> File Service upload + Workflow DAG
  | service + DAG|     (SegY-to-VDS pattern)
  +--------------+

  +--------------+
  | Path D       |     No RDDMS, no ETP
  | Direct EPC   +---> Parse EPC locally, build manifest,
  | parsing      |     push to catalog only
  +--------------+
```

### Path A - ETP import (current primary path)

**How it works:** openETPServer CLI imports EPC into a local or remote RDDMS PostgreSQL via ETP protocol. Objects, arrays, relationships, and topology are preserved. M27 manifest generator (NestJS) then reads RDDMS content and builds OSDU catalog records.

**What we use:**
- `openETPServer --import-epc drogon.epc --target maap/drogon` (276 objects, ~18s, 90MB)
- M27 generator: 420 RESQML objects -> 161 OSDU records (object compression)
- Catalog push via `Osdu_ingest` workflow

**Pros:**
- RDDMS owns the full RESQML graph (FIRP, topology, arrays, CRS, property kinds)
- Graph queries work immediately (parents, children, references via foreign keys)
- Array data is served from RDDMS (fast: <50ms via direct PG, sub-second via REST)
- Transactions and dataspaces give isolation and reproducibility
- M27 manifest is built from authoritative RDDMS content (not brittle local parsing)
- Standards-based: ETP 1.2 protocol, RESQML 2.0.1/2.2 schemas

**Cons:**
- User must deploy ETP client (openETPServer CLI or Docker stack)
- Large arrays can be unstable without timeout/retry tuning (lesson learned: `--timeout 60s,120s --transaction-retries 5`)
- ETP delete rights are limited on shared instances (cannot purge dataspaces without owner entitlement)
- M27 generator requires NestJS build (`npx tsc` -> dist), Docker restart for changes

**Operational experience (Drogon):**
- 2.0.1: interop clean import 278 objs + catalog 142 records. eqndev additive 2005 objs (shared multi-user).
- 2.2 subset: interop 207 objs + catalog 100 records. eqndev additive 446 objs + catalog 100 records.
- Both instances: `Osdu_ingest` workflow FINISHED, all records indexed.

### Path B - REST transactional import

**How it works:** RDDMS REST API accepts XML->JSON converted objects in transactional batches. No ETP protocol needed.

**Pros:** Simpler deployment (HTTP only). Transaction semantics.
**Cons:** Requires XML->JSON conversion. Less mature tooling.

### Path C - File/Dataset service + DAG (SegY-to-VDS pattern)

**How it works:** Upload RESQML EPC+H5 to OSDU File/Dataset service. Trigger a DAG (Airflow workflow) that imports into RDDMS server-side. User never deploys ETP client.

**This is what Debasis proposes in point B - and it's a valid pattern.** Seismic DDMS considered this for sdutil in V4 (stalled). Bluware's SegYImport utility follows this model for seismic.

**Pros:**
- User uploads a file and clicks "import" - no local tooling
- Server-side processing - scalable, auditable, reproducible
- Same pattern as SegY-to-VDS (proven for seismic)

**Cons:**
- Requires a DAG/workflow to be deployed and maintained on the OSDU platform
- DAG must handle: EPC validation, ETP import, M27 manifest generation, catalog push
- No existing DAG for RESQML today (would need to be built)
- Large files (>1GB grids, 10GB+ simulation results) need chunked upload
- Debugging is harder (server-side logs, no interactive feedback)

**Assessment:** This is the right long-term direction for non-expert users. But it requires deploying a server-side RDDMS import DAG - which is infrastructure work, not a library swap.

### Path D - Direct EPC parsing (no RDDMS)

**How it works:** Parse EPC XML locally (Python stdlib, regex, or fesAPI/energyml). Build OSDU manifest directly. Push to catalog. Arrays go to blob storage or are lost.

**What we have:** `build_full_manifest.py` does regex-based XML extraction from EPC to build M27 manifests without needing ETP.

**Pros:** No RDDMS dependency. Works offline.
**Cons:** Arrays are not served (no consumption API). Graph queries don't work. Values are separated from meaning (see RddmsGov principle #3).

---

## 2. EnergyML Parser vs fesAPI vs Custom Parsing

### What each tool does

| Tool | Language | Reads | Writes | RESQML versions | Array handling |
|------|----------|-------|--------|-----------------|----------------|
| **fesAPI** (Energistics) | C++/Python | EPC+H5 | EPC+H5 | 2.0.1 (ignores 2.2) | Full HDF5 read/write |
| **energyml** (Geosiris) | Python | EPC+H5 | EPC+H5 | 2.0.1 + 2.2 + 2.3 | Lossy on read (array paths dropped) |
| **Custom XML** (ORES) | Python | EPC XML | - | 2.0.1 + 2.2 | Regex/ElementTree, no HDF5 |
| **open-etp-client** | TypeScript | RDDMS JSON | M27 manifest | 2.0.1 + 2.2 | RDDMS arrays (no local H5) |

### Our experience

**fesAPI:**
- C++ library with Python bindings. Mature for 2.0.1.
- **Does not support RESQML 2.2** ("could not be wrapped" for all 2.2 objects).
- Good for validation (`resqml-validate` passes 276 objs / 0 err / 0 warn on curated Drogon 2.0.1).
- Heavy dependency (C++ build, SWIG bindings). Overkill if you only need metadata extraction.

**energyml:**
- Pure Python. Supports 2.0.1 + 2.2 + 2.3 schemas natively.
- Good for object construction and serialization (guaranteed schema-valid by construction).
- **Array read is lossy:** `ContinuousProperty.values_for_patch` -> `[AbstractValueArray()]` (H5 paths gone). IjkGrid: only 2/8 H5 paths survive round-trip. Cannot use energyml read->export for array-bearing objects.
- Array write works if you construct fresh from raw XML paths + h5py data.
- Validation is over-strict for 2.2: 607 CRITICAL errors on valid Geosiris EPC (false positives on `value_count_per_indexable_element` + UoM regex).
- Used successfully for our 2.2 EPC construction path.

**Custom XML parsing (ORES current approach):**
- Regex + ElementTree extraction from EPC ZIP entries.
- Fast, minimal dependencies, works for metadata extraction.
- No schema validation (fragile if EPC structure varies).
- Adequate for building M27 manifests from known-good EPCs.

### Is EnergyML adequate as a DAG replacement?

**For point A (Debasis' diagram):** EnergyML can parse RESQML objects from EPC for metadata extraction - it handles both 2.0.1 and 2.2. But it cannot replace the ETP import into RDDMS (it's a parser, not a data store). The DAG workflow (point B) still needs ETP or REST to load objects into RDDMS.

**For point B (DAG approach):** A server-side DAG could use energyml to parse the uploaded EPC, then use ETP or REST to import into RDDMS. EnergyML would handle the parsing layer; RDDMS handles storage and serving. This is viable - but the DAG itself (file upload trigger, EPC validation, RDDMS import orchestration, M27 manifest generation, catalog push) is the hard part, not the parser.

**Bottom line:** The parser choice (fesAPI vs energyml vs custom) matters less than the integration architecture. All three can extract metadata. None of them replaces the need for RDDMS to serve arrays and maintain the object graph.

---

## 3. RESQML Construction from Common Sources (Point C)

### What objects to create and why

The RESQML object model follows FIRP: Feature - Interpretation - Representation - Property. The right level of FIRP depends on the source data.

#### Seismic horizon data

```text
Source: Gridded TWT picks (Ni x Nj regular lattice + Z values)

RESQML objects needed:
  LocalDepth3dCrs              - coordinate system (offsets, rotation, Z direction)
  Grid2dRepresentation         - the geometry (origin, spacing, node counts, Z array)
  ContinuousProperty           - Z values attached to Grid2dRepresentation (kind: depth)

  If geological parent exists:
    LocalBoundaryFeature       - the geological feature (e.g. "BCU")
    HorizonInterpretation      - the interpretation (age, conformability)
    Grid2dRepresentation       - linked to HorizonInterpretation

  If no parent (standalone map):
    Grid2dRepresentation       - unlinked (no Feature/Interpretation)
    → OSDU: GenericBinGrid WPC (not StructureMap)
```

#### Scattered point data (e.g. average porosity from wells)

```text
Source: N wells, each with (X, Y, value) for a property in a zone

RESQML objects needed:
  LocalDepth3dCrs              - coordinate system
  PointSetRepresentation       - XYZ coordinates of all points
  ContinuousProperty           - values attached to PointSetRepresentation
                                 (kind: porosity, or local "Average Zone Porosity")

  → OSDU: GenericProperty WPC
  → No FIRP needed (these are not geological surfaces)
```

#### Grid properties (reservoir model)

```text
Source: Eclipse/OPM grid with PORO, PERMX, SW, FACIES per cell

RESQML objects needed:
  LocalDepth3dCrs              - coordinate system
  IjkGridRepresentation        - 3D grid geometry (Ni x Nj x Nk, pillar shape, geometry arrays)
  ContinuousProperty (PORO)    - porosity values, StandardPropertyKind: porosity, UoM: v/v
  ContinuousProperty (PERMX)   - permeability values, StandardPropertyKind: rock permeability, UoM: mD
  ContinuousProperty (SW)      - saturation values, StandardPropertyKind: saturation, UoM: v/v
  DiscreteProperty (FACIES)    - facies codes, LocalPropertyKind: "General discrete", unitless
  DiscreteProperty (ZONE)      - zone indices, StandardPropertyKind: zone, unitless

  → Each property has SupportingRepresentation pointing to the IjkGrid
  → IndexableElement = cells
  → OSDU: GenericRepresentation WPC (grid) + GenericProperty WPC per property
```

### Property kind selection rationale

Use **StandardPropertyKind** when the quantity matches an Energistics-defined kind (porosity, permeability, saturation, depth, pressure, etc.). This enables:
- Cross-project discovery ("find all porosity properties")
- Alias resolution (ORES resolves PHIT/PHI/NPHI -> porosity)
- RDDMS deepSearch filtering (`propertyFilter: {kind: "porosity"}`)

Use **LocalPropertyKind** when:
- The quantity is derived or custom (e.g. "Net Pay Thickness", "HC Column Height")
- No standard kind matches
- Always set a parent standard kind for partial interoperability

### Continuous vs Discrete - choose correctly

| | Continuous | Discrete |
|---|---|---|
| Values | Floating-point | Integer codes |
| Interpolation | Meaningful (averaging, kriging) | Not meaningful |
| Property kind | porosity, permeability, saturation | facies, zone, fault block |
| Display | Color ramp (gradient) | Color map (categorical) |
| RESQML type | `ContinuousProperty` | `DiscreteProperty` |
| OSDU equivalent | Column with ValueType: number | Column with ValueType: integer |

---

## 4. RESQML-to-Catalog Record Mapping (Point D)

### M27 object compression

Not every RESQML object becomes a catalog record. OSDU M27 defines which RESQML types map to which WPC kinds, and many objects compress or merge.

Drogon example: **420 RESQML objects -> 161 OSDU records**

| RESQML objects | OSDU catalog record | What happens |
|---|---|---|
| ContinuousProperty + DiscreteProperty | GenericProperty WPC | Multiple properties on same grid -> separate WPCs |
| Grid2dRepresentation | StructureMap or GenericBinGrid WPC | One WPC per representation |
| IjkGridRepresentation | GenericRepresentation WPC | One WPC for the grid |
| LocalBoundaryFeature + GeneticBoundary | LocalBoundaryFeature (master-data) | Feature + type merged |
| WellboreFeature + Interpretation | Wellbore (master-data) | Already exists in OSDU master data |
| LocalCrs, MdDatum, PropertyKind | Fields on parent records | Metadata, not separate records |
| EpcExternalPartReference | Not cataloged | Internal HDF5 backing store |

### CRS mapping (critical challenge)

RESQML stores CRS as `LocalDepth3dCrs` with offsets, rotation, axis order, and vertical datum. OSDU splits this into separate fields:

```text
RESQML LocalDepth3dCrs:
  ProjectedEpsgCode: 23031         (ED50 / UTM zone 31N)
  VerticalEpsgCode: 5714           (MSL depth)
  XOffset: 457200.0                (easting origin)
  YOffset: 6462400.0               (northing origin)
  ZOffset: 0.0
  ArealRotation: 0.0 (dega)
  ProjectedAxisOrder: easting northing
  ZIncreasingDownward: true

OSDU catalog record:
  coordinateReferenceSystemID: "BoundProjected:EPSG::23031_EPSG::1612"  (ED50 needs Bound!)
  verticalCRSID: "VerticalCRS:EPSG::5714"
  rddms/localFrame/offsetX: 457200.0
  rddms/localFrame/offsetY: 6462400.0
  rddms/localFrame/rotation: 0.0
  rddms/localFrame/zDirection: "increasing downward"
```

**Key issues:**
- ED50 requires `BoundProjected` CRS (e.g. `BoundProjected:EPSG::23037_EPSG::1612`). ETRS89 uses plain `Projected`.
- ArealRotation units vary (degrees vs radians) - must normalize.
- `ProjectedAxisOrder` (easting/northing) must match OSDU convention.
- `ZIncreasingDownward` flag is critical for correct depth display.
- Some old RESQML files have `VerticalUnknownCrs` - metadata gap, not an error.

### Horizon data - why round-trip is non-trivial

Verifying catalog-stored metadata against original source data is hard for horizons because RDDMS transforms the representation:

1. **Regular grid assumption:** RESQML `Grid2dRepresentation` stores origin + spacing + node counts. Irregular grids are not supported.
2. **Null padding:** Sparse grids may have null values where the surface doesn't exist. Arrays are flattened (nested -> 1D).
3. **CRS transform:** The Z-array values are in the CRS of the `LocalDepth3dCrs`. To compare with source, you need offset + rotation + Z-direction.
4. **Resampling:** If the source grid doesn't align with the RESQML lattice, values are resampled (interpolated). The original points are lost.

**Practical verification approach:**
- Fetch array from RDDMS: `GET /dataspaces/{ds}/resources/{uri}/arrays` (or via ETP GetDataArray)
- Apply CRS transform (offset, rotation, Z-direction) to get real-world coordinates
- Compare against source data within tolerance

---

## 5. Challenges & Solutions Summary

| Challenge | Status | Solution |
|---|---|---|
| User must deploy ETP client | Solved locally | Docker Compose stack (PG + ETP + REST). Long-term: server-side DAG (point B) |
| fesAPI doesn't support 2.2 | Solved | Use energyml for 2.2 construction; custom XML for metadata extraction |
| energyml array read is lossy | Worked around | Construct array elements fresh from raw XML paths + h5py; don't round-trip via energyml |
| Large array instability | Solved | Timeout + retry tuning (`--timeout 60s,120s --transaction-retries 5 --reconnect-retries 5`) |
| ETP delete rights on shared instances | Open | Recommend dedicated dataspaces. Purge requires owner entitlement. |
| CRS mapping complexity (ED50, Bound CRS) | Documented | CRS Guide + localFrame metadata pattern. Must be replicated per tool. |
| M27 object compression rules | Working | open-etp-client TypeScript generators. PropertyType fallback by lowercased Code. |
| Missing OSDU schemas | Solved | Registered 3 permissive stubs (BoundaryFeature:1.2.0, CurveMainFamily, SamplingDomainType) |
| 2.0.1 wellbore FIRP gap in M27 generator | Fixed | MR 269: added WellboreInterpretation + WellboreTrajectoryRepresentation converters for 2.0.1 |
| EPC validation strictness | Pragmatic | Gate = reference integrity + RDDMS import success. energyml/XSD over-strictness is advisory only. |
| Empty Interpretation anti-pattern | Documented | Don't fabricate FIRP. Create Feature/Interpretation only when semantic fields are filled, reuse is real, or strat linkage exists. |
| Server-side DAG for RESQML import | Missing | The key gap for point B. Needs: file upload trigger, EPC validation, ETP import, M27 generation, catalog push. |

---

## 6. Recommendations

### Short-term (existing tools)

1. **Provide "Hello World" programs** (point C): Build sample scripts using energyml (Python, no C++ deps) that create RESQML from:
   - Gridded horizon (numpy array -> Grid2dRepresentation + ContinuousProperty)
   - Scattered points (CSV -> PointSetRepresentation + ContinuousProperty)
   - Grid properties (Eclipse INIT -> IjkGridRepresentation + properties)
   Each sample should explain FIRP object selection with the decision tree above.

2. **Document the catalog mapping** (point D): For each sample, show the M27 manifest that results and how to verify round-trip via RDDMS array retrieval + CRS transform.

3. **Keep ETP as the primary import path** with Docker Compose for developer convenience.

### Long-term (infrastructure)

4. **Build a server-side RESQML import DAG** (point B): Upload EPC to File/Dataset service, trigger workflow that:
   - Validates EPC (reference integrity, schema version)
   - Imports into RDDMS via ETP (server-side, no user deployment)
   - Generates M27 manifest
   - Pushes to catalog via Osdu_ingest
   - Returns status + record IDs

5. **Parser choice for the DAG:** energyml for validation + metadata extraction. ETP for RDDMS import. fesAPI only if 2.0.1-only validation is needed.

6. **sdutil convergence:** If Seismic DDMS V4 DAG pattern materializes, align RESQML import DAG on the same infrastructure (shared file upload, workflow engine, status reporting).
