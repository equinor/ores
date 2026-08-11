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
from unittest.mock import AsyncMock, MagicMock, patch

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


# ── _is_proper_grid2d_map ───────────────────────────────────────────────────

class TestIsProperGrid2dMap:
    """Test the heuristic that distinguishes real maps from table-as-Grid2d."""

    def test_fmu_map_prefix(self):
        from app.bd_enrichment import _is_proper_grid2d_map
        assert _is_proper_grid2d_map("DS_extract_simgrid_20250101") is True
        assert _is_proper_grid2d_map("TS_surface_depth") is True
        assert _is_proper_grid2d_map("GS_velocity_model") is True

    def test_table_marker_rejected(self):
        from app.bd_enrichment import _is_proper_grid2d_map
        assert _is_proper_grid2d_map("Estimated reserves parameters") is False
        assert _is_proper_grid2d_map("Volumes per realisation table") is False
        assert _is_proper_grid2d_map("statistics_raw, all") is False

    def test_map_keywords_accepted(self):
        from app.bd_enrichment import _is_proper_grid2d_map
        assert _is_proper_grid2d_map("Top_Reservoir_Depth") is True
        assert _is_proper_grid2d_map("Horizon_A_surface") is True
        assert _is_proper_grid2d_map("velocity_model_v2") is True
        assert _is_proper_grid2d_map("isochore_zone1") is True

    def test_short_underscore_name_accepted(self):
        from app.bd_enrichment import _is_proper_grid2d_map
        assert _is_proper_grid2d_map("zone1_prop") is True

    def test_default_is_inclusive(self):
        from app.bd_enrichment import _is_proper_grid2d_map
        assert _is_proper_grid2d_map("unknown_thing") is True


# ── _enrich_bd_maps ─────────────────────────────────────────────────────────

class TestEnrichBdMaps:
    """Test async ETPDataspace → Grid2d discovery."""

    @pytest.mark.asyncio
    async def test_no_etpdataspace_returns_empty(self):
        from app.bd_enrichment import _enrich_bd_maps
        data_block = {"Parameters": [{"DataObjectParameter": "dev:wpc--GeoLabelSet:x:1"}]}
        client = AsyncMock()
        result = await _enrich_bd_maps(data_block, client, "http://x/records", {})
        assert result == {"maps": [], "all": []}

    @pytest.mark.asyncio
    async def test_empty_parameters(self):
        from app.bd_enrichment import _enrich_bd_maps
        data_block = {"Parameters": []}
        client = AsyncMock()
        result = await _enrich_bd_maps(data_block, client, "http://x/records", {})
        assert result == {"maps": [], "all": []}

    @pytest.mark.asyncio
    async def test_discovers_maps_in_dataspace(self):
        """Should fetch ETPDataspace record, then list Grid2d objects."""
        from app.bd_enrichment import _enrich_bd_maps
        import app.osdu as osdu_mod

        data_block = {
            "Parameters": [{
                "DataObjectParameter": "dev:wpc--ETPDataspace:ds1:1",
                "Keys": [{"StringParameterKey": "ETPDataspace"}],
            }],
        }

        ds_record = {
            "id": "dev:wpc--ETPDataspace:ds1:1",
            "data": {
                "Name": "maap/drogon_dg",
                "DatasetProperties": {"URI": "eml:///dataspace('maap/drogon_dg')"},
            },
        }

        grid2d_objects = [
            {"Uuid": "aaa-111", "name": "DS_extract_simgrid_top", "uri": "eml:///..."},
            {"Uuid": "bbb-222", "name": "Estimated Volumes Table", "uri": "eml:///..."},
            {"Uuid": "ccc-333", "name": "DS_extract_geogrid_base", "uri": "eml:///..."},
        ]

        client = AsyncMock()
        client.get = AsyncMock(return_value=MagicMock(status_code=200, json=MagicMock(return_value=ds_record)))

        with patch.object(osdu_mod, "list_resources", AsyncMock(return_value=grid2d_objects)), \
             patch.object(osdu_mod, "get_resource", AsyncMock(return_value={})):

            result = await _enrich_bd_maps(data_block, client, "http://x/records",
                                           {"Authorization": "Bearer test"})

        assert len(result["all"]) == 3
        # "Estimated Volumes Table" is a table marker → excluded from proper maps
        assert len(result["maps"]) == 2
        # DS_extract_simgrid should sort first
        assert result["maps"][0]["title"] == "DS_extract_simgrid_top"

    @pytest.mark.asyncio
    async def test_limits_to_3_dataspaces(self):
        """Should only process at most 3 ETPDataspace refs."""
        from app.bd_enrichment import _enrich_bd_maps
        import app.osdu as osdu_mod

        data_block = {
            "Parameters": [
                {"DataObjectParameter": f"dev:wpc--ETPDataspace:ds{i}:1",
                 "Keys": [{"StringParameterKey": "ETPDataspace"}]}
                for i in range(5)
            ],
        }

        ds_record = {
            "data": {"Name": "demo", "DatasetProperties": {"URI": "eml:///dataspace('demo')"}},
        }
        client = AsyncMock()
        client.get = AsyncMock(return_value=MagicMock(status_code=200, json=MagicMock(return_value=ds_record)))

        with patch.object(osdu_mod, "list_resources", AsyncMock(return_value=[])), \
             patch.object(osdu_mod, "get_resource", AsyncMock(return_value={})):
            result = await _enrich_bd_maps(data_block, client, "http://x/records",
                                           {"Authorization": "Bearer test"})

        # Should have fetched exactly 3 dataspace records
        assert client.get.call_count == 3


