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

#ifndef __weco_datareader_h__
#define __weco_datareader_h__

#include <weco.h>
#include <fstream>

namespace WeCo{

/// WeCo file reader
class DataReader {
public:
	DataReader();
	DataReader(const std::string & file_name) : DataReader()
		{open(file_name);}
	DataReader(const std::string & file_name,const std::string &file_type): DataReader()
		{open(file_name,file_type);}

	bool open(const std::string & file_name);
	bool open(const std::string & file_name,const std::string &file_type)
		{return open(file_name)&& check_file_type(file_type) ;}



	bool check_file_type(const std::string & _file_type ) {
		return set_error(_file_type == file_type(),"Bad File Type");
	}

	void close();


	const std::string & file_type() const {return file_type_;}
	int  file_version() const {return file_version_;}

	bool ok() const {
		return ok_;
	}

	bool operator ! () const {
		return !ok_;
	}

	const std::string& error() const {
		return error_text_;
	}

	bool set_error(const std::string text="Error");
	bool set_error(bool ok,const std::string text) {
		return (ok?true:set_error(text));
	}

	enum {
		min_version = 1,
		cur_version = 2,
	};


	int read_int() ;
	int read_int(int min_value,int max_value);

	std::string read_string();
	DataValue read_value();

	bool check_end();

private:
	std::ifstream file_;
	std::string file_type_;
	int file_version_=-1;
	std::string error_text_;
	bool ok_=false;

};

}

#endif
