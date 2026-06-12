#!/usr/bin/env python3
"""Reduce the proven-working drogon22.epc (RESQML 2.2) to a curated subset
analogous to the 2.0.1 Drogon demo (demo/drogonresqml/drogon.epc).

Strategy (reduce, do NOT re-convert):
  * Keep the full structural skeleton (CRS, features, interpretations, strat
    column/rank/units, Model, wellbores + trajectories + frames, the IJK grid,
    EpcExternalPartReference, PropertyKinds, fault polylines).
  * Reduce surfaces: keep 2 Grid2d (one depth-interpreted + one time-interpreted)
    and only the fault-related PointSets.
  * Keep only an analogous subset of properties (by title + supporting rep type),
    mirroring the 2.0.1 keep philosophy (~6-7 property types on grid and wells).
  * Compute the transitive DOR closure so there are NO dangling references.
  * Rebuild [Content_Types].xml and per-object .rels for the kept parts.
  * Build a reduced .h5 containing only the /RESQML/<uuid> groups referenced by
    the kept parts (copied from the 239MB companion drogon.h5).

Outputs (next to the source):
  drogon22_subset.epc
  drogon22_subset.h5   (URI inside the EPC is rewritten to this name)
"""
from __future__ import annotations
import os
import re
import sys
import zipfile
from collections import Counter, deque

HERE = os.path.dirname(os.path.abspath(__file__))
SRC_EPC = os.path.join(HERE, "drogon22.epc")
SRC_H5 = os.path.join(HERE, "drogon.h5")
OUT_EPC = os.path.join(HERE, "drogon22_subset.epc")
OUT_H5 = os.path.join(HERE, "drogon22_subset.h5")
OUT_H5_NAME = "drogon22_subset.h5"  # URI written into the reduced EPC

# ---- keep-lists (analogous to 2.0.1 curation) -----------------------------
# Well-log properties (supported by WellboreFrameRepresentation)
WELL_PROP_KEEP = {
    "Total Porosity",
    "Horizontal Permeability",
    "Water Saturation",
    "Shale Volume",
    "P-Wave Velocity",
    "Zone Index",
    "Facies",
    "Measured Depth",
}
# Grid properties (supported by IjkGridRepresentation)
GRID_PROP_KEEP = {
    "Total Porosity",
    "Horizontal Permeability",
    "Vertical Permeability",
    "Water Saturation",
    "Shale Volume",
    "Zone Index",
    "Facies",
}

# Structural / skeleton types kept in full
SKELETON_TYPES = {
    "LocalDepth3dCrs",
    "LocalTime3dCrs",
    "BoundaryFeature",
    "FaultInterpretation",
    "HorizonInterpretation",
    "StructuralOrganizationInterpretation",
    "RockVolumeFeature",
    "StratigraphicColumn",
    "StratigraphicColumnRankInterpretation",
    "StratigraphicUnitInterpretation",
    "Model",
    "WellboreFeature",
    "WellboreInterpretation",
    "WellboreTrajectoryRepresentation",
    "WellboreFrameRepresentation",
    "IjkGridRepresentation",
    "EpcExternalPartReference",
    "PropertyKind",
    "PolylineSetRepresentation",  # fault sticks
}

PROP_TYPES = {"ContinuousProperty", "DiscreteProperty", "CategoricalProperty"}

# ---------------------------------------------------------------------------
UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                     r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


def part_type(name: str) -> str:
    base = name.split("/")[-1]
    base = re.sub(r"_[0-9a-fA-F\-]{36}\.xml$", "", base)
    return base.replace("obj_", "")


def part_uuid(name: str) -> str | None:
    m = re.search(r"_([0-9a-fA-F\-]{36})\.xml$", name.split("/")[-1])
    return m.group(1).lower() if m else None


def get_title(xml: str) -> str:
    m = re.search(r"<(?:\w+:)?Title[^>]*>([^<]+)<", xml)
    return m.group(1) if m else "?"


def root_uuid(xml: str) -> str | None:
    m = re.search(r'uuid="([0-9a-fA-F\-]{36})"', xml)
    return m.group(1).lower() if m else None


