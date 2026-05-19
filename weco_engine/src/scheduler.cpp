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

#include <weco/scheduler.h>

#include <mutex>
#include <thread>
#include <iostream>
#include <condition_variable>

using Task = WeCo::CorScheduler::Task;
using TaskParent = WeCo::CorScheduler::TaskParent;

using WeCo::CorScheduler;




namespace {

//==================== MonoScheduler ================================================

class MonoScheduler : public CorScheduler {
public:
	void run_() override;


	WeCo::Correlator & final_correlator() override {
		return correlator_;
	}


private:
	WeCo::Correlator correlator_;

};




void MonoScheduler::run_() {

	while (!task_queue_.empty()) {
		Task * task =task_queue_.front();
		task_queue_.pop();

		run_task(task,correlator_);

		if (task ==  final_task_) return ;

		task_end(task);


	}

	LOG<<"*WRN* No final task done"<<std::endl;
}

//================== MultiScheduler ====================================


class MultiScheduler : public CorScheduler {
public:
	MultiScheduler(unsigned n);
	void run_() override;


	WeCo::Correlator & final_correlator() override {
		return correlators_[final_correlator_];
	}

private:
	unsigned nbr_threads_=0;
	std::vector<WeCo::Correlator> correlators_;
	std::vector<std::thread> workers_;

	std::mutex mutex_;
	std::condition_variable condition_;
	bool stop_=false;
	unsigned running_workers_=0;
	unsigned final_correlator_=0;

	void work(unsigned n);

};

MultiScheduler::MultiScheduler(unsigned n):
	nbr_threads_(n),correlators_(n),final_correlator_(0)
{
	assert(n>=1);
}


void MultiScheduler::run_() {
	stop_ = false;
	running_workers_ = 0;

	workers_.reserve(nbr_threads_);
	for(unsigned n=0;n<nbr_threads_;n++)
		workers_.emplace_back(&MultiScheduler::work,this,n);
	for(auto &i : workers_) i.join();
	workers_.clear();

}

void MultiScheduler::work(unsigned n) {


    for(;;)  {
    	Task * task;
    	{
			std::unique_lock<std::mutex> lock(mutex_);
			condition_.wait(lock,[this]{ return this->stop_ || !this->task_queue_.empty(); });
			if(stop_ && task_queue_.empty())
			  return;
			task = task_queue_.front();
			task_queue_.pop();
			running_workers_++;

    	}

    	run_task(task,correlators_[n]);
    	{
    		std::unique_lock<std::mutex> lock(mutex_);
    		running_workers_--;
    		task_end(task);
    		if (task == final_task_) {
    			stop_ = true;
    			final_correlator_ = n;
    			condition_.notify_all();
    			return;
    		}

    		if(!running_workers_ && task_queue_.empty()) {
    			// bad end
    			stop_ = true;
    			condition_.notify_all();
    			return;
    		}
			condition_.notify_all();
    	};

	}
}


}//anonymous namespace




