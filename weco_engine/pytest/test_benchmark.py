"""Performance benchmark for /auto pipeline (R1).

Run with: pytest pytest/test_benchmark.py -v --tb=short
Prints timing per demo dataset. Not meant to fail - just records times.
"""

import time
import pytest
from pathlib import Path

DEMO_DIR = Path(__file__).parent.parent / "demo" / "data"


def _get_demo_paths():
    from weco.data import WellList
    paths = []
    for p in sorted(DEMO_DIR.glob("*/wells.txt")):
        try:
            wl = WellList()
            wl.read(str(p))
            if len(wl.wells) <= 10:
                paths.append(p)
        except Exception:
            pass
    return paths


@pytest.mark.parametrize("wells_path", _get_demo_paths(),
                         ids=lambda p: p.parent.name)
def test_auto_pipeline_timing(wells_path, capsys):
    """Time the full auto-correlate pipeline for each demo dataset."""
    from weco.data import WellList
    from weco.api import (_suggest_defaults_for_wells, _run_engine,
                          _extract_results, _diverse_results)

    wl = WellList()
    wl.read(str(wells_path))
    n_wells = len(wl.wells)

    t0 = time.perf_counter()
    options, _ = _suggest_defaults_for_wells(wl)
    t_suggest = time.perf_counter() - t0

    options["nbr-cor"] = 50
    options["out-nbr-cor"] = 10
    options["max-cor"] = 80

    t1 = time.perf_counter()
    rf, data, engine_ms = _run_engine(wl, options)
    t_engine = time.perf_counter() - t1

    t2 = time.perf_counter()
    results = _extract_results(rf, data, 20)
    diverse_idx = _diverse_results(rf, data, n_best=20, n_diverse=3)
    t_post = time.perf_counter() - t2

    total_ms = (time.perf_counter() - t0) * 1000

    with capsys.disabled():
        print(f"\n  {wells_path.parent.name}: {n_wells} wells | "
              f"suggest={t_suggest*1000:.0f}ms engine={t_engine*1000:.0f}ms "
              f"post={t_post*1000:.0f}ms total={total_ms:.0f}ms | "
              f"{len(results)} results, {len(diverse_idx)} diverse")

    # Soft warning: CI runners (especially Windows) are much slower than local
    if total_ms > 120000:
        pytest.fail(f"Pipeline extremely slow: {total_ms:.0f}ms (>120s)")
    elif total_ms > 30000:
        import warnings
        warnings.warn(f"Pipeline slow: {total_ms:.0f}ms (>30s, expected on Windows CI)")
