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
 */


#include <weco/project.h>

#include <b3d/curve.h>
#include <b3d/patch.h>
#include <b3d/profile.h>
#include <b3d/corner_point.h>
#include <b3d/control_point.h>

#include <cassert>
#include <filesystem>

namespace WeCo {

namespace  {

using namespace B3D;

// ========================================================================= //
// Depositional profile vs Dipmeter data Cost Function (2 wells)             //
// ========================================================================= //

class _CCFPartB3DCurve : public CCFPart {

public:

    _CCFPartB3DCurve(
        const Project& project,
        const CCFContext& context,

        const std::string& dip,             // Depositional dip angle (degree)
        const std::string& azim,            // Depositional strike direction (degree)

        const std::string& depth,           // Z position of the well marker (m)

        const std::string& facies,          // Depositional sedimentary facies (id)

        bool write_bezier,                  // Creates all bezier lines files
        bool write_profile,                 // Creates all depositional profile files

        const std::string bezier_folder,    // Folder to store all bezier lines files
        const std::string profile_folder,   // Folder to store all depositional profile files

        const std::string& dep_facies_file, // All information about depositional facies
        const std::string& dep_profile_file,// All information about depositional profile
        bool normalize                      // Normalize cost by characteristic area
    ) :
        CCFPart(context),

        dip_(context, project.well_list(), dip),
        azim_(context, project.well_list(), azim),

        depth_(context, project.well_list(), depth),

        facies_(context, project.well_list(), facies),

        write_bezier_(write_bezier),
        write_profile_(write_profile),

        bezier_folder_(bezier_folder),
        profile_folder_(profile_folder),

        dep_facies_file_(dep_facies_file),
        dep_profile_file_(dep_profile_file),
        normalize_(normalize)
    {
        well_1_ = context.size1() - 1; //  Last well of the correlation graph 1
        well_2_ = context.size1();     // First well of the correlation graph 2

        x_well_1_ = project.well_list().well(well_1_)->x();   // X position of well markers in Well 1
        y_well_1_ = project.well_list().well(well_1_)->y();   // Y position of well markers in Well 1
        h_well_1_ = project.well_list().well(well_1_)->len(); // Length of the well 1

        x_well_2_ = project.well_list().well(well_2_)->x();   // X position of well markers in Well 2
        y_well_2_ = project.well_list().well(well_2_)->y();   // Y position of well markers in Well 2
        h_well_2_ = project.well_list().well(well_2_)->len(); // Length of the well 2

        double dist_well = dist(x_well_1_ - x_well_2_, y_well_1_ - y_well_2_);

        norm_aera_ = (h_well_1_ + h_well_2_) * dist_well / 2.00;
        
        read_dep_profile_file();

        read_dep_facies_file();

        if (well_1_ == 0)
            write_dep_profile_file(project);
    }

	bool full_cost(CostValue& cost) override
    {
        CostValue prev_cost = context.parent_cost1();

        B3D::Profile profile( source_, facies_z_map_ );

        B3D::CornerPoint corner_point_1 = create_corner_point(well_1_, x_well_1_, y_well_1_);
        B3D::CornerPoint corner_point_2 = create_corner_point(well_2_, x_well_2_, y_well_2_);

        B3D::Marker well_marker_1 = { profile, corner_point_1 };
        B3D::Marker well_marker_2 = { profile, corner_point_2 };

        std::string name_marker_1 = std::to_string(well_1_) + "-" + std::to_string(context.dest(well_1_));
        std::string name_marker_2 = std::to_string(well_2_) + "-" + std::to_string(context.dest(well_2_));

        B3D::Curve bezier_curve ( corner_point_1, corner_point_2 );

        std::string beziez_file_name = bezier_folder_ + "/bezier_" + name_marker_1 + "_" + name_marker_2 + ".bez";
        std::ifstream bezier_file(beziez_file_name);

        if (write_bezier_)
            bezier_curve.generate_point_set(beziez_file_name);

        B3D::Profile profile_1 = well_marker_1.profile();
        B3D::Profile profile_2 = well_marker_2.profile();

        std::string profile_file_1_name = profile_folder_ + "/profile_" + name_marker_1 + ".dep";
        std::ifstream profile_file_1(profile_file_1_name);

        std::string profile_file_2_name = profile_folder_ + "/profile_" + name_marker_2 + ".dep";
        std::ifstream profile_file_2(profile_file_2_name);

        if (write_profile_) {
            Range x_range = { std::min(x_well_1_,x_well_2_), std::max(x_well_1_,x_well_2_), 100 };
            Range y_range = { std::min(y_well_1_,y_well_2_), std::max(y_well_1_,y_well_2_), 100 };

            profile_1.generate_point_set(x_range, y_range, profile_file_1_name);
            profile_2.generate_point_set(x_range, y_range, profile_file_2_name);
        }

        CostValue cost_1 = profile_1.compute_area(bezier_curve);
        CostValue cost_2 = profile_2.compute_area(bezier_curve);

        if (normalize_ && norm_aera_ > 0.0) {
            cost_1 /= norm_aera_;
            cost_2 /= norm_aera_;
        }

        cost += prev_cost + (cost_1 + cost_2) / 2.00;   // Cost increment to allow for composite costs.

        return true;
    }

