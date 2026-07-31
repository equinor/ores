#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ingest_preship.py - Ingest demo data into an OSDU instance.

Reads target-instance config from .env  (INSTANCE_<NAME>_* variables)
so the same script works against any registered backend.

Datasets
  dg1       Drogon DG1 - business-decision, risks, volumes, master data
  dg2       Drogon DG2 - development concepts, seismic, documents, …

Usage
  python demo/ingest_preship.py                          # all → preship
  python demo/ingest_preship.py --target preship         # explicit target
  python demo/ingest_preship.py --only dg1               # just DG1
  python demo/ingest_preship.py --only dg1 dg2           # DG1 + DG2
  python demo/ingest_preship.py --dry-run                # preview only
  python demo/ingest_preship.py --skip-schemas           # skip schema reg.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, List

import httpx

# ── Paths ─────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT  = SCRIPT_DIR.parent

DG1_RECORDS       = SCRIPT_DIR / "drogon" / "records"
DG2_RECORDS       = SCRIPT_DIR / "drogon_dg2" / "records"
DEVCONCEPT_SCHEMA = SCRIPT_DIR / "drogon" / "schema_devconcept.json"
CHRONOSTRAT_ZIP   = SCRIPT_DIR / "strat" / "chronostrat_records.zip"
STRATCOLUMN_ZIP   = SCRIPT_DIR / "strat" / "stratcolumn_records.zip"

# ── Instance config (populated by load_instance_config in main) ──────
TARGET: Dict[str, Any] = {}

# Source partition (auto-detected from records, fallback)
SRC_PARTITION = "dev"

# ── kind string parser ────────────────────────────────────────────────
KIND_RE = re.compile(
    r"^(?P<authority>[^:]+)"
    r":(?P<source>[^:]+)"
    r":(?P<entityType>[^:]+)"
    r":(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)$"
)


def parse_kind(kind: str) -> dict:
    m = KIND_RE.match(kind)
    if not m:
        raise ValueError(f"Cannot parse kind string: {kind!r}")
    return {
        "authority": m.group("authority"),
        "source": m.group("source"),
        "entityType": m.group("entityType"),
        "schemaVersionMajor": int(m.group("major")),
        "schemaVersionMinor": int(m.group("minor")),
        "schemaVersionPatch": int(m.group("patch")),
    }


# ── Instance config loader (via central _auth module) ─────────────────

sys.path.insert(0, str(SCRIPT_DIR))
from _auth import load_instance as _load_inst, mint_from_env  # noqa: E402


def load_instance_config(name: str) -> Dict[str, Any]:
    """Build an instance config dict via the unified _auth resolution chain.

    Tries:  k8s/secret.yaml + configmap.yaml → INSTANCE_<NAME>_* env → .env
    """
    inst = _load_inst(name)
    return {
        "host":          inst["host"],
        "partition":     inst["partition"],
        "tenant":        inst["tenant"],
        "client_id":     inst["client_id"],
        "client_secret": inst.get("client_secret", ""),
        "scope":         inst.get("scope") or f"{inst['client_id']}/.default",
        "legal_tag":     inst.get("legal_tag") or f"{inst['partition']}-public-usa-dataset-1",
        "owners":        inst.get("owners") or [f"data.default.owners@{inst['partition']}.dataservices.energy"],
        "viewers":       inst.get("viewers") or [f"data.default.viewers@{inst['partition']}.dataservices.energy"],
        "countries":     inst.get("countries") or ["US"],
    }


# ── Auth (via central _auth module) ───────────────────────────────────

_cached_token: str | None = None
_cached_exp: float = 0.0


