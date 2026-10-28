import unittest
from unittest.mock import Mock

from freecad_plm_addon.panel_browser import PanelBrowserMixin
from freecad_plm_addon.panel_helpers import project_file_part_label
from freecad_plm_addon.panel_projects import PanelProjectsMixin
from freecad_plm_addon.panel_state import PanelStateMixin


class ProjectMainFileTests(unittest.TestCase):
    def setUp(self):
        self.panel = Mock()
        self.project_item = Mock()
        self.project_item.data.return_value = False
        self.panel.tree_item_payload.return_value = {"id": 7, "main_part_id": 2}
        self.main = {"id": 2, "number": "A", "name": "Assembly", "latest_fcstd_revision": {
            "id": 8, "original_filename": "Assembly.FCStd", "revision_code": "R0002"}}
        self.other = {"id": 3, "number": "B", "name": "Other", "latest_fcstd_revision": None}
        self.panel.client.return_value.get_parts.return_value = [self.other, self.main]

    def test_main_part_precedes_collapsed_other_group(self):
        PanelProjectsMixin.load_project_parts(self.panel, self.project_item)
        created = self.panel.add_tree_item.call_args_list
        self.assertEqual(created[0].args[:3], (self.project_item, "part", self.main))
        self.assertEqual(created[1].args[:2], (self.project_item, "other_files"))
        self.assertEqual(created[2].args[1:3], ("part", self.other))
        self.assertIs(created[2].args[0], self.panel.add_tree_item.return_value)
        self.assertIn("Assembly.FCStd", created[0].args[3])
        self.panel.add_tree_item.return_value.setExpanded.assert_not_called()

    def test_without_main_keeps_flat_project_tree(self):
        self.panel.tree_item_payload.return_value = {"id": 7, "main_part_id": None}
        PanelProjectsMixin.load_project_parts(self.panel, self.project_item)
        self.assertEqual([c.args[1] for c in self.panel.add_tree_item.call_args_list], ["part", "part"])
        self.assertEqual(project_file_part_label(self.other), "B - Other")

    def test_selection_saves_project_part_id(self):
        self.panel.selected_project.return_value = {"id": 7, "main_part_id": 2}
        self.panel.QtWidgets.QInputDialog.getItem.return_value = (project_file_part_label(self.main), True)
        PanelProjectsMixin.choose_project_main_file(self.panel)
        self.panel.client.return_value.update_project.assert_called_once_with(7, {"main_part_id": 2})
        self.panel.refresh_projects.assert_called_once()

    def test_group_ancestors_expand_for_navigation(self):
        item = Mock()
        group = Mock()
        project = Mock()
        item.parent.return_value = group
        group.parent.return_value = project
        project.parent.return_value = None
        PanelBrowserMixin.expand_tree_ancestors(self.panel, item)
        group.setExpanded.assert_called_once_with(True)
        project.setExpanded.assert_called_once_with(True)

    def test_folder_context_menu_does_not_block_event_loop(self):
        item = Mock()
        position = Mock()
        menu = self.panel.QtWidgets.QMenu.return_value
        self.panel.browser_tree.itemAt.return_value = item
        self.panel.tree_item_kind.return_value = "folder"
        self.panel.context_primary_label = "Projekt importieren"
        self.panel.context_primary_callback = Mock()
        self.panel.context_more_actions = []

        PanelBrowserMixin.show_browser_context_menu(self.panel, position)

        menu.popup.assert_called_once_with(
            self.panel.browser_tree.viewport.return_value.mapToGlobal.return_value
        )
        menu.exec_.assert_not_called()
        menu.aboutToHide.connect.assert_called_once_with(menu.deleteLater)

    def test_replacing_context_actions_releases_previous_menu(self):
        previous_menu = self.panel.context_more_button.menu.return_value

        PanelStateMixin.set_context_actions(self.panel, "Projekt", "Öffnen", Mock(), [])

        self.panel.context_more_button.setMenu.assert_called_once_with(None)
        previous_menu.deleteLater.assert_called_once()
        self.panel.QtWidgets.QMenu.assert_not_called()


if __name__ == "__main__":
    unittest.main()
