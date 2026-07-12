"""FreeCAD GUI entrypoint for FreeCAD-PLM."""

import FreeCADGui

from freecad_plm_addon.workbench import FreeCADPLMWorkbenchMixin


_WorkbenchBase = globals().get("Workbench")

if _WorkbenchBase is None:
    class FreeCADPLMWorkbench(FreeCADPLMWorkbenchMixin):
        pass
else:
    class FreeCADPLMWorkbench(FreeCADPLMWorkbenchMixin, _WorkbenchBase):
        pass


FreeCADGui.addWorkbench(FreeCADPLMWorkbench())
