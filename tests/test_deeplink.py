import unittest

from freecad_plm_addon.deeplink import (
    RevisionDeepLink,
    deep_link_from_argv,
    parse_revision_deep_link,
)


class DeepLinkTests(unittest.TestCase):
    def test_parses_revision_checkout_link(self):
        self.assertEqual(
            parse_revision_deep_link(
                "freecad-plm://revision/17?project_id=2&part_id=9&action=checkout"
            ),
            RevisionDeepLink(2, 9, 17, "checkout"),
        )

    def test_defaults_to_checkout(self):
        link = parse_revision_deep_link(
            "freecad-plm://revision/17?project_id=2&part_id=9"
        )
        self.assertEqual(link.action, "checkout")

    def test_rejects_unknown_action_or_parameter(self):
        with self.assertRaises(ValueError):
            parse_revision_deep_link(
                "freecad-plm://revision/17?project_id=2&part_id=9&action=delete"
            )
        with self.assertRaises(ValueError):
            parse_revision_deep_link(
                "freecad-plm://revision/17?project_id=2&part_id=9&token=secret"
            )

    def test_rejects_duplicate_parameters(self):
        with self.assertRaises(ValueError):
            parse_revision_deep_link(
                "freecad-plm://revision/17?project_id=2&project_id=3&part_id=9"
            )

    def test_rejects_wrong_scheme_and_invalid_ids(self):
        with self.assertRaises(ValueError):
            parse_revision_deep_link(
                "https://revision/17?project_id=2&part_id=9"
            )
        with self.assertRaises(ValueError):
            parse_revision_deep_link(
                "freecad-plm://revision/nope?project_id=2&part_id=9"
            )

    def test_finds_link_in_process_arguments(self):
        self.assertEqual(
            deep_link_from_argv(
                [
                    "FreeCAD",
                    "--single-instance",
                    "freecad-plm://revision/17?project_id=2&part_id=9&action=readonly",
                ]
            ).action,
            "readonly",
        )
        self.assertIsNone(deep_link_from_argv(["FreeCAD", "model.FCStd"]))
