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

from typing import Tuple, List, Dict, Sequence, Optional
import re

import numpy as np


class Reader:
    max_version = 2

    def __init__(self, filename):
        self.version = None
        self._file = open(filename)
        self._buf = None

    def get(self):
        while not self._buf:
            line = self._file.readline().strip()
            if not line or line[0] == "#":
                continue
            line = list(line.split())
            if line:
                self._buf = line

        return self._buf.pop(0)

    def get_int(self):
        return int(self.get())

    def get_float(self):
        return float(self.get())

    def read_header(self, name):
        h1 = self.get()
        h2 = self.get()
        if h1 != "WeCo" or h2 != name:
            return False
        self.version = self.get_int()
        if self.version < 1 or self.version > self.max_version:
            return False
        return True


class Well:
    #: well name
    name: str = None

    #: well size (numbers of markers)
    size: int = 0

    #: well x position
    x: float = 0.

    #: well y position
    y: float = 0.

    #: well x position
    z: float = 0.

    #: well length (distance)
    h: float = 0.

    #: well data
    data: Dict[str, Sequence[float]]

    def __init__(self, name=None, reader=None):
        self.name = name or 'NoName'
        self.data = dict()
        self.region = dict()
        self.meta = dict()  # per-channel metadata: {name: {uom, kind, ...}}

        if reader:
            self._read(reader)

    def _read(self, reader):
        self.name = reader.get()
        # Handle quoted well names (spaces allowed)
        if self.name.startswith('"'):
            while not self.name.endswith('"'):
                self.name += " " + reader.get()
            self.name = self.name.strip('"')
        self.size = reader.get_int()
        self.x = reader.get_float()
        self.y = reader.get_float()
        self.z = reader.get_float()
        self.h = reader.get_float()

        # data
        self.data = dict()
        for i in range(reader.get_int()):
            data_name = reader.get()
            data_size = reader.get_int()
            data = tuple(reader.get_float() for _ in range(data_size))
            self.data[data_name] = data

        # regions
        if reader.version >= 2:
            for i in range(reader.get_int()):
                region_name = reader.get()
                region_size = reader.get_int()
                data = tuple(
                    (reader.get_int(), reader.get_int(), reader.get_int()) for
                    _ in range(region_size))
                self.region[region_name] = data

    def _write(self, f):
        # Quote well name if it contains spaces
        name = '"%s"' % self.name if ' ' in self.name else self.name
        f.write('%s\n%i\n' % (name, self.size))
        f.write('%f %f %f %f\n' % (self.x, self.y, self.z, self.h))
        # data
        # f.write("#data\n%i\n" % len(self.data))
        f.write("%i\n" % len(self.data))
        for name, values in self.data.items():
            f.write("%s %i\n" % (name, len(values)))
            for i in values:
                f.write('%f\n' % i)

        f.write("%i\n" % len(self.region))
        for name, values in self.region.items():
            f.write("%s %i\n" % (name, len(values)))
            for i in values:
                f.write('%i %i %i\n' % i)

    def add_data(self, name, *values):
        if len(values) == 1:
            self.data[name] = tuple(values[0])
        else:
            self.data[name] = tuple(values)
        return self

    def add_data_from_region(self, region_name: str, data_name: Optional[str] = None, default: float = 0.) -> bool:
        """
        Create data from region data.

        :param region_name: region name
        :param data_name: new data name, if None,use region_name
        :param default: default value (in no region)
        :return: False in case of failure
        """
        if region_name not in self.region:
            print(f"*ERR* Cannot fine region {region_name} in well {self.name} ")
            return False
        data = [default] * self.size
        for rid, start, lgr in self.region[region_name]:
            for i in range(start, start + lgr):
                if 0 <= i < self.size:
                    data[i] = float(rid)
        self.add_data(data_name or region_name, data)
        return True

    def add_region_from_data(self, data_name: str, region_name: Optional[str] = None, ignore_zero: bool = True) -> bool:
        """
        Create region form data

        Warning: negative values are added after positive ones (region id must be >=0)

        :param region_name: new region name (default: data_name)
        :param data_name: data name
        :param ignore_zero:
        :return: False in case of failure
        """
        if data_name not in self.data:
            print(f"*ERR* Cannot find data {data_name} in well {self.name} ")
            return False
        data: list[int] = list(map(int, self.data[data_name]))
        last_value = max(0, max(data))
        region = list()
        reg_start = 0
        reg_value = data[0]
        reg_len = 1

        def add():
            if ignore_zero and reg_value == 0:
                return
            region.append((
                (reg_value if reg_value >= 0 else last_value - reg_value)
                , reg_start
                , reg_len
            ))

        for pos, v in enumerate(data[1:]):
            if v != reg_value:
                add()
                reg_start = pos + 1
                reg_len = 1
                reg_value = v
            else:
                reg_len += 1
        add()
        self.add_region(region_name or data_name, region)
        return True

    def add_derivative(self, curve_name: str, derivative_name: Optional[str] = None) -> bool:
        """
        Computes the derivative of a curve and adds is as a new curve.
        """
        if curve_name not in self.data:
            print(f"*ERR* Cannot find curve {curve_name} in well {self.name} to compute derivative")
            return False
        values = self.data[curve_name]
        derivatives = np.gradient(values)
        self.add_data((curve_name + '_derivative') if derivative_name is None else derivative_name, tuple(derivatives))
        return True

    def add_region(self, name, *p):
        if len(p) == 1 and isinstance(p[0], (tuple, list)) and (
                len(p[0]) == 0 or isinstance(p[0][0], (tuple, list))):
            regions = tuple(p[0])
        else:
            regions = tuple(p)

        for i in regions:
            if len(i) != 3:
                print('*ERR* bad region')
        self.region[name] = regions
        return self

    def get_zdata(self, depth_prop=None):
        """
        get depth from data or as float from 0. to 1. if not depth_prop
        :param depth_prop:
        :return: list of depths
        """

        if depth_prop:
            return self.data[depth_prop]

        return list(float(i) / float(self.size - 1) for i in range(self.size))


