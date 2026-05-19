"""
weco.decision_tree — Correlation Workflow Decision Tree
========================================================

Guides the user through parameter selection based on:
- Geological environment (depositional setting)
- Data availability (which channels exist)
- Data quality (noise level, cross-correlation)
- Uncertainty level (well spacing, lateral variability)

Usage::

    from weco.decision_tree import recommend_workflow
    rec = recommend_workflow(well_list)
    print(rec["strategy"])
    print(rec["options"])
    print(rec["warnings"])

The tree outputs:
- Recommended cost function
- Suggested options (max_cor, nbr_cor, band_width, etc.)
- Data channel priorities
- Warnings about potential noise correlation
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .data import WellList

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# §1  Data Quality Assessment
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class DataQuality:
    """Assessment of input data quality for one channel."""
    name: str
    present_in_all: bool = False
    mean_snr: float = 0.0        # signal-to-noise ratio estimate
    cross_corr: float = 0.0      # avg cross-correlation between wells
    variability: float = 0.0     # coefficient of variation
    is_discrete: bool = False    # facies-like integer data
    n_unique: int = 0            # distinct values (for discrete)
    recommendation: str = ""     # "use", "secondary", "skip"


def assess_channel_quality(wl: WellList, channel: str) -> DataQuality:
    """Assess data quality for a single channel across all wells."""
    dq = DataQuality(name=channel)
    dq.present_in_all = wl.wells_data_exists(channel)

    if not dq.present_in_all:
        dq.recommendation = "skip"
        return dq

    all_values = []
    well_means = []
    well_stds = []

    for w in wl.wells:
        vals = np.array(w.data[channel], dtype=float)
        vals = vals[np.isfinite(vals)]
        if len(vals) == 0:
            continue
        all_values.append(vals)
        well_means.append(np.mean(vals))
        well_stds.append(np.std(vals))

    if not all_values:
        dq.recommendation = "skip"
        return dq

    # Check if discrete
    combined = np.concatenate(all_values)
    unique_vals = np.unique(combined)
    dq.n_unique = len(unique_vals)
    dq.is_discrete = (dq.n_unique <= 30 and
                      np.all(np.abs(combined - np.round(combined)) < 0.01))

    # Signal-to-noise: ratio of inter-well variance to intra-well noise
    global_std = np.std(combined)
    avg_local_std = np.mean(well_stds) if well_stds else 1.0
    dq.mean_snr = global_std / max(avg_local_std, 1e-10)

    # Variability (coefficient of variation)
    global_mean = np.mean(combined)
    dq.variability = global_std / max(abs(global_mean), 1e-10)

    # Cross-correlation estimate (between adjacent wells)
    if len(all_values) >= 2:
        correlations = []
        for i in range(len(all_values) - 1):
            a, b = all_values[i], all_values[i + 1]
            min_len = min(len(a), len(b))
            if min_len > 3:
                # Normalize and compute correlation
                a_norm = (a[:min_len] - np.mean(a[:min_len]))
                b_norm = (b[:min_len] - np.mean(b[:min_len]))
                denom = np.std(a_norm) * np.std(b_norm) * min_len
                if denom > 0:
                    correlations.append(
                        np.sum(a_norm * b_norm) / denom
                    )
        dq.cross_corr = np.mean(correlations) if correlations else 0.0

    # Recommendation
    if dq.is_discrete and dq.n_unique >= 2:
        dq.recommendation = "use"  # facies/region data is always useful
    elif dq.cross_corr > 0.3 and dq.mean_snr > 0.5:
        dq.recommendation = "use"
    elif dq.cross_corr > 0.1:
        dq.recommendation = "secondary"
    else:
        dq.recommendation = "skip"  # likely noise

    return dq


# ═══════════════════════════════════════════════════════════════════════════
# §2  Geological Environment Detection
# ═══════════════════════════════════════════════════════════════════════════

ENVIRONMENT_SIGNATURES = {
    "coal_basin": {
        "channels": ["GR", "DEN", "RT", "SON", "CAL"],
        "regions": ["SEAM", "LITH", "COAL"],
        "indicators": ["GR bimodal (coal=low, shale=high)"],
    },
    "shallow_marine": {
        "channels": ["GR", "NPHI", "RHOB", "DT", "RT"],
        "regions": ["FACIES", "BIOZONE"],
        "indicators": ["GR coarsening-up, fining-up cycles"],
    },
    "deep_marine": {
        "channels": ["GR", "NPHI", "RHOB", "RT", "DISTALITY"],
        "regions": ["FACIES", "BIOZONE", "SEQUENCE"],
        "indicators": ["Turbidite cycles, high GR shale background"],
    },
    "fluvial_deltaic": {
        "channels": ["GR", "FACIES", "SP"],
        "regions": ["FACIES", "STRAT"],
        "indicators": ["Channel sands (blocky low GR), floodplain shales"],
    },
    "paralic_estuarine": {
        "channels": ["FACIES", "ZONE"],
        "regions": ["FACIES", "ZONE"],
        "indicators": ["Marsh/bay/channel/lagoon alternation"],
    },
    "carbonate": {
        "channels": ["GR", "NPHI", "RHOB", "PE", "DT"],
        "regions": ["FACIES", "BIOZONE"],
        "indicators": ["Low GR, porosity logs dominate, PE discriminator"],
    },
    "continental_quaternary": {
        "channels": ["GR", "RT", "MS", "COND", "SPT"],
        "regions": ["FACIES", "HYDRO", "STRAT"],
        "indicators": ["High lateral variability, unconformities"],
    },
}


def detect_geological_environment(wl: WellList) -> Tuple[str, float]:
    """Detect likely geological environment from data channels/regions.

    Returns (environment_key, confidence 0-1).
    """
    data_names_upper = set(n.upper() for n in wl.get_data_names())
    region_names_upper = set(n.upper() for n in wl.get_region_names())

    best_env = "unknown"
    best_score = 0.0

    for env, sig in ENVIRONMENT_SIGNATURES.items():
        score = 0.0
        # Channel matches (support prefix matching: FACIES matches FACIES6)
        env_channels = set(c.upper() for c in sig["channels"])
        channel_overlap = 0
        for ec in env_channels:
            if ec in data_names_upper:
                channel_overlap += 1
            elif any(d.startswith(ec) for d in data_names_upper):
                channel_overlap += 0.8  # partial match
        score += channel_overlap / max(len(env_channels), 1) * 0.6

        # Region matches (support prefix matching)
        env_regions = set(r.upper() for r in sig["regions"])
        region_overlap = 0
        for er in env_regions:
            if er in region_names_upper:
                region_overlap += 1
            elif any(r.startswith(er) for r in region_names_upper):
                region_overlap += 0.8
        score += region_overlap / max(len(env_regions), 1) * 0.4

        if score > best_score:
            best_score = score
            best_env = env

    return best_env, best_score


# ═══════════════════════════════════════════════════════════════════════════
# §3  Workflow Decision Tree
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class WorkflowRecommendation:
    """Complete workflow recommendation from the decision tree."""

    # Strategy
    strategy: str = ""
    environment: str = "unknown"
    confidence: float = 0.0

    # Recommended options
    options: Dict[str, Any] = field(default_factory=dict)

    # Data usage plan
    primary_channel: str = ""
    secondary_channels: List[str] = field(default_factory=list)
    region_constraints: List[str] = field(default_factory=list)
    skip_channels: List[str] = field(default_factory=list)

    # Quality assessment
    channel_quality: List[DataQuality] = field(default_factory=list)

    # Warnings
    warnings: List[str] = field(default_factory=list)

    # Reasoning (for GUI display)
    reasoning: Dict[str, str] = field(default_factory=dict)


def recommend_workflow(wl: WellList) -> WorkflowRecommendation:
    """Main decision tree entry point.

    Analyzes the well data and recommends a complete correlation workflow.

    Decision nodes:
    1. How many wells? (memory/performance implications)
    2. What geological environment? (determines strategy)
    3. Which data channels are useful? (quality assessment)
    4. Any region constraints available? (biozone, sequence)
    5. Risk of noise correlation? (cross-correlation check)

    Returns
    -------
    WorkflowRecommendation
        Complete set of recommendations.
    """
    rec = WorkflowRecommendation()
    n_wells = wl.nbr_wells()
    data_names = wl.get_data_names()
    region_names = wl.get_region_names()

    # ─── Node 1: Well count → performance settings ───
    if n_wells > 50:
        rec.options["max_cor"] = 20
        rec.options["nbr_cor"] = 3
        rec.options["band_width"] = 30
        rec.warnings.append(
            f"Large dataset ({n_wells} wells): using band_width=30, max_cor=20 "
            "to prevent memory exhaustion."
        )
        rec.reasoning["performance"] = (
            "With >50 wells the correlation graph grows exponentially. "
            "Band-width and max-cor limits are essential."
        )
    elif n_wells > 10:
        rec.options["max_cor"] = 30
        rec.options["nbr_cor"] = 5
        rec.reasoning["performance"] = (
            "Medium dataset: max_cor=30 balances quality vs memory."
        )
    else:
        rec.options["max_cor"] = 50
        rec.options["nbr_cor"] = 5
        rec.reasoning["performance"] = (
            "Small dataset: full resolution correlation is safe."
        )

    rec.options["out_nbr_cor"] = min(5, rec.options["nbr_cor"])
    rec.options["cost_function"] = "composite"

    # ─── Node 2: Geological environment ───
    env, conf = detect_geological_environment(wl)
    rec.environment = env
    rec.confidence = conf

    # ─── Node 3: Channel quality assessment ───
    # Skip depth-axis channels (always monotonic, not geologically meaningful)
    SKIP_CHANNELS = {"DEPTH", "MD", "TVD", "TVDSS", "Z"}
    quality_map = {}
    for ch in data_names:
        if ch.upper() in SKIP_CHANNELS:
            continue
        dq = assess_channel_quality(wl, ch)
        rec.channel_quality.append(dq)
        quality_map[ch] = dq

    # ─── Node 4: Select primary channel (decision by environment) ───
    # Priority order by environment
    PRIORITY = {
        "coal_basin": ["GR", "DEN", "RT", "SON"],
        "shallow_marine": ["GR", "NPHI", "RHOB", "DT", "FACIES", "DISTALITY"],
        "deep_marine": ["GR", "NPHI", "RHOB", "FACIES", "DISTALITY"],
        "fluvial_deltaic": ["GR", "FACIES", "SP"],
        "paralic_estuarine": ["FACIES", "ZONE", "GR"],
        "carbonate": ["GR", "NPHI", "PE", "RHOB"],
        "continental_quaternary": ["GR", "MS", "RT", "COND"],
        "unknown": ["GR", "FACIES", "NPHI", "RT", "DISTALITY"],
    }

    priority = PRIORITY.get(env, PRIORITY["unknown"])
    primary = None
    for ch in priority:
        # Exact match first, then prefix match (e.g. FACIES matches FACIES6)
        matches = [n for n in data_names if n.upper() == ch.upper()]
        if not matches:
            matches = [n for n in data_names
                       if n.upper().startswith(ch.upper())
                       and n.upper() not in SKIP_CHANNELS]
        if matches:
            dq = quality_map.get(matches[0])
            if dq and dq.recommendation != "skip":
                primary = matches[0]
                break

    # Fallback: pick highest cross-correlation channel
    if not primary:
        usable = [dq for dq in rec.channel_quality
                  if dq.recommendation in ("use", "secondary")]
        if usable:
            usable.sort(key=lambda d: d.cross_corr, reverse=True)
            primary = usable[0].name

    if primary:
        rec.primary_channel = primary
        rec.options["var_data"] = primary
        rec.reasoning["primary_channel"] = (
            f"Selected '{primary}' based on {env} environment priority "
            f"and data quality (xcorr={quality_map.get(primary, DataQuality(name=primary)).cross_corr:.2f})."
        )
    else:
        rec.warnings.append("No suitable primary channel found — check data quality.")

    # Secondary channels
    for dq in rec.channel_quality:
        if dq.name == primary:
            continue
        if dq.recommendation == "use":
            rec.secondary_channels.append(dq.name)
        elif dq.recommendation == "skip":
            rec.skip_channels.append(dq.name)

    # ─── Node 5: Region constraints ───
    # Biozones are the strongest constraint (hard boundaries)
    biozone_like = [r for r in region_names
                    if any(k in r.upper() for k in ["BIO", "ZONE", "STRAT"])]
    sequence_like = [r for r in region_names
                     if any(k in r.upper() for k in ["SEQ", "SEQUENCE"])]
    facies_like = [r for r in region_names
                   if any(k in r.upper() for k in ["FACIES", "LITH", "LITHO"])]

    if biozone_like:
        rec.region_constraints.extend(biozone_like)
        rec.reasoning["constraints"] = (
            f"Biozone regions ({biozone_like}) provide hard chronostratigraphic "
            "boundaries — horizons cannot cross them."
        )
    if sequence_like:
        rec.region_constraints.extend(sequence_like)

    # ─── Node 6: Noise risk assessment ───
    if primary and primary in quality_map:
        dq = quality_map[primary]
        if dq.cross_corr < 0.1 and not dq.is_discrete:
            rec.warnings.append(
                f"Low cross-correlation ({dq.cross_corr:.2f}) for '{primary}' — "
                "risk of correlating noise. Consider using region constraints "
                "or switching to facies data."
            )
            rec.reasoning["noise_risk"] = (
                "When wireline logs show low inter-well similarity, the algorithm "
                "may match random peaks. Facies/region data provides geological "
                "boundaries that are more robust."
            )
        elif dq.cross_corr > 0.7:
            rec.reasoning["noise_risk"] = (
                f"High cross-correlation ({dq.cross_corr:.2f}) — wells are very "
                "similar. Low risk of noise correlation."
            )

    # ─── Node 7: Build strategy summary ───
    parts = []
    if rec.environment != "unknown":
        parts.append(f"{rec.environment.replace('_', ' ').title()} setting")
    if primary:
        parts.append(f"primary={primary}")
    if rec.region_constraints:
        parts.append(f"constrained by {rec.region_constraints}")
    if rec.warnings:
        parts.append(f"{len(rec.warnings)} warning(s)")

    rec.strategy = " | ".join(parts) if parts else "Generic correlation"

    # ─── Node 8: Lateral variability → min_dist ───
    # Wells far apart or in high-variability environments need more diversity
    if env in ("continental_quaternary", "fluvial_deltaic"):
        rec.options["min_dist"] = 0.1
        rec.reasoning["diversity"] = (
            "High lateral variability expected — min_dist>0 ensures "
            "alternative correlation scenarios are preserved."
        )
    elif env in ("paralic_estuarine",):
        rec.options["min_dist"] = 0.05

    # ─── Node 9: Well spacing → order scheme ───
    has_xy = all(hasattr(w, 'x') and w.x != 0 for w in wl.wells)
    if has_xy and n_wells > 3:
        rec.options["order"] = "position"
        rec.reasoning["order"] = (
            "Wells have XY coordinates — position-based order correlates "
            "nearby wells first for better spatial coherence."
        )
    elif n_wells > 6:
        rec.options["order"] = "position"

    return rec


# ═══════════════════════════════════════════════════════════════════════════
# §4  Pretty-print for CLI/GUI
# ═══════════════════════════════════════════════════════════════════════════

def format_recommendation(rec: WorkflowRecommendation) -> str:
    """Format recommendation as human-readable text."""
    lines = []
    lines.append("╔══════════════════════════════════════════════════════════════╗")
    lines.append("║  WeCo Workflow Recommendation                               ║")
    lines.append("╚══════════════════════════════════════════════════════════════╝")
    lines.append("")
    lines.append(f"  Strategy: {rec.strategy}")
    lines.append(f"  Environment: {rec.environment} (confidence: {rec.confidence:.0%})")
    lines.append("")

    lines.append("  ┌─ Recommended Options ─────────────────────────────────────")
    for k, v in rec.options.items():
        lines.append(f"  │  {k}: {v}")
    lines.append("  └────────────────────────────────────────────────────────────")
    lines.append("")

    lines.append("  ┌─ Data Plan ───────────────────────────────────────────────")
    lines.append(f"  │  Primary channel: {rec.primary_channel}")
    if rec.secondary_channels:
        lines.append(f"  │  Secondary: {', '.join(rec.secondary_channels)}")
    if rec.region_constraints:
        lines.append(f"  │  Region constraints: {', '.join(rec.region_constraints)}")
    if rec.skip_channels:
        lines.append(f"  │  Skip (noise): {', '.join(rec.skip_channels)}")
    lines.append("  └────────────────────────────────────────────────────────────")
    lines.append("")

    if rec.warnings:
        lines.append("  ⚠ Warnings:")
        for w in rec.warnings:
            lines.append(f"    • {w}")
        lines.append("")

    if rec.reasoning:
        lines.append("  ┌─ Reasoning ──────────────────────────────────────────────")
        for topic, text in rec.reasoning.items():
            lines.append(f"  │  [{topic}] {text}")
        lines.append("  └────────────────────────────────────────────────────────────")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
# §5  Decision Tree Diagram (for documentation/GUI)
# ═══════════════════════════════════════════════════════════════════════════

DECISION_TREE_TEXT = """
WeCo Correlation Workflow Decision Tree
========================================

    ┌─────────────────────────────────────────┐
    │  START: Load Well Data                  │
    └──────────────────┬──────────────────────┘
                       │
         ┌─────────────▼─────────────┐
         │  How many wells?          │
         └─────┬───────┬───────┬─────┘
               │       │       │
          ≤10  │  11-50│  >50  │
               │       │       │
               ▼       ▼       ▼
         max_cor=50  max_cor=30  max_cor=20
         nbr_cor=5   nbr_cor=5   band_width=30
                                  nbr_cor=3
                       │
         ┌─────────────▼─────────────┐
         │  Geological Environment?  │
         │  (auto-detect from data)  │
         └─────┬───────┬───────┬─────┘
               │       │       │
     Wireline  │ Facies │ Mixed │
     (GR,RT..) │       │       │
               ▼       ▼       ▼
     Primary=GR  Primary=   Primary=GR
                 FACIES     +FACIES region
                       │
         ┌─────────────▼─────────────┐
         │  Region constraints       │
         │  available?               │
         └─────┬───────┬─────────────┘
               │       │
          Yes  │  No   │
               │       │
               ▼       ▼
     Use as hard    Rely on data
     boundaries     similarity only
     (BIOZONE,      (risk: noise
      SEQUENCE)      correlation)
                       │
         ┌─────────────▼─────────────┐
         │  Cross-correlation check  │
         │  (between well pairs)     │
         └─────┬───────┬─────────────┘
               │       │
         >0.3  │  <0.1 │
               │       │
               ▼       ▼
         Good signal   ⚠ NOISE RISK
         → proceed     → add regions
                       → reduce max_cor
                       → try facies instead
                       │
         ┌─────────────▼─────────────┐
         │  Well spacing / XY?       │
         └─────┬───────┬─────────────┘
               │       │
          Yes  │  No   │
               │       │
               ▼       ▼
     order=position  order=linear
                       │
         ┌─────────────▼─────────────┐
         │  OUTPUT: Recommended       │
         │  options + warnings        │
         └────────────────────────────┘

Key Principles:
  • Facies/region data >> wireline logs for correlation robustness
  • Biozone constraints prevent impossible horizon crossings
  • max_cor controls memory: too high = OOM on large datasets
  • band_width prevents wild jumps (correlation ≈ diagonal path)
  • min_dist > 0 ensures multiple DIFFERENT solutions (not clones)
  • Cross-correlation < 0.1 = danger zone (correlating noise)
"""
