/*
 * Association Scientifique pour la Geologie et ses Applications (ASGA)
 *
 * Copyright (c) 2019 ASGA. All Rights Reserved.
 *
 * This program is a Trade Secret of the ASGA and it is not to be:
 *  - reproduced, published, or disclosed to other,
 *  - distributed or displayed,
 *  - used for purposes or on Sites other than described in the GOCAD
 *    Advancement Agreement, without the prior written authorization
 *    of the ASGA.
 *
 * Licensee agrees to attach or embed this Notice on all copies of the program,
 * including partial copies or modified versions thereof.
 * 
 * Author: Paul Baville - paul.baville@univ-lorraine.fr
 */

#include <weco/project.h>

#include <cmath>
#include <map>
#include <sstream>

namespace WeCo {
namespace  {

// §11.2.2 Parse facies group string "0,1;2,3;4,5" into a facies→group lookup
static std::map<int,int> parse_facies_groups(const std::string& groups_str) {
	std::map<int,int> lookup;
	if(groups_str.empty()) return lookup;
	std::istringstream ss(groups_str);
	std::string group_token;
	int group_id = 0;
	while(std::getline(ss, group_token, ';')) {
		std::istringstream gs(group_token);
		std::string facies_token;
		while(std::getline(gs, facies_token, ',')) {
			int fid = std::stoi(facies_token);
			lookup[fid] = group_id;
		}
		group_id++;
	}
	return lookup;
}

// ========================================================================= //
// Sedimentary Facies vs Well Distality Cost Function                        //
// ========================================================================= //

class _CCFPartDistal : public CCFPart {

public:

	_CCFPartDistal(
		const Project& project,
		const CCFContext& context,
		const std::string& facies,
		const std::string& distal,
		double scaling,
		const std::string& facies_groups_str = ""
	) :
		CCFPart(context),
        facies_(context, project.well_list(), facies),
		distal_(context, project.well_list(), distal),
        scaling_(scaling),
        facies_group_lookup_(parse_facies_groups(facies_groups_str))
    {
        w1_ = context.size1() - 1; //  Last well of the correlation graph 1
        w2_ = context.size1();     // First well of the correlation graph 2

        double f_max = -1e38; // Facies max value initialization
        double f_min = +1e38; // Facies min value initialization

        double d_max = -1e38; // Distal max value initialization
        double d_min = +1e38; // Distal min value initialization

        // Find extreme values of facies and distality in the entire data set.
        for (unsigned well_id = 0; well_id < project.well_list().nbr_wells(); well_id ++) {

            const Well* cur_well = project.well_list().well(well_id);

            const RegionList& facies_list = cur_well->get_region_list(facies); // Facies list
            const RegionList& distal_list = cur_well->get_region_list(distal); // Distal list

            for (unsigned facies_id = 0; facies_id < facies_list.regions().size(); facies_id ++) {

                if (f_max < facies_list.regions()[facies_id].id)
                    f_max = facies_list.regions()[facies_id].id; // Facies max value updating

                if (f_min > facies_list.regions()[facies_id].id)
                    f_min = facies_list.regions()[facies_id].id; // Facies min value updating
            }

            for (unsigned distal_id = 0; distal_id < distal_list.regions().size(); distal_id ++) {

                if (d_max < distal_list.regions()[distal_id].id)
                    d_max = distal_list.regions()[distal_id].id; // Distal max value updating

                if (d_min > distal_list.regions()[distal_id].id)
                    d_min = distal_list.regions()[distal_id].id; // Distal min value updating
            }
        }

        f0_ = f_max - f_min; // Facies normalization value
        d0_ = d_max - d_min; // Distal normalization value
        
        // std::cout << "Facies maximum variation = " << f0_ << std::endl;
        // std::cout << "Distal maximum variation = " << d0_ << std::endl;
        // std::cout << std::endl;
    }

    WellId w1_;
    WellId w2_;

    double f0_;
    double d0_;

    double scaling_;

    CostHelperRegion facies_;
    CostHelperRegion distal_;

