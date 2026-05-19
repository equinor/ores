from weco.ext import ProjectExt

# 1 Create project instance
project = ProjectExt()

# 2 set options (replace - with _)
project.set_options_ext(
    var_data="data",
    cost_function="composite",
    debug_cor_info=1,
    max_cor=1,
)

# you can also read option files
# project.option_load("options.txt")

# start correlation on wells file test_wells.txt
project.run("test_wells.txt")
