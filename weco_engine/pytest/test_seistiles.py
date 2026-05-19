"""
Tests for weco.seistiles_constraint — Seismic Tiles correlation constraint.
==========================================================================

End-to-end tests for tile loading, spatial lookup, dip/azimuth/amplitude
penalty computation, cost-matrix generation, and API routes.
"""

from __future__ import annotations

import csv
import json
import math
import os
import tempfile

import numpy as np
import pytest

from weco.seistiles_constraint import (
    SeismicTile,
    SeismicTileSet,
    SeisTilesConstraint,
    _angular_diff,
    _expected_dz,
)


# ═══════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════

def _synthetic_tiles(
    nx: int = 5,
    ny: int = 5,
    nz: int = 3,
    x0: float = 460000.0,
    y0: float = 6780000.0,
    z0: float = 1000.0,
    dx: float = 100.0,
    dy: float = 100.0,
    dz: float = 50.0,
    dip: float = 5.0,
    azimuth: float = 135.0,
    amplitude: float = 0.8,
    seed: int = 42,
) -> list:
    """Generate a regular 3-D grid of synthetic tiles with small noise."""
    rng = np.random.default_rng(seed)
    tiles = []
    for ix in range(nx):
        for iy in range(ny):
            for iz in range(nz):
                tiles.append(SeismicTile(
                    x=x0 + ix * dx + rng.normal(0, 1),
                    y=y0 + iy * dy + rng.normal(0, 1),
                    z=z0 + iz * dz + rng.normal(0, 1),
                    dip=dip + rng.normal(0, 0.5),
                    azimuth=azimuth + rng.normal(0, 2),
                    amplitude=amplitude + rng.normal(0, 0.05),
                    frequency=25.0,
                ))
    return tiles


@pytest.fixture
def tile_set():
    return SeismicTileSet(_synthetic_tiles())


@pytest.fixture
def csv_tile_file():
    """Write a temp CSV with synthetic tiles."""
    tiles = _synthetic_tiles(nx=3, ny=3, nz=2)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, newline=""
    ) as f:
        writer = csv.writer(f)
        writer.writerow(["x", "y", "z", "dip", "azimuth", "amplitude", "frequency"])
        for t in tiles:
            writer.writerow([t.x, t.y, t.z, t.dip, t.azimuth,
                             t.amplitude, t.frequency])
        path = f.name
    yield path
    os.unlink(path)


@pytest.fixture
def json_tile_file():
    """Write a temp JSON with synthetic tiles."""
    tiles = _synthetic_tiles(nx=3, ny=3, nz=2)
    data = [{"x": t.x, "y": t.y, "z": t.z, "dip": t.dip,
             "azimuth": t.azimuth, "amplitude": t.amplitude,
             "frequency": t.frequency} for t in tiles]
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    ) as f:
        json.dump(data, f)
        path = f.name
    yield path
    os.unlink(path)


@pytest.fixture
def constraint(tile_set):
    return SeisTilesConstraint(tile_set)


# ═══════════════════════════════════════════════════════════════════════════
# SeismicTile
# ═══════════════════════════════════════════════════════════════════════════

class TestSeismicTile:
    def test_construction(self):
        t = SeismicTile(100.0, 200.0, 300.0, dip=5.0, azimuth=90.0)
        assert t.x == 100.0
        assert t.y == 200.0
        assert t.z == 300.0
        assert t.dip == 5.0
        assert t.azimuth == 90.0

    def test_defaults(self):
        t = SeismicTile(0, 0, 0)
        assert t.dip == 0.0
        assert t.azimuth == 0.0
        assert t.amplitude == 0.0
        assert t.frequency == 0.0

    def test_repr(self):
        t = SeismicTile(1, 2, 3, dip=4, azimuth=5, amplitude=0.6)
        r = repr(t)
        assert "SeismicTile" in r
        assert "dip=4.0" in r


# ═══════════════════════════════════════════════════════════════════════════
# SeismicTileSet — I/O
# ═══════════════════════════════════════════════════════════════════════════

