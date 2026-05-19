"""
WeCo Professional Correlation Plot Window
==========================================

A publication-quality, interactive multi-well correlation panel built on
matplotlib + Qt, supporting:

  • Multiple log tracks per well (GR, RT, DEN, etc.) with fill
  • Region / lithology / facies colour strips
  • Correlation lines between adjacent wells (coloured by cost)
  • Horizon labels + depth ticks
  • Drag-and-drop well reordering
  • Log-scale support (resistivity, sonic)
  • Interactive hover tooltips (well name, depth, value)
  • Colour legends for regions + logs
  • Zoom / pan with matplotlib navigation toolbar
  • Export: PNG, SVG, PDF at configurable DPI
  • Input-only mode (QC wells before correlation)
  • Result overlay mode (correlation lines on top of well logs)

Data flow:
    WellList  ──►  CorrelationPlotWindow.set_wells()
    ResFile   ──►  CorrelationPlotWindow.set_result()
    CostMatrix──►  CorrelationPlotWindow.set_cost_matrix()

Public API
----------
    CorrelationPlotWindow(parent=None)
        .set_wells(well_list: WellList)
        .set_result(res_file: ResFile, cor_index=0)
        .set_cost_matrix(cost_matrix: CostMatrix)
        .refresh()
"""

from __future__ import annotations

import math
from typing import Optional, Sequence

import numpy as np

import matplotlib
matplotlib.use("QtAgg")

import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.patches import FancyArrowPatch, ConnectionPatch
from matplotlib.collections import LineCollection
import matplotlib.colors as mcolors
import matplotlib.ticker as mticker

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QToolBar,
    QLabel, QPushButton, QComboBox, QSpinBox, QCheckBox, QSplitter,
    QScrollArea, QSizePolicy, QFileDialog, QMessageBox, QStatusBar,
    QGroupBox, QFormLayout, QSlider, QMenu, QApplication,
)
from PyQt6.QtGui import QAction, QFont, QIcon, QCursor
from PyQt6.QtCore import Qt, pyqtSignal, QSize

from .data import WellList, ResFile, CostMatrix


# ═══════════════════════════════════════════════════════════════════════════
#  Geological colour palettes
# ═══════════════════════════════════════════════════════════════════════════

#: Lithology / facies palette — covers common sedimentary and periglacial types
#: Index 0 = background (no region / ID 0), indices 1..20 are distinct colours
LITHO_PALETTE = [
    "#ffffff",   # 0  background / undefined
    "#f5e042",   # 1  sand / sandstone
    "#a0a0a0",   # 2  shale / mudstone
    "#7ec850",   # 3  silt / siltstone
    "#4096c8",   # 4  limestone / carbonate
    "#80d0f0",   # 5  marl
    "#c87820",   # 6  gravel / conglomerate
    "#ffa060",   # 7  till / diamicton
    "#9060c0",   # 8  cryoturbate / breccia
    "#40e0d0",   # 9  dropstone / erratic
    "#2d2d2d",   # 10 coal
    "#783c00",   # 11 peat / lignite
    "#ff4060",   # 12 marine band
    "#ff8000",   # 13 ironstone
    "#b0b060",   # 14 Brandschiefer / oil shale
    "#e0c0a0",   # 15 dolomite
    "#606060",   # 16 anhydrite
    "#c0c0c0",   # 17 halite / evaporite
    "#008080",   # 18 clay
    "#d0b0e0",   # 19 tuff / volcanic
    "#f0f0f0",   # 20 chalk / white limestone
]

#: Named log colours for common log types
LOG_STYLES = {
    "GR":    {"color": "#2ca02c", "fill": "right", "fill_alpha": 0.15, "lw": 1.0},
    "RT":    {"color": "#d62728", "fill": None,     "fill_alpha": 0.0,  "lw": 1.0, "log_scale": True},
    "DEN":   {"color": "#1f77b4", "fill": "left",   "fill_alpha": 0.10, "lw": 1.0},
    "CAL":   {"color": "#9467bd", "fill": None,     "fill_alpha": 0.0,  "lw": 0.8},
    "SPT":   {"color": "#8c564b", "fill": None,     "fill_alpha": 0.0,  "lw": 1.0},
    "COND":  {"color": "#ff7f0e", "fill": None,     "fill_alpha": 0.0,  "lw": 1.0},
    "MS":    {"color": "#e377c2", "fill": None,     "fill_alpha": 0.0,  "lw": 0.8},
    "WC":    {"color": "#17becf", "fill": "right",  "fill_alpha": 0.10, "lw": 0.8},
    "SON":   {"color": "#bcbd22", "fill": None,     "fill_alpha": 0.0,  "lw": 1.0},
    "NEU":   {"color": "#7f7f7f", "fill": None,     "fill_alpha": 0.0,  "lw": 1.0},
    "FACIES": {"color": "#444444", "fill": None,    "fill_alpha": 0.0,  "lw": 0.6},
    "LITH":  {"color": "#444444", "fill": None,     "fill_alpha": 0.0,  "lw": 0.6},
}

# Default style for unknown logs
_DEFAULT_LOG_STYLE = {"color": "#555555", "fill": None, "fill_alpha": 0.0, "lw": 1.0}

# Well column colours (for headers / outlines)
WELL_COLORS = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
    "#aec7e8", "#ffbb78", "#98df8a", "#ff9896", "#c5b0d5",
]

