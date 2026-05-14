"""
tests/test_resqml_viz.py – Unit tests for RESQML visualisation helpers.

Covers pure functions that do NOT require a database or HTTP backend:
  - _strip_ns / _xfind / _xfindall / _xtext / _xfloat  – XML helpers
  - _try_numeric            – type coercion
  - xml_to_dict             – full XML → dict conversion
  - _parse_lattice          – lattice geometry parsing
  - _apply_crs_rotation     – CRS rotation + offset
  - build_xy_mesh           – coordinate mesh generation
  - render_grid2d_png       – PNG rendering (returns bytes starting with PNG magic)
  - render_triset_png       – TriangulatedSet PNG rendering
"""
from __future__ import annotations

import math
from typing import Any, Dict

import pytest


# ─── XML namespace helpers ───────────────────────────────────────────────────

class TestStripNs:
    def test_with_namespace(self):
        from app.resqml_viz import _strip_ns
        assert _strip_ns("{http://www.energistics.org/energyml/data/resqmlv2}Grid2dRepresentation") == "Grid2dRepresentation"

    def test_without_namespace(self):
        from app.resqml_viz import _strip_ns
        assert _strip_ns("PlainTag") == "PlainTag"


class TestTryNumeric:
    def test_integer(self):
        from app.resqml_viz import _try_numeric
        assert _try_numeric("42") == 42

    def test_float(self):
        from app.resqml_viz import _try_numeric
        assert _try_numeric("3.14") == pytest.approx(3.14)

    def test_scientific(self):
        from app.resqml_viz import _try_numeric
        assert _try_numeric("1.5e3") == pytest.approx(1500.0)

    def test_bool_true(self):
        from app.resqml_viz import _try_numeric
        assert _try_numeric("true") is True

    def test_bool_false(self):
        from app.resqml_viz import _try_numeric
        assert _try_numeric("false") is False

    def test_string(self):
        from app.resqml_viz import _try_numeric
        assert _try_numeric("hello") == "hello"

    def test_empty(self):
        from app.resqml_viz import _try_numeric
        assert _try_numeric("") == ""

    def test_whitespace(self):
        from app.resqml_viz import _try_numeric
        assert _try_numeric("  ") == ""


# ─── xml_to_dict ─────────────────────────────────────────────────────────────

class TestXmlToDict:
    """Test the full XML → JSON-like dict converter."""

    def test_simple_element(self):
        from app.resqml_viz import xml_to_dict
        xml = "<Root><Name>Test</Name><Count>5</Count></Root>"
        d = xml_to_dict(xml)
        assert d["Name"] == "Test"
        assert d["Count"] == 5

    def test_nested_elements(self):
        from app.resqml_viz import xml_to_dict
        xml = """
        <Root>
          <Origin>
            <Coordinate1>100.0</Coordinate1>
            <Coordinate2>200.0</Coordinate2>
            <Coordinate3>0.0</Coordinate3>
          </Origin>
        </Root>
        """
        d = xml_to_dict(xml)
        assert d["Origin"]["Coordinate1"] == pytest.approx(100.0)
        assert d["Origin"]["Coordinate2"] == pytest.approx(200.0)

    def test_repeated_elements_become_list(self):
        from app.resqml_viz import xml_to_dict
        xml = """
        <Root>
          <Item>one</Item>
          <Item>two</Item>
          <Item>three</Item>
        </Root>
        """
        d = xml_to_dict(xml)
        assert d["Item"] == ["one", "two", "three"]

    def test_attributes_preserved(self):
        from app.resqml_viz import xml_to_dict
        xml = '<Root><Depth uom="m">1500.5</Depth></Root>'
        d = xml_to_dict(xml)
        assert d["Depth"]["_"] == pytest.approx(1500.5)
        assert d["Depth"]["Uom"] == "m"

    def test_namespace_stripped(self):
        from app.resqml_viz import xml_to_dict
        xml = '<ns:Root xmlns:ns="http://example.com"><ns:Name>Test</ns:Name></ns:Root>'
        d = xml_to_dict(xml)
        assert "Name" in d
        assert d["Name"] == "Test"

    def test_boolean_values(self):
        from app.resqml_viz import xml_to_dict
        xml = "<Root><Flag>true</Flag><Other>false</Other></Root>"
        d = xml_to_dict(xml)
        assert d["Flag"] is True
        assert d["Other"] is False

    def test_empty_root(self):
        from app.resqml_viz import xml_to_dict
        d = xml_to_dict("<Root/>")
        assert d == {}

    def test_xsi_type_dropped(self):
        from app.resqml_viz import xml_to_dict
        xml = '<Root xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><Val xsi:type="xs:string">hello</Val></Root>'
        d = xml_to_dict(xml)
        # xsi:type should be dropped
        assert d["Val"] == "hello"


