"""
resqml_v22_converter.py – Reusable RESQML 2.0.1 → 2.2 XML converter.

Uses lxml for proper XML manipulation instead of fragile regex chains.

RESQML 2.2 / EML 2.3 key schema changes handled:
  1. Namespace prefixes and declarations
  2. schemaVersion attribute: "2.0" → "2.2"
  3. Type renames (GeneticBoundaryFeature→BoundaryFeature, etc.)
  4. DataObjectReference: ContentType/UUID/UuidAuthority → Uuid/QualifiedType/Title
  5. Property structure: Count→ValueCountPerIndexableElement, PatchOfValues→ValuesForPatch
  6. HDF5 arrays: Hdf5Dataset → ExternalDataArray/ExternalDataArrayPart
  7. PropertyKind: inline StandardPropertyKind/Kind → DOR
  8. ExtraMetadata (resqml2:) → ExtensionNameValue (eml:)
  9. Element ordering per XSD hierarchy
  10. Removed elements: MinimumValue, MaximumValue, GeneticBoundaryKind, etc.
  11. xsi:type cleanup (EML 2.3 rejects them on simple-typed elements)

Usage:
    from resqml_v22_converter import convert_object_xml, make_property_kind_xml
"""
from __future__ import annotations

import re
import uuid as _uuid
from copy import deepcopy
from lxml import etree

# ── Namespace URIs ────────────────────────────────────────────────────────

NS = {
    "eml": "http://www.energistics.org/energyml/data/commonv2",
    "resqml2": "http://www.energistics.org/energyml/data/resqmlv2",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
    "xsd": "http://www.w3.org/2001/XMLSchema",
}

EML = f"{{{NS['eml']}}}"
RESQML = f"{{{NS['resqml2']}}}"
XSI = f"{{{NS['xsi']}}}"

# ── Type renames ──────────────────────────────────────────────────────────

TYPE_RENAMES = {
    "GeneticBoundaryFeature": "BoundaryFeature",
    "TectonicBoundaryFeature": "BoundaryFeature",
    "StratigraphicUnitFeature": "RockVolumeFeature",
    "OrganizationFeature": "Model",
    "WellboreMarkerFrameRepresentation": "WellboreFrameRepresentation",
}

# v2.0.1 elements removed in v2.2
REMOVED_ELEMENTS = {
    f"{RESQML}MinimumValue",
    f"{RESQML}MaximumValue",
    f"{RESQML}GeneticBoundaryKind",
    f"{RESQML}TectonicBoundaryKind",
}

# xsi:type values that should be stripped (simple types that EML 2.3 rejects)
STRIP_XSI_TYPES = {
    f"{NS['xsd']}string", "xsd:string",
    f"{NS['xsd']}dateTime", "xsd:dateTime",
    f"{NS['xsd']}boolean", "xsd:boolean",
    f"{NS['xsd']}positiveInteger", "xsd:positiveInteger",
    f"{NS['xsd']}double", "xsd:double",
    f"{NS['xsd']}long", "xsd:long",
    f"{NS['xsd']}int", "xsd:int",
    f"{NS['xsd']}nonNegativeInteger", "xsd:nonNegativeInteger",
    f"{NS['eml']}DescriptionString", "eml:DescriptionString",
    f"{NS['eml']}NameString", "eml:NameString",
    f"{NS['eml']}UuidString", "eml:UuidString",
    f"{NS['eml']}LengthUom", "eml:LengthUom",
    f"{NS['eml']}Citation", "eml:Citation",
    f"{NS['eml']}TimeStamp", "eml:TimeStamp",
    f"{NS['resqml2']}IndexableElements", "resqml2:IndexableElements",
    f"{NS['resqml2']}ResqmlUom", "resqml2:ResqmlUom",
    f"{NS['resqml2']}ResqmlPropertyKind", "resqml2:ResqmlPropertyKind",
    f"{NS['resqml2']}NameValuePair", "resqml2:NameValuePair",
    f"{NS['resqml2']}PatchOfValues", "resqml2:PatchOfValues",
    f"{NS['resqml2']}Domain", "resqml2:Domain",
}

# Interpretation types (use InterpretedFeature for their DOR to feature)
INTERPRETATION_TYPES = {
    "FaultInterpretation", "HorizonInterpretation",
    "StratigraphicUnitInterpretation", "StratigraphicColumnRankInterpretation",
    "StructuralOrganizationInterpretation", "WellboreInterpretation",
    "GeobodyInterpretation", "GeobodyBoundaryInterpretation",
    "EarthModelInterpretation",
}

