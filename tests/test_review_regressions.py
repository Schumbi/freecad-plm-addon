"""Desired contracts for CODE_REVIEW_2026-09-16, including known defects.

The former expected failures remain as regression tests after their fixes.
"""

from contextlib import contextmanager
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from unittest.mock import Mock, patch
from zipfile import ZipFile

from freecad_plm_addon.api_client import PLMClient
from freecad_plm_addon.errors import APIError, ConflictError, WorkspaceError
from freecad_plm_addon.panel import PLMPanel
from freecad_plm_addon.slicer import (
    migrate_legacy_slicer_project, read_sync_state, slicer_project_dir,
    sync_state_path, write_sync_state,
)
from freecad_plm_addon.workspace import safe_join, sha256_file


class FileTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.target = self.root / "project.3mf"
        with ZipFile(self.target, "w") as archive:
            archive.writestr("3D/3dmodel.model", "<model><triangle /></model>")


class DownloadIntegrityTests(FileTests):
    def download(self, response, digest):
        with patch.object(PLMClient, "_absolute_urlopen", return_value=response):
            return PLMClient("https://plm.example", "dummy").download_revision_file(
                "https://plm.example/api/revisions/1/file/", self.target, digest
            )

    def test_hash_mismatch_preserves_existing_file(self):
        previous = self.target.read_bytes()
        response = BytesIO(b"corrupt")
        with self.assertRaises(APIError):
            self.download(response, sha256(b"wanted").hexdigest())
        self.assertTrue(self.target.is_file(), "The previous good file was removed")
        self.assertEqual(self.target.read_bytes(), previous)
        self.assertTrue(response.closed)
        self.assertEqual(list(self.root.iterdir()), [self.target])

    def test_read_error_preserves_existing_file_and_closes_response(self):
        previous = self.target.read_bytes()
        response = Mock()
        response.read.side_effect = OSError("connection interrupted")
        with self.assertRaises(OSError):
            self.download(response, "a" * 64)
        self.assertEqual(self.target.read_bytes(), previous)
        response.close.assert_called_once()
        self.assertEqual(list(self.root.iterdir()), [self.target])

    def test_bad_first_download_leaves_no_file(self):
        self.target.unlink()
        with self.assertRaises(APIError):
            self.download(BytesIO(b"corrupt"), "a" * 64)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_verified_download_replaces_existing_file(self):
        response = BytesIO(b"new file")
        self.download(response, sha256(b"new file").hexdigest())
        self.assertEqual(self.target.read_bytes(), b"new file")
        self.assertTrue(response.closed)
        self.assertEqual(list(self.root.iterdir()), [self.target])


class PortablePathTests(FileTests):
    def reject(self, name):
        with self.assertRaises(WorkspaceError):
            safe_join(self.root, name)

    def test_posix_parent_is_rejected(self):
        self.reject("../outside.FCStd")

    def test_absolute_posix_path_is_rejected(self):
        self.reject("/outside.FCStd")

    def test_nested_unicode_path_is_preserved(self):
        self.assertEqual(safe_join(self.root, "Baugruppe/Deckel ä.FCStd"),
                         self.root / "Baugruppe" / "Deckel ä.FCStd")

    def test_windows_parent_is_rejected(self):
        self.reject(r"..\escape/model.FCStd")

    def test_drive_absolute_is_rejected(self):
        self.reject(r"C:\outside.FCStd")

    def test_drive_relative_is_rejected(self):
        self.reject("C:outside.FCStd")

    def test_unc_is_rejected(self):
        self.reject(r"\\server\share\outside.FCStd")

    def test_windows_separators_are_normalized_inside_root(self):
        self.assertEqual(
            safe_join(self.root, r"Baugruppe\Deckel.FCStd"),
            self.root / "Baugruppe" / "Deckel.FCStd",
        )

    def test_symlink_escape_is_rejected_when_supported(self):
        outside = self.root.parent / f"{self.root.name}-outside"
        outside.mkdir(exist_ok=True)
        self.addCleanup(lambda: outside.rmdir() if outside.exists() else None)
        link = self.root / "linked"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"Symlinks are unavailable: {exc}")
        self.reject("linked/outside.FCStd")


