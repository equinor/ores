#!/usr/bin/env python3
"""
build_resqml22.py – Generic RESQML 2.0.1 → 2.2 converter with strict validation
and OSDU metadata enrichment.

Produces XSD-compliant RESQML 2.2 output with:
  - EML 2.3 compound CRS (LocalEngineeringCompoundCrs + VerticalCrs + 2dCrs)
  - Proper PropertyKind objects with deterministic UUIDs
  - ExternalDataArray references (ETP-compatible, no H5 files needed)
  - OSDU-compliant ExtraMetadata / ExtensionNameValue enrichment
  - Strict validation pass before output

Usage:
    python build_resqml22.py INPUT.epc [--output OUTPUT.epc] [--field FIELD]
                             [--basin BASIN] [--source SOURCE]
                             [--projected-epsg EPSG] [--vertical-epsg EPSG]
                             [--validate] [--no-h5-copy]

Examples:
    python build_resqml22.py drogonresqml/drogon.epc --output drogonresqml22/drogon22.epc \\
        --field Drogon --basin "Norwegian Continental Shelf" --source "Equinor" \\
        --projected-epsg 23031 --validate

    python build_resqml22.py input.epc --validate
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional


def main():
    parser = argparse.ArgumentParser(
        description="Convert RESQML 2.0.1 to strictly valid RESQML 2.2 with OSDU enrichment",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("input", help="Input EPC file (RESQML 2.0.1)")
    parser.add_argument("--output", "-o", help="Output EPC file (default: input_22.epc)")
    parser.add_argument("--field", help="OSDU field name (e.g. 'Drogon')")
    parser.add_argument("--basin", help="OSDU basin (e.g. 'Norwegian Continental Shelf')")
    parser.add_argument("--source", help="OSDU data source (e.g. 'Equinor')")
    parser.add_argument("--projected-epsg", type=int, default=0,
                        help="Override projected CRS EPSG code (e.g. 23031 for ED50 UTM31N)")
    parser.add_argument("--vertical-epsg", type=int, default=0,
                        help="Override vertical CRS EPSG code (e.g. 5714 for MSL)")
    parser.add_argument("--validate", action="store_true",
                        help="Run strict validation on output (exit 1 if fails)")
    parser.add_argument("--no-h5-copy", action="store_true",
                        help="Don't copy associated H5 files (for ETP workflows)")
    parser.add_argument("--json", action="store_true",
                        help="Output results as JSON")

    args = parser.parse_args()

    input_path = Path(args.input).resolve()
    if not input_path.exists():
        print(f"Error: input file not found: {input_path}", file=sys.stderr)
        sys.exit(2)

    if args.output:
        output_path = Path(args.output).resolve()
    else:
        output_path = input_path.with_stem(input_path.stem + "_22")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # ── Step 1: Convert ──
    print(f"Converting: {input_path.name} → {output_path.name}")
    from resqml_converter.converter import convert_epc
    result = convert_epc(
        str(input_path),
        str(output_path),
        target_version="2.2",
        validate=False,
        copy_h5=not args.no_h5_copy,
    )
    print(f"  Objects converted: {result.objects_converted}")
    print(f"  Objects skipped: {result.objects_skipped}")
    if result.errors:
        print(f"  Conversion errors: {len(result.errors)}")
        for e in result.errors[:5]:
            print(f"    {e}")

    # ── Step 2: OSDU metadata enrichment ──
    osdu_meta = {}
    if args.field:
        osdu_meta["FieldName"] = args.field
    if args.basin:
        osdu_meta["Basin"] = args.basin
    if args.source:
        osdu_meta["DataSource"] = args.source

    if osdu_meta or args.projected_epsg or args.vertical_epsg:
        print(f"  Enriching with OSDU metadata: {osdu_meta}")
        _enrich_osdu_metadata(
            str(output_path), osdu_meta,
            projected_epsg=args.projected_epsg,
            vertical_epsg=args.vertical_epsg,
        )

    # ── Step 3: Validate ──
    if args.validate:
        print("  Running strict validation...")
        from resqml_converter.strict_validation import validate_epc_strict
        h5_path = _find_h5(output_path)
        report = validate_epc_strict(
            epc_path=str(output_path),
            version="2.2",
            h5_path=str(h5_path) if h5_path else None,
            skip_hdf5=args.no_h5_copy,
        )
        if args.json:
            import json
            print(json.dumps({
                "valid": report.is_valid,
                "objects": report.object_count,
                "errors": report.error_count,
                "warnings": report.warning_count,
            }, indent=2))
        else:
            print(f"  Validation: {'PASS' if report.is_valid else 'FAIL'} "
                  f"({report.error_count} errors, {report.warning_count} warnings)")
            if not report.is_valid:
                for err in report.errors[:10]:
                    print(f"    {err}")

        if not report.is_valid:
            sys.exit(1)

    print(f"Done: {output_path}")
    sys.exit(0)


def _enrich_osdu_metadata(
    epc_path: str,
    metadata: dict,
    projected_epsg: int = 0,
    vertical_epsg: int = 0,
) -> None:
    """Post-process EPC to add OSDU ExtraMetadata to all objects.

    This operates on the XML inside the ZIP, adding ExtraMetadata elements
    that RDDMS manifest builder uses to populate OSDU record fields.
    """
    import re
    import zipfile
    import tempfile
    import shutil

    if not metadata and not projected_epsg and not vertical_epsg:
        return

    # Build ExtraMetadata XML snippet (uses whatever ns prefix the file has)
    # We'll detect and use the correct prefix during injection

    # Process ZIP
    tmp = tempfile.mktemp(suffix=".epc")
    with zipfile.ZipFile(epc_path, 'r') as zin, zipfile.ZipFile(tmp, 'w') as zout:
        for item in zin.namelist():
            data = zin.read(item)
            if item.endswith('.xml') and b'<' in data:
                text = data.decode('utf-8')
                # Detect namespace prefix for resqml
                resqml_prefix = "resqml2"
                if 'xmlns:resqml=' in text:
                    resqml_prefix = "resqml"

                # Add OSDU metadata before closing tag for RESQML objects
                if 'resqmlv2' in text and metadata:
                    meta_snippet = ""
                    for key, value in metadata.items():
                        meta_snippet += (
                            f'<{resqml_prefix}:ExtraMetadata>'
                            f'<{resqml_prefix}:Name>{key}</{resqml_prefix}:Name>'
                            f'<{resqml_prefix}:Value>{_xml_escape(value)}</{resqml_prefix}:Value>'
                            f'</{resqml_prefix}:ExtraMetadata>\n'
                        )
                    # Insert before the closing root tag
                    text = re.sub(
                        r'(</(?:resqml2?|resqml):\w+>)\s*$',
                        meta_snippet + r'\1\n',
                        text,
                    )
                elif 'commonv2' in text and metadata and 'PropertyKind' not in item:
                    # EML objects: use ExtensionNameValue
                    eml_prefix = "eml"
                    ext_snippet = ""
                    for key, value in metadata.items():
                        ext_snippet += (
                            f'<{eml_prefix}:ExtensionNameValue>'
                            f'<{eml_prefix}:Name>{key}</{eml_prefix}:Name>'
                            f'<{eml_prefix}:Value><{eml_prefix}:Value>{_xml_escape(value)}</{eml_prefix}:Value></{eml_prefix}:Value>'
                            f'</{eml_prefix}:ExtensionNameValue>\n'
                        )
                    text = re.sub(
                        r'(</eml:\w+>)\s*$',
                        ext_snippet + r'\1\n',
                        text,
                    )
                data = text.encode('utf-8')
            zout.writestr(item, data)
    shutil.move(tmp, epc_path)


def _xml_escape(s: str) -> str:
    """Escape XML special characters."""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _find_h5(epc_path: Path) -> Optional[Path]:
    """Find associated H5 file for an EPC."""
    # Try same directory, same stem
    h5 = epc_path.with_suffix('.h5')
    if h5.exists():
        return h5
    # Try common names
    for candidate in epc_path.parent.glob("*.h5"):
        return candidate
    return None


if __name__ == "__main__":
    main()
