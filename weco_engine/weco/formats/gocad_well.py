"""
GOCAD Well (.wl) reader/writer.

Reads GOCAD well files containing:
  - Well trajectory (WREF lines: MD, X, Y, Z)
  - Well logs (ZONE lines: MD, values per property)
  - Markers (MRKR lines: name, MD)

Produces standard ``weco.data.Well`` objects.

Usage::

    from weco.formats.gocad_well import read_gocad_well, write_gocad_well

    wells = read_gocad_well("my_well.wl")  # list of Well objects
"""

from typing import List, Optional
from pathlib import Path

from weco.data import Well, WellList
from .gocad_common import parse_gocad_file, name_from_header


def read_gocad_well(path: str) -> List[Well]:
    """
    Read a GOCAD Well file and return Well objects.

    Parameters
    ----------
    path : str
        Path to .wl file.

    Returns
    -------
    list of weco.data.Well
    """
    obj = parse_gocad_file(path)

    well = Well()
    well.name = name_from_header(obj)
    prop_names = obj.properties  # column names for ZONE data

    trajectory_md = []
    trajectory_x = []
    trajectory_y = []
    trajectory_z = []
    zone_data = {p: [] for p in prop_names}
    zone_md = []
    markers = {}  # name → MD

    for line in obj.body_lines:
        parts = line.split()
        if not parts:
            continue

        keyword = parts[0]

        if keyword == "WREF":
            # Trajectory: WREF x y z
            # or WREF md x y z (depends on variant)
            values = [float(v) for v in parts[1:]]
            if len(values) >= 4:
                trajectory_md.append(values[0])
                trajectory_x.append(values[1])
                trajectory_y.append(values[2])
                trajectory_z.append(values[3])
            elif len(values) == 3:
                trajectory_x.append(values[0])
                trajectory_y.append(values[1])
                trajectory_z.append(values[2])

        elif keyword in ("ZONE", "LOG"):
            # ZONE md val1 val2 ... valN
            values = parts[1:]
            if len(values) >= 1 + len(prop_names):
                md = float(values[0])
                zone_md.append(md)
                for j, pname in enumerate(prop_names):
                    try:
                        zone_data[pname].append(float(values[j + 1]))
                    except (ValueError, IndexError):
                        zone_data[pname].append(0.0)
            elif len(values) >= 1:
                # MD only
                zone_md.append(float(values[0]))

        elif keyword == "MRKR":
            # MRKR name md
            if len(parts) >= 3:
                mname = parts[1]
                try:
                    mmd = float(parts[2])
                    markers[mname] = mmd
                except ValueError:
                    pass

        elif keyword in ("VRTX", "PVRTX", "ATOM"):
            # Vertex data — common in point-set-like wells
            values = parts[1:]
            if len(values) >= 4:
                try:
                    trajectory_x.append(float(values[1]))
                    trajectory_y.append(float(values[2]))
                    trajectory_z.append(float(values[3]))
                    # Additional property values
                    for j, pname in enumerate(prop_names):
                        if j + 4 < len(values):
                            zone_data.setdefault(pname, []).append(float(values[j + 4]))
                except ValueError:
                    pass

    # Build Well object
    if zone_md:
        well.size = len(zone_md)
        well.data["Depth"] = zone_md
        for pname, vals in zone_data.items():
            if vals and len(vals) == well.size:
                # Replace no-data
                ndv = obj.prop_no_data.get(pname)
                if ndv is not None:
                    vals = [0.0 if v == ndv else v for v in vals]
                well.data[pname] = vals
    elif trajectory_md:
        well.size = len(trajectory_md)
        well.data["Depth"] = trajectory_md
        if trajectory_x:
            well.data["X"] = trajectory_x
            well.data["Y"] = trajectory_y
            well.data["Z"] = trajectory_z
    elif trajectory_x:
        well.size = len(trajectory_x)
        well.data["X"] = trajectory_x
        well.data["Y"] = trajectory_y
        well.data["Z"] = trajectory_z

    # Set well coordinates from first trajectory point or header
    if trajectory_x:
        well.x = trajectory_x[0]
        well.y = trajectory_y[0]
    elif "x" in obj.header:
        try:
            well.x = float(obj.header["x"])
            well.y = float(obj.header.get("y", "0"))
        except ValueError:
            pass

    # Store markers as a region
    if markers and well.size > 0 and "Depth" in well.data:
        depths = well.data["Depth"]
        marker_region = []
        for mname, mmd in sorted(markers.items(), key=lambda x: x[1]):
            # Find nearest depth index
            best_idx = min(range(len(depths)), key=lambda i: abs(depths[i] - mmd))
            marker_region.append((hash(mname) % 10000, best_idx, 1))
        well.region["Markers"] = marker_region

    return [well]


