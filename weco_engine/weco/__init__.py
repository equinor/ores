"""
WeCo — Well Correlation using Graph-DTW.

§7.3/7.4 — Hybrid C++/Python mode.  The C++ engine is the default and
recommended path.  If the compiled extension is not available (e.g.
missing build, WebAssembly, pure-pip install without compiler), a
warning is emitted and engine-dependent imports will raise ImportError.
"""

_ENGINE_AVAILABLE = True

try:
    from weco import engine as _engine  # noqa: F401
except ImportError:
    _ENGINE_AVAILABLE = False
    import warnings
    warnings.warn(
        "WeCo C++ engine not available — running in pure-Python mode. "
        "Correlation (ProjectExt.run) will not work. "
        "Rebuild with: pip install -e '.[dev]'",
        RuntimeWarning,
        stacklevel=2,
    )


def engine_available() -> bool:
    """Return True if the C++ correlation engine is importable."""
    return _ENGINE_AVAILABLE
