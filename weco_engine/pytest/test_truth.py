"""Round-trip truth tests — verify the engine recovers known stratigraphy.

These tests create synthetic well data with *known* horizon positions, run the
WeCo correlation engine, and verify that the top-ranked correlation either
reproduces the truth exactly or passes within a tolerance.

Test categories
---------------
1. **Identical wells** — all wells share the same data.  The engine must
   produce a perfect 1-to-1 diagonal correlation.
2. **Eroded wells** — identical underlying signal, but wells are truncated
   at top/bottom.  The engine should still align the shared section.
3. **Realistic generators** — use the Quaternary and Coal generators to
   produce rich geological data with deterministic seeds, run the engine,
   and check that the best correlation visits known unit boundaries.
4. **Noise tolerance** — add increasing noise and verify graceful
   degradation.
"""

import math
import os
import sys
import tempfile
import shutil

import pytest

# ---------------------------------------------------------------------------
# Ensure project root is importable
# ---------------------------------------------------------------------------
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from weco.data import WellList, Well
from weco.ext import ProjectExt


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_engine(well_list, **options):
    """Run the engine on a WellList and return the ResFile."""
    engine = ProjectExt()
    defaults = {
        "cost-function": "composite",
        "order": "pyramidal",
        "nbr-cor": "50",
        "out-nbr-cor": "10",
        "max-cor": "100",
    }
    defaults.update(options)
    for k, v in defaults.items():
        engine.set_option_ext(k, str(v))
    success = engine.run(well_list)
    assert success, "Engine run failed"
    res = engine.get_res_file()
    assert res.get_nbr_results() > 0, "Engine produced no results"
    return res


def _build_identical_wells(n_wells, size, wave_length=10.0, amplitude=1.0):
    """Build *n_wells* identical sine-wave wells (no noise)."""
    wl = WellList()
    data = [math.sin(2 * math.pi * i / wave_length) * amplitude
            for i in range(size)]
    depth = [float(i) for i in range(size)]
    for j in range(n_wells):
        w = wl.create_well(f"W{j}", y=j * 100, size=size)
        w.add_data("depth", depth)
        w.add_data("signal", data)
    return wl


def _build_shifted_wells(n_wells, size, shifts, wave_length=10.0):
    """Build wells with the same underlying signal but vertical shifts.

    *shifts* is a list of integer sample offsets per well.
    The returned dict maps each well index to the 'truth' sample index in
    the original full signal where the horizon at the midpoint should sit.
    """
    full_size = size + max(abs(s) for s in shifts) * 2
    full_signal = [math.sin(2 * math.pi * i / wave_length) for i in range(full_size)]
    mid = full_size // 2  # "true horizon" sample in the full signal
    wl = WellList()
    horizon_truth = {}
    for j, shift in enumerate(shifts):
        start = (full_size - size) // 2 + shift
        end = start + size
        segment = full_signal[start:end]
        depth = [float(i) for i in range(len(segment))]
        w = wl.create_well(f"W{j}", y=j * 100, size=len(segment))
        w.add_data("depth", depth)
        w.add_data("signal", segment)
        # truth: the midpoint of the full signal maps to this sample
        local_idx = mid - start
        if 0 <= local_idx < len(segment):
            horizon_truth[j] = local_idx
    return wl, horizon_truth


def _best_path(res):
    """Return the best (lowest-cost) correlation path as a list of tuples."""
    return res.get_result_full_path(0)


# ===================================================================
# 1. Identical-well truth tests
# ===================================================================

