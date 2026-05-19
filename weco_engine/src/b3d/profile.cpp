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

#include <b3d/profile.h>

namespace B3D {

// ========================================================================= //
// Sediment Source                                                           //
// ========================================================================= //

// Default constructor
Source::Source(const Coord& coord, const Slope& slope, const SedDir& sed_dir) :
    coord_(coord), slope_(slope), sed_dir_(sed_dir) {};

// Destructor: does nothing
Source::~Source() {};

// ========================================================================= //
// Depositional Profile                                                      //
// ========================================================================= //

// Coordinate system transformation from (xyz) to (XYZ):
// Rotation of the angle corresponding to the sediment direction (sed_dir)
// Translation of the vector corresponding to the position of the sediment source
Coord Profile::xyz_to_xpypzp_transform(double x, double y, double z) const
{
    return {
        (x - source_.x_pos()) * sin(rad(source_.sed_dir())) + (y - source_.y_pos()) * cos(rad(source_.sed_dir())),
        (y - source_.y_pos()) * sin(rad(source_.sed_dir())) - (x - source_.x_pos()) * cos(rad(source_.sed_dir())),
        (z - source_.z_pos())
    };
}

// Coordinate system transformation from (XYZ) to (xyz):
// Rotation of an angle corresponding to the sediment direction (-sed_dir)
// Translation of the vector corresponding to the position of the sediment source
Coord Profile::xpypzp_to_xyz_transform(double X, double Y, double Z) const
{
    return{
        source_.x_pos() + X * sin(rad(source_.sed_dir())) - Y * cos(rad(source_.sed_dir())),
        source_.y_pos() + Y * sin(rad(source_.sed_dir())) + X * cos(rad(source_.sed_dir())),
        source_.z_pos() + Z
    };
}

// Coordinate system transformation from (XYZ) to (xyz):
// Rotation of an angle corresponding to the sediment direction (-sed_dir)
// Translation of the vector corresponding to the position of the sediment source
Coord Profile::xpypzp_to_xsyszs_transform(double X, double Y, double Z) const
{
    return{
        source_.x_pos() + X * sin(rad(source_.sed_dir())) - Y * cos(rad(source_.sed_dir())),
        source_.y_pos() + Y * sin(rad(source_.sed_dir())) + X * cos(rad(source_.sed_dir())),
        source_.z_pos() + Z
    };
}

Coord Profile::marker_to_source_transform(const Coord& marker, const Coord& marker_p) const
{
    double xn = marker[0];
    double yn = marker[1];
    double zn = marker[2];
    
    double xp = marker_p[0];
    double yp = marker_p[1];
    double zp = marker_p[2];
    
    double xs = xn + xp * sin(rad(source_.sed_dir())) - yp * cos(rad(source_.sed_dir()));
    double ys = yn + xp * cos(rad(source_.sed_dir())) + yp * sin(rad(source_.sed_dir()));
    double zs = zn + zp;

    Coord source = { xs, ys, zs };

    return source;
}

// Assign the good facies accordong to the depositional depth
FaciesId Profile::get_facies(double Z) const
{
    FaciesZMap::const_iterator strt = facies_z_map_.begin();
    FaciesZMap::const_iterator stop = facies_z_map_.begin();

    std::advance(stop, facies_z_map_.size() - 1);

    if (Z - source_.z_pos() == strt->second[0])
        return strt->first;

    else if (Z - source_.z_pos() == stop->second[0])
        return stop->first;

    else {
        for (unsigned index = 1; index < facies_z_map_.size() - 1; ++index) {

            FaciesZMap::const_iterator iter = facies_z_map_.begin();

            std::advance(iter, index);

            if (iter->second[0] <= Z - source_.z_pos() && Z - source_.z_pos() <= iter->second[1])
                return iter->first;
        }
        assert(false);
    }
}

// Compute the radius within the deltaic ellipsoid from the direction (dir)
// Input angle have to be in degree
double Profile::dir_to_radius(double dir) const
{
    double A = rad(dir);

    return source_.dX() * source_.dY() / dist(source_.dY()*cos(A), source_.dX()*sin(A));
}

// Compute the azimuth from Cartesian coordinates (x,y)
double Profile::xy_to_dir(double X, double Y) const
{
    double R = sqrt(X*X + Y*Y);

    if (X == 0 && Y == 0) { return 000.00; }

    else if (X >= 0 && Y >= 0) { return deg(1 * PI2 - acos( X / R)); }
    else if (X >= 0 && Y <= 0) { return deg(1 * PI2 + acos( X / R)); }
    else if (X <= 0 && Y <= 0) { return deg(3 * PI2 - acos(-X / R)); }
    else  { return deg(3 * PI2 + acos(-X / R)); }
}

// Compute the depositional dip from Cartesian coordinates (x,y)
double Profile::xy_to_dip(double X, double Y) const
{
    double R = sqrt(X*X + Y*Y);

    double dY = source_.dY();
    double dZ = source_.dZ();
    double dR = xy_to_radius(X, Y);

    if (X == 0 && Y == 0) { return 0.00; }

    else if (X <= 0 && abs(Y) / dY < 1) { return deg(atan(PI / 2 * dZ * sin(abs(Y) / dY * PI) / dY)); }

    else if (X >= 0 && abs(R) / dR < 1) { return deg(atan(PI / 2 * dZ * sin(abs(R) / dR * PI) / dR)); }

    return 0.00;
};

// Compute the depositional depth from Cartesian coordinates (x,y)
double Profile::xy_to_depth(double X, double Y) const
{
    double R = dist(X, Y);

    double dY = source_.dY();
    double dZ = source_.dZ();
    double dR = xy_to_radius(X, Y);

    if (X == 0 && Y == 0) { return 0.00; }

    else if (X <= 0 && abs(Y) / dY <= 1) { return source_.z_pos() + dZ * pow(sin(abs(Y) / dY * PI / 2), 2); }

    else if (X >= 0 && abs(R) / dR <= 1) { return source_.z_pos() + dZ * pow(sin(abs(R) / dR * PI / 2), 2); }

    return source_.z_pos() + dZ;
};

// Compute the radius within the deltaic ellipsoid from Cartesian coordinates (x,y)
double Profile::xy_to_radius(double X, double Y) const
{
    double A = rad(xy_to_dir(X, Y));

    return source_.dX() * source_.dY() / dist(source_.dX()*cos(A), source_.dY()*sin(A));
}

// Compute the depositional depth from Barycentric coordinates (u,v)
double Profile::uv_to_depth(double u, double v, const B3D::Curve& curve) const
{
    double X = curve.p30().x_pos() * u + curve.p03().x_pos() * v;
    double Y = curve.p30().y_pos() * u + curve.p03().y_pos() * v;

    return xy_to_depth(X, Y);
};

// Compute the depositional depth from Barycentric coordinates (u,v,w)
double Profile::uvw_to_depth(double u, double v, double w, const B3D::Patch& patch) const
{
    double X = patch.p300().x_pos() * u + patch.p030().x_pos() * v + patch.p003().x_pos() * w;
    double Y = patch.p300().y_pos() * u + patch.p030().y_pos() * v + patch.p003().y_pos() * w;

    return xy_to_depth(X, Y);
};

// Generated the depositional profile point set from x and y ranges
void Profile::generate_point_set(const Range& X_range, const Range& Y_range, const std::string& file)
{
    std::ofstream cout_file(file, std::ios::out | std::ios::trunc);

    if (cout_file) {
        cout_file << "X     Y     Z     Xs    Ys    Rs   Dir   Dip   Facies   Zone" << std::endl;

        double Xs, Ys, Zs, Rs, dR, Dip, Dir, Rad;

        unsigned Zone, Facies;

        double dY = source_.dY();

        for (unsigned X_iter = 0; X_iter <= X_range[2]; ++X_iter) {
            for (unsigned Y_iter = 0; Y_iter <= Y_range[2]; ++Y_iter) {

                double X = X_range[0] + X_iter * (X_range[1] - X_range[0]) / X_range[2];
                double Y = Y_range[0] + Y_iter * (Y_range[1] - Y_range[0]) / Y_range[2];

                Xs = xyz_to_xpypzp_transform(X, Y, 0)[0];
                Ys = xyz_to_xpypzp_transform(X, Y, 0)[1];

                Rs = sqrt(Xs*Xs + Ys*Ys);

                dR = xy_to_radius(Xs, Ys);

                Zs = xy_to_depth(Xs, Ys);

                Dip = xy_to_dip(Xs, Ys);

                Dir = xy_to_dir(X - source_.x_pos(), Y - source_.y_pos());

                if (Xs == 0 && Ys == 0)
                    Rad = 0.0;

                else if (Xs <= 0 && abs(Ys) / dY <= 1) {
                    Rad = abs(Ys) / dY;
                    Zone = 1;
                }

                else if (Xs >= 0 && abs(Rs) / dR < 1) {
                    Rad = Rs / dR;
                    Zone = 2;
                }

                else {
                    Rad = 1.0;
                    Zone = 3;
                }

                Facies = get_facies(Zs);

                cout_file << X << " " << Y << " " << Zs << " " << Xs << " " << Ys << " " << Rad << " " << Dir << " " << Dip << " " << Facies << " " << Zone << '\n';
            }
        }

        cout_file.close();
    }

    else
        std::cerr << "Impossible to open the file!" << std::endl;
};

// Compute the vertical distance between corner nodes with the good weight
double Profile::corner_area(const B3D::Curve& curve) const
{
    double area = 0.00;

    area += fabs(curve.p30().z_pos() - uv_to_depth(1, 0, curve)) / 2.00;
    area += fabs(curve.p03().z_pos() - uv_to_depth(0, 1, curve)) / 2.00;

    return area;
};

// Compute the vertical distance between border nodes with the good weight
double Profile::border_area(const B3D::Curve& curve) const
{
    double area = 0.00;

    // double x_pos = 0.;
    // double y_pos = 0.;

    for (double u : { .1, .2, .3, .4, .5, .6, .7, .8, .9 }) {
        // x_pos = u * curve.p30().x_pos() + (1 - u) * curve.p03().x_pos();
        // y_pos = u * curve.p30().y_pos() + (1 - u) * curve.p03().y_pos();

        area += fabs(curve.z_bezier(u, 1 - u) - uv_to_depth(u, 1 - u, curve));
    }

    return area;
};

// Compute the absolute area between two complex 3D curves
double Profile::compute_area(const B3D::Curve& curve) const
{
    double area = 0;

    area += corner_area(curve);
    area += border_area(curve);

    area *= curve.projected_distance() / 10.00;

    return area;
};

// Compute the vertical distance between corner nodes with the good weight
double Profile::corner_volume(const B3D::Patch& patch) const
{
    double volume = 0.;

    volume += fabs(patch.p300().z_pos() - uvw_to_depth(1, 0, 0, patch)) / 3.00;
    volume += fabs(patch.p030().z_pos() - uvw_to_depth(0, 1, 0, patch)) / 3.00;
    volume += fabs(patch.p003().z_pos() - uvw_to_depth(0, 0, 1, patch)) / 3.00;

    return volume;
};

// Compute the vertical distance between border nodes with the good weight
double Profile::border_volume(const B3D::Patch& patch) const
{
    double volume = 0.;

    // double x_pos = 0.;
    // double y_pos = 0.;

    for (auto v : { .1, .2, .3, .4, .5, .6, .7, .8, .9 }) {
        volume += fabs(patch.z_bezier(0, v, 1 - v) - uvw_to_depth(0, v, 1 - v, patch));

        // x_pos = 0 * patch.p300().x_pos() + v * patch.p030().x_pos() + (1 - v) * patch.p003().x_pos();
        // y_pos = 0 * patch.p300().y_pos() + v * patch.p030().y_pos() + (1 - v) * patch.p003().y_pos();

        volume += fabs(patch.z_bezier(1 - v, 0, v) - uvw_to_depth(1. - v, 0, v, patch));

        // x_pos = (1 - v) * patch.p300().x_pos() + 0 * patch.p030().x_pos() + v * patch.p003().x_pos();
        // y_pos = (1 - v) * patch.p300().y_pos() + 0 * patch.p030().y_pos() + v * patch.p003().y_pos();

        volume += fabs(patch.z_bezier(v, 1 - v, 0) - uvw_to_depth(v, 1 - v, 0, patch));

        // x_pos = v * patch.p300().x_pos() + (1 - v) * patch.p030().x_pos() + 0 * patch.p003().x_pos();
        // y_pos = v * patch.p300().y_pos() + (1 - v) * patch.p030().y_pos() + 0 * patch.p003().y_pos();
    }

    return volume;
};

// Compute the vertical distance between central nodes with the good weight
double Profile::center_volume(const B3D::Patch& patch) const
{
    double volume = 0.;

    //double x_pos = 0.;
    //double y_pos = 0.;

    for (auto u : { .1, .2, .3, .4, .5, .6, .7, .8 }) {
        for (double v = 0.1; v <= 0.9 - u; v += .1) {
            volume += 2 * fabs(patch.z_bezier(u, v, 1 - u - v) - uvw_to_depth(u, v, 1 - u - v, patch));

            //x_pos = u * patch.p300().x_pos() + v * patch.p030().x_pos() + (1 - u - v) * patch.p003().x_pos();
            //y_pos = u * patch.p300().y_pos() + v * patch.p030().y_pos() + (1 - u - v) * patch.p003().y_pos();

            volume += 2 * fabs(patch.z_bezier(1 - u - v, u, v) - uvw_to_depth(1 - u - v, u, v, patch));

            //x_pos = (1 - u - v) * patch.p300().x_pos() + u * patch.p030().x_pos() + v * patch.p003().x_pos();
            //y_pos = (1 - u - v) * patch.p300().y_pos() + u * patch.p030().y_pos() + v * patch.p003().y_pos();

            volume += 2 * fabs(patch.z_bezier(v, 1 - u - v, u) - uvw_to_depth(v, 1 - u - v, u, patch));

            //x_pos = v * patch.p300().x_pos() + (1 - u - v) * patch.p030().x_pos() + u * patch.p003().x_pos();
            //y_pos = v * patch.p300().y_pos() + (1 - u - v) * patch.p030().y_pos() + u * patch.p003().y_pos();
        }
    }

    return volume;
};

// Compute the absolute volume between two 3D triangular surfaces
double Profile::compute_volume(const B3D::Patch& patch) const
{
    double volume = 0.;

    volume += corner_volume(patch);
    volume += border_volume(patch);
    volume += center_volume(patch);

    volume *= patch.projected_surface() / 100.00;

    return volume;
};
// Compute the likeliest position of the well marker on the depositional profile

// ========================================================================= //
// Well Marker                                                               //
// ========================================================================= //

// Default constructor
Marker::Marker(const Profile& dep_profile, const CornerPoint& marker) :
    marker_(marker), dep_profile_(dep_profile)
{
    dep_source_ = dep_profile_.source();

    dep_marker_ = marker_in_dep_profile();

    source_ = source_in_space();

    profile_ = profile_in_space();
};

// Destructor: does nothing
Marker::~Marker() {};

// Position of the marker in the depositional coordinate system
CornerPoint Marker::marker_in_dep_profile() const
{
    double dir = marker_.dipmeter()[0]; // Angle in degree
    double dip = marker_.dipmeter()[1]; // Angle in degree

    double dip_dir = (dir < 270.00 ? dir + 090.00 : dir - 270.00);

    double angle = dep_source_.sed_dir() - dip_dir + 180.00; // Angle in degree

    unsigned facies = marker_.facies_id();

    double facies_z_bot = dep_profile_.facies_z_map()[facies][0];
    double facies_z_top = dep_profile_.facies_z_map()[facies][1];

    assert((angle >= 000.00) && (angle <= 180.00));

    double xp = 0.00;
    double yp = 0.00;
    double zp = 0.00;;

    double rp = dep_profile_.dir_to_radius(angle);

    double dip_error = +1e38;

    for (unsigned i = 0; i <= 100; ++i) {
        double rpi = (double)i / 100.00 * rp;

        double xpi = rpi * cos(angle);
        double ypi = rpi * sin(angle);

        double zpi = dep_profile_.xy_to_depth(xpi, ypi);

        double dpi = dep_profile_.xy_to_dip(xpi, ypi);

        if (abs(dip - dpi) < dip_error && (facies_z_bot <= zpi && zpi <= facies_z_top)) {
            xp = xpi;
            yp = ypi;
            zp = zpi;
            dip_error = abs(dip - dpi);
        }
    }

    Coord dep_coord = { xp, yp, zp };

    CornerPoint dep_marker = { dep_coord, marker_.dipmeter(), marker_.facies_id(), marker_.extension() };

    return dep_marker;
}

// Position of the sediment source in the spatial coordinate system
Source Marker::source_in_space() const
{
    double xs = xn() + xp() * sin(rad(dep_source_.sed_dir())) - yp() * cos(rad(dep_source_.sed_dir()));
    double ys = yn() + xp() * cos(rad(dep_source_.sed_dir())) + yp() * sin(rad(dep_source_.sed_dir()));
    double zs = zn() + zp();

    Coord coord = { xs, ys, zs };

    Source source = { coord, dep_source_.slope(), dep_source_.sed_dir() };

    return source;
}

// Position of the depositional profile in the spatial coordinate system
Profile Marker::profile_in_space() const
{
    Profile profile = { source_, dep_profile_.facies_z_map() };

    return profile;
}

}; // End of namespace B3D
