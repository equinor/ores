#!/usr/bin/env python3
"""
WeCo Demo Runner — Interactive GUI
====================================
PyQt6 application for running WeCo example datasets interactively.
Allows selecting datasets, tweaking parameters, running correlations,
and viewing result plots inline.

Usage:
    source ~/.venv/bin/activate
    python demo_gui.py
"""

import sys
import os
import io
from pathlib import Path
from contextlib import redirect_stdout, redirect_stderr

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QTreeWidget, QTreeWidgetItem, QLabel, QPushButton,
    QTextEdit, QGroupBox, QFormLayout, QDoubleSpinBox, QSpinBox,
    QComboBox, QLineEdit, QTabWidget, QScrollArea, QCheckBox,
    QProgressBar, QFrame, QSizePolicy, QFileDialog
)
from PyQt6.QtGui import QPixmap, QFont, QColor, QTextCursor, QIcon
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize, QTimer

from weco.ext import ProjectExt
from weco.data import WellList, ResFile
from weco.engine import get_version

# ═══════════════════════════════════════════════════════════════════════════
#  Dataset Definitions (same as auto_run_examples.py)
# ═══════════════════════════════════════════════════════════════════════════

SCRIPT_DIR = Path(__file__).resolve().parent.parent  # bin/ → project root
DATA_DIR = SCRIPT_DIR / "data"
OUTPUT_DIR = SCRIPT_DIR / "output"

WELL_COLORS = plt.cm.tab10.colors

# Full option reset dict to prevent global state leakage
RESET_OPTS = {
    "no_crossing": "", "no_crossing2": "", "no_crossing3": "",
    "same_region": "", "same_region2": "", "same_region3": "",
    "polarity_region": "", "var_region": "",
    "var_data": "", "var_data2": "", "var_data3": "",
    "var_data4": "", "var_data5": "",
    "var_weight": 1.0, "var_weight2": 1.0, "var_weight3": 1.0,
    "var_weight4": 1.0, "var_weight5": 1.0,
    "dist_distal": "", "dist_facies": "",
    "gap_cost_func": "", "const_gap_cost": 0.0,
    "const_gap_cost_start": -1.0, "const_gap_cost_end": -1.0,
    "multi_dist_distal": "", "multi_dist_facies": "",
}

