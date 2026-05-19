from weco.ext import ProjectExt
from pathlib import Path

wells_file = str(Path(__file__).parent / "test_wells.txt")

# 1 Create project instance
project = ProjectExt()


# create an order function
def order_function(wells, create_task):
    """
    This example creates two DAG correlations between the first and second well, then between the result
    and the third well.
    Is used by weco.ext.ProjectExt.set_order_func()

    :param wells: wells list
    :param create_task:  The function that launches the pair correlation task for two DAGs. Taken care of by WeCo.
    """
    t1 = create_task(wells[0], wells[1])
    t2 = create_task(t1, wells[2])
    print("Tasks:", t1, t2)


project.set_order_func(order_function)

project.set_options_ext(
    order_dot="order.dot",
    order_only=1,

)

project.run(wells_file)
