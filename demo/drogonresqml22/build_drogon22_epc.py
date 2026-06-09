#!/usr/bin/env python3
"""
build_drogon22_epc.py – Convert the RESQML 2.0.1 Drogon EPC to valid RESQML 2.2.

Transforms:
  1. schemaVersion "2.0" → "2.2"
  2. Remove obj_ prefix from type names
  3. Rename types: GeneticBoundaryFeature/TectonicBoundaryFeature → BoundaryFeature
                   StratigraphicUnitFeature → RockVolumeFeature
                   OrganizationFeature → Model
  4. DataObjectReference: ContentType/UUID → QualifiedType/Uuid
  5. Properties: Count→ValueCountPerIndexableElement, PatchOfValues→ValuesForPatch, UOM→Uom
  6. PropertyKind: StandardPropertyKind/Kind → PropertyKind DOR
  7. Grid2dRepresentation: unwrap Grid2dPatch → FastestAxisCount/SlowestAxisCount/Geometry
  8. Representations: RepresentedInterpretation → RepresentedObject
  9. Interpretations: RepresentedInterpretation → InterpretedFeature
  10. WellboreTrajectory: StartMd/FinishMd/MdUom → MdInterval
  11. Remove DisabledMarkers CustomData blocks

Usage:
    python build_drogon22_epc.py
"""
from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SRC_EPC = SCRIPT_DIR.parent / "drogonresqml" / "drogon_demo.epc"
OUT_EPC = SCRIPT_DIR / "drogon_demo_22.epc"

# ── RESQML 2.0.1 → 2.2 type renames ─────────────────────────────────────
TYPE_RENAMES = {
    "GeneticBoundaryFeature": "BoundaryFeature",
    "TectonicBoundaryFeature": "BoundaryFeature",
    "StratigraphicUnitFeature": "RockVolumeFeature",
    "OrganizationFeature": "Model",
    "WellboreMarkerFrameRepresentation": "WellboreFrameRepresentation",
}

# Types removed in RESQML 2.2 — exclude from output EPC
EXCLUDED_TYPES = {
    "MdDatum",
    "DeviationSurveyRepresentation",
}

# Objects whose HDF5 datasets are missing from all available source H5 files
# (Grid2dRepresentation "Depth Surface - Geogrid Extract" with no points_patch0)
EXCLUDED_UUIDS = {
    "023e0b30-3822-41a3-b4ad-7b8d34b5f42a",
    "4b836144-9eaf-4511-aea0-cee8b1d63994",
    "7d76b4fb-d927-4697-89a9-882b7a516a49",
    "ce5fac58-c8c8-44ad-be08-12f75a2af509",
    "d2fef43f-0aa0-427d-afc1-ab254b71fcd2",
    "eba48dd6-f2d0-49e1-b0d6-ad2f401c51f9",
}

# Types that are Interpretations (use InterpretedFeature for their DOR to feature)
INTERPRETATION_TYPES = {
    "FaultInterpretation", "HorizonInterpretation",
    "StratigraphicUnitInterpretation", "StratigraphicColumnRankInterpretation",
    "StructuralOrganizationInterpretation", "WellboreInterpretation",
    "GeobodyInterpretation", "GeobodyBoundaryInterpretation",
    "EarthModelInterpretation",
}

# Types that are Representations (use RepresentedObject)
REPRESENTATION_TYPES = {
    "Grid2dRepresentation", "PolylineSetRepresentation", "PointSetRepresentation",
    "WellboreTrajectoryRepresentation", "WellboreFrameRepresentation",
    "IjkGridRepresentation", "TriangulatedSetRepresentation",
    "UnstructuredGridRepresentation",
}


def _convert_type_name(name_201: str) -> str:
    """Convert a 2.0.1 type name (with or without obj_ prefix) to 2.2."""
    bare = name_201.replace("obj_", "")
    return TYPE_RENAMES.get(bare, bare)


def _content_type_to_qualified_type(content_type: str) -> str:
    """Convert ContentType string to QualifiedType.

    'application/x-resqml+xml;version=2.0;type=obj_FaultInterpretation'
    -> 'resqml22.FaultInterpretation'
    """
    m = re.match(r'application/x-(\w+)\+xml;version=[\d.]+;type=(?:obj_)?(\w+)', content_type)
    if not m:
        return content_type

    domain = m.group(1)
    type_name = _convert_type_name(m.group(2))

    if domain == "resqml":
        return f"resqml22.{type_name}"
    elif domain == "eml":
        return f"eml22.{type_name}"
    elif domain == "witsml":
        return f"witsml21.{type_name}"
    else:
        return f"{domain}22.{type_name}"


