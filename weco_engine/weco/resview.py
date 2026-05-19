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

import sys
from typing import Optional, List
from PyQt6.QtWidgets import QApplication, QMainWindow, \
    QLabel, QWidget, QVBoxLayout, QCheckBox, QComboBox, QHBoxLayout, \
    QSplitter, QListWidget
from PyQt6.QtGui import QBrush, QPen, QColor, QAction
from PyQt6.QtCore import Qt

try:
    from PyQt6.QtSvg import QSvgGenerator
except ImportError:
    print("*WRN* QtSvg missing")
    QSvgGenerator = None
from .data import ResFile, WellList, CostMatrix
from enum import Enum
from .baseview import BaseResView, ResGraphicsView, get_file_save, \
    get_file_load


# from .utils import MinMax


# =============== CorResView Window =============================

class CorResView(BaseResView):
    class WellData:
        depth = None
        y = None

        def __init__(self, well, name=None, size=0, result_index=0):
            self.well = well
            self._data = dict()
            self._data_info = dict()
            self._region = dict()
            self._size = size if well is None else well.size
            self._name = name if name is not None else well.name
            self._result_index = result_index

        def name(self):
            return self._name

        def size(self):
            return self._size

        def result_index(self):
            """
            index in result
            """
            return self._result_index

        def set_depth(self, data):
            if (data is None or self.well is None or data not in self.well.data
                    or not self.well.data[data]):
                self.depth = list(range(self.size()))
                return
            self.depth = list(self.well.data[data][:self.size()])
            # check
            pv = self.depth[0]
            for i in self.depth[1:]:
                if i <= pv:
                    # not a depth
                    self.depth = list(range(self.size()))
                    print(f"*ERR* invalid depth {self.depth[i]} in well {self.well.name}", data)
                    return
                pv = i
            while len(self.depth) < self.size():
                self.depth.append(self.depth[-1] + 1.)

        def map_depth(self, end, start=0.):
            assert len(self.depth) == self.size()
            if self.size() < 2:
                self.y = [start]
                return
            start = float(start)
            minv = float(self.depth[0])
            mult = (float(end) - start) / (float(self.depth[-1]) - minv)
            self.y = tuple(
                (float(i) - minv) * mult + start for i in self.depth)

        def get_data(self, name):
            if self.well is None:
                ret = [0.] * self.size()
                self._data[name] = ret
                return ret
            if name in self._data:
                return self._data[name]
            if name not in self.well.data or len(self.well.data[name]) < 2:
                ret = [0.] * self.size()
                self._data[name] = ret
                return ret
            dta = self.well.data[name][:self.size()]
            minv = min(dta)
            rng = max(dta) - minv
            if rng <= 0.:
                rng = 1.
            ret = list((float(i) - minv) / rng for i in dta)
            # append some 0. if needed
            ret.extend([0.] * (self.size() - len(ret)))
            self._data[name] = ret
            self._data_info[name] = (minv, rng)
            return ret

        def get_data_info(self, name):
            """
            return min and range for a data
            """
            return self._data_info.get(name, (0., 1.))

        def get_region(self, name):
            if name in self._region:
                return self._region[name]
            if self.well is None or name not in self.well.region:
                return ()

            ret = []
            for rid, st, ln in self.well.region[name]:
                end = st + ln
                if st >= self.size() - 1:
                    continue
                if end <= 0:
                    continue
                if st < 0:
                    st = 0
                elif end >= self.size() - 1:
                    end = self.size() - 1
                if end <= st:
                    continue
                ret.append((rid, st, end))
            self._region[name] = ret
            return ret

    cor_pen = Qt.GlobalColor.lightGray
    tw_path_pen = QPen(Qt.GlobalColor.black, 3.0)

    region_palettes = (
        (
            '#002ff5', '#1860ba', '#2a7d84', '#3f9350', '#4fa71a', '#81b412',
            '#b1c01a', '#deca21', '#f8c323', '#f8a91e', '#f68d19', '#f17015',
            '#f05626', '#fa6266', '#ff79ae', '#fd91fa'
        ),
        # Hardcoded regions for magnetic polarity zones + grayscales
        # 0 (reverse): white (default)
        # 1 (normal): black,
        # 2 (unknown): grey50
        (
            '#ff0000', '#000000', '#888888', '#222222', '#dddddd', '#444444', '#aaaaaa',
            '#666666', '#777777', '#bbbbbb', '#333333', '#cccccc', '#555555',
            '#a1a1a1', '#8f8f8f', '#3a3a3a', '#4d4d4d'
        ),
        # Dark colors
        (
            '#ff0000', '#782121', '#803300', '#806600', '#338000', '#212178', '#706496',
            '#755137', '#a5876d', '#7a5855', '#483d45', '#372b37', '#646682',
            '#41533b', '#554840', '#554840', '#41533b'
        ),
    )

    tw_cost_palette = (
        '#3e944d', '#3fa027', '#57ab0d', '#79b211', '#95b915', '#b2c01a',
        '#cfc71f', '#eacc24', '#fbc722', '#feb61b', '#ffa413', '#ff9109',
        '#ff7e01', '#ff6800', '#ff4e00', '#ff2a00')

    class ViewType(Enum):
        AllWells = 0
        SelectedWells = 1
        TwoWells = 2

    cur_view_type = ViewType.AllWells

    class DataType(Enum):
        No = 0
        Blank = 1
        Markers = 2
        Data = 10
        Region = 11
        Trans = 20

    class MappingType(Enum):
        Rescaled = 0
        TrueDepth = 1
        TrueDepthTop = 2
        DepthRescaled = 3

    #: true if well list changed
    wells_changed = True

    #: wells at screen (WellData)
    wells_visible = None

    #: possible wells (WellData)
    wells_data: Optional[List[WellData]] = None

    #: list of data names
    well_data_names = None
    #: list of region names
    well_region_names = None

    #: well list
    cur_wells: Optional[WellList] = None
    #: result
    cur_res: Optional[ResFile] = None

    #: current path in two wells mode
    tw_cor_path = None

    #: correlation cost in two wells mode
    tw_cost_table = None
    #: correlation cost color in two wells mode
    tw_cost_color = None
    #: correlation cost range in two wells mode
    tw_cost_range = (0., 1.)

    #: Cost matrix instance
    cost_matrix: CostMatrix = None

    def __init__(self, parent=None):
        BaseResView.__init__(self)
        self.cur_wells = None
        self.cur_res = None
        self.cur_opt = dict()

        self.wells_data = list()
        self.wells_visible = list()

        self.data_visible = [self.DataType.Blank]

        self.well_data_names = []
        self.well_region_names = []

        self.cor_lines = None
        self.cor_line_num = 0

        self.splitter = QSplitter(parent)
        self.options_panel = QWidget(self.splitter)
        self.view = ResGraphicsView(self, self.splitter)
        self.cor_panel = QListWidget(self.splitter)
        # self.cor_panel.setMinimumWidth(80)
        # noinspection PyUnresolvedReferences
        self.cor_panel.currentRowChanged.connect(self.on_cor_change)

        self.splitter.addWidget(self.options_panel)
        self.splitter.addWidget(self.view)
        self.splitter.addWidget(self.cor_panel)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setCollapsible(1, False)

        self.options_panel_layout = QVBoxLayout(self.options_panel)
        self.options_panel_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.options_panel_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        palette_id = (self.cur_opt.get('palette', 0))
        self.region_brushes = list(
            QBrush(QColor(i)) for i in self.region_palettes[palette_id])
        self.no_pen = QPen(Qt.PenStyle.NoPen)
        self.red_brush = QBrush(Qt.GlobalColor.red)
        self.blue_brush = QBrush(Qt.GlobalColor.blue)
        self.gray_pen = QPen(Qt.GlobalColor.lightGray)

        self.tw_cost_brushes = list(
            QBrush(QColor(i)) for i in self.tw_cost_palette)
        self.tw_cost_pen = list(
            QPen(QColor(i), 9.) for i in self.tw_cost_palette) + [
                               QPen(QColor("#303030"), 9.)]

        self.option_init()

    def option_init(self):

        self.add_zoom_option()
        vt = self.ViewType
        self.add_select_option("viewtype", (
            ('All Wells', vt.AllWells),
            ('Selected Wells', vt.SelectedWells),
            ('Two Wells', vt.TwoWells),
        ), "Mode:")
        for i in range(self.max_well_select):
            self.add_select_option("wellselect%i" % i,
                                   self.get_well_select_possible_values)

        self.add_bool_option("reorder", "reorder", "Reorder wells to use the order of the input well"
                             + "file\n(the correlation order will be used if unchecked")
        self.add_bool_option("name", "Wells Name", "Show well names")
        self.add_select_option('depth', self.get_depth_possibles_values,
                               'Depth:', 'Depth data value')
        mt = self.MappingType
        self.add_select_option('map', (
            ("Rescaled index", mt.Rescaled),
            ("True depth", mt.TrueDepth),
            ("True depth (aligned on top)", mt.TrueDepthTop),
            ("Rescaled depth", mt.DepthRescaled),),
                               "Mapping:", "Depth mapping")
        self.add_select_option('maxcor', (
            ("None", 0), ("16", 16), ("32", 32), ("64", 64), ("128", 128),), "Max Cor:",
                               "Maximum number of visible correlations")

        self.add_select_option('palette', (
            ("Default", 0), ("Magnetostrati", 1), ("Dark", 2),),
                               "Region Palette:", "Region Palette")

        self.add_bool_option('datasep', 'Data Sep.')
        for i in range(self.max_well_data_col):
            self.add_select_option("welldata%i" % i,
                                   self.get_well_data_possible_values,
                                   tooltip="Visible Data #%i on well" % (
                                           i + 1))

        self.disable_options("wellselect*")

    def get_well_data_possible_values(self):
        dt = self.DataType
        # noinspection XPyTypeChecker
        ret = ([("None", (dt.No, None)), ("Blank", (dt.Blank, None)),
                ("Markers", (dt.Markers, None))] +
               list((i + ' (Log)', (dt.Data, i)) for i in self.well_data_names) +
               list((i + ' (Color)', (dt.Region, i)) for i in self.well_region_names))
        ret += list(
            (i + ' (R/T Sequence)', (dt.Trans, i)) for i in self.well_region_names)
        return ret

    def get_well_select_possible_values(self):
        return [("None", -1)] + list(
            (i.name(), n) for n, i in enumerate(self.wells_data)
        )

    def set_default_well_select(self):
        nbr2set = min(self.max_well_select, len(self.wells_data))
        for i in range(nbr2set):
            self.set_option("wellselect%i" % i, i)
        for i in range(nbr2set, self.max_well_select):
            self.set_option("wellselect%i" % i, -1)

    def get_depth_possibles_values(self):
        return [("None", None)] + [(i, i) for i in self.well_data_names]

    def on_cor_change(self, num, *_):
        self.cor_line_num = num
        self.cor_lines = None
        self.tw_cor_path = None
        self.update()

    #: maximum number of data columns
    max_well_data_col = 5
    size_well_data_per_nbr = (40, 25, 20, 10, 10)
    #: maximum number of wells in selected wells mode
    max_well_select = 5

    # normal mode
    size_left_margin = 5
    size_right_margin = 5
    size_top_margin = 2
    size_bottom_margin = 2
    size_correlation = 50
    size_well = 0
    size_well_data = 10
    size_well_height = 100.
    size_well_name = 10.

    # Two Well
    size_tw_well_name_width = 5.
    size_tw_well_name_height = 5.
    size_tw_well_width = 3.
    size_tw_well_height = 3.
    size_tw_well_margin_width = 1.
    size_tw_well_margin_height = 1.
    size_tw_matrix_width = 100.
    size_tw_matrix_height = 100.
    size_tw_colormap_width = 50.
    size_tw_colormap_height = 3.
    size_tw_colormap_label_dx = 10.
    size_tw_colormap_label_dy = 1.5

    size_attributes = (
        'size_bottom_margin', 'size_correlation', 'size_left_margin',
        'size_right_margin', 'size_top_margin', 'size_tw_matrix_height',
        'size_tw_matrix_width', 'size_tw_well_height',
        'size_tw_well_margin_height', 'size_tw_well_margin_width',
        'size_tw_well_name_height', 'size_tw_well_name_width',
        'size_tw_well_width', 'size_well', 'size_well_data',
        'size_well_height', 'size_well_name', "size_tw_colormap_width",
        "size_tw_colormap_height", "size_tw_colormap_label_dx",
        "size_tw_colormap_label_dy")

    rect_tw_matrix = [0., 0., 1., 1.]
    rect_tw_well1 = [0., 0., 1., 1.]
    rect_tw_well2 = [0., 0., 1., 1.]

    def scene_size(self):
        # get default size from class
        for i in self.size_attributes:
            setattr(self, i, getattr(self.__class__, i))

        if self.cur_view_type == self.ViewType.TwoWells:
            x0 = self.size_left_margin
            if self.cur_opt.get("name"):
                x0 += self.size_tw_well_name_width
            x1 = x0 + self.size_tw_well_width + self.size_tw_well_margin_width
            w = x1 + self.size_tw_matrix_width + self.size_right_margin

            y0 = self.size_top_margin
            y1 = (y0 + self.size_tw_matrix_height +
                  self.size_tw_well_margin_height)
            h = y1 + self.size_bottom_margin + self.size_tw_well_height
            if self.cur_opt.get("name"):
                h += (self.size_tw_well_name_height +
                      self.size_tw_colormap_height)

            self.rect_tw_matrix = [x1, y0, self.size_tw_matrix_width,
                                   self.size_tw_matrix_height]
            self.rect_tw_well1 = [x0, y0, self.size_tw_well_width,
                                  self.size_tw_matrix_height]
            self.rect_tw_well2 = [x1, y1, self.size_tw_matrix_width,
                                  self.size_tw_well_height]
            return w, h

        else:
            if self.cur_opt.get("name"):
                self.size_top_margin += self.size_well_name

            nbr_data = max(1, len(self.data_visible))
            self.size_well_data = self.size_well_data_per_nbr[nbr_data - 1]
            self.size_well = nbr_data * self.size_well_data

            if self.size_well <= 10:
                self.size_well = 10

            nbr_well = len(self.wells_visible)

            if nbr_well < 1:
                nbr_well = 1

            return (
                self.size_left_margin + self.size_right_margin
                + self.size_correlation * (nbr_well - 1)
                + self.size_well * nbr_well,
                self.size_top_margin + self.size_well_height
                + self.size_bottom_margin)

    def tw_get_cor_path(self):
        self.tw_cor_path = None
        if (not self.wells_visible
                or len(self.wells_visible) != 2
                or not self.cur_res):
            return

        res_num = self.cor_line_num
        if res_num > self.cur_res.get_nbr_results():
            return

        wi1 = self.wells_visible[0].result_index()
        wi2 = self.wells_visible[1].result_index()

        line = list((i[wi1], i[wi2]) for i in
                    self.cur_res.get_result_full_path(res_num))
        # remove duplicate
        prev = (0, 0)
        res = list()
        for i in line:
            if i == prev:
                continue
            prev = i
            res.append(i)
        self.tw_cor_path = res

    def tw_build_cost_table(self):
        self.tw_cost_table = None
        self.tw_cost_color = None
        self.tw_cost_range = (0., 1.)
        if (not self.cost_matrix or not self.wells_visible or len(
                self.wells_visible) != 2):
            return
        wi1 = self.wells_visible[0].result_index()
        wi2 = self.wells_visible[1].result_index()
        if (wi1 not in self.cost_matrix.wells()
                or wi2 not in self.cost_matrix.wells()):
            return
        self.tw_cost_table = self.cost_matrix.get_dict_full(wi1, wi2)

        minv = min(i for i in self.tw_cost_table.values() if i >= 0.)
        maxv = max(self.tw_cost_table.values())
        self.tw_cost_range = minv, maxv

        palette_size = len(self.tw_cost_palette)

        cost_mult = float(palette_size) / max(maxv - minv, .001)

        self.tw_cost_color = tuple(
            (key[0][0], key[0][1], key[1][0], key[1][1],
             (min(palette_size - 1, int((cost - minv) * cost_mult)))
             if cost >= 0 else palette_size)
            for key, cost in self.tw_cost_table.items()
        )

    def tw_draw_scene(self):
        if not self.wells_visible or len(self.wells_visible) != 2:
            return
        well1, well2 = self.wells_visible
        # well map
        if well1.y is None:
            well1.map_depth(self.rect_tw_well1[3])
            well2.map_depth(self.rect_tw_well2[2])

        if self.tw_cor_path is None:
            self.tw_get_cor_path()
        if not self.tw_cost_table:
            self.tw_build_cost_table()

        # unpack coords
        w1x, w1y, w1w, w1h = self.rect_tw_well1
        w2x, w2y, w2w, w2h = self.rect_tw_well2
        mx, my, mw, mh = self.rect_tw_matrix
        view = self.view

        # well1
        if well1.size() <= 100:
            for y in well1.y:
                view.draw_line(w1x, w1y + y, w1x + w1w, w1y + y)
        view.draw_box(w1x, w1y, w1w, w1h)

        # well2
        if well2.size() <= 100:
            for x in well2.y:
                view.draw_line(w2x + x, w2y, w2x + x, w2y + w2h)
        view.draw_box(w2x, w2y, w2w, w2h)

        self.view.draw_box(mx, my, mw, mh, self.gray_pen)
        if well1.size() <= 100 and well2.size() <= 100:
            for x in well2.y[1:-1]:
                view.draw_line(x + mx, my, x + mx, my + mh, self.gray_pen)
            for y in well1.y[1:-1]:
                view.draw_line(mx, my + y, mx + mw, my + y, self.gray_pen)

        # matrix
        # cost matrix
        if self.tw_cost_color:
            for y0, x0, y1, x1, color in self.tw_cost_color:
                if y1 >= len(well1.y) or x1 >= len(well2.y):
                    continue
                view.draw_line(well2.y[x0] + mx, well1.y[y0] + my,
                               well2.y[x1] + mx,
                               well1.y[y1] + my,
                               self.tw_cost_pen[color])

        # path
        if self.tw_cor_path:
            prev1, prev2 = (0, 0)
            for cur1, cur2 in self.tw_cor_path:
                view.draw_line(
                    well2.y[prev2] + mx,
                    well1.y[prev1] + my,
                    well2.y[cur2] + mx,
                    well1.y[cur1] + my,
                    self.tw_path_pen
                )
                prev1, prev2 = cur1, cur2
        # name
        if self.cur_opt.get('name'):
            view.draw_centered_text(
                w2x + w2w / 2.,
                w2y + w2h + self.size_tw_well_name_height / 2.,
                well2.name())
            view.draw_centered_text(
                w1x - self.size_tw_well_name_width / 2.,
                w1y + w1h / 2.,
                well1.name(), rotation=-90.)
            if self.tw_cost_color:
                cmx = w2x + (w2w - self.size_tw_colormap_width) / 2
                cmy = w2y + self.size_tw_well_name_height + w2h
                cmw = self.size_tw_colormap_width / float(
                    len(self.tw_cost_brushes))
                for n, brush in enumerate(self.tw_cost_brushes):
                    view.draw_box(
                        cmx + cmw * n, cmy,
                        cmw, self.size_tw_colormap_height,
                        self.gray_pen,
                        brush
                    )
                if self.tw_cost_range:
                    r1, r2 = self.tw_cost_range
                    y = cmy + self.size_tw_colormap_label_dy
                    view.draw_centered_text(cmx -
                                            self.size_tw_colormap_label_dx, y,
                                            str(r1))
                    view.draw_centered_text(cmx + self.size_tw_colormap_width +
                                            self.size_tw_colormap_label_dx,
                                            y, str(r2))
        self.hit_zone(self.tw_hz, w1x, w1y, w1w, w1h, zone=1)
        self.hit_zone(self.tw_hz, w2x, w2y, w2w, w2h, zone=2)
        self.hit_zone(self.tw_hz, mx, my, mw, mh, zone=3)

    def tw_hz(self, hz):
        status = []
        well_text = "{well}:{marker} Depth={depth:.1f}"
        w1index = 0.
        w2index = 0.

        if hz.zone & 1:
            well1 = self.wells_visible[0]
            w1index = hz.from_array_map(well1.y, hz.y)
            depth = hz.to_array_map(well1.depth, w1index)
            status.append(well_text.format(
                well=well1.name(), marker=int(w1index), depth=depth))

        if hz.zone & 2:
            well2 = self.wells_visible[1]
            w2index = hz.from_array_map(well2.y, hz.x)
            depth = hz.to_array_map(well2.depth, w2index)
            status.append(well_text.format(
                well=well2.name(), marker=int(w2index), depth=depth))

        if hz.zone == 3 and self.tw_cost_table is not None:
            cell1 = int(w1index)
            cell2 = int(w2index)
            part1 = int((w1index - cell1) * 4.)
            part2 = int((w2index - cell2) * 4.)
            if part1 in (1, 2):
                if part2 in (1, 2):
                    trans_val = (cell1, cell2), (cell1 + 1, cell2 + 1)
                elif part2 == 0:
                    trans_val = (cell1, cell2), (cell1 + 1, cell2)
                else:
                    trans_val = (cell1, cell2 + 1), (cell1 + 1, cell2 + 1)
            elif part2 in (0, 3):
                trans_val = None
            elif part1 == 0:
                trans_val = (cell1, cell2), (cell1, cell2 + 1)
            else:
                trans_val = (cell1 + 1, cell2), (cell1 + 1, cell2 + 1)
            if trans_val is not None:
                cost = self.tw_cost_table.get(trans_val)
                if cost is not None:
                    status.append("Cost={}".format(
                        "F" if cost < 0 else cost))

        self.status_message(", ".join(status))

    def draw_scene(self):
        if self.cur_view_type == self.ViewType.TwoWells:
            self.tw_draw_scene()
            return

            # draw wells
        for n, well in enumerate(self.wells_visible):
            self.draw_well(well, self.size_left_margin + n * (
                    self.size_well + self.size_correlation),
                           self.size_top_margin)

        if self.cur_res:
            self.draw_cor()

    def draw_well(self, well, x, y):
        if self.cur_opt.get("name"):
            self.view.draw_centered_text(x + self.size_well / 2.,
                                         y - self.size_well_name / 2.,
                                         well.name())

        for n, dta in enumerate(self.data_visible):
            self.draw_data(well, dta, x + n * self.size_well_data, y)

        if self.cur_opt.get('datasep'):
            for n in range(1, len(self.data_visible)):
                xl = x + n * self.size_well_data
                self.view.draw_line(xl, y + well.y[0], xl, y + well.y[-1])

        self.view.draw_box(x, y + well.y[0], self.size_well,
                           well.y[-1] - well.y[0])

    def draw_data(self, well, data, x, y):
        self.hit_zone(self.hz_well_data, x, y + well.y[0], self.size_well_data,
                      well.y[-1] - well.y[0], well=well, data=data)
        dt, param = data
        if dt == self.DataType.Markers:
            for yl in well.y[1:-1]:
                self.view.draw_line(x, y + yl, x + self.size_well_data, y + yl)
        elif dt == self.DataType.Data:
            dta = well.get_data(param)
            # small magin
            sx = x + float(self.size_well_data) * .05
            sw = float(self.size_well_data) * .9

            x0 = sx + dta[0] * sw
            y0 = well.y[0] + y
            for nx, ny in zip(dta[1:], well.y[1:]):
                nx = sx + nx * sw
                ny += y
                self.view.draw_line(x0, y0, nx, ny)
                x0, y0 = nx, ny
        elif dt == self.DataType.Region:

            for rid, rst, rend in well.get_region(param):
                if not rid:
                    continue

                self.view.draw_box(x, y + well.y[rst], self.size_well_data,
                                   well.y[rend] - well.y[rst],
                                   QPen(Qt.PenStyle.NoPen), self.region_brushes[
                                       rid % len(
                                           self.region_brushes)])
        elif dt == self.DataType.Trans:
            for rid, rst, rend in well.get_region(param):
                if not rid:
                    continue
                y0 = y + well.y[rst]
                y1 = y + well.y[rend]
                x0 = x + float(self.size_well_data) * .05
                x1 = x + float(self.size_well_data) * .9
                x12 = x + float(self.size_well_data) * .5

                if rid % 2:
                    self.view.draw_poly(((x0, y0), (x1, y0), (x12, y1)),
                                        QPen(), self.red_brush)
                else:
                    self.view.draw_poly(((x12, y0), (x1, y1), (x0, y1)),
                                        QPen(), self.blue_brush)

    def draw_cor(self):
        if self.cor_lines is None:
            # recalc cor lines

            if not self.cur_res or len(self.wells_visible) <= 1:
                return
            res_num = self.cor_line_num
            if res_num > self.cur_res.get_nbr_results():
                return

            max_cor = self.cur_opt.get('maxcor', 0)

            line = self.cur_res.get_result_full_path(res_num)
            if 2 < max_cor < len(line):
                mult = float(len(line)) / float(max_cor - 1)
                line = tuple(
                    line[int(i * mult)] for i in range(max_cor - 1)) + (
                           line[-1],)

            remap = tuple(well.result_index() for well in self.wells_visible)
            line = list(
                tuple(li[j] for j in remap)
                for li in line
            )
            self.cor_lines = line

        if not self.cor_lines:
            return

        nbr_line = len(self.wells_visible) - 1
        pen = self.cor_pen

        x0 = list(self.size_left_margin + self.size_well + (
                self.size_well + self.size_correlation) * i for i in
                  range(nbr_line))
        x1 = list(i + self.size_correlation for i in x0)
        y0 = self.size_top_margin
        wells = self.wells_visible
        for li in self.cor_lines:
            py = y0 + wells[0].y[li[0]]
            for n in range(nbr_line):
                ny = y0 + wells[n + 1].y[li[n + 1]]
                self.view.draw_line(x0[n], py, x1[n], ny, pen=pen)
                py = ny

    def hz_well_data(self, hz):
        welly = hz.from_array_map(hz.well.y, hz.y + hz.well.y[0])
        depth = hz.to_array_map(hz.well.depth, welly)
        text = "{well}:{marker} Depth={depth:.1f}".format(
            well=hz.well.name(), marker=int(welly), depth=depth)
        data_type, data_name = hz.data
        if data_type == self.DataType.Data:
            minv, rng = hz.well.get_data_info(data_name)
            value = minv + hz.well.get_data(data_name)[
                min(int(welly + .5), hz.well.size())] * rng
            text += "  {data}={value:g} [{minv:g},{maxv:g}]".format(
                value=value, minv=minv, maxv=minv + rng, data=data_name
            )
        elif data_type in (self.DataType.Region, self.DataType.Trans):
            idx = int(welly)
            for rid, rst, rend in hz.well.get_region(data_name):
                if rst <= idx < rend:
                    text += "  {name}={value}".format(
                        name=data_name, value=rid
                    )
                    break

        self.status_message(text)

    # ============== Options ===========================

    def create_bool_option_widget(self, label):
        w = QCheckBox(label, self.options_panel)
        self.options_panel_layout.addWidget(w)
        return w

    def create_select_option_widget(self, label):
        w = QComboBox(self.options_panel)

        if not label:
            self.options_panel_layout.addWidget(w)
        else:
            lo = QHBoxLayout()
            self.options_panel_layout.addLayout(lo)
            lo.addWidget(QLabel(label, self.options_panel), 0)
            lo.addWidget(w, 1)

        return w

    def set_wells_file(self, filename):
        try:
            wells = WellList(filename)
        except Exception as e:
            print("Load error:", e)
            return False

        self.set_wells(wells)

    def set_wells(self, wells):
        with self.update_locked():
            self.cur_wells = wells
            self.wells_changed = True
            self.wells_visible = []
            if not wells:
                self.well_data_names = []
                self.well_region_names = []
            else:
                self.well_data_names = list(wells.get_data_names())
                self.well_region_names = list(wells.get_region_names())
            self.set_wells_data()
            self.update_options()
            self.set_default_well_select()
            self.update()

    def set_res_file(self, filename):
        try:
            resfile = ResFile(filename)
        except Exception as e:
            print("Load error:", e)
            return False
        self.set_res(resfile)

    def load_cost_matrix(self, filename):
        try:
            cost_matrix = CostMatrix(filename)
        except Exception as err:
            print(f"*ERR* can't load Cost Matrix file {filename}:{err}")
            return
        self.set_cost_matrix(cost_matrix)

    def set_cost_matrix(self, cost_matrix=None):
        with self.update_locked():
            self.cost_matrix = cost_matrix
            self.tw_cost_table = None
            self.update()

    def set_res(self, res=None):
        with self.update_locked():
            self.cur_res = res
            self.cor_lines = None
            self.tw_cor_path = None
            self.cor_panel.clear()
            if self.cur_res:
                for i in range(self.cur_res.get_nbr_results()):
                    self.cor_panel.addItem('#%03i (%f)' % (
                        i + 1, self.cur_res.get_result_cost(i)))
                self.cor_panel.setCurrentRow(0)

            self.cor_line_num = 0
            self.set_wells_data()
            self.update()

    def set_wells_data(self):
        """
        Create wells_data from cur_wels and cur_res
        """
        self.wells_visible = list()
        self.wells_changed = True
        if not self.cur_res and not self.cur_wells:
            # no wells and no res
            self.wells_data = list()
            return
        if not self.cur_res:
            # no res
            self.wells_data = list(self.WellData(well)
                                   for well in self.cur_wells.wells)
            return

        self.wells_data = list()
        if not self.cur_wells:
            # no wells
            for well_id in range(len(self.cur_res.well_id)):
                result_index = self.cur_res.wellid2index(well_id)
                assert result_index >= 0
                self.wells_data.append(
                    self.WellData(None, "Well#%i" % (well_id + 1),
                                  self.cur_res.well_size[result_index],
                                  result_index=result_index))
            return
        # wells and res — use well_id to look up the correct well,
        # handling reordered wells (§10.4 fix)
        for well_id in range(len(self.cur_res.well_id)):
            result_index = self.cur_res.wellid2index(well_id)

            assert result_index >= 0
            well_size = self.cur_res.well_size[result_index]
            # Map well_id from result file to actual well object
            actual_well_idx = self.cur_res.well_id[well_id] if well_id < len(self.cur_res.well_id) else well_id
            if (actual_well_idx >= self.cur_wells.nbr_wells() or
                    self.cur_wells.wells[actual_well_idx].size < well_size):
                self.wells_data.append(
                    self.WellData(None, "ERR#%i" % (well_id + 1), well_size,
                                  result_index=result_index))
            else:
                self.wells_data.append(
                    self.WellData(self.cur_wells.wells[actual_well_idx],
                                  result_index=result_index))

    def do_update(self):
        opt = self.get_all_options()

        # check if an option has been modified
        def test_opt_diff(*options):
            for iopt in options:
                if self.cur_opt.get(iopt) != opt.get(iopt):
                    return True

        # need resize from zoom
        resize = self.view.zoom(opt.get("zoomx", 1), opt.get("zoomy", 1),
                                False)

        viewtype = opt.get("viewtype")

        # disable options with mode
        if viewtype != self.cur_view_type:
            if viewtype == self.ViewType.TwoWells:
                self.disable_options('reorder', 'map', 'maxcor', 'welldata*',
                                     'datasep', "wellselect[!01]")
            elif viewtype == self.ViewType.AllWells:
                self.disable_options("wellselect*")
            elif viewtype == self.ViewType.SelectedWells:
                self.disable_options("reorder")

        if viewtype == self.ViewType.TwoWells:
            # two wells vue

            wells_visible = list(
                self.wells_data[i] for i in
                (opt.get("wellselect0"), opt.get("wellselect1"))
                if i >= 0
            )

            remap = False
            if (self.cur_view_type != viewtype
                    or wells_visible != self.wells_visible):
                # selection change
                resize = True
                self.tw_cost_table = None
                remap = True
                self.tw_cor_path = None
                self.wells_visible = wells_visible

            if remap or test_opt_diff('depth'):
                for well in self.wells_visible:
                    well.set_depth(opt.get("depth"))
                    well.y = None

            resize = resize or test_opt_diff("map", "name", )

        else:
            # multiple well with correlations

            # need remap ?
            remap = False

            # build well_visible
            if viewtype == self.ViewType.SelectedWells:
                wells_visible = list(
                    self.wells_data[i] for i in (
                        opt.get("wellselect%i" % j)
                        for j in range(self.max_well_select)
                    )
                    if i >= 0
                )
            elif self.cur_res and not opt.get('reorder'):
                wells_visible = list(
                    self.wells_data[i] for i in self.cur_res.well_id)
            else:
                wells_visible = self.wells_data

            if wells_visible != self.wells_visible:
                self.cor_lines = None
                remap = True
                resize = True
                self.wells_visible = wells_visible
            elif self.cur_view_type != viewtype:
                resize = True
                remap = True
                self.cor_lines = None
            elif test_opt_diff('maxcor'):
                self.cor_lines = None

            # data visible
            prev_data_size = len(self.data_visible)
            self.data_visible = list(
                filter(lambda x: x[0] != self.DataType.No,
                       (opt.get("welldata%i" % n, "None") for n in
                        range(self.max_well_data_col))))
            if not self.data_visible:
                self.data_visible = [(self.DataType.Blank, None)]

            if prev_data_size != len(self.data_visible):
                resize = True

            resize = resize or test_opt_diff("name", )

            if test_opt_diff("palette", ):
                palette_id = opt.get("palette")
                self.region_brushes = list(
                    QBrush(QColor(i)) for i in self.region_palettes[palette_id])
                remap = True

            if remap or test_opt_diff("map", "depth"):
                depth = opt.get("depth")
                for w in self.wells_visible:
                    w.set_depth(depth)
                self.remap_wells(opt.get("map", self.MappingType.Rescaled))

        self.cur_view_type = viewtype
        self.wells_changed = False
        self.cur_opt = opt
        self.build_scene(resize)

    def remap_wells(self, method):
        if not self.wells_visible:
            return
        if method == self.MappingType.TrueDepth:
            y_min = float(min(well.depth[0] for well in self.wells_visible))
            y_range = float(
                max(well.depth[-1] for well in self.wells_visible)) - y_min
            if y_range <= 0.:
                y_range = 1.
            mult = float(self.size_well_height) / y_range
            for well in self.wells_visible:
                well.y = tuple(float(i - y_min) * mult for i in well.depth)
        elif method == self.MappingType.TrueDepthTop:
            y_range = float(max((well.depth[-1] - well.depth[0]) for well in
                                self.wells_visible))
            if y_range <= 0.:
                y_range = 1.
            mult = float(self.size_well_height) / y_range
            for well in self.wells_visible:
                y_min = well.depth[0]
                well.y = tuple(float(i - y_min) * mult for i in well.depth)
        elif method == self.MappingType.DepthRescaled:
            for well in self.wells_visible:
                y_min = well.depth[0]
                y_range = float(well.depth[-1]) - y_min
                if y_range <= 0.:
                    y_range = 1.
                mult = float(self.size_well_height) / y_range
                well.y = tuple(float(i - y_min) * mult for i in well.depth)
        else:  # self.MappingType.Rescaled
            for well in self.wells_visible:
                mult = float(self.size_well_height) / max(1., float(
                    well.size() - 1.))
                well.y = tuple(float(i) * mult for i in range(well.size()))

    def set_depth_view(self, prop=None):
        with self.update_locked():
            if prop is not None:
                self.set_option('depth', prop)
            self.set_option('map', self.MappingType.TrueDepth)

    def show_data_prop(self, name, col=0):
        if 0 <= col < self.max_well_data_col:
            self.set_option("welldata%i" % col, (self.DataType.Data, name))

    def show_region_prop(self, name, col=0):
        if 0 <= col < self.max_well_data_col:
            self.set_option("welldata%i" % col, (self.DataType.Region, name))

    def cmd_svg_output_all(self, *_):
        res = get_file_save(None, "Save all correlations as SVG")
        if not res:
            return
        for i in range(self.cur_res.get_nbr_results()):
            self.on_cor_change(i)
            self.view.svg_output(res + ("_%03i.svg" % i))
        self.on_cor_change(0)

    def cmd_png_output_all(self, *_):
        res = get_file_save(None, "Save all correlations as PNG")
        if not res:
            return
        for i in range(self.cur_res.get_nbr_results()):
            self.on_cor_change(i)
            self.view.png_output(res + ("_%03i.png" % i))
        self.on_cor_change(0)

    def cmd_load_wells(self):
        res = get_file_load(None, "Load Wells", "Wells file (*wells.txt)")
        if res:
            try:
                self.set_wells_file(res)
                self.update()
            except Exception as eee:
                print("ERR", eee)

    def cmd_load_res(self):
        res = get_file_load(None, "Load Result file", "Result file (*.txt)")
        if res:
            self.set_res_file(res)

    def cmd_load_cm(self):
        res = get_file_load(None, "Load Cost Matrix file",
                            "Cost Matrix file (*.txt)")
        if res:
            self.load_cost_matrix(res)

    def cmd_clear_res(self):
        self.set_res(None)

    def cmd_clear_cm(self):
        self.set_cost_matrix(None)

    def cmd_show_hide_cor_panel(self, *_):
        if self.cor_panel.isVisible():
            self.cor_panel.hide()
        else:
            self.cor_panel.show()

    def cmd_show_hide_options_panel(self, *_):
        if self.options_panel.isVisible():
            self.options_panel.hide()
        else:
            self.options_panel.show()


