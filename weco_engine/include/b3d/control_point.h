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

#ifndef __b3d_point_h__
#define __b3d_point_h__

#include <b3d/common.h>

#include <b3d/corner_point.h>

namespace B3D {

// ========================================================================= //
// Bezier 3D Points                                                          //
// ========================================================================= //
class ControlPoint {

public:

    ControlPoint(const Coord& coord = coord_ndv);
    ControlPoint(const CornerPoint& marker_1, const CornerPoint& marker_2);

    ~ControlPoint();

    Coord coord() const { return coord_; };

    double x_pos() const { return coord_[0]; };
    double y_pos() const { return coord_[1]; };
    double z_pos() const { return coord_[2]; };

    void compute_coord(const CornerPoint& marker_1, const CornerPoint& marker_2);

protected:

    Coord coord_;

};

} // End of namespace B3D

#endif // __b3d_point_h__