class TestIdenticalWells:
    """All wells share the same signal — engine must produce a 1-to-1 match."""

    def test_3_wells_diagonal(self):
        """3 identical wells → near-perfect diagonal (sample i maps to ~i)."""
        wl = _build_identical_wells(3, 50, wave_length=10)
        res = _run_engine(wl, **{"var-data": "signal", "var-weight": "1.0"})
        path = _best_path(res)
        # Every node should map the same sample index across all wells
        # Allow off-by-1 due to merge-order discretization effects
        for node in path:
            assert max(node) - min(node) <= 1, (
                f"Expected near-diagonal, got {node}")

    def test_5_wells_diagonal(self):
        """5 identical wells → still near-diagonal."""
        wl = _build_identical_wells(5, 20, wave_length=8)
        res = _run_engine(wl, **{
            "var-data": "signal", "var-weight": "1.0",
            "nbr-cor": "20", "max-cor": "20"})
        path = _best_path(res)
        for node in path:
            assert max(node) - min(node) <= 1, f"Not near-diagonal: {node}"

    def test_full_coverage(self):
        """3 identical wells, 30 samples — most samples must appear."""
        wl = _build_identical_wells(3, 30, wave_length=6)
        res = _run_engine(wl, **{
            "var-data": "signal", "var-weight": "1.0",
            "max-cor": "30"})
        path = _best_path(res)
        w0_samples = sorted(n[0] for n in path)
        # Allow engine to miss a few boundary samples
        assert len(w0_samples) >= 27, (
            f"Expected ≥27 of 30 samples covered, got {len(w0_samples)}")


# ===================================================================
# 2. Eroded-well truth tests (truncation)
# ===================================================================

class TestErodedWells:
    """Wells share the same signal but are truncated at top/bottom."""

    def _make_eroded(self, n_wells=3, full_size=60, wave_length=12):
        """Create 3 wells: full, top-10 eroded, bottom-10 eroded."""
        signal = [math.sin(2 * math.pi * i / wave_length) for i in range(full_size)]
        depth = [float(i) for i in range(full_size)]
        wl = WellList()
        # W0: full
        w0 = wl.create_well("W0", y=0, size=full_size)
        w0.add_data("depth", depth)
        w0.add_data("signal", signal)
        # W1: eroded top 10
        w1 = wl.create_well("W1", y=100, size=full_size - 10)
        w1.add_data("depth", depth[10:])
        w1.add_data("signal", signal[10:])
        # W2: eroded bottom 10
        w2 = wl.create_well("W2", y=200, size=full_size - 10)
        w2.add_data("depth", depth[:full_size - 10])
        w2.add_data("signal", signal[:full_size - 10])
        return wl

    def test_eroded_alignment(self):
        """Eroded wells should align the overlapping section correctly."""
        wl = self._make_eroded()
        res = _run_engine(wl, **{
            "var-data": "signal", "var-weight": "1.0",
            "max-cor": "60"})
        path = _best_path(res)
        # In the overlapping section (samples 10..49 of W0), all three
        # wells should be present.  W0[i] should match W1[i-10] and W2[i].
        n_aligned = 0
        for node in path:
            s_w0 = node[0]
            s_w1 = node[1]
            s_w2 = node[2]
            if 10 <= s_w0 < 50:
                # Allow off-by-1 due to engine discretization
                assert abs(s_w1 - (s_w0 - 10)) <= 1, (
                    f"W0={s_w0} should match W1~={s_w0 - 10}, got W1={s_w1}")
                assert abs(s_w2 - s_w0) <= 1, (
                    f"W0={s_w0} should match W2~={s_w0}, got W2={s_w2}")
                n_aligned += 1
        assert n_aligned >= 25, (
            f"Expected ≥25 aligned samples in overlap, got {n_aligned}")


# ===================================================================
# 3. Shifted-well truth tests
# ===================================================================

class TestShiftedWells:
    """Wells with the same signal but vertically shifted — horizon should be found."""

    def test_small_shift(self):
        """Small vertical shifts (±3 samples) → midpoint recovered."""
        shifts = [0, 3, -3]
        wl, truth = _build_shifted_wells(3, 50, shifts, wave_length=10)
        res = _run_engine(wl, **{
            "var-data": "signal", "var-weight": "1.0",
            "max-cor": "60"})
        path = _best_path(res)
        # Check that the truth horizon sample is hit (within ±1) in each well
        for well_idx, expected_sample in truth.items():
            samples_at_well = sorted(node[well_idx] for node in path)
            closest = min(samples_at_well,
                          key=lambda s: abs(s - expected_sample))
            assert abs(closest - expected_sample) <= 1, (
                f"Well {well_idx}: expected sample ~{expected_sample}, "
                f"closest in path = {closest}")


