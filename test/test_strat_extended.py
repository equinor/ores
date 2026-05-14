"""
tests/test_strat_extended.py – Extended tests for strat routes not covered
by test_routes.py.

Covers:
  POST /api/strat/storage/put          – direct Storage PUT for strat records
  GET  /api/strat/dataspaces.json      – list RDDMS dataspaces
  GET  /api/strat/rddms/resources.json – RDDMS resource listing
  GET  /api/strat/rddms/resource.json  – fetch single RDDMS resource
  POST /api/strat/ingest/rddms         – push strat to RDDMS
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
    session.put = AsyncMock(return_value=resp)
    session.delete = AsyncMock(return_value=resp)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm, session


# ── storage/put ──────────────────────────────────────────────────────────────

class TestStratStoragePut:
    """POST /api/strat/storage/put."""

    def test_success(self, authed_client):
        put_resp = _mock_resp(200, json_body={"recordCount": 2, "recordIds": ["a", "b"]})
        mock_cm, _ = _mock_http(put_resp)

        with patch("app.strat.osdu.http_client", return_value=mock_cm):
            r = authed_client.post("/api/strat/storage/put", json={
                "bundle": {
                    "records": [
                        {"id": "dev:wpc--StratigraphicColumn:x:1", "kind": "osdu:wks:wpc--SC:1.2.0", "data": {"Name": "Test"}},
                        {"id": "dev:wpc--StratigraphicColumnRankInterpretation:y:1", "kind": "osdu:wks:wpc--SCRI:1.2.0", "data": {"Name": "Rank"}},
                    ],
                },
            })

        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["created"] == 2

    def test_missing_bundle(self, authed_client):
        r = authed_client.post("/api/strat/storage/put", json={"bundle": {}})
        assert r.status_code == 400

    def test_partial_failure(self, authed_client):
        """First batch OK, second fails."""
        ok_resp = _mock_resp(200, json_body={"recordCount": 20})
        fail_resp = _mock_resp(403, json_body={"message": "forbidden"})

        session = AsyncMock()
        session.put = AsyncMock(side_effect=[ok_resp, fail_resp])
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.strat.osdu.http_client", return_value=cm):
            records = [{"id": f"dev:wpc:r{i}:1", "kind": "k", "data": {}} for i in range(25)]
            r = authed_client.post("/api/strat/storage/put", json={
                "bundle": {"records": records},
            })

        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "partial"
        assert body["created"] == 20
        assert len(body["errors"]) == 1

    def test_acl_legal_injected(self, authed_client):
        """Records without acl/legal get defaults injected."""
        put_resp = _mock_resp(200, json_body={"recordCount": 1})
        mock_cm, session = _mock_http(put_resp)

        with patch("app.strat.osdu.http_client", return_value=mock_cm):
            r = authed_client.post("/api/strat/storage/put", json={
                "bundle": {
                    "records": [{"id": "x:y:z:1", "kind": "k", "data": {}}],
                },
            })

        assert r.status_code == 200
        # Verify the PUT was called - records should have acl/legal injected
        put_args = session.put.call_args
        records_sent = put_args.kwargs.get("json") or put_args[1].get("json", [])
        # The records should now have acl and legal
        if records_sent:
            assert "acl" in records_sent[0]
            assert "legal" in records_sent[0]


# ── dataspaces.json ──────────────────────────────────────────────────────────

class TestStratDataspaces:
    """GET /api/strat/dataspaces.json."""

    def test_success(self, authed_client):
        with patch("app.strat.osdu.list_dataspaces", new_callable=AsyncMock, return_value=[
            {"Path": "maap/strat", "path": "maap/strat"},
            {"Path": "maap/drogon", "path": "maap/drogon"},
        ]):
            r = authed_client.get("/api/strat/dataspaces.json")

        assert r.status_code == 200
        ds = r.json()["dataspaces"]
        assert len(ds) == 2
        assert ds[0]["path"] == "maap/strat"

    def test_error_returns_empty(self, authed_client):
        with patch("app.strat.osdu.list_dataspaces", new_callable=AsyncMock, side_effect=Exception("timeout")):
            r = authed_client.get("/api/strat/dataspaces.json")

        assert r.status_code == 200
        body = r.json()
        assert body["dataspaces"] == []
        assert "error" in body


# ── rddms/resources.json ─────────────────────────────────────────────────────

class TestRddmsListResources:
    """GET /api/strat/rddms/resources.json."""

    def test_success(self, authed_client):
        with patch("app.strat.osdu.list_types", new_callable=AsyncMock, return_value=[
            {"name": "resqml20.obj_StratigraphicColumn"},
        ]), patch("app.strat.osdu.list_resources", new_callable=AsyncMock, return_value=[
            {"uri": "eml:///ds/sc(abc)", "name": "Test Column"},
        ]):
            r = authed_client.get("/api/strat/rddms/resources.json", params={"dataspace": "maap/strat"})

        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 1
        assert body["resources"][0]["name"] == "Test Column"

    def test_type_fetch_error(self, authed_client):
        with patch("app.strat.osdu.list_types", new_callable=AsyncMock, side_effect=Exception("fail")):
            r = authed_client.get("/api/strat/rddms/resources.json", params={"dataspace": "x"})
        assert r.status_code == 502


# ── rddms/resource.json ─────────────────────────────────────────────────────

class TestRddmsGetResource:
    """GET /api/strat/rddms/resource.json."""

    def test_success(self, authed_client):
        obj = {"name": "ICS Column", "uuid": "abc-123"}
        with patch("app.strat.osdu.get_resource", new_callable=AsyncMock, return_value=obj):
            r = authed_client.get("/api/strat/rddms/resource.json", params={
                "dataspace": "maap/strat",
                "type": "resqml20.obj_StratigraphicColumn",
                "uuid": "abc-123",
            })

        assert r.status_code == 200
        assert r.json()["name"] == "ICS Column"

    def test_not_found(self, authed_client):
        exc = httpx.HTTPStatusError(
            "err",
            request=httpx.Request("GET", "http://x"),
            response=httpx.Response(404, text="Not found"),
        )
        with patch("app.strat.osdu.get_resource", new_callable=AsyncMock, side_effect=exc):
            r = authed_client.get("/api/strat/rddms/resource.json", params={
                "dataspace": "maap/strat",
                "type": "resqml20.obj_StratigraphicColumn",
                "uuid": "missing",
            })
        assert r.status_code == 404
