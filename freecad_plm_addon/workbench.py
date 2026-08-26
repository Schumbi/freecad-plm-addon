import sys
from pathlib import Path


_handled_deep_link = False


class FreeCADPLMWorkbenchMixin:
    MenuText = "FreeCAD-PLM"
    ToolTip = "FreeCAD-PLM Workbench"
    Icon = str(Path(__file__).resolve().parent / "icons" / "activate-connection.svg")

    def Initialize(self):
        from .commands import register_commands

        commands = register_commands()
        self.appendToolbar("FreeCAD-PLM", commands)
        self.appendMenu("FreeCAD-PLM", commands)

    def Activated(self):
        global _handled_deep_link
        if _handled_deep_link:
            return
        from .deeplink import deep_link_from_argv

        try:
            deep_link = deep_link_from_argv(sys.argv)
        except ValueError:
            deep_link = None
        if deep_link is None:
            return
        _handled_deep_link = True
        from .panel import open_revision_deep_link

        try:
            from PySide import QtCore
        except ImportError:
            from PySide2 import QtCore
        QtCore.QTimer.singleShot(0, lambda: open_revision_deep_link(deep_link))

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
