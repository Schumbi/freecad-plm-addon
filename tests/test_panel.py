import unittest

from freecad_plm_addon.panel import (
    annotation_label,
    annotations_for_revision,
    connection_label,
    format_bytes,
    part_label,
    project_label,
    revision_label,
    revision_notes_text,
    revision_overview_text,
    revision_technical_text,
    revisions_from_part_detail,
)


class PanelTests(unittest.TestCase):
    def test_project_label_prefers_code_and_name(self):
        self.assertEqual(
            project_label({"code": "PRJ", "name": "Demo Project"}),
            "PRJ - Demo Project",
        )

    def test_project_label_falls_back_to_id(self):
        self.assertEqual(project_label({"id": 7}), "Projekt 7")

    def test_connection_label(self):
        self.assertEqual(connection_label("https://plm.lan.schumbi.de"), "Verbunden mit plm.lan.schumbi.de")
        self.assertEqual(connection_label(""), "Nicht verbunden.")

    def test_part_label_uses_number_name_and_status(self):
        self.assertEqual(
            part_label({"number": "P-100", "name": "Bracket", "status": "draft"}),
            "P-100 - Bracket [draft]",
        )

    def test_part_label_accepts_alternate_api_fields(self):
        self.assertEqual(
            part_label({"part_number": "P-200", "title": "Housing", "release_status": "released"}),
            "P-200 - Housing [released]",
        )

    def test_part_label_falls_back_to_id(self):
        self.assertEqual(part_label({"id": 9}), "Teil 9")

    def test_revision_label_uses_revision_status_filename_and_date(self):
        self.assertEqual(
            revision_label(
                {
                    "revision": "A",
                    "status": "released",
                    "original_filename": "part.FCStd",
                    "created_at": "2026-07-06T09:30:00Z",
                }
            ),
            "Revision A - released, part.FCStd, 2026-07-06",
        )

    def test_revision_label_falls_back_to_id(self):
        self.assertEqual(revision_label({"id": 11}), "Revision 11")

    def test_revisions_from_part_detail_accepts_wrapped_part(self):
        revisions = [{"id": 1}, {"id": 2}]

        self.assertEqual(revisions_from_part_detail({"part": {"revisions": revisions}}), revisions)

    def test_revisions_from_part_detail_accepts_api_part_response(self):
        revisions = [{"id": 4}]

        self.assertEqual(
            revisions_from_part_detail({"part": {"id": 8}, "revisions": revisions}),
            revisions,
        )

    def test_revisions_from_part_detail_accepts_plain_part(self):
        revisions = [{"id": 3}]

        self.assertEqual(revisions_from_part_detail({"revision_set": revisions}), revisions)

    def test_format_bytes(self):
        self.assertEqual(format_bytes(512), "512 B")
        self.assertEqual(format_bytes(1536), "1.5 KB")
        self.assertEqual(format_bytes(2 * 1024 * 1024), "2.0 MB")

    def test_revision_overview_text_includes_api_fields_without_metadata(self):
        details = revision_overview_text(
            {
                "id": 11,
                "revision_code": "R0001",
                "status": "draft",
                "original_filename": "part.FCStd",
                "size_bytes": 1536,
                "sha256": "abc123",
                "created_at": "2026-07-06T09:30:00Z",
                "download_url": "https://plm.example/api/revisions/11/file/",
                "extracted_metadata": {"Label": "Part"},
            }
        )

        self.assertIn("Revision: R0001", details)
        self.assertIn("Datei: part.FCStd", details)
        self.assertIn("Groesse: 1.5 KB", details)
        self.assertIn("SHA-256: abc123", details)
        self.assertIn("Download-URL: https://plm.example/api/revisions/11/file/", details)
        self.assertNotIn('"Label": "Part"', details)

    def test_revision_notes_text(self):
        self.assertEqual(revision_notes_text({"notes": "Initial import"}), "Initial import")
        self.assertEqual(revision_notes_text({}), "Keine Notizen vorhanden.")

    def test_revision_technical_text_contains_metadata(self):
        self.assertIn('"Label": "Part"', revision_technical_text({"extracted_metadata": {"Label": "Part"}}))

    def test_annotation_label(self):
        self.assertEqual(
            annotation_label(
                {
                    "object_name": "Body",
                    "subelement": "Face1",
                    "status": "open",
                    "created_by": "ralf",
                    "created_at": "2026-07-06T10:00:00Z",
                    "text": "Kante prüfen",
                }
            ),
            "Body.Face1 - [open] - ralf 2026-07-06 - Kante prüfen",
        )

    def test_annotations_for_revision_includes_general_and_matching_annotations(self):
        annotations = [
            {"id": 1, "revision_id": None},
            {"id": 2, "revision_id": 7},
            {"id": 3, "revision_id": 8},
        ]

        self.assertEqual(
            annotations_for_revision(annotations, 7),
            [{"id": 1, "revision_id": None}, {"id": 2, "revision_id": 7}],
        )


if __name__ == "__main__":
    unittest.main()
