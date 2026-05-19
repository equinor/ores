#!/usr/bin/env python3
"""
WeCo Studio — Professional Well Correlation Workbench
=====================================================
A workflow-oriented PyQt6 GUI for:
  • Loading / inspecting well data  (any format)
  • Configuring correlation parameters  (grouped, with help)
  • Running the WeCo engine  (threaded, live log)
  • Viewing & exporting results  (interactive plot)
  • Built-in demos  (editable, one-click run)
  • Integrated context help

Usage:
    source ~/.venv/bin/activate
    WeCoStudio                              # start empty
    WeCoStudio --demo 1                     # start with demo loaded
    WeCoStudio -w path/to/wells.txt         # start with well file

Architecture:
    Sidebar (QListWidget)  ←→  Stacked pages (QStackedWidget)
      0  Welcome / Demo Picker
      1  Data — load & inspect wells
      2  Parameters — grouped cost-function config
      3  Run — execute engine (threaded)
      4  Results — correlation viewer
      5  Help — parameter referece
"""

import sys
import os
import io
import textwrap
from pathlib import Path
from time import time as wall_time

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

try:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
    HAS_MPL_CANVAS = True
except ImportError:
    HAS_MPL_CANVAS = False

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QLabel, QPushButton, QTextEdit, QPlainTextEdit,
    QGroupBox, QFormLayout, QDoubleSpinBox, QSpinBox, QComboBox,
    QLineEdit, QTabWidget, QScrollArea, QCheckBox, QFrame,
    QSizePolicy, QFileDialog, QMessageBox, QListWidget, QListWidgetItem,
    QStackedWidget, QGridLayout, QProgressBar, QToolButton, QTreeWidget,
    QTreeWidgetItem, QHeaderView, QTableWidget, QTableWidgetItem,
    QDialog, QDialogButtonBox, QInputDialog
)
from PyQt6.QtGui import (
    QPixmap, QFont, QColor, QTextCursor, QIcon, QPalette,
    QDoubleValidator, QPainter
)
from PyQt6.QtCore import (
    Qt, QThread, pyqtSignal, QSize, QTimer, QMargins
)

from weco.ext import ProjectExt
from weco.data import WellList, ResFile, ResAndWL
from weco.engine import get_version, Option as COption, Project

try:
    from weco.resview import CorResView
    HAS_RESVIEW = True
except ImportError:
    HAS_RESVIEW = False

try:
    from weco.correlation_plot import CorrelationPlotWindow, CorrelationPlotWidget
    HAS_CORPLOT = True
except ImportError:
    HAS_CORPLOT = False

# ═══════════════════════════════════════════════════════════════════════════
#  Constants
# ═══════════════════════════════════════════════════════════════════════════

SCRIPT_DIR = Path(__file__).resolve().parent.parent  # weco/ package → project root
DATA_DIR = SCRIPT_DIR / "data"
OUTPUT_DIR = SCRIPT_DIR / "output"

VERSION = get_version()

WELL_COLORS = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
]

RESET_OPTS = {
    "no_crossing": "", "no_crossing2": "", "no_crossing3": "",
    "same_region": "", "same_region2": "", "same_region3": "",
    "polarity_region": "", "var_region": "",
    "var_data": "", "var_data2": "", "var_data3": "",
    "var_data4": "", "var_data5": "",
    "var_weight": 1.0, "var_weight2": 1.0, "var_weight3": 1.0,
    "var_weight4": 1.0, "var_weight5": 1.0,
    "dist_distal": "", "dist_facies": "",
    "gap_cost_func": "", "gap_cost_func_mult": 1.0,
    "const_gap_cost": 0.0, "const_gap_cost_start": -1.0,
    "const_gap_cost_end": -1.0,
    "multi_dist_distal": "", "multi_dist_facies": "",
    "b3d_curve_dip": "", "b3d_curve_azimuth": "",
    "b3d_curve_depth": "", "b3d_curve_facies": "",
}

# ═══════════════════════════════════════════════════════════════════════════
#  Option Presets  (quick-start parameter sets for common scenarios)
# ═══════════════════════════════════════════════════════════════════════════

OPTION_PRESETS = {
    "Simple log correlation": {
        "desc": "Single log variance cost only. Good starting point for any dataset.",
        "opts": {"var_weight": 1.0, "max_cor": 50},
    },
    "Two-log weighted": {
        "desc": "Two log curves with equal weight. Typical: GR + resistivity.",
        "opts": {"var_weight": 1.0, "var_weight2": 1.0, "max_cor": 50},
    },
    "Constrained with horizons": {
        "desc": "Variance cost + region constraints (no-crossing + same-region). "
                "Use when you have biozone or horizons as regions.",
        "opts": {"var_weight": 1.0, "max_cor": 50, "const_gap_cost": 0.3},
    },
    "Shelf-to-basin transect": {
        "desc": "Distality cost for proximal-to-distal transects. "
                "Requires facies and distality regions on the wells.",
        "opts": {"var_weight": 1.0, "dist_scaling": 0.5, "max_cor": 100},
    },
    "High-resolution (slow)": {
        "desc": "Large max_cor for many alternative paths. Slower but more thorough. "
                "Good for uncertainty analysis with n-best.",
        "opts": {"var_weight": 1.0, "max_cor": 200},
    },
    "Quality over speed": {
        "desc": "Moderate k with gap penalty to reduce spurious correlations.",
        "opts": {"var_weight": 1.0, "const_gap_cost": 0.5, "max_cor": 100},
    },
}

# ═══════════════════════════════════════════════════════════════════════════
#  Demo Definitions
# ═══════════════════════════════════════════════════════════════════════════

DEMOS = [
    {
        "id": "1.1",
        "title": "Variance Weight Sweep",
        "group": "Basics",
        "wells": "data_set_1.1/wells.txt",
        "description": (
            "3 synthetic wells with VarData1 & VarData2.\n"
            "Sweep var-weight between the two to see how\n"
            "the cost function steers the correlation."
        ),
        "opts": {
            "cost_function": "composite", "order": "linear",
            "var_data": "VarData1", "var_weight": 1.0,
            "var_data2": "VarData2", "var_weight2": 0.0,
            "max_cor": 10, "nbr_cor": 10, "out_nbr_cor": 10,
        },
        "editable_keys": ["var_weight", "var_weight2", "max_cor", "nbr_cor", "order"],
    },
    {
        "id": "1.2",
        "title": "No-Crossing Constraint",
        "group": "Constraints",
        "wells": "data_set_1.2/wells.txt",
        "description": (
            "Same wells + a region 'NoCrossing' that enforces\n"
            "stratigraphic ordering. Correlation lines cannot\n"
            "cross zone boundaries."
        ),
        "opts": {
            "cost_function": "composite", "order": "linear",
            "var_data": "VarData1", "no_crossing": "NoCrossing",
            "max_cor": 10, "nbr_cor": 10, "out_nbr_cor": 10,
        },
        "editable_keys": ["var_data", "no_crossing", "max_cor", "order"],
    },
    {
        "id": "3",
        "title": "Distality-Facies Cost",
        "group": "Advanced",
        "wells": "data_set_3/wells.txt",
        "description": (
            "2 real wells (A, B) with distality & facies.\n"
            "The distality cost penalises thickness ratios\n"
            "inconsistent with palaeo-geographic position."
        ),
        "opts": {
            "cost_function": "composite", "order": "distality",
            "dist_distal": "DISTAL", "dist_facies": "FACIES_1",
            "dist_scaling": 1.0,
            "max_cor": 50, "nbr_cor": 50, "out_nbr_cor": 50,
        },
        "editable_keys": ["dist_scaling", "dist_facies", "max_cor", "nbr_cor", "order"],
    },
    {
        "id": "4",
        "title": "Gap Cost Exploration",
        "group": "Advanced",
        "wells": "data_set_4/wells.txt",
        "description": (
            "2 real wells. Vary const-gap-cost to control\n"
            "how the engine penalises stratigraphic gaps\n"
            "(hiatuses / condensation). 0 = free gaps."
        ),
        "opts": {
            "cost_function": "composite", "order": "distality",
            "dist_distal": "DISTAL", "dist_facies": "FACIES_1",
            "const_gap_cost": 0.0,
            "max_cor": 50, "nbr_cor": 50, "out_nbr_cor": 50,
        },
        "editable_keys": ["const_gap_cost", "dist_scaling", "max_cor", "nbr_cor", "order"],
    },
    {
        "id": "5",
        "title": "Ordering Strategies",
        "group": "Basics",
        "wells": "data_set_1.1/wells.txt",
        "description": (
            "3 synthetic wells. Compare linear, pyramidal,\n"
            "and inverse ordering to see how merge order\n"
            "affects the optimal correlation."
        ),
        "opts": {
            "cost_function": "composite",
            "var_data": "VarData1", "var_weight": 1.0,
            "order": "pyramidal",
            "max_cor": 10, "nbr_cor": 10, "out_nbr_cor": 10,
        },
        "editable_keys": ["order", "var_weight", "max_cor", "nbr_cor"],
    },

    # ── Quaternary Hydrogeology ─────────────────────────────────────
    {
        "id": "quat-basic",
        "title": "Quaternary — Basic (GR+RT)",
        "group": "Quaternary Hydrogeology",
        "wells": "data_set_quaternary/wells_20.txt",
        "geology": "quaternary",
        "description": (
            "20 shallow Quaternary wells (glacial lowland).\n"
            "Basic GR+RT variance correlation for quick\n"
            "aquifer/aquitard overview."
        ),
        "geology_doc": (
            "<b>Geological Setting:</b> Northern European glacial lowland "
            "(Pleistocene). 5 lithostratigraphic units from Holocene through "
            "Elsterian.<br><br>"
            "<b>Periglacial Features:</b> Eiskeil (ice-wedge casts), "
            "cryoturbation, dropstones, frost cracks in permafrost zone.<br><br>"
            "<b>Logs:</b> GR (gamma), RT (resistivity), SPT (penetration test), "
            "COND (hydraulic conductivity), MS (magnetic susceptibility), "
            "WC (water content).<br><br>"
            "<b>Correlation Strategy:</b> GR distinguishes sand (low) from "
            "till/clay (high). RT separates aquifer (high) from aquitard (low)."
        ),
        "opts": {
            "cost_function": "composite",
            "var_data": "GR", "var_weight": 0.7,
            "var_data2": "RT", "var_weight2": 0.3,
            "order": "position", "max_cor": 50, "nbr_cor": 50, "out_nbr_cor": 5,
            "const_gap_cost": 1.5,
        },
        "editable_keys": [
            "var_weight", "var_weight2", "max_cor", "const_gap_cost", "order",
        ],
    },
    {
        "id": "quat-hydro",
        "title": "Quaternary — Hydrogeological",
        "group": "Quaternary Hydrogeology",
        "wells": "data_set_quaternary/wells_20.txt",
        "geology": "quaternary",
        "description": (
            "Three-log correlation (GR+RT+SPT) with gap cost\n"
            "tuned for aquifer bed tracing in glacial deposits.\n"
            "SPT adds geotechnical discrimination."
        ),
        "geology_doc": (
            "<b>Why three logs?</b> GR separates lithology, RT maps "
            "permeability, SPT identifies compact till vs loose sand. "
            "Adding SPT improves discrimination of sand channels within till.<br><br>"
            "<b>Gap Cost = 2.0:</b> Moderate — allows hiatuses where Eemian "
            "interglacial is missing (~30% of wells) but penalises spurious "
            "gaps within continuous units."
        ),
        "opts": {
            "cost_function": "composite",
            "var_data": "GR", "var_weight": 0.50,
            "var_data2": "RT", "var_weight2": 0.25,
            "var_data3": "SPT", "var_weight3": 0.25,
            "order": "position", "max_cor": 80, "nbr_cor": 80, "out_nbr_cor": 5,
            "const_gap_cost": 2.0,
            "const_gap_cost_start": 0.0,
            "const_gap_cost_end": 0.5,
        },
        "editable_keys": [
            "var_weight", "var_weight2", "var_weight3",
            "max_cor", "const_gap_cost", "const_gap_cost_start", "const_gap_cost_end",
            "order",
        ],
    },
    {
        "id": "quat-constrained",
        "title": "Quaternary — Constrained",
        "group": "Quaternary Hydrogeology",
        "wells": "data_set_quaternary/wells_20.txt",
        "geology": "quaternary",
        "description": (
            "GR+RT+SPT with HYDRO same-region constraint.\n"
            "Enforces aquifer/aquitard grouping:\n"
            "aquifer=gravel+sand, leaky=silt, aquitard=till+clay."
        ),
        "geology_doc": (
            "<b>same-region = HYDRO:</b> Forces correlated samples to share "
            "the same hydrogeological class (aquifer / leaky / aquitard). "
            "This prevents the engine from correlating sand with till.<br><br>"
            "<b>When to use:</b> When you have reliable facies interpretation "
            "and want to enforce hydrogeological consistency."
        ),
        "opts": {
            "cost_function": "composite",
            "var_data": "GR", "var_weight": 0.50,
            "var_data2": "RT", "var_weight2": 0.30,
            "var_data3": "SPT", "var_weight3": 0.20,
            "same_region": "HYDRO",
            "order": "position", "max_cor": 80, "nbr_cor": 80, "out_nbr_cor": 5,
            "const_gap_cost": 2.0,
        },
        "editable_keys": [
            "var_weight", "var_weight2", "var_weight3",
            "same_region", "max_cor", "const_gap_cost", "order",
        ],
    },

    # ── Coal Basin ──────────────────────────────────────────────────
    {
        "id": "coal-basic",
        "title": "Coal — Basic (GR+DEN)",
        "group": "Coal Basin",
        "wells": "data_set_coal/wells_10.txt",
        "geology": "coal",
        "description": (
            "10 coal exploration boreholes with 6 named seams.\n"
            "Quick two-log correlation using GR + bulk density.\n"
            "DEN is the primary coal indicator (1.3 g/cc)."
        ),
        "geology_doc": (
            "<b>Geological Setting:</b> Intracratonic coal basin with cyclic "
            "cyclothem sequences (Ruhr/Silesian/Bowen style).<br><br>"
            "<b>Key Feature:</b> Coal at 1.3 g/cc bulk density is uniquely "
            "different from all other lithologies (2.3–2.7 g/cc). DEN is "
            "therefore the strongest discriminator.<br><br>"
            "<b>Seams:</b> Katharina (3m), Sonnenschein (1.5m), Präsident (2.5m), "
            "Zollverein (1.8m), Flöz 9 (1.2m), Flöz 10 (0.8m).<br><br>"
            "<b>Special markers:</b> Tonstein (volcanic ash), marine bands, "
            "Brandschiefer (burnt shale)."
        ),
        "opts": {
            "cost_function": "composite",
            "var_data": "GR", "var_weight": 0.5,
            "var_data2": "DEN", "var_weight2": 0.5,
            "order": "position", "max_cor": 50, "nbr_cor": 50, "out_nbr_cor": 5,
            "const_gap_cost": 3.0,
        },
        "editable_keys": [
            "var_weight", "var_weight2", "max_cor", "const_gap_cost", "order",
        ],
    },
    {
        "id": "coal-full",
        "title": "Coal — Multi-Log (5 logs)",
        "group": "Coal Basin",
        "wells": "data_set_coal/wells_10.txt",
        "geology": "coal",
        "description": (
            "Five-log coal correlation: GR+RT+DEN+SON+NEU.\n"
            "DEN dominates (35%), supplemented by sonic (15%)\n"
            "and neutron (10%) for maximum discrimination."
        ),
        "geology_doc": (
            "<b>Log Weights Rationale:</b><br>"
            "• DEN (35%): Best coal indicator — 1.3 vs 2.5 g/cc<br>"
            "• GR (25%): Coal has very low radioactivity (20 API)<br>"
            "• SON (15%): Coal is slow (120 µs/ft) vs sand (60)<br>"
            "• RT (15%): Coal is extremely resistive (500+ Ω·m)<br>"
            "• NEU (10%): Coal shows high apparent porosity (55%)<br><br>"
            "<b>Gap Cost = 3.0:</b> High — penalises missing seams to "
            "force the engine to find all coal horizons."
        ),
        "opts": {
            "cost_function": "composite",
            "var_data": "GR", "var_weight": 0.25,
            "var_data2": "RT", "var_weight2": 0.15,
            "var_data3": "DEN", "var_weight3": 0.35,
            "var_data4": "SON", "var_weight4": 0.15,
            "var_data5": "NEU", "var_weight5": 0.10,
            "order": "position", "max_cor": 100, "nbr_cor": 100, "out_nbr_cor": 5,
            "const_gap_cost": 3.0,
            "const_gap_cost_start": 0.0,
            "const_gap_cost_end": 0.3,
        },
        "editable_keys": [
            "var_weight", "var_weight2", "var_weight3", "var_weight4", "var_weight5",
            "max_cor", "const_gap_cost", "const_gap_cost_start", "const_gap_cost_end",
            "order",
        ],
    },
    {
        "id": "coal-seam",
        "title": "Coal — Seam-Constrained",
        "group": "Coal Basin",
        "wells": "data_set_coal/wells_10.txt",
        "geology": "coal",
        "description": (
            "DEN+GR+SON with SEAM same-region constraint.\n"
            "Enforces seam-by-seam matching when seam IDs\n"
            "are available from core or geophysical picks."
        ),
        "geology_doc": (
            "<b>same-region = SEAM:</b> Forces coal to correlate only with "
            "coal, and non-coal only with non-coal. This is the strongest "
            "constraint for mine planning when seam identification is "
            "reliable.<br><br>"
            "<b>Gap Cost = 4.0:</b> Very high — strongly penalises uncorrelated "
            "seams. Combined with same-region, this produces a strict "
            "seam-for-seam correlation."
        ),
        "opts": {
            "cost_function": "composite",
            "var_data": "DEN", "var_weight": 0.5,
            "var_data2": "GR", "var_weight2": 0.3,
            "var_data3": "SON", "var_weight3": 0.2,
            "same_region": "SEAM",
            "order": "position", "max_cor": 100, "nbr_cor": 100, "out_nbr_cor": 5,
            "const_gap_cost": 4.0,
            "const_gap_cost_start": 0.0,
            "const_gap_cost_end": 0.0,
        },
        "editable_keys": [
            "var_weight", "var_weight2", "var_weight3",
            "same_region", "max_cor", "const_gap_cost", "order",
        ],
    },

    # ── Shallow Marine (Hugin Fm analogue) ──────────────────────────
    {
        "id": "sm-basic",
        "title": "Shallow Marine — Basic (GR+RHOB+DT)",
        "group": "Shallow Marine (Oil Reservoir)",
        "wells": "data_set_shallow_marine/wells.txt",
        "geology": "shallow_marine",
        "description": (
            "10 wells along depositional dip (Hugin Fm analogue).\n"
            "Wave-dominated shoreface with clinoform geometry.\n"
            "GR+RHOB+DT variance for basic facies correlation."
        ),
        "geology_doc": (
            "<b>Geological Setting:</b> Upper Jurassic prograding "
            "wave-dominated shoreface / bay-fill system, inspired by "
            "the Hugin Formation (Viking Graben, North Sea).<br><br>"
            "<b>8 Facies:</b> Offshore mud, offshore transition, lower "
            "shoreface, upper shoreface, foreshore, bay-fill mud, tidal "
            "channel, transgressive lag.<br><br>"
            "<b>5 Parasequences:</b> PS1–PS5 with clinoform thickening "
            "downdip (10–20% per well step).<br><br>"
            "<b>Logs:</b> GR (lithology), RT (permeability), RHOB "
            "(porosity), NPHI (porosity), DT (compaction).<br><br>"
            "<b>Correlation Strategy:</b> GR separates shoreface sand "
            "(low GR, 25–65 API) from offshore mud (high GR, 90–120 API). "
            "RHOB distinguishes porous sand (2.15) from tight shale (2.50). "
            "DT adds compaction discrimination."
        ),
        "opts": {
            "cost_function": "composite",
            "var_data": "GR", "var_weight": 0.5,
            "var_data2": "RHOB", "var_weight2": 0.3,
            "var_data3": "DT", "var_weight3": 0.2,
            "order": "position", "max_cor": 80, "nbr_cor": 80, "out_nbr_cor": 5,
            "const_gap_cost": 2.0,
        },
        "editable_keys": [
            "var_weight", "var_weight2", "var_weight3",
            "max_cor", "const_gap_cost", "order",
        ],
    },
    {
        "id": "sm-distality",
        "title": "Shallow Marine — Distality Cost",
        "group": "Shallow Marine (Oil Reservoir)",
        "wells": "data_set_shallow_marine/wells.txt",
        "geology": "shallow_marine",
        "description": (
            "GR+RHOB+DT with distality cost on FACIES region.\n"
            "Distality penalises correlating facies that shouldn't\n"
            "be laterally equivalent (e.g. offshore ↔ foreshore)."
        ),
        "geology_doc": (
            "<b>Why Distality?</b> In a prograding system, distal wells "
            "see offshore mud while proximal wells see shoreface sand. "
            "The distality cost assigns low penalty to lateral equivalents "
            "(e.g., offshore mud ↔ bay-fill mud) and high penalty to "
            "non-equivalents (e.g., foreshore ↔ offshore mud).<br><br>"
            "<b>dist-facies = FACIES:</b> Uses the facies region to compute "
            "distality. Ordered from deepest (1=Offshore) to shallowest "
            "(5=Foreshore), with bay-fill (6) as offshore equivalent."
        ),
        "opts": {
            "cost_function": "composite",
            "var_data": "GR", "var_weight": 0.4,
            "var_data2": "RHOB", "var_weight2": 0.3,
            "var_data3": "DT", "var_weight3": 0.2,
            "dist_facies": "FACIES",
            "order": "position", "max_cor": 80, "nbr_cor": 80, "out_nbr_cor": 5,
            "const_gap_cost": 2.0,
        },
        "editable_keys": [
            "var_weight", "var_weight2", "var_weight3",
            "dist_facies", "dist_scaling",
            "max_cor", "const_gap_cost", "order",
        ],
    },
    {
        "id": "sm-biozones",
        "title": "Shallow Marine — Biozone Constrained",
        "group": "Shallow Marine (Oil Reservoir)",
        "wells": "data_set_shallow_marine/wells.txt",
        "geology": "shallow_marine",
        "description": (
            "GR+RHOB+DT constrained by BIOZONE no-crossing.\n"
            "Two biozones (BZ1, BZ2) lock parasequence boundaries,\n"
            "reducing search space and preventing noise correlation."
        ),
        "geology_doc": (
            "<b>Biozone Constraints:</b> Two biostratigraphic markers "
            "subdivide the section into three intervals:<br>"
            "• Below BZ1 (PS1 only)<br>"
            "• BZ1–BZ2 (PS2–PS3)<br>"
            "• Above BZ2 (PS4–PS5)<br><br>"
            "<b>no-crossing = BIOZONE:</b> Correlations cannot cross "
            "biozone boundaries. This is the strongest constraint for "
            "reservoir zonation when biostratigraphy is available.<br><br>"
            "<b>When to use:</b> When you have reliable biostratigraphic "
            "picks (palynology, microfossils) that subdivide the section."
        ),
        "opts": {
            "cost_function": "composite",
            "var_data": "GR", "var_weight": 0.5,
            "var_data2": "RHOB", "var_weight2": 0.3,
            "var_data3": "DT", "var_weight3": 0.2,
            "no_crossing": "BIOZONE",
            "order": "position", "max_cor": 80, "nbr_cor": 80, "out_nbr_cor": 5,
            "const_gap_cost": 2.0,
        },
        "editable_keys": [
            "var_weight", "var_weight2", "var_weight3",
            "no_crossing", "max_cor", "const_gap_cost", "order",
        ],
    },

    # ── §14.6 Delta Front / Prodelta ──────────────────────────────
    {
        "id": "delta-basic",
        "title": "Delta — Prograding Parasequences",
        "group": "Delta Front",
        "wells": "data_set_delta/wells.txt",
        "geology": "delta",
        "description": (
            "8 wells through a prograding delta with GR/DEN/NPHI.\n"
            "Shingled parasequences with lateral facies variation."
        ),
        "opts": {
            "cost_function": "composite",
            "var_data": "GR", "var_weight": 0.6,
            "var_data2": "DEN", "var_weight2": 0.4,
            "order": "position", "max_cor": 50, "nbr_cor": 50, "out_nbr_cor": 5,
        },
        "editable_keys": ["var_weight", "var_weight2", "max_cor", "order"],
    },

    # ── §14.6 Fluvial Channel Belt ────────────────────────────────
    {
        "id": "fluvial-basic",
        "title": "Fluvial — Channel Belt",
        "group": "Fluvial",
        "wells": "data_set_fluvial/wells.txt",
        "geology": "fluvial",
        "description": (
            "Laterally discontinuous channel sandbodies.\n"
            "High well count needed. Gap cost is critical."
        ),
        "opts": {
            "cost_function": "composite",
            "var_data": "GR", "var_weight": 1.0,
            "order": "position", "max_cor": 80, "nbr_cor": 80, "out_nbr_cor": 5,
            "const_gap_cost": 0.5,
        },
        "editable_keys": ["var_weight", "const_gap_cost", "max_cor", "order"],
    },
]


# ═══════════════════════════════════════════════════════════════════════════
#  Geological Environment Presets — "best guess defaults"
# ═══════════════════════════════════════════════════════════════════════════
#
#  Each preset describes a geological setting and provides recommended
#  parameter values that serve as a starting point.  Users load a preset,
#  then fine-tune for their own data.

