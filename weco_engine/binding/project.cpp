/*

Association Scientifique pour la Geologie et ses Applications (ASGA)

Copyright (c) 2024 ASGA. All Rights Reserved.

This program is a Trade Secret of the ASGA and it is not to be:
 * reproduced, published, or disclosed to other,
 * distributed or displayed,
 * used for purposes or on Sites other than described in the GOCAD Advancement Agreement,
   without the prior written authorization of the ASGA.

Licencee agrees to attach or embed this Notice on all copies of the program,
including partial copies or modified versions thereof.

*/
#include "ccf_part.h"

namespace WeCo {

class PyProject : public Project {
	
public:
	struct TaskCreator{
		TaskCreator(const CreateTaskFunc &func): create_func(func){}
		const CreateTaskFunc& create_func; 
	};

	struct PyTask {
		WeCo::CorScheduler::Task * task;
		PyTask(WeCo::CorScheduler::Task *t):task(t){}

		WeCo::CorScheduler::Task & ref()const
			{return  *task;}

		std::string repr() const {
			return task->repr();
		}
	};

	void py_add_ccf_part(py::object constructor) {
		new _PyCCFPartFactory(*this,constructor);
	}

	bool py_run_file(const std::string& data_file) {
		py::gil_scoped_release rel;
		return run(data_file);
	}

	bool py_run_welllist(const WellList& well_list) {
		py::gil_scoped_release rel;
		return run(well_list);
	}


	void py_set_order_func(const py::object & func){
		py_order_func_ = func;

		set_order_func(
			[this](const WellVector&wells,CreateTaskFunc cf)
			{this ->py_order_func_proxy(wells,cf);}
		);
	};


private:
	py::object py_order_func_=py::none();


	void py_order_func_proxy(const WellVector&wells,CreateTaskFunc cf) {
		py::gil_scoped_acquire _gil;
		TaskCreator tc(cf);
		py_order_func_(wells,tc);
	}
};

}


void def_project(py::module_& m){
        py::class_<WeCo::PyProject,WeCo::OptionParser>(m,"Project")
		.def(py::init<>())


		.def("run",&WeCo::PyProject::py_run_file,"run from file")
		.def("run",&WeCo::PyProject::py_run_welllist,"run from WellList")
		.def("add_ccf_part",&WeCo::PyProject::py_add_ccf_part,"Adds a CCFPart to the list of costs")

		.def_static("task_order_keys",[](){return WeCo::Project::TaskOrderFactory::name_list();} )
		.def_static("cost_function_keys",[](){return WeCo::Project::CostFunction::name_list();} )

		.def("set_order_func",&WeCo::PyProject::py_set_order_func,"Set order function")

		DEF(PyProject,clear_order_func,"Remove define order function")

		DEF(PyProject,result,"")
		DEF(PyProject,well_list,"return well list")

	;

    //========================= order func =================================
    py::class_<WeCo::PyProject::PyTask>(m,"Task")
		.def("__repr__",&WeCo::PyProject::PyTask::repr)
	;

    py::class_<WeCo::PyProject::TaskCreator>(m,"CreatTaskFunc") 
		.def("__call__",[](WeCo::PyProject::TaskCreator*ct,WeCo::Well*a,WeCo::Well*b)->WeCo::PyProject::PyTask
				{return WeCo::PyProject::PyTask(ct->create_func(*a,*b));})
		.def("__call__",[](WeCo::PyProject::TaskCreator*ct,const WeCo::PyProject::PyTask &a,WeCo::Well*b)->WeCo::PyProject::PyTask
				{return WeCo::PyProject::PyTask(ct->create_func(a.ref(),*b));})
		.def("__call__",[](WeCo::PyProject::TaskCreator*ct,WeCo::Well*a,const WeCo::PyProject::PyTask &b)->WeCo::PyProject::PyTask
				{return WeCo::PyProject::PyTask(ct->create_func(*a,b.ref()));})
		.def("__call__",[](WeCo::PyProject::TaskCreator*ct,const WeCo::PyProject::PyTask &a,const WeCo::PyProject::PyTask &b)->WeCo::PyProject::PyTask
				{return WeCo::PyProject::PyTask(ct->create_func(a.ref(),b.ref()));})
	;


}