def get_access_token() -> str:
    """Mint access_token via the unified _auth module (auto-detects grant type)."""
    global _cached_token, _cached_exp
    if _cached_token and time.time() < _cached_exp:
        return _cached_token

    env = {
        "tenant":        TARGET["tenant"],
        "client_id":     TARGET["client_id"],
        "client_secret": TARGET.get("client_secret", ""),
        "refresh_token": TARGET.get("refresh_token", ""),
        "scope":         TARGET["scope"],
    }
    _cached_token = mint_from_env(env)
    _cached_exp = time.time() + 3000
    return _cached_token


def api_headers() -> dict:
    return {
        "Authorization": f"Bearer {get_access_token()}",
        "Content-Type":  "application/json",
        "data-partition-id": TARGET["partition"],
    }


# ── Schema registration ──────────────────────────────────────────────

def check_schema_exists(client: httpx.Client, kind: str) -> bool:
    r = client.get(
        f"{TARGET['host']}/api/schema-service/v1/schema/{kind}",
        headers=api_headers(),
    )
    return r.status_code == 200


def register_schema(client: httpx.Client, schema_body: dict,
                    *, authority_override: str | None = None,
                    dry_run: bool = False) -> bool:
    kind = schema_body.get("x-osdu-schema-source", "")
    if not kind:
        print("    ✗ schema has no x-osdu-schema-source")
        return False

    identity = parse_kind(kind)
    if authority_override:
        identity["authority"] = authority_override

    payload = {
        "schemaInfo": {
            "schemaIdentity": identity,
            "status": "DEVELOPMENT",
        },
        "schema": schema_body,
    }

    label = f"{identity['authority']}:{identity['source']}:{identity['entityType']}:{identity['schemaVersionMajor']}.{identity['schemaVersionMinor']}.{identity['schemaVersionPatch']}"

    if dry_run:
        print(f"    [dry-run] would register {label}")
        return True

    url = f"{TARGET['host']}/api/schema-service/v1/schema"
    r = client.put(url, json=payload, headers=api_headers(), timeout=60)
    if r.status_code in (200, 201):
        print(f"    ✓ registered {label}")
        return True
    elif r.status_code == 409:
        print(f"    ≈ {label} already exists")
        return True
    else:
        print(f"    ✗ {label}: {r.status_code} {r.text[:200]}")
        return False


def register_missing_schemas(client: httpx.Client, dry_run: bool = False) -> None:
    """Register schemas that are missing on the pre-ship instance."""
    print("\n── Registering missing schemas ──")

    # 1. Resolved SeisInt schemas
    if SEISINT_SCHEMAS.is_dir():
        for f in sorted(SEISINT_SCHEMAS.glob("*.json")):
            body = json.loads(f.read_text(encoding="utf-8"))
            kind = body.get("x-osdu-schema-source", "")
            if kind and not check_schema_exists(client, kind):
                register_schema(client, body, dry_run=dry_run)
            else:
                print(f"    ≈ {kind} exists (or unresolvable)")

    # 2. DevelopmentConcept custom schema
    if DEVCONCEPT_SCHEMA.exists():
        body = json.loads(DEVCONCEPT_SCHEMA.read_text(encoding="utf-8"))
        kind = body.get("x-osdu-schema-source", "")
        # For preship, register under "opendes" authority instead of "dev"
        tgt_kind = kind.replace("dev:", f"{TARGET['partition']}:") if kind.startswith("dev:") else kind
        if not check_schema_exists(client, tgt_kind) and not check_schema_exists(client, kind):
            register_schema(client, body, authority_override=TARGET["partition"], dry_run=dry_run)
        else:
            print(f"    ≈ {kind} exists")

    # 3. ActivityTemplate and work-product - these are standard OSDU schemas
    #    that should exist on M26 but may not. We'll create minimal schemas.
    for missing_kind, entity_type, group in [
        ("osdu:wks:work-product-component--ActivityTemplate:1.0.0",
         "work-product-component--ActivityTemplate", "work-product-component"),
        ("osdu:wks:work-product:1.0.0", "work-product", "work-product"),
    ]:
        if not check_schema_exists(client, missing_kind):
            # Create a minimal permissive schema
            minimal = {
                "x-osdu-schema-source": missing_kind,
                "$schema": "http://json-schema.org/draft-07/schema#",
                "title": entity_type,
                "type": "object",
                "additionalProperties": True,
            }
            register_schema(client, minimal, dry_run=dry_run)
        else:
            print(f"    ≈ {missing_kind} exists")

    # 4. LocalBoundaryFeature
    lbf_kind = "osdu:wks:master-data--LocalBoundaryFeature:1.1.0"
    if not check_schema_exists(client, lbf_kind):
        minimal = {
            "x-osdu-schema-source": lbf_kind,
            "$schema": "http://json-schema.org/draft-07/schema#",
            "title": "LocalBoundaryFeature",
            "type": "object",
            "additionalProperties": True,
        }
        register_schema(client, minimal, dry_run=dry_run)
    else:
        print(f"    ≈ {lbf_kind} exists")


