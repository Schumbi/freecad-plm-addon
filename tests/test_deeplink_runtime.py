import unittest
from unittest.mock import Mock, patch

from freecad_plm_addon.deeplink import RevisionDeepLink
from freecad_plm_addon.deeplink_runtime import (
    deep_link_event_value,
    dispatch_deep_link,
    install_deep_link_runtime,
    reset_runtime_state_for_tests,
)


DEEPLINK = "freecad-plm://revision/17?project_id=2&part_id=9&action=checkout"


class FakeUrl:
    def __init__(self, value):
        self.value = value

    def toString(self):
        return self.value


class FakeEvent:
    def __init__(self, value, event_type=42):
        self.value = value
        self.event_type = event_type

    def type(self):
        return self.event_type

    def url(self):
        return FakeUrl(self.value)

    def file(self):
        return self.value


class FakeQObject:
    def __init__(self, *_args):
        pass

    def eventFilter(self, _watched, _event):
        return False


class FakeQEvent:
    class Type:
        FileOpen = 42


class FakeQTimer:
    @staticmethod
    def singleShot(_delay, callback):
        callback()


class FakeQtCore:
    QObject = FakeQObject
    QEvent = FakeQEvent
    QTimer = FakeQTimer


class FakeApplication:
    def __init__(self):
        self.event_filter = None

    def installEventFilter(self, event_filter):
        self.event_filter = event_filter


class FakeQApplication:
    application = FakeApplication()

    @classmethod
    def instance(cls):
        return cls.application


class DeepLinkRuntimeTests(unittest.TestCase):
    def setUp(self):
        reset_runtime_state_for_tests()

    def test_dispatches_valid_link_and_suppresses_only_immediate_duplicate(self):
        opener = Mock()

        self.assertTrue(dispatch_deep_link(DEEPLINK, opener=opener, now=10))
        self.assertFalse(dispatch_deep_link(DEEPLINK, opener=opener, now=11))
        self.assertTrue(dispatch_deep_link(DEEPLINK, opener=opener, now=13))

        self.assertEqual(opener.call_count, 2)
        opener.assert_called_with(RevisionDeepLink(2, 9, 17, "checkout"))

    def test_extracts_deep_link_from_file_open_event(self):
        self.assertEqual(deep_link_event_value(FakeEvent(DEEPLINK)), DEEPLINK)
        self.assertEqual(deep_link_event_value(FakeEvent("/tmp/model.FCStd")), "")

    def test_installs_file_open_filter_for_running_freecad(self):
        FakeQApplication.application = FakeApplication()
        with (
            patch(
                "freecad_plm_addon.deeplink_runtime._load_qt",
                return_value=(FakeQtCore, FakeQApplication),
            ),
            patch("freecad_plm_addon.deeplink_runtime.dispatch_deep_link") as dispatch,
        ):
            self.assertTrue(install_deep_link_runtime(arguments=["FreeCAD"]))
            handled = FakeQApplication.application.event_filter.eventFilter(
                None,
                FakeEvent(DEEPLINK),
            )

        self.assertTrue(handled)
        dispatch.assert_called_once_with(DEEPLINK)

    def test_dispatches_startup_argument_without_workbench_activation(self):
        FakeQApplication.application = FakeApplication()
        with (
            patch(
                "freecad_plm_addon.deeplink_runtime._load_qt",
                return_value=(FakeQtCore, FakeQApplication),
            ),
            patch("freecad_plm_addon.deeplink_runtime.dispatch_deep_link") as dispatch,
        ):
            install_deep_link_runtime(arguments=["FreeCAD", DEEPLINK])

        dispatch.assert_called_once_with(DEEPLINK)


if __name__ == "__main__":
    unittest.main()
