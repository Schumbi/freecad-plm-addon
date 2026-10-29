import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from zipfile import ZipFile

from freecad_plm_addon.panel_checkout import PanelCheckoutMixin
from freecad_plm_addon.workspace import build_checkout_metadata, sha256_file, technically_changed_manifest_files, write_manifest, write_checkout_metadata


class CheckinFlowTests(unittest.TestCase):
    def run_checkin(self, accepted=True, upload_error=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'files' / 'part.FCStd'
            path.parent.mkdir()
            def save(color):
                with ZipFile(path, 'w') as archive:
                    archive.writestr('Document.xml', '<Document><Properties><Property name="PLMRevision"><String value="R0001"/></Property></Properties></Document>')
                    archive.writestr('GuiDocument.xml', f'<GuiDocument><ViewProvider name="Body"><Properties><Property name="ShapeColor"><PropertyColor value="{color}"/></Property></Properties></ViewProvider></GuiDocument>')
            save(0xff0000ff)
            manifest = {'files': [{'path': 'part.FCStd', 'revision_id': 10, 'revision_code': 'R0001', 'sha256': sha256_file(path), 'is_root': True}]}
            write_manifest(root, manifest)
            write_checkout_metadata(root, build_checkout_metadata(manifest, root))
            save(0x0000ffff)
            before = path.read_bytes()
            client = Mock()
            def upload(checkout_id, files, summary):
                self.assertEqual(checkout_id, 7)
                self.assertEqual(summary, 'Neue Farbe')
                self.assertNotEqual(files[0]['local_path'], path)
                self.assertEqual(sha256_file(files[0]['local_path']), files[0]['sha256'])
                self.assertEqual(path.read_bytes(), before)
                if upload_error:
                    raise upload_error
                return {'checkout': {'status': 'completed'}, 'revision': {'id': 11}, 'revisions': [{'path': 'part.FCStd', 'revision': {'id': 11}}]}
            client.checkin_files.side_effect = upload
            panel = SimpleNamespace(
                active_checkout_id=lambda: 7, active_checkout_dir=root, active_checkout_root_path=path,
                checkout_document_names=['Part'], widget=None, QtCore=None,
                QtWidgets=SimpleNamespace(QInputDialog=SimpleNamespace(getMultiLineText=Mock(return_value=('Neue Farbe', accepted)))),
                checkout_state_timer=Mock(), client=lambda: client, set_status=Mock(),
                reset_active_checkout=Mock(), refresh_revisions=Mock(), refresh_active_checkouts=Mock(),
                select_revision_by_id=Mock(), offer_cancel_unchanged_checkout=Mock(),
            )
            def background(*args, **_kwargs):
                with ThreadPoolExecutor(max_workers=1) as executor:
                    return executor.submit(args[4]).result()
            with patch('freecad_plm_addon.panel_checkout.run_background_work', side_effect=background), patch('freecad_plm_addon.panel_checkout.technically_changed_manifest_files', wraps=technically_changed_manifest_files) as compare, patch('freecad_plm_addon.fcstd.document_names_in_directory', return_value=['Part']), patch('freecad_plm_addon.fcstd.save_documents', return_value=(['Part'], [])), patch('freecad_plm_addon.fcstd.close_documents', return_value=(['Part'], [])) as close:
                PanelCheckoutMixin.checkin_active_checkout(panel)
            compare.assert_called_once()
            self.assertFalse(panel.checkin_busy)
            self.assertEqual(path.read_bytes(), before)
            panel.checkout_state_timer.start.assert_called_once()
            return panel, client, close

    def test_success_uploads_copy_and_completes_on_gui_side(self):
        panel, client, close = self.run_checkin()
        client.checkin_files.assert_called_once()
        panel.reset_active_checkout.assert_called_once()
        close.assert_called_once()

    def test_cancelled_comment_does_not_upload_or_change_working_file(self):
        panel, client, close = self.run_checkin(accepted=False)
        client.checkin_files.assert_not_called()
        panel.reset_active_checkout.assert_not_called()
        close.assert_not_called()

    def test_failed_upload_keeps_checkout_and_documents_open(self):
        panel, client, close = self.run_checkin(upload_error=RuntimeError('Network unavailable'))
        client.checkin_files.assert_called_once()
        panel.reset_active_checkout.assert_not_called()
        close.assert_not_called()
