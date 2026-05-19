from weco.data import WellList
from weco.testgen import TestBuilder
from weco.ext import ProjectExt

full_data = (0, 1, 2, 3, 2, 1, 0, 1, 2, 3, 2, 1)
full_zone = (0, 0, 0, 1, 1, 1, 1, 1, 2, 2, 2, 2)
level1_data = ((1, 2, 3), (0, 1, 2, 3), (0, 1, 2))

level1_param = dict(out_nbr_cor=2, var_data="data1", )
level2_param = dict(out_nbr_cor=3, var_data="data2", )


def extract_level(wl, zone, *num):
    new_wl = WellList()

    for wnum, well in zip(num, wl.wells):
        if wnum is None:
            continue
        _, start, lgr = well.region[zone][wnum]
        new_well = new_wl.create_well(well.name, size=lgr + 1)
        for data_name, data_values in well.data.items():
            new_data_values = data_values[start:start + lgr + 1]
            if len(new_data_values):
                new_well.add_data(data_name, new_data_values)

    return new_wl


def build_wl1():
    # real well list
    wl1 = (TestBuilder(3, 12)
           .add_data("data2", full_data)
           .add_region("level", full_zone)
           .add_depth_data()
           .erode_well(0, 0, 1, 2, 3)
           .erode_well(1, 0, 6, 11)
           .erode_well(2, 8, 9, 10, 11)
           .print_erode_map()
           .build()
           .multiscale_from_region('level')
           .wells_add_data('data1', *level1_data)
           .write("ms1.wells.txt")).well_list

    # level 1 well list
    wl2 = WellList()
    for n, i in enumerate(level1_data):
        w = wl2.create_well('Well%i' % n, size=len(i))
        w.add_data("data1", i)
        w.add_region('zone', list((n, n, 1) for n in range(len(i))))
    wl2.write("level1.wells.txt")

    # level 2 , scenario 1, first res
    extract_level(wl1, "level", None, 0, 0).write("level2_1_1.wells.txt")
    extract_level(wl1, "level", 0, 1, 1).write("level2_1_2.wells.txt")
    extract_level(wl1, "level", 1, 2, None).write("level2_1_3.wells.txt")

    extract_level(wl1, "level", None, 2, None).write("level2_2_3.wells.txt")
    extract_level(wl1, "level", 1, None, None).write("level2_2_4.wells.txt")


def build_res1():
    p = ProjectExt()
    p.set_options_ext(level1_param, out_file='ms_level1_res.txt')
    p.run("level1.wells.txt")


def build_res2():
    for i in ('1_1', '1_2', '1_3'):
        print("building level2", i)
        p = ProjectExt()
        p.set_options_ext(level2_param, out_file='ms_level2_%s_res.txt' % i)
        p.run("level2_%s.wells.txt" % i)


def build_ms():
    from weco.multiscale import MultiScaleProject
    project = MultiScaleProject("ms1.wells.txt")
    project.level("level", ("data1",), out_nbr_cor=2, var_data="data1")
    project.final(("data2",), out_nbr_cor=3, var_data="data2"
                  , ms_max_cor_per_scenario=3)
    project.run()


# build_wl1()
# build_res1()
# build_res2()

build_ms()
