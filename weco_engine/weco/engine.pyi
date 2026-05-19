"""
WeCo Python Bindings
"""
from __future__ import annotations
import typing
__all__ = ['CCFPart', 'CorGraph', 'Correlator', 'CostFunc', 'CostHelper', 'CreatTaskFunc', 'DataStore', 'DataStore_Data', 'Log', 'Option', 'OptionParser', 'Project', 'RegionList', 'RegionList_Region', 'Task', 'Well', 'WellList', 'dtw_distance', 'get_version']
class CCFPart:
    def __init__(self) -> None:
        ...
    def dest(self, arg0: int) -> int:
        """
        Destination Marker id
        """
    def dest_cost(self, arg0: float) -> tuple[bool, float]:
        """
        Simplified cost function including only destination, to compute for all wells 
        
        :return: (ok,cost)
        """
    def dest_only(self) -> bool:
        """
        Tells whether the full or simplified transition cost is used 
                    
        :return: True if `dest_cost` must be used or False if it's `full_cost`
        """
    def full_cost(self, arg0: float) -> tuple[bool, float]:
        """
        Full transition cost function including origin and destination, to compute for all wells 
        
        :return: (ok,cost)
        """
    def init(self) -> None:
        """
        init hook
        """
    def init_done(self) -> bool:
        """
        :return: True if the context is defined
        """
    def parent_cost1(self) -> float:
        """
        Cost of first parent corelation
        """
    def parent_cost2(self) -> float:
        """
        Cost of second parent corelation
        """
    def same(self, arg0: int) -> bool:
        """
        True if gap
        """
    def size(self) -> int:
        """
        :return: number of wells  = `size1` + `size1`
        """
    def size1(self) -> int:
        """
        :return: number of wells in first part
        """
    def size2(self) -> int:
        """
        :return: number of wells in second part
        """
    def src(self, arg0: int) -> int:
        """
        Source Marker id
        """
    def well(self, arg0: int) -> Well:
        """
        Well access
        """
class CorGraph:
    def check_order(self) -> bool:
        ...
    @typing.overload
    def dump(self) -> None:
        """
        Debug function: output the graph to std::cout
        """
    @typing.overload
    def dump(self, arg0: str) -> None:
        """
        Debug function: output the graph to file argO
        """
    def empty(self) -> bool:
        """
        True if no correlations
        """
    def marker(self, node_id: int, well_id: int) -> int:
        """
        :return: Marker ID from a node ID and a Well ID
        """
    def nbr_correlation(self) -> int:
        """
        Number if correlations
        """
    def nbr_trans(self, node_id: int) -> int:
        """
        :return: Number of transitions from a CorGraph Node ID
        """
    def node_size(self) -> int:
        """
        :return: Number of wells in the CorGraph
        """
    def size(self) -> int:
        """
        :return: Size of the graph (Number of nodes)
        :rtype: int
        """
    def to_dot(self, filename: str, show_cost: bool = True) -> None:
        """
        Creates a dot file from the graph
        
        :param filename: dot file name
        """
    def trans_cost(self, dest_node_id: int, edge_id: int) -> float:
        """
        :return: Transition cost to arrive at CorGraph Node ID and transition ID 
                         :param edge_id: The transition ID (must be smaller than nbr_trans)
        """
    def trans_from(self, dest_node_id: int, edge_id: int) -> int:
        """
        Allows to navigate in the CorGraph structure 
                        :return: The source CorGraph Node ID corresponding to transition ID 
                        :param dest_node_id: The destination node ID (must be smaller than size) 
                        :param edge_id: The transition ID (must be smaller than nbr_trans)
        """
    def well_id(self, arg0: int) -> int:
        """
        Well id for each column
        """
class Correlator:
    def __init__(self) -> None:
        ...
    def dump_result(self, arg0: int) -> None:
        ...
    def nbr_result(self) -> int:
        ...
    @typing.overload
    def result2corgraph(self, arg0: CorGraph) -> None:
        ...
    @typing.overload
    def result2corgraph(self, arg0: CorGraph, arg1: int) -> None:
        ...
    def run(self, left_corgraph: CorGraph, right_corgraph: CorGraph, number_best_results: int, cost_function: CostFunc) -> None:
        """
        Runs the Correlation between the left and right CorGraphs
        """
class CostFunc:
    def __init__(self) -> None:
        ...
    def get_cost(self, arg0: int, arg1: int, arg2: float, arg3: int, arg4: int, arg5: float) -> bool:
        """
        Deprecated
        """
    def set_cost(self, arg0: float) -> None:
        """
        Deprecated
        """
class CostHelper:
    def cor_graph1(self) -> CorGraph:
        """
        The left CorGraph to be correlated
        """
    def cor_graph2(self) -> CorGraph:
        """
        The right CorGraph to be Correlated
        """
    def dest(self, well_id: int) -> int:
        """
        The destination marker ID for a well 
        			:param well_id: The well identifier (between 0 and size -1)
        """
    def same(self, well_id: int) -> bool:
        """
        :return: True if there is a gap (src == dest) for a well 
        			:param well_id: The well identifier (between 0 and size -1)
        """
    def size(self) -> int:
        """
        The total size for both (left and right) CorGraphs to be correlated.Is equal to size1 + size2
        """
    def size1(self) -> int:
        """
        Number of wells on the left side
        """
    def size2(self) -> int:
        """
        Number of wells on the right side
        """
    def src(self, well_id: int) -> int:
        """
        The source marker ID for a well 
        			:param well_id: The well identifier (between 0 and size -1)
        """