class WellList:
    wells: List[Well] = None

    def __init__(self, filename=None):
        self.wells = []

        if filename:
            self.read(filename)

    def nbr_wells(self):
        return len(self.wells)

    def write(self, filename):
        f = open(filename, "w")
        f.write('WeCo WellList %i\n' % Reader.max_version)
        f.write("%i\n" % self.nbr_wells())
        for i in self.wells:
            # noinspection PyProtectedMember
            i._write(f)
        f.write("END\n")

    def clear(self):
        self.wells = []

    def read(self, filename) -> bool:

        self.clear()
        reader = Reader(filename)

        if not reader.read_header("WellList"):
            print("*ERR* bad file type")
            self.clear()
            return False

        nbr_well = reader.get_int()
        self.wells = list(Well(reader=reader) for _ in range(nbr_well))

        if reader.get() != "END":
            print("*ERR* END missing")
            self.clear()
            return False
        return True

    def add_well(self, well: Well):
        assert isinstance(well, Well)
        self.wells.append(well)

    def create_well(self, well_name, **pp) -> Well:
        well = Well(well_name)
        self.add_well(well)
        for k, v in pp.items():
            assert hasattr(well, k), "No %s attribute in well" % k
            setattr(well, k, v)
        return well

    def wells_data_exists(self, name) -> bool:
        """check if data exist for every wells"""
        for well in self.wells:
            if name not in well.data:
                return False
        return True

    def get_well(self, name_or_id, default=None) -> Well:
        for well in self.wells:
            if well.name == name_or_id:
                return well
        try:
            num = int(name_or_id)
        except ValueError:
            return default
        if 0 <= num < self.nbr_wells():
            return self.wells[num]
        return default

    def get_data_names(self) -> list:
        """
        return list of data presents in every wells
        """
        if not self.wells:
            return []
        res = set(self.wells[0].data.keys())
        for well in self.wells[1:]:
            res &= set(well.data.keys())
        return list(sorted(res))

    def get_region_names(self) -> list:
        """
        return list of region list presents in every wells
        """
        if not self.wells:
            return []
        res = set(self.wells[0].region.keys())
        for well in self.wells[1:]:
            res &= set(well.region.keys())
        return list(sorted(res))

    def add_data_from_region(self, region_name: str, data_name: Optional[str] = None, default: float = 0.):
        """
        call Well.add_data_from_region for each wells
        """
        for well in self.wells:
            well.add_data_from_region(region_name, data_name, default)

    def add_region_from_data(self, data_name: str, region_name: Optional[str] = None, ignore_zero: bool = True) -> bool:
        """
        call Well.add_region_from_data for each wells
        """
        ok = True
        for well in self.wells:
            if not well.add_region_from_data(data_name, region_name, ignore_zero):
                ok = False
        return ok


