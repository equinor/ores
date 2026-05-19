"""
weco.seistiles_constraint — Seismic Tiles correlation constraint
=================================================================

Honour piecewise-planar seismic reflectors ("Seismic Tiles") during
well-to-well correlation.  Each tile carries **dip**, **azimuth**,
and **amplitude/frequency** attributes at a spatial location.
The constraint penalises marker ties whose implied inter-well
geometry contradicts the local seismic tile dip and azimuth, similar
to how the distality cost (``ccf_distal``) penalises geologically
inconsistent facies transitions.

Algorithm
---------
For each candidate marker tie ``(i_a, i_b)`` connecting well A
(depth ``z_a``) to well B (depth ``z_b``):

1. **Tile lookup** — find the tile closest to each well at the
   marker depth (spatial + depth nearest-neighbour).

2. **Dip consistency** — the expected depth shift between wells
   is derived from the tile's dip (``θ``) and the azimuth (``φ``):

   .. math::

       Δz_{expected} = \\|\\mathbf{d}_{AB}\\| \\, \\tan(θ) \\, \\cos(φ - α_{AB})

   where ``d_AB`` is the horizontal inter-well vector,
   ``α_AB`` is its azimuth, ``θ`` is the tile dip and ``φ``
   is the tile azimuth-of-dip.

   The penalty is the squared normalised deviation:

   .. math::

       c_{dip} = w_{dip} \\left(\\frac{Δz_{actual} - Δz_{expected}}{σ_{dip}}\\right)^2

3. **Azimuth consistency** — if tiles at both wells have
   azimuth data, a penalty for angular mismatch is added:

   .. math::

       c_{az} = w_{az} \\left(\\frac{Δφ}{σ_{az}}\\right)^2

   where ``Δφ`` is the angular difference (wrapping around 360°).

4. **Amplitude similarity** (optional) — penalises ties where
   the tile amplitudes differ significantly:

   .. math::

       c_{amp} = w_{amp} \\left(\\frac{A_a - A_b}{σ_{amp}}\\right)^2

The total seismic-tile penalty for cell ``(i, j)`` is:

    ``penalty[i, j] = c_dip + c_az + c_amp``

This is added to the base DTW cost matrix.

Data Format
-----------
Seismic tiles are loaded from a **CSV** file::

    x,y,z,dip,azimuth,amplitude,frequency
    460100,6780200,1500.0,5.2,135.0,0.85,25
    460100,6780200,1520.0,4.8,138.0,0.82,25
    ...

Or from a **JSON** array of tile objects (as produced by SeisTiles
export tools).

Usage
-----
::

    from weco.seistiles_constraint import SeisTilesConstraint

    sc = SeisTilesConstraint.from_csv("tiles.csv")
    penalty = sc.build_cost_matrix_modifier(
        "Well_A", "Well_B",
        well_positions, depths_a, depths_b
    )
    cost_matrix += penalty

See Also
--------
* ``weco.seismic_constraint`` — simpler horizon-pick based penalty.
* ``src/ccf_distal.cpp`` — C++ distality/facies cost (similar principle).
* Skjæveland & Torset (2023), *Geophysics* 88(3) — SeisTiles format spec.
* https://www.seistiles.com/

Reference
---------
The Seismic Tiles concept was developed by Equinor and is described in:

    Øyvind Skjæveland and Sondre Torset, "Seismic Tiles, a data format
    to facilitate analytics on seismic reflectors", Geophysics, Vol. 88,
    No. 3, 2023.

The SeisTiles consortium (2024–) is hosted by Norsk Regnesentral,
sponsored by Equinor, Aker BP, Harbour Energy, and OMV.
"""

from __future__ import annotations

import csv
import json
import logging
import math
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
#  Data model
# ═══════════════════════════════════════════════════════════════════════════