def dor_targets(xml: str, self_uuid: str | None) -> set[str]:
    """All UUIDs referenced via <...:Uuid>UUID</...:Uuid> DOR elements."""
    out = set()
    for m in re.finditer(r"<(?:\w+:)?Uuid[^>]*>([0-9a-fA-F\-]{36})</", xml):
        out.add(m.group(1).lower())
    if self_uuid:
        out.discard(self_uuid)
    return out


def supporting_rep(xml: str) -> str | None:
    m = re.search(r"SupportingRepresentation.*?<(?:\w+:)?Uuid[^>]*>"
                  r"([0-9a-fA-F\-]{36})<", xml, re.S)
    return m.group(1).lower() if m else None


def array_uuids(xml: str) -> set[str]:
    """uuids appearing in /RESQML/<uuid>/ external array paths."""
    out = set()
    for m in re.finditer(r"/RESQML/([0-9a-fA-F\-]{36})/", xml):
        out.add(m.group(1).lower())
    return out


def main() -> int:
    if not os.path.exists(SRC_EPC):
        print(f"ERROR: missing {SRC_EPC}", file=sys.stderr)
        return 2
    if not os.path.exists(SRC_H5):
        print(f"ERROR: missing {SRC_H5}", file=sys.stderr)
        return 2

    z = zipfile.ZipFile(SRC_EPC)
    names = z.namelist()

    # object xml parts (exclude rels, docProps, content-types)
    obj_names = [n for n in names if n.endswith(".xml")
                 and "_rels" not in n and "docProps" not in n
                 and "Content_Types" not in n]

    parts: dict[str, dict] = {}      # uuid -> {name, type, title, xml, edges, support}
    uuid_to_name: dict[str, str] = {}
    for n in obj_names:
        xml = z.read(n).decode("utf-8", "replace")
        u = root_uuid(xml) or part_uuid(n)
        t = part_type(n)
        parts[u] = {
            "name": n,
            "type": t,
            "title": get_title(xml),
            "xml": xml,
            "edges": dor_targets(xml, u),
            "support": supporting_rep(xml) if t in PROP_TYPES else None,
        }
        uuid_to_name[u] = n

    # --- seed keep set --------------------------------------------------
    keep: set[str] = set()
    grid2d_depth = grid2d_time = None
    for u, p in parts.items():
        t = p["type"]
        if t in SKELETON_TYPES:
            keep.add(u)
        elif t == "Grid2dRepresentation":
            title = p["title"]
            if grid2d_depth is None and title == "Depth Surface - Interpreted":
                grid2d_depth = u
                keep.add(u)
            elif grid2d_time is None and title == "Time Surface - Interpreted":
                grid2d_time = u
                keep.add(u)
        elif t == "PointSetRepresentation":
            if "Fault Points" in p["title"]:
                keep.add(u)
        elif t in PROP_TYPES:
            sup = p["support"]
            sup_type = parts.get(sup, {}).get("type") if sup else None
            title = p["title"]
            if sup_type == "WellboreFrameRepresentation" and title in WELL_PROP_KEEP:
                keep.add(u)
            elif sup_type == "IjkGridRepresentation" and title in GRID_PROP_KEEP:
                keep.add(u)

    # --- transitive DOR closure (no dangling references) ----------------
    q = deque(keep)
    while q:
        u = q.popleft()
        for tgt in parts.get(u, {}).get("edges", set()):
            if tgt in parts and tgt not in keep:
                keep.add(tgt)
                q.append(tgt)

    # --- referenced array uuids -> reduced h5 groups --------------------
    needed_arrays: set[str] = set()
    for u in keep:
        needed_arrays |= array_uuids(parts[u]["xml"])

    # --- report ---------------------------------------------------------
    kept_types = Counter(parts[u]["type"] for u in keep)
    dropped = [u for u in parts if u not in keep]
    print(f"Source objects: {len(parts)}  ->  kept: {len(keep)}  dropped: {len(dropped)}")
    print("Kept by type:")
    for t, c in sorted(kept_types.items()):
        print(f"   {c:4d}  {t}")
    print(f"Array groups needed in reduced h5: {len(needed_arrays)}")

    # --- verify reference integrity over kept set -----------------------
    dangling = []
    for u in keep:
        for tgt in parts[u]["edges"]:
            if tgt not in keep and tgt in uuid_to_name:
                dangling.append((parts[u]["type"], u, parts[tgt]["type"], tgt))
    if dangling:
        print(f"WARNING: {len(dangling)} dangling DOR(s) after closure (should be 0):")
        for a, b, c, d in dangling[:10]:
            print(f"   {a} {b} -> {c} {d}")
    else:
        print("Reference integrity OK: 0 dangling DORs within kept set.")

    # --- build reduced h5 ----------------------------------------------
    import h5py
    miss = []
    with h5py.File(SRC_H5, "r") as src, h5py.File(OUT_H5, "w") as dst:
        grp = src.get("RESQML")
        if grp is None:
            print(f"ERROR: no /RESQML group in {SRC_H5}", file=sys.stderr)
            return 3
        outg = dst.create_group("RESQML")
        present = set(grp.keys())
        for au in sorted(needed_arrays):
            # match case-insensitively
            key = au if au in present else next(
                (k for k in present if k.lower() == au), None)
            if key is None:
                miss.append(au)
                continue
            src.copy(grp[key], outg, name=key)
    if miss:
        print(f"WARNING: {len(miss)} array uuids not found in source h5: {miss[:5]}")
    else:
        print(f"Reduced h5 written: all {len(needed_arrays)} array groups present.")

    # --- write reduced EPC ---------------------------------------------
    kept_names = {parts[u]["name"] for u in keep}
    # always-present packaging parts
    keep_aux = {n for n in names
                if "docProps" in n or n == "_rels/.rels"}

    def rewrite_uri(xml: str) -> str:
        # point all array URIs to the reduced h5
        xml = re.sub(r"(<(?:\w+:)?URI[^>]*>)[^<]*?\.h5(</)",
                     r"\g<1>" + OUT_H5_NAME + r"\g<2>", xml)
        xml = re.sub(r"(Filename[^>]*>)[^<]*?\.h5(<)",
                     r"\g<1>" + OUT_H5_NAME + r"\g<2>", xml)
        return xml

    def filter_rels(rels_xml: str) -> str:
        out_lines = []
        for line in rels_xml.splitlines():
            m = re.search(r'Target="([^"]+)"', line)
            if m and "Relationship " in line:
                tgt = m.group(1).split("/")[-1]
                # keep rel if target part is kept (or it's a non-object target)
                tgt_uuid = part_uuid(tgt)
                if tgt_uuid is not None and tgt not in {
                        nm.split("/")[-1] for nm in kept_names}:
                    continue  # drop rel to removed part
            out_lines.append(line)
        return "\n".join(out_lines)

    ct_overrides = []
    with zipfile.ZipFile(OUT_EPC, "w", zipfile.ZIP_DEFLATED) as zo:
        for u in sorted(keep, key=lambda x: parts[x]["name"]):
            n = parts[u]["name"]
            zo.writestr(n, rewrite_uri(parts[u]["xml"]))
            # carry its .rels (filtered)
            rels_name = f"_rels/{n.split('/')[-1]}.rels"
            if rels_name in names:
                zo.writestr(rels_name, filter_rels(
                    z.read(rels_name).decode("utf-8", "replace")))
        # docProps + root rels
        for n in keep_aux:
            zo.writestr(n, z.read(n))
        # [Content_Types].xml — rebuild from original, keep only kept parts
        ct_name = next(n for n in names if "Content_Types" in n)
        ct = z.read(ct_name).decode("utf-8", "replace")
        kept_basenames = {nm.split("/")[-1] for nm in kept_names}
        new_ct_lines = []
        for line in ct.splitlines():
            m = re.search(r'PartName="/([^"]+)"', line)
            if m and "Override" in line:
                base = m.group(1).split("/")[-1]
                u2 = part_uuid(base)
                if u2 is not None and base not in kept_basenames:
                    continue  # drop override for removed part
            new_ct_lines.append(line)
        zo.writestr(ct_name, "\n".join(new_ct_lines))

    print(f"\nReduced EPC written: {OUT_EPC}")
    print(f"Reduced h5 written:  {OUT_H5}")
    print(f"  ({os.path.getsize(OUT_EPC)//1024} KiB EPC, "
          f"{os.path.getsize(OUT_H5)//(1024*1024)} MiB h5)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