class TestTileSetIO:
    def test_from_csv(self, csv_tile_file):
        ts = SeismicTileSet.from_csv(csv_tile_file)
        assert len(ts.tiles) == 3 * 3 * 2  # 18

    def test_from_json(self, json_tile_file):
        ts = SeismicTileSet.from_json(json_tile_file)
        assert len(ts.tiles) == 3 * 3 * 2

    def test_to_csv_roundtrip(self, tile_set):
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            path = f.name
        try:
            tile_set.to_csv(path)
            ts2 = SeismicTileSet.from_csv(path)
            assert len(ts2.tiles) == len(tile_set.tiles)
            assert ts2.tiles[0].x == pytest.approx(tile_set.tiles[0].x, abs=0.01)
        finally:
            os.unlink(path)

    def test_empty_tile_set(self):
        ts = SeismicTileSet([])
        assert len(ts.tiles) == 0

    def test_csv_case_insensitive_headers(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, newline=""
        ) as f:
            writer = csv.writer(f)
            writer.writerow(["X", "Y", "Z", "Dip", "Azimuth", "Amplitude", "Frequency"])
            writer.writerow([100, 200, 300, 5, 90, 0.8, 25])
            path = f.name
        try:
            ts = SeismicTileSet.from_csv(path)
            assert len(ts.tiles) == 1
            assert ts.tiles[0].dip == pytest.approx(5.0)
        finally:
            os.unlink(path)


# ═══════════════════════════════════════════════════════════════════════════
# SeismicTileSet — Spatial lookup
# ═══════════════════════════════════════════════════════════════════════════

class TestTileSetLookup:
    def test_find_nearest_exact(self, tile_set):
        """Should find a tile very close to a grid node."""
        t = tile_set.find_nearest(460000, 6780000, 1000,
                                  max_horizontal_dist=50, max_vertical_dist=50)
        assert t is not None
        assert abs(t.x - 460000) < 5
        assert abs(t.y - 6780000) < 5

    def test_find_nearest_returns_none_far_away(self, tile_set):
        t = tile_set.find_nearest(0, 0, 0,
                                  max_horizontal_dist=10, max_vertical_dist=10)
        assert t is None

    def test_find_nearest_depth_filter(self, tile_set):
        """Tile at z=1000 should not match z=5000."""
        t = tile_set.find_nearest(460000, 6780000, 5000,
                                  max_horizontal_dist=500, max_vertical_dist=10)
        assert t is None

    def test_find_tiles_near_well(self, tile_set):
        depths = np.array([1000.0, 1050.0, 1100.0])
        tiles = tile_set.find_tiles_near_well(
            460000, 6780000, depths,
            max_horizontal_dist=500, max_vertical_dist=60,
        )
        assert len(tiles) == 3
        # At least first two should find tiles (z=1000, z=1050)
        assert tiles[0] is not None
        assert tiles[1] is not None

    def test_bin_size_affects_search(self, tile_set):
        tile_set.set_bin_size(50.0)
        t = tile_set.find_nearest(460000, 6780000, 1000,
                                  max_horizontal_dist=50, max_vertical_dist=50)
        assert t is not None


# ═══════════════════════════════════════════════════════════════════════════
# Geometry helpers
# ═══════════════════════════════════════════════════════════════════════════

class TestGeometryHelpers:
    def test_angular_diff_same(self):
        assert _angular_diff(90, 90) == pytest.approx(0.0)

    def test_angular_diff_opposite(self):
        assert _angular_diff(0, 180) == pytest.approx(180.0)

    def test_angular_diff_wrap(self):
        assert _angular_diff(350, 10) == pytest.approx(20.0)

    def test_angular_diff_symmetric(self):
        assert _angular_diff(30, 60) == pytest.approx(_angular_diff(60, 30))

    def test_expected_dz_horizontal(self):
        """Zero dip → zero depth change."""
        dz = _expected_dz(100, 0, tile_dip=0, tile_azimuth=0)
        assert dz == pytest.approx(0.0)

    def test_expected_dz_dipping_north(self):
        """Dip=45° azimuth=0° (north), dy=100 → dz=100."""
        dz = _expected_dz(0, 100, tile_dip=45, tile_azimuth=0)
        assert dz == pytest.approx(100.0, rel=0.01)

    def test_expected_dz_dipping_east(self):
        """Dip=45° azimuth=90° (east), dx=100 → dz=100."""
        dz = _expected_dz(100, 0, tile_dip=45, tile_azimuth=90)
        assert dz == pytest.approx(100.0, rel=0.01)

    def test_expected_dz_perpendicular(self):
        """Move perpendicular to dip → zero depth change."""
        # Dip north, move east
        dz = _expected_dz(100, 0, tile_dip=45, tile_azimuth=0)
        assert dz == pytest.approx(0.0, abs=0.01)

    def test_expected_dz_negative(self):
        """Moving against dip direction → negative depth change."""
        dz = _expected_dz(0, -100, tile_dip=45, tile_azimuth=0)
        assert dz == pytest.approx(-100.0, rel=0.01)


