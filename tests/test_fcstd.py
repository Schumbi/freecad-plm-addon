import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock

from freecad_plm_addon import fcstd


class FakeDocument:
    def __init__(self, name="Doc", modified=False, file_name=None):
        self.Name = name
        self.recompute = Mock()
        self.save = Mock()
        self.Modified = modified
        self.isModified = Mock(return_value=modified)
        self.FileName = file_name or f"/tmp/{name}.FCStd"


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

    def test_create_empty_document_saves_and_closes_temporary_document(self):
        document = FakeDocument("Unnamed")
        document.saveAs = Mock(side_effect=lambda path: Path(path).write_bytes(b"fcstd"))
        freecad = types.SimpleNamespace(
            newDocument=Mock(return_value=document),
            closeDocument=Mock(),
        )
        sys.modules["FreeCAD"] = freecad

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "Klebeschale.FCStd"
            result = fcstd.create_empty_document(target, "Klebeschale")

            self.assertEqual(result, target)
            self.assertEqual(target.read_bytes(), b"fcstd")
        self.assertEqual(document.Label, "Klebeschale")
        document.saveAs.assert_called_once()
        document.save.assert_called_once_with()
        freecad.closeDocument.assert_called_once_with("Unnamed")

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

    def test_document_is_modified_prefers_callable(self):
        modified = FakeDocument("A", modified=True)
        unmodified = FakeDocument("B", modified=False)

        self.assertTrue(fcstd.document_is_modified(modified))
        self.assertFalse(fcstd.document_is_modified(unmodified))

    def test_modified_document_names_filters_unmodified_documents(self):
        modified = FakeDocument("A", modified=True)
        unmodified = FakeDocument("B", modified=False)
        freecad = types.SimpleNamespace(
            listDocuments=Mock(return_value={"A": modified, "B": unmodified}),
        )
        sys.modules["FreeCAD"] = freecad

        self.assertEqual(fcstd.modified_document_names(["A", "B", "Missing"]), ["A"])

    def test_document_names_in_directory_filters_by_path(self):
        checkout_root = "/tmp/checkout/files"
        inside = FakeDocument("A", file_name="/tmp/checkout/files/A.FCStd")
        nested = FakeDocument("B", file_name="/tmp/checkout/files/sub/B.FCStd")
        outside = FakeDocument("C", file_name="/tmp/other/C.FCStd")
        freecad = types.SimpleNamespace(
            listDocuments=Mock(return_value={"A": inside, "B": nested, "C": outside}),
        )
        sys.modules["FreeCAD"] = freecad

        self.assertEqual(fcstd.document_names_in_directory(checkout_root), ["A", "B"])

    def test_document_names_for_path_matches_exact_file(self):
        target = FakeDocument("A", file_name="/tmp/checkout/files/A.FCStd")
        other = FakeDocument("B", file_name="/tmp/checkout/files/B.FCStd")
        freecad = types.SimpleNamespace(
            listDocuments=Mock(return_value={"A": target, "B": other}),
        )
        sys.modules["FreeCAD"] = freecad

        self.assertEqual(
            fcstd.document_names_for_path("/tmp/checkout/files/A.FCStd"),
            ["A"],
        )

    def test_active_document_name_in_directory_requires_checkout_path(self):
        document = FakeDocument("A", file_name="/tmp/checkout/files/A.FCStd")
        freecad = types.SimpleNamespace(
            listDocuments=Mock(return_value={"A": document}),
            ActiveDocument=document,
        )
        sys.modules["FreeCAD"] = freecad

        self.assertEqual(fcstd.active_document_name_in_directory("/tmp/checkout/files"), "A")

    def test_active_document_name_in_directory_rejects_other_paths(self):
        document = FakeDocument("A", file_name="/tmp/other/A.FCStd")
        freecad = types.SimpleNamespace(
            listDocuments=Mock(return_value={"A": document}),
            ActiveDocument=document,
        )
        sys.modules["FreeCAD"] = freecad

        self.assertEqual(fcstd.active_document_name_in_directory("/tmp/checkout/files"), "")


if __name__ == "__main__":
    unittest.main()
