"""
gen_ontology.py - Generate ontology-enriched OSDU records (BD, CP, Activity).

Produces BusinessDecision, CollaborationProject, and Activity records
with full ontology fields:
  - Parameters[].Keys[] with relationship semantics
  - LifecycleEvents[] (audit trail)
  - ActivityStates[] (gate checklist)
  - Remarks[] (typed annotations)
  - Activity + ActivityTemplate (collaboration actions)

Spec format:
{
  "generator": "ontology",
  "project": "Drogon",
  "gate": "DG2",
  "description": "...",

  // Business Decision
  "business_decision": {
    "name": "Drogon DG2 - Concept Select",
    "decision_level": "DG2",
    "approval_status": "Approved",
    "decision_date": "2026-05-15",
    "decision_summary": "...",
    "reservoir_id": "dev:master-data--Reservoir:Drogon:1",
    "economics": {
      "NPV_10pct": {"value": 520, "unit": "MUSD"},
      "IRR": {"value": 17, "unit": "%"},
      "CAPEX": {"value": 8500, "unit": "MNOK"},
      "OPEX_pa": {"value": 420, "unit": "MNOK"},
      "BreakevenOil": {"value": 42, "unit": "USD/bbl"},
      "Payback": {"value": 7.0, "unit": "a"}
    },
    "uncertainty_summary": {
      "Basis": "FMU ...",
      "TotalRealisations": 250,
      "StaticInPlace_Oil_MSm3": {"P90": 33.8, "P50": 45.4, "P10": 59.4},
      "Recoverable_Oil_MSm3": {"P90": 9.2, "P50": 14.8, "P10": 20.6},
      "RecoveryFactor_pct": {"P90": 27.0, "P50": 32.5, "P10": 36.0}
    },
    "alternatives": [
      {"name": "Full 7-segment", "rank": 1, "rationale": "...", "action": "Approve"},
      {"name": "Reduced scope", "rank": 2, "rationale": "...", "action": "Consider"}
    ],
    "relationships": [
      {"title": "Evidence Package", "target_id": "...", "type": "evidences", "artifact": "PersistedCollection"},
      {"title": "Prior gate", "target_id": "...", "type": "supersedes"},
      {"title": "Geomodel", "target_id": "...", "type": "evidences", "artifact": "ETPDataspace"}
    ],
    "risk_ids": ["dev:master-data--Risk:..."],
    "remarks": [
      {"source": "DG1-Recommendation", "text": "Upgrade FMU to Level 3."},
      {"source": "DG2-Condition", "text": "Acquire core before DG3."}
    ]
  },

  // Collaboration Project
  "collaboration_project": {
    "name": "Drogon Geomodelling",
    "parent_bd": "auto",  // or explicit ID
    "lifecycle_events": [
      {"event_id": "DG1Approved", "name": "DG1 Approved", "datetime": "2026-02-28T00:00:00Z", "remark": "..."},
      ...
    ],
    "gate_checklist": [
      {"milestone_id": "DG2-Volumes", "status": "Completed", "date": "2026-04-01T00:00:00Z"},
      {"milestone_id": "DG2-DevConcept", "status": "Completed", "date": "2026-04-10T00:00:00Z"},
      ...
    ],
    "relationships": [
      {"title": "GeoModel Dataspace", "target_id": "...", "type": "evidences", "artifact": "ETPDataspace"}
    ]
  },

  // Optional: Activity (collaboration actions)
  "activities": [
    {
      "template_name": "Volume Update Action",
      "name": "Volume update — porosity revision",
      "start": "2026-02-12T14:00:00Z",
      "end": "2026-02-12T16:00:00Z",
      "parameters": [
        {"title": "Target BD", "target_id": "...", "type": "informs"},
        {"title": "Reason", "value": "Porosity revised 0.18→0.14"}
      ]
    }
  ]
}
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ._common import (
    default_acl,
    default_legal,
    det_uuid,
    md_id,
    ref_id,
    wpc_id,
)
from ._registry import register


# ═══════════════════════════════════════════════════════════════════════════════
# Main generator entry point
# ═══════════════════════════════════════════════════════════════════════════════


@register("ontology")
def generate(
    spec: Dict[str, Any],
    pfx: str,
    base_dir: Path,
    refs: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Generate ontology-enriched BD + CP + Activity records from config."""
    project = spec.get("project", "Unknown")
    gate = spec.get("gate", "DG1")
    acl = spec.get("acl") or default_acl(pfx)
    legal = spec.get("legal") or default_legal(pfx)

    records: List[Dict[str, Any]] = []
    bd_id = ""

    # ── Business Decision ──
    bd_spec = spec.get("business_decision")
    if bd_spec:
        bd_rec = _build_bd(bd_spec, project, gate, pfx, acl, legal, refs)
        bd_id = bd_rec["id"]
        records.append(bd_rec)

    # ── Collaboration Project ──
    cp_spec = spec.get("collaboration_project")
    if cp_spec:
        cp_rec = _build_cp(cp_spec, project, gate, pfx, acl, legal, bd_id, refs)
        records.append(cp_rec)

    # ── Activities (collaboration actions) ──
    for act_spec in spec.get("activities") or []:
        tpl_rec, act_rec = _build_activity(act_spec, project, gate, pfx, acl, legal, refs)
        records.append(tpl_rec)
        records.append(act_rec)

    return records


# ═══════════════════════════════════════════════════════════════════════════════
# Business Decision builder
# ═══════════════════════════════════════════════════════════════════════════════


def _build_bd(
    bd: Dict[str, Any],
    project: str,
    gate: str,
    pfx: str,
    acl: Dict,
    legal: Dict,
    refs: Dict,
) -> Dict[str, Any]:
    """Build a BD record with full ontology enrichment."""
    slug = bd.get("slug") or f"{project}-{gate}-{bd.get('name', 'BD')}"
    record_id = bd.get("id") or md_id(pfx, "BusinessDecision", det_uuid(slug))

    data: Dict[str, Any] = {
        "Name": bd["name"],
        "Description": bd.get("description", ""),
        "ProjectName": bd.get("project_name", f"{project} Field Development"),
        "DecisionLevelID": ref_id(pfx, "DecisionLevel", bd.get("decision_level", gate)),
        "ApprovalStatusID": ref_id(pfx, "DecisionApprovalStatus", bd.get("approval_status", "Pending")),
    }

    if bd.get("decision_date"):
        data["DecisionDate"] = bd["decision_date"]
    if bd.get("decision_due_date"):
        data["DecisionDueDate"] = bd["decision_due_date"]
    if bd.get("decision_summary"):
        data["DecisionSummary"] = bd["decision_summary"]

    # ── Risk IDs ──
    if bd.get("risk_ids"):
        data["RiskIDs"] = bd["risk_ids"]

    # ── Prior Activity IDs ──
    if bd.get("prior_activity_ids"):
        data["PriorActivityIDs"] = bd["prior_activity_ids"]

    # ── Parameters[] — passthrough (capital-P) or build from relationships ──
    if bd.get("Parameters"):
        data["Parameters"] = bd["Parameters"]
    else:
        params = []
        for rel in bd.get("relationships") or []:
            p = _build_parameter(rel, pfx)
            params.append(p)
        if bd.get("reservoir_id"):
            params.append({
                "Title": "Reservoir scope",
                "Selection": bd.get("reservoir_description", f"{project} reservoir"),
                "ParameterKindID": ref_id(pfx, "ParameterKind", "DataObject"),
                "ParameterRoleID": ref_id(pfx, "ParameterRole", "InputReference"),
                "DataObjectParameter": bd["reservoir_id"],
                "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "Reservoir"}],
            })
        if params:
            data["Parameters"] = params

    # ── ProjectSpecifications[] — passthrough or build from economics ──
    if bd.get("ProjectSpecifications"):
        data["ProjectSpecifications"] = bd["ProjectSpecifications"]
    elif bd.get("economics"):
        data["ProjectSpecifications"] = _build_economics(bd["economics"], pfx)

    # ── Remarks[] — passthrough or build from remarks ──
    if bd.get("Remarks"):
        data["Remarks"] = bd["Remarks"]
    else:
        remarks = []
        for r in bd.get("remarks") or []:
            remarks.append({
                "RemarkSource": r["source"],
                "Remark": r["text"],
            })
        if remarks:
            data["Remarks"] = remarks

    # ── ActivityStates[] — passthrough or build from activity_states ──
    if bd.get("ActivityStates"):
        data["ActivityStates"] = bd["ActivityStates"]
    elif bd.get("activity_states"):
        data["ActivityStates"] = [
            {
                "MilestoneID": st["milestone_id"],
                "EffectiveDateTime": st.get("date", ""),
                "ActivityStatusID": ref_id(pfx, "ActivityStatus", st.get("status", "Planned")),
                "Remark": st.get("remark", ""),
            }
            for st in bd["activity_states"]
        ]

    # ── ext.equinor (uncertainty, alternatives, project type) ──
    ext_eq: Dict[str, Any] = {}
    if bd.get("uncertainty_summary"):
        ext_eq["UncertaintySummary"] = bd["uncertainty_summary"]
    if bd.get("alternatives"):
        ext_eq["Alternatives"] = [
            {
                "Name": a["name"],
                "Rank": a.get("rank", i + 1),
                "Rationale": a.get("rationale", ""),
                "RecommendedAction": a.get("action", ""),
            }
            for i, a in enumerate(bd["alternatives"])
        ]
    if bd.get("activity_state_template_id"):
        ext_eq["ActivityStateTemplateID"] = bd["activity_state_template_id"]
    if bd.get("project_type_id"):
        ext_eq["ProjectTypeID"] = bd["project_type_id"]
    if ext_eq:
        data["ext"] = {"equinor": ext_eq}

    return {
        "id": record_id,
        "kind": "osdu:wks:master-data--BusinessDecision:1.0.0",
        "acl": acl,
        "legal": legal,
        "data": data,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Collaboration Project builder
# ═══════════════════════════════════════════════════════════════════════════════


def _build_cp(
    cp: Dict[str, Any],
    project: str,
    gate: str,
    pfx: str,
    acl: Dict,
    legal: Dict,
    bd_id: str,
    refs: Dict,
) -> Dict[str, Any]:
    """Build a CP record with lifecycle events, gate checklist, relationships."""
    slug = cp.get("slug") or f"{project}-{gate}-CP"
    record_id = cp.get("id") or md_id(pfx, "CollaborationProject", det_uuid(slug))

    parent = cp.get("parent_bd")
    if parent == "auto":
        parent = bd_id
    elif not parent:
        parent = bd_id

    data: Dict[str, Any] = {
        "ProjectName": cp.get("name", f"{project} Collaboration"),
        "Description": cp.get("description", ""),
        "Purpose": cp.get("purpose", f"Cross-gate namespace for {project} {gate}"),
        "Namespace": cp.get("namespace", f"project-{project.lower()}-{gate.lower()}"),
        "LifecycleStatusID": ref_id(pfx, "CollaborationProjectLifecycleStatus", cp.get("status", "Open")),
    }

    if parent:
        data["ParentProjectID"] = parent
    if cp.get("begin_date"):
        data["ProjectBeginDate"] = cp["begin_date"]
    if cp.get("trusted_collection_id"):
        data["TrustedCollectionID"] = cp["trusted_collection_id"]

    # ── Personnel[] (passthrough) ──
    if cp.get("Personnel"):
        data["Personnel"] = cp["Personnel"]

    # ── ProjectSpecifications[] (passthrough) ──
    if cp.get("ProjectSpecifications"):
        data["ProjectSpecifications"] = cp["ProjectSpecifications"]

    # ── LifecycleEvents[] — passthrough or build from lifecycle_events ──
    if cp.get("LifecycleEvents"):
        data["LifecycleEvents"] = cp["LifecycleEvents"]
    else:
        events = []
        for ev in cp.get("lifecycle_events") or []:
            event = {
                "EventID": ev.get("event_id", ""),
                "Name": ev.get("name", ""),
                "DateTime": ev.get("datetime", ""),
            }
            if ev.get("remark"):
                event["Remark"] = ev["remark"]
            if ev.get("resource_collection_id"):
                event["ResourceCollectionID"] = ev["resource_collection_id"]
            events.append(event)
        if events:
            data["LifecycleEvents"] = events

    # ── ActivityStates[] — passthrough or build from gate_checklist ──
    if cp.get("ActivityStates"):
        data["ActivityStates"] = cp["ActivityStates"]
    else:
        checklist = []
        for st in cp.get("gate_checklist") or []:
            checklist.append({
                "MilestoneID": st["milestone_id"],
                "EffectiveDateTime": st.get("date", ""),
                "ActivityStatusID": ref_id(pfx, "ActivityStatus", st.get("status", "Planned")),
                "Remark": st.get("remark", ""),
            })
        if checklist:
            data["ActivityStates"] = checklist

    # ── LastActivityState (passthrough) ──
    if cp.get("LastActivityState"):
        data["LastActivityState"] = cp["LastActivityState"]

    # ── Parameters[] — passthrough or build from relationships ──
    if cp.get("Parameters"):
        data["Parameters"] = cp["Parameters"]
    else:
        params = []
        for rel in cp.get("relationships") or []:
            params.append(_build_parameter(rel, pfx))
        if params:
            data["Parameters"] = params

    return {
        "id": record_id,
        "kind": "osdu:wks:master-data--CollaborationProject:1.0.0",
        "acl": acl,
        "legal": legal,
        "data": data,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Activity builder (template + execution pair)
# ═══════════════════════════════════════════════════════════════════════════════


def _build_activity(
    act: Dict[str, Any],
    project: str,
    gate: str,
    pfx: str,
    acl: Dict,
    legal: Dict,
    refs: Dict,
) -> tuple:
    """Build an ActivityTemplate + Activity pair."""
    tpl_slug = f"{project}-{gate}-AT-{act.get('template_name', 'Action')}"
    tpl_id = act.get("template_id") or wpc_id(pfx, "ActivityTemplate", det_uuid(tpl_slug))

    act_slug = f"{project}-{gate}-Act-{act.get('name', 'Action')}"
    act_id = act.get("activity_id") or wpc_id(pfx, "Activity", det_uuid(act_slug))

    # ActivityTemplate
    tpl_params = []
    for p in act.get("template_parameters") or act.get("parameters") or []:
        tpl_params.append({
            "Title": p["title"],
            "Description": p.get("description", ""),
            "AllowedParameterKindID": ref_id(pfx, "ParameterKind", "DataObject" if p.get("target_id") else "String"),
            "IsRequired": p.get("required", True),
            "MaximumOccurrences": p.get("max_occurrences", 1),
        })

    tpl_rec = {
        "id": tpl_id,
        "kind": "osdu:wks:work-product-component--ActivityTemplate:1.0.0",
        "acl": acl,
        "legal": legal,
        "data": {
            "Name": act.get("template_name", act.get("name", "Collaboration Action")),
            "Description": act.get("template_description", "Collaboration action with audit trail."),
            "ActivityTemplateParameters": tpl_params,
        },
    }

    # Activity (execution instance)
    act_params = []
    for p in act.get("parameters") or []:
        param: Dict[str, Any] = {
            "Title": p["title"],
            "ParameterKindID": ref_id(pfx, "ParameterKind", "DataObject" if p.get("target_id") else "String"),
            "ParameterRoleID": ref_id(pfx, "ParameterRole", p.get("role", "Input")),
        }
        if p.get("target_id"):
            param["DataObjectParameter"] = p["target_id"]
            keys = []
            if p.get("type"):
                keys.append({"ParameterKey": "relationship", "StringParameterKey": p["type"]})
            if p.get("artifact"):
                keys.append({"ParameterKey": "artifact", "StringParameterKey": p["artifact"]})
            if keys:
                param["Keys"] = keys
        elif p.get("value"):
            param["StringParameter"] = p["value"]
        act_params.append(param)

    act_rec = {
        "id": act_id,
        "kind": "osdu:wks:work-product-component--Activity:1.0.0",
        "acl": acl,
        "legal": legal,
        "data": {
            "Name": act["name"],
            "Description": act.get("description", ""),
            "ActivityTemplateID": tpl_id,
            "WorkflowStatus": act.get("status", "Completed"),
            "StartDateTime": act.get("start", ""),
            "EndDateTime": act.get("end", ""),
            "Parameters": act_params,
        },
    }

    return tpl_rec, act_rec


# ═══════════════════════════════════════════════════════════════════════════════
# Shared helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _build_parameter(rel: Dict[str, Any], pfx: str) -> Dict[str, Any]:
    """Build a Parameters[] entry with relationship Keys[]."""
    p: Dict[str, Any] = {
        "Title": rel["title"],
        "ParameterKindID": ref_id(pfx, "ParameterKind", "DataObject"),
        "ParameterRoleID": ref_id(pfx, "ParameterRole", rel.get("role", "InputReference")),
        "DataObjectParameter": rel["target_id"],
    }
    if rel.get("selection"):
        p["Selection"] = rel["selection"]

    keys: List[Dict[str, str]] = []
    if rel.get("type"):
        keys.append({"ParameterKey": "relationship", "StringParameterKey": rel["type"]})
    if rel.get("artifact"):
        keys.append({"ParameterKey": "artifact", "StringParameterKey": rel["artifact"]})
    if rel.get("gate"):
        keys.append({"ParameterKey": "gate", "StringParameterKey": rel["gate"]})
    if keys:
        p["Keys"] = keys

    return p


def _build_economics(econ: Dict[str, Any], pfx: str) -> List[Dict[str, Any]]:
    """Build ProjectSpecifications[] from economics config."""
    specs = []
    for param_type, val in econ.items():
        if isinstance(val, dict):
            specs.append({
                "ParameterTypeID": ref_id(pfx, "ParameterType", param_type),
                "DataQuantityParameter": val["value"],
                "UnitOfMeasureID": ref_id(pfx, "UnitOfMeasure", val.get("unit", "")),
            })
        else:
            # Simple numeric value
            specs.append({
                "ParameterTypeID": ref_id(pfx, "ParameterType", param_type),
                "DataQuantityParameter": val,
            })
    return specs
