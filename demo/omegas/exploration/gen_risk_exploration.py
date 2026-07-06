#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_risk_exploration.py – Generate Risk manifest for Omega Sør exploration
well decision (34/4-19 S).

Exploration-focused risks:
  1. Volume/structural uncertainty (OWC, deformation bands) – SHARED with WPC
  2. Geological play risk (trap, seal, reservoir presence)
  3. Drilling & completion (overburden, Hordaland flow) – SHARED with WPC
  4. Well control / kick risk (overpressure in Brent Group)
  5. Data acquisition failure (sampling, logging tool issues)

Risks 1 and 3 are the SAME records as in the WPC decision (same OSDU IDs),
so they can be tracked across both decisions. The exploration BD references
them by ID.

Output: manifest_risk_exploration.json

Usage:
  python demo/omegas/exploration/gen_risk_exploration.py
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from _shared_expl import (
    SCRIPT_DIR, DEFAULT_ACL, DEFAULT_LEGAL, ID_PREFIX,
)


def main():
    ap = argparse.ArgumentParser(description="Generate Omega Sør Exploration Risk manifest")
    ap.add_argument("--manifest", default=str(SCRIPT_DIR / "manifest_risk_exploration.json"))
    ap.add_argument("--id-prefix", default=ID_PREFIX)
    args = ap.parse_args()

    pfx = args.id_prefix

    # ══════════════════════════════════════════════════════════════════
    # SHARED risks (same IDs as WPC decision – enables cross-BD tracking)
    # ══════════════════════════════════════════════════════════════════

    # Risk 1: Volume / Structural uncertainty (same as WPC Risk #3)
    risk_volumes = {
        "id": f"{pfx}:master-data--Risk:OmegaSor-VolumeUncertainty:1",
        "kind": "osdu:wks:master-data--Risk:1.2.0",
        "acl": DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": "Omega Sør – Subsurface volume and structural uncertainty",
            "Summary": (
                "OWC position, deformation bands, and subseismic faults "
                "create significant volume and recovery uncertainty."
            ),
            "Description": (
                "OWC uncertainty: mean 3860 m MSL vs ODT 3772.5 m. Pre-drill OWC "
                "distribution ranges from proven (ODT) to structure-filled. "
                "Deformation bands observed in core/image logs near ISF – "
                "potential permeability reduction by orders of magnitude. "
                "Subseismic faults possible (seismic interpretation ongoing). "
                "STOIIP range: P90 15.8 – P10 22.9 MSm³. "
                "Northern volumes not captured in GEOX evaluation. "
                "Beta prospect (Pg=0.69) represents additional upside. "
                "Exploration well 34/4-19 S critical for OWC confirmation "
                "and reservoir characterization."
            ),
            "TypeID": "osdu:wks:reference-data--RiskType:risk:1.0.0",
            "EffectiveDateTime": "2023-06-01T00:00:00Z",
            "ext": {
                "equinor": {
                    "CategoryID": f"{pfx}:reference-data--RiskCategory:Subsurface-Static:",
                    "SeverityScaleID": f"{pfx}:reference-data--RiskSeverityScale:Equinor-5x5:",
                    "ProbabilityScaleID": f"{pfx}:reference-data--RiskProbabilityScale:Equinor-5x5:",
                    "InherentSeverity": "S3",
                    "InherentProbability": "P4",
                    "ResidualSeverity": "S2",
                    "ResidualProbability": "P3",
                    "AcceptedAsIs": False,
                    "Status": "OpenMitigation",
                    "MitigationActions": [
                        "Exploration well to prove deeper OWC and Tarbert presence",
                        "FMU sensitivity model with deformation band multiplier",
                        "Core analysis for deformation band characterization",
                        "Seismic reprocessing for improved fault imaging",
                    ],
                },
            },
        },
    }

    # Risk 2: Geological play risk (exploration-specific)
    risk_play = {
        "id": f"{pfx}:master-data--Risk:OmegaSor-GeologicalPlay:1",
        "kind": "osdu:wks:master-data--Risk:1.2.0",
        "acl": DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": "Omega Sør – Geological play and trap risk",
            "Summary": (
                "Risk of inadequate trap integrity, seal capacity, or reservoir "
                "quality in the Brent Group target at Omega Sør Alfa prospect."
            ),
            "Description": (
                "Play risk elements for the Omega Sør Alfa prospect: "
                "1) Trap: 4-way dip closure on Top Brent, confirmed on 3D seismic "
                "but subseismic faults may breach seal – Pg(trap) = 0.85. "
                "2) Seal: Drake Fm (shale) provides top seal; lateral seal by "
                "juxtaposition against Inner Snorre Fault – Pg(seal) = 0.90. "
                "3) Reservoir: Brent Group (Tarbert + Rannoch) expected from "
                "regional correlation to Snorre wells – Pg(reservoir) = 0.95. "
                "4) Charge: Draupne Fm source rock, lateral migration from "
                "Snorre kitchen – Pg(charge) = 0.95. "
                "Combined Pg = 0.69 (including Beta segment). "
                "Key uncertainty: actual sand quality and thickness in Tarbert "
                "at prospect location (no well penetration prior to 34/4-19 S)."
            ),
            "TypeID": "osdu:wks:reference-data--RiskType:risk:1.0.0",
            "EffectiveDateTime": "2023-06-01T00:00:00Z",
            "ext": {
                "equinor": {
                    "CategoryID": f"{pfx}:reference-data--RiskCategory:Exploration-Play:",
                    "SeverityScaleID": f"{pfx}:reference-data--RiskSeverityScale:Equinor-5x5:",
                    "ProbabilityScaleID": f"{pfx}:reference-data--RiskProbabilityScale:Equinor-5x5:",
                    "InherentSeverity": "S4",
                    "InherentProbability": "P3",
                    "ResidualSeverity": "S2",
                    "ResidualProbability": "P1",
                    "AcceptedAsIs": False,
                    "Status": "ClosedMitigated",
                    "MitigationActions": [
                        "Drill exploration well 34/4-19 S to confirm play elements",
                        "3D seismic interpretation for trap geometry and fault mapping",
                        "Regional correlation studies from Snorre/Vigdis analogues",
                        "Basin modelling for charge timing and migration pathway",
                    ],
                    "PostDrillOutcome": (
                        "34/4-19 S confirmed: oil in Tarbert + Rannoch (Brent Group), "
                        "trap and seal effective, charge proven. Pg(play) → 1.0 for proven elements."
                    ),
                },
            },
        },
    }

    # Risk 3: Drilling & Completion (same as WPC Risk #4)
    risk_drilling = {
        "id": f"{pfx}:master-data--Risk:OmegaSor-DrillingCompletion:1",
        "kind": "osdu:wks:master-data--Risk:1.2.0",
        "acl": DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": "Omega Sør – Drilling and completion risk",
            "Summary": (
                "Well design decisions (9⅝\" shoe placement) and overburden "
                "management (Hordaland flow unit) present technical risks."
            ),
            "Description": (
                "Key decisions: 9⅝\" liner shoe placement – potential issues if "
                "placed too shallow for reservoir section TD requirements. "
                "Flow unit in Hordaland 1-2 creates P&A risk – need to de-risk "
                "to 'no flow potential' as on Snorre. Critical to have sufficient "
                "cement length and quality above flow unit in Heather Fm. "
                "For exploration well: cement integrity for P&A obligations, "
                "overburden management documentation (SUB9100) under QA. "
                "Shallow hazards assessment from site survey completed."
            ),
            "TypeID": "osdu:wks:reference-data--RiskType:risk:1.0.0",
            "EffectiveDateTime": "2023-06-01T00:00:00Z",
            "ext": {
                "equinor": {
                    "CategoryID": f"{pfx}:reference-data--RiskCategory:Drilling:",
                    "SeverityScaleID": f"{pfx}:reference-data--RiskSeverityScale:Equinor-5x5:",
                    "ProbabilityScaleID": f"{pfx}:reference-data--RiskProbabilityScale:Equinor-5x5:",
                    "InherentSeverity": "S2",
                    "InherentProbability": "P2",
                    "ResidualSeverity": "S2",
                    "ResidualProbability": "P1",
                    "AcceptedAsIs": False,
                    "Status": "ClosedMitigated",
                    "MitigationActions": [
                        "Site survey and shallow hazards assessment completed",
                        "SUB9100 documentation QA for overburden management",
                        "De-risk Hordaland flow unit (cement verification strategy)",
                        "Offset well analysis (Snorre wells for Hordaland behavior)",
                    ],
                },
            },
        },
    }

    # Risk 4: Well control / kick risk (exploration-specific)
    risk_wellcontrol = {
        "id": f"{pfx}:master-data--Risk:OmegaSor-WellControl:1",
        "kind": "osdu:wks:master-data--Risk:1.2.0",
        "acl": DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": "Omega Sør – Well control and kick risk",
            "Summary": (
                "Risk of influx/kick when penetrating the overpressured Brent "
                "Group reservoir with unknown pressure regime."
            ),
            "Description": (
                "The Omega Sør Alfa prospect targets the Brent Group at ~3800-3870 m "
                "TVD. Pressure regime extrapolated from offset Snorre wells suggests "
                "moderate overpressure (EMW ~1.35-1.45 sg). However, compartmentalization "
                "or proximity to Inner Snorre Fault may create higher-than-expected "
                "pressures. Pre-drill pore pressure prediction based on seismic velocity "
                "analysis. Mud weight window modelling indicates narrow margin in "
                "reservoir section. BOP and well barrier verification per NORSOK D-010. "
                "Kick detection: MPD (Managed Pressure Drilling) considered but not "
                "required for base case. ECD management critical in 8½\" reservoir section."
            ),
            "TypeID": "osdu:wks:reference-data--RiskType:risk:1.0.0",
            "EffectiveDateTime": "2023-06-01T00:00:00Z",
            "ext": {
                "equinor": {
                    "CategoryID": f"{pfx}:reference-data--RiskCategory:Drilling-WellControl:",
                    "SeverityScaleID": f"{pfx}:reference-data--RiskSeverityScale:Equinor-5x5:",
                    "ProbabilityScaleID": f"{pfx}:reference-data--RiskProbabilityScale:Equinor-5x5:",
                    "InherentSeverity": "S4",
                    "InherentProbability": "P2",
                    "ResidualSeverity": "S3",
                    "ResidualProbability": "P1",
                    "AcceptedAsIs": False,
                    "Status": "ClosedMitigated",
                    "MitigationActions": [
                        "Pore pressure prediction from seismic velocity (pre-drill)",
                        "Mud weight window modelling and ECD management plan",
                        "BOP verification and well barrier per NORSOK D-010",
                        "Real-time pore pressure monitoring while drilling (LWD sonic)",
                        "48 MDT pressure points acquired – confirms pressure regime",
                    ],
                    "PostDrillOutcome": (
                        "No influx events during drilling. Pore pressure as predicted. "
                        "48 MDT points confirmed reservoir pressure regime."
                    ),
                },
            },
        },
    }

    # Risk 5: Data acquisition failure (exploration-specific)
    risk_dataquality = {
        "id": f"{pfx}:master-data--Risk:OmegaSor-DataAcquisition:1",
        "kind": "osdu:wks:master-data--Risk:1.2.0",
        "acl": DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": "Omega Sør – Data acquisition and sampling risk",
            "Summary": (
                "Risk that key subsurface data (cores, fluid samples, logs) "
                "cannot be acquired to sufficient quality for prospect evaluation."
            ),
            "Description": (
                "Critical data objectives for 34/4-19 S exploration well: "
                "1) Core Tarbert + Rannoch (target 120 m), "
                "2) Formation water sample for barium content, "
                "3) MDT pressure profile (depletion, contacts, barriers), "
                "4) FMI image log for fracture/deformation band characterization, "
                "5) CMR for permeability estimation. "
                "Risk: unable to obtain formation water sample from 34/4-19 S – "
                "this was realized (no water sample obtained despite attempts). "
                "Core recovery risk in poorly consolidated sands. "
                "FMI tool sticking risk in deviated section. "
                "Contingency: sidewall cores if conventional coring fails."
            ),
            "TypeID": "osdu:wks:reference-data--RiskType:risk:1.0.0",
            "EffectiveDateTime": "2023-06-01T00:00:00Z",
            "ext": {
                "equinor": {
                    "CategoryID": f"{pfx}:reference-data--RiskCategory:Subsurface-DataAcquisition:",
                    "SeverityScaleID": f"{pfx}:reference-data--RiskSeverityScale:Equinor-5x5:",
                    "ProbabilityScaleID": f"{pfx}:reference-data--RiskProbabilityScale:Equinor-5x5:",
                    "InherentSeverity": "S3",
                    "InherentProbability": "P3",
                    "ResidualSeverity": "S3",
                    "ResidualProbability": "P2",
                    "AcceptedAsIs": False,
                    "Status": "ClosedPartial",
                    "MitigationActions": [
                        "Redundant logging suite (wireline + LWD backup)",
                        "Contingency sidewall cores if conventional coring fails",
                        "Multiple MDT attempts at different depths/zones",
                        "Extended pump-out for formation water sampling",
                    ],
                    "PostDrillOutcome": (
                        "120 m core recovered successfully (Tarbert + Rannoch). "
                        "48 MDT points acquired. FMI log obtained. "
                        "FAILED: formation water sample not obtained – barium content "
                        "remains unknown (critical input for development concept)."
                    ),
                },
            },
        },
    }

    # ── Assemble manifest ───────────────────────────────────────────────
    risks = [risk_volumes, risk_play, risk_drilling, risk_wellcontrol, risk_dataquality]

    manifest = {
        "kind": "osdu:wks:Manifest:1.0.0",
        "ReferenceData": [],
        "MasterData": risks,
        "Data": {
            "Datasets": [],
            "WorkProductComponents": [],
            "WorkProducts": [],
        },
    }

    out = Path(args.manifest)
    out.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Exploration Risk manifest written → {out}")
    print(f"  Risks ({len(risks)}):")
    for r in risks:
        shared = "(SHARED with WPC)" if r["id"] in [
            f"{pfx}:master-data--Risk:OmegaSor-VolumeUncertainty:1",
            f"{pfx}:master-data--Risk:OmegaSor-DrillingCompletion:1",
        ] else "(exploration-specific)"
        print(f"    {r['id']}  {shared}")


if __name__ == "__main__":
    main()
