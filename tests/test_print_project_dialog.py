import unittest
from unittest.mock import Mock, patch
from freecad_plm_addon.print_project_dialog import next_print_project_code
from freecad_plm_addon.api_client import PLMClient
from freecad_plm_addon.errors import APIError


class PrintProjectDialogTests(unittest.TestCase):
    def test_new_code_is_unique_within_project(self):
        projects = [{"project_id": 1, "code": "DP-7"},
                    {"project_id": 1, "code": "DP-7-2"},
                    {"project_id": 2, "code": "DP-7-3"}]
        self.assertEqual(next_print_project_code(projects, 1, 7), "DP-7-3")
        self.assertEqual(next_print_project_code([], 1, 7), "DP-7")

    def test_preview_uses_authenticated_same_origin_download(self):
        client = PLMClient("https://plm.example", "token")
        response = Mock()
        response.read.return_value = b"png"
        with patch.object(client, "_absolute_urlopen", return_value=response) as opener:
            self.assertEqual(client.get_print_project_preview("/api/preview/"), b"png")
            req = opener.call_args.args[0]
            self.assertEqual(req.full_url, "https://plm.example/api/preview/")
            self.assertEqual(req.headers["Authorization"], "Bearer token")
            response.close.assert_called_once()
            with self.assertRaises(APIError):
                client.get_print_project_preview("https://foreign.example/image.png")
            self.assertEqual(opener.call_count, 1)

    def test_oversized_preview_is_rejected_and_response_closed(self):
        client = PLMClient("https://plm.example", "token")
        response = Mock()
        response.read.return_value = b"x" * (2 * 1024 * 1024 + 1)
        with patch.object(client, "_absolute_urlopen", return_value=response):
            with self.assertRaises(APIError):
                client.get_print_project_preview("/api/preview/")
        response.close.assert_called_once()

    def test_older_server_cannot_reuse_existing_project_when_creating_new(self):
        client = PLMClient("https://plm.example", "token")
        with patch.object(client, "_json", return_value={"created": False, "print_project": {"id": 7}}):
            with self.assertRaises(APIError):
                client.create_print_project(1, "DP-1", "New", require_new=True)
