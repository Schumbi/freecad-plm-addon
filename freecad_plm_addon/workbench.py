from pathlib import Path


class FreeCADPLMWorkbenchMixin:
    MenuText = "FreeCAD-PLM Connector"
    ToolTip = "FreeCAD-PLM Connector Workbench"
    Icon = str(Path(__file__).resolve().parent / "icons" / "activate-connection.svg")

    def Initialize(self):
        from .commands import register_commands

        commands = register_commands()
        toolbar_commands = [
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
        menu_commands = [
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
            "Separator",
            "FreeCADPLM_SetupProtocolHandler",
        ]
        self.appendToolbar("FreeCAD-PLM Connector", toolbar_commands)
        self.appendMenu("FreeCAD-PLM Connector", menu_commands)

    def Activated(self):
        pass

    def Deactivated(self):
        pass

    def GetClassName(self):
        return "Gui::PythonWorkbench"


def create_workbench(base_class=None):
    if base_class is None:
        return FreeCADPLMWorkbenchMixin()

    class FreeCADPLMWorkbench(FreeCADPLMWorkbenchMixin, base_class):
        pass

    return FreeCADPLMWorkbench()
