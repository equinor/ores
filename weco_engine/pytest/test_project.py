from unittest import main, TestCase


class TestProject(TestCase):

    def get_project(self):
        from weco.engine import Project
        return Project()

    def test_options(self):
        p = self.get_project()
        self.assertTrue(p.option_exists("cost-function"))

        p.set_option_value("var-data", "test1")
        self.assertEqual(p.get_option_value("var-data"), "test1")

        self.assertFalse(p.set_option_value("NotAnOption",""))
        self.assertTrue(p.set_option_value("nbr-cor","11"))
        self.assertFalse(p.set_option_value("nbr-cor","AAA"))


class TestProjectEx(TestProject):
    def get_project(self):
        from weco.ext import ProjectExt
        return ProjectExt()

    def test_options_ext(self):
        p = self.get_project()

        self.assertRaises(
            ValueError, p.get_option_ext, "not_an_option"
        )

        p.set_option_ext("var-data2", "test2")
        self.assertEqual(p.get_option_ext("var-data2"), "test2")

        p.set_option_ext("nbr-cor", 32)
        self.assertEqual(p.get_option_ext("nbr-cor"), 32)

        p.set_option_ext("min-dist", 42)
        self.assertEqual(p.get_option_ext("min-dist"), 42.)

        self.assertRaises(ValueError, p.set_option_ext, "max-cor", "abcd")
        self.assertRaises(ValueError, p.set_option_ext, "NotAnOption", "abcd")
        self.assertRaises(ValueError, p.set_option_ext, "min-dist", "abcd")

        p.set_options_ext(step_dot="test.txt", max_cor=44)
        self.assertEqual(p.get_option_ext("step-dot"), "test.txt")
        self.assertEqual(p.get_option_ext("max-cor"), 44)


if __name__ == '__main__':
    main()
