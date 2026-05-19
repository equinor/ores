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
#include <weco.h>
#include <weco/project.h>
#include <weco_plugin.h>

namespace WeCo {

//=================================================
// platfome specific
//=================================================

constexpr const char *entry_point = "_weco_plugin_init";
#ifdef _WIN32
#define NOMINMAX
#define WIN32_LEAN_AND_MEAN
#include "Windows.h"

static void *_load_plugin(const std::string &file_name) {
    HMODULE library = LoadLibraryA(file_name.c_str());
    if (!library)
        return nullptr;
    return reinterpret_cast<void *>(
        GetProcAddress(library, LPCSTR(entry_point)));
};

#else // UNIX
#include <dlfcn.h>

static void *_load_plugin(const std::string &file_name) {
    void *lib = dlopen(file_name.c_str(), RTLD_NOW);
    if (!lib)
        return nullptr;
    return dlsym(lib, entry_point);
};

#endif

//=================================================
// Options
//=================================================
static std::vector<WeCo::Option *> _options;
static std::vector<std::string> _options_value;

static std::string _option_order() {
    static int num;
    char buf[32];

    snprintf(buf, 32, "60PLU.%03i", num++);
    return buf;
};

static int _create_option(const char *name, int option_type, const char *desc,
                          const char *value) {

    WeCo::Option *new_option = nullptr;

    switch (option_type) {
    case WCPOptionType::String:
        new_option = new WeCo::OptionString(name, "", desc, _option_order());
        break;
    case WCPOptionType::Int:
        new_option = new WeCo::OptionInt(name, 0, desc, _option_order());
        break;
    case WCPOptionType::Float:
        new_option = new WeCo::OptionFloat(name, 0., desc, _option_order());
        break;
    case WCPOptionType::Bool:
        new_option = new WeCo::OptionBool(name, false, desc, _option_order());
        break;
    case WCPOptionType::Data:
        new_option = new WeCo::OptionData(name, "", desc, _option_order());
        break;
    case WCPOptionType::Region:
        new_option = new WeCo::OptionRegion(name, "", desc, _option_order());
        break;
    default:
        std::cerr << "*ERR* Bad plugin option type " << option_type
                  << " for option " << name << std::endl;
        return -1;
    };

    new_option->set(value);
    _options.push_back(new_option);
    _options_value.push_back("");

    return _options.size() - 1;
};

static const char *_get_option_value(int num) {
    if (num < 0 || (unsigned)num >= _options.size()) {
        return nullptr;
    };
    _options_value[num] = _options[num]->string();
    return _options_value[num].c_str();
};

//=================================================
// Plugin CCF
//=================================================
namespace {

class _PluginCCFPart : public CCFPart {
  public:
    _PluginCCFPart(const CCFContext &ctx, const Project &project)
        : CCFPart(ctx), project(project) {
    }

    bool dest_cost(CostValue &cost) override { return cost_function(cost); }

    bool full_cost(CostValue &cost) override { return cost_function(cost); }

    bool cost_function(CostValue &cost);

    virtual ~_PluginCCFPart() {
        if (free_func_)
            free_func_(user_data_);
    }

    bool dest_only() const override { return dest_only_; }

    const Project &project;
    WCPCostFunctionFree free_func_;
    WCPCostFunction cost_func_;
    void *user_data_;
    bool dest_only_;

    std::vector<std::unique_ptr<WeCo::CostHelperData>> datas;
    std::vector<std::unique_ptr<WeCo::CostHelperRegion>> regions;

    bool set_result(WCPCostFunctionFactoryResult &res) {
        if (!res.cost_function) {
            return false;
        }
        cost_func_ = res.cost_function;
        free_func_ = res.free_function;
        user_data_ = res.user;
        dest_only_ = (bool)res.dest_only;

        return true;
    }

    static const char *f_get_option_value(void *, int num) {
        return _get_option_value(num);
    }

    static unsigned f_size(void *weco) {
        return reinterpret_cast<_PluginCCFPart *>(weco)->context.size();
    }
    static unsigned f_size1(void *weco) {
        return reinterpret_cast<_PluginCCFPart *>(weco)->context.size1();
    }
    static unsigned f_size2(void *weco) {
        return reinterpret_cast<_PluginCCFPart *>(weco)->context.size2();
    }

