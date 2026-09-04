#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
curate_epc_201.py – Generic RESQML 2.0.1 EPC curator for RDDMS/ETP ingest.

Learns from the Drogon pipeline (drogonresqml/sanitize_drogon_epc.py +
resqml_v201_sanitizer.py) but is dataset-agnostic: it does NOT do RMS-name
specific feature selection.  It keeps every object and scrubs the package so it
passes ~/rddmsmg/tools/validate (resqml-validate) and imports cleanly into the
open-etp-server.

Fixes applied (all grounded in resqml-validate output):
  fesapi_compat  : move every <resqml2:ExtraMetadata> to the last child position
                   (StringTableLookup -> before first <Value>).
  xsd_schema/    : strip every <eml:CustomData> block (RMS pseudo-object DORs
  dor/rddms        e.g. the StratigraphicColumn back-reference that breaks XSD).
  object_pattern : strip every <eml:VersionString> (FESAPI: no object versioning).
  xsd_schema     : repair degenerate IntegerConstantArray Count=0 on GCS
                   connection properties (expand to supporting element count).
  xsd_schema     : DROP empty SubRepresentations (SubRepresentationPatch Count=0)
                   -- schema-invalid positiveInteger 0, carry no data.
  fesapi_native  : DROP FESAPI "fake" properties (uuids parsed from validator)
                   and prune the DOR that references them from any PropertySet.
  rddms_compat   : drop OPC docProps (Core Properties) -> fixes missing xsi:type.
  fesapi_compat  : drop the [Content_Types] catch-all <Default Extension="xml">.
  fesapi_compat  : stamp the HDF5 root group 'uuid' attr = owning ext-ref uuid.

All dropped parts have their .rels, [Content_Types] Override, inbound
Relationship entries and inbound DOR references pruned.

Usage:
    python curate_epc_201.py --epc in.epc --h5 in.h5 \
        --out-epc out.epc --out-h5 out.h5 [--dry-run]

The FESAPI fake-property uuids are discovered automatically by running
resqml-validate on the input (falls back to none if the CLI is unavailable);
override/extend with --drop-uuid UUID (repeatable).
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

import h5py

# Reuse the battle-tested Drogon sanitiser helpers.
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR / "drogonresqml"))
from sanitize_drogon_epc import (  # noqa: E402
    CUSTOMDATA_RE,
    CUSTOMDATA_EMPTY_RE,
    CONST_ZERO_COUNT_RE,
    SUPPORT_UUID_RE,
    REP_COUNT_RE,
    move_extrametadata_last,
    strip_all_versions,
    is_obj_part,
    basename,
    ext_ref_uuid,
)

CT_PART = "[Content_Types].xml"

EML = "http://www.energistics.org/energyml/data/commonv2"
RESQML = "http://www.energistics.org/energyml/data/resqmlv2"
XSI = "http://www.w3.org/2001/XMLSchema-instance"
ET.register_namespace("eml", EML)
ET.register_namespace("resqml2", RESQML)
ET.register_namespace("xsi", XSI)

# A SubRepresentationPatch whose Count is 0 => empty subrep (drop it).
SUBREP_ZERO_RE = re.compile(
    rb"<resqml2:SubRepresentationPatch\b.*?"
    rb"<resqml2:Count\b[^>]*>0</resqml2:Count>",
    re.S,
)
UUID_ATTR_RE = re.compile(rb'uuid="([0-9a-fA-F-]{36})"')


def part_uuid(data: bytes) -> str | None:
    m = UUID_ATTR_RE.search(data[:800])
    return m.group(1).decode().lower() if m else None


def part_type(name: str) -> str | None:
    m = re.search(r"obj_([A-Za-z0-9]+)_", basename(name))
    return m.group(1) if m else None


