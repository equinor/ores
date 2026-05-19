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

CCFProjectPartFactory::CCFProjectPartFactory(Project&project )
{
	project.add_ccf_part(this);
}

namespace  {

// ========================================================================= //
// Composite Cost Function                                                   //
// ========================================================================= //

class _CostFunctionComposite: public Project::CostFunction {
    /*!
     * A Composite Cost function combining several cost functions
     */
	class _CostFunction:public CCFContext {
	public:
		std::vector<std::unique_ptr<CCFPart>> dest_parts;
		std::vector<std::unique_ptr<CCFPart>> full_parts;
		bool weighted_avg_ = false;


		_CostFunction(const CorGraph&cg1,const CorGraph&cg2,const WellList& well_list) :
			CCFContext(cg1,cg2,well_list) {}

		void run(const Project&project,Correlator&correlator){
			weighted_avg_ = project.cost_weighted_avg();
			// create parts from global
			for(auto i : CCFGlobalPartFactory::list()) {
				CCFPart * part = i->create(project,*this);
				if(!part) continue;
				(part->dest_only()?dest_parts:full_parts ).emplace_back(part);
			}
			// create parts from project
			for(auto const &i : project.ccf_part_factories()) {
				CCFPart * part = i->create(project,*this);
				if(!part) continue;
				(part->dest_only()?dest_parts:full_parts ).emplace_back(part);
			}
			//
			if (project.option_cost_matrix){
				correlator.write_cost_matrix(project.option_cost_matrix(),
					cor_graph1(),cor_graph2(),*this);
			}

			// §6.1 & §6.5: configure correlator constraints
			correlator.set_band_width(project.band_width());
			correlator.set_beam_width(project.beam_width());

			// call engine

			unsigned maxcor = project.max_cor();

			if(dest_parts.empty())
				correlator.run(cor_graph1(),cor_graph2(),maxcor,*this);
			else if(full_parts.empty())
				correlator.run_dest_only(cor_graph1(),cor_graph2(),maxcor,*this);
			else
				correlator.run_dest_opt(cor_graph1(),cor_graph2(),maxcor,*this);


		}

		/// dest only
		bool operator()(CorGraph::NodeId d1 ,CorGraph::NodeId d2,CostValue &cost) {
			set_dest(d1,d2);
			for(auto & i : dest_parts)
				if(!i->dest_cost(cost))
					return false;
			if(weighted_avg_ && !dest_parts.empty())
				cost /= static_cast<CostValue>(dest_parts.size());
			return true;
		}

		/// full
		bool operator()(CorGraph::NodeId s1,CorGraph::NodeId d1 ,CostValue cost1,CorGraph::NodeId s2,CorGraph::NodeId d2,CostValue cost2,CostValue &cost)  {
			set(s1,d1,s2,d2);
			set_parent_cost(cost1,cost2);
			for(auto & i : full_parts)
				if(!i->full_cost(cost))
					return false;
			if(weighted_avg_ && !full_parts.empty())
				cost /= static_cast<CostValue>(full_parts.size());
			return true;
		}

	};


public:
	_CostFunctionComposite():
		Project::CostFunction("composite","composite cost function"){}

	bool check_param(const Project&project) const override {
		for (auto i:CCFGlobalPartFactory::list())
			if (!i->test(project)) return false;
		for (auto const  &i:project.ccf_part_factories())
			if (!i->test(project)) return false;
		return true;
	}

	virtual void run(const Project&project,Correlator&correlator,const CorGraph&cg1,const CorGraph&cg2) const override {
		_CostFunction cost_function(cg1,cg2,project.well_list());
		cost_function.run(project,correlator);

	}
};

static _CostFunctionComposite _cost_function_composite;	

}
} // End of namespace WeCo
