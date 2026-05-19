"""
weco.rms_export — RMS / Roxar geomodelling export formats
=========================================================

Export WeCo correlation results in formats directly importable by
Roxar RMS for geomodel construction:

- **Well picks** (ASCII tab-separated) for horizon modelling
- **Discrete zonation logs** (LAS 2.0 with integer ZONE curve)
- **Horizon control points** (X, Y, Z per horizon for surface building)
- **Zone-to-facies mapping table** for facies modelling constraints
- **RMS Python import script** (roxar API template)

Target workflow::

    WeCo chronostratigraphic correlation
      → well picks + zonation logs
        → RMS: zone model + constrained facies model
          → reservoir simulation grid

Reference: Equinor–AspenTech PoC Proposal (2022),
           Baville PhD thesis §6, §7 (reservoir modelling pipeline)
"""

from __future__ import annotations

import csv
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np

from .data import ResFile, Well, WellList, ResAndWL


# ---------------------------------------------------------------------------
# Well picks — RMS ASCII import format
# ---------------------------------------------------------------------------

def export_rms_well_picks(
    picks: list[dict],
    output_path: str,
    *,
    well_list: Optional[WellList] = None,
    depth_type: str = "MD",
    include_xy: bool = True,
    surface_prefix: str = "",
    surface_suffix: str = "",
) -> str:
    """Export horizon picks in RMS-compatible ASCII well picks format.

    Format: tab-separated with columns::

        Well  Surface  MD  [TVD]  [X]  [Y]

    This format is directly importable via RMS > Wells > Import Well Picks.

    Parameters
    ----------
    picks : list[dict]
        Output of :func:`weco.export.res_to_horizon_picks`.
        Each: ``{"horizon": "H001", "picks": {well_name: depth}}``.
    output_path : str
        Output file path (typically ``.txt`` or ``.dat``).
    well_list : WellList, optional
        If provided, adds X/Y coordinates to each pick row.
    depth_type : str
        ``"MD"`` (measured depth) or ``"TVD"`` (true vertical depth).
    include_xy : bool
        Whether to include X/Y coordinates (requires *well_list*).
    surface_prefix, surface_suffix : str
        Optional prefix/suffix for surface names (e.g., ``"Top_"``).

    Returns
    -------
    str
        The output file path.
    """
    well_coords = {}
    if well_list and include_xy:
        for w in well_list.wells:
            well_coords[w.name] = (w.x, w.y)

    has_xy = bool(well_coords)

    with open(output_path, "w") as f:
        # Header comment
        f.write(f"# RMS Well Picks — exported by WeCo {datetime.now():%Y-%m-%d %H:%M}\n")
        f.write(f"# Depth type: {depth_type}\n")
        f.write(f"# Number of horizons: {len(picks)}\n")
        f.write("#\n")

        # Column header (RMS expects this format)
        cols = ["Well", "Surface", depth_type]
        if has_xy:
            cols.extend(["X", "Y"])
        f.write("\t".join(cols) + "\n")

        # Data rows
        for h in picks:
            sname = f"{surface_prefix}{h['horizon']}{surface_suffix}"
            for well_name, depth in sorted(h["picks"].items()):
                row = [well_name, sname, f"{depth:.4f}"]
                if has_xy and well_name in well_coords:
                    x, y = well_coords[well_name]
                    row.extend([f"{x:.2f}", f"{y:.2f}"])
                elif has_xy:
                    row.extend(["", ""])
                f.write("\t".join(row) + "\n")

    return output_path


