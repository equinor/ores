"""
Tests for weco.preprocessing — Data conditioning transforms
============================================================

Tests all public functions in weco.preprocessing that were previously
untested: compute_vshale, compute_stacking_pattern, compute_porosity_density,
compute_log_ratio, compute_moving_average, normalise_log, add_biozones,
read_biozone_csv, project_facies_map, compute_electrofacies,
apply_standard_preprocessing.
"""

import csv
import os
import tempfile

import numpy as np
import pytest

from weco.data import Well, WellList
from weco.preprocessing import (
    _array,
    _labels_to_intervals,
    _region_to_array,
    compute_vshale,
    compute_stacking_pattern,
    compute_porosity_density,
    compute_log_ratio,
    compute_moving_average,
    normalise_log,
    add_biozones,
    read_biozone_csv,
    project_facies_map,
    apply_standard_preprocessing,
)


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------

def _make_well(name="W1", size=20, gr=None, rhob=None, rt=None):
    """Create a Well with synthetic log data."""
    w = Well(name)
    w.size = size
    w.x = 100.0
    w.y = 200.0
    w.z = 0.0
    w.h = float(size)

    if gr is None:
        # Realistic GR: 20-120 API
        gr = np.linspace(30, 110, size) + np.random.default_rng(42).normal(0, 5, size)
    w.add_data("GR", gr.tolist())

    if rhob is None:
        # Realistic density: 2.0-2.6 g/cc
        rhob = np.linspace(2.1, 2.55, size)
    w.add_data("RHOB", rhob.tolist())

    if rt is None:
        # Resistivity: 1-100 ohm.m
        rt = np.linspace(5, 80, size)
    w.add_data("RT", rt.tolist())

    return w


def _make_well_list(n_wells=3, size=20):
    """Create a WellList with n synthetic wells."""
    wl = WellList()
    for i in range(n_wells):
        w = _make_well(f"Well_{i}", size=size)
        w.x = float(i * 100)
        w.y = float(i * 50)
        wl.wells.append(w)
    return wl


# ═══════════════════════════════════════════════════════════════════════════
#  Internal helpers
# ═══════════════════════════════════════════════════════════════════════════


class TestInternalHelpers:
    def test_array_ok(self):
        w = _make_well()
        arr = _array(w, "GR")
        assert isinstance(arr, np.ndarray)
        assert arr.dtype == np.float64
        assert len(arr) == w.size

    def test_array_missing(self):
        w = _make_well()
        with pytest.raises(KeyError, match="MISSING"):
            _array(w, "MISSING")

    def test_labels_to_intervals_empty(self):
        assert _labels_to_intervals(np.array([])) == []

    def test_labels_to_intervals_uniform(self):
        labels = np.array([2, 2, 2, 2])
        result = _labels_to_intervals(labels)
        assert result == [(2, 0, 4)]

    def test_labels_to_intervals_varied(self):
        labels = np.array([0, 0, 1, 1, 1, 2])
        result = _labels_to_intervals(labels)
        assert result == [(0, 0, 2), (1, 2, 3), (2, 5, 1)]

    def test_region_to_array_missing(self):
        w = _make_well()
        with pytest.raises(KeyError, match="MISSING"):
            _region_to_array(w, "MISSING")

    def test_region_to_array_basic(self):
        w = _make_well(size=10)
        w.add_region("facies", [(1, 0, 4), (2, 4, 3), (3, 7, 3)])
        arr = _region_to_array(w, "facies")
        assert arr[0] == 1.0
        assert arr[5] == 2.0
        assert arr[9] == 3.0


# ═══════════════════════════════════════════════════════════════════════════
#  compute_vshale
# ═══════════════════════════════════════════════════════════════════════════


class TestComputeVshale:
    def test_linear_default(self):
        w = _make_well()
        assert compute_vshale(w) is True
        assert "Vshale" in w.data
        vsh = np.array(w.data["Vshale"])
        assert len(vsh) == w.size
        assert np.all(vsh >= 0.0)
        assert np.all(vsh <= 1.0)

    def test_clavier(self):
        w = _make_well()
        assert compute_vshale(w, method="clavier", output_name="Vsh_clv") is True
        vsh = np.array(w.data["Vsh_clv"])
        assert np.all(vsh >= 0.0)
        assert np.all(vsh <= 1.0)

    def test_steiber(self):
        w = _make_well()
        assert compute_vshale(w, method="steiber", output_name="Vsh_stb") is True
        vsh = np.array(w.data["Vsh_stb"])
        assert len(vsh) == w.size
        # Steiber values are ∈ [0, 1] for IGR ∈ [0, 1]
        assert vsh.min() >= 0.0

    def test_custom_clean_shale(self):
        w = _make_well()
        assert compute_vshale(w, gr_clean=20.0, gr_shale=120.0) is True
        vsh = np.array(w.data["Vshale"])
        assert np.all(vsh >= 0.0)
        assert np.all(vsh <= 1.0)

    def test_missing_log_returns_false(self):
        w = _make_well()
        assert compute_vshale(w, gr_name="NONEXISTENT") is False

    def test_output_name(self):
        w = _make_well()
        compute_vshale(w, output_name="MY_VSH")
        assert "MY_VSH" in w.data


