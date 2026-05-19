/*
 * Association Scientifique pour la Geologie et ses Applications (ASGA)
 *
 * Copyright � 2018 ASGA. All Rights Reserved.
 *
 * This program is a Trade Secret of the ASGA and it is not to be:
 *  - reproduced, published, or disclosed to other,
 *  - distributed or displayed,
 *  - used for purposes or on Sites other than described in the GOCAD Advancement Agreement,
 *    without the prior written authorization of the ASGA.
 *
 * Licencee agrees to attach or embed this Notice on all copies of the program,
 * including partial copies or modified versions thereof.
 */

#include <weco/project.h>

#include <algorithm>
#include <memory.h>



namespace WeCo {

//======================== options ================================


OptionInt    Project::option_thread{"thread",0,"Number of threads (0 for auto)","10G"};

OptionString Project::option_order_dot("order-dot","","Write order tasks as a dot file","10G");
OptionBool Project::option_order_only("order-only",false,"Stop after order tasks generation","10G");
OptionInt  Project::option_band_width{"band-width",0,"Sakoe-Chiba band width (0=unlimited)","10G"};
OptionInt  Project::option_beam_width{"beam-width",0,"Beam search width per column (0=full enumeration)","10G"};
OptionFloat Project::option_cost_floor{"cost-floor",0.,"Minimum cost per transition (noise suppression)","10G"};
OptionBool Project::option_cost_weighted_avg{"cost-weighted-avg",false,"Use weighted-average cost combination instead of sum","10G"};

OptionInt    Project::option_max_cor{"max-cor",50,"Maximum number of correlations during DTW","10G"};
OptionInt    Project::option_nbr_cor{"nbr-cor",50,"Number of correlations kept for the next DTW" ,"10G"};
OptionFloat  Project::option_min_dist{ "min-dist",.0,"Minimum cost distance to subsample the kept correlations (Exp)","10G"};

OptionInt    Project::option_out_nbr_cor{ "out-nbr-cor",5,"Number of output correlations" ,"10G"};
OptionFloat  Project::option_out_min_dist{ "out-min-dist",0.,"Minimum cost distance between 2 correlations in output" ,"10G"};

OptionString Project::option_out_dot{"out-dot","","Output file name in dot (graphviz) format" ,"10G"};
OptionString Project::option_out_file{ "out-file","out.txt","Output result file in WeCo format","10G"};

OptionString Project::option_step_dot{"step-dot","","Base name for optional dot output file at each correlation step (for QC)" ,"10G"};
OptionString Project::option_step_file{ "step-file","","Base name for optional output file in WeCo format at each correlation step (for QC)","10G"};

OptionString Project::option_cost_matrix{ "cost-matrix","","Output cost matrix file name (for QC and debugging)","10G"};


OptionBool   Project::option_debug_cor_info{ "debug-cor-info",false,"show info on correlations (for QC and debugging)","10G"};

NDAROptionSelect<Project::CostFunction>  Project::option_cost_function{"cost-function","composite","cost function","20SEL"};



// ==================== option classes =====================================


bool OptionData::project_check(Project const& project,bool only_if_set)const {
	if (only_if_set && empty())
		return true;
	if(!project.well_list().wells_data_exists(string())){
		LOG << "*ERR* data "<<string()<<" missing"<<std::endl;
		return false;
	}
	//TODO: check size
	return true;
};

bool OptionRegion::project_check(Project const& project,bool only_if_set)const {
	if (only_if_set && empty())
		return true;
	if(!project.well_list().region_list_exists(string())){
		LOG << "*ERR* region list "<<string()<<" missing"<<std::endl;
		return false;
	}
	//TODO: check size
	return true;
};



//====================================== TaskOrder ===================================================================

NDAROptionSelect<Project::TaskOrderFactory> Project::option_order{"order","pyramidal","task ordering","20SEL"};

static Project::TaskOrderFactory tof_linear_{"linear", make_task_linear,
		"Correlates 1 to 2, then 1-2 to 3, etc"};
static Project::TaskOrderFactory tof_position_{"position", make_task_position,
        "Uses spatial clustering of well positions with BSP-trees to decide about the correlation order"};
static Project::TaskOrderFactory tof_pyramidal_{"pyramidal", make_task_pyramidal,
		"Correlates 1 to 2, then 3 to 4, then 1-2 to 3-4, etc"};
static Project::TaskOrderFactory tof_distality_{"distality", make_task_distality,
        "Reorder wells by them distality from the most distal to the most proximal"};
static Project::TaskOrderFactory tof_inverse_{ "inverse", make_task_inverse,
		"Invert the well order. Correlates (-1) to (-2), then (-1)-(-2), etc" };

//======================== Task ==========================

Project::Task::Task(const CorScheduler::TaskParent& parent1,const CorScheduler::TaskParent& parent2,Project &project)
	: CorScheduler::Task(parent1,parent2,project.scheduler_),project_(project){}

void Project::Task::run(Correlator &correlator) {

	if (project_.option_debug_cor_info())
		std::cout << "Starting "<< *this<<std::endl;
	
	project_.cost_function_->run(project_,correlator,parent1(),parent2());

	CorGraph * new_cg = new CorGraph();
	correlator.result2corgraph(*new_cg,project_.option_nbr_cor(),project_.option_min_dist());

	if (project_.option_debug_cor_info()) {
		std::cout << "Finishing "<< *this<<std::endl;
		new_cg->dump_info(Log::out());
	};

	if(project_.option_step_file)
		new_cg->dump(project_.option_step_file()+new_cg->well_id_str()+".txt");

	if(project_.option_step_dot)
		new_cg->to_dot(project_.option_step_dot()+new_cg->well_id_str()+".dot");

	set_result(new_cg);


}


// ========================== Project ===================================

Project::Project():
	scheduler_(nullptr)
{
};

Project::~Project() {
	delete scheduler_;
};



void Project::option_help(std::ostream& out  )const {
	out<< "Usage: [optionfile] [options] datafile"<<std::endl<<std::endl;;
	OptionParser::option_help(out);
}


//================== checks ============================

bool Project::option_check() const{
	if(!TaskOrderFactory::name_exists(option_order())) {
		LOG << "*ERR* Unknown order option "<<option_order()<<std::endl;
		return false;
	}
	if(!CostFunction::name_exists(option_cost_function())) {		
		LOG << "*ERR* Unknown cost-function option "<<option_cost_function()<<std::endl;
		return false;
	}

	return true;

}



bool Project::project_parse_args(int argc, char * argv[],std::string & data) {
	int arg_num = 1;
	#ifdef GEN_PLUGIN
	while (arg_num < argc) {
		if(arg_num+1 < argc && !strcmp(argv[arg_num],"-P") ) {
			if(!load_plugin(argv[arg_num+1])){
				return false;
			};
			arg_num+=2;
			continue;
		}
		break;
	};
	#endif

	std::vector<std::string >args;
	if(!OptionParser::parse_args(argc,argv,args,1,arg_num)) return false;
	if(!option_check()) return false;
	if(args.size() != 1) {
		LOG<<"*ERR* Missing data file"<<std::endl;
		return false;
	}
	// change options
	if(option_max_cor() <option_nbr_cor())
		option_max_cor.set_value(option_nbr_cor());

	data = args[0];
	return true;
}


bool Project::run(const std::string& data_file) {

	if(!well_list_.read(data_file))
		return false;
	
	return run_();

}



bool Project::run(const WellList& well_list) {

	well_list_ = well_list;
	return run_();
}



bool Project::run_() {
	if (scheduler_) {
		delete scheduler_;
		scheduler_ = nullptr;
	}

	cost_function_ = CostFunction::from_name(option_cost_function());
	assert(cost_function_!=nullptr);


	if(!cost_function_->check_param(*this))
		return false;

	scheduler_ =CorScheduler::create(option_thread());

	// create tasks
	make_task(
		(order_func_?order_func_: TaskOrderFactory::value_from_name(option_order()) ),
		well_list(),
		[this](const CorScheduler::TaskParent&p1,const CorScheduler::TaskParent&p2){ return (CorScheduler::Task*)(new Task(p1,p2,*this));}
	);

	// scheduler_->dump_tasks(std::cout);

	if(option_order_dot) 
		scheduler_->tasks_dot(option_order_dot());

	if(option_order_only()) 
		return true;


	if(!scheduler_->run()){
		LOG <<"*ERR* Correlation failure"<<std::endl;
		return false;
	}


	CorGraph res_cg;
	scheduler_->final_correlator().result2corgraph(res_cg,option_out_nbr_cor(),option_out_min_dist());
	if(option_out_dot)
		res_cg.to_dot(option_out_dot());
	if(option_out_file)
		res_cg.dump(option_out_file());

	if (option_debug_cor_info())
		res_cg.dump_info(Log::out());


	return true;
}




}
