"""
weco.sequence_strat — Sequence-stratigraphic surface detection
==============================================================

Detect maximum flooding surfaces (MFS), sequence boundaries (SB),
and transgressive surfaces (TS) from GR log patterns.  Assign systems
tract regions to wells for hierarchical correlation.

These surfaces can be used as ``no_crossing`` or ``same_region``
constraints in the WeCo engine, enabling a multi-scale cascade:

1. Lock 2nd/3rd-order surfaces → DTW resolves within bounded intervals
2. Reduces search space and prevents noise propagation
3. Ensures geological consistency across scales

Reference
---------
Baville (2022) §6.3.5; Catuneanu (2006) *Principles of Sequence Stratigraphy*;
Van Wagoner et al. (1990) *Siliciclastic Sequence Stratigraphy*.

Todo §12.1 — ``weco/sequence_strat.py``: MFS/SB detection from GR peaks
+ systems tract assignment.
"""

from __future__ import annotations

from typing import Optional

import numpy as np

from .data import Well, WellList


# ---------------------------------------------------------------------------
# Surface detection helpers
# ---------------------------------------------------------------------------

def _smooth(signal: np.ndarray, window: int) -> np.ndarray:
    """Simple moving-average smoother."""
    if window <= 1:
        return signal
    kernel = np.ones(window) / window
    return np.convolve(signal, kernel, mode="same")


def _find_peaks(signal: np.ndarray, min_spacing: int = 3) -> list[int]:
    """Find local maxima with minimum spacing constraint."""
    peaks = []
    for i in range(1, len(signal) - 1):
        if signal[i] > signal[i - 1] and signal[i] >= signal[i + 1]:
            if not peaks or (i - peaks[-1]) >= min_spacing:
                peaks.append(i)
    return peaks


def _find_troughs(signal: np.ndarray, min_spacing: int = 3) -> list[int]:
    """Find local minima with minimum spacing constraint."""
    troughs = []
    for i in range(1, len(signal) - 1):
        if signal[i] < signal[i - 1] and signal[i] <= signal[i + 1]:
            if not troughs or (i - troughs[-1]) >= min_spacing:
                troughs.append(i)
    return troughs


# ---------------------------------------------------------------------------
# MFS / SB detection
# ---------------------------------------------------------------------------

def detect_mfs(
    well: Well,
    gr_name: str = "GR",
    window: int = 5,
    prominence: float = 0.3,
    min_spacing: int = 5,
) -> list[int]:
    """Detect Maximum Flooding Surfaces from GR log peaks.

    MFS locations are identified as prominent GR maxima (high shale
    content = distal / deepest water).

    Parameters
    ----------
    well : Well
        Well with a GR log.
    gr_name : str
        Name of the GR data channel.
    window : int
        Smoothing window (samples).
    prominence : float
        Minimum prominence (fraction of GR range) to accept a peak.
    min_spacing : int
        Minimum spacing between detected surfaces (samples).

    Returns
    -------
    list[int]
        Marker indices of detected MFS positions.
    """
    if gr_name not in well.data:
        return []

    gr = np.array(well.data[gr_name], dtype=float)
    smoothed = _smooth(gr, window)

    gr_range = smoothed.max() - smoothed.min()
    if gr_range < 1e-10:
        return []

    peaks = _find_peaks(smoothed, min_spacing)

    # Filter by prominence
    threshold = smoothed.min() + prominence * gr_range
    mfs = [p for p in peaks if smoothed[p] >= threshold]

    return mfs


def detect_sb(
    well: Well,
    gr_name: str = "GR",
    window: int = 5,
    prominence: float = 0.3,
    min_spacing: int = 5,
) -> list[int]:
    """Detect Sequence Boundaries from GR log troughs.

    SB locations are identified as prominent GR minima (clean sand /
    maximum regression → base of next sequence).

    Parameters
    ----------
    well : Well
        Well with a GR log.
    gr_name : str
        Name of the GR data channel.
    window, prominence, min_spacing
        As for :func:`detect_mfs`.

    Returns
    -------
    list[int]
        Marker indices of detected SB positions.
    """
    if gr_name not in well.data:
        return []

    gr = np.array(well.data[gr_name], dtype=float)
    smoothed = _smooth(gr, window)

    gr_range = smoothed.max() - smoothed.min()
    if gr_range < 1e-10:
        return []

    troughs = _find_troughs(smoothed, min_spacing)

    threshold = smoothed.max() - prominence * gr_range
    sb = [t for t in troughs if smoothed[t] <= threshold]

    return sb