    // §11.2.2 Facies group lookup table
    std::map<int,int> facies_group_lookup_;

    // §11.2.2 Map facies ID to group ID (identity if no groups defined)
    double facies_to_group(double f) const {
        if(facies_group_lookup_.empty()) return f;
        auto it = facies_group_lookup_.find(static_cast<int>(f));
        return (it != facies_group_lookup_.end()) ? static_cast<double>(it->second) : f;
    }

    // Test the nature of the lateral facies transition (no gap / gap in well 1 / gap in well 2)
    bool is_w1_gap() { return (context.same(w1_) && !context.same(w2_)); }  // Gap in Well 1
    bool is_w2_gap() { return (!context.same(w1_) && context.same(w2_)); }  // Gap in Well 2
    bool is_no_gap() { return (!context.same(w1_) && !context.same(w2_)); } // There is no gap

    // TODO: Test the nature of the vertical facies transition (aggradation / regression / transgression)
    bool is_a_sequence(WellId well) { return true; }
    bool is_r_sequence(WellId well) { return true; }
    bool is_t_sequence(WellId well) { return true; }

    // Test if the transition is possible
    bool is_w1_gap_possible(double f2, double d1, double d2) { return true; }

    bool is_w2_gap_possible(double f1, double d1, double d2) { return true; }

    bool is_no_gap_possible(double f1, double f2, double d1, double d2)
    {
        if ((f1 < f2) && (d1 > d2)) { return false; }

        if ((f1 > f2) && (d1 < d2)) { return false; }

        return true;
    }

    // Upper well-marker association cost c
    CostValue top_correlation_cost() { return 0.00; } // null in this cost function

    // Lower well-marker association cost c
    CostValue bot_correlation_cost() { return 0.00; } // null in this cost function

    // Well-marker association transition cost t
    CostValue mid_correlation_cost(double f1, double f2, double d1, double d2)
    {   
        if (is_w1_gap()) return 1.0;

        if (is_w2_gap()) return 1.0;

        // §11.2.2 Apply facies group mapping if defined
        double fg1 = facies_to_group(f1);
        double fg2 = facies_to_group(f2);

        // Normalized facies and distal parameters
        double facies = (f0_ != 0.00 ? std::fabs(fg1 - fg2) / f0_ : 0.00);
        double distal = (d0_ != 0.00 ? std::fabs(d1 - d2) / d0_ : 0.00);

        // std::cout << "f1 = " << f1 << ", f2 = " << f2 << ", f0 = " << f0_ << " --> facies = " << facies << std::endl;
        // std::cout << "d1 = " << d1 << ", d2 = " << d2 << ", d0 = " << d0_ << " --> distal = " << distal << std::endl;

        // the scaling by 0.9 ensures that the conformal (no gap) transition is always more
        // likely than the gap.
        assert(is_no_gap());
        return 0.9 * (scaling_ * distal - facies) * (scaling_ * distal - facies);

    }

    // Compute correlation cost
    bool full_cost(CostValue& cost) override
    {
        // Well marker initialization
        // std::cout << "from (" << context.src(w1_) << "," << context.src(w2_) << ")";
        // std::cout << " to (" << context.dest(w1_) << "," << context.dest(w2_) << ")";

        // Compute correlation cost as used in Baville et al., Marine and Petroleum Geology (2022)
        // return full_cost_2022a(cost);
        return full_cost_2022b(cost);
    }

