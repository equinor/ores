#!/usr/bin/env python3
"""
build_drogon22_epc.py – Convert the RESQML 2.0.1 Drogon EPC to valid RESQML 2.2.

Uses resqml_v22_converter for proper XML-level transformations via lxml.
This script handles EPC-level concerns: zip packaging, filenames,
Content_Types.xml, .rels files, PropertyKind generation.

Usage:
    python build_drogon22_epc.py
"""
from __future__ import annotations

import re
import sys
import zipfile
from collections import Counter
from pathlib import Path

from resqml_v22_converter import (
    convert_object_xml,
    get_collected_property_kinds,
    make_property_kind_xml,
    reset_collected_property_kinds,
    TYPE_RENAMES,
    _pk_uuid,
    _convert_type_name,
)

SCRIPT_DIR = Path(__file__).resolve().parent
SRC_EPC = SCRIPT_DIR.parent / "drogonresqml" / "drogon.epc"
OUT_EPC = SCRIPT_DIR / "drogon_demo_22.epc"
H5_FILENAME = "drogon.h5"

# Types removed in RESQML 2.2 - exclude from output EPC
EXCLUDED_TYPES = {
    "MdDatum",
    "DeviationSurveyRepresentation",
}

# Objects whose HDF5 datasets are missing from all available source H5 files
EXCLUDED_UUIDS = {
    "023e0b30-3822-41a3-b4ad-7b8d34b5f42a",
    "4b836144-9eaf-4511-aea0-cee8b1d63994",
    "7d76b4fb-d927-4697-89a9-882b7a516a49",
    "ce5fac58-c8c8-44ad-be08-12f75a2af509",
    "d2fef43f-0aa0-427d-afc1-ab254b71fcd2",
    "eba48dd6-f2d0-49e1-b0d6-ad2f401c51f9",
}


def _convert_filename(old_name: str) -> str:
    """Convert filename: obj_Type_uuid.xml -> Type_uuid.xml"""
    m = re.match(r"obj_(\w+?)_([0-9a-f-]{36})\.xml", old_name)
    if m:
        old_type = m.group(1)
        obj_uuid = m.group(2)
        new_type = _convert_type_name(old_type)
        return f"{new_type}_{obj_uuid}.xml"
    return old_name


def _cleanup_broken_rels(epc_path: Path):
    """Remove .rels Relationship entries whose Target doesn't exist in the EPC."""
    with zipfile.ZipFile(epc_path, "r") as z:
        all_files = set(z.namelist())
        entries = {}
        for name in z.namelist():
            entries[name] = z.read(name)

    fixed = 0
    for name in list(entries.keys()):
        if not name.endswith(".rels"):
            continue
        content = entries[name].decode("utf-8")
        original = content

        def _keep_rel(m):
            nonlocal fixed
            target_m = re.search(r'Target="([^"]+)"', m.group(0))
            if not target_m:
                return m.group(0)
            target = target_m.group(1)
            if target.endswith(".h5") or target.startswith("http"):
                return m.group(0)
            if target in all_files:
                return m.group(0)
            fixed += 1
            return ""

        content = re.sub(r"\s*<Relationship[^>]*/>", _keep_rel, content)
        if content != original:
            entries[name] = content.encode("utf-8")

    if fixed > 0:
        tmp = epc_path.with_suffix(".tmp")
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
            for name, data in entries.items():
                zout.writestr(name, data)
        tmp.replace(epc_path)
        print(f"  Cleaned {fixed} broken .rels entries")