# ═══════════════════════════════════════════════════════════════════════════
#  compute_stacking_pattern
# ═══════════════════════════════════════════════════════════════════════════


class TestComputeStackingPattern:
    def test_basic(self):
        w = _make_well()
        assert compute_stacking_pattern(w) is True
        assert "StackingPattern" in w.data
        sp = np.array(w.data["StackingPattern"])
        assert len(sp) == w.size

    def test_no_smoothing(self):
        w = _make_well()
        compute_stacking_pattern(w, window=1, output_name="SP_raw")
        sp = np.array(w.data["SP_raw"])
        assert len(sp) == w.size

    def test_missing_log(self):
        w = _make_well()
        assert compute_stacking_pattern(w, gr_name="NOPE") is False

    def test_increasing_gr_positive_derivative(self):
        """Monotonically increasing GR should yield mostly positive stacking."""
        w = _make_well(gr=np.linspace(10, 100, 20))
        compute_stacking_pattern(w, window=1)
        sp = np.array(w.data["StackingPattern"])
        # All derivatives should be positive (fining-up)
        assert np.all(sp > 0)


# ═══════════════════════════════════════════════════════════════════════════
#  compute_porosity_density
# ═══════════════════════════════════════════════════════════════════════════


class TestComputePorosityDensity:
    def test_basic(self):
        w = _make_well()
        assert compute_porosity_density(w) is True
        assert "PHID" in w.data
        phi = np.array(w.data["PHID"])
        assert len(phi) == w.size
        assert np.all(phi >= 0.0)
        assert np.all(phi <= 0.50)

    def test_known_values(self):
        """For RHOB=2.65 (matrix), porosity should be 0."""
        w = _make_well(rhob=np.full(10, 2.65), size=10)
        compute_porosity_density(w, rho_matrix=2.65, rho_fluid=1.0)
        phi = np.array(w.data["PHID"])
        assert np.allclose(phi, 0.0, atol=0.001)

    def test_known_values_water(self):
        """For RHOB=1.0 (water), porosity should be 1.0 (clipped to 0.5)."""
        w = _make_well(rhob=np.full(10, 1.0), size=10)
        compute_porosity_density(w, rho_matrix=2.65, rho_fluid=1.0)
        phi = np.array(w.data["PHID"])
        assert np.allclose(phi, 0.50, atol=0.001)

    def test_missing_log(self):
        w = _make_well()
        assert compute_porosity_density(w, rhob_name="MISSING") is False

    def test_custom_output(self):
        w = _make_well()
        compute_porosity_density(w, output_name="MyPhi")
        assert "MyPhi" in w.data


# ═══════════════════════════════════════════════════════════════════════════
#  compute_log_ratio
# ═══════════════════════════════════════════════════════════════════════════


class TestComputeLogRatio:
    def test_log_ratio(self):
        w = _make_well()
        assert compute_log_ratio(w, "GR", "RT") is True
        assert "GR/RT" in w.data

    def test_raw_ratio(self):
        w = _make_well()
        compute_log_ratio(w, "GR", "RT", output_name="ratio", log_scale=False)
        ratio = np.array(w.data["ratio"])
        gr = np.array(w.data["GR"])
        rt = np.array(w.data["RT"])
        np.testing.assert_allclose(ratio, gr / rt, rtol=1e-6)

    def test_custom_name(self):
        w = _make_well()
        compute_log_ratio(w, "GR", "RT", output_name="MyRatio")
        assert "MyRatio" in w.data

    def test_missing_numerator(self):
        w = _make_well()
        assert compute_log_ratio(w, "MISSING", "RT") is False

    def test_missing_denominator(self):
        w = _make_well()
        assert compute_log_ratio(w, "GR", "MISSING") is False

    def test_zero_denominator(self):
        """Should handle zero denominator without crash."""
        w = _make_well(rt=np.zeros(20))
        assert compute_log_ratio(w, "GR", "RT") is True


# ═══════════════════════════════════════════════════════════════════════════
#  compute_moving_average
# ═══════════════════════════════════════════════════════════════════════════


