# Association Scientifique pour la Geologie et ses Applications (ASGA)
#
# Copyright (c) 2024 ASGA. All Rights Reserved.
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

from weco.data import WellList, Well
from pathlib import Path
from statistics import stdev, mean
from itertools import chain
from typing import Union, Optional, List, Tuple, Callable, Any, Iterable

"""
Import data from csv, ....
"""


class Name2Int:
    """
    Translate name 2 integers. Each name will have the same value.


    """

    def __init__(self, start=0):
        """

        :param start: value of the first world
        """
        super().__init__()
        self.start = start
        self._dict = dict()

    def __call__(self, name: str) -> int:
        try:
            return self._dict[name]
        except KeyError:
            value = len(self._dict) + self.start
            self._dict[name] = value
            return value

    def lexicon(self) -> List[Tuple[str, int]]:
        return sorted(self._dict.items(), key=lambda x: x[1])


class DataImport:
    """
    Read data and add them to Well/WellList.

    columns parameter:
     * (0,int) to get column 0 as an integer
     * (2,float) to get column 2 as a float
     * (2,str) to get column 2 as a string

    default:
     * well name (well_name_col) : column 0
     * depth (depth_col) : column 1
    """

    #: well name column in data
    well_name_col = 0
    #: depth column
    depth_col = 1
    # index column (marker id in well)
    index_col = -1

    DataType = Union[str, int, float]
    DataLine = List[DataType]
    DataArray = List[DataLine]

    def __init__(self, data: Optional[Iterable[DataLine]] = None) -> None:
        self.data = [] if data is None else list(data)

    @classmethod
    def from_space_file(cls,
                        path: Union[str, Path],
                        *columns: Tuple[int, Callable[[str], Any]],
                        header: bool = False
                        ) -> "DataImport":
        """
        read data from space separated file

        :param path: file path
        :param columns: columns to read (num,converter/type)
        :param header: if True, ignore first line
        """

        data = cls()

        with Path(path).open() as f:
            if header:
                next(f)
            for line in f:
                line = line.strip()
                if not line:
                    continue
                line = line.split()
                data._import_line(line, columns)

        return data

    @classmethod
    def from_csv_file(cls,
                      path: Union[str, Path],
                      *columns: Tuple[int, Callable[[str], Any]],
                      header: Optional[bool] = None
                      ) -> "DataImport":
        """
        read data from csv file

        :param path: file path
        :param columns: columns to read (num,converter/type)
        :param header: if True, ignore first line, if None: autodetect
        """
        from csv import reader, Sniffer

        path = Path(path)
        with path.open() as f:
            sample = f.read(1024)
        dialect = Sniffer().sniff(sample)
        if header is None:
            header = Sniffer().has_header(sample)

        data = cls()

        with Path(path).open() as f:
            cvs_reader = reader(f, dialect=dialect)
            if header:
                next(cvs_reader)
            for line in cvs_reader:
                data._import_line(line, columns)

        return data

    def _import_line(self, line: List[str], columns: Tuple[Tuple[int, Callable[[str], Any]], ...]):
        res = list()
        for num, cvt in columns:
            try:
                value = line[num]
            except IndexError:
                raise ValueError(f'Column {num} not found in line {len(self.data)}')
            try:
                value = cvt(value)
            except ValueError:
                raise ValueError(
                    f'Column {num} / line {len(self.data)} ({value}) can\'t be converted with {cvt.__name__}')
            res.append(value)
        self.data.append(res)

    def __len__(self):
        return len(self.data)

    def __getitem__(self, item):
        return self.data[item]

    def __iter__(self):
        return iter(self.data)

    def __bool__(self):
        return bool(self.data)

    def nbr_columns(self) -> int:
        """ return number of columns """
        return len(self[0]) if self else 0

    def select(self, value: Any, column=0) -> "DataImport":
        """
        return a new DataImport object with data line[column] == value

        :return: a new DataImport
        """
        return self._copy(list(i) for i in self.data if i[column] == value)

    def _copy(self, data: Iterable[DataLine]) -> "DataImport":
        ret = self.__class__(data)
        ret.well_name_col = self.well_name_col
        ret.depth_col = self.depth_col
        ret.index_col = self.index_col
        return ret

    def sort(self, column: int = 0) -> "DataImport":
        """
        sort the data on a column

        :param column: column to sort
        :return: self
        """
        self.data.sort(key=lambda x: x[column])
        return self

    def dump(self) -> "DataImport":
        """
        Write data to screen
        """
        for line in self:
            print(', '.join(map(str, line)))
        return self

    def get_well(self, well_name: str, depth: Optional[List[float]] = None) -> "DataImport":
        """
        get all line about well_name (col[well_name_coll] == well_name)

        if depth is given, replace the well_name column with the index of the nearest value in depth

        the data will be sorted on depth or index

        :param well_name:
        :param depth:
        :return: A new DataImport object
        """
        ret = self.select(well_name, self.well_name_col)
        if depth is not None:
            ret.add_depth(depth)
        if ret.depth_col > 0:
            ret.sort(self.depth_col)
        elif ret.index_col > 0:
            ret.sort(self.index_col)
        return ret

    def add_depth(self, depth: List[float], depth_column: int = -1) -> "DataImport":
        """
        create index (marker id) column from depth list

        :param depth: depth values
        :param depth_column: depth column (default:self.depth_col)
        :return: self
        """
        if depth_column < 0:
            depth_column = self.depth_col

        for line in self.data:
            depth_value = line[depth_column]
            if depth_value <= depth[0]:
                index_value = 0
            elif depth_value >= depth[-1]:
                index_value = len(depth) - 1
            else:
                for n, v in enumerate(depth):
                    if v >= depth_value:
                        index_value = n
                        break
                else:
                    raise ValueError('Not Possible ???')
                if depth_value - depth[index_value - 1] < depth[index_value] - depth_value:
                    index_value -= 1
            line.append(index_value)
        # set self.index_column
        if len(self):
            self.index_col = len(self[0]) - 1
        return self

    def multiscale_valid(self, well_size: int) -> "DataImport":
        """
        Check if data is valid for multiscale

        check self.index_col and size

        :param well_size: well size (number of markers)
        :return: self
        :raise ValueError: if not
        """
        if len(self) < 2:
            raise ValueError('Multi-scale not supported (need 2 markers')
        self.sort(self.index_col)
        if self[0][self.index_col] != 0:
            raise ValueError('Multi-scale not supported (start != 0')
        if self[-1][self.index_col] != well_size - 1:
            raise ValueError('Multi-scale not supported (end != size-1')
        prev = -1
        for i in self:
            if prev == i[self.index_col]:
                raise ValueError('Multi-scale not supported (duplicate marker)')
        return self

    def create_multiscale_data(self, well_list: WellList, *data: Tuple[str, int], depth: str = "",
                               multiscale_region: str = "multiscale") -> "DataImport":
        """
        Create multi-scale data to a well list.

         * add multi scale region
         * add data

        :param well_list: well list
        :param data: (name,column) of data to add
        :param depth: optional depth property name (in Wells)
        :param multiscale_region: multi-scale region name

        """
        for well in well_list.wells:
            well_data = self.get_well(well.name, list(well.data[depth]) if depth else None)
            well_data.multiscale_valid(well.size).create_region_multiscale(well, multiscale_region)
            for name, column in data:
                well.add_data(name, list(i[column] for i in well_data))

        return self

    def create_region_from_name(self, well_list: WellList, region_name: str, column: int,
                                depth: str = "", first_region: int = 1, index_column: int = -1) -> "DataImport":
        region_num = Name2Int(first_region)
        for well in well_list.wells:
            well_data = self.get_well(well.name, list(well.data[depth]) if depth else None)
            if index_column < 0:
                index_column = well_data.index_col
                if index_column < 0:
                    raise ValueError('No index column')
            reg_data = list((region_num(i[column]), i[index_column]) for i in well_data)
            reg_data.append((0, well.size))
            reg_size = list(reg_data[i + 1][1] - reg_data[i][1] for i in range(len(reg_data) - 1))
            regions = list(i + (reg_size[n],) for n, i in enumerate(reg_data[:-1]) if reg_size[n] > 0)
            well.add_region(region_name, regions)
        return self

    def create_region_multiscale(self, well: Well, region_name: str, first_region: int = 0) -> "DataImport":
        column = self.index_col
        regions = list((self[n][column], self[n + 1][column] - self[n][column]) for n in range(len(self) - 1))
        regions = filter(lambda x: x[1] > 0, regions)
        well.add_region(region_name, list((n + first_region,) + i for n, i in enumerate(regions)))
        return self


if __name__ == '__main__':
    base_path = Path(__file__).parent.parent.parent.resolve() / "WeCoTest"
    markers = DataImport.from_space_file(
        base_path / "rawdata" / "WeCoTestSynth_Markers.csv",
        (0, str),  # Well Name
        (4, float),  # md as position
        (6, float),  # dip
        (7, float),  # Azimuth
        (5, str),  # Marker name
        header=True)
    wells = WellList(base_path / "wecodata" / "full_set2.wells.txt")

    markers.create_multiscale_data(wells, ("ms_dip", 2), ("ms_azimuth", 3), depth='DEPTH')
    markers.create_region_from_name(wells, "Markers", 4, depth="DEPTH")
    wells.write("test.wells.txt")
