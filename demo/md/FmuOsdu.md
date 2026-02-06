<<<<<<< HEAD

## **OSDU Support for FMU Data Handling – Simulation Grids**

### **OSDU Reservoir DMS ↔ FMU/Eclipse**

***

### **1. Purpose**

Enable round-trip fidelity between Eclipse/OPM decks and OSDU Reservoir DMS using:

*   `resqpy` for lossless, in-memory RESQML IJK grid and property handling.
*   `pyetp` for efficient, file-less data transfer.

Metadata is preserved end-to-end to ensure traceability and reproducibility.

***

### **2. Ground Rules**

*   **One identity per artifact**: Each grid, property, map, and deck has a stable `UUID/SRN` and `version`.
*   **Lossless provenance**: Every output carries ancestry back to the exact input WPCs and FMU run.
*   **CRS & units are first-class**: CRS definition, axis order, rotation, and UOM travel with the data.
*   **Round-trip fidelity**: Data exported from Eclipse can be fully recovered from OSDU with identical identity and metadata.

***

### **3. Canonical Data Model**

#### **Dataspace**

Partition boundary for ACL and legal tags.

#### **Work Product (WP)**

Reservoir model context (e.g., asset/model/vintage/ensemble).

#### **Work Product Component (WPC)**

Atomic datasets (3D grid, 2D grid, property, table, deck, etc.).

#### **Collection**

Groups WPs/WPCs by case, ensemble, or realization.

***

#### **Grid (IJK, Corner-Point)**

*   **Identity**: `grid_uuid`, `osdu_srn`, `version`
*   **Geometry**: `ni, nj, nk`, `k_direction`, `handedness`
*   **CRS**: Type (LocalDepth3d/Global), origin, rotation, axis order, units (XY/Z)
*   **Governance**: `legalTags`, `acl`, `data.ancestry.inputs`, timestamps
*   FMU-generated metadata: fmu-dataio

#### **Property (Cell-Sized)**

*   **Identity**: `property_uuid`, `osdu_srn`, `version`
*   **Mapping**: Eclipse keyword (PORO, PERMX, etc.), indexable element (cells), UOM, discrete/continuous
*   **Ties**: `supported_by_uuid` (grid UUID), property set/title
*   Governance & ancestry as above
*   FMU-generated metadata

#### **2D Grid / Map**

*   Identity + grid reference (surface grid or parent 3D grid + layer/slice), units, CRS
*   FMU-generated metadata

#### **Table (CSV/Parquet or RESQML Table)**

*   Identity + schema (columns & UOM), run scope (case/realization/time)
*   FMU-generated metadata

#### **Deck Artifact (Eclipse/OPM)**

*   **Identity**: `deck_id` (stable identifier for produced deck bundle)
*   **Components**: Which files exist (`GRID.grdecl`, `PORO.grdecl`, `.DATA/.EGRID`)
*   **Binding**: `grid_uuid` + list of `property_uuid`s
*   **Manifest**: See §4
*   FMU-generated metadata

***

### **4. Deck Manifest**

A small sidecar (JSON/YAML) accompanying every deck export and OSDU write-back:

*   **Identity**: `deck_id`, `case`, `realization`
*   **Grid**: `grid_uuid`, `osdu_srn`, `dims`, `crs`
*   **Properties\[]**: `property_uuid`, `title`, `ecl_keyword`, `uom`, `discrete`
*   **Files**: List of produced artifacts (paths/names)
*   **Ancestry Inputs**: `[<wpc-id-grid>, <wpc-id-poro>, …]`
*   **Provenance**: Timestamp, tool version, conversion notes

> Stored both on disk and as metadata/attachment on the OSDU WPC.\
> Enables Eclipse → OSDU → Eclipse identity continuity.

***

### **5. Flow & Functionality (Metadata Emphasized)**

*   **Discovery**: Only attach properties linked to the chosen grid (`supported_by_uuid`).
*   **Conversion**: `resqpy` writes GRDECL using grid’s CRS/UOM; manifest records included items.
*   **FMU Run**: Consumes deck as-is; manifest ties run back to inputs.
*   **Write-back**: Outputs become WPCs with ancestry to manifest inputs, linked into correct Collection.
*   **Round-trip**: Re-fetching Deck Artifact WPC + manifest allows deck reconstruction.

***

### **6. Round-Trip Identity Rules (Eclipse ⇄ OSDU)**

1.  **Grid Lock**
    *   Deck’s grid always referenced by `grid_uuid`.
    *   Re-publishing increments `deck_id`; `grid_uuid` remains unless topology changes.

2.  **Property Lock**
    *   Each property retains original `property_uuid`, Eclipse keyword, and UOM.
    *   Renames in Eclipse don’t overwrite OSDU identity.

3.  **CRS/UOM Lock**
    *   Manifest must include CRS type, origin/rotation, axis order, and UOM.
    *   Mismatches trigger validation warnings.

