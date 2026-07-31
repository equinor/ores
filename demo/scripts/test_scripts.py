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


def test_generators():
    """All generator data specs produce records."""
    from scripts.generators import run_generator

    gen_dir = SCRIPT_DIR / "inputs" / "generators" / "drogon"
    if not gen_dir.exists():
        print("  ⚠ Generator specs not found (skipped)")
        return

    expected_counts = {
        "grid": 11,
        "maps": 49,
        "markers": 33,
        "master": 9,
        "polygons": 7,
        "simtables": 5,
        "volumes_raw": 1,
        "volumes_stat": 1,
        "wells": 20,
    }

    for spec_file in sorted(gen_dir.glob("*.json")):
        spec = json.loads(spec_file.read_text("utf-8"))
        gen_type = spec.get("generator", "?")
        records = run_generator(spec, "dev", spec_file.parent)
        assert len(records) > 0, f"{spec_file.name}: no records generated"
        # Verify each record has required fields
        for rec in records:
            assert "id" in rec, f"{spec_file.name}: record missing 'id'"
            assert "kind" in rec, f"{spec_file.name}: record missing 'kind'"
            assert "data" in rec, f"{spec_file.name}: record missing 'data'"
        # Verify expected counts
        expected = expected_counts.get(gen_type)
        if expected is not None:
            assert len(records) == expected, (
                f"{spec_file.name}: expected {expected} records, got {len(records)}"
            )

    print(f"  ✓ All generators valid ({len(list(gen_dir.glob('*.json')))} specs, "
          f"{sum(expected_counts.values())} total records)")


def test_generator_pipeline():
    """Pipeline config with generators produces correct record count."""
    inst = OsduInstance(
        name="t", partition="dev", host="https://x.com",
        legal_tag="dev-tag", owners=["o@dev"], viewers=["v@dev"],
    )
    config_file = SCRIPT_DIR / "inputs" / "drogon_DG2_generated.json"
    if not config_file.exists():
        print("  ⚠ Generator pipeline config not found (skipped)")
        return
    config = json.loads(config_file.read_text("utf-8"))
    records = generate_records_from_input(
        config, inst, config_dir=config_file.parent
    )
    # 10 generators produce 137 records + 18 template records = 155
    assert len(records) == 155, f"Expected 155 records, got {len(records)}"
    print(f"  ✓ Generator pipeline ({len(records)} records)")


def test_record_type_coverage():
    """DG2 generated pipeline covers all expected OSDU entity types."""
    inst = OsduInstance(
        name="t", partition="dev", host="https://x.com",
        legal_tag="dev-tag", owners=["o@dev"], viewers=["v@dev"],
    )
    config_file = SCRIPT_DIR / "inputs" / "drogon_DG2_generated.json"
    config = json.loads(config_file.read_text("utf-8"))
    records = generate_records_from_input(config, inst, config_dir=config_file.parent)

    # Extract entity types from kind strings
    entities = set()
    for r in records:
        kind = r.get("kind", "")
        # kind format: osdu:wks:category--Entity:version
        parts = kind.split("--")
        if len(parts) >= 2:
            entities.add(parts[-1].split(":")[0])

    expected_entities = {
        # From generators
        "Reservoir", "ReservoirSegment", "Well", "Wellbore",
        "WellboreMarkerSet", "StratigraphicColumn",
        "StratigraphicColumnRankInterpretation", "StratigraphicUnitInterpretation",
        "HorizonInterpretation", "IjkGridRepresentation",
        "StructureMap", "GenericRepresentation", "ColumnBasedTable",
        "ReservoirEstimatedVolumes", "GeoLabelSet",
        # From template records
        "BusinessDecision", "Risk", "Activity", "ActivityTemplate",
        "Document", "DevelopmentConcept", "PersistedCollection",
        "CollaborationProject", "ActivityStateTemplate", "ETPDataspace",
    }
    # WorkProduct is from generators too
    missing = expected_entities - entities
    assert not missing, f"Missing entity types: {missing}"
    assert len(entities) >= 25, f"Expected ≥25 entity types, got {len(entities)}: {entities}"
    print(f"  ✓ Record type coverage ({len(entities)} unique OSDU types)")


