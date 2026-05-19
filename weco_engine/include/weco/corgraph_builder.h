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

#ifndef __weco_corgraph_buider_h__
#define __weco_corgraph_buider_h__


#include <weco.h>

namespace WeCo {

/// Used to build CorGraph
class CorGraphBuilder {
public:
	CorGraphBuilder(CorGraph& corgraph) :
		corgraph_(corgraph){}


	void init(unsigned node_size,unsigned nbr_nodes=0,unsigned nbr_trans=0);
	void init_merge(const CorGraph &in1,const CorGraph&in2,unsigned nbr_nodes=0,unsigned nbr_trans=0);


	CorGraph::NodeId add_node();
	CorGraph::NodeId add_merged_node(CorGraph::NodeId,CorGraph::NodeId);
	void add_trans(CorGraph::NodeId dest,CostValue cost = 0);


private:
	CorGraph& corgraph_;
	const CorGraph *merged_graph1_=nullptr;
	const CorGraph *merged_graph2_=nullptr;
	CorGraph::NodeId last_node_=0;
};

}



#endif
