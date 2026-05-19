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
#include <algorithm>

namespace WeCo {


//==================================== CostHelperRegion =====================================

void CostHelperRegion::init(const WellList&well_list,const std::string & region_name) {
	region_.resize(cost_helper_.size());
	for(unsigned n = 0;n<cost_helper_.size1();n++)
		region_[n] = &(well_list.well(cost_helper_.cor_graph1().well_id(n))->get_region_list(region_name));
	for(unsigned n = 0;n<cost_helper_.size2();n++)
		region_[n+cost_helper_.size1()] = &(well_list.well(cost_helper_.cor_graph2().well_id(n))->get_region_list(region_name));
}

bool CostHelperRegion::dest_in_same_region() const {
	unsigned reg_id = 0;
	for( unsigned well_id=0; well_id <size(); well_id++ ) {
		unsigned cur_reg = dest_region( well_id );
		if( cur_reg > 0 ) {
			if (reg_id == 0)
				reg_id = cur_reg;
			else if( reg_id != cur_reg )
				return false;
		}
	}
	return true;
}


//==================================== CostHelperBand =====================================

void CostHelperBand::init(const WellList&well_list,const std::string & region_name) {
	 std::vector<const RegionList *> data(size());
	for(unsigned n = 0;n<cost_helper_.size1();n++)
		data[n] = &(well_list.well(cost_helper_.cor_graph1().well_id(n))->get_region_list(region_name));
	for(unsigned n = 0;n<cost_helper_.size2();n++)
		data[n+cost_helper_.size1()] = &(well_list.well(cost_helper_.cor_graph2().well_id(n))->get_region_list(region_name));

	// get max band number
	nbr_band_ =1;
	for(unsigned well = 0;well<size();well++) {
		for(const RegionList::Region &i : data[well]->regions()) {
			if(i.id >= nbr_band_) nbr_band_ = i.id +1;
		}
	}

	data_.resize(nbr_band_*size()*2);
	std::fill(data_.begin(),data_.end(),-1);

	//fill data
	for(unsigned well = 0;well<size();well++) {
		for(const RegionList::Region &reg : data[well]->regions()) {
			unsigned idx = get_idx(well,reg.id);
			data_[idx]=reg.start;
			data_[idx+1]=reg.start +reg.length;
		}
	}
}



bool CostHelperBand::no_crossing() const {
	bool in_another_band = false;

	unsigned idx = 0;

	for(unsigned band=0;band<nbr_band();band++){
		bool before = false;
		bool after = false;
		bool in_band = false;
		for(unsigned well=0;well<size();well++){
			assert(idx == get_idx(well,band));
			if(data_[idx]==-1) {/*undefined zone*/}
			else if((unsigned)data_[idx]>cost_helper_.dest(well)) {
				// before zone
				if(after) return false;
				before = true;
			}
			else if((unsigned)data_[idx+1]<=cost_helper_.dest(well)) {
				//after zone
				if(before)  return false;
				after = true;
			}
			else {
				// in zone
				if(in_another_band) return false;
				in_band = true;
			}
			idx+=2;
		}
		if (in_band) in_another_band = true;
	}
	return true;
}



//==================================== CostHelperData =====================================

void CostHelperData::init(const WellList&well_list,const std::string & data_name) {
	data_name_ = data_name;
	data_.resize(size());
	for(unsigned n = 0;n<cost_helper_.size1();n++)
		data_[n] = &(well_list.well(cost_helper_.cor_graph1().well_id(n))->get_data(data_name));
	for(unsigned n = 0;n<cost_helper_.size2();n++)
		data_[n+cost_helper_.size1()] = &(well_list.well(cost_helper_.cor_graph2().well_id(n))->get_data(data_name));
}

// §6.6: Variance computation — kept simple for typical 2-10 well counts.
// Compiler auto-vectorizes this loop with -O2/-O3.
// For large node counts, consider AVX2 intrinsics.
DataValue CostHelperData::dest_var() const {
    const unsigned n_wells = size();
    DataValue sum = 0.;
    CostValue sum2 = 0.;

    for(unsigned n = 0; n < n_wells; n++) {
          DataValue v = dest_data(n);
          sum += v;
          sum2 += v*v;
     }
     DataValue mean = sum / n_wells;
     return (sum2 / n_wells - mean * mean);
}


//============================= CostHelperWell =====
void CostHelperWell::set(const CorGraph& cg1,const CorGraph& cg2,const WellList&well_list) {
	wells_.clear();
	unsigned s1 = cg1.node_size();
	unsigned s2 = cg2.node_size();
	wells_.resize(s1+s2);
	for(unsigned n = 0;n<s1;n++)
		wells_[n] = well_list.well(cg1.well_id(n));
	for(unsigned n = 0;n<s2;n++)
		wells_[n+s1] = well_list.well(cg2.well_id(n));
}


//===================================== Correlator ======================================
using PathItem = Correlator::PathItem;


Correlator::Correlator(){

}
Correlator::~Correlator(){

}




void Correlator::add_path_from(CorGraph::NodeId node1,CorGraph::NodeId node2,CostValue cost){

	PathItemList & from = path_buffer(node1,node2);
	if (! from.size()) return;

	for(auto &i : from) {
		CostValue path_cost = cost+i.cost();
		if(cur_path_item_list_->size()>=max_res_ && path_cost> cur_max_cost_)
			continue;
		cur_path_item_list_->push_back(PathItem(cur_node1_,cur_node2_,path_cost,&i));
		if(cur_max_cost_<path_cost)
			cur_max_cost_= path_cost;
	}

}


static bool path_item_sort(const Correlator::PathItem &a,const Correlator::PathItem &b) {
	return a.cost() < b.cost();
}

void Correlator::init_path(CorGraph::NodeId node1,CorGraph::NodeId node2){
	cur_path_item_list_ = &path_buffer(node1,node2);
	cur_node1_ = node1;
	cur_node2_ = node2;
	cur_max_cost_ =0.;
}


void Correlator::finish_path(){

	// §6.5 Beam search pruning: if beam_width_ > 0, keep only top-k paths per cell
	unsigned effective_max = max_res_;
	if (beam_width_ > 0 && static_cast<unsigned>(beam_width_) < effective_max)
		effective_max = static_cast<unsigned>(beam_width_);

	if (cur_path_item_list_->size() > effective_max) {
		std::partial_sort(cur_path_item_list_->begin(),cur_path_item_list_->begin()+effective_max, cur_path_item_list_->end(),&path_item_sort);
		cur_path_item_list_->resize(effective_max);
	};

}

bool Correlator::init_run(const CorGraph&graph1,const CorGraph& graph2,unsigned nbr_res){
	graph1_ =&graph1;
	graph2_ =&graph2;
	path_buffer_.clear();
	sparse_path_buffer_.clear();
	result_ = nullptr;

	if(!graph1.size() || ! graph2.size()){
		LOG<< "*WRN* Correlation failure: empty parent"<<std::endl;
		return false;

	}
	assert(graph1.size()>1);
	assert(graph2.size()>1);
	assert(nbr_res>=1);
	max_res_ = nbr_res;
	graph1_size_ = graph1.size();
	graph2_size_ = graph2.size();

	// §6.3 Use sparse buffer when band constraint limits cells
	use_sparse_ = (band_width_ > 0);
	if(!use_sparse_) {
		path_buffer_.resize(graph1_size_*graph2_size_);
		path_buffer_[0].push_back(PathItem());
	} else {
		uint64_t key0 = 0;
		sparse_path_buffer_[key0].push_back(PathItem());
	}
	return true;

}
void Correlator::finish_run(){
	result_ = &path_buffer(graph1_size_-1 ,graph2_size_-1);
	std::sort(result_->begin(),result_->end(),&path_item_sort);
}





void PathItem::dump(std::ostream &out)const {
	out << this->node1_<<','<<this->node2_<<','<<this->cost_<< std::endl;
	if (this->prev_)
		this->prev_->dump(out);
}



void PathItem::dump(std::ostream &out, const CorGraph& cg1,const CorGraph&cg2)const {

	for (unsigned n = 0; n < cg1.node_size();n++)
	   out << " "<< cg1.marker(this->node1_,n);
	for (unsigned n = 0; n < cg2.node_size();n++)
	   out << " "<< cg2.marker(this->node2_,n);
	out << " : "<<this->cost_<<std::endl;
	if (this->prev_)
		this->prev_->dump(out,cg1,cg2);
}


unsigned PathItem::length() const {
	unsigned cnt =0;
	for(const PathItem *i = this; i!=nullptr;i=i->prev()) cnt++;
	return cnt;
}

/// compute distance between 2 path
double PathItem::path_distance(const PathItem& other, const CorGraph& cg1,const CorGraph&cg2) const {
	unsigned len1= length();
	unsigned len2 = other.length();

	std::unique_ptr<double[]> col1(new double[len1]);
	std::unique_ptr<double[]> col2(new double[len1]);

	double * cur_col = col1.get();
	double * prev_col = col2.get();

	{//fill first col
		double prev_cost =  cur_col[0] = item_distance(other,cg1,cg2);
		const PathItem * item = this;
		for(unsigned line = 1;line<len1;line++) {
			item = item->prev();
			assert(item !=nullptr);
			cur_col[line] = prev_cost += item->item_distance(other,cg1,cg2);
		}
	}
	{
		const PathItem * col_item = &other;

		for ( unsigned col = 1; col < len2; col++) {

			std::swap(cur_col,prev_col);
			col_item = col_item->prev();
			assert(col_item);
			const PathItem * line_item = this;

			cur_col[0] = prev_col[0] + col_item->item_distance(*line_item,cg1,cg2);
			for ( unsigned line =1 ; line < len1; line++) {
				line_item = line_item->prev();
				assert(line_item);

				cur_col[line] = std::min({cur_col[line-1],prev_col[line-1],prev_col[line]})
					+  col_item->item_distance(*line_item,cg1,cg2);
			}

		}
	}
    return cur_col[len1-1];
}

double PathItem::item_distance(const PathItem& other, const CorGraph& cg1,const CorGraph&cg2) const {
   unsigned nbr_err = 0;

   if (other.node1() != node1() ) {
	   for(unsigned i =0;i<cg1.node_size();i++) {
		   if (cg1.marker(node1(),i) != cg1.marker(other.node1(),i))
			   nbr_err++;
	   }
   }

   if (other.node2() != node2() ) {
	   for(unsigned i =0;i<cg2.node_size();i++) {
		   if (cg2.marker(node2(),i) != cg2.marker(other.node2(),i))
			   nbr_err++;
	   }
   }

   return (double)nbr_err/(double)(cg1.node_size()+cg2.node_size());

}

void Correlator::result2corgraph(CorGraph&out,unsigned max_size,double min_dist )const {

	if(failled()) {
		out.clear();
		return;
	}
	const PathItemList * pil = &result();

	PathItemList new_pil;

	if( min_dist >0.){
		//filter with distance
		std::vector<bool> flag(pil->size(),true);

		for (unsigned i = 0;i<pil->size();i++) {
			if(!flag[i] ) continue;
			for(unsigned j = i+1;j< pil->size();j++) {
				if (flag[j] && pil->at(i).path_distance(pil->at(j),*graph1_,*graph2_)<min_dist)
					flag[j]=false;
			}
		}
		for (unsigned i = 0;i<pil->size();i++) {
			if(flag[i]) new_pil.emplace_back(pil->at(i));
		}

		pil =&new_pil;

	}

	if(!max_size || max_size>pil->size() ) {
		path_item_list2cor_graph(*pil,*graph1_,*graph2_,out);

	} else {
		path_item_list2cor_graph(pil->begin(),pil->begin()+max_size,*graph1_,*graph2_,out);

	}
}



}



