import unittest
from unittest.mock import Mock
from freecad_plm_addon.project_tags import project_matches, PanelProjectTagsMixin
from freecad_plm_addon.panel_helpers import project_edit_payload


class ProjectTagsTests(unittest.TestCase):
    def setUp(self):
        self.project = {'code':'A', 'name':'Halter', 'description':'Für die Bahn',
                        'tags':[{'id':1, 'name':'Modellbau'}, {'id':2, 'name':'Zubehör'}]}

    def test_all_any_and_text_filters(self):
        self.assertTrue(project_matches(self.project, 'HALTER', ['modellbau','ZUBEHÖR']))
        self.assertFalse(project_matches(self.project, selected=['Modellbau','Haushalt']))
        self.assertTrue(project_matches(self.project, selected=['Modellbau','Haushalt'],mode='any'))
        self.assertFalse(project_matches(self.project, 'Box', ['Modellbau'], 'any'))
        self.assertTrue(project_matches(self.project, 'Zubehör'))

    def test_untagged_and_older_server_payload(self):
        self.assertFalse(project_matches(self.project, untagged=True))
        self.assertTrue(project_matches({'code':'OLD'}, untagged=True))
        self.assertFalse(project_matches({'code':'OLD'},selected=['Modellbau']))
        self.assertTrue(project_matches({'code':'OLD'}))

    def test_payload_preserves_absent_tags_and_explicit_empty(self):
        self.assertNotIn('tags', project_edit_payload({'code':'A'}))
        self.assertEqual(project_edit_payload({'code':'A', 'tags':''})['tags'], [])
        self.assertEqual(project_edit_payload({'tags':' Modellbau, Zubehör, '})['tags'], ['Modellbau','Zubehör'])

    def test_filtered_selection_is_cleared_without_removing_tree_children(self):
        panel = PanelProjectTagsMixin()
        item = Mock()
        child = Mock()
        panel.project_search = Mock()
        panel.project_search.text.return_value = 'Box'
        panel.project_tag_actions = []
        panel.project_tag_mode = Mock()
        panel.project_tag_mode.currentData.return_value = 'all'
        panel.project_tag_button = Mock()
        panel.project_filter_count = Mock()
        panel.browser_tree = Mock()
        panel.browser_tree.currentItem.return_value = child
        panel.iter_tree_items = lambda: iter([item,child])
        panel.tree_item_kind = lambda i: 'project' if i is item else 'revision'
        panel.tree_item_payload = lambda i: self.project
        panel.tree_ancestor = lambda i,k: item
        panel.apply_project_filters()
        item.setHidden.assert_called_once_with(True)
        child.setHidden.assert_not_called()
        panel.browser_tree.setCurrentItem.assert_called_once_with(None)
        panel.project_filter_count.setText.assert_called_once_with('0 von 1 Projekten')
