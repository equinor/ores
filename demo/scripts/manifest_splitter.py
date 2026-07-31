"""
manifest_splitter.py - Split OSDU manifest envelopes into individual record files.

Replaces the dataset-specific manifest2records_*.py scripts with one generic utility.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .record_factory import manifest_to_records


def split_manifest(
    manifest_path: Path,
    output_dir: Optional[Path] = None,
    *,
    prefix: str = "",
) -> List[Path]:
    """
    Split a manifest JSON into individual record files.

    Args:
        manifest_path: Path to manifest JSON file
        output_dir: Directory for output records (default: manifest_path.parent / "records")
        prefix: Optional numeric prefix for ordering (e.g. "01_")

    Returns:
        List of created file paths
    """
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    records = manifest_to_records(data)

    if not records:
        print(f"  No records found in {manifest_path.name}")
        return []

    out_dir = output_dir or manifest_path.parent / "records"
    out_dir.mkdir(parents=True, exist_ok=True)

    created: List[Path] = []
    for i, rec in enumerate(records):
        # Build filename from record ID
        rec_id = rec.get("id", f"unknown_{i}")
        safe_name = _safe_filename(rec_id)
        filename = f"{prefix}{i:03d}_{safe_name}.json"
        out_path = out_dir / filename
        out_path.write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")
        created.append(out_path)

    print(f"  Split {manifest_path.name} → {len(created)} records in {out_dir.name}/")
    return created


def split_manifests(
    manifest_paths: List[Path],
    output_dir: Optional[Path] = None,
) -> List[Path]:
    """Split multiple manifests, preserving order with numeric prefixes."""
    all_created: List[Path] = []
    for idx, mpath in enumerate(manifest_paths):
        prefix = f"{idx:02d}_"
        created = split_manifest(mpath, output_dir, prefix=prefix)
        all_created.extend(created)
    return all_created


def _safe_filename(record_id: str) -> str:
    """Convert an OSDU record ID to a safe filename."""
    # dev:master-data--BusinessDecision:slug:1 → master-data--BusinessDecision_slug
    import re
    parts = record_id.split(":")
    if len(parts) >= 3:
        # Take category--Entity and slug
        name = f"{parts[1]}_{parts[2]}"
    else:
        name = record_id
    # Sanitize
    name = re.sub(r"[^a-zA-Z0-9_\-.]", "_", name)
    return name[:120]
