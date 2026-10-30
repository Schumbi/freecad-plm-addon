import threading
import time
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch
import unittest

try:
    from PySide6 import QtCore, QtWidgets
except ImportError:
    QtCore = QtWidgets = None

from freecad_plm_addon.background_work import GuiNetworkClient, run_background_work
from freecad_plm_addon.panel_browser import PanelBrowserMixin
from freecad_plm_addon.panel_projects import PanelProjectsMixin
from freecad_plm_addon.panel import PLMPanel
from freecad_plm_addon.panel_state import PanelStateMixin
from freecad_plm_addon.print_project_dialog import choose_print_project
from freecad_plm_addon.slicer import SlicerProjectMonitor, write_sync_state


@unittest.skipIf(QtWidgets is None, "Requires the FreeCAD Qt runtime")
class BackgroundWorkQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_gui_keeps_processing_events_while_work_runs_on_other_thread(self):
        main = threading.get_ident()
        ticks = []
        timer = QtCore.QTimer()
        timer.timeout.connect(lambda: ticks.append(threading.get_ident()))
        timer.start(20)
        try:
            def work():
                time.sleep(.2)
                return threading.get_ident()
            worker = run_background_work(QtCore, QtWidgets, None, "Test", work)
        finally:
            timer.stop()
        self.assertNotEqual(worker, main)
        self.assertGreaterEqual(len(ticks), 3)
        self.assertTrue(all(t == main for t in ticks))

    def test_worker_errors_reach_the_caller(self):
        def fail():
            raise RuntimeError("Upload failed")
        with self.assertRaisesRegex(RuntimeError, "Upload failed"):
            run_background_work(QtCore, QtWidgets, None, "Test", fail)

    def test_legacy_client_request_runs_off_thread_while_qt_keeps_ticking(self):
        main = threading.get_ident()
        parent = QtWidgets.QWidget()
        activity = []
        parent._plm_panel = Mock(
            begin_network_activity=lambda: activity.append("start"),
            end_network_activity=lambda: activity.append("end"),
        )
        api = Mock()
        api.get_projects.side_effect = lambda: (time.sleep(.2), threading.get_ident())[1]
        client = GuiNetworkClient(api, QtCore, parent)
        ticks = []
        timer = QtCore.QTimer()
        timer.timeout.connect(lambda: ticks.append(threading.get_ident()))
        timer.start(20)
        try:
            worker = client.get_projects()
        finally:
            timer.stop()
        self.assertNotEqual(worker, main)
        self.assertGreaterEqual(len(ticks), 3)
        self.assertTrue(all(tick == main for tick in ticks))
        self.assertEqual(activity, ["start", "end"])

    def test_legacy_client_error_restores_activity_state(self):
        parent = QtWidgets.QWidget()
        activity = []
        parent._plm_panel = Mock(
            begin_network_activity=lambda: activity.append("start"),
            end_network_activity=lambda: activity.append("end"),
        )
        api = Mock()
        api.get_parts.side_effect = RuntimeError("offline")
        client = GuiNetworkClient(api, QtCore, parent)
        with self.assertRaisesRegex(RuntimeError, "offline"):
            client.get_parts(1)
        self.assertEqual(activity, ["start", "end"])

    def test_client_already_in_worker_does_not_enter_nested_qt_loop(self):
        parent = QtWidgets.QWidget()
        activity = []
        parent._plm_panel = Mock(
            begin_network_activity=lambda: activity.append("start"),
            end_network_activity=lambda: activity.append("end"),
        )
        api = Mock()
        api.get_parts.side_effect = lambda _id: threading.get_ident()
        client = GuiNetworkClient(api, QtCore, parent)
        with ThreadPoolExecutor(max_workers=1) as executor:
            worker = executor.submit(client.get_parts, 1).result()
        self.assertNotEqual(worker, threading.get_ident())
        self.assertEqual(activity, [])

    def test_panel_client_wraps_plm_requests(self):
        class Panel(PanelStateMixin):
            QtCore = QtCore

            def __init__(self):
                self.widget = QtWidgets.QWidget()
                self.widget._plm_panel = self
                self.server_url = QtWidgets.QLineEdit("https://plm.example")
                self.api_token = QtWidgets.QLineEdit("secret")
                self.begin_network_activity = Mock()
                self.end_network_activity = Mock()

        panel = Panel()
        api = Mock()
        api.get_projects.return_value = []
        with patch("freecad_plm_addon.panel_state.PLMClient", return_value=api):
            client = panel.client()
        self.assertIsInstance(client, GuiNetworkClient)
        self.assertEqual(client.get_projects(), [])
        panel.begin_network_activity.assert_called_once()
        panel.end_network_activity.assert_called_once()

    def test_print_preview_activity_ends_after_dialog_closes(self):
        parent = QtWidgets.QWidget()
        activity = []
        parent._plm_panel = Mock(
            begin_network_activity=lambda: activity.append("start"),
            end_network_activity=lambda: activity.append("end"),
        )
        client = Mock()
        client.get_print_project_preview.side_effect = lambda _url: (time.sleep(.2), b"invalid")[1]
        projects = [{"id": 1, "code": "DP-1", "plates": [{"number": 1, "preview_url": "https://plm.example/preview"}]}]
        QtCore.QTimer.singleShot(30, lambda: parent.findChild(QtWidgets.QDialog).reject())
        self.assertIsNone(choose_print_project(parent, QtCore, None, QtWidgets, projects, client))
        self.assertEqual(activity, ["start"])
        deadline = time.monotonic() + 2
        while len(activity) < 2 and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.02)
        self.assertEqual(activity, ["start", "end"])

    def test_network_indicator_keeps_its_place_and_disables_project_controls(self):
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(widget)
        layout.addWidget(QtWidgets.QLabel("Projekte · Teile · Revisionen"))
        layout.addStretch(1)
        panel = PLMPanel.__new__(PLMPanel)
        panel.network_indicator = QtWidgets.QLabel("●")
        panel.network_indicator.setFixedWidth(16)
        panel.network_indicator.setStyleSheet("color: rgba(22, 132, 197, 0); font-size: 15px;")
        layout.addWidget(panel.network_indicator)
        panel.network_indicator_timer = QtCore.QTimer(widget)
        panel.network_indicator_timer.setInterval(300)
        panel.network_indicator_timer.timeout.connect(panel._blink_network_indicator)
        panel._network_activity_count = 0
        panel._network_indicator_lit = False
        panel.browser_tree = QtWidgets.QTreeWidget()
        panel.variant_role = QtWidgets.QComboBox()
        panel.project_search = QtWidgets.QLineEdit()
        panel.project_tag_button = QtWidgets.QToolButton()
        panel.project_tag_mode = QtWidgets.QComboBox()
        panel.project_filter_reset = QtWidgets.QPushButton()
        panel.action_bar_widget = QtWidgets.QWidget()
        panel.settings_button = QtWidgets.QPushButton()
        panel.update_context_actions = Mock()
        widget.resize(400, 50)
        widget.show()
        self.app.processEvents()
        width = panel.network_indicator.width()
        panel.begin_network_activity()
        self.assertEqual(panel.network_indicator_timer.interval(), 300)
        self.assertFalse(panel.browser_tree.isEnabled())
        self.assertFalse(panel.variant_role.isEnabled())
        self.assertFalse(panel.action_bar_widget.isEnabled())
        self.assertIn("255", panel.network_indicator.styleSheet())
        panel._blink_network_indicator()
        self.assertIn("rgba(22, 132, 197, 0)", panel.network_indicator.styleSheet())
        panel.end_network_activity()
        self.app.processEvents()
        self.assertEqual(panel.network_indicator.width(), width)
        self.assertTrue(panel.network_indicator.isVisible())
        self.assertTrue(panel.browser_tree.isEnabled())
        self.assertFalse(panel.network_indicator_timer.isActive())
        self.assertIn("rgba(22, 132, 197, 0)", panel.network_indicator.styleSheet())

    def test_expanding_project_keeps_qt_timer_running(self):
        class Panel(PanelBrowserMixin, PanelProjectsMixin):
            QtCore = QtCore
            QtWidgets = QtWidgets

            def __init__(self):
                self.widget = QtWidgets.QWidget()
                self.browser_tree = QtWidgets.QTreeWidget(self.widget)
                self.browser_tree.itemExpanded.connect(self.browser_item_expanded)
                self.set_status = Mock()
                self.api = Mock()
                self.api.get_parts.side_effect = lambda _id, **_kwargs: (time.sleep(.2), [])[1]
                self.client = lambda: self.api

        panel = Panel()
        project = panel.add_tree_item(None, "project", {"id": 1}, "Test", lazy=True)
        ticks = []
        timer = QtCore.QTimer()
        timer.timeout.connect(lambda: ticks.append(time.monotonic()))
        timer.start(10)
        loop = QtCore.QEventLoop()
        QtCore.QTimer.singleShot(20, lambda: project.setExpanded(True))
        QtCore.QTimer.singleShot(350, loop.quit)
        loop.exec_()
        timer.stop()
        self.assertEqual(panel.api.get_parts.call_count, 1)
        self.assertTrue(project.data(0, panel.tree_role(2)))
        self.assertLess(max(b - a for a, b in zip(ticks, ticks[1:])), .1)

    def test_slicer_status_file_does_not_retrigger_sync(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "part.3mf"
            path.write_bytes(b"first")
            calls = []

            def callback(_path):
                calls.append(1)
                write_sync_state(path, {"sync_status": "conflict"})

            monitor = SlicerProjectMonitor(QtCore, path, callback, debounce_ms=20)
            path.write_bytes(b"second")
            monitor.schedule()
            loop = QtCore.QEventLoop()
            QtCore.QTimer.singleShot(250, loop.quit)
            loop.exec_()
            monitor.stop()
            self.assertEqual(len(calls), 1)

    def test_refresh_discards_late_project_response(self):
        class Panel(PanelBrowserMixin, PanelProjectsMixin):
            QtCore = QtCore
            QtWidgets = QtWidgets

            def __init__(self):
                self.widget = QtWidgets.QWidget()
                self.browser_tree = QtWidgets.QTreeWidget(self.widget)
                self.browser_tree.itemExpanded.connect(self.browser_item_expanded)
                self.set_status = Mock()
                self.api = Mock()
                self.api.get_parts.side_effect = lambda _id: (time.sleep(.15), [])[1]
                self.client = lambda: self.api

        panel = Panel()
        project = panel.add_tree_item(None, "project", {"id": 1}, "Test", lazy=True)
        loop = QtCore.QEventLoop()
        QtCore.QTimer.singleShot(10, lambda: project.setExpanded(True))
        QtCore.QTimer.singleShot(40, panel.browser_tree.clear)
        QtCore.QTimer.singleShot(260, loop.quit)
        loop.exec_()
        self.assertEqual(panel.api.get_parts.call_count, 1)
        self.assertEqual(panel.browser_tree.topLevelItemCount(), 0)
