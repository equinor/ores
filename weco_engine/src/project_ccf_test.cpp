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


namespace {

// ====================== Test Composite Cost Function Part 1 ============

class _CCFPartTest1 : public CCFPart {
public:
	_CCFPartTest1(const CCFContext& ctx):CCFPart(ctx) {

	}

	bool dest_cost(CostValue&) override
		{ return true;}

	bool full_cost( CostValue&) override
		{ return true;}

	bool dest_only() const override
		{ return false;}

};


class _CCFPartTest1Factory : public CCFPartFactory {
	OptionBool option_activate{"test-part1",false,"Activate _CCFPartTest1","50CCF.Test1"};
	CCFPart* create(const Project &project,const CCFContext & ctx) const override {
		if (!option_activate())
			return nullptr;
		return new _CCFPartTest1(ctx);
	};
};

// Uncomment thn next line to activate the cost function part
//static _CCFPartTest1Factory _test1factory;


// ====================== Test Composite Cost Function Part 2 ============


class _CCFPartTest2 : public CCFPart {
public:
	_CCFPartTest2(const CCFContext& ctx):CCFPart(ctx) {

	}

	virtual bool dest_cost(CostValue&)
		{ return true;}

	virtual bool full_cost(CostValue&)
		{ return true;}

	virtual bool dest_only() const
		{ return false;}


};

class _CCFPartTest2Factory : public CCFPartFactory {
	OptionBool option_activate{"test-part2",false,"Activate _CCFPartTest2","50CCF.Test2"};
	CCFPart* create(const Project &project,const CCFContext & ctx) const override {
		if (!option_activate())
			return nullptr;
		return new _CCFPartTest2(ctx);
	};
};

// Uncomment thn next line to activate the cost function part
// static _CCFPartTest2Factory _test2factory;


// ====================== Test Composite Cost Function Part 3 ============


class _CCFPartTest3 : public CCFPart {
public:
	_CCFPartTest3(const CCFContext& ctx):CCFPart(ctx) {

	}

	virtual bool dest_cost(CostValue&)
		{ return true;}

	virtual bool full_cost( CostValue&)
		{ return true;}

	virtual bool dest_only() const
		{ return false;}

};

class _CCFPartTest3Factory : public CCFPartFactory {
	OptionBool option_activate{"test-part3",false,"Activate _CCFPartTest3","50CCF.Test3"};
	CCFPart* create(const Project &project,const CCFContext & ctx) const override {
		if (!option_activate())
			return nullptr;
		return new _CCFPartTest3(ctx);
	};
};


// Uncomment thn next line to activate the cost function part
// static _CCFPartTest3Factory _test3factory;


} //anonymous namespace


}// name space WeCo
