"""
Tests for weco.validate — Reference comparison + quality scoring
================================================================

Tests load_reference_csv, load_reference_from_resfile, compare_correlations,
score_correlation_quality, and compare_n_best.
Uses real data from data/data_set_1.1 for integration tests.
"""

import csv
import os

import numpy as np
import pytest

from weco.data import ResFile, WellList, ResAndWL
from weco.validate import (
    load_reference_csv,
    load_reference_from_resfile,
    compare_correlations,
    score_correlation_quality,
    compare_n_best,
)

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "demo", "data", "data_set_1.1")
WELLS_FILE = os.path.join(DATA_DIR, "wells.txt")
OUTCOME_FILE = os.path.join(DATA_DIR, "outcome_1.txt")


def _have_data():
    return os.path.isfile(WELLS_FILE) and os.path.isfile(OUTCOME_FILE)


# ═══════════════════════════════════════════════════════════════════════════
#  load_reference_csv
# ═══════════════════════════════════════════════════════════════════════════


class TestLoadReferenceCsv:
    def test_basic(self, tmp_path):
        csv_path = str(tmp_path / "ref.csv")
        with open(csv_path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["Well_01", "Well_02", "Well_03"])
            w.writerow(["5", "3", "7"])
            w.writerow(["10", "8", "12"])
            w.writerow(["15", "13", "17"])

        lines = load_reference_csv(csv_path)
        assert len(lines) == 3
        assert lines[0] == {"Well_01": 5, "Well_02": 3, "Well_03": 7}
        assert lines[1] == {"Well_01": 10, "Well_02": 8, "Well_03": 12}
        assert lines[2] == {"Well_01": 15, "Well_02": 13, "Well_03": 17}

    def test_empty_rows_skipped(self, tmp_path):
        csv_path = str(tmp_path / "ref2.csv")
        with open(csv_path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["A", "B"])
            w.writerow(["1", "2"])
            w.writerow(["", ""])  # empty row
            w.writerow(["3", "4"])

        lines = load_reference_csv(csv_path)
        assert len(lines) == 2

    def test_whitespace_handling(self, tmp_path):
        csv_path = str(tmp_path / "ref3.csv")
        with open(csv_path, "w") as f:
            f.write(" Well_A , Well_B \n")
            f.write(" 5 , 10 \n")

        lines = load_reference_csv(csv_path)
        assert len(lines) == 1
        assert lines[0]["Well_A"] == 5
        assert lines[0]["Well_B"] == 10

    def test_non_integer_skipped(self, tmp_path):
        csv_path = str(tmp_path / "ref4.csv")
        with open(csv_path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["A", "B"])
            w.writerow(["5", "N/A"])

        lines = load_reference_csv(csv_path)
        assert len(lines) == 1
        assert "B" not in lines[0]  # non-integer skipped
        assert lines[0]["A"] == 5


# ═══════════════════════════════════════════════════════════════════════════
#  load_reference_from_resfile
# ═══════════════════════════════════════════════════════════════════════════


class TestLoadReferenceFromResfile:
    @pytest.fixture(autouse=True)
    def _skip_no_data(self):
        if not _have_data():
            pytest.skip("data_set_1.1 not available")

    def test_basic(self):
        lines = load_reference_from_resfile(OUTCOME_FILE, WELLS_FILE, cor_num=0)
        assert isinstance(lines, list)
        assert len(lines) > 0
        # Each line should be a dict of well_name -> marker_index
        for tie in lines:
            assert isinstance(tie, dict)
            for wn, mi in tie.items():
                assert isinstance(wn, str)
                assert isinstance(mi, int)
                assert mi >= 0

    def test_out_of_range(self):
        with pytest.raises(IndexError):
            load_reference_from_resfile(OUTCOME_FILE, WELLS_FILE, cor_num=9999)

    def test_invalid_resfile(self, tmp_path):
        bad_file = str(tmp_path / "bad.txt")
        with open(bad_file, "w") as f:
            f.write("garbage\n")
        with pytest.raises(Exception):
            load_reference_from_resfile(bad_file, WELLS_FILE)


# ═══════════════════════════════════════════════════════════════════════════
#  compare_correlations
# ═══════════════════════════════════════════════════════════════════════════


