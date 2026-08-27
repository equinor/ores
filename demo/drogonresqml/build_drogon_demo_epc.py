#!/usr/bin/env python3
"""
build_drogon_demo_epc.py – Build a curated Drogon demo EPC containing
all object types but pruned of redundant map artefacts.

Uses resqml_v201_sanitizer for proper XML sanitization via lxml.
This script handles EPC-level concerns: object selection, zip packaging,
Content_Types.xml, .rels files, HDF5 subsetting, JSON record export.

Usage:
    python build_drogon_demo_epc.py
"""
from __future__ import annotations

import base64
import json
import re
import sys
import zipfile
from collections import Counter
from io import BytesIO
from pathlib import Path

import h5py
import numpy as np

from resqml_v201_sanitizer import sanitize_object_xml

SCRIPT_DIR = Path(__file__).resolve().parent
SRC_EPC = SCRIPT_DIR / "drogon_demo_repackaged_geosiris.epc"
SRC_H5 = SCRIPT_DIR / "drogon.h5"
OUT_EPC = SCRIPT_DIR / "drogon.epc"
OUT_H5 = SCRIPT_DIR / "drogon.h5"
OUT_JSON = SCRIPT_DIR / "drogon_records.json"

# Regex helpers
H5_PATH_RE = re.compile(r"<eml:PathInHdfFile[^>]*>([^<]+)</eml:PathInHdfFile>")
UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)

# ── Object selection rules ──────────────────────────────────────────────── #

ALWAYS_INCLUDE_TYPES = [
    "IjkGridRepresentation",
    "WellboreFeature",
    "WellboreInterpretation",
    "WellboreTrajectoryRepresentation",
    "DeviationSurveyRepresentation",
    "MdDatum",
    "WellboreFrameRepresentation",
    "WellboreMarkerFrameRepresentation",
    "ContinuousProperty",
    "DiscreteProperty",
    "GeneticBoundaryFeature",
    "HorizonInterpretation",
    "TectonicBoundaryFeature",
    "FaultInterpretation",
    "PolylineSetRepresentation",
    "StratigraphicColumn",
    "StratigraphicColumnRankInterpretation",
    "StratigraphicUnitFeature",
    "StratigraphicUnitInterpretation",
    "OrganizationFeature",
    "StructuralOrganizationInterpretation",
    "Activity",
    "ActivityTemplate",
    "LocalDepth3dCrs",
    "LocalTime3dCrs",
    "EpcExternalPartReference",
]

GRID2D_KEEP_TITLES = ["Interpreted", "Velocity Model"]
GRID2D_SKIP_TITLES = ["Geogrid Extract"]

POINTSET_KEEP_PATTERNS = [
    "Interpreted",
    "Extracted Fault",
    "Truth Model",
    "Time Points",
]
POINTSET_SKIP_PATTERNS = [
    "HUM Geophysics",
    "HUM Post-Iterate",
    "Filtered",
]


# ── Helpers ──────────────────────────────────────────────────────────────── #

def _get_title(content: str) -> str:
    m = re.search(r"<eml:Title[^>]*>([^<]+)</eml:Title>", content)
    return m.group(1) if m else ""


def _get_uuid(filename: str) -> str | None:
    m = UUID_RE.search(filename)
    return m.group(0) if m else None


def _get_obj_type(filename: str) -> str:
    m = re.match(r"obj_([A-Za-z0-9]+)_", filename)
    return m.group(1) if m else ""


def should_include(filename: str, content: str) -> bool:
    """Decide whether to include this object in the demo EPC."""
    obj_type = _get_obj_type(filename)

    if obj_type in ALWAYS_INCLUDE_TYPES:
        return True

    if obj_type == "Grid2dRepresentation":
        title = _get_title(content)
        for skip in GRID2D_SKIP_TITLES:
            if skip in title:
                return False
        for keep in GRID2D_KEEP_TITLES:
            if keep in title:
                return True
        return False

    if obj_type == "PointSetRepresentation":
        title = _get_title(content)
        for keep in POINTSET_KEEP_PATTERNS:
            if keep in title:
                return True
        for skip in POINTSET_SKIP_PATTERNS:
            if skip in title:
                return False
        return False

    return False


# ── EPC packaging ────────────────────────────────────────────────────────── #

def _build_content_types(include_xmls: dict[str, str]) -> str:
    lines = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>']
    lines.append('<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">')
    lines.append('  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>')
    lines.append('  <Default Extension="xml" ContentType="application/xml"/>')

    for name in sorted(include_xmls):
        m = re.match(r"obj_([A-Za-z0-9]+)_", name)
        if m:
            obj_type = m.group(1)
            if obj_type == "EpcExternalPartReference":
                ct = "application/x-eml+xml;version=2.0;type=obj_EpcExternalPartReference"
            else:
                ct = f"application/x-resqml+xml;version=2.0;type=obj_{obj_type}"
            lines.append(f'  <Override PartName="/{name}" ContentType="{ct}"/>')

    lines.append("</Types>")
    return "\n".join(lines)