class _CorrelationView:
    """Lightweight proxy exposing a single n-best path from a :class:`ResFile`.

    Used by the AI modules (:mod:`weco.ai.quality`, :mod:`weco.ai.uncertainty`,
    :mod:`weco.ai.anomaly`) which expect ``res_file.cor(i)`` to return an
    object with ``.cost`` and ``.get_well_markers(wi)``.
    """

    __slots__ = ("_res", "_idx", "cost")

    def __init__(self, res_file: "ResFile", idx: int):
        self._res = res_file
        self._idx = idx
        self.cost = res_file.get_result_cost(idx)

    def get_well_markers(self, wi: int):
        """Return a list of marker indices for well *wi* along this path."""
        path = self._res.get_result_full_path(self._idx)
        return [node[wi] for node in path]


class ResFile:
    re_wellids = re.compile(r"^WellIds:\s*(\d+(?:\s+\d+)+)$")
    re_nodes = re.compile(r"^Node\s+(\d+)\s+\(\s*(\d+(?:\s+\d+)+)\s+\)$")
    re_trans = re.compile(r"^\s+->\s*(\d+)\s*\((.*)\)$")

    well_id: Sequence[int] = None

    def __init__(self, filename=None, build_list=True, reorder=False):
        self.well_id = ()
        self.well_size = ()
        self.nodes = ()
        self.backward_trans = ()
        self.forward_trans = ()
        self.cost = dict()
        self.size = 0
        self.paths = ()
        self.results = []
        if filename:
            self.read(filename, build_list, reorder)

    def clear(self):
        self.well_id = ()
        self.well_size = ()
        self.nodes = ()
        self.backward_trans = ()
        self.forward_trans = ()
        self.cost = dict()
        self.size = 0
        self.paths = ()
        self.results = []

    def read(self, filename, build_list=True, reorder=False):
        self.clear()
        nodes = []
        trans = []
        cur_trans = []
        ftrans = []
        cost = dict()
        cur_node = -1

        with open(filename) as file:
            for line in file:
                line = line.rstrip()
                if not line:
                    continue

                match = self.re_trans.match(line)
                if match:
                    dst = int(match.group(1))
                    cost_value = float(match.group(2))
                    cur_trans.append(dst)
                    ftrans[dst].append(cur_node)
                    cost[(dst, cur_node)] = cost_value
                    continue
                match = self.re_nodes.match(line)
                if match:
                    num = int(match.group(1))
                    assert num == len(nodes), "Bad node ordering"
                    cur_node = num
                    nodes.append(tuple(map(int, match.group(2).split())))
                    cur_trans = list()
                    trans.append(cur_trans)
                    ftrans.append([])
                    continue
                match = self.re_wellids.match(line)
                if match:
                    self.well_id = tuple(map(int, match.group(1).split()))
                    continue

        self.nodes = tuple(nodes)
        # noinspection PyTypeChecker
        self.backward_trans = tuple(map(tuple, trans))
        self.forward_trans = tuple(map(tuple, ftrans))
        self.cost = cost
        self.size = len(self.nodes)
        self.well_size = tuple(
            1 + max(v[i] for v in nodes)
            for i in range(len(self.well_id))
        )

        if reorder:
            self.reorder()

        if build_list:
            self.build_list()

    def wellid2index(self, wi):
        """
        return index of a well id
        :param wi: well_id
        :return: index or -1 if not found
        """
        for n, i in enumerate(self.well_id):
            if i == wi:
                return n
        return -1

    def reorder(self):
        order_list = list((v, n) for n, v in enumerate(self.well_id))
        order_list.sort()
        new_well_id = tuple(sorted(self.well_id))
        if new_well_id == self.well_id:
            # nothing to do
            return
        table = list(
            v for _, v in sorted((b, a) for a, b in enumerate(self.well_id)))
        self.nodes = tuple(
            tuple(n[i] for i in table)
            for n in self.nodes
        )
        self.well_id = new_well_id

    def build_list(self):
        if not self.size:
            return

        back_res = [None] * self.size
        # noinspection PyTypeChecker
        back_res[-1] = ((0., (self.size - 1,)),)

        for n in range(self.size - 2, -1, -1):
            res = []
            for dst in self.forward_trans[n]:
                trans_cost = self.cost[(n, dst)]
                for cost, path in back_res[dst]:
                    res.append((cost + trans_cost, (n,) + path))
            # noinspection PyTypeChecker
            back_res[n] = res
        # noinspection PyUnresolvedReferences
        back_res[0].sort()
        self.results = back_res[0]

    def get_nbr_results(self):
        return len(self.results)

    def get_result_cost(self, n):
        return self.results[n][0]

    def nbr_well(self):
        return len(self.well_id)

    def get_result_full_path(self, n):
        return tuple(
            self.nodes[i]
            for i in self.results[n][1]
        )

    # ------------------------------------------------------------------
    #  Compatibility layer for AI modules (quality, uncertainty, anomaly)
    # ------------------------------------------------------------------

    def nbr_cor(self):
        """Alias for :meth:`get_nbr_results` (AI module compatibility)."""
        return self.get_nbr_results()

    def cor(self, n):
        """Return a lightweight correlation-path view for path *n*.

        The returned object has:
        - ``.cost`` — total path cost
        - ``.get_well_markers(wi)`` — list of marker indices for well *wi*

        This adapter bridges the engine's ``ResFile`` to the interface
        expected by :mod:`weco.ai.quality`, :mod:`weco.ai.uncertainty`,
        and :mod:`weco.ai.anomaly`.
        """
        if n < 0 or n >= len(self.results):
            return None
        return _CorrelationView(self, n)

    def well_id_map(self) -> Tuple[int, ...]:
        """
        well_id_map()[well_id] = index in result
        """
        res = [-1] * (max(self.well_id) + 1)
        for idx, wid in enumerate(self.well_id):
            res[wid] = idx
        return tuple(res)

    def write(self, filename: str) -> None:
        """Write the correlation graph to a native WeCo result file.

        The format mirrors the one produced by the C++ engine and
        parsed by :meth:`read`::

            WellIds: 0 1 2
            Node 0 ( 0 0 0 )
            Node 1 ( 1 1 1 )
              -> 0 (0.123456)
            ...

        Parameters
        ----------
        filename : str
            Output file path.
        """
        with open(filename, "w") as fh:
            # WellIds header
            fh.write("WellIds: " + " ".join(str(w) for w in self.well_id) + "\n")
            # Nodes + backward transitions
            for nid in range(self.size):
                markers = " ".join(str(m) for m in self.nodes[nid])
                fh.write(f"Node {nid} ( {markers} )\n")
                for dst in self.backward_trans[nid]:
                    c = self.cost.get((dst, nid), 0.0)
                    fh.write(f"  -> {dst} ({c:g})\n")

    def copy(self) -> "ResFile":
        """Return a deep copy of this ResFile."""
        rf = ResFile()
        rf.well_id = tuple(self.well_id)
        rf.well_size = tuple(self.well_size)
        rf.nodes = tuple(self.nodes)
        rf.backward_trans = tuple(self.backward_trans)
        rf.forward_trans = tuple(self.forward_trans)
        rf.cost = dict(self.cost)
        rf.size = self.size
        rf.paths = tuple(self.paths)
        rf.results = list(self.results)
        return rf


