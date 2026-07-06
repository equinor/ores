#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_collection_exploration.py – Generate PersistedCollections for the
Omega Sør exploration well decision.

Produces:
  - Geoscience PersistedCollection (seismic horizons, well trajectory,
    prospect maps, play assessment – RDDMS objects)
  - Main Exploration PersistedCollection (all evidence combined)

Uses the SAME CollaborationProject as the WPC development decision,
maintaining the link between exploration → development lifecycle.

Reads:
  manifest_risk_exploration.json     - Risk IDs
  manifest_drilling_exploration.json - Drilling WPC IDs
  ../manifest_rddms_omegas.json      - EPC-derived RDDMS records (if available)

Output: manifest_collection_exploration.json

Usage:
  python demo/omegas/exploration/gen_collection_exploration.py
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

from demo.eqn.omegas.exploration._shared_expl import (
    SCRIPT_DIR, DEFAULT_ACL, DEFAULT_LEGAL, ID_PREFIX, DATASPACE,
    SPATIAL_AREA_WGS84, PROJECT_CRS_ID,
    FIELD_NAME, DISCOVERY_NAME, LICENCE, BLOCK, OPERATOR,
    CP_ID, RESERVOIR_ID, SEG_TARBERT_ID, SEG_RANNOCH_ID,
    WELL_EXPL_ID, WELLBORE_EXPL_ID, DATASPACE_ID,
    COLLECTION_EXPL_ID, DRILLING_COLLECTION_EXPL_ID,
    GEOSCIENCE_COLLECTION_EXPL_ID,
    load_json,
)

PARENT_DIR = SCRIPT_DIR.parent


def _collect_ids(manifest: Dict) -> List[str]:
    """Collect all record IDs from a manifest."""
    ids: List[str] = []
    for md in manifest.get("MasterData", []):
        if md.get("id"):
            ids.append(md["id"])
    data = manifest.get("Data", {})
    for grp in ("WorkProductComponents", "Datasets"):
        for wpc in data.get(grp, []):
            if wpc.get("id"):
                ids.append(wpc["id"])
    return ids


def _collect_rddms_ids(manifest: Dict) -> List[str]:
    """Collect record IDs from RDDMS manifest."""
    ids: List[str] = []
    for section in ("WorkProductComponents", "Datasets", "MasterData", "ReferenceData"):
        items = manifest.get(section) or manifest.get("Data", {}).get(section) or []
        if isinstance(items, list):
            for r in items:
                rid = r.get("id")
                if rid:
                    ids.append(rid)
    return ids


