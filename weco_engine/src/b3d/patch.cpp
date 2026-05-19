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
#include <b3d/patch.h>

namespace B3D {

// ========================================================================= //
// Bezier 3D Curve                                                           //
// ========================================================================= //
Patch::Patch(
    const CornerPoint& marker_1,
    const CornerPoint& marker_2,
    const CornerPoint& marker_3
) :
    p300_(marker_1),
    p030_(marker_2),
    p003_(marker_3)
{
    p210_ = ControlPoint(p300_, p030_);
    p120_ = ControlPoint(p030_, p300_);

    p021_ = ControlPoint(p030_, p003_);
    p012_ = ControlPoint(p003_, p030_);

    p102_ = ControlPoint(p003_, p300_);
    p201_ = ControlPoint(p300_, p003_);

    compute_p111_coords();
};

Patch::~Patch() {};

void Patch::compute_p111_coords()
{
    double x =
        1. / 4. * (p210_.x_pos() + p120_.x_pos() + p021_.x_pos() + p012_.x_pos() + p102_.x_pos() + p201_.x_pos()) -
        1. / 6. * (p300_.x_pos() + p030_.x_pos() + p003_.x_pos());

    double y =
        1. / 4. * (p210_.y_pos() + p120_.y_pos() + p021_.y_pos() + p012_.y_pos() + p102_.y_pos() + p201_.y_pos()) -
        1. / 6. * (p300_.y_pos() + p030_.y_pos() + p003_.y_pos());

    double z =
        1. / 4. * (p210_.z_pos() + p120_.z_pos() + p021_.z_pos() + p012_.z_pos() + p102_.z_pos() + p201_.z_pos()) -
        1. / 6. * (p300_.z_pos() + p030_.z_pos() + p003_.z_pos());

    Coord coords {{x, y, z}}; // Added double brace for Visual 17

    p111_ = ControlPoint(coords);
};

double Patch::projected_surface() const
{
    double d12, d23, d31, sp, surface;

    d12 = sqrt(
        pow(p300().x_pos() - p030().x_pos(), 2) +
        pow(p300().y_pos() - p030().y_pos(), 2)
    );

    d23 = sqrt(
        pow(p030().x_pos() - p003().x_pos(), 2) +
        pow(p030().y_pos() - p003().y_pos(), 2)
    );

    d31 = sqrt(
        pow(p003().x_pos() - p300().x_pos(), 2) +
        pow(p003().y_pos() - p300().y_pos(), 2)
    );

    sp = (d12 + d23 + d31) / 2;

    surface = sqrt(sp*(sp - d12)*(sp - d23)*(sp - d31));

    return surface;
};

double Patch::z_bezier(double u, double v, double w) const
{
    double z = (
        p300_.z_pos() * pow(u, 3) + 3 * (p210_.z_pos() * pow(u, 2) * v + p120_.z_pos() * pow(v, 2) * u) +
        p030_.z_pos() * pow(v, 3) + 3 * (p021_.z_pos() * pow(v, 2) * w + p012_.z_pos() * pow(w, 2) * v) +
        p003_.z_pos() * pow(w, 3) + 3 * (p102_.z_pos() * pow(w, 2) * u + p201_.z_pos() * pow(u, 2) * w) +
        p111_.z_pos() * u * v * w
        );

    return z;
};

// Generated the depositional profile point set from x and y ranges
void Patch::generate_point_set(const std::string& file)
{
    std::ofstream out_file(file, std::ios::out | std::ios::trunc);

    if (out_file) {
        out_file << "x     y     z     u     v     w     " << std::endl;

        for (unsigned u = 0; u <= 100; ++u) {
            for (unsigned v = 0; v <= 100; ++v) {

                if (u + v <= 100) {
                    unsigned w = 100 - u - v;

                    double u_pos = u / 100.;
                    double v_pos = v / 100.;
                    double w_pos = w / 100.;

                    double x = u_pos * p300_.x_pos() + v_pos * p030_.x_pos() + w_pos * p003_.x_pos();
                    double y = u_pos * p300_.y_pos() + v_pos * p030_.y_pos() + w_pos * p003_.y_pos();
                    double z = z_bezier(u_pos, v_pos, w_pos);

                    out_file << x << " " << y << " " << z << " " << u_pos << " " << v_pos << " " << w_pos << std::endl;
                }
            }
        }

        out_file.close();
    }

    else
        std::cerr << "Impossible to open the file!" << std::endl;
};

}; // End of namespace B3D