class ResAndWL:
    """WellList + ResFile"""
    well_list = None
    res_file = None

    def __init__(self, res_file=None, well_list=None):
        self.set_well_list(well_list)
        self.set_res_file(res_file)

    def set_well_list(self, wl):
        if wl is None:
            return
        if isinstance(wl, WellList):
            self.well_list = wl
            return
        self.well_list = WellList(wl)

    def set_res_file(self, rf):
        if rf is None:
            return
        if isinstance(rf, ResFile):
            self.res_file = rf
            return
        self.res_file = ResFile(rf)

    def ok(self):
        return (self.res_file is not None
                and self.well_list is not None
                )

    def check(self):
        if not self.ok():
            return False
        if max(self.res_file.well_id) >= self.well_list.nbr_wells():
            return False
        return True

    def well_name(self, n):
        """ get well name from index in result """
        return self.well_list.wells[self.res_file.well_id[n]].name

    def well_names(self):
        """ list of well_name from index in result """
        return list(self.well_name(i) for i in range(self.res_file.nbr_well()))

    def get_zdatas(self, prop=None):
        """
        call get_zdata for each well in res_file.well_id
        """
        return list(self.well_list.wells[n].get_zdata(prop) for n in
                    self.res_file.well_id)


class BaseChecker:
    """
    Bas class for checker
    """
    _error = None

    def set_error(self, error):
        if not self._error:
            self._error = error

    def error(self):
        return self._error

    def ok(self):
        return self._error is None

    def print_check_result(self, check_name):
        if self.ok():
            print("Check", check_name, ": Ok")
            return True
        print("Check", check_name, "Failled :", self.error())
        return False