def _dedup(refs: List[str]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for r in refs:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


def main():
    ap = argparse.ArgumentParser(
        description="Generate Omega Sør Exploration collections")
    ap.add_argument("--risks", default=str(SCRIPT_DIR / "manifest_risk_exploration.json"))
    ap.add_argument("--drilling", default=str(SCRIPT_DIR / "manifest_drilling_exploration.json"))
    ap.add_argument("--rddms", default=str(PARENT_DIR / "manifest_rddms_omegas.json"))
    ap.add_argument("--manifest", default=str(SCRIPT_DIR / "manifest_collection_exploration.json"))
    ap.add_argument("--id-prefix", default=ID_PREFIX)
    args = ap.parse_args()

    pfx = args.id_prefix

    # ── Collect referenced IDs ──────────────────────────────────────────
    risk_refs: List[str] = []
    drilling_refs: List[str] = []
    rddms_refs: List[str] = []

    if Path(args.risks).exists():
        risk_refs = _collect_ids(load_json(args.risks))
    if Path(args.drilling).exists():
        drilling_refs = _collect_ids(load_json(args.drilling))

    rddms_path = Path(args.rddms)
    if rddms_path.exists():
        rddms_refs = _collect_rddms_ids(load_json(str(rddms_path)))
        print(f"  RDDMS manifest: {len(rddms_refs)} EPC-derived records included")
    else:
        print(f"  ⚠ No RDDMS manifest ({rddms_path.name}) – spatial data pending RDDMS ingest")

    # Master data references
    master_refs = [RESERVOIR_ID, SEG_TARBERT_ID, SEG_RANNOCH_ID, WELL_EXPL_ID, WELLBORE_EXPL_ID]

    # ── Geoscience PersistedCollection (RDDMS + seismic + horizons) ────
    # This is the spatial data collection: seismic horizons, well trajectory,
    # fault polygons, etc. from the RMS model via RDDMS/EPC
    geoscience_refs = _dedup(rddms_refs + [DATASPACE_ID])

    geoscience_collection = {
        "id": GEOSCIENCE_COLLECTION_EXPL_ID,
        "kind": "osdu:wks:work-product-component--PersistedCollection:1.0.0",
        "acl": DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": "Omega Sør Exploration – Geoscience Evidence Package",
            "Description": (
                "Geoscience evidence for the exploration well decision. "
                "Contains RDDMS-derived objects from the RMS geomodel: "
                "seismic horizons (Top Tarbert, Top Rannoch, Base Brent), "
                "fault representations (Inner Snorre Fault, subseismic faults), "
                "drilled well trajectory, stratigraphic column, and "
                "IjkGrid (geo-model). Spatial data for prospect evaluation."
            ),
            "DataReferences": geoscience_refs,
            "SpatialArea": SPATIAL_AREA_WGS84,
            "CoordinateReferenceSystemID": PROJECT_CRS_ID,
        },
    }

    # ── Main Exploration PersistedCollection (all evidence) ────────────
    all_refs = _dedup(
        master_refs + risk_refs + drilling_refs + rddms_refs +
        [DATASPACE_ID, DRILLING_COLLECTION_EXPL_ID, GEOSCIENCE_COLLECTION_EXPL_ID]
    )

    main_collection = {
        "id": COLLECTION_EXPL_ID,
        "kind": "osdu:wks:work-product-component--PersistedCollection:1.0.0",
        "acl": DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": "Omega Sør Exploration – Complete Evidence Package",
            "Description": (
                f"Complete evidence snapshot for the {DISCOVERY_NAME} exploration "
                f"well decision ({WELL_EXPL_ID}). Bundles all artifacts: "
                "reservoir master-data, exploration risks (5, with 2 shared with WPC), "
                "drilling records (trajectory, logs, markers, activities, "
                "casing, fluids), 7 documents from SharePoint WCPNO344-19S, "
                "and RDDMS geomodel objects (seismic horizons, faults, grid). "
                "Links to the same CollaborationProject as the WPC field "
                "development decision for lifecycle traceability."
            ),
            "DataReferences": all_refs,
            "SpatialArea": SPATIAL_AREA_WGS84,
            "CoordinateReferenceSystemID": PROJECT_CRS_ID,
        },
    }

    # ── Assemble manifest ───────────────────────────────────────────────
    manifest = {
        "kind": "osdu:wks:Manifest:1.0.0",
        "ReferenceData": [],
        "MasterData": [],
        "Data": {
            "Datasets": [],
            "WorkProductComponents": [geoscience_collection, main_collection],
            "WorkProducts": [],
        },
    }

    out = Path(args.manifest)
    out.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    n_rddms = len(rddms_refs)
    n_drilling = len(drilling_refs)
    n_risk = len(risk_refs)
    print(f"Exploration collection manifest written → {out}")
    print(f"  Geoscience collection : {GEOSCIENCE_COLLECTION_EXPL_ID}")
    print(f"    DataReferences      : {len(geoscience_refs)} ({n_rddms} RDDMS + 1 dataspace)")
    print(f"  Main collection       : {COLLECTION_EXPL_ID}")
    print(f"    DataReferences      : {len(all_refs)} total")
    print(f"      Master-data       : {len(master_refs)}")
    print(f"      Risks             : {n_risk}")
    print(f"      Drilling          : {n_drilling}")
    print(f"      RDDMS             : {n_rddms}")
    print(f"  CollaborationProject  : {CP_ID} (shared with WPC BD)")


if __name__ == "__main__":
    main()
