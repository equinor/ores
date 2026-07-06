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


def main():
    ap = argparse.ArgumentParser(
        description="Generate DG2 PersistedCollection WPC"
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

    # ── Gather all component IDs from every manifest ──────────────
    components: List[str] = []

    def _add_all(path_str: str, kind_frag: str | None = None) -> None:
        p = Path(path_str)
        if p.exists():
            man = load_json(str(p))
            components.extend(_collect_ids(man, kind_frag))

    # Input WPCs (volumes, parameters, production forecast)
    _add_all(args.rawvol)
    _add_all(args.statvol)
    _add_all(args.params)
    _add_all(args.production)

    # DevelopmentConcept
    _add_all(args.devconcept)

    # Grid + grid properties (IjkGridRepresentation)
    _add_all(args.grid)

    # Maps / surfaces (StructureMap + GenericRepresentation)
    _add_all(args.maps)

    # Simulator tables (ColumnBasedTable: relperm, pvt, summary, etc.)
    _add_all(args.simtables)

    # Polygons (GenericRepresentation: fault lines, outlines)
    _add_all(args.polygons)

    # Activity + ActivityTemplate
    _add_all(args.activity)

    # Risks (master-data)
    _add_all(args.risks)

    # Documents (WPCs)
    _add_all(args.documents)

    # Shared master data (Reservoir, ReservoirSegments)
    _add_all(args.masterwp, "master-data--Reservoir")

    # Wells + Wellbores (DG1 shared master data)
    _add_all(args.wells)

    # Lithostratigraphic column + rank + unit interpretations
    _add_all(args.strat)

    # WellboreMarkerSets (formation tops per wellbore)
    _add_all(args.markers)

    # Seismic (SeismicBinGrid + SeismicTraceData WPCs) – IDs use target prefix
    seismic_ids = [
        f"{pfx}:work-product-component--SeismicBinGrid:drogon-seismic-bingrid",
        f"{pfx}:work-product-component--SeismicTraceData:drogon-amp-far-time-20180101",
        f"{pfx}:work-product-component--SeismicTraceData:drogon-amp-near-time-20180101",
    ]
    components.extend(seismic_ids)

    # GeoLabelSet (generated separately, added by ID)
    if args.geolabelset_id:
        components.append(args.geolabelset_id)

    # ETP Dataspace dataset
    dataspace_id = f"{pfx}:dataset--ETPDataspace:maap-drogon_dg:1"
    components.append(dataspace_id)

    # ── De-duplicate while preserving order ───────────────────────
    seen: set[str] = set()
    unique: List[str] = []
    for c in components:
        if c and c not in seen:
            seen.add(c)
            unique.append(c)
    components = unique

    # ── Build PersistedCollection WPC record ─────────────────────
    collection_id = (
        f"{pfx}:work-product-component--PersistedCollection:"
        "Drogon-DG2-EvidencePackage:1"
    )

    pc_record: Dict[str, Any] = {
        "id":    collection_id,
        "kind":  "osdu:wks:work-product-component--PersistedCollection:1.0.0",
        "acl":   DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": "Drogon DG2 - Evidence Package",
            "Description": (
                "PersistedCollection bundling all artifacts used to create "
                "the Drogon DG2 Concept Select BusinessDecision. "
                "Includes input volumes (raw + statistics), parameters, "
                "production forecast, development concept, grid model (IjkGrid + 10 properties), "
                "structure maps (49 surfaces), simulator tables (relperm, PVT, summary, "
                "well completions, group tree), polygons (fault lines, outlines), "
                "seismic (SeismicBinGrid + SeismicTraceData far/near with OpenVDS), "
                "activity chain, risks, documents, wells + wellbores, "
                "lithostratigraphic column, wellbore marker sets, "
                "GeoLabelSet, and RDDMS dataspace reference. "
                f"{len(components)} data references."
            ),
            "DataReferences": components,
            "Tags": [
                "DG2",
                "Drogon",
                "EvidencePackage",
                "Seismic",
                "Stratigraphy",
                "WellboreMarkerSet",
                "Wells",
            ],
        },
    }

    manifest: Dict[str, Any] = {
        "kind": "osdu:wks:Manifest:1.0.0",
        "ReferenceData": [],
        "MasterData": [],
        "Data": {
            "Datasets": [],
            "WorkProductComponents": [pc_record],
            "WorkProducts": [],
        },
    }

    out = Path(args.manifest)
    out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"DG2 PersistedCollection manifest written → {out}")
    print(f"  Collection ID : {collection_id}")
    print(f"  DataReferences: {len(components)} artifacts")
    for c in components:
        print(f"    • {c}")

    return collection_id


if __name__ == "__main__":
    main()
