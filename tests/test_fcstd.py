import sys
import types
import unittest
from unittest.mock import Mock

from freecad_plm_addon import fcstd


class FCStdTests(unittest.TestCase):
    def tearDown(self):
        sys.modules.pop("FreeCAD", None)
        sys.modules.pop("FreeCADGui", None)

    def test_open_document_recomputes_and_updates_gui(self):
        document = Mock()
        freecad = types.SimpleNamespace(openDocument=Mock(return_value=document))
        freecad_gui = types.SimpleNamespace(updateGui=Mock())
        sys.modules["FreeCAD"] = freecad
        sys.modules["FreeCADGui"] = freecad_gui

        result = fcstd.open_document("/tmp/assembly.FCStd")

        self.assertIs(result, document)
        freecad.openDocument.assert_called_once_with("/tmp/assembly.FCStd")
        document.recompute.assert_called_once_with()
        freecad_gui.updateGui.assert_called_once_with()

    def test_open_document_can_skip_recompute(self):
        document = Mock()
        freecad = types.SimpleNamespace(openDocument=Mock(return_value=document))
        sys.modules["FreeCAD"] = freecad

        fcstd.open_document("/tmp/part.FCStd", recompute=False)

        document.recompute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
