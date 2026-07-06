import json
import tempfile
import unittest
from pathlib import Path

from freecad_plm_addon.errors import WorkspaceError
from freecad_plm_addon.workspace import (
    checkout_dir,
    read_manifest,
    readonly_revision_dir,
    resolve_reference_path,
    root_file_path,
    safe_join,
    safe_download_filename,
    server_slug,
    sha256_file,
    write_manifest,
)


class WorkspaceTests(unittest.TestCase):
    def test_safe_join_rejects_absolute_paths(self):
        with self.assertRaises(WorkspaceError):
            safe_join("/tmp/root", "/etc/passwd")

    def test_safe_join_rejects_parent_paths(self):
        with self.assertRaises(WorkspaceError):
            safe_join("/tmp/root", "../x.FCStd")

    def test_server_slug(self):
        self.assertEqual(server_slug("https://plm.lan.schumbi.de"), "plm-lan-schumbi-de")

    def test_manifest_roundtrip_and_root_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = {
                "files": [
                    {"path": "A.FCStd", "is_root": True},
                    {"path": "sub/B.FCStd", "is_root": False},
                ]
            }
            write_manifest(tmp, manifest)
            self.assertEqual(read_manifest(tmp), manifest)
            self.assertEqual(root_file_path(manifest, tmp), Path(tmp) / "files" / "A.FCStd")

    def test_sha256_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data.txt"
            path.write_text("abc", encoding="utf-8")
            self.assertEqual(
                sha256_file(path),
                "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
            )

    def test_checkout_dir(self):
        path = checkout_dir("~/FreeCAD-PLM", "https://plm.lan.schumbi.de", "PRJ", 17)
        self.assertEqual(path.name, "checkout-17")
        self.assertEqual(path.parent.name, "PRJ")

    def test_readonly_revision_dir(self):
        path = readonly_revision_dir("~/FreeCAD-PLM", "https://plm.lan.schumbi.de", "PRJ", 23)
        self.assertEqual(path.name, "revision-23")
        self.assertEqual(path.parent.name, "readonly")
        self.assertEqual(path.parent.parent.name, "PRJ")

    def test_safe_download_filename_strips_path(self):
        self.assertEqual(safe_download_filename("../part.FCStd"), "part.FCStd")
        self.assertEqual(safe_download_filename("/tmp/part.FCStd"), "part.FCStd")
        self.assertEqual(safe_download_filename(""), "revision.FCStd")

    def test_resolve_reference_path(self):
        self.assertEqual(resolve_reference_path("Assembly.FCStd", "Box.FCStd"), "Box.FCStd")
        self.assertEqual(
            resolve_reference_path("assemblies/Assembly.FCStd", "../parts/Box.FCStd"),
            "parts/Box.FCStd",
        )


if __name__ == "__main__":
    unittest.main()
