# TODO - Ontology-Driven Improvements

## Open  Tier B (ORES/RDDMS backend additions, M27 schemas sufficient)

### B1. RDDMS Graph Traversal Endpoint
- [ ] New endpoint: given a BD SRN, walk Parameters[] → resolve ETPDataspace links → list RESQML objects in those dataspaces
- [ ] Returns unified graph: OSDU records + RESQML objects across the boundary
- [ ] ORES consumes this for the object explorer (A4) to include subsurface detail
- **Deps**: A4 benefits from this but works without it (OSDU-only graph)
- **Effort**: ~3-4 days RDDMS TypeScript endpoint + ORES integration

### B2. Dataspace Diff/Compare
- [ ] RDDMS endpoint: given two dataspaces (or two transaction snapshots), return structural diff
- [ ] Objects added/removed/modified, property changes, grid dimension changes
- [ ] ORES UI: show diff when comparing two BD alternatives that reference different dataspaces
- **Deps**: B1 (needs object listing per dataspace). A3 benefits from this
- **Effort**: ~4-5 days. RDDMS comparison logic + diff rendering

### B3. Relationship-Aware Search
- [x] Compound cell-level AND filter (`compoundFilter`)  done for RDDMS property arrays
- [ ] Extend to OSDU side: "BD where Parameters[role=Output, kind=REV].P50 > X"
- [ ] Requires post-search enrichment filtering (OSDU search can't query nested arrays)
- [ ] Server-side: fetch candidates by kind → enrich → filter → return
- **Deps**: Existing enrichment pipeline. RDDMS compound filter is the pattern to follow.
- **Effort**: ~3 days for OSDU side. RDDMS side done.

### B4. Decision Branches via Dataspace Clone
- [ ] ORES UI: "Create Alternative" button on BD → clones linked RDDMS dataspace → creates new BD with cloned dataspace reference
- [ ] Names branch: "Alternative A - Water Injection" / "Alternative B - Gas Injection"
- [ ] Uses existing RDDMS Clone Dataspace API
- **Deps**: RDDMS clone endpoint exists. Needs ORES orchestration
- **Effort**: ~2-3 days. Orchestration + UI

### B5. Atomic Collaboration Actions (using existing audit fields)
- [ ] ORES endpoints: POST `/bd/{id}/add-alternative`, `/bd/{id}/update-volume`, `/bd/{id}/flag-risk`
- [ ] Each action: updates BD Parameters[] or linked records + appends `LifecycleEvents[]` entry on CP
- [ ] Also creates Activity record (with ActivityTemplate="CollaborationAction") for full provenance
- [ ] Use `ext.equinor.Alternatives[]` for alternative management (already structured)
- [ ] Feed into A6 (activity feed) automatically via LifecycleEvents[] + Activity queries
- **Deps**: A6 design. Existing addgate logic for record creation
- **Effort**: ~4-5 days. Multiple endpoints + dual audit (LifecycleEvents + Activity)

### B6. RDDMS Change Notification (Polling)
- [ ] RDDMS periodic check: compare dataspace object list/timestamps vs last known state
- [ ] ORES: on BD detail view, show "2 objects modified since last gate freeze"
- [ ] Lightweight - no webhook infrastructure needed, just timestamp comparison
- **Deps**: B1 (object listing with timestamps)
- **Effort**: ~2 days atop B1

---

## Tier C - True infrastructure gaps (cannot solve with existing schemas)

### C1. Real-Time Collaboration (Webhooks/SSE)
- [ ] RDDMS webhook: push notification when ETP dataspace objects change
- [ ] ORES Server-Sent Events: live updates to open BD detail views
- [ ] Requires infrastructure: message bus or polling service + SSE endpoint
- **Deps**: B6 is the lightweight precursor
- **Effort**: ~2 weeks (infrastructure + RDDMS webhook + ORES SSE + reconnection logic)

### C2. User-Configurable Dashboard Builder
- [ ] Domain users compose custom BD views: pick which Parameters[] to surface, KPI cards, graph layouts
- [ ] Requires a layout persistence model + dynamic rendering engine
- [ ] Consider: saved views as JSON in user preferences or as OSDU Document WPC
- **Deps**: A1-A6 provide the building blocks; this makes them composable
- **Effort**: ~2 weeks (layout engine + persistence + UI)

### ~~C3-C5. Previously proposed new schemas - NOW UNNECESSARY~~

**Eliminated by reusing existing M27 fields:**

| Was | Replaced By |
|---|---|
| ~~`DecisionAlternative` WPC~~ | `ext.equinor.Alternatives[]` already on BD + B4 dataspace branching |
| ~~`RelationshipType` ref-data kind~~ | `Parameters[].Keys[ParameterKey="relationship-kind"]` + conventions |
| ~~`GateChecklist` schema extension~~ | `ActivityStates[]` with custom MilestoneID/ActivityStatusID ref-data |
| ~~`ChangeEvent` WPC~~ | `CollaborationProject.LifecycleEvents[]` + Activity records as audit trail |

---

## Implementation Order

```
B4 (decision branches)       ─┐
B3 (relationship search)     ─┤── Next: backend enrichment
B5 (atomic actions + audit)  ─┘   (uses LifecycleEvents[] + Activity)

B1 (RDDMS graph traversal)  ─┐
B2 (dataspace diff)          ─┤── Then: cross-boundary integration
B6 (change notification)     ─┘

C1-C2 (SSE + dashboards)    ─── Later: infrastructure (no new OSDU schemas needed)

Ref-data setup (run once):   ─── Define conventions for Keys[], MilestoneID, EventID
```