def _convert_dor(dor_xml: str) -> str:
    """Convert all DataObjectReferences: ContentType/UUID -> QualifiedType/Uuid.

    Includes HdfProxy DORs — v2.2 requires QualifiedType/Uuid everywhere.
    """

    # ContentType -> QualifiedType
    def _replace_ct(m):
        indent = m.group(1)
        ct_value = m.group(2)
        qt = _content_type_to_qualified_type(ct_value)
        return f'{indent}<eml:QualifiedType xsi:type="xsd:string">{qt}</eml:QualifiedType>'

    dor_xml = re.sub(
        r'(\s*)<eml:ContentType[^>]*>([^<]+)</eml:ContentType>',
        _replace_ct, dor_xml)

    # UUID -> Uuid
    dor_xml = re.sub(
        r'<eml:UUID([^>]*)>([^<]+)</eml:UUID>',
        r'<eml:Uuid\1>\2</eml:Uuid>',
        dor_xml)

    return dor_xml


# Deterministic namespace for PropertyKind UUIDs
import uuid as _uuid
_PK_NS = _uuid.UUID("a48c9c25-1e3a-43c8-be6a-044224cc69cb")

# Track all PropertyKind names encountered during conversion
_property_kind_names: set = set()


def _pk_uuid(kind_name: str) -> str:
    """Deterministic UUID for a standard PropertyKind name."""
    return str(_uuid.uuid5(_PK_NS, kind_name))


def _convert_property_kind(xml: str) -> str:
    """Convert v2.0 StandardPropertyKind/Kind enum to v2.2 PropertyKind DOR."""

    def _replace_pk(m):
        kind_name = m.group(1)
        _property_kind_names.add(kind_name)
        pk_uuid = _pk_uuid(kind_name)
        return (
            '<resqml2:PropertyKind xsi:type="eml:DataObjectReference">\n'
            '\t\t<eml:QualifiedType xsi:type="xsd:string">eml23.PropertyKind</eml:QualifiedType>\n'
            f'\t\t<eml:Title xsi:type="eml:DescriptionString">{kind_name}</eml:Title>\n'
            f'\t\t<eml:Uuid xsi:type="eml:UuidString">{pk_uuid}</eml:Uuid>\n'
            '\t</resqml2:PropertyKind>'
        )

    xml = re.sub(
        r'<resqml2:PropertyKind[^>]*xsi:type="resqml2:StandardPropertyKind"[^>]*>\s*'
        r'<resqml2:Kind[^>]*>([^<]+)</resqml2:Kind>\s*</resqml2:PropertyKind>',
        _replace_pk, xml)

    return xml


def _convert_grid2d_patch(xml: str) -> str:
    """Unwrap Grid2dPatch: move FastestAxisCount, SlowestAxisCount, Geometry up."""

    def _replace_patch(m):
        inner = m.group(1)
        # Remove PatchIndex
        inner = re.sub(r'\s*<resqml2:PatchIndex[^>]*>[^<]*</resqml2:PatchIndex>\s*', '\n', inner)
        # Dedent one level
        lines = inner.split('\n')
        dedented = []
        for line in lines:
            if line.startswith('\t\t'):
                dedented.append(line[1:])
            elif line.strip():
                dedented.append(line)
        return '\n'.join(dedented)

    xml = re.sub(
        r'\s*<resqml2:Grid2dPatch[^>]*>(.*?)</resqml2:Grid2dPatch>',
        _replace_patch, xml, flags=re.DOTALL)

    return xml




def _convert_lattice_offset_to_dimension(xml: str) -> str:
    """Convert Point3dLatticeArray Offset to Dimension (v2.0 -> v2.2).

    v2.0: <resqml2:Offset xsi:type="resqml2:Point3dOffset">
              <resqml2:Offset xsi:type="resqml2:Point3d">...</resqml2:Offset>
              <resqml2:Spacing ...>...</resqml2:Spacing>
          </resqml2:Offset>

    v2.2: <resqml2:Dimension xsi:type="resqml2:Point3dLatticeDimension">
              <resqml2:Direction xsi:type="resqml2:Point3d">...</resqml2:Direction>
              <resqml2:Spacing ...>...</resqml2:Spacing>
          </resqml2:Dimension>
    """
    # First rename inner Offset (point3d direction) -> Direction
    # The inner offset is: <resqml2:Offset xsi:type="resqml2:Point3d">
    xml = re.sub(
        r'<resqml2:Offset(\s+xsi:type="resqml2:Point3d")>',
        r'<resqml2:Direction\1>',
        xml)
    xml = re.sub(
        r'</resqml2:Offset>(\s*<resqml2:Spacing)',
        r'</resqml2:Direction>\1',
        xml)

    # Then rename outer Offset (Point3dOffset) -> Dimension (Point3dLatticeDimension)
    xml = xml.replace(
        'xsi:type="resqml2:Point3dOffset"',
        'xsi:type="resqml2:Point3dLatticeDimension"')
    xml = re.sub(
        r'<resqml2:Offset(\s+xsi:type="resqml2:Point3dLatticeDimension")>',
        r'<resqml2:Dimension\1>',
        xml)
    # Fix closing tags - find </resqml2:Offset> that comes after Dimension opening
    # This is tricky - use a simpler approach: replace remaining Offset open/close that 
    # contain Dimension/Direction children
    xml = re.sub(
        r'</resqml2:Offset>(\s*</resqml2:(?:SupportingGeometry|Point3dLatticeArray))',
        r'</resqml2:Dimension>\1',
        xml)
    # Also fix closing Offset that appears before another Dimension
    xml = re.sub(
        r'</resqml2:Offset>(\s*<resqml2:Dimension)',
        r'</resqml2:Dimension>\1',
        xml)
    
    return xml