def _build_root_rels(include_xmls: dict[str, str]) -> str:
    lines = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>']
    lines.append('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">')

    for i, name in enumerate(sorted(include_xmls), 1):
        m = re.match(r"obj_([A-Za-z0-9]+)_", name)
        obj_type = m.group(1) if m else "Unknown"
        if obj_type == "EpcExternalPartReference":
            rel_type = "http://schemas.energistics.org/package/2012/relationships/externalResource"
        else:
            rel_type = "http://schemas.energistics.org/package/2012/relationships/destinationObject"
        lines.append(f'  <Relationship Id="rId{i}" Type="{rel_type}" Target="{name}"/>')

    lines.append("</Relationships>")
    return "\n".join(lines)


def _build_subset_h5(h5_paths: set[str]):
    if not SRC_H5.exists():
        print(f"  WARNING: Source H5 not found ({SRC_H5}), skipping")
        return

    # Use a temp file to avoid truncating the source when SRC == OUT
    tmp_h5 = OUT_H5.with_suffix(".h5.tmp")
    with h5py.File(SRC_H5, "r") as src_h5, h5py.File(tmp_h5, "w") as dst_h5:
        copied = 0
        missing = 0
        for path in sorted(h5_paths):
            if path in src_h5:
                parent = "/".join(path.split("/")[:-1])
                if parent and parent not in dst_h5:
                    dst_h5.require_group(parent)
                src_h5.copy(src_h5[path], dst_h5, name=path)
                copied += 1
            else:
                missing += 1
        print(f"  Copied {copied}/{len(h5_paths)} H5 datasets ({missing} missing)")
    tmp_h5.replace(OUT_H5)


# ── Main build ────────────────────────────────────────────────────────────── #

def build_demo_epc():
    """Build the curated demo EPC."""
    print(f"Reading source EPC: {SRC_EPC}")
    with zipfile.ZipFile(SRC_EPC, "r") as src:
        all_names = src.namelist()

        # 1. Filter objects
        include_xmls: dict[str, str] = {}
        skip_log = []
        for name in all_names:
            if not name.endswith(".xml") or "obj_" not in name or "/_rels/" in name:
                continue
            flat_name = name.split("/")[-1]
            if not flat_name.startswith("obj_"):
                continue
            content = src.read(name).decode("utf-8")
            if should_include(flat_name, content):
                include_xmls[flat_name] = name
            else:
                skip_log.append((_get_obj_type(flat_name), _get_title(content)))

        # 2. Collect .rels
        include_rels: dict[str, str] = {}
        for flat_name, zip_path in include_xmls.items():
            prefix = zip_path.rsplit("/", 1)[0] + "/" if "/" in zip_path else ""
            rel_name = f"{prefix}_rels/{flat_name}.rels"
            if rel_name in all_names:
                include_rels[f"_rels/{flat_name}.rels"] = rel_name

        # 3. Collect H5 paths
        h5_paths: set[str] = set()
        for flat_name, zip_path in include_xmls.items():
            content = src.read(zip_path).decode("utf-8")
            for path in H5_PATH_RE.findall(content):
                h5_paths.add(path)

        # Summary
        type_counts: Counter = Counter()
        for name in include_xmls:
            type_counts[_get_obj_type(name)] += 1

        print(f"\n  Included objects: {len(include_xmls)}")
        for t, c in sorted(type_counts.items()):
            print(f"    {t:45s} {c:4d}")
        print(f"  Included .rels:   {len(include_rels)}")
        print(f"  H5 paths needed:  {len(h5_paths)}")

        skip_types = Counter(t for t, _ in skip_log)
        print(f"\n  Excluded: {len(skip_log)} objects")
        for t, c in sorted(skip_types.items()):
            print(f"    {t:45s} {c:4d}")

        # 4. Build packaging files
        content_types_xml = _build_content_types(include_xmls)
        root_rels = _build_root_rels(include_xmls)

        # 5. Write EPC
        print(f"\nWriting demo EPC: {OUT_EPC}")
        with zipfile.ZipFile(OUT_EPC, "w", zipfile.ZIP_DEFLATED) as dst:
            dst.writestr("[Content_Types].xml", content_types_xml)
            dst.writestr("_rels/.rels", root_rels)

            for flat_name in sorted(include_xmls):
                zip_path = include_xmls[flat_name]
                xml_bytes = src.read(zip_path)
                obj_type = _get_obj_type(flat_name)

                # Sanitize XML for XSD compliance
                sanitized = sanitize_object_xml(xml_bytes, obj_type)
                dst.writestr(flat_name, sanitized)

            for flat_rels, zip_rels in sorted(include_rels.items()):
                if "EpcExternalPartReference" in flat_rels:
                    epr_rels = (
                        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
                        f'  <Relationship Id="Hdf5File" Type="http://schemas.energistics.org/package/2012/relationships/externalResource"'
                        f' Target="{OUT_H5.name}" TargetMode="External"/>\n'
                        '</Relationships>'
                    )
                    dst.writestr(flat_rels, epr_rels.encode("utf-8"))
                else:
                    dst.writestr(flat_rels, src.read(zip_rels))

    # 6. Build H5 subset
    print(f"\nBuilding demo H5: {OUT_H5}")
    _build_subset_h5(h5_paths)

    # 7. Verify
    _verify_epc(OUT_EPC)

    return include_xmls, h5_paths