# Representation types (use RepresentedObject)
REPRESENTATION_TYPES = {
    "Grid2dRepresentation", "PolylineSetRepresentation", "PointSetRepresentation",
    "WellboreTrajectoryRepresentation", "WellboreFrameRepresentation",
    "IjkGridRepresentation", "TriangulatedSetRepresentation",
    "UnstructuredGridRepresentation",
}

# v2.0 Hdf5Array xsi:type → v2.2 ExternalArray xsi:type
HDF5_TO_EXTERNAL = {
    "resqml2:DoubleHdf5Array": "eml:FloatingPointExternalArray",
    "resqml2:IntegerHdf5Array": "eml:IntegerExternalArray",
    "resqml2:BooleanHdf5Array": "eml:BooleanExternalArray",
    "resqml2:Point3dHdf5Array": "resqml2:Point3dExternalArray",
}

# Map for ExternalArray sub-type metadata
EXTERNAL_ARRAY_META = {
    "eml:FloatingPointExternalArray": ("ArrayFloatingPointType", "arrayOfDouble64LE"),
    "eml:IntegerExternalArray": ("ArrayIntegerType", "arrayOfInt32LE"),
}

# Deterministic namespace for PropertyKind UUIDs
_PK_NS = _uuid.UUID("a48c9c25-1e3a-43c8-be6a-044224cc69cb")
_property_kind_names: set[str] = set()

# Map PropertyKind names to QuantityTypeKind values
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
    "property multiplier": "dimensionless",
    "density": "mass per volume",
    "volume per volume": "volume per volume",
    "pressure": "pressure",
    "code": "not a measure",
    "formation volume factor": "volume per volume",
    "relative permeability": "dimensionless",
    "Poisson ratio": "dimensionless",
    "mass concentration": "dimensionless",
    "solution gas-oil ratio": "volume per volume",
}

# Abstract property kinds must not be directly assigned to properties.
# Map them to the most common concrete descendant.
_ABSTRACT_KIND_FIX = {
    "volume per volume": "net to gross ratio",
    "dimensionless": "property multiplier",
    "categorical": "code",
    "continuous": "property multiplier",
    "discrete": "index",
    "quantity": "property multiplier",
    "unitless": "property multiplier",
    "RESQML root property": "property multiplier",
}

# Property kinds in the continuous hierarchy — invalid for DiscreteProperty
_CONTINUOUS_ONLY_KINDS = {
    "length", "depth", "cell length", "thickness", "velocity",
    "pressure", "density", "temperature", "thermodynamic temperature",
    "porosity", "saturation", "permeability rock", "rock permeability",
    "amplitude", "volume", "area", "angle", "time", "mass",
    "net to gross ratio", "formation volume factor",
    "property multiplier", "relative permeability",
}


def _pk_uuid(kind_name: str) -> str:
    return str(_uuid.uuid5(_PK_NS, kind_name))


def get_collected_property_kinds() -> set[str]:
    """Return all PropertyKind names encountered during conversion."""
    return _property_kind_names.copy()


def reset_collected_property_kinds():
    _property_kind_names.clear()


# ── Helpers ───────────────────────────────────────────────────────────────

def _bare_type(name: str) -> str:
    """Strip obj_ prefix."""
    return name.replace("obj_", "")


def _convert_type_name(name_201: str) -> str:
    """Convert a v2.0.1 type name to v2.2."""
    bare = _bare_type(name_201)
    return TYPE_RENAMES.get(bare, bare)


def _qualified_type(content_type: str) -> str:
    """Convert ContentType string to QualifiedType.

    'application/x-resqml+xml;version=2.0;type=obj_FaultInterpretation'
    → 'resqml22.FaultInterpretation'
    """
    m = re.match(r"application/x-(\w+)\+xml;version=[\d.]+;type=(?:obj_)?(\w+)", content_type)
    if not m:
        return content_type
    domain, type_name = m.group(1), _convert_type_name(m.group(2))
    prefix_map = {"resqml": "resqml22", "eml": "eml23", "witsml": "witsml21"}
    return f"{prefix_map.get(domain, domain + '22')}.{type_name}"


def _el(parent: etree._Element, ns: str, local: str) -> etree._Element | None:
    """Find first child element by namespace+local name."""
    return parent.find(f"{ns}{local}")


