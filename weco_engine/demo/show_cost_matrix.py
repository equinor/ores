import matplotlib.pyplot as plt
from weco.data import CostMatrix

filename = "../wecorun/cm_0_1.txt"
# well index
well1 = 0
well2 = 1

# get cost matrix as np array
cost_matrix = CostMatrix(filename)
np_array = cost_matrix.get_array_dest(well1, well2)

# show it
fig, main = plt.subplots(1, 1)
main_fig = main.pcolormesh(np_array)
main.invert_yaxis()
fig.colorbar(main_fig)
plt.show()
