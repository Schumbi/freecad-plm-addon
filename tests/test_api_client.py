import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from freecad_plm_addon.api_client import PLMClient
from freecad_plm_addon.errors import AuthenticationError, ConflictError


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


if __name__ == "__main__":
    unittest.main()
