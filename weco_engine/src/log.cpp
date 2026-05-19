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
#include <assert.h>
#include <sstream>


namespace WeCo {
namespace {


class LogStringBuf : public std::stringbuf {
public:
	int sync() override {
		assert(WeCo::Log::current());
		WeCo::Log::current()->write(str());
		str(std::string());
		return 0;
	}

};

}

Log::Log() {
	current_= this;
}

Log::~Log() {
	if (current_== this) {
		//log_stream_ <<std::flush;
		current_ = nullptr;
	}
}




Log * Log::current_ = nullptr;
static LogStringBuf _logbuf;
std::ostream  Log::log_stream_(&_logbuf);

}
