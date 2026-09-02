import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZipFile

from freecad_plm_addon.errors import EmptyGeometryError, WorkspaceError
from freecad_plm_addon.slicer import (
    detect_slicer,
    export_revision_manifest_to_3mf,
    export_revision_manifest_to_stl,
    flatpak_cli_command,
    launch_slicer,
    parse_extra_args,
    reconcile_slicer_project,
    read_sync_state,
    resolve_slicer_command,
    select_export_objects,
    slicer_project_dir,
    slicer_project_filename,
    validate_3mf,
    write_sync_state,
)


class SlicerTests(unittest.TestCase):
    class ExportObject:
        def __init__(self, *, visible=True, parent=None, shape=False, mesh=False):
            self.ViewObject = SimpleNamespace(Visibility=visible)
            self._parent = parent
            if shape:
                self.Shape = object()
            if mesh:
                self.Mesh = object()

        def getParentGeoFeatureGroup(self):
            return self._parent

    def test_detects_binary_and_flatpak_without_shell(self):
        detected = detect_slicer(
            "auto", which=lambda name: "/usr/bin/orca-slicer" if name == "orca-slicer" else None
        )
        self.assertEqual(detected["kind"], "orca")
        self.assertEqual(detected["command"], ["/usr/bin/orca-slicer"])

        detected = detect_slicer(
            "bambu",
            which=lambda _name: None,
            flatpak_apps={"com.bambulab.BambuStudio"},
        )
        self.assertEqual(
            detected["command"],
            ["flatpak", "run", "com.bambulab.BambuStudio"],
        )

    def test_detects_known_macos_and_windows_installations(self):
        mac = detect_slicer(
            "orca",
            which=lambda _name: None,
            platform_name="Darwin",
            path_exists=lambda path: str(path).endswith(
                "OrcaSlicer.app/Contents/MacOS/OrcaSlicer"
            ),
        )
        self.assertIn("OrcaSlicer.app", mac["command"][0])

        windows = detect_slicer(
            "bambu",
            which=lambda _name: None,
            platform_name="Windows",
            environ={"ProgramFiles": "C:/Program Files"},
            path_exists=lambda path: str(path).endswith("Bambu Studio/bambu-studio.exe"),
        )
        self.assertIn("bambu-studio.exe", windows["command"][0])

    def test_uses_flatpak_spawn_from_inside_freecad_flatpak(self):
        def which(name):
            return "/usr/bin/flatpak-spawn" if name == "flatpak-spawn" else None

        with patch("shutil.which", side_effect=which):
            self.assertEqual(
                flatpak_cli_command(),
                ["/usr/bin/flatpak-spawn", "--host", "flatpak"],
            )

        detected = detect_slicer(
            "bambu",
            which=lambda _name: None,
            flatpak_apps={"com.bambulab.BambuStudio"},
            flatpak_command=["/usr/bin/flatpak-spawn", "--host", "flatpak"],
        )
        self.assertEqual(
            detected["command"],
            [
                "/usr/bin/flatpak-spawn",
                "--host",
                "flatpak",
                "run",
                "com.bambulab.BambuStudio",
            ],
        )

    def test_parses_json_or_display_friendly_args(self):
        self.assertEqual(parse_extra_args('["--foo", "two words"]'), ["--foo", "two words"])
        self.assertEqual(parse_extra_args('--foo "two words"'), ["--foo", "two words"])
        with self.assertRaises(WorkspaceError):
            parse_extra_args('{"unsafe": true}')

    def test_custom_command_and_project_path(self):
        self.assertEqual(
            resolve_slicer_command("auto", "/opt/Bambu Studio", '["--flag"]'),
            ["/opt/Bambu Studio", "--flag"],
        )
        path = slicer_project_dir("~/PLM", "https://plm.example", "P7", 12)
        self.assertTrue(str(path).endswith("plm-example/P7/slicer-projects/revision-12"))
        self.assertEqual(
            slicer_project_filename("P7", "A 1", "R0002"),
            "P7_A_1_R0002.3mf",
        )

    def test_state_is_atomic_and_contains_no_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "part.3mf"
            state = {"revision_id": 4, "server_sha256": "a" * 64}
            write_sync_state(project, state)
            self.assertEqual(read_sync_state(project), state)
            self.assertFalse(any(Path(tmp).glob("*.tmp")))

    def test_validates_and_launches_3mf_as_argument_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "part.3mf"
            with ZipFile(project, "w") as archive:
                archive.writestr(
                    "3D/3dmodel.model",
                    "<model><resources><object><mesh><triangles>"
                    "<triangle v1='0' v2='1' v3='2' />"
                    "</triangles></mesh></object></resources></model>",
                )
            self.assertEqual(validate_3mf(project), project)
            with patch("subprocess.Popen") as popen:
                argv = launch_slicer(project, ["orca-slicer", "--flag"])
            self.assertEqual(argv, ["orca-slicer", "--flag", str(project)])
            popen.assert_called_once_with(argv, start_new_session=True)

    def test_rejects_invalid_3mf(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.3mf"
            path.write_bytes(b"not a zip")
            with self.assertRaises(WorkspaceError):
                validate_3mf(path)

    def test_rejects_geometryless_3mf(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty.3mf"
            with ZipFile(path, "w") as archive:
                archive.writestr("3D/3dmodel.model", "<model><resources /></model>")
            with self.assertRaises(EmptyGeometryError):
                validate_3mf(path)

    def test_manifest_export_downloads_dependencies_and_uses_root(self):
        class FakeClient:
            def __init__(self):
                self.downloaded = []

            def get_revision_manifest(self, revision_id):
                self.revision_id = revision_id
                digest = hashlib.sha256(b"fcstd").hexdigest()
                return {
                    "files": [
                        {
                            "path": "project/Assembly.FCStd",
                            "is_root": True,
                            "download_url": "https://plm/root",
                            "sha256": digest,
                        },
                        {
                            "path": "project/Part.FCStd",
                            "is_root": False,
                            "download_url": "https://plm/part",
                            "sha256": digest,
                        },
                    ]
                }

            def download_revision_file(self, url, target_path, _sha256):
                self.downloaded.append((url, Path(target_path)))
                Path(target_path).parent.mkdir(parents=True, exist_ok=True)
                Path(target_path).write_bytes(b"fcstd")

        def fake_export(source_path, target_path):
            self.assertEqual(source_path.name, "Assembly.FCStd")
            self.assertTrue(source_path.with_name("Part.FCStd").is_file())
            with ZipFile(target_path, "w") as archive:
                archive.writestr(
                    "3D/3dmodel.model",
                    "<model><resources><object><mesh><triangles>"
                    "<triangle v1='0' v2='1' v3='2' />"
                    "</triangles></mesh></object></resources></model>",
                )

        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClient()
            target = Path(tmp) / "result.3mf"
            with patch(
                "freecad_plm_addon.slicer.export_revision_to_3mf",
                side_effect=fake_export,
            ):
                export_revision_manifest_to_3mf(
                    client, 147, Path(tmp) / "source", target
                )

            self.assertEqual(client.revision_id, 147)
            self.assertEqual(len(client.downloaded), 2)
            self.assertEqual(validate_3mf(target), target)

    def test_manifest_stl_export_downloads_dependencies_and_uses_root(self):
        class FakeClient:
            def get_revision_manifest(self, revision_id):
                self.revision_id = revision_id
                digest = hashlib.sha256(b"fcstd").hexdigest()
                return {
                    "files": [
                        {
                            "path": "project/Scheibe.FCStd",
                            "is_root": True,
                            "download_url": "https://plm/scheibe",
                            "sha256": digest,
                        }
                    ]
                }

            def download_revision_file(self, _url, target_path, _sha256):
                Path(target_path).parent.mkdir(parents=True, exist_ok=True)
                Path(target_path).write_bytes(b"fcstd")

        def fake_export(source_path, target_path):
            self.assertEqual(source_path.name, "Scheibe.FCStd")
            Path(target_path).write_bytes(b"solid scheibe\nendsolid\n")

        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClient()
            target = Path(tmp) / "Scheibe.stl"
            with patch(
                "freecad_plm_addon.slicer.export_revision_to_stl",
                side_effect=fake_export,
            ):
                export_revision_manifest_to_stl(
                    client, 42, Path(tmp) / "source", target
                )

            self.assertEqual(client.revision_id, 42)
            self.assertEqual(target.read_bytes(), b"solid scheibe\nendsolid\n")

    def test_reconcile_never_silently_overwrites_parallel_changes(self):
        self.assertEqual(reconcile_slicer_project("", "", ""), "create")
        self.assertEqual(reconcile_slicer_project("local", "", ""), "upload")
        self.assertEqual(reconcile_slicer_project("same", "same", "same"), "current")
        self.assertEqual(reconcile_slicer_project("old", "old", "new"), "download")
        self.assertEqual(reconcile_slicer_project("local", "old", "old"), "upload")
        self.assertEqual(reconcile_slicer_project("local", "old", "new"), "conflict")

    def test_export_selects_body_without_visible_tip_duplicate(self):
        body = self.ExportObject(shape=True)
        tip = self.ExportObject(parent=body, shape=True)

        self.assertEqual(select_export_objects([body, tip]), [body])

    def test_export_keeps_independent_geometry_and_visible_child(self):
        hidden_body = self.ExportObject(visible=False, shape=True)
        visible_tip = self.ExportObject(parent=hidden_body, shape=True)
        step_part = self.ExportObject(shape=True)
        stl_mesh = self.ExportObject(mesh=True)

        self.assertEqual(
            select_export_objects([hidden_body, visible_tip, step_part, stl_mesh]),
            [visible_tip, step_part, stl_mesh],
        )


if __name__ == "__main__":
    unittest.main()
