
# Strat Column Handler

This guide documents the **Strat Column CLI ** that round‑trips stratigraphy between **SMDA .xlsx**, **OW JSON**, **RESQML 2.0.1 JSON graph**, and **OSDU WKS** using a **generic, rank‑agnostic model**. It merges strategy, accepted **input formats (with snippets)**, **output formats**, **OW→OSDU mapping**, **CLI usage**, **validation rules**, and a **pre‑run checklist**.

---

## 1) Standards & Model Alignment (authoritative references)

- **OSDU Stratigraphy worked example** demonstrates a column composed of an ordered list of **ranks**, where **chrono ranks** list **reference‑data SRNs** (`ChronoStratigraphySet`) and **litho ranks** list **unit interpretations** (`StratigraphicUnitInterpretationSet`). This CLI mirrors that shape.  
  Ref: OSDU Worked Example (Stratigraphy) — `.../Examples/WorkedExamples/Reservoir Data/Stratigraphy/README.md`
  https://community.opengroup.org/osdu/data/data-definitions/-/blob/v0.14.0/Examples/WorkedExamples/Reservoir%20Data/Stratigraphy/README.md

- **Chrono rank example (System)** illustrates `ChronoStratigraphySet` with **SRNs** (replace the placeholder `partition-id` with your tenant partition, e.g., `data`).  
  Ref: ColumnRankInterpretationSystem.json (Worked Examples)
  https://github.com/jonslo/osdu-data-data-definitions/blob/master/Examples/WorkedExamples/Reservoir%20Data/Stratigraphy/ChronoStratigraphySets/ColumnRankInterpretationSystem.json

- **ChronoStratigraphy reference values** define the time‑scale hierarchy used by Chrono ranks. The CLI resolves **Name/Alias/Code → SRN** from your **1.0.0** (or **1.1.0**) catalog.  
  Ref: ChronoStratigraphy.1.0.0 E‑R  
  https://github.com/jonslo/osdu-data-data-definitions/blob/master/E-R/reference-data/ChronoStratigraphy.1.0.0.md

- **RESQML 2.0.1** relationship graph: `StratigraphicColumn` → `StratigraphicColumnRankInterpretation` → `StratigraphicUnitInterpretation`. The CLI outputs/imports a JSON graph following this structure.  
  Ref: RESQML 2.0.1 Overview  
  https://docs.energistics.org/RESQML/RESQML_TOPICS/RESQML-000-000-titlepage.html

---

## 2) Conceptual Data Model (in‑memory)

- `StratColumn(name, ranks[])`
- `StratRank(name, kind='litho'|'chrono', level:int, ordering='OlderToYounger', units[], chrono_names[])`
- `StratUnit(name, uuid, level, top_age_ma, base_age_ma, parent_name, color_html, vendor={...})`

Notes:
- **Arbitrary depth**: any number of ranks.
- **Mixed ranks**: chrono & litho in the same column (e.g., Systems/Series + Groups/Formations).
- **Ordering**: older→younger via `(top_age, base_age, name)`.
- **Vendor metadata**: all unrecognized OW/SMDA keys remain in `vendor` and round‑trip to `data.VendorMetadata.OW` (OSDU) and `extraMetadata.ow` (RESQML).

---

## 3) Input Formats — Specifications & Snippets

### 3.1 SMDA (.xlsx) — **ApiStratUnit** sheet

**Required/typical columns (case‑insensitive):**
- **Column context** (per row; used for level/rank inference):
  - `strat_column_type` *(string)*: contains “chronostrat” for chrono ranks; otherwise litho.
  - `strat_column_identifier` *(string)*: column title; used to set `StratColumn.name` (first non‑empty).
