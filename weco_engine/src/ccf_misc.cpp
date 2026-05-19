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
// Variance Cost Function                                                    //
// ========================================================================= //

class _CCFPartVar:public CCFPart{
public:
	_CCFPartVar(const Project &project,const CCFContext& ctx,const std::string& data_name,float weight=1.0) :
		CCFPart(ctx),data(ctx,project.well_list(),data_name),weight_(weight) {
		};

	CostHelperData data;
	CostValue weight_;

	virtual bool dest_cost(CostValue& cost) override{
		cost += (CostValue)data.dest_var()*weight_;
		return true;
	}

	virtual bool dest_only() const override
		{ return true;}

};

class _CCFPartVarFactory : public CCFGlobalPartFactory {
public:
	_CCFPartVarFactory(const std::string & num) : 
		option_data{"var-data"+num,"","data name for variance cost "+num,"50CCF.Variance."+num},
		option_weight{"var-weight"+num,1.,"weight for variance cost "+num,"50CCF.Variance."+num}
		{}

protected:
	OptionData option_data;
	OptionFloat option_weight;

	virtual bool test(const Project& project) const
		{ return option_data.project_check(project,true); }

	virtual  CCFPart * create(const Project& project,const CCFContext&ctx) const {
		if (!option_data) return nullptr;
		return new _CCFPartVar(project,ctx,option_data(),option_weight());
	}
};

static _CCFPartVarFactory _ccfpart_factory_var1("");
static _CCFPartVarFactory _ccfpart_factory_var2("2");
static _CCFPartVarFactory _ccfpart_factory_var3("3");
static _CCFPartVarFactory _ccfpart_factory_var4("4");
static _CCFPartVarFactory _ccfpart_factory_var5("5");

// ========================================================================= //
// Same Region Cost Function                                                 //
// ========================================================================= //

class _CCFPartSR:public CCFPart{
public:
	_CCFPartSR(const Project &project,const CCFContext& ctx,const std::string& region_name) :
		CCFPart(ctx),region(ctx,project.well_list(),region_name) {};

	CostHelperRegion region;

	virtual bool dest_cost(CostValue& ) override{
		return region.dest_in_same_region();
	}

	virtual bool dest_only() const override
		{ return true;}

};

class _CCFPartSRFactory : public CCFGlobalPartFactory {
public:
	_CCFPartSRFactory(const std::string & num) :
		option_region{"same-region"+num,"","regions used for same region check "+num,"50CCF.SameRegion."+num}
		{}

protected:
	OptionRegion option_region;
	

	virtual bool test(const Project& project) const
		{ return option_region.project_check(project,true); }

	virtual  CCFPart * create(const Project& project,const CCFContext&ctx) const {
		if (!option_region) return nullptr;
		return new _CCFPartSR(project,ctx,option_region());
	}
};

// ========================================================================= //
// No Crossing Cost Function                                                 //
// ========================================================================= //

class _CCFPartNC:public CCFPart{
public:
	_CCFPartNC(const Project &project,const CCFContext& ctx,const std::string& region_name) :
		CCFPart(ctx),band(ctx,project.well_list(),region_name) {};

	CostHelperBand band;

	virtual bool dest_cost(CostValue& ) override{
		return band.no_crossing();
	}

	virtual bool dest_only() const override
		{ return true;}

};

class _CCFPartNCFactory : public CCFGlobalPartFactory {
public:
	_CCFPartNCFactory(const std::string & num) : 
		option_region{"no-crossing"+num,"","regions used for no crossing check "+num,"50CCF.NoCrossing."+num}
		{}

protected:
	OptionRegion option_region;

	virtual bool test(const Project& project) const
		{ return option_region.project_check(project,true);}

	virtual  CCFPart * create(const Project& project,const CCFContext&ctx) const {
		if (!option_region) return nullptr;
		return new _CCFPartNC(project,ctx,option_region());
	}
};


static _CCFPartSRFactory _ccfpart_factory_same_region1("");
static _CCFPartNCFactory _ccfpart_factory_no_crossing1("");
static _CCFPartSRFactory _ccfpart_factory_same_region2("2");
static _CCFPartNCFactory _ccfpart_factory_no_crossing2("2");
static _CCFPartSRFactory _ccfpart_factory_same_region3("3");
static _CCFPartNCFactory _ccfpart_factory_no_crossing3("3");


}
} //namespace WeCo
