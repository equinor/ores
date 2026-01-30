#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
4ingest.py (Polling edition)
Ingest OSDU manifests using a refresh_token (no external CLI required).
Now with Workflow run polling (Azure run-log equivalent) and verbose results.

Behavior
--------
- Auth: exchanges refresh_token -> access_token (AAD v2 first, v1 fallback).
- Modes:
  * workflow (default): POST /api/workflow/v1/workflow/Osdu_ingest/workflowRun
    Then POLL runId until terminal state, fetch logs, and print an ingest summary.
  * legacy: POST /api/osdu/v3/ingest/manifest (synchronous ingest).
- Files:
  * If you pass files on the CLI, they are ingested in order.
  * If none provided, it tries reference_statistics_bundle.json first (if present),
    then all "*manifest.json" in the current folder.

Environment variables
---------------------
 refresh_token = <your refresh token> [REQUIRED]

Optional overrides (defaults shown):


Notes
-----
- Refresh tokens are bound to a combination of user + client (app). Redeem with the same client_id that obtained it.  # see docs
- Including redirect_uri in the v2 refresh request is optional but safe and can prevent edge cases.                 # see docs
"""

import argparse
import base64
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests


# ------------------------------- helpers ------------------------------------
def getenv(name: str, default: Optional[str] = None) -> Optional[str]:
    v = os.environ.get(name)
    if v is None:
        return default
    v = v.strip()
    return v if v else default


def get_access_token_from_refresh_token(
    refresh_token: str,
    tenant_id: str,
    client_id: str,
    authority_base: str,
    scope_v2: Optional[str],
    resource_v1: Optional[str],
    redirect_uri_v2: Optional[str] = None,
    timeout: int = 20,
) -> Tuple[str, int]:
    """
    Try AAD v2 (oauth2/v2.0/token) with scope, then fall back to v1 (oauth2/token) with resource.
    Returns: (access_token, expires_in_seconds)
    Raises: RuntimeError on failure.
    """
    if not refresh_token:
        raise RuntimeError("Missing refresh_token")

    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/x-www-form-urlencoded"})

    # Attempt v2 first
    if scope_v2:
        v2_url = f"{authority_base.rstrip('/')}/{tenant_id}/oauth2/v2.0/token"
        v2_form = {
            "grant_type": "refresh_token",
            "client_id": client_id,
            "refresh_token": refresh_token,
            "scope": scope_v2,  # e.g., "<API_APP_ID>/.default openid profile offline_access"
        }
        if redirect_uri_v2:
            # Align with the redirect used to obtain the token (optional but safe)
            v2_form["redirect_uri"] = redirect_uri_v2
        try:
            r = sess.post(v2_url, data=v2_form, timeout=timeout)
            if r.ok:
                data = r.json()
                if "access_token" in data:
                    return data["access_token"], int(data.get("expires_in", 3600))
                else:
                    print(f"[auth v2] {r.status_code}: {r.text[:800]}")
            else:
                print(f"[auth v2] {r.status_code}: {r.text[:800]}")
        except requests.RequestException as e:
            print(f"[auth v2] request error: {e}")

    # Fallback to v1 only if a valid resource is provided
    if resource_v1:
        v1_url = f"{authority_base.rstrip('/')}/{tenant_id}/oauth2/token"
        v1_form = {
            "grant_type": "refresh_token",
            "client_id": client_id,
            "refresh_token": refresh_token,
            "resource": resource_v1,  # Must be the API App ID URI or GUID, NOT a redirect URI
        }
        try:
            r = sess.post(v1_url, data=v1_form, timeout=timeout)
            if r.ok:
                data = r.json()
                if "access_token" in data:
                    return data["access_token"], int(data.get("expires_in", 3600))
                raise RuntimeError(f"Token endpoint returned no access_token. Body: {data}")
            raise RuntimeError(f"Token request failed: {r.status_code} {r.text}")
        except requests.RequestException as e:
            raise RuntimeError(f"Token request error: {e}") from e

    raise RuntimeError(
        "Unable to obtain access_token via v2 or v1 token endpoints. "
        "Verify client/tenant and OSDU_SCOPE/OSDU_RESOURCE."
    )


def _peek_jwt(jwt_token: str) -> None:
    """Print a minimal peek of JWT payload fields (aud, azp, exp) for debugging."""
    try:
        parts = jwt_token.split(".")
        if len(parts) >= 2:
            payload = parts[1] + "==="
            payload_json = json.loads(base64.urlsafe_b64decode(payload.encode()))
            aud = payload_json.get("aud")
            azp = payload_json.get("azp")
            exp = payload_json.get("exp")
            print(f"Token audience (aud): {aud}\n authorized party (azp): {azp}\n exp: {exp}")
    except Exception:
        pass


def _requests_session() -> requests.Session:
    """
    Create a requests session. If HTTPS proxy is defined via env (HTTPS_PROXY/https_proxy),
    requests will honor it automatically. No special proxy handling needed otherwise.
    """
    s = requests.Session()
    s.headers.update({"Accept": "application/json"})
    return s


# ---------------------------- workflow helpers ------------------------------
def _wf_submit(
    sess: requests.Session,
    host: str,
    partition: str,
    token: str,
    manifest_json: Dict[str, Any],
    workflow_id: str = "Osdu_ingest",
) -> Tuple[str, Dict[str, Any]]:
    """
    Submit a workflow run. Returns (run_id, submit_response_json).
    """
    cid = str(uuid.uuid4())
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "data-partition-id": partition,
        "x-correlation-id": cid,
    }
    url = f"{host.rstrip('/')}/api/workflow/v1/workflow/{workflow_id}/workflowRun"
    payload = {
        "executionContext": {
            "Payload": {"AppKey": "ingest.py", "data-partition-id": partition},
            "manifest": manifest_json,
        }
    }
    resp = sess.post(url, headers=headers, data=json.dumps(payload), timeout=120)
    ok = resp.ok
    print(f"[POST {resp.status_code}] submit -> {url} (x-correlation-id={cid})")
    try:
        rh = {k: v for (k, v) in resp.headers.items()}
        print(f"Response headers: {json.dumps(rh, indent=2)[:2000]}")
    except Exception:
        pass
    try:
        body = resp.json()
    except Exception:
        body = {"raw": (resp.text or "")[:4000]}
    print(json.dumps(body, indent=2)[:4000])
    if not ok:
        raise RuntimeError(f"Workflow submit failed: {resp.status_code} {resp.text[:500]}")
    run_id = str(body.get("runId") or body.get("id") or "")
    if not run_id:
        raise RuntimeError("Workflow submit returned no runId.")
    return run_id, body


def _wf_get(sess: requests.Session, host: str, partition: str, token: str, url_path: str) -> Optional[Dict[str, Any]]:
    headers = {
        "Authorization": f"Bearer {token}",
        "data-partition-id": partition,
    }
    url = f"{host.rstrip('/')}{url_path}"
    try:
        r = sess.get(url, headers=headers, timeout=60)
        if r.ok:
            return r.json()
        else:
            # print soft errors for diagnostics
            print(f"[GET {r.status_code}] {url_path} -> {r.text[:400]}")
            return None
    except requests.RequestException as e:
        print(f"[GET error] {url_path}: {e}")
        return None


def _wf_poll_until_done(
    sess: requests.Session,
    host: str,
    partition: str,
    token: str,
    workflow_id: str,
    run_id: str,
    poll_interval: float,
    max_wait: float,
    verbose_logs: bool = True,
) -> Dict[str, Any]:
    """
    Poll the workflow run using a few possible routes until terminal state.
    Returns the best JSON we got for the run (may include outputs/errors).
    """
    start = time.time()
    attempts = 0
    last_obj: Dict[str, Any] = {}

    # Possible status endpoints (clusters vary)
    paths = [
        f"/api/workflow/v1/workflow/{workflow_id}/workflowRun/{run_id}",          # full run object
        f"/api/workflow/v1/workflowRun/{run_id}",                                 # alt root
        f"/api/workflow/v1/workflow/{workflow_id}/workflowRun/{run_id}/status",   # status-only
    ]
    terminal = {"completed", "succeeded", "failed", "error", "cancelled"}
    print(f"Polling workflow runId={run_id} ...")

    while True:
        attempts += 1
        for p in paths:
            obj = _wf_get(sess, host, partition, token, p)
            if obj:
                last_obj = obj
                # Try to read a status in a variety of shapes
                status = str(
                    obj.get("status")
                    or obj.get("workflowRunStatus")
                    or obj.get("overallStatus")
                    or obj.get("state")
                    or ""
                ).lower()
                if status:
                    print(f"[{attempts}] status={status}")
                else:
                    print(f"[{attempts}] status: <unavailable> (path {p})")
                if status in terminal:
                    # Optionally fetch logs
                    if verbose_logs:
                        logs_paths = [
                            f"/api/workflow/v1/workflow/{workflow_id}/workflowRun/{run_id}/logs",
                            f"/api/workflow/v1/workflowRun/{run_id}/logs",
                        ]
                        for lp in logs_paths:
                            logs = _wf_get(sess, host, partition, token, lp)
                            if logs:
                                print("\n=== Workflow Logs (truncated) ===")
                                try:
                                    print(json.dumps(logs, indent=2)[:6000])
                                except Exception:
                                    print(str(logs)[:6000])
                                break
                    return last_obj

        if time.time() - start > max_wait:
            print(f"Polling timed out after ~{int(max_wait)} seconds.")
            return last_obj
        time.sleep(max(0.2, poll_interval))


def _try_print_ingest_summary(run_obj: Dict[str, Any]) -> None:
    """
    Best-effort parse of workflow outputs to print a per-record ingest summary.
    Different pipelines produce different shapes; we scan for likely keys.
    """
    if not run_obj:
        return

    # Heuristics over common fields
    candidates: List[Any] = []
    for k in ("outputs", "output", "result", "results", "payload", "data"):
        v = run_obj.get(k)
        if isinstance(v, (dict, list)):
            candidates.append(v)

    def walk(x):
        if isinstance(x, dict):
            yield x
            for v in x.values():
                yield from walk(v)
        elif isinstance(x, list):
            for it in x:
                yield from walk(it)

    # Scan for per-record entries
    rows = []
    for cand in candidates:
        for node in walk(cand):
            if not isinstance(node, dict):
                continue
            # Common shapes:
            # { "id": "data:...", "status": "created\nupdated\nfailed", "message": "...", "error": "..." }
            rid = node.get("id") or node.get("recordId") or node.get("record_id")
            st = node.get("status") or node.get("result") or node.get("outcome")
            msg = node.get("message") or node.get("error") or node.get("reason") or node.get("details")
            if rid and st:
                rows.append((str(rid), str(st), (str(msg) if msg is not None else "")))

    if rows:
        print("\n=== Ingestion Check Summary (from workflow outputs) ===")
        created = sum(1 for _, s, _ in rows if s.lower().startswith("creat"))
        updated = sum(1 for _, s, _ in rows if s.lower().startswith("updat"))
        failed = sum(1 for _, s, _ in rows if s.lower().startswith("fail") or s.lower() == "error")
        print(f"Total: {len(rows)} created={created} updated={updated} failed={failed}")
        for rid, st, msg in rows[:200]:  # truncate long lists
            line = f" - {rid} -> {st}"
            if msg:
                line += f" ({msg[:200]})"
            print(line)
    else:
        print("\n(No per-record ingestion details were found in workflow outputs.)")


# ------------------------------ legacy ingest -------------------------------
def _legacy_ingest(
    sess: requests.Session,
    host: str,
    partition: str,
    token: str,
    manifest_json: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Direct manifest ingest (synchronous): POST /api/osdu/v3/ingest/manifest
    Returns response JSON.
    """
    cid = str(uuid.uuid4())
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "data-partition-id": partition,
        "x-correlation-id": cid,
    }
    url = f"{host.rstrip('/')}/api/osdu/v3/ingest/manifest"
    resp = sess.post(url, headers=headers, data=json.dumps(manifest_json), timeout=300)
    print(f"[POST {resp.status_code}] legacy ingest -> {url} (x-correlation-id={cid})")
    try:
        rh = {k: v for (k, v) in resp.headers.items()}
        print(f"Response headers: {json.dumps(rh, indent=2)[:2000]}")
    except Exception:
        pass
    try:
        body = resp.json()
    except Exception:
        body = {"raw": (resp.text or "")[:4000]}
    print(json.dumps(body, indent=2)[:6000])
    if not resp.ok:
        raise RuntimeError(f"Legacy ingest failed: {resp.status_code} {resp.text[:600]}")
    return body


