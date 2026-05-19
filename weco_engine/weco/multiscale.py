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
The `MultiScaleProject` creates different correlations using a multi-scale
 approach.

At each level, it creates new correlations (scenarios) restricted by
 the scenarios of the previous level.

There is an example in **ex4_multiscale_and_test_generation.py**

Each level (except the last one) is defined by a region list.

Regions must be contiguous and numbered from 0 to n.

The first region must start at 0, the last one must finish just at the end.

The list of data and regions used by the correlation for each level
must have a size of number of regions +1.

3 levels example with a well length of 22:
  | ``level 1 : 000000001111111222222  Data length:4``
  | ``level 2 : 000111223333344555555  Data Length:7``
  | ``Markers : 000000000011111111112  Data length:21``
  | ``=======   012345678901234567890``

  The level 1  contains 3 regions:
    * zone 0 : [0..7]
    * zone 1 : [8..14]
    * zone 2 : [15..20]

  and need 4 values in each data

  The level 1 zone 0 become 3 zones (0,1,2) at level 2 then 8 markers
  at the final level (0 - 7).

  The level 1 zone 1 become 2 zones (3,4) at level 2 then 7 markers
  at the final level (8 - 14).

  The level 1 zone 2 become 1 zone (5) at level 2 then 6 markers
  at the final level (15 - 20).
