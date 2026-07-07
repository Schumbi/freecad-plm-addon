import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from freecad_plm_addon.api_client import PLMClient
from freecad_plm_addon.errors import APIError, AuthenticationError, ConflictError


class FakeResponse:
    status = 200

    def __init__(self, payload):
        self.payload = payload

    def read(self):
        if isinstance(self.payload, bytes):
            return self.payload
        return json.dumps(self.payload).encode("utf-8")

    def close(self):
        pass


class PLMClientTests(unittest.TestCase):
    def test_get_projects_sets_bearer_header(self):
        client = PLMClient("https://plm.example", "token")
        with patch("urllib.request.urlopen", return_value=FakeResponse({"projects": []})) as urlopen:
            self.assertEqual(client.get_projects(), [])
            req = urlopen.call_args.args[0]
            self.assertEqual(req.headers["Authorization"], "Bearer token")

    def test_401_raises_authentication_error(self):
        client = PLMClient("https://plm.example", "token")
        error = HTTPError(
            "https://plm.example/api/projects/",
            401,
            "Unauthorized",
            {},
            FakeResponse({"error": "API-Token erforderlich."}),
        )
        with patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(AuthenticationError):
                client.get_projects()

    def test_409_raises_conflict_error(self):
        client = PLMClient("https://plm.example", "token")
        error = HTTPError(
            "https://plm.example/api/revisions/1/checkout/",
            409,
            "Conflict",
            {},
            FakeResponse({"error": "Dieses Teil ist bereits ausgecheckt."}),
        )
        with patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(ConflictError):
                client.checkout_revision(1)

    def test_html_error_response_is_shortened(self):
        client = PLMClient("https://plm.example", "token")
        error = HTTPError(
            "https://plm.example/api/checkouts/1/checkin/",
            500,
            "Internal Server Error",
            {},
            FakeResponse(b"<html><body><h1>Server Error (500)</h1></body></html>"),
        )

        with patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(APIError) as raised:
                client.get_projects()

        self.assertIn("HTTP 500: Internal Server Error", str(raised.exception))
        self.assertNotIn("<html>", str(raised.exception))

    def test_download_revision_file_checks_hash(self):
        client = PLMClient("https://plm.example", "token")
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "part.FCStd"
            digest = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
            with patch("urllib.request.urlopen", return_value=FakeResponse(b"abc")):
                client.download_revision_file(
                    "https://plm.example/api/revisions/1/file/",
                    target,
                    digest,
                )
            self.assertEqual(target.read_bytes(), b"abc")

    def test_download_revision_file_reuses_matching_cached_file(self):
        client = PLMClient("https://plm.example", "token")
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "part.FCStd"
            target.write_bytes(b"abc")
            digest = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"

            with patch("urllib.request.urlopen") as urlopen:
                client.download_revision_file(
                    "https://plm.example/api/revisions/1/file/",
                    target,
                    digest,
                )

            urlopen.assert_not_called()
            self.assertEqual(target.read_bytes(), b"abc")

    def test_get_revision_manifest_adds_optional_snapshot_id(self):
        client = PLMClient("https://plm.example", "token")
        with patch(
            "urllib.request.urlopen",
            return_value=FakeResponse({"manifest": {"files": []}}),
        ) as urlopen:
            self.assertEqual(
                client.get_revision_manifest(17, snapshot_id=3),
                {"files": []},
            )
            req = urlopen.call_args.args[0]
            self.assertEqual(
                req.full_url,
                "https://plm.example/api/revisions/17/manifest/?snapshot_id=3",
            )

    def test_checkout_revision_posts_workspace_hint_and_snapshot(self):
        client = PLMClient("https://plm.example", "token")
        payload = {"checkout": {"id": 9}, "manifest": {"files": []}}
        with patch("urllib.request.urlopen", return_value=FakeResponse(payload)) as urlopen:
            self.assertEqual(
                client.checkout_revision(17, snapshot_id=3, workspace_hint="/tmp/plm"),
                payload,
            )
            req = urlopen.call_args.args[0]
            body = json.loads(req.data.decode("utf-8"))
            self.assertEqual(
                req.full_url,
                "https://plm.example/api/revisions/17/checkout/",
            )
            self.assertEqual(body, {"workspace_hint": "/tmp/plm", "snapshot_id": 3})

    def test_get_active_checkouts(self):
        client = PLMClient("https://plm.example", "token")
        payload = {"checkouts": [{"id": 9}]}
        with patch("urllib.request.urlopen", return_value=FakeResponse(payload)) as urlopen:
            self.assertEqual(client.get_active_checkouts(), [{"id": 9}])
            req = urlopen.call_args.args[0]
            self.assertEqual(req.full_url, "https://plm.example/api/checkouts/active/")

    def test_cancel_checkout_posts_empty_payload(self):
        client = PLMClient("https://plm.example", "token")
        with patch("urllib.request.urlopen", return_value=FakeResponse({"checkout": {}})) as urlopen:
            self.assertEqual(client.cancel_checkout(9), {"checkout": {}})
            req = urlopen.call_args.args[0]
            self.assertEqual(req.full_url, "https://plm.example/api/checkouts/9/cancel/")
            self.assertEqual(json.loads(req.data.decode("utf-8")), {})

    def test_checkin_posts_multipart_file_and_summary(self):
        client = PLMClient("https://plm.example", "token")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "part.FCStd"
            path.write_bytes(b"fcstd")

            with patch(
                "urllib.request.urlopen",
                return_value=FakeResponse({"revision": {"id": 10}}),
            ) as urlopen:
                self.assertEqual(
                    client.checkin(9, path, "changed root"),
                    {"revision": {"id": 10}},
                )

            req = urlopen.call_args.args[0]
            body = req.data
            self.assertEqual(req.full_url, "https://plm.example/api/checkouts/9/checkin/")
            self.assertIn(b'name="change_summary"', body)
            self.assertIn(b"changed root", body)
            self.assertIn(b'name="file"; filename="part.FCStd"', body)
            self.assertIn(b"fcstd", body)

    def test_checkin_files_posts_metadata_and_multiple_files(self):
        client = PLMClient("https://plm.example", "token")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root.FCStd"
            child = Path(tmp) / "child.FCStd"
            root.write_bytes(b"root")
            child.write_bytes(b"child")
            changed_files = [
                {
                    "path": "root.FCStd",
                    "local_path": root,
                    "revision_id": 10,
                    "base_sha256": "old-root",
                    "sha256": "new-root",
                    "is_root": True,
                },
                {
                    "path": "child.FCStd",
                    "local_path": child,
                    "revision_id": 11,
                    "base_sha256": "old-child",
                    "sha256": "new-child",
                    "is_root": False,
                },
            ]

            with patch(
                "urllib.request.urlopen",
                return_value=FakeResponse({"revision": {"id": 12}}),
            ) as urlopen:
                self.assertEqual(
                    client.checkin_files(9, changed_files, "changed assembly"),
                    {"revision": {"id": 12}},
                )

            req = urlopen.call_args.args[0]
            body = req.data
            self.assertEqual(req.full_url, "https://plm.example/api/checkouts/9/checkin/")
            self.assertIn(b'name="change_summary"', body)
            self.assertIn(b"changed assembly", body)
            self.assertIn(b'name="files_metadata"', body)
            self.assertIn(b'"field": "file_0"', body)
            self.assertIn(b'"path": "root.FCStd"', body)
            self.assertIn(b'name="file_0"; filename="root.FCStd"', body)
            self.assertIn(b'name="file_1"; filename="child.FCStd"', body)
            self.assertIn(b"root", body)
            self.assertIn(b"child", body)


if __name__ == "__main__":
    unittest.main()
