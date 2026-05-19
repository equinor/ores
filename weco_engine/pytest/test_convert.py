"""
Tests for weco.convert — WeCoConvert CLI
=========================================

Tests the main() CLI entry point for format conversion with
multiple scenarios: happy paths, error handling, flags.
"""

import os

import pytest

from weco.convert import main

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "demo", "data", "data_set_1.1")
WELLS_FILE = os.path.join(DATA_DIR, "wells.txt")


def _have_data():
    return os.path.isfile(WELLS_FILE)


@pytest.fixture(autouse=True)
def _skip_no_data():
    if not _have_data():
        pytest.skip("data_set_1.1 not available")


class TestWeCoConvertCLI:
    """Tests for WeCoConvert CLI entry point."""

    def test_weco_to_csv(self, tmp_path):
        out = str(tmp_path / "out.csv")
        ret = main([WELLS_FILE, out])
        assert ret == 0
        assert os.path.isfile(out)

    def test_weco_to_las(self, tmp_path):
        out = str(tmp_path / "out.las")
        ret = main([WELLS_FILE, out])
        assert ret == 0
        # With 3 wells, output is split into per-well LAS files in tmp_path
        las_files = list(tmp_path.glob("*.las"))
        assert len(las_files) >= 1

    def test_weco_to_csv_explicit_fmt(self, tmp_path):
        out = str(tmp_path / "out.data")
        ret = main([WELLS_FILE, out, "--fmt-in", "weco", "--fmt-out", "csv"])
        assert ret == 0
        assert os.path.isfile(out)

    def test_verbose(self, tmp_path, capsys):
        out = str(tmp_path / "v.csv")
        ret = main([WELLS_FILE, out, "--verbose"])
        assert ret == 0
        captured = capsys.readouterr()
        assert "Reading" in captured.out or "Converted" in captured.out

    def test_csv_to_weco_roundtrip(self, tmp_path):
        csv_path = str(tmp_path / "step1.csv")
        weco_path = str(tmp_path / "step2.wells.txt")
        # Step 1: weco → csv
        assert main([WELLS_FILE, csv_path]) == 0
        # Step 2: csv → weco
        assert main([csv_path, weco_path, "--fmt-out", "weco"]) == 0
        assert os.path.isfile(weco_path)

    def test_unknown_input_format(self, tmp_path, capsys):
        bad_input = str(tmp_path / "data.xyz")
        with open(bad_input, "w") as f:
            f.write("garbage")
        out = str(tmp_path / "out.csv")
        ret = main([bad_input, out])
        assert ret == 1

    def test_unknown_output_format(self, tmp_path, capsys):
        out = str(tmp_path / "out.xyz")
        ret = main([WELLS_FILE, out])
        assert ret == 1

    def test_nonexistent_input(self, tmp_path):
        out = str(tmp_path / "out.csv")
        ret = main(["/nonexistent/path/file.wells.txt", out])
        assert ret == 1

    def test_well_filter(self, tmp_path):
        out = str(tmp_path / "filtered.csv")
        ret = main([WELLS_FILE, out, "--wells", "Well_01"])
        assert ret == 0
        assert os.path.isfile(out)
        # Output should only have Well_01 data
        with open(out) as f:
            content = f.read()
        assert "Well_01" in content