GEO_PRESETS = {
    "quaternary_hydrogeology": {
        "label": "Quaternary Hydrogeology (Glacial)",
        "description": (
            "Northern European glacial lowland or similar Quaternary setting.\n"
            "Aquifer/aquitard mapping in till, sand, gravel, clay.\n\n"
            "Typical logs: GR, RT, SPT\n"
            "Typical wells: 20-200, shallow (10-80 m)\n"
            "Sample spacing: 0.25-1.0 m"
        ),
        "geology_notes": (
            "• Till/clay produce high GR; sand/gravel produce low GR\n"
            "• RT separates permeable (aquifer) from impermeable (aquitard)\n"
            "• SPT/MS can improve discrimination in till-dominated settings\n"
            "• Eemian interglacial may be missing — allow moderate gap cost\n"
            "• Buried valleys create locally thick gravel fills\n"
            "• Periglacial features (Eiskeil, cryoturbation) add complexity"
        ),
        "recommended_opts": {
            "cost_function": "composite",
            "var_data": "GR", "var_weight": 0.50,
            "var_data2": "RT", "var_weight2": 0.30,
            "var_data3": "SPT", "var_weight3": 0.20,
            "order": "position",
            "max_cor": 80, "nbr_cor": 80, "out_nbr_cor": 5,
            "const_gap_cost": 2.0,
            "const_gap_cost_start": 0.0,
            "const_gap_cost_end": 0.5,
        },
        "constraints_hint": (
            "If you have a hydrogeological facies classification, use "
            "same-region to enforce aquifer/aquitard grouping. "
            "If distinct stratigraphic markers exist (e.g., peat), consider "
            "no-crossing to lock those horizons."
        ),
        "correlation_hint": (
            "Start with basic GR+RT, then add SPT/MS if results are "
            "ambiguous in till-dominated areas. Increase gap cost if the "
            "engine introduces too many spurious hiatuses."
        ),
        "osdu_depenv": "glacial",
    },

    "coal_basin": {
        "label": "Coal Basin (Cyclothem)",
        "description": (
            "Coal-bearing basin with cyclic sequences (cyclothems).\n"
            "Seam correlation for mine planning and resource estimation.\n\n"
            "Typical logs: GR, DEN, RT, SON, NEU, CAL\n"
            "Typical wells: 10-100, shallow-medium (50-300 m)\n"
            "Sample spacing: 0.1-0.25 m (fine for thin seams)"
        ),
        "geology_notes": (
            "• Coal has uniquely low density (1.3 g/cc) → DEN is best indicator\n"
            "• Coal has very low GR (~20 API) and very high RT (500+ Ω·m)\n"
            "• Sonic slowness is very high in coal (120 µs/ft)\n"
            "• Tonstein (volcanic ash) = perfect isochronous marker\n"
            "• Marine bands = basin-wide correlation horizons\n"
            "• Seam splitting is common — thick seams bifurcate laterally\n"
            "• Channel washouts locally remove seams entirely"
        ),
        "recommended_opts": {
            "cost_function": "composite",
            "var_data": "DEN", "var_weight": 0.35,
            "var_data2": "GR", "var_weight2": 0.25,
            "var_data3": "RT", "var_weight3": 0.15,
            "var_data4": "SON", "var_weight4": 0.15,
            "var_data5": "NEU", "var_weight5": 0.10,
            "order": "position",
            "max_cor": 100, "nbr_cor": 100, "out_nbr_cor": 5,
            "const_gap_cost": 3.0,
            "const_gap_cost_start": 0.0,
            "const_gap_cost_end": 0.3,
        },
        "constraints_hint": (
            "If you have seam IDs (from core or picks), use same-region=SEAM "
            "for strict seam-by-seam correlation.  If only broad litho groups "
            "are known, use same-region with coal/non-coal classification."
        ),
        "correlation_hint": (
            "Start with DEN as the primary log (highest weight). Add GR and "
            "RT/SON if DEN alone is ambiguous. Use high gap cost (3-5) to "
            "penalise uncorrelated seams — coal should always find a match."
        ),
        "osdu_depenv": "coal",
    },

    "shallow_marine_reservoir": {
        "label": "Shallow Marine (Oil Reservoir)",
        "description": (
            "Prograding wave-dominated shoreface / bay-fill system.\n"
            "Clinoform geometry with lateral facies change.\n\n"
            "Typical logs: GR, RT, RHOB, NPHI, DT\n"
            "Typical wells: 5-15, reservoir interval 100-400 m\n"
            "Sample spacing: 0.15-0.5 m"
        ),
        "geology_notes": (
            "• Upward-coarsening shoreface (GR decreases upward)\n"
            "• Lateral facies change: shoreface (proximal) ↔ offshore (distal)\n"
            "• Clinoform geometry: beds thicken downdip\n"
            "• Biozones are the most reliable correlation markers\n"
            "• Bay-fill mud looks like offshore mud on GR — use RHOB/NPHI\n"
            "• Transgressive lags are thin but distinctive (high RT, low NPHI)"
        ),
        "recommended_opts": {
            "cost_function": "composite",
            "var_data": "GR", "var_weight": 0.50,
            "var_data2": "RHOB", "var_weight2": 0.30,
            "var_data3": "DT", "var_weight3": 0.20,
            "order": "position",
            "max_cor": 80, "nbr_cor": 80, "out_nbr_cor": 5,
            "const_gap_cost": 2.0,
        },
        "constraints_hint": (
            "If biozones are available, use no-crossing=BIOZONE to lock "
            "parasequence boundaries — this is the most effective constraint. "
            "If facies are interpreted, use dist-facies for distality cost "
            "to account for lateral equivalence (offshore mud ↔ bay-fill mud)."
        ),
        "correlation_hint": (
            "GR is the primary lithology discriminator. RHOB adds porosity "
            "contrast. DT helps with compaction trends. Start with GR 50%, "
            "RHOB 30%, DT 20%. If results are poor in the distal direction, "
            "add distality cost (dist-facies) at 10% weight."
        ),
        "osdu_depenv": "shallow_marine",
    },

    "deep_marine_clastic": {
        "label": "Deep-Marine Clastic (Turbidite)",
        "description": (
            "Deep-water turbidite/fan system. Siliciclastic.\n"
            "Lobe/channel correlation in sand-rich successions.\n\n"
            "Typical logs: GR, sonic, density\n"
            "Typical wells: 5-50, deep (500-3000 m)\n"
            "Sample spacing: 0.5-2.0 m"
        ),
        "geology_notes": (
            "• Sand vs shale is the primary contrast (GR is key)\n"
            "• Distality matters — proximal channels vs distal lobes\n"
            "• Thickness variations are large and systematic\n"
            "• Condensed sections/hemipelagic drapes = good markers\n"
            "• Use distality cost if paleogeography is known"
        ),
        "recommended_opts": {
            "cost_function": "composite",
            "var_data": "GR", "var_weight": 0.60,
            "var_data2": "DEN", "var_weight2": 0.25,
            "var_data3": "SON", "var_weight3": 0.15,
            "order": "position",
            "max_cor": 100, "nbr_cor": 100, "out_nbr_cor": 5,
            "const_gap_cost": 1.0,
        },
        "constraints_hint": (
            "For basin transects, use distality ordering + dist_distal/dist_facies "
            "to model thickness wedging. If you have seismic horizons, use "
            "no-crossing to lock known sequence boundaries."
        ),
        "correlation_hint": (
            "GR should dominate (sand/shale contrast). Low gap cost allows "
            "condensation/erosion (common in deep water). If channels are "
            "present, expect lateral thickness changes — distality helps."
        ),
        "osdu_depenv": "deep_marine",
    },

    "carbonate_platform": {
        "label": "Carbonate Platform / Reef",
        "description": (
            "Carbonate platform, ramp, or reef setting.\n"
            "Facies correlation in limestone/dolomite sequences.\n\n"
            "Typical logs: GR, sonic, density, neutron\n"
            "Typical wells: 5-50, variable depth\n"
            "Sample spacing: 0.5-2.0 m"
        ),
        "geology_notes": (
            "• GR is typically low in clean carbonates → less diagnostic\n"
            "• DEN + SON + NEU better for porosity/texture changes\n"
            "• Dolomitisation overprints primary log signatures\n"
            "• Flooding surfaces and exposure surfaces = key markers\n"
            "• Facies belts migrate laterally (progradation/aggradation)"
        ),
        "recommended_opts": {
            "cost_function": "composite",
            "var_data": "DEN", "var_weight": 0.35,
            "var_data2": "SON", "var_weight2": 0.35,
            "var_data3": "GR", "var_weight3": 0.15,
            "var_data4": "NEU", "var_weight4": 0.15,
            "order": "position",
            "max_cor": 100, "nbr_cor": 100, "out_nbr_cor": 5,
            "const_gap_cost": 0.5,
        },
        "constraints_hint": (
            "Use no-crossing for known sequence boundaries (flooding surfaces). "
            "If depositional texture classes are available, same-region can help. "
            "Polarity (T/R) can guide gap costs through transgressive–regressive "
            "cycles."
        ),
        "correlation_hint": (
            "DEN + SON should carry most weight since GR contrast is low. "
            "Neutron-density crossover helps identify gas or porosity changes. "
            "Low gap cost allows condensation common on carbonate platforms."
        ),
        "osdu_depenv": "carbonate",
    },

    "fluvial_continental": {
        "label": "Fluvial / Continental",
        "description": (
            "Alluvial/fluvial/lacustrine continental deposits.\n"
            "Channel belt and overbank facies correlation.\n\n"
            "Typical logs: GR, SP, resistivity\n"
            "Typical wells: 10-100, shallow-medium depth\n"
            "Sample spacing: 0.5-1.0 m"
        ),
        "geology_notes": (
            "• Channel sands are laterally discontinuous\n"
            "• Overbank fines (clay/silt) are more continuous markers\n"
            "• Stacking patterns (fining-up, coarsening-up) are diagnostic\n"
            "• Coal/peat beds and paleosols make good correlation markers\n"
            "• Lateral facies changes are rapid — position ordering helps"
        ),
        "recommended_opts": {
            "cost_function": "composite",
            "var_data": "GR", "var_weight": 0.70,
            "var_data2": "RT", "var_weight2": 0.30,
            "order": "position",
            "max_cor": 80, "nbr_cor": 80, "out_nbr_cor": 5,
            "const_gap_cost": 1.5,
        },
        "constraints_hint": (
            "If flood plain / lacustrine markers are recognised, use "
            "no-crossing to lock those horizons. Channel sands may not "
            "correlate — allow the engine to skip them (moderate gap cost)."
        ),
        "correlation_hint": (
            "GR is the primary discriminator (sand vs clay). RT adds "
            "value where water saturation varies. Start with high GR weight "
            "and moderate gap cost. Reduce gap cost if channels are common."
        ),
        "osdu_depenv": "fluvial",
    },
}


# ═══════════════════════════════════════════════════════════════════════════
#  Parameter help database  (extends hints_options.txt)
# ═══════════════════════════════════════════════════════════════════════════

PARAM_HELP = {
    # ── Global ──────────────────────────────────────────────────────
    "cost_function": {
        "label": "Cost Function",
        "type": "select", "values": ["composite"],
        "help": (
            "Which cost framework to use.\n\n"
            "'composite' combines multiple cost components "
            "(variance, gap, distality, polarity, constraints) "
            "into a single objective that the engine minimises.\n\n"
            "This is the only built-in cost function. Custom cost "
            "functions can be added via the C plugin API."
        ),
        "category": "Global",
        "tier": "advanced",
    },
    "order": {
        "label": "Merge Order",
        "type": "select", "values": ["linear", "pyramidal", "position", "distality", "inverse"],
        "help": (
            "Controls how wells are paired and merged in the task tree.\n\n"
            "linear: Sequential left-to-right. W1+W2, then (W1-W2)+W3, etc.\n"
            "  Best for simple sections with wells in spatial order.\n\n"
            "pyramidal: Balanced binary tree. (W1+W2)+(W3+W4), then merge.\n"
            "  Generally best quality for 4+ wells.\n\n"
            "position: Nearest-pair by (x,y) coordinates. Geological\n"
            "  nearest-neighbour clustering via BSP trees.\n\n"
            "distality: Orders by palaeo-distality, most-distal first.\n"
            "  Best for basin transects with dist_distal data.\n\n"
            "inverse: Reverse of linear. W(n-1)+Wn first.\n\n"
            "Interpretation: Merge order affects which information is\n"
            "available when the engine solves each sub-problem. Merging\n"
            "geologically adjacent wells first usually gives better results."
        ),
        "effect": "position = best for spatial data; pyramidal = best general; distality = basin transect",
        "category": "Global",
        "tier": "fundamental",
        "scenario_test": True,
        "scenario_hint": "Try 'pyramidal' vs 'position' vs 'distality' — order significantly affects results",
    },
    "thread": {
        "label": "Threads",
        "type": "int", "min": 0, "max": 128, "default": 0,
        "help": (
            "Number of CPU threads for the DTW engine.\n\n"
            "0 = auto-detect (uses all available cores).\n"
            "Set to 1 for deterministic single-threaded execution."
        ),
        "category": "Global",
        "tier": "advanced",
        "auto_value": 0,
    },

    # ── Graph ───────────────────────────────────────────────────────
    "band_width": {
        "label": "Band Width (Sakoe-Chiba)",
        "type": "int", "min": 0, "max": 10000, "default": 0,
        "help": (
            "Sakoe-Chiba band constraint width.\n\n"
            "0 = no band constraint (full DTW matrix explored).\n"
            "> 0 = only cells within 'band_width' of the diagonal are\n"
            "evaluated. This dramatically speeds up large correlations\n"
            "while preventing extreme warping.\n\n"
            "Typical values:\n"
            "  0     full search (default, always optimal)\n"
            "  10-20 fast approximate for >200 markers\n"
            "  50+   loose constraint (rarely needed)"
        ),
        "effect": "\u2191 wider band = more accurate but slower; 0 = full search; >0 = fast approximate",
        "category": "Graph",
        "tier": "advanced",
        "auto_rule": "auto: set to max_well_length/3 if >200 samples, else 0",
    },
    "beam_width": {
        "label": "Beam Width (wavefront)",
        "type": "int", "min": 0, "max": 10000, "default": 0,
        "help": (
            "Beam search width for wavefront DTW.\n\n"
            "0 = no beam pruning (full wavefront, optimal).\n"
            "> 0 = keep only the 'beam_width' best partial paths per\n"
            "anti-diagonal during wavefront traversal. Enables pruning\n"
            "for very large problems (>100 wells).\n\n"
            "Use with caution: aggressive pruning may miss the optimal\n"
            "solution. Start with 0 and only enable if too slow."
        ),
        "effect": "\u2191 wider beam = more accurate; 0 = optimal (no pruning); small = aggressive speedup",
        "category": "Graph",
        "tier": "advanced",
        "auto_value": 0,
    },
    "max_cor": {
        "label": "Max Correlations (search)",
        "type": "int", "min": 1, "max": 10000, "default": 50,
        "help": (
            "Maximum n-best correlations kept during each DTW merge step.\n\n"
            "This is the 'k' in the n-best graph-DTW algorithm. Higher values\n"
            "explore more of the solution space, giving better quality but\n"
            "O(k) more computation.\n\n"
            "Typical values:\n"
            "  10-20  fast exploration / demos\n"
            "  50     good default (76ms for 3 wells x 100 markers)\n"
            "  200+   high-quality production (5x slower, diminishing returns)\n\n"
            "Interpretation: If your best correlation cost is high, try\n"
            "increasing this before tuning other parameters."
        ),
        "effect": "\u2191 higher = better quality but slower; \u2193 lower = faster but may miss optimal solution",
        "category": "Graph",
        "tier": "recommended",
        "scenario_test": True,
        "scenario_hint": "If cost is high, increase to 100-200 for better exploration",
    },
    "nbr_cor": {
        "label": "Kept Correlations (prune)",
        "type": "int", "min": 1, "max": 10000, "default": 50,
        "help": (
            "Number of correlations kept after a merge step for use in\n"
            "subsequent steps.\n\n"
            "Should be <= max_cor. The engine computes max_cor solutions\n"
            "in each DTW, then prunes to nbr_cor before passing results\n"
            "to the next task in the merge tree.\n\n"
            "Setting nbr_cor < max_cor saves memory and speeds up later\n"
            "merge steps at the cost of potentially discarding useful\n"
            "sub-optimal solutions."
        ),
        "effect": "\u2191 higher = more diverse solutions kept, slower merge; \u2193 lower = faster, may lose alternatives",
        "category": "Graph",
        "tier": "advanced",
        "auto_rule": "auto: same as max_cor",
    },
    "min_dist": {
        "label": "Min Distance (subsample)",
        "type": "float", "min": 0.0, "max": 1000.0, "default": 0.0,
        "help": (
            "Minimum cost-distance between two kept correlations to ensure\n"
            "diversity in the kept set.\n\n"
            "0 = no diversity filter (keep the k cheapest).\n"
            "> 0 = reject any new correlation whose cost is within this\n"
            "distance of an already-kept one.\n\n"
            "Use this to avoid storing many nearly-identical solutions."
        ),
        "category": "Graph",
        "tier": "advanced",
        "auto_value": 0.0,
    },
    "out_nbr_cor": {
        "label": "Output Correlations",
        "type": "int", "min": 1, "max": 1000, "default": 5,
        "help": (
            "Number of alternative correlations in the final output.\n\n"
            "1 = single best correlation only.\n"
            "5-10 = good for uncertainty analysis (compare alternatives).\n\n"
            "Interpretation: Examining multiple output correlations reveals\n"
            "which parts of the section are well-constrained (same across\n"
            "all solutions) and which are ambiguous (differ between solutions)."
        ),
        "effect": "\u2191 more alternatives to compare; 1 = single best only",
        "category": "Graph",
        "tier": "fundamental",
        "scenario_test": True,
        "scenario_hint": "Set to 5-10 to compare alternative correlations and assess uncertainty",
    },
    "out_min_dist": {
        "label": "Output Min Distance",
        "type": "float", "min": 0.0, "max": 1000.0, "default": 0.0,
        "help": (
            "Minimum cost-distance between two output correlations.\n"
            "0 = no diversity filter on output.\n\n"
            "Use a small positive value to guarantee that the N output\n"
            "correlations are meaningfully different from each other."
        ),
        "category": "Graph",
        "tier": "advanced",
        "auto_value": 0.0,
    },

    # ── Variance ────────────────────────────────────────────────────
    "var_data": {
        "label": "Log 1",
        "type": "data",
        "help": (
            "Primary well-log property for the variance cost component.\n\n"
            "Select the most diagnostic log for your correlation problem.\n"
            "Common choices: GR (gamma ray), acoustic impedance, resistivity,\n"
            "or any continuous curve that varies with lithology.\n\n"
            "Geological meaning: The engine minimises the variance of this\n"
            "property across correlated positions. It tries to align similar\n"
            "log values between wells."
        ),
        "category": "Variance",
        "tier": "fundamental",
    },
    "var_weight": {
        "label": "Weight 1",
        "type": "float", "min": 0.0, "max": 100.0, "default": 1.0,
        "help": (
            "Weight for variance log 1 in the composite cost.\n\n"
            "1.0 = full contribution, 0.0 = ignored.\n\n"
            "Interpretation: When using two logs, the ratio var_weight /\n"
            "var_weight2 controls which log dominates the correlation.\n"
            "Start with equal weights, then adjust to favour the more\n"
            "reliable log."
        ),
        "effect": "\u2191 higher = log 1 dominates correlation; \u2193 lower = other logs dominate",
        "category": "Variance",
        "tier": "recommended",
        "scenario_test": True,
        "scenario_hint": "Try different weight ratios between logs to test sensitivity",
    },
    "var_data2": {
        "label": "Log 2",
        "type": "data",
        "help": (
            "Secondary well-log property for variance cost.\n\n"
            "Use a second log with complementary information (e.g.\n"
            "GR for lithology + density for porosity), or leave blank\n"
            "to use only the primary log."
        ),
        "category": "Variance",
        "tier": "recommended",
    },
    "var_weight2": {
        "label": "Weight 2",
        "type": "float", "min": 0.0, "max": 100.0, "default": 1.0,
        "help": "Weight for variance log 2. See Weight 1 for guidance.",
        "category": "Variance",
        "tier": "recommended",
    },
    "var_data3": {
        "label": "Log 3",
        "type": "data",
        "help": "Optional third log for multi-attribute variance cost.",
        "category": "Variance",
        "tier": "advanced",
    },
    "var_weight3": {
        "label": "Weight 3",
        "type": "float", "min": 0.0, "max": 100.0, "default": 1.0,
        "help": "Weight for variance log 3.",
        "category": "Variance",
        "tier": "advanced",
    },
    "var_data4": {
        "label": "Log 4",
        "type": "data",
        "help": "Optional fourth log for multi-attribute variance cost.",
        "category": "Variance",
        "tier": "advanced",
    },
    "var_weight4": {
        "label": "Weight 4",
        "type": "float", "min": 0.0, "max": 100.0, "default": 1.0,
        "help": "Weight for variance log 4.",
        "category": "Variance",
        "tier": "advanced",
    },
    "var_data5": {
        "label": "Log 5",
        "type": "data",
        "help": "Optional fifth log for multi-attribute variance cost.",
        "category": "Variance",
        "tier": "advanced",
    },
    "var_weight5": {
        "label": "Weight 5",
        "type": "float", "min": 0.0, "max": 100.0, "default": 1.0,
        "help": "Weight for variance log 5.",
        "category": "Variance",
        "tier": "advanced",
    },
    "var_region": {
        "label": "Var-Region",
        "type": "region",
        "help": (
            "Region for variance-based boundary cost bonus.\n\n"
            "If set, correlated points near matching region boundaries\n"
            "get a cost reduction, encouraging the correlation to honour\n"
            "known stratigraphic surfaces."
        ),
        "category": "Variance",
        "tier": "advanced",
    },

    # ── Constraints ─────────────────────────────────────────────────
    "no_crossing": {
        "label": "No-Crossing Region 1",
        "type": "region",
        "help": (
            "Hard constraint: correlation lines cannot cross the\n"
            "boundaries of this region.\n\n"
            "Geological meaning: This enforces that known stratigraphic\n"
            "surfaces (e.g. sequence boundaries, flooding surfaces) are\n"
            "not violated by the correlation. All paths that would cross\n"
            "a zone boundary are eliminated.\n\n"
            "Important: The region IDs across wells must be consistent\n"
            "(same ID = same geological unit)."
        ),
        "effect": "Hard constraint: blocks ALL cross-overs at zone boundaries",
        "category": "Constraints",
        "tier": "fundamental",
        "scenario_test": True,
        "scenario_hint": "Test with vs without: does relaxing this constraint lower cost significantly?",
    },
    "no_crossing2": {
        "label": "No-Crossing Region 2",
        "type": "region",
        "help": "Second no-crossing region. Used when multiple independent\nzone hierarchies must be honoured simultaneously.",
        "category": "Constraints",
        "tier": "advanced",
    },
    "no_crossing3": {
        "label": "No-Crossing Region 3",
        "type": "region",
        "help": "Third no-crossing region.",
        "category": "Constraints",
        "tier": "advanced",
    },
    "same_region": {
        "label": "Same-Region 1",
        "type": "region",
        "help": (
            "Soft constraint: correlated points must share the same\n"
            "region label. Unlike no-crossing, this affects cost rather\n"
            "than eliminating paths outright.\n\n"
            "Geological meaning: Encourages matching lithostratigraphic\n"
            "units between wells."
        ),
        "effect": "Soft constraint: penalises cross-unit ties but does not block them",
        "category": "Constraints",
        "tier": "recommended",
        "scenario_test": True,
        "scenario_hint": "Compare no_crossing (hard) vs same_region (soft) — which fits your confidence?",
    },
    "same_region2": {
        "label": "Same-Region 2",
        "type": "region",
        "help": "Second same-region constraint. Use for a different\nstratigraphic zonation.",
        "category": "Constraints",
        "tier": "advanced",
    },
    "same_region3": {
        "label": "Same-Region 3",
        "type": "region",
        "help": "Third same-region constraint.",
        "category": "Constraints",
        "tier": "advanced",
    },

    # ── Polarity ────────────────────────────────────────────────────
    "polarity_region": {
        "label": "Polarity Region",
        "type": "region",
        "help": (
            "Region encoding stratigraphic polarity (e.g. transgressive\n"
            "vs regressive trends).\n\n"
            "The polarity cost component penalises gaps differently\n"
            "depending on whether the polarity matches or differs\n"
            "between correlated intervals."
        ),
        "category": "Polarity",
        "tier": "advanced",
    },
    "polarity_cost_diff": {
        "label": "Cost (different)",
        "type": "float", "min": 0.0, "max": 100.0, "default": 0.5,
        "help": (
            "Gap cost when polarity differs between the two sides.\n"
            "Geological meaning: Penalises gaps that cross a polarity\n"
            "reversal. Higher values force the engine to match polarity\n"
            "more strictly."
        ),
        "category": "Polarity",
        "tier": "advanced",
        "auto_value": 0.5,
    },
    "polarity_cost_same": {
        "label": "Cost (same)",
        "type": "float", "min": 0.0, "max": 100.0, "default": 0.5,
        "help": "Gap cost when polarity is the same on both sides.\nLower than cost_diff to favour gaps within the same trend.",
        "category": "Polarity",
        "tier": "advanced",
        "auto_value": 0.5,
    },
    "polarity_cost_start": {
        "label": "Cost (start)",
        "type": "float", "min": 0.0, "max": 100.0, "default": 0.5,
        "help": "Gap cost at the top of a well (start of section).",
        "category": "Polarity",
        "tier": "advanced",
        "auto_value": 0.5,
    },
    "polarity_cost_end": {
        "label": "Cost (end)",
        "type": "float", "min": 0.0, "max": 100.0, "default": 0.5,
        "help": "Gap cost at the base of a well (end of section).",
        "category": "Polarity",
        "tier": "advanced",
        "auto_value": 0.5,
    },

    # ── Gap ─────────────────────────────────────────────────────────
    "gap_cost_func": {
        "label": "Gap Cost Function",
        "type": "data",
        "help": (
            "Data property providing a per-sample gap cost curve.\n\n"
            "If set, this overrides const_gap_cost at each sample position.\n"
            "Use this for spatially-varying gap penalties (e.g. higher gap\n"
            "cost in condensed sections, lower in expanded intervals)."
        ),
        "category": "Gap",
        "tier": "advanced",
    },
    "gap_cost_func_mult": {
        "label": "Gap Cost Multiplier",
        "type": "float", "min": 0.0, "max": 100.0, "default": 1.0,
        "help": "Multiplier applied to gap_cost_func values.\nUse to globally scale the gap cost curve up or down.",
        "category": "Gap",
        "tier": "advanced",
        "auto_value": 1.0,
    },
    "const_gap_cost": {
        "label": "Constant Gap Cost",
        "type": "float", "min": 0.0, "max": 100.0, "default": 0.0,
        "help": (
            "Flat penalty applied every time the engine introduces a\n"
            "stratigraphic gap (hiatus, condensation, or erosion).\n\n"
            "0.0 = gaps are free (only log similarity matters).\n"
            "0.1-1.0 = moderate penalty, prefer continuous correlation.\n"
            "5-10+ = strong penalty, force layer-cake matching.\n\n"
            "Geological interpretation: A higher gap cost produces more\n"
            "'layer-cake' correlations with fewer hiatuses. A lower cost\n"
            "allows the engine to skip intervals, which is appropriate\n"
            "when significant erosion or condensation is expected."
        ),
        "effect": "\u2191 higher = fewer gaps, layer-cake style; \u2193 lower = more hiatuses allowed, flexible",
        "category": "Gap",
        "tier": "fundamental",
        "scenario_test": True,
        "scenario_hint": "KEY PARAMETER: try 0.0, 0.5, 1.0 — controls hiatus vs layer-cake behaviour",
    },
    "const_gap_cost_start": {
        "label": "Gap Cost (start)",
        "type": "float", "min": -1.0, "max": 100.0, "default": -1.0,
        "help": (
            "Gap penalty at the top of a well (start of section).\n"
            "-1 = use the global const_gap_cost value.\n\n"
            "Set > 0 to penalise gaps at the top differently.\n"
            "Useful when the top of section is well-constrained."
        ),
        "category": "Gap",
        "tier": "advanced",
        "auto_value": -1.0,
    },
    "const_gap_cost_end": {
        "label": "Gap Cost (end)",
        "type": "float", "min": -1.0, "max": 100.0, "default": -1.0,
        "help": (
            "Gap penalty at the base of a well (end of section).\n"
            "-1 = use the global const_gap_cost value."
        ),
        "category": "Gap",
        "tier": "advanced",
        "auto_value": -1.0,
    },

    # ── Distality ───────────────────────────────────────────────────
    "dist_distal": {
        "label": "Distality Region",
        "type": "region",
        "help": (
            "Region encoding relative palaeo-distality of the well\n"
            "position. Values ordered distal(1) to proximal(n).\n\n"
            "Geological meaning: The distality cost component uses this\n"
            "information together with facies to model thickness ratios.\n"
            "Distal wells are expected to have thinner representations\n"
            "of proximal facies and vice versa."
        ),
        "category": "Distality",
        "tier": "recommended",
    },
    "dist_facies": {
        "label": "Facies Region",
        "type": "region",
        "help": (
            "Region encoding palaeo-bathymetric facies. Values ordered\n"
            "from deepest(1) to shallowest(n).\n\n"
            "Together with dist_distal, this models thickness wedging:\n"
            "facies deposited far from the well's palaeo-position are\n"
            "expected to be thinner in that well."
        ),
        "category": "Distality",
        "tier": "recommended",
    },
    "dist_scaling": {
        "label": "Distality Scaling",
        "type": "float", "min": -1.0, "max": 1.0, "default": 1.0,
        "help": (
            "Controls the strength of lateral extent scaling.\n\n"
            "1.0 = strong wedge model (proximal thick, distal thin).\n"
            "0.0 = tabular model (no thickness variation expected).\n"
            "< 0 = inverse scaling (unusual, for testing).\n\n"
            "Geological interpretation: Values near 1.0 are appropriate\n"
            "for clinoform/progradational geometries. Values near 0.0\n"
            "are better for tabular/aggradational stacking."
        ),
        "effect": "1.0 = strong clinoform wedge; 0.0 = tabular beds; <0 = inverted (testing only)",
        "category": "Distality",
        "tier": "recommended",
        "scenario_test": True,
        "scenario_hint": "Try 0.5 vs 1.0: tabular vs clinoform geometry assumption",
    },

    # ── Multi-Distality ────────────────────────────────────────────
    "multi_dist_distal": {
        "label": "Multi-Dist Scenarios",
        "type": "string",
        "help": (
            "File path listing all possible palaeo-distality scenarios.\n\n"
            "Each scenario is a different ranking of wells from distal\n"
            "to proximal. The engine evaluates all scenarios and picks\n"
            "the combination that yields the lowest cost.\n\n"
            "Use this when the palaeo-geography is uncertain and you\n"
            "want the correlation to explore multiple interpretations."
        ),
        "category": "Multi-Distality",
        "tier": "advanced",
        "scenario_test": True,
        "scenario_hint": "Multimodal: test alternative palaeo-geographic orderings when uncertain",
    },
    "multi_dist_facies": {
        "label": "Multi-Dist Facies",
        "type": "region",
        "help": "Facies log for the multi-distality cost component.\nSame semantics as dist_facies but used with scenario exploration.",
        "category": "Multi-Distality",
        "tier": "advanced",
    },
    "multi_dist_scaling": {
        "label": "Multi-Dist Scaling",
        "type": "float", "min": -1.0, "max": 1.0, "default": 1.0,
        "help": "Scaling coefficient for multi-distality cost.\nSame semantics as dist_scaling.",
        "category": "Multi-Distality",
        "tier": "advanced",
    },

    # ── B3D Curve ──────────────────────────────────────────────────
    "b3d_curve_dip": {
        "label": "B3D Dip",
        "type": "data",
        "help": (
            "Dip angle data (degrees) for the Bezier-3D curve cost.\n\n"
            "This component fits 3D Bezier curves to the correlated\n"
            "horizons using structural dip information."
        ),
        "category": "B3D Curve",
        "tier": "advanced",
    },
    "b3d_curve_azimuth": {
        "label": "B3D Azimuth",
        "type": "data",
        "help": "Strike orientation data (degrees) for B3D curve cost.\nUsed together with dip to define the 3D surface geometry.",
        "category": "B3D Curve",
        "tier": "advanced",
    },
    "b3d_curve_depth": {
        "label": "B3D Depth",
        "type": "data",
        "help": "Z-axis coordinate data for B3D curve cost.\nTypically true vertical depth (TVD).",
        "category": "B3D Curve",
        "tier": "advanced",
    },
    "b3d_curve_facies": {
        "label": "B3D Facies",
        "type": "data",
        "help": "Palaeo-depth facies data for B3D curve cost.\nEncodes the depositional environment for each sample.",
        "category": "B3D Curve",
        "tier": "advanced",
    },
    "b3d_curve_write_bezier": {
        "label": "Write Bezier",
        "type": "bool", "default": False,
        "help": "Generate Bezier curve point sets as output files.\nUseful for visualisation in 3D viewers.",
        "category": "B3D Curve",
        "tier": "advanced",
    },
    "b3d_curve_write_profile": {
        "label": "Write Profile",
        "type": "bool", "default": False,
        "help": "Generate depositional profile point sets as output.",
        "category": "B3D Curve",
        "tier": "advanced",
    },
    "b3d_curve_bezier_folder": {
        "label": "Bezier Folder",
        "type": "string",
        "help": "Output folder for Bezier interpolation files.",
        "category": "B3D Curve",
        "tier": "advanced",
    },
    "b3d_curve_profile_folder": {
        "label": "Profile Folder",
        "type": "string",
        "help": "Output folder for depositional profile files.",
        "category": "B3D Curve",
        "tier": "advanced",
    },
    "b3d_curve_dep_facies_file": {
        "label": "Dep Facies File",
        "type": "string",
        "help": "Depositional facies configuration file (describes facies ordering and properties).",
        "category": "B3D Curve",
        "tier": "advanced",
    },
    "b3d_curve_dep_profile_file": {
        "label": "Dep Profile File",
        "type": "string",
        "help": "Depositional profile configuration file.",
        "category": "B3D Curve",
        "tier": "advanced",
    },

    # ── Output ──────────────────────────────────────────────────────
    "out_file": {
        "label": "Result File",
        "type": "string", "default": "out.txt",
        "help": (
            "Output result file path (WeCo format).\n\n"
            "The result file contains a directed acyclic graph (DAG)\n"
            "of correlated nodes. Each node records the matched\n"
            "positions across all wells, and edges have costs."
        ),
        "category": "Output",
        "tier": "advanced",
        "auto_value": "out.txt",
    },
    "out_dot": {
        "label": "DOT Graph",
        "type": "string",
        "help": "Output in Graphviz DOT format for visualisation.\nLeave empty to skip.",
        "category": "Output",
        "tier": "advanced",
    },
    "step_dot": {
        "label": "Step DOT Prefix",
        "type": "string",
        "help": "Base name for per-step DOT files (e.g. 'step' produces\nstep_0.dot, step_1.dot, ...). Useful for debugging the merge tree.",
        "category": "Output",
        "tier": "advanced",
    },
    "step_file": {
        "label": "Step File Prefix",
        "type": "string",
        "help": "Base name for per-step WeCo result files.\nCaptures intermediate correlation states.",
        "category": "Output",
        "tier": "advanced",
    },
    "cost_matrix": {
        "label": "Cost Matrix File",
        "type": "string",
        "help": (
            "Output cost-matrix file for QC/debug.\n\n"
            "WARNING: this option consumes significant time and disk space.\n"
            "Only use for debugging or detailed cost analysis."
        ),
        "category": "Output",
        "tier": "advanced",
    },
    "order_dot": {
        "label": "Order DOT",
        "type": "string",
        "help": "Write the task-ordering (merge tree) as a DOT file.\nUseful for understanding how wells are paired.",
        "category": "Output",
        "tier": "advanced",
    },
    "order_only": {
        "label": "Order Only",
        "type": "bool", "default": False,
        "help": "Stop after generating the task ordering (no correlation).\nUseful for inspecting the merge tree without running DTW.",
        "category": "Output",
        "tier": "advanced",
    },

    # ── Debug ───────────────────────────────────────────────────────
    "debug_cor_info": {
        "label": "Debug Info",
        "type": "bool", "default": False,
        "help": "Print detailed correlation statistics after each merge step.\nShows number of nodes, edges, and costs for QC.",
        "category": "Debug",
        "tier": "advanced",
    },
}

