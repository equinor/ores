"""
Tests for weco.export — Zonation, horizon picks, CSV/JSON/LAS export
====================================================================

Tests res_to_zonation_log, res_to_horizon_picks,
export_zonation_csv, export_horizon_picks_csv, export_horizon_picks_json,
export_zonation_las, and correlation_summary.
Uses real data from data/data_set_1.1 for integration tests.
"""

import csv
import json
import os

import numpy as np
import pytest

from weco.data import ResFile, WellList, ResAndWL
from weco.export import (
    res_to_zonation_log,
    res_to_horizon_picks,
    export_zonation_csv,
    export_horizon_picks_csv,
    export_horizon_picks_json,
    export_zonation_las,
    correlation_summary,
)

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "demo", "data", "data_set_1.1")
WELLS_FILE = os.path.join(DATA_DIR, "wells.txt")
OUTCOME_FILE = os.path.join(DATA_DIR, "outcome_1.txt")


def _have_data():
    return os.path.isfile(WELLS_FILE) and os.path.isfile(OUTCOME_FILE)


@pytest.fixture(autouse=True)
def _skip_no_data():
    if not _have_data():
        pytest.skip("data_set_1.1 not available")


# ═══════════════════════════════════════════════════════════════════════════
#  res_to_zonation_log
# ═══════════════════════════════════════════════════════════════════════════


class TestResToZonationLog:
    def test_basic(self):
        zon = res_to_zonation_log(OUTCOME_FILE, WELLS_FILE, cor_num=0)
        assert isinstance(zon, dict)
        assert len(zon) > 0

    def test_structure(self):
        zon = res_to_zonation_log(OUTCOME_FILE, WELLS_FILE)
        for well_name, info in zon.items():
            assert isinstance(well_name, str)
            assert "zone" in info
            assert "depth" in info
            assert "n_zones" in info
            assert "zone_tops" in info
            assert "zone_bases" in info
            # Zones should be non-negative integers
            assert all(z >= 0 for z in info["zone"])
            # Number of zone tops/bases should match n_zones
            assert len(info["zone_tops"]) == info["n_zones"]
            assert len(info["zone_bases"]) == info["n_zones"]

    def test_zone_ids_start_at_zero(self):
        zon = res_to_zonation_log(OUTCOME_FILE, WELLS_FILE)
        for well_name, info in zon.items():
            assert info["zone"][0] == 0

    def test_zone_monotonic(self):
        """Zone IDs should be monotonically non-decreasing."""
        zon = res_to_zonation_log(OUTCOME_FILE, WELLS_FILE)
        for well_name, info in zon.items():
            zones = info["zone"]
            for i in range(1, len(zones)):
                assert zones[i] >= zones[i - 1]

    def test_out_of_range(self):
        with pytest.raises(IndexError):
            res_to_zonation_log(OUTCOME_FILE, WELLS_FILE, cor_num=9999)

    def test_invalid_data(self, tmp_path):
        bad = str(tmp_path / "bad.txt")
        with open(bad, "w") as f:
            f.write("garbage")
        with pytest.raises(Exception):
            res_to_zonation_log(bad, WELLS_FILE)


# ═══════════════════════════════════════════════════════════════════════════
#  res_to_horizon_picks
# ═══════════════════════════════════════════════════════════════════════════


class TestResToHorizonPicks:
    def test_basic(self):
        picks = res_to_horizon_picks(OUTCOME_FILE, WELLS_FILE, cor_num=0)
        assert isinstance(picks, list)
        assert len(picks) > 0

    def test_structure(self):
        picks = res_to_horizon_picks(OUTCOME_FILE, WELLS_FILE)
        for h in picks:
            assert "horizon" in h
            assert "picks" in h
            assert h["horizon"].startswith("H")
            assert isinstance(h["picks"], dict)
            for wn, depth in h["picks"].items():
                assert isinstance(wn, str)
                assert isinstance(depth, (int, float))

    def test_horizon_names_sequential(self):
        picks = res_to_horizon_picks(OUTCOME_FILE, WELLS_FILE)
        for i, h in enumerate(picks):
            assert h["horizon"] == f"H{i + 1:03d}"

    def test_max_horizons(self):
        all_picks = res_to_horizon_picks(OUTCOME_FILE, WELLS_FILE)
        limited = res_to_horizon_picks(OUTCOME_FILE, WELLS_FILE, max_horizons=5)
        if len(all_picks) > 5:
            assert len(limited) == 5
        else:
            assert len(limited) == len(all_picks)

    def test_out_of_range(self):
        with pytest.raises(IndexError):
            res_to_horizon_picks(OUTCOME_FILE, WELLS_FILE, cor_num=9999)


# ═══════════════════════════════════════════════════════════════════════════
#  export_zonation_csv
# ═══════════════════════════════════════════════════════════════════════════


