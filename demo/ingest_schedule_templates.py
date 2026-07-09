#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ingest_schedule_templates.py - Ingest ActivityStateTemplate WPCs and
ProjectType reference data to OSDU instances.

Usage:
  # Ingest to eqndev (default):
  python demo/ingest_schedule_templates.py

  # Ingest to interop:
  python demo/ingest_schedule_templates.py --target interop

  # Dry-run:
  python demo/ingest_schedule_templates.py --dry-run

  # Both eqndev and interop:
  python demo/ingest_schedule_templates.py --target eqndev interop
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

SCRIPT_DIR = Path(__file__).resolve().parent  # demo/
REPO_ROOT = SCRIPT_DIR.parent

sys.path.insert(0, str(SCRIPT_DIR))
from _auth import get_token, load_instance  # noqa: E402

try:
    import httpx
except ImportError:
    sys.exit("pip install httpx")

# ── Data files ──────────────────────────────────────────────────────────
TEMPLATES_FILE = SCRIPT_DIR / "activity_state_templates.json"
PROJECT_TYPES_FILE = SCRIPT_DIR / "reference_data_project_types.json"

# Source partition (records are authored with "dev" prefix)
SRC_PARTITION = "dev"


# ═══════════════════════════════════════════════════════════════════════════
# Record transformation
# ═══════════════════════════════════════════════════════════════════════════

def transform_record(rec: dict, target: dict) -> dict:
    """Rewrite record IDs, ACL, legal, and embedded refs for target instance."""
    import copy
    rec = copy.deepcopy(rec)
    tgt = target["partition"]

    # ID
    rid = rec.get("id", "")
    if rid.startswith(f"{SRC_PARTITION}:"):
        rec["id"] = f"{tgt}:{rid[len(SRC_PARTITION)+1:]}"

    # Kind stays osdu:wks:... (community schemas, no partition prefix)

    # ACL
    rec["acl"] = {
        "owners": target["owners"][:],
        "viewers": target["viewers"][:],
    }

    # Legal
    rec["legal"] = {
        "legaltags": [target["legal_tag"]],
        "otherRelevantDataCountries": target["countries"][:],
    }

    # Rewrite embedded partition refs in data
    _rewrite_refs(rec.get("data", {}), tgt)

    return rec


def _rewrite_refs(obj: Any, tgt: str) -> None:
    """Recursively rewrite SRC_PARTITION: → target partition: in strings."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str) and v.startswith(f"{SRC_PARTITION}:"):
                obj[k] = f"{tgt}:{v[len(SRC_PARTITION)+1:]}"
            elif isinstance(v, (dict, list)):
                _rewrite_refs(v, tgt)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            if isinstance(item, str) and item.startswith(f"{SRC_PARTITION}:"):
                obj[i] = f"{tgt}:{item[len(SRC_PARTITION)+1:]}"
            elif isinstance(item, (dict, list)):
                _rewrite_refs(item, tgt)


# ═══════════════════════════════════════════════════════════════════════════
# Schema registration
# ═══════════════════════════════════════════════════════════════════════════

def ensure_schema(client: httpx.Client, target: dict, kind: str,
                  title: str, *, dry_run: bool = False) -> None:
    """Register a minimal schema if it doesn't exist."""
    host = target["host"]
    headers = _headers(target)

    # Check if already exists
    r = client.get(f"{host}/api/schema-service/v1/schema/{kind}",
                   headers=headers, timeout=30)
    if r.status_code == 200:
        print(f"    ≈ schema {kind} already exists")
        return

    if dry_run:
        print(f"    [dry-run] would register schema {kind}")
        return

    payload = {
        "schemaInfo": {
            "schemaIdentity": {
                "authority": "osdu",
                "source": "wks",
                "entityType": kind.split("--")[1].split(":")[0] if "--" in kind else kind,
                "schemaVersionMajor": 1,
                "schemaVersionMinor": 0,
                "schemaVersionPatch": 0,
            },
            "status": "DEVELOPMENT",
        },
        "schema": {
            "x-osdu-schema-source": kind,
            "$schema": "http://json-schema.org/draft-07/schema#",
            "title": title,
            "type": "object",
            "additionalProperties": True,
        },
    }
    r = client.put(f"{host}/api/schema-service/v1/schema",
                   json=payload, headers=headers, timeout=60)
    if r.status_code in (200, 201):
        print(f"    ✓ registered schema {kind}")
    elif r.status_code == 409:
        print(f"    ≈ schema {kind} already exists (409)")
    else:
        print(f"    ✗ schema {kind}: {r.status_code} {r.text[:200]}")


# ═══════════════════════════════════════════════════════════════════════════
# Ingestion
# ═══════════════════════════════════════════════════════════════════════════