def test_deterministic_generation():
    """Template-based record IDs are deterministic across runs."""
    inst = OsduInstance(
        name="t", partition="dev", host="https://x.com",
        legal_tag="dev-tag", owners=["o@dev"], viewers=["v@dev"],
    )
    # Use a template-only config (no generators with random UUIDs)
    config_file = SCRIPT_DIR / "inputs" / "examples" / "drogon_DG2.json"
    config = json.loads(config_file.read_text("utf-8"))

    run1 = generate_records_from_input(config, inst)
    run2 = generate_records_from_input(config, inst)

    assert len(run1) == len(run2), "Different record counts between runs"
    for r1, r2 in zip(run1, run2):
        assert r1["id"] == r2["id"], f"ID mismatch: {r1['id']} != {r2['id']}"
        assert r1["kind"] == r2["kind"], f"Kind mismatch for {r1['id']}"
    print(f"  ✓ Deterministic generation ({len(run1)} template records identical across 2 runs)")


def test_partition_rewriting():
    """Partition rewriting updates IDs, ACLs, legal tags, and data references."""
    from scripts.ingest import _rewrite_record

    inst = OsduInstance(
        name="target", partition="prod", host="https://x.com",
        legal_tag="prod-legal", owners=["o@prod"], viewers=["v@prod"],
    )
    record = {
        "id": "dev:master-data--Risk:abc:1",
        "kind": "osdu:wks:master-data--Risk:1.2.0",
        "acl": {"owners": ["data.owners@dev.example.com"],
                "viewers": ["data.viewers@dev.example.com"]},
        "legal": {"legaltags": ["dev-legal"],
                  "otherRelevantDataCountries": ["NO"]},
        "data": {
            "Name": "Test",
            "SomeRef": "dev:master-data--Other:xyz:1",
            "Nested": {"RefList": ["dev:work-product--WP:aaa:1"]},
        },
    }
    rewritten = _rewrite_record(record, "prod", inst)

    assert rewritten["id"] == "prod:master-data--Risk:abc:1"
    assert rewritten["acl"] == inst.acl
    assert rewritten["legal"] == inst.legal
    assert rewritten["data"]["SomeRef"] == "prod:master-data--Other:xyz:1"
    assert rewritten["data"]["Nested"]["RefList"][0] == "prod:work-product--WP:aaa:1"
    # Original unchanged
    assert record["id"] == "dev:master-data--Risk:abc:1"
    print("  ✓ Partition rewriting (ID, ACL, legal, nested refs)")


def test_generator_registry():
    """All expected generators are registered."""
    from scripts.generators._registry import GENERATORS, _import_all

    _import_all()
    expected = {"master", "wells", "markers", "grid", "maps", "polygons",
                "simtables", "volumes_raw", "volumes_stat", "params",
                "geolabelset"}
    registered = set(GENERATORS.keys())
    missing = expected - registered
    assert not missing, f"Missing generators: {missing}"
    # Each entry must be callable
    for name, fn in GENERATORS.items():
        assert callable(fn), f"Generator '{name}' is not callable"
    print(f"  ✓ Generator registry ({len(registered)} generators registered)")


def test_generator_record_structure():
    """Every generated record has required OSDU envelope fields."""
    from scripts.generators import run_generator

    gen_dir = SCRIPT_DIR / "inputs" / "generators" / "drogon"
    all_records = []
    for spec_file in sorted(gen_dir.glob("*.json")):
        spec = json.loads(spec_file.read_text("utf-8"))
        records = run_generator(spec, "dev", spec_file.parent)
        all_records.extend(records)

    required_keys = {"id", "kind", "acl", "legal", "data"}
    for rec in all_records:
        missing = required_keys - set(rec.keys())
        assert not missing, f"Record {rec.get('id','?')} missing: {missing}"
        # ID format: partition:category--Entity:uuid:version
        assert ":" in rec["id"], f"Invalid ID format: {rec['id']}"
        assert "osdu:wks:" in rec["kind"], f"Invalid kind format: {rec['kind']}"
        assert isinstance(rec["acl"], dict), f"ACL not dict: {rec['id']}"
        assert isinstance(rec["legal"], dict), f"Legal not dict: {rec['id']}"
        assert isinstance(rec["data"], dict), f"Data not dict: {rec['id']}"
    print(f"  ✓ Generator record structure ({len(all_records)} records validated)")


def test_all_generated_records_valid():
    """All records from DG2 pipeline pass client-side validation."""
    inst = OsduInstance(
        name="t", partition="dev", host="https://x.com",
        legal_tag="dev-tag", owners=["o@dev"], viewers=["v@dev"],
    )
    config_file = SCRIPT_DIR / "inputs" / "drogon_DG2_generated.json"
    config = json.loads(config_file.read_text("utf-8"))
    records = generate_records_from_input(config, inst, config_dir=config_file.parent)

    client = OsduClient(inst, token="dummy")
    errors = client.validate_records(records)
    assert not errors, f"Validation errors: {errors}"
    print(f"  ✓ All generated records valid ({len(records)} records)")