class SeismicTile:
    """
    A single piecewise-planar seismic reflector segment.

    Attributes
    ----------
    x, y, z : float
        Tile centre position (easting, northing, depth / TWT).
    dip : float
        Dip angle in degrees (0 = horizontal, 90 = vertical).
    azimuth : float
        Azimuth of maximum dip in degrees clockwise from north
        (0 = north, 90 = east, 180 = south, 270 = west).
    amplitude : float
        Seismic amplitude (optional, default 0).
    frequency : float
        Dominant frequency in Hz (optional, default 0).
    """

    __slots__ = ("x", "y", "z", "dip", "azimuth", "amplitude", "frequency")

    def __init__(
        self,
        x: float,
        y: float,
        z: float,
        dip: float = 0.0,
        azimuth: float = 0.0,
        amplitude: float = 0.0,
        frequency: float = 0.0,
    ):
        self.x = float(x)
        self.y = float(y)
        self.z = float(z)
        self.dip = float(dip)
        self.azimuth = float(azimuth)
        self.amplitude = float(amplitude)
        self.frequency = float(frequency)

    def __repr__(self) -> str:
        return (
            f"SeismicTile(x={self.x}, y={self.y}, z={self.z}, "
            f"dip={self.dip}°, az={self.azimuth}°, amp={self.amplitude})"
        )