def _els(parent: etree._Element, ns: str, local: str) -> list[etree._Element]:
    """Find all child elements by namespace+local name."""
    return parent.findall(f"{ns}{local}")


def _remove_el(parent: etree._Element, ns: str, local: str) -> etree._Element | None:
    """Remove and return first matching child element."""
    el = parent.find(f"{ns}{local}")
    if el is not None:
        parent.remove(el)
    return el


def _remove_all(parent: etree._Element, ns: str, local: str) -> list[etree._Element]:
    """Remove and return all matching child elements."""
    found = parent.findall(f"{ns}{local}")
    for el in found:
        parent.remove(el)
    return found


def _insert_after(parent: etree._Element, ref_tag: str, new_el: etree._Element):
    """Insert new_el after the last child matching ref_tag, or append if not found."""
    idx = None
    for i, child in enumerate(parent):
        if child.tag == ref_tag:
            idx = i
    if idx is not None:
        parent.insert(idx + 1, new_el)
    else:
        parent.append(new_el)


def _make_sub(parent: etree._Element, tag: str, text: str | None = None,
              attrib: dict | None = None, nsmap: dict | None = None) -> etree._Element:
    """Create and append a sub-element."""
    el = etree.SubElement(parent, tag, attrib=attrib or {}, nsmap=nsmap or {})
    if text is not None:
        el.text = text
    return el


# ── DOR conversion ────────────────────────────────────────────────────────

def _convert_dor(dor: etree._Element):
    """Convert a DataObjectReference from v2.0.1 to v2.2 format IN PLACE.

    v2.0.1: ContentType, Title, UUID, UuidAuthority?
    v2.2:   Uuid, ObjectVersion?, QualifiedType, Title
    """
    # Extract values
    ct_el = _el(dor, EML, "ContentType")
    title_el = _el(dor, EML, "Title")
    uuid_el = _el(dor, EML, "UUID")
    uuid_auth = _el(dor, EML, "UuidAuthority")
    version_el = _el(dor, EML, "VersionString")

    ct_val = ct_el.text if ct_el is not None else ""
    title_val = title_el.text if title_el is not None else ""
    uuid_val = uuid_el.text if uuid_el is not None else ""

    # Also check for already-converted elements
    existing_uuid = _el(dor, EML, "Uuid")
    existing_qt = _el(dor, EML, "QualifiedType")
    if existing_uuid is not None and existing_qt is not None:
        # Already converted — just ensure correct order
        _reorder_dor(dor)
        return

    qt_val = _qualified_type(ct_val) if ct_val else ""

    # Remove all old children
    for child in list(dor):
        dor.remove(child)

    # Strip xsi:type from the DOR element itself if present
    # (keep it on DOR — it's a polymorphic type selector)

    # Build in correct v2.2 order: Uuid, QualifiedType, Title
    _make_sub(dor, f"{EML}Uuid", uuid_val)
    if version_el is not None and version_el.text:
        _make_sub(dor, f"{EML}ObjectVersion", version_el.text)
    _make_sub(dor, f"{EML}QualifiedType", qt_val)
    _make_sub(dor, f"{EML}Title", title_val)


def _reorder_dor(dor: etree._Element):
    """Ensure DOR children are in v2.2 XSD order: Uuid, ObjectVersion?, QualifiedType, Title."""
    uuid_el = _el(dor, EML, "Uuid")
    obj_ver = _el(dor, EML, "ObjectVersion")
    qt_el = _el(dor, EML, "QualifiedType")
    title_el = _el(dor, EML, "Title")
    if not (uuid_el is not None and qt_el is not None and title_el is not None):
        return
    # Remove and re-insert in order
    for child in list(dor):
        dor.remove(child)
    dor.append(uuid_el)
    if obj_ver is not None:
        dor.append(obj_ver)
    dor.append(qt_el)
    dor.append(title_el)


def _convert_all_dors(root: etree._Element):
    """Find and convert ALL DataObjectReference elements in the tree."""
    # DORs are identified by having ContentType+UUID children (v2.0.1)
    # or by having xsi:type="eml:DataObjectReference"
    # NOTE: Collect first, then mutate — modifying the tree during iter() skips
    # sibling elements because lxml's iterator invalidates on structural changes.
    to_convert = []
    to_reorder = []
    for el in root.iter():
        has_ct = _el(el, EML, "ContentType") is not None
        has_uuid = _el(el, EML, "UUID") is not None
        if has_ct and has_uuid:
            to_convert.append(el)
        # Also handle already partially converted DORs (e.g. from PropertyKind conversion)
        elif _el(el, EML, "QualifiedType") is not None and _el(el, EML, "Uuid") is not None:
            to_reorder.append(el)
    for el in to_convert:
        _convert_dor(el)
    for el in to_reorder:
        _reorder_dor(el)


