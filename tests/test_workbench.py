import unittest
from unittest.mock import patch
from pathlib import Path

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

    def test_workbench_has_icon_for_addon_manager_metadata(self):
        workbench = create_workbench(BaseWorkbench)

        self.assertTrue(Path(workbench.Icon).is_file())

    def test_initialize_builds_grouped_toolbar_and_menu(self):
        workbench = create_workbench(BaseWorkbench)
        commands = ["FreeCADPLM_ActivateConnection"]

        with patch("freecad_plm_addon.commands.register_commands", return_value=commands):
            workbench.Initialize()

        expected_toolbar = [
            "FreeCADPLM_ActivateConnection",
            "FreeCADPLM_Refresh",
            "Separator",
            "FreeCADPLM_Checkout",
            "FreeCADPLM_Checkin",
            "FreeCADPLM_CancelCheckout",
            "Separator",
            "FreeCADPLM_CreateAnnotation",
            "FreeCADPLM_OpenInSlicer",
            "FreeCADPLM_OpenDeepLink",
        ]
        self.assertEqual(workbench.toolbar, ("FreeCAD-PLM", expected_toolbar))
        self.assertEqual(workbench.menu[0], "FreeCAD-PLM")
        self.assertIn("Separator", workbench.menu[1])
        self.assertIn("FreeCADPLM_SetupProtocolHandler", workbench.menu[1])
        self.assertNotIn("FreeCADPLM_SetupProtocolHandler", workbench.toolbar[1])
