#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_collection_dg2.py - Generate a PersistedCollection WPC
that bundles **all** artifacts feeding the DG2 BusinessDecision.

This gives the BD a single "DG2 evidence package" reference in addition
to the individual Parameters[] entries - the recommended OSDU pattern
when the artifact set is large (see BusinessDecision guide §6–7).

Uses the OSDU canonical schema:
  osdu:wks:work-product-component--PersistedCollection:1.0.0

The PersistedCollection.DataReferences[] list collects every object
referenced by the BD - inputs, outputs, context references, risks,
documents, activity, GeoLabelSet, DevelopmentConcept, and the ETP
dataspace dataset.

Reads (from DG2 folder):
  manifest_wpcraw_dg2.json
  manifest_wpcstat_dg2.json
  manifest_wpcparams_dg2.json
  manifest_wpc_production_dg2.json
  manifest_activity_dg2.json
  manifest_risk_dg2.json
  manifest_documents_dg2.json
  manifest_devconcept_dg2.json

Reads (from DG1 folder - shared master data):
  ../drogon/manifest_masterwp_drogon.json

Output:
  manifest_collection_dg2.json

Usage:
  python demo/drogon_dg2/gen_collection_dg2.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

SCRIPT_DIR = Path(__file__).resolve().parent       # demo/drogon_dg2
DG1_DIR    = SCRIPT_DIR.parent / "drogon"           # demo/drogon

import sys
if str(DG1_DIR) not in sys.path:
    sys.path.insert(0, str(DG1_DIR))
from _shared import load_json  # noqa: E402

DEFAULT_ACL = {
    "owners":  ["data.default.owners@dev.dataservices.energy"],
    "viewers": ["data.office.global.viewers@dev.dataservices.energy"],
}
DEFAULT_LEGAL = {
    "legaltags": ["dev-equinor-private-default"],
    "otherRelevantDataCountries": ["NO"],
}


def _collect_ids(manifest: Dict, kind_fragment: str | None = None) -> List[str]:
    """Collect all record IDs from a manifest, optionally filtered by kind."""
    ids: List[str] = []
    for md in manifest.get("MasterData", []):
        if kind_fragment is None or kind_fragment in md.get("kind", ""):
            ids.append(md["id"])
    data = manifest.get("Data", {})
    for grp in ("WorkProductComponents", "Datasets"):
        for wpc in data.get(grp, []):
            if kind_fragment is None or kind_fragment in wpc.get("kind", ""):
                ids.append(wpc["id"])
    # WorkProduct (single object)
    wp = data.get("WorkProduct")
    if isinstance(wp, dict) and wp.get("id"):
        if kind_fragment is None or kind_fragment in wp.get("kind", ""):
            ids.append(wp["id"])
    return ids


def _find_id(manifest: Dict, kind_fragment: str) -> str:
    ids = _collect_ids(manifest, kind_fragment)
    return ids[0] if ids else ""


def _dedup(refs: List[str]) -> List[str]:
    """De-duplicate while preserving order."""
    seen: set[str] = set()
    out: List[str] = []
    for r in refs:
        if r and r not in seen:
            seen.add(r)
            out.append(r)
    return out


