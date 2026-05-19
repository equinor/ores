from unittest import main, TestCase
from weco.data import Well, WellList
from weco.engine_data import well_engine2python, well_python2engine
from weco.engine_data import well_list_engine2python, well_list_python2engine


class TestCovert(TestCase):

    @staticmethod
    def well1():
        well = Well(name="Well1")
        well.size = 12
        well.x = 3.
        well.y = 5.
        well.z = 8.
        well.h = 2.

        well.add_data("data1", 12., 44., 22.)
        well.add_data("data2", 2., 4., 2., 7.)

        well.add_region('region1', (1, 2, 5), (3, 9, 4))
        well.add_region('region2', (0, 6, 59), (2, 1, 2), (1, 5, 7))
        return well

    @staticmethod
    def well2():
        well = Well(name="Well2")
        well.size = 1
        well.x = 13.
        well.y = 15.
        well.z = 18.
        well.h = 22.

        well.add_data("data1", 12., 41., 22.)
        well.add_data("data2", 2., 2., 2., 7.)

        well.add_region('region1', (1, 3, 5), (3, 2, 4))
        well.add_region('region2', (0, 4, 5), (3, 1, 2), (1, 6, 7))
        return well

    def compare_well(self, well1: Well, well2: Well):
        self.assertEqual(well1.name, well2.name)
        self.assertEqual(well1.size, well2.size)
        self.assertEqual(well1.x, well2.x)
        self.assertEqual(well1.y, well2.y)
        self.assertEqual(well1.z, well2.z)
        self.assertEqual(well1.h, well2.h)
        self.assertEqual(well1.data, well2.data)
        self.assertEqual(well1.region, well2.region)

    def test_well_convert(self):
        well = self.well2()
        ewell = well_python2engine(well)
        conv = well_engine2python(ewell)
        self.compare_well(well, conv)

    def test_well_list_convert(self):
        well_list = WellList()
        well_list.add_well(self.well1())
        well_list.add_well(self.well2())
        well_list.add_well(self.well1())
        cwell_list = well_list_python2engine(well_list)
        conv = well_list_engine2python(cwell_list)

        self.assertEqual(len(well_list.wells), len(conv.wells))
        for w1, w2 in zip(well_list.wells, conv.wells):
            self.compare_well(w1, w2)


if __name__ == '__main__':
    main()