def _headers(target: dict) -> dict:
    return {
        "Authorization": f"Bearer {target['token']}",
        "data-partition-id": target["partition"],
        "Content-Type": "application/json",
    }


def ingest_records(client: httpx.Client, records: List[dict], target: dict,
                   label: str, *, dry_run: bool = False) -> dict:
    """PUT records to Storage API. Returns summary."""
    transformed = [transform_record(r, target) for r in records]
    print(f"\n  [{label}]  {len(transformed)} records → {target['partition']}")

    if dry_run:
        for r in transformed:
            print(f"    [dry-run] {r.get('id', '?')[:80]}")
        return {"created": len(transformed), "failed": 0}

    url = f"{target['host']}/api/storage/v2/records"
    headers = _headers(target)

    r = client.put(url, json=transformed, headers=headers, timeout=60)
    if r.is_success:
        body = r.json()
        created = body.get("recordIds", [])
        skipped = body.get("skippedRecordIds", [])
        print(f"    ✓ created={len(created)}  skipped={len(skipped)}")
        return {"created": len(created), "failed": 0}
    else:
        print(f"    ✗ batch failed ({r.status_code}): {r.text[:300]}")
        # Sequential fallback
        created = 0
        failed = 0
        for rec in transformed:
            rr = client.put(url, json=[rec], headers=headers, timeout=30)
            rid = rec.get("id", "?")
            short = rid.split("--")[-1][:50] if "--" in rid else rid[:50]
            if rr.is_success:
                print(f"    ✓ {short}")
                created += 1
            else:
                print(f"    ✗ {short}: {rr.status_code} {rr.text[:100]}")
                failed += 1
            time.sleep(0.3)
        return {"created": created, "failed": failed}


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(
        description="Ingest ActivityStateTemplate WPCs and ProjectType reference data")
    ap.add_argument("--target", nargs="+", default=["eqndev"],
                    help="Target instance(s) (default: eqndev)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Preview without ingesting")
    ap.add_argument("--skip-schemas", action="store_true",
                    help="Skip schema registration")
    args = ap.parse_args()

    # Load data
    templates = json.loads(TEMPLATES_FILE.read_text(encoding="utf-8"))
    project_types = json.loads(PROJECT_TYPES_FILE.read_text(encoding="utf-8"))

    print(f"Loaded {len(templates)} ActivityStateTemplates, {len(project_types)} ProjectTypes")

    for target_name in args.target:
        print(f"\n{'=' * 64}")
        print(f"  Target: {target_name}")
        print(f"{'=' * 64}")

        # Load instance config
        try:
            inst = load_instance(target_name)
        except Exception as e:
            print(f"  ✗ Could not load instance '{target_name}': {e}")
            continue

        # Get token
        token = get_token(target_name)
        target = {
            "host": f"https://{inst['host']}" if not inst["host"].startswith("http") else inst["host"],
            "partition": inst["partition"],
            "token": token,
            "legal_tag": inst.get("legal_tag") or f"{inst['partition']}-public-usa-dataset-1",
            "owners": inst.get("owners") if isinstance(inst.get("owners"), list)
                      else [inst["owners"]] if inst.get("owners") else
                      [f"data.default.owners@{inst['partition']}.dataservices.energy"],
            "viewers": inst.get("viewers") if isinstance(inst.get("viewers"), list)
                       else [inst["viewers"]] if inst.get("viewers") else
                       [f"data.default.viewers@{inst['partition']}.dataservices.energy"],
            "countries": inst.get("countries", ["US"]),
        }

        print(f"  Host:      {target['host']}")
        print(f"  Partition: {target['partition']}")

        with httpx.Client(timeout=60) as client:
            # Register schemas if needed
            if not args.skip_schemas:
                print("\n  ── Schema registration ──")
                ensure_schema(
                    client, target,
                    "osdu:wks:work-product-component--ActivityStateTemplate:1.0.0",
                    "ActivityStateTemplate",
                    dry_run=args.dry_run,
                )
                ensure_schema(
                    client, target,
                    "osdu:wks:reference-data--ProjectType:1.0.0",
                    "ProjectType",
                    dry_run=args.dry_run,
                )

            # Ingest ProjectType reference data
            ingest_records(
                client, project_types, target,
                "ProjectType reference data",
                dry_run=args.dry_run,
            )

            # Ingest ActivityStateTemplate WPCs
            ingest_records(
                client, templates, target,
                "ActivityStateTemplate WPCs",
                dry_run=args.dry_run,
            )

    print(f"\n{'=' * 64}")
    print("  Done.")
    print(f"{'=' * 64}")


if __name__ == "__main__":
    main()
