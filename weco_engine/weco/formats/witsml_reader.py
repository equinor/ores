"""
weco.formats.witsml_reader — WITSML reader stub
=================================================

Read WITSML (Wellsite Information Transfer Standard Markup Language)
data.  WITSML is an XML-based format used for real-time and historical
well data transfer.

This is a minimal parser for WITSML v1.4.1 log objects.

Todo §4.11 — WITSML reader (P3)
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Optional


# WITSML namespace
NS = {"witsml": "http://www.witsml.org/schemas/1series"}


def read_witsml_log(filepath: str) -> "WellList":
    """Read a WITSML log file and convert to WeCo WellList.

    Supports WITSML v1.4.1 log objects (XML format).

    Parameters
    ----------
    filepath : str
        Path to WITSML XML file.

    Returns
    -------
    WellList
        Converted well data.
    """
    from ..data import WellList

    tree = ET.parse(filepath)
    root = tree.getroot()

    wl = WellList()

    # Handle namespace
    ns = _detect_namespace(root)

    # Find log elements
    logs = root.findall(f".//{{{ns}}}log") if ns else root.findall(".//log")
    if not logs:
        # Try without namespace
        logs = [root] if root.tag.endswith("log") else []

    for log in logs:
        well_name = _get_text(log, "nameWell", ns) or "Unknown"
        wellbore = _get_text(log, "nameWellbore", ns) or ""

        # Get curve info
        curve_info = log.findall(f".//{{{ns}}}logCurveInfo") if ns else log.findall(".//logCurveInfo")
        curve_names = []
        for ci in curve_info:
            mnemonic = _get_text(ci, "mnemonic", ns)
            if mnemonic:
                curve_names.append(mnemonic)

        # Get data
        data_sections = log.findall(f".//{{{ns}}}logData") if ns else log.findall(".//logData")
        if not data_sections:
            continue

        # Parse data rows
        all_data = {name: [] for name in curve_names}
        for data_sec in data_sections:
            rows = data_sec.findall(f".//{{{ns}}}data") if ns else data_sec.findall(".//data")
            for row in rows:
                text = row.text or ""
                values = text.split(",")
                for i, name in enumerate(curve_names):
                    if i < len(values):
                        try:
                            all_data[name].append(float(values[i].strip()))
                        except ValueError:
                            all_data[name].append(float("nan"))

        if not all_data or not curve_names:
            continue

        n_samples = len(all_data.get(curve_names[0], []))
        if n_samples == 0:
            continue

        w = wl.create_well(well_name, size=n_samples)
        for name, values in all_data.items():
            if values:
                w.add_data(name, values)

    return wl


def _detect_namespace(root: ET.Element) -> str:
    """Detect WITSML namespace from root element."""
    tag = root.tag
    if "{" in tag:
        return tag[1:tag.index("}")]
    return ""


def _get_text(element: ET.Element, child_tag: str, ns: str) -> Optional[str]:
    """Get text content of a child element."""
    if ns:
        child = element.find(f"{{{ns}}}{child_tag}")
    else:
        child = element.find(child_tag)
    return child.text.strip() if child is not None and child.text else None


def is_available() -> bool:
    """WITSML reader is always available (uses stdlib xml)."""
    return True
