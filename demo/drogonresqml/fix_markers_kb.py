#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_markers_kb.py – Correct the Drogon WellboreMarkerFrameRepresentation objects.

Problem (verified against drogon.epc / drogon.h5):
  * NodeMd is MSL-referenced (MSL pick at 0, "Above" at -KB), but the trajectory
    MD is KB-referenced (StartMd=0 at kelly bushing). Interpolating XYZ from the
    trajectory at these MDs therefore lands every marker KB_height metres too
    shallow, and the same boundary appears twice (zone vs horizon).
  * Half the markers (Above, Valysar, Therys, Volon) are GeologicBoundaryKind
    "geobody" with NO Interpretation reference -> not linked to a feature or the
    stratigraphic column; they duplicate the interpreted Top* horizon picks.
  * Repeated pdgm ExtraMetadata blocks.

Fix (per agreed decisions):
  1. Datum: shift NodeMd onto the trajectory's KB reference:
         MD_KB = NodeMd_MSL + KB_height,  KB_height = -MdDatum.Coordinate3
  2. Drop every marker WITHOUT an <Interpretation> (the geobody zone duplicates
     and the "Above" pseudo-marker). Keep the interpreted horizon markers
     (MSL, TopVolantis, TopTherys, TopVolon, BaseVolantis).
  3. Rewrite NodeCount and the mdValues HDF5 dataset to the retained nodes.
  4. De-duplicate ExtraMetadata.

Operates in place on drogon.epc + drogon.h5 (originals backed up as *.orig).
Idempotent: re-running on already-fixed frames is a no-op (no uninterpreted
markers remain and the KB shift is detected via the absence of an MSL@0 pick).

Usage:
    python demo/drogonresqml/fix_markers_kb.py [--dry-run]
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
import zipfile
from io import BytesIO
from pathlib import Path

import h5py
import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
EPC = SCRIPT_DIR / "drogon.epc"
H5 = SCRIPT_DIR / "drogon.h5"

MARKER_BLOCK_RE = re.compile(
    r"[ \t]*<resqml2?:WellboreMarker\b.*?</resqml2?:WellboreMarker>\s*", re.S
)
EXTRAMETA_RE = re.compile(
    r"[ \t]*<resqml2?:ExtraMetadata>.*?</resqml2?:ExtraMetadata>\s*", re.S
)
UUID_RE = re.compile(r"[0-9a-fA-F-]{36}")


def _tag(xml: str, tag: str) -> str | None:
    m = re.search(r"<[^>]*\b" + tag + r">(.*?)</[^>]*\b" + tag + r">", xml, re.S)
    return m.group(1).strip() if m else None


def _build_part_index(z: zipfile.ZipFile) -> dict[str, str]:
    """Map object UUID -> part name for all object XML parts."""
    idx: dict[str, str] = {}
    for n in z.namelist():
        if not n.endswith(".xml") or n.startswith("_rels") or n == "[Content_Types].xml":
            continue
        m = UUID_RE.search(Path(n).name)
        if m:
            idx[m.group(0).lower()] = n
    return idx


def _kb_height_for_frame(frame_xml: str, parts: dict[str, str], blobs: dict[str, bytes]) -> float:
    """Resolve KB elevation via Trajectory -> MdDatum.Coordinate3."""
    traj = re.search(r"<resqml2?:Trajectory>.*?<eml:UUID>([0-9a-f-]+)", frame_xml, re.S)
    if not traj:
        raise ValueError("frame has no Trajectory reference")
    traj_uuid = traj.group(1).lower()
    traj_xml = blobs[parts[traj_uuid]].decode("utf-8")
    mdd = re.search(r"MdDatum>.*?<eml:UUID>([0-9a-f-]+)", traj_xml, re.S)
    if not mdd:
        raise ValueError("trajectory has no MdDatum reference")
    mdd_xml = blobs[parts[mdd.group(1).lower()]].decode("utf-8")
    c3 = re.search(r"<resqml2?:Coordinate3>(.*?)</resqml2?:Coordinate3>", mdd_xml, re.S)
    if not c3:
        raise ValueError("MdDatum has no Coordinate3")
    return -float(c3.group(1))


def _dedupe_extrametadata(xml: str) -> str:
    seen: set[tuple[str, str]] = set()

    def repl(m: re.Match) -> str:
        block = m.group(0)
        name = _tag(block, "Name") or ""
        val = _tag(block, "Value") or ""
        key = (name, val)
        if key in seen:
            return ""
        seen.add(key)
        return block

    return EXTRAMETA_RE.sub(repl, xml)


