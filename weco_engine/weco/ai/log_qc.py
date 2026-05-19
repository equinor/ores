"""
weco.ai.log_qc — AI-powered log quality control
=================================================

Detect bad-hole intervals, impute missing data, and normalise logs
across wells with different tool suites or mud systems.

Typical usage::

    from weco.ai.log_qc import LogQC

    qc = LogQC()
    for well in well_list.wells:
        qc.detect_washouts(well, caliper_name="CALI")
        qc.impute_missing(well, "DT", predictor_logs=["GR", "RHOB", "RT"])
    qc.normalise_logs(well_list, "GR")
"""

from __future__ import annotations

from typing import List, Optional

import numpy as np


class LogQC:
    """
    Log quality-control toolkit.

    All methods operate on :class:`weco.data.Well` or
    :class:`weco.data.WellList` objects in-place.
    """

    # ------------------------------------------------------------------
    #  Washout detection
    # ------------------------------------------------------------------

    @staticmethod
    def detect_washouts(
        well,
        caliper_name: str = "CALI",
        bit_size: Optional[float] = None,
        threshold_sigma: float = 2.0,
        output_name: str = "QC_weight",
        bad_weight: float = 0.1,
    ) -> np.ndarray:
        """
        Flag intervals where borehole is washed out (caliper >> bit size).

        Washed-out zones produce unreliable log readings — GR reads low,
        density reads low, neutron reads high.

        Parameters
        ----------
        well : Well
        caliper_name : str
            Name of the caliper data channel.
        bit_size : float, optional
            Nominal bit size.  If None, uses mean caliper as proxy.
        threshold_sigma : float
            Caliper values > bit_size + threshold * std are flagged.
        output_name : str
            Quality-weight data channel created on the well (0..1).
        bad_weight : float
            Weight assigned to washed-out markers (0 = suppress, 1 = keep).

        Returns
        -------
        ndarray of bool
            True where washout is detected.
        """
        if caliper_name not in well.data:
            # No caliper — assume everything is OK
            weight = np.ones(well.size)
            well.add_data(output_name, weight.tolist())
            return np.zeros(well.size, dtype=bool)

        cali = np.asarray(well.data[caliper_name], dtype=np.float64)

        if bit_size is None:
            bit_size = np.nanmean(cali)

        sigma = np.nanstd(cali) + 1e-10
        bad = cali > (bit_size + threshold_sigma * sigma)

        weight = np.where(bad, bad_weight, 1.0)
        well.add_data(output_name, weight.tolist())

        return bad

    # ------------------------------------------------------------------
    #  Missing-value imputation
    # ------------------------------------------------------------------

    @staticmethod
    def impute_missing(
        well,
        target_log: str,
        predictor_logs: List[str],
        method: str = "rf",
        nan_sentinel: float = -999.25,
        n_estimators: int = 100,
    ) -> int:
        """
        Fill missing values in *target_log* using other logs as predictors.

        Missing values are identified as NaN or as the LAS null sentinel
        (typically -999.25).

        Parameters
        ----------
        well : Well
        target_log : str
            Data channel with gaps.
        predictor_logs : list of str
            Available logs used as feature columns.
        method : str
            ``"rf"`` — Random Forest (default, robust).
            ``"knn"`` — K-nearest neighbours.
            ``"mean"`` — Simple column mean (no ML, always available).
        nan_sentinel : float
            Value treated as missing (LAS convention).
        n_estimators : int
            Number of trees for RF.

        Returns
        -------
        int
            Number of values imputed.
        """
        if target_log not in well.data:
            return 0
        if not all(p in well.data for p in predictor_logs):
            return 0

        y = np.asarray(well.data[target_log], dtype=np.float64).copy()
        mask = np.isnan(y) | np.isclose(y, nan_sentinel)

        if not mask.any():
            return 0

        X = np.column_stack([
            np.asarray(well.data[p], dtype=np.float64)
            for p in predictor_logs
        ])

        # Also mark predictor-NaN rows as unavailable for training
        valid = ~mask & ~np.any(np.isnan(X) | np.isclose(X, nan_sentinel), axis=1)

        if valid.sum() < 10:
            # Too few training samples — fallback to mean
            y[mask] = np.nanmean(y[~mask])
            well.add_data(target_log, y.tolist())
            return int(mask.sum())

        if method == "knn":
            try:
                from sklearn.neighbors import KNeighborsRegressor
                model = KNeighborsRegressor(n_neighbors=min(5, valid.sum()))
            except ImportError:
                y[mask] = np.nanmean(y[valid])
                well.add_data(target_log, y.tolist())
                return int(mask.sum())
        elif method == "rf":
            try:
                from sklearn.ensemble import RandomForestRegressor
                model = RandomForestRegressor(
                    n_estimators=n_estimators, random_state=42, n_jobs=-1
                )
            except ImportError:
                y[mask] = np.nanmean(y[valid])
                well.add_data(target_log, y.tolist())
                return int(mask.sum())
        else:
            y[mask] = np.nanmean(y[valid])
            well.add_data(target_log, y.tolist())
            return int(mask.sum())

        model.fit(X[valid], y[valid])
        # For prediction rows, replace NaN predictors with column mean
        X_pred = X[mask].copy()
        col_means = np.nanmean(X[valid], axis=0)
        for col in range(X_pred.shape[1]):
            bad_pred = np.isnan(X_pred[:, col]) | np.isclose(X_pred[:, col], nan_sentinel)
            X_pred[bad_pred, col] = col_means[col]

        y[mask] = model.predict(X_pred)
        well.add_data(target_log, y.tolist())
        return int(mask.sum())

    # ------------------------------------------------------------------
    #  Cross-well normalisation
    # ------------------------------------------------------------------

    @staticmethod
    def normalise_logs(
        well_list,
        log_name: str,
        output_name: Optional[str] = None,
        method: str = "histogram",
        reference_well: Optional[str] = None,
    ) -> bool:
        """
        Normalise a log across all wells to reduce tool/mud variability.

        Parameters
        ----------
        well_list : WellList
        log_name : str
        output_name : str, optional
            Output channel.  None → overwrite original.
        method : str
            ``"histogram"`` — match to reference well P10/P50/P90.
            ``"percentile"`` — robust P5-P95 to [0,1].
            ``"zscore"`` — mean=0, std=1.
        reference_well : str, optional
            Well name used as the reference for histogram matching.
            If None, uses the well with the most data points.
        """
        from weco.preprocessing import normalise_log as _norm

        if method == "histogram" and reference_well:
            # Histogram-match each well to the reference
            ref = next((w for w in well_list.wells if w.name == reference_well), None)
            if ref is None or log_name not in ref.data:
                return False
            ref_vals = np.asarray(ref.data[log_name], dtype=np.float64)
            ref_p = np.percentile(ref_vals, [10, 50, 90])
            for w in well_list.wells:
                if log_name not in w.data or w.name == reference_well:
                    continue
                vals = np.asarray(w.data[log_name], dtype=np.float64)
                w_p = np.percentile(vals, [10, 50, 90])
                # Piecewise linear remap
                mapped = np.interp(vals, w_p, ref_p)
                w.add_data(output_name or log_name, mapped.tolist())
            return True

        return _norm(well_list, log_name, output_name=output_name,
                     method="percentile" if method == "histogram" else method)

    # ------------------------------------------------------------------
    #  Depth matching (pre-alignment)
    # ------------------------------------------------------------------

    @staticmethod
    def depth_match(
        well,
        reference_well,
        log_name: str = "GR",
        max_shift: int = 10,
    ) -> int:
        """
        Estimate and correct a constant depth offset between two wells
        using cross-correlation on a log curve.

        Parameters
        ----------
        well : Well
            Well to shift.
        reference_well : Well
            Reference well (not modified).
        log_name : str
        max_shift : int
            Maximum allowed marker shift.

        Returns
        -------
        int
            Applied shift in markers (positive = shifted down).
        """
        if log_name not in well.data or log_name not in reference_well.data:
            return 0

        a = np.asarray(well.data[log_name], dtype=np.float64)
        b = np.asarray(reference_well.data[log_name], dtype=np.float64)

        # Normalise
        a = (a - a.mean()) / (a.std() + 1e-10)
        b = (b - b.mean()) / (b.std() + 1e-10)

        # Cross-correlate within allowed shift range
        best_shift = 0
        best_corr = -np.inf
        min_len = min(len(a), len(b))

        for shift in range(-max_shift, max_shift + 1):
            if shift >= 0:
                a_slice = a[shift:min_len]
                b_slice = b[:min_len - shift]
            else:
                a_slice = a[:min_len + shift]
                b_slice = b[-shift:min_len]
            if len(a_slice) < 5:
                continue
            corr = np.dot(a_slice, b_slice) / len(a_slice)
            if corr > best_corr:
                best_corr = corr
                best_shift = shift

        if best_shift == 0:
            return 0

        # Apply shift to all data channels
        for name, vals in list(well.data.items()):
            arr = np.asarray(vals, dtype=np.float64)
            shifted = np.roll(arr, best_shift)
            if best_shift > 0:
                shifted[:best_shift] = arr[0]
            else:
                shifted[best_shift:] = arr[-1]
            well.data[name] = tuple(shifted.tolist())

        return best_shift
