#!/usr/bin/env python3
"""
build_drogon_demo_epc.py – Build a curated Drogon demo EPC containing
all object types but pruned of redundant map artefacts.

Includes:
  - IjkGridRepresentation (Geogrid 92×146×69) + all 32 grid properties
  - 12 wells (Feature, Interpretation, Trajectory, DeviationSurvey, MdDatum)
  - 9 WellboreFrameRepresentation (log frames) + all log properties
  - 9 WellboreMarkerFrameRepresentation (stratigraphic markers)
  - Structural framework (GeneticBoundaryFeature, HorizonInterpretation,
    TectonicBoundaryFeature, FaultInterpretation, OrganizationFeature)
  - StratigraphicColumn + ColumnRankInterpretation + units
  - 6 PolylineSetRepresentation (fault sticks)
  - Grid2d: ONE "Interpreted" depth + time map per horizon (5 of 15)
  - PointSet: "Interpreted" picks + fault extractions (pruned)
  - CRS objects + EpcExternalPartReference

Excluded:
  - Grid2d "Geogrid Extract" (redundant with IjkGrid geometry)
  - Grid2d "Velocity Model" (derived artefact)
  - PointSet "HUM Geophysics" / "HUM Post-Iterate" / "Filtered" (workflow artefacts)

Usage:
    python demo/drogonresqml/build_drogon_demo_epc.py
"""
from __future__ import annotations

import base64
import json
import re
import sys
import zipfile
from io import BytesIO
from pathlib import Path

import h5py
import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
SRC_EPC = SCRIPT_DIR / "drogon_demo_repackaged_geosiris.epc"
SRC_H5 = SCRIPT_DIR / "drogon.h5"
OUT_EPC = SCRIPT_DIR / "drogon.epc"
OUT_H5 = SCRIPT_DIR / "drogon.h5"
OUT_JSON = SCRIPT_DIR / "drogon_records.json"

# Regex
H5_PATH_RE = re.compile(r"<eml:PathInHdfFile[^>]*>([^<]+)</eml:PathInHdfFile>")
UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)

# ── Object type classification ──────────────────────────────────────────── #

# Always include (all instances)
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

# Grid2d: keep "Interpreted" and "Velocity Model", skip "Geogrid Extract" (redundant with IjkGrid)
GRID2D_KEEP_TITLES = ["Interpreted", "Velocity Model"]
GRID2D_SKIP_TITLES = ["Geogrid Extract"]

# PointSet: keep these title patterns
POINTSET_KEEP_PATTERNS = [
    "Interpreted",       # original interpretation picks (depth + time)
    "Extracted Fault",   # fault point extractions (structural)
    "Truth Model",       # reference/truth case
    "Time Points",       # time-domain picks (seismic interpretation)
]
POINTSET_SKIP_PATTERNS = [
    "HUM Geophysics",
    "HUM Post-Iterate",
    "Filtered",
]


def _fix_namespaces(content: str) -> str:
    """Normalize namespace prefixes from geosiris repack format.

    The source EPC uses 'resqml:' prefix and 'obj_' in root element names.
    Normalize to 'resqml2:' prefix and strip 'obj_' from root element opening tag.
    """
    content = content.replace(
        'xmlns:resqml="http://www.energistics.org/energyml/data/resqmlv2"',
        'xmlns:resqml2="http://www.energistics.org/energyml/data/resqmlv2"')
    content = content.replace('xmlns:prodml="http://www.energistics.org/energyml/data/prodmlv2" ', '')
    content = content.replace('xmlns:witsml="http://www.energistics.org/energyml/data/witsmlv2" ', '')
    content = content.replace('<resqml:', '<resqml2:')
    content = content.replace('</resqml:', '</resqml2:')
    content = content.replace('resqml:obj_', 'resqml2:obj_')
    content = content.replace('resqml:Domain', 'resqml2:Domain')
    content = content.replace('resqml:Resqml', 'resqml2:Resqml')
    # Strip obj_ from root element opening tag: <resqml2:obj_TypeName → <resqml2:TypeName
    content = re.sub(r'<resqml2:obj_([A-Za-z0-9]+)', r'<resqml2:\1', content, count=1)
    # Same for eml: namespace (EpcExternalPartReference)
    content = re.sub(r'<eml:obj_([A-Za-z0-9]+)', r'<eml:\1', content, count=1)
    content = re.sub(r'</eml:obj_([A-Za-z0-9]+)>', r'</eml:\1>', content)
    return content


