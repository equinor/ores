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

from .data import WellList
import sys


class AddRegion:
    @classmethod
    def fatal(cls, text):
        print("*ERROR*", text)
        sys.exit(-1)

    @classmethod
    def warning(cls, text):
        print("*WARNING*", text)

    @classmethod
    def read_csv(cls, filename, float_data=False):
        from csv import reader, Sniffer
        if float_data:
            cvt = float
        else:
            cvt = int

        with open(filename, newline='') as csvfile:
            dialect = Sniffer().sniff(csvfile.read(1024))
            csvfile.seek(0)
            return list((a, b, cvt(c), cvt(d)) for a, b, c, d in
                        reader(csvfile, dialect))

    @classmethod
    def region2id(cls, csv_data: list[tuple]) -> list[tuple]:
        """
        Transforms the input region names (column 1) into region ids.
        """
        region_codes = dict()
        region_index = 0
        new_data = list()
        for well_name, region, start, stop in csv_data:
            # Find or add region index to the dict
            if region_codes.setdefault(region, region_index) == region_index:
                region_index += 1
                print('Adding region code')
            new_data.append((well_name, region_codes[region], start, stop))
        return new_data

    @classmethod
    def run(cls, wells_file: str, region_name, csv_file: str, out: str = None, depth: str = None):
        """
        Creates regions from a wells file and a CSV file (well, region_id, start, end)
        :param wells_file: Input WeCo wells file
        :param region_name: Name of region to create (should be the value in the CSV file)
        :param csv_file: Input CSV file/ Expected structure: well, region, start, end
        :param out: Output file name (the input file is overwritten if None)
        :param depth: Name of the depth log.
        If None, top / bottom values will be treated as index
        """

        wells = WellList(wells_file)
        if depth and not wells.wells_data_exists(depth):
            cls.fatal(f'Depth log named {depth} not found in file {wells_file}')

        data = cls.read_csv(csv_file, float_data=(depth is not None))

        if isinstance(data[0][1], str):
            data = cls.region2id(data)
            print(data)

        for well in wells.wells:
            well.region[region_name] = list()

        for well_name, region, start, stop in data:
            well = wells.get_well(well_name)
            if well is None:
                cls.warning("Well %s in file not found in WellList" % well_name)
                continue
            if depth:
                # translate depth to index
                dd = well.data[depth]
                for n, v in enumerate(dd):
                    if v >= start:
                        start = n
                        break
                else:
                    cls.warning(f"Depth outside range for well {well_name}")
                    continue
                for n, v in enumerate(dd):
                    if v > stop:
                        stop = max(start, 0, n - 1)
                        break
                else:
                    stop = len(dd)

            well.region[region_name].append((region, start, stop - start))

        wells.write(out or wells_file)
        print("Ok;")

    @classmethod
    def main(cls, params=None):
        import argparse
        parser = argparse.ArgumentParser(
            description='Add region from csv file '
                        '(well,region,start,end) to a welllist')
        parser.add_argument('wells_file')
        parser.add_argument('region_name', )
        parser.add_argument('csv_file', )
        parser.add_argument('--depth', '-z', help='use depth ')
        parser.add_argument('--out', '-o', help='out file name')

        args = parser.parse_args(params)

        cls.run(args.wells_file, args.region_name, args.csv_file, out=args.out,
                depth=args.depth)


run = AddRegion.run
main = AddRegion.main

if __name__ == '__main__':
    main()