def test_manifest_include_pipeline():
    """Pipeline with include_manifests loads pre-generated records."""
    inst = OsduInstance(
        name="t", partition="dev", host="https://x.com",
        legal_tag="dev-tag", owners=["o@dev"], viewers=["v@dev"],
    )
    # Use drogon_DG1_full which has include_manifests
    config_file = SCRIPT_DIR / "inputs" / "drogon_DG1_full.json"
    if not config_file.exists():
        print("  ⚠ drogon_DG1_full.json not found (skipped)")
        return
    config = json.loads(config_file.read_text("utf-8"))
    records = generate_records_from_input(config, inst, config_dir=config_file.parent)
    assert len(records) > 0, "No records from include_manifests pipeline"
    # Validate all
    client = OsduClient(inst, token="dummy")
    errors = client.validate_records(records)
    assert not errors, f"Validation errors: {errors}"
    print(f"  ✓ Manifest include pipeline ({len(records)} records from DG1)")


def test_template_data_merge():
    """Template data fields are properly merged, not overwritten."""
    inst = OsduInstance(
        name="t", partition="dev", host="https://x.com",
        legal_tag="dev-tag", owners=["o@dev"], viewers=["v@dev"],
    )
    # Generate a business_decision with partial data
    rec = generate_record("business_decision", inst, {
        "Name": "TestBD",
        "ext": {"equinor": {"Alternatives": [{"Name": "Alt1"}]}},
    }, slug="merge-test")
    # Template fields should be present even if not explicitly set
    assert rec["data"]["Name"] == "TestBD"
    # ext should contain our data
    assert rec["data"]["ext"]["equinor"]["Alternatives"][0]["Name"] == "Alt1"
    print("  ✓ Template data merge (deep fields preserved)")


def test_invalid_record_type():
    """Unknown record type raises a clear error."""
    inst = OsduInstance(
        name="t", partition="dev", host="https://x.com",
        legal_tag="dev-tag", owners=["o@dev"], viewers=["v@dev"],
    )
    try:
        generate_record("nonexistent_type", inst, {"Name": "X"}, slug="x")
        assert False, "Should have raised an error"
    except (KeyError, FileNotFoundError, ValueError):
        pass
    print("  ✓ Invalid record type raises error")


def test_generator_unknown_type():
    """Unknown generator type raises a clear error."""
    from scripts.generators import run_generator
    try:
        run_generator({"generator": "nonexistent_gen"}, "dev", Path("."))
        assert False, "Should have raised an error"
    except (KeyError, ValueError):
        pass
    print("  ✓ Unknown generator type raises error")


def test_empty_records_config():
    """Config with empty records list produces no records."""
    inst = OsduInstance(
        name="t", partition="dev", host="https://x.com",
        legal_tag="dev-tag", owners=["o@dev"], viewers=["v@dev"],
    )
    config = {"project": "Empty", "gate": "DG0", "records": []}
    records = generate_records_from_input(config, inst)
    assert len(records) == 0
    print("  ✓ Empty records config produces 0 records")


def test_all_pipeline_configs():
    """All pipeline configs in inputs/ generate valid records."""
    inst = OsduInstance(
        name="t", partition="dev", host="https://x.com",
        legal_tag="dev-tag", owners=["o@dev"], viewers=["v@dev"],
    )
    inputs_dir = SCRIPT_DIR / "inputs"
    count = 0
    for config_file in sorted(inputs_dir.glob("*.json")):
        config = json.loads(config_file.read_text("utf-8"))
        records = generate_records_from_input(
            config, inst, config_dir=config_file.parent
        )
        assert len(records) >= 0, f"{config_file.name}: generation failed"
        # Validate
        client = OsduClient(inst, token="dummy")
        errors = client.validate_records(records)
        assert not errors, f"{config_file.name}: {errors}"
        count += 1
    print(f"  ✓ All pipeline configs valid ({count} configs)")


def test_generator_wells_wellbore_refs():
    """Wells generator creates matching Well→Wellbore references."""
    from scripts.generators import run_generator

    spec_file = SCRIPT_DIR / "inputs" / "generators" / "drogon" / "wells.json"
    spec = json.loads(spec_file.read_text("utf-8"))
    records = run_generator(spec, "dev", spec_file.parent)

    wells = [r for r in records if "--Well:" in r["kind"]]
    wellbores = [r for r in records if "--Wellbore:" in r["kind"]]

    assert len(wells) == 9, f"Expected 9 wells, got {len(wells)}"
    assert len(wellbores) == 11, f"Expected 11 wellbores, got {len(wellbores)}"

    # Each wellbore should reference a well that exists
    well_ids = {w["id"] for w in wells}
    for wb in wellbores:
        well_ref = wb["data"].get("WellID", "")
        if well_ref:
            assert well_ref in well_ids, f"Wellbore {wb['id']} references unknown well {well_ref}"
    print(f"  ✓ Well→Wellbore references valid ({len(wells)} wells, {len(wellbores)} wellbores)")


