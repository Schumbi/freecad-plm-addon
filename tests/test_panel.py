import unittest

from freecad_plm_addon.panel import project_label


class PanelTests(unittest.TestCase):
    def test_project_label_prefers_code_and_name(self):
        self.assertEqual(
            project_label({"code": "PRJ", "name": "Demo Project"}),
            "PRJ - Demo Project",
        )

    def test_project_label_falls_back_to_id(self):
        self.assertEqual(project_label({"id": 7}), "Projekt 7")


if __name__ == "__main__":
    unittest.main()
