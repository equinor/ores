
cmake_minimum_required(VERSION 3.12)
Project(WeCo)
# Read version from pyproject.toml (single source of truth)
file(READ "pyproject.toml" _pyproject_content)
string(REGEX MATCH "version = '([0-9]+\\.[0-9]+\\.[0-9]+)'" _ "${_pyproject_content}")
set(WeCo_VERSION "${CMAKE_MATCH_1}")

#some options
option (GEN_PYBINDING "Generate Python Binding" OFF)
option (GEN_WECORUN "Generate WeCoRun executable" ON)
option (GEN_TEST_EXEC "Generate test executables" OFF)
option (GEN_TEST_COST_FUNCTION "Add test cost function" OFF)
option (GEN_PLUGIN "Add Plugin Architecture" OFF)
option (GEN_CPP_DOC "Generate C++ documentation" OFF)
option (B3D_INTERPOLATION "Use Bézier 3D cubic interpolation" ON)

# use c++14
set(CMAKE_CXX_STANDARD 14 CACHE STRING "The C++ standard to use")
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

find_package (Threads)
find_package (OpenMP)

#================= main source files ========================
set(MAINSRC
	src/corgraph.cpp
	src/correlator.cpp
	src/path_item_list2cor_graph.cpp
	src/data.cpp
	src/datareader.cpp
	src/scheduler.cpp
	src/option.cpp
	src/project.cpp
	src/project_ccf.cpp
	src/project_ccf_test.cpp
	src/log.cpp
	src/utils.cpp

	src/ccf_misc.cpp
	src/ccf_gap.cpp
	src/ccf_polarity.cpp
	src/ccf_distal.cpp
	src/ccf_var_region.cpp

	src/ccf_thickness.cpp

    src/dtw_distance.cpp

	include/weco.h
	include/weco/tmpgraph.h
	include/weco/matrix.h
	include/weco/datareader.h
	include/weco/scheduler.h
	include/weco/project.h
	include/weco/option.h
	include/weco/utils.h
	include/weco/dtw_distance.h
)

if (B3D_INTERPOLATION)

	set(B3DSRC
		src/b3d/corner_point.cpp
		src/b3d/control_point.cpp
		src/b3d/curve.cpp
		src/b3d/patch.cpp
		src/b3d/profile.cpp
		include/b3d/common.h
		include/b3d/corner_point.h
		include/b3d/control_point.h
		include/b3d/curve.h
		include/b3d/patch.h
		include/b3d/profile.h
	)
	
	set(MAINSRC ${MAINSRC} ${B3DSRC} src/ccf_b3d.cpp)

endif (B3D_INTERPOLATION)


if (GEN_TEST_COST_FUNCTION) 
    set(MAINSRC ${MAINSRC} src/project_test.cpp)
endif (GEN_TEST_COST_FUNCTION) 


if (GEN_PLUGIN)
    set(MAINSRC	${MAINSRC}	plugin/plugin.cpp include/weco_plugin.h)
endif (GEN_PLUGIN)

#================ binding source files =======
set(BINDINGSRC
	binding/common.h

	binding/main.cpp
	binding/misc.cpp
	binding/cost_function.cpp
	binding/option.cpp
	binding/project.cpp
	binding/ccf_part.h
	binding/ccf_part.cpp
	binding/data.cpp
)

#================ set link options =======
set(LINKOPT ${CMAKE_THREAD_LIBS_INIT})
if(OpenMP_CXX_FOUND)
    set(LINKOPT ${LINKOPT} OpenMP::OpenMP_CXX)
endif()
if (GEN_PLUGIN)
    set(LINKOPT	${LINKOPT} ${CMAKE_DL_LIBS}	)
endif (GEN_PLUGIN)

#================ weco_cfg.h =======
configure_file (
  "${PROJECT_SOURCE_DIR}/include/weco/config.h.in"
  "${PROJECT_SOURCE_DIR}/include/weco/config.h"
)

#================ add warnings =======
if ( CMAKE_COMPILER_IS_GNUCC )
    set(CMAKE_CXX_FLAGS  "${CMAKE_CXX_FLAGS} -Wall" )
endif ( CMAKE_COMPILER_IS_GNUCC )
if ( MSVC )
    set(CMAKE_CXX_FLAGS  "${CMAKE_CXX_FLAGS} /W4")
endif ( MSVC )

include_directories("include")

#========== main executable =================
if (GEN_WECORUN)
    add_executable( WeCoRun ${MAINSRC} src/main.cpp )
    target_link_libraries( WeCoRun ${LINKOPT})
endif (GEN_WECORUN)

# =========== option main =======
# if test.cpp (in root dir) exists create weco_test binary
if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/test.cpp")
    add_executable( weco_test ${MAINSRC} test.cpp )
    target_link_libraries( weco_test ${LINKOPT})
endif()


#========== plugin example =================
if(GEN_PLUGIN_EXAMPLE)
    add_library( plugin_example SHARED plugin/plugin_example.cpp include/weco_plugin.h)
endif(GEN_PLUGIN_EXAMPLE)

#================= test executable ==============================

if (GEN_TEST_EXEC)
    foreach(TESTNAME test1 test2 test3 test_log)
    	add_executable(${TESTNAME} ${MAINSRC} src/${TESTNAME}.cpp)
    	target_link_libraries(${TESTNAME} ${LINKOPT})
    endforeach(TESTNAME)
endif(GEN_TEST_EXEC)

#=================== python bindings ==========================
if (GEN_PYBINDING)
    find_package(Python REQUIRED COMPONENTS Interpreter Development.Module)
    find_package(pybind11 CONFIG REQUIRED)

   pybind11_add_module(engine ${MAINSRC} ${BINDINGSRC} WITH_SOABI)
    target_link_libraries(engine PRIVATE pybind11::headers)
    target_compile_definitions(engine PRIVATE VERSION_INFO=${PROJECT_VERSION})
    install(TARGETS engine DESTINATION "weco/")

    if(GEN_WECORUN)
        install(TARGETS WeCoRun DESTINATION "${SKBUILD_SCRIPTS_DIR}")
    endif(GEN_WECORUN)

endif (GEN_PYBINDING)

# ====================================
# Documentation
# ====================================

if (GEN_CPP_DOC)
    find_package(Doxygen REQUIRED dot)
    set(DOXYGEN_OUTPUT_DIRECTORY ${PROJECT_SOURCE_DIR}/doc/cpp)
    doxygen_add_docs(doc include ALL COMMENT "building doc")
endif (GEN_CPP_DOC)

#=================== WebAssembly (§5.1) ==========================
if (WASM_BUILD)
    add_executable(weco_wasm ${MAINSRC})
    set_target_properties(weco_wasm PROPERTIES SUFFIX ".js")
endif (WASM_BUILD)

