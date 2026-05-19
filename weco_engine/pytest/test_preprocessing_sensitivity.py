"""
Tests for weco.preprocessing facies clustering and weco.sensitivity well order.
==============================================================================

Covers:
- parse_facies_groups() — string spec → mapping dict (§13.2)
- remap_facies_groups() — well region remapping + merging (§13.2)
- configure_well_order() — engine order key + Python-side strategies (§13.3)
- ALL_ORDER_KEYS / BUILTIN_ORDER_KEYS / EXTENDED_ORDER_KEYS constants
"""

import os
import pytest
import numpy as np

from weco.data import Well, WellList
from weco.preprocessing import parse_facies_groups, remap_facies_groups
from weco.sensitivity import (
    configure_well_order,
    ALL_ORDER_KEYS,
    BUILTIN_ORDER_KEYS,
    EXTENDED_ORDER_KEYS,
)

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "demo", "data")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_well(name, size=20, seed=0, x=0.0, y=0.0, facies_ids=None):
    """Create a Well with data and facies region."""
    rng = np.random.RandomState(seed)
    w = Well()
    w.name = name
    w.size = size
    w.x = x
    w.y = y
    w.z = 0.0
    w.h = float(size) * 10.0
    w.data["GR"] = list(rng.uniform(20, 120, size))
    # Facies region: cycling through IDs
    if facies_ids is None:
        facies_ids = [1, 2, 3, 4, 5]
    cycle = [facies_ids[i % len(facies_ids)] for i in range(size)]
    w.data["Facies"] = [float(f) for f in cycle]
    w.add_region_from_data("Facies")
    return w


def _make_well_list(n=4, size=20):
    """Create a WellList with n wells spread spatially."""
    wl = WellList.__new__(WellList)
    wl.wells = [
        _make_well(f"W{i+1}", size=size, seed=i,
                   x=float(i * 300), y=float(i * 100))
        for i in range(n)
    ]
    return wl


# ===================================================================
# §13.2 — Facies clustering (parse_facies_groups)
# ===================================================================

class TestParseFaciesGroups:

    def test_basic_three_groups(self):
        m = parse_facies_groups("1,2,3;4,5;6,7,8")
        assert m == {1: 1, 2: 1, 3: 1, 4: 2, 5: 2, 6: 3, 7: 3, 8: 3}

    def test_single_group(self):
        m = parse_facies_groups("10,20,30")
        assert m == {10: 1, 20: 1, 30: 1}

    def test_single_element_groups(self):
        m = parse_facies_groups("1;2;3")
        assert m == {1: 1, 2: 2, 3: 3}

    def test_whitespace_handling(self):
        m = parse_facies_groups(" 1 , 2 ; 3 , 4 ")
        assert m == {1: 1, 2: 1, 3: 2, 4: 2}

    def test_empty_string(self):
        m = parse_facies_groups("")
        assert m == {}

    def test_group_indices_start_at_1(self):
        m = parse_facies_groups("5;10;15")
        assert m[5] == 1
        assert m[10] == 2
        assert m[15] == 3

    def test_large_facies_ids(self):
        m = parse_facies_groups("100,200;300,400")
        assert m == {100: 1, 200: 1, 300: 2, 400: 2}

    def test_trailing_semicolon_ignored(self):
        m = parse_facies_groups("1,2;3,4;")
        # Trailing empty group is ignored because tok.strip() is empty
        assert m == {1: 1, 2: 1, 3: 2, 4: 2}


# ===================================================================
# §13.2 — Facies clustering (remap_facies_groups)
# ===================================================================

