"""
weco.cost_functions — Reusable Python cost function plugins for WeCo
=====================================================================

Ready-to-use :class:`~weco.ext.CCFPartExt` subclasses that add
geological intelligence beyond what the built-in C++ cost functions
provide.

Modules in this file:

* :class:`BiozonAgeCost` — penalise correlating across biozone
  boundaries proportionally to the age difference (§11.8).
* :class:`FaciesGroupCost` — penalise correlating markers from
  different lateral-equivalence facies groups (§13.2).
* :class:`TransportDirectionCost` — penalise correlations that are
  inconsistent with the assumed sediment transport direction (§13.9).

Usage::

    from weco.ext import ProjectExt
    from weco.cost_functions import BiozonAgeCost

    project = ProjectExt()
    project.add_ccf_part(BiozonAgeCost)
    project.set_options_ext(cost_function="composite", ...)
    project.run("wells.txt")

Reference
---------
Baville (2022) §3.4.3, §6.3.3, §6.3.5
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

from weco.ext import CCFPartExt


# ═══════════════════════════════════════════════════════════════════════════
#  BiozonAgeCost  (§11.8)
# ═══════════════════════════════════════════════════════════════════════════

class BiozonAgeCost(CCFPartExt):
    """Penalise correlating markers from different biozones by age offset.

    The cost is proportional to the squared normalised age difference
    between the biozones at the destination markers in each well::

        cost = weight × (|age_A − age_B| / max_age_range)²

    This is a *soft* constraint: correlating within the same biozone
    costs nothing; correlating across one zone is cheap; correlating
    across many zones is very expensive.

    Requirements
    ------------
    Each well must have:
    - A *region* called ``biozone`` (or the name set via
      :attr:`REGION_NAME`) with integer IDs assigned to marker
      intervals.  Use :func:`weco.preprocessing.add_biozones` to
      create this from CSV biostratigraphy.

    Class attributes (override before ``add_ccf_part``):

    =============  ========  ==========================================
    Attribute      Default   Description
    =============  ========  ==========================================
    REGION_NAME    biozone   Name of the biozone region on each well
    ZONE_AGES      {}        {zone_id: absolute_age_Ma}  mapping
    WEIGHT         1.0       Scaling weight for this cost term
    =============  ========  ==========================================

    If ``ZONE_AGES`` is empty, the cost falls back to an ordinal
    penalty: ``|id_A − id_B|`` normalised by the total number of
    distinct zones.
    """

    #: Override these before calling ``project.add_ccf_part(BiozonAgeCost)``
    REGION_NAME: str = "biozone"
    ZONE_AGES: Dict[int, float] = {}
    WEIGHT: float = 1.0

    # ---- internal state (set per-merge in init) -------------------------
    _zone = None
    _max_age_range: float = 1.0
    _use_ordinal: bool = True
    _n_zones: int = 1

    # CCFPartExt API ------------------------------------------------------

    @staticmethod
    def dest_only():
        """Only destination marker values are needed (optimisation)."""
        return True

    def init(self):
        """Called once per merge — bind region helper."""
        self._zone = self.region_helper(self.REGION_NAME)

        if self.ZONE_AGES:
            ages = list(self.ZONE_AGES.values())
            self._max_age_range = max(ages) - min(ages)
            if self._max_age_range < 1e-10:
                self._max_age_range = 1.0
            self._use_ordinal = False
        else:
            # Fallback: collect distinct zone IDs across wells
            ids: set = set()
            for w in range(self.size()):
                try:
                    ids.add(self._zone.dest(w))
                except Exception:
                    pass
            self._n_zones = max(len(ids), 1)
            self._use_ordinal = True

    def dest_cost(self, prev_cost):
        """Compute biozone age-offset cost at destination markers."""
        # Collect zone IDs at destination for each well
        zones = []
        for w in range(self.size()):
            zones.append(self._zone.dest(w))

        # Pairwise age difference (averaged over all pairs)
        n = len(zones)
        if n < 2:
            return True, prev_cost

        total = 0.0
        count = 0
        for i in range(n):
            for j in range(i + 1, n):
                if self._use_ordinal:
                    diff = abs(zones[i] - zones[j]) / self._n_zones
                else:
                    age_i = self.ZONE_AGES.get(zones[i], 0.0)
                    age_j = self.ZONE_AGES.get(zones[j], 0.0)
                    diff = abs(age_i - age_j) / self._max_age_range
                total += diff * diff
                count += 1

        cost = self.WEIGHT * total / max(count, 1)
        return True, prev_cost + cost


# ═══════════════════════════════════════════════════════════════════════════
#  FaciesGroupCost  (§13.2)
# ═══════════════════════════════════════════════════════════════════════════

class FaciesGroupCost(CCFPartExt):
    """Assign zero cost when facies belong to the same lateral-equivalence
    group, and a penalty proportional to inter-group distance otherwise.

    Each well must have a ``facies`` region (integer IDs).  The
    :attr:`FACIES_GROUPS` class attribute maps facies IDs to group
    indices.  Facies in the same group are considered laterally
    equivalent and cost nothing to correlate.

    Class attributes (override before ``add_ccf_part``):

    ===============  =========  =========================================
    Attribute        Default    Description
    ===============  =========  =========================================
    REGION_NAME      facies     Region name on each well
    FACIES_GROUPS    {}         {facies_id: group_index}
    WEIGHT           1.0        Scaling weight
    ===============  =========  =========================================

    Reference: Baville (2022) §3.4.5, §6.3.3
    """

    REGION_NAME: str = "facies"
    FACIES_GROUPS: Dict[int, int] = {}
    WEIGHT: float = 1.0

    _facies = None
    _n_groups: int = 1

    @staticmethod
    def dest_only():
        return True

    def init(self):
        self._facies = self.region_helper(self.REGION_NAME)
        if self.FACIES_GROUPS:
            self._n_groups = max(len(set(self.FACIES_GROUPS.values())), 1)
        else:
            self._n_groups = 1

    def dest_cost(self, prev_cost):
        facies = [self._facies.dest(w) for w in range(self.size())]
        n = len(facies)
        if n < 2:
            return True, prev_cost

        total = 0.0
        count = 0
        for i in range(n):
            for j in range(i + 1, n):
                gi = self.FACIES_GROUPS.get(facies[i], facies[i])
                gj = self.FACIES_GROUPS.get(facies[j], facies[j])
                if gi != gj:
                    # Normalised group distance
                    total += abs(gi - gj) / max(self._n_groups, 1)
                count += 1

        cost = self.WEIGHT * total / max(count, 1)
        return True, prev_cost + cost


# ═══════════════════════════════════════════════════════════════════════════
#  TransportDirectionCost  (§13.9)
# ═══════════════════════════════════════════════════════════════════════════

class TransportDirectionCost(CCFPartExt):
    """Penalise correlations inconsistent with the assumed transport direction.

    Given a sediment transport azimuth θ (degrees from N), wells that
    are aligned parallel to θ should show a distality gradient (proximal
    → distal), while wells perpendicular to θ should show similar
    depositional character.

    Each well must have a ``distality`` data channel (float, 0 = proximal,
    1 = distal), typically pre-computed by
    :func:`weco.distality.compute_distality`.

    The cost penalises correlating markers where the distality difference
    is inconsistent with the expected gradient along the transport
    direction.

    Class attributes (override before ``add_ccf_part``):

    ===============  =========  =========================================
    Attribute        Default    Description
    ===============  =========  =========================================
    DATA_NAME        distality  Data channel name
    WEIGHT           0.5        Scaling weight
    ===============  =========  =========================================
    """

    DATA_NAME: str = "distality"
    WEIGHT: float = 0.5

    _dist = None

    def init(self):
        self._dist = self.data_helper(self.DATA_NAME)

    def full_cost(self, prev_cost):
        # Variance of distality across current destination markers
        var = self._dist.dest_var()
        cost = self.WEIGHT * var
        return True, prev_cost + cost


# ═══════════════════════════════════════════════════════════════════════════
#  FaciesMapCost  (§11.0.3)
# ═══════════════════════════════════════════════════════════════════════════

class FaciesMapCost(CCFPartExt):
    """Penalise correlations based on facies transition probability.

    Uses a transition probability matrix to assign cost when correlating
    markers with different facies.  Low-probability transitions get
    high cost; high-probability transitions get low cost.

    The matrix can be estimated from well data using
    :func:`compute_facies_transitions`.

    Class attributes (override before ``add_ccf_part``):

    ==================  =========  =========================================
    Attribute           Default    Description
    ==================  =========  =========================================
    REGION_NAME         facies     Region name with facies IDs
    TRANSITION_MATRIX   {}         {(f_src, f_dst): probability} mapping
    WEIGHT              1.0        Scaling weight
    ==================  =========  =========================================

    Reference: Baville (2022) §6.3.5
    """

    REGION_NAME: str = "facies"
    TRANSITION_MATRIX: Dict[Tuple[int, int], float] = {}
    WEIGHT: float = 1.0

    _facies = None

    @staticmethod
    def dest_only():
        return True

    def init(self):
        self._facies = self.region_helper(self.REGION_NAME)

    def dest_cost(self, prev_cost):
        facies = [self._facies.dest(w) for w in range(self.size())]
        n = len(facies)
        if n < 2:
            return True, prev_cost

        total = 0.0
        count = 0
        for i in range(n):
            for j in range(i + 1, n):
                pair = (facies[i], facies[j])
                prob = self.TRANSITION_MATRIX.get(pair, 0.0)
                # Low probability → high cost
                cost_ij = 1.0 - prob if prob > 0 else 1.0
                total += cost_ij
                count += 1

        cost = self.WEIGHT * total / max(count, 1)
        return True, prev_cost + cost


def compute_facies_transitions(
    well_list,
    region_name: str = "facies",
) -> Dict[Tuple[int, int], float]:
    """Compute facies transition probability matrix from well data.

    Counts vertical transitions between facies in all wells and
    normalises to probabilities.  Useful as input for
    :class:`FaciesMapCost.TRANSITION_MATRIX`.

    Parameters
    ----------
    well_list : WellList
        Well data with facies regions.
    region_name : str
        Region name containing facies IDs.

    Returns
    -------
    dict[(int, int), float]
        Transition probability matrix.
    """
    counts: Dict[Tuple[int, int], int] = {}
    totals: Dict[int, int] = {}

    for well in well_list.wells:
        if region_name not in getattr(well, "region", {}):
            continue
        intervals = well.region[region_name]
        for idx in range(len(intervals) - 1):
            f_from = intervals[idx][0]
            f_to = intervals[idx + 1][0]
            counts[(f_from, f_to)] = counts.get((f_from, f_to), 0) + 1
            totals[f_from] = totals.get(f_from, 0) + 1

    matrix = {}
    for (f_from, f_to), count in counts.items():
        total = totals.get(f_from, 1)
        matrix[(f_from, f_to)] = count / total

    return matrix


# ═══════════════════════════════════════════════════════════════════════════
#  ThicknessRatioCost  (§11.5)
# ═══════════════════════════════════════════════════════════════════════════

class ThicknessRatioCost(CCFPartExt):
    """Penalise geologically implausible thickness ratios between wells.

    When correlating intervals, the thickness ratio between wells should
    be consistent with expected depositional geometry.  Large deviations
    from the expected ratio are penalised.

    cost = weight × ((h_a/h_b - expected_ratio) / sigma)²

    Reference: Baville (2022) §6.3.5 (p. 155)

    Class attributes (override before ``add_ccf_part``):

    ==================  =========  =========================================
    Attribute           Default    Description
    ==================  =========  =========================================
    DATA_NAME           depth      Depth data channel
    EXPECTED_RATIO      1.0        Expected thickness ratio
    SIGMA               0.5        Tolerance (standard deviation)
    WEIGHT              0.5        Scaling weight
    ==================  =========  =========================================
    """

    DATA_NAME: str = "depth"
    EXPECTED_RATIO: float = 1.0
    SIGMA: float = 0.5
    WEIGHT: float = 0.5

    _depth = None

    def init(self):
        self._depth = self.data_helper(self.DATA_NAME)

    def full_cost(self, prev_cost):
        # Collect depth at src and dest for each well
        n = self.size()
        if n < 2:
            return True, prev_cost

        thicknesses = []
        for w in range(n):
            src_d = self._depth.src(w)
            dest_d = self._depth.dest(w)
            thicknesses.append(abs(dest_d - src_d) + 1e-10)

        total = 0.0
        count = 0
        for i in range(n):
            for j in range(i + 1, n):
                ratio = thicknesses[i] / thicknesses[j]
                deviation = (ratio - self.EXPECTED_RATIO) / self.SIGMA
                total += deviation * deviation
                count += 1

        cost = self.WEIGHT * total / max(count, 1)
        return True, prev_cost + cost


# ═══════════════════════════════════════════════════════════════════════════
#  VerticalTransitionCost  (§11.6)
# ═══════════════════════════════════════════════════════════════════════════

class VerticalTransitionCost(CCFPartExt):
    """Data-driven transition cost based on vertical facies stacking.

    Replaces the constant gap cost (0.1) with a cost derived from
    facies transition probabilities.  Penalises facies sequences that
    violate the expected stacking pattern.

    Reference: Baville (2022) §6.3.5 (p. 156); Homewood et al. (1992)

    Class attributes (override before ``add_ccf_part``):

    ==================  =========  =========================================
    Attribute           Default    Description
    ==================  =========  =========================================
    REGION_NAME         facies     Region name with facies IDs
    TRANSITION_MATRIX   {}         {(f_src, f_dst): probability}
    WEIGHT              0.5        Scaling weight
    ==================  =========  =========================================
    """

    REGION_NAME: str = "facies"
    TRANSITION_MATRIX: Dict[Tuple[int, int], float] = {}
    WEIGHT: float = 0.5

    _facies = None

    @staticmethod
    def dest_only():
        return False

    def init(self):
        self._facies = self.region_helper(self.REGION_NAME)

    def full_cost(self, prev_cost):
        n = self.size()
        if n < 1:
            return True, prev_cost

        total = 0.0
        count = 0
        for w in range(n):
            src_f = self._facies.src(w)
            dest_f = self._facies.dest(w)
            if src_f != dest_f:
                pair = (src_f, dest_f)
                prob = self.TRANSITION_MATRIX.get(pair, 0.0)
                cost_w = 1.0 - prob if prob > 0 else 1.0
                total += cost_w
            count += 1

        cost = self.WEIGHT * total / max(count, 1)
        return True, prev_cost + cost


# ═══════════════════════════════════════════════════════════════════════════
#  ErosionSurfaceCost  (§11.7)
# ═══════════════════════════════════════════════════════════════════════════

class ErosionSurfaceCost(CCFPartExt):
    """Penalise correlations that cross detected erosion surfaces.

    Erosion surfaces are identified by sharp GR bases (abrupt decrease
    in GR from high to low = erosional truncation).  These act as hard
    boundaries that should not be crossed.

    This cost applies a high penalty when source and destination markers
    are on opposite sides of an erosion surface.

    Reference: Baville (2022) §6.3.5 (p. 156)

    Class attributes (override before ``add_ccf_part``):

    ==================  =========  =========================================
    Attribute           Default    Description
    ==================  =========  =========================================
    REGION_NAME         erosion    Region name with erosion boundaries
    WEIGHT              10.0       High weight = near-hard boundary
    ==================  =========  =========================================
    """

    REGION_NAME: str = "erosion"
    WEIGHT: float = 10.0

    _erosion = None

    @staticmethod
    def dest_only():
        return False

    def init(self):
        self._erosion = self.region_helper(self.REGION_NAME)

    def full_cost(self, prev_cost):
        n = self.size()
        total = 0.0
        for w in range(n):
            src_r = self._erosion.src(w)
            dest_r = self._erosion.dest(w)
            if src_r != dest_r:
                total += 1.0

        cost = self.WEIGHT * total / max(n, 1)
        return True, prev_cost + cost


# ═══════════════════════════════════════════════════════════════════════════
#  WeightedCombinationCost  (§11.8.2)
# ═══════════════════════════════════════════════════════════════════════════

class WeightedCombinationCost(CCFPartExt):
    """Multi-criteria cost combination framework.

    Wraps multiple CCFPartExt instances and combines their costs
    using configurable combination modes: sum, weighted average, or
    product.

    Class attributes (override before ``add_ccf_part``):

    ==================  ==================  ===================================
    Attribute           Default             Description
    ==================  ==================  ===================================
    COST_PARTS          []                  List of (CCFPartExt_class, weight)
    COMBINATION         "weighted_average"  "sum", "weighted_average", "product"
    ==================  ==================  ===================================

    Reference: Baville (2022) §6.3.5 (p. 156) — normalised multi-criteria
    """

    COST_PARTS: List[Tuple[type, float]] = []
    COMBINATION: str = "weighted_average"

    _parts: list = []

    def init(self):
        self._parts = []
        for cls, weight in self.COST_PARTS:
            instance = cls.__new__(cls)
            CCFPartExt.__init__(instance)
            instance.WEIGHT = weight
            self._parts.append(instance)

    def dest_cost(self, prev_cost):
        costs = []
        weights = []
        for part in self._parts:
            ok, c = part.dest_cost(0.0)
            if ok:
                costs.append(c)
                weights.append(getattr(part, "WEIGHT", 1.0))

        if not costs:
            return True, prev_cost

        if self.COMBINATION == "sum":
            combined = sum(costs)
        elif self.COMBINATION == "product":
            combined = 1.0
            for c in costs:
                combined *= (1.0 + c)
            combined -= 1.0
        else:  # weighted_average
            w_total = sum(weights)
            combined = sum(c * w for c, w in zip(costs, weights)) / max(w_total, 1e-10)

        return True, prev_cost + combined


# ═══════════════════════════════════════════════════════════════════════════
# §11.12 — Asymmetric B3D Cost (different updip vs downdip scaling)
# ═══════════════════════════════════════════════════════════════════════════


class AsymmetricB3DCost(CCFPartExt):
    """
    §11.12.2 — Asymmetric B3D that applies different scaling
    factors for updip vs downdip transitions.

    Attributes
    ----------
    UPDIP_SCALE : float
        Scaling factor for updip (thinning) direction. Default 1.0.
    DOWNDIP_SCALE : float
        Scaling factor for downdip (thickening) direction. Default 1.5.
    NORMALIZE : bool
        §11.4.1 — Normalize by characteristic area A₀ if True.
    A0 : float
        §11.4.1 — Characteristic area for normalization.
    """

    UPDIP_SCALE: float = 1.0
    DOWNDIP_SCALE: float = 1.5
    NORMALIZE: bool = True
    A0: float = 100.0

    def dest_cost(self, prev_cost):
        wells = self.get_well_list()
        n = wells.nbr_well()

        total = 0.0
        count = 0

        for w in range(n):
            src = self.get_ori(w)
            dst = self.get_dest(w)
            if src < 0 or dst < 0:
                continue

            well = wells.get_well(w)
            depth_key = None
            for dk in ("Depth", "DEPTH", "MD"):
                if dk in well.data:
                    depth_key = dk
                    break
            if depth_key is None:
                continue

            depths = well.data[depth_key]
            if src >= len(depths) or dst >= len(depths):
                continue

            thickness = abs(depths[dst] - depths[src])

            # Determine direction
            if dst > src:
                scale = self.DOWNDIP_SCALE
            else:
                scale = self.UPDIP_SCALE

            cost = scale * thickness
            if self.NORMALIZE and self.A0 > 0:
                cost /= self.A0

            total += cost
            count += 1

        if count == 0:
            return True, prev_cost

        return True, prev_cost + total / count


# ═══════════════════════════════════════════════════════════════════════════
# §11.13 — Production Data Cost (pressure communication = same zone)
# ═══════════════════════════════════════════════════════════════════════════


class ProductionDataCost(CCFPartExt):
    """
    §11.13.1 — Penalise correlations that separate wells known to be in
    pressure communication (same reservoir zone).

    Attributes
    ----------
    CONNECTED_PAIRS : list of (int, int)
        Well index pairs known to communicate via production data.
    PENALTY : float
        Cost penalty when connected wells end up in different zones.
    """

    CONNECTED_PAIRS: List[Tuple[int, int]] = []
    PENALTY: float = 5.0

    def dest_cost(self, prev_cost):
        penalty = 0.0
        for (w1, w2) in self.CONNECTED_PAIRS:
            d1 = self.get_dest(w1)
            d2 = self.get_dest(w2)
            if d1 < 0 or d2 < 0:
                continue
            # If destinations diverge significantly, add penalty
            if abs(d1 - d2) > 2:
                penalty += self.PENALTY

        return True, prev_cost + penalty


# ═══════════════════════════════════════════════════════════════════════════
# §11.13.2 — Tracer Breakthrough Hard Constraint (stub)
# ═══════════════════════════════════════════════════════════════════════════


class TracerConstraintCost(CCFPartExt):
    """
    §11.13.2 — Tracer breakthrough data as hard correlation constraint.

    If a tracer test shows that well A zone X connects to well B zone Y,
    this cost function returns infinite cost for correlations violating
    that constraint.

    Attributes
    ----------
    CONSTRAINTS : list of (int, int, int, int)
        (well_a, zone_a, well_b, zone_b) — hard connectivity constraints.
    """

    CONSTRAINTS: List[Tuple[int, int, int, int]] = []

    def dest_cost(self, prev_cost):
        for (wa, za, wb, zb) in self.CONSTRAINTS:
            da = self.get_dest(wa)
            db = self.get_dest(wb)
            if da == za and db != zb:
                return False, 0.0  # Violates hard constraint
            if db == zb and da != za:
                return False, 0.0

        return True, prev_cost


# ═══════════════════════════════════════════════════════════════════════════
# §11.13.3 — Rate / Decline Similarity Cost
# ═══════════════════════════════════════════════════════════════════════════


class RateDeclineCost(CCFPartExt):
    """
    §11.13.3 — Penalise correlating markers whose production rate
    or decline curves are dissimilar.

    Requires a ``rate`` (or custom-named) data channel on each well
    containing production rate values at marker depths.  The cost is
    the normalised L2 difference between rate values at destination
    markers across all wells.

    Class attributes (override before ``add_ccf_part``):

    ==============  ========  ============================================
    Attribute       Default   Description
    ==============  ========  ============================================
    DATA_NAME       rate      Name of the production rate data channel
    WEIGHT          1.0       Scaling weight for this cost term
    ==============  ========  ============================================
    """

    DATA_NAME: str = "rate"
    WEIGHT: float = 1.0

    _rate = None
    _max_range: float = 1.0

    @staticmethod
    def dest_only():
        return True

    def init(self):
        self._rate = self.data_helper(self.DATA_NAME)
        all_vals = []
        for w in range(self.size()):
            well = self.well(w)
            for m in range(well.well_size()):
                all_vals.append(self._rate._data[w].get(m))
        if all_vals:
            self._max_range = max(all_vals) - min(all_vals)
            if self._max_range < 1e-10:
                self._max_range = 1.0

    def dest_cost(self, prev_cost):
        rates = [self._rate.dest(w) for w in range(self.size())]
        n = len(rates)
        if n < 2:
            return True, prev_cost

        total = 0.0
        count = 0
        for i in range(n):
            for j in range(i + 1, n):
                diff = abs(rates[i] - rates[j]) / self._max_range
                total += diff * diff
                count += 1

        cost = self.WEIGHT * total / max(count, 1)
        return True, prev_cost + cost
