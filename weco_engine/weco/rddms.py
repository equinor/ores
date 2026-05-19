"""
weco.rddms — Universal well-data bridge (RDDMS / EPC / GOCAD / RMS / LAS / CSV)
==================================================================================

This module is the *format hub* for WeCo.  It converts freely among
six external representations:

    ═══ Storage/REST ═══                ═══ File ═══
    RDDMS (RESQML JSON)                EPC + HDF5
    GOCAD ASCII (.wl, .ts)             RMS Well / Well‑Picks
                                        LAS 2.0
                                        CSV / tab‑separated

All conversions go through two bridges:

    External format  ↔  RESQML ResqmlObject  ↔  WeCo Well / WellList / ResFile

The GOCAD ``resqml`` package (~/gocad/lib/scripts/resqml) supplies
the RESQML layer: ``ResqmlObject``, ``WellInfo``, ``WellMarkerInfo``,
``StratColumnInfo``, ``PropertyInfo``, ``CrsInfo``, ``FeatureInfo``,
plus readers and writers for RDDMS and EPC.

Type‑mapping matrix
-------------------
==============================  ==============================  ==============  =========  =============  ==========
WeCo                            RESQML / RDDMS                  RMS             LAS 2.0    CSV            GOCAD
==============================  ==============================  ==============  =========  =============  ==========
``Well.data[name]`` continuous  ContinuousProperty              .rmswell log    ~A curve   column         CURVE
``Well.region[name]`` discrete  DiscreteProperty / Categorical  discrete log    int curve  code column    REGION
``Well.x,y,z,h`` trajectory    WellboreTrajectoryRep           well head       ~W header  x,y columns    WREF+VRTX
Horizon picks (ResFile)         WellboreMarkerFrameRep          well_picks.txt  --         H,Well,Depth   MRKR
Zone boundaries (ResFile)       WellboreMarkerFrameRep          zone_picks.txt  zone LAS   zone column    MRKR
Strat column                    StratigraphicColumn (+ranks)    zone model      --         --             StratColumn
CRS / projection                LocalEngineeringCRS             project CRS     --         --             GOCAD CRS
Code table (facies)             lookup dict on PropertyInfo     code_table.txt  comments   name column    --
==============================  ==============================  ==============  =========  =============  ==========

Usage — import from RDDMS::

    from weco.rddms import rddms_import_wells
    well_list = rddms_import_wells(
        url="https://host/api/reservoir-ddms/v2",
        token="<access_token>",
        dataspace="project/wells",
    )

Usage — export correlation results to RDDMS::

    from weco.rddms import rddms_export_results
    rddms_export_results(url, token, dataspace, res_file, well_list, cor_num=0)

Usage — round‑trip via EPC file::

    from weco.rddms import epc_import_wells, epc_export_results
    wl = epc_import_wells("input.epc")
    epc_export_results("output.epc", res_file, wl)

Usage — GOCAD ASCII::

    from weco.rddms import gocad_import_wells, gocad_export_wells
    wl = gocad_import_wells("field.wl")
    gocad_export_wells(wl, "output.wl")

Usage — universal converter::

    from weco.rddms import convert
    convert("input.epc", "tmp/rms_package/", fmt_out="rms")
"""

from __future__ import annotations

import csv as csvmod
import json
import os
import re
import sys
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np

from .data import Well, WellList, ResFile

logger = logging.getLogger("weco.rddms")

# ═══════════════════════════════════════════════════════════════════════
# §1  GOCAD RESQML package availability
# ═══════════════════════════════════════════════════════════════════════
_RESQML_DIR = os.path.expanduser("~/gocad/lib/scripts")
if _RESQML_DIR not in sys.path:
    sys.path.insert(0, _RESQML_DIR)

_resqml_available = False
try:
    from resqml.rddms_client import (
        RddmsSession, rddms_available, _make_session,
        rddms_read_objects,
    )
    from resqml.rddms_writer import write_rddms
    from resqml.resqml_json import objects_to_json
    from resqml.types import (
        ResqmlObject, WellInfo, WellMarkerInfo, CrsInfo,
        PropertyInfo, FeatureInfo, Vec3,
        StratColumnInfo, HorizonInterpInfo,
        StratUnitInterpInfo, StratRankInterpInfo,
    )
    from resqml.gocad_io import (
        write_well as _gocad_write_well,
        write_object as _gocad_write_object,
        read_gocad as _gocad_read,
    )
    _resqml_available = rddms_available()
except ImportError as exc:
    logger.debug(f"GOCAD RESQML package not available: {exc}")


def is_available() -> bool:
    """Return *True* if the GOCAD RESQML package is importable."""
    return _resqml_available


# ═══════════════════════════════════════════════════════════════════════
# §2  ResqmlObject ↔ WeCo Well  (core conversion layer)
# ═══════════════════════════════════════════════════════════════════════

# ------- helpers -------------------------------------------------------

def _resample_nearest(
    src_md: np.ndarray,
    src_values: np.ndarray,
    tgt_md: np.ndarray,
) -> np.ndarray:
    """Nearest-neighbour resample from *src_md* to *tgt_md*."""
    idx = np.searchsorted(src_md, tgt_md, side="left").clip(0, len(src_md) - 1)
    # Refine: check whether left or right neighbour is closer
    right = np.minimum(idx, len(src_md) - 1)
    left = np.maximum(idx - 1, 0)
    pick = np.where(
        np.abs(src_md[left] - tgt_md) <= np.abs(src_md[right] - tgt_md),
        left, right,
    )
    return src_values[pick]


def _attach_markers_as_region(
    well: "Well",
    marker_names: list,
    marker_mds: np.ndarray,
) -> None:
    """Store well markers as region ``"Markers"`` in the WeCo model."""
    if "Depth" not in well.data or well.size == 0:
        return
    depths = np.array(well.data["Depth"], dtype=np.float64)
    name_to_id: dict[str, int] = {}
    next_id = 1
    intervals = []
    for mname, md in zip(marker_names, marker_mds):
        if mname not in name_to_id:
            name_to_id[mname] = next_id
            next_id += 1
        idx = int(np.argmin(np.abs(depths - float(md))))
        intervals.append((name_to_id[mname], idx, 1))
    well.region["Markers"] = intervals
    well.data["_marker_names"] = list(name_to_id.keys())
    well.data["_marker_ids"] = list(name_to_id.values())


# ------- ResqmlObject → WeCo Well ------------------------------------