# Correlation line gradient: green (low cost) → red (high cost)
COR_CMAP = plt.cm.RdYlGn_r  # reversed: green=good, red=bad


# ═══════════════════════════════════════════════════════════════════════════
#  Helper: build depth array for a well
# ═══════════════════════════════════════════════════════════════════════════

def _get_depth(well, depth_prop=None) -> np.ndarray:
    """Return a depth array for a well. Tries depth_prop, then common names, then range."""
    if depth_prop and depth_prop in well.data and well.data[depth_prop]:
        return np.array(well.data[depth_prop][:well.size], dtype=float)
    for dn in ("Depth", "DEPTH", "depth", "MD", "TVD"):
        if dn in well.data and well.data[dn]:
            return np.array(well.data[dn][:well.size], dtype=float)
    return np.arange(well.size, dtype=float)


def _get_log(well, name) -> Optional[np.ndarray]:
    """Return normalised log data or None."""
    if name not in well.data or not well.data[name]:
        return None
    d = np.array(well.data[name][:well.size], dtype=float)
    return d


def _classify_logs(data_names: list[str]) -> tuple[list[str], list[str]]:
    """Split data property names into log-type and skip-type (depth aliases)."""
    skip = {"Depth", "DEPTH", "depth", "MD", "TVD", "TVDSS", "md", "tvd"}
    logs = [n for n in data_names if n not in skip]
    return logs, list(skip & set(data_names))


# ═══════════════════════════════════════════════════════════════════════════
#  CorrelationPlotWidget — the matplotlib canvas + drawing logic
# ═══════════════════════════════════════════════════════════════════════════

