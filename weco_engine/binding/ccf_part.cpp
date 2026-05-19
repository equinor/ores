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

#include "ccf_part.h"
    
void def_ccf_part(py::module_& m){

    //========================= CCFPart =================================
    py::class_<WeCo::_PyCCFPart,WeCo::_PyCCFPartT>(m,"CCFPart")
    	.def(py::init<>())
        DEF(_PyCCFPart,dest_cost,"Simplified cost function including only destination, to compute for all wells \n\n:return: (ok,cost)")
        DEF(_PyCCFPart,full_cost,"Full transition cost function including origin and destination, to compute for all wells \n\n:return: (ok,cost)")
        DEF(_PyCCFPart,dest_only,"Tells whether the full or simplified transition cost is used \n\
            \n:return: True if `dest_cost` must be used or False if it's `full_cost`")
        DEF(_PyCCFPart,init,"init hook")

        DEF(_PyCCFPart,init_done,":return: True if the context is defined")


        DEF(_PyCCFPart,well,"Well access")

        DEF(_PyCCFPart,size,":return: number of wells  = `size1` + `size1`")
        DEF(_PyCCFPart,size1,":return: number of wells in first part")
        DEF(_PyCCFPart,size2,":return: number of wells in second part")

		DEF(_PyCCFPart,src,"Source Marker id")
		DEF(_PyCCFPart,dest,"Destination Marker id")
		DEF(_PyCCFPart,same,"True if gap")

		DEF(_PyCCFPart,parent_cost1,"Cost of first parent corelation")
		DEF(_PyCCFPart,parent_cost2,"Cost of second parent corelation")


    ;
}
