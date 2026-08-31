#!/usr/bin/env python3
"""Time all GQL_PRESETS against the running ORES instance.

Usage:
    python test/test_preset_timing.py [--ds maap/drogon201]
"""
import json, re, sys, time, httpx

BASE = "http://localhost:8000"
DS = sys.argv[sys.argv.index("--ds") + 1] if "--ds" in sys.argv else "demo/Drogon"
DS_ARG = f'dataspace: "{DS}"'
DS_LIST = f'["{DS}"]'
DS_NAME = DS.split("/")[-1].replace(DS.split("/")[-1][0], DS.split("/")[-1][0].upper(), 1)

# Extract presets from keys.js
with open("app/static/keys.js", encoding="utf-8") as f:
    js = f.read()

# Match   key: `...template...`,
presets: dict[str, str] = {}
# Standard presets inside the const GQL_PRESETS = { ... } block
for m in re.finditer(r"^\s+(\w+):\s*`((?:[^`\\]|\\.)*)`,?", js, re.M | re.S):
    presets[m.group(1)] = m.group(2)
# Appended presets: GQL_PRESETS.key = `...`
for m in re.finditer(r"GQL_PRESETS\.(\w+)\s*=\s*`((?:[^`\\]|\\.)*)`", js, re.S):
    presets[m.group(1)] = m.group(2)

def resolve(tpl: str) -> str:
    q = tpl.replace("$DS_ARG", DS_ARG)
    q = q.replace("$DS_LIST", DS_LIST)
    q = q.replace("$DS_NAME", DS_NAME)
    q = q.replace("$DS", DS)
    # Strip comment lines
    lines = [l for l in q.split("\n") if not l.strip().startswith("#")]
    return "\n".join(lines).strip()

# Categorise presets
icon_presets = [
    "markers_by_horizon",
    "field_bypassed_oil", "field_water_breakthrough",
    "field_completion_ntg", "field_segment_ranking",
    "field_injection_support", "field_grid_inventory",
]
field_dev = [k for k in presets if k.startswith("field_")]
advanced = [k for k in presets if k not in icon_presets]

print(f"{'Preset':<35} {'Time':>7}  {'Objects':>8}  {'Backend':<18}  Notes")
print("=" * 100)

slow = []
errors = []

with httpx.Client(timeout=httpx.Timeout(120.0, read=120.0)) as client:
    for key in sorted(presets.keys()):
        query = resolve(presets[key])
        if not query or not query.strip().startswith("{"):
            print(f"{key:<35} {'skip':>7}  {'':>8}  {'':>18}  not a query")
            continue

        t0 = time.time()
        try:
            r = client.post(
                f"{BASE}/api/graphql/query",
                json={"query": query},
                headers={"Content-Type": "application/json"},
            )
            elapsed = time.time() - t0
            data = r.json()

            if data.get("errors"):
                msg = data["errors"][0].get("message", "")[:60]
                errors.append((key, elapsed, msg))
                print(f"{key:<35} {elapsed:>6.1f}s  {'ERROR':>8}  {'':>18}  {msg}")
                continue

            # Count objects across all sub-queries
            total_obj = 0
            backend = ""
            warnings = []
            for qname, val in (data.get("data") or {}).items():
                if isinstance(val, dict):
                    objs = val.get("objects") or val.get("hits") or []
                    total_obj += len(objs) if isinstance(objs, list) else 0
                    if not backend:
                        backend = val.get("backend", "")
                    for w in (val.get("warnings") or []):
                        warnings.append(w[:50])
                elif isinstance(val, list):
                    total_obj += len(val)

            tag = "⚡" if key in icon_presets else "📋" if key.startswith("field_") else ""
            note = "; ".join(warnings[:2]) if warnings else ""
            if elapsed > 60:
                note = "🐌 SLOW!" + (" " + note if note else "")
                slow.append((key, elapsed))
            elif elapsed > 15:
                note = "⚠️ slow" + (" " + note if note else "")
                slow.append((key, elapsed))

            print(f"{tag}{key:<34} {elapsed:>6.1f}s  {total_obj:>8}  {backend:<18}  {note}")

        except Exception as e:
            elapsed = time.time() - t0
            errors.append((key, elapsed, str(e)[:60]))
            print(f"{key:<35} {elapsed:>6.1f}s  {'FAIL':>8}  {'':>18}  {e!s:.60}")

print("\n" + "=" * 100)
print(f"Total presets: {len(presets)}")
if slow:
    print(f"\n🐌 Slow queries (>15s):")
    for k, t in sorted(slow, key=lambda x: -x[1]):
        print(f"  {k}: {t:.1f}s")
if errors:
    print(f"\n❌ Errors ({len(errors)}):")
    for k, t, msg in errors:
        print(f"  {k}: {msg}")
