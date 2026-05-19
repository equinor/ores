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


class Res2LAS:
    data_hdr = (
        ('DEPTH', 'M', '', ''),
        ('RGTMI', 'T/T', '', 'Relative Geological Age Min'),
        ('RGTMA', 'T/T', '', 'Relative Geological Age Max'),
    )

    @classmethod
    def run(cls, res_file, well_list, las_file="well_", cor_num=0, zdata=None, rgtnorm=False):

        data = ResAndWL(res_file, well_list)

        if not data.check():
            print("*ERR* bad input files")
            return False

        if cor_num < 0 or cor_num >= data.res_file.get_nbr_results():
            print("*ERR* bad correlation number, max=%i" % data.res_file.get_nbr_results())
            return False

        if zdata and not data.well_list.wells_data_exists(zdata):
            print("*ERR* no %s data in wells" % zdata)
            return False

        from lasfile import las_write

        res = data.res_file.get_result_full_path(cor_num)
        depths = data.get_zdatas(zdata)

        if rgtnorm:
            rgt_factor = 1. / float(len(res) - 1)
        else:
            rgt_factor = 1.

        for n, well_id in enumerate(data.res_file.well_id):
            well = data.well_list.wells[well_id]
            depth = depths[n]
            prev = -1
            las_data = []
            for lv, v in enumerate(res):
                v = v[n]
                if v != prev:
                    assert v == prev + 1
                    prev = v
                    las_data.append([lv, lv])
                else:
                    las_data[-1][1] += 1
            assert len(las_data) == well.size

            well_data = list((depth[z], rgt_factor * float(d[0]), rgt_factor * float(d[1]))
                             for z, d in enumerate(las_data)
                             )

            las_write(las_file + '%03i.las' % n, well.name, cls.data_hdr, well_data)
        return True

    @classmethod
    def main(cls, params=None):
        import argparse
        parser = argparse.ArgumentParser(description='Create las files from a correlation (DEPTH ,RGTMI,RGTMA)')
        parser.add_argument('res_file', help='res file')
        parser.add_argument('well_list', help='well list file')
        parser.add_argument('--las_file', '-o', default="well_", help='star of las file name (well_)')
        parser.add_argument('--z-prop', '-z', help="Depth property")
        parser.add_argument('--cor-num', '-c', type=int, default=0, help="Correlation number")
        parser.add_argument('--rgt-norm', '-n', action="store_true", help="Normalyse RGT from 0 to 1.")

        args = parser.parse_args(params)
        cls.run(args.res_file, args.well_list, las_file=args.las_file, zdata=args.z_prop,
                cor_num=args.cor_num, rgtnorm=args.rgt_norm)


main = Res2LAS.main
if __name__ == '__main__':
    Res2LAS.main()