class CreatTaskFunc:
    @typing.overload
    def __call__(self, arg0: Well, arg1: Well) -> Task:
        ...
    @typing.overload
    def __call__(self, arg0: Task, arg1: Well) -> Task:
        ...
    @typing.overload
    def __call__(self, arg0: Well, arg1: Task) -> Task:
        ...
    @typing.overload
    def __call__(self, arg0: Task, arg1: Task) -> Task:
        ...
class DataStore:
    def add_data(self, arg0: str, arg1: list[float]) -> None:
        ...
    def data_exists(self, arg0: str) -> bool:
        """
        True if data exists
        """
    def data_names(self) -> list[str]:
        """
        List of data names
        """
    def get_data(self, arg0: str) -> DataStore_Data:
        ...
class DataStore_Data:
    def data(self) -> list[float]:
        """
        get all values
        """
    def get(self, arg0: int) -> float:
        """
        get value
        """
    def name(self) -> str:
        """
        Data name
        """
    def size(self) -> int:
        """
        Data size
        """
class Log:
    """
    WeCo Log stream
    """
    def __init__(self) -> None:
        """
        Constructor
        """
    def write(self, arg0: str) -> None:
        """
        Write a string to the log
        """
class Option:
    @staticmethod
    def exists(arg0: str) -> bool:
        ...
    @staticmethod
    def list() -> list[Option]:
        ...
    @staticmethod
    def search(arg0: str) -> Option:
        ...
    @staticmethod
    def sorted_list() -> list[Option]:
        ...
    def desc(self) -> str:
        ...
    def info(self) -> str:
        ...
    @typing.overload
    def name(self) -> str:
        ...
    @typing.overload
    def name(self) -> str:
        ...
    def option_list(self) -> list[str]:
        ...
    def set(self, arg0: str) -> bool:
        ...
    def string(self) -> str:
        ...
    def type(self) -> str:
        ...
class OptionParser:
    def __init__(self) -> None:
        ...
    def get_option_value(self, arg0: str) -> str:
        ...
    def option_exists(self, arg0: str) -> bool:
        ...
    def option_load(self, arg0: str) -> bool:
        """
        load options from file
        """
    def reset_options(self) -> None:
        """
        Set all options to default value
        """
    def search_option(self, arg0: str) -> Option:
        ...
    def set_option_value(self, arg0: str, arg1: str) -> bool:
        ...
class Project(OptionParser):
    @staticmethod
    def cost_function_keys() -> list[str]:
        ...
    @staticmethod
    def task_order_keys() -> list[str]:
        ...
    def __init__(self) -> None:
        ...
    def add_ccf_part(self, arg0: typing.Any) -> None:
        """
        Adds a CCFPart to the list of costs
        """
    def clear_order_func(self) -> None:
        """
        Remove define order function
        """
    def result(self) -> CorGraph:
        ...
    @typing.overload
    def run(self, arg0: str) -> bool:
        """
        run from file
        """
    @typing.overload
    def run(self, arg0: WellList) -> bool:
        """
        run from WellList
        """
    def set_order_func(self, arg0: typing.Any) -> None:
        """
        Set order function
        """
    def well_list(self) -> WellList:
        """
        return well list
        """
class RegionList:
    def __init__(self, arg0: str) -> None:
        ...
    def add(self, arg0: int, arg1: int, arg2: int) -> None:
        """
        Add a new region (id,start,length)
        """
    def get_region(self, value: int, default: int = 0) -> int:
        """
        Return region id for value
        """
    def name(self) -> str:
        """
        Region List Name
        """
    def regions(self) -> list[RegionList_Region]:
        """
        Return all regions
        """
class RegionList_Region:
    def __repr__(self) -> str:
        ...
    def is_in(self, arg0: int) -> bool:
        """
        return True if value is in region
        """
    @property
    def id(self) -> int:
        """
        Region id
        """
    @property
    def length(self) -> int:
        """
        Region length
        """
    @property
    def start(self) -> int:
        """
        Region start
        """
class Task:
    def __repr__(self) -> str:
        ...
class Well(DataStore):
    def __init__(self, well_id: int = 0, well_name: str = '', well_size: int = 0, x: float = 0, y: float = 0, z: float = 0, h: float = 0) -> None:
        """
        Constructor
        """
    def add_region_list(self, arg0: RegionList) -> None:
        ...
    def get_region_list(self, arg0: str) -> RegionList:
        ...
    def h(self) -> float:
        """
        well's len (distance)
        """
    def region_list_exists(self, arg0: str) -> bool:
        ...
    def region_list_names(self) -> list[str]:
        ...
    def well_name(self) -> str:
        """
        well's name
        """
    def well_size(self) -> int:
        """
        well's size
        """
    def x(self) -> float:
        """
        well's x position
        """
    def y(self) -> float:
        """
        well's y position
        """
    def z(self) -> float:
        """
        well's z position
        """
class WellList:
    @typing.overload
    def __init__(self) -> None:
        ...
    @typing.overload
    def __init__(self, arg0: str) -> None:
        ...
    def add(self, arg0: Well) -> None:
        """
        Add well ot well list
        """
    def nbr_wells(self) -> int:
        ...
    def read(self, arg0: str) -> bool:
        ...
    def well(self, arg0: int) -> Well:
        ...
@typing.overload
def dtw_distance(well1: DataStore, well2: DataStore, name: str, norm: int = 1) -> float:
    """
    dtw_distance from DataStore/Well
    """
@typing.overload
def dtw_distance(data1: list[float], data2: list[float], norm: int = 1) -> float:
    """
    dtw_distance from lists
    """
def get_version() -> str:
    """
    Returns the WeCo version
    """
