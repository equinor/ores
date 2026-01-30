#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Build and ingest an OSDU manifest from a Reservoir DMS (RD-DMS) dataspace,
with extensive debug/trace logging and workflow status checks.

Usage examples
--------------
# Verbose + debug (recommended first run)
python gendataspacemanifest.py --dataspace "demo/volve" -v --debug

# Dry-run (build only) and write manifest to a file
python gendataspacemanifest.py --dataspace "demo/volve" --no-ingest --out demo_volve_manifest.json

# Submit, then just capture runId from output (look for RUN_ID=...)
python -u gendataspacemanifest.py --dataspace "demo/volve" -v --debug

# Check status of a specific run id
python gendataspacemanifest.py --check-run --run-id "e4a205d0-dc98-40c4-8334-6d566dd0a39c" -v --debug

# Check status and enforce expected state, returning non-zero if it doesn't match
python gendataspacemanifest.py --check-run --run-id "<RUN_ID>" --expect-state Completed -v

Environment variables (defaults align with equinordev)
------------------------------------------------------
Required:
  refresh_token              # AAD refresh token used to obtain access_token

Optional (defaults provided):
  AAD_AUTHORITY              = https://login.microsoftonline.com
  OSDU_SCOPE                 = 7daee810-3f78-40c4-84c2-7a199428de18/.default openid offline_Access
  OSDU_RESOURCE              = https://oauth.pstmn.io/v1/callback
  OSDU_HOST                  = https://equinordev.energy.azure.com
  OSDU_PARTITION             = data
  OSDU_CLIENT_ID             = ebd2bfee-ecba-47b7-a33c-017d0131879d
  OSDU_TENANT_ID             = 3aa4a235-b6e2-48d5-9195-7fcf05b459b0
  RDDMS_HOST                 = <OSDU_HOST>/api/reservoir-ddms/v2 (derived if missing)

Exit codes
----------
 0 = success
 2 = fatal error/exception
 3 = no URIs found
 4 = workflow state Failed/Error (when --expect-state is used)
 5 = workflow state Cancelled (when --expect-state is used)
 6 = runId not found (404) during --check-run
 7 = state does not match --expect-state (e.g., still Running/Queued)
