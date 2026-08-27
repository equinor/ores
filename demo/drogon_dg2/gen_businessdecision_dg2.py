#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_businessdecision_dg2.py - Generate a BusinessDecision manifest for
Drogon DG2 (Decision Gate 2 - Concept Select).

This is the enriched DG2 record including elements not present at DG1:
  - KeyEconomics (NPV, IRR, CAPEX, OPEX, Breakeven, Payback)
  - ScheduleMilestones (7 milestones from DG2 through plateau)
  - ProductionProfile (20-year forecast with oil/gas/water/cum/RF)
  - Enriched DevelopmentConcept (host facility, flowlines, IOR, well plan)
  - Per-alternative economics in Alternatives[]
  - Document references in Parameters[] (SRA, CRA, PDO, PTR)
  - VolumesSummary with recoverable volumes
  - Extended UncertaintySummary with StaticInPlace AND Recoverable
  - 4 risks (porosity, fault, HSE, schedule)

Reads (from DG1 folder - shared master data):
  ../drogon/manifest_masterwp_drogon.json   - Reservoir ID, acl, legal

Reads (from DG2 folder - DG2-specific volume tables with ×0.8 porosity):
  manifest_wpcraw_dg2.json      - DG2 Raw REV WPC ID (volumes ×0.8)
  manifest_wpcstat_dg2.json     - DG2 Statistics REV WPC ID
  manifest_wpcparams_dg2.json   - DG2 ColumnBasedTable WPC ID (porosity ×0.8)
  manifest_activity_dg2.json    - DG2 Activity WPC ID
  manifest_risk_dg2.json        - Risk IDs (4 risks)
  manifest_documents_dg2.json   - Document IDs (SRA, CRA, PDO, PTR)

Output:
  manifest_bd_dg2.json

Usage:
  py demo/drogon_dg2/gen_businessdecision_dg2.py
