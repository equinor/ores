"""
WeCo Export Module
==================

Convert WeCo correlation results into geomodelling-ready outputs:
- Zonation logs (per-well zone assignments from correlation lines)
- Horizon picks (depth of each correlation horizon in each well)
- CSV / JSON export of picks and zones

These outputs follow the standard pipeline described in the
Equinor-AspenTech PoC Proposal (2022):
    WeCo result → zonation log → horizon picks → structural model → 3D grid

Reference: Baville et al. (2022), Equinor WeCo PoC Proposal §Process Steps
"""

from __future__ import annotations

import csv
import json
from typing import Optional, Union

import numpy as np

from .data import ResFile, WellList, ResAndWL


# ---------------------------------------------------------------------------
# Zonation log
# ---------------------------------------------------------------------------

def res_to_zonation_log(
    res_file: Union[str, ResFile],
    well_list: Union[str, WellList],
    cor_num: int = 0,
    depth_prop: Optional[str] = None,
) -> dict[str, dict]:
    """Convert a correlation path into per-well zonation logs.

    A *zonation log* assigns each marker in a well to a *zone index*
    (0, 1, 2, …) where zone boundaries correspond to the correlation
    lines of the selected n-best path.  Consecutive correlation lines
    that tie the same set of markers define one zone.

    Parameters
    ----------
    res_file : str or ResFile
        Result file path or loaded ResFile instance.
    well_list : str or WellList
        Well-list file path or loaded WellList instance.
    cor_num : int
        Which n-best path to use (0 = best).
    depth_prop : str or None
        Name of the depth data channel.  If *None*, normalised [0, 1].

    Returns
    -------
    dict[str, dict]
        ``{well_name: {"zone": [...], "depth": [...], "n_zones": int,
        "zone_tops": [...], "zone_bases": [...]}}``

        - **zone**: integer zone ID per marker (length = well.size)
        - **depth**: depth value per marker
        - **n_zones**: total number of zones
        - **zone_tops**: depth of zone tops (length = n_zones)
        - **zone_bases**: depth of zone bases (length = n_zones)
    """
    data = _load(res_file, well_list)
    _check_cor(data, cor_num)

    path = data.res_file.get_result_full_path(cor_num)
    well_names = data.well_names()
    n_wells = data.res_file.nbr_well()
    depths = data.get_zdatas(depth_prop)

    result = {}
    for wi in range(n_wells):
        well_obj = data.well_list.wells[data.res_file.well_id[wi]]
        n_markers = well_obj.size
        dep = list(depths[wi])

        # Collect zone boundaries: the marker indices where the path
        # advances for this well.  Each boundary starts a new zone.
        boundaries = []  # marker index of first marker in each new zone
        prev_marker = path[0][wi]
        for step in path[1:]:
            cur_marker = step[wi]
            if cur_marker != prev_marker:
                boundaries.append(cur_marker)
                prev_marker = cur_marker

        # Assign zone IDs: zone 0 = before first boundary, zone 1 = etc.
        zone = np.zeros(n_markers, dtype=int)
        current_zone = 0
        bi = 0
        for m in range(n_markers):
            if bi < len(boundaries) and m >= boundaries[bi]:
                current_zone += 1
                bi += 1
            zone[m] = current_zone

        n_zones = current_zone + 1

        # Compute zone tops and bases
        zone_tops = []
        zone_bases = []
        for z in range(n_zones):
            markers_in_zone = np.where(zone == z)[0]
            if len(markers_in_zone) > 0:
                zone_tops.append(dep[markers_in_zone[0]])
                zone_bases.append(dep[markers_in_zone[-1]])
            else:
                zone_tops.append(None)
                zone_bases.append(None)

        result[well_names[wi]] = {
            "zone": zone.tolist(),
            "depth": dep,
            "n_zones": n_zones,
            "zone_tops": zone_tops,
            "zone_bases": zone_bases,
        }

    return result


# ---------------------------------------------------------------------------
# Horizon picks
# ---------------------------------------------------------------------------

