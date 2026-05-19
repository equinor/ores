"""
weco.formats — Unified file format registry
============================================

Provides a single ``read_wells()`` entry point that auto-detects
the file format and returns a standard ``weco.data.WellList``.

Usage::

    from weco.formats import read_wells, detect_format

    wl = read_wells("data.wells.txt")   # native
    wl = read_wells("data.las")         # LAS 2.0
    wl = read_wells("data.epc")         # RESQML
    wl = read_wells("data.csv", columns=["WELL","DEPTH","GR"])

    fmt = detect_format("somefile.wl")  # → "gocad_well"
"""

from pathlib import Path
from typing import Optional, List, Dict, Any
import os

# ─── Format detection ──────────────────────────────────────────────────

FORMAT_EXT_MAP = {
    ".wells.txt": "weco",
    ".las":       "las",
    ".las3":      "las3",
    ".epc":       "resqml",
    ".csv":       "csv",
    ".wl":        "gocad_well",
    ".ts":        "gocad_tsurf",
    ".pl":        "gocad_pline",
    ".vs":        "gocad_vset",
    ".rmswell":   "rms_well",
    ".dlis":      "dlis",
    ".xml":       "witsml",
}


def detect_format(path: str) -> Optional[str]:
    """
    Detect file format from extension and (optionally) magic bytes.

    Returns format key string or None.
    """
    p = Path(path)
    name = p.name.lower()

    # Check compound extensions first
    if name.endswith(".wells.txt"):
        return "weco"

    # Single extension
    ext = p.suffix.lower()
    if ext in FORMAT_EXT_MAP:
        return FORMAT_EXT_MAP[ext]

    # Sniff first line for format magic
    try:
        with open(path, "r", errors="ignore") as f:
            first_line = f.readline(200).strip()
        if first_line.startswith("GOCAD"):
            obj_type = first_line.split()[1].lower() if len(first_line.split()) > 1 else ""
            if "well" in obj_type:
                return "gocad_well"
            if "tsurf" in obj_type:
                return "gocad_tsurf"
            if "pline" in obj_type:
                return "gocad_pline"
            if "vset" in obj_type:
                return "gocad_vset"
            return "gocad_unknown"
        if first_line.startswith("~V") or first_line.startswith("~v"):
            return "las"
        if first_line.startswith("WeCo"):
            return "weco"
    except (OSError, UnicodeDecodeError):
        pass

    # Check for RESQML (zip magic)
    try:
        with open(path, "rb") as f:
            magic = f.read(4)
        if magic == b"PK\x03\x04":  # ZIP
            return "resqml"
    except OSError:
        pass

    return None


# ─── Reader registry ───────────────────────────────────────────────────

_READERS: Dict[str, Any] = {}


def register_reader(fmt: str, func):
    """Register a reader function for a format key."""
    _READERS[fmt] = func


def _read_weco(path, **kw):
    from weco.data import WellList as WL
    return WL(str(path))


def _read_las(path, *, curves=None, filter_expr=None, **kw):
    from weco.las2welllist import las2well
    from weco.lasfile import LASFile
    from weco.data import WellList as WL

    las = LASFile()
    las.read(str(path))
    well = las2well(las, curves=curves, filter=filter_expr)
    if well is None:
        raise ValueError(f"Could not convert LAS file: {path}")
    wl = WL.__new__(WL)
    wl.wells = [well]
    return wl


def _read_las_multi(paths: List[str], **kw):
    """Read multiple LAS files into one WellList."""
    from weco.data import WellList as WL
    wl = WL.__new__(WL)
    wl.wells = []
    for p in paths:
        sub = _read_las(p, **kw)
        wl.wells.extend(sub.wells)
    return wl


def _read_resqml(path, **kw):
    """Read RESQML .epc+.h5 into WellList (best effort)."""
    from weco.resqml import ResqmlFile
    from weco.data import WellList as WL, Well

    rf = ResqmlFile(str(path))
    wl = WL.__new__(WL)
    wl.wells = []

    for wbf in rf.get_objects_by_type("WellboreFrameRepresentation"):
        # Get well name from interpretation chain
        name = wbf.title or f"Well_{len(wl.wells)}"
        # Get MD array
        md_data = wbf.get_md_data(rf)
        if md_data is None:
            continue
        size = len(md_data)

        w = Well()
        w.name = name
        w.size = size
        w.data["Depth"] = list(md_data)

        # Continuous properties
        for prop in rf.get_properties_on(wbf.uuid):
            pname = prop.title or "unnamed"
            try:
                values = prop.get_values(rf)
                if values is not None and len(values) >= size:
                    w.data[pname] = list(values[:size])
            except Exception:
                pass

        wl.wells.append(w)

    if not wl.wells:
        raise ValueError(f"No wellbore data found in RESQML file: {path}")
    return wl