    static unsigned f_well_size(void *weco, unsigned well) {
        const WeCo::CCFContext &ctx =
            reinterpret_cast<_PluginCCFPart *>(weco)->context;
        return well < ctx.size() ? ctx.well(well).well_size() : 0;
    }
    static unsigned f_well_id(void *weco, unsigned well) {
        const WeCo::CCFContext &ctx =
            reinterpret_cast<_PluginCCFPart *>(weco)->context;
        return well < ctx.size() ? ctx.well(well).well_id() : 0;
    }
    static double f_well_x(void *weco, unsigned well) {
        const WeCo::CCFContext &ctx =
            reinterpret_cast<_PluginCCFPart *>(weco)->context;
        return well < ctx.size() ? ctx.well(well).x() : 0.;
    }
    static double f_well_y(void *weco, unsigned well) {
        const WeCo::CCFContext &ctx =
            reinterpret_cast<_PluginCCFPart *>(weco)->context;
        return well < ctx.size() ? ctx.well(well).y() : 0.;
    }
    static double f_well_z(void *weco, unsigned well) {
        const WeCo::CCFContext &ctx =
            reinterpret_cast<_PluginCCFPart *>(weco)->context;
        return well < ctx.size() ? ctx.well(well).z() : 0.;
    }
    static double f_well_h(void *weco, unsigned well) {
        const WeCo::CCFContext &ctx =
            reinterpret_cast<_PluginCCFPart *>(weco)->context;
        return well < ctx.size() ? ctx.well(well).h() : 0.;
    }

    static int f_data_exists(void *weco, unsigned well, const char *name) {
        return reinterpret_cast<_PluginCCFPart *>(weco)
            ->context.well(well)
            .data_exists(name);
    }
    static unsigned f_data_size(void *weco, unsigned well, const char *name) {
        return reinterpret_cast<_PluginCCFPart *>(weco)
            ->context.well(well)
            .get_data(name)
            .size();
    }

    static double f_data_get(void *weco, unsigned well, const char *name,
                             unsigned n) {
        return reinterpret_cast<_PluginCCFPart *>(weco)
            ->context.well(well)
            .get_data(name)[n];
    }

    static int f_region_exists(void *weco, unsigned well, const char *name) {
        return reinterpret_cast<_PluginCCFPart *>(weco)
            ->context.well(well)
            .region_list_exists(name);
    }

    static unsigned f_region_get(void *weco, unsigned well, const char *name,
                                 unsigned n, unsigned default_value) {
        return reinterpret_cast<_PluginCCFPart *>(weco)
            ->context.well(well)
            .get_region_list(name)
            .get_region(n, default_value);
    }

    static int f_data_helper(void *weco, const char *name) {
        return reinterpret_cast<_PluginCCFPart *>(weco)->data_helper(name);
    }

    int data_helper(const std::string &name) {

        if (!project.well_list().wells_data_exists(name))
            return -1;
        for (unsigned w = 0; w < context.size(); w++) {
            if (context.well(w).get_data(name).size() <
                context.well(w).well_size())
                return -1;
        }
        datas.emplace_back(
            new WeCo::CostHelperData(context, project.well_list(), name));
        return datas.size() - 1;
    }
    static int f_region_helper(void *weco, const char *name) {
        return reinterpret_cast<_PluginCCFPart *>(weco)->region_helper(name);
    }

    int region_helper(const std::string &name) {
        if (!project.well_list().region_list_exists(name))
            return -1;
        regions.emplace_back(
            new WeCo::CostHelperRegion(context, project.well_list(), name));
        return regions.size() - 1;
    }

    static unsigned f_src(void *weco, unsigned well) {
        return reinterpret_cast<_PluginCCFPart *>(weco)->context.src(well);
    }
    static unsigned f_dest(void *weco, unsigned well) {
        return reinterpret_cast<_PluginCCFPart *>(weco)->context.dest(well);
    }
    static int f_same(void *weco, unsigned well) {
        return reinterpret_cast<_PluginCCFPart *>(weco)->context.same(well);
    }
    static int f_at_start(void *weco, unsigned well) {
        return reinterpret_cast<_PluginCCFPart *>(weco)->context.at_start(well);
    }
    static int f_at_end(void *weco, unsigned well) {
        return reinterpret_cast<_PluginCCFPart *>(weco)->context.at_end(well);
    }
    static int f_gap_at_start(void *weco, unsigned well) {
        return reinterpret_cast<_PluginCCFPart *>(weco)->context.at_start(well);
    }
    static int f_gap_at_end(void *weco, unsigned well) {
        return reinterpret_cast<_PluginCCFPart *>(weco)->context.at_end(well);
    }
    static double f_parent_cost1(void *weco) {
        return reinterpret_cast<_PluginCCFPart *>(weco)->context.parent_cost1();
    }
    static double f_parent_cost2(void *weco) {
        return reinterpret_cast<_PluginCCFPart *>(weco)->context.parent_cost2();
    }

    static unsigned f_data_size(void *weco, unsigned data_helper,
                                unsigned well) {
        return reinterpret_cast<_PluginCCFPart *>(weco)
            ->datas.at(data_helper)
            ->data(well)
            .size();
    }
    static double f_data_get(void *weco, unsigned data_helper, unsigned well,
                             unsigned n) {
        return reinterpret_cast<_PluginCCFPart *>(weco)
            ->datas.at(data_helper)
            ->data(well)
            .get(n);
    }
    static double f_data_src(void *weco, unsigned data_helper, unsigned well) {
        return reinterpret_cast<_PluginCCFPart *>(weco)
            ->datas.at(data_helper)
            ->src_data(well);
    }
    static double f_data_dest(void *weco, unsigned data_helper, unsigned well) {
        return reinterpret_cast<_PluginCCFPart *>(weco)
            ->datas.at(data_helper)
            ->dest_data(well);
    }

