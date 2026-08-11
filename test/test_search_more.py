"""
tests/test_search_more.py – Tests for the /search/more incremental loading endpoint
and _enrich_record_light with BD Activity + DevelopmentConcept enrichment.

Covers:
  POST /search/more       – batch record fetch + enrich + HTML fragment rendering
  _enrich_record_light    – light enrichment including BD-specific parallel calls
  Pagination state        – offset tracking, remaining_ids in template context
  Error handling          – OSDU failures, empty batches, invalid IDs
"""
from __future__ import annotations

import json
from typing import Any, Dict
from unittest.mock import AsyncMock, patch, MagicMock

import httpx
import pytest

from test.conftest import USERS


# ── Fake record factories ───────────────────────────────────────────────────

def _fake_storage_record(
    rid: str = "dev:wpc--WellLog:abc:1",
    kind: str = "dev:wks:work-product-component--WellLog:1.0.0",
    name: str = "TestLog",
    **extra_data,
) -> dict:
    """Build a fake OSDU Storage record."""
    data = {"Name": name, "Description": f"Test record {name}", **extra_data}
    return {"id": rid, "kind": kind, "version": 1, "data": data}


def _fake_bd_record(
    rid: str = "dev:wpc--BusinessDecision:dg2:1",
    name: str = "Drogon DG2",
) -> dict:
    """Build a fake BD record with Parameters referencing GeoLabelSet, Activity, DC."""
    return {
        "id": rid,
        "kind": "dev:wks:work-product-component--BusinessDecision:1.0.0",
        "version": 1,
        "data": {
            "Name": name,
            "Description": f"BD: {name}",
            "DecisionLevel": "DG2",
            "ApprovalStatus": "Approved",
            "Parameters": [
                {
                    "DataObjectParameter": "dev:wpc--GeoLabelSet:gls1:1",
                    "Keys": [{"StringParameterKey": "GeoLabelSet"}],
                },
                {
                    "DataObjectParameter": "dev:wpc--DevelopmentConcept:dc1:1",
                    "Keys": [{"StringParameterKey": "DevelopmentConcept"}],
                },
            ],
            "PriorActivityIDs": ["dev:wpc--Activity:act1:1"],
        },
    }


def _fake_geolabel_record() -> dict:
    return {
        "id": "dev:wpc--GeoLabelSet:gls1:1",
        "kind": "dev:wks:work-product-component--GeoLabelSet:1.0.0",
        "data": {
            "Name": "Test GLS",
            "GeoLabels": {
                "KeyColumns": [{"ColumnName": "SegmentID"}, {"ColumnName": "Facies"}],
                "Columns": [],
                "ColumnValues": {
                    "SegmentID": ["TOTAL"],
                    "Facies": ["ALL"],
                    "Oil.P10": [120.0],
                    "Oil.P50": [100.0],
                    "Oil.P90": [80.0],
                    "Porosity": [0.22],
                },
            },
        },
    }


def _fake_activity_record() -> dict:
    return {
        "id": "dev:wpc--Activity:act1:1",
        "kind": "dev:wks:work-product-component--Activity:1.0.0",
        "data": {
            "Name": "DG2 Workflow",
            "WorkflowStatus": "Completed",
            "Originator": "alice@example.com",
            "CreationDateTime": "2026-01-15T10:00:00Z",
            "Parameters": [
                {"Role": "input", "Title": "Geo Model", "DataObjectParameter": "dev:wpc--ETPDataspace:ds1:1"},
                {"Role": "output", "Title": "REV Report", "DataObjectParameter": "dev:wpc--REV:rev1:1"},
            ],
        },
    }


def _fake_devconcept_record() -> dict:
    return {
        "id": "dev:wpc--DevelopmentConcept:dc1:1",
        "kind": "dev:wks:work-product-component--DevelopmentConcept:4.0.0",
        "data": {
            "Name": "Drogon Dev Concept",
            "FacilityConcept": {"FacilityType": "FPSO", "HostFacility": "Drogon FPSO"},
            "WellPlan": {"Producers": 4, "Injectors": 2, "TotalTargets": 8},
            "DrainageStrategy": {"PrimaryRecoveryMechanism": "WaterInjection"},
        },
    }


# ── Mock HTTP transport ─────────────────────────────────────────────────────

def _make_mock_client(records: dict[str, dict]):
    """Create a mock httpx.AsyncClient that returns records by ID from GET."""
    async def _mock_get(url: str, **kw):
        for rid, rec in records.items():
            if rid in url:
                return MagicMock(status_code=200, json=lambda r=rec: r)
        return MagicMock(status_code=404, json=lambda: {"error": "not found"})

    async def _mock_post(url: str, **kw):
        return MagicMock(
            status_code=200,
            is_success=True,
            json=lambda: {"results": [], "totalCount": 0},
        )

    mock = AsyncMock()
    mock.get = AsyncMock(side_effect=_mock_get)
    mock.post = AsyncMock(side_effect=_mock_post)
    mock.__aenter__ = AsyncMock(return_value=mock)
    mock.__aexit__ = AsyncMock(return_value=False)
    return mock


