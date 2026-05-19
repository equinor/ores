# Association Scientifique pour la Geologie et ses Applications (ASGA)
#
# Copyright (c) 2021 ASGA. All Rights Reserved.
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

""" RESQML (https://www.energistics.org/resqml-standards/) data access

Usefull clases:

* `ResqmlFile` : read RESQML file (.epc,.h5)
* `ContinuousProperty` : properties represented as an array of floats
* `WellboreFrameRepresentation`: Representation of a wellbore
* `StratigraphicColumn` : Stratigraphic Column

Print a list of  properties on WellboreFrameRepresentation:

.. code:: python

    resqml_file = ResqmlFile("path/file")
    resqml_file.dump_wellbore_properties()

Print depth and property values :

.. code:: python

    resqml_file = ResqmlFile("path/file")
    myprop = resqml_file.get_object("611dcab1-1a8d-49ef-8541-ce95aaddeb9a")

    well_rep = my_prop.get_supporting_representation()
    well_data = well.get_md_data()
    prop_data = prop.get_data()
    print("  Prop:", len(prop_data), prop_data)
    print("  MD  :", len(well_data), well_data)

"""

from typing import Union, Any, Tuple, Optional
# noinspection PyPep8Naming
import xml.etree.ElementTree as ET
from zipfile import ZipFile
from pathlib import Path
from fnmatch import fnmatch
import h5py

PathType = Union[str, Path]


# GlobalChronostratigraphicColumn

# === Exceptions ====
class ResqmlException(Exception):
    """
    Base class for exceptions
    """


class ResqmlNotFound(ResqmlException):
    """
    Object or data missing
    """


class EPCFile:
    def __init__(self, filename):
        self.file = ZipFile(filename)

    def list_files(self, pattern=None, object_only=True):
        def filter_file(name):
            if object_only and not name.startswith("obj_"):
                return False
            return pattern is None or fnmatch(name, pattern)

        return filter(filter_file, self.file.namelist())

    def get_file(self, filename):
        return self.file.open(filename)


class ResqmlContext:
    def get_data(self, _):
        return None

    def get_object(self, _):
        return None


