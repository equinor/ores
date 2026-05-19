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

#ifndef __profile_h__
#define __profile_h__

#include <b3d/curve.h>
#include <b3d/patch.h>
#include <b3d/common.h>
#include <b3d/corner_point.h>
#include <b3d/control_point.h>

namespace B3D {

// ===================================================================== //
// Sediment Source                                                       //
// ===================================================================== //

class Source {

public:

    Source(
        const Coord& coord = {0,0,0},
        const Slope& slope = {1,1,0},
        const SedDir& sed_dir = 090.00
    );

    ~Source();

    // Modify the coordinate of the sediment source
    void set_coord(const Coord& coord) { coord_ = coord; };

    // Accessors to sediment source coordinates
    double x_pos() const { return coord_[0]; };
    double y_pos() const { return coord_[1]; };
    double z_pos() const { return coord_[2]; };

    // Accessors to slope extension
    double dX() const { return slope_[0]; };
    double dY() const { return slope_[1]; };
    double dZ() const { return slope_[2]; };

    // Accessors to Class attributs
    Coord coord() const { return coord_; };
    Slope slope() const { return slope_; };
    SedDir sed_dir() const { return sed_dir_; };

protected:

    Coord coord_;
    Slope slope_;
    SedDir sed_dir_;
};

// ===================================================================== //
// Depositional Profile                                                  //
// ===================================================================== //

class Profile {

public:

    Profile() {};

    Profile(const Source& source) : source_(source) {};

    Profile(const FaciesZMap& facies_z_map) : facies_z_map_(facies_z_map) {};

    Profile(const Source& source, const FaciesZMap& facies_z_map) : source_(source), facies_z_map_(facies_z_map) {};

    ~Profile() {};

    // Depositional profile -> Facies assignation
    FaciesId get_facies(double z) const;

    // Coordinate system transformation
    Coord xyz_to_xpypzp_transform(double x, double y, double z) const;
    Coord xpypzp_to_xyz_transform(double xp, double yp, double zp) const;
    Coord xpypzp_to_xsyszs_transform(double xp, double yp, double zp) const;

    Coord marker_to_source_transform(const Coord& marker, const Coord& marker_p) const;

    // Depositional profile -> Mathematical definition
    double dir_to_radius(double dir) const;

    double xy_to_dip(double x, double y) const;
    double xy_to_dir(double x, double y) const;
    double xy_to_depth(double x, double y) const;
    double xy_to_radius(double x, double y) const;

    double uv_to_depth(double u, double v, const B3D::Curve& curve) const;
    double uvw_to_depth(double u, double v, double w, const B3D::Patch& patch) const;

    // Generate the depositional point set
    void generate_point_set(const Range& x_range, const Range& y_range, const std::string& file);

    // Functionalities -> Area between two complex 3D curves
    double corner_area(const B3D::Curve& curve) const;
    double border_area(const B3D::Curve& curve) const;

    double compute_area(const B3D::Curve& curve) const;

    // Functionalities -> Volume between two 3D triangular surfaces
    double border_volume(const B3D::Patch& patch) const;
    double center_volume(const B3D::Patch& patch) const;
    double corner_volume(const B3D::Patch& patch) const;

    double compute_volume(const B3D::Patch& patch) const;

    // Accessors to Class attributs
    Source source() const { return source_; };
    FaciesZMap facies_z_map() const { return facies_z_map_; };

protected:

    Source source_;
    FaciesZMap facies_z_map_;
};

// ===================================================================== //
// Well Marker                                                           //
// ===================================================================== //

class Marker {

public:

    Marker(const Profile& dep_profile, const CornerPoint& marker);

    ~Marker();

    // Accessors to marker spatial coordinates
    double xn() const { return marker_.x_pos(); };
    double yn() const { return marker_.y_pos(); };
    double zn() const { return marker_.z_pos(); };

    // Accessors to sediment source coordinates
    double xs() const { return source_.x_pos(); };
    double ys() const { return source_.y_pos(); };
    double zs() const { return source_.z_pos(); };

    // Accessors to marker depositional coordinates
    double xp() const { return dep_marker_.x_pos(); };
    double yp() const { return dep_marker_.y_pos(); };
    double zp() const { return dep_marker_.z_pos(); };

    Source source() const { return source_; };
    Source dep_source() const { return dep_source_; };

    Profile profile() const { return profile_; };
    Profile dep_profile() const { return dep_profile_; };

    CornerPoint marker() const { return marker_; };
    CornerPoint dep_marker() const { return dep_marker_; };

    Source source_in_space() const;
    Profile profile_in_space() const;

    CornerPoint marker_in_dep_profile() const;

protected:

    Source source_;
    Profile profile_;
    CornerPoint marker_;
    
    Source dep_source_;
    Profile dep_profile_;
    CornerPoint dep_marker_;
};

} // End of namespace Profile

#endif // __profile_h__