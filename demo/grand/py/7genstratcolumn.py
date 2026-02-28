
# build_strat_column_from_manifest.py
# Build a Stratigraphic Column (Chronostratigraphy-focused) from an existing ChronoStratigraphy manifest.
# It emits a single WKS Manifest with:
#   - ReferenceData: StratigraphicRoleType:Chronostratigraphic (optional)
#   - WorkProductComponents:
#       * StratigraphicUnitInterpretation (one per chrono unit)
#       * StratigraphicColumnRankInterpretation (one per rank)
#       * StratigraphicColumn (one per column instance)
#
# Schema alignment (see OSDU WKS docs):
#  - StratigraphicColumn (WPC) lists StratigraphicColumnRankInterpretation records (coarse -> fine)
#  - StratigraphicColumnRankInterpretation (WPC) lists StratigraphicUnitInterpretation (ordered top->base)
#  - StratigraphicUnitInterpretation (WPC) links to ChronoStratigraphy ref records via ChronoStratigraphyID
#
# Usage (PowerShell):
# py .\build_strat_column_from_manifest.py `
#   --in-manifest .\manifest_chronostratics.json `
#   --include-scheme `
#   --verbose
#
# You can override defaults via switches (see argparse) or environment variable:
#   $env:OSDU_SCHEME_ID = "dev:reference-data--ChronoStratigraphicScheme:ICS2017:"

import argparse, json, re, sys, os
from pathlib import Path
from typing import Any, Dict, List, Tuple

def _log(msg: str, verbose: bool):
    if verbose:
        print(msg)

def sanitize_token(s: str) -> str:
    s = s.strip()
    s = re.sub(r"[^A-Za-z0-9._:-]+", "-", s)
    s = re.sub(r"-+", "-", s)
    return s

def make_acl(owners: List[str], viewers: List[str]) -> Dict:
    return {"owners": owners, "viewers": viewers}

def make_legal(legaltags: List[str], countries: List[str]) -> Dict:
    return {"legaltags": legaltags, "otherRelevantDataCountries": countries}

def load_json_any(path: Path) -> Any:
    txt = path.read_text(encoding="utf-8")
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        return json.loads(path.read_text(encoding="utf-8-sig"))

def extract_ref_objects(obj: Any, kind_prefix: str) -> List[Dict]:
    out = []
    if isinstance(obj, dict):
        for r in (obj.get("ReferenceData") or []):
            if isinstance(r, dict) and str(r.get("kind", "")).startswith(kind_prefix):
                out.append(r)
    elif isinstance(obj, list):
        for r in obj:
            if isinstance(r, dict) and str(r.get("kind", "")).startswith(kind_prefix):
                out.append(r)
    return out

# tolerant getters for rank and ages
def get_rank(data: Dict) -> str:
    h = data.get("ChronostratigraphicHierarchy") or data.get("ChronoStratigraphicHierarchy") or {}
    for k in ("Rank", "ChronostratigraphicRank", "ChronoStratigraphicRank", "RankName"):
        v = h.get(k) if isinstance(h, dict) else None
        if v:
            return str(v)
    for k in ("Rank", "RankName"):
        if k in data and data[k]:
            return str(data[k])
    return ""

def get_ma(data: Dict, top: bool) -> float:
    c_top = ("TopMa", "TopMA", "TopAgeMa", "TopAge", "Top")
    c_base = ("BaseMa", "BaseMA", "BaseAgeMa", "BaseAge", "Base")
    for k in (c_top if top else c_base):
        v = data.get(k)
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            try:
                return float(v)
            except:
                pass
    return None

def get_scheme_id(data: Dict) -> str:
    for k in ("ChronoStratigraphicSchemeID", "ChronostratigraphicSchemeID", "SchemeID"):
        v = data.get(k)
        if isinstance(v, str) and v:
            return v
    h = data.get("ChronostratigraphicHierarchy") or data.get("ChronoStratigraphicHierarchy") or {}
    for k in ("SchemeID", "ChronoStratigraphicSchemeID", "ChronostratigraphicSchemeID"):
        v = h.get(k) if isinstance(h, dict) else None
        if isinstance(v, str) and v:
            return v
    return ""

