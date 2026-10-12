import threading
import time
import unittest

try:
    from PySide6 import QtCore, QtWidgets
except ImportError:
    QtCore = QtWidgets = None

from freecad_plm_addon.background_work import run_background_work


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
