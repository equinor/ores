#include <weco.h>

class MyLog:public WeCo::Log {
public:
	void write(const std::string&s) override {
		std::cout <<"MYLOG[[["<<s<<"]]]\n";
	}
};



int main() {

	LOG << "Some text without logger"<<std::endl;
	{
		MyLog log;
		LOG << "Some text with logger"<<std::endl;

	}
	LOG << "Some text without logger"<<std::endl;

	return 0;

}