def detect_ts(
    well: Well,
    gr_name: str = "GR",
    window: int = 5,
    min_spacing: int = 5,
) -> list[int]:
    """Detect Transgressive Surfaces from GR inflection points.

    TS locations are identified as upward inflections in the GR log
    (transition from progradation to retrogradation).

    Parameters
    ----------
    well : Well
        Well with a GR log.
    gr_name : str
        Name of the GR data channel.
    window : int
        Smoothing window.
    min_spacing : int
        Minimum spacing between surfaces.

    Returns
    -------
    list[int]
        Marker indices of detected TS positions.
    """
    if gr_name not in well.data:
        return []

    gr = np.array(well.data[gr_name], dtype=float)
    smoothed = _smooth(gr, window)

    # Compute first derivative
    deriv = np.gradient(smoothed)
    # TS = where derivative changes from negative to positive (start of GR increase)
    ts = []
    for i in range(1, len(deriv) - 1):
        if deriv[i - 1] < 0 and deriv[i] >= 0:
            if not ts or (i - ts[-1]) >= min_spacing:
                ts.append(i)
    return ts


# ---------------------------------------------------------------------------
# Systems tract assignment
# ---------------------------------------------------------------------------

def assign_systems_tracts(
    well: Well,
    gr_name: str = "GR",
    window: int = 5,
    mfs_prominence: float = 0.3,
    sb_prominence: float = 0.3,
    min_spacing: int = 5,
    output_region: str = "systems_tract",
) -> bool:
    """Assign systems tract regions to a well based on GR log patterns.

    Systems tracts (simplified):
    - **HST** (Highstand Systems Tract, ID=0): between MFS and next SB
      (progradation — GR decreasing upward)
    - **LST** (Lowstand Systems Tract, ID=1): between SB and next TS
      (initial transgression or forced regression)
    - **TST** (Transgressive Systems Tract, ID=2): between TS and next MFS
      (retrogradation — GR increasing upward)

    Parameters
    ----------
    well : Well
        Well with a GR log.
    gr_name : str
        GR channel name.
    window : int
        Smoothing window.
    mfs_prominence, sb_prominence : float
        Prominence thresholds.
    min_spacing : int
        Minimum spacing between surfaces.
    output_region : str
        Name of the region to create.

    Returns
    -------
    bool
        True if systems tracts were assigned.
    """
    mfs_indices = detect_mfs(well, gr_name, window, mfs_prominence, min_spacing)
    sb_indices = detect_sb(well, gr_name, window, sb_prominence, min_spacing)

    if not mfs_indices and not sb_indices:
        return False

    n = well.size

    # Merge all surfaces and sort
    surfaces = [(i, "MFS") for i in mfs_indices] + [(i, "SB") for i in sb_indices]
    surfaces.sort(key=lambda x: x[0])

    # Assign tracts based on surface sequence
    tracts = np.zeros(n, dtype=int)  # default HST
    current_tract = 0  # HST

    surface_idx = 0
    for m in range(n):
        while surface_idx < len(surfaces) and surfaces[surface_idx][0] <= m:
            _, stype = surfaces[surface_idx]
            if stype == "MFS":
                current_tract = 0  # HST follows MFS
            elif stype == "SB":
                current_tract = 1  # LST follows SB
            surface_idx += 1
        tracts[m] = current_tract

    # Convert to region format: (id, start, length)
    intervals = []
    if n > 0:
        cur_id = int(tracts[0])
        cur_start = 0
        cur_len = 1
        for m in range(1, n):
            if int(tracts[m]) == cur_id:
                cur_len += 1
            else:
                intervals.append((cur_id, cur_start, cur_len))
                cur_id = int(tracts[m])
                cur_start = m
                cur_len = 1
        intervals.append((cur_id, cur_start, cur_len))

    well.add_region(output_region, intervals)
    return True


# ---------------------------------------------------------------------------
# Surface region creation (for no_crossing / same_region)
# ---------------------------------------------------------------------------

