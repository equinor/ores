
# -*- coding: utf-8
r"""
7genchronostrat.py

Creates a single JSON payload (Manifest) that includes:
  • ALL ChronoStratigraphy reference-data records (from a local --source-path or remote --source-url)
  • ONE WPC (StratigraphicColumnRankInterpretation) that references every record
  • Optional ChronoStratigraphicScheme record

Examples (PowerShell):
  py .\7genchronostrat.py --source-path .\ChronoStratigraphy.1.json --out .\chronostrat_manifest_ics.json --include-scheme --verbose
  py .\7genchronostrat.py --out .\chronostrat_manifest_ics.json --include-scheme --verbose
"""

import argparse, copy, json, sys
from pathlib import Path
from typing import Any, Dict, List, Union

try:
    import requests  # only needed when using --source-url
except Exception:
    requests = None

DEFAULT_URL = (
    "https://raw.githubusercontent.com/jonslo/osdu-data-data-definitions/"
    "master/ReferenceValues/Manifests/reference-data/OPEN/ChronoStratigraphy.1.json"
)

KIND_CHRONO = "osdu:wks:reference-data--ChronoStratigraphy:1.0.0"
KIND_SCHEME = "osdu:wks:reference-data--ChronoStratigraphicScheme:1.0.0"
KIND_MANIFEST = "osdu:wks:Manifest:1.0.0"
KIND_WPC = "osdu:wks:work-product-component--StratigraphicColumnRankInterpretation:1.3.0"

def _acl(owners: List[str], viewers: List[str]) -> Dict[str, Any]:
    return {"owners": owners, "viewers": viewers}

def _legal(legaltag: str, countries: List[str]) -> Dict[str, Any]:
    return {"legaltags": [legaltag], "otherRelevantDataCountries": countries}

def _id(partition: str, code: str) -> str:
    return f"{partition}:reference-data--ChronoStratigraphy:{code}:"

def _normalize_parent_ids(partition: str, parent_ids: List[str]) -> List[str]:
    out = []
    for pid in (parent_ids or []):
        try:
            if ":reference-data--ChronoStratigraphy:" in pid:
                code = pid.split(":reference-data--ChronoStratigraphy:")[1]
                code = code.split(":")[0]
                out.append(_id(partition, code))
        except Exception:
            pass
    return out

def build_wpc(partition: str, owners: List[str], viewers: List[str],
              legaltag: str, countries: List[str],
              scheme_name: str, scheme_code: str,
              chrono_ids: List[str]) -> Dict[str, Any]:
    return {
        "id": f"{partition}:work-product-component--StratigraphicColumnRankInterpretation:Global-ICS-Column:",
        "kind": KIND_WPC,
        "acl": _acl(owners, viewers),
        "legal": _legal(legaltag, countries),
        "data": {
            "Name": f"{scheme_name} ({scheme_code})",
            "StratigraphicRoleType": f"{partition}:reference-data--StratigraphicRoleType:Chronostratigraphic:",
            "ChronoStratigraphySet": chrono_ids,
            "IsDiscoverable": True
        }
    }

def build_scheme(partition: str, owners: List[str], viewers: List[str],
                 legaltag: str, countries: List[str],
                 name: str, code: str) -> Dict[str, Any]:
    return {
        "kind": KIND_SCHEME,
        "id": f"{partition}:reference-data--ChronoStratigraphicScheme:{code}:",
        "acl": _acl(owners, viewers),
        "legal": _legal(legaltag, countries),
        "data": {"Name": name, "Code": code, "Description": name}
    }

def _replace_namespace(obj: Any, namespace: str) -> Any:
    """Recursively replace {{NAMESPACE}} in all string values."""
    if isinstance(obj, str):
        return obj.replace("{{NAMESPACE}}", namespace)
    if isinstance(obj, list):
        return [_replace_namespace(x, namespace) for x in obj]
    if isinstance(obj, dict):
        return {k: _replace_namespace(v, namespace) for k, v in obj.items()}
    return obj