def _build_rels_from_dors(epc_path: Path):
    """Post-process EPC: regenerate all .rels files from DOR references in XML.

    This creates proper OPC relationship files matching the Energistics EPC spec:
    - Core _rels/.rels: minimal (empty or just docProps)
    - Per-object .rels: sourceObject + destinationObject relationships based on
      actual DOR <eml:Uuid> references in the XML
    - Objects that reference H5 via <eml:URI> don't need EpcExternalPartReference
    """
    with zipfile.ZipFile(epc_path, "r") as z:
        all_data = {name: z.read(name) for name in z.namelist()}

    # Collect object metadata: filename → uuid, and uuid → filename
    uuid_to_file = {}
    file_to_uuid = {}
    xml_parts = set()
    for name in all_data:
        if name.endswith(".xml") and not name.startswith("[") and not name.startswith("_"):
            xml_parts.add(name)
            txt = all_data[name].decode("utf-8")[:500]
            m = re.search(r'uuid="([0-9a-f-]{36})"', txt, re.I)
            if m:
                uid = m.group(1)
                uuid_to_file[uid] = name
                file_to_uuid[name] = uid

    # Build DOR reference graph: source_file → set of target_files
    # Also build reverse: target_file → set of source_files
    dest_refs = {}  # file → {target_files}
    src_refs = {}   # file → {source_files that reference it}
    for name in xml_parts:
        txt = all_data[name].decode("utf-8")
        own_uuid = file_to_uuid.get(name, "")
        targets = set()
        for m in re.finditer(r"<eml:Uuid>([0-9a-f-]{36})</eml:Uuid>", txt, re.I):
            ref_uuid = m.group(1)
            if ref_uuid != own_uuid and ref_uuid in uuid_to_file:
                targets.add(uuid_to_file[ref_uuid])
        if targets:
            dest_refs[name] = targets
            for t in targets:
                src_refs.setdefault(t, set()).add(name)

    # Remove old .rels files and EpcExternalPartReference
    new_data = {}
    epc_ext_removed = 0
    for name, data in all_data.items():
        if name.endswith(".rels"):
            continue  # will regenerate
        if "EpcExternalPartReference" in name:
            epc_ext_removed += 1
            continue  # v2.2 doesn't need this
        new_data[name] = data

    # Remove EpcExternalPartReference from [Content_Types].xml
    if "[Content_Types].xml" in new_data:
        ct = new_data["[Content_Types].xml"].decode("utf-8")
        ct = re.sub(r'\s*<Override[^>]*EpcExternalPartReference[^>]*/>', '', ct)
        new_data["[Content_Types].xml"] = ct.encode("utf-8")

    # Generate core _rels/.rels (minimal - just the standard marker)
    core_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
        '</Relationships>\n'
    )
    new_data["_rels/.rels"] = core_rels.encode("utf-8")

    # Generate per-object .rels with source + destination relationships
    total_rels = 0
    for name in sorted(xml_parts):
        if "EpcExternalPartReference" in name:
            continue
        own_uuid = file_to_uuid.get(name, "")
        rels_entries = []

        # destinationObject: objects that THIS object references
        for target in sorted(dest_refs.get(name, [])):
            rel_id = f"{own_uuid}_{target}"
            rels_entries.append(
                f'    <Relationship Target="{target}" '
                f'Type="http://schemas.energistics.org/package/2012/relationships/destinationObject" '
                f'Id="{rel_id}"/>'
            )

        # sourceObject: objects that reference THIS object
        for source in sorted(src_refs.get(name, [])):
            if "EpcExternalPartReference" in source:
                continue
            source_uuid = file_to_uuid.get(source, "")
            rel_id = f"{own_uuid}_{source}"
            rels_entries.append(
                f'    <Relationship Target="{source}" '
                f'Type="http://schemas.energistics.org/package/2012/relationships/sourceObject" '
                f'Id="{rel_id}"/>'
            )

        total_rels += len(rels_entries)

        rels_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
            + "\n".join(rels_entries) + "\n"
            '</Relationships>\n'
        )
        rels_name = f"_rels/{name}.rels"
        new_data[rels_name] = rels_xml.encode("utf-8")

    # Write output
    tmp = epc_path.with_suffix(".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for name in sorted(new_data):
            zout.writestr(name, new_data[name])
    tmp.replace(epc_path)

    print(f"  Regenerated OPC relationships: {total_rels} entries across {len(xml_parts)} objects")
    if epc_ext_removed:
        print(f"  Removed EpcExternalPartReference (not needed in v2.2)")


def main():
    if not SRC_EPC.exists():
        sys.exit(f"Source EPC not found: {SRC_EPC}")

    print(f"Converting RESQML 2.0.1 -> 2.2 (full schema transformation)")
    print(f"  Source: {SRC_EPC}")
    print(f"  Output: {OUT_EPC}")

    reset_collected_property_kinds()
    type_counts: Counter = Counter()
    renamed_count = 0
    excluded_count = 0
    ct_xml_deferred = ""
    ct_name_deferred = ""

    with zipfile.ZipFile(SRC_EPC, "r") as src:
        with zipfile.ZipFile(OUT_EPC, "w", zipfile.ZIP_DEFLATED) as dst:
            for old_name in src.namelist():
                content_bytes = src.read(old_name)

                # ── Object XML files (obj_Type_uuid.xml) ─────────────
                if old_name.endswith(".xml") and old_name.startswith("obj_"):
                    m = re.match(r"obj_(\w+?)_([0-9a-f-]{36})\.xml", old_name)
                    old_type = m.group(1) if m else ""
                    obj_uuid = m.group(2) if m else ""

                    # Skip types removed in v2.2
                    if old_type in EXCLUDED_TYPES:
                        excluded_count += 1
                        continue

                    # Skip objects with missing HDF5 data
                    if obj_uuid in EXCLUDED_UUIDS:
                        excluded_count += 1
                        continue

                    # Skip EpcExternalPartReference (not needed in v2.2)
                    if old_type == "EpcExternalPartReference":
                        excluded_count += 1
                        continue

                    # Convert XML content
                    converted_xml, new_type = convert_object_xml(
                        content_bytes, old_type, H5_FILENAME
                    )
                    type_counts[new_type] += 1
                    if old_type.replace("obj_", "") != new_type:
                        renamed_count += 1

                    new_name = _convert_filename(old_name)
                    dst.writestr(new_name, converted_xml)

                # ── [Content_Types].xml ───────────────────────────────
                elif old_name == "[Content_Types].xml":
                    ct_xml = content_bytes.decode("utf-8")
                    # Rename obj_ in PartNames
                    ct_xml = re.sub(
                        r'obj_(\w+?)_',
                        lambda m2: f"{_convert_type_name(m2.group(1))}_",
                        ct_xml,
                    )
                    # Update ContentType to v2.2 format
                    def _fix_content_type(m2):
                        app = m2.group(1)
                        tname = m2.group(2)
                        clean_type = re.sub(r'^obj_', '', tname)
                        clean_type = _convert_type_name(clean_type)
                        ver = "2.3" if app == "x-eml+xml" else "2.2"
                        return f'application/{app};version={ver};type={clean_type}'

                    ct_xml = re.sub(
                        r'application/(x-(?:resqml|eml)\+xml);version=2\.0;type=(obj_\w+)',
                        _fix_content_type,
                        ct_xml,
                    )
                    # Remove entries for excluded types, UUIDs, EpcExternalPartReference,
                    # and the Default Extension="xml" catch-all (confuses ETP client)
                    ct_xml = re.sub(
                        r'\s*<Default\s+Extension="xml"[^>]*/>', '', ct_xml
                    )
                    for excl_type in EXCLUDED_TYPES | {"EpcExternalPartReference"}:
                        ct_xml = re.sub(
                            rf'<Override[^>]*PartName="/(?:obj_)?{excl_type}_[^"]*"[^>]*/>\s*',
                            "",
                            ct_xml,
                        )
                    for excl_uuid in EXCLUDED_UUIDS:
                        ct_xml = re.sub(
                            rf'<Override[^>]*PartName="[^"]*{excl_uuid}[^"]*"[^>]*/>\s*',
                            "",
                            ct_xml,
                        )
                    ct_xml_deferred = ct_xml
                    ct_name_deferred = old_name

                # ── Skip all .rels (will be regenerated) ──────────────
                elif old_name.endswith(".rels"):
                    continue

                # ── Skip other non-obj XML files (EpcExternalPartReference etc.) ──
                elif old_name.endswith(".xml") and not old_name.startswith("["):
                    continue

                # ── Pass-through (other files) ────────────────────────
                else:
                    dst.writestr(old_name, content_bytes)

            # ── Add PropertyKind objects ──────────────────────────────
            pk_names = get_collected_property_kinds()
            if pk_names:
                for kind_name in sorted(pk_names):
                    pk_xml = make_property_kind_xml(kind_name)
                    pk_uuid = _pk_uuid(kind_name)
                    pk_filename = f"PropertyKind_{pk_uuid}.xml"
                    dst.writestr(pk_filename, pk_xml)
                    type_counts["PropertyKind"] += 1

                    # Add to [Content_Types].xml
                    ct_xml_deferred = ct_xml_deferred.replace(
                        "</Types>",
                        f' <Override PartName="/{pk_filename}" '
                        f'ContentType="application/x-eml+xml;version=2.3;type=PropertyKind"/>\n</Types>',
                    )
                print(f"  Added {len(pk_names)} PropertyKind objects")

            # Write [Content_Types].xml
            if ct_name_deferred:
                dst.writestr(ct_name_deferred, ct_xml_deferred.encode("utf-8"))

    # Post-process: regenerate OPC .rels from DOR references
    _build_rels_from_dors(OUT_EPC)

    print(
        f"\n  Converted {sum(type_counts.values())} objects "
        f"({renamed_count} type renames, {excluded_count} excluded)"
    )
    print(f"  Types:")
    for t, c in sorted(type_counts.items()):
        print(f"    {t:45s} {c:4d}")
    print(f"\n  Output: {OUT_EPC} ({OUT_EPC.stat().st_size / 1024:.0f} KB)")

    # Quick verification
    print("\n  Verifying sample...")
    with zipfile.ZipFile(OUT_EPC) as z:
        names = [
            n
            for n in z.namelist()
            if n.endswith(".xml") and not n.startswith("[") and not n.startswith("_")
        ]
        has_obj = any(n.startswith("obj_") for n in names)
        sample_issues = []
        for n in names[:20]:
            content = z.read(n).decode()
            if "<eml:ContentType" in content:
                sample_issues.append(f"  {n}: still has <eml:ContentType>")
            if "<eml:UUID" in content:
                sample_issues.append(f"  {n}: still has <eml:UUID>")
            if 'schemaVersion="2.0"' in content:
                sample_issues.append(f"  {n}: still has schemaVersion 2.0")

        print(f"    obj_ prefix remaining: {'YES !!' if has_obj else 'NO ok'}")
        if sample_issues:
            print(f"    Issues found ({len(sample_issues)}):")
            for i in sample_issues[:5]:
                print(f"      {i}")
        else:
            print(f"    Sample check: OK")

    print("\n  Done")


if __name__ == "__main__":
    main()
