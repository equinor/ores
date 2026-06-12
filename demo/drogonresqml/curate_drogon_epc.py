#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
curate_drogon_epc.py – Build the curated Drogon demo EPC from the authoritative
Aspen RMS export (src/drogonfull.epc + src/drogonfull.h5).

The RMS export carries, for every horizon/fault, a whole workflow lineage of
map/point/line artefacts (DS_interp, DS_velmod, DS_gf_*, DS_hum_*, DP_*, GL_* …)
and the Citation.Title is the RMS *category* name, not the feature.  For the
demo we keep exactly ONE depth + ONE time representation (grid + points) per
horizon, name each object after the feature it represents, and record the RMS
name + domain in metadata so objects stay searchable by horizon name AND RMS
name.

Selection (per user):
  Grid2d   : DS_extract_geogrid (depth, QC'd set) + TS_time_extracted (time)
  PointSet : one depth per horizon (DP_filter -> DP_filter_post fallback)
             + TP_filter (time); ExtractedFaultPoints for faults
  Polyline : DL_faultsticks (depth) + TL_faultsticks (time) for faults
  Everything that is NOT a Grid2d/PointSet/Polyline representation (features,
  interpretations, strat column/units, wells, trajectories, deviation surveys,
  MdDatum, log/marker frames, IjkGrid + properties, CRS, ext-ref) is kept
  verbatim.

Each kept representation is rewritten:
  Citation.Title              -> feature name (e.g. 'TopVolantis', 'F2')
  ExtraMetadata Domain        -> 'DS' / 'TS'
  ExtraMetadata osdu:SurfaceCategory / osdu:RmsName -> original RMS title

Packaging is preserved (fesapi layout): per-part .rels are kept but every
Relationship whose Target was dropped is removed; the EpcExternalPartReference
proxy list is filtered to surviving parts; the HDF external resource is
repointed to drogon.h5; and only the HDF5 datasets referenced by surviving
parts are copied into a fresh drogon.h5.

Usage:
    python demo/drogonresqml/curate_drogon_epc.py [--dry-run]
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
import uuid as uuidlib
import zipfile
from collections import defaultdict
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET

import h5py

SCRIPT_DIR = Path(__file__).resolve().parent
SRC_EPC = SCRIPT_DIR / "src" / "drogonfull.epc"
SRC_H5 = SCRIPT_DIR / "src" / "drogonfull.h5"
OUT_EPC = SCRIPT_DIR / "drogon.epc"
OUT_H5 = SCRIPT_DIR / "drogon.h5"
H5_NAME = "drogon.h5"

CT_PART = "[Content_Types].xml"
REP_TYPES = {
    "Grid2dRepresentation",
    "PointSetRepresentation",
    "PolylineSetRepresentation",
}

GRID2D_KEEP = {"DS_extract_geogrid", "TS_time_extracted"}
POINTSET_TIME_KEEP = {"TP_filter"}
POINTSET_DEPTH_PRIORITY = ["DP_filter", "DP_filter_post",
                           "DP_filter_post_hum_input"]
FAULT_POINTSET_KEEP = {"ExtractedFaultPoints"}
POLYLINE_KEEP = {"DL_faultsticks", "TL_faultsticks"}

# ---------------------------------------------------------------------------
# Property reduction.  The RMS export carries 100+ grid/well properties.  For
# the demo we keep only a small, representative reservoir set, named with the
# canonical OSDU/PWLS-aligned property kinds, sufficient to run a simulation
# and to show the well-log <-> grid-property <-> strat-zone relationships.
#   wells : PHIT (porosity), KLOGH (permeability), Sw (water saturation),
#           VSH (shale volume), VP (velocity), Zone (stratigraphic unit)
#   grid  : the RMS export names the same reservoir property differently on the
#           geological vs the simulation grid, so the keep-list is the union of
#           both naming conventions and each grid keeps whatever it carries:
#             Geogrid : PHIT (porosity), KLOGH (permeability), SW (saturation),
#                       VSH (shale volume), Zone (stratigraphic unit)
#             Simgrid : PORO (porosity), PERMX (permeability),
#                       SWATINIT (water saturation), Zone (stratigraphic unit)
#   GCS   : cellForFaultFace + multipliers (required by GridConnectionSet)
# ---------------------------------------------------------------------------
PROP_TYPES = {"ContinuousProperty", "CategoricalProperty", "DiscreteProperty"}
WELL_LOG_KEEP = {"PHIT", "KLOGH", "Sw", "VSH", "VP", "Zone"}
GRID_PROP_KEEP = {"PORO", "PHIT", "PERMX", "KLOGH", "SW", "SWATINIT",
                  "VSH", "Zone"}
GCS_PROP_KEEP = {"cellForFaultFace", "multipliers"}

# Survivors that RMS exported with a placeholder/abstract kind get reassigned to
# a concrete RESQML 2.0.1 standard property kind (verified non-abstract).
STD_KIND_REASSIGN = {
    ("WELL", "KLOGH"): "rock permeability",
    ("WELL", "VP"): "velocity",
    ("GRID", "KLOGH"): "rock permeability",
    ("GRID", "SWATINIT"): "saturation",
    ("GCS", "multipliers"): "property multiplier",
}
# Vsh has no concrete standard kind, so it points at a local, non-abstract
# property kind that derives from the continuous root (FESAPI-compliant).
VSH_TITLES = {"VSH"}
VSH_KIND_UUID = "f0a1b2c3-d4e5-4678-9abc-def012345678"
VSH_KIND_TITLE = "volume of shale"
VSH_KIND_PART = f"obj_PropertyKind_{VSH_KIND_UUID}.xml"

SUPPORT_RE = re.compile(
    rb"<(?:\w+:)?SupportingRepresentation\b.*?<(?:\w+:)?UUID[^>]*>"
    rb"([0-9a-fA-F-]{36})", re.S)
KIND_BLOCK_RE = re.compile(
    rb"<resqml2:PropertyKind\b.*?</resqml2:PropertyKind>", re.S)
UUID_REF_RE = re.compile(rb"<eml:UUID[^>]*>([0-9a-fA-F-]{36})</eml:UUID>")

UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
H5_PATH_RE = re.compile(rb"<(?:\w+:)?PathInHdfFile[^>]*>([^<]+)</(?:\w+:)?PathInHdfFile>")


def lname(t: str) -> str:
    return t.split("}")[-1]


def first_title(data: bytes) -> str | None:
    m = re.search(rb"<(?:\w+:)?Title[^>]*>(.*?)</(?:\w+:)?Title>", data, re.S)
    return m.group(1).decode("utf-8", "replace").strip() if m else None


def represented_feature(root: ET.Element, name_by_uuid: dict) -> str | None:
    for el in root.iter():
        if lname(el.tag) == "RepresentedInterpretation":
            uuid = next((c.text for c in el if lname(c.tag) == "UUID"), None)
            if uuid:
                return name_by_uuid.get(uuid)
    return None


def domain_code(data: bytes) -> str | None:
    if b"obj_LocalTime3dCrs" in data:
        return "TS"
    if b"obj_LocalDepth3dCrs" in data:
        return "DS"
    return None


def set_title(data: bytes, new_title: str) -> bytes:
    return re.sub(
        rb"(<(?:\w+:)?Title[^>]*>)(.*?)(</(?:\w+:)?Title>)",
        lambda m: m.group(1) + new_title.encode("utf-8") + m.group(3),
        data, count=1, flags=re.S,
    )


def upsert_metadata(text: str, name: str, value: str) -> str:
    pair = re.compile(
        r"(<(?P<ns>\w+):ExtraMetadata[^>]*>\s*"
        r"<(?:\w+:)?Name[^>]*>" + re.escape(name) + r"</(?:\w+:)?Name>\s*"
        r"<(?:\w+:)?Value[^>]*>)(.*?)(</(?:\w+:)?Value>\s*</(?:\w+:)?ExtraMetadata>)",
        re.S,
    )
    if pair.search(text):
        return pair.sub(lambda m: m.group(1) + value + m.group(3), text, count=1)
    nsm = re.search(r"<(\w+):ExtraMetadata", text)
    ns = nsm.group(1) if nsm else "resqml2"
    block = (
        f'  <{ns}:ExtraMetadata xsi:type="{ns}:NameValuePair">\n'
        f'    <{ns}:Name xsi:type="xsd:string">{name}</{ns}:Name>\n'
        f'    <{ns}:Value xsi:type="xsd:string">{value}</{ns}:Value>\n'
        f'  </{ns}:ExtraMetadata>\n'
    )
    last = None
    for m in re.finditer(r"</(?:\w+:)?ExtraMetadata>", text):
        last = m
    if last:
        i = last.end()
        return text[:i] + "\n" + block.rstrip("\n") + text[i:]
    rc = list(re.finditer(r"</(?:\w+:)?\w+>\s*$", text))
    if rc:
        i = rc[-1].start()
        return text[:i] + block + text[i:]
    return text


def rels_part_for(obj_name: str) -> str:
    return f"_rels/{obj_name}.rels"


def obj_for_rels(rels_name: str) -> str:
    # "_rels/obj_X.xml.rels" -> "obj_X.xml"
    base = rels_name.split("/")[-1]
    return base[:-5] if base.endswith(".rels") else base


def supporting_uuid(data: bytes) -> str | None:
    m = SUPPORT_RE.search(data)
    return m.group(1).decode() if m else None


def support_kind(typ: str | None) -> str | None:
    return {"WellboreFrameRepresentation": "WELL",
            "IjkGridRepresentation": "GRID",
            "GridConnectionSetRepresentation": "GCS"}.get(typ or "")


def std_kind_block(name: str) -> bytes:
    return (
        '<resqml2:PropertyKind xsi:type="resqml2:StandardPropertyKind">'
        '<resqml2:Kind xsi:type="resqml2:ResqmlPropertyKind">'
        f'{name}</resqml2:Kind></resqml2:PropertyKind>'
    ).encode()


def local_kind_block(kind_uuid: str, title: str) -> bytes:
    return (
        '<resqml2:PropertyKind xsi:type="resqml2:LocalPropertyKind">'
        '<resqml2:LocalPropertyKind xsi:type="eml:DataObjectReference">'
        '<eml:ContentType xsi:type="xsd:string">'
        'application/x-resqml+xml;version=2.0;type=obj_PropertyKind'
        '</eml:ContentType>'
        f'<eml:Title xsi:type="eml:DescriptionString">{title}</eml:Title>'
        f'<eml:UUID xsi:type="eml:UuidString">{kind_uuid}</eml:UUID>'
        '<eml:UuidAuthority xsi:type="xsd:string">ores</eml:UuidAuthority>'
        '</resqml2:LocalPropertyKind></resqml2:PropertyKind>'
    ).encode()


def vsh_kind_xml() -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<resqml2:PropertyKind '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
        'xmlns:resqml2="http://www.energistics.org/energyml/data/resqmlv2" '
        'xmlns:eml="http://www.energistics.org/energyml/data/commonv2" '
        f'schemaVersion="2.0" uuid="{VSH_KIND_UUID}" '
        'xsi:type="resqml2:obj_PropertyKind">\n'
        '  <eml:Citation xsi:type="eml:Citation">\n'
        f'    <eml:Title xsi:type="eml:DescriptionString">{VSH_KIND_TITLE}</eml:Title>\n'
        '    <eml:Originator xsi:type="eml:NameString">ores</eml:Originator>\n'
        '    <eml:Creation xsi:type="xsd:dateTime">2026-06-11T15:01:30Z</eml:Creation>\n'
        '    <eml:Format xsi:type="eml:DescriptionString">ores</eml:Format>\n'
        '  </eml:Citation>\n'
        '  <resqml2:NamingSystem xsi:type="xsd:anyURI">urn:resqml:energistics.org</resqml2:NamingSystem>\n'
        '  <resqml2:IsAbstract xsi:type="xsd:boolean">false</resqml2:IsAbstract>\n'
        '  <resqml2:RepresentativeUom xsi:type="resqml2:ResqmlUom">Euc</resqml2:RepresentativeUom>\n'
        '  <resqml2:ParentPropertyKind xsi:type="resqml2:StandardPropertyKind">\n'
        '    <resqml2:Kind xsi:type="resqml2:ResqmlPropertyKind">continuous</resqml2:Kind>\n'
        '  </resqml2:ParentPropertyKind>\n'
        '</resqml2:PropertyKind>\n'
    ).encode()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not SRC_EPC.exists() or not SRC_H5.exists():
        print(f"ERROR: source not found: {SRC_EPC} / {SRC_H5}", file=sys.stderr)
        return 1

    zin = zipfile.ZipFile(SRC_EPC)
    names = zin.namelist()

    # Pass 1: parse object parts.
    parts: dict[str, dict] = {}
    name_by_uuid: dict[str, str] = {}
    for n in names:
        if not n.endswith(".xml") or n.startswith("_rels") or "/_rels/" in n \
                or n == CT_PART or n.startswith("docProps"):
            continue
        data = zin.read(n)
        try:
            root = ET.fromstring(data)
        except ET.ParseError:
            parts[n] = {"root": None, "type": "?", "uuid": None,
                        "title": first_title(data), "data": data}
            continue
        uuid = root.get("uuid") or root.get("Uuid")
        title = first_title(data)
        if uuid and title is not None:
            name_by_uuid[uuid] = title
        parts[n] = {"root": root, "type": lname(root.tag), "uuid": uuid,
                    "title": title, "data": data}

    # Pass 2: selection.
    keep: set[str] = set()
    drop: set[str] = set()
    rewrite: dict[str, tuple] = {}   # part -> (feature, domain, category)
    prop_keep: dict[str, tuple] = {}  # property part -> (support_kind, title)
    depth_candidates: dict[str, list] = defaultdict(list)  # feature -> [(prio, part, dom)]

    type_by_uuid = {p["uuid"]: p["type"] for p in parts.values() if p["uuid"]}

    for n, p in parts.items():
        typ = p["type"]
        if typ in PROP_TYPES:
            sk = support_kind(type_by_uuid.get(supporting_uuid(p["data"])))
            title = p["title"] or ""
            if (sk == "WELL" and title in WELL_LOG_KEEP) or \
               (sk == "GRID" and title in GRID_PROP_KEEP) or \
               (sk == "GCS" and title in GCS_PROP_KEEP):
                keep.add(n)
                prop_keep[n] = (sk, title)
            else:
                drop.add(n)
            continue
        if typ not in REP_TYPES:
            keep.add(n)
            continue
        title = p["title"] or ""
        feat = represented_feature(p["root"], name_by_uuid) if p["root"] is not None else None
        dom = domain_code(p["data"])

        if typ == "Grid2dRepresentation":
            if title in GRID2D_KEEP:
                keep.add(n)
                rewrite[n] = (feat, dom, title)
            else:
                drop.add(n)
        elif typ == "PolylineSetRepresentation":
            if title in POLYLINE_KEEP:
                keep.add(n)
                rewrite[n] = (feat, dom, title)
            else:
                drop.add(n)
        elif typ == "PointSetRepresentation":
            if title in FAULT_POINTSET_KEEP or title in POINTSET_TIME_KEEP:
                keep.add(n)
                rewrite[n] = (feat, dom, title)
            elif dom == "DS" and title in POINTSET_DEPTH_PRIORITY and feat:
                depth_candidates[feat].append(
                    (POINTSET_DEPTH_PRIORITY.index(title), n, dom, title, feat))
            else:
                drop.add(n)

    # Resolve one depth pointset per feature by priority.
    for feat, cands in depth_candidates.items():
        cands.sort(key=lambda c: c[0])
        chosen = cands[0]
        n = chosen[1]
        keep.add(n)
        rewrite[n] = (chosen[4], chosen[2], chosen[3])
        for c in cands[1:]:
            drop.add(c[1])

    drop_uuids = {parts[n]["uuid"] for n in drop if parts[n]["uuid"]}

    # Report selection.
    print(f"Source parts: {len(parts)}   keep(obj): {len(keep)}   drop(rep): {len(drop)}")
    print("Kept representations:")
    for n in sorted(rewrite, key=lambda k: (rewrite[k][0] or "", rewrite[k][1] or "")):
        feat, dom, cat = rewrite[n]
        print(f"  {feat or '?':14s} {dom or '?'}  {parts[n]['type'][:8]:8s} <- {cat}")

    # Referential check: any KEPT object inline-referencing a dropped uuid?
    dangling = []
    for n in keep:
        body = parts[n]["data"]
        for u in drop_uuids:
            if u.encode() in body:
                dangling.append((n, u))
    if dangling:
        print("\nWARNING: kept parts inline-reference dropped uuids:")
        for n, u in dangling[:10]:
            print(f"   {parts[n]['type']} {n} -> {u}")

    # --- Property reduction follow-up: reassign canonical kinds, inject the
    #     local Vsh kind, then prune now-orphaned lookups / property kinds. ---
    rels_add_kind: dict[str, str] = {}   # property part -> local kind uuid to add
    for n, (sk, title) in prop_keep.items():
        data = parts[n]["data"]
        if title in VSH_TITLES:
            data = KIND_BLOCK_RE.sub(
                local_kind_block(VSH_KIND_UUID, VSH_KIND_TITLE), data, count=1)
            rels_add_kind[n] = VSH_KIND_UUID
        elif (sk, title) in STD_KIND_REASSIGN:
            data = KIND_BLOCK_RE.sub(
                std_kind_block(STD_KIND_REASSIGN[(sk, title)]), data, count=1)
        parts[n]["data"] = data

    parts[VSH_KIND_PART] = {"root": None, "type": "PropertyKind",
                            "uuid": VSH_KIND_UUID, "title": VSH_KIND_TITLE,
                            "data": vsh_kind_xml()}
    keep.add(VSH_KIND_PART)

    referenced: set[str] = set()
    for n in keep:
        if parts[n]["type"] in PROP_TYPES:
            for m in UUID_REF_RE.finditer(parts[n]["data"]):
                referenced.add(m.group(1).decode())
    pruned = 0
    for n in list(keep):
        t = parts[n]["type"]
        if t in ("StringTableLookup", "PropertyKind"):
            u = parts[n]["uuid"]
            if u == VSH_KIND_UUID:
                continue
            if u and u not in referenced:
                keep.discard(n)
                drop.add(n)
                pruned += 1

    print(f"\nProperties kept: {len(prop_keep)}   "
          f"reassigned-to-Vsh: {len(rels_add_kind)}   "
          f"orphan lookups/kinds pruned: {pruned}")

    if args.dry_run:
        print("\n[dry-run] no files written.")
        return 0

    # Collect HDF paths referenced by kept object parts.
    h5_paths: set[str] = set()
    for n in keep:
        data = parts[n]["data"]
        if n in rewrite:
            feat, dom, cat = rewrite[n]
            data = set_title(data, feat or parts[n]["title"] or "")
            text = data.decode("utf-8")
            if dom:
                text = upsert_metadata(text, "Domain", dom)
            text = upsert_metadata(text, "osdu:SurfaceCategory", cat)
            text = upsert_metadata(text, "osdu:RmsName", cat)
            data = text.encode("utf-8")
            parts[n]["data"] = data
        for m in H5_PATH_RE.finditer(parts[n]["data"]):
            h5_paths.add(m.group(1).decode("utf-8", "replace").strip())

    kept_obj_basenames = {n for n in keep}

    def filter_rels(text: str, add_kind_uuid: str | None = None) -> str:
        out_lines = []
        for line in text.splitlines():
            m = re.search(r'Target="([^"]+)"', line)
            if m and "<Relationship" in line:
                tgt = m.group(1).split("/")[-1]
                if tgt.endswith(".xml") and tgt not in kept_obj_basenames:
                    continue  # drop dangling relationship
                # repoint HDF external resource
                if tgt == "drogonfull.h5":
                    line = line.replace("drogonfull.h5", H5_NAME)
            out_lines.append(line)
        result = "\n".join(out_lines)
        if add_kind_uuid:
            kind_part = f"obj_PropertyKind_{add_kind_uuid}.xml"
            if kind_part not in result:
                rel = (
                    f'        <Relationship Id="_{add_kind_uuid}_{uuidlib.uuid4()}" '
                    'Type="http://schemas.energistics.org/package/2012/'
                    'relationships/destinationObject" '
                    f'Target="{kind_part}"/>')
                result = result.replace(
                    "</Relationships>", rel + "\n</Relationships>")
        return result + ("\n" if text.endswith("\n") else "")

    # Build output EPC.
    out = BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            n = item.filename
            if n == CT_PART:
                txt = zin.read(n).decode("utf-8")
                for d in drop:
                    txt = re.sub(
                        r'\s*<Override PartName="/' + re.escape(d) + r'"[^>]*/>',
                        "", txt)
                # register the injected local Vsh property kind part
                vsh_ovr = (
                    f'  <Override PartName="/{VSH_KIND_PART}" '
                    'ContentType="application/x-resqml+xml;version=2.0;'
                    'type=obj_PropertyKind"/>\n')
                txt = txt.replace("</Types>", vsh_ovr + "</Types>")
                zout.writestr(item, txt.encode("utf-8"))
                continue
            if n.endswith(".rels"):
                if n == "_rels/.rels":
                    zout.writestr(item, zin.read(n))
                    continue
                target_obj = obj_for_rels(n)
                if target_obj not in kept_obj_basenames:
                    continue  # rels for a dropped part
                txt = zin.read(n).decode("utf-8")
                zout.writestr(
                    item,
                    filter_rels(txt, rels_add_kind.get(target_obj)).encode("utf-8"))
                continue
            if n.startswith("docProps"):
                zout.writestr(item, zin.read(n))
                continue
            # object part
            if n in drop:
                continue
            if n in parts:
                zout.writestr(item, parts[n]["data"])
            else:
                zout.writestr(item, zin.read(n))

        # Inject the local 'volume of shale' property kind object part.
        zout.writestr(VSH_KIND_PART, parts[VSH_KIND_PART]["data"])

    # Validate kept object XML parses.
    chk = zipfile.ZipFile(BytesIO(out.getvalue()))
    bad = []
    for n in rewrite:
        try:
            ET.fromstring(chk.read(n))
        except ET.ParseError as e:
            bad.append((n, str(e)))
    if bad:
        print("ABORT: rewritten parts no longer parse:")
        for n, e in bad[:10]:
            print(f"   {n}: {e}")
        return 2

    # Build subset HDF5.
    print(f"\nCopying {len(h5_paths)} HDF5 datasets -> {OUT_H5.name}")
    copied = skipped = 0
    with h5py.File(SRC_H5, "r") as src_h5, h5py.File(OUT_H5, "w") as dst_h5:
        for path in sorted(h5_paths):
            if path not in src_h5:
                skipped += 1
                continue
            src_h5.copy(src_h5[path], dst_h5, name=path)
            copied += 1
    print(f"  datasets copied: {copied}  missing: {skipped}")

    OUT_EPC.write_bytes(out.getvalue())
    print(f"Wrote {OUT_EPC.name} ({len(out.getvalue())//1024} KiB) and {OUT_H5.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