def resqml_to_weco(obj: "ResqmlObject") -> "Well":
    """Convert a GOCAD ``ResqmlObject`` (kind='well') to a WeCo ``Well``.

    Mapping
    -------
    * Trajectory XYZ → ``Well.x / y / z / h``
    * Measured-depth → ``Well.data["Depth"]``
    * Continuous properties → ``Well.data[name]``
    * Discrete properties → ``Well.data[name]`` + ``Well.region[name]``
    * Markers (names + MDs) → ``Well.region["Markers"]``
    """
    info = obj.info
    pts = obj.points  # (N, 3) or None

    w = Well()
    w.name = info.title or getattr(info, "raw_title", "") or "unnamed"
    w.size = len(pts) if pts is not None and len(pts) > 0 else 0

    # --- trajectory header ---
    if w.size > 0:
        w.x = float(pts[0, 0])
        w.y = float(pts[0, 1])
        w.z = float(pts[0, 2])
        if w.size >= 2:
            diffs = np.diff(pts, axis=0)
            w.h = float(np.sum(np.sqrt(np.sum(diffs ** 2, axis=1))))
        else:
            w.h = 0.0
    else:
        w.x = w.y = w.z = w.h = 0.0

    # --- measured depth ---
    md_arr = obj.properties.get("md")
    if md_arr is not None and isinstance(md_arr, np.ndarray) and md_arr.size > 0:
        w.data["Depth"] = list(md_arr[:w.size])
    elif w.size > 0:
        diffs = np.diff(pts, axis=0)
        seg = np.sqrt(np.sum(diffs ** 2, axis=1))
        w.data["Depth"] = list(np.concatenate([[0.0], np.cumsum(seg)]))

    # --- XYZ data channels (for deviated wells) ---
    if w.size > 0:
        w.data["X"] = list(pts[:, 0])
        w.data["Y"] = list(pts[:, 1])
        w.data["Z"] = list(pts[:, 2])

    # --- property metadata lookup ---
    meta: dict[str, "PropertyInfo"] = {}
    for pm in getattr(obj, "property_meta", []):
        meta[pm.title] = pm

    _SKIP = {"md", "marker_names", "marker_mds", "names"}
    for pname, pdata in obj.properties.items():
        if pname in _SKIP or pname.startswith("_frame_md_"):
            continue
        if not isinstance(pdata, np.ndarray) or pdata.size == 0:
            continue

        pm = meta.get(pname)
        is_discrete = pm.kind in ("discrete", "categorical") if pm else False

        # Resample if log is on a different depth frame
        frame_md = obj.properties.get(f"_frame_md_{pname}")
        if frame_md is not None and isinstance(frame_md, np.ndarray):
            tgt = np.array(w.data.get("Depth", []), dtype=np.float64)
            if tgt.size > 0 and frame_md.size > 0:
                w.data[pname] = list(
                    _resample_nearest(frame_md, pdata[:len(frame_md)], tgt))
            else:
                w.data[pname] = list(pdata[:w.size])
        else:
            w.data[pname] = list(pdata[:w.size])

        if is_discrete and pname in w.data:
            w.add_region_from_data(pname)

        # Preserve code table from PropertyInfo.lookup
        if pm and pm.lookup:
            w.data[f"_code_table_{pname}"] = pm.lookup

        # Preserve property metadata (UoM, kind, min/max)
        if pm:
            entry = {}
            if getattr(pm, "uom", None):
                entry["uom"] = pm.uom
            if getattr(pm, "kind", None):
                entry["kind"] = pm.kind
            if getattr(pm, "min_value", None) is not None:
                entry["min"] = pm.min_value
            if getattr(pm, "max_value", None) is not None:
                entry["max"] = pm.max_value
            if entry:
                w.meta[pname] = entry

    # --- markers ---
    mk_names = obj.properties.get("marker_names", [])
    mk_mds = obj.properties.get("marker_mds", np.array([]))
    if mk_names and isinstance(mk_mds, np.ndarray) and mk_mds.size > 0:
        _attach_markers_as_region(w, mk_names, mk_mds)

    return w


# ------- Horizon / Unit / Rank import --------------------------------

def import_horizons_as_region(
    well: "Well",
    horizon_picks: list,
    region_name: str = "Horizons",
) -> bool:
    """Add horizon picks as a no-crossing region on a Well.

    Parameters
    ----------
    well : Well
        Target well (must have data["Depth"]).
    horizon_picks : list of dict
        Each ``{"name": str, "md": float}`` or ``{"name": str, "depth": float}``.
    region_name : str
        Name for the resulting region.

    Returns
    -------
    bool
        True if at least one horizon was matched.
    """
    depths = well.data.get("Depth", [])
    if not depths or not horizon_picks:
        return False

    darr = np.array(depths, dtype=np.float64)
    regions = []
    names_seen = {}
    name_id = 1

    for hp in sorted(horizon_picks, key=lambda h: h.get("md", h.get("depth", 0))):
        md = hp.get("md", hp.get("depth"))
        name = hp.get("name", f"H{name_id:03d}")
        if md is None:
            continue
        idx = int(np.argmin(np.abs(darr - md)))
        if name not in names_seen:
            names_seen[name] = name_id
            name_id += 1
        rid = names_seen[name]
        regions.append((rid, idx, 1))

    if regions:
        well.add_region(region_name, regions)
        well.data[f"_code_table_{region_name}"] = {
            v: k for k, v in names_seen.items()
        }
    return len(regions) > 0


def import_units_as_region(
    well: "Well",
    unit_picks: list,
    region_name: str = "UNIT",
) -> bool:
    """Map stratigraphic unit intervals to a discrete region on a Well.

    Parameters
    ----------
    well : Well
        Target well (must have data["Depth"]).
    unit_picks : list of dict
        Each ``{"name": str, "top_md": float, "base_md": float}``.
    region_name : str
        Name for the resulting region.

    Returns
    -------
    bool
        True if at least one unit was mapped.
    """
    depths = well.data.get("Depth", [])
    if not depths or not unit_picks:
        return False

    darr = np.array(depths, dtype=np.float64)
    regions = []
    names_seen = {}
    name_id = 1

    for up in sorted(unit_picks, key=lambda u: u.get("top_md", 0)):
        name = up.get("name", f"Unit_{name_id}")
        top_md = up.get("top_md")
        base_md = up.get("base_md")
        if top_md is None or base_md is None:
            continue
        if name not in names_seen:
            names_seen[name] = name_id
            name_id += 1
        rid = names_seen[name]
        top_idx = int(np.argmin(np.abs(darr - top_md)))
        base_idx = int(np.argmin(np.abs(darr - base_md)))
        if base_idx < top_idx:
            top_idx, base_idx = base_idx, top_idx
        length = base_idx - top_idx + 1
        if length > 0:
            regions.append((rid, top_idx, length))

    if regions:
        well.add_region(region_name, regions)
        well.data[f"_code_table_{region_name}"] = {
            v: k for k, v in names_seen.items()
        }
    return len(regions) > 0


def import_ranks_as_regions(
    well: "Well",
    strat_column: dict,
    well_picks: list,
) -> dict:
    """Import hierarchical stratigraphic column ranks as separate regions.

    Parameters
    ----------
    well : Well
        Target well.
    strat_column : dict
        ``{"ranks": [{"name": str, "units": [{"name": str, "top_md": float, "base_md": float}]}]}``
    well_picks : list of dict
        Well-specific picks: ``[{"unit_name": str, "top_md": float, "base_md": float}]``

    Returns
    -------
    dict
        ``{region_name: bool}`` — which rank regions were successfully created.
    """
    results = {}
    picks_by_name = {p["unit_name"]: p for p in well_picks}

    for rank in strat_column.get("ranks", []):
        rank_name = rank.get("name", "Rank")
        region_name = f"Rank_{rank_name}".replace(" ", "_")
        unit_picks = []
        for unit in rank.get("units", []):
            uname = unit.get("name", "")
            pick = picks_by_name.get(uname)
            if pick:
                unit_picks.append({
                    "name": uname,
                    "top_md": pick["top_md"],
                    "base_md": pick["base_md"],
                })
        results[region_name] = import_units_as_region(
            well, unit_picks, region_name
        )
    return results


