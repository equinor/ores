#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
curate_resqml.py — Generic, dataset-agnostic RESQML 2.0.1 EPC curator.

A standalone library (no ORES / drogon dependencies) that scrubs an arbitrary
RESQML 2.0.1 EPC so it passes the strict validator (resqml-validate) and imports
cleanly into the open-etp-server (RDDMS/ETP).  Distilled from the Drogon demo
pipeline and cross-checked against Volve, Olympus and Teapot exports (each of
which uses different namespace-prefix conventions and carries different vendor
quirks), so every transform here is **byte-preserving** and **prefix-agnostic**.

Design rules (learned the hard way):
  * NEVER reserialise with ElementTree.  ET.tostring renames namespace prefixes
    (e.g. ``resqml2:`` -> ``resqml20:``) which orphans the ``xsi:type`` QName
    values that RESQML stamps as plain strings, silently corrupting the object.
    Every edit is a regex excision/move on the original bytes.
  * Vendors disagree on prefixes: Volve uses ``resqml2:``/``eml:``, Olympus uses
    ``resqml20:``/``eml20:``.  All patterns match ``(?:\\w+:)?`` and re-use the
    captured prefix when re-inserting.
  * Dropping objects can orphan their referents.  Only drop things proven safe
    (empty sub-representations with 0 inbound refs) by default; everything more
    aggressive (FESAPI "fake" properties) is opt-in.

Fixes (each grounded in a resqml-validate diagnostic category):
  fesapi_compat  move <ExtraMetadata> to the last child (StringTableLookup: just
                 before the first <Value>).
  xsd_schema /   strip every <CustomData> block (RMS pseudo-object DORs, e.g. the
  dor_integrity  StratigraphicColumn back-reference that fails XSD derivation).
  object_pattern strip every <VersionString> (FESAPI: avoid object versioning;
                 removes hdf-proxy / strat-contact version mismatches).
  xsd_schema     repair degenerate IntegerConstantArray Count=0 on GridConnection
                 Set connection properties (expand to the supporting count).
  xsd_schema     drop empty SubRepresentations (SubRepresentationPatch Count=0 —
                 invalid positiveInteger 0, carry no data) [default on].
  fesapi_native  drop FESAPI "fake" properties + prune their DORs [opt-in].
  rddms_compat   drop OPC docProps (Core Properties) — missing xsi:type on root.
  fesapi_compat  drop the [Content_Types] catch-all <Default Extension="xml">.
  fesapi_compat  stamp the HDF5 root group ``uuid`` attr = owning ext-ref uuid.

CLI:
    python curate_resqml.py --epc in.epc --h5 in.h5 \
        --out-epc out.epc --out-h5 out.h5 \
        [--keep-empty-subreps] [--drop-fake-properties] [--drop-uuid U ...] \
        [--dry-run]
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET
import zipfile

try:
    import h5py
except ImportError:  # h5 stamping is optional
    h5py = None  # type: ignore

CT_PART = "[Content_Types].xml"

# ── prefix-agnostic byte patterns ─────────────────────────────────────────
_UUID = r"[0-9a-fA-F-]{36}"
UUID_ATTR_RE = re.compile(rf'uuid="({_UUID})"'.encode())
CUSTOMDATA_RE = re.compile(rb"<(?:\w+:)?CustomData\b[^>]*>.*?</(?:\w+:)?CustomData>", re.S)
CUSTOMDATA_EMPTY_RE = re.compile(rb"<(?:\w+:)?CustomData\b[^>]*/>")
EXTRAMETA_RE = re.compile(rb"<(\w+):ExtraMetadata\b[^>]*>.*?</\1:ExtraMetadata>", re.S)
VERSIONSTRING_RE = re.compile(rb"\s*<(\w+):VersionString\b[^>]*>.*?</\1:VersionString>", re.S)
ROOT_TAG_RE = re.compile(rb"<(\w+:[A-Za-z0-9_]+)\b")
# a SubRepresentationPatch whose Count is 0 => empty subrep
SUBREP_ZERO_RE = re.compile(
    rb"<(?:\w+:)?SubRepresentationPatch\b.*?<(?:\w+:)?Count\b[^>]*>0</(?:\w+:)?Count>", re.S)
