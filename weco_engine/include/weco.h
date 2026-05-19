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

///@file weco.h
///@brief main include


#ifndef __weco_h__
#define __weco_h__

#include <vector>
#include <unordered_map>
#include <iostream>
#include <fstream>
#include <string>
#include <cmath>
#include <assert.h>
#include <algorithm>
#include <exception>
#include <memory>
#include <functional>

/// Main WeCo namespace
namespace WeCo {
#include "weco/config.h"

/// return WeCo Version
inline std::string get_version()
	{return WeCo_VERSION;}


/// Simple Logger
class Log {
public:
	static std::ostream & out()
		{ return current_?log_stream_ : std::cout;}

	Log();

	virtual ~Log();

	virtual void write(const std::string&) = 0;

	static Log * current() {return current_;}

private:
	static Log * current_;
	static std::ostream log_stream_;

};

#define LOG ::WeCo::Log::out()

using WellId = unsigned;
using MarkerId = unsigned;
using CostValue = double;
using DataValue = double;


/// Base Exception
class Exception : public std::exception{
public:
	Exception(const std::string & text)
		:text_(text){};

	virtual const char* what() const noexcept
		{ return text_.c_str();}

private:
	std::string text_;
};

/// Error when reading files (Exception)
class ReadError: public Exception {
public :
	using Exception::Exception;
};

class DataReader;


/// store a list of DataValue vectors
class DataStore {
public:
	/// create an empty datastore
	DataStore() {};



	/// DataValue vector
	class Data {
	public:
		/// create from file
		Data(DataReader&reader){
			read(reader);
		}

		/// create from std::vector
		Data(const std::string &name ,std::vector<DataValue> &&data):
			name_(name),data_(data){};

		/// create from std::vector
		Data(const std::string &name ,const std::vector<DataValue> &data):
			name_(name),data_(data){};


		/// create from size
		Data(const std::string &name ,unsigned size):
			name_(name),data_(size,0){};

		/// return Data name
		const std::string & name() const
			{ return name_;}

		/// return data size
		unsigned size() const
		   {  return (unsigned)data_.size();}

		/// access to data value
		DataValue get(unsigned n) const{
			assert(n<size());
			return data_[n];
		}

		/// access to data value
		DataValue operator[](unsigned n) const
			{return get(n);}


		/// change a  data value
		void set(unsigned n,DataValue v){
			assert(n<size());
			data_[n] =v;
		}


		const std::vector<DataValue> &data() const 
			{ return data_;}

		bool read(DataReader & reader);
	private:
		std::string name_;
		std::vector<DataValue> data_;

	};


	const Data & get_data(const std::string & name) const;

	/**
	 * @brief return alldata names as a vector of strings
	 * 
	 * @return std::vector<std::string> 
	 */
	std::vector<std::string> data_names()const;

	bool data_exists(const std::string & name) const ;

	void add_data(const std::string&name,std::vector<DataValue>&&data) {
		assert(!data_exists(name));
		datas_.emplace_back(name,data);
	}

	void add_data(const std::string&name,const std::vector<DataValue>&data) {
		assert(!data_exists(name));
		datas_.emplace_back(name,data);
	}

	void create_data(const std::string&name,unsigned size) {
		assert(!data_exists(name));
		datas_.emplace_back(name,size);
	}


	bool read(DataReader&reader );
	void clear();

private:
	std::vector<Data> datas_;

};



/// Regions List(for well)
class RegionList {
public:
	/// One Region: an interval and region ID in a well
	struct Region{
		Region(unsigned _id=0,unsigned _start=0,unsigned _length=0)
			:id(_id),start(_start),length(_length){};

		/// region id
		unsigned id;
		/// first marker
		unsigned start;
		/// length
		unsigned length;

		/// return true if \p marker_id is inside region
		bool is_in(unsigned marker_id) const
			{return ( marker_id >=start) && ( marker_id < start+length );}
	};

	RegionList():name_(""){}

	RegionList(const std::string& name):name_(name){}

	RegionList(DataReader&reader) {
		read(reader);
	}

	void add(unsigned _id=0,unsigned _start=0,unsigned _length=0)
		{regions_.emplace_back(_id,_start,_length);}

	const std::string & name() const {
		return name_;
	}


	unsigned get_region(unsigned value,unsigned default_value=0)const{
		for(const Region& region: regions_){
			if  (region.is_in(value))
				return region.id;
		}
		return default_value;
	}

	const std::vector<Region> &regions()const {
		return regions_;
	}
private:
	std::string name_;
	std::vector<Region> regions_;

	void read(DataReader&);
};


/// Store well's data
class Well: public DataStore {
public:
	///Create from file
	Well(DataReader&);

	///Constructor
	Well(WellId id=0,const std::string &name="",unsigned size=0,DataValue x=0.
		,DataValue y=0.,DataValue z=0.,DataValue h=0.):
			well_id_(id),well_name_(name),well_size_(size),x_(x),y_(y),z_(z),h_(h) {};
	

	/// return the WellId
	WellId well_id() const
		{return well_id_;}

	/// return the well name
	const std::string & well_name() const
		{return well_name_;}

	/// number of markers in well
	unsigned well_size() const
		{return well_size_; }

	/// x position
	DataValue x() const {return x_;}
	/// y position
	DataValue y() const {return y_;}
	/// z position
	DataValue z() const { return z_; }
	/// Well height (distance) h sysnonim
	DataValue len() const { return h_; }
	/// Well height (distance)
	DataValue h() const { return h_; }

	bool read(DataReader&);
	void clear();


	void set_well_id(WellId id){
		well_id_ =id;
	}

