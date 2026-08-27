"""
Tests for demo/_auth.py - the centralised auth & env helper for all demo scripts.

Covers:
  - k8s YAML loading (configmap + secret)
  - .env file parsing
  - Instance resolution chain (k8s → env → .env)
  - Token minting (mock httpx.post)
  - Backward-compatible load_env() and mint_from_env()
  - get_token() caching
"""
from __future__ import annotations

import os
import sys
import textwrap
import time
from pathlib import Path
from typing import Dict
from unittest.mock import MagicMock, patch

import pytest

# ── Import the module under test ────────────────────────────────────────
DEMO_DIR = Path(__file__).resolve().parent.parent / "demo"
sys.path.insert(0, str(DEMO_DIR))
import _auth  # noqa: E402


# ════════════════════════════════════════════════════════════════════════
# Fixtures
# ════════════════════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def _clear_cache():
    """Clear the token cache between tests."""
    _auth._token_cache.clear()
    yield
    _auth._token_cache.clear()


@pytest.fixture
def k8s_dir(tmp_path: Path) -> Path:
    """Create a minimal k8s dir with configmap + secret."""
    cm = tmp_path / "configmap.yaml"
    cm.write_text(textwrap.dedent("""\
        apiVersion: v1
        kind: ConfigMap
        metadata:
          name: ores-config
        data:
          INSTANCE_EQNDEV_TENANT_ID: "aaa-bbb-ccc"
          INSTANCE_EQNDEV_CLIENT_ID: "cli-111"
          INSTANCE_EQNDEV_HOSTNAME: "swedev.energy.azure.com"
          INSTANCE_EQNDEV_DATA_PARTITION_ID: "dev"
          INSTANCE_EQNDEV_SCOPE: "cli-111/.default openid"
          INSTANCE_PRESHIP_TENANT_ID: "ddd-eee-fff"
          INSTANCE_PRESHIP_CLIENT_ID: "cli-222"
          INSTANCE_PRESHIP_HOSTNAME: "preship.energy.azure.com"
          INSTANCE_PRESHIP_DATA_PARTITION_ID: "opendes"
    """))
    sec = tmp_path / "secret.yaml"
    sec.write_text(textwrap.dedent("""\
        apiVersion: v1
        kind: Secret
        metadata:
          name: ores-secret
        stringData:
          INSTANCE_EQNDEV_REFRESH_TOKEN: "rt-swedev-123"
          INSTANCE_PRESHIP_CLIENT_SECRET: "cs-preship-456"
    """))
    return tmp_path


@pytest.fixture
def env_file(tmp_path: Path) -> Path:
    """Create a legacy .env file."""
    f = tmp_path / ".env"
    f.write_text(textwrap.dedent("""\
        OSDU_TENANT_ID=tenant-from-env
        OSDU_CLIENT_ID=client-from-env
        OSDU_SCOPE=scope-from-env
        OSDU_HOST=envhost.energy.azure.com
        OSDU_PARTITION=envpart
        refresh_token=rt-from-env
    """))
    return f


def _mock_httpx_success(url, *, data=None, timeout=None) -> MagicMock:
    """Mock httpx.post that returns a valid token response."""
    resp = MagicMock()
    resp.is_success = True
    resp.json.return_value = {
        "access_token": "mock-at-12345",
        "expires_in": 3600,
        "token_type": "Bearer",
    }
    return resp


def _mock_httpx_fail(url, *, data=None, timeout=None) -> MagicMock:
    """Mock httpx.post that returns a 400 error."""
    resp = MagicMock()
    resp.is_success = False
    resp.status_code = 400
    resp.text = "invalid_grant: token expired"
    return resp


# ════════════════════════════════════════════════════════════════════════
# k8s YAML loading
# ════════════════════════════════════════════════════════════════════════

