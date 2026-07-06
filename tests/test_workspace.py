import json
import tempfile
import unittest
from pathlib import Path

from freecad_plm_addon.errors import WorkspaceError
from freecad_plm_addon.workspace import (
    checkout_dir,
    read_manifest,
    root_file_path,
    safe_join,
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


if __name__ == "__main__":
    unittest.main()