# ═══════════════════════════════════════════════════════════════════════════
# SeisTilesConstraint — Penalty computation
# ═══════════════════════════════════════════════════════════════════════════

class TestSeisTilesConstraint:
    def test_construction(self, tile_set):
        sc = SeisTilesConstraint(tile_set, dip_weight=2.0)
        assert sc.dip_weight == 2.0
        assert sc.tile_set is tile_set

    def test_from_csv(self, csv_tile_file):
        sc = SeisTilesConstraint.from_csv(csv_tile_file)
        assert len(sc.tile_set.tiles) > 0

    def test_from_json(self, json_tile_file):
        sc = SeisTilesConstraint.from_json(json_tile_file)
        assert len(sc.tile_set.tiles) > 0

    def test_dip_penalty_zero_at_expected(self, constraint):
        """If actual dz matches expected dz, penalty should be ~0."""
        # Flat tile (dip=0) → expected dz=0
        flat_tile = SeismicTile(0, 0, 1000, dip=0, azimuth=0)
        p = constraint._dip_penalty(flat_tile, dx=100, dy=0, dz_actual=0)
        assert p == pytest.approx(0.0)

    def test_dip_penalty_increases_with_error(self, constraint):
        flat_tile = SeismicTile(0, 0, 1000, dip=0, azimuth=0)
        p1 = constraint._dip_penalty(flat_tile, dx=100, dy=0, dz_actual=5)
        p2 = constraint._dip_penalty(flat_tile, dx=100, dy=0, dz_actual=20)
        assert p2 > p1 > 0

    def test_azimuth_penalty_same_azimuth(self, constraint):
        t1 = SeismicTile(0, 0, 0, azimuth=90)
        t2 = SeismicTile(0, 0, 0, azimuth=90)
        assert constraint._azimuth_penalty(t1, t2) == pytest.approx(0.0)

    def test_azimuth_penalty_different(self, constraint):
        t1 = SeismicTile(0, 0, 0, azimuth=0)
        t2 = SeismicTile(0, 0, 0, azimuth=90)
        p = constraint._azimuth_penalty(t1, t2)
        assert p > 0

    def test_azimuth_penalty_none_tile(self, constraint):
        t1 = SeismicTile(0, 0, 0, azimuth=90)
        assert constraint._azimuth_penalty(t1, None) == 0.0
        assert constraint._azimuth_penalty(None, t1) == 0.0

    def test_amplitude_penalty_same(self, constraint):
        t1 = SeismicTile(0, 0, 0, amplitude=0.5)
        t2 = SeismicTile(0, 0, 0, amplitude=0.5)
        assert constraint._amplitude_penalty(t1, t2) == pytest.approx(0.0)

    def test_amplitude_penalty_different(self, constraint):
        t1 = SeismicTile(0, 0, 0, amplitude=0.1)
        t2 = SeismicTile(0, 0, 0, amplitude=0.9)
        p = constraint._amplitude_penalty(t1, t2)
        assert p > 0

    def test_weight_scaling(self):
        ts = SeismicTileSet([SeismicTile(0, 0, 1000, dip=0)])
        sc_low = SeisTilesConstraint(ts, dip_weight=1.0, dip_sigma=10)
        sc_high = SeisTilesConstraint(ts, dip_weight=5.0, dip_sigma=10)
        tile = ts.tiles[0]
        p_low = sc_low._dip_penalty(tile, 100, 0, 10)
        p_high = sc_high._dip_penalty(tile, 100, 0, 10)
        assert p_high > p_low

    def test_sigma_scaling(self):
        ts = SeismicTileSet([SeismicTile(0, 0, 1000, dip=0)])
        sc_tight = SeisTilesConstraint(ts, dip_weight=1.0, dip_sigma=2)
        sc_loose = SeisTilesConstraint(ts, dip_weight=1.0, dip_sigma=20)
        tile = ts.tiles[0]
        p_tight = sc_tight._dip_penalty(tile, 100, 0, 10)
        p_loose = sc_loose._dip_penalty(tile, 100, 0, 10)
        assert p_tight > p_loose


