import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from freecad_plm_addon.link_import import open as open_link_file
from freecad_plm_addon.link_import import read_link_file
from freecad_plm_addon.protocol_handler import LINK_FILE_MAGIC


DEEPLINK = "freecad-plm://revision/17?project_id=2&part_id=9&action=checkout"


class LinkImportTests(unittest.TestCase):
    def test_reads_valid_link_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "test.FCPLMLink"
            path.write_text(f"{LINK_FILE_MAGIC}\n{DEEPLINK}\n", encoding="utf-8")

            self.assertEqual(read_link_file(path), DEEPLINK)

    def test_rejects_link_file_without_magic(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "test.FCPLMLink"
            path.write_text(DEEPLINK, encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "Ungültige"):
                read_link_file(path)

    def test_import_queues_link_and_removes_one_shot_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "test.FCPLMLink"
            path.write_text(f"{LINK_FILE_MAGIC}\n{DEEPLINK}\n", encoding="utf-8")

            with patch("freecad_plm_addon.deeplink_runtime.queue_deep_link") as queue:
                open_link_file(path)

            queue.assert_called_once_with(DEEPLINK)
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