class PrintProjectSyncTests(FileTests):
    def setUp(self):
        super().setUp()
        # Use the real panel sync method; only its GUI and server are replaced.
        self.panel = Mock()
        self.panel._sync_slicer_project_path = lambda *args, **kwargs: (
            PLMPanel._sync_slicer_project_path(self.panel, *args, **kwargs)
        )
        self.client = self.panel.client.return_value
        self.client.sync_print_project.return_value = {
            "id": 8, "slicer_project": {"sha256": sha256_file(self.target)}
        }
        self.state = {"print_project_id": 8, "server_sha256": "a" * 64}
        write_sync_state(self.target, self.state)

    def test_second_project_does_not_replace_first_projects_sync_state(self):
        second = self.root / "second.3mf"
        write_sync_state(second, {"print_project_id": 9, "server_sha256": "b" * 64})
        self.assertEqual(read_sync_state(self.target), self.state)

    def test_print_project_paths_separate_the_same_revision(self):
        first = slicer_project_dir(self.root, "https://plm.example", "P-1", 183, 8)
        second = slicer_project_dir(self.root, "https://plm.example", "P-1", 183, 9)
        self.assertNotEqual(first, second)
        self.assertEqual(first.parent, second.parent)
        self.assertEqual(first.name, "print-project-8")

    def test_state_filename_is_unique_per_3mf(self):
        other = self.root / "second.3mf"
        self.assertNotEqual(sync_state_path(self.target), sync_state_path(other))
        self.assertEqual(sync_state_path(self.target).name, "project.3mf.sync.json")

    def test_matching_legacy_state_is_copied_without_deleting_old_work(self):
        legacy = self.root / "revision-183" / "project.3mf"
        legacy.parent.mkdir()
        legacy.write_bytes(self.target.read_bytes())
        (legacy.parent / "sync.json").write_text(
            '{"print_project_id": 8, "server_sha256": "known"}', encoding="utf-8"
        )
        current = legacy.parent / "print-project-8" / legacy.name
        self.assertTrue(migrate_legacy_slicer_project(legacy, current, 8))
        self.assertEqual(current.read_bytes(), legacy.read_bytes())
        self.assertEqual(read_sync_state(current)["print_project_id"], 8)
        self.assertTrue(legacy.is_file())

    def test_ambiguous_legacy_state_is_not_assigned_to_another_project(self):
        legacy = self.root / "revision-183" / "project.3mf"
        legacy.parent.mkdir()
        legacy.write_bytes(self.target.read_bytes())
        (legacy.parent / "sync.json").write_text('{"print_project_id": 9}', encoding="utf-8")
        current = legacy.parent / "print-project-8" / legacy.name
        self.assertFalse(migrate_legacy_slicer_project(legacy, current, 8))
        self.assertFalse(current.exists())

    def test_directory_and_state_disagreement_blocks_upload(self):
        other = self.root / "print-project-8" / "project.3mf"
        other.parent.mkdir()
        other.write_bytes(self.target.read_bytes())
        write_sync_state(other, {"print_project_id": 9})
        with self.assertRaises(WorkspaceError):
            self.panel._sync_slicer_project_path(other, {"id": 183})
        self.client.sync_print_project.assert_not_called()

    def test_file_changed_uploads_to_its_own_project(self):
        write_sync_state(self.root / "second.3mf", {"print_project_id": 9})
        PLMPanel._slicer_file_changed(self.panel, self.target, {"id": 183})
        self.assertEqual(self.client.sync_print_project.call_count, 1)
        self.assertEqual(self.client.sync_print_project.call_args.args[:2],
                         (8, self.target))

    def test_sync_sends_last_known_server_hash(self):
        self.panel._sync_slicer_project_path(self.target, {"id": 183})
        self.assertEqual(self.client.sync_print_project.call_args.kwargs.get("base_sha256"),
                         self.state["server_sha256"])

    def test_unchanged_file_does_not_upload(self):
        write_sync_state(self.target, {**self.state, "server_sha256": sha256_file(self.target)})
        self.assertFalse(self.panel._sync_slicer_project_path(self.target, {"id": 183}))
        self.client.sync_print_project.assert_not_called()

    def test_conflict_keeps_file_and_base_hash_for_resolution(self):
        previous = self.target.read_bytes()
        self.client.sync_print_project.side_effect = ConflictError(409, "changed remotely")
        PLMPanel._slicer_file_changed(self.panel, self.target, {"id": 183})
        state = read_sync_state(self.target)
        self.assertEqual(state["sync_status"], "conflict")
        self.assertEqual(state["server_sha256"], self.state["server_sha256"])
        self.assertEqual(state["print_project_id"], 8)
        self.assertEqual(self.target.read_bytes(), previous)
        self.client.sync_print_project.assert_called_once()

    def test_nested_file_payload_without_id_is_supported(self):
        self.assertTrue(self.panel._sync_slicer_project_path(self.target, {"id": 183}))
        state = read_sync_state(self.target)
        self.assertEqual(state["print_project_id"], 8)
        self.assertEqual(state["server_sha256"], sha256_file(self.target))
        self.assertEqual(state["sync_status"], "synchronized")


@contextmanager
def http_endpoint(redirect_to=None):
    """Loopback-only HTTP endpoint, recording dummy credentials, no external I/O."""
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            received.append((self.path, self.headers.get("Authorization")))
            destination = redirect_to
            if self.path == "/same-origin":
                destination = "/file"
            self.send_response(302 if destination else 200)
            if destination:
                self.send_header("Location", destination)
            self.send_header("Content-Length", "0" if destination else "4")
            self.end_headers()
            if not destination:
                self.wfile.write(b"file")

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", received
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class CredentialBoundaryTests(FileTests):
    def fetch(self, base, url):
        PLMClient(base, "dummy-test-token", timeout=3).download_revision_file(
            url, self.target, sha256(b"file").hexdigest()
        )

    def test_same_origin_download_authenticates(self):
        with http_endpoint() as (base, received):
            self.fetch(base, base + "/file")
        self.assertEqual(received, [("/file", "Bearer dummy-test-token")])
        self.assertEqual(self.target.read_bytes(), b"file")

    def test_same_origin_redirect_authenticates(self):
        with http_endpoint() as (base, received):
            self.fetch(base, base + "/same-origin")
        self.assertEqual(received, [("/same-origin", "Bearer dummy-test-token"),
                                    ("/file", "Bearer dummy-test-token")])

    def test_foreign_absolute_url_never_receives_token(self):
        with http_endpoint() as (foreign, received), http_endpoint() as (base, _):
            try:
                self.fetch(base, foreign + "/file")
            except (APIError, ValueError):
                pass  # Rejecting the URL before sending is also safe.
        self.assertFalse(any(token for _, token in received))

    def test_cross_origin_redirect_never_receives_token(self):
        with http_endpoint() as (foreign, received):
            with http_endpoint(foreign + "/file") as (base, _):
                try:
                    self.fetch(base, base + "/redirect")
                except (APIError, ValueError):
                    pass
        self.assertFalse(any(token for _, token in received))