def _convert_wellbore_trajectory(xml: str) -> str:
    """Convert StartMd/FinishMd/MdUom to MdInterval."""

    start_m = re.search(r'<resqml2:StartMd[^>]*>([^<]+)</resqml2:StartMd>', xml)
    finish_m = re.search(r'<resqml2:FinishMd[^>]*>([^<]+)</resqml2:FinishMd>', xml)
    uom_m = re.search(r'<resqml2:MdUom[^>]*>([^<]+)</resqml2:MdUom>', xml)

    if start_m and finish_m:
        start_val = start_m.group(1)
        finish_val = finish_m.group(1)
        uom_val = uom_m.group(1) if uom_m else "m"

        md_interval = (
            '\t<resqml2:MdInterval xsi:type="resqml2:MdInterval">\n'
            f'\t\t<eml:MdMin xsi:type="xsd:double">{start_val}</eml:MdMin>\n'
            f'\t\t<eml:MdMax xsi:type="xsd:double">{finish_val}</eml:MdMax>\n'
            f'\t\t<eml:Uom xsi:type="eml:LengthUom">{uom_val}</eml:Uom>\n'
            '\t</resqml2:MdInterval>\n'
        )

        # Remove old elements
        xml = re.sub(r'\s*<resqml2:StartMd[^>]*>[^<]*</resqml2:StartMd>', '', xml)
        xml = re.sub(r'\s*<resqml2:FinishMd[^>]*>[^<]*</resqml2:FinishMd>', '', xml)
        xml = re.sub(r'\s*<resqml2:MdUom[^>]*>[^<]*</resqml2:MdUom>', '', xml)

        # Remove MdDatum DOR if present
        xml = re.sub(
            r'\s*<resqml2:MdDatum[^>]*>.*?</resqml2:MdDatum>',
            '', xml, flags=re.DOTALL)

        # Insert MdInterval after RepresentedObject or after Citation
        if '</resqml2:RepresentedObject>' in xml:
            xml = re.sub(
                r'(</resqml2:RepresentedObject>)',
                r'\1\n' + md_interval, xml, count=1)
        elif '</eml:Citation>' in xml:
            xml = re.sub(
                r'(</eml:Citation>)',
                r'\1\n' + md_interval, xml, count=1)

    return xml


def _fix_namespace_decl(xml: str) -> str:
    """Add xmlns:xsd if missing."""
    if 'xmlns:xsd=' not in xml:
        xml = xml.replace(
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"',
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            'xmlns:xsd="http://www.w3.org/2001/XMLSchema"',
        )
    return xml


def _remove_disabled_markers(xml: str) -> str:
    """Remove the CustomData/DisabledMarkers block."""
    xml = re.sub(
        r'\s*<eml:CustomData[^>]*>.*?DisabledMarkers.*?</eml:CustomData>',
        '', xml, flags=re.DOTALL)
    return xml


def _remove_inline_markers(xml: str) -> str:
    """Remove inline WellboreMarker elements from WellboreFrameRepresentation.

    In RESQML 2.2, the WellboreMarker type does NOT exist in the RESQML namespace.
    WellboreFrameRepresentation only contains: NodeCount, NodeMd, Trajectory,
    and optionally WitsmlLog, CellFluidPhaseUnits, IntervalStratigraphicUnits.

    The 2.0.1 WellboreMarkerFrameRepresentation nested WellboreMarker elements
    inside the frame, but this is invalid in the 2.2 XSD schema.
    Marker metadata is preserved implicitly through the NodeMd positions.
    """
    xml = re.sub(
        r'\s*<resqml2:WellboreMarker[^>]*>.*?</resqml2:WellboreMarker>',
        '', xml, flags=re.DOTALL)
    return xml


def _determine_object_category(type_name: str) -> str:
    """Determine if a type is an interpretation or representation."""
    bare = _convert_type_name(type_name.replace("obj_", ""))
    if bare in INTERPRETATION_TYPES:
        return "interpretation"
    if bare in REPRESENTATION_TYPES:
        return "representation"
    return "other"


# Map v2.0 Hdf5Array xsi:type to v2.2 ExternalArray xsi:type
_HDF5_TO_EXTERNAL = {
    "resqml2:DoubleHdf5Array": "eml:FloatingPointExternalArray",
    "resqml2:IntegerHdf5Array": "eml:IntegerExternalArray",
    "resqml2:BooleanHdf5Array": "eml:BooleanExternalArray",
    "resqml2:Point3dHdf5Array": "resqml2:Point3DExternalArray",
}


