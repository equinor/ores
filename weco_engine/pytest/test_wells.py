from unittest import main, TestCase
from weco.engine import Well, RegionList, WellList
from weco.data import Well as PyWell


class TestWell(TestCase):

    def test_create(self):
        well = Well(well_name="WellName", x=3., y=9., z=2., h=6., well_size=42, )

        self.assertEqual(well.well_name(), "WellName")
        self.assertEqual(well.x(), 3.)
        self.assertEqual(well.y(), 9.)
        self.assertEqual(well.z(), 2.)
        self.assertEqual(well.h(), 6.)
        self.assertEqual(well.well_size(), 42)

    def test_create_default(self):
        well = Well()

        self.assertEqual(well.well_name(), "")
        self.assertEqual(well.x(), 0.)
        self.assertEqual(well.y(), 0.)
        self.assertEqual(well.z(), 0.)
        self.assertEqual(well.h(), 0.)
        self.assertEqual(well.well_size(), 0)

    def test_data(self):
        data = [3., 1., 2., 999.]
        well = Well()
        well.add_data("data", data)
        self.assertTrue(well.data_exists("data"))
        self.assertFalse(well.data_exists("data2"))
        self.assertEqual(well.data_names(), ["data"])
        well_data = well.get_data("data")
        self.assertEqual(well_data.size(), len(data))
        self.assertEqual(well_data.name(), "data")
        for n, v in enumerate(data):
            self.assertEqual(well_data.get(n), v)
        self.assertEqual(well.get_data('data').data(), data)

    def test_region(self):

        region_data = [(1, 0, 5), (2, 5, 3), (1, 9, 4)]

        region_list = RegionList("region")
        self.assertEqual(region_list.name(), "region")

        for i in region_data:
            region_list.add(*i)

        self.assertEqual(region_list.get_region(7), 2)
        self.assertEqual(region_list.get_region(45, 9), 9)
        self.assertEqual(region_list.get_region(45), 0)

        self.assertEqual(len(region_list.regions()), len(region_data))
        for region, data in zip(region_list.regions(), region_data):
            self.assertEqual((region.id, region.start, region.length), data)

        well = Well()
        self.assertFalse(well.region_list_exists('region'))
        self.assertEqual(well.region_list_names(), [])

        well.add_region_list(region_list)
        self.assertTrue(well.region_list_exists('region'))
        self.assertEqual(well.get_region_list("region").get_region(7), 2)
        self.assertEqual(well.region_list_names(), ["region"])

    def test_well_list(self):
        well1_data = [3., 1., 2., 999.]
        well2_data = [7., 9., 999.]

        well1 = Well(well_name="Well1")
        well1.add_data("data", well1_data)
        well2 = Well(well_name="Well2")
        well2.add_data("data", well2_data)

        well_list = WellList()
        self.assertEqual(well_list.nbr_wells(), 0)

        well_list.add(well1)
        well_list.add(well2)
        self.assertEqual(well_list.nbr_wells(), 2)

        self.assertEqual(well_list.well(1).well_name(), "Well2")
        self.assertEqual(well_list.well(1).get_data("data").get(1), 9.)

    def test_derivative(self):
        well = PyWell()
        well.add_data("data", [1., 2., 3.])
        well.add_derivative("data")
        self.assertEqual(well.data["data_derivative"], (1., 1., 1.))


if __name__ == '__main__':
    main()
