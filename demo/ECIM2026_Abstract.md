# ECIM 2026 - Presentation Abstracts

## 1. OSDU as System of Record for Subsurface Decision Gates

Subsurface decision-making follows a structured gate process (DG0–DG4) where volumetric estimates, risk assessments, and development concepts evolve between gates. Yet the underlying data remains fragmented - volumes in specialized tools, risks in spreadsheets, documents in file shares, geomodels in proprietary formats - preventing systematic cross-gate comparison, reproducibility, and AI-driven analysis.

We present a data architecture using the OSDU platform as the canonical backbone for decision-gate evidence. A single BusinessDecision record per gate serves as a rich metadata hub, linking ~25 typed artefacts: volumetric tables (raw ensemble and P10/P50/P90 aggregates), input parameter matrices, risk records with severity/probability evolution, development concepts, governance documents, and geomodel references. Shared master-data persists across gates while versioned components capture gate-specific evidence.

The architecture rests on four pillars: (1) BusinessDecision as metadata hub - typed input/output/context links with full provenance; (2) Complete data repository - the Reservoir DDMS stores geomodels via ETP protocol, with activity records capturing workflow configuration for reproducibility; (3) Gate-to-gate tracking - canonical volume schemas, risk evolution, sensitivity analysis attributing volume changes to specific parameter revisions; (4) Searchable archive - indexed records enabling what-if scenarios, automated reporting, and AI-generated insights.

We validate the approach with the public Drogon dataset (DG1→DG2, ~100 records across 14 schema kinds). The implementation transforms FMU/RMS simulation outputs into OSDU-compliant records, provides a web application with multi-gate analysis dashboards, and integrates with the Reservoir DDMS for geomodel storage. This converts ephemeral decision-gate artifacts into a persistent, queryable knowledge base - enabling audit-ready provenance, portfolio-wide performance tracking, uncertainty calibration from historical decisions, and AI-readiness for automated sensitivity reporting.

---

## 2. The OSDU Reservoir DDMS: A Standards-Based Data Service for Complex Subsurface Models

Reservoir characterization produces deeply interconnected data - structural interpretations referencing seismic horizons, grids built from multiple surfaces, properties tied to stratigraphic zones, simulation results linked to input models - all accompanied by large numerical arrays. Traditional storage approaches either flatten these relationships into disconnected files or lock them inside proprietary application databases, making cross-tool interoperability and long-term preservation difficult.

The OSDU Reservoir Domain Data Management Service (Reservoir DDMS) addresses this through a standards-only approach. Built on the Energistics Transfer Protocol (ETP 1.2) over WebSocket with binary Avro encoding, it stores subsurface objects from RESQML, WITSML, and PRODML as native data objects with full relationship graphs preserved. Unlike file-based exchange, every object is individually addressable, queryable, and traversable - a horizon interpretation can be retrieved with all its source features, target representations, and attached properties through typed graph navigation without loading an entire project.

Key capabilities include: ACID transactions ensuring geomodels are stored atomically (objects plus arrays committed together or not at all); a dedicated DataArray protocol for efficient binary streaming of grid properties, well logs, and surface meshes; dataspace isolation providing project/scenario workspaces with copy-on-write branching; and lossless round-trip fidelity - objects are retrievable exactly as submitted, critical for regulatory and legal compliance of well data.

The service operates as both System of Engagement (teams collaborate on live dataspaces with full read-write access) and System of Record (locked dataspaces projected into OSDU catalog via manifest generation for enterprise search and governance). A REST API bridges ETP's binary protocol to standard HTTP clients, exposing discovery, store, transaction, and array operations. The architecture supports real-time streaming for drilling data alongside static model storage, unifying the full subsurface lifecycle - from acquisition through interpretation to simulation - in a single, vendor-neutral, OSDU-compliant service.

---

**Keywords:** Reservoir DDMS, ETP, RESQML, WITSML, OSDU, Subsurface Data Management, Geomodel Storage, Standards Compliance