    bool dest_only() const override { return false; }

    void read_dep_facies_file()
    {
        std::ifstream cin_file(dep_facies_file_, std::ios::in);  // on ouvre le fichier en lecture
        
        if (cin_file) {
        
            std::string file_line;
        
            facies_map_.clear();
            facies_z_map_.clear();

            double facies_id;
        
            double facies_x_ext;
            double facies_y_ext;
            double facies_z_ext;
        
            double facies_z_top;
            double facies_z_bot;
        
            Range facies_zrange;
            FaciesExt facies_ext;

            while (cin_file) {
                cin_file >> facies_id;

                if (cin_file.eof()) break;
                
                cin_file >> facies_x_ext >> facies_y_ext >> facies_z_ext >> facies_z_top >> facies_z_bot;

                facies_zrange = { facies_z_bot , facies_z_top };
                facies_ext = { facies_x_ext , facies_y_ext , facies_z_ext };

                facies_map_[facies_id] = facies_ext;
                facies_z_map_[facies_id] = facies_zrange;
            }

            cin_file.close();
        }
        
        else
            std::cerr << "Impossible to open the file!" << std::endl;
    }

    void read_dep_profile_file()
    {
        std::ifstream cin_file(dep_profile_file_, std::ios::in);  // on ouvre le fichier en lecture

        if (cin_file) {

            std::string file_line;

            while (cin_file) {

                if (cin_file.eof()) break;

                cin_file >> dX_src_ >> dY_src_ >> dZ_src_ >> sed_dir_;

            }

            cin_file.close();


            slope_ = { dX_src_,dY_src_,dZ_src_ };

            source_ = B3D::Source({ 0,0,0 }, slope_, sed_dir_);
        }

        else
            std::cerr << "Impossible to open the file!" << std::endl;
    }