def _sanitize_xml(content: str) -> str:
    """Fix XSD validation issues in RESQML 2.0.1 XML.

    Fixes:
      1. Add xmlns:xsd if used but not declared
      2. Fix Citation element ordering (VersionString must precede Description per XSD sequence)
      3. Replace invalid UOM 'v/v' with 'm3/m3'
      4. Replace invalid PropertyKinds with closest valid enum values
      5. Fix ExtraMetadata position (must come before Count/IndexableElement)
      6. Fix ExtraMetadata values to match corrected UOM/PropertyKind
      7. Remove DisabledMarkers vendor extension (empty uuid violates pattern facet)
      8. Fix StratigraphicColumn in CustomData (use ext: namespace to avoid lax validation)
      9. Add missing Domain element before InterpretedFeature in StructuralOrganizationInterpretation
     10. Fix mismatched obj_ prefix on root element closing tags
     11. Add xsi:type on root element (required by fesapi for object type identification)
    """
    # 10. Fix closing tag obj_ mismatch (from geosiris repack)
    #     Opening: <resqml2:Grid2dRepresentation ...>  Closing: </resqml2:obj_Grid2dRepresentation>
    content = re.sub(
        r'</resqml2:obj_([A-Za-z0-9]+)>\s*$',
        r'</resqml2:\1>',
        content)

    # 1. Add xmlns:xsd if xsd: prefix is used but namespace undeclared
    if 'xsd:' in content and 'xmlns:xsd=' not in content:
        content = content.replace(
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"',
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            'xmlns:xsd="http://www.w3.org/2001/XMLSchema"')

    # 2. Fix Citation element ordering: XSD sequence is
    #    Title, Originator, Creation, Format, Editor?, LastUpdate?, VersionString?, Description?
    #    We must ensure VersionString comes before Description
    def _fix_citation_order(m):
        citation = m.group(0)
        # Extract Description and VersionString if both present
        desc_m = re.search(
            r'(\s*<eml:Description[^>]*>.*?</eml:Description>)', citation, re.DOTALL)
        vers_m = re.search(
            r'(\s*<eml:VersionString[^>]*>.*?</eml:VersionString>)', citation, re.DOTALL)
        if desc_m and vers_m:
            # Check if Description appears before VersionString (wrong order)
            if desc_m.start() < vers_m.start():
                # Remove both, then re-insert in correct order (VersionString before Description)
                citation = citation.replace(desc_m.group(1), '')
                citation = citation.replace(vers_m.group(1), '')
                # Insert before closing </eml:Citation>
                insert_pos = citation.rfind('</eml:Citation>')
                if insert_pos >= 0:
                    citation = (citation[:insert_pos] +
                                vers_m.group(1) + desc_m.group(1) + '\n' +
                                citation[insert_pos:])
        return citation

    content = re.sub(
        r'<eml:Citation[^>]*>.*?</eml:Citation>', _fix_citation_order, content, flags=re.DOTALL)

    # 3. Replace invalid UOM 'v/v' with 'm3/m3' (valid ResqmlUom)
    content = re.sub(
        r'(<resqml2:UOM[^>]*>)v/v(</resqml2:UOM>)',
        r'\g<1>m3/m3\2', content)

    # 4. Replace invalid PropertyKinds with valid enum values
    _PROPERTY_KIND_MAP = {
        'mass per volume': 'density',
        'shale volume': 'volume per volume',
        'volume fraction': 'volume per volume',
    }
    for invalid, valid in _PROPERTY_KIND_MAP.items():
        # Match both with and without xsi:type attribute
        content = content.replace(
            f'<resqml2:Kind xsi:type="resqml2:ResqmlPropertyKind">{invalid}</resqml2:Kind>',
            f'<resqml2:Kind xsi:type="resqml2:ResqmlPropertyKind">{valid}</resqml2:Kind>')
        content = content.replace(
            f'<resqml2:Kind>{invalid}</resqml2:Kind>',
            f'<resqml2:Kind>{valid}</resqml2:Kind>')

    # 5. Fix ExtraMetadata position: fesapi requires ExtraMetadata AFTER all type-specific
    #    elements, just before the closing root tag.  Move them there unconditionally.
    extra_metadata_blocks = re.findall(
        r'<resqml2:ExtraMetadata[^>]*>.*?</resqml2:ExtraMetadata>', content, re.DOTALL)
    if extra_metadata_blocks:
        # Remove all ExtraMetadata blocks from current positions
        for block in extra_metadata_blocks:
            content = content.replace(block, '')
        # Clean up any trailing whitespace/newlines from removal
        content = re.sub(r'\n\s*\n', '\n', content)
        # Insert all ExtraMetadata blocks just before the closing root element
        # Find the last closing tag (</resqml2:...> or </eml:...>)
        close_tag_m = re.search(r'(</(?:resqml2|eml):\w+>)\s*$', content)
        if close_tag_m:
            em_text = '\n  ' + '\n  '.join(extra_metadata_blocks) + '\n'
            content = content[:close_tag_m.start()] + em_text + close_tag_m.group(0)

    # 6. Fix ExtraMetadata values to match corrected UOM/PropertyKind
    content = content.replace(
        '>v/v</resqml2:Value>', '>m3/m3</resqml2:Value>')
    for invalid, valid in _PROPERTY_KIND_MAP.items():
        content = content.replace(
            f'>{invalid}</resqml2:Value>', f'>{valid}</resqml2:Value>')

    # 7. Fix DisabledMarkers inside CustomData (RMS vendor extension).
    #    The element has xsi:type="resqml2:obj_WellboreMarkerFrameRepresentation"
    #    with empty uuid="" which violates the UUID pattern facet.  Remove entirely.
    content = re.sub(
        r'\s*<DisabledMarkers[^>]*>.*?</DisabledMarkers>',
        '', content, flags=re.DOTALL)

    # 8. Fix StratigraphicColumn inside CustomData (processContents="lax" resolves
    #    the resqml2: namespace element against the global obj_StratigraphicColumn
    #    declaration).  Change to a custom namespace so lax validation skips it.
    if '<resqml2:StratigraphicColumn' in content and '<eml:CustomData' in content:
        # Add custom namespace declaration if not present
        if 'xmlns:ext=' not in content:
            content = re.sub(
                r'(xmlns:resqml2="http://www.energistics.org/energyml/data/resqmlv2")',
                r'\1 xmlns:ext="http://www.equinor.com/resqml/extensions"',
                content)
        # Replace resqml2:StratigraphicColumn inside CustomData with ext:StratigraphicColumn
        # Also strip xsi:type to prevent lax validation of children
        content = re.sub(
            r'(<eml:CustomData[^>]*>)\s*<resqml2:StratigraphicColumn[^>]*>',
            r'\1<ext:StratigraphicColumn>',
            content, flags=re.DOTALL)
        # Fix closing tag (may have whitespace/newline before it)
        content = re.sub(
            r'</resqml2:StratigraphicColumn>\s*</eml:CustomData>',
            '</ext:StratigraphicColumn></eml:CustomData>',
            content)

    # 9. Fix StructuralOrganizationInterpretation: missing Domain element before
    #    InterpretedFeature (required by AbstractFeatureInterpretation XSD sequence).
    if 'StructuralOrganizationInterpretation' in content:
        # Check if Domain is missing (InterpretedFeature directly after Citation/CustomData)
        if '<resqml2:InterpretedFeature' in content and '<resqml2:Domain' not in content:
            content = content.replace(
                '<resqml2:InterpretedFeature',
                '<resqml2:Domain>depth</resqml2:Domain>\n  <resqml2:InterpretedFeature')

    # 11. Add xsi:type on root element (required by fesapi for object type identification).
    #     Pattern: <ns:TypeName ...> → <ns:TypeName xsi:type="ns:obj_TypeName" ...>
    m = re.match(r'(<\?xml[^>]+\?>\s*<(resqml2|eml):(\w+)\s)', content)
    if m and 'xsi:type=' not in content.split('\n')[1]:
        ns_prefix = m.group(2)
        type_name = m.group(3)
        insert_pos = m.end()
        content = content[:insert_pos] + f'xsi:type="{ns_prefix}:obj_{type_name}" ' + content[insert_pos:]

    return content


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
        # Skip artefact variants
        for skip in GRID2D_SKIP_TITLES:
            if skip in title:
                return False
        # Keep interpreted surfaces
        for keep in GRID2D_KEEP_TITLES:
            if keep in title:
                return True
        return False

    if obj_type == "PointSetRepresentation":
        title = _get_title(content)
        # Keep patterns take priority over skip patterns
        for keep in POINTSET_KEEP_PATTERNS:
            if keep in title:
                return True
        # Skip workflow artefacts
        for skip in POINTSET_SKIP_PATTERNS:
            if skip in title:
                return False
        return False

    # Unknown type - skip
    return False


