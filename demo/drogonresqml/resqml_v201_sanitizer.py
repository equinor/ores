"""
resqml_v201_sanitizer.py – Reusable RESQML 2.0.1 XML sanitizer.

Uses lxml for proper XML manipulation. Ensures strict XSD compliance
against the RESQML 2.0.1 / EML 2.0 schemas.

Fixes handled:
  1. Namespace normalization (geosiris resqml: → resqml2:, strip unused ns)
  2. Root element cleanup (strip obj_ prefix, add xsi:type, add xmlns:xsd)
  3. Citation element ordering (VersionString before Description per XSD)
  4. Invalid UOM values (v/v → m3/m3)
  5. Invalid PropertyKind names → closest valid ResqmlPropertyKind enum value
  6. ExtraMetadata position (after CustomData, before type-specific elements)
  7. ExtraMetadata content fix (mirror corrected UOM/PropertyKind values)
  8. DisabledMarkers vendor extension removal (empty uuid violates pattern)
  9. CustomData StratigraphicColumn → ext: namespace (avoid lax validation clash)
  10. Missing Domain element in AbstractFeatureInterpretation subtypes
  11. Closing tag obj_ mismatch fix

Usage:
    from resqml_v201_sanitizer import sanitize_object_xml
"""
from __future__ import annotations

import re
from copy import deepcopy
from lxml import etree

# ── Namespace URIs ────────────────────────────────────────────────────────

NS = {
    "eml": "http://www.energistics.org/energyml/data/commonv2",
    "resqml2": "http://www.energistics.org/energyml/data/resqmlv2",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
    "xsd": "http://www.w3.org/2001/XMLSchema",
    "ext": "http://www.equinor.com/resqml/extensions",
}

EML = f"{{{NS['eml']}}}"
RESQML = f"{{{NS['resqml2']}}}"
XSI = f"{{{NS['xsi']}}}"
XSD = f"{{{NS['xsd']}}}"
EXT = f"{{{NS['ext']}}}"

# ── Valid ResqmlPropertyKind enum values that require mapping ──────────────

PROPERTY_KIND_MAP = {
    "mass per volume": "density",
    "shale volume": "net to gross ratio",
    "volume fraction": "net to gross ratio",
}

# Abstract property kinds must not be directly assigned to properties.
# Map them to their most common concrete descendant.
ABSTRACT_KIND_FIX = {
    "volume per volume": "net to gross ratio",
    "dimensionless": "property multiplier",
    "categorical": "code",
    "continuous": "property multiplier",
    "discrete": "index",
    "quantity": "property multiplier",
    "unitless": "property multiplier",
    "RESQML root property": "property multiplier",
    "angle per length": "property multiplier",
    "angle per time": "property multiplier",
    "angle per volume": "property multiplier",
    "area per area": "net to gross ratio",
    "area per volume": "property multiplier",
    "energy length per area": "property multiplier",
    "energy length per time area temperature": "property multiplier",
    "energy per length": "property multiplier",
    "force area": "property multiplier",
    "force length per length": "property multiplier",
    "force per force": "property multiplier",
    "force per volume": "property multiplier",
    "length per length": "property multiplier",
    "length per temperature": "property multiplier",
    "length per volume": "property multiplier",
    "mass length": "property multiplier",
    "mass per length": "property multiplier",
    "mass per time per area": "property multiplier",
    "mass per time per length": "property multiplier",
    "mass per volume per length": "property multiplier",
    "per area": "property multiplier",
    "per electric potential": "property multiplier",
    "per force": "property multiplier",
    "per length": "property multiplier",
    "per mass": "property multiplier",
    "per volume": "property multiplier",
    "permeability rock": "rock permeability",
    "power per volume": "property multiplier",
    "pressure per time": "property multiplier",
    "pressure squared": "property multiplier",
    "pressure squared per force time per area": "property multiplier",
    "pressure time per volume": "property multiplier",
    "resistivity per length": "property multiplier",
    "time per length": "property multiplier",
    "time per volume": "property multiplier",
    "volume length per time": "property multiplier",
    "volume per area": "property multiplier",
    "volume per length": "property multiplier",
    "volume per time per area": "property multiplier",
    "volume per time per length": "property multiplier",
    "volume per time per time": "property multiplier",
    "volume per time per volume": "property multiplier",
}

# Property kinds that belong to the continuous hierarchy (descend from "quantity")
# A DiscreteProperty must NOT use these.
CONTINUOUS_ONLY_KINDS = {
    "length", "depth", "cell length", "thickness", "velocity",
    "pressure", "density", "temperature", "thermodynamic temperature",
    "porosity", "saturation", "permeability rock", "rock permeability",
    "amplitude", "volume", "area", "angle", "time", "mass",
    "net to gross ratio", "formation volume factor",
    "property multiplier", "relative permeability",
}