def export_rms_zone_picks(
    zonation: dict[str, dict],
    output_path: str,
    *,
    well_list: Optional[WellList] = None,
    zone_names: Optional[dict[int, str]] = None,
) -> str:
    """Export zone tops/bases as RMS well picks (one pick per zone boundary).

    Unlike :func:`export_rms_well_picks` which exports every correlation
    horizon, this exports only *zone boundaries* — the tops and bases that
    define the geological zonation. More useful for structural modelling.

    Parameters
    ----------
    zonation : dict
        Output of :func:`weco.export.res_to_zonation_log`.
    output_path : str
        Output file path.
    well_list : WellList, optional
        For X/Y coordinates.
    zone_names : dict[int, str], optional
        Map zone index → name.  Default: ``Zone_00``, ``Zone_01``, etc.

    Returns
    -------
    str
        The output file path.
    """
    well_coords = {}
    if well_list:
        for w in well_list.wells:
            well_coords[w.name] = (w.x, w.y)

    has_xy = bool(well_coords)
    if zone_names is None:
        zone_names = {}

    with open(output_path, "w") as f:
        f.write(f"# RMS Zone Picks — exported by WeCo {datetime.now():%Y-%m-%d %H:%M}\n")
        cols = ["Well", "Surface", "MD"]
        if has_xy:
            cols.extend(["X", "Y"])
        f.write("\t".join(cols) + "\n")

        for well_name, info in sorted(zonation.items()):
            tops = info["zone_tops"]
            bases = info["zone_bases"]
            n_zones = info["n_zones"]

            for z in range(n_zones):
                zname = zone_names.get(z, f"Zone_{z:02d}")

                # Top of zone
                if tops[z] is not None:
                    row = [well_name, f"Top_{zname}", f"{tops[z]:.4f}"]
                    if has_xy and well_name in well_coords:
                        x, y = well_coords[well_name]
                        row.extend([f"{x:.2f}", f"{y:.2f}"])
                    f.write("\t".join(row) + "\n")

                # Base of last zone
                if z == n_zones - 1 and bases[z] is not None:
                    row = [well_name, f"Base_{zname}", f"{bases[z]:.4f}"]
                    if has_xy and well_name in well_coords:
                        x, y = well_coords[well_name]
                        row.extend([f"{x:.2f}", f"{y:.2f}"])
                    f.write("\t".join(row) + "\n")

    return output_path


# ---------------------------------------------------------------------------
# Horizon control points — for surface building in RMS
# ---------------------------------------------------------------------------

def export_horizon_points(
    picks: list[dict],
    output_dir: str,
    *,
    well_list: WellList,
    file_format: str = "irap",
) -> list[str]:
    """Export horizon picks as X/Y/Z point files for surface interpolation.

    Creates one file per horizon, suitable for RMS surface import
    (IRAP Classic Points or General Points format).

    Parameters
    ----------
    picks : list[dict]
        Output of :func:`weco.export.res_to_horizon_picks`.
    output_dir : str
        Output directory (created if needed).
    well_list : WellList
        Required for X/Y coordinates.
    file_format : str
        ``"irap"`` (X Y Z) or ``"general"`` (Name X Y Z).

    Returns
    -------
    list[str]
        Paths of created point files.
    """
    os.makedirs(output_dir, exist_ok=True)

    well_coords = {w.name: (w.x, w.y) for w in well_list.wells}
    paths = []

    for h in picks:
        fname = f"{h['horizon']}.dat"
        fpath = os.path.join(output_dir, fname)

        with open(fpath, "w") as f:
            for well_name, depth in sorted(h["picks"].items()):
                if well_name in well_coords:
                    x, y = well_coords[well_name]
                    if file_format == "general":
                        f.write(f"{well_name}\t{x:.2f}\t{y:.2f}\t{depth:.4f}\n")
                    else:
                        f.write(f"{x:.2f}\t{y:.2f}\t{depth:.4f}\n")

        paths.append(fpath)

    return paths


# ---------------------------------------------------------------------------
# Discrete well log export (facies / zones)
# ---------------------------------------------------------------------------

