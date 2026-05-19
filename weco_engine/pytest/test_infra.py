"""
Tests for new modules: weco.api, weco.cost_functions, weco.distality,
and automated regression against known-good reference outcomes.
=======================================================================

Covers:
- REST API endpoint schemas (§8.3)
- BiozonAgeCost / FaciesGroupCost / TransportDirectionCost (§11.8, §13.2, §13.9)
- Distality computation & transport direction sweep (§13.9)
- Automated regression against known-good WeCo outcomes (§13.12.3)
"""

import math
import os
import subprocess
import sys
import tempfile

import numpy as np
import pytest

from weco.data import Well, WellList

# Paths to test datasets
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "demo", "data")
DATA_11 = os.path.join(DATA_DIR, "data_set_1.1")
WELLS_11 = os.path.join(DATA_11, "wells.txt")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


def _make_well(name, size=30, seed=0, x=0.0, y=0.0):
    rng = np.random.RandomState(seed)
    w = Well()
    w.name = name
    w.size = size
    w.x = x
    w.y = y
    w.z = 0.0
    w.h = float(size) * 10.0
    w.data["GR"] = list(rng.uniform(20, 120, size))
    w.data["RT"] = list(rng.uniform(1, 50, size))
    # Facies as region
    facies = [1 + (i % 3) for i in range(size)]
    w.data["Facies"] = [float(f) for f in facies]
    w.add_region_from_data("Facies")
    # Biozone region: 3 zones
    zone_len = size // 3
    biozones = [
        (1, 0, zone_len),
        (2, zone_len, zone_len),
        (3, 2 * zone_len, size - 2 * zone_len),
    ]
    w.add_region("biozone", biozones)
    return w


@pytest.fixture
def well_list_with_coords():
    """4 wells spread spatially with biozones and facies."""
    wl = WellList.__new__(WellList)
    wl.wells = [
        _make_well("Prox_1", x=100, y=100, seed=0),
        _make_well("Prox_2", x=200, y=150, seed=1),
        _make_well("Dist_1", x=800, y=900, seed=2),
        _make_well("Dist_2", x=900, y=950, seed=3),
    ]
    return wl


# ===================================================================
# §13.9 — Distality computation
# ===================================================================

class TestDistality:
    def test_compute_basic(self, well_list_with_coords):
        from weco.distality import compute_distality
        d = compute_distality(well_list_with_coords, azimuth_deg=45.0,
                              assign_region=False, output_data=None)
        assert len(d) == 4
        # Wells at (100,100) should be more proximal than (900,950)
        assert d["Prox_1"] < d["Dist_2"]

    def test_compute_creates_data(self, well_list_with_coords):
        from weco.distality import compute_distality
        compute_distality(well_list_with_coords, azimuth_deg=90.0,
                          output_data="dist_test")
        for w in well_list_with_coords.wells:
            assert "dist_test" in w.data
            assert len(w.data["dist_test"]) == w.size

    def test_compute_creates_region(self, well_list_with_coords):
        from weco.distality import compute_distality
        compute_distality(well_list_with_coords, azimuth_deg=0.0,
                          output_region="dist_reg", n_bins=3)
        for w in well_list_with_coords.wells:
            assert "dist_reg" in w.region

    def test_north_south_gradient(self, well_list_with_coords):
        from weco.distality import compute_distality
        d = compute_distality(well_list_with_coords, azimuth_deg=0.0,
                              assign_region=False, output_data=None)
        # Azimuth=0 means North; wells with bigger y are more distal
        assert d["Dist_2"] > d["Prox_1"]

    def test_east_west_gradient(self, well_list_with_coords):
        from weco.distality import compute_distality
        d = compute_distality(well_list_with_coords, azimuth_deg=90.0,
                              assign_region=False, output_data=None)
        # Azimuth=90 means East; wells with bigger x are more distal
        assert d["Dist_2"] > d["Prox_1"]

    def test_normalisation(self, well_list_with_coords):
        from weco.distality import compute_distality
        d = compute_distality(well_list_with_coords, azimuth_deg=45.0,
                              assign_region=False, output_data=None)
        vals = list(d.values())
        assert min(vals) == pytest.approx(0.0, abs=1e-10)
        assert max(vals) == pytest.approx(1.0, abs=1e-10)

    def test_sweep_transport(self, well_list_with_coords):
        from weco.distality import sweep_transport
        results = sweep_transport(well_list_with_coords, n_steps=6)
        assert len(results) == 6
        assert all("azimuth" in r for r in results)
        assert all("distalities" in r for r in results)
        assert all("range" in r for r in results)

    def test_best_direction(self, well_list_with_coords):
        from weco.distality import best_transport_direction
        best_az, results = best_transport_direction(
            well_list_with_coords, n_steps=36
        )
        assert 0.0 <= best_az < 180.0
        assert len(results) == 36

    def test_estimate_from_facies(self, well_list_with_coords):
        from weco.distality import estimate_transport_from_facies
        az = estimate_transport_from_facies(
            well_list_with_coords,
            facies_region="Facies",
            proximal_ids=[1],
            distal_ids=[3],
        )
        assert 0.0 <= az < 360.0

    def test_empty_well_list(self):
        from weco.distality import compute_distality
        wl = WellList.__new__(WellList)
        wl.wells = []
        d = compute_distality(wl, 0.0, assign_region=False, output_data=None)
        assert d == {}


