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

#include <b3d/control_point.h>

namespace B3D {

// ========================================================================= //
// Bezier 3D Points                                                          //
// ========================================================================= //
ControlPoint::ControlPoint(const Coord& coord) : coord_(coord) {};

ControlPoint::ControlPoint(const CornerPoint& marker_1, const CornerPoint& marker_2)
{
    compute_coord(marker_1, marker_2);
};

ControlPoint::~ControlPoint() {};

void ControlPoint::compute_coord(const CornerPoint& marker_1, const CornerPoint& marker_2)
{
    // Distance between the two corner points.
    double x_dist = marker_2.x_pos() - marker_1.x_pos();
    double y_dist = marker_2.y_pos() - marker_1.y_pos();
    double z_dist = marker_2.z_pos() - marker_1.z_pos();

    // Zone of influence around the corner point 1.
    double x_ext = marker_1.x_ext();
    double y_ext = marker_1.y_ext();
    double z_ext = marker_1.z_ext();

    // Control point distance to corner point 1.
    double x_len = x_ext * x_dist;
    double y_len = y_ext * y_dist;
    double z_len = z_ext * z_dist;

    // double radius = sqrt(pow(x_len, 2) + pow(y_len, 2) + pow(z_len, 2));
    double radius = dist(x_len, y_len, z_len);
    
    // Computation of the apparent dipmeter at the corner point 1.
    Dipmeter app_dipmeter = marker_1.apparent_dipmeter(marker_2);

    double app_dir = rad(app_dipmeter[0]);
    double app_dip = rad(app_dipmeter[1]);

    // Control point coordinates.
    double x_pos = marker_1.x_pos() + radius * cos(app_dip) * sin(app_dir);
    double y_pos = marker_1.y_pos() + radius * cos(app_dip) * cos(app_dir);
    double z_pos = marker_1.z_pos() + radius * sin(app_dip);

    coord_ = { x_pos, y_pos, z_pos };
};

}; // End of namespace B3D