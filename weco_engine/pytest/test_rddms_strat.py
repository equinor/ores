"""
Tests for weco.strat_column, weco.depenv, weco.osdu_auth, and §11 RDDMS features.
==================================================================================

Tests cover:
- StratColumn from_dict / to_dict round-trip
- StratColumn apply_to_well
- Horizon / Unit / Rank import functions
- Depositional environment presets and detection
- OSDU auth config helper
- RDDMS API routes (mocked)
- Well.meta dict
"""

import json
import os
import tempfile

import numpy as np
import pytest

from weco.data import Well, WellList


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

def _make_well(name="W1", n=100, depth_start=0.0, depth_end=100.0):
    """Create a minimal Well with depth + GR data."""
    w = Well(name=name)
    w.size = n
    depths = list(np.linspace(depth_start, depth_end, n))
    w.data["Depth"] = depths
    gr = list(np.random.default_rng(42).uniform(20, 120, n))
    w.data["GR"] = gr
    w.x, w.y, w.z = 100.0, 200.0, 0.0
    w.h = depth_end - depth_start
    return w


# ═══════════════════════════════════════════════════════════════════════════
# Well.meta
# ═══════════════════════════════════════════════════════════════════════════

class TestWellMeta:
    def test_meta_initialised(self):
        w = Well("TestMeta")
        assert hasattr(w, "meta")
        assert isinstance(w.meta, dict)
        assert len(w.meta) == 0

    def test_meta_stores_uom(self):
        w = Well("TestMeta")
        w.meta["GR"] = {"uom": "gAPI", "kind": "continuous"}
        assert w.meta["GR"]["uom"] == "gAPI"


# ═══════════════════════════════════════════════════════════════════════════
# StratColumn model
# ═══════════════════════════════════════════════════════════════════════════

class TestStratColumn:
    SAMPLE_DICT = {
        "name": "Test Column",
        "ranks": [
            {
                "name": "System",
                "kind": "chrono",
                "units": [
                    {"name": "Cretaceous", "top_age_ma": 66.0, "base_age_ma": 145.0},
                    {"name": "Jurassic", "top_age_ma": 145.0, "base_age_ma": 201.3},
                ],
            },
            {
                "name": "Series",
                "kind": "chrono",
                "units": [
                    {"name": "Upper Cretaceous", "top_age_ma": 66.0, "base_age_ma": 100.5,
                     "parent_name": "Cretaceous"},
                    {"name": "Lower Cretaceous", "top_age_ma": 100.5, "base_age_ma": 145.0,
                     "parent_name": "Cretaceous"},
                ],
            },
        ],
        "horizons": [
            {"name": "Top Cretaceous", "age_ma": 66.0, "unit_name": "Cretaceous",
             "boundary_type": "Top"},
            {"name": "Top Jurassic", "age_ma": 145.0, "unit_name": "Jurassic",
             "boundary_type": "Top"},
        ],
    }

    def test_from_dict(self):
        from weco.strat_column import StratColumn
        col = StratColumn.from_dict(self.SAMPLE_DICT)
        assert col.name == "Test Column"
        assert len(col.ranks) == 2
        assert col.unit_count == 4
        assert col.horizon_count == 2

    def test_round_trip(self):
        from weco.strat_column import StratColumn
        col = StratColumn.from_dict(self.SAMPLE_DICT)
        d = col.to_dict()
        col2 = StratColumn.from_dict(d)
        assert col2.name == col.name
        assert col2.unit_count == col.unit_count

    def test_to_json_from_json(self):
        from weco.strat_column import StratColumn
        col = StratColumn.from_dict(self.SAMPLE_DICT)
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            path = f.name
        try:
            col.to_json(path)
            col2 = StratColumn.from_json(path)
            assert col2.name == "Test Column"
            assert col2.unit_count == 4
        finally:
            os.unlink(path)

    def test_apply_to_well(self):
        from weco.strat_column import StratColumn
        col = StratColumn.from_dict(self.SAMPLE_DICT)
        w = _make_well(n=200, depth_start=0, depth_end=200)
        picks = [
            {"unit_name": "Cretaceous", "top_md": 10.0, "base_md": 80.0},
            {"unit_name": "Jurassic", "top_md": 80.0, "base_md": 180.0},
        ]
        result = col.apply_to_well(w, picks)
        assert len(result["regions_created"]) >= 1
        assert result["no_crossing_region"] == "StratHorizons"
        assert "Rank_System" in w.region

    def test_repr(self):
        from weco.strat_column import StratColumn
        col = StratColumn.from_dict(self.SAMPLE_DICT)
        r = repr(col)
        assert "Test Column" in r
        assert "ranks=2" in r

    def test_detect_depositional_environments(self):
        from weco.strat_column import StratColumn
        d = {
            "name": "EnvCol",
            "ranks": [{
                "name": "R1",
                "units": [
                    {"name": "U1", "depositional_environment": "Shallow Marine"},
                    {"name": "U2", "depositional_environment": "Shallow Marine"},
                    {"name": "U3", "depositional_environment": "Deltaic"},
                ],
            }],
        }
        col = StratColumn.from_dict(d)
        envs = col.detect_depositional_environments()
        assert "Deltaic" in envs
        assert "Shallow Marine" in envs