class ResqmlBase:
    _namespaces = (
        ('oxmlct',
         'http://schemas.openxmlformats.org/package/2006/content-types'),
        ('xsi', "http://www.w3.org/2001/XMLSchema-instance"),
        ('eml', "http://www.energistics.org/energyml/data/commonv2"),
        ("resqml2", "http://www.energistics.org/energyml/data/resqmlv2"),
        ("resqml1", "http://www.resqml.org/schemas/1series"),
        ("xsd", "http://www.w3.org/2001/XMLSchema"),
    )

    short_ns_dict = dict((b, a) for a, b in _namespaces)
    long_ns_dict = dict((a, b) for a, b in _namespaces)

    _tag2class = dict()

    xml_tag = None

    ctx: ResqmlContext

    def __init__(self, ctx: ResqmlContext):
        self.ctx = ctx
        self.obj_init()

    @classmethod
    def from_file(cls, ctx: ResqmlContext, file):
        return cls.from_tree(ctx, ET.parse(file))

    @classmethod
    def from_tree(cls, ctx: ResqmlContext, tree: ET.ElementTree):
        return cls.from_element(ctx, tree.getroot())

    @classmethod
    def from_element(cls, ctx: ResqmlContext, element: ET.Element):
        obj = cls.empty(ctx)
        obj.read(element)
        return obj

    @classmethod
    def auto_from_file(cls, ctx: ResqmlContext, file):
        return cls.auto_from_tree(ctx, ET.parse(file))

    @classmethod
    def auto_from_tree(cls, ctx: ResqmlContext, tree: ET.ElementTree):
        return cls.auto_from_element(ctx, tree.getroot())

    @classmethod
    def auto_from_element(cls, ctx: ResqmlContext, element: ET.Element):
        object_class = cls.tag2class(element.tag)
        if object_class is None:
            raise ResqmlException(f"Unknown class {element.tag}")
        return object_class.from_element(ctx, element)

    @classmethod
    def auto_from_type(cls, ctx: ResqmlContext, element: ET.Element):
        xml_type = element.get(cls.long_ns("xsi:type"))
        if not xml_type:
            raise ResqmlException("Missing type")
        obj_type = cls.tag2class(cls.remove_ns(xml_type))
        if not obj_type:
            raise ResqmlException(f"Unknown type {xml_type}")
        return obj_type.from_element(ctx, element)

    @classmethod
    def tag2class(cls, ns):
        return cls._tag2class.get(cls.short_ns(ns))

    @classmethod
    def empty(cls, ctx):
        return cls(ctx)

    def obj_init(self):
        pass

    def read(self, element: ET.Element):
        raise ResqmlException("Read Not Implemented")

    @classmethod
    def tag_is(cls, elm: ET.Element, tag: str):
        return elm.tag == tag or cls.short_ns(elm.tag) == tag

    @classmethod
    def short_ns(cls, tag: str):
        if tag[:1] != '{':
            return tag
        ns, tag = tag.split('}', 1)
        return cls.short_ns_dict[ns[1:]] + ':' + tag

    @classmethod
    def long_ns(cls, tag: str):
        if ':' not in tag:
            return tag
        ns, tag = tag.split(':', 1)
        return '{' + cls.long_ns_dict[ns] + '}' + tag

    @staticmethod
    def remove_ns(tag: str):
        if ':' in tag:
            return tag.split(':')[-1]
        if '}' in tag:
            return tag.split('}')[-1]
        return tag

    @classmethod
    def ns_find(cls, elem, tag):
        return elem.find(tag, cls.long_ns_dict)

    @classmethod
    def ns_findall(cls, elem, tag):
        return elem.findall(tag, cls.long_ns_dict)

    @classmethod
    def read_sub_str(cls, elem: ET.Element, tag: str, convert=None,
                     default: Any = "", mandatory=True):
        elem = cls.ns_find(elem, tag)
        if elem is None:
            if mandatory:
                raise ResqmlException(f"Tag {tag} missing")
            else:
                return default
        return elem.text if convert is None else convert(elem.text)

    @classmethod
    def read_sub_int(cls, elem: ET.Element, tag: str, default=0,
                     mandatory=True):
        return cls.read_sub_str(elem, tag, int, default, mandatory)

    @classmethod
    def read_sub_float(cls, elem: ET.Element, tag: str, default=0,
                       mandatory=True):
        return cls.read_sub_str(elem, tag, float, default, mandatory)

    @classmethod
    def read_sub_bool(cls, elem: ET.Element, tag: str, default=False,
                      mandatory=True):
        def to_bool(x):
            return x.lower().strip() in ("1", "true")

        return cls.read_sub_str(elem, tag, to_bool, default, mandatory)

    def read_sub_ref(self, elem: ET.Element, tag: str, mandatory=True):
        elem = self.ns_find(elem, tag)
        if elem is None:
            if mandatory:
                raise ResqmlException(f"Tag {tag} missing")
            else:
                return None
        return DataObjectReference.from_element(self.ctx, elem)

    @classmethod
    def read_sub_coord(cls, elem: ET.Element, tag: str, nbr_coord=3):
        elem = cls.ns_find(elem, tag)
        return tuple(cls.read_sub_float(elem, "resqml2:Coordinate%i" % i)
                     for i in range(1, nbr_coord + 1))

    @classmethod
    def read_citation(cls, elem: ET.Element) -> dict:
        if not cls.tag_is(elem, "eml:Citation"):
            elem = cls.ns_find(elem, "eml:Citation")
            if not elem:
                return dict()
        res = dict()
        for child in elem:
            res[child.tag.split("}")[-1]] = child.text

        return res

    @classmethod
    def read_extra_metadata(cls, elem: ET.Element) -> dict:
        res = dict()
        for child in cls.ns_findall(elem, "resqml2:ExtraMetadata"):
            res[cls.ns_find(child, "resqml2:Name").text] = (
                cls.ns_find(child, "resqml2:Value").text)
        return res

    @classmethod
    def register(cls, tag=None):
        cls._tag2class[tag or cls.xml_tag] = cls

    def get(self):
        return self

    @classmethod
    def _dump_start(cls, level, *__args, **__kwargs):
        if level > 0:
            print("| " * (level - 1) + '+-', end="")

        print(*__args, **__kwargs)

    @classmethod
    def _dump_sub(cls, level, *__args, **__kwargs):
        print("| " * level + '|', *__args, **__kwargs)

    @classmethod
    def _dump_ref_str(cls, ref: Optional["DataObjectReference"]):
        if not ref:
            return 'None'
        return f'{ref.get_ref_class()} {ref.uuid} {ref.title}'


