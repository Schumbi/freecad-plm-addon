import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from freecad_plm_addon import import_directory as importer
from freecad_plm_addon.errors import APIError


def write(path: Path, data: bytes = b"x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


class ImportDirectoryScanTests(unittest.TestCase):
    def make_tree(self, root: Path) -> None:
        write(root / "Assembly.FCStd", b"assembly")
        write(root / "Parts" / "Box.FCStd", b"box")
        write(root / "Parts" / "cover.step", b"step")
        write(root / "notes.pdf", b"pdf")
        write(root / ".git" / "config", b"git")
        write(root / "__pycache__" / "module.pyc", b"pyc")
        write(root / ".~lock.notes.pdf#", b"lock")
        write(root / "checkout.json", b"{}")
        write(root / "Assembly.FCStd1", b"backup")

    def test_scan_collects_cad_and_documents_and_skips_junk(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_tree(root)

            scan = importer.scan_directory(root)

            self.assertEqual(
                [item.relative_path for item in scan.files],
                [
                    "Assembly.FCStd",
                    "Parts/Box.FCStd",
                    "Parts/cover.step",
                    "notes.pdf",
                ],
            )
            self.assertEqual(len(scan.fcstd_files), 2)
            self.assertEqual(len(scan.external_files), 1)
            self.assertEqual(len(scan.document_files), 1)
            self.assertEqual(scan.total_size, len(b"assembly") + len(b"box") + len(b"step") + len(b"pdf"))
            self.assertIn(".git", scan.pruned_dirs)
            self.assertIn("__pycache__", scan.pruned_dirs)
            self.assertGreaterEqual(scan.excluded_files, 3)

    def test_scan_cad_only_omits_documents(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_tree(root)

            scan = importer.scan_directory(root, include_documents=False)

            self.assertEqual([item.kind for item in scan.files], ["fcstd", "fcstd", "external"])
            self.assertEqual(scan.omitted_documents, 1)

    def test_scan_skips_symlinks(self):
        if os.name == "nt":
            self.skipTest("Symlink-Test wird unter Windows übersprungen.")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root / "Assembly.FCStd", b"assembly")
            try:
                (root / "Linked.FCStd").symlink_to(root / "Assembly.FCStd")
            except OSError as exc:
                self.skipTest(f"Symlinks nicht verfügbar: {exc}")

            scan = importer.scan_directory(root)

            self.assertEqual([item.relative_path for item in scan.files], ["Assembly.FCStd"])
            self.assertEqual(scan.skipped_symlinks, 1)

    def test_scan_requires_existing_directory(self):
        with self.assertRaises(importer.ImportValidationError):
            importer.scan_directory("/pfad/gibt/es/nicht")


class ImportDirectoryValidationTests(unittest.TestCase):
    def scan_with(self, root: Path, relative: str = "Assembly.FCStd", kind: str = "fcstd") -> importer.ImportScan:
        path = root / relative
        write(path)
        return importer.ImportScan(
            folder=root,
            files=[importer.ImportFile(path=path, relative_path=relative, size=path.stat().st_size, kind=kind)],
        )

    def test_validation_requires_fcstd(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root / "notes.pdf")
            scan = importer.scan_directory(root)
            with self.assertRaises(importer.ImportValidationError) as raised:
                importer.validate_scan(scan)
            self.assertIn("keine .FCStd-Datei", str(raised.exception))

    def test_validation_rejects_member_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scan = self.scan_with(root)
            limits = importer.ScanLimits(max_members=0)
            with self.assertRaises(importer.ImportValidationError) as raised:
                importer.validate_scan(scan, limits)
            self.assertIn("Zu viele Dateien", str(raised.exception))

    def test_validation_rejects_large_member(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scan = self.scan_with(root)
            limits = importer.ScanLimits(max_member_bytes=0)
            with self.assertRaises(importer.ImportValidationError) as raised:
                importer.validate_scan(scan, limits)
            self.assertIn("Datei zu groß", str(raised.exception))

    def test_validation_rejects_oversized_zip_estimate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scan = self.scan_with(root)
            limits = importer.ScanLimits(max_zip_bytes=1)
            with self.assertRaises(importer.ImportValidationError) as raised:
                importer.validate_scan(scan, limits)
            self.assertIn("ZIP-Upload", str(raised.exception))


class DependencyRootTests(unittest.TestCase):
    def make_scan(self, root: Path, names: list[str], external: bool = True) -> importer.ImportScan:
        files = []
        for name in names:
            path = root / name
            write(path)
            files.append(importer.ImportFile(path=path, relative_path=name, size=1, kind="fcstd"))
        if external:
            path = root / "part.step"
            write(path)
            files.append(importer.ImportFile(path=path, relative_path="part.step", size=1, kind="external"))
        return importer.ImportScan(folder=root, files=files)

    def test_single_fcstd_is_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            scan = self.make_scan(Path(tmp), ["Assembly.FCStd"])
            self.assertEqual(importer.resolve_dependency_root(scan), "Assembly.FCStd")

    def test_multiple_fcstd_require_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            scan = self.make_scan(Path(tmp), ["A.FCStd", "B.FCStd"])
            with self.assertRaises(importer.DependencyRootRequired) as raised:
                importer.resolve_dependency_root(scan)
            self.assertEqual(raised.exception.candidates, ("A.FCStd", "B.FCStd"))

    def test_requested_root_is_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            scan = self.make_scan(Path(tmp), ["A.FCStd", "B.FCStd"])
            self.assertEqual(importer.resolve_dependency_root(scan, "B.FCStd"), "B.FCStd")
            with self.assertRaises(importer.ImportValidationError):
                importer.resolve_dependency_root(scan, "C.FCStd")

    def test_without_external_files_no_root_is_needed(self):
        with tempfile.TemporaryDirectory() as tmp:
            scan = self.make_scan(Path(tmp), ["A.FCStd"], external=False)
            self.assertEqual(importer.resolve_dependency_root(scan), "")

    def test_external_without_fcstd_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root / "part.step")
            scan = importer.ImportScan(
                folder=root,
                files=[importer.ImportFile(root / "part.step", "part.step", 1, "external")],
            )
            with self.assertRaises(importer.ImportValidationError) as raised:
                importer.resolve_dependency_root(scan)
            self.assertIn("keine .FCStd-Datei", str(raised.exception))


class ZipBuilderTests(unittest.TestCase):
    def test_zip_preserves_relative_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root / "Assembly.FCStd", b"assembly")
            write(root / "Parts" / "Box.FCStd", b"box")
            scan = importer.scan_directory(root)
            target = root / "out" / "import.zip"

            importer.build_import_zip(scan, target)

            with ZipFile(target) as archive:
                self.assertEqual(
                    archive.namelist(),
                    ["Assembly.FCStd", "Parts/Box.FCStd"],
                )
                self.assertEqual(archive.read("Parts/Box.FCStd"), b"box")


class CodeTests(unittest.TestCase):
    def test_code_is_transliterated_and_uppercase(self):
        self.assertEqual(
            importer.derive_project_code("Prüfbericht Übung 2026"),
            "PRUEFBERICHT-UEBUNG-2026",
        )

    def test_code_is_limited_to_40_characters(self):
        code = importer.derive_project_code("x" * 100)
        self.assertLessEqual(len(code), 40)

    def test_empty_name_gets_fallback(self):
        self.assertTrue(importer.derive_project_code("!!!").startswith("PROJEKT-"))

    def test_next_available_code(self):
        self.assertEqual(importer.next_available_code("ABC", []), "ABC")
        self.assertEqual(importer.next_available_code("ABC", ["ABC"]), "ABC-2")
        self.assertEqual(importer.next_available_code("ABC", ["ABC", "ABC-2"]), "ABC-3")

    def test_validate_project_values(self):
        code, name, snapshot = importer.validate_project_values(" test ", " Name ", "")
        self.assertEqual((code, name, snapshot), ("TEST", "Name", "Initial"))
        with self.assertRaises(importer.ImportValidationError):
            importer.validate_project_values("TEST", "Name", "", existing_codes=["TEST"])
        with self.assertRaises(importer.ImportValidationError):
            importer.validate_project_values("", "Name", "Initial")
        with self.assertRaises(importer.ImportValidationError):
            importer.validate_project_values("TEST", "x" * 201, "Initial")


class ConfigTests(unittest.TestCase):
    def test_read_freecad_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "user.cfg"
            path.write_text(
                """<?xml version="1.0" encoding="utf-8"?>
<FCConfig>
  <FCParamGroup Name="BaseApp">
    <FCParamGroup Name="Preferences">
      <FCParamGroup Name="Mod">
        <FCParamGroup Name="FreeCADPLM">
          <FCText Name="server_url">https://plm.example</FCText>
          <FCText Name="api_token">test-token</FCText>
        </FCParamGroup>
      </FCParamGroup>
    </FCParamGroup>
  </FCParamGroup>
</FCConfig>
""",
                encoding="utf-8",
            )
            self.assertEqual(
                importer.read_freecad_config(path),
                {"server_url": "https://plm.example", "api_token": "test-token"},
            )

    def test_json_config_is_loaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "server_url": "https://plm.example",
                        "api_token": "test-token",
                        "exclude_patterns": ["*.tmp"],
                    }
                ),
                encoding="utf-8",
            )
            config = importer.load_plm_config(path)
            self.assertEqual(config.server_url, "https://plm.example")
            self.assertEqual(config.api_token, "test-token")
            self.assertIn("*.tmp", config.exclude_patterns)
            self.assertIn("checkout.json", config.exclude_patterns)