class CorrelationPlotWidget(FigureCanvasQTAgg):
    """Interactive matplotlib canvas that renders the correlation panel."""

    # Signals
    hover_info = pyqtSignal(str)  # emitted on mouse move with status text
    well_clicked = pyqtSignal(int)  # well index clicked

    def __init__(self, parent=None, dpi=100):
        self.fig = Figure(dpi=dpi, facecolor="white")
        super().__init__(self.fig)
        self.setParent(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # Data
        self._wells: Optional[WellList] = None
        self._res: Optional[ResFile] = None
        self._cost_matrix: Optional[CostMatrix] = None
        self._well_order: Optional[list[int]] = None  # display order of well indices

        # Display config
        self._depth_prop: Optional[str] = None
        self._cor_index: int = 0
        self._max_cor_lines: int = 200
        self._show_logs: list[str] = []  # which logs to show (empty = auto-select first 2)
        self._show_regions: list[str] = []  # which regions to show as colour strips
        self._show_names: bool = True
        self._show_depth_ticks: bool = True
        self._show_horizons: bool = True
        self._show_cor_lines: bool = True
        self._cor_color_by_cost: bool = True
        self._log_fill: bool = True
        self._show_legend: bool = True
        self._marker_size: int = 0  # 0 = hide markers

        # Axes cache (cleared on redraw)
        self._well_axes: list = []  # list of (log_axes, region_ax) per well
        self._gap_axes: list = []  # axes between wells for correlation lines

        # Hover state
        self._hover_annot = None

        # Connect events
        self.mpl_connect("motion_notify_event", self._on_hover)
        self.mpl_connect("button_press_event", self._on_click)

    # ──── Public setters ─────────────────────────────────────────────

    def set_wells(self, wl: Optional[WellList]):
        self._wells = wl
        self._well_order = None
        self._auto_configure()

    def set_result(self, rf: Optional[ResFile], cor_index: int = 0):
        self._res = rf
        self._cor_index = cor_index

    def set_cost_matrix(self, cm: Optional[CostMatrix]):
        self._cost_matrix = cm

    def set_well_order(self, order: list[int]):
        self._well_order = order

    def set_depth_prop(self, prop: Optional[str]):
        self._depth_prop = prop

    def set_cor_index(self, idx: int):
        self._cor_index = idx

    def set_show_logs(self, logs: list[str]):
        self._show_logs = logs

    def set_show_regions(self, regions: list[str]):
        self._show_regions = regions

    # ──── Auto-configure display from data ───────────────────────────

    def _auto_configure(self):
        """Pick sensible defaults from loaded data."""
        if not self._wells or not self._wells.wells:
            return
        data_names = list(self._wells.get_data_names())
        region_names = list(self._wells.get_region_names())
        logs, _ = _classify_logs(data_names)

        # Auto-select up to 3 logs
        if not self._show_logs:
            priority = ["GR", "RT", "DEN", "SPT", "CAL", "SON", "NEU",
                         "COND", "MS", "WC", "FACIES", "LITH"]
            auto = [l for l in priority if l in logs]
            # Add any remaining
            for l in logs:
                if l not in auto:
                    auto.append(l)
            self._show_logs = auto[:3]

        # Auto-select first region if available
        if not self._show_regions and region_names:
            self._show_regions = region_names[:1]

    # ──── Main rendering ─────────────────────────────────────────────

    def render(self):
        """Full redraw of the correlation panel."""
        self.fig.clear()
        self._well_axes.clear()
        self._gap_axes.clear()

        if not self._wells or not self._wells.wells:
            ax = self.fig.add_subplot(111)
            ax.text(0.5, 0.5, "No wells loaded", transform=ax.transAxes,
                    ha="center", va="center", fontsize=14, color="#888")
            ax.set_axis_off()
            self.draw()
            return

        wells = self._wells.wells
        n_wells = len(wells)

        # Determine well display order
        if self._well_order is not None:
            order = self._well_order
        elif self._res is not None:
            order = list(self._res.well_id)
        else:
            order = list(range(n_wells))
        order = [i for i in order if 0 <= i < n_wells]

        # Cap displayed wells to avoid matplotlib gridspec explosion
        MAX_DISPLAY = 25
        if len(order) > MAX_DISPLAY:
            # Subsample evenly
            step = len(order) / MAX_DISPLAY
            order = [order[int(i * step)] for i in range(MAX_DISPLAY)]

        n_disp = len(order)
        if n_disp == 0:
            return

        # Layout calculation
        n_log_tracks = max(1, len(self._show_logs))
        n_region_tracks = len(self._show_regions)
        # Each well gets: region strip(s) + log track(s)
        # Between wells: a gap for correlation lines
        #
        # GridSpec columns:
        #   For each well:  [region_strip_1..N] [log_track_1..N]
        #   Between wells:  [gap]
        well_cols = n_region_tracks + n_log_tracks
        gap_cols = 1
        total_cols = n_disp * well_cols + (n_disp - 1) * gap_cols

        # Width ratios: region strips narrow, log tracks medium, gaps medium
        ratios = []
        for wi in range(n_disp):
            for _ in range(n_region_tracks):
                ratios.append(0.3)  # region strip
            for _ in range(n_log_tracks):
                ratios.append(1.0)  # log track
            if wi < n_disp - 1:
                ratios.append(0.8)  # gap for cor lines

        gs = self.fig.add_gridspec(
            nrows=1, ncols=total_cols,
            width_ratios=ratios,
            wspace=0.02,
            left=0.04, right=0.96, top=0.92, bottom=0.06,
        )

        # Compute global depth range
        all_depths = []
        well_depths = {}
        for idx in order:
            d = _get_depth(wells[idx], self._depth_prop)
            well_depths[idx] = d
            all_depths.extend(d)
        if not all_depths:
            return
        depth_min, depth_max = min(all_depths), max(all_depths)
        depth_pad = max(1.0, (depth_max - depth_min) * 0.02)
        y_lim = (depth_max + depth_pad, depth_min - depth_pad)  # inverted

        # Draw each well
        col = 0
        first_ax = None
        for wi_display, wi_data in enumerate(order):
            well = wells[wi_data]
            depth = well_depths[wi_data]
            wcolor = WELL_COLORS[wi_display % len(WELL_COLORS)]

            # Region strips
            for ri, rname in enumerate(self._show_regions):
                ax_r = self.fig.add_subplot(gs[0, col])
                col += 1
                self._draw_region_strip(ax_r, well, rname, depth, y_lim,
                                        show_label=(wi_display == 0), first_ax=first_ax)
                if first_ax is None:
                    first_ax = ax_r

            # Log tracks
            log_axes_for_well = []
            for li, lname in enumerate(self._show_logs):
                share_y = first_ax if first_ax else None
                ax_l = self.fig.add_subplot(gs[0, col], sharey=share_y)
                col += 1
                self._draw_log_track(ax_l, well, lname, depth, y_lim,
                                     wcolor, li, wi_display, n_disp)
                log_axes_for_well.append(ax_l)
                if first_ax is None:
                    first_ax = ax_l

            self._well_axes.append(log_axes_for_well)

            # Well name header
            if self._show_names and log_axes_for_well:
                # Place name centred above the log tracks
                mid_ax = log_axes_for_well[len(log_axes_for_well) // 2]
                mid_ax.set_title(well.name, fontsize=9, fontweight="bold",
                                 color=wcolor, pad=8)

            # Gap axis for correlation lines
            if wi_display < n_disp - 1:
                ax_gap = self.fig.add_subplot(gs[0, col], sharey=first_ax)
                col += 1
                ax_gap.set_axis_off()
                ax_gap.set_ylim(y_lim)
                self._gap_axes.append((ax_gap, wi_display, wi_data, order[wi_display + 1]))

        # Draw correlation lines
        if self._show_cor_lines and self._res is not None:
            self._draw_correlations(wells, order, well_depths, y_lim)

        # Legend
        if self._show_legend:
            self._draw_legend()

        # Title
        title_parts = []
        if self._res:
            cost = self._res.get_result_cost(self._cor_index)
            n_cor = self._res.get_nbr_results()
            title_parts.append(f"Correlation #{self._cor_index}  |  Cost: {cost:.4f}  |  {n_cor} alternatives")
        if title_parts:
            self.fig.text(0.5, 0.985, "  ".join(title_parts),
                          ha="center", va="top", fontsize=9, style="italic",
                          color="#555")

        self.draw()

    # ──── Draw a region / lithology colour strip ─────────────────────

    def _draw_region_strip(self, ax, well, region_name, depth, y_lim,
                           show_label=False, first_ax=None):
        ax.set_ylim(y_lim)
        ax.set_xlim(0, 1)
        ax.set_xticks([])

        if show_label:
            ax.set_ylabel("Depth", fontsize=8)
            ax.tick_params(axis="y", labelsize=7)
        else:
            ax.tick_params(axis="y", labelleft=False, length=0)

        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["bottom"].set_visible(False)

        if region_name not in well.region:
            ax.text(0.5, 0.5, "—", transform=ax.transAxes,
                    ha="center", va="center", fontsize=7, color="#aaa")
            return

        for rid, start, length in well.region[region_name]:
            if rid == 0:
                continue
            end = start + length
            if start >= well.size or end <= 0:
                continue
            start = max(0, start)
            end = min(well.size - 1, end)
            if start >= len(depth) or end >= len(depth):
                continue
            y_top = depth[start]
            y_bot = depth[end]
            c = LITHO_PALETTE[rid % len(LITHO_PALETTE)]
            ax.axhspan(y_top, y_bot, facecolor=c, alpha=0.85, linewidth=0.3,
                       edgecolor="#888")

        # Label at top
        ax.text(0.5, 1.01, region_name, transform=ax.transAxes,
                ha="center", va="bottom", fontsize=6, rotation=0,
                color="#666", fontweight="bold")

    # ──── Draw a log track ───────────────────────────────────────────

    def _draw_log_track(self, ax, well, log_name, depth, y_lim,
                        well_color, track_idx, well_idx, n_wells):
        ax.set_ylim(y_lim)

        # Y ticks: only first track of first well
        if track_idx == 0 and well_idx == 0 and not self._show_regions:
            ax.set_ylabel("Depth", fontsize=8)
            ax.tick_params(axis="y", labelsize=7)
        else:
            ax.tick_params(axis="y", labelleft=False, length=0)

        # Get log data
        raw = _get_log(well, log_name)
        style = LOG_STYLES.get(log_name, _DEFAULT_LOG_STYLE)
        lcolor = style["color"]
        lw = style.get("lw", 1.0)
        is_log_scale = style.get("log_scale", False)

        if raw is None:
            ax.set_xlim(0, 1)
            ax.text(0.5, 0.5, f"no\n{log_name}", transform=ax.transAxes,
                    ha="center", va="center", fontsize=6, color="#ccc",
                    rotation=90)
        else:
            n = min(len(raw), len(depth))
            vals = raw[:n]
            dep = depth[:n]

            if is_log_scale:
                pos = vals[vals > 0]
                if len(pos) > 0:
                    ax.set_xscale("log")
                    vmin = np.percentile(pos, 2)
                    vmax = np.percentile(pos, 98)
                else:
                    vmin, vmax = 0.1, 100.0
            else:
                vmin = np.nanpercentile(vals, 1)
                vmax = np.nanpercentile(vals, 99)
                pad = max(0.01, (vmax - vmin) * 0.05)
                vmin -= pad
                vmax += pad

            ax.set_xlim(vmin, vmax)
            ax.plot(vals, dep, color=lcolor, linewidth=lw, zorder=5)

            # Fill
            if self._log_fill and style.get("fill"):
                fill_dir = style["fill"]
                fill_alpha = style.get("fill_alpha", 0.12)
                if fill_dir == "right":
                    ax.fill_betweenx(dep, vals, vmax, alpha=fill_alpha,
                                      color=lcolor, zorder=2)
                elif fill_dir == "left":
                    ax.fill_betweenx(dep, vmin, vals, alpha=fill_alpha,
                                      color=lcolor, zorder=2)

        # Grid and styling
        ax.grid(True, axis="y", alpha=0.15, linewidth=0.5)
        ax.grid(True, axis="x", alpha=0.10, linewidth=0.3)
        ax.tick_params(axis="x", labelsize=6, rotation=45)
        ax.xaxis.set_major_locator(mticker.MaxNLocator(nbins=3))

        # Top label (log name)
        ax.text(0.5, 1.01, log_name, transform=ax.transAxes,
                ha="center", va="bottom", fontsize=7, color=lcolor,
                fontweight="bold")

        # Subtle well outline
        for spine in ax.spines.values():
            spine.set_linewidth(0.5)
            spine.set_color("#ccc")

        ax.spines["top"].set_visible(False)

    # ──── Draw correlation lines ─────────────────────────────────────

    def _draw_correlations(self, wells, order, well_depths, y_lim):
        if self._res is None:
            return
        n_res = self._res.get_nbr_results()
        cid = min(self._cor_index, n_res - 1)
        if cid < 0:
            return

        path = self._res.get_result_full_path(cid)
        if not path:
            return

        # Subsample if too many
        if self._max_cor_lines > 0 and len(path) > self._max_cor_lines:
            step = len(path) / self._max_cor_lines
            indices = [int(i * step) for i in range(self._max_cor_lines)]
            if (len(path) - 1) not in indices:
                indices.append(len(path) - 1)
            path = [path[i] for i in indices]

        # Cost range for colouring
        costs = []
        if self._cor_color_by_cost and n_res > 1:
            for i in range(min(n_res, 20)):
                costs.append(self._res.get_result_cost(i))
            cost_min = min(costs)
            cost_max = max(costs)
        else:
            cost_min = cost_max = 0.0

        cur_cost = self._res.get_result_cost(cid)
        if cost_max > cost_min:
            norm_cost = (cur_cost - cost_min) / (cost_max - cost_min)
        else:
            norm_cost = 0.0

        # Choose line colour
        if self._cor_color_by_cost and cost_max > cost_min:
            line_color = COR_CMAP(norm_cost)
            line_alpha = 0.55
        else:
            line_color = "#888888"
            line_alpha = 0.45

        # Draw lines in gap axes
        for gap_ax, disp_left, data_left, data_right in self._gap_axes:
            dl = well_depths.get(data_left)
            dr = well_depths.get(data_right)
            if dl is None or dr is None:
                continue

            # Find result indices for left and right wells
            ri_left = self._get_result_index(data_left)
            ri_right = self._get_result_index(data_right)
            if ri_left is None or ri_right is None:
                continue

            segments = []
            for node in path:
                ml = node[ri_left]
                mr = node[ri_right]
                if ml < len(dl) and mr < len(dr):
                    y_l = dl[ml]
                    y_r = dr[mr]
                    segments.append([(0.0, y_l), (1.0, y_r)])

            if segments:
                lc = LineCollection(segments, colors=[line_color] * len(segments),
                                    linewidths=0.6, alpha=line_alpha, zorder=3)
                gap_ax.add_collection(lc)
                gap_ax.set_xlim(0, 1)
                gap_ax.set_ylim(y_lim)

        # Draw horizon labels
        if self._show_horizons and len(path) > 2:
            self._draw_horizon_labels(wells, order, well_depths, path, y_lim)

    def _get_result_index(self, well_data_index: int) -> Optional[int]:
        """Map a well data index to the result file's internal index."""
        if self._res is None:
            return None
        try:
            pos = list(self._res.well_id).index(well_data_index)
            return self._res.wellid2index(well_data_index)
        except (ValueError, AttributeError):
            # well_id is already the index sometimes
            if well_data_index < self._res.nbr_well():
                return well_data_index
            return None

    # ──── Horizon labels ─────────────────────────────────────────────

    def _draw_horizon_labels(self, wells, order, well_depths, path, y_lim):
        """Add small numbered labels at horizon crossings on the first well."""
        if not self._well_axes or not order:
            return
        first_well_idx = order[0]
        first_depth = well_depths.get(first_well_idx)
        if first_depth is None or not self._well_axes[0]:
            return

        ax = self._well_axes[0][0]  # first log track of first well

        ri = self._get_result_index(first_well_idx)
        if ri is None:
            return

        # Deduplicate: only mark where this well's marker changes
        prev_m = path[0][ri]
        hz_num = 0
        labeled = set()
        for node in path[1:]:
            m = node[ri]
            if m != prev_m and m < len(first_depth) and m not in labeled:
                hz_num += 1
                if hz_num % max(1, len(path) // 15) == 0:  # don't overcrowd
                    y = first_depth[m]
                    ax.axhline(y=y, color="#ff6600", alpha=0.3, lw=0.5,
                               linestyle="--", zorder=1)
                    ax.text(ax.get_xlim()[0], y, f" H{hz_num}", fontsize=5,
                            color="#cc5500", va="center", ha="left",
                            zorder=10, fontweight="bold",
                            bbox=dict(boxstyle="round,pad=0.1",
                                      facecolor="white", alpha=0.7,
                                      edgecolor="none"))
                labeled.add(m)
            prev_m = m

    # ──── Legend ──────────────────────────────────────────────────────

    def _draw_legend(self):
        """Add a compact colour legend for logs and regions."""
        # Log legend
        handles = []
        for lname in self._show_logs:
            style = LOG_STYLES.get(lname, _DEFAULT_LOG_STYLE)
            h = plt.Line2D([0], [0], color=style["color"], lw=1.5, label=lname)
            handles.append(h)

        # Region legend (first few IDs)
        if self._show_regions:
            for i in range(1, min(11, len(LITHO_PALETTE))):
                c = LITHO_PALETTE[i]
                h = plt.Rectangle((0, 0), 1, 1, fc=c, ec="#888", lw=0.3,
                                  label=f"ID {i}")
                handles.append(h)

        if handles:
            self.fig.legend(handles=handles, loc="lower center",
                            ncol=min(len(handles), 10), fontsize=6,
                            frameon=True, framealpha=0.8, edgecolor="#ccc",
                            borderpad=0.3, handlelength=1.2,
                            columnspacing=0.8)

    # ──── Mouse interaction ──────────────────────────────────────────

    def _on_hover(self, event):
        if event.inaxes is None:
            self.hover_info.emit("")
            return

        ax = event.inaxes
        x, y = event.xdata, event.ydata
        if x is None or y is None:
            return

        # Find which well this axis belongs to
        for wi, (log_axes) in enumerate(self._well_axes):
            if ax in log_axes:
                track_idx = log_axes.index(ax)
                if wi < len(self._wells.wells if self._wells else []):
                    well = self._wells.wells[wi]
                    log_name = self._show_logs[track_idx] if track_idx < len(self._show_logs) else "?"
                    self.hover_info.emit(
                        f"{well.name}  |  Depth: {y:.1f}  |  {log_name}: {x:.3g}")
                return

        self.hover_info.emit(f"Depth: {y:.1f}")

    def _on_click(self, event):
        if event.inaxes is None:
            return
        for wi, log_axes in enumerate(self._well_axes):
            if event.inaxes in log_axes:
                self.well_clicked.emit(wi)
                return


# ═══════════════════════════════════════════════════════════════════════════
#  CorrelationPlotWindow — the full standalone / embeddable window
# ═══════════════════════════════════════════════════════════════════════════

class CorrelationPlotWindow(QMainWindow):
    """Professional interactive correlation panel window.

    Can be used standalone or embedded as a widget in WeCo Studio.
    Supports both input QC (wells only) and result viewing (wells + correlations).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("WeCo Correlation Viewer")
        self.setMinimumSize(900, 600)

        # ── Central widget ──────────────────────────────────────────
        central = QWidget()
        self.setCentralWidget(central)
        main_lo = QVBoxLayout(central)
        main_lo.setContentsMargins(0, 0, 0, 0)
        main_lo.setSpacing(0)

        # Splitter: sidebar | canvas
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        main_lo.addWidget(self._splitter)

        # ── Sidebar (controls) ──────────────────────────────────────
        sidebar_scroll = QScrollArea()
        sidebar_scroll.setFixedWidth(230)
        sidebar_scroll.setWidgetResizable(True)
        sidebar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sidebar = QWidget()
        sidebar.setStyleSheet("""
            QWidget { background: #f7f8fa; }
            QGroupBox { font-weight: bold; border: 1px solid #ddd;
                        border-radius: 4px; margin-top: 10px; padding-top: 18px; }
            QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }
        """)
        sb_lo = QVBoxLayout(sidebar)
        sb_lo.setContentsMargins(6, 6, 6, 6)
        sb_lo.setSpacing(4)

        # Mode
        mode_grp = QGroupBox("View Mode")
        mode_lo = QFormLayout(mode_grp)
        self._mode_combo = QComboBox()
        self._mode_combo.addItems(["All Wells", "Input QC (no result)", "Selected Wells"])
        self._mode_combo.currentIndexChanged.connect(self._on_config_change)
        mode_lo.addRow("Mode:", self._mode_combo)
        sb_lo.addWidget(mode_grp)

        # Correlation
        cor_grp = QGroupBox("Correlation")
        cor_lo = QFormLayout(cor_grp)
        self._cor_spin = QSpinBox()
        self._cor_spin.setRange(0, 0)
        self._cor_spin.valueChanged.connect(self._on_cor_change)
        cor_lo.addRow("Cor #:", self._cor_spin)
        self._cost_label = QLabel("—")
        self._cost_label.setFont(QFont("Monospace", 9))
        cor_lo.addRow("Cost:", self._cost_label)
        self._max_lines_spin = QSpinBox()
        self._max_lines_spin.setRange(0, 10000)
        self._max_lines_spin.setValue(200)
        self._max_lines_spin.setSpecialValueText("All")
        self._max_lines_spin.valueChanged.connect(self._on_config_change)
        cor_lo.addRow("Max lines:", self._max_lines_spin)
        self._cor_color_cb = QCheckBox("Colour by cost")
        self._cor_color_cb.setChecked(True)
        self._cor_color_cb.toggled.connect(self._on_config_change)
        cor_lo.addRow(self._cor_color_cb)
        self._show_cor_cb = QCheckBox("Show cor. lines")
        self._show_cor_cb.setChecked(True)
        self._show_cor_cb.toggled.connect(self._on_config_change)
        cor_lo.addRow(self._show_cor_cb)
        self._show_hz_cb = QCheckBox("Horizon labels")
        self._show_hz_cb.setChecked(True)
        self._show_hz_cb.toggled.connect(self._on_config_change)
        cor_lo.addRow(self._show_hz_cb)
        sb_lo.addWidget(cor_grp)

        # Logs
        log_grp = QGroupBox("Log Tracks")
        log_lo = QVBoxLayout(log_grp)
        self._log_checks: list[QCheckBox] = []
        self._log_container = QWidget()
        self._log_container_lo = QVBoxLayout(self._log_container)
        self._log_container_lo.setContentsMargins(0, 0, 0, 0)
        self._log_container_lo.setSpacing(2)
        log_lo.addWidget(self._log_container)
        self._fill_cb = QCheckBox("Log fill")
        self._fill_cb.setChecked(True)
        self._fill_cb.toggled.connect(self._on_config_change)
        log_lo.addWidget(self._fill_cb)
        sb_lo.addWidget(log_grp)

        # Regions
        reg_grp = QGroupBox("Region Strips")
        reg_lo = QVBoxLayout(reg_grp)
        self._reg_checks: list[QCheckBox] = []
        self._reg_container = QWidget()
        self._reg_container_lo = QVBoxLayout(self._reg_container)
        self._reg_container_lo.setContentsMargins(0, 0, 0, 0)
        self._reg_container_lo.setSpacing(2)
        reg_lo.addWidget(self._reg_container)
        sb_lo.addWidget(reg_grp)

        # Display
        disp_grp = QGroupBox("Display")
        disp_lo = QFormLayout(disp_grp)
        self._depth_combo = QComboBox()
        self._depth_combo.addItem("(auto)", None)
        self._depth_combo.currentIndexChanged.connect(self._on_config_change)
        disp_lo.addRow("Depth:", self._depth_combo)
        self._names_cb = QCheckBox("Well names")
        self._names_cb.setChecked(True)
        self._names_cb.toggled.connect(self._on_config_change)
        disp_lo.addRow(self._names_cb)
        self._legend_cb = QCheckBox("Legend")
        self._legend_cb.setChecked(True)
        self._legend_cb.toggled.connect(self._on_config_change)
        disp_lo.addRow(self._legend_cb)
        sb_lo.addWidget(disp_grp)

        # Well order
        order_grp = QGroupBox("Well Order")
        order_lo = QVBoxLayout(order_grp)
        self._order_combo = QComboBox()
        self._order_combo.addItems(["Result order", "Input order", "By X coord", "By Y coord"])
        self._order_combo.currentIndexChanged.connect(self._on_order_change)
        order_lo.addWidget(self._order_combo)
        # Move up / down buttons
        btn_lo = QHBoxLayout()
        self._btn_up = QPushButton("Move Up")
        self._btn_up.setEnabled(False)
        self._btn_up.clicked.connect(self._move_well_up)
        btn_lo.addWidget(self._btn_up)
        self._btn_down = QPushButton("Move Down")
        self._btn_down.setEnabled(False)
        self._btn_down.clicked.connect(self._move_well_down)
        btn_lo.addWidget(self._btn_down)
        order_lo.addLayout(btn_lo)
        self._selected_well = -1
        sb_lo.addWidget(order_grp)

        sb_lo.addStretch()
        sidebar_scroll.setWidget(sidebar)

        # ── Canvas area ─────────────────────────────────────────────
        canvas_widget = QWidget()
        canvas_lo = QVBoxLayout(canvas_widget)
        canvas_lo.setContentsMargins(0, 0, 0, 0)
        canvas_lo.setSpacing(0)

        self._canvas = CorrelationPlotWidget(canvas_widget, dpi=100)
        self._toolbar = NavigationToolbar2QT(self._canvas, canvas_widget)
        self._toolbar.setStyleSheet("QToolBar { background: #f0f0f0; border-bottom: 1px solid #ddd; }")
        canvas_lo.addWidget(self._toolbar)
        canvas_lo.addWidget(self._canvas, 1)

        self._splitter.addWidget(sidebar_scroll)
        self._splitter.addWidget(canvas_widget)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setCollapsible(0, True)
        self._splitter.setCollapsible(1, False)

        # Status bar
        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._canvas.hover_info.connect(self._status.showMessage)
        self._canvas.well_clicked.connect(self._on_well_clicked)

        # ── Menu bar ────────────────────────────────────────────────
        mb = self.menuBar()
        file_menu = mb.addMenu("&File")
        act_png = QAction("Export &PNG…", self)
        act_png.triggered.connect(self._export_png)
        file_menu.addAction(act_png)
        act_svg = QAction("Export &SVG…", self)
        act_svg.triggered.connect(self._export_svg)
        file_menu.addAction(act_svg)
        act_pdf = QAction("Export P&DF…", self)
        act_pdf.triggered.connect(self._export_pdf)
        file_menu.addAction(act_pdf)
        file_menu.addSeparator()
        act_close = QAction("&Close", self)
        act_close.triggered.connect(self.close)
        file_menu.addAction(act_close)

        # Data
        self._wells: Optional[WellList] = None
        self._res: Optional[ResFile] = None
        self._cost_matrix: Optional[CostMatrix] = None
        self._well_order: Optional[list[int]] = None

    # ════════════════════════════════════════════════════════════════
    #  Public API
    # ════════════════════════════════════════════════════════════════

    def set_wells(self, wl: WellList):
        self._wells = wl
        self._populate_log_region_lists()
        self._populate_depth_combo()
        self._canvas.set_wells(wl)
        self._well_order = None
        self._on_order_change()

    def set_result(self, rf: ResFile, cor_index: int = 0):
        self._res = rf
        self._canvas.set_result(rf, cor_index)
        if rf:
            self._cor_spin.setMaximum(max(0, rf.get_nbr_results() - 1))
            self._cor_spin.setValue(cor_index)
            cost = rf.get_result_cost(cor_index)
            self._cost_label.setText(f"{cost:.6f}")
        self.refresh()

    def set_cost_matrix(self, cm: CostMatrix):
        self._cost_matrix = cm
        self._canvas.set_cost_matrix(cm)

    def refresh(self):
        """Re-read all config from sidebar and redraw."""
        self._apply_config()
        self._canvas.render()

    # ════════════════════════════════════════════════════════════════
    #  Internal
    # ════════════════════════════════════════════════════════════════

    def _populate_log_region_lists(self):
        """Build checkboxes for available logs and regions."""
        # Clear existing
        for cb in self._log_checks:
            cb.setParent(None)
        self._log_checks.clear()
        for cb in self._reg_checks:
            cb.setParent(None)
        self._reg_checks.clear()

        if not self._wells:
            return

        data_names = list(self._wells.get_data_names())
        region_names = list(self._wells.get_region_names())
        logs, _ = _classify_logs(data_names)

        # Priority ordering
        priority = ["GR", "RT", "DEN", "SPT", "CAL", "SON", "NEU",
                     "COND", "MS", "WC"]
        ordered_logs = [l for l in priority if l in logs] + [l for l in logs if l not in priority]

        for i, lname in enumerate(ordered_logs):
            cb = QCheckBox(lname)
            cb.setChecked(i < 2)  # auto-select first 2
            cb.toggled.connect(self._on_config_change)
            self._log_container_lo.addWidget(cb)
            self._log_checks.append(cb)

        for i, rname in enumerate(region_names):
            cb = QCheckBox(rname)
            cb.setChecked(i == 0)  # auto-select first
            cb.toggled.connect(self._on_config_change)
            self._reg_container_lo.addWidget(cb)
            self._reg_checks.append(cb)

    def _populate_depth_combo(self):
        self._depth_combo.blockSignals(True)
        self._depth_combo.clear()
        self._depth_combo.addItem("(auto)", None)
        if self._wells:
            for dn in self._wells.get_data_names():
                if dn.upper() in ("DEPTH", "MD", "TVD", "TVDSS"):
                    self._depth_combo.addItem(dn, dn)
        self._depth_combo.blockSignals(False)

    def _apply_config(self):
        """Push sidebar config into the canvas widget."""
        c = self._canvas

        # Logs
        c.set_show_logs([cb.text() for cb in self._log_checks if cb.isChecked()])

        # Regions
        c.set_show_regions([cb.text() for cb in self._reg_checks if cb.isChecked()])

        # Depth
        dp = self._depth_combo.currentData()
        c.set_depth_prop(dp)

        # Correlation
        c._max_cor_lines = self._max_lines_spin.value()
        c._cor_color_by_cost = self._cor_color_cb.isChecked()
        c._show_cor_lines = self._show_cor_cb.isChecked()
        c._show_horizons = self._show_hz_cb.isChecked()
        c._show_names = self._names_cb.isChecked()
        c._log_fill = self._fill_cb.isChecked()
        c._show_legend = self._legend_cb.isChecked()

        # Well order
        c.set_well_order(self._well_order)

        # Result
        if self._res:
            c.set_result(self._res, self._cor_spin.value())

    def _on_config_change(self, *_):
        self.refresh()

    def _on_cor_change(self, idx):
        if self._res:
            cost = self._res.get_result_cost(idx)
            self._cost_label.setText(f"{cost:.6f}")
        self.refresh()

    def _on_order_change(self, *_):
        if not self._wells:
            return
        n = len(self._wells.wells)
        mode = self._order_combo.currentIndex()
        if mode == 0 and self._res:
            # result order
            self._well_order = list(self._res.well_id)
        elif mode == 2:
            # sort by X
            self._well_order = sorted(range(n), key=lambda i: self._wells.wells[i].x)
        elif mode == 3:
            # sort by Y
            self._well_order = sorted(range(n), key=lambda i: self._wells.wells[i].y)
        else:
            # input order
            self._well_order = list(range(n))
        self.refresh()

    def _on_well_clicked(self, idx):
        self._selected_well = idx
        self._btn_up.setEnabled(idx > 0)
        self._btn_down.setEnabled(
            self._well_order is not None and idx < len(self._well_order) - 1)
        if self._wells and self._well_order and 0 <= idx < len(self._well_order):
            wi = self._well_order[idx]
            w = self._wells.wells[wi]
            self._status.showMessage(
                f"Selected: {w.name}  (well #{wi}, {w.size} markers, "
                f"x={w.x:.1f} y={w.y:.1f})",
                5000)

    def _move_well_up(self):
        if self._well_order and self._selected_well > 0:
            i = self._selected_well
            self._well_order[i - 1], self._well_order[i] = (
                self._well_order[i], self._well_order[i - 1])
            self._selected_well -= 1
            self._order_combo.blockSignals(True)
            self._order_combo.setCurrentIndex(1)  # switch to "Input order" label
            self._order_combo.blockSignals(False)
            self.refresh()

    def _move_well_down(self):
        if self._well_order and self._selected_well < len(self._well_order) - 1:
            i = self._selected_well
            self._well_order[i + 1], self._well_order[i] = (
                self._well_order[i], self._well_order[i + 1])
            self._selected_well += 1
            self._order_combo.blockSignals(True)
            self._order_combo.setCurrentIndex(1)
            self._order_combo.blockSignals(False)
            self.refresh()

    # ── Export ───────────────────────────────────────────────────────

    def _export_png(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export PNG", "correlation.png", "PNG (*.png)")
        if path:
            self._canvas.fig.savefig(path, dpi=200, bbox_inches="tight",
                                      facecolor="white")
            self._status.showMessage(f"Exported {path}", 3000)

    def _export_svg(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export SVG", "correlation.svg", "SVG (*.svg)")
        if path:
            self._canvas.fig.savefig(path, format="svg", bbox_inches="tight")
            self._status.showMessage(f"Exported {path}", 3000)

    def _export_pdf(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export PDF", "correlation.pdf", "PDF (*.pdf)")
        if path:
            self._canvas.fig.savefig(path, format="pdf", bbox_inches="tight")
            self._status.showMessage(f"Exported {path}", 3000)

    # ── Widget for embedding (returns the central widget, not the QMainWindow) ──

    def as_widget(self) -> QWidget:
        """Return the central widget for embedding in another layout."""
        return self.centralWidget()


# ═══════════════════════════════════════════════════════════════════════════
#  Standalone entry point
# ═══════════════════════════════════════════════════════════════════════════

def main():
    """Launch the correlation plot viewer as a standalone application."""
    import argparse
    parser = argparse.ArgumentParser(description="WeCo Correlation Viewer")
    parser.add_argument("--wells", "-w", help="Wells file path")
    parser.add_argument("--result", "-r", help="Result file path")
    parser.add_argument("--cost-matrix", "-c", help="Cost matrix file path")
    parser.add_argument("--cor", type=int, default=0, help="Correlation index")
    args = parser.parse_args()

    app = QApplication([])
    win = CorrelationPlotWindow()
    win.show()

    if args.wells:
        wl = WellList(args.wells)
        win.set_wells(wl)
    if args.result:
        rf = ResFile(args.result)
        win.set_result(rf, args.cor)
    if args.cost_matrix:
        cm = CostMatrix(args.cost_matrix)
        win.set_cost_matrix(cm)

    win.refresh()
    app.exec()


if __name__ == "__main__":
    main()