def discover_fake_properties(epc: Path) -> set[str]:
    """Parse resqml-validate output for FESAPI 'fake property {uuid}'."""
    try:
        out = subprocess.run(
            ["resqml-validate", str(epc), "--skip-hdf5"],
            capture_output=True, text=True, timeout=900,
        )
        text = out.stdout + out.stderr
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        print(f"   [warn] resqml-validate unavailable ({exc}); "
              f"no fake-property auto-discovery")
        return set()
    uuids = set(re.findall(
        r"fake property ([0-9a-fA-F-]{36})", text))
    return {u.lower() for u in uuids}


_DOR_BLOCK_RE = re.compile(
    rb'<(\w+:[A-Za-z0-9]+)\b[^>]*xsi:type="[^"]*DataObjectReference"[^>]*>'
    rb'.*?</\1>',
    re.S,
)


def prune_dor_refs(data: bytes, drop: set[str]) -> bytes:
    """Byte-preserving removal of any DataObjectReference block whose
    <eml:UUID> is in `drop`. Never reserialises (would rename ns prefixes and
    break xsi:type QName values), only excises the matched bytes."""
    if not drop or not any(u.encode() in data for u in drop):
        return data

    def repl(m: "re.Match[bytes]") -> bytes:
        uid = re.search(rb"<[^:>]*:?UUID[^>]*>([0-9a-fA-F-]{36})", m.group(0))
        if uid and uid.group(1).decode().lower() in drop:
            return b""
        return m.group(0)

    return _DOR_BLOCK_RE.sub(repl, data)


