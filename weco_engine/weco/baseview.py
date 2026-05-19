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


from PyQt6.QtWidgets import QGraphicsView, QGraphicsScene, QMenu, QFileDialog
from PyQt6.QtGui import QBrush, QPainter, QPolygonF
from PyQt6.QtCore import QSize, Qt, QRectF, QPointF
from fnmatch import fnmatchcase
from typing import List, Callable, Optional

try:
    from PyQt6.QtSvg import QSvgGenerator
except ImportError:
    print("*WRN* QtSvg missing")
    QSvgGenerator = None


# ============ utility
def get_file_save(parent, title, filters="") -> str:
    if filters:
        filters += ";;All files (*)"
    res = QFileDialog.getSaveFileName(parent, title, "", filters)
    if isinstance(res, tuple):
        return res[0]
    return res


def get_file_load(parent, title, filters="") -> str:
    if filters:
        filters += ";;All files (*)"
    res = QFileDialog.getOpenFileName(parent, title, "", filters)
    if isinstance(res, tuple):
        return res[0]
    return res


# ===== Res Graphics view

class ResGraphicsView(QGraphicsView):
    """
    Base class of all views
    """
    _anti_rebuild_loop = False
    _x_zoom = 1.
    _y_zoom = 1.
    _x_mult = 1.
    _y_mult = 1.

    def __init__(self, resview, parent=None):
        QGraphicsView.__init__(self, resview if parent is None else parent)
        self.resview = resview
        self.setMinimumSize(500, 300)

        self.scene = QGraphicsScene(0, 0, 100, 100, self)
        self.setScene(self.scene)
        self.setMouseTracking(True)
        self.setBackgroundBrush(QBrush(Qt.GlobalColor.white))
        self.menu = QMenu(self)

    def mouseMoveEvent(self, evt):
        super().mouseMoveEvent(evt)
        p = self.mapToScene(evt.pos())
        self.resview.on_mouse_move(p.x() / self._x_mult, p.y() / self._y_mult)

    def resizeEvent(self, evt):
        if not self._anti_rebuild_loop:
            self._anti_rebuild_loop = True
            self.resview.build_scene(True)
            self._anti_rebuild_loop = False
        super().resizeEvent(evt)

    def zoom(self, x_zoom=None, y_zoom=None, do_rebuild=True):
        rebuild = False
        if x_zoom is not None and x_zoom != self._x_zoom:
            self._x_zoom = x_zoom
            rebuild = True
        if y_zoom is not None and y_zoom != self._y_zoom:
            self._y_zoom = y_zoom
            rebuild = True

        if do_rebuild and rebuild:
            self.resview.build_scene(True)
        return rebuild

    def set_vsize(self, w, h):
        if w < 10.:
            w = 10.
        if h < 10.:
            h = 10.
        ww = float(max(self.size().width(), 50))
        wh = float(max(self.size().height(), 50))
        if self._y_zoom:
            ww -= 10
        if self._x_zoom:
            wh -= 10
        self.scene.setSceneRect(0, 0, ww * self._x_zoom, wh * self._y_zoom)
        self.fitInView(0., 0., ww, wh)
        self._x_mult = ww * self._x_zoom / w
        self._y_mult = wh * self._y_zoom / h

    def draw_line(self, x1, y1, x2, y2, *p, **pp):
        # noinspection PyArgumentList
        return self.scene.addLine(x1 * self._x_mult, y1 * self._y_mult,
                                  x2 * self._x_mult, y2 * self._y_mult, *p,
                                  **pp)

    def draw_box(self, x, y, w, h, *p, **pp):
        # noinspection PyArgumentList
        return self.scene.addRect(x * self._x_mult, y * self._y_mult,
                                  w * self._x_mult, h * self._y_mult, *p, **pp)

    def draw_centered_text(self, x, y, text, rotation=None, *p, **pp):
        obj = self.scene.addSimpleText(text, *p, **pp)
        if rotation is not None:
            obj.setRotation(rotation)
        obj.setPos(x * self._x_mult - obj.boundingRect().width() / 2.,
                   y * self._y_mult - obj.boundingRect().height() / 2.)
        return obj

    def draw_poly(self, points, *p, **pp):
        poly = QPolygonF()
        for x, y in points:
            poly.append(
                QPointF(float(x) * self._x_mult, float(y) * self._y_mult))
        poly.append(poly.first())
        return self.scene.addPolygon(poly, *p, **pp)

    def point(self, x, y):
        return float(x) * self._x_mult, float(y) * self._y_mult

    def contextMenuEvent(self, event):
        self.menu.exec(event.globalPos())

    def svg_output(self, filename='test.svg'):
        if QSvgGenerator is None:
            return
        gen = QSvgGenerator()
        ww = self.size().width()
        hh = self.size().height()

        gen.setFileName(filename)
        gen.setSize(QSize(ww, hh))
        gen.setViewBox(QRectF(0, 0, ww, hh))
        gen.setTitle("WeCo")
        gen.setDescription("")

        self.render(QPainter(gen))

    def png_output(self, filename='output.png'):
        self.grab().save(filename, "PNG")

    def cmd_svg_output(self, *_):
        res = get_file_save(self, 'Save as SVG', 'SVG Files (*.svg)')
        if res:
            self.svg_output(res)

    def cmd_png_output(self, *_):
        res = get_file_save(self, 'Save as &PNG', 'PNG Files (*.png)')
        if res:
            self.png_output(res)