	//Regions list
	void add_region_list(const RegionList& rl){
		region_lists_.push_back(rl);
	}


	/**
	 * @brief return all region list names as a vector of string
	 * 
	 * @return std::vector<std::string> 
	 */
	std::vector<std::string> region_list_names()const;

	const RegionList & get_region_list(const std::string & name) const;

	bool region_list_exists(const std::string & name) const ;

private:
	WellId well_id_;
	std::string well_name_;
	/// Number of Marker
	unsigned well_size_;
	/// Well position and height
	DataValue x_,y_,z_,h_;

	std::vector<RegionList> region_lists_;

};


/// Stores a well list
class WellList {
public :
	/// default Constructor
	WellList();

	/// Create from file
	WellList(const std::string & filename);

	/// Create from DataReader
	WellList(DataReader & data_reader);

	WellList& operator = (const WellList &);

	WellList& operator = (WellList &&)  = delete;
	WellList(const WellList &)  = delete;
	WellList(WellList &&)  = delete;



	/// Read a well list
	bool read(DataReader & data_reader);
	bool read(const std::string& filename);

	/**
	 * @brief Add a new well (copy)
	 * 
	 * @param well : Well to add
	 */
	void add(const Well& well);


	unsigned nbr_wells() const {
		return (unsigned)wells_.size();
	}


	Well* well(WellId id) {
		assert(id>=0 && id <nbr_wells()  );
		return wells_[id].get();
	}


	const Well* well(WellId id) const{
		assert(id>=0 && id <nbr_wells()  );
		return wells_[id].get();
	}


	void convert(std::vector<Well*>&)const;

	/// check if data exist for every wells
	bool wells_data_exists(const std::string&name) const {
		for(auto &i:wells_) {
			if(!i->data_exists(name)) return false;
		}
		return true;
	}

	/// check if region list exists for every wells
	bool region_list_exists(const std::string&name) const {
		for(auto &i:wells_) {
			if(!i->region_list_exists(name)) return false;
		}
		return true;
	}


private :
	std::vector<std::unique_ptr<Well>> wells_;

	void set_well_id();
};







/*!
 * Directed Acyclic Graph optimized for Correlator input. 
 * CorGraph represents a well or a set of correlated wells as a 
 * directed acyclic graph. Each graph node corresponds to a 
 * layer top marker (or correlation line). Transitions between nodes
 * can store a cost. 
 */
class CorGraph {
public:
	typedef unsigned NodeId;

	CorGraph():size_(0),node_size_(0){};

    CorGraph( unsigned size, WellId wellid = 0 );

	CorGraph(const Well &well):
		CorGraph(well.well_size(),well.well_id()) {
	}

	void clear();

	~CorGraph(){};

	/// number of nodes
	unsigned size() const { return size_; }

	/// number of wells
	unsigned node_size() const { return node_size_; }

	/// return true if there is no path
	bool empty() const {
		return !size();
	}

    /*!
     * Access to the marker corresponding to the node \p node_id 
     * and to the well \p well_id.
     */
	MarkerId marker(NodeId node_id,unsigned well_id =0) const {
		assert( well_id <node_size_ );
		assert( node_id < size_ );
		return markers_[node_id*node_size_ + well_id];
	}

    /*!
     * Access to the array of markers corresponding to the node \p node_id. 
     * The size of the returned array is given by \p node_size()
     */
	const MarkerId* markers(NodeId node_id) const {
		assert (node_id < size_);
		return &markers_[node_id*node_size_];
	}

    /*!
     * Access to the number of edges starting from \p node_id
     */
	unsigned nbr_trans(NodeId node_id) const {
		assert(node_id<size_);
		return nodes_[node_id].nbr_trans;
	}

    /*!
     * Access to the transition cost corresponding to the edge \p edge_id 
     * arriving to from \p node_id.
     * \param edge_id   The local edge index (between 0 and nbr_trans(node_id-1))
     */
	CostValue trans_cost(NodeId dest_node_id, unsigned edge_id) const {
		assert( dest_node_id <size_);
		assert(edge_id <nbr_trans( dest_node_id ));
		return trans_[nodes_[dest_node_id].trans_id + edge_id].cost;
	}

    /*!
     * Access to the parent node corresponding to the edge \p edge_id
     * arriving to \p dest_node_id.
     * \param edge_id   The local edge index (between 0 and nbr_trans(node_id-1))
     */
	NodeId trans_from(NodeId dest_node_id, unsigned edge_id ) const {
		assert( dest_node_id <size_);
		assert(edge_id<nbr_trans( dest_node_id ));
		return trans_[nodes_[dest_node_id].trans_id + edge_id].from;
	}

    /*!
     * Access to the global WellId from the well index in this CorGraph.
     * \param local_well_index  Should be between 0 and \p node_size()-1
     */
	WellId well_id(unsigned local_well_index) const {
		assert ( local_well_index < node_size_);
		return wells_[local_well_index];
	}

	bool check_order() const;

	/// compute the real number of correlations
	unsigned nbr_correlation() const;


	/// CorGraph node
	class Node {
	private :
		const CorGraph& cg_;
		NodeId node_id_;


	public :
		Node(const CorGraph&cg,NodeId node_id) : cg_(cg),node_id_(node_id) {};

		unsigned size() const {return cg_.node_size();}

		MarkerId marker(unsigned well_id=0) const {return cg_.marker(node_id_,well_id);}
		const MarkerId * markers() const {return cg_.markers(node_id_);}

		unsigned nbr_trans() const { return cg_.nbr_trans(node_id_);}
		CostValue trans_cost(unsigned trans_id) const {return cg_.trans_cost( node_id_, trans_id );}
		Node trans_from(unsigned n) const;
	};


