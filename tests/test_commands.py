import unittest

from freecad_plm_addon.commands import (
    ActivateConnectionCommand,
    CancelCheckoutCommand,
    CheckoutCommand,
    CheckinCommand,
    ConnectCommand,
    CreateAnnotationCommand,
    RefreshCommand,
)

from pathlib import Path


class CommandResourceTests(unittest.TestCase):
    def test_toolbar_commands_have_pixmaps(self):
        commands = [
            ActivateConnectionCommand(),
            ConnectCommand(),
            RefreshCommand(),
            CheckoutCommand(),
            CheckinCommand(),
            CancelCheckoutCommand(),
            CreateAnnotationCommand(),
        ]

        for command in commands:
            with self.subTest(command=command.__class__.__name__):
                resources = command.GetResources()
                self.assertIn("MenuText", resources)
                self.assertIn("ToolTip", resources)
                self.assertIn("Pixmap", resources)
                self.assertTrue(resources["Pixmap"])

    def test_connection_commands_use_local_icons(self):
        commands = [
            ActivateConnectionCommand(),
            ConnectCommand(),
        ]

        for command in commands:
            with self.subTest(command=command.__class__.__name__):
                resources = command.GetResources()
                self.assertTrue(Path(resources["Pixmap"]).is_file())


if __name__ == "__main__":
    unittest.main()