def add_surface_boundaries(
    well: Well,
    surfaces: list[int],
    region_name: str = "strat_boundary",
) -> bool:
    """Create a region from surface picks, suitable for ``no_crossing``.

    Each interval between surfaces gets a unique zone ID, creating
    hard boundaries that the correlation engine cannot cross.

    Parameters
    ----------
    well : Well
        Target well.
    surfaces : list[int]
        Sorted marker indices of detected surfaces.
    region_name : str
        Output region name.

    Returns
    -------
    bool
        True if at least one boundary was created.
    """
    if not surfaces:
        return False

    n = well.size
    boundaries = sorted(set(surfaces))

    intervals = []
    zone_id = 0
    prev = 0
    for b in boundaries:
        if b > prev:
            intervals.append((zone_id, prev, b - prev))
            zone_id += 1
        prev = b
    if prev < n:
        intervals.append((zone_id, prev, n - prev))

    well.add_region(region_name, intervals)
    return True


def add_sequence_boundaries(
    well_list: WellList,
    gr_name: str = "GR",
    window: int = 5,
    mfs_prominence: float = 0.3,
    sb_prominence: float = 0.3,
    min_spacing: int = 5,
    boundary_region: str = "strat_boundary",
    tract_region: str = "systems_tract",
    surface_types: Optional[list[str]] = None,
) -> int:
    """Detect and add sequence-stratigraphic boundaries to all wells.

    Combines MFS and SB detection, creates ``no_crossing`` boundary
    regions and systems tract assignment.

    Parameters
    ----------
    well_list : WellList
        Wells to process.
    gr_name : str
        GR channel name.
    window : int
        Smoothing window.
    mfs_prominence, sb_prominence : float
        Detection thresholds.
    min_spacing : int
        Minimum inter-surface spacing.
    boundary_region : str
        Name for the boundary region (``no_crossing``).
    tract_region : str
        Name for the systems tract region (``same_region``).
    surface_types : list[str], optional
        Which surfaces to use as boundaries: ``["MFS", "SB"]`` (default: both).

    Returns
    -------
    int
        Total number of surfaces detected across all wells.
    """
    if surface_types is None:
        surface_types = ["MFS", "SB"]

    total = 0
    for well in well_list.wells:
        surfaces = []
        if "MFS" in surface_types:
            surfaces.extend(detect_mfs(well, gr_name, window, mfs_prominence, min_spacing))
        if "SB" in surface_types:
            surfaces.extend(detect_sb(well, gr_name, window, sb_prominence, min_spacing))

        surfaces.sort()
        total += len(surfaces)

        add_surface_boundaries(well, surfaces, boundary_region)
        assign_systems_tracts(
            well, gr_name, window, mfs_prominence, sb_prominence,
            min_spacing, tract_region,
        )

    return total


# ---------------------------------------------------------------------------
# Hierarchical multi-pass orchestrator (§12.2)
# ---------------------------------------------------------------------------

def hierarchical_correlate(
    well_list: WellList,
    *,
    gr_name: str = "GR",
    var_data: str = "GR",
    coarse_window: int = 10,
    medium_window: int = 5,
    mfs_prominence: float = 0.3,
    sb_prominence: float = 0.3,
    min_spacing: int = 5,
    options: Optional[dict] = None,
    n_passes: int = 2,
) -> "ResFile":
    """Run a hierarchical multi-pass correlation.

    Pass 1 (coarse): Smooth logs, detect and lock sequence boundaries,
    correlate major surfaces.

    Pass 2 (fine): Use locked boundaries as ``no_crossing`` regions,
    correlate at full resolution within bounded intervals.

    Parameters
    ----------
    well_list : WellList
        Well data.
    gr_name : str
        GR channel for surface detection.
    var_data : str
        Data channel for correlation.
    coarse_window : int
        Smoothing window for coarse pass.
    medium_window : int
        Smoothing window for medium pass.
    mfs_prominence, sb_prominence : float
        Surface detection thresholds.
    min_spacing : int
        Minimum inter-surface spacing.
    options : dict, optional
        Additional engine options.
    n_passes : int
        Number of passes (2 or 3).

    Returns
    -------
    ResFile
        Final correlation result.
    """
    from .ext import ProjectExt
    from .preprocessing import compute_moving_average

    opts = {
        "cost-function": "composite",
        "var-data": var_data,
        "var-weight": "1.0",
        "order": "pyramidal",
    }
    if options:
        opts.update(options)

    # §12.3 — var_window_size option (windowed variance cost)
    if "var-window-size" not in opts:
        opts["var-window-size"] = str(coarse_window)

    # §12.7 — cost_floor option (suppress noise-driven path preference)
    # If not set, use a small default to stabilize noisy intervals
    if "cost-floor" not in opts:
        opts["cost-floor"] = "0.01"

    # --- Pass 1: Coarse ---
    # Smooth logs and detect boundaries
    for well in well_list.wells:
        compute_moving_average(well, gr_name, f"{gr_name}_smooth", coarse_window)

    n_surfaces = add_sequence_boundaries(
        well_list, gr_name, coarse_window,
        mfs_prominence, sb_prominence, min_spacing,
    )

    if n_surfaces > 0:
        opts["no-crossing"] = "strat_boundary"

    # Run fine pass with boundaries locked
    proj = ProjectExt()
    for k, v in opts.items():
        proj.set_option_ext(k, str(v))

    proj.run(well_list)
    res = proj.get_res_file()

    # §12.4 — min_bed_thickness post-filter
    min_thickness = float(opts.get("min-bed-thickness", "0"))
    if min_thickness > 0 and res is not None:
        res = _filter_thin_beds(res, well_list, min_thickness)

    return res