class WellListChecker(BaseChecker):
    """
    Cheker for WellList
    """

    def __init__(self, well_list):
        """

        :param well_list: WellList instance or file name

        """
        try:
            self.well_list = well_list if isinstance(well_list,
                                                     WellList) else WellList(
                well_list)
        except Exception as err:
            self.set_error("Read Error:" + str(err))
            return
        if not self.well_list.wells:
            self.set_error("No Wells")

    def data_exists(self, name):
        """check if data exist for every wells"""
        if not self.well_list.wells_data_exists(name):
            self.set_error('Data %s missing in some wells' % name)
            return False
        return self.ok()

    def valid_data(self, name):
        """check if data exist for every well and it's size is >= well size"""
        for well in self.well_list.wells:
            if name not in well.data:
                self.set_error('Data %s missing in some wells' % name)
                return False
            if len(well.data[name]) < well.size:
                self.set_error('Data %s too short' % name)
                return False
        return self.ok()

    def region_exists(self, name):
        """check if region exist for every wells"""
        for well in self.well_list.wells:
            if name not in well.region:
                self.set_error('Region %s missing in some wells')
                break
        return self.ok()


class ResFileChecker(BaseChecker):
    """
    res file check
    """

    def __init__(self, res_file: ResFile):
        self._res_file = res_file
        if not self._res_file.get_nbr_results():
            self.set_error("No results")

    def order_check(self):
        """
        check result order
        :return: True if ok
        """
        for res_num in range(self._res_file.get_nbr_results()):
            prev = (0,) * self._res_file.size
            res = self._res_file.get_result_full_path(res_num)
            for i in res:
                for a, b in zip(prev, i):
                    if a > b:
                        self.set_error("Bad order in result %i" % res_num)
                        return False
                prev = i
        return self.ok()


# =====================================================================
#  CostMatrix
# =====================================================================

