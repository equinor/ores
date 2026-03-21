"""Consistency check across chrono + strat column manifests & record dirs."""
import json, os
from pathlib import Path
from collections import Counter, defaultdict

STRAT = Path("demo/strat")
M_CH = STRAT / "manifest_chronostratics.json"
M_SC = STRAT / "manifest_stratcolumn.json"
DIR_CH = STRAT / "chronostrat_records"
DIR_SC = STRAT / "stratcolumn_records"

def load(p):
    return json.loads(p.read_text("utf-8"))

def extract(m):
    recs = []
    for k in ("ReferenceData", "MasterData"):
        recs.extend(m.get(k) or [])
    d = m.get("Data") or {}
    for k in ("WorkProductComponents", "WorkProducts", "Datasets"):
        recs.extend(d.get(k) or [])
    return [r for r in recs if isinstance(r, dict) and r.get("id")]

print("=" * 60)
print("CHRONO MANIFEST")
print("=" * 60)
ch = load(M_CH)
ch_recs = extract(ch)
ch_ids = [r["id"] for r in ch_recs]
ch_unique = set(ch_ids)
print(f"  Total records: {len(ch_recs)}")
print(f"  Unique IDs:    {len(ch_unique)}")
dups = len(ch_ids) - len(ch_unique)
print(f"  Duplicates:    {dups} {'*** PROBLEM' if dups else '(clean)'}")
# {{NAMESPACE}} check
ns = sum(1 for r in ch_recs if "{{NAMESPACE}}" in json.dumps(r))
print(f"  {{NAMESPACE}}:  {ns} {'*** PROBLEM' if ns else '(clean)'}")
# Kind breakdown
kinds = Counter(r.get("kind","?").split("--")[-1] for r in ch_recs)
for k, n in kinds.most_common():
    print(f"    {k}: {n}")

print()
print("=" * 60)
print("STRAT COLUMN MANIFEST")
print("=" * 60)
sc = load(M_SC)
sc_recs = extract(sc)
sc_ids = [r["id"] for r in sc_recs]
sc_unique = set(sc_ids)
print(f"  Total records: {len(sc_recs)}")
print(f"  Unique IDs:    {len(sc_unique)}")
dups = len(sc_ids) - len(sc_unique)
print(f"  Duplicates:    {dups} {'*** PROBLEM' if dups else '(clean)'}")
ns = sum(1 for r in sc_recs if "{{NAMESPACE}}" in json.dumps(r))
print(f"  {{NAMESPACE}}:  {ns} {'*** PROBLEM' if ns else '(clean)'}")
kinds = Counter(r.get("kind","?").split("--")[-1] for r in sc_recs)
for k, n in kinds.most_common():
    print(f"    {k}: {n}")

print()
print("=" * 60)
print("CROSS-REFERENCE CHECK")
print("=" * 60)
# Strat units -> ChronoStratigraphyID -> must exist in chrono manifest
unit_chrono_refs = set()
for r in sc_recs:
    cid = r.get("data", {}).get("ChronoStratigraphyID", "")
    if cid:
        unit_chrono_refs.add(cid)
matched = unit_chrono_refs & ch_unique
unmatched = unit_chrono_refs - ch_unique
print(f"  Strat units referencing ChronoStratigraphyID: {len(unit_chrono_refs)}")
print(f"  Matched in chrono manifest: {len(matched)}")
print(f"  UNMATCHED: {len(unmatched)} {'*** PROBLEM' if unmatched else '(clean)'}")
for u in sorted(unmatched)[:5]:
    print(f"    {u}")

# Strat units -> HorizonTop/BaseID
horizon_refs = set()
for r in sc_recs:
    d = r.get("data", {})
    for hk in ("ColumnStratigraphicHorizonTopID", "ColumnStratigraphicHorizonBaseID"):
        hid = d.get(hk, "")
        if hid:
            horizon_refs.add(hid)
print(f"\n  Strat units referencing Horizon IDs: {len(horizon_refs)}")
# Check if any horizon records exist in either manifest
all_ids = ch_unique | sc_unique
horizon_matched = horizon_refs & all_ids
print(f"  Horizon IDs found in manifests: {len(horizon_matched)}")
print(f"  Horizon IDs MISSING (need generation): {len(horizon_refs - all_ids)}")
if horizon_refs:
    for h in sorted(horizon_refs)[:5]:
        print(f"    e.g. {h}")

print()
print("=" * 60)
print("RECORD FILES vs MANIFEST")
print("=" * 60)
for label, mf_unique, rdir in [("Chrono", ch_unique, DIR_CH), ("StratCol", sc_unique, DIR_SC)]:
    if rdir.exists():
        files = list(rdir.glob("*.json"))
        file_ids = set()
        for f in files:
            try:
                rec = json.loads(f.read_text("utf-8"))
                file_ids.add(rec.get("id", ""))
            except Exception:
                pass
        in_manifest_not_files = mf_unique - file_ids
        in_files_not_manifest = file_ids - mf_unique
        print(f"  {label}: {len(files)} files, {len(mf_unique)} manifest records")
        if in_manifest_not_files:
            print(f"    In manifest but missing file: {len(in_manifest_not_files)} *** PROBLEM")
        if in_files_not_manifest:
            print(f"    In files but not manifest: {len(in_files_not_manifest)} (stale?)")
            for s in sorted(in_files_not_manifest)[:3]:
                print(f"      {s}")
        if not in_manifest_not_files and not in_files_not_manifest:
            print(f"    Perfect match")
    else:
        print(f"  {label}: directory {rdir} not found")