def res_to_horizon_picks(
    res_file: Union[str, ResFile],
    well_list: Union[str, WellList],
    cor_num: int = 0,
    depth_prop: Optional[str] = None,
    max_horizons: int = 0,
) -> list[dict]:
    """Extract horizon picks from a correlation path.

    Each step in the correlation path defines a potential *horizon*
    linking markers across wells.  Consecutive steps where a well's
    marker does **not** change are merged (only transitions = new
    horizons).

    Parameters
    ----------
    res_file, well_list, cor_num, depth_prop
        As for :func:`res_to_zonation_log`.
    max_horizons : int
        Maximum number of horizons to extract.  0 = all.

    Returns
    -------
    list[dict]
        Each element: ``{"horizon": "H001", "picks": {well_name: depth, ...}}``
    """
    data = _load(res_file, well_list)
    _check_cor(data, cor_num)

    path = data.res_file.get_result_full_path(cor_num)
    well_names = data.well_names()
    n_wells = data.res_file.nbr_well()
    depths = data.get_zdatas(depth_prop)

    # Identify *transitions* — steps where at least one well advances.
    # We skip the first node (all-zero start) and deduplicate static lines.
    horizons = []
    prev = path[0]
    for step in path[1:]:
        if step != prev:
            picks = {}
            for wi in range(n_wells):
                marker = step[wi]
                picks[well_names[wi]] = depths[wi][marker]
            horizons.append(picks)
        prev = step

    if max_horizons > 0 and len(horizons) > max_horizons:
        # Subsample evenly
        indices = np.linspace(0, len(horizons) - 1, max_horizons, dtype=int)
        horizons = [horizons[i] for i in indices]

    return [
        {"horizon": f"H{i + 1:03d}", "picks": h}
        for i, h in enumerate(horizons)
    ]


# ---------------------------------------------------------------------------
# File exports
# ---------------------------------------------------------------------------

def export_zonation_csv(
    zonation: dict[str, dict],
    output_path: str,
) -> str:
    """Write zonation logs to CSV.

    Columns: ``Well, Marker, Depth, Zone``

    Parameters
    ----------
    zonation : dict
        Output of :func:`res_to_zonation_log`.
    output_path : str
        Output CSV file path.

    Returns
    -------
    str
        The output file path.
    """
    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Well", "Marker", "Depth", "Zone"])
        for well_name, info in zonation.items():
            for i, (d, z) in enumerate(zip(info["depth"], info["zone"])):
                writer.writerow([well_name, i, f"{d:.4f}", z])
    return output_path


def export_horizon_picks_csv(
    picks: list[dict],
    output_path: str,
) -> str:
    """Write horizon picks to CSV.

    Columns: ``Horizon, Well, Depth``

    Parameters
    ----------
    picks : list[dict]
        Output of :func:`res_to_horizon_picks`.
    output_path : str
        Output CSV file path.

    Returns
    -------
    str
        The output file path.
    """
    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Horizon", "Well", "Depth"])
        for h in picks:
            for well_name, depth in h["picks"].items():
                writer.writerow([h["horizon"], well_name, f"{depth:.4f}"])
    return output_path


def export_horizon_picks_json(
    picks: list[dict],
    output_path: str,
) -> str:
    """Write horizon picks to JSON.

    Parameters
    ----------
    picks : list[dict]
        Output of :func:`res_to_horizon_picks`.
    output_path : str
        Output JSON file path.

    Returns
    -------
    str
        The output file path.
    """
    with open(output_path, "w") as f:
        json.dump(picks, f, indent=2)
    return output_path


def export_zonation_las(
    zonation: dict[str, dict],
    output_dir: str,
    depth_unit: str = "M",
) -> list[str]:
    """Write per-well zonation logs as LAS 2.0 files.

    Each well gets one LAS file with a ZONE curve.

    Parameters
    ----------
    zonation : dict
        Output of :func:`res_to_zonation_log`.
    output_dir : str
        Output directory.
    depth_unit : str
        Depth unit label (default: "M").

    Returns
    -------
    list[str]
        Paths of created LAS files.
    """
    import os
    os.makedirs(output_dir, exist_ok=True)

    paths = []
    for well_name, info in zonation.items():
        safe_name = well_name.replace(" ", "_").replace("/", "_")
        las_path = os.path.join(output_dir, f"{safe_name}_zonation.las")

        dep = info["depth"]
        zones = info["zone"]

        # Compute step
        if len(dep) > 1:
            step = (dep[-1] - dep[0]) / (len(dep) - 1)
        else:
            step = 1.0

        with open(las_path, "w") as f:
            f.write("~VERSION INFORMATION\n")
            f.write(" VERS.                2.0 : CWLS LOG ASCII STANDARD\n")
            f.write(" WRAP.                 NO : ONE LINE PER DEPTH STEP\n")
            f.write("~WELL INFORMATION\n")
            f.write(f" WELL.          {well_name} : WELL NAME\n")
            f.write(f" STRT.{depth_unit}    {dep[0]:.4f} : START DEPTH\n")
            f.write(f" STOP.{depth_unit}    {dep[-1]:.4f} : STOP DEPTH\n")
            f.write(f" STEP.{depth_unit}    {step:.6f} : STEP\n")
            f.write(f" NULL.         -999.2500 : NULL VALUE\n")
            f.write("~CURVE INFORMATION\n")
            f.write(f" DEPT.{depth_unit}                 : DEPTH\n")
            f.write(f" ZONE.                       : ZONATION LOG\n")
            f.write("~A  DEPT        ZONE\n")
            for d, z in zip(dep, zones):
                f.write(f"  {d:12.4f}  {z:6d}\n")

        paths.append(las_path)

    return paths


