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

from weco.engine import Project, CCFPart, WellList as EngineWellList
from typing import Union
from weco.engine_data import WellList, well_list_python2engine, cor_graph2res_file, ResFile


class ProjectExt(Project):
    """
    A base class for defining WeCo extensions in Python
    """

    def __init__(self):

        super().__init__()

    def get_option_ext(self, name):
        coption = self.search_option(name)
        if coption is None:
            raise ValueError("Unknown option " + name)
        if coption.type() == 'Int':
            return int(coption.string())
        if coption.type() == 'Float':
            return float(coption.string())
        return coption.string()

    def set_option_ext(self, name, value):
        if not self.set_option_value(name, str(value)):
            if not self.option_exists(name):
                raise ValueError("Unknown option " + name)
            raise ValueError("Bad value for option " + name)

    def set_options_ext(self, __dict=None, **__kwargs):
        if __dict:
            for key, value in __dict.items():
                self.set_option_ext(key.replace("_", "-"), value)

        for key, value in __kwargs.items():
            self.set_option_ext(key.replace("_", "-"), value)

    def run(self, well_list: Union[WellList, EngineWellList, str]) -> bool:
        """
        run engine from a python WellList (`weco.data.WellList`) or an Engine WellList (`weco.engine.WellList`)
        or a file (str)
        """
        if isinstance(well_list, WellList):
            return super().run(well_list_python2engine(well_list))
        return super().run(well_list)

    def get_res_file(self, build_list: bool = True, reorder: bool = True) -> ResFile:
        """
        return result as a data.ResFile

        :param build_list: create results as lists if True
        :param reorder: reorder wells if True
        :return: a ResFile instance
        """
        return cor_graph2res_file(self.result(), build_list, reorder)


class CCFPartExt(CCFPart):
    """
    A base class for accessing information in Python composite cost functions
    """

    class _DataHelper:
        def __init__(self, parent, data_name):
            self.parent = parent
            assert self.parent.init_done()
            self._data = []
            for n in range(self.parent.size()):
                w = self.parent.well(n)
                if not w.data_exists(data_name):
                    raise ValueError("No data " + data_name + " in well")
                d = w.get_data(data_name)
                if d.size() < w.well_size():
                    raise ValueError("Data " + data_name + " too short")
                self._data.append(d)

        def src(self, w):
            """
            Accesses the source data from well index 'w'
            """
            assert 0 <= w < self.parent.size()
            return self._data[w].get(self.parent.src(w))

        def dest(self, w):
            """
            Accesses the destination data from well index 'w'
            """
            assert 0 <= w < self.parent.size()
            return self._data[w].get(self.parent.dest(w))

        def dest_var(self):
            """
            Computes the variance of destination data
            """
            s = 0.
            s2 = 0.
            for i in range(self.parent.size()):
                v = self.dest(i)
                s += v
                s2 += v * v
            float_size = float(self.parent.size())
            s = s / float_size
            return (s2 / float_size) - (s * s)

    class _RegionHelper:
        def __init__(self, parent, region_name):
            self.parent = parent
            assert self.parent.init_done()
            self._data = []
            for n in range(self.parent.size()):
                w = self.parent.well(n)
                if not w.region_list_exists(region_name):
                    raise ValueError("No Region " + region_name + " in well")
                d = w.get_region_list(region_name)
                self._data.append(d)

        def src(self, w):
            assert 0 <= w < self.parent.size()
            return self._data[w].get_region(self.parent.src(w))

        def dest(self, w):
            assert 0 <= w < self.parent.size()
            return self._data[w].get_region(self.parent.dest(w))

    def data_helper(self, name):
        return self._DataHelper(self, name)

    def region_helper(self, name):
        return self._RegionHelper(self, name)


# ═══════════════════════════════════════════════════════════════════════════
# §11.3.4 — WellScheduleExt: declarative merger order specification
# ═══════════════════════════════════════════════════════════════════════════

class WellScheduleExt:
    """Declarative merger-order builder for :class:`ProjectExt`.

    Instead of writing a raw ``CreateTaskFunc`` callback, use this class
    to describe mergers step by step::

        sched = WellScheduleExt()
        sched.merge("W1", "W2")          # first merge
        sched.merge("W1-W2", "W3")       # merge previous result with W3
        project.set_order_func(sched.build())

    The :meth:`build` method returns a callable suitable for
    ``Project.set_order_func()``.
    """

    def __init__(self):
        self._steps: list = []  # list of (name_or_idx_a, name_or_idx_b)

    def merge(self, parent_a, parent_b):
        """Add a merge step between two wells or previously merged groups.

        Parameters
        ----------
        parent_a, parent_b : str or int
            Well names (str) or step indices (int).  Step indices refer
            to zero-based positions in the list of already-declared merges,
            where each completed merge produces a result at that index.
        """
        self._steps.append((parent_a, parent_b))
        return self

    def build(self):
        """Return a ``WellVector2TasksFunc`` compatible callable.

        The callable accepts a list of wells and returns a list of
        ``(parent_a, parent_b)`` task descriptors.
        """
        steps = self._steps[:]

        def _order_func(wells):
            from weco.engine import TaskParent
            # Map well names to indices
            name2idx = {}
            for i, w in enumerate(wells):
                name2idx[str(w.well_id())] = i

            tasks = []
            result_map = {}  # step_index -> TaskParent result

            for step_idx, (a, b) in enumerate(steps):
                if isinstance(a, str) and a in name2idx:
                    pa = TaskParent(name2idx[a])
                elif isinstance(a, int) and a in result_map:
                    pa = result_map[a]
                else:
                    pa = TaskParent(name2idx.get(str(a), 0))

                if isinstance(b, str) and b in name2idx:
                    pb = TaskParent(name2idx[b])
                elif isinstance(b, int) and b in result_map:
                    pb = result_map[b]
                else:
                    pb = TaskParent(name2idx.get(str(b), 0))

                tasks.append((pa, pb))

            return tasks

        return _order_func