# ─── _parse_lattice ─────────────────────────────────────────────────────────

class TestParseLattice:
    """Test lattice geometry parsing from RDDMS JSON structures."""

    def test_basic_lattice(self):
        from app.resqml_viz import _parse_lattice
        origin = {"Coordinate1": 500000, "Coordinate2": 6500000, "Coordinate3": 0}
        offsets = [
            {"Offset": {"Coordinate1": 1, "Coordinate2": 0, "Coordinate3": 0}, "Spacing": {"Value": 25.0}},
            {"Offset": {"Coordinate1": 0, "Coordinate2": 1, "Coordinate3": 0}, "Spacing": {"Value": 25.0}},
        ]
        geo = _parse_lattice(origin, offsets, n_slow=100, n_fast=200)
        assert geo["origin"] == (500000, 6500000, 0)
        assert geo["u_vec"] == (1, 0)
        assert geo["v_vec"] == (0, 1)
        assert geo["u_space"] == 25.0
        assert geo["v_space"] == 25.0
        assert geo["n_slow"] == 100
        assert geo["n_fast"] == 200

    def test_single_offset(self):
        from app.resqml_viz import _parse_lattice
        origin = {"Coordinate1": 0, "Coordinate2": 0, "Coordinate3": 0}
        offsets = [
            {"Offset": {"Coordinate1": 0.5, "Coordinate2": 0.866, "Coordinate3": 0}, "Spacing": {"Value": 50.0}},
        ]
        geo = _parse_lattice(origin, offsets, n_slow=10, n_fast=20)
        assert geo["u_vec"] == pytest.approx((0.5, 0.866))
        assert geo["v_vec"] == (0, 0)  # default when no second offset

    def test_empty_offsets(self):
        from app.resqml_viz import _parse_lattice
        origin = {"Coordinate1": 0, "Coordinate2": 0, "Coordinate3": 0}
        geo = _parse_lattice(origin, [], n_slow=5, n_fast=5)
        assert geo["u_vec"] == (0, 0)
        assert geo["v_vec"] == (0, 0)


# ─── _apply_crs_rotation ────────────────────────────────────────────────────

class TestApplyCrsRotation:
    """Test CRS rotation + offset application."""

    def test_no_crs(self):
        from app.resqml_viz import _apply_crs_rotation
        geo = {"origin": (100, 200, 0), "u_vec": (1, 0), "v_vec": (0, 1)}
        result = _apply_crs_rotation(geo, None)
        assert result is geo  # unchanged

    def test_identity_crs(self):
        from app.resqml_viz import _apply_crs_rotation
        geo = {"origin": (100, 200, 0), "u_vec": (1, 0), "v_vec": (0, 1)}
        crs = {"XOffset": 0, "YOffset": 0, "ArealRotation": {"_": 0, "Uom": "dega"}}
        result = _apply_crs_rotation(geo, crs)
        assert result is geo  # no transform needed

    def test_translation_only(self):
        from app.resqml_viz import _apply_crs_rotation
        geo = {"origin": (0, 0, -500), "u_vec": (1, 0), "v_vec": (0, 1)}
        crs = {"XOffset": 500000, "YOffset": 6500000, "ArealRotation": {"_": 0}}
        result = _apply_crs_rotation(geo, crs)
        assert result["origin"][0] == pytest.approx(500000)
        assert result["origin"][1] == pytest.approx(6500000)
        assert result["origin"][2] == -500  # Z unchanged

    def test_90_degree_rotation(self):
        from app.resqml_viz import _apply_crs_rotation
        geo = {"origin": (100, 0, 0), "u_vec": (1, 0), "v_vec": (0, 1)}
        crs = {"XOffset": 0, "YOffset": 0, "ArealRotation": {"_": 90, "Uom": "dega"}}
        result = _apply_crs_rotation(geo, crs)
        # 90° rotation: (100,0) → (0,100)
        assert result["origin"][0] == pytest.approx(0, abs=1e-10)
        assert result["origin"][1] == pytest.approx(100)
        # u_vec (1,0) → (0,1)
        assert result["u_vec"][0] == pytest.approx(0, abs=1e-10)
        assert result["u_vec"][1] == pytest.approx(1)

    def test_rotation_radians(self):
        from app.resqml_viz import _apply_crs_rotation
        geo = {"origin": (100, 0, 0), "u_vec": (1, 0), "v_vec": (0, 1)}
        angle_rad = math.pi / 2
        crs = {"XOffset": 0, "YOffset": 0, "ArealRotation": {"_": angle_rad, "Uom": "rad"}}
        result = _apply_crs_rotation(geo, crs)
        assert result["origin"][0] == pytest.approx(0, abs=1e-10)
        assert result["origin"][1] == pytest.approx(100)


