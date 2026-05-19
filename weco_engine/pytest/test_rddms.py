"""
Tests for weco.rddms — Universal well-data bridge
===================================================

Tests the core conversion layer (§2), format round-trips (§7, §8),
RMS pick import (§9), universal converter (§10), and utilities (§11).

RDDMS/EPC tests that require the GOCAD RESQML package are marked
with ``@pytest.mark.skipif(not _resqml_available, ...)``.
"""

import os
import tempfile
import json

import numpy as np
import pytest

from weco.data import Well, WellList
from weco.rddms import (
    # core converters
    resqml_to_weco,
    weco_to_resqml,
    # LAS
    las_import_wells,
    las_export_wells,
    # CSV
    csv_import_wells,
    csv_export_wells,
    csv_export_picks,
    # RMS
    rms_import_well_picks,
    # universal
    convert,
    # utilities
    summarise_well_list,
    compare_well_lists,
    is_available,
)

# Try to import RESQML types for RESQML-specific tests
_resqml_available = is_available()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def sample_well():
    """A single Well with continuous + discrete data."""
    w = Well()
    w.name = "TestWell_A"
    w.size = 30
    w.x = 500000.0
    w.y = 6600000.0
    w.z = 0.0
    w.h = 300.0
    w.data["Depth"] = list(np.linspace(100, 400, 30))
    w.data["GR"] = list(np.random.RandomState(42).uniform(20, 120, 30))
    w.data["RT"] = list(np.random.RandomState(43).uniform(1, 50, 30))
    # Discrete facies log
    facies = list(np.random.RandomState(44).choice([1, 2, 3], 30))
    w.data["Facies"] = [float(f) for f in facies]
    w.add_region_from_data("Facies")
    return w


@pytest.fixture
def sample_well_list(sample_well):
    """A WellList with 3 wells."""
    wl = WellList.__new__(WellList)
    wl.wells = []
    for i in range(3):
        w = Well()
        w.name = f"Well_{chr(65 + i)}"
        w.size = sample_well.size
        w.x = sample_well.x + i * 1000
        w.y = sample_well.y + i * 500
        w.z = sample_well.z
        w.h = sample_well.h
        w.data = dict(sample_well.data)  # shallow copy is fine for lists
        w.data["GR"] = list(np.random.RandomState(42 + i).uniform(20, 120, 30))
        w.region = dict(sample_well.region)
        wl.wells.append(w)
    return wl


@pytest.fixture
def sample_picks():
    """Horizon picks in weco.export format."""
    return [
        {"horizon": "H001", "picks": {"Well_A": 150.0, "Well_B": 155.0, "Well_C": 148.0}},
        {"horizon": "H002", "picks": {"Well_A": 200.0, "Well_B": 210.0, "Well_C": 198.0}},
        {"horizon": "H003", "picks": {"Well_A": 280.0, "Well_B": 290.0, "Well_C": 275.0}},
    ]


# ===================================================================
# §2 Core conversion: WeCo ↔ ResqmlObject
# ===================================================================