"""

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

SCRIPT_DIR = Path(__file__).resolve().parent       # demo/drogon_dg2
DG1_DIR    = SCRIPT_DIR.parent / "drogon_dg1"           # demo/drogon_dg1

import sys
if str(DG1_DIR) not in sys.path:
    sys.path.insert(0, str(DG1_DIR))
from _shared import load_json  # noqa: E402

DEFAULT_ACL = {
    "owners":  ["data.default.owners@dev.dataservices.energy"],
    "viewers": ["data.default.viewers@dev.dataservices.energy"],
}
DEFAULT_LEGAL = {
    "legaltags": ["opendes-private-usa-default"],
    "otherRelevantDataCountries": ["NO"],
}


def _find_id(manifest: Dict, kind_fragment: str) -> str:
    """Find the first record ID whose kind contains kind_fragment."""
    for md in manifest.get("MasterData", []):
        if kind_fragment in md.get("kind", ""):
            return md["id"]
    for wpc in manifest.get("Data", {}).get("WorkProductComponents", []):
        if kind_fragment in wpc.get("kind", ""):
            return wpc["id"]
    return ""


def _find_all_ids(manifest: Dict, kind_fragment: str) -> List[str]:
    ids = []
    for md in manifest.get("MasterData", []):
        if kind_fragment in md.get("kind", ""):
            ids.append(md["id"])
    for wpc in manifest.get("Data", {}).get("WorkProductComponents", []):
        if kind_fragment in wpc.get("kind", ""):
            ids.append(wpc["id"])
    return ids


def main():
    ap = argparse.ArgumentParser(description="Generate Drogon DG2 BusinessDecision manifest")
    # DG1 shared master data
    ap.add_argument("--masterwp",  default=str(DG1_DIR / "manifest_masterwp_drogon.json"))
    # DG2-specific volume tables (×0.8 porosity)
    ap.add_argument("--rawvol",    default=str(SCRIPT_DIR / "manifest_wpcraw_dg2.json"))
    ap.add_argument("--statvol",   default=str(SCRIPT_DIR / "manifest_wpcstat_dg2.json"))
    ap.add_argument("--params",    default=str(SCRIPT_DIR / "manifest_wpcparams_dg2.json"))
    ap.add_argument("--activity",  default=str(SCRIPT_DIR / "manifest_activity_dg2.json"))
    # DG2-specific risks & documents
    ap.add_argument("--risks",     default=str(SCRIPT_DIR / "manifest_risk_dg2.json"))
    ap.add_argument("--documents", default=str(SCRIPT_DIR / "manifest_documents_dg2.json"))
    ap.add_argument("--production", default=str(SCRIPT_DIR / "manifest_wpc_production_dg2.json"))
    ap.add_argument("--devconcept", default=str(SCRIPT_DIR / "manifest_devconcept_dg2.json"))
    ap.add_argument("--grid",       default=str(SCRIPT_DIR / "manifest_grid_dg2.json"))
    ap.add_argument("--maps",       default=str(SCRIPT_DIR / "manifest_maps_dg2.json"))
    ap.add_argument("--simtables",  default=str(SCRIPT_DIR / "manifest_simtables_dg2.json"))
    ap.add_argument("--polygons",   default=str(SCRIPT_DIR / "manifest_polygons_dg2.json"))
    ap.add_argument("--geolabelset-id", default="dev:work-product-component--GeoLabelSet:e4b7a1c3-5f28-4d9e-8a61-7c3d9e0f2b85:1")
    ap.add_argument("--collection", default=str(SCRIPT_DIR / "manifest_collection_dg2.json"))
    ap.add_argument("--manifest",  default=str(SCRIPT_DIR / "manifest_bd_dg2.json"))
    ap.add_argument("--id-prefix", default="dev")
    args = ap.parse_args()

    pfx = args.id_prefix

    # ── Load shared master data + DG2 volume manifests ────────────────
    masterwp = load_json(args.masterwp)
    rawvol   = load_json(args.rawvol)
    statvol  = load_json(args.statvol)
    params   = load_json(args.params)
    risks    = load_json(args.risks)

    # Activity (from DG1)
    activity_id = ""
    if Path(args.activity).exists():
        act_man = load_json(args.activity)
        activity_id = _find_id(act_man, "work-product-component--Activity:")

    # DG2 documents
    doc_ids: Dict[str, str] = {}
    if Path(args.documents).exists():
        doc_man = load_json(args.documents)
        for wpc in doc_man.get("Data", {}).get("WorkProductComponents", []):
            rid = wpc.get("id", "")
            if "SRA" in rid:
                doc_ids["sra"] = rid
            elif "CRA" in rid:
                doc_ids["cra"] = rid
            elif "PDO" in rid:
                doc_ids["pdo"] = rid
            elif "PTR" in rid:
                doc_ids["ptr"] = rid

    reservoir_id  = _find_id(masterwp, "master-data--Reservoir:")
    segment_ids   = _find_all_ids(masterwp, "master-data--ReservoirSegment:")
    raw_wpc_id    = _find_id(rawvol,   "ReservoirEstimatedVolumes")
    stat_wpc_id   = _find_id(statvol,  "ReservoirEstimatedVolumes")
    params_wpc_id = _find_id(params,   "ColumnBasedTable")
    risk_ids      = _find_all_ids(risks, "master-data--Risk:")

    # PP WPC manifest
    pp_wpc_id = ""
    if Path(args.production).exists():
        pp_wpc_id = _find_id(load_json(args.production), "ColumnBasedTable")

    # DevelopmentConcept WPC manifest
    devconcept_wpc_id = ""
    if Path(args.devconcept).exists():
        devconcept_wpc_id = _find_id(load_json(args.devconcept), "DevelopmentConcept")

    # Grid WPC (IjkGridRepresentation)
    grid_wpc_id = ""
    if Path(args.grid).exists():
        grid_wpc_id = _find_id(load_json(args.grid), "IjkGridRepresentation")

    # Maps WPC (first StructureMap for reference)
    maps_wpc_ids = []
    if Path(args.maps).exists():
        maps_man = load_json(args.maps)
        maps_wpc_ids = _find_all_ids(maps_man, "StructureMap")
        maps_wpc_ids += _find_all_ids(maps_man, "GenericRepresentation")

    # Simulator tables
    simtable_wpc_ids = []
    if Path(args.simtables).exists():
        simtable_wpc_ids = _find_all_ids(load_json(args.simtables), "ColumnBasedTable")

    # Polygons
    polygon_wpc_ids = []
    if Path(args.polygons).exists():
        polygon_wpc_ids = _find_all_ids(load_json(args.polygons), "GenericRepresentation")

    # Reference to DG1 BD (prior decision gate)
    dg1_bd_id = f"{pfx}:master-data--BusinessDecision:Drogon-DG1-Identify:1"

    # PersistedCollection WPC (evidence package - top-level)
    collection_id = ""
    if Path(args.collection).exists():
        coll_man = load_json(args.collection)
        for wpc in coll_man.get("Data", {}).get("WorkProductComponents", []):
            if "PersistedCollection" in wpc.get("kind", ""):
                wpc_id = wpc["id"]
                if "EvidencePackage" in wpc_id:
                    collection_id = wpc_id
                    break
        # Fallback: use last one (top-level is last in hierarchical manifest)
        if not collection_id:
            for wpc in reversed(coll_man.get("Data", {}).get("WorkProductComponents", [])):
                if "PersistedCollection" in wpc.get("kind", ""):
                    collection_id = wpc["id"]
                    break

    # ETP dataspace for RESQML artefacts
    dataspace_id = f"{pfx}:dataset--ETPDataspace:maap-drogon_dg:1"

    # ── Build DG2 BusinessDecision ───────────────────────────────────
    bd_id = f"{pfx}:master-data--BusinessDecision:Drogon-DG2-ConceptSelect:1"

    bd_record = {
        "id":    bd_id,
        "kind":  "osdu:wks:master-data--BusinessDecision:1.0.0",
        "acl":   DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": "Drogon DG2 - Concept Select",
            "Description": (
                "DG2 Concept Select for the Drogon field development, aligned with the "
                "official Drogon FMU model (equinor/fmu-drogon tutorial 24.3.1). "
                "Volantis Group (Valysar, Therys, Volon formations) across 7 fault-bounded "
                "reservoir regions (WestLowland, CentralSouth, CentralNorth, NorthHorst, "
                "CentralRamp, CentralHorst, EastLowland). 250 FMU realisations with "
                "one-by-one sensitivity design, OPM Flow simulator. "
                "4 producers (A1\u2013A4), 2 water injectors (A5\u2013A6). "
                "STOIIP P50 45.4 MSm\u00b3, EUR P50 10.4 MSm\u00b3 oil, RF P50 33.5%. "
                "Recommended concept: subsea tie-back to FPSO with 2\u00d74-slot templates, "
                "6 active wells + 2 contingent infill. "
                "NPV@10% 520 MUSD, CAPEX 8,500 MNOK, first oil 2028-H1."
            ),
            "ProjectName": "Drogon Field Development",
            "DecisionLevelID": f"{pfx}:reference-data--DecisionLevel:DG2:",
            "ApprovalStatusID": f"{pfx}:reference-data--DecisionApprovalStatus:Pending:",
            "DecisionDueDate": "2026-06-30",
            "DecisionSummary": (
                "Approve subsea tie-back development concept. Two 4-slot templates (8 slots + "
                "2 contingent), 4 producers (A1\u2013A4) + 2 injectors (A5\u2013A6) targeting full "
                "Volantis Group (Valysar, Therys, Volon) across 7 regions. STOIIP P50 "
                "45.4 MSm\u00b3 (P90 33.8, P10 59.4). EUR P50 10.4 MSm\u00b3 (RF 33.5%). "
                "250 FMU realisations with one-by-one sensitivity (drogon_design.ert). "
                "First oil target 2028-H1. Proceed to DG3 FEED."
            ),
            "RiskAssessmentDocument": doc_ids.get("sra", ""),
            "ReservoirIDs": [reservoir_id] if reservoir_id else [],
            "ReservoirSegmentIDs": segment_ids,
            "RiskIDs": risk_ids,
            "PriorActivityIDs": (
                [activity_id] if activity_id
                else [x for x in [raw_wpc_id, stat_wpc_id, params_wpc_id] if x]
            ),
            "Parameters": _build_parameters(
                pfx, raw_wpc_id, stat_wpc_id, params_wpc_id,
                reservoir_id, dataspace_id, dg1_bd_id, doc_ids,
                pp_wpc_id, devconcept_wpc_id,
                gls_id=args.geolabelset_id,
                collection_id=collection_id,
                grid_wpc_id=grid_wpc_id,
                maps_wpc_ids=maps_wpc_ids,
                simtable_wpc_ids=simtable_wpc_ids,
                polygon_wpc_ids=polygon_wpc_ids,
                seismic_wpc_ids=[
                    f"{pfx}:dataset--FileCollection.Bluware.OpenVDS:drogon-amplitude-far-time-20180101",
                    f"{pfx}:dataset--FileCollection.Bluware.OpenVDS:drogon-amplitude-near-time-20180101",
                ],
                sub_collection_ids=[
                    f"{pfx}:work-product-component--PersistedCollection:Drogon-DG2-Geomodel:1",
                    f"{pfx}:work-product-component--PersistedCollection:Drogon-DG2-Seismic:1",
                    f"{pfx}:work-product-component--PersistedCollection:Drogon-DG2-Wells:1",
                    f"{pfx}:work-product-component--PersistedCollection:Drogon-DG2-Simulation:1",
                    f"{pfx}:work-product-component--PersistedCollection:Drogon-DG2-Documents:1",
                ],
            ),
            # ── Canonical fields (survive OSDU ingestion) ──
            **_build_canonical_fields(pfx),
            "ancestry": {
                "parents": [activity_id] if activity_id else [],
                "children": [x for x in [args.geolabelset_id] if x],
            },
            "ext": {
                "equinor": _build_ext_equinor(pfx, risk_ids),
            },
        },
    }

    manifest = {
        "kind": "osdu:wks:Manifest:1.0.0",
        "ReferenceData": [],
        "MasterData": [bd_record],
        "Data": {
            "Datasets": [],
            "WorkProductComponents": [],
            "WorkProducts": [],
        },
    }

    out = Path(args.manifest)
    out.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"DG2 BusinessDecision manifest written \u2192 {out}")
    print(f"  BD ID        : {bd_id}")
    print(f"  Reservoir ref: {reservoir_id}")
    print(f"  Raw REV ref  : {raw_wpc_id}")
    print(f"  Stat REV ref : {stat_wpc_id}")
    print(f"  Params ref   : {params_wpc_id}")
    print(f"  Risk refs    : {risk_ids}")
    print(f"  Doc refs     : {list(doc_ids.values())}")
    print(f"  Collection   : {collection_id or '(none)'}")


# ─────────────────────────────────────────────────────────────────────
# Parameters[] - typed references to evidence artefacts
# ─────────────────────────────────────────────────────────────────────

def _build_parameters(
    pfx: str,
    raw_wpc_id: str, stat_wpc_id: str, params_wpc_id: str,
    reservoir_id: str, dataspace_id: str, dg1_bd_id: str,
    doc_ids: Dict[str, str],
    pp_wpc_id: str = "",
    devconcept_wpc_id: str = "",
    gls_id: str = "",
    collection_id: str = "",
    grid_wpc_id: str = "",
    maps_wpc_ids: List[str] | None = None,
    simtable_wpc_ids: List[str] | None = None,
    polygon_wpc_ids: List[str] | None = None,
    seismic_wpc_ids: List[str] | None = None,
    sub_collection_ids: List[str] | None = None,
) -> List[Dict[str, Any]]:
    params: List[Dict[str, Any]] = [
        {
            "Title": "Raw volumes (per realisation)",
            "Selection": "Raw per-realisation volumes feeding the statistical summary",
            "ParameterKindID": f"{pfx}:reference-data--ParameterKind:DataObject:",
            "ParameterRoleID": f"{pfx}:reference-data--ParameterRole:Input:",
            "DataObjectParameter": raw_wpc_id,
            "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "REV-raw"}],
        },
        {
            "Title": "Statistical volumes (P10/P50/P90)",
            "Selection": "Aggregated statistics used for the DG2 concept selection",
            "ParameterKindID": f"{pfx}:reference-data--ParameterKind:DataObject:",
            "ParameterRoleID": f"{pfx}:reference-data--ParameterRole:Input:",
            "DataObjectParameter": stat_wpc_id,
            "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "REV-stats"}],
        },
        {
            "Title": "Design matrix – one-by-one sensitivities (250 realisations)",
            "Selection": "Real design matrix from drogon_design.ert: 15 sensitivities × 21 parameters",
            "ParameterKindID": f"{pfx}:reference-data--ParameterKind:DataObject:",
            "ParameterRoleID": f"{pfx}:reference-data--ParameterRole:Input:",
            "DataObjectParameter": params_wpc_id,
            "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "ColumnBasedTable-designmatrix"}],
        },
        {
            "Title": "Reservoir scope",
            "Selection": "Master-data context for the decision",
            "ParameterKindID": f"{pfx}:reference-data--ParameterKind:DataObject:",
            "ParameterRoleID": f"{pfx}:reference-data--ParameterRole:InputReference:",
            "DataObjectParameter": reservoir_id,
        },
        {
            "Title": "GeoModelDataspace",
            "Selection": "RDDMS ETP dataspace with the Drogon DG2 geomodel EPC files",
            "ParameterKindID": f"{pfx}:reference-data--ParameterKind:DataObject:",
            "ParameterRoleID": f"{pfx}:reference-data--ParameterRole:InputReference:",
            "DataObjectParameter": dataspace_id,
            "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "ETPDataspace"}],
        },
        {
            "Title": "Prior gate (DG1 Identify & Assess)",
            "Selection": "DG1 decision record for the Drogon field",
            "ParameterKindID": f"{pfx}:reference-data--ParameterKind:DataObject:",
            "ParameterRoleID": f"{pfx}:reference-data--ParameterRole:InputReference:",
            "DataObjectParameter": dg1_bd_id,
            "Keys": [
                {"ParameterKey": "gate", "StringParameterKey": "DG1"},
                {"ParameterKey": "relationship", "StringParameterKey": "supersedes"},
            ],
        },
    ]
    # Document references
    doc_entries = [
        ("SRA report",                 "sra"),
        ("CRA report",                 "cra"),
        ("PDO (draft)",                "pdo"),
        ("Petroleum Technology Report", "ptr"),
    ]
    for title, key in doc_entries:
        did = doc_ids.get(key)
        if did:
            params.append({
                "Title": title,
                "ParameterKindID": f"{pfx}:reference-data--ParameterKind:DataObject:",
                "ParameterRoleID": f"{pfx}:reference-data--ParameterRole:InputReference:",
                "DataObjectParameter": did,
            })
    # Production Forecast WPC reference
    if pp_wpc_id:
        params.append({
            "Title": "Production Forecast (20-year)",
            "Selection": "Reference case forecast from dynamic simulation (revised porosity ×0.8)",
            "ParameterKindID": f"{pfx}:reference-data--ParameterKind:DataObject:",
            "ParameterRoleID": f"{pfx}:reference-data--ParameterRole:Input:",
            "DataObjectParameter": pp_wpc_id,
            "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "ProductionForecast"}],
        })
    # DevelopmentConcept WPC reference
    if devconcept_wpc_id:
        params.append({
            "Title": "Development Concept",
            "Selection": "DG2 development concept definition",
            "ParameterKindID": f"{pfx}:reference-data--ParameterKind:DataObject:",
            "ParameterRoleID": f"{pfx}:reference-data--ParameterRole:Input:",
            "DataObjectParameter": devconcept_wpc_id,
            "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "DevelopmentConcept"}],
        })
    # GeoLabelSet - headline volumes & reservoir properties
    if gls_id:
        params.append({
            "Title": "Headline volumes & reservoir properties (GeoLabelSet)",
            "Selection": "P10/P50/P90 headline volumes per segment, derived from stat REV",
            "ParameterKindID": f"{pfx}:reference-data--ParameterKind:DataObject:",
            "ParameterRoleID": f"{pfx}:reference-data--ParameterRole:Input:",
            "DataObjectParameter": gls_id,
            "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "GeoLabelSet"}],
        })
    # Persisted collection (WorkProduct evidence package)
    if collection_id:
        params.append({
            "Title": "DG2 Evidence Package (persisted collection)",
            "Selection": (
                "WorkProduct bundling all DG2 input/output artifacts - "
                "volumes, parameters, forecast, grid model, maps, "
                "simulator tables, polygons, risks, documents, "
                "GeoLabelSet, activity, and ETP dataspace reference"
            ),
            "ParameterKindID": f"{pfx}:reference-data--ParameterKind:DataObject:",
            "ParameterRoleID": f"{pfx}:reference-data--ParameterRole:InputReference:",
            "DataObjectParameter": collection_id,
            "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "PersistedCollection"}],
        })
    # ── Geomodel artifacts (grid, maps, tables, polygons) ────────
    if grid_wpc_id:
        params.append({
            "Title": "Static geomodel grid (IjkGridRepresentation + 10 properties)",
            "Selection": (
                "Drogon geogrid 92×146×69 (Valysar/Therys/Volon) with PHIT, KLOGH, "
                "KV, SW, SWL, SG, VSH, FACIES, REGION, ZONE. RDDMS-backed."
            ),
            "ParameterKindID": f"{pfx}:reference-data--ParameterKind:DataObject:",
            "ParameterRoleID": f"{pfx}:reference-data--ParameterRole:Input:",
            "DataObjectParameter": grid_wpc_id,
            "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "GridModel"}],
        })
    if maps_wpc_ids:
        # Reference the first StructureMap as representative; collection has all
        params.append({
            "Title": f"Depth surfaces and derived maps ({len(maps_wpc_ids)} WPCs)",
            "Selection": (
                "Structure depth surfaces (6 horizons), amplitude maps, facies fractions, "
                "property averages, APS probability cubes. P50 aggregated. RDDMS-backed."
            ),
            "ParameterKindID": f"{pfx}:reference-data--ParameterKind:DataObject:",
            "ParameterRoleID": f"{pfx}:reference-data--ParameterRole:Input:",
            "DataObjectParameter": maps_wpc_ids[0],
            "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "DepthSurfaces"}],
        })
    if simtable_wpc_ids:
        params.append({
            "Title": f"Simulator tables ({len(simtable_wpc_ids)} WPCs: relperm, PVT, summary, completions, gruptree)",
            "Selection": (
                "Eclipse/OPM output tables exported by RES2CSV. "
                "Includes saturation functions, fluid properties, summary vectors, "
                "well completion data, and group tree hierarchy."
            ),
            "ParameterKindID": f"{pfx}:reference-data--ParameterKind:DataObject:",
            "ParameterRoleID": f"{pfx}:reference-data--ParameterRole:Input:",
            "DataObjectParameter": simtable_wpc_ids[0],
            "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "SimulatorTables"}],
        })
    if polygon_wpc_ids:
        params.append({
            "Title": f"Polygons ({len(polygon_wpc_ids)} WPCs: fault lines, outlines)",
            "Selection": (
                "Fault lines (4 horizons), field outline, fluid contact outlines (GOC, FWL)."
            ),
            "ParameterKindID": f"{pfx}:reference-data--ParameterKind:DataObject:",
            "ParameterRoleID": f"{pfx}:reference-data--ParameterRole:InputReference:",
            "DataObjectParameter": polygon_wpc_ids[0],
            "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "Polygons"}],
        })
    # ── Seismic (SeismicTraceData WPCs via OpenVDS) ──────────────
    if seismic_wpc_ids:
        for s_id in seismic_wpc_ids:
            offset = "FAR" if "far" in s_id.lower() else "NEAR"
            params.append({
                "Title": f"OpenVDS Drogon Amplitude {offset.title()} Offset (Time) 2018-01-01",
                "Selection": (
                    "Curated OpenVDS seismic volume supporting the DG2 concept selection "
                    "evidence package."
                ),
                "ParameterKindID": f"{pfx}:reference-data--ParameterKind:DataObject:",
                "ParameterRoleID": f"{pfx}:reference-data--ParameterRole:InputReference:",
                "DataObjectParameter": s_id,
                "Keys": [
                    {"ParameterKey": "artifact", "StringParameterKey": f"OpenVDS-seismic-{offset.lower()}"},
                    {"ParameterKey": "domain", "StringParameterKey": "SeismicTraceData"},
                    {"ParameterKey": "format", "StringParameterKey": "OpenVDS"},
                    {"ParameterKey": "offsetClass", "StringParameterKey": offset},
                ],
            })
    # ── Sub-collections (domain-specific evidence packages) ──────
    if sub_collection_ids:
        sub_titles = {
            "Geomodel": "Geomodel Package (grid + maps + polygons + RDDMS)",
            "Seismic": "Seismic Package (BinGrid + TraceData far/near + OpenVDS)",
            "Wells": "Wells & Stratigraphy Package",
            "Simulation": "Simulation & Volumes Package (FMU + forecast + tables)",
            "Documents": "Documents Package (SRA, CRA, PDO, PTR)",
        }
        for coll_id in sub_collection_ids:
            # Extract domain from ID: ...:Drogon-DG2-{Domain}:1
            domain = coll_id.split("Drogon-DG2-")[-1].split(":")[0]
            title = sub_titles.get(domain, f"{domain} Package")
            params.append({
                "Title": title,
                "Selection": "Domain-specific evidence sub-collection for DG2",
                "ParameterKindID": f"{pfx}:reference-data--ParameterKind:DataObject:",
                "ParameterRoleID": f"{pfx}:reference-data--ParameterRole:InputReference:",
                "DataObjectParameter": coll_id,
                "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "PersistedCollection"}],
            })
    return params


# ─────────────────────────────────────────────────────────────────────
# Canonical BD fields (survive OSDU ingestion)
# ─────────────────────────────────────────────────────────────────────

def _build_canonical_fields(pfx: str) -> Dict[str, Any]:
    """Return canonical data.* fields mapped from ext.equinor concepts."""
    return {
        # ── Personnel[] ← Authors ──
        "Personnel": [
            {"Name": "Kristin Haugen",   "ProjectRoleID": f"{pfx}:reference-data--ProjectRole:GeoscienceLead:",   "Organisation": "Drogon Subsurface"},
            {"Name": "Henrik Bjørnstad", "ProjectRoleID": f"{pfx}:reference-data--ProjectRole:ReservoirEngineer:", "Organisation": "Drogon Reservoir Management"},
            {"Name": "Anna-Lise Tveit",  "ProjectRoleID": f"{pfx}:reference-data--ProjectRole:Petrophysicist:",   "Organisation": "Drogon Petec"},
            {"Name": "Erik Stensrud",    "ProjectRoleID": f"{pfx}:reference-data--ProjectRole:FMULead:",           "Organisation": "Drogon Geomodelling"},
            {"Name": "Silje Vik",        "ProjectRoleID": f"{pfx}:reference-data--ProjectRole:FacilitiesEngineer:","Organisation": "Drogon Concept"},
            {"Name": "Olav Mæland",      "ProjectRoleID": f"{pfx}:reference-data--ProjectRole:DrillingWellsLead:", "Organisation": "Drogon D&W"},
        ],
        # ── DecisionOwners/Makers/Contributors[] ← ReviewTeam ──
        "DecisionOwners": [
            {"Name": "Kristin Haugen", "Organisation": "Drogon Subsurface Lead"},
        ],
        "DecisionMakers": [
            {"Name": "Lars Kongsvik", "Organisation": "Drogon Project Director"},
        ],
        "Contributors": [
            {"Name": "Erik Stensrud", "Organisation": "Drogon Geomodelling"},
            {"Name": "Marte Nygaard", "Organisation": "ST MSU Subsurface QA"},
            {"Name": "Trond Berge",   "Organisation": "Drogon QRM Manager"},
        ],
        # ── Remarks[] ← Recommendations ──
        "Remarks": [
            {"Remark": r, "RemarkSource": "DG2 Recommendations"}
            for r in [
                "Execute FEED for FPSO conversion and subsea installation scope",
                "Secure FPSO drydock slot (2027-Q4 target) with dual-yard tendering strategy",
                "Drill NorthHorst appraisal sidetrack to constrain fault compartmentalisation model",
                "Finalise Phase 2 water injection well locations based on DG3 dynamic simulation",
                "Complete EIA with cold-water coral avoidance routing for flowline corridor",
                "Run Level 3+ FMU workflow with 100+ realisations for DG3 volumetric basis",
                "Prepare PDO final draft for MPE submission post-FID",
            ]
        ],
        # ── ProjectSpecifications[] ← KeyEconomics ──
        "ProjectSpecifications": [
            {"ParameterTypeID": f"{pfx}:reference-data--ParameterType:NPV_10pct:",      "DataQuantityParameter": 520,  "UnitOfMeasureID": f"{pfx}:reference-data--UnitOfMeasure:MUSD:"},
            {"ParameterTypeID": f"{pfx}:reference-data--ParameterType:IRR:",             "DataQuantityParameter": 17,   "UnitOfMeasureID": f"{pfx}:reference-data--UnitOfMeasure:%:"},
            {"ParameterTypeID": f"{pfx}:reference-data--ParameterType:CAPEX:",           "DataQuantityParameter": 8500, "UnitOfMeasureID": f"{pfx}:reference-data--UnitOfMeasure:MNOK:"},
            {"ParameterTypeID": f"{pfx}:reference-data--ParameterType:OPEX_pa:",         "DataQuantityParameter": 420,  "UnitOfMeasureID": f"{pfx}:reference-data--UnitOfMeasure:MNOK:"},
            {"ParameterTypeID": f"{pfx}:reference-data--ParameterType:BreakevenOil:",    "DataQuantityParameter": 42,   "UnitOfMeasureID": f"{pfx}:reference-data--UnitOfMeasure:USD/bbl:"},
            {"ParameterTypeID": f"{pfx}:reference-data--ParameterType:Payback:",         "DataQuantityParameter": 7.0,  "UnitOfMeasureID": f"{pfx}:reference-data--UnitOfMeasure:a:"},
        ],
        # ── ActivityStates[] ← ScheduleMilestones ──
        "ActivityStates": [
            {"MilestoneID": "DG2",       "EffectiveDateTime": "2026-02-28", "ActivityStatusID": f"{pfx}:reference-data--ActivityStatus:Completed:", "Remark": "DG2 Concept Select"},
            {"MilestoneID": "DG3",       "EffectiveDateTime": "2027-01-01", "ActivityStatusID": f"{pfx}:reference-data--ActivityStatus:Planned:",   "Remark": "DG3 FEED"},
            {"MilestoneID": "DG4",       "EffectiveDateTime": "2027-07-01", "ActivityStatusID": f"{pfx}:reference-data--ActivityStatus:Planned:",   "Remark": "FID / DG4"},
            {"MilestoneID": "INSTALL",   "EffectiveDateTime": "2027-10-01", "ActivityStatusID": f"{pfx}:reference-data--ActivityStatus:Planned:",   "Remark": "FPSO Drydock Start"},
            {"MilestoneID": "INSTALL",   "EffectiveDateTime": "2028-01-01", "ActivityStatusID": f"{pfx}:reference-data--ActivityStatus:Planned:",   "Remark": "Subsea Installation"},
            {"MilestoneID": "FIRST_OIL", "EffectiveDateTime": "2028-06-01", "ActivityStatusID": f"{pfx}:reference-data--ActivityStatus:Planned:",   "Remark": "First Oil"},
            {"MilestoneID": "PLATEAU",   "EffectiveDateTime": "2029-01-01", "ActivityStatusID": f"{pfx}:reference-data--ActivityStatus:Planned:",   "Remark": "Plateau Production"},
        ],
    }


# ─────────────────────────────────────────────────────────────────────
# ext.equinor - the enrichment payload
# ─────────────────────────────────────────────────────────────────────

def _build_ext_equinor(pfx: str, risk_ids: List[str]) -> Dict[str, Any]:
    return {

        # ── Template references ──────────────────────────────────────
        "ActivityStateTemplateID": f"{pfx}:work-product-component--ActivityStateTemplate:FieldDevelopment:1",
        "ProjectTypeID": f"{pfx}:reference-data--ProjectType:FieldDevelopment:",

        # ── Alternatives with per-alternative economics ──────────────
        "Alternatives": [
            {
                "Name": "Alt-A: Subsea tie-back to FPSO (4 prod + 2 inj, 2\u00d74-slot templates)",
                "Rank": 1,
                "Rationale": (
                    "Highest NPV; leverages planned FPSO conversion for Drogon area. "
                    "4 producers (A1\u2013A4) + 2 water injectors (A5\u2013A6), 2\u00d74-slot templates "
                    "with 2 contingent slots for infill. Based on 250 FMU realisations "
                    "(drogon_design.ert). Peak oil 5,500 Sm\u00b3/d, plateau 2020\u20132021. "
                    "Subsea boosting pump for low-pressure phase. "
                    "EUR 10.4 MSm\u00b3 oil at RF 33.5%."
                ),
                "RecommendedAction": "Approve",
                "NPV_10pct_MUSD": 520,
                "CAPEX_MNOK": 8500,
                "IRR_pct": 17,
            },
            {
                "Name": "Alt-B: Reduced scope - CentralHorst + CentralSouth only (3 prod + 1 inj)",
                "Rank": 2,
                "Rationale": (
                    "Focus on the two highest-confidence regions (CentralHorst + CentralSouth, "
                    "FIPNUM 2,6). Channel facies dominant, lowest FWL uncertainty. "
                    "3 producers + 1 injector, single 4-slot template. "
                    "Lower investment but captures only ~55% of recoverable resource. "
                    "OPM Flow sensitivity: EUR ~5.8 MSm\u00b3, RF ~30%. "
                    "Provides first-oil option if FPSO schedule slips."
                ),
                "RecommendedAction": "Consider",
                "NPV_10pct_MUSD": 300,
                "CAPEX_MNOK": 4800,
                "IRR_pct": 20,
            },
            {
                "Name": "Alt-C: Defer - acquire DG3-quality appraisal data",
                "Rank": 3,
                "Rationale": (
                    "NorthHorst and EastLobe fault compartmentalisation remains "
                    "poorly constrained. Additional well test data (est. 12 months, "
                    "200 MNOK) would reduce dynamic uncertainty range by ~40%. "
                    "Risk of losing FPSO drydock window if deferred beyond 2026-Q3."
                ),
                "RecommendedAction": "Fallback",
                "NPV_10pct_MUSD": None,
                "CAPEX_MNOK": None,
                "IRR_pct": None,
            },
        ],

        # ── Uncertainty Summary (enriched with recoverable) ──────────
        "UncertaintySummary": {
            "Basis": (
                "FMU static + dynamic uncertainty from 250 realisations (one-by-one "
                "sensitivity design, drogon_design.ert) across Volantis Group "
                "(Valysar, Therys, Volon) and 7 fault-bounded regions. "
                "Dynamic forecasts run with OPM Flow for all realisations."
            ),
            "Note": (
                "See stat WPC for full P10/P50/P90 breakdown per segment & facies. "
                "Recoverable estimated from dynamic simulation with 4 producers (A1\u2013A4) "
                "and 2 water injectors (A5\u2013A6). Key uncertainty drivers: FWL contacts, "
                "Kv/Kh per facies, fault seal scaling, relperm interpolation, "
                "APS facies probability fractions."
            ),
            "TotalRealisations": 250,
            "DesignType": "one-by-one sensitivity",
            "ErtConfig": "drogon_design.ert",
            "Simulator": "OPM_FLOW",
            "SelectedRealisations": {
                "P90": "Real 42",
                "P50": "Real 1",
                "P10": "Real 17",
            },
            "MethodologyReference": "FMU Level 3 static + dynamic uncertainty workflow (equinor/fmu-drogon 24.3.1)",
            "StaticInPlace_Oil_MSm3": {
                "P90": 33.8,
                "P50": 45.4,
                "P10": 59.4,
            },
            "Recoverable_Oil_MSm3": {
                "P90": 7.5,
                "P50": 10.4,
                "P10": 14.2,
            },
            "RecoveryFactor_pct": {
                "P90": 28.0,
                "P50": 33.5,
                "P10": 37.0,
            },
            "GIIP_P50_GSm3": 6.4,
            "PeakOilRate_Sm3d": 5500,
            "TopUncertaintyDrivers": [
                "FWL_CENTRAL (STOIIP driver)",
                "FAULT_SEAL_SCALING (recovery driver)",
                "KVKH_CHANNEL (sweep efficiency)",
                "RELPERM_INT_WO (water cut / recovery)",
                "VALYSAR_APS_PROB_CHANNEL (facies distribution)",
            ],
        },
    }


if __name__ == "__main__":
    main()
