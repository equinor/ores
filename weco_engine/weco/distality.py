"""
weco.distality — Sediment transport direction and distality computation
========================================================================

Compute per-well distality values from well coordinates and an assumed
sediment transport direction (azimuth).  The distality is the distance
projected onto the transport direction, normalised to [0, 1] across
the well panel.

Typical usage::

    from weco.distality import compute_distality, sweep_transport

    # Compute distality for a single direction
    compute_distality(well_list, azimuth_deg=120.0)

    # Sweep multiple directions and compare
    results = sweep_transport(well_list, azimuths=[0, 45, 90, 135])

Reference
---------
Baville (2022) §3.4.3 (pp. 78–79): The distality is computed from
well positions relative to a *principal sediment transport direction*.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple, Union

import numpy as np


# ═══════════════════════════════════════════════════════════════════════════
#  Core distality computation
# ═══════════════════════════════════════════════════════════════════════════

def compute_distality(
    well_list,
    azimuth_deg: float = 0.0,
    output_data: str = "distality",
    output_region: str = "distal",
    n_bins: int = 5,
    assign_region: bool = True,
) -> Dict[str, float]:
    """Compute per-well distality from coordinates and transport direction.

    The transport direction is an azimuth (degrees clockwise from North).
    Each well's position is projected onto this direction.  The projected
    distance is normalised to [0, 1] where 0 = most proximal and
    1 = most distal.

    Parameters
    ----------
    well_list : WellList
        Well list (must have ``x``, ``y`` attributes on each well).
    azimuth_deg : float
        Sediment transport direction in degrees clockwise from North.
        0° = North, 90° = East, 180° = South, 270° = West.
        Wells further along this direction are more *distal*.
    output_data : str or None
        If given, add a constant data channel on each well with this
        name, value = normalised distality.
    output_region : str or None
        If given, add a discretised distality region (n_bins classes).
    n_bins : int
        Number of distality bins for the region (default 5).
    assign_region : bool
        Whether to create discrete regions (requires ``output_region``).

    Returns
    -------
    dict[str, float]
        ``{well_name: distality_value}`` (0 = proximal, 1 = distal).
    """
    wells = well_list.wells
    if not wells:
        return {}

    # Convert azimuth to a unit vector
    # Azimuth: 0 = North (+y), 90 = East (+x), clockwise
    theta = math.radians(azimuth_deg)
    dx = math.sin(theta)  # East component
    dy = math.cos(theta)  # North component

    # Project each well onto the transport direction
    projections: Dict[str, float] = {}
    for w in wells:
        proj = w.x * dx + w.y * dy
        projections[w.name] = proj

    # Normalise to [0, 1]
    vals = list(projections.values())
    p_min = min(vals)
    p_max = max(vals)
    rng = p_max - p_min
    if rng < 1e-10:
        rng = 1.0

    distalities: Dict[str, float] = {}
    for name, proj in projections.items():
        distalities[name] = (proj - p_min) / rng

    # Assign to wells
    for w in wells:
        d = distalities[w.name]

        if output_data:
            # Constant data channel (same distality for all markers)
            w.add_data(output_data, [d] * w.size)

        if assign_region and output_region:
            # Discretise into bins
            bin_id = min(int(d * n_bins), n_bins - 1)
            w.add_region(output_region, [(bin_id, 0, w.size)])

    return distalities


# ═══════════════════════════════════════════════════════════════════════════
#  Transport direction estimation
# ═══════════════════════════════════════════════════════════════════════════

def estimate_transport_from_facies(
    well_list,
    facies_region: str = "facies",
    proximal_ids: Optional[List[int]] = None,
    distal_ids: Optional[List[int]] = None,
) -> float:
    """Estimate transport direction from facies distribution.

    A simple approach: compute the vector from the centroid of
    proximal-facies wells to the centroid of distal-facies wells.

    Parameters
    ----------
    well_list : WellList
    facies_region : str
        Region name containing facies codes.
    proximal_ids : list of int
        Facies IDs considered proximal (e.g., fluvial, shoreface).
    distal_ids : list of int
        Facies IDs considered distal (e.g., offshore marine).

    Returns
    -------
    float
        Estimated azimuth in degrees (0–360).
    """
    if proximal_ids is None or distal_ids is None:
        return 0.0

    prox_x, prox_y, prox_n = 0.0, 0.0, 0
    dist_x, dist_y, dist_n = 0.0, 0.0, 0

    for w in well_list.wells:
        if facies_region not in w.region:
            continue
        # Count dominant facies
        prox_count = 0
        dist_count = 0
        for rid, start, length in w.region[facies_region]:
            if rid in proximal_ids:
                prox_count += length
            elif rid in distal_ids:
                dist_count += length

        if prox_count > dist_count:
            prox_x += w.x
            prox_y += w.y
            prox_n += 1
        elif dist_count > prox_count:
            dist_x += w.x
            dist_y += w.y
            dist_n += 1

    if prox_n == 0 or dist_n == 0:
        return 0.0

    # Vector from proximal centroid to distal centroid
    vec_x = (dist_x / dist_n) - (prox_x / prox_n)
    vec_y = (dist_y / dist_n) - (prox_y / prox_n)

    # Convert to azimuth (degrees from North, clockwise)
    azimuth = math.degrees(math.atan2(vec_x, vec_y)) % 360.0
    return azimuth


# ═══════════════════════════════════════════════════════════════════════════
#  Multi-scenario sweep
# ═══════════════════════════════════════════════════════════════════════════

def sweep_transport(
    well_list,
    azimuths: Optional[List[float]] = None,
    n_steps: int = 12,
    output_data: str = "distality",
) -> List[Dict]:
    """Compute distality for multiple transport directions.

    Useful for exploring which transport direction produces the most
    geologically consistent correlations.

    Parameters
    ----------
    well_list : WellList
    azimuths : list of float, optional
        Explicit azimuths to test.  If None, generates ``n_steps``
        evenly spaced azimuths in [0°, 180°).
    n_steps : int
        Number of azimuths if ``azimuths`` is None.
    output_data : str
        Data channel name for distality (suffixed with azimuth).

    Returns
    -------
    list of dict
        Each: ``{"azimuth": float, "distalities": {name: val}, "range": float}``
    """
    if azimuths is None:
        azimuths = [i * (180.0 / n_steps) for i in range(n_steps)]

    results = []
    for az in azimuths:
        d = compute_distality(
            well_list,
            azimuth_deg=az,
            output_data=None,
            assign_region=False,
        )
        vals = list(d.values())
        results.append({
            "azimuth": az,
            "distalities": d,
            "range": max(vals) - min(vals) if vals else 0.0,
        })

    return results


def best_transport_direction(
    well_list,
    n_steps: int = 36,
) -> Tuple[float, List[Dict]]:
    """Find the transport direction that maximises distality spread.

    The direction with the greatest range of projected positions is
    the one that best separates proximal from distal wells.

    Parameters
    ----------
    well_list : WellList
    n_steps : int
        Angular resolution.

    Returns
    -------
    (best_azimuth, all_results)
    """
    results = sweep_transport(well_list, n_steps=n_steps)
    best = max(results, key=lambda r: r["range"])
    return best["azimuth"], results