# ── _enrich_bd_production ────────────────────────────────────────────────────

class TestEnrichBdProduction:
    """Test async production forecast fetch + parse."""

    @pytest.mark.asyncio
    async def test_no_production_parameter(self):
        from app.bd_enrichment import _enrich_bd_production
        data_block = {"Parameters": [{"DataObjectParameter": "dev:wpc--GeoLabelSet:x:1"}]}
        client = AsyncMock()
        result = await _enrich_bd_production(data_block, client, "http://x/records", {})
        assert result == {}

    @pytest.mark.asyncio
    async def test_production_forecast_parsed(self):
        """Should fetch CBT record and parse production columns."""
        from app.bd_enrichment import _enrich_bd_production

        data_block = {
            "Parameters": [{
                "DataObjectParameter": "dev:wpc--ColumnBasedTable:prod1:1",
                "Keys": [{"StringParameterKey": "ProductionForecast"}],
            }],
        }

        cbt_record = {
            "data": {
                "Table": {
                    "KeyColumns": [{"ColumnName": "Year"}],
                    "Columns": [
                        {"ColumnName": "FOPR"},
                        {"ColumnName": "FWPR"},
                    ],
                    "ColumnValues": [
                        {"IntegerColumn": [2026, 2027, 2028]},
                        {"NumberColumn": [8500.0, 7200.0, 6100.0]},
                        {"NumberColumn": [200.0, 450.0, 800.0]},
                    ],
                },
            },
        }

        client = AsyncMock()
        client.get = AsyncMock(return_value=MagicMock(
            status_code=200, json=MagicMock(return_value=cbt_record),
        ))

        result = await _enrich_bd_production(data_block, client, "http://x/records", {})
        assert result["Years"] == [2026, 2027, 2028]
        assert result["OilRate_kSm3d"] == [8500.0, 7200.0, 6100.0]
        assert result["WaterRate_kSm3d"] == [200.0, 450.0, 800.0]

    @pytest.mark.asyncio
    async def test_production_dict_format(self):
        """ColumnValues as dict (legacy format)."""
        from app.bd_enrichment import _enrich_bd_production

        data_block = {
            "Parameters": [{
                "DataObjectParameter": "dev:wpc--ColumnBasedTable:prod2:1",
                "Keys": [{"StringParameterKey": "ProductionProfile"}],
            }],
        }

        cbt_record = {
            "data": {
                "Table": {
                    "KeyColumns": [{"ColumnName": "Year"}],
                    "Columns": [{"ColumnName": "OilRate"}],
                    "ColumnValues": {
                        "Year": [2025, 2026],
                        "OilRate": [5000.0, 4500.0],
                    },
                },
            },
        }

        client = AsyncMock()
        client.get = AsyncMock(return_value=MagicMock(
            status_code=200, json=MagicMock(return_value=cbt_record),
        ))

        result = await _enrich_bd_production(data_block, client, "http://x/records", {})
        assert result["Years"] == [2025, 2026]
        assert result["OilRate_kSm3d"] == [5000.0, 4500.0]

    @pytest.mark.asyncio
    async def test_production_fetch_failure(self):
        from app.bd_enrichment import _enrich_bd_production

        data_block = {
            "Parameters": [{
                "DataObjectParameter": "dev:wpc--ColumnBasedTable:bad:1",
                "Keys": [{"StringParameterKey": "ProductionForecast"}],
            }],
        }

        client = AsyncMock()
        client.get = AsyncMock(return_value=MagicMock(status_code=500, json=MagicMock(return_value={})))

        result = await _enrich_bd_production(data_block, client, "http://x/records", {})
        assert result == {}


