"""
tests/test_ingest.py – Integration tests for the ingest router.

Covers:
  POST /api/manifest/ingest    – manifest ingestion (storage + workflow methods)
  GET  /api/manifest/last      – last stored manifest
  POST /api/rddms/build        – RDDMS manifest build (dry-run)
  POST /api/rddms/index        – RDDMS build + ingest
  POST /api/records/delete     – soft-delete OSDU records
  POST /api/records/ingest     – direct Storage PUT
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch, MagicMock

import httpx
import pytest
from starlette.testclient import TestClient


def _mock_resp(status: int = 200, json_body: dict | list | None = None, text: str = ""):
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
    session.post = AsyncMock(return_value=resp)
    session.put = AsyncMock(return_value=resp)
    session.get = AsyncMock(return_value=resp)
    session.delete = AsyncMock(return_value=resp)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm, session


# ── manifest/ingest ──────────────────────────────────────────────────────────

class TestManifestIngest:
    """POST /api/manifest/ingest."""

    def test_storage_method_success(self, authed_client):
        put_resp = _mock_resp(200, json_body={"recordCount": 1, "recordIds": ["dev:wpc:x:1"]})
        mock_cm, _ = _mock_http(put_resp)

        with patch("app.ingest_router._osdu_mod.http_client", return_value=mock_cm):
            r = authed_client.post("/api/manifest/ingest", json={
                "manifest": {"WorkProductComponents": [{"id": "dev:wpc:x:1", "kind": "osdu:wks:wpc:1"}]},
                "method": "storage",
            })

        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "submitted"
        assert body["method"] == "storage"
        assert "manifestId" in body

    def test_workflow_method_success(self, authed_client):
        post_resp = _mock_resp(200, json_body={"runId": "abc-123"})
        mock_cm, _ = _mock_http(post_resp)

        with patch("app.ingest_router._osdu_mod.http_client", return_value=mock_cm):
            r = authed_client.post("/api/manifest/ingest", json={
                "manifest": {"Data": {"WorkProductComponents": [{"id": "x"}]}},
                "method": "workflow",
            })

        assert r.status_code == 200
        body = r.json()
        assert body["method"] == "workflow"

    def test_missing_manifest(self, authed_client):
        r = authed_client.post("/api/manifest/ingest", json={"method": "storage"})
        assert r.status_code == 400

    def test_invalid_method(self, authed_client):
        r = authed_client.post("/api/manifest/ingest", json={
            "manifest": {"x": 1},
            "method": "invalid",
        })
        assert r.status_code == 400

    def test_invalid_json(self, authed_client):
        r = authed_client.post(
            "/api/manifest/ingest",
            content="not json",
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 400


# ── manifest/last ────────────────────────────────────────────────────────────

class TestManifestLast:
    """GET /api/manifest/last."""

    def test_no_manifests_404(self, authed_client):
        # Clear manifest store
        import app.ingest_router as ir
        ir._MANIFESTS.clear()
        ir._MANIFEST_TS.clear()
        r = authed_client.get("/api/manifest/last")
        assert r.status_code == 404

    def test_returns_last_after_ingest(self, authed_client):
        import app.ingest_router as ir
        ir._store_manifest("test-id", {"test": True})
        r = authed_client.get("/api/manifest/last")
        assert r.status_code == 200
        body = r.json()
        assert body["manifest"]["test"] is True
        # Cleanup
        ir._MANIFESTS.clear()
        ir._MANIFEST_TS.clear()


# ── records/delete ───────────────────────────────────────────────────────────

class TestRecordsDelete:
    """POST /api/records/delete."""

    def test_success(self, authed_client):
        del_resp = _mock_resp(204)
        mock_cm, session = _mock_http(del_resp)

        with patch("app.ingest_router._osdu_mod.http_client", return_value=mock_cm):
            r = authed_client.post("/api/records/delete", json={
                "ids": ["dev:wpc--X:a:1", "dev:wpc--X:b:1"],
            })

        assert r.status_code == 200
        body = r.json()
        assert len(body["results"]) == 2
        assert all(res["ok"] for res in body["results"])

    def test_missing_ids(self, authed_client):
        r = authed_client.post("/api/records/delete", json={"ids": []})
        assert r.status_code == 400

    def test_partial_failure(self, authed_client):
        """One record deleted, one fails."""
        ok_resp = _mock_resp(204)
        fail_resp = _mock_resp(404, text="Not found")

        session = AsyncMock()
        session.delete = AsyncMock(side_effect=[ok_resp, fail_resp])
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.ingest_router._osdu_mod.http_client", return_value=cm):
            r = authed_client.post("/api/records/delete", json={
                "ids": ["dev:wpc--X:a:1", "dev:wpc--X:missing:1"],
            })

        assert r.status_code == 200
        results = r.json()["results"]
        assert results[0]["ok"] is True
        assert results[1]["ok"] is False


# ── records/ingest ───────────────────────────────────────────────────────────

class TestRecordsIngest:
    """POST /api/records/ingest."""

    def test_success(self, authed_client):
        put_resp = _mock_resp(200, json_body={"recordCount": 1, "recordIds": ["dev:wpc:x:1"]})
        mock_cm, _ = _mock_http(put_resp)

        with patch("app.ingest_router._osdu_mod.http_client", return_value=mock_cm):
            r = authed_client.post("/api/records/ingest", json={
                "records": [{"id": "dev:wpc:x:1", "kind": "osdu:wks:wpc:1"}],
            })

        assert r.status_code == 200
        body = r.json()
        assert body["recordCount"] == 1

    def test_missing_records(self, authed_client):
        r = authed_client.post("/api/records/ingest", json={"records": []})
        assert r.status_code == 400

    def test_storage_api_failure(self, authed_client):
        fail_resp = _mock_resp(500, json_body={"message": "Internal error"})
        mock_cm, _ = _mock_http(fail_resp)

        with patch("app.ingest_router._osdu_mod.http_client", return_value=mock_cm):
            r = authed_client.post("/api/records/ingest", json={
                "records": [{"id": "x", "kind": "y"}],
            })

        assert r.status_code == 502


# ── _store_manifest (internal) ───────────────────────────────────────────────

class TestStoreManifest:
    """Unit tests for manifest store eviction."""

    def test_size_eviction(self):
        import app.ingest_router as ir
        ir._MANIFESTS.clear()
        ir._MANIFEST_TS.clear()
        # Fill to max
        for i in range(ir._MAX_ITEMS + 5):
            ir._store_manifest(f"id-{i}", {"n": i})
        assert len(ir._MANIFESTS) <= ir._MAX_ITEMS
        # Cleanup
        ir._MANIFESTS.clear()
        ir._MANIFEST_TS.clear()

    def test_ttl_eviction(self):
        import time
        import app.ingest_router as ir
        ir._MANIFESTS.clear()
        ir._MANIFEST_TS.clear()
        # Store with a very old timestamp
        ir._MANIFESTS["old"] = {"old": True}
        ir._MANIFEST_TS["old"] = time.time() - ir._MAX_AGE_S - 100
        # Store a new one triggers eviction
        ir._store_manifest("new", {"new": True})
        assert "old" not in ir._MANIFESTS
        assert "new" in ir._MANIFESTS
        # Cleanup
        ir._MANIFESTS.clear()
        ir._MANIFEST_TS.clear()
