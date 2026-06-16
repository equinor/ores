#!/usr/bin/env python3
"""
build_full_manifest_22.py – Build a comprehensive OSDU manifest from the
Drogon RESQML 2.2 EPC with maximum OSDU alignment.

RESQML 2.2 improvements for OSDU mapping:
  - BoundaryFeature is now unified → 1:1 with LocalBoundaryFeature
  - RockVolumeFeature → 1:1 with LocalRockVolumeFeature
  - No obj_ prefix in type names → cleaner DDMSDataset URIs
  - PropertyKindIndex → better alignment with OSDU reference-data PropertyKind
  - EML Common 2.3 citation → richer metadata mapping

Usage:
    python demo/drogonresqml22/build_full_manifest_22.py                # from EPC
    python demo/drogonresqml22/build_full_manifest_22.py --save-only    # save, no push
    python demo/drogonresqml22/build_full_manifest_22.py --from-201     # convert from 2.0.1 EPC
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import uuid as uuid_mod
import zipfile
from collections import defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
EPC_FILE_22 = SCRIPT_DIR / "drogon_demo_22.epc"
EPC_FILE_201 = SCRIPT_DIR.parent / "drogonresqml" / "drogon_demo.epc"
OUT_FILE = SCRIPT_DIR / "manifest_drogon22_interop.json"

# ── Default config (interop / opendes) ────────────────────────────────────
DATASPACE = "maap/drogon22"
PARTITION = "opendes"
LEGAL_TAG = "opendes-ReservoirDDMS-Legal-Tag"
OWNERS = ["data.default.owners@opendes.dataservices.energy"]
VIEWERS = ["data.default.viewers@opendes.dataservices.energy"]
COUNTRIES = ["US"]

# DDMS base URI – uses resqml22 prefix (no obj_)
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
# RESQML 2.2 → OSDU type mapping
#
# Key improvements over 2.0.1:
#   1. BoundaryFeature (unified) → LocalBoundaryFeature (1:1, was 2:1)
#   2. RockVolumeFeature → LocalRockVolumeFeature (1:1, was renamed)
#   3. Model → LocalModelFeature (1:1, cleaner name)
# ═══════════════════════════════════════════════════════════════════════════

# RESQML 2.2 type → OSDU kind (direct 1:1 where possible)
RESQML22_TO_OSDU = {
    # Master Data (Features) – all 1:1 in RESQML 2.2!
    "BoundaryFeature": "osdu:wks:master-data--LocalBoundaryFeature:1.1.0",
    "RockVolumeFeature": "osdu:wks:work-product-component--LocalRockVolumeFeature:1.2.0",
    "Model": "osdu:wks:work-product-component--LocalModelFeature:1.2.0",
    "WellboreFeature": "osdu:wks:master-data--Wellbore:1.3.0",

    # WPC – Interpretations (all 1:1)
    "HorizonInterpretation": "osdu:wks:work-product-component--HorizonInterpretation:1.2.0",
    "FaultInterpretation": "osdu:wks:work-product-component--FaultInterpretation:1.3.0",
    "StructuralOrganizationInterpretation": "osdu:wks:work-product-component--StructuralModel:1.0.0",
    "StratigraphicColumn": "osdu:wks:work-product-component--StratigraphicColumn:1.2.0",
    "StratigraphicColumnRankInterpretation": "osdu:wks:work-product-component--StratigraphicColumnRankInterpretation:1.3.0",
    "StratigraphicUnitInterpretation": "osdu:wks:work-product-component--StratigraphicUnitInterpretation:1.3.0",

    # WPC – Representations (some 1:1, some context-dependent)
    "IjkGridRepresentation": "osdu:wks:work-product-component--IjkGridRepresentation:1.1.0",
    "Grid2dRepresentation": None,  # → StructureMap or SeismicHorizon (context-dependent)
    "WellboreTrajectoryRepresentation": "osdu:wks:work-product-component--WellboreTrajectory:1.3.0",
    "WellboreFrameRepresentation": "osdu:wks:work-product-component--WellLog:1.2.0",
    "WellboreMarkerFrameRepresentation": "osdu:wks:work-product-component--WellboreMarkerSet:1.2.0",
    "PolylineSetRepresentation": "osdu:wks:work-product-component--GenericRepresentation:1.2.0",
    "PointSetRepresentation": "osdu:wks:work-product-component--GenericRepresentation:1.2.0",

    # WPC – Properties (collapse to GenericProperty)
    "ContinuousProperty": "osdu:wks:work-product-component--GenericProperty:1.2.0",
    "DiscreteProperty": "osdu:wks:work-product-component--GenericProperty:1.2.0",
    "CategoricalProperty": "osdu:wks:work-product-component--GenericProperty:1.2.0",

    # CRS
    "LocalEngineeringCompoundCrs": "osdu:wks:work-product-component--LocalModelCompoundCrs:1.2.0",
    "LocalDepth3dCrs": "osdu:wks:work-product-component--LocalModelCompoundCrs:1.2.0",
    "LocalTime3dCrs": "osdu:wks:work-product-component--LocalModelCompoundCrs:1.2.0",

    # Metadata-only (no catalog record)
    "MdDatum": None,
    "PropertyKind": None,
    "TimeSeries": None,
    "EpcExternalPartReference": None,
}

# RESQML 2.0.1 → 2.2 type name conversion (for --from-201 mode)
RESQML201_TO_22 = {
    "GeneticBoundaryFeature": "BoundaryFeature",
    "TectonicBoundaryFeature": "BoundaryFeature",
    "OrganizationFeature": "Model",
    "StratigraphicUnitFeature": "RockVolumeFeature",
    "LocalDepth3dCrs": "LocalEngineeringCompoundCrs",
    "LocalTime3dCrs": "LocalEngineeringCompoundCrs",
    # Types that keep the same name in 2.2:
    "HorizonInterpretation": "HorizonInterpretation",
    "FaultInterpretation": "FaultInterpretation",
    "StructuralOrganizationInterpretation": "StructuralOrganizationInterpretation",
    "WellboreFeature": "WellboreFeature",
    "WellboreInterpretation": "WellboreInterpretation",
    "WellboreTrajectoryRepresentation": "WellboreTrajectoryRepresentation",
    "WellboreFrameRepresentation": "WellboreFrameRepresentation",
    "WellboreMarkerFrameRepresentation": "WellboreMarkerFrameRepresentation",
    "IjkGridRepresentation": "IjkGridRepresentation",
    "Grid2dRepresentation": "Grid2dRepresentation",
    "ContinuousProperty": "ContinuousProperty",
    "DiscreteProperty": "DiscreteProperty",
    "PolylineSetRepresentation": "PolylineSetRepresentation",
    "PointSetRepresentation": "PointSetRepresentation",
    "StratigraphicColumn": "StratigraphicColumn",
    "StratigraphicColumnRankInterpretation": "StratigraphicColumnRankInterpretation",
    "StratigraphicUnitInterpretation": "StratigraphicUnitInterpretation",
    "DeviationSurveyRepresentation": "WellboreTrajectoryRepresentation",
}


# ═══════════════════════════════════════════════════════════════════════════
# Parse EPC (supports both 2.0.1 and 2.2 internal naming)
# ═══════════════════════════════════════════════════════════════════════════

def parse_epc(epc_path: Path, convert_from_201: bool = False) -> dict:
    """Parse all objects from EPC into structured inventory."""
    objects = {}
    with zipfile.ZipFile(epc_path, "r") as zf:
        for name in sorted(zf.namelist()):
            if not name.endswith(".xml") or name.startswith("[") or name.startswith("_rels"):
                continue

            # RESQML 2.2: ClassName_uuid.xml (no obj_ prefix)
            # RESQML 2.0.1: obj_ClassName_uuid.xml
            m = re.match(r"(?:obj_)?([A-Za-z0-9]+)_([0-9a-f-]+)\.xml", name)
            if not m:
                continue
            rtype, obj_uuid = m.group(1), m.group(2)

            # Convert 2.0.1 type names to 2.2 equivalents
            if convert_from_201:
                rtype = RESQML201_TO_22.get(rtype, rtype)

            content = zf.read(name).decode("utf-8")

            # EML 2.3 citation (RESQML 2.2) or EML 2.0 citation (2.0.1)
            title = _extract(r"<eml\d*:Title[^>]*>([^<]+)</eml\d*:Title>", content, "")
            if not title:
                title = _extract(r"<Citation>.*?<Title>([^<]+)</Title>", content, "", re.S)
            description = _extract(r"<eml\d*:Description[^>]*>([^<]+)</eml\d*:Description>", content, "")
            originator = _extract(r"<eml\d*:Originator[^>]*>([^<]+)</eml\d*:Originator>", content, "")
            creation = _extract(r"<eml\d*:Creation[^>]*>([^<]+)</eml\d*:Creation>", content, "")

            # RESQML 2.2 uses GeologicBoundaryKind for horizon/fault distinction
            boundary_kind = _extract(
                r"<resqml22:GeologicBoundaryKind[^>]*>([^<]+)</resqml22:GeologicBoundaryKind>",
                content, None)
            # Fallback for 2.0.1 type-based distinction
            if not boundary_kind and convert_from_201:
                orig_type = None
                m2 = re.match(r"obj_([A-Za-z0-9]+)_", name)
                if m2:
                    orig_type = m2.group(1)
                if orig_type == "GeneticBoundaryFeature":
                    boundary_kind = "horizon"
                elif orig_type == "TectonicBoundaryFeature":
                    boundary_kind = "fault"

            # Relationships
            # RESQML 2.0.1: InterpretedFeature / RepresentedInterpretation
            # RESQML 2.2:   RepresentedObject (unified)
            interp_uuid = _extract(
                r"(?:InterpretedFeature|RepresentedInterpretation|RepresentedObject).*?<eml\d*:(?:UUID|Uuid)[^>]*>([^<]+)</eml\d*:(?:UUID|Uuid)>",
                content, None, re.S)
            if not interp_uuid:
                interp_uuid = _extract(
                    r"(?:InterpretedFeature|RepresentedInterpretation|RepresentedObject).*?uuid=\"([^\"]+)\"",
                    content, None, re.S)
            interp_title = _extract(
                r"(?:RepresentedInterpretation|RepresentedObject).*?<eml\d*:Title[^>]*>([^<]+)</eml\d*:Title>",
                content, None, re.S)
            crs_uuid = _extract(
                r"(?:LocalCrs|Crs).*?<eml\d*:(?:UUID|Uuid)[^>]*>([^<]+)</eml\d*:(?:UUID|Uuid)>", content, None, re.S)
            support_uuid = _extract(
                r"SupportingRepresentation.*?<eml\d*:(?:UUID|Uuid)[^>]*>([^<]+)</eml\d*:(?:UUID|Uuid)>", content, None, re.S)

            # Grid2d geometry
            fast_axis = _extract(r"<resqml\d*:FastestAxisCount[^>]*>(\d+)<", content, None)
            slow_axis = _extract(r"<resqml\d*:SlowestAxisCount[^>]*>(\d+)<", content, None)
            grid_origin = None
            grid_spacing = None
            if fast_axis:
                ox = _extract(r"<resqml\d*:Origin[^>]*>.*?<resqml\d*:Coordinate1[^>]*>([^<]+)", content, None, re.S)
                oy = _extract(r"<resqml\d*:Origin[^>]*>.*?<resqml\d*:Coordinate2[^>]*>([^<]+)", content, None, re.S)
                if ox and oy:
                    grid_origin = (float(ox), float(oy))
                spacings = re.findall(r"<resqml\d*:Spacing[^>]*>.*?<resqml\d*:Value[^>]*>([^<]+)", content, re.S)
                if spacings:
                    grid_spacing = [float(s) for s in spacings[:2]]

            # Properties
            uom = _extract(r"<resqml\d*:UOM[^>]*>([^<]+)</resqml\d*:UOM>", content, None)
            if not uom:
                uom = _extract(r"<eml\d*:Uom[^>]*>([^<]+)</eml\d*:Uom>", content, None)
            std_kind = _extract(r"<resqml\d*:Kind[^>]*>([^<]+)</resqml\d*:Kind>", content, None)
            indexable = _extract(r"<resqml\d*:IndexableElement[^>]*>([^<]+)</resqml\d*:IndexableElement>", content, None)
            min_val = _extract(r"<resqml\d*:MinimumValue[^>]*>([^<]+)</resqml\d*:MinimumValue>", content, None)
            max_val = _extract(r"<resqml\d*:MaximumValue[^>]*>([^<]+)</resqml\d*:MaximumValue>", content, None)

            # ExtraMetadata
            extra = {}
            for em in re.finditer(r"<resqml\d*:Name[^>]*>([^<]+)</resqml\d*:Name>\s*<resqml\d*:Value[^>]*>([^<]+)</resqml\d*:Value>", content):
                extra[em.group(1)] = em.group(2)

            objects[obj_uuid] = {
                "type": rtype, "uuid": obj_uuid, "title": title,
                "description": description, "originator": originator,
                "creation": creation, "boundary_kind": boundary_kind,
                "interp_uuid": interp_uuid, "interp_title": interp_title,
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
# Build OSDU records – RESQML 2.2 variant
# ═══════════════════════════════════════════════════════════════════════════

def _base_record(obj_uuid: str, kind: str, name: str, description: str = "",
                 creation: str = "2026-05-20T10:00:00.000Z") -> dict:
    return {
        "id": f"{PARTITION}:{kind.replace('osdu:wks:', '')}:{obj_uuid}",
        "kind": kind,
        "acl": {"owners": OWNERS, "viewers": VIEWERS},
        "legal": {
            "legaltags": [LEGAL_TAG],
            "otherRelevantDataCountries": COUNTRIES,
            "status": "compliant",
        },
        "createTime": creation or "2026-05-20T10:00:00.000Z",
        "modifyTime": creation or "2026-05-20T10:00:00.000Z",
        "createUser": "Drogon Demo RESQML 2.2 (Equinor)",
        "modifyUser": "Drogon Demo RESQML 2.2 (Equinor)",
        "version": 1,
        "data": {
            "Name": name,
            "Description": description or f"{name} - Drogon field (RESQML 2.2)",
            "ExistenceKind": "osdu:reference-data--ExistenceKind:Prototype:",
        },
    }


def _ddms_uri(rtype: str, obj_uuid: str) -> str:
    """RESQML 2.2 DDMS URI (no obj_ prefix)."""
    return f"{DDMS_URI}/resqml22.{rtype}({obj_uuid})"


def _wpc_id(kind_short: str, obj_uuid: str) -> str:
    return f"{PARTITION}:work-product-component--{kind_short}:{obj_uuid}:"


def _md_id(kind_short: str, obj_uuid: str) -> str:
    return f"{PARTITION}:master-data--{kind_short}:{obj_uuid}:"


def build_manifest(objects: dict) -> dict:
    """Build comprehensive OSDU manifest from parsed EPC objects."""

    by_type = defaultdict(list)
    for obj in objects.values():
        by_type[obj["type"]].append(obj)

    # Reverse indices
    interp_to_reprs = defaultdict(list)
    for obj in objects.values():
        if obj["interp_uuid"] and obj["type"].endswith("Representation"):
            interp_to_reprs[obj["interp_uuid"]].append(obj["uuid"])

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
        DATASPACE, f"RDDMS dataspace for Drogon RESQML 2.2 demo")
    ds_rec["data"]["DatasetProperties"] = {"URI": f"eml:///dataspace('{DATASPACE}')"}
    ds_rec["data"]["ResqmlVersion"] = "2.2"
    datasets.append(ds_rec)
    ds_id = ds_rec["id"]

    # ── CRS (RESQML 2.2: LocalEngineeringCompoundCrs) ──
    depth_crs_id = None
    time_crs_id = None
    crs_types = ["LocalEngineeringCompoundCrs", "LocalDepth3dCrs", "LocalTime3dCrs"]
    for ctype in crs_types:
        for obj in by_type.get(ctype, []):
            rec = _base_record(obj["uuid"],
                               "osdu:wks:work-product-component--LocalModelCompoundCrs:1.2.0",
                               obj["title"], obj["description"])
            rec["data"]["DDMSDatasets"] = [_ddms_uri(ctype, obj["uuid"])]
            rec["data"]["DatasetIDs"] = [ds_id]
            is_time = "Time" in ctype or "time" in obj.get("title", "").lower()
            rec["data"]["VerticalDomain"] = "time" if is_time else "depth"
            rec["data"]["ProjectedCrsName"] = "ED50 / UTM zone 31N"
            rec["data"]["VerticalCrsName"] = "TWT (ms)" if is_time else "MSL (m)"
            wpcs.append(rec)
            crs_id = _wpc_id("LocalModelCompoundCrs:1.2.0", obj["uuid"])
            if is_time:
                time_crs_id = crs_id
            else:
                depth_crs_id = crs_id

    # ── Shared BinGrid ──
    bingrid_id = None
    grid2d_objs = by_type.get("Grid2dRepresentation", [])
    if grid2d_objs:
        ref = grid2d_objs[0]
        if ref.get("fast_axis") and ref.get("slow_axis") and ref.get("grid_origin"):
            bingrid_uuid = str(uuid_mod.uuid5(uuid_mod.NAMESPACE_DNS, f"{DATASPACE}/bingrid"))
            bingrid_id = _wpc_id("GenericBinGrid:1.0.0", bingrid_uuid)
            rec = _base_record(bingrid_uuid,
                               "osdu:wks:work-product-component--GenericBinGrid:1.0.0",
                               "Drogon Surface Grid (shared lattice)",
                               "Shared regular grid for all depth and time surfaces")
            rec["data"]["DatasetIDs"] = [ds_id]
            rec["data"]["CoordinateReferenceSystemID"] = depth_crs_id
            rec["data"]["NodeCountOnIAxis"] = ref["fast_axis"]
            rec["data"]["NodeCountOnJAxis"] = ref["slow_axis"]
            rec["data"]["IncrementOnIAxis"] = ref["grid_spacing"][0] if ref.get("grid_spacing") else 25.0
            rec["data"]["IncrementOnJAxis"] = ref["grid_spacing"][1] if ref.get("grid_spacing") and len(ref["grid_spacing"]) > 1 else 25.0
            rec["data"]["OriginX"] = ref["grid_origin"][0]
            rec["data"]["OriginY"] = ref["grid_origin"][1]
            wpcs.append(rec)

    # ── BoundaryFeature → LocalBoundaryFeature (1:1 in RESQML 2.2!) ──
    for obj in by_type.get("BoundaryFeature", []):
        rec = _base_record(obj["uuid"],
                           "osdu:wks:master-data--LocalBoundaryFeature:1.1.0",
                           obj["title"], obj["description"])
        # In RESQML 2.2 the kind is an attribute, not encoded in the type name
        bkind = (obj.get("boundary_kind") or "").lower()
        if "fault" in bkind or "tectonic" in bkind:
            rec["data"]["BoundaryType"] = "fault"
        else:
            rec["data"]["BoundaryType"] = "horizon"
        rec["data"]["DDMSDatasets"] = [_ddms_uri("BoundaryFeature", obj["uuid"])]
        rec["data"]["FieldNames"] = ["Drogon"]
        master_data.append(rec)

    # ── WellboreFeature → Wellbore (1:1) ──
    for obj in by_type.get("WellboreFeature", []):
        rec = _base_record(obj["uuid"],
                           "osdu:wks:master-data--Wellbore:1.3.0",
                           obj["title"], f"Wellbore {obj['title']} - Drogon field")
        rec["data"]["DDMSDatasets"] = [_ddms_uri("WellboreFeature", obj["uuid"])]
        rec["data"]["FieldNames"] = ["Drogon"]
        rec["data"]["Basin"] = "Norwegian Continental Shelf"
        for wi in by_type.get("WellboreInterpretation", []):
            if wi["interp_uuid"] == obj["uuid"]:
                rec["data"]["WellboreInterpretationID"] = _ddms_uri("WellboreInterpretation", wi["uuid"])
                break
        master_data.append(rec)

    # ── HorizonInterpretation (1:1) ──
    for obj in by_type.get("HorizonInterpretation", []):
        rec = _base_record(obj["uuid"],
                           "osdu:wks:work-product-component--HorizonInterpretation:1.2.0",
                           obj["title"], obj["description"])
        rec["data"]["DDMSDatasets"] = [_ddms_uri("HorizonInterpretation", obj["uuid"])]
        rec["data"]["DatasetIDs"] = [ds_id]
        rec["data"]["DomainTypeID"] = "osdu:reference-data--DomainType:Mixed:"
        rec["data"]["StratigraphicRoleTypeID"] = "osdu:reference-data--StratigraphicRoleType:Chronostratigraphic:"
        if obj["interp_uuid"]:
            rec["data"]["InterpretedBoundaryFeatureID"] = _md_id("LocalBoundaryFeature:1.1.0", obj["interp_uuid"])
        repr_ids = interp_to_reprs.get(obj["uuid"], [])
        if repr_ids:
            rec["data"]["RepresentationIDs"] = [_wpc_id("GenericRepresentation:1.2.0", rid) for rid in repr_ids]
        wpcs.append(rec)

    # ── FaultInterpretation (1:1) ──
    for obj in by_type.get("FaultInterpretation", []):
        rec = _base_record(obj["uuid"],
                           "osdu:wks:work-product-component--FaultInterpretation:1.3.0",
                           obj["title"], obj["description"])
        rec["data"]["DDMSDatasets"] = [_ddms_uri("FaultInterpretation", obj["uuid"])]
        rec["data"]["DatasetIDs"] = [ds_id]
        if obj["interp_uuid"]:
            rec["data"]["InterpretedBoundaryFeatureID"] = _md_id("LocalBoundaryFeature:1.1.0", obj["interp_uuid"])
        repr_ids = interp_to_reprs.get(obj["uuid"], [])
        if repr_ids:
            rec["data"]["RepresentationIDs"] = [_wpc_id("GenericRepresentation:1.2.0", rid) for rid in repr_ids]
        wpcs.append(rec)

    # ── StructuralOrganizationInterpretation → StructuralModel ──
    for obj in by_type.get("StructuralOrganizationInterpretation", []):
        rec = _base_record(obj["uuid"],
                           "osdu:wks:work-product-component--StructuralModel:1.0.0",
                           obj["title"], obj["description"])
        rec["data"]["DDMSDatasets"] = [_ddms_uri("StructuralOrganizationInterpretation", obj["uuid"])]
        rec["data"]["DatasetIDs"] = [ds_id]
        if obj["interp_uuid"]:
            rec["data"]["InterpretedFeatureID"] = _wpc_id("LocalModelFeature:1.2.0", obj["interp_uuid"])
        rec["data"]["FaultInterpretationIDs"] = [
            _wpc_id("FaultInterpretation:1.3.0", f["uuid"])
            for f in by_type.get("FaultInterpretation", [])
        ]
        rec["data"]["HorizonInterpretationIDs"] = [
            _wpc_id("HorizonInterpretation:1.2.0", h["uuid"])
            for h in by_type.get("HorizonInterpretation", [])
        ]
        wpcs.append(rec)

    # ── Model → LocalModelFeature (1:1 in 2.2) ──
    for obj in by_type.get("Model", []):
        rec = _base_record(obj["uuid"],
                           "osdu:wks:work-product-component--LocalModelFeature:1.2.0",
                           obj["title"], obj["description"])
        rec["data"]["DDMSDatasets"] = [_ddms_uri("Model", obj["uuid"])]
        rec["data"]["DatasetIDs"] = [ds_id]
        wpcs.append(rec)

    # ── Grid2d → StructureMap (depth) or SeismicHorizon (time) ──
    # First pass: build lookup of interp_uuid → SeismicHorizon record ID
    # so StructureMaps can reference their TWT counterpart via SeismicHorizonID.
    interp_to_seishorizon: dict[str, str] = {}  # interp_uuid → SeismicHorizon WPC id
    for obj in grid2d_objs:
        crs_id = depth_crs_id
        if obj.get("crs_uuid"):
            crs_obj = objects.get(obj["crs_uuid"])
            if crs_obj and "Time" in crs_obj.get("type", ""):
                crs_id = time_crs_id
        if crs_id == time_crs_id and obj["interp_uuid"]:
            interp_to_seishorizon[obj["interp_uuid"]] = _wpc_id("SeismicHorizon:2.1.0", obj["uuid"])

    for obj in grid2d_objs:
        crs_id = depth_crs_id
        if obj.get("crs_uuid"):
            crs_obj = objects.get(obj["crs_uuid"])
            if crs_obj and "Time" in crs_obj.get("type", ""):
                crs_id = time_crs_id
        is_time = crs_id == time_crs_id

        if is_time:
            kind = "osdu:wks:work-product-component--SeismicHorizon:2.1.0"
        else:
            kind = "osdu:wks:work-product-component--StructureMap:1.0.0"

        horizon_name = obj.get("interp_title") or ""
        name = f"{obj['title']} ({horizon_name})" if horizon_name else obj["title"]

        rec = _base_record(obj["uuid"], kind, name, obj["description"])
        rec["data"]["DDMSDatasets"] = [_ddms_uri("Grid2dRepresentation", obj["uuid"])]
        rec["data"]["DatasetIDs"] = [ds_id]
        rec["data"]["CoordinateReferenceSystemID"] = crs_id
        rec["data"]["VerticalDomain"] = "time" if is_time else "depth"
        if obj["interp_uuid"]:
            rec["data"]["InterpretedHorizonID"] = _wpc_id("HorizonInterpretation:1.2.0", obj["interp_uuid"])
        # StructureMap → SeismicHorizon cross-reference (depth surface links to its TWT counterpart)
        if not is_time and obj["interp_uuid"] and obj["interp_uuid"] in interp_to_seishorizon:
            rec["data"]["SeismicHorizonID"] = interp_to_seishorizon[obj["interp_uuid"]]
        if bingrid_id:
            rec["data"]["BinGridID"] = bingrid_id
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
            rec["data"]["DDMSDatasets"] = [_ddms_uri(rtype, obj["uuid"])]
            rec["data"]["DatasetIDs"] = [ds_id]
            rec["data"]["CoordinateReferenceSystemID"] = depth_crs_id
            if obj["interp_uuid"]:
                rec["data"]["InterpretationID"] = _wpc_id("FaultInterpretation:1.3.0", obj["interp_uuid"])
            rec["data"]["RepresentationType"] = "PolylineSet" if "Polyline" in rtype else "PointSet"
            wpcs.append(rec)

    # ── IjkGrid ──
    for obj in by_type.get("IjkGridRepresentation", []):
        rec = _base_record(obj["uuid"],
                           "osdu:wks:work-product-component--IjkGridRepresentation:1.1.0",
                           obj["title"], obj["description"])
        rec["data"]["DDMSDatasets"] = [_ddms_uri("IjkGridRepresentation", obj["uuid"])]
        rec["data"]["DatasetIDs"] = [ds_id]
        rec["data"]["CoordinateReferenceSystemID"] = depth_crs_id
        rec["data"]["Ni"] = 92
        rec["data"]["Nj"] = 146
        rec["data"]["Nk"] = 69
        rec["data"]["CellCount"] = 925668
        wpcs.append(rec)

    # ── Grid Properties → GenericProperty ──
    ijk_uuid = by_type["IjkGridRepresentation"][0]["uuid"] if by_type.get("IjkGridRepresentation") else None
    for prop_type in ("ContinuousProperty", "DiscreteProperty", "CategoricalProperty"):
        for obj in by_type.get(prop_type, []):
            if obj["support_uuid"] != ijk_uuid:
                continue
            rec = _base_record(obj["uuid"],
                               "osdu:wks:work-product-component--GenericProperty:1.2.0",
                               obj["title"], obj["description"])
            rec["data"]["DDMSDatasets"] = [_ddms_uri(prop_type, obj["uuid"])]
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

    # ── WellboreTrajectory ──
    for obj in by_type.get("WellboreTrajectoryRepresentation", []):
        well_name = _resolve_well_name(obj, objects, by_type)
        traj_name = f"{obj['title']} ({well_name})" if well_name else obj["title"]
        rec = _base_record(obj["uuid"],
                           "osdu:wks:work-product-component--WellboreTrajectory:1.3.0",
                           traj_name, f"Trajectory for {well_name or obj['title']}")
        rec["data"]["DDMSDatasets"] = [_ddms_uri("WellboreTrajectoryRepresentation", obj["uuid"])]
        rec["data"]["DatasetIDs"] = [ds_id]
        rec["data"]["CoordinateReferenceSystemID"] = depth_crs_id
        if obj["interp_uuid"]:
            wi = objects.get(obj["interp_uuid"])
            if wi and wi["interp_uuid"]:
                rec["data"]["WellboreID"] = _md_id("Wellbore:1.3.0", wi["interp_uuid"])
        wpcs.append(rec)

    # ── WellLog (WellboreFrame + curves) ──
    for obj in by_type.get("WellboreFrameRepresentation", []):
        well_name = _resolve_well_name(obj, objects, by_type)
        log_name = f"Well Log ({well_name})" if well_name else f"Well Log - {obj['title']}"
        rec = _base_record(obj["uuid"],
                           "osdu:wks:work-product-component--WellLog:1.2.0",
                           log_name, f"Log curves on {well_name or obj['title']}")
        rec["data"]["DDMSDatasets"] = [_ddms_uri("WellboreFrameRepresentation", obj["uuid"])]
        rec["data"]["DatasetIDs"] = [ds_id]
        if obj["interp_uuid"]:
            wi = objects.get(obj["interp_uuid"])
            if wi and wi["interp_uuid"]:
                rec["data"]["WellboreID"] = _md_id("Wellbore:1.3.0", wi["interp_uuid"])
        curve_uuids = repr_to_props.get(obj["uuid"], [])
        rec["data"]["CurveCount"] = len(curve_uuids)
        curves = []
        for cuuid in curve_uuids:
            prop = objects.get(cuuid)
            if prop:
                curves.append({
                    "CurveName": prop["title"],
                    "PropertyKind": prop.get("std_kind") or "",
                    "UoM": prop.get("uom") or "",
                })
        rec["data"]["Curves"] = curves
        wpcs.append(rec)

    # ── WellboreMarkerSet ──
    for obj in by_type.get("WellboreMarkerFrameRepresentation", []):
        well_name = _resolve_well_name(obj, objects, by_type)
        rec = _base_record(obj["uuid"],
                           "osdu:wks:work-product-component--WellboreMarkerSet:1.2.0",
                           f"Markers ({well_name})" if well_name else obj["title"],
                           f"Wellbore markers on {well_name or obj['title']}")
        rec["data"]["DDMSDatasets"] = [_ddms_uri("WellboreMarkerFrameRepresentation", obj["uuid"])]
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
        rec["data"]["DDMSDatasets"] = [_ddms_uri("StratigraphicColumn", obj["uuid"])]
        rec["data"]["DatasetIDs"] = [ds_id]
        wpcs.append(rec)

    for obj in by_type.get("StratigraphicColumnRankInterpretation", []):
        rec = _base_record(obj["uuid"],
                           "osdu:wks:work-product-component--StratigraphicColumnRankInterpretation:1.3.0",
                           obj["title"], obj["description"])
        rec["data"]["DDMSDatasets"] = [_ddms_uri("StratigraphicColumnRankInterpretation", obj["uuid"])]
        rec["data"]["DatasetIDs"] = [ds_id]
        wpcs.append(rec)

    # ── RockVolumeFeature → LocalRockVolumeFeature (1:1 in 2.2!) ──
    for obj in by_type.get("RockVolumeFeature", []):
        rec = _base_record(obj["uuid"],
                           "osdu:wks:work-product-component--LocalRockVolumeFeature:1.2.0",
                           obj["title"], obj["description"])
        rec["data"]["DDMSDatasets"] = [_ddms_uri("RockVolumeFeature", obj["uuid"])]
        rec["data"]["DatasetIDs"] = [ds_id]
        wpcs.append(rec)

    for obj in by_type.get("StratigraphicUnitInterpretation", []):
        rec = _base_record(obj["uuid"],
                           "osdu:wks:work-product-component--StratigraphicUnitInterpretation:1.3.0",
                           obj["title"], obj["description"])
        rec["data"]["DDMSDatasets"] = [_ddms_uri("StratigraphicUnitInterpretation", obj["uuid"])]
        rec["data"]["DatasetIDs"] = [ds_id]
        if obj["interp_uuid"]:
            rec["data"]["InterpretedFeatureID"] = _wpc_id("LocalRockVolumeFeature:1.2.0", obj["interp_uuid"])
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


def _resolve_well_name(obj: dict, objects: dict, by_type: dict) -> str | None:
    """Resolve well name from Trajectory/Frame → WellboreInterpretation → WellboreFeature chain."""
    if obj["interp_uuid"]:
        wi = objects.get(obj["interp_uuid"])
        if wi and wi["interp_uuid"]:
            wf = objects.get(wi["interp_uuid"])
            if wf:
                return wf["title"]
    return None


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(description="Build OSDU manifest from Drogon RESQML 2.2 EPC")
    ap.add_argument("--from-201", action="store_true",
                    help="Convert from RESQML 2.0.1 EPC (demo/drogonresqml/drogon_demo.epc)")
    ap.add_argument("--epc", type=Path, default=None,
                    help="Explicit source EPC path (overrides default 2.2 EPC)")
    ap.add_argument("--save-only", action="store_true",
                    help="Save manifest JSON only (don't push)")
    ap.add_argument("-o", "--output", type=Path, default=OUT_FILE,
                    help=f"Output path (default: {OUT_FILE.name})")
    args = ap.parse_args()

    # Select source EPC
    if args.from_201:
        epc = EPC_FILE_201
        convert = True
        print(f"  Source: {epc.name} (RESQML 2.0.1 → converting to 2.2 types)")
    elif args.epc:
        epc = args.epc
        convert = False
        print(f"  Source: {epc.name} (RESQML 2.2 native, explicit)")
    else:
        epc = EPC_FILE_22
        convert = False
        print(f"  Source: {epc.name} (RESQML 2.2 native)")

    if not epc.exists():
        sys.exit(f"  ✗ EPC not found: {epc}")

    print(f"  Target dataspace: {DATASPACE}")
    print(f"  Output: {args.output.name}")
    print()

    # Parse
    objects = parse_epc(epc, convert_from_201=convert)
    print(f"  Parsed {len(objects)} objects from EPC")

    # Count by type
    from collections import Counter
    type_counts = Counter(obj["type"] for obj in objects.values())
    for t, c in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f"    {t}: {c}")
    print()

    # Build manifest
    manifest = build_manifest(objects)

    # Summary
    data = manifest["Data"]
    total = sum(len(v) for v in data.values() if isinstance(v, list))
    print(f"  Built {total} OSDU records:")
    for section, records in data.items():
        if isinstance(records, list) and records:
            print(f"    {section}: {len(records)}")

    # Save
    args.output.write_text(json.dumps(manifest, indent=2))
    size_kb = args.output.stat().st_size / 1024
    print(f"\n  ✓ Saved: {args.output.name} ({size_kb:.0f} KB)")


if __name__ == "__main__":
    main()
