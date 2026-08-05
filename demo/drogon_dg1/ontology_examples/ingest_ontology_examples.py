#!/usr/bin/env python3
"""
ingest_ontology_examples.py — Ingest ontology demo records to OSDU instances.

Targets:
  - interop: Drogon DG1 only (public demo)
  - eqndev:  Drogon DG1 + DG2 + Omegas (confidential)

Verifies relationship consistency after ingestion.
"""
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

import httpx

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "demo"))
from _auth import get_token, load_instance  # noqa: E402

# ── Record directories ──
DROGON_DIR = REPO_ROOT / "demo" / "drogon_dg1" / "ontology_examples"
OMEGAS_DIR = REPO_ROOT / "demo" / "eqn" / "omegas" / "ontology_examples"

# ── DG1-only records (interop + eqndev) ──
DG1_RECORDS = [
    "dg1_business_decision.json",
]

# ── DG1 + DG2 records (eqndev + interop) ──
DG12_RECORDS = [
    "dg1_business_decision.json",
    "dg2_business_decision.json",
    "cp_full_dg1_to_dg2.json",
    "activity_collaboration_action.json",
]

# ── Omegas records (eqndev only) ──
OMEGAS_RECORDS = [
    "bd_omegas_ssvp.json",
    "cp_omegas_ssvp.json",
    "gls_omegas_ssvp.json",
]


def _rewrite_partition(obj: Any, src: str, dst: str) -> Any:
    """Recursively rewrite partition prefix in all string values (IDs, refs)."""
    if isinstance(obj, str):
        if obj.startswith(f"{src}:"):
            return f"{dst}:{obj[len(src)+1:]}"
        return obj
    if isinstance(obj, list):
        return [_rewrite_partition(item, src, dst) for item in obj]
    if isinstance(obj, dict):
        return {k: _rewrite_partition(v, src, dst) for k, v in obj.items()}
    return obj


def load_record(path: Path, partition: str) -> Any:
    """Load a JSON record and adapt ACL/legal/IDs for the target partition.
    Returns a single record dict OR a list of records (for manifest files)."""
    rec = json.loads(path.read_text("utf-8"))
    # Remove _comment field (not OSDU-valid)
    rec.pop("_comment", None)

    # Handle manifest-wrapped records (extract inner records)
    if rec.get("kind") == "osdu:wks:Manifest:1.0.0":
        inner: List[Dict[str, Any]] = []
        data = rec.get("Data", {})
        for section in ["WorkProductComponents", "MasterData", "Datasets", "ReferenceData"]:
            for r in data.get(section, []):
                r.pop("_comment", None)
                inner.append(r)
        for r in rec.get("MasterData", []):
            r.pop("_comment", None)
            inner.append(r)
        for r in rec.get("ReferenceData", []):
            r.pop("_comment", None)
            inner.append(r)
        # Rewrite partition and set ACL/legal for each inner record
        results = []
        for r in inner:
            if partition != "dev":
                r = _rewrite_partition(r, "dev", partition)
            r["acl"] = _acl_for(partition)
            r["legal"] = _legal_for(partition)
            results.append(r)
        return results

    # Single record
    if partition != "dev":
        rec = _rewrite_partition(rec, "dev", partition)
    rec["acl"] = _acl_for(partition)
    rec["legal"] = _legal_for(partition)
    return rec


def _acl_for(partition: str) -> Dict[str, Any]:
    if partition == "opendes":
        return {
            "owners": ["data.default.owners@opendes.dataservices.energy"],
            "viewers": ["data.default.viewers@opendes.dataservices.energy"],
        }
    return {
        "owners": ["data.default.owners@dev.dataservices.energy"],
        "viewers": ["data.office.global.viewers@dev.dataservices.energy"],
    }


def _legal_for(partition: str) -> Dict[str, Any]:
    if partition == "opendes":
        return {"legaltags": ["opendes-public-norway"], "otherRelevantDataCountries": ["NO"]}
    return {"legaltags": ["dev-equinor-private-default"], "otherRelevantDataCountries": ["NO"]}


def ingest_records(
    records: List[Dict[str, Any]],
    host: str,
    partition: str,
    token: str,
    label: str,
) -> tuple[int, int, List[str]]:
    """PUT records to Storage API. Returns (created, skipped, errors)."""
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
            # Handle list (from manifest unwrapping) — each item is one record
            batch = rec if isinstance(rec, list) else [rec]
            for single in batch:
                rid = single.get("id", "?")
                short = rid.split(":")[-1][:40] if ":" in rid else rid[:40]

                url = f"{host}/api/storage/v2/records"
                try:
                    r = client.put(url, json=[single])
                    if r.is_success:
                        resp = r.json()
                        c = len(resp.get("recordIds", []))
                        s = len(resp.get("skippedRecordIds", []))
                        created += c
                        skipped += s
                        tag = "✓" if c else "○"
                        print(f"  {tag} {short}")
                    else:
                        errors.append(f"{short}: HTTP {r.status_code} - {r.text[:200]}")
                        print(f"  ✗ {short}: {r.status_code} {r.text[:100]}")
                except Exception as e:
                    errors.append(f"{short}: {e}")
                    print(f"  ✗ {short}: {e}")

                time.sleep(1)  # allow indexing

    print(f"  [{label}] created={created} skipped={skipped} errors={len(errors)}")
    return created, skipped, errors


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
        "Content-Type": "application/json",
    }
    # Collect all referenced IDs from Parameters[].DataObjectParameter, RiskIDs, etc.
    referenced: set = set()
    record_ids: set = set()
    for rec in records:
        if isinstance(rec, list):
            for r in rec:
                _collect_refs(r, referenced, record_ids)
        else:
            _collect_refs(rec, referenced, record_ids)

    # Only check external references (not in our own batch)
    external = referenced - record_ids
    if not external:
        print("  All references are self-contained in this batch.")
        return []

    print(f"  Checking {len(external)} external references …")
    missing: List[str] = []
    with httpx.Client(headers=headers, timeout=30) as client:
        for rid in sorted(external):
            try:
                r = client.get(f"{host}/api/storage/v2/records/{rid}")
                if r.status_code == 404:
                    missing.append(rid)
                    print(f"    ⚠ MISSING: {rid.split(':')[-1][:50]}")
            except Exception:
                pass  # network errors are not relationship errors

    if not missing:
        print("  ✓ All external references resolved.")
    else:
        print(f"  ⚠ {len(missing)} references not found (may need prior ingestion).")
    return missing