# The only valid concrete discrete kind in the standard
DISCRETE_FALLBACK_KIND = "index"

# Types that require a Domain element (AbstractFeatureInterpretation subtypes)
INTERPRETATION_TYPES = {
    "FaultInterpretation",
    "HorizonInterpretation",
    "StratigraphicUnitInterpretation",
    "StratigraphicColumnRankInterpretation",
    "StructuralOrganizationInterpretation",
    "WellboreInterpretation",
    "GeobodyInterpretation",
    "GeobodyBoundaryInterpretation",
    "EarthModelInterpretation",
}

# ── Element ordering reference ────────────────────────────────────────────
# AbstractCitedDataObject: Citation[1], Aliases[0..*], CustomData[0..1]
# AbstractResqmlDataObject adds: ExtraMetadata[0..*]
# Then type-specific elements follow.

ABSTRACT_OBJECT_ORDER = {
    f"{EML}Citation": 1,
    f"{EML}Aliases": 2,
    f"{EML}CustomData": 3,
    f"{RESQML}ExtraMetadata": 4,
}

# Citation child order per XSD:
# Title, Originator, Creation, Format, Editor?, LastUpdate?, VersionString?, Description?, DescriptiveKeywords?
CITATION_ORDER = {
    f"{EML}Title": 1,
    f"{EML}Originator": 2,
    f"{EML}Creation": 3,
    f"{EML}Format": 4,
    f"{EML}Editor": 5,
    f"{EML}LastUpdate": 6,
    f"{EML}VersionString": 7,
    f"{EML}Description": 8,
    f"{EML}DescriptiveKeywords": 9,
}


# ── Helpers ───────────────────────────────────────────────────────────────

def _el(parent: etree._Element, ns: str, local: str) -> etree._Element | None:
    return parent.find(f"{ns}{local}")


def _els(parent: etree._Element, ns: str, local: str) -> list[etree._Element]:
    return parent.findall(f"{ns}{local}")


def _remove_el(parent: etree._Element, ns: str, local: str) -> etree._Element | None:
    el = parent.find(f"{ns}{local}")
    if el is not None:
        parent.remove(el)
    return el


def _remove_all(parent: etree._Element, ns: str, local: str) -> list[etree._Element]:
    found = parent.findall(f"{ns}{local}")
    for el in found:
        parent.remove(el)
    return found


def _insert_after(parent: etree._Element, ref_tag: str, new_el: etree._Element):
    idx = None
    for i, child in enumerate(parent):
        if child.tag == ref_tag:
            idx = i
    if idx is not None:
        parent.insert(idx + 1, new_el)
    else:
        parent.append(new_el)


def _make_sub(parent: etree._Element, tag: str, text: str | None = None) -> etree._Element:
    el = etree.SubElement(parent, tag)
    if text is not None:
        el.text = text
    return el


def _bare_type(tag_or_name: str) -> str:
    """Strip namespace URI and obj_ prefix to get bare type name."""
    local = etree.QName(tag_or_name).localname if "{" in tag_or_name else tag_or_name
    return local.replace("obj_", "")


# ── Namespace normalization (pre-parse) ───────────────────────────────────

def _normalize_namespaces(xml_text: str) -> str:
    """Normalize geosiris namespace prefixes before parsing.

    Source uses 'resqml:' prefix → normalize to 'resqml2:'.
    Strip unused prodml/witsml namespace declarations.
    Fix obj_ prefix on root element tags.
    """
    # Namespace declaration: resqml → resqml2
    xml_text = xml_text.replace(
        'xmlns:resqml="http://www.energistics.org/energyml/data/resqmlv2"',
        'xmlns:resqml2="http://www.energistics.org/energyml/data/resqmlv2"',
    )
    # Strip unused namespace declarations
    xml_text = xml_text.replace(
        'xmlns:prodml="http://www.energistics.org/energyml/data/prodmlv2" ', ""
    )
    xml_text = xml_text.replace(
        'xmlns:witsml="http://www.energistics.org/energyml/data/witsmlv2" ', ""
    )
    # Element/attribute prefix: resqml: → resqml2:
    xml_text = xml_text.replace("<resqml:", "<resqml2:")
    xml_text = xml_text.replace("</resqml:", "</resqml2:")
    # Attribute values referencing the prefix (xsi:type="resqml:Foo")
    xml_text = xml_text.replace('"resqml:', '"resqml2:')

    # Strip obj_ from root element opening and closing tags
    xml_text = re.sub(r"<resqml2:obj_([A-Za-z0-9]+)", r"<resqml2:\1", xml_text, count=1)
    xml_text = re.sub(r"</resqml2:obj_([A-Za-z0-9]+)>", r"</resqml2:\1>", xml_text)
    xml_text = re.sub(r"<eml:obj_([A-Za-z0-9]+)", r"<eml:\1", xml_text, count=1)
    xml_text = re.sub(r"</eml:obj_([A-Za-z0-9]+)>", r"</eml:\1>", xml_text)

    # Add xmlns:xsd if xsd: prefix is used but not declared
    if "xsd:" in xml_text and 'xmlns:xsd=' not in xml_text:
        xml_text = xml_text.replace(
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"',
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            'xmlns:xsd="http://www.w3.org/2001/XMLSchema"',
        )

    return xml_text


