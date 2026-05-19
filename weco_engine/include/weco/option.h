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

#ifndef __weco_option_h__
#define __weco_option_h__
#include <weco.h>
#include <assert.h>
#include <map>
#include <string>
#include <iostream>
#include "autoreg.h"

namespace WeCo {

using StringList = std::vector<std::string>;

class Option : public AutoReg<Option> {
protected :
	std::string const name_;
	std::string const desc_;
	std::string info_;

	Option(std::string const & name, std::string const & desc
			, std::string const & info = ""):
		name_(name), desc_(desc), info_(info) {}



public:
	using StringList = std::vector<std::string>;


	virtual std::string const type() const = 0;
	virtual std::string string() const = 0;
	virtual bool set(std::string const & value) = 0;
	virtual void reset() =0;

	std::string const & name() const {return name_;};
	std::string const & info() const {return info_;};
	std::string const & desc() const {return desc_;};

	virtual void dump(std::ostream&) const;

	virtual StringList option_list() const 
		{return StringList();}

    static std::vector<Option*> sorted_list();

    static void reset_all();


	static Option * search(std::string const & name);
	static bool exists(std::string const & name) 
		{return search(name);}

};

class OptionString : public Option {
protected:
	std::string value_;
	std::string default_;

public:
	OptionString(std::string const & name, std::string const & value,
			 std::string const & desc, std::string const & info = ""):
		Option(name,desc,info),value_(value), default_(value) {}

	void reset() override
		{value_=default_;}

	std::string const type() const override
		{return "String";}

	std::string string() const override 
		{return value_;}

	std::string const & operator()() const 
		{return value_;}

	std::string const & value() const 
		{return value_;}

	bool empty() const 
		{return value_.empty();}

	operator bool() const
		{return ! value_.empty();}

	bool operator !() const
		{return value_.empty();}


	bool set(std::string const & value) override {
		if( !check(value)) return false;
		value_ = value;
		return true;
	}

	virtual bool check(std::string const &) const 
		{return true;}

};

class OptionInt : public Option {
protected:
	int value_;
	int default_;
public:
	OptionInt(std::string const & name, int value,
			 std::string const & desc, std::string const & info = ""):
		Option(name,desc,info), value_(value), default_(value) {}

	void reset() override
		{value_=default_;}

	std::string const type() const override
		{return "Int";}

	std::string string() const override 
		{return std::to_string(value_);}

	int operator()() const 
		{return value_;}

	int value() const 
		{return value_;}

	bool set(std::string const & value) override;

	void set_value(int value) 
		 {value_ = value;}

};


class OptionFloat : public Option {
protected:
    double value_;
	double default_;
public:
	OptionFloat(std::string const & name, double value,
			 std::string const & desc, std::string const & info = ""):
		Option(name,desc,info), value_(value), default_(value) {}

	void reset() override
		{value_=default_;}

	std::string const type() const override
		{return "Float";}

	std::string string() const override 
		{return std::to_string(value_);}

	double operator()() const 
		{return value_;}

	double value() const 
		{return value_;}

	bool set(std::string const & value) override;

};

class OptionBool : public Option {
protected:
    bool value_;
	bool default_;
public:
	OptionBool(std::string const & name, bool value,
			 std::string const & desc, std::string const & info = ""):
		Option(name,desc,info), value_(value), default_(value) {}

	void reset() override
		{value_=default_;}

	std::string const type() const override
		{return "Bool";}

	std::string string() const override 
		{return value_?"1":"0";}

	bool operator()() const 
		{return value_;}

	bool value() const 
		{return value_;}

	bool set(std::string const & value) override;

};


class OptionSelect:public OptionString{
public:
	using OptionString::OptionString;

	std::string const type() const override
		{return "Select";}

	bool check(std::string const &) const override;

};

template <class T> class NDAROptionSelect : public OptionSelect {
public:
	using OptionSelect::OptionSelect;

	StringList option_list() const override 
		{ return T::name_list();} 


	void dump(std::ostream&out) const override {
		this->OptionString::dump(out);
		T::dump_list(out,"   - ");
	}


};

/// parse options from command line and files
class OptionParser {
public:
	OptionParser();
	virtual ~OptionParser(){};

	bool option_exists(const std::string&name ) const {
		return search_option(name) !=nullptr;
	}

	Option * search_option(std::string const & name)const
		{return Option::search(name);}


	bool set_option_value(std::string const& name,std::string& value);
	std::string get_option_value(std::string const& name) ;



	void list_options(std::ostream& out = std::cout)const;

	void reset_options() 
		{Option::reset_all();}


	bool parse_args(int , char * argv[],std::vector<std::string>&args,unsigned max_args = 1, 
			int first_arg=1);
	bool parse_args(int argc , char * argv[]) {
		std::vector<std::string>args;
		return parse_args(argc,argv,args,0);
	}

	/// load options from file
	bool option_load(const std::string&);

	/// show help
	virtual void option_help(std::ostream& out = std::cout )const;
protected:
	bool parse_option_item(const std::string& option);
};

}

#endif