class TestComputeMovingAverage:
    def test_basic(self):
        w = _make_well()
        assert compute_moving_average(w, "GR") is True
        assert "GR_smooth5" in w.data

    def test_custom_window(self):
        w = _make_well()
        compute_moving_average(w, "GR", window=3)
        assert "GR_smooth3" in w.data

    def test_custom_name(self):
        w = _make_well()
        compute_moving_average(w, "GR", output_name="GR_avg")
        assert "GR_avg" in w.data

    def test_missing_log(self):
        w = _make_well()
        assert compute_moving_average(w, "MISSING") is False

    def test_smoothing_reduces_variance(self):
        """Moving average should reduce variance compared to raw."""
        rng = np.random.default_rng(42)
        noisy_gr = 50.0 + rng.normal(0, 20, 50)
        w = _make_well(gr=noisy_gr, size=50)
        compute_moving_average(w, "GR", window=7, output_name="GR_sm")
        raw_var = np.var(w.data["GR"])
        smooth_var = np.var(w.data["GR_sm"])
        assert smooth_var < raw_var


# ═══════════════════════════════════════════════════════════════════════════
#  normalise_log
# ═══════════════════════════════════════════════════════════════════════════


class TestNormaliseLog:
    def test_percentile(self):
        wl = _make_well_list(3)
        assert normalise_log(wl, "GR", output_name="GR_norm") is True
        for w in wl.wells:
            norm = np.array(w.data["GR_norm"])
            assert np.all(norm >= 0.0)
            assert np.all(norm <= 1.0)

    def test_zscore(self):
        wl = _make_well_list(3)
        assert normalise_log(wl, "GR", method="zscore", output_name="GR_z") is True
        # After z-score, combined mean ≈ 0
        all_z = np.concatenate([np.array(w.data["GR_z"]) for w in wl.wells])
        assert abs(np.mean(all_z)) < 0.5  # approximately 0

    def test_minmax(self):
        wl = _make_well_list(3)
        assert normalise_log(wl, "GR", method="minmax", output_name="GR_mm") is True
        all_mm = np.concatenate([np.array(w.data["GR_mm"]) for w in wl.wells])
        assert np.min(all_mm) >= 0.0
        assert np.max(all_mm) <= 1.0

    def test_custom_target_range(self):
        wl = _make_well_list(2)
        normalise_log(wl, "GR", method="minmax",
                      target_range=(-1.0, 1.0), output_name="GR_r")
        all_r = np.concatenate([np.array(w.data["GR_r"]) for w in wl.wells])
        assert np.min(all_r) >= -1.0
        assert np.max(all_r) <= 1.0

    def test_missing_log_returns_false(self):
        wl = _make_well_list(2)
        assert normalise_log(wl, "NONEXISTENT") is False

    def test_overwrites_in_place(self):
        wl = _make_well_list(1)
        raw_gr = list(wl.wells[0].data["GR"])
        normalise_log(wl, "GR")  # no output_name → overwrites
        new_gr = list(wl.wells[0].data["GR"])
        assert raw_gr != new_gr


# ═══════════════════════════════════════════════════════════════════════════
#  add_biozones
# ═══════════════════════════════════════════════════════════════════════════


class TestAddBiozones:
    def test_basic(self):
        w = _make_well(size=30)
        zones = [("NP10", 0, 10), ("NP11", 10, 10), ("NP12", 20, 10)]
        assert add_biozones(w, zones) is True
        assert "biozone" in w.region
        region = w.region["biozone"]
        # Should have 3 intervals with IDs 1, 2, 3
        assert len(region) == 3
        assert region[0][0] == 1  # NP10 → group 1
        assert region[1][0] == 2  # NP11 → group 2
        assert region[2][0] == 3  # NP12 → group 3

    def test_custom_order(self):
        w = _make_well(size=20)
        zones = [("B", 0, 10), ("A", 10, 10)]
        add_biozones(w, zones, zone_order=["A", "B"])
        region = w.region["biozone"]
        assert region[0][0] == 2  # B → index 2 in ["A", "B"]
        assert region[1][0] == 1  # A → index 1

    def test_custom_region_name(self):
        w = _make_well(size=10)
        add_biozones(w, [("Z1", 0, 10)], output_region="my_zone")
        assert "my_zone" in w.region

    def test_unknown_zone_skipped(self):
        w = _make_well(size=10)
        zones = [("NP10", 0, 5), ("UNKNOWN", 5, 5)]
        add_biozones(w, zones, zone_order=["NP10"])
        region = w.region["biozone"]
        assert len(region) == 1  # UNKNOWN skipped


# ═══════════════════════════════════════════════════════════════════════════
#  read_biozone_csv
# ═══════════════════════════════════════════════════════════════════════════