	const Node get_node(NodeId node_id) const{
		assert(node_id<size_);
		return Node(*this,node_id);
	}



	void dump_info(std::ostream & stream) const;
	void dump_info() const
			{dump_info(std::cout);}


	void dump(std::ostream & stream) const;
	void dump() const
			{dump(std::cout);}
	void dump(const std::string & filename) const
		{std::ofstream file(filename);dump(file);}

    /*! Writes this CorGraph in dot format to an ostream */
	void to_dot(std::ostream& stream = std::cout, bool show_cost = true) const;
    
    /*! Writes this CorGraph in dot format to a file */
    void to_dot(const std::string& filename, bool show_cost = true) const {
        std::ofstream file(filename);
        to_dot(file,show_cost);
    }

	void dump_well_id(std::ostream & stream = std::cout)const;

	/// - separated well id list (with starting -)
	std::string well_id_str() const;


	/// - separated well id list
	std::string well_string() const;

	///node string (- separated marker ids)
	std::string node_string(NodeId node_id) const;

	/// §6.2 Remove unreachable nodes (no in/out edges except start/end)
	void compact();


private:
	unsigned size_ ;
	unsigned node_size_;

	struct NodeInfo {
		unsigned trans_id;
		unsigned nbr_trans;

		NodeInfo(unsigned trans=0, unsigned nbr=0) :
			trans_id(trans),nbr_trans(nbr){}
	};

	struct TransInfo {
		NodeId from;
		CostValue cost;
		TransInfo(NodeId parent=0, CostValue cost =0.):
			from(parent),cost(cost){};
	};

	std::vector<MarkerId> markers_;
	std::vector<NodeInfo> nodes_;
	std::vector<TransInfo> trans_;
	std::vector<WellId> wells_;



	friend class CorGraph::Node;

	friend class CorGraphBuilder;
};

/*! \todo Sanity check. */
inline CorGraph::Node CorGraph::Node::trans_from(unsigned n) const {
    return cg_.get_node(cg_.trans_from(node_id_,n));
}

//==============================================================================
// CostHelper
//=============================================================================

/// Translates NodeId to MarkerId in CostFunc to provide easy access to the well marker indices. 
class CostHelper {
public:
	CostHelper(const CorGraph& cg1,const CorGraph& cg2):
		cg1_(cg1),cg2_(cg2)
		,size1_(cg1.node_size()),size2_(cg2.node_size()),size_(size1_+size2_)
		,src_(size_,0),dest_(size_,0) {}

	CostHelper(const CorGraph& cg1,const CorGraph& cg2,
			CorGraph::NodeId src1,CorGraph::NodeId dest1,
			CorGraph::NodeId src2,CorGraph::NodeId dest2
		):CostHelper(cg1,cg2) {
		set(src1,dest1,src2,dest2);
	}


	void set(CorGraph::NodeId src1,CorGraph::NodeId dest1,
			CorGraph::NodeId src2,CorGraph::NodeId dest2)
	{
		for(unsigned n= 0;n<size1();n++){
			src_[n] = cor_graph1().marker(src1,n);
			dest_[n] = cor_graph1().marker(dest1,n);
		}
		for(unsigned n= 0;n<size2();n++){
			src_[n+size1()] = cor_graph2().marker(src2,n);
			dest_[n+size1()] = cor_graph2().marker(dest2,n);
		}
	}

	void set_dest(CorGraph::NodeId dest1,CorGraph::NodeId dest2)
	{
		for(unsigned n= 0;n<size1();n++){
			dest_[n] = cor_graph1().marker(dest1,n);
		}
		for(unsigned n= 0;n<size2();n++){
			dest_[n+size1()] = cor_graph2().marker(dest2,n);
		}
	}

	unsigned size() const {return size_;}
	unsigned size1() const {return size1_;}
	unsigned size2() const {return size2_;}

	const CorGraph& cor_graph1() const {return cg1_;}
	const CorGraph& cor_graph2() const {return cg2_;}

    /*!
     \return    The current source index for well \p well_id
     */
	MarkerId src(unsigned well_id) const {
        assert( well_id <size() );
        return src_[well_id];
    }
    /*!
     \return    The current destination marker index for well \p well_id
     */
    MarkerId dest(unsigned well_id) const {
        assert( well_id <size() ); 
        return dest_[well_id];
    }

    /*!
     \return    True if the current marker for well \p well_id is a gap
     */
	bool same(unsigned well_id) const {
        assert( well_id <size());
        return dest_[well_id]==src_[well_id];
    }

    /*!
     \return    True if the start marker is at the top  for well
     */
	bool at_start(unsigned well_id) const {
        assert( well_id <size());
        return src_[well_id]==0;
    }


    /*!
     \return    True if the end marker is at the top  for well (\p well_id is a gap)
     */
	bool gap_at_start(unsigned well_id) const {
        assert( well_id <size());
        return dest_[well_id]==0;
    }

private :
	const CorGraph& cg1_;
	const CorGraph& cg2_;
	unsigned size1_,size2_,size_;
	std::vector<MarkerId> src_;
	std::vector<MarkerId> dest_;

};

/// Cost helper for Well access
class CostHelperWell {
public:
	CostHelperWell() {}
	CostHelperWell(const CorGraph& cg1,const CorGraph& cg2,const WellList&well_list)
		{set(cg1,cg2,well_list);}
	void set(const CorGraph& cg1,const CorGraph& cg2,const WellList&well_list);

	unsigned size() const
		{return wells_.size();}

