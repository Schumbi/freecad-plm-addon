import sys
import types
import unittest
from unittest.mock import patch

from freecad_plm_addon.panel import (
    annotation_create_payload,
    annotation_label,
    annotation_matches_filter,
    annotation_update_payload,
    annotations_for_revision,
    checkin_conflict_text,
    checkin_created_revision_count,
    checkin_completed,
    checkin_result_text,
    active_checkout_revision_id,
    checkout_label,
    checkout_guard_action,
    checkout_file_label,
    checkout_display_name,
    checkout_project_code,
    compact_revision_summary,
    connection_label,
    format_bytes,
    import_checkout_candidates,
    import_checkout_followup_text,
    new_part_filename,
    part_label,
    part_edit_payload,
    print_freecad_console,
    project_edit_payload,
    project_import_result_text,
    project_label,
    revision_label,
    revision_primary_action,
    revision_is_checkout_editable,
    revision_workflow_hint,
    revision_notes_payload,
    revision_notes_text,
    revision_overview_text,
    revision_technical_text,
    revisions_from_part_detail,
    save_slicer_settings,
    unchanged_checkout_text,
)
from freecad_plm_addon.errors import ConflictError


class PanelTests(unittest.TestCase):
    def test_save_slicer_settings_imports_and_updates_config(self):
        with (
            patch("freecad_plm_addon.config.set_slicer_kind") as set_kind,
            patch("freecad_plm_addon.config.set_slicer_executable") as set_executable,
            patch("freecad_plm_addon.config.set_slicer_extra_args") as set_extra_args,
        ):
            save_slicer_settings("bambu", "", "[]")

        set_kind.assert_called_once_with("bambu")
        set_executable.assert_called_once_with("")
        set_extra_args.assert_called_once_with("[]")

    def test_new_part_filename_is_safe_and_keeps_fcstd_suffix(self):
        self.assertEqual(new_part_filename("Klebeschale"), "Klebeschale.FCStd")
        self.assertEqual(new_part_filename("Große Schale / links"), "Große_Schale_links.FCStd")
        self.assertEqual(new_part_filename("Deckel.FCStd"), "Deckel.FCStd")
        self.assertEqual(new_part_filename(""), "Neues_Teil.FCStd")

    def test_checkout_file_label_includes_part_and_revision(self):
        self.assertEqual(
            checkout_file_label(
                {
                    "path": "Box.FCStd",
                    "part_number": "P-002",
                    "revision_code": "R0003",
                }
            ),
            "Box.FCStd (P-002 · R0003)",
        )

    def test_checkin_completed_uses_checkout_status(self):
        self.assertTrue(checkin_completed({"checkout": {"status": "completed"}}))
        self.assertFalse(checkin_completed({"checkout": {"status": "active"}}))

    def test_project_label_prefers_code_and_name(self):
        self.assertEqual(
            project_label({"code": "PRJ", "name": "Demo Project"}),
            "PRJ - Demo Project",
        )

    def test_project_label_falls_back_to_id(self):
        self.assertEqual(project_label({"id": 7}), "Projekt 7")

    def test_project_edit_payload_trims_and_uppercases_code(self):
        self.assertEqual(
            project_edit_payload(
                {
                    "code": " prj ",
                    "name": " Demo ",
                    "status": " order ",
                    "project_date": " 2026-07-08 ",
                    "description": " Test ",
                }
            ),
            {
                "code": "PRJ",
                "name": "Demo",
                "status": "order",
                "project_date": "2026-07-08",
                "description": "Test",
            },
        )

    def test_project_import_result_text_summarizes_import(self):
        self.assertEqual(
            project_import_result_text(
                {
                    "snapshot": {"name": "Initial"},
                    "import_summary": {
                        "created_parts": 2,
                        "created_revisions": 3,
                        "reused_revisions": 1,
                        "files": [{"path": "A.FCStd"}, {"path": "B.FCStd"}],
                    },
                }
            ),
            "Import abgeschlossen: Initial (2 Datei(en), 2 neue Teile, "
            "3 neue Revisionen, 1 wiederverwendet).",
        )

    def test_import_checkout_candidates_uses_snapshot_entries(self):
        self.assertEqual(
            import_checkout_candidates(
                {
                    "snapshot": {
                        "id": 9,
                        "entries": [
                            {
                                "path": "Assembly.FCStd",
                                "revision_id": 17,
                                "part_id": 5,
                                "part_number": "A-001",
                                "part_name": "Assembly",
                                "part_category": "assembly",
                            }
                        ],
                    }
                }
            ),
            [
                {
                    "label": "Assembly.FCStd (A-001 - Assembly) [assembly]",
                    "path": "Assembly.FCStd",
                    "revision_id": 17,
                    "snapshot_id": 9,
                    "part_id": 5,
                    "part_number": "A-001",
                    "part_name": "Assembly",
                    "part_category": "assembly",
                }
            ],
        )

    def test_import_checkout_candidates_excludes_external_cad_roots(self):
        result = {
            "snapshot": {
                "id": 9,
                "entries": [
                    {
                        "path": "Vendor.step",
                        "file_format": "step",
                        "revision_id": 18,
                    },
                    {
                        "path": "Mesh.stl",
                        "file_format": "stl",
                        "revision_id": 19,
                    },
                ],
            }
        }

        self.assertEqual(import_checkout_candidates(result), [])

    def test_import_followup_explains_external_cad_revisions(self):
        result = {
            "snapshot": {
                "entries": [
                    {"path": "Vendor.step", "file_format": "step"},
                    {"path": "Mesh.stl", "file_format": "stl"},
                ]
            }
        }

        self.assertEqual(
            import_checkout_followup_text(result),
            "2 STEP-/STL-Revisionen importiert. Diese Austauschmodelle können "
            "in der Revisionsliste schreibgeschützt geöffnet werden.",
        )

    def test_connection_label(self):
        self.assertEqual(connection_label("https://plm.lan.schumbi.de"), "Verbunden mit plm.lan.schumbi.de")
        self.assertEqual(connection_label(""), "Nicht verbunden.")

    def test_checkout_project_code_uses_nested_project(self):
        self.assertEqual(
            checkout_project_code({"project": {"id": 3, "code": "PRJ"}}),
            "PRJ",
        )

    def test_checkout_project_code_falls_back_to_project_id(self):
        self.assertEqual(
            checkout_project_code({"project_id": 3}),
            "project-3",
        )

    def test_checkout_label_includes_project_part_and_revision(self):
        self.assertEqual(
            checkout_label(
                {
                    "id": 42,
                    "project": {"code": "PRJ"},
                    "part": {"number": "A-001"},
                    "revision": {"revision_code": "R0001"},
                }
            ),
            "Checkout 42 - PRJ, A-001, Revision R0001",
        )

    def test_active_checkout_revision_id_uses_nested_revision(self):
        self.assertEqual(
            active_checkout_revision_id({"revision": {"id": 17}}),
            17,
        )

    def test_active_checkout_revision_id_uses_revision_id_or_base_revision_id(self):
        self.assertEqual(active_checkout_revision_id({"revision_id": 18}), 18)
        self.assertEqual(active_checkout_revision_id({"base_revision_id": 19}), 19)

    def test_checkout_guard_allows_checkout_without_active_checkout(self):
        self.assertEqual(checkout_guard_action(None, {"id": 7}), "checkout")

    def test_checkout_guard_detects_same_checkout(self):
        self.assertEqual(
            checkout_guard_action({"revision": {"id": 7}}, {"id": 7}),
            "same_checkout",
        )

    def test_checkout_guard_blocks_other_checkout(self):
        self.assertEqual(
            checkout_guard_action({"revision_id": 8}, {"id": 7}),
            "blocked_by_other_checkout",
        )

    def test_checkout_guard_requires_revision_id(self):
        self.assertEqual(checkout_guard_action({"revision_id": 8}, {}), "missing_revision")

    def test_checkout_display_name_uses_path_name(self):
        self.assertEqual(
            checkout_display_name("/home/ralf/FreeCAD-PLM/checkout/Box.FCStd"),
            "Box.FCStd",
        )

    def test_print_freecad_console_without_freecad_is_noop(self):
        print_freecad_console("Test")

    def test_print_freecad_console_prefixes_messages(self):
        messages = []
        fake_freecad = types.SimpleNamespace(
            Console=types.SimpleNamespace(PrintMessage=messages.append)
        )
        previous = sys.modules.get("FreeCAD")
        sys.modules["FreeCAD"] = fake_freecad
        try:
            print_freecad_console("Test")
        finally:
            if previous is None:
                sys.modules.pop("FreeCAD", None)
            else:
                sys.modules["FreeCAD"] = previous

        self.assertEqual(messages, ["[FreeCAD-PLM] Test\n"])

    def test_compact_revision_summary_shows_primary_fields(self):
        self.assertEqual(
            compact_revision_summary(
                {
                    "revision_code": "R0001",
                    "status": "Entwurf",
                    "filename": "Box.FCStd",
                    "created_at": "2026-07-10T12:00:00Z",
                    "id": 7,
                }
            ),
            "R0001 · Entwurf · FCStd · Box.FCStd · 2026-07-10",
        )

    def test_checkin_result_text_reports_root_and_revision_count(self):
        self.assertEqual(
            checkin_result_text(
                {
                    "revision": {"id": 20},
                    "revisions": [
                        {"path": "Root.FCStd", "revision": {"id": 20}},
                        {"path": "Box.FCStd", "revision": {"id": 21}},
                    ],
                }
            ),
            "Neue Root-Revision: 20. Neue Revisionen: 2.",
        )

    def test_checkin_result_text_handles_referenced_only_checkin(self):
        self.assertEqual(
            checkin_result_text(
                {
                    "revision": None,
                    "revisions": [
                        {"path": "Box.FCStd", "revision": {"id": 21}},
                    ],
                }
            ),
            "Neue Revision: 1.",
        )

    def test_checkin_result_text_reports_ignored_files(self):
        self.assertEqual(
            checkin_result_text(
                {
                    "revision": None,
                    "revisions": [],
                    "ignored_files": [
                        {"path": "Druck.FCStd", "reason": "no_model_change"},
                    ],
                }
            ),
            "Ignoriert: 1.",
        )

    def test_checkin_result_text_reports_revisions_and_ignored_files(self):
        self.assertEqual(
            checkin_result_text(
                {
                    "revision": None,
                    "revisions": [
                        {"path": "Box.FCStd", "revision": {"id": 21}},
                    ],
                    "ignored_files": [
                        {"path": "Deckel.FCStd", "reason": "no_model_change"},
                    ],
                }
            ),
            "Neue Revision: 1. Ignoriert: 1.",
        )

    def test_checkin_created_revision_count_uses_revisions_list(self):
        self.assertEqual(
            checkin_created_revision_count(
                {
                    "revision": None,
                    "revisions": [
                        {"path": "Box.FCStd", "revision": {"id": 21}},
                    ],
                    "ignored_files": [],
                }
            ),
            1,
        )

    def test_checkin_created_revision_count_handles_ignored_only_response(self):
        self.assertEqual(
            checkin_created_revision_count(
                {
                    "revision": None,
                    "revisions": [],
                    "ignored_files": [
                        {"path": "Druck.FCStd", "reason": "no_model_change"},
                    ],
                }
            ),
            0,
        )

    def test_checkin_conflict_text_explains_stale_checkout(self):
        text = checkin_conflict_text(
            ConflictError(
                409,
                "PLMRevision in der FCStd-Datei ist R0002, erwartet wird R0003.",
            )
        )

        self.assertIn("Check-in-Konflikt", text)
        self.assertIn("Checkout neu laden oder abbrechen", text)
        self.assertIn("erwartet wird R0003", text)

    def test_unchanged_checkout_text_includes_saved_count(self):
        self.assertEqual(
            unchanged_checkout_text(saved_count=2),
            "Keine modellrelevanten Änderungen; Checkout bleibt aktiv. Gespeichert: 2.",
        )

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

    def test_part_edit_payload_trims_supported_fields(self):
        self.assertEqual(
            part_edit_payload(
                {
                    "name": " Halter ",
                    "description": " Test ",
                    "material": " PLA ",
                    "supplier": " intern ",
                    "tags": " demo, addon ",
                    "category": " assembly ",
                    "is_archived": True,
                }
            ),
            {
                "name": "Halter",
                "description": "Test",
                "material": "PLA",
                "supplier": "intern",
                "tags": "demo, addon",
                "category": "assembly",
                "is_archived": True,
            },
        )

    def test_part_edit_payload_can_include_number_for_create(self):
        self.assertEqual(
            part_edit_payload(
                {"number": " A-001 ", "name": " Baugruppe ", "category": "assembly"},
                include_number=True,
            )["number"],
            "A-001",
        )

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
            "A · Freigegeben · FCStd · part.FCStd · 2026-07-06",
        )

    def test_revision_label_falls_back_to_id(self):
        self.assertEqual(revision_label({"id": 11}), "Revision 11")

    def test_only_fcstd_revision_is_checkout_editable(self):
        self.assertTrue(revision_is_checkout_editable({"file_format": "fcstd"}))
        self.assertTrue(revision_is_checkout_editable({"filename": "Part.FCStd"}))
        self.assertFalse(revision_is_checkout_editable({"file_format": "step"}))
        self.assertFalse(revision_is_checkout_editable({"file_format": "stl"}))

    def test_revision_primary_action_matches_file_format(self):
        self.assertEqual(
            revision_primary_action({"id": 1, "file_format": "fcstd"}),
            "checkout",
        )
        self.assertEqual(
            revision_primary_action({"id": 2, "file_format": "step"}),
            "open_readonly",
        )
        self.assertEqual(revision_primary_action({"file_format": "stl"}), "missing_revision")

    def test_revision_workflow_hint_explains_double_click(self):
        self.assertEqual(
            revision_workflow_hint({"id": 1, "file_format": "fcstd"}),
            "FCStd: bearbeitbar · Doppelklick startet den Checkout",
        )
        self.assertEqual(
            revision_workflow_hint({"id": 2, "file_format": "stl"}),
            "STL: Austauschmodell · Doppelklick öffnet schreibgeschützt",
        )

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

    def test_revision_notes_payload_trims_notes(self):
        self.assertEqual(
            revision_notes_payload("  Vor Montage prüfen.  "),
            {"notes": "Vor Montage prüfen."},
        )

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

    def test_annotation_update_payload_trims_text_and_sets_status(self):
        self.assertEqual(
            annotation_update_payload(text=" erledigt ", status="resolved"),
            {"text": "erledigt", "status": "resolved"},
        )

    def test_annotation_update_payload_allows_status_only(self):
        self.assertEqual(
            annotation_update_payload(status="open"),
            {"status": "open"},
        )

    def test_annotation_create_payload_ignores_qt_clicked_bool(self):
        self.assertEqual(
            annotation_create_payload(7, " Prüfen ", False, ""),
            {
                "revision_id": 7,
                "text": "Prüfen",
                "object_name": "",
                "subelement": "",
            },
        )

    def test_annotation_matches_filter(self):
        open_revision_annotation = {"status": "open", "revision_id": 7}
        resolved_part_annotation = {"status": "resolved", "revision_id": None}

        self.assertTrue(annotation_matches_filter(open_revision_annotation, "all", 7))
        self.assertTrue(annotation_matches_filter(open_revision_annotation, "open", 7))
        self.assertFalse(annotation_matches_filter(open_revision_annotation, "resolved", 7))
        self.assertTrue(annotation_matches_filter(open_revision_annotation, "revision", 7))
        self.assertFalse(annotation_matches_filter(open_revision_annotation, "part", 7))
        self.assertTrue(annotation_matches_filter(resolved_part_annotation, "part", 7))
        self.assertFalse(annotation_matches_filter(resolved_part_annotation, "open", 7))

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