def _gather_records(obj: Union[Dict[str, Any], List[Any]], verbose: bool=False) -> List[Dict[str, Any]]:
    """Return ChronoStratigraphy records regardless of source layout.

    Fixed: previously the walk would add records from node['ReferenceData']
    and then re-walk the same list via `for v in node.values()`, causing
    every record to be collected twice.
    """
    found: List[Dict[str, Any]] = []
    def is_chrono(rec: Any) -> bool:
        if not isinstance(rec, dict):
            return False
        k = rec.get("kind", "")
        d = rec.get("data", {})
        return isinstance(k, str) and k.startswith("osdu:wks:reference-data--ChronoStratigraphy:") and isinstance(d, dict)
    def walk(node: Any, depth: int=0):
        if isinstance(node, list):
            for x in node:
                if is_chrono(x):
                    found.append(x)
                else:
                    walk(x, depth+1)
        elif isinstance(node, dict):
            handled_keys: set = set()
            if "ReferenceData" in node and isinstance(node["ReferenceData"], list):
                handled_keys.add("ReferenceData")
                for x in node["ReferenceData"]:
                    if is_chrono(x):
                        found.append(x)
            for k, v in node.items():
                if k not in handled_keys:
                    walk(v, depth+1)
    walk(obj)
    if verbose:
        print(f"_gather_records: collected {len(found)} ChronoStratigraphy candidates")
    return found