class EPCContent(ResqmlBase):
    filename = '[Content_Types].xml'

    defaults: list
    overrides: dict

    xml_tag = "oxmlct:Types"

    def obj_init(self):
        self.defaults = list()
        self.overrides = dict()

    def read(self, elem: ET.Element):
        assert self.tag_is(elem, self.xml_tag)
        for child in elem:
            if self.tag_is(child, "oxmlct:Override"):
                self.overrides[child.get("PartName")] = child.get(
                    "ContentType")
            elif self.tag_is(child, "oxmlct:Default"):
                self.defaults.append(
                    (child.get("Extension"), child.get("ContentType")))

    def get_type(self, filename):
        if filename in self.overrides:
            return self.overrides[filename]
        for ext, content_type in self.defaults:
            if filename.endswith("." + ext):
                return content_type
        return None


# ========================= Data Values ===========================

class Hdf5Dataset(ResqmlBase):
    path_in_hdf_file: str
    hdf_proxy = None

    def read(self, element: ET.Element):
        self.path_in_hdf_file = self.ns_find(
            element, "eml:PathInHdfFile").text.strip()
        self.hdf_proxy = self.read_sub_ref(element, "eml:HdfProxy")


class AbstractValueArray(ResqmlBase):
    def get_data(self):
        return None


class AbstractDoubleArray(AbstractValueArray):
    pass


class DoubleHdf5Array(AbstractDoubleArray):
    values: Hdf5Dataset = None

    def read(self, element: ET.Element):
        self.values = Hdf5Dataset.from_element(
            self.ctx, self.ns_find(element, "resqml2:Values"))

    def get_data(self):
        return self.ctx.get_data(self.values.path_in_hdf_file)


DoubleHdf5Array.register("DoubleHdf5Array")


class AbstractIntegerArray(AbstractValueArray):
    pass


class IntegerHdf5Array(AbstractIntegerArray):
    values: Hdf5Dataset = None
    null_value: int

    def read(self, element: ET.Element):
        self.values = Hdf5Dataset.from_element(
            self.ctx, self.ns_find(element, "resqml2:Values"))
        self.null_value = self.read_sub_int(element, "resqml2:NullValue")

    def get_data(self):
        return self.ctx.get_data(self.values.path_in_hdf_file)


IntegerHdf5Array.register("IntegerHdf5Array")


class DoubleLatticeArray(AbstractDoubleArray):
    start_value: float
    offsets: tuple

    def read(self, element: ET.Element):
        self.start_value = float(
            self.ns_find(element, "resqml2:StartValue").text)
        self.offsets = tuple(
            (float(self.ns_find(i, "resqml2:Value").text),
             int(self.ns_find(i, "resqml2:Count").text))
            for i in self.ns_findall(element, "resqml2:Offset")
        )

    def get_data(self):
        res = [self.start_value]
        cur = self.start_value
        for value, count in self.offsets:
            for _ in range(count):
                cur += value
                res.append(cur)
        return res


DoubleLatticeArray.register("DoubleLatticeArray")


# ===================== base objets ===============================
class DataObjectReference(ResqmlBase):
    """ RESQML2 DataObjectReference object

    reference to an object

    * content_type(str) : MIME Type
    * title (str)
    * uuid (str)
    * uuid_authority (str)
    * version_string (str)

    """

    content_type: str = ""
    title: str = ""
    uuid: str = ""
    uuid_authority: str = ""
    version_string: str = ""

    def read(self, element: ET.Element):
        self.content_type = self.read_sub_str(element, "eml:ContentType")
        self.title = self.read_sub_str(element, "eml:Title")
        self.uuid = self.read_sub_str(element, "eml:UUID")
        self.uuid_authority = self.read_sub_str(element, "eml:UuidAuthority")
        self.version_string = self.read_sub_str(element, "eml:VersionString")

    def get(self):
        return self.ctx.get_object(self.uuid)

    def object_type_is(self, object_type):
        return self.content_type.endswith("type=obj_" + object_type)

    def get_ref_class(self):
        ct = self.content_type.rsplit(";", 1)[-1][9:]
        return ct


