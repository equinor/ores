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

#pragma once

#include <weco/project.h>
#include "common.h"


namespace WeCo {
    
//================================================
// CCFPart
//==============================================

/*!
 * Base class for Python CompositeCostFunctionPart.
 */
class _PyCCFPart {
public :
	_PyCCFPart() {}
	virtual ~_PyCCFPart() {};
	const CCFContext * ctx_=nullptr;


	using RetValue = std::tuple<bool,CostValue>;

	virtual RetValue dest_cost(CostValue v)
		{ return RetValue(true,v);}
	virtual RetValue full_cost(CostValue v)
		{ return RetValue(true,v);}
	virtual bool dest_only() const
		{ return false;}

	virtual void init() {};

	// §10.5 Batched cost evaluation — override in Python to process arrays
	// Default implementation falls back to per-element full_cost()
	virtual std::vector<RetValue> batch_full_cost(const std::vector<CostValue>& costs) {
		std::vector<RetValue> results;
		results.reserve(costs.size());
		for(auto& c : costs)
			results.push_back(full_cost(c));
		return results;
	}

	bool init_done() const {return ctx_!=nullptr;}

	const Well& well(unsigned n) const {return ctx_->well(n);}

	unsigned size() const {return ctx_->size();}
	unsigned size1() const {return ctx_->size1();}
	unsigned size2() const {return ctx_->size2();}

	MarkerId src(unsigned n) const {return ctx_->src(n);}
	MarkerId dest(unsigned n) const {return ctx_->dest(n);}
	bool same(unsigned n) const {return ctx_->same(n);}

	CostValue parent_cost1() const {return ctx_->parent_cost1();}
	CostValue parent_cost2() const {return ctx_->parent_cost2();}

};

/*!
 * Trampoline class for Pybind11 to have virtual methods in python
 */
class _PyCCFPartT : public _PyCCFPart{
public:
	RetValue dest_cost(CostValue v) override {
		py::gil_scoped_acquire aa; // Need to lock as there is only 1 thread in Python.
		 PYBIND11_OVERLOAD(RetValue,_PyCCFPart,dest_cost,v);
 		 return RetValue(true,v);
	}
	RetValue full_cost(CostValue v) override {
		py::gil_scoped_acquire aa;
		 PYBIND11_OVERLOAD(RetValue,_PyCCFPart,full_cost,v);
 		 return RetValue(true,v);
	}
	bool dest_only() const override {
		py::gil_scoped_acquire aa;
		 PYBIND11_OVERLOAD(bool,_PyCCFPart,dest_only,);
 		 return false;
	}
	void init() override {
		 PYBIND11_OVERLOAD(void,_PyCCFPart,init);
 	}

};


/// Proxy to _PyCCFPart
/*! Allows to define a CompositeCostFunctionPart in Python and use it in C++.
 */
class _PyCCFPartProxy : public CCFPart {
protected:
	_PyCCFPart * cpp_instance_;
	// save python instance
	py::handle  py_instance_;

	_PyCCFPartProxy(py::object py_inst,_PyCCFPart *cpp_inst,const CCFContext& ctx):
		CCFPart(ctx),cpp_instance_(cpp_inst),py_instance_(py_inst.release()) {
		cpp_inst->ctx_ = &context;
		cpp_inst->init();
	}

public:
	~_PyCCFPartProxy() {
		// release python instance with gil
		py::gil_scoped_acquire aa; // Locks the python code before destruction
		py_instance_.dec_ref();
	}

	bool dest_cost(CostValue& v) override {
		_PyCCFPart::RetValue ret = cpp_instance_->dest_cost(v);
		if(!std::get<0>(ret)) return false;
		v = std::get<1>(ret);
		return true;
	}

	virtual bool full_cost( CostValue& v) override {
		_PyCCFPart::RetValue ret = cpp_instance_->full_cost(v);
		if(!std::get<0>(ret)) return false;
		v = std::get<1>(ret);
		return true;
	}

	virtual bool dest_only() const override {
		return cpp_instance_->dest_only();
	}

	static _PyCCFPartProxy* build(const py::object & py_constructor,const Project&,const CCFContext&ctx) {
			py::gil_scoped_acquire aa; // Lock before calling python costs.

			py::object py_instance = py_constructor();
			_PyCCFPart* cpp_instance = py::cast<_PyCCFPart*>(py_instance);
			if(!cpp_instance){
				LOG << "Error creating Python CCFPart"<<std::endl;
				return nullptr;
			}
			return new _PyCCFPartProxy(py_instance,cpp_instance,ctx);
	}

};




class _PyCCFPartFactory : public CCFProjectPartFactory {
public:
	py::object py_constructor_;
	_PyCCFPartFactory(Project& project,py::object py_constructor):CCFProjectPartFactory(project),
		 py_constructor_(py_constructor) {}
	_PyCCFPartProxy * create(const Project&project,const CCFContext&ctx) const override
	    {return _PyCCFPartProxy::build(py_constructor_,project,ctx);}




};
};