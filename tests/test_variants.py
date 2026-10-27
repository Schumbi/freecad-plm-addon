import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from zipfile import ZipFile

from freecad_plm_addon import fcstd
from freecad_plm_addon.api_client import PLMClient
from freecad_plm_addon.errors import WorkspaceError
from freecad_plm_addon.panel_parts import PanelPartsMixin
from freecad_plm_addon.workspace import checkout_dir, document_source_revision, write_manifest


class VariantTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.directory = checkout_dir(self.root, "https://plm.example", "BOX", 1)
        self.manifest = {
            "snapshot": {"id": 7},
            "files": [
                {"path": "Box.FCStd", "revision_id": 10, "reference_files": ["Chip.FCStd"]},
                {"path": "Chip.FCStd", "revision_id": 11, "reference_files": []},
            ],
        }
        write_manifest(self.directory, self.manifest)
        (self.directory / "files").mkdir()
        for item in self.manifest["files"]:
            (self.directory / "files" / item["path"]).write_bytes(b"original")

    def test_document_identity_comes_from_workspace_and_server(self):
        path = self.directory / "files/Chip.FCStd"
        self.assertEqual(document_source_revision(path, self.root, "https://plm.example"), 11)
        with self.assertRaises(WorkspaceError):
            document_source_revision(path, self.root, "https://other.example")
        with self.assertRaises(WorkspaceError):
            document_source_revision(self.directory / "files/unrelated.FCStd", self.root, "https://plm.example")

    def test_bundle_keeps_unsaved_parameters_and_recomputes_dependencies_first(self):
        events = []
        documents = {}
        for item in self.manifest["files"]:
            name = item["path"]
            doc = Mock(FileName=str(self.directory / "files" / name))
            doc.recompute.side_effect = lambda value=name: events.append(value)
            doc.saveCopy.side_effect = lambda target, value=name: Path(target).write_bytes(f"modified {value}".encode())
            documents[name] = doc
        with patch.dict("sys.modules", {"FreeCAD": types.SimpleNamespace(listDocuments=lambda: documents)}):
            path = fcstd.build_variant_bundle(self.manifest, self.directory, self.root / "variant.zip")
        self.assertEqual(events, ["Chip.FCStd", "Box.FCStd"])
        with ZipFile(path) as archive:
            self.assertEqual(archive.read("Chip.FCStd"), b"modified Chip.FCStd")
        for doc in documents.values():
            doc.save.assert_not_called()
            doc.saveAs.assert_not_called()
            self.assertEqual(Path(doc.FileName).read_bytes(), b"original")

    def test_bundle_retains_closed_dependencies_and_rejects_missing_file(self):
        with patch.dict("sys.modules", {"FreeCAD": types.SimpleNamespace(listDocuments=lambda: {})}):
            path = fcstd.build_variant_bundle(self.manifest, self.directory, self.root / "variant.zip")
            with ZipFile(path) as archive:
                self.assertEqual(archive.read("Chip.FCStd"), b"original")
            (self.directory / "files/Chip.FCStd").unlink()
            with self.assertRaises(ValueError):
                fcstd.build_variant_bundle(self.manifest, self.directory, self.root / "broken.zip")

    def test_save_copy_failure_is_not_uploaded(self):
        document = Mock()
        document.saveCopy.return_value = False
        with self.assertRaises(RuntimeError):
            fcstd.save_document_copy(document, self.root / "failed.FCStd")

    def test_windows_clears_ucrt_errno_immediately_before_save_copy(self):
        events = []
        document = Mock()
        document.recompute.side_effect = lambda: events.append("recompute")
        def save(target):
            events.append("saveCopy")
            Path(target).write_bytes(b"valid copy")
        document.saveCopy.side_effect = save
        with patch.object(fcstd, "sys", types.SimpleNamespace(platform="win32")), patch("ctypes.CDLL") as load_ucrt:
            load_ucrt.return_value._set_errno.side_effect = lambda value: events.append(f"errno={value}")
            target = fcstd.save_document_copy(document, self.root / "copy.FCStd")
            load_ucrt.assert_called_once_with("ucrtbase.dll")
            self.assertEqual(load_ucrt.return_value._set_errno.argtypes, [__import__("ctypes").c_int])
        self.assertEqual(events, ["recompute", "errno=0", "saveCopy"])
        self.assertEqual(target.read_bytes(), b"valid copy")

    def test_non_windows_save_copy_does_not_load_ucrt(self):
        document = Mock()
        document.saveCopy.side_effect = lambda target: Path(target).write_bytes(b"copy")
        with patch.object(fcstd, "sys", types.SimpleNamespace(platform="linux")), patch("ctypes.CDLL") as load_ucrt:
            result = fcstd.save_document_copy(document, self.root / "linux.FCStd")
            load_ucrt.assert_not_called()
        self.assertEqual(result.read_bytes(), b"copy")

    def test_save_copy_error_includes_path_and_original_cause(self):
        document = Mock()
        document.saveCopy.side_effect = OSError("disk full")
        target = self.root / "failed.FCStd"
        with self.assertRaisesRegex(RuntimeError, "failed.FCStd") as captured:
            fcstd.save_document_copy(document, target)
        self.assertIsInstance(captured.exception.__cause__, OSError)

    def test_client_sends_provenance_snapshot_and_no_source_checkout(self):
        client = PLMClient("https://plm.example", "token")
        with patch.object(client, "_multipart", return_value={}) as upload:
            client.create_variant(1, 10, {"name": "20 Chips"}, self.root / "variant.zip", source_snapshot_id=7)
        self.assertEqual(upload.call_args.args[0], "/api/projects/1/parts/create-fcstd/")
        self.assertEqual(upload.call_args.args[1]["source_revision_id"], 10)
        self.assertEqual(upload.call_args.args[1]["source_snapshot_id"], 7)
        self.assertNotIn("checkout_id", upload.call_args.args[1])

    def panel(self, allowed=True):
        panel = Mock()
        panel.workspace_root.text.return_value = str(self.root)
        panel.server_url.text.return_value = "https://plm.example"
        panel.selected_revision.return_value = {"id": 10}
        client = panel.client.return_value
        client.get_revision_manifest.return_value = self.manifest
        client.get_revision.return_value = {"id": 10, "part_id": 1, "revision_code": "R0001"}
        client.get_part.return_value = {"part": {"id": 1, "project_id": 1, "name": "Chipbox"}, "can_create_variant": allowed}
        client.get_project.return_value = {"id": 1, "code": "BOX"}
        client.create_variant.return_value = {"part": {"id": 2}, "revision": {"id": 12}}
        panel.QtWidgets.QDialog.Accepted = 1
        panel.QtWidgets.QDialog.return_value.exec_.return_value = 1
        panel.QtWidgets.QDialogButtonBox.Ok = 1
        panel.QtWidgets.QDialogButtonBox.Cancel = 2
        name = Mock()
        name.text.return_value = "20 Chips"
        number = Mock()
        number.text.return_value = ""
        panel.QtWidgets.QLineEdit.side_effect = [name, number]
        return panel

    def test_dialog_uses_selected_root_with_active_parameter_document(self):
        panel = self.panel()
        with patch.object(fcstd, "active_document_path", return_value=self.directory / "files/Chip.FCStd"), patch.object(fcstd, "build_variant_bundle", return_value=self.root / "variant.zip") as bundle:
            PanelPartsMixin.create_variant_dialog(panel)
        client = panel.client.return_value
        self.assertEqual(client.create_variant.call_args.args[:2], (1, 10))
        self.assertEqual(client.create_variant.call_args.kwargs["source_snapshot_id"], 7)
        bundle.assert_called_once()
        panel.open_checkout_response_to_workspace.assert_called_once_with(
            client.get_project.return_value, client.create_variant.return_value, preserve_readonly=True,
        )

    def test_dialog_checks_rights_before_copying_or_uploading(self):
        panel = self.panel(allowed=False)
        with patch.object(fcstd, "active_document_path", return_value=self.directory / "files/Chip.FCStd"), patch.object(fcstd, "build_variant_bundle") as bundle:
            PanelPartsMixin.create_variant_dialog(panel)
        bundle.assert_not_called()
        panel.client.return_value.create_variant.assert_not_called()
        panel.QtWidgets.QDialog.assert_not_called()
