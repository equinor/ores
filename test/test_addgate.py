"""
tests/test_addgate.py – Integration tests for the AddGate (record creation) routes.

Covers:
  POST /add-dg/create          – create BusinessDecision
  POST /add-dg/create-cp       – create CollaborationProject
  POST /add-dg/create-pc       – create PersistedCollection
  POST /add-dg/create-activity-template – create ActivityTemplate
  POST /add-dg/create-activity  – create Activity
  POST /add-dg/create-generic   – create generic record
  GET  /add-dg/reservoirs       – reservoir list
  GET  /add-dg/wpc-search       – WPC kind search
  GET  /add-dg/fetch-record     – fetch single record by ID
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch, MagicMock

import httpx
import pytest
from starlette.testclient import TestClient


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_mock_response(status: int = 200, json_body: dict | list | None = None, text: str = ""):
    """Create a mock httpx.Response object."""
    resp = MagicMock()
    resp.status_code = status
    resp.reason_phrase = httpx.codes.get_reason_phrase(status) if status in httpx.codes else "Unknown"
    resp.is_success = 200 <= status < 300
    if json_body is not None:
        resp.json.return_value = json_body
        resp.text = json.dumps(json_body)
    else:
        resp.text = text
    return resp


def _mock_http_client(responses: dict[str, MagicMock] | MagicMock = None):
    """Build a patched osdu.http_client context manager.

    If responses is a single mock, all calls return it.
    If a dict, keyed by method (get/post/put/delete).
    """
    mock_session = AsyncMock()
    if isinstance(responses, dict):
        for meth, resp in responses.items():
            setattr(mock_session, meth, AsyncMock(return_value=resp))
    elif responses is not None:
        mock_session.get = AsyncMock(return_value=responses)
        mock_session.post = AsyncMock(return_value=responses)
        mock_session.put = AsyncMock(return_value=responses)
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    return mock_cm, mock_session


# ── create BD ────────────────────────────────────────────────────────────────

class TestCreateBD:
    """POST /add-dg/create – create a BusinessDecision record."""

    def test_success(self, authed_client):
        put_resp = _make_mock_response(201, json_body={"recordIds": ["dev:master-data--BusinessDecision:Test:1"]})
        mock_cm, mock_session = _mock_http_client({"put": put_resp})

        with patch("app.addgate.osdu.http_client", return_value=mock_cm):
            r = authed_client.post("/add-dg/create", json={
                "reservoir_id": "dev:master-data--Reservoir:Drogon:1",
                "name": "Test BD",
                "description": "A test BD",
                "decision_level": "DG2",
            })

        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert "bd_id" in body
        assert body["status"] == 201

    def test_missing_reservoir_id(self, authed_client):
        r = authed_client.post("/add-dg/create", json={
            "reservoir_id": "",
            "name": "Test BD",
        })
        assert r.status_code == 400

    def test_missing_name(self, authed_client):
        r = authed_client.post("/add-dg/create", json={
            "reservoir_id": "dev:master-data--Reservoir:X:1",
            "name": "",
        })
        assert r.status_code == 400

    def test_storage_api_error(self, authed_client):
        put_resp = _make_mock_response(403, json_body={"message": "Access denied"})
        mock_cm, _ = _mock_http_client({"put": put_resp})

        with patch("app.addgate.osdu.http_client", return_value=mock_cm):
            r = authed_client.post("/add-dg/create", json={
                "reservoir_id": "dev:master-data--Reservoir:Drogon:1",
                "name": "Test BD",
            })

        assert r.status_code == 403
        body = r.json()
        assert body["ok"] is False

    def test_network_exception(self, authed_client):
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(side_effect=httpx.ConnectError("timeout"))
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.addgate.osdu.http_client", return_value=mock_cm):
            r = authed_client.post("/add-dg/create", json={
                "reservoir_id": "dev:master-data--Reservoir:Drogon:1",
                "name": "Test BD",
            })

        assert r.status_code == 502
        body = r.json()
        assert body["ok"] is False

    def test_linked_records(self, authed_client):
        """BD with various linked records builds all Parameters."""
        put_resp = _make_mock_response(201, json_body={"recordIds": ["x"]})
        mock_cm, mock_session = _mock_http_client({"put": put_resp})

        with patch("app.addgate.osdu.http_client", return_value=mock_cm):
            r = authed_client.post("/add-dg/create", json={
                "reservoir_id": "dev:master-data--Reservoir:Drogon:1",
                "name": "Linked BD",
                "geolabelset_id": "dev:wpc--GeoLabelSet:gls:1",
                "rev_stats_id": "dev:wpc--ReservoirEstimatedVolumes:stats:1",
                "dataspace_id": "dev:dataset--ETPDataspace:ds:1",
                "risk_ids": ["dev:master-data--Risk:r1:1", "dev:master-data--Risk:r2:1"],
                "custom_records": [{"label": "Doc", "id": "dev:wpc--Document:doc:1"}],
            })

        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        # geolabelset + rev_stats + dataspace + custom + reservoir = 5 params
        assert body["parameters_count"] >= 5
        assert body["risk_count"] == 2


# ── create CP ────────────────────────────────────────────────────────────────

class TestCreateCP:
    """POST /add-dg/create-cp – create a CollaborationProject."""

    def test_success(self, authed_client):
        put_resp = _make_mock_response(201, json_body={"recordIds": ["x"]})
        mock_cm, _ = _mock_http_client({"put": put_resp})

        with patch("app.addgate.osdu.http_client", return_value=mock_cm):
            r = authed_client.post("/add-dg/create-cp", json={
                "name": "Test Project",
                "description": "A project",
                "purpose": "Testing",
            })

        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert "cp_id" in body

    def test_missing_name(self, authed_client):
        r = authed_client.post("/add-dg/create-cp", json={"name": ""})
        assert r.status_code == 400


# ── create PC ────────────────────────────────────────────────────────────────

class TestCreatePC:
    """POST /add-dg/create-pc – create a PersistedCollection."""

    def test_success(self, authed_client):
        put_resp = _make_mock_response(201, json_body={"recordIds": ["x"]})
        mock_cm, _ = _mock_http_client({"put": put_resp})

        with patch("app.addgate.osdu.http_client", return_value=mock_cm):
            r = authed_client.post("/add-dg/create-pc", json={
                "name": "Test Collection",
                "description": "A collection",
                "data_references": ["dev:wpc--X:a:1", "dev:wpc--X:b:1"],
                "tags": "tag1, tag2",
            })

        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["data_references_count"] == 2
        assert body["tags"] == ["tag1", "tag2"]

    def test_missing_name(self, authed_client):
        r = authed_client.post("/add-dg/create-pc", json={"name": ""})
        assert r.status_code == 400


# ── create ActivityTemplate ──────────────────────────────────────────────────

class TestCreateActivityTemplate:
    """POST /add-dg/create-activity-template."""

    def test_success(self, authed_client):
        put_resp = _make_mock_response(201, json_body={"recordIds": ["x"]})
        mock_cm, _ = _mock_http_client({"put": put_resp})

        with patch("app.addgate.osdu.http_client", return_value=mock_cm):
            r = authed_client.post("/add-dg/create-activity-template", json={
                "name": "FMU Template",
                "description": "Standard FMU workflow template",
                "parameter_templates": [
                    {"Title": "Input volumes", "IsInput": True, "MinOccurs": 1, "MaxOccurs": 1},
                ],
            })

        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["param_count"] == 1

    def test_missing_name(self, authed_client):
        r = authed_client.post("/add-dg/create-activity-template", json={"name": ""})
        assert r.status_code == 400


# ── create Activity ──────────────────────────────────────────────────────────

class TestCreateActivity:
    """POST /add-dg/create-activity."""

    def test_success(self, authed_client):
        put_resp = _make_mock_response(201, json_body={"recordIds": ["x"]})
        mock_cm, _ = _mock_http_client({"put": put_resp})

        with patch("app.addgate.osdu.http_client", return_value=mock_cm):
            r = authed_client.post("/add-dg/create-activity", json={
                "name": "DG2 Workflow Run",
                "template_id": "dev:wpc--ActivityTemplate:tmpl:1",
                "workflow_status": "Completed",
                "parameters": [
                    {"title": "Volumes input", "role": "input", "kind": "DataObject", "value": "dev:wpc--REV:vol:1"},
                ],
            })

        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True

    def test_missing_name(self, authed_client):
        r = authed_client.post("/add-dg/create-activity", json={"name": ""})
        assert r.status_code == 400


# ── fetch-record ─────────────────────────────────────────────────────────────

class TestFetchRecord:
    """GET /add-dg/fetch-record?id=…"""

    def test_success(self, authed_client):
        get_resp = _make_mock_response(200, json_body={
            "data": {"Name": "Test"},
            "kind": "osdu:wks:wpc--X:1.0.0",
        })
        mock_cm, _ = _mock_http_client(get_resp)

        with patch("app.addgate.osdu.http_client", return_value=mock_cm):
            r = authed_client.get("/add-dg/fetch-record", params={"id": "dev:wpc--X:a:1"})

        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["data"]["Name"] == "Test"

    def test_not_found(self, authed_client):
        get_resp = _make_mock_response(404, text="Not found")
        mock_cm, _ = _mock_http_client(get_resp)

        with patch("app.addgate.osdu.http_client", return_value=mock_cm):
            r = authed_client.get("/add-dg/fetch-record", params={"id": "missing:x:1"})

        assert r.status_code == 404
        body = r.json()
        assert body["ok"] is False


# ── wpc-search ───────────────────────────────────────────────────────────────

class TestWpcSearch:
    """GET /add-dg/wpc-search?kind=…"""

    def test_empty_kind_returns_empty(self, authed_client):
        r = authed_client.get("/add-dg/wpc-search", params={"kind": ""})
        assert r.status_code == 200
        assert r.json() == []

    def test_with_results(self, authed_client):
        post_resp = _make_mock_response(200, json_body={
            "results": [
                {"id": "dev:wpc--X:a:1", "kind": "osdu:wks:wpc--X:1.0.0",
                 "data": {"Name": "Result A"}},
            ],
        })
        mock_cm, _ = _mock_http_client({"post": post_resp})

        with patch("app.addgate.osdu.http_client", return_value=mock_cm):
            r = authed_client.get("/add-dg/wpc-search", params={
                "kind": "osdu:wks:wpc--X:*",
                "q": "*",
            })

        assert r.status_code == 200
        results = r.json()
        assert len(results) == 1
        assert results[0]["name"] == "Result A"


# ── reservoirs ───────────────────────────────────────────────────────────────

class TestReservoirs:
    """GET /add-dg/reservoirs."""

    def test_returns_list(self, authed_client):
        """If search returns results, reservoirs endpoint returns JSON list."""
        post_resp = _make_mock_response(200, json_body={
            "results": [
                {"id": "dev:master-data--Reservoir:Drogon:1", "kind": "osdu:wks:master-data--Reservoir:2.0.0", "version": 1},
            ],
        })
        get_resp = _make_mock_response(200, json_body={
            "data": {"Name": "Drogon Reservoir"},
        })

        mock_session = AsyncMock()
        mock_session.post = AsyncMock(return_value=post_resp)
        mock_session.get = AsyncMock(return_value=get_resp)
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.common.osdu.http_client", return_value=mock_cm), \
             patch("app.common.osdu.headers", return_value={"Authorization": "Bearer x"}):
            r = authed_client.get("/add-dg/reservoirs")

        assert r.status_code == 200
        assert isinstance(r.json(), list)
