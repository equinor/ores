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

#ifndef __b3d_patch_h__
#define __b3d_patch_h__

#include <b3d/common.h>

#include <b3d/corner_point.h>
#include <b3d/control_point.h>

namespace B3D {

// ========================================================================= //
// Bezier 3D Curve                                                           //
// ========================================================================= //
class Patch {

public:

    Patch(const CornerPoint& marker_1, const CornerPoint& marker_2, const CornerPoint& marker_3);

    ~Patch();

    void compute_p111_coords();

    // Computes the area of the vertical projected triangular surfaces
    double projected_surface() const;
    
    // Computes z value from barycentric coordinates (u,v,w)
    double z_bezier(double u, double v, double w) const;

    // Accessors to normal vectors
    Normal n300() const { return n300_; };
    Normal n030() const { return n030_; };
    Normal n003() const { return n003_; };

    // Accessors to Corner points
    CornerPoint p300() const { return p300_; };
    CornerPoint p030() const { return p030_; };
    CornerPoint p003() const { return p003_; };

    // Accessors to Control points
    ControlPoint p210() const { return p210_; };
    ControlPoint p201() const { return p201_; };
    ControlPoint p120() const { return p120_; };
    ControlPoint p021() const { return p021_; };
    ControlPoint p102() const { return p102_; };
    ControlPoint p012() const { return p012_; };
    ControlPoint p111() const { return p111_; };

    const std::vector< CornerPoint > corner_points() { return{ p300_, p030_, p003_ }; };
    const std::vector< ControlPoint > control_points() { return{ p210_, p201_, p120_, p021_, p102_, p012_, p111_ }; };

	// Generate the depositional point set
	void generate_point_set(const std::string& file);

private:

    Normal n300_; // Normal vector at p300 computed from dipmeter data.
    Normal n030_; // Normal vector at p030 computed from dipmeter data.
    Normal n003_; // Normal vector at p003 computed from dipmeter data.

    CornerPoint p300_; // Well marker 1 : Corner point 300.
    CornerPoint p030_; // Well marker 2 : Corner point 030.
    CornerPoint p003_; // Well marker 3 : Corner point 003.

    ControlPoint p210_; // Control point 210 linked to corner point 300.
    ControlPoint p201_; // Control point 201 linked to corner point 300.
    ControlPoint p120_; // Control point 120 linked to corner point 030.
    ControlPoint p021_; // Control point 021 linked to corner point 030.
    ControlPoint p102_; // Control point 102 linked to corner point 003.
    ControlPoint p012_; // Control point 012 linked to corner point 003.
    ControlPoint p111_; // Control point 111 linked to all other points.    
};

} // End of namespace B3D

#endif // __b3d_patch_h__