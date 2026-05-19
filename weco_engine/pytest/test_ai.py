"""
Tests for weco.ai — AI-enhanced preprocessing and postprocessing
=================================================================

Covers:
- facies_predict: FaciesPredictor (train, predict, cross-validate, save/load)
- auto_tune: AutoTuner (objective, DE optimiser, helpers)
- anomaly: CorrelationAnomalyDetector, StatisticalAnomalyDetector
- log_qc: LogQC (washout, impute, normalise)
- quality: CorrelationQuality
- uncertainty: CorrelationUncertainty
"""

import math
import os
import tempfile

import numpy as np
import pytest

from weco.data import Well, WellList


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


def _make_well(name: str, size: int = 40, seed: int = 0) -> Well:
    """Create a synthetic well with GR, RT, RHOB + facies region."""
    rng = np.random.RandomState(seed)
    w = Well()
    w.name = name
    w.size = size
    w.x = 1000.0 + seed * 500
    w.y = 2000.0 + seed * 300
    w.z = 0.0
    w.h = float(size) * 10.0
    w.data["GR"] = list(rng.uniform(20, 120, size))
    w.data["RT"] = list(rng.uniform(1, 50, size))
    w.data["RHOB"] = list(rng.uniform(2.0, 2.7, size))

    # Deterministic facies pattern (ensures >1 class)
    facies = np.array([1 + (i % 4) for i in range(size)], dtype=float)
    w.data["Facies"] = list(facies)
    w.add_region_from_data("Facies")
    return w


@pytest.fixture
def sample_wells():
    """6 wells with shared log names and facies."""
    return [_make_well(f"W{i:02d}", 40, seed=i) for i in range(6)]


@pytest.fixture
def sample_well_list(sample_wells):
    wl = WellList.__new__(WellList)
    wl.wells = list(sample_wells)
    return wl


# Minimal ResFile mock for anomaly/uncertainty/quality tests
class _MockCorrelation:
    def __init__(self, cost, points=None, is_gap=False):
        self.cost = cost
        self.points = points or []
        self.list = None


class _MockResFile:
    def __init__(self, n_cor=5, costs=None):
        self._n = n_cor
        costs = costs or [float(i) for i in range(n_cor)]
        self._cors = [_MockCorrelation(c) for c in costs]
        self.well_names = []

    def nbr_cor(self):
        return self._n

    def cor(self, i):
        if 0 <= i < self._n:
            return self._cors[i]
        return None


# ===================================================================
# FaciesPredictor
# ===================================================================

