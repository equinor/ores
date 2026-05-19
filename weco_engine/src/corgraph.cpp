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
#include <weco/corgraph_builder.h>
#include <algorithm>
#include <climits>
#include <sstream>
#include <weco/utils.h>

namespace WeCo {


CorGraph::CorGraph(unsigned size,WellId well_id) :size_(size),node_size_(1){
	wells_.resize(1);
	wells_[0] = well_id;
	if (size>0) {
		nodes_.resize(size);
		markers_.resize(size);
		for(NodeId i = 0;i<size_;i++) {
			markers_[i] = i;
		}
		nodes_[0].nbr_trans = 0;
		nodes_[0].trans_id =0;
		if(size>1) {
			trans_.resize(size-1);
			for(NodeId i = 1;i<size_;i++) {
				nodes_[i].nbr_trans=1;
				nodes_[i].trans_id =i-1;
				trans_[i-1].cost = 0.;
				trans_[i-1].from = i-1;

			}
		}
	}
}


void CorGraph::clear() {
	size_=0 ;
	node_size_=0;

	markers_.clear();
	nodes_.clear();
	trans_.clear();
	wells_.clear();


}

void CorGraph::dump_well_id(std::ostream & stream )const {
	for (unsigned n = 0; n < node_size();n++)
			stream << " "<< well_id(n);
}

std::string CorGraph::well_id_str() const {
	std::stringstream out;
	for (unsigned n = 0; n < node_size();n++)
			out << '-'<< well_id(n);
	return out.str();
}

std::string CorGraph::well_string() const{
	static const std::string sep("-");
	std::string result = std::to_string(well_id(0));
	for (unsigned n = 1; n < node_size();n++)
			result += sep+std::to_string(well_id(n));
	return result;
}


std::string CorGraph::node_string(NodeId node) const{
	static const std::string sep("-");
	std::string result = std::to_string(marker(node,0));
	for (unsigned n = 1; n < node_size();n++)
			result += sep+std::to_string(marker(node,n));
	return result;
}

void CorGraph::dump(std::ostream & stream ) const {
	stream << "WellIds:";
	dump_well_id(stream);
	stream<<std::endl;

	for(NodeId node=0;node<size() ; node++ ){
		stream<< "Node "<<node<<" (";
		for (unsigned n = 0; n < node_size();n++)
			stream << " "<< marker(node,n);
		stream<<" )"<<std::endl;
		for (unsigned t=0;t<nbr_trans(node);t++)
			stream <<"  -> "<<trans_from(node,t)<<" ("<<trans_cost(node,t)<<")"<<std::endl;
	}
}


void CorGraph::dump_info(std::ostream & stream) const {
	stream << "WellIds:";
	dump_well_id(stream);
	stream<<  "  Nodes:"<<size()<<" Trans:"<<trans_.size()<<" Wells:"<<node_size()<<" MaxCor:"<<nbr_correlation()<<"\n";
	Statistics stats;
	for(const TransInfo &i:trans_)
		stats(i.cost);
	stream << "  Cost: mean="<<stats.mean()<<", stddev="<<stats.std_dev()
		    <<", min="<<stats.min()<<", max="<<stats.max()
			<<std::endl;
}

void CorGraph::to_dot(std::ostream & stream,bool show_cost) const {

	stream << "digraph test {"<<std::endl;
	for(NodeId node=0;node<size() ; node++ ){
		stream << "n"<<node;
		if(node_size() < 10) {
			stream <<" [ label = \"";
			for (unsigned n = 0; n < node_size();n++)
				stream << " "<< marker(node,n);
			stream << "\" ]";
		}
		stream <<";"<<std::endl;
		for (unsigned t=0;t<nbr_trans(node);t++) {
			stream <<"n"<<trans_from(node,t)<<" -> n"<<node;
			if(show_cost)
				stream << " [ label = \""<<trans_cost(node,t)<<"\" ]";
			stream<<std::endl;
		}

	}
	stream << "}"<<std::endl;

}



bool CorGraph::check_order() const {
	for(NodeId node=0;node<size() ; node++ ){
		for (unsigned t=0;t<nbr_trans(node);t++)
			if (trans_from(node,t) >=node) return false;
	}
	return true;
}



static unsigned _cor_count(const CorGraph& cg,std::vector<unsigned> &cnt,CorGraph::NodeId id){
	if(cnt[id]>0) return cnt[id];
	if(cg.nbr_trans(id) == 0) return 1;
	unsigned n = 0;
	for(unsigned i = 0;i < cg.nbr_trans(id);i++)
		n+= _cor_count(cg,cnt,cg.trans_from(id,i));
	cnt[id] = n;
	return n;


}
unsigned CorGraph::nbr_correlation() const{
	if(size()==0) return 0;
	std::vector<unsigned> cnt(size(),0);
	return _cor_count(*this,cnt,size()-1);
}



void CorGraphBuilder::init(unsigned node_size,unsigned nbr_nodes,unsigned nbr_trans){
	assert(node_size>0);
	corgraph_.size_ = 0;
	corgraph_.node_size_ = node_size;
	corgraph_.wells_.resize(node_size);
	corgraph_.markers_.clear();
	corgraph_.nodes_.clear();
	corgraph_.trans_.clear();
	corgraph_.markers_.reserve(node_size*nbr_nodes);
	corgraph_.nodes_.reserve(nbr_nodes);
	corgraph_.trans_.reserve(nbr_trans);
	last_node_=0;
}

void CorGraphBuilder::init_merge(const CorGraph &in1,const CorGraph&in2,unsigned nbr_nodes,unsigned nbr_trans) {
	init(in1.node_size()+in2.node_size(),nbr_nodes,nbr_trans);
	// copy wellId
	for(unsigned i = 0;i< in1.node_size();i++)
		corgraph_.wells_[i] = in1.wells_[i];
	for(unsigned i = 0;i< in2.node_size();i++)
		corgraph_.wells_[i+in1.node_size()] = in2.wells_[i];

	merged_graph1_ = &in1;
	merged_graph2_ = &in2;

}


CorGraph::NodeId CorGraphBuilder::add_node() {
	corgraph_.nodes_.emplace_back(corgraph_.trans_.size());
	corgraph_.size_ ++;
	corgraph_.markers_.resize(corgraph_.size() * corgraph_.node_size());

	last_node_ = corgraph_.size() -1;
	return last_node_;

}
CorGraph::NodeId CorGraphBuilder::add_merged_node(CorGraph::NodeId node_id1,CorGraph::NodeId node_id2) {
	assert(merged_graph1_ != nullptr && merged_graph2_!=  nullptr);
	add_node();

	unsigned n = last_node_* corgraph_.node_size();
	unsigned size1 = merged_graph1_->node_size();
	auto p1 = merged_graph1_->markers_.begin() + size1 * node_id1;

	std::copy(p1,p1+size1,corgraph_.markers_.begin()+n);
	unsigned size2 = merged_graph2_->node_size();
	auto p2 = merged_graph2_->markers_.begin() + size2 * node_id2;
	std::copy(p2,p2+size2,corgraph_.markers_.begin()+n+size1);

	return last_node_;

}
void CorGraphBuilder::add_trans(CorGraph::NodeId dest,CostValue cost){
	assert(corgraph_.size()>0);
	assert(dest<last_node_);
	corgraph_.nodes_[last_node_].nbr_trans+=1;
	corgraph_.trans_.emplace_back(dest,cost);


}


// §6.2 Graph compaction — remove unreachable nodes
void CorGraph::compact() {
	if(size_ <= 2) return;

	// 1) Mark reachable nodes by forward pass from node 0 and backward from last node
	std::vector<bool> has_out(size_, false);
	std::vector<bool> has_in(size_, false);

	// Node 0 (start) always reachable, last node (end) always reachable
	has_out[0] = true;
	has_in[size_-1] = true;

	// Forward: mark nodes that have incoming edges from earlier reachable nodes
	for(NodeId n = 1; n < size_; n++) {
		for(unsigned t = 0; t < nbr_trans(n); t++) {
			if(has_out[trans_from(n,t)]) {
				has_out[n] = true;
				break;
			}
		}
	}

	// Backward: mark nodes whose successors are reachable
	for(NodeId n = size_-1; n > 0; n--) {
		for(unsigned t = 0; t < nbr_trans(n); t++) {
			if(has_in[n]) {
				has_in[trans_from(n,t)] = true;
			}
		}
	}
	has_in[0] = true;

	// 2) Build old-to-new node ID mapping
	std::vector<NodeId> old2new(size_, UINT_MAX);
	NodeId new_count = 0;
	for(NodeId n = 0; n < size_; n++) {
		if(has_out[n] && has_in[n]) {
			old2new[n] = new_count++;
		}
	}

	if(new_count == size_) return; // nothing to compact

	// 3) Rebuild arrays
	std::vector<MarkerId> new_markers;
	std::vector<NodeInfo> new_nodes;
	std::vector<TransInfo> new_trans;
	new_markers.reserve(new_count * node_size_);
	new_nodes.reserve(new_count);
	new_trans.reserve(trans_.size());

	for(NodeId n = 0; n < size_; n++) {
		if(old2new[n] == UINT_MAX) continue;
		// Copy markers
		for(unsigned w = 0; w < node_size_; w++)
			new_markers.push_back(markers_[n * node_size_ + w]);
		// Copy transitions, remapping source IDs
		unsigned new_trans_id = static_cast<unsigned>(new_trans.size());
		unsigned new_nbr = 0;
		for(unsigned t = 0; t < nbr_trans(n); t++) {
			NodeId from = trans_from(n,t);
			if(old2new[from] != UINT_MAX) {
				new_trans.push_back(TransInfo(old2new[from], trans_cost(n,t)));
				new_nbr++;
			}
		}
		new_nodes.push_back(NodeInfo(new_trans_id, new_nbr));
	}

	markers_ = std::move(new_markers);
	nodes_ = std::move(new_nodes);
	trans_ = std::move(new_trans);
	size_ = new_count;
}

} // namespace WeCo