    void write_dep_profile_file(const Project& project)
    {
        B3D::Float x_max = -1e38; // x max value initialization
        B3D::Float x_min = +1e38; // x min value initialization

        B3D::Float y_max = -1e38; // y max value initialization
        B3D::Float y_min = +1e38; // y min value initialization

        B3D::Float z_max = -1e38; // z max value initialization
        B3D::Float z_min = +1e38; // z min value initialization

        // Find extrem values of x and y in the entire data set.
        for (unsigned id_well = 0; id_well < project.well_list().nbr_wells(); ++id_well) {

            const Well* cur_well = project.well_list().well(id_well);

            B3D::Float x_pos = cur_well->x(); // x position
            B3D::Float y_pos = cur_well->y(); // y position
            B3D::Float z_pos = cur_well->z(); // z position

            if (x_max < x_pos)
                x_max = x_pos; // x max value updating

            if (x_min > x_pos)
                x_min = x_pos; // x min value updating

            if (y_max < y_pos)
                y_max = y_pos; // y max value updating

            if (y_min > y_pos)
                y_min = y_pos; // y min value updating

            if (z_max < z_pos)
                z_max = z_pos; // z max value updating

            if (z_min > z_pos)
                z_min = z_pos; // z min value updating
        }

        std::cout << "(" << x_min << "," << x_max << ") (" << y_min << "," << y_max << ") (" << z_min << "," << z_max << ")" << std::endl;

        B3D::Float len_x = x_max - x_min;
        B3D::Float len_y = y_max - y_min;

        if (len_x > len_y) {
            x_min -= 0.1 * len_x;
            x_max += 0.1 * len_x;

            y_min -= 0.1 * len_x + 0.5 * (len_x - len_y);
            y_max += 0.1 * len_x + 0.5 * (len_x - len_y);
        }

        else if (len_x < len_y) {
            x_min -= 0.1 * len_y + 0.5 * (len_y - len_x);
            x_max += 0.1 * len_y + 0.5 * (len_y - len_x);

            y_min -= 0.1 * len_y;
            y_max += 0.1 * len_y;
        }

        else {
            x_min -= 0.1 * len_x;
            x_max += 0.1 * len_x;

            y_min -= 0.1 * len_y;
            y_max += 0.1 * len_y;
        }

        B3D::Range x_range = { x_min, x_max, 100 }; // x range
        B3D::Range y_range = { y_min, y_max, 100 }; // y range

        B3D::Float x_source = (x_min + x_max) / 2.00;
        B3D::Float y_source = (y_min + y_max) / 2.00;
        B3D::Float z_source = (z_min + z_max) / 2.00;

        std::cout << "Source (" << x_source << "," << y_source << "," << z_source << ")" << std::endl;

        B3D::Coord source_coord = { x_source, y_source, z_source };

        B3D::Source source(source_coord, slope_, sed_dir_);

        B3D::Profile profile(source, facies_z_map_);

        profile.generate_point_set(x_range, y_range, profile_folder_ + "/profile.dep");
    }

    B3D::CornerPoint create_corner_point(const WellId& well_id, double x_coord, double y_coord)
    {
        CostValue depth = depth_.dest_data(well_id);

        CostValue dip = dip_.dest_data(well_id);

        CostValue azimuth = (azim_.dest_data(well_id) - 90.00 < 0.00 ? azim_.dest_data(well_id) + 270.00 : azim_.dest_data(well_id) - 90.00);

        CostValue facies = facies_.dest_data(well_id);

        B3D::Coord coord = { x_coord, y_coord, depth };

        B3D::Dipmeter dipmeter = { azimuth, dip };

        B3D::FaciesExt extension = facies_map_[facies];

        B3D::CornerPoint corner_point = { coord, dipmeter, (unsigned)facies, extension };

        return corner_point;
    }

    WellId well_1_;
    WellId well_2_;

    double x_well_1_;
    double x_well_2_;

    double y_well_1_;
    double y_well_2_;

    double h_well_1_;
    double h_well_2_;

    double norm_aera_;
    bool normalize_;

    Slope slope_;
    Source source_;

    double dX_src_;
    double dY_src_;
    double dZ_src_;

    double sed_dir_;

    CostHelperData dip_;
    CostHelperData azim_;

    CostHelperData depth_;

    CostHelperData facies_;

    bool write_bezier_;
    bool write_profile_;

    FaciesMap facies_map_;
    FaciesZMap facies_z_map_;

    std::string bezier_folder_;
    std::string profile_folder_;

    std::string dep_facies_file_;
    std::string dep_profile_file_;
};

class _CCFPartB3DCurveFactory : public CCFGlobalPartFactory {

public:

protected:

    OptionData option_dip{ "b3d-curve-dip","","It corresponds to the dip angle (deg).","50CCF.B3DCurve" };
    OptionData option_azim{ "b3d-curve-azimuth","","It corresponds to the strike orientation (deg).","50CCF.B3DCurve" };
    OptionData option_depth{ "b3d-curve-depth","","It corresponds to the z-axis coordinate.","50CCF.B3DCurve" };
    OptionData option_facies{ "b3d-curve-facies","","It corresponds to the paleo-depth of the deposit.","50CCF.B3DCurve" };

    OptionBool option_write_bezier{ "b3d-curve-write-bezier",false,"If true, it generates point sets of all Bezier curves interpolations.","50CCF.B3DCurve" };
    OptionBool option_write_profile{ "b3d-curve-write-profile",false,"If true, it generates point sets of all translated depositional profiles.","50CCF.B3DCurve" };
    OptionBool option_normalize{ "b3d-curve-normalize",true,"Normalize B3D cost by characteristic area (h1+h2)*d/2.","50CCF.B3DCurve" };
    