4.  **Ancestry Chain**
    *   All outputs must set `data.ancestry.inputs` to exact input WPC IDs.
    *   Collections capture ensemble structure; each realization adds its Deck Artifact WPC.

***

### **7. Minimal Responsibilities per Component**

*   **pyetp**: Discover WPCs (grid + properties), stream arrays, respect dataspace/ACL.
*   **resqpy**: Build in-memory model, convert to GRDECL, emit Deck Manifest.
*   **OSDU**: Persist WPCs with `legalTags`, `acl`, `version`, `ancestry`, and Collections.
*   **FMU**: Consume decks as-is; echo `deck_id` and realization in run metadata.

***

### **8. Lightweight Acceptance**

*   **Identity**: `grid_uuid` in manifest matches WPC; all `property_uuid`s present and correct.
*   **CRS/UOM**: Manifest CRS fields complete; property UOMs consistent.
*   **Ancestry**: Output WPCs list all inputs; Collection structure matches ensemble layout.
*   **Round-trip**: Deck Artifact WPC + manifest sufficient to reconstruct runnable deck.

***

### **9. Quick Decisions to Lock Before Build**

1.  **Manifest Format & Location**: JSON preferred; stored as disk sidecar and attached to Deck Artifact WPC.
2.  **Property Set & UOM**: Canonical list for phase-1: PORO, PERMX/Y/Z, NTG, SATNUM, FACIES, ACTNUM.
3.  **Collection Granularity**: One Collection per **case** with **realization facet**, or one per **realization**.

***

## Flow diagram 

``` mermaid
flowchart LR
  OSDU[OSDU Reservoir DMS]
  RMS[RMS]
  RESQPY[resqpy/etp handler]
  ECL[Eclipse/OPM]
  COLL[Ensemble as Collections]
  SUMO[Sumo / Clients]
 
  OSDU -- ETP read 2D grid maps --> RMS

  OSDU -- ETP read grid properties deck --> RESQPY
  RESQPY -- build deck --> ECL

  ECL -- ETP write 2D maps 3D properties tables --> OSDU
  OSDU -- organize and relate --> COLL

  OSDU -- ETP read results maps properties tables --> RMS

  OSDU -- query maps results tables --> SUMO

  RMS -- store maps results tables --> OSDU
```
=======
***

## **OSDU Support for FMU Data Handling – System of Record**

***

### **1. Purpose**

* Support for OSDU storage and query as System of Record. SSDL alternative. Perspectively SoE workflow support.
* Enable round-trip fidelity between FMU Eclipse/OPM decks and OSDU Reservoir DMS facilitating:
   * Lossless, in-memory RESQML IJK grid and property handling (`resqpy`)
   * Efficient, file-less data transfer  (`pyetp`)
   * Metadata preservation end-to-end to ensure traceability and reproducibility. Option complete Activity use.
   * Bonus: Nexus, Intersect support via RESQML ETP API

***

### **2. Ground Rules**

*   **No breaking changes to FMU** workflow design and functionality, governance, Ert and other component roles: focus is on data handling, storage, metadata support, query
*   **One identity per artifact**: Each grid, property, map, and deck has a stable `UUID/SRN` and `version`.
*   **Lossless provenance**: Every output carries ancestry back to the exact input WPCs and FMU run.
*   **CRS & units are first-class**: CRS definition, axis order, rotation, and UOM travel with the data.
*   **Round-trip fidelity**: Data exported from Eclipse can be fully recovered from OSDU with identical identity and metadata.

***

### **3. Canonical Data Model**

* **Dataspace**: Partition boundary for ACL and legal tags. Analogous to ensemble unix file structure. 
* **Work Product (WP)**: Reservoir model context (e.g., asset/model/vintage/ensemble).
* **Work Product Component (WPC)**: Atomic datasets (3D grid, 2D grid, property, table, deck, etc.).
* **Collection**: Groups WPs/WPCs by case, ensemble, or realization. Collection Granularity: One per **case** with **realization facet**. 

***

#### **Grid (IJK, Corner-Point)**

*   **Identity**: `grid_uuid`, `osdu_srn`, `version`
*   **Geometry**: `ni, nj, nk`, `k_direction`, `handedness`
*   **CRS**: Type (LocalDepth3d/Global), origin, rotation, axis order, units (XY/Z)
*   **Governance**: `legalTags`, `acl`, `data.ancestry.inputs`, timestamps
*   FMU-generated metadata: fmu-dataio

#### **Property (Cell-Sized)**

*   **Identity**: `property_uuid`, `osdu_srn`, `version`
*   **Mapping**: Eclipse keyword (PORO, PERMX, etc.), indexable element (cells), UOM, discrete/continuous
*   **Ties**: `supported_by_uuid` (grid UUID), property set/title
*   Governance & ancestry as above
*   FMU-generated metadata

#### **2D Grid / Map**

*   Identity + grid reference (surface grid or parent 3D grid + layer/slice), units, CRS
*   FMU-generated metadata 

