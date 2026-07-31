"""
ingest.py - Generic OSDU ingestion module.

Handles:
  - Record ID/ACL/legal rewriting for target instances
  - Batch ingestion via Storage API
  - Manifest ingestion via Workflow API
  - Dry-run mode
  - Progress reporting

Independent of ORES.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config import OsduInstance
from .osdu_client import OsduClient


def ingest_records(
    records: List[Dict[str, Any]],
    client: OsduClient,
    *,
    dry_run: bool = False,
    rewrite_partition: Optional[str] = None,
    progress_callback=None,
) -> Dict[str, Any]:
    """
    Ingest records into OSDU via Storage API.

    Args:
        records: List of OSDU records (with id, kind, acl, legal, data)
        client: Authenticated OsduClient
        dry_run: If True, validate only, don't push
        rewrite_partition: If set, rewrite all record IDs/references from
                          source partition to this target partition
        progress_callback: Optional callable(current, total, record_id)

    Returns:
        {"recordIds": [...], "totalCount": N, "errors": [...]}
    """
    instance = client.instance

    # Rewrite partition/ACL/legal if targeting a different instance
    if rewrite_partition:
        records = [_rewrite_record(r, rewrite_partition, instance) for r in records]
    else:
        # Always ensure ACL/legal match target instance
        for r in records:
            r["acl"] = instance.acl
            r["legal"] = instance.legal

    # Validate
    errors = client.validate_records(records)
    if errors:
        return {"recordIds": [], "totalCount": 0, "errors": errors}

    if dry_run:
        return {
            "recordIds": [r["id"] for r in records],
            "totalCount": len(records),
            "mode": "dry-run",
        }

    # Ingest
    if progress_callback:
        # Ingest one-by-one for progress reporting
        all_ids: List[str] = []
        all_errors: List[Any] = []
        for i, rec in enumerate(records):
            progress_callback(i + 1, len(records), rec["id"])
            try:
                result = client.put_records([rec])
                all_ids.extend(result.get("recordIds", []))
            except RuntimeError as e:
                all_errors.append({"record": rec["id"], "error": str(e)})
        resp: Dict[str, Any] = {"recordIds": all_ids, "totalCount": len(all_ids)}
        if all_errors:
            resp["errors"] = all_errors
        return resp
    else:
        return client.put_records(records)


def ingest_from_files(
    record_dir: Path,
    client: OsduClient,
    *,
    dry_run: bool = False,
    rewrite_partition: Optional[str] = None,
    pattern: str = "*.json",
) -> Dict[str, Any]:
    """
    Load records from a directory of JSON files and ingest.

    Records are sorted by filename (use numeric prefixes for ordering).
    """
    files = sorted(record_dir.glob(pattern))
    if not files:
        raise FileNotFoundError(f"No {pattern} files found in {record_dir}")

    records: List[Dict[str, Any]] = []
    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        if isinstance(data, list):
            records.extend(data)
        elif isinstance(data, dict):
            # Could be a single record or a manifest envelope
            if "id" in data and "kind" in data:
                records.append(data)
            else:
                # Assume manifest envelope
                from .record_factory import manifest_to_records
                records.extend(manifest_to_records(data))

    print(f"  Loaded {len(records)} records from {len(files)} files in {record_dir.name}/")
    return ingest_records(records, client, dry_run=dry_run,
                          rewrite_partition=rewrite_partition)


def ingest_from_manifest(
    manifest_path: Path,
    client: OsduClient,
    *,
    dry_run: bool = False,
    rewrite_partition: Optional[str] = None,
) -> Dict[str, Any]:
    """Load a manifest JSON file and ingest all records within."""
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    from .record_factory import manifest_to_records
    records = manifest_to_records(data)
    print(f"  Loaded {len(records)} records from {manifest_path.name}")
    return ingest_records(records, client, dry_run=dry_run,
                          rewrite_partition=rewrite_partition)


# ── Rewrite logic ────────────────────────────────────────────────────────

def _rewrite_record(
    record: Dict[str, Any],
    target_partition: str,
    instance: OsduInstance,
) -> Dict[str, Any]:
    """Rewrite a record's partition, ACL, legal, and internal references."""
    rec = json.loads(json.dumps(record))  # deep copy

    # Detect source partition from record ID
    src_partition = rec["id"].split(":")[0] if ":" in rec.get("id", "") else ""

    # Rewrite ID
    if src_partition and src_partition != target_partition:
        rec["id"] = rec["id"].replace(f"{src_partition}:", f"{target_partition}:", 1)

    # Set ACL and legal
    rec["acl"] = instance.acl
    rec["legal"] = instance.legal

    # Rewrite references in data (recursive string replacement)
    if src_partition and src_partition != target_partition:
        rec["data"] = _rewrite_refs(rec["data"], src_partition, target_partition)

    return rec


def _rewrite_refs(obj: Any, src: str, target: str) -> Any:
    """Recursively rewrite partition references in data fields."""
    if isinstance(obj, str):
        # Only rewrite OSDU record ID patterns (partition:type--Entity:...)
        if obj.startswith(f"{src}:") and "--" in obj:
            return obj.replace(f"{src}:", f"{target}:", 1)
        return obj
    elif isinstance(obj, dict):
        return {k: _rewrite_refs(v, src, target) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_rewrite_refs(item, src, target) for item in obj]
    return obj
