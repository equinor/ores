"""
tests/test_gettoken.py - Tests for demo/gettoken.py k8s secret loading.

Covers:
  • _load_k8s_yaml: parses both PyYAML and the minimal fallback parser
  • load_k8s_env: merges configmap + secret YAML
  • discover_k8s_instances: finds INSTANCE_<NAME>_* entries
  • _resolve_k8s_instance: builds a mint-ready config dict
  • mint_token: k8s → env → legacy fallback chain
  • list_instances: discovers from all three sources
  • CLI: --from-k8s, --list flags
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict
from unittest.mock import patch, MagicMock

import pytest


# ── Import the module under test ─────────────────────────────────────────

# demo/ isn't a package, so we add it to sys.path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "demo"))
import gettoken  # noqa: E402


# ── Fixtures: fake k8s YAML files ────────────────────────────────────────

FAKE_CONFIGMAP = """\
apiVersion: v1
kind: ConfigMap
metadata:
  name: ores-config
  namespace: ores
data:
  DEFAULT_INSTANCE: "interop"
  INSTANCE_EQNDEV_HOSTNAME: "admeinterop.energy.azure.com"
  INSTANCE_EQNDEV_DATA_PARTITION_ID: "dev"
  INSTANCE_EQNDEV_DEFAULT_LEGAL_TAG: "opendes-private-usa-default"
  INSTANCE_PRESHIP_HOSTNAME: "osdu-ship.msft-osdu-test.org"
  INSTANCE_PRESHIP_DATA_PARTITION_ID: "opendes"
"""

FAKE_SECRET = """\
apiVersion: v1
kind: Secret
metadata:
  name: ores-secrets
  namespace: ores
type: Opaque
stringData:
  SECRET_KEY: "test-secret-key"
  INSTANCE_EQNDEV_TENANT_ID: "fake-tenant-aaaa"
  INSTANCE_EQNDEV_CLIENT_ID: "fake-client-bbbb"
  INSTANCE_EQNDEV_SCOPE: "fake-scope/.default openid offline_access"
  INSTANCE_EQNDEV_REFRESH_TOKEN: "fake-rt-interop-12345"
  INSTANCE_PRESHIP_TENANT_ID: "fake-tenant-cccc"
  INSTANCE_PRESHIP_CLIENT_ID: "fake-client-dddd"
  INSTANCE_PRESHIP_CLIENT_SECRET: "fake-secret-eeee"
  INSTANCE_PRESHIP_SCOPE: "fake-client-dddd/.default"