	const Well & well(unsigned well_id) const{
		assert( well_id <size());
		return *(wells_[well_id]);
	}

private :
	std::vector<const Well*> wells_;
};



/// Region Data for Cost Helper
class CostHelperRegion {
public:
	CostHelperRegion(const CostHelper& cost_helper):
		cost_helper_(cost_helper){}

	CostHelperRegion(const CostHelper& cost_helper,const WellList&well_list,const std::string & region_name):
		cost_helper_(cost_helper){init(well_list,region_name);}

	/// Sets the regions from wellList
	/** \warning region_name is not checked
	 *
	 */
	void init(const WellList&well_list,const std::string & region_name);

	unsigned size()const
		{return cost_helper_.size();}

	const RegionList & region_list(unsigned well_id) const {
        assert( well_id <size());
        return *(region_[well_id]); 
    }

	/*! \return the region 
     */
    unsigned src_region(unsigned well_id ) const {
        return get_region(well_id,cost_helper_.src( well_id )); 
    }

	unsigned dest_region(unsigned well_id) const {
        return get_region(well_id,cost_helper_.dest( well_id )); 
    }

	unsigned get_region(unsigned well_id,unsigned n) const {
        assert(well_id<size());
        return region_[well_id]->get_region(n); 
    }

	/// return true if all destination markers are in the same region (0 is ignored)
	bool dest_in_same_region() const;

protected:
	const CostHelper& cost_helper_;
	std::vector<const RegionList *> region_;
};




/// Optimized band check  for Cost Helper
class CostHelperBand  {
public:
	CostHelperBand(const CostHelper& cost_helper):
		cost_helper_(cost_helper){}

	CostHelperBand(const CostHelper& cost_helper,const WellList&well_list,const std::string & region_name):
		cost_helper_(cost_helper){init(well_list,region_name);}

	/// set the regions from wellList
	/** \warning region_name is not checked
	 *
	 */
	void init(const WellList&well_list,const std::string & region_name);

	unsigned size()const
		{return cost_helper_.size();}

	unsigned nbr_band()const {return nbr_band_;}

	/// check if correlation doesnt cross the band (some before and some after)
	bool no_crossing()const;



protected:
	const CostHelper& cost_helper_;

	unsigned nbr_band_ =0;
	std::vector<int> data_;

	unsigned int get_idx(unsigned well,unsigned band)const
	{ return (band*size() +well) *2; }
	unsigned int get_idx(unsigned band)const
	{ return band*size() *2; }

};



/// Well Data for Cost Helper
class CostHelperData {
public:
	CostHelperData(const CostHelper& cost_helper):
		cost_helper_(cost_helper){}

	CostHelperData(const CostHelper& cost_helper,const WellList&well_list,const std::string & data_name):
		cost_helper_(cost_helper) {init(well_list,data_name);}

	/// set the data from wellList
	/** \warning data_name is not checked
	 *
	 */
	void init(const WellList&well_list,const std::string & data_name);

	unsigned size()const
		{return cost_helper_.size();}

	const Well::Data & data(unsigned n) const
		{assert(n<size());return *(data_[n]); }

	DataValue src_data(unsigned n) const
		{assert(n<size());return data_[n]->get(cost_helper_.src(n)); }

	DataValue dest_data(unsigned n) const
		{assert(n<size());return data_[n]->get(cost_helper_.dest(n)); }


	std::string data_name() const { return data_name_; };

	/// Compute variance on all dest_data
	DataValue dest_var() const;

protected:
	const CostHelper& cost_helper_;
	std::string data_name_;
    std::vector<const Well::Data *> data_;
};




/// CostHelper + CostHelperData
class DataCostHelper : public CostHelper{
public:
	DataCostHelper(const CorGraph& cg1,const CorGraph& cg2,const WellList&well_list,const std::string & data_name)
		:CostHelper(cg1,cg2),data_(*this) {
		data_.init(well_list,data_name);
	}

	const Well::Data & data(unsigned n)
		{return data_.data(n);}

	DataValue src_data(unsigned n) const
		{return data_.src_data(n); }

	DataValue dest_data(unsigned n) const
		{return data_.dest_data(n); }

	const CostHelperData & data_helper() const
		{return data_;}

private :
	CostHelperData data_;

};

/// CostHelper + CostHelperData + CostHelperRegion
class DataRegionCostHelper : public DataCostHelper {
public:
	DataRegionCostHelper(const CorGraph& cg1,const CorGraph& cg2,const WellList&well_list
			,const std::string & data_name,const std::string &region_name)
		: DataCostHelper(cg1,cg2,well_list,data_name),region_(*this)
			{region_.init(well_list,region_name);}

	const CostHelperRegion & region_helper() const
		{ return region_;}


	const RegionList & region_list(unsigned n) const
		{return region_.region_list(n); }

	unsigned src_region(unsigned n) const
		{return region_.src_region(n);}

	unsigned dest_region(unsigned n) const
		{return region_.dest_region(n);}


private:
	CostHelperRegion region_;
};



//==============================================================================
// CostComputer
//=============================================================================

/// Variance based Cost computer
class VarCostComputer : public DataCostHelper {
public:
	using DataCostHelper::DataCostHelper;

	/// Normal version
	bool operator()(CorGraph::NodeId s1,CorGraph::NodeId d1 ,CostValue,CorGraph::NodeId s2,CorGraph::NodeId d2,CostValue,CostValue &cost) {
		set(s1,d1,s2,d2);
        cost = (CostValue)data_helper().dest_var();
		return true;

	}

	/// dest only optimized
	bool operator()(CorGraph::NodeId d1 ,CorGraph::NodeId d2,CostValue &cost) {
		set_dest(d1,d2);
        cost = (CostValue)data_helper().dest_var();
		return true;

	}

};

/// Variance + Same Region  based Cost computer
class VarSRCostComputer : public DataRegionCostHelper {
public:
	using DataRegionCostHelper::DataRegionCostHelper;


