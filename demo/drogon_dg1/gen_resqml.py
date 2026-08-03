#!/usr/bin/env python3
"""Generate RESQML 2.0.1 EPC/H5 from the Drogon OSDU records.

Creates:
  resqml/drogon_tables.epc   – two DataFrames (Grid2dRepresentation + StringTableLookup)
  resqml/drogon_tables.h5    – backing HDF5 data
    resqml/drogon_activity.epc – ActivityTemplate + 3 sequential Activity instances
  resqml/drogon_activity.h5  – (empty, needed by resqpy)

Each OSDU ColumnBasedTable → resqpy DataFrame, stored as a Grid2dRepresentation
with StringTableLookup objects providing column names and UoMs.  This is the
established resqpy convention for tabular data in RESQML 2.0.1.

The Activity chain:
    Activity 1 (Generate input parameter table)  → output: input parameters table
    Activity 2 (Run volumetrics workflow)        → input: parameters, output: RAW volumes table
    Activity 3 (Aggregate/report statistics)     → input: RAW volumes, output: STAT/report table
"""

from __future__ import annotations

import json
import pathlib
import uuid as _uuid

import numpy as np
import pandas as pd

import resqpy.model as rq
import resqpy.olio.dataframe as rqdf
import resqpy.olio.uuid as bu
import resqpy.olio.xml_et as rqet
from resqpy.olio.xml_namespaces import curly_namespace as ns

HERE = pathlib.Path(__file__).resolve().parent
RECORDS = HERE / "records"
OUT = HERE / "resqml"

# ---------------------------------------------------------------------------
# Deterministic UUIDs  (uuid5 from a fixed namespace – stable across runs)
# ---------------------------------------------------------------------------
_NS = _uuid.UUID("a0000000-d509-4e00-8000-000000000000")
PARAMS_UUID  = _uuid.uuid5(_NS, "drogon-valysar-input-parameters")
VOLUMES_UUID = _uuid.uuid5(_NS, "drogon-valysar-raw-volumes")
STATS_UUID   = _uuid.uuid5(_NS, "drogon-valysar-stat-volumes")
TMPL_UUID    = _uuid.uuid5(_NS, "drogon-activity-template")
# Single merged activity (replaces former three-step ACT1/2/3 chain).
# Same seed as used for the OSDU Activity record in gen_activity_drogon.py:
#   uuid5(_NS, "drogon-activity-merged")
ACT_UUID     = _uuid.uuid5(_NS, "drogon-activity-merged")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _osdu_uom(osdu_uom_id: str) -> str:
    """Convert OSDU UoM ID to RESQML-friendly string."""
    return osdu_uom_id.rsplit(":", 1)[-1] if osdu_uom_id else "Euc"


def _load_osdu_table(record_path: pathlib.Path) -> tuple[dict, str]:
    """Load an OSDU record and return (table_dict, record_name).
    Works for 'data.Table' (ColumnBasedTable) and 'data.Volumes' (REV).
    """
    rec = json.loads(record_path.read_text("utf-8"))
    data = rec["data"]
    name = data.get("Name", record_path.stem)
    table = data.get("Table") or data.get("Volumes")
    if table is None:
        raise ValueError(f"No Table/Volumes in {record_path.name}")
    return table, name


def _table_to_dataframe(table: dict) -> tuple[pd.DataFrame, list[str]]:
    """Convert OSDU ColumnBasedTable dict → (pandas DataFrame, uom_list).
    Key columns get UoM 'Euc', value columns get their declared UoM.
    String key columns are encoded as float category codes (resqpy DataFrame
    stores the original labels in a StringTableLookup automatically).
    """
    cv = table["ColumnValues"]
    key_names = [c["ColumnName"] for c in table["KeyColumns"]]
    val_cols = table["Columns"]
    val_names = [c["ColumnName"] for c in val_cols]
    all_names = key_names + val_names

    # Build DataFrame – keys first, then values
    df_dict = {}
    for col_name in all_names:
        df_dict[col_name] = cv[col_name]
    df = pd.DataFrame(df_dict)

    # For resqpy DataFrame, all columns must be numeric.
    # Encode string key columns as category codes.
    for c in table["KeyColumns"]:
        if c.get("ValueType") == "string":
            df[c["ColumnName"]] = df[c["ColumnName"]].astype("category").cat.codes.astype(float)
        elif c.get("ValueType") == "integer":
            df[c["ColumnName"]] = df[c["ColumnName"]].astype(float)

    # Ensure all value columns are float
    for vc in val_names:
        df[vc] = pd.to_numeric(df[vc], errors="coerce").astype(float)

    # UoM list: Euc for key columns, declared UoM for value columns
    uom_list = ["Euc"] * len(key_names)
    for vc in val_cols:
        uom_list.append(_osdu_uom(vc.get("UnitOfMeasureID", "")))

    return df, uom_list