class TestCoreConversion:
    """Tests for resqml_to_weco / weco_to_resqml."""

    @pytest.mark.skipif(not _resqml_available, reason="GOCAD RESQML not available")
    def test_weco_to_resqml_basic(self, sample_well):
        obj = weco_to_resqml(sample_well)
        assert obj.kind == "well"
        assert obj.info.title == "TestWell_A"
        assert obj.points.shape == (30, 3)
        assert "md" in obj.properties
        assert len(obj.property_meta) >= 2  # GR, RT, Facies

    @pytest.mark.skipif(not _resqml_available, reason="GOCAD RESQML not available")
    def test_round_trip_preserves_name(self, sample_well):
        obj = weco_to_resqml(sample_well)
        w2 = resqml_to_weco(obj)
        assert w2.name == sample_well.name

    @pytest.mark.skipif(not _resqml_available, reason="GOCAD RESQML not available")
    def test_round_trip_preserves_size(self, sample_well):
        obj = weco_to_resqml(sample_well)
        w2 = resqml_to_weco(obj)
        assert w2.size == sample_well.size

    @pytest.mark.skipif(not _resqml_available, reason="GOCAD RESQML not available")
    def test_round_trip_preserves_continuous_data(self, sample_well):
        obj = weco_to_resqml(sample_well)
        w2 = resqml_to_weco(obj)
        gr_a = np.array(sample_well.data["GR"])
        gr_b = np.array(w2.data["GR"])
        np.testing.assert_allclose(gr_a, gr_b, atol=1e-4)

    @pytest.mark.skipif(not _resqml_available, reason="GOCAD RESQML not available")
    def test_round_trip_preserves_discrete_region(self, sample_well):
        obj = weco_to_resqml(sample_well)
        w2 = resqml_to_weco(obj)
        assert "Facies" in w2.region
        assert len(w2.region["Facies"]) > 0

    @pytest.mark.skipif(not _resqml_available, reason="GOCAD RESQML not available")
    def test_round_trip_preserves_coordinates(self, sample_well):
        obj = weco_to_resqml(sample_well)
        w2 = resqml_to_weco(obj)
        assert abs(w2.x - sample_well.x) < 0.01
        assert abs(w2.y - sample_well.y) < 0.01

    @pytest.mark.skipif(not _resqml_available, reason="GOCAD RESQML not available")
    def test_round_trip_preserves_depth(self, sample_well):
        obj = weco_to_resqml(sample_well)
        w2 = resqml_to_weco(obj)
        d_a = np.array(sample_well.data["Depth"])
        d_b = np.array(w2.data["Depth"])
        np.testing.assert_allclose(d_a, d_b, atol=1e-4)

    @pytest.mark.skipif(not _resqml_available, reason="GOCAD RESQML not available")
    def test_empty_well(self):
        w = Well()
        w.name = "Empty"
        w.size = 0
        obj = weco_to_resqml(w)
        assert obj.points.shape == (0, 3)
        w2 = resqml_to_weco(obj)
        assert w2.size == 0

    @pytest.mark.skipif(not _resqml_available, reason="GOCAD RESQML not available")
    def test_discrete_property_marked_discrete(self, sample_well):
        obj = weco_to_resqml(sample_well)
        facies_meta = [pm for pm in obj.property_meta if pm.title == "Facies"]
        assert len(facies_meta) == 1
        assert facies_meta[0].kind == "discrete"

    @pytest.mark.skipif(not _resqml_available, reason="GOCAD RESQML not available")
    def test_xyz_channels_added_on_import(self, sample_well):
        obj = weco_to_resqml(sample_well)
        w2 = resqml_to_weco(obj)
        assert "X" in w2.data
        assert "Y" in w2.data
        assert "Z" in w2.data


# ===================================================================
# §7 LAS round-trip
# ===================================================================

class TestLASBridge:
    def test_export_creates_files(self, sample_well_list, tmp_dir):
        paths = las_export_wells(sample_well_list, tmp_dir)
        assert len(paths) == 3
        for p in paths:
            assert os.path.isfile(p)
            assert p.endswith(".las")

    def test_export_file_has_header(self, sample_well_list, tmp_dir):
        paths = las_export_wells(sample_well_list, tmp_dir)
        with open(paths[0]) as f:
            content = f.read()
        assert "~VERSION" in content
        assert "~WELL" in content
        assert "~CURVE" in content
        assert "~A" in content
        assert "Well_A" in content

    def test_export_file_has_coordinates(self, sample_well_list, tmp_dir):
        paths = las_export_wells(sample_well_list, tmp_dir)
        with open(paths[0]) as f:
            content = f.read()
        assert "XCOORD" in content
        assert "YCOORD" in content

    def test_export_import_round_trip(self, sample_well_list, tmp_dir):
        paths = las_export_wells(sample_well_list, tmp_dir)
        wl2 = las_import_wells(paths)
        assert len(wl2.wells) == 3

    def test_export_import_preserves_data(self, sample_well_list, tmp_dir):
        paths = las_export_wells(sample_well_list, tmp_dir)
        wl2 = las_import_wells(paths)
        for w in wl2.wells:
            # LAS reader maps DEPT → DEPT (not Depth)
            assert "DEPT" in w.data or "Depth" in w.data

    def test_glob_import(self, sample_well_list, tmp_dir):
        las_export_wells(sample_well_list, tmp_dir)
        pattern = os.path.join(tmp_dir, "*.las")
        wl2 = las_import_wells(pattern)
        assert len(wl2.wells) == 3


