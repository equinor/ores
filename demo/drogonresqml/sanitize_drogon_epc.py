#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sanitize_drogon_epc.py – Scrub the Aspen-RMS-native quirks out of the curated
drogon.epc so it conforms to RESQML 2.0.1 as consumed by fesapi / RDDMS ETP.

The RMS export (and therefore the curated EPC subset from it) carries several
defects that the strict validator (~/validate) flags and that break / dirty an
RDDMS import.  Each is fixed here:

  fesapi_compat (ExtraMetadata placed right after Citation)
        -> move every top-level <resqml2:ExtraMetadata> to be the LAST child
           of the object (fesapi requires ExtraMetadata last).

  xsd_schema / dor_integrity / rddms_compat  (RMS <eml:CustomData> blocks hold
        non-conformant pseudo-objects: DisabledMarkers/NodeCount fragments,
        a StratigraphicColumn DOR, GridConnectionSet custom data, fragments
        without xsi:type)
        -> strip every <eml:CustomData> block (it is optional, non-standard
           pdgm extension data; the real links exist elsewhere).

  xsd_schema (DiscreteProperty whose Values is an IntegerConstantArray with
        Count=0 - the RMS exporter wrote the 'cellForFaultFace' connection
        properties with an empty constant array even though the supporting
        GridConnectionSet has thousands of cell-index pairs)
        -> set the constant-array Count to the supporting representation's
           element count (constant value -1 = 'no fault face', so this is the
           correct, schema-valid expansion).

  object_pattern (hdf-proxy DOR ObjectVersion :31/:32 != ext-ref :30; the RMS
        exporter stamped each part with its write-second; and strat contact
        DORs carried unit-creation ObjectVersions)
        -> per FESAPI guidance, do not use object versioning at all: strip
           every <eml:VersionString> in the package (DORs and the ext-ref).

  rddms_compat (the OPC docProps/core.xml + extendedCore.xml have no xsi:type;
        the validator scans them as if they were RESQML objects - a false
        positive, and the previously-imported EPC carried no docProps)
        -> drop docProps and their references (Core Properties are optional).

  fesapi_compat ([Content_Types] catch-all <Default Extension="xml"> - FESAPI
        ignores it and every object xml is already an explicit Override)
        -> drop the xml Default (keep the .rels Default required by OPC).

  fesapi_compat (the HDF5 file must advertise the owning EpcExternalPartReference
        uuid as a root-group attribute so FESAPI/ETP can bind the two)
        -> write a fixed-length ASCII 'uuid' attribute on the drogon.h5 root.

Usage:
    python demo/drogonresqml/sanitize_drogon_epc.py [--dry-run]