class TestFaciesPredictor:
    """Tests for weco.ai.facies_predict."""

    def test_import(self):
        from weco.ai.facies_predict import FaciesPredictor
        assert FaciesPredictor is not None

    def test_init_defaults(self):
        from weco.ai.facies_predict import FaciesPredictor
        fp = FaciesPredictor()
        assert fp.n_classes == 5
        assert fp.window == 3
        assert not fp.is_trained
        assert fp.classes is None

    def test_train_basic(self, sample_wells):
        from weco.ai.facies_predict import FaciesPredictor
        fp = FaciesPredictor(window=2, n_estimators=20, max_depth=3)
        fp.train(sample_wells, log_names=["GR", "RT"], facies_name="Facies")
        assert fp.is_trained
        assert fp.classes is not None
        assert len(fp.classes) >= 2

    def test_predict_returns_labels(self, sample_wells):
        from weco.ai.facies_predict import FaciesPredictor
        fp = FaciesPredictor(window=2, n_estimators=20, max_depth=3)
        fp.train(sample_wells[:4], ["GR", "RT"], "Facies")
        labels = fp.predict(sample_wells[4], ["GR", "RT"])
        assert len(labels) == sample_wells[4].size
        assert all(isinstance(int(l), int) for l in labels)

    def test_predict_creates_region(self, sample_wells):
        from weco.ai.facies_predict import FaciesPredictor
        fp = FaciesPredictor(window=1, n_estimators=10, max_depth=2)
        fp.train(sample_wells[:3], ["GR"], "Facies")
        fp.predict(sample_wells[5], ["GR"], output_region="pred_fac")
        assert "pred_fac" in sample_wells[5].region

    def test_predict_creates_data_channel(self, sample_wells):
        from weco.ai.facies_predict import FaciesPredictor
        fp = FaciesPredictor(window=1, n_estimators=10, max_depth=2)
        fp.train(sample_wells[:3], ["GR"], "Facies")
        fp.predict(sample_wells[5], ["GR"], output_data="pred_data")
        assert "pred_data" in sample_wells[5].data

    def test_predict_untrained_raises(self, sample_wells):
        from weco.ai.facies_predict import FaciesPredictor
        fp = FaciesPredictor()
        with pytest.raises(RuntimeError, match="not trained"):
            fp.predict(sample_wells[0], ["GR"])

    def test_predict_missing_log_raises(self, sample_wells):
        from weco.ai.facies_predict import FaciesPredictor
        fp = FaciesPredictor(window=1, n_estimators=10, max_depth=2)
        fp.train(sample_wells[:3], ["GR"], "Facies")
        with pytest.raises(KeyError, match="missing log"):
            fp.predict(sample_wells[0], ["GR", "NONEXIST"])

    def test_train_no_usable_wells_raises(self):
        from weco.ai.facies_predict import FaciesPredictor
        fp = FaciesPredictor()
        w = Well("empty")
        w.size = 5
        w.data["GR"] = [1.0] * 5
        # No facies region
        with pytest.raises(ValueError, match="No usable"):
            fp.train([w], ["GR"], "FACIES")

    def test_train_from_data_channel(self, sample_wells):
        from weco.ai.facies_predict import FaciesPredictor
        fp = FaciesPredictor(window=1, n_estimators=10, max_depth=2)
        fp.train(sample_wells[:3], ["GR"], "Facies", facies_source="data")
        assert fp.is_trained

    def test_predict_proba(self, sample_wells):
        from weco.ai.facies_predict import FaciesPredictor
        fp = FaciesPredictor(window=1, n_estimators=10, max_depth=2)
        fp.train(sample_wells[:3], ["GR", "RT"], "Facies")
        proba = fp.predict_proba(sample_wells[4], ["GR", "RT"])
        assert proba.shape[0] == sample_wells[4].size
        assert proba.shape[1] == len(fp.classes)
        np.testing.assert_allclose(proba.sum(axis=1), 1.0, atol=1e-6)

    def test_feature_importance(self, sample_wells):
        from weco.ai.facies_predict import FaciesPredictor
        fp = FaciesPredictor(window=1, n_estimators=10, max_depth=2)
        fp.train(sample_wells[:4], ["GR", "RT"], "Facies")
        imp = fp.feature_importance()
        assert "GR" in imp
        assert "RT" in imp
        assert sum(imp.values()) == pytest.approx(1.0, abs=0.01)

    def test_cross_validate(self, sample_wells):
        from weco.ai.facies_predict import FaciesPredictor
        fp = FaciesPredictor(window=1, n_estimators=10, max_depth=2)
        result = fp.cross_validate(
            sample_wells, ["GR", "RT"], "Facies", n_folds=-1  # LOOCV
        )
        assert "accuracy" in result
        assert 0.0 <= result["accuracy"] <= 1.0
        assert "per_class_accuracy" in result
        assert result["n_samples"] > 0

    def test_save_load(self, sample_wells, tmp_dir):
        from weco.ai.facies_predict import FaciesPredictor
        fp = FaciesPredictor(window=1, n_estimators=10, max_depth=2)
        fp.train(sample_wells[:3], ["GR", "RT"], "Facies")

        path = os.path.join(tmp_dir, "model.pkl")
        fp.save(path)
        assert os.path.exists(path)

        fp2 = FaciesPredictor.load(path)
        assert fp2.is_trained
        labels1 = fp.predict(sample_wells[4], ["GR", "RT"], output_region=None)
        labels2 = fp2.predict(sample_wells[4], ["GR", "RT"], output_region=None)
        np.testing.assert_array_equal(labels1, labels2)

    def test_multiple_logs(self, sample_wells):
        from weco.ai.facies_predict import FaciesPredictor
        fp = FaciesPredictor(window=1, n_estimators=10, max_depth=2)
        fp.train(sample_wells[:3], ["GR", "RT", "RHOB"], "Facies")
        labels = fp.predict(sample_wells[4], ["GR", "RT", "RHOB"])
        assert len(labels) == sample_wells[4].size


# ===================================================================
# AutoTuner
# ===================================================================