class CostMatrix:
    """
    CostMatrix Data (from cost-matrix option)

    note:
       cost is -1 for forbidden transitions
    """

    _wells1 = ()
    _wells2 = ()

    _data = []  # raw data from file

    _accumulator = dict()

    def __init__(self, filename=None):
        """
        :param filename: cost matrix file name
        """
        self.read(filename)

    def read(self, filename=None):
        """
        read a file

        :param filename: file name
        """
        self.clear()
        if not filename:
            return
        with open(filename) as infile:
            # header = wells_id1 wells_id2
            header = infile.readline().rstrip()
            wells1, wells2 = header.split()
            self._wells1 = tuple(map(int, wells1.strip().split("-")))
            self._wells2 = tuple(map(int, wells2.strip().split("-")))

            for line in infile:
                # lines : source destination cost
                # cost = -1 => forbidden transition
                source, destination, cost = line.split()
                source = tuple(map(int, source.split("-")))
                destination = tuple(map(int, destination.split("-")))
                cost = float(cost)
                self._data.append((source, destination, cost))

    def clear(self):
        """
        Clear data
        """
        self._wells1 = ()
        self._wells2 = ()
        self._data = []

    def wells1(self):
        """Wells in first part"""
        return self._wells1

    def wells2(self):
        """Wells in second part"""
        return self._wells2

    def wells(self):
        """All Wells"""
        return self._wells1 + self._wells2

    def well_size(self, well_index):
        """
        :return: well size from well_index (not well_id)
        """
        return 1 + max(dest[well_index] for _, dest, _ in self._data)

    def get_tuple_dest(self, well1, well2):
        """
        extract values with well1 and well2

        ignore source

        :param well1: first well id
        :param well2: second well id
        :return: list of ((state1 ,state2),cost)
        """
        return dict(self.get_iter_dest(well1, well2))

    def get_dict_dest(self, well1, well2):
        """
        extract values with well1 and well2

        ignore source

        :param well1: first well id
        :param well2: second well id
        :return: dict of (state1 ,state2) -> cost
        """
        return dict(self.get_iter_dest(well1, well2))

    def get_matrix_dest(self, well1, well2):
        """
        extract values with well1 and well2

        ignore source

        -1.: forbidden
        -2.: no info

        :param well1: first well id
        :param well2: second well id
        :return: cost matrix
        """

        size1 = self.well_size(well1)
        size2 = self.well_size(well2)
        result = list(list(-2. for _ in range(size2)) for _ in range(size1))
        for (s1, s2), cost in self.get_iter_dest(well1, well2):
            result[s1][s2] = cost
        return result

    def get_array_dest(self, well1, well2):
        """
        extract values with well1 and well2

        ignore source

        -1.: forbidden
        -2.: no info

        :param well1: first well id
        :param well2: second well id
        :return: cost matrix as np.array
        """

        size1 = self.well_size(well1)
        size2 = self.well_size(well2)
        result = np.full((size1, size2), -2.)
        for (s1, s2), cost in self.get_iter_dest(well1, well2):
            result[s1, s2] = cost
        return result

    def get_iter_dest(self, well1, well2):
        """
        extract values with well1 and well2

        ignore source

        :param well1: first well id
        :param well2: second well id
        :return: iterator of (state1 ,state2) , cost
        """
        assert well1 in self.wells() and well2 in self.wells()
        index1 = self.wells().index(well1)
        index2 = self.wells().index(well2)
        return self._cost_map(
            lambda _, dest: (dest[index1], dest[index2])
        )

    def get_iter_full(self, well1, well2):
        """
        extract values with well1 and well2

        :param well1: first well id
        :param well2: second well id
        :return: iterator of ((src1,src2),(dst1,dst2)) , cost
        """
        assert well1 in self.wells() and well2 in self.wells()
        index1 = self.wells().index(well1)
        index2 = self.wells().index(well2)
        return self._cost_map(
            lambda src, dest: (
                (src[index1], src[index2]), (dest[index1], dest[index2]))
        )

    def get_tuple_full(self, well1, well2):
        """
        extract values with well1 and well2

        :param well1: first well id
        :param well2: second well id
        :return: tuple of ((src1,src2),(dst1,dst2)) , cost
        """
        return tuple(self.get_iter_full(well1, well2))

    def get_dict_full(self, well1, well2):
        """
        extract values with well1 and well2

        :param well1: first well id
        :param well2: second well id
        :return: dict of ((src1,src2),(dst1,dst2)) -> cost
        """
        return dict(self.get_iter_full(well1, well2))

    def _cost_map(self, map_function):
        tmp_dict = dict()
        for source, destination, cost in self._data:
            key = map_function(source, destination)
            if key is None:
                continue
            if cost < 0.:
                if key not in tmp_dict:
                    tmp_dict[key] = (0, 0.)
            elif key in tmp_dict:
                n, c = tmp_dict[key]
                tmp_dict[key] = (n + 1, c + cost)
            else:
                tmp_dict[key] = (1, cost)
        return ((key,
                 value / float(nbr) if nbr else -1.
                 ) for key, (nbr, value) in tmp_dict.items()
                )

    def csv_dest(self, well1, well2, out_file, no_header=False):
        """
        Write matrix in a csv file

        ignore source

        :param well1: first well id
        :param well2: second well id
        :param out_file: out file name
        :param no_header: no file header
        """
        import csv
        with open(out_file, 'w', newline='') as file:
            writer = csv.writer(file)
            if not no_header:
                writer.writerow(('well1', 'well2', 'cost'))
            for (s1, s2), cost in self.get_iter_dest(well1, well2):
                writer.writerow((s1, s2, cost))

    def csv_full(self, well1, well2, out_file, no_header=False):
        """
        Write matrix in a csv file

        :param well1: first well id
        :param well2: second well id
        :param out_file: out file name
        :param no_header: no file header
        """
        import csv
        with open(out_file, 'w', newline='') as file:
            writer = csv.writer(file)
            if not no_header:
                writer.writerow(('src1', 'src2', "dst1", 'dst2', 'cost'))
            for ((s1, s2), (d1, d2)), cost in self.get_iter_full(well1, well2):
                writer.writerow((s1, s2, d1, d2, cost))


