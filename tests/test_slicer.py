import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from freecad_plm_addon.errors import WorkspaceError
from freecad_plm_addon.slicer import (
    detect_slicer,
    launch_slicer,
    parse_extra_args,
    reconcile_slicer_project,
    read_sync_state,
    resolve_slicer_command,
    slicer_project_dir,
    slicer_project_filename,
    validate_3mf,
    write_sync_state,
)


class SlicerTests(unittest.TestCase):
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
        self.assertEqual(slicer_project_filename("A 1", "R0002"), "A_1_R0002.3mf")

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
                archive.writestr("3D/3dmodel.model", "<model />")
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

    def test_reconcile_never_silently_overwrites_parallel_changes(self):
        self.assertEqual(reconcile_slicer_project("", "", ""), "create")
        self.assertEqual(reconcile_slicer_project("local", "", ""), "upload")
        self.assertEqual(reconcile_slicer_project("same", "same", "same"), "current")
        self.assertEqual(reconcile_slicer_project("old", "old", "new"), "download")
        self.assertEqual(reconcile_slicer_project("local", "old", "old"), "upload")
        self.assertEqual(reconcile_slicer_project("local", "old", "new"), "conflict")


if __name__ == "__main__":
    unittest.main()
