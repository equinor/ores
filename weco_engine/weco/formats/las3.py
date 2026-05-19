"""
weco.formats.las3 — LAS 3.0 reader
====================================

Read LAS 3.0 (Log ASCII Standard version 3.0) files, which use
a section-based format with multi-dimensional data support.

LAS 3.0 differences from LAS 2.0:
- Sections delimited by ``~Section_Name | Description``
- Data and parameters in tables with explicit column headers
- Support for multi-dimensional arrays
- Associated parameters per curve
- Section associations

Reference: CWLS LAS 3.0 specification (2000)

Todo §4.9 — LAS 3.0 reader
"""

from __future__ import annotations

import re
from typing import Optional


def read_las3(filepath: str) -> dict:
    """Read a LAS 3.0 file and return structured data.

    Parameters
    ----------
    filepath : str
        Path to the LAS 3.0 file.

    Returns
    -------
    dict
        ``{"version": str, "well": dict, "curves": dict,
        "data": dict[str, list[float]], "parameters": dict,
        "sections": dict}``
    """
    sections = {}
    current_section = None
    current_lines = []

    with open(filepath, "r") as f:
        for raw_line in f:
            line = raw_line.rstrip("\n\r")
            stripped = line.strip()

            # Skip empty lines and comments
            if not stripped or stripped.startswith("#"):
                continue

            # Section header: ~SectionName | Description
            if stripped.startswith("~"):
                if current_section is not None:
                    sections[current_section] = current_lines
                # Parse section name
                parts = stripped[1:].split("|", 1)
                current_section = parts[0].strip()
                current_lines = []
                continue

            if current_section is not None:
                current_lines.append(line)

    if current_section is not None:
        sections[current_section] = current_lines

    # Parse structured sections
    result = {
        "version": "",
        "well": {},
        "curves": {},
        "data": {},
        "parameters": {},
        "sections": sections,
    }

    # Version section
    if "Version Information" in sections or "VERSION INFORMATION" in sections:
        ver_key = "Version Information" if "Version Information" in sections else "VERSION INFORMATION"
        for line in sections[ver_key]:
            parsed = _parse_las3_line(line)
            if parsed:
                mnem, unit, val, desc = parsed
                if mnem.upper() == "VERS":
                    result["version"] = val

    # Well section
    for key in sections:
        if key.upper().startswith("WELL"):
            for line in sections[key]:
                parsed = _parse_las3_line(line)
                if parsed:
                    mnem, unit, val, desc = parsed
                    result["well"][mnem] = {
                        "unit": unit, "value": val, "description": desc
                    }

    # Curve section
    for key in sections:
        if key.upper().startswith("CURVE") or key.upper().startswith("LOG_DEFINITION"):
            for line in sections[key]:
                parsed = _parse_las3_line(line)
                if parsed:
                    mnem, unit, val, desc = parsed
                    result["curves"][mnem] = {
                        "unit": unit, "api_code": val, "description": desc
                    }

    # Parameter section
    for key in sections:
        if key.upper().startswith("PARAM"):
            for line in sections[key]:
                parsed = _parse_las3_line(line)
                if parsed:
                    mnem, unit, val, desc = parsed
                    result["parameters"][mnem] = {
                        "unit": unit, "value": val, "description": desc
                    }

    # Data section(s) — can be ASCII or tab-delimited
    for key in sections:
        if key.upper().startswith("LOG_DATA") or key.upper() in ("A", "ASCII"):
            _parse_las3_data(sections[key], result)

    return result


def _parse_las3_line(line: str) -> Optional[tuple]:
    """Parse a LAS 3.0 parameter/definition line.

    Format: ``MNEM.UNIT  VALUE : DESCRIPTION``
    """
    line = line.strip()
    if not line or line.startswith("#"):
        return None

    # Try standard LAS format: MNEM.UNIT VALUE : DESC
    match = re.match(
        r"^\s*(\S+)\s*\.\s*(\S*)\s+(.*?)\s*:\s*(.*)\s*$", line
    )
    if match:
        mnem = match.group(1)
        unit = match.group(2)
        value = match.group(3).strip()
        desc = match.group(4).strip()
        return mnem, unit, value, desc

    # Try pipe-delimited (LAS 3.0 table format)
    if "|" in line:
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 2:
            return parts[0], "", parts[1] if len(parts) > 1 else "", parts[2] if len(parts) > 2 else ""

    return None


def _parse_las3_data(lines: list[str], result: dict) -> None:
    """Parse the data section of a LAS 3.0 file."""
    if not lines:
        return

    # Determine curve names from the curves dict, or from header line
    curve_names = list(result["curves"].keys()) if result["curves"] else []

    data_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("~"):
            continue
        # Check if this is a header line (non-numeric first token)
        tokens = stripped.split()
        try:
            float(tokens[0])
            data_lines.append(tokens)
        except ValueError:
            # This is a column header line
            if not curve_names:
                curve_names = tokens
            continue

    if not curve_names:
        curve_names = [f"COL_{i}" for i in range(len(data_lines[0]))] if data_lines else []

    # Initialise data arrays
    for name in curve_names:
        result["data"][name] = []

    # Parse data
    for tokens in data_lines:
        for i, name in enumerate(curve_names):
            if i < len(tokens):
                try:
                    result["data"][name].append(float(tokens[i]))
                except ValueError:
                    result["data"][name].append(float("nan"))
            else:
                result["data"][name].append(float("nan"))


def las3_to_wells(filepath: str) -> "WellList":
    """Read a LAS 3.0 file and convert to WeCo WellList.

    Parameters
    ----------
    filepath : str
        Path to LAS 3.0 file.

    Returns
    -------
    WellList
        Single-well WellList.
    """
    from ..data import WellList

    parsed = read_las3(filepath)
    wl = WellList()

    well_name = parsed["well"].get("WELL", {}).get("value", "Unknown")
    if not well_name or well_name == "Unknown":
        import os
        well_name = os.path.splitext(os.path.basename(filepath))[0]

    curves = parsed["data"]
    if not curves:
        return wl

    # Determine size from first curve
    first_curve = next(iter(curves.values()))
    n = len(first_curve)

    # Get well coordinates
    x = float(parsed["well"].get("XCOORD", {}).get("value", 0) or 0)
    y = float(parsed["well"].get("YCOORD", {}).get("value", 0) or 0)

    w = wl.create_well(well_name, x=x, y=y, size=n)

    for name, values in curves.items():
        w.add_data(name, values)

    return wl
