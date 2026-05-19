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

#ifndef __weco_plugin_h__
#define __weco_plugin_h__
#include <assert.h>

#ifdef __cplusplus
extern "C" {
#define __WCPEXTERN extern "C"
#else
#define __WCPEXTERN
#endif

#ifdef _WIN32
#define WCP_PLUGIN_INIT                                                        \
    __WCPEXTERN _declspec(dllexport) void _weco_plugin_init(                   \
        const WCPPluginInit *ctx)
#else
#define WCP_PLUGIN_INIT                                                        \
    __WCPEXTERN void _weco_plugin_init(const WCPPluginInit *ctx)
#endif

#define WCP_VERSION 1

struct WCPOptionType {
    enum { String = 0, Int, Float, Bool, Data, Region };
};

// ============================== cost function =========================

struct WCPCostFunctionFunctions {

    unsigned (*size)(void *weco);
    unsigned (*size1)(void *weco);
    unsigned (*size2)(void *weco);

    unsigned (*well_size)(void *weco, unsigned well);
    unsigned (*well_id)(void *weco, unsigned well);

    double (*well_x)(void *weco, unsigned well);
    double (*well_y)(void *weco, unsigned well);
    double (*well_z)(void *weco, unsigned well);
    double (*well_h)(void *weco, unsigned well);

    unsigned (*src)(void *weco, unsigned well);
    unsigned (*dest)(void *weco, unsigned well);
    int (*same)(void *weco, unsigned well);
    int (*at_start)(void *weco, unsigned well);
    int (*at_end)(void *weco, unsigned well);
    int (*gap_at_start)(void *weco, unsigned well);
    int (*gap_at_end)(void *weco, unsigned well);
    double (*parent_cost1)(void *weco);
    double (*parent_cost2)(void *weco);

    unsigned (*data_size)(void *weco, unsigned data_helper, unsigned well);
    double (*data_get)(void *weco, unsigned data_helper, unsigned well,
                       unsigned n);
    double (*data_src)(void *weco, unsigned data_helper, unsigned well);
    double (*data_dest)(void *weco, unsigned data_helper, unsigned well);

    unsigned (*region_get)(void *weco, unsigned region_helper, unsigned well,
                           unsigned n);
    unsigned (*region_src)(void *weco, unsigned region_helper, unsigned well);
    unsigned (*region_dest)(void *weco, unsigned region_helper, unsigned well);
};

typedef void (*WCPCostFunctionFree)(void *user);

typedef double (*WCPCostFunction)(void *weco,
                                  const WCPCostFunctionFunctions *func,
                                  void *user);

// ============================== cost function factory

struct WCPCostFunctionFactoryFunctions {
    /// @brief return option value
    const char *(*get_option_value)(void *weco, int num);

    unsigned (*size)(void *weco);
    unsigned (*size1)(void *weco);
    unsigned (*size2)(void *weco);

    unsigned (*well_size)(void *weco, unsigned well);
    unsigned (*well_id)(void *weco, unsigned well);

    double (*well_x)(void *weco, unsigned well);
    double (*well_y)(void *weco, unsigned well);
    double (*well_z)(void *weco, unsigned well);
    double (*well_h)(void *weco, unsigned well);

    int (*data_exists)(void *weco, unsigned well, const char *name);
    unsigned (*data_size)(void *weco, unsigned well, const char *name);
    double (*data_get)(void *weco, unsigned well, const char *name, unsigned n);

    int (*region_exists)(void *weco, unsigned well, const char *name);
    unsigned (*region_get)(void *weco, unsigned well, const char *name,
                           unsigned n, unsigned default_value);

    int (*data_helper)(void *weco, const char *name);
    int (*region_helper)(void *weco, const char *name);
};
struct WCPCostFunctionFactoryResult {
    void *user;
    WCPCostFunction cost_function;
    WCPCostFunctionFree free_function;
    int dest_only;
};

typedef void (*WCPCostFunctionFactory)(void *,
                                       const WCPCostFunctionFactoryFunctions *,
                                       WCPCostFunctionFactoryResult *);

// ============================== init =========================

struct WCPPluginInit {
    /**
     * @brief
     *
     */
    const int version;

    /// decare a cost function
    bool (*declare_cost_function)(const char *name,
                                  WCPCostFunctionFactory factory,
                                  const char *desc);
    /// create a new option
    int (*create_option)(const char *name, int option_type, const char *doc,
                         const char *value);
};

#ifdef __cplusplus
}; // extern "C"
#include <string>

