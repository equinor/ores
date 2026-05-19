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

#include <weco/project.h>

namespace WeCo {

namespace  {


//=============================== Cost Functions Test1 ================================================

/*
 * sample cost function : return sum(data)+constant(cost-float-param)
 *
 */

class _CostFunctionTest: public Project::CostFunction {
	class _CostFunction:public CostHelper {
	public:
		_CostFunction(const CorGraph&cg1,const CorGraph&cg2,const WellList& wl,
				const std::string & data_name,double float_param
				):CostHelper(cg1,cg2),data(*this,wl,data_name),param(float_param)

			{}

		bool operator()(CorGraph::NodeId s1,CorGraph::NodeId d1 ,CostValue,CorGraph::NodeId s2,CorGraph::NodeId d2,CostValue,CostValue &cost) {
			set(s1,d1,s2,d2);

			DataValue tot = 0.;

			for (unsigned i =0;i<size();i++)
				tot += data.dest_data(i);

	        cost = (CostValue)(param + tot);
			return true;
		}

	    CostHelperData data;
	    double param;
	};


public:
	bool check_param(const Project&project) const override {
		// check params
		return option_data.project_check(project);
	}

	virtual void run(const Project&project,Correlator&correlator,const CorGraph&cg1,const CorGraph&cg2) const override {
		_CostFunction cost(cg1,cg2,project.well_list(),option_data(),option_value());

		correlator.run(cg1,cg2,project.max_cor(),cost);
	}

	OptionData option_data{"cftest-data","data","Data for cftest cost function","40CF.Test"};
	OptionFloat option_value{"cftest-value",0.,"Constant for cftest cost function","40CF.Test"};
	_CostFunctionTest():Project::CostFunction("cftest","test cost function"){};
	
};

// uncomment the next line to activate this Cost Function
//static _CostFunctionTest _cost_function_test;

} // anonymous name space
} // namespace WeCo