# constant array whose Count is 0 (degenerate) — match Count inside the block
CONST_ZERO_COUNT_RE = re.compile(
    rb'(xsi:type="(?:\w+:)?\w*ConstantArray".*?<(?:\w+:)?Count[^>]*>)0(</(?:\w+:)?Count>)', re.S)
SUPPORT_UUID_RE = re.compile(
    rf"SupportingRepresentation.*?<(?:\\w+:)?UUID[^>]*>({_UUID})".encode(), re.S)
REP_COUNT_RE = re.compile(rb"<(?:\w+:)?Count[^>]*>(\d+)</(?:\w+:)?Count>")
# any DataObjectReference element block (for reference pruning)
_DOR_BLOCK_RE = re.compile(
    rb'<(\w+:[A-Za-z0-9]+)\b[^>]*xsi:type="[^"]*DataObjectReference"[^>]*>.*?</\1>', re.S)


# ── part helpers ──────────────────────────────────────────────────────────
def basename(name: str) -> str:
    return name.rsplit("/", 1)[-1]


def is_obj_part(name: str) -> bool:
    return (name.endswith(".xml") and "_rels" not in name
            and name != CT_PART and not name.startswith("docProps"))


def part_uuid(data: bytes) -> str | None:
    m = UUID_ATTR_RE.search(data[:1200])
    return m.group(1).decode().lower() if m else None


def part_type(name: str) -> str | None:
    m = re.search(r"obj_([A-Za-z0-9]+)_", basename(name))
    return m.group(1) if m else None


def ext_ref_uuid(parts: dict[str, bytes]) -> str | None:
    for name, data in parts.items():
        if "EpcExternalPartReference" in name and is_obj_part(name):
            m = UUID_ATTR_RE.search(data)
            if m:
                return m.group(1).decode()
    return None


# ── individual byte-preserving fixes ──────────────────────────────────────
def strip_customdata(data: bytes) -> bytes:
    data = CUSTOMDATA_RE.sub(b"", data)
    return CUSTOMDATA_EMPTY_RE.sub(b"", data)


def strip_versionstrings(data: bytes) -> bytes:
    return VERSIONSTRING_RE.sub(b"", data)


def move_extrametadata_last(data: bytes) -> bytes:
    """Move every <ExtraMetadata> to the correct XSD position (last child; for
    StringTableLookup before the first <Value>). Prefix-agnostic."""
    metas = [m.group(0) for m in EXTRAMETA_RE.finditer(data)]
    if not metas:
        return data
    data = EXTRAMETA_RE.sub(b"", data)
    rm = ROOT_TAG_RE.search(data)
    if not rm:
        return data
    root = rm.group(1)
    prefix = root.split(b":", 1)[0]
    block = b"\n\t" + b"\n\t".join(m.strip() for m in metas) + b"\n"
    if root.endswith(b":StringTableLookup"):
        vi = data.find(b"<" + prefix + b":Value")
        if vi != -1:
            return data[:vi] + block.lstrip() + b"\n\t" + data[vi:]
    close = b"</" + root + b">"
    idx = data.rfind(close)
    if idx == -1:
        return data
    return data[:idx] + block + data[idx:]


def fix_zero_constant_count(data: bytes, rep_count: dict[str, int]) -> bytes:
    if not CONST_ZERO_COUNT_RE.search(data):
        return data
    sup = SUPPORT_UUID_RE.search(data)
    cnt = rep_count.get(sup.group(1).decode()) if sup else None
    if not cnt:
        return data
    return CONST_ZERO_COUNT_RE.sub(
        lambda m: m.group(1) + str(cnt).encode() + m.group(2), data)


def prune_dor_refs(data: bytes, drop: set[str]) -> bytes:
    """Excise any DataObjectReference block whose <UUID> is in `drop`.
    Byte-preserving (no reserialisation)."""
    if not drop or not any(u.encode() in data for u in drop):
        return data

    def repl(m: "re.Match[bytes]") -> bytes:
        uid = re.search(rf"<[^:>]*:?UUID[^>]*>({_UUID})".encode(), m.group(0))
        if uid and uid.group(1).decode().lower() in drop:
            return b""
        return m.group(0)

    return _DOR_BLOCK_RE.sub(repl, data)


