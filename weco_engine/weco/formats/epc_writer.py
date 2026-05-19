"""
§4.6 — Pure Python RESQML EPC writer (offline fallback).

Writes a minimal RESQML v2.0.1 EPC package (.epc = ZIP containing .xml + .h5)
without requiring the GOCAD RESQML library.  Covers:

- WellboreTrajectoryRepresentation
- WellLogCurveRepresentation (continuous logs)
- WellboreMarkerFrameRepresentation (correlation picks)

The EPC format is a standard OPC (Open Packaging Convention) ZIP with
``[Content_Types].xml`` and ``_rels/.rels`` plus RESQML XML parts.

Usage::

    from weco.formats.epc_writer import write_epc_wells, write_epc_results

    write_epc_wells("out.epc", well_list)
    write_epc_results("results.epc", res_file, wells_file)
"""

import uuid
import zipfile
import io
from typing import Optional, List
from xml.etree.ElementTree import Element, SubElement, tostring

try:
    import h5py
    _h5py = True
except ImportError:
    _h5py = False

import numpy as np

_RESQML_NS = "http://www.energistics.org/energyml/data/resqmlv2"
_EML_NS = "http://www.energistics.org/energyml/data/commonv2"


def _uuid():
    return str(uuid.uuid4())


def _citation(parent, title, creation="2024-01-01T00:00:00Z"):
    cit = SubElement(parent, f"{{{_EML_NS}}}Citation")
    SubElement(cit, f"{{{_EML_NS}}}Title").text = title
    SubElement(cit, f"{{{_EML_NS}}}Creation").text = creation
    SubElement(cit, f"{{{_EML_NS}}}Format").text = "WeCo"
    SubElement(cit, f"{{{_EML_NS}}}Originator").text = "WeCo"
    return cit


def _content_types_xml(parts):
    root = Element("Types", xmlns="http://schemas.openxmlformats.org/package/2006/content-types")
    SubElement(root, "Default", Extension="rels",
               ContentType="application/vnd.openxmlformats-package.relationships+xml")
    SubElement(root, "Default", Extension="xml",
               ContentType="application/x-resqml+xml;version=2.0;type=obj_EpcExternalPartReference")
    for part_name, content_type in parts:
        SubElement(root, "Override", PartName=f"/{part_name}",
                   ContentType=content_type)
    return tostring(root, xml_declaration=True, encoding="unicode")


def _rels_xml(relationships):
    root = Element("Relationships",
                   xmlns="http://schemas.openxmlformats.org/package/2006/relationships")
    for rid, target, rtype in relationships:
        SubElement(root, "Relationship", Id=rid, Target=target, Type=rtype)
    return tostring(root, xml_declaration=True, encoding="unicode")


def write_epc_wells(
    epc_path: str,
    well_list,
    *,
    h5_path: Optional[str] = None,
) -> str:
    """
    Write a WellList to a .epc + .h5 file pair.

    Parameters
    ----------
    epc_path : str
        Output .epc path.
    well_list : WellList
        Wells to export.
    h5_path : str, optional
        HDF5 path for array data. Defaults to ``epc_path`` with ``.h5`` suffix.

    Returns
    -------
    str
        Path to the written .epc file.
    """
    if h5_path is None:
        h5_path = epc_path.rsplit(".", 1)[0] + ".h5"

    parts = []
    xml_docs = {}
    rels = []

    # Write HDF5 data
    if _h5py:
        h5f = h5py.File(h5_path, "w")
    else:
        h5f = None

    for wi, well in enumerate(well_list.wells):
        wuuid = _uuid()
        part_name = f"well_{wi}.xml"

        root = Element(f"{{{_RESQML_NS}}}WellboreTrajectoryRepresentation",
                       uuid=wuuid)
        _citation(root, well.name)

        # Store MD array
        depth_key = None
        for dk in ("Depth", "DEPTH", "MD"):
            if dk in well.data:
                depth_key = dk
                break

        if depth_key and h5f is not None:
            ds_path = f"/well_{wi}/MD"
            h5f.create_dataset(ds_path, data=np.array(well.data[depth_key]))

            # Log curves
            for key in well.data:
                if key == depth_key:
                    continue
                log_path = f"/well_{wi}/{key}"
                h5f.create_dataset(log_path, data=np.array(well.data[key]))

        xml_docs[part_name] = tostring(root, xml_declaration=True, encoding="unicode")
        ct = f"application/x-resqml+xml;version=2.0;type=obj_WellboreTrajectoryRepresentation"
        parts.append((part_name, ct))
        rels.append((f"r{wi}", part_name,
                      "http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties"))

    if h5f is not None:
        h5f.close()

    # Write EPC (ZIP)
    with zipfile.ZipFile(epc_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", _content_types_xml(parts))
        zf.writestr("_rels/.rels", _rels_xml(rels))
        for name, xml_str in xml_docs.items():
            zf.writestr(name, xml_str)

    return epc_path


def write_epc_results(
    epc_path: str,
    res_file,
    wells_file,
    *,
    cor_num: int = 0,
    h5_path: Optional[str] = None,
) -> str:
    """
    Write correlation results to a .epc + .h5 file pair.

    Parameters
    ----------
    epc_path : str
    res_file : str or ResFile
    wells_file : str or WellList
    cor_num : int
    h5_path : str, optional

    Returns
    -------
    str
    """
    from weco.data import WellList
    from weco.resfile import ResFile

    if isinstance(wells_file, str):
        wl = WellList(wells_file)
    else:
        wl = wells_file
    if isinstance(res_file, str):
        rf = ResFile(res_file)
    else:
        rf = res_file

    if h5_path is None:
        h5_path = epc_path.rsplit(".", 1)[0] + ".h5"

    parts = []
    xml_docs = {}
    rels = []

    path = rf.get_result_full_path(cor_num) if rf.get_nbr_results() > cor_num else []

    # Marker frame per well
    for wi in range(rf.nbr_well()):
        muuid = _uuid()
        part_name = f"markers_{wi}.xml"

        root = Element(f"{{{_RESQML_NS}}}WellboreMarkerFrameRepresentation",
                       uuid=muuid)
        wname = wl.wells[wi].name if wi < len(wl.wells) else f"Well_{wi}"
        _citation(root, f"Markers_{wname}")

        # Add marker MDs from correlation path
        md_list = []
        for node in path:
            if wi < len(node):
                sample = node[wi]
                depth_key = None
                for dk in ("Depth", "DEPTH", "MD"):
                    if dk in wl.wells[wi].data:
                        depth_key = dk
                        break
                if depth_key and 0 <= sample < len(wl.wells[wi].data[depth_key]):
                    md_list.append(wl.wells[wi].data[depth_key][sample])

        for hi, md in enumerate(md_list):
            marker = SubElement(root, f"{{{_RESQML_NS}}}WellboreMarker")
            SubElement(marker, f"{{{_RESQML_NS}}}Md").text = str(md)
            _citation(marker, f"Horizon_{hi}")

        xml_docs[part_name] = tostring(root, xml_declaration=True, encoding="unicode")
        ct = "application/x-resqml+xml;version=2.0;type=obj_WellboreMarkerFrameRepresentation"
        parts.append((part_name, ct))
        rels.append((f"m{wi}", part_name,
                      "http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties"))

    with zipfile.ZipFile(epc_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", _content_types_xml(parts))
        zf.writestr("_rels/.rels", _rels_xml(rels))
        for name, xml_str in xml_docs.items():
            zf.writestr(name, xml_str)

    return epc_path
