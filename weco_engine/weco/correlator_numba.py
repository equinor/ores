"""
weco.correlator_numba — Numba JIT DTW correlator (§7.1)
========================================================

A pure-Python + Numba implementation of the n-best graph-DTW correlator
for use when the C++ engine is unavailable or for rapid prototyping.

Requires ``numba`` as an optional dependency::

    pip install numba

The algorithm mirrors the C++ ``Correlator::run()`` template:
- Iterate over all (node1, node2) pairs
- Accumulate path costs from transitions
- Keep the top-k paths per cell
"""

from __future__ import annotations

import logging
from typing import List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

try:
    from numba import njit, prange
    HAS_NUMBA = True
except ImportError:
    HAS_NUMBA = False

    def njit(*args, **kwargs):
        def decorator(func):
            return func
        if callable(args[0]) if args else False:
            return args[0]
        return decorator

    prange = range


@njit(cache=True)
def _dtw_nbest(
    trans_from: np.ndarray,
    trans_cost: np.ndarray,
    trans_offset: np.ndarray,
    trans_count: np.ndarray,
    size1: int,
    size2: int,
    cost_matrix: np.ndarray,
    max_res: int,
    band_width: int,
):
    """Core n-best DTW on two CorGraphs represented as flat arrays.

    Parameters
    ----------
    trans_from, trans_cost : 1-D arrays
        Flat transition source-node IDs and costs for graph 1 and 2 interleaved.
    trans_offset, trans_count : 1-D arrays
        Per-node offset into trans_from/trans_cost and count.
    size1, size2 : int
        Number of nodes in each graph.
    cost_matrix : 2-D array of shape (size1, size2)
        Pre-computed destination cost at each (node1, node2) cell.
        Use NaN to signal forbidden cells.
    max_res : int
        Maximum paths to keep per cell.
    band_width : int
        Sakoe-Chiba band width (0 = unlimited).

    Returns
    -------
    best_costs : 1-D array
        Costs of the top-k paths arriving at (size1-1, size2-1).
    """
    INF = 1e30

    # path_buffer[n2 * size1 + n1] stores up to max_res costs
    buf_size = size1 * size2
    # Flatten: buf_costs[cell_idx, k] = cost of k-th best path
    buf_costs = np.full((buf_size, max_res), INF, dtype=np.float64)
    buf_counts = np.zeros(buf_size, dtype=np.int32)

    # Seed: cell (0,0) has one zero-cost path
    buf_costs[0, 0] = 0.0
    buf_counts[0] = 1

    for node1 in range(size1):
        for node2 in range(size2):
            if node1 == 0 and node2 == 0:
                continue

            # Band constraint
            if band_width > 0:
                rel1 = node1 / max(size1 - 1, 1)
                rel2 = node2 / max(size2 - 1, 1)
                band_frac = band_width / max(size1, size2)
                if abs(rel1 - rel2) > band_frac:
                    continue

            cell_idx = node2 * size1 + node1
            dest_cost = cost_matrix[node1, node2]
            if np.isnan(dest_cost):
                continue

            count = 0

            # Transitions from graph2 only (gap in graph1)
            n2_off = trans_offset[size1 + node2]
            n2_cnt = trans_count[size1 + node2]
            for t2 in range(n2_cnt):
                from2 = trans_from[n2_off + t2]
                tc2 = trans_cost[n2_off + t2]
                src_idx = from2 * size1 + node1
                for k in range(buf_counts[src_idx]):
                    c = buf_costs[src_idx, k] + tc2 + dest_cost
                    if count < max_res:
                        buf_costs[cell_idx, count] = c
                        count += 1
                    elif c < buf_costs[cell_idx, max_res - 1]:
                        buf_costs[cell_idx, max_res - 1] = c
                        # Insertion sort
                        for s in range(max_res - 2, -1, -1):
                            if buf_costs[cell_idx, s] > buf_costs[cell_idx, s + 1]:
                                buf_costs[cell_idx, s], buf_costs[cell_idx, s + 1] = (
                                    buf_costs[cell_idx, s + 1],
                                    buf_costs[cell_idx, s],
                                )

            # Transitions from graph1 only (gap in graph2)
            n1_off = trans_offset[node1]
            n1_cnt = trans_count[node1]
            for t1 in range(n1_cnt):
                from1 = trans_from[n1_off + t1]
                tc1 = trans_cost[n1_off + t1]
                src_idx = node2 * size1 + from1
                for k in range(buf_counts[src_idx]):
                    c = buf_costs[src_idx, k] + tc1 + dest_cost
                    if count < max_res:
                        buf_costs[cell_idx, count] = c
                        count += 1
                    elif c < buf_costs[cell_idx, max_res - 1]:
                        buf_costs[cell_idx, max_res - 1] = c
                        for s in range(max_res - 2, -1, -1):
                            if buf_costs[cell_idx, s] > buf_costs[cell_idx, s + 1]:
                                buf_costs[cell_idx, s], buf_costs[cell_idx, s + 1] = (
                                    buf_costs[cell_idx, s + 1],
                                    buf_costs[cell_idx, s],
                                )

                # Both transitions
                for t2 in range(n2_cnt):
                    from2 = trans_from[n2_off + t2]
                    tc2 = trans_cost[n2_off + t2]
                    src_idx = from2 * size1 + from1
                    for k in range(buf_counts[src_idx]):
                        c = buf_costs[src_idx, k] + tc1 + tc2 + dest_cost
                        if count < max_res:
                            buf_costs[cell_idx, count] = c
                            count += 1
                        elif c < buf_costs[cell_idx, max_res - 1]:
                            buf_costs[cell_idx, max_res - 1] = c
                            for s in range(max_res - 2, -1, -1):
                                if buf_costs[cell_idx, s] > buf_costs[cell_idx, s + 1]:
                                    buf_costs[cell_idx, s], buf_costs[cell_idx, s + 1] = (
                                        buf_costs[cell_idx, s + 1],
                                        buf_costs[cell_idx, s],
                                    )

            # Sort and truncate
            if count > max_res:
                count = max_res
            buf_counts[cell_idx] = count
            # Simple sort for small max_res
            for i in range(count):
                for j in range(i + 1, count):
                    if buf_costs[cell_idx, j] < buf_costs[cell_idx, i]:
                        buf_costs[cell_idx, i], buf_costs[cell_idx, j] = (
                            buf_costs[cell_idx, j],
                            buf_costs[cell_idx, i],
                        )

    # Extract results from final cell
    final_idx = (size2 - 1) * size1 + (size1 - 1)
    n_results = buf_counts[final_idx]
    return buf_costs[final_idx, :n_results].copy()


