#!/usr/bin/env python3
"""
build_volve22_epc.py – Convert the curated RESQML 2.0.1 Volve EPC to RESQML 2.2.

Thin wrapper around the drogon 2.2 generator: reuses the exact same XML-level
transformation, EPC packaging, .rels regeneration and PropertyKind logic from
``drogonresqml22/build_drogon22_epc.py`` but points it at the curated Volve EPC.

Usage:
    python build_volve22_epc.py
"""
from __future__ import annotations

import sys
from pathlib import Path

DEMO = Path(__file__).resolve().parent.parent          # ~/ores/demo
D22 = DEMO / "drogonresqml22"
sys.path.insert(0, str(D22))

import build_drogon22_epc as gen  # noqa: E402

# ── Volve-specific overrides ───────────────────────────────────────────────
gen.SRC_EPC = Path(__file__).resolve().parent / "curated" / "volve.epc"
gen.OUT_EPC = Path(__file__).resolve().parent / "volve_demo_22.epc"
# The output XML will reference this H5 filename (ship volve.h5 alongside).
gen.H5_FILENAME = "volve.h5"
# The drogon EXCLUDED_UUIDS list is drogon-specific (missing HDF5 datasets in the
# drogon source); Volve's arrays are all present in curated/volve.h5.
# This local open-etp-server build cannot stream RESQML jagged arrays on import
# ("PutUninitializedDataArrays -> Dataspace not found"). Two objects carry jagged
# arrays: the GridConnectionSetRepresentation (FaultIndices) and the faulted
# IjkGridRepresentation (ColumnsPerSplitCoordinateLine split-pillar structure).
# openETPServer rejects the whole import if any kept object has a dangling DOR, so
# we must drop the full transitive closure of objects that depend on those two
# (grid properties + sub-representations + their property sets).
_JAGGED_ARRAY_OWNERS = {
    "d6f43026-e0cd-482d-83b5-63e6ea1e8c84",  # IjkGridRepresentation (faulted)
    "2efbb020-a489-4037-87b0-7204784f7c0c",  # GridConnectionSetRepresentation
}


def _dependency_closure(src_epc: Path, seed: set[str]) -> set[str]:
    """Return seed plus every object whose XML references (directly or
    transitively) an object already in the set."""
    import re
    import zipfile

    objs: dict[str, str] = {}
    with zipfile.ZipFile(src_epc) as z:
        for name in z.namelist():
            if not name.endswith(".xml") or "_rels" in name or name.startswith("["):
                continue
            txt = z.read(name).decode("utf-8", "ignore").lower()
            m = re.search(r'uuid="([0-9a-f-]{36})"', txt)
            if m:
                objs[m.group(1)] = txt

    excl = {u.lower() for u in seed}
    changed = True
    while changed:
        changed = False
        for uid, txt in objs.items():
            if uid in excl:
                continue
            if any(e[:13] in txt for e in excl):
                excl.add(uid)
                changed = True
    return excl


gen.EXCLUDED_UUIDS = _dependency_closure(gen.SRC_EPC, _JAGGED_ARRAY_OWNERS)
# EXCLUDED_TYPES (MdDatum, DeviationSurveyRepresentation) are generic 2.2 removals
# and stay as-is.

if __name__ == "__main__":
    gen.main()
