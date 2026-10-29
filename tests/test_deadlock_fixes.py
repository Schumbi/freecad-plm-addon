import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from freecad_plm_addon.deeplink_runtime import dispatch_deep_link, reset_runtime_state_for_tests
from freecad_plm_addon.panel_browser import PanelBrowserMixin
from freecad_plm_addon.panel_projects import PanelProjectsMixin
from freecad_plm_addon.panel_state import PanelStateMixin


class DeadlockFixTests(unittest.TestCase):
    def test_manual_refresh_fetches_visible_checkout_data_before_rebuilding_tree(self):
        panel = Mock()
        panel._project_refresh_pending = False
        panel.server_url.text.return_value = "https://plm.example"
        panel.api_token.text.return_value = "token"
        panel.tree_selection_key.return_value = ("revision", 3, 1, 2)
        client = panel.client.return_value
        client.get_projects.return_value = [{"id": 1}]
        client.get_folders.return_value = []
        client.get_active_checkouts.return_value = [
            {"project": {"id": 1}, "part": {"id": 2}},
        ]
        with patch("freecad_plm_addon.background_work.run_gui_work") as run:
            PanelProjectsMixin.refresh_projects_background(panel)
            client.get_projects.assert_not_called()
            work, finished = run.call_args.args[-2:]
            result = work()
            self.assertEqual(result["parts"], {1: client.get_parts.return_value})
            self.assertEqual(result["details"], {2: client.get_part.return_value})
            finished(result, None)
        panel.refresh_projects.assert_called_once_with(prefetched=result)
        self.assertFalse(panel._project_refresh_pending)
        self.assertEqual(panel._refresh_parts_by_project, {})
        self.assertEqual(panel._refresh_part_details, {})

    def test_deep_links_wait_for_current_modal_workflow(self):
        reset_runtime_state_for_tests()
        events = []
        first = "freecad-plm://revision/1?project_id=1&part_id=1&action=readonly"
        second = "freecad-plm://revision/2?project_id=1&part_id=1&action=readonly"

        def open_link(link):
            events.append(("start", link.revision_id))
            if link.revision_id == 1:
                dispatch_deep_link(second, opener=open_link)
                events.append(("first-still-active", 1))
            events.append(("end", link.revision_id))

        dispatch_deep_link(first, opener=open_link)
        self.assertEqual(events, [("start", 1), ("first-still-active", 1),
                                  ("end", 1), ("start", 2), ("end", 2)])

    def test_expansion_schedules_network_without_calling_it_inline(self):
        panel = Mock()
        item = Mock()
        item.data.return_value = False
        panel.tree_item_kind.return_value = "project"
        PanelBrowserMixin.browser_item_expanded(panel, item)
        panel.load_project_parts.assert_called_once_with(item, background=True)

    def test_periodic_checkout_check_caches_error_for_same_file_state(self):
        panel = Mock()
        with tempfile.TemporaryDirectory() as tmp:
            panel.active_checkout_dir = Path(tmp)
            panel.checkin_busy = False
            panel.checkout_document_names = []
            panel.checkout_change_signature = None
            panel.checkout_change_state = True
            panel._checkout_check_pending = False
            panel._checkout_check_generation = 0
            manifest = {"files": [{"path": "part.FCStd"}]}
            with patch("freecad_plm_addon.panel_state.read_manifest", return_value=manifest), \
                 patch("freecad_plm_addon.panel_state.ensure_checkout_metadata", return_value={}), \
                 patch("freecad_plm_addon.fcstd.document_names_in_directory", return_value=[]), \
                 patch("freecad_plm_addon.fcstd.modified_document_names", return_value=[]), \
                 patch("freecad_plm_addon.panel_state.checkout_files_signature", return_value=(("part.FCStd", 10, 1),)), \
                 patch("freecad_plm_addon.panel_state.checkout_has_changes", side_effect=ValueError("bad file")), \
                 patch("freecad_plm_addon.background_work.run_gui_work") as run:
                self.assertTrue(PanelStateMixin.poll_checkout_change_state(panel))
                work, finished = run.call_args.args[-2:]
                with self.assertRaises(ValueError):
                    work()
                # In production run_gui_work delivers the exception to finished.
                finished(None, ValueError("bad file"))
                self.assertTrue(PanelStateMixin.poll_checkout_change_state(panel))
                run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
