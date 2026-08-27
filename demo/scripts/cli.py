#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cli.py - Main CLI for the OSDU record generation and ingestion suite.

Usage:
  python -m demo.scripts.cli generate --input drogon_DG2.json --output records/
  python -m demo.scripts.cli ingest --dir records/ --target interop
  python -m demo.scripts.cli template --type business_decision
  python -m demo.scripts.cli validate --dir records/
  python -m demo.scripts.cli pipeline --config drogon_DG2.json --target interop
  python -m demo.scripts.cli list-types

Or via the shortcut:
  python demo/scripts/cli.py pipeline --config demo/scripts/inputs/examples/drogon_DG2.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure imports work whether run as module or script
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR.parent) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR.parent))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from scripts.config import OsduInstance, load_config
from scripts.auth import get_token, resolve_instance, list_instances
from scripts.record_factory import (
    generate_blank_template,
    generate_record,
    generate_records_from_input,
    get_record_types,
    load_template,
    records_to_manifest,
)
from scripts.ingest import ingest_records, ingest_from_files
from scripts.manifest_splitter import split_manifest, split_manifests
from scripts.osdu_client import OsduClient


def main():
    parser = argparse.ArgumentParser(
        prog="osdu-scripts",
        description="Generic OSDU record generation and ingestion CLI.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full pipeline: generate + ingest from a dataset config
  %(prog)s pipeline --config inputs/examples/drogon_DG2.json --target interop

  # Generate records from JSON input
  %(prog)s generate --input my_project.json --output ./records

  # Ingest pre-generated records
  %(prog)s ingest --dir ./records --target interop

  # Get a blank template to fill in
  %(prog)s template --type business_decision > my_bd.json

  # Validate records before ingestion
  %(prog)s validate --dir ./records

  # List all supported record types
  %(prog)s list-types
""",
    )
    sub = parser.add_subparsers(dest="command", help="Available commands")

    # ── pipeline ─────────────────────────────────────────────────────────
    p_pipe = sub.add_parser("pipeline", help="Full pipeline: generate + ingest")
    p_pipe.add_argument("--config", "-c", required=True,
                        help="Dataset config JSON (e.g. drogon_DG2.json)")
    p_pipe.add_argument("--target", "-t", default="default",
                        help="Target instance name (default: 'default')")
    p_pipe.add_argument("--output", "-o", default=None,
                        help="Output directory for generated records")
    p_pipe.add_argument("--skip-ingest", action="store_true",
                        help="Generate only, don't ingest")
    p_pipe.add_argument("--dry-run", action="store_true",
                        help="Validate only, don't push to OSDU")
    p_pipe.add_argument("--token", help="Bearer token (or set OSDU_TOKEN)")
    p_pipe.add_argument("--config-file", help="Instance config file path")

    # ── generate ─────────────────────────────────────────────────────────
    p_gen = sub.add_parser("generate", help="Generate records from JSON input")
    p_gen.add_argument("--input", "-i", required=True,
                       help="Input JSON file (dataset config or record list)")
    p_gen.add_argument("--output", "-o", default="./records",
                       help="Output directory")
    p_gen.add_argument("--target", "-t", default="default",
                       help="Target instance name")
    p_gen.add_argument("--config-file", help="Instance config file path")
    p_gen.add_argument("--format", choices=["records", "manifest"], default="records",
                       help="Output format: individual records or manifest envelope")

    # ── ingest ───────────────────────────────────────────────────────────
    p_ing = sub.add_parser("ingest", help="Ingest records to OSDU")
    p_ing.add_argument("--dir", "-d", required=True,
                       help="Directory with record JSON files")
    p_ing.add_argument("--target", "-t", default="default",
                       help="Target instance name")
    p_ing.add_argument("--token", help="Bearer token (or set OSDU_TOKEN)")
    p_ing.add_argument("--dry-run", action="store_true")
    p_ing.add_argument("--rewrite-from", help="Source partition to rewrite from")
    p_ing.add_argument("--config-file", help="Instance config file path")

    # ── template ─────────────────────────────────────────────────────────
    p_tpl = sub.add_parser("template", help="Output a blank record template")
    p_tpl.add_argument("--type", "-T", required=True,
                       help="Record type (use 'list-types' to see options)")
    p_tpl.add_argument("--target", "-t", default="default",
                       help="Target instance (for ID prefixes)")
    p_tpl.add_argument("--config-file", help="Instance config file path")

    # ── validate ─────────────────────────────────────────────────────────
    p_val = sub.add_parser("validate", help="Validate records before ingestion")
    p_val.add_argument("--dir", "-d", required=True,
                       help="Directory with record JSON files")

    # ── split ────────────────────────────────────────────────────────────
    p_split = sub.add_parser("split", help="Split manifest into individual records")
    p_split.add_argument("--manifest", "-m", required=True, nargs="+",
                         help="Manifest JSON file(s)")
    p_split.add_argument("--output", "-o", help="Output directory")

    # ── list-types ───────────────────────────────────────────────────────
    sub.add_parser("list-types", help="List all supported record types")

    # ── list-generators ──────────────────────────────────────────────────
    sub.add_parser("list-generators", help="List all available data generators")

    # ── run-generator ────────────────────────────────────────────────────
    p_rgen = sub.add_parser("run-generator", help="Run a single data generator from a spec file")
    p_rgen.add_argument("--spec", "-s", required=True,
                        help="Generator spec JSON file")
    p_rgen.add_argument("--output", "-o", default="./output",
                        help="Output directory or manifest path")
    p_rgen.add_argument("--target", "-t", default="default",
                        help="Target instance (for partition prefix)")
    p_rgen.add_argument("--format", choices=["records", "manifest"], default="manifest",
                        help="Output format")
    p_rgen.add_argument("--config-file", help="Instance config file path")

    # ── list-instances ───────────────────────────────────────────────────
    sub.add_parser("list-instances", help="List available OSDU instances")

    # ── auth ─────────────────────────────────────────────────────────────
    p_auth = sub.add_parser("auth", help="Test auth / mint token for an instance")
    p_auth.add_argument("--target", "-t", default="interop",
                        help="Instance name to authenticate against")
    p_auth.add_argument("--rotate", action="store_true",
                        help="Rotate refresh token (print new token pair)")
    p_auth.add_argument("--show-token", action="store_true",
                        help="Print the access token (for pasting into other tools)")
    p_auth.add_argument("--export", action="store_true",
                        help="Print export TOKEN=... for eval in shell")
    p_auth.add_argument("--list", action="store_true",
                        help="List available instances")

    # ── search ───────────────────────────────────────────────────────────
    p_search = sub.add_parser("search", help="Search OSDU records by kind")
    p_search.add_argument("kinds", nargs="*", help="OSDU kind pattern(s)")
    p_search.add_argument("-q", "--query", default="*", help="Search query")
    p_search.add_argument("-l", "--limit", type=int, default=50, help="Max results")
    p_search.add_argument("--target", "-t", default="interop", help="Instance")
    p_search.add_argument("--id", dest="record_id", help="Fetch record by ID")
    p_search.add_argument("--list-kinds", dest="kind_pattern", help="List kinds matching pattern")
    p_search.add_argument("-o", "--output", choices=["table", "json"], default="table")
    p_search.add_argument("--token", help="Bearer token")
    p_search.add_argument("--config-file", help="Instance config file path")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Dispatch
    handlers = {
        "pipeline": cmd_pipeline,
        "generate": cmd_generate,
        "ingest": cmd_ingest,
        "template": cmd_template,
        "validate": cmd_validate,
        "split": cmd_split,
        "list-types": cmd_list_types,
        "list-generators": cmd_list_generators,
        "run-generator": cmd_run_generator,
        "list-instances": cmd_list_instances,
        "auth": cmd_auth,
        "search": cmd_search,
    }
    handlers[args.command](args)


# ═══════════════════════════════════════════════════════════════════════════
# Command implementations
# ═══════════════════════════════════════════════════════════════════════════

def cmd_pipeline(args):
    """Full pipeline: load config → generate records → ingest."""
    config_path = Path(args.config)
    if not config_path.exists():
        # Try relative to inputs/examples/
        alt = SCRIPT_DIR / "inputs" / "examples" / config_path.name
        if alt.exists():
            config_path = alt
        else:
            sys.exit(f"Config not found: {args.config}")

    input_config = json.loads(config_path.read_text(encoding="utf-8"))
    instance = _load_instance(args)

    print(f"═══ Pipeline: {input_config.get('project', 'unnamed')} "
          f"({input_config.get('gate', '')}) ═══")
    print(f"  Target: {instance.name} ({instance.host})")
    print(f"  Partition: {instance.partition}")
    print()

    # 1. Generate records
    print("── Step 1: Generate records ──")
    records = generate_records_from_input(input_config, instance,
                                          config_dir=config_path.parent)
    print(f"  Generated {len(records)} records")

    # 2. Write to disk
    output_dir = Path(args.output) if args.output else config_path.parent / "records"
    output_dir.mkdir(parents=True, exist_ok=True)
    for i, rec in enumerate(records):
        fname = f"{i:03d}_{_safe_fn(rec['id'])}.json"
        (output_dir / fname).write_text(json.dumps(rec, indent=2) + "\n", "utf-8")
    print(f"  Written to {output_dir}/")
    print()

    # 3. Ingest
    if args.skip_ingest:
        print("── Skipping ingestion (--skip-ingest) ──")
        return

    print("── Step 2: Ingest to OSDU ──")
    if args.dry_run:
        print("  [DRY RUN - no records will be pushed]")

    client = _make_client(instance, args)
    result = ingest_records(records, client, dry_run=args.dry_run)
    _print_result(result)


def cmd_generate(args):
    """Generate records from JSON input."""
    input_path = Path(args.input)
    if not input_path.exists():
        sys.exit(f"Input not found: {args.input}")

    input_config = json.loads(input_path.read_text(encoding="utf-8"))
    instance = _load_instance(args)

    records = generate_records_from_input(input_config, instance,
                                          config_dir=input_path.parent)
    print(f"Generated {len(records)} records")

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.format == "manifest":
        manifest = records_to_manifest(records)
        out_path = output_dir / "manifest.json"
        out_path.write_text(json.dumps(manifest, indent=2) + "\n", "utf-8")
        print(f"Written manifest to {out_path}")
    else:
        for i, rec in enumerate(records):
            fname = f"{i:03d}_{_safe_fn(rec['id'])}.json"
            (output_dir / fname).write_text(json.dumps(rec, indent=2) + "\n", "utf-8")
        print(f"Written {len(records)} record files to {output_dir}/")


def cmd_ingest(args):
    """Ingest records from a directory."""
    record_dir = Path(args.dir)
    if not record_dir.is_dir():
        sys.exit(f"Directory not found: {args.dir}")

    instance = _load_instance(args)
    client = _make_client(instance, args)

    print(f"Ingesting from {record_dir}/ → {instance.host}")
    if args.dry_run:
        print("  [DRY RUN]")

    result = ingest_from_files(
        record_dir, client,
        dry_run=args.dry_run,
        rewrite_partition=args.rewrite_from,
    )
    _print_result(result)


def cmd_template(args):
    """Output a blank record template."""
    rec_type = args.type.replace("-", "_")
    if rec_type not in get_record_types():
        sys.exit(
            f"Unknown type: {args.type}\n"
            f"Available: {', '.join(get_record_types())}"
        )
    instance = _load_instance(args)
    template = generate_blank_template(rec_type, instance)
    print(json.dumps(template, indent=2))


def cmd_validate(args):
    """Validate records in a directory."""
    record_dir = Path(args.dir)
    if not record_dir.is_dir():
        sys.exit(f"Directory not found: {args.dir}")

    files = sorted(record_dir.glob("*.json"))
    if not files:
        sys.exit(f"No JSON files in {args.dir}")

    records: List[Dict[str, Any]] = []
    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        if isinstance(data, list):
            records.extend(data)
        elif isinstance(data, dict) and "id" in data:
            records.append(data)

    # Use OsduClient validation (no auth needed)
    from scripts.osdu_client import OsduClient
    dummy_instance = OsduInstance(name="validate", host="", partition="validate")
    client = OsduClient(dummy_instance, token="dummy")
    errors = client.validate_records(records)

    if errors:
        print(f"✗ {len(errors)} validation errors:")
        for e in errors[:20]:
            print(f"  • {e}")
        if len(errors) > 20:
            print(f"  ... and {len(errors) - 20} more")
        sys.exit(1)
    else:
        print(f"✓ All {len(records)} records valid")


def cmd_split(args):
    """Split manifest(s) into individual records."""
    paths = [Path(p) for p in args.manifest]
    for p in paths:
        if not p.exists():
            sys.exit(f"File not found: {p}")

    output = Path(args.output) if args.output else None
    if len(paths) == 1:
        created = split_manifest(paths[0], output)
    else:
        created = split_manifests(paths, output)
    print(f"Created {len(created)} record files")


def cmd_list_types(args):
    """List supported record types with descriptions."""
    print("Supported record types:\n")
    for rt in get_record_types():
        try:
            tpl = load_template(rt)
            desc = tpl.get("_meta", {}).get("description", "")
        except FileNotFoundError:
            desc = "(no template)"
        print(f"  {rt:<30} {desc[:70]}")


def cmd_list_generators(args):
    """List available data generators."""
    from scripts.generators import GENERATORS
    from scripts.generators._registry import _import_all
    _import_all()
    print("Available data generators:\n")
    for name in sorted(GENERATORS):
        fn = GENERATORS[name]
        desc = (fn.__doc__ or "").strip().split("\n")[0][:70]
        print(f"  {name:<20} {desc}")
    print()
    print("Data spec files: demo/scripts/inputs/generators/")


def cmd_run_generator(args):
    """Run a single data generator from a spec file."""
    from scripts.generators import run_generator
    from scripts.generators._common import build_manifest

    spec_path = Path(args.spec)
    if not spec_path.exists():
        sys.exit(f"Spec not found: {args.spec}")

    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    instance = _load_instance(args)
    pfx = instance.partition if instance.partition else "dev"

    records = run_generator(spec, pfx, spec_path.parent)
    print(f"Generated {len(records)} records from '{spec.get('generator')}'")

    output = Path(args.output)
    if args.format == "manifest":
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.is_dir():
            out_path = output / f"manifest_{spec.get('generator', 'output')}.json"
        else:
            out_path = output
        manifest = build_manifest(
            master_data=[r for r in records if "master-data" in r.get("kind", "")],
            wpcs=[r for r in records if "work-product-component" in r.get("kind", "")],
            datasets=[r for r in records if "dataset--" in r.get("kind", "")],
            work_products=[r for r in records if "work-product:" in r.get("kind", "")],
        )
        out_path.write_text(json.dumps(manifest, indent=2) + "\n", "utf-8")
        print(f"Written manifest to {out_path}")
    else:
        output.mkdir(parents=True, exist_ok=True)
        for i, rec in enumerate(records):
            fname = f"{i:03d}_{_safe_fn(rec['id'])}.json"
            (output / fname).write_text(json.dumps(rec, indent=2) + "\n", "utf-8")
        print(f"Written {len(records)} record files to {output}/")


def cmd_list_instances(args):
    """List available OSDU instances."""
    instances = list_instances()
    print("Available instances:\n")
    for name in instances:
        try:
            inst = resolve_instance(name)
            status = f"{inst.host} (partition: {inst.partition})"
        except (RuntimeError, SystemExit):
            status = "(config incomplete)"
        print(f"  {name:<20} {status}")


def cmd_auth(args):
    """Test authentication / mint token for an instance."""
    from scripts.auth import rotate_token as _rotate_token

    # --list: show all instances
    if args.list:
        cmd_list_instances(args)
        return

    target = args.target

    # --export: print eval-able shell exports
    if args.export:
        try:
            tok = get_token(target)
            inst = resolve_instance(target)
            print(f"export TOKEN='{tok}'")
            print(f"export OSDU_HOST='{inst.host}'")
            print(f"export OSDU_PARTITION='{inst.partition}'")
        except RuntimeError as e:
            print(f"# Auth failed: {e}", file=sys.stderr)
            sys.exit(1)
        return

    print(f"Instance: {target}")

    if args.rotate:
        print("Rotating refresh token...")
        result = _rotate_token(target)
        print(f"  ✓ Access token obtained (expires_in: {result['expires_in']}s)")
        print(f"  Rotated: {result['rotated']}")
        if args.show_token:
            print(f"\n  access_token: {result['access_token'][:20]}...{result['access_token'][-10:]}")
            if result['rotated'] == 'true':
                print(f"  NEW refresh_token: {result['refresh_token'][:20]}...")
        return

    # Simple token test
    try:
        tok = get_token(target)
        print(f"  ✓ Token obtained ({len(tok)} chars)")
        if args.show_token:
            print(f"\n  {tok}")
        # Try a quick API call to verify
        inst = resolve_instance(target)
        if inst.host:
            import httpx
            resp = httpx.get(
                f"{inst.host}/api/storage/v2/info",
                headers={
                    "Authorization": f"Bearer {tok}",
                    "data-partition-id": inst.partition,
                },
                timeout=10,
            )
            if resp.status_code == 200:
                print(f"  ✓ API reachable ({inst.host})")
            else:
                print(f"  ⚠ API returned {resp.status_code} (token OK, endpoint may differ)")
    except RuntimeError as e:
        print(f"  ✗ Auth failed: {e}")
        sys.exit(1)


def cmd_search(args):
    """Search OSDU records by kind, fetch by ID, or list kinds."""
    import httpx

    target = args.target
    tok = args.token or os.environ.get("OSDU_TOKEN") or get_token(target)
    inst = resolve_instance(target)
    hdr = {
        "Authorization": f"Bearer {tok}",
        "Content-Type": "application/json",
        "data-partition-id": inst.partition,
    }

    # Fetch single record by ID
    if args.record_id:
        url = f"{inst.host}/api/storage/v2/records/{args.record_id}"
        resp = httpx.get(url, headers=hdr, timeout=30)
        if resp.status_code != 200:
            print(f"ERROR {resp.status_code}: {resp.text[:200]}", file=sys.stderr)
            sys.exit(1)
        rec = resp.json()
        if args.output == "json":
            print(json.dumps(rec, indent=2))
        else:
            print(f"  id:   {rec.get('id')}")
            print(f"  kind: {rec.get('kind')}")
            print(f"  Name: {(rec.get('data') or {}).get('Name', '')}")
            print(f"  keys: {list((rec.get('data') or {}).keys())}")
        return

    # List kinds matching a pattern
    if args.kind_pattern:
        pattern = args.kind_pattern
        url = f"{inst.host}/api/search/v2/query"
        for prefix in ["master-data", "work-product-component", "reference-data", "work-product", "dataset"]:
            kind = f"osdu:wks:{prefix}--*{pattern}*:*"
            payload = {"kind": kind, "query": "*", "limit": 0, "trackTotalCount": True}
            resp = httpx.post(url, headers=hdr, json=payload, timeout=30)
            if resp.status_code == 200:
                total = resp.json().get("totalCount", 0)
                if total > 0:
                    print(f"  {prefix}--*{pattern}*  →  {total} records")
        return

    # Search by kind(s)
    if not args.kinds:
        print("Provide kind pattern(s) or use --id / --list-kinds", file=sys.stderr)
        sys.exit(1)

    url = f"{inst.host}/api/search/v2/query"
    for kind in args.kinds:
        short = kind.split("--")[-1].split(":")[0] if "--" in kind else kind
        payload = {
            "kind": kind,
            "query": args.query,
            "limit": args.limit,
            "returnedFields": ["id", "kind", "version", "data.Name"],
            "trackTotalCount": True,
        }
        resp = httpx.post(url, headers=hdr, json=payload, timeout=30)
        if resp.status_code != 200:
            print(f"ERROR {resp.status_code} for {short}", file=sys.stderr)
            continue
        data = resp.json()
        total = data.get("totalCount", "?")
        results = data.get("results") or []

        print(f"\n{'━' * 60}")
        print(f"  {short}  -  {total} total, showing {len(results)}")
        print(f"{'━' * 60}")

        if args.output == "json":
            print(json.dumps(results, indent=2))
        else:
            for i, rec in enumerate(results, 1):
                name = ((rec.get("data") or {}).get("Name")) or "(unnamed)"
                print(f"  {i:3d}. {name}")
                print(f"       {rec.get('id', '?')}")


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

def _load_instance(args) -> OsduInstance:
    """Load instance config from args using the auth module."""
    target = getattr(args, "target", "default")
    try:
        return resolve_instance(target)
    except RuntimeError:
        # Fallback: load minimal config (for generate-only / validate flows)
        config_file = getattr(args, "config_file", None)
        return load_config(target, config_file=config_file)


def _make_client(instance: OsduInstance, args) -> OsduClient:
    """Create an authenticated OsduClient (full auth chain)."""
    token = getattr(args, "token", None) or os.environ.get("OSDU_TOKEN", "")
    if token:
        # Explicit token provided - use directly
        client = OsduClient(instance)
        client.set_token(token)
        return client
    # Use from_instance_name for full auth resolution
    return OsduClient.from_instance_name(instance.name)


def _safe_fn(record_id: str) -> str:
    """Make a record ID safe for use as a filename."""
    import re
    parts = record_id.split(":")
    if len(parts) >= 3:
        name = f"{parts[1]}_{parts[2]}"
    else:
        name = record_id
    return re.sub(r"[^a-zA-Z0-9_\-.]", "_", name)[:100]


def _print_result(result: Dict[str, Any]):
    """Print ingestion result summary."""
    ids = result.get("recordIds", [])
    errors = result.get("errors", [])
    mode = result.get("mode", "live")

    print(f"\n  Result ({mode}):")
    print(f"    ✓ Records: {len(ids)}")
    if errors:
        print(f"    ✗ Errors: {len(errors)}")
        for e in errors[:5]:
            print(f"      • {e}")


if __name__ == "__main__":
    main()
