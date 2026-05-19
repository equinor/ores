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

#include <weco.h>
#include <weco/matrix.h>
#include <weco/tmpgraph.h>
#include <weco/corgraph_builder.h>
#include <algorithm>

namespace {

class  PathItemList2CorCraph {
public:
	struct NodeData {
		NodeData(WeCo::CorGraph::NodeId _in1,WeCo::CorGraph::NodeId _in2):
			in1(_in1),in2(_in2),out(0),order((_in1+_in2)*(_in1+_in2+1)/2 + _in1) {}



		WeCo::CorGraph::NodeId in1;
		WeCo::CorGraph::NodeId in2;
		WeCo::CorGraph::NodeId out;
		int order;



	};
	using TmpGraphType = WeCo::TmpGraph<NodeData,WeCo::CostValue>;

	const WeCo::CorGraph & in1_;
	const WeCo::CorGraph & in2_;

	TmpGraphType tmp_graph_;
	WeCo::Matrix<TmpGraphType::NodeId> node_table_;
	std::vector<TmpGraphType::NodeId> node_list_;




	PathItemList2CorCraph(const WeCo::CorGraph& in1,const WeCo::CorGraph& in2) :
		in1_(in1),in2_(in2),node_table_(in1.size(),in2.size(),TmpGraphType::no_node)
	{

	}


	void build(const WeCo::Correlator::PathItemList::const_iterator &begin,const WeCo::Correlator::PathItemList::const_iterator &end
		,WeCo::CorGraph & out){

		for(WeCo::Correlator::PathItemList::const_iterator i = begin;i!=end;i++) {
			const WeCo::Correlator::PathItem * path_item = &*i;
			TmpGraphType::NodeId node_id = get_node(path_item->node1(),path_item->node2());

			while(true) {
				const WeCo::Correlator::PathItem * prev_path_item = path_item->prev();
				if(prev_path_item == nullptr) break;
				TmpGraphType::NodeId prev_node_id = get_node(prev_path_item->node1(),prev_path_item->node2());


				TmpGraphType::TransId trans = tmp_graph_.find_trans(node_id,prev_node_id);
				if (trans ==TmpGraphType::no_trans ) {
					tmp_graph_.create_trans(node_id,prev_node_id,path_item->trans_cost());

				} else if(tmp_graph_.trans_data(trans) > path_item->trans_cost()) {
					tmp_graph_.trans_data(trans) = path_item->trans_cost();
				}


				path_item = prev_path_item;
				node_id = prev_node_id;

			}

		} // for all path

		// order nodes
		std::sort(node_list_.begin(),node_list_.end()
				, [this](TmpGraphType::NodeId a,TmpGraphType::NodeId b) {
		        	return this->tmp_graph_.node_data(a).order <this->tmp_graph_.node_data(b).order;}
	        );

		// set number
		{
			WeCo::CorGraph::NodeId num =0;
			for(auto i : node_list_)
				tmp_graph_.node_data(i).out = num++;
		}


		{
			WeCo::CorGraphBuilder builder(out);
			builder.init_merge(in1_,in2_,tmp_graph_.size(),tmp_graph_.trans_size());

			for (auto node_id : node_list_){
				const NodeData & node= tmp_graph_.node_data(node_id);
				builder.add_merged_node(node.in1,node.in2);

				for (TmpGraphType::TransId trans_id = tmp_graph_.node_trans(node_id);
						trans_id!=TmpGraphType::no_trans;trans_id=tmp_graph_.trans_next(trans_id)) {
					builder.add_trans(tmp_graph_.node_data(tmp_graph_.trans_dest(trans_id)).out,tmp_graph_.trans_data(trans_id));
				}

			}

		}


	}

	TmpGraphType::NodeId get_node(WeCo::CorGraph::NodeId n1,WeCo::CorGraph::NodeId n2) {
		TmpGraphType::NodeId id = node_table_(n1,n2);
		if (id != TmpGraphType::no_node) return id;
		id = tmp_graph_.create_node(NodeData(n1,n2));
		node_list_.push_back(id);
		node_table_(n1,n2) = id;
		return id;
	}


};

}

namespace WeCo{
void path_item_list2cor_graph(const Correlator::PathItemList::const_iterator &begin,const Correlator::PathItemList::const_iterator &end
		,const CorGraph& in1,const CorGraph& in2,CorGraph & out) {


	PathItemList2CorCraph(in1,in2).build(begin,end,out);

}

}
