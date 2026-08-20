#!/usr/bin/env python3
"""
build_full_manifest.py – Build a comprehensive OSDU manifest covering ALL
objects in the Drogon demo RDDMS dataspace with proper FIRP hierarchy,
cross-references, and specialised OSDU kinds.

Covers what the RDDMS manifest builder misses:
  - Wells → master-data--Wellbore + WellboreTrajectory + WellLog + WellboreMarkerSet
  - StructureMap (Grid2d depth surfaces)
  - SeismicHorizon (Grid2d TWT surfaces)
  - StructuralModel (StructuralOrganizationInterpretation)
  - Cross-references (InterpretedFeatureID, RepresentationIDs, etc.)
  - CoordinateReferenceSystemID on all representations
  - PropertyUoM from RESQML UOM element

Usage:
    python demo/drogonresqml/build_full_manifest.py                     # from local RDDMS
    python demo/drogonresqml/build_full_manifest.py --from-epc          # from EPC directly
    python demo/drogonresqml/build_full_manifest.py --save-only         # save, don't push
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import uuid as uuid_mod
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
EPC_FILE = SCRIPT_DIR / "drogon_demo.epc"
OUT_FILE = SCRIPT_DIR / "manifest_full_interop.json"

# ── Default config (interop / opendes) ────────────────────────────────────
DATASPACE = "maap/drogon"
PARTITION = "opendes"
LEGAL_TAG = "opendes-default-legal-tag"
OWNERS = ["data.default.owners@opendes.dataservices.energy"]
VIEWERS = ["data.default.viewers@opendes.dataservices.energy"]
COUNTRIES = ["US"]

# DDMS base URI pattern
DDMS_URI = f"eml://reservoir-ddms1/dataspace('{DATASPACE}')"


def _configure(partition: str, legal_tag: str, owners: list[str],
               viewers: list[str], countries: list[str],
               dataspace: str | None = None):
    """Override module-level config (called from argparse)."""
    global PARTITION, LEGAL_TAG, OWNERS, VIEWERS, COUNTRIES, DATASPACE, DDMS_URI
    PARTITION = partition
    LEGAL_TAG = legal_tag
    OWNERS = owners
    VIEWERS = viewers
    COUNTRIES = countries
    if dataspace:
        DATASPACE = dataspace
        DDMS_URI = f"eml://reservoir-ddms1/dataspace('{DATASPACE}')"


# ═══════════════════════════════════════════════════════════════════════════
# Parse EPC
# ═══════════════════════════════════════════════════════════════════════════

def parse_epc(epc_path: Path) -> dict:
    """Parse all objects from EPC into a structured inventory."""
    objects = {}
    with zipfile.ZipFile(epc_path, "r") as zf:
        for name in sorted(zf.namelist()):
            if not name.endswith(".xml") or name.startswith("[") or name.startswith("_rels"):
                continue
            m = re.match(r"obj_([A-Za-z0-9]+)_([0-9a-f-]+)\.xml", name)
            if not m:
                continue
            rtype, obj_uuid = m.group(1), m.group(2)
            content = zf.read(name).decode("utf-8")

            title = _extract(r"<eml:Title[^>]*>([^<]+)</eml:Title>", content, "")
            description = _extract(r"<eml:Description[^>]*>([^<]+)</eml:Description>", content, "")
            originator = _extract(r"<eml:Originator[^>]*>([^<]+)</eml:Originator>", content, "")
            creation = _extract(r"<eml:Creation[^>]*>([^<]+)</eml:Creation>", content, "")

            # Relationships
            interp_uuid = _extract(
                r"(?:InterpretedFeature|RepresentedInterpretation).*?<eml:UUID[^>]*>([^<]+)</eml:UUID>",
                content, None, re.S)
            interp_title = _extract(
                r"RepresentedInterpretation.*?<eml:Title[^>]*>([^<]+)</eml:Title>",
                content, None, re.S)
            crs_uuid = _extract(
                r"LocalCrs.*?<eml:UUID[^>]*>([^<]+)</eml:UUID>", content, None, re.S)
            support_uuid = _extract(
                r"SupportingRepresentation.*?<eml:UUID[^>]*>([^<]+)</eml:UUID>", content, None, re.S)

            # Grid2d geometry (for StructureMap enrichment)
            fast_axis = _extract(r"<resqml2:FastestAxisCount[^>]*>(\d+)<", content, None)
            slow_axis = _extract(r"<resqml2:SlowestAxisCount[^>]*>(\d+)<", content, None)
            grid_origin = None
            grid_spacing = None
            if fast_axis:
                ox = _extract(r"<resqml2:Origin[^>]*>.*?<resqml2:Coordinate1[^>]*>([^<]+)", content, None, re.S)
                oy = _extract(r"<resqml2:Origin[^>]*>.*?<resqml2:Coordinate2[^>]*>([^<]+)", content, None, re.S)
                if ox and oy:
                    grid_origin = (float(ox), float(oy))
                spacings = re.findall(r"<resqml2:Spacing[^>]*>.*?<resqml2:Value[^>]*>([^<]+)", content, re.S)
                if spacings:
                    grid_spacing = [float(s) for s in spacings[:2]]

            # Properties
            uom = _extract(r"<resqml2:UOM[^>]*>([^<]+)</resqml2:UOM>", content, None)
            std_kind = _extract(r"<resqml2:Kind[^>]*>([^<]+)</resqml2:Kind>", content, None)
            indexable = _extract(r"<resqml2:IndexableElement[^>]*>([^<]+)</resqml2:IndexableElement>", content, None)
            min_val = _extract(r"<resqml2:MinimumValue[^>]*>([^<]+)</resqml2:MinimumValue>", content, None)
            max_val = _extract(r"<resqml2:MaximumValue[^>]*>([^<]+)</resqml2:MaximumValue>", content, None)

            # ExtraMetadata
            extra = {}
            for em in re.finditer(r"<resqml2:Name[^>]*>([^<]+)</resqml2:Name>\s*<resqml2:Value[^>]*>([^<]+)</resqml2:Value>", content):
                extra[em.group(1)] = em.group(2)

            objects[obj_uuid] = {
                "type": rtype, "uuid": obj_uuid, "title": title,
                "description": description, "originator": originator,
                "creation": creation, "interp_uuid": interp_uuid,
                "interp_title": interp_title,
                "crs_uuid": crs_uuid, "support_uuid": support_uuid,
                "uom": uom, "std_kind": std_kind, "indexable": indexable,
                "min_val": min_val, "max_val": max_val, "extra": extra,
                "fast_axis": int(fast_axis) if fast_axis else None,
                "slow_axis": int(slow_axis) if slow_axis else None,
                "grid_origin": grid_origin, "grid_spacing": grid_spacing,
            }
    return objects


def _extract(pattern: str, content: str, default, flags=0):
    m = re.search(pattern, content, flags)
    return m.group(1) if m else default


# ═══════════════════════════════════════════════════════════════════════════
# Build OSDU records
# ═══════════════════════════════════════════════════════════════════════════

def _base_record(obj_uuid: str, kind: str, name: str, description: str = "",
                 creation: str = "2025-06-12T15:37:00.000Z") -> dict:
    """Create base OSDU record skeleton."""
    return {
        "id": f"{PARTITION}:{kind.replace('osdu:wks:', '')}:{obj_uuid}",
        "kind": kind,
        "acl": {"owners": OWNERS, "viewers": VIEWERS},
        "legal": {
            "legaltags": [LEGAL_TAG],
            "otherRelevantDataCountries": COUNTRIES,
            "status": "compliant",
        },
        "createTime": creation or "2025-06-12T15:37:00.000Z",
        "modifyTime": creation or "2025-06-12T15:37:00.000Z",
        "createUser": "Drogon Demo (Equinor)",
        "modifyUser": "Drogon Demo (Equinor)",
        "version": 1,
        "data": {
            "Name": name,
            "Description": description or f"{name} - Drogon field",
            "ExistenceKind": "osdu:reference-data--ExistenceKind:Prototype:",
        },
    }


def _ddms_uri(rtype: str, obj_uuid: str) -> str:
    return f"{DDMS_URI}/resqml20.obj_{rtype}({obj_uuid})"


def _wpc_id(kind_short: str, obj_uuid: str) -> str:
    return f"{PARTITION}:work-product-component--{kind_short}:{obj_uuid}:"


def _md_id(kind_short: str, obj_uuid: str) -> str:
    return f"{PARTITION}:master-data--{kind_short}:{obj_uuid}:"


def build_manifest(objects: dict) -> dict:
    """Build comprehensive OSDU manifest from parsed EPC objects."""

    # Index by type
    by_type = defaultdict(list)
    for obj in objects.values():
        by_type[obj["type"]].append(obj)

    # Build reverse index: what representations belong to each interpretation
    interp_to_reprs = defaultdict(list)
    for obj in objects.values():
        if obj["interp_uuid"] and obj["type"].endswith("Representation"):
            interp_to_reprs[obj["interp_uuid"]].append(obj["uuid"])

    # Build reverse index: what properties belong to each representation
    repr_to_props = defaultdict(list)
    for obj in objects.values():
        if obj["support_uuid"] and "Property" in obj["type"]:
            repr_to_props[obj["support_uuid"]].append(obj["uuid"])

    datasets = []
    master_data = []
    wpcs = []

    # ── Dataset: ETPDataspace ──
    ds_rec = _base_record(
        f"{DATASPACE.replace('/', '-')}", "osdu:wks:dataset--ETPDataspace:1.0.1",
        DATASPACE, f"RDDMS dataspace for Drogon demo")
    ds_rec["data"]["DatasetProperties"] = {"URI": f"eml:///dataspace('{DATASPACE}')"}
    datasets.append(ds_rec)
    ds_id = ds_rec["id"]

    # ── CRS ──
    for obj in by_type.get("LocalDepth3dCrs", []) + by_type.get("LocalTime3dCrs", []):
        rec = _base_record(obj["uuid"],
                           "osdu:wks:work-product-component--LocalModelCompoundCrs:1.2.0",
                           obj["title"], obj["description"])
        rec["data"]["DDMSDatasets"] = [_ddms_uri(obj["type"], obj["uuid"])]
        rec["data"]["DatasetIDs"] = [ds_id]
        is_time = "Time" in obj["type"]
        rec["data"]["VerticalDomain"] = "time" if is_time else "depth"
        rec["data"]["ProjectedCrsName"] = "ED50 / UTM zone 37S"
        rec["data"]["VerticalCrsName"] = "TWT (ms)" if is_time else "MSL (m)"
        wpcs.append(rec)

    # CRS ID lookup
    depth_crs_id = None
    time_crs_id = None
    for obj in by_type.get("LocalDepth3dCrs", []):
        depth_crs_id = _wpc_id("LocalModelCompoundCrs:1.2.0", obj["uuid"])
    for obj in by_type.get("LocalTime3dCrs", []):
        time_crs_id = _wpc_id("LocalModelCompoundCrs:1.2.0", obj["uuid"])

    # ── Shared BinGrid (all Grid2d surfaces use the same lattice) ──
    bingrid_id = None
    grid2d_objs = by_type.get("Grid2dRepresentation", [])
    if grid2d_objs:
        # Derive shared lattice from first Grid2d (all identical in Drogon)
        ref = grid2d_objs[0]
        if ref.get("fast_axis") and ref.get("slow_axis") and ref.get("grid_origin"):
            # Deterministic UUID from dataspace name (stable across rebuilds)
            bingrid_uuid = str(uuid_mod.uuid5(uuid_mod.NAMESPACE_DNS, f"{DATASPACE}/bingrid"))
            bingrid_id = _wpc_id("GenericBinGrid:1.0.0", bingrid_uuid)
            rec = _base_record(bingrid_uuid,
                               "osdu:wks:work-product-component--GenericBinGrid:1.0.0",
                               "Drogon Surface Grid (shared lattice)",
                               "Shared 280×440 regular grid at 25m spacing for all depth and time surfaces")
            rec["data"]["DatasetIDs"] = [ds_id]
            rec["data"]["CoordinateReferenceSystemID"] = depth_crs_id
            rec["data"]["NodeCountOnIAxis"] = ref["fast_axis"]
            rec["data"]["NodeCountOnJAxis"] = ref["slow_axis"]
            rec["data"]["IncrementOnIAxis"] = ref["grid_spacing"][0] if ref.get("grid_spacing") else 25.0
            rec["data"]["IncrementOnJAxis"] = ref["grid_spacing"][1] if ref.get("grid_spacing") and len(ref["grid_spacing"]) > 1 else 25.0
            rec["data"]["OriginX"] = ref["grid_origin"][0]
            rec["data"]["OriginY"] = ref["grid_origin"][1]
            wpcs.append(rec)

    # ── Boundary Features (MasterData) ──
    for obj in by_type.get("GeneticBoundaryFeature", []):
        rec = _base_record(obj["uuid"],
                           "osdu:wks:master-data--LocalBoundaryFeature:1.1.0",
                           obj["title"], obj["description"])
        rec["data"]["BoundaryType"] = "horizon"
        rec["data"]["DDMSDatasets"] = [_ddms_uri(obj["type"], obj["uuid"])]
        rec["data"]["FieldNames"] = [obj["extra"].get("osdu:FieldName", "Drogon")]
        master_data.append(rec)

    for obj in by_type.get("TectonicBoundaryFeature", []):
        rec = _base_record(obj["uuid"],
                           "osdu:wks:master-data--LocalBoundaryFeature:1.1.0",
                           obj["title"], obj["description"])
        rec["data"]["BoundaryType"] = "fault"
        rec["data"]["DDMSDatasets"] = [_ddms_uri(obj["type"], obj["uuid"])]
        rec["data"]["FieldNames"] = [obj["extra"].get("osdu:FieldName", "Drogon")]
        master_data.append(rec)

    # ── Wells (MasterData) ──
    for obj in by_type.get("WellboreFeature", []):
        rec = _base_record(obj["uuid"],
                           "osdu:wks:master-data--Wellbore:1.3.0",
                           obj["title"], f"Wellbore {obj['title']} - Drogon field")
        rec["data"]["DDMSDatasets"] = [_ddms_uri(obj["type"], obj["uuid"])]
        rec["data"]["FieldNames"] = ["Drogon"]
        rec["data"]["Basin"] = "Norwegian Continental Shelf"
        # Find matching WellboreInterpretation
        for wi in by_type.get("WellboreInterpretation", []):
            if wi["interp_uuid"] == obj["uuid"]:
                rec["data"]["WellboreInterpretationID"] = _ddms_uri("WellboreInterpretation", wi["uuid"])
                break
        master_data.append(rec)

    # ── Horizon Interpretations ──
    for obj in by_type.get("HorizonInterpretation", []):
        rec = _base_record(obj["uuid"],
                           "osdu:wks:work-product-component--HorizonInterpretation:1.2.0",
                           obj["title"], obj["description"])
        rec["data"]["DDMSDatasets"] = [_ddms_uri(obj["type"], obj["uuid"])]
        rec["data"]["DatasetIDs"] = [ds_id]
        rec["data"]["DomainTypeID"] = "osdu:reference-data--DomainType:Mixed:"
        rec["data"]["StratigraphicRoleTypeID"] = "osdu:reference-data--StratigraphicRoleType:Chronostratigraphic:"
        # Cross-ref to feature
        if obj["interp_uuid"]:
            rec["data"]["InterpretedBoundaryFeatureID"] = _md_id("LocalBoundaryFeature:1.1.0", obj["interp_uuid"])
        # Cross-ref to representations
        repr_ids = interp_to_reprs.get(obj["uuid"], [])
        if repr_ids:
            rec["data"]["RepresentationIDs"] = [
                _wpc_id("GenericRepresentation:1.2.0", rid) for rid in repr_ids
            ]
        wpcs.append(rec)

    # ── Fault Interpretations ──
    for obj in by_type.get("FaultInterpretation", []):
        rec = _base_record(obj["uuid"],
                           "osdu:wks:work-product-component--FaultInterpretation:1.3.0",
                           obj["title"], obj["description"])
        rec["data"]["DDMSDatasets"] = [_ddms_uri(obj["type"], obj["uuid"])]
        rec["data"]["DatasetIDs"] = [ds_id]
        if obj["interp_uuid"]:
            rec["data"]["InterpretedBoundaryFeatureID"] = _md_id("LocalBoundaryFeature:1.1.0", obj["interp_uuid"])
        repr_ids = interp_to_reprs.get(obj["uuid"], [])
        if repr_ids:
            rec["data"]["RepresentationIDs"] = [
                _wpc_id("GenericRepresentation:1.2.0", rid) for rid in repr_ids
            ]
        wpcs.append(rec)

    # ── StructuralOrganizationInterpretation → StructuralModel ──
    for obj in by_type.get("StructuralOrganizationInterpretation", []):
        rec = _base_record(obj["uuid"],
                           "osdu:wks:work-product-component--StructuralModel:1.0.0",
                           obj["title"], obj["description"])
        rec["data"]["DDMSDatasets"] = [_ddms_uri(obj["type"], obj["uuid"])]
        rec["data"]["DatasetIDs"] = [ds_id]
        if obj["interp_uuid"]:
            rec["data"]["InterpretedFeatureID"] = _wpc_id("LocalModelFeature:1.2.0", obj["interp_uuid"])
        # Reference all fault and horizon interpretations
        rec["data"]["FaultInterpretationIDs"] = [
            _wpc_id("FaultInterpretation:1.3.0", f["uuid"])
            for f in by_type.get("FaultInterpretation", [])
        ]
        rec["data"]["HorizonInterpretationIDs"] = [
            _wpc_id("HorizonInterpretation:1.2.0", h["uuid"])
            for h in by_type.get("HorizonInterpretation", [])
        ]
        wpcs.append(rec)

    # ── Grid2d → StructureMap (depth) or SeismicHorizon (time) ──
    # First pass: build lookup of interp_uuid → SeismicHorizon record ID
    # so StructureMaps can reference their TWT counterpart via SeismicHorizonID.
    interp_to_seishorizon: dict[str, str] = {}  # interp_uuid → SeismicHorizon WPC id
    for obj in by_type.get("Grid2dRepresentation", []):
        crs_id = time_crs_id if obj.get("crs_uuid") and objects.get(obj["crs_uuid"], {}).get("type") == "LocalTime3dCrs" else depth_crs_id
        is_time = crs_id == time_crs_id
        if is_time and obj["interp_uuid"]:
            interp_to_seishorizon[obj["interp_uuid"]] = _wpc_id("SeismicHorizon:2.1.0", obj["uuid"])

    for obj in by_type.get("Grid2dRepresentation", []):
        crs_id = time_crs_id if obj.get("crs_uuid") and objects.get(obj["crs_uuid"], {}).get("type") == "LocalTime3dCrs" else depth_crs_id
        is_time = crs_id == time_crs_id

        if is_time:
            kind = "osdu:wks:work-product-component--SeismicHorizon:2.1.0"
            kind_short = "SeismicHorizon:2.1.0"
        else:
            kind = "osdu:wks:work-product-component--StructureMap:1.0.0"
            kind_short = "StructureMap:1.0.0"

        # Use the interpreted horizon name if available, else the RESQML title
        name = obj.get("interp_title") or obj["title"]

        rec = _base_record(obj["uuid"], kind, name, obj["description"])
        rec["data"]["DDMSDatasets"] = [_ddms_uri(obj["type"], obj["uuid"])]
        rec["data"]["DatasetIDs"] = [ds_id]
        rec["data"]["CoordinateReferenceSystemID"] = crs_id
        rec["data"]["VerticalDomain"] = "time" if is_time else "depth"
        if obj["interp_uuid"]:
            rec["data"]["InterpretedHorizonID"] = _wpc_id("HorizonInterpretation:1.2.0", obj["interp_uuid"])
        # StructureMap → SeismicHorizon cross-reference (depth surface links to its TWT counterpart)
        if not is_time and obj["interp_uuid"] and obj["interp_uuid"] in interp_to_seishorizon:
            rec["data"]["SeismicHorizonID"] = interp_to_seishorizon[obj["interp_uuid"]]
        # Shared BinGrid reference (all surfaces use the same XY lattice)
        if bingrid_id:
            rec["data"]["BinGridID"] = bingrid_id
        # Inline grid geometry (convenience - authoritative source is BinGrid)
        if obj.get("fast_axis") and obj.get("slow_axis"):
            rec["data"]["NodeCountOnIAxis"] = obj["fast_axis"]
            rec["data"]["NodeCountOnJAxis"] = obj["slow_axis"]
        if obj.get("grid_spacing"):
            rec["data"]["IncrementOnIAxis"] = obj["grid_spacing"][0]
            if len(obj["grid_spacing"]) > 1:
                rec["data"]["IncrementOnJAxis"] = obj["grid_spacing"][1]
        if obj.get("grid_origin"):
            rec["data"]["OriginX"] = obj["grid_origin"][0]
            rec["data"]["OriginY"] = obj["grid_origin"][1]
        wpcs.append(rec)

    # ── PolylineSet + PointSet → GenericRepresentation ──
    for rtype in ("PolylineSetRepresentation", "PointSetRepresentation"):
        for obj in by_type.get(rtype, []):
            rec = _base_record(obj["uuid"],
                               "osdu:wks:work-product-component--GenericRepresentation:1.2.0",
                               obj["title"], obj["description"])
            rec["data"]["DDMSDatasets"] = [_ddms_uri(obj["type"], obj["uuid"])]
            rec["data"]["DatasetIDs"] = [ds_id]
            crs_id_ref = time_crs_id if obj.get("crs_uuid") and objects.get(obj["crs_uuid"], {}).get("type") == "LocalTime3dCrs" else depth_crs_id
            rec["data"]["CoordinateReferenceSystemID"] = crs_id_ref
            if obj["interp_uuid"]:
                rec["data"]["InterpretationID"] = _wpc_id("FaultInterpretation:1.3.0", obj["interp_uuid"])
            rec["data"]["RepresentationType"] = "PolylineSet" if "Polyline" in rtype else "PointSet"
            wpcs.append(rec)

    # ── IjkGrid ──
    for obj in by_type.get("IjkGridRepresentation", []):
        rec = _base_record(obj["uuid"],
                           "osdu:wks:work-product-component--IjkGridRepresentation:1.1.0",
                           obj["title"], obj["description"])
        rec["data"]["DDMSDatasets"] = [_ddms_uri(obj["type"], obj["uuid"])]
        rec["data"]["DatasetIDs"] = [ds_id]
        rec["data"]["CoordinateReferenceSystemID"] = depth_crs_id
        rec["data"]["Ni"] = 92
        rec["data"]["Nj"] = 146
        rec["data"]["Nk"] = 69
        rec["data"]["CellCount"] = 925668
        wpcs.append(rec)

    # ── Grid properties (on IjkGrid) → GenericProperty ──
    ijk_uuid = by_type["IjkGridRepresentation"][0]["uuid"] if by_type.get("IjkGridRepresentation") else None
    for prop_type in ("ContinuousProperty", "DiscreteProperty"):
        for obj in by_type.get(prop_type, []):
            if obj["support_uuid"] != ijk_uuid:
                continue  # well log properties handled below
            rec = _base_record(obj["uuid"],
                               "osdu:wks:work-product-component--GenericProperty:1.2.0",
                               obj["title"], obj["description"])
            rec["data"]["DDMSDatasets"] = [_ddms_uri(obj["type"], obj["uuid"])]
            rec["data"]["DatasetIDs"] = [ds_id]
            rec["data"]["SupportingRepresentationID"] = _wpc_id("IjkGridRepresentation:1.1.0", ijk_uuid)
            rec["data"]["IndexableElementID"] = f"osdu:reference-data--IndexableElement:{obj['indexable'] or 'cells'}:"
            if obj["uom"]:
                rec["data"]["PropertyUoM"] = obj["uom"]
            if obj["std_kind"]:
                rec["data"]["PropertyType"] = {"Name": obj["std_kind"]}
            if obj["min_val"] is not None:
                try:
                    rec["data"]["MinValue"] = float(obj["min_val"])
                except (ValueError, TypeError):
                    pass
            if obj["max_val"] is not None:
                try:
                    rec["data"]["MaxValue"] = float(obj["max_val"])
                except (ValueError, TypeError):
                    pass
            rec["data"]["ValueType"] = "number" if prop_type == "ContinuousProperty" else "integer"
            wpcs.append(rec)

    # ── Wellbore Trajectories ──
    for obj in by_type.get("WellboreTrajectoryRepresentation", []):
        # Resolve well name from chain: Trajectory → WellboreInterpretation → WellboreFeature
        well_name = None
        if obj["interp_uuid"]:
            wi = objects.get(obj["interp_uuid"])
            if wi and wi["interp_uuid"]:
                wf = objects.get(wi["interp_uuid"])
                if wf:
                    well_name = wf["title"]
        traj_name = f"{obj['title']} ({well_name})" if well_name else obj["title"]
        rec = _base_record(obj["uuid"],
                           "osdu:wks:work-product-component--WellboreTrajectory:1.3.0",
                           traj_name, f"Trajectory for {well_name or obj['title']} - Drogon field")
        rec["data"]["DDMSDatasets"] = [_ddms_uri(obj["type"], obj["uuid"])]
        rec["data"]["DatasetIDs"] = [ds_id]
        rec["data"]["CoordinateReferenceSystemID"] = depth_crs_id
        # Link to Wellbore master data
        if obj["interp_uuid"]:
            wi = objects.get(obj["interp_uuid"])
            if wi and wi["interp_uuid"]:
                rec["data"]["WellboreID"] = _md_id("Wellbore:1.3.0", wi["interp_uuid"])
        wpcs.append(rec)

    # ── WellLog (WellboreFrame + its properties) ──
    for obj in by_type.get("WellboreFrameRepresentation", []):
        # Resolve well name
        well_name = None
        if obj["interp_uuid"]:
            wi = objects.get(obj["interp_uuid"])
            if wi and wi["interp_uuid"]:
                wf = objects.get(wi["interp_uuid"])
                if wf:
                    well_name = wf["title"]
        log_name = f"Well Log ({well_name})" if well_name else f"Well Log - {obj['title']}"
        rec = _base_record(obj["uuid"],
                           "osdu:wks:work-product-component--WellLog:1.2.0",
                           log_name, f"Log curves on {well_name or obj['title']} - Drogon field")
        rec["data"]["DDMSDatasets"] = [_ddms_uri(obj["type"], obj["uuid"])]
        rec["data"]["DatasetIDs"] = [ds_id]
        # Link to trajectory/wellbore
        if obj["interp_uuid"]:
            wi = objects.get(obj["interp_uuid"])
            if wi and wi["interp_uuid"]:
                rec["data"]["WellboreID"] = _md_id("Wellbore:1.3.0", wi["interp_uuid"])
        # Count curves (properties on this frame)
        curve_uuids = repr_to_props.get(obj["uuid"], [])
        rec["data"]["CurveCount"] = len(curve_uuids)
        # List curve names
        curves = []
        for cuuid in curve_uuids:
            prop = objects.get(cuuid)
            if prop:
                curve_info = {"CurveName": prop["title"]}
                if prop["std_kind"]:
                    curve_info["PropertyKind"] = prop["std_kind"]
                if prop["uom"]:
                    curve_info["UoM"] = prop["uom"]
                curves.append(curve_info)
        if curves:
            rec["data"]["Curves"] = curves
        wpcs.append(rec)

    # ── WellboreMarkerSet ──
    for obj in by_type.get("WellboreMarkerFrameRepresentation", []):
        # Resolve well name
        well_name = None
        if obj["interp_uuid"]:
            wi = objects.get(obj["interp_uuid"])
            if wi and wi["interp_uuid"]:
                wf = objects.get(wi["interp_uuid"])
                if wf:
                    well_name = wf["title"]
        marker_name = f"Markers ({well_name})" if well_name else f"Markers - {obj['title']}"
        rec = _base_record(obj["uuid"],
                           "osdu:wks:work-product-component--WellboreMarkerSet:1.2.0",
                           marker_name, f"Stratigraphic markers on {well_name or obj['title']} - Drogon field")
        rec["data"]["DDMSDatasets"] = [_ddms_uri(obj["type"], obj["uuid"])]
        rec["data"]["DatasetIDs"] = [ds_id]
        if obj["interp_uuid"]:
            wi = objects.get(obj["interp_uuid"])
            if wi and wi["interp_uuid"]:
                rec["data"]["WellboreID"] = _md_id("Wellbore:1.3.0", wi["interp_uuid"])
        wpcs.append(rec)

    # ── Stratigraphy ──
    for obj in by_type.get("StratigraphicColumn", []):
        rec = _base_record(obj["uuid"],
                           "osdu:wks:work-product-component--StratigraphicColumn:1.2.0",
                           obj["title"], obj["description"])
        rec["data"]["DDMSDatasets"] = [_ddms_uri(obj["type"], obj["uuid"])]
        rec["data"]["DatasetIDs"] = [ds_id]
        wpcs.append(rec)

    for obj in by_type.get("StratigraphicColumnRankInterpretation", []):
        rec = _base_record(obj["uuid"],
                           "osdu:wks:work-product-component--StratigraphicColumnRankInterpretation:1.3.0",
                           obj["title"], obj["description"])
        rec["data"]["DDMSDatasets"] = [_ddms_uri(obj["type"], obj["uuid"])]
        rec["data"]["DatasetIDs"] = [ds_id]
        wpcs.append(rec)

    for obj in by_type.get("StratigraphicUnitFeature", []):
        rec = _base_record(obj["uuid"],
                           "osdu:wks:work-product-component--LocalRockVolumeFeature:1.2.0",
                           obj["title"], obj["description"])
        rec["data"]["DDMSDatasets"] = [_ddms_uri(obj["type"], obj["uuid"])]
        rec["data"]["DatasetIDs"] = [ds_id]
        wpcs.append(rec)

    for obj in by_type.get("StratigraphicUnitInterpretation", []):
        rec = _base_record(obj["uuid"],
                           "osdu:wks:work-product-component--StratigraphicUnitInterpretation:1.3.0",
                           obj["title"], obj["description"])
        rec["data"]["DDMSDatasets"] = [_ddms_uri(obj["type"], obj["uuid"])]
        rec["data"]["DatasetIDs"] = [ds_id]
        if obj["interp_uuid"]:
            rec["data"]["InterpretedFeatureID"] = _wpc_id("LocalRockVolumeFeature:1.2.0", obj["interp_uuid"])
        wpcs.append(rec)

    # ── OrganizationFeature → LocalModelFeature ──
    for obj in by_type.get("OrganizationFeature", []):
        rec = _base_record(obj["uuid"],
                           "osdu:wks:work-product-component--LocalModelFeature:1.2.0",
                           obj["title"], obj["description"])
        rec["data"]["DDMSDatasets"] = [_ddms_uri(obj["type"], obj["uuid"])]
        rec["data"]["DatasetIDs"] = [ds_id]
        wpcs.append(rec)

    # ── Assemble manifest ──
    manifest = {
        "kind": "osdu:wks:Manifest:1.0.0",
        "Data": {
            "Datasets": datasets,
            "MasterData": master_data,
            "WorkProductComponents": wpcs,
        },
    }
    return manifest


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(description="Build comprehensive OSDU manifest from Drogon EPC")
    ap.add_argument("--epc", type=Path, default=EPC_FILE, help="EPC file to parse")
    ap.add_argument("-o", "--output", type=Path, default=None, help="Output manifest path")
    ap.add_argument("--partition", default="opendes", help="OSDU partition for record IDs")
    ap.add_argument("--dataspace", default=None, help="RDDMS dataspace name (default: maap/drogon)")
    ap.add_argument("--legal-tag", default=None, help="Legal tag (default: <partition>-default-legal-tag)")
    ap.add_argument("--owners", default=None, help="Owners ACL group")
    ap.add_argument("--viewers", default=None, help="Viewers ACL group")
    ap.add_argument("--countries", default="US", help="Legal countries (comma-separated)")
    ap.add_argument("--save-only", action="store_true", help="Save manifest, don't push")
    args = ap.parse_args()

    # Apply config
    partition = args.partition
    legal_tag = args.legal_tag or f"{partition}-default-legal-tag"
    owners = [args.owners] if args.owners else [f"data.default.owners@{partition}.dataservices.energy"]
    viewers = [args.viewers] if args.viewers else [f"data.default.viewers@{partition}.dataservices.energy"]
    countries = [c.strip() for c in args.countries.split(",")]
    _configure(partition, legal_tag, owners, viewers, countries,
               dataspace=args.dataspace)

    output = args.output or SCRIPT_DIR / f"manifest_full_{partition}.json"

    print(f"{'═' * 60}")
    print(f"  Building FULL OSDU manifest from {args.epc.name}")
    print(f"  Target: {DATASPACE} @ {PARTITION}")
    print(f"{'═' * 60}\n")

    # Parse EPC
    print("=== 1. Parse EPC ===")
    objects = parse_epc(args.epc)
    type_counts = Counter(o["type"] for o in objects.values())
    print(f"  Parsed {len(objects)} objects ({len(type_counts)} types)")
    for t, c in type_counts.most_common():
        print(f"    {t:45s} {c}")

    # Build manifest
    print(f"\n=== 2. Build manifest ===")
    manifest = build_manifest(objects)

    # Summary
    data = manifest["Data"]
    print(f"\n  Manifest summary:")
    print(f"    Datasets:              {len(data['Datasets'])}")
    print(f"    MasterData:            {len(data['MasterData'])}")
    print(f"    WorkProductComponents: {len(data['WorkProductComponents'])}")
    total = len(data["Datasets"]) + len(data["MasterData"]) + len(data["WorkProductComponents"])
    print(f"    Total:                 {total}")

    # Kind breakdown
    print(f"\n  WPC kinds:")
    wpc_kinds = Counter(r["kind"].split("--")[-1] for r in data["WorkProductComponents"])
    for k, c in wpc_kinds.most_common():
        print(f"    {k}: {c}")

    print(f"\n  MasterData kinds:")
    md_kinds = Counter(r["kind"].split("--")[-1] for r in data["MasterData"])
    for k, c in md_kinds.most_common():
        print(f"    {k}: {c}")

    # Cross-reference audit
    print(f"\n=== 3. Cross-reference audit ===")
    wpcs_with_interp = sum(1 for r in data["WorkProductComponents"]
                           if r["data"].get("InterpretedBoundaryFeatureID") or
                           r["data"].get("InterpretedFeatureID") or
                           r["data"].get("InterpretedHorizonID") or
                           r["data"].get("InterpretationID"))
    wpcs_with_crs = sum(1 for r in data["WorkProductComponents"]
                        if r["data"].get("CoordinateReferenceSystemID"))
    wpcs_with_support = sum(1 for r in data["WorkProductComponents"]
                            if r["data"].get("SupportingRepresentationID"))
    wpcs_with_wellbore = sum(1 for r in data["WorkProductComponents"]
                             if r["data"].get("WellboreID"))
    print(f"  InterpretedFeature refs: {wpcs_with_interp}")
    print(f"  CRS refs:                {wpcs_with_crs}")
    print(f"  SupportingRep refs:      {wpcs_with_support}")
    print(f"  WellboreID refs:         {wpcs_with_wellbore}")

    # Save
    print(f"\n=== 4. Save ===")
    output.write_text(json.dumps(manifest, indent=2))
    size_mb = output.stat().st_size / 1024 / 1024
    print(f"  Saved: {output} ({size_mb:.1f} MB)")
    print(f"\n  Done.")


if __name__ == "__main__":
    main()