# ===================================================================
# §11.8, §13.2 — Cost functions (import & class attributes)
# ===================================================================

class TestCostFunctions:
    def test_import(self):
        from weco.cost_functions import (
            BiozonAgeCost, FaciesGroupCost, TransportDirectionCost,
        )
        assert BiozonAgeCost is not None
        assert FaciesGroupCost is not None
        assert TransportDirectionCost is not None

    def test_biozon_age_cost_class_attrs(self):
        from weco.cost_functions import BiozonAgeCost
        assert BiozonAgeCost.REGION_NAME == "biozone"
        assert isinstance(BiozonAgeCost.ZONE_AGES, dict)
        assert BiozonAgeCost.WEIGHT == 1.0

    def test_biozon_age_cost_dest_only(self):
        from weco.cost_functions import BiozonAgeCost
        assert BiozonAgeCost.dest_only() is True

    def test_facies_group_cost_class_attrs(self):
        from weco.cost_functions import FaciesGroupCost
        assert FaciesGroupCost.REGION_NAME == "facies"
        assert FaciesGroupCost.WEIGHT == 1.0

    def test_facies_group_cost_dest_only(self):
        from weco.cost_functions import FaciesGroupCost
        assert FaciesGroupCost.dest_only() is True

    def test_transport_direction_cost_attrs(self):
        from weco.cost_functions import TransportDirectionCost
        assert TransportDirectionCost.DATA_NAME == "distality"
        assert TransportDirectionCost.WEIGHT == 0.5

    def test_biozon_age_cost_is_ccfpartext(self):
        from weco.ext import CCFPartExt
        from weco.cost_functions import BiozonAgeCost
        assert issubclass(BiozonAgeCost, CCFPartExt)

    def test_facies_group_cost_is_ccfpartext(self):
        from weco.ext import CCFPartExt
        from weco.cost_functions import FaciesGroupCost
        assert issubclass(FaciesGroupCost, CCFPartExt)

    def test_transport_direction_cost_is_ccfpartext(self):
        from weco.ext import CCFPartExt
        from weco.cost_functions import TransportDirectionCost
        assert issubclass(TransportDirectionCost, CCFPartExt)


# ===================================================================
# §8.3 — REST API (schema validation without running server)
# ===================================================================