def default_sort_key(unit: Dict) -> Tuple:
    t = unit.get("top_ma"); b = unit.get("base_ma")
    if t is not None:
        return (t, b if b is not None else 0.0, unit["name"])
    if unit.get("order") is not None:
        return (unit["order"], unit["name"])
    return (unit["name"],)

def build_unit_interp(partition: str, owners: List[str], viewers: List[str], legaltags: List[str], countries: List[str],
                      column_token: str, unit: Dict, role_type_id: str, include_scheme: bool,
                      scheme_id: str, scheme_name: str, scheme_code: str) -> Dict:
    name = unit["name"]
    unit_token = sanitize_token(name)
    rec_id = f"{partition}:work-product-component--StratigraphicUnitInterpretation:{column_token}-{unit_token}:"
    data = {
        "Name": name,
        "StratigraphicRoleTypeID": role_type_id,
        "ChronoStratigraphyID": unit["chrono_id"],
    }
    rec = {
        "id": rec_id,
        "kind": "osdu:wks:work-product-component--StratigraphicUnitInterpretation:1.3.0",
        "acl": make_acl(owners, viewers),
        "legal": make_legal(legaltags, countries),
        "data": data,
    }
    if include_scheme:
        rec.setdefault("tags", {})
        rec["tags"].update({
            "ChronoStratigraphicSchemeID": scheme_id,
            "ChronoStratigraphicSchemeName": scheme_name,
            "ChronoStratigraphicSchemeCode": scheme_code
        })
    return rec

def build_rank_interp(partition: str, owners: List[str], viewers: List[str], legaltags: List[str], countries: List[str],
                      column_token: str, rank_name: str, role_type_id: str, unit_interp_ids: List[str],
                      include_scheme: bool, scheme_id: str, scheme_name: str, scheme_code: str) -> Dict:
    rank_token = sanitize_token(rank_name or "Unspecified")
    rec_id = f"{partition}:work-product-component--StratigraphicColumnRankInterpretation:{column_token}-Chrono-{rank_token}:"
    data = {
        "Name": f"Chronostratigraphic {rank_name or 'Unspecified'}",
        "StratigraphicRoleTypeID": role_type_id,
        "RankName": rank_name or "Unspecified",
        "StratigraphicUnitInterpretationSet": unit_interp_ids,  # ordered top -> base
    }
    rec = {
        "id": rec_id,
        "kind": "osdu:wks:work-product-component--StratigraphicColumnRankInterpretation:1.3.0",
        "acl": make_acl(owners, viewers),
        "legal": make_legal(legaltags, countries),
        "data": data,
    }
    if include_scheme:
        rec.setdefault("tags", {})
        rec["tags"].update({
            "ChronoStratigraphicSchemeID": scheme_id,
            "ChronoStratigraphicSchemeName": scheme_name,
            "ChronoStratigraphicSchemeCode": scheme_code
        })
    return rec

def build_column_wpc(partition: str, owners: List[str], viewers: List[str], legaltags: List[str], countries: List[str],
                     column_name: str, rank_interp_ids: List[str], validity_id: str, vcs_id: str,
                     include_scheme: bool, scheme_id: str, scheme_name: str, scheme_code: str) -> Dict:
    column_token = sanitize_token(column_name)
    rec_id = f"{partition}:work-product-component--StratigraphicColumn:{column_token}:"
    data = {
        "Name": column_name,
        "StratigraphicColumnRankInterpretationSet": rank_interp_ids,
        "StratigraphicColumnValidityAreaType": validity_id,
        "ValueChainStatusType": vcs_id,
    }
    rec = {
        "id": rec_id,
        "kind": "osdu:wks:work-product-component--StratigraphicColumn:1.2.0",
        "acl": make_acl(owners, viewers),
        "legal": make_legal(legaltags, countries),
        "data": data,
    }
    if include_scheme:
        rec.setdefault("tags", {})
        rec["tags"].update({
            "ChronoStratigraphicSchemeID": scheme_id,
            "ChronoStratigraphicSchemeName": scheme_name,
            "ChronoStratigraphicSchemeCode": scheme_code
        })
    return rec