# ===================================================================
# §8 CSV round-trip
# ===================================================================

class TestCSVBridge:
    def test_export_creates_file(self, sample_well_list, tmp_dir):
        path = csv_export_wells(sample_well_list,
                                os.path.join(tmp_dir, "wells.csv"))
        assert os.path.isfile(path)

    def test_export_has_header(self, sample_well_list, tmp_dir):
        path = csv_export_wells(sample_well_list,
                                os.path.join(tmp_dir, "wells.csv"))
        with open(path) as f:
            header = f.readline().strip()
        assert "Well" in header
        assert "Depth" in header

    def test_export_import_round_trip(self, sample_well_list, tmp_dir):
        path = csv_export_wells(sample_well_list,
                                os.path.join(tmp_dir, "wells.csv"))
        wl2 = csv_import_wells(path)
        assert len(wl2.wells) == 3

    def test_preserves_discrete_columns(self, sample_well_list, tmp_dir):
        path = csv_export_wells(sample_well_list,
                                os.path.join(tmp_dir, "wells.csv"))
        wl2 = csv_import_wells(path, discrete_columns=["Facies"])
        for w in wl2.wells:
            assert "Facies" in w.region

    def test_tsv_separator(self, sample_well_list, tmp_dir):
        path = csv_export_wells(sample_well_list,
                                os.path.join(tmp_dir, "wells.tsv"),
                                separator="\t")
        wl2 = csv_import_wells(path, separator="\t")
        assert len(wl2.wells) == 3

    def test_csv_export_picks(self, sample_picks, tmp_dir):
        path = csv_export_picks(sample_picks,
                                os.path.join(tmp_dir, "picks.csv"))
        assert os.path.isfile(path)
        with open(path) as f:
            lines = f.readlines()
        assert len(lines) == 10  # header + 9 picks (3 horizons × 3 wells)

    def test_csv_export_picks_with_coordinates(self, sample_picks,
                                                sample_well_list, tmp_dir):
        path = csv_export_picks(
            sample_picks,
            os.path.join(tmp_dir, "picks_xy.csv"),
            well_list=sample_well_list,
        )
        with open(path) as f:
            header = f.readline().strip()
        assert "X" in header
        assert "Y" in header


# ===================================================================
# §9 RMS pick import
# ===================================================================

class TestRMSBridge:
    def test_import_well_picks(self, tmp_dir):
        # Write an RMS-format picks file
        pick_path = os.path.join(tmp_dir, "picks.txt")
        with open(pick_path, "w") as f:
            f.write("# RMS Well Picks\n")
            f.write("Well\tSurface\tMD\n")
            f.write("W1\tTop_A\t100.0\n")
            f.write("W1\tTop_B\t200.0\n")
            f.write("W2\tTop_A\t105.0\n")
            f.write("W2\tTop_B\t210.0\n")

        picks = rms_import_well_picks(pick_path)
        assert len(picks) == 2
        top_a = next(p for p in picks if p["horizon"] == "Top_A")
        assert "W1" in top_a["picks"]
        assert abs(top_a["picks"]["W1"] - 100.0) < 0.01

    def test_import_empty_file(self, tmp_dir):
        pick_path = os.path.join(tmp_dir, "empty.txt")
        with open(pick_path, "w") as f:
            f.write("# empty\n")
        picks = rms_import_well_picks(pick_path)
        assert picks == []


# ===================================================================
# §10 Universal converter
# ===================================================================

