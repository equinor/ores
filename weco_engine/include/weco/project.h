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

/*
 * weco_project.h
 *
 *  Created on: Dec 21, 2017
 *      Author: antoine16
 */

#ifndef INCLUDE_WECO_PROJECT_H_
#define INCLUDE_WECO_PROJECT_H_

#include <functional>
#include <weco.h>
#include "scheduler.h"
#include <map>
#include <tuple>
#include "option.h"
#include "autoreg.h"

namespace WeCo {

class Project;

/*! 
 * Provides information for implementing concrete \p Project::CostFunction classes
 */
class CCFContext : public CostHelper {
public :
	//CCFContext() {};
	CCFContext(const CorGraph&cg1,const CorGraph & cg2,const WellList& well_list):
		CostHelper(cg1,cg2),chwell_(cg1,cg2,well_list) {}

	void set_parent_cost(CostValue c1,CostValue c2) {
		parent_cost1_ = c1;
		parent_cost2_ = c2;
	}

	CostValue parent_cost1() const
		{ return parent_cost1_;}
	CostValue parent_cost2() const
		{ return parent_cost2_;}

	const Well& well( unsigned well_id ) const {
		return chwell_.well( well_id );
	}

    /*!
     \return    True if the end marker is at the bottom  for well
     */
	bool at_end(unsigned well_id) const {
        assert( well_id <size());
        return dest(well_id)==well(well_id).well_size()-1;
    }

    /*!
     \return    True if the src marker is at the bottom  for well (\p well_id is a gap)
     */
	bool gap_at_end(unsigned well_id) const {
        assert( well_id <size());
        return src(well_id)==well(well_id).well_size()-1;
    }


private:
	CostValue parent_cost1_ = 0.;
	CostValue parent_cost2_ = 0.;
	CostHelperWell chwell_;

};


/*!
 * Abstract base class for elementary cost functions integrated in 
 * elementary composite cost functions.
 * 
 * One of the two virtual cost functions must be overloaded by derived classes:
 * \li \p dest_cost if \p dest_only() returns true 
 * \li \p full_cost if \p dest_only() returns false
 *
 * CLient code should use CCFPartFactory to instanciate derived classes. 
 *
 * \see _CCFPartTest1, _CCFPartTest2, _CCFPartTest3
 */
class CCFPart {
protected:
	CCFPart(const CCFContext& ctx):
		context(ctx){}

	const CCFContext& context;

public:
	virtual ~CCFPart() {}

    /*! Correlation cost based only on the destination node C(i,j). 
     * This corresponsds to a simplified version of Eq (1) 
     * in Lallier et al 2016 (assumes that transition cost is null). 
     * This simplification is useful for optimization. 
     * \return true if the \p cost value is computed, false if cost is infinite
     */
	virtual bool dest_cost( CostValue& cost ) { 
        return true;
    }

    /*! Correlation cost based both on the destination node C(i,j) 
     * and transition cost t_{i,origin_i}^{j,origin_j} in Eq (1) of Lallier et al 2016
     * \return true if the \p cost value is computed, false if cost is infinite
     */
    virtual bool full_cost( CostValue& cost ) {
        return true;
    }

    /*!
     * Tells whether this cost should include the transition cost or 
     * use as a simplification only the destination C(i,j) cost. 
     * Computation is faster when this function returns true. 
     */
    virtual bool dest_only() const {
        return false;
    }

};


class CCFPartFactory{
public:

	virtual ~CCFPartFactory() {}
	virtual bool test(const Project&) const
		{ return true; }
	virtual  CCFPart * create(const Project&,const CCFContext&) const
		{ return nullptr;}

};


class CCFGlobalPartFactory: public CCFPartFactory,
	public AutoReg<CCFGlobalPartFactory> {
};

class CCFProjectPartFactory: public CCFPartFactory {
public:
	CCFProjectPartFactory(Project&project );
};


// =================== Options =================================

class OptionData : public OptionString {
public:
	using OptionString::OptionString;

	std::string const type() const override
		{return "Data";}

	bool project_check(Project const& project,bool only_if_set=false)const;
};

class OptionRegion : public OptionString {
public:
	using OptionString::OptionString;

