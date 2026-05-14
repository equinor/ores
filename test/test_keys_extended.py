"""
tests/test_keys_extended.py – Extended tests for keys_router routes not covered
by test_routes.py.

Covers:
  GET  /keys/object.json        – single object detail (PG→REST fallback)
  GET  /keys/objects.json       – aggregated object list
  POST /dataspaces/delete       – dataspace deletion
  POST /dataspaces/lock         – dataspace lock
  POST /dataspaces/unlock       – dataspace unlock
  POST /dataspaces/manifest     – build OSDU manifest from dataspace
  Internal helpers              – _sanitize_type, _sanitize_uuid, _infer_type_path
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch, MagicMock

import httpx
import pytest
from starlette.testclient import TestClient


def _mock_resp(status: int = 200, json_body=None, text: str = ""):
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


# ── object.json ──────────────────────────────────────────────────────────────

class TestKeysObjectJson:
    """GET /keys/object.json – single object detail."""

    def test_rest_fallback(self, authed_client):
        """When PG is unavailable, falls back to REST."""
        obj_data = {
            "Citation": {"Title": "TestSurface"},
            "uri": "eml:///dataspace('demo')/resqml20.obj_Grid2dRepresentation('abc-123')",
        }

        with patch("app.keys_router.resqml_viz.pg_get_object_and_arrays", new_callable=AsyncMock, return_value=(None, None)), \
             patch("app.keys_router.osdu.get_resource", new_callable=AsyncMock, return_value=obj_data), \
             patch("app.keys_router.osdu.list_arrays", new_callable=AsyncMock, return_value=[{"name": "zvalues", "count": 100}]), \
             patch("app.keys_router.extract_metadata_generic", return_value={"pairs": [{"name": "Title", "value": "TestSurface"}]}):

            r = authed_client.get("/keys/object.json", params={
                "ds": "demo",
                "typ": "resqml20.obj_Grid2dRepresentation",
                "uuid": "abc-123",
            })

        assert r.status_code == 200
        body = r.json()
        assert body["primary"]["uuid"] == "abc-123"
        assert body["primary"]["title"] == "TestSurface"
        assert len(body["arrays"]) == 1

    def test_pg_path(self, authed_client):
        """When PG has data, uses PG directly."""
        obj_data = {"Citation": {"Title": "PG Surface"}}
        arr_data = [{"name": "zvalues"}]

        async def mock_pg_get(pool, ds, typ, uuid):
            return obj_data, arr_data

        with patch("app.keys_router.resqml_viz.pg_get_object_and_arrays", new_callable=AsyncMock, side_effect=mock_pg_get), \
             patch("app.keys_router.extract_metadata_generic", return_value={"pairs": []}):

            r = authed_client.get("/keys/object.json", params={
                "ds": "demo", "typ": "resqml20.obj_Grid2dRepresentation", "uuid": "abc",
            })

        assert r.status_code == 200
        body = r.json()
        assert body["primary"]["title"] == "PG Surface"

    def test_http_error(self, authed_client):
        """HTTPStatusError from REST returns structured error."""
        exc = httpx.HTTPStatusError(
            "err",
            request=httpx.Request("GET", "http://x"),
            response=httpx.Response(404, text='{"message": "object not found"}'),
        )

        with patch("app.keys_router.resqml_viz.pg_get_object_and_arrays", new_callable=AsyncMock, return_value=(None, None)), \
             patch("app.keys_router.osdu.get_resource", new_callable=AsyncMock, side_effect=exc):

            r = authed_client.get("/keys/object.json", params={
                "ds": "demo", "typ": "whatever", "uuid": "missing",
            })

        assert r.status_code == 404


# ── objects.json ─────────────────────────────────────────────────────────────

class TestKeysObjectsJson:
    """GET /keys/objects.json – aggregated object list."""

    def test_with_type(self, authed_client):
        """List objects for a specific type."""
        with patch("app.keys_router.osdu.list_resources", new_callable=AsyncMock, return_value=[
            {"Uuid": "a1", "Citation": {"Title": "Obj A"}},
            {"Uuid": "b2", "Citation": {"Title": "Obj B"}},
        ]):
            r = authed_client.get("/keys/objects.json", params={
                "ds": "demo",
                "typ": "resqml20.obj_Grid2dRepresentation",
            })

        assert r.status_code == 200
        body = r.json()
        assert len(body["items"]) == 2

    def test_without_type_aggregates(self, authed_client):
        """When no type, aggregates across all types."""
        with patch("app.keys_router.osdu.list_all_resources", new_callable=AsyncMock, return_value=[
            {"Uuid": "a1", "$type": "resqml20.obj_Grid2dRepresentation", "Citation": {"Title": "A"}},
            {"Uuid": "b2", "$type": "resqml20.obj_IjkGridRepresentation", "Citation": {"Title": "B"}},
        ]):
            r = authed_client.get("/keys/objects.json", params={"ds": "demo"})

        assert r.status_code == 200
        body = r.json()
        assert len(body["items"]) >= 2


# ── dataspaces/delete ────────────────────────────────────────────────────────

class TestDataspacesDelete:
    """POST /dataspaces/delete."""

    def test_success(self, authed_client):
        with patch("app.keys_router.osdu.delete_dataspace", new_callable=AsyncMock), \
             patch("app.keys_router.cache_invalidate", create=True):
            r = authed_client.post("/dataspaces/delete", data={"path": "demo/test"})
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_http_error(self, authed_client):
        exc = httpx.HTTPStatusError(
            "err",
            request=httpx.Request("DELETE", "http://x"),
            response=httpx.Response(403, text='{"message": "forbidden"}'),
        )
        with patch("app.keys_router.osdu.delete_dataspace", new_callable=AsyncMock, side_effect=exc):
            r = authed_client.post("/dataspaces/delete", data={"path": "demo/test"})
        assert r.status_code == 403


# ── dataspaces/lock & unlock ─────────────────────────────────────────────────

class TestDataspacesLockUnlock:
    """POST /dataspaces/lock and /dataspaces/unlock."""

    def test_lock_success(self, authed_client):
        with patch("app.keys_router.osdu.lock_dataspace", new_callable=AsyncMock):
            r = authed_client.post("/dataspaces/lock", data={"path": "demo/test"})
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_unlock_success(self, authed_client):
        with patch("app.keys_router.osdu.unlock_dataspace", new_callable=AsyncMock):
            r = authed_client.post("/dataspaces/unlock", data={"path": "demo/test"})
        assert r.status_code == 200

    def test_lock_error(self, authed_client):
        exc = httpx.HTTPStatusError(
            "err", request=httpx.Request("POST", "http://x"),
            response=httpx.Response(409, text='{"message": "already locked"}'),
        )
        with patch("app.keys_router.osdu.lock_dataspace", new_callable=AsyncMock, side_effect=exc):
            r = authed_client.post("/dataspaces/lock", data={"path": "demo/test"})
        assert r.status_code == 409


# ── dataspaces/manifest ──────────────────────────────────────────────────────

class TestDataspacesManifest:
    """POST /dataspaces/manifest – build OSDU manifest."""

    def test_success(self, authed_client):
        manifest = {"kind": "osdu:wks:Manifest:1.0.0", "WorkProductComponents": []}
        with patch("app.keys_router.osdu.build_manifest", new_callable=AsyncMock, return_value=manifest):
            r = authed_client.post("/dataspaces/manifest", data={"path": "demo/test"})
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert "manifest" in body

    def test_error(self, authed_client):
        exc = httpx.HTTPStatusError(
            "err", request=httpx.Request("POST", "http://x"),
            response=httpx.Response(500, text='{"message": "build failed"}'),
        )
        with patch("app.keys_router.osdu.build_manifest", new_callable=AsyncMock, side_effect=exc):
            r = authed_client.post("/dataspaces/manifest", data={"path": "demo/test"})
        assert r.status_code == 500


# ── Internal helpers ─────────────────────────────────────────────────────────

class TestHelpers:
    """Unit tests for _sanitize_type, _sanitize_uuid, _infer_type_path."""

    def test_sanitize_type_noop(self):
        from app.keys_router import _sanitize_type
        assert _sanitize_type("resqml20.obj_Grid2dRepresentation") == "resqml20.obj_Grid2dRepresentation"

    def test_sanitize_type_with_uuid(self):
        from app.keys_router import _sanitize_type
        assert _sanitize_type("resqml20.obj_Grid2dRepresentation(abc-123)") == "resqml20.obj_Grid2dRepresentation"

    def test_sanitize_type_empty(self):
        from app.keys_router import _sanitize_type
        assert _sanitize_type("") == ""

    def test_sanitize_uuid_strips_quotes(self):
        from app.keys_router import _sanitize_uuid
        # Standard quoted UUID
        assert _sanitize_uuid('"abc-123"') == "abc-123"
        # Trailing paren stripped
        assert _sanitize_uuid("abc-123)") == "abc-123"
        # RDDMS-style UUID with outer wrapping
        assert _sanitize_uuid("'abc-123'") == "abc-123"

    def test_sanitize_uuid_empty(self):
        from app.keys_router import _sanitize_uuid
        assert _sanitize_uuid("") == ""

    def test_infer_type_from_dollar_type(self):
        from app.keys_router import _infer_type_path
        item = {"$type": "resqml20.obj_IjkGridRepresentation"}
        assert _infer_type_path(item) == "resqml20.obj_IjkGridRepresentation"

    def test_infer_type_from_content_type(self):
        from app.keys_router import _infer_type_path
        item = {"contentType": "application/x-resqml+xml;version=2.0;type=obj_LocalDepth3dCrs"}
        assert _infer_type_path(item) == "resqml20.obj_LocalDepth3dCrs"

    def test_infer_type_from_uri(self):
        from app.keys_router import _infer_type_path
        item = {"uri": "eml:///dataspace('demo')/resqml20.obj_Grid2dRepresentation(abc)"}
        assert _infer_type_path(item) == "resqml20.obj_Grid2dRepresentation"

    def test_infer_type_empty(self):
        from app.keys_router import _infer_type_path
        assert _infer_type_path({}) == ""