def fix_const_count(data: bytes, name: str, rep_count: dict[str, int]) -> bytes:
    if not CONST_ZERO_COUNT_RE.search(data):
        return data
    sup = SUPPORT_UUID_RE.search(data)
    cnt = rep_count.get(sup.group(1).decode()) if sup else None
    if not cnt:
        return data
    return CONST_ZERO_COUNT_RE.sub(
        lambda m: m.group(1) + str(cnt).encode() + m.group(2), data)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--epc", required=True, type=Path)
    ap.add_argument("--h5", type=Path)
    ap.add_argument("--out-epc", required=True, type=Path)
    ap.add_argument("--out-h5", type=Path)
    ap.add_argument("--drop-uuid", action="append", default=[],
                    help="extra object uuid to drop (repeatable)")
    ap.add_argument("--drop-fake-properties", action="store_true",
                    help="drop FESAPI 'fake' properties (opt-in: they are "
                         "non-fatal, FESAPI/ETP ignore them; dropping can "
                         "orphan their PropertySet)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    import zipfile

    with zipfile.ZipFile(args.epc) as z:
        parts = {n: z.read(n) for n in z.namelist()}

    # ── decide which parts to drop ────────────────────────────────────────
    drop_uuids = {u.lower() for u in args.drop_uuid}
    if args.drop_fake_properties:
        drop_uuids |= discover_fake_properties(args.epc)

    drop_parts: set[str] = set()
    for name, data in parts.items():
        if not is_obj_part(name):
            continue
        u = part_uuid(data)
        typ = part_type(name)
        if u and u in drop_uuids:
            drop_parts.add(name)
            continue
        # empty SubRepresentation (Count=0 patch) -> drop
        if typ == "SubRepresentation" and SUBREP_ZERO_RE.search(data):
            drop_parts.add(name)
            if u:
                drop_uuids.add(u)

    print(f"dropping {len(drop_parts)} object part(s); "
          f"{len(drop_uuids)} uuid(s) pruned from references")
    for n in sorted(drop_parts):
        print(f"   - {basename(n)}")

    # GCS element counts for degenerate-constant-array repair.
    rep_count: dict[str, int] = {}
    for name, data in parts.items():
        if is_obj_part(name) and "GridConnectionSet" in name:
            mu = UUID_ATTR_RE.search(data)
            mc = REP_COUNT_RE.search(data)
            if mu and mc:
                rep_count[mu.group(1).decode()] = int(mc.group(1))

    # ── transform surviving parts ─────────────────────────────────────────
    out: dict[str, bytes] = {}
    stats = {"customdata": 0, "extrameta": 0, "version": 0,
             "constcount": 0, "dorprune": 0}
    for name, data in parts.items():
        # drop the object part and its .rels
        if name in drop_parts:
            continue
        rels_owner = name.replace("_rels/", "").replace(".rels", "")
        if name.endswith(".rels") and any(
                basename(rels_owner) == basename(dp) for dp in drop_parts):
            continue

        if is_obj_part(name):
            new = CUSTOMDATA_RE.sub(b"", data)
            new = CUSTOMDATA_EMPTY_RE.sub(b"", new)
            if new != data:
                stats["customdata"] += 1
            b = new
            new = fix_const_count(new, name, rep_count)
            if new != b:
                stats["constcount"] += 1
            b = new
            new = move_extrametadata_last(new)
            if new != b:
                stats["extrameta"] += 1
            b = new
            new = strip_all_versions(new)
            if new != b:
                stats["version"] += 1
            b = new
            new = prune_dor_refs(new, drop_uuids)
            if new != b:
                stats["dorprune"] += 1
            try:
                ET.fromstring(new)
            except ET.ParseError as e:
                print(f"   PARSE FAIL {basename(name)}: {e}")
                return 1
            out[name] = new
        elif name.endswith(".rels"):
            # prune Relationship entries targeting dropped parts
            txt = data.decode()
            for dp in drop_parts:
                bn = re.escape(basename(dp))
                txt = re.sub(
                    rf'\s*<Relationship\b[^>]*Target="[^"]*{bn}"[^>]*/>',
                    "", txt)
            out[name] = txt.encode()
        else:
            out[name] = data
    print("edits: " + "  ".join(f"{k}={v}" for k, v in stats.items()))

    # ── package cleanup (docProps, CT overrides, xml default) ─────────────
    docprops = [n for n in out if n.startswith("docProps")]
    for n in docprops:
        del out[n]
    if "_rels/.rels" in out:
        rels = out["_rels/.rels"].decode()
        rels = re.sub(
            r'\s*<Relationship\b[^>]*Target="docProps/[^"]*"[^>]*/>', "", rels)
        out["_rels/.rels"] = rels.encode()

    ct = out[CT_PART].decode()
    ct = re.sub(r'\s*<Override PartName="/docProps/[^"]*"[^>]*/>', "", ct)
    ct = re.sub(r'\s*<Default Extension="xml"[^>]*/>', "", ct)
    for dp in drop_parts:
        bn = re.escape(basename(dp))
        ct = re.sub(rf'\s*<Override PartName="/[^"]*{bn}"[^>]*/>', "", ct)
    out[CT_PART] = ct.encode()
    print(f"dropped docProps parts: {len(docprops)}")

    if args.dry_run:
        print("[dry-run] no file written.")
        return 0

    # ── write EPC (CT first, then root rels, then the rest) ───────────────
    args.out_epc.parent.mkdir(parents=True, exist_ok=True)
    ordered = [CT_PART, "_rels/.rels"] + [
        n for n in out if n not in (CT_PART, "_rels/.rels")]
    tmp = args.out_epc.with_suffix(".epc.tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for n in ordered:
            if n in out:
                z.writestr(n, out[n])
    tmp.replace(args.out_epc)
    print(f"wrote {args.out_epc} ({args.out_epc.stat().st_size // 1024} KiB)")

    # ── H5: copy verbatim + stamp owning ext-ref uuid on root group ───────
    if args.h5 and args.h5.exists():
        out_h5 = args.out_h5 or args.out_epc.with_suffix(".h5")
        if out_h5.resolve() != args.h5.resolve():
            shutil.copy2(args.h5, out_h5)
        uid = ext_ref_uuid(parts)
        if uid:
            uid = uid.lower()
            with h5py.File(out_h5, "r+") as f:
                dt = h5py.string_dtype("ascii", len(uid))
                f.attrs.create("uuid", uid.encode("ascii"), dtype=dt)
            print(f"stamped {out_h5.name} root uuid attribute = {uid}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
