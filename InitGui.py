"""FreeCAD GUI entrypoint for FreeCAD-PLM."""

import FreeCADGui

from freecad_plm_addon.workbench import FreeCADPLMWorkbench


FreeCADGui.addWorkbench(FreeCADPLMWorkbench())