class TestK8sYamlLoading:
    def test_load_configmap(self, k8s_dir: Path):
        env = _auth._load_k8s_yaml(k8s_dir / "configmap.yaml")
        assert env["INSTANCE_EQNDEV_TENANT_ID"] == "aaa-bbb-ccc"
        assert env["INSTANCE_EQNDEV_CLIENT_ID"] == "cli-111"

    def test_load_secret(self, k8s_dir: Path):
        env = _auth._load_k8s_yaml(k8s_dir / "secret.yaml")
        assert env["INSTANCE_EQNDEV_REFRESH_TOKEN"] == "rt-swedev-123"

    def test_load_missing_file(self, tmp_path: Path):
        assert _auth._load_k8s_yaml(tmp_path / "nope.yaml") == {}

    def test_load_k8s_env_merges(self, k8s_dir: Path):
        env = _auth.load_k8s_env(k8s_dir)
        assert env["INSTANCE_EQNDEV_TENANT_ID"] == "aaa-bbb-ccc"
        assert env["INSTANCE_EQNDEV_REFRESH_TOKEN"] == "rt-swedev-123"
        assert env["INSTANCE_PRESHIP_CLIENT_SECRET"] == "cs-preship-456"


# ════════════════════════════════════════════════════════════════════════
# .env parsing
# ════════════════════════════════════════════════════════════════════════

class TestDotenvParsing:
    def test_parse_basic(self, env_file: Path):
        vals = _auth.parse_dotenv(env_file)
        assert vals["OSDU_TENANT_ID"] == "tenant-from-env"
        assert vals["refresh_token"] == "rt-from-env"

    def test_parse_quotes(self, tmp_path: Path):
        f = tmp_path / ".env"
        f.write_text('FOO="bar baz"\nSINGLE=\'one two\'\n')
        vals = _auth.parse_dotenv(f)
        assert vals["FOO"] == "bar baz"
        assert vals["SINGLE"] == "one two"

    def test_parse_comments_and_blanks(self, tmp_path: Path):
        f = tmp_path / ".env"
        f.write_text("# comment\n\nKEY=val\n  # another\n")
        vals = _auth.parse_dotenv(f)
        assert vals == {"KEY": "val"}

    def test_parse_missing_file(self, tmp_path: Path):
        assert _auth.parse_dotenv(tmp_path / "nope") == {}


# ════════════════════════════════════════════════════════════════════════
# Instance resolution
# ════════════════════════════════════════════════════════════════════════

class TestInstanceResolution:
    def test_resolve_from_k8s(self, k8s_dir: Path):
        inst = _auth.load_instance("interop", k8s_dir=k8s_dir)
        assert inst["name"] == "interop"
        assert inst["source"] == "k8s"
        assert inst["tenant"] == "aaa-bbb-ccc"
        assert inst["client_id"] == "cli-111"
        assert inst["refresh_token"] == "rt-swedev-123"
        assert inst["grant"] == "refresh_token"
        assert inst["host"] == "https://swedev.energy.azure.com"
        assert inst["partition"] == "dev"

    def test_resolve_preship_client_credentials(self, k8s_dir: Path):
        inst = _auth.load_instance("preship", k8s_dir=k8s_dir)
        assert inst["source"] == "k8s"
        assert inst["grant"] == "client_credentials"
        assert inst["client_secret"] == "cs-preship-456"

    def test_alias_swedev_resolves_to_interop(self, k8s_dir: Path):
        inst = _auth.load_instance("swedev", k8s_dir=k8s_dir)
        assert inst["name"] == "interop"

    def test_resolve_from_environ(self, tmp_path: Path):
        """Fall back to INSTANCE_* env vars when k8s dir is empty."""
        empty_k8s = tmp_path / "empty_k8s"
        empty_k8s.mkdir()
        env_vars = {
            "INSTANCE_MYINST_TENANT_ID": "t-env",
            "INSTANCE_MYINST_CLIENT_ID": "c-env",
            "INSTANCE_MYINST_HOSTNAME": "myinst.test",
            "INSTANCE_MYINST_DATA_PARTITION_ID": "part",
            "INSTANCE_MYINST_REFRESH_TOKEN": "rt-env",
            "INSTANCE_MYINST_SCOPE": "c-env/.default",
        }
        with patch.dict(os.environ, env_vars, clear=False):
            inst = _auth.load_instance("myinst", k8s_dir=empty_k8s)
        assert inst["source"] == "env"
        assert inst["tenant"] == "t-env"

    def test_resolve_from_dotenv(self, env_file: Path, tmp_path: Path):
        """Fall back to .env file when k8s and env are empty."""
        empty_k8s = tmp_path / "k8s_empty"
        empty_k8s.mkdir()
        with patch.dict(os.environ, {}, clear=True):
            # patch REPO_ROOT to point at tmp dir so .env is found
            with patch.object(_auth, "REPO_ROOT", env_file.parent):
                with patch.object(_auth, "K8S_DIR", empty_k8s):
                    inst = _auth.load_instance("interop", k8s_dir=empty_k8s)
        assert inst["source"] == "dotenv"
        assert inst["tenant"] == "tenant-from-env"

    def test_resolve_not_found_raises(self, tmp_path: Path):
        empty = tmp_path / "empty"
        empty.mkdir()
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(_auth, "REPO_ROOT", tmp_path):
                with patch.object(_auth, "K8S_DIR", empty):
                    with pytest.raises(SystemExit):
                        _auth.load_instance("nonexistent", k8s_dir=empty)