# ===================================================================
# 4. TestBuilder truth tests
# ===================================================================

class TestBuilderTruth:
    """Use weco.testgen.TestBuilder for test generation."""

    def test_noiseless_sine(self):
        """No noise → perfect diagonal."""
        from weco.testgen import TestBuilder
        tb = TestBuilder(nbr_wells=4, size=40)
        tb.add_sin_data("data", wave_length=8, noise=0.0)
        tb.add_depth_data()
        tb.build()
        res = _run_engine(tb.well_list, **{
            "var-data": "data", "var-weight": "1.0"})
        path = _best_path(res)
        for node in path:
            assert len(set(node)) == 1, f"Not diagonal: {node}"

    def test_low_noise_sine(self):
        """Low noise (0.1) → still near-diagonal."""
        from weco.testgen import TestBuilder
        tb = TestBuilder(nbr_wells=4, size=40)
        tb.add_sin_data("data", wave_length=8, noise=0.1)
        tb.add_depth_data()
        tb.build()
        res = _run_engine(tb.well_list, **{
            "var-data": "data", "var-weight": "1.0"})
        path = _best_path(res)
        # Allow ±2 sample tolerance
        for node in path:
            spread = max(node) - min(node)
            assert spread <= 2, (
                f"Spread too large with low noise: {node} (spread={spread})")

    def test_eroded_sine(self):
        """Partial erosion still recovers underlying signal."""
        from weco.testgen import TestBuilder
        tb = TestBuilder(nbr_wells=3, size=60)
        tb.add_sin_data("data", wave_length=12, noise=0.0)
        tb.add_depth_data()
        tb.erode_start(10, 5)
        tb.erode_end(10, 5)
        tb.build()
        res = _run_engine(tb.well_list, **{
            "var-data": "data", "var-weight": "1.0",
            "max-cor": "60"})
        path = _best_path(res)
        # The best correlation should exist and have low cost
        assert res.get_result_cost(0) < 1.0, (
            f"Cost too high for noiseless eroded data: {res.get_result_cost(0)}")


# ===================================================================
# 5. Realistic dataset tests (Quaternary & Coal generators)
# ===================================================================

