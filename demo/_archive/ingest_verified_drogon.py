#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ingest_verified_drogon.py - Ingest Drogon manifests one-by-one via the OSDU
Workflow API, **verifying** before and after each step:

  1. PRE-CHECK  - all cross-manifest referenced IDs already exist in Storage
  2. SUBMIT     - POST manifest to Workflow API
  3. POST-CHECK - every record in the manifest is retrievable via Storage GET

Stops on the first failure so you can fix before continuing.

Usage:
  py demo/drogon/ingest_verified_drogon.py
  py demo/drogon/ingest_verified_drogon.py --start 2          # skip first 2
  py demo/drogon/ingest_verified_drogon.py --dry-run           # verify refs only
  py demo/drogon/ingest_verified_drogon.py --verify-only       # check existing records
"""

import argparse
import json
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import httpx

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT  = SCRIPT_DIR.parent.parent

# ── Manifest ingestion order ────────────────────────────────────────────
DEFAULT_MANIFESTS = [
    "reftypes_associatedliquid.json",       # 0. new ref value (no deps)
    "manifest_masterwp_drogon.json",        # 1. Reservoir + Segments + WP
    "manifest_wpcraw_drogon.json",          # 2. RAW WPC -> refs Reservoir & WP
    "manifest_wpcstat_drogon.json",         # 3. STAT WPC -> refs Reservoir & WP
    "manifest_risk_drogon.json",            # 4. Risk (no ancestry deps)
    "manifest_devconcept_drogon.json",      # 5. DevelopmentConcept WPC -> refs Reservoir
    "manifest_bd_drogon.json",              # 6. BusinessDecision
    "manifest_cp_drogon.json",              # 7. CollaborationProject + Collection
    "manifest_wells_drogon.json",           # 8. Well + Wellbore master-data (Drogon + Volve)
    "manifest_litho_strat_drogon.json",     # 9. StratColumn + Rank + Unit interpretations
    "manifest_markers_drogon.json",         # 10. WellboreMarkerSet (formation tops per wellbore)
]


# ═══════════════ Auth & env (via central _auth module) ═════════════════
import sys as _sys
_sys.path.insert(0, str(REPO_ROOT / "demo"))
from _auth import load_env, mint_from_env as get_access_token  # noqa: E402


# ═══════════════ Storage API helpers ════════════════════════════════════
_record_cache: Dict[str, bool] = {}     # id → exists


def record_exists(client: httpx.Client, env: Dict[str, str], record_id: str) -> bool:
    """Check if a record exists in OSDU via Storage GET (with cache)."""
    if record_id in _record_cache:
        return _record_cache[record_id]

    # Use the record ID as-is (the :1 suffix is part of the ID, NOT a version).
    url = f"{env['host']}/api/storage/v2/records/{record_id}"
    try:
        r = client.get(url, timeout=30)
        found = r.status_code == 200
    except httpx.TimeoutException:
        found = False

    _record_cache[record_id] = found
    return found


def record_get(client: httpx.Client, env: Dict[str, str], record_id: str) -> Optional[Dict]:
    """GET a record from Storage. Returns parsed JSON or None."""
    url = f"{env['host']}/api/storage/v2/records/{record_id}"
    try:
        r = client.get(url, timeout=30)
        if r.is_success:
            return r.json()
    except httpx.TimeoutException:
        pass
    return None


# ═══════════════ Reference extraction ═══════════════════════════════════
def _is_osdu_id(s: str) -> bool:
    """Rough check: looks like  dev:kind--Entity:something  or similar."""
    return isinstance(s, str) and ":" in s and "--" in s


def _walk_refs(obj: Any, refs: Set[str], exclude_self: Set[str]) -> None:
    """Recursively collect all OSDU reference IDs from a JSON object."""
    if isinstance(obj, str):
        if _is_osdu_id(obj) and obj not in exclude_self:
            refs.add(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            _walk_refs(v, refs, exclude_self)
    elif isinstance(obj, list):
        for v in obj:
            _walk_refs(v, refs, exclude_self)


def extract_records(manifest: Dict) -> List[Dict]:
    """All record objects inside a manifest envelope."""
    records: List[Dict] = []
    for grp in ("ReferenceData", "MasterData"):
        for r in manifest.get(grp, []):
            if isinstance(r, dict) and "data" in r:
                records.append(r)
    data = manifest.get("Data", {})
    for grp in ("WorkProductComponents", "WorkProducts"):
        for r in data.get(grp, []):
            if isinstance(r, dict) and "data" in r:
                records.append(r)
    wp = data.get("WorkProduct")
    if isinstance(wp, dict) and wp.get("data"):
        records.append(wp)
    return records


def manifest_self_ids(manifest: Dict) -> Set[str]:
    """Record IDs declared *inside* this manifest (they don't need to pre-exist)."""
    ids: Set[str] = set()
    for rec in extract_records(manifest):
        rid = rec.get("id", "")
        if rid:
            ids.add(rid)
    return ids


def manifest_external_refs(manifest: Dict) -> Set[str]:
    """
    All OSDU IDs referenced inside the manifest EXCEPT those defined
    in the same manifest.  Also excludes well-known schema kinds and
    standard reference-data IDs (PropertyType, UoM, FacetType, etc.)
    which are ingested separately.
    """
    self_ids = manifest_self_ids(manifest)

    # Collect all referenced IDs
    all_refs: Set[str] = set()
    for rec in extract_records(manifest):
        data = rec.get("data", {})
        # ancestry parents & children
        ancestry = data.get("ancestry", {})
        for pid in ancestry.get("parents", []):
            if _is_osdu_id(pid):
                all_refs.add(pid)
        for cid in ancestry.get("children", []):
            if _is_osdu_id(cid):
                all_refs.add(cid)
        # ParentObjectID, ParentWorkProductID
        for key in ("ParentObjectID", "ParentWorkProductID"):
            val = data.get(key, "")
            if _is_osdu_id(val):
                all_refs.add(val)

    # Subtract self-defined IDs
    external = all_refs - self_ids

    return external


# ═══════════════ Workflow API ═══════════════════════════════════════════
WORKFLOW_ID = "Osdu_ingest"


def wf_submit(client: httpx.Client, env: Dict[str, str],
              manifest: Dict) -> str:
    cid = str(uuid.uuid4())
    url = f"{env['host']}/api/workflow/v1/workflow/{WORKFLOW_ID}/workflowRun"
    payload = {
        "executionContext": {
            "Payload": {
                "AppKey": "ingest_verified_drogon.py",
                "data-partition-id": env["partition"],
            },
            "manifest": manifest,
        }
    }
    r = client.post(
        url,
        content=json.dumps(payload),
        headers={"Content-Type": "application/json", "x-correlation-id": cid},
        timeout=120,
    )
    if not r.is_success:
        raise RuntimeError(f"Workflow submit failed ({r.status_code}): {r.text[:800]}")
    body = r.json()
    run_id = str(body.get("runId") or body.get("id") or "")
    if not run_id:
        raise RuntimeError(f"No runId in response: {json.dumps(body)[:500]}")
    return run_id


def wf_poll(client: httpx.Client, env: Dict[str, str], run_id: str,
            poll_interval: float = 10.0, max_wait: float = 180.0) -> Dict:
    paths = [
        f"/api/workflow/v1/workflow/{WORKFLOW_ID}/workflowRun/{run_id}",
        f"/api/workflow/v1/workflowRun/{run_id}",
    ]
    terminal = {"completed", "succeeded", "failed", "error", "cancelled", "finished"}
    start = time.time()
    last_obj: Dict = {}
    attempt = 0

    while True:
        attempt += 1
        for p in paths:
            try:
                r = client.get(f"{env['host']}{p}", timeout=60)
                if r.is_success:
                    last_obj = r.json()
                    status = str(
                        last_obj.get("status") or
                        last_obj.get("workflowRunStatus") or
                        last_obj.get("state") or ""
                    ).lower()
                    if status:
                        print(f"      [{attempt}] status={status} ({int(time.time()-start)}s)")
                    if status in terminal:
                        return last_obj
                    break
            except httpx.TimeoutException:
                pass

        if time.time() - start > max_wait:
            print(f"      Polling timed out after {int(max_wait)}s")
            return last_obj
        time.sleep(poll_interval)


def wf_status(run_obj: Dict) -> str:
    return str(run_obj.get("status") or run_obj.get("workflowRunStatus") or "").lower()


# ═══════════════ Main ═══════════════════════════════════════════════════
def main():
    ap = argparse.ArgumentParser(
        description="Verified ingest of Drogon manifests via OSDU Workflow API")
    ap.add_argument("--env-file", action="append", default=[])
    ap.add_argument("--dry-run", action="store_true",
                    help="Pre-check refs only, don't submit")
    ap.add_argument("--verify-only", action="store_true",
                    help="Check which records already exist - no ingestion")
    ap.add_argument("--start", type=int, default=0,
                    help="Skip first N manifests (already ingested)")
    ap.add_argument("--poll-interval", type=float, default=10)
    ap.add_argument("--max-wait", type=float, default=180)
    ap.add_argument("manifests", nargs="*")
    args = ap.parse_args()

    env_files = args.env_file or [str(REPO_ROOT / ".env")]
    print("Loading env …")
    env = load_env(env_files)
    print(f"  host={env['host']}  partition={env['partition']}")

    # Resolve manifest files
    if args.manifests:
        paths = []
        for m in args.manifests:
            p = Path(m) if Path(m).exists() else SCRIPT_DIR / m
            if not p.exists():
                raise SystemExit(f"Not found: {m}")
            paths.append(p)
    else:
        paths = [SCRIPT_DIR / m for m in DEFAULT_MANIFESTS if (SCRIPT_DIR / m).exists()]

    print(f"\n{len(paths)} manifests in pipeline:")
    for i, p in enumerate(paths):
        tag = "  [skip]" if i < args.start else ""
        print(f"  {i}. {p.name}{tag}")

    # Load all manifests
    manifests: List[Tuple[Path, Dict]] = []
    for p in paths:
        manifests.append((p, json.loads(p.read_text(encoding="utf-8"))))

    # Auth
    print("\nAuthenticating …")
    token = get_access_token(env)
    headers = {
        "Authorization":     f"Bearer {token}",
        "data-partition-id": env["partition"],
    }

    ok = 0
    fail = 0

    with httpx.Client(headers=headers) as client:

        # ── verify-only mode ────────────────────────────────────────────
        if args.verify_only:
            print("\n── Verify-only: checking record existence ──")
            for path, manifest in manifests:
                records = extract_records(manifest)
                print(f"\n{path.name} ({len(records)} records):")
                for rec in records:
                    rid = rec.get("id", "?")
                    exists = record_exists(client, env, rid)
                    tag = "✅ exists" if exists else "❌ missing"
                    print(f"  {tag}  {rid[:90]}")
            return

        # ── Step-by-step ingestion ──────────────────────────────────────
        for idx, (path, manifest) in enumerate(manifests):
            if idx < args.start:
                continue

            records = extract_records(manifest)
            record_ids = [r.get("id", "?") for r in records]
            print(f"\n{'='*60}")
            print(f"[{idx}] {path.name}  ({len(records)} records)")

            # ── 1. PRE-CHECK: external references exist ─────────────────
            ext_refs = manifest_external_refs(manifest)
            if ext_refs:
                print(f"  PRE-CHECK: {len(ext_refs)} external references …")
                missing_refs = []
                for ref in sorted(ext_refs):
                    exists = record_exists(client, env, ref)
                    status = "ok" if exists else "MISSING"
                    print(f"    [{status:7s}] {ref[:90]}")
                    if not exists:
                        missing_refs.append(ref)

                if missing_refs:
                    print(f"\n  ❌ PRE-CHECK FAILED - {len(missing_refs)} missing references!")
                    print(f"     Stopping. Fix references before re-running with --start {idx}")
                    fail += 1
                    break
                else:
                    print(f"  ✅ All {len(ext_refs)} external references verified")
            else:
                print(f"  PRE-CHECK: no external references (standalone)")

            if args.dry_run:
                print(f"  [dry-run] Would submit {path.name} - skipping")
                ok += 1
                continue

            # ── 2. SUBMIT via Workflow API ──────────────────────────────
            print(f"  SUBMITTING via Workflow API …")
            try:
                run_id = wf_submit(client, env, manifest)
                print(f"    runId = {run_id}")

                run_obj = wf_poll(client, env, run_id,
                                  poll_interval=args.poll_interval,
                                  max_wait=args.max_wait)
                final = wf_status(run_obj)
                print(f"    Workflow result: {final}")

                if final not in ("completed", "succeeded", "finished"):
                    print(f"  ❌ WORKFLOW FAILED ({final})")
                    print(f"     Response: {json.dumps(run_obj, indent=2)[:2000]}")
                    print(f"     Stopping. Re-run with --start {idx}")
                    fail += 1
                    break

            except Exception as e:
                print(f"  ❌ SUBMIT ERROR: {e}")
                fail += 1
                break

            # ── 3. POST-CHECK: all records exist in Storage ─────────────
            # Wait a moment for eventual consistency
            time.sleep(3)
            print(f"  POST-CHECK: verifying {len(record_ids)} records in Storage …")
            all_ok = True
            for rid in record_ids:
                # Clear cache to get fresh result
                _record_cache.pop(rid, None)
                exists = record_exists(client, env, rid)
                tag = "✅" if exists else "❌ NOT FOUND"
                print(f"    {tag}  {rid[:90]}")
                if not exists:
                    all_ok = False

            if all_ok:
                print(f"  ✅ All {len(record_ids)} records verified in Storage")
                ok += 1
            else:
                print(f"  ⚠️  Some records missing after 'finished' - possible schema issue")
                print(f"     Stopping. Investigate before re-running with --start {idx}")
                fail += 1
                break

            # Brief pause before next manifest
            time.sleep(2)

    print(f"\n{'='*60}")
    print(f"Result: {ok} ok, {fail} failed  (of {len(manifests) - args.start} attempted)")
    sys.exit(0 if fail == 0 else 2)


if __name__ == "__main__":
    main()
