/*
 * ccf_thickness.cpp — Thickness ratio cost function (§4.3, Baville §6.3.2)
 *
 * Penalises geologically implausible thickness ratios between wells.
 * C++ port of weco.cost_functions.ThicknessRatioCost.
 *
 * cost = weight × Σ ((h_a/h_b - expected_ratio) / sigma)² / n_pairs
 */

#include <weco/project.h>
#include <cmath>

namespace WeCo {

namespace {

class _CCFPartThickness : public CCFPart {
public:
    _CCFPartThickness(
        const CCFContext& ctx,
        const Project& project,
        const std::string& depth_name,
        double expected_ratio,
        double sigma,
        double weight
    ) :
        CCFPart(ctx),
        depth_(ctx, project.well_list(), depth_name),
        expected_ratio_(expected_ratio),
        sigma_(sigma),
        weight_(weight)
    {}

    bool full_cost(CostValue& cost) override {
        unsigned n = context.size();
        if (n < 2) return true;

        // Compute thickness per well (|dest - src| depth)
        std::vector<double> thickness(n);
        for (unsigned w = 0; w < n; w++) {
            double src_d = depth_.src_data(w);
            double dest_d = depth_.dest_data(w);
            thickness[w] = std::fabs(dest_d - src_d) + 1e-10;
        }

        double total = 0.0;
        unsigned count = 0;
        for (unsigned i = 0; i < n; i++) {
            for (unsigned j = i + 1; j < n; j++) {
                double ratio = thickness[i] / thickness[j];
                double deviation = (ratio - expected_ratio_) / sigma_;
                total += deviation * deviation;
                count++;
            }
        }

        if (count > 0)
            cost += weight_ * total / static_cast<double>(count);

        return true;
    }

    bool dest_only() const override { return false; }

private:
    CostHelperData depth_;
    double expected_ratio_;
    double sigma_;
    double weight_;
};


class _CCFPartThicknessFactory : public CCFGlobalPartFactory {
public:
    OptionString option_data{ "thickness-data", "depth",
        "Depth data channel for thickness ratio cost", "50CCF.Thickness" };
    OptionFloat option_expected_ratio{ "thickness-expected-ratio", 1.0,
        "Expected thickness ratio between wells", "50CCF.Thickness" };
    OptionFloat option_sigma{ "thickness-sigma", 0.5,
        "Tolerance (std dev) for thickness ratio", "50CCF.Thickness" };
    OptionFloat option_weight{ "thickness-weight", 0.0,
        "Weight for thickness ratio cost (0 = disabled)", "50CCF.Thickness" };

    bool test(const Project& project) const override {
        return true;
    }

    CCFPart* create(const Project& project, const CCFContext& ctx) const override {
        if (option_weight() <= 0.0) return nullptr;
        return new _CCFPartThickness(
            ctx, project,
            option_data(),
            option_expected_ratio(),
            option_sigma(),
            option_weight()
        );
    }
};

static _CCFPartThicknessFactory _ccf_thickness_factory;

} // anonymous namespace
} // namespace WeCo