def export_rms_discrete_log(
    well: Well,
    log_name: str,
    output_path: str,
    *,
    depth_name: str = "Depth",
    code_table: Optional[dict[int, str]] = None,
    depth_unit: str = "M",
) -> str:
    """Export a discrete region as an RMS-compatible LAS file with code table.

    Parameters
    ----------
    well : Well
        Well object containing the region.
    log_name : str
        Region name in ``well.region``.
    output_path : str
        Output LAS file path.
    depth_name : str
        Name of the depth data channel.
    code_table : dict[int, str], optional
        Mapping of integer codes to names.  Written as LAS comments.
    depth_unit : str
        Depth unit.

    Returns
    -------
    str
        The output file path.
    """
    if log_name not in well.region:
        raise KeyError(f"Region '{log_name}' not found in well '{well.name}'. "
                       f"Available: {sorted(well.region.keys())}")

    # Convert region intervals to per-sample array
    codes = np.zeros(well.size, dtype=int)
    for rid, start, length in well.region[log_name]:
        end = min(start + length, well.size)
        codes[start:end] = rid

    # Get depth
    if depth_name in well.data:
        depths = list(well.data[depth_name])
    else:
        depths = list(np.linspace(0, well.h or well.size, well.size))

    step = (depths[-1] - depths[0]) / max(len(depths) - 1, 1) if len(depths) > 1 else 1.0

    with open(output_path, "w") as f:
        f.write("~VERSION INFORMATION\n")
        f.write(" VERS.                2.0 : CWLS LOG ASCII STANDARD\n")
        f.write(" WRAP.                 NO : ONE LINE PER DEPTH STEP\n")
        f.write("~WELL INFORMATION\n")
        f.write(f" WELL.          {well.name} : WELL NAME\n")
        f.write(f" STRT.{depth_unit}    {depths[0]:.4f} : START DEPTH\n")
        f.write(f" STOP.{depth_unit}    {depths[-1]:.4f} : STOP DEPTH\n")
        f.write(f" STEP.{depth_unit}    {step:.6f} : STEP\n")
        f.write(f" NULL.         -999.2500 : NULL VALUE\n")

        # Code table as comments (RMS reads these)
        if code_table:
            f.write("~OTHER INFORMATION\n")
            f.write(f"# Code table for {log_name}:\n")
            for code, name in sorted(code_table.items()):
                f.write(f"#   {code} = {name}\n")

        f.write("~CURVE INFORMATION\n")
        f.write(f" DEPT.{depth_unit}                 : DEPTH\n")
        f.write(f" {log_name}.                       : {log_name} (discrete)\n")
        f.write(f"~A  DEPT        {log_name}\n")
        for d, c in zip(depths, codes):
            f.write(f"  {d:12.4f}  {c:6d}\n")

    return output_path


def export_rms_code_table(
    code_table: dict[int, str],
    output_path: str,
    *,
    table_name: str = "Facies",
) -> str:
    """Export a facies/zone code lookup table.

    Format: tab-separated ``Code  Name  [Color_R  Color_G  Color_B]``

    Parameters
    ----------
    code_table : dict[int, str]
        Mapping of integer codes to names.
    output_path : str
        Output file path.
    table_name : str
        Table name header.

    Returns
    -------
    str
        The output file path.
    """
    # Default colour palette (geological convention - ish)
    _PALETTE = [
        (255, 255, 0),    # sand / yellow
        (128, 128, 128),  # shale / grey
        (0, 128, 0),      # green
        (0, 0, 255),      # blue
        (255, 128, 0),    # orange
        (128, 0, 128),    # purple
        (0, 255, 255),    # cyan
        (255, 0, 0),      # red
        (200, 200, 200),  # light grey
        (139, 69, 19),    # brown
    ]

    with open(output_path, "w") as f:
        f.write(f"# {table_name} code table — WeCo export\n")
        f.write("Code\tName\tR\tG\tB\n")
        for i, (code, name) in enumerate(sorted(code_table.items())):
            r, g, b = _PALETTE[i % len(_PALETTE)]
            f.write(f"{code}\t{name}\t{r}\t{g}\t{b}\n")

    return output_path


# ---------------------------------------------------------------------------
# Composite RMS export package
# ---------------------------------------------------------------------------

