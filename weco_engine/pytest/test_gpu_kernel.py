"""
Tests for weco.gpu_kernel — GPU cost-matrix fill.
===================================================

Tests the NumPy backend (always available) and verifies the API contract
for CuPy/OpenCL backends (import-gated).
"""

from __future__ import annotations

import numpy as np
import pytest

from weco.gpu_kernel import gpu_cost_matrix_fill, _cost_matrix_numpy


# ═══════════════════════════════════════════════════════════════════════════
# NumPy backend
# ═══════════════════════════════════════════════════════════════════════════

class TestCostMatrixNumpy:
    """Test the CPU reference implementation."""

    def test_shape(self):
        d1 = np.array([1.0, 2.0, 3.0])
        d2 = np.array([4.0, 5.0])
        cost = _cost_matrix_numpy(d1, d2)
        assert cost.shape == (3, 2)

    def test_identical_data_zero_diagonal(self):
        d = np.array([10.0, 20.0, 30.0])
        cost = _cost_matrix_numpy(d, d)
        for i in range(3):
            assert cost[i, i] == pytest.approx(0.0)

    def test_squared_difference(self):
        d1 = np.array([0.0, 1.0])
        d2 = np.array([3.0, 5.0])
        cost = _cost_matrix_numpy(d1, d2)
        assert cost[0, 0] == pytest.approx(9.0)   # (0-3)^2
        assert cost[0, 1] == pytest.approx(25.0)  # (0-5)^2
        assert cost[1, 0] == pytest.approx(4.0)   # (1-3)^2
        assert cost[1, 1] == pytest.approx(16.0)  # (1-5)^2

    def test_non_negative(self):
        rng = np.random.default_rng(42)
        d1 = rng.normal(50, 10, 20)
        d2 = rng.normal(50, 10, 15)
        cost = _cost_matrix_numpy(d1, d2)
        finite = cost[np.isfinite(cost)]
        assert np.all(finite >= 0)

    def test_symmetric_square_matrix(self):
        """cost(d1,d2) should equal cost(d2,d1).T"""
        d1 = np.array([1.0, 2.0, 3.0])
        d2 = np.array([4.0, 5.0, 6.0])
        c12 = _cost_matrix_numpy(d1, d2)
        c21 = _cost_matrix_numpy(d2, d1)
        np.testing.assert_array_almost_equal(c12, c21.T)

    def test_band_width_constrains_cells(self):
        """Non-zero band_width should set far-off-diagonal cells to inf."""
        d1 = np.arange(20, dtype=float)
        d2 = np.arange(20, dtype=float)
        cost = _cost_matrix_numpy(d1, d2, band_width=3)
        # Corner cells should be inf (far from diagonal)
        assert np.isinf(cost[0, -1])
        assert np.isinf(cost[-1, 0])
        # Diagonal should be finite
        for i in range(20):
            assert np.isfinite(cost[i, i])

    def test_band_width_zero_is_full(self):
        """band_width=0 should produce no inf cells (full matrix)."""
        d1 = np.arange(10, dtype=float)
        d2 = np.arange(10, dtype=float)
        cost = _cost_matrix_numpy(d1, d2, band_width=0)
        assert not np.any(np.isinf(cost))

    def test_single_element(self):
        d1 = np.array([5.0])
        d2 = np.array([8.0])
        cost = _cost_matrix_numpy(d1, d2)
        assert cost.shape == (1, 1)
        assert cost[0, 0] == pytest.approx(9.0)


# ═══════════════════════════════════════════════════════════════════════════
# Public API: gpu_cost_matrix_fill
# ═══════════════════════════════════════════════════════════════════════════

class TestGpuCostMatrixFill:
    """Test the public interface with auto/numpy backend."""

    def test_auto_fallback_to_numpy(self):
        d1 = np.array([1.0, 2.0, 3.0])
        d2 = np.array([4.0, 5.0])
        cost = gpu_cost_matrix_fill(d1, d2, backend="auto")
        assert cost.shape == (3, 2)

    def test_numpy_backend_explicit(self):
        d1 = np.array([10.0, 20.0])
        d2 = np.array([10.0, 20.0])
        cost = gpu_cost_matrix_fill(d1, d2, backend="numpy")
        assert cost[0, 0] == pytest.approx(0.0)
        assert cost[1, 1] == pytest.approx(0.0)

    def test_unknown_backend_raises(self):
        d1 = np.array([1.0])
        d2 = np.array([1.0])
        with pytest.raises(ValueError, match="Unknown backend"):
            gpu_cost_matrix_fill(d1, d2, backend="nonexistent")

    def test_band_width_passed_through(self):
        d1 = np.arange(20, dtype=float)
        d2 = np.arange(20, dtype=float)
        cost = gpu_cost_matrix_fill(d1, d2, band_width=3, backend="numpy")
        assert np.isinf(cost[0, -1])

    def test_large_matrix_performance(self):
        """Should handle 500x500 without error."""
        rng = np.random.default_rng(42)
        d1 = rng.normal(0, 1, 500)
        d2 = rng.normal(0, 1, 500)
        cost = gpu_cost_matrix_fill(d1, d2, backend="numpy")
        assert cost.shape == (500, 500)
        assert np.all(cost >= 0)

    def test_cupy_backend_import_error(self):
        """If CuPy is not installed, auto should still work (falls back)."""
        d1 = np.array([1.0, 2.0])
        d2 = np.array([3.0, 4.0])
        # auto should never raise even without GPU
        cost = gpu_cost_matrix_fill(d1, d2, backend="auto")
        assert cost.shape == (2, 2)