class TestConverter:
    def test_weco_to_csv(self, sample_well_list, tmp_dir):
        # Write sample as WeCo native first
        weco_path = os.path.join(tmp_dir, "test.wells.txt")
        sample_well_list.write(weco_path)

        csv_path = os.path.join(tmp_dir, "out.csv")
        result = convert(weco_path, csv_path, fmt_out="csv")
        assert os.path.isfile(csv_path)

    def test_csv_to_las(self, sample_well_list, tmp_dir):
        # Write CSV first
        csv_path = os.path.join(tmp_dir, "wells.csv")
        csv_export_wells(sample_well_list, csv_path)

        las_dir = os.path.join(tmp_dir, "las_out")
        os.makedirs(las_dir)
        result = convert(csv_path, las_dir, fmt_in="csv", fmt_out="las")

    def test_auto_detect_weco(self, sample_well_list, tmp_dir):
        path = os.path.join(tmp_dir, "test.wells.txt")
        sample_well_list.write(path)
        from weco.formats import detect_format
        assert detect_format(path) == "weco"

    def test_auto_detect_csv(self, tmp_dir):
        path = os.path.join(tmp_dir, "data.csv")
        with open(path, "w") as f:
            f.write("Well,Depth,GR\nW1,100,50\n")
        from weco.formats import detect_format
        assert detect_format(path) == "csv"


# ===================================================================
# §11 Utilities
# ===================================================================

class TestUtilities:
    def test_summarise_well_list(self, sample_well_list):
        s = summarise_well_list(sample_well_list)
        assert s["n_wells"] == 3
        assert len(s["wells"]) == 3
        w0 = s["wells"][0]
        assert w0["size"] == 30
        assert "GR" in w0["continuous"]
        assert "Facies" in w0["discrete"]

    def test_compare_identical(self, sample_well_list):
        # Compare with itself
        cmp = compare_well_lists(sample_well_list, sample_well_list)
        assert cmp["match"] is True

    def test_compare_detects_missing_well(self, sample_well_list):
        wl2 = WellList.__new__(WellList)
        wl2.wells = sample_well_list.wells[:2]  # only 2 of 3
        cmp = compare_well_lists(sample_well_list, wl2)
        assert cmp["match"] is False
        # Third well should show as only_in_A
        missing = [n for n, v in cmp["wells"].items()
                    if v.get("status") == "only_in_A"]
        assert len(missing) == 1

    @pytest.mark.skipif(not _resqml_available, reason="GOCAD RESQML not available")
    def test_compare_after_resqml_round_trip(self, sample_well_list):
        wl2 = WellList.__new__(WellList)
        wl2.wells = [resqml_to_weco(weco_to_resqml(w))
                      for w in sample_well_list.wells]
        cmp = compare_well_lists(sample_well_list, wl2,
                                  tolerance=1e-3)
        # GR/RT/Depth should match; extra X/Y/Z channels = only_in_B is OK
        for wn, info in cmp["wells"].items():
            assert info.get("size_match") is True
            chans = info.get("channels", {})
            for c in ("Depth", "GR", "RT"):
                if c in chans and isinstance(chans[c], dict):
                    assert chans[c]["match"] is True

    def test_is_available_returns_bool(self):
        assert isinstance(is_available(), bool)


# ===================================================================
# Workflow integration (new methods)
# ===================================================================

class TestWorkflowIntegration:
    """Test the new import_*/export_* methods on CorrelationWorkflow."""

    def test_import_csv_method(self, sample_well_list, tmp_dir):
        from weco.workflow import CorrelationWorkflow

        # Write CSV
        csv_path = os.path.join(tmp_dir, "wells.csv")
        csv_export_wells(sample_well_list, csv_path)

        wf = CorrelationWorkflow("CSV_Test")
        wf.import_csv(csv_path)
        assert wf.well_list is not None
        assert len(wf.well_list.wells) == 3

    def test_export_las_method(self, sample_well_list, tmp_dir):
        from weco.workflow import CorrelationWorkflow

        wf = CorrelationWorkflow("LAS_Test")
        # Use synthetic data, not file-based import
        wf.well_list = sample_well_list
        wf._record("import_synthetic", n_wells=len(sample_well_list.wells))

        las_dir = os.path.join(tmp_dir, "las_out")
        paths = wf.export_las(las_dir)
        assert len(paths) > 0
        for p in paths:
            assert os.path.isfile(p)

    def test_new_methods_exist(self):
        from weco.workflow import CorrelationWorkflow
        wf = CorrelationWorkflow("Check")
        for method in ["import_rddms", "import_epc", "import_gocad",
                        "import_csv", "export_rddms", "export_epc",
                        "export_gocad", "export_las"]:
            assert hasattr(wf, method), f"Missing {method}"
            assert callable(getattr(wf, method))