# ── _enrich_bd_developmentconcept ────────────────────────────────────────────

class TestEnrichBdDevelopmentConcept:
    """Test async DevelopmentConcept WPC fetch + injection."""

    @pytest.mark.asyncio
    async def test_injects_into_ext_equinor(self):
        """Should inject fetched DC fields into data.ext.equinor.DevelopmentConcept."""
        from app.bd_enrichment import _enrich_bd_developmentconcept

        data_block = {
            "Parameters": [{
                "DataObjectParameter": "dev:wpc--DevelopmentConcept:dc1:1",
                "Keys": [{"StringParameterKey": "DevelopmentConcept"}],
            }],
        }

        dc_record = {
            "data": {
                "Name": "Drogon DevConcept",
                "Summary": "FPSO-based development",
                "DecisionGate": "DG2",
                "FacilityConcept": {"FacilityType": "FPSO"},
                "WellPlan": {"Producers": 4, "Injectors": 2},
                "DrainageStrategy": {"PrimaryRecoveryMechanism": "WaterInjection"},
            },
        }

        client = AsyncMock()
        client.get = AsyncMock(return_value=MagicMock(
            status_code=200, json=MagicMock(return_value=dc_record),
        ))

        await _enrich_bd_developmentconcept(data_block, client, "http://x/records", {})

        dc = data_block["ext"]["equinor"]["DevelopmentConcept"]
        assert dc["Name"] == "Drogon DevConcept"
        assert dc["FacilityConcept"]["FacilityType"] == "FPSO"
        assert dc["WellPlan"]["Producers"] == 4
        assert dc["DrainageStrategy"]["PrimaryRecoveryMechanism"] == "WaterInjection"

    @pytest.mark.asyncio
    async def test_no_devconcept_parameter(self):
        from app.bd_enrichment import _enrich_bd_developmentconcept
        data_block = {"Parameters": []}
        client = AsyncMock()
        await _enrich_bd_developmentconcept(data_block, client, "http://x/records", {})
        assert "ext" not in data_block

    @pytest.mark.asyncio
    async def test_fetch_failure_no_injection(self):
        from app.bd_enrichment import _enrich_bd_developmentconcept

        data_block = {
            "Parameters": [{
                "DataObjectParameter": "dev:wpc--DevelopmentConcept:dc1:1",
                "Keys": [{"StringParameterKey": "DevelopmentConcept"}],
            }],
        }

        client = AsyncMock()
        client.get = AsyncMock(return_value=MagicMock(status_code=404, json=MagicMock(return_value={})))

        await _enrich_bd_developmentconcept(data_block, client, "http://x/records", {})
        assert "ext" not in data_block

    @pytest.mark.asyncio
    async def test_preserves_existing_ext(self):
        """Should not clobber existing ext.equinor fields."""
        from app.bd_enrichment import _enrich_bd_developmentconcept

        data_block = {
            "ext": {"equinor": {"ExistingField": "keep"}},
            "Parameters": [{
                "DataObjectParameter": "dev:wpc--DevelopmentConcept:dc1:1",
                "Keys": [{"StringParameterKey": "DevelopmentConcept"}],
            }],
        }

        dc_record = {"data": {"Name": "Test DC"}}
        client = AsyncMock()
        client.get = AsyncMock(return_value=MagicMock(
            status_code=200, json=MagicMock(return_value=dc_record),
        ))

        await _enrich_bd_developmentconcept(data_block, client, "http://x/records", {})
        assert data_block["ext"]["equinor"]["ExistingField"] == "keep"
        assert data_block["ext"]["equinor"]["DevelopmentConcept"]["Name"] == "Test DC"


