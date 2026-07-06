#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_collection_omegas.py - Generate CollaborationProject + PersistedCollection
+ CollaborationProjectCollection for the Omega Sør WPC decision.

Produces:
  - CollaborationProject master data – long-lived project envelope for the
    Omega Sør field development (survives post-drill follow-up work)
  - CollaborationProjectCollection WPC – living collection of trusted SoR
    resources that grows per gate
  - PersistedCollection WPC – frozen evidence snapshot for the WPC decision,
    bundling ALL artifacts: custom records + RDDMS-derived EPC objects

Collects references from:
  manifest_master_omegas.json   - Reservoir, Well, Wellbore IDs
  manifest_volumes_omegas.json  - Volume WPC IDs
  manifest_risk_omegas.json     - Risk IDs
  manifest_rddms_omegas.json   - EPC-derived RDDMS records (if available)

Output: manifest_collection_omegas.json

Usage:
  python demo/omegas/gen_collection_omegas.py
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

from demo.eqn.omegas._shared import (
    SCRIPT_DIR, DEFAULT_ACL, DEFAULT_LEGAL, ID_PREFIX, DATASPACE,
    SPATIAL_AREA_WGS84, PROJECT_CRS_ID, load_json,
    FIELD_NAME, DISCOVERY_NAME, LICENCE, BLOCK, OPERATOR,
)

# ── Well-known IDs (must match across generators) ──────────────────────
COLLECTION_ID_SUFFIX = "OmegaSor-WPC-Evidence"
CP_ID_SUFFIX = "OmegaSor-FieldDev"
CPC_ID_SUFFIX = "OmegaSor-FieldDev-Collection"


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
    for wp in data.get("WorkProducts", []):
        if wp.get("id"):
            ids.append(wp["id"])
    return ids


