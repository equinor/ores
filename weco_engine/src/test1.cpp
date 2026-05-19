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

using WeCo::CorGraph;
using WeCo::Correlator;
using WeCo::CostValue;

std::random_device r;
std::default_random_engine random_engine(r());

bool test_cost(CorGraph::NodeId ,CorGraph::NodeId ,CostValue,CorGraph::NodeId ,CorGraph::NodeId ,CostValue,CostValue &cost) {
	cost=  std::uniform_real_distribution<CostValue>(.1,.5)(random_engine);
	return true;
}



int main() {
	std::cout << "WeCo Version "<<WeCo::get_version()<<std::endl;

	CorGraph cg1(7);
	CorGraph cg2(5);
	CorGraph cg3(6);
	CorGraph cg4(4);

	CorGraph cg12;
	CorGraph cg34;

	CorGraph cg_all;
	CorGraph cg_best;

	Correlator cor;

	cor.run(cg1,cg2,5,test_cost);
	std::cout <<"=== Cor 12:"<<std::endl;
	cor.dump_result(0);
	cor.result2corgraph(cg12);
	cg12.to_dot("cg12.dot");



	cor.run(cg3,cg4,5,test_cost);
	std::cout <<"=== Cor 34:"<<std::endl;
	cor.dump_result(0);
	cor.result2corgraph(cg34);
	cg34.to_dot("cg34.dot");


	cor.run(cg12,cg34,10,test_cost);
	std::cout <<"=== Cor all:"<<std::endl;
	cor.dump_result(0);
	cor.result2corgraph(cg_all);
	cg_all.to_dot("cg_all.dot");
	cor.result2corgraph(cg_best,1);
	cg_best.to_dot("cg_best.dot");

	return 0;
}
