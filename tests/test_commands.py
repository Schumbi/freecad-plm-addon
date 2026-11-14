import unittest
from types import SimpleNamespace

from freecad_plm_addon.commands import (
    ActivateConnectionCommand,
    CancelCheckoutCommand,
    CheckoutCommand,
    CheckinCommand,
    CreateAnnotationCommand,
    OpenDeepLinkCommand,
    OpenInSlicerCommand,
    RefreshCommand,
    SetupProtocolHandlerCommand,
)

from pathlib import Path


class CommandResourceTests(unittest.TestCase):
    def test_toolbar_commands_have_pixmaps(self):
        commands = [
            ActivateConnectionCommand(),
            RefreshCommand(),
            CheckoutCommand(),
            CheckinCommand(),
            CancelCheckoutCommand(),
            CreateAnnotationCommand(),
            OpenInSlicerCommand(),
            OpenDeepLinkCommand(),
            SetupProtocolHandlerCommand(),
        ]

        for command in commands:
            with self.subTest(command=command.__class__.__name__):
                resources = command.GetResources()
                self.assertIn("MenuText", resources)
                self.assertIn("ToolTip", resources)
                self.assertIn("Pixmap", resources)
                self.assertTrue(resources["Pixmap"])

    def test_commands_with_packaged_icons_reference_existing_files(self):
        commands = [
            ActivateConnectionCommand(),
            OpenInSlicerCommand(),
            OpenDeepLinkCommand(),
            SetupProtocolHandlerCommand(),
        ]

        for command in commands:
            with self.subTest(command=command.__class__.__name__):
                resources = command.GetResources()
                self.assertTrue(Path(resources["Pixmap"]).is_file())


if __name__ == "__main__":
    unittest.main()


class CommandEnablementTests(unittest.TestCase):
    def _panel(self, **overrides):
        from types import SimpleNamespace
        from unittest.mock import Mock

        panel = SimpleNamespace(
            selected_revision=Mock(return_value={"id": 1, "file_format": "fcstd"}),
            active_checkout_id=Mock(return_value=None),
            server_url=SimpleNamespace(text=lambda: "https://plm.example"),
            api_token=SimpleNamespace(text=lambda: "plm_pat_x"),
        )
        for key, value in overrides.items():
            setattr(panel, key, value)
        return panel

    def test_checkout_requires_editable_revision(self):
        from unittest.mock import patch

        with patch("freecad_plm_addon.commands.active_panel", return_value=None):
            self.assertFalse(CheckoutCommand().IsActive())
        with patch("freecad_plm_addon.commands.active_panel", return_value=self._panel()):
            self.assertTrue(CheckoutCommand().IsActive())
        panel = self._panel(selected_revision=lambda: {"id": 2, "file_format": "stl"})
        with patch("freecad_plm_addon.commands.active_panel", return_value=panel):
            self.assertFalse(CheckoutCommand().IsActive())

    def test_checkin_and_cancel_require_active_checkout(self):
        from unittest.mock import patch

        with patch("freecad_plm_addon.commands.active_panel", return_value=self._panel()):
            self.assertFalse(CheckinCommand().IsActive())
            self.assertFalse(CancelCheckoutCommand().IsActive())
        panel = self._panel(active_checkout_id=lambda: 7)
        with patch("freecad_plm_addon.commands.active_panel", return_value=panel):
            self.assertTrue(CheckinCommand().IsActive())
            self.assertTrue(CancelCheckoutCommand().IsActive())

    def test_annotation_requires_revision(self):
        from unittest.mock import patch

        with patch("freecad_plm_addon.commands.active_panel", return_value=self._panel()):
            self.assertTrue(CreateAnnotationCommand().IsActive())
        panel = self._panel(selected_revision=lambda: None)
        with patch("freecad_plm_addon.commands.active_panel", return_value=panel):
            self.assertFalse(CreateAnnotationCommand().IsActive())

    def test_refresh_requires_connection_settings(self):
        from unittest.mock import patch

        panel = self._panel(api_token=SimpleNamespace(text=lambda: ""))
        with patch("freecad_plm_addon.commands.active_panel", return_value=panel):
            self.assertFalse(RefreshCommand().IsActive())