class TestAutoTuner:
    """Tests for weco.ai.auto_tune."""

    def test_import(self):
        from weco.ai.auto_tune import AutoTuner, DEFAULT_PARAM_BOUNDS
        assert AutoTuner is not None
        assert "var-weight" in DEFAULT_PARAM_BOUNDS

    def test_init_defaults(self):
        from weco.ai.auto_tune import AutoTuner
        t = AutoTuner()
        assert t.param_bounds  # non-empty
        assert t.history == []
        assert t.misfit_fn is not None

    def test_init_custom_bounds(self):
        from weco.ai.auto_tune import AutoTuner
        bounds = {"var-weight": (0.5, 2.0)}
        t = AutoTuner(param_bounds=bounds)
        assert t.param_bounds == bounds

    def test_marker_offset_misfit_empty(self):
        from weco.ai.auto_tune import marker_offset_misfit
        r1 = _MockResFile(0)
        r2 = _MockResFile(0)
        assert marker_offset_misfit(r1, r2) == float("inf")

    def test_marker_offset_misfit_basic(self):
        from weco.ai.auto_tune import marker_offset_misfit
        r1 = _MockResFile(3, [1.0, 2.0, 3.0])
        r2 = _MockResFile(3, [1.0, 2.0, 3.0])
        m = marker_offset_misfit(r1, r2)
        assert m >= 0.0
        assert not math.isinf(m)

    def test_cost_misfit_basic(self):
        from weco.ai.auto_tune import cost_misfit
        r1 = _MockResFile(3, [1.0, 2.0, 3.0])
        r2 = _MockResFile(3, [1.0, 2.0, 3.0])
        assert cost_misfit(r1, r2) == pytest.approx(0.0, abs=1e-8)

    def test_cost_misfit_different(self):
        from weco.ai.auto_tune import cost_misfit
        r1 = _MockResFile(3, [1.0, 2.0, 3.0])
        r2 = _MockResFile(3, [2.0, 3.0, 4.0])
        assert cost_misfit(r1, r2) > 0.0

    def test_best_result_empty(self):
        from weco.ai.auto_tune import AutoTuner
        t = AutoTuner()
        assert t.best_result() is None

    def test_best_result_with_history(self):
        from weco.ai.auto_tune import AutoTuner
        t = AutoTuner()
        t.history = [
            {"params": {"var-weight": 1.0}, "misfit": 0.5},
            {"params": {"var-weight": 2.0}, "misfit": 0.2},
            {"params": {"var-weight": 3.0}, "misfit": 0.8},
        ]
        best = t.best_result()
        assert best["misfit"] == pytest.approx(0.2)
        assert best["params"]["var-weight"] == 2.0

    def test_convergence_curve_empty(self):
        from weco.ai.auto_tune import AutoTuner
        t = AutoTuner()
        iters, curve = t.convergence_curve()
        assert len(iters) == 0
        assert len(curve) == 0

    def test_convergence_curve(self):
        from weco.ai.auto_tune import AutoTuner
        t = AutoTuner()
        t.history = [
            {"params": {}, "misfit": 1.0},
            {"params": {}, "misfit": 0.8},
            {"params": {}, "misfit": 0.9},
            {"params": {}, "misfit": 0.5},
        ]
        iters, curve = t.convergence_curve()
        assert len(iters) == 4
        np.testing.assert_array_equal(curve, [1.0, 0.8, 0.8, 0.5])

    def test_parameter_sensitivity(self):
        from weco.ai.auto_tune import AutoTuner
        t = AutoTuner(param_bounds={"var-weight": (0, 5)})
        # Create fake history with clear correlation
        rng = np.random.RandomState(42)
        for _ in range(30):
            x = rng.uniform(0, 5)
            t.history.append({"params": {"var-weight": x}, "misfit": x * 2 + rng.normal(0, 0.1)})
        sens = t.parameter_sensitivity()
        assert "var-weight" in sens
        assert sens["var-weight"] > 0.5  # should be highly correlated

    def test_parameter_sensitivity_insufficient_data(self):
        from weco.ai.auto_tune import AutoTuner
        t = AutoTuner()
        t.history = [{"params": {"var-weight": 1.0}, "misfit": 0.5}]
        assert t.parameter_sensitivity() == {}

    def test_summary_no_data(self):
        from weco.ai.auto_tune import AutoTuner
        t = AutoTuner()
        s = t.summary()
        assert "No optimisation" in s

    def test_summary_with_data(self):
        from weco.ai.auto_tune import AutoTuner
        t = AutoTuner(param_bounds={"var-weight": (0, 5)})
        rng = np.random.RandomState(42)
        for _ in range(10):
            x = rng.uniform(0, 5)
            t.history.append({"params": {"var-weight": x}, "misfit": x + 1})
        s = t.summary()
        assert "Best misfit" in s
        assert "var-weight" in s

    def test_optimise_invalid_method(self):
        from weco.ai.auto_tune import AutoTuner
        t = AutoTuner()
        with pytest.raises(ValueError, match="Unknown method"):
            t.optimise(method="bogus")