def export_rms_package(
    res_file: Union[str, ResFile],
    well_list: Union[str, WellList],
    output_dir: str,
    *,
    cor_num: int = 0,
    depth_prop: Optional[str] = None,
    n_best_summary: int = 5,
    zone_names: Optional[dict[int, str]] = None,
    surface_prefix: str = "",
    include_points: bool = True,
    include_script: bool = True,
) -> dict[str, Any]:
    """One-call export of a complete RMS-ready correlation package.

    Creates a directory structure::

        output_dir/
          well_picks.txt          # All horizon picks (RMS ASCII)
          zone_picks.txt          # Zone boundary picks (RMS ASCII)
          zonation/               # Per-well zonation LAS files
            Well_A_zonation.las
            Well_B_zonation.las
          horizon_points/         # Per-horizon XYZ point files
            H001.dat
            H002.dat
          summary.json            # Correlation quality summary
          import_script.py        # RMS Python import template

    Parameters
    ----------
    res_file : str or ResFile
        WeCo result file.
    well_list : str or WellList
        WeCo well-list file.
    output_dir : str
        Root output directory.
    cor_num : int
        Which n-best path to export (0 = best).
    depth_prop : str or None
        Depth data channel name.
    n_best_summary : int
        How many n-best results to include in summary.
    zone_names : dict[int, str], optional
        Custom zone name mapping.
    surface_prefix : str
        Prefix for surface names in RMS.
    include_points : bool
        Whether to create horizon point files.
    include_script : bool
        Whether to generate RMS import Python script.

    Returns
    -------
    dict
        Summary of all exported files with paths and counts.
    """
    from .export import (
        res_to_zonation_log,
        res_to_horizon_picks,
        export_zonation_las,
        correlation_summary,
    )

    os.makedirs(output_dir, exist_ok=True)

    # Ensure we have data objects
    if isinstance(well_list, str):
        wl = WellList(well_list)
    else:
        wl = well_list

    # --- Zonation ---
    zonation = res_to_zonation_log(res_file, wl, cor_num=cor_num,
                                   depth_prop=depth_prop)
    zon_dir = os.path.join(output_dir, "zonation")
    zon_files = export_zonation_las(zonation, zon_dir)

    # --- Horizon picks ---
    picks = res_to_horizon_picks(res_file, wl, cor_num=cor_num,
                                 depth_prop=depth_prop)

    wp_path = os.path.join(output_dir, "well_picks.txt")
    export_rms_well_picks(picks, wp_path, well_list=wl,
                          surface_prefix=surface_prefix)

    # --- Zone boundary picks ---
    zp_path = os.path.join(output_dir, "zone_picks.txt")
    export_rms_zone_picks(zonation, zp_path, well_list=wl,
                          zone_names=zone_names)

    # --- Horizon points ---
    pt_files = []
    if include_points:
        pt_dir = os.path.join(output_dir, "horizon_points")
        # Subsample to max ~50 horizons for practical surface building
        sub_picks = picks
        if len(picks) > 50:
            indices = np.linspace(0, len(picks) - 1, 50, dtype=int)
            sub_picks = [picks[i] for i in indices]
        pt_files = export_horizon_points(sub_picks, pt_dir, well_list=wl)

    # --- Summary ---
    summary = correlation_summary(res_file, wl, n_best=n_best_summary,
                                  depth_prop=depth_prop)
    summary["export_info"] = {
        "correlation_rank": cor_num,
        "n_horizons": len(picks),
        "n_zones": max((z["n_zones"] for z in zonation.values()), default=0),
        "n_wells": len(zonation),
        "export_time": datetime.now().isoformat(),
    }
    sum_path = os.path.join(output_dir, "summary.json")
    with open(sum_path, "w") as f:
        json.dump(summary, f, indent=2)

    # --- RMS Import Script ---
    script_path = None
    if include_script:
        script_path = os.path.join(output_dir, "import_script.py")
        _generate_rms_import_script(
            script_path,
            well_names=[w.name for w in wl.wells],
            n_zones=summary["export_info"]["n_zones"],
            zone_names=zone_names,
            output_dir=output_dir,
        )

    manifest = {
        "output_dir": output_dir,
        "well_picks": wp_path,
        "zone_picks": zp_path,
        "zonation_las": zon_files,
        "horizon_points": pt_files,
        "summary": sum_path,
        "import_script": script_path,
        "n_horizons": len(picks),
        "n_zones": summary["export_info"]["n_zones"],
        "n_wells": len(zonation),
    }

    return manifest


# ---------------------------------------------------------------------------
# RMS import script generator
# ---------------------------------------------------------------------------