def _collect_refs(rec: Dict[str, Any], refs: set, ids: set):
    """Extract all SRN references from a record."""
    rid = rec.get("id", "")
    if rid:
        ids.add(rid)
    data = rec.get("data", {})
    # Parameters
    for p in data.get("Parameters", []):
        if isinstance(p, dict):
            dop = p.get("DataObjectParameter", "")
            if dop and ":" in dop:
                refs.add(dop)
    # RiskIDs
    for r in data.get("RiskIDs", []):
        if isinstance(r, str) and ":" in r:
            refs.add(r)
    # PriorActivityIDs
    for a in data.get("PriorActivityIDs", []):
        if isinstance(a, str) and ":" in a:
            refs.add(a)
    # ParentProjectID
    pp = data.get("ParentProjectID", "")
    if pp and ":" in pp:
        refs.add(pp)
    # TrustedCollectionID
    tc = data.get("TrustedCollectionID", "")
    if tc and ":" in tc:
        refs.add(tc)
    # Ancestry
    for parent in (data.get("ancestry", {}) or {}).get("parents", []):
        if isinstance(parent, str) and ":" in parent:
            refs.add(parent)
    # CollaborationProjectID
    cp = data.get("CollaborationProjectID", "")
    if cp and ":" in cp:
        refs.add(cp)


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--target", choices=["interop", "eqndev", "both"], default="both")
    ap.add_argument("--verify-only", action="store_true")
    args = ap.parse_args()

    # ═══ INTEROP: Drogon DG1+DG2 ═══
    if args.target in ("interop", "both"):
        print("\n══════════════════════════════════════════════")
        print("  TARGET: interop (Drogon DG1+DG2)")
        print("══════════════════════════════════════════════")
        inst = load_instance("interop")
        token = get_token("interop")
        records = []
        for fname in DG12_RECORDS:
            rec = load_record(DROGON_DIR / fname, inst["partition"])
            records.append(rec)
        print(f"  Loaded {len(records)} records")

        if not args.dry_run and not args.verify_only:
            ingest_records(records, inst["host"], inst["partition"], token, "interop-dg12")

        print("\n  Verifying relationships …")
        flat = [r for rec in records for r in (rec if isinstance(rec, list) else [rec])]
        verify_relationships(flat, inst["host"], inst["partition"], token)

    # ═══ EQNDEV: Drogon DG1+DG2 + Omegas ═══
    if args.target in ("eqndev", "both"):
        print("\n══════════════════════════════════════════════")
        print("  TARGET: eqndev (Drogon DG1+DG2 + Omegas)")
        print("══════════════════════════════════════════════")
        inst = load_instance("eqndev")
        token = get_token("eqndev")

        # Drogon records
        drogon_records = []
        for fname in DG12_RECORDS:
            rec = load_record(DROGON_DIR / fname, inst["partition"])
            drogon_records.append(rec)

        # Omegas records
        omegas_records = []
        for fname in OMEGAS_RECORDS:
            rec = load_record(OMEGAS_DIR / fname, inst["partition"])
            omegas_records.append(rec)

        all_records = drogon_records + omegas_records
        print(f"  Loaded {len(drogon_records)} Drogon + {len(omegas_records)} Omegas records")

        if not args.dry_run and not args.verify_only:
            print("\n  Ingesting Drogon DG1+DG2 …")
            ingest_records(drogon_records, inst["host"], inst["partition"], token, "eqndev-drogon")
            print("\n  Ingesting Omegas SSVP …")
            ingest_records(omegas_records, inst["host"], inst["partition"], token, "eqndev-omegas")

        print("\n  Verifying relationships (Drogon) …")
        flat_d = [r for rec in drogon_records for r in (rec if isinstance(rec, list) else [rec])]
        verify_relationships(flat_d, inst["host"], inst["partition"], token)

        print("\n  Verifying relationships (Omegas) …")
        flat_o = [r for rec in omegas_records for r in (rec if isinstance(rec, list) else [rec])]
        verify_relationships(flat_o, inst["host"], inst["partition"], token)

    print("\n✓ Done.")


if __name__ == "__main__":
    main()