    /// unoptimized
	bool operator()(CorGraph::NodeId s1,CorGraph::NodeId d1 ,CostValue,CorGraph::NodeId s2,CorGraph::NodeId d2,CostValue,CostValue &cost) {
		set(s1,d1,s2,d2);
		if (!region_helper().dest_in_same_region())
			return false;
        cost = (CostValue)data_helper().dest_var();
		return true;

	}

	/// dest only optimisation
	bool operator()(CorGraph::NodeId d1 ,CorGraph::NodeId d2,CostValue &cost) {
		set_dest(d1,d2);
		if (!region_helper().dest_in_same_region())
			return false;
        cost = (CostValue)data_helper().dest_var();
		return true;
	}


};




//==============================================================================
// Correlator
//=============================================================================


/// Computes correlations between 2 CorGraph using n-best graph-DTW.
class Correlator {
public:
	Correlator();
	~Correlator();

	Correlator(const Correlator &) = delete;
	Correlator(const Correlator &&) = delete;
    Correlator& operator=( const Correlator& ) = delete;

	/// §6.1 Set Sakoe-Chiba band width (0 = unlimited)
	void set_band_width(int w) { band_width_ = w; }
	int  get_band_width() const { return band_width_; }

	/// §6.5 Set beam search width per column (0 = full enumeration)
	void set_beam_width(int w) { beam_width_ = w; }
	int  get_beam_width() const { return beam_width_; }

	/*!
     * Standard correlator. Computes the first \p nbr_res least-cost paths between the starting 
     * and ending nodes of the CorGraphs \p graph1 and \p graph2. 
     */
	template <class COSTFUNC> void run(
        const CorGraph& graph1, const CorGraph& graph2, unsigned nbr_res, COSTFUNC& cost_func
    );

	/// optimized correlator (only dest is checked)
	template <class COSTFUNC> void run_dest_only(const CorGraph&g1,const CorGraph&g2,unsigned nbr_res,COSTFUNC& cost_func);

	/// optimized correlator ( dest is checked first)
	template <class COSTFUNC> void run_dest_opt(const CorGraph&g1,const CorGraph&g2,unsigned nbr_res,COSTFUNC& cost_func);

	/// §6.7 Anti-diagonal wavefront parallel correlator (same semantics as run())
	/// Processes cells along anti-diagonals d = node1 + node2 so that
	/// all cells on the same anti-diagonal are independent.
	template <class COSTFUNC> void run_wavefront(
		const CorGraph& graph1, const CorGraph& graph2, unsigned nbr_res, COSTFUNC& cost_func
	);


	/*!
     * write the cost matrix to a stream 
     */
	template <class COSTFUNC> static void write_cost_matrix(std::ostream &stream,const CorGraph& graph1, 
			const CorGraph& graph2, COSTFUNC& cost_func);

	/*!
     * write the cost matrix to a file 
     */
	template <class COSTFUNC> static void write_cost_matrix(const std::string &filename,const CorGraph& graph1, 
			const CorGraph& graph2, COSTFUNC& cost_func);


	void result2corgraph(CorGraph&,unsigned max_size=0,double min_dist = 0.0)const;


	/// Path Node for correlations
	class PathItem {
	public:
		PathItem(CorGraph::NodeId node1,CorGraph::NodeId node2,CostValue cost=0.,PathItem *prev =nullptr) :
			node1_(node1),node2_(node2),cost_(cost),prev_(prev) {}
		PathItem() :
			node1_(0),node2_(0),cost_(0.),prev_(nullptr) {}

		const PathItem * prev() const
			{return prev_;}

		CostValue cost() const
			{return cost_;}
		CostValue trans_cost() const
			{ return (prev_==nullptr?cost_:cost_-prev_->cost_);}

		CorGraph::NodeId node1() const
			{return node1_;}

		CorGraph::NodeId node2() const
			{return node2_;}

		void dump(std::ostream &)const;
		void dump(std::ostream &, const CorGraph& cg1,const CorGraph&cg2)const;

		/// compute distance between 2 path
		double path_distance(const PathItem& path, const CorGraph& cg1,const CorGraph&cg2) const;

		/// compute distance between 2 path item
		double item_distance(const PathItem& path, const CorGraph& cg1,const CorGraph&cg2) const;

		///return length of path
		unsigned length() const ;
	private:


		CorGraph::NodeId node1_;
		CorGraph::NodeId node2_;
		CostValue cost_;
		PathItem *prev_;
	};


	typedef std::vector <PathItem> PathItemList;


	const PathItemList & result() const {
		return *result_;
	}

	bool failled() const {
		return !result_ || !result_->size() ;
	}

	unsigned nbr_result() const {
		return (unsigned)(result_==nullptr?0:result_->size());
	}

	const PathItem & result (unsigned n) const {
		assert(n<nbr_result());
		return result()[n];
	}

	void dump_result(unsigned n,std::ostream & out =std::cout) const {
		result(n).dump(out);
	}

	void dump_result_marker(unsigned n,std::ostream & out =std::cout) const {
		result(n).dump(out,*graph1_,*graph2_);
	}

	double result_distance (unsigned n1,unsigned n2) const {
		assert(n1<nbr_result() && n2<nbr_result());
		return result(n1).path_distance(result(n2),*graph1_,*graph2_);
	}


private:
	const CorGraph * graph1_=nullptr;
	const CorGraph * graph2_=nullptr;


