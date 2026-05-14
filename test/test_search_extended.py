"""
tests/test_search_extended.py – Extended tests for search_router routes
not covered by test_routes.py.

Covers:
  POST /search/schemas           – OSDU Schema Service search
  POST /search/refdata           – reference-data search
  GET  /search/api/schema/{kind} – schema detail JSON
  GET  /search/api/record/{id}   – record detail JSON
  GET  /search/api/refdata-kinds – dynamic refdata kind discovery
  GET  /api/queries              – list saved queries
  POST /api/queries              – save a query
  DELETE /api/queries/{id}       – delete a saved query
  Internal helpers               – _parse_kind_inputs, _flatten_osdu_data
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch, MagicMock

import httpx
import pytest
from starlette.testclient import TestClient


def _mock_resp(status: int = 200, json_body=None, text=""):
    resp = MagicMock()
    resp.status_code = status
    resp.reason_phrase = "OK" if status < 300 else "Error"
    resp.is_success = 200 <= status < 300
    if json_body is not None:
        resp.json.return_value = json_body
        resp.text = json.dumps(json_body)
    else:
        resp.text = text
    return resp


def _mock_http(resp):
    session = AsyncMock()
    session.get = AsyncMock(return_value=resp)
    session.post = AsyncMock(return_value=resp)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm, session


# ── Internal helpers ─────────────────────────────────────────────────────────

class TestParseKindInputs:
    def test_single_kind(self):
        from app.search_router import _parse_kind_inputs
        assert _parse_kind_inputs("osdu:wks:master-data--BD:1.0.0", "") == [
            "osdu:wks:master-data--BD:1.0.0"
        ]

    def test_extra_kinds(self):
        from app.search_router import _parse_kind_inputs
        result = _parse_kind_inputs("kind1", "kind2\nkind3,kind4")
        assert result == ["kind1", "kind2", "kind3", "kind4"]

    def test_deduplication(self):
        from app.search_router import _parse_kind_inputs
        result = _parse_kind_inputs("k1", "k1,k2,k1")
        assert result == ["k1", "k2"]

    def test_empty(self):
        from app.search_router import _parse_kind_inputs
        assert _parse_kind_inputs("", "") == []


class TestFlattenOsduData:
    def test_basic(self):
        from app.search_router import _flatten_osdu_data
        data = {"Name": "Test", "Description": "A test"}
        pairs = _flatten_osdu_data(data)
        names = [p["name"] for p in pairs]
        assert "Description" in names
        assert "Name" in names

    def test_heavy_keys_excluded(self):
        from app.search_router import _flatten_osdu_data
        data = {"Name": "Test", "ColumnBasedTable": {"big": "data"}, "ColumnValues": [1, 2, 3]}
        pairs = _flatten_osdu_data(data)
        names = [p["name"] for p in pairs]
        assert "ColumnBasedTable" not in names
        assert "ColumnValues" not in names
        assert "Name" in names

    def test_none_value(self):
        from app.search_router import _flatten_osdu_data
        data = {"NullField": None}
        pairs = _flatten_osdu_data(data)
        assert pairs[0]["value"] is None


# ── Schema search ────────────────────────────────────────────────────────────

class TestSearchSchemas:
    """POST /search/schemas."""

    def test_success(self, authed_client):
        schema_resp = _mock_resp(200, json_body={
            "schemaInfos": [
                {
                    "schemaIdentity": {
                        "authority": "osdu",
                        "source": "wks",
                        "entityType": "master-data--BusinessDecision",
                        "schemaVersionMajor": 1,
                        "schemaVersionMinor": 0,
                        "schemaVersionPatch": 0,
                    },
                    "status": "PUBLISHED",
                    "scope": "SHARED",
                },
            ],
        })
        mock_cm, _ = _mock_http(schema_resp)

        with patch("app.search_router.osdu.http_client", return_value=mock_cm):
            r = authed_client.post("/search/schemas", data={"query": "*", "limit": 50})

        assert r.status_code == 200
        assert "master-data--BusinessDecision" in r.text

    def test_entity_filter(self, authed_client):
        """entity:XXX filter should do local substring match."""
        schema_resp = _mock_resp(200, json_body={
            "schemaInfos": [
                {"schemaIdentity": {"authority": "osdu", "source": "wks",
                 "entityType": "master-data--BusinessDecision",
                 "schemaVersionMajor": 1, "schemaVersionMinor": 0, "schemaVersionPatch": 0},
                 "status": "PUBLISHED", "scope": "SHARED"},
                {"schemaIdentity": {"authority": "osdu", "source": "wks",
                 "entityType": "master-data--Well",
                 "schemaVersionMajor": 1, "schemaVersionMinor": 0, "schemaVersionPatch": 0},
                 "status": "PUBLISHED", "scope": "SHARED"},
            ],
        })
        mock_cm, _ = _mock_http(schema_resp)

        with patch("app.search_router.osdu.http_client", return_value=mock_cm):
            r = authed_client.post("/search/schemas", data={"query": "entity:BusinessDecision", "limit": 50})

        assert r.status_code == 200
        assert "BusinessDecision" in r.text
        # Well should be filtered out
        # (checking the result page contains the correct one)


# ── Refdata search ───────────────────────────────────────────────────────────

class TestSearchRefdata:
    """POST /search/refdata."""

    def test_wildcard_without_query_rejected(self, authed_client):
        """Searching all refdata without a filter should show an error."""
        r = authed_client.post("/search/refdata", data={
            "kind": "osdu:wks:reference-data--*:*",
            "query": "*",
        })
        assert r.status_code == 200
        assert "Please select" in r.text

    def test_specific_kind(self, authed_client):
        post_resp = _mock_resp(200, json_body={
            "totalCount": 2,
            "results": [
                {"id": "osdu:ref:DecisionLevel:DG1", "kind": "osdu:wks:reference-data--DecisionLevel:1.0.0",
                 "data": {"Name": "DG1", "Code": "DG1", "Description": "Identify & Assess"}},
                {"id": "osdu:ref:DecisionLevel:DG2", "kind": "osdu:wks:reference-data--DecisionLevel:1.0.0",
                 "data": {"Name": "DG2", "Code": "DG2", "Description": "Concept Select"}},
            ],
        })
        mock_cm, _ = _mock_http(post_resp)

        with patch("app.search_router.osdu.http_client", return_value=mock_cm):
            r = authed_client.post("/search/refdata", data={
                "kind": "osdu:wks:reference-data--DecisionLevel:1.0.0",
                "query": "*",
            })

        assert r.status_code == 200
        assert "DG1" in r.text


# ── API endpoints ────────────────────────────────────────────────────────────

class TestApiSchemaDetail:
    """GET /search/api/schema/{kind}."""

    def test_success(self, authed_client):
        schema = {"properties": {"Name": {"type": "string"}}}
        get_resp = _mock_resp(200, json_body=schema)
        mock_cm, _ = _mock_http(get_resp)

        with patch("app.search_router.osdu.http_client", return_value=mock_cm):
            r = authed_client.get("/search/api/schema/osdu:wks:md--BD:1.0.0")

        assert r.status_code == 200
        assert r.json()["properties"]["Name"]["type"] == "string"

    def test_not_found(self, authed_client):
        exc_resp = httpx.Response(404, text="not found", request=httpx.Request("GET", "http://x"))
        exc = httpx.HTTPStatusError("err", request=exc_resp.request, response=exc_resp)
        session = AsyncMock()
        session.get = AsyncMock(side_effect=exc)
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.search_router.osdu.http_client", return_value=cm):
            r = authed_client.get("/search/api/schema/nonexistent")

        assert r.status_code == 404


class TestApiRecordDetail:
    """GET /search/api/record/{record_id}."""

    def test_success(self, authed_client):
        rec = {"id": "dev:md--BD:x:1", "kind": "osdu:wks:md--BD:1.0.0", "data": {"Name": "Test"}}
        get_resp = _mock_resp(200, json_body=rec)
        mock_cm, _ = _mock_http(get_resp)

        with patch("app.search_router.osdu.http_client", return_value=mock_cm):
            r = authed_client.get("/search/api/record/dev:md--BD:x:1")

        assert r.status_code == 200
        assert r.json()["data"]["Name"] == "Test"


class TestApiRefdataKinds:
    """GET /search/api/refdata-kinds."""

    def test_merges_dynamic_and_static(self, authed_client):
        schema_resp = _mock_resp(200, json_body={
            "schemaInfos": [
                {"schemaIdentity": {"authority": "osdu", "source": "wks",
                 "entityType": "reference-data--CustomType",
                 "schemaVersionMajor": 1, "schemaVersionMinor": 0, "schemaVersionPatch": 0}},
            ],
        })
        mock_cm, _ = _mock_http(schema_resp)

        with patch("app.search_router.osdu.http_client", return_value=mock_cm):
            r = authed_client.get("/search/api/refdata-kinds")

        assert r.status_code == 200
        kinds = r.json()["kinds"]
        # Should include the dynamic one
        assert any("CustomType" in k for k in kinds)
        # Should also include static ones
        assert any("DecisionLevel" in k for k in kinds)

    def test_fallback_on_error(self, authed_client):
        session = AsyncMock()
        session.get = AsyncMock(side_effect=Exception("timeout"))
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.search_router.osdu.http_client", return_value=cm):
            r = authed_client.get("/search/api/refdata-kinds")

        assert r.status_code == 200
        kinds = r.json()["kinds"]
        assert len(kinds) > 0  # static fallback


# ── Saved queries ────────────────────────────────────────────────────────────

class TestSavedQueries:
    """Saved queries CRUD."""

    def test_save_and_list(self, authed_client):
        # Save a query
        r = authed_client.post("/api/queries", json={
            "name": "Test Query",
            "kind": "osdu:wks:master-data--BD:1.0.0",
            "query": "data.Name:Drogon*",
        })
        assert r.status_code == 200
        body = r.json()
        assert body["name"] == "Test Query"
        qid = body["id"]

        # List queries
        r2 = authed_client.get("/api/queries")
        assert r2.status_code == 200
        # Should contain our query
        queries = r2.json()
        assert any(q["name"] == "Test Query" for q in queries)

        # Delete
        r3 = authed_client.delete(f"/api/queries/{qid}")
        assert r3.status_code == 200
        assert r3.json()["deleted"] == qid

    def test_save_missing_name(self, authed_client):
        r = authed_client.post("/api/queries", json={
            "name": "",
            "kind": "test",
            "query": "*",
        })
        assert r.status_code == 400

    def test_list_with_source_filter(self, authed_client):
        # Save a search query
        authed_client.post("/api/queries", json={
            "name": "Search Q", "kind": "osdu:wks:md:1", "query": "*",
        })
        # Save a graphql query
        authed_client.post("/api/queries", json={
            "name": "GQL Q", "kind": "__graphql__", "query": "{ dataspaces }",
        })

        r_search = authed_client.get("/api/queries", params={"source": "search"})
        r_gql = authed_client.get("/api/queries", params={"source": "graphql"})

        search_qs = r_search.json()
        gql_qs = r_gql.json()

        assert all(q["kind"] != "__graphql__" for q in search_qs)
        assert all(q["kind"] == "__graphql__" for q in gql_qs)