"""

import argparse
import base64
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
from urllib.parse import quote, unquote

# --------------------------- small helpers ---------------------------

def encode_dataspace_id(ds: str) -> str:
    """Ensure exactly-once encoding of reserved characters (incl. '/')."""
    return quote(unquote(ds), safe='')  # '/' becomes %2F and we avoid double-encoding

def log(msg: str, *, flush: bool = True):
    print(msg, flush=flush)

def mask_token(h: Dict[str, str]) -> Dict[str, str]:
    """Return a shallow-copied headers dict with Authorization masked."""
    if not h:
        return {}
    out = dict(h)
    if "Authorization" in out:
        out["Authorization"] = "Bearer ****"
    return out

def getenv(name: str, default: Optional[str] = None) -> Optional[str]:
    v = os.environ.get(name)
    if v is None:
        return default
    v = v.strip()
    return v if v else default

# --------------------------- auth ---------------------------

def get_access_token_from_refresh_token(
    refresh_token: str,
    tenant_id: str,
    client_id: str,
    authority_base: str,
    scope_v2: Optional[str],
    resource_v1: Optional[str],
    timeout: int = 20,
    debug: bool = False,
) -> Tuple[str, int]:
    if not refresh_token:
        raise RuntimeError("Missing refresh_token (env var 'refresh_token')")

    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/x-www-form-urlencoded"})

    if debug:
        log("[auth] trying AAD v2 (scope)")

    # Try AAD v2 (scope)
    if scope_v2:
        v2_url = f"{authority_base.rstrip('/')}/{tenant_id}/oauth2/v2.0/token"
        v2_form = {
            "grant_type": "refresh_token",
            "client_id": client_id,
            "refresh_token": refresh_token,
            "scope": scope_v2,
        }
        t0 = time.time()
        r = sess.post(v2_url, data=v2_form, timeout=timeout)
        dt = time.time() - t0
        if debug:
            log(f"[auth] v2 POST {r.status_code} in {dt:.2f}s to {v2_url}")
        if r.ok and "access_token" in r.json():
            data = r.json()
            return data["access_token"], int(data.get("expires_in", 3600))
        else:
            if debug:
                log(f"[auth] v2 error body: {r.text[:800]}")

    # Fallback AAD v1 (resource)
    if debug:
        log("[auth] trying AAD v1 (resource)")
    if resource_v1:
        v1_url = f"{authority_base.rstrip('/')}/{tenant_id}/oauth2/token"
        v1_form = {
            "grant_type": "refresh_token",
            "client_id": client_id,
            "refresh_token": refresh_token,
            "resource": resource_v1,
        }
        t0 = time.time()
        r = sess.post(v1_url, data=v1_form, timeout=timeout)
        dt = time.time() - t0
        if debug:
            log(f"[auth] v1 POST {r.status_code} in {dt:.2f}s to {v1_url}")
        if r.ok and "access_token" in r.json():
            data = r.json()
            return data["access_token"], int(data.get("expires_in", 3600))
        raise RuntimeError(f"Token request failed: {r.status_code} {r.text[:800]}")

    raise RuntimeError("Unable to obtain access_token via v2 or v1 token endpoints.")

def peek_jwt(jwt_token: str) -> Dict[str, str]:
    """Return minimal details from JWT for quick inspection (aud, azp, exp)."""
    try:
        parts = jwt_token.split(".")
        if len(parts) >= 2:
            payload = parts[1] + "==="
            payload_json = json.loads(base64.urlsafe_b64decode(payload.encode()))
            return {
                "aud": str(payload_json.get("aud")),
                "azp": str(payload_json.get("azp")),
                "exp": str(payload_json.get("exp")),
            }
    except Exception:
        pass
    return {}

# --------------------------- RD-DMS helpers ---------------------------

def rddms_headers(token: str, partition: str, correlation_id: Optional[str]=None) -> Dict[str, str]:
    h = {
        "Authorization": f"Bearer {token}",
        "data-partition-id": partition,
        "Accept": "application/json",
    }
    if correlation_id:
        h["x-correlation-id"] = correlation_id
    return h

def list_resources_all(
    rddms_host: str,
    dataspace: str,
    token: str,
    partition: str,
    *,
    top: int = 1000,
    max_items: Optional[int] = None,
    data_object_types: Optional[List[str]] = None,
    debug: bool = False,
    trace: bool = False,
) -> List[Dict]:
    items: List[Dict] = []
    skip = 0
    params = {"$top": str(top), "$skip": str(skip)}
    if data_object_types:
        params["dataObjectTypes"] = ",".join(data_object_types)
    sess = requests.Session()

    while True:
        params["$skip"] = str(skip)
        ds = encode_dataspace_id(dataspace)
        url = f"{rddms_host.rstrip('/')}/dataspaces/{ds}/resources/all"
        cid = str(uuid.uuid4())
        hdr = rddms_headers(token, partition, cid)

        if debug:
            log(f"[rddms] GET {url} params={params} headers={mask_token(hdr)}")
            log(f"[rddms] encoded dataspace: {ds}")

        t0 = time.time()
        r = sess.get(url, headers=hdr, params=params, timeout=60)
        dt = time.time() - t0

        if trace:
            log(f"[rddms] ← {r.status_code} in {dt:.2f}s "
                f"(x-correlation-id={cid}) headers={dict(r.headers)}")
            body_preview = (r.text or "")[:1200]
            log(f"[rddms] body: {body_preview}")

        if not r.ok:
            raise RuntimeError(f"RD-DMS list resources failed: {r.status_code} {r.text[:600]}")

        page = r.json() or []
        if not isinstance(page, list):
            raise RuntimeError("Unexpected response for resources/all (expected list)")

        items.extend(page)
        if debug:
            log(f"[rddms] page items={len(page)} total={len(items)}")

        if max_items and len(items) >= max_items:
            items = items[:max_items]
            break
        if len(page) < top:
            break
        skip += top
        time.sleep(0.2)

    return items

def collect_uris(resources: List[Dict]) -> List[str]:
    seen = set()
    unique = []
    for r in resources:
        u = r.get("uri")
        if isinstance(u, str) and u and u not in seen:
            unique.append(u)
            seen.add(u)
    return unique

def build_manifest(
    osdu_host: str,
    token: str,
    partition: str,
    uris: List[str],
    *,
    viewers: Optional[List[str]] = None,
    owners: Optional[List[str]] = None,
    legaltags: Optional[List[str]] = None,
    other_countries: Optional[List[str]] = None,
    create_missing_refs: bool = True,
    debug: bool = False,
    trace: bool = False,
) -> Dict:
    url = f"{osdu_host.rstrip('/')}/api/reservoir-ddms/v2/manifests/build"
    body = {
        "uris": uris,
        "acl": {"viewers": viewers or [], "owners": owners or []},
        "legal": {"legaltags": legaltags or [], "otherRelevantDataCountries": other_countries or []},
        "createMissingReferences": bool(create_missing_refs),
    }
    cid = str(uuid.uuid4())
    headers = {
        "Authorization": f"Bearer {token}",
        "data-partition-id": partition,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "x-correlation-id": cid,
    }

    if debug:
        log(f"[build] POST {url} headers={mask_token(headers)} uris={len(uris)}")

    t0 = time.time()
    r = requests.post(url, headers=headers, data=json.dumps(body), timeout=300)
    dt = time.time() - t0

    if trace:
        log(f"[build] ← {r.status_code} in {dt:.2f}s (x-correlation-id={cid}) headers={dict(r.headers)}")
        log(f"[build] body preview: {(r.text or '')[:2000]}")

    if not r.ok:
        raise RuntimeError(f"RD-DMS build manifest failed: {r.status_code} {r.text[:600]}")

    return r.json()

def ingest_manifest_via_workflow(
    osdu_host: str,
    partition: str,
    token: str,
    manifest: Dict,
    *,
    debug: bool = False,
    trace: bool = False,
) -> Dict:
    url = f"{osdu_host.rstrip('/')}/api/workflow/v1/workflow/Osdu_ingest/workflowRun"
    cid = str(uuid.uuid4())
    payload = {
        "executionContext": {
            "Payload": {"AppKey": "gendataspacemanifest.py", "data-partition-id": partition},
            "manifest": manifest,
        }
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "data-partition-id": partition,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "x-correlation-id": cid,
    }

    if debug:
        log(f"[ingest] POST {url} headers={mask_token(headers)}")

    t0 = time.time()
    r = requests.post(url, headers=headers, data=json.dumps(payload), timeout=180)
    dt = time.time() - t0

    if trace:
        log(f"[ingest] ← {r.status_code} in {dt:.2f}s (x-correlation-id={cid}) headers={dict(r.headers)}")
        log(f"[ingest] body preview: {(r.text or '')[:2000]}")

    if not r.ok:
        raise RuntimeError(f"Workflow ingest failed: {r.status_code} {r.text[:800]}")

    try:
        resp_json = r.json()
    except Exception:
        return {"status": r.status_code, "text": r.text}

    # Surface runId if present
    run_id = None
    try:
        run_id = resp_json.get("runId") or resp_json.get("id") \
                 or resp_json.get("data", {}).get("runId")
    except Exception:
        pass
    if run_id:
        log(f"[ingest] runId: {run_id}")

    return resp_json

# --------------------------- Workflow status ---------------------------

def get_workflow_status(osdu_host: str, partition: str, token: str, run_id: str,
                        *, debug: bool = False, trace: bool = False) -> Dict:
    """
    GET /api/workflow/v1/workflow/Osdu_ingest/workflowRun/{run_id}
    """
    url = f"{osdu_host.rstrip('/')}/api/workflow/v1/workflow/Osdu_ingest/workflowRun/{run_id}"
    cid = str(uuid.uuid4())
    headers = {
        "Authorization": f"Bearer {token}",
        "data-partition-id": partition,
        "Accept": "application/json",
        "x-correlation-id": cid,
    }
    if debug:
        log(f"[status] GET {url} headers={mask_token(headers)}")

    t0 = time.time()
    r = requests.get(url, headers=headers, timeout=60)
    dt = time.time() - t0

    if trace:
        log(f"[status] ← {r.status_code} in {dt:.2f}s (x-correlation-id={cid}) headers={dict(r.headers)}")
        log(f"[status] body: {(r.text or '')[:2000]}")

    if r.status_code == 404:
        raise FileNotFoundError(f"Workflow run not found: {run_id}")
    if not r.ok:
        raise RuntimeError(f"Workflow status failed: {r.status_code} {r.text[:800]}")

    return r.json() or {}

def normalize_state(status_json: Dict) -> Optional[str]:
    """
    Attempt to normalize workflow run status/state from various response shapes.
    Returns a capitalized string like: Completed, Running, Queued, Failed, Cancelled, Error...
    """
    candidates = [
        status_json.get("status"),
        status_json.get("state"),
        status_json.get("runStatus"),
        status_json.get("workflowStatus"),
        status_json.get("data", {}).get("status"),
        status_json.get("data", {}).get("state"),
    ]
    for c in candidates:
        if isinstance(c, str) and c.strip():
            # Normalize e.g. 'completed' -> 'Completed'
            return c.strip().capitalize()
    return None

def exit_code_for_state(current: Optional[str], expect: Optional[str]) -> int:
    """
    Map workflow state vs expected to exit codes.
    If no expect provided -> 0.
    If expect provided:
      - return 0 if current == expect (case-insensitive, trimmed)
      - 4 on Failed/Error
      - 5 on Cancelled
      - 7 otherwise (including Running/Queued or any mismatch)
    """
    if not expect:
        return 0
    if not current:
        return 7
    c = current.strip().lower()
    e = expect.strip().lower()
    if c == e:
        return 0
    if c in ("failed", "error"):
        return 4
    if c in ("cancelled", "canceled"):
        return 5
    # Running, Queued, or any other mismatch
    return 7

# --------------------------- main ---------------------------

def main() -> int:
    p = argparse.ArgumentParser(description="Build OSDU manifest from RD-DMS dataspace and ingest via Workflow")
    p.add_argument("--dataspace", required=False,
                   help="RD-DMS dataspace id, e.g. 'demo/volve' (required unless --check-run)")
    p.add_argument("--data-object-types", default=None,
                   help="Optional CSV list of Energistics types to include (RD-DMS filter)")
    p.add_argument("--top", type=int, default=1000, help="Page size for RD-DMS listing (default: 1000)")
    p.add_argument("--max-items", type=int, default=None, help="Optional cap on number of resources to include")
    p.add_argument("--out", default=None, help="Write built manifest JSON to this file")
    p.add_argument("--no-ingest", action="store_true", help="Only build manifest; do not submit to Workflow")
    p.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    p.add_argument("--debug", action="store_true", help="Add request/response summaries")
    p.add_argument("--trace", action="store_true", help="Full HTTP trace: headers and body previews")

    # ACL / legal overrides
    p.add_argument("--viewers", default=None, help="CSV of viewer groups; overrides default")
    p.add_argument("--owners",  default=None, help="CSV of owner groups; overrides default")
    p.add_argument("--legaltags", default=None, help="CSV of legal tags; overrides default")
    p.add_argument("--countries", default=None, help="CSV of otherRelevantDataCountries; overrides default")

    # Host/partition overrides
    p.add_argument("--osdu-host", default=getenv("OSDU_HOST", "https://equinordev.energy.azure.com"))
    p.add_argument("--partition", default=getenv("OSDU_PARTITION", "data"))
    p.add_argument("--rddms-host", default=getenv("RDDMS_HOST", None))

    # Workflow status checking
    p.add_argument("--check-run", action="store_true",
                   help="Check workflow run status by --run-id and exit")
    p.add_argument("--run-id", default=None,
                   help="Workflow run id to check with --check-run")
    p.add_argument("--expect-state", default=None,
                   help="Expected workflow state (e.g., Completed). Sets exit code if not matched.")

    args = p.parse_args()

    # Setup low-level trace if requested
    if args.trace:
        import http.client as httpclient
        httpclient.HTTPConnection.debuglevel = 1
        import logging
        logging.basicConfig(level=logging.DEBUG)
        logging.getLogger("urllib3").setLevel(logging.DEBUG)
        logging.getLogger("requests").setLevel(logging.DEBUG)

    refresh_token = getenv("refresh_token")
    aad_authority = getenv("AAD_AUTHORITY", "https://login.microsoftonline.com")
    scope_v2 = getenv("OSDU_SCOPE", "7daee810-3f78-40c4-84c2-7a199428de18/.default openid offline_Access")
    resource_v1 = getenv("OSDU_RESOURCE", "https://oauth.pstmn.io/v1/callback")
    tenant_id = getenv("OSDU_TENANT_ID", "3aa4a235-b6e2-48d5-9195-7fcf05b459b0")
    client_id = getenv("OSDU_CLIENT_ID", "ebd2bfee-ecba-47b7-a33c-017d0131879d")

    osdu_host = args.osdu_host
    partition = args.partition
    rddms_host = args.rddms_host or f"{osdu_host.rstrip('/')}/api/reservoir-ddms/v2"

    # If only checking status, dataspace is not required.
    if not args.check_run and not args.dataspace:
        raise SystemExit("Missing --dataspace (or use --check-run with --run-id)")

    if args.verbose or args.debug or args.trace:
        log("=== Config ===")
        if args.dataspace:
            log(f"Dataspace    : {args.dataspace}")
        log(f"OSDU Host    : {osdu_host}")
        log(f"RD-DMS Host  : {rddms_host}")
        log(f"Partition    : {partition}")
        log(f"AAD Tenant   : {tenant_id}")
        log(f"Client ID    : {client_id}")
        log(f"Scope v2     : {scope_v2}")
        log(f"Resource v1  : {resource_v1}")
        log(f"Filters      : data_object_types={args.data_object_types} top={args.top} max_items={args.max_items}")
        log(f"Debug/Trace  : debug={args.debug} trace={args.trace}")
        if args.check_run:
            log(f"Check Run    : run_id={args.run_id} expect_state={args.expect_state}")
        log("==============")

    # 1) Auth for both flows (build/ingest or check-run)
    log("Requesting access_token via refresh_token ...")
    token, expires_in = get_access_token_from_refresh_token(
        refresh_token=refresh_token,
        tenant_id=tenant_id,
        client_id=client_id,
        authority_base=aad_authority,
        scope_v2=scope_v2,
        resource_v1=resource_v1,
        debug=args.debug or args.trace,
    )
    jwt_info = peek_jwt(token)
    log(f"Got access_token (~{round(expires_in/60.0,1)} min). JWT peek={jwt_info}")

    # 1a) Optional status-only branch
    if args.check_run:
        if not args.run_id:
            raise SystemExit("Missing --run-id for --check-run")
        try:
            status = get_workflow_status(osdu_host=osdu_host, partition=partition, token=token,
                                         run_id=args.run_id, debug=args.debug or args.trace, trace=args.trace)
        except FileNotFoundError as nf:
            log(f"[status] {nf}")
            return 6
        # Print a compact summary plus the JSON
        state = normalize_state(status)
        log(f"[status] runId={args.run_id} state={state}")
        log(json.dumps(status, indent=2))
        return exit_code_for_state(state, args.expect_state)

    # 2) Discover content in RD-DMS
    types_list = [t.strip() for t in args.data_object_types.split(",")] if args.data_object_types else None
    log("Listing RD-DMS resources ...")
    resources = list_resources_all(
        rddms_host=rddms_host,
        dataspace=args.dataspace,
        token=token,
        partition=partition,
        top=args.top,
        max_items=args.max_items,
        data_object_types=types_list,
        debug=args.debug or args.trace,
        trace=args.trace,
    )
    log(f"Found {len(resources)} resources in dataspace '{args.dataspace}'.")

    # 3) Collect URIs
    uris = collect_uris(resources)
    log(f"Collected {len(uris)} unique URIs.")
    if not uris:
        log("No URIs found; nothing to build.", flush=True)
        return 3

    # 4) Build manifest via RD-DMS
    viewers = [v.strip() for v in (args.viewers or "").split(",") if v.strip()] \
              or [f"{partition}.default.viewers@{partition}.dataservices.energy"]
    owners  = [v.strip() for v in (args.owners or "").split(",") if v.strip()] \
              or [f"{partition}.default.owners@{partition}.dataservices.energy"]
    legals  = [v.strip() for v in (args.legaltags or "").split(",") if v.strip()] \
              or [f"{partition}-equinor-private-default"]
    countries = [v.strip() for v in (args.countries or "").split(",") if v.strip()] or ["NO"]

    log(f"Building manifest via RD-DMS /manifests/build (uris={len(uris)}) ...")
    manifest = build_manifest(
        osdu_host=osdu_host,
        token=token,
        partition=partition,
        uris=uris,
        viewers=viewers,
        owners=owners,
        legaltags=legals,
        other_countries=countries,
        create_missing_refs=True,
        debug=args.debug or args.trace,
        trace=args.trace,
    )
    log("Manifest built successfully.")

    if args.out:
        Path(args.out).write_text(json.dumps(manifest, indent=2))
        log(f"Manifest written to {args.out}")

    # 5) Ingest via Workflow
    if args.no_ingest:
        log("--no-ingest specified; skipping Workflow submission.")
        return 0

    log("Submitting manifest to Workflow Osdu_ingest ...")
    resp = ingest_manifest_via_workflow(
        osdu_host=osdu_host,
        partition=partition,
        token=token,
        manifest=manifest,
        debug=args.debug or args.trace,
        trace=args.trace,
    )
    log("Workflow response:\n" + json.dumps(resp, indent=2)[:4000])

    # Echo RUN_ID=<id> for easy scripting (if present)
    try:
        run_id = resp.get("runId") or resp.get("id") or resp.get("data", {}).get("runId")
        if run_id:
            log(f"RUN_ID={run_id}")
    except Exception:
        pass

    log("Done.")
    return 0


if __name__ == "__main__":
    try:
        # unbuffered stdout for immediate logs even without -u
        os.environ.setdefault("PYTHONUNBUFFERED", "1")
        sys.exit(main())
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr, flush=True)
        sys.exit(130)
    except Exception as e:
        print(f"[fatal] {e}", file=sys.stderr, flush=True)
        sys.exit(2)