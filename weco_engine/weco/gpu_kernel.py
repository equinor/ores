"""
weco.gpu_kernel — GPU cost-matrix fill prototype (§4.4)
=======================================================

CUDA/OpenCL prototype for accelerating cost matrix computation.
Uses CuPy (CUDA) or PyOpenCL as backend, falling back to NumPy.

This is an experimental prototype for benchmarking GPU vs CPU cost
matrix fill performance.

Usage::

    from weco.gpu_kernel import gpu_cost_matrix_fill
    cost_matrix = gpu_cost_matrix_fill(data1, data2, backend="cupy")
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


def _cost_matrix_numpy(
    data1: np.ndarray,
    data2: np.ndarray,
    band_width: int = 0,
) -> np.ndarray:
    """CPU reference: pairwise squared difference cost matrix."""
    n1, n2 = len(data1), len(data2)
    cost = np.full((n1, n2), np.inf, dtype=np.float64)
    for i in range(n1):
        for j in range(n2):
            if band_width > 0:
                rel1 = i / max(n1 - 1, 1)
                rel2 = j / max(n2 - 1, 1)
                if abs(rel1 - rel2) > band_width / max(n1, n2):
                    continue
            cost[i, j] = (data1[i] - data2[j]) ** 2
    return cost


def _cost_matrix_cupy(
    data1: np.ndarray,
    data2: np.ndarray,
    band_width: int = 0,
) -> np.ndarray:
    """CUDA cost matrix via CuPy."""
    try:
        import cupy as cp
    except ImportError:
        raise ImportError("CuPy required for CUDA backend: pip install cupy-cuda12x")

    d1 = cp.asarray(data1, dtype=cp.float64)
    d2 = cp.asarray(data2, dtype=cp.float64)

    # Broadcast: cost[i,j] = (d1[i] - d2[j])^2
    cost = (d1[:, None] - d2[None, :]) ** 2

    # Apply band constraint on GPU
    if band_width > 0:
        n1, n2 = len(data1), len(data2)
        i_idx = cp.arange(n1, dtype=cp.float64)[:, None] / max(n1 - 1, 1)
        j_idx = cp.arange(n2, dtype=cp.float64)[None, :] / max(n2 - 1, 1)
        mask = cp.abs(i_idx - j_idx) > band_width / max(n1, n2)
        cost[mask] = cp.inf

    return cp.asnumpy(cost)


def _cost_matrix_opencl(
    data1: np.ndarray,
    data2: np.ndarray,
    band_width: int = 0,
) -> np.ndarray:
    """OpenCL cost matrix via PyOpenCL."""
    try:
        import pyopencl as cl
        import pyopencl.array as cl_array
    except ImportError:
        raise ImportError("PyOpenCL required: pip install pyopencl")

    ctx = cl.create_some_context(interactive=False)
    queue = cl.CommandQueue(ctx)

    n1, n2 = len(data1), len(data2)
    d1_buf = cl_array.to_device(queue, data1.astype(np.float64))
    d2_buf = cl_array.to_device(queue, data2.astype(np.float64))
    cost_buf = cl_array.empty(queue, (n1, n2), dtype=np.float64)

    kernel_src = """
    __kernel void cost_fill(
        __global const double *d1,
        __global const double *d2,
        __global double *cost,
        int n1, int n2, int band_width)
    {
        int i = get_global_id(0);
        int j = get_global_id(1);
        if (i >= n1 || j >= n2) return;

        if (band_width > 0) {
            double rel1 = (double)i / max(n1 - 1, 1);
            double rel2 = (double)j / max(n2 - 1, 1);
            double bw_frac = (double)band_width / max(n1, n2);
            if (fabs(rel1 - rel2) > bw_frac) {
                cost[i * n2 + j] = INFINITY;
                return;
            }
        }
        double diff = d1[i] - d2[j];
        cost[i * n2 + j] = diff * diff;
    }
    """

    prg = cl.Program(ctx, kernel_src).build()
    prg.cost_fill(
        queue,
        (n1, n2),
        None,
        d1_buf.data,
        d2_buf.data,
        cost_buf.data,
        np.int32(n1),
        np.int32(n2),
        np.int32(band_width),
    )
    queue.finish()

    return cost_buf.get()


_BACKENDS = {
    "numpy": _cost_matrix_numpy,
    "cupy": _cost_matrix_cupy,
    "cuda": _cost_matrix_cupy,
    "opencl": _cost_matrix_opencl,
}


def gpu_cost_matrix_fill(
    data1: np.ndarray,
    data2: np.ndarray,
    band_width: int = 0,
    backend: str = "auto",
) -> np.ndarray:
    """
    Compute pairwise cost matrix, optionally on GPU.

    Parameters
    ----------
    data1 : ndarray, shape (n1,)
        Log values for well 1.
    data2 : ndarray, shape (n2,)
        Log values for well 2.
    band_width : int
        Sakoe-Chiba band (0 = unlimited).
    backend : str
        One of 'auto', 'numpy', 'cupy'/'cuda', 'opencl'.

    Returns
    -------
    ndarray, shape (n1, n2)
        Cost matrix.
    """
    if backend == "auto":
        for name in ("cupy", "opencl", "numpy"):
            try:
                return _BACKENDS[name](data1, data2, band_width)
            except ImportError:
                continue
        return _cost_matrix_numpy(data1, data2, band_width)

    if backend not in _BACKENDS:
        raise ValueError(f"Unknown backend: {backend}. Choose from {list(_BACKENDS)}")

    return _BACKENDS[backend](data1, data2, band_width)
