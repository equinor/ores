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

#include <b3d/corner_point.h>

namespace B3D {

// ===================================================================== //
// Bezier 3D Well Markers                                                //
// ===================================================================== //

CornerPoint::CornerPoint(
    const Coord& coord,
    const Dipmeter& dipmeter,
    const FaciesId& facies_id,
    const FaciesExt& extension
) :
    coord_(coord),
    dipmeter_(dipmeter),
    facies_id_(facies_id),
    extension_(extension)
{
    if (dipmeter_ != dipmeter_ndv)
        compute_normal();

    else
        normal_ = normal_ndv;
};

CornerPoint::~CornerPoint() {};

Dipmeter CornerPoint::apparent_dipmeter(const CornerPoint& marker_2) const
{
    double x_dist = marker_2.x_pos() - x_pos();
    double y_dist = marker_2.y_pos() - y_pos();

    double true_dir = rad(dipmeter_[0]); // Angle in radian
    double true_dip = rad(dipmeter_[1]); // Angle in radian

    double seg_dir; // M1 -> M2 segment direction

    double app_dir; // Apparent strike direction
    double app_dip; // Apparent dip angle

    // ================================================================= //
    // Computation of the M1 -> M2 segment direction in degree           //
    // ================================================================= //

    // M1 -> M2: top
    if (x_dist == 0 && y_dist > 0)
        seg_dir = 0.00;

    // M1 -> M2: top right
    else if (x_dist > 0 && y_dist > 0)
        seg_dir = atan(y_dist / x_dist);

    // M1 -> M2: right
    else if (x_dist > 0 && y_dist == 0)
        seg_dir = PI2;

    // M1 -> M2; bottom right
    else if (x_dist > 0 && y_dist < 0)
        seg_dir = atan(y_dist / x_dist);

    // M1 -> M2: bottom
    else if (x_dist == 0 && y_dist < 0)
        seg_dir = PI;

    // M1 -> M2: bottom left
    else if (x_dist < 0 && y_dist < 0)
        seg_dir = atan(y_dist / x_dist) + PI;

    // M1 -> M2: left
    else if (x_dist < 0 && y_dist == 0)
        seg_dir = 3 * PI2;

    // M1 -> M2: top left
    else
        seg_dir = atan(y_dist / x_dist) + PI;

    // ================================================================= //
    // Computation of the apparent dip angle                             //
    // ================================================================= //

    app_dip = atan(tan(true_dip) * sin(seg_dir - true_dir));

    // ================================================================= //
    // Computation of the apparent dir direction                         //
    // ================================================================= //

    app_dir = (seg_dir - PI2 < 0.00 ? seg_dir + 3 * PI2 : seg_dir - PI2);

    return{ deg(app_dir), deg(app_dip) };
};

void CornerPoint::compute_normal()
{
    double x_pos = 0;
    double y_pos = 0;
    double z_pos = 0;

    double dir = rad(dipmeter_[0]); // Angle in Radian
    double dip = rad(dipmeter_[1]); // Angle in Radian

    // Strike direction and dip angle must be correct.
    assert(((0 <= dip) && (dip <= PI2)) && ((0 <= dir) && (dir <= 2 * PI)));

    // strike = NOOO
    if (dir == 0) {
        x_pos = (dip == 0 ? 0 : 1);
        y_pos = (dip == 0 ? 0 : 0);
    }

    // N000 < strike < N090
    else if (0 < dir && dir < PI2) {
        x_pos = (dip == 0 ? 0 :  sin(dir));
        y_pos = (dip == 0 ? 0 : -cos(dir));
    }

    // strike = N090
    else if (dir == PI2) {
        x_pos = (dip == 0 ? 0 :  0);
        y_pos = (dip == 0 ? 0 : -1);
    }

    // N090 < strike < N180
    else if (PI2 < dir && dir < PI) {
        x_pos = (dip == 0 ? 0 : -cos(dir - 1 * PI2));
        y_pos = (dip == 0 ? 0 : -sin(dir - 1 * PI2));
    }

    // strike = N180
    else if (dir == 2 * PI2) {
        x_pos = (dip == 0 ? 0 : -1);
        y_pos = (dip == 0 ? 0 : -0);
    }

    // N180 < strike < N270
    else if (2 * PI2 < dir && dir < 3 * PI2) {
        x_pos = (dip == 0 ? 0 : -sin(dir - 2 * PI2));
        y_pos = (dip == 0 ? 0 :  cos(dir - 2 * PI2));
    }

    // strike = N270
    else if (dir == 3 * PI2) {
        x_pos = (dip == 0 ? 0 : 0);
        y_pos = (dip == 0 ? 0 : 1);
    }

    // N270 < strike < N360
    else {
        x_pos = (dip == 0 ? 0 : cos(dir - 3 * PI2));
        y_pos = (dip == 0 ? 0 : sin(dir - 3 * PI2));
    }

    z_pos = (dip == 0 ? 1 : tan(dip));

    normal_ = Normal({ x_pos, y_pos, z_pos });
};

}; // End of namespace B3D