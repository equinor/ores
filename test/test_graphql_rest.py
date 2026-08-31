"""
test/test_graphql_rest.py – Unit tests for REST-based GraphQL resolvers.

Tests the helper functions that parse RDDMS REST responses without
making any actual HTTP calls. All RDDMS responses are mocked.

Covers:
  - _parse_eml_entry()       – URI → uuid/contentType/name extraction
  - _extract_property_kind() – Standard + Local property kind extraction
  - _deep_search_rest()      – full REST deep search with mocked RDDMS
  - _merge_deep_results()    – multi-dataspace merging
  - Kind cache               – duplicate property fetches are avoided
  - Warnings                 – surfaced when arrays unavailable or errors occur

Run:
    python -m pytest test/test_graphql_rest.py -v
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch

import pytest

# ── Bootstrap ──────────────────────────────────────────────────────────────
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from app.graphql_search import (
    _parse_eml_entry,
    _extract_property_kind,
    _merge_deep_results,
    _deep_search_rest,
    DeepSearchResult,
    PropertyFilter,
    ArrayFilter,
    ComparisonOperator,
)


# ═══════════════════════════════════════════════════════════════════════════
# 1.  _parse_eml_entry
# ═══════════════════════════════════════════════════════════════════════════

class TestParseEmlEntry:
    """Extracts uuid, contentType, name from RDDMS REST listing entries."""

    def test_standard_uri(self):
        entry = {
            "uri": "eml:///dataspace('maap/drogon_dg')/resqml20.obj_ContinuousProperty(0046abcd-0eaa-41da-af0a-edee013f30a4)",
            "name": "PORO",
        }
        parsed = _parse_eml_entry(entry)
        assert parsed["uuid"] == "0046abcd-0eaa-41da-af0a-edee013f30a4"
        assert parsed["contentType"] == "resqml20.obj_ContinuousProperty"
        assert parsed["name"] == "PORO"

    def test_uri_without_dataspace(self):
        entry = {
            "uri": "resqml20.obj_IjkGridRepresentation(0bc36994-2032-4e08-bad8-60ce0871002a)",
            "name": "Simgrid",
        }
        parsed = _parse_eml_entry(entry)
        assert parsed["uuid"] == "0bc36994-2032-4e08-bad8-60ce0871002a"
        assert parsed["contentType"] == "resqml20.obj_IjkGridRepresentation"

    def test_entry_with_explicit_keys(self):
        """If top-level UUID/ContentType keys exist, prefer them."""
        entry = {
            "UUID": "aaaa-bbbb",
            "ContentType": "resqml20.obj_Grid2dRepresentation",
            "Title": "TopVolantis",
            "uri": "eml:///dataspace('x')/resqml20.obj_Grid2dRepresentation(aaaa-bbbb)",
        }
        parsed = _parse_eml_entry(entry)
        assert parsed["uuid"] == "aaaa-bbbb"
        assert parsed["name"] == "TopVolantis"

    def test_empty_entry(self):
        parsed = _parse_eml_entry({})
        assert parsed["uuid"] == ""
        assert parsed["contentType"] == ""
        assert parsed["name"] == ""

    def test_underscore_in_dataspace(self):
        entry = {
            "uri": "eml:///dataspace('maap/drogon_dg')/resqml20.obj_WellboreFeature(12345678-1234-1234-1234-123456789abc)",
            "name": "R-1",
        }
        parsed = _parse_eml_entry(entry)
        assert parsed["uuid"] == "12345678-1234-1234-1234-123456789abc"
        assert "WellboreFeature" in parsed["contentType"]


# ═══════════════════════════════════════════════════════════════════════════
# 2.  _extract_property_kind
# ═══════════════════════════════════════════════════════════════════════════

class TestExtractPropertyKind:
    """Handles both StandardPropertyKind and LocalPropertyKind."""

    def test_standard_kind(self):
        obj = {"PropertyKind": {"$type": "resqml20.StandardPropertyKind", "Kind": "porosity"}}
        assert _extract_property_kind(obj) == "porosity"

    def test_local_kind(self):
        obj = {
            "PropertyKind": {
                "$type": "resqml20.LocalPropertyKind",
                "LocalPropertyKind": {
                    "$type": "eml20.DataObjectReference",
                    "Title": "General discrete",
                    "UUID": "abc",
                },
            }
        }
        assert _extract_property_kind(obj) == "General discrete"

    def test_local_kind_string(self):
        obj = {
            "PropertyKind": {
                "$type": "resqml20.LocalPropertyKind",
                "LocalPropertyKind": "Custom Kind Name",
            }
        }
        assert _extract_property_kind(obj) == "Custom Kind Name"

    def test_fallback_standard_property_kind(self):
        obj = {"StandardPropertyKind": "rock permeability"}
        assert _extract_property_kind(obj) == "rock permeability"

    def test_empty_object(self):
        assert _extract_property_kind({}) == "Unknown"

    def test_kind_in_citation(self):
        """Last-resort fallback via PropertyKind.Title."""
        obj = {"PropertyKind": {"Title": "custom-thing"}}
        assert _extract_property_kind(obj) == "custom-thing"


# ═══════════════════════════════════════════════════════════════════════════
# 3.  _merge_deep_results
# ═══════════════════════════════════════════════════════════════════════════

class TestMergeDeepResults:
    def test_merge_two_results(self):
        from app.graphql_router import ResqmlObject
        r1 = DeepSearchResult(
            objects=[ResqmlObject(uuid="a", title="Grid1", type_name="IjkGrid")],
            total_scanned=5, total_matched=1,
            query_description="ds1", backend="REST",
            warnings=["warn1"],
        )
        r2 = DeepSearchResult(
            objects=[ResqmlObject(uuid="b", title="Grid2", type_name="IjkGrid")],
            total_scanned=3, total_matched=1,
            query_description="ds2", backend="PostgreSQL",
        )
        merged = _merge_deep_results([r1, r2], ["ds1", "ds2"], limit=10)
        assert merged.total_scanned == 8
        assert merged.total_matched == 2
        assert len(merged.objects) == 2
        assert "REST" in merged.backend
        assert "PostgreSQL" in merged.backend
        assert merged.warnings == ["warn1"]

    def test_merge_respects_limit(self):
        from app.graphql_router import ResqmlObject
        objs = [ResqmlObject(uuid=str(i), title=f"G{i}", type_name="t") for i in range(10)]
        r = DeepSearchResult(
            objects=objs, total_scanned=10, total_matched=10,
            query_description="", backend="REST",
        )
        merged = _merge_deep_results([r], ["ds"], limit=3)
        assert len(merged.objects) == 3

    def test_merge_no_warnings(self):
        r = DeepSearchResult(
            objects=[], total_scanned=0, total_matched=0,
            query_description="", backend="REST",
        )
        merged = _merge_deep_results([r], ["ds"], limit=10)
        assert merged.warnings is None


# ═══════════════════════════════════════════════════════════════════════════
# 4.  _deep_search_rest – mocked end-to-end
# ═══════════════════════════════════════════════════════════════════════════

def _make_eml_entry(ct: str, uuid: str, name: str) -> dict:
    """Create a minimal RDDMS REST listing entry."""
    return {"uri": f"eml:///dataspace('test')/{ct}({uuid})", "name": name}


def _make_prop_object(kind: str, title: str, standard: bool = True) -> dict:
    """Create a minimal property object JSON."""
    if standard:
        return {
            "Citation": {"Title": title},
            "PropertyKind": {"$type": "resqml20.StandardPropertyKind", "Kind": kind},
        }
    return {
        "Citation": {"Title": title},
        "PropertyKind": {
            "$type": "resqml20.LocalPropertyKind",
            "LocalPropertyKind": {"Title": kind},
        },
    }


class TestDeepSearchRest:
    """Full _deep_search_rest with mocked RDDMS REST calls."""

    @pytest.fixture(autouse=True)
    def _patch_rest(self):
        """Patch all REST helper functions used by _deep_search_rest."""
        self.list_resources = AsyncMock(return_value=[])
        self.list_sources = AsyncMock(return_value=[])
        self.list_targets = AsyncMock(return_value=[])
        self.get_resource = AsyncMock(return_value={})
        self.list_arrays = AsyncMock(return_value=[])
        self.read_array = AsyncMock(return_value=[])

        patches = [
            patch("app.graphql_search._rest_list_resources", self.list_resources),
            patch("app.graphql_search._rest_list_sources", self.list_sources),
            patch("app.graphql_search._rest_list_targets", self.list_targets),
            patch("app.graphql_search._rest_get_resource", self.get_resource),
            patch("app.graphql_search._rest_list_arrays", self.list_arrays),
            patch("app.graphql_search._rest_read_array", self.read_array),
        ]
        for p in patches:
            p.start()
        yield
        for p in patches:
            p.stop()

    def _run(self, **kwargs) -> DeepSearchResult:
        defaults = dict(
            token="fake", dataspace="test/ds",
            type_name="resqml20.obj_IjkGridRepresentation",
            title_contains=None, property_filter=None,
            include_relations=False,
            include_statistics=False, include_sample_values=False,
            sample_size=50, limit=20,
        )
        defaults.update(kwargs)
        return asyncio.get_event_loop().run_until_complete(
            _deep_search_rest(**defaults)
        )

    # ── Basic listing ──

    def test_empty_dataspace(self):
        self.list_resources.return_value = []
        result = self._run()
        assert result.total_scanned == 0
        assert result.total_matched == 0
        assert result.backend == "REST"

    def test_listing_error_yields_warning(self):
        self.list_resources.side_effect = Exception("connection refused")
        result = self._run()
        assert result.total_scanned == 0
        assert result.warnings is not None
        assert any("connection refused" in w for w in result.warnings)

    # ── Kind filter ──

    def test_kind_filter_matches(self):
        """Objects with matching property kind are returned."""
        grid_uuid = "11111111-1111-1111-1111-111111111111"
        prop_uuid = "22222222-2222-2222-2222-222222222222"

        self.list_resources.return_value = [
            {"uuid": grid_uuid, "title": "Simgrid", "type_name": "resqml20.obj_IjkGridRepresentation", "raw": {}},
        ]
        self.list_sources.return_value = [
            _make_eml_entry("resqml20.obj_ContinuousProperty", prop_uuid, "PORO"),
        ]
        self.get_resource.return_value = _make_prop_object("porosity", "PORO")

        result = self._run(property_filter=PropertyFilter(kind="porosity"))
        assert result.total_matched == 1
        assert len(result.objects) == 1
        assert result.objects[0].properties[0].kind == "porosity"
        assert result.objects[0].properties[0].title == "PORO"

    def test_kind_filter_no_match(self):
        """Objects without matching property kind are excluded."""
        grid_uuid = "11111111-1111-1111-1111-111111111111"
        prop_uuid = "22222222-2222-2222-2222-222222222222"

        self.list_resources.return_value = [
            {"uuid": grid_uuid, "title": "Simgrid", "type_name": "t", "raw": {}},
        ]
        self.list_sources.return_value = [
            _make_eml_entry("resqml20.obj_ContinuousProperty", prop_uuid, "PORO"),
        ]
        self.get_resource.return_value = _make_prop_object("porosity", "PORO")

        result = self._run(property_filter=PropertyFilter(kind="saturation"))
        assert result.total_matched == 0

    # ── Array filter warning ──

    def test_array_filter_warns_when_no_data(self):
        """arrayFilter with no array data should include object with warning (REST fallback)."""
        grid_uuid = "11111111-1111-1111-1111-111111111111"
        prop_uuid = "22222222-2222-2222-2222-222222222222"

        self.list_resources.return_value = [
            {"uuid": grid_uuid, "title": "Simgrid", "type_name": "t", "raw": {}},
        ]
        self.list_sources.return_value = [
            _make_eml_entry("resqml20.obj_ContinuousProperty", prop_uuid, "PORO"),
        ]
        self.get_resource.return_value = _make_prop_object("porosity", "PORO")
        self.list_arrays.return_value = []  # no arrays available

        pf = PropertyFilter(
            kind="porosity",
            array_filter=ArrayFilter(threshold=0.25, operator=ComparisonOperator.GT),
        )
        result = self._run(property_filter=pf, include_statistics=True)
        # REST fallback: object is included (not filtered out) with a warning
        assert result.total_matched == 1
        assert result.warnings is not None
        assert any("array" in w.lower() for w in result.warnings)

    # ── Property kind cache ──

    def test_kind_cache_avoids_duplicate_fetches(self):
        """Same property UUID referenced by two grids → fetched only once."""
        prop_uuid = "33333333-3333-3333-3333-333333333333"
        g1 = "11111111-1111-1111-1111-111111111111"
        g2 = "22222222-2222-2222-2222-222222222222"

        self.list_resources.return_value = [
            {"uuid": g1, "title": "Grid1", "type_name": "t", "raw": {}},
            {"uuid": g2, "title": "Grid2", "type_name": "t", "raw": {}},
        ]
        self.list_sources.return_value = [
            _make_eml_entry("resqml20.obj_ContinuousProperty", prop_uuid, "PORO"),
        ]
        self.get_resource.return_value = _make_prop_object("porosity", "PORO")

        result = self._run(property_filter=PropertyFilter(kind="porosity"))
        assert result.total_matched == 2
        # get_resource called once (first grid), cached for second
        assert self.get_resource.call_count == 1

    # ── Title filter ──

    def test_title_contains_filter(self):
        self.list_resources.return_value = [
            {"uuid": "a", "title": "Simgrid", "type_name": "t", "raw": {}},
            {"uuid": "b", "title": "Geogrid", "type_name": "t", "raw": {}},
        ]
        result = self._run(title_contains="Sim")
        assert result.total_matched == 1
        assert result.objects[0].title == "Simgrid"

    # ── No filter (browse all) ──

    def test_no_filter_returns_all_with_properties(self):
        """Without property filter, all objects returned with all properties."""
        g1 = "11111111-1111-1111-1111-111111111111"
        p1 = "22222222-2222-2222-2222-222222222222"
        p2 = "33333333-3333-3333-3333-333333333333"

        self.list_resources.return_value = [
            {"uuid": g1, "title": "Simgrid", "type_name": "t", "raw": {}},
        ]
        self.list_sources.return_value = [
            _make_eml_entry("resqml20.obj_ContinuousProperty", p1, "PORO"),
            _make_eml_entry("resqml20.obj_DiscreteProperty", p2, "FACIES"),
        ]

        def _get_res(token, ds, typ, uuid):
            if uuid == p1:
                return _make_prop_object("porosity", "PORO")
            return _make_prop_object("General discrete", "FACIES", standard=False)

        self.get_resource.side_effect = _get_res

        result = self._run()
        assert result.total_matched == 1
        assert len(result.objects[0].properties) == 2
        kinds = {p.kind for p in result.objects[0].properties}
        assert "porosity" in kinds
        assert "General discrete" in kinds