def _patch_epc_uuids(epc_path: pathlib.Path, uuid_map: dict[str, str]):
    """Post-process an EPC (ZIP) to replace auto-generated UUIDs with fixed ones.

    *uuid_map*: ``{old_uuid_str: new_uuid_str, ...}``
    Replaces UUIDs in XML filenames, XML content, and .rels files.
    """
    import io, zipfile

    buf = io.BytesIO(epc_path.read_bytes())
    with zipfile.ZipFile(buf, "r") as zin:
        names = zin.namelist()
        contents = {n: zin.read(n) for n in names}

    new_contents: dict[str, bytes] = {}
    for name, data in contents.items():
        new_name = name
        for old, new in uuid_map.items():
            new_name = new_name.replace(old, new)
        # Replace inside XML / rels content
        text = data
        for old, new in uuid_map.items():
            text = text.replace(old.encode(), new.encode())
        new_contents[new_name] = text

    with zipfile.ZipFile(epc_path, "w", zipfile.ZIP_DEFLATED) as zout:
        for name, data in new_contents.items():
            zout.writestr(name, data)


def _patch_h5_uuids(h5_path: pathlib.Path, uuid_map: dict[str, str]):
    """Rename HDF5 groups whose names contain old UUIDs to use new UUIDs.

    resqpy stores data under ``RESQML/<uuid>/...`` - this renames those groups.
    """
    import h5py

    with h5py.File(str(h5_path), "r+") as h5:
        if "RESQML" not in h5:
            return
        resqml_grp = h5["RESQML"]
        for old_uuid, new_uuid in uuid_map.items():
            if old_uuid in resqml_grp:
                resqml_grp.move(old_uuid, new_uuid)


def _inject_stl_extra_metadata(model: rq.Model, df_rq: rqdf.DataFrame,
                               parts_before: set[str]):
    """Add ExtraMetadata entries to the Grid2dRepresentation XML listing its
    associated StringTableLookup UUIDs.  This allows the web UI to resolve
    column names and UoMs without relying on the RDDMS graph API.

    Only considers STL parts that were added AFTER `parts_before` snapshot.

    Adds:
      stl_columns=<uuid>   (title contains 'column')
      stl_uoms=<uuid>      (title contains 'unit')
      stl_decode=<uuid>,.. (all others, comma-separated)
    """
    mesh_node = df_rq.mesh.root
    if mesh_node is None:
        return

    stl_cols: list[str] = []
    stl_uoms: list[str] = []
    stl_decode: list[str] = []

    for part in model.parts():
        if part in parts_before:
            continue  # existed before this DataFrame
        if "StringTableLookup" not in part:
            continue
        stl_uuid = str(model.uuid_for_part(part))
        stl_node = model.root_for_part(part)
        title = rqet.find_nested_tags_text(stl_node, ["Citation", "Title"]) or ""
        tl = title.lower()
        if "column" in tl or "name" in tl:
            stl_cols.append(stl_uuid)
        elif "uom" in tl or "unit" in tl:
            stl_uoms.append(stl_uuid)
        else:
            stl_decode.append(stl_uuid)

    def _add_em(node, name: str, value: str):
        em = rqet.SubElement(node, ns["resqml2"] + "ExtraMetadata")
        em.set(ns["xsi"] + "type", ns["resqml2"] + "NameValuePair")
        n = rqet.SubElement(em, ns["resqml2"] + "Name")
        n.text = name
        v = rqet.SubElement(em, ns["resqml2"] + "Value")
        v.text = value

    if stl_cols:
        _add_em(mesh_node, "stl_columns", ",".join(stl_cols))
    if stl_uoms:
        _add_em(mesh_node, "stl_uoms", ",".join(stl_uoms))
    if stl_decode:
        _add_em(mesh_node, "stl_decode", ",".join(stl_decode))
    print(f"    → ExtraMetadata: stl_columns={len(stl_cols)}, stl_uoms={len(stl_uoms)}, stl_decode={len(stl_decode)}")