def main():
    ap = argparse.ArgumentParser()
    # Accept both --partition and --namespace (alias)
    ap.add_argument('--partition', default='dev', help="Data partition id (aka namespace), e.g., dev | opendes | equinor-dev")
    ap.add_argument('--namespace', default='', help="Alias for --partition")
    ap.add_argument('--owners', default='data.default.owners@dev.dataservices.energy')
    ap.add_argument('--viewers', default='data.office.global.viewers@dev.dataservices.energy')
    ap.add_argument('--legaltag', default='dev-equinor-osdu-reference-default')
    ap.add_argument('--countries', default='NO')
    ap.add_argument('--out', default='')
    ap.add_argument('--include-scheme', action='store_true')
    ap.add_argument('--scheme-name', default='International Chronostratigraphic Chart')
    ap.add_argument('--scheme-code', default='ICS-2024-12')
    ap.add_argument('--filter-scheme', default='',
                    help='Only include records from this scheme (e.g. ICS2017, GTS2020). Default: all schemes')
    ap.add_argument('--source-url', default=DEFAULT_URL)
    ap.add_argument('--source-path', default='')
    ap.add_argument('--verbose', action='store_true')
    args = ap.parse_args()

    partition = args.namespace.strip() or args.partition.strip() or 'dev'

    # Normalize and ensure defaults are actually populated
    def _listize(csv: str) -> List[str]:
        return [x.strip() for x in (csv or '').split(',') if x.strip()]
    owners  = _listize(args.owners)  or ["data.default.owners@dev.dataservices.energy"]
    viewers = _listize(args.viewers) or ["data.office.global.viewers@dev.dataservices.energy"]
    countries = [x.strip().upper()[:2] for x in (args.countries or 'NO').replace(';', ',').split(',') if x.strip()]
    if not countries: countries = ["NO"]
    legaltag = args.legaltag or "dev-equinor-osdu-reference-default"

    if args.verbose:
        print("=== Configuration ===")
        print(f"partition (namespace): {partition}")
        print(f"owners: {owners}")
        print(f"viewers: {viewers}")
        print(f"legaltag: {legaltag}")
        print(f"countries: {countries}")
        print(f"include-scheme: {args.include_scheme}  scheme: {args.scheme_name} / {args.scheme_code}")
        print(f"source-path: {args.source_path or '(none)'}")
        print(f"source-url : {args.source_url if not args.source_path else '(ignored — using source-path)'}")
        print("================================\n")

    # Load source JSON (prefer local path if provided)
    if args.source_path:
        p = Path(args.source_path)
        if not p.exists():
            print(f"ERROR: --source-path not found: {p}")
            sys.exit(2)
        if args.verbose:
            print(f"Reading local source: {p.resolve()} ({p.stat().st_size} bytes)")
        try:
            src_obj = json.loads(p.read_text(encoding='utf-8'))
        except UnicodeDecodeError:
            src_obj = json.loads(p.read_text(encoding='utf-8-sig'))
    else:
        if requests is None:
            print("ERROR: 'requests' not available. Use --source-path or install requests (py -m pip install requests)")
            sys.exit(2)
        if args.verbose:
            print(f"Fetching remote source: {args.source_url}")
        r = requests.get(args.source_url, timeout=120)
        r.raise_for_status()
        ctype = r.headers.get('Content-Type', '')
        if args.verbose and 'json' not in ctype.lower():
            print(f"WARNING: content-type is {ctype}; attempting JSON parse anyway")
        src_obj = r.json()

    # Extract all ChronoStratigraphy records
    records_in = _gather_records(src_obj, verbose=args.verbose)

    # Optional: filter to a single scheme
    filter_scheme = (args.filter_scheme or '').strip()
    if filter_scheme:
        before = len(records_in)
        records_in = [
            r for r in records_in
            if filter_scheme in (r.get('data') or {}).get('ChronoStratigraphicSchemeID', '')
        ]
        if args.verbose:
            print(f"Filtered to scheme '{filter_scheme}': {before} → {len(records_in)}")

    # Build output, deduplicating by id (last wins)
    by_id: Dict[str, Dict[str, Any]] = {}   # id → record
    for idx, item in enumerate(records_in):
        data = item.get('data') or {}
        code = data.get('Code')
        if not code:
            continue
        rid = _id(partition, code)
        pids = data.get('ParentIDs')
        norm_parents = _normalize_parent_ids(partition, pids) if pids else []

        # Deep-copy data and replace {{NAMESPACE}} placeholders
        new_data = _replace_namespace(copy.deepcopy(data), partition)
        if norm_parents:
            new_data['ParentIDs'] = norm_parents

        # Force-apply ACL & legal on every record
        by_id[rid] = {
            "kind": KIND_CHRONO,
            "id": rid,
            "acl": _acl(owners, viewers),
            "legal": _legal(legaltag, countries),
            "data": new_data
        }

    out_ref = list(by_id.values())
    all_ids = [r["id"] for r in out_ref]

    # Per-scheme stats
    from collections import Counter
    scheme_counts: Counter = Counter()
    for rec in out_ref:
        sid = rec.get('data', {}).get('ChronoStratigraphicSchemeID', '')
        scheme = sid.split('ChronoStratigraphicScheme:')[-1].rstrip(':') if 'ChronoStratigraphicScheme:' in sid else '(none)'
        scheme_counts[scheme] += 1
    if args.verbose:
        print(f"\nUnique records by scheme ({len(out_ref)} total):")
        for s, c in scheme_counts.most_common():
            print(f"  {s}: {c}")
    if all_ids[:5] and args.verbose:
        print("\nSample IDs:", *all_ids[:5], sep="\n  ")

    manifest = {
        "kind": KIND_MANIFEST,
        "acl": _acl(owners, viewers),
        "legal": _legal(legaltag, countries),
        "ReferenceData": out_ref,
        "MasterData": [],
        "Data": {"Datasets": [], "WorkProductComponents": [], "WorkProduct": {}}
    }

    if args.include_scheme:
        scheme_rec = build_scheme(partition, owners, viewers, legaltag, countries, args.scheme_name, args.scheme_code)
        manifest["ReferenceData"].append(scheme_rec)

    wpc = build_wpc(partition, owners, viewers, legaltag, countries, args.scheme_name, args.scheme_code, all_ids)
    manifest["Data"]["WorkProductComponents"].append(wpc)

    out_path = Path(args.out) if args.out else Path(__file__).resolve().parent.parent / 'strat' / 'manifest_chronostratics.json'
    out_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"\nWrote {out_path} with {len(out_ref)} ChronoStratigraphy records and 1 WPC")
    for s, c in scheme_counts.most_common():
        print(f"  {s}: {c}")
    if len(out_ref) == 0:
        print("NOTE: 0 records found. Likely causes:\n"
              "- Source JSON not reachable (proxy, auth) or not JSON\n"
              "- Source manifest layout unexpected; try --verbose and/or --source-path with a locally downloaded file\n"
              "- Wrong URL or truncated download: verify the file is the large ChronoStratigraphy.1.json")

if __name__ == '__main__':
    main()
