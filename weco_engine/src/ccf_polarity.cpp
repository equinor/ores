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
// Magnetic polarity Cost Function                                           //
// ========================================================================= //

/*!
 * A magnetic polarity cost function
 */
class _CCFPartPolarity:public CCFPart{
public:
	_CCFPartPolarity(const Project &project,const CCFContext& ctx,const std::string& region_name
		,DataValue cost_same,DataValue cost_diff,DataValue cost_start,DataValue cost_end) :
		CCFPart(ctx),region(ctx,project.well_list(),region_name),cost_same_(cost_same)
			,cost_diff_(cost_diff),cost_start_(cost_start),cost_end_(cost_end) {};

	CostHelperRegion region;
	CostValue cost_same_;
	CostValue cost_diff_;
	CostValue cost_start_;
	CostValue cost_end_;

	bool full_cost( CostValue& cost) override {
		unsigned polarity = 99999;

		// Force polarity to remain the same for all destination well samples
		for(unsigned well=0;well<context.size();well++) {
			if (context.same(well)) // Gap at well
				continue;
            // if( region.dest_region ) // Need to continue if polarity is undefined. 
			else if (polarity == 99999) 
				polarity = region.dest_region(well);  
			else if (polarity != region.dest_region(well))
				return false;
		}

		// Deal with gap cost
		for(unsigned well=0;well<context.size();well++) {
			if (!context.same(well)) 
				continue;
			if (polarity == region.dest_region(well)) {
				if (context.src(well) == 0) // Top marker
					cost += std::min(cost_start_,cost_same_);
				else if (context.src(well) == context.well(well).well_size()-1)
					cost += std::min(cost_end_,cost_same_);
				else 
					cost += cost_same_;
			} else if (context.src(well) == 0)
					cost += cost_start_;
			else if (context.src(well) == context.well(well).well_size()-1)
					cost += cost_end_;
			else 
					cost += cost_diff_;
		}

		return true;
	}

};

class _CCFPartPolarityFactory : public CCFGlobalPartFactory {
public:

protected:
	OptionRegion option_region{"polarity-region","","Polarity test: region name","50CCF.Polarity"};
	OptionFloat option_cost_diff{"polarity-cost-diff",.5,"Polarity test: gap cost if polarity is not the same","50CCF.Polarity"};
	OptionFloat option_cost_same{"polarity-cost-same",.5,"Polarity test: gap cost if polarity is the same","50CCF.Polarity"};
	OptionFloat option_cost_start{"polarity-cost-start",.5,"Polarity test: gap cost at well start","50CCF.Polarity"};
	OptionFloat option_cost_end{"polarity-cost-end",.5,"Polarity test: gap cost at well start","50CCF.Polarity"};


	virtual bool test(const Project& project) const
		{ return option_region.project_check(project,true); }

	virtual  CCFPart * create(const Project& project,const CCFContext&ctx) const {
		if (!option_region)  return nullptr;
		return new _CCFPartPolarity(project,ctx,option_region(),
			option_cost_diff(), option_cost_same(),
			option_cost_start(),option_cost_end()
		);
	}
};

static _CCFPartPolarityFactory _ccfpart_factory_polarity;

} // End of anonymous namespace
    
} //namespace WeCo
