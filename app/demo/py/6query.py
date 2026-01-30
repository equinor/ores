#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
6query.py — ADME/OSDU manifest-aware validator & debugger
Auth, partition, and defaults intentionally mirror your ingest scripts.
What’s in here:
- Robust KQL for Airflow logs (OEPAirFlowTask) scoped to your ADME resource:
  * Matches CorrelationId OR RunId and falls back to search in Content/CodePath.
  * Printed only when --run-id is provided.
  * The script WON'T run a generic Search when you only want KQL.
- Manifest-driven checks for ReferenceData and WPCs (CBT/GeoLabelSet), with:
  * --index-diagnostics (surface index errors in Search results),
  * --verify-storage (GET each expected id in Storage),
  * --check-legal (validate all referenced LegalTags),
  * --entitlements-check (verify typical service groups, flexible matching),
  * --debug-manifests (show matched manifest files, harvested counts).
- Optional Workflow Service status fetch for a run ( --workflow-status <name> ).
Environment variables (kept identical to your other scripts):
  refresh_token [REQUIRED]
  AAD_AUTHORITY = https://login.microsoftonline.com
  OSDU_TENANT_ID = 3aa4a235-b6e2-48d5-9195-7fcf05b459b0
  OSDU_CLIENT_ID = ebd2bfee-ecba-47b7-a33c-017d0131879d
  OSDU_SCOPE = 7daee810-3f78-40c4-84c2-7a199428de18/.default openid offline_Access
  OSDU_REDIRECT_URI = https://oauth.pstmn.io/v1/callback
  OSDU_RESOURCE = (unset/None by default; enables v1 fallback only if set)
  OSDU_HOST = https://equinorswedev.energy.azure.com
  OSDU_PARTITION = dev
"""
import argparse
import base64
import glob
import json
import os
import re
from pathlib import Path
from typing import Optional, Tuple, Dict, List, Any, Iterable

import requests

# ------------------------------- helpers ------------------------------- #
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
    Auth flow:
    - Try AAD v2 (scope) first.
    - Fall back to AAD v1 (resource) only if resource_v1 is provided.
    """
    if not refresh_token:
        raise RuntimeError("Missing refresh_token")
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/x-www-form-urlencoded"})
    # v2
    if scope_v2:
        v2_url = f"{authority_base.rstrip('/')}/{tenant_id}/oauth2/v2.0/token"
        v2_form = {
            "grant_type": "refresh_token",
            "client_id": client_id,
            "refresh_token": refresh_token,
            "scope": scope_v2,
        }
        if redirect_uri_v2:
            v2_form["redirect_uri"] = redirect_uri_v2
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
    # v1
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
        "Set OSDU_SCOPE to '<GUID>/.default openid offline_Access' (v2), or "
        "set OSDU_RESOURCE to a valid API resource (v1)."
    )


def _peek_jwt(jwt_token: str) -> None:
    """Minimal peek of JWT payload (aud, azp, exp) for debugging."""
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


