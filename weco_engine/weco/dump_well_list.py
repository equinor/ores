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

from weco.data import WellList
from pathlib import Path
from statistics import stdev, mean
from itertools import chain
from typing import Union, Optional

"""
WeCoWellList command
"""


def dump_well_list(well_list: Union[str, Path, WellList], ndv: Optional[float] = None) -> None:
    if not isinstance(well_list, WellList):
        try:
            well_list = WellList(well_list)
        except FileNotFoundError:
            print("*ERR* file not found")
            return
    if not well_list.nbr_wells():
        print("*ERR* no well")
        return
    # Well
    print("===", well_list.nbr_wells(), "Wells")
    for well in well_list.wells:
        print(f"* {well.name}: size={well.size}, Coord={well.x},{well.y},{well.z}, h={well.h}")
    # data
    all_data = set()
    for well in well_list.wells:
        all_data.update(well.data.keys())
    print("===", len(all_data), " Data")
    for data in sorted(all_data):
        comp = set()
        for well in well_list.wells:
            if data not in well.data:
                comp.add("Not In " + well.name)
                continue
            length = len(well.data[data])
            if length == well.size:
                comp.add("=Size")
            elif length == well.size + 1:
                comp.add("=Size+1")
            elif length == well.size - 1:
                comp.add("=Size-1")
            elif length > well.size:
                comp.add(">Size")
            else:
                comp.add("<Size")
        values = list(chain.from_iterable(w.data[data] for w in well_list.wells))
        if ndv is not None and ndv in values:
            comp.add('NDV')
            values = list(filter(lambda x: x != ndv, values))

        _mean = mean(values)
        _stdev = stdev(values, _mean)
        _max = max(values)
        _min = min(values)

        print(f"* {data}: Min:{_min:5g}, Max:{_max:5g}, Mean:{_mean:5g}, StDev:{_stdev:5g}, {', '.join(sorted(comp))}")

    # region
    all_region = set()
    for well in well_list.wells:
        all_region.update(well.region.keys())
    print("===", len(all_region), " Region")
    for region in sorted(all_region):
        not_in = list("Not In " + w.name for w in well_list.wells if region not in w.region)

        values = list(sorted(set(v for w in well_list.wells for v, _, _ in w.region[region])))

        print(f"* {region}: {values}  {', '.join(sorted(not_in))}")


def main():
    from argparse import ArgumentParser
    parser = ArgumentParser(description="Show Well List content")
    parser.add_argument("--ndv", help="No Data Value", default=None, type=float)
    parser.add_argument("wellfile", help="Well List file name")

    args = parser.parse_args()
    dump_well_list(args.wellfile, ndv=args.ndv)


if __name__ == '__main__':
    main()