def _read_csv(path, *, columns=None, well_column=None, depth_column=None,
              separator=None, header=True, **kw):
    """Read CSV/space-separated file into WellList using data_import."""
    from weco.data_import import DataImport
    from weco.data import WellList as WL, Well

    di = DataImport()
    if separator and separator.strip() == "":
        di.from_space_file(str(path), *(columns or []), header=header)
    else:
        di.from_csv_file(str(path), *(columns or []), header=header)

    # Group by well name if well_column given
    if well_column is not None:
        groups = {}
        for row in di.data:
            wn = row.get(well_column, "Unknown")
            groups.setdefault(wn, []).append(row)

        wl = WL.__new__(WL)
        wl.wells = []
        for wn, rows in groups.items():
            w = Well()
            w.name = str(wn)
            w.size = len(rows)
            # Build data arrays from columns
            for col in rows[0]:
                if col != well_column:
                    try:
                        w.data[col] = [float(r.get(col, 0)) for r in rows]
                    except (ValueError, TypeError):
                        pass
            wl.wells.append(w)
        return wl

    # Single well case
    wl = WL.__new__(WL)
    wl.wells = []
    w = Well()
    w.name = Path(path).stem
    w.size = len(di.data) if hasattr(di, 'data') else 0
    wl.wells.append(w)
    return wl


def _read_las_with_discrete(path, *, curves=None, discrete=None,
                             filter_expr=None, **kw):
    """Read a LAS file with proper discrete log → region conversion.

    Parameters
    ----------
    path : str
        LAS file path.
    curves : list or dict, optional
        Continuous curve mapping (as for las2well).
    discrete : dict[str, str], optional
        ``{region_name: las_curve_name}`` — curves to import and
        convert to WeCo regions automatically.
    filter_expr : str, optional
        Row filter expression.
    """
    from weco.las2welllist import las2well
    from weco.lasfile import LASFile
    from weco.data import WellList as WL

    las = LASFile()
    las.read(str(path))

    # Merge continuous + discrete into one curve list
    curve_list = None
    if curves or discrete:
        curve_list = []
        if curves:
            if isinstance(curves, dict):
                for wname, lname in curves.items():
                    curve_list.append((wname, lname))
            elif isinstance(curves, list):
                curve_list.extend(curves)
        if discrete:
            for rname, lname in discrete.items():
                curve_list.append((rname, lname))

    well = las2well(las, curves=curve_list, filter=filter_expr)
    if well is None:
        raise ValueError(f"Could not convert LAS file: {path}")

    # Convert discrete curves to regions
    if discrete:
        for rname, lname in discrete.items():
            if rname in well.data:
                well.add_region_from_data(rname)

    wl = WL.__new__(WL)
    wl.wells = [well]
    return wl


def _read_gocad_well(path, **kw):
    """Read GOCAD ASCII well format via rddms bridge."""
    from weco.rddms import gocad_import_wells
    return gocad_import_wells(str(path))


def _read_rddms(path, **kw):
    """Read from RDDMS — path is treated as config file with url/token/dataspace."""
    import json as _json
    with open(path) as f:
        cfg = _json.load(f)
    from weco.rddms import rddms_import_wells
    return rddms_import_wells(cfg["url"], cfg["token"], cfg["dataspace"])


def _read_gocad_generic(path, **kw):
    """Read GOCAD .ts/.vs/.pl/.wl via the shared resqml.gocad_io parser.

    Returns a list of ResqmlObject for non-well types, or WellList for wells.
    For .ts/.vs/.pl this returns the raw ResqmlObject list (not a WellList).
    """
    try:
        from resqml.gocad_io import read_gocad
    except ImportError:
        raise ImportError(
            "GOCAD .ts/.vs/.pl support requires the 'resqml' package "
            "(~/gocad/lib/scripts/resqml). Add it to PYTHONPATH."
        )
    return read_gocad(str(path))


def _read_gocad_tsurf(path, **kw):
    """Read GOCAD triangulated surface (.ts)."""
    return _read_gocad_generic(path, **kw)


def _read_gocad_vset(path, **kw):
    """Read GOCAD vertex set / point set (.vs)."""
    return _read_gocad_generic(path, **kw)


def _read_gocad_pline(path, **kw):
    """Read GOCAD polyline (.pl)."""
    return _read_gocad_generic(path, **kw)


# Register built-in readers
register_reader("weco", _read_weco)
register_reader("las", _read_las)
register_reader("las_discrete", _read_las_with_discrete)
register_reader("resqml", _read_resqml)
register_reader("csv", _read_csv)
register_reader("gocad_well", _read_gocad_well)
register_reader("gocad_tsurf", _read_gocad_tsurf)
register_reader("gocad_pline", _read_gocad_pline)
register_reader("gocad_vset", _read_gocad_vset)
register_reader("rddms", _read_rddms)


# LAS 3.0 reader (§4.9)
def _read_las3(path, **kw):
    """Read LAS 3.0 file into WellList."""
    from weco.formats.las3 import las3_to_wells
    return las3_to_wells(str(path))


# DLIS reader (§4.10)
def _read_dlis(path, **kw):
    """Read DLIS file into WellList."""
    from weco.formats.dlis_reader import read_dlis
    return read_dlis(str(path), **kw)


