import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch
from zipfile import ZipFile

from freecad_plm_addon.panel import PLMPanel
from freecad_plm_addon.slicer import (
    read_3mf_sources,
    revision_sources,
    write_3mf_sources,
    write_sync_state,
)
from freecad_plm_addon.workspace import sha256_file


class PanelSlicerTests(unittest.TestCase):
    def setUp(self):
        self.context = ExitStack()
        self.addCleanup(self.context.close)
        self.directory = Path(self.context.enter_context(tempfile.TemporaryDirectory()))
        self.target = self.directory / "project.3mf"
        self.write_mesh(None, self.target)
        self.manifest = {
            "project": {"id": 15},
            "files": [
                {"path": "Druck.FCStd", "revision_id": 183, "sha256": "a" * 64, "is_root": True},
                {"path": "Deckel.FCStd", "revision_id": 187, "sha256": "b" * 64},
            ],
        }
        self.panel = Mock()
        self.panel.selected_project.return_value = {"id": 15, "code": "RODELN"}
        self.panel.selected_part.return_value = {"id": 48, "number": "A-001"}
        self.panel.selected_revision.return_value = {"id": 183, "file_format": "fcstd"}
        self.panel.workspace_root.text.return_value = str(self.directory)
        self.panel.server_url.text.return_value = "https://plm.example"
        self.panel.slicer_kind = "bambu"
        self.monitor = Mock()
        self.panel.slicer_monitors = {str(self.target): self.monitor}
        self.client = self.panel.client.return_value
        self.client.base_url = "https://plm.example"
        self.client.get_revision_manifest.return_value = self.manifest
        self.patch("slicer_project_dir", return_value=self.directory)
        self.patch("slicer_project_filename", return_value=self.target.name)
        self.patch("resolve_slicer_command", return_value=["bambu-studio"])
        self.patch("download_manifest_files")
        self.export = self.patch("export_revision_to_3mf", side_effect=self.write_mesh)
        self.launch = self.patch("launch_slicer")
        self.patch("SlicerProjectMonitor")

    def patch(self, name, **kwargs):
        return self.context.enter_context(patch(f"freecad_plm_addon.slicer.{name}", **kwargs))

    def write_mesh(self, source, output):
        with ZipFile(output, "w") as archive:
            archive.writestr("3D/3dmodel.model", "<model><triangle /></model>")

    def set_sources(self, revision_id=None):
        if revision_id is not None:
            sources = revision_sources(self.manifest, 183, self.client.base_url)
            sources["files"][0]["revision_id"] = revision_id
            write_3mf_sources(self.target, sources)
        digest = sha256_file(self.target)
        write_sync_state(self.target, {"server_sha256": digest})
        self.client.get_print_projects.return_value = [{
            "id": 8, "primary_revision_id": 183, "code": "DP-183",
            "slicer_project": {"id": 10, "sha256": digest},
        }]

    def test_changed_dependency_can_be_rebuilt_with_backup(self):
        self.set_sources(186)
        original = self.target.read_bytes()
        self.panel.choose_slicer_geometry_action.return_value = "rebuild"
        PLMPanel.open_selected_revision_in_slicer(self.panel)
        self.panel.choose_slicer_geometry_action.assert_called_once_with("changed", False)
        self.export.assert_called_once()
        self.launch.assert_called_once()
        self.assertEqual(read_3mf_sources(self.target)["files"][0]["revision_id"], 187)
        backups = list(self.directory.glob("backups/*/project.3mf"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), original)
        self.monitor.pause.assert_called_once()
        self.monitor.stop.assert_called_once()
        self.monitor.resume.assert_not_called()

    def test_current_sources_open_without_warning_and_manual_rebuild_confirms(self):
        for force in (False, True):
            with self.subTest(force=force):
                self.panel.choose_slicer_geometry_action.reset_mock()
                self.export.reset_mock()
                self.set_sources(187)
                self.panel.choose_slicer_geometry_action.return_value = "rebuild"
                PLMPanel.open_selected_revision_in_slicer(self.panel, force_rebuild=force)
                if force:
                    self.panel.choose_slicer_geometry_action.assert_called_once_with("current", True)
                    self.export.assert_called_once()
                else:
                    self.panel.choose_slicer_geometry_action.assert_not_called()
                    self.export.assert_not_called()

    def test_legacy_project_can_be_kept_without_relabeling_sources(self):
        self.set_sources()
        original = self.target.read_bytes()
        self.panel.choose_slicer_geometry_action.return_value = "keep"
        PLMPanel.open_selected_revision_in_slicer(self.panel)
        self.panel.choose_slicer_geometry_action.assert_called_once_with("unknown", False)
        self.export.assert_not_called()
        self.launch.assert_called_once()
        self.assertEqual(self.target.read_bytes(), original)
        self.assertIsNone(read_3mf_sources(self.target))

    def test_cancel_preserves_project_and_resumes_monitor(self):
        self.set_sources(186)
        original = self.target.read_bytes()
        self.panel.choose_slicer_geometry_action.return_value = "cancel"
        PLMPanel.open_selected_revision_in_slicer(self.panel)
        self.export.assert_not_called()
        self.launch.assert_not_called()
        self.assertEqual(self.target.read_bytes(), original)
        self.monitor.resume.assert_called_once()
        self.monitor.stop.assert_not_called()

    def test_export_failure_preserves_project_without_launching_or_uploading(self):
        self.set_sources(186)
        original = self.target.read_bytes()
        self.panel.choose_slicer_geometry_action.return_value = "rebuild"
        self.export.side_effect = RuntimeError("export failed")
        PLMPanel.open_selected_revision_in_slicer(self.panel)
        self.launch.assert_not_called()
        self.panel._sync_slicer_project_path.assert_not_called()
        self.assertEqual(self.target.read_bytes(), original)
        self.monitor.resume.assert_called_once()

    def test_window_close_and_escape_cancel_instead_of_rebuilding(self):
        box = self.panel.QtWidgets.QMessageBox.return_value
        rebuild, keep, cancel = Mock(), Mock(), Mock()
        box.addButton.side_effect = [rebuild, keep, cancel]
        box.clickedButton.return_value = None
        self.assertEqual(PLMPanel.choose_slicer_geometry_action(self.panel, "unknown"), "cancel")
        box.setDefaultButton.assert_called_once_with(cancel)


if __name__ == "__main__":
    unittest.main()