# ---------------------------------------------------------------------------
# Summary helpers
# ---------------------------------------------------------------------------

def correlation_summary(
    res_file: Union[str, ResFile],
    well_list: Union[str, WellList],
    n_best: int = 5,
    depth_prop: Optional[str] = None,
) -> dict:
    """Generate a summary of the n-best correlation results.

    Returns
    -------
    dict
        ``{"n_results": int, "well_names": [...],
           "results": [{"rank": int, "cost": float,
                        "n_horizons": int, "n_gaps": int}, ...]}``
    """
    data = _load(res_file, well_list)
    n = min(n_best, data.res_file.get_nbr_results())
    well_names = data.well_names()
    n_wells = data.res_file.nbr_well()

    results = []
    for i in range(n):
        cost = data.res_file.get_result_cost(i)
        path = data.res_file.get_result_full_path(i)

        # Count horizons (transitions) and gaps
        n_horizons = 0
        n_gaps = 0
        prev = path[0]
        for step in path[1:]:
            if step != prev:
                n_horizons += 1
                # A gap = a step where only one well's marker advances
                advancing = sum(1 for w in range(n_wells)
                                if step[w] != prev[w])
                if advancing < n_wells:
                    n_gaps += 1
            prev = step

        results.append({
            "rank": i + 1,
            "cost": float(cost),
            "n_horizons": n_horizons,
            "n_gaps": n_gaps,
        })

    return {
        "n_results": data.res_file.get_nbr_results(),
        "well_names": well_names,
        "results": results,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load(
    res_file: Union[str, ResFile],
    well_list: Union[str, WellList],
) -> ResAndWL:
    """Load and validate ResAndWL."""
    data = ResAndWL(res_file, well_list)
    if not data.check():
        raise ValueError("Invalid ResFile / WellList combination")
    return data


def _check_cor(data: ResAndWL, cor_num: int) -> None:
    """Validate correlation number."""
    n = data.res_file.get_nbr_results()
    if cor_num < 0 or cor_num >= n:
        raise IndexError(
            f"Correlation {cor_num} out of range (0..{n - 1})"
        )


# ---------------------------------------------------------------------------
# Unified marker set export (§15.1)
# ---------------------------------------------------------------------------

def export_marker_set(
    res_file: Union[str, ResFile],
    well_list: Union[str, WellList],
    output_path: str,
    *,
    fmt: str = "csv",
    cor_num: int = 0,
    depth_prop: Optional[str] = None,
    max_horizons: int = 0,
    horizon_prefix: str = "H",
    include_xy: bool = True,
) -> str:
    """Export correlation horizon picks as a marker set in multiple formats.

    Supported formats:
        - ``"csv"``    → CSV table (horizon, well, depth, [x, y])
        - ``"json"``   → JSON array of pick objects
        - ``"gocad"``  → GOCAD ``.wl`` file with MRKR records
        - ``"rms"``    → RMS ASCII well_picks.txt

    Parameters
    ----------
    res_file, well_list : str or loaded objects
    output_path : str
        Output file path.
    fmt : str
        Output format key.
    cor_num : int
        Which n-best path to use (0 = best).
    depth_prop : str or None
        Depth channel name.
    max_horizons : int
        Limit number of horizons (0 = all).
    horizon_prefix : str
        Prefix for auto-generated horizon names.
    include_xy : bool
        Include well XY coordinates in output (where format supports it).

    Returns
    -------
    str
        Path to written file.
    """
    picks = res_to_horizon_picks(
        res_file, well_list, cor_num=cor_num,
        depth_prop=depth_prop, max_horizons=max_horizons,
    )

    # Rename horizons with prefix if default H001 naming
    for i, p in enumerate(picks):
        if p.get("horizon", "").startswith("H") and p["horizon"][1:].isdigit():
            p["horizon"] = f"{horizon_prefix}{i + 1:03d}"

    if fmt == "csv":
        export_horizon_picks_csv(picks, output_path)
    elif fmt == "json":
        export_horizon_picks_json(picks, output_path)
    elif fmt == "gocad":
        data = _load(res_file, well_list)
        from .rddms import gocad_export_wells
        gocad_export_wells(data.well_list, output_path)
    elif fmt == "rms":
        data = _load(res_file, well_list)
        from .rms_export import export_rms_well_picks
        export_rms_well_picks(picks, output_path,
                              well_list=data.well_list,
                              include_xy=include_xy)
    else:
        raise ValueError(
            f"Unknown marker set format '{fmt}'. "
            f"Supported: csv, json, gocad, rms"
        )
    return output_path


# ---------------------------------------------------------------------------
# Zone thickness table export (§15.2)
# ---------------------------------------------------------------------------

def export_zone_thickness_table(
    res_file: Union[str, ResFile],
    well_list: Union[str, WellList],
    output_path: str,
    *,
    cor_num: int = 0,
    depth_prop: Optional[str] = None,
    include_xy: bool = True,
    zone_names: Optional[list[str]] = None,
    fmt: str = "csv",
) -> str:
    """Export per-well zone geometry as a thickness table.

    Each row: well, zone, top_depth, base_depth, thickness, [x, y].

    Parameters
    ----------
    fmt : str
        ``"csv"`` or ``"rms"`` (RMS zone_picks.txt format).

    Returns
    -------
    str
        Path to written file.
    """
    zonation = res_to_zonation_log(
        res_file, well_list, cor_num=cor_num, depth_prop=depth_prop,
    )
    data = _load(res_file, well_list)

    rows = []
    for wname, zdata in zonation.items():
        n_zones = zdata["n_zones"]
        # Find well object for XY
        well_obj = None
        if include_xy:
            for w in data.well_list.wells:
                if w.name == wname:
                    well_obj = w
                    break

        for zi in range(n_zones):
            top = zdata["zone_tops"][zi]
            base = zdata["zone_bases"][zi]
            thickness = (base - top) if (top is not None and base is not None) else None
            zn = zone_names[zi] if zone_names and zi < len(zone_names) else f"Zone_{zi}"

            row = {"well": wname, "zone": zn, "zone_index": zi,
                   "top_depth": top, "base_depth": base,
                   "thickness": thickness}
            if include_xy and well_obj is not None:
                row["x"] = getattr(well_obj, "x", 0.0)
                row["y"] = getattr(well_obj, "y", 0.0)
            rows.append(row)

    if fmt == "csv":
        if not rows:
            with open(output_path, "w") as f:
                f.write("well,zone,zone_index,top_depth,base_depth,thickness\n")
            return output_path

        fieldnames = list(rows[0].keys())
        with open(output_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
    elif fmt == "rms":
        from .rms_export import export_rms_zone_picks
        export_rms_zone_picks(
            zonation, output_path,
            well_list=data.well_list,
            zone_names=zone_names,
        )
    else:
        raise ValueError(f"Unknown format '{fmt}'. Supported: csv, rms")

    return output_path


# ---------------------------------------------------------------------------
# N-best ensemble export (§15.3)
# ---------------------------------------------------------------------------

def export_n_best_ensemble(
    res_file: Union[str, ResFile],
    well_list: Union[str, WellList],
    output_dir: str,
    *,
    n_best: int = 0,
    depth_prop: Optional[str] = None,
    fmt: str = "csv",
) -> list[str]:
    """Export top-N correlation results as separate realisations.

    Creates one subdirectory per realisation containing marker picks
    and zonation logs.

    Parameters
    ----------
    n_best : int
        Number of results to export (0 = all available).
    fmt : str
        Format for each realisation: ``"csv"``, ``"json"``, ``"rms"``.

    Returns
    -------
    list[str]
        Paths to created realisation directories.
    """
    import os
    data = _load(res_file, well_list)
    total = data.res_file.get_nbr_results()
    n = min(n_best, total) if n_best > 0 else total

    created = []
    for i in range(n):
        real_dir = os.path.join(output_dir, f"realisation_{i:03d}")
        os.makedirs(real_dir, exist_ok=True)

        # Picks
        picks_path = os.path.join(real_dir, f"picks.{fmt}" if fmt != "json" else "picks.json")
        export_marker_set(
            res_file, well_list, picks_path,
            fmt=fmt, cor_num=i, depth_prop=depth_prop,
        )

        # Zonation
        zon_path = os.path.join(real_dir, "zonation.csv")
        export_zone_thickness_table(
            res_file, well_list, zon_path,
            cor_num=i, depth_prop=depth_prop, fmt="csv",
        )

        # Summary
        cost = data.res_file.get_result_cost(i)
        summary = {"rank": i, "cost": float(cost)}
        with open(os.path.join(real_dir, "summary.json"), "w") as f:
            json.dump(summary, f, indent=2)

        created.append(real_dir)

    return created


# ---------------------------------------------------------------------------
# Correlation polylines — GOCAD .pl export (§15.4)
# ---------------------------------------------------------------------------

def export_correlation_polylines(
    res_file: Union[str, ResFile],
    well_list: Union[str, WellList],
    output_path: str,
    *,
    cor_num: int = 0,
    depth_prop: Optional[str] = None,
    max_horizons: int = 0,
) -> str:
    """Export correlation horizons as GOCAD polylines (.pl).

    Each horizon becomes a polyline connecting the wells at the
    picked depth, using the well XY coordinates for 3D geometry.

    Parameters
    ----------
    output_path : str
        Output .pl file path.

    Returns
    -------
    str
        Path to written file.
    """
    picks = res_to_horizon_picks(
        res_file, well_list, cor_num=cor_num,
        depth_prop=depth_prop, max_horizons=max_horizons,
    )
    data = _load(res_file, well_list)

    # Build well XY lookup
    well_xy = {}
    for w in data.well_list.wells:
        well_xy[w.name] = (getattr(w, "x", 0.0), getattr(w, "y", 0.0))

    lines = []
    for p in picks:
        horizon = p["horizon"]
        lines.append(f"GOCAD PLine 1")
        lines.append(f"HEADER {{")
        lines.append(f"name:{horizon}")
        lines.append(f"*painted:on")
        lines.append(f"}}")
        lines.append(f"GEOLOGICAL_FEATURE {horizon}")
        lines.append(f"GEOLOGICAL_TYPE boundary")
        lines.append(f"ILINE")

        idx = 0
        for wname, depth in p["picks"].items():
            if depth is not None:
                x, y = well_xy.get(wname, (0.0, 0.0))
                lines.append(f"VRTX {idx} {x:.2f} {y:.2f} {depth:.4f}")
                idx += 1

        for s in range(idx - 1):
            lines.append(f"SEG {s} {s + 1}")

        lines.append("END")
        lines.append("")

    with open(output_path, "w") as f:
        f.write("\n".join(lines))

    return output_path


# ---------------------------------------------------------------------------
# Correlation surfaces — GOCAD .ts export (§15.5)
# ---------------------------------------------------------------------------

def export_correlation_surfaces(
    res_file: Union[str, ResFile],
    well_list: Union[str, WellList],
    output_dir: str,
    *,
    cor_num: int = 0,
    depth_prop: Optional[str] = None,
    max_horizons: int = 0,
) -> list[str]:
    """Export correlation horizons as GOCAD triangulated surfaces (.ts).

    Each horizon becomes a Delaunay-triangulated surface connecting
    the well control points at the picked depth.

    Parameters
    ----------
    output_dir : str
        Output directory (one .ts file per horizon).

    Returns
    -------
    list[str]
        Paths to created .ts files.
    """
    import os
    os.makedirs(output_dir, exist_ok=True)

    picks = res_to_horizon_picks(
        res_file, well_list, cor_num=cor_num,
        depth_prop=depth_prop, max_horizons=max_horizons,
    )
    data = _load(res_file, well_list)

    well_xy = {}
    for w in data.well_list.wells:
        well_xy[w.name] = (getattr(w, "x", 0.0), getattr(w, "y", 0.0))

    created = []
    for p in picks:
        horizon = p["horizon"]
        points = []
        for wname, depth in p["picks"].items():
            if depth is not None:
                x, y = well_xy.get(wname, (0.0, 0.0))
                points.append((x, y, depth))

        if len(points) < 3:
            continue  # Need at least 3 points for triangulation

        ts_path = os.path.join(output_dir, f"{horizon}.ts")
        lines = [
            "GOCAD TSurf 1",
            "HEADER {",
            f"name:{horizon}",
            "*painted:on",
            "}",
            f"GEOLOGICAL_FEATURE {horizon}",
            "GEOLOGICAL_TYPE boundary",
            "TFACE",
        ]

        for i, (x, y, z) in enumerate(points):
            lines.append(f"VRTX {i} {x:.2f} {y:.2f} {z:.4f}")

        # Simple triangulation: fan from first point if ≤5 points,
        # otherwise use Delaunay if scipy available
        triangles = []
        if len(points) <= 5:
            for i in range(1, len(points) - 1):
                triangles.append((0, i, i + 1))
        else:
            try:
                from scipy.spatial import Delaunay as DelaunayTri
                pts_2d = np.array([(p[0], p[1]) for p in points])
                tri = DelaunayTri(pts_2d)
                triangles = tri.simplices.tolist()
            except ImportError:
                for i in range(1, len(points) - 1):
                    triangles.append((0, i, i + 1))

        for t in triangles:
            lines.append(f"TRGL {t[0]} {t[1]} {t[2]}")

        lines.append("END")

        with open(ts_path, "w") as f:
            f.write("\n".join(lines))
        created.append(ts_path)

    return created


# ---------------------------------------------------------------------------
# Seam table export — coal-specific (§15.13)
# ---------------------------------------------------------------------------

def export_seam_table(
    res_file: Union[str, ResFile],
    well_list: Union[str, WellList],
    output_path: str,
    *,
    cor_num: int = 0,
    depth_prop: Optional[str] = None,
    seam_region: str = "seam",
    seam_names: Optional[list[str]] = None,
) -> str:
    """Export coal-specific seam correlation table.

    Produces a table: seam_name × well × depth × thickness, with
    handling for split seams (multiple intervals per seam per well).

    Parameters
    ----------
    seam_region : str
        Name of the region identifying seam intervals.
    seam_names : list[str], optional
        Names for seams. If None, auto-generated from region IDs.

    Returns
    -------
    str
        Path to written CSV file.
    """
    zonation = res_to_zonation_log(
        res_file, well_list, cor_num=cor_num, depth_prop=depth_prop,
    )
    data = _load(res_file, well_list)

    rows = []
    for well_obj in data.well_list.wells:
        wname = well_obj.name
        if wname not in zonation:
            continue

        zdata = zonation[wname]
        depths = zdata["depth"]

        # Check for seam region
        if seam_region in getattr(well_obj, "region", {}):
            seam_intervals = well_obj.region[seam_region]
            for rid, rstart, rlen in seam_intervals:
                sname = seam_names[rid] if seam_names and rid < len(seam_names) else f"Seam_{rid}"
                top_depth = depths[rstart] if rstart < len(depths) else None
                base_idx = min(rstart + rlen - 1, len(depths) - 1)
                base_depth = depths[base_idx] if base_idx < len(depths) else None
                thickness = (base_depth - top_depth) if (top_depth is not None and base_depth is not None) else None

                rows.append({
                    "well": wname,
                    "seam": sname,
                    "seam_id": rid,
                    "top_depth": top_depth,
                    "base_depth": base_depth,
                    "thickness": thickness,
                    "n_intervals": 1,
                    "x": getattr(well_obj, "x", 0.0),
                    "y": getattr(well_obj, "y", 0.0),
                })
        else:
            # Fallback: use zonation zones as seams
            for zi in range(zdata["n_zones"]):
                sname = seam_names[zi] if seam_names and zi < len(seam_names) else f"Zone_{zi}"
                top = zdata["zone_tops"][zi]
                base = zdata["zone_bases"][zi]
                thickness = (base - top) if (top is not None and base is not None) else None
                rows.append({
                    "well": wname,
                    "seam": sname,
                    "seam_id": zi,
                    "top_depth": top,
                    "base_depth": base,
                    "thickness": thickness,
                    "n_intervals": 1,
                    "x": getattr(well_obj, "x", 0.0),
                    "y": getattr(well_obj, "y", 0.0),
                })

    if not rows:
        with open(output_path, "w") as f:
            f.write("well,seam,seam_id,top_depth,base_depth,thickness,n_intervals,x,y\n")
        return output_path

    fieldnames = list(rows[0].keys())
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    return output_path


# ---------------------------------------------------------------------------
# MODFLOW layers export — hydrogeology (§15.14)
# ---------------------------------------------------------------------------

def export_modflow_layers(
    res_file: Union[str, ResFile],
    well_list: Union[str, WellList],
    output_path: str,
    *,
    cor_num: int = 0,
    depth_prop: Optional[str] = None,
    aquifer_region: str = "aquifer",
    layer_names: Optional[list[str]] = None,
) -> str:
    """Export aquifer zone geometry for FloPy / MODFLOW.

    Produces a CSV with columns: well, layer, top_elevation, bot_elevation,
    thickness, x, y — suitable for FloPy's ``flopy.modflow.ModflowDis``.

    Parameters
    ----------
    aquifer_region : str
        Region name identifying aquifer zones (if available).
    layer_names : list[str], optional
        Names for layers.

    Returns
    -------
    str
        Path to written CSV file.
    """
    zonation = res_to_zonation_log(
        res_file, well_list, cor_num=cor_num, depth_prop=depth_prop,
    )
    data = _load(res_file, well_list)

    rows = []
    for well_obj in data.well_list.wells:
        wname = well_obj.name
        if wname not in zonation:
            continue

        zdata = zonation[wname]
        x = getattr(well_obj, "x", 0.0)
        y = getattr(well_obj, "y", 0.0)
        z_surf = getattr(well_obj, "z", 0.0)

        for zi in range(zdata["n_zones"]):
            lname = layer_names[zi] if layer_names and zi < len(layer_names) else f"Layer_{zi}"
            top = zdata["zone_tops"][zi]
            base = zdata["zone_bases"][zi]
            thickness = (base - top) if (top is not None and base is not None) else None

            # Convert depth to elevation (surface_elevation - depth)
            top_elev = (z_surf - top) if top is not None else None
            bot_elev = (z_surf - base) if base is not None else None

            rows.append({
                "well": wname,
                "layer": lname,
                "layer_index": zi,
                "top_elevation": top_elev,
                "bot_elevation": bot_elev,
                "thickness": thickness,
                "x": x,
                "y": y,
            })

    if not rows:
        with open(output_path, "w") as f:
            f.write("well,layer,layer_index,top_elevation,bot_elevation,thickness,x,y\n")
        return output_path

    fieldnames = list(rows[0].keys())
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    return output_path


# ---------------------------------------------------------------------------
# Continuous logs export (§15.15)
# ---------------------------------------------------------------------------

def export_continuous_logs(
    well_list: Union[str, WellList],
    output_dir: str,
    *,
    log_names: Optional[list[str]] = None,
    fmt: str = "las",
    depth_name: str = "depth",
    depth_unit: str = "M",
) -> list[str]:
    """Export raw + derived continuous curves per well.

    Supported formats:
        - ``"las"``   → LAS 2.0 files (one per well)
        - ``"csv"``   → CSV files (one per well)
        - ``"gocad"`` → GOCAD .wl with LOG sections

    Parameters
    ----------
    well_list : WellList or str
        Well data.
    output_dir : str
        Output directory.
    log_names : list[str], optional
        Log names to export (None = all).
    fmt : str
        Output format.
    depth_name : str
        Depth channel name.
    depth_unit : str
        Depth unit.

    Returns
    -------
    list[str]
        Paths to created files.
    """
    import os
    os.makedirs(output_dir, exist_ok=True)

    if isinstance(well_list, str):
        well_list = WellList(well_list)

    created = []
    for well in well_list.wells:
        safe_name = well.name.replace(" ", "_").replace("/", "_")

        # Determine which logs to export
        names = log_names if log_names else list(well.data.keys())
        if not names:
            continue

        if fmt == "las":
            path = os.path.join(output_dir, f"{safe_name}.las")
            _write_las_logs(well, names, path, depth_name, depth_unit)
        elif fmt == "csv":
            path = os.path.join(output_dir, f"{safe_name}.csv")
            _write_csv_logs(well, names, path, depth_name)
        elif fmt == "gocad":
            path = os.path.join(output_dir, f"{safe_name}.wl")
            _write_gocad_logs(well, names, path)
        else:
            raise ValueError(f"Unknown format '{fmt}'. Supported: las, csv, gocad")

        created.append(path)

    return created


def _write_las_logs(well, names, path, depth_name, depth_unit):
    """Write continuous logs as LAS 2.0."""
    depth = list(well.data.get(depth_name, range(well.size)))
    step = (depth[-1] - depth[0]) / max(len(depth) - 1, 1) if len(depth) > 1 else 1.0

    curve_names = [n for n in names if n != depth_name]

    with open(path, "w") as f:
        f.write("~VERSION INFORMATION\n")
        f.write(" VERS.                2.0 : CWLS LOG ASCII STANDARD\n")
        f.write(" WRAP.                 NO : ONE LINE PER DEPTH STEP\n")
        f.write("~WELL INFORMATION\n")
        f.write(f" WELL.          {well.name} : WELL NAME\n")
        f.write(f" STRT.{depth_unit}    {depth[0]:.4f} : START DEPTH\n")
        f.write(f" STOP.{depth_unit}    {depth[-1]:.4f} : STOP DEPTH\n")
        f.write(f" STEP.{depth_unit}    {step:.6f} : STEP\n")
        f.write(f" NULL.         -999.2500 : NULL VALUE\n")
        f.write("~CURVE INFORMATION\n")
        f.write(f" DEPT.{depth_unit}                 : DEPTH\n")
        for cn in curve_names:
            f.write(f" {cn}.                       : {cn}\n")
        f.write("~A  DEPT  " + "  ".join(curve_names) + "\n")
        for i, d in enumerate(depth):
            vals = [f"{d:12.4f}"]
            for cn in curve_names:
                if cn in well.data and i < len(well.data[cn]):
                    vals.append(f"{well.data[cn][i]:12.4f}")
                else:
                    vals.append(f"{'  -999.2500':>12}")
            f.write("  ".join(vals) + "\n")


def _write_csv_logs(well, names, path, depth_name):
    """Write continuous logs as CSV."""
    depth = list(well.data.get(depth_name, range(well.size)))
    curve_names = [n for n in names if n != depth_name]

    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Depth"] + curve_names)
        for i, d in enumerate(depth):
            row = [f"{d:.4f}"]
            for cn in curve_names:
                if cn in well.data and i < len(well.data[cn]):
                    row.append(f"{well.data[cn][i]:.4f}")
                else:
                    row.append("")
            writer.writerow(row)


def _write_gocad_logs(well, names, path):
    """Write continuous logs as GOCAD .wl."""
    from .formats.gocad_well import write_gocad_well
    write_gocad_well(well, path, log_names=names)


# ═══════════════════════════════════════════════════════════════════════════
# §15.10 — export_rms_package extend: blocked well log + IRAP surfaces
# ═══════════════════════════════════════════════════════════════════════════


def export_blocked_well_log(
    res_file,
    well_list,
    out_dir: str,
    *,
    cor_num: int = 0,
    log_name: str = "ZONE",
) -> list:
    """
    Export blocked (zonation) well logs as RMS-compatible ASCII files.

    Each file has columns: WELL, MD, ZONE_ID.

    Parameters
    ----------
    res_file : str or ResFile
    well_list : str or WellList
    out_dir : str
    cor_num : int
    log_name : str

    Returns
    -------
    list of str
        Created file paths.
    """
    import os, csv
    from .resfile import ResFile
    from .data import WellList as WL

    if isinstance(res_file, str):
        rf = ResFile(res_file)
    else:
        rf = res_file
    if isinstance(well_list, str):
        wl = WL(well_list)
    else:
        wl = well_list

    os.makedirs(out_dir, exist_ok=True)
    path = rf.get_result_full_path(cor_num) if rf.get_nbr_results() > cor_num else []

    created = []
    for wi in range(min(rf.nbr_well(), len(wl.wells))):
        well = wl.wells[wi]
        depth_key = None
        for dk in ("Depth", "DEPTH", "MD"):
            if dk in well.data:
                depth_key = dk
                break
        if depth_key is None:
            continue

        # Build zone log
        depths = well.data[depth_key]
        zone_log = [0] * len(depths)
        for hi, node in enumerate(path):
            if wi < len(node) and node[wi] >= 0:
                idx = node[wi]
                if 0 <= idx < len(zone_log):
                    zone_log[idx] = hi + 1

        safe_name = well.name.replace(" ", "_").replace("/", "_")
        fpath = os.path.join(out_dir, f"{safe_name}_blocked.csv")
        with open(fpath, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["WELL", "MD", log_name])
            for i, d in enumerate(depths):
                writer.writerow([well.name, f"{d:.4f}", zone_log[i]])
        created.append(fpath)

    return created


def export_irap_surfaces(
    res_file,
    well_list,
    out_dir: str,
    *,
    cor_num: int = 0,
    grid_size: int = 100,
) -> list:
    """
    Export horizon surfaces as IRAP Classic Grid ASCII files.

    Creates a simple nearest-neighbour gridded surface from well picks.
    Suitable for import into RMS.

    Parameters
    ----------
    res_file : str or ResFile
    well_list : str or WellList
    out_dir : str
    cor_num : int
    grid_size : int
        Grid resolution (NX = NY = grid_size).

    Returns
    -------
    list of str
        Created file paths.
    """
    import os
    from .resfile import ResFile
    from .data import WellList as WL

    if isinstance(res_file, str):
        rf = ResFile(res_file)
    else:
        rf = res_file
    if isinstance(well_list, str):
        wl = WL(well_list)
    else:
        wl = well_list

    os.makedirs(out_dir, exist_ok=True)
    path = rf.get_result_full_path(cor_num) if rf.get_nbr_results() > cor_num else []

    # Gather well XY positions
    xs = [getattr(w, "x", 0.0) or 0.0 for w in wl.wells]
    ys = [getattr(w, "y", 0.0) or 0.0 for w in wl.wells]

    if not xs or max(xs) == min(xs):
        return []

    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    dx = max((xmax - xmin) / grid_size, 1.0)
    dy = max((ymax - ymin) / grid_size, 1.0)

    created = []
    for hi, node in enumerate(path):
        # Gather depth values at this horizon
        points = []
        for wi in range(min(len(node), len(wl.wells))):
            if node[wi] < 0:
                continue
            well = wl.wells[wi]
            for dk in ("Depth", "DEPTH", "MD"):
                if dk in well.data:
                    idx = node[wi]
                    if idx < len(well.data[dk]):
                        points.append((xs[wi], ys[wi], well.data[dk][idx]))
                    break

        if len(points) < 3:
            continue

        # Simple nearest-neighbour grid
        grid = np.full((grid_size, grid_size), 9999900.0)
        for px, py, pz in points:
            gi = int((px - xmin) / dx)
            gj = int((py - ymin) / dy)
            gi = max(0, min(gi, grid_size - 1))
            gj = max(0, min(gj, grid_size - 1))
            grid[gj, gi] = pz

        fpath = os.path.join(out_dir, f"horizon_{hi:03d}.irap")
        with open(fpath, "w") as f:
            # IRAP Classic Grid header
            f.write(f"-996 {grid_size} {dx:.4f} {dy:.4f}\n")
            f.write(f"{xmin:.4f} {xmax:.4f} {ymin:.4f} {ymax:.4f}\n")
            f.write(f"{grid_size} 0.0 0.0 0.0\n")
            f.write("0 0 0 0 0 0 0\n")
            # Grid values
            for row in grid:
                for val in row:
                    f.write(f" {val:.4f}")
                f.write("\n")
        created.append(fpath)

    return created
