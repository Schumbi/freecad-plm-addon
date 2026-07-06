import sys
import types
import unittest
from unittest.mock import Mock

from freecad_plm_addon import fcstd


class FakeDocument:
    def __init__(self, name="Doc"):
        self.Name = name
        self.recompute = Mock()
        self.save = Mock()


class FCStdTests(unittest.TestCase):
    def tearDown(self):
        sys.modules.pop("FreeCAD", None)
        sys.modules.pop("FreeCADGui", None)

    def test_open_document_recomputes_and_updates_gui(self):
        document = FakeDocument("Assembly")
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
        document = FakeDocument("Part")
        freecad = types.SimpleNamespace(openDocument=Mock(return_value=document))
        sys.modules["FreeCAD"] = freecad

        fcstd.open_document("/tmp/part.FCStd", recompute=False)

        document.recompute.assert_not_called()

    def test_document_names_uses_freecad_list_documents(self):
        freecad = types.SimpleNamespace(listDocuments=Mock(return_value={"A": object(), "B": object()}))
        sys.modules["FreeCAD"] = freecad

        self.assertEqual(fcstd.document_names(), {"A", "B"})

    def test_opened_document_names_includes_new_and_root_document(self):
        root = FakeDocument("Root")
        freecad = types.SimpleNamespace(listDocuments=Mock(return_value={"Old": object(), "Ref": object()}))
        sys.modules["FreeCAD"] = freecad

        self.assertEqual(fcstd.opened_document_names({"Old"}, root), ["Ref", "Root"])

    def test_close_documents_only_closes_known_names(self):
        freecad = types.SimpleNamespace(
            listDocuments=Mock(return_value={"A": object(), "B": object()}),
            closeDocument=Mock(),
        )
        sys.modules["FreeCAD"] = freecad

        closed, failed = fcstd.close_documents(["A", "Missing"])

        self.assertEqual(closed, ["A"])
        self.assertEqual(failed, [])
        freecad.closeDocument.assert_called_once_with("A")

    def test_save_documents_only_saves_known_names(self):
        document = FakeDocument("A")
        freecad = types.SimpleNamespace(
            listDocuments=Mock(return_value={"A": document, "B": FakeDocument("B")}),
        )
        sys.modules["FreeCAD"] = freecad

        saved, failed = fcstd.save_documents(["A", "Missing"])

        self.assertEqual(saved, ["A"])
        self.assertEqual(failed, [])
        document.save.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