# ── HDF5 → ExternalDataArray ─────────────────────────────────────────────

def _convert_hdf5_dataset(parent: etree._Element, hdf5_el: etree._Element,
                          h5_filename: str = "drogon.h5"):
    """Convert a Hdf5Dataset element to ExternalDataArray format.

    v2.0.1: <Values xsi:type="eml:Hdf5Dataset">
              <eml:PathInHdfFile>PATH</eml:PathInHdfFile>
              <eml:HdfProxy>...</eml:HdfProxy>
            </Values>

    v2.2:   <Values xsi:type="eml:ExternalDataArray">
              <eml:ExternalDataArrayPart>
                <eml:Count>1</eml:Count>
                <eml:PathInExternalFile>PATH</eml:PathInExternalFile>
                <eml:StartIndex>0</eml:StartIndex>
                <eml:URI>drogon.h5</eml:URI>
              </eml:ExternalDataArrayPart>
            </Values>
    """
    path_el = _el(hdf5_el, EML, "PathInHdfFile")
    h5_path = path_el.text if path_el is not None else ""

    # Clear old content
    hdf5_el.tag = f"{EML}Values"
    hdf5_el.set(f"{XSI}type", "eml:ExternalDataArray")
    for child in list(hdf5_el):
        hdf5_el.remove(child)

    # Build ExternalDataArrayPart
    part = _make_sub(hdf5_el, f"{EML}ExternalDataArrayPart")
    _make_sub(part, f"{EML}Count", "1")
    _make_sub(part, f"{EML}PathInExternalFile", h5_path)
    _make_sub(part, f"{EML}StartIndex", "0")
    _make_sub(part, f"{EML}URI", h5_filename)


def _convert_all_hdf5_arrays(root: etree._Element, h5_filename: str = "drogon.h5"):
    """Convert all Hdf5Dataset and Hdf5Array elements to ExternalArray format."""
    for el in list(root.iter()):
        xsi_type = el.get(f"{XSI}type", "")

        # Convert Hdf5Array containers (DoubleHdf5Array, IntegerHdf5Array, etc.)
        if xsi_type in HDF5_TO_EXTERNAL:
            new_type = HDF5_TO_EXTERNAL[xsi_type]
            el.set(f"{XSI}type", new_type)

            # Add required metadata elements before Values
            if new_type in EXTERNAL_ARRAY_META:
                meta_tag, meta_val = EXTERNAL_ARRAY_META[new_type]
                # Insert at beginning, before any existing children
                meta_el = etree.Element(f"{EML}{meta_tag}")
                meta_el.text = meta_val
                meta_el.tail = "\n\t\t\t"
                el.insert(0, meta_el)
                cpv = etree.Element(f"{EML}CountPerValue")
                cpv.text = "1"
                cpv.tail = "\n\t\t\t"
                el.insert(1, cpv)

            # Find and convert inner Hdf5Dataset Values
            for inner in list(el):
                inner_type = inner.get(f"{XSI}type", "")
                if inner_type == "eml:Hdf5Dataset" or (
                    inner.tag in (f"{RESQML}Values", f"{RESQML}Coordinates", f"{EML}Values")
                    and _el(inner, EML, "PathInHdfFile") is not None
                ):
                    _convert_hdf5_dataset(el, inner, h5_filename)

        # Convert standalone Hdf5Dataset (e.g. NodeMd, ControlPointParameters)
        elif xsi_type == "eml:Hdf5Dataset" or (
            _el(el, EML, "PathInHdfFile") is not None
            and _el(el, EML, "HdfProxy") is not None
            and el.getparent() is not None
        ):
            _convert_hdf5_dataset(el.getparent(), el, h5_filename)


# ── Property conversions ──────────────────────────────────────────────────