- **Unit fields** (per row, for litho ranks):
  - `identifier` *(string)*: unit display name.
  - `uuid` *(string, optional)*: stable UUID; if omitted, one is generated.
  - `strat_unit_level` *(int)*: groups rows into ranks (e.g., 1=Group, 2=Formation).
  - `strat_unit_parent` *(string, optional)*: parent name; preserved.
  - `top_age` *(float, Ma)* and `base_age` *(float, Ma)*: used for ordering; preserved.
  - `color_html` *(string, #RRGGBB)*: preserved.

**Heuristic & behavior:**
- All rows with the same `strat_unit_level` become one **rank**.
- If any row in that level has `strat_column_type` containing “chronostrat”, the rank is **chrono** and will list **Chrono SRNs** (resolved from catalogs); otherwise it’s **litho** and will list **Unit interpretations**.

> Tip: Additional columns are copied into `vendor` and round‑trip intact.

---

### 3.2 OW JSON (compat) — **minimal shape**

```json
{
  "StratColumn": {
    "Name": "JOHAN SVERDRUP 2015",
    "Uuid": "ad215071-c4f1-2e4b-e053-c918a4881b5c",
    "Type": "lithostratigraphy" // or "chronostratigraphy"
  },
  "Units": [
    {
      "identifier": "CROMER KNOLL GP.",
      "uuid": "d0d2fc5d-b128-41b2-897d-247627056ff2",
      "strat_unit_type": "group",
      "strat_unit_level": 1,
      "top_age": 95,
      "base_age": 139,
      "color_html": "#00daff",
      "source": "SCE"
    },
    {
      "identifier": "Roedby Fm.",
      "uuid": "a8737968-86e7-495e-82c8-84049c2e80e7",
      "strat_unit_type": "formation",
      "strat_unit_level": 2,
      "strat_unit_parent": "CROMER KNOLL GP.",
      "top_age": 95,
      "base_age": 110,
      "color_html": "#006dff"
    }
    // ...more units...
  ]
}
```

**Notes:**
- `StratColumn.Type` controls chrono vs litho behavior (as in SMDA heuristic).
- Unrecognized keys are preserved under `VendorMetadata.OW` (OSDU) and `extraMetadata.ow` (RESQML).

---

### 3.3 ChronoStratigraphy reference‑data JSON — **catalog bundle**

Provide your deployed catalog exported as a **bundle**. The CLI builds a **name/alias/code → SRN** index from `records[].data.{Name, AliasNames, Code}` and uses `records[].id` **verbatim** as the SRN.

```json
{
  "records": [
    {
      "id": "data:reference-data--ChronoStratigraphy:System:Jurassic:",
      "kind": "osdu:wks:reference-data--ChronoStratigraphy:1.0.0",
      "data": { "Name": "Jurassic", "AliasNames": ["J"], "Code": "J" }
    },
    {
      "id": "data:reference-data--ChronoStratigraphy:Series:Oxfordian:",
      "kind": "osdu:wks:reference-data--ChronoStratigraphy:1.0.0",
      "data": { "Name": "Oxfordian" }
    }
  ]
}
```

> Works with **1.0.0** (per your link) and **1.1.0** catalogs.  
> Ref: ChronoStratigraphy 1.0.0 E‑R — `.../E-R/reference-data/ChronoStratigraphy.1.0.0.md`

---

### 3.4 LithoStratigraphy reference‑data JSON — **optional enrichment**

If you maintain LithoStrat catalogs, you can attach those SRNs into vendor metadata for units.

```json
{
  "records": [
    {
      "id": "data:reference-data--LithoStratigraphy:Roedby_Fm.:",
      "kind": "osdu:wks:reference-data--LithoStratigraphy:1.0.0",
      "data": { "Name": "Roedby Fm." }
    }
  ]
}
```

---

### 3.5 OSDU input accepted by `osdu2resqml`

- **Bundle** (`{ "records": [ ... ] }`) — recommended.
- **Single WPC record** — a single Column WPC is accepted.
- **Bare `data`** — minimal Column `data` object (advanced).

---

## 4) Output Formats — Snippets

### 4.1 OSDU **bundle** (litho case; abbreviated)

```json
{
  "records": [
    {
      "id": "data:work-product-component--StratigraphicUnitInterpretation:Roedby_Fm.:",
      "kind": "osdu:wks:work-product-component--StratigraphicUnitInterpretation:1.3.0",
      "data": {
        "Name": "Roedby Fm.",
        "VendorMetadata": {
          "OW": { "top_age": 95, "base_age": 110, "strat_unit_parent": "CROMER KNOLL GP.", "color_html": "#006dff" }
        },
        "OW_Mapped": {
          // present if you use --ow-map to copy fields to OSDU paths;
          // by default, best-guess mapping goes under data.VendorMetadata.OW_Mapped.*
        }
      }
    },
    {
      "id": "data:work-product-component--StratigraphicColumnRankInterpretation:Formation:",
      "kind": "osdu:wks:work-product-component--StratigraphicColumnRankInterpretation:1.3.0",
      "data": {
        "Name": "Formation",
        "OrderingCriteria": "OlderToYounger",
        "StratigraphicUnitInterpretationSet": [
          "data:work-product-component--StratigraphicUnitInterpretation:Roedby_Fm:"
          // ... more units ...
        ],
        "VendorMetadata": { "OW": { "level": 2, "strat_column_type": "lithostratigraphy" } }
      }
    },
    {
      "id": "data:work-product-component--StratigraphicColumn:JOHAN_SVERDRUP_2015:",
      "kind": "osdu:wks:work-product-component--StratigraphicColumn:1.2.0",
      "data": {
        "Name": "JOHAN SVERDRUP 2015",
        "StratigraphicColumnRankInterpretationSet": [
          "data:work-product-component--StratigraphicColumnRankInterpretation:Group:",
          "data:work-product-component--StratigraphicColumnRankInterpretation:Formation:"
        ],
        "VendorMetadata": { "OW": { "Uuid": "ad215071-c4f1-2e4b-e053-c918a4881b5c" } }
      }
    }
  ]
}
```

> Kinds and linking follow OSDU schema/E‑R guidance (Column 1.2.0; Rank 1.3.0).  
> Ref: Worked Examples Stratigraphy README; RankInterpretation schema resources.

---

### 4.2 RESQML **JSON graph** (litho case; abbreviated)

```json
[
  {
    "resqmlType": "resqml20:StratigraphicUnitInterpretation",
    "uuid": "a8737968-...",
    "title": "Roedby Fm.",
    "topAgeMa": 95,
    "baseAgeMa": 110,
    "extraMetadata": { "ow": { "...": "..." } }
  },
  {
    "resqmlType": "resqml20:StratigraphicColumnRankInterpretation",
    "uuid": "Formation",
    "title": "Formation",
    "orderingCriteria": "OlderToYounger",
    "unitInterpretationRefs": [
      { "uuid": "a8737968-...", "contentType": "resqml20:StratigraphicUnitInterpretation" }
    ]
  },
  {
    "resqmlType": "resqml20:StratigraphicColumn",
    "uuid": "JOHAN_SVERDRUP_2015",
    "title": "JOHAN SVERDRUP 2015",
    "rankInterpretationRefs": [
      { "uuid": "Group", "contentType": "resqml20:StratigraphicColumnRankInterpretation" },
      { "uuid": "Formation", "contentType": "resqml20:StratigraphicColumnRankInterpretation" }
    ]
  }
]
```

---

### 4.3 RESQML **JSON graph** (chrono case; abbreviated)

```json
[
  {
    "resqmlType": "resqml20:StratigraphicColumnRankInterpretation",
    "uuid": "System",
    "title": "System",
    "orderingCriteria": "OlderToYounger",
    "chronoStratRefs": [
      { "srn": "data:reference-data--ChronoStratigraphy:System:Jurassic:" },
      { "srn": "data:reference-data--ChronoStratigraphy:System:Cretaceous:" }
    ]
  }
]
```

---

## 5) OW→OSDU Mapping

### 5.1 Built‑in best‑guess mapping (safe vendor paths)

By default, selected OW/SMDA keys are copied into **vendor‑scoped** paths (`data.VendorMetadata.OW_Mapped.*`) so nothing collides with standardized WKS semantics:

```json
{
  "source": "data.VendorMetadata.OW_Mapped.Source",
  "update_date": "data.VendorMetadata.OW_Mapped.UpdateDate",
  "update_user": "data.VendorMetadata.OW_Mapped.UpdateUser",
  "insert_date": "data.VendorMetadata.OW_Mapped.InsertDate",
  "insert_user": "data.VendorMetadata.OW_Mapped.InsertUser",
  "strat_unit_type": "data.VendorMetadata.OW_Mapped.UnitType",
  "color_html": "data.VendorMetadata.OW_Mapped.ColorHtml",
  "strat_unit_parent": "data.VendorMetadata.OW_Mapped.ParentName",
  "top_age": "data.VendorMetadata.OW_Mapped.TopAgeMa",
  "base_age": "data.VendorMetadata.OW_Mapped.BaseAgeMa"
}
```

### 5.2 Custom mapping (`--ow-map`)

Provide a JSON dict to map **source OW keys** → **target dotted OSDU field paths** (relative to the WPC record root):

```json
{
  "strat_unit_type": "data.StratigraphicRoleTypeID",
  "source": "data.Source"
}
```

> Only target standardized OSDU fields when you control the **SRN values** and semantics. Otherwise, stay within `VendorMetadata.OW_Mapped.*`.

---

## 6) CLI Usage

```bash
# A) SMDA → RESQML
python strat_column_cli_v2.py smda2resqml \
  --xlsx smda-api_strat-units.xlsx --sheet ApiStratUnit \
  -o strat.resqml.json \
  --chrono-refdata chrono_catalog.json

# B) SMDA → OSDU (default partition = 'data')
python strat_column_cli_v2.py smda2osdu \
  --xlsx smda-api_strat-units.xlsx --sheet ApiStratUnit \
  -o strat.osdu.json --partition data \
  --chrono-refdata chrono_catalog.json \
  --ow-map ow_to_osdu_map.json   # optional override

# C) Round-trip A: RESQML → OSDU → RESQML
python strat_column_cli_v2.py resqml2osdu \
  --resqml-json strat.resqml.json \
  -o a.osdu.json --partition data

python strat_column_cli_v2.py osdu2resqml \
  --manifest a.osdu.json \
  -o a.rt.resqml.json

# D) Round-trip B: OSDU → RESQML → OSDU
python strat_column_cli_v2.py osdu2resqml \
  --manifest strat.osdu.json \
  -o b.resqml.json

python strat_column_cli_v2.py resqml2osdu \
  --resqml-json b.resqml.json \
  -o b.rt.osdu.json --partition data
```

---

## 7) Strategy & Decision Logic

1) **Shape parity (OSDU ↔ RESQML)**  
   Column holds **rank references**; ranks hold **unit references** (litho) **or** **Chrono SRNs** (chrono). Matches OSDU worked examples and E‑R.  
   Ref: Worked Example Stratigraphy README.