class ZenityParsingTests(unittest.TestCase):
    def scan(self) -> importer.ImportScan:
        return importer.ImportScan(
            folder=Path("/tmp"),
            files=[
                importer.ImportFile(Path("/tmp/A.FCStd"), "A.FCStd", 1, "fcstd"),
            ],
        )

    def test_step_one_parsing(self):
        with patch.object(
            importer,
            "run_zenity",
            return_value="Neues Projekt|Nur CAD-Dateien|Ja",
        ):
            self.assertEqual(
                importer.ask_import_options(self.scan(), projects=[]),
                ("Neues Projekt", True, True),
            )

    def test_step_one_can_default_to_cad_only(self):
        captured = {}

        def fake_run(args, **kwargs):
            captured["args"] = args
            return "Neues Projekt|Nur CAD-Dateien|Nein"

        with patch.object(importer, "run_zenity", side_effect=fake_run):
            importer.ask_import_options(
                self.scan(), projects=[], default_cad_only=True
            )
        self.assertIn("--combo-values=Nur CAD-Dateien|Alle Dateien", captured["args"])

    def test_new_project_defaults_from_empty_fields(self):
        with patch.object(importer, "run_zenity", return_value="|||"):
            self.assertEqual(
                importer.ask_new_project_details(
                    self.scan(),
                    suggested_code="CODE",
                    suggested_name="Name",
                    existing_codes=[],
                ),
                ("CODE", "Name", "Initial", ""),
            )

    def test_existing_project_parsing(self):
        projects = [{"id": 7, "code": "CODE", "name": "Name"}]
        with patch.object(importer, "run_zenity", return_value="CODE – Name|Import"):
            self.assertEqual(
                importer.ask_existing_project_details(self.scan(), projects=projects),
                (7, "Import"),
            )

    def test_dependency_root_parsing(self):
        with patch.object(importer, "run_zenity", return_value="B.FCStd"):
            self.assertEqual(
                importer.ask_dependency_root(["A.FCStd", "B.FCStd"]),
                "B.FCStd",
            )

    def test_cancel_returns_none(self):
        with patch.object(importer, "run_zenity", return_value=None):
            self.assertIsNone(importer.ask_import_options(self.scan(), projects=[]))