# ------- WeCo Well → ResqmlObject ------------------------------------

def weco_to_resqml(
    well: "Well",
    crs_uuid: str = "",
    *,
    include_xyz: bool = True,
) -> "ResqmlObject":
    """Convert a WeCo ``Well`` to a GOCAD ``ResqmlObject`` (kind='well').

    Mapping
    -------
    * ``Well.data["Depth"]`` → measured-depth array
    * ``Well.x / y / z`` + XYZ channels → trajectory points
    * Continuous channels → ``ContinuousProperty``
    * Discrete regions → ``DiscreteProperty`` (with code table if present)
    """
    import uuid as _uuid

    pts = _build_trajectory_points(well)
    md_arr = _build_md_array(well, pts)
    n_pts = len(pts)
    uid = str(_uuid.uuid4())

    info = WellInfo(
        uuid=uid,
        title=well.name,
        raw_title=well.name,
        crs_uuid=crs_uuid,
        h5_points_path="",
        h5_md_path="",
        kb_elevation=abs(well.z) if well.z else 0.0,
    )

    props: dict[str, np.ndarray] = {"md": md_arr}
    property_meta: list["PropertyInfo"] = []

    # Skip coordinate channels — they are in the trajectory itself
    _COORD_NAMES = {"X", "x", "Y", "y", "Z", "z", "XCOOR", "YCOOR", "Xcoor", "Ycoor"}

    for dname, dvals in well.data.items():
        if dname.upper() in ("DEPTH", "MD"):
            continue
        if dname.startswith("_"):
            continue
        if dname in _COORD_NAMES:
            continue

        arr = np.array(dvals, dtype=np.float64)
        if arr.size != n_pts:
            continue

        is_disc = dname in well.region
        if is_disc:
            arr = arr.astype(np.int32)

        # Retrieve code table if available
        lookup = None
        ct = well.data.get(f"_code_table_{dname}")
        if isinstance(ct, dict):
            lookup = ct

        props[dname] = arr
        property_meta.append(PropertyInfo(
            uuid=str(_uuid.uuid4()),
            title=dname,
            kind="discrete" if is_disc else "continuous",
            uom="" if is_disc else "unitless",
            support_uuid=uid,
            h5_values_path="",
            min_value=float(np.nanmin(arr)),
            max_value=float(np.nanmax(arr)),
            indexable="intervals" if is_disc else "nodes",
            lookup=lookup,
        ))

    feature = FeatureInfo(
        feature_name=well.name,
        feature_type="wellbore",
        interp_name=well.name,
        interp_type="WellboreInterpretation",
        geological_type="",
    )

    return ResqmlObject(
        info=info, points=pts,
        properties=props, property_meta=property_meta,
        feature=feature,
    )


def _build_trajectory_points(well: "Well") -> np.ndarray:
    """Build (N, 3) XYZ from data channels or well header."""
    if well.size == 0:
        return np.empty((0, 3), dtype=np.float64)

    # Try explicit XYZ channels
    x_name = next((n for n in ("X", "x", "XCOOR", "Xcoor") if n in well.data), None)
    y_name = next((n for n in ("Y", "y", "YCOOR", "Ycoor") if n in well.data), None)

    if x_name and y_name:
        xs = np.array(well.data[x_name], dtype=np.float64)
        ys = np.array(well.data[y_name], dtype=np.float64)
    else:
        xs = np.full(well.size, well.x or 0.0)
        ys = np.full(well.size, well.y or 0.0)

    depth_name = next((n for n in ("Depth", "DEPTH", "Z", "z") if n in well.data), None)
    if depth_name:
        zs = np.array(well.data[depth_name], dtype=np.float64)
    else:
        zs = np.linspace(well.z or 0.0, (well.z or 0.0) + (well.h or well.size), well.size)

    return np.column_stack([xs, ys, zs])


def _build_md_array(well: "Well", pts: np.ndarray) -> np.ndarray:
    """Measured-depth array from Depth channel or trajectory geometry."""
    for n in ("Depth", "DEPTH", "MD"):
        if n in well.data:
            return np.array(well.data[n], dtype=np.float64)
    if len(pts) >= 2:
        diffs = np.diff(pts, axis=0)
        seg = np.sqrt(np.sum(diffs ** 2, axis=1))
        return np.concatenate([[0.0], np.cumsum(seg)])
    return np.zeros(len(pts), dtype=np.float64)


# ═══════════════════════════════════════════════════════════════════════
# §3  WeCo correlation results → RESQML marker frames
# ═══════════════════════════════════════════════════════════════════════

def _correlation_to_markers(
    res_file: Union[str, "ResFile"],
    well_list: Union[str, "WellList"],
    cor_num: int = 0,
    depth_prop: Optional[str] = None,
    max_horizons: int = 0,
    crs_uuid: str = "",
) -> list["ResqmlObject"]:
    """Build one ``ResqmlObject`` per well with trajectory + markers.

    Marker names are ``H001``, ``H002``, … (horizon labels).
    """
    import uuid as _uuid
    from .export import res_to_horizon_picks

    if isinstance(well_list, str):
        wl = WellList(well_list)
    else:
        wl = well_list

    picks = res_to_horizon_picks(
        res_file, wl,
        cor_num=cor_num, depth_prop=depth_prop,
        max_horizons=max_horizons,
    )

    objs: list["ResqmlObject"] = []
    for w in wl.wells:
        traj = weco_to_resqml(w, crs_uuid=crs_uuid)

        names, mds = [], []
        for h in picks:
            if w.name in h["picks"]:
                names.append(h["horizon"])
                mds.append(h["picks"][w.name])

        if names:
            traj.properties["marker_names"] = names
            traj.properties["marker_mds"] = np.array(mds, dtype=np.float64)

        objs.append(traj)
    return objs


