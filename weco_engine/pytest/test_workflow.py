"""Tests for weco.workflow, weco.rms_export, and enhanced format handling."""

import json
import os
import shutil
import tempfile

import pytest

from weco.data import WellList, Well
from weco.workflow import CorrelationWorkflow, PRESETS, quick_correlate


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

DATA_1_1 = os.path.join(os.path.dirname(__file__), "..", "demo", "data", "data_set_1.1", "wells.txt")
OPT_1_1 = os.path.join(os.path.dirname(__file__), "..", "demo", "data", "data_set_1.1", "option_1.txt")


@pytest.fixture
def tmp_dir():
    d = tempfile.mkdtemp(prefix="weco_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def workflow(tmp_dir):
    wf = CorrelationWorkflow("Test", working_dir=tmp_dir)
    wf.import_wells(DATA_1_1)
    return wf


# ---------------------------------------------------------------------------
# Tests: Workflow
# ---------------------------------------------------------------------------

class TestWorkflow:
    def test_presets(self):
        presets = CorrelationWorkflow.list_presets()
        assert "shallow_marine" in presets
        assert "deep_marine" in presets
        assert "default" in presets
        assert len(presets) >= 5

    def test_import(self, workflow):
        assert len(workflow.well_list.wells) == 3
        assert workflow._step_count == 1

    def test_configure_preset(self, workflow):
        workflow.configure(preset="shallow_marine",
                           cost_logs=["VarData1"],
                           cost_weights=[1.0])
        assert workflow.preset_name == "shallow_marine"
        assert "cost-function" in workflow.options
        assert workflow._cost_logs == ["VarData1"]

    def test_configure_invalid_preset(self, workflow):
        with pytest.raises(ValueError, match="Unknown preset"):
            workflow.configure(preset="nonexistent")

    def test_run(self, workflow):
        workflow.configure(preset="default",
                           cost_logs=["VarData1", "VarData2"],
                           cost_weights=[1.0, 1.0])
        workflow.run()
        assert workflow.res_file is not None
        assert workflow.res_file.get_nbr_results() > 0

    def test_run_with_options_file(self, workflow):
        workflow.configure(preset="default")
        workflow.run(options_file=OPT_1_1)
        assert workflow.res_file is not None
        assert workflow.res_file.get_nbr_results() > 0

    def test_export_rms(self, workflow, tmp_dir):
        workflow.configure(preset="default",
                           cost_logs=["VarData1"],
                           cost_weights=[1.0])
        workflow.run()
        rms_dir = os.path.join(tmp_dir, "rms")
        manifest = workflow.export_rms(rms_dir)

        assert os.path.exists(manifest["well_picks"])
        assert os.path.exists(manifest["zone_picks"])
        assert os.path.exists(manifest["summary"])
        assert len(manifest["zonation_las"]) == 3
        assert manifest["n_horizons"] > 0
        assert manifest["n_zones"] > 0

    def test_export_csv(self, workflow, tmp_dir):
        workflow.configure(preset="default",
                           cost_logs=["VarData1"],
                           cost_weights=[1.0])
        workflow.run()
        csv_dir = os.path.join(tmp_dir, "csv")
        paths = workflow.export_csv(csv_dir)

        assert os.path.exists(paths["zonation_csv"])
        assert os.path.exists(paths["picks_csv"])
        assert os.path.exists(paths["picks_json"])

    def test_save_report(self, workflow, tmp_dir):
        workflow.configure(preset="default",
                           cost_logs=["VarData1"],
                           cost_weights=[1.0])
        workflow.run()
        report_path = os.path.join(tmp_dir, "report.json")
        workflow.save_report(report_path)

        with open(report_path) as f:
            report = json.load(f)

        assert report["study_name"] == "Test"
        assert report["n_wells"] == 3
        assert len(report["steps"]) >= 3  # import + configure + run + report
        assert report["preset"] == "default"

    def test_repr(self, workflow):
        s = repr(workflow)
        assert "Test" in s
        assert "wells=3" in s

    def test_method_chaining(self, tmp_dir):
        wf = (CorrelationWorkflow("Chain", working_dir=tmp_dir)
              .import_wells(DATA_1_1)
              .configure(preset="default",
                         cost_logs=["VarData1"],
                         cost_weights=[1.0])
              .run())
        assert wf.res_file is not None


# ---------------------------------------------------------------------------
# Tests: RMS Export
# ---------------------------------------------------------------------------

class TestRMSExport:
    def test_well_picks_format(self, workflow, tmp_dir):
        from weco.rms_export import export_rms_well_picks
        from weco.export import res_to_horizon_picks

        workflow.configure(preset="default",
                           cost_logs=["VarData1"],
                           cost_weights=[1.0])
        workflow.run()

        picks = res_to_horizon_picks(workflow.res_file, workflow.well_list)
        out_path = os.path.join(tmp_dir, "picks.txt")
        export_rms_well_picks(picks, out_path, well_list=workflow.well_list)

        with open(out_path) as f:
            lines = f.readlines()

        # Check header
        assert any("RMS Well Picks" in l for l in lines)
        # Check column header
        header_line = [l for l in lines if not l.startswith("#")][0]
        assert "Well" in header_line
        assert "Surface" in header_line
        assert "MD" in header_line
        # Check data lines
        data_lines = [l for l in lines if not l.startswith("#")][1:]
        assert len(data_lines) > 0

    def test_zone_picks_format(self, workflow, tmp_dir):
        from weco.rms_export import export_rms_zone_picks
        from weco.export import res_to_zonation_log

        workflow.configure(preset="default",
                           cost_logs=["VarData1"],
                           cost_weights=[1.0])
        workflow.run()

        zonation = res_to_zonation_log(workflow.res_file, workflow.well_list)
        out_path = os.path.join(tmp_dir, "zones.txt")
        export_rms_zone_picks(zonation, out_path, well_list=workflow.well_list)

        with open(out_path) as f:
            content = f.read()

        assert "Top_Zone_00" in content
        assert "Well_01" in content

    def test_discrete_log_export(self, tmp_dir):
        from weco.rms_export import export_rms_discrete_log

        # Create a well with a region
        w = Well()
        w.name = "TestWell"
        w.size = 10
        w.data["Depth"] = list(range(10))
        w.region["FACIES"] = [(1, 0, 3), (2, 3, 4), (1, 7, 3)]

        out_path = os.path.join(tmp_dir, "facies.las")
        code_table = {1: "Sand", 2: "Shale"}
        export_rms_discrete_log(w, "FACIES", out_path, code_table=code_table)

        with open(out_path) as f:
            content = f.read()

        assert "FACIES" in content
        assert "Sand" in content
        assert "Shale" in content
        assert "~A" in content

    def test_code_table_export(self, tmp_dir):
        from weco.rms_export import export_rms_code_table

        table = {1: "Sand", 2: "Shale", 3: "Silt"}
        out_path = os.path.join(tmp_dir, "codes.txt")
        export_rms_code_table(table, out_path, table_name="Lithology")

        with open(out_path) as f:
            content = f.read()

        assert "Sand" in content
        assert "Shale" in content
        assert "Silt" in content

    def test_rms_package(self, workflow, tmp_dir):
        from weco.rms_export import export_rms_package

        workflow.configure(preset="default",
                           cost_logs=["VarData1"],
                           cost_weights=[1.0])
        workflow.run()

        pkg_dir = os.path.join(tmp_dir, "rms_pkg")
        manifest = export_rms_package(
            workflow.res_file, workflow.well_list, pkg_dir,
            include_script=True, include_points=True)

        assert os.path.isdir(pkg_dir)
        assert os.path.exists(manifest["well_picks"])
        assert os.path.exists(manifest["zone_picks"])
        assert os.path.exists(manifest["summary"])
        assert manifest["import_script"] is not None
        assert os.path.exists(manifest["import_script"])

    def test_rms_import_script_is_valid_python(self, workflow, tmp_dir):
        """Verify generated import script is syntactically valid Python."""
        workflow.configure(preset="default",
                           cost_logs=["VarData1"],
                           cost_weights=[1.0])
        workflow.run()

        pkg_dir = os.path.join(tmp_dir, "rms_pkg2")
        manifest = workflow.export_rms(pkg_dir)

        with open(manifest["import_script"]) as f:
            code = f.read()

        # Should compile without syntax errors
        compile(code, manifest["import_script"], "exec")


# ---------------------------------------------------------------------------
# Tests: Quick correlate
# ---------------------------------------------------------------------------

class TestQuickCorrelate:
    def test_quick_correlate(self, tmp_dir):
        out = os.path.join(tmp_dir, "quick")
        manifest = quick_correlate(
            DATA_1_1, out,
            preset="default",
            cost_logs=["VarData1", "VarData2"],
            cost_weights=[1.0, 1.0])

        assert manifest["n_horizons"] > 0
        assert manifest["n_zones"] > 0
        assert os.path.exists(os.path.join(out, "report.json"))


# ---------------------------------------------------------------------------
# Tests: Format registry
# ---------------------------------------------------------------------------

class TestFormats:
    def test_las_discrete_reader_registered(self):
        from weco.formats import _READERS
        assert "las_discrete" in _READERS

    def test_rms_well_in_ext_map(self):
        from weco.formats import FORMAT_EXT_MAP
        assert ".rmswell" in FORMAT_EXT_MAP
