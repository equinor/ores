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

//================================================
// CostFunc
//==============================================



class _PyCostFunc {
public :
	virtual ~_PyCostFunc(){}

	virtual bool get_cost(CorGraph::NodeId f1,CorGraph::NodeId t1,CostValue cost1,CorGraph::NodeId f2,CorGraph::NodeId t2,CostValue cost2) = 0;

	bool operator()(CorGraph::NodeId f1,CorGraph::NodeId t1,CostValue cost1,CorGraph::NodeId f2,CorGraph::NodeId t2,CostValue cost2, CostValue& cost){
		if(get_cost(f1,t1,cost1,f2,t2,cost2)) {
			cost = _cost;
			return true;
		}
		return false;
	}

	void set_cost(CostValue c)
		{_cost = c;}
private :
	CostValue _cost;
};

class _PyCostFuncT : public _PyCostFunc {
public :
	virtual bool get_cost(CorGraph::NodeId f1,CorGraph::NodeId t1,CostValue cost1,CorGraph::NodeId f2,CorGraph::NodeId t2,CostValue cost2) override {
		 PYBIND11_OVERLOAD_PURE(
		            bool, /* Return type */
		            _PyCostFunc,      /* Parent class */
		            get_cost,          /* Name of function in C++ (must match Python name) */
					f1,t1,cost1,f2,t2,cost2
		 );
		 return false;
	}
};

};

void def_cost_function(py::module_& m){

    py::class_<WeCo::_PyCostFunc,WeCo::_PyCostFuncT>(m,"CostFunc")
 	    .def(py::init<>())
 	    .def("set_cost",&WeCo::_PyCostFunc::set_cost,"Deprecated")
 	    .def("get_cost",&WeCo::_PyCostFunc::get_cost,"Deprecated")
    ;
    py::class_<WeCo::CorGraph>(m,"CorGraph")
			.def("size",&WeCo::CorGraph::size,
			    ":return: Size of the graph (Number of nodes)\n:rtype: int\n"
			    )
			.def("node_size",&WeCo::CorGraph::node_size,":return: Number of wells in the CorGraph")
			.def("marker",&WeCo::CorGraph::marker, 
                ":return: Marker ID from a node ID and a Well ID",
                py::arg( "node_id" ),
                py::arg( "well_id" )
                )
			.def("nbr_trans",&WeCo::CorGraph::nbr_trans, 
                ":return: Number of transitions from a CorGraph Node ID",
                py::arg( "node_id" ) )
			.def("trans_cost",&WeCo::CorGraph::trans_cost,
                ":return: Transition cost to arrive at CorGraph Node ID and transition ID \n \
                :param edge_id: The transition ID (must be smaller than nbr_trans)",
                py::arg( "dest_node_id" ),
                py::arg( "edge_id" ) )
			.def("trans_from",&WeCo::CorGraph::trans_from,
                "Allows to navigate in the CorGraph structure \n\
                :return: The source CorGraph Node ID corresponding to transition ID \n\
                :param dest_node_id: The destination node ID (must be smaller than size) \n\
                :param edge_id: The transition ID (must be smaller than nbr_trans)",
                py::arg( "dest_node_id" ),
                py::arg( "edge_id" ) )
			.def("check_order",&WeCo::CorGraph::check_order)
			.def("dump",(void (WeCo::CorGraph::*)()const)&WeCo::CorGraph::dump,
			    "Debug function: output the graph to std::cout")
			.def("dump",(void (WeCo::CorGraph::*)(const std::string&)const)&WeCo::CorGraph::dump,
			    "Debug function: output the graph to file argO")
			.def("to_dot",(void (WeCo::CorGraph::*)(const std::string &,bool)const)&WeCo::CorGraph::to_dot,
					"Creates a dot file from the graph\n\n:param filename: dot file name",
					py::arg("filename"),py::arg("show_cost")=true)
			DEF(CorGraph,empty,"True if no correlations")
			DEF(CorGraph,nbr_correlation,"Number if correlations")
			DEF(CorGraph,well_id,"Well id for each column")
	;

    py::class_<WeCo::Correlator>(m,"Correlator")
        .def(py::init<>())
		.def("run",
		    [](WeCo::Correlator &cor,WeCo::CorGraph&cg1,WeCo::CorGraph&cg2,unsigned nbr_res,WeCo::_PyCostFunc&f ) {
			    cor.run(cg1,cg2,nbr_res,f);
    		},
            "Runs the Correlation between the left and right CorGraphs",
            py::arg( "left_corgraph" ),
            py::arg( "right_corgraph" ),
            py::arg( "number_best_results" ),
            py::arg( "cost_function" ) )
		.def("result2corgraph",(void (WeCo::Correlator::*)(WeCo::CorGraph&)const)&WeCo::Correlator::result2corgraph)
		.def("result2corgraph",(void (WeCo::Correlator::*)(WeCo::CorGraph&,unsigned)const)&WeCo::Correlator::result2corgraph)
		.def("nbr_result",&WeCo::Correlator::nbr_result)
		.def("dump_result",[](const WeCo::Correlator &cor,unsigned n) {cor.dump_result(n);})
	;
   //========================= CostHelper ======================================

	py::class_<WeCo::CostHelper>( m, "CostHelper" )
		.def( "size", &WeCo::CostHelper::size, "The total size for both (left and right) CorGraphs to be correlated."
		    "Is equal to size1 + size2")
		.def( "size1", &WeCo::CostHelper::size1, "Number of wells on the left side" )
		.def( "size2", &WeCo::CostHelper::size2, "Number of wells on the right side" )
		.def( "cor_graph1", &WeCo::CostHelper::cor_graph1, "The left CorGraph to be correlated" )
		.def( "cor_graph2", &WeCo::CostHelper::cor_graph2, "The right CorGraph to be Correlated" )
		.def( "src", &WeCo::CostHelper::src, "The source marker ID for a well \n\
			:param well_id: The well identifier (between 0 and size -1)",
			py::arg( "well_id" ) )
		.def( "dest", &WeCo::CostHelper::dest, "The destination marker ID for a well \n\
			:param well_id: The well identifier (between 0 and size -1)",
			py::arg( "well_id" ) )
		.def( "same", &WeCo::CostHelper::same,
			":return: True if there is a gap (src == dest) for a well \n\
			:param well_id: The well identifier (between 0 and size -1)",
			py::arg( "well_id" ) )
	;

}