# =============== BaseResView Window =============================
class BaseResView:
    _update_locked = 1
    _update_needed = True
    _status_message: Optional[Callable] = None

    def __init__(self):
        self.view = None
        self._options = dict()
        self._hit_zones = list()
        self._status_message = None

    def set_status_message(self, func: Optional[Callable] = None):
        """
        Define the status message function
        """
        self._status_message = func

    def status_message(self, text: str = ""):
        """
        Show a message on status bar

        must be ovverided or defined with set_status_message
        """
        if self._status_message:
            self._status_message(text)

    def on_mouse_move(self, x, y):
        for i in self._hit_zones:
            if i.test_hit(x, y):
                break

    def build_scene(self, resize=True):
        if resize:
            self.view.set_vsize(*self.scene_size())
        self.scene.clear()
        self._hit_zones.clear()
        self.draw_scene()

    def scene_size(self):
        return 180, 120

    def draw_scene(self):
        self.view.draw_line(10, 10, 170, 110, Qt.GlobalColor.black)

    @property
    def scene(self):
        return self.view.scene

    # ========= update =======================
    def lock_update(self):
        self._update_locked += 1

    def unlock_update(self):
        if not self._update_locked:
            return
        self._update_locked -= 1
        if not self._update_locked and self._update_needed:
            self._update_locked = 99
            self.do_update()
            self._update_needed = False
            self._update_locked = 0

    def update_locked(self):
        """
        with version of lock updated
        """

        class _ULock:
            def __init__(self, obj):
                self.obj = obj

            def __enter__(self):
                self.obj.lock_update()

            def __exit__(self, *_):
                self.obj.unlock_update()

        return _ULock(self)

    def update(self, *_):
        if self._update_locked:
            self._update_needed = True
        else:
            self._update_locked = 99
            self.do_update()
            self._update_locked = 0
            self._update_needed = False

    def do_update(self):
        pass

    # =========  options ======================
    class Option:
        def __init__(self, widget):
            self.widget = widget

        def update(self):
            pass

        def get(self):
            raise Exception("Unimplemanted")

        def enable(self, b: bool = True):
            self.widget.setEnabled(b)

    class BoolOption(Option):
        def get(self):
            return self.widget.isChecked()

        def set(self, v):
            self.widget.setChecked(bool(v))

    class SelectOption(Option):
        update_func = None

        def __init__(self, widget, values):
            super().__init__(widget)
            self.values = ()
            if isinstance(values, (list, tuple)):
                self.set_values(values)
            else:
                self.update_func = values
                assert callable(values)
                self.update()

        def set_values(self, v):
            if len(v) > 0 and isinstance(v[0], str):
                v = list((i, i) for i in v)
            if self.values == v:
                return

            idx = self.widget.currentIndex()
            old_value = self.values[idx][0] if idx >= 0 else None

            self.values = v
            self.widget.clear()
            self.widget.addItems(list(i[0] for i in self.values))

            for num, it in enumerate(self.values):
                if it[0] == old_value:
                    self.widget.setCurrentIndex(num)
                    break
            else:
                if self.values:
                    self.widget.setCurrentIndex(0)

        def update(self):
            if self.update_func:
                self.set_values(self.update_func())

        def get(self):
            idx = self.widget.currentIndex()
            return self.values[idx][1] if 0 <= idx < len(self.values) else None

        def set(self, value):
            for num, it in enumerate(self.values):
                if it[1] == value:
                    self.widget.setCurrentIndex(num)
                    return

    def add_bool_option(self, name, label, tooltip=None):
        w = self.create_bool_option_widget(label)
        if tooltip:
            w.setToolTip(tooltip)
        self._options[name] = self.BoolOption(w)
        w.stateChanged.connect(self.update)

    def add_zoom_option(self):
        zoom_values = (("No", 1), ("*2", 2), ("*4", 4), ("*8", 8),)
        self.add_select_option("zoomx", zoom_values, "X Zoom:",
                               tooltip="Zoom on X axis")
        self.add_select_option("zoomy", zoom_values, "Y Zoom:",
                               tooltip="Zoom on Y axis")

    def add_select_option(self, name, values, label=None, tooltip=None):
        w = self.create_select_option_widget(label)
        if tooltip:
            w.setToolTip(tooltip)
        self._options[name] = self.SelectOption(w, values)
        w.currentIndexChanged.connect(self.update)

    def create_bool_option_widget(self, label):
        raise Exception("Unimplemented")

    def create_select_option_widget(self, label):
        raise Exception("Unimplemented")

    def get_option(self, option_name, default=None):
        if option_name in self._options:
            return self._options[option_name].get()
        return default

    def get_all_options(self):
        """
        :return: A dict with all options values
        """
        return dict(
            (name, option.get()) for name, option in self._options.items())

    def update_options(self):
        with self.update_locked():
            for i in self._options.values():
                i.update()

    def set_option(self, option_name, value):
        if option_name in self._options:
            self._options[option_name].set(value)

    def disable_options(self, *patterns):
        def check(opt_name):
            for pat in patterns:
                if fnmatchcase(opt_name, pat):
                    return False
            return True

        for name, option in self._options.items():
            option.enable(check(name))

    # ================ HitZone ===================================
    class HitZone:
        _hit_x: float = 0.
        _hit_y: float = 0.

        def __init__(self, func: Callable, x: float, y: float,
                     width: float, height: float, kwargs: dict):
            self._x = x
            self._y = y
            self._width = width
            self._height = height
            self._func = func
            for key, value in kwargs.items():
                setattr(self, key, value)

        @property
        def x(self):
            return self._hit_x

        @property
        def y(self):
            return self._hit_y

        def test_hit(self, x, y):
            if (x < self._x or x >= self._x + self._width or
                    y < self._y or y >= self._y + self._height):
                return False
            self._hit_x = x - self._x
            self._hit_y = y - self._y
            self._func(self)
            return True

        @staticmethod
        def from_array_map(data, x):
            """
            Get float coord from an array
            """
            if x <= data[0]:
                return 0.
            prev = data[0]
            for n, v in enumerate(data[1:]):
                if x <= v:
                    return float(n) + (x - prev) / (v - prev)
                prev = v
            return float(len(data))

        @staticmethod
        def to_array_map(data, x):
            """
            Get value from float coord in an array
            """
            if x <= 0.:
                return data[0]
            if x >= len(data):
                return data[-1]
            ix = int(x)
            return data[ix] + (x - ix) * (data[ix + 1] - data[ix])

    _hit_zones: List[HitZone] = None

    def hit_zone(self, __func: Callable, __x: float, __y: float,
                 __width: float, __height: float, **__kwargs):
        self._hit_zones.append(
            self.HitZone(__func, __x, __y, __width, __height, __kwargs)
        )