# ─── build_xy_mesh ──────────────────────────────────────────────────────────

class TestBuildXyMesh:
    """Test coordinate mesh generation."""

    def test_basic_mesh(self):
        import numpy as np
        from app.resqml_viz import build_xy_mesh
        geo = {
            "origin": (0, 0, 0),
            "u_vec": (1, 0),
            "v_vec": (0, 1),
            "u_space": 10.0,
            "v_space": 10.0,
            "n_slow": 3,
            "n_fast": 4,
        }
        X, Y = build_xy_mesh(geo)
        assert X.shape == (3, 4)
        assert Y.shape == (3, 4)
        # Origin corner
        assert X[0, 0] == pytest.approx(0)
        assert Y[0, 0] == pytest.approx(0)
        # Far corner
        assert X[2, 3] == pytest.approx(20)
        assert Y[2, 3] == pytest.approx(30)

    def test_mesh_with_crs_offset(self):
        import numpy as np
        from app.resqml_viz import build_xy_mesh
        geo = {
            "origin": (0, 0, 0),
            "u_vec": (1, 0), "v_vec": (0, 1),
            "u_space": 1, "v_space": 1,
            "n_slow": 2, "n_fast": 2,
        }
        crs = {"XOffset": 1000, "YOffset": 2000, "ArealRotation": {"_": 0}}
        X, Y = build_xy_mesh(geo, crs)
        assert X[0, 0] == pytest.approx(1000)
        assert Y[0, 0] == pytest.approx(2000)


# ─── render_grid2d_png ──────────────────────────────────────────────────────