# ===================================================================
# CorrelationAnomalyDetector
# ===================================================================

class TestAnomalyDetector:
    """Tests for weco.ai.anomaly."""

    def test_import(self):
        from weco.ai.anomaly import CorrelationAnomalyDetector, StatisticalAnomalyDetector
        assert CorrelationAnomalyDetector is not None
        assert StatisticalAnomalyDetector is not None

    def test_init_default(self):
        from weco.ai.anomaly import CorrelationAnomalyDetector
        d = CorrelationAnomalyDetector()
        assert d.contamination == 0.1

    def test_init_bad_contamination(self):
        from weco.ai.anomaly import CorrelationAnomalyDetector
        with pytest.raises(ValueError, match="contamination"):
            CorrelationAnomalyDetector(contamination=0.6)
        with pytest.raises(ValueError, match="contamination"):
            CorrelationAnomalyDetector(contamination=0.0)

    def test_flag_basic(self, sample_well_list):
        from weco.ai.anomaly import CorrelationAnomalyDetector
        # Create a ResFile mock with varying costs
        res = _MockResFile(20, [float(i) for i in range(20)])
        d = CorrelationAnomalyDetector(contamination=0.15)
        report = d.flag_anomalies(res, sample_well_list)
        assert len(report) == 20
        assert all("anomaly" in r for r in report)
        assert all("score" in r for r in report)
        assert all("features" in r for r in report)

    def test_flag_with_outlier(self, sample_well_list):
        from weco.ai.anomaly import CorrelationAnomalyDetector
        costs = [1.0] * 19 + [100.0]  # last one is outlier
        res = _MockResFile(20, costs)
        d = CorrelationAnomalyDetector(contamination=0.1)
        report = d.flag_anomalies(res, sample_well_list)
        # The outlier should be flagged
        flagged = [r["index"] for r in report if r["anomaly"]]
        assert 19 in flagged

    def test_flag_single_cor(self, sample_well_list):
        from weco.ai.anomaly import CorrelationAnomalyDetector
        res = _MockResFile(1, [5.0])
        d = CorrelationAnomalyDetector()
        report = d.flag_anomalies(res, sample_well_list)
        assert len(report) == 1
        assert not report[0]["anomaly"]  # can't flag with just 1

    def test_flag_empty(self, sample_well_list):
        from weco.ai.anomaly import CorrelationAnomalyDetector
        res = _MockResFile(0)
        d = CorrelationAnomalyDetector()
        report = d.flag_anomalies(res, sample_well_list)
        assert report == []

    def test_anomaly_indices(self, sample_well_list):
        from weco.ai.anomaly import CorrelationAnomalyDetector
        costs = [1.0] * 19 + [100.0]
        res = _MockResFile(20, costs)
        d = CorrelationAnomalyDetector(contamination=0.1)
        indices = d.anomaly_indices(res, sample_well_list)
        assert isinstance(indices, list)
        assert all(isinstance(i, int) for i in indices)

    def test_summary_text(self, sample_well_list):
        from weco.ai.anomaly import CorrelationAnomalyDetector
        costs = [1.0] * 19 + [100.0]
        res = _MockResFile(20, costs)
        d = CorrelationAnomalyDetector(contamination=0.1)
        s = d.summary(res, sample_well_list)
        assert "flagged" in s

    def test_statistical_detector(self, sample_well_list):
        from weco.ai.anomaly import StatisticalAnomalyDetector
        costs = [1.0] * 19 + [100.0]
        res = _MockResFile(20, costs)
        d = StatisticalAnomalyDetector(threshold=2.0)
        report = d.flag_anomalies(res, sample_well_list)
        assert len(report) == 20
        flagged = [r["index"] for r in report if r["anomaly"]]
        assert 19 in flagged  # outlier should be flagged

    def test_statistical_detector_single(self, sample_well_list):
        from weco.ai.anomaly import StatisticalAnomalyDetector
        res = _MockResFile(1, [5.0])
        d = StatisticalAnomalyDetector()
        report = d.flag_anomalies(res, sample_well_list)
        assert len(report) == 1

    def test_feature_extraction(self, sample_well_list):
        from weco.ai.anomaly import _extract_correlation_features
        res = _MockResFile(5, [1.0, 2.0, 3.0, 4.0, 5.0])
        features = _extract_correlation_features(res, sample_well_list)
        assert features.shape == (5, 6)
        # Cost column should match
        np.testing.assert_array_equal(features[:, 0], [1.0, 2.0, 3.0, 4.0, 5.0])