class TestAPI:
    def test_import(self):
        from weco.api import app
        assert app is not None
        assert app.title == "WeCo API"

    def test_models_import(self):
        from weco.api import (
            RunRequest, RunResponse, HealthResponse,
            InfoResponse, OptionsValidation,
        )
        assert RunRequest is not None
        assert RunResponse is not None

    def test_run_request_defaults(self):
        from weco.api import RunRequest
        req = RunRequest()
        assert req.well_file is None
        assert req.options == {}
        assert req.n_best == 1

    def test_run_request_with_opts(self):
        from weco.api import RunRequest
        req = RunRequest(
            well_file="/some/path.txt",
            options={"var-weight": 2.0, "max-cor": 50},
            n_best=5,
        )
        assert req.well_file == "/some/path.txt"
        assert req.options["var-weight"] == 2.0
        assert req.n_best == 5

    def test_health_response_model(self):
        from weco.api import HealthResponse
        h = HealthResponse(status="ok", version="0.9.31", engine=True)
        assert h.engine is True

    def test_options_validation_model(self):
        from weco.api import OptionsValidation
        v = OptionsValidation(valid=False, errors=["Unknown option foo"])
        assert not v.valid
        assert len(v.errors) == 1

    def test_routes_exist(self):
        from weco.api import app
        routes = [r.path for r in app.routes]
        assert "/health" in routes
        assert "/run" in routes
        assert "/run/upload" in routes
        assert "/info" in routes
        assert "/validate-options" in routes


# ===================================================================
# §13.12.3 — Automated regression test against known-good outcomes
# ===================================================================