def _generate_rms_import_script(
    output_path: str,
    well_names: list[str],
    n_zones: int,
    zone_names: Optional[dict[int, str]] = None,
    output_dir: str = ".",
) -> str:
    """Generate a Python script for importing WeCo results into RMS.

    The generated script uses the ``roxar`` API available inside RMS
    Python environment and can be run from the RMS Python console or
    as a workflow job.
    """
    if zone_names is None:
        zone_names = {i: f"Zone_{i:02d}" for i in range(n_zones)}

    script = f'''#!/usr/bin/env python3
"""
RMS Import Script — WeCo Correlation Results
=============================================

Generated by WeCo on {datetime.now():%Y-%m-%d %H:%M}

Run this script inside RMS (Python console or workflow job)
to import WeCo correlation results as:
  - Well picks / markers (horizon surfaces)
  - Blocked well logs (zonation)

Prerequisites:
  - Wells must already exist in the RMS project
  - Adjust DATA_DIR to the WeCo export directory path

Usage in RMS:
  1. Open Python console (Ctrl+P)
  2. Adjust DATA_DIR below
  3. Run the script
"""

import os
import numpy as np

# ── Configuration ────────────────────────────────────────────
DATA_DIR = r"{os.path.abspath(output_dir)}"
PROJECT_NAME = "WeCo_Correlation"
WELL_NAMES = {well_names!r}
N_ZONES = {n_zones}
ZONE_NAMES = {zone_names!r}

# ── Import well picks ───────────────────────────────────────
def import_well_picks():
    """Import correlation horizons as well markers."""
    import roxar

    project = roxar.Project.current()
    picks_file = os.path.join(DATA_DIR, "well_picks.txt")

    if not os.path.exists(picks_file):
        print(f"ERROR: {{picks_file}} not found")
        return

    with open(picks_file) as f:
        lines = f.readlines()

    # Skip comment lines
    data_lines = [l for l in lines if not l.startswith("#")]
    header = data_lines[0].strip().split("\\t")
    print(f"Importing {{len(data_lines) - 1}} well picks...")

    for line in data_lines[1:]:
        parts = line.strip().split("\\t")
        if len(parts) < 3:
            continue
        well_name, surface_name, md = parts[0], parts[1], float(parts[2])

        try:
            well = project.wells[well_name]
            # Create or update well pick
            if surface_name not in well.wellpicks:
                well.wellpicks.create(surface_name)
            well.wellpicks[surface_name].set_values(md=md)
            print(f"  {{well_name}} / {{surface_name}} @ {{md:.1f}} m")
        except Exception as e:
            print(f"  WARNING: {{well_name}} / {{surface_name}}: {{e}}")

    print("Done importing well picks.")


# ── Import zonation logs ────────────────────────────────────
def import_zonation_logs():
    """Import WeCo zonation as blocked well logs."""
    import roxar

    project = roxar.Project.current()
    zon_dir = os.path.join(DATA_DIR, "zonation")

    if not os.path.isdir(zon_dir):
        print(f"ERROR: {{zon_dir}} not found")
        return

    for wname in WELL_NAMES:
        safe = wname.replace(" ", "_").replace("/", "_")
        las_file = os.path.join(zon_dir, f"{{safe}}_zonation.las")
        if not os.path.exists(las_file):
            print(f"  Skipping {{wname}} (no zonation file)")
            continue

        try:
            well = project.wells[wname]
            # Read LAS data
            depths, zones = [], []
            reading_data = False
            with open(las_file) as f:
                for line in f:
                    if line.startswith("~A"):
                        reading_data = True
                        continue
                    if reading_data and line.strip():
                        parts = line.split()
                        if len(parts) >= 2:
                            depths.append(float(parts[0]))
                            zones.append(int(float(parts[1])))

            # Create discrete log
            log_name = "WeCo_Zone"
            if log_name not in well.well_logs:
                well.well_logs.create(log_name, roxar.WellLogType.discrete)

            log = well.well_logs[log_name]
            log.set_values(
                np.array(depths),
                np.array(zones, dtype=np.int32)
            )
            print(f"  {{wname}}: {{len(zones)}} samples, "
                  f"{{len(set(zones))}} zones")
        except Exception as e:
            print(f"  WARNING: {{wname}}: {{e}}")

    print("Done importing zonation logs.")


# ── Main ────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("WeCo → RMS Import")
    print("=" * 60)
    import_well_picks()
    print()
    import_zonation_logs()
    print()
    print("Import complete. Check the wells panel for new data.")
'''

    with open(output_path, "w") as f:
        f.write(script)

    return output_path


# ---------------------------------------------------------------------------
# Convenience: direct ResFile → RMS picks
# ---------------------------------------------------------------------------

def res_to_rms_picks(
    res_file: Union[str, ResFile],
    well_list: Union[str, WellList],
    output_path: str,
    *,
    cor_num: int = 0,
    depth_prop: Optional[str] = None,
    max_horizons: int = 0,
) -> str:
    """Shortcut: correlation result → RMS well picks file in one call."""
    from .export import res_to_horizon_picks

    if isinstance(well_list, str):
        wl = WellList(well_list)
    else:
        wl = well_list

    picks = res_to_horizon_picks(res_file, wl, cor_num=cor_num,
                                 depth_prop=depth_prop,
                                 max_horizons=max_horizons)
    return export_rms_well_picks(picks, output_path, well_list=wl)


# ---------------------------------------------------------------------------
# Exported API
# ---------------------------------------------------------------------------

__all__ = [
    "export_rms_well_picks",
    "export_rms_zone_picks",
    "export_horizon_points",
    "export_rms_discrete_log",
    "export_rms_code_table",
    "export_rms_package",
    "res_to_rms_picks",
]