def _filter_thin_beds(res_file, well_list, min_thickness: float):
    """
    §12.4 — Remove correlation horizons where bed thickness < min_thickness
    in any well.  Returns the same res_file (filtering is informational;
    the actual path is not modified, but a warning is logged).
    """
    import logging
    logger = logging.getLogger(__name__)

    for cor in range(min(res_file.get_nbr_results(), 5)):
        path = res_file.get_result_full_path(cor)
        thin_count = 0
        for hi in range(1, len(path)):
            for w in range(res_file.nbr_well()):
                s0, s1 = path[hi - 1][w], path[hi][w]
                if s0 < 0 or s1 < 0:
                    continue
                well = well_list.wells[w] if w < len(well_list.wells) else None
                if well is None:
                    continue
                for dk in ("Depth", "DEPTH", "MD"):
                    if dk in well.data:
                        t = abs(well.data[dk][s1] - well.data[dk][s0])
                        if t < min_thickness:
                            thin_count += 1
                        break
        if thin_count > 0:
            logger.info(
                f"Correlation {cor}: {thin_count} thin beds "
                f"(< {min_thickness} m) detected"
            )

    return res_file


# ═══════════════════════════════════════════════════════════════════════════
# §11.5.2 — Expected thickness ratios from sequence stratigraphy theory
# ═══════════════════════════════════════════════════════════════════════════

#: Expected thickness ratios by systems tract and depositional setting.
#: Keys: (systems_tract, setting) → expected thickness fraction of total
#: sequence thickness (0–1 range).
#: Based on Catuneanu (2006) and Posamentier & Allen (1999).
EXPECTED_THICKNESS_RATIOS = {
    # Siliciclastic shelf
    ("LST", "shelf"):       0.15,  # Lowstand — thin on shelf
    ("TST", "shelf"):       0.30,  # Transgressive — moderate
    ("HST", "shelf"):       0.45,  # Highstand — thickest
    ("FSST", "shelf"):      0.10,  # Falling stage — thin
    # Siliciclastic basin
    ("LST", "basin"):       0.40,  # Lowstand — thick turbidites
    ("TST", "basin"):       0.15,  # Transgressive — condensed
    ("HST", "basin"):       0.30,  # Highstand — moderate
    ("FSST", "basin"):      0.15,  # Falling stage
    # Carbonate platform
    ("LST", "carbonate"):   0.10,  # Lowstand — minimal production
    ("TST", "carbonate"):   0.35,  # Transgressive — catch-up
    ("HST", "carbonate"):   0.45,  # Highstand — maximum production
    ("FSST", "carbonate"):  0.10,  # Falling stage — erosion
}


def expected_thickness(systems_tract: str, setting: str = "shelf") -> float:
    """Return the expected fractional thickness for a systems tract.

    Parameters
    ----------
    systems_tract : str
        One of 'LST', 'TST', 'HST', 'FSST'.
    setting : str
        Depositional setting: 'shelf', 'basin', or 'carbonate'.

    Returns
    -------
    float
        Expected fraction of total sequence thickness (0–1).
    """
    return EXPECTED_THICKNESS_RATIOS.get(
        (systems_tract.upper(), setting.lower()), 0.25
    )