def _verify_epc(epc_path: Path):
    print(f"\nVerifying: {epc_path}")
    with zipfile.ZipFile(epc_path, "r") as zf:
        names = zf.namelist()
        assert "[Content_Types].xml" in names, "Missing [Content_Types].xml"
        assert "_rels/.rels" in names, "Missing _rels/.rels"

        xml_count = sum(1 for n in names if n.endswith(".xml"))
        obj_count = sum(1 for n in names if n.startswith("obj_") and n.endswith(".xml"))

    sz_epc = epc_path.stat().st_size / (1024 * 1024)
    sz_h5 = OUT_H5.stat().st_size / (1024 * 1024) if OUT_H5.exists() else 0
    print(f"  OK - {obj_count} objects, {xml_count} XML parts")
    print(f"  EPC: {sz_epc:.1f} MB, H5: {sz_h5:.1f} MB, Total: {sz_epc + sz_h5:.1f} MB")


def build_json_records(include_xmls: dict[str, str], h5_paths: set[str]):
    """Build JSON RESQML records with embedded arrays."""
    print(f"\n{'='*60}")
    print("Building JSON RESQML records for OpenETPClient")
    print(f"{'='*60}")

    dataspace = "maap/drogon"
    records = []

    with zipfile.ZipFile(OUT_EPC, "r") as zf:
        h5_arrays = {}
        if SRC_H5.exists():
            with h5py.File(SRC_H5, "r") as h5f:
                for path in sorted(h5_paths):
                    if path in h5f:
                        arr = h5f[path][()]
                        h5_arrays[path] = arr

        for name in sorted(include_xmls):
            if "EpcExternalPartReference" in name:
                continue

            content = zf.read(name).decode("utf-8")
            uid = _get_uuid(name)
            if not uid:
                continue

            obj_type = _get_obj_type(name)
            record = {
                "uri": f"eml:///dataspace('{dataspace}')/resqml20.obj_{obj_type}('{uid}')",
                "dataObjectType": f"resqml20.obj_{obj_type}",
                "uuid": uid,
                "title": _get_title(content),
                "xml": content,
            }

            obj_h5_paths = H5_PATH_RE.findall(content)
            if obj_h5_paths:
                arrays = {}
                for h5path in obj_h5_paths:
                    if h5path in h5_arrays:
                        arr = h5_arrays[h5path]
                        arrays[h5path] = {
                            "dtype": str(arr.dtype),
                            "shape": list(arr.shape),
                            "data_b64": base64.b64encode(arr.tobytes()).decode("ascii"),
                        }
                if arrays:
                    record["blobData"] = arrays

            records.append(record)

    output = {
        "dataspace": dataspace,
        "description": "Drogon demo - curated RESQML objects (all types, pruned maps)",
        "objectCount": len(records),
        "objects": records,
    }

    print(f"  Writing {len(records)} records to {OUT_JSON}")
    with open(OUT_JSON, "w") as f:
        json.dump(output, f, indent=2)
    sz = OUT_JSON.stat().st_size / (1024 * 1024)
    print(f"  JSON size: {sz:.1f} MB")

    records_dir = SCRIPT_DIR / "demo_records"
    records_dir.mkdir(exist_ok=True)
    for i, rec in enumerate(records):
        fname = f"{i:03d}_{rec['dataObjectType'].replace('resqml20.obj_','')[:30]}_{rec['uuid'][:8]}.json"
        (records_dir / fname).write_text(json.dumps(rec, indent=2))
    print(f"  Also wrote {len(records)} individual files to {records_dir.name}/")

    return records


def main():
    if not SRC_EPC.exists():
        sys.exit(f"Source EPC not found: {SRC_EPC}")

    include_xmls, h5_paths = build_demo_epc()
    build_json_records(include_xmls, h5_paths)

    print(f"\n{'='*60}")
    print("Done! Files:")
    print(f"  {OUT_EPC.name}")
    print(f"  {OUT_H5.name}")
    print(f"  {OUT_JSON.name}")
    print(f"  demo_records/ ({len(include_xmls)-1} files)")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