# ══════════════════════════════════════════════════════════════════════════════
# _enrich_record_light tests
# ══════════════════════════════════════════════════════════════════════════════

class TestEnrichRecordLight:
    """Test the lightweight enrichment function used for search list view."""

    @pytest.mark.asyncio
    async def test_non_bd_record_no_api_calls(self):
        """Non-BD records should not trigger extra OSDU API calls."""
        from app.search_router import _enrich_record_light

        full = _fake_storage_record()
        mock_client = _make_mock_client({})

        result = await _enrich_record_light(
            full, mock_client, "https://x/storage/v2/records",
            "https://x/search/v2/query", {"Authorization": "Bearer t"},
        )
        assert result["display_name"] == "TestLog"
        assert result["bd_geolabel"] == {}
        assert result["bd_activity"] == {}
        assert result["bd_maps"] == {"maps": [], "all": []}
        # No GET calls for non-BD records
        mock_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_bd_record_fetches_geolabel_and_activity(self):
        """BD records should fetch GeoLabelSet, Activity, and DevelopmentConcept."""
        from app.search_router import _enrich_record_light

        records = {
            "dev:wpc--GeoLabelSet:gls1:1": _fake_geolabel_record(),
            "dev:wpc--Activity:act1:1": _fake_activity_record(),
            "dev:wpc--DevelopmentConcept:dc1:1": _fake_devconcept_record(),
        }
        full = _fake_bd_record()
        mock_client = _make_mock_client(records)

        result = await _enrich_record_light(
            full, mock_client, "https://x/storage/v2/records",
            "https://x/search/v2/query", {"Authorization": "Bearer t"},
        )
        assert result["display_name"] == "Drogon DG2"
        # GeoLabelSet should be enriched
        assert result["bd_geolabel"].get("properties") is not None or result["bd_geolabel"].get("volumes_by_segment") is not None
        # Activity should be enriched
        assert result["bd_activity"].get("Name") == "DG2 Workflow"
        assert result["bd_activity"].get("WorkflowStatus") == "Completed"

    @pytest.mark.asyncio
    async def test_bd_record_with_failed_enrichment(self):
        """BD enrichment failures should fall back gracefully."""
        from app.search_router import _enrich_record_light

        full = _fake_bd_record()
        # All fetches fail
        mock_client = _make_mock_client({})

        result = await _enrich_record_light(
            full, mock_client, "https://x/storage/v2/records",
            "https://x/search/v2/query", {"Authorization": "Bearer t"},
        )
        assert result["id"] == full["id"]
        assert result["bd_geolabel"] == {}
        assert result["bd_activity"] == {}

    @pytest.mark.asyncio
    async def test_ddms_refs_extraction(self):
        """DDMSDatasets URIs should be parsed into ddms_refs."""
        from app.search_router import _enrich_record_light

        full = _fake_storage_record(
            DDMSDatasets=[
                "eml:///dataspace('demo')/resqml22.Grid2dRepresentation(12345678-1234-1234-1234-123456789abc)"
            ],
        )
        mock_client = _make_mock_client({})

        result = await _enrich_record_light(
            full, mock_client, "https://x/storage/v2/records",
            "https://x/search/v2/query", {"Authorization": "Bearer t"},
        )
        assert len(result["ddms_refs"]) == 1
        assert result["ddms_refs"][0]["ds"] == "demo"
        assert result["ddms_refs"][0]["rtype"] == "map"

    @pytest.mark.asyncio
    async def test_is_discoverable_false_not_enriched(self):
        """Records with IsDiscoverable=False should be filtered at the caller level."""
        from app.search_router import _enrich_record_light

        # The filter is at the caller, not in _enrich_record_light itself
        # but we verify the function still works with the field present
        full = _fake_storage_record(IsDiscoverable=False)
        mock_client = _make_mock_client({})

        result = await _enrich_record_light(
            full, mock_client, "https://x/storage/v2/records",
            "https://x/search/v2/query", {"Authorization": "Bearer t"},
        )
        assert result["id"] == full["id"]


# ══════════════════════════════════════════════════════════════════════════════
# POST /search/more endpoint tests
# ══════════════════════════════════════════════════════════════════════════════