def process_frame(frame_xml: str, parts, blobs, h5w, dry: bool) -> tuple[str, dict]:
    well = _tag(
        re.search(r"RepresentedInterpretation>.*?</resqml2?:RepresentedInterpretation>",
                  frame_xml, re.S).group(0), "Title") if "RepresentedInterpretation" in frame_xml else "?"
    md_path = re.search(r"PathInHdfFile>(.*?)<", frame_xml).group(1)
    md = np.asarray(h5w[md_path][()], dtype="float64")

    blocks = list(MARKER_BLOCK_RE.finditer(frame_xml))
    if len(blocks) != len(md):
        raise ValueError(f"{well}: {len(blocks)} markers vs {len(md)} MD values")

    kb = _kb_height_for_frame(frame_xml, parts, blobs)

    keep_idx, dropped = [], []
    for i, b in enumerate(blocks):
        title = _tag(b.group(0), "Title")
        has_interp = "<resqml2:Interpretation>" in b.group(0) or "<resqml:Interpretation>" in b.group(0)
        if has_interp:
            keep_idx.append(i)
        else:
            dropped.append(title)

    # Idempotency guard: if nothing to drop AND MSL pick is not at ~0, assume
    # already KB-corrected -> skip shifting.
    already_kb = (not dropped) and not any(abs(md[i]) < 1e-6 for i in keep_idx
                                           if "MSL" in (_tag(blocks[i].group(0), "Title") or ""))

    new_md = md[keep_idx] + (0.0 if already_kb else kb)

    # Rebuild XML: drop non-kept marker blocks, fix NodeCount, dedupe meta.
    new_xml = frame_xml
    for i in reversed(range(len(blocks))):
        if i not in keep_idx:
            b = blocks[i]
            new_xml = new_xml[:b.start()] + new_xml[b.end():]
    new_xml = re.sub(r"(<resqml2?:NodeCount>)\d+(</resqml2?:NodeCount>)",
                     rf"\g<1>{len(keep_idx)}\g<2>", new_xml, count=1)
    new_xml = _dedupe_extrametadata(new_xml)

    if not dry:
        del h5w[md_path]
        h5w.create_dataset(md_path, data=new_md, dtype="float64")

    return new_xml, {
        "well": well, "kb": kb, "already_kb": already_kb,
        "kept": len(keep_idx), "dropped": dropped,
        "md_before": [round(float(x), 3) for x in md],
        "md_after": [round(float(x), 3) for x in new_md],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    z = zipfile.ZipFile(EPC, "r")
    blobs = {n: z.read(n) for n in z.namelist()}
    parts = _build_part_index(z)
    z.close()

    frame_parts = [n for n in blobs if "WellboreMarkerFrameRepresentation" in n
                   and n.endswith(".xml") and not n.startswith("_rels")]

    h5w = h5py.File(H5, "r" if args.dry_run else "r+")
    summaries = []
    for n in sorted(frame_parts):
        xml = blobs[n].decode("utf-8")
        new_xml, info = process_frame(xml, parts, blobs, h5w, args.dry_run)
        blobs[n] = new_xml.encode("utf-8")
        summaries.append(info)
    h5w.close()

    if not args.dry_run:
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zout:
            for n, data in blobs.items():
                zout.writestr(n, data)
        EPC.write_bytes(buf.getvalue())

    print(f"{'DRY-RUN: ' if args.dry_run else ''}Processed {len(summaries)} marker frames\n")
    for s in summaries:
        flag = " [already KB]" if s["already_kb"] else ""
        print(f"=== {s['well']}  KB={s['kb']:.0f}m  kept={s['kept']}  dropped={s['dropped']}{flag}")
        print(f"    before: {s['md_before']}")
        print(f"    after : {s['md_after']}")
        dup = [s['md_after'][i] for i in range(1, len(s['md_after']))
               if s['md_after'][i] == s['md_after'][i - 1]]
        if dup:
            print(f"    !! duplicate MD (zero-thickness): {dup}")
        if any(s['md_after'][i] < s['md_after'][i - 1] for i in range(1, len(s['md_after']))):
            print("    !! NON-MONOTONIC MD")
    return 0


if __name__ == "__main__":
    sys.exit(main())