"""

from .data import WellListChecker, WellList, Well, ResFile

debug = False


class MultiScaleChecker(WellListChecker):
    """
    MultiScale checking class

    Check if a `MultiScaleProject` is valid

    """

    def valid_level(self, level_region, previous_level=None):
        """
        Check if a region is valid as a multiscale level

        :param str level_region: region to check
        :param str previous_level: previous level region or None, must be valid
        :return: True if Ok
        """
        if not self.region_exists(level_region):
            return False
        if previous_level is not None and not self.region_exists(
                previous_level):
            return False
        for well in self.well_list.wells:
            region = well.region[level_region]
            cur_end = 0
            for num, (region_id, region_start, region_len) in enumerate(
                    region):
                if num != region_id:
                    self.set_error('Bad id in level region ' + level_region)
                    return False
                if cur_end != region_start:
                    self.set_error('Bad start in level region ' + level_region)
                    return False
                if region_len <= 0:
                    self.set_error('Bad len in level region ' + level_region)
                    return False
                cur_end += region_len
            if cur_end + 1 != well.size:
                self.set_error('Bad level region size  %i/%i : %s' % (
                    cur_end + 1, well.size, level_region))
                return False
            if previous_level:
                level_start = set(i[1] for i in region)
                for prev_reg in well.region[previous_level]:
                    if prev_reg[1] not in level_start:
                        self.set_error('level region mismatch : %s/%s' % (
                            level_region, previous_level))
                        return False
        return self.ok()

    def valid_level_data(self, level_zone, data):
        """
        check if a data is valid inside a  level

        :param str level_zone: level zone name (must be valid)
        :param str data:  data name
        :return: True if ok
        """
        if not self.region_exists(level_zone) or not self.data_exists(data):
            return False
        for well in self.well_list.wells:
            if len(well.region[level_zone]) >= len(well.data[data]):
                self.set_error("Invalid level data " + data)
                return False
        return self.ok()

    def valid_multiscale_project(self, *levels):
        """
        full check of a multiscale project (level_zone and data)

        Usage::

            valid_multiscale_project(
               ('leve_zone_1',("data11","data12", ...)),
               ('level_zone2',("data21","data22", ...)),
               ...
               ('dataN1','dataN2', ...))
        """
        prev_level = None
        for cur_level, level_data in levels[:-1]:
            if not self.valid_level(cur_level, prev_level):
                return False
            prev_level = cur_level
            for idata in level_data:
                if not self.valid_level_data(cur_level, idata):
                    return False
        # last level
        for idata in levels[-1]:
            if not self.valid_data(idata):
                return False
        return self.ok()


def _dup_well(w, size=0):
    out = Well(w.name)
    out.x = w.x
    out.y = w.y
    out.z = w.z
    out.h = w.h
    out.size = size
    return out


def _copy_data(src: Well, dest: Well, name, x, lgr):
    dest.add_data(name, src.data[name][x:x + lgr])


def _copy_region(src: Well, dest: Well, name, x, lgr):
    new_region = []
    for rid, rstart, rlen in src.region[name]:
        if rstart < x + lgr and rstart + rlen > x:
            new_start = max(0, rstart - x)
            new_len = min(rstart + rlen, x + lgr) - x - new_start
            new_region.append((rid, new_start, new_len))
    dest.add_region(name, new_region)


class MultiScaleProject:
    """
    MultiScale computing class

    Usage::

       project = MultiScaleProject(well_list)
       project.level(...)
       ...
       project.final(...)
       project.run()

    See `level`, `final` and `run`


    Multiscale options:
        * ms_max_cor_per_scenario : Maximum number of correlations for each
          scenarios of the previous level
        * ms_one_well_cost=0. : Correlation cost when there is only one
          possible path.
        * ms_out_res = "res.txt" :Final result file name
          possible path.


    .. note::
       Every methods return self
    """

    class Error(Exception):
        """
        Exception for MultiScale errors
        """

    #: file name for temporary wells files
    tmp_well_file = '__tmp_well'
    #: file name for temporary result files
    tmp_res_file = '__tmp_res'

    default_multi_scale_options = dict(
        ms_max_cor_per_scenario=5,
        ms_one_well_cost=0.,
        ms_out_res="res.txt",
    )
    """
    default values for multi scale options
    """

    default_project_options = dict(
        out_nbr_cor=5,
    )
    """
    default values for correlation options
    """

    def __init__(self, well_list=None):
        """
        :param well_list: file name or `WeCoData.WellList` instance or None
        """
        self.well_list = WellList(well_list) if isinstance(well_list,
                                                           str) else well_list
        self.level_list = []
        self.final_level = []
        self._default_options = self.default_multi_scale_options.copy()
        self._default_options.update(self.default_project_options)

    def _full_options(self, opt):
        nopt = self._default_options.copy()
        nopt.update(opt)
        return nopt

    def default_options(self, _dict=None, **_opts):
        """
        define default correlations options as dict or keyword arguments
        """
        if _dict is not None:
            self._default_options.update(_dict)
        self._default_options.update(_opts)
        return self

    def level(self, _level_region, datas=None, regions=None, **_kwargs):
        """
        Add a new level

        :param _level_region: Name of the region that define the level
        :param datas: list of datas name needed for correlation
        :param regions: list of regions name needed for correlation
        :param _kwargs: correlation parameters (same as WeCo config)
          and multi scale parameters.
        :return: self
        """
        if len(self.level_list) > 0:
            raise self.Error("Not Implemented: 2 levels maximum")
        self.level_list.append((_level_region, datas or (), regions or (),
                                self._full_options(_kwargs)))
        return self

    def final(self, datas=None, regions=None, **_kwargs):
        """
        Add the final level

        :param datas: list of datas name needed for correlation
        :param regions: list of regions name needed for correlation
        :param _kwargs: correlation parameters (same as WeCo config) and
         multi scale parameters.
        :return: self
        """
        self.final_level = (
            datas or (), regions or (), self._full_options(_kwargs))
        return self

    def check(self):
        """
        Check the project definition with `MultiScaleChecker`

        :raise: `Error` if the check failed
        :return: self
        """
        if not self.final_level or not self.level_list:
            raise Exception("Project missing some levels infos")
        c = MultiScaleChecker(self.well_list)
        c.valid_multiscale_project(*(
                tuple((i[0], i[1]) for i in self.level_list) +
                (self.final_level[0],)))
        if not c.ok():
            raise self.Error(c.error())
        return self

    def run(self):
        """
        Execute the project

        :return: self
        """

        results = self.first_pass()
        level_region = self.level_list[0][0]
        for next_level_region, datas, regions, options in self.level_list[1:]:
            level_region = next_level_region
            results = self.level_pass(results, level_region, datas, regions,
                                      options)

        datas, regions, options = self.final_level
        results = self.level_pass(results, level_region, datas, regions,
                                  options)

        self.write_result(results, options["ms_out_res"])

    def run_correl(self, wells, options):
        """
        execute a normal (non-multiscale) correlation with this parameters

        :param WeCoData.WellList wells: WeCoData.WellList
        :param dict options: correlation options
        :return: a list of path with cost
        """

        # remove options from default_multi_scale_options
        options = dict((k, v) for k, v in options.items() if
                       k not in self.default_multi_scale_options)

        # §12.10: Pass WellList directly instead of writing temp files
        from .ext import ProjectExt
        project = ProjectExt()
        project.reset_options()
        project.set_options_ext(options)
        project.set_option_ext("out-file", self.tmp_res_file)

        # project.list_options()
        if not project.run(wells):
            raise self.Error("Correlation Error")
        res = ResFile(self.tmp_res_file, reorder=True)
        nbr_res = min(res.get_nbr_results(),
                      project.get_option_ext("out-nbr-cor"))
        if not nbr_res:
            raise self.Error("Correlation Error: no results")

        # noinspection PyTypeChecker
        return list(
            (res.get_result_full_path(i), res.get_result_cost(i)) for i in
            range(nbr_res))

    def first_pass(self):
        """
        process the first level

        :return:  list of path (scenarios)

        """
        print("=== First pass ===")
        np = WellList()
        level_region, datas, regions, options = self.level_list[0]

        for well in self.well_list.wells:
            new_well = _dup_well(well, 1 + len(well.region[level_region]))
            for i in regions:
                new_well.add_region(i, well.region[i])
            for i in datas:
                new_well.add_data(i, well.data[i])
            np.add_well(new_well)
        return list(i[0] for i in self.run_correl(np, options))

    def level_pass(self, prev_results, level_region, datas, regions, options):
        """
        process a level (except the first one)
        most options come from `level`

        :param prev_results: scenarios from the higher level
        :param level_region: level zone
        :param datas: data needed for correlation
        :param regions: regions list needed for correlation
        :param options: correlation options
        :return: a list of scenario
        """
        max_cor_per_scenario = options.get("ms_max_cor_per_scenario", 0)

        result_buffer = dict()
        nbr_wells = self.well_list.nbr_wells()
        y_len = tuple(
            tuple(i[2] + 1 for i in well.region[level_region]) for well in
            self.well_list.wells)
        y_level = tuple(
            tuple(i[1] for i in well.region[level_region]) for well in
            self.well_list.wells)
        # add last level
        y_level = tuple(
            _level + (_level[-1] + _len[-1] - 1,) for _level, _len in
            zip(y_level, y_len))
        y_len = tuple(i + (0,) for i in y_len)

        def get_res_part():
            dif = tuple(a != b for a, b in zip(pres, nres))
            code = '.'.join(str(a) if b else '' for a, b in zip(pres, dif))
            firsts = tuple(y_level[i][pres[i]] for i in range(nbr_wells))
            nbr_dif = dif.count(True)

            # only one well
            if nbr_dif == 1:
                mv = dif.index(True)
                res = list((tuple(
                    (firsts[w] if w != mv else firsts[w] + i) for w in
                    range(nbr_wells))) for i in
                           range(y_len[mv][pres[mv]]))
                res = ((res, options['ms_one_well_cost']),)
                return res

            # build well list
            if code in result_buffer:
                res = result_buffer[code]
            else:
                np = WellList()
                for n, well in enumerate(self.well_list.wells):
                    y_well = firsts[n]
                    l_well = y_len[n][pres[n]]
                    if dif[n]:
                        new_well = _dup_well(well, l_well)
                        for i in regions:
                            _copy_region(well, new_well, i, y_well, l_well)
                        for i in datas:
                            _copy_data(well, new_well, i, y_well, l_well)
                        np.add_well(new_well)
                res = self.run_correl(np, options)
                result_buffer[code] = res

            # translate res
            def trans_res(in_res):
                i_src = 0
                out_res = []
                for i in range(nbr_wells):
                    if dif[i]:
                        out_res.append(in_res[i_src] + firsts[i])
                        i_src += 1
                    else:
                        out_res.append(firsts[i])
                return tuple(out_res)

            res = list(
                (list(map(trans_res, path)), cost) for path, cost in res)
            return res

        print("=== Level Pass ===")

        all_res = []
        # For each correlation scenario generated at the coarser level
        for cur_res in prev_results:
            # set of zone indexes corresponding to the uppermost unit
            pres = cur_res[0]
            i_res = None
            # For all layers in the current coarse scenario
            for nres in cur_res[1:]:
                res_part = get_res_part()

                if i_res is None:
                    i_res = res_part
                else:
                    # Accumulates incrementally the local scenarios
                    # between the top and the current coarse level.
                    # Number of possibilities = nb_correlations at
                    # current level (=out_nbr_core)  ^ nb coarse layers
                    if debug:
                        d1 = set(i[0][-1] for i in i_res)
                        d2 = set(i[0][0] for i in res_part)
                        if len(d1) != 1 or d1 != d2:
                            print("MERGE ERROR", d1, d2, pres, nres)

                    i_res = list(
                        (list(a1) + list(b1)[1:], a2 + b2) for a1, a2 in i_res
                        for b1, b2 in res_part)
                pres = nres
                if max_cor_per_scenario and len(i_res) > max_cor_per_scenario:
                    # Prune the number of correlations
                    i_res.sort(key=lambda x: x[1])
                    i_res = i_res[:max_cor_per_scenario]
            all_res.extend(i_res)

        # sort on cost
        all_res.sort(key=lambda x: x[1])
        return list(i[0] for i in all_res)

    def write_result(self, result, filename):
        """
        Write results ro a file

        :param result: list of scenarios
        :param filename:  name of the file
        """
        with open(filename, "w") as file:
            nbr_wells = self.well_list.nbr_wells()
            file.write(
                "WellIds: " + " ".join(map(str, range(nbr_wells))) + '\n')
            file.write("Node 0 (%s )\n" % (' 0' * nbr_wells))
            idx = 0
            finals = []
            for res in result:
                prev = 0
                for i in res[1:-1]:
                    idx += 1
                    file.write(
                        "Node %i ( %s )\n" % (idx, ' '.join(map(str, i))))
                    file.write("  -> %i ( 0 )\n" % prev)
                    prev = idx
                finals.append(idx)
            file.write("Node %i ( %s )\n" % (
                idx + 1, ' '.join(map(str, result[-1][-1]))))
            for cost, src in enumerate(finals):
                file.write("  -> %i ( %f )\n" % (src, cost))
