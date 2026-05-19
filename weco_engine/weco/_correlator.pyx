# cython: boundscheck=False, wraparound=False, cdivision=True
"""
weco._correlator — Cython fallback DTW correlator (§7.2)
=========================================================

A Cython implementation of the n-best graph-DTW correlator for use
when the C++ engine is unavailable.  Provides ~10-50x speedup over
pure Python (without Numba).

Build with::

    cythonize -i weco/_correlator.pyx

Or include in setup.py / pyproject.toml build configuration.
"""

import numpy as np
cimport numpy as np
from libc.math cimport fabs

ctypedef np.float64_t DTYPE_t
ctypedef np.int32_t ITYPE_t

DEF INF = 1e30


def dtw_nbest_cython(
    np.ndarray[ITYPE_t, ndim=1] trans_from,
    np.ndarray[DTYPE_t, ndim=1] trans_cost,
    np.ndarray[ITYPE_t, ndim=1] trans_offset,
    np.ndarray[ITYPE_t, ndim=1] trans_count,
    int size1,
    int size2,
    np.ndarray[DTYPE_t, ndim=2] cost_matrix,
    int max_res,
    int band_width,
):
    """Cython n-best DTW correlator.

    Parameters and return value mirror :func:`weco.correlator_numba._dtw_nbest`.
    """
    cdef int buf_size = size1 * size2
    cdef np.ndarray[DTYPE_t, ndim=2] buf_costs = np.full(
        (buf_size, max_res), INF, dtype=np.float64
    )
    cdef np.ndarray[ITYPE_t, ndim=1] buf_counts = np.zeros(
        buf_size, dtype=np.int32
    )

    cdef int node1, node2, cell_idx, src_idx, count
    cdef int t1, t2, k, s, from1, from2
    cdef int n1_off, n1_cnt, n2_off, n2_cnt
    cdef double dest_cost_val, c, tc1, tc2, rel1, rel2, band_frac
    cdef double tmp

    # Seed
    buf_costs[0, 0] = 0.0
    buf_counts[0] = 1

    for node1 in range(size1):
        for node2 in range(size2):
            if node1 == 0 and node2 == 0:
                continue

            # Band constraint
            if band_width > 0:
                rel1 = <double>node1 / max(size1 - 1, 1)
                rel2 = <double>node2 / max(size2 - 1, 1)
                band_frac = <double>band_width / max(size1, size2)
                if fabs(rel1 - rel2) > band_frac:
                    continue

            cell_idx = node2 * size1 + node1
            dest_cost_val = cost_matrix[node1, node2]
            if dest_cost_val != dest_cost_val:  # NaN check
                continue

            count = 0

            n2_off = trans_offset[size1 + node2]
            n2_cnt = trans_count[size1 + node2]
            n1_off = trans_offset[node1]
            n1_cnt = trans_count[node1]

            # Graph2-only transitions
            for t2 in range(n2_cnt):
                from2 = trans_from[n2_off + t2]
                tc2 = trans_cost[n2_off + t2]
                src_idx = from2 * size1 + node1
                for k in range(buf_counts[src_idx]):
                    c = buf_costs[src_idx, k] + tc2 + dest_cost_val
                    if count < max_res:
                        buf_costs[cell_idx, count] = c
                        count += 1
                    elif c < buf_costs[cell_idx, max_res - 1]:
                        buf_costs[cell_idx, max_res - 1] = c

            # Graph1-only transitions
            for t1 in range(n1_cnt):
                from1 = trans_from[n1_off + t1]
                tc1 = trans_cost[n1_off + t1]
                src_idx = node2 * size1 + from1
                for k in range(buf_counts[src_idx]):
                    c = buf_costs[src_idx, k] + tc1 + dest_cost_val
                    if count < max_res:
                        buf_costs[cell_idx, count] = c
                        count += 1
                    elif c < buf_costs[cell_idx, max_res - 1]:
                        buf_costs[cell_idx, max_res - 1] = c

                # Both transitions
                for t2 in range(n2_cnt):
                    from2 = trans_from[n2_off + t2]
                    tc2 = trans_cost[n2_off + t2]
                    src_idx = from2 * size1 + from1
                    for k in range(buf_counts[src_idx]):
                        c = buf_costs[src_idx, k] + tc1 + tc2 + dest_cost_val
                        if count < max_res:
                            buf_costs[cell_idx, count] = c
                            count += 1
                        elif c < buf_costs[cell_idx, max_res - 1]:
                            buf_costs[cell_idx, max_res - 1] = c

            # Sort
            buf_counts[cell_idx] = min(count, max_res)
            for i in range(buf_counts[cell_idx]):
                for j in range(i + 1, buf_counts[cell_idx]):
                    if buf_costs[cell_idx, j] < buf_costs[cell_idx, i]:
                        tmp = buf_costs[cell_idx, i]
                        buf_costs[cell_idx, i] = buf_costs[cell_idx, j]
                        buf_costs[cell_idx, j] = tmp

    # Results
    cdef int final_idx = (size2 - 1) * size1 + (size1 - 1)
    cdef int n_results = buf_counts[final_idx]
    return np.array(buf_costs[final_idx, :n_results], dtype=np.float64)