    // Compute correlation cost as used in Baville et al., MPG (2022) - Facies as well data
    bool full_cost_2022a(CostValue& cost)
    {
        // Facies interpretations in wells 1 & 2
        double f1 = facies_.dest_region(w1_);
        double f2 = facies_.dest_region(w2_);

        // Distality interpretations in wells 1 & 2
        double d1 = distal_.dest_region(w1_);
        double d2 = distal_.dest_region(w2_);

        if (is_no_gap_possible(f1, f2, d1, d2)) {

            // Addition of the cost aggregated at well markers during the previous correlation iteration
            cost += context.parent_cost1() + context.parent_cost2();

            // Normalized facies and distal parameters
            double facies = (f0_ != 0.00 ? std::fabs(f1 - f2) / f0_ : 0.00);
            double distal = (d0_ != 0.00 ? std::fabs(d1 - d2) / d0_ : 0.00);

            // Transition between these two correlation lines (0 < cost < 1)
            cost += 0.9 * std::pow(scaling_ * distal - facies, 2);

            if ((context.same(w1_) || context.same(w2_))) { cost += 0.1; };

            // std::cout << " --> cost = " << cost << std::endl;
            // std::cout << std::endl;

            return true;
        }

        // std::cout << " --> Impossible correlation" << cost << std::endl;
        // std::cout << std::endl;

        return false;
    }

    // Compute correlation cost as used in Baville et al., MPG (2022) - Facies as well region
    bool full_cost_2022b(CostValue& cost)
    {
        // Facies interpretations in wells 1 & 2
        double f1 = facies_.src_region(w1_);
        double f2 = facies_.src_region(w2_);

        // Distality interpretations in wells 1 & 2
        double d1 = distal_.src_region(w1_);
        double d2 = distal_.src_region(w2_);

        // Test is the transition is possible
        // Gap in well 1
        if (is_w1_gap() && !is_w1_gap_possible(f2, d1, d2)) { return false; }

        // Gap in well 2
        if (is_w2_gap() && !is_w2_gap_possible(f1, d1, d2)) { return false; }

        // There is no gap
        if (is_no_gap() && !is_no_gap_possible(f1, f2, d1, d2)) { return false; }
  
        // Addition of the cost aggregated at well markers during the previous correlation iteration
        cost += context.parent_cost1() + context.parent_cost2();

        // Upper and lower association costs c
        CostValue top_cost = top_correlation_cost();
        CostValue bot_cost = bot_correlation_cost();

        // Transition cost t
        CostValue mid_cost = mid_correlation_cost(f1, f2, d1, d2);

        // Correlation cost. Divide by two to avoid giving more weight to interface costs in the cumulated DTW cost
        cost += (top_cost / 2) + mid_cost + (bot_cost / 2);

        // std::cout << "  --> cost = " << cost << std::endl;

        return true;
    }

    bool dest_only() const override { return false; }
};

class _CCFPartDistalFactory : public CCFGlobalPartFactory {

public:

protected:

    OptionRegion option_facies{"dist-facies","","Corresponds to the paleo-depth of the deposit. Facies are ordered from the deepest (1) to shallowest (++)","50CCF.Distal"};
    OptionRegion option_distal{"dist-distal","","Corresponds to the paleo-distality of the well. Distalities are ordered from the most distal (1) to the most proximal (++)","50CCF.Distal"};

    OptionFloat option_scaling{"dist-scaling",1.,"Corresponds to the scaling coefficient representing how the lateral size of the depositional system is deemed to scale with the inter-well distance (-1 < scaling < 1)","50CCF.Distal"};

    // §11.2.2 Facies group definitions (semicolon-separated groups of comma-separated facies IDs)
    OptionString option_facies_groups{"dist-facies-groups","","Facies group mapping, e.g. '0,1;2,3;4,5' (same-group facies have zero Δf)","50CCF.Distal"};

    virtual bool test(const Project& project) const override
    {
        return option_facies.project_check(project, true) && option_distal.project_check(project, true);
    }

    virtual  CCFPart* create(const Project& project, const CCFContext& context)  const override
    {
        if (!option_distal || !option_facies) return nullptr;

        return new _CCFPartDistal(project, context, option_facies(), option_distal(), option_scaling(), option_facies_groups());
    }
};

static _CCFPartDistalFactory _ccf_part_distal_factory;

// ========================================================================= //
// Sedimentary Facies vs Multi Well Distality Cost Function                  //
// ========================================================================= //

class _CCFPartMultiDistal : public CCFPart {

public:

    _CCFPartMultiDistal(
        const Project& project,
        const CCFContext& context,
        const std::string& facies,
        const std::string& distal_file,
        double scaling
    ) :
        CCFPart(context),

        facies_(context, project.well_list(), facies),

        distal_file_(distal_file),

        scaling_(scaling)
    {
        read_distal_file();

        w1_ = context.size1() - 1; //  Last well of the correlation graph 1
        w2_ = context.size1();     // First well of the correlation graph 2

        double f_max = -1e38; // Facies max value initialization
        double f_min = +1e38; // Facies min value initialization

        // Find extreme values of facies and distality in the entire data set.
        for (unsigned well_id = 0; well_id < project.well_list().nbr_wells(); well_id ++) {

            const Well* cur_well = project.well_list().well(well_id);

            const RegionList& facies_list = cur_well->get_region_list(facies); // Facies log

            for (unsigned facies_id = 0; facies_id < facies_list.regions().size(); facies_id ++) {

                if (f_max < facies_list.regions()[facies_id].id)
                    f_max = facies_list.regions()[facies_id].id; // Facies max value updating

                if (f_min > facies_list.regions()[facies_id].id)
                    f_min = facies_list.regions()[facies_id].id; // Facies min value updating
            }
        }

        f0_ = f_max - f_min; // Facies normalization value
    }

    WellId w1_;
    WellId w2_;

    double f0_;
    double d0_;

    double scaling_;

    unsigned nb_sed_dir_;

    std::string distal_file_;

    CostHelperRegion facies_;

    // std::vector< double > distal_;

    std::vector< std::vector< double > > list_distal_;

    // Test the nature of the lateral facies transition (no gap / gap in well 1 / gap in well 2)
    bool is_w1_gap() { return (context.same(w1_) && !context.same(w2_)); }  // Gap in Well 1
    bool is_w2_gap() { return (!context.same(w1_) && context.same(w2_)); }  // Gap in Well 2
    bool is_no_gap() { return (!context.same(w1_) && !context.same(w2_)); } // There is no gap

    // Test the nature of the vertical facies transition (aggradation / regression / transgression)
    bool is_a_sequence(WellId well) { return true; }
    bool is_r_sequence(WellId well) { return true; }
    bool is_t_sequence(WellId well) { return true; }

    // Test if the transition is possible
    bool is_w1_gap_possible(double f2, double d1, double d2) { return true; }

    bool is_w2_gap_possible(double f1, double d1, double d2) { return true; }

    bool is_no_gap_possible(double f1, double f2, double d1, double d2)
    {
        if ((f1 < f2) && (d1 > d2)) { return false; }

        if ((f1 > f2) && (d1 < d2)) { return false; }

        return true;
    }

    // Upper well-marker association cost c
    CostValue top_correlation_cost() { return 0.00; } // null in this cost function

    // Lower well-marker association cost c
    CostValue bot_correlation_cost() { return 0.00; } // null in this cost function

    // Well-marker association transition cost t
    CostValue mid_correlation_cost(double f1, double f2, double d1, double d2)
    {   
        CostValue cost = 1.00;

        // Normalized facies and distal parameters
        double facies = (f0_ != 0.00 ? std::fabs(f1 - f2) / f0_ : 0.00);
        double distal = (d0_ != 0.00 ? std::fabs(d1 - d2) / d0_ : 0.00);

        // std::cout << "f1 = " << f1 << ", f2 = " << f2 << ", f0 = " << f0_ << " --> facies = " << facies << std::endl;
        // std::cout << "d1 = " << d1 << ", d2 = " << d2 << ", d0 = " << d0_ << " --> distal = " << distal << std::endl;

        if (is_no_gap()) cost = 0.9 * std::pow(scaling_ * distal - facies, 2);

        if (is_w1_gap()) cost = 1.0;

        if (is_w2_gap()) cost = 1.0;

        return cost;
    }

