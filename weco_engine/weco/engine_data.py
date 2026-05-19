# Association Scientifique pour la Geologie et ses Applications (ASGA)
#
# Copyright (c) 2022 ASGA. All Rights Reserved.
#
# This program is a Trade Secret of the ASGA and it is not to be:
#  - reproduced, published, or disclosed to other,
#  - distributed or displayed,
#  - used for purposes or on Sites other than described in the GOCAD
#    Advancement Agreement, without the prior written authorization
#    of the ASGA.
#
# Licencee agrees to attach or embed this Notice on all copies of the program,
# including partial copies or modified versions thereof.
"""
Engine data <-> python data conversion
"""
import weco.engine as engine
from weco.data import Well, WellList, ResFile


def well_engine2python(ewell: engine.Well) -> Well:
    """
    Convert Engine Well to Python Well
    """
    well = Well(ewell.well_name())
    well.size = ewell.well_size()
    well.x = ewell.x()
    well.y = ewell.y()
    well.z = ewell.z()
    well.h = ewell.h()
    for data_name in ewell.data_names():
        well.add_data(data_name, ewell.get_data(data_name).data())
    for name in ewell.region_list_names():
        well.add_region(
            name,
            list((i.id, i.start, i.length) for i in ewell.get_region_list(name).regions())
        )

    return well


def well_list_engine2python(ewell_list: engine.WellList) -> WellList:
    """
    Convert Engine WellList to Python WellList
    """
    well_list = WellList()
    for i in range(ewell_list.nbr_wells()):
        well_list.add_well(well_engine2python(ewell_list.well(i)))
    return well_list


def well_python2engine(well: Well) -> engine.Well:
    """
    Convert Python Well to Engine Well
    """
    ewell = engine.Well(well_name=well.name, well_size=well.size, x=well.x, y=well.y, z=well.z, h=well.h)
    for name, value in well.data.items():
        ewell.add_data(name, value)
    for name, regions in well.region.items():
        rm = engine.RegionList(name)
        for i in regions:
            rm.add(*i)
        ewell.add_region_list(rm)

    return ewell


def well_list_python2engine(well_list: WellList) -> engine.WellList:
    """
    Convert Python WellList to Engine WellList
    """
    ewell_list = engine.WellList()
    for well in well_list.wells:
        ewell_list.add(well_python2engine(well))
    return ewell_list


def cor_graph2res_file(cor_graph: engine.CorGraph, build_list: bool = True, reorder: bool = True) -> ResFile:
    res_file = ResFile()
    nbr_well = cor_graph.node_size()
    nbr_nodes = cor_graph.size()
    res_file.well_id = tuple(map(cor_graph.well_id, range(nbr_well)))

    nodes: list[tuple[int, ...]] = list()
    cost: dict[tuple[int, int], float] = dict()
    ftrans: list[list[int]] = list()
    trans: list[list[int]] = list()

    for node_id in range(nbr_nodes):
        ftrans.append(list())
        trans.append(list())
        nodes.append(
            tuple(cor_graph.marker(node_id, i) for i in range(nbr_well))
        )
        nbr_trans = cor_graph.nbr_trans(node_id)
        for t in range(nbr_trans):
            cost_value = cor_graph.trans_cost(node_id, t)
            origin = cor_graph.trans_from(node_id, t)
            cost[(origin, node_id)] = cost_value
            ftrans[origin].append(node_id)
            trans[node_id].append(origin)
    res_file.nodes = tuple(nodes)
    # noinspection PyTypeChecker
    res_file.backward_trans = tuple(map(tuple, trans))
    # noinspection PyTypeChecker
    res_file.forward_trans = tuple(map(tuple, ftrans))
    res_file.cost = cost
    res_file.size = nbr_nodes
    res_file.well_size = tuple(
        1 + max(v[i] for v in nodes)
        for i in range(nbr_well)
    )

    if reorder:
        res_file.reorder()
    if build_list:
        res_file.build_list()

    return res_file