    OptionString option_bezier_folder{ "b3d-curve-bezier-folder","","It corresponds to the file where all information about facies are stored (z range, lateral & vertical extension).","50CCF.B3DCurve" };
    OptionString option_profile_folder{ "b3d-curve-profile-folder","","It corresponds to the file where all information about facies are stored (z range, lateral & vertical extension).","50CCF.B3DCurve" };

    OptionString option_dep_facies_file{ "b3d-curve-dep-facies-file","","It corresponds to the file where all information about depositional facies are stored (z range, lateral & vertical extension).","50CCF.B3DCurve" };
    OptionString option_dep_profile_file{ "b3d-curve-dep-profile-file","","It corresponds to the file where all information about depositional profile are stored (lateral and vertical extension & sediment direction).","50CCF.B3DCurve" };

    virtual bool test(const Project& project) const override
    {
        return (
            option_dip.project_check(project,true) &&
            option_azim.project_check(project, true) &&
            option_depth.project_check(project, true) &&
            option_facies.project_check(project, true)
        );
    }

    virtual CCFPart* create(const Project& project, const CCFContext& context) const override
    {
        if ( !option_dip || !option_azim || !option_depth || !option_facies )
            return nullptr;

        return new _CCFPartB3DCurve(
            project,
            context,
            option_dip(),
            option_azim(),
            option_depth(),
            option_facies(),
            option_write_bezier(),
            option_write_profile(),
            option_bezier_folder(),
            option_profile_folder(),
            option_dep_facies_file(),
            option_dep_profile_file(),
            option_normalize()
        );
    }
};

static _CCFPartB3DCurveFactory _ccf_part_b3d_curve_factory;

// ========================================================================= //
// Depositional profile vs Dipmeter data Cost Function (3 wells)             //
// ========================================================================= //

class _CCFPartB3DPatch : public CCFPart {

public:

    _CCFPartB3DPatch(
        const Project& project,
        const CCFContext& context,

        const std::string& dip,             // Depositional dip angle (degree)
        const std::string& azim,            // Depositional strike direction (degree)

        const std::string& depth,           // Z position of the well marker (m)

        const std::string& facies,          // Depositional sedimentary facies (id)

        bool write_bezier,                  // Creates all bezier lines files
        bool write_profile,                 // Creates all depositional profile files

        const std::string bezier_folder,    // Folder to store all bezier lines files
        const std::string profile_folder,   // Folder to store all depositional profile files

        const std::string& dep_facies_file, // All information about depositional facies
        const std::string& dep_profile_file,// All information about depositional profile
        bool normalize                      // Normalize cost by characteristic volume
    ) :
        CCFPart(context),

        dip_(context, project.well_list(), dip),
        azim_(context, project.well_list(), azim),

        depth_(context, project.well_list(), depth),

        facies_(context, project.well_list(), facies),

        write_bezier_(write_bezier),
        write_profile_(write_profile),

        bezier_folder_(bezier_folder),
        profile_folder_(profile_folder),

        dep_facies_file_(dep_facies_file),
        dep_profile_file_(dep_profile_file),
        normalize_(normalize)
    {
        well_1_ = context.size1() - 2; // Last well of the correlation graph 1
        well_2_ = context.size1() - 1; // Last well of the correlation graph 1
        well_3_ = context.size1();     // First well of the correlation graph 2

        x_well_1_ = project.well_list().well(well_1_)->x();   // X position of well markers in Well 1
        y_well_1_ = project.well_list().well(well_1_)->y();   // Y position of well markers in Well 1
        h_well_1_ = project.well_list().well(well_1_)->len(); // Length of the well 1

        x_well_2_ = project.well_list().well(well_2_)->x();   // X position of well markers in Well 2
        y_well_2_ = project.well_list().well(well_2_)->y();   // Y position of well markers in Well 2
        h_well_2_ = project.well_list().well(well_2_)->len(); // Length of the well 2

        x_well_3_ = project.well_list().well(well_3_)->x();   // X position of well markers in Well 3
        y_well_3_ = project.well_list().well(well_3_)->y();   // Y position of well markers in Well 3
        h_well_3_ = project.well_list().well(well_3_)->len(); // Length of the well 3

        double surf_well = dist(x_well_1_ - x_well_2_, y_well_1_ - y_well_2_);

        norm_volume_ = (h_well_1_ + h_well_2_ + h_well_3_) * surf_well / 3.00;
        
        read_dep_profile_file();

        read_dep_facies_file();

        if (well_1_ == 0)
            write_dep_profile_file(project);
    }

