#!/usr/bin/env python3
"""Quick cross-reference integrity check for the subset M27 manifest."""
import json
import re
import sys
from collections import Counter
from pathlib import Path

path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
    "demo/drogonresqml22/manifest_drogon22_subset.json")
m = json.loads(path.read_text())
D = m["Data"]

recs = []
for sec in ["Datasets", "MasterData", "WorkProductComponents",
            "WorkProduct", "ReferenceData"]:
    v = D.get(sec)
    if isinstance(v, list):
        recs += v
    elif isinstance(v, dict):
        recs.append(v)

ids = {r["id"] for r in recs if r.get("id")}
ids_nover = {i.rsplit(":", 1)[0] for i in ids}

refpat = re.compile(r"^[A-Za-z0-9.\-]+:[A-Za-z0-9.\-]+--[A-Za-z0-9.\-]+:")
refs = []


def walk(o, path=""):
    if isinstance(o, dict):
        for k, v in o.items():
            walk(v, path + "." + k)
    elif isinstance(o, list):
        for v in o:
            walk(v, path)
    elif isinstance(o, str) and refpat.match(o):
        refs.append((o.rstrip(":"), path))


for r in recs:
    walk(r)

unresolved = []
for ref, p in refs:
    nover = ref.rsplit(":", 1)[0]
    if ref in ids or ref in ids_nover or nover in ids_nover:
        continue
    unresolved.append((ref, p))

print(f"records: {len(recs)}, distinct ids: {len(ids)}")
print(f"total refs: {len(refs)}, in-manifest resolved: {len(refs)-len(unresolved)},"
      f" external/unresolved: {len(unresolved)}")
c = Counter(p.split(".")[-1] for _, p in unresolved)
for k, v in c.most_common(25):
    print(f"   {v:3d}  ...{k}")
print("--- sample external/unresolved refs ---")
seen = set()
for ref, p in unresolved:
    key = (ref.rsplit(":", 1)[0], p.split(".")[-1])
    if key in seen:
        continue
    seen.add(key)
    print(f"   {ref}   <- {p}")
    if len(seen) >= 20:
        break
