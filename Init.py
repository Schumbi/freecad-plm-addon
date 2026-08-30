"""FreeCAD module entrypoint for FreeCAD-PLM."""

import FreeCAD


# FreeCAD's built-in single-instance mechanism forwards filesystem paths.  The
# operating-system URL handler therefore creates a one-shot .FCPLMLink file.
FreeCAD.addImportType(
    "FreeCAD-PLM-Link (*.FCPLMLink)",
    "freecad_plm_addon.link_import",
)
