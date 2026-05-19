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

#include <weco/dtw_distance.h>
#include "common.h"
#include <pybind11/stl.h>

using namespace pybind11::literals;

namespace WeCo {
    

//================================================
// Log
//==============================================

class _LogT : public Log {
public :
	void write(const std::string&s) override {
		py::gil_scoped_acquire aa;
		PYBIND11_OVERLOAD_PURE(void,Log,write,s);
	}
};

} // namespace WeCo


void def_misc(py::module_& m){
    m.def("get_version", &WeCo::get_version, "Returns the WeCo version");

    py::class_<WeCo::Log,WeCo::_LogT>(m,"Log","WeCo Log stream")
   	    .def(py::init<>(),"Constructor")
 	    .def("write",&WeCo::Log::write,"Write a string to the log")
	;


    // ===================== dtw_distance =======================================
    m.def("dtw_distance",static_cast<double (*)
            (const WeCo::DataStore&,const WeCo::DataStore&,const std::string& ,int)> (&WeCo::dtw_distance),
            "well1"_a,"well2"_a,"name"_a,"norm"_a=1,
                "dtw_distance from DataStore/Well");

    m.def("dtw_distance",static_cast<double (*)
            (const std::vector<WeCo::DataValue>&,const std::vector<WeCo::DataValue>&,int)> (&WeCo::dtw_distance),
            "data1"_a,"data2"_a,"norm"_a=1,
                "dtw_distance from lists");

    // ===================== plugins =======================================

	#ifdef GEN_PLUGIN
	m.def("load_plugin",&WeCo::load_plugin,"Load a plugin");
	#endif

}