# ── detection ─────────────────────────────────────────────────────────────
def find_empty_subreps(parts: dict[str, bytes]) -> dict[str, str]:
    """Return {part_name: uuid} for SubRepresentations with a Count=0 patch."""
    out: dict[str, str] = {}
    for name, data in parts.items():
        if is_obj_part(name) and part_type(name) == "SubRepresentation" \
                and SUBREP_ZERO_RE.search(data):
            u = part_uuid(data)
            if u:
                out[name] = u
    return out


def discover_fake_properties(epc: Path) -> set[str]:
    """Parse resqml-validate output for FESAPI 'fake property {uuid}'."""
    try:
        r = subprocess.run(["resqml-validate", str(epc), "--skip-hdf5"],
                           capture_output=True, text=True, timeout=900)
        text = r.stdout + r.stderr
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return set()
    return {u.lower() for u in re.findall(rf"fake property ({_UUID})", text)}


def inbound_refs(parts: dict[str, bytes], uuid: str, owner_part: str) -> int:
    n = 0
    ub = uuid.encode()
    for name, data in parts.items():
        if name == owner_part or not is_obj_part(name):
            continue
        if ub in data:
            n += 1
    return n


# ── report ────────────────────────────────────────────────────────────────
@dataclass
class CurationReport:
    dropped: list[str] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)
    docprops_dropped: int = 0
    out_epc: Path | None = None
    out_h5: Path | None = None
    h5_uuid: str | None = None

    def summary(self) -> str:
        return (f"dropped={len(self.dropped)} "
                + " ".join(f"{k}={v}" for k, v in self.stats.items())
                + f" docProps={self.docprops_dropped}")


