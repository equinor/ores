/*
 * Association Scientifique pour la Geologie et ses Applications (ASGA)
 *
 * Copyright � 2018 ASGA. All Rights Reserved.
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
 * Author: Paul Baville - paul.baville@kit.edu
 */

#include <weco/project.h>

#include <cmath>

namespace WeCo {
namespace  {

// ========================================================================= //
// Sedimentary Facies vs Well Distality Cost Function                        //
// ========================================================================= //

class _CCFPartVarRegion : public CCFPart {

public:

	_CCFPartVarRegion(
		const Project& project,
		const CCFContext& context,
		const std::string& region
	) :
		CCFPart(context),
        region_(context, project.well_list(), region)
    {
        std::cout << "Var-Region cost-function" << std::endl;

        nb_wells_ = context.size();

        std::cout << "Nb wells : " << nb_wells_ << std::endl;

        double r_max = -1e16; // Region max value initialization
        double r_min = +1e16; // Region min value initialization

        // Find extreme values of region in the entire data set.
        for (unsigned well_id = 0; well_id < nb_wells_; well_id ++) {

            const Well* cur_well = project.well_list().well(well_id);

            const RegionList& region_list = cur_well->get_region_list(region); // Facies list

            for (unsigned region_id = 0; region_id < region_list.regions().size(); region_id ++) {

                if (r_max < region_list.regions()[region_id].id)
                    r_max = region_list.regions()[region_id].id; // Region max value updating

                if (r_min > region_list.regions()[region_id].id)
                    r_min = region_list.regions()[region_id].id; // Region min value updating
            }
        }

        r0_ = r_max - r_min; // Region normalization value
    }

    double r0_;

    unsigned nb_wells_;

    CostHelperRegion region_;

    // Return the number of gaps along the correlation line
    unsigned nb_gaps()
    {
        unsigned nb_gaps = 0;

        for (WellId well_id = 0; well_id < nb_wells_; well_id ++) {
            if (context.same(well_id))
                nb_gaps += 1;
        }

        return nb_gaps;
    }

    bool no_gaps() { return (nb_gaps() == 0); }                 // There is no gap

    bool few_gaps() { return (!no_gaps() && !only_gaps()); }    // There are gaps

    bool only_gaps() { return (nb_gaps() == nb_wells_ - 1); }   // There are only gaps but one

    // Upper well-marker association cost c
    CostValue top_correlation_cost() { return 0.00; } // null in this cost function

    // Lower well-marker association cost c
    CostValue bot_correlation_cost() { return 0.00; } // null in this cost function

    // Well-marker association transition cost t
    CostValue mid_correlation_cost()
    {
        // If there are no gaps, we compute the variance on the region
        // between all markers
        if (no_gaps()) {

            double r_avg = 0.00;
            double r_var = 0.00;
            
            for (unsigned well_id = 0; well_id < nb_wells_; well_id ++)
                r_avg += region_.src_region(well_id);
            
            r_avg = r_avg / (nb_wells_ + 1.);

            for (unsigned well_id = 0; well_id < nb_wells_; well_id ++)
                r_var += std::pow(region_.src_region(well_id) - r_avg, 2);
            
            r_var = r_var / (nb_wells_ + 1.);

            std::cout << " No gap ";

            return (r_var / r0_) / 2.00;
        }

        // If there are few gaps, we compute the variance on the region
        // between no-gap wells
        if (few_gaps()) {

            double r_avg = 0.00;
            double r_var = 0.00;
            
            for (unsigned well_id = 0; well_id < nb_wells_; well_id ++) {
                if (!context.same(well_id)) {
                    r_avg += region_.src_region(well_id);
                }
            }
            
            r_avg = r_avg / nb_gaps();

            for (unsigned well_id = 0; well_id < nb_wells_; well_id ++) {
                if (!context.same(well_id)) {
                    r_var += std::pow(region_.src_region(well_id) - r_avg, 2);
                }
            }
            
            double r_gap = nb_gaps() / nb_wells_;

            r_var = r_var / nb_gaps();

            std::cout << " Few gaps ";

            return ((r_var / r0_) + r_gap) / 2.00;
        }

        std::cout << " Only gaps ";

        // If there are only gaps but one, we don't compute the variance
        // and we return the proportion of gaps.
        return (1 + (nb_gaps() / nb_wells_)) / 2.00;
    }

    // Compute correlation cost
    bool full_cost(CostValue& cost) override
    {  
        // Addition of the cost aggregated at well markers during the previous correlation iteration
        // cost += context.parent_cost1() + context.parent_cost2();

        // Upper and lower association costs c
        CostValue top_cost = top_correlation_cost();
        CostValue bot_cost = bot_correlation_cost();

        // Transition cost t
        CostValue mid_cost = mid_correlation_cost();

        // Correlation cost
        cost += 0.05 + 0.95 * ((top_cost / 2.) + mid_cost + (bot_cost / 2.));
        
        std::cout << " --> cost = " << cost << std::endl;

        return true;        
    }

    bool dest_only() const override { return false; }
};

class _CCFPartVarRegionFactory : public CCFGlobalPartFactory {

public:

protected:

    OptionRegion option_region{"var-region","","It corresponds to the value of the region","50CCF.VarRegion"};

    virtual bool test(const Project& project) const override
    {
        return option_region.project_check(project,true);
    }

    virtual  CCFPart* create(const Project& project, const CCFContext& context)  const override
    {
        if (!option_region)
            return nullptr;

        return new _CCFPartVarRegion(project, context, option_region());
    }
};

static _CCFPartVarRegionFactory _ccf_part_var_region_factory;

}

} //Namespace WeCo