namespace WeCoPlugin {

class CostFunction {

  public:
    CostFunction(bool dest_only = false) : dest_only_(dest_only) {}

  private:
    bool dest_only_;

  public:
    void set_cost_function(WCPCostFunctionFactoryResult *result) {
        assert(!result->cost_function);
        result->cost_function = cost_function_;
        result->free_function = free_function_;
        result->dest_only = dest_only_ ? 1 : 0;
        result->user = this;
    };

  protected:
    virtual ~CostFunction(){};

    virtual double get_cost() { return 0.0001; };

    /// Total number of wells in correlation (size1 +size2)
    unsigned size() const { return func_->size(weco_); }
    /// number of wells in the first part of the correlation
    unsigned size1() const { return func_->size1(weco_); }
    /// number of wells in the second part of the correlation
    unsigned size2() const { return func_->size2(weco_); }

    /**
     * @brief Size of each wells (number of markers)
     *
     * @param well well num [0..size()[
     * @return unsigned
     */
    unsigned well_size(unsigned well) const {
        return func_->well_size(weco_, well);
    }
    /**
     * @brief well id
     *
     * @param well well num [0..size()[
     * @return unsigned
     */
    unsigned well_id(unsigned well) const {
        return func_->well_id(weco_, well);
    }

    /**
     * @brief well x position
     *
     * @param well well num [0..size()[
     * @return douple
     */
    double well_x(unsigned well) const { return func_->well_x(weco_, well); }

    /**
     * @brief well y position
     *
     * @param well well num [0..size()[
     * @return douple
     */
    double well_y(unsigned well) const { return func_->well_y(weco_, well); }
    /**
     * @brief well z position
     *
     * @param well well num [0..size()[
     * @return douple
     */
    double well_z(unsigned well) const { return func_->well_z(weco_, well); }
    /**
     * @brief well height (distance)
     *
     * @param well well num [0..size()[
     * @return douple
     */
    double well_h(unsigned well) const { return func_->well_h(weco_, well); }

    /**
     * @brief source of transition for well well
     *
     * @param well
     * @return unsigned well marker num
     */
    unsigned src(unsigned well) const { return func_->src(weco_, well); }
    /**
     * @brief destination of transition for well well
     *
     * @param well
     * @return unsigned well marker num
     */
    unsigned dest(unsigned well) const { return func_->src(weco_, well); }

    /**
     * @brief Check if source == destionation
     *
     * @param well
     * @return src(well) == dest(well)
     */
    bool same(unsigned well) const { return (bool)func_->same(weco_, well); }

    /// @return  src(well) == 0
    bool at_start(unsigned well) const {
        return (bool)func_->at_start(weco_, well);
    }
    /// @return  dest(well) == well_size(well)-1
    bool at_end(unsigned well) const {
        return (bool)func_->at_end(weco_, well);
    }
    /// @return  dest(well) == 0
    bool gap_at_start(unsigned well) const {
        return (bool)func_->gap_at_start(weco_, well);
    }
    /// @return  src(well) == well_size(well)-1
    bool gap_at_end(unsigned well) const {
        return (bool)func_->gap_at_end(weco_, well);
    }

    /// Transition cost of the first part in the previous correlation
    double parent_cost1() const { return func_->parent_cost1(weco_); }

    /// Transition cost of the second part in the previous correlation
    double parent_cost2() const { return func_->parent_cost2(weco_); }

    /**
     * @brief data size
     *
     * @param data_helper from FactoryHelper::data_helper
     * @param well well num [0..size()[
     * @return unsigned data size
     */
    unsigned data_size(unsigned data_helper, unsigned well) const {
        return func_->data_size(weco_, data_helper, well);
    }
    /**
     * @brief data size
     *
     * @param data_helper from FactoryHelper::data_helper
     * @param well well num [0..size()[
     * @param n data index  [ 0 .. data_size() [
     * @return double data value
     */
    double data_get(unsigned data_helper, unsigned well, unsigned n) const {
        return func_->data_get(weco_, data_helper, well, n);
    }

    /// shortcut for @ref data_get(data_helper, well, @ref src (well))
    double data_src(unsigned data_helper, unsigned well) const {
        return func_->data_src(weco_, data_helper, well);
    }

