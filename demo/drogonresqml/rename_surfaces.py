#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rename_surfaces.py – Make Drogon surface/line representations self-describing
and drop derived modelling artefacts.

Problem (verified against drogon.epc and seen in the maap/drogon catalog UI):
  * Every Grid2dRepresentation / PointSetRepresentation / PolylineSetRepresentation
    has a GENERIC Citation.Title ("Depth Surface - Interpreted",
    "Depth Surface - Velocity Model", "Extracted Fault Points", ...).  The
    feature it represents (TopVolantis, BaseVolantis, F1 ...) is only
    recoverable by chasing RepresentedInterpretation -> Interpretation -> Title,
    so in flat catalog listings the horizon/fault name is lost.
  * The export carries redundant derived surfaces ("Depth Surface - Velocity
    Model") on top of the interpreted ones – noise for the demo.

Fix:
  1. Prefix each representation's Citation.Title with the represented feature
     name, e.g.  'TopVolantis - Depth Surface - Interpreted'.
  2. Drop the 'Depth Surface - Velocity Model' Grid2d parts (derived artefacts),
     leaving each horizon a small set: interpreted depth + time surface + points.

Operates in place on drogon.epc (original backed up as drogon.epc.orig2).
Idempotent: titles already carrying the ' - ' feature prefix are left untouched.
HDF5 arrays of pruned parts are left as harmless orphans in drogon.h5.

Usage:
    python demo/drogonresqml/rename_surfaces.py [--dry-run] [--keep-velocity]
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
import zipfile
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET

SCRIPT_DIR = Path(__file__).resolve().parent
EPC = SCRIPT_DIR / "drogon.epc"
BACKUP = SCRIPT_DIR / "drogon.epc.orig2"

REP_TYPES = {
    "Grid2dRepresentation",
    "PointSetRepresentation",
    "PolylineSetRepresentation",
}
# Grid2d titles considered derived/redundant and pruned by default.
PRUNE_TITLES = {"Depth Surface - Velocity Model"}

CT_PART = "[Content_Types].xml"
SEP = "\u2014"  # em dash


def _local(tag: str) -> str:
    return tag.split("}")[-1]


def _first_title(xml_bytes: bytes) -> str | None:
    """Citation.Title is the first <...:Title> element in any RESQML object."""
    m = re.search(rb"<(?:\w+:)?Title>(.*?)</(?:\w+:)?Title>", xml_bytes, re.S)
    return m.group(1).decode("utf-8", "replace") if m else None


def _represented_feature(root: ET.Element, name_by_uuid: dict) -> str | None:
    """Resolve RepresentedInterpretation -> interpretation title (feature name)."""
    for el in root.iter():
        if _local(el.tag) == "RepresentedInterpretation":
            uuid = next(
                (c.text for c in el if _local(c.tag) == "UUID"), None
            )
            if uuid:
                return name_by_uuid.get(uuid)
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--keep-velocity",
        action="store_true",
        help="Do not prune 'Depth Surface - Velocity Model' Grid2d parts.",
    )
    args = ap.parse_args()

    if not EPC.exists():
        print(f"ERROR: {EPC} not found", file=sys.stderr)
        return 1

    raw = EPC.read_bytes()
    zin = zipfile.ZipFile(BytesIO(raw))
    names = zin.namelist()

    # Pass 1: index every object: uuid -> title, and remember rep parts.
    name_by_uuid: dict[str, str] = {}
    parts: dict[str, dict] = {}  # partname -> {root, type, title, uuid}
    for n in names:
        if not n.lower().endswith(".xml") or n.startswith("_rels") or n == CT_PART:
            continue
        data = zin.read(n)
        try:
            root = ET.fromstring(data)
        except ET.ParseError:
            continue
        typ = _local(root.tag)
        uuid = root.get("uuid") or root.get("Uuid")
        title = _first_title(data)
        if uuid and title is not None:
            name_by_uuid[uuid] = title
        parts[n] = {"root": root, "type": typ, "title": title, "uuid": uuid}

    # Pass 2: decide renames and prunes.
    renames: dict[str, str] = {}      # partname -> new title
    prune_parts: set[str] = set()     # partnames to drop
    prune_uuids: set[str] = set()
    for n, info in parts.items():
        if info["type"] not in REP_TYPES:
            continue
        orig = info["title"] or ""
        feat = _represented_feature(info["root"], name_by_uuid)

        if (not args.keep_velocity) and info["type"] == "Grid2dRepresentation" \
                and orig in PRUNE_TITLES:
            prune_parts.add(n)
            if info["uuid"]:
                prune_uuids.add(info["uuid"])
            continue

        if feat is None:
            continue
        if SEP in orig:  # already renamed -> idempotent
            continue
        renames[n] = f"{feat} {SEP} {orig}"

    # Safety: ensure no surviving OBJECT part references a pruned UUID.
    # The package manifests ([Content_Types].xml and _rels/.rels) register every
    # part and are cleaned below, so they are excluded from this check.
    if prune_uuids:
        manifests = {CT_PART, "_rels/.rels"}
        dangling = []
        for n in names:
            if n in prune_parts or n in manifests:
                continue
            if not (n.lower().endswith(".xml") or n.lower().endswith(".rels")):
                continue
            body = zin.read(n)
            for u in prune_uuids:
                if u.encode() in body:
                    dangling.append((n, u))
        if dangling:
            print("ABORT: pruned surfaces are still referenced elsewhere:")
            for n, u in dangling[:10]:
                print(f"   {n} -> {u}")
            return 2

    # Report.
    print(f"Surfaces/lines indexed: "
          f"{sum(1 for p in parts.values() if p['type'] in REP_TYPES)}")
    print(f"Renames: {len(renames)}   Prunes: {len(prune_parts)}")
    for n, new in sorted(renames.items(), key=lambda x: x[1]):
        print(f"  rename: {parts[n]['title']!r:42s} -> {new!r}")
    for n in sorted(prune_parts):
        print(f"  prune : {n}  ({parts[n]['title']})")

    if args.dry_run:
        print("\n[dry-run] no files written.")
        return 0
    if not renames and not prune_parts:
        print("Nothing to do (already consistent).")
        return 0

    # Build the new EPC.
    pruned_rels = {
        f"_rels/{Path(n).name}.rels" for n in prune_parts
    }
    out = BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            n = item.filename
            if n in prune_parts or n in pruned_rels:
                continue
            data = zin.read(n)
            if n == CT_PART and prune_parts:
                txt = data.decode("utf-8")
                for p in prune_parts:
                    txt = re.sub(
                        r'\s*<Override PartName="/' + re.escape(p) + r'"[^>]*/>',
                        "",
                        txt,
                    )
                data = txt.encode("utf-8")
            elif n == "_rels/.rels" and prune_parts:
                txt = data.decode("utf-8")
                for p in prune_parts:
                    txt = re.sub(
                        r'\s*<Relationship [^>]*Target="' + re.escape(p) + r'"[^>]*/>',
                        "",
                        txt,
                    )
                data = txt.encode("utf-8")
            elif n in renames:
                new_title = renames[n].encode("utf-8")
                data = re.sub(
                    rb"(<(?:\w+:)?Title>)(.*?)(</(?:\w+:)?Title>)",
                    lambda m: m.group(1) + new_title + m.group(3),
                    data,
                    count=1,
                    flags=re.S,
                )
            zout.writestr(item, data)

    if not BACKUP.exists():
        shutil.copy2(EPC, BACKUP)
        print(f"Backup written: {BACKUP.name}")
    EPC.write_bytes(out.getvalue())
    print(f"Updated {EPC.name}: {len(renames)} renamed, {len(prune_parts)} pruned.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