"""


@pytest.fixture()
def k8s_dir(tmp_path: Path) -> Path:
    """Write fake configmap + secret YAML into a temp dir."""
    (tmp_path / "configmap.yaml").write_text(FAKE_CONFIGMAP)
    (tmp_path / "secret.yaml").write_text(FAKE_SECRET)
    return tmp_path


@pytest.fixture()
def k8s_env(k8s_dir: Path) -> Dict[str, str]:
    """Pre-loaded k8s env dict from the fake YAML files."""
    return gettoken.load_k8s_env(k8s_dir)


# ── YAML loading ─────────────────────────────────────────────────────────

class TestLoadK8sYaml:

    def test_load_configmap(self, k8s_dir):
        config = gettoken._load_k8s_yaml(k8s_dir / "configmap.yaml")
        assert config["DEFAULT_INSTANCE"] == "interop"
        assert config["INSTANCE_EQNDEV_HOSTNAME"] == "admeinterop.energy.azure.com"

    def test_load_secret(self, k8s_dir):
        secrets = gettoken._load_k8s_yaml(k8s_dir / "secret.yaml")
        assert secrets["SECRET_KEY"] == "test-secret-key"
        assert secrets["INSTANCE_EQNDEV_REFRESH_TOKEN"] == "fake-rt-interop-12345"
        assert secrets["INSTANCE_PRESHIP_CLIENT_SECRET"] == "fake-secret-eeee"

    def test_load_missing_file(self, tmp_path):
        result = gettoken._load_k8s_yaml(tmp_path / "nonexistent.yaml")
        assert result == {}

    def test_load_empty_file(self, tmp_path):
        (tmp_path / "empty.yaml").write_text("")
        result = gettoken._load_k8s_yaml(tmp_path / "empty.yaml")
        assert result == {}


class TestLoadK8sEnv:

    def test_merges_config_and_secret(self, k8s_dir):
        env = gettoken.load_k8s_env(k8s_dir)
        # From configmap
        assert env["INSTANCE_EQNDEV_HOSTNAME"] == "admeinterop.energy.azure.com"
        # From secret
        assert env["INSTANCE_EQNDEV_TENANT_ID"] == "fake-tenant-aaaa"
        assert env["INSTANCE_EQNDEV_REFRESH_TOKEN"] == "fake-rt-interop-12345"

    def test_secret_overrides_config(self, tmp_path):
        """When same key in both files, secret wins."""
        (tmp_path / "configmap.yaml").write_text(
            "data:\n  MY_KEY: from-config\n")
        (tmp_path / "secret.yaml").write_text(
            "stringData:\n  MY_KEY: from-secret\n")
        env = gettoken.load_k8s_env(tmp_path)
        assert env["MY_KEY"] == "from-secret"


# ── Instance discovery ────────────────────────────────────────────────────

class TestDiscoverInstances:

    def test_finds_two_instances(self, k8s_env):
        instances = gettoken.discover_k8s_instances(k8s_env)
        assert "interop" in instances
        assert "preship" in instances

    def test_interop_fields(self, k8s_env):
        instances = gettoken.discover_k8s_instances(k8s_env)
        interop = instances["interop"]
        assert interop["tenant_id"] == "fake-tenant-aaaa"
        assert interop["client_id"] == "fake-client-bbbb"
        assert interop["refresh_token"] == "fake-rt-interop-12345"
        assert interop["hostname"] == "admeinterop.energy.azure.com"

    def test_preship_fields(self, k8s_env):
        instances = gettoken.discover_k8s_instances(k8s_env)
        preship = instances["preship"]
        assert preship["tenant_id"] == "fake-tenant-cccc"
        assert preship["client_secret"] == "fake-secret-eeee"

    def test_no_instances_in_empty_env(self):
        assert gettoken.discover_k8s_instances({}) == {}


class TestResolveK8sInstance:

    def test_resolve_interop(self, k8s_env):
        resolved = gettoken._resolve_k8s_instance("interop", k8s_env)
        assert resolved is not None
        assert resolved["grant"] == "refresh_token"
        assert resolved["tenant_id"] == "fake-tenant-aaaa"
        assert resolved["refresh_token"] == "fake-rt-interop-12345"
        assert resolved["label"] == "k8s/interop"

    def test_resolve_preship(self, k8s_env):
        resolved = gettoken._resolve_k8s_instance("preship", k8s_env)
        assert resolved is not None
        assert resolved["grant"] == "client_credentials"
        assert resolved["client_secret"] == "fake-secret-eeee"

    def test_resolve_unknown(self, k8s_env):
        assert gettoken._resolve_k8s_instance("nonexistent", k8s_env) is None


# ── Token minting (mocked HTTP) ──────────────────────────────────────────

def _mock_httpx_post(status=200, access_token="fake-at-minted", expires_in=3600):
    """Return a patched httpx.post that returns a fake token response."""
    response = MagicMock()
    response.is_success = (status == 200)
    response.status_code = status
    response.text = json.dumps({"error": "mock error"})
    response.json.return_value = {
        "access_token": access_token,
        "expires_in": expires_in,
        "token_type": "Bearer",
    }
    return patch("gettoken.httpx.post", return_value=response)


class TestMintFromK8s:
    """Test minting with --from-k8s using fake YAML files."""

    def test_mint_interop_from_k8s(self, k8s_dir):
        with _mock_httpx_post(access_token="at-interop-k8s"):
            token = gettoken.mint_token("interop", from_k8s=True, k8s_dir=k8s_dir)
        assert token == "at-interop-k8s"

    def test_mint_preship_from_k8s(self, k8s_dir):
        with _mock_httpx_post(access_token="at-preship-k8s"):
            token = gettoken.mint_token("preship", from_k8s=True, k8s_dir=k8s_dir)
        assert token == "at-preship-k8s"

    def test_mint_alias_interop_as_swedev(self, k8s_dir):
        """'interop' is aliased to 'swedev' in legacy, but k8s uses 'interop' directly."""
        with _mock_httpx_post(access_token="at-alias"):
            token = gettoken.mint_token("interop", from_k8s=True, k8s_dir=k8s_dir)
        assert token == "at-alias"

    def test_mint_verbose(self, k8s_dir, capsys):
        with _mock_httpx_post(access_token="at-verbose"):
            gettoken.mint_token("interop", from_k8s=True, k8s_dir=k8s_dir, verbose=True)
        captured = capsys.readouterr()
        assert "k8s/interop" in captured.err
        assert "expires_in" in captured.err

    def test_mint_k8s_posts_correct_form(self, k8s_dir):
        """Verify the httpx.post is called with the right form data."""
        with _mock_httpx_post() as mock_post:
            gettoken.mint_token("interop", from_k8s=True, k8s_dir=k8s_dir)
        call_args = mock_post.call_args
        url = call_args[0][0]
        form = call_args[1]["data"]
        assert "fake-tenant-aaaa" in url
        assert form["grant_type"] == "refresh_token"
        assert form["client_id"] == "fake-client-bbbb"
        assert form["refresh_token"] == "fake-rt-interop-12345"

    def test_mint_preship_posts_client_credentials(self, k8s_dir):
        with _mock_httpx_post() as mock_post:
            gettoken.mint_token("preship", from_k8s=True, k8s_dir=k8s_dir)
        form = mock_post.call_args[1]["data"]
        assert form["grant_type"] == "client_credentials"
        assert form["client_secret"] == "fake-secret-eeee"

    def test_mint_k8s_not_found_falls_through(self, tmp_path):
        """If k8s dir has no matching instance, falls through to env/legacy.
        'swedev' exists in the hard-coded INSTANCES dict but needs
        SWEDEV_REFRESH_TOKEN - without it, mint_token exits."""
        (tmp_path / "configmap.yaml").write_text("data:\n  UNRELATED: value\n")
        (tmp_path / "secret.yaml").write_text("stringData:\n  ALSO_UNRELATED: value\n")
        # Ensure the legacy env var is NOT set
        env_clean = {k: v for k, v in os.environ.items()
                     if not k.startswith("INSTANCE_SWEDEV") and k != "SWEDEV_REFRESH_TOKEN"}
        with patch.dict(os.environ, env_clean, clear=True):
            with pytest.raises(SystemExit):
                gettoken.mint_token("swedev", from_k8s=True, k8s_dir=tmp_path)


class TestMintFromEnv:
    """Test minting via INSTANCE_<NAME>_* environment variables."""

    def test_mint_from_env_vars(self):
        env_vars = {
            "INSTANCE_MYINST_TENANT_ID": "env-tenant",
            "INSTANCE_MYINST_CLIENT_ID": "env-client",
            "INSTANCE_MYINST_SCOPE": "env-scope",
            "INSTANCE_MYINST_REFRESH_TOKEN": "env-rt-1234",
        }
        with patch.dict(os.environ, env_vars, clear=False):
            with _mock_httpx_post(access_token="at-from-env"):
                token = gettoken.mint_token("myinst")
        assert token == "at-from-env"

    def test_env_client_credentials(self):
        env_vars = {
            "INSTANCE_SVC_TENANT_ID": "env-tenant",
            "INSTANCE_SVC_CLIENT_ID": "env-client",
            "INSTANCE_SVC_CLIENT_SECRET": "env-secret",
            "INSTANCE_SVC_SCOPE": "env-scope",
        }
        with patch.dict(os.environ, env_vars, clear=False):
            with _mock_httpx_post(access_token="at-svc") as mock_post:
                token = gettoken.mint_token("svc")
        assert token == "at-svc"
        form = mock_post.call_args[1]["data"]
        assert form["grant_type"] == "client_credentials"


class TestMintFromConfig:

    def test_raises_on_no_tenant(self):
        with pytest.raises(RuntimeError, match="No tenant_id"):
            gettoken._mint_from_config({"tenant_id": "", "grant": "refresh_token"})

    def test_raises_on_missing_refresh_token(self):
        with pytest.raises(RuntimeError, match="no refresh_token"):
            gettoken._mint_from_config({
                "tenant_id": "t", "client_id": "c",
                "grant": "refresh_token", "refresh_token": "",
            })

    def test_raises_on_missing_client_secret(self):
        with pytest.raises(RuntimeError, match="missing client_id or client_secret"):
            gettoken._mint_from_config({
                "tenant_id": "t", "client_id": "",
                "grant": "client_credentials", "client_secret": "",
            })

    def test_raises_on_http_failure(self):
        bad_resp = MagicMock()
        bad_resp.is_success = False
        bad_resp.status_code = 401
        bad_resp.text = "Unauthorized"
        with patch("gettoken.httpx.post", return_value=bad_resp):
            with pytest.raises(RuntimeError, match="Auth failed"):
                gettoken._mint_from_config({
                    "tenant_id": "t", "client_id": "c",
                    "grant": "refresh_token", "refresh_token": "rt",
                    "scope": "s",
                })


# ── Instance listing ──────────────────────────────────────────────────────

class TestListInstances:

    def test_lists_builtin_instances(self):
        instances = gettoken.list_instances()
        names = [i["name"] for i in instances]
        assert "swedev" in names
        assert "preship" in names

    def test_lists_k8s_instances(self, k8s_dir):
        instances = gettoken.list_instances(k8s_dir)
        sources = {i["name"]: i["source"] for i in instances}
        # k8s should override builtin for overlapping names
        assert "interop" in sources
        assert sources["interop"] == "k8s"

    def test_k8s_grant_types(self, k8s_dir):
        instances = gettoken.list_instances(k8s_dir)
        grants = {i["name"]: i["grant"] for i in instances}
        assert grants.get("interop") == "refresh_token"
        assert grants.get("preship") == "client_credentials"


# ── ETP / partition helpers ───────────────────────────────────────────────

class TestHelpers:

    def test_etp_url(self):
        url = gettoken.etp_url("swedev")
        assert url.startswith("wss://")
        assert "admeinterop" in url

    def test_partition(self):
        assert gettoken.partition("swedev") == "dev"

    def test_etp_url_alias(self):
        url = gettoken.etp_url("interop")
        assert "admeinterop" in url