def run_numba_correlator(
    cg1_trans_from: np.ndarray,
    cg1_trans_cost: np.ndarray,
    cg1_trans_offset: np.ndarray,
    cg1_trans_count: np.ndarray,
    cg2_trans_from: np.ndarray,
    cg2_trans_cost: np.ndarray,
    cg2_trans_offset: np.ndarray,
    cg2_trans_count: np.ndarray,
    size1: int,
    size2: int,
    cost_matrix: np.ndarray,
    max_res: int = 50,
    band_width: int = 0,
) -> np.ndarray:
    """Run the Numba JIT n-best DTW correlator.

    Parameters mirror the C++ CorGraph data layout.  See
    :func:`_dtw_nbest` for details.

    Returns
    -------
    ndarray
        Sorted costs of the best paths.
    """
    # Merge transition arrays for both graphs
    trans_from = np.concatenate([cg1_trans_from, cg2_trans_from])
    trans_cost_arr = np.concatenate([cg1_trans_cost, cg2_trans_cost])
    offset2 = cg2_trans_offset + len(cg1_trans_from)
    trans_offset = np.concatenate([cg1_trans_offset, offset2])
    trans_count = np.concatenate([cg1_trans_count, cg2_trans_count])

    return _dtw_nbest(
        trans_from, trans_cost_arr, trans_offset, trans_count,
        size1, size2, cost_matrix, max_res, band_width
    )