def build_role_type_record(partition: str, owners: List[str], viewers: List[str], legaltags: List[str], countries: List[str],
                           role_name: str = "Chronostratigraphic") -> Dict:
    rec_id = f"{partition}:reference-data--StratigraphicRoleType:{sanitize_token(role_name)}:"
    return {
        "id": rec_id,
        "kind": "osdu:wks:reference-data--StratigraphicRoleType:1.0.0",
        "acl": make_acl(owners, viewers),
        "legal": make_legal(legaltags, countries),
        "data": {
            "Name": role_name,
            "ShortName": role_name,
            "Description": f"Stratigraphic role type: {role_name}",
            "Source": "OSDU-Generated for Column Manifest"
        }
    }

def main():
    ap = argparse.ArgumentParser(description="Build a Stratigraphic Column manifest from an existing ChronoStrat manifest")

    # Your preferred defaults
    ap.add_argument('--partition', default='dev', help="Data partition id (aka namespace), e.g., dev | opendes | equinor-dev")
    ap.add_argument('--namespace', default='', help="Alias for --partition")
    ap.add_argument('--owners', default='data.default.owners@dev.dataservices.energy')
    ap.add_argument('--viewers', default='data.office.global.viewers@dev.dataservices.energy')
    ap.add_argument('--legaltag', default='dev-equinor-osdu-reference-default')
    ap.add_argument('--countries', default='NO')
    ap.add_argument('--out', default='manifest_stratcolumn.json')
    ap.add_argument('--include-scheme', action='store_true')
    ap.add_argument('--verbose', action='store_true')

    # Inputs and column defaults
    ap.add_argument('--in-manifest', required=True, help="Path to input ChronoStratigraphy manifest")
    ap.add_argument('--column-name', default='ChronoStratigraphicScheme:ICS2017')

    # Scheme defaults (as requested)
    ap.add_argument('--scheme-id', default='dev:reference-data--ChronoStratigraphicScheme:ICS2017:',
                    help="ChronoStratigraphicScheme id (default: dev:...:ICS2017:)")
    ap.add_argument('--scheme-name', default='International Chronostratigraphic Chart')
    ap.add_argument('--scheme-code', default='ICS-2024-12')

    # Optional reference-data id defaults
    ap.add_argument('--validity', default='', help="e.g., dev:reference-data--StratigraphicColumnValidityAreaType:field:")
    ap.add_argument('--vcs', default='', help="e.g., dev:reference-data--ValueChainStatusType:Production:")
    ap.add_argument('--emit-role-type', choices=['yes','no'], default='yes')

    args = ap.parse_args()
    verbose = args.verbose

    # Allow env override for scheme id
    if os.getenv('OSDU_SCHEME_ID'):
        args.scheme_id = os.getenv('OSDU_SCHEME_ID')

    # Resolve partition/namespace
    partition = args.namespace or args.partition
    owners = [s.strip() for s in str(args.owners).split(",") if s.strip()]
    viewers = [s.strip() for s in str(args.viewers).split(",") if s.strip()]
    legaltags = [args.legaltag]
    countries = [s.strip() for s in str(args.countries).split(",") if s.strip()]

    _log(f"Partition={partition} | Owners={owners} | Viewers={viewers} | LegalTags={legaltags} | Countries={countries}", verbose)
    _log(f"ColumnName={args.column_name} | SchemeID={args.scheme_id} | IncludeSchemeTags={args.include_scheme}", verbose)

    obj = load_json_any(Path(args.in_manifest))

    # Collect ChronoStratigraphy reference records from input
    chrono_refs = extract_ref_objects(obj, "osdu:wks:reference-data--ChronoStratigraphy:")
    if not chrono_refs and isinstance(obj, list):
        chrono_refs = [r for r in obj if isinstance(r, dict) and str(r.get("kind","")).startswith("osdu:wks:reference-data--ChronoStratigraphy:")]

    if not chrono_refs:
        print("No ChronoStratigraphy reference-data records found in input.", file=sys.stderr)
        sys.exit(1)

    # Filter by scheme when present on records
    filtered = []
    for r in chrono_refs:
        data = r.get("data", {})
        sch = get_scheme_id(data)
        if sch and sch != args.scheme_id:
            continue
        filtered.append(r)
    if not filtered:
        # If scheme id missing on records, include all
        filtered = chrono_refs

    # Normalize units
    units: List[Dict] = []
    for r in filtered:
        data = r.get("data", {})
        name = data.get("Name") or data.get("DefaultName") or r.get("id","").split(":")[-2]
        rank = get_rank(data)
        top_ma = get_ma(data, top=True)
        base_ma = get_ma(data, top=False)
        units.append({
            "chrono_id": r.get("id"),
            "name": str(name),
            "rank": str(rank or ""),
            "top_ma": top_ma,
            "base_ma": base_ma,
            "order": None
        })

    if not units:
        print("ChronoStratigraphy records found, but no usable Name/Rank fields.", file=sys.stderr)
        sys.exit(2)

    # Group by rank & sort within rank
    ranks: Dict[str, List[Dict]] = {}
    for u in units:
        ranks.setdefault(u["rank"], []).append(u)
    for rk, lst in ranks.items():
        lst.sort(key=default_sort_key)

    # Build outputs
    column_token = sanitize_token(args.column_name)
    role_type_id = f"{partition}:reference-data--StratigraphicRoleType:Chronostratigraphic:"

    unit_records: List[Dict] = []
    unit_id_by_key: Dict[Tuple[str, str], str] = {}
    for rk, lst in ranks.items():
        for u in lst:
            rec = build_unit_interp(partition, owners, viewers, legaltags, countries,
                                    column_token, u, role_type_id, args.include_scheme,
                                    args.scheme_id, args.scheme_name, args.scheme_code)
            unit_records.append(rec)
            unit_id_by_key[(rk, u["name"])] = rec["id"]

    preferred_rank_order = ["Eonothem","Erathem","System","Series","Stage"]
    rank_keys_sorted = sorted(ranks.keys(), key=lambda x: (preferred_rank_order.index(x) if x in preferred_rank_order else 999, x or ""))
    rank_records: List[Dict] = []
    rank_ids_in_order: List[str] = []
    for rk in rank_keys_sorted:
        lst = ranks[rk]
        unit_ids = [unit_id_by_key[(rk, u["name"])] for u in lst]
        rec = build_rank_interp(partition, owners, viewers, legaltags, countries,
                                column_token, rk or "Unspecified", role_type_id, unit_ids,
                                args.include_scheme, args.scheme_id, args.scheme_name, args.scheme_code)
        rank_records.append(rec)
        rank_ids_in_order.append(rec["id"])

    validity_id = args.validity or f"{partition}:reference-data--StratigraphicColumnValidityAreaType:field:"
    vcs_id = args.vcs or f"{partition}:reference-data--ValueChainStatusType:Production:"
    column_record = build_column_wpc(partition, owners, viewers, legaltags, countries,
                                     args.column_name, rank_ids_in_order, validity_id, vcs_id,
                                     args.include_scheme, args.scheme_id, args.scheme_name, args.scheme_code)

    ref_records = []
    if args.emit_role_type == "yes":
        ref_records.append(build_role_type_record(partition, owners, viewers, legaltags, countries))

    manifest = {
        "kind": "osdu:wks:Manifest:1.0.0",
        "ReferenceData": ref_records,
        "MasterData": [],
        "Data": {
            "Datasets": [],
            "WorkProductComponents": unit_records + rank_records + [column_record]
        }
    }

    Path(args.out).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    if verbose:
        print(f"Units: {len(unit_records)} | Ranks: {len(rank_records)} | Column WPC: 1 | RefData: {len(ref_records)}")
        print(f"Wrote {args.out}")

if __name__ == "__main__":
    main()
