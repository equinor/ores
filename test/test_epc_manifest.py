"""
test_epc_manifest.py – Verify the Drogon EPC → OSDU manifest pipeline
produces complete, well-formed output with all expected cross-references.

Runs entirely offline (no remote calls) using the local EPC file.
"""
import json
import sys
from collections import Counter
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "demo" / "epc"
sys.path.insert(0, str(SCRIPT_DIR))

EPC_FILE = SCRIPT_DIR / "drogon_demo.epc"


@pytest.fixture(scope="module")
def manifest():
    """Build manifest from EPC (fresh, using default opendes config)."""
    from build_full_manifest import parse_epc, build_manifest
    objects = parse_epc(EPC_FILE)
    return build_manifest(objects)


@pytest.fixture(scope="module")
def data(manifest):
    return manifest["Data"]


@pytest.fixture(scope="module")
def all_records(data):
    recs = []
    for section in data.values():
        if isinstance(section, list):
            recs.extend(section)
    return recs


@pytest.fixture(scope="module")
def all_ids(all_records):
    return {r["id"] for r in all_records}


# ═══════════════════════════════════════════════════════════════════════════
# Record counts
# ═══════════════════════════════════════════════════════════════════════════


class TestRecordCounts:
    def test_total_records(self, all_records):
        assert len(all_records) == 145

    def test_datasets(self, data):
        assert len(data["Datasets"]) == 1

    def test_master_data(self, data):
        assert len(data["MasterData"]) == 24

    def test_wpc_count(self, data):
        assert len(data["WorkProductComponents"]) == 120

    def test_kind_breakdown(self, data):
        kinds = Counter(
            r["kind"].split("--")[-1]
            for r in data["WorkProductComponents"]
        )
        assert kinds["GenericProperty:1.2.0"] == 32
        assert kinds["GenericRepresentation:1.2.0"] == 19
        assert kinds["WellboreTrajectory:1.3.0"] == 12
        assert kinds["WellLog:1.2.0"] == 9
        assert kinds["WellboreMarkerSet:1.2.0"] == 9
        assert kinds["StructureMap:1.0.0"] == 7
        assert kinds["HorizonInterpretation:1.2.0"] == 6
        assert kinds["FaultInterpretation:1.3.0"] == 6
        assert kinds["SeismicHorizon:2.1.0"] == 2
        assert kinds["GenericBinGrid:1.0.0"] == 1
        assert kinds["StructuralModel:1.0.0"] == 1
        assert kinds["IjkGridRepresentation:1.1.0"] == 1

    def test_master_data_kinds(self, data):
        kinds = Counter(
            r["kind"].split("--")[-1]
            for r in data["MasterData"]
        )
        assert kinds["LocalBoundaryFeature:1.1.0"] == 12
        assert kinds["Wellbore:1.3.0"] == 12


# ═══════════════════════════════════════════════════════════════════════════
# Cross-reference integrity
# ═══════════════════════════════════════════════════════════════════════════


class TestCrossReferences:
    def test_all_ids_unique(self, all_records):
        ids = [r["id"] for r in all_records]
        assert len(ids) == len(set(ids)), f"Duplicate IDs found"

    def test_interpreted_boundary_feature_refs(self, data, all_ids):
        """HorizonInterpretation/FaultInterpretation → LocalBoundaryFeature."""
        for r in data["WorkProductComponents"]:
            ref = r["data"].get("InterpretedBoundaryFeatureID")
            if ref:
                assert ref in all_ids, f"{r['data']['Name']} refs missing feature: {ref}"

    def test_interpreted_horizon_refs(self, data, all_ids):
        """StructureMap/SeismicHorizon → HorizonInterpretation."""
        for r in data["WorkProductComponents"]:
            ref = r["data"].get("InterpretedHorizonID")
            if ref:
                assert ref in all_ids, f"{r['data']['Name']} refs missing interp: {ref}"

    def test_supporting_rep_refs(self, data, all_ids):
        """GenericProperty → IjkGridRepresentation."""
        for r in data["WorkProductComponents"]:
            ref = r["data"].get("SupportingRepresentationID")
            if ref:
                assert ref in all_ids, f"{r['data']['Name']} refs missing rep: {ref}"

    def test_wellbore_refs(self, data, all_ids):
        """WellboreTrajectory/WellLog/MarkerSet → Wellbore."""
        for r in data["WorkProductComponents"]:
            ref = r["data"].get("WellboreID")
            if ref:
                assert ref in all_ids, f"{r['data']['Name']} refs missing wellbore: {ref}"

    def test_bingrid_refs(self, data, all_ids):
        """StructureMap/SeismicHorizon → GenericBinGrid."""
        for r in data["WorkProductComponents"]:
            ref = r["data"].get("BinGridID")
            if ref:
                assert ref in all_ids, f"{r['data']['Name']} refs missing bingrid: {ref}"

    def test_crs_refs(self, data, all_ids):
        """Representations → LocalModelCompoundCrs."""
        for r in data["WorkProductComponents"]:
            ref = r["data"].get("CoordinateReferenceSystemID")
            if ref:
                assert ref in all_ids, f"{r['data']['Name']} refs missing CRS: {ref}"

    def test_dataset_refs(self, data, all_ids):
        """All WPCs → ETPDataspace dataset."""
        ds_id = data["Datasets"][0]["id"]
        for r in data["WorkProductComponents"]:
            dataset_ids = r["data"].get("DatasetIDs", [])
            if dataset_ids:
                assert ds_id in dataset_ids, f"{r['data']['Name']} missing dataset ref"

    def test_structural_model_refs(self, data, all_ids):
        """StructuralModel → all faults + horizons."""
        for r in data["WorkProductComponents"]:
            if "StructuralModel" in r["kind"]:
                fault_ids = r["data"].get("FaultInterpretationIDs", [])
                horizon_ids = r["data"].get("HorizonInterpretationIDs", [])
                assert len(fault_ids) == 6
                assert len(horizon_ids) == 6
                for fid in fault_ids:
                    assert fid in all_ids, f"StructuralModel refs missing fault: {fid}"
                for hid in horizon_ids:
                    assert hid in all_ids, f"StructuralModel refs missing horizon: {hid}"


