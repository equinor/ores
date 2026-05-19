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

#ifndef __weco_utils_h__
#define __weco_utils_h__
#include <weco.h>

namespace WeCo {

class Statistics {
public:
    Statistics() {clear();}

    void clear();

    void operator()(double);

    double mean() const;
    double std_dev() const;
    double min() const { return min_; }
    double max() const { return max_; }
private :
    double sum_x_;
    double sum_x2_;
    double max_;
    double min_;
    int number_;
};
}

#endif
