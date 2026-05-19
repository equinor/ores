"""
Tests for weco.utils — MeanAccumulator + MinMax
"""

import pytest
from weco.utils import MeanAccumulator, MinMax


# ═══════════════════════════════════════════════════════════════════════════
#  MeanAccumulator
# ═══════════════════════════════════════════════════════════════════════════


class TestMeanAccumulator:
    """Tests for MeanAccumulator."""

    def test_empty(self):
        m = MeanAccumulator()
        assert m.mean() == 0.0

    def test_single_value(self):
        m = MeanAccumulator()
        m.add(5.0)
        assert m.mean() == 5.0

    def test_multiple_adds(self):
        m = MeanAccumulator()
        m.add(2.0)
        m.add(4.0)
        m.add(6.0)
        assert m.mean() == pytest.approx(4.0)

    def test_constructor_values(self):
        m = MeanAccumulator(1.0, 2.0, 3.0)
        assert m.mean() == pytest.approx(2.0)

    def test_add_varargs(self):
        m = MeanAccumulator()
        m.add(10.0, 20.0, 30.0)
        assert m.mean() == pytest.approx(20.0)

    def test_add_empty(self):
        m = MeanAccumulator(5.0)
        m.add()  # no-op
        assert m.mean() == 5.0

    def test_negative_values(self):
        m = MeanAccumulator(-3.0, 3.0)
        assert m.mean() == pytest.approx(0.0)

    def test_large_number_of_values(self):
        m = MeanAccumulator()
        for i in range(1000):
            m.add(float(i))
        assert m.mean() == pytest.approx(499.5)

    def test_zero_values(self):
        m = MeanAccumulator(0.0, 0.0, 0.0)
        assert m.mean() == 0.0

    def test_incremental_consistency(self):
        """Incremental adds match single batch."""
        m1 = MeanAccumulator(1, 2, 3, 4, 5)
        m2 = MeanAccumulator()
        for v in [1, 2, 3, 4, 5]:
            m2.add(v)
        assert m1.mean() == pytest.approx(m2.mean())


# ═══════════════════════════════════════════════════════════════════════════
#  MinMax
# ═══════════════════════════════════════════════════════════════════════════


class TestMinMax:
    """Tests for MinMax."""

    def test_empty(self):
        mm = MinMax()
        assert mm.min() is None
        assert mm.max() is None
        assert mm.range() == (None, None)

    def test_single_value(self):
        mm = MinMax()
        mm(5.0)
        assert mm.min() == 5.0
        assert mm.max() == 5.0

    def test_ascending(self):
        mm = MinMax()
        for v in [1, 2, 3, 4, 5]:
            mm(v)
        assert mm.min() == 1
        assert mm.max() == 5

    def test_descending(self):
        mm = MinMax()
        for v in [5, 4, 3, 2, 1]:
            mm(v)
        assert mm.min() == 1
        assert mm.max() == 5

    def test_random_order(self):
        mm = MinMax()
        for v in [3, 1, 4, 1, 5, 9, 2, 6]:
            mm(v)
        assert mm.min() == 1
        assert mm.max() == 9

    def test_negative_values(self):
        mm = MinMax()
        for v in [-5, -3, -7, -1]:
            mm(v)
        assert mm.min() == -7
        assert mm.max() == -1

    def test_all_same(self):
        mm = MinMax()
        for _ in range(10):
            mm(42)
        assert mm.min() == 42
        assert mm.max() == 42

    def test_range(self):
        mm = MinMax()
        for v in [10, 20, 30]:
            mm(v)
        assert mm.range() == (10, 30)

    def test_floats(self):
        mm = MinMax()
        mm(1.5)
        mm(2.7)
        mm(0.3)
        assert mm.min() == pytest.approx(0.3)
        assert mm.max() == pytest.approx(2.7)

    def test_min_update_after_max(self):
        """Regression: ensure updating min works after max has been set."""
        mm = MinMax()
        mm(5)   # sets both min and max
        mm(10)  # updates max
        mm(1)   # updates min — this was the bug (self._mix typo)
        assert mm.min() == 1
        assert mm.max() == 10