	bool full_cost(CostValue& cost) override
    {
        CostValue prev_cost = context.parent_cost1();

        B3D::Profile profile( source_, facies_z_map_ );

        B3D::CornerPoint corner_point_1 = create_corner_point(well_1_, x_well_1_, y_well_1_);
        B3D::CornerPoint corner_point_2 = create_corner_point(well_2_, x_well_2_, y_well_2_);
        B3D::CornerPoint corner_point_3 = create_corner_point(well_3_, x_well_3_, y_well_3_);

        B3D::Marker well_marker_1 = { profile, corner_point_1 };
        B3D::Marker well_marker_2 = { profile, corner_point_2 };
        B3D::Marker well_marker_3 = { profile, corner_point_3 };

        std::string name_marker_1 = std::to_string(well_1_) + "-" + std::to_string(context.dest(well_1_));
        std::string name_marker_2 = std::to_string(well_2_) + "-" + std::to_string(context.dest(well_2_));
        std::string name_marker_3 = std::to_string(well_3_) + "-" + std::to_string(context.dest(well_3_));

        B3D::Patch bezier_patch ( corner_point_1, corner_point_2, corner_point_3 );

        std::string beziez_file_name = bezier_folder_ + "/bezier_" + name_marker_1 + "_" + name_marker_2 + "_" + name_marker_3 + ".bez";
        std::ifstream bezier_file(beziez_file_name);

        if (write_bezier_)
            bezier_patch.generate_point_set(beziez_file_name);

        B3D::Profile profile_1 = well_marker_1.profile();
        B3D::Profile profile_2 = well_marker_2.profile();
        B3D::Profile profile_3 = well_marker_3.profile();

        std::string profile_file_1_name = profile_folder_ + "/profile_" + name_marker_1 + ".dep";
        std::ifstream profile_file_1(profile_file_1_name);

        std::string profile_file_2_name = profile_folder_ + "/profile_" + name_marker_2 + ".dep";
        std::ifstream profile_file_2(profile_file_2_name);

        std::string profile_file_3_name = profile_folder_ + "/profile_" + name_marker_3 + ".dep";
        std::ifstream profile_file_3(profile_file_3_name);

        if (write_profile_) {
            Range x_range = { std::min(x_well_1_,x_well_2_), std::max(x_well_1_,x_well_2_), 100 };
            Range y_range = { std::min(y_well_1_,y_well_2_), std::max(y_well_1_,y_well_2_), 100 };

            profile_1.generate_point_set(x_range, y_range, profile_file_1_name);
            profile_2.generate_point_set(x_range, y_range, profile_file_2_name);
            profile_3.generate_point_set(x_range, y_range, profile_file_3_name);
        }

        CostValue cost_1 = profile_1.compute_volume(bezier_patch);
        CostValue cost_2 = profile_2.compute_volume(bezier_patch);
        CostValue cost_3 = profile_3.compute_volume(bezier_patch);

        if (normalize_ && norm_volume_ > 0.0) {
            cost_1 /= norm_volume_;
            cost_2 /= norm_volume_;
            cost_3 /= norm_volume_;
        }

        cost = prev_cost + (cost_1 + cost_2 + cost_3) / 3.00;

        return true;
    }

    bool dest_only() const override { return false; }

    void read_dep_facies_file()
    {
        std::ifstream cin_file(dep_facies_file_, std::ios::in);  // on ouvre le fichier en lecture
        
        if (cin_file) {
        
            std::string file_line;
        
            facies_map_.clear();
            facies_z_map_.clear();

            double facies_id;
        
            double facies_x_ext;
            double facies_y_ext;
            double facies_z_ext;
        
            double facies_z_top;
            double facies_z_bot;
        
            Range facies_zrange;
            FaciesExt facies_ext;

            while (cin_file) {
                cin_file >> facies_id;

                if (cin_file.eof()) break;
                
                cin_file >> facies_x_ext >> facies_y_ext >> facies_z_ext >> facies_z_top >> facies_z_bot;

                facies_zrange = { facies_z_bot , facies_z_top };
                facies_ext = { facies_x_ext , facies_y_ext , facies_z_ext };

                facies_map_[facies_id] = facies_ext;
                facies_z_map_[facies_id] = facies_zrange;
            }

            cin_file.close();
        }
        
        else
            std::cerr << "Impossible to open the file!" << std::endl;
    }

