"""
Tests for weco.geomodel_feedback — 3D structural model feedback loop.
=====================================================================

Tests residual computation, feedback weight generation, and iterative
convergence using synthetic thickness maps.
"""

from __future__ import annotations

import numpy as np
import pytest

from weco.geomodel_feedback import GeomodelFeedback


# ═══════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════

def _make_thickness_maps(n_layers=3, ny=10, nx=10, seed=42):
    """Synthetic thickness maps: smooth fields with a gentle trend."""
    rng = np.random.default_rng(seed)
    maps = {}
    for i in range(n_layers):
        base = 10.0 + i * 5.0
        maps[f"Layer_{i}"] = base + rng.normal(0, 1, (ny, nx))
    return maps


def _make_well_positions(n_wells=4, spacing=2.0):
    return {f"Well_{i}": (i * spacing, i * spacing) for i in range(n_wells)}


def _make_observed_thicknesses(n_wells=4, n_layers=3, seed=42):
    rng = np.random.default_rng(seed)
    obs = {}
    for i in range(n_wells):
        obs[f"Well_{i}"] = {}
        for j in range(n_layers):
            obs[f"Well_{i}"][f"Layer_{j}"] = 10.0 + j * 5.0 + rng.normal(0, 0.5)
    return obs


@pytest.fixture
def feedback():
    return GeomodelFeedback(
        thickness_maps=_make_thickness_maps(),
        well_positions=_make_well_positions(),
        observed_thicknesses=_make_observed_thicknesses(),
    )


# ═══════════════════════════════════════════════════════════════════════════
# Construction
# ═══════════════════════════════════════════════════════════════════════════

class TestConstruction:
    def test_attributes(self, feedback):
        assert len(feedback.thickness_maps) == 3
        assert len(feedback.well_positions) == 4
        assert len(feedback.observed_thicknesses) == 4

    def test_empty_inputs(self):
        fb = GeomodelFeedback({}, {}, {})
        assert fb.thickness_maps == {}


# ═══════════════════════════════════════════════════════════════════════════
# Residual computation
# ═══════════════════════════════════════════════════════════════════════════

class TestResiduals:
    def test_returns_dict(self, feedback):
        res = feedback.compute_residuals()
        assert isinstance(res, dict)

    def test_residuals_per_well(self, feedback):
        res = feedback.compute_residuals()
        # Should have entries for wells that appear in observed
        assert len(res) >= 1

    def test_residuals_per_layer(self, feedback):
        res = feedback.compute_residuals()
        for well, layers in res.items():
            assert isinstance(layers, dict)
            for layer, val in layers.items():
                assert isinstance(val, float)

    def test_zero_residual_when_model_matches(self):
        """If model thickness == observed, residual should be 0."""
        tmap = np.full((5, 5), 20.0)
        fb = GeomodelFeedback(
            thickness_maps={"L": tmap},
            well_positions={"W": (0.0, 0.0)},
            observed_thicknesses={"W": {"L": 20.0}},
        )
        res = fb.compute_residuals(grid_origin=(0, 0), grid_spacing=(1, 1))
        assert res["W"]["L"] == pytest.approx(0.0)

    def test_positive_residual_when_observed_thicker(self):
        """observed > modelled → positive residual."""
        tmap = np.full((5, 5), 10.0)
        fb = GeomodelFeedback(
            thickness_maps={"L": tmap},
            well_positions={"W": (0.0, 0.0)},
            observed_thicknesses={"W": {"L": 15.0}},
        )
        res = fb.compute_residuals()
        assert res["W"]["L"] == pytest.approx(5.0)

    def test_negative_residual_when_observed_thinner(self):
        """observed < modelled → negative residual."""
        tmap = np.full((5, 5), 20.0)
        fb = GeomodelFeedback(
            thickness_maps={"L": tmap},
            well_positions={"W": (0.0, 0.0)},
            observed_thicknesses={"W": {"L": 15.0}},
        )
        res = fb.compute_residuals()
        assert res["W"]["L"] == pytest.approx(-5.0)

    def test_missing_well_skipped(self):
        """Wells not in observed_thicknesses should be skipped."""
        tmap = np.full((5, 5), 10.0)
        fb = GeomodelFeedback(
            thickness_maps={"L": tmap},
            well_positions={"W1": (0, 0), "W2": (1, 1)},
            observed_thicknesses={"W1": {"L": 10.0}},
        )
        res = fb.compute_residuals()
        assert "W1" in res
        assert "W2" not in res

    def test_missing_layer_skipped(self):
        """Layers not in thickness_maps should be skipped."""
        tmap = np.full((5, 5), 10.0)
        fb = GeomodelFeedback(
            thickness_maps={"L": tmap},
            well_positions={"W": (0, 0)},
            observed_thicknesses={"W": {"L": 10.0, "M": 5.0}},
        )
        res = fb.compute_residuals()
        assert "L" in res["W"]
        assert "M" not in res["W"]

    def test_grid_coordinates(self):
        """Grid origin and spacing should affect which cell is sampled."""
        tmap = np.zeros((10, 10))
        tmap[5, 5] = 99.0  # only cell (5,5) has thickness
        fb = GeomodelFeedback(
            thickness_maps={"L": tmap},
            well_positions={"W": (50.0, 50.0)},
            observed_thicknesses={"W": {"L": 99.0}},
        )
        res = fb.compute_residuals(grid_origin=(0, 0), grid_spacing=(10, 10))
        assert res["W"]["L"] == pytest.approx(0.0)