    bool full_cost(CostValue& cost) override
    {
        // Facies interpretations in wells 1 & 2
        double f1 = facies_.src_region(w1_);
        double f2 = facies_.src_region(w2_);
        
        // Addition of the cost aggregated at well markers during the previous correlation iteration
        cost += context.parent_cost1() + context.parent_cost2();

        // Correlation cost
        cost += test_sed_dir(f1, f2);

        // std::cout << "  --> cost = " << cost << std::endl;

        return true;
    }

    CostValue test_sed_dir(double f1, double f2)
    {
        double best_cost = +1e38;
        double temp_cost = +1e38;

        double best_d1 = list_distal_[0][0];
        double best_d2 = list_distal_[0][1];

        // Multiple sediment direction test
        for (unsigned sed_dir = 0; sed_dir < nb_sed_dir_; sed_dir ++) {

            double temp_d1 = list_distal_[sed_dir][0];
            double temp_d2 = list_distal_[sed_dir][1];

            // Test is the transition is possible
            // Gap in well 1
            if (is_w1_gap() && !is_w1_gap_possible(f2, temp_d1, temp_d2)) { temp_cost = +1e38; }

            // Gap in well 2
            else if (is_w2_gap() && !is_w2_gap_possible(f1, temp_d1, temp_d2)) { temp_cost = +1e38; }

            // There is no gap
            else if (is_no_gap() && !is_no_gap_possible(f1, f2, temp_d1, temp_d2)) { temp_cost = +1e38; }
    
            // Possible marker association.
            else {

                // Upper and lower association costs c
                CostValue top_cost = top_correlation_cost();
                CostValue bot_cost = bot_correlation_cost();

                // Transition cost t
                CostValue mid_cost = mid_correlation_cost(f1, f2, temp_d1, temp_d2);
                
                // Correlation cost
                temp_cost += (top_cost / 2) + mid_cost + (bot_cost / 2);
            }

            best_cost = (temp_cost <= best_cost ? temp_cost : best_cost);

            best_d1 = (temp_cost <= best_cost ? temp_d1 : best_d1);
            best_d2 = (temp_cost <= best_cost ? temp_d2 : best_d2);
        }

        // distal_ = { best_d1, best_d2 };

        return best_cost;
    }

    void read_distal_file()
    {
        std::ifstream cin_file(distal_file_, std::ios::in);

        if (cin_file) {

            std::string file_line;

            list_distal_.clear();

            d0_ = 0;

            double d1;
            double d2;

            cin_file >> nb_sed_dir_;

            while (cin_file) {

                if (cin_file.eof()) break;

                cin_file >> d1 >> d2;

                d0_ = (fabs(d1 - d2) >= d0_ ? fabs(d1 - d2) : d0_);

                list_distal_.push_back({ d1, d2 });
            }

            cin_file.close();

            assert(list_distal_.size() == nb_sed_dir_);
        }
    }

    
    bool dest_only() const override { return false; }
};

class _CCFPartMultiDistalFactory : public CCFGlobalPartFactory {

public:

protected:

    OptionRegion option_multi_facies{ "multi-dist-facies","","The facies log","50CCF.MultiDistal" };

    OptionString option_multi_distal{ "multi-dist-distal","","File containing all the possible paleo-distalities of\
     wells: \n Line 1: number N of distality scenarios. \n \
     Lines 2 to N+1: space-separated distality indices for each well (same well order than in the well list)", "50CCF.MultiDistal" };

    OptionFloat option_multi_scaling{ "multi-dist-scaling",1.,"It corresponds to the scaling coefficient representing how the lateral size of the depositional system is deemed to scale with the inter-well distance.","50CCF.MultiDistal" };

    virtual bool test(const Project& project) const override
    {
        return option_multi_facies.project_check(project, true);
    }

    virtual  CCFPart* create(const Project& project, const CCFContext& context)  const override
    {
        if (!option_multi_distal) return nullptr;

        return new _CCFPartMultiDistal(project, context, option_multi_facies(), option_multi_distal(), option_multi_scaling());
    }
};

static _CCFPartMultiDistalFactory _ccf_part_multi_distal_factory;

}
} //Namespace WeCo