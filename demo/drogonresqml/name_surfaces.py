#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
name_surfaces.py – Title = feature name, domain (DS/TS) + category in metadata.

Follow-up to rename_surfaces.py.  Earlier we *prefixed* the feature onto the
generic title ('TopVolantis — Depth Surface - Interpreted').  Per request the
object's display name should simply be the feature it represents
('TopVolantis'), with the depth/time domain recorded as metadata instead of in
the name.

For every Grid2d / PointSet / PolylineSet / TriangulatedSet representation that
resolves a RepresentedInterpretation feature:

  1. Citation.Title  -> bare feature name (e.g. 'TopVolantis', 'F2').
  2. ExtraMetadata 'Domain'            -> 'DS' or 'TS'
     (derived from the geometry LocalCrs: obj_LocalDepth3dCrs -> DS,
      obj_LocalTime3dCrs -> TS; falls back to existing osdu:SurfaceDomain).
  3. ExtraMetadata 'osdu:SurfaceCategory' -> the original descriptive title
     (e.g. 'Depth Surface - Interpreted', 'Time Points (Filtered)') so the
     provenance/category that used to live in the name is preserved.

The existing osdu:SurfaceDomain (depth/time) metadata is left untouched.
Operates in place on drogon.epc (backup drogon.epc.orig3).  Idempotent:
parts whose Title already equals the feature name and that already carry a
'Domain' pair are skipped.

Usage:
    python demo/drogonresqml/name_surfaces.py [--dry-run]
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
BACKUP = SCRIPT_DIR / "drogon.epc.orig3"

REP_TYPES = {
    "Grid2dRepresentation",
    "PointSetRepresentation",
    "PolylineSetRepresentation",
    "TriangulatedSetRepresentation",
}
CT_PART = "[Content_Types].xml"
SEP = "\u2014"  # em dash used by rename_surfaces.py


def _local(tag: str) -> str:
    return tag.split("}")[-1]


def _first_title(data: bytes) -> str | None:
    m = re.search(rb"<(?:\w+:)?Title>(.*?)</(?:\w+:)?Title>", data, re.S)
    return m.group(1).decode("utf-8", "replace") if m else None


def _represented_feature(root: ET.Element, name_by_uuid: dict) -> str | None:
    for el in root.iter():
        if _local(el.tag) == "RepresentedInterpretation":
            uuid = next((c.text for c in el if _local(c.tag) == "UUID"), None)
            if uuid:
                return name_by_uuid.get(uuid)
    return None


def _domain_code(data: bytes) -> str | None:
    """DS/TS from the geometry LocalCrs ContentType, else osdu:SurfaceDomain."""
    if b"obj_LocalTime3dCrs" in data:
        return "TS"
    if b"obj_LocalDepth3dCrs" in data:
        return "DS"
    m = re.search(
        rb"<(?:\w+:)?Name>osdu:SurfaceDomain</(?:\w+:)?Name>\s*"
        rb"<(?:\w+:)?Value>(.*?)</(?:\w+:)?Value>",
        data,
        re.S,
    )
    if m:
        v = m.group(1).decode("utf-8", "replace").strip().lower()
        return {"depth": "DS", "time": "TS"}.get(v)
    return None


def _set_title(data: bytes, new_title: str) -> bytes:
    return re.sub(
        rb"(<(?:\w+:)?Title>)(.*?)(</(?:\w+:)?Title>)",
        lambda m: m.group(1) + new_title.encode("utf-8") + m.group(3),
        data,
        count=1,
        flags=re.S,
    )