class TestCompareCorrelations:
    @pytest.fixture(autouse=True)
    def _skip_no_data(self):
        if not _have_data():
            pytest.skip("data_set_1.1 not available")

    def test_self_comparison(self):
        """Comparing a result against itself should yield perfect match."""
        ref = load_reference_from_resfile(OUTCOME_FILE, WELLS_FILE, cor_num=0)
        metrics = compare_correlations(OUTCOME_FILE, ref, WELLS_FILE, cor_num=0)

        assert metrics["marker_offset_mean"] == pytest.approx(0.0, abs=1e-6)
        assert metrics["match_rate"] == pytest.approx(1.0, abs=1e-6)
        assert metrics["n_unmatched"] == 0
        assert metrics["n_matched"] == len(ref)

    def test_metrics_keys(self):
        ref = load_reference_from_resfile(OUTCOME_FILE, WELLS_FILE, cor_num=0)
        metrics = compare_correlations(OUTCOME_FILE, ref, WELLS_FILE)

        expected_keys = {
            "marker_offset_mean", "marker_offset_max",
            "depth_offset_mean", "depth_offset_max",
            "match_rate", "n_gaps_computed",
            "n_reference", "n_computed", "n_matched", "n_unmatched",
            "per_well", "matched_lines", "unmatched_lines",
        }
        assert expected_keys.issubset(set(metrics.keys()))

    def test_per_well_stats(self):
        ref = load_reference_from_resfile(OUTCOME_FILE, WELLS_FILE, cor_num=0)
        metrics = compare_correlations(OUTCOME_FILE, ref, WELLS_FILE)
        assert isinstance(metrics["per_well"], dict)
        for wn, stats in metrics["per_well"].items():
            assert "marker_offset_mean" in stats
            assert "n_matched" in stats

    def test_shifted_reference(self):
        """A shifted reference should have non-zero offset."""
        ref = load_reference_from_resfile(OUTCOME_FILE, WELLS_FILE, cor_num=0)
        # Shift all reference markers by 2
        shifted = [{wn: mi + 2 for wn, mi in tie.items()} for tie in ref]
        metrics = compare_correlations(OUTCOME_FILE, shifted, WELLS_FILE)
        assert metrics["marker_offset_mean"] > 0


# ═══════════════════════════════════════════════════════════════════════════
#  score_correlation_quality
# ═══════════════════════════════════════════════════════════════════════════


class TestScoreCorrelationQuality:
    @pytest.fixture(autouse=True)
    def _skip_no_data(self):
        if not _have_data():
            pytest.skip("data_set_1.1 not available")

    def test_without_reference(self):
        scores = score_correlation_quality(OUTCOME_FILE, WELLS_FILE, cor_num=0)
        assert "total" in scores
        assert "cost_score" in scores
        assert "gap_score" in scores
        assert "consistency_score" in scores
        assert scores["reference_score"] is None
        # All scores ∈ [0, 1]
        assert 0.0 <= scores["total"] <= 1.0
        assert 0.0 <= scores["cost_score"] <= 1.0
        assert 0.0 <= scores["gap_score"] <= 1.0
        assert 0.0 <= scores["consistency_score"] <= 1.0

    def test_with_reference(self):
        ref = load_reference_from_resfile(OUTCOME_FILE, WELLS_FILE, cor_num=0)
        scores = score_correlation_quality(OUTCOME_FILE, WELLS_FILE,
                                           cor_num=0, reference=ref)
        assert scores["reference_score"] is not None
        assert 0.0 <= scores["reference_score"] <= 1.0
        assert 0.0 <= scores["total"] <= 1.0

    def test_out_of_range(self):
        with pytest.raises(IndexError):
            score_correlation_quality(OUTCOME_FILE, WELLS_FILE, cor_num=9999)


# ═══════════════════════════════════════════════════════════════════════════
#  compare_n_best
# ═══════════════════════════════════════════════════════════════════════════


class TestCompareNBest:
    @pytest.fixture(autouse=True)
    def _skip_no_data(self):
        if not _have_data():
            pytest.skip("data_set_1.1 not available")

    def test_basic(self):
        results = compare_n_best(OUTCOME_FILE, WELLS_FILE, n_best=5)
        assert isinstance(results, list)
        assert len(results) > 0

        # First result should have rank 1 and diff_vs_best = 0
        assert results[0]["rank"] == 1
        assert results[0]["diff_vs_best"] == 0
        assert results[0]["cost"] >= 0.0

    def test_keys(self):
        results = compare_n_best(OUTCOME_FILE, WELLS_FILE, n_best=3)
        for r in results:
            assert "rank" in r
            assert "cost" in r
            assert "n_horizons" in r
            assert "n_gaps" in r
            assert "diff_vs_best" in r

    def test_ordered_by_cost(self):
        results = compare_n_best(OUTCOME_FILE, WELLS_FILE, n_best=10)
        if len(results) >= 2:
            for i in range(len(results) - 1):
                assert results[i]["cost"] <= results[i + 1]["cost"]

    def test_n_best_capped(self):
        results = compare_n_best(OUTCOME_FILE, WELLS_FILE, n_best=1)
        assert len(results) == 1
