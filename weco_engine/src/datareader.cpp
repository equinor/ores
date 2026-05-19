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
#include <weco/datareader.h>
#include <fstream>
namespace WeCo {

DataReader::DataReader() : ok_(true){

}
bool DataReader::open(const std::string & file_name) {
	ok_ = true;
	error_text_ = "No Error";
	file_.open(file_name);

	if (!file_) return set_error("Can't open file");

	std::string hdr;

	file_ >> hdr >> file_type_ >> file_version_;

	if (!file_ || hdr != "WeCo") return set_error("Bad File Header");

	if (file_version_< min_version  || file_version_ > cur_version)
		return set_error("Bad File Version");

	return true;
}

void DataReader::close() {
	file_.close();

}



bool DataReader::set_error(const std::string text) {
	if (!ok()) return false;
	ok_ = false;
	error_text_ = text;
	throw ReadError(text);
}



int DataReader::read_int() {
	if(!ok()) return 0;
	int v;
	file_ >> v;
	if(!file_) {
		set_error("ReadError: Not an int");
		return 0;
	}
	return v;
}
int DataReader::read_int(int min_value,int max_value) {
	int v = read_int();
	if(!ok()) return 0;
	if (v<min_value||v>max_value)
		set_error("ReadError: int range");
	return v;
}

std::string DataReader::read_string(){
	if (!ok()) return "";
	std::string ret;
	file_>>ret;
	if(!file_) {
		set_error("ReadError: string");
		return "";
	}
	return ret;

}
DataValue DataReader::read_value(){
	if (!ok()) return 0.;
	DataValue ret;
	file_>>ret;
	if(!file_) {
		set_error("ReadError: DataValue");
		return 0.;
	}
	return ret;
}

bool DataReader::check_end() {
	if (!ok()) return 0.;
	std::string end;
	file_>>end;
	if(!file_ || end!="END") {
		set_error("ReadError: END NOT FOUND");
		return false;
	}

	return true;
}

}
