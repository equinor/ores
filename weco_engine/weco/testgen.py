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

"""
WeCo Test Generation

"""
from math import sin, pi
from random import uniform, randrange

from .data import WellList


class TestBuilder:
    @classmethod
    def pack_region(cls, lst):
        prev = 0
        pos = 0
        nbr = 0
        res = []
        for i in lst:
            if i == prev:
                nbr += 1
            else:
                if prev:
                    res.append((prev, pos - nbr, nbr))
                prev = i
                nbr = 1
            pos += 1
        if nbr and prev:
            res.append((prev, pos - nbr, nbr))
        return res

    @classmethod
    def get_noise(cls, amplitude: float):
        """

        :param amplitude:
        :return:
        """
        return uniform(-amplitude, amplitude)

    # ================ data ==============================
    @classmethod
    def sin_data(cls, size: int, wave_length: float = 10.,
                 amplitude: float = 1., noise: float = 0., shift: float = 0.):
        """

        :param size: number of value generated
        :param wave_length: sinus wave length v[n] == v[n+wave_length]
        :param amplitude: amplitude of values [-amplitude, +amplitude]
        :param noise: add blank noise [-amplitude*noise , +ampllitude*noise]
        :param shift: shift [O.,1.]
        :return: list of float
        """
        noise *= amplitude
        wave_length = 2. * pi / wave_length
        shift = shift * 2. * pi

        return list(
            sin(wave_length * float(i) + shift) * amplitude + cls.get_noise(
                noise) for i in range(size))

    def add_sin_data(self, name, size=None, **__argv):
        return self.add_data(name, self.sin_data(size or self.size, **__argv))

    def add_data(self, name, values):
        self.datas.append((name, values))
        return self

    def add_depth_data(self, name="depth", size=None):
        return self.add_data(name, list(range(size or self.size)))

    # ======================== regions ====================
    @classmethod
    def region1(cls, size: int, _max: int, _min: int = 1):
        p = 0
        res = []
        n = 1
        while True:
            s = min(size - p, randrange(_min, _max))
            res += [n] * s
            p += s
            if p >= size:
                break
            if (size - p) < _min:
                res += [n] * (size - p)
                break
            n += 1
        assert len(res) == size
        return res

    def add_region1(self, name, _max: int = 1, _min: int = 1, size=None):
        return self.add_region(name,
                               self.region1(size or self.size, _max, _min))

    def add_region(self, name, values):
        self.regions.append((name, values))
        return self

    # ======================== init ====================
    def __init__(self, nbr_wells=5, size=100):
        self.size = size
        self.min_size = size // 5
        self.nbr_wells = nbr_wells
        self.datas = []
        self.regions = []
        self.erode_map = list([True] * size for _ in range(nbr_wells))
        self.well_list = None

    # ================= erode ====================

    def try_erode(self, func, maxtry=5):
        for w in range(self.nbr_wells):
            for _ in range(maxtry):
                save = self.erode_map[w].copy()
                func(self.erode_map[w])
                if self.erode_map[w].count(True) >= self.min_size:
                    break
                self.erode_map[w] = save
        return self

    def erode_start(self, _max, _min=0):
        def f(dta):
            for i in range(min(self.size, randrange(_min, _max))):
                dta[i] = False

        return self.try_erode(f)

    def erode_end(self, _max, _min=0):
        def f(dta):
            for i in range(min(self.size, randrange(_min, _max))):
                dta[-1 - i] = False

        return self.try_erode(f)

    def erode_parts(self, _nbr, _max=1, _min=1):
        def f(dta):
            s = randrange(_min, _max)
            if s:
                p = randrange(0, self.size - 1 - s)
                for i in range(s):
                    dta[p + i] = False

        for _ in range(_nbr):
            self.try_erode(f)
        return self

    def erode_well(self, well, *p):
        for i in p:
            self.erode_map[well][i] = False
        return self

    def print_erode_map(self):
        for m in self.erode_map:
            print("".join(("-" if i else "_") for i in m))
        return self

    @classmethod
    def erode_data(cls, emap, data):
        return tuple(
            data[i] for i in range(min(len(data), len(emap))) if emap[i])

    @classmethod
    def erode_region(cls, emap, data):
        return cls.pack_region(
            data[i] for i in range(min(len(data), len(emap))) if emap[i])

    # ========= build ==========
    def build(self):
        self.well_list = WellList()

        for i in range(self.nbr_wells):
            w = self.well_list.create_well("well%i" % i,
                                           size=self.erode_map[i].count(True))

            emap = self.erode_map[i]
            for name, data in self.datas:
                w.add_data(name, self.erode_data(emap, data))
            for name, data in self.regions:
                w.add_region(name, self.erode_region(emap, data))

        return self

    # ========== Multi Scale ================
    def multiscale_from_region(self, multiscale_region, source_region=None):
        assert self.well_list
        if not source_region:
            source_region = multiscale_region
        for w in self.well_list.wells:
            # get zones start
            d = list(sorted(i[1] for i in w.region[source_region]))
            if d[0] != 0:
                d.insert(0, 0)
            while d and d[-1] >= w.size - 2:
                del d[-1]
            d.append(w.size - 1)
            prev = d[0]
            num = 0
            r = []
            for last in d[1:]:
                r.append((num, prev, last - prev))
                num += 1
                prev = last
            w.region[multiscale_region] = r
            print(w.size, r)
        return self

    def multiscale_data(self, multiscale_region, multiscale_data,
                        source_data=None):
        if not source_data:
            source_data = multiscale_data
        for w in self.well_list.wells:
            src = w.data[source_data]
            d = list(src[i[1]] for i in w.region[multiscale_region]) + [
                src[w.size - 1]]
            w.data[multiscale_data] = d

        return self

    # ======================
    def add_noise(self, name, noise):
        assert self.well_list
        for w in self.well_list.wells:
            w.data[name] = tuple(
                i + self.get_noise(noise) for i in w.data[name])
        return self

    # =========================
    def wells_add_data(self, name, *datas):
        assert len(datas) == len(self.well_list.wells)
        for data, well in zip(datas, self.well_list.wells):
            well.add_data(name, data)
        return self

    # ========= write ==========
    def write(self, filename):
        assert self.well_list
        self.well_list.write(filename)
        return self
