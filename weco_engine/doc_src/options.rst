Options
=======

WeCoBin -h gives the complete option list.

Global
------
* cost-matrix (String) =  : cost matrix file name. If this option is set, WeCo
  create a file for every DTW correlations.It contains a part of the transition
  costs. (Debug or Visualisation)

  Warning: this option consumes a lot of time and disk space.

* order-dot (String) =  : Write order tasks as a dot file
* order-only (Bool) = 0 : Stop after order tasks generation
* debug-cor-info (Bool) = 0 : print some debug information if set.
* max-cor (Int) = 50 : maximum number of correlations kept inside DTW.
* min-dist (Float) = 0.000000 : minimum distance between 2 correlations
* nbr-cor (Int) = 50 : number of correlations kept at the end of a DTW
  correlation.
* step-dot (String) =  : result filename for each steps (dot format)
* step-file (String) =  : result filename for each steps (WeCo format)
* thread (Int) = 0 : number of threads (0 for auto)

* cost-function (Select) = composite : cost function
   - composite : composite cost function

* order (Select) = pyramidal : task ordering
   - distality : Reorder wells by them distality from the most distal to the most proximal (Not Working)
   - linear : Correlates 1 to 2, then 1-2 to 3, etc
   - position : Uses spatial clustering of well positions with BSP-trees to decide about the correlation order
   - pyramidal : Correlates 1 to 2, then 3 to 4, then 1-2 to 3-4, etc


Final Result
------------
* out-dot (String) =  : result file (dot format)
* out-file (String) = out.txt : result file (WeCo format)
* out-min-dist (Float) = 0.000000 : minimum distance between 2 correlations.
* out-nbr-cor (Int) = 5 : number of correlation in final result


composite Cost Function
-----------------------

b3dcurve
^^^^^^^^

* azimuth (Data)  : It corresponds to the strike orientation.
* delta-dx (Float) = 1.000000 : It corresponds to the extension of the delta in the strike direction (m).
* delta-dy (Float) = 1.000000 : It corresponds to the extension of the delta in the dip direction (m).
* delta-dz (Float) = 0.000000 : It corresponds to the vertical extension of the delta (m).
* depth (Data)  : It correspond to the z-axis coordinate.
* dip (Data) : It corresponds to the dip angle.
* facies-b3d (Data) : It corresponds to the paleo-depth of the deposit.
* facies-file (String) : It corresponds to the file where all information about facies are stored (z range, lateral
  & vertical extension).
* sed-dir (Float) = 90.000000 : It corresponds to the principal sediment transport direction (deg).
* write-bezier (Bool) = 0 : If true, it generates point sets of all Bezier curves interpolations.
* write-profile (Bool) = 0 : If true, it generates point sets of all translated depositional profiles.

const-gap-cost
^^^^^^^^^^^^^^

 * const-gap-cost (Float) = 0.000000 : Constant Gap Cost
 * const-gap-cost-end (Float) = -1.000000 : Constant Gap Cost at well end (default = const-gap-cost)
 * const-gap-cost-start (Float) = -1.000000 : Constant Gap Cost at well start (default = const-gap-cost)

distal
^^^^^^

* distal (Data) =  : It correspond to the paleo-distality of the well.
* facies (Data) =  : It corresponds to the paleo-depth of the deposit.
* scaling (Float) = 1.000000 : It corresponds to the scaling coefficient representing how the lateral size of the
  depositional system is deemed to scale with the inter-well distance.

gap-cost-func
^^^^^^^^^^^^^
* gap-cost-func (Data) =  : Gap Cost Function data name
* gap-cost-func-mult (Float) = 1.000000 : Gap Cost Function multiplier

no-crossing
^^^^^^^^^^^^^
* no-crossing (Region) =  : regions used for no crossing check
* no-crossing2 (Region) =  : regions used for no crossing check 2
* no-crossing3 (Region) =  : regions used for no crossing check 3

polarity
^^^^^^^^
* polarity-cost-diff (Float) = 0.500000 : Polarity test: gap cost if polarity is not the same
* polarity-cost-end (Float) = 0.500000 : Polarity test: gap cost at well start
* polarity-cost-same (Float) = 0.500000 : Polarity test: gap cost if polarity is the same
* polarity-cost-start (Float) = 0.500000 : Polarity test: gap cost at well start
* polarity-region (Region) =  : Polarity test: region name

same-region
^^^^^^^^^^^
* same-region (Region) =  : regions used for same region check
* same-region2 (Region) =  : regions used for same region check 2
* same-region3 (Region) =  : regions used for same region check 3

variance
^^^^^^^^
* var-data (Data) =  : data name for variance cost
* var-weight (Float) = 1.000000 : weight for variance cost
* var-data2 (Data) =  : data name for variance cost 2
* var-weight2 (Float) = 1.000000 : weight for variance cost 2
* var-data3 (Data) =  : data name for variance cost 3
* var-weight3 (Float) = 1.000000 : weight for variance cost 3
* var-data4 (Data) =  : data name for variance cost 4
* var-weight4 (Float) = 1.000000 : weight for variance cost 4
* var-data5 (Data) =  : data name for variance cost 5
* var-weight5 (Float) = 1.000000 : weight for variance cost 5
