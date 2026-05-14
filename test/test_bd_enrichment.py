"""
tests/test_bd_enrichment.py – Unit tests for BD enrichment pure functions.

Covers:
  _normalize_volumes       – volumes normalisation from various OSDU layouts
  _normalize_geolabel      – GeoLabelSet → structured dict
  _is_proper_grid2d_map    – map vs table heuristic
  _enrich_bd_volumes       – async fetch stat REV
  _enrich_bd_geolabel      – async fetch GeoLabelSet
  _enrich_bd_activity      – async fetch Activity record
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest


# ── _normalize_volumes ───────────────────────────────────────────────────────

class TestNormalizeVolumes:
    """Test volume data normalisation from different OSDU layouts."""

    def test_rev_layout(self):
        """REV: Volumes nested under data['Volumes']."""
        from app.bd_enrichment import _normalize_volumes
        data = {
            "Volumes": {
                "KeyColumns": [{"ColumnName": "Phase"}],
                "Columns": [{"ColumnName": "P50", "ColumnRole": "value"}],
                "ColumnValues": {"Phase": ["Oil", "Gas"], "P50": [100, 50]},
            },
        }
        result = _normalize_volumes(data)
        assert result["ColumnValues"]["Phase"] == ["Oil", "Gas"]
        assert result["ColumnValues"]["P50"] == [100, 50]
        assert len(result["KeyColumns"]) == 1

    def test_cbt_layout(self):
        """ColumnBasedTable: Table nested under data['Table']."""
        from app.bd_enrichment import _normalize_volumes
        data = {
            "Table": {
                "KeyColumns": [{"ColumnName": "Segment"}],
                "Columns": [],
                "ColumnValues": {"Segment": ["A", "B"], "Value": [1, 2]},
            },
        }
        result = _normalize_volumes(data)
        assert "Segment" in result["ColumnValues"]

    def test_top_level_column_values(self):
        """ColumnValues at the top level of data{}."""
        from app.bd_enrichment import _normalize_volumes
        data = {
            "KeyColumns": [{"ColumnName": "Segment"}],
            "Columns": [],
            "ColumnValues": {"Segment": ["X"], "Mean": [42]},
        }
        result = _normalize_volumes(data)
        assert result["ColumnValues"]["Segment"] == ["X"]

    def test_column_values_as_list(self):
        """ColumnValues as list of dicts [{ColumnName, Values}]."""
        from app.bd_enrichment import _normalize_volumes
        data = {
            "Volumes": {
                "KeyColumns": [],
                "Columns": [],
                "ColumnValues": [
                    {"ColumnName": "Phase", "Values": ["Oil", "Gas"]},
                    {"ColumnName": "P50", "Values": [100, 50]},
                ],
            },
        }
        result = _normalize_volumes(data)
        assert result["ColumnValues"]["Phase"] == ["Oil", "Gas"]
        assert result["ColumnValues"]["P50"] == [100, 50]

    def test_empty_data(self):
        from app.bd_enrichment import _normalize_volumes
        result = _normalize_volumes({})
        assert result["ColumnValues"] == {}

    def test_none_data(self):
        from app.bd_enrichment import _normalize_volumes
        result = _normalize_volumes(None)
        assert result["ColumnValues"] == {}


# ── _normalize_geolabel ─────────────────────────────────────────────────────

class TestNormalizeGeolabel:
    """Test GeoLabelSet normalisation."""

    def test_basic_geolabel(self):
        from app.bd_enrichment import _normalize_geolabel
        data = {
            "GeoLabels": {
                "KeyColumns": [
                    {"ColumnName": "SegmentID"},
                    {"ColumnName": "Facies"},
                ],
                "Columns": [],
                "ColumnValues": {
                    "SegmentID": ["Valysar", "TOTAL"],
                    "Facies": ["ALL", "ALL"],
                    "Oil.P50": [62e6, 100e6],
                    "Oil.P90": [45e6, 73e6],
                    "Porosity": [0.22, 0.20],
                    "Recoverable.P50": [25e6, 40e6],
                },
            },
        }
        result = _normalize_geolabel(data)
        assert "volumes_by_segment" in result
        assert "Valysar" in result["volumes_by_segment"]
        assert result["volumes_by_segment"]["Valysar"]["Oil.P50"] == 62e6
        assert result["properties"]["Porosity"] == 0.20  # TOTAL row
        assert result["uncertainty"]["Recoverable.P50"] == 40e6  # TOTAL row

    def test_totals_normalization(self):
        """'Totals' and 'total' should all normalize to 'TOTAL'."""
        from app.bd_enrichment import _normalize_geolabel
        data = {
            "GeoLabels": {
                "KeyColumns": [{"ColumnName": "SegmentID"}, {"ColumnName": "Facies"}],
                "Columns": [],
                "ColumnValues": {
                    "SegmentID": ["totals"],
                    "Facies": ["ALL"],
                    "Oil.P50": [100e6],
                },
            },
        }
        result = _normalize_geolabel(data)
        assert "TOTAL" in result["volumes_by_segment"]

    def test_empty_geolabels(self):
        from app.bd_enrichment import _normalize_geolabel
        assert _normalize_geolabel({}) == {}
        assert _normalize_geolabel({"GeoLabels": {}}) == {}
        assert _normalize_geolabel({"GeoLabels": {"ColumnValues": {}}}) == {}

    def test_facies_specific_properties(self):
        """When Facies != 'ALL', properties should be per-facies dicts."""
        from app.bd_enrichment import _normalize_geolabel
        data = {
            "GeoLabels": {
                "KeyColumns": [{"ColumnName": "SegmentID"}, {"ColumnName": "Facies"}],
                "Columns": [],
                "ColumnValues": {
                    "SegmentID": ["Valysar", "Valysar"],
                    "Facies": ["Channel", "Crevasse"],
                    "Porosity": [0.25, 0.18],
                },
            },
        }
        result = _normalize_geolabel(data)
        assert isinstance(result["properties"]["Porosity"], dict)
        assert result["properties"]["Porosity"]["Channel"] == 0.25
        assert result["properties"]["Porosity"]["Crevasse"] == 0.18


# ── _is_proper_grid2d_map ───────────────────────────────────────────────────

class TestIsProperGrid2dMap:
    """Test the heuristic for distinguishing maps from tables."""

    def test_map_prefix(self):
        from app.bd_enrichment import _is_proper_grid2d_map
        assert _is_proper_grid2d_map("DS_extract_Valysar_depth") is True
        assert _is_proper_grid2d_map("TS_TopVolantis") is True

    def test_map_keyword(self):
        from app.bd_enrichment import _is_proper_grid2d_map
        assert _is_proper_grid2d_map("TopVolantis_depth_surface") is True
        assert _is_proper_grid2d_map("horizon_interp_filtered") is True

    def test_table_rejected(self):
        from app.bd_enrichment import _is_proper_grid2d_map
        assert _is_proper_grid2d_map("In-place volumes statistics (P10/P50/P90)") is False
        assert _is_proper_grid2d_map("Parameters per realisation table") is False
        assert _is_proper_grid2d_map("Estimated volumes dataframe") is False

    def test_short_underscore_name(self):
        from app.bd_enrichment import _is_proper_grid2d_map
        assert _is_proper_grid2d_map("my_grid_2d") is True

    def test_empty(self):
        from app.bd_enrichment import _is_proper_grid2d_map
        assert _is_proper_grid2d_map("") is True  # default: include


# ── _enrich_bd_volumes ───────────────────────────────────────────────────────

class TestEnrichBdVolumes:
    """Test async volumes enrichment with mocked client."""

    @pytest.mark.asyncio
    async def test_finds_stat_rev(self):
        from app.bd_enrichment import _enrich_bd_volumes
        data_block = {
            "Parameters": [
                {
                    "DataObjectParameter": "dev:wpc--ReservoirEstimatedVolumes:stats:1",
                    "Keys": [{"StringParameterKey": "InPlaceVol-stats"}],
                },
                {
                    "DataObjectParameter": "dev:wpc--ReservoirEstimatedVolumes:raw:1",
                    "Keys": [{"StringParameterKey": "InPlaceVol-raw"}],
                },
            ],
        }
        rev_data = {
            "data": {
                "Volumes": {
                    "KeyColumns": [{"ColumnName": "Phase"}],
                    "Columns": [],
                    "ColumnValues": {"Phase": ["Oil"], "P50": [95.2]},
                },
            },
        }
        client = AsyncMock()
        client.get = AsyncMock(return_value=MagicMock(
            status_code=200, json=MagicMock(return_value=rev_data),
        ))

        result = await _enrich_bd_volumes(data_block, client, "http://x/records", {})
        assert result["ColumnValues"]["P50"] == [95.2]

    @pytest.mark.asyncio
    async def test_no_rev_returns_empty(self):
        from app.bd_enrichment import _enrich_bd_volumes
        data_block = {"Parameters": []}
        client = AsyncMock()
        result = await _enrich_bd_volumes(data_block, client, "http://x/records", {})
        assert result == {}


# ── _enrich_bd_geolabel ─────────────────────────────────────────────────────

class TestEnrichBdGeolabel:
    """Test async GeoLabelSet enrichment."""

    @pytest.mark.asyncio
    async def test_finds_geolabelset(self):
        from app.bd_enrichment import _enrich_bd_geolabel
        data_block = {
            "Parameters": [
                {
                    "DataObjectParameter": "dev:wpc--GeoLabelSet:gls:1",
                    "Keys": [{"StringParameterKey": "GeoLabelSet"}],
                },
            ],
        }
        gls_data = {
            "data": {
                "GeoLabels": {
                    "KeyColumns": [{"ColumnName": "SegmentID"}, {"ColumnName": "Facies"}],
                    "Columns": [],
                    "ColumnValues": {
                        "SegmentID": ["Seg1"],
                        "Facies": ["ALL"],
                        "Oil.P50": [100e6],
                    },
                },
            },
        }
        client = AsyncMock()
        client.get = AsyncMock(return_value=MagicMock(
            status_code=200, json=MagicMock(return_value=gls_data),
        ))

        result = await _enrich_bd_geolabel(data_block, client, "http://x/records", {})
        assert "volumes_by_segment" in result
        assert "Seg1" in result["volumes_by_segment"]

    @pytest.mark.asyncio
    async def test_no_geolabelset_returns_empty(self):
        from app.bd_enrichment import _enrich_bd_geolabel
        data_block = {"Parameters": []}
        client = AsyncMock()
        result = await _enrich_bd_geolabel(data_block, client, "http://x/records", {})
        assert result == {}


# ── _enrich_bd_activity ──────────────────────────────────────────────────────

class TestEnrichBdActivity:
    """Test async Activity enrichment."""

    @pytest.mark.asyncio
    async def test_finds_activity(self):
        from app.bd_enrichment import _enrich_bd_activity
        data_block = {
            "PriorActivityIDs": ["dev:wpc--Activity:act1:1"],
        }
        activity_data = {
            "id": "dev:wpc--Activity:act1:1",
            "kind": "osdu:wks:wpc--Activity:1.0.0",
            "data": {
                "Name": "FMU Run",
                "WorkflowStatus": "Completed",
                "Parameters": [],
            },
        }
        client = AsyncMock()
        client.get = AsyncMock(return_value=MagicMock(
            status_code=200, json=MagicMock(return_value=activity_data),
        ))

        result = await _enrich_bd_activity(data_block, client, "http://x/records", {})
        assert result["Name"] == "FMU Run"
        assert result["WorkflowStatus"] == "Completed"

    @pytest.mark.asyncio
    async def test_no_activity_returns_empty(self):
        from app.bd_enrichment import _enrich_bd_activity
        data_block = {"PriorActivityIDs": []}
        client = AsyncMock()
        result = await _enrich_bd_activity(data_block, client, "http://x/records", {})
        assert result == {}

    @pytest.mark.asyncio
    async def test_skips_activity_template(self):
        """Should skip ActivityTemplate refs, only pick Activity."""
        from app.bd_enrichment import _enrich_bd_activity
        data_block = {
            "PriorActivityIDs": ["dev:wpc--ActivityTemplate:tmpl:1"],
        }
        client = AsyncMock()
        result = await _enrich_bd_activity(data_block, client, "http://x/records", {})
        assert result == {}