def _convert_property_kind(root: etree._Element):
    """Convert inline StandardPropertyKind/Kind to PropertyKind DOR.

    Also resolves abstract property kinds to concrete descendants
    and fixes discrete/continuous property kind compatibility.
    """
    bare_type = _bare_type(etree.QName(root.tag).localname)
    is_discrete = bare_type in ("DiscreteProperty", "CategoricalProperty")

    for pk in _els(root, RESQML, "PropertyKind"):
        xsi_type = pk.get(f"{XSI}type", "")
        if "StandardPropertyKind" in xsi_type:
            kind_el = _el(pk, RESQML, "Kind")
            if kind_el is not None:
                kind_name = kind_el.text or "dimensionless"

                # Resolve abstract kinds to concrete descendants
                if kind_name in _ABSTRACT_KIND_FIX:
                    kind_name = _ABSTRACT_KIND_FIX[kind_name]

                # Fix discrete/continuous mismatch
                if is_discrete and kind_name in _CONTINUOUS_ONLY_KINDS:
                    kind_name = "index"

                _property_kind_names.add(kind_name)
                pk_uuid = _pk_uuid(kind_name)

                # Clear and rebuild as DOR
                for child in list(pk):
                    pk.remove(child)
                pk.set(f"{XSI}type", "eml:DataObjectReference")
                _make_sub(pk, f"{EML}Uuid", pk_uuid)
                _make_sub(pk, f"{EML}QualifiedType", "eml23.PropertyKind")
                _make_sub(pk, f"{EML}Title", kind_name)


def _convert_property_elements(root: etree._Element, obj_type: str):
    """Rename and restructure property-specific elements for v2.2."""
    # Count → ValueCountPerIndexableElement
    for count_el in _els(root, RESQML, "Count"):
        count_el.tag = f"{RESQML}ValueCountPerIndexableElement"

    # UOM → Uom, fix invalid values
    for uom_el in _els(root, RESQML, "UOM"):
        uom_el.tag = f"{RESQML}Uom"
        if uom_el.text == "v/v":
            uom_el.text = "m3/m3"

    # PatchOfValues → ValuesForPatch (flatten structure)
    for pov in _els(root, RESQML, "PatchOfValues"):
        pov.tag = f"{RESQML}ValuesForPatch"
        # Remove RepresentationPatchIndex
        _remove_el(pov, RESQML, "RepresentationPatchIndex")
        # The inner Values element should become the ValuesForPatch content directly
        inner_values = _el(pov, RESQML, "Values")
        if inner_values is not None:
            # Move xsi:type from inner Values to ValuesForPatch
            inner_type = inner_values.get(f"{XSI}type", "")
            if inner_type:
                pov.set(f"{XSI}type", inner_type)
            # Move all children of inner Values to ValuesForPatch
            for child in list(inner_values):
                pov.append(child)
            pov.remove(inner_values)

    # Remove MinimumValue / MaximumValue (not in v2.2)
    _remove_all(root, RESQML, "MinimumValue")
    _remove_all(root, RESQML, "MaximumValue")

    # PropertyKind: inline → DOR
    _convert_property_kind(root)


def _reorder_property_children(root: etree._Element, obj_type: str):
    """Reorder property elements to match v2.2 XSD sequence.

    AbstractProperty: IndexableElement, Time?, RealizationIndices?,
                      ValueCountPerIndexableElement+, PropertyKind,
                      LabelPerComponent*, SupportingRepresentation,
                      LocalCrs?, TimeOrIntervalSeries?
    AbstractValuesProperty adds: ValuesForPatch+, Facet*
    ContinuousProperty adds: Uom, CustomUnitDictionary?
    DiscreteProperty adds: CategoryLookup?
    """
    # Collect all resqml2: children that need reordering
    ORDER = {
        "IndexableElement": 10,
        "Time": 15,
        "RealizationIndices": 20,
        "ValueCountPerIndexableElement": 30,
        "PropertyKind": 40,
        "LabelPerComponent": 50,
        "SupportingRepresentation": 60,
        "LocalCrs": 65,
        "TimeOrIntervalSeries": 67,
        "ValuesForPatch": 70,
        "Facet": 80,
        "Uom": 90,
        "CustomUnitDictionary": 95,
        "CategoryLookup": 100,
        "Lookup": 105,
    }

    reorderable = []
    non_reorderable = []

    for child in list(root):
        # Get local name
        local = etree.QName(child.tag).localname
        if local in ORDER:
            reorderable.append((ORDER[local], child))
            root.remove(child)
        elif child.tag.startswith(RESQML) and local not in (
            "IsWellKnown", "ExtraMetadata",
        ):
            reorderable.append((ORDER.get(local, 200), child))
            root.remove(child)

    # Sort and re-append
    reorderable.sort(key=lambda x: x[0])
    for _, child in reorderable:
        root.append(child)


