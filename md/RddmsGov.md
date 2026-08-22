# RDDMS Governance & Usage Guide

> A practical guide for **users** (geoscientists, reservoir engineers) and **data managers** who work with the Reservoir Domain Data Management Service.

[[_TOC_]]

---

## What Is RDDMS?

The Reservoir DDMS stores, serves, and manages subsurface model data — the RESQML objects that describe geological structures, grids, surfaces, properties, and their relationships.

```mermaid
flowchart LR
    subgraph You["What you do"]
        Upload["Upload model<br/>(EPC + H5)"]
        Query["Query & consume<br/>(REST / ETP)"]
        Discover["Discover via<br/>OSDU Search"]
    end

    subgraph RDDMS["What RDDMS does"]
        Store["Store objects +<br/>arrays + graph"]
        Manifest["Build OSDU<br/>catalog records"]
        Serve["Serve data to<br/>applications"]
    end

    subgraph Catalog["What OSDU Catalog does"]
        Index["Index metadata<br/>for search"]
        Govern["Govern access<br/>& lifecycle"]
    end

    Upload --> Store
    Store --> Manifest
    Manifest --> Index
    Discover --> Index
    Index -.->|DDMSDatasets link| Serve
    Query --> Serve
```

**The fundamental principle:**

> Catalog **discovers** reservoir models. RDDMS **manages and serves** reservoir model content.

---

## Why Not Just Store Arrays?

RESQML is not "metadata + arrays." It's a **domain object graph** where meaning comes from linked objects:

```mermaid
graph TD
    F[Feature<br/><i>what exists in nature</i>] --> I[Interpretation<br/><i>how we understand it</i>]
    I --> R[Representation<br/><i>how we describe it numerically</i>]
    R --> G[Geometry / Topology<br/><i>coordinates, connectivity</i>]
    R --> P[Property<br/><i>values per cell/node</i>]
    P --> PK[PropertyKind + Unit<br/><i>what the values mean</i>]
    R --> CRS[CRS<br/><i>where in the world</i>]
```

If you split this graph across systems (arrays in one, objects in another), every application must reassemble the meaning. RDDMS keeps them together.

| System | Owns | Does NOT own |
|--------|------|-------------|
| **RDDMS** | Model graph, arrays, topology, properties, derived objects | Enterprise wells, official logs, raw seismic |
| **OSDU Catalog** | Discovery metadata, WPC summaries, lineage, governance | Numerical arrays, object relationships |
| **Other DDMSes** | Their domain data (wells, logs, seismic, CRS, units) | Reservoir model objects |

---

## How Data Gets In

```mermaid
flowchart TD
    subgraph Input["Your data"]
        EPC["EPC + H5 file"]
        XML["RESQML/WITSML XML"]
        App["Desktop app<br/>(Petrel, GAIA)"]
    end

    subgraph Ingest["Ingestion paths"]
        REST["REST API<br/>POST /epc/upload"]
        ETP["ETP WebSocket<br/>(binary, fast)"]
        CLI["CLI import<br/>openETPServer put"]
    end

    subgraph RDDMS["RDDMS"]
        PG[(PostgreSQL<br/>objects + arrays)]
    end

    subgraph Catalog["OSDU Catalog"]
        WPC["WPC records<br/>searchable"]
    end

    EPC --> REST
    EPC --> CLI
    XML --> REST
    App --> ETP

    REST --> PG
    ETP --> PG
    CLI --> PG

    PG -->|autoIngest=true| WPC
    PG -->|POST /manifests/build| WPC
```

| Path | Best for | Catalog registration |
|------|----------|---------------------|
| **EPC upload** (`POST /epc/upload`) | One-shot model upload | `?autoIngest=true` — automatic |
| **ETP WebSocket** | Streaming, desktop apps, large arrays | Separate manifest build step |
| **REST PUT** | Web clients, scripting | Separate manifest build step |
| **CLI import** | Offline bulk import | Manual manifest + push |

