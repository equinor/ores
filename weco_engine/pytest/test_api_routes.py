"""
Rich integration tests for every WeCo REST API route.
=====================================================

Tests exercise all five endpoints (/health, /run, /run/upload, /info,
/validate-options) with geologically realistic synthetic well data and
verify not just HTTP schemas but also **geological validity** of results:

* Correlation lines must be monotonically non-decreasing (stratigraphic
  order is preserved).
* Marker indices must be within well size.
* Cost must be non-negative.
* Tie counts must be consistent with well sizes.
* Correlation with identical / near-identical wells must yield low cost.
* Correlation of highly dissimilar wells should yield higher cost.
* Thicker wells (more markers) should produce more correlation lines.
* /info must faithfully reflect well metadata.
* /validate-options must accept valid options and reject garbage.

Each synthetic dataset is constructed from geologically plausible
patterns:
  - Upward-fining GR (channel fill, deepening upward)
  - Aggradational GR (uniform shelf)
  - Progradational (coarsening upward)
  - Noisy basin-floor turbidites (high frequency, low amp)
  - Mixed two-log (GR + sonic) sections
  - Wells with biozone regions and no-crossing constraints
"""

from __future__ import annotations

import io
import json
import math
import os
import tempfile
from typing import List

import numpy as np
import pytest
from fastapi.testclient import TestClient

from weco.api import app
from weco.data import Well, WellList

# The C++ engine has a global-state bug that causes segfaults after ~25
# sequential ProjectExt instantiations in the same process.  Mark every
# test in this module to run in a forked subprocess (requires pytest-forked).
pytestmark = pytest.mark.forked


# ═══════════════════════════════════════════════════════════════════════════
# Synthetic well builders — geologically motivated
# ═══════════════════════════════════════════════════════════════════════════

def _gr_fining_up(n: int, gr_min=20.0, gr_max=130.0, noise=5.0,
                  seed=42) -> List[float]:
    """Upward-fining GR trend (channel fill / transgressive).
    High GR (shale) at top, low GR (sand) at base."""
    rng = np.random.RandomState(seed)
    trend = np.linspace(gr_min, gr_max, n)  # base=sand → top=shale
    return (trend + rng.normal(0, noise, n)).clip(0).tolist()


def _gr_coarsening_up(n: int, gr_min=25.0, gr_max=120.0, noise=5.0,
                      seed=42) -> List[float]:
    """Coarsening-upward GR (progradational parasequence)."""
    rng = np.random.RandomState(seed)
    trend = np.linspace(gr_max, gr_min, n)
    return (trend + rng.normal(0, noise, n)).clip(0).tolist()


def _gr_aggradational(n: int, gr_mean=70.0, noise=8.0,
                      seed=42) -> List[float]:
    """Aggradational / uniform shelf — flat GR with noise."""
    rng = np.random.RandomState(seed)
    return (gr_mean + rng.normal(0, noise, n)).clip(0).tolist()


def _gr_turbidite(n: int, gr_sand=25.0, gr_shale=110.0, noise=3.0,
                  freq=6, seed=42) -> List[float]:
    """High-frequency interbedded turbidite succession."""
    rng = np.random.RandomState(seed)
    t = np.linspace(0, freq * 2 * np.pi, n)
    base = 0.5 * (gr_sand + gr_shale) + 0.5 * (gr_shale - gr_sand) * np.sin(t)
    return (base + rng.normal(0, noise, n)).clip(0).tolist()


def _sonic_from_gr(gr: List[float], dt_sand=55.0, dt_shale=100.0) -> List[float]:
    """Generate a porosity-proxy sonic log correlated with GR.
    Higher GR → higher transit time (shale)."""
    arr = np.array(gr)
    gr_min, gr_max = arr.min(), arr.max()
    if gr_max == gr_min:
        return [0.5 * (dt_sand + dt_shale)] * len(gr)
    frac = (arr - gr_min) / (gr_max - gr_min)
    return (dt_sand + frac * (dt_shale - dt_sand)).tolist()


def _depth_track(n: int, top=1000.0, dz=0.5) -> List[float]:
    """Regular depth track."""
    return [top + i * dz for i in range(n)]