DATASETS = {
    "1_variance_weights": {
        "title": "Variance Cost Weight Sweep",
        "subtitle": "3 synthetic wells · 2 data properties",
        "description": (
            "Three synthetic wells with two data properties (VarData1, VarData2).\n"
            "Sweep the relative weight between the two properties to see how\n"
            "changing var-weight steers the correlation result."
        ),
        "wells": DATA_DIR / "data_set_1.1" / "wells.txt",
        "runs": [
            {"name": "VarData1 only", "opts": {"var_data": "VarData1", "var_weight": 1.0,
                                               "var_data2": "VarData2", "var_weight2": 0.0}},
            {"name": "VarData2 only", "opts": {"var_data": "VarData1", "var_weight": 0.0,
                                               "var_data2": "VarData2", "var_weight2": 1.0}},
            {"name": "Equal 50/50", "opts": {"var_data": "VarData1", "var_weight": 0.5,
                                             "var_data2": "VarData2", "var_weight2": 0.5}},
            {"name": "Favor1 70/30", "opts": {"var_data": "VarData1", "var_weight": 0.7,
                                              "var_data2": "VarData2", "var_weight2": 0.3}},
            {"name": "Favor2 30/70", "opts": {"var_data": "VarData1", "var_weight": 0.3,
                                              "var_data2": "VarData2", "var_weight2": 0.7}},
        ],
        "common_opts": {"cost_function": "composite", "order": "linear",
                        "max_cor": 10, "nbr_cor": 10, "out_nbr_cor": 10},
    },
    "2_no_crossing": {
        "title": "No-Crossing Constraint",
        "subtitle": "3 synthetic wells · region constraint",
        "description": (
            "Adds no-crossing constraint on region 'NoCrossing' which forces\n"
            "correlation lines to respect zone ordering (stratigraphic units).\n"
            "Demonstrates hard constraints on the correlation graph."
        ),
        "wells": DATA_DIR / "data_set_1.2" / "wells.txt",
        "runs": [
            {"name": "With NoCrossing", "opts": {"var_data": "VarData1", "no_crossing": "NoCrossing"}},
        ],
        "common_opts": {"cost_function": "composite", "order": "linear",
                        "max_cor": 10, "nbr_cor": 10, "out_nbr_cor": 10},
    },
    "3_distality": {
        "title": "Distality-Facies Cost",
        "subtitle": "2 real wells · palaeo-geographic cost",
        "description": (
            "Two wells (A, B) with DISTAL, FACIES properties and\n"
            "regions (BIOZONES, SEQUENCE). Uses dist-distal/dist-facies cost\n"
            "to penalise inconsistent facies vs. distality relationships.\n"
            "Order = distality (most-distal well first)."
        ),
        "wells": DATA_DIR / "data_set_3" / "wells.txt",
        "runs": [
            {"name": "Distality (FACIES_1)", "opts": {
                "dist_distal": "DISTAL", "dist_facies": "FACIES_1", "dist_scaling": 1.0}},
        ],
        "common_opts": {"cost_function": "composite", "order": "distality",
                        "max_cor": 50, "nbr_cor": 50, "out_nbr_cor": 50},
    },
    "4_gap_cost": {
        "title": "Gap Cost Exploration",
        "subtitle": "2 real wells · varying gap penalty",
        "description": (
            "Same wells as dataset 3. Explores the effect of const-gap-cost\n"
            "which penalises gaps (missing intervals). Higher gap cost forces\n"
            "more 1-to-1 matching; lower allows more gaps/hiatuses."
        ),
        "wells": DATA_DIR / "data_set_4" / "wells.txt",
        "runs": [
            {"name": "Gap cost = 0", "opts": {"const_gap_cost": 0.0,
                                              "dist_distal": "DISTAL", "dist_facies": "FACIES_1"}},
            {"name": "Gap cost = 5", "opts": {"const_gap_cost": 5.0,
                                              "dist_distal": "DISTAL", "dist_facies": "FACIES_1"}},
            {"name": "Gap cost = 8", "opts": {"const_gap_cost": 8.0,
                                              "dist_distal": "DISTAL", "dist_facies": "FACIES_1"}},
        ],
        "common_opts": {"cost_function": "composite", "order": "distality",
                        "max_cor": 50, "nbr_cor": 50, "out_nbr_cor": 50},
    },
    "5_ordering": {
        "title": "Ordering Strategy Comparison",
        "subtitle": "3 synthetic wells · 3 ordering modes",
        "description": (
            "Same 3 wells with variance cost, but different merge ordering:\n"
            "linear, pyramidal, inverse. Shows how the order in which wells\n"
            "are merged in the task tree affects the best correlation."
        ),
        "wells": DATA_DIR / "data_set_1.1" / "wells.txt",
        "runs": [
            {"name": "Linear", "opts": {"order": "linear"}},
            {"name": "Pyramidal", "opts": {"order": "pyramidal"}},
            {"name": "Inverse", "opts": {"order": "inverse"}},
        ],
        "common_opts": {"cost_function": "composite", "var_data": "VarData1",
                        "var_weight": 1.0, "max_cor": 10, "nbr_cor": 10,
                        "out_nbr_cor": 10},
    },
}


# ═══════════════════════════════════════════════════════════════════════════
#  Worker Thread
# ═══════════════════════════════════════════════════════════════════════════

class CorrelationWorker(QThread):
    """Run a single correlation in a background thread."""
    finished = pyqtSignal(str, object, object, str)  # run_name, res_file, well_list, log_text
    progress = pyqtSignal(str)  # status message

    def __init__(self, run_name, wells_path, opts, parent=None):
        super().__init__(parent)
        self.run_name = run_name
        self.wells_path = wells_path
        self.opts = opts

    def run(self):
        log_buf = io.StringIO()
        try:
            with redirect_stdout(log_buf), redirect_stderr(log_buf):
                project = ProjectExt()
                project.set_options_ext(**RESET_OPTS)
                project.set_options_ext(**self.opts)
                project.run(str(self.wells_path))

            res_file = project.get_res_file()
            well_list = WellList(str(self.wells_path))
            self.finished.emit(self.run_name, res_file, well_list, log_buf.getvalue())
        except Exception as e:
            self.finished.emit(self.run_name, None, None, f"ERROR: {e}\n{log_buf.getvalue()}")


# ═══════════════════════════════════════════════════════════════════════════
#  Plot Generation
# ═══════════════════════════════════════════════════════════════════════════

