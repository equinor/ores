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

#ifndef __b3d_marker_h__
#define __b3d_marker_h__

#include <b3d/common.h> // Must be included by every file of the b3d library.

namespace B3D {

// ===================================================================== //
// Bezier 3D Well Markers                                                //
// ===================================================================== //
class CornerPoint {

public:

    CornerPoint(
        const Coord& coord = coord_ndv,
        const Dipmeter& dipmeter = dipmeter_ndv,
        const FaciesId& facies_id = undv,
        const FaciesExt& extension = facies_ext_ndv
    );

    ~CornerPoint();

    void compute_normal();

    // Apparent strike direction and dip angle
    Dipmeter apparent_dipmeter(const CornerPoint& marker_2) const;

    // Accessors to corner point coordinates
    double x_pos() const { return coord_[0]; };
    double y_pos() const { return coord_[1]; };
    double z_pos() const { return coord_[2]; };

    // Accessors to corner point extension
    double x_ext() const { return extension_[0]; };
    double y_ext() const { return extension_[1]; };
    double z_ext() const { return extension_[2]; };

    // Accessors to Class attributs
    Coord coord() const { return coord_; };
    Normal normal() const { return normal_; };
    Dipmeter dipmeter() const { return dipmeter_; };
    FaciesId facies_id() const { return facies_id_; };
    FaciesExt extension() const { return extension_; };

protected:

    Coord coord_;
    Normal normal_;
    Dipmeter dipmeter_;
    FaciesId facies_id_;
    FaciesExt extension_;

};

} // End of namespace B3D

#endif // __b3d_marker_h__