# ----------------------------- file collection ------------------------------
def collect_files_from_args_or_glob(cli_files: List[str]) -> List[Path]:
    """
    If CLI files are provided, use them (in order).
    Otherwise, ingest reference_statistics_bundle.json first (if present),
    then all *manifest.json in cwd (sorted by name).
    """
    if cli_files:
        return [Path(f).resolve() for f in cli_files]
    cwd = Path(".").resolve()
    files: List[Path] = []
    ref_bundle = cwd / "reference_statistics_bundle.json"
    if ref_bundle.exists() and ref_bundle.is_file():
        files.append(ref_bundle)
    files.extend(sorted(cwd.glob("*manifest.json")))
    return files


# --------------------------------- main -------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Ingest OSDU manifests using a refresh_token (REST only, no osdu-cli). Now with Workflow polling."
    )
    parser.add_argument(
        "files",
        nargs="*",
        help="Optional list of manifest files. If omitted, the tool ingests reference_statistics_bundle.json "
             "first (if present) and then all *manifest.json in ./",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.5,
        help="Seconds to sleep between ingestions (default: 0.5)",
    )
    parser.add_argument(
        "--mode",
        choices=["workflow", "legacy"],
        help="Override ingestion mode (default taken from env INGEST_MODE or 'workflow')",
    )
    args = parser.parse_args()

