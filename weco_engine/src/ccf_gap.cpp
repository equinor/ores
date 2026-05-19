/*
 * Association Scientifique pour la Geologie et ses Applications (ASGA)
 *
 * Copyright � 2018 ASGA. All Rights Reserved.
 *
 * This program is a Trade Secret of the ASGA and it is not to be:
 *  - reproduced, published, or disclosed to other,
 *  - distributed or displayed,
 *  - used for purposes or on Sites other than described in the GOCAD
 *    Advancement Agreement, without the prior written authorization
 *    of the ASGA.
 *
 * Licencee agrees to attach or embed this Notice on all copies of the program,
 * including partial copies or modified versions thereof.
 */


#include <weco/project.h>

namespace WeCo {
namespace  {
    
// ========================================================================= //
// Gap Cost Function                                                         //
// ========================================================================= //

class _CCFPartGapCostFunc:public CCFPart{
public:
	_CCFPartGapCostFunc(const Project &project,const CCFContext& ctx,const std::string& data_name,DataValue mult) :
		CCFPart(ctx),data(ctx,project.well_list(),data_name),cost_mult(mult) {};

	CostHelperData data;
	CostValue cost_mult;

	bool full_cost( CostValue&cost) override {
		for(unsigned well=0;well<context.size();well++)  {
			if (context.same(well)) 
				cost += data.src_data(well)*cost_mult;
		}
		return true;
	}


};

class _CCFPartGapCostFuncFactory : public CCFGlobalPartFactory {
public:

protected:

	OptionData option_data{"gap-cost-func","","Gap Cost Function data name","50CCF.GapCost"};
	OptionFloat option_mult{"gap-cost-func-mult",1.,"Gap Cost Function multiplier","50CCF.GapCost"};

	virtual bool test(const Project& project) const
		{ return option_data.project_check(project,true); }

	virtual  CCFPart * create(const Project& project,const CCFContext&ctx) const {
		if (!option_data) return nullptr;
		return new _CCFPartGapCostFunc(project,ctx,option_data(),option_mult());
	}
};

static  _CCFPartGapCostFuncFactory _ccfpart_factory_gap_cost;

// ========================================================================= //
// Const Gap Cost Function                                                   //
// ========================================================================= //

class _CCFPartConstGapCost:public CCFPart{
public:
	_CCFPartConstGapCost(const Project &project,const CCFContext& ctx,DataValue gap_cost,DataValue gap_cost_start,DataValue gap_cost_end) :
		CCFPart(ctx),gap_cost_(gap_cost),
        gap_cost_start_(gap_cost_start?gap_cost_start>=0.:gap_cost),
        gap_cost_end_(gap_cost_end?gap_cost_end>=0.:gap_cost)
        {};

	CostValue gap_cost_;
    CostValue gap_cost_start_;
    CostValue gap_cost_end_;


	bool full_cost( CostValue&cost) override {
		for(unsigned well=0;well<context.size();well++)  {
			if(context.gap_at_start(well))
				cost += gap_cost_start_;
			else if(context.gap_at_end(well))
				cost += gap_cost_end_;
			else if (context.same(well))
                    cost += gap_cost_;
		}
		return true;
	}
};

class _CCFPartConstGapCostFactory : public CCFGlobalPartFactory {
public:

protected:

	
	OptionFloat option_cost{"const-gap-cost",0.,"Constant Gap Cost","50CCF.ConstGapCost"};
	OptionFloat option_cost_start{"const-gap-cost-start",-1.,"Constant Gap Cost at well start","50CCF.ConstGapCost"};
	OptionFloat option_cost_end{"const-gap-cost-end",-1.,"Constant Gap Cost at well end","50CCF.ConstGapCost"};

	virtual  CCFPart * create(const Project& project,const CCFContext&ctx) const {
		if (option_cost() <=0.) return nullptr;
		return new _CCFPartConstGapCost(project,ctx,option_cost(),option_cost_start(),option_cost_end());
	}
};

static  _CCFPartConstGapCostFactory _ccfpart_factory_const_gap_cost;
}
} //namespace WeCo
