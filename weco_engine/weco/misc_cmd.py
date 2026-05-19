# Association Scientifique pour la Geologie et ses Applications (ASGA)
#
# Copyright (c) 2024 ASGA. All Rights Reserved.
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


def region2data():
    import argparse
    parser = argparse.ArgumentParser(description='Create a new log(data) from regions')
    parser.add_argument('wells_file', help='Wells file')
    parser.add_argument('region_name', help='Region name')
    parser.add_argument('--data-name', help='Log name (default:region name)')
    parser.add_argument('--out', '-o', help='out file name')

    args = parser.parse_args()

    wells = WellList(args.wells_file)
    wells.add_data_from_region(args.region_name, args.data_name)
    wells.write(args.out or args.wells_file)


def data2region():
    import argparse
    parser = argparse.ArgumentParser(description='Create a new region from log(data)')
    parser.add_argument('wells_file', help='Wells file')
    parser.add_argument('--region-name', help='Region name (default:log name)')
    parser.add_argument('data_name', help='Log name (default:region name)')
    parser.add_argument('--out', '-o', help='out file name')

    args = parser.parse_args()

    wells = WellList(args.wells_file)
    wells.add_region_from_data(args.data_name, args.region_name)
    wells.write(args.out or args.wells_file)
