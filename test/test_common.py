"""
tests/test_common.py – Unit tests for app.common helpers.

Covers:
  - sanitize_upstream_error()  – JSON, HTML, plain-text, empty bodies
  - safe_error_detail()         – HTTPStatusError, generic exceptions
  - http_error_response()       – standard JSON error wrapper
  - friendly_value / friendly_list – human-readable formatting
  - normalize_obj               – RDDMS list-unwrapping
  - pretty_val                  – Jinja filter
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


# ─── sanitize_upstream_error ─────────────────────────────────────────────────

class TestSanitizeUpstreamError:
    """Test sanitize_upstream_error() with various response shapes."""

    def _resp(self, text: str, status: int = 400, reason: str = "Bad Request"):
        """Build a minimal response-like object."""
        r = SimpleNamespace()
        r.text = text
        r.status_code = status
        r.reason_phrase = reason
        return r

    def test_json_message_field(self):
        from app.common import sanitize_upstream_error
        body = json.dumps({"message": "Something went wrong"})
        assert sanitize_upstream_error(self._resp(body)) == "Something went wrong"

    def test_json_detail_field(self):
        from app.common import sanitize_upstream_error
        body = json.dumps({"detail": "Not found"})
        assert sanitize_upstream_error(self._resp(body)) == "Not found"

    def test_json_error_field(self):
        from app.common import sanitize_upstream_error
        body = json.dumps({"error": "unauthorized"})
        assert sanitize_upstream_error(self._resp(body)) == "unauthorized"

    def test_json_reason_field(self):
        from app.common import sanitize_upstream_error
        body = json.dumps({"reason": "rate limited"})
        assert sanitize_upstream_error(self._resp(body)) == "rate limited"

    def test_json_nested_message(self):
        from app.common import sanitize_upstream_error
        body = json.dumps({"message": {"message": "deep error"}})
        assert sanitize_upstream_error(self._resp(body)) == "deep error"

    def test_json_nested_detail(self):
        from app.common import sanitize_upstream_error
        body = json.dumps({"message": {"detail": "deep detail"}})
        assert sanitize_upstream_error(self._resp(body)) == "deep detail"

    def test_json_no_known_fields(self):
        """JSON without message/detail/error/reason → falls through to plain text."""
        from app.common import sanitize_upstream_error
        body = json.dumps({"unknown_field": "value"})
        result = sanitize_upstream_error(self._resp(body))
        # Falls through JSON block to plain-text fallback
        assert "unknown_field" in result

    def test_json_message_capped_at_500(self):
        from app.common import sanitize_upstream_error
        body = json.dumps({"message": "x" * 800})
        result = sanitize_upstream_error(self._resp(body))
        assert len(result) <= 500

    def test_html_body_rejected(self):
        from app.common import sanitize_upstream_error
        body = "<html><body><h1>502 Bad Gateway</h1></body></html>"
        result = sanitize_upstream_error(self._resp(body, 502, "Bad Gateway"))
        assert "502" in result
        assert "<html" not in result

    def test_doctype_html_body_rejected(self):
        from app.common import sanitize_upstream_error
        body = "<!DOCTYPE html>\n<html><body>error</body></html>"
        result = sanitize_upstream_error(self._resp(body, 500, "Internal Server Error"))
        assert "<html" not in result
        assert "500" in result

    def test_plain_text_body(self):
        from app.common import sanitize_upstream_error
        result = sanitize_upstream_error(self._resp("simple error text"))
        assert result == "simple error text"

    def test_plain_text_capped_at_300(self):
        from app.common import sanitize_upstream_error
        result = sanitize_upstream_error(self._resp("x" * 600))
        assert len(result) <= 300

    def test_empty_body_falls_back_to_status(self):
        from app.common import sanitize_upstream_error
        result = sanitize_upstream_error(self._resp("", 404, "Not Found"))
        assert "404" in result
        assert "Not Found" in result

    def test_whitespace_only_body(self):
        from app.common import sanitize_upstream_error
        result = sanitize_upstream_error(self._resp("   \n  ", 503, "Service Unavailable"))
        assert "503" in result


# ─── safe_error_detail ───────────────────────────────────────────────────────

class TestSafeErrorDetail:
    """Test safe_error_detail() for different exception types."""

    def test_generic_exception(self):
        from app.common import safe_error_detail
        result = safe_error_detail(ValueError("bad value"))
        assert result == "bad value"

    def test_generic_caps_at_300(self):
        from app.common import safe_error_detail
        result = safe_error_detail(RuntimeError("x" * 600))
        assert len(result) <= 300

    def test_generic_no_message(self):
        from app.common import safe_error_detail
        result = safe_error_detail(ValueError())
        assert result == "ValueError"

    def test_html_in_generic_exception(self):
        from app.common import safe_error_detail
        result = safe_error_detail(RuntimeError("<html>big error page</html>"))
        assert "<html" not in result
        assert result == "RuntimeError"

    def test_httpx_status_error(self):
        """HTTPStatusError delegates to sanitize_upstream_error."""
        import httpx
        from app.common import safe_error_detail

        resp = httpx.Response(502, text=json.dumps({"message": "upstream fail"}))
        resp.request = httpx.Request("GET", "http://example.com")
        exc = httpx.HTTPStatusError("err", request=resp.request, response=resp)
        result = safe_error_detail(exc)
        assert result == "upstream fail"


# ─── http_error_response ─────────────────────────────────────────────────────

class TestHttpErrorResponse:
    """Test http_error_response() builds correct JSONResponse."""

    def test_basic_error(self):
        import httpx
        from app.common import http_error_response

        resp = httpx.Response(
            403,
            text=json.dumps({"message": "forbidden"}),
            request=httpx.Request("GET", "http://example.com"),
        )
        exc = httpx.HTTPStatusError("err", request=resp.request, response=resp)
        jr = http_error_response(exc)
        assert jr.status_code == 403
        body = json.loads(jr.body)
        assert body["status"] == "error"
        assert body["code"] == 403
        assert body["detail"] == "forbidden"

    def test_error_with_html_body(self):
        import httpx
        from app.common import http_error_response

        resp = httpx.Response(
            502,
            text="<html><body>bad gateway</body></html>",
            request=httpx.Request("GET", "http://example.com"),
        )
        exc = httpx.HTTPStatusError("err", request=resp.request, response=resp)
        jr = http_error_response(exc)
        body = json.loads(jr.body)
        assert "<html" not in body["detail"]
        assert body["code"] == 502


# ─── friendly_value / friendly_list ──────────────────────────────────────────

class TestFriendlyValue:
    """Test friendly_value / friendly_list formatting helpers."""

    def test_none(self):
        from app.common import friendly_value
        assert friendly_value(None) == ""

    def test_string(self):
        from app.common import friendly_value
        assert friendly_value("hello") == "hello"

    def test_string_truncated(self):
        from app.common import friendly_value
        result = friendly_value("x" * 500)
        assert len(result) <= 401  # 400 + "…"
        assert result.endswith("…")

    def test_int_float_bool(self):
        from app.common import friendly_value
        assert friendly_value(42) == "42"
        assert friendly_value(3.14) == "3.14"
        assert friendly_value(True) == "True"

    def test_dict(self):
        from app.common import friendly_value
        result = friendly_value({"a": 1, "b": "two"})
        assert "a: 1" in result
        assert "b: two" in result

    def test_simple_list(self):
        from app.common import friendly_value
        result = friendly_value([1, 2, 3])
        assert result == "1, 2, 3"

    def test_list_of_dicts(self):
        from app.common import friendly_value
        result = friendly_value([{"x": 1}, {"y": 2}])
        assert "x: 1" in result
        assert "y: 2" in result

    def test_empty_list(self):
        from app.common import friendly_list
        assert friendly_list([]) == ""


# ─── normalize_obj ───────────────────────────────────────────────────────────

class TestNormalizeObj:
    """Test normalize_obj() list-unwrapping logic."""

    def test_dict_passthrough(self):
        from app.common import normalize_obj
        d = {"Uuid": "abc", "Name": "test"}
        assert normalize_obj(d, "abc") is d

    def test_list_exact_uuid_match(self):
        from app.common import normalize_obj
        items = [
            {"Uuid": "111", "Name": "first"},
            {"Uuid": "222", "Name": "second"},
        ]
        result = normalize_obj(items, "222")
        assert result["Name"] == "second"

    def test_list_case_insensitive_uuid(self):
        from app.common import normalize_obj
        items = [{"UUID": "AAA-BBB", "Name": "match"}]
        result = normalize_obj(items, "aaa-bbb")
        assert result["Name"] == "match"

    def test_list_fallback_first_dict(self):
        from app.common import normalize_obj
        items = [{"Uuid": "xxx", "Name": "fallback"}]
        result = normalize_obj(items, "not-found")
        assert result["Name"] == "fallback"

    def test_list_no_dicts(self):
        from app.common import normalize_obj
        assert normalize_obj(["a", "b"], "a") == {}

    def test_empty_list(self):
        from app.common import normalize_obj
        assert normalize_obj([], "anything") == {}

    def test_non_dict_non_list(self):
        from app.common import normalize_obj
        assert normalize_obj("scalar", "x") == {}


# ─── pretty_val ──────────────────────────────────────────────────────────────

class TestPrettyVal:
    """Test pretty_val Jinja filter."""

    def test_none(self):
        from app.common import pretty_val
        assert pretty_val(None) == "-"

    def test_plain_string(self):
        from app.common import pretty_val
        assert pretty_val("hello") == "hello"

    def test_json_dict_string(self):
        from app.common import pretty_val
        result = pretty_val('{"a": 1, "b": 2}')
        assert "a: 1" in result

    def test_json_list_string(self):
        from app.common import pretty_val
        result = pretty_val('[1, 2, 3]')
        assert "1, 2, 3" in result

    def test_invalid_json(self):
        from app.common import pretty_val
        assert pretty_val("{broken json") == "{broken json"
