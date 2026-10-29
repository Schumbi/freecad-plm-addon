"""Run file/network work while Qt continues processing its event loop."""
from concurrent.futures import ThreadPoolExecutor


_ui_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="plm-ui")


def run_gui_work(qt_core, parent, work, finished, *, track_network=True):
    """Run pure file/network work off-thread and deliver its result on the Qt thread."""
    panel = getattr(parent, "_plm_panel", None) if track_network else None
    if panel is not None:
        panel.begin_network_activity()
    future = _ui_executor.submit(work)
    timer = qt_core.QTimer(parent)

    def poll():
        if not future.done():
            return
        timer.stop()
        timer.deleteLater()
        try:
            result, error = future.result(), None
        except Exception as exc:
            result, error = None, exc
        try:
            finished(result, error)
        finally:
            if panel is not None:
                panel.end_network_activity()

    timer.timeout.connect(poll)
    timer.start(50)
    return future


def run_network_call(qt_core, parent, work):
    """Keep Qt processing events while a legacy synchronous action awaits HTTP."""
    loop = qt_core.QEventLoop(parent)
    outcome = []

    def finished(result, error):
        outcome.append((result, error))
        loop.quit()

    run_gui_work(qt_core, parent, work, finished)
    if not outcome:
        loop.exec_()
    result, error = outcome[0]
    if error is not None:
        raise error
    return result


class GuiNetworkClient:
    """Run every PLMClient request off the Qt thread, including legacy callers."""

    def __init__(self, client, qt_core, parent):
        self._client = client
        self._qt_core = qt_core
        self._parent = parent
        self._gui_thread = qt_core.QThread.currentThread()

    def __getattr__(self, name):
        attribute = getattr(self._client, name)
        if not callable(attribute) or name.startswith("_"):
            return attribute

        def call(*args, **kwargs):
            if self._qt_core.QThread.currentThread() != self._gui_thread:
                return attribute(*args, **kwargs)
            return run_network_call(
                self._qt_core, self._parent,
                lambda: attribute(*args, **kwargs),
            )

        return call


def run_background_work(qt_core, qt_widgets, parent, message, work, *, track_network=True):
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
    panel = getattr(parent, "_plm_panel", None) if track_network else None
    if panel is not None:
        panel.begin_network_activity()
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
        if panel is not None:
            panel.end_network_activity()