# ═══════════════════════════════════════════════════════════════════════════
# Horizon / Unit / Rank import
# ═══════════════════════════════════════════════════════════════════════════

class TestHorizonUnitRankImport:
    def test_import_horizons_as_region(self):
        from weco.rddms import import_horizons_as_region
        w = _make_well(n=100, depth_start=0, depth_end=100)
        picks = [
            {"name": "Top_A", "md": 20.0},
            {"name": "Top_B", "md": 50.0},
            {"name": "Top_C", "md": 80.0},
        ]
        ok = import_horizons_as_region(w, picks, "TestHorizons")
        assert ok
        assert "TestHorizons" in w.region

    def test_import_horizons_empty(self):
        from weco.rddms import import_horizons_as_region
        w = _make_well()
        ok = import_horizons_as_region(w, [], "Empty")
        assert not ok

    def test_import_units_as_region(self):
        from weco.rddms import import_units_as_region
        w = _make_well(n=200, depth_start=0, depth_end=200)
        units = [
            {"name": "Sand_A", "top_md": 10.0, "base_md": 50.0},
            {"name": "Shale_B", "top_md": 50.0, "base_md": 100.0},
            {"name": "Sand_C", "top_md": 100.0, "base_md": 180.0},
        ]
        ok = import_units_as_region(w, units, "UNIT")
        assert ok
        assert "UNIT" in w.region

    def test_import_units_empty(self):
        from weco.rddms import import_units_as_region
        w = _make_well()
        ok = import_units_as_region(w, [], "UNIT")
        assert not ok

    def test_import_ranks_as_regions(self):
        from weco.rddms import import_ranks_as_regions
        w = _make_well(n=200, depth_start=0, depth_end=200)
        strat_column = {
            "ranks": [
                {
                    "name": "System",
                    "units": [
                        {"name": "Cretaceous"},
                        {"name": "Jurassic"},
                    ],
                },
            ],
        }
        well_picks = [
            {"unit_name": "Cretaceous", "top_md": 10.0, "base_md": 100.0},
            {"unit_name": "Jurassic", "top_md": 100.0, "base_md": 190.0},
        ]
        results = import_ranks_as_regions(w, strat_column, well_picks)
        assert results.get("Rank_System") is True


# ═══════════════════════════════════════════════════════════════════════════
# Depositional Environment
# ═══════════════════════════════════════════════════════════════════════════

