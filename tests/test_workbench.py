import unittest

from freecad_plm_addon.workbench import create_workbench


class BaseWorkbench:
    def appendToolbar(self, name, commands):
        self.toolbar = (name, commands)

    def appendMenu(self, name, commands):
        self.menu = (name, commands)


class WorkbenchTests(unittest.TestCase):
    def test_create_workbench_uses_base_class(self):
        workbench = create_workbench(BaseWorkbench)

        self.assertIsInstance(workbench, BaseWorkbench)
        self.assertEqual(workbench.GetClassName(), "Gui::PythonWorkbench")


if __name__ == "__main__":
    unittest.main()