class AbstractCitedDataObject(ResqmlBase):
    # schemaVersion string
    # Aliases ObjectAlias
    # CustomData CustomData
    uuid: str = None
    citation: dict

    def read(self, elem: ET.Element):
        assert self.tag_is(elem, self.xml_tag)
        self.uuid = elem.get("uuid")
        self.citation = self.read_citation(elem)

    def get_title(self):
        return self.citation.get("Title")

    def dump(self, level=0):
        self._dump_start(level, self.__class__.__name__, self.uuid,
                         self.get_title())


class AbstractResqmlDataObject(AbstractCitedDataObject):
    extra_metadata: dict

    def read(self, elem: ET.Element):
        AbstractCitedDataObject.read(self, elem)
        self.extra_metadata = self.read_extra_metadata(elem)


class AbstractRepresentation(AbstractResqmlDataObject):
    represented_interpretation = None

    def read(self, elem: ET.Element):
        AbstractResqmlDataObject.read(self, elem)
        self.represented_interpretation = self.read_sub_ref(
            elem, "resqml2:RepresentedInterpretation", mandatory=False)


class AbstractFeatureInterpretation(AbstractResqmlDataObject):
    interpreted_feature = None
    domain: str = ""

    def read(self, elem: ET.Element):
        AbstractResqmlDataObject.read(self, elem)
        self.interpreted_feature = self.read_sub_ref(
            elem, "resqml2:InterpretedFeature")
        self.domain = self.read_sub_str(elem, "resqml2:Domain")

    # HasOccuredDuring TimeInterval 0..1

    def get_interpreted_feature(self):
        return self.interpreted_feature.get()


class AbstractFeature(AbstractResqmlDataObject):
    pass


class AbstractTechnicalFeature(AbstractFeature):
    pass


class AbstractGeologicFeature(AbstractFeature):
    pass


class OrganizationFeature(AbstractGeologicFeature):
    xml_tag = "resqml2:OrganizationFeature"

    #: "earth model" or "fluid"
    organization_kind: str

    def read(self, elem: ET.Element):
        super().read(elem)
        self.organization_kind = self.read_sub_str(
            elem, "resqml2:OrganizationKind")


OrganizationFeature.register()


# =================== Well objects =====================

class WellboreFrameRepresentation(AbstractRepresentation):
    """ RESQML2 WellboreFrameRepresentation object

    * node_count(int) : number of noded
    * node_md(`AbstractDoubleArray`) : measured depth for each nodes
    * get_md_data() (float array) : measured depth as float array
    * trajectory : pointer to `WellboreTrajectoryRepresentation` object
    * represented_interpretation : pointer to `WellboreInterpretation`
    * extra_metadata (dict str->str) : extra meta data
    * uuid(str) :  object identifier
    * get_title()(str) : Citation Title
    * citation(dict) : Citation object as dict (Title,Originator,Creation,
        Format)
    """

    xml_tag = "resqml2:WellboreFrameRepresentation"

    node_count: int
    node_md: AbstractDoubleArray
    trajectory: DataObjectReference

    def read(self, elem: ET.Element):
        AbstractRepresentation.read(self, elem)
        self.extra_metadata = self.read_extra_metadata(elem)
        self.node_count = int(self.ns_find(elem, "resqml2:NodeCount").text)
        self.node_md = self.auto_from_type(
            self.ctx, self.ns_find(elem, "resqml2:NodeMd"))
        self.trajectory = self.read_sub_ref(elem, "resqml2:Trajectory")

        # WitsmlLogReference ???

    # IntervalStratigraphiUnits IntervalStratigraphicUnits 0..1
    # CellFluidPhaseUnits CellFluidPhaseUnits 0..1
    def get_md_data(self):
        return self.node_md.get_data()


WellboreFrameRepresentation.register()


class WellboreInterpretation(AbstractFeatureInterpretation):
    xml_tag = "resqml2:WellboreInterpretation"

    is_drilled: bool = False

    def read(self, elem: ET.Element):
        AbstractFeatureInterpretation.read(self, elem)
        self.is_drilled = self.read_sub_bool(elem, "resqml2:IsDrilled")

    # IsDrilled boolean


WellboreInterpretation.register()


class WellboreFeature(AbstractTechnicalFeature):
    xml_tag = "resqml2:WellboreFeature"


WellboreFeature.register()