class SeismicTileSet:
    """
    A collection of seismic tiles, indexed for fast spatial lookup.

    Tiles are stored in a flat list and indexed using a simple grid
    (binned by (x, y) for fast nearest-neighbour lookup in 2-D,
    then by depth within each bin).
    """

    def __init__(self, tiles: Optional[List[SeismicTile]] = None):
        self.tiles: List[SeismicTile] = tiles or []
        self._grid: Dict[Tuple[int, int], List[SeismicTile]] = {}
        self._bin_size: float = 100.0  # metres
        if self.tiles:
            self._build_index()

    # ── I/O ───────────────────────────────────────────────────────────

    @classmethod
    def from_csv(cls, path: str) -> "SeismicTileSet":
        """
        Load tiles from CSV.

        Expected columns (case-insensitive):
        ``x, y, z, dip, azimuth, amplitude, frequency``

        Only ``x, y, z`` are required; other columns default to 0.
        """
        tiles: List[SeismicTile] = []
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            # Normalise header names to lowercase
            if reader.fieldnames is None:
                return cls([])
            header_map = {h.strip().lower(): h for h in reader.fieldnames}
            for row in reader:
                lower = {k.strip().lower(): v for k, v in row.items()}
                tiles.append(SeismicTile(
                    x=float(lower.get("x", 0)),
                    y=float(lower.get("y", 0)),
                    z=float(lower.get("z", 0)),
                    dip=float(lower.get("dip", 0)),
                    azimuth=float(lower.get("azimuth", 0)),
                    amplitude=float(lower.get("amplitude", 0)),
                    frequency=float(lower.get("frequency", 0)),
                ))
        logger.info("Loaded %d seismic tiles from %s", len(tiles), path)
        return cls(tiles)

    @classmethod
    def from_json(cls, path: str) -> "SeismicTileSet":
        """
        Load tiles from a JSON array::

            [{"x": 460100, "y": 6780200, "z": 1500, "dip": 5.2, ...}, ...]
        """
        with open(path) as f:
            data = json.load(f)
        tiles = [
            SeismicTile(
                x=d.get("x", 0),
                y=d.get("y", 0),
                z=d.get("z", 0),
                dip=d.get("dip", 0),
                azimuth=d.get("azimuth", 0),
                amplitude=d.get("amplitude", 0),
                frequency=d.get("frequency", 0),
            )
            for d in data
        ]
        logger.info("Loaded %d seismic tiles from %s", len(tiles), path)
        return cls(tiles)

    def to_csv(self, path: str) -> None:
        """Export tiles to CSV."""
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["x", "y", "z", "dip", "azimuth",
                             "amplitude", "frequency"])
            for t in self.tiles:
                writer.writerow([t.x, t.y, t.z, t.dip, t.azimuth,
                                 t.amplitude, t.frequency])

    # ── Indexing ──────────────────────────────────────────────────────

    def _bin_key(self, x: float, y: float) -> Tuple[int, int]:
        return (int(x // self._bin_size), int(y // self._bin_size))

    def _build_index(self) -> None:
        """Build spatial grid index from tiles."""
        self._grid.clear()
        for t in self.tiles:
            key = self._bin_key(t.x, t.y)
            self._grid.setdefault(key, []).append(t)

    def set_bin_size(self, size: float) -> None:
        """Change grid bin size and rebuild index."""
        self._bin_size = max(size, 1.0)
        self._build_index()

    # ── Lookup ────────────────────────────────────────────────────────

    def find_nearest(
        self,
        x: float,
        y: float,
        z: float,
        max_horizontal_dist: float = 500.0,
        max_vertical_dist: float = 50.0,
    ) -> Optional[SeismicTile]:
        """
        Find the nearest tile to (x, y, z).

        Search scans grid bins within ``max_horizontal_dist`` and then
        filters by ``max_vertical_dist``.  Returns None if no tile is
        found within the search radius.
        """
        bx, by = self._bin_key(x, y)
        n_bins = int(math.ceil(max_horizontal_dist / self._bin_size)) + 1

        best: Optional[SeismicTile] = None
        best_dist = float("inf")

        for dx in range(-n_bins, n_bins + 1):
            for dy in range(-n_bins, n_bins + 1):
                key = (bx + dx, by + dy)
                for t in self._grid.get(key, []):
                    hdist = math.hypot(t.x - x, t.y - y)
                    if hdist > max_horizontal_dist:
                        continue
                    vdist = abs(t.z - z)
                    if vdist > max_vertical_dist:
                        continue
                    dist = math.sqrt(hdist ** 2 + vdist ** 2)
                    if dist < best_dist:
                        best_dist = dist
                        best = t

        return best

    def find_tiles_near_well(
        self,
        well_x: float,
        well_y: float,
        depths: np.ndarray,
        max_horizontal_dist: float = 500.0,
        max_vertical_dist: float = 50.0,
    ) -> List[Optional[SeismicTile]]:
        """
        For each depth in ``depths``, find the nearest tile.

        Returns a list parallel to ``depths`` (None where no tile found).
        """
        return [
            self.find_nearest(well_x, well_y, float(z),
                              max_horizontal_dist, max_vertical_dist)
            for z in depths
        ]


# ═══════════════════════════════════════════════════════════════════════════
#  Geometry helpers
# ═══════════════════════════════════════════════════════════════════════════

def _deg2rad(deg: float) -> float:
    return deg * math.pi / 180.0


def _angular_diff(a1: float, a2: float) -> float:
    """Smallest angular difference in degrees, range [0, 180]."""
    d = abs(a1 - a2) % 360.0
    return d if d <= 180.0 else 360.0 - d


def _expected_dz(
    dx: float,
    dy: float,
    tile_dip: float,
    tile_azimuth: float,
) -> float:
    """
    Expected depth shift between two points given tile dip/azimuth.

    Parameters
    ----------
    dx, dy : float
        Horizontal offset from well A to well B (easting, northing).
    tile_dip : float
        Dip angle in degrees.
    tile_azimuth : float
        Azimuth of maximum dip in degrees from north.

    Returns
    -------
    float
        Expected depth change (positive = B is deeper).

    Notes
    -----
    The dip direction unit vector in the horizontal plane is
    ``(sin(azimuth), cos(azimuth))``.  The projection of the
    inter-well vector onto this direction gives the lateral distance
    along dip, and ``tan(dip)`` converts it to vertical offset:

    .. math::

        Δz = (dx \\sin φ + dy \\cos φ) \\tan θ
    """
    phi = _deg2rad(tile_azimuth)
    theta = _deg2rad(tile_dip)
    # Project inter-well vector onto dip direction
    along_dip = dx * math.sin(phi) + dy * math.cos(phi)
    return along_dip * math.tan(theta)


# ═══════════════════════════════════════════════════════════════════════════
#  Constraint
# ═══════════════════════════════════════════════════════════════════════════

class SeisTilesConstraint:
    """
    DTW cost penalty honouring seismic tile dip, azimuth & amplitude.

    This is analogous to the distality/facies cost in ``ccf_distal.cpp``
    but uses seismic tile geometry instead of sedimentological regions.

    Parameters
    ----------
    tile_set : SeismicTileSet
        The seismic tiles to honour.
    dip_weight : float
        Weight for the dip-consistency penalty (default 1.0).
    dip_sigma : float
        Normalisation depth-error in metres (default 10.0).
    azimuth_weight : float
        Weight for the azimuth-consistency penalty (default 0.5).
    azimuth_sigma : float
        Normalisation angle difference in degrees (default 30.0).
    amplitude_weight : float
        Weight for the amplitude-similarity penalty (default 0.3).
    amplitude_sigma : float
        Normalisation amplitude difference (default 0.2).
    max_horizontal_dist : float
        Maximum horizontal distance for tile lookup (default 500 m).
    max_vertical_dist : float
        Maximum vertical distance for tile lookup (default 50 m).
    """

    def __init__(
        self,
        tile_set: SeismicTileSet,
        dip_weight: float = 1.0,
        dip_sigma: float = 10.0,
        azimuth_weight: float = 0.5,
        azimuth_sigma: float = 30.0,
        amplitude_weight: float = 0.3,
        amplitude_sigma: float = 0.2,
        max_horizontal_dist: float = 500.0,
        max_vertical_dist: float = 50.0,
    ):
        self.tile_set = tile_set
        self.dip_weight = dip_weight
        self.dip_sigma = max(dip_sigma, 1e-9)
        self.azimuth_weight = azimuth_weight
        self.azimuth_sigma = max(azimuth_sigma, 1e-9)
        self.amplitude_weight = amplitude_weight
        self.amplitude_sigma = max(amplitude_sigma, 1e-9)
        self.max_horizontal_dist = max_horizontal_dist
        self.max_vertical_dist = max_vertical_dist

    # ── Factory methods ───────────────────────────────────────────────

    @classmethod
    def from_csv(
        cls,
        path: str,
        **kwargs,
    ) -> "SeisTilesConstraint":
        """Create constraint from a CSV tile file."""
        return cls(SeismicTileSet.from_csv(path), **kwargs)

    @classmethod
    def from_json(
        cls,
        path: str,
        **kwargs,
    ) -> "SeisTilesConstraint":
        """Create constraint from a JSON tile file."""
        return cls(SeismicTileSet.from_json(path), **kwargs)

    # ── Per-cell penalties ────────────────────────────────────────────

    def _dip_penalty(
        self,
        tile: SeismicTile,
        dx: float,
        dy: float,
        dz_actual: float,
    ) -> float:
        """
        Dip-consistency penalty.

        Compares actual depth shift between wells with the expected
        shift implied by the tile dip and azimuth.
        """
        dz_expected = _expected_dz(dx, dy, tile.dip, tile.azimuth)
        deviation = dz_actual - dz_expected
        return self.dip_weight * (deviation / self.dip_sigma) ** 2

    def _azimuth_penalty(
        self,
        tile_a: Optional[SeismicTile],
        tile_b: Optional[SeismicTile],
    ) -> float:
        """
        Azimuth consistency between tiles at well A and well B.

        If reflectors are continuous, tiles at both wells should
        have similar azimuth-of-dip.
        """
        if tile_a is None or tile_b is None:
            return 0.0
        delta = _angular_diff(tile_a.azimuth, tile_b.azimuth)
        return self.azimuth_weight * (delta / self.azimuth_sigma) ** 2

    def _amplitude_penalty(
        self,
        tile_a: Optional[SeismicTile],
        tile_b: Optional[SeismicTile],
    ) -> float:
        """
        Amplitude similarity between tiles at well A and well B.

        Matched reflectors should have comparable amplitude.
        """
        if tile_a is None or tile_b is None:
            return 0.0
        delta = abs(tile_a.amplitude - tile_b.amplitude)
        return self.amplitude_weight * (delta / self.amplitude_sigma) ** 2

    # ── Cost matrix ───────────────────────────────────────────────────

    def build_cost_matrix_modifier(
        self,
        well_a_name: str,
        well_b_name: str,
        well_positions: Dict[str, Tuple[float, float]],
        depths_a: np.ndarray,
        depths_b: np.ndarray,
    ) -> np.ndarray:
        """
        Build an additive cost matrix honouring seismic tiles.

        Parameters
        ----------
        well_a_name, well_b_name : str
            Well identifiers.
        well_positions : dict
            ``{well_name: (x, y)}``.
        depths_a, depths_b : ndarray
            Marker depths for each well.

        Returns
        -------
        ndarray, shape (n_a, n_b)
            Penalty to add to the base DTW cost matrix.
        """
        n_a, n_b = len(depths_a), len(depths_b)
        penalty = np.zeros((n_a, n_b), dtype=np.float64)

        pos_a = well_positions.get(well_a_name)
        pos_b = well_positions.get(well_b_name)
        if pos_a is None or pos_b is None:
            logger.warning("Missing well position for %s or %s",
                           well_a_name, well_b_name)
            return penalty

        ax, ay = pos_a
        bx, by = pos_b
        dx = bx - ax
        dy = by - ay

        # Pre-fetch tiles for both wells
        tiles_a = self.tile_set.find_tiles_near_well(
            ax, ay, depths_a,
            self.max_horizontal_dist, self.max_vertical_dist,
        )
        tiles_b = self.tile_set.find_tiles_near_well(
            bx, by, depths_b,
            self.max_horizontal_dist, self.max_vertical_dist,
        )

        for i in range(n_a):
            ta = tiles_a[i]
            za = float(depths_a[i])
            for j in range(n_b):
                tb = tiles_b[j]
                zb = float(depths_b[j])
                dz_actual = zb - za

                # --- Dip penalty (use whichever tile is available) ---
                dip_cost = 0.0
                if ta is not None:
                    dip_cost += self._dip_penalty(ta, dx, dy, dz_actual)
                if tb is not None:
                    # Reverse direction (B→A)
                    dip_cost += self._dip_penalty(tb, -dx, -dy, -dz_actual)
                if ta is not None and tb is not None:
                    dip_cost /= 2.0  # average if both available

                # --- Azimuth penalty ---
                az_cost = self._azimuth_penalty(ta, tb)

                # --- Amplitude penalty ---
                amp_cost = self._amplitude_penalty(ta, tb)

                penalty[i, j] = dip_cost + az_cost + amp_cost

        return penalty

    def compute_penalty_single(
        self,
        well_x: float,
        well_y: float,
        well_z: float,
        other_x: float,
        other_y: float,
        other_z: float,
    ) -> float:
        """
        Compute total seismic-tile penalty for a single marker tie.

        Convenience method for point queries.
        """
        dx = other_x - well_x
        dy = other_y - well_y
        dz_actual = other_z - well_z

        tile = self.tile_set.find_nearest(
            well_x, well_y, well_z,
            self.max_horizontal_dist, self.max_vertical_dist,
        )
        if tile is None:
            return 0.0
        return self._dip_penalty(tile, dx, dy, dz_actual)

    # ── Summary statistics ────────────────────────────────────────────

    def coverage_report(
        self,
        well_positions: Dict[str, Tuple[float, float]],
        well_depths: Dict[str, np.ndarray],
    ) -> Dict[str, Dict[str, float]]:
        """
        Report tile coverage for each well.

        Returns
        -------
        dict
            ``{well_name: {"total_markers": N, "covered": M, "coverage_pct": %}}``
        """
        report = {}
        for name, (wx, wy) in well_positions.items():
            depths = well_depths.get(name, np.array([]))
            tiles = self.tile_set.find_tiles_near_well(
                wx, wy, depths,
                self.max_horizontal_dist, self.max_vertical_dist,
            )
            covered = sum(1 for t in tiles if t is not None)
            total = len(depths)
            report[name] = {
                "total_markers": total,
                "covered": covered,
                "coverage_pct": 100.0 * covered / max(total, 1),
            }
        return report