# ── _enrich_bd_collaboration ────────────────────────────────────────────────

class TestEnrichBdCollaboration:
    """Test async CollaborationProject reverse lookup + extraction."""

    @pytest.mark.asyncio
    async def test_no_record_id_returns_empty(self):
        from app.bd_enrichment import _enrich_bd_collaboration
        data_block = {}
        client = AsyncMock()
        result = await _enrich_bd_collaboration(data_block, client, "http://x/search", "http://x/records", {})
        assert result == {}

    @pytest.mark.asyncio
    async def test_finds_cp_and_extracts_fields(self):
        from app.bd_enrichment import _enrich_bd_collaboration

        data_block = {"_record_id": "dev:wpc--BusinessDecision:dg2:1"}

        search_response = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"results": [{"id": "dev:md--CollaborationProject:cp1:1"}]}),
        )

        cp_record = {
            "data": {
                "ProjectName": "Drogon DG2 Project",
                "LifecycleEvents": [
                    {"EventType": "Created", "EventDate": "2025-01-01"},
                    {"EventType": "Approved", "EventDate": "2026-03-15"},
                ],
                "ActivityStates": [
                    {"MilestoneID": "DG2-Volumes", "ActivityStatusID": "completed"},
                    {"MilestoneID": "DG2-GeoModel", "ActivityStatusID": "in-progress"},
                    {"MilestoneID": "DG3", "ActivityStatusID": "planned"},
                ],
                "Parameters": [
                    {
                        "Title": "REV Link",
                        "DataObjectParameter": "dev:wpc--REV:rev1:1",
                        "Keys": [{"ParameterKey": "relationship", "StringParameterKey": "uses"}],
                    },
                ],
            },
        }

        client = AsyncMock()
        client.post = AsyncMock(return_value=search_response)
        client.get = AsyncMock(return_value=MagicMock(
            status_code=200, json=MagicMock(return_value=cp_record),
        ))

        result = await _enrich_bd_collaboration(
            data_block, client, "http://x/search", "http://x/records", {},
        )

        assert result["cp_name"] == "Drogon DG2 Project"
        assert len(result["events"]) == 2
        assert result["checklist_total"] == 2  # DG2-Volumes + DG2-GeoModel
        assert result["checklist_completed"] == 1  # DG2-Volumes
        assert len(result["relationships"]) == 1
        assert result["relationships"][0]["relationship"] == "uses"

    @pytest.mark.asyncio
    async def test_no_cp_found_returns_empty(self):
        from app.bd_enrichment import _enrich_bd_collaboration

        data_block = {"_record_id": "dev:wpc--BusinessDecision:dg2:1"}

        client = AsyncMock()
        client.post = AsyncMock(return_value=MagicMock(
            status_code=200,
            json=MagicMock(return_value={"results": []}),
        ))

        result = await _enrich_bd_collaboration(
            data_block, client, "http://x/search", "http://x/records", {},
        )
        assert result == {}

    @pytest.mark.asyncio
    async def test_search_failure_returns_empty(self):
        from app.bd_enrichment import _enrich_bd_collaboration

        data_block = {"_record_id": "dev:wpc--BusinessDecision:dg2:1"}

        client = AsyncMock()
        client.post = AsyncMock(side_effect=Exception("network error"))

        result = await _enrich_bd_collaboration(
            data_block, client, "http://x/search", "http://x/records", {},
        )
        assert result == {}


