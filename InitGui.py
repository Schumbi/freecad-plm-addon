"""FreeCAD GUI entrypoint for FreeCAD-PLM."""

import FreeCADGui

from freecad_plm_addon.workbench import create_workbench


FreeCADGui.addWorkbench(create_workbench(globals().get("Workbench")))
