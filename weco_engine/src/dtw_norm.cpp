/*

Association Scientifique pour la Geologie et ses Applications (ASGA)

Copyright (c) 2024 ASGA. All Rights Reserved.

This program is a Trade Secret of the ASGA and it is not to be:
 * reproduced, published, or disclosed to other,
 * distributed or displayed,
 * used for purposes or on Sites other than described in the GOCAD Advancement Agreement,
   without the prior written authorization of the ASGA.

Licencee agrees to attach or embed this Notice on all copies of the program,
including partial copies or modified versions thereof.

*/

#include <weco.h>
#include <weco/dtw_norm.h>
#include <cmath>
#include <memory>
#include <algorithm>

namespace WeCo {

namespace {
    inline CostValue min3(CostValue a,CostValue b,CostValue c) {
        return std::min(a,std::min(b,c));
    }
    inline CostValue square(DataValue a) {
        return a*a;
    }

};



CostValue dtw_norm_l1(const DataValue * data1,unsigned size1,const DataValue * data2,unsigned size2) {
    if(!size1 || !size2)
        return 0.;
    std::unique_ptr<CostValue[]> prev = std::make_unique<CostValue[]>(size1);
    std::unique_ptr<CostValue[]> cur = std::make_unique<CostValue[]>(size1);

    // first column
    {
        const double v2 = data2[0];
        cur[0] = std::abs(data1[0]-v2);
        for(unsigned i1=1;i1<size1;++i1)
            cur[i1] = cur[i1-1] + std::abs(data1[i1]-v2);
    }
    // other columns
    for (unsigned i2 =1;i2<size2;i2++){
        cur.swap(prev);
        const double v2 = data2[i2];
        cur[0] = std::abs(data1[0]-v2);
        for(unsigned i1=1;i1<size1;++i1)
            cur[i1] = min3(cur[i1-1],prev[i1-1],prev[i1]) + std::abs(data1[i1]-v2);

    }
    return cur[size1-1];
}


CostValue dtw_norm_l2(const DataValue * data1,unsigned size1,const DataValue * data2,unsigned size2) {
    if(!size1 || !size2)
        return 0.;
    std::unique_ptr<CostValue[]> prev = std::make_unique<CostValue[]>(size1);
    std::unique_ptr<CostValue[]> cur = std::make_unique<CostValue[]>(size1);

    // first column
    {
        const double v2 = data2[0];
        cur[0] = square(data1[0]-v2);
        for(unsigned i1=1;i1<size1;++i1)
            cur[i1] = cur[i1-1] + square(data1[i1]-v2);
    }
    // other columns
    for (unsigned i2 =1;i2<size2;i2++){
        cur.swap(prev);
        const double v2 = data2[i2];
        cur[0] = square(data1[0]-v2);
        for(unsigned i1=1;i1<size1;++i1)
            cur[i1] = min3(cur[i1-1],prev[i1-1],prev[i1]) + square(data1[i1]-v2);
    }
    return std::sqrt(cur[size1-1]);
}


CostValue dtw_norm(const DataStore::Data & data1,const DataStore::Data & data2,int norm){
    if (norm ==2)
        return dtw_norm_l2(data1.data().data(),data1.size(),data2.data().data(),data2.size());
    if (norm ==1)
        return dtw_norm_l1(data1.data().data(),data1.size(),data2.data().data(),data2.size());
    return 1e300;
}





} // namespace WeCo