    void read_dep_profile_file()
    {
        std::ifstream cin_file(dep_profile_file_, std::ios::in);  // on ouvre le fichier en lecture

        if (cin_file) {

            std::string file_line;

            while (cin_file) {

                if (cin_file.eof()) break;

                cin_file >> dX_src_ >> dY_src_ >> dZ_src_ >> sed_dir_;

            }

            cin_file.close();


            slope_ = { dX_src_,dY_src_,dZ_src_ };

            source_ = B3D::Source({ 0,0,0 }, slope_, sed_dir_);
        }

        else
            std::cerr << "Impossible to open the file!" << std::endl;
    }

    void write_dep_profile_file(const Project& project)
    {
        B3D::Float x_max = -1e38; // x max value initialization
        B3D::Float x_min = +1e38; // x min value initialization

        B3D::Float y_max = -1e38; // y max value initialization
        B3D::Float y_min = +1e38; // y min value initialization

        B3D::Float z_max = -1e38; // z max value initialization
        B3D::Float z_min = +1e38; // z min value initialization

        // Find extrem values of x and y in the entire data set.
        for (unsigned id_well = 0; id_well < project.well_list().nbr_wells(); ++id_well) {

            const Well* cur_well = project.well_list().well(id_well);

            B3D::Float x_pos = cur_well->x(); // x position
            B3D::Float y_pos = cur_well->y(); // y position
            B3D::Float z_pos = cur_well->z(); // z position

            if (x_max < x_pos)
                x_max = x_pos; // x max value updating

            if (x_min > x_pos)
                x_min = x_pos; // x min value updating

            if (y_max < y_pos)
                y_max = y_pos; // y max value updating

            if (y_min > y_pos)
                y_min = y_pos; // y min value updating

            if (z_max < z_pos)
                z_max = z_pos; // z max value updating

            if (z_min > z_pos)
                z_min = z_pos; // z min value updating
        }

        std::cout << "(" << x_min << "," << x_max << ") (" << y_min << "," << y_max << ") (" << z_min << "," << z_max << ")" << std::endl;

        B3D::Float len_x = x_max - x_min;
        B3D::Float len_y = y_max - y_min;

        if (len_x > len_y) {
            x_min -= 0.1 * len_x;
            x_max += 0.1 * len_x;

            y_min -= 0.1 * len_x + 0.5 * (len_x - len_y);
            y_max += 0.1 * len_x + 0.5 * (len_x - len_y);
        }

        else if (len_x < len_y) {
            x_min -= 0.1 * len_y + 0.5 * (len_y - len_x);
            x_max += 0.1 * len_y + 0.5 * (len_y - len_x);

            y_min -= 0.1 * len_y;
            y_max += 0.1 * len_y;
        }

        else {
            x_min -= 0.1 * len_x;
            x_max += 0.1 * len_x;

            y_min -= 0.1 * len_y;
            y_max += 0.1 * len_y;
        }

        B3D::Range x_range = { x_min, x_max, 100 }; // x range
        B3D::Range y_range = { y_min, y_max, 100 }; // y range

        B3D::Float x_source = (x_min + x_max) / 2.00;
        B3D::Float y_source = (y_min + y_max) / 2.00;
        B3D::Float z_source = (z_min + z_max) / 2.00;

        std::cout << "Source (" << x_source << "," << y_source << "," << z_source << ")" << std::endl;

        B3D::Coord source_coord = { x_source, y_source, z_source };

        B3D::Source source(source_coord, slope_, sed_dir_);

        B3D::Profile profile(source, facies_z_map_);

        profile.generate_point_set(x_range, y_range, profile_folder_ + "/profile.dep");
    }

