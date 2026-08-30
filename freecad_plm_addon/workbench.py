from pathlib import Path


class FreeCADPLMWorkbenchMixin:
    MenuText = "FreeCAD-PLM"
    ToolTip = "FreeCAD-PLM Workbench"
    Icon = str(Path(__file__).resolve().parent / "icons" / "activate-connection.svg")

    def Initialize(self):
        from .commands import register_commands

        commands = register_commands()
        toolbar_commands = [
            command
            for command in commands
            if command != "FreeCADPLM_SetupProtocolHandler"
        ]
        self.appendToolbar("FreeCAD-PLM", toolbar_commands)
        self.appendMenu("FreeCAD-PLM", commands)

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