def main():
    ap = argparse.ArgumentParser(
        description="Generate DG2 PersistedCollection WPCs (hierarchical)"
    )
    # DG1 shared master data
    ap.add_argument("--masterwp",    default=str(DG1_DIR / "manifest_masterwp_drogon.json"))
    # DG2-specific manifests
    ap.add_argument("--rawvol",      default=str(SCRIPT_DIR / "manifest_wpcraw_dg2.json"))
    ap.add_argument("--statvol",     default=str(SCRIPT_DIR / "manifest_wpcstat_dg2.json"))
    ap.add_argument("--params",      default=str(SCRIPT_DIR / "manifest_wpcparams_dg2.json"))
    ap.add_argument("--production",  default=str(SCRIPT_DIR / "manifest_wpc_production_dg2.json"))
    ap.add_argument("--activity",    default=str(SCRIPT_DIR / "manifest_activity_dg2.json"))
    ap.add_argument("--risks",       default=str(SCRIPT_DIR / "manifest_risk_dg2.json"))
    ap.add_argument("--documents",   default=str(SCRIPT_DIR / "manifest_documents_dg2.json"))
    ap.add_argument("--devconcept",  default=str(SCRIPT_DIR / "manifest_devconcept_dg2.json"))
    ap.add_argument("--grid",        default=str(SCRIPT_DIR / "manifest_grid_dg2.json"))
    ap.add_argument("--maps",        default=str(SCRIPT_DIR / "manifest_maps_dg2.json"))
    ap.add_argument("--simtables",   default=str(SCRIPT_DIR / "manifest_simtables_dg2.json"))
    ap.add_argument("--polygons",    default=str(SCRIPT_DIR / "manifest_polygons_dg2.json"))
    ap.add_argument("--wells",       default=str(DG1_DIR / "manifest_wells_drogon.json"))
    ap.add_argument("--strat",       default=str(DG1_DIR / "manifest_litho_strat_drogon.json"))
    ap.add_argument("--markers",     default=str(DG1_DIR / "manifest_markers_drogon.json"))
    ap.add_argument("--geolabelset-id",
                    default="dev:work-product-component--GeoLabelSet:e4b7a1c3-5f28-4d9e-8a61-7c3d9e0f2b85:1")
    ap.add_argument("--manifest",    default=str(SCRIPT_DIR / "manifest_collection_dg2.json"))
    ap.add_argument("--id-prefix",   default="dev")
    args = ap.parse_args()

    pfx = args.id_prefix

    # ── Helper: load IDs from manifest ────────────────────────────
    def _load_ids(path_str: str, kind_frag: str | None = None) -> List[str]:
        p = Path(path_str)
        if p.exists():
            return _collect_ids(load_json(str(p)), kind_frag)
        return []

    # ── Sub-collection IDs ────────────────────────────────────────
    COLL_GEOMODEL  = f"{pfx}:work-product-component--PersistedCollection:Drogon-DG2-Geomodel:1"
    COLL_SEISMIC   = f"{pfx}:work-product-component--PersistedCollection:Drogon-DG2-Seismic:1"
    COLL_WELLS     = f"{pfx}:work-product-component--PersistedCollection:Drogon-DG2-Wells:1"
    COLL_SIMULATION = f"{pfx}:work-product-component--PersistedCollection:Drogon-DG2-Simulation:1"
    COLL_DOCUMENTS = f"{pfx}:work-product-component--PersistedCollection:Drogon-DG2-Documents:1"
    COLL_MAIN      = f"{pfx}:work-product-component--PersistedCollection:Drogon-DG2-EvidencePackage:1"

    # ── 1. Geomodel Package ───────────────────────────────────────
    # Grid, maps, polygons, RDDMS dataspace
    geomodel_refs = _dedup(
        _load_ids(args.grid)
        + _load_ids(args.maps)
        + _load_ids(args.polygons)
        + [f"{pfx}:dataset--ETPDataspace:maap-drogon_dg:1"]
    )
    geomodel_collection: Dict[str, Any] = {
        "id": COLL_GEOMODEL,
        "kind": "osdu:wks:work-product-component--PersistedCollection:1.0.0",
        "acl": DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": "Drogon DG2 – Geomodel Package",
            "Description": (
                "Static geomodel evidence for DG2 Concept Select. "
                "IjkGridRepresentation (92×146×69, 10 properties: PHIT, KLOGH, KV, SW, SWL, "
                "SG, VSH, FACIES, REGION, ZONE), 49 depth/property surfaces (StructureMap + "
                "GenericRepresentation), fault polygons and outlines, and RDDMS dataspace. "
                f"{len(geomodel_refs)} data references."
            ),
            "DataReferences": geomodel_refs,
            "Tags": ["DG2", "Drogon", "Geomodel", "Grid", "Maps", "Polygons"],
        },
    }

    # ── 2. Seismic Package ────────────────────────────────────────
    # BinGrid + TraceData + VDS/SEGY datasets
    seismic_refs = [
        f"{pfx}:work-product-component--SeismicBinGrid:drogon-seismic-bingrid",
        f"{pfx}:work-product-component--SeismicTraceData:drogon-amp-far-time-20180101",
        f"{pfx}:work-product-component--SeismicTraceData:drogon-amp-near-time-20180101",
        f"{pfx}:dataset--FileCollection.Bluware.OpenVDS:drogon-amplitude-far-time-20180101",
        f"{pfx}:dataset--FileCollection.Bluware.OpenVDS:drogon-amplitude-near-time-20180101",
        f"{pfx}:dataset--FileCollection.SEGY:drogon-amplitude-far-time-20180101",
        f"{pfx}:dataset--FileCollection.SEGY:drogon-amplitude-near-time-20180101",
    ]
    seismic_collection: Dict[str, Any] = {
        "id": COLL_SEISMIC,
        "kind": "osdu:wks:work-product-component--PersistedCollection:1.0.0",
        "acl": DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": "Drogon DG2 – Seismic Package",
            "Description": (
                "Seismic evidence for DG2 Concept Select. "
                "Drogon 3D survey (436×276 bins, 25 m spacing): SeismicBinGrid, "
                "2 SeismicTraceData (far/near offset, time domain, 2000 samples), "
                "with OpenVDS converted volumes and original SEG-Y files. "
                f"{len(seismic_refs)} data references."
            ),
            "DataReferences": seismic_refs,
            "Tags": ["DG2", "Drogon", "Seismic", "OpenVDS", "BinGrid"],
        },
    }

    # ── 3. Wells Package ──────────────────────────────────────────
    # Wells, wellbores, markers, stratigraphy
    well_refs = _dedup(
        _load_ids(args.wells)
        + _load_ids(args.strat)
        + _load_ids(args.markers)
    )
    wells_collection: Dict[str, Any] = {
        "id": COLL_WELLS,
        "kind": "osdu:wks:work-product-component--PersistedCollection:1.0.0",
        "acl": DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": "Drogon DG2 – Wells & Stratigraphy Package",
            "Description": (
                "Well data evidence for DG2 Concept Select. "
                "Drogon wells (55/33-A-1 through A-6) + wellbores, "
                "lithostratigraphic column (Volantis Group: Valysar, Therys, Volon), "
                "wellbore marker sets (formation tops per wellbore). "
                f"{len(well_refs)} data references."
            ),
            "DataReferences": well_refs,
            "Tags": ["DG2", "Drogon", "Wells", "Stratigraphy", "WellboreMarkerSet"],
        },
    }

    # ── 4. Simulation Package ─────────────────────────────────────
    # Volumes (raw/stat), parameters, production forecast, sim tables
    simulation_refs = _dedup(
        _load_ids(args.rawvol)
        + _load_ids(args.statvol)
        + _load_ids(args.params)
        + _load_ids(args.production)
        + _load_ids(args.simtables)
    )
    simulation_collection: Dict[str, Any] = {
        "id": COLL_SIMULATION,
        "kind": "osdu:wks:work-product-component--PersistedCollection:1.0.0",
        "acl": DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": "Drogon DG2 – Simulation & Volumes Package",
            "Description": (
                "Dynamic simulation evidence for DG2 Concept Select. "
                "250-realisation FMU volumes (raw + P10/P50/P90 statistics), "
                "design matrix (21 parameters), 20-year production forecast, "
                "simulator tables (relperm, PVT, summary vectors, well completions, "
                "group tree). OPM Flow simulator. "
                f"{len(simulation_refs)} data references."
            ),
            "DataReferences": simulation_refs,
            "Tags": ["DG2", "Drogon", "Simulation", "Volumes", "FMU"],
        },
    }

    # ── 5. Documents Package ──────────────────────────────────────
    document_refs = _load_ids(args.documents)
    documents_collection: Dict[str, Any] = {
        "id": COLL_DOCUMENTS,
        "kind": "osdu:wks:work-product-component--PersistedCollection:1.0.0",
        "acl": DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": "Drogon DG2 – Documents Package",
            "Description": (
                "Decision documents for DG2 Concept Select. "
                "SRA (Subsurface Risk Assessment), CRA (Concept Risk Assessment), "
                "draft PDO (Plan for Development & Operation), "
                "Petroleum Technology Report. "
                f"{len(document_refs)} data references."
            ),
            "DataReferences": document_refs,
            "Tags": ["DG2", "Drogon", "Documents", "SRA", "PDO"],
        },
    }

    # ── 6. Main Evidence Package (references sub-collections) ─────
    # Top-level also includes: risks, activity, devconcept, reservoir master-data,
    # GeoLabelSet, and the sub-collection IDs themselves
    toplevel_refs: List[str] = []

    # Sub-collection references
    toplevel_refs.extend([
        COLL_GEOMODEL, COLL_SEISMIC, COLL_WELLS,
        COLL_SIMULATION, COLL_DOCUMENTS,
    ])

    # Activity + ActivityTemplate
    toplevel_refs.extend(_load_ids(args.activity))

    # Risks
    toplevel_refs.extend(_load_ids(args.risks))

    # DevelopmentConcept
    toplevel_refs.extend(_load_ids(args.devconcept))

    # Shared master data (Reservoir, ReservoirSegments)
    toplevel_refs.extend(_load_ids(args.masterwp, "master-data--Reservoir"))

    # GeoLabelSet
    if args.geolabelset_id:
        toplevel_refs.append(args.geolabelset_id)

    toplevel_refs = _dedup(toplevel_refs)

    # Total count across all sub-collections
    total_artifacts = (
        len(geomodel_refs) + len(seismic_refs) + len(well_refs)
        + len(simulation_refs) + len(document_refs) + len(toplevel_refs)
    )

    main_collection: Dict[str, Any] = {
        "id": COLL_MAIN,
        "kind": "osdu:wks:work-product-component--PersistedCollection:1.0.0",
        "acl": DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": "Drogon DG2 – Evidence Package",
            "Description": (
                "Top-level evidence package for DG2 Concept Select. "
                "Organises all supporting artifacts into domain-specific "
                "sub-collections: Geomodel (grid + maps + polygons), "
                "Seismic (BinGrid + TraceData far/near + OpenVDS), "
                "Wells & Stratigraphy (wells + markers + litho column), "
                "Simulation & Volumes (FMU + forecast + tables), "
                "and Documents (SRA, CRA, PDO, PTR). "
                "Also directly references risks, activity chain, "
                "DevelopmentConcept, reservoir master-data, and GeoLabelSet. "
                f"{total_artifacts} total artifacts across 5 sub-collections."
            ),
            "DataReferences": toplevel_refs,
            "Tags": ["DG2", "Drogon", "EvidencePackage", "TopLevel"],
        },
    }

    # ── Assemble manifest ─────────────────────────────────────────
    all_records = [
        geomodel_collection,
        seismic_collection,
        wells_collection,
        simulation_collection,
        documents_collection,
        main_collection,
    ]

    manifest: Dict[str, Any] = {
        "kind": "osdu:wks:Manifest:1.0.0",
        "ReferenceData": [],
        "MasterData": [],
        "Data": {
            "Datasets": [],
            "WorkProductComponents": all_records,
            "WorkProducts": [],
        },
    }

    out = Path(args.manifest)
    out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"DG2 PersistedCollection manifest written → {out}")
    print(f"  6 collections ({len(all_records)} records):")
    for r in all_records:
        n = len(r["data"]["DataReferences"])
        print(f"    {r['data']['Name']:50s} ({n} refs) {r['id']}")
    print(f"  Total artifacts: {total_artifacts}")

    return COLL_MAIN


if __name__ == "__main__":
    main()