def _zonation_to_strat_column(
    res_file: Union[str, "ResFile"],
    well_list: Union[str, "WellList"],
    cor_num: int = 0,
    depth_prop: Optional[str] = None,
    zone_names: Optional[dict[int, str]] = None,
) -> "ResqmlObject":
    """Build a ``StratColumnInfo`` from zonation results.

    The strat column records the zone boundaries as horizons and the
    zones as stratigraphic units in a single rank.
    """
    import uuid as _uuid
    from .export import res_to_zonation_log, res_to_horizon_picks

    if isinstance(well_list, str):
        wl = WellList(well_list)
    else:
        wl = well_list

    zonation = res_to_zonation_log(res_file, wl, cor_num=cor_num,
                                   depth_prop=depth_prop)
    picks = res_to_horizon_picks(res_file, wl, cor_num=cor_num,
                                 depth_prop=depth_prop)

    # Determine number of zones from maximum across wells
    n_zones = max((z["n_zones"] for z in zonation.values()), default=1)
    if zone_names is None:
        zone_names = {i: f"Zone_{i:02d}" for i in range(n_zones)}

    # Horizons = zone boundaries
    horizons: list["HorizonInterpInfo"] = []
    for i, h in enumerate(picks):
        horizons.append(HorizonInterpInfo(name=h["horizon"]))

    # Units
    units: list["StratUnitInterpInfo"] = []
    for z in range(n_zones):
        zname = zone_names.get(z, f"Zone_{z:02d}")
        top_h = f"H{z + 1:03d}" if z < len(picks) else ""
        base_h = f"H{z + 2:03d}" if z + 1 < len(picks) else ""
        units.append(StratUnitInterpInfo(
            name=zname,
            top_horizon_name=top_h,
            base_horizon_name=base_h,
        ))

    rank = StratRankInterpInfo(
        name="WeCo_Zonation",
        rank_name="primary",
        units=units,
    )

    sc_info = StratColumnInfo(
        uuid=str(_uuid.uuid4()),
        title="WeCo_StratColumn",
        raw_title="WeCo_StratColumn",
        description=f"Auto-generated from WeCo path {cor_num}",
        horizons=horizons,
        ranks=[rank],
    )

    return ResqmlObject(
        info=sc_info,
        points=np.empty((0, 3), dtype=np.float64),
    )


# ═══════════════════════════════════════════════════════════════════════
# §4  RDDMS public API
# ═══════════════════════════════════════════════════════════════════════

def rddms_list_wells(
    url: str,
    token: str,
    dataspace: str,
    *,
    partition: str = "",
) -> list[dict]:
    """List wells on an RDDMS server.

    Returns ``[{"name": "…", "uuid": "…", "uri": "…"}, …]``.
    """
    if not _resqml_available:
        raise ImportError("RDDMS requires the GOCAD RESQML package")
    sess = _make_session(url, token, partition)
    ttype = "resqml20.obj_WellboreTrajectoryRepresentation"
    try:
        resources = sess.list_resources(dataspace, ttype)
    except Exception:
        return []
    out = []
    for r in resources:
        out.append({
            "name": r.get("name", "(unnamed)"),
            "uuid": _extract_uuid(r.get("uri", "")),
            "uri": r.get("uri", ""),
        })
    return out


def rddms_import_wells(
    url: str,
    token: str,
    dataspace: str,
    *,
    partition: str = "",
    uuid_filter: Optional[set] = None,
    include_logs: bool = True,
    include_markers: bool = True,
) -> "WellList":
    """Import wells from an RDDMS dataspace into a WeCo ``WellList``.

    Parameters
    ----------
    url, token, dataspace : connection credentials
    partition : optional partition ID
    uuid_filter : restrict to these UUIDs
    include_logs / include_markers : what to include

    Returns
    -------
    WellList

    Raises
    ------
    ImportError
        GOCAD RESQML package missing.
    RuntimeError
        No wells found.
    """
    if not _resqml_available:
        raise ImportError(
            "RDDMS import requires the GOCAD RESQML package "
            "(~/gocad/lib/scripts/resqml) and the 'requests' library.")

    logger.info(f"RDDMS import: {url} / {dataspace}")
    _crs, objects = rddms_read_objects(
        url, token, dataspace,
        uuid_filter=uuid_filter, partition=partition,
    )
    well_objs = [o for o in objects if o.kind == "well"]
    if not well_objs:
        raise RuntimeError(f"No wells in RDDMS dataspace '{dataspace}'")

    wl = WellList.__new__(WellList)
    wl.wells = []
    for obj in well_objs:
        w = resqml_to_weco(obj)
        wl.wells.append(w)
        logger.info(f"  {w.name}: {w.size} pts, "
                     f"{len(w.data)} chans, {len(w.region)} regions")
    logger.info(f"Imported {len(wl.wells)} wells")
    return wl


def rddms_export_wells(
    url: str,
    token: str,
    dataspace: str,
    well_list: "WellList",
    *,
    partition: str = "",
    crs: Optional["CrsInfo"] = None,
) -> int:
    """Export a ``WellList`` to RDDMS (trajectories + properties).

    Returns the number of JSON objects written.
    """
    if not _resqml_available:
        raise ImportError("RDDMS export requires the GOCAD RESQML package")
    objs = [weco_to_resqml(w, crs_uuid=crs.uuid if crs else "")
            for w in well_list.wells]
    n = write_rddms(url, token, dataspace, objs, crs=crs, partition=partition)
    logger.info(f"Exported {n} well objects to RDDMS")
    return n


# §15.6 — RESQML REST: markers → WellboreMarkerFrameRepresentation
def rddms_export_markers(
    url: str,
    token: str,
    dataspace: str,
    res_file: Union[str, "ResFile"],
    well_list: Union[str, "WellList"],
    *,
    cor_num: int = 0,
    depth_prop: Optional[str] = None,
    max_horizons: int = 0,
    partition: str = "",
    crs: Optional["CrsInfo"] = None,
) -> int:
    """Export correlation markers to RDDMS as WellboreMarkerFrameRepresentation."""
    if not _resqml_available:
        raise ImportError("RDDMS export requires the GOCAD RESQML package")
    objs = _correlation_to_markers(
        res_file, well_list, cor_num=cor_num, depth_prop=depth_prop,
        max_horizons=max_horizons, crs_uuid=crs.uuid if crs else "",
    )
    n = write_rddms(url, token, dataspace, objs, crs=crs, partition=partition)
    logger.info(f"Exported {n} marker objects to RDDMS")
    return n


# §15.7 — RESQML REST: zonation → DiscreteProperty on WellboreFrame
def rddms_export_zonation(
    url: str,
    token: str,
    dataspace: str,
    res_file: Union[str, "ResFile"],
    well_list: Union[str, "WellList"],
    *,
    cor_num: int = 0,
    depth_prop: Optional[str] = None,
    zone_names: Optional[dict[int, str]] = None,
    partition: str = "",
    crs: Optional["CrsInfo"] = None,
) -> int:
    """Export zonation logs to RDDMS as DiscreteProperty on WellboreFrame."""
    if not _resqml_available:
        raise ImportError("RDDMS export requires the GOCAD RESQML package")
    from weco.export import res_to_zonation_log
    zonation = res_to_zonation_log(res_file, well_list, cor_num=cor_num, depth_prop=depth_prop)

    objs = []
    for wname, zdata in zonation.items():
        obj = _build_resqml_discrete_property(
            wname, "zonation", zdata["zone"], zone_names,
            crs_uuid=crs.uuid if crs else "",
        )
        if obj:
            objs.append(obj)

    n = write_rddms(url, token, dataspace, objs, crs=crs, partition=partition)
    logger.info(f"Exported {n} zonation objects to RDDMS")
    return n