class TestDepositionalEnvironment:
    def test_normalise_depenv(self):
        from weco.depenv import normalise_depenv
        assert normalise_depenv("Shallow Marine") == "shallow_marine"
        assert normalise_depenv("Turbidite") == "deep_marine"
        assert normalise_depenv("Deltaic") == "deltaic"
        assert normalise_depenv("Lacustrine") == "lacustrine"
        assert normalise_depenv("Aeolian") == "aeolian"
        assert normalise_depenv("Tidal") == "tidal"
        assert normalise_depenv("Reef") == "reef"
        assert normalise_depenv("Coal") == "coal"
        assert normalise_depenv("Glacial") == "glacial"
        assert normalise_depenv("") is None
        assert normalise_depenv("Unknown Thing") is None

    def test_presets_complete(self):
        from weco.depenv import DEPENV_PRESETS
        expected = {
            "shallow_marine", "deep_marine", "deltaic", "fluvial",
            "lacustrine", "aeolian", "tidal", "carbonate", "reef",
            "coal", "glacial",
        }
        assert set(DEPENV_PRESETS.keys()) == expected

    def test_all_presets_have_required_keys(self):
        from weco.depenv import DEPENV_PRESETS
        for key, preset in DEPENV_PRESETS.items():
            assert "label" in preset, f"{key} missing label"
            assert "osdu_names" in preset, f"{key} missing osdu_names"
            assert "recommended_opts" in preset, f"{key} missing recommended_opts"
            assert "log_priority" in preset, f"{key} missing log_priority"

    def test_suggest_options_basic(self):
        from weco.depenv import suggest_options
        opts = suggest_options("shallow_marine")
        assert "var_data" in opts
        assert opts["cost_function"] == "composite"

    def test_suggest_options_log_substitution(self):
        from weco.depenv import suggest_options
        # Only GR and DT available — should substitute RHOB
        opts = suggest_options("shallow_marine", data_names=["GR", "DT"])
        assert opts.get("var_data") == "GR"

    def test_detect_environment(self):
        from weco.strat_column import StratColumn
        from weco.depenv import detect_environment
        d = {
            "name": "Env Test",
            "ranks": [{
                "name": "R1",
                "units": [
                    {"name": "U1", "depositional_environment": "Shallow Marine"},
                    {"name": "U2", "depositional_environment": "Shallow Marine"},
                    {"name": "U3", "depositional_environment": "Deltaic"},
                ],
            }],
        }
        col = StratColumn.from_dict(d)
        env = detect_environment(col)
        assert env == "shallow_marine"  # majority


# ═══════════════════════════════════════════════════════════════════════════
# OSDU Auth
# ═══════════════════════════════════════════════════════════════════════════

class TestOsduAuth:
    def test_osdu_headers(self):
        from weco.osdu_auth import osdu_headers
        h = osdu_headers("test-token-123", data_partition="my-part")
        assert h["Authorization"] == "Bearer test-token-123"
        assert h["data-partition-id"] == "my-part"
        assert h["Content-Type"] == "application/json"

    def test_osdu_config_from_env(self, monkeypatch):
        from weco.osdu_auth import osdu_config_from_env
        monkeypatch.setenv("OSDU_URL", "https://osdu.example.com")
        monkeypatch.setenv("OSDU_DATA_PARTITION", "test-partition")
        config = osdu_config_from_env()
        assert config["url"] == "https://osdu.example.com"
        assert config["data_partition"] == "test-partition"

    def test_get_token_static(self, monkeypatch):
        from weco.osdu_auth import get_token
        monkeypatch.setenv("OSDU_TOKEN", "static-bearer-token")
        tok = get_token()
        assert tok == "static-bearer-token"

    def test_get_token_no_config_raises(self, monkeypatch):
        from weco.osdu_auth import get_token
        monkeypatch.delenv("OSDU_TOKEN", raising=False)
        monkeypatch.delenv("OSDU_TOKEN_URL", raising=False)
        monkeypatch.delenv("OSDU_CLIENT_ID", raising=False)
        # Azure CLI might also fail — patch subprocess
        import subprocess as sp
        monkeypatch.setattr(
            sp, "run",
            lambda *a, **kw: type("R", (), {"returncode": 1, "stdout": ""})(),
        )
        with pytest.raises(RuntimeError, match="Cannot acquire OSDU token"):
            get_token()


