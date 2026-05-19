/*

Association Scientifique pour la Geologie et ses Applications (ASGA)

Copyright (c) 2018 ASGA. All Rights Reserved.

This program is a Trade Secret of the ASGA and it is not to be:
 * reproduced, published, or disclosed to other,
 * distributed or displayed,
 * used for purposes or on Sites other than described in the GOCAD Advancement Agreement,
   without the prior written authorization of the ASGA.

Licencee agrees to attach or embed this Notice on all copies of the program,
including partial copies or modified versions thereof.

*/

#include "common.h"


//============= some helping macro
#define INCDEF(NAME) \
	void def_ ## NAME(py::module_& ); \
	def_ ## NAME(m);



PYBIND11_MODULE(engine, m) {
    m.doc() = "WeCo Python Bindings";

 
	INCDEF(data)
	INCDEF(misc)
	INCDEF(option)
	INCDEF(cost_function)
	INCDEF(ccf_part)
	INCDEF(project)

};