class TestExportZonationCsv:
    def test_basic(self, tmp_path):
        zon = res_to_zonation_log(OUTCOME_FILE, WELLS_FILE)
        out = str(tmp_path / "zonation.csv")
        result = export_zonation_csv(zon, out)
        assert result == out
        assert os.path.isfile(out)

    def test_csv_header(self, tmp_path):
        zon = res_to_zonation_log(OUTCOME_FILE, WELLS_FILE)
        out = str(tmp_path / "zon.csv")
        export_zonation_csv(zon, out)
        with open(out) as f:
            reader = csv.reader(f)
            header = next(reader)
            assert header == ["Well", "Marker", "Depth", "Zone"]

    def test_csv_content(self, tmp_path):
        zon = res_to_zonation_log(OUTCOME_FILE, WELLS_FILE)
        out = str(tmp_path / "zon2.csv")
        export_zonation_csv(zon, out)
        with open(out) as f:
            reader = csv.reader(f)
            next(reader)  # header
            rows = list(reader)
            assert len(rows) > 0
            # Each row should have 4 columns
            for row in rows:
                assert len(row) == 4
                assert row[0]  # well name
                int(row[1])  # marker index
                float(row[2])  # depth
                int(row[3])  # zone


# ═══════════════════════════════════════════════════════════════════════════
#  export_horizon_picks_csv
# ═══════════════════════════════════════════════════════════════════════════


class TestExportHorizonPicksCsv:
    def test_basic(self, tmp_path):
        picks = res_to_horizon_picks(OUTCOME_FILE, WELLS_FILE)
        out = str(tmp_path / "picks.csv")
        result = export_horizon_picks_csv(picks, out)
        assert result == out
        assert os.path.isfile(out)

    def test_csv_header(self, tmp_path):
        picks = res_to_horizon_picks(OUTCOME_FILE, WELLS_FILE)
        out = str(tmp_path / "picks_h.csv")
        export_horizon_picks_csv(picks, out)
        with open(out) as f:
            reader = csv.reader(f)
            header = next(reader)
            assert header == ["Horizon", "Well", "Depth"]

    def test_csv_content(self, tmp_path):
        picks = res_to_horizon_picks(OUTCOME_FILE, WELLS_FILE)
        out = str(tmp_path / "picks_c.csv")
        export_horizon_picks_csv(picks, out)
        with open(out) as f:
            reader = csv.reader(f)
            next(reader)  # header
            rows = list(reader)
            assert len(rows) > 0
            for row in rows:
                assert len(row) == 3
                assert row[0].startswith("H")
                float(row[2])


# ═══════════════════════════════════════════════════════════════════════════
#  export_horizon_picks_json
# ═══════════════════════════════════════════════════════════════════════════


class TestExportHorizonPicksJson:
    def test_basic(self, tmp_path):
        picks = res_to_horizon_picks(OUTCOME_FILE, WELLS_FILE)
        out = str(tmp_path / "picks.json")
        result = export_horizon_picks_json(picks, out)
        assert result == out
        assert os.path.isfile(out)

    def test_json_content(self, tmp_path):
        picks = res_to_horizon_picks(OUTCOME_FILE, WELLS_FILE)
        out = str(tmp_path / "picks_j.json")
        export_horizon_picks_json(picks, out)
        with open(out) as f:
            data = json.load(f)
        assert isinstance(data, list)
        assert len(data) == len(picks)
        for h in data:
            assert "horizon" in h
            assert "picks" in h

    def test_roundtrip_consistency(self, tmp_path):
        """JSON output should be loadable and match original picks."""
        picks = res_to_horizon_picks(OUTCOME_FILE, WELLS_FILE)
        out = str(tmp_path / "rt.json")
        export_horizon_picks_json(picks, out)
        with open(out) as f:
            loaded = json.load(f)
        for orig, load in zip(picks, loaded):
            assert orig["horizon"] == load["horizon"]
            for wn in orig["picks"]:
                assert abs(orig["picks"][wn] - load["picks"][wn]) < 1e-4


# ═══════════════════════════════════════════════════════════════════════════
#  export_zonation_las
# ═══════════════════════════════════════════════════════════════════════════


class TestExportZonationLas:
    def test_basic(self, tmp_path):
        zon = res_to_zonation_log(OUTCOME_FILE, WELLS_FILE)
        out_dir = str(tmp_path / "las_out")
        paths = export_zonation_las(zon, out_dir)
        assert len(paths) > 0
        for p in paths:
            assert os.path.isfile(p)
            assert p.endswith("_zonation.las")

    def test_creates_directory(self, tmp_path):
        zon = res_to_zonation_log(OUTCOME_FILE, WELLS_FILE)
        out_dir = str(tmp_path / "new_las_dir")
        assert not os.path.exists(out_dir)
        export_zonation_las(zon, out_dir)
        assert os.path.isdir(out_dir)

    def test_las_format(self, tmp_path):
        zon = res_to_zonation_log(OUTCOME_FILE, WELLS_FILE)
        out_dir = str(tmp_path / "las_fmt")
        paths = export_zonation_las(zon, out_dir)
        for p in paths:
            with open(p) as f:
                content = f.read()
            assert "~VERSION INFORMATION" in content
            assert "VERS." in content
            assert "2.0" in content
            assert "~WELL INFORMATION" in content
            assert "~CURVE INFORMATION" in content
            assert "ZONE" in content
            assert "~A" in content

    def test_one_file_per_well(self, tmp_path):
        zon = res_to_zonation_log(OUTCOME_FILE, WELLS_FILE)
        out_dir = str(tmp_path / "las_count")
        paths = export_zonation_las(zon, out_dir)
        assert len(paths) == len(zon)


