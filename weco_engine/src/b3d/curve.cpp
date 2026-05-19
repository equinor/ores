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

#include <b3d/curve.h>

namespace B3D {

// ========================================================================= //
// Bezier 3D Curve                                                           //
// ========================================================================= //
Curve::Curve(
    const CornerPoint& marker_1,
    const CornerPoint& marker_2
) :
    p30_(marker_1),
    p03_(marker_2)
{
    n30_ = p30_.normal();
    n03_ = p03_.normal();

    p21_ = ControlPoint(p30_, p03_);
    p12_ = ControlPoint(p03_, p30_);
};

Curve::~Curve() {}

double Curve::projected_distance() const
{
    double dx, dy, distance;
    
    dx = p30().x_pos() - p03().x_pos();
    dy = p30().y_pos() - p03().y_pos();

    distance = dist(dx, dy);

    return distance;
};

double Curve::z_bezier(double u, double v) const
{
    double z = p30_.z_pos() * pow(u, 3) + 3 * p21_.z_pos() * pow(u, 2) * v
             + p03_.z_pos() * pow(v, 3) + 3 * p12_.z_pos() * pow(v, 2) * u;

    return z;
};

// Generated the depositional profile point set from x and y ranges
void Curve::generate_point_set(const std::string& file)
{
    std::ofstream out_file(file, std::ios::out | std::ios::trunc);

    if (out_file) {
        out_file << "x     y     z     u     v     " << std::endl;

        for (unsigned u = 0; u <= 100; ++u ) {

            unsigned v = 100 - u;

            double u_pos = u / 100.00;
            double v_pos = v / 100.00;

            double x = u_pos * p30_.x_pos() + v_pos * p03_.x_pos();
            double y = u_pos * p30_.y_pos() + v_pos * p03_.y_pos();
            double z = z_bezier(u_pos, v_pos);

            out_file << x << " " << y << " " << z << " " << u_pos << " " << v_pos << std::endl;
        }

        out_file.close();
    }

    else
        std::cerr << "Impossible to open the file!" << std::endl;
};

} // End of namespace B3D