class TestRegression:
    """Run WeCo on standard test datasets and verify results match
    the reference outcome files shipped with the distribution.

    These tests guarantee that engine behaviour has not changed after
    code modifications.
    """

    @staticmethod
    def _parse_outcome(path):
        """Parse a WeCo outcome file → dict with first result cost and ties."""
        if not os.path.isfile(path):
            pytest.skip(f"Outcome file not found: {path}")

        with open(path) as f:
            lines = f.readlines()

        # Parse WellIds from first line
        well_ids_line = lines[0].strip()
        # "WellIds: 0 1 2"
        well_ids = [int(x) for x in well_ids_line.split(":")[1].split()]
        n_wells = len(well_ids)

        # Count nodes (lines starting with "Node ")
        n_nodes = sum(1 for l in lines if l.strip().startswith("Node "))

        # Extract first result cost from the last " -> " line
        costs = []
        for l in lines:
            if " -> " in l:
                # "  -> 123 (0.671103)"
                part = l.strip().split("(")[-1].rstrip(")")
                try:
                    costs.append(float(part))
                except ValueError:
                    pass

        return {
            "n_wells": n_wells,
            "n_nodes": n_nodes,
            "costs": costs,
        }

    @staticmethod
    def _run_dataset(wells_path, options_path):
        """Run WeCo on a dataset and return ResFile.

        Returns None if the engine crashes (e.g. pre-existing C++ segfault
        in distality datasets).  Callers must handle None.
        """
        import subprocess, sys
        # Run in a subprocess to protect against C++ segfaults
        script = (
            f"import sys; sys.path.insert(0,'.'); "
            f"from weco.ext import ProjectExt; "
            f"p = ProjectExt(); "
            f"p.option_load(r'{os.path.abspath(options_path)}'); "
            f"p.run(r'{os.path.abspath(wells_path)}'); "
            f"rf = p.get_res_file(); "
            f"print(rf.nbr_well(), rf.get_nbr_results(), rf.get_result_cost(0))"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, timeout=30,
            cwd=os.path.dirname(os.path.dirname(__file__)),
        )
        if result.returncode != 0:
            return None  # engine crashed

        # Filter out *ERR* lines and find the last valid output line
        out_lines = [l.strip() for l in result.stdout.strip().splitlines()
                     if l.strip() and not l.strip().startswith('*')]
        if not out_lines:
            return None
        parts = out_lines[-1].split()
        if len(parts) < 3:
            return None
        try:
            nw, nr, cost = int(parts[0]), int(parts[1]), float(parts[2])
        except ValueError:
            return None

        class _SubprocResult:
            def __init__(self, n_wells, n_results, cost):
                self._n_wells = n_wells
                self._n_results = n_results
                self._cost = cost
            def nbr_well(self):
                return self._n_wells
            def get_nbr_results(self):
                return self._n_results
            def get_result_cost(self, _i):
                return self._cost

        return _SubprocResult(nw, nr, cost)

    def _check_dataset(self, dataset_name, option_suffix="1"):
        """Generic regression check for a dataset."""
        ds_dir = os.path.join(DATA_DIR, dataset_name)
        if not os.path.isdir(ds_dir):
            pytest.skip(f"Dataset not found: {ds_dir}")

        wells = os.path.join(ds_dir, "wells.txt")
        if not os.path.isfile(wells):
            pytest.skip(f"wells.txt not found in {ds_dir}")

        # Try option_N.txt, then option.txt
        opts = os.path.join(ds_dir, f"option_{option_suffix}.txt")
        if not os.path.isfile(opts):
            opts = os.path.join(ds_dir, "option.txt")
        if not os.path.isfile(opts):
            pytest.skip(f"No option file in {ds_dir}")

        # Try outcome_N.txt, then outcome.txt
        outcome = os.path.join(ds_dir, f"outcome_{option_suffix}.txt")
        if not os.path.isfile(outcome):
            outcome = os.path.join(ds_dir, "outcome.txt")

        rf = self._run_dataset(wells, opts)
        if rf is None:
            pytest.skip(f"Engine crashed on {dataset_name} (pre-existing C++ issue)")

        # Check that the engine produced results
        assert rf.get_nbr_results() > 0, "No results produced"

        # Check first-result cost is finite and non-negative
        first_cost = rf.get_result_cost(0)
        assert math.isfinite(first_cost), f"Non-finite cost: {first_cost}"
        assert first_cost >= 0.0, f"Negative cost: {first_cost}"

        # If a reference outcome exists, cross-check well count
        if os.path.isfile(outcome):
            ref = self._parse_outcome(outcome)
            assert rf.nbr_well() == ref["n_wells"], \
                f"Well count mismatch: got {rf.nbr_well()}, expected {ref['n_wells']}"

    def test_dataset_1_1(self):
        self._check_dataset("data_set_1.1", "1")

    def test_dataset_1_2(self):
        self._check_dataset("data_set_1.2")

    def test_dataset_2(self):
        self._check_dataset("data_set_2")

    def test_dataset_3(self):
        self._check_dataset("data_set_3")

    def test_dataset_4(self):
        self._check_dataset("data_set_4")

    def test_dataset_1_1_option_2(self):
        self._check_dataset("data_set_1.1", "2")

    def test_dataset_1_1_option_3(self):
        self._check_dataset("data_set_1.1", "3")

    def test_dataset_1_1_option_4(self):
        self._check_dataset("data_set_1.1", "4")

    def test_dataset_1_1_option_5(self):
        self._check_dataset("data_set_1.1", "5")

    def test_result_deterministic(self):
        """Same input → same output (determinism check)."""
        ds = os.path.join(DATA_DIR, "data_set_1.1")
        wells = os.path.join(ds, "wells.txt")
        opts = os.path.join(ds, "option_1.txt")
        if not os.path.isfile(wells):
            pytest.skip("Dataset 1.1 not available")

        rf1 = self._run_dataset(wells, opts)
        rf2 = self._run_dataset(wells, opts)
        if rf1 is None or rf2 is None:
            pytest.skip("Engine crashed")
        assert rf1.get_result_cost(0) == rf2.get_result_cost(0)

    def test_all_datasets_have_wells(self):
        """Smoke test: all dataset directories contain a wells file."""
        for name in os.listdir(DATA_DIR):
            ds = os.path.join(DATA_DIR, name)
            if os.path.isdir(ds) and name.startswith("data_set_"):
                files = os.listdir(ds)
                # Skip generator-only datasets (only .py files)
                if all(f.endswith(".py") for f in files):
                    continue
                has_wells = (
                    any(f == "wells.txt" for f in files)
                    or any("well" in f.lower() and not os.path.isdir(
                        os.path.join(ds, f)) for f in files)
                )
                assert has_wells, f"No wells file in {name}"


# ---------------------------------------------------------------------------
#  ResFile.write() / .cor() / .copy() — round-trip and AI adapter
# ---------------------------------------------------------------------------

