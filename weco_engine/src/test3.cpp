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
#include <weco/project.h>

using WeCo::Project;
using std::cout;
using std::endl;

int main(int argc, char * argv[]) {
	std::cout << "WeCo Version "<<WeCo::get_version()<<std::endl;

	Project project;
	std::string data_file;
	if(!project.project_parse_args(argc,argv,data_file)) return -1;

	project.list_options();

	project.run(data_file);
	return 0;
}
