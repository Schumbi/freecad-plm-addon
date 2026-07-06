import unittest
from unittest.mock import patch

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

    def test_initialize_adds_activate_connection_to_toolbar(self):
        workbench = create_workbench(BaseWorkbench)
        commands = [
            "FreeCADPLM_ActivateConnection",
            "FreeCADPLM_Connect",
            "FreeCADPLM_Refresh",
            "FreeCADPLM_Checkout",
            "FreeCADPLM_Checkin",
            "FreeCADPLM_CancelCheckout",
            "FreeCADPLM_CreateAnnotation",
        ]

        with patch("freecad_plm_addon.commands.register_commands", return_value=commands):
            workbench.Initialize()

        self.assertEqual(workbench.toolbar, ("FreeCAD-PLM", commands))
        self.assertEqual(workbench.menu, ("FreeCAD-PLM", commands))


if __name__ == "__main__":
    unittest.main()
