Examples
========

wecorun
-------

Six simple tests, used as regressions test. You can use also test them
with WeCoGui:

* Load the well_list_files (test?_wells.txt) with the **well list** /
  **select** button on the **main** panel.
* load the option file (test?_options.txt) with the **load** button on the
  **options**  panel.
* click on the **run** button (**main** panel)
* You can visualize the result on th **result** panel.
* then you can change some options and test it.

Tests:

* test1 : 2 wells and data correlation
* test2 : 2 wells,data correlation, 3 regions (1,8,1) for first well,
  (3,4,3) for second well
* test3 : 3 wells, data  correlation, alternate regions
* test4 : No result possible
* test5 : 20 wells size 150-200 data and alternate regions
* test6 : 4 wells with no-crossing

python
------

Some python code sample.

* ex1_run_weco_from_python.py : run weco from python
* ex2_python_cost_function.py : create a cost function in python
* ex4_multiscale_and_test_generation.py : Test generation and multiscale
* ex6_order_function.py : Order function in python
* ex8_multiscale.py : Multiscale correlation example
