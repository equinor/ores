# Data Set 1.1 - Variance Cost Function Test

## Purpose

Synthetic toy example demonstrating the **variance** correlation cost function
(`var-data`). Tests how different weight ratios between two data channels
affect correlation results.

## Wells: 3

Three synthetic wells with two simulated petrophysical-like signals
(**VarData1** and **VarData2**) as functions of depth.

## Data Channels

- **Depth**: Simulated measured depth
- **VarData1**: First synthetic log (e.g., analogous to GR)
- **VarData2**: Second synthetic log (e.g., analogous to resistivity)

## Options (5 configurations)

Each option file varies the weight ratio between VarData1 and VarData2:

| File      | var-weight | var-weight2 | Interpretation              |
|-----------|:----------:|:-----------:|-----------------------------|
| option_1  | 1.0        | 0.0         | VarData1 only               |
| option_2  | 0.75       | 0.25        | VarData1 dominant           |
| option_3  | 0.5        | 0.5         | Equal weight                |
| option_4  | 0.25       | 0.75        | VarData2 dominant           |
| option_5  | 0.0        | 1.0         | VarData2 only               |

## Correlation Cost Function

The **variance** cost function minimises the variance of log values along
each correlation horizon. If values tied by a correlation line are similar
across wells, the cost is low. The key equation:

$$C_{var} = \sum_{h} \text{Var}(d_{h,1}, d_{h,2}, \ldots, d_{h,n_w})$$

where $d_{h,w}$ is the data value at horizon $h$ in well $w$.

## References

- Lallier, F. et al. (2016) Uncertainty assessment in the stratigraphic
  well correlation of a carbonate ramp. *AAPG Bulletin* 100, 625–648.
- Edwards, J. et al. (2017) Uncertainty management in stratigraphic well
  correlation and stratigraphic architectures: A training-based method.
  *Computers & Geosciences* 111, 1–17.
- Baville, P. (2022) *Stratigraphic correlation of well logs using
  graph-based dynamic time warping*, PhD Thesis, Université de Lorraine, §3.

## Authors

Christophe Antoine, Guillaume Caumon, Paul Baville - ASGA/RING, Université de Lorraine.