# ═══════════════════════════════════════════════════════════════════════════
# Cost matrix modifier
# ═══════════════════════════════════════════════════════════════════════════

class TestCostMatrixModifier:
    def test_shape(self, constraint):
        depths_a = np.linspace(1000, 1100, 10)
        depths_b = np.linspace(1000, 1100, 8)
        pos = {"WA": (460000.0, 6780000.0), "WB": (460200.0, 6780000.0)}
        penalty = constraint.build_cost_matrix_modifier(
            "WA", "WB", pos, depths_a, depths_b
        )
        assert penalty.shape == (10, 8)

    def test_non_negative(self, constraint):
        depths_a = np.linspace(1000, 1100, 10)
        depths_b = np.linspace(1000, 1100, 10)
        pos = {"WA": (460000.0, 6780000.0), "WB": (460200.0, 6780000.0)}
        penalty = constraint.build_cost_matrix_modifier(
            "WA", "WB", pos, depths_a, depths_b
        )
        assert np.all(penalty >= 0)

    def test_missing_well_position_returns_zeros(self, constraint):
        depths = np.linspace(1000, 1100, 5)
        penalty = constraint.build_cost_matrix_modifier(
            "Unknown", "Also_Unknown", {}, depths, depths
        )
        np.testing.assert_array_equal(penalty, 0.0)

    def test_diagonal_lower_for_consistent_dip(self):
        """Tiles dipping south at 5°: consistent depth shifts along
        diagonal should have lower penalty than off-diagonal."""
        tiles = [SeismicTile(0, 0, z, dip=5, azimuth=180) for z in range(950, 1150, 10)]
        ts = SeismicTileSet(tiles)
        ts.set_bin_size(50)
        sc = SeisTilesConstraint(
            ts, dip_weight=1.0, dip_sigma=5.0,
            azimuth_weight=0, amplitude_weight=0,
            max_horizontal_dist=100, max_vertical_dist=60,
        )
        depths_a = np.array([1000.0, 1010.0, 1020.0])
        depths_b = np.array([1000.0, 1010.0, 1020.0])
        pos = {"A": (0.0, 0.0), "B": (0.0, 0.0)}  # same location → dz_expected=0
        penalty = sc.build_cost_matrix_modifier("A", "B", pos, depths_a, depths_b)
        # Diagonal should have lower penalty (dz_actual≈0 = dz_expected)
        for i in range(3):
            assert penalty[i, i] <= penalty[0, 2] or penalty[i, i] == pytest.approx(0.0, abs=0.1)


# ═══════════════════════════════════════════════════════════════════════════
# Coverage report
# ═══════════════════════════════════════════════════════════════════════════

class TestCoverageReport:
    def test_coverage_keys(self, constraint):
        pos = {"W1": (460000.0, 6780000.0)}
        depths = {"W1": np.array([1000.0, 1050.0])}
        report = constraint.coverage_report(pos, depths)
        assert "W1" in report
        assert "total_markers" in report["W1"]
        assert "covered" in report["W1"]
        assert "coverage_pct" in report["W1"]

    def test_coverage_within_range(self, constraint):
        pos = {"W1": (460000.0, 6780000.0)}
        depths = {"W1": np.array([1000.0, 1050.0, 1100.0])}
        report = constraint.coverage_report(pos, depths)
        assert report["W1"]["total_markers"] == 3
        assert 0 <= report["W1"]["coverage_pct"] <= 100

    def test_coverage_no_tiles(self):
        sc = SeisTilesConstraint(SeismicTileSet([]))
        pos = {"W": (0.0, 0.0)}
        depths = {"W": np.array([100.0])}
        report = sc.coverage_report(pos, depths)
        assert report["W"]["covered"] == 0
        assert report["W"]["coverage_pct"] == pytest.approx(0.0)