    B3D::CornerPoint create_corner_point(const WellId& well_id, double x_coord, double y_coord)
    {
        CostValue depth = depth_.dest_data(well_id);

        CostValue dip = dip_.dest_data(well_id);

        CostValue azimuth = (azim_.dest_data(well_id) - 90.00 < 0.00 ? azim_.dest_data(well_id) + 270.00 : azim_.dest_data(well_id) - 90.00);

        CostValue facies = facies_.dest_data(well_id);

        B3D::Coord coord = { x_coord, y_coord, depth };

        B3D::Dipmeter dipmeter = { azimuth, dip };

        B3D::FaciesExt extension = facies_map_[facies];

        B3D::CornerPoint corner_point = { coord, dipmeter, (unsigned)facies, extension };

        return corner_point;
    }

    WellId well_1_;
    WellId well_2_;
    WellId well_3_;

    double x_well_1_;
    double x_well_2_;
    double x_well_3_;

    double y_well_1_;
    double y_well_2_;
    double y_well_3_;

    double h_well_1_;
    double h_well_2_;
    double h_well_3_;

    double norm_volume_;
    bool normalize_;

    Slope slope_;
    Source source_;

    double dX_src_;
    double dY_src_;
    double dZ_src_;

    double sed_dir_;

    CostHelperData dip_;
    CostHelperData azim_;

    CostHelperData depth_;

    CostHelperData facies_;

    bool write_bezier_;
    bool write_profile_;

    FaciesMap facies_map_;
    FaciesZMap facies_z_map_;

    std::string bezier_folder_;
    std::string profile_folder_;

    std::string dep_facies_file_;
    std::string dep_profile_file_;
};


class _CCFPartB3DPatchFactory : public CCFGlobalPartFactory {

public:

protected:

    OptionData option_dip{ "b3d-patch-dip","","It corresponds to the dip angle (deg).","50CCF.B3DPatch" };
    OptionData option_azim{ "b3d-patch-azimuth","","It corresponds to the strike orientation (deg).","50CCF.B3DPatch" };
    OptionData option_depth{ "b3d-patch-depth","","It corresponds to the z-axis coordinate.","50CCF.B3DPatch" };
    OptionData option_facies{ "b3d-patch-facies","","It corresponds to the paleo-depth of the deposit.","50CCF.B3DPatch" };

    OptionBool option_write_bezier{ "b3d-patch-write-bezier",false,"If true, it generates point sets of all Bezier curves interpolations.","50CCF.B3DPatch" };
    OptionBool option_write_profile{ "b3d-patch-write-profile",false,"If true, it generates point sets of all translated depositional profiles.","50CCF.B3DPatch" };
    OptionBool option_normalize{ "b3d-patch-normalize",true,"Normalize B3D cost by characteristic volume (h1+h2+h3)*S/3.","50CCF.B3DPatch" };
    
    OptionString option_bezier_folder{ "b3d-patch-bezier-folder","","It corresponds to the file where all information about facies are stored (z range, lateral & vertical extension).","50CCF.B3DPatch" };
    OptionString option_profile_folder{ "b3d-patch-profile-folder","","It corresponds to the file where all information about facies are stored (z range, lateral & vertical extension).","50CCF.B3DPatch" };

    OptionString option_dep_facies_file{ "b3d-patch-dep-facies-file","","It corresponds to the file where all information about depositional facies are stored (z range, lateral & vertical extension).","50CCF.B3DPatch" };
    OptionString option_dep_profile_file{ "b3d-patch-dep-profile-file","","It corresponds to the file where all information about depositional profile are stored (lateral and vertical extension & sediment direction).","50CCF.B3DPatch" };

    virtual bool test(const Project& project) const override
    {
        return (
            option_dip.project_check(project,true) &&
            option_azim.project_check(project, true) &&
            option_depth.project_check(project, true) &&
            option_facies.project_check(project, true)
        );
    }

    virtual CCFPart* create(const Project& project, const CCFContext& context) const override
    {
        if ( !option_dip || !option_azim || !option_depth || !option_facies )
            return nullptr;

        return new _CCFPartB3DPatch(
            project,
            context,
            option_dip(),
            option_azim(),
            option_depth(),
            option_facies(),
            option_write_bezier(),
            option_write_profile(),
            option_bezier_folder(),
            option_profile_folder(),
            option_dep_facies_file(),
            option_dep_profile_file(),
            option_normalize()
        );
    }
};

static _CCFPartB3DPatchFactory _ccf_part_b3d_patch_factory;

}

} //namesapce WeCo