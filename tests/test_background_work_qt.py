import threading
import time
import tempfile
from pathlib import Path
from unittest.mock import Mock
import unittest

try:
    from PySide6 import QtCore, QtWidgets
except ImportError:
    QtCore = QtWidgets = None

from freecad_plm_addon.background_work import run_background_work
from freecad_plm_addon.panel_browser import PanelBrowserMixin
from freecad_plm_addon.panel_projects import PanelProjectsMixin
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
                self.api.get_parts.side_effect = lambda _id: (time.sleep(.2), [])[1]
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