# ── Feature/Interpretation conversions ────────────────────────────────────

def _convert_feature(root: etree._Element, old_type: str, new_type: str):
    """Add IsWellKnown, remove v2.0.1-only kind elements."""
    # Add IsWellKnown if not present
    if _el(root, RESQML, "IsWellKnown") is None:
        iswk = etree.Element(f"{RESQML}IsWellKnown")
        iswk.text = "true"
        # Insert after Citation or ExtensionNameValue
        _insert_after(root, f"{EML}ExtensionNameValue", iswk)
        if _el(root, EML, "ExtensionNameValue") is None:
            _insert_after(root, f"{EML}Citation", iswk)

    # Remove v2.0.1-only elements
    for tag in REMOVED_ELEMENTS:
        for el in root.findall(tag):
            root.remove(el)


def _convert_interpretation(root: etree._Element, old_type: str, new_type: str):
    """Fix interpretation-specific elements."""
    # RepresentedInterpretation → InterpretedFeature
    for el in _els(root, RESQML, "RepresentedInterpretation"):
        el.tag = f"{RESQML}InterpretedFeature"


def _convert_representation(root: etree._Element, old_type: str, new_type: str):
    """Fix representation-specific elements."""
    # RepresentedInterpretation → RepresentedObject
    for el in _els(root, RESQML, "RepresentedInterpretation"):
        el.tag = f"{RESQML}RepresentedObject"


# ── WellboreTrajectory ────────────────────────────────────────────────────

def _convert_wellbore_trajectory(root: etree._Element):
    """Convert StartMd/FinishMd/MdUom to MdInterval."""
    start_el = _remove_el(root, RESQML, "StartMd")
    finish_el = _remove_el(root, RESQML, "FinishMd")
    uom_el = _remove_el(root, RESQML, "MdUom")
    _remove_el(root, RESQML, "MdDatum")  # MdDatum removed in v2.2

    if start_el is not None and finish_el is not None:
        start_val = start_el.text or "0"
        finish_val = finish_el.text or "0"
        uom_val = uom_el.text if uom_el is not None else "m"

        md_interval = etree.Element(f"{RESQML}MdInterval")
        _make_sub(md_interval, f"{EML}MdMin", start_val)
        _make_sub(md_interval, f"{EML}MdMax", finish_val)
        _make_sub(md_interval, f"{EML}Uom", uom_val)

        # Insert after RepresentedObject or after Citation
        rep_obj = _el(root, RESQML, "RepresentedObject")
        if rep_obj is not None:
            _insert_after(root, f"{RESQML}RepresentedObject", md_interval)
        else:
            _insert_after(root, f"{EML}Citation", md_interval)


# ── WellboreFrame ─────────────────────────────────────────────────────────

def _convert_wellbore_frame(root: etree._Element):
    """Remove NodePatch, WellboreMarker elements (invalid in v2.2)."""
    _remove_all(root, RESQML, "NodePatch")
    _remove_all(root, RESQML, "WellboreMarker")


# ── Grid2d ────────────────────────────────────────────────────────────────

def _convert_grid2d(root: etree._Element):
    """Unwrap Grid2dPatch and convert Offset→Dimension."""
    for patch in _els(root, RESQML, "Grid2dPatch"):
        # Move children up (except PatchIndex)
        for child in list(patch):
            local = etree.QName(child.tag).localname
            if local != "PatchIndex":
                root.append(child)
        root.remove(patch)

    # Convert Offset → Dimension in Point3dLatticeArray
    _convert_offset_to_dimension(root)


def _convert_offset_to_dimension(root: etree._Element):
    """Convert Point3dLatticeArray Offset elements to Dimension.

    v2.0.1: <Offset xsi:type="resqml2:Point3dOffset">
              <Offset xsi:type="resqml2:Point3d">...</Offset>  (direction vector)
              <Spacing ...>...</Spacing>
            </Offset>

    v2.2:   <Dimension xsi:type="resqml2:Point3dLatticeDimension">
              <Direction xsi:type="resqml2:Point3d">...</Direction>
              <Spacing ...>...</Spacing>
            </Dimension>
    """
    for el in list(root.iter()):
        xsi_type = el.get(f"{XSI}type", "")
        if xsi_type == "resqml2:Point3dOffset":
            el.tag = el.tag.replace("Offset", "Dimension")
            el.set(f"{XSI}type", "resqml2:Point3dLatticeDimension")
            # Rename inner Offset (direction vector) to Direction
            for inner in list(el):
                inner_type = inner.get(f"{XSI}type", "")
                if inner_type == "resqml2:Point3d":
                    inner.tag = inner.tag.replace("Offset", "Direction")


