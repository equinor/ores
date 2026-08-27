#!/usr/bin/env python3
"""Test: push strat column to local RDDMS using multi-transaction approach.

Requires the local RDDMS docker stack running on localhost:3000.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import httpx
import json

RDDMS_BASE = "http://localhost:3000/api/reservoir-ddms/v2"
HEADERS = {
    "Authorization": "Bearer dummy",
    "Content-Type": "application/json",
    "data-partition-id": "opendes",
}
DS_ENC = "maap%2Fdrogon"

# ── Build a mock column model ────────────────────────────────────────────────
CHRONO_UNITS = [
    ("Holocene",           0.0,    0.0117, "#FEF2C0", "Qh"),
    ("Upper Pleistocene",  0.0117, 0.126,  "#FFF2AE", "Q4"),
    ("Middle Pleistocene", 0.126,  0.781,  "#FFF2C4", "Q3"),
    ("Calabrian",          0.781,  1.80,   "#FFF2D8", "Q2"),
    ("Gelasian",           1.80,   2.58,   "#FFF2EC", "Q1"),
]

model = {
    "column": {"id": "ics-chrono-test", "data": {"Name": "ICS Chrono Test"}},
    "ranks": [{
        "rankName": "Chronostratigraphy",
        "isChrono": True,
        "unitCount": len(CHRONO_UNITS),
        "units": [
            {"name": n, "topMa": t, "baseMa": b, "color": c, "code": cd}
            for n, t, b, c, cd in CHRONO_UNITS
        ],
    }],
}

# ── Convert model → RESQML objects ───────────────────────────────────────────
from app.strat import _osdu_column_to_resqml

resqml_by_type = _osdu_column_to_resqml(model)
total = sum(len(v) for v in resqml_by_type.values())
print(f"\n✓ Generated {total} RESQML objects across {len(resqml_by_type)} types:")
for typ, objs in resqml_by_type.items():
    print(f"    {typ}: {len(objs)}")

# ── Multi-phase push (same logic as _push_resqml_to_rddms) ──────────────────
phases = [
    # Phase 1: features (no outgoing references)
    [
        "resqml20.obj_StratigraphicUnitFeature",
        "resqml20.obj_BoundaryFeature",
        "resqml20.obj_OrganizationFeature",
    ],
    # Phase 2: interpretations (InterpretedFeature → features from phase 1)
    [
        "resqml20.obj_HorizonInterpretation",
        "resqml20.obj_StratigraphicUnitInterpretation",
    ],
    # Phase 3: ranks (StratigraphicUnits[] → units from phase 2)
    ["resqml20.obj_StratigraphicColumnRankInterpretation"],
    # Phase 4: column (Ranks[] → ranks from phase 3)
    ["resqml20.obj_StratigraphicColumn"],
]

print(f"\n→ Pushing to local RDDMS dataspace: maap/drogon (multi-transaction)")

# Create dataspace via ETP (already exists from earlier, but try anyway)
os.system('docker exec drogonresqml-etp-server-1 openETPServer space -S ws://localhost:9002 --auth none -P opendes -s "maap/drogon" --new 2>/dev/null')

for pi, phase_types in enumerate(phases):
    phase_objects = []
    for typ in phase_types:
        phase_objects.extend(resqml_by_type.get(typ, []))
    if not phase_objects:
        continue

    print(f"\n  Phase {pi+1}/{len(phases)}: {len(phase_objects)} objects")
    for typ in phase_types:
        n = len(resqml_by_type.get(typ, []))
        if n:
            print(f"    - {typ}: {n}")

    # Begin transaction
    r = httpx.post(f"{RDDMS_BASE}/dataspaces/{DS_ENC}/transactions", headers=HEADERS, timeout=30)
    if r.status_code not in (200, 201):
        print(f"    ✗ BEGIN TX failed: {r.status_code} {r.text[:300]}")
        sys.exit(1)
    try:
        tx_id = r.json() if isinstance(r.json(), str) else r.text.strip('" \n')
    except Exception:
        tx_id = r.text.strip('" \n')
    print(f"    tx={tx_id}")

    # PUT objects
    r = httpx.put(
        f"{RDDMS_BASE}/dataspaces/{DS_ENC}/resources",
        headers=HEADERS, json=phase_objects,
        params={"transactionId": tx_id},
        timeout=60,
    )
    if r.status_code not in (200, 201, 204):
        print(f"    ✗ PUT failed: {r.status_code}")
        print(f"      {r.text[:500]}")
        httpx.delete(f"{RDDMS_BASE}/dataspaces/{DS_ENC}/transactions/{tx_id}", headers=HEADERS, timeout=10)
        sys.exit(1)
    print(f"    PUT OK ({r.status_code})")

    # Commit
    r = httpx.put(
        f"{RDDMS_BASE}/dataspaces/{DS_ENC}/transactions/{tx_id}",
        headers=HEADERS, timeout=60,
    )
    if r.status_code not in (200, 201, 204):
        print(f"    ✗ COMMIT failed: {r.status_code}")
        print(f"      {r.text[:500]}")
        httpx.delete(f"{RDDMS_BASE}/dataspaces/{DS_ENC}/transactions/{tx_id}", headers=HEADERS, timeout=10)
        sys.exit(1)
    print(f"    COMMIT OK ({r.status_code})")

print(f"\n✓ All {len(phases)} phases committed successfully! ({total} objects)")
