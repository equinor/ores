/*
 * Association Scientifique pour la Geologie et ses Applications (ASGA)
 *
 * Copyright (c) 2020 ASGA. All Rights Reserved.
 *
 * This program is a Trade Secret of the ASGA and it is not to be:
 *  - reproduced, published, or disclosed to other,
 *  - distributed or displayed,
 *  - used for purposes or on Sites other than described in the GOCAD
 *    Advancement Agreement, without the prior written authorization
 *    of the ASGA.
 *
 * Licencee agrees to attach or embed this Notice on all copies of the program,
 * including partial copies or modified versions thereof.
 *
 * Author: Paul Baville -- paul.baville@univ-lorraine.fr
 */

#ifndef __b3d_common_h__
#define __b3d_common_h__

#include <cmath>
#include <cassert>

#include <map>
#include <array>
#include <limits>
#include <string>
#include <vector>
#include <fstream>
#include <iostream>
#include <iterator>

#ifndef _USE_MATH_DEFINES
//const double PI = acos(-1.0);
const double PI = 3.14159265358979323846;
const double PI2 = PI / 2;
const double PI3 = PI / 3;
const double PI4 = PI / 4;
const double PI6 = PI / 6;
#endif

namespace B3D {

// ========================================================================= //
// Functionalities                                                           //
// ========================================================================= //

inline double square(double val) { return val * val; };

inline double dist(double dx, double dy) { return sqrt(dx*dx + dy*dy); };
inline double dist(double dx, double dy, double dz) { return sqrt(dx*dx + dy*dy + dz*dz); };

inline double cos2(double x) { return square(cos(x)); };
inline double sin2(double x) { return square(sin(x)); };

inline double deg(double angle) { return angle * 180 / PI; };
inline double rad(double angle) { return angle * PI / 180; };

// ========================================================================= //
// Type definitions                                                          //
// ========================================================================= //

using Float = double;

using SedDir = double; // Principal sediment transport direction

using FaciesId = unsigned; // Facies label

using Head = std::array< Float, 2 >; // Head = ( x_pos , y_pos )

using Coord = std::array< Float, 3 >;// Coord = ( x_pos , y_pos , z_pos )

using Range = std::vector< Float >; // Range = ( min , max (, step) )

using Slope = std::array< Float, 3 >; // Slope = ( x_ext , y_ext , z_ext )

using Normal = std::array< Float, 3 >; // Normal = ( n_x , n_y , n_z )

using Dipmeter = std::array< Float, 2 >; // Dipmeter = ( dir , dip )

using FaciesExt = std::array< Float, 3 >; // FaciesExt = ( x_ext, y_ext, z_ext )

using FaciesMap = std::map< FaciesId, FaciesExt >; // FaciesMap = { FaciesId : FaciesExt }

using FaciesZMap = std::map< FaciesId, Range >; // FaciesZMap = { FaciesId : Range }

// ========================================================================= //
// No Data Values                                                            //
// ========================================================================= //

const double ndv = std::numeric_limits< Float >::quiet_NaN();
const unsigned undv = std::numeric_limits< unsigned >::max();

const Head head_ndv{ ndv, ndv };

const Range range_ndv{ ndv, ndv };

const Coord coord_ndv{ ndv, ndv, ndv };

const Slope slope_ndv{ ndv, ndv, ndv };

const Normal normal_ndv{ ndv, ndv, ndv };

const Dipmeter dipmeter_ndv{ ndv, ndv };

const FaciesExt facies_ext_ndv{ ndv, ndv, ndv };

//const FaciesMap facies_map_ndv = { undv, facies_ext_ndv };

//const FaciesZMap facies_z_map_ndv{ undv, range_ndv };

}; // End of namespace B3D

#endif // __b3d_common_h__