# ═══════════════════════════════════════════════════════════════════════════
# Domain & metadata quality
# ═══════════════════════════════════════════════════════════════════════════


class TestMetadataQuality:
    def test_horizon_interp_domain_type(self, data):
        """All HorizonInterpretations have DomainTypeID: Mixed."""
        for r in data["WorkProductComponents"]:
            if "HorizonInterpretation" in r["kind"]:
                assert r["data"].get("DomainTypeID") == "osdu:reference-data--DomainType:Mixed:", \
                    f"{r['data']['Name']} missing DomainTypeID"

    def test_horizon_interp_strat_role(self, data):
        """All HorizonInterpretations have StratigraphicRoleTypeID."""
        for r in data["WorkProductComponents"]:
            if "HorizonInterpretation" in r["kind"]:
                assert r["data"].get("StratigraphicRoleTypeID") == \
                    "osdu:reference-data--StratigraphicRoleType:Chronostratigraphic:", \
                    f"{r['data']['Name']} missing StratigraphicRoleTypeID"

    def test_structure_map_names_specific(self, data):
        """StructureMap names include horizon name in parentheses."""
        for r in data["WorkProductComponents"]:
            if "StructureMap" in r["kind"]:
                name = r["data"]["Name"]
                assert "(" in name and ")" in name, \
                    f"StructureMap name not specific: {name}"

    def test_seismic_horizon_names_specific(self, data):
        """SeismicHorizon names include horizon name."""
        for r in data["WorkProductComponents"]:
            if "SeismicHorizon" in r["kind"]:
                name = r["data"]["Name"]
                assert "(" in name and ")" in name, \
                    f"SeismicHorizon name not specific: {name}"

    def test_welllog_names_specific(self, data):
        """WellLog names include well name."""
        for r in data["WorkProductComponents"]:
            if "WellLog" in r["kind"]:
                name = r["data"]["Name"]
                assert "(" in name and ")" in name, \
                    f"WellLog name not specific: {name}"

    def test_structure_map_has_grid_geometry(self, data):
        """StructureMaps have NodeCount and spacing."""
        for r in data["WorkProductComponents"]:
            if "StructureMap" in r["kind"]:
                d = r["data"]
                assert d.get("NodeCountOnIAxis") == 280, f"{d['Name']} missing NodeCountOnIAxis"
                assert d.get("NodeCountOnJAxis") == 440, f"{d['Name']} missing NodeCountOnJAxis"
                assert d.get("IncrementOnIAxis") == 25.0
                assert d.get("IncrementOnJAxis") == 25.0

    def test_bingrid_geometry(self, data):
        """GenericBinGrid has correct lattice definition."""
        for r in data["WorkProductComponents"]:
            if "BinGrid" in r["kind"]:
                d = r["data"]
                assert d["NodeCountOnIAxis"] == 280
                assert d["NodeCountOnJAxis"] == 440
                assert d["IncrementOnIAxis"] == 25.0
                assert d["IncrementOnJAxis"] == 25.0
                assert d["OriginX"] == 461500.0
                assert d["OriginY"] == 5926500.0

    def test_all_records_have_acl(self, all_records):
        """Every record has ACL with owners and viewers."""
        for r in all_records:
            assert "acl" in r
            assert r["acl"]["owners"]
            assert r["acl"]["viewers"]

    def test_all_records_have_legal(self, all_records):
        """Every record has legal tag."""
        for r in all_records:
            assert "legal" in r
            assert r["legal"]["legaltags"]

    def test_all_wpcs_have_ddms_datasets(self, data):
        """Every WPC (except synthesized BinGrid) has DDMSDatasets URI."""
        for r in data["WorkProductComponents"]:
            if "BinGrid" in r["kind"]:
                continue  # synthesized record, no RDDMS backing object
            ddms = r["data"].get("DDMSDatasets", [])
            assert ddms, f"{r['data']['Name']} missing DDMSDatasets"
            assert ddms[0].startswith("eml://"), f"Bad DDMS URI: {ddms[0]}"


# ═══════════════════════════════════════════════════════════════════════════
# Repartition test
# ═══════════════════════════════════════════════════════════════════════════


class TestRepartition:
    def test_repartition_to_dev(self, manifest):
        """Repartition from opendes to dev changes IDs and dataspace."""
        sys.path.insert(0, str(SCRIPT_DIR.parent))

        # Simulate InstanceConfig for interop
        class FakeCfg:
            partition = "dev"
            dataspace = "maap/drogon"

        from ingest_drogon import _repartition
        m2 = _repartition(json.loads(json.dumps(manifest)), FakeCfg())

        # Check IDs changed
        ds = m2["Data"]["Datasets"][0]
        assert ds["id"].startswith("dev:")
        assert "opendes:" not in ds["id"]

        # Check dataspace changed in DDMSDatasets
        wpc = m2["Data"]["WorkProductComponents"][0]
        ddms = wpc["data"]["DDMSDatasets"][0]
        assert "maap/drogon" in ddms
        assert "demo/drogon" not in ddms

        # Check dataset URI
        assert "maap/drogon" in ds["data"]["DatasetProperties"]["URI"]
