"""
config.py - Configuration management for generic OSDU scripts.

Supports multiple configuration sources (in priority order):
  1. CLI arguments / explicit dict
  2. Environment variables (OSDU_HOST, OSDU_PARTITION, etc.)
  3. JSON config file (~/.osdu/config.json or specified path)
  4. k8s/secret.yaml + k8s/configmap.yaml (ores repo fallback)

Perspective: fully independent of ORES - can be used standalone.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional


DEFAULT_CONFIG_PATH = Path.home() / ".osdu" / "config.json"
REPO_ROOT = Path(__file__).resolve().parent.parent.parent  # ores/
K8S_DIR = REPO_ROOT / "k8s"


@dataclass
class OsduInstance:
    """Complete OSDU instance configuration."""
    name: str = "default"
    host: str = ""
    partition: str = ""
    legal_tag: str = ""
    owners: List[str] = field(default_factory=list)
    viewers: List[str] = field(default_factory=list)
    countries: List[str] = field(default_factory=lambda: ["NO"])

    # Auth fields (not serialized to output)
    tenant_id: str = ""
    client_id: str = ""
    scope: str = ""
    refresh_token: str = ""
    client_secret: str = ""

    @property
    def acl(self) -> Dict[str, List[str]]:
        return {"owners": self.owners, "viewers": self.viewers}

    @property
    def legal(self) -> Dict[str, Any]:
        return {
            "legaltags": [self.legal_tag],
            "otherRelevantDataCountries": self.countries,
        }

    def to_dict(self) -> Dict[str, Any]:
        """Serialize config (excluding secrets)."""
        d = asdict(self)
        for secret_key in ("refresh_token", "client_secret"):
            d.pop(secret_key, None)
        return d


def load_config(
    instance_name: str = "default",
    config_file: Optional[str] = None,
    overrides: Optional[Dict[str, Any]] = None,
) -> OsduInstance:
    """
    Load OSDU instance configuration from multiple sources.

    Priority: overrides > env vars > config file > k8s YAML > defaults.
    """
    cfg: Dict[str, Any] = {}

    # 1. k8s YAML (ores repo fallback)
    cfg.update(_load_from_k8s(instance_name))

    # 2. Config file
    cfg.update(_load_from_file(instance_name, config_file))

    # 3. Environment variables
    cfg.update(_load_from_env())

    # 4. Explicit overrides
    if overrides:
        cfg.update({k: v for k, v in overrides.items() if v})

    cfg.setdefault("name", instance_name)
    return OsduInstance(**{k: v for k, v in cfg.items()
                          if k in OsduInstance.__dataclass_fields__})


def _load_from_env() -> Dict[str, Any]:
    """Read OSDU_* environment variables."""
    mapping = {
        "OSDU_HOST": "host",
        "OSDU_PARTITION": "partition",
        "OSDU_LEGAL_TAG": "legal_tag",
        "OSDU_OWNERS": "owners",
        "OSDU_VIEWERS": "viewers",
        "OSDU_COUNTRIES": "countries",
        "OSDU_TENANT_ID": "tenant_id",
        "OSDU_CLIENT_ID": "client_id",
        "OSDU_SCOPE": "scope",
        "OSDU_REFRESH_TOKEN": "refresh_token",
        "OSDU_CLIENT_SECRET": "client_secret",
    }
    result: Dict[str, Any] = {}
    for env_key, cfg_key in mapping.items():
        val = os.environ.get(env_key, "").strip()
        if not val:
            continue
        if cfg_key in ("owners", "viewers", "countries"):
            result[cfg_key] = [v.strip() for v in val.split(",")]
        else:
            result[cfg_key] = val
    return result


def _load_from_file(instance_name: str, config_file: Optional[str]) -> Dict[str, Any]:
    """Read from JSON config file."""
    path = Path(config_file) if config_file else DEFAULT_CONFIG_PATH
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}

    # Support both flat and multi-instance configs
    if "instances" in data and instance_name in data["instances"]:
        return data["instances"][instance_name]
    elif instance_name == "default":
        # Flat config (single instance)
        return {k: v for k, v in data.items() if k != "instances"}
    return {}


def _load_from_k8s(instance_name: str) -> Dict[str, Any]:
    """Try ores k8s/ YAML files as fallback."""
    if not K8S_DIR.exists():
        return {}
    try:
        env = _parse_k8s_yaml(K8S_DIR / "configmap.yaml")
        env.update(_parse_k8s_yaml(K8S_DIR / "secret.yaml"))
    except Exception:
        return {}

    # Look for INSTANCE_<NAME>_* keys
    prefix = f"INSTANCE_{instance_name.upper()}_"
    fields = {k[len(prefix):].lower(): v for k, v in env.items()
              if k.startswith(prefix) and v}
    if not fields:
        return {}

    # Map k8s field names to our config names
    mapping = {
        "hostname": "host",
        "data_partition_id": "partition",
        "default_legal_tag": "legal_tag",
        "default_owners": "owners",
        "default_viewers": "viewers",
        "default_countries": "countries",
    }
    result: Dict[str, Any] = {}
    for k8s_key, cfg_key in mapping.items():
        val = fields.get(k8s_key, "")
        if val:
            if cfg_key in ("owners", "viewers", "countries"):
                result[cfg_key] = [v.strip() for v in val.split(",")]
            else:
                result[cfg_key] = val
    # Pass through auth fields directly
    for auth_key in ("tenant_id", "client_id", "scope", "refresh_token", "client_secret"):
        if auth_key in fields:
            result[auth_key] = fields[auth_key]
    return result


def _parse_k8s_yaml(path: Path) -> Dict[str, str]:
    """Minimal k8s YAML parser (data: section only)."""
    if not path.exists():
        return {}
    result: Dict[str, str] = {}
    in_data = False
    for raw in path.read_text(encoding="utf-8").splitlines():
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        if s in ("data:", "stringData:"):
            in_data = True
            continue
        if not raw[0].isspace():
            in_data = False
            continue
        if in_data and ":" in s:
            k, _, v = s.partition(":")
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k and not k.startswith("#"):
                result[k] = v
    return result


def save_config(instance: OsduInstance, config_file: Optional[str] = None) -> Path:
    """Save instance config to JSON file."""
    path = Path(config_file) if config_file else DEFAULT_CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    existing: Dict[str, Any] = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    if "instances" not in existing:
        existing["instances"] = {}
    existing["instances"][instance.name] = instance.to_dict()

    path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
    return path