class MdDatum(AbstractResqmlDataObject):
    xml_tag = "resqml2:MdDatum"
    md_reference: str
    location: tuple
    local_crs = None

    def read(self, elem: ET.Element):
        super().read(elem)
        self.location = self.read_sub_coord(elem, "resqml2:Location")
        self.md_reference = self.read_sub_str(elem, "resqml2:MdReference")
        self.local_crs = self.read_sub_ref(elem, "resqml2:LocalCrs")


MdDatum.register()


class WellboreTrajectoryRepresentation(AbstractRepresentation):
    xml_tag = "resqml2:WellboreTrajectoryRepresentation"

    start_md: float
    finish_md: float
    md_uom: str
    md_domain: str
    md_datum: None

    def read(self, elem: ET.Element):
        super().read(elem)
        self.start_md = self.read_sub_float(elem, "resqml2:StartMd")
        self.finish_md = self.read_sub_float(elem, "resqml2:FinishMd")
        self.md_uom = self.read_sub_str(elem, "resqml2:MdUom")
        self.md_domain = self.read_sub_str(elem, "resqml2:MdDomain",
                                           mandatory=False)
        self.md_datum = self.read_sub_ref(elem, "resqml2:MdDatum")

    def get_md_datum(self):
        return self.md_datum.get()

        # Geometry AbstractParametricLineGeometry 0..1
        # DeviationSurvey DeviationSurveyRepresentation 0..1
        # ParentIntersection WellboreTrajectoryParentIntersection 0..1


WellboreTrajectoryRepresentation.register()


class WellboreMarker(AbstractResqmlDataObject):
    xml_tag = "resqml2:WellboreMarker"

    geologic_boundary_kind: str

    def read(self, elem: ET.Element):
        super().read(elem)
        self.geologic_boundary_kind = self.read_sub_str(
            elem, "resqml2:GeologicBoundaryKind")

    # FluidMarker FluidMarker
    # FluidContact FluidContact
    # WitsmlFormationMarker DataObjectReference


class WellboreMarkerFrameRepresentation(WellboreFrameRepresentation):
    xml_tag = "resqml2:WellboreMarkerFrameRepresentation"
    wellbore_markers: Tuple[WellboreMarker]

    def read(self, elem: ET.Element):
        super().read(elem)
        self.wellbore_markers = tuple(
            WellboreMarker.from_element(self.ctx, wm_elem)
            for wm_elem in self.ns_findall(elem, "resqml2:WellboreMarker")
        )

    def dump_markers(self):
        """
        print markers depth and title
        """
        # noinspection PyTypeChecker
        for md, marker in zip(self.node_md.get_data(), self.wellbore_markers):
            print(md, marker.get_title())


WellboreMarkerFrameRepresentation.register()


# ===================== Properties =================================
class AbstractProperty(AbstractResqmlDataObject):
    count: int
    indexable_element: str
    supporting_representation = None
    realization_index: int
    time_step: int

    def read(self, elem: ET.Element):
        super().read(elem)
        self.count = self.read_sub_int(elem, "resqml2:Count")
        self.time_step = self.read_sub_int(
            elem, "resqml2:TimeStep", mandatory=False)
        self.realization_index = self.read_sub_int(
            elem, "resqml2:RealizationIndex", mandatory=False)
        self.indexable_element = self.read_sub_str(
            elem, "resqml2:IndexableElement")
        self.supporting_representation = self.read_sub_ref(
            elem, "resqml2:SupportingRepresentation")
        # TimeIndex TimeIndex 0..1
        # LocalCrs AbstractLocal3dCrs 0..1
        # PropertyKind AbstractPropertyKind 1..1

    def get_supporting_representation(self):
        return self.supporting_representation.get()


class PatchOfValues(ResqmlBase):
    representation_patch_index: int
    values = None

    def read(self, elem: ET.Element):
        self.representation_patch_index = self.read_sub_int(
            elem, "resqml2:RepresentationPatchIndex")
        self.values = self.auto_from_type(
            self.ctx, self.ns_find(elem, "resqml2:Values"))


class AbstractValuesProperty(AbstractProperty):
    patch_of_values: Tuple[PatchOfValues]

    def read(self, elem: ET.Element):
        super().read(elem)
        self.patch_of_values = tuple(
            PatchOfValues.from_element(self.ctx, i)
            for i in self.ns_findall(elem, "resqml2:PatchOfValues")
        )

        # Facet PropertyKindFacet 0..*

    def get_data(self):
        if len(self.patch_of_values) == 1:
            return self.patch_of_values[0].values.get_data()
        return tuple(
            i.values.get_data()
            for i in self.patch_of_values
        )