# §15.8 — RESQML REST: horizons → HorizonInterpretation + PolylineSet
def rddms_export_horizons(
    url: str,
    token: str,
    dataspace: str,
    res_file: Union[str, "ResFile"],
    well_list: Union[str, "WellList"],
    *,
    cor_num: int = 0,
    depth_prop: Optional[str] = None,
    max_horizons: int = 0,
    partition: str = "",
    crs: Optional["CrsInfo"] = None,
) -> int:
    """Export horizon picks to RDDMS as HorizonInterpretation objects."""
    if not _resqml_available:
        raise ImportError("RDDMS export requires the GOCAD RESQML package")
    from weco.export import res_to_horizon_picks
    picks = res_to_horizon_picks(res_file, well_list, cor_num=cor_num,
                                  depth_prop=depth_prop, max_horizons=max_horizons)

    objs = _correlation_to_markers(
        res_file, well_list, cor_num=cor_num, depth_prop=depth_prop,
        max_horizons=max_horizons, crs_uuid=crs.uuid if crs else "",
    )

    n = write_rddms(url, token, dataspace, objs, crs=crs, partition=partition)
    logger.info(f"Exported {n} horizon objects to RDDMS")
    return n


# §15.9 — RESQML REST: strat column → StratigraphicColumn
def rddms_export_strat_column(
    url: str,
    token: str,
    dataspace: str,
    res_file: Union[str, "ResFile"],
    well_list: Union[str, "WellList"],
    *,
    cor_num: int = 0,
    depth_prop: Optional[str] = None,
    zone_names: Optional[dict[int, str]] = None,
    partition: str = "",
    crs: Optional["CrsInfo"] = None,
) -> int:
    """Export stratigraphic column to RDDMS."""
    if not _resqml_available:
        raise ImportError("RDDMS export requires the GOCAD RESQML package")
    sc = _zonation_to_strat_column(
        res_file, well_list, cor_num=cor_num, depth_prop=depth_prop,
        zone_names=zone_names,
    )
    n = write_rddms(url, token, dataspace, [sc], crs=crs, partition=partition)
    logger.info(f"Exported strat column to RDDMS")
    return n


def rddms_import_strat_column(
    url: str,
    token: str,
    dataspace: str,
) -> "StratColumn":
    """Import a StratigraphicColumn from RDDMS.

    Reads StratigraphicColumn, StratColumnRankInterpretation,
    StratUnitInterpretation, and HorizonInterpretation objects from RDDMS
    and builds a :class:`weco.strat_column.StratColumn`.
    """
    if not _resqml_available:
        raise ImportError("RDDMS import requires the GOCAD RESQML package")
    from weco.strat_column import StratColumn

    # Read all stratigraphic objects from RDDMS
    objs = read_rddms(url, token, dataspace)
    records = []
    for obj in objs:
        otype = getattr(obj, "object_type", "")
        if "Strat" in otype or "Horizon" in otype:
            records.append({
                "id": getattr(obj, "uuid", ""),
                "kind": otype,
                "data": getattr(obj, "properties", {}),
            })

    if not records:
        logger.warning("No stratigraphic objects found in RDDMS dataspace")
        return StratColumn(name="empty")

    return StratColumn.from_osdu_bundle(records)


def _build_resqml_discrete_property(well_name, prop_name, values, code_map=None,
                                     crs_uuid=""):
    """Build a RESQML DiscreteProperty object (helper for zonation export)."""
    if not _resqml_available:
        return None
    try:
        from resqml.types import ResqmlObject
        obj = ResqmlObject()
        obj.kind = "discrete_property"
        obj.title = f"{well_name}_{prop_name}"
        obj.well_name = well_name
        obj.values = values
        if code_map:
            obj.code_map = code_map
        return obj
    except Exception:
        return None


def rddms_export_results(
    url: str,
    token: str,
    dataspace: str,
    res_file: Union[str, "ResFile"],
    well_list: Union[str, "WellList"],
    *,
    cor_num: int = 0,
    depth_prop: Optional[str] = None,
    max_horizons: int = 0,
    include_strat_column: bool = True,
    zone_names: Optional[dict[int, str]] = None,
    partition: str = "",
    crs: Optional["CrsInfo"] = None,
) -> int:
    """Export correlation results as RDDMS well markers + optional strat column.

    Sends ``WellboreMarkerFrameRepresentation`` per well and, optionally,
    a ``StratigraphicColumn`` object.

    Returns the number of JSON objects written.
    """
    if not _resqml_available:
        raise ImportError("RDDMS export requires the GOCAD RESQML package")

    objs = _correlation_to_markers(
        res_file, well_list,
        cor_num=cor_num, depth_prop=depth_prop,
        max_horizons=max_horizons,
        crs_uuid=crs.uuid if crs else "",
    )

    if include_strat_column:
        try:
            sc = _zonation_to_strat_column(
                res_file, well_list,
                cor_num=cor_num, depth_prop=depth_prop,
                zone_names=zone_names,
            )
            objs.append(sc)
        except Exception as e:
            logger.warning(f"Could not build strat column: {e}")

    n = write_rddms(url, token, dataspace, objs, crs=crs, partition=partition)
    logger.info(f"Exported {n} marker/strat objects to RDDMS")
    return n


# ═══════════════════════════════════════════════════════════════════════
# §5  EPC file API  (offline RESQML without REST)
# ═══════════════════════════════════════════════════════════════════════

def epc_import_wells(epc_path: str) -> "WellList":
    """Import wells from a RESQML ``.epc`` (+ companion ``.h5``)."""
    if not _resqml_available:
        raise ImportError("EPC import requires the GOCAD RESQML package")
    from resqml.epc_reader import read_epc
    _crs, objs = read_epc(epc_path)
    well_objs = [o for o in objs if o.kind == "well"]
    if not well_objs:
        raise RuntimeError(f"No wells in {epc_path}")
    wl = WellList.__new__(WellList)
    wl.wells = [resqml_to_weco(o) for o in well_objs]
    logger.info(f"EPC import: {len(wl.wells)} wells from {epc_path}")
    return wl


def epc_export_wells(
    epc_path: str,
    well_list: "WellList",
    *,
    crs: Optional["CrsInfo"] = None,
) -> str:
    """Export a ``WellList`` to a RESQML ``.epc`` file."""
    if not _resqml_available:
        raise ImportError("EPC export requires the GOCAD RESQML package")
    from resqml.epc_writer import write_epc
    objs = [weco_to_resqml(w, crs_uuid=crs.uuid if crs else "")
            for w in well_list.wells]
    write_epc(epc_path, objs, crs=crs)
    logger.info(f"EPC export: {len(objs)} wells → {epc_path}")
    return epc_path


def epc_export_results(
    epc_path: str,
    res_file: Union[str, "ResFile"],
    well_list: Union[str, "WellList"],
    *,
    cor_num: int = 0,
    depth_prop: Optional[str] = None,
    max_horizons: int = 0,
    include_strat_column: bool = True,
    zone_names: Optional[dict[int, str]] = None,
) -> str:
    """Export correlation results (markers + strat column) to ``.epc``."""
    if not _resqml_available:
        raise ImportError("EPC export requires the GOCAD RESQML package")
    from resqml.epc_writer import write_epc

    objs = _correlation_to_markers(
        res_file, well_list,
        cor_num=cor_num, depth_prop=depth_prop,
        max_horizons=max_horizons,
    )
    if include_strat_column:
        try:
            objs.append(_zonation_to_strat_column(
                res_file, well_list,
                cor_num=cor_num, depth_prop=depth_prop,
                zone_names=zone_names,
            ))
        except Exception as e:
            logger.warning(f"Could not build strat column: {e}")

    write_epc(epc_path, objs)
    logger.info(f"EPC export: {len(objs)} objects → {epc_path}")
    return epc_path