def read_gocad_wells_to_welllist(path: str) -> WellList:
    """Read GOCAD well file(s) and return as WellList."""
    wells = read_gocad_well(path)
    wl = WellList.__new__(WellList)
    wl.wells = wells
    return wl


def write_gocad_well(
    well: Well,
    path: str,
    properties: List[str] = None,
    log_names: List[str] = None,
    strat_column: Optional[dict] = None,
    zone_colours: Optional[dict] = None,
):
    """
    Write a Well as GOCAD .wl file.

    Parameters
    ----------
    well : weco.data.Well
    path : str
    properties : list of str, optional
        Data keys to export as ZONE columns. If None, all data except Depth.
    log_names : list of str, optional
        Alias for properties (§15.15 compatibility).
    strat_column : dict, optional
        §15.11 — Stratigraphic column header.
        ``{zone_index: {"name": str, "age_top": float, "age_base": float}}``
    zone_colours : dict, optional
        §15.11 — Zone colours: ``{zone_name: (r, g, b)}``
    """
    if log_names is not None and properties is None:
        properties = log_names
    if properties is None:
        properties = [k for k in well.data if k.upper() not in ("DEPTH", "MD")]

    depth_key = None
    for dk in ("Depth", "DEPTH", "MD"):
        if dk in well.data:
            depth_key = dk
            break

    with open(path, "w") as f:
        f.write(f"GOCAD Well 1.0\n")
        f.write(f"HEADER {{\n")
        f.write(f"  name: {well.name}\n")
        if well.x != 0 or well.y != 0:
            f.write(f"  x: {well.x}\n")
            f.write(f"  y: {well.y}\n")

        # §15.11 — Strat column in header
        if strat_column:
            f.write(f"  *strat_column: {len(strat_column)} units\n")
            for zi, info in sorted(strat_column.items()):
                name = info.get("name", f"Zone_{zi}")
                age_top = info.get("age_top", "")
                age_base = info.get("age_base", "")
                f.write(f"  *strat_unit_{zi}: {name}")
                if age_top:
                    f.write(f" {age_top}")
                if age_base:
                    f.write(f" {age_base}")
                f.write("\n")

        # §15.11 — Zone colours
        if zone_colours:
            for zname, (r, g, b) in zone_colours.items():
                f.write(f"  *zone_colour_{zname}: {r} {g} {b}\n")

        f.write(f"}}\n")

        if properties:
            f.write(f"PROPERTIES {' '.join(properties)}\n")

        for i in range(well.size):
            md = well.data[depth_key][i] if depth_key else float(i)
            vals = " ".join(
                f"{well.data[p][i]:.6g}" if p in well.data and i < len(well.data[p]) else "0"
                for p in properties
            )
            f.write(f"ZONE {md:.4f} {vals}\n")

        f.write("END\n")


# Register with the format system
try:
    from weco.formats import register_reader
    register_reader("gocad_well", read_gocad_wells_to_welllist)
except ImportError:
    pass


def write_gocad_vset(wells: List[Well], path: str, property_name: str = "horizon"):
    """
    Write well marker / horizon picks as a GOCAD VSet (.vs) point set.

    §15.12 — Each point is (X, Y, Z) with an optional integer property
    identifying the horizon index.

    Parameters
    ----------
    wells : list of Well
    path : str
        Output .vs file path.
    property_name : str
        Name of the integer property column (default ``horizon``).
    """
    with open(path, "w") as f:
        f.write("GOCAD VSet 1.0\n")
        f.write("HEADER {\n")
        f.write("  name: well_picks\n")
        f.write("}\n")
        f.write(f"PROPERTIES {property_name}\n")

        vid = 1
        for well in wells:
            depth_key = None
            for dk in ("Depth", "DEPTH", "MD"):
                if dk in well.data:
                    depth_key = dk
                    break
            x = getattr(well, "x", 0.0) or 0.0
            y = getattr(well, "y", 0.0) or 0.0
            depths = well.data.get(depth_key, []) if depth_key else []
            for idx, d in enumerate(depths):
                f.write(f"VRTX {vid} {x:.2f} {y:.2f} {-d:.2f} {idx}\n")
                vid += 1

        f.write("END\n")