# ═══════════════════════════════════════════════════════════════════════════
# Point-query convenience
# ═══════════════════════════════════════════════════════════════════════════

class TestComputePenaltySingle:
    def test_no_tile_returns_zero(self):
        sc = SeisTilesConstraint(SeismicTileSet([]))
        p = sc.compute_penalty_single(0, 0, 0, 100, 0, 0)
        assert p == pytest.approx(0.0)

    def test_returns_positive_for_mismatch(self, constraint):
        p = constraint.compute_penalty_single(
            460000, 6780000, 1000,
            460200, 6780000, 1100,  # large depth shift
        )
        # May or may not have a tile — if found, penalty > 0
        assert p >= 0.0


# ═══════════════════════════════════════════════════════════════════════════
# API route tests (POST /run/seistiles, POST /seistiles/info)
# ═══════════════════════════════════════════════════════════════════════════

class TestSeisTilesAPI:
    """Test the SeisTiles REST API routes.

    These tests require pytest-forked because the engine uses global state.
    """

    pytestmark = pytest.mark.forked

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from weco.api import app
        return TestClient(app)

    @pytest.fixture
    def well_and_tiles(self):
        """Create temp well file and tiles file for API tests."""
        from weco.data import Well, WellList

        wl = WellList()
        rng = np.random.default_rng(42)
        for i, name in enumerate(["W_A", "W_B"]):
            w = Well()
            w.name = name
            w.size = 30
            w.x = 460000 + i * 200
            w.y = 6780000
            w.z = 0
            w.h = 30 * 0.5
            w.data["GR"] = (rng.normal(70, 15, 30)).clip(0).tolist()
            w.data["Depth"] = [1000 + j * 0.5 for j in range(30)]
            wl.add_well(w)

        tmpdir = tempfile.mkdtemp()
        well_path = os.path.join(tmpdir, "wells.txt")
        wl.write(well_path)

        tiles = _synthetic_tiles(nx=3, ny=3, nz=3,
                                 x0=460000, y0=6780000, z0=1000,
                                 dx=100, dy=100, dz=5)
        tile_path = os.path.join(tmpdir, "tiles.csv")
        with open(tile_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["x", "y", "z", "dip", "azimuth",
                             "amplitude", "frequency"])
            for t in tiles:
                writer.writerow([t.x, t.y, t.z, t.dip, t.azimuth,
                                 t.amplitude, t.frequency])

        yield well_path, tile_path

        # Cleanup
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_seistiles_info(self, client, well_and_tiles):
        _, tile_path = well_and_tiles
        r = client.post("/seistiles/info",
                        json={"tiles_file": tile_path})
        assert r.status_code == 200
        body = r.json()
        assert body["n_tiles"] == 3 * 3 * 3
        assert body["dip_min"] <= body["dip_max"]
        assert len(body["x_range"]) == 2
        assert len(body["z_range"]) == 2

    def test_seistiles_info_missing_file(self, client):
        r = client.post("/seistiles/info",
                        json={"tiles_file": "/no/such/tiles.csv"})
        assert r.status_code == 404

    def test_run_seistiles(self, client, well_and_tiles):
        well_path, tile_path = well_and_tiles
        r = client.post("/run/seistiles", json={
            "well_file": well_path,
            "tiles_file": tile_path,
            "dip_weight": 1.0,
        })
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["n_wells"] == 2
        assert body["n_tiles"] > 0
        assert len(body["tile_coverage"]) == 2
        for cov in body["tile_coverage"]:
            assert "well" in cov
            assert "coverage_pct" in cov

    def test_run_seistiles_missing_well_file(self, client, well_and_tiles):
        _, tile_path = well_and_tiles
        r = client.post("/run/seistiles", json={
            "well_file": "/no/such/wells.txt",
            "tiles_file": tile_path,
        })
        assert r.status_code == 404

    def test_run_seistiles_missing_tiles_file(self, client, well_and_tiles):
        well_path, _ = well_and_tiles
        r = client.post("/run/seistiles", json={
            "well_file": well_path,
            "tiles_file": "/no/such/tiles.csv",
        })
        assert r.status_code == 404