# ── Citation ordering ─────────────────────────────────────────────────────

def _fix_citation_order(citation: etree._Element):
    """Ensure Citation children are in XSD sequence order."""
    children = list(citation)
    if not children:
        return

    ordered = sorted(children, key=lambda c: CITATION_ORDER.get(c.tag, 99))

    # Only reorder if actually out of order
    current_order = [c.tag for c in children]
    correct_order = [c.tag for c in ordered]
    if current_order == correct_order:
        return

    for child in children:
        citation.remove(child)
    for child in ordered:
        citation.append(child)


# ── PropertyKind fix ──────────────────────────────────────────────────────

def _fix_property_kinds(root: etree._Element):
    """Replace invalid PropertyKind enum values with valid ones.

    Also resolves abstract property kinds to concrete descendants
    and fixes discrete/continuous property kind compatibility.
    """
    bare_type = _bare_type(etree.QName(root.tag).localname)
    is_discrete = bare_type in ("DiscreteProperty", "CategoricalProperty")

    for kind_el in root.iter(f"{RESQML}Kind"):
        if not kind_el.text:
            continue

        # Step 1: Apply explicit invalid-name mappings
        if kind_el.text in PROPERTY_KIND_MAP:
            kind_el.text = PROPERTY_KIND_MAP[kind_el.text]

        # Step 2: Resolve abstract kinds to concrete descendants
        if kind_el.text in ABSTRACT_KIND_FIX:
            kind_el.text = ABSTRACT_KIND_FIX[kind_el.text]

        # Step 3: Fix discrete/continuous mismatch
        if is_discrete and kind_el.text in CONTINUOUS_ONLY_KINDS:
            kind_el.text = DISCRETE_FALLBACK_KIND


# ── UOM fix ───────────────────────────────────────────────────────────────

def _fix_uom(root: etree._Element):
    """Replace invalid UOM values."""
    for uom_el in root.iter(f"{RESQML}UOM"):
        if uom_el.text == "v/v":
            uom_el.text = "m3/m3"


# ── ExtraMetadata fix (position + content) ────────────────────────────────

def _fix_extra_metadata(root: etree._Element):
    """Reposition ExtraMetadata and fix content to match corrected values.

    XSD order: Citation, Aliases*, CustomData?, ExtraMetadata*, <derived>
    """
    em_blocks = _remove_all(root, RESQML, "ExtraMetadata")
    if not em_blocks:
        return

    # Fix ExtraMetadata content: mirror UOM and PropertyKind corrections
    for em in em_blocks:
        val_el = _el(em, RESQML, "Value")
        if val_el is not None and val_el.text:
            if val_el.text == "v/v":
                val_el.text = "m3/m3"
            if val_el.text in PROPERTY_KIND_MAP:
                val_el.text = PROPERTY_KIND_MAP[val_el.text]

    # Find insertion point: after CustomData if present, else after Aliases, else after Citation
    ref_tag = None
    if _el(root, EML, "CustomData") is not None:
        ref_tag = f"{EML}CustomData"
    elif _els(root, EML, "Aliases"):
        ref_tag = f"{EML}Aliases"
    elif _el(root, EML, "Citation") is not None:
        ref_tag = f"{EML}Citation"

    # Insert in reverse so they end up in original order
    for em in reversed(em_blocks):
        if ref_tag:
            _insert_after(root, ref_tag, em)
        else:
            root.insert(0, em)


# ── DisabledMarkers removal ──────────────────────────────────────────────

def _remove_disabled_markers(root: etree._Element):
    """Remove DisabledMarkers vendor extension from CustomData.

    Has xsi:type with empty uuid="" violating UUID pattern facet.
    """
    for custom_data in _els(root, EML, "CustomData"):
        text = etree.tostring(custom_data, encoding="unicode")
        if "DisabledMarkers" in text:
            root.remove(custom_data)


# ── CustomData StratigraphicColumn fix ────────────────────────────────────