# ═══════════════════════════════════════════════════════════════════════════
# API Routes (functional tests via TestClient)
# ═══════════════════════════════════════════════════════════════════════════

class TestRddmsApiRoutes:
    """Test RDDMS API routes using FastAPI TestClient."""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from weco.api import app
        return TestClient(app)

    def test_rddms_import_no_source(self, client):
        resp = client.post("/rddms/import", json={
            "dataspace": "demo",
        })
        assert resp.status_code == 400

    def test_rddms_import_epc_not_found(self, client):
        resp = client.post("/rddms/import", json={
            "epc_file": "/nonexistent/path.epc",
        })
        assert resp.status_code == 404

    def test_rddms_import_url_no_token(self, client, monkeypatch):
        monkeypatch.delenv("OSDU_TOKEN", raising=False)
        resp = client.post("/rddms/import", json={
            "url": "https://rddms.example.com",
            "dataspace": "demo",
        })
        assert resp.status_code == 401

    def test_rddms_export_no_token(self, client, monkeypatch):
        monkeypatch.delenv("OSDU_TOKEN", raising=False)
        resp = client.post("/rddms/export", json={
            "url": "https://rddms.example.com",
            "project_path": "/tmp/test",
            "dataspace": "demo",
        })
        assert resp.status_code == 401

    def test_rddms_export_project_not_found(self, client, monkeypatch):
        monkeypatch.setenv("OSDU_TOKEN", "fake-token")
        resp = client.post("/rddms/export", json={
            "url": "https://rddms.example.com",
            "project_path": "/nonexistent/project",
            "dataspace": "demo",
        })
        assert resp.status_code == 404

    def test_rddms_strat_column_no_source(self, client):
        resp = client.post("/rddms/strat-column", json={
            "action": "import",
            "dataspace": "demo",
        })
        assert resp.status_code == 400

    def test_rddms_strat_column_import_json(self, client):
        from weco.strat_column import StratColumn
        col = StratColumn.from_dict({
            "name": "APITest",
            "ranks": [{
                "name": "R1",
                "units": [
                    {"name": "U1", "depositional_environment": "Shallow Marine"},
                ],
            }],
        })
        with tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w"
        ) as f:
            json.dump(col.to_dict(), f)
            path = f.name
        try:
            resp = client.post("/rddms/strat-column", json={
                "action": "import",
                "column_json": path,
            })
            assert resp.status_code == 200
            body = resp.json()
            assert body["column_name"] == "APITest"
            assert body["unit_count"] == 1
            assert body["detected_environment"] == "shallow_marine"
        finally:
            os.unlink(path)

    def test_rddms_strat_column_export_not_impl(self, client):
        resp = client.post("/rddms/strat-column", json={
            "action": "export",
            "dataspace": "demo",
        })
        assert resp.status_code == 501

    def test_depenv_suggest_shallow_marine(self, client):
        resp = client.post("/depenv/suggest", json={
            "environment": "Shallow Marine",
            "data_names": ["GR", "RHOB", "DT"],
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["environment"] == "shallow_marine"
        assert "var_data" in body["suggested_options"]

    def test_depenv_suggest_unknown(self, client):
        resp = client.post("/depenv/suggest", json={
            "environment": "Unknown_XYZ",
        })
        assert resp.status_code == 400

    def test_depenv_suggest_from_strat_column(self, client):
        from weco.strat_column import StratColumn
        col = StratColumn.from_dict({
            "name": "DetectTest",
            "ranks": [{
                "name": "R1",
                "units": [
                    {"name": "U1", "depositional_environment": "Deltaic"},
                    {"name": "U2", "depositional_environment": "Deltaic"},
                ],
            }],
        })
        with tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w"
        ) as f:
            json.dump(col.to_dict(), f)
            path = f.name
        try:
            resp = client.post("/depenv/suggest", json={
                "strat_column_json": path,
            })
            assert resp.status_code == 200
            assert resp.json()["environment"] == "deltaic"
        finally:
            os.unlink(path)