# WITSML reader (§4.11)
def _read_witsml(path, **kw):
    """Read WITSML XML file into WellList."""
    from weco.formats.witsml_reader import read_witsml_log
    return read_witsml_log(str(path))


register_reader("las3", _read_las3)
register_reader("dlis", _read_dlis)
register_reader("witsml", _read_witsml)


# ─── Universal read function ──────────────────────────────────────────

def read_wells(path: str, fmt: str = None, **kwargs):
    """
    Read well data from any supported format.

    Parameters
    ----------
    path : str
        Path to well data file.
    fmt : str, optional
        Force format key. If None, auto-detected from extension/magic.
    **kwargs
        Format-specific options (e.g. ``curves``, ``columns``, ``separator``).

    Returns
    -------
    weco.data.WellList

    Raises
    ------
    ValueError
        If format cannot be detected or no reader is registered.
    """
    if fmt is None:
        fmt = detect_format(path)
    if fmt is None:
        raise ValueError(
            f"Cannot detect format of '{path}'.\n"
            f"Known formats: {', '.join(sorted(FORMAT_EXT_MAP.values()))}\n"
            f"Use fmt='...' to override."
        )
    reader = _READERS.get(fmt)
    if reader is None:
        raise ValueError(
            f"No reader registered for format '{fmt}'.\n"
            f"Available readers: {', '.join(sorted(_READERS.keys()))}"
        )
    return reader(path, **kwargs)


# ─── Write support ─────────────────────────────────────────────────────

_WRITERS: Dict[str, Any] = {}


def register_writer(fmt: str, func):
    _WRITERS[fmt] = func


def _write_weco(well_list, path, **kw):
    well_list.write(str(path))


def _write_las(well_list, path, **kw):
    from weco.lasfile import las_write
    for i, w in enumerate(well_list.wells):
        depth = w.data.get("Depth", w.data.get("DEPTH", list(range(w.size))))
        data_keys = [k for k in w.data if k.upper() != "DEPTH"]
        # las_write expects header entries as (name, unit, value, desc)
        data_hdr = [("DEPTH", "M", "", "Depth")] + \
                   [(k, "", "", k) for k in data_keys]
        data_cols = [depth] + [w.data[k] for k in data_keys]
        # Transpose to row-major
        rows = list(zip(*data_cols))
        out = path if len(well_list.wells) == 1 else \
            str(Path(path).parent / f"{Path(path).stem}_{w.name}.las")
        las_write(str(out), w.name, data_hdr, rows)


def _write_csv(well_list, path, **kw):
    from weco.rddms import csv_export_wells
    csv_export_wells(well_list, str(path), **kw)


def _write_gocad(well_list, path, **kw):
    from weco.rddms import gocad_export_wells
    gocad_export_wells(well_list, str(path), **kw)


def _write_epc(well_list, path, **kw):
    try:
        from weco.rddms import epc_export_wells
        epc_export_wells(str(path), well_list, **kw)
    except ImportError:
        # §4.6 — fallback pure-Python EPC writer
        from weco.formats.epc_writer import write_epc_wells
        write_epc_wells(str(path), well_list, **kw)


def _write_gocad_object(obj, path, **kw):
    """Write a ResqmlObject to GOCAD ASCII format (.ts/.vs/.pl).

    Parameters
    ----------
    obj : ResqmlObject or list[ResqmlObject]
        Object(s) to write.
    path : str
        Output file path.
    """
    try:
        from resqml.gocad_io import write_object
    except ImportError:
        raise ImportError(
            "GOCAD .ts/.vs/.pl write requires the 'resqml' package "
            "(~/gocad/lib/scripts/resqml). Add it to PYTHONPATH."
        )
    objs = obj if isinstance(obj, list) else [obj]
    with open(path, "w") as f:
        for o in objs:
            crs = getattr(o, "crs", None)
            write_object(f, o, crs)


register_writer("weco", _write_weco)
register_writer("las", _write_las)
register_writer("csv", _write_csv)
register_writer("gocad_well", _write_gocad)
register_writer("resqml", _write_epc)
register_writer("gocad_tsurf", _write_gocad_object)
register_writer("gocad_pline", _write_gocad_object)
register_writer("gocad_vset", _write_gocad_object)


def write_wells(well_list, path: str, fmt: str = None, **kwargs):
    """
    Write well data to any supported format.

    Parameters
    ----------
    well_list : weco.data.WellList
    path : str
    fmt : str, optional
    """
    if fmt is None:
        fmt = detect_format(path) or "weco"
    writer = _WRITERS.get(fmt)
    if writer is None:
        raise ValueError(f"No writer for format '{fmt}'. Available: {list(_WRITERS.keys())}")
    writer(well_list, path, **kwargs)


# ─── Exported API ──────────────────────────────────────────────────────

__all__ = [
    "detect_format", "read_wells", "write_wells",
    "register_reader", "register_writer",
    "FORMAT_EXT_MAP",
]