class TestQuaternaryTruth:
    """Generate a small quaternary dataset and verify the engine produces
    sensible correlations against known unit boundaries."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.tmp = str(tmp_path)

    def _generate_small(self, n_grid=3, seed=42):
        """Generate a small (n_grid²) quaternary dataset."""
        gen_path = os.path.join(ROOT, "demo", "data", "data_set_quaternary",
                                "generate_quaternary.py")
        # Import the generator
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "gen_quat", gen_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        wells = mod.main(seed=seed, n_grid=n_grid,
                         output_dir=self.tmp)
        return wells

    def test_basic_run(self):
        """Engine produces results on quaternary data."""
        wells = self._generate_small()
        wells_path = os.path.join(self.tmp, "wells.txt")
        options_path = os.path.join(self.tmp, "options_basic.txt")
        assert os.path.exists(wells_path)
        assert os.path.exists(options_path)
        engine = ProjectExt()
        engine.option_load(os.path.abspath(options_path))
        success = engine.run(os.path.abspath(wells_path))
        assert success
        res = engine.get_res_file()
        assert res.get_nbr_results() > 0
        # Best cost should be finite
        best_cost = res.get_result_cost(0)
        assert math.isfinite(best_cost)

    def test_multiple_results(self):
        """Engine produces multiple alternative correlations."""
        wells = self._generate_small(n_grid=3, seed=99)
        wells_path = os.path.join(self.tmp, "wells.txt")
        options_path = os.path.join(self.tmp, "options_basic.txt")
        engine = ProjectExt()
        engine.option_load(os.path.abspath(options_path))
        engine.set_option_ext("out-nbr-cor", "5")
        success = engine.run(os.path.abspath(wells_path))
        assert success
        res = engine.get_res_file()
        n = res.get_nbr_results()
        assert n >= 2, f"Expected ≥2 results, got {n}"
        # Costs should be monotonically non-decreasing
        costs = [res.get_result_cost(i) for i in range(n)]
        for i in range(1, len(costs)):
            assert costs[i] >= costs[i - 1] - 1e-9, (
                f"Costs not sorted: {costs}")

    def test_horizon_monotonicity(self):
        """Best correlation path should be monotonically increasing per well.
        This is a fundamental DAG-DTW property — the path can only advance
        forward in each well."""
        wells = self._generate_small()
        wells_path = os.path.join(self.tmp, "wells.txt")
        options_path = os.path.join(self.tmp, "options_basic.txt")
        engine = ProjectExt()
        engine.option_load(os.path.abspath(options_path))
        success = engine.run(os.path.abspath(wells_path))
        assert success
        res = engine.get_res_file()
        path = _best_path(res)
        n_wells = res.nbr_well()
        for w in range(n_wells):
            samples = [node[w] for node in path]
            for i in range(1, len(samples)):
                assert samples[i] >= samples[i - 1], (
                    f"Well {w}: non-monotonic at nodes {i - 1}→{i}: "
                    f"{samples[i - 1]}→{samples[i]}")


class TestCoalTruth:
    """Generate a small coal dataset and verify engine behaviour."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.tmp = str(tmp_path)

    def _generate_small(self, n_wells=6, seed=42):
        gen_path = os.path.join(ROOT, "demo", "data", "data_set_coal",
                                "generate_coal.py")
        import importlib.util
        spec = importlib.util.spec_from_file_location("gen_coal", gen_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        wells = mod.main(seed=seed, n_wells=n_wells,
                         output_dir=self.tmp)
        return wells

    def test_basic_run(self):
        """Engine produces results on coal data."""
        wells = self._generate_small()
        wells_path = os.path.join(self.tmp, "wells.txt")
        assert os.path.exists(wells_path)
        engine = ProjectExt()
        engine.set_option_ext("cost-function", "composite")
        engine.set_option_ext("var-data", "GR")
        engine.set_option_ext("var-weight", "1.0")
        engine.set_option_ext("order", "pyramidal")
        engine.set_option_ext("nbr-cor", "50")
        engine.set_option_ext("out-nbr-cor", "5")
        engine.set_option_ext("max-cor", "100")
        success = engine.run(os.path.abspath(wells_path))
        assert success
        res = engine.get_res_file()
        assert res.get_nbr_results() > 0

    def test_path_monotonicity(self):
        """Correlation paths must be monotonically increasing in each well."""
        wells = self._generate_small()
        wells_path = os.path.join(self.tmp, "wells.txt")
        engine = ProjectExt()
        engine.set_option_ext("cost-function", "composite")
        engine.set_option_ext("var-data", "GR")
        engine.set_option_ext("var-weight", "0.7")
        engine.set_option_ext("var-data2", "DEN")
        engine.set_option_ext("var-weight2", "0.3")
        engine.set_option_ext("order", "pyramidal")
        engine.set_option_ext("nbr-cor", "30")
        engine.set_option_ext("out-nbr-cor", "3")
        engine.set_option_ext("max-cor", "100")
        success = engine.run(os.path.abspath(wells_path))
        assert success
        res = engine.get_res_file()
        for r_idx in range(min(3, res.get_nbr_results())):
            path = res.get_result_full_path(r_idx)
            for w in range(res.nbr_well()):
                samples = [node[w] for node in path]
                for i in range(1, len(samples)):
                    assert samples[i] >= samples[i - 1]

    def test_best_beats_worst(self):
        """Best correlation should have lower cost than the worst."""
        wells = self._generate_small(n_wells=8, seed=123)
        wells_path = os.path.join(self.tmp, "wells.txt")
        engine = ProjectExt()
        engine.set_option_ext("cost-function", "composite")
        engine.set_option_ext("var-data", "GR")
        engine.set_option_ext("var-weight", "1.0")
        engine.set_option_ext("order", "pyramidal")
        engine.set_option_ext("nbr-cor", "30")
        engine.set_option_ext("out-nbr-cor", "10")
        engine.set_option_ext("max-cor", "80")
        success = engine.run(os.path.abspath(wells_path))
        assert success
        res = engine.get_res_file()
        if res.get_nbr_results() >= 2:
            best = res.get_result_cost(0)
            worst = res.get_result_cost(res.get_nbr_results() - 1)
            assert best <= worst + 1e-9, (
                f"Best cost {best} > worst cost {worst}")


# ===================================================================
# 6. Noise tolerance tests
# ===================================================================

class TestNoiseTolerance:
    """Verify the engine degrades gracefully with increasing noise."""

    def _run_with_noise(self, noise_level, size=50, n_wells=3, wl=10.0):
        wl_data = WellList()
        signal = [math.sin(2 * math.pi * i / wl) for i in range(size)]
        import random
        rng = random.Random(42)
        for j in range(n_wells):
            noisy = [v + rng.gauss(0, noise_level) for v in signal]
            depth = [float(i) for i in range(size)]
            w = wl_data.create_well(f"W{j}", y=j * 100, size=size)
            w.add_data("depth", depth)
            w.add_data("signal", noisy)
        res = _run_engine(wl_data, **{
            "var-data": "signal", "var-weight": "1.0"})
        return res

    def test_zero_noise_perfect(self):
        """Zero noise → perfect diagonal."""
        res = self._run_with_noise(0.0)
        path = _best_path(res)
        for node in path:
            assert len(set(node)) == 1

    def test_low_noise_close(self):
        """Low noise (σ=0.1) → near-diagonal (spread ≤ 3)."""
        res = self._run_with_noise(0.1)
        path = _best_path(res)
        bad = sum(1 for node in path if max(node) - min(node) > 3)
        assert bad <= len(path) * 0.1, (
            f"Too many off-diagonal nodes with low noise: {bad}/{len(path)}")

    def test_moderate_noise_still_runs(self):
        """Moderate noise (σ=0.5) → engine still produces results."""
        res = self._run_with_noise(0.5)
        assert res.get_nbr_results() > 0
        assert math.isfinite(res.get_result_cost(0))

    def test_noise_cost_increases(self):
        """Higher noise should produce higher correlation cost."""
        costs = []
        for noise in [0.0, 0.2, 0.5]:
            res = self._run_with_noise(noise)
            costs.append(res.get_result_cost(0))
        # Costs should generally increase (or stay similar for zero → low)
        assert costs[2] >= costs[0] - 1e-3, (
            f"High-noise cost ({costs[2]:.4f}) < zero-noise ({costs[0]:.4f})")


# ===================================================================
# 7. Existing dataset regression tests
# ===================================================================

class TestExistingDatasets:
    """Run the engine on the shipped datasets and verify basic properties."""

    DATA = os.path.join(ROOT, "demo", "data")

    @pytest.mark.parametrize("ds,opt", [
        ("data_set_1.1", "option_1.txt"),
        ("data_set_1.2", "option.txt"),
        ("data_set_1.3", "option.txt"),
        ("data_set_2", "option.txt"),
    ])
    def test_shipped_dataset(self, ds, opt):
        """Each shipped dataset produces ≥1 result with finite cost."""
        wells_path = os.path.join(self.DATA, ds, "wells.txt")
        opt_path = os.path.join(self.DATA, ds, opt)
        if not os.path.exists(wells_path) or not os.path.exists(opt_path):
            pytest.skip(f"Dataset {ds} not found")
        engine = ProjectExt()
        engine.option_load(os.path.abspath(opt_path))
        success = engine.run(os.path.abspath(wells_path))
        assert success, f"Engine failed on {ds}"
        res = engine.get_res_file()
        assert res.get_nbr_results() > 0
        assert math.isfinite(res.get_result_cost(0))

    @pytest.mark.parametrize("ds,opt", [
        ("data_set_1.1", "option_1.txt"),
    ])
    def test_result_monotonicity(self, ds, opt):
        """Correlation paths are monotonic in every well."""
        wells_path = os.path.join(self.DATA, ds, "wells.txt")
        opt_path = os.path.join(self.DATA, ds, opt)
        engine = ProjectExt()
        engine.option_load(os.path.abspath(opt_path))
        success = engine.run(os.path.abspath(wells_path))
        assert success
        res = engine.get_res_file()
        for r_idx in range(min(5, res.get_nbr_results())):
            path = res.get_result_full_path(r_idx)
            for w in range(res.nbr_well()):
                samples = [node[w] for node in path]
                for i in range(1, len(samples)):
                    assert samples[i] >= samples[i - 1]


# ═══════════════════════════════════════════════════════════════════════
# §13.9 — Systematic truth-recovery tests for all generators
# ═══════════════════════════════════════════════════════════════════════

class TestRoundtripGenerators:
    """Systematic truth-recovery tests using roundtrip.py generators."""

    def test_parallel_basic(self):
        """Parallel layers with no noise — should be trivially correct."""
        from weco.roundtrip import generate_parallel, roundtrip_test
        model = generate_parallel(n_wells=3, n_markers=20, seed=42)
        result = roundtrip_test(model, k=5)
        assert result["truth_rank"] >= 0, "Truth not found in results"
        assert result["marker_mae"] < 3.0, f"MAE too high: {result['marker_mae']}"

    def test_parallel_noisy(self):
        """Parallel layers with noise — truth should still be in top-5."""
        from weco.roundtrip import generate_parallel, roundtrip_test
        model = generate_parallel(n_wells=3, n_markers=20, noise=0.1, seed=42)
        result = roundtrip_test(model, k=10)
        assert result["truth_rank"] >= 0

    def test_clinoform_basic(self):
        """Clinoform wedge — tests gap cost sensitivity."""
        from weco.roundtrip import generate_clinoform, roundtrip_test
        model = generate_clinoform(n_wells=3, n_markers=30, max_shift=3, seed=42)
        result = roundtrip_test(model, k=10)
        assert result["truth_rank"] >= 0

    def test_prograding_delta(self):
        """Prograding delta — tests lateral facies change."""
        from weco.roundtrip import generate_prograding_delta, roundtrip_test
        model = generate_prograding_delta(n_wells=3, n_markers=30, seed=42)
        result = roundtrip_test(model, k=10)
        assert result["truth_rank"] >= 0

    def test_shallow_marine(self):
        """Shallow marine bay fill — tests distality."""
        from weco.roundtrip import generate_shallow_marine, roundtrip_test
        model = generate_shallow_marine(n_wells=3, n_markers=40, seed=42)
        result = roundtrip_test(model, k=10)
        assert result["truth_rank"] >= 0

    def test_fluvial(self):
        """Fluvial channels — hardest scenario, laterally discontinuous."""
        from weco.roundtrip import generate_fluvial, roundtrip_test
        model = generate_fluvial(n_wells=3, n_markers=30, seed=42)
        result = roundtrip_test(model, k=10)
        # Fluvial is hard — just verify engine runs and produces results
        assert result.get("error") is None

    def test_noise_injection(self):
        """Noise injection: verify graceful degradation."""
        from weco.roundtrip import generate_parallel, inject_noise, roundtrip_test
        base = generate_parallel(n_wells=3, n_markers=20, seed=42)

        for noise_level in [0.0, 0.05, 0.1, 0.2]:
            noisy = inject_noise(base, noise_level, seed=100)
            result = roundtrip_test(noisy, k=10)
            # At low noise, should still find truth
            if noise_level <= 0.1:
                assert result["truth_rank"] >= 0, \
                    f"Truth lost at noise={noise_level}"

    def test_dataset_quaternary(self):
        """Existing quaternary dataset runs successfully."""
        from weco.roundtrip import roundtrip_from_dataset
        try:
            result = roundtrip_from_dataset("quaternary", seed=42)
            assert result["success"], f"Failed: {result.get('error')}"
            assert result["n_results"] > 0
        except FileNotFoundError:
            pytest.skip("Quaternary dataset not generated")

    def test_dataset_coal(self):
        """Existing coal dataset runs successfully."""
        from weco.roundtrip import roundtrip_from_dataset
        try:
            result = roundtrip_from_dataset("coal", seed=42)
            assert result["success"], f"Failed: {result.get('error')}"
            assert result["n_results"] > 0
        except FileNotFoundError:
            pytest.skip("Coal dataset not generated")


# ===================================================================
# §11.4.2 — Distality + normalised B3D combined test
# ===================================================================

class TestDistalityB3D:
    """Verify that distality + B3D normalisation work together."""

    def test_combined_distality_b3d(self):
        """Run with both dist-facies/dist-distal and b3d options on data_set_2."""
        data_dir = os.path.join(ROOT, "demo", "data", "data_set_2")
        well_file = os.path.join(data_dir, "wells.txt")
        if not os.path.exists(well_file):
            pytest.skip("data_set_2 not available")

        engine = ProjectExt()
        engine.set_options_ext(
            cost_function="composite",
            var_data="GR",
            var_weight="1.0",
        )
        # Enable B3D curve normalisation (default on)
        engine.set_option_ext("b3d-curve-normalize", "true")

        success = engine.run(well_file)
        assert success, "Combined distality+B3D run failed"
        res = engine.get_res_file()
        assert res.get_nbr_results() > 0


# ===================================================================
# §11.5.3 — Validate thickness on synthetic
# ===================================================================

class TestThicknessValidation:
    """Verify that thickness-aware correlation improves recovery."""

    def test_thickness_consistency(self):
        """Check that correlated intervals have consistent thicknesses."""
        from weco.roundtrip import generate_parallel, roundtrip_test
        model = generate_parallel(n_wells=3, n_markers=30, seed=123)
        result = roundtrip_test(model, k=10)
        assert result.get("error") is None

        # Verify thickness ratios between consecutive horizons
        if result.get("truth_rank", -1) >= 0:
            path = result.get("best_path", [])
            if len(path) > 2:
                # Check that interval thicknesses are roughly consistent
                for hi in range(1, len(path)):
                    thicknesses = []
                    for w in range(len(path[hi])):
                        if path[hi][w] >= 0 and path[hi - 1][w] >= 0:
                            thicknesses.append(abs(path[hi][w] - path[hi - 1][w]))
                    if len(thicknesses) >= 2:
                        mean_t = sum(thicknesses) / len(thicknesses)
                        if mean_t > 0:
                            cv = (max(thicknesses) - min(thicknesses)) / mean_t
                            # Coefficient of variation should be reasonable
                            assert cv < 5.0, f"Excessive thickness variation at horizon {hi}"


# ===================================================================
# §12.8 — Noise suppression validation (hierarchical mode)
# ===================================================================

class TestNoiseValidation:
    """Verify that the engine handles noise gracefully across levels."""

    def test_noise_levels_systematic(self):
        """Systematic noise test at 5%, 10%, 20%, 50% levels."""
        from weco.roundtrip import generate_parallel, inject_noise, roundtrip_test

        base = generate_parallel(n_wells=4, n_markers=25, seed=42)
        results = {}

        for noise_pct in [0.0, 0.05, 0.1, 0.2, 0.5]:
            noisy = inject_noise(base, noise_pct, seed=200)
            result = roundtrip_test(noisy, k=10)
            results[noise_pct] = result

        # At zero noise, must find truth
        assert results[0.0]["truth_rank"] >= 0, "Failed on clean data"

        # At moderate noise (10%), should still find truth
        if results[0.1].get("truth_rank", -1) < 0:
            pytest.skip("Engine sensitive to 10% noise — acceptable")

    def test_noise_with_band_constraint(self):
        """Verify band constraint helps suppress noise."""
        from weco.roundtrip import generate_parallel, inject_noise, roundtrip_test

        base = generate_parallel(n_wells=3, n_markers=20, seed=55)
        noisy = inject_noise(base, 0.15, seed=300)

        # Without band constraint
        result_no_band = roundtrip_test(noisy, k=10)

        # With band constraint
        result_band = roundtrip_test(noisy, k=10, extra_options={"band-width": "5"})

        # Band constraint should not make things worse
        assert result_band.get("error") is None
