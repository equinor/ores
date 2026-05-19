/*
Association Scientifique pour la Geologie et ses Applications (ASGA)

Copyright (c) 2024 ASGA. All Rights Reserved.

This program is a Trade Secret of the ASGA and it is not to be:
 * reproduced, published, or disclosed to other,
 * distributed or displayed,
 * used for purposes or on Sites other than described in the GOCAD Advancement Agreement,
   without the prior written authorization of the ASGA.

Licencee agrees to attach or embed this Notice on all copies of the program,
including partial copies or modified versions thereof.

*/
#include <weco.h>
#include "common.h"


namespace WeCo {


DEF_REPR(RegionList::Region,
		std::to_string(o.id)+" : "
		+ std::to_string(o.start)+"-"
		+std::to_string(o.start+o.length)
)


} // namespace WeCo


void def_data(py::module_& m){

    //========================= Data ======================================
    py::class_<WeCo::DataStore::Data>(m,"DataStore_Data")
    	DEF(DataStore::Data,name,"Data name")
    	DEF(DataStore::Data,size,"Data size")
    	DEF(DataStore::Data,get,"get value")
    	DEF(DataStore::Data,data,"get all values")
	;

    py::class_<WeCo::DataStore>(m,"DataStore")
	    .def("get_data",&WeCo::DataStore::get_data)
		.def("add_data",(void (WeCo::DataStore::*)(const std::string&,const std::vector<WeCo::DataValue>&))&WeCo::DataStore::add_data)
		DEF(DataStore,data_exists,"True if data exists")
		DEF(DataStore,data_names,"List of data names")
	;



    //===================== Regions ===================================

    py::class_<WeCo::RegionList::Region>(m,"RegionList_Region")
    		.def_readonly("id",&WeCo::RegionList::Region::id,"Region id")
    		.def_readonly("start",&WeCo::RegionList::Region::start,"Region start")
    		.def_readonly("length",&WeCo::RegionList::Region::length,"Region length")
			DEF(RegionList::Region,is_in,"return True if value is in region")
			REPR(RegionList::Region)
	;

    py::class_<WeCo::RegionList>(m,"RegionList")
			.def(py::init<const std::string &>())
    		DEF(RegionList,name,"Region List Name")
			.def("get_region",&WeCo::RegionList::get_region,py::arg("value"),py::arg("default")=0,"Return region id for value")
			DEF(RegionList,regions,"Return all regions")
			DEF(RegionList,add,"Add a new region (id,start,length)")
	;


   //========================== Well ======================================
    py::class_<WeCo::Well,WeCo::DataStore>(m,"Well")
     
		.def(py::init<WeCo::WellId,const std::string &,unsigned,WeCo::DataValue,WeCo::DataValue,WeCo::DataValue,WeCo::DataValue>()
			,"Constructor",py::arg("well_id")=0,py::arg("well_name")="",py::arg("well_size")=0,py::arg("x")=0,py::arg("y")=0,py::arg("z")=0,py::arg("h")=0)
        DEF(Well,well_name,"well's name")
        DEF(Well,well_size,"well's size")
        DEF(Well,x,"well's x position")
        DEF(Well,y,"well's y position")
        DEF(Well,z,"well's z position")
        DEF(Well,h,"well's len (distance)")

		DEF(Well,add_region_list,"")
		DEF(Well,region_list_names,"")
		DEF(Well,region_list_exists,"")
		.def( "get_region_list",(const WeCo::RegionList & (WeCo::Well::*)(const std::string&) const)&WeCo::Well::get_region_list)
	;

    //========================== Well List ======================================
    py::class_<WeCo::WellList>(m,"WellList")
    	.def(py::init<>())
    	.def(py::init<const std::string&>())

		.def("read",(bool(WeCo::WellList::*)(const std::string&))&WeCo::WellList::read)

		DEF(WellList,nbr_wells,"")

		.def("well",[](WeCo::WellList & wl,WeCo::WellId id)->WeCo::Well&{return *(wl.well(id)); })
		DEF(WellList,add,"Add well ot well list")
	;



};