class TestRemapFaciesGroups:

    def test_basic_remap(self):
        wl = _make_well_list(2, size=10)
        ok = remap_facies_groups(wl, "Facies", "1,2,3;4,5", "FACIES_GRP")
        assert ok is True
        for w in wl.wells:
            assert "FACIES_GRP" in w.region
            # All group IDs should be 1 or 2
            for (gid, start, length) in w.region["FACIES_GRP"]:
                assert gid in (1, 2)

    def test_merging_consecutive(self):
        """Consecutive facies in same group should merge into one region."""
        w = Well()
        w.name = "MergeTest"
        w.size = 6
        w.x = w.y = w.z = 0.0
        w.h = 60.0
        # Facies: 1,2,1,3,3,2 — groups: {1:1, 2:1, 3:2}
        w.data["F"] = [1.0, 2.0, 1.0, 3.0, 3.0, 2.0]
        w.add_region_from_data("F")

        wl = WellList.__new__(WellList)
        wl.wells = [w]

        ok = remap_facies_groups(wl, "F", "1,2;3", "FG")
        assert ok is True

        regions = w.region["FG"]
        # Original: (1,0,1),(2,1,1),(1,2,1),(3,3,1),(3,4,1),(2,5,1)
        # After mapping: (1,0,1),(1,1,1),(1,2,1),(2,3,1),(2,4,1),(1,5,1)
        # After merge:   (1,0,3),(2,3,2),(1,5,1)
        assert len(regions) == 3
        assert regions[0] == (1, 0, 3)
        assert regions[1] == (2, 3, 2)
        assert regions[2] == (1, 5, 1)

    def test_empty_groups_string(self):
        wl = _make_well_list(1)
        ok = remap_facies_groups(wl, "Facies", "", "FG")
        assert ok is False

    def test_empty_dict(self):
        wl = _make_well_list(1)
        ok = remap_facies_groups(wl, "Facies", {}, "FG")
        assert ok is False

    def test_missing_region(self):
        """Wells without the named region are skipped."""
        wl = _make_well_list(1)
        ok = remap_facies_groups(wl, "NONEXISTENT", "1;2;3", "FG")
        assert ok is False

    def test_dict_input(self):
        """Groups can be passed as a pre-parsed dict."""
        wl = _make_well_list(2, size=10)
        mapping = {1: 1, 2: 1, 3: 2, 4: 2, 5: 3}
        ok = remap_facies_groups(wl, "Facies", mapping, "FACIES_DICT")
        assert ok is True
        for w in wl.wells:
            assert "FACIES_DICT" in w.region

    def test_unmapped_facies_keep_original(self):
        """Facies IDs not in the mapping should keep their original ID."""
        w = Well()
        w.name = "Unmapped"
        w.size = 3
        w.x = w.y = w.z = 0.0
        w.h = 30.0
        w.data["F"] = [1.0, 99.0, 2.0]
        w.add_region_from_data("F")

        wl = WellList.__new__(WellList)
        wl.wells = [w]

        ok = remap_facies_groups(wl, "F", "1,2", "FG")
        assert ok is True
        regions = w.region["FG"]
        # 1→1, 99→99 (unmapped), 2→1
        # After mapping: (1,0,1),(99,1,1),(1,2,1) — no merge across 99
        assert len(regions) == 3
        assert regions[1][0] == 99

    def test_fewer_groups_than_original(self):
        """All facies mapped to one group → single merged region."""
        w = Well()
        w.name = "AllSame"
        w.size = 5
        w.x = w.y = w.z = 0.0
        w.h = 50.0
        w.data["F"] = [1.0, 2.0, 3.0, 1.0, 2.0]
        w.add_region_from_data("F")

        wl = WellList.__new__(WellList)
        wl.wells = [w]

        ok = remap_facies_groups(wl, "F", "1,2,3", "FG")
        assert ok is True
        regions = w.region["FG"]
        # All mapped to group 1 → one big region
        assert len(regions) == 1
        assert regions[0] == (1, 0, 5)


# ===================================================================
# §13.3 — Well order control (configure_well_order)
# ===================================================================

class TestWellOrderConstants:

    def test_builtin_keys(self):
        for k in ["pyramidal", "linear", "position", "distality", "inverse"]:
            assert k in BUILTIN_ORDER_KEYS

    def test_extended_keys(self):
        for k in ["proximal_first", "distal_first", "random", "auto"]:
            assert k in EXTENDED_ORDER_KEYS

    def test_all_keys_is_union(self):
        assert ALL_ORDER_KEYS == BUILTIN_ORDER_KEYS + EXTENDED_ORDER_KEYS

    def test_no_duplicates(self):
        assert len(set(ALL_ORDER_KEYS)) == len(ALL_ORDER_KEYS)


class TestConfigureWellOrder:

    def test_builtin_keys_accepted(self):
        """All built-in order keys should be accepted without error."""
        from weco.ext import ProjectExt
        for key in BUILTIN_ORDER_KEYS:
            proj = ProjectExt()
            configure_well_order(proj, key)
            # Should not raise

    def test_auto_maps_to_pyramidal(self):
        from weco.ext import ProjectExt
        proj = ProjectExt()
        configure_well_order(proj, "auto")
        # auto → pyramidal; no error

    def test_random_is_reproducible(self):
        from weco.ext import ProjectExt
        proj = ProjectExt()
        configure_well_order(proj, "random", seed=42)
        # Should not raise

    def test_proximal_first_accepted(self):
        from weco.ext import ProjectExt
        proj = ProjectExt()
        configure_well_order(proj, "proximal_first")

    def test_distal_first_accepted(self):
        from weco.ext import ProjectExt
        proj = ProjectExt()
        configure_well_order(proj, "distal_first")

    def test_unknown_key_raises(self):
        from weco.ext import ProjectExt
        proj = ProjectExt()
        with pytest.raises(ValueError, match="Unknown well order"):
            configure_well_order(proj, "bogus_order")

    def test_case_insensitive(self):
        from weco.ext import ProjectExt
        proj = ProjectExt()
        configure_well_order(proj, "PYRAMIDAL")
        configure_well_order(proj, "Random")
        configure_well_order(proj, "  Distal_First  ")