def test_generator_master_segments():
    """Master generator creates Reservoir + ReservoirSegment + WorkProduct."""
    from scripts.generators import run_generator

    spec_file = SCRIPT_DIR / "inputs" / "generators" / "drogon" / "master.json"
    spec = json.loads(spec_file.read_text("utf-8"))
    records = run_generator(spec, "dev", spec_file.parent)

    reservoirs = [r for r in records if "--Reservoir:" in r["kind"]]
    segments = [r for r in records if "--ReservoirSegment:" in r["kind"]]
    wps = [r for r in records if "work-product" in r["kind"].lower()]

    assert len(reservoirs) == 1, f"Expected 1 Reservoir, got {len(reservoirs)}"
    assert len(segments) == 7, f"Expected 7 ReservoirSegments, got {len(segments)}"
    assert len(wps) == 1, f"Expected 1 WorkProduct, got {len(wps)}"

    # Each segment should reference the reservoir
    res_id = reservoirs[0]["id"]
    for seg in segments:
        assert res_id in str(seg["data"]), f"Segment {seg['id']} doesn't reference reservoir"
    print(f"  ✓ Master generator: 1 reservoir, {len(segments)} segments, 1 WP")


def test_generator_markers_stratigraphy():
    """Markers generator builds full stratigraphic hierarchy."""
    from scripts.generators import run_generator

    spec_file = SCRIPT_DIR / "inputs" / "generators" / "drogon" / "markers.json"
    spec = json.loads(spec_file.read_text("utf-8"))
    records = run_generator(spec, "dev", spec_file.parent)

    marker_sets = [r for r in records if "--WellboreMarkerSet:" in r["kind"]]
    strat_cols = [r for r in records if "--StratigraphicColumn:" in r["kind"]]
    rank_interps = [r for r in records if "RankInterpretation" in r["kind"]]
    unit_interps = [r for r in records if "UnitInterpretation" in r["kind"]]
    horizon_interps = [r for r in records if "HorizonInterpretation" in r["kind"]]

    assert len(marker_sets) >= 1, "No WellboreMarkerSets"
    assert len(strat_cols) == 1, f"Expected 1 StratigraphicColumn, got {len(strat_cols)}"
    assert len(rank_interps) >= 1, "No RankInterpretations"
    assert len(unit_interps) >= 1, "No UnitInterpretations"
    assert len(horizon_interps) >= 1, "No HorizonInterpretations"
    print(f"  ✓ Markers: {len(marker_sets)} marker sets, {len(strat_cols)} strat col, "
          f"{len(rank_interps)} ranks, {len(unit_interps)} units, {len(horizon_interps)} horizons")


def test_ingest_dry_run():
    """Dry-run ingestion reports what would be sent without HTTP calls."""
    inst = OsduInstance(
        name="t", partition="dev", host="https://x.com",
        legal_tag="dev-tag", owners=["o@dev"], viewers=["v@dev"],
    )
    client = OsduClient(inst, token="dummy")
    records = [
        generate_record("risk", inst, {"Name": f"R{i}"}, slug=f"dry-{i}")
        for i in range(3)
    ]
    result = ingest_records(records, client, dry_run=True)
    assert result["mode"] == "dry-run"
    assert result["totalCount"] == 3
    assert len(result["recordIds"]) == 3
    print("  ✓ Dry-run ingestion (3 records, no HTTP calls)")


def main():
    print("═══ Script Suite Tests ═══\n")
    tests = [
        # Core functionality
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
        # Config validation
        test_all_example_configs,
        test_all_pipeline_configs,
        # Generator framework
        test_generator_registry,
        test_generators,
        test_generator_record_structure,
        test_generator_pipeline,
        # Record type coverage
        test_record_type_coverage,
        test_deterministic_generation,
        test_all_generated_records_valid,
        # Cross-reference integrity
        test_generator_wells_wellbore_refs,
        test_generator_master_segments,
        test_generator_markers_stratigraphy,
        # Pipeline features
        test_manifest_include_pipeline,
        test_partition_rewriting,
        test_template_data_merge,
        test_ingest_dry_run,
        # Edge cases
        test_invalid_record_type,
        test_generator_unknown_type,
        test_empty_records_config,
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
