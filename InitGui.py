"""FreeCAD GUI entrypoint for FreeCAD-PLM."""

import FreeCADGui

from freecad_plm_addon.deeplink_runtime import install_deep_link_runtime
from freecad_plm_addon.protocol_handler import register_protocol_handler
from freecad_plm_addon.workbench import FreeCADPLMWorkbenchMixin


_WorkbenchBase = globals().get("Workbench")

if _WorkbenchBase is None:
    class FreeCADPLMWorkbench(FreeCADPLMWorkbenchMixin):
        pass
else:
    class FreeCADPLMWorkbench(FreeCADPLMWorkbenchMixin, _WorkbenchBase):
        pass


FreeCADGui.addWorkbench(FreeCADPLMWorkbench())
try:
    install_deep_link_runtime()
    _protocol_result = register_protocol_handler()
    if not _protocol_result.success:
        raise RuntimeError(_protocol_result.message)
except Exception as exc:
    try:
        import FreeCAD

        FreeCAD.Console.PrintWarning(f"FreeCAD-PLM Weblink-Handler: {exc}\n")
    except (ImportError, AttributeError):
        pass
