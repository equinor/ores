#!/usr/bin/env python3
"""
test_scripts.py - Quick smoke test for the generic scripts suite.

Run: python demo/scripts/test_scripts.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

# Ensure imports work
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parent))

from scripts.config import OsduInstance, load_config
from scripts.record_factory import (
    generate_blank_template,
    generate_record,
    generate_records_from_input,
    get_record_types,
    load_template,
    make_kind,
    make_record_id,
    manifest_to_records,
    records_to_manifest,
)
from scripts.ingest import ingest_records
from scripts.manifest_splitter import split_manifest
from scripts.osdu_client import OsduClient


def test_instance():
    """Instance config loads with defaults."""
    inst = OsduInstance(
        name="test",
        host="https://example.com",
        partition="testpart",
        legal_tag="testpart-legal-tag",
        owners=["data.owners@testpart.example.com"],
        viewers=["data.viewers@testpart.example.com"],
        countries=["NO"],
    )
    assert inst.acl == {
        "owners": ["data.owners@testpart.example.com"],
        "viewers": ["data.viewers@testpart.example.com"],
    }
    assert inst.legal == {
        "legaltags": ["testpart-legal-tag"],
        "otherRelevantDataCountries": ["NO"],
    }
    print("  ✓ Instance config")


def test_record_types():
    """All registered types have templates."""
    types = get_record_types()
    assert len(types) >= 10, f"Expected ≥10 types, got {len(types)}"
    for rt in types:
        tpl = load_template(rt)
        assert "data" in tpl, f"Template {rt} missing 'data'"
        assert "_meta" in tpl, f"Template {rt} missing '_meta'"
    print(f"  ✓ {len(types)} record types with templates")


def test_make_ids():
    """Record IDs are deterministic."""
    id1 = make_record_id("dev", "business_decision", "my-slug", 1)
    id2 = make_record_id("dev", "business_decision", "my-slug", 1)
    assert id1 == id2, "IDs not deterministic"
    assert id1.startswith("dev:master-data--BusinessDecision:")
    assert id1.endswith(":1")
    print("  ✓ Deterministic record IDs")


def test_make_kind():
    """Kind strings are well-formed."""
    kind = make_kind("risk")
    assert kind == "osdu:wks:master-data--Risk:1.2.0"
    kind2 = make_kind("activity")
    assert kind2 == "osdu:wks:work-product-component--Activity:1.0.0"
    print("  ✓ Kind strings")


def test_generate_blank():
    """Blank template generates valid envelope."""
    inst = OsduInstance(
        name="t", partition="dev", host="https://x.com",
        legal_tag="dev-tag", owners=["o@dev"], viewers=["v@dev"],
    )
    rec = generate_blank_template("business_decision", inst)
    assert "id" in rec
    assert "kind" in rec
    assert "acl" in rec
    assert "legal" in rec
    assert "data" in rec
    assert rec["kind"] == "osdu:wks:master-data--BusinessDecision:1.0.0"
    print("  ✓ Blank template generation")


def test_generate_record():
    """Record generation merges data with template."""
    inst = OsduInstance(
        name="t", partition="dev", host="https://x.com",
        legal_tag="dev-tag", owners=["o@dev"], viewers=["v@dev"],
    )
    rec = generate_record("risk", inst, {
        "Name": "Test Risk",
        "Description": "A test risk",
        "MitigationStatus": "Open",
    }, slug="test-risk-1")
    assert rec["data"]["Name"] == "Test Risk"
    assert rec["data"]["MitigationStatus"] == "Open"
    assert "dev:master-data--Risk:" in rec["id"]
    print("  ✓ Record generation with data merge")


def test_generate_from_config():
    """Full pipeline config generates expected records."""
    inst = OsduInstance(
        name="t", partition="dev", host="https://x.com",
        legal_tag="dev-tag", owners=["o@dev"], viewers=["v@dev"],
    )
    config_path = SCRIPT_DIR / "inputs" / "examples" / "drogon_DG2.json"
    config = json.loads(config_path.read_text("utf-8"))
    records = generate_records_from_input(config, inst)
    assert len(records) >= 10, f"Expected ≥10 records, got {len(records)}"

    # Check we got the expected types
    kinds = {r["kind"] for r in records}
    assert "osdu:wks:master-data--BusinessDecision:1.0.0" in kinds
    assert "osdu:wks:master-data--Risk:1.2.0" in kinds
    assert "osdu:wks:work-product-component--Activity:1.0.0" in kinds
    print(f"  ✓ Config-driven generation ({len(records)} records from drogon_DG2.json)")


def test_manifest_roundtrip():
    """Records → manifest → records roundtrip."""
    inst = OsduInstance(
        name="t", partition="dev", host="https://x.com",
        legal_tag="dev-tag", owners=["o@dev"], viewers=["v@dev"],
    )
    records = [
        generate_record("risk", inst, {"Name": "R1"}, slug="r1"),
        generate_record("business_decision", inst, {"Name": "BD1"}, slug="bd1"),
        generate_record("activity", inst, {"Name": "A1"}, slug="a1"),
    ]
    manifest = records_to_manifest(records)
    assert "MasterData" in manifest
    assert "Data" in manifest

    recovered = manifest_to_records(manifest)
    assert len(recovered) == 3
    print("  ✓ Manifest roundtrip")


def test_manifest_split():
    """Split manifest writes individual files."""
    inst = OsduInstance(
        name="t", partition="dev", host="https://x.com",
        legal_tag="dev-tag", owners=["o@dev"], viewers=["v@dev"],
    )
    records = [
        generate_record("risk", inst, {"Name": f"R{i}"}, slug=f"r{i}")
        for i in range(5)
    ]
    manifest = records_to_manifest(records)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        manifest_file = tmp_path / "manifest.json"
        manifest_file.write_text(json.dumps(manifest), "utf-8")

        created = split_manifest(manifest_file, tmp_path / "records")
        assert len(created) == 5
        # Verify files are valid JSON
        for f in created:
            rec = json.loads(f.read_text("utf-8"))
            assert "id" in rec
            assert "kind" in rec
    print("  ✓ Manifest split")


def test_validate():
    """Client-side validation catches missing fields."""
    inst = OsduInstance(name="t", partition="dev", host="")
    client = OsduClient(inst, token="dummy")

    # Valid record
    valid = [{"id": "dev:x--Y:z:1", "kind": "osdu:wks:x--Y:1.0.0",
              "acl": {}, "legal": {}, "data": {}}]
    assert client.validate_records(valid) == []

    # Invalid records
    invalid = [{"id": "no-colon"}, {}]
    errors = client.validate_records(invalid)
    assert len(errors) > 0
    print("  ✓ Validation")


def test_all_example_configs():
    """All example configs generate valid records."""
    inst = OsduInstance(
        name="t", partition="dev", host="https://x.com",
        legal_tag="dev-tag", owners=["o@dev"], viewers=["v@dev"],
    )
    examples_dir = SCRIPT_DIR / "inputs" / "examples"
    for config_file in sorted(examples_dir.glob("*.json")):
        config = json.loads(config_file.read_text("utf-8"))
        records = generate_records_from_input(config, inst)
        assert len(records) > 0, f"{config_file.name}: no records generated"

        # Validate all records
        client = OsduClient(inst, token="dummy")
        errors = client.validate_records(records)
        assert not errors, f"{config_file.name}: {errors}"
    print(f"  ✓ All example configs valid ({len(list(examples_dir.glob('*.json')))} files)")


def main():
    print("═══ Script Suite Tests ═══\n")
    tests = [
        test_instance,
        test_record_types,
        test_make_ids,
        test_make_kind,
        test_generate_blank,
        test_generate_record,
        test_generate_from_config,
        test_manifest_roundtrip,
        test_manifest_split,
        test_validate,
        test_all_example_configs,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"  ✗ {test.__name__}: {e}")
            failed += 1

    print(f"\n{'═' * 40}")
    print(f"  {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
    print("  All tests passed ✓")


if __name__ == "__main__":
    main()
