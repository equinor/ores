from weco.testgen import TestBuilder
from weco.multiscale import MultiScaleProject

wells_filename = 'ex4_wells.txt'

# ================================
# 1 create random wells_data
# ================================

# 8 wells base size 100
test_builder = TestBuilder(8, 100)

(
    test_builder
        # add data1 :fast sinusoidal
        .add_sin_data("data1", wave_length=10., noise=.2)
        # add data2 :slow sinusoidal
        .add_sin_data("data2", wave_length=50., noise=.1)
        # add pseudo depth data
        .add_depth_data()
        # add random region zone 1
        .add_region1("zone1", 30, 10)

        # erode the top of the wells (max 20)
        .erode_start(20)
        # erode the bottom of the wells (max 20)
        .erode_end(20)
        # erode the middle of the wells (5 Zone 1-20 markers)
        .erode_parts(5, 10)
        # show the "erosion" map
        .print_erode_map()

        # Creates the wells from previous data
        .build()

        # Uses the Zone1 region to create a multiscale level definition
        .multiscale_from_region("zone1")
        # Creates the data associated to the coarse unit
        .multiscale_data("zone1", "msdata1", "data2")
        # add some noise to data1 values
        .add_noise("data1", .3)
        # write the well list in a file
        .write(wells_filename)
)

well_list = test_builder.well_list

# =========================================
# 2 Create and Run a WeCoMultiScale project
# =========================================


# create project
project = MultiScaleProject(well_list)

# Global options for all levels
project.default_options(nbr_cor=10)

# Defines one hierarchical level: define zone, data to transfer, data and options
project.level('zone1', datas=('msdata1',), var_data="msdata1", out_nbr_cor=4)

# Define the final level
project.final(('data1',), var_data="data1", ms_max_cor_per_scenario=4)

# Check if the project is correct
project.check()

# execute tr project
project.run()
