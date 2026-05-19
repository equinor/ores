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

import re
from typing import Optional


class _LASSection:
    def __init__(self):
        self.data = []

    def get_value(self, name, default=None):
        for line in self.data:
            if line[0] == name:
                return line[2]
        return default

    def get_float_value(self, name, default=None):
        for line in self.data:
            if line[0] == name:
                return float(line[2])
        return default

    def get_index(self, name):
        for n, c in enumerate(self.data):
            if name == c[0]:
                return n
        return -1


class LASFile:
    #: NULL value (No Data Value)
    null: Optional[float] = None

    #: STRT value (Well Start)
    strt: Optional[float] = None

    #: STOP value (Well End)
    stop: Optional[float] = None

    #: STEP value
    step: Optional[float] = None

    #: Well name
    well_name: str = None

    #: Well data
    data: list = None

    #: XCOORD
    xcoord: float = 0.

    #: YCOORD
    ycoord: float = 0.

    _sec_line_re = re.compile(
        r'^\s*(\S+)\s*\.(\S*)\s+([^:]*?)\s*:\s*(.*?)\s*$')

    def __init__(self, filename=None):
        self.version = _LASSection()
        self.well = _LASSection()
        self.curve = _LASSection()
        self.parameter = _LASSection()
        self.other = []

        if filename:
            self.read(filename)

    def read(self, filename):
        f = open(filename)
        line = f.readline().rstrip()

        def read_section(section):
            while True:
                rsline = f.readline().rstrip()
                if rsline.startswith('#'):
                    continue
                if rsline.startswith('~'):
                    return rsline

                if not rsline:
                    continue

                rr = self._sec_line_re.match(rsline)
                if not rr:
                    raise Exception('Bad section line %s' % repr(rsline))

                section.data.append(tuple(rr.groups()))

        # read headers

        while True:
            if line.startswith('#'):
                line = f.readline().rstrip()
                continue

            if not line.startswith('~'):
                raise Exception("Section Needed")

            section_name = line[1:2]
            if section_name == "V":
                line = read_section(self.version)
            elif section_name == "W":
                line = read_section(self.well)
            elif section_name == "P":
                line = read_section(self.parameter)
            elif section_name == "C":
                line = read_section(self.curve)
            elif section_name == "O":
                while True:
                    line = f.readline().rstrip()
                    if line.startswith('#'):
                        continue
                    if line.startswith('~'):
                        break
                    self.other.append(line)
            elif section_name == "A":
                break

            else:
                raise Exception('Bad section ' + line)

        # read data
        wrap = self.version.get_value('WRAP', 'NO') == 'YES'
        if wrap:
            ndata = len(self.curve.data)
            tdata = []
            self.data = []
            for i in f:
                tdata.extend(map(float, i.strip().split()))
                if len(tdata) >= ndata:
                    self.data.append(tuple(tdata[:ndata]))
                    del tdata[:ndata]

        else:
            self.data = list(
                tuple(map(float, i.strip().split()))
                for i in f
                if i.strip()
            )

        self.null = self.well.get_float_value('NULL')
        self.strt = self.well.get_float_value('STRT', 0.)
        self.stop = self.well.get_float_value('STOP', 0.)
        self.step = self.well.get_float_value('STEP', 0.)
        self.well_name = self.well.get_value('WELL')
        self.xcoord = self.well.get_float_value('XCOORD', 0.)
        self.ycoord = self.well.get_float_value('YCOORD', 0.)

    def get_curve_index(self, name):
        """return curve index or -1 if not found"""
        return self.curve.get_index(name)

    def get_all_curves_name(self):
        """return a tuple with all curves name"""
        return tuple(i[0] for i in self.curve.data)

    def get_curve(self, name):
        idx = self.get_curve_index(name)
        return list(i[idx] for i in self.data)


def las_write(file_name, well_name, data_hdr, data, info=()):
    frmt = '%-5s.%-5s %15s:  %s\n'
    with open(file_name, "w") as f:
        f.write("~Version Information Block\n")
        f.write(frmt % (
            "VERS", '', "2.00", "CWLS LOG ASCII STANDARD - VERSION 2.0"))
        f.write(frmt % ("WRAP", '', "NO", "One line per depth step"))
        f.write('~Well Information Block\n')
        f.write(frmt % ("STRT", 'M', data[0][0], "START DEPTH"))
        f.write(frmt % ("STOP", 'M', data[-1][0], "STOP DEPTH"))
        f.write(frmt % ("STEP", 'M', data[1][0] - data[0][0], "STEP"))
        f.write(frmt % ("WELL", '', well_name, "WELL NAME"))
        for i in info:
            f.write(frmt % i)
        f.write('~Curve Information Block\n')
        for i in data_hdr:
            f.write(frmt % i)

        f.write('~A%13s' % data_hdr[0][0])
        for i in data_hdr[1:]:
            f.write(' %15s' % i[0])
        f.write('\n')
        for i in data:
            f.write(' '.join('%15s' % j for j in i))
            f.write('\n')