def headers(partition: str, token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "data-partition-id": partition,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

# ------------------------------- service calls ------------------------------- #
def call_search(host: str, partition: str, token: str, payload: Dict, timeout: int = 60) -> requests.Response:
    url = f"{host.rstrip('/')}/api/search/v2/query"
    return requests.post(url, headers=headers(partition, token), data=json.dumps(payload), timeout=timeout)


def get_record_storage(host: str, partition: str, token: str, record_id: str, timeout: int = 30) -> requests.Response:
    url = f"{host.rstrip('/')}/api/storage/v2/records/{record_id}"
    return requests.get(url, headers=headers(partition, token), timeout=timeout)


def list_groups(host: str, partition: str, token: str) -> requests.Response:
    url = f"{host.rstrip('/')}/api/entitlements/v2/groups"
    return requests.get(url, headers=headers(partition, token), timeout=60)


def get_legal_tag(host: str, partition: str, token: str, tag_name: str) -> requests.Response:
    url = f"{host.rstrip('/')}/api/legal/v1/legaltags/{tag_name}"
    return requests.get(url, headers=headers(partition, token), timeout=30)


def get_workflow_run_status(host: str, partition: str, token: str,
                            workflow_name: str, run_id: str, timeout: int = 30) -> requests.Response:
    url = f"{host.rstrip('/')}/api/workflow/v1/workflow/{workflow_name}/workflowRun/{run_id}"
    return requests.get(url, headers=headers(partition, token), timeout=timeout)

# ------------------------------- manifest parsing ------------------------------- #
def safe_get(d: Dict[str, Any], path: List[str]) -> Optional[Any]:
    cur: Any = d
    try:
        for k in path:
            if isinstance(cur, dict) and k in cur:
                cur = cur[k]
            else:
                return None
        return cur
    except Exception:
        return None


def extract_name(rec: Dict[str, Any]) -> Optional[str]:
    return safe_get(rec, ["data", "Name"]) or safe_get(rec, ["data", "name"]) or None


def _iter_manifest_files(patterns: Iterable[str], debug: bool = False) -> List[Path]:
    matched: List[Path] = []
    for pat in patterns:
        for fp in glob.glob(pat):
            p = Path(fp).resolve()
            if p.exists():
                matched.append(p)
    if debug:
        print("=== Manifest debug ===")
        if matched:
            for p in matched:
                print(f" matched: {p}")
        else:
            print(" no files matched the provided patterns.")
        print("======================\n")
    return matched


# ---- NEW: fallback harvester for flattened "kind/id/legal/Name" files ---- #
_FLAT_KIND_RE = re.compile(r"^\s*kind\s+(\S+)\s*$", re.IGNORECASE)
_FLAT_ID_RE = re.compile(r"^\s*id\s+(\S+)\s*$", re.IGNORECASE)
_FLAT_LEGAL_RE = re.compile(r"^\s*legal\s+legaltags\s+(\S+)\s*$", re.IGNORECASE)
_FLAT_NAME_RE = re.compile(r"^\s*data\s+Name\s+(.+?)\s*$", re.IGNORECASE)

def _harvest_flat_manifest_text(raw: str,
                                created_kinds: set,
                                legal_tags: set,
                                add_ref) -> None:
    """
    Consume a flattened manifest dump like:
      kind osdu:wks:reference-data--PropertyType:1.0.0
      id dev:reference-data--PropertyType:Oil.Volume.Bulk:
      legal legaltags dev-equinor-osdu-reference-default
      data Name Oil.Volume.Bulk
    and push (kind, id) to ref_ids, kinds to created_kinds, tags to legal_tags.
    """
    current_kind: Optional[str] = None
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue

        m_kind = _FLAT_KIND_RE.match(line)
        if m_kind:
            k = m_kind.group(1)
            # ignore the top-level manifest kind
            if k and k != "osdu:wks:Manifest:1.0.0":
                current_kind = k
                created_kinds.add(k)
            else:
                current_kind = None
            continue

        m_id = _FLAT_ID_RE.match(line)
        if m_id:
            rid = m_id.group(1)
            # associate with last seen non-Manifest kind
            if current_kind and rid:
                add_ref(current_kind, rid)
            continue

        m_legal = _FLAT_LEGAL_RE.match(line)
        if m_legal:
            t = m_legal.group(1)
            if t:
                legal_tags.add(t)
            continue

        # Name not required for RefData; kept for potential WPC detection later
        # m_name = _FLAT_NAME_RE.match(line)
        # if m_name:
        #     _ = m_name.group(1)
        #     continue


def build_queries_from_manifests(paths: List[str],
                                 cbt_version: str,
                                 geo_version: str,
                                 debug: bool = False
                                 ) -> Tuple[Dict[str, Dict[str, Any]], List[str], List[str]]:
    """
    Return (qmap, created_kinds, legal_tags).
    qmap: dict keyed by kind (or kind-version),
    value has 'query', 'limit', 'expect' (ids for ref-data, names for WPCs).
    """
    cbt_names: set[str] = set()
    gls_names: set[str] = set()
    legal_tags: set[str] = set()
    created_kinds: set[str] = set()
    ref_ids_by_kind: Dict[str, set[str]] = {}

    def add_ref(kind_version: str, rec_id: str):
        if not rec_id:
            return
        ref_ids_by_kind.setdefault(kind_version, set()).add(rec_id)

    for p in _iter_manifest_files(paths, debug=debug):
        try:
            raw = p.read_text(encoding="utf-8")
        except Exception as e:
            if debug:
                print(f"[read-error] {p}: {e}")
            continue

        # First: try canonical JSON parsing
        try:
            doc = json.loads(raw)
            parsed_as_json = True
        except Exception:
            doc = None
            parsed_as_json = False

        if parsed_as_json and isinstance(doc, dict):
            blocks: List[Dict[str, Any]] = []
            # Canonical 'data' root
            if isinstance(doc.get("data"), dict):
                d = doc["data"]
                # ReferenceData
                for rd in d.get("ReferenceData", []) or []:
                    k = rd.get("kind", "")
                    rec_id = rd.get("id", "")
                    if k:
                        created_kinds.add(k)
                    if k and rec_id:
                        add_ref(k, rec_id)
                # WPCs at data.WorkProductComponents
                for wpc in d.get("WorkProductComponents", []) or []:
                    blocks.append(wpc)
                    if wpc.get("kind"):
                        created_kinds.add(wpc["kind"])
                # ADME canonical WPC path
                data_block = d.get("Data", {})
                if isinstance(data_block, dict):
                    for wpc in data_block.get("WorkProductComponents", []) or []:
                        blocks.append(wpc)
                        if wpc.get("kind"):
                            created_kinds.add(wpc["kind"])
            # Legacy 'Data' root
            elif isinstance(doc.get("Data"), dict):
                D = doc["Data"]
                for rd in D.get("ReferenceData", []) or []:
                    k = rd.get("kind", "")
                    rec_id = rd.get("id", "")
                    if k:
                        created_kinds.add(k)
                    if k and rec_id:
                        add_ref(k, rec_id)
                for wpc in D.get("WorkProductComponents", []) or []:
                    blocks.append(wpc)
                    if wpc.get("kind"):
                        created_kinds.add(wpc["kind"])
            # Single record
            elif "kind" in doc and "data" in doc:
                blocks.append(doc)
                created_kinds.add(str(doc.get("kind", "")))

            # Harvest WPCs + LegalTags
            for w in blocks:
                k = w.get("kind", "")
                dd = w.get("data", {}) or {}
                nm = dd.get("Name")
                lg = (w.get("legal") or {}).get("legaltags", [])
                for l in lg or []:
                    if isinstance(l, str) and l:
                        legal_tags.add(l)
                if "ColumnBasedTable" in k and nm:
                    cbt_names.add(nm)
                if "GeoLabelSet" in k and nm:
                    gls_names.add(nm)
            if debug:
                print(f"- {p.name}: [JSON] ref-ids={sum(len(v) for v in ref_ids_by_kind.values())}, "
                      f"WPCs={(len(blocks))}, legalTags={len(legal_tags)}")
        else:
            # Fallback: flattened manifest dump (no JSON)
            _harvest_flat_manifest_text(raw, created_kinds, legal_tags, add_ref)
            if debug:
                print(f"- {p.name}: [FLAT] ref-ids={sum(len(v) for v in ref_ids_by_kind.values())}, "
                      f"legalTags={len(legal_tags)}")

    def _or_vals(field: str, values: set[str]) -> Optional[str]:
        if not values:
            return None
        parts = [f'{field}:"{v}"' for v in sorted(values)]
        return "(" + " OR ".join(parts) + ")"

    qmap: Dict[str, Dict[str, Any]] = {}

    # WPC — ColumnBasedTable by Name (and legal tag filter if present)
    if cbt_names:
        q = _or_vals("data.Name", cbt_names)
        if legal_tags:
            q += " AND legal.legaltags:(" + " ".join(sorted(legal_tags)) + ")"
        kind = f"osdu:wks:work-product-component--ColumnBasedTable:{cbt_version}"
        qmap[kind] = {"query": q, "limit": 200, "expect": cbt_names}

    # WPC — GeoLabelSet by Name (and legal tag filter if present)
    if gls_names:
        q = _or_vals("data.Name", gls_names)
        if legal_tags:
            q += " AND legal.legaltags:(" + " ".join(sorted(legal_tags)) + ")"
        kind = f"osdu:wks:work-product-component--GeoLabelSet:{geo_version}"
        qmap[kind] = {"query": q, "limit": 500, "expect": gls_names}

    # Reference Data — exact ids by kind
    for kind_version, ids in ref_ids_by_kind.items():
        if not ids:
            continue
        id_terms = [f'id:"{rid}"' for rid in sorted(ids)]
        qmap[kind_version] = {
            "query": "(" + " OR ".join(id_terms) + ")",
            "limit": max(200, len(ids) + 10),
            "expect": ids
        }

    if debug:
        print("\n=== Harvest summary ===")
        print(f" created_kinds : {len(created_kinds)}")
        for k, s in list(ref_ids_by_kind.items())[:5]:
            print(f"  - {k}: {len(s)} ids (showing up to 3) -> {list(sorted(s))[:3]}")
        print(f" WPC CBT names : {len(cbt_names)}")
        print(f" WPC Geo names : {len(gls_names)}")
        print("=======================\n")

    return qmap, sorted(created_kinds), sorted(legal_tags)

# ---------------------------- diagnostics helpers ---------------------------- #
# Accept broader alternates; names vary across environments.
REQUIRED_SERVICE_GROUPS = {
    "service.storage.access": (
        "service.storage.user", "service.storage.creator", "service.storage.viewer", "service.storage.viewers"
    ),
    "service.search.user": ("service.search.user", "service.search.viewer", "service.search.viewers"),
    "service.schema.view": ("service.schema-service.viewer", "service.schema-service.viewers", "service.schema.user"),
    "service.workflow.create": ("service.workflow.creator", "service.workflow.user"),
}

def analyze_entitlements(groups_json: Dict[str, Any]) -> Dict[str, List[str]]:
    names = set()
    raw = groups_json.get("groups", groups_json if isinstance(groups_json, list) else [])
    for g in raw:
        n = (g.get("name") or g.get("email") or g.get("id") or "").lower()
        if n:
            names.add(n)
    missing: Dict[str, List[str]] = {}
    for label, alts in REQUIRED_SERVICE_GROUPS.items():
        if not any(any(a in n for a in alts) for n in names):
            missing[label] = list(alts)
    return missing


def summarize_index_errors(hits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    bad: List[Dict[str, Any]] = []
    for h in hits or []:
        ix = h.get("index")
        if isinstance(ix, dict):
            code = ix.get("statusCode")
            if isinstance(code, int) and code != 200:
                bad.append({
                    "id": h.get("id"),
                    "statusCode": code,
                    "trace": ix.get("trace"),
                    "lastUpdateTime": ix.get("lastUpdateTime")
                })
    return bad


def print_kql_for_runid(run_id: str, resource_name: Optional[str] = None) -> None:
    """
    Print a single, resource-scoped KQL block that returns ONLY relevant rows
    for the given runId from OEPAirFlowTask:
    - Filters by ResourceName if provided.
    - Matches CorrelationId OR RunId, and falls back to search in Content/CodePath.
    See: Microsoft OEPAirFlowTask sample queries and columns reference.
    """
    rn = resource_name or "<your-adme-resource-name>"
    print("\n=== Azure Monitor KQL (Airflow logs for this runId) ===")
    print(f"""let runId = "{run_id}";
let adme = "{rn}";
OEPAirFlowTask
\
 extend ResourceName = tostring(split(_ResourceId, "/")[-1])
\
 where ResourceName == adme
\
 where CorrelationId == runId or RunId == runId
 or tostring(Content) has runId or tostring(CodePath) has runId
\
 project TimeGenerated, DagName, LogLevel, DagTaskName, CodePath, Content
\
 order by TimeGenerated desc
========================================
""")


# ----------------------------------- main ----------------------------------- #
def main():
    ap = argparse.ArgumentParser(description="Query/validate ADME/OSDU by manifests and surface debug info (index, entitlements, legal, Airflow KQL).")
    # diagnostics
    ap.add_argument("--print-token", action="store_true", help="Print token peek (aud/azp/exp).")
    ap.add_argument("--whoami", action="store_true", help="Show entitlements (first ~20 groups).")
    ap.add_argument("--entitlements-check", action="store_true", help="Check required service groups for ingestion/search.")
    ap.add_argument("--index-diagnostics", action="store_true", help="Add 'index' to returnedFields and summarize indexer errors.")
    ap.add_argument("--check-legal", action="store_true", help="Validate referenced LegalTags via Legal v1.")
    ap.add_argument("--debug-manifests", action="store_true", help="Print matched files, load errors, and harvested counts.")
    # Airflow / KQL
    ap.add_argument("--run-id", default=None, help="Print resource-scoped KQL for this Workflow/Airflow runId.")
    ap.add_argument("--resource-name", default=None, help="ADME resource name to scope KQL (recommended).")
    ap.add_argument("--workflow-status", metavar="WORKFLOW_NAME",
                    help="Call Workflow service to fetch run status for --run-id (e.g., Osdu_ingest).")
    # partition override (env default: dev)
    ap.add_argument("--partition", default=getenv("OSDU_PARTITION", "dev"),
                    help="SRN namespace / data-partition-id (default: dev)")
    # generic search
    ap.add_argument("--kind", default="osdu:*:*:*", help="Kind to search (generic mode).")
    ap.add_argument("--query", default=None, help="Free-text query string for generic mode.")
    ap.add_argument("--limit", type=int, default=50, help="Limit per search (default: 50).")
    # WPC schema versions
    ap.add_argument("--cbt-version", default="1.3.0", help="ColumnBasedTable version (default 1.3.0).")
    ap.add_argument("--geo-version", default="1.0.0", help="GeoLabelSet version (default 1.0.0).")
    # manifest-driven mode
    ap.add_argument("--from-manifests", nargs="+", help="Manifest file(s) or globs.")
    ap.add_argument("--show-created-kinds", action="store_true", help="List kinds discovered in manifests.")
    # output
    ap.add_argument("--summary", action="store_true", help="Print summary with ids and names.")
    ap.add_argument("--export", default=None, help="Optional path to export raw JSON results.")
    # storage verification
    ap.add_argument("--verify-storage", action="store_true", help="GET each expected id via Storage v2 and report.")

    args = ap.parse_args()

    # Required env
    refresh_token = getenv("refresh_token")
    if not refresh_token:
        raise SystemExit("Missing env var 'refresh_token'.")

    # Env defaults
    authority_base = getenv("AAD_AUTHORITY", "https://login.microsoftonline.com")
    tenant_id = getenv("OSDU_TENANT_ID", "3aa4a235-b6e2-48d5-9195-7fcf05b459b0")
    client_id = getenv("OSDU_CLIENT_ID", "ebd2bfee-ecba-47b7-a33c-017d0131879d")
    scope_v2 = getenv("OSDU_SCOPE", "7daee810-3f78-40c4-84c2-7a199428de18/.default openid offline_Access")
    redirect_uri_v2 = getenv("OSDU_REDIRECT_URI", "https://oauth.pstmn.io/v1/callback")
    resource_v1 = getenv("OSDU_RESOURCE", None)  # v1 fallback only if provided
    host = getenv("OSDU_HOST", "https://equinorswedev.energy.azure.com")
    partition = (args.partition or getenv("OSDU_PARTITION", "dev")).strip() or "dev"

    print("=== Config ===")
    print(f"Authority : {authority_base}")
    print(f"Tenant ID : {tenant_id}")
    print(f"Client ID : {client_id}")
    print(f"Host : {host}")
    print(f"Partition : {partition}")
    if args.from_manifests:
        print("Mode : manifest-driven (exact ids/names from files)")
    else:
        print("Mode : generic (use --from-manifests for exact checks)")

    # Mint token
    print("Minting access_token from refresh_token ...")
    token, _expires_in = get_access_token_from_refresh_token(
        refresh_token=refresh_token,
        tenant_id=tenant_id,
        client_id=client_id,
        authority_base=authority_base,
        scope_v2=scope_v2,
        resource_v1=resource_v1,
        redirect_uri_v2=redirect_uri_v2,
    )
    if args.print_token:
        _peek_jwt(token)

    # When --run-id is present, print ONLY relevant, resource-scoped KQL and optionally call Workflow status.
    if args.run_id:
        print_kql_for_runid(args.run_id, resource_name=args.resource_name)
        if args.workflow_status:
            r = get_workflow_run_status(host, partition, token, args.workflow_status, args.run_id)
            print(f"[GET {r.status_code}] /workflow/v1/workflow/{args.workflow_status}/workflowRun/{args.run_id}")
            try:
                print(json.dumps(r.json(), indent=2))
            except Exception:
                print(r.text[:4000])
        # Important: Return here so we DO NOT run generic Search afterwards.
        return

    returned_fields = ["id", "kind", "data.Name", "legal.legaltags", "meta.DataSource"]
    if args.index_diagnostics:
        returned_fields.append("index")

    all_results: Dict[str, List[Dict[str, Any]]] = {}
    totals: Dict[str, Dict[str, Any]] = {}

    # whoami and optional entitlements check
    entitlements_json = None
    if args.whoami or args.entitlements_check:
        r = list_groups(host, partition, token)
        print(f"[GET {r.status_code}] /entitlements/v2/groups")
        try:
            entitlements_json = r.json()
            groups = entitlements_json.get("groups", entitlements_json)
            preview = [{"name": x.get("name"), "type": x.get("type")} for x in groups[:20]]
            print(json.dumps(preview, indent=2))
        except Exception:
            print(r.text[:4000])
        print()
        if args.entitlements_check and entitlements_json:
            missing = analyze_entitlements(entitlements_json)
            if missing:
                print(">>> Missing expected service entitlements for this partition:")
                for label, alts in missing.items():
                    print(f" - {label}: accepts any of {alts}")
                print("(Adjust memberships and retry ingestion/search.)\n")
            else:
                print("Service entitlements: OK (required groups present)\n")

    # Manifest-driven mode
    if args.from_manifests:
        qmap, created_kinds, legal_tags = build_queries_from_manifests(
            args.from_manifests, args.cbt_version, args.geo_version, debug=args.debug_manifests
        )
        if args.show_created_kinds:
            print("=== Created kinds discovered in manifests ===")
            for k in created_kinds:
                print(f" - {k}")
            print("===========================================\n")

        if args.check_legal and legal_tags:
            print("=== LegalTag validation ===")
            bad_tags = []
            for t in legal_tags:
                resp = get_legal_tag(host, partition, token, t)
                if not resp.ok:
                    bad_tags.append((t, resp.status_code))
                    print(f" - {t}: [GET {resp.status_code}] NOT FOUND/INVALID")
                else:
                    print(f" - {t}: [GET {resp.status_code}] OK")
            if bad_tags:
                print("Some LegalTags are invalid; Storage will reject records using them.\n")
            else:
                print("All referenced LegalTags are valid.\n")

        if not qmap:
            print("[warn] No queries could be derived from --from-manifests inputs.")
            return

        for kind, spec in qmap.items():
            payload = {"kind": kind, "limit": spec.get("limit", args.limit), "returnedFields": returned_fields}
            if spec.get("query"):
                payload["query"] = spec["query"]
            r = call_search(host, partition, token, payload)
            body = r.json() if r.headers.get("content-type", "").lower().startswith("application/json") else {"raw": r.text}
            print(f"[POST {r.status_code}] /search/v2/query kind={kind}\n{json.dumps(body, indent=2)[:8000]}\n")
            hits = body.get("results", body.get("Results", []))
            hits = hits if isinstance(hits, list) else []
            all_results[kind] = hits

            if args.index_diagnostics:
                bad = summarize_index_errors(hits)
                if bad:
                    print(">>> Index diagnostics: Some hits report indexing issues:")
                    for b in bad[:10]:
                        print(f" - id={b.get('id')} status={b.get('statusCode')}")
                        tr = b.get("trace")
                        if isinstance(tr, list) and tr:
                            print(f"   trace[0]: {str(tr[0])[:300]}")
                    if len(bad) > 10:
                        print(f" ... and {len(bad)-10} more with issues\n")
                else:
                    print("Index diagnostics: no per-hit index errors reported.\n")

            expect = spec.get("expect", set())
            present_ids = set()
            present_names = set()
            for rec in hits:
                rid = rec.get("id")
                nm = extract_name(rec)
                if rid:
                    present_ids.add(rid)
                if nm:
                    present_names.add(nm)
            if kind.startswith("osdu:wks:work-product-component--"):
                matched = len(expect & present_names) if expect else len(hits)
                totals[kind] = {"wanted": len(expect), "found": matched, "missing": sorted(expect - present_names)}
            else:
                matched = len(expect & present_ids) if expect else len(hits)
                totals[kind] = {"wanted": len(expect), "found": matched, "missing": sorted(expect - present_ids)}

        if args.verify_storage:
            print("\n=== Storage v2 verification (GET by id) ===")
            missing = []
            for kind, spec in qmap.items():
                if kind.startswith("osdu:wks:work-product-component--"):
                    continue
                for rid in sorted(spec.get("expect", [])):
                    resp = get_record_storage(host, partition, token, rid)
                    if not resp.ok:
                        missing.append(rid)
                        print(f" - {rid}: [GET {resp.status_code}] not found")
            if not missing:
                print("All expected record ids resolved via Storage v2.")
            else:
                print(f"{len(missing)} record ids not found by Storage v2.")
            print("============================================\n")

        print("=== Ingestion Check Summary ===")
        for kind, info in totals.items():
            print(f"{kind} -> wanted={info['wanted']} found={info['found']}")
            if info["missing"]:
                print(f"  missing ({len(info['missing'])}):")
                for mid in info["missing"][:25]:
                    print(f"   - {mid}")
                if len(info["missing"]) > 25:
                    print(f"   ... and {len(info['missing']) - 25} more")
        print("================================\n")

        if args.export:
            with open(args.export, "w", encoding="utf-8") as f:
                json.dump(all_results, f, indent=2)
            print(f"Exported raw results to: {args.export}")

        if args.summary:
            print("=== Summary (kind -> first 10 rows: id, Name) ===")
            for k, recs in all_results.items():
                if recs:
                    for rec in recs[:10]:
                        rid = rec.get("id", "")
                        nm = extract_name(rec) or ""
                        print(f"{k}\t{rid}\t{nm}")
            print("===============================================\n")
        return

    # Generic mode (only if you didn’t pass --run-id)
    payload = {"kind": args.kind, "limit": args.limit, "returnedFields": returned_fields}
    if args.query:
        payload["query"] = args.query
    r = call_search(host, partition, token, payload)
    body = r.json() if r.headers.get("content-type", "").lower().startswith("application/json") else {"raw": r.text}
    print(f"[POST {r.status_code}] /search/v2/query kind={args.kind}\n{json.dumps(body, indent=2)[:8000]}\n")
    if args.export:
        with open(args.export, "w", encoding="utf-8") as f:
            json.dump(body, f, indent=2)
        print(f"Exported raw result to: {args.export}")

if __name__ == "__main__":
    main()