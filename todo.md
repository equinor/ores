## Tier C - True infrastructure gaps (cannot solve with existing schemas)

### C1. Real-Time Collaboration (Webhooks/SSE)
- [ ] RDDMS webhook: push notification when ETP dataspace objects change
- [ ] ORES Server-Sent Events: live updates to open BD detail views
- [ ] Requires infrastructure: message bus or polling service + SSE endpoint
- **Deps**: B6 notification service integration (done) is the lightweight precursor
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
B3 (relationship search)     ─── Done: POST /api/search/filtered (enrichment filter)
B5 (atomic actions + audit)  ─── Done: add-alternative, update-volume, flag-risk

B1 (RDDMS graph traversal)  ─── Resolved: keys page + GraphQL already cover this
B2 (dataspace diff)          ─── Resolved: Activity input/output pattern
B4 (decision branches)       ─── Verified: Import/Copy in admin page works
B6 (change notification)     ─── Done: /notifications page + OSDU notification API

GUI integration:
  B5 Quick Actions           ─── Done: popup buttons on BD detail (add-alt, update-vol, flag-risk)
  Collaboration History      ─── Done: timeline on BD detail (3 recent inline, full in popup)
  FMU Activity               ─── Refactored: compact summary inline, full I/O grid in popup
  Notifications page         ─── Done: /notifications (test, subscriptions, polling)

C1-C2 (SSE + dashboards)    ─── Later: infrastructure (no new OSDU schemas needed)

Ref-data setup (run once):   ─── Define conventions for Keys[], MilestoneID, EventID
```