def _convert_hdf5_arrays(xml: str) -> str:
    """Convert v2.0 Hdf5Array blocks to v2.2 ExternalArray format.
    
    RESQML 2.2 uses EML 2.3 ExternalDataArray/ExternalDataArrayPart structure:
    
    v2.2: <X xsi:type="eml:FloatingPointExternalArray">
            <eml:ArrayFloatingPointType>arrayOfDouble64LE</eml:ArrayFloatingPointType>
            <eml:CountPerValue>1</eml:CountPerValue>
            <eml:Values xsi:type="eml:ExternalDataArray">
              <eml:ExternalDataArrayPart>
                <eml:Count>1</eml:Count>
                <eml:PathInExternalFile>PATH</eml:PathInExternalFile>
                <eml:StartIndex>0</eml:StartIndex>
                <eml:URI>drogon.h5</eml:URI>
              </eml:ExternalDataArrayPart>
            </eml:Values>
          </X>
    """
    # Replace xsi:type for array containers
    for old_type, new_type in _HDF5_TO_EXTERNAL.items():
        xml = xml.replace(f'xsi:type="{old_type}"', f'xsi:type="{new_type}"')

    # After type replacement, add required child elements for FloatingPointExternalArray
    # Insert ArrayFloatingPointType and CountPerValue before Values
    xml = re.sub(
        r'(xsi:type="eml:FloatingPointExternalArray">)\s*(<eml:Values|<resqml2:Values)',
        r'\1\n\t\t\t<eml:ArrayFloatingPointType>arrayOfDouble64LE</eml:ArrayFloatingPointType>'
        r'\n\t\t\t<eml:CountPerValue>1</eml:CountPerValue>\n\t\t\t\2',
        xml)

    # Insert ArrayIntegerType and CountPerValue before Values for IntegerExternalArray
    # (NullValue already exists from v2.0)
    xml = re.sub(
        r'(xsi:type="eml:IntegerExternalArray">)\s*'
        r'(<resqml2:NullValue[^>]*>[^<]*</resqml2:NullValue>)\s*'
        r'(<eml:Values|<resqml2:Values)',
        r'\1\n\t\t\t<eml:ArrayIntegerType>arrayOfInt32LE</eml:ArrayIntegerType>'
        r'\n\t\t\t\2'
        r'\n\t\t\t<eml:CountPerValue>1</eml:CountPerValue>\n\t\t\t\3',
        xml)

    # Convert <resqml2:Values/Coordinates xsi:type="eml:Hdf5Dataset"> → ExternalDataArray
    def _rewrite_hdf5_dataset(m):
        indent = m.group(1)
        elem_name = m.group(2)
        path = m.group(3)
        # All use ExternalDataArray/ExternalDataArrayPart with URI
        if elem_name == 'Coordinates':
            tag_open = f'<resqml2:Coordinates xsi:type="resqml2:ExternalDataArray">'
            tag_close = '</resqml2:Coordinates>'
        else:
            tag_open = '<eml:Values xsi:type="eml:ExternalDataArray">'
            tag_close = '</eml:Values>'
        return (
            f'{indent}{tag_open}\n'
            f'{indent}\t<eml:ExternalDataArrayPart>\n'
            f'{indent}\t\t<eml:Count>1</eml:Count>\n'
            f'{indent}\t\t<eml:PathInExternalFile>{path}</eml:PathInExternalFile>\n'
            f'{indent}\t\t<eml:StartIndex>0</eml:StartIndex>\n'
            f'{indent}\t\t<eml:URI>drogon.h5</eml:URI>\n'
            f'{indent}\t</eml:ExternalDataArrayPart>\n'
            f'{indent}{tag_close}'
        )

    xml = re.sub(
        r'(\s*)<resqml2:(Values|Coordinates) xsi:type="eml:Hdf5Dataset">\s*'
        r'<eml:PathInHdfFile[^>]*>([^<]+)</eml:PathInHdfFile>\s*'
        r'<eml:HdfProxy xsi:type="eml:DataObjectReference">.*?</eml:HdfProxy>\s*'
        r'</resqml2:\2>',
        _rewrite_hdf5_dataset,
        xml,
        flags=re.DOTALL)

    return xml


