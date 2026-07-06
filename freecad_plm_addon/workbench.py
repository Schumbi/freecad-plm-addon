class FreeCADPLMWorkbenchMixin:
    MenuText = "FreeCAD-PLM"
    ToolTip = "FreeCAD-PLM Workbench"

    def Initialize(self):
        from .commands import register_commands

        commands = register_commands()
        self.appendToolbar("FreeCAD-PLM", commands)
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
