"""
weco.preprocessing — Data conditioning transforms for well correlation
======================================================================

Pre-engine transforms that derive geologically meaningful data channels
from raw well logs, improving WeCo correlation quality.

All functions operate on :class:`weco.data.Well` or :class:`weco.data.WellList`
objects and add new *data* or *region* channels in-place.

Usage example::

    from weco.data import WellList
    from weco.preprocessing import (
        compute_vshale, compute_stacking_pattern, compute_porosity_density,
        normalise_log, compute_electrofacies,
    )

    wl = WellList("wells.txt")

    # Per-well transforms
    for w in wl.wells:
        compute_vshale(w, gr_name="GR")
        compute_stacking_pattern(w, gr_name="GR")
        compute_porosity_density(w, rhob_name="RHOB")

    # Cross-well normalisation
    normalise_log(wl, "GR", method="percentile")

    # Unsupervised electrofacies
    compute_electrofacies(wl, log_names=["GR", "RT"], n_clusters=5)
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

import numpy as np

# ---------------------------------------------------------------------------
#  Internal helpers
# ---------------------------------------------------------------------------

def _array(well, name: str) -> np.ndarray:
    """Extract a named data channel as a numpy float64 array."""
    if name not in well.data:
        raise KeyError(f"Data channel '{name}' not found in well '{well.name}'. "
                       f"Available: {sorted(well.data.keys())}")
    return np.asarray(well.data[name], dtype=np.float64)


def _labels_to_intervals(labels: np.ndarray) -> list:
    """Convert a per-marker label array to [(id, start, length), ...] region format."""
    intervals = []
    if len(labels) == 0:
        return intervals
    start = 0
    cur = int(labels[0])
    for i in range(1, len(labels)):
        v = int(labels[i])
        if v != cur:
            intervals.append((cur, start, i - start))
            start = i
            cur = v
    intervals.append((cur, start, len(labels) - start))
    return intervals


def _region_to_array(well, region_name: str, default: float = 0.0) -> np.ndarray:
    """Expand a region to a per-marker float array."""
    if region_name not in well.region:
        raise KeyError(f"Region '{region_name}' not found in well '{well.name}'.")
    arr = np.full(well.size, default, dtype=np.float64)
    for rid, start, length in well.region[region_name]:
        arr[start:start + length] = float(rid)
    return arr


# ═══════════════════════════════════════════════════════════════════════════
#  Single-well transforms
# ═══════════════════════════════════════════════════════════════════════════

def compute_vshale(
    well,
    gr_name: str = "GR",
    output_name: str = "Vshale",
    method: str = "linear",
    gr_clean: Optional[float] = None,
    gr_shale: Optional[float] = None,
) -> bool:
    """
    Compute shale volume from gamma-ray log.

    Parameters
    ----------
    well : Well
        Target well (modified in-place).
    gr_name : str
        Name of the gamma-ray data channel.
    output_name : str
        Name for the output Vshale data channel.
    method : str
        ``"linear"`` (default) or ``"clavier"`` or ``"steiber"``.
    gr_clean, gr_shale : float, optional
        Clean-sand and shale-line GR values. If *None*, uses the 5th and
        95th percentiles of the GR distribution.

    Returns
    -------
    bool
        True on success.
    """
    if gr_name not in well.data:
        return False

    gr = _array(well, gr_name)

    if gr_clean is None:
        gr_clean = np.nanpercentile(gr, 5)
    if gr_shale is None:
        gr_shale = np.nanpercentile(gr, 95)

    igr = np.clip((gr - gr_clean) / (gr_shale - gr_clean + 1e-10), 0.0, 1.0)

    if method == "clavier":
        vsh = 1.7 - np.sqrt(3.38 - (igr + 0.7) ** 2)
        vsh = np.clip(vsh, 0.0, 1.0)
    elif method == "steiber":
        vsh = igr / (3.0 - 2.0 * igr)
    else:  # linear
        vsh = igr

    well.add_data(output_name, vsh.tolist())
    return True


def compute_stacking_pattern(
    well,
    gr_name: str = "GR",
    output_name: str = "StackingPattern",
    window: int = 5,
) -> bool:
    """
    Compute smoothed GR derivative as a stacking-pattern indicator.

    Positive values → fining-upward (transgressive).
    Negative values → coarsening-upward (regressive).

    Parameters
    ----------
    well : Well
    gr_name : str
    output_name : str
    window : int
        Smoothing window (number of markers) for moving-average filter.
    """
    if gr_name not in well.data:
        return False

    gr = _array(well, gr_name)
    deriv = np.gradient(gr)

    if window > 1:
        kernel = np.ones(window) / window
        deriv = np.convolve(deriv, kernel, mode="same")

    well.add_data(output_name, deriv.tolist())
    return True


def compute_porosity_density(
    well,
    rhob_name: str = "RHOB",
    output_name: str = "PHID",
    rho_matrix: float = 2.65,
    rho_fluid: float = 1.0,
) -> bool:
    """
    Compute density porosity: ``phi = (rho_matrix - rho_b) / (rho_matrix - rho_fluid)``.

    Parameters
    ----------
    well : Well
    rhob_name : str
        Bulk density data channel name.
    rho_matrix : float
        Matrix density (g/cc). Default 2.65 (quartz sandstone).
    rho_fluid : float
        Fluid density (g/cc). Default 1.0 (fresh water).
    """
    if rhob_name not in well.data:
        return False

    rhob = _array(well, rhob_name)
    phi = (rho_matrix - rhob) / (rho_matrix - rho_fluid + 1e-10)
    phi = np.clip(phi, 0.0, 0.50)

    well.add_data(output_name, phi.tolist())
    return True


def compute_log_ratio(
    well,
    numerator: str,
    denominator: str,
    output_name: Optional[str] = None,
    log_scale: bool = True,
) -> bool:
    """
    Compute ratio (or log-ratio) of two data channels.

    Useful for: deep/shallow resistivity ratio (invasion indicator),
    neutron-density separation, etc.

    Parameters
    ----------
    log_scale : bool
        If True, output is log10(num/denom). Otherwise raw ratio.
    """
    if numerator not in well.data or denominator not in well.data:
        return False

    num = _array(well, numerator)
    den = _array(well, denominator)
    den = np.where(np.abs(den) < 1e-30, 1e-30, den)

    ratio = num / den
    if log_scale:
        ratio = np.log10(np.abs(ratio) + 1e-30)

    name = output_name or f"{numerator}/{denominator}"
    well.add_data(name, ratio.tolist())
    return True


def compute_moving_average(
    well,
    data_name: str,
    output_name: Optional[str] = None,
    window: int = 5,
) -> bool:
    """
    Smooth a data channel with a centred moving-average filter.
    """
    if data_name not in well.data:
        return False

    vals = _array(well, data_name)
    kernel = np.ones(window) / window
    smoothed = np.convolve(vals, kernel, mode="same")

    name = output_name or f"{data_name}_smooth{window}"
    well.add_data(name, smoothed.tolist())
    return True


# ═══════════════════════════════════════════════════════════════════════════
#  Cross-well normalisation
# ═══════════════════════════════════════════════════════════════════════════

def normalise_log(
    well_list,
    log_name: str,
    output_name: Optional[str] = None,
    method: str = "percentile",
    target_range: Tuple[float, float] = (0.0, 1.0),
) -> bool:
    """
    Normalise a log across all wells to a common scale.

    This is critical when wells were logged with different tools or mud
    systems — raw GR or resistivity values are not directly comparable.

    Parameters
    ----------
    well_list : WellList
    log_name : str
    output_name : str, optional
        If None, overwrites the original channel.
    method : str
        ``"percentile"``  — map P5..P95 to target_range (robust to outliers).
        ``"zscore"``      — mean=0, std=1  (ignore target_range).
        ``"minmax"``      — map global min..max to target_range.
    """
    wells = [w for w in well_list.wells if log_name in w.data]
    if not wells:
        return False

    all_vals = np.concatenate([_array(w, log_name) for w in wells])

    if method == "zscore":
        mu, sigma = np.nanmean(all_vals), np.nanstd(all_vals) + 1e-10
        for w in wells:
            vals = (_array(w, log_name) - mu) / sigma
            w.add_data(output_name or log_name, vals.tolist())

    elif method == "minmax":
        lo, hi = np.nanmin(all_vals), np.nanmax(all_vals)
        span = hi - lo + 1e-10
        for w in wells:
            vals = ((_array(w, log_name) - lo) / span) * (target_range[1] - target_range[0]) + target_range[0]
            w.add_data(output_name or log_name, vals.tolist())

    else:  # percentile
        p05, p95 = np.nanpercentile(all_vals, [5, 95])
        span = p95 - p05 + 1e-10
        for w in wells:
            vals = ((_array(w, log_name) - p05) / span) * (target_range[1] - target_range[0]) + target_range[0]
            vals = np.clip(vals, target_range[0], target_range[1])
            w.add_data(output_name or log_name, vals.tolist())

    return True


# ═══════════════════════════════════════════════════════════════════════════
#  Electrofacies (unsupervised)
# ═══════════════════════════════════════════════════════════════════════════

def compute_electrofacies(
    well_list,
    log_names: List[str],
    n_clusters: int = 5,
    output_region: str = "electrofacies",
    output_data: Optional[str] = "electrofacies_data",
    random_state: int = 42,
) -> bool:
    """
    Cluster multi-log responses into discrete electrofacies using K-Means.

    Electrofacies can then be used as the ``dist_facies`` region for the
    distality cost function — even when geologist-interpreted facies are
    unavailable.

    Parameters
    ----------
    well_list : WellList
    log_names : list of str
        Log channels to use as clustering features.
    n_clusters : int
        Number of electrofacies classes.
    output_region : str
        Region channel name to create on each well.
    output_data : str or None
        Also create a continuous data channel (for variance cost). None to skip.
    random_state : int
        Random seed for reproducibility.
    """
    try:
        from sklearn.cluster import KMeans
    except ImportError:
        print("*ERR* scikit-learn is required for electrofacies. "
              "Install with: pip install scikit-learn")
        return False

    # Collect feature matrices per well
    well_indices = []     # (well_obj, start_row, end_row)
    feature_rows = []

    for w in well_list.wells:
        if not all(name in w.data for name in log_names):
            continue
        X = np.column_stack([_array(w, name) for name in log_names])
        well_indices.append((w, len(feature_rows), len(feature_rows) + len(X)))
        feature_rows.append(X)

    if not feature_rows:
        return False

    X_all = np.vstack(feature_rows)

    # Standardise
    mu = np.nanmean(X_all, axis=0)
    sigma = np.nanstd(X_all, axis=0) + 1e-10
    X_norm = (X_all - mu) / sigma

    # Handle NaN (replace with column mean = 0 after normalisation)
    X_norm = np.nan_to_num(X_norm, nan=0.0)

    # Cluster
    km = KMeans(n_clusters=n_clusters, random_state=random_state, n_init=10)
    labels_all = km.fit_predict(X_norm)

    # Assign back to wells
    for w, start, end in well_indices:
        labels = labels_all[start:end]

        # Region
        intervals = _labels_to_intervals(labels)
        # Remap labels to start from 1 (WeCo regions use 0 as "no region")
        intervals = [(rid + 1, s, l) for rid, s, l in intervals]
        w.add_region(output_region, intervals)

        # Optional continuous data
        if output_data:
            w.add_data(output_data, (labels + 1).astype(float).tolist())

    return True


# ═══════════════════════════════════════════════════════════════════════════
# §11.2.4 — Auto-Suggest Facies Groups
# ═══════════════════════════════════════════════════════════════════════════


def suggest_facies_groups(
    well_list,
    facies_region: str = "electrofacies",
    n_groups: int = 3,
) -> str:
    """
    Auto-suggest lateral equivalence facies groups using transition proximity.

    Returns a ``dist_facies_groups`` option string (semicolon-separated).

    Parameters
    ----------
    well_list : WellList
    facies_region : str
    n_groups : int

    Returns
    -------
    str
        e.g. ``"1,2;3,4,5;6,7"``
    """
    trans = compute_facies_transition_matrix(well_list, facies_region)
    matrix = trans["matrix"]
    facies_ids = trans["facies_ids"]

    if len(facies_ids) <= n_groups:
        return ";".join(str(f) for f in facies_ids)

    n = len(facies_ids)
    id_map = {fid: i for i, fid in enumerate(facies_ids)}
    prox = np.zeros((n, n))
    for (f_from, f_to), prob in matrix.items():
        i, j = id_map.get(f_from), id_map.get(f_to)
        if i is not None and j is not None:
            prox[i, j] = prob
            prox[j, i] = max(prox[j, i], prob)

    groups = [[fid] for fid in facies_ids]
    while len(groups) > n_groups:
        best_sim = -1
        best_i, best_j = 0, 1
        for i in range(len(groups)):
            for j in range(i + 1, len(groups)):
                sim = 0
                count = 0
                for fi in groups[i]:
                    for fj in groups[j]:
                        ii, jj = id_map.get(fi), id_map.get(fj)
                        if ii is not None and jj is not None:
                            sim += prox[ii, jj]
                            count += 1
                avg_sim = sim / max(count, 1)
                if avg_sim > best_sim:
                    best_sim = avg_sim
                    best_i, best_j = i, j
        groups[best_i].extend(groups[best_j])
        groups.pop(best_j)

    return ";".join(",".join(str(f) for f in g) for g in groups)


# ═══════════════════════════════════════════════════════════════════════════
#  Biostratigraphy
# ═══════════════════════════════════════════════════════════════════════════

def add_biozones(
    well,
    biozones: List[Tuple[str, int, int]],
    zone_order: Optional[List[str]] = None,
    output_region: str = "biozone",
) -> bool:
    """
    Add biostratigraphic zonation as an ordered region.

    Parameters
    ----------
    well : Well
    biozones : list of (zone_name, start_marker, length)
        Biozone intervals.
    zone_order : list of str, optional
        Ordered list of zone names (oldest → youngest). If provided,
        region IDs are assigned in this order (1, 2, 3, ...).
        If None, zones are numbered in order of first appearance.
    output_region : str
        Region name on the well.

    Returns
    -------
    bool

    Notes
    -----
    The resulting region is ideal for ``no_crossing`` (hard ordering
    constraint) and ``same_region`` (soft preference for intra-zone
    correlation).

    Example::

        add_biozones(well, [("NP10", 0, 15), ("NP11", 15, 27), ("NP12", 42, 38)],
                     zone_order=["NP10", "NP11", "NP12"])
        # Then in engine options:
        #   no_crossing  = biozone
        #   same_region2 = biozone
    """
    if zone_order is None:
        seen = []
        for name, _, _ in biozones:
            if name not in seen:
                seen.append(name)
        zone_order = seen

    name_to_id = {name: i + 1 for i, name in enumerate(zone_order)}

    intervals = []
    for name, start, length in biozones:
        rid = name_to_id.get(name, 0)
        if rid > 0:
            intervals.append((rid, start, length))

    well.add_region(output_region, intervals)
    return True


def read_biozone_csv(
    filepath: str,
    well_list,
    well_name_col: str = "well",
    zone_col: str = "zone",
    top_col: str = "top_marker",
    base_col: str = "base_marker",
    output_region: str = "biozone",
) -> int:
    """
    Read a CSV file with biozone picks and add as regions to wells.

    Expected CSV format::

        well,zone,top_marker,base_marker
        Well_A,NP10,0,14
        Well_A,NP11,15,41
        Well_B,NP10,0,21
        ...

    Parameters
    ----------
    filepath : str
    well_list : WellList
    well_name_col, zone_col, top_col, base_col : str
        Column names.
    output_region : str

    Returns
    -------
    int
        Number of wells updated.
    """
    import csv

    # Parse CSV
    well_zones = {}  # well_name -> [(zone, top, base), ...]
    all_zones = []
    with open(filepath, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            wn = row[well_name_col].strip()
            zn = row[zone_col].strip()
            top = int(row[top_col])
            base = int(row[base_col])
            well_zones.setdefault(wn, []).append((zn, top, base))
            if zn not in all_zones:
                all_zones.append(zn)

    # Apply to wells
    count = 0
    for w in well_list.wells:
        if w.name in well_zones:
            biozones = [(zn, top, base - top + 1) for zn, top, base in well_zones[w.name]]
            add_biozones(w, biozones, zone_order=all_zones, output_region=output_region)
            count += 1

    return count


# ═══════════════════════════════════════════════════════════════════════════
#  Facies map projection
# ═══════════════════════════════════════════════════════════════════════════

def project_facies_map(
    well,
    facies_grid: np.ndarray,
    x_origin: float,
    y_origin: float,
    cell_size: float,
    output_region: str = "map_facies",
    marker_start: int = 0,
    marker_end: Optional[int] = None,
) -> bool:
    """
    Sample a 2D facies map at the well's (x, y) location.

    The facies map is a 2D numpy integer array where each cell contains
    a facies code. The map is for a single depositional time step.

    Parameters
    ----------
    well : Well
    facies_grid : ndarray of shape (ny, nx)
        Integer facies codes.
    x_origin, y_origin : float
        Map origin (lower-left corner).
    cell_size : float
        Grid cell size (assumed square).
    output_region : str
        Region name to create.
    marker_start, marker_end : int
        Marker range to assign this facies to.

    Returns
    -------
    bool
    """
    # Compute grid indices for the well location
    ix = int((well.x - x_origin) / cell_size)
    iy = int((well.y - y_origin) / cell_size)

    ny, nx = facies_grid.shape
    if not (0 <= ix < nx and 0 <= iy < ny):
        return False

    facies_code = int(facies_grid[iy, ix])
    end = marker_end if marker_end is not None else well.size

    well.add_region(output_region, [(facies_code, marker_start, end - marker_start)])
    return True


# ═══════════════════════════════════════════════════════════════════════════
#  Facies clustering — lateral equivalence groups (§13.2)
# ═══════════════════════════════════════════════════════════════════════════

def parse_facies_groups(spec: str) -> dict:
    """Parse a semicolon-separated facies group specification.

    Format: ``"1,2,3;4,5;6,7,8"`` — each semicolon-delimited group
    contains comma-separated facies IDs that are considered laterally
    equivalent.

    Returns
    -------
    dict[int, int]
        Mapping ``{original_facies_id: group_index}``.  Group indices
        start at 1.

    Example
    -------
    >>> parse_facies_groups("1,2,3;4,5;6,7,8")
    {1: 1, 2: 1, 3: 1, 4: 2, 5: 2, 6: 3, 7: 3, 8: 3}
    """
    mapping: dict = {}
    for gi, group_str in enumerate(spec.split(";"), start=1):
        for tok in group_str.split(","):
            tok = tok.strip()
            if tok:
                mapping[int(tok)] = gi
    return mapping


def remap_facies_groups(
    well_list,
    facies_region: str = "FACIES",
    groups: str | dict = "",
    output_region: str = "FACIES_GRP",
) -> bool:
    """Remap facies regions by lateral-equivalence group membership.

    Creates a new region ``output_region`` on each well where the
    region IDs correspond to group indices rather than original facies
    codes.  Facies in the same group get the same ID, so the engine's
    built-in ``same-region`` or ``dist-facies`` will treat them as
    identical.

    Parameters
    ----------
    well_list : WellList
        Wells with a ``facies_region`` region defined.
    facies_region : str
        Name of the existing facies region on each well.
    groups : str or dict
        Either a semicolon-separated spec (``"1,2,3;4,5;6,7,8"``)
        or a pre-parsed ``{facies_id: group_index}`` dict.
    output_region : str
        Name for the new grouped region.

    Returns
    -------
    bool
        True if at least one well was processed.

    Reference
    ---------
    Baville (2022) §3.4.5, §6.3.3 — facies associations A, B, C.
    """
    if isinstance(groups, str):
        if not groups.strip():
            return False
        mapping = parse_facies_groups(groups)
    else:
        mapping = dict(groups)

    if not mapping:
        return False

    processed = False
    for w in well_list.wells:
        if facies_region not in w.region:
            continue
        old_regions = w.region[facies_region]
        new_regions = []
        for (rid, start, length) in old_regions:
            gid = mapping.get(rid, rid)  # unmapped → keep original
            new_regions.append((gid, start, length))

        # Merge consecutive regions with same group ID
        merged = []
        for (gid, start, length) in new_regions:
            if merged and merged[-1][0] == gid and merged[-1][1] + merged[-1][2] == start:
                merged[-1] = (gid, merged[-1][1], merged[-1][2] + length)
            else:
                merged.append((gid, start, length))

        w.region[output_region] = merged
        processed = True

    return processed


# ═══════════════════════════════════════════════════════════════════════════
#  Convenience: apply all standard transforms
# ═══════════════════════════════════════════════════════════════════════════

def apply_standard_preprocessing(
    well_list,
    gr_name: str = "GR",
    enable_vshale: bool = True,
    enable_stacking: bool = True,
    enable_normalise: bool = True,
    enable_electrofacies: bool = False,
    electrofacies_logs: Optional[List[str]] = None,
    n_clusters: int = 5,
) -> dict:
    """
    One-call convenience for the most common preprocessing steps.

    Returns a dict of ``{step_name: success_bool}``.
    """
    results = {}

    if enable_normalise and gr_name:
        results["normalise_GR"] = normalise_log(well_list, gr_name,
                                                 output_name=f"{gr_name}_norm")

    for w in well_list.wells:
        if enable_vshale and gr_name:
            results.setdefault("vshale", True)
            results["vshale"] &= compute_vshale(w, gr_name=gr_name)

        if enable_stacking and gr_name:
            results.setdefault("stacking", True)
            results["stacking"] &= compute_stacking_pattern(w, gr_name=gr_name)

    if enable_electrofacies and electrofacies_logs:
        results["electrofacies"] = compute_electrofacies(
            well_list, log_names=electrofacies_logs, n_clusters=n_clusters
        )

    return results


# ---------------------------------------------------------------------------
# Seismic attribute extraction (§11.0.1)
# ---------------------------------------------------------------------------

def extract_seismic_attributes(
    well: "Well",
    segy_path: str,
    attributes: list[str] | None = None,
    window: int = 5,
) -> bool:
    """Extract seismic attributes at well locations from SEG-Y file.

    Uses the ``segyio`` library to read the SEG-Y file and interpolate
    attribute values along the well trajectory.

    Parameters
    ----------
    well : Well
        Well with x, y coordinates and depth data.
    segy_path : str
        Path to SEG-Y file.
    attributes : list[str], optional
        Attributes to extract. Default: ["amplitude"].
    window : int
        Averaging window (traces) around well location.

    Returns
    -------
    bool
        True if extraction succeeded.
    """
    try:
        import segyio
    except ImportError:
        print("*WARN* segyio not installed — skipping seismic extraction")
        return False

    if attributes is None:
        attributes = ["amplitude"]

    try:
        with segyio.open(segy_path, "r", ignore_geometry=True) as f:
            n_traces = f.tracecount
            n_samples = len(f.samples)
            sample_rate = f.samples[1] - f.samples[0] if n_samples > 1 else 1.0

            # Find nearest trace to well location
            min_dist = float("inf")
            best_trace = 0
            for i in range(n_traces):
                hdr = f.header[i]
                sx = hdr.get(segyio.TraceField.SourceX, 0) / 100.0
                sy = hdr.get(segyio.TraceField.SourceY, 0) / 100.0
                d = (sx - well.x) ** 2 + (sy - well.y) ** 2
                if d < min_dist:
                    min_dist = d
                    best_trace = i

            # Extract trace data in window around best trace
            half_w = window // 2
            start_t = max(0, best_trace - half_w)
            end_t = min(n_traces, best_trace + half_w + 1)

            traces = np.array([f.trace[t] for t in range(start_t, end_t)])
            avg_trace = np.mean(traces, axis=0)

            # Resample to well depth grid
            depth = list(well.data.get("depth", range(well.size)))
            n_markers = well.size
            attr_values = np.interp(
                np.linspace(0, n_samples - 1, n_markers),
                np.arange(n_samples),
                avg_trace,
            )

            well.add_data("seismic_amplitude", attr_values.tolist())
            return True

    except Exception as e:
        print(f"*WARN* Seismic extraction failed: {e}")
        return False


# ---------------------------------------------------------------------------
# Erosion surface detection (§11.7.1)
# ---------------------------------------------------------------------------

def detect_erosion_surfaces(
    well: "Well",
    gr_name: str = "GR",
    threshold: float = 0.5,
    min_spacing: int = 5,
    output_region: str = "erosion",
) -> bool:
    """Detect erosion surfaces from sharp GR log bases.

    Erosion surfaces are identified by abrupt decreases in GR
    (sharp base = erosional truncation at top of regressive cycle).

    Parameters
    ----------
    well : Well
        Well with a GR log.
    gr_name : str
        GR channel name.
    threshold : float
        Minimum normalised GR drop to detect an erosion (0-1).
    min_spacing : int
        Minimum spacing between surfaces.
    output_region : str
        Region name to create.

    Returns
    -------
    bool
        True if at least one erosion surface was detected.
    """
    if gr_name not in well.data:
        return False

    gr = np.array(well.data[gr_name], dtype=float)
    gr_range = gr.max() - gr.min()
    if gr_range < 1e-10:
        return False

    gr_norm = (gr - gr.min()) / gr_range

    # Detect sharp bases: large negative gradient
    erosion_indices = []
    for i in range(1, len(gr_norm)):
        drop = gr_norm[i - 1] - gr_norm[i]
        if drop > threshold:
            if not erosion_indices or (i - erosion_indices[-1]) >= min_spacing:
                erosion_indices.append(i)

    if not erosion_indices:
        return False

    # Create region: each interval between erosions gets unique ID
    n = well.size
    intervals = []
    zone_id = 0
    prev = 0
    for idx in erosion_indices:
        if idx > prev:
            intervals.append((zone_id, prev, idx - prev))
            zone_id += 1
        prev = idx
    if prev < n:
        intervals.append((zone_id, prev, n - prev))

    well.add_region(output_region, intervals)
    return True


# ---------------------------------------------------------------------------
# Facies transition probability (§11.6.1)
# ---------------------------------------------------------------------------

def compute_facies_transition_matrix(
    well_list: "WellList",
    region_name: str = "facies",
) -> dict:
    """Compute facies transition probability matrix from well data.

    Counts vertical transitions between facies in all wells and
    normalises to row-wise probabilities.

    Parameters
    ----------
    well_list : WellList
        Wells with facies region.
    region_name : str
        Facies region name.

    Returns
    -------
    dict
        ``{"matrix": {(from, to): prob}, "facies_ids": list,
        "counts": {(from, to): int}}``
    """
    counts = {}
    totals = {}
    all_ids = set()

    for well in well_list.wells:
        if region_name not in getattr(well, "region", {}):
            continue
        intervals = well.region[region_name]
        for i in range(len(intervals) - 1):
            f_from = intervals[i][0]
            f_to = intervals[i + 1][0]
            all_ids.add(f_from)
            all_ids.add(f_to)
            counts[(f_from, f_to)] = counts.get((f_from, f_to), 0) + 1
            totals[f_from] = totals.get(f_from, 0) + 1

    matrix = {}
    for (f_from, f_to), count in counts.items():
        total = totals.get(f_from, 1)
        matrix[(f_from, f_to)] = count / total

    return {
        "matrix": matrix,
        "facies_ids": sorted(all_ids),
        "counts": counts,
    }


# ═══════════════════════════════════════════════════════════════════════════
# §11.0.2 — PVT Region Reader
# ═══════════════════════════════════════════════════════════════════════════


def read_pvt_regions(
    well,
    report_path: str,
    *,
    region_name: str = "PVT",
    depth_col: str = "MD",
    pvt_col: str = "PVT_REGION",
    delimiter: str = ",",
) -> int:
    """
    Read PVT region assignments from MDT/DST report CSV and add as a
    well region.

    Parameters
    ----------
    well : Well
    report_path : str
        CSV file with columns: depth, PVT region ID.
    region_name : str
    depth_col, pvt_col : str
    delimiter : str

    Returns
    -------
    int
        Number of PVT regions assigned.
    """
    import csv

    depth_key = None
    for dk in ("Depth", "DEPTH", "MD"):
        if dk in well.data:
            depth_key = dk
            break
    if depth_key is None:
        return 0

    depths = well.data[depth_key]
    regions = []

    with open(report_path, "r") as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        entries = []
        for row in reader:
            try:
                md = float(row[depth_col])
                pvt_id = int(row[pvt_col])
                entries.append((md, pvt_id))
            except (ValueError, KeyError):
                continue

    if not entries:
        return 0

    entries.sort()

    # Assign PVT region to each depth sample
    for md, pvt_id in entries:
        # Find nearest depth index
        best_idx = min(range(len(depths)), key=lambda i: abs(depths[i] - md))
        regions.append((pvt_id, best_idx, 1))

    if not hasattr(well, "region"):
        well.region = {}
    well.region[region_name] = regions

    return len(regions)


# ═══════════════════════════════════════════════════════════════════════════
# §11.0.5 — Autoencoder Feature Extraction (PyTorch)
# ═══════════════════════════════════════════════════════════════════════════


def autoencoder_features(
    well_list,
    log_names: List[str],
    *,
    latent_dim: int = 4,
    window_size: int = 20,
    epochs: int = 50,
    output_prefix: str = "AE",
) -> int:
    """
    Extract features using a 1D convolutional autoencoder on log windows.

    Requires PyTorch. Adds ``AE_0``, ``AE_1``, ... channels to each well.

    Parameters
    ----------
    well_list : WellList
    log_names : list of str
        Log channels to use as input.
    latent_dim : int
        Bottleneck dimension.
    window_size : int
        Sliding window size in samples.
    epochs : int
        Training epochs.
    output_prefix : str
        Prefix for output channel names.

    Returns
    -------
    int
        Number of features added per well.
    """
    try:
        import torch
        import torch.nn as nn
    except ImportError:
        raise ImportError(
            "Autoencoder features require PyTorch: pip install torch"
        )

    # Collect training windows from all wells
    windows = []
    for well in well_list.wells:
        n_channels = len(log_names)
        n_samples = well.size
        if n_samples < window_size:
            continue
        matrix = np.zeros((n_channels, n_samples))
        for ci, ln in enumerate(log_names):
            if ln in well.data:
                arr = np.array(well.data[ln])
                # Normalize per-well
                std = np.std(arr)
                if std > 1e-10:
                    arr = (arr - np.mean(arr)) / std
                matrix[ci, :len(arr)] = arr

        for start in range(0, n_samples - window_size + 1, window_size // 2):
            windows.append(matrix[:, start:start + window_size])

    if not windows:
        return 0

    X = torch.tensor(np.array(windows), dtype=torch.float32)

    # Simple 1D conv autoencoder
    class Autoencoder(nn.Module):
        def __init__(self):
            super().__init__()
            self.encoder = nn.Sequential(
                nn.Conv1d(n_channels, 8, 3, padding=1),
                nn.ReLU(),
                nn.AdaptiveAvgPool1d(latent_dim),
            )
            self.decoder = nn.Sequential(
                nn.ConvTranspose1d(8, n_channels, 3, padding=1),
                nn.AdaptiveAvgPool1d(window_size),
            )

        def forward(self, x):
            z = self.encoder(x)
            return self.decoder(z), z

    model = Autoencoder()
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    criterion = nn.MSELoss()

    for epoch in range(epochs):
        model.train()
        recon, _ = model(X)
        loss = criterion(recon, X)
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()

    # Extract features for each well
    model.eval()
    with torch.no_grad():
        for well in well_list.wells:
            n_samples = well.size
            if n_samples < window_size:
                for d in range(latent_dim):
                    well.data[f"{output_prefix}_{d}"] = [0.0] * n_samples
                continue

            matrix = np.zeros((n_channels, n_samples))
            for ci, ln in enumerate(log_names):
                if ln in well.data:
                    arr = np.array(well.data[ln])
                    std = np.std(arr)
                    if std > 1e-10:
                        arr = (arr - np.mean(arr)) / std
                    matrix[ci, :len(arr)] = arr

            features = np.zeros((latent_dim, n_samples))
            counts = np.zeros(n_samples)
            for start in range(0, n_samples - window_size + 1, max(1, window_size // 4)):
                win = torch.tensor(
                    matrix[:, start:start + window_size][np.newaxis],
                    dtype=torch.float32,
                )
                _, z = model(win)
                z_np = z.squeeze(0).numpy()  # (8, latent_dim)
                z_mean = z_np.mean(axis=0)   # (latent_dim,)
                for d in range(latent_dim):
                    features[d, start:start + window_size] += z_mean[d]
                counts[start:start + window_size] += 1

            counts[counts == 0] = 1
            for d in range(latent_dim):
                well.data[f"{output_prefix}_{d}"] = (features[d] / counts).tolist()

    return latent_dim


# ═══════════════════════════════════════════════════════════════════════════
# §11.12.3 — Structural domain regions
# ═══════════════════════════════════════════════════════════════════════════

def assign_structural_domains(well_list, domain_map, region_name="structural_domain"):
    """Assign structural domain regions to wells for same_region constraints.

    Wells in different structural domains (e.g. hangingwall vs footwall
    of a fault) should not be directly compared for dip-based costs
    like B3D.  This function creates a region on each well so the
    engine can enforce ``same_region`` constraints.

    Parameters
    ----------
    well_list : WellList
        The well list to annotate.
    domain_map : dict
        Mapping of well name/id (str or int) → domain_id (int).
        Wells not in the map get domain 0 (default domain).
    region_name : str
        Name of the region to create on each well.

    Example
    -------
    >>> assign_structural_domains(wl, {"W1": 1, "W2": 1, "W3": 2})
    # W1, W2 in domain 1 (hangingwall), W3 in domain 2 (footwall)
    """
    for well in well_list.wells:
        wid = str(well.well_id) if hasattr(well, 'well_id') else str(well)
        domain = domain_map.get(wid, domain_map.get(int(wid) if wid.isdigit() else wid, 0))
        n = well.well_size if hasattr(well, 'well_size') else len(next(iter(well.data.values()), []))
        well.regions[region_name] = [domain] * n