def _convert_content(xml: str, old_type: str, new_type: str) -> str:
    """Apply all 2.0.1->2.2 transformations to XML content."""

    # 1. Fix namespace declarations
    xml = _fix_namespace_decl(xml)

    # 2. schemaVersion="2.0" -> "2.2"
    xml = xml.replace('schemaVersion="2.0"', 'schemaVersion="2.2"')

    # 3. Update root element tag: resqml2:obj_Type -> resqml2:Type
    xml = re.sub(
        r'(</?resqml2:)obj_' + re.escape(old_type),
        r'\g<1>' + new_type,
        xml)
    if old_type != new_type:
        xml = re.sub(
            r'(</?resqml2:)' + re.escape(old_type) + r'(?=[\s>])',
            r'\g<1>' + new_type,
            xml)

    # 4. xsi:type="resqml2:obj_Type" -> xsi:type="resqml2:Type"
    xml = re.sub(r'xsi:type="resqml2:obj_(\w+)"',
                 lambda m: f'xsi:type="resqml2:{_convert_type_name(m.group(1))}"', xml)

    # 5. Convert all DataObjectReferences (ContentType/UUID -> QualifiedType/Uuid)
    xml = _convert_dor(xml)

    # 6. RepresentedInterpretation -> InterpretedFeature or RepresentedObject
    category = _determine_object_category(old_type)
    if category == "interpretation":
        xml = xml.replace("RepresentedInterpretation", "InterpretedFeature")
    elif category == "representation":
        xml = xml.replace("RepresentedInterpretation", "RepresentedObject")

    # 6b. Convert Hdf5Array types -> ExternalArray (v2.2)
    xml = _convert_hdf5_arrays(xml)

    # 7. Property-specific conversions
    if "Property" in new_type:
        # Count -> ValueCountPerIndexableElement
        xml = re.sub(
            r'<resqml2:Count([^>]*)>([^<]+)</resqml2:Count>',
            r'<resqml2:ValueCountPerIndexableElement\1>\2</resqml2:ValueCountPerIndexableElement>',
            xml)
        # PatchOfValues -> ValuesForPatch
        xml = xml.replace('<resqml2:PatchOfValues', '<resqml2:ValuesForPatch')
        xml = xml.replace('</resqml2:PatchOfValues>', '</resqml2:ValuesForPatch>')
        # UOM -> Uom (standalone element, not part of other words)
        # Also fix invalid value v/v -> m3/m3
        xml = xml.replace('>v/v</resqml2:UOM>', '>m3/m3</resqml2:UOM>')
        xml = re.sub(
            r'<resqml2:UOM([^>]*)>([^<]+)</resqml2:UOM>',
            r'<resqml2:Uom\1>\2</resqml2:Uom>',
            xml)
        # PropertyKind inline -> DOR
        xml = _convert_property_kind(xml)

    # 8. Grid2d-specific: unwrap Grid2dPatch + Offset->Dimension
    if "Grid2d" in new_type:
        xml = _convert_grid2d_patch(xml)
        xml = _convert_lattice_offset_to_dimension(xml)

    # 9. WellboreTrajectory-specific: StartMd/FinishMd -> MdInterval
    if "WellboreTrajectory" in new_type:
        xml = _convert_wellbore_trajectory(xml)

    # 10. Remove DisabledMarkers
    xml = _remove_disabled_markers(xml)

    # 10b. Remove inline WellboreMarker elements (invalid in RESQML 2.2 XSD)
    if "WellboreFrame" in new_type:
        xml = _remove_inline_markers(xml)

    # 11. Update Format citation
    xml = xml.replace(
        'RESQML v2.0 (Drogon Demo)',
        'RESQML v2.2 (Drogon Demo)')

    # 12. All Features + Model: add IsWellKnown (required in v2.2)
    if "Feature" in new_type or new_type == "Model":
        if '<resqml2:IsWellKnown' not in xml and '<eml:IsWellKnown' not in xml:
            xml = re.sub(
                r'(</eml:Citation>)',
                r'\1\n\t<resqml2:IsWellKnown xsi:type="xsd:boolean">true</resqml2:IsWellKnown>',
                xml, count=1)

    # 13. Fix ExtraMetadata ordering (must be after Citation, before Count/IndexableElement)
    extra_metadata_blocks = re.findall(
        r'<resqml2:ExtraMetadata[^>]*>.*?</resqml2:ExtraMetadata>', xml, re.DOTALL)
    if extra_metadata_blocks:
        citation_end = xml.find('</eml:Citation>')
        first_em = xml.find('<resqml2:ExtraMetadata')
        count_pos = xml.find('<resqml2:ValueCountPerIndexableElement')
        if count_pos < 0:
            count_pos = xml.find('<resqml2:Count')
        if citation_end > 0 and first_em > 0 and count_pos > 0 and first_em > count_pos:
            for block in extra_metadata_blocks:
                xml = xml.replace(block, '')
            xml = re.sub(r'\n\s*\n', '\n', xml)
            em_text = '\n' + '\n'.join(extra_metadata_blocks)
            xml = xml.replace('</eml:Citation>', '</eml:Citation>' + em_text, 1)

    # 14. Fix v/v in ExtraMetadata values
    xml = xml.replace('>v/v</resqml2:Value>', '>m3/m3</resqml2:Value>')

    return xml


def _convert_filename(old_name: str) -> str:
    """Convert filename: obj_Type_uuid.xml -> Type_uuid.xml"""
    if not old_name.startswith("obj_"):
        return old_name
    m = re.match(r'obj_(\w+?)_([0-9a-f-]{36})\.xml', old_name)
    if m:
        old_type = m.group(1)
        uuid = m.group(2)
        new_type = _convert_type_name(old_type)
        return f"{new_type}_{uuid}.xml"
    return old_name