# ---------------------------------------------------------------------------
# 1. Build the tables EPC
# ---------------------------------------------------------------------------

def build_tables_epc() -> tuple[pathlib.Path, _uuid.UUID, _uuid.UUID, _uuid.UUID]:
    """Create drogon_tables.epc with two DataFrames (Grid2dRepresentation).
    Returns (epc_path, params_uuid, raw_volumes_uuid, stat_volumes_uuid).
    """
    OUT.mkdir(parents=True, exist_ok=True)
    epc = OUT / "drogon_tables.epc"

    model = rq.new_model(str(epc))

    # --- Input parameters ---
    parts_before_params = set(model.parts())
    params_path = sorted(RECORDS.glob("012_*ColumnBasedTable*.json"))[0]
    params_table, params_name = _load_osdu_table(params_path)
    params_df, params_uom = _table_to_dataframe(params_table)
    print(f"  Params: {params_name}  ({len(params_df)} rows × {len(params_df.columns)} cols)")

    params_rq = rqdf.DataFrame(model, df=params_df, uom_list=params_uom, title=params_name)
    params_rq.write_hdf5_and_create_xml()
    _inject_stl_extra_metadata(model, params_rq, parts_before_params)
    auto_params_uuid = str(params_rq.mesh.uuid)
    print(f"    → Grid2dRepresentation {auto_params_uuid}  (will become {PARAMS_UUID})")

    # --- Output volumes (RAW) ---
    parts_before_vol = set(model.parts())
    vol_path = sorted(RECORDS.glob("010_*ReservoirEstimatedVolumes*.json"))[0]
    vol_table, vol_name = _load_osdu_table(vol_path)
    vol_df, vol_uom = _table_to_dataframe(vol_table)
    print(f"  Volumes: {vol_name}  ({len(vol_df)} rows × {len(vol_df.columns)} cols)")

    vol_rq = rqdf.DataFrame(model, df=vol_df, uom_list=vol_uom, title=vol_name)
    vol_rq.write_hdf5_and_create_xml()
    _inject_stl_extra_metadata(model, vol_rq, parts_before_vol)
    auto_vol_uuid = str(vol_rq.mesh.uuid)
    print(f"    → Grid2dRepresentation {auto_vol_uuid}  (will become {VOLUMES_UUID})")

    # --- Output volumes (STAT) ---
    parts_before_stat = set(model.parts())
    stat_path = sorted(RECORDS.glob("011_*ReservoirEstimatedVolumes*.json"))[0]
    stat_table, stat_name = _load_osdu_table(stat_path)
    stat_df, stat_uom = _table_to_dataframe(stat_table)
    print(f"  Stat volumes: {stat_name}  ({len(stat_df)} rows × {len(stat_df.columns)} cols)")

    stat_rq = rqdf.DataFrame(model, df=stat_df, uom_list=stat_uom, title=stat_name)
    stat_rq.write_hdf5_and_create_xml()
    _inject_stl_extra_metadata(model, stat_rq, parts_before_stat)
    auto_stat_uuid = str(stat_rq.mesh.uuid)
    print(f"    → Grid2dRepresentation {auto_stat_uuid}  (will become {STATS_UUID})")

    model.store_epc()
    model.h5_release()

    # Post-process: replace auto-generated UUIDs with deterministic ones
    uuid_map = {
        auto_params_uuid: str(PARAMS_UUID),
        auto_vol_uuid:    str(VOLUMES_UUID),
        auto_stat_uuid:   str(STATS_UUID),
    }
    _patch_epc_uuids(epc, uuid_map)
    _patch_h5_uuids(epc.with_suffix(".h5"), uuid_map)
    print(f"  → {epc}  (UUIDs patched)")
    return epc, PARAMS_UUID, VOLUMES_UUID, STATS_UUID


# ---------------------------------------------------------------------------
# 2. Build the activity EPC  (ActivityTemplate + Activity)
# ---------------------------------------------------------------------------