# Required env
    refresh_token = getenv("refresh_token")

    # Corrected 
    # Use plain authority base (no tenant segment here; tenant_id is added later)
    authority_base = getenv("AAD_AUTHORITY", "https://login.microsoftonline.com")
    tenant_id = getenv("OSDU_TENANT_ID", "3aa4a235-b6e2-48d5-9195-7fcf05b459b0")
    client_id = getenv("OSDU_CLIENT_ID", "7a414874-4b27-4378-b34f-bc9e5a5faa4f")
    scope_v2 = getenv("OSDU_SCOPE","7daee810-3f78-40c4-84c2-7a199428de18/.default openid offline_Access")
    redirect_uri_v2 = getenv("OSDU_REDIRECT_URI", "https://oauth.pstmn.io/v1/callback")
    resource_v1 = getenv("OSDU_RESOURCE", None)
    host = getenv("OSDU_HOST", "https://equinorswedev.energy.azure.com")
    partition = getenv("OSDU_PARTITION", "dev")
    env_mode = getenv("INGEST_MODE", "workflow").lower()
    mode = (args.mode or env_mode).lower()

    # Polling controls
    poll_interval = float(getenv("WF_POLL_INTERVAL_SECONDS", "15"))
    max_wait = float(getenv("WF_MAX_WAIT_SECONDS", "30"))
    verbose_logs = getenv("WF_VERBOSE_LOGS", "1") not in ("0", "false", "no")

    files = collect_files_from_args_or_glob(args.files)

    print("=== Config ===")
    print(f"Authority : {authority_base}")
    print(f"Tenant ID : {tenant_id}")
    print(f"Client ID : {client_id}")
    print(f"Host      : {host}")
    print(f"Partition : {partition}")
    print(f"Mode      : {mode}")
    print(f"Files     : {[str(p) for p in files]}")
    print("==============\n")

    if not files:
        raise SystemExit("No manifest files found (neither reference_statistics_bundle.json nor *manifest.json).")
    if not refresh_token:
        raise SystemExit("Missing env var 'refresh_token'.")

    print("Requesting access_token via refresh_token ...")
    access_token, expires_in = get_access_token_from_refresh_token(
        refresh_token=refresh_token,
        tenant_id=tenant_id,
        client_id=client_id,
        authority_base=authority_base,
        scope_v2=scope_v2,
        resource_v1=(resource_v1 or None),  # skip v1 if empty
        redirect_uri_v2=redirect_uri_v2,
    )
    
    exp_mins = round(expires_in / 60.0, 1)
    print(f"Got access_token (expires in ~{exp_mins} minutes).")
    _peek_jwt(access_token)

    sess = _requests_session()
    ok_all = True

    for fp in files:
        print(f"\n==> Ingesting: {fp.name}")
        if not fp.exists():
            print(f"[skip] File not found: {fp}")
            ok_all = False
            continue

        # Load manifest JSON upfront
        try:
            manifest_json = json.loads(fp.read_text(encoding="utf-8"))
        except Exception as ex:
            print(f"[error] {fp.name}: invalid JSON: {ex}")
            ok_all = False
            continue

        try:
            if mode == "legacy":
                _ = _legacy_ingest(sess, host, partition, access_token, manifest_json)
            else:
                # workflow submit + poll
                run_id, _submit = _wf_submit(sess, host, partition, access_token, manifest_json, workflow_id="Osdu_ingest")
                run_obj = _wf_poll_until_done(
                    sess=sess,
                    host=host,
                    partition=partition,
                    token=access_token,
                    workflow_id="Osdu_ingest",
                    run_id=run_id,
                    poll_interval=poll_interval,
                    max_wait=max_wait,
                    verbose_logs=verbose_logs,
                )
                print("\n=== Final Workflow Run Object (truncated) ===")
                try:
                    print(json.dumps(run_obj, indent=2)[:8000])
                except Exception:
                    print(str(run_obj)[:8000])
                _try_print_ingest_summary(run_obj)
        except Exception as ex:
            print(f"[error] {fp.name}: {ex}")
            ok_all = False

        time.sleep(max(0.0, args.sleep))

    if ok_all:
        print("\nAll ingestions completed successfully.")
        sys.exit(0)
    else:
        print("\nOne or more ingestions failed.")
        sys.exit(2)


if __name__ == "__main__":
    main()