# ── ExtraMetadata → ExtensionNameValue ────────────────────────────────────

def _convert_extra_metadata(root: etree._Element):
    """Convert resqml2:ExtraMetadata to eml:ExtensionNameValue.

    v2.0.1: <resqml2:ExtraMetadata><resqml2:Name>...</resqml2:Name>
              <resqml2:Value>...</resqml2:Value></resqml2:ExtraMetadata>

    v2.2: <eml:ExtensionNameValue><eml:Name>...</eml:Name>
            <eml:Value>...</eml:Value></eml:ExtensionNameValue>

    Position: after CustomData, before type-specific elements (part of AbstractObject).
    """
    em_blocks = _els(root, RESQML, "ExtraMetadata")
    if not em_blocks:
        return

    env_elements = []
    for em in em_blocks:
        name_el = _el(em, RESQML, "Name")
        val_el = _el(em, RESQML, "Value")
        if name_el is not None and val_el is not None:
            env = etree.Element(f"{EML}ExtensionNameValue")
            _make_sub(env, f"{EML}Name", name_el.text or "")
            _make_sub(env, f"{EML}Value", val_el.text or "")
            env_elements.append(env)
        root.remove(em)

    # Insert after CustomData or Citation (AbstractObject sequence)
    custom_data = _el(root, EML, "CustomData")
    if custom_data is not None:
        ref_tag = f"{EML}CustomData"
    else:
        ref_tag = f"{EML}Citation"

    for env in reversed(env_elements):
        _insert_after(root, ref_tag, env)


# ── CustomData cleanup ────────────────────────────────────────────────────

def _clean_custom_data(root: etree._Element):
    """Remove DisabledMarkers and other invalid CustomData content."""
    for cd in _els(root, EML, "CustomData"):
        # Remove if it contains DisabledMarkers
        text = etree.tostring(cd, encoding="unicode")
        if "DisabledMarkers" in text:
            root.remove(cd)


# ── xsi:type cleanup ─────────────────────────────────────────────────────

def _strip_simple_xsi_types(root: etree._Element):
    """Remove xsi:type attributes for simple types that EML 2.3 rejects.

    Keep xsi:type only on the root element and on elements with polymorphic types
    (DataObjectReference, ExternalArray, Point3d, etc.)
    """
    for el in root.iter():
        if el == root:
            continue
        xsi_type = el.get(f"{XSI}type")
        if xsi_type and xsi_type in STRIP_XSI_TYPES:
            del el.attrib[f"{XSI}type"]


# ── Root element updates ─────────────────────────────────────────────────

def _update_root_element(root: etree._Element, old_type: str, new_type: str):
    """Update root element tag, xsi:type, schemaVersion."""
    # Update tag
    old_tag_variants = [
        f"{RESQML}obj_{old_type}",
        f"{RESQML}{old_type}",
        f"{EML}obj_{old_type}",
        f"{EML}{old_type}",
    ]
    new_ns = EML if "EpcExternalPartReference" in new_type else RESQML
    if root.tag in old_tag_variants:
        root.tag = f"{new_ns}{new_type}"

    # Update xsi:type
    xsi_type = root.get(f"{XSI}type", "")
    if xsi_type:
        root.set(f"{XSI}type", f"resqml2:{new_type}")

    # schemaVersion
    root.set("schemaVersion", "2.2")


# ── Format citation ──────────────────────────────────────────────────────

def _update_format(root: etree._Element):
    """Update Format citation to say v2.2."""
    citation = _el(root, EML, "Citation")
    if citation is not None:
        fmt = _el(citation, EML, "Format")
        if fmt is not None and fmt.text:
            fmt.text = fmt.text.replace("v2.0", "v2.2").replace("RESQML v2.2 (Drogon Demo)", "RESQML v2.2 (Drogon Demo)")


# ── Element ordering (AbstractObject base) ────────────────────────────────