    /// shortcut for @ref data_get(data_helper, well, @ref dest (well))
    double data_dest(unsigned data_helper, unsigned well) const {
        return func_->data_dest(weco_, data_helper, well);
    }

    /// shortcut for @ref region_get(region_helper, well, @ref src (well))
    unsigned region_src(unsigned region_helper, unsigned well) const {
        return func_->region_src(weco_, region_helper, well);
    }

    /// shortcut for @ref region_get(region_helper, well, @ref dest (well))
    unsigned region_dest(unsigned region_helper, unsigned well) const {
        return func_->region_dest(weco_, region_helper, well);
    }

    /**
     * @brief region id for well marker
     *
     * @param region_helper from FactoryHelper::region_helper
     * @param well well num [0..size()[
     * @param n
     * @return unsigned region id
     */
    unsigned region_get(unsigned region_helper, unsigned well,
                        unsigned n) const {
        return func_->region_get(weco_, region_helper, well, n);
    }

    void *weco() const { return weco_; }
    const ::WCPCostFunctionFunctions *weco_functions() const { return func_; };

  private:
    void *weco_;
    const ::WCPCostFunctionFunctions *func_;

    static double cost_function_(void *weco,
                                 const ::WCPCostFunctionFunctions *func,
                                 void *user) {
        CostFunction *instance = reinterpret_cast<CostFunction *>(user);
        instance->weco_ = weco;
        instance->func_ = func;

        return instance->get_cost();
    };

    static void free_function_(void *user) {
        delete reinterpret_cast<CostFunction *>(user);
    };
};

class FactoryHelper {
  public:
    /**
     * @brief Construct a new Factory Helper object
     *
     * @param weco
     * @param func
     * @param result
     */
    FactoryHelper(void *weco, const ::WCPCostFunctionFactoryFunctions *func,
                  ::WCPCostFunctionFactoryResult *result)
        : weco_(weco), func_(func), result_(result){};

    template <class T, typename... Args> T *set_cost_function(Args... args) {
        T *cf = new T(args...);
        cf->set_cost_function(result_);
        return cf;
    };

    std::string get_option_value(int num) const {
        const char *value = func_->get_option_value(weco_, num);
        return value ? std::string(value) : std::string("");
    }

    bool get_option_bool(int num) const {
        return get_option_value(num) == "1";
    };
    double get_option_float(int num) const {
        return std::stod(get_option_value(num));
    };
    int get_option_int(int num) const {
        return std::stoi(get_option_value(num));
    };

    /// Total number of wells in correlation (size1 +size2)
    unsigned size() const { return func_->size(weco_); }
    /// number of wells in the first part of the correlation
    unsigned size1() const { return func_->size1(weco_); }
    /// number of wells in the second part of the correlation
    unsigned size2() const { return func_->size2(weco_); }

    /**
     * @brief Size of each wells (number of markers)
     *
     * @param well well num [0..size()[
     * @return unsigned
     */
    unsigned well_size(unsigned well) const {
        return func_->well_size(weco_, well);
    }
    /**
     * @brief well id
     *
     * @param well well num [0..size()[
     * @return unsigned
     */
    unsigned well_id(unsigned well) const {
        return func_->well_id(weco_, well);
    }

    /**
     * @brief well x position
     *
     * @param well well num [0..size()[
     * @return douple
     */
    double well_x(unsigned well) const { return func_->well_x(weco_, well); }

    /**
     * @brief well y position
     *
     * @param well well num [0..size()[
     * @return douple
     */
    double well_y(unsigned well) const { return func_->well_y(weco_, well); }
    /**
     * @brief well z position
     *
     * @param well well num [0..size()[
     * @return douple
     */
    double well_z(unsigned well) const { return func_->well_z(weco_, well); }
    /**
     * @brief well height (distance)
     *
     * @param well well num [0..size()[
     * @return douple
     */
    double well_h(unsigned well) const { return func_->well_h(weco_, well); }

