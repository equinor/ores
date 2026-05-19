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
#pragma once

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/iostream.h>

namespace py = pybind11;


#define DEF(CCC,FUNC,DOC) .def(#FUNC,&WeCo::CCC::FUNC,DOC)
#define DEF_REPR(CCC,VVV) inline std::string py_repr(const CCC &o) { return std::string("<" #CCC " ")+VVV+">";};
#define REPR(CCC) .def("__repr__",[](const WeCo::CCC& obj)->std::string{return py_repr(obj);})