	std::string const type() const override
		{return "Region";}

	bool project_check(Project const& project,bool only_if_set=false)const;
};



/// WeCo project: run correlations from options
class Project : public OptionParser {

public:
	/// Base class for Project Cost Function
	class CostFunction: public NDAutoReg<CostFunction> {
	public:
		CostFunction(std::string const & name,std::string const &desc ) 
			:NDAutoReg(name,desc){}

		virtual bool check_param(const Project&) const
			{ return true;}

		virtual void run(const Project&,Correlator&,const CorGraph&,const CorGraph&) const=0;

	};



public:
	using CCFPartFactoryList = std::vector<std::unique_ptr<CCFPartFactory>>;


	Project();
	~Project();

	using TaskOrderFactory = NDVAutoReg<WellVector2TasksFunc>;
	
	const WellList & well_list() const {return well_list_;}
	/*WellList & well_list() {return well_list_;}*/

	/**
	 * @brief Run project from WellList file 
	 * 
	 * @param data_file WellList filename
	 * @return false in case of errro
	 */
	bool run(const std::string& data_file);


	/**
	 * @brief Run project from WellList
	 * 
	 * @param well_list WellList
	 * @return false in case of errro
	 */
	bool run(const WellList& well_list);

	const WeCo::CorGraph &result() const {
		return scheduler_->result();
	}

	/// show help
	void option_help(std::ostream& out = std::cout )const override;

	bool option_check()const;

	bool project_parse_args(int argc, char * argv[],std::string & data);


	// CCF parts
	void add_ccf_part(CCFPartFactory* fact )
		{ ccf_part_factories_.emplace_back(fact); }

	const CCFPartFactoryList & ccf_part_factories() const
		{ return ccf_part_factories_;}

	// Order function
	void set_order_func(WellVector2TasksFunc func)
		{ order_func_ =func;}
	void clear_order_func() 
		{ order_func_ =nullptr;}

private :
	class Task : public CorScheduler::Task {
	public :
		Task(const CorScheduler::TaskParent& parent1,const CorScheduler::TaskParent& parent2,Project &);
		void run(Correlator &) override;
	private:
		Project& project_;
		friend class Project;
	};


	CorScheduler * scheduler_;
	WellList well_list_;

	const CostFunction * cost_function_=nullptr;

	friend class Task;

	CCFPartFactoryList ccf_part_factories_;

	WellVector2TasksFunc order_func_;

protected:

	/// run project (well_list must be defined)
	bool run_();


	static NDAROptionSelect<TaskOrderFactory> option_order;
	static NDAROptionSelect<CostFunction> option_cost_function;
	static OptionInt    option_thread;

	static OptionInt    option_max_cor;
	static OptionInt    option_nbr_cor;
	static OptionFloat  option_min_dist;

	static OptionInt    option_out_nbr_cor;
	static OptionFloat  option_out_min_dist;

	static OptionString option_out_dot;
	static OptionString option_out_file;

	static OptionString option_step_dot;
	static OptionString option_step_file;


	static OptionBool   option_debug_cor_info;

	static OptionString option_order_dot;
	static OptionBool option_order_only;

	// §6.1 Sakoe-Chiba band width (0 = unlimited)
	static OptionInt option_band_width;
	// §6.5 Beam width (0 = unlimited / full enumeration)
	static OptionInt option_beam_width;
	// §12.7 Cost floor (minimum cost per transition)
	static OptionFloat option_cost_floor;
	// §4.2 Weighted-average cost combination mode
	static OptionBool option_cost_weighted_avg;

public:
	static OptionString option_cost_matrix;

	int band_width() const { return option_band_width(); }
	int beam_width() const { return option_beam_width(); }
	double cost_floor() const { return option_cost_floor(); }
	bool cost_weighted_avg() const { return option_cost_weighted_avg(); }

	int max_cor()const 
	   	{return option_max_cor();}
};



#ifdef GEN_PLUGIN
bool load_plugin(const std::string& file_name);
#endif


}// namespace WeCo


#endif /* INCLUDE_WECO_PROJECT_H_ */