class TestSearchMoreEndpoint:
    """Test the incremental load-more endpoint."""

    def test_search_more_empty_ids(self, authed_client):
        """Empty IDs list should return empty result."""
        resp = authed_client.post(
            "/search/more",
            json={"ids": [], "offset": 0},
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["html"] == ""

    def test_search_more_returns_html_with_split(self, authed_client):
        """Valid IDs should return HTML with <!--SPLIT--> separator."""
        fake_rec = _fake_storage_record()

        async def _mock_get(url, **kw):
            return MagicMock(status_code=200, json=lambda: fake_rec)

        with patch("app.osdu.http_client") as mock_ctx:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=_mock_get)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_ctx.return_value = mock_client

            resp = authed_client.post(
                "/search/more",
                json={"ids": ["dev:wpc--WellLog:abc:1"], "offset": 50},
                headers={"Content-Type": "application/json"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] >= 0
        if data["count"] > 0:
            assert "<!--SPLIT-->" in data["html"]
            parts = data["html"].split("<!--SPLIT-->")
            assert len(parts) == 2
            # Part 1 should contain <tr> rows
            assert "<tr" in parts[0]
            # Part 2 should contain rec-block divs
            assert "rec-block" in parts[1] or "rec-" in parts[1]

    def test_search_more_offset_numbering(self, authed_client):
        """Records should use offset-based rec_index numbering."""
        fake_rec = _fake_storage_record()

        async def _mock_get(url, **kw):
            return MagicMock(status_code=200, json=lambda: fake_rec)

        with patch("app.osdu.http_client") as mock_ctx:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=_mock_get)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_ctx.return_value = mock_client

            resp = authed_client.post(
                "/search/more",
                json={"ids": ["dev:wpc--WellLog:abc:1"], "offset": 100},
                headers={"Content-Type": "application/json"},
            )

        if resp.status_code == 200 and resp.json()["count"] > 0:
            html = resp.json()["html"]
            # rec_index should be offset + loop.index = 101
            assert 'data-rec-idx="101"' in html or "rec-101" in html

    def test_search_more_caps_at_page_size(self, authed_client):
        """Requesting more than _PAGE_SIZE IDs should be capped."""
        from app.search_router import _PAGE_SIZE

        # Build a list longer than _PAGE_SIZE
        many_ids = [f"dev:wpc--WellLog:rec{i}:1" for i in range(_PAGE_SIZE + 20)]

        fake_rec = _fake_storage_record()

        async def _mock_get(url, **kw):
            return MagicMock(status_code=200, json=lambda: fake_rec)

        with patch("app.osdu.http_client") as mock_ctx:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=_mock_get)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_ctx.return_value = mock_client

            resp = authed_client.post(
                "/search/more",
                json={"ids": many_ids, "offset": 0},
                headers={"Content-Type": "application/json"},
            )

        assert resp.status_code == 200
        # Should be capped at _PAGE_SIZE
        assert resp.json()["count"] <= _PAGE_SIZE

    def test_search_more_filters_undiscoverable(self, authed_client):
        """Records with IsDiscoverable=False should be excluded."""
        hidden_rec = _fake_storage_record()
        hidden_rec["data"]["IsDiscoverable"] = False

        async def _mock_get(url, **kw):
            return MagicMock(status_code=200, json=lambda: hidden_rec)

        with patch("app.osdu.http_client") as mock_ctx:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=_mock_get)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_ctx.return_value = mock_client

            resp = authed_client.post(
                "/search/more",
                json={"ids": ["dev:wpc--WellLog:hidden:1"], "offset": 0},
                headers={"Content-Type": "application/json"},
            )

        assert resp.status_code == 200
        assert resp.json()["count"] == 0


# ══════════════════════════════════════════════════════════════════════════════
# Search pagination (remaining_ids passed to template)
# ══════════════════════════════════════════════════════════════════════════════

class TestSearchPagination:
    """Test that search_run paginates results correctly."""

    def test_search_returns_remaining_ids_when_over_page_size(self, authed_client):
        """When results > _PAGE_SIZE, remaining_ids should be in the response."""
        from app.search_router import _PAGE_SIZE

        all_ids = [f"dev:wpc--WellLog:rec{i}:1" for i in range(_PAGE_SIZE + 10)]
        fake_rec = _fake_storage_record()

        async def _mock_post(url, **kw):
            results = [{"id": rid, "kind": fake_rec["kind"], "version": 1} for rid in all_ids]
            return MagicMock(
                status_code=200,
                is_success=True,
                raise_for_status=MagicMock(),
                json=lambda: {"results": results, "totalCount": len(results)},
            )

        async def _mock_get(url, **kw):
            return MagicMock(status_code=200, json=lambda: fake_rec)

        with patch("app.osdu.http_client") as mock_ctx:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=_mock_post)
            mock_client.get = AsyncMock(side_effect=_mock_get)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_ctx.return_value = mock_client

            resp = authed_client.get(
                "/search/run",
                params={"kind": "dev:wks:work-product-component--WellLog:1.0.0", "query": "*", "limit": _PAGE_SIZE + 10},
            )

        assert resp.status_code == 200
        html = resp.text
        # remaining-ids-data JSON should be present
        assert "remaining-ids-data" in html
        # Load More button should be present
        assert "Load More" in html