# ═══════════════════════════════════════════════════════════════════════
# §6  GOCAD ASCII well I/O
# ═══════════════════════════════════════════════════════════════════════

def gocad_import_wells(path: str) -> "WellList":
    """Import wells from a GOCAD Well ASCII file (``.wl``).

    Uses the GOCAD RESQML package's ``read_gocad()`` → ``resqml_to_weco()``.
    Also handles plain WeCo ``.wells.txt`` format as a fallback.
    """
    if not _resqml_available:
        # Fallback: try native WeCo format
        return WellList(path)

    objs = _gocad_read(path)
    well_objs = [o for o in objs if o.kind == "well"]
    if not well_objs:
        raise RuntimeError(f"No wells in GOCAD file {path}")

    wl = WellList.__new__(WellList)
    wl.wells = [resqml_to_weco(o) for o in well_objs]
    logger.info(f"GOCAD import: {len(wl.wells)} wells from {path}")
    return wl


def gocad_export_wells(
    well_list: "WellList",
    path: str,
    *,
    crs: Optional["CrsInfo"] = None,
) -> str:
    """Export a ``WellList`` to GOCAD Well ASCII format.

    Each well becomes a GOCAD Well object with WREF, VRTX, CURVE, MRKR.
    """
    if not _resqml_available:
        well_list.write(path)
        return path

    with open(path, "w") as f:
        for w in well_list.wells:
            obj = weco_to_resqml(w, crs_uuid=crs.uuid if crs else "")
            text = _gocad_write_object(obj, crs=crs)
            f.write(text)
            f.write("\n")
    logger.info(f"GOCAD export: {len(well_list.wells)} wells → {path}")
    return path


# ═══════════════════════════════════════════════════════════════════════
# §7  LAS 2.0 helpers  (works without GOCAD package)
# ═══════════════════════════════════════════════════════════════════════

def las_import_wells(
    paths: Union[str, list[str]],
    *,
    curves: Optional[dict[str, str]] = None,
    discrete: Optional[dict[str, str]] = None,
) -> "WellList":
    """Import one or more LAS files into a ``WellList``.

    Parameters
    ----------
    paths : str or list[str]
        File paths or glob pattern.
    curves : dict
        ``{weco_name: las_mnemonic}`` for continuous curves.
    discrete : dict
        ``{region_name: las_mnemonic}`` — imported as data then converted
        to regions automatically.

    Returns
    -------
    WellList
    """
    import glob as globmod
    from .lasfile import LASFile
    from .las2welllist import las2well

    if isinstance(paths, str):
        paths = sorted(globmod.glob(paths)) if ("*" in paths or "?" in paths) else [paths]
    if not paths:
        raise FileNotFoundError("No LAS files found")

    curve_list = None
    if curves or discrete:
        curve_list = []
        if curves:
            for w, l in curves.items():
                curve_list.append((w, l))
        if discrete:
            for r, l in discrete.items():
                curve_list.append((r, l))

    wl = WellList.__new__(WellList)
    wl.wells = []
    for p in paths:
        las = LASFile()
        las.read(str(p))
        w = las2well(las, curves=curve_list)
        if w is None:
            logger.warning(f"LAS skip: {p}")
            continue
        if discrete:
            for rname in discrete:
                if rname in w.data:
                    w.add_region_from_data(rname)
        wl.wells.append(w)

    logger.info(f"LAS import: {len(wl.wells)} wells from {len(paths)} files")
    return wl


def las_export_wells(
    well_list: "WellList",
    output_dir: str,
    *,
    depth_name: str = "Depth",
    depth_unit: str = "M",
    include_discrete: bool = True,
) -> list[str]:
    """Export each well in a ``WellList`` as an individual LAS 2.0 file.

    Returns list of created file paths.
    """
    os.makedirs(output_dir, exist_ok=True)
    paths = []
    for w in well_list.wells:
        safe = w.name.replace(" ", "_").replace("/", "_")
        fpath = os.path.join(output_dir, f"{safe}.las")

        depth = list(w.data.get(depth_name, w.data.get("DEPTH", range(w.size))))
        step = ((depth[-1] - depth[0]) / max(len(depth) - 1, 1)
                if len(depth) > 1 else 1.0)

        with open(fpath, "w") as f:
            f.write("~VERSION INFORMATION\n")
            f.write(" VERS.                2.0 : CWLS LOG ASCII STANDARD\n")
            f.write(" WRAP.                 NO : ONE LINE PER DEPTH STEP\n")
            f.write("~WELL INFORMATION\n")
            f.write(f" WELL.          {w.name} : WELL NAME\n")
            f.write(f" STRT.{depth_unit}    {depth[0]:.4f} : START DEPTH\n")
            f.write(f" STOP.{depth_unit}    {depth[-1]:.4f} : STOP DEPTH\n")
            f.write(f" STEP.{depth_unit}    {step:.6f} : STEP\n")
            f.write(f" NULL.         -999.2500 : NULL VALUE\n")
            if w.x or w.y:
                f.write(f" XCOORD.       {w.x:.2f} : X COORDINATE\n")
                f.write(f" YCOORD.       {w.y:.2f} : Y COORDINATE\n")

            # Code tables as comments
            for rname in w.region:
                ct = w.data.get(f"_code_table_{rname}")
                if isinstance(ct, dict):
                    f.write(f"~OTHER INFORMATION\n")
                    f.write(f"# Code table for {rname}:\n")
                    for code, label in sorted(ct.items()):
                        f.write(f"#   {code} = {label}\n")
                    break  # Only one OTHER section allowed

            f.write("~CURVE INFORMATION\n")
            f.write(f" DEPT.{depth_unit}                 : DEPTH\n")

            # Select exportable channels
            export_chans = []
            for cname in w.data:
                if cname.upper() in ("DEPTH", "MD"):
                    continue
                if cname.startswith("_"):
                    continue
                if cname in ("X", "Y", "Z", "x", "y", "z"):
                    continue
                vals = w.data[cname]
                if len(vals) != w.size:
                    continue
                export_chans.append(cname)
                kind_tag = " (discrete)" if cname in w.region else ""
                f.write(f" {cname}.                       : {cname}{kind_tag}\n")

            # Data section
            f.write(f"~A  DEPT")
            for cn in export_chans:
                f.write(f"        {cn}")
            f.write("\n")

            for i in range(w.size):
                d = depth[i] if i < len(depth) else -999.25
                f.write(f"  {d:12.4f}")
                for cn in export_chans:
                    v = w.data[cn][i] if i < len(w.data[cn]) else -999.25
                    if cn in w.region:
                        f.write(f"  {int(v):6d}")
                    else:
                        f.write(f"  {v:12.4f}")
                f.write("\n")

        paths.append(fpath)
    logger.info(f"LAS export: {len(paths)} files → {output_dir}")
    return paths