# ===================================================================
# Format registry
# ===================================================================

class TestFormatRegistry:
    def test_gocad_well_reader_registered(self):
        from weco.formats import _READERS
        assert "gocad_well" in _READERS

    def test_rddms_reader_registered(self):
        from weco.formats import _READERS
        assert "rddms" in _READERS

    def test_csv_writer_registered(self):
        from weco.formats import _WRITERS
        assert "csv" in _WRITERS

    def test_gocad_writer_registered(self):
        from weco.formats import _WRITERS
        assert "gocad_well" in _WRITERS

    def test_epc_writer_registered(self):
        from weco.formats import _WRITERS
        assert "resqml" in _WRITERS

    def test_write_wells_csv(self, sample_well_list, tmp_dir):
        from weco.formats import write_wells
        path = os.path.join(tmp_dir, "out.csv")
        write_wells(sample_well_list, path, fmt="csv")
        assert os.path.isfile(path)


# ===================================================================
# §4.11 WeCoConvert CLI
# ===================================================================

class TestWeCoConvertCLI:
    """Tests for the WeCoConvert command-line tool (weco.convert)."""

    def test_weco_to_csv(self, sample_well_list, tmp_dir):
        """Convert native weco → csv via CLI entry point."""
        from weco.convert import main as convert_main
        weco_path = os.path.join(tmp_dir, "input.wells.txt")
        sample_well_list.write(weco_path)
        csv_path = os.path.join(tmp_dir, "output.csv")
        rc = convert_main([weco_path, csv_path])
        assert rc == 0
        assert os.path.isfile(csv_path)

    def test_csv_to_weco(self, sample_well_list, tmp_dir):
        """Convert csv → weco via CLI entry point."""
        from weco.convert import main as convert_main
        from weco.rddms import csv_export_wells
        csv_path = os.path.join(tmp_dir, "src.csv")
        csv_export_wells(sample_well_list, csv_path)
        weco_path = os.path.join(tmp_dir, "result.wells.txt")
        rc = convert_main([csv_path, weco_path, "--fmt-out", "weco"])
        assert rc == 0

    def test_verbose_flag(self, sample_well_list, tmp_dir):
        from weco.convert import main as convert_main
        weco_path = os.path.join(tmp_dir, "v.wells.txt")
        sample_well_list.write(weco_path)
        csv_path = os.path.join(tmp_dir, "v.csv")
        rc = convert_main([weco_path, csv_path, "-v"])
        assert rc == 0
        assert os.path.isfile(csv_path)

    def test_unknown_input_format(self):
        from weco.convert import main as convert_main
        rc = convert_main(["unknown.xyz", "out.csv"])
        assert rc == 1

    def test_well_filter(self, sample_well_list, tmp_dir):
        """--wells flag should subset output."""
        from weco.convert import main as convert_main
        weco_path = os.path.join(tmp_dir, "filt.wells.txt")
        sample_well_list.write(weco_path)
        csv_path = os.path.join(tmp_dir, "filt.csv")
        first_name = sample_well_list.wells[0].name
        rc = convert_main([weco_path, csv_path, "--wells", first_name])
        assert rc == 0


# ── §2.2 Production dataspace tests ──────────────────────────────────────

_production_url = os.environ.get("RDDMS_PRODUCTION_URL", "")


@pytest.mark.skipif(
    not _production_url,
    reason="Production RDDMS not configured (set RDDMS_PRODUCTION_URL)",
)
class TestRDDMSProduction:
    """End-to-end RDDMS tests against a production dataspace."""

    def test_connect(self):
        from weco.rddms import RDDMSClient
        client = RDDMSClient(url=_production_url)
        assert client.ping()

    def test_list_wells(self):
        from weco.rddms import RDDMSClient
        client = RDDMSClient(url=_production_url)
        wells = client.list_wells()
        assert isinstance(wells, list)

    def test_roundtrip(self, sample_well_list):
        from weco.rddms import RDDMSClient
        client = RDDMSClient(url=_production_url)
        # Write, read back, compare
        client.upload(sample_well_list, namespace="weco_test")
        wl = client.download(namespace="weco_test")
        assert wl.nbr_well() == sample_well_list.nbr_well()