def _collect_rddms_ids(manifest: Dict) -> List[str]:
    """Collect record IDs from RDDMS-generated manifest (different structure)."""
    ids: List[str] = []
    # RDDMS manifests may nest under Data.WorkProductComponents or top-level sections
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
        description="Generate Omega Sør CollaborationProject + PersistedCollection")
    ap.add_argument("--master", default=str(SCRIPT_DIR / "manifest_master_omegas.json"))
    ap.add_argument("--volumes", default=str(SCRIPT_DIR / "manifest_volumes_omegas.json"))
    ap.add_argument("--risks", default=str(SCRIPT_DIR / "manifest_risk_omegas.json"))
    ap.add_argument("--drilling", default=str(SCRIPT_DIR / "manifest_drilling_omegas.json"))
    ap.add_argument("--rddms", default=str(SCRIPT_DIR / "manifest_rddms_omegas.json"))
    ap.add_argument("--manifest", default=str(SCRIPT_DIR / "manifest_collection_omegas.json"))
    ap.add_argument("--id-prefix", default=ID_PREFIX)
    args = ap.parse_args()

    pfx = args.id_prefix

    # ── Collect all referenced IDs ──────────────────────────────────────
    custom_refs: List[str] = []

    if Path(args.master).exists():
        custom_refs.extend(_collect_ids(load_json(args.master)))
    if Path(args.volumes).exists():
        custom_refs.extend(_collect_ids(load_json(args.volumes)))
    if Path(args.risks).exists():
        custom_refs.extend(_collect_ids(load_json(args.risks)))
    if Path(args.drilling).exists():
        custom_refs.extend(_collect_ids(load_json(args.drilling)))

    # RDDMS-derived records (IjkGrid, surfaces, faults, trajectories, etc.)
    rddms_refs: List[str] = []
    rddms_path = Path(args.rddms)
    if rddms_path.exists():
        rddms_refs = _collect_rddms_ids(load_json(str(rddms_path)))
        print(f"  RDDMS manifest: {len(rddms_refs)} EPC-derived records included")
    else:
        print(f"  ⚠ No RDDMS manifest ({rddms_path.name}) – run ingest first to include EPC objects")

    # ETP dataspace reference
    dataspace_id = f"{pfx}:dataset--ETPDataspace:maap-omegas:1"

    all_refs = _dedup(custom_refs + rddms_refs + [dataspace_id])

    # ── Stable IDs ──────────────────────────────────────────────────────
    collection_id = f"{pfx}:work-product-component--PersistedCollection:{COLLECTION_ID_SUFFIX}:1"
    cp_id = f"{pfx}:master-data--CollaborationProject:{CP_ID_SUFFIX}:1"
    cpc_id = f"{pfx}:work-product-component--CollaborationProjectCollection:{CPC_ID_SUFFIX}:1"

    # ── 1. CollaborationProject (master data) ───────────────────────────
    cp_record = {
        "id": cp_id,
        "kind": "osdu:wks:master-data--CollaborationProject:1.0.0",
        "acl": DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "ProjectName": f"{DISCOVERY_NAME} Field Development",
            "ProjectID": "OmegaSor-FieldDev",
            "Description": (
                f"Collaboration project for the {DISCOVERY_NAME} field development "
                f"(Snorre area, block {BLOCK}, {LICENCE}). Covers subsurface evaluation, "
                f"WPC well decision, drilling, and post-drill production follow-up. "
                f"Reservoir: Brent Group (Tarbert + Rannoch formations). "
                f"Operator: {OPERATOR}."
            ),
            "Purpose": (
                "Manage the full lifecycle of the Omega Sør field development from "
                "concept maturation through WPC approval, drilling execution, and "
                "post-drill reservoir surveillance. Provides a shared workspace for "
                "subsurface, drilling, and production engineering teams."
            ),
            "LifecycleStatusID": f"{pfx}:reference-data--CollaborationProjectLifecycleStatus:Open:",
            "TrustedCollectionID": cpc_id,
            "ProjectBeginDate": "2025-06-01",
            "Personnel": [
                {"PersonName": "Subsurface Lead", "ProjectRoleID": f"{pfx}:reference-data--ProjectRole:GeoscienceLead:"},
                {"PersonName": "Reservoir Engineer", "ProjectRoleID": f"{pfx}:reference-data--ProjectRole:ReservoirEngineer:"},
                {"PersonName": "Drilling & Wells Lead", "ProjectRoleID": f"{pfx}:reference-data--ProjectRole:DrillingWellsLead:"},
                {"PersonName": "Production Technology", "ProjectRoleID": f"{pfx}:reference-data--ProjectRole:ProductionTechnology:"},
            ],
            "Parameters": [
                {
                    "Title": "SoR Geomodel Dataspace",
                    "ParameterKindID": f"{pfx}:reference-data--ParameterKind:DataObject:",
                    "DataObjectParameter": f"eml:///dataspace('{DATASPACE}')",
                },
                {
                    "Title": "Target Reservoir",
                    "ParameterKindID": f"{pfx}:reference-data--ParameterKind:DataObject:",
                    "DataObjectParameter": f"{pfx}:master-data--Reservoir:OmegaSorAlfa:1",
                },
            ],
            "LifecycleEvents": [
                {
                    "EventID": "1",
                    "Name": "Project Created",
                    "DateTime": "2025-06-01T08:00:00Z",
                    "Remark": "Initial setup for Omega Sør field development evaluation.",
                },
                {
                    "EventID": "2",
                    "Name": "SSVP Complete",
                    "DateTime": "2026-03-15T12:00:00Z",
                    "Remark": "Subsurface evaluation and volume estimation completed. 65-realisation FMU ensemble run.",
                },
                {
                    "EventID": "3",
                    "Name": "WPC Evidence Package Frozen",
                    "DateTime": "2026-07-01T09:00:00Z",
                    "Remark": "Evidence package (PersistedCollection) frozen for WPC review. Decision due 2026-09-30.",
                },
            ],
            "SpatialArea": SPATIAL_AREA_WGS84,
        },
    }

    # ── 2. CollaborationProjectCollection WPC (living SoR collection) ──
    cpc_record = {
        "id": cpc_id,
        "kind": "osdu:wks:work-product-component--CollaborationProjectCollection:1.0.0",
        "acl": DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": f"{DISCOVERY_NAME} – Trusted SoR Collection",
            "Description": (
                "Living collection of trusted system-of-record resources for the "
                f"{DISCOVERY_NAME} field development. Grows as new artifacts are "
                "approved per gate. Referenced by CollaborationProject.TrustedCollectionID."
            ),
            "ResourceIDs": all_refs,
        },
    }

    # ── 3. PersistedCollection WPC (frozen evidence snapshot for WPC) ──
    collection_wpc = {
        "id": collection_id,
        "kind": "osdu:wks:work-product-component--PersistedCollection:1.0.0",
        "acl": DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": "Omega Sør WPC – Evidence Package",
            "Description": (
                "Frozen evidence snapshot for the Omega Sør WPC well planning decision. "
                "Bundles all subsurface evaluation artifacts: "
                "reservoir master-data, well records (exploration + planned), "
                "volume tables (statistical + in-place), 5 risks, "
                "RDDMS geomodel objects (IjkGrid, horizons, faults, trajectories), "
                "and the ETP dataspace reference."
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
        "MasterData": [cp_record],
        "Data": {
            "Datasets": [],
            "WorkProductComponents": [cpc_record, collection_wpc],
            "WorkProducts": [],
        },
    }

    out = Path(args.manifest)
    out.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    n_custom = len(custom_refs)
    n_rddms = len(rddms_refs)
    print(f"Collection manifest written → {out}")
    print(f"  CollaborationProject    : {cp_id}")
    print(f"  ProjectCollection (SoR) : {cpc_id}")
    print(f"  PersistedCollection     : {collection_id}")
    print(f"  DataReferences          : {len(all_refs)} total ({n_custom} custom + {n_rddms} RDDMS + 1 dataspace)")


if __name__ == "__main__":
    main()
