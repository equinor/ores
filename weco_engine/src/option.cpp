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

#include <weco/option.h>
#include <regex>
#include <string>
#include <string.h>
namespace WeCo {

//======================== utils ================================================

static void strip_space(std::string &s) {
	std::string trim_char = "\t\n\v\f\r ";
	s.erase(0,s.find_first_not_of(trim_char));
	s.erase(s.find_last_not_of(trim_char)+1);
}




// =============================== Option =========================
void Option::dump(std::ostream&stream) const {
	stream << name() << " (" << type() <<") = "
		<<string()<<" : "<<desc()<<std::endl;

}

std::vector<Option*> Option::sorted_list() {
	std::vector<Option*> res = list();
	std::sort(res.begin(),res.end(),
		[](Option *a,Option*b)
			{return a->info()+" "+a->name() 
					<b->info()+" "+b->name();}
	);
	return res;
}


Option * Option::search(std::string const & name){
	for(Option * i = first();i!= nullptr; i = i-> next() ) {
		if (i->name() == name) return i;
	}
	return nullptr;
}

void Option::reset_all(){
	for(Option * i = first();i!= nullptr; i = i-> next() ) {
		i->reset();
	}
}




bool OptionInt::set(std::string const & value) {
	std::size_t len;
	int real_value;
	std::string tmp{value};
	strip_space(tmp);

	try {
		real_value = std::stoi(tmp,&len);
	} catch(...){
		return false;
	};
	if(value.size() != len)
		return false;
	value_ = real_value;
	return true;
};

bool OptionFloat::set(std::string const & value) {
	std::size_t len;
	double real_value;
	std::string tmp{value};
	strip_space(tmp);
	try {
		real_value = std::stod(tmp,&len);
	} catch(...){
		return false;
	};
	if(value.size() != len)
		return false;
	value_ = real_value;
	return true;
};

bool OptionBool::set(std::string const & value) {
	std::string tmp{value};
	strip_space(tmp);
	if (tmp=="0") {
		value_ = false;
		return true;
	}
	if (tmp=="1") {
		value_ = true;
		return true;
	}
	return false;
};


bool OptionSelect::check(std::string const &value) const {
	StringList lst = option_list();
	return std::find(lst.begin(),lst.end(),value) != lst.end();
}


// ====================== OptionParser ==========================



OptionParser::OptionParser() {
};

void OptionParser::option_help(std::ostream & out ) const{
	out << "Options:"<<std::endl<<std::endl;
	out << "option (string) : load an option file"<<std::endl;
	list_options(out);
}




bool OptionParser::set_option_value(std::string const& name,std::string& value) {
	Option * option = search_option(name);
	if(!option) return false;
	return option->set(value);
}

std::string OptionParser::get_option_value(std::string const& name) {
	Option * option = search_option(name);
	if(!option) return "*ERR*";
	return option->string();

}

void OptionParser::list_options(std::ostream& out) const{
	std::string prev_info{"XXX"};
	for(Option* option : Option::sorted_list()){
		if (prev_info != option->info()){
			prev_info = option->info();
			std::cout<<std::endl;
		}
		option->dump(out);
	}
}



static inline void strip(std::string &s) {
	std::string trim_char = "\t\n\v\f\r ";
	s.erase(0,s.find_first_not_of(trim_char));
	s.erase(s.find_last_not_of(trim_char)+1);
}


bool OptionParser::parse_option_item(const std::string& _option) {
	std::string option_string(_option);
	strip_space (option_string);
	//empty option or comment
	if (option_string.empty() || option_string[0] == '#') {
		return true;
	}

	size_t pos = option_string.find("=");
	if(pos == std::string::npos) {
		LOG << "*ERR* Bad option : "<<option_string<<std::endl;
		// missing option value
		return false;
	}
	std::string name = option_string.substr(0,pos);
	std::string value = option_string.substr(pos+1);
	strip_space(name);
	strip_space(value);

	if (name=="option" )
		return option_load(value);

	Option * option = search_option(name);
	if(!option) {
		LOG << "*ERR* Unknown option : "<<name<<std::endl;
		return false;
	}

	if(!option->set(value)) {
		LOG <<"*ERR* bad value for option "<<name<<" ("<<value<<")"<<std::endl;
		return false;
	}


	return true;
}

bool OptionParser::parse_args(int argc, char * argv[],std::vector<std::string>&args,unsigned max_args,
			int first_arg) {
	if (argc == first_arg || (argc == first_arg+1 &&
			(!strcmp(argv[first_arg],"-h") || !strcmp(argv[first_arg],"--help"))
		)) {
		option_help();
		return false;
	}
	for(int i =first_arg; i <argc;i++) {
		std::string arg(argv[i]);
		if (arg.substr(0,2)=="--") {
			if(!parse_option_item(arg.substr(2)))
				return false;
			continue;
		}
		if(i == first_arg ) {// load option file
			if(!option_load(arg)) return false;
			continue;
		}

		if(max_args > args.size()) {
			args.emplace_back(arg);
			continue;
		}
		LOG <<"*ERR* Bad option "<<arg<<std::endl;
		return false;

	}

	return true;
}


bool OptionParser::option_load(const std::string &filename) {
	std::ifstream file(filename);

	if(!file.is_open()) {
		LOG <<"*ERR* Can't open file "<<filename<<std::endl;
		return false;
	};
	while (!file.eof()) {
		if(!file) {
			LOG <<"*ERR* Error reading file "<<filename<<std::endl;
			return false;
		}
		std::string line;
		std::getline(file,line);
		if(!parse_option_item(line))
			return false;

	}
	return true;
}

}