class ContinuousProperty(AbstractValuesProperty):
    """ RESQML2 ContinuousProperty object

    * minimum_value (float) : minimum of property
    * maximum_value (float) : maximum of property
    * uom(str) : property unit
    * get_data() (float array) : property values
    * count (int) : number of elements
    * get_supporting_representation() : property support class (
       `WellboreFrameRepresentation` for example)
    *  extra_metadata (dict str->str) : extra meta data
    * uuid(str) :  object identifier
    * get_title()(str) : Citation Title
    * citation(dict) : Citation object as dict (Title,Originator,Creation,
        Format)
    """

    xml_tag = "resqml2:ContinuousProperty"
    minimum_value: float
    maximum_value: float
    uom: str

    def read(self, elem: ET.Element):
        super().read(elem)
        self.minimum_value = self.read_sub_float(elem, "resqml2:MinimumValue")
        self.maximum_value = self.read_sub_float(elem, "resqml2:MaximumValue")
        self.uom = self.read_sub_str(elem, "resqml2:UOM")


ContinuousProperty.register()


class DiscreteProperty(AbstractValuesProperty):
    xml_tag = "resqml2:DiscreteProperty"
    minimum_value: float
    maximum_value: float
    uom: str

    def read(self, elem: ET.Element):
        super().read(elem)
        self.minimum_value = self.read_sub_int(elem, "resqml2:MinimumValue")
        self.maximum_value = self.read_sub_int(elem, "resqml2:MaximumValue")


DiscreteProperty.register()


# ================= StratigraphicColumn

class StratigraphicColumn(AbstractResqmlDataObject):
    """ RESQML2 StratigraphicColumn object

    * ranks:list of ref to `StratigraphicColumnRankInterpretation`
    * extra_metadata (dict str->str) : extra meta data
    * uuid(str) :  object identifier
    * get_title()(str) : Citation Title
    * citation(dict) : Citation object as dict (Title,Originator,Creation,
        Format)

    use `dump` to view it
    """

    xml_tag = "resqml2:StratigraphicColumn"
    ranks: Tuple[DataObjectReference]

    def read(self, elem: ET.Element):
        super().read(elem)
        self.ranks = tuple(
            DataObjectReference.from_element(self.ctx, i)
            for i in self.ns_findall(elem, "resqml2:Ranks")
        )

    def get_ranks(self) -> Any:
        """
        :return: ranks objects as `StratigraphicColumnRankInterpretation`
        """
        return (i.get() for i in self.ranks)

    def dump(self, level=0):
        """ Show instance content """

        super().dump(level)
        for i in self.get_ranks():
            i.dump(level + 1)


StratigraphicColumn.register()


class AbstractOrganizationInterpretation(AbstractFeatureInterpretation):
    # ContactInterpretation AbstractContactInterpretationPart 0..*

    contact_interpretation: tuple

    def read(self, elem: ET.Element):
        super().read(elem)
        self.contact_interpretation = tuple(
            self.auto_from_type(self.ctx, i)
            for i in self.ns_findall(elem, "resqml2:ContactInterpretation")
        )


# @formatter:off
class AbstractStratigraphicOrganizationInterpretation(
        AbstractOrganizationInterpretation):
    # @formatter:on
    ordering_criteria: str

    def read(self, elem: ET.Element):
        super().read(elem)
        self.ordering_criteria = self.read_sub_str(elem,
                                                   "resqml2:OrderingCriteria")


class GeologicUnitInterpretation(AbstractFeatureInterpretation):
    pass
    # GeologicUnitComposition GeologicUnitComposition
    # GeologicUnitMaterialImplacement GeologicUnitMaterialImplacement


class StratigraphicUnitInterpretation(GeologicUnitInterpretation):
    xml_tag = "resqml2:StratigraphicUnitInterpretation"
    # DepositionMode DepositionMode
    # MaxThickness LengthMeasure
    # MinThickness LengthMeasure


StratigraphicUnitInterpretation.register()


class StratigraphicUnitInterpretationIndex(ResqmlBase):
    index: int
    unit: DataObjectReference

    def read(self, element: ET.Element):
        self.index = self.read_sub_int(element, "resqml2:Index")
        self.unit = self.read_sub_ref(element, "resqml2:Unit")

    def get_unit(self) -> Any:
        return self.unit.get()


