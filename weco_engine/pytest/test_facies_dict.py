"""Tests for weco.facies_dict - FaciesDictionary and lithology detection."""

import pytest
from weco.facies_dict import (
    FaciesDictionary, FaciesEntry, STANDARD_LITHO_PALETTE,
    ZONE_COLORS, _LITHO_CODE_TABLES,
)


class TestFaciesEntry:
    def test_defaults(self):
        e = FaciesEntry(zone_id=1)
        assert e.zone_id == 1
        assert e.color == "#CCCCCC"
        assert e.name == ""

    def test_custom(self):
        e = FaciesEntry(zone_id=5, name="Sand", color="#F5D76E", lithology="sandstone")
        assert e.lithology == "sandstone"


class TestFaciesDictionary:
    def test_get_color_fallback(self):
        fd = FaciesDictionary()
        assert fd.get_color(0) == ZONE_COLORS[0]
        assert fd.get_color(20) == ZONE_COLORS[0]  # wraps

    def test_get_color_with_entry(self):
        fd = FaciesDictionary()
        fd.add(3, name="Limestone", lithology="limestone")
        assert fd.get_color(3) == STANDARD_LITHO_PALETTE["limestone"]

    def test_get_label_fallback(self):
        fd = FaciesDictionary()
        assert fd.get_label(7) == "7"

    def test_get_label_with_entry(self):
        fd = FaciesDictionary()
        fd.add(2, name="Shale")
        assert fd.get_label(2) == "Shale"

    def test_add_auto_color_from_lithology(self):
        fd = FaciesDictionary()
        fd.add(1, lithology="coal")
        assert fd.get_color(1) == STANDARD_LITHO_PALETTE["coal"]

    def test_add_explicit_color(self):
        fd = FaciesDictionary()
        fd.add(1, color="#FF0000")
        assert fd.get_color(1) == "#FF0000"

    def test_from_zone_ids(self):
        fd = FaciesDictionary.from_zone_ids([1, 3, 5, 3, 1])
        assert set(fd.entries.keys()) == {1, 3, 5}

    def test_from_region_data(self):
        class MockWell:
            pass
        w = MockWell()
        w.region = {"LITH": [(0, 0, 10), (1, 10, 5), (2, 15, 8)]}
        fd = FaciesDictionary.from_region_data("LITH", [w])
        assert 0 in fd.entries
        assert 1 in fd.entries
        assert 2 in fd.entries

    def test_from_region_auto_binary(self):
        class MockWell:
            pass
        w = MockWell()
        w.region = {"FACIES": [(0, 0, 20), (1, 20, 30)]}
        fd = FaciesDictionary.from_region_auto("FACIES", [w])
        assert 0 in fd.entries
        assert 1 in fd.entries
        # Binary matches the "binary" code table
        assert fd.entries[0].lithology == "shale"
        assert fd.entries[1].lithology == "sandstone"

    def test_from_region_auto_npd_codes(self):
        class MockWell:
            pass
        w = MockWell()
        # NPD codes 1-5
        w.region = {"LITH": [(1, 0, 10), (2, 10, 10), (3, 20, 10),
                             (4, 30, 10), (5, 40, 10)]}
        fd = FaciesDictionary.from_region_auto("LITH", [w])
        assert fd.entries[1].lithology == "sandstone"
        assert fd.entries[2].lithology == "shale"
        assert fd.entries[3].lithology == "limestone"

    def test_from_region_auto_seam_hint(self):
        class MockWell:
            pass
        w = MockWell()
        w.region = {"SEAM": [(0, 0, 20), (1, 20, 5)]}
        fd = FaciesDictionary.from_region_auto("SEAM", [w])
        assert fd.entries[0].lithology == "shale"
        assert fd.entries[1].lithology == "coal"

    def test_from_region_auto_no_match(self):
        class MockWell:
            pass
        w = MockWell()
        # Zone IDs 100-103 don't match any table
        w.region = {"CUSTOM": [(100, 0, 10), (101, 10, 10), (102, 20, 10), (103, 30, 10)]}
        fd = FaciesDictionary.from_region_auto("CUSTOM", [w])
        # Should fall back to default colours
        assert 100 in fd.entries
        assert fd.entries[100].lithology == ""

    def test_from_osdu_units(self):
        records = [
            {"data": {"Code": 1, "Name": "Draupne Fm", "LithologyType": "shale",
                      "ColorCode": "#808080"}},
            {"data": {"Code": 2, "Name": "Hugin Fm", "LithologyType": "sandstone",
                      "ColorCode": "#F5D76E"}},
        ]
        fd = FaciesDictionary.from_osdu_units(records, region_name="FORMATION")
        assert fd.region_name == "FORMATION"
        assert fd.entries[1].name == "Draupne Fm"
        assert fd.entries[2].lithology == "sandstone"
        assert fd.entries[2].color == "#F5D76E"

    def test_from_osdu_units_empty(self):
        fd = FaciesDictionary.from_osdu_units([])
        assert len(fd.entries) == 0


class TestPalettes:
    def test_standard_palette_all_hex(self):
        for name, color in STANDARD_LITHO_PALETTE.items():
            assert color.startswith("#"), f"{name} has invalid color {color}"
            assert len(color) == 7, f"{name} color {color} not 7 chars"

    def test_zone_colors_count(self):
        assert len(ZONE_COLORS) == 20

    def test_litho_code_tables_keys(self):
        assert "npd" in _LITHO_CODE_TABLES
        assert "cgd" in _LITHO_CODE_TABLES
        assert "simple" in _LITHO_CODE_TABLES
        assert "binary" in _LITHO_CODE_TABLES