    /**
     * @brief check if data exists
     *
     * @param well well num [0..size()[
     * @param name data name
     * @return true if data exists
     */
    bool data_exists(unsigned well, const std::string &name) const {
        return (bool)func_->data_exists(weco_, well, name.c_str());
    }
    /**
     * @brief data size
     *
     * @param well well num [0..size()[
     * @param name data name (must exists)
     * @return unsigned data size
     */
    unsigned data_size(unsigned well, const std::string &name) const {
        return func_->data_size(weco_, well, name.c_str());
    }
    /**
     * @brief  get data value
     *
     * @param well well num [0..size()[
     * @param name data name (must exists)
     * @param n data index
     * @return double data value
     */
    double data_get(unsigned well, const std::string &name, unsigned n) const {
        return func_->data_get(weco_, well, name.c_str(), n);
    }
    /**
     * @brief test if a region list exists
     *
     * @param well well num [0..size()[
     * @param name region name
     * @return true if region list exists
     */
    bool region_exists(unsigned well, const std::string &name) const {
        return (bool)func_->region_exists(weco_, well, name.c_str());
    }
    /**
     * @brief get region id
     *
     * @param well well num [0..size()[
     * @param name region name
     * @param n position
     * @param default_value value if there is no region at huis position
     * @return unsigned region id
     */
    unsigned region_get(unsigned well, const std::string &name, unsigned n,
                        unsigned default_value = 0) const {
        return func_->region_get(weco_, well, name.c_str(), n, default_value);
    }

    /**
     * @brief Create a data helper
     *
     * A data helper give access to data in a cost function
     *
     * data size must be >= well size and must exist for each wells
     *
     * @param name data name
     * @return int -1 if function fails, data helper id else
     */
    int data_helper(const std::string &name) const {
        return func_->data_helper(weco_, name.c_str());
    }

    /**
     * @brief Create a region helper
     *
     * A region helper give access to region in a cost function
     *
     * region must exist for each wells
     *
     * @param name regio name
     * @return int -1 if function fails, region helper id else
     */
    int region_helper(const std::string &name) const {
        return func_->region_helper(weco_, name.c_str());
    }

    /**
     * @brief Create a data helper from option
     *
     * A data helper give access to data in a cost function
     *
     * data size must be >= well size and must exists for each wells
     *
     * @param option option id
     * @return int -1 if function fails, data helper id else
     */
    int data_helper(int option) const {
        std::string name = get_option_value(option);
        return data_helper(name);
    }
    /**
     * @brief Create a region helper from option
     *
     * A region helper give access to data in a cost function
     *
     * region  must exist for each wells
     *
     * @param option option id
     * @return int -1 if function fails, data helper id else
     */
    int region_helper(int option) const {
        std::string name = get_option_value(option);
        return region_helper(name);
    }

  private:
    void *weco_;
    const ::WCPCostFunctionFactoryFunctions *func_;
    ::WCPCostFunctionFactoryResult *result_;
};

class InitHelper {
  public:
    InitHelper(const ::WCPPluginInit *ctx) : ctx_(ctx){};

    int version() const { return ctx_->version; };

    bool check_version() const { return version() >= WCP_VERSION; };

    bool declare_cost_function(const std::string &name,
                               ::WCPCostFunctionFactory factory,
                               const std::string &desc = "") {
        return ctx_->declare_cost_function(name.c_str(), factory, desc.c_str());
    };

    int create_option(const std::string &name, int option_type,
                      const std::string &doc, const std::string &value) {
        return ctx_->create_option(name.c_str(), option_type, doc.c_str(),
                                   value.c_str());
    };

    int create_float_option(const std::string &name, const std::string &doc,
                            double default_value = 0) {
        std::string value = std::to_string(default_value);
        return create_option(name, ::WCPOptionType::Float, doc, value);
    };
    int create_bool_option(const std::string &name, const std::string &doc,
                           bool default_value = false) {
        return create_option(name, ::WCPOptionType::Bool, doc,
                             default_value ? "1" : "0");
    };
    int create_int_option(const std::string &name, const std::string &doc,
                          int default_value = 0) {
        std::string value = std::to_string(default_value);
        return create_option(name, ::WCPOptionType::Int, doc, value);
    };

    int create_data_option(const std::string &name, const std::string &doc,
                           const std::string &value = "") {
        return create_option(name, ::WCPOptionType::Data, doc, value);
    };
    int create_region_option(const std::string &name, const std::string &doc,
                             const std::string &value = "") {
        return create_option(name, ::WCPOptionType::Region, doc, value);
    };

  private:
    const ::WCPPluginInit *ctx_;
};

}; // namespace WeCoPlugin

#endif // __cpluspus
#endif // __weco_plugin_h__