	CorGraph::NodeId graph1_size_=0;
	CorGraph::NodeId graph2_size_=0;
	unsigned max_res_=0;
	int band_width_=0;     // §6.1 Sakoe-Chiba band width (0=unlimited)
	int beam_width_=0;     // §6.5 Beam search width (0=full)
	std::vector<PathItemList> path_buffer_;
	// §6.3 Sparse path buffer for large grids (used when band_width_ > 0)
	std::unordered_map<uint64_t, PathItemList> sparse_path_buffer_;
	bool use_sparse_=false;

	PathItemList * cur_path_item_list_=nullptr;
	CostValue cur_max_cost_=0.;

	CorGraph::NodeId cur_node1_=0;
	CorGraph::NodeId cur_node2_=0;

	PathItemList * result_=nullptr;

	PathItemList & path_buffer(CorGraph::NodeId n1,CorGraph::NodeId n2)
	{
		if(use_sparse_) {
			uint64_t key = (static_cast<uint64_t>(n2) << 32) | n1;
			return sparse_path_buffer_[key];
		}
		assert(n1<graph1_size_);assert(n2<graph2_size_);
		return path_buffer_[n2*graph1_size_ +n1];
	}

    /*!
     * Starts the correlation between two starting nodes in two CorGraphs. 
     */
	void init_path(CorGraph::NodeId node1,CorGraph::NodeId node2);

    /*!
     * Adds the possible paths between two starting nodes to the list of paths.
     */
    void add_path_from(CorGraph::NodeId node1,CorGraph::NodeId node2,double cost);
    
    /*!
     * Terminates the various correlations between two CorGraph nodes. 
     * Truncates and sorts the paths if needed depending on \p max_nb_paths. 
     */
	void finish_path();

    /*!
     * Starts the correlation between two CorGraphs.
     */
	bool init_run(const CorGraph &graph1,const CorGraph &graph2,unsigned nbr_res);