def _fix_custom_data_strat_column(root: etree._Element):
    """Change resqml2:StratigraphicColumn in CustomData to ext: namespace.

    processContents="lax" in CustomData resolves resqml2: elements against
    the global schema, which expects the full obj_StratigraphicColumn type.
    Use a custom namespace to avoid lax validation clash.
    """
    for custom_data in _els(root, EML, "CustomData"):
        for strat_col in list(custom_data.iter(f"{RESQML}StratigraphicColumn")):
            # Change tag to ext: namespace
            strat_col.tag = f"{EXT}StratigraphicColumn"
            # Remove xsi:type to prevent lax validation of children
            if f"{XSI}type" in strat_col.attrib:
                del strat_col.attrib[f"{XSI}type"]
            # Recursively change child tags from resqml2: to ext:
            for child in strat_col.iter():
                if child.tag.startswith(RESQML):
                    local = etree.QName(child.tag).localname
                    child.tag = f"{EXT}{local}"


# ── Missing Domain element ────────────────────────────────────────────────

def _ensure_domain_element(root: etree._Element, obj_type: str):
    """Add Domain element if missing for AbstractFeatureInterpretation subtypes.

    XSD requires Domain before InterpretedFeature.
    """
    bare = _bare_type(obj_type)
    if bare not in INTERPRETATION_TYPES:
        return

    if _el(root, RESQML, "Domain") is not None:
        return

    interpreted = _el(root, RESQML, "InterpretedFeature")
    if interpreted is None:
        return

    domain_el = etree.Element(f"{RESQML}Domain")
    domain_el.text = "depth"
    domain_el.tail = interpreted.tail

    # Insert Domain just before InterpretedFeature
    idx = list(root).index(interpreted)
    root.insert(idx, domain_el)


# ── xsi:type on root element ─────────────────────────────────────────────

def _ensure_root_xsi_type(root: etree._Element, obj_type: str):
    """Add xsi:type on root element if not present.

    Required by fesapi for object type identification.
    Format: xsi:type="ns:obj_TypeName"
    """
    if f"{XSI}type" in root.attrib:
        return

    bare = _bare_type(obj_type)
    # Determine namespace prefix from root tag
    if root.tag.startswith(EML):
        root.set(f"{XSI}type", f"eml:obj_{bare}")
    else:
        root.set(f"{XSI}type", f"resqml2:obj_{bare}")


# ── AbstractObject element reordering ─────────────────────────────────────

def _reorder_abstract_object_elements(root: etree._Element):
    """Ensure Citation, Aliases, CustomData, ExtraMetadata are in XSD order,
    followed by all type-specific elements in their original order.

    EML 2.0 / RESQML 2.0.1 order:
      Citation[1], Aliases[0..*], CustomData[0..1], ExtraMetadata[0..*], <derived>
    """
    base_elements = []
    derived_elements = []

    for child in list(root):
        if child.tag in ABSTRACT_OBJECT_ORDER:
            base_elements.append((ABSTRACT_OBJECT_ORDER[child.tag], child))
        else:
            derived_elements.append(child)
        root.remove(child)

    base_elements.sort(key=lambda x: x[0])

    for _, el in base_elements:
        root.append(el)
    for el in derived_elements:
        root.append(el)


# ── Main entry point ──────────────────────────────────────────────────────

def sanitize_object_xml(xml_bytes: bytes, obj_type: str) -> bytes:
    """Sanitize a single RESQML 2.0.1 XML object for strict XSD compliance.

    Args:
        xml_bytes: Raw XML bytes (may have geosiris namespace format).
        obj_type: Object type name (with or without obj_ prefix).

    Returns:
        Sanitized XML bytes, XSD-compliant.
    """
    xml_text = xml_bytes.decode("utf-8")

    # 1. Pre-parse namespace normalization (text-level, before lxml parsing)
    xml_text = _normalize_namespaces(xml_text)

    # 2. Parse with lxml
    root = etree.fromstring(xml_text.encode("utf-8"))

    # 3. Fix Citation element ordering
    citation = _el(root, EML, "Citation")
    if citation is not None:
        _fix_citation_order(citation)

    # 4. Fix invalid PropertyKind enum values
    _fix_property_kinds(root)

    # 5. Fix invalid UOM values
    _fix_uom(root)

    # 6. Remove DisabledMarkers vendor extension
    _remove_disabled_markers(root)

    # 7. Fix CustomData StratigraphicColumn namespace
    _fix_custom_data_strat_column(root)

    # 8. Reposition and fix ExtraMetadata
    _fix_extra_metadata(root)

    # 9. Add missing Domain element for interpretation types
    _ensure_domain_element(root, obj_type)

    # 10. Add xsi:type on root element
    _ensure_root_xsi_type(root, obj_type)

    # 11. Ensure AbstractObject elements are in XSD order
    _reorder_abstract_object_elements(root)

    # Serialize with declaration
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8",
                          pretty_print=True)