2) **Chrono vs. Litho decision**  
   If `strat_column_type` (or `StratColumn.Type`) contains “chronostrat”, rank becomes **chrono** and is populated from **ChronoStrat SRNs** (catalog). Otherwise, it becomes **litho** listing **units**.  
   Ref: Worked Examples; ChronoStratigraphy E‑R.

3) **Reference‑data policy**  
   No SRN synthesis. Chrono names are resolved from your **reference bundle**; SRNs pass through unchanged.

4) **Partition & IDs**  
   Default partition is `data` (override with `--partition` or `OSDU_PARTITION`).  
   IDs:  
   ```
   {partition}:work-product-component--<Entity>:{SanitizedNameOrUUID}:
   ```

---

## 8) Validation & Invariants

- **Rank XOR rule**: each rank has **either** `ChronoStratigraphySet` **or** `StratigraphicUnitInterpretationSet`, never both (enforced by construction).  
- **Chrono resolution**: unresolved chrono names **fail fast** unless SRNs are present or a reference catalog is provided.  
- **Ordering**: ranks/units sorted older→younger using `(top_age, base_age, name)` with sensible defaults for missing ages.  
- **Round‑trip safety**: all source keys preserved under vendor metadata (OSDU: `VendorMetadata.OW`; RESQML: `extraMetadata.ow`).

