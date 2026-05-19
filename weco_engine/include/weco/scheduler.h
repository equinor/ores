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

#ifndef __weco_scheduler_h__
#define __weco_scheduler_h__

#include <weco.h>
#include <queue>
#include <memory>
#include <functional>
namespace WeCo {

/// Base class for all correlations scheduler
class CorScheduler {
public :
	static CorScheduler * create(unsigned nbr_threads = 0);
	using CorGraphPtr = std::shared_ptr<const CorGraph>;

	static CorScheduler * default_scheduler()
		{return default_scheduler_;}

	bool run();

	/// execute task of the default scheduler
	static bool default_run() {
		assert(default_scheduler_);
		return default_scheduler()->run();
	}

	class Task;
	/// Parent for a task (Task then CorGraph)
	struct TaskParent {
		TaskParent(Task&t):
			task(&t),cor_graph(nullptr){}
		TaskParent(CorGraphPtr& cg):
			task(nullptr),cor_graph(cg){}
		TaskParent(const CorGraph* cg):
			task(nullptr),cor_graph(cg){}
		TaskParent(const Well &well):
			TaskParent(new CorGraph(well)){}
		Task* task;
		CorGraphPtr cor_graph;

		std::string name() const;

	};

	/// A scheduler task
	class Task {
	public :
		Task(const TaskParent& parent1,const TaskParent& parent2,CorScheduler *scheduler =nullptr);
		Task(const Task &&) =delete;
		Task(const Task &) =delete;

		const CorGraph & parent1() const
			{assert(parent1_.cor_graph);return *(parent1_.cor_graph);}
		const CorGraph & parent2() const
			{assert(parent2_.cor_graph);return *(parent2_.cor_graph);}

		virtual void run(Correlator &) =0;

		const CorGraph& result() const
			{ assert(result_);return *(result_.get());}


		int num()const 
		{return num_;}
			
		std::string name() const {
			return std::string("T")+std::to_string(num());
		}

		std::string parent_name1() const {
			return parent1_.name();
		}

		std::string parent_name2() const {
			return parent2_.name();
		}

		std::string repr() const;



	protected :
		void set_result(CorGraph *cg) {
			result_= CorGraphPtr(cg);
		}

	private :
		TaskParent parent1_,parent2_;
		std::vector <Task*> children_;
		CorGraphPtr result_;
		int num_;

		friend class CorScheduler;

		bool fully_defined() const
		{ return parent1_.cor_graph && parent2_.cor_graph;}

	};


	virtual Correlator & final_correlator() =0;

	const CorGraph &result() const {
		assert(final_task_);
		return final_task_->result();
	}

	virtual ~CorScheduler();


	void dump_tasks(std::ostream&stream)const;


    /*! Writes the task list in dot format to an ostream */
	void tasks_dot(std::ostream& stream = std::cout) const;
    
    /*! Writes the task list in dot format to a file */
    void tasks_dot(const std::string& filename) const {
        std::ofstream file(filename);
        tasks_dot(file);
    }


protected :
	static CorScheduler * default_scheduler_;
	std::vector<std::unique_ptr<Task>> tasks_;
	std::queue<Task*> task_queue_;
	Task * final_task_=nullptr;

	void task_end(Task *);

	void run_task(Task *,Correlator &);

	CorScheduler();

	virtual void run_() = 0;
	friend class Task;

};


inline std::ostream& operator<<(std::ostream &stream,const CorScheduler::Task& task) {
	return stream << task.repr();
};

inline std::ostream& operator<<(std::ostream &stream,const CorScheduler::TaskParent& task_parent) {
	return stream << task_parent.name();
};



//========================= implementation ==================================


using CreateTaskFunc = std::function<CorScheduler::Task *(const CorScheduler::TaskParent&,const CorScheduler::TaskParent&)>;
using WellVector = std::vector<Well*>;
//using WellVector2TasksFunc = std::function<CorScheduler::TaskParent(const WellVector&,CreateTaskFunc)>;
using WellVector2TasksFunc = std::function<void(const WellVector&,CreateTaskFunc)>;
using WellVectorSplitFunc = std::function<void(const WellVector&in,WellVector&out1,WellVector&out2)>;

CorScheduler::TaskParent  make_task_linear(const WellVector&wells,CreateTaskFunc cf);
CorScheduler::TaskParent  make_task_pyramidal(const WellVector&wells,CreateTaskFunc cf);
CorScheduler::TaskParent  make_task_position(const WellVector&wells, CreateTaskFunc cf);
CorScheduler::TaskParent  make_task_distality(const WellVector& wells,CreateTaskFunc cf);
CorScheduler::TaskParent  make_task_inverse(const WellVector& wells, CreateTaskFunc cf);


void make_task(WellVector2TasksFunc wv2t,const WellList&wl,CreateTaskFunc ct);

template <class T> void make_task(WellVector2TasksFunc wv2,const WellVector&wells,CorScheduler * s =nullptr ) {
	if(!s) s = CorScheduler::default_scheduler();
	wv2(wells,[s](const CorScheduler::TaskParent&p1,const CorScheduler::TaskParent&p2){ return (CorScheduler::Task*)(new T(p1,p2,s));});
}

template <class T> void make_task(WellVector2TasksFunc wv2t,const WellList&wl,CorScheduler * s =nullptr ){
	WellVector wells;
	wl.convert(wells);
	make_task<T>(wv2t,wells,s);
}




};

#endif