class ImportCallTests(unittest.TestCase):
    def test_new_project_upload_uses_expected_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root / "Assembly.FCStd", b"assembly")
            scan = importer.scan_directory(root)
            captured = {}

            class FakeClient:
                def import_project(self, zip_path, project_data, snapshot_name, dependency_root_path=""):
                    captured.update(
                        zip_path=Path(zip_path),
                        project_data=project_data,
                        snapshot_name=snapshot_name,
                        dependency_root_path=dependency_root_path,
                    )
                    with ZipFile(zip_path) as archive:
                        captured["members"] = archive.namelist()
                    return {"project": {"id": 1, "code": "CODE", "name": "Name"}}

            result = importer.import_directory(
                scan,
                client=FakeClient(),
                mode="new",
                code="CODE",
                name="Name",
                snapshot="Initial",
            )
            self.assertEqual(result["project"]["id"], 1)
            self.assertEqual(captured["project_data"]["code"], "CODE")
            self.assertEqual(captured["snapshot_name"], "Initial")
            self.assertEqual(captured["members"], ["Assembly.FCStd"])

    def test_existing_project_uses_snapshot_endpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root / "Assembly.FCStd", b"assembly")
            scan = importer.scan_directory(root)
            captured = {}

            class FakeClient:
                def import_project_snapshot(self, project_id, zip_path, snapshot_name, dependency_root_path=""):
                    captured.update(project_id=project_id, snapshot=snapshot_name)
                    return {"project": {"id": project_id, "code": "CODE", "name": "Name"}}

            importer.import_directory(
                scan,
                client=FakeClient(),
                mode="existing",
                project_id=9,
                snapshot="Import",
            )
            self.assertEqual(captured, {"project_id": 9, "snapshot": "Import"})

    def test_api_errors_are_propagated(self):
        class FailingClient:
            def import_project(self, *args, **kwargs):
                raise APIError(400, "Ungültige FCStd-Datei.")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root / "Assembly.FCStd", b"assembly")
            scan = importer.scan_directory(root)
            with self.assertRaises(APIError):
                importer.import_directory(
                    scan,
                    client=FailingClient(),
                    mode="new",
                    code="CODE",
                    name="Name",
                    snapshot="Initial",
                )


class DryRunTests(unittest.TestCase):
    def test_dry_run_prints_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root / "Assembly.FCStd", b"assembly")
            output = io.StringIO()
            with redirect_stdout(output):
                code = importer.main(["--dry-run", "--folder", str(root)])
            self.assertEqual(code, 0)
            self.assertIn("FCStd: 1", output.getvalue())
            self.assertIn("Ordner:", output.getvalue())


if __name__ == "__main__":
    unittest.main()
