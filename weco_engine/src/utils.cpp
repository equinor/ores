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

#include <weco/utils.h>
#include <cmath>

namespace WeCo {

void Statistics::clear(){
    sum_x_ = sum_x2_ = 0.;
    max_ = -1e300;
    min_ = 1e300;
    number_ = 0;
};

void Statistics::operator()(double x){
    sum_x_ += x;
    sum_x2_ += x*x;
    if(x<min_) min_ = x;
    if(x>max_) max_ = x;
    number_++;
};

double Statistics::mean() const{
    if (!number_) return 0;
    return sum_x_ /double(number_);
}

double Statistics::std_dev() const{
    if (!number_) return 0;
    double mean = sum_x_ /double(number_);
    return std::sqrt(sum_x2_/double(number_) - mean * mean );
}

} // namespace WeCo