def _reorder_abstract_object(root: etree._Element):
    """Ensure AbstractObject elements are in XSD order.

    EML 2.3: Aliases*, Citation, Existence?, ObjectVersionReason?,
             BusinessActivityHistory*, OSDUIntegration?, CustomData?,
             ExtensionNameValue*, <derived type elements>
    """
    BASE_ORDER = {
        f"{EML}Aliases": 1,
        f"{EML}Citation": 2,
        f"{EML}Existence": 3,
        f"{EML}ObjectVersionReason": 4,
        f"{EML}BusinessActivityHistory": 5,
        f"{EML}OSDUIntegration": 6,
        f"{EML}CustomData": 7,
        f"{EML}ExtensionNameValue": 8,
    }

    base_elements = []
    derived_elements = []

    for child in list(root):
        if child.tag in BASE_ORDER:
            base_elements.append((BASE_ORDER[child.tag], child))
        else:
            derived_elements.append(child)
        root.remove(child)

    base_elements.sort(key=lambda x: x[0])

    for _, el in base_elements:
        root.append(el)
    for el in derived_elements:
        root.append(el)


# ── Main entry point ──────────────────────────────────────────────────────

def convert_object_xml(xml_bytes: bytes, old_type: str,
                       h5_filename: str = "drogon.h5") -> tuple[bytes, str]:
    """Convert a single RESQML 2.0.1 XML object to RESQML 2.2.

    Returns (converted_xml_bytes, new_type_name).
    """
    new_type = _convert_type_name(old_type)

    # Parse XML
    root = etree.fromstring(xml_bytes)

    # 1. Update root element (tag, xsi:type, schemaVersion)
    _update_root_element(root, old_type, new_type)

    # 2. Update Format citation
    _update_format(root)

    # 3. Clean CustomData
    _clean_custom_data(root)

    # 4. Convert ExtraMetadata → ExtensionNameValue
    _convert_extra_metadata(root)

    # 5. Convert all DataObjectReferences
    _convert_all_dors(root)

    # 6. Convert HDF5 arrays → ExternalDataArray
    _convert_all_hdf5_arrays(root, h5_filename)

    # 7. Type-specific conversions
    bare = _bare_type(old_type)

    if bare in INTERPRETATION_TYPES:
        _convert_interpretation(root, bare, new_type)
    elif bare in REPRESENTATION_TYPES:
        _convert_representation(root, bare, new_type)

    if "Property" in new_type and new_type != "PropertyKind":
        _convert_property_elements(root, new_type)

    if "Feature" in new_type or new_type in ("Model", "BoundaryFeature",
                                              "RockVolumeFeature"):
        _convert_feature(root, bare, new_type)

    if "WellboreTrajectory" in new_type:
        _convert_wellbore_trajectory(root)

    if "WellboreFrame" in new_type:
        _convert_wellbore_frame(root)

    if "Grid2d" in new_type:
        _convert_grid2d(root)

    # 8. Reorder elements
    _reorder_abstract_object(root)
    if "Property" in new_type and new_type != "PropertyKind":
        _reorder_property_children(root, new_type)

    # 9. Strip unnecessary xsi:type attributes (last step)
    _strip_simple_xsi_types(root)

    # 10. Remove removed elements (safety net)
    for tag in REMOVED_ELEMENTS:
        for el in root.findall(f".//{tag}"):
            el.getparent().remove(el)

    # Serialize
    result = etree.tostring(root, xml_declaration=True, encoding="UTF-8",
                            pretty_print=True)
    return result, new_type


def make_property_kind_xml(kind_name: str) -> bytes:
    """Generate a PropertyKind EML 2.3 XML object."""
    pk_uuid = _pk_uuid(kind_name)
    quantity_class = _QUANTITY_CLASS_MAP.get(kind_name, "dimensionless")

    nsmap = {
        "eml": NS["eml"],
        "xsi": NS["xsi"],
    }
    root = etree.Element(f"{EML}PropertyKind", nsmap=nsmap)
    root.set("schemaVersion", "2.3")
    root.set("uuid", pk_uuid)
    root.set(f"{XSI}type", "eml:PropertyKind")

    citation = _make_sub(root, f"{EML}Citation")
    _make_sub(citation, f"{EML}Title", kind_name)
    _make_sub(citation, f"{EML}Originator", "Energistics")
    _make_sub(citation, f"{EML}Creation", "2025-01-01T00:00:00Z")
    _make_sub(citation, f"{EML}Format", "RESQML v2.2 Standard PropertyKind")

    _make_sub(root, f"{EML}QuantityClass", quantity_class)
    _make_sub(root, f"{EML}IsAbstract", "false")

    return etree.tostring(root, xml_declaration=True, encoding="UTF-8",
                          pretty_print=True)
