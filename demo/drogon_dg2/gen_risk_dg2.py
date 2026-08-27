#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_risk_dg2.py - Generate a Risk manifest for Drogon DG2 (Concept Select).

Carries forward the two DG1 risks (updated residual ratings reflecting
appraisal data) and adds two new DG2-level risks:
  - HSE / environmental (marine discharge & spill risk)
  - Schedule / FPSO availability (long-lead equipment)

Output:
  manifest_risk_dg2.json

Usage:
  py demo/drogon_dg2/gen_risk_dg2.py
"""

import argparse
import json
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent

DEFAULT_ACL = {
    "owners":  ["data.default.owners@dev.dataservices.energy"],
    "viewers": ["data.default.viewers@dev.dataservices.energy"],
}
DEFAULT_LEGAL = {
    "legaltags": ["opendes-private-usa-default"],
    "otherRelevantDataCountries": ["NO"],
}


def main():
    ap = argparse.ArgumentParser(description="Generate Drogon DG2 Risk manifest")
    ap.add_argument("--manifest", default=str(SCRIPT_DIR / "manifest_risk_dg2.json"))
    ap.add_argument("--id-prefix", default="dev")
    args = ap.parse_args()

    pfx = args.id_prefix

    # ── Risk 1: Porosity & cementation (carried from DG1, revised) ──
    risk_porosity = {
        "id":    f"{pfx}:master-data--Risk:Drogon-DG2-PorosityAndCementation:1",
        "kind":  "osdu:wks:master-data--Risk:1.2.0",
        "acl":   DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": "Drogon DG2 - Porosity and cementation uncertainty",
            "Summary": (
                "Porosity and cementation quality in the Valysar fluvial deposits "
                "drive uncertainty in pore volume and hydrocarbon recovery. "
                "DG2 appraisal data have narrowed the range but residual risk remains."
            ),
            "Description": (
                "Updated from DG1 with additional core data from NorthSea and EastLobe "
                "segments. Revised petrophysical interpretation reduces porosity by factor "
                "0.8 (Channel ~0.22, Crevasse ~0.17, Floodplain ~0.08). Cementation effects "
                "are now better constrained through thin-section analysis, reducing inherent "
                "severity from S3 to S2. Revised porosity leads to ~20% reduction in pore "
                "volumes and STOIIP (P50 45.4 vs DG1 56.8 MSm\u00b3). 50 FMU realisations "
                "(up from 3 at DG1) show volume uncertainty is dominated by Channel facies "
                "distribution rather than porosity per facies."
            ),
            "TypeID": "osdu:wks:reference-data--RiskType:risk:1.0.0",
            "EffectiveDateTime": "2026-02-28T00:00:00Z",
            "ext": {
                "equinor": {
                    "CategoryID": f"{pfx}:reference-data--RiskCategory:Subsurface-Static:",
                    "SeverityScaleID": f"{pfx}:reference-data--RiskSeverityScale:Equinor-5x5:",
                    "ProbabilityScaleID": f"{pfx}:reference-data--RiskProbabilityScale:Equinor-5x5:",
                    "RiskAcceptanceCriteriaID": f"{pfx}:reference-data--RiskAcceptanceCriteria:RAC-2025-01:",
                    "InherentSeverity":   "S2",
                    "InherentProbability": "P3",
                    "ResidualSeverity":   "S2",
                    "ResidualProbability": "P2",
                    "AcceptedAsIs": False,
                    "Status": "Mitigated",
                    "MitigationActionIDs": [],
                },
            },
        },
    }

    # ── Risk 2: Fault compartmentalisation (carried from DG1, revised) ──
    risk_fault = {
        "id":    f"{pfx}:master-data--Risk:Drogon-DG2-FaultCompartment:1",
        "kind":  "osdu:wks:master-data--Risk:1.2.0",
        "acl":   DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": "Drogon DG2 - Fault transmissibility and reservoir compartmentalization",
            "Summary": (
                "Sealing or partially-sealing faults may compartmentalise the Valysar "
                "reservoir, restricting drainage and requiring additional infill wells."
            ),
            "Description": (
                "Production testing in early appraisal wells (2025-Q4) confirmed "
                "partial pressure communication across the CentralHorst–CentralSouth "
                "boundary fault, reducing worst-case compartmentalisation risk. "
                "However NorthHorst and EastLobe remain untested. With DG2-revised "
                "porosity (\u00d70.8), absolute recoverable volumes are lower, making "
                "infill well economics more marginal. Dynamic simulation (50 realisations) "
                "indicates 30% probability of needing 2\u20134 additional infill wells "
                "(est. 80\u2013120 MUSD incremental CAPEX). DG2 concept includes 2 contingent "
                "well slots in the template layout."
            ),
            "TypeID": "osdu:wks:reference-data--RiskType:risk:1.0.0",
            "EffectiveDateTime": "2026-02-28T00:00:00Z",
            "ext": {
                "equinor": {
                    "CategoryID": f"{pfx}:reference-data--RiskCategory:Subsurface-Dynamic:",
                    "SeverityScaleID": f"{pfx}:reference-data--RiskSeverityScale:Equinor-5x5:",
                    "ProbabilityScaleID": f"{pfx}:reference-data--RiskProbabilityScale:Equinor-5x5:",
                    "RiskAcceptanceCriteriaID": f"{pfx}:reference-data--RiskAcceptanceCriteria:RAC-2025-01:",
                    "InherentSeverity":   "S3",
                    "InherentProbability": "P3",
                    "ResidualSeverity":   "S2",
                    "ResidualProbability": "P2",
                    "AcceptedAsIs": False,
                    "Status": "Mitigated",
                    "MitigationActionIDs": [],
                },
            },
        },
    }

    # ── Risk 3: HSE / environmental (new for DG2) ──────────────────
    risk_hse = {
        "id":    f"{pfx}:master-data--Risk:Drogon-DG2-HSE-Environmental:1",
        "kind":  "osdu:wks:master-data--Risk:1.2.0",
        "acl":   DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": "Drogon DG2 - HSE and environmental impact",
            "Summary": (
                "Marine discharge and accidental spill risk during subsea installation "
                "and production operations in the Drogon area."
            ),
            "Description": (
                "Environmental impact assessment (EIA) identifies cold-water coral "
                "habitats within 2 km of the planned template locations. Produced water "
                "discharge exceeding 30 mg/L oil-in-water requires additional treatment "
                "capacity on the FPSO. Accidental spill scenarios (blowout, pipeline "
                "rupture) modelled with OSCAR show shoreline impact probability <2% "
                "under prevailing current conditions. Mitigation: coral avoidance "
                "routing for flowlines, enhanced produced-water treatment module, "
                "and subsea isolation valves at each template."
            ),
            "TypeID": "osdu:wks:reference-data--RiskType:risk:1.0.0",
            "EffectiveDateTime": "2026-02-28T00:00:00Z",
            "ext": {
                "equinor": {
                    "CategoryID": f"{pfx}:reference-data--RiskCategory:HSE:",
                    "SeverityScaleID": f"{pfx}:reference-data--RiskSeverityScale:Equinor-5x5:",
                    "ProbabilityScaleID": f"{pfx}:reference-data--RiskProbabilityScale:Equinor-5x5:",
                    "RiskAcceptanceCriteriaID": f"{pfx}:reference-data--RiskAcceptanceCriteria:RAC-2025-01:",
                    "InherentSeverity":   "S4",
                    "InherentProbability": "P2",
                    "ResidualSeverity":   "S3",
                    "ResidualProbability": "P1",
                    "AcceptedAsIs": False,
                    "Status": "Mitigated",
                    "MitigationActionIDs": [],
                },
            },
        },
    }

    # ── Risk 4: Schedule / long-lead equipment (new for DG2) ──────
    risk_schedule = {
        "id":    f"{pfx}:master-data--Risk:Drogon-DG2-ScheduleFPSO:1",
        "kind":  "osdu:wks:master-data--Risk:1.2.0",
        "acl":   DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": "Drogon DG2 - Schedule risk (FPSO and long-lead equipment)",
            "Summary": (
                "FPSO conversion drydock availability and subsea template fabrication "
                "lead times threaten the 2028-H1 first oil target."
            ),
            "Description": (
                "SRA Monte Carlo schedule analysis (1000 iterations) gives P50 first "
                "oil June 2028 and P90 first oil March 2029. Key drivers: (1) FPSO "
                "drydock slot availability - only two qualifying yards confirmed for "
                "2027-Q1 window, (2) subsea template fabrication - 18-month lead time "
                "from order to delivery, (3) drilling rig market tightness with 2027 "
                "contracting window. Mitigation: early FEED commitment, dual-yard "
                "tendering strategy, and pre-ordering of long-lead subsea equipment."
            ),
            "TypeID": "osdu:wks:reference-data--RiskType:risk:1.0.0",
            "EffectiveDateTime": "2026-02-28T00:00:00Z",
            "ext": {
                "equinor": {
                    "CategoryID": f"{pfx}:reference-data--RiskCategory:Schedule:",
                    "SeverityScaleID": f"{pfx}:reference-data--RiskSeverityScale:Equinor-5x5:",
                    "ProbabilityScaleID": f"{pfx}:reference-data--RiskProbabilityScale:Equinor-5x5:",
                    "RiskAcceptanceCriteriaID": f"{pfx}:reference-data--RiskAcceptanceCriteria:RAC-2025-01:",
                    "InherentSeverity":   "S3",
                    "InherentProbability": "P3",
                    "ResidualSeverity":   "S2",
                    "ResidualProbability": "P2",
                    "AcceptedAsIs": False,
                    "Status": "Open",
                    "MitigationActionIDs": [],
                },
            },
        },
    }

    # ── Risk 5: Fluid contact depth uncertainty (new - from actual model) ──
    risk_owc = {
        "id":    f"{pfx}:master-data--Risk:Drogon-DG2-OWCDepth:1",
        "kind":  "osdu:wks:master-data--Risk:1.2.0",
        "acl":   DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": "Drogon DG2 - Fluid contact depth uncertainty",
            "Summary": (
                "Free water level and gas\u2013oil contact depths are uncertain across "
                "the 7 fault-bounded reservoir regions, directly impacting STOIIP."
            ),
            "Description": (
                "FWL Central = UNIFORM(1672, 1682) m, FWL NorthHorst = UNIFORM(1655, 1665) m, "
                "GOC NorthHorst = UNIFORM(1635, 1645) m (from global_variables.dist). "
                "The 10 m uncertainty range in each region translates to ~8\u201312 % STOIIP "
                "uncertainty per segment. Combined effect: P90\u2013P10 range of ~25 MSm\u00b3 "
                "total oil in place. NorthHorst GOC is particularly critical as it controls "
                "the gas cap volume and associated-gas recovery. Sensitivity analysis shows "
                "FWL_CENTRAL and FWL_NORTH_HORST are top 3 STOIIP drivers."
            ),
            "TypeID": "osdu:wks:reference-data--RiskType:risk:1.0.0",
            "EffectiveDateTime": "2026-02-28T00:00:00Z",
            "ext": {
                "equinor": {
                    "CategoryID": f"{pfx}:reference-data--RiskCategory:Subsurface-Static:",
                    "SeverityScaleID": f"{pfx}:reference-data--RiskSeverityScale:Equinor-5x5:",
                    "ProbabilityScaleID": f"{pfx}:reference-data--RiskProbabilityScale:Equinor-5x5:",
                    "RiskAcceptanceCriteriaID": f"{pfx}:reference-data--RiskAcceptanceCriteria:RAC-2025-01:",
                    "InherentSeverity":   "S3",
                    "InherentProbability": "P4",
                    "ResidualSeverity":   "S2",
                    "ResidualProbability": "P3",
                    "AcceptedAsIs": False,
                    "Status": "Open",
                    "MitigationActionIDs": [],
                    "FmuParameters": [
                        "FWL_CENTRAL (UNIFORM 1672\u20131682 m)",
                        "FWL_NORTH_HORST (UNIFORM 1655\u20131665 m)",
                        "GOC_NORTH_HORST (UNIFORM 1635\u20131645 m)",
                    ],
                },
            },
        },
    }

    # ── Risk 6: Recovery factor uncertainty (new - from dynamic simulation) ──
    risk_rf = {
        "id":    f"{pfx}:master-data--Risk:Drogon-DG2-RecoveryFactor:1",
        "kind":  "osdu:wks:master-data--Risk:1.2.0",
        "acl":   DEFAULT_ACL,
        "legal": DEFAULT_LEGAL,
        "data": {
            "Name": "Drogon DG2 - Recovery factor uncertainty (dynamic)",
            "Summary": (
                "Dynamic simulation recovery factor ranges from 28% (P90) to 37% (P10) "
                "driven by Kv/Kh, relperm, and fault seal uncertainties."
            ),
            "Description": (
                "OPM Flow dynamic simulations (250 realisations, one-by-one sensitivity "
                "design) show recovery factor P90=28%, P50=32.5%, P10=37%. Key dynamic "
                "uncertainty drivers: KVKH_CHANNEL (UNIFORM 0.4\u20130.8), KVKH_CREVASSE "
                "(UNIFORM 0.1\u20130.5), RELPERM_INT_WO (UNIFORM -1\u20131), RELPERM_INT_GO "
                "(UNIFORM -1\u20131), and FAULT_SEAL_SCALING (LOGUNIF 0.1\u201310). "
                "Low Kv/Kh combined with high fault seal reduces sweep efficiency and "
                "pushes recovery below 30%. Mitigation: water injection strategy (A5, A6) "
                "and rate scaling optimisation. Phase 2 infill wells target remaining "
                "oil in poorly-swept segments."
            ),
            "TypeID": "osdu:wks:reference-data--RiskType:risk:1.0.0",
            "EffectiveDateTime": "2026-02-28T00:00:00Z",
            "ext": {
                "equinor": {
                    "CategoryID": f"{pfx}:reference-data--RiskCategory:Subsurface-Dynamic:",
                    "SeverityScaleID": f"{pfx}:reference-data--RiskSeverityScale:Equinor-5x5:",
                    "ProbabilityScaleID": f"{pfx}:reference-data--RiskProbabilityScale:Equinor-5x5:",
                    "RiskAcceptanceCriteriaID": f"{pfx}:reference-data--RiskAcceptanceCriteria:RAC-2025-01:",
                    "InherentSeverity":   "S3",
                    "InherentProbability": "P3",
                    "ResidualSeverity":   "S2",
                    "ResidualProbability": "P3",
                    "AcceptedAsIs": False,
                    "Status": "Open",
                    "MitigationActionIDs": [],
                    "FmuParameters": [
                        "KVKH_CHANNEL (UNIFORM 0.4\u20130.8)",
                        "KVKH_CREVASSE (UNIFORM 0.1\u20130.5)",
                        "RELPERM_INT_WO (UNIFORM -1\u20131)",
                        "RELPERM_INT_GO (UNIFORM -1\u20131)",
                        "FAULT_SEAL_SCALING (LOGUNIF 0.1\u201310)",
                    ],
                },
            },
        },
    }

    manifest = {
        "kind": "osdu:wks:Manifest:1.0.0",
        "ReferenceData": [],
        "MasterData": [risk_porosity, risk_fault, risk_hse, risk_schedule, risk_owc, risk_rf],
        "Data": {
            "Datasets": [],
            "WorkProductComponents": [],
            "WorkProducts": [],
        },
    }

    out = Path(args.manifest)
    out.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"DG2 Risk manifest written → {out}")
    for r in manifest["MasterData"]:
        print(f"  {r['id']}")


if __name__ == "__main__":
    main()
