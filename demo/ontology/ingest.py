#!/usr/bin/env python3
"""
demo/ontology/ingest.py — Generate ontology records from specs and ingest to OSDU.

All records are generated on-the-fly from specs in ./specs/.
No pre-generated JSON files are needed.

Usage:
  python demo/ontology/ingest.py --target eqndev
  python demo/ontology/ingest.py --target interop
  python demo/ontology/ingest.py --target eqndev --dry-run
  python demo/ontology/ingest.py --target eqndev --verify-only
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, Dict, List

import httpx

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
SPECS_DIR = SCRIPT_DIR / "specs"

sys.path.insert(0, str(REPO_ROOT / "demo"))
from _auth import get_token, load_instance  # noqa: E402

sys.path.insert(0, str(REPO_ROOT / "demo" / "scripts"))
from scripts.generators import run_generator  # noqa: E402
from scripts.generators._common import load_json, default_acl, default_legal  # noqa: E402


# ═══════════════════════════════════════════════════════════════════════════════
# Spec groups — ordered for dependency resolution
# ═══════════════════════════════════════════════════════════════════════════════

# Interop target: public demo (Drogon only)
INTEROP_SPECS = [
    "drogon_dg1.json",
    "drogon_dg2.json",
]

# Eqndev target: Drogon + Omegas (confidential)
EQNDEV_SPECS = [
    "drogon_dg1.json",
    "drogon_dg2.json",
    "omegas_wpc.json",
    "omegas_geolabelset.json",
    "omegas_document.json",
]


# ═══════════════════════════════════════════════════════════════════════════════
# Generate records from specs
# ═══════════════════════════════════════════════════════════════════════════════


def generate_all(spec_names: List[str], partition: str) -> List[Dict[str, Any]]:
    """Generate OSDU records from all listed specs."""
    records: List[Dict[str, Any]] = []
    for name in spec_names:
        spec_path = SPECS_DIR / name
        spec = load_json(spec_path)
        generated = run_generator(spec, partition, spec_path.parent)
        records.extend(generated)
        print(f"  {name}: {len(generated)} records")
    return records


# ═══════════════════════════════════════════════════════════════════════════════
# Ingest to OSDU Storage API
# ═══════════════════════════════════════════════════════════════════════════════


def ingest_records(
    records: List[Dict[str, Any]],
    host: str,
    partition: str,
    token: str,
    label: str,
    dry_run: bool = False,
) -> tuple:
    """PUT records to Storage API. Returns (created, skipped, errors)."""
    if dry_run:
        print(f"  [{label}] DRY RUN — {len(records)} records would be ingested")
        return len(records), 0, []

    headers = {
        "Authorization": f"Bearer {token}",
        "data-partition-id": partition,
        "Content-Type": "application/json",
    }
    created = 0
    skipped = 0
    errors: List[str] = []

    with httpx.Client(headers=headers, timeout=120) as client:
        for rec in records:
            rid = rec.get("id", "?")
            short = rid.split(":")[-1][:40] if ":" in rid else rid[:40]

            url = f"{host}/api/storage/v2/records"
            try:
                r = client.put(url, json=[rec])
                if r.is_success:
                    resp = r.json()
                    c = len(resp.get("recordIds", []))
                    s = len(resp.get("skippedRecordIds", []))
                    created += c
                    skipped += s
                    tag = "✓" if c else "○"
                    print(f"    {tag} {short}")
                else:
                    errors.append(f"{short}: HTTP {r.status_code} - {r.text[:200]}")
                    print(f"    ✗ {short}: {r.status_code} {r.text[:100]}")
            except Exception as e:
                errors.append(f"{short}: {e}")
                print(f"    ✗ {short}: {e}")

            time.sleep(1)

    print(f"  [{label}] created={created} skipped={skipped} errors={len(errors)}")
    return created, skipped, errors


# ═══════════════════════════════════════════════════════════════════════════════
# Verify cross-references
# ═══════════════════════════════════════════════════════════════════════════════


def verify_relationships(
    records: List[Dict[str, Any]],
    host: str,
    partition: str,
    token: str,
) -> List[str]:
    """Verify that all referenced record IDs exist in the target instance."""
    headers = {
        "Authorization": f"Bearer {token}",
        "data-partition-id": partition,
    }
    referenced: set = set()
    record_ids: set = set()
    for rec in records:
        _collect_refs(rec, referenced, record_ids)

    external = referenced - record_ids
    if not external:
        print("    All references are self-contained.")
        return []

    print(f"    Checking {len(external)} external references …")
    missing: List[str] = []
    with httpx.Client(headers=headers, timeout=30) as client:
        for rid in sorted(external):
            try:
                r = client.get(f"{host}/api/storage/v2/records/{rid}")
                if r.status_code == 404:
                    missing.append(rid)
                    print(f"      ⚠ MISSING: {rid.split(':')[-1][:50]}")
            except Exception:
                pass

    if not missing:
        print("    ✓ All external references resolved.")
    else:
        print(f"    ⚠ {len(missing)} references not found.")
    return missing


def _collect_refs(rec: Dict[str, Any], refs: set, ids: set):
    """Extract all SRN references from a record."""
    rid = rec.get("id", "")
    if rid:
        ids.add(rid)
    data = rec.get("data", {})
    for p in data.get("Parameters", []):
        if isinstance(p, dict):
            dop = p.get("DataObjectParameter", "")
            if dop and ":" in dop:
                refs.add(dop)
    for r in data.get("RiskIDs", []):
        if isinstance(r, str) and ":" in r:
            refs.add(r)
    for a in data.get("PriorActivityIDs", []):
        if isinstance(a, str) and ":" in a:
            refs.add(a)
    pp = data.get("ParentProjectID", "")
    if pp and ":" in pp:
        refs.add(pp)
    tc = data.get("TrustedCollectionID", "")
    if tc and ":" in tc:
        refs.add(tc)
    for parent in (data.get("ancestry", {}) or {}).get("parents", []):
        if isinstance(parent, str) and ":" in parent:
            refs.add(parent)


# ═══════════════════════════════════════════════════════════════════════════════
# Stub (placeholder) records for missing references
# ═══════════════════════════════════════════════════════════════════════════════


def _id_to_kind(record_id: str) -> str:
    """Derive OSDU kind from a record ID.

    e.g. dev:master-data--Risk:X:1 → osdu:wks:master-data--Risk:1.0.0
         dev:work-product-component--WellPlan:X:1 → osdu:wks:work-product-component--WellPlan:1.0.0
         dev:dataset--ETPDataspace:X:1 → osdu:wks:dataset--ETPDataspace:1.0.0
    """
    # Split: partition:namespace--Entity:uid:version
    parts = record_id.split(":")
    if len(parts) < 3:
        return ""
    ns_entity = parts[1]  # e.g. "master-data--Risk" or "work-product-component--WellPlan"
    return f"osdu:wks:{ns_entity}:1.0.0"


def _id_to_name(record_id: str) -> str:
    """Generate a placeholder name from the ID slug.

    e.g. dev:master-data--Risk:OmegaSor-BariumScale-00061:1 → OmegaSor-BariumScale-00061
    """
    parts = record_id.split(":")
    if len(parts) >= 4:
        return parts[-2]  # the uid segment
    return record_id.split(":")[-1]


def build_stubs(
    missing_ids: List[str],
    partition: str,
) -> List[Dict[str, Any]]:
    """Build minimal placeholder records for missing referenced IDs."""
    acl = default_acl(partition)
    legal = default_legal(partition)
    stubs = []
    for rid in sorted(missing_ids):
        kind = _id_to_kind(rid)
        if not kind:
            continue
        name = _id_to_name(rid)
        entity = rid.split("--")[1].split(":")[0] if "--" in rid else "Record"
        stubs.append({
            "id": rid,
            "kind": kind,
            "acl": acl,
            "legal": legal,
            "data": {
                "Name": name.replace("-", " ").replace("_", " "),
                "Description": f"Placeholder {entity} record. Referenced by ontology but not yet fully populated.",
            },
        })
    return stubs


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Generate + ingest ontology records")
    ap.add_argument("--target", choices=["interop", "eqndev"], required=True)
    ap.add_argument("--dry-run", action="store_true", help="Generate but don't push")
    ap.add_argument("--verify-only", action="store_true", help="Only check references")
    ap.add_argument("--stubs", action="store_true", help="Create placeholder records for missing refs")
    args = ap.parse_args()

    inst = load_instance(args.target)
    token = get_token(args.target)
    partition = inst["partition"]

    specs = EQNDEV_SPECS if args.target == "eqndev" else INTEROP_SPECS
    label = args.target

    print(f"\n══ Ontology ingest: {args.target} ══")
    print(f"   Host: {inst['host']}")
    print(f"   Partition: {partition}")
    print(f"   Specs: {len(specs)}")
    print()

    # 1. Generate
    print("── Generate ──")
    records = generate_all(specs, partition)
    print(f"   Total: {len(records)} records\n")

    # 2. Ingest
    if not args.verify_only:
        print("── Ingest ──")
        ingest_records(records, inst["host"], partition, token, label,
                       dry_run=args.dry_run)
        print()

    # 3. Verify + stubs
    print("── Verify references ──")
    missing = verify_relationships(records, inst["host"], partition, token)

    if missing and args.stubs and not args.dry_run:
        print(f"\n── Creating {len(missing)} stub records ──")
        stubs = build_stubs(missing, partition)
        ingest_records(stubs, inst["host"], partition, token, f"{label}-stubs",
                       dry_run=False)

    print("\n✓ Done.")


if __name__ == "__main__":
    main()