    /*!
     * Terminates the correlation between two CorGraphs.
     */
	void finish_run();

};





void path_item_list2cor_graph(const Correlator::PathItemList::const_iterator &begin,const Correlator::PathItemList::const_iterator &end,const CorGraph& in1,const CorGraph& in2,CorGraph & out);


inline void path_item_list2cor_graph(const Correlator::PathItemList&results,const CorGraph& in1,const CorGraph& in2,CorGraph & out) {
	path_item_list2cor_graph(results.cbegin(),results.cend(),in1, in2, out);
}

///  Write a a part of an item list to a stream
void path_item_list_write(std::ostream & out,const Correlator::PathItemList::const_iterator &begin,const Correlator::PathItemList::const_iterator &end,const CorGraph& in1,const CorGraph& in2);



inline void path_item_list_write(std::ostream & out,const Correlator::PathItemList&results,const CorGraph& in1,const CorGraph& in2) {
	path_item_list_write(out, results.cbegin(),results.cend(),in1, in2);
}
inline void path_item_list_write(const std::string& filename,const Correlator::PathItemList&results,const CorGraph& in1,const CorGraph& in2) {
	std::ofstream file(filename);
	path_item_list_write(file, results.cbegin(),results.cend(),in1, in2);
}
inline void path_item_list_write(const std::string& filename,const Correlator::PathItemList::const_iterator &begin,const Correlator::PathItemList::const_iterator &end,const CorGraph& in1,const CorGraph& in2){
	std::ofstream file(filename);
	path_item_list_write(file, begin,end,in1,in2);
}



// ====================== run* implementation ===================================

template <class COSTFUNC> void Correlator::run(
		const CorGraph &cg1,const CorGraph&cg2,unsigned nbr_res,COSTFUNC& cost_func) {
	CorGraph::NodeId size1 = cg1.size();
	CorGraph::NodeId size2 = cg2.size();

	if(!init_run(cg1,cg2,nbr_res))
		return;

	for (CorGraph::NodeId node1 =0;node1<size1;node1++) {
		unsigned nbr_trans1 = cg1.nbr_trans(node1);
		for (CorGraph::NodeId node2 =0;node2<size2;node2++) {
			if(node1==0 && node2==0) continue;

			// §6.1 Sakoe-Chiba band constraint: skip cells outside the band
			if(band_width_ > 0) {
				// Map node indices to relative positions in [0,1] range
				double rel1 = (size1 > 1) ? static_cast<double>(node1) / (size1-1) : 0.;
				double rel2 = (size2 > 1) ? static_cast<double>(node2) / (size2-1) : 0.;
				double band_frac = static_cast<double>(band_width_) / std::max(size1, size2);
				if(std::fabs(rel1 - rel2) > band_frac) continue;
			}

			init_path(node1,node2);

			double cost;

			unsigned nbr_trans2 = cg2.nbr_trans(node2);

			for (unsigned trans2=0;trans2<nbr_trans2;trans2++) {
				CorGraph::NodeId from2 = cg2.trans_from(node2,trans2);
				cost=0.;
				if (cost_func(node1,node1,0.,from2,node2,cg2.trans_cost(node2,trans2),cost))
					add_path_from(node1,from2,cost);
			}


			for (unsigned trans1=0;trans1<nbr_trans1;trans1++) {
				CorGraph::NodeId from1 = cg1.trans_from(node1,trans1);
				double trans1_cost = cg1.trans_cost(node1,trans1);
				cost=0.;
				if (cost_func(from1,node1,trans1_cost,node2,node2,0.,cost))
					add_path_from(from1,node2,cost);
				for (unsigned trans2=0;trans2<nbr_trans2;trans2++) {
					CorGraph::NodeId from2 = cg2.trans_from(node2,trans2);
					cost=0.;
					if (cost_func(from1,node1,trans1_cost,from2,node2,cg2.trans_cost(node2,trans2),cost))
						add_path_from(from1,from2,cost);
				}


			}
			finish_path();

		}

	}
	finish_run();

};

template <class COSTFUNC> void Correlator::run_dest_only(
		const CorGraph &cg1,const CorGraph&cg2,unsigned nbr_res,COSTFUNC& cost_func) {
	CorGraph::NodeId size1 = cg1.size();
	CorGraph::NodeId size2 = cg2.size();

	if (!init_run(cg1,cg2,nbr_res))
		return;

	for (CorGraph::NodeId node1 =0;node1<size1;node1++) {
		unsigned nbr_trans1 = cg1.nbr_trans(node1);
		for (CorGraph::NodeId node2 =0;node2<size2;node2++) {
			if(node1==0 && node2==0) continue;

			init_path(node1,node2);

			double cost=0.;
			if (! cost_func(node1,node2,cost) )
				continue;

			unsigned nbr_trans2 = cg2.nbr_trans(node2);

			for (unsigned trans2=0;trans2<nbr_trans2;trans2++) {
				CorGraph::NodeId from2 = cg2.trans_from(node2,trans2);
					add_path_from(node1,from2,cost);
			}


			for (unsigned trans1=0;trans1<nbr_trans1;trans1++) {
				CorGraph::NodeId from1 = cg1.trans_from(node1,trans1);
				add_path_from(from1,node2,cost);
				for (unsigned trans2=0;trans2<nbr_trans2;trans2++) {
					CorGraph::NodeId from2 = cg2.trans_from(node2,trans2);
					add_path_from(from1,from2,cost);
				}

			}
			finish_path();

		}

	}
	finish_run();

};


// optimized correlator ( dest is checked first)
template <class COSTFUNC> void Correlator::run_dest_opt(
		const CorGraph &cg1,const CorGraph&cg2,unsigned nbr_res,COSTFUNC& cost_func) {
	CorGraph::NodeId size1 = cg1.size();
	CorGraph::NodeId size2 = cg2.size();

	if(!init_run(cg1,cg2,nbr_res))
		return;

	for (CorGraph::NodeId node1 =0;node1<size1;node1++) {
		unsigned nbr_trans1 = cg1.nbr_trans(node1);
		for (CorGraph::NodeId node2 =0;node2<size2;node2++) {
			if(node1==0 && node2==0) continue;

			init_path(node1,node2);

			double dest_cost=0.;
			if (! cost_func(node1,node2,dest_cost) )
				continue;

			unsigned nbr_trans2 = cg2.nbr_trans(node2);
			double cost;
			for (unsigned trans2=0;trans2<nbr_trans2;trans2++) {
				CorGraph::NodeId from2 = cg2.trans_from(node2,trans2);
				cost=dest_cost;
				if (cost_func(node1,node1,0.,from2,node2,cg2.trans_cost(node2,trans2),cost))
					add_path_from(node1,from2,cost);
			}


			for (unsigned trans1=0;trans1<nbr_trans1;trans1++) {
				CorGraph::NodeId from1 = cg1.trans_from(node1,trans1);
				double trans1_cost = cg1.trans_cost(node1,trans1);
				cost=dest_cost;
				if (cost_func(from1,node1,trans1_cost,node2,node2,0.,cost))
					add_path_from(from1,node2,cost);
				for (unsigned trans2=0;trans2<nbr_trans2;trans2++) {
					CorGraph::NodeId from2 = cg2.trans_from(node2,trans2);
					cost=dest_cost;
					if (cost_func(from1,node1,trans1_cost,from2,node2,cg2.trans_cost(node2,trans2),cost))
						add_path_from(from1,from2,cost);
				}


			}
			finish_path();

		}

	}
	finish_run();

};

// §6.7 Anti-diagonal wavefront implementation
template <class COSTFUNC> void Correlator::run_wavefront(
		const CorGraph &cg1,const CorGraph&cg2,unsigned nbr_res,COSTFUNC& cost_func) {
	CorGraph::NodeId size1 = cg1.size();
	CorGraph::NodeId size2 = cg2.size();

	if(!init_run(cg1,cg2,nbr_res))
		return;

	// Process anti-diagonals d = node1 + node2 (0 to size1+size2-2)
	// All cells on the same anti-diagonal are independent (they only depend on
	// cells from earlier diagonals), enabling future parallelisation.
	unsigned max_diag = size1 + size2 - 2;
	for (unsigned diag = 0; diag <= max_diag; diag++) {
		// Cells on this diagonal: node1 + node2 == diag
		CorGraph::NodeId n1_start = (diag < size2) ? 0 : (diag - size2 + 1);
		CorGraph::NodeId n1_end = std::min(diag, size1 - 1);

		// §6.7: Anti-diagonal cells are independent — parallelise with OpenMP
		// Note: sparse path buffer (unordered_map) is not thread-safe for concurrent
		// operator[] — disable parallelism in sparse mode.
		#pragma omp parallel for schedule(dynamic) if (!use_sparse_ && n1_end - n1_start > 16)
		for (CorGraph::NodeId node1 = n1_start; node1 <= n1_end; node1++) {
			CorGraph::NodeId node2 = diag - node1;

			if(node1==0 && node2==0) continue;

			// §6.1 Sakoe-Chiba band constraint
			if(band_width_ > 0) {
				double rel1 = (size1 > 1) ? static_cast<double>(node1) / (size1-1) : 0.;
				double rel2 = (size2 > 1) ? static_cast<double>(node2) / (size2-1) : 0.;
				double band_frac = static_cast<double>(band_width_) / std::max(size1, size2);
				if(std::fabs(rel1 - rel2) > band_frac) continue;
			}

			// Thread-local path state (avoids data race on member variables)
			PathItemList& local_pil = path_buffer(node1, node2);
			local_pil.clear();
			CostValue local_max_cost = 0.;

			double cost;
			unsigned nbr_trans1 = cg1.nbr_trans(node1);
			unsigned nbr_trans2 = cg2.nbr_trans(node2);

			// Lambda to add path from a source cell
			auto local_add_path = [&](CorGraph::NodeId from1, CorGraph::NodeId from2, double c) {
				PathItemList& from = path_buffer(from1, from2);
				if (!from.size()) return;
				for (auto& i : from) {
					CostValue path_cost = c + i.cost();
					if (local_pil.size() >= max_res_ && path_cost > local_max_cost)
						continue;
					local_pil.push_back(PathItem(node1, node2, path_cost, &i));
					if (local_max_cost < path_cost)
						local_max_cost = path_cost;
				}
			};

			for (unsigned trans2=0;trans2<nbr_trans2;trans2++) {
				CorGraph::NodeId from2 = cg2.trans_from(node2,trans2);
				cost=0.;
				if (cost_func(node1,node1,0.,from2,node2,cg2.trans_cost(node2,trans2),cost))
					local_add_path(node1,from2,cost);
			}

			for (unsigned trans1=0;trans1<nbr_trans1;trans1++) {
				CorGraph::NodeId from1 = cg1.trans_from(node1,trans1);
				double trans1_cost = cg1.trans_cost(node1,trans1);
				cost=0.;
				if (cost_func(from1,node1,trans1_cost,node2,node2,0.,cost))
					local_add_path(from1,node2,cost);
				for (unsigned trans2=0;trans2<nbr_trans2;trans2++) {
					CorGraph::NodeId from2 = cg2.trans_from(node2,trans2);
					cost=0.;
					if (cost_func(from1,node1,trans1_cost,from2,node2,cg2.trans_cost(node2,trans2),cost))
						local_add_path(from1,from2,cost);
				}
			}

			// Finish: trim to max results
			unsigned effective_max = max_res_;
			if (beam_width_ > 0 && static_cast<unsigned>(beam_width_) < effective_max)
				effective_max = static_cast<unsigned>(beam_width_);
			if (local_pil.size() > effective_max) {
				std::partial_sort(local_pil.begin(), local_pil.begin() + effective_max,
					local_pil.end(), [](const PathItem& a, const PathItem& b){ return a.cost() < b.cost(); });
				local_pil.resize(effective_max);
			}
		}
	}
	finish_run();
};

// ====================== write-cost_matrix implementation ===================================
template <class COSTFUNC> void Correlator::write_cost_matrix(const std::string& file_name,
		const CorGraph &cg1,const CorGraph&cg2,COSTFUNC& cost_func) {
			std::ofstream file(file_name+cg1.well_string()+"_"+cg2.well_string()+".txt");
			write_cost_matrix(file,cg1,cg2,cost_func);
}

template <class COSTFUNC> void Correlator::write_cost_matrix(std::ostream & out,
		const CorGraph &cg1,const CorGraph&cg2,COSTFUNC& cost_func) {

	CorGraph::NodeId size1 = cg1.size();
	CorGraph::NodeId size2 = cg2.size();

	// header
	out<<cg1.well_string()<<" "<<cg2.well_string()<<'\n';

	for (CorGraph::NodeId node1 =0;node1<size1;node1++) {
		unsigned nbr_trans1 = cg1.nbr_trans(node1);
		for (CorGraph::NodeId node2 =0;node2<size2;node2++) {
			if(node1==0 && node2==0) continue;

			double dest_cost=0.;
			bool dest_ok =cost_func(node1,node2,dest_cost) ;

			unsigned nbr_trans2 = cg2.nbr_trans(node2);
			double cost;
			for (unsigned trans2=0;trans2<nbr_trans2;trans2++) {
				CorGraph::NodeId from2 = cg2.trans_from(node2,trans2);
				cost=dest_cost;
				bool ok = dest_ok && cost_func(node1,node1,0.,from2,node2,cg2.trans_cost(node2,trans2),cost);
				out<<cg1.node_string(node1)<<'-'<<cg2.node_string(from2)<<' '
					<<cg1.node_string(node1)<<'-'<<cg2.node_string(node2)<<' '
					<< (ok?cost:-1.)<<'\n';

			}
			for (unsigned trans1=0;trans1<nbr_trans1;trans1++) {
				CorGraph::NodeId from1 = cg1.trans_from(node1,trans1);
				double trans1_cost = cg1.trans_cost(node1,trans1);
				cost=dest_cost;
				bool ok = dest_ok && cost_func(from1,node1,trans1_cost,node2,node2,0.,cost);
				out<<cg1.node_string(from1)<<'-'<<cg2.node_string(node2)<<' '
					<<cg1.node_string(node1)<<'-'<<cg2.node_string(node2)<<' '
					<< (ok?cost:-1.)<<'\n';
				for (unsigned trans2=0;trans2<nbr_trans2;trans2++) {
					CorGraph::NodeId from2 = cg2.trans_from(node2,trans2);
					cost=dest_cost;
					ok = dest_ok && cost_func(from1,node1,trans1_cost,from2,node2,cg2.trans_cost(node2,trans2),cost);
					out<<cg1.node_string(from1)<<'-'<<cg2.node_string(from2)<<' '
						<<cg1.node_string(node1)<<'-'<<cg2.node_string(node2)<<' '
						<< (ok?cost:-1.)<<'\n';
				}
			}
		}
	}

};


} // namespace WeCo



#endif
