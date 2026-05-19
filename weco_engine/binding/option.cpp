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
#include <weco/option.h>
#include "common.h"

using namespace pybind11::literals;

namespace WeCo {}
    



void def_option(py::module_& m){
    //========================= Option =================================
	py::class_<WeCo::Option>(m,"Option")
		DEF(Option,type,"")
		DEF(Option,name,"")
		DEF(Option,string,"")
		DEF(Option,set,"")
		DEF(Option,name,"") 
		DEF(Option,info,"")
		DEF(Option,desc,"")
		DEF(Option,option_list,"")
		.def_static("sorted_list",&WeCo::Option::sorted_list,py::return_value_policy::reference)
		.def_static("list",&WeCo::Option::list,py::return_value_policy::reference)
		.def_static("search",&WeCo::Option::search,py::return_value_policy::reference)
		.def_static("exists",&WeCo::Option::exists)
	;

    //========================= OptionParser =================================
    py::class_<WeCo::OptionParser>(m,"OptionParser")
        .def(py::init<>())

		DEF(OptionParser,option_exists,"")
		DEF(OptionParser,set_option_value,"")
		DEF(OptionParser,get_option_value,"")
		DEF(OptionParser,reset_options,"Set all options to default value")
		.def("search_option",&WeCo::OptionParser::search_option,py::return_value_policy::reference)

		DEF(OptionParser,option_load,"load options from file")
	;

}