namespace WeCo {


//===================== stream ==================


void  CorScheduler::dump_tasks(std::ostream&stream) const{
	for(const auto& task:tasks_) 
		stream << task->repr()<<std::endl;
};


void CorScheduler::tasks_dot(std::ostream& stream ) const {

	stream << "digraph test {"<<std::endl;
	for(const auto& task:tasks_){
		stream << task->parent_name1()<<" -> "<<task->name()<<std::endl;
		stream << task->parent_name2()<<" -> "<<task->name()<<std::endl;
	} 
	stream << "}"<<std::endl;
}





CorScheduler * CorScheduler::default_scheduler_ = nullptr;

CorScheduler * CorScheduler::create(unsigned nbr_threads ){
	if (!nbr_threads)
		nbr_threads =  std::thread::hardware_concurrency();

	// LOG << "Treads:"<<nbr_threads<<std::endl;
	if(nbr_threads>1)
		return new MultiScheduler(nbr_threads);
	else
		return new MonoScheduler();

}


bool CorScheduler::run() {
	assert (!tasks_.empty());

	// start defined tasks
	for (auto &i : tasks_) {
		if(i->fully_defined())
			task_queue_.push(i.get());
	}
	final_task_ = (tasks_.empty()?nullptr:tasks_[tasks_.size()-1].get());

	//real run
	run_();


	return (bool)(final_task_->result_);

}


void CorScheduler::run_task(Task * task, Correlator &cor) {
	// one of the parent has empty result ?

	task->run(cor);

	if(cor.failled()) {
		LOG<< "*WRN* Correlation failure: no correlation possible"<<std::endl;
	}
}


void CorScheduler::task_end(Task * task) {
	assert(task->result_);
	for (auto child : task->children_){
		if (child->parent1_.task == task )
			child->parent1_.cor_graph = task->result_;
		if (child->parent2_.task == task )
			child->parent2_.cor_graph = task->result_;
		if (child->fully_defined())
			task_queue_.push(child);
	}

}

CorScheduler::CorScheduler() {
	if(!default_scheduler_)
		default_scheduler_ = this;
}
CorScheduler::~CorScheduler() {
	if (default_scheduler_ == this)
		default_scheduler_ = nullptr;
}

//============================== Task =====================================================

Task::Task(const CorScheduler::TaskParent& parent1,const CorScheduler::TaskParent& parent2,CorScheduler *scheduler)
	: parent1_(parent1),parent2_(parent2){
	if(!scheduler) scheduler =  CorScheduler::default_scheduler();
	assert(scheduler);

	num_ = (int)scheduler->tasks_.size();
	scheduler->tasks_.emplace_back(this);

	if(parent1_.task) parent1_.task->children_.push_back(this);
	if(parent2_.task) parent2_.task->children_.push_back(this);
}		

std::string Task::repr() const {
	return std::string("<")+name()+"="+parent_name1()+"+"+parent_name2()+">";
};


std::string CorScheduler::TaskParent::name() const {
	if (task) 
		return task->name();

	return std::string("W")+std::to_string(cor_graph->well_id(0));
}

//===================================== make_task ================================================
CorScheduler::TaskParent  make_task_linear(const WellVector&wells,CreateTaskFunc cf) {
	assert(wells.size() >=2);
	CorScheduler::TaskParent prev_parent(*wells[0]);

	for(unsigned n=1;n<wells.size();n++) {
		CorScheduler::TaskParent new_parent(*wells[n]);
		CorScheduler::Task* task=cf(prev_parent,new_parent);
		prev_parent = CorScheduler::TaskParent(*task);
	};
	return prev_parent;

}
CorScheduler::TaskParent  make_task_pyramidal(const WellVector&wells,CreateTaskFunc cf){
	assert(wells.size() >=2);
	std::queue<CorScheduler::TaskParent> queue;
	for(auto i : wells)
		queue.emplace(*i);
	while(queue.size()>1) {
		CorScheduler::TaskParent p1=queue.front();
		queue.pop();

		CorScheduler::Task* task=cf(p1,queue.front());

		queue.pop();
		queue.emplace(*task);
	};
	return queue.front();

}


static void center_split( const WellVector& in,WellVector&out1,WellVector&out2) {
	if (in.size()==2) {
		out1.push_back(in[0]);
		out2.push_back(in[1]);
		return;
	}
	if (in.size()<2) {
		out1 = in;
		return;
	}
	DataValue min_x = 1e300;
	DataValue min_y = 1e300;
	DataValue max_x = -1e300;
	DataValue max_y = -1e300;
	for(auto i : in) {
		if(i->x() < min_x) min_x = i->x();
		if(i->x() > max_x) max_x = i->x();
		if(i->y() < min_y) min_y = i->y();
		if(i->y() > max_y) max_y = i->y();
	}

	if( (max_x-min_x)>(max_y - min_y) ) {
		// split on x
		DataValue center  = (min_x+max_x) /2;
		for(auto i : in) {
			if(i->x() < center) out1.push_back(i);
			else out2.push_back(i);
		}
	} else {
		// split on y
		DataValue center  = (min_y+max_y) /2;
		for(auto i : in) {
			if(i->y() < center) out1.push_back(i);
			else out2.push_back(i);
		}

	}

}

static CorScheduler::TaskParent  make_task_split(const WellVector&wells,CreateTaskFunc cf,WellVectorSplitFunc split_func,unsigned max_rec=64){
	if(!max_rec) {
		//max recursion level , use pyramidal
		return make_task_pyramidal(wells,cf);
	}

	if (wells.size()==1)
		return CorScheduler::TaskParent(*wells[0]);
	if (wells.size()==2)
		return CorScheduler::TaskParent(*cf(CorScheduler::TaskParent(*wells[0]),CorScheduler::TaskParent(*wells[1])));

	WellVector split1,split2;
	split_func(wells,split1,split2);

	if (split1.empty()) return make_task_split(split2,cf,split_func,max_rec-1);
	if (split2.empty()) return make_task_split(split1,cf,split_func,max_rec-1);

	return CorScheduler::TaskParent(*cf(
			make_task_split(split1,cf,split_func,max_rec-1)
			,make_task_split(split2,cf,split_func,max_rec-1)
		));
}


CorScheduler::TaskParent  make_task_position(const WellVector&wells,CreateTaskFunc cf){
	return make_task_split(wells,cf,center_split);

}

CorScheduler::TaskParent make_task_distality(const WellVector& wells, CreateTaskFunc cf)
{
    return make_task_linear(wells, cf);
}

CorScheduler::TaskParent make_task_inverse(const WellVector& wells, CreateTaskFunc cf)
{
	assert(wells.size() >= 2);

	CorScheduler::TaskParent prev_parent(*wells[wells.size() - 1]);

	for (int n = wells.size() - 2; n >= 0; n--) {
		CorScheduler::TaskParent new_parent(*wells[n]);
		CorScheduler::Task* task = cf(prev_parent, new_parent);
		prev_parent = CorScheduler::TaskParent(*task);
	};

	return prev_parent;
}

void make_task(WellVector2TasksFunc wv2t,const WellList&wl,CreateTaskFunc ct) {
	WellVector wells;
	wl.convert(wells);
	wv2t(wells,ct);
}


}
