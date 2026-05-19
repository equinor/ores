/*

Association Scientifique pour la Geologie et ses Applications (ASGA)

Copyright (c) 2018 ASGA. All Rights Reserved.

This program is a Trade Secret of the ASGA and it is not to be:
 * reproduced, published, or disclosed to other,
 * distributed or displayed,
 * used for purposes or on Sites other than described in the GOCAD Advancement
Agreement, without the prior written authorization of the ASGA.

Licencee agrees to attach or embed this Notice on all copies of the program,
including partial copies or modified versions thereof.

*/
#include <iostream>
#include <weco_plugin.h>

//================  Dist Cost function ======================
class DistCostFunction : public WeCoPlugin::CostFunction {
  public:
    DistCostFunction(unsigned data)
        : WeCoPlugin::CostFunction(false), data_(data){};

  protected:
    unsigned data_;
    virtual double get_cost() override {
        double sum = 0.;
        unsigned s = size();

        for (unsigned n = 0; n < s; n++) {
            double v = data_src(data_, n) - data_dest(data_, n);
            sum += v * v;
        }
        return sum;
    };
};

static int dist_data;
static void dist_factory(void *weco,
                         const WCPCostFunctionFactoryFunctions *func,
                         WCPCostFunctionFactoryResult *result) {
    WeCoPlugin::FactoryHelper factory(weco, func, result);

    int data = factory.data_helper(dist_data);
    if (data < 0) {
        std::cerr << "*ERR* bad value for testplugin-dist-data" << std::endl;
        return;
    }

    factory.set_cost_function<DistCostFunction>((unsigned)data);
};

//================  Var Cost function ======================

class VarCostFunction : public WeCoPlugin::CostFunction {
  public:
    VarCostFunction(unsigned data, double weight)
        : WeCoPlugin::CostFunction(true), data_(data), weight_(weight){};

  protected:
    unsigned data_;
    double weight_;
    virtual double get_cost() override {
        double sum = 0.;
        double sum2 = 0.;
        unsigned s = size();

        for (unsigned n = 0; n < s; n++) {
            double v = data_dest(data_, n);
            sum += v;
            sum2 += v * v;
        }
        double mean = sum / s;
        return ((sum2 / s) - mean * mean) * weight_;
    };
};

static int var_weight;
static int var_data;
static void var_factory(void *weco, const WCPCostFunctionFactoryFunctions *func,
                        WCPCostFunctionFactoryResult *result) {
    WeCoPlugin::FactoryHelper factory(weco, func, result);

    double weight = factory.get_option_float(var_weight);
    int data = factory.data_helper(var_data);
    if (data < 0) {
        std::cerr << "*ERR* bad value for testplugin-var-data" << std::endl;
        return;
    }

    factory.set_cost_function<VarCostFunction>((unsigned)data, weight);
};

WCP_PLUGIN_INIT {
    WeCoPlugin::InitHelper plugin(ctx);

    std::cout << "Loading Plugin\n"
              << "Loader Version:" << plugin.version() << '\n'
              << "Local Version:" << WCP_VERSION << std::endl;

    if (!plugin.check_version()) {
        std::cerr << "*ERR* Bad WeCo Version for this plugin" << std::endl;
        return;
    }

    // var cost function
    plugin.declare_cost_function("testplugin-var", var_factory,
                                 "simple variance cost function");

    var_data = plugin.create_data_option("testplugin-var-data",
                                         "data for testplugin-var");

    var_weight = plugin.create_float_option("testplugin-var-weight",
                                            "weight for testplugin-var", 1.);

    // dist cost function
    plugin.declare_cost_function("testplugin-dist", dist_factory,
                                 "simple square distance cost function");

    dist_data = plugin.create_data_option("testplugin-dist-data",
                                          "data for testplugin-dist");
};