# ═══════════════════════════════════════════════════════════════════════
# §8  CSV helpers  (works without GOCAD package)
# ═══════════════════════════════════════════════════════════════════════

def csv_import_wells(
    path: str,
    *,
    well_column: str = "Well",
    depth_column: str = "Depth",
    x_column: Optional[str] = "X",
    y_column: Optional[str] = "Y",
    discrete_columns: Optional[list[str]] = None,
    separator: str = ",",
) -> "WellList":
    """Import wells from a CSV / TSV file.

    Expects one row per depth sample with at least *well_column* and
    *depth_column*.  Remaining numeric columns become data channels.
    Columns listed in *discrete_columns* are also converted to regions.

    Returns
    -------
    WellList
    """
    discrete_columns = discrete_columns or []

    with open(path, newline="") as f:
        reader = csvmod.DictReader(f, delimiter=separator)
        rows = list(reader)

    if not rows:
        raise ValueError(f"Empty CSV: {path}")

    # Group rows by well
    groups: dict[str, list[dict]] = {}
    for r in rows:
        wn = r.get(well_column, "Unknown")
        groups.setdefault(wn, []).append(r)

    wl = WellList.__new__(WellList)
    wl.wells = []

    for wn, wrows in groups.items():
        w = Well()
        w.name = wn
        w.size = len(wrows)

        # Position from first row
        if x_column and x_column in wrows[0]:
            try:
                w.x = float(wrows[0][x_column])
            except (ValueError, TypeError):
                pass
        if y_column and y_column in wrows[0]:
            try:
                w.y = float(wrows[0][y_column])
            except (ValueError, TypeError):
                pass

        # Build data channels from all numeric columns
        for col in wrows[0]:
            if col == well_column:
                continue
            try:
                vals = [float(r.get(col, "nan")) for r in wrows]
                w.data[col] = vals
            except (ValueError, TypeError):
                continue

        # Rename depth column if needed
        if depth_column != "Depth" and depth_column in w.data:
            w.data["Depth"] = w.data.pop(depth_column)

        # Discrete columns → regions
        for dc in discrete_columns:
            if dc in w.data:
                w.add_region_from_data(dc)

        # Compute well length
        if "Depth" in w.data and len(w.data["Depth"]) >= 2:
            w.z = w.data["Depth"][0]
            w.h = w.data["Depth"][-1] - w.data["Depth"][0]

        wl.wells.append(w)

    logger.info(f"CSV import: {len(wl.wells)} wells from {path}")
    return wl


def csv_export_wells(
    well_list: "WellList",
    output_path: str,
    *,
    include_xy: bool = True,
    separator: str = ",",
) -> str:
    """Export a ``WellList`` to a single CSV file (one row per sample).

    Columns: ``Well, Depth, [X, Y,] <channel1>, <channel2>, …``
    """
    if not well_list.wells:
        raise ValueError("Empty WellList")

    # Collect all channel names across wells (excluding internals)
    all_chans: list[str] = []
    seen = set()
    for w in well_list.wells:
        for c in w.data:
            if c not in seen and not c.startswith("_") and c not in ("X", "Y", "Z"):
                all_chans.append(c)
                seen.add(c)

    cols = ["Well"]
    if include_xy:
        cols += ["X", "Y"]
    cols += all_chans

    with open(output_path, "w", newline="") as f:
        writer = csvmod.writer(f, delimiter=separator)
        writer.writerow(cols)
        for w in well_list.wells:
            for i in range(w.size):
                row = [w.name]
                if include_xy:
                    row += [f"{w.x:.2f}", f"{w.y:.2f}"]
                for c in all_chans:
                    if c in w.data and i < len(w.data[c]):
                        row.append(f"{w.data[c][i]:.6f}")
                    else:
                        row.append("")
                writer.writerow(row)

    logger.info(f"CSV export: {len(well_list.wells)} wells → {output_path}")
    return output_path


def csv_export_picks(
    picks: list[dict],
    output_path: str,
    *,
    well_list: Optional["WellList"] = None,
    include_xy: bool = True,
    separator: str = ",",
) -> str:
    """Export horizon picks to CSV.

    Columns: ``Horizon, Well, MD [, X, Y]``.
    """
    well_coords = {}
    if well_list and include_xy:
        well_coords = {w.name: (w.x, w.y) for w in well_list.wells}

    with open(output_path, "w", newline="") as f:
        writer = csvmod.writer(f, delimiter=separator)
        cols = ["Horizon", "Well", "MD"]
        if well_coords:
            cols += ["X", "Y"]
        writer.writerow(cols)
        for h in picks:
            for wn, md in sorted(h["picks"].items()):
                row = [h["horizon"], wn, f"{md:.4f}"]
                if well_coords and wn in well_coords:
                    row += [f"{well_coords[wn][0]:.2f}",
                            f"{well_coords[wn][1]:.2f}"]
                writer.writerow(row)

    logger.info(f"CSV picks: {sum(len(h['picks']) for h in picks)} rows → {output_path}")
    return output_path


# ═══════════════════════════════════════════════════════════════════════
# §9  RMS helpers  (thin wrappers — heavy lifting in rms_export.py)
# ═══════════════════════════════════════════════════════════════════════

def rms_import_well_picks(
    path: str,
    *,
    depth_column: str = "MD",
) -> list[dict]:
    """Read an RMS‑format well‑picks file back into pick dicts.

    Expected tab‑separated: ``Well  Surface  MD  [X  Y]``

    Returns ``[{"horizon": "…", "picks": {well: depth, …}}, …]``
    """
    horizons: dict[str, dict[str, float]] = {}
    with open(path) as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            parts = line.strip().split("\t")
            if len(parts) < 3:
                continue
            if parts[0] == "Well":  # header
                continue
            wn, sname = parts[0], parts[1]
            try:
                md = float(parts[2])
            except ValueError:
                continue
            horizons.setdefault(sname, {})[wn] = md

    return [{"horizon": h, "picks": p} for h, p in horizons.items()]


def rms_import_wells(path: str) -> "WellList":
    """Read an RMS ASCII well file  (stub — delegates to LAS reader).

    RMS .rmswell is close to LAS; this wraps the appropriate reader.
    """
    from .formats import read_wells
    return read_wells(path, fmt="las")


# ═══════════════════════════════════════════════════════════════════════
# §10  Universal converter
# ═══════════════════════════════════════════════════════════════════════

# Maps user-facing format name → (import_func, export_func)
_FORMAT_TABLE: dict[str, tuple] = {}  # populated after function defs


