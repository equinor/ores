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
#include <random>
#include <weco/scheduler.h>
#include <weco/project.h>


using WeCo::CorGraph;
using WeCo::Correlator;
using WeCo::CostValue;
using WeCo::CorScheduler;
using WeCo::WellId;
using WeCo::WellList;
using WeCo::DataValue;
using WeCo::DataCostHelper;
using Task = WeCo::CorScheduler::Task;
using TaskParent = WeCo::CorScheduler::TaskParent;




class MyCostComputer : public DataCostHelper {
public:
	using DataCostHelper::DataCostHelper;

	bool operator()(CorGraph::NodeId s1,CorGraph::NodeId d1 ,CostValue,CorGraph::NodeId s2,CorGraph::NodeId d2,CostValue,CostValue &cost)  {
		set(s1,d1,s2,d2);
        DataValue sum = 0.;
        CostValue sum2 = 0.;


        for(unsigned n = 0;n<size();n++) {
            DataValue v = dest_data(n);
            sum += v;
            sum2 += v*v;
        }
        DataValue mean = sum / size();
        cost = (CostValue)(sum2 / size() - mean *mean);
		return true;

	}

};



class MyTask : public Task {
public :
	using Task::Task;

	void run(WeCo::Correlator &) override;
};

WellList well_list;

void MyTask::run(WeCo::Correlator &correlator){
	std::cout <<"run task: ";
	parent1().dump_well_id();
	std::cout <<" |";
	parent2().dump_well_id();
	std::cout<<std::endl;

	MyCostComputer cost(parent1(),parent2(),well_list,"data");
	correlator.run(parent1(),parent2(),100,cost);



	CorGraph * new_cg = new CorGraph();
	correlator.result2corgraph(*new_cg,50);

	set_result(new_cg);
}


int main() {
	std::cout << "WeCo Version "<<WeCo::get_version()<<std::endl;

	well_list.read("test.wells.txt");

	CorScheduler::create(1);

	WeCo::make_task<MyTask>(WeCo::make_task_position,well_list);

	CorScheduler::default_run();


	CorScheduler::default_scheduler()->result().to_dot("test2.dot");






	return 0;
}
