"""
_common.py - Shared utilities for all generators.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional


# Stable deterministic UUID namespace (matches existing gen scripts)
NS = uuid.UUID("a0000000-d509-4e00-8000-000000000000")


def det_uuid(seed: str) -> str:
    """Deterministic UUID from seed string."""
    return str(uuid.uuid5(NS, seed))


def rand_uuid() -> str:
    return str(uuid.uuid4())


def load_json(path: str | Path) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_manifest(manifest: Dict, path: str | Path) -> None:
    Path(path).write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def build_manifest(
    *,
    reference_data: Optional[List[Dict]] = None,
    master_data: Optional[List[Dict]] = None,
    datasets: Optional[List[Dict]] = None,
    wpcs: Optional[List[Dict]] = None,
    work_products: Optional[List[Dict]] = None,
) -> Dict[str, Any]:
    """Build a standard OSDU Manifest envelope."""
    return {
        "kind": "osdu:wks:Manifest:1.0.0",
        "ReferenceData": reference_data or [],
        "MasterData": master_data or [],
        "Data": {
            "Datasets": datasets or [],
            "WorkProductComponents": wpcs or [],
            "WorkProducts": work_products or [],
        },
    }


def find_id(manifest: Dict, kind_fragment: str) -> str:
    """Find the first record ID in a manifest matching a kind substring."""
    for md in manifest.get("MasterData", []):
        if kind_fragment in md.get("kind", ""):
            return md["id"]
    for wpc in manifest.get("Data", {}).get("WorkProductComponents", []):
        if kind_fragment in wpc.get("kind", ""):
            return wpc["id"]
    for ds in manifest.get("Data", {}).get("Datasets", []):
        if kind_fragment in ds.get("kind", ""):
            return ds["id"]
    wp = manifest.get("Data", {}).get("WorkProducts")
    if isinstance(wp, list):
        for w in wp:
            if kind_fragment in w.get("kind", ""):
                return w["id"]
    elif isinstance(wp, dict) and kind_fragment in wp.get("kind", ""):
        return wp["id"]
    return ""


def find_all_ids(manifest: Dict, kind_fragment: str) -> List[str]:
    """Find all record IDs in a manifest matching a kind substring."""
    ids = []
    for md in manifest.get("MasterData", []):
        if kind_fragment in md.get("kind", ""):
            ids.append(md["id"])
    for wpc in manifest.get("Data", {}).get("WorkProductComponents", []):
        if kind_fragment in wpc.get("kind", ""):
            ids.append(wpc["id"])
    for ds in manifest.get("Data", {}).get("Datasets", []):
        if kind_fragment in ds.get("kind", ""):
            ids.append(ds["id"])
    return ids


def default_acl(partition: str = "dev") -> Dict[str, List[str]]:
    # Interop instance uses default viewers, interop uses office.global.viewers
    if partition == "dev":
        viewers = f"data.default.viewers@{partition}.dataservices.energy"
    else:
        viewers = f"data.default.viewers@{partition}.dataservices.energy"
    return {
        "owners":  [f"data.default.owners@{partition}.dataservices.energy"],
        "viewers": [viewers],
    }


def default_legal(partition: str = "dev") -> Dict[str, Any]:
    # Interop instance uses a different legal tag naming convention
    tag_overrides = {
        "opendes": "opendes-public-norway",
    }
    tag = tag_overrides.get(partition, f"{partition}-private-usa-default")
    return {
        "legaltags": [tag],
        "otherRelevantDataCountries": ["NO"],
    }


def ref_id(pfx: str, entity: str, name: str) -> str:
    """Reference-data ID with trailing colon."""
    return f"{pfx}:reference-data--{entity}:{name}:"


def md_id(pfx: str, entity: str, uid: str) -> str:
    """Master-data ID."""
    return f"{pfx}:master-data--{entity}:{uid}:1"


def wpc_id(pfx: str, entity: str, uid: str) -> str:
    """Work-product-component ID."""
    return f"{pfx}:work-product-component--{entity}:{uid}:1"


def ds_id(pfx: str, entity: str, uid: str) -> str:
    """Dataset ID."""
    return f"{pfx}:dataset--{entity}:{uid}:1"


def resolve_acl_legal(
    spec: Dict,
    partition: str,
    masterwp: Optional[Dict] = None,
) -> tuple:
    """Resolve ACL and legal from spec, masterwp, or defaults."""
    acl = spec.get("acl")
    legal = spec.get("legal")

    if not acl and masterwp:
        for md in masterwp.get("MasterData", []):
            if "Reservoir:" in md.get("kind", ""):
                acl = md.get("acl")
                legal = md.get("legal")
                break

    if not acl:
        acl = default_acl(partition)
    if not legal:
        legal = default_legal(partition)

    return acl, legal


def resolve_reservoir_id(masterwp: Optional[Dict]) -> str:
    """Extract Reservoir ID from a masterwp manifest."""
    if not masterwp:
        return ""
    for md in masterwp.get("MasterData", []):
        if "Reservoir:" in md.get("kind", ""):
            return md["id"]
    return ""


def resolve_file(rel_path: str, base_dir: Path) -> Path:
    """Resolve a relative path against base_dir, then repo root."""
    p = base_dir / rel_path
    if p.exists():
        return p
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    alt = repo_root / rel_path
    if alt.exists():
        return alt
    return p  # return original for error messages


def load_ref(
    spec: Dict,
    refs: Dict,
    spec_key: str,
    ref_key: str,
    base_dir: Path,
) -> Optional[Dict]:
    """Load a manifest from refs dict or from a file path in the spec."""
    if ref_key in refs:
        return refs[ref_key]
    path = spec.get(spec_key)
    if path:
        p = resolve_file(path, base_dir)
        if p.exists():
            return load_json(p)
    return None