# ════════════════════════════════════════════════════════════════════════
# Token minting
# ════════════════════════════════════════════════════════════════════════

class TestTokenMinting:
    def test_get_token_from_k8s(self, k8s_dir: Path):
        with patch.object(_auth.httpx, "post", side_effect=_mock_httpx_success):
            token = _auth.get_token("swedev", k8s_dir=k8s_dir)
        assert token == "mock-at-12345"

    def test_get_token_caches(self, k8s_dir: Path):
        with patch.object(_auth.httpx, "post", side_effect=_mock_httpx_success) as mock:
            t1 = _auth.get_token("swedev", k8s_dir=k8s_dir)
            t2 = _auth.get_token("swedev", k8s_dir=k8s_dir)
        assert t1 == t2
        assert mock.call_count == 1  # only one HTTP call

    def test_get_token_auth_failure(self, k8s_dir: Path):
        with patch.object(_auth.httpx, "post", side_effect=_mock_httpx_fail):
            with pytest.raises(RuntimeError, match="Auth failed"):
                _auth.get_token("swedev", k8s_dir=k8s_dir)

    def test_mint_from_env_refresh_token(self):
        env = {
            "tenant": "t1",
            "client_id": "c1",
            "refresh_token": "rt1",
            "scope": "s1",
        }
        with patch.object(_auth.httpx, "post", side_effect=_mock_httpx_success):
            token = _auth.mint_from_env(env)
        assert token == "mock-at-12345"

    def test_mint_from_env_client_credentials(self):
        env = {
            "tenant": "t1",
            "client_id": "c1",
            "client_secret": "cs1",
            "scope": "s1",
        }
        with patch.object(_auth.httpx, "post", side_effect=_mock_httpx_success):
            token = _auth.mint_from_env(env)
        assert token == "mock-at-12345"

    def test_mint_from_env_no_creds_raises(self):
        env = {
            "tenant": "t1",
            "client_id": "c1",
            "scope": "s1",
        }
        with pytest.raises(RuntimeError, match="No usable credentials"):
            _auth.mint_from_env(env)


# ════════════════════════════════════════════════════════════════════════
# Backward-compatible load_env()
# ════════════════════════════════════════════════════════════════════════

class TestBackwardCompatLoadEnv:
    def test_load_env_with_instance_name(self, k8s_dir: Path):
        with patch.object(_auth, "K8S_DIR", k8s_dir):
            env = _auth.load_env(instance="swedev")
        assert env["tenant"] == "aaa-bbb-ccc"
        assert env["refresh_token"] == "rt-swedev-123"
        assert env["host"] == "https://swedev.energy.azure.com"

    def test_load_env_with_paths(self, env_file: Path, tmp_path: Path):
        empty_k8s = tmp_path / "k8s_empty"
        empty_k8s.mkdir()
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(_auth, "REPO_ROOT", env_file.parent):
                with patch.object(_auth, "K8S_DIR", empty_k8s):
                    env = _auth.load_env([str(env_file)])
        assert env["tenant"] == "tenant-from-env"
        assert env["host"] == "https://envhost.energy.azure.com"


# ════════════════════════════════════════════════════════════════════════
# Convenience functions
# ════════════════════════════════════════════════════════════════════════

class TestConvenience:
    def test_api_headers(self, k8s_dir: Path):
        with patch.object(_auth.httpx, "post", side_effect=_mock_httpx_success):
            h = _auth.api_headers("swedev", k8s_dir=k8s_dir)
        assert h["Authorization"] == "Bearer mock-at-12345"
        assert h["data-partition-id"] == "dev"
        assert h["Content-Type"] == "application/json"

    def test_base_url(self, k8s_dir: Path):
        url = _auth.base_url("interop", k8s_dir=k8s_dir)
        assert url == "https://swedev.energy.azure.com"
