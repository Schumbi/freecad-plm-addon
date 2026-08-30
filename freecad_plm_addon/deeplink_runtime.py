import sys
import time

from .deeplink import DEEPLINK_SCHEME, deep_link_from_argv, parse_revision_deep_link


DUPLICATE_WINDOW_SECONDS = 2.0
_event_filter = None
_recent_links = {}


def dispatch_deep_link(value, *, opener=None, now=None):
    raw_value = str(value or "").strip()
    deep_link = parse_revision_deep_link(raw_value)
    timestamp = time.monotonic() if now is None else float(now)
    expired = [
        link
        for link, handled_at in _recent_links.items()
        if timestamp - handled_at > DUPLICATE_WINDOW_SECONDS
    ]
    for link in expired:
        _recent_links.pop(link, None)
    if raw_value in _recent_links:
        return False
    _recent_links[raw_value] = timestamp
    if opener is None:
        from .panel import open_revision_deep_link

        opener = open_revision_deep_link
    opener(deep_link)
    return True


def deep_link_event_value(event):
    url_method = getattr(event, "url", None)
    if callable(url_method):
        url = url_method()
        to_string = getattr(url, "toString", None)
        if callable(to_string):
            value = to_string()
            if str(value or "").lower().startswith(f"{DEEPLINK_SCHEME}://"):
                return str(value)
    file_method = getattr(event, "file", None)
    if callable(file_method):
        value = file_method()
        if str(value or "").lower().startswith(f"{DEEPLINK_SCHEME}://"):
            return str(value)
    return ""


def _load_qt():
    try:
        from PySide import QtCore, QtGui

        return QtCore, QtGui.QApplication
    except ImportError:
        pass
    try:
        from PySide6 import QtCore, QtWidgets

        return QtCore, QtWidgets.QApplication
    except ImportError:
        from PySide2 import QtCore, QtWidgets

        return QtCore, QtWidgets.QApplication


def queue_deep_link(value):
    QtCore, _QApplication = _load_qt()
    QtCore.QTimer.singleShot(0, lambda: dispatch_deep_link(value))


def install_deep_link_runtime(arguments=None):
    global _event_filter
    QtCore, QApplication = _load_qt()
    application = QApplication.instance()
    if application is None:
        return False
    file_open_type = getattr(getattr(QtCore.QEvent, "Type", QtCore.QEvent), "FileOpen")

    class DeepLinkEventFilter(QtCore.QObject):
        def eventFilter(self, watched, event):
            if event.type() == file_open_type:
                value = deep_link_event_value(event)
                if value:
                    try:
                        dispatch_deep_link(value)
                    except ValueError:
                        return False
                    return True
            return super().eventFilter(watched, event)

    if _event_filter is None:
        _event_filter = DeepLinkEventFilter(application)
        application.installEventFilter(_event_filter)

    try:
        startup_link = deep_link_from_argv(sys.argv if arguments is None else arguments)
    except ValueError:
        startup_link = None
    if startup_link is not None:
        raw_value = next(
            str(argument)
            for argument in (sys.argv if arguments is None else arguments)
            if str(argument).lower().startswith(f"{DEEPLINK_SCHEME}://")
        )
        queue_deep_link(raw_value)
    return True


def reset_runtime_state_for_tests():
    global _event_filter
    _event_filter = None
    _recent_links.clear()