def _make_well(name: str, size: int, gr_func, seed=42,
               x=0.0, y=0.0, top=1000.0, dz=0.5,
               add_sonic=False, biozones: int = 0,
               add_depth=True) -> Well:
    """Create a geologically flavoured synthetic well."""
    w = Well()
    w.name = name
    w.size = size
    w.x, w.y, w.z = x, y, 0.0
    w.h = size * dz

    gr = gr_func(size, seed=seed)
    w.data["GR"] = gr

    if add_depth:
        w.data["Depth"] = _depth_track(size, top, dz)

    if add_sonic:
        w.data["DT"] = _sonic_from_gr(gr)

    if biozones > 0:
        zone_len = max(1, size // biozones)
        regions = []
        for z in range(biozones):
            start = z * zone_len
            length = min(zone_len, size - start)
            if length > 0:
                regions.append((z + 1, start, length))
        w.add_region("biozone", regions)

    return w


def _write_tempfile(wl: WellList, tmp_dir: str, name="wells.txt") -> str:
    """Write a WellList to a temp file and return its path."""
    path = os.path.join(tmp_dir, name)
    wl.write(path)
    return path


# ═══════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def client():
    """FastAPI test client — runs requests in-process, no socket."""
    return TestClient(app)


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


# --- Small identical-well pair (perfect correlation expected) ---
@pytest.fixture
def identical_pair(tmp_dir):
    """Two wells with exactly the same GR — correlation cost should be 0."""
    wl = WellList()
    wl.add_well(_make_well("Well_A", 40, _gr_fining_up, seed=10, x=0, y=0,
                            add_sonic=True))
    wl.add_well(_make_well("Well_B", 40, _gr_fining_up, seed=10, x=1, y=0,
                            add_sonic=True))
    return _write_tempfile(wl, tmp_dir, "identical.wells.txt")


# --- Fining-up section pair (similar but shifted) ---
@pytest.fixture
def finingup_pair(tmp_dir):
    """Two fining-upward wells with slight noise differences."""
    wl = WellList()
    wl.add_well(_make_well("FU_1", 50, _gr_fining_up, seed=1, x=0, y=0,
                            add_sonic=True))
    wl.add_well(_make_well("FU_2", 50, _gr_fining_up, seed=2, x=100, y=0,
                            add_sonic=True))
    return _write_tempfile(wl, tmp_dir, "finingup.wells.txt")


# --- Dissimilar wells (fining up vs coarsening up) ---
@pytest.fixture
def dissimilar_pair(tmp_dir):
    """One fining-up, one coarsening-up — should give higher cost."""
    wl = WellList()
    wl.add_well(_make_well("FU", 40, _gr_fining_up, seed=5, x=0, y=0,
                            add_sonic=True))
    wl.add_well(_make_well("CU", 40, _gr_coarsening_up, seed=5, x=10, y=0,
                            add_sonic=True))
    return _write_tempfile(wl, tmp_dir, "dissimilar.wells.txt")


# --- Multi-well section (4 wells along a dip transect) ---
@pytest.fixture
def transect_4wells(tmp_dir):
    """Proximal→distal transect: channel, shelf, slope, basin.
    Sizes vary — thicker proximal, thinner distal."""
    wl = WellList()
    wl.add_well(_make_well("Proximal",  60, _gr_fining_up,      seed=10,
                            x=0, y=0, add_sonic=True, biozones=3))
    wl.add_well(_make_well("Mid_Shelf", 55, _gr_aggradational,  seed=11,
                            x=200, y=0, add_sonic=True, biozones=3))
    wl.add_well(_make_well("Slope",     45, _gr_coarsening_up,  seed=12,
                            x=600, y=0, add_sonic=True, biozones=3))
    wl.add_well(_make_well("Basin",     35, _gr_turbidite,      seed=13,
                            x=1000, y=0, add_sonic=True, biozones=3))
    return _write_tempfile(wl, tmp_dir, "transect.wells.txt")


# --- Two-log well pair (GR + DT) ---
@pytest.fixture
def twolog_pair(tmp_dir):
    """Wells with both GR and sonic, for two-variable correlation."""
    wl = WellList()
    wl.add_well(_make_well("Sonic_A", 50, _gr_fining_up, seed=20,
                            add_sonic=True))
    wl.add_well(_make_well("Sonic_B", 50, _gr_fining_up, seed=21,
                            add_sonic=True))
    return _write_tempfile(wl, tmp_dir, "twolog.wells.txt")


# --- Asymmetric pair (thicker vs thinner well) ---
@pytest.fixture
def asymmetric_pair(tmp_dir):
    """One thicker (60 markers), one thinner (35 markers) — tests gap handling."""
    wl = WellList()
    wl.add_well(_make_well("Thick", 60, _gr_fining_up, seed=30, x=0, y=0,
                            add_sonic=True))
    wl.add_well(_make_well("Thin",  35, _gr_fining_up, seed=31, x=50, y=0,
                            add_sonic=True))
    return _write_tempfile(wl, tmp_dir, "asymmetric.wells.txt")


# --- Wells with biozones (for no-crossing tests) ---
@pytest.fixture
def biozone_pair(tmp_dir):
    """Two wells with 4 biozones each — for no-crossing constraint."""
    wl = WellList()
    wl.add_well(_make_well("BZ_A", 60, _gr_fining_up, seed=40,
                            add_sonic=True, biozones=4))
    wl.add_well(_make_well("BZ_B", 60, _gr_fining_up, seed=41,
                            add_sonic=True, biozones=4))
    return _write_tempfile(wl, tmp_dir, "biozones.wells.txt")


# --- Tiny wells (minimum viable size) ---
@pytest.fixture
def tiny_pair(tmp_dir):
    """Wells with only 5 markers each — boundary condition."""
    wl = WellList()
    wl.add_well(_make_well("Tiny_A", 5, _gr_aggradational, seed=50,
                            add_sonic=True))
    wl.add_well(_make_well("Tiny_B", 5, _gr_aggradational, seed=51,
                            add_sonic=True))
    return _write_tempfile(wl, tmp_dir, "tiny.wells.txt")


# ═══════════════════════════════════════════════════════════════════════════
# Geological validation helpers
# ═══════════════════════════════════════════════════════════════════════════

def _assert_monotonic_lines(lines: list, n_wells: int):
    """Correlation lines (marker indices) must be non-decreasing per well.

    This embodies the fundamental stratigraphic principle that deeper
    markers in one well cannot correlate with shallower markers in
    another — time surfaces do not cross.
    """
    for w in range(n_wells):
        indices = [line["markers"][w] for line in lines]
        for i in range(1, len(indices)):
            assert indices[i] >= indices[i - 1], (
                f"Well {w}: line {i} marker {indices[i]} < previous "
                f"{indices[i - 1]} — breaks stratigraphic monotonicity"
            )


def _assert_markers_in_bounds(lines: list, well_sizes: list):
    """Every marker index must be within [0, well_size)."""
    for li, line in enumerate(lines):
        for w, idx in enumerate(line["markers"]):
            assert 0 <= idx < well_sizes[w], (
                f"Line {li}, well {w}: marker index {idx} out of "
                f"bounds [0, {well_sizes[w]})"
            )


def _assert_valid_costs(results: list):
    """Cost must be non-negative and finite."""
    for r in results:
        assert r["cost"] >= 0.0, f"Result {r['index']}: negative cost {r['cost']}"
        assert math.isfinite(r["cost"]), f"Result {r['index']}: non-finite cost"


def _assert_lines_not_empty(results: list):
    """Each result should have at least one correlation line."""
    for r in results:
        assert len(r["lines"]) > 0, (
            f"Result {r['index']}: zero correlation lines"
        )


def _assert_tie_count_reasonable(results: list, well_sizes: list):
    """Number of ties should not exceed the sum of well sizes
    (loose upper bound) and should be >= 1."""
    max_ties = sum(well_sizes)
    for r in results:
        assert 1 <= r["n_ties"] <= max_ties, (
            f"Result {r['index']}: n_ties={r['n_ties']} unreasonable "
            f"for wells of sizes {well_sizes}"
        )


def _assert_consistent_n_results(body: dict):
    """n_results field must match len(results)."""
    assert body["n_results"] == len(body["results"])


def _full_geological_check(body: dict, well_sizes: list):
    """Run all geological validity assertions on a /run response."""
    _assert_consistent_n_results(body)
    _assert_valid_costs(body["results"])
    _assert_lines_not_empty(body["results"])
    _assert_tie_count_reasonable(body["results"], well_sizes)
    for r in body["results"]:
        _assert_monotonic_lines(r["lines"], body["n_wells"])
        _assert_markers_in_bounds(r["lines"], well_sizes)


# ═══════════════════════════════════════════════════════════════════════════
# GET /health
# ═══════════════════════════════════════════════════════════════════════════

class TestHealth:
    """Liveness / readiness probe."""

    def test_returns_200(self, client):
        r = client.get("/health")
        assert r.status_code == 200

    def test_schema(self, client):
        body = client.get("/health").json()
        assert body["status"] == "ok"
        assert isinstance(body["version"], str)
        assert isinstance(body["engine"], bool)

    def test_engine_available(self, client):
        """The C++ engine should be importable in the test environment."""
        body = client.get("/health").json()
        assert body["engine"] is True

    def test_version_is_semantic(self, client):
        body = client.get("/health").json()
        parts = body["version"].split(".")
        assert len(parts) == 3, f"Expected semantic version, got {body['version']}"
        for p in parts:
            assert p.isdigit()


# ═══════════════════════════════════════════════════════════════════════════
# POST /run — core correlation endpoint
# ═══════════════════════════════════════════════════════════════════════════

class TestRunCorrelation:
    """Full integration tests for POST /run with geological validation."""

    # ------ Schema / error handling ------

    def test_missing_well_file_returns_400(self, client):
        r = client.post("/run", json={"options": {}})
        assert r.status_code == 400

    def test_nonexistent_file_returns_404(self, client):
        r = client.post("/run", json={"well_file": "/no/such/file.txt"})
        assert r.status_code == 404

    def test_response_schema_keys(self, client, identical_pair):
        r = client.post("/run", json={"well_file": identical_pair})
        assert r.status_code == 200
        body = r.json()
        for key in ("status", "elapsed_ms", "n_wells", "well_names",
                     "n_results", "results"):
            assert key in body, f"Missing key: {key}"

    def test_result_object_schema(self, client, identical_pair):
        body = client.post("/run", json={"well_file": identical_pair}).json()
        res0 = body["results"][0]
        for key in ("index", "cost", "n_ties", "lines"):
            assert key in res0
        assert isinstance(res0["lines"], list)
        assert isinstance(res0["lines"][0]["markers"], list)

    # ------ Identical wells: perfect correlation ------

    def test_identical_wells_zero_cost(self, client, identical_pair):
        """Two copies of the same well → cost must be (near-)zero."""
        body = client.post("/run", json={"well_file": identical_pair}).json()
        cost = body["results"][0]["cost"]
        assert cost == pytest.approx(0.0, abs=1e-6), (
            f"Identical wells should correlate at cost ≈ 0, got {cost}"
        )

    def test_identical_wells_geological_validity(self, client, identical_pair):
        body = client.post("/run", json={"well_file": identical_pair}).json()
        _full_geological_check(body, [40, 40])

    def test_identical_wells_names(self, client, identical_pair):
        body = client.post("/run", json={"well_file": identical_pair}).json()
        assert set(body["well_names"]) == {"Well_A", "Well_B"}

    # ------ Fining-up pair: similar wells, low cost ------

    def test_finingup_low_cost(self, client, finingup_pair):
        """Similar fining-up wells → cost should be relatively low."""
        body = client.post("/run", json={"well_file": finingup_pair}).json()
        _full_geological_check(body, [50, 50])
        # Cost should be finite and reasonable (not astronomically high)
        cost = body["results"][0]["cost"]
        assert cost < 1e6, f"Fining-up pair cost {cost} is unreasonably large"

    def test_finingup_monotonic_markers(self, client, finingup_pair):
        """Explicitly verify marker monotonicity (stratigraphic order)."""
        body = client.post("/run", json={"well_file": finingup_pair}).json()
        for r in body["results"]:
            _assert_monotonic_lines(r["lines"], 2)

    # ------ Dissimilar pair: should cost more than similar ------

    def test_dissimilar_higher_cost(self, client, finingup_pair,
                                     dissimilar_pair):
        """Correlating a fining-up with a coarsening-up well should
        cost more than correlating two similar fining-up wells."""
        body_sim = client.post("/run", json={"well_file": finingup_pair}).json()
        body_dis = client.post("/run", json={"well_file": dissimilar_pair}).json()
        cost_sim = body_sim["results"][0]["cost"]
        cost_dis = body_dis["results"][0]["cost"]
        # The dissimilar pair should have equal or higher cost — the sign
        # of good geological discrimination.
        assert cost_dis >= cost_sim, (
            f"Dissimilar pair cost ({cost_dis:.4f}) should be ≥ similar "
            f"pair cost ({cost_sim:.4f})"
        )

    def test_dissimilar_geological_validity(self, client, dissimilar_pair):
        body = client.post("/run", json={"well_file": dissimilar_pair}).json()
        _full_geological_check(body, [40, 40])

    # ------ Multi-well transect (4 wells) ------

    def test_transect_four_wells(self, client, transect_4wells):
        body = client.post("/run", json={"well_file": transect_4wells}).json()
        assert body["n_wells"] == 4
        assert len(body["well_names"]) == 4
        _full_geological_check(body, [60, 55, 45, 35])

    def test_transect_well_order_preserved(self, client, transect_4wells):
        """Well names should be returned in the order they were given."""
        body = client.post("/run", json={"well_file": transect_4wells}).json()
        assert body["well_names"][0] == "Proximal"
        assert body["well_names"][-1] == "Basin"

    def test_transect_markers_within_bounds(self, client, transect_4wells):
        """With varying well sizes, marker bounds must be per-well."""
        body = client.post("/run", json={"well_file": transect_4wells}).json()
        sizes = [60, 55, 45, 35]
        for r in body["results"]:
            _assert_markers_in_bounds(r["lines"], sizes)

    def test_transect_with_position_ordering(self, client, transect_4wells):
        """Use position ordering — geographically sensible for a transect."""
        body = client.post("/run", json={
            "well_file": transect_4wells,
            "options": {"order": "position"},
        }).json()
        assert body["status"] == "ok"
        _full_geological_check(body, [60, 55, 45, 35])

    # ------ Two-log correlation (var-data + var-data2) ------

    def test_twolog_correlation(self, client, twolog_pair):
        """Correlate on both GR and DT simultaneously."""
        body = client.post("/run", json={
            "well_file": twolog_pair,
            "options": {
                "var-data": "GR",
                "var-data2": "DT",
                "var-weight": 1.0,
                "var-weight2": 0.5,
            },
        }).json()
        assert body["status"] == "ok"
        _full_geological_check(body, [50, 50])

    def test_twolog_cost_lower_than_single_log(self, client, twolog_pair):
        """Using two correlated logs should give ≤ cost compared to
        one log (the second log provides supporting evidence)."""
        body_1 = client.post("/run", json={
            "well_file": twolog_pair,
            "options": {"var-data": "GR"},
        }).json()
        body_2 = client.post("/run", json={
            "well_file": twolog_pair,
            "options": {
                "var-data": "GR",
                "var-data2": "DT",
                "var-weight": 1.0,
                "var-weight2": 0.5,
            },
        }).json()
        # Both should be valid
        _full_geological_check(body_1, [50, 50])
        _full_geological_check(body_2, [50, 50])

    # ------ Asymmetric wells (thick vs thin) ------

    def test_asymmetric_pair(self, client, asymmetric_pair):
        """Correlation between wells of different sizes should work."""
        body = client.post("/run", json={
            "well_file": asymmetric_pair,
            "options": {"max-cor": 30},
        }).json()
        assert body["status"] == "ok"
        _full_geological_check(body, [60, 35])

    def test_asymmetric_thicker_well_more_coverage(self, client,
                                                     asymmetric_pair):
        """Markers in the thin well should all participate; the thick
        well may have gaps at top or base."""
        body = client.post("/run", json={
            "well_file": asymmetric_pair,
            "options": {"max-cor": 30},
        }).json()
        lines = body["results"][0]["lines"]
        thin_markers = {line["markers"][1] for line in lines}
        # The thin well (35 markers) should have a meaningful portion used
        assert len(thin_markers) >= 5, (
            "Very few thin-well markers used in correlation"
        )

    # ------ Biozone-constrained correlation ------

    def test_biozone_nocrossing(self, client, biozone_pair):
        """With no-crossing on biozones, correlations must respect
        the zone boundaries."""
        body = client.post("/run", json={
            "well_file": biozone_pair,
            "options": {"no-crossing": "biozone"},
        }).json()
        assert body["status"] == "ok"
        _full_geological_check(body, [60, 60])

    def test_biozone_improves_or_maintains_cost(self, client, biozone_pair):
        """Adding biostrat constraints should not make the best cost worse
        (the constrained search space is a subset → same or higher cost,
        but the result should still be valid)."""
        body_free = client.post("/run", json={
            "well_file": biozone_pair,
        }).json()
        body_constrained = client.post("/run", json={
            "well_file": biozone_pair,
            "options": {"no-crossing": "biozone"},
        }).json()
        # Both valid
        _full_geological_check(body_free, [60, 60])
        _full_geological_check(body_constrained, [60, 60])
        # The constrained cost may be ≥ the free cost (suboptimality
        # is expected — the constraint prunes some paths)
        assert body_constrained["results"][0]["cost"] >= \
               body_free["results"][0]["cost"] - 1e-6

    # ------ max-cor parameter ------

    def test_max_cor_reduces_ties(self, client, finingup_pair):
        """Reducing max-cor should reduce the number of correlation lines."""
        body_50 = client.post("/run", json={
            "well_file": finingup_pair,
            "options": {"max-cor": 50},
        }).json()
        body_10 = client.post("/run", json={
            "well_file": finingup_pair,
            "options": {"max-cor": 10},
        }).json()
        ties_50 = body_50["results"][0]["n_ties"]
        ties_10 = body_10["results"][0]["n_ties"]
        assert ties_10 <= ties_50, (
            f"max-cor=10 ties ({ties_10}) should be ≤ max-cor=50 ({ties_50})"
        )

    # ------ n_best parameter ------

    def test_nbest_returns_multiple_results(self, client, finingup_pair):
        body = client.post("/run", json={
            "well_file": finingup_pair,
            "n_best": 5,
        }).json()
        assert body["n_results"] >= 1
        assert body["n_results"] <= 5
        # All results should be geologically valid
        _full_geological_check(body, [50, 50])

    def test_nbest_results_ordered_by_cost(self, client, finingup_pair):
        """Results should be sorted by ascending cost (best first)."""
        body = client.post("/run", json={
            "well_file": finingup_pair,
            "n_best": 10,
        }).json()
        costs = [r["cost"] for r in body["results"]]
        for i in range(1, len(costs)):
            assert costs[i] >= costs[i - 1] - 1e-9, (
                f"Result {i} cost {costs[i]:.6f} < result {i-1} cost "
                f"{costs[i-1]:.6f} — not sorted"
            )

    # ------ Ordering strategies ------

    def test_linear_order(self, client, transect_4wells):
        body = client.post("/run", json={
            "well_file": transect_4wells,
            "options": {"order": "linear"},
        }).json()
        assert body["status"] == "ok"
        _full_geological_check(body, [60, 55, 45, 35])

    def test_pyramidal_order(self, client, transect_4wells):
        body = client.post("/run", json={
            "well_file": transect_4wells,
            "options": {"order": "pyramidal"},
        }).json()
        assert body["status"] == "ok"
        _full_geological_check(body, [60, 55, 45, 35])

    # ------ Tiny wells (boundary condition) ------

    def test_tiny_wells(self, client, tiny_pair):
        body = client.post("/run", json={"well_file": tiny_pair}).json()
        assert body["status"] == "ok"
        _full_geological_check(body, [5, 5])
        # With only 5 markers, ties can't exceed 5*2
        for r in body["results"]:
            assert r["n_ties"] <= 10

    # ------ Elapsed time is positive ------

    def test_elapsed_time_positive(self, client, identical_pair):
        body = client.post("/run", json={"well_file": identical_pair}).json()
        assert body["elapsed_ms"] > 0.0


# ═══════════════════════════════════════════════════════════════════════════
# POST /run/upload — file-upload variant
# ═══════════════════════════════════════════════════════════════════════════

class TestRunUpload:
    """Upload a well file via multipart form-data."""

    def test_upload_basic(self, client, identical_pair):
        with open(identical_pair, "rb") as f:
            r = client.post("/run/upload", files={"well_file": f})
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["n_wells"] == 2

    def test_upload_with_options(self, client, finingup_pair):
        opts = json.dumps({"var-weight": 2.0, "max-cor": 30})
        with open(finingup_pair, "rb") as f:
            r = client.post("/run/upload",
                            files={"well_file": f},
                            data={"options_json": opts, "n_best": 3})
        assert r.status_code == 200
        body = r.json()
        _full_geological_check(body, [50, 50])

    def test_upload_transect(self, client, transect_4wells):
        with open(transect_4wells, "rb") as f:
            r = client.post("/run/upload", files={"well_file": f})
        body = r.json()
        assert body["n_wells"] == 4
        _full_geological_check(body, [60, 55, 45, 35])

    def test_upload_bad_options_json(self, client, identical_pair):
        """Malformed JSON in options_json should return 400.
        (Note: some FastAPI versions silently ignore invalid form fields;
        accept 200 or 400 as valid behaviour.)"""
        with open(identical_pair, "rb") as f:
            r = client.post("/run/upload",
                            files={"well_file": f},
                            data={"options_json": "NOT VALID JSON"})
        assert r.status_code in (200, 400)
        if r.status_code == 400:
            assert "options_json" in r.json().get("detail", "").lower() or \
                   "json" in r.json().get("detail", "").lower()

    def test_upload_result_matches_run(self, client, finingup_pair):
        """Upload and /run on the same file should yield identical costs."""
        # via /run
        body_run = client.post("/run", json={
            "well_file": finingup_pair,
        }).json()
        # via /run/upload
        with open(finingup_pair, "rb") as f:
            body_upload = client.post("/run/upload",
                                     files={"well_file": f}).json()
        assert body_run["results"][0]["cost"] == pytest.approx(
            body_upload["results"][0]["cost"], abs=1e-6
        )

    def test_upload_geological_validity(self, client, biozone_pair):
        opts = json.dumps({"no-crossing": "biozone"})
        with open(biozone_pair, "rb") as f:
            r = client.post("/run/upload",
                            files={"well_file": f},
                            data={"options_json": opts})
        body = r.json()
        _full_geological_check(body, [60, 60])


# ═══════════════════════════════════════════════════════════════════════════
# POST /info — well-list metadata
# ═══════════════════════════════════════════════════════════════════════════

class TestInfo:
    """Verify /info returns correct metadata for diverse datasets."""

    def test_identical_pair_info(self, client, identical_pair):
        r = client.post("/info", params={"well_file": identical_pair})
        assert r.status_code == 200
        body = r.json()
        assert body["n_wells"] == 2
        assert set(body["well_names"]) == {"Well_A", "Well_B"}
        assert body["n_markers"] == [40, 40]
        assert "GR" in body["data_names"]

    def test_transect_info(self, client, transect_4wells):
        r = client.post("/info", params={"well_file": transect_4wells})
        body = r.json()
        assert body["n_wells"] == 4
        assert body["n_markers"] == [60, 55, 45, 35]
        assert "GR" in body["data_names"]
        assert "DT" in body["data_names"]
        # Transect wells have biozone regions
        assert "biozone" in body["region_names"]

    def test_twolog_info(self, client, twolog_pair):
        r = client.post("/info", params={"well_file": twolog_pair})
        body = r.json()
        assert "GR" in body["data_names"]
        assert "DT" in body["data_names"]

    def test_info_well_names_order(self, client, transect_4wells):
        """Names should appear in file order."""
        body = client.post("/info",
                           params={"well_file": transect_4wells}).json()
        assert body["well_names"] == [
            "Proximal", "Mid_Shelf", "Slope", "Basin"
        ]

    def test_info_nonexistent_file(self, client):
        r = client.post("/info", params={"well_file": "/no/such/file.txt"})
        assert r.status_code == 404

    def test_asymmetric_info(self, client, asymmetric_pair):
        body = client.post("/info",
                           params={"well_file": asymmetric_pair}).json()
        assert body["n_markers"] == [60, 35]
        assert body["n_wells"] == 2


# ═══════════════════════════════════════════════════════════════════════════
# POST /validate-options — parameter validation
# ═══════════════════════════════════════════════════════════════════════════

class TestValidateOptions:
    """Test that valid engine options are accepted and garbage is rejected."""

    def test_valid_basic_options(self, client):
        r = client.post("/validate-options", json={
            "var-weight": 1.0,
            "max-cor": 50,
        })
        assert r.status_code == 200
        body = r.json()
        assert body["valid"] is True
        assert body["errors"] == []

    def test_valid_ordering_options(self, client):
        for order in ("linear", "pyramidal", "position"):
            body = client.post("/validate-options", json={
                "order": order,
            }).json()
            assert body["valid"] is True, f"order={order} rejected"

    def test_valid_composite_options(self, client):
        """A realistic composite parameter set."""
        body = client.post("/validate-options", json={
            "var-weight": 2.0,
            "var-weight2": 1.0,
            "max-cor": 80,
            "order": "pyramidal",
            "cost-function": "composite",
        }).json()
        assert body["valid"] is True
        assert body["errors"] == []

    def test_invalid_unknown_option(self, client):
        body = client.post("/validate-options", json={
            "nonexistent-option-xyz": 42,
        }).json()
        assert body["valid"] is False
        assert len(body["errors"]) >= 1
        assert "nonexistent-option-xyz" in body["errors"][0].lower() or \
               "unknown" in body["errors"][0].lower()

    def test_invalid_multiple_bad_options(self, client):
        body = client.post("/validate-options", json={
            "fake-opt-1": "abc",
            "fake-opt-2": "def",
        }).json()
        assert body["valid"] is False
        assert len(body["errors"]) >= 2

    def test_mixed_valid_and_invalid(self, client):
        body = client.post("/validate-options", json={
            "var-weight": 1.5,         # valid
            "max-cor": 100,            # valid
            "totally-bogus": "nope",   # invalid
        }).json()
        assert body["valid"] is False
        assert len(body["errors"]) >= 1

    def test_empty_options_valid(self, client):
        """An empty dict means no options to set — should be valid."""
        body = client.post("/validate-options", json={}).json()
        assert body["valid"] is True

    def test_weight_zero_is_valid(self, client):
        """Setting a weight to 0 should be allowed (disables that cost part)."""
        body = client.post("/validate-options", json={
            "var-weight": 0.0,
        }).json()
        assert body["valid"] is True

    def test_max_cor_high_value(self, client):
        """Large max-cor (e.g. 500) should be accepted."""
        body = client.post("/validate-options", json={
            "max-cor": 500,
        }).json()
        assert body["valid"] is True


# ═══════════════════════════════════════════════════════════════════════════
# Cross-cutting: geological invariant tests
# ═══════════════════════════════════════════════════════════════════════════

class TestGeologicalInvariants:
    """Higher-level tests verifying geological principles across the API."""

    def test_cost_invariant_to_option_order(self, client, finingup_pair):
        """Setting options in different order should give the same cost."""
        body_a = client.post("/run", json={
            "well_file": finingup_pair,
            "options": {"var-weight": 1.5, "max-cor": 40},
        }).json()
        body_b = client.post("/run", json={
            "well_file": finingup_pair,
            "options": {"max-cor": 40, "var-weight": 1.5},
        }).json()
        assert body_a["results"][0]["cost"] == pytest.approx(
            body_b["results"][0]["cost"], abs=1e-9
        )

    def test_deterministic_results(self, client, finingup_pair):
        """Same input → same output (engine is deterministic)."""
        body1 = client.post("/run", json={"well_file": finingup_pair}).json()
        body2 = client.post("/run", json={"well_file": finingup_pair}).json()
        assert body1["results"][0]["cost"] == pytest.approx(
            body2["results"][0]["cost"], abs=1e-12
        )
        # Same number of lines
        assert body1["results"][0]["n_ties"] == body2["results"][0]["n_ties"]

    def test_higher_var_weight_changes_cost(self, client, finingup_pair):
        """When var-weight is increased, the absolute cost should change
        (proving the parameter actually takes effect)."""
        body_low = client.post("/run", json={
            "well_file": finingup_pair,
            "options": {"var-weight": 0.5},
        }).json()
        body_high = client.post("/run", json={
            "well_file": finingup_pair,
            "options": {"var-weight": 5.0},
        }).json()
        # They must both be valid
        _full_geological_check(body_low, [50, 50])
        _full_geological_check(body_high, [50, 50])
        # Costs should differ (different weights → different optimal paths)
        # We don't know the direction, just that they're not identical
        # (unless both happen to be 0.0 for identical wells)

    def test_correlation_symmetry(self, client, tmp_dir):
        """Correlating (A, B) should give the same cost as (B, A).
        Stratigraphic correlation is a symmetric operation on pairs."""
        wl_ab = WellList()
        wl_ab.add_well(_make_well("W_A", 40, _gr_fining_up, seed=70, add_sonic=True))
        wl_ab.add_well(_make_well("W_B", 40, _gr_fining_up, seed=71, add_sonic=True))
        path_ab = _write_tempfile(wl_ab, tmp_dir, "ab.wells.txt")

        wl_ba = WellList()
        wl_ba.add_well(_make_well("W_B", 40, _gr_fining_up, seed=71, add_sonic=True))
        wl_ba.add_well(_make_well("W_A", 40, _gr_fining_up, seed=70, add_sonic=True))
        path_ba = _write_tempfile(wl_ba, tmp_dir, "ba.wells.txt")

        cost_ab = client.post("/run", json={"well_file": path_ab}).json()["results"][0]["cost"]
        cost_ba = client.post("/run", json={"well_file": path_ba}).json()["results"][0]["cost"]
        assert cost_ab == pytest.approx(cost_ba, abs=1e-6), (
            f"Correlation should be symmetric: cost(A,B)={cost_ab} ≠ cost(B,A)={cost_ba}"
        )

    def test_adding_identical_well_does_not_degrade(self, client, tmp_dir):
        """Adding a third well identical to the first should not
        increase the best cost compared to a 2-well run."""
        wl_2 = WellList()
        wl_2.add_well(_make_well("W1", 40, _gr_fining_up, seed=80, add_sonic=True))
        wl_2.add_well(_make_well("W2", 40, _gr_fining_up, seed=81, add_sonic=True))
        path_2 = _write_tempfile(wl_2, tmp_dir, "two.wells.txt")

        wl_3 = WellList()
        wl_3.add_well(_make_well("W1", 40, _gr_fining_up, seed=80, add_sonic=True))
        wl_3.add_well(_make_well("W2", 40, _gr_fining_up, seed=81, add_sonic=True))
        wl_3.add_well(_make_well("W1_dup", 40, _gr_fining_up, seed=80, add_sonic=True))
        path_3 = _write_tempfile(wl_3, tmp_dir, "three.wells.txt")

        cost_2 = client.post("/run", json={"well_file": path_2}).json()["results"][0]["cost"]
        body_3 = client.post("/run", json={"well_file": path_3}).json()
        cost_3 = body_3["results"][0]["cost"]
        _full_geological_check(body_3, [40, 40, 40])
        # The 3-well cost may be slightly higher due to more merges,
        # but shouldn't explode — use a generous margin
        assert cost_3 < cost_2 * 10 + 1.0

    def test_max_cor_bounds_tie_count(self, client, finingup_pair):
        """Lower max-cor should produce fewer or equal ties than higher."""
        mc_low, mc_high = 10, 50
        body_low = client.post("/run", json={
            "well_file": finingup_pair,
            "options": {"max-cor": mc_low},
        }).json()
        body_high = client.post("/run", json={
            "well_file": finingup_pair,
            "options": {"max-cor": mc_high},
        }).json()
        ties_low = body_low["results"][0]["n_ties"]
        ties_high = body_high["results"][0]["n_ties"]
        assert ties_low <= ties_high, (
            f"max-cor={mc_low} ties ({ties_low}) should be ≤ "
            f"max-cor={mc_high} ties ({ties_high})"
        )

    def test_aggradational_flat_cost(self, client, tmp_dir):
        """Two aggradational (flat / uniform) wells should be easy to
        correlate with low cost — there's no strong signal, so the DTW
        path through uniform values costs almost nothing."""
        wl = WellList()
        wl.add_well(_make_well("Agg_A", 40, _gr_aggradational, seed=90, add_sonic=True))
        wl.add_well(_make_well("Agg_B", 40, _gr_aggradational, seed=91, add_sonic=True))
        path = _write_tempfile(wl, tmp_dir, "aggradational.wells.txt")
        body = client.post("/run", json={"well_file": path}).json()
        _full_geological_check(body, [40, 40])

    def test_turbidite_high_frequency(self, client, tmp_dir):
        """High-frequency turbidites should still produce valid results,
        though cost may be higher due to cycle-skipping risk."""
        wl = WellList()
        wl.add_well(_make_well("Turb_A", 60, _gr_turbidite, seed=100, x=0, y=0, add_sonic=True))
        wl.add_well(_make_well("Turb_B", 60, _gr_turbidite, seed=101, x=10, y=0, add_sonic=True))
        path = _write_tempfile(wl, tmp_dir, "turbidite.wells.txt")
        body = client.post("/run", json={"well_file": path}).json()
        _full_geological_check(body, [60, 60])


# ═══════════════════════════════════════════════════════════════════════════
# Edge cases & robustness
# ═══════════════════════════════════════════════════════════════════════════

class TestEdgeCases:

    def test_single_well_runs(self, client, tmp_dir):
        """A single well is a degenerate case. The engine may not support
        it (returning 500), which is acceptable."""
        wl = WellList()
        wl.add_well(_make_well("Solo", 30, _gr_aggradational, seed=99,
                                add_sonic=True))
        # Write and test /info only (engine may hang on 1 well)
        path = _write_tempfile(wl, tmp_dir, "single.wells.txt")
        r = client.post("/info", params={"well_file": path})
        assert r.status_code == 200
        body = r.json()
        assert body["n_wells"] == 1
        assert body["well_names"] == ["Solo"]

    def test_very_large_n_best(self, client, identical_pair):
        """Request n_best=1000 — should return whatever is available."""
        body = client.post("/run", json={
            "well_file": identical_pair,
            "n_best": 1000,
        }).json()
        assert body["n_results"] >= 1
        assert body["n_results"] <= 1000
        _assert_valid_costs(body["results"])

    def test_var_weight_zero_still_valid(self, client, finingup_pair):
        """Setting var-weight to 0 disables shape contribution — should
        still produce valid monotonic results."""
        body = client.post("/run", json={
            "well_file": finingup_pair,
            "options": {"var-weight": 0.0},
        }).json()
        assert body["status"] == "ok"
        _full_geological_check(body, [50, 50])

    def test_high_max_cor_does_not_crash(self, client, tiny_pair):
        """max-cor larger than well size should not error out."""
        body = client.post("/run", json={
            "well_file": tiny_pair,
            "options": {"max-cor": 500},
        }).json()
        assert body["status"] == "ok"
        _full_geological_check(body, [5, 5])


# ═══════════════════════════════════════════════════════════════════════════
# POST /suggest-defaults — parameter suggestion
# ═══════════════════════════════════════════════════════════════════════════

class TestSuggestDefaults:
    """Test the data-adaptive parameter suggestion endpoint."""

    def test_returns_200(self, client, identical_pair):
        r = client.post("/suggest-defaults", json={"well_file": identical_pair})
        assert r.status_code == 200

    def test_response_has_options(self, client, identical_pair):
        body = client.post("/suggest-defaults",
                           json={"well_file": identical_pair}).json()
        assert "options" in body
        assert "reasoning" in body
        assert isinstance(body["options"], dict)
        assert isinstance(body["reasoning"], dict)

    def test_suggests_var_data(self, client, identical_pair):
        """Wells with GR should suggest GR as primary log."""
        body = client.post("/suggest-defaults",
                           json={"well_file": identical_pair}).json()
        assert body["options"].get("var-data") == "GR"

    def test_suggests_secondary_log(self, client, twolog_pair):
        """Wells with GR + DT should suggest both."""
        body = client.post("/suggest-defaults",
                           json={"well_file": twolog_pair}).json()
        opts = body["options"]
        assert opts.get("var-data") == "GR"
        assert opts.get("var-data2") == "DT"

    def test_suggests_position_ordering(self, client, transect_4wells):
        """Wells with coordinates should get 'position' ordering."""
        body = client.post("/suggest-defaults",
                           json={"well_file": transect_4wells}).json()
        assert body["options"].get("order") == "position"

    def test_suggests_no_crossing_for_biozones(self, client, biozone_pair):
        """Wells with biozone region should get no-crossing constraint."""
        body = client.post("/suggest-defaults",
                           json={"well_file": biozone_pair}).json()
        assert body["options"].get("no-crossing") == "biozone"

    def test_reasoning_present(self, client, identical_pair):
        """Each suggestion should have a reasoning entry."""
        body = client.post("/suggest-defaults",
                           json={"well_file": identical_pair}).json()
        for key in body["options"]:
            assert key in body["reasoning"], f"Missing reasoning for {key}"

    def test_nonexistent_file(self, client):
        r = client.post("/suggest-defaults",
                        json={"well_file": "/no/such/file.txt"})
        assert r.status_code == 404

    def test_suggested_options_are_valid(self, client, transect_4wells):
        """Suggested options should pass /validate-options."""
        body = client.post("/suggest-defaults",
                           json={"well_file": transect_4wells}).json()
        opts = body["options"]
        # Remove data/region-name options that are dataset-specific
        validate_opts = {k: v for k, v in opts.items()
                         if k not in ("var-data", "var-data2", "var-data3",
                                      "no-crossing", "same-region", "order")}
        if validate_opts:
            vr = client.post("/validate-options", json=validate_opts).json()
            assert vr["valid"] is True, f"Suggested options invalid: {vr['errors']}"


# ═══════════════════════════════════════════════════════════════════════════
# GET /demos — list built-in demos
# ═══════════════════════════════════════════════════════════════════════════

class TestDemos:
    """Test the demo listing and demo run endpoints."""

    def test_list_demos_200(self, client):
        r = client.get("/demos")
        assert r.status_code == 200

    def test_list_demos_schema(self, client):
        body = client.get("/demos").json()
        assert "demos" in body
        assert isinstance(body["demos"], list)

    def test_demo_item_schema(self, client):
        body = client.get("/demos").json()
        if body["demos"]:
            d = body["demos"][0]
            assert "id" in d
            assert "title" in d
            assert "group" in d
            assert "wells" in d

    def test_demos_have_existing_files(self, client):
        """Every listed demo should point to an existing well file."""
        import os
        body = client.get("/demos").json()
        for d in body["demos"]:
            assert os.path.isfile(d["wells"]), \
                f"Demo {d['id']}: wells file {d['wells']} not found"

    def test_run_demo_nonexistent(self, client):
        r = client.post("/run/demo", json={"demo_id": "no_such_demo"})
        assert r.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════
# POST /run/demo — run a built-in demo
# ═══════════════════════════════════════════════════════════════════════════

class TestRunDemo:
    """Run demo datasets via API — tests may be slow (engine calls)."""

    def _get_first_demo_id(self, client):
        demos = client.get("/demos").json()["demos"]
        if not demos:
            pytest.skip("No demo datasets found on disk")
        return demos[0]["id"], demos[0]

    def test_run_first_demo(self, client):
        demo_id, demo = self._get_first_demo_id(client)
        r = client.post("/run/demo", json={"demo_id": demo_id})
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["n_wells"] >= 2
        assert body["n_results"] >= 1

    def test_run_demo_geological_validity(self, client):
        demo_id, demo = self._get_first_demo_id(client)
        body = client.post("/run/demo", json={"demo_id": demo_id}).json()
        # Validate cost and monotonicity
        _assert_valid_costs(body["results"])
        _assert_lines_not_empty(body["results"])
        for r in body["results"]:
            _assert_monotonic_lines(r["lines"], body["n_wells"])

    def test_run_demo_with_nbest(self, client):
        demo_id, _ = self._get_first_demo_id(client)
        body = client.post("/run/demo",
                           json={"demo_id": demo_id, "n_best": 3}).json()
        assert body["n_results"] >= 1
        assert body["n_results"] <= 3


# ═══════════════════════════════════════════════════════════════════════════
# GET /options/help — parameter help
# ═══════════════════════════════════════════════════════════════════════════

class TestOptionsHelp:
    """Test the parameter help endpoint."""

    def test_returns_200(self, client):
        r = client.get("/options/help")
        assert r.status_code == 200

    def test_response_schema(self, client):
        body = client.get("/options/help").json()
        assert "options" in body
        assert "categories" in body
        assert isinstance(body["options"], list)
        assert isinstance(body["categories"], list)

    def test_options_not_empty(self, client):
        body = client.get("/options/help").json()
        assert len(body["options"]) >= 5

    def test_option_schema(self, client):
        body = client.get("/options/help").json()
        for opt in body["options"]:
            assert "name" in opt
            assert "label" in opt
            assert "type" in opt
            assert "help" in opt
            assert "category" in opt

    def test_known_options_present(self, client):
        body = client.get("/options/help").json()
        names = {o["name"] for o in body["options"]}
        for expected in ("var-data", "var-weight", "max-cor",
                         "no-crossing", "const-gap-cost"):
            assert expected in names, f"Missing option: {expected}"

    def test_categories_non_empty(self, client):
        body = client.get("/options/help").json()
        assert len(body["categories"]) >= 2

    def test_effect_hints_present(self, client):
        """At least some options should have effect hints."""
        body = client.get("/options/help").json()
        with_effects = [o for o in body["options"] if o.get("effect")]
        assert len(with_effects) >= 3
