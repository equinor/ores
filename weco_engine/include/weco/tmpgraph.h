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

#ifndef __weco_tmpgraph_h__
#define __weco_tmpgraph_h__

#include <vector>
#include <assert.h>

namespace WeCo {




/// Temporary graph template with data on Nodes and edges(Trans)
template <typename NodeDataType,typename TransDataType>
class TmpGraph {
public :
	using NodeId = int;
	using TransId = int;
	using NodeData = NodeDataType;
	using TransData = TransDataType;


	enum  {
		no_node = -1,
		no_trans = -1
	};

	/// Temporary graph node
	struct Node {
		NodeData data;
		TransId trans;

		Node(const NodeData&d) : data(d),trans(no_trans) {}
	};

	/// Temporary graph edge
	struct Trans {
		NodeId dest;
		TransId next;
		TransData data;

		Trans(NodeId _dest,TransId _next,const TransData& _data) :
			dest(_dest),next(_next),data(_data) {}
	};




	unsigned size() const {
		return (unsigned)nodes_.size();
	}

	unsigned trans_size() const {
		return (unsigned)trans_.size();
	}



	NodeData & node_data(NodeId node) {
		assert(node_id_valid(node));
		return nodes_[node].data;
	}
	const NodeData & node_data(NodeId node) const{
		assert(node_id_valid(node));
		return nodes_[node].data;
	}


	NodeId create_node(const NodeData& data) {
		nodes_.emplace_back(data);
		return (NodeId)(nodes_.size()-1);
	}


	TransData& trans_data(TransId trans) {
		assert(trans_id_valid(trans));
		return trans_[trans].data;
	}

	const TransData& trans_data(TransId trans) const{
		assert(trans_id_valid(trans));
		return trans_[trans].data;
	}

	TransId node_trans(NodeId node) const {
		assert(node_id_valid(node));
		return nodes_[node].trans;
	}

	TransId trans_dest(TransId trans) const {
		assert(trans_id_valid(trans));
		return trans_[trans].dest;
	}

	TransId trans_next(TransId trans) const {
		assert(trans_id_valid(trans));
		return trans_[trans].next;
	}

	TransId find_trans(NodeId src,NodeId dest) const {
		assert(node_id_valid(src));
		assert(node_id_valid(dest));

		for(TransId trans = node_trans(src);trans!=no_trans;trans=trans_next(trans)){
			if(trans_dest(trans)== dest) return trans;
		}
		return no_trans;
	}

	TransId create_trans(NodeId src,NodeId dest,const TransData & data) {
		assert(node_id_valid(src));
		assert(node_id_valid(dest));
		trans_.emplace_back(dest,node_trans(src),data);
		TransId trans = (unsigned)(trans_.size()-1);
		nodes_[src].trans = trans;
		return trans;
	}

	bool node_id_valid(NodeId node) const {
		return node>=0 && node < (int)nodes_.size();
	}

	bool trans_id_valid(TransId trans) const {
		return trans>=0 && trans <  (int)trans_.size();
	}




private:

	std::vector<Node> nodes_;
	std::vector<Trans> trans_;



};





} // namespace WeCo



#endif
