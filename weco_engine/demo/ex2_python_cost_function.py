from weco.ext import ProjectExt, CCFPartExt

wells_file = "test_wells.txt"

# 1 Create project instance
project = ProjectExt()


class MyCost1(CCFPartExt):
    data = None

    def init(self):
        # easy access to data value
        self.data = self.data_helper("data")

    def full_cost(self, prev_cost):
        # compute cost
        # cost = max of dest - src
        cost = max(
            abs(self.data.src(i) - self.dest(i))
            for i in range(self.size())
        )

        # return True for ok and cost
        return True, prev_cost + cost


class MyCost2(CCFPartExt):
    region = None

    @staticmethod
    def dest_only():
        # optimisation : only the destinations values are needed
        return True

    def init(self):
        # easy access to region value
        self.region = self.region_helper("region")

    def dest_cost(self, prev_cost):
        # compute cost
        # cost is number of different regions in destination
        cost = len(set(self.region.dest(i) for i in range(self.size()))) - 1

        return True, prev_cost + cost


# 2 declare cost functions
project.add_ccf_part(MyCost1)
project.add_ccf_part(MyCost2)

# 3 set options (replace - with _)
project.set_options_ext(
    cost_function="composite",
    debug_cor_info=1,
    max_cor=5,
)

# you can also read option files
# project.option_load("options.txt")

# 4 start correlation on wells file test_wells.txt
project.run(wells_file)