# ── Record transformation ────────────────────────────────────────────

def transform_record(rec: dict) -> dict:
    """Re-prefix record ID, rewrite ACL/legal for target instance."""
    # 1. Re-prefix ID:  dev:master-data--X:uuid:1 → opendes:master-data--X:uuid:1
    rid = rec.get("id", "")
    if ":" in rid:
        parts = rid.split(":", 1)
        if parts[0] == SRC_PARTITION:
            rec["id"] = f"{TARGET['partition']}:{parts[1]}"

    # 2. Re-prefix kind if it starts with "dev:"
    kind = rec.get("kind", "")
    if kind.startswith(f"{SRC_PARTITION}:"):
        rec["kind"] = f"{TARGET['partition']}:{kind[len(SRC_PARTITION)+1:]}"

    # 3. Rewrite ACL
    acl = rec.get("acl", {})
    acl["owners"] = TARGET["owners"][:]
    acl["viewers"] = TARGET["viewers"][:]
    rec["acl"] = acl

    # 4. Rewrite legal
    legal = rec.get("legal", {})
    legal["legaltags"] = [TARGET["legal_tag"]]
    legal["otherRelevantDataCountries"] = TARGET["countries"][:]
    rec["legal"] = legal

    # 5. Rewrite any embedded partition references in data.* fields
    _rewrite_partition_refs(rec.get("data", {}))

    return rec


def _rewrite_partition_refs(obj: Any) -> None:
    """Recursively rewrite dev: → opendes: in nested string values,
    and patch ServerURL to point at the target OSDU instance."""
    src_host = "equinorswedev.energy.azure.com"
    tgt_host_raw = TARGET.get("host", "")
    # Strip https:// to get bare hostname
    tgt_host = tgt_host_raw.replace("https://", "").replace("http://", "").rstrip("/")

    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str):
                if v.startswith(f"{SRC_PARTITION}:"):
                    obj[k] = f"{TARGET['partition']}:{v[len(SRC_PARTITION)+1:]}"
                elif src_host in v and tgt_host:
                    obj[k] = v.replace(src_host, tgt_host)
            elif isinstance(v, (dict, list)):
                _rewrite_partition_refs(v)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            if isinstance(item, str):
                if item.startswith(f"{SRC_PARTITION}:"):
                    obj[i] = f"{TARGET['partition']}:{item[len(SRC_PARTITION)+1:]}"
                elif src_host in item and tgt_host:
                    obj[i] = item.replace(src_host, tgt_host)
            elif isinstance(item, (dict, list)):
                _rewrite_partition_refs(item)


# ── Ingestion ────────────────────────────────────────────────────────

MAX_RETRIES = 4
RETRY_BACKOFF = [3, 6, 10, 15]


def ingest_records(client: httpx.Client, records: List[dict],
                   label: str, *, dry_run: bool = False) -> dict:
    """Ingest a batch of records via Storage API."""
    print(f"\n── Ingesting {label} ({len(records)} records) ──")

    if dry_run:
        for r in records:
            print(f"    [dry-run] {r.get('id', '?')[:60]}")
        return {"created": 0, "skipped": 0, "failed": 0}

    created, skipped, failed = [], [], []

    # Try batch first
    print(f"  Attempting batch PUT ({len(records)} records) …")
    url = f"{TARGET['host']}/api/storage/v2/records"

    for attempt in range(MAX_RETRIES + 1):
        resp = client.put(url, json=records, headers=api_headers(), timeout=120)
        if resp.status_code == 404 and attempt < MAX_RETRIES:
            wait = RETRY_BACKOFF[attempt]
            print(f"    404 on attempt {attempt+1}, retrying in {wait}s …")
            time.sleep(wait)
            continue
        break

    if resp.is_success:
        result = resp.json()
        created = result.get("recordIds", [])
        skipped = result.get("skippedRecordIds", [])
        print(f"    ✓ batch OK: created={len(created)}  skipped={len(skipped)}")
    else:
        print(f"    ✗ batch failed ({resp.status_code}): {resp.text[:300]}")
        print(f"    Falling back to sequential ingestion …")

        for i, rec in enumerate(records):
            rid = rec.get("id", "?")
            short = rid.split(":")[-1][:35] if ":" in rid else rid[:40]
            for attempt in range(MAX_RETRIES + 1):
                resp = client.put(url, json=[rec], headers=api_headers(), timeout=60)
                if resp.is_success:
                    r = resp.json()
                    created.extend(r.get("recordIds", []))
                    skipped.extend(r.get("skippedRecordIds", []))
                    tag = "✓" if r.get("recordIds") else "≈"
                    print(f"    [{i+1:02d}/{len(records)}] {tag} {short}")
                    break
                if resp.status_code == 404 and attempt < MAX_RETRIES:
                    wait = RETRY_BACKOFF[attempt]
                    print(f"        ↳ 404 - retry in {wait}s …")
                    time.sleep(wait)
                    continue
                failed.append(f"{rid}: {resp.status_code} {resp.text[:150]}")
                print(f"    [{i+1:02d}/{len(records)}] ✗ {short} ({resp.status_code})")
                break
            time.sleep(1)  # small delay between individual puts

    summary = {"created": len(created), "skipped": len(skipped), "failed": len(failed)}
    print(f"  Summary: created={summary['created']}  skipped={summary['skipped']}  failed={summary['failed']}")
    if failed:
        print("  Failures:")
        for f in failed:
            print(f"    {f}")
    return summary


def load_and_transform(records_dir: Path) -> List[dict]:
    """Load JSON records from a directory, transform for target."""
    records = []
    for f in sorted(records_dir.glob("*.json")):
        rec = json.loads(f.read_text(encoding="utf-8"))
        rec = transform_record(rec)
        records.append(rec)
    return records


def load_and_transform_zip(zip_path: Path) -> List[dict]:
    """Load JSON records from a zip archive, transform for target."""
    records = []
    with zipfile.ZipFile(zip_path) as zf:
        for name in sorted(zf.namelist()):
            if not name.endswith(".json"):
                continue
            raw = zf.read(name)
            rec = json.loads(raw)
            rec = transform_record(rec)
            records.append(rec)
    return records


INGEST_BATCH_SIZE = 500   # Storage API limit per PUT


def ingest_records_chunked(client: httpx.Client, records: List[dict],
                           label: str, *, dry_run: bool = False) -> dict:
    """Ingest records in chunks of INGEST_BATCH_SIZE."""
    if len(records) <= INGEST_BATCH_SIZE:
        return ingest_records(client, records, label, dry_run=dry_run)

    totals = {"created": 0, "skipped": 0, "failed": 0}
    n_chunks = (len(records) + INGEST_BATCH_SIZE - 1) // INGEST_BATCH_SIZE
    for i in range(0, len(records), INGEST_BATCH_SIZE):
        chunk = records[i : i + INGEST_BATCH_SIZE]
        chunk_num = i // INGEST_BATCH_SIZE + 1
        result = ingest_records(client, chunk,
                                f"{label} [{chunk_num}/{n_chunks}]",
                                dry_run=dry_run)
        for k in totals:
            totals[k] += result[k]
    return totals


# ── Main ──────────────────────────────────────────────────────────────

DATASETS = ["dg1", "dg2", "strat"]


def main():
    global TARGET

    ap = argparse.ArgumentParser(description="Ingest demo data into an OSDU instance")
    ap.add_argument("--target", default="preship",
                    help="Instance name (reads INSTANCE_<NAME>_* from .env)")
    ap.add_argument("--dry-run", action="store_true", help="Preview only, no changes")
    ap.add_argument("--skip-schemas", action="store_true", help="Skip schema registration")
    ap.add_argument("--only", nargs="+", choices=DATASETS,
                    help="Datasets to ingest (default: all)")
    args = ap.parse_args()

    selected = set(args.only) if args.only else set(DATASETS)

    # Load target instance config from .env
    TARGET = load_instance_config(args.target)

    print("=" * 60)
    print(f"  OSDU Demo Ingestion  →  {args.target}")
    print(f"  Host:      {TARGET['host']}")
    print(f"  Partition:  {TARGET['partition']}")
    print(f"  Legal tag:  {TARGET['legal_tag']}")
    print(f"  Datasets:   {', '.join(sorted(selected))}")
    print("=" * 60)

    print("\n── Authenticating ──")
    get_access_token()

    with httpx.Client(timeout=120) as client:

        # 1. Register missing schemas
        if not args.skip_schemas:
            register_missing_schemas(client, dry_run=args.dry_run)

        totals = {"created": 0, "skipped": 0, "failed": 0}

        # 2. Ingest drogon DG1 records  (master data first - DG2 may reference it)
        if "dg1" in selected:
            if DG1_RECORDS.is_dir() and any(DG1_RECORDS.glob("*.json")):
                recs = load_and_transform(DG1_RECORDS)
                result = ingest_records(client, recs, "drogon_dg1", dry_run=args.dry_run)
                for k in totals:
                    totals[k] += result[k]
            else:
                print(f"\n⚠ DG1 records not found at {DG1_RECORDS}")
                print("  Run: python demo/run_pipeline.py demo/drogon --skip-optional --skip-ingest")

        # 3. Ingest drogon DG2 records
        if "dg2" in selected:
            if DG2_RECORDS.is_dir() and any(DG2_RECORDS.glob("*.json")):
                recs = load_and_transform(DG2_RECORDS)
                result = ingest_records(client, recs, "drogon_dg2", dry_run=args.dry_run)
                for k in totals:
                    totals[k] += result[k]
            else:
                print(f"\n⚠ DG2 records not found at {DG2_RECORDS}")
                print("  Run: python demo/run_pipeline.py demo/drogon_dg2")

        # 4. Ingest stratigraphy records (from zips)
        if "strat" in selected:
            for zip_path, label in [
                (CHRONOSTRAT_ZIP,  "chronostrat"),
                (STRATCOLUMN_ZIP,  "stratcolumn"),
            ]:
                if zip_path.exists():
                    recs = load_and_transform_zip(zip_path)
                    print(f"  Loaded {len(recs)} {label} records from zip")
                    result = ingest_records_chunked(client, recs, label,
                                                   dry_run=args.dry_run)
                    for k in totals:
                        totals[k] += result[k]
                else:
                    print(f"\n⚠ {label} zip not found at {zip_path}")

        # Summary
        print("\n" + "=" * 60)
        print("  TOTAL")
        print(f"  created/updated: {totals['created']}")
        print(f"  skipped:         {totals['skipped']}")
        print(f"  failed:          {totals['failed']}")
        print("=" * 60)


if __name__ == "__main__":
    main()
