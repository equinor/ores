#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
4ingest.py (STRICT .env mode)

Ingest OSDU manifests using a refresh_token (no external CLI required) with Workflow run polling
(Azure run-log equivalent) and verbose results.

STRICT ENV BEHAVIOR
- Configuration is loaded EXCLUSIVELY from .env file(s) provided via --env-file (repeatable).
- No process environment variables are read.
- Validation fails if required keys are missing.

Required .env keys (canonical names; compatible aliases in parentheses):
  - refresh_token               (REFRESH_TOKEN)
  - OSDU_TENANT_ID              (AZURE_TENANT_ID)
  - OSDU_CLIENT_ID              (AZURE_CLIENT_ID)
  - OSDU_SCOPE OR OSDU_RESOURCE (AZURE_SCOPE)
  - OSDU_HOST                   (OSDU_BASE_URL; http(s) scheme added if omitted)
  - OSDU_PARTITION              (DATA_PARTITION_ID)

Optional:
  - AAD_AUTHORITY (defaults to https://login.microsoftonline.com)
  - OSDU_REDIRECT_URI (OIDC_REDIRECT_URI)  # NOTE: NOT sent for refresh_token grant
  - INGEST_MODE ("workflow" | "legacy")    # default "workflow"
  - WF_POLL_INTERVAL_SECONDS               # default 15
  - WF_MAX_WAIT_SECONDS                    # default 30
  - WF_VERBOSE_LOGS                        # default "1" (true)

Usage examples:
  python 4ingest.py --env-file .env -- files/*.manifest.json
  python 4ingest.py --env-file .env.dev --env-file secrets.env --mode workflow

"""

import argparse
import base64
import json
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests


# =============================== .env handling =============================== #
def _parse_dotenv_file(path: Path) -> Dict[str, str]:
    """Parse KEY=VALUE pairs from a .env-style file into a dict (no external deps)."""
    vals: Dict[str, str] = {}
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception:
        return vals
    for raw_line in raw.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip()
        if len(v) >= 2 and ((v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'"))):
            v = v[1:-1]
        vals[k] = v
    return vals


def _first(env: Dict[str, str], keys: List[str]) -> Optional[str]:
    """Return the first non-empty value for any of the provided keys (exact match)."""
    for k in keys:
        v = env.get(k)
        if v is not None:
            v = v.strip()
            if v:
                return v
    return None


def _normalize_env(raw_chain: List[Dict[str, str]]) -> Dict[str, str]:
    """
    Normalize and merge multiple .env dicts (earlier -> later; later wins).
    Map common aliases to canonical names and perform minimal value normalization.
    """
    merged: Dict[str, str] = {}
    for kv in raw_chain:
        merged.update(kv)

    norm: Dict[str, str] = {}

    # Canonical keys (with aliases)
    norm["refresh_token"]     = _first(merged, ["refresh_token", "REFRESH_TOKEN"]) or ""
    norm["OSDU_TENANT_ID"]    = _first(merged, ["OSDU_TENANT_ID", "AZURE_TENANT_ID"]) or ""
    norm["OSDU_CLIENT_ID"]    = _first(merged, ["OSDU_CLIENT_ID", "AZURE_CLIENT_ID"]) or ""
    norm["OSDU_SCOPE"]        = _first(merged, ["OSDU_SCOPE", "AZURE_SCOPE"]) or ""
    norm["OSDU_RESOURCE"]     = _first(merged, ["OSDU_RESOURCE"]) or ""
    norm["OSDU_REDIRECT_URI"] = _first(merged, ["OSDU_REDIRECT_URI", "OIDC_REDIRECT_URI"]) or ""
    norm["OSDU_PARTITION"]    = _first(merged, ["OSDU_PARTITION", "DATA_PARTITION_ID"]) or ""

    host = _first(merged, ["OSDU_HOST", "OSDU_BASE_URL"]) or ""
    if host and not host.startswith("http"):
        host = "https://" + host.lstrip("/")
    norm["OSDU_HOST"] = host

    # Optional with safe defaults (constants, not from OS env)
    norm["AAD_AUTHORITY"] = _first(merged, ["AAD_AUTHORITY"]) or "https://login.microsoftonline.com"
    norm["INGEST_MODE"]   = (_first(merged, ["INGEST_MODE"]) or "workflow").lower()

    # Workflow polling controls
    norm["WF_POLL_INTERVAL_SECONDS"] = _first(merged, ["WF_POLL_INTERVAL_SECONDS"]) or "15"
    norm["WF_MAX_WAIT_SECONDS"]      = _first(merged, ["WF_MAX_WAIT_SECONDS"]) or "30"
    norm["WF_VERBOSE_LOGS"]          = _first(merged, ["WF_VERBOSE_LOGS"]) or "1"

    return norm


def _validate_env(env: Dict[str, str]) -> None:
    """Validate presence of required keys and either scope (v2) or resource (v1)."""
    missing: List[str] = []
    required = ["refresh_token", "OSDU_TENANT_ID", "OSDU_CLIENT_ID", "OSDU_HOST", "OSDU_PARTITION"]
    for k in required:
        if not env.get(k):
            missing.append(k)
    if not (env.get("OSDU_SCOPE") or env.get("OSDU_RESOURCE")):
        missing.append("OSDU_SCOPE or OSDU_RESOURCE")
    if missing:
        raise SystemExit(
            "Missing required configuration from .env:\n  - " + "\n  - ".join(missing) +
            "\n\nEnsure your --env-file contains these keys (aliases allowed)."
        )


def load_env_chain(paths: List[str]) -> Tuple[Dict[str, str], List[str]]:
    """
    Load one or more .env files in order, returning (normalized_env, loaded_paths).
    Later files override earlier ones. No OS environment is consulted.
    """
    loaded: List[str] = []
    raw_chain: List[Dict[str, str]] = []
    for p in paths:
        fp = Path(p).expanduser().resolve()
        if not fp.exists():
            raise SystemExit(f"--env-file not found: {p}")
        raw = _parse_dotenv_file(fp)
        raw_chain.append(raw)
        loaded.append(str(fp))
    env = _normalize_env(raw_chain)
    _validate_env(env)
    return env, loaded


# ================================ HTTP helpers =============================== #
def _headers(partition: str, token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "data-partition-id": partition,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _requests_session() -> requests.Session:
    """
    Create a requests session.
    Note: requests will honor HTTPS proxy vars if set in the OS, but this script does not read them.
    """
    s = requests.Session()
    s.headers.update({"Accept": "application/json"})
    return s


# ================================ Auth helpers =============================== #
def get_access_token_from_refresh_token(
    refresh_token: str,
    tenant_id: str,
    client_id: str,
    authority_base: str,
    scope_v2: Optional[str],
    resource_v1: Optional[str],
    timeout: int = 20,
) -> Tuple[str, int]:
    """
    Auth flow:
      - Try AAD v2 (scope) first.
      - Fall back to AAD v1 (resource) only if resource_v1 is provided.

    IMPORTANT: We do NOT send redirect_uri on the refresh_token grant to avoid AADSTS50011
    mismatches when the registered redirect does not exactly match the request.
    """
    if not refresh_token:
        raise RuntimeError("Missing refresh_token")

    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/x-www-form-urlencoded"})

    # v2 (prefer)
    if scope_v2:
        v2_url = f"{authority_base.rstrip('/')}/{tenant_id}/oauth2/v2.0/token"
        v2_form = {
            "grant_type": "refresh_token",
            "client_id": client_id,
            "refresh_token": refresh_token,
            "scope": scope_v2,
        }
        try:
            r = sess.post(v2_url, data=v2_form, timeout=timeout)
            if r.ok:
                data = r.json()
                if "access_token" in data:
                    return data["access_token"], int(data.get("expires_in", 3600))
                raise RuntimeError(f"[auth v2] token payload missing access_token: {data}")
            else:
                raise RuntimeError(f"[auth v2] {r.status_code}: {r.text[:800]}")
        except requests.RequestException as e:
            raise RuntimeError(f"[auth v2] request error: {e}") from e

    # v1 (fallback only if resource is provided)
    if resource_v1:
        v1_url = f"{authority_base.rstrip('/')}/{tenant_id}/oauth2/token"
        v1_form = {
            "grant_type": "refresh_token",
            "client_id": client_id,
            "refresh_token": refresh_token,
            "resource": resource_v1,
        }
        try:
            r = sess.post(v1_url, data=v1_form, timeout=timeout)
            if r.ok:
                data = r.json()
                if "access_token" in data:
                    return data["access_token"], int(data.get("expires_in", 3600))
                raise RuntimeError(f"[auth v1] token payload missing access_token: {data}")
            raise RuntimeError(f"[auth v1] {r.status_code}: {r.text[:800]}")
        except requests.RequestException as e:
            raise RuntimeError(f"[auth v1] request error: {e}") from e

    raise RuntimeError(
        "Unable to obtain access_token via v2 (OSDU_SCOPE) or v1 (OSDU_RESOURCE). "
        "Set OSDU_SCOPE to '<GUID>/.default openid offline_access' (v2), or "
        "set OSDU_RESOURCE to a valid API resource (v1)."
    )


def _peek_jwt(jwt_token: str) -> None:
    """Minimal peek of JWT payload (aud, azp, exp) for debugging."""
    try:
        parts = jwt_token.split(".")
        if len(parts) >= 2:
            import base64 as _b64
            payload = parts[1] + "==="
            payload_json = json.loads(_b64.urlsafe_b64decode(payload.encode()))
            aud = payload_json.get("aud")
            azp = payload_json.get("azp")
            exp = payload_json.get("exp")
            print(f"Token audience (aud): {aud}\n authorized party (azp): {azp}\n exp: {exp}")
    except Exception:
        pass


# ================================ Workflow API =============================== #
def _wf_submit(
    sess: requests.Session,
    host: str,
    partition: str,
    token: str,
    manifest_json: Dict[str, Any],
    workflow_id: str = "Osdu_ingest",
) -> Tuple[str, Dict[str, Any]]:
    """Submit a workflow run. Returns (run_id, submit_response_json)."""
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
    paths = [
        f"/api/workflow/v1/workflow/{workflow_id}/workflowRun/{run_id}",
        f"/api/workflow/v1/workflowRun/{run_id}",
        f"/api/workflow/v1/workflow/{workflow_id}/workflowRun/{run_id}/status",
    ]
    terminal = {"completed", "succeeded", "failed", "error", "cancelled"}
    print(f"Polling workflow runId={run_id} ...")
    while True:
        attempts += 1
        for p in paths:
            obj = _wf_get(sess, host, partition, token, p)
            if obj:
                last_obj = obj
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

    def walk(x):
        if isinstance(x, dict):
            yield x
            for v in x.values():
                yield from walk(v)
        elif isinstance(x, list):
            for it in x:
                yield from walk(it)

    candidates: List[Any] = []
    for k in ("outputs", "output", "result", "results", "payload", "data"):
        v = run_obj.get(k)
        if isinstance(v, (dict, list)):
            candidates.append(v)

    rows = []
    for cand in candidates:
        for node in walk(cand):
            if not isinstance(node, dict):
                continue
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
        for rid, st, msg in rows[:200]:
            line = f" - {rid} -> {st}"
            if msg:
                line += f" ({msg[:200]})"
            print(line)
    else:
        print("\n(No per-record ingestion details were found in workflow outputs.)")


# ================================ Legacy ingest ============================== #
def _legacy_ingest(
    sess: requests.Session,
    host: str,
    partition: str,
    token: str,
    manifest_json: Dict[str, Any],
) -> Dict[str, Any]:
    """Direct manifest ingest (synchronous): POST /api/osdu/v3/ingest/manifest"""
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


# ================================= File set ================================= #
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


# =================================== main =================================== #
def main():
    # Bootstrap: capture --env-file early to load config before full parser
    boot = argparse.ArgumentParser(add_help=False)
    boot.add_argument(
        "--env-file", action="append", metavar="PATH", required=True,
        help="Path to a .env file (repeatable). Later files override earlier ones."
    )
    boot_args, _ = boot.parse_known_args()

    # Load and validate .env chain (STRICT: .env only; no OS env)
    ENV, loaded_paths = load_env_chain(boot_args.env_file)

    # Full parser (include boot in help so --env-file is documented)
    ap = argparse.ArgumentParser(
        parents=[boot],
        description="Ingest OSDU manifests using a refresh_token (REST only, no osdu-cli). Now with Workflow polling."
    )
    ap.add_argument(
        "files",
        nargs="*",
        help="Optional list of manifest files. If omitted, ingests reference_statistics_bundle.json first (if present) and then all *manifest.json in ./",
    )
    ap.add_argument(
        "--sleep",
        type=float,
        default=0.5,
        help="Seconds to sleep between ingestions (default: 0.5)",
    )
    ap.add_argument(
        "--mode",
        choices=["workflow", "legacy"],
        help="Override ingestion mode (default taken from .env INGEST_MODE or 'workflow')",
    )
    args = ap.parse_args()

    # Resolve config strictly from ENV (with minimal CLI override for mode)
    refresh_token = ENV["refresh_token"]
    authority_base = ENV["AAD_AUTHORITY"]
    tenant_id = ENV["OSDU_TENANT_ID"]
    client_id = ENV["OSDU_CLIENT_ID"]
    scope_v2 = ENV.get("OSDU_SCOPE") or ""
    resource_v1 = ENV.get("OSDU_RESOURCE") or None
    host = ENV["OSDU_HOST"]
    partition = ENV["OSDU_PARTITION"]
    env_mode = ENV["INGEST_MODE"]
    mode = (args.mode or env_mode).lower()

    # Poll controls
    try:
        poll_interval = float(ENV.get("WF_POLL_INTERVAL_SECONDS", "15"))
    except Exception:
        poll_interval = 15.0
    try:
        max_wait = float(ENV.get("WF_MAX_WAIT_SECONDS", "30"))
    except Exception:
        max_wait = 30.0
    verbose_logs = (ENV.get("WF_VERBOSE_LOGS", "1").lower() not in ("0", "false", "no"))

    files = collect_files_from_args_or_glob(args.files)

    print("=== Config (strict .env mode) ===")
    print(f".env files loaded : {', '.join(loaded_paths)}")
    print("OS environment    : NOT USED")
    print(f"Authority         : {authority_base}")
    print(f"Tenant ID         : {tenant_id}")
    print(f"Client ID         : {client_id}")
    print(f"Host              : {host}")
    print(f"Partition         : {partition}")
    print(f"Mode              : {mode}")
    print(f"Files             : {[str(p) for p in files]}")
    print("=================================\n")

    if not files:
        raise SystemExit("No manifest files found (neither reference_statistics_bundle.json nor *manifest.json).")
    if not refresh_token:
        raise SystemExit("Missing 'refresh_token' (put REFRESH_TOKEN=... into your --env-file).")

    print("Requesting access_token via refresh_token ...")
    access_token, expires_in = get_access_token_from_refresh_token(
        refresh_token=refresh_token,
        tenant_id=tenant_id,
        client_id=client_id,
        authority_base=authority_base,
        scope_v2=scope_v2,
        resource_v1=resource_v1,
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