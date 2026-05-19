"""
test_flow_interface.py — Integration tests for FloPy/MODFLOW interface (§2.1)
===============================================================================

Tests :class:`weco.flow_interface.CorrelationToModflow` with mock data.
If MODFLOW 6 is available, also runs actual flow simulations.
"""

import os
import tempfile

import numpy as np
import pytest

try:
    import flopy
    _flopy_available = True
except ImportError:
    _flopy_available = False


from weco.flow_interface import CorrelationToModflow


# ── Fixtures ──────────────────────────────────────────────────────────────

class _MockWell:
    def __init__(self, name, x, y, markers):
        self.name = name
        self._x = x
        self._y = y
        self._markers = markers

    def x(self): return self._x
    def y(self): return self._y
    def nbr_marker(self): return len(self._markers)
    def marker_depth(self, i): return self._markers[i]


class _MockWellList:
    def __init__(self, wells):
        self.wells = wells
    def nbr_well(self): return len(self.wells)
    def well(self, i): return self.wells[i]


class _MockCorrelation:
    """Minimal correlation result for testing."""
    def __init__(self, markers_per_well):
        self._markers = markers_per_well
        self.cost = 0.5

    def get_well_markers(self, well_idx):
        return self._markers[well_idx]


class _MockResFile:
    def __init__(self, well_list, correlations):
        self.well_list = well_list
        self._cors = correlations
    def nbr_cor(self): return len(self._cors)
    def cor(self, i): return self._cors[i]


@pytest.fixture
def mock_well_list():
    return _MockWellList([
        _MockWell("W1", 0.0, 0.0, [10.0, 20.0, 30.0]),
        _MockWell("W2", 100.0, 0.0, [12.0, 22.0, 32.0]),
        _MockWell("W3", 200.0, 0.0, [11.0, 21.0, 31.0]),
    ])


@pytest.fixture
def mock_res_file(mock_well_list):
    cors = [
        _MockCorrelation([[0, 1, 2], [0, 1, 2], [0, 1, 2]]),
    ]
    return _MockResFile(mock_well_list, cors)


# ── Tests ─────────────────────────────────────────────────────────────────

def test_import():
    """Module imports without errors."""
    from weco.flow_interface import CorrelationToModflow
    assert CorrelationToModflow is not None


@pytest.mark.skipif(not _flopy_available, reason="flopy not installed")
def test_build_model(mock_res_file, mock_well_list):
    """CorrelationToModflow.build_model() produces a FloPy simulation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        converter = CorrelationToModflow(mock_res_file, mock_well_list)
        sim = converter.build_model(workspace=tmpdir)
        assert sim is not None


@pytest.mark.skipif(not _flopy_available, reason="flopy not installed")
def test_connectivity(mock_res_file, mock_well_list):
    """get_connectivity() returns a dict keyed by well pairs."""
    converter = CorrelationToModflow(mock_res_file, mock_well_list)
    conn = converter.get_connectivity()
    assert isinstance(conn, dict)


@pytest.mark.skipif(
    not _flopy_available or not os.environ.get("MODFLOW6_EXE"),
    reason="MODFLOW 6 not available (set MODFLOW6_EXE to enable)",
)
def test_run_modflow(mock_res_file, mock_well_list):
    """Full MODFLOW 6 simulation run (requires mf6 binary)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        converter = CorrelationToModflow(mock_res_file, mock_well_list)
        converter.build_model(workspace=tmpdir)
        converter.run()
        conn = converter.get_connectivity()
        assert len(conn) > 0