# ===================================================================
# LogQC (existing module — verify integration)
# ===================================================================

class TestLogQC:
    """Sanity checks for weco.ai.log_qc."""

    def test_import(self):
        from weco.ai.log_qc import LogQC
        assert LogQC is not None

    def test_detect_washouts_no_caliper(self):
        from weco.ai.log_qc import LogQC
        w = _make_well("Test", 20, seed=99)
        qc = LogQC()
        bad = qc.detect_washouts(w, caliper_name="CALI")
        # No CALI → should return all-good
        assert not bad.any()
        assert "QC_weight" in w.data

    def test_detect_washouts_with_caliper(self):
        from weco.ai.log_qc import LogQC
        w = _make_well("Test", 30, seed=99)
        cali = [8.5] * 30
        cali[10] = 20.0  # washout
        cali[11] = 22.0  # washout
        w.data["CALI"] = cali
        qc = LogQC()
        bad = qc.detect_washouts(w, caliper_name="CALI", threshold_sigma=2.0)
        assert bad[10] or bad[11]  # at least one washout flagged
        assert "QC_weight" in w.data

    def test_normalise_log(self):
        from weco.ai.log_qc import LogQC
        wells = [_make_well(f"N{i}", 30, seed=i) for i in range(3)]
        wl = WellList.__new__(WellList)
        wl.wells = wells
        qc = LogQC()
        qc.normalise_logs(wl, "GR")
        # After normalisation, values should be in [0, 1] range (mostly)
        for w in wl.wells:
            vals = np.array(w.data["GR"])
            assert np.all(vals >= -0.5)  # some may be slightly below 0
            assert np.all(vals <= 1.5)   # some may be slightly above 1


# ===================================================================
# CorrelationQuality (existing module — verify)
# ===================================================================

class TestCorrelationQuality:
    """Sanity checks for weco.ai.quality."""

    def test_import(self):
        from weco.ai.quality import CorrelationQuality
        assert CorrelationQuality is not None

    def test_init_weights(self):
        from weco.ai.quality import CorrelationQuality
        q = CorrelationQuality()
        assert sum(q.weights.values()) == pytest.approx(1.0)


# ===================================================================
# CorrelationUncertainty (existing module — verify)
# ===================================================================

class TestCorrelationUncertainty:
    """Sanity checks for weco.ai.uncertainty."""

    def test_import(self):
        from weco.ai.uncertainty import CorrelationUncertainty
        assert CorrelationUncertainty is not None

    def test_from_n_best_single(self):
        from weco.ai.uncertainty import CorrelationUncertainty
        res = _MockResFile(1, [1.0])
        cu = CorrelationUncertainty()
        unc = cu.from_n_best(res)
        assert isinstance(unc, dict)
        # Single path → no spread → empty uncertainty
        assert len(unc) == 0


# ===================================================================
# Package __init__
# ===================================================================

class TestPackageInit:
    """Verify the weco.ai package exposes the expected modules."""

    def test_all_modules_listed(self):
        import weco.ai
        assert "log_qc" in weco.ai.__all__
        assert "facies_predict" in weco.ai.__all__
        assert "uncertainty" in weco.ai.__all__
        assert "quality" in weco.ai.__all__
        assert "anomaly" in weco.ai.__all__
        assert "auto_tune" in weco.ai.__all__

    def test_submodule_import(self):
        from weco.ai import log_qc, facies_predict, uncertainty, quality, anomaly, auto_tune
        assert log_qc is not None
        assert facies_predict is not None
        assert uncertainty is not None
        assert quality is not None
        assert anomaly is not None
        assert auto_tune is not None