# =============== ResView as application ======================


class ResViewApp(QMainWindow):

    def __init__(self):
        QMainWindow.__init__(self)
        self.resview = CorResView(self)
        self.setWindowTitle("ResView")
        self.setCentralWidget(self.resview.splitter)
        self.setGeometry(50, 50, 1000, 600)
        self.statusBar()
        self.resview.set_status_message(self.status_message)

        def act(name, func, shortcut=None):
            ret = QAction(name, self)
            # noinspection PyUnresolvedReferences
            ret.triggered.connect(func)
            if shortcut:
                ret.setShortcut(shortcut)
            return ret

        menu_bar = self.menuBar()
        menu = menu_bar.addMenu("&File")

        menu.addAction(act("Load &Wells", self.resview.cmd_load_wells))
        menu.addAction(act("Load &Results", self.resview.cmd_load_res))
        menu.addAction(act("&Clear Results", self.resview.cmd_clear_res))
        menu.addAction(act("Load C&ost Matrix", self.resview.cmd_load_cm))
        menu.addAction(act("Clear C&ost Matrix", self.resview.cmd_clear_cm))
        menu.addSeparator()
        menu.addAction(act("&Quit", QApplication.instance().exit))

        menu = menu_bar.addMenu("&Save")
        menu.addAction(act("Save as &png", self.resview.view.cmd_png_output))
        menu.addAction(act("Save as &svg", self.resview.view.cmd_svg_output))
        menu.addSeparator()
        menu.addAction(act("Save all correlations as png",
                           self.resview.cmd_png_output_all))
        menu.addAction(act("Save all correlations as svg",
                           self.resview.cmd_svg_output_all))

        menu = menu_bar.addMenu("&View")
        menu.addAction(
            act("&Options", self.resview.cmd_show_hide_options_panel))
        menu.addAction(
            act("&Correlations", self.resview.cmd_show_hide_cor_panel))

    def status_message(self, text=None):
        """
        Show message in status bar
        """
        self.statusBar().showMessage(text or "")

    @classmethod
    def init_parser(cls, parser):
        parser.add_argument("--wells", '-w', help="wells file")
        parser.add_argument('cor_file', nargs='?')
        parser.add_argument('wells_file', nargs='?')
        parser.add_argument('--z-prop', '-z', help="Depth property")
        parser.add_argument('--data', '-d', help="Data property")
        parser.add_argument('--region', '-r', help="Region")
        parser.add_argument('--reorder', '-o', action="store_true",
                            help="Reorder wells to use the order of the input well file (and not the results file)")
        parser.add_argument('--two-wells', '-2', action="store_true",
                            help="Display the cost matrix")
        parser.add_argument('--cost-matrix', '-c', help="Cost matrix file")

    def set_args(self, params):
        if params.wells_file:
            self.resview.set_wells_file(params.wells_file)
        elif params.wells:
            self.resview.set_wells_file(params.wells)
        if params.cor_file:
            self.resview.set_res_file(params.cor_file)
        if params.reorder:
            self.resview.set_option('reorder', True)
        if params.z_prop:
            self.resview.set_depth_view(params.z_prop)
        if params.data:
            self.resview.show_data_prop(params.data, 2)
        if params.region:
            self.resview.show_region_prop(params.region, 0)
            if params.data:
                self.resview.show_region_prop(params.region, 4)
                self.resview.set_option("datasep", True)

        if params.cost_matrix:
            self.resview.load_cost_matrix(params.cost_matrix)

        if params.two_wells:
            self.resview.set_option("viewtype", self.resview.ViewType.TwoWells)

    @classmethod
    def main(cls, params=None):
        import argparse
        parser = argparse.ArgumentParser()
        cls.init_parser(parser)
        args = parser.parse_args(params)
        cls.application = QApplication(sys.argv)
        wnd = cls.main_window = cls()
        wnd.show()
        wnd.set_args(args)
        # update is locked by constructor
        wnd.resview.unlock_update()

        sys.exit(cls.application.exec())


main = ResViewApp.main

if __name__ == '__main__':
    # ResViewApp.main('-o -z depth  -r region -w ../tests/test6_wells.txt'
    # ' ../tests/test6_res.txt'.split())
    ResViewApp.main()