def _generate_property_kind_objects_from_names(kinds: set) -> dict:
    """Generate PropertyKind XML objects for the given kind names."""
    import uuid as _uuid
    _NS = _uuid.UUID("a48c9c25-1e3a-43c8-be6a-044224cc69cb")

    # Map PropertyKind names to valid QuantityTypeKind enum values
    _QUANTITY_CLASS_MAP = {
        "net to gross ratio": "volume per volume",
        "index": "dimensionless",
        "volume": "volume",
        "amplitude": "dimensionless",
        "dimensionless": "dimensionless",
        "saturation": "volume per volume",
        "porosity": "volume per volume",
        "length": "length",
        "velocity": "length per time",
        "volume fraction": "volume per volume",
        "mass per volume": "mass per volume",
        "shale volume": "volume per volume",
        "Rock Impedance": "dimensionless",
        "rock permeability": "permeability rock",
        "depth": "length",
        "thermodynamic temperature": "thermodynamic temperature",
    }
    
    pk_objects = {}
    for kind_name in sorted(kinds):
        pk_uuid = str(_uuid.uuid5(_NS, kind_name))
        quantity_class = _QUANTITY_CLASS_MAP.get(kind_name, "dimensionless")
        pk_xml = f"""<?xml version='1.0' encoding='UTF-8'?>
<eml:PropertyKind xmlns:eml="http://www.energistics.org/energyml/data/commonv2" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema" schemaVersion="2.3" uuid="{pk_uuid}" xsi:type="eml:PropertyKind">
\t<eml:Citation xsi:type="eml:Citation">
\t\t<eml:Title xsi:type="eml:DescriptionString">{kind_name}</eml:Title>
\t\t<eml:Originator xsi:type="eml:NameString">Energistics</eml:Originator>
\t\t<eml:Creation xsi:type="xsd:dateTime">2025-01-01T00:00:00Z</eml:Creation>
\t\t<eml:Format xsi:type="eml:DescriptionString">RESQML v2.2 Standard PropertyKind</eml:Format>
\t</eml:Citation>
\t<eml:QuantityClass xsi:type="eml:QuantityTypeKind">{quantity_class}</eml:QuantityClass>
\t<eml:IsAbstract xsi:type="xsd:boolean">false</eml:IsAbstract>
</eml:PropertyKind>"""
        filename = f"PropertyKind_{pk_uuid}.xml"
        pk_objects[filename] = pk_xml
    
    return pk_objects


def _cleanup_broken_rels(epc_path: Path):
    """Remove .rels Relationship entries whose Target doesn't exist in the EPC."""
    import shutil, tempfile
    with zipfile.ZipFile(epc_path, 'r') as z:
        all_files = set(z.namelist())
        entries = {}
        for name in z.namelist():
            entries[name] = z.read(name)

    # Find and fix broken .rels
    fixed = 0
    for name in list(entries.keys()):
        if not name.endswith('.rels'):
            continue
        content = entries[name].decode('utf-8')
        original = content
        # Remove Relationship entries whose Target isn't in the EPC
        def _keep_rel(m):
            nonlocal fixed
            target_m = re.search(r'Target="([^"]+)"', m.group(0))
            if not target_m:
                return m.group(0)
            target = target_m.group(1)
            if target.endswith('.h5') or target.startswith('http'):
                return m.group(0)
            if target in all_files:
                return m.group(0)
            fixed += 1
            return ''
        content = re.sub(r'\s*<Relationship[^>]*/>', _keep_rel, content)
        if content != original:
            entries[name] = content.encode('utf-8')

    if fixed > 0:
        # Rewrite the EPC
        tmp = epc_path.with_suffix('.tmp')
        with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as zout:
            for name, data in entries.items():
                zout.writestr(name, data)
        tmp.replace(epc_path)
        print(f"  Cleaned {fixed} broken .rels entries")