#### **Table (CSV/Parquet or RESQML Table)**

*   Identity + schema (columns & UOM), run scope (case/realization/time)
*   FMU-generated metadata

#### **Deck Artifacts (Eclipse/OPM)**

*   **Identity**: `deck_id` (stable identifier for produced deck bundle)
*   **Components**: Which files exist (`GRID.grdecl`, `PORO.grdecl`, `.DATA/.EGRID`)
*   **Binding**: `grid_uuid` + list of `property_uuid`s
*   **Manifest**: json preferred but can use fmu-dataio yaml handler; stored as disk sidecar and attached to Deck WPC, Dataspace.
*   FMU-generated metadata

***

### **4. Deck Manifest**

A small sidecar (JSON/YAML) accompanying every deck export and OSDU write-back:

*   **Identity**: `deck_id`, `case`, `realization`
*   **Grid**: `grid_uuid`, `osdu_srn`, `dims`, `crs`
*   **Properties\[]**: `property_uuid`, `title`, `ecl_keyword`, `uom`, `discrete`
*   **Files**: List of produced artifacts (paths/names)
*   **Ancestry Inputs**: `[<wpc-id-grid>, <wpc-id-poro>, …]`
*   **Provenance**: Timestamp, tool version, conversion notes

> Stored both on disk and as metadata/attachment on the OSDU WPC.\
> Enables Eclipse → OSDU → Eclipse identity continuity.

***

### **5. Flow & Functionality (Metadata Emphasized)**

*   **Discovery**: Only attach properties linked to the chosen grid (`supported_by_uuid`).
*   **Conversion**: `resqpy` writes GRDECL/EGRID/ROFF using grid’s CRS/UOM; manifest records included items. Evaluate use of xtgeo/resdata for conversion support/parsing/validation. Maintain FMU-related metadata schema (prefer json, support yaml).
*   *   **FMU Run**: Consumes deck as-is; metadata manifest ties run back to inputs.
*   **Write-back**: Outputs become WPCs with ancestry to manifest inputs, linked into correct Collection.
*   **Round-trip**: Re-fetching Deck Artifact WPC + manifest allows deck reconstruction.

***

### **6. Round-Trip Identity Rules (Eclipse ⇄ OSDU)**

1.  **Grid Lock**
    *   Deck’s grid always referenced by `grid_uuid`.
    *   Re-publishing increments `deck_id`; `grid_uuid` remains unless topology changes.

2.  **Property Lock**
    *   Each property retains original `property_uuid`, Eclipse keyword, and UOM.
    *   Renames in Eclipse don’t overwrite OSDU identity.

3.  **CRS/UOM Lock**
    *   Manifest must include CRS type, origin/rotation, axis order, and UOM.
    *   Mismatches trigger validation warnings.

4.  **Ancestry Chain**
    *   All outputs must set `data.ancestry.inputs` to exact input WPC IDs.
    *   Collections capture ensemble structure; each realization adds its Deck Artifact WPC.

***

### **7. Minimal Responsibilities per Component**

*   **pyetp**: Discover WPCs (grid + properties), stream arrays, respect dataspace/ACL.
*   **resqpy**: Build in-memory model, convert to GRDECL/EGRID, emit Deck Manifest.
*   **xtgeo (resdata)**: support ROFF/GRDECL/EGRID conversion/validation
*   **OSDU**: Persist WPCs with `legalTags`, `acl`, `version`, `ancestry`, and Collections.
*   **FMU**: Consume decks as-is; echo `deck_id` and realization in run metadata.

***

### **8. Lightweight Acceptance**

*   **Identity**: `grid_uuid` in manifest matches WPC; all `property_uuid`s present and correct.
*   **CRS/UOM**: Manifest CRS fields complete; property UOMs consistent.
*   **Ancestry**: Output WPCs list all inputs; Collection structure matches ensemble layout.
*   **Round-trip**: Deck Artifact WPC + manifest sufficient to reconstruct runnable deck.

***

## Data flow diagram - SoR case

``` mermaid
flowchart LR
  OSDU[OSDU Reservoir DMS]
  RMS[RMS]
  RESQPY[resqpy/etp handler]
  ECL[Eclipse/OPM]
  COLL[Ensemble as Collections]
  FMU[FMU/Sumo]
  CLIENTS[Clients/ResInsight/Web ...]

  OSDU -- input maps wells ... --> RMS
  OSDU -- grid properties deck --> RESQPY
  RESQPY -- build deck --> ECL
  RESQPY -- results properties tables --> OSDU
  ECL -- properties tables ... --> RESQPY
  OSDU -- organize and relate --> COLL
  OSDU -- query maps results tables --> CLIENTS
  FMU -- filtered results with known quality --> OSDU
  RMS -- SoR models maps ... --> OSDU
```



























>>>>>>> f7b6fd96c08154e7c50a31613d689d33675448c2