class TestReadBiozoneCsv:
    def test_basic(self, tmp_path):
        csv_path = str(tmp_path / "biozones.csv")
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["well", "zone", "top_marker", "base_marker"])
            writer.writerow(["Well_0", "NP10", "0", "9"])
            writer.writerow(["Well_0", "NP11", "10", "19"])
            writer.writerow(["Well_1", "NP10", "0", "14"])

        wl = _make_well_list(2)
        count = read_biozone_csv(csv_path, wl)
        assert count == 2
        assert "biozone" in wl.wells[0].region
        assert "biozone" in wl.wells[1].region

    def test_no_matching_wells(self, tmp_path):
        csv_path = str(tmp_path / "bio.csv")
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["well", "zone", "top_marker", "base_marker"])
            writer.writerow(["Unknown_Well", "Z1", "0", "5"])

        wl = _make_well_list(2)
        count = read_biozone_csv(csv_path, wl)
        assert count == 0


# ═══════════════════════════════════════════════════════════════════════════
#  project_facies_map
# ═══════════════════════════════════════════════════════════════════════════


class TestProjectFaciesMap:
    def test_basic(self):
        w = _make_well(size=10)
        w.x = 150.0
        w.y = 250.0
        grid = np.array([[1, 2, 3], [4, 5, 6], [7, 8, 9]])
        # cell_size=100, origin=(0,0) → ix=1, iy=2 → facies_code=8
        assert project_facies_map(w, grid, 0, 0, 100.0) is True
        assert "map_facies" in w.region
        region = w.region["map_facies"]
        assert len(region) == 1
        assert region[0][0] == 8

    def test_out_of_bounds(self):
        w = _make_well(size=10)
        w.x = 9999.0
        w.y = 9999.0
        grid = np.array([[1, 2], [3, 4]])
        assert project_facies_map(w, grid, 0, 0, 100.0) is False

    def test_custom_region_name(self):
        w = _make_well(size=10)
        w.x = 50.0
        w.y = 50.0
        grid = np.array([[7]])
        project_facies_map(w, grid, 0, 0, 100.0, output_region="mf")
        assert "mf" in w.region

    def test_marker_range(self):
        w = _make_well(size=20)
        w.x = 50.0
        w.y = 50.0
        grid = np.array([[3]])
        project_facies_map(w, grid, 0, 0, 100.0, marker_start=5, marker_end=15)
        region = w.region["map_facies"]
        assert region[0] == (3, 5, 10)  # start=5, length=10


# ═══════════════════════════════════════════════════════════════════════════
#  compute_electrofacies (requires sklearn)
# ═══════════════════════════════════════════════════════════════════════════


class TestComputeElectrofacies:
    @pytest.fixture(autouse=True)
    def _skip_no_sklearn(self):
        pytest.importorskip("sklearn")

    def test_basic(self):
        from weco.preprocessing import compute_electrofacies
        wl = _make_well_list(3, size=30)
        assert compute_electrofacies(wl, ["GR", "RT"], n_clusters=3) is True
        for w in wl.wells:
            assert "electrofacies" in w.region
            assert "electrofacies_data" in w.data
            ef_data = np.array(w.data["electrofacies_data"])
            assert np.all(ef_data >= 1)  # IDs start from 1

    def test_custom_names(self):
        from weco.preprocessing import compute_electrofacies
        wl = _make_well_list(2, size=15)
        compute_electrofacies(wl, ["GR", "RT"],
                              output_region="ef_reg", output_data="ef_dat")
        assert "ef_reg" in wl.wells[0].region
        assert "ef_dat" in wl.wells[0].data

    def test_no_data(self):
        from weco.preprocessing import compute_electrofacies
        wl = _make_well_list(2, size=10)
        assert compute_electrofacies(wl, ["NONEXISTENT"]) is False

    def test_no_continuous_output(self):
        from weco.preprocessing import compute_electrofacies
        wl = _make_well_list(2, size=15)
        compute_electrofacies(wl, ["GR", "RT"], output_data=None)
        assert "electrofacies" in wl.wells[0].region
        assert "electrofacies_data" not in wl.wells[0].data


# ═══════════════════════════════════════════════════════════════════════════
#  apply_standard_preprocessing
# ═══════════════════════════════════════════════════════════════════════════


class TestApplyStandardPreprocessing:
    def test_defaults(self):
        wl = _make_well_list(2)
        results = apply_standard_preprocessing(wl)
        assert "normalise_GR" in results
        assert "vshale" in results
        assert "stacking" in results

    def test_all_disabled(self):
        wl = _make_well_list(2)
        results = apply_standard_preprocessing(
            wl, enable_vshale=False, enable_stacking=False, enable_normalise=False)
        assert len(results) == 0

    def test_with_electrofacies(self):
        pytest.importorskip("sklearn")
        wl = _make_well_list(2, size=20)
        results = apply_standard_preprocessing(
            wl, enable_electrofacies=True,
            electrofacies_logs=["GR", "RT"])
        assert "electrofacies" in results
        assert results["electrofacies"] is True