# ── _parse_cbt_production ────────────────────────────────────────────────────

class TestParseCbtProduction:
    """Test CBT production parsing (pure function, no async)."""

    def test_positional_array_format(self):
        from app.bd_enrichment import _parse_cbt_production
        d = {
            "Table": {
                "KeyColumns": [{"ColumnName": "Year"}],
                "Columns": [{"ColumnName": "FOPR"}, {"ColumnName": "FWCT"}],
                "ColumnValues": [
                    {"IntegerColumn": [2025, 2026, 2027]},
                    {"NumberColumn": [9000.0, 7500.0, 6000.0]},
                    {"NumberColumn": [0.05, 0.15, 0.30]},
                ],
            },
        }
        result = _parse_cbt_production(d)
        assert result["Years"] == [2025, 2026, 2027]
        assert result["OilRate_kSm3d"] == [9000.0, 7500.0, 6000.0]
        assert result["WaterCut_pct"] == [0.05, 0.15, 0.30]

    def test_dict_format(self):
        from app.bd_enrichment import _parse_cbt_production
        d = {
            "Table": {
                "KeyColumns": [{"ColumnName": "Year"}],
                "Columns": [{"ColumnName": "OilRate"}],
                "ColumnValues": {"Year": [2025], "OilRate": [5000.0]},
            },
        }
        result = _parse_cbt_production(d)
        assert result["Years"] == [2025]
        assert result["OilRate_kSm3d"] == [5000.0]

    def test_empty_column_values(self):
        from app.bd_enrichment import _parse_cbt_production
        d = {"Table": {"KeyColumns": [], "Columns": [], "ColumnValues": []}}
        result = _parse_cbt_production(d)
        assert result == {}

    def test_with_ext_summary(self):
        from app.bd_enrichment import _parse_cbt_production
        d = {
            "Table": {
                "KeyColumns": [{"ColumnName": "Year"}],
                "Columns": [{"ColumnName": "FOPR"}],
                "ColumnValues": [
                    {"IntegerColumn": [2025]},
                    {"NumberColumn": [1000.0]},
                ],
            },
            "ext": {"equinor": {"ForecastSummary": {"plateau_years": 5}, "Note": "Test note"}},
        }
        result = _parse_cbt_production(d)
        assert result["summary"]["plateau_years"] == 5
        assert result["Note"] == "Test note"

    def test_omega_column_names(self):
        """Omega-style explicit-unit column names should be mapped."""
        from app.bd_enrichment import _parse_cbt_production
        d = {
            "Table": {
                "KeyColumns": [{"ColumnName": "Year"}],
                "Columns": [
                    {"ColumnName": "OilRate_Sm3d"},
                    {"ColumnName": "CumulativeOil_MSm3"},
                ],
                "ColumnValues": [
                    {"IntegerColumn": [2025]},
                    {"NumberColumn": [8000.0]},
                    {"NumberColumn": [2.5]},
                ],
            },
        }
        result = _parse_cbt_production(d)
        assert result["OilRate_kSm3d"] == [8000.0]
        assert result["CumOil_MSm3"] == [2.5]