"""
from __future__ import annotations

import argparse
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import h5py

SCRIPT_DIR = Path(__file__).resolve().parent
EPC = SCRIPT_DIR / "drogon.epc"
H5 = SCRIPT_DIR / "drogon.h5"
CT_PART = "[Content_Types].xml"

CUSTOMDATA_RE = re.compile(rb"<eml:CustomData\b[^>]*>.*?</eml:CustomData>", re.S)
CUSTOMDATA_EMPTY_RE = re.compile(rb"<eml:CustomData\b[^>]*/>")
EXTRAMETA_RE = re.compile(rb"<resqml2:ExtraMetadata\b[^>]*>.*?</resqml2:ExtraMetadata>", re.S)
# a constant array whose Count is 0 (degenerate): match the Count *inside* the
# ConstantArray block so other Count elements are left alone.
CONST_ZERO_COUNT_RE = re.compile(
    rb'(xsi:type="resqml2:\w*ConstantArray".*?<resqml2:Count[^>]*>)0(</resqml2:Count>)',
    re.S,
)
SUPPORT_UUID_RE = re.compile(
    rb"SupportingRepresentation.*?<eml:UUID[^>]*>([0-9a-fA-F-]{36})", re.S
)
REP_COUNT_RE = re.compile(rb"<resqml2:Count[^>]*>(\d+)</resqml2:Count>")


def is_obj_part(name: str) -> bool:
    return (
        name.endswith(".xml")
        and "_rels" not in name
        and name != CT_PART
        and not name.startswith("docProps")
    )


def basename(name: str) -> str:
    return name.rsplit("/", 1)[-1]


def ext_ref_canonical_version(parts: dict[str, bytes]) -> str | None:
    for name, data in parts.items():
        if "EpcExternalPartReference" in name and is_obj_part(name):
            m = re.search(rb"<eml:Creation[^>]*>(.*?)</eml:Creation>", data)
            if m:
                return m.group(1).decode()
    return None


def ext_ref_uuid(parts: dict[str, bytes]) -> str | None:
    for name, data in parts.items():
        if "EpcExternalPartReference" in name and is_obj_part(name):
            m = re.search(rb'uuid="([0-9a-fA-F-]{36})"', data)
            if m:
                return m.group(1).decode()
    return None


def move_extrametadata_last(data: bytes) -> bytes:
    metas = EXTRAMETA_RE.findall(data)
    if not metas:
        return data
    data = EXTRAMETA_RE.sub(b"", data)
    # locate the root element name (first resqml2:* element after the xml decl)
    m = re.search(rb"<(resqml2:[A-Za-z0-9_]+)\b", data)
    if not m:
        return data
    root = m.group(1)
    close = b"</" + root + b">"
    idx = data.rfind(close)
    if idx == -1:
        return data
    block = b"\n\t" + b"\n\t".join(m.strip() for m in metas) + b"\n"
    return data[:idx] + block + data[idx:]


def normalise_versions(data: bytes, canonical: str | None) -> bytes:
    if not canonical:
        return data
    prefix = canonical[:-3]  # 'YYYY-MM-DDTHH:MM:'
    pat = re.compile(re.escape(prefix.encode()) + rb"\d\dZ")
    return pat.sub(canonical.encode(), data)


VERSIONSTRING_RE = re.compile(rb"\s*<eml:VersionString\b[^>]*>(.*?)</eml:VersionString>", re.S)


def strip_all_versions(data: bytes) -> bytes:
    """Remove every <eml:VersionString> element.

    FESAPI guidance: do not use object versioning unless you really need it.
    Stripping every VersionString (DOR references and the ext-ref's own) leaves
    a single, unambiguous version of each object and removes the hdf-proxy /
    strat-contact version mismatches the RMS exporter introduced.
    """
    return VERSIONSTRING_RE.sub(b"", data)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    with zipfile.ZipFile(EPC) as z:
        names = z.namelist()
        parts = {n: z.read(n) for n in names}

    canonical = ext_ref_canonical_version(parts)
    print(f"ext-ref canonical version: {canonical}")

    # representation element counts (GridConnectionSet pair count) for
    # repairing degenerate constant-array properties.
    rep_count: dict[str, int] = {}
    for name, data in parts.items():
        if is_obj_part(name) and "GridConnectionSet" in name:
            u = re.search(rb'uuid="([0-9a-fA-F-]{36})"', data).group(1).decode()
            m = REP_COUNT_RE.search(data)
            if m:
                rep_count[u] = int(m.group(1))

    def fix_const_count(data: bytes) -> tuple[bytes, bool]:
        if not CONST_ZERO_COUNT_RE.search(data):
            return data, False
        sup = SUPPORT_UUID_RE.search(data)
        cnt = rep_count.get(sup.group(1).decode()) if sup else None
        if not cnt:
            print(f"   WARNING: cannot resolve support count for {basename(name)}")
            return data, False
        new = CONST_ZERO_COUNT_RE.sub(
            lambda m: m.group(1) + str(cnt).encode() + m.group(2), data
        )
        return new, True

    # transform every object part
    fes = cust = ver = cnt_fix = 0
    out: dict[str, bytes] = {}
    for name, data in parts.items():
        if is_obj_part(name):
            new = CUSTOMDATA_RE.sub(b"", data)
            new = CUSTOMDATA_EMPTY_RE.sub(b"", new)
            if new != data:
                cust += 1
            new, fixed = fix_const_count(new)
            if fixed:
                cnt_fix += 1
            before = new
            new = move_extrametadata_last(new)
            if new != before:
                fes += 1
            before = new
            new = strip_all_versions(new)
            if new != before:
                ver += 1
            try:
                ET.fromstring(new)
            except ET.ParseError as e:
                print(f"   PARSE FAIL after edit: {basename(name)}: {e}")
                return 1
            out[name] = new
        else:
            out[name] = data
    print(f"edited: CustomData stripped={cust}  constant-Count fixed={cnt_fix}  "
          f"ExtraMetadata moved={fes}  VersionString stripped={ver}")

    if args.dry_run:
        print("[dry-run] no file written.")
        return 0

    # drop OPC docProps (Core Properties) and clean their references
    docprops = [n for n in out if n.startswith("docProps")]
    for n in docprops:
        del out[n]
    if "_rels/.rels" in out:
        rels = out["_rels/.rels"].decode()
        rels = re.sub(r'\s*<Relationship\b[^>]*Target="docProps/[^"]*"[^>]*/>', "", rels)
        out["_rels/.rels"] = rels.encode()
    ct = out[CT_PART].decode()
    ct = re.sub(r'\s*<Override PartName="/docProps/[^"]*"[^>]*/>', "", ct)
    # FESAPI ignores the catch-all xml Default; every object xml is an explicit
    # Override, so drop it (keep the .rels Default required by OPC).
    ct = re.sub(r'\s*<Default Extension="xml"[^>]*/>', "", ct)
    out[CT_PART] = ct.encode()
    print(f"dropped docProps parts: {len(docprops)}")

    # write the new EPC (CT first, then root rels, then the rest)
    ordered = [CT_PART, "_rels/.rels"] + [
        n for n in out if n not in (CT_PART, "_rels/.rels")
    ]
    tmp = EPC.with_suffix(".epc.tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for n in ordered:
            if n in out:
                z.writestr(n, out[n])
    tmp.replace(EPC)
    print(f"wrote {EPC} ({EPC.stat().st_size // 1024} KiB)")

    # Stamp the HDF5 root group with the owning ext-ref uuid (fixed-length
    # ASCII, lowercase canonical) so FESAPI/ETP can bind the HDF5 to the EPC.
    uid = ext_ref_uuid(parts)
    if uid and H5.exists():
        uid = uid.lower()
        with h5py.File(H5, "r+") as f:
            dt = h5py.string_dtype("ascii", len(uid))
            f.attrs.create("uuid", uid.encode("ascii"), dtype=dt)
        print(f"stamped {H5.name} root uuid attribute = {uid}")
    elif not H5.exists():
        print(f"   WARNING: {H5.name} not found; uuid attribute not written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
