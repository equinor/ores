from weco.data import WellList
from weco.multiscale import MultiScaleChecker, MultiScaleProject
from weco.testgen import TestBuilder


def create1():
    wells = WellList()

    for i in range(3):
        (wells.create_well("well%i" % (i + 1), y=i, size=10)
         .add_data('depth', list(range(10)))
         .add_data('data1', (2, 4, 6, 8))
         .add_data('dataf', list(range(10)))
         .add_region('level1', (0, 0, 3), (1, 3, 3), (2, 6, 3))
         )
    return wells


def test1():
    c = MultiScaleChecker(create1())
    c.valid_multiscale_project(
        ('level1', ('data1',)),
        ('dataf',)
    )
    return c.print_check_result("test1")


def project1():
    (MultiScaleProject(create1())
     .default_options(debug_cor_info=1, out_nbr_cor=2, ms_max_cor_per_branch=2)
     .level('level1', ('data1',), var_data="data1")
     .final(('dataf',), var_data="dataf")
     .check()
     .run()
     )


"""
create1().write('wells.txt')
test1()
project1()
"""


def test2():
    # ==================== create well list =====================
    # Equivalent to
    # var  = (TestBuilder(8, 100)
    # var.sin_data(...)
    # var.sin_data(...)
    well_list = (TestBuilder(8, 100)
                 .add_sin_data("data1", wave_length=10., noise=.2)
                 .add_sin_data("data2", wave_length=50., noise=.1)
                 .add_depth_data()
                 .add_region1("zone1", 30, 10)

                 .erode_start(20)
                 .erode_end(20)
                 .erode_parts(5, 10)
                 .print_erode_map()  # Some text output

                 .build()  # Creates the wells

                 .multiscale_from_region("zone1")  # Uses the Zone1 region for use in multisacele
                 .multiscale_data("zone1", "msdata1", "data2")  # Creates the info associated to the coarse unit
                 .add_noise("data1", .3)
                 .write("test_wells.txt")
                 ).well_list

    # run project
    (MultiScaleProject(well_list)
     # Global options for all levels
     .default_options(out_nbr_cor=4, nbr_cor=10, ms_max_cor_per_scenario=4)
     # Creates one hierarchical level: define zone, data to transfer, data and options
     .level('zone1', datas=('msdata1',), var_data="msdata1", out_nbr_cor=4)
     .final(('data1',), var_data="data1", out_nbr_cor=4)  #
     .check()
     .run()
     )


test2()