### Auto-Ingest: One-Call Ingestion

With `autoIngest=true`, the EPC upload stores your data AND registers it in the OSDU catalog in a single call — matching the user experience of other DDMSes (Seismic, Wellbore):

| Mode | How it works | Data searchable |
|------|-------------|-----------------|
| `autoIngest=records` (default) | Pushes directly to Storage Service | Immediately |
| `autoIngest=workflow` | Submits to Airflow DAG | After 30-90s |
| `autoIngest=false` | No catalog registration | Only via RDDMS APIs |

---

## Dataspaces: Where Your Data Lives

Every piece of data lives in a **dataspace** — a named, governed container:

```mermaid
flowchart TD
    subgraph Project["Project-X"]
        WIP["project-x/wip<br/>🔓 Unlocked<br/><i>Active work</i>"]
        V1["project-x/v1<br/>🔒 Locked<br/><i>DG1 snapshot</i>"]
        V2["project-x/v2<br/>🔒 Locked<br/><i>DG2 snapshot</i>"]
        SOR["project-x/sor<br/>🔒 Locked<br/><i>Approved model</i>"]
    end

    WIP -->|"clone + lock"| V1
    WIP -->|"iterate, clone + lock"| V2
    V2 -->|"promote"| SOR
```

| Dataspace type | Lock | Purpose | Who can write |
|---------------|------|---------|---------------|
| **WIP** (work-in-progress) | Unlocked | Active modelling | Project contributors |
| **Snapshot** | Locked | Gate evidence, reproducibility | Nobody (immutable) |
| **SoR** (system of record) | Locked | Approved model version | Nobody (immutable) |

### Rules

- **WIP is isolated** — project teams work without affecting others
- **Snapshots are immutable** — once locked, content cannot change
- **ACL = data-room boundary** — access is controlled per dataspace
- **Sharing = access grant, not copy** — avoid uncontrolled replication

---

## The Publish Workflow

```mermaid
sequenceDiagram
    participant User as Modeller
    participant WIP as RDDMS WIP
    participant QC as Reviewer
    participant SNAP as Locked Snapshot
    participant CAT as OSDU Catalog

    User->>WIP: Write/update model objects
    User->>QC: Request review
    QC->>WIP: Validate graph, arrays, CRS
    
    alt Approved
        User->>SNAP: Clone WIP → lock
        SNAP->>CAT: Build manifest → push WPCs
        Note over CAT: Data discoverable via Search
        User->>CAT: Create Activity (provenance)
    else Rejected
        QC-->>User: Feedback
        User->>WIP: Revise
    end
```

Each publish creates:
1. **Locked snapshot** — immutable model state
2. **OSDU WPC records** — searchable catalog entries with `DDMSDatasets[]` links
3. **Activity record** — provenance (who, when, what changed, inputs/outputs)
4. **Lifecycle event** — human-readable changelog entry

---

## What RDDMS Owns vs. What It References

### RDDMS Owns (model content)

- Features, interpretations, representations
- Grid geometry and topology
- Surface meshes and point sets
- Continuous and discrete properties (PORO, PERMX, SW, FACIES...)
- Structural frameworks and sealed models
- Model-derived objects (blocked wells, upscaled logs, grid/well intersections)
- Property kinds, stratigraphic context within the model
- Binary arrays (geometry, values)

### RDDMS References (external authority)

- Enterprise wells and wellbores → **SDMA / Wellbore DDMS**
- Official trajectories and logs → **Wellbore DDMS**
- Seismic volumes → **Seismic DDMS**
- CRS and unit definitions → **Reference-data services**
- Enterprise stratigraphy → **Central catalog**