# ═══════════════════════════════════════════════════════════════════════════
#  correlation_summary
# ═══════════════════════════════════════════════════════════════════════════


class TestCorrelationSummary:
    def test_basic(self):
        summary = correlation_summary(OUTCOME_FILE, WELLS_FILE, n_best=3)
        assert "n_results" in summary
        assert "well_names" in summary
        assert "results" in summary
        assert isinstance(summary["well_names"], list)
        assert len(summary["well_names"]) > 0

    def test_results_structure(self):
        summary = correlation_summary(OUTCOME_FILE, WELLS_FILE, n_best=5)
        for r in summary["results"]:
            assert "rank" in r
            assert "cost" in r
            assert "n_horizons" in r
            assert "n_gaps" in r
            assert r["cost"] >= 0.0
            assert r["n_horizons"] >= 0
            assert r["n_gaps"] >= 0

    def test_ordered_by_rank(self):
        summary = correlation_summary(OUTCOME_FILE, WELLS_FILE, n_best=5)
        ranks = [r["rank"] for r in summary["results"]]
        assert ranks == sorted(ranks)

    def test_n_best_limits(self):
        s1 = correlation_summary(OUTCOME_FILE, WELLS_FILE, n_best=1)
        assert len(s1["results"]) == 1


# ═══════════════════════════════════════════════════════════════════════════
# §15.18 — Round-trip tests for new export formats
# ═══════════════════════════════════════════════════════════════════════════


class TestExportCorrelationSurfaces:
    """Test export_correlation_surfaces (§15.5)."""

    def test_surfaces_created(self, tmp_path):
        from weco.export import export_correlation_surfaces
        out_dir = str(tmp_path / "surfaces")
        created = export_correlation_surfaces(
            OUTCOME_FILE, WELLS_FILE, out_dir, cor_num=0,
        )
        # May produce 0 surfaces if < 3 wells per horizon
        assert isinstance(created, list)

    def test_surfaces_are_gocad_ts(self, tmp_path):
        from weco.export import export_correlation_surfaces
        out_dir = str(tmp_path / "surfaces")
        created = export_correlation_surfaces(
            OUTCOME_FILE, WELLS_FILE, out_dir, cor_num=0,
        )
        for path in created:
            assert path.endswith(".ts")
            with open(path) as f:
                first_line = f.readline().strip()
            assert first_line.startswith("GOCAD TSurf")


class TestExportSeamTable:
    """Test export_seam_table (§15.13)."""

    def test_basic(self, tmp_path):
        from weco.export import export_seam_table
        out = str(tmp_path / "seams.csv")
        result = export_seam_table(OUTCOME_FILE, WELLS_FILE, out)
        assert os.path.isfile(result)
        with open(result) as f:
            header = f.readline()
        assert "well" in header
        assert "seam" in header


class TestExportModflowLayers:
    """Test export_modflow_layers (§15.14)."""

    def test_basic(self, tmp_path):
        from weco.export import export_modflow_layers
        out = str(tmp_path / "modflow.csv")
        result = export_modflow_layers(OUTCOME_FILE, WELLS_FILE, out)
        assert os.path.isfile(result)
        with open(result) as f:
            header = f.readline()
        assert "well" in header
        assert "layer" in header
        assert "top_elevation" in header


class TestExportContinuousLogs:
    """Test export_continuous_logs (§15.15)."""

    def test_las_format(self, tmp_path):
        from weco.export import export_continuous_logs
        from weco.data import WellList
        wl = WellList(WELLS_FILE)
        out_dir = str(tmp_path / "logs_las")
        created = export_continuous_logs(wl, out_dir, fmt="las")
        assert len(created) > 0
        for path in created:
            assert path.endswith(".las")
            assert os.path.isfile(path)

    def test_csv_format(self, tmp_path):
        from weco.export import export_continuous_logs
        from weco.data import WellList
        wl = WellList(WELLS_FILE)
        out_dir = str(tmp_path / "logs_csv")
        created = export_continuous_logs(wl, out_dir, fmt="csv")
        assert len(created) > 0
        for path in created:
            assert path.endswith(".csv")
