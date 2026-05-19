"""
Tests for weco.seismic_constraint — Seismic-guided correlation.
================================================================

Tests SeismicHorizonPicks loading and SeismicConstraint cost penalty
computation using synthetic horizon picks.
"""

from __future__ import annotations

import csv
import os
import tempfile

import numpy as np
import pytest

from weco.seismic_constraint import (
    SeismicHorizonPicks,
    SeismicConstraint,
    create_seismic_cost_function,
)


# ═══════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def simple_picks():
    """Two horizons, two wells."""
    return SeismicHorizonPicks({
        "Top_Sand": {"Well_A": 1000.0, "Well_B": 1020.0},
        "Top_Shale": {"Well_A": 1050.0, "Well_B": 1065.0},
    })


@pytest.fixture
def csv_file():
    """Write a temporary CSV with horizon picks."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, newline=""
    ) as f:
        writer = csv.writer(f)
        writer.writerow(["horizon", "well", "depth"])
        writer.writerow(["H1", "W1", "500.0"])
        writer.writerow(["H1", "W2", "510.0"])
        writer.writerow(["H2", "W1", "600.0"])
        writer.writerow(["H2", "W2", "620.0"])
        path = f.name
    yield path
    os.unlink(path)


# ═══════════════════════════════════════════════════════════════════════════
# SeismicHorizonPicks
# ═══════════════════════════════════════════════════════════════════════════

class TestSeismicHorizonPicks:
    def test_horizon_names(self, simple_picks):
        assert sorted(simple_picks.horizon_names) == ["Top_Sand", "Top_Shale"]

    def test_get_pick_exists(self, simple_picks):
        assert simple_picks.get_pick("Top_Sand", "Well_A") == 1000.0

    def test_get_pick_missing_well(self, simple_picks):
        assert simple_picks.get_pick("Top_Sand", "Well_C") is None

    def test_get_pick_missing_horizon(self, simple_picks):
        assert simple_picks.get_pick("NoSuchHorizon", "Well_A") is None

    def test_wells_for_horizon(self, simple_picks):
        wells = simple_picks.wells_for_horizon("Top_Sand")
        assert sorted(wells) == ["Well_A", "Well_B"]

    def test_wells_for_missing_horizon(self, simple_picks):
        wells = simple_picks.wells_for_horizon("NoSuchHorizon")
        assert wells == []

    def test_from_csv(self, csv_file):
        picks = SeismicHorizonPicks.from_csv(csv_file)
        assert sorted(picks.horizon_names) == ["H1", "H2"]
        assert picks.get_pick("H1", "W1") == 500.0
        assert picks.get_pick("H2", "W2") == 620.0

    def test_from_csv_wells(self, csv_file):
        picks = SeismicHorizonPicks.from_csv(csv_file)
        assert sorted(picks.wells_for_horizon("H1")) == ["W1", "W2"]

    def test_empty_picks(self):
        picks = SeismicHorizonPicks({})
        assert picks.horizon_names == []
        assert picks.get_pick("H", "W") is None


# ═══════════════════════════════════════════════════════════════════════════
# SeismicConstraint — Penalty computation
# ═══════════════════════════════════════════════════════════════════════════

class TestSeismicConstraint:
    def test_zero_penalty_at_pick_depth(self, simple_picks):
        """Marker exactly at horizon depth → zero penalty."""
        sc = SeismicConstraint(simple_picks, weight=1.0, sigma=5.0,
                               tolerance=0.0)
        p = sc.compute_penalty("Well_A", 1000.0)
        assert p == pytest.approx(0.0)

    def test_zero_penalty_within_tolerance(self, simple_picks):
        """Marker within tolerance of horizon → zero penalty."""
        sc = SeismicConstraint(simple_picks, weight=1.0, sigma=5.0,
                               tolerance=2.0)
        p = sc.compute_penalty("Well_A", 1001.5)
        assert p == pytest.approx(0.0)

    def test_nonzero_penalty_beyond_tolerance(self, simple_picks):
        """Marker beyond tolerance → positive penalty."""
        sc = SeismicConstraint(simple_picks, weight=1.0, sigma=5.0,
                               tolerance=0.0)
        p = sc.compute_penalty("Well_A", 1010.0)
        assert p > 0.0

    def test_penalty_increases_with_deviation(self, simple_picks):
        """Larger deviation → larger penalty."""
        sc = SeismicConstraint(simple_picks, weight=1.0, sigma=5.0)
        p_small = sc.compute_penalty("Well_A", 1005.0)
        p_large = sc.compute_penalty("Well_A", 1020.0)
        assert p_large > p_small

    def test_penalty_scales_with_weight(self, simple_picks):
        """Higher weight → higher penalty for same deviation."""
        sc_low = SeismicConstraint(simple_picks, weight=1.0, sigma=5.0)
        sc_high = SeismicConstraint(simple_picks, weight=3.0, sigma=5.0)
        p_low = sc_low.compute_penalty("Well_A", 1010.0)
        p_high = sc_high.compute_penalty("Well_A", 1010.0)
        assert p_high > p_low

    def test_penalty_scales_with_sigma(self, simple_picks):
        """Smaller sigma → larger penalty for same deviation."""
        sc_small = SeismicConstraint(simple_picks, weight=1.0, sigma=2.0)
        sc_large = SeismicConstraint(simple_picks, weight=1.0, sigma=10.0)
        p_small_sigma = sc_small.compute_penalty("Well_A", 1010.0)
        p_large_sigma = sc_large.compute_penalty("Well_A", 1010.0)
        assert p_small_sigma > p_large_sigma

    def test_penalty_quadratic(self, simple_picks):
        """Penalty should be quadratic: weight × ((dev - tol) / sigma)^2."""
        sc = SeismicConstraint(simple_picks, weight=2.0, sigma=5.0,
                               tolerance=0.0)
        # At depth 1010 for Well_A (pick at 1000), deviation = 10
        # But there's also Top_Shale at 1050, deviation = 40
        # Should take minimum → nearest horizon penalty
        expected = 2.0 * (10.0 / 5.0) ** 2
        p = sc.compute_penalty("Well_A", 1010.0)
        assert p == pytest.approx(expected)

    def test_no_penalty_for_unknown_well(self, simple_picks):
        """Well without any horizon picks → zero penalty."""
        sc = SeismicConstraint(simple_picks, weight=1.0, sigma=5.0)
        p = sc.compute_penalty("Unknown_Well", 1000.0)
        assert p == pytest.approx(0.0)

    def test_nearest_horizon_selected(self, simple_picks):
        """Penalty should use the nearest horizon, not a far one."""
        sc = SeismicConstraint(simple_picks, weight=1.0, sigma=5.0,
                               tolerance=0.0)
        # Well_A has picks at 1000 and 1050
        # At depth 1048, nearest is Top_Shale (1050), dev=2
        p = sc.compute_penalty("Well_A", 1048.0)
        expected = 1.0 * (2.0 / 5.0) ** 2
        assert p == pytest.approx(expected)


# ═══════════════════════════════════════════════════════════════════════════
# Cost matrix modifier
# ═══════════════════════════════════════════════════════════════════════════

class TestCostMatrixModifier:
    def test_matrix_shape(self, simple_picks):
        sc = SeismicConstraint(simple_picks, weight=1.0, sigma=5.0)
        depths_a = np.linspace(990, 1060, 15)
        depths_b = np.linspace(1010, 1080, 12)
        penalty = sc.build_cost_matrix_modifier(
            "Well_A", "Well_B", depths_a, depths_b
        )
        assert penalty.shape == (15, 12)

    def test_matrix_non_negative(self, simple_picks):
        sc = SeismicConstraint(simple_picks, weight=1.0, sigma=5.0)
        depths_a = np.linspace(990, 1060, 10)
        depths_b = np.linspace(1010, 1080, 10)
        penalty = sc.build_cost_matrix_modifier(
            "Well_A", "Well_B", depths_a, depths_b
        )
        assert np.all(penalty >= 0)

    def test_matrix_zero_at_pick_intersection(self, simple_picks):
        """Cell where both wells are at horizon picks → zero penalty."""
        sc = SeismicConstraint(simple_picks, weight=1.0, sigma=5.0,
                               tolerance=0.0)
        depths_a = np.array([1000.0])  # exactly at Top_Sand
        depths_b = np.array([1020.0])  # exactly at Top_Sand for Well_B
        penalty = sc.build_cost_matrix_modifier(
            "Well_A", "Well_B", depths_a, depths_b
        )
        assert penalty[0, 0] == pytest.approx(0.0)

    def test_matrix_additive(self, simple_picks):
        """Penalty should be sum of penalties for both wells."""
        sc = SeismicConstraint(simple_picks, weight=1.0, sigma=5.0,
                               tolerance=0.0)
        depths_a = np.array([1010.0])
        depths_b = np.array([1030.0])
        penalty = sc.build_cost_matrix_modifier(
            "Well_A", "Well_B", depths_a, depths_b
        )
        pa = sc.compute_penalty("Well_A", 1010.0)
        pb = sc.compute_penalty("Well_B", 1030.0)
        assert penalty[0, 0] == pytest.approx(pa + pb)

    def test_unknown_wells_zero_penalty(self):
        picks = SeismicHorizonPicks({"H": {"W1": 100.0}})
        sc = SeismicConstraint(picks, weight=1.0, sigma=5.0)
        depths = np.array([100.0, 110.0])
        penalty = sc.build_cost_matrix_modifier(
            "Unknown_A", "Unknown_B", depths, depths
        )
        np.testing.assert_array_equal(penalty, 0.0)


# ═══════════════════════════════════════════════════════════════════════════
# Factory function
# ═══════════════════════════════════════════════════════════════════════════

class TestFactory:
    def test_create_from_csv(self, csv_file):
        sc = create_seismic_cost_function(csv_file, weight=2.0, sigma=3.0)
        assert isinstance(sc, SeismicConstraint)
        assert sc.weight == 2.0
        assert sc.sigma == 3.0
        assert len(sc.horizon_picks.horizon_names) == 2

    def test_factory_penalty_works(self, csv_file):
        sc = create_seismic_cost_function(csv_file)
        p = sc.compute_penalty("W1", 500.0)
        assert p == pytest.approx(0.0)