def weco_cm2csv_main():
    """
    Main function for WeCoCM2Csv
    """
    import argparse
    parser = argparse.ArgumentParser(
        description='Create a csv file from a cost matrix file')
    parser.add_argument('cm_file',
                        help="Cost Matrix file (from cost-matrix option)")
    parser.add_argument('out_file', default="cost_matrix.csv",
                        help='csv file name', nargs="?")
    parser.add_argument('--well1', '-1', help='first well id', type=int,
                        default=-1)
    parser.add_argument('--well2', '-2', help='second well id', type=int,
                        default=-1)
    parser.add_argument('--dest-only', '-d', action="store_true",
                        help="ignore transition source")
    parser.add_argument('--no-header', '-H', action="store_true",
                        help="Remove header in csv file")
    args = parser.parse_args()

    try:
        cost_matrix = CostMatrix(args.cm_file)
    except Exception as err:
        print(f"*ERR* can't read cost matrix file {args.cm_file} : {err}")
        return

    if args.well1 < 0:
        args.well1 = cost_matrix.wells1()[0]
    elif args.well1 not in cost_matrix.wells():
        print(f"*ERR* Invalid well id {args.well1}")

    if args.well2 < 0:
        args.well2 = cost_matrix.wells2()[0]
    elif args.well2 not in cost_matrix.wells():
        print(f"*ERR* Invalid well id {args.well2}")

    if args.dest_only:
        cost_matrix.csv_dest(args.well1, args.well2, args.out_file,
                             no_header=args.no_header)
    else:
        cost_matrix.csv_full(args.well1, args.well2, args.out_file,
                             no_header=args.no_header)