---

## 9) Error Messages (typical)

- `Chrono name '…' requires --chrono-refdata to resolve to SRN`  
  → Provide a ChronoStrat reference bundle containing that entry.

- `OpenWorks JSON must contain 'StratColumn' and 'Units'`  
  → Input shape mismatch when using OW JSON reader.

- `Unsupported OSDU payload shape`  
  → For `osdu2resqml`, the input must be a bundle (`records`), a single WPC, or bare `data` for a Column.

- `No data rows in SMDA sheet`  
  → Empty or incorrect SMDA input.

---

## 10) Pre‑Run Checklist (quick verification)

**General**
- [ ] Choose the correct **partition** (defaults to `data`); override with `--partition` or `OSDU_PARTITION`.
- [ ] Confirm **rank policy**: which levels are **chrono** vs **litho** (based on `strat_column_type` or column metadata).
- [ ] For chrono ranks, have at least one **ChronoStratigraphy** catalog bundle (1.0.0 or 1.1.0) ready.

**SMDA (.xlsx) input**
- [ ] Sheet name is **`ApiStratUnit`** (or provide `--sheet`).
- [ ] Columns exist with consistent spelling (case‑insensitive acceptable):  
      `identifier`, `uuid` (optional), `strat_unit_level`, `strat_unit_parent` (optional),  
      `top_age`, `base_age`, `color_html` (optional), `strat_column_type`, `strat_column_identifier`.
- [ ] `strat_unit_level` values group rows correctly into ranks (e.g., 1=Group, 2=Formation).
- [ ] Ages are in **Ma** and make sense for ordering (top ≤ base by convention you use; tool sorts older→younger).

**OW JSON input**
- [ ] Root object contains **`StratColumn`** and **`Units`** arrays.
- [ ] `StratColumn.Name` present; `StratColumn.Type` set to `"chronostratigraphy"` only if you want chrono ranks.
- [ ] Each unit has `identifier` (and preferably `uuid`).

**ChronoStrat catalog(s)**
- [ ] Bundle has **`records[]`** with **`id`** SRNs and **`data.{Name, AliasNames, Code}`** for lookup.
- [ ] Names/aliases/codes in your ranks match the catalog entries; otherwise add aliases.

**Mapping (optional)**
- [ ] If mapping OW fields into standardized OSDU fields, provide **`--ow-map`** JSON and ensure values are valid (e.g., SRNs for ID fields).
- [ ] Otherwise rely on safe defaults to **`data.VendorMetadata.OW_Mapped.*`**.

**Round‑trip expectations**
- [ ] Object **counts** (units, ranks, columns) should be preserved.
- [ ] **Membership**: Rank → Unit lists and Column → Rank lists should remain stable across conversions.

---

## 11) Roadmap

- `--strict` mode (fail on empty ranks; age consistency checks).
- Schema validation hooks (offline JSON Schema; platform Schema Service).
- Rank label inference (semantic names like Group/Formation/Member with overrides).
- Optional LithoStrat enrichment: attach LithoStrat SRNs in vendor metadata when catalogs are available.