# ── main entry point ──────────────────────────────────────────────────────
def curate_epc(
    epc: str | Path,
    out_epc: str | Path,
    *,
    h5: str | Path | None = None,
    out_h5: str | Path | None = None,
    drop_empty_subreps: bool = True,
    drop_fake_properties: bool = False,
    extra_drop_uuids: "list[str] | tuple[str, ...]" = (),
    stamp_h5_uuid: bool = True,
    require_safe_drops: bool = True,
    dry_run: bool = False,
    verbose: bool = True,
) -> CurationReport:
    epc = Path(epc)
    out_epc = Path(out_epc)
    rep = CurationReport()

    with zipfile.ZipFile(epc) as z:
        parts = {n: z.read(n) for n in z.namelist()}

    def log(*a):
        if verbose:
            print(*a)

    # ── decide drops ──────────────────────────────────────────────────────
    drop_uuids = {u.lower() for u in extra_drop_uuids}
    if drop_fake_properties:
        drop_uuids |= discover_fake_properties(epc)

    drop_parts: set[str] = set()
    for name, data in parts.items():
        if is_obj_part(name) and part_uuid(data) in drop_uuids:
            drop_parts.add(name)
    if drop_empty_subreps:
        for name, u in find_empty_subreps(parts).items():
            if require_safe_drops and inbound_refs(parts, u, name) > 0:
                log(f"   keep {basename(name)} (empty subrep but has inbound refs)")
                continue
            drop_parts.add(name)
            drop_uuids.add(u)

    rep.dropped = sorted(basename(n) for n in drop_parts)
    log(f"dropping {len(drop_parts)} part(s); {len(drop_uuids)} uuid(s) pruned")
    for n in rep.dropped:
        log(f"   - {n}")

    # GCS element counts for degenerate-constant-array repair
    rep_count: dict[str, int] = {}
    for name, data in parts.items():
        if is_obj_part(name) and "GridConnectionSet" in name:
            mu, mc = UUID_ATTR_RE.search(data), REP_COUNT_RE.search(data)
            if mu and mc:
                rep_count[mu.group(1).decode()] = int(mc.group(1))

    # ── transform surviving parts ─────────────────────────────────────────
    out: dict[str, bytes] = {}
    stats = dict(customdata=0, extrameta=0, version=0, constcount=0, dorprune=0)
    for name, data in parts.items():
        if name in drop_parts:
            continue
        # drop a dropped object's own .rels
        if name.endswith(".rels"):
            owner = basename(name)[:-5]  # strip trailing ".rels"
            if any(basename(dp) == owner for dp in drop_parts):
                continue

        if is_obj_part(name):
            new = strip_customdata(data)
            if new != data:
                stats["customdata"] += 1
            b = new
            new = fix_zero_constant_count(new, rep_count)
            stats["constcount"] += new != b
            b = new
            new = move_extrametadata_last(new)
            stats["extrameta"] += new != b
            b = new
            new = strip_versionstrings(new)
            stats["version"] += new != b
            b = new
            new = prune_dor_refs(new, drop_uuids)
            stats["dorprune"] += new != b
            try:
                ET.fromstring(new)
            except ET.ParseError as e:
                raise ValueError(f"parse fail after edit: {basename(name)}: {e}")
            out[name] = new
        elif name.endswith(".rels"):
            txt = data.decode()
            for dp in drop_parts:
                bn = re.escape(basename(dp))
                txt = re.sub(rf'\s*<Relationship\b[^>]*Target="[^"]*{bn}"[^>]*/>', "", txt)
            out[name] = txt.encode()
        else:
            out[name] = data
    rep.stats = {k: int(v) for k, v in stats.items()}
    log("edits: " + rep.summary())

    # ── package cleanup ───────────────────────────────────────────────────
    docprops = [n for n in out if n.startswith("docProps")]
    for n in docprops:
        del out[n]
    rep.docprops_dropped = len(docprops)
    if "_rels/.rels" in out:
        r = out["_rels/.rels"].decode()
        r = re.sub(r'\s*<Relationship\b[^>]*Target="docProps/[^"]*"[^>]*/>', "", r)
        out["_rels/.rels"] = r.encode()
    ct = out[CT_PART].decode()
    ct = re.sub(r'\s*<Override PartName="/docProps/[^"]*"[^>]*/>', "", ct)
    ct = re.sub(r'\s*<Default Extension="xml"[^>]*/>', "", ct)
    for dp in drop_parts:
        bn = re.escape(basename(dp))
        ct = re.sub(rf'\s*<Override PartName="/[^"]*{bn}"[^>]*/>', "", ct)
    out[CT_PART] = ct.encode()

    if dry_run:
        log("[dry-run] no file written.")
        return rep

    # ── write EPC (CT first, then root rels, then rest) ───────────────────
    out_epc.parent.mkdir(parents=True, exist_ok=True)
    ordered = [CT_PART, "_rels/.rels"] + [n for n in out if n not in (CT_PART, "_rels/.rels")]
    tmp = out_epc.with_suffix(".epc.tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for n in ordered:
            if n in out:
                z.writestr(n, out[n])
    tmp.replace(out_epc)
    rep.out_epc = out_epc
    log(f"wrote {out_epc} ({out_epc.stat().st_size // 1024} KiB)")

    # ── H5: copy verbatim + stamp owning ext-ref uuid ─────────────────────
    if h5 and Path(h5).exists():
        h5 = Path(h5)
        dst = Path(out_h5) if out_h5 else out_epc.with_suffix(".h5")
        if dst.resolve() != h5.resolve():
            shutil.copy2(h5, dst)
        rep.out_h5 = dst
        if stamp_h5_uuid and h5py is not None:
            uid = ext_ref_uuid(parts)
            if uid:
                uid = uid.lower()
                with h5py.File(dst, "r+") as f:
                    f.attrs.create("uuid", uid.encode("ascii"),
                                   dtype=h5py.string_dtype("ascii", len(uid)))
                rep.h5_uuid = uid
                log(f"stamped {dst.name} root uuid attribute = {uid}")
    return rep


def _cli() -> int:
    ap = argparse.ArgumentParser(description="Generic RESQML 2.0.1 EPC curator")
    ap.add_argument("--epc", required=True, type=Path)
    ap.add_argument("--h5", type=Path)
    ap.add_argument("--out-epc", required=True, type=Path)
    ap.add_argument("--out-h5", type=Path)
    ap.add_argument("--keep-empty-subreps", action="store_true")
    ap.add_argument("--drop-fake-properties", action="store_true")
    ap.add_argument("--drop-uuid", action="append", default=[])
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    curate_epc(
        a.epc, a.out_epc, h5=a.h5, out_h5=a.out_h5,
        drop_empty_subreps=not a.keep_empty_subreps,
        drop_fake_properties=a.drop_fake_properties,
        extra_drop_uuids=a.drop_uuid, dry_run=a.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
