"""Run file/network work while Qt continues processing its event loop."""
from concurrent.futures import ThreadPoolExecutor


def run_background_work(qt_core, qt_widgets, parent, message, work):
    class WorkDialog(qt_widgets.QDialog):
        def reject(self):
            # Upload results must be observed before allowing another check-in.
            pass

    dialog = WorkDialog(parent)
    dialog.setWindowTitle("Einchecken")
    dialog.setWindowFlags(dialog.windowFlags() & ~qt_core.Qt.WindowCloseButtonHint)
    dialog.setWindowModality(qt_core.Qt.ApplicationModal)
    layout = qt_widgets.QVBoxLayout(dialog)
    layout.addWidget(qt_widgets.QLabel(message, dialog))
    bar = qt_widgets.QProgressBar(dialog)
    bar.setRange(0, 0)
    layout.addWidget(bar)
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="plm-checkin")
    future = executor.submit(work)
    timer = qt_core.QTimer(dialog)
    timer.timeout.connect(lambda: dialog.accept() if future.done() else None)
    timer.start(50)
    try:
        dialog.exec_()
        return future.result()
    finally:
        timer.stop()
        executor.shutdown(wait=False)
        dialog.deleteLater()
