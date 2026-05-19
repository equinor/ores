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
///@file dtw_distance.h
///simple dtw to compute distance between wells

#ifndef __weco_dtw_distance_h__
#define __weco_dtw_distance_h__

#include <weco.h>

namespace WeCo {

/// dtw distance between to arrays using norm L^1
CostValue dtw_distance_l1(const DataValue * data1,unsigned size1,const DataValue * data2,unsigned size2);

/// dtw distance between to arrays using norm L^2
CostValue dtw_distance_l2(const DataValue * data1,unsigned size1,const DataValue * data2,unsigned size2);

/// compute dtw distance between two arrays
/// @param norm 1 for norm L^1, 2 for norm L^2
CostValue dtw_distance(const DataValue * data1,unsigned size1,const DataValue * data2,unsigned size2,int norm=1);

/// compute dtw distance between two std::vector
/// @param norm 1 for norm L^1, 2 for norm L^2
inline CostValue dtw_distance(const std::vector<DataValue>&data1,const std::vector<DataValue>&data2 ,int norm=1){
    return dtw_distance(data1.data(),data1.size(),data2.data(),data2.size(),norm);
}

/// compute dtw distance between two \ref DataStore::Data
/// @param norm 1 for norm L^1, 2 for norm L^2
inline CostValue dtw_distance(const DataStore::Data & data1,const DataStore::Data & data2,int norm=1){
    return dtw_distance(data1.data(),data2.data(),norm);
};

/// Compute dtw distance between two \ref DataStore or \ref Well
/// @param data1 First DataStore or Well
/// @param data2 Second DataStore or Well
/// @param name Data name
/// @param norm 1 for norm L^1, 2 for norm L^2
inline CostValue dtw_distance(const DataStore & data1,const DataStore & data2,const std::string & name,int norm=1) {
    return dtw_distance(data1.get_data(name),data2.get_data(name),norm);
}

} // namespace WeCo

#endif
