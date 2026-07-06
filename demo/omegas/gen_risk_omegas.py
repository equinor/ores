#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_risk_omegas.py - Generate Risk manifest for Omega Sør WPC decision.

Five risks from the SSVP/PIMS register (PM978 Omega Sør):
  1. Barium scale (Risk #00061) - critical
  2. Low permeability / injectivity (Rannoch)
  3. Volume/structural uncertainty (OWC, deformation bands)
  4. Drilling & completion (shoe placement, overburden)
  5. Schedule & cost overrun (deferral sensitivity)

Output: manifest_risk_omegas.json

Usage:
  python demo/omegas/gen_risk_omegas.py
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from demo.eqn.omegas._shared import SCRIPT_DIR, DEFAULT_ACL, DEFAULT_LEGAL, ID_PREFIX


def main():
    ap = argparse.ArgumentParser(description="Generate Omega Sør Risk manifest")
    ap.add_argument("--manifest", default=str(SCRIPT_DIR / "manifest_risk_omegas.json"))
    ap.add_argument("--id-prefix", default=ID_PREFIX)
    args = ap.parse_args()

    pfx = args.id_prefix

    # ── Risk 1: Barium Scale (#00061) ───────────────────────────────────
    risk_barium = {
        "id": f"{pfx}:master-data--Risk:OmegaSor-BariumScale-00061:1",
        "kind": "osdu:wks:master-data--Risk:1.2.0",
        "acl": DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": "Omega Sør – Barium scale risk (PIMS #00061)",
            "Summary": (
                "Barium sulphate (BaSO4) scale precipitation risk in injector, "
                "producer, and reservoir. Critical decision driver for drainage strategy."
            ),
            "Description": (
                "Scaling risk in the water injector through cross-flow between high and "
                "low permeability sands. BaSO4 can precipitate in the producer and SEP "
                "flowlines, and within the reservoir reducing permeability. "
                "Unable to take water sample from 34/4-19 S - barium content unknown. "
                "Decision tree: Ba <50 mg/L → proceed with base concept; "
                "50–100 mg/L → evaluate depletion/limited injection/GAG; "
                ">100 mg/L → fundamental concept change required. "
                "Mitigation: pilot well to deeper structure for water sample, "
                "WI placement 5–20 m above OWC, HPHT scale inhibitor qualification, "
                "Heriot-Watt university study on in-reservoir precipitation."
            ),
            "TypeID": "osdu:wks:reference-data--RiskType:risk:1.0.0",
            "EffectiveDateTime": "2026-06-15T00:00:00Z",
            "ext": {
                "equinor": {
                    "CategoryID": f"{pfx}:reference-data--RiskCategory:Subsurface-Production:",
                    "SeverityScaleID": f"{pfx}:reference-data--RiskSeverityScale:Equinor-5x5:",
                    "ProbabilityScaleID": f"{pfx}:reference-data--RiskProbabilityScale:Equinor-5x5:",
                    "InherentSeverity": "S4",
                    "InherentProbability": "P3",
                    "ResidualSeverity": "S3",
                    "ResidualProbability": "P3",
                    "AcceptedAsIs": False,
                    "Status": "OpenMitigation",
                    "MitigationActions": [
                        "Pilot well for formation water sampling (OWC + Ba content)",
                        "HPHT scale inhibitor qualification (downhole + squeeze)",
                        "WI placement 5–20 m above OWC to prevent aquifer mobilization",
                        "Heriot-Watt study on in-reservoir BaSO4 precipitation",
                    ],
                },
            },
        },
    }

    # ── Risk 2: Low permeability / Injectivity ─────────────────────────
    risk_injectivity = {
        "id": f"{pfx}:master-data--Risk:OmegaSor-Injectivity:1",
        "kind": "osdu:wks:master-data--Risk:1.2.0",
        "acl": DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": "Omega Sør – Low permeability and injectivity risk",
            "Summary": (
                "Reservoir permeability in Rannoch Fm may be insufficient for "
                "water injection without stimulation."
            ),
            "Description": (
                "Low reservoir permeability (<50 mD avg) and potential injectivity "
                "issues in Rannoch Fm if poor lateral and vertical communication. "
                "Injection pressure limited by what Snorre system can deliver plus "
                "pipeline pressure limits. Solution requires cold-water stress "
                "reduction and fracturing after depletion. If Rannoch injection "
                "desired, zone must be perforated only initially with sufficient "
                "distance to Tarbert. Production packer must be as close to "
                "reservoir as possible. IMR vessel fracturing may be needed. "
                "Mini-DST results from 34/4-19 S indicate producibility but "
                "remaining uncertainty on permeability."
            ),
            "TypeID": "osdu:wks:reference-data--RiskType:risk:1.0.0",
            "EffectiveDateTime": "2026-06-15T00:00:00Z",
            "ext": {
                "equinor": {
                    "CategoryID": f"{pfx}:reference-data--RiskCategory:Subsurface-Dynamic:",
                    "SeverityScaleID": f"{pfx}:reference-data--RiskSeverityScale:Equinor-5x5:",
                    "ProbabilityScaleID": f"{pfx}:reference-data--RiskProbabilityScale:Equinor-5x5:",
                    "InherentSeverity": "S3",
                    "InherentProbability": "P3",
                    "ResidualSeverity": "S2",
                    "ResidualProbability": "P2",
                    "AcceptedAsIs": False,
                    "Status": "OpenMitigation",
                    "MitigationActions": [
                        "Depletion phase before injection to reduce stresses",
                        "Cold water injection to enable fracturing",
                        "Consider IMR vessel for stimulation",
                        "Zone control: perforate Rannoch only if dedicated",
                    ],
                },
            },
        },
    }

    # ── Risk 3: Volume / Structural uncertainty ─────────────────────────
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
                "Recovery factor not fully QC'd/calibrated at SSVP level. "
                "STOIIP range: P90 15.8 – P10 22.9 MSm³. "
                "Northern volumes not captured in GEOX evaluation. "
                "Beta prospect (Pg=0.69) represents additional upside."
            ),
            "TypeID": "osdu:wks:reference-data--RiskType:risk:1.0.0",
            "EffectiveDateTime": "2026-06-15T00:00:00Z",
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
                        "Pilot well to prove deeper OWC and Tarbert presence",
                        "FMU sensitivity model with deformation band multiplier",
                        "Core analysis for deformation band characterization",
                        "Integrate 4D seismic for fault compartment validation",
                    ],
                },
            },
        },
    }

    # ── Risk 4: Drilling & Completion ───────────────────────────────────
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
                "Key decisions: 9⅝\" liner shoe placement – AGI requests placement "
                "into reservoir for deep production packer, but risk of too-shallow "
                "shoe for required injection pressure. Flow unit in Hordaland 1-2 "
                "creates P&A risk – need to de-risk to 'no flow potential' as on "
                "Snorre. Critical to have sufficient cement length and quality above "
                "flow unit in Heather Fm. No extraordinary drilling risks identified "
                "IF stratigraphy and lithology similar to 34/4-19 S. Overburden "
                "management documentation (SUB9100) under QA."
            ),
            "TypeID": "osdu:wks:reference-data--RiskType:risk:1.0.0",
            "EffectiveDateTime": "2026-06-15T00:00:00Z",
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
                    "Status": "OpenMitigation",
                    "MitigationActions": [
                        "Pilot well confirms stratigraphy/lithology for safe planning",
                        "SUB9100 documentation QA for overburden management",
                        "De-risk Hordaland flow unit (cement verification strategy)",
                    ],
                },
            },
        },
    }

    # ── Risk 5: Schedule & Cost ─────────────────────────────────────────
    risk_schedule = {
        "id": f"{pfx}:master-data--Risk:OmegaSor-ScheduleCost:1",
        "kind": "osdu:wks:master-data--Risk:1.2.0",
        "acl": DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": "Omega Sør – Schedule and cost overrun risk",
            "Summary": (
                "Project deferral or cost escalation risk – robustness scenario "
                "shows +20% CAPEX, -10% production, +1 year delay still economic."
            ),
            "Description": (
                "Schedule sensitivity: 1-year postponement of DG3+DG4 tested. "
                "1-year DG4 delay tested separately. Robustness scenario: +20% CAPEX, "
                "-10% production, +1 year postponement – project remains economic. "
                "Soil investigation (CPT) planned June 2026 as input to detail "
                "engineering for new template location (~MNOK 2). "
                "Phase 2 D&W cost assumes similar to Phase 1. "
                "CO2, fuel & flare costs not included in current economics. "
                "Break-even at 25 USD/bbl provides significant headroom."
            ),
            "TypeID": "osdu:wks:reference-data--RiskType:risk:1.0.0",
            "EffectiveDateTime": "2026-06-15T00:00:00Z",
            "ext": {
                "equinor": {
                    "CategoryID": f"{pfx}:reference-data--RiskCategory:Commercial:",
                    "SeverityScaleID": f"{pfx}:reference-data--RiskSeverityScale:Equinor-5x5:",
                    "ProbabilityScaleID": f"{pfx}:reference-data--RiskProbabilityScale:Equinor-5x5:",
                    "InherentSeverity": "S2",
                    "InherentProbability": "P2",
                    "ResidualSeverity": "S1",
                    "ResidualProbability": "P2",
                    "AcceptedAsIs": True,
                    "Status": "Accepted",
                    "MitigationActions": [
                        "Complete CPT soil investigation for template location",
                        "Parallel-track DG0/DG3 to compress schedule",
                        "Monitor oil price vs break-even (25 USD/bbl headroom)",
                    ],
                },
            },
        },
    }

    # ── Assemble manifest ───────────────────────────────────────────────
    risks = [risk_barium, risk_injectivity, risk_volumes, risk_drilling, risk_schedule]

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
    print(f"Risk manifest written → {out}")
    print(f"  Risks ({len(risks)}):")
    for r in risks:
        print(f"    {r['id']}")


if __name__ == "__main__":
    main()