# @formatter:off
class StratigraphicColumnRankInterpretation(
        AbstractStratigraphicOrganizationInterpretation):
    # @formatter:on
    """ RESQML2 StratigraphicColumnRankInterpretation object

    * index (int) : index
    * stratigraphic_units: tuple of `StratigraphicUnitInterpretationIndex`
    * ordering_criteria (str) :
    * interpreted_feature (ref To `AbstractFeature`)
    * domain (str)
    * contact_interpretation (Tuple of `AbstractContactInterpretationPart`):
        0..*
    * extra_metadata (dict str->str) : extra meta data
    * uuid(str) :  object identifier
    * get_title()(str) : Citation Title
    * citation(dict) : Citation object as dict (Title,Originator,Creation,
        Format)
    """

    xml_tag = "resqml2:StratigraphicColumnRankInterpretation"
    index: int
    stratigraphic_units: Tuple[StratigraphicUnitInterpretationIndex]

    def read(self, elem: ET.Element):
        super().read(elem)
        self.index = self.read_sub_int(elem, "resqml2:Index")

        self.stratigraphic_units = tuple(
            StratigraphicUnitInterpretationIndex.from_element(self.ctx, i)
            for i in self.ns_findall(elem, "resqml2:StratigraphicUnits")
        )

    def dump(self, level=0):
        super().dump(level)
        self._dump_sub(level, f"domain={self.domain}", f"index={self.index}",
                       f"ordering_criteria={self.ordering_criteria}")
        self._dump_sub(level, "interpreted_feature:",
                       self._dump_ref_str(self.interpreted_feature))
        self._dump_start(level + 1, "stratigraphic_units:")
        for i in self.stratigraphic_units:
            self._dump_start(level + 2, i.index, self._dump_ref_str(i.unit))
        self._dump_start(level + 1, "contact_interpretation:")
        for i in self.contact_interpretation:
            i.dump(level + 2)


StratigraphicColumnRankInterpretation.register()


class AbstractContactInterpretationPart(ResqmlBase):
    """RESQML2 AbstractContactInterpretationPart object

    base class of `BinaryContactInterpretationPart`

    """
    index: int
    contact_relationship: str
    part_of: Optional[DataObjectReference] = None

    def read(self, elem: ET.Element):
        self.index = self.read_sub_int(elem, "resqml2:Index")
        self.contact_relationship = self.read_sub_str(
            elem, "resqml2:ContactRelationship")
        self.part_of = self.read_sub_ref(elem, "resqml2:PartOf",
                                         mandatory=False)

    def get_part_of(self):
        return self.part_of.get() if self.part_of else None

    def dump(self, level=0):
        self._dump_start(level, self.__class__.__name__, f'index={self.index}')
        self._dump_sub(level,
                       f"contact_relationship={self.contact_relationship}")
        self._dump_sub(level, "part_of:", self._dump_ref_str(self.part_of))


class ContactElementReference(DataObjectReference):
    """ RESQML2 ContactElementReference object

    `DataObjectReference` + `qualifier` + `secondary_qualifier`

    * secondary_qualifier (str) : Contact Mode
    * qualifier (str) : Contact Side
    * content_type(str) : MIME Type
    * title (str)
    * uuid (str)
    * uuid_authority (str)
    * version_string (str)

    """
    #: ContactMode
    secondary_qualifier: str
    #: ContactSide
    qualifier: str

    def read(self, element: ET.Element):
        super().read(element)
        self.secondary_qualifier = self.read_sub_str(
            element, "resqml2:SecondaryQualifier")
        self.qualifier = self.read_sub_str(
            element, "resqml2:Qualifier")

    def sub_dump(self, level, title):
        self._dump_start(level, title, self._dump_ref_str(self))
        self._dump_sub(level, f'qualifier={self.qualifier}',
                       f"secondary_qualifier={self.secondary_qualifier}")


