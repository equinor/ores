"""
GOCAD ASCII format common parser.

Handles the shared structure of all GOCAD files:
  GOCAD <ObjectType> <version>
  HEADER { name: ... }
  PROPERTIES ...
  <body>
  END

Usage::

    from weco.formats.gocad_common import parse_gocad_file

    obj = parse_gocad_file("well.wl")
    print(obj.object_type)    # "Well"
    print(obj.header)         # {"name": "Well_01", ...}
    print(obj.properties)     # ["GR", "NPHI"]
    print(obj.body_lines)     # raw lines between header and END
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Optional


@dataclass
class GocadObject:
    """Parsed GOCAD ASCII file."""
    object_type: str = ""
    version: str = ""
    header: Dict[str, str] = field(default_factory=dict)
    properties: List[str] = field(default_factory=list)
    prop_legal_ranges: Dict[str, tuple] = field(default_factory=dict)
    prop_no_data: Dict[str, float] = field(default_factory=dict)
    coordinate_system: Dict[str, str] = field(default_factory=dict)
    body_lines: List[str] = field(default_factory=list)
    path: str = ""


def parse_gocad_file(path: str) -> GocadObject:
    """
    Parse a GOCAD ASCII file into structured sections.

    Parameters
    ----------
    path : str
        Path to .wl, .ts, .pl, .vs, or other GOCAD file.

    Returns
    -------
    GocadObject
    """
    obj = GocadObject(path=str(path))

    with open(path, "r", errors="replace") as f:
        lines = f.readlines()

    if not lines:
        raise ValueError(f"Empty GOCAD file: {path}")

    # Line 0: GOCAD <type> <version>
    parts = lines[0].strip().split()
    if len(parts) < 2 or parts[0] != "GOCAD":
        raise ValueError(f"Not a GOCAD file (first line: {lines[0].strip()!r})")
    obj.object_type = parts[1]
    obj.version = parts[2] if len(parts) > 2 else ""

    in_header = False
    i = 1
    while i < len(lines):
        line = lines[i].strip()
        i += 1

        if not line or line.startswith("#"):
            continue

        # Header block
        if line.startswith("HEADER"):
            in_header = True
            # Handle HEADER { on same line
            if "{" in line:
                continue
            continue

        if in_header:
            if line.startswith("}"):
                in_header = False
                continue
            if ":" in line:
                k, _, v = line.partition(":")
                obj.header[k.strip()] = v.strip()
            continue

        # Properties
        if line.startswith("PROPERTIES"):
            obj.properties = line.split()[1:]
            continue

        if line.startswith("PROP_LEGAL_RANGES"):
            parts = line.split()
            if len(parts) >= 4:
                obj.prop_legal_ranges[parts[1]] = (float(parts[2]), float(parts[3]))
            continue

        if line.startswith("NO_DATA_VALUES"):
            parts = line.split()
            for j, p in enumerate(obj.properties):
                if j + 1 < len(parts):
                    try:
                        obj.prop_no_data[p] = float(parts[j + 1])
                    except ValueError:
                        pass
            continue

        if line.startswith("COORDINATE_SYSTEM"):
            parts = line.split(None, 1)
            if len(parts) > 1:
                obj.coordinate_system["system"] = parts[1]
            continue

        if line == "END":
            break

        # Everything else is body
        obj.body_lines.append(line)

    return obj


def name_from_header(obj: GocadObject) -> str:
    """Extract object name from header dict."""
    return obj.header.get("name", obj.header.get("NAME",
           Path(obj.path).stem))