# ═══════════════════════════════════════════════════════════════════════════
# Feedback weights
# ═══════════════════════════════════════════════════════════════════════════

class TestFeedbackWeights:
    def test_returns_dict(self, feedback):
        w = feedback.compute_feedback()
        assert isinstance(w, dict)

    def test_weight_per_layer(self, feedback):
        w = feedback.compute_feedback()
        for layer, val in w.items():
            assert isinstance(val, float)
            assert val >= 0.0

    def test_base_weight_when_perfect_match(self):
        """Zero residual → weight should equal base_weight."""
        tmap = np.full((5, 5), 20.0)
        fb = GeomodelFeedback(
            thickness_maps={"L": tmap},
            well_positions={"W": (0.0, 0.0)},
            observed_thicknesses={"W": {"L": 20.0}},
        )
        w = fb.compute_feedback(base_weight=1.0, sensitivity=2.0)
        assert w["L"] == pytest.approx(1.0)

    def test_higher_residual_higher_weight(self):
        """Larger mismatch → higher weight."""
        tmap = np.full((5, 5), 10.0)
        fb1 = GeomodelFeedback(
            thickness_maps={"L": tmap},
            well_positions={"W": (0, 0)},
            observed_thicknesses={"W": {"L": 11.0}},  # small mismatch
        )
        fb2 = GeomodelFeedback(
            thickness_maps={"L": tmap},
            well_positions={"W": (0, 0)},
            observed_thicknesses={"W": {"L": 20.0}},  # large mismatch
        )
        w1 = fb1.compute_feedback()["L"]
        w2 = fb2.compute_feedback()["L"]
        assert w2 > w1

    def test_sensitivity_scaling(self):
        """Higher sensitivity → larger weight difference."""
        tmap = np.full((5, 5), 10.0)
        fb = GeomodelFeedback(
            thickness_maps={"L": tmap},
            well_positions={"W": (0, 0)},
            observed_thicknesses={"W": {"L": 15.0}},
        )
        w_low = fb.compute_feedback(sensitivity=1.0)["L"]
        w_high = fb.compute_feedback(sensitivity=5.0)["L"]
        assert w_high > w_low


# ═══════════════════════════════════════════════════════════════════════════
# Iteration
# ═══════════════════════════════════════════════════════════════════════════

class TestIteration:
    def test_iterate_with_mock_functions(self, feedback):
        """Test the iteration loop with trivial mock functions."""
        call_count = {"run": 0, "build": 0}

        def mock_run(weights):
            call_count["run"] += 1
            obs = _make_observed_thicknesses()
            return "mock_res_file", obs

        def mock_build(res_file):
            call_count["build"] += 1
            return _make_thickness_maps()

        history = feedback.iterate(
            mock_run, mock_build,
            max_iterations=3,
            convergence_threshold=0.001,
        )
        assert len(history) >= 1
        assert len(history) <= 3
        assert call_count["run"] >= 1
        assert call_count["build"] >= 1

    def test_iterate_converges(self):
        """With matching thicknesses, should converge quickly."""
        tmap = np.full((5, 5), 20.0)
        fb = GeomodelFeedback(
            thickness_maps={"L": tmap},
            well_positions={"W": (0, 0)},
            observed_thicknesses={"W": {"L": 20.0}},
        )

        def run(w):
            return None, {"W": {"L": 20.0}}

        def build(rf):
            return {"L": np.full((5, 5), 20.0)}

        history = fb.iterate(run, build, max_iterations=5,
                             convergence_threshold=0.01)
        # Should converge in 1-2 iterations since perfect match
        assert len(history) <= 2
