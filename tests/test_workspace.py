import json
import os
import tempfile
import unittest
from pathlib import Path

from freecad_plm_addon.errors import WorkspaceError
from freecad_plm_addon.workspace import (
    changed_manifest_files,
    checkout_dir,
    download_manifest_files,
    ensure_checkout_manifest_files,
    prune_readonly_cache,
    read_manifest,
    readonly_revision_dir,
    root_file_path,
    safe_join,
    safe_download_filename,
    server_slug,
    sha256_file,
    touch_directory,
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

    def make_readonly_revision(self, root, project, revision_id, file_count=1, mtime=1):
        revision_dir = (
            Path(root)
            / "plm-lan-schumbi-de"
            / project
            / "readonly"
            / f"revision-{revision_id}"
        )
        revision_dir.mkdir(parents=True)
        for index in range(file_count):
            (revision_dir / f"part-{index}.FCStd").write_text("data", encoding="utf-8")
        os.utime(revision_dir, (mtime, mtime))
        return revision_dir

    def test_touch_directory_updates_cache_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "revision-1"

            touch_directory(path)

            self.assertTrue(path.is_dir())

    def test_prune_readonly_cache_keeps_five_revisions_per_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            for index in range(7):
                self.make_readonly_revision(tmp, "PRJ", index, mtime=index + 1)

            removed = prune_readonly_cache(
                tmp,
                "https://plm.lan.schumbi.de",
                current_project_code="PRJ",
                current_revision_id=6,
            )

            self.assertEqual(len(removed), 2)
            self.assertFalse((Path(tmp) / "plm-lan-schumbi-de" / "PRJ" / "readonly" / "revision-0").exists())
            self.assertFalse((Path(tmp) / "plm-lan-schumbi-de" / "PRJ" / "readonly" / "revision-1").exists())
            self.assertTrue((Path(tmp) / "plm-lan-schumbi-de" / "PRJ" / "readonly" / "revision-6").exists())

    def test_prune_readonly_cache_keeps_five_projects(self):
        with tempfile.TemporaryDirectory() as tmp:
            for index in range(7):
                self.make_readonly_revision(tmp, f"PRJ{index}", 1, mtime=index + 1)

            removed = prune_readonly_cache(
                tmp,
                "https://plm.lan.schumbi.de",
                current_project_code="PRJ6",
                current_revision_id=1,
            )

            self.assertEqual(len(removed), 2)
            self.assertFalse((Path(tmp) / "plm-lan-schumbi-de" / "PRJ0" / "readonly").exists())
            self.assertFalse((Path(tmp) / "plm-lan-schumbi-de" / "PRJ1" / "readonly").exists())
            self.assertTrue((Path(tmp) / "plm-lan-schumbi-de" / "PRJ6" / "readonly").exists())

    def test_prune_readonly_cache_limits_fcstd_files_by_removing_project_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.make_readonly_revision(tmp, "OLD", 1, file_count=12, mtime=1)
            self.make_readonly_revision(tmp, "MID", 1, file_count=8, mtime=2)
            self.make_readonly_revision(tmp, "CUR", 1, file_count=5, mtime=3)

            removed = prune_readonly_cache(
                tmp,
                "https://plm.lan.schumbi.de",
                current_project_code="CUR",
                current_revision_id=1,
            )

            self.assertEqual(len(removed), 1)
            self.assertFalse((Path(tmp) / "plm-lan-schumbi-de" / "OLD" / "readonly").exists())
            self.assertTrue((Path(tmp) / "plm-lan-schumbi-de" / "MID" / "readonly").exists())
            self.assertTrue((Path(tmp) / "plm-lan-schumbi-de" / "CUR" / "readonly").exists())

    def test_download_manifest_files_chmods_existing_readonly_file(self):
        class FakeClient:
            def download_revision_file(self, _url, target_path, _sha256):
                Path(target_path).write_bytes(b"abc")

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "files" / "part.FCStd"
            path.parent.mkdir(parents=True)
            path.write_bytes(b"old")
            path.chmod(0o444)
            manifest = {
                "files": [
                    {
                        "path": "part.FCStd",
                        "download_url": "https://plm.example/file",
                        "sha256": "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
                    }
                ]
            }

            downloaded = download_manifest_files(FakeClient(), manifest, tmp)

            self.assertEqual(downloaded, [path])
            self.assertEqual(path.read_bytes(), b"abc")

    def test_ensure_checkout_manifest_files_does_not_overwrite_existing_file(self):
        class FakeClient:
            def __init__(self):
                self.calls = 0

            def download_revision_file(self, _url, target_path, _sha256):
                self.calls += 1
                Path(target_path).write_bytes(b"abc")

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "files" / "part.FCStd"
            path.parent.mkdir(parents=True)
            path.write_bytes(b"local changes")
            manifest = {
                "files": [
                    {
                        "path": "part.FCStd",
                        "download_url": "https://plm.example/file",
                        "sha256": "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
                    }
                ]
            }
            client = FakeClient()

            downloaded = ensure_checkout_manifest_files(client, manifest, tmp)

            self.assertEqual(downloaded, [])
            self.assertEqual(client.calls, 0)
            self.assertEqual(path.read_bytes(), b"local changes")

    def test_changed_manifest_files_returns_modified_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "files" / "part.FCStd"
            path.parent.mkdir(parents=True)
            path.write_bytes(b"changed")
            manifest = {
                "files": [
                    {
                        "path": "part.FCStd",
                        "revision_id": 10,
                        "sha256": "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
                        "is_root": True,
                    }
                ]
            }

            changed = changed_manifest_files(manifest, tmp)

            self.assertEqual(len(changed), 1)
            self.assertEqual(changed[0]["path"], "part.FCStd")
            self.assertEqual(changed[0]["local_path"], path)
            self.assertEqual(changed[0]["revision_id"], 10)
            self.assertTrue(changed[0]["is_root"])
            self.assertNotEqual(changed[0]["sha256"], changed[0]["base_sha256"])


if __name__ == "__main__":
    unittest.main()