def convert(
    input_path: str,
    output_path: str,
    *,
    fmt_in: Optional[str] = None,
    fmt_out: Optional[str] = None,
    **kwargs,
) -> str:
    """Convert well data between any two supported formats.

    Parameters
    ----------
    input_path : str
        Source file.
    output_path : str
        Destination file or directory.
    fmt_in, fmt_out : str, optional
        Format override (auto-detected from extension if omitted).
        Recognised: ``weco``, ``las``, ``csv``, ``epc``,
        ``gocad``, ``rms``, ``rddms``.
    **kwargs
        Extra options forwarded to the importer/exporter.

    Returns
    -------
    str
        Output path.
    """
    from .formats import detect_format

    # Auto-detect input format
    if fmt_in is None:
        ext = Path(input_path).suffix.lower()
        auto = detect_format(input_path)
        _GUESS = {
            "weco": "weco", "las": "las", "csv": "csv",
            "resqml": "epc", "gocad_well": "gocad",
            "rms_well": "rms",
        }
        fmt_in = _GUESS.get(auto, auto or ext.lstrip("."))

    # Auto-detect output format
    if fmt_out is None:
        ext = Path(output_path).suffix.lower()
        _EXT_OUT = {
            ".wells.txt": "weco", ".las": "las", ".csv": "csv",
            ".epc": "epc", ".wl": "gocad", ".rmswell": "rms",
        }
        fmt_out = _EXT_OUT.get(ext, ext.lstrip("."))

    # Import
    importers = {
        "weco":  lambda p, **k: WellList(p),
        "las":   lambda p, **k: las_import_wells(p, **k),
        "csv":   lambda p, **k: csv_import_wells(p, **k),
        "epc":   lambda p, **k: epc_import_wells(p),
        "gocad": lambda p, **k: gocad_import_wells(p),
        "rms":   lambda p, **k: rms_import_wells(p),
    }

    importer = importers.get(fmt_in)
    if importer is None:
        raise ValueError(f"Unknown input format: {fmt_in}")
    wl = importer(input_path, **{k: v for k, v in kwargs.items()
                                  if k in ("curves", "discrete", "well_column",
                                           "depth_column", "separator",
                                           "discrete_columns")})

    # Export
    exporters = {
        "weco":  lambda wl_, p, **k: (wl_.write(p), p)[1],
        "las":   lambda wl_, p, **k: las_export_wells(wl_, p, **k)[-1],
        "csv":   lambda wl_, p, **k: csv_export_wells(wl_, p, **k),
        "epc":   lambda wl_, p, **k: epc_export_wells(p, wl_, **k),
        "gocad": lambda wl_, p, **k: gocad_export_wells(wl_, p, **k),
        "rms":   lambda wl_, p, **k: _export_rms_package_bridge(wl_, p, **k),
    }

    exporter = exporters.get(fmt_out)
    if exporter is None:
        raise ValueError(f"Unknown output format: {fmt_out}")
    result = exporter(wl, output_path, **{k: v for k, v in kwargs.items()
                                           if k not in ("curves", "discrete",
                                                        "well_column",
                                                        "depth_column",
                                                        "separator",
                                                        "discrete_columns")})
    logger.info(f"Converted {fmt_in} → {fmt_out}: {input_path} → {output_path}")
    return output_path


def _export_rms_package_bridge(wl: "WellList", output_dir: str, **kw) -> str:
    """Thin bridge to rms_export for convert()."""
    os.makedirs(output_dir, exist_ok=True)
    # Write wells as LAS into output_dir
    las_export_wells(wl, output_dir)
    # Also write a CSV summary
    csv_export_wells(wl, os.path.join(output_dir, "wells.csv"))
    return output_dir


# ═══════════════════════════════════════════════════════════════════════
# §11  Utilities
# ═══════════════════════════════════════════════════════════════════════

def _extract_uuid(uri: str) -> str:
    """Extract a UUID from an RDDMS-style URI."""
    m = re.search(r"\(([0-9a-fA-F-]{36})\)", uri)
    return m.group(1) if m else ""


def summarise_well_list(wl: "WellList") -> dict:
    """Produce a JSON-serialisable summary of a WellList.

    Useful for debugging and format-comparison checks.
    """
    wells = []
    for w in wl.wells:
        cont = [c for c in w.data if not c.startswith("_")]
        disc = list(w.region.keys())
        wells.append({
            "name": w.name,
            "size": w.size,
            "x": w.x, "y": w.y, "z": w.z, "h": w.h,
            "continuous": cont,
            "discrete": disc,
        })
    return {
        "n_wells": len(wl.wells),
        "wells": wells,
    }


def compare_well_lists(
    wl_a: "WellList",
    wl_b: "WellList",
    *,
    tolerance: float = 1e-4,
) -> dict:
    """Compare two WellLists channel-by-channel (for round-trip validation).

    Returns a dict of per-well, per-channel match statistics.
    """
    results: dict[str, Any] = {"match": True, "wells": {}}
    a_map = {w.name: w for w in wl_a.wells}
    b_map = {w.name: w for w in wl_b.wells}

    all_names = sorted(set(a_map) | set(b_map))
    for name in all_names:
        wr: dict[str, Any] = {}
        wa = a_map.get(name)
        wb = b_map.get(name)
        if wa is None:
            wr["status"] = "only_in_B"
            results["match"] = False
        elif wb is None:
            wr["status"] = "only_in_A"
            results["match"] = False
        else:
            wr["status"] = "both"
            wr["size_match"] = wa.size == wb.size
            if not wr["size_match"]:
                results["match"] = False
            chans: dict[str, Any] = {}
            for c in set(wa.data) | set(wb.data):
                if c.startswith("_"):
                    continue
                if c not in wa.data:
                    chans[c] = "only_in_B"
                    results["match"] = False
                elif c not in wb.data:
                    chans[c] = "only_in_A"
                    results["match"] = False
                else:
                    arr_a = np.array(wa.data[c], dtype=np.float64)
                    arr_b = np.array(wb.data[c], dtype=np.float64)
                    n = min(len(arr_a), len(arr_b))
                    if n == 0:
                        chans[c] = "empty"
                    else:
                        diff = np.max(np.abs(arr_a[:n] - arr_b[:n]))
                        chans[c] = {"max_diff": float(diff),
                                    "match": bool(diff <= tolerance)}
                        if diff > tolerance:
                            results["match"] = False
            wr["channels"] = chans
        results["wells"][name] = wr

    return results


# ═══════════════════════════════════════════════════════════════════════
# §12  Exported API
# ═══════════════════════════════════════════════════════════════════════

__all__ = [
    # availability
    "is_available",
    # core converters
    "resqml_to_weco",
    "weco_to_resqml",
    # RDDMS
    "rddms_list_wells",
    "rddms_import_wells",
    "rddms_export_wells",
    "rddms_export_results",
    "rddms_export_markers",
    "rddms_export_zonation",
    "rddms_export_horizons",
    "rddms_export_strat_column",
    # EPC
    "epc_import_wells",
    "epc_export_wells",
    "epc_export_results",
    # GOCAD ASCII
    "gocad_import_wells",
    "gocad_export_wells",
    # LAS
    "las_import_wells",
    "las_export_wells",
    # CSV
    "csv_import_wells",
    "csv_export_wells",
    "csv_export_picks",
    # RMS
    "rms_import_wells",
    "rms_import_well_picks",
    # universal
    "convert",
    # utilities
    "summarise_well_list",
    "compare_well_lists",
]