```mermaid
flowchart LR
    SDMA["SDMA<br/>(Wells, Wellbores)"]
    WDDMS["Wellbore DDMS<br/>(Logs, Trajectories)"]
    SDDMS["Seismic DDMS<br/>(Volumes)"]
    REF["Reference Data<br/>(CRS, Units)"]

    RDDMS["RDDMS<br/>(Reservoir Model)"]
    CAT["OSDU Catalog<br/>(Search & Governance)"]

    SDMA -->|"reference by ID"| RDDMS
    WDDMS -->|"reference or snapshot"| RDDMS
    SDDMS -->|"reference"| RDDMS
    REF -->|"reference"| RDDMS
    RDDMS -->|"WPC summaries"| CAT
```

### Reference Patterns

| Pattern | When to use | Example |
|---------|------------|---------|
| **Reference only** | Master data that stays authoritative elsewhere | Well ID, CRS EPSG code |
| **Snapshot** | Reproducibility requires frozen state | Trajectory version used for blocked wells |
| **Derive** | Model creates new objects from external inputs | Blocked-wellbore representation, upscaled properties |
| **Copy** | Data-room or partner boundaries require it | JV export, regulatory submission |

> **Rule:** Reference first. Snapshot only when reproducibility demands it. Derive for model-specific objects. Copy only when governance requires it.

---

## Versioning Without Git

RDDMS dataspaces are mutable (WIP) or immutable (locked). There's no built-in version history like Git. Instead, use this pattern:

```mermaid
flowchart LR
    subgraph Timeline
        direction LR
        W["WIP<br/>(iterate)"] --> S1["v1 🔒<br/>pre-DG1"]
        W --> S2["v2 🔒<br/>post well-tie"]
        W --> S3["v3 🔒<br/>DG2 approved"]
    end

    subgraph Provenance
        A1["Activity: v1 created"]
        A2["Activity: v2 - incorporated new wells"]
        A3["Activity: v3 - DG2 approval"]
    end

    S1 -.- A1
    S2 -.- A2
    S3 -.- A3
```

| Mechanism | Purpose |
|-----------|---------|
| **Locked snapshots** | Immutable model states (the "versions") |
| **Activity records** | What changed, who, when, inputs/outputs |
| **Lifecycle events** | Human-readable changelog on CollaborationProject |
| **PersistedCollection** | Frozen gate evidence (what a decision was based on) |

---

## Transactions and Consistency

Reservoir model updates often involve multiple objects:

```mermaid
graph LR
    TX["Transaction"]
    TX --> O1["Grid object"]
    TX --> O2["Geometry arrays"]
    TX --> O3["Topology arrays"]
    TX --> O4["Property object"]
    TX --> O5["Property values"]
    TX --> O6["Relationships"]

    TX -->|"commit"| OK["All or nothing<br/>✓ consistent"]
```

- All objects in a transaction commit together or roll back together
- No partial model states become visible
- External transactions (caller-managed) or internal (auto-commit)
- Timeout: 300s default, with keepalive pings

---

## Access Control

| Dataspace | Owners | Viewers | Lock |
|-----------|--------|---------|------|
| Project WIP | Project contributors | Project viewers | Unlocked |
| Snapshot | Field/project owners | Project viewers | Locked |
| Model SoR | Asset owners | Enterprise viewers | Locked |
| JV/shared | JV contributors | Partner data-room | Locked |

**Rules:**
- ACL is the data-room boundary
- Legal tags validated before promotion or sharing
- Published records never more permissive than source data
- Cross-border sharing validates data countries

---

## Practical Domain Rules

### Wells & Wellbores

| RDDMS stores | RDDMS does NOT store |
|--------------|---------------------|
| References to wells/wellbores | New official well records |
| Blocked-wellbore representations | Uncontrolled copies of raw logs |
| Grid/well intersections | Official trajectories |
| Simulation connection objects | — |

### Logs

| RDDMS stores | RDDMS does NOT store |
|--------------|---------------------|
| References to source logs | Raw/governed logs (Wellbore DDMS owns) |
| Upscaled log-derived properties | Uncontrolled log copies |
| Provenance linking to source | — |

### Stratigraphy, CRS, Units