class TestRenderGrid2dPng:
    """Test Grid2d PNG rendering returns valid PNG bytes."""

    def test_basic_render(self):
        from app.resqml_viz import render_grid2d_png
        zvalues = [float(i) for i in range(20)]
        dims = [4, 5]
        geometry = {
            "origin": (0, 0, 0),
            "u_vec": (1, 0), "v_vec": (0, 1),
            "u_space": 100, "v_space": 100,
            "n_slow": 4, "n_fast": 5,
        }
        result = render_grid2d_png(zvalues, dims, geometry)
        assert isinstance(result, bytes)
        assert result[:4] == b"\x89PNG"

    def test_render_with_nans(self):
        """Should handle NaN values gracefully."""
        from app.resqml_viz import render_grid2d_png
        zvalues = [1.0, 2.0, float("nan"), 4.0, 5.0, 6.0]
        dims = [2, 3]
        geometry = {
            "origin": (0, 0, 0),
            "u_vec": (1, 0), "v_vec": (0, 1),
            "u_space": 100, "v_space": 100,
            "n_slow": 2, "n_fast": 3,
        }
        result = render_grid2d_png(zvalues, dims, geometry)
        assert result[:4] == b"\x89PNG"

    def test_render_with_sentinel(self):
        """Values above nan_sentinel should be treated as NaN."""
        from app.resqml_viz import render_grid2d_png
        zvalues = [1.0, 2.0, 3.0, 1e31, 5.0, 6.0]
        dims = [2, 3]
        geometry = {
            "origin": (0, 0, 0),
            "u_vec": (1, 0), "v_vec": (0, 1),
            "u_space": 100, "v_space": 100,
            "n_slow": 2, "n_fast": 3,
        }
        result = render_grid2d_png(zvalues, dims, geometry)
        assert result[:4] == b"\x89PNG"

    def test_render_with_crs(self):
        from app.resqml_viz import render_grid2d_png
        zvalues = [float(i) for i in range(12)]
        dims = [3, 4]
        geometry = {
            "origin": (0, 0, 0),
            "u_vec": (1, 0), "v_vec": (0, 1),
            "u_space": 50, "v_space": 50,
            "n_slow": 3, "n_fast": 4,
        }
        crs = {
            "XOffset": 500000,
            "YOffset": 6500000,
            "ArealRotation": {"_": 5, "Uom": "dega"},
            "ZIncreasingDownward": True,
            "Citation": {"Title": "Test CRS"},
        }
        result = render_grid2d_png(zvalues, dims, geometry, crs=crs, title="Test Surface")
        assert result[:4] == b"\x89PNG"

    def test_short_zvalues_padded(self):
        """zvalues shorter than dims should be padded with NaN."""
        from app.resqml_viz import render_grid2d_png
        zvalues = [1.0, 2.0]  # only 2, but grid is 2x3=6
        dims = [2, 3]
        geometry = {
            "origin": (0, 0, 0),
            "u_vec": (1, 0), "v_vec": (0, 1),
            "u_space": 100, "v_space": 100,
            "n_slow": 2, "n_fast": 3,
        }
        result = render_grid2d_png(zvalues, dims, geometry)
        assert result[:4] == b"\x89PNG"


# ─── render_triset_png ───────────────────────────────────────────────────────

class TestRenderTrisetPng:
    """Test TriangulatedSetRepresentation PNG rendering."""

    def test_basic_triangle(self):
        """Single triangle should render successfully."""
        from app.resqml_viz import render_triset_png
        positions = [
            0.0, 0.0, -100.0,    # vertex 0
            1000.0, 0.0, -150.0, # vertex 1
            500.0, 1000.0, -120.0,  # vertex 2
        ]
        indices = [0, 1, 2]
        result = render_triset_png(positions, indices)
        assert isinstance(result, bytes)
        assert result[:4] == b"\x89PNG"

    def test_multiple_triangles(self):
        from app.resqml_viz import render_triset_png
        positions = [
            0.0, 0.0, -100.0,
            1000.0, 0.0, -150.0,
            500.0, 1000.0, -120.0,
            1000.0, 1000.0, -130.0,
        ]
        indices = [0, 1, 2, 1, 3, 2]
        result = render_triset_png(positions, indices, title="Test TriSet")
        assert result[:4] == b"\x89PNG"

    def test_too_few_vertices_raises(self):
        from app.resqml_viz import render_triset_png
        positions = [0.0, 0.0, -100.0, 1.0, 1.0, -50.0]  # only 2 vertices
        indices = []
        with pytest.raises(ValueError, match="Too few vertices"):
            render_triset_png(positions, indices)

    def test_all_nan_z_raises(self):
        from app.resqml_viz import render_triset_png
        positions = [
            0.0, 0.0, float("nan"),
            1.0, 0.0, float("nan"),
            0.5, 1.0, float("nan"),
        ]
        indices = [0, 1, 2]
        with pytest.raises(ValueError, match="NaN"):
            render_triset_png(positions, indices)

    def test_sentinel_values_become_nan(self):
        from app.resqml_viz import render_triset_png
        positions = [
            0.0, 0.0, -100.0,
            1000.0, 0.0, -150.0,
            500.0, 1000.0, 2e30,    # sentinel
            1500.0, 500.0, -130.0,
        ]
        indices = [0, 1, 3]  # triangle uses only valid verts
        result = render_triset_png(positions, indices)
        assert result[:4] == b"\x89PNG"