class BinaryContactInterpretationPart(AbstractContactInterpretationPart):
    """RESQML2 BinaryContactInterpretationPart object

    * direct_object: ContactElementReference
    * subject (`ContactElementReference`)
    * verb (str)
    * direct_objet (`ContactElementReference`)
    * index (int)
    * part_of (ref)


    """
    direct_object: ContactElementReference
    subject: ContactElementReference
    verb: str

    def read(self, elem: ET.Element):
        super().read(elem)
        self.direct_object = ContactElementReference.from_element(
            self.ctx, self.ns_find(elem, "resqml2:DirectObject"))
        self.subject = ContactElementReference.from_element(
            self.ctx, self.ns_find(elem, "resqml2:Subject"))
        self.verb = self.read_sub_str(elem, "resqml2:Verb")

    def dump(self, level=0):
        super().dump(level)
        self.subject.sub_dump(level + 1, "subject:")
        self._dump_sub(level, "verb:", self.verb)
        self.direct_object.sub_dump(level + 1, "direct_objet:")


BinaryContactInterpretationPart.register("BinaryContactInterpretationPart")


# ==================== ResqmlFile ====================================


class ResqmlFile(ResqmlContext):
    hdf5_path: Path
    epc_path: Path

    _hdf5_file: h5py.File = None
    _epc_file: EPCFile = None

    _objects: dict

    @property
    def epc_file(self) -> EPCFile:
        if self._epc_file is None:
            self._epc_file = EPCFile(self.epc_path)
        return self._epc_file

    @property
    def hdf5_file(self) -> h5py.File:
        if self._hdf5_file is None:
            self._hdf5_file = h5py.File(self.hdf5_path, "r")
        return self._hdf5_file

    def __init__(self, path: PathType):
        """ RESQML file (.epc +.h5)

        :param path: path to file (without extension)
        """
        path = str(Path(path).resolve())
        self.hdf5_path = Path(path + '.h5')
        self.epc_path = Path(path + '.epc')
        self._objects = dict()

    def list_files(self, object_type=None, uuid=None):
        """ list file in the .epc file

        :param object_type: object type (accept joker)
        :param uuid: object uuid
        :return: an iterator on file names
        """
        if object_type is None:
            if uuid is None:
                return self.epc_file.list_files()
            return self.epc_file.list_files("obj_*_" + uuid + '.xml')
        elif uuid is None:
            return self.epc_file.list_files("obj_" + object_type + '_*.xml')
        return self.epc_file.list_files(
            "obj_" + object_type + '_' + uuid + '.xml')

    def read_object(self, *, filename=None, uuid=None, object_type=None):
        """
        Read an object from the file. You must give a filename or an uuid.

        :raise ResqmlNotFound: if there is O or more than 1 object is found

        :param filename: object filename
        :param uuid: object uuid
        :param object_type: object class (auto detected if None)
        :return: object instance
        """
        assert filename or uuid
        if not filename:
            # search filename from uuid
            search = list(self.list_files(uuid=uuid))
            if len(search) == 0:
                raise ResqmlNotFound(f"uuid {uuid} not found")
            elif len(search) > 1:
                raise ResqmlNotFound(f"Too many files with id {uuid}")
            filename = search[0]
        if object_type is None:
            return ResqmlBase.auto_from_file(
                self, self.epc_file.get_file(filename))
        return object_type.from_file(self, self.epc_file.get_file(filename))

    def get_data(self, dataname):
        return self.hdf5_file[dataname][...]

    def get_object(self, uuid):
        """return an object from is uuid

        :raise ResqmlNotFound: if there is no object with this uuid
        """
        uuid = uuid.lower()
        if uuid in self._objects:
            return self._objects[uuid]
        obj = self.read_object(uuid=uuid)
        self._objects[uuid] = obj
        return obj

    def objects_by_type(self, object_type: str):
        """ List objects with type object_type

        :param object_type: type of objects listed ("ContinuousProperty" for
            example)
        :return: a generator
        """
        return (
            self.read_object(filename=filename)
            for filename in self.list_files(object_type)
        )

    def dump_objects(self, object_type: str):
        """print object uuid and title with type object_type"""
        for i in self.objects_by_type(object_type):
            print(i.uuid, i.get_title())

    def wellbore_properties(self):
        """
        :return: list `ContinuousProperty` on Wellbore (generator)
        """
        return (
            i for i in self.objects_by_type('ContinuousProperty')
            if i.supporting_representation.
        object_type_is("WellboreFrameRepresentation")
        )

    def dump_wellbore_properties(self):
        """
        write property uuid,property title and wellbore frame representation
        title
        """
        for i in self.wellbore_properties():
            print(i.uuid, i.get_title(), i.supporting_representation.title)