def main():
    if not SRC_EPC.exists():
        sys.exit(f"Source EPC not found: {SRC_EPC}")

    print(f"Converting RESQML 2.0.1 -> 2.2 (full schema transformation)")
    print(f"  Source: {SRC_EPC}")
    print(f"  Output: {OUT_EPC}")

    from collections import Counter
    type_counts = Counter()
    renamed_count = 0
    excluded_count = 0


    with zipfile.ZipFile(SRC_EPC, "r") as src:
        with zipfile.ZipFile(OUT_EPC, "w", zipfile.ZIP_DEFLATED) as dst:
            for old_name in src.namelist():
                content_bytes = src.read(old_name)

                if old_name.endswith(".xml") and old_name.startswith("obj_"):
                    xml = content_bytes.decode("utf-8")

                    m = re.match(r'obj_(\w+?)_([0-9a-f-]{36})\.xml', old_name)
                    old_type = m.group(1) if m else ""
                    obj_uuid = m.group(2) if m else ""

                    # Skip types that don't exist in RESQML 2.2
                    if old_type in EXCLUDED_TYPES:
                        excluded_count += 1
                        continue

                    # Skip objects with missing HDF5 data
                    if obj_uuid in EXCLUDED_UUIDS:
                        excluded_count += 1
                        continue

                    # Keep EpcExternalPartReference completely unchanged
                    # (import tool uses .rels for v2.0 but fails with v2.2 parsing)
                    if old_type == 'EpcExternalPartReference':
                        type_counts['EpcExternalPartReference'] += 1
                        dst.writestr(old_name, content_bytes)
                        continue

                    new_type = _convert_type_name(old_type)
                    type_counts[new_type] += 1
                    if old_type != new_type:
                        renamed_count += 1

                    xml = _convert_content(xml, old_type, new_type)
                    content_bytes = xml.encode("utf-8")

                    # Keep obj_ prefix for EpcExternalPartReference (import tool expects it)
                    if 'EpcExternalPartReference' in old_type:
                        new_name = old_name
                    else:
                        new_name = _convert_filename(old_name)
                    dst.writestr(new_name, content_bytes)

                elif old_name.endswith(".xml") and not old_name.startswith("[") and not old_name.startswith("_"):
                    # Non-obj_ XML files (e.g. EpcExternalPartReference)
                    xml = content_bytes.decode("utf-8")
                    xml = _fix_namespace_decl(xml)
                    xml = xml.replace('schemaVersion="2.0"', 'schemaVersion="2.2"')
                    # Fix obj_ in xsi:type
                    xml = re.sub(r'xsi:type="eml:obj_(\w+)"', r'xsi:type="eml:\1"', xml)
                    xml = re.sub(r'xsi:type="resqml2:obj_(\w+)"', lambda m2: f'xsi:type="resqml2:{_convert_type_name(m2.group(1))}"', xml)
                    xml = xml.replace('RESQML v2.0 (Drogon Demo)', 'RESQML v2.2 (Drogon Demo)')
                    # Add <eml:Filename> to EpcExternalPartReference (required by ETP import)
                    if 'EpcExternalPartReference' in xml and '<eml:Filename' not in xml:
                        title_m = re.search(r'<eml:Title[^>]*>([^<]+)</eml:Title>', xml)
                        if title_m:
                            filename = title_m.group(1)
                            xml = re.sub(
                                r'(</eml:MimeType>)',
                                r'\1\n\t<eml:Filename xsi:type="xsd:string">' + filename + '</eml:Filename>',
                                xml)
                    content_bytes = xml.encode("utf-8")
                    dst.writestr(old_name, content_bytes)

                elif old_name == "[Content_Types].xml":
                    ct_xml = content_bytes.decode("utf-8")
                    # Rename obj_ in PartNames — but keep EpcExternalPartReference as-is
                    ct_xml = re.sub(
                        r'obj_(\w+?)_',
                        lambda m2: (f'obj_{m2.group(1)}_' if m2.group(1) == 'EpcExternalPartReference'
                                    else f'{_convert_type_name(m2.group(1))}_'),
                        ct_xml)
                    # Upgrade version=2.0 → 2.2 EXCEPT for EpcExternalPartReference
                    # (import tool uses .rels Target for v2.0 but not v2.2)
                    ct_xml = ct_xml.replace("version=2.0", "version=2.2")
                    ct_xml = ct_xml.replace(
                        "version=2.2;type=obj_EpcExternalPartReference",
                        "version=2.0;type=obj_EpcExternalPartReference")
                    # Strip obj_ from ContentType values — except EpcExternalPartReference
                    ct_xml = re.sub(
                        r'type=obj_(\w+)',
                        lambda m2: (f'type=obj_{m2.group(1)}' if m2.group(1) == 'EpcExternalPartReference'
                                    else f'type={_convert_type_name(m2.group(1))}'),
                        ct_xml)
                    # No PropertyKind entries needed (kept as inline enum)
                    # Defer [Content_Types].xml write until after PropertyKind objects are known
                    # Remove entries for excluded types (match both obj_ and non-prefixed)
                    for excl_type in EXCLUDED_TYPES:
                        ct_xml = re.sub(
                            rf'<Override[^>]*PartName="/(?:obj_)?{excl_type}_[^"]*"[^>]*/>\s*', '', ct_xml)
                    # Remove entries for excluded UUIDs
                    for excl_uuid in EXCLUDED_UUIDS:
                        ct_xml = re.sub(
                            rf'<Override[^>]*PartName="[^"]*{excl_uuid}[^"]*"[^>]*/>\s*', '', ct_xml)
                    ct_xml_deferred = ct_xml
                    ct_name_deferred = old_name

                elif old_name.startswith("_rels/") and old_name.endswith(".rels"):
                    # Skip .rels for excluded types (check both obj_ and non-prefixed)
                    rels_type_m = re.search(r'(?:obj_)?(\w+?)_[0-9a-f-]{36}', old_name)
                    if rels_type_m and rels_type_m.group(1) in EXCLUDED_TYPES:
                        continue
                    # Skip .rels for excluded UUIDs
                    rels_uuid_m = re.search(r'([0-9a-f-]{36})', old_name)
                    if rels_uuid_m and rels_uuid_m.group(1) in EXCLUDED_UUIDS:
                        continue
                    rels_xml = content_bytes.decode("utf-8")
                    # Rename obj_ targets — but keep EpcExternalPartReference as-is
                    rels_xml = re.sub(
                        r'obj_(\w+?)_',
                        lambda m2: (f'obj_{m2.group(1)}_' if m2.group(1) == 'EpcExternalPartReference'
                                    else f'{_convert_type_name(m2.group(1))}_'),
                        rels_xml)
                    # Remove relationships targeting excluded types
                    for excl_type in EXCLUDED_TYPES:
                        rels_xml = re.sub(
                            rf'<Relationship[^>]*Target="[^"]*{excl_type}_[^"]*"[^>]*/>\s*', '', rels_xml)
                    # Remove relationships targeting excluded UUIDs
                    for excl_uuid in EXCLUDED_UUIDS:
                        rels_xml = re.sub(
                            rf'<Relationship[^>]*Target="[^"]*{excl_uuid}[^"]*"[^>]*/>\s*', '', rels_xml)
                    # Remove stale PropertyKind .rels entries whose targets don't
                    # exist (the v2.0.1 source had broken PropertyKind references
                    # that are now replaced by DOR-based references with new UUIDs)
                    rels_xml = re.sub(
                        r'\s*<Relationship[^>]*Target="PropertyKind_934c5a04-db08-4a31-9cb1-48046d4f7843\.xml"[^>]*/>', '', rels_xml)
                    # Keep EpcExternalPartReference .rels filename with obj_ prefix
                    if 'EpcExternalPartReference' in old_name:
                        new_rels_name = old_name
                    else:
                        new_rels_name = re.sub(
                            r'obj_(\w+?)_',
                            lambda m2: f'{_convert_type_name(m2.group(1))}_',
                            old_name)
                    dst.writestr(new_rels_name, rels_xml.encode("utf-8"))

                else:
                    dst.writestr(old_name, content_bytes)

            # ── Add PropertyKind objects ──────────────────────────────────
            if _property_kind_names:
                pk_objects = _generate_property_kind_objects_from_names(_property_kind_names)
                for pk_filename, pk_xml in pk_objects.items():
                    dst.writestr(pk_filename, pk_xml.encode("utf-8"))
                    type_counts["PropertyKind"] += 1
                print(f"  Added {len(pk_objects)} PropertyKind objects")

                # Add PropertyKind entries to [Content_Types].xml
                pk_ct_entries = ""
                for pk_filename in pk_objects:
                    pk_ct_entries += (
                        f'\n <Override PartName="/{pk_filename}" '
                        f'ContentType="application/x-eml+xml;version=2.3;type=PropertyKind"/>'
                    )
                # Insert before closing </Types>
                ct_xml_deferred = ct_xml_deferred.replace(
                    '</Types>', pk_ct_entries + '\n</Types>')

            # Write [Content_Types].xml
            dst.writestr(ct_name_deferred, ct_xml_deferred.encode("utf-8"))

    # ── Post-process: remove broken .rels entries ──────────────────────────
    # Some .rels entries reference targets that don't exist in the final EPC
    # (e.g. Geosiris objects excluded during merge, stale PropertyKind refs).
    # The ETP server rejects imports with unresolved .rels targets.
    _cleanup_broken_rels(OUT_EPC)

    print(f"\n  Converted {sum(type_counts.values())} objects ({renamed_count} type renames, {excluded_count} excluded)")
    print(f"  Types:")
    for t, c in sorted(type_counts.items()):
        print(f"    {t:45s} {c:4d}")
    print(f"\n  Output: {OUT_EPC} ({OUT_EPC.stat().st_size / 1024:.0f} KB)")

    # Quick verification
    print("\n  Verifying sample...")
    with zipfile.ZipFile(OUT_EPC) as z:
        names = [n for n in z.namelist() if n.endswith('.xml') and not n.startswith('[') and not n.startswith('_')]
        has_obj = any(n.startswith('obj_') for n in names)
        sample_issues = []
        for n in names[:20]:
            content = z.read(n).decode()
            if '<eml:ContentType' in content:
                sample_issues.append(f"  {n}: still has <eml:ContentType>")
            if '<eml:UUID' in content:
                sample_issues.append(f"  {n}: still has <eml:UUID>")
            if 'schemaVersion="2.0"' in content:
                sample_issues.append(f"  {n}: still has schemaVersion 2.0")

        print(f"    obj_ prefix remaining: {'YES !!' if has_obj else 'NO ok'}")
        if sample_issues:
            print(f"    Issues found ({len(sample_issues)}):")
            for i in sample_issues[:5]:
                print(f"      {i}")
        else:
            print(f"    Sample check: OK")

    print("\n  Done")


if __name__ == "__main__":
    main()