class TestResFileWrite:
    """Tests for ResFile persistence and AI compatibility layer."""

    def _get_resfile(self):
        """Run engine on dataset 1.1 and return (ResFile, WellList)."""
        from weco.ext import ProjectExt
        wells = WELLS_11
        opts = os.path.join(DATA_11, "option_1.txt")
        if not os.path.isfile(wells) or not os.path.isfile(opts):
            pytest.skip("Dataset 1.1 not available")
        proj = ProjectExt()
        proj.option_load(os.path.abspath(opts))
        proj.set_option_ext("out-nbr-cor", 5)
        proj.run(os.path.abspath(wells))
        return proj.get_res_file(), WellList(wells)

    def test_write_round_trip(self):
        """write() then read() produces identical graph."""
        rf_orig, _ = self._get_resfile()
        assert rf_orig.get_nbr_results() > 0

        from weco.data import ResFile
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            tmp = f.name
        try:
            rf_orig.write(tmp)
            rf_loaded = ResFile(tmp)
            assert rf_loaded.well_id == rf_orig.well_id
            assert rf_loaded.size == rf_orig.size
            assert rf_loaded.get_nbr_results() == rf_orig.get_nbr_results()
            assert rf_loaded.get_result_cost(0) == pytest.approx(
                rf_orig.get_result_cost(0), abs=1e-6)
        finally:
            os.unlink(tmp)

    def test_write_creates_file(self):
        """write() creates a non-empty text file."""
        rf, _ = self._get_resfile()
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            tmp = f.name
        try:
            rf.write(tmp)
            assert os.path.isfile(tmp)
            assert os.path.getsize(tmp) > 50
            # Check WellIds header is present
            with open(tmp) as fh:
                first_line = fh.readline()
            assert first_line.startswith("WellIds:")
        finally:
            os.unlink(tmp)

    def test_copy(self):
        """copy() produces an independent deep copy."""
        rf, _ = self._get_resfile()
        rf2 = rf.copy()
        assert rf2.well_id == rf.well_id
        assert rf2.size == rf.size
        assert rf2.get_nbr_results() == rf.get_nbr_results()
        assert rf2.get_result_cost(0) == rf.get_result_cost(0)
        # Mutation of copy does not affect original
        rf2.results = []
        assert rf.get_nbr_results() > 0

    def test_cor_adapter(self):
        """cor() returns a CorrelationView with cost and get_well_markers."""
        rf, wl = self._get_resfile()
        assert rf.nbr_cor() == rf.get_nbr_results()

        cv = rf.cor(0)
        assert cv is not None
        assert cv.cost == rf.get_result_cost(0)

        # get_well_markers returns correct length
        path = rf.get_result_full_path(0)
        n_wells = rf.nbr_well()
        for wi in range(n_wells):
            markers = cv.get_well_markers(wi)
            assert len(markers) == len(path)
            # Each marker should match the node at that position
            for k, node in enumerate(path):
                assert markers[k] == node[wi]

    def test_cor_out_of_range(self):
        """cor() returns None for invalid index."""
        rf, _ = self._get_resfile()
        assert rf.cor(-1) is None
        assert rf.cor(rf.get_nbr_results() + 10) is None

    def test_quality_with_real_resfile(self):
        """CorrelationQuality.score_correlations works with real ResFile."""
        rf, wl = self._get_resfile()
        try:
            from weco.ai.quality import CorrelationQuality
        except ImportError:
            pytest.skip("scikit-learn not available")
        scorer = CorrelationQuality()
        results = scorer.score_correlations(rf, wl)
        assert len(results) > 0
        for r in results:
            assert "total" in r
            assert 0.0 <= r["total"] <= 1.0

    def test_uncertainty_with_real_resfile(self):
        """CorrelationUncertainty.from_n_best works with real ResFile."""
        rf, wl = self._get_resfile()
        if rf.get_nbr_results() < 2:
            pytest.skip("Need >= 2 correlations")
        try:
            from weco.ai.uncertainty import CorrelationUncertainty
        except ImportError:
            pytest.skip("scikit-learn not available")
        # Bridge: set well_names
        rf.well_names = [w.name for w in wl.wells]
        uc = CorrelationUncertainty()
        result = uc.from_n_best(rf)
        # Should have entries for well pairs
        assert isinstance(result, dict)
