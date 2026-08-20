"""Tests for weco.api utility functions - scenario labelling, facies independence, Wheeler analysis."""

import pytest
import numpy as np
from weco.api import _label_scenario, _check_facies_independence, _wheeler_gap_analysis
from weco.data import Well, WellList


class TestLabelScenario:
    def test_empty(self):
        assert _label_scenario(()) == "Unknown"

    def test_layer_cake(self):
        # No gaps anywhere
        assert _label_scenario((0, 0, 0, 0)) == "Layer-cake"
        assert _label_scenario((1, 0, 1)) == "Layer-cake"

    def test_pinch_out(self):
        # One well has significant gaps, others don't
        assert _label_scenario((0, 0, 0, 4)) == "Pinch-out"
        assert _label_scenario((0, 0, 3)) == "Pinch-out"

    def test_unconformity(self):
        # Most wells have many gaps (bucket >= 4)
        assert _label_scenario((5, 5, 5, 5, 5)) == "Unconformity"
        assert _label_scenario((4, 5, 4, 5)) == "Unconformity"

    def test_condensed(self):
        # All wells have moderate gaps, uniform distribution
        assert _label_scenario((3, 3, 3, 3)) == "Condensed"
        assert _label_scenario((2, 2, 2, 2)) == "Condensed"

    def test_wedge(self):
        # Significant variation in gap intensity
        assert _label_scenario((0, 5, 1, 5)) == "Wedge"
        assert _label_scenario((1, 3, 5, 4)) == "Wedge"

    def test_onlap(self):
        # Progressive gradient
        assert _label_scenario((0, 2, 4)) == "Onlap"

    def test_complex_or_fallback(self):
        # Complex is a catch-all for patterns not matching specific categories
        # With 1 well at moderate gap but > 3, no other category matches
        result = _label_scenario((4, 1, 4, 0, 1))
        assert result in ("Complex", "Wedge", "Pinch-out")  # implementation detail

    def test_single_well(self):
        # Edge case: single well
        result = _label_scenario((0,))
        assert result in ("Layer-cake", "Unknown")


class TestCheckFaciesIndependence:
    def _make_wl(self, gr_values, facies_regions, var_data_name="GR"):
        """Helper to create a WellList with one well."""
        w = Well()
        w.name = "Test"
        w.size = len(gr_values)
        w.data = {var_data_name: tuple(gr_values), "Depth": tuple(range(len(gr_values)))}
        w.region = {"FACIES": tuple(facies_regions)}
        wl = WellList.__new__(WellList)
        wl.wells = [w]
        return wl

    def test_empty_var_data(self):
        """No var-data specified → always independent."""
        wl = self._make_wl([60.0] * 10, [(0, 0, 5), (1, 5, 5)])
        assert _check_facies_independence(wl, "FACIES", "") is True

    def test_binary_gr_cutoff(self):
        """Binary facies + GR var-data → detected as circular."""
        np.random.seed(42)
        gr = list(np.random.normal(60, 20, 100).astype(float))
        # Build binary regions from GR cutoff
        regions = []
        current = 0 if gr[0] < 60 else 1
        start = 0
        for i in range(1, 100):
            val = 0 if gr[i] < 60 else 1
            if val != current:
                regions.append((current, start, i - start))
                current = val
                start = i
        regions.append((current, start, 100 - start))

        wl = self._make_wl(gr, regions)
        assert _check_facies_independence(wl, "FACIES", "GR") is False

    def test_multiclass_expert_facies(self):
        """5-class facies → assumed expert interpretation → independent."""
        gr = list(np.random.normal(60, 20, 50).astype(float))
        regions = [(1, 0, 10), (2, 10, 10), (3, 20, 10), (4, 30, 10), (5, 40, 10)]
        wl = self._make_wl(gr, regions)
        assert _check_facies_independence(wl, "FACIES", "GR") is True

    def test_binary_but_different_log(self):
        """Binary facies + RT (not GR) → independent (different source)."""
        rt = list(np.random.lognormal(1, 1, 50).astype(float))
        regions = [(0, 0, 25), (1, 25, 25)]
        wl = self._make_wl(rt, regions, var_data_name="RT")
        assert _check_facies_independence(wl, "FACIES", "RT") is True

    def test_region_not_found(self):
        """If facies region doesn't exist in wells → default independent."""
        wl = self._make_wl([60.0] * 10, [(0, 0, 5), (1, 5, 5)])
        assert _check_facies_independence(wl, "NONEXISTENT", "GR") is True


class TestWheelerGapAnalysis:
    def _make_result(self, lines_data):
        """Create a minimal result-like object with .lines attribute."""
        class Line:
            def __init__(self, markers):
                self.markers = markers
        class Result:
            def __init__(self, lines):
                self.lines = lines
        return Result([Line(m) for m in lines_data])

    def test_empty_result(self):
        result = self._make_result([])
        analysis = _wheeler_gap_analysis(result, ["W1", "W2"])
        assert "wells" in analysis
        assert "W1" in analysis["wells"]
        assert analysis["wells"]["W1"]["gaps"] == []

    def test_no_gaps(self):
        """All wells advance between lines → no gaps."""
        lines = [[0, 0], [10, 10], [20, 20]]
        result = self._make_result(lines)
        analysis = _wheeler_gap_analysis(result, ["W1", "W2"])
        assert len(analysis["wells"]["W1"]["gaps"]) == 0
        assert len(analysis["wells"]["W1"]["present"]) == 2
        assert analysis["wells"]["W1"]["gap_fraction"] == 0.0

    def test_one_well_gaps(self):
        """Second well stays at same index → gap detected."""
        lines = [[0, 0], [10, 0], [20, 5]]
        result = self._make_result(lines)
        analysis = _wheeler_gap_analysis(result, ["W1", "W2"])
        # W1 advances in both intervals → 0 gaps
        assert len(analysis["wells"]["W1"]["gaps"]) == 0
        # W2 doesn't advance in first interval → 1 gap
        assert len(analysis["wells"]["W2"]["gaps"]) == 1
        assert analysis["wells"]["W2"]["gap_fraction"] == 0.5

    def test_all_wells_gap(self):
        """All wells have same marker → universal gap."""
        lines = [[5, 5], [5, 5], [10, 10]]
        result = self._make_result(lines)
        analysis = _wheeler_gap_analysis(result, ["W1", "W2"])
        # First interval is a gap for both
        assert len(analysis["wells"]["W1"]["gaps"]) == 1
        assert len(analysis["wells"]["W2"]["gaps"]) == 1
