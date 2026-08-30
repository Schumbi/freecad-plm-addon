import tempfile
import unittest
import subprocess
import sys
from pathlib import Path

from freecad_plm_addon.protocol_handler import (
    LINUX_DESKTOP_ID,
    LINK_FILE_MAGIC,
    LINK_FILE_SUFFIX,
    MIME_TYPE,
    WINDOWS_CLASS_KEY,
    linux_desktop_entry,
    protocol_launcher_script,
    register_linux_protocol_handler,
    register_windows_protocol_handler,
    windows_handler_command,
)


class FakeRunner:
    def __init__(self, *, flatpak=False):
        self.flatpak = flatpak
        self.commands = []

    def __call__(self, command, **_kwargs):
        self.commands.append(list(command))
        if command[-2:] == ["printenv", "HOME"]:
            return Result(stdout=self.host_home)
        if command[-2:] == ["printenv", "XDG_DATA_HOME"]:
            return Result(returncode=1)
        if "query" in command:
            return Result(stdout=f"{LINUX_DESKTOP_ID}\n")
        return Result()


class Result:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class FakeRegistryKey:
    def __init__(self, path):
        self.path = path

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class FakeWinreg:
    HKEY_CURRENT_USER = "HKCU"
    REG_SZ = 1

    def __init__(self):
        self.values = []

    def CreateKey(self, root, path):
        self.values.append(("create", root, path))
        return FakeRegistryKey(path)

    def SetValueEx(self, key, name, _reserved, kind, value):
        self.values.append(("value", key.path, name, kind, value))


class ProtocolHandlerTests(unittest.TestCase):
    def test_linux_desktop_entry_uses_uri_placeholder_without_shell(self):
        entry = linux_desktop_entry(
            ["/opt/Free CAD/FreeCAD", "--single-instance"]
        )

        self.assertIn(
            'Exec="/opt/Free CAD/FreeCAD" "--single-instance" %u',
            entry,
        )
        self.assertIn(f"MimeType={MIME_TYPE};", entry)

    def test_registers_native_linux_handler_in_user_data_home(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            runner = FakeRunner()
            result = register_linux_protocol_handler(
                executable="/opt/FreeCAD/bin/FreeCAD",
                environ={"XDG_DATA_HOME": temp_dir},
                runner=runner,
                home=temp_dir,
            )

            desktop_path = Path(temp_dir) / "applications" / LINUX_DESKTOP_ID
            self.assertTrue(result.success)
            self.assertEqual(result.handler, str(desktop_path))
            launcher_path = Path(temp_dir) / "freecad-plm" / "protocol_launcher.py"
            self.assertIn(str(launcher_path), desktop_path.read_text())
            self.assertIn("/opt/FreeCAD/bin/FreeCAD", launcher_path.read_text())
            self.assertIn(
                ["xdg-mime", "default", LINUX_DESKTOP_ID, MIME_TYPE],
                runner.commands,
            )

    def test_registers_flatpak_handler_on_host(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            runner = FakeRunner(flatpak=True)
            runner.host_home = temp_dir
            result = register_linux_protocol_handler(
                environ={"FLATPAK_ID": "org.freecad.FreeCAD"},
                runner=runner,
            )

            desktop_path = Path(temp_dir) / ".local/share/applications" / LINUX_DESKTOP_ID
            content = desktop_path.read_text()
            self.assertTrue(result.success)
            launcher_path = Path(temp_dir) / ".local/share/freecad-plm/protocol_launcher.py"
            self.assertIn(str(launcher_path), content)
            self.assertIn("org.freecad.FreeCAD", launcher_path.read_text())
            self.assertIn(
                [
                    "flatpak-spawn",
                    "--host",
                    "xdg-mime",
                    "default",
                    LINUX_DESKTOP_ID,
                    MIME_TYPE,
                ],
                runner.commands,
            )

    def test_windows_command_quotes_python_launcher_and_uri(self):
        self.assertEqual(
            windows_handler_command(
                r"C:\Program Files\FreeCAD\bin\pythonw.exe",
                r"C:\Users\Ralf\AppData\Local\FreeCAD-PLM\protocol_launcher.py",
            ),
            r'"C:\Program Files\FreeCAD\bin\pythonw.exe" "C:\Users\Ralf\AppData\Local\FreeCAD-PLM\protocol_launcher.py" "%1"',
        )

    def test_registers_windows_scheme_for_current_user(self):
        registry = FakeWinreg()
        executable = r"C:\Program Files\FreeCAD\bin\FreeCAD.exe"

        with tempfile.TemporaryDirectory() as temp_dir:
            result = register_windows_protocol_handler(
                executable=executable,
                python_executable=r"C:\Program Files\FreeCAD\bin\pythonw.exe",
                winreg_module=registry,
                local_app_data=temp_dir,
            )

            launcher_path = Path(temp_dir) / "FreeCAD-PLM" / "protocol_launcher.py"
            self.assertTrue(launcher_path.exists())

        self.assertTrue(result.success)
        self.assertIn(
            (
                "value",
                rf"{WINDOWS_CLASS_KEY}\shell\open\command",
                "",
                registry.REG_SZ,
                windows_handler_command(
                    r"C:\Program Files\FreeCAD\bin\pythonw.exe",
                    launcher_path,
                ),
            ),
            registry.values,
        )

    def test_launcher_creates_link_file_and_invokes_freecad_with_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            capture_path = temp_path / "captured.txt"
            fake_freecad = temp_path / "fake_freecad.py"
            fake_freecad.write_text(
                "import pathlib, sys\n"
                f"pathlib.Path({str(capture_path)!r}).write_text(sys.argv[-1])\n",
                encoding="utf-8",
            )
            launcher = temp_path / "launcher.py"
            launcher.write_text(
                protocol_launcher_script(
                    [sys.executable, str(fake_freecad), "--single-instance"],
                    temp_path / "links",
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(launcher), "freecad-plm://revision/17?action=checkout"],
                check=False,
            )
            for _attempt in range(100):
                if capture_path.exists():
                    break
                import time

                time.sleep(0.01)

            self.assertEqual(result.returncode, 0)
            link_path = Path(capture_path.read_text())
            self.assertEqual(link_path.suffix, LINK_FILE_SUFFIX)
            self.assertEqual(
                link_path.read_text(encoding="utf-8"),
                f"{LINK_FILE_MAGIC}\nfreecad-plm://revision/17?action=checkout\n",
            )


if __name__ == "__main__":
    unittest.main()