def build_demo_epc():
    """Build the curated demo EPC."""
    print(f"Reading source EPC: {SRC_EPC}")
    with zipfile.ZipFile(SRC_EPC, "r") as src:
        all_names = src.namelist()

        # 1. Filter objects
        include_xmls = {}  # flat_name -> zip_path
        skip_log = []
        for name in all_names:
            if not name.endswith(".xml") or "obj_" not in name or "/_rels/" in name:
                continue
            # Extract flat filename (strip namespace_resqml20/ or similar prefix)
            flat_name = name.split("/")[-1]
            if not flat_name.startswith("obj_"):
                continue
            content = src.read(name).decode("utf-8")
            if should_include(flat_name, content):
                include_xmls[flat_name] = name
            else:
                skip_log.append((_get_obj_type(flat_name), _get_title(content)))

        # 2. Collect .rels (look in namespace folders too)
        include_rels = {}  # flat_rels_name -> zip_path
        for flat_name, zip_path in include_xmls.items():
            # Try both flat and prefixed paths
            prefix = zip_path.rsplit("/", 1)[0] + "/" if "/" in zip_path else ""
            rel_name = f"{prefix}_rels/{flat_name}.rels"
            if rel_name in all_names:
                include_rels[f"_rels/{flat_name}.rels"] = rel_name

        # 3. Collect H5 paths
        h5_paths = set()
        for flat_name, zip_path in include_xmls.items():
            content = src.read(zip_path).decode("utf-8")
            for path in H5_PATH_RE.findall(content):
                h5_paths.add(path)

        # Summary
        from collections import Counter
        type_counts = Counter()
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

        # 4. Build [Content_Types].xml
        content_types_xml = _build_content_types(include_xmls)

        # 5. Build _rels/.rels
        root_rels = _build_root_rels(include_xmls)

        # 6. Write EPC (with sanitization)
        print(f"\nWriting demo EPC: {OUT_EPC}")
        with zipfile.ZipFile(OUT_EPC, "w", zipfile.ZIP_DEFLATED) as dst:
            dst.writestr("[Content_Types].xml", content_types_xml)
            dst.writestr("_rels/.rels", root_rels)
            for flat_name in sorted(include_xmls):
                zip_path = include_xmls[flat_name]
                xml_content = src.read(zip_path).decode("utf-8")
                xml_content = _fix_namespaces(xml_content)
                xml_content = _sanitize_xml(xml_content)
                dst.writestr(flat_name, xml_content.encode("utf-8"))
            for flat_rels, zip_rels in sorted(include_rels.items()):
                # For EPR, write a proper rels pointing to the HDF5 file
                if "EpcExternalPartReference" in flat_rels:
                    epr_rels = (
                        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
                        f'  <Relationship Id="Hdf5File" Type="http://schemas.energistics.org/package/2012/relationships/externalResource"'
                        f' Target="{OUT_H5.name}" TargetMode="External"/>\n'
                        '</Relationships>')
                    dst.writestr(flat_rels, epr_rels.encode("utf-8"))
                else:
                    dst.writestr(flat_rels, src.read(zip_rels))

    # 7. Build H5 subset
    print(f"\nBuilding demo H5: {OUT_H5}")
    _build_subset_h5(h5_paths)

    # 8. Verify
    _verify_epc(OUT_EPC)

    return include_xmls, h5_paths


def _build_content_types(include_xmls: set[str]) -> str:
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


def _build_root_rels(include_xmls: set[str]) -> str:
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

    with h5py.File(SRC_H5, "r") as src_h5, h5py.File(OUT_H5, "w") as dst_h5:
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


def build_json_records(include_xmls: set[str], h5_paths: set[str]):
    """Build JSON RESQML records with embedded arrays."""
    print(f"\n{'='*60}")
    print("Building JSON RESQML records for OpenETPClient")
    print(f"{'='*60}")

    dataspace = "maap/drogon"
    records = []

    with zipfile.ZipFile(SRC_EPC, "r") as zf:
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

            # Embed arrays
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

    # Individual files
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
    print(f"\nTest with local RDDMS:")
    print(f"  openETPServer space -S ws://localhost:9002 --auth none \\")
    print(f"    -s maap/drogon --new")
    print(f"  openETPServer space -S ws://localhost:9002 --auth none \\")
    print(f"    -s maap/drogon --import-epc /data/drogon.epc")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