def _upsert_metadata(text: str, name: str, value: str) -> str:
    """Add or update a <ns:ExtraMetadata><Name>name</Name><Value>value</Value>."""
    # Try to update an existing pair with this Name.
    pair = re.compile(
        r"(<(?P<ns>\w+):ExtraMetadata>\s*"
        r"<(?:\w+:)?Name>" + re.escape(name) + r"</(?:\w+:)?Name>\s*"
        r"<(?:\w+:)?Value>)(.*?)(</(?:\w+:)?Value>\s*</(?:\w+:)?ExtraMetadata>)",
        re.S,
    )
    if pair.search(text):
        return pair.sub(lambda m: m.group(1) + value + m.group(3), text, count=1)

    # Determine namespace prefix used for ExtraMetadata in this part.
    nsm = re.search(r"<(\w+):ExtraMetadata>", text)
    ns = nsm.group(1) if nsm else "resqml2"
    block = (
        f"  <{ns}:ExtraMetadata>\n"
        f"    <{ns}:Name>{name}</{ns}:Name>\n"
        f"    <{ns}:Value>{value}</{ns}:Value>\n"
        f"  </{ns}:ExtraMetadata>\n"
    )
    # Insert after the last existing ExtraMetadata, else before the root close.
    last = None
    for m in re.finditer(r"</(?:\w+:)?ExtraMetadata>", text):
        last = m
    if last:
        i = last.end()
        return text[:i] + "\n" + block.rstrip("\n") + text[i:]
    # No ExtraMetadata yet: insert before the final root closing tag.
    rc = list(re.finditer(r"</(?:\w+:)?\w+>\s*$", text))
    if rc:
        i = rc[-1].start()
        return text[:i] + block + text[i:]
    return text


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not EPC.exists():
        print(f"ERROR: {EPC} not found", file=sys.stderr)
        return 1

    raw = EPC.read_bytes()
    zin = zipfile.ZipFile(BytesIO(raw))

    # Pass 1: uuid -> title for interpretation resolution.
    name_by_uuid: dict[str, str] = {}
    parts: dict[str, dict] = {}
    for n in zin.namelist():
        if not n.lower().endswith(".xml") or n.startswith("_rels") or n == CT_PART:
            continue
        data = zin.read(n)
        try:
            root = ET.fromstring(data)
        except ET.ParseError:
            continue
        uuid = root.get("uuid") or root.get("Uuid")
        title = _first_title(data)
        if uuid and title is not None:
            name_by_uuid[uuid] = title
        parts[n] = {"root": root, "type": _local(root.tag),
                    "title": title, "data": data}

    # Pass 2: compute edits.
    edits: dict[str, tuple] = {}  # part -> (feature, domain, category)
    for n, info in parts.items():
        if info["type"] not in REP_TYPES:
            continue
        feat = _represented_feature(info["root"], name_by_uuid)
        if not feat:
            continue
        orig = info["title"] or ""
        category = orig.split(SEP, 1)[1].strip() if SEP in orig else orig
        domain = _domain_code(info["data"])
        edits[n] = (feat, domain, category)

    # Report.
    print(f"Representations resolved: {len(edits)}")
    for n, (feat, dom, cat) in sorted(edits.items(),
                                      key=lambda kv: (kv[1][0], kv[1][1] or "")):
        print(f"  {parts[n]['title']!r:48s} -> Title={feat!r}  "
              f"Domain={dom}  Category={cat!r}")

    if args.dry_run:
        print("\n[dry-run] no files written.")
        return 0
    if not edits:
        print("Nothing to do.")
        return 0

    out = BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            n = item.filename
            data = zin.read(n)
            if n in edits:
                feat, dom, cat = edits[n]
                data = _set_title(data, feat)
                text = data.decode("utf-8")
                if dom:
                    text = _upsert_metadata(text, "Domain", dom)
                text = _upsert_metadata(text, "osdu:SurfaceCategory", cat)
                data = text.encode("utf-8")
            zout.writestr(item, data)

    # Validate the rewritten parts parse as XML.
    chk = zipfile.ZipFile(BytesIO(out.getvalue()))
    bad = []
    for n in edits:
        try:
            ET.fromstring(chk.read(n))
        except ET.ParseError as e:
            bad.append((n, str(e)))
    if bad:
        print("ABORT: rewritten parts no longer parse:")
        for n, e in bad[:10]:
            print(f"   {n}: {e}")
        return 2

    if not BACKUP.exists():
        shutil.copy2(EPC, BACKUP)
        print(f"Backup written: {BACKUP.name}")
    EPC.write_bytes(out.getvalue())
    print(f"Updated {EPC.name}: {len(edits)} representations renamed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