- Reference from enterprise services
- Snapshot only when reproducibility requires it
- Project-local stratigraphy = proposal, not replacement for enterprise data

### FMU & Ensembles

| RDDMS stores | Stays in results store |
|--------------|----------------------|
| Selected model objects & realizations | Raw FMU ensemble outputs |
| P10/P50/P90 promoted summaries | Full ensemble runs |
| Static model versions | — |

---

## Implementation Checklist

### Project setup

- [ ] Create `CollaborationProject` in OSDU catalog
- [ ] Create project WIP dataspace (e.g. `project-x/wip`)
- [ ] Set dataspace ACL groups (owners + viewers)
- [ ] Register legal tags
- [ ] Create initial `CollaborationProjectCollection`

### During work

- [ ] Write model objects to WIP (ETP, REST, or EPC upload)
- [ ] Reference wells/logs/CRS from authoritative sources (don't duplicate)
- [ ] Create Activity records for significant updates
- [ ] Validate: object graph integrity, arrays present, CRS correct

### At decision gate

- [ ] Clone WIP → locked snapshot
- [ ] Build manifest (`POST /manifests/build` or `autoIngest=true`)
- [ ] Verify WPC records in OSDU Search
- [ ] Create Activity (provenance for this version)
- [ ] Create `PersistedCollection` (frozen gate evidence)
- [ ] Link to `BusinessDecision` if at formal gate

### At project close

- [ ] Lock final snapshot
- [ ] Archive/retain snapshots per retention policy
- [ ] Delete abandoned WIP dataspaces
- [ ] Keep all snapshots referenced by BusinessDecision
- [ ] Record final lifecycle event

---

## Comparison: RDDMS as Full DDMS vs. Arrays-Only

| Aspect | RDDMS as proper DDMS ✓ | Arrays-only (objects in catalog) |
|--------|----------------------|-------------------------------|
| Object graph | Preserved, queryable | Split across services |
| Array meaning | Linked to context | Separated from context |
| Transactions | Atomic model updates | Distributed coordination needed |
| Reproducibility | Dataspace = complete model | Must reassemble from multiple services |
| Domain query | "What properties on this grid?" | Must query catalog + RDDMS separately |
| Application perf | Single service call | Multiple cross-service hops |
| Complexity | Higher implementation | Simpler but brittle |

---

## Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| RDDMS becomes duplicate Wellbore DDMS | Reference wells/logs, derive model objects only |
| Catalog becomes accidental model DB | Keep catalog to summaries + DDMS links |
| Stale external references | Store source version + timestamp; snapshot when needed |
| No native versioning | Locked snapshots + Activities + lifecycle events |
| Orphan arrays or objects | Transaction layer enforces reference integrity |
| ACL sprawl | Standardize naming; automate project setup/cleanup |

---

## Glossary

| Term | Meaning |
|------|---------|
| **FIRP** | Feature → Interpretation → Representation → Property (RESQML object pattern) |
| **WPC** | Work Product Component (OSDU catalog record type) |
| **DDMSDatasets** | Field on a WPC linking to the authoritative DDMS location |
| **SoR** | System of Record — locked, governed, authoritative |
| **SoE** | System of Engagement — mutable, project-scoped, collaborative |
| **EPC** | Energistics Package Convention — ZIP file containing RESQML XML objects |
| **Dataspace** | Named container in RDDMS (like a folder/project/version) |
| **Manifest** | OSDU JSON structure that registers DDMS content in the catalog |
| **autoIngest** | EPC upload option that auto-builds manifest + pushes to catalog |

---

## Further Reading

- [RddmsIntegration.md](RddmsIntegration.md) — Technical details: parser comparison, CRS mapping, M27 object compression
- [RestApi.md](/home/maap/rddms/RestApi.md) — Full REST API reference
- [RDDMS Architecture](https://community.opengroup.org/osdu/platform/domain-data-mgmt-services/reservoir/home) — Service components and deployment