def generate_plot(well_list, res_file, title, data_name=None, depth_name=None, cor_index=0):
    """Generate a correlation plot and return the PNG path (temp file)."""
    if res_file is None or res_file.get_nbr_results() == 0:
        return None

    n_wells = len(res_file.well_id)
    wells = [well_list.wells[wid] for wid in res_file.well_id]

    def get_depth(well):
        for dn in ("Depth", "DEPTH", "MD"):
            if dn in well.data and well.data[dn]:
                return list(well.data[dn])
        return list(range(well.size))

    depths = [get_depth(w) for w in wells]

    if data_name is None:
        for dname in wells[0].data:
            if dname.upper() not in ("DEPTH", "MD", "TVD", "TVDSS"):
                data_name = dname
                break

    fig_width = max(8, 2.5 * n_wells + 2)
    fig, axes = plt.subplots(1, n_wells, figsize=(fig_width, 7), sharey=False)
    if n_wells == 1:
        axes = [axes]

    fig.suptitle(title, fontsize=11, fontweight="bold")

    for i, (well, ax, depth) in enumerate(zip(wells, axes, depths)):
        ax.set_title(well.name, fontsize=10, color=WELL_COLORS[i % 10])
        ax.invert_yaxis()
        ax.set_ylabel("Depth")

        if data_name and data_name in well.data:
            vals = list(well.data[data_name])[:len(depth)]
            ax.plot(vals, depth[:len(vals)], color=WELL_COLORS[i % 10],
                    linewidth=1.2, label=data_name)
            ax.set_xlabel(data_name)
            ax.legend(fontsize=7, loc="lower right")
        else:
            ax.set_xlim(-0.5, 0.5)
            ax.axvline(0, color=WELL_COLORS[i % 10], linewidth=2)
            ax.set_xlabel("Well Stick")
        ax.grid(True, alpha=0.3)

    # Draw correlation lines
    cid = min(cor_index, res_file.get_nbr_results() - 1)
    path = res_file.get_result_full_path(cid)
    cost = res_file.get_result_cost(cid)

    for step, node in enumerate(path):
        for j in range(n_wells - 1):
            ml = node[j]
            mr = node[j + 1]
            if ml < len(depths[j]) and mr < len(depths[j + 1]):
                yl = depths[j][ml]
                yr = depths[j + 1][mr]
                con = matplotlib.patches.ConnectionPatch(
                    xyA=(1.0, yl), coordsA=axes[j].get_yaxis_transform(),
                    xyB=(0.0, yr), coordsB=axes[j + 1].get_yaxis_transform(),
                    color="gray", alpha=0.5, linewidth=0.7)
                fig.add_artist(con)

    fig.text(0.5, 0.01,
             f"Correlation #{cid}  |  Cost: {cost:.4f}  |  "
             f"{res_file.get_nbr_results()} total correlations",
             ha="center", fontsize=9, style="italic")

    plt.tight_layout(rect=[0, 0.03, 1, 0.94])

    # Save to output dir
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    safe_title = title.replace(" ", "_").replace("/", "_").replace("\n", "_")[:60]
    out_path = OUTPUT_DIR / f"gui_{safe_title}.png"
    fig.savefig(str(out_path), dpi=130, bbox_inches="tight")
    plt.close(fig)
    return str(out_path)


# ═══════════════════════════════════════════════════════════════════════════
#  Main GUI
# ═══════════════════════════════════════════════════════════════════════════

class DemoRunnerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"WeCo {get_version()} — Demo Runner")
        self.setMinimumSize(1100, 700)
        self.resize(1300, 800)

        self._workers = []
        self._run_results = {}  # {run_name: (res_file, well_list, cost)}

        self._init_ui()

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(6, 6, 6, 6)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)

        # ── Left panel: dataset tree ──────────────────────────────────
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)

        header = QLabel("Demo Datasets")
        header.setFont(QFont("", 12, QFont.Weight.Bold))
        left_layout.addWidget(header)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Dataset / Run"])
        self.tree.setMinimumWidth(260)
        self.tree.itemClicked.connect(self._on_tree_click)
        left_layout.addWidget(self.tree)

        # Populate tree
        for ds_key, ds in DATASETS.items():
            parent = QTreeWidgetItem(self.tree, [ds["title"]])
            parent.setData(0, Qt.ItemDataRole.UserRole, ds_key)
            parent.setFont(0, QFont("", 10, QFont.Weight.Bold))
            parent.setToolTip(0, ds["description"])
            for run in ds["runs"]:
                child = QTreeWidgetItem(parent, [f"  {run['name']}"])
                child.setData(0, Qt.ItemDataRole.UserRole, (ds_key, run["name"]))
            parent.setExpanded(True)

        # Buttons
        btn_layout = QHBoxLayout()
        self.btn_run_selected = QPushButton("Run Selected")
        self.btn_run_selected.clicked.connect(self._run_selected)
        self.btn_run_selected.setStyleSheet("QPushButton { font-weight: bold; padding: 6px; }")
        btn_layout.addWidget(self.btn_run_selected)

        self.btn_run_all = QPushButton("Run All")
        self.btn_run_all.clicked.connect(self._run_all)
        btn_layout.addWidget(self.btn_run_all)

        left_layout.addLayout(btn_layout)

        splitter.addWidget(left_panel)

        # ── Right panel: tabs (info / parameters / results / log) ─────
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self.tabs = QTabWidget()
        right_layout.addWidget(self.tabs)

        # Tab 1: Info
        self.info_widget = QWidget()
        info_layout = QVBoxLayout(self.info_widget)
        self.info_title = QLabel("Select a dataset from the tree")
        self.info_title.setFont(QFont("", 13, QFont.Weight.Bold))
        info_layout.addWidget(self.info_title)
        self.info_desc = QLabel("")
        self.info_desc.setWordWrap(True)
        self.info_desc.setFont(QFont("Monospace", 10))
        info_layout.addWidget(self.info_desc)

        self.info_wells = QLabel("")
        self.info_wells.setFont(QFont("", 10))
        info_layout.addWidget(self.info_wells)

        # Parameter override area
        self.param_group = QGroupBox("Parameters (editable before run)")
        param_layout = QFormLayout(self.param_group)
        self.param_widgets = {}
        # We'll populate dynamically based on selection
        info_layout.addWidget(self.param_group)
        info_layout.addStretch()
        self.tabs.addTab(self.info_widget, "Info && Params")

        # Tab 2: Plot (result view)
        self.plot_scroll = QScrollArea()
        self.plot_scroll.setWidgetResizable(True)
        self.plot_container = QWidget()
        self.plot_layout = QVBoxLayout(self.plot_container)
        self.plot_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.plot_scroll.setWidget(self.plot_container)
        self.tabs.addTab(self.plot_scroll, "Results")

        # Tab 3: Engine Log
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Monospace", 9))
        self.tabs.addTab(self.log_text, "Engine Log")

        # Progress bar
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setTextVisible(True)
        right_layout.addWidget(self.progress)

        splitter.addWidget(right_panel)
        splitter.setSizes([300, 1000])

        self.statusBar().showMessage("Ready — select a dataset and click Run")

    # ─── Tree Selection ───────────────────────────────────────────────

    def _on_tree_click(self, item, column):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data is None:
            return

        if isinstance(data, str):
            # Dataset-level click
            ds = DATASETS[data]
            self._show_dataset_info(data, ds)
        elif isinstance(data, tuple):
            # Run-level click
            ds_key, run_name = data
            ds = DATASETS[ds_key]
            self._show_run_info(ds_key, ds, run_name)

    def _show_dataset_info(self, ds_key, ds):
        self.info_title.setText(ds["title"])
        self.info_desc.setText(ds["description"])

        wells_path = ds["wells"]
        if wells_path.exists():
            wl = WellList(str(wells_path))
            well_names = [w.name for w in wl.wells]
            data_names = list(wl.wells[0].data.keys()) if wl.wells else []
            region_names = list(wl.wells[0].region.keys()) if wl.wells else []
            self.info_wells.setText(
                f"Wells ({len(well_names)}): {', '.join(well_names)}\n"
                f"Data: {', '.join(data_names)}\n"
                f"Regions: {', '.join(region_names) if region_names else '(none)'}"
            )
        else:
            self.info_wells.setText(f"Wells file not found: {wells_path}")

        self._populate_params(ds, None)
        self.tabs.setCurrentIndex(0)

    def _show_run_info(self, ds_key, ds, run_name):
        run = next(r for r in ds["runs"] if r["name"] == run_name)
        self.info_title.setText(f"{ds['title']} → {run_name}")
        self.info_desc.setText(ds["description"])

        wells_path = ds["wells"]
        if wells_path.exists():
            wl = WellList(str(wells_path))
            well_names = [w.name for w in wl.wells]
            self.info_wells.setText(f"Wells: {', '.join(well_names)}")
        else:
            self.info_wells.setText("")

        self._populate_params(ds, run)
        self.tabs.setCurrentIndex(0)

    def _populate_params(self, ds, run):
        """Show editable parameters for the selected dataset/run."""
        # Clear existing
        layout = self.param_group.layout()
        while layout.count():
            child = layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self.param_widgets.clear()

        # Merge common + run opts
        opts = dict(ds.get("common_opts", {}))
        if run:
            opts.update(run.get("opts", {}))

        # Create widgets for each param
        for key, val in sorted(opts.items()):
            if key in ("cost_function", "debug_cor_info", "out_file"):
                continue  # skip internal ones

            if isinstance(val, float):
                w = QDoubleSpinBox()
                w.setRange(-100.0, 1000.0)
                w.setDecimals(2)
                w.setSingleStep(0.1)
                w.setValue(val)
            elif isinstance(val, int):
                w = QSpinBox()
                w.setRange(0, 10000)
                w.setValue(val)
            elif key == "order":
                w = QComboBox()
                w.addItems(["linear", "pyramidal", "position", "distality", "inverse"])
                w.setCurrentText(str(val))
            else:
                w = QLineEdit(str(val))

            label = key.replace("_", " ").title()
            layout.addRow(label + ":", w)
            self.param_widgets[key] = w

    def _get_current_opts(self, ds, run):
        """Read current parameter values from widgets."""
        opts = dict(ds.get("common_opts", {}))
        if run:
            opts.update(run.get("opts", {}))

        # Override from widgets
        for key, widget in self.param_widgets.items():
            if isinstance(widget, QDoubleSpinBox):
                opts[key] = widget.value()
            elif isinstance(widget, QSpinBox):
                opts[key] = widget.value()
            elif isinstance(widget, QComboBox):
                opts[key] = widget.currentText()
            elif isinstance(widget, QLineEdit):
                text = widget.text()
                # Try to interpret as number
                try:
                    opts[key] = float(text)
                except ValueError:
                    opts[key] = text

        opts["debug_cor_info"] = 1
        return opts

    # ─── Running ──────────────────────────────────────────────────────

    def _get_selected_runs(self):
        """Return list of (ds_key, run_dict) for current selection."""
        items = self.tree.selectedItems()
        runs = []
        for item in items:
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(data, str):
                # Dataset selected — run all its runs
                ds = DATASETS[data]
                for r in ds["runs"]:
                    runs.append((data, r))
            elif isinstance(data, tuple):
                ds_key, run_name = data
                ds = DATASETS[ds_key]
                r = next(x for x in ds["runs"] if x["name"] == run_name)
                runs.append((ds_key, r))
        return runs

    def _run_selected(self):
        runs = self._get_selected_runs()
        if not runs:
            self.statusBar().showMessage("Nothing selected — click a dataset or run first")
            return
        self._execute_runs(runs)

    def _run_all(self):
        runs = []
        for ds_key, ds in DATASETS.items():
            for r in ds["runs"]:
                runs.append((ds_key, r))
        self._execute_runs(runs)

    def _execute_runs(self, runs):
        """Queue and execute a list of (ds_key, run) tuples."""
        self._pending_runs = list(runs)
        self._total_runs = len(runs)
        self._completed_runs = 0
        self._all_results = []

        # Clear old results display
        self._clear_plots()
        self.log_text.clear()

        self.progress.setVisible(True)
        self.progress.setMaximum(self._total_runs)
        self.progress.setValue(0)
        self.btn_run_selected.setEnabled(False)
        self.btn_run_all.setEnabled(False)

        self._run_next()

    def _run_next(self):
        if not self._pending_runs:
            self._on_all_done()
            return

        ds_key, run = self._pending_runs.pop(0)
        ds = DATASETS[ds_key]

        # Get options (use widget values if this is the currently-displayed run)
        opts = dict(ds.get("common_opts", {}))
        opts.update(run.get("opts", {}))
        opts["debug_cor_info"] = 1

        # Try to use widget overrides if they match
        if self.param_widgets:
            for key, widget in self.param_widgets.items():
                if key in opts:
                    if isinstance(widget, QDoubleSpinBox):
                        opts[key] = widget.value()
                    elif isinstance(widget, QSpinBox):
                        opts[key] = widget.value()
                    elif isinstance(widget, QComboBox):
                        opts[key] = widget.currentText()
                    elif isinstance(widget, QLineEdit):
                        text = widget.text()
                        try:
                            opts[key] = float(text)
                        except ValueError:
                            opts[key] = text

        run_label = f"{ds['title']} / {run['name']}"
        self.statusBar().showMessage(f"Running: {run_label}...")
        self.log_text.append(f"\n{'─'*60}\n  Running: {run_label}\n{'─'*60}\n")

        worker = CorrelationWorker(run_label, ds["wells"], opts)
        worker.finished.connect(lambda name, rf, wl, log: self._on_run_finished(name, rf, wl, log))
        self._workers.append(worker)
        worker.start()

    def _on_run_finished(self, run_name, res_file, well_list, log_text):
        self._completed_runs += 1
        self.progress.setValue(self._completed_runs)

        # Append log
        self.log_text.append(log_text)
        self.log_text.moveCursor(QTextCursor.MoveOperation.End)

        if res_file is not None and res_file.get_nbr_results() > 0:
            cost = res_file.get_result_cost(0)
            n_cor = res_file.get_nbr_results()
            self.log_text.append(
                f"  ✓ {run_name}: cost={cost:.4f}, {n_cor} correlations\n")

            # Generate plot
            plot_path = generate_plot(well_list, res_file, run_name)
            if plot_path:
                self._add_plot(run_name, plot_path, cost, n_cor)
            self._all_results.append((run_name, cost, n_cor))
        else:
            self.log_text.append(f"  ✗ {run_name}: FAILED\n")

        # Proceed to next
        QTimer.singleShot(50, self._run_next)

    def _on_all_done(self):
        self.progress.setVisible(False)
        self.btn_run_selected.setEnabled(True)
        self.btn_run_all.setEnabled(True)

        n = len(self._all_results)
        self.statusBar().showMessage(f"Done — {n} run(s) completed successfully")
        self.tabs.setCurrentIndex(1)  # Switch to Results tab

        # Add summary at bottom of results
        if self._all_results:
            summary = QLabel(self._format_summary())
            summary.setFont(QFont("Monospace", 9))
            summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.plot_layout.addWidget(summary)

    def _format_summary(self):
        lines = ["\n─── Summary ───────────────────────────────────────\n"]
        for name, cost, n_cor in self._all_results:
            lines.append(f"  {name:40s}  cost={cost:.4f}  ({n_cor} cors)")
        return "\n".join(lines)

    # ─── Plot Display ─────────────────────────────────────────────────

    def _clear_plots(self):
        while self.plot_layout.count():
            child = self.plot_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

    def _add_plot(self, title, png_path, cost, n_cor):
        """Add a plot image to the results tab."""
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(4, 4, 4, 4)

        # Title label
        lbl_title = QLabel(f"{title}  —  cost: {cost:.4f}  ({n_cor} correlations)")
        lbl_title.setFont(QFont("", 10, QFont.Weight.Bold))
        frame_layout.addWidget(lbl_title)

        # Image
        pixmap = QPixmap(png_path)
        if not pixmap.isNull():
            # Scale to fit width
            scaled = pixmap.scaledToWidth(
                min(900, self.width() - 350),
                Qt.TransformationMode.SmoothTransformation
            )
            img_label = QLabel()
            img_label.setPixmap(scaled)
            img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            frame_layout.addWidget(img_label)
        else:
            frame_layout.addWidget(QLabel(f"(plot saved to {png_path})"))

        self.plot_layout.addWidget(frame)

    # ─── Export ───────────────────────────────────────────────────────

    def _export_results(self):
        pass  # Future: export all results as PDF/ZIP


# ═══════════════════════════════════════════════════════════════════════════
#  Entry Point
# ═══════════════════════════════════════════════════════════════════════════

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("WeCo Demo Runner")
    app.setStyle("Fusion")

    # Dark-ish palette for a professional look
    from PyQt6.QtGui import QPalette
    palette = app.palette()
    palette.setColor(QPalette.ColorRole.Window, QColor(245, 245, 248))
    palette.setColor(QPalette.ColorRole.Base, QColor(255, 255, 255))
    app.setPalette(palette)

    window = DemoRunnerWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
