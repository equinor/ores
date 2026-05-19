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

from .data import ResAndWL


class Res2CSV:
    @classmethod
    def run(cls, res_file, well_list, csv_file="result.csv", cor_num=0,
            zdata=None, max_line=0, marker_name="M"):
        if '%' not in marker_name:
            marker_name += '%03i'
        data = ResAndWL(res_file, well_list)

        if not data.check():
            print("*ERR* bad input files")
            return False

        if cor_num < 0 or cor_num >= data.res_file.get_nbr_results():
            print("*ERR* bad correlation number, max=%i" %
                  data.res_file.get_nbr_results())
            return False

        if zdata and not data.well_list.wells_data_exists(zdata):
            print("*ERR* no %s data in wells" % zdata)
            return False

        res = data.res_file.get_result_full_path(cor_num)
        if 1 < max_line < len(res):
            factor = float(len(res) - 1) / float(max_line - 1)
            res = list(
                res[int(float(i) * factor)]
                for i in range(max_line)
            )

        well_names = data.well_names()
        depths = data.get_zdatas(zdata)
        import csv
        with open(csv_file, 'w', newline='') as f:
            writer = csv.writer(f)

            for nline, line in enumerate(res):
                for n, v in enumerate(line):
                    writer.writerow(
                        (well_names[n], marker_name % nline, depths[n][v]))

        return True

    @classmethod
    def main(cls, params=None):
        import argparse
        parser = argparse.ArgumentParser(
            description='Create a csv file from a correlation')
        parser.add_argument('res_file')
        parser.add_argument('well_list')
        parser.add_argument('--csv_file', '-o', default="result.csv",
                            help='csv file name (result.csv)')
        parser.add_argument('--z-prop', '-z', help="Depth property")
        parser.add_argument('--max-line', '-m', type=int, default=0,
                            help="maximum number of lines")
        parser.add_argument('--cor-num', '-c', type=int, default=0,
                            help="Correlation number")
        parser.add_argument('--marker-name', '-n', default="M",
                            help="Start of marker name (default:M)")

        args = parser.parse_args(params)
        cls.run(args.res_file, args.well_list, csv_file=args.csv_file,
                zdata=args.z_prop, max_line=args.max_line,
                cor_num=args.cor_num, marker_name=args.marker_name)


main = Res2CSV.main
if __name__ == '__main__':
    Res2CSV.main()
