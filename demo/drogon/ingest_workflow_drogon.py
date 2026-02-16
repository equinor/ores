#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ingest_workflow_drogon.py — Ingest Drogon manifests via the OSDU Workflow API
(same approach that succeeded for the GRAND manifests).

Uses httpx (not requests) to avoid the corporate-proxy timeout.

Submits each manifest to POST /api/workflow/v1/workflow/Osdu_ingest/workflowRun,
which processes the manifest atomically — no eventual-consistency race on
ancestry parents.

Usage:
  py demo/drogon/ingest_workflow_drogon.py --env-file .env
  py demo/drogon/ingest_workflow_drogon.py --env-file .env --dry-run
  py demo/drogon/ingest_workflow_drogon.py --env-file .env manifest_wpcraw_drogon.json
"""

import argparse
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent  # ores/

# Manifest ingestion order — dependencies first.
# The Workflow API handles intra-manifest ancestry atomically, but
# cross-manifest references (e.g. WPC → Reservoir) must already exist.
DEFAULT_MANIFESTS = [
    "reftypes_associatedliquid.json",        # 0. reference data (no deps)
    "manifest_masterwp_drogon.json",          # 1. Reservoir + Segments + WorkProduct
    "manifest_wpcraw_drogon.json",            # 2. RAW WPC (refs Reservoir & WP)
    "manifest_wpcstat_drogon.json",           # 3. STAT WPC (refs Reservoir & WP)
    "manifest_risk_drogon.json",              # 4. Risk (no ancestry deps)
    "manifest_bd_drogon.json",                # 5. BusinessDecision (refs Risk & WPC)
]


# ──────────────── .env loader ──────────────── #
def _parse_dotenv(path: Path) -> Dict[str, str]:
    vals: Dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in ('"', "'"):
            v = v[1:-1]
        vals[k] = v
    return vals


def _first(env: Dict[str, str], keys: List[str]) -> Optional[str]:
    for k in keys:
        v = (env.get(k) or "").strip()
        if v:
            return v
    return None


def load_env(paths: List[str]) -> Dict[str, str]:
    merged: Dict[str, str] = {}
    for p in paths:
        fp = Path(p).expanduser().resolve()
        if not fp.exists():
            raise SystemExit(f"env file not found: {p}")
        merged.update(_parse_dotenv(fp))

    env: Dict[str, str] = {}
    env["refresh_token"] = _first(merged, ["refresh_token", "REFRESH_TOKEN"]) or ""
    env["tenant"]        = _first(merged, ["OSDU_TENANT_ID", "AZURE_TENANT_ID"]) or ""
    env["client_id"]     = _first(merged, ["OSDU_CLIENT_ID", "AZURE_CLIENT_ID"]) or ""
    env["scope"]         = _first(merged, ["OSDU_SCOPE", "AZURE_SCOPE"]) or ""
    host                 = _first(merged, ["OSDU_HOST", "OSDU_BASE_URL"]) or ""
    if host and not host.startswith("http"):
        host = "https://" + host.lstrip("/")
    env["host"]          = host
    env["partition"]     = _first(merged, ["OSDU_PARTITION", "DATA_PARTITION_ID"]) or ""

    missing = [k for k in ("refresh_token", "tenant", "client_id", "scope", "host", "partition") if not env[k]]
    if missing:
        raise SystemExit(f"Missing keys in .env: {', '.join(missing)}")
    return env


# ──────────────── Auth (httpx) ──────────────── #
def get_access_token(env: Dict[str, str]) -> str:
    url = f"https://login.microsoftonline.com/{env['tenant']}/oauth2/v2.0/token"
    form = {
        "grant_type":    "refresh_token",
        "client_id":     env["client_id"],
        "refresh_token": env["refresh_token"],
        "scope":         env["scope"],
    }
    r = httpx.post(url, data=form, timeout=30)
    if not r.is_success:
        raise RuntimeError(f"Auth failed ({r.status_code}): {r.text[:600]}")
    data = r.json()
    token = data.get("access_token")
    if not token:
        raise RuntimeError(f"No access_token in response: {list(data.keys())}")
    exp = data.get("expires_in", "?")
    print(f"  token acquired (expires_in={exp}s)")
    return token


# ──────────────── Workflow submit + poll ──────────────── #
WORKFLOW_ID = "Osdu_ingest"


def wf_submit(
    client: httpx.Client,
    env: Dict[str, str],
    manifest: Dict[str, Any],
) -> Tuple[str, Dict[str, Any]]:
    """POST manifest to Workflow API. Returns (runId, response_body)."""
    cid = str(uuid.uuid4())
    url = f"{env['host']}/api/workflow/v1/workflow/{WORKFLOW_ID}/workflowRun"
    payload = {
        "executionContext": {
            "Payload": {
                "AppKey": "ingest_workflow_drogon.py",
                "data-partition-id": env["partition"],
            },
            "manifest": manifest,
        }
    }
    r = client.post(
        url,
        content=json.dumps(payload),
        headers={
            "Content-Type": "application/json",
            "x-correlation-id": cid,
        },
        timeout=120,
    )
    print(f"  [POST {r.status_code}] x-correlation-id={cid}")
    if not r.is_success:
        raise RuntimeError(f"Workflow submit failed ({r.status_code}): {r.text[:800]}")
    body = r.json()
    run_id = str(body.get("runId") or body.get("id") or "")
    if not run_id:
        raise RuntimeError(f"Workflow submit returned no runId: {json.dumps(body)[:500]}")
    return run_id, body


def wf_poll(
    client: httpx.Client,
    env: Dict[str, str],
    run_id: str,
    poll_interval: float = 10.0,
    max_wait: float = 120.0,
) -> Dict[str, Any]:
    """Poll workflow run until terminal state."""
    paths = [
        f"/api/workflow/v1/workflow/{WORKFLOW_ID}/workflowRun/{run_id}",
        f"/api/workflow/v1/workflowRun/{run_id}",
    ]
    terminal = {"completed", "succeeded", "failed", "error", "cancelled", "finished"}
    start = time.time()
    attempt = 0
    last_obj: Dict[str, Any] = {}

    while True:
        attempt += 1
        for p in paths:
            url = f"{env['host']}{p}"
            try:
                r = client.get(url, timeout=60)
                if r.is_success:
                    obj = r.json()
                    last_obj = obj
                    status = str(
                        obj.get("status")
                        or obj.get("workflowRunStatus")
                        or obj.get("overallStatus")
                        or obj.get("state")
                        or ""
                    ).lower()
                    if status:
                        elapsed = int(time.time() - start)
                        print(f"    [{attempt}] status={status} ({elapsed}s)")
                    if status in terminal:
                        return last_obj
                    break  # got a response, wait before next poll
            except httpx.TimeoutException:
                pass

        if time.time() - start > max_wait:
            print(f"    Polling timed out after {int(max_wait)}s")
            return last_obj
        time.sleep(poll_interval)


def print_summary(run_obj: Dict[str, Any]) -> None:
    """Parse workflow outputs for per-record status."""
    if not run_obj:
        return
    status = str(
        run_obj.get("status")
        or run_obj.get("workflowRunStatus")
        or ""
    ).lower()

    # Try to find record-level details in outputs
    def walk(x):
        if isinstance(x, dict):
            yield x
            for v in x.values():
                yield from walk(v)
        elif isinstance(x, list):
            for it in x:
                yield from walk(it)

    rows = []
    for key in ("outputs", "output", "result", "results", "payload", "data"):
        v = run_obj.get(key)
        if isinstance(v, (dict, list)):
            for node in walk(v):
                if not isinstance(node, dict):
                    continue
                rid = node.get("id") or node.get("recordId") or node.get("record_id")
                st = node.get("status") or node.get("result") or node.get("outcome")
                msg = node.get("message") or node.get("error") or node.get("reason")
                if rid and st:
                    rows.append((str(rid)[:80], str(st), str(msg)[:200] if msg else ""))

    if rows:
        created = sum(1 for _, s, _ in rows if "creat" in s.lower())
        updated = sum(1 for _, s, _ in rows if "updat" in s.lower())
        failed  = sum(1 for _, s, _ in rows if "fail" in s.lower() or s.lower() == "error")
        print(f"    records: {len(rows)} (created={created} updated={updated} failed={failed})")
        for rid, st, msg in rows:
            line = f"      {st:10s} {rid}"
            if msg:
                line += f"  — {msg}"
            print(line)
    else:
        print(f"    (no per-record details in workflow outputs; overall={status})")


# ──────────────── Main ──────────────── #
def main():
    ap = argparse.ArgumentParser(
        description="Ingest Drogon manifests via OSDU Workflow API (httpx)")
    ap.add_argument("--env-file", action="append", default=[],
                    help=".env file(s) with auth credentials")
    ap.add_argument("--dry-run", action="store_true",
                    help="Load manifests and validate — don't submit")
    ap.add_argument("--poll-interval", type=float, default=10,
                    help="Seconds between poll requests (default 10)")
    ap.add_argument("--max-wait", type=float, default=120,
                    help="Max seconds to wait per manifest (default 120)")
    ap.add_argument("--sleep", type=float, default=2,
                    help="Seconds between manifests (default 2)")
    ap.add_argument("manifests", nargs="*",
                    help="Specific manifest files to ingest (default: all in order)")
    args = ap.parse_args()

    env_files = args.env_file or [str(REPO_ROOT / ".env")]

    print("Loading env …")
    env = load_env(env_files)
    print(f"  host={env['host']}  partition={env['partition']}")

    # Resolve manifest files
    if args.manifests:
        manifest_paths = []
        for m in args.manifests:
            p = Path(m)
            if not p.exists():
                p = SCRIPT_DIR / m
            if not p.exists():
                raise SystemExit(f"Manifest not found: {m}")
            manifest_paths.append(p)
    else:
        manifest_paths = [SCRIPT_DIR / m for m in DEFAULT_MANIFESTS]
        manifest_paths = [p for p in manifest_paths if p.exists()]

    print(f"\nManifests to ingest ({len(manifest_paths)}):")
    for p in manifest_paths:
        print(f"  {p.name}")

    # Load and validate
    manifests: List[Tuple[Path, Dict[str, Any]]] = []
    for p in manifest_paths:
        data = json.loads(p.read_text(encoding="utf-8"))
        kind = data.get("kind", "")
        if kind != "osdu:wks:Manifest:1.0.0":
            print(f"  ⚠  {p.name}: unexpected kind={kind}")
        manifests.append((p, data))
    print(f"\n{len(manifests)} manifests loaded and validated")

    if args.dry_run:
        print("\n[dry-run] Would submit these manifests — exiting.")
        return

    print("\nAuthenticating …")
    token = get_access_token(env)

    headers = {
        "Authorization":     f"Bearer {token}",
        "data-partition-id": env["partition"],
    }

    ok_count = 0
    fail_count = 0

    print(f"\nIngesting {len(manifests)} manifests via Workflow API …\n")
    with httpx.Client(headers=headers) as client:
        for i, (path, manifest) in enumerate(manifests):
            print(f"[{i+1}/{len(manifests)}] {path.name}")
            try:
                run_id, _ = wf_submit(client, env, manifest)
                print(f"    runId={run_id}")
                run_obj = wf_poll(
                    client, env, run_id,
                    poll_interval=args.poll_interval,
                    max_wait=args.max_wait,
                )
                print_summary(run_obj)
                final_status = str(
                    run_obj.get("status")
                    or run_obj.get("workflowRunStatus")
                    or ""
                ).lower()
                if final_status in ("completed", "succeeded", "finished"):
                    ok_count += 1
                    print(f"    ✅ {final_status}")
                else:
                    fail_count += 1
                    print(f"    ❌ {final_status}")
                    # Print full run object for debugging
                    print(f"    Full response: {json.dumps(run_obj, indent=2)[:3000]}")
            except Exception as e:
                fail_count += 1
                print(f"    ❌ ERROR: {e}")

            if i < len(manifests) - 1:
                time.sleep(args.sleep)

    print(f"\n{'='*50}")
    print(f"Done: {ok_count} ok, {fail_count} failed")
    sys.exit(0 if fail_count == 0 else 2)


if __name__ == "__main__":
    main()
