"""
weco.formats.dlis_reader — DLIS reader stub
=============================================

Read DLIS (Digital Log Interchange Standard) files.  This is a stub
that delegates to the ``dlisio`` library if available.

DLIS is a binary format used for well log data, more complex than LAS.
It supports multiple frames, multiple log sets, and rich metadata.

Todo §4.10 — DLIS reader (P3)
"""

from __future__ import annotations

from typing import Optional


def read_dlis(filepath: str, frame_index: int = 0) -> "WellList":
    """Read a DLIS file and convert to WeCo WellList.

    Requires the ``dlisio`` package (``pip install dlisio``).

    Parameters
    ----------
    filepath : str
        Path to DLIS file.
    frame_index : int
        Which frame to read (DLIS files can contain multiple frames).

    Returns
    -------
    WellList
        Converted well data.

    Raises
    ------
    ImportError
        If dlisio is not installed.
    """
    try:
        import dlisio
    except ImportError:
        raise ImportError(
            "dlisio is required for DLIS support. "
            "Install with: pip install dlisio"
        )

    from ..data import WellList
    import numpy as np

    wl = WellList()

    with dlisio.dlis.load(filepath) as (f, *_tail):
        # Get origin for well name
        origins = f.origins
        well_name = "Unknown"
        if origins:
            well_name = getattr(origins[0], "well_name", None) or "Unknown"

        # Get frames
        frames = f.frames
        if not frames:
            return wl

        frame = frames[min(frame_index, len(frames) - 1)]
        channels = frame.channels

        if not channels:
            return wl

        # Read curves
        curves = frame.curves()
        depth_name = frame.index
        n_samples = len(curves[channels[0].name]) if channels else 0

        if n_samples == 0:
            return wl

        w = wl.create_well(well_name, size=n_samples)

        for ch in channels:
            name = ch.name
            data = curves[name]
            if data.ndim == 1:
                w.add_data(name, data.tolist())
            elif data.ndim == 2:
                # Multi-dimensional: add each column separately
                for col in range(data.shape[1]):
                    w.add_data(f"{name}_{col}", data[:, col].tolist())

    return wl


def is_available() -> bool:
    """Check if dlisio is installed."""
    try:
        import dlisio
        return True
    except ImportError:
        return False
