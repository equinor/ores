
# split_for_osducli.py
# Input:  Manifest JSON (kind=osdu:wks:Manifest:1.0.0) OR a JSON array of records
# Output: Directory with one JSON file per record object (dict)
# the ps call:
# Folder that contains the single-record JSONs:
# $dir = ".\records_for_storage"
# Get-ChildItem -Path $dir -Filter *.json | ForEach-Object {osdu storage add -p $_.FullName}

import json, re
from pathlib import Path
from typing import Any, Dict, List, Union

def _sanitize_filename(s: str) -> str:
    # Windows-safe: replace colon and other invalids
    return re.sub(r'[^A-Za-z0-9._-]+', '_', s)[:200]

def _load_json(path: Path) -> Any:
    text = path.read_text(encoding='utf-8')
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # sometimes UTF-8 BOM
        return json.loads(path.read_text(encoding='utf-8-sig'))

def _extract_manifest(obj: Any) -> Dict[str, Any]:
    if isinstance(obj, dict) and obj.get('kind') == 'osdu:wks:Manifest:1.0.0':
        return obj
    # richtext wrapper case
    if isinstance(obj, dict) and len(obj) == 1:
        k = next(iter(obj))
        val = obj[k]
        if isinstance(val, dict) and val.get('type') == 'richtext':
            txt = ((val.get('value') or {}).get('text') or '').strip()
            # unescape typical backslash sequences
            manifest_str = txt.encode('utf-8', 'ignore').decode('unicode_escape')
            return json.loads(manifest_str)
    raise ValueError("Input is not a Manifest and not a records array.")

def _flatten_manifest(man: Dict[str, Any]) -> List[Dict[str, Any]]:
    refs = man.get('ReferenceData') or []
    mds  = man.get('MasterData') or []
    data = man.get('Data') or {}
    wpcs = data.get('WorkProductComponents') or []
    wp   = data.get('WorkProduct')
    out: List[Dict[str, Any]] = []
    for grp in (refs, mds, wpcs):
        for r in grp:
            if not isinstance(r, dict) or 'data' not in r:
                raise ValueError("Found an item without top-level 'data' while flattening.")
            out.append(r)
    if isinstance(wp, dict) and wp.get('data'):
        out.append(wp)
    return out

def _replace_namespace_in_strings(obj: Any, namespace: str) -> Any:
    if isinstance(obj, str):
        return obj.replace("{{NAMESPACE}}", namespace)
    if isinstance(obj, list):
        return [_replace_namespace_in_strings(x, namespace) for x in obj]
    if isinstance(obj, dict):
        return {k: _replace_namespace_in_strings(v, namespace) for k, v in obj.items()}
    return obj

def split_records(in_path: Path, out_dir: Path, namespace: str=None) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    obj = _load_json(in_path)
    records: List[Dict[str, Any]]
    if isinstance(obj, list):
        records = obj
    else:
        man = _extract_manifest(obj)
        records = _flatten_manifest(man)

    count = 0
    for rec in records:
        if not isinstance(rec, dict) or 'data' not in rec:
            # skip non-records (e.g., datasets)
            continue
        out_rec = rec
        if namespace:
            out_rec = _replace_namespace_in_strings(rec, namespace)
            # also adjust id prefix if someone left a different partition
            rid = out_rec.get('id', '')
            if isinstance(rid, str) and ':' in rid:
                parts = rid.split(':', 1)
                out_rec['id'] = f"{namespace}:{parts[1]}"
        rid = out_rec.get('id') or f"rec_{count}"
        fname = _sanitize_filename(rid) + ".json"
        Path(out_dir, fname).write_text(json.dumps(out_rec, ensure_ascii=False, indent=2), encoding='utf-8')
        count += 1
    return count

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="in_path", default="records_chronostratics_for_storage.json")
    ap.add_argument("--outdir", default="records_for_add")
    ap.add_argument("--namespace", default="dev", help="Optional data partition to replace {{NAMESPACE}} and id prefixes")
    args = ap.parse_args()
    n = split_records(Path(args.in_path), Path(args.outdir), args.namespace or None)
    print(f"Wrote {n} record files to {args.outdir}")



