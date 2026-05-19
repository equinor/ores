#!/usr/bin/python3

# Association Scientifique pour la Geologie et ses Applications (ASGA)
#
# Copyright (c) 2018 ASGA. All Rights Reserved.
#
# This program is a Trade Secret of the ASGA and it is not to be:
#  - reproduced, published, or disclosed to other,
#  - distributed or displayed,
#  - used for purposes or on Sites other than described in the GOCAD
#    Advancement Agreement, without the prior written authorization
#    of the ASGA.
#
# Licencee agrees to attach or embed this Notice on all copies of the program,
# including partial copies or modified versions thereof.

from weco.lasfile import LASFile
from weco.data import WellList, Well


# noinspection PyShadowingBuiltins
def las2well(las_file, curves=None, filter=None):
    # return None if v == NULL else v
    def gd(_v):
        if _v == las_file.null:
            return None
        else:
            return _v

    if not isinstance(las_file, LASFile):
        las_file = LASFile(las_file)
    well = Well(name=las_file.well_name or 'NONAME')

    well.z = las_file.strt
    well.h = abs(las_file.strt - las_file.stop)
    well.x = las_file.xcoord
    well.y = las_file.ycoord

    # check curves name
    data_index = []
    data_name = []
    filter_var = {}

    if curves:
        for i in curves:
            if isinstance(i, tuple):
                w_name, l_name = i
            else:
                l_name = i
                w_name = l_name.replace(' ', '_')

            c_index = las_file.get_curve_index(l_name)
            if c_index < 0:
                raise Exception('No curve named %s' % l_name)
            data_index.append(c_index)
            data_name.append(w_name)
            if filter:
                filter_var[w_name] = c_index
                filter_var[l_name] = c_index
    else:
        for idx, name in enumerate(las_file.get_all_curves_name()):
            data_index.append(idx)
            w_name = name.replace(' ', '_')
            data_name.append(w_name)

            if filter:
                filter_var[name] = idx
                filter_var[w_name] = idx

    data_array = tuple(list() for _ in range(len(data_index)))
    for row in las_file.data:
        # Remove NDV
        one_data_is_none = False
        for i in row[1:]:  # depth is first
            if i is None or i == -999.:
                one_data_is_none = True
        if one_data_is_none:
            continue

        if filter:
            frow = tuple(map(gd, row))
            dico = dict(_curve=frow, curve=frow)
            for k, v in filter_var.items():
                dico[k] = frow[v]
            try:
                xx = eval(filter, dico)
            except Exception:
                raise Exception('Filter error')
            if xx is False:
                continue
        for dn, didx in enumerate(data_index):
            data_array[dn].append(row[didx])

    for idx, name in enumerate(data_name):
        well.data[name] = data_array[idx]

    well.size = len(data_array[0])

    return well


class LAS2WellList:

    # noinspection PyShadowingBuiltins
    @classmethod
    def run(cls, wl_file, las_files, curves=None, filter=None):
        well_list = WellList()

        for las_file in las_files:
            well = las2well(las_file, curves=curves, filter=filter)
            well_list.add_well(well)

        well_list.write(wl_file)

    @classmethod
    def main(cls, params=None):
        import argparse
        parser = argparse.ArgumentParser(
            description='Create a WeCo well list file from LAS files')
        parser.add_argument('wells_file')
        parser.add_argument('las_files', nargs='+')
        parser.add_argument('--curves', '-c',
                            help='comma separated curves (DEPTH,data=GR)')
        parser.add_argument('--filter', '-f',
                            help='row filter (DEPTH > 10. or data is not None or _curve[4]>5.)')

        args = parser.parse_args(params)
        curves = None
        if args.curves:
            curves = []
            for i in args.curves.split(","):
                if '=' in i:
                    curves.append(tuple(i.split('=', 1)))
                else:
                    curves.append(i)
        cls.run(wl_file=args.wells_file, las_files=args.las_files,
                curves=curves, filter=args.filter)


run = LAS2WellList.run
main = LAS2WellList.main

if __name__ == '__main__':
    main()