    static unsigned f_region_get(void *weco, unsigned region_helper,
                                 unsigned well, unsigned n) {
        return reinterpret_cast<_PluginCCFPart *>(weco)
            ->regions.at(region_helper)
            ->get_region(well, n);
    }
    static unsigned f_region_src(void *weco, unsigned region_helper,
                                 unsigned well) {
        return reinterpret_cast<_PluginCCFPart *>(weco)
            ->regions.at(region_helper)
            ->src_region(well);
    }
    static unsigned f_region_dest(void *weco, unsigned region_helper,
                                  unsigned well) {
        return reinterpret_cast<_PluginCCFPart *>(weco)
            ->regions.at(region_helper)
            ->dest_region(well);
    }
};

static const WCPCostFunctionFactoryFunctions _fact_func_table{
    _PluginCCFPart::f_get_option_value,

    _PluginCCFPart::f_size,
    _PluginCCFPart::f_size1,
    _PluginCCFPart::f_size2,

    _PluginCCFPart::f_well_size,
    _PluginCCFPart::f_well_id,
    _PluginCCFPart::f_well_x,
    _PluginCCFPart::f_well_y,
    _PluginCCFPart::f_well_z,
    _PluginCCFPart::f_well_h,

    _PluginCCFPart::f_data_exists,
    _PluginCCFPart::f_data_size,
    _PluginCCFPart::f_data_get,

    _PluginCCFPart::f_region_exists,
    _PluginCCFPart::f_region_get,

    _PluginCCFPart::f_data_helper,
    _PluginCCFPart::f_region_helper

};

static const WCPCostFunctionFunctions _cost_func_table{

    _PluginCCFPart::f_size,         _PluginCCFPart::f_size1,
    _PluginCCFPart::f_size2,

    _PluginCCFPart::f_well_size,    _PluginCCFPart::f_well_id,
    _PluginCCFPart::f_well_x,       _PluginCCFPart::f_well_y,
    _PluginCCFPart::f_well_z,       _PluginCCFPart::f_well_h,

    _PluginCCFPart::f_src,          _PluginCCFPart::f_dest,
    _PluginCCFPart::f_same,         _PluginCCFPart::f_at_start,
    _PluginCCFPart::f_at_end,       _PluginCCFPart::f_gap_at_start,
    _PluginCCFPart::f_gap_at_end,   _PluginCCFPart::f_parent_cost1,
    _PluginCCFPart::f_parent_cost2,

    _PluginCCFPart::f_data_size,    _PluginCCFPart::f_data_get,
    _PluginCCFPart::f_data_src,     _PluginCCFPart::f_data_dest,

    _PluginCCFPart::f_region_get,   _PluginCCFPart::f_region_src,
    _PluginCCFPart::f_region_dest

};

inline bool _PluginCCFPart::cost_function(CostValue &cost) {

    double new_cost = cost_func_(this, &_cost_func_table, user_data_);
    if (new_cost < 0.)
        return false;
    cost += new_cost;
    return true;
}

//=================================================
// Plugin CCF Factory
//=================================================

class _PluginCCFPartFactory : public CCFGlobalPartFactory {

    static std::vector<_PluginCCFPartFactory *> factories_;
    WCPCostFunctionFactory fact_func_;
    OptionBool option_activate_;

    _PluginCCFPartFactory(const std::string &name,
                          WCPCostFunctionFactory fact_func,
                          const std::string &desc)
        : fact_func_(fact_func),
          option_activate_(name, false, desc, _option_order()) {
    }

  public:
    CCFPart *create(const Project &project,
                    const CCFContext &ctx) const override {
        if (!option_activate_())
            return nullptr;

        WCPCostFunctionFactoryResult result;
        result.cost_function = nullptr;
        result.free_function = nullptr;
        result.dest_only = 0;

        _PluginCCFPart *cost_func = new _PluginCCFPart(ctx, project);
        fact_func_(cost_func, &_fact_func_table, &result);
        if (cost_func->set_result(result)) {
            return cost_func;
        }
        delete cost_func;
        return nullptr;
    };

    static bool declare(const char *name, WCPCostFunctionFactory fact_func,
                        const char *desc) {
        factories_.push_back(new _PluginCCFPartFactory(name, fact_func, desc));
        return true;
    };
};
std::vector<_PluginCCFPartFactory *> _PluginCCFPartFactory::factories_;

}; // namespace

//=================================================
// load plugin
//=================================================

bool load_plugin(const std::string &file_name) {
    void *entry_point = _load_plugin(file_name);
    if (!entry_point) {
        std::cerr << "*ERR* loading plugin " << file_name << std::endl;
        return false;
    }

    WCPPluginInit init_context{WCP_VERSION, _PluginCCFPartFactory::declare,
                               _create_option};
    reinterpret_cast<void (*)(const WCPPluginInit *)>(entry_point)(
        &init_context);
    return true;
};

} // namespace WeCo