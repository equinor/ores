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

#ifndef __b3d_curve_h__
#define __b3d_curve_h__

#include <b3d/common.h>

#include <b3d/corner_point.h>
#include <b3d/control_point.h>

namespace B3D {

// ========================================================================= //
// Bezier 3D Curve                                                           //
// ========================================================================= //
class Curve {

public:

    Curve(const CornerPoint& marker_1, const CornerPoint& marker_2);

    ~Curve();

    double projected_distance() const;

    double z_bezier(double u, double v) const;

    double r12() const { return r12_; };
    double r21() const { return r21_; };

    // Accessors to normal vectors
    Normal n30() const { return n30_; };
    Normal n03() const { return n03_; };

    // Accessors to Corner Points
    CornerPoint p30() const { return p30_; };
    CornerPoint p03() const { return p03_; };

    // Accessors to Control Points
    ControlPoint p21() const { return p21_; };
    ControlPoint p12() const { return p12_; };
    
    std::vector< CornerPoint > corner_points() const { return{ p30_, p03_ }; };
    std::vector< ControlPoint > control_points() const { return{ p21_, p12_ }; };

	// Generate the depositional point set
	void generate_point_set(const std::string& file);

private:

    double r12_; // Radius of marker 1 influence.
    double r21_; // Radius of marker 2 influence.

    Normal n30_; // Normal vector at p30 computed from dipmeter data.
    Normal n03_; // Normal vector at p03 computed from dipmeter data.

    CornerPoint p30_; // Well marker 1 : Corner point 30.
    CornerPoint p03_; // Well marker 2 : Corner point 03.

    ControlPoint p21_; // Control point 21 linked to corner point 30.
    ControlPoint p12_; // Control point 21 linked to corner point 03.
};

} // End of namespace B3D

#endif // __b3d_point_h__