def _add_activity_template(model: rq.Model, title: str) -> rqet.Element:
    """Manually build an obj_ActivityTemplate XML node (RESQML 2.0.1)."""

    at_uuid = bu.uuid_from_string(str(TMPL_UUID))
    at_node = model.new_obj_node("ActivityTemplate")
    at_node.set("uuid", str(TMPL_UUID))
    model.create_citation(root=at_node, title=title, originator="ores-pipeline")

    # Generic parameters used across a 3-step sequential activity chain.
    _add_param_template(at_node, "InputParameters", "in",
                        "Input parameter table for the reservoir model workflow",
                        is_input=True, is_output=False, min_occurs=0, max_occurs=1,
                        allowed_kind="dataObject")

    _add_param_template(at_node, "InputVolumes", "in",
                        "Input volume table",
                        is_input=True, is_output=False, min_occurs=0, max_occurs=1,
                        allowed_kind="dataObject")

    # Parameter: Process (reference to the RMS reservoir model workflow)
    _add_param_template(at_node, "Process", "in",
                        "Reservoir modelling workflow (RMS project)",
                        is_input=True, is_output=False, min_occurs=0, max_occurs=1,
                        allowed_kind="dataObject")

    _add_param_template(at_node, "OutputParameters", "out",
                        "Generated input parameter table",
                        is_input=False, is_output=True, min_occurs=0, max_occurs=1,
                        allowed_kind="dataObject")

    # Parameter: Output (ColumnBasedTable – the RAW volumes table)
    _add_param_template(at_node, "OutputVolumes", "out",
                        "Output volume table produced by the workflow",
                        is_input=False, is_output=True, min_occurs=0, max_occurs=1,
                        allowed_kind="dataObject")

    _add_param_template(at_node, "ReportTable", "out",
                        "Output report/statistics table",
                        is_input=False, is_output=True, min_occurs=0, max_occurs=1,
                        allowed_kind="dataObject")

    _add_param_template(at_node, "NumberOfRealizations", "in",
                        "Number of uncertainty realizations",
                        is_input=True, is_output=False, min_occurs=0, max_occurs=1,
                        allowed_kind="integer")

    _add_param_template(at_node, "Workflow", "in",
                        "Workflow label",
                        is_input=True, is_output=False, min_occurs=0, max_occurs=1,
                        allowed_kind="string")

    _add_param_template(at_node, "Method", "in",
                        "Method identifier",
                        is_input=True, is_output=False, min_occurs=0, max_occurs=1,
                        allowed_kind="string")

    _add_param_template(at_node, "Variables", "in",
                        "Serialized workflow variable configuration",
                        is_input=True, is_output=False, min_occurs=0, max_occurs=1,
                        allowed_kind="string")

    _add_param_template(at_node, "DesignMatrix", "in",
                        "Serialized design matrix",
                        is_input=True, is_output=False, min_occurs=0, max_occurs=1,
                        allowed_kind="dataObject")

    model.add_part("obj_ActivityTemplate", at_uuid, at_node)
    return at_node


def _add_param_template(root, title: str, role: str, description: str, *,
                        is_input: bool, is_output: bool, min_occurs: int,
                        max_occurs: int,
                        allowed_kind: str):
    """Add a Parameter (of type ParameterTemplate) child to an ActivityTemplate node."""

    # XSD element name is "Parameter", type is "ParameterTemplate"
    pt = rqet.SubElement(root, ns["resqml2"] + "Parameter")
    pt.set(ns["xsi"] + "type", ns["resqml2"] + "ParameterTemplate")
    pt.text = rqet.null_xml_text

    # XSD order: KeyConstraint?, IsInput, AllowedKind*, IsOutput, Title,
    #            DataObjectContentType?, MaxOccurs, MinOccurs, Constraint?, DefaultValue*

    ii = rqet.SubElement(pt, ns["resqml2"] + "IsInput")
    ii.set(ns["xsi"] + "type", ns["xsd"] + "boolean")
    ii.text = str(is_input).lower()

    ak = rqet.SubElement(pt, ns["resqml2"] + "AllowedKind")
    ak.set(ns["xsi"] + "type", ns["resqml2"] + "ParameterKind")
    ak.text = allowed_kind

    io = rqet.SubElement(pt, ns["resqml2"] + "IsOutput")
    io.set(ns["xsi"] + "type", ns["xsd"] + "boolean")
    io.text = str(is_output).lower()

    t_node = rqet.SubElement(pt, ns["resqml2"] + "Title")
    t_node.set(ns["xsi"] + "type", ns["xsd"] + "string")
    t_node.text = title

    mo = rqet.SubElement(pt, ns["resqml2"] + "MaxOccurs")
    mo.set(ns["xsi"] + "type", ns["xsd"] + "long")
    mo.text = str(max_occurs)

    mino = rqet.SubElement(pt, ns["resqml2"] + "MinOccurs")
    mino.set(ns["xsi"] + "type", ns["xsd"] + "long")
    mino.text = str(min_occurs)


def _add_activity(model: rq.Model, template_node, title: str, *,
                  act_uuid: _uuid.UUID,
                  input_ref: dict | None = None,
                  process_title: str | None = None,
                  output_ref: dict | None = None,
                  extra_string_params: dict[str, str] | None = None,
                  extra_int_params: dict[str, int] | None = None) -> rqet.Element:
    """Manually build an obj_Activity XML node (RESQML 2.0.1)."""

    act_uuid_obj = bu.uuid_from_string(str(act_uuid))
    act_node = model.new_obj_node("Activity")
    act_node.set("uuid", str(act_uuid))
    model.create_citation(root=act_node, title=title, originator="ores-pipeline")

    # Link to template
    tmpl_uuid = template_node.attrib["uuid"]
    model.create_ref_node("ActivityDescriptor", rqet.find_nested_tags_text(template_node, ["Citation", "Title"]),
                          tmpl_uuid, content_type="obj_ActivityTemplate", root=act_node)

    # --- Parameter: Input (DataObjectReference) ---
    if input_ref:
        _add_activity_param_ref(
            act_node,
            input_ref["key"],
            ref_title=input_ref["title"],
            ref_uuid=input_ref["uuid"],
            ref_content_type=input_ref.get("content_type", "obj_Grid2dRepresentation"),
        )

    # --- Parameter: Process ---
    if process_title:
        _add_activity_param_string(act_node, "Process", process_title)

    # --- Parameter: Output (DataObjectReference) ---
    if output_ref:
        _add_activity_param_ref(
            act_node,
            output_ref["key"],
            ref_title=output_ref["title"],
            ref_uuid=output_ref["uuid"],
            ref_content_type=output_ref.get("content_type", "obj_Grid2dRepresentation"),
        )

    if extra_int_params:
        for key, value in extra_int_params.items():
            _add_activity_param_int(act_node, key, value)

    if extra_string_params:
        for key, value in extra_string_params.items():
            _add_activity_param_string(act_node, key, value)

    model.add_part("obj_Activity", act_uuid_obj, act_node)

    # relationship: Activity → Template
    model.create_reciprocal_relationship(act_node, "destinationObject",
                                         template_node, "sourceObject")
    return act_node


def _add_activity_param_ref(root, key: str, *, ref_title: str, ref_uuid, ref_content_type: str):
    """Add a Parameter child with a DataObject reference."""
    param = rqet.SubElement(root, ns["resqml2"] + "Parameter")
    param.set(ns["xsi"] + "type", ns["resqml2"] + "DataObjectParameter")
    param.text = rqet.null_xml_text

    # XSD order: Title, Index?, Selection?, Key*, then DataObject (extension)
    ti = rqet.SubElement(param, ns["resqml2"] + "Title")
    ti.set(ns["xsi"] + "type", ns["xsd"] + "string")
    ti.text = key

    # DataObject sub-element (DataObjectReference)
    dor = rqet.SubElement(param, ns["resqml2"] + "DataObject")
    dor.set(ns["xsi"] + "type", ns["eml"] + "DataObjectReference")
    dor.text = rqet.null_xml_text

    ct = rqet.SubElement(dor, ns["eml"] + "ContentType")
    ct.set(ns["xsi"] + "type", ns["xsd"] + "string")
    ct.text = f"application/x-resqml+xml;version=2.0;type={ref_content_type}"

    tt = rqet.SubElement(dor, ns["eml"] + "Title")
    tt.set(ns["xsi"] + "type", ns["eml"] + "DescriptionString")
    tt.text = ref_title

    uu = rqet.SubElement(dor, ns["eml"] + "UUID")
    uu.set(ns["xsi"] + "type", ns["eml"] + "UuidString")
    uu.text = str(ref_uuid)


def _add_activity_param_string(root, key: str, value: str):
    """Add a Parameter child with a string value (for the dummy Process reference)."""
    param = rqet.SubElement(root, ns["resqml2"] + "Parameter")
    param.set(ns["xsi"] + "type", ns["resqml2"] + "StringParameter")
    param.text = rqet.null_xml_text

    # XSD order: Title, Index?, Selection?, Key*, then Value (extension)
    ti = rqet.SubElement(param, ns["resqml2"] + "Title")
    ti.set(ns["xsi"] + "type", ns["xsd"] + "string")
    ti.text = key

    val = rqet.SubElement(param, ns["resqml2"] + "Value")
    val.set(ns["xsi"] + "type", ns["xsd"] + "string")
    val.text = value


def _add_activity_param_int(root, key: str, value: int):
    """Add a Parameter child with an integer value."""
    param = rqet.SubElement(root, ns["resqml2"] + "Parameter")
    param.set(ns["xsi"] + "type", ns["resqml2"] + "IntegerQuantityParameter")
    param.text = rqet.null_xml_text

    # XSD order: Title, Index?, Selection?, Key*, then Value (extension)
    ti = rqet.SubElement(param, ns["resqml2"] + "Title")
    ti.set(ns["xsi"] + "type", ns["xsd"] + "string")
    ti.text = key

    val = rqet.SubElement(param, ns["resqml2"] + "Value")
    val.text = str(value)


def build_activity_epc(params_uuid, raw_vol_uuid, stat_vol_uuid) -> pathlib.Path:
    """Create drogon_activity.epc with an ActivityTemplate, Activity, and the referenced tables.

    Copies the tables EPC first so that all DataObjectReferences resolve within the file.
    """

    OUT.mkdir(parents=True, exist_ok=True)
    epc = OUT / "drogon_activity.epc"
    tables_epc = OUT / "drogon_tables.epc"

    # Start from the tables EPC so referenced objects are present
    import shutil
    shutil.copy2(tables_epc, epc)
    # Also copy the HDF5 file if present
    tables_h5 = tables_epc.with_suffix(".epc.h5")
    if not tables_h5.exists():
        tables_h5 = tables_epc.with_name(tables_epc.stem + ".h5")
    epc_h5 = epc.with_suffix(".epc.h5")
    if not epc_h5.exists():
        epc_h5 = epc.with_name(epc.stem + ".h5")
    if tables_h5.exists():
        shutil.copy2(tables_h5, epc_h5)

    model = rq.Model(str(epc))

    tmpl = _add_activity_template(
        model,
        title="Reservoir Volumetrics Workflow Template"
    )

    # Derived from obj_Activity_MISSING.xml (example activity for input table generation)
    variables = json.dumps([
        {
            "Name": "ModTable, Oil/water contact OWC 1",
            "QuantityType": "Low/Base/High",
            "Low": 1650.0,
            "Base": 1660.0,
            "High": 1670.0,
            "Group": "Skirt"
        },
        {
            "Name": "ModTable, Oil/water contact OWC 2",
            "QuantityType": "Low/Base/High",
            "Low": 1667.0,
            "Base": 1677.0,
            "High": 1687.0,
            "Group": "Centre"
        },
        {
            "Name": "ModTable, Oil/water contact OWC 3",
            "QuantityType": "Low/Base/High",
            "Low": 1667.0,
            "Base": 1677.0,
            "High": 1687.0,
            "Group": "Centre"
        },
        {
            "Name": "ModTable, Oil/water contact OWC 4",
            "QuantityType": "Low/Base/High",
            "Low": 1650.0,
            "Base": 1660.0,
            "High": 1670.0,
            "Group": "Skirt"
        },
        {
            "Name": "ModTable, Oil/water contact OWC 5",
            "QuantityType": "Low/Base/High",
            "Low": 1667.0,
            "Base": 1677.0,
            "High": 1687.0,
            "Group": "Centre"
        },
        {
            "Name": "ModTable, Oil/water contact OWC 6",
            "QuantityType": "Low/Base/High",
            "Low": 1667.0,
            "Base": 1677.0,
            "High": 1687.0,
            "Group": "Centre"
        },
        {
            "Name": "ModTable, Oil/water contact OWC 7",
            "QuantityType": "Low/Base/High",
            "Low": 1650.0,
            "Base": 1660.0,
            "High": 1670.0,
            "Group": "Skirt"
        },
        {
            "Name": "std_valysar, Floodplain, PHIT, expected mean",
            "QuantityType": "Low/Base/High",
            "Low": 0.09000000357627869,
            "Base": 0.10300000011920929,
            "High": 0.11299999803304672,
            "Group": "Centre"
        },
        {
            "Name": "std_valysar, Channel, PHIT, expected mean",
            "QuantityType": "Low/Base/High",
            "Low": 0.2653200030326843,
            "Base": 0.27532124519348145,
            "High": 0.2853200137615204,
            "Group": "Centre"
        },
        {
            "Name": "std_valysar, Crevasse, PHIT, expected mean",
            "QuantityType": "Low/Base/High",
            "Low": 0.19869999587535858,
            "Base": 0.20869815349578857,
            "High": 0.21870000660419464,
            "Group": "Centre"
        }
    ], separators=(",", ":"))

    design_matrix = json.dumps([
        {
            "Realization": 1,
            "Floodplain, PHIT, expected mean": "Base",
            "Channel, PHIT, expected mean": "Base",
            "Crevasse, PHIT, expected mean": "Base",
            "Skirt": "Base",
            "Center": "Base"
        },
        {
            "Realization": 2,
            "Floodplain, PHIT, expected mean": "Low",
            "Channel, PHIT, expected mean": "Low",
            "Crevasse, PHIT, expected mean": "Low",
            "Skirt": "Low",
            "Center": "Low"
        },
        {
            "Realization": 3,
            "Floodplain, PHIT, expected mean": "High",
            "Channel, PHIT, expected mean": "High",
            "Crevasse, PHIT, expected mean": "High",
            "Skirt": "High",
            "Center": "High"
        }
    ], separators=(",", ":"))

    # Single merged activity: input params → RMS run → statistical table.
    # Incorporates the scenario data from obj_Activity_MISSING.xml.
    # UUID matches the OSDU Activity record (gen_activity_drogon.py).
    _add_activity(
        model, tmpl,
        title="Drogon Valysar - DG1 Volumetrics Workflow Run",
        act_uuid=ACT_UUID,
        input_ref={
            "key": "InputParameters",
            "title": "Drogon Valysar - Input Parameters (per realisation)",
            "uuid": params_uuid,
            "content_type": "obj_Grid2dRepresentation",
        },
        process_title="RMS DecisionExample - Drogon Valysar (3 realisations: Base / Low / High)",
        output_ref={
            "key": "OutputVolumes",
            "title": "Drogon Valysar - Reservoir Estimated Volumes (RAW, per realisation)",
            "uuid": raw_vol_uuid,
            "content_type": "obj_Grid2dRepresentation",
        },
        extra_int_params={"NumberOfRealizations": 3},
        extra_string_params={
            "Workflow":         "DecisionExample",
            "ReportTableName": "DecisionExample_report",
            "Method":           "User_Defined",
            "Variables":        variables,
            "DesignMatrix":     design_matrix,
        },
    )
    # Add OutputParameters (params Grid2dRepresentation) as a second DataObject reference.
    act_node = model.root_for_part(
        model.part_for_uuid(bu.uuid_from_string(str(ACT_UUID)))
    )
    _add_activity_param_ref(
        act_node,
        "OutputParameters",
        ref_title="Drogon Valysar - Input Parameters (per realisation)",
        ref_uuid=params_uuid,
        ref_content_type="obj_Grid2dRepresentation",
    )
    # Add the report table (STAT) as a third output reference.
    _add_activity_param_ref(
        act_node,
        "ReportTable",
        ref_title="Drogon Valysar - Reservoir Estimated Volumes (statistics)",
        ref_uuid=stat_vol_uuid,
        ref_content_type="obj_Grid2dRepresentation",
    )

    model.store_epc()
    model.h5_release()
    print(f"  → {epc}")
    return epc


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    print("\n=== Step 1: RESQML DataFrames (tables) ===")
    epc, params_uuid, vol_uuid, stat_uuid = build_tables_epc()

    print("\n=== Step 2: RESQML Activity ===")
    build_activity_epc(params_uuid, vol_uuid, stat_uuid)

    print("\n=== Summary ===")
    # Re-open and list parts
    m = rq.Model(str(epc))
    parts = m.parts()
    print(f"  Tables EPC: {len(parts)} parts")
    for p in sorted(parts):
        print(f"    {p}")

    act_epc = OUT / "drogon_activity.epc"
    m2 = rq.Model(str(act_epc))
    parts2 = m2.parts()
    print(f"  Activity EPC: {len(parts2)} parts")
    for p in sorted(parts2):
        print(f"    {p}")

    print("\nDone.")


if __name__ == "__main__":
    main()