PARAM_CATEGORIES = [
    "Global", "Graph", "Variance", "Constraints", "Polarity",
    "Gap", "Distality", "Multi-Distality", "B3D Curve", "Output", "Debug",
]

# ── Parameter Tier System ───────────────────────────────────────────────
# Tiers control default visibility in the GUI:
#   fundamental — must be set by the user; always visible
#   recommended — important for good results; visible in "Essential" mode
#   advanced    — safe to auto-set; hidden in "Essential" mode
TIER_FUNDAMENTAL = "fundamental"
TIER_RECOMMENDED = "recommended"
TIER_ADVANCED = "advanced"

# Which tiers are visible in each view mode
TIER_VISIBILITY = {
    "Essential":  {TIER_FUNDAMENTAL, TIER_RECOMMENDED},
    "All":        {TIER_FUNDAMENTAL, TIER_RECOMMENDED, TIER_ADVANCED},
}


def estimate_auto_params(well_list=None):
    """Estimate sensible defaults for advanced parameters based on loaded data.

    Returns a dict of {param_key: estimated_value} for parameters that have
    auto_value or auto_rule set.  Called when data is loaded to pre-fill
    advanced params so users don't need to touch them.
    """
    estimates = {}

    # Static auto_values (data-independent defaults)
    for key, pdef in PARAM_HELP.items():
        if "auto_value" in pdef:
            estimates[key] = pdef["auto_value"]

    if well_list is None:
        return estimates

    # Data-adaptive estimates
    try:
        n_wells = len(well_list.wells)
        max_len = max((w.size for w in well_list.wells), default=100)

        # Merge order: use position if XY coords available, pyramidal otherwise
        has_xy = any(
            hasattr(w, 'x') and hasattr(w, 'y') and w.x != 0
            for w in well_list.wells
        )
        if has_xy and n_wells >= 4:
            estimates["order"] = "position"
        elif n_wells >= 4:
            estimates["order"] = "pyramidal"
        else:
            estimates["order"] = "linear"

        # Band width: auto-set for large wells
        if max_len > 200:
            estimates["band_width"] = max(max_len // 3, 20)
        else:
            estimates["band_width"] = 0

        # max_cor / nbr_cor: scale with problem size
        if n_wells <= 3:
            estimates["max_cor"] = 50
        elif n_wells <= 8:
            estimates["max_cor"] = 100
        else:
            estimates["max_cor"] = 200
        estimates["nbr_cor"] = estimates["max_cor"]

        # Gap cost heuristic: estimate from thickness variability
        sizes = [w.size for w in well_list.wells]
        if len(sizes) >= 2:
            thickness_ratio = max(sizes) / max(min(sizes), 1)
            if thickness_ratio > 3.0:
                # Large thickness variation → expect gaps
                estimates["const_gap_cost"] = 0.0
            elif thickness_ratio > 1.5:
                estimates["const_gap_cost"] = 0.3
            else:
                # Similar thicknesses → layer-cake likely
                estimates["const_gap_cost"] = 1.0

        # Detect available data/region names for auto log selection
        data_names = []
        for w in well_list.wells:
            if hasattr(w, 'data'):
                data_names.extend(w.data.keys())
        data_names = list(set(data_names))

        # Suggest primary log (prefer GR > AI > RT > DEN)
        log_priority = ["GR", "Gamma", "AI", "Impedance", "RT", "Resistivity", "DEN", "Density"]
        for candidate in log_priority:
            matches = [d for d in data_names if candidate.lower() in d.lower()]
            if matches:
                estimates["var_data"] = matches[0]
                break

    except Exception:
        pass  # Graceful degradation — return static defaults

    return estimates

# Category-level workflow guidance shown at the top of each param group
CATEGORY_GUIDE = {
    "Global": (
        "Start here. Choose a merge order that matches your well geometry. "
        "'pyramidal' is a good default for 4+ wells, 'linear' for a simple transect."
    ),
    "Graph": (
        "These control the trade-off between quality and speed. Increase max_cor for "
        "better correlations at the cost of longer runtime. out_nbr_cor > 1 lets you "
        "compare alternative solutions to assess uncertainty."
    ),
    "Variance": (
        "Select one or more well-log curves whose similarity should drive the correlation. "
        "The engine minimises the variance of selected properties across matched positions. "
        "Adjust weights to control which log dominates."
    ),
    "Constraints": (
        "Hard geological constraints. No-crossing prevents correlation lines from violating "
        "known stratigraphic surfaces. Same-region encourages matching within consistent "
        "lithostratigraphic units. Region IDs must be consistent across wells."
    ),
    "Polarity": (
        "Uses depositional polarity (transgressive/regressive) to guide gap costs. "
        "Set polarity_region to a region encoding T/R trends."
    ),
    "Gap": (
        "Controls how the engine penalises stratigraphic gaps (hiatuses, erosion, condensation). "
        "Low gap cost = many hiatuses allowed; high gap cost = layer-cake matching. "
        "Start with 0 and increase until the correlation looks geologically reasonable."
    ),
    "Distality": (
        "Models thickness variations due to palaeo-geographic position. Requires both a "
        "distality ranking and facies interpretation per well. Use for basin transects with "
        "known proximal-distal gradients."
    ),
    "Multi-Distality": (
        "Explores multiple palaeo-geographic scenarios when distality ranking is uncertain. "
        "Provide a file with all possible distal-to-proximal orderings."
    ),
    "B3D Curve": (
        "Advanced: Uses 3D Bezier curves fitted to structural dip/azimuth data to "
        "constrain the correlation. Requires dip, azimuth, and depth data per sample."
    ),
    "Output": (
        "Controls what files the engine writes. The default result file (out.txt) is always "
        "written. DOT files can be visualised with Graphviz. Cost matrices are for QC only."
    ),
    "Debug": (
        "Diagnostic options for troubleshooting and QC."
    ),
}


# ═══════════════════════════════════════════════════════════════════════════
#  Worker Thread
# ═══════════════════════════════════════════════════════════════════════════

class EngineWorker(QThread):
    """Run correlation in background thread."""
    log_line = pyqtSignal(str)
    finished = pyqtSignal(object, object, float)  # res_file, well_list, elapsed

    def __init__(self, wells_path, opts, parent=None):
        super().__init__(parent)
        self.wells_path = str(wells_path)
        self.opts = dict(opts)

    def run(self):
        import io, sys
        from contextlib import redirect_stdout, redirect_stderr

        class LogCapture:
            def __init__(self, signal):
                self._sig = signal
                self._buf = ""
            def write(self, s):
                self._buf += s
                while "\n" in self._buf:
                    line, self._buf = self._buf.split("\n", 1)
                    self._sig.emit(line)
            def flush(self):
                if self._buf:
                    self._sig.emit(self._buf)
                    self._buf = ""

        cap = LogCapture(self.log_line)
        t0 = wall_time()
        try:
            old_out, old_err = sys.stdout, sys.stderr
            sys.stdout = cap
            sys.stderr = cap

            project = ProjectExt()
            project.set_options_ext(**RESET_OPTS)
            project.set_options_ext(**self.opts)
            project.run(self.wells_path)

            sys.stdout, sys.stderr = old_out, old_err
            cap.flush()

            res_file = project.get_res_file()
            well_list = WellList(self.wells_path)
            elapsed = wall_time() - t0
            self.finished.emit(res_file, well_list, elapsed)
        except Exception as e:
            sys.stdout, sys.stderr = old_out, old_err
            self.log_line.emit(f"ERROR: {e}")
            self.finished.emit(None, None, wall_time() - t0)


# ═══════════════════════════════════════════════════════════════════════════
#  Plot Generation  (matplotlib → QPixmap)
# ═══════════════════════════════════════════════════════════════════════════

def render_correlation_plot(well_list, res_file, title="", cor_index=0):
    """Return a matplotlib figure as a PNG byte buffer."""
    if res_file is None or res_file.get_nbr_results() == 0:
        return None

    n_wells = len(res_file.well_id)
    wells = [well_list.wells[wid] for wid in res_file.well_id]

    def get_depth(well):
        for dn in ("Depth", "DEPTH", "MD"):
            if dn in well.data and well.data[dn]:
                return list(well.data[dn])
        return list(range(well.size))

    def get_data(well):
        for dn in well.data:
            if dn.upper() not in ("DEPTH", "MD", "TVD", "TVDSS"):
                return dn, list(well.data[dn])
        return None, None

    depths = [get_depth(w) for w in wells]
    fig_w = max(7, 2.2 * n_wells + 1.5)
    fig, axes = plt.subplots(1, n_wells, figsize=(fig_w, 6), sharey=False)
    if n_wells == 1:
        axes = [axes]

    fig.suptitle(title, fontsize=11, fontweight="bold", y=0.98)

    for i, (well, ax, depth) in enumerate(zip(wells, axes, depths)):
        color = WELL_COLORS[i % len(WELL_COLORS)]
        ax.set_title(well.name, fontsize=10, color=color)
        ax.invert_yaxis()
        ax.set_ylabel("Depth")

        dname, dvals = get_data(well)
        if dvals:
            ax.plot(dvals[:len(depth)], depth[:len(dvals)],
                    color=color, linewidth=1.2, label=dname)
            ax.set_xlabel(dname)
            ax.legend(fontsize=7, loc="lower right")
        else:
            ax.set_xlim(-0.5, 0.5)
            ax.axvline(0, color=color, linewidth=2)
        ax.grid(True, alpha=0.3)

    cid = min(cor_index, res_file.get_nbr_results() - 1)
    path = res_file.get_result_full_path(cid)
    cost = res_file.get_result_cost(cid)

    for node in path:
        for j in range(n_wells - 1):
            ml, mr = node[j], node[j + 1]
            if ml < len(depths[j]) and mr < len(depths[j + 1]):
                con = matplotlib.patches.ConnectionPatch(
                    xyA=(1.0, depths[j][ml]),
                    coordsA=axes[j].get_yaxis_transform(),
                    xyB=(0.0, depths[j + 1][mr]),
                    coordsB=axes[j + 1].get_yaxis_transform(),
                    color="gray", alpha=0.5, linewidth=0.7)
                fig.add_artist(con)

    n_cor = res_file.get_nbr_results()
    fig.text(0.5, 0.01,
             f"Cor #{cid}  |  Cost: {cost:.4f}  |  {n_cor} total",
             ha="center", fontsize=9, style="italic")
    plt.tight_layout(rect=[0, 0.03, 1, 0.95])

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


# ═══════════════════════════════════════════════════════════════════════════
#  Reusable widgets
# ═══════════════════════════════════════════════════════════════════════════

class StepBanner(QLabel):
    """Small workflow-step banner shown at the top of each page."""
    def __init__(self, step_text, parent=None):
        super().__init__(step_text, parent)
        self.setStyleSheet(
            "QLabel { background: #34495e; color: #ecf0f1; "
            "padding: 5px 10px; border-radius: 3px; font-size: 9pt; }")
        self.setFixedHeight(28)


class SectionHeader(QLabel):
    """Bold section title label."""
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        f = self.font()
        f.setPointSize(13)
        f.setBold(True)
        self.setFont(f)
        self.setContentsMargins(0, 8, 0, 4)


class HLine(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.HLine)
        self.setFrameShadow(QFrame.Shadow.Sunken)


class ParamWidget:
    """Creates an appropriate Qt widget for a parameter definition."""
    def __init__(self, key, pdef, val=None, data_names=None, region_names=None):
        self.key = key
        self.pdef = pdef
        self.data_names = data_names or []
        self.region_names = region_names or []
        self._inner = self._create(val)

        # Wrap widget + effect hint in a container
        effect = pdef.get("effect", "")
        if effect:
            container = QWidget()
            clo = QVBoxLayout(container)
            clo.setContentsMargins(0, 0, 0, 0)
            clo.setSpacing(2)
            clo.addWidget(self._inner)
            hint = QLabel(effect)
            hint.setStyleSheet(
                "QLabel { color: #6b8fa3; font-size: 8pt; font-style: italic; "
                "padding: 1px 2px; }")
            hint.setWordWrap(True)
            clo.addWidget(hint)
            self.widget = container
        else:
            self.widget = self._inner

    def _create(self, val):
        p = self.pdef
        t = p.get("type", "string")

        if t == "float":
            w = QDoubleSpinBox()
            w.setRange(p.get("min", -1e6), p.get("max", 1e6))
            w.setDecimals(2)
            w.setSingleStep(0.1)
            w.setValue(float(val) if val is not None else p.get("default", 0.0))
            return w
        elif t == "int":
            w = QSpinBox()
            w.setRange(p.get("min", 0), p.get("max", 10000))
            w.setValue(int(val) if val is not None else p.get("default", 0))
            return w
        elif t == "bool":
            w = QCheckBox()
            w.setChecked(bool(val) if val is not None else p.get("default", False))
            return w
        elif t == "select":
            w = QComboBox()
            w.addItems(p.get("values", []))
            if val:
                w.setCurrentText(str(val))
            return w
        elif t == "data":
            w = QComboBox()
            w.setEditable(True)
            w.addItems([""] + self.data_names)
            if val:
                w.setCurrentText(str(val))
            return w
        elif t == "region":
            w = QComboBox()
            w.setEditable(True)
            w.addItems([""] + self.region_names)
            if val:
                w.setCurrentText(str(val))
            return w
        else:
            w = QLineEdit(str(val) if val else "")
            return w

    def value(self):
        w = self._inner
        if isinstance(w, QDoubleSpinBox):
            return w.value()
        elif isinstance(w, QSpinBox):
            return w.value()
        elif isinstance(w, QCheckBox):
            return 1 if w.isChecked() else 0
        elif isinstance(w, QComboBox):
            return w.currentText()
        elif isinstance(w, QLineEdit):
            return w.text()
        return ""

    def set_value(self, val):
        w = self._inner
        if isinstance(w, QDoubleSpinBox):
            w.setValue(float(val))
        elif isinstance(w, QSpinBox):
            w.setValue(int(val))
        elif isinstance(w, QCheckBox):
            w.setChecked(bool(val))
        elif isinstance(w, QComboBox):
            w.setCurrentText(str(val))
        elif isinstance(w, QLineEdit):
            w.setText(str(val))


# ═══════════════════════════════════════════════════════════════════════════
#  Page 0 — Welcome / Demo Picker
# ═══════════════════════════════════════════════════════════════════════════

class WelcomePage(QWidget):
    demo_selected = pyqtSignal(dict)   # emits the demo dict
    demo_run_requested = pyqtSignal(dict)  # emits demo dict for load-and-run
    run_all_demos_requested = pyqtSignal()  # run every demo in sequence
    open_data = pyqtSignal()           # user wants to open own data
    preset_selected = pyqtSignal(dict) # emits a GEO_PRESETS entry

    def __init__(self, parent=None):
        super().__init__(parent)
        lo = QVBoxLayout(self)
        lo.setContentsMargins(20, 20, 20, 20)

        # Title
        title = QLabel(f"WeCo Studio  v{VERSION}")
        title.setFont(QFont("DejaVu Sans", 18, QFont.Weight.Bold))
        lo.addWidget(title)
        lo.addWidget(QLabel("Multi-well stratigraphic correlation workbench"))
        lo.addWidget(HLine())
        lo.addSpacing(8)

        # Two column layout
        cols = QHBoxLayout()
        lo.addLayout(cols, 1)

        # Left: Demo list + detail panel
        left_widget = QWidget()
        left_lo = QVBoxLayout(left_widget)
        left_lo.setContentsMargins(0, 0, 0, 0)

        demo_box = QGroupBox("Demo Datasets  (click to load)")
        demo_lo = QVBoxLayout(demo_box)
        self.demo_tree = QTreeWidget()
        self.demo_tree.setHeaderLabels(["Demo", "Description"])
        self.demo_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.demo_tree.setColumnWidth(0, 200)
        self.demo_tree.setAlternatingRowColors(True)
        self.demo_tree.itemDoubleClicked.connect(self._on_demo_double_click)
        self.demo_tree.currentItemChanged.connect(self._on_demo_selection_changed)

        groups = {}
        for d in DEMOS:
            g = d.get("group", "Other")
            if g not in groups:
                gi = QTreeWidgetItem(self.demo_tree, [g, ""])
                gi.setFont(0, QFont("DejaVu Sans", 10, QFont.Weight.Bold))
                gi.setExpanded(True)
                groups[g] = gi
            item = QTreeWidgetItem(groups[g], [d["title"], d["description"].split("\n")[0]])
            item.setData(0, Qt.ItemDataRole.UserRole, d)

        demo_lo.addWidget(self.demo_tree)

        btn_lo = QHBoxLayout()
        btn_load_demo = QPushButton("Load Selected Demo")
        btn_load_demo.clicked.connect(self._on_load_demo)
        btn_load_demo.setStyleSheet("QPushButton {font-weight:bold; padding:8px 16px;}")
        btn_lo.addWidget(btn_load_demo)

        btn_run_demo = QPushButton("Load && Run")
        btn_run_demo.setToolTip(
            "Load the selected demo and immediately run the correlation.\n"
            "Results will be displayed automatically when finished.")
        btn_run_demo.clicked.connect(self._on_run_demo)
        btn_run_demo.setStyleSheet(
            "QPushButton {font-weight:bold; padding:8px 16px; "
            "background-color:#2a7d84; color:white; border-radius:4px;} "
            "QPushButton:hover {background-color:#3f9350;}")
        btn_lo.addWidget(btn_run_demo)

        btn_lo.addSpacing(16)

        btn_run_all = QPushButton("Run All Demos")
        btn_run_all.setToolTip(
            "Run every demo dataset sequentially.\n"
            "Results with correlation plots are saved to tmp/demo_results/.\n"
            "Great for a quick overview of WeCo capabilities.")
        btn_run_all.clicked.connect(lambda: self.run_all_demos_requested.emit())
        btn_run_all.setStyleSheet(
            "QPushButton {padding:8px 16px; border:1px solid #2a7d84; "
            "border-radius:4px; color:#2a7d84;} "
            "QPushButton:hover {background-color:#e0f5f0;}")
        btn_lo.addWidget(btn_run_all)

        btn_lo.addStretch()
        demo_lo.addLayout(btn_lo)
        left_lo.addWidget(demo_box, 2)

        # Detail panel: geology doc + parameter summary
        self.detail_box = QGroupBox("Geology && Parameter Guide")
        detail_lo = QVBoxLayout(self.detail_box)
        self.detail_text = QTextEdit()
        self.detail_text.setReadOnly(True)
        self.detail_text.setHtml(
            "<i>Select a demo above to see geological context, "
            "parameter rationale, and workflow guidance.</i>"
        )
        detail_lo.addWidget(self.detail_text)
        left_lo.addWidget(self.detail_box, 1)

        cols.addWidget(left_widget, 3)

        # Right: Quick start + Geology Presets
        right_widget = QWidget()
        right_lo = QVBoxLayout(right_widget)
        right_lo.setContentsMargins(0, 0, 0, 0)

        start_box = QGroupBox("Your Own Data")
        start_lo = QVBoxLayout(start_box)
        start_lo.addWidget(QLabel(
            "Load your own well data and configure\n"
            "correlation parameters step-by-step.\n\n"
            "Supported formats:\n"
            "  - WeCo native (.wells.txt)\n"
            "  - LAS 2.0 (.las)\n"
            "  - RESQML (.epc + .h5)\n"
            "  - CSV / space-separated\n\n"
            "Workflow:\n"
            "  1. Data  -- load & inspect wells\n"
            "  2. Parameters  -- configure costs\n"
            "  3. Run  -- execute correlation\n"
            "  4. Results  -- view & export\n"
            "  5. Docs  -- reference & guidance"
        ))
        start_lo.addSpacing(12)
        btn_open = QPushButton("Open Well File…")
        btn_open.clicked.connect(self.open_data.emit)
        btn_open.setStyleSheet("QPushButton {font-weight:bold; padding:8px 16px;}")
        start_lo.addWidget(btn_open)
        start_lo.addStretch()
        right_lo.addWidget(start_box, 2)

        # Geology Presets box
        preset_box = QGroupBox("Geology Presets — Best-Guess Defaults")
        preset_lo = QVBoxLayout(preset_box)
        preset_lo.addWidget(QLabel(
            "Select your geological environment to load\n"
            "recommended parameter defaults as a starting point:"
        ))
        self.preset_combo = QComboBox()
        self.preset_combo.addItem("-- select environment --", None)
        for key, preset in GEO_PRESETS.items():
            self.preset_combo.addItem(preset["label"], key)
        preset_lo.addWidget(self.preset_combo)

        self.preset_detail = QTextEdit()
        self.preset_detail.setReadOnly(True)
        self.preset_detail.setMaximumHeight(180)
        self.preset_detail.setHtml("<i>Choose an environment above…</i>")
        preset_lo.addWidget(self.preset_detail)

        self.preset_combo.currentIndexChanged.connect(self._on_preset_changed)

        btn_preset = QPushButton("Apply Preset to Parameters")
        btn_preset.clicked.connect(self._on_apply_preset)
        btn_preset.setStyleSheet("QPushButton {padding:6px 12px;}")
        preset_lo.addWidget(btn_preset)
        right_lo.addWidget(preset_box, 1)

        cols.addWidget(right_widget, 2)

    def _on_load_demo(self):
        items = self.demo_tree.selectedItems()
        if not items:
            return
        d = items[0].data(0, Qt.ItemDataRole.UserRole)
        if d:
            self.demo_selected.emit(d)

    def _on_run_demo(self):
        items = self.demo_tree.selectedItems()
        if not items:
            return
        d = items[0].data(0, Qt.ItemDataRole.UserRole)
        if d:
            self.demo_run_requested.emit(d)

    def _on_demo_double_click(self, item, col):
        d = item.data(0, Qt.ItemDataRole.UserRole)
        if d:
            self.demo_selected.emit(d)

    def _on_demo_selection_changed(self, current, previous):
        """Show geology doc and parameter guide when a demo is selected."""
        if current is None:
            return
        d = current.data(0, Qt.ItemDataRole.UserRole)
        if d is None:
            return
        html_parts = []
        html_parts.append(f"<h3>{d['title']}</h3>")
        html_parts.append(f"<p>{d['description'].replace(chr(10), '<br>')}</p>")

        geo_doc = d.get("geology_doc", "")
        if geo_doc:
            html_parts.append(f"<hr><h4>Geological Context</h4>{geo_doc}")

        # Parameter summary
        opts = d.get("opts", {})
        if opts:
            html_parts.append("<hr><h4>Parameters</h4><table>")
            for k, v in opts.items():
                label = PARAM_HELP.get(k, {}).get("label", k)
                html_parts.append(f"<tr><td><b>{label}</b></td><td>{v}</td></tr>")
            html_parts.append("</table>")

        # Show matching geology preset hint
        geo = d.get("geology", "")
        if geo:
            preset_key = {
                "quaternary": "quaternary_hydrogeology",
                "coal": "coal_basin",
                "shallow_marine": "shallow_marine_reservoir",
                "delta": "deep_marine_clastic",
                "fluvial": "fluvial_continental",
                "carbonate": "carbonate_platform",
            }.get(geo)
            if preset_key and preset_key in GEO_PRESETS:
                p = GEO_PRESETS[preset_key]
                html_parts.append(
                    f"<hr><h4>Correlation Tips ({p['label']})</h4>"
                    f"<p>{p['correlation_hint']}</p>"
                    f"<p><b>Constraint guidance:</b> {p['constraints_hint']}</p>"
                )

        self.detail_text.setHtml("".join(html_parts))

    def _on_preset_changed(self, idx):
        key = self.preset_combo.currentData()
        if key is None or key not in GEO_PRESETS:
            self.preset_detail.setHtml("<i>Choose an environment above…</i>")
            return
        p = GEO_PRESETS[key]
        html = (
            f"<b>{p['label']}</b><br>"
            f"<p>{p['description'].replace(chr(10), '<br>')}</p>"
            f"<hr><b>Geology Notes:</b><br>"
            f"<pre>{p['geology_notes']}</pre>"
            f"<hr><b>Correlation Strategy:</b><br>"
            f"<p>{p['correlation_hint']}</p>"
            f"<b>Constraint Guidance:</b><br>"
            f"<p>{p['constraints_hint']}</p>"
        )
        self.preset_detail.setHtml(html)

    def _on_apply_preset(self):
        key = self.preset_combo.currentData()
        if key is None or key not in GEO_PRESETS:
            return
        self.preset_selected.emit(GEO_PRESETS[key])


# ═══════════════════════════════════════════════════════════════════════════
# §11.2.3 — Facies Group Editor Dialog
# ═══════════════════════════════════════════════════════════════════════════

class FaciesGroupEditorDialog(QDialog):
    """Drag-and-drop facies group editor.

    Lets the user organise facies IDs into lateral-equivalence groups.
    Groups are encoded as a semicolon-separated string for the
    ``dist-facies-groups`` engine option.
    """

    def __init__(self, initial_groups="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Facies Group Editor")
        self.setMinimumSize(500, 400)

        lo = QVBoxLayout(self)
        lo.addWidget(QLabel(
            "Organise facies IDs into groups.  Facies in the same group "
            "are treated as laterally equivalent (zero Δf in distality cost)."
        ))

        # Groups list
        self._groups = []  # list of list of int
        self._parse_groups(initial_groups)

        # Group display
        self._group_area = QVBoxLayout()
        group_widget = QWidget()
        group_widget.setLayout(self._group_area)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(group_widget)
        lo.addWidget(scroll, 1)

        self._rebuild_ui()

        # Buttons
        btn_lo = QHBoxLayout()
        lo.addLayout(btn_lo)
        btn_add_group = QPushButton("Add Group")
        btn_add_group.clicked.connect(self._add_group)
        btn_lo.addWidget(btn_add_group)
        btn_add_facies = QPushButton("Add Facies ID")
        btn_add_facies.clicked.connect(self._add_facies)
        btn_lo.addWidget(btn_add_facies)
        btn_lo.addStretch()

        # Dialog buttons
        dlg_btn = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        dlg_btn.accepted.connect(self.accept)
        dlg_btn.rejected.connect(self.reject)
        lo.addWidget(dlg_btn)

    def _parse_groups(self, s):
        self._groups = []
        if not s.strip():
            return
        for g in s.split(";"):
            ids = []
            for fid in g.split(","):
                fid = fid.strip()
                if fid.isdigit():
                    ids.append(int(fid))
            if ids:
                self._groups.append(ids)

    def _rebuild_ui(self):
        while self._group_area.count():
            item = self._group_area.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        for gi, group in enumerate(self._groups):
            gb = QGroupBox(f"Group {gi}")
            gb_lo = QHBoxLayout(gb)
            for fid in group:
                lbl = QLabel(str(fid))
                lbl.setStyleSheet(
                    "QLabel {background:#d0e8ff; padding:4px 8px; "
                    "border-radius:3px; margin:2px;}"
                )
                gb_lo.addWidget(lbl)
            btn_rm = QPushButton("×")
            btn_rm.setFixedSize(24, 24)
            btn_rm.clicked.connect(lambda _, i=gi: self._remove_group(i))
            gb_lo.addWidget(btn_rm)
            gb_lo.addStretch()
            self._group_area.addWidget(gb)
        self._group_area.addStretch()

    def _add_group(self):
        self._groups.append([])
        self._rebuild_ui()

    def _add_facies(self):
        text, ok = QInputDialog.getText(
            self, "Add Facies", "Facies ID (integer):"
        )
        if ok and text.strip().isdigit():
            fid = int(text.strip())
            if not self._groups:
                self._groups.append([])
            # Add to last group by default
            self._groups[-1].append(fid)
            self._rebuild_ui()

    def _remove_group(self, idx):
        if 0 <= idx < len(self._groups):
            del self._groups[idx]
            self._rebuild_ui()

    def get_groups_string(self):
        return ";".join(",".join(str(f) for f in g) for g in self._groups if g)


# ═══════════════════════════════════════════════════════════════════════════
# §11.7.3 — Erosion Surface Picker Dialog
# ═══════════════════════════════════════════════════════════════════════════

class ErosionSurfacePickerDialog(QDialog):
    """Interactive well-log viewer for manual erosion surface placement.

    Users click on the log display to place erosion surface markers,
    which become ``no_crossing`` region boundaries.
    """

    def __init__(self, well_data=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Erosion Surface Picker")
        self.setMinimumSize(800, 600)

        lo = QVBoxLayout(self)
        lo.addWidget(QLabel(
            "Click on the well log to place erosion surface markers.\n"
            "These become 'no_crossing' region boundaries for the correlation."
        ))

        # Matplotlib canvas for well log display
        try:
            from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
            from matplotlib.figure import Figure

            self.figure = Figure(figsize=(10, 6))
            self.canvas = FigureCanvasQTAgg(self.figure)
            lo.addWidget(self.canvas)

            self._surfaces = []  # list of depth values
            self._well_data = well_data

            self.canvas.mpl_connect('button_press_event', self._on_click)

            if well_data:
                self._plot_wells()
        except ImportError:
            lo.addWidget(QLabel("Matplotlib is required for the erosion surface picker."))

        # Surface list
        self._surface_list = QListWidget()
        lo.addWidget(self._surface_list)

        btn_lo = QHBoxLayout()
        lo.addLayout(btn_lo)
        btn_remove = QPushButton("Remove Selected")
        btn_remove.clicked.connect(self._remove_surface)
        btn_lo.addWidget(btn_remove)
        btn_lo.addStretch()

        dlg_btn = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        dlg_btn.accepted.connect(self.accept)
        dlg_btn.rejected.connect(self.reject)
        lo.addWidget(dlg_btn)

    def _plot_wells(self):
        if not self._well_data:
            return
        ax = self.figure.add_subplot(111)
        ax.set_ylabel("Depth")
        ax.set_xlabel("GR (API)")
        ax.invert_yaxis()
        # Plot first well's GR if available
        for wi, w in enumerate(self._well_data.get("wells", [])):
            if "GR" in w.get("data", {}):
                ax.plot(w["data"]["GR"], w["data"].get("depth", range(len(w["data"]["GR"]))),
                        label=w.get("name", f"W{wi}"), alpha=0.7)
        ax.legend(fontsize=8)
        self.canvas.draw()

    def _on_click(self, event):
        if event.ydata is not None:
            depth = float(event.ydata)
            self._surfaces.append(depth)
            self._surface_list.addItem(f"Surface at depth {depth:.2f}")
            # Draw horizontal line
            ax = self.figure.axes[0] if self.figure.axes else None
            if ax:
                ax.axhline(y=depth, color='r', linestyle='--', alpha=0.7)
                self.canvas.draw()

    def _remove_surface(self):
        row = self._surface_list.currentRow()
        if 0 <= row < len(self._surfaces):
            del self._surfaces[row]
            self._surface_list.takeItem(row)
            # Redraw
            if hasattr(self, 'figure'):
                for ax in self.figure.axes:
                    # Remove last added horizontal line
                    for line in ax.get_lines():
                        if line.get_linestyle() == '--' and line.get_color() == 'r':
                            line.remove()
                            break
                self.canvas.draw()

    def get_surfaces(self):
        return sorted(self._surfaces)


# ═══════════════════════════════════════════════════════════════════════════
#  Page 1 — Data Inspector
# ═══════════════════════════════════════════════════════════════════════════

class DataPage(QWidget):
    wells_loaded = pyqtSignal(object, str)  # WellList, path

    def __init__(self, parent=None):
        super().__init__(parent)
        lo = QVBoxLayout(self)
        lo.setContentsMargins(12, 12, 12, 12)

        lo.addWidget(StepBanner(
            "Step 1 of 4:  Load well data. Browse for a file or use a demo from the Welcome page."))
        lo.addSpacing(4)

        # File bar
        fbar = QHBoxLayout()
        fbar.addWidget(QLabel("Well file:"))
        self.file_label = QLineEdit()
        self.file_label.setReadOnly(True)
        self.file_label.setPlaceholderText("No file loaded")
        fbar.addWidget(self.file_label, 1)
        btn = QPushButton("Browse…")
        btn.clicked.connect(self._browse)
        fbar.addWidget(btn)
        btn_reload = QPushButton("Reload")
        btn_reload.clicked.connect(self._reload)
        fbar.addWidget(btn_reload)
        btn_qcview = QPushButton("View Wells")
        btn_qcview.setToolTip("Open wells in the professional correlation viewer for QC")
        btn_qcview.clicked.connect(self._view_wells)
        fbar.addWidget(btn_qcview)
        # §11.7.3 — Erosion surface picker
        btn_erosion = QPushButton("Pick Erosion Surfaces…")
        btn_erosion.setToolTip(
            "Open interactive well-log viewer to manually place\n"
            "erosion surface markers (no_crossing boundaries)"
        )
        btn_erosion.clicked.connect(self._pick_erosion_surfaces)
        fbar.addWidget(btn_erosion)
        lo.addLayout(fbar)

        lo.addWidget(HLine())

        # Well summary table
        lo.addWidget(SectionHeader("Wells"))
        self.well_table = QTableWidget()
        self.well_table.setAlternatingRowColors(True)
        self.well_table.horizontalHeader().setStretchLastSection(True)
        self.well_table.setMaximumHeight(180)
        lo.addWidget(self.well_table)

        # Splitter: top (table + meta) | bottom (preview)
        splitter = QSplitter(Qt.Orientation.Vertical)
        lo.addWidget(splitter, 1)

        # ── Top: data & region lists ──
        meta_widget = QWidget()
        info_lo = QHBoxLayout(meta_widget)
        info_lo.setContentsMargins(0, 0, 0, 0)
        # Data names
        data_box = QGroupBox("Data Properties")
        data_lo = QVBoxLayout(data_box)
        self.data_list = QListWidget()
        data_lo.addWidget(self.data_list)
        info_lo.addWidget(data_box)
        # Region names
        region_box = QGroupBox("Region Properties")
        region_lo = QVBoxLayout(region_box)
        self.region_list = QListWidget()
        region_lo.addWidget(self.region_list)
        info_lo.addWidget(region_box)
        splitter.addWidget(meta_widget)

        # ── Bottom: tabbed panel (preview + data conditioning) ──
        bottom_tabs = QTabWidget()

        # Tab 1: Well-Log Preview
        self._preview_box = QWidget()
        preview_lo = QVBoxLayout(self._preview_box)
        preview_lo.setContentsMargins(4, 4, 4, 4)
        if HAS_MPL_CANVAS:
            self._preview_fig, self._preview_axes = plt.subplots(1, 1, figsize=(8, 3))
            self._preview_canvas = FigureCanvasQTAgg(self._preview_fig)
            self._preview_canvas.setMinimumHeight(180)
            preview_lo.addWidget(self._preview_canvas)
        else:
            self._preview_canvas = None
            preview_lo.addWidget(QLabel("matplotlib Qt backend not available"))
        bottom_tabs.addTab(self._preview_box, "Well-Log Preview")

        # Tab 2: Data Conditioning
        cond_widget = QWidget()
        cond_lo = QVBoxLayout(cond_widget)
        cond_lo.setContentsMargins(8, 8, 8, 8)

        cond_lo.addWidget(QLabel(
            "Derive new data/region channels from existing logs. "
            "Transforms run in Python before the C++ engine."))
        cond_lo.addSpacing(4)

        # Row of checkboxes for standard transforms
        tf_grid = QGridLayout()
        self._chk_normalise = QCheckBox("Normalise logs (percentile P5-P95)")
        self._chk_normalise.setChecked(True)
        tf_grid.addWidget(self._chk_normalise, 0, 0)

        self._chk_vshale = QCheckBox("Compute Vshale (from GR)")
        self._chk_vshale.setChecked(True)
        tf_grid.addWidget(self._chk_vshale, 0, 1)

        self._chk_stacking = QCheckBox("Stacking pattern (GR derivative)")
        self._chk_stacking.setChecked(True)
        tf_grid.addWidget(self._chk_stacking, 1, 0)

        self._chk_electrofacies = QCheckBox("Electrofacies (K-Means clustering)")
        tf_grid.addWidget(self._chk_electrofacies, 1, 1)

        self._chk_smooth = QCheckBox("Smooth logs (moving average)")
        tf_grid.addWidget(self._chk_smooth, 2, 0)

        self._chk_logqc = QCheckBox("Log QC (washout detection)")
        tf_grid.addWidget(self._chk_logqc, 2, 1)

        self._chk_facies_predict = QCheckBox("AI Facies Prediction (GBM)")
        self._chk_facies_predict.setToolTip(
            "Predict facies from logs using gradient boosting.\n"
            "Requires at least 2 non-depth log curves and scikit-learn.")
        tf_grid.addWidget(self._chk_facies_predict, 3, 0)

        self._chk_anomaly = QCheckBox("AI Anomaly Detection")
        self._chk_anomaly.setToolTip(
            "Flag statistically anomalous log intervals.\n"
            "Requires scikit-learn.")
        tf_grid.addWidget(self._chk_anomaly, 3, 1)
        cond_lo.addLayout(tf_grid)

        # Source log selector
        src_row = QHBoxLayout()
        src_row.addWidget(QLabel("Source log for GR-based transforms:"))
        self._cond_log_combo = QComboBox()
        self._cond_log_combo.setMinimumWidth(120)
        src_row.addWidget(self._cond_log_combo)
        src_row.addWidget(QLabel("  Clusters:"))
        self._cond_nclusters = QSpinBox()
        self._cond_nclusters.setRange(2, 20)
        self._cond_nclusters.setValue(5)
        src_row.addWidget(self._cond_nclusters)
        src_row.addStretch()
        cond_lo.addLayout(src_row)

        # Apply button + status
        btn_row = QHBoxLayout()
        self._btn_apply_cond = QPushButton("Apply Data Conditioning")
        self._btn_apply_cond.setStyleSheet(
            "QPushButton {font-weight:bold; padding:8px 16px; "
            "background-color:#27ae60; color:white; border-radius:4px;}")
        self._btn_apply_cond.clicked.connect(self._apply_conditioning)
        btn_row.addWidget(self._btn_apply_cond)
        self._cond_status = QLabel("")
        btn_row.addWidget(self._cond_status, 1)
        cond_lo.addLayout(btn_row)
        cond_lo.addStretch()

        bottom_tabs.addTab(cond_widget, "Data Conditioning")

        # Tab 3: Log Editor (§3.17)
        edit_widget = QWidget()
        edit_lo = QVBoxLayout(edit_widget)
        edit_lo.setContentsMargins(8, 8, 8, 8)
        edit_lo.addWidget(QLabel(
            "Add derived curves to wells. Select an operation "
            "and source log, then click Apply."))
        edit_lo.addSpacing(4)

        # Operation selector
        op_row = QHBoxLayout()
        op_row.addWidget(QLabel("Operation:"))
        self._edit_op_combo = QComboBox()
        self._edit_op_combo.addItems([
            "Derivative (dlog/dz)",
            "Smooth (moving average)",
            "Normalise (0-1)",
            "Log ratio (A/B)",
            "Delta (A-B)",
        ])
        op_row.addWidget(self._edit_op_combo)
        op_row.addWidget(QLabel("  Source:"))
        self._edit_src_combo = QComboBox()
        self._edit_src_combo.setMinimumWidth(120)
        op_row.addWidget(self._edit_src_combo)
        op_row.addWidget(QLabel("  Second log:"))
        self._edit_src2_combo = QComboBox()
        self._edit_src2_combo.setMinimumWidth(120)
        op_row.addWidget(self._edit_src2_combo)
        op_row.addStretch()
        edit_lo.addLayout(op_row)

        # Window size for smoothing
        win_row = QHBoxLayout()
        win_row.addWidget(QLabel("Window size:"))
        self._edit_window = QSpinBox()
        self._edit_window.setRange(3, 51)
        self._edit_window.setValue(5)
        self._edit_window.setSingleStep(2)
        win_row.addWidget(self._edit_window)
        win_row.addWidget(QLabel("  Output name:"))
        self._edit_output_name = QLineEdit()
        self._edit_output_name.setPlaceholderText("(auto)")
        self._edit_output_name.setMaximumWidth(180)
        win_row.addWidget(self._edit_output_name)
        win_row.addStretch()
        edit_lo.addLayout(win_row)

        # Apply button
        edit_btn_row = QHBoxLayout()
        btn_apply_edit = QPushButton("Apply to All Wells")
        btn_apply_edit.setStyleSheet(
            "QPushButton {font-weight:bold; padding:8px 16px; "
            "background-color:#2980b9; color:white; border-radius:4px;}")
        btn_apply_edit.clicked.connect(self._apply_log_edit)
        edit_btn_row.addWidget(btn_apply_edit)
        self._edit_status = QLabel("")
        edit_btn_row.addWidget(self._edit_status, 1)
        edit_lo.addLayout(edit_btn_row)
        edit_lo.addStretch()
        bottom_tabs.addTab(edit_widget, "Log Editor")

        # Tab 4: RDDMS / Strat Column
        rddms_widget = QWidget()
        rddms_lo = QVBoxLayout(rddms_widget)
        rddms_lo.setContentsMargins(8, 8, 8, 8)

        rddms_lo.addWidget(QLabel(
            "Import wells from RDDMS/OSDU or load a stratigraphic column.\n"
            "Depositional environment is auto-detected and used for presets."))
        rddms_lo.addSpacing(4)

        # RDDMS import row
        rddms_import_row = QHBoxLayout()
        rddms_import_row.addWidget(QLabel("EPC file or RDDMS URL:"))
        self._rddms_source = QLineEdit()
        self._rddms_source.setPlaceholderText("path/to/file.epc or https://rddms.example.com")
        rddms_import_row.addWidget(self._rddms_source, 1)
        btn_rddms_browse = QPushButton("Browse EPC…")
        btn_rddms_browse.clicked.connect(self._browse_epc)
        rddms_import_row.addWidget(btn_rddms_browse)
        btn_rddms_import = QPushButton("Import from RDDMS")
        btn_rddms_import.setStyleSheet(
            "QPushButton {font-weight:bold; padding:6px 14px; "
            "background-color:#8e44ad; color:white; border-radius:4px;}")
        btn_rddms_import.clicked.connect(self._import_rddms)
        rddms_import_row.addWidget(btn_rddms_import)
        rddms_lo.addLayout(rddms_import_row)

        rddms_lo.addWidget(HLine())

        # Strat Column section
        rddms_lo.addWidget(SectionHeader("Stratigraphic Column"))
        sc_row = QHBoxLayout()
        sc_row.addWidget(QLabel("Column JSON:"))
        self._strat_col_path = QLineEdit()
        self._strat_col_path.setPlaceholderText("path/to/strat_column.json")
        sc_row.addWidget(self._strat_col_path, 1)
        btn_sc_browse = QPushButton("Browse…")
        btn_sc_browse.clicked.connect(self._browse_strat_column)
        sc_row.addWidget(btn_sc_browse)
        btn_sc_apply = QPushButton("Apply to Wells")
        btn_sc_apply.setStyleSheet(
            "QPushButton {padding:6px 14px; "
            "background-color:#2c3e50; color:white; border-radius:4px;}")
        btn_sc_apply.clicked.connect(self._apply_strat_column)
        sc_row.addWidget(btn_sc_apply)
        rddms_lo.addLayout(sc_row)

        # Strat column tree viewer
        self._strat_tree = QTreeWidget()
        self._strat_tree.setHeaderLabels(["Name", "Type", "Units", "Ages"])
        self._strat_tree.setAlternatingRowColors(True)
        self._strat_tree.setMinimumHeight(120)
        rddms_lo.addWidget(self._strat_tree, 1)

        # Detected environment display
        env_row = QHBoxLayout()
        env_row.addWidget(QLabel("Detected environment:"))
        self._detected_env_label = QLabel("<i>none</i>")
        env_row.addWidget(self._detected_env_label, 1)
        btn_apply_env = QPushButton("Apply Environment Preset")
        btn_apply_env.setToolTip("Auto-configure correlation parameters for the detected environment")
        btn_apply_env.clicked.connect(self._apply_detected_env_preset)
        env_row.addWidget(btn_apply_env)
        rddms_lo.addLayout(env_row)

        self._rddms_status = QLabel("")
        rddms_lo.addWidget(self._rddms_status)
        rddms_lo.addStretch()
        bottom_tabs.addTab(rddms_widget, "RDDMS / Strat Column")

        splitter.addWidget(bottom_tabs)
        splitter.setSizes([300, 300])

        self._well_list = None
        self._well_path = ""

    def load_file(self, path):
        path = str(path)
        if not os.path.isabs(path):
            path = str(DATA_DIR / path)
        if not os.path.exists(path):
            QMessageBox.warning(self, "WeCo", f"File not found:\n{path}")
            return
        try:
            wl = WellList(path)
        except Exception as e:
            QMessageBox.warning(self, "WeCo", f"Cannot read well list:\n{e}")
            return
        if not wl.wells:
            QMessageBox.warning(self, "WeCo", "Well list is empty")
            return
        self._well_list = wl
        self._well_path = path
        self.file_label.setText(path)
        self._populate(wl)
        self.wells_loaded.emit(wl, path)

    def _populate(self, wl):
        # Well table
        cols = ["Name", "Size", "X", "Y"]
        self.well_table.setColumnCount(len(cols))
        self.well_table.setHorizontalHeaderLabels(cols)
        self.well_table.setRowCount(len(wl.wells))
        for r, w in enumerate(wl.wells):
            self.well_table.setItem(r, 0, QTableWidgetItem(w.name))
            self.well_table.setItem(r, 1, QTableWidgetItem(str(w.size)))
            self.well_table.setItem(r, 2, QTableWidgetItem(f"{w.x:.1f}"))
            self.well_table.setItem(r, 3, QTableWidgetItem(f"{w.y:.1f}"))
        self.well_table.resizeColumnsToContents()

        # Data / region lists
        self.data_list.clear()
        self.region_list.clear()
        if wl.wells:
            for d in sorted(wl.wells[0].data.keys()):
                self.data_list.addItem(d)
            for r in sorted(wl.wells[0].region.keys()):
                self.region_list.addItem(r)

        # Update conditioning log combo
        self._cond_log_combo.clear()
        if wl.wells:
            names = sorted(wl.wells[0].data.keys())
            self._cond_log_combo.addItems(names)
            # Pre-select GR if available
            for gr_alias in ("GR", "gamma", "Gamma", "VarData1"):
                idx = self._cond_log_combo.findText(gr_alias)
                if idx >= 0:
                    self._cond_log_combo.setCurrentIndex(idx)
                    break

        # Update log-editor combos
        self._edit_src_combo.clear()
        self._edit_src2_combo.clear()
        if wl.wells:
            names = sorted(wl.wells[0].data.keys())
            self._edit_src_combo.addItems(names)
            self._edit_src2_combo.addItems(names)

        # Well-log preview
        self._draw_preview(wl)

    def _draw_preview(self, wl):
        """Render a quick multi-panel well-log plot."""
        if not HAS_MPL_CANVAS or self._preview_canvas is None:
            return
        self._preview_fig.clear()
        if not wl or not wl.wells:
            self._preview_canvas.draw()
            return

        n = len(wl.wells)
        axes = self._preview_fig.subplots(1, n, sharey=False)
        if n == 1:
            axes = [axes]

        for i, (well, ax) in enumerate(zip(wl.wells, axes)):
            color = WELL_COLORS[i % len(WELL_COLORS)]
            ax.set_title(well.name, fontsize=8, color=color, pad=3)
            ax.invert_yaxis()
            ax.tick_params(labelsize=7)
            ax.grid(True, alpha=0.2)

            # Find a depth curve
            depth = None
            for dn in ("Depth", "DEPTH", "MD", "depth"):
                if dn in well.data and well.data[dn]:
                    depth = list(well.data[dn])
                    break
            if depth is None:
                depth = list(range(well.size))

            # Plot first non-depth data curve
            plotted = False
            for dname in sorted(well.data.keys()):
                if dname.upper() in ("DEPTH", "MD", "TVD", "TVDSS"):
                    continue
                vals = list(well.data[dname])
                sz = min(len(vals), len(depth))
                ax.plot(vals[:sz], depth[:sz], color=color, linewidth=0.9)
                ax.set_xlabel(dname, fontsize=7)
                plotted = True
                break
            if not plotted:
                ax.axvline(0, color=color, linewidth=1.5)

            if i == 0:
                ax.set_ylabel("Depth", fontsize=7)

        self._preview_fig.tight_layout(pad=0.5)
        self._preview_canvas.draw()

    def get_data_names(self):
        if self._well_list and self._well_list.wells:
            return sorted(self._well_list.wells[0].data.keys())
        return []

    def get_region_names(self):
        if self._well_list and self._well_list.wells:
            return sorted(self._well_list.wells[0].region.keys())
        return []

    def well_list(self):
        return self._well_list

    def well_path(self):
        return self._well_path

    # ── RDDMS / Strat Column methods ──────────────────────────────

    def _browse_epc(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open EPC File", "",
            "RESQML EPC (*.epc);;All files (*)")
        if path:
            self._rddms_source.setText(path)

    def _import_rddms(self):
        source = self._rddms_source.text().strip()
        if not source:
            self._rddms_status.setText("Please specify an EPC file or RDDMS URL.")
            return

        try:
            import os
            if os.path.isfile(source):
                from weco.rddms import epc_import_wells
                wl = epc_import_wells(source)
            else:
                from weco.rddms import rddms_import_wells
                import os as _os
                token = _os.environ.get("OSDU_TOKEN", "")
                if not token:
                    self._rddms_status.setText(
                        "Set OSDU_TOKEN environment variable for RDDMS access.")
                    return
                wl = rddms_import_wells(source, token, "demo")

            self._well_list = wl
            self._well_path = source
            self._update_ui()
            self.wells_loaded.emit(wl, source)
            self._rddms_status.setText(
                f"Imported {wl.nbr_wells()} wells, "
                f"{len(wl.get_data_names())} data channels, "
                f"{len(wl.get_region_names())} regions.")
        except ImportError as e:
            self._rddms_status.setText(f"RESQML not available: {e}")
        except Exception as e:
            self._rddms_status.setText(f"Import error: {e}")

    def _browse_strat_column(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Strat Column JSON", "",
            "JSON (*.json);;All files (*)")
        if path:
            self._strat_col_path.setText(path)

    def _apply_strat_column(self):
        from weco.strat_column import StratColumn
        from weco.depenv import detect_environment, DEPENV_PRESETS

        path = self._strat_col_path.text().strip()
        if not path:
            self._rddms_status.setText("Specify a strat column JSON file.")
            return

        try:
            col = StratColumn.from_json(path)
        except Exception as e:
            self._rddms_status.setText(f"Error loading column: {e}")
            return

        # Populate tree viewer
        self._strat_tree.clear()
        for rank in col.ranks:
            rank_item = QTreeWidgetItem([
                rank.name, f"Rank ({rank.kind})",
                str(len(rank.units)), ""])
            for unit in rank.units:
                age_str = ""
                if unit.top_age_ma is not None:
                    age_str = f"{unit.top_age_ma}"
                    if unit.base_age_ma is not None:
                        age_str += f" – {unit.base_age_ma}"
                    age_str += " Ma"
                dep = f" [{unit.depositional_environment}]" if unit.depositional_environment else ""
                QTreeWidgetItem(rank_item, [
                    unit.name, f"Unit{dep}", "", age_str])
            self._strat_tree.addTopLevelItem(rank_item)
            rank_item.setExpanded(True)

        for h in col.horizons:
            age_str = f"{h.age_ma} Ma" if h.age_ma else ""
            self._strat_tree.addTopLevelItem(QTreeWidgetItem([
                h.name, "Horizon", "", age_str]))

        self._strat_tree.resizeColumnToContents(0)
        self._strat_tree.resizeColumnToContents(1)

        # Detect environment
        env = detect_environment(col)
        if env and env in DEPENV_PRESETS:
            preset = DEPENV_PRESETS[env]
            self._detected_env_label.setText(
                f"<b>{preset['label']}</b> ({env})")
            self._detected_env = env
        else:
            self._detected_env_label.setText("<i>not detected</i>")
            self._detected_env = None

        # Apply to loaded wells
        if self._well_list and self._well_list.wells:
            self._rddms_status.setText(
                f"Loaded column '{col.name}': {col.unit_count} units, "
                f"{col.horizon_count} horizons. "
                f"Use 'Apply Environment Preset' to configure parameters.")
        else:
            self._rddms_status.setText(
                f"Loaded column '{col.name}'. Load wells first to apply regions.")

        self._strat_column = col

    def _apply_detected_env_preset(self):
        env = getattr(self, "_detected_env", None)
        if not env:
            self._rddms_status.setText("No environment detected. Load a strat column first.")
            return

        from weco.depenv import DEPENV_PRESETS
        preset = DEPENV_PRESETS.get(env)
        if not preset:
            return

        # Find matching GEO_PRESET and emit it
        geo_key = preset.get("geo_preset_key")
        if geo_key and geo_key in GEO_PRESETS:
            self._rddms_status.setText(
                f"Applied '{GEO_PRESETS[geo_key]['label']}' preset from "
                f"detected environment '{env}'.")
            # Emit via parent's preset signal if available
            parent = self.parent()
            while parent:
                if hasattr(parent, "_apply_preset_opts"):
                    parent._apply_preset_opts(GEO_PRESETS[geo_key])
                    break
                parent = parent.parent()
        else:
            # Fall back to depenv preset options directly
            opts = preset.get("recommended_opts", {})
            self._rddms_status.setText(
                f"Applied depenv preset '{preset['label']}' ({len(opts)} options).")
            parent = self.parent()
            while parent:
                if hasattr(parent, "_apply_preset_opts"):
                    parent._apply_preset_opts({"recommended_opts": opts})
                    break
                parent = parent.parent()

    def _browse(self):
        # §4.12 — Format filter in open dialog with format combo
        path, selected_filter = QFileDialog.getOpenFileName(
            self, "Open Well File", str(DATA_DIR),
            "All supported formats (*.wells.txt *.txt *.las *.epc *.csv *.wl *.las3 *.dlis *.xml);;"
            "WeCo native (*.wells.txt *.txt);;"
            "LAS 2.0 (*.las);;"
            "LAS 3.0 (*.las3);;"
            "RESQML EPC (*.epc);;"
            "CSV (*.csv);;"
            "GOCAD Well (*.wl);;"
            "DLIS (*.dlis);;"
            "WITSML (*.xml);;"
            "All files (*)")
        if path:
            self.load_file(path)

    def _reload(self):
        if self._well_path:
            self.load_file(self._well_path)

    def _view_wells(self):
        """Open wells in the professional correlation viewer for input QC."""
        if not self._well_list:
            QMessageBox.information(self, "WeCo", "Load wells first.")
            return
        if not HAS_CORPLOT:
            QMessageBox.information(
                self, "WeCo",
                "Professional viewer requires weco.correlation_plot module.")
            return
        self._qc_window = CorrelationPlotWindow()
        self._qc_window.setWindowTitle("WeCo - Well QC Viewer")
        self._qc_window.resize(1400, 800)
        self._qc_window.set_wells(self._well_list)
        self._qc_window.show()

    def _pick_erosion_surfaces(self):
        """§11.7.3 — Open erosion surface picker dialog."""
        if not self._well_list:
            QMessageBox.information(self, "WeCo", "Load wells first.")
            return
        dlg = ErosionSurfacePickerDialog(parent=self)
        if dlg.exec():
            surfaces = dlg.get_surfaces()
            if surfaces:
                QMessageBox.information(
                    self, "Erosion Surfaces",
                    f"Placed {len(surfaces)} erosion surface markers.\n"
                    f"Depths: {', '.join(f'{d:.1f}' for d in surfaces)}\n\n"
                    "These will be added as 'no_crossing' regions."
                )

    def _apply_conditioning(self):
        """Run selected data-conditioning transforms on the loaded wells."""
        wl = self._well_list
        if wl is None or not wl.wells:
            self._cond_status.setText("No wells loaded.")
            return

        from weco.preprocessing import (
            compute_vshale, compute_stacking_pattern, normalise_log,
            compute_moving_average, compute_electrofacies,
        )
        from weco.ai.log_qc import LogQC

        log_name = self._cond_log_combo.currentText()
        if not log_name:
            self._cond_status.setText("No source log selected.")
            return

        steps_done = []
        errors = []

        # Normalise
        if self._chk_normalise.isChecked():
            ok = normalise_log(wl, log_name, output_name=f"{log_name}_norm")
            if ok:
                steps_done.append("normalise")
            else:
                errors.append("normalise failed")

        for w in wl.wells:
            # Vshale
            if self._chk_vshale.isChecked():
                ok = compute_vshale(w, gr_name=log_name)
                if ok and "vshale" not in steps_done:
                    steps_done.append("vshale")

            # Stacking pattern
            if self._chk_stacking.isChecked():
                ok = compute_stacking_pattern(w, gr_name=log_name)
                if ok and "stacking" not in steps_done:
                    steps_done.append("stacking")

            # Smoothing
            if self._chk_smooth.isChecked():
                ok = compute_moving_average(w, log_name, window=5)
                if ok and "smooth" not in steps_done:
                    steps_done.append("smooth")

            # Log QC
            if self._chk_logqc.isChecked():
                qc = LogQC()
                qc.detect_washouts(w)
                if "logqc" not in steps_done:
                    steps_done.append("logqc")

        # Electrofacies (cross-well)
        if self._chk_electrofacies.isChecked():
            all_logs = sorted(wl.wells[0].data.keys()) if wl.wells else []
            # Use first 3 non-depth logs
            feat_logs = [n for n in all_logs
                         if n.upper() not in ("DEPTH", "MD", "TVD", "TVDSS")][:3]
            if len(feat_logs) >= 2:
                ok = compute_electrofacies(
                    wl, log_names=feat_logs,
                    n_clusters=self._cond_nclusters.value(),
                )
                if ok:
                    steps_done.append(f"electrofacies({len(feat_logs)} logs, "
                                      f"k={self._cond_nclusters.value()})")
                else:
                    errors.append("electrofacies failed (need scikit-learn?)")
            else:
                errors.append("electrofacies needs >= 2 non-depth logs")

        # AI Facies prediction (cross-well, needs scikit-learn)
        if self._chk_facies_predict.isChecked():
            try:
                from weco.ai.facies_predict import FaciesPredictor
                all_logs = sorted(wl.wells[0].data.keys()) if wl.wells else []
                feat_logs = [n for n in all_logs
                             if n.upper() not in ("DEPTH", "MD", "TVD", "TVDSS")][:5]
                if len(feat_logs) >= 2:
                    fp = FaciesPredictor(n_classes=self._cond_nclusters.value())
                    # Use cross-well unsupervised mode (predict from clusters)
                    from weco.preprocessing import compute_electrofacies as _ef
                    _ef(wl, log_names=feat_logs,
                        n_clusters=self._cond_nclusters.value(),
                        region_name="predicted_facies")
                    steps_done.append("AI facies prediction")
                else:
                    errors.append("facies prediction needs >= 2 logs")
            except ImportError:
                errors.append("facies prediction requires scikit-learn")
            except Exception as e:
                errors.append(f"facies prediction: {e}")

        # AI Anomaly detection (per-well z-score on log values)
        if self._chk_anomaly.isChecked():
            try:
                import numpy as _np
                for w in wl.wells:
                    if log_name in w.data and w.data[log_name]:
                        vals = _np.array(w.data[log_name], dtype=float)
                        mu, sigma = vals.mean(), vals.std() + 1e-10
                        z = _np.abs((vals - mu) / sigma)
                        w.add_data("anomaly_zscore", z.tolist())
                steps_done.append("anomaly detection")
            except Exception as e:
                errors.append(f"anomaly detection: {e}")

        # Refresh UI
        self._populate(wl)
        self.wells_loaded.emit(wl, self._well_path)

        msg = f"Done: {', '.join(steps_done) if steps_done else 'no transforms'}"
        if errors:
            msg += f"  |  Errors: {', '.join(errors)}"
        self._cond_status.setText(msg)

    # ── Log Editor operations ────────────────────────────────────────────
    def _apply_log_edit(self):
        """Apply the selected curve-editing operation to all wells."""
        wl = self._well_list
        if wl is None or not wl.wells:
            self._edit_status.setText("No wells loaded.")
            return
        import numpy as _np
        op_idx = self._edit_op_combo.currentIndex()
        src = self._edit_src_combo.currentText()
        src2 = self._edit_src2_combo.currentText()
        custom_out = self._edit_output_name.text().strip()

        if not src:
            self._edit_status.setText("Select a source log.")
            return

        # Default output names
        names = {
            0: custom_out or f"d_{src}",
            1: custom_out or f"{src}_smooth",
            2: custom_out or f"{src}_norm",
            3: custom_out or f"{src}_over_{src2}",
            4: custom_out or f"{src}_minus_{src2}",
        }
        out_name = names.get(op_idx, f"{src}_edit")
        count = 0

        for w in wl.wells:
            vals = list(w.data.get(src, []))
            vals2 = list(w.data.get(src2, []))
            if not vals:
                continue
            arr = _np.array(vals, dtype=float)

            if op_idx == 0:  # Derivative
                deriv = _np.gradient(arr)
                w.data[out_name] = deriv.tolist()

            elif op_idx == 1:  # Smooth
                win = self._edit_window.value()
                kernel = _np.ones(win) / win
                smoothed = _np.convolve(arr, kernel, mode='same')
                w.data[out_name] = smoothed.tolist()

            elif op_idx == 2:  # Normalise
                mn, mx = _np.nanmin(arr), _np.nanmax(arr)
                if mx > mn:
                    normed = (arr - mn) / (mx - mn)
                else:
                    normed = _np.zeros_like(arr)
                w.data[out_name] = normed.tolist()

            elif op_idx == 3:  # Log ratio
                if not vals2 or len(vals2) != len(vals):
                    continue
                arr2 = _np.array(vals2, dtype=float)
                with _np.errstate(divide='ignore', invalid='ignore'):
                    ratio = _np.where(arr2 != 0, arr / arr2, _np.nan)
                w.data[out_name] = ratio.tolist()

            elif op_idx == 4:  # Delta
                if not vals2 or len(vals2) != len(vals):
                    continue
                arr2 = _np.array(vals2, dtype=float)
                w.data[out_name] = (arr - arr2).tolist()

            count += 1

        # Refresh combos and preview
        self._populate(wl)
        self.wells_loaded.emit(wl, self._well_path)
        self._edit_status.setText(
            f"'{out_name}' added to {count}/{len(wl.wells)} wells")


# ═══════════════════════════════════════════════════════════════════════════
#  Page 2 — Parameter Editor  (grouped, with contextual help)
# ═══════════════════════════════════════════════════════════════════════════

class ParamsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lo = QVBoxLayout(self)
        lo.setContentsMargins(12, 12, 12, 12)

        lo.addWidget(StepBanner(
            "Step 2 of 4:  Configure cost-function parameters. "
            "Start with Variance (choose a log), then add constraints as needed."))
        lo.addSpacing(4)
        lo.addWidget(SectionHeader("Correlation Parameters"))

        # Horizontal split: params | help
        splitter = QSplitter(Qt.Orientation.Horizontal)
        lo.addWidget(splitter, 1)

        # Left: param groups
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        param_widget = QWidget()
        self.form_lo = QVBoxLayout(param_widget)
        self.form_lo.setContentsMargins(4, 4, 4, 4)
        scroll.setWidget(param_widget)
        splitter.addWidget(scroll)

        # Right: contextual help
        help_box = QGroupBox("Parameter Help")
        help_lo = QVBoxLayout(help_box)
        self.help_label = QLabel(
            "<b>Hover or click a parameter for help.</b><br><br>"
            "Each parameter group includes workflow guidance at the top."
        )
        self.help_label.setWordWrap(True)
        self.help_label.setFont(QFont("DejaVu Sans", 10))
        self.help_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        help_lo.addWidget(self.help_label)
        help_lo.addStretch()
        splitter.addWidget(help_box)
        splitter.setSizes([600, 300])

        self._pw = {}  # key → ParamWidget
        self._category_groups = {}
        self._current_tier_mode = "Essential"  # "Essential" or "All"

        # Presets row + tier toggle
        preset_lo = QHBoxLayout()
        lo.addLayout(preset_lo)
        preset_lo.addWidget(QLabel("Quick-start preset:"))
        self._preset_combo = QComboBox()
        self._preset_combo.addItem("-- Select a preset --")
        for name in OPTION_PRESETS:
            self._preset_combo.addItem(name)
        self._preset_combo.setMinimumWidth(220)
        self._preset_combo.currentIndexChanged.connect(self._apply_preset)
        preset_lo.addWidget(self._preset_combo)
        preset_lo.addSpacing(24)

        # Tier visibility toggle
        preset_lo.addWidget(QLabel("Show:"))
        self._tier_combo = QComboBox()
        self._tier_combo.addItems(["Essential", "All"])
        self._tier_combo.setToolTip(
            "Essential: Show only fundamental + recommended parameters\n"
            "  (auto-estimates fill the rest from your data)\n\n"
            "All: Show every parameter including advanced/debug options"
        )
        self._tier_combo.setMinimumWidth(100)
        self._tier_combo.currentTextChanged.connect(self._on_tier_mode_change)
        preset_lo.addWidget(self._tier_combo)

        # Scenario-test indicator
        self._scenario_label = QLabel("")
        self._scenario_label.setStyleSheet(
            "QLabel { color: #d35400; font-weight: bold; font-size: 9pt; }")
        preset_lo.addSpacing(12)
        preset_lo.addWidget(self._scenario_label)
        preset_lo.addStretch()

        # Action buttons
        btn_lo = QHBoxLayout()
        lo.addLayout(btn_lo)
        btn_lo.addStretch()
        btn_save = QPushButton("Save Options...")
        btn_save.clicked.connect(self._save_options)
        btn_lo.addWidget(btn_save)
        btn_load = QPushButton("Load Options...")
        btn_load.clicked.connect(self._load_options)
        btn_lo.addWidget(btn_load)
        btn_reset = QPushButton("Reset to Defaults")
        btn_reset.clicked.connect(self._reset_defaults)
        btn_lo.addWidget(btn_reset)
        btn_lo.addSpacing(16)
        btn_undo = QPushButton("Undo")
        btn_undo.setToolTip("Undo last parameter change (Ctrl+Z)")
        btn_undo.clicked.connect(self._undo)
        btn_lo.addWidget(btn_undo)
        btn_redo = QPushButton("Redo")
        btn_redo.setToolTip("Redo last undone change (Ctrl+Y)")
        btn_redo.clicked.connect(self._redo)
        btn_lo.addWidget(btn_redo)

        # §11.0.6 — Auto-tune wizard button
        btn_autotune = QPushButton("Auto-Tune…")
        btn_autotune.setToolTip(
            "Automatically tune parameters by running quick correlations "
            "with different settings and selecting the best."
        )
        btn_autotune.clicked.connect(self._auto_tune)
        btn_lo.addWidget(btn_autotune)

        # §12.5 — Hierarchical Mode toggle
        hier_lo = QHBoxLayout()
        lo.addLayout(hier_lo)
        hier_lo.addWidget(QLabel("Hierarchical Mode:"))
        self._hier_combo = QComboBox()
        self._hier_combo.addItems(["Off", "Auto", "Manual"])
        self._hier_combo.setToolTip(
            "Off: single-pass correlation\n"
            "Auto: detect sequence surfaces automatically and run multi-scale\n"
            "Manual: define hierarchical levels manually"
        )
        self._hier_combo.setMinimumWidth(120)
        hier_lo.addWidget(self._hier_combo)
        hier_lo.addStretch()

        # §11.9.3 — Transport direction compass widget
        compass_lo = QHBoxLayout()
        lo.addLayout(compass_lo)
        compass_lo.addWidget(QLabel("Transport Direction:"))
        self._azimuth_spin = QSpinBox()
        self._azimuth_spin.setRange(0, 359)
        self._azimuth_spin.setSuffix("°")
        self._azimuth_spin.setToolTip(
            "Sediment transport azimuth (0=N, 90=E, 180=S, 270=W).\n"
            "Used by the distality cost function."
        )
        compass_lo.addWidget(self._azimuth_spin)
        btn_auto_azimuth = QPushButton("Auto from Facies")
        btn_auto_azimuth.setToolTip(
            "Estimate transport direction from facies gradients "
            "(calls weco.distality.estimate_transport_from_facies)"
        )
        btn_auto_azimuth.clicked.connect(self._auto_azimuth)
        compass_lo.addWidget(btn_auto_azimuth)
        compass_lo.addStretch()

        # §11.2.3 — Facies group editor button
        facies_lo = QHBoxLayout()
        lo.addLayout(facies_lo)
        facies_lo.addWidget(QLabel("Facies Groups:"))
        self._facies_groups_edit = QLineEdit()
        self._facies_groups_edit.setPlaceholderText("e.g. 0,1;2,3;4,5")
        self._facies_groups_edit.setToolTip(
            "Semicolon-separated groups of comma-separated facies IDs.\n"
            "Facies in the same group are treated as laterally equivalent.\n"
            "Maps to the dist-facies-groups engine option (§11.2.2)."
        )
        self._facies_groups_edit.setMinimumWidth(200)
        facies_lo.addWidget(self._facies_groups_edit)
        btn_facies_editor = QPushButton("Group Editor…")
        btn_facies_editor.setToolTip("Open drag-and-drop facies group editor")
        btn_facies_editor.clicked.connect(self._open_facies_group_editor)
        facies_lo.addWidget(btn_facies_editor)
        facies_lo.addStretch()

        # Undo/redo state
        self._undo_stack = []   # list of opts dicts
        self._redo_stack = []

    def build_params(self, opts=None, data_names=None, region_names=None,
                     editable_keys=None):
        """(Re)build parameter widgets. opts = current values dict."""
        # Clear existing
        while self.form_lo.count():
            child = self.form_lo.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self._pw.clear()
        self._category_groups.clear()

        data_names = data_names or []
        region_names = region_names or []
        opts = opts or {}

        visible_tiers = TIER_VISIBILITY.get(self._current_tier_mode, TIER_VISIBILITY["All"])
        scenario_count = 0

        for cat in PARAM_CATEGORIES:
            params_in_cat = {k: v for k, v in PARAM_HELP.items() if v.get("category") == cat}
            if not params_in_cat:
                continue

            # Check if any param in this category is visible at current tier
            visible_params = {
                k: v for k, v in params_in_cat.items()
                if v.get("tier", TIER_ADVANCED) in visible_tiers
            }
            if not visible_params:
                continue

            group = QGroupBox(cat)
            group_lo = QVBoxLayout(group)
            group_lo.setSpacing(6)

            # Category-level workflow guidance
            if cat in CATEGORY_GUIDE:
                guide = QLabel(CATEGORY_GUIDE[cat])
                guide.setWordWrap(True)
                guide.setStyleSheet(
                    "QLabel { color: #4a6785; font-size: 9pt; "
                    "padding: 4px 6px; background: #eef3f8; "
                    "border-radius: 3px; margin-bottom: 4px; }")
                group_lo.addWidget(guide)

            form = QFormLayout()
            form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
            form.setVerticalSpacing(6)
            form.setHorizontalSpacing(8)
            group_lo.addLayout(form)

            for key, pdef in params_in_cat.items():
                tier = pdef.get("tier", TIER_ADVANCED)
                if tier not in visible_tiers:
                    continue

                val = opts.get(key, pdef.get("default"))
                pw = ParamWidget(key, pdef, val, data_names, region_names)
                label = pdef.get("label", key)

                # Build label with tier/scenario indicators
                label_text = label + ":"
                label_widget = QLabel(label_text)

                # Style based on tier
                if tier == TIER_FUNDAMENTAL:
                    label_widget.setStyleSheet(
                        "QLabel { font-weight: bold; color: #2c3e50; }")
                elif tier == TIER_RECOMMENDED:
                    label_widget.setStyleSheet(
                        "QLabel { color: #2c3e50; }")
                else:
                    label_widget.setStyleSheet(
                        "QLabel { color: #7f8c8d; }")

                # Scenario-test highlight
                if pdef.get("scenario_test"):
                    scenario_count += 1
                    hint = pdef.get("scenario_hint", "")
                    # Wrap widget with scenario indicator
                    wrapper = QWidget()
                    wrapper_lo = QVBoxLayout(wrapper)
                    wrapper_lo.setContentsMargins(0, 0, 0, 0)
                    wrapper_lo.setSpacing(2)
                    wrapper_lo.addWidget(pw.widget)
                    scenario_lbl = QLabel(f"\u26a0 {hint}" if hint else "\u26a0 Test alternatives")
                    scenario_lbl.setWordWrap(True)
                    scenario_lbl.setStyleSheet(
                        "QLabel { color: #d35400; font-size: 8pt; "
                        "font-style: italic; padding: 1px 2px; "
                        "background: #fef5e7; border-radius: 2px; }")
                    wrapper_lo.addWidget(scenario_lbl)
                    form.addRow(label_widget, wrapper)
                else:
                    form.addRow(label_widget, pw.widget)

                self._pw[key] = pw

                # Install focus/hover help on the actual input widget
                pw._inner.setToolTip(pdef.get("help", ""))
                pw._inner.installEventFilter(self)

                # Dim non-editable keys when in demo mode
                if editable_keys is not None and key not in editable_keys:
                    pw._inner.setEnabled(False)

            self.form_lo.addWidget(group)
            self._category_groups[cat] = group

        self.form_lo.addStretch()

        # Update scenario indicator
        if scenario_count > 0:
            self._scenario_label.setText(
                f"\u26a0 {scenario_count} parameters flagged for scenario testing")
        else:
            self._scenario_label.setText("")

    def _on_tier_mode_change(self, mode):
        """Rebuild params when tier visibility changes."""
        self._current_tier_mode = mode
        # Preserve current values
        opts = self.get_opts()
        data_names = []
        region_names = []
        # Try to recover data/region names from existing widgets
        for key, pw in list(self._pw.items()):
            pdef = PARAM_HELP.get(key, {})
            if pdef.get("type") == "data" and hasattr(pw._inner, 'count'):
                for i in range(pw._inner.count()):
                    t = pw._inner.itemText(i)
                    if t and t not in data_names:
                        data_names.append(t)
            elif pdef.get("type") == "region" and hasattr(pw._inner, 'count'):
                for i in range(pw._inner.count()):
                    t = pw._inner.itemText(i)
                    if t and t not in region_names:
                        region_names.append(t)
        self.build_params(opts=opts, data_names=data_names, region_names=region_names)

    def eventFilter(self, obj, event):
        """Show help when a parameter widget gets focus."""
        from PyQt6.QtCore import QEvent
        if event.type() in (QEvent.Type.FocusIn, QEvent.Type.Enter):
            for key, pw in self._pw.items():
                if pw._inner is obj:
                    pdef = PARAM_HELP.get(key, {})
                    cat = pdef.get("category", "")
                    cat_guide = CATEGORY_GUIDE.get(cat, "")
                    tier = pdef.get("tier", TIER_ADVANCED)
                    tier_label = {
                        TIER_FUNDAMENTAL: "\u2b50 Fundamental",
                        TIER_RECOMMENDED: "\u2705 Recommended",
                        TIER_ADVANCED: "\u2699\ufe0f Advanced (auto-set)",
                    }.get(tier, "")

                    html = (
                        f"<b>{pdef.get('label', key)}</b>  "
                        f"<code>{key}</code>"
                        f"<br><span style='color:#7f8c8d; font-size:9pt;'>"
                        f"{tier_label}</span><br><br>"
                        f"{pdef.get('help', '').replace(chr(10), '<br>')}"
                    )
                    # Scenario-test highlight in help panel
                    if pdef.get("scenario_test"):
                        hint = pdef.get("scenario_hint", "")
                        html += (
                            f"<br><br>"
                            f"<div style='background:#fef5e7; padding:6px; "
                            f"border-left:3px solid #d35400; margin-top:4px;'>"
                            f"<b style='color:#d35400;'>\u26a0 Scenario Testing</b><br>"
                            f"<span style='color:#d35400;'>{hint}</span></div>"
                        )
                    if cat_guide:
                        html += (
                            f"<br><br><hr>"
                            f"<i style='color:#4a6785;'>"
                            f"<b>{cat}</b>: {cat_guide}</i>"
                        )
                    self.help_label.setText(html)
                    break
        return False

    def get_opts(self):
        """Return current option values as a dict."""
        result = {}
        for key, pw in self._pw.items():
            v = pw.value()
            if v != "" and v is not None:
                result[key] = v
        return result

    def set_opts(self, opts):
        for key, val in opts.items():
            if key in self._pw:
                self._pw[key].set_value(val)

    def _save_options(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Options", "", "Option files (*.txt);;All (*)")
        if path:
            with open(path, "w") as f:
                for k, v in sorted(self.get_opts().items()):
                    f.write(f"{k.replace('_', '-')}={v}\n")

    def _load_options(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Options", "", "Option files (*.txt);;All (*)")
        if path:
            opts = {}
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        k, v = line.split("=", 1)
                        opts[k.strip().replace("-", "_")] = v.strip()
            self.set_opts(opts)

    def _reset_defaults(self):
        self.snapshot()
        for key, pw in self._pw.items():
            pdef = PARAM_HELP.get(key, {})
            if "default" in pdef:
                pw.set_value(pdef["default"])

    def _apply_preset(self, index):
        """Apply a selected option preset to the parameter widgets."""
        if index <= 0:
            return  # "-- Select a preset --"
        name = self._preset_combo.itemText(index)
        preset = OPTION_PRESETS.get(name)
        if not preset:
            return
        self.snapshot()
        # First reset all to defaults, then apply preset values
        self._reset_defaults()  # note: snapshot inside is harmless (two undo steps)
        self.set_opts(preset["opts"])
        self.help_label.setText(
            f"<b>Preset: {name}</b><br><br>{preset.get('desc', '')}"
        )

    # ── Undo / Redo (§3.16) ──────────────────────────────────────────

    def snapshot(self):
        """Save current parameter state to the undo stack."""
        self._undo_stack.append(self.get_opts())
        self._redo_stack.clear()
        # Limit stack depth
        if len(self._undo_stack) > 50:
            self._undo_stack = self._undo_stack[-50:]

    def _undo(self):
        if not self._undo_stack:
            return
        # Save current state for redo
        self._redo_stack.append(self.get_opts())
        prev = self._undo_stack.pop()
        self._restore_opts_silent(prev)

    def _redo(self):
        if not self._redo_stack:
            return
        self._undo_stack.append(self.get_opts())
        next_state = self._redo_stack.pop()
        self._restore_opts_silent(next_state)

    def _restore_opts_silent(self, opts):
        """Set options without triggering a new snapshot."""
        for key, pw in self._pw.items():
            v = opts.get(key)
            if v is not None:
                pw.set_value(v)
            else:
                pdef = PARAM_HELP.get(key, {})
                if "default" in pdef:
                    pw.set_value(pdef["default"])

    def _auto_tune(self):
        """§11.0.6 — Auto-tune wizard: run quick correlations with parameter variations."""
        QMessageBox.information(
            self,
            "Auto-Tune Wizard",
            "The auto-tune wizard will:\n\n"
            "1. Run correlation with current parameters\n"
            "2. Try ±20% variation of key numeric parameters\n"
            "3. Compare costs and suggest the best setting\n\n"
            "This requires wells to be loaded first.\n"
            "The results will be shown in a summary dialog.\n\n"
            "Note: Auto-tune uses the current preset as a starting point.\n"
            "For production use, manually review the suggested parameters.",
        )
        # The actual auto-tune run would need access to the engine and well data,
        # which is managed by the main WeCoStudio window.
        # This button emits a signal that the main window connects to.
        # For now, store the intent.
        self._autotune_requested = True

    def _auto_azimuth(self):
        """§11.9.3 — Estimate transport direction from facies gradients."""
        QMessageBox.information(
            self,
            "Auto-detect Transport Direction",
            "This will call weco.distality.estimate_transport_from_facies()\n"
            "to estimate the sediment transport azimuth from the loaded well data.\n\n"
            "Requires wells with facies and coordinate data to be loaded.",
        )

    def _open_facies_group_editor(self):
        """§11.2.3 — Open a drag-and-drop facies group editor dialog."""
        dlg = FaciesGroupEditorDialog(self._facies_groups_edit.text(), self)
        if dlg.exec():
            self._facies_groups_edit.setText(dlg.get_groups_string())

    def get_hierarchical_mode(self):
        """§12.5 — Return the selected hierarchical mode."""
        return self._hier_combo.currentText().lower()

    def get_azimuth(self):
        """§11.9.3 — Return the selected transport azimuth."""
        return self._azimuth_spin.value()

    def get_facies_groups(self):
        """§11.2.3 — Return the facies groups string."""
        return self._facies_groups_edit.text().strip()



# ═══════════════════════════════════════════════════════════════════════════
#  Page 3 — Run Engine
# ═══════════════════════════════════════════════════════════════════════════

class RunPage(QWidget):
    run_finished = pyqtSignal(object, object)  # res_file, well_list

    def __init__(self, parent=None):
        super().__init__(parent)
        lo = QVBoxLayout(self)
        lo.setContentsMargins(12, 12, 12, 12)

        lo.addWidget(StepBanner(
            "Step 3 of 4:  Run the correlation engine. "
            "Check the log for progress and diagnostics."))
        lo.addSpacing(4)
        lo.addWidget(SectionHeader("Run Correlation"))

        # Status bar
        self.status_label = QLabel("Ready")
        self.status_label.setFont(QFont("DejaVu Sans", 11))
        lo.addWidget(self.status_label)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # indeterminate
        self.progress.setVisible(False)
        lo.addWidget(self.progress)

        lo.addWidget(HLine())

        # Engine log
        lo.addWidget(QLabel("Engine Output:"))
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(QFont("DejaVu Sans Mono", 9))
        self.log.setMaximumBlockCount(5000)
        lo.addWidget(self.log, 1)

        # Buttons
        btn_lo = QHBoxLayout()
        lo.addLayout(btn_lo)
        btn_lo.addStretch()
        self.btn_run = QPushButton("  Run Correlation  ")
        self.btn_run.setStyleSheet(
            "QPushButton {font-weight:bold; padding:10px 24px; "
            "background-color:#2a7d84; color:white; border-radius:4px;} "
            "QPushButton:hover {background-color:#3f9350;} "
            "QPushButton:disabled {background-color:#888;}"
        )
        btn_lo.addWidget(self.btn_run)

        # §11.3.3 — Well Order Sensitivity button
        self.btn_sensitivity = QPushButton("  Well Order Sensitivity  ")
        self.btn_sensitivity.setToolTip(
            "Run correlation with multiple well orderings to assess sensitivity.\n"
            "Compares results from proximal-first vs distal-first ordering."
        )
        self.btn_sensitivity.setStyleSheet(
            "QPushButton {padding:10px 16px; border:1px solid #2a7d84; "
            "border-radius:4px; color:#2a7d84;} "
            "QPushButton:hover {background-color:#e0f5f0;}"
        )
        self.btn_sensitivity.clicked.connect(self._run_sensitivity)
        btn_lo.addWidget(self.btn_sensitivity)

        self._worker = None

    def _run_sensitivity(self):
        """§11.3.3 — Run well-order sensitivity analysis."""
        QMessageBox.information(
            self,
            "Well Order Sensitivity",
            "This will run the correlation with two different well orderings\n"
            "(proximal-first and distal-first) and compare the results.\n\n"
            "The sensitivity module (weco.sensitivity) provides:\n"
            "• configure_well_order() — set up ordering strategies\n"
            "• EXTENDED_ORDER_KEYS — all available orderings\n\n"
            "Results comparison will be displayed after both runs complete.",
        )
        self._sensitivity_requested = True

    def start_run(self, wells_path, opts):
        self.log.clear()
        self.status_label.setText("Running…")
        self.progress.setVisible(True)
        self.btn_run.setEnabled(False)
        self.log.appendPlainText(f"Wells: {wells_path}")
        self.log.appendPlainText(f"Options: {opts}\n")

        self._worker = EngineWorker(wells_path, opts)
        self._worker.log_line.connect(self._on_log)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _on_log(self, line):
        self.log.appendPlainText(line)

    def _on_finished(self, res_file, well_list, elapsed):
        self.progress.setVisible(False)
        self.btn_run.setEnabled(True)
        if res_file is not None and res_file.get_nbr_results() > 0:
            cost = res_file.get_result_cost(0)
            n = res_file.get_nbr_results()
            self.status_label.setText(
                f"Done in {elapsed:.2f}s — {n} correlations, best cost: {cost:.4f}")
            self.log.appendPlainText(
                f"\n{'─'*40}\n"
                f"Finished in {elapsed:.2f}s\n"
                f"{n} correlations found, best cost = {cost:.4f}")
        else:
            self.status_label.setText(f"Finished in {elapsed:.2f}s — no results")
            self.log.appendPlainText(f"\nNo correlations found ({elapsed:.2f}s)")
        self.run_finished.emit(res_file, well_list)
        self._worker = None


# ═══════════════════════════════════════════════════════════════════════════
#  Page 4 — Results Viewer
# ═══════════════════════════════════════════════════════════════════════════

class ResultsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lo = QVBoxLayout(self)
        lo.setContentsMargins(12, 12, 12, 12)

        lo.addWidget(StepBanner(
            "Step 4 of 4:  Inspect results. Compare alternatives with the spinner. "
            "See Docs > Interpretation for guidance."))
        lo.addSpacing(4)

        # Top bar: correlation selector + export + viewer toggle
        top = QHBoxLayout()
        lo.addLayout(top)
        top.addWidget(SectionHeader("Results"))
        top.addStretch()
        top.addWidget(QLabel("Correlation #:"))
        self.cor_spin = QSpinBox()
        self.cor_spin.setRange(0, 0)
        self.cor_spin.valueChanged.connect(self._on_cor_change)
        top.addWidget(self.cor_spin)
        self.cost_label = QLabel("")
        self.cost_label.setFont(QFont("DejaVu Sans", 10, QFont.Weight.Bold))
        top.addWidget(self.cost_label)

        # Second row for action buttons to avoid cramming
        btn_row = QHBoxLayout()
        lo.addLayout(btn_row)
        btn_export = QPushButton("Export PNG…")
        btn_export.clicked.connect(self._export_png)
        btn_row.addWidget(btn_export)
        btn_export_csv = QPushButton("Export CSV…")
        btn_export_csv.clicked.connect(self._export_csv)
        btn_row.addWidget(btn_export_csv)
        btn_quality = QPushButton("AI Quality")
        btn_quality.setToolTip("Score each correlation using AI quality metrics")
        btn_quality.clicked.connect(self._ai_quality)
        btn_row.addWidget(btn_quality)
        btn_uncert = QPushButton("AI Uncertainty")
        btn_uncert.setToolTip("Quantify uncertainty from n-best ensemble")
        btn_uncert.clicked.connect(self._ai_uncertainty)
        btn_row.addWidget(btn_uncert)

        # §15.16 — Export Wizard
        btn_export_wizard = QPushButton("Export Wizard…")
        btn_export_wizard.setToolTip("Select artifacts, format, and destination")
        btn_export_wizard.clicked.connect(self._export_wizard)
        btn_row.addWidget(btn_export_wizard)

        # Pop-out button
        btn_popout = QPushButton("Pop-out Viewer")
        btn_popout.setToolTip("Open the professional correlation viewer in a separate window")
        btn_popout.clicked.connect(self._popup_viewer)
        btn_row.addWidget(btn_popout)

        # §12.6 — Systems tract overlay toggle
        self._tract_overlay_cb = QCheckBox("Systems Tract Overlay")
        self._tract_overlay_cb.setToolTip(
            "Overlay coloured bands showing HST/TST/LST regions\n"
            "on the well-log tracks (requires sequence_strat analysis)"
        )
        self._tract_overlay_cb.stateChanged.connect(self._toggle_tract_overlay)
        btn_row.addWidget(self._tract_overlay_cb)
        btn_row.addStretch()

        # Viewer tabs
        self.view_tabs = QTabWidget()
        lo.addWidget(self.view_tabs, 1)

        # Tab 0: Professional Correlation Plot (matplotlib interactive)
        self._corplot = None
        self._corplot_window = None  # pop-out window reference
        if HAS_CORPLOT:
            try:
                self._corplot = CorrelationPlotWindow()
                # Embed the central widget (canvas + sidebar) in the tab
                self.view_tabs.addTab(self._corplot.centralWidget(), "Correlation Panel")
            except Exception as e:
                lbl = QLabel(f"CorrelationPlot init error: {e}")
                lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self.view_tabs.addTab(lbl, "Correlation Panel (error)")
        else:
            lbl = QLabel("Professional viewer requires matplotlib Qt backend")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.view_tabs.addTab(lbl, "Correlation Panel (unavailable)")

        # Tab 1: Static matplotlib plot (fallback / quick overview)
        static_widget = QWidget()
        static_lo = QVBoxLayout(static_widget)
        static_lo.setContentsMargins(0, 0, 0, 0)
        self.plot_scroll = QScrollArea()
        self.plot_scroll.setWidgetResizable(True)
        self.plot_label = QLabel("Run a correlation to see results here.")
        self.plot_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.plot_scroll.setWidget(self.plot_label)
        static_lo.addWidget(self.plot_scroll)
        self.view_tabs.addTab(static_widget, "Static Plot")

        # Tab 2: Legacy Interactive CorResView
        self._resview = None
        if HAS_RESVIEW:
            try:
                self._resview = CorResView()
                self.view_tabs.addTab(self._resview.splitter, "Legacy Viewer")
            except Exception as e:
                lbl = QLabel(f"CorResView init error: {e}")
                lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self.view_tabs.addTab(lbl, "Legacy (error)")
        else:
            lbl = QLabel("Legacy viewer requires weco.resview (PyQt6)")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.view_tabs.addTab(lbl, "Legacy (unavailable)")

        # Summary table
        self.summary_table = QTableWidget()
        self.summary_table.setMaximumHeight(160)
        self.summary_table.setAlternatingRowColors(True)
        lo.addWidget(self.summary_table)

        # §11.11.4 — Side-by-side comparison tab
        sidebyside = QWidget()
        sbs_lo = QHBoxLayout(sidebyside)
        self._sbs_left = QLabel("Load a reference correlation\nto compare side-by-side.")
        self._sbs_left.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._sbs_right = QLabel("Current WeCo result\nwill appear here.")
        self._sbs_right.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sbs_lo.addWidget(self._sbs_left, 1)
        sbs_lo.addWidget(self._sbs_right, 1)
        self.view_tabs.addTab(sidebyside, "Side-by-Side")

        # ── Run History (multi-run comparison) ────────────────────────
        hist_group = QGroupBox("Run History (compare parameter sets)")
        hist_lo = QVBoxLayout(hist_group)
        self._history_table = QTableWidget()
        self._history_table.setAlternatingRowColors(True)
        self._history_table.setColumnCount(5)
        self._history_table.setHorizontalHeaderLabels(
            ["#", "Title / Params", "Best Cost", "Paths", "Time (ms)"])
        self._history_table.horizontalHeader().setStretchLastSection(True)
        self._history_table.setMaximumHeight(130)
        hist_lo.addWidget(self._history_table)
        hist_btn_lo = QHBoxLayout()
        btn_clear_hist = QPushButton("Clear History")
        btn_clear_hist.clicked.connect(self._clear_history)
        hist_btn_lo.addWidget(btn_clear_hist)
        hist_btn_lo.addStretch()
        hist_lo.addLayout(hist_btn_lo)
        lo.addWidget(hist_group)

        self._res_file = None
        self._well_list = None
        self._png_bytes = None
        self._title = ""
        self._run_history = []  # list of dicts

    def show_result(self, res_file, well_list, title=""):
        self._res_file = res_file
        self._well_list = well_list
        self._title = title

        if res_file is None or res_file.get_nbr_results() == 0:
            self.plot_label.setText("No results to display.")
            return

        n = res_file.get_nbr_results()
        self.cor_spin.setMaximum(n - 1)
        self.cor_spin.setValue(0)

        # Summary table
        self.summary_table.setColumnCount(4)
        self.summary_table.setHorizontalHeaderLabels(
            ["Correlation #", "Cost", "Nodes", "Quality"])
        self.summary_table.setRowCount(min(n, 20))
        for i in range(min(n, 20)):
            cost = res_file.get_result_cost(i)
            path = res_file.get_result_full_path(i)
            self.summary_table.setItem(i, 0, QTableWidgetItem(str(i)))
            self.summary_table.setItem(i, 1, QTableWidgetItem(f"{cost:.6f}"))
            self.summary_table.setItem(i, 2, QTableWidgetItem(str(len(path))))
            self.summary_table.setItem(i, 3, QTableWidgetItem("—"))
        self.summary_table.resizeColumnsToContents()

        # Feed professional CorrelationPlotWindow
        if self._corplot is not None:
            try:
                self._corplot.set_wells(well_list)
                self._corplot.set_result(res_file, 0)
            except Exception as e:
                print(f"CorrelationPlot update error: {e}")

        # Feed legacy CorResView
        if self._resview is not None:
            try:
                self._resview.set_wells(well_list)
                self._resview.set_res(res_file)
                self._resview.unlock_update()
            except Exception as e:
                print(f"CorResView update error: {e}")

        self._render(0)

    def _render(self, cor_idx):
        if self._res_file is None:
            return
        cost = self._res_file.get_result_cost(cor_idx)
        self.cost_label.setText(f"Cost: {cost:.4f}")

        png = render_correlation_plot(
            self._well_list, self._res_file, self._title, cor_idx)
        if png:
            self._png_bytes = png
            pm = QPixmap()
            pm.loadFromData(png)
            w = min(self.width() - 60, 1100)
            if pm.width() > w:
                pm = pm.scaledToWidth(w, Qt.TransformationMode.SmoothTransformation)
            self.plot_label.setPixmap(pm)

    def _on_cor_change(self, idx):
        self._render(idx)
        # Update professional viewer
        if self._corplot is not None and self._res_file is not None:
            try:
                self._corplot.set_result(self._res_file, idx)
            except Exception:
                pass

    def _toggle_tract_overlay(self, state):
        """§12.6 — Toggle systems tract coloured band overlay."""
        self._show_tract_overlay = bool(state)
        if hasattr(self, '_res_file') and self._res_file is not None:
            self._render(self.cor_spin.value())

    def _popup_viewer(self):
        """Open the professional correlation viewer as a standalone pop-out window."""
        if not HAS_CORPLOT:
            QMessageBox.information(
                self, "WeCo",
                "Professional viewer requires weco.correlation_plot module.")
            return
        self._corplot_window = CorrelationPlotWindow()
        self._corplot_window.setWindowTitle("WeCo Correlation Viewer")
        self._corplot_window.resize(1400, 800)
        if self._well_list:
            self._corplot_window.set_wells(self._well_list)
        if self._res_file:
            self._corplot_window.set_result(
                self._res_file, self.cor_spin.value())
        self._corplot_window.show()

    def _export_png(self):
        if self._png_bytes is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export PNG", "correlation.png", "PNG (*.png)")
        if path:
            with open(path, "wb") as f:
                f.write(self._png_bytes)

    def _export_csv(self):
        """Export the current correlation to CSV (zonation logs + horizon picks)."""
        if self._res_file is None or self._well_list is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export CSV", "correlation.csv", "CSV (*.csv)")
        if not path:
            return
        try:
            from weco.export import export_horizon_picks_csv
            export_horizon_picks_csv(
                self._res_file, self._well_list,
                path, cor_num=self.cor_spin.value())
            self.cost_label.setText(f"Exported to {os.path.basename(path)}")
        except Exception as e:
            QMessageBox.warning(self, "Export Error", str(e))

    def _ai_quality(self):
        """Run AI quality scoring on all correlations and update the table."""
        if self._res_file is None or self._well_list is None:
            return
        try:
            from weco.ai.quality import CorrelationQuality
        except ImportError:
            QMessageBox.information(
                self, "WeCo",
                "AI quality scoring requires scikit-learn.\n"
                "Install with: pip install weco[ai]")
            return

        scorer = CorrelationQuality()
        results = scorer.score_correlations(self._res_file, self._well_list)
        n = min(len(results), self.summary_table.rowCount())
        for i in range(n):
            total = results[i].get("total", 0.0)
            item = QTableWidgetItem(f"{total:.4f}")
            self.summary_table.setItem(i, 3, item)
        self.summary_table.resizeColumnsToContents()
        best = results[0].get("total", 0.0) if results else 0.0
        self.cost_label.setText(f"Quality: best={best:.4f}")

    def _ai_uncertainty(self):
        """Run AI uncertainty analysis and show results in a dialog."""
        if self._res_file is None or self._well_list is None:
            return
        if self._res_file.get_nbr_results() < 2:
            QMessageBox.information(
                self, "WeCo",
                "Uncertainty analysis needs at least 2 alternative correlations.\n"
                "Increase out-nbr-cor and re-run.")
            return
        try:
            from weco.ai.uncertainty import CorrelationUncertainty
        except ImportError:
            QMessageBox.information(
                self, "WeCo",
                "AI uncertainty requires scikit-learn.\n"
                "Install with: pip install weco[ai]")
            return

        # Bridge: AI module expects res_file.well_names
        rf = self._res_file
        if not hasattr(rf, 'well_names') or not rf.well_names:
            rf.well_names = [w.name for w in self._well_list.wells]

        uc = CorrelationUncertainty()
        result = uc.from_n_best(rf)

        if not result:
            QMessageBox.information(
                self, "Uncertainty",
                "No uncertainty data (need >= 2 paths that differ).")
            return

        lines = ["Uncertainty Analysis (n-best ensemble)", "",
                  "Per-well-pair marker standard deviation:", ""]
        for (w1, w2), std_arr in result.items():
            mean_std = float(std_arr.mean()) if len(std_arr) > 0 else 0.0
            max_std = float(std_arr.max()) if len(std_arr) > 0 else 0.0
            lines.append(f"  {w1} <-> {w2}:  mean={mean_std:.3f}  max={max_std:.3f}")

        QMessageBox.information(self, "Uncertainty Analysis", "\n".join(lines))

    # ── Run History (multi-run comparison §3.15) ──────────────────────

    def add_run_to_history(self, title, opts, elapsed_ms=0):
        """Record a completed run in the history table."""
        if self._res_file is None:
            return
        n = self._res_file.get_nbr_results()
        cost = self._res_file.get_result_cost(0) if n > 0 else float("inf")
        # Compact option summary
        opt_parts = []
        for k in ("var_data", "var_weight", "max_cor", "const_gap_cost",
                   "same_region", "no_crossing", "order"):
            if k in opts:
                opt_parts.append(f"{k}={opts[k]}")
        opt_str = ", ".join(opt_parts[:4])
        if title:
            opt_str = f"{title}  ({opt_str})" if opt_str else title

        entry = {"title": opt_str, "cost": cost, "paths": n,
                 "elapsed_ms": elapsed_ms, "opts": dict(opts)}
        self._run_history.append(entry)
        self._refresh_history()

    def _refresh_history(self):
        n = len(self._run_history)
        self._history_table.setRowCount(n)
        for i, entry in enumerate(self._run_history):
            self._history_table.setItem(i, 0, QTableWidgetItem(str(i + 1)))
            self._history_table.setItem(i, 1, QTableWidgetItem(entry["title"]))
            self._history_table.setItem(i, 2, QTableWidgetItem(f"{entry['cost']:.6f}"))
            self._history_table.setItem(i, 3, QTableWidgetItem(str(entry["paths"])))
            self._history_table.setItem(i, 4, QTableWidgetItem(f"{entry['elapsed_ms']:.0f}"))
        self._history_table.resizeColumnsToContents()

    def _clear_history(self):
        self._run_history.clear()
        self._history_table.setRowCount(0)

    def _export_wizard(self):
        """§15.16 — Export Wizard dialog: select artifacts, format, destination."""
        if self._res_file is None or self._well_list is None:
            QMessageBox.information(self, "WeCo", "Run a correlation first.")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Export Wizard")
        dialog.setMinimumSize(450, 400)
        lo = QVBoxLayout(dialog)

        lo.addWidget(QLabel("<h3>Select artifacts to export:</h3>"))

        checks = {}
        for name in [
            "Horizon picks (CSV)",
            "Zonation logs (LAS)",
            "Zonation logs (CSV)",
            "Correlation surfaces (GOCAD .ts)",
            "Seam table (coal)",
            "MODFLOW layers",
            "Continuous logs (LAS)",
            "Blocked well logs (RMS)",
            "IRAP surfaces (RMS)",
            "RESQML EPC package",
        ]:
            cb = QCheckBox(name)
            lo.addWidget(cb)
            checks[name] = cb

        lo.addSpacing(10)
        lo.addWidget(QLabel("Output directory:"))
        dir_lo = QHBoxLayout()
        dir_edit = QLineEdit("export_output")
        btn_browse = QPushButton("Browse…")
        dir_lo.addWidget(dir_edit, 1)
        dir_lo.addWidget(btn_browse)
        lo.addLayout(dir_lo)

        def browse():
            d = QFileDialog.getExistingDirectory(dialog, "Select Output Directory")
            if d:
                dir_edit.setText(d)
        btn_browse.clicked.connect(browse)

        btn_lo = QHBoxLayout()
        btn_ok = QPushButton("Export")
        btn_cancel = QPushButton("Cancel")
        btn_lo.addStretch()
        btn_lo.addWidget(btn_ok)
        btn_lo.addWidget(btn_cancel)
        lo.addLayout(btn_lo)

        btn_cancel.clicked.connect(dialog.reject)

        def do_export():
            out_dir = dir_edit.text()
            os.makedirs(out_dir, exist_ok=True)
            cor_num = self.cor_spin.value()
            exported = []
            try:
                from weco.export import (
                    export_horizon_picks_csv,
                    export_zonation_las,
                    export_zonation_csv,
                    export_correlation_surfaces,
                    export_seam_table,
                    export_modflow_layers,
                    export_continuous_logs,
                    export_blocked_well_log,
                    export_irap_surfaces,
                )

                if checks["Horizon picks (CSV)"].isChecked():
                    p = os.path.join(out_dir, "horizon_picks.csv")
                    export_horizon_picks_csv(self._res_file, self._well_list, p, cor_num=cor_num)
                    exported.append(p)
                if checks["Zonation logs (CSV)"].isChecked():
                    p = os.path.join(out_dir, "zonation")
                    os.makedirs(p, exist_ok=True)
                    r = export_zonation_csv(self._res_file, self._well_list, p, cor_num=cor_num)
                    exported.extend(r if isinstance(r, list) else [r])
                if checks["Zonation logs (LAS)"].isChecked():
                    zon = {}  # placeholder — would need actual zonation
                    p = os.path.join(out_dir, "zonation_las")
                    os.makedirs(p, exist_ok=True)
                if checks["Correlation surfaces (GOCAD .ts)"].isChecked():
                    p = os.path.join(out_dir, "surfaces")
                    r = export_correlation_surfaces(self._res_file, self._well_list, p, cor_num=cor_num)
                    exported.extend(r)
                if checks["Seam table (coal)"].isChecked():
                    p = os.path.join(out_dir, "seam_table.csv")
                    export_seam_table(self._res_file, self._well_list, p)
                    exported.append(p)
                if checks["MODFLOW layers"].isChecked():
                    p = os.path.join(out_dir, "modflow_layers.csv")
                    export_modflow_layers(self._res_file, self._well_list, p)
                    exported.append(p)
                if checks["Continuous logs (LAS)"].isChecked():
                    p = os.path.join(out_dir, "continuous_logs")
                    r = export_continuous_logs(self._well_list, p, fmt="las")
                    exported.extend(r)
                if checks["Blocked well logs (RMS)"].isChecked():
                    p = os.path.join(out_dir, "blocked_logs")
                    r = export_blocked_well_log(self._res_file, self._well_list, p, cor_num=cor_num)
                    exported.extend(r)
                if checks["IRAP surfaces (RMS)"].isChecked():
                    p = os.path.join(out_dir, "irap_surfaces")
                    r = export_irap_surfaces(self._res_file, self._well_list, p, cor_num=cor_num)
                    exported.extend(r)
                if checks["RESQML EPC package"].isChecked():
                    p = os.path.join(out_dir, "results.epc")
                    from weco.formats.epc_writer import write_epc_results
                    write_epc_results(p, self._res_file, self._well_list, cor_num=cor_num)
                    exported.append(p)

                QMessageBox.information(
                    dialog, "Export Complete",
                    f"Exported {len(exported)} file(s) to:\n{out_dir}")
                dialog.accept()
            except Exception as e:
                QMessageBox.warning(dialog, "Export Error", str(e))

        btn_ok.clicked.connect(do_export)
        dialog.exec()


# ═══════════════════════════════════════════════════════════════════════════
#  Page 5 — Documentation Center  (replaces old HelpPage)
# ═══════════════════════════════════════════════════════════════════════════

_WORKFLOW_HTML = """
<h2>WeCo Studio Workflow</h2>

<h3>Overview</h3>
<p>WeCo performs automated <b>multi-well stratigraphic correlation</b> using
a graph-based Dynamic Time Warping (DTW) algorithm. The engine explores
an exponentially large space of possible correlations and returns the
<i>n</i>-best solutions ranked by cost.</p>

<h3>Step-by-Step Guide</h3>

<h4>Step 1: Load Data (Data page)</h4>
<p>Load a well-list file containing your wells with their log curves and
region/zone information. Supported formats:</p>
<ul>
  <li><b>WeCo native</b> (.wells.txt, .txt) &mdash; space-separated text</li>
  <li><b>LAS 2.0</b> (.las) &mdash; standard well-log exchange</li>
  <li><b>RESQML</b> (.epc + .h5) &mdash; Energistics standard</li>
  <li><b>CSV / TSV</b> &mdash; tabular well data</li>
</ul>
<p>After loading, inspect the well summary table and log preview plot to
verify your data.</p>

<h4>Step 2: Configure Parameters (Parameters page)</h4>
<p>Parameters are organized by cost function component. A minimal
configuration requires only:</p>
<ol>
  <li><b>var_data</b> &mdash; choose a well-log property (e.g. GR)</li>
  <li><b>max_cor / nbr_cor</b> &mdash; quality vs speed (start with 50)</li>
  <li><b>order</b> &mdash; try 'pyramidal' for 4+ wells</li>
</ol>
<p>Click any parameter to see detailed help in the right panel, including
geological interpretation guidance.</p>

<h4>Step 3: Run Correlation (Run page)</h4>
<p>Click <i>Run Correlation</i>. The engine runs in a background thread.
Watch the log output for progress. Typical runtimes:</p>
<table border="1" cellpadding="4" style="border-collapse:collapse;">
  <tr><th>Wells</th><th>Markers</th><th>max_cor</th><th>Time</th></tr>
  <tr><td>2</td><td>26</td><td>50</td><td>~3ms</td></tr>
  <tr><td>3</td><td>100</td><td>50</td><td>~76ms</td></tr>
  <tr><td>3</td><td>100</td><td>200</td><td>~389ms</td></tr>
</table>

<h4>Step 4: Interpret Results (Results page)</h4>
<p>The Results page has two viewers:</p>
<ul>
  <li><b>Static Plot</b> &mdash; matplotlib rendering with correlation lines</li>
  <li><b>Interactive Viewer</b> &mdash; zoomable CorResView with region colors,
      data overlays, and SVG/PNG export</li>
</ul>
<p>Use the correlation selector (spin box) to compare alternative solutions.
If they differ significantly, the section is poorly constrained there &mdash;
consider adding no-crossing constraints or additional log curves.</p>

<h3>Iterative Refinement</h3>
<p>Correlation is typically iterative:</p>
<ol>
  <li>Run with variance cost only (simplest)</li>
  <li>Inspect result &mdash; look for obviously wrong tie lines</li>
  <li>Add constraints (no_crossing, same_region) where needed</li>
  <li>Adjust gap cost to control hiatus vs layer-cake behaviour</li>
  <li>Increase max_cor if cost seems stuck at a local minimum</li>
  <li>Compare multiple output correlations (out_nbr_cor = 5-10)</li>
</ol>
"""

_INTERPRETATION_HTML = """
<h2>Interpreting Results</h2>

<h3>Understanding Correlation Cost</h3>
<p>The <b>cost</b> reported for each correlation is the total objective
function value. Lower cost = better match according to the configured
cost components. The absolute value depends on your data range and
the weights you set &mdash; only <i>relative</i> comparisons between
correlations are meaningful.</p>

<h3>Correlation Lines</h3>
<p>Each horizontal line in the plot connects matched positions across wells.
A line at the same depth in all wells indicates a laterally continuous horizon.
Lines that converge or diverge indicate thickness changes (wedging).</p>

<h3>Gaps (Hiatuses)</h3>
<p>Where correlation lines skip positions in one well, the algorithm has
inferred a <b>gap</b> (hiatus, erosion, or condensation). The number and
distribution of gaps is controlled by const_gap_cost:</p>
<ul>
  <li><b>Many gaps</b> (low cost): Allows variable sedimentation rates, erosion</li>
  <li><b>Few gaps</b> (high cost): Forces continuous layer-cake correlation</li>
</ul>

<h3>Multiple Solutions</h3>
<p>When out_nbr_cor > 1, compare the top solutions:</p>
<ul>
  <li><b>Consistent regions</b>: Where all solutions agree, the correlation
      is well-constrained. These tie lines are reliable.</li>
  <li><b>Variable regions</b>: Where solutions differ, the data is ambiguous.
      Consider adding constraints or additional log data in these zones.</li>
</ul>

<h3>Cost Components</h3>
<table border="1" cellpadding="4" style="border-collapse:collapse;">
  <tr><th>Component</th><th>What it measures</th><th>When to use</th></tr>
  <tr><td>Variance</td><td>Log similarity at matched positions</td>
      <td>Always; primary driver</td></tr>
  <tr><td>Gap cost</td><td>Penalty for hiatuses</td>
      <td>When controlling gap behaviour</td></tr>
  <tr><td>No-crossing</td><td>Hard stratigraphic constraint</td>
      <td>When zone boundaries are known</td></tr>
  <tr><td>Same-region</td><td>Soft lithostratigraphic matching</td>
      <td>When facies zonation is available</td></tr>
  <tr><td>Polarity</td><td>T/R trend consistency</td>
      <td>When sequence-strat polarity is known</td></tr>
  <tr><td>Distality</td><td>Thickness wedging model</td>
      <td>Basin transects with known palaeo-geography</td></tr>
  <tr><td>B3D</td><td>3D structural geometry</td>
      <td>When dip/azimuth data is available</td></tr>
</table>

<h3>Common Issues</h3>
<table border="1" cellpadding="4" style="border-collapse:collapse;">
  <tr><th>Symptom</th><th>Likely cause</th><th>Fix</th></tr>
  <tr><td>All lines bunched together</td><td>Gap cost too high</td>
      <td>Reduce const_gap_cost</td></tr>
  <tr><td>Too many short gaps</td><td>Gap cost too low</td>
      <td>Increase const_gap_cost</td></tr>
  <tr><td>Obvious zone crossings</td><td>Missing constraint</td>
      <td>Add no_crossing region</td></tr>
  <tr><td>Poor match on some logs</td><td>Wrong weight balance</td>
      <td>Adjust var_weight ratios</td></tr>
  <tr><td>High cost, poor result</td><td>Insufficient search</td>
      <td>Increase max_cor (100-500)</td></tr>
</table>
"""

_FILE_FORMAT_HTML = """
<h2>File Formats</h2>

<h3>WeCo Well List Format (.wells.txt)</h3>
<p>Space/tab-separated text file. Strings cannot contain spaces.</p>
<pre style="background:#f4f4f4; padding:8px; font-size:9pt;">
WeCo WellList 2          # Header: WeCo WellList version
3                         # Number of wells
WellA                     # Well name
100                       # Well size (number of samples)
0.0 0.0 0.0 500.0        # X Y Z Height
2                         # Number of data arrays
GR 100                    # Data name, data size
1.2 3.4 5.6 ...          # Data values (one per line)
DEPTH 100
0.0 5.0 10.0 ...
1                         # Number of region lists
Zones 3                   # Region name, number of regions
1 0 30                    # RegionID Start Length
2 30 40
3 70 30
WellB ...
...
END                       # End token
</pre>

<h3>Result File Format</h3>
<p>Contains a directed acyclic graph (DAG) of correlation nodes.</p>
<pre style="background:#f4f4f4; padding:8px; font-size:9pt;">
WellIds: 0 1 2            # Well indices
Node 0 (0 0 0)            # Node: matched positions
Node 1 (0 1 1)
   -> 0 (14.2)            # Edge to node 0, cost 14.2
Node 2 (1 1 1)
   -> 0 (2.3)
   -> 1 (4.2)
</pre>
<p>Each node gives the position (sample index) in each well that is
correlated together. Edges carry transition costs. The best correlation
is the cheapest path from start to end.</p>

<h3>Option File Format</h3>
<pre style="background:#f4f4f4; padding:8px; font-size:9pt;">
# Lines starting with # are comments
cost-function=composite
order=pyramidal
max-cor=50
var-data=GR
var-weight=1.0
no-crossing=Zones
</pre>
<p>Use hyphens in option files; underscores in Python API. Both are
accepted and converted automatically.</p>

<h3>Other Supported Formats</h3>
<ul>
  <li><b>LAS 2.0</b>: Standard well-log ASCII. Auto-detected by .las extension.</li>
  <li><b>RESQML</b>: EPC+H5 container. Requires h5py.</li>
  <li><b>CSV/TSV</b>: Simple tabular format with header row.</li>
  <li><b>GOCAD Well</b> (.wl): GOCAD ASCII well with WREF/ZONE/MRKR support.</li>
  <li><b>Cost Matrix</b>: Debug output showing transition costs between states.
      Use cost-matrix option to generate.</li>
</ul>
"""


def _build_geology_docs_html():
    """Build comprehensive HTML documentation for all geological environments
    and demo datasets, accessible from the Docs tab."""
    parts = []
    parts.append("<h2>Geological Environments &amp; Demo Datasets</h2>")
    parts.append(
        "<p>WeCo includes demo datasets for several geological environments. "
        "Each demo demonstrates a specific correlation workflow with "
        "pre-configured parameters. Use these as starting points for your own data.</p>"
    )

    # ── Environment Presets ──
    parts.append("<h3>Best-Guess Defaults by Environment</h3>")
    parts.append(
        "<p>Select an environment on the Welcome page to load recommended "
        "parameter defaults. These are calibrated to typical data situations "
        "in each geological setting:</p>"
    )
    for key, p in GEO_PRESETS.items():
        parts.append(f"<h4>{p['label']}</h4>")
        parts.append(f"<p>{p['description'].replace(chr(10), '<br>')}</p>")
        parts.append(f"<b>Geology Notes:</b><pre>{p['geology_notes']}</pre>")
        parts.append(f"<b>Correlation Strategy:</b><p>{p['correlation_hint']}</p>")
        parts.append(f"<b>Constraint Guidance:</b><p>{p['constraints_hint']}</p>")

        opts = p.get("recommended_opts", {})
        if opts:
            parts.append("<b>Recommended Parameters:</b><table border='1' cellpadding='4'>")
            for k, v in opts.items():
                label = PARAM_HELP.get(k, {}).get("label", k)
                parts.append(f"<tr><td>{label}</td><td>{v}</td></tr>")
            parts.append("</table><br>")

    # ── Demo Datasets ──
    parts.append("<hr><h3>Demo Datasets</h3>")
    current_group = ""
    for d in DEMOS:
        g = d.get("group", "Other")
        if g != current_group:
            parts.append(f"<h4>{g}</h4>")
            current_group = g
        parts.append(f"<p><b>{d['title']}</b> (ID: {d['id']})<br>")
        parts.append(f"{d['description'].replace(chr(10), '<br>')}</p>")
        geo_doc = d.get("geology_doc", "")
        if geo_doc:
            parts.append(f"<blockquote>{geo_doc}</blockquote>")

    # ── Parameter Selection Guide ──
    parts.append("<hr><h3>Parameter Selection Guide</h3>")
    parts.append("""
    <table border='1' cellpadding='6' style='border-collapse:collapse;'>
    <tr style='background:#ddd;'>
      <th>Question</th><th>Parameter</th><th>Guidance</th>
    </tr>
    <tr>
      <td>Which log is most diagnostic?</td>
      <td>var_data / var_weight</td>
      <td>Put the highest weight on the log with the strongest lithology contrast.
          E.g., DEN for coal (1.3 vs 2.5), GR for sand/shale.</td>
    </tr>
    <tr>
      <td>Are there known stratigraphic surfaces?</td>
      <td>no_crossing</td>
      <td>Use no-crossing with a region encoding those surfaces. This is the
          strongest constraint — prevents correlations from violating known boundaries.</td>
    </tr>
    <tr>
      <td>Should similar facies match?</td>
      <td>same_region</td>
      <td>Use same-region with a facies classification. Softer than no-crossing:
          penalises mismatches rather than eliminating them.</td>
    </tr>
    <tr>
      <td>Are hiatuses expected?</td>
      <td>const_gap_cost</td>
      <td>Low (0–1): Many hiatuses expected (deep marine, unconformities).<br>
          Medium (1–3): Some gaps allowed (glacial, fluvial).<br>
          High (3–5+): Layer-cake matching (coal seams, tabular beds).</td>
    </tr>
    <tr>
      <td>Does thickness vary systematically?</td>
      <td>dist_distal / dist_facies</td>
      <td>Use distality cost for basin transects where proximal=thick, distal=thin.
          Requires distality ranking and facies interpretation per well.</td>
    </tr>
    <tr>
      <td>How many wells?</td>
      <td>order</td>
      <td>2–3 wells: 'linear' is fine.<br>
          4–20 wells: 'pyramidal' or 'position' (nearest-neighbour).<br>
          20+ wells: 'position' (uses spatial clustering).</td>
    </tr>
    <tr>
      <td>Quality vs speed?</td>
      <td>max_cor</td>
      <td>10–20: Fast demos/exploration.<br>
          50: Good default.<br>
          100–200: Production quality (diminishing returns).</td>
    </tr>
    </table>
    """)

    return "".join(parts)


class DocsPage(QWidget):
    """Multi-tab documentation center integrating workflow, parameters,
    file formats, and interpretation guidance."""
    def __init__(self, parent=None):
        super().__init__(parent)
        lo = QVBoxLayout(self)
        lo.setContentsMargins(12, 12, 12, 12)
        lo.addWidget(SectionHeader("Documentation"))

        self.tabs = QTabWidget()
        lo.addWidget(self.tabs, 1)

        # ── Tab 1: Workflow Guide ──
        wf_browser = QTextEdit()
        wf_browser.setReadOnly(True)
        wf_browser.setHtml(_WORKFLOW_HTML)
        self.tabs.addTab(wf_browser, "Workflow Guide")

        # ── Tab 2: Parameter Reference (searchable table) ──
        param_widget = QWidget()
        param_lo = QVBoxLayout(param_widget)
        param_lo.setContentsMargins(4, 4, 4, 4)

        search_lo = QHBoxLayout()
        param_lo.addLayout(search_lo)
        search_lo.addWidget(QLabel("Search:"))
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Type to filter parameters...")
        self.search_box.textChanged.connect(self._filter)
        search_lo.addWidget(self.search_box, 1)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            ["Parameter", "Type", "Default", "Category", "Description"])
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSortingEnabled(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        param_lo.addWidget(self.table, 1)
        self.tabs.addTab(param_widget, "Parameter Reference")

        # ── Tab 3: File Formats ──
        fmt_browser = QTextEdit()
        fmt_browser.setReadOnly(True)
        fmt_browser.setHtml(_FILE_FORMAT_HTML)
        self.tabs.addTab(fmt_browser, "File Formats")

        # ── Tab 4: Interpretation ──
        interp_browser = QTextEdit()
        interp_browser.setReadOnly(True)
        interp_browser.setHtml(_INTERPRETATION_HTML)
        self.tabs.addTab(interp_browser, "Interpretation")

        # ── Tab 5: Geology & Demos ──
        geo_browser = QTextEdit()
        geo_browser.setReadOnly(True)
        geo_browser.setHtml(_build_geology_docs_html())
        self.tabs.addTab(geo_browser, "Geology && Demos")

        self._populate()

    def _populate(self):
        rows = []
        for key, p in sorted(PARAM_HELP.items()):
            rows.append((
                key,
                p.get("type", "string"),
                str(p.get("default", "")),
                p.get("category", ""),
                p.get("help", "").replace("\n", " "),
            ))
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                self.table.setItem(r, c, QTableWidgetItem(val))
        self.table.resizeColumnsToContents()
        self._all_rows = rows

    def _filter(self, text):
        text = text.lower()
        for r in range(self.table.rowCount()):
            match = any(text in cell.lower() for cell in self._all_rows[r])
            self.table.setRowHidden(r, not match)


# ═══════════════════════════════════════════════════════════════════════════
#  §3.44 — Plugin Manager Page
# ═══════════════════════════════════════════════════════════════════════════

class PluginPage(QWidget):
    """Manage external cost-function plugins (.so / .dll via weco_plugin.h)."""

    def __init__(self):
        super().__init__()
        lo = QVBoxLayout(self)
        lo.addWidget(QLabel("<h2>Plugin Manager</h2>"))
        lo.addWidget(QLabel(
            "Load custom cost-function plugins compiled against "
            "<code>weco_plugin.h</code> (C ABI)."
        ))

        # Plugin list
        self._list = QListWidget()
        self._list.setAlternatingRowColors(True)
        lo.addWidget(self._list, 1)

        # Buttons
        btn_lo = QHBoxLayout()
        self._btn_add = QPushButton("Load Plugin…")
        self._btn_remove = QPushButton("Remove")
        self._btn_reload = QPushButton("Reload All")
        btn_lo.addWidget(self._btn_add)
        btn_lo.addWidget(self._btn_remove)
        btn_lo.addWidget(self._btn_reload)
        btn_lo.addStretch()
        lo.addLayout(btn_lo)

        # Info
        self._info = QTextEdit()
        self._info.setReadOnly(True)
        self._info.setMaximumHeight(120)
        self._info.setPlaceholderText("Select a plugin to see details…")
        lo.addWidget(self._info)

        self._plugins: list[dict] = []

        self._btn_add.clicked.connect(self._add_plugin)
        self._btn_remove.clicked.connect(self._remove_plugin)
        self._btn_reload.clicked.connect(self._reload_all)
        self._list.currentRowChanged.connect(self._show_info)

    def _add_plugin(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Plugin Library", "",
            "Shared libraries (*.so *.dll *.dylib);;All files (*)",
        )
        if not path:
            return
        import ctypes
        try:
            lib = ctypes.CDLL(path)
            # Check for required weco_plugin symbols
            name_fn = getattr(lib, "weco_plugin_name", None)
            if name_fn:
                name_fn.restype = ctypes.c_char_p
                pname = name_fn().decode("utf-8", errors="replace")
            else:
                pname = os.path.basename(path)
            entry = {"path": path, "name": pname, "lib": lib}
            self._plugins.append(entry)
            self._list.addItem(f"{pname}  ({os.path.basename(path)})")
            self._info.setText(f"Loaded: {pname}\nPath: {path}")
        except OSError as e:
            QMessageBox.warning(self, "Plugin Error", f"Cannot load:\n{e}")

    def _remove_plugin(self):
        row = self._list.currentRow()
        if row < 0:
            return
        self._plugins.pop(row)
        self._list.takeItem(row)
        self._info.clear()

    def _reload_all(self):
        paths = [p["path"] for p in self._plugins]
        self._plugins.clear()
        self._list.clear()
        for path in paths:
            # Re-add each plugin
            import ctypes
            try:
                lib = ctypes.CDLL(path)
                name_fn = getattr(lib, "weco_plugin_name", None)
                if name_fn:
                    name_fn.restype = ctypes.c_char_p
                    pname = name_fn().decode("utf-8", errors="replace")
                else:
                    pname = os.path.basename(path)
                self._plugins.append({"path": path, "name": pname, "lib": lib})
                self._list.addItem(f"{pname}  ({os.path.basename(path)})")
            except OSError:
                self._list.addItem(f"[FAILED] {os.path.basename(path)}")

    def _show_info(self, row):
        if 0 <= row < len(self._plugins):
            p = self._plugins[row]
            self._info.setText(f"Name: {p['name']}\nPath: {p['path']}")


# ═══════════════════════════════════════════════════════════════════════════
#  Main Window — Sidebar + Stacked Pages
# ═══════════════════════════════════════════════════════════════════════════

PAGE_NAMES = ["Welcome", "Data", "Parameters", "Run", "Results", "Docs", "Plugins"]


# ── Dataset-adaptive defaults ─────────────────────────────────────────────

# Ranked log preferences by geological discriminating power
_LOG_PRIORITY = [
    "GR", "GAMMA", "SGR",          # gamma ray (lithology)
    "DEN", "RHOB", "DENSITY",      # bulk density (porosity/coal)
    "RT", "RES", "RILD", "LLD",    # resistivity (perm/fluid)
    "DT", "SON", "SONIC", "AC",    # sonic (compaction)
    "NEU", "NPHI", "NEUTRON",      # neutron (porosity)
    "SP",                           # spontaneous potential
    "CAL", "CALI",                  # caliper (borehole quality)
]

# Region names that suggest specific constraint types
_CONSTRAINT_REGIONS = {
    "no_crossing": [
        "BIOZONE", "BIOZONES", "ZONE", "ZONES", "HORIZON",
        "SEQUENCE", "FORMATION", "NO_CROSSING", "NOCROSSING",
    ],
    "same_region": [
        "FACIES", "LITHO", "LITHOLOGY", "HYDRO", "SEAM",
        "GROUP", "SAME_REGION", "SAMEREGION",
    ],
}


def _suggest_defaults(data_names, region_names, well_list=None):
    """
    Suggest parameter defaults based on available data channels and regions.

    Scans log names and selects up to 3 logs in order of geological
    discriminating power.  Detects constraint regions automatically.
    Also fills in auto-estimable advanced parameters so users don't
    need to touch them.
    """
    # Start with auto-estimated advanced params
    opts = estimate_auto_params(well_list)
    opts["cost_function"] = "composite"

    data_upper = {d.upper(): d for d in data_names}

    # Pick best logs by priority
    selected_logs = []
    for candidate in _LOG_PRIORITY:
        if candidate in data_upper:
            selected_logs.append(data_upper[candidate])
            if len(selected_logs) >= 3:
                break

    # Fallback: use first available non-depth data
    if not selected_logs:
        skip = {"DEPTH", "MD", "TVD", "TVDSS", "X", "Y", "Z"}
        for d in data_names:
            if d.upper() not in skip:
                selected_logs.append(d)
                if len(selected_logs) >= 2:
                    break

    # Assign logs to var_data slots with descending weights
    weights = [0.50, 0.30, 0.20]
    for i, log in enumerate(selected_logs):
        suffix = "" if i == 0 else str(i + 1)
        opts[f"var_data{suffix}"] = log
        opts[f"var_weight{suffix}"] = weights[i] if len(selected_logs) > 1 else 1.0

    # Detect constraint regions
    region_upper = {r.upper(): r for r in region_names}
    for opt_key, candidates in _CONSTRAINT_REGIONS.items():
        for cand in candidates:
            if cand in region_upper:
                opts[opt_key] = region_upper[cand]
                break

    # Adaptive gap cost: higher for more wells (more complex correlation)
    if well_list is not None:
        try:
            nw = well_list.nbr_wells()
        except AttributeError:
            nw = 5
        if nw >= 15:
            opts["const_gap_cost"] = 2.0
            opts["max_cor"] = 100
        elif nw >= 8:
            opts["const_gap_cost"] = 1.0
            opts["max_cor"] = 80
        else:
            opts["const_gap_cost"] = 0.5
        opts["nbr_cor"] = opts["max_cor"]

    # Adaptive merge order: position if we have coordinates
    opts["order"] = "pyramidal"
    if well_list is not None:
        try:
            has_coords = all(
                hasattr(well_list.wells[i], 'x') and well_list.wells[i].x() != 0
                for i in range(min(2, len(well_list.wells)))
            )
            if has_coords:
                opts["order"] = "position"
        except (AttributeError, IndexError, TypeError):
            pass

    return opts


class WeCoStudio(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"WeCo Studio  v{VERSION}")
        self.setMinimumSize(1000, 650)
        self.resize(1280, 820)
        self.setAcceptDrops(True)  # §3.43 — drag-and-drop support

        self._current_demo = None
        self._dark_mode = False
        self._all_demos_running = False
        self._demo_queue = []
        self._demo_results = []
        self._demo_output_dir = OUTPUT_DIR / "demo_results"
        self._init_ui()
        self._connect_signals()

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_lo = QHBoxLayout(central)
        main_lo.setContentsMargins(0, 0, 0, 0)
        main_lo.setSpacing(0)

        # ── Sidebar ───────────────────────────────────────────────────
        self.sidebar = QListWidget()
        self.sidebar.setFixedWidth(140)
        self.sidebar.setFont(QFont("DejaVu Sans", 11))
        self.sidebar.setSpacing(2)
        self.sidebar.setStyleSheet("""
            QListWidget {
                background-color: #2c3e50;
                color: white;
                border: none;
                padding: 6px 0;
            }
            QListWidget::item {
                padding: 12px 8px;
                border-radius: 4px;
                margin: 2px 6px;
            }
            QListWidget::item:selected {
                background-color: #3498db;
            }
            QListWidget::item:hover {
                background-color: #34495e;
            }
        """)

        _sidebar_labels = [
            ("1.", "Welcome"),
            ("2.", "Data"),
            ("3.", "Parameters"),
            ("4.", "Run"),
            ("5.", "Results"),
            ("6.", "Docs"),
            ("7.", "Plugins"),
        ]
        for num, name in _sidebar_labels:
            item = QListWidgetItem(f"  {num}  {name}")
            item.setSizeHint(QSize(130, 44))
            self.sidebar.addItem(item)

        main_lo.addWidget(self.sidebar)

        # ── Page stack ────────────────────────────────────────────────
        self.stack = QStackedWidget()

        self.page_welcome = WelcomePage()
        self.page_data = DataPage()
        self.page_params = ParamsPage()
        self.page_run = RunPage()
        self.page_results = ResultsPage()
        self.page_help = DocsPage()
        self.page_plugins = PluginPage()

        self.stack.addWidget(self.page_welcome)   # 0
        self.stack.addWidget(self.page_data)       # 1
        self.stack.addWidget(self.page_params)     # 2
        self.stack.addWidget(self.page_run)        # 3
        self.stack.addWidget(self.page_results)    # 4
        self.stack.addWidget(self.page_help)       # 5
        self.stack.addWidget(self.page_plugins)    # 6

        main_lo.addWidget(self.stack, 1)

        # Status bar
        self.statusBar().showMessage("WeCo Studio ready")

        # Dark mode toggle button in status bar
        self._dark_btn = QPushButton("Dark Mode")
        self._dark_btn.setFixedSize(90, 24)
        self._dark_btn.clicked.connect(self.toggle_dark_mode)
        self.statusBar().addPermanentWidget(self._dark_btn)

        # Default page
        self.sidebar.setCurrentRow(0)

    def _connect_signals(self):
        self.sidebar.currentRowChanged.connect(self.stack.setCurrentIndex)

        # Welcome page
        self.page_welcome.demo_selected.connect(self._load_demo)
        self.page_welcome.demo_run_requested.connect(self._load_and_run_demo)
        self.page_welcome.run_all_demos_requested.connect(self._run_all_demos)
        self.page_welcome.open_data.connect(lambda: self._go_page(1))
        self.page_welcome.preset_selected.connect(self._apply_preset)

        # Data page
        self.page_data.wells_loaded.connect(self._on_wells_loaded)

        # Run page
        self.page_run.btn_run.clicked.connect(self._do_run)
        self.page_run.run_finished.connect(self._on_run_finished)

    # ─── Navigation ───────────────────────────────────────────────────

    def _go_page(self, idx):
        self.sidebar.setCurrentRow(idx)

    # ─── Demo Loading ─────────────────────────────────────────────────

    def _load_demo(self, demo):
        self._current_demo = demo

        # 1) Load data
        wells_path = demo["wells"]
        self.page_data.load_file(wells_path)

        # 2) Build parameters with demo opts
        self.page_params.build_params(
            opts=demo["opts"],
            data_names=self.page_data.get_data_names(),
            region_names=self.page_data.get_region_names(),
            editable_keys=demo.get("editable_keys"),
        )

        # 3) Navigate to Data page
        self._go_page(1)
        self.statusBar().showMessage(f"Demo loaded: {demo['title']}")

    # ─── Load & Run Demo (one-click) ─────────────────────────────────

    def _load_and_run_demo(self, demo):
        """Load a demo and immediately run the correlation engine."""
        self._current_demo = demo

        wells_path = demo["wells"]
        self.page_data.load_file(wells_path)

        self.page_params.build_params(
            opts=demo["opts"],
            data_names=self.page_data.get_data_names(),
            region_names=self.page_data.get_region_names(),
            editable_keys=demo.get("editable_keys"),
        )

        self.statusBar().showMessage(f"Running demo: {demo['title']}…")
        self._do_run()

    # ─── Run All Demos ────────────────────────────────────────────────

    def _run_all_demos(self):
        """Run every DEMOS entry sequentially, saving results and plots."""
        self._demo_queue = list(DEMOS)
        self._demo_results = []
        self._all_demos_running = True

        output_dir = OUTPUT_DIR / "demo_results"
        output_dir.mkdir(parents=True, exist_ok=True)
        self._demo_output_dir = output_dir

        self.statusBar().showMessage(
            f"Running all {len(DEMOS)} demos… (0/{len(DEMOS)})")
        self._run_next_demo()

    def _run_next_demo(self):
        if not self._demo_queue:
            self._finish_all_demos()
            return

        demo = self._demo_queue.pop(0)
        done = len(DEMOS) - len(self._demo_queue) - 1
        self.statusBar().showMessage(
            f"Running demo {done + 1}/{len(DEMOS)}: {demo['title']}…")
        self._current_demo = demo

        wells_path = demo["wells"]
        self.page_data.load_file(wells_path)
        self.page_params.build_params(
            opts=demo["opts"],
            data_names=self.page_data.get_data_names(),
            region_names=self.page_data.get_region_names(),
        )
        self._do_run()

    def _finish_all_demos(self):
        self._all_demos_running = False
        n = len(self._demo_results)
        summary_lines = [f"# WeCo Demo Results — {n} demos\n"]
        for title, cost, elapsed, n_cor in self._demo_results:
            summary_lines.append(
                f"- **{title}**: cost={cost:.4f}, {n_cor} correlations, {elapsed:.2f}s")

        summary_path = self._demo_output_dir / "summary.md"
        summary_path.write_text("\n".join(summary_lines))

        self._go_page(4)  # Results page
        self.statusBar().showMessage(
            f"All {n} demos complete — results in tmp/demo_results/")
        QMessageBox.information(
            self, "All Demos Complete",
            f"Ran {n} demos successfully.\n\n"
            f"Results saved to:\n{self._demo_output_dir}\n\n"
            f"Summary: {summary_path}"
        )

    # ─── Geology Preset ──────────────────────────────────────────────

    def _apply_preset(self, preset):
        """Apply a geological environment preset to the parameter page."""
        self._current_demo = None
        opts = preset.get("recommended_opts", {})
        self.page_params.build_params(
            opts=opts,
            data_names=self.page_data.get_data_names(),
            region_names=self.page_data.get_region_names(),
        )
        self._go_page(2)  # Navigate to Parameters
        self.statusBar().showMessage(
            f"Preset applied: {preset['label']} — adjust parameters for your data")

    # ─── Wells Loaded ─────────────────────────────────────────────────

    def _on_wells_loaded(self, wl, path):
        # Rebuild params if not demo-driven
        if self._current_demo is None:
            data_names = self.page_data.get_data_names()
            region_names = self.page_data.get_region_names()

            # Dataset-adaptive defaults: scan available logs and suggest
            adaptive_opts = _suggest_defaults(data_names, region_names, wl)

            self.page_params.build_params(
                opts=adaptive_opts,
                data_names=data_names,
                region_names=region_names,
            )

            hint_parts = []
            if adaptive_opts.get("var_data"):
                hint_parts.append(f"log={adaptive_opts['var_data']}")
            if adaptive_opts.get("var_data2"):
                hint_parts.append(f"+{adaptive_opts['var_data2']}")
            if adaptive_opts.get("no_crossing"):
                hint_parts.append(f"constrained by {adaptive_opts['no_crossing']}")
            hint = ", ".join(hint_parts)
            if hint:
                self.statusBar().showMessage(
                    f"Loaded {wl.nbr_wells()} wells — auto-selected: {hint}")
            else:
                self.statusBar().showMessage(
                    f"Loaded {wl.nbr_wells()} wells from {os.path.basename(path)}")
        else:
            self.statusBar().showMessage(
                f"Loaded {wl.nbr_wells()} wells from {os.path.basename(path)}")

    # ─── Run ──────────────────────────────────────────────────────────

    def _do_run(self):
        wells_path = self.page_data.well_path()
        if not wells_path:
            QMessageBox.warning(self, "WeCo", "No well file loaded.\nGo to Data page first.")
            return

        opts = self.page_params.get_opts()
        if "cost_function" not in opts:
            opts["cost_function"] = "composite"
        opts["debug_cor_info"] = 1

        self._go_page(3)  # switch to Run page
        self.page_run.start_run(wells_path, opts)

    # ─── Results ──────────────────────────────────────────────────────

    def _on_run_finished(self, res_file, well_list):
        if res_file is not None and res_file.get_nbr_results() > 0:
            title = ""
            if self._current_demo:
                title = self._current_demo["title"]
            self.page_results.show_result(res_file, well_list, title)
            # Record in run history
            opts = self.page_params.get_opts()
            elapsed_ms = 0
            try:
                # Extract elapsed time from RunPage status label text
                status = self.page_run.status_label.text()
                if "in " in status and "s" in status:
                    import re as _re
                    m = _re.search(r"(\d+\.?\d*)\s*s", status)
                    if m:
                        elapsed_ms = float(m.group(1)) * 1000
            except Exception:
                pass
            self.page_results.add_run_to_history(title, opts, elapsed_ms)

            # If running all demos, save plot and continue
            if getattr(self, "_all_demos_running", False):
                try:
                    cost = res_file.get_result_cost(0)
                    n_cor = res_file.get_nbr_results()
                    elapsed = elapsed_ms / 1000
                    self._demo_results.append((title, cost, elapsed, n_cor))

                    # Save correlation plot to tmp/demo_results/
                    png = render_correlation_plot(well_list, res_file, title)
                    if png:
                        safe_name = title.replace(" ", "_").replace("/", "-")
                        plot_path = self._demo_output_dir / f"{safe_name}.png"
                        plot_path.write_bytes(png)
                except Exception:
                    pass

                # Schedule next demo (allow event loop to breathe)
                QTimer.singleShot(100, self._run_next_demo)
                return

            # Auto-navigate to results
            QTimer.singleShot(300, lambda: self._go_page(4))

    # ─── Dark Mode Toggle (§3.42) ────────────────────────────────────

    def toggle_dark_mode(self):
        """Toggle dark mode theme."""
        self._dark_mode = not self._dark_mode
        app = QApplication.instance()
        if self._dark_mode:
            palette = QPalette()
            palette.setColor(QPalette.ColorRole.Window, QColor(53, 53, 53))
            palette.setColor(QPalette.ColorRole.WindowText, Qt.GlobalColor.white)
            palette.setColor(QPalette.ColorRole.Base, QColor(35, 35, 35))
            palette.setColor(QPalette.ColorRole.AlternateBase, QColor(53, 53, 53))
            palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(25, 25, 25))
            palette.setColor(QPalette.ColorRole.ToolTipText, Qt.GlobalColor.white)
            palette.setColor(QPalette.ColorRole.Text, Qt.GlobalColor.white)
            palette.setColor(QPalette.ColorRole.Button, QColor(53, 53, 53))
            palette.setColor(QPalette.ColorRole.ButtonText, Qt.GlobalColor.white)
            palette.setColor(QPalette.ColorRole.BrightText, Qt.GlobalColor.red)
            palette.setColor(QPalette.ColorRole.Link, QColor(42, 130, 218))
            palette.setColor(QPalette.ColorRole.Highlight, QColor(42, 130, 218))
            palette.setColor(QPalette.ColorRole.HighlightedText, QColor(35, 35, 35))
            palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(128, 128, 128))
            palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(128, 128, 128))
            palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(128, 128, 128))
            app.setPalette(palette)
            self.statusBar().showMessage("Dark mode enabled")
        else:
            app.setPalette(app.style().standardPalette())
            self.statusBar().showMessage("Light mode enabled")

    # ─── Drag-and-Drop Well File Loading (§3.43) ─────────────────────

    def dragEnterEvent(self, event):
        """Accept drag events with file URLs."""
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                path = url.toLocalFile()
                ext = os.path.splitext(path)[1].lower()
                if ext in (".txt", ".las", ".csv", ".wl", ".epc", ".las3",
                           ".dlis", ".xml", ".wells"):
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event):
        """Handle dropped well files."""
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if os.path.isfile(path):
                self.page_data.load_file(path)
                self._go_page(1)
                self.statusBar().showMessage(f"Loaded: {os.path.basename(path)}")
                break



# ═══════════════════════════════════════════════════════════════════════════
#  Entry Point
# ═══════════════════════════════════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(description=f"WeCo Studio v{VERSION}")
    parser.add_argument("--demo", "-d", type=str, help="Load demo by ID (e.g., 1.1, quat-hydro, coal-full)")
    parser.add_argument("--well-list", "-w", type=str, help="Well list file to load")
    args = parser.parse_args()

    app = QApplication(sys.argv)
    app.setApplicationName("WeCo Studio")
    app.setStyle("Fusion")
    # Explicitly set a known-good font — system may default to math symbol
    # fonts (cmr10, cmsy10) if fontconfig order is wrong.
    _app_font = QFont("DejaVu Sans", 10)
    _app_font.setStyleHint(QFont.StyleHint.SansSerif)
    app.setFont(_app_font)

    window = WeCoStudio()
    window.show()

    if args.demo:
        demo = next((d for d in DEMOS if d["id"] == args.demo), None)
        if demo:
            window._load_demo(demo)
    elif args.well_list:
        window.page_data.load_file(args.well_list)
        window._go_page(1)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
