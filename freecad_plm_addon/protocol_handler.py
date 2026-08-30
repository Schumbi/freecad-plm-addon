import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath


SCHEME = "freecad-plm"
MIME_TYPE = f"x-scheme-handler/{SCHEME}"
LINUX_DESKTOP_ID = "freecad-plm-handler.desktop"
WINDOWS_CLASS_KEY = rf"Software\Classes\{SCHEME}"
LINK_FILE_SUFFIX = ".FCPLMLink"
LINK_FILE_MAGIC = "FREECAD-PLM-LINK/1"
LAUNCHER_FILENAME = "protocol_launcher.py"


@dataclass(frozen=True)
class ProtocolRegistrationResult:
    success: bool
    platform: str
    changed: bool
    message: str
    handler: str = ""


def _completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def _run(command, runner=None):
    runner = runner or subprocess.run
    try:
        return runner(
            list(command),
            check=False,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return _completed(returncode=1, stderr=str(exc))


def _desktop_quote(value):
    escaped = (
        str(value)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("`", "\\`")
        .replace("$", "\\$")
        .replace("%", "%%")
    )
    return f'"{escaped}"'


def linux_desktop_entry(command):
    exec_line = " ".join(_desktop_quote(value) for value in command)
    return "\n".join(
        (
            "[Desktop Entry]",
            "Type=Application",
            "Name=FreeCAD-PLM Link Handler",
            "Comment=Open FreeCAD-PLM revision links in FreeCAD",
            f"Exec={exec_line} %u",
            "NoDisplay=true",
            "Terminal=false",
            f"MimeType={MIME_TYPE};",
            "Categories=Graphics;Engineering;",
            "",
        )
    )


def protocol_launcher_script(launch_command, inbox_dir):
    """Return a dependency-free launcher used by Linux and Windows URL handlers.

    A URL must not be handed to FreeCAD directly: FreeCAD's single-instance IPC
    treats every positional argument as a filesystem path.  The launcher therefore
    stores the URL in a tiny, one-shot link file.  FreeCAD can forward that file to
    an existing instance, where the add-on's registered importer consumes it.
    """

    command_json = json.dumps([str(value) for value in launch_command], ensure_ascii=True)
    inbox_json = json.dumps(str(inbox_dir), ensure_ascii=True)
    return f'''#!/usr/bin/env python3
import json
import subprocess
import sys
import uuid
from pathlib import Path

SCHEME_PREFIX = "{SCHEME}://"
MAGIC = "{LINK_FILE_MAGIC}"
SUFFIX = "{LINK_FILE_SUFFIX}"
COMMAND = json.loads({json.dumps(command_json)})
INBOX = Path(json.loads({json.dumps(inbox_json)}))


def main():
    if len(sys.argv) != 2:
        return 2
    url = sys.argv[1].strip()
    if not url.lower().startswith(SCHEME_PREFIX) or len(url) > 8192:
        return 2
    INBOX.mkdir(parents=True, exist_ok=True)
    link_path = INBOX / (uuid.uuid4().hex + SUFFIX)
    link_path.write_text(MAGIC + "\\n" + url + "\\n", encoding="utf-8")
    try:
        subprocess.Popen(COMMAND + [str(link_path)], close_fds=True)
    except Exception as exc:
        try:
            link_path.unlink()
            (INBOX.parent / "protocol-handler.log").write_text(
                str(exc) + "\\n", encoding="utf-8"
            )
        except OSError:
            pass
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def _write_launcher(path, launch_command, inbox_dir):
    content = protocol_launcher_script(launch_command, inbox_dir)
    old_content = path.read_text(encoding="utf-8") if path.exists() else ""
    changed = old_content != content
    if changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        path.chmod(0o755)
    return changed


def _host_environment_value(name, runner):
    result = _run(("flatpak-spawn", "--host", "printenv", name), runner)
    if result.returncode == 0:
        return result.stdout.strip()
    return ""


def _native_freecad_executable(executable=None):
    candidates = []
    if executable:
        candidates.append(str(executable))
    candidates.extend(
        value
        for value in (
            shutil.which("FreeCAD"),
            shutil.which("freecad"),
        )
        if value
    )
    for candidate in candidates:
        name = Path(candidate).name.lower()
        if "freecad" in name and "freecadcmd" not in name:
            return candidate
    return ""


def register_linux_protocol_handler(
    *,
    executable=None,
    environ=None,
    runner=None,
    home=None,
):
    environ = dict(os.environ if environ is None else environ)
    flatpak_id = environ.get("FLATPAK_ID", "").strip()
    host_prefix = []
    if flatpak_id:
        host_prefix = ["flatpak-spawn", "--host"]
        host_home = _host_environment_value("HOME", runner)
        home = Path(host_home or home or Path.home())
        host_xdg_data_home = _host_environment_value("XDG_DATA_HOME", runner)
        data_home = Path(host_xdg_data_home) if host_xdg_data_home else home / ".local/share"
        freecad_command = [
            "/usr/bin/flatpak",
            "run",
            flatpak_id,
            "-",
            "--single-instance",
        ]
    else:
        home = Path(home or Path.home())
        data_home = Path(environ.get("XDG_DATA_HOME") or home / ".local/share")
        freecad_executable = _native_freecad_executable(executable)
        if not freecad_executable:
            return ProtocolRegistrationResult(
                False,
                "linux",
                False,
                "FreeCAD-Programmdatei wurde nicht gefunden.",
            )
        freecad_command = [freecad_executable, "--single-instance"]

    applications_dir = data_home / "applications"
    handler_dir = data_home / "freecad-plm"
    launcher_path = handler_dir / LAUNCHER_FILENAME
    inbox_dir = handler_dir / "links"
    desktop_path = applications_dir / LINUX_DESKTOP_ID
    try:
        launcher_changed = _write_launcher(launcher_path, freecad_command, inbox_dir)
        desktop_content = linux_desktop_entry(["/usr/bin/python3", str(launcher_path)])
        applications_dir.mkdir(parents=True, exist_ok=True)
        old_content = desktop_path.read_text(encoding="utf-8") if desktop_path.exists() else ""
        desktop_changed = old_content != desktop_content
        if desktop_changed:
            desktop_path.write_text(desktop_content, encoding="utf-8")
            desktop_path.chmod(0o644)
        changed = launcher_changed or desktop_changed
    except OSError as exc:
        return ProtocolRegistrationResult(
            False,
            "linux",
            False,
            f"Desktop-Handler konnte nicht geschrieben werden: {exc}",
        )

    _run((*host_prefix, "update-desktop-database", str(applications_dir)), runner)
    assignment = _run(
        (*host_prefix, "xdg-mime", "default", LINUX_DESKTOP_ID, MIME_TYPE),
        runner,
    )
    if assignment.returncode != 0:
        return ProtocolRegistrationResult(
            False,
            "linux",
            changed,
            "xdg-mime konnte den FreeCAD-PLM-Handler nicht registrieren: "
            f"{assignment.stderr.strip() or 'unbekannter Fehler'}",
            str(desktop_path),
        )
    query = _run((*host_prefix, "xdg-mime", "query", "default", MIME_TYPE), runner)
    registered = query.returncode == 0 and query.stdout.strip() == LINUX_DESKTOP_ID
    return ProtocolRegistrationResult(
        registered,
        "linux",
        changed,
        (
            "FreeCAD-PLM-Weblinks sind für diesen Benutzer eingerichtet."
            if registered
            else "Die Registrierung des FreeCAD-PLM-Handlers konnte nicht bestätigt werden."
        ),
        str(desktop_path),
    )


def windows_handler_command(python_executable, launcher_path):
    values = (str(python_executable), str(launcher_path))
    if any('"' in value for value in values):
        raise ValueError("Ein Programmpfad enthält ein ungültiges Anführungszeichen.")
    return f'"{values[0]}" "{values[1]}" "%1"'


def _windows_freecad_executable(executable=None):
    candidates = [str(executable)] if executable else []
    candidates.append(sys.executable)
    try:
        import FreeCAD

        home_path = Path(FreeCAD.getHomePath())
        candidates.extend((home_path / "bin/FreeCAD.exe", home_path / "FreeCAD.exe"))
    except (ImportError, AttributeError, TypeError):
        pass
    for candidate in candidates:
        path = PureWindowsPath(candidate)
        if path.name.lower() == "freecad.exe":
            return str(path)
    return ""


def _windows_python_executable(freecad_executable, executable=None):
    candidates = [str(executable)] if executable else []
    bin_dir = PureWindowsPath(freecad_executable).parent
    candidates.extend((str(bin_dir / "pythonw.exe"), str(bin_dir / "python.exe")))
    matching = []
    for candidate in candidates:
        if PureWindowsPath(candidate).name.lower() in {"pythonw.exe", "python.exe"}:
            matching.append(str(PureWindowsPath(candidate)))
    if sys.platform.startswith("win"):
        for candidate in matching:
            if Path(candidate).is_file():
                return candidate
        return ""
    if matching:
        return matching[0]
    return ""


def register_windows_protocol_handler(
    *,
    executable=None,
    python_executable=None,
    winreg_module=None,
    local_app_data=None,
):
    if winreg_module is None:
        try:
            import winreg as winreg_module
        except ImportError:
            return ProtocolRegistrationResult(
                False,
                "windows",
                False,
                "Die Windows-Registry ist in dieser Laufzeit nicht verfügbar.",
            )
    freecad_executable = _windows_freecad_executable(executable)
    if not freecad_executable:
        return ProtocolRegistrationResult(
            False,
            "windows",
            False,
            "FreeCAD.exe wurde nicht gefunden.",
        )
    python_executable = _windows_python_executable(
        freecad_executable,
        executable=python_executable,
    )
    if not python_executable:
        return ProtocolRegistrationResult(
            False,
            "windows",
            False,
            "Die mit FreeCAD gelieferte Python-Laufzeit wurde nicht gefunden.",
        )
    local_app_data = local_app_data or os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        return ProtocolRegistrationResult(
            False,
            "windows",
            False,
            "LOCALAPPDATA ist nicht gesetzt.",
        )
    handler_dir = Path(local_app_data) / "FreeCAD-PLM"
    launcher_path = handler_dir / LAUNCHER_FILENAME
    inbox_dir = handler_dir / "links"
    try:
        launcher_changed = _write_launcher(
            launcher_path,
            [freecad_executable, "--single-instance"],
            inbox_dir,
        )
    except OSError as exc:
        return ProtocolRegistrationResult(
            False,
            "windows",
            False,
            f"Windows-Handler konnte nicht geschrieben werden: {exc}",
        )
    command = windows_handler_command(python_executable, launcher_path)
    values = (
        (WINDOWS_CLASS_KEY, "", "URL:FreeCAD-PLM Protocol"),
        (WINDOWS_CLASS_KEY, "URL Protocol", ""),
        (rf"{WINDOWS_CLASS_KEY}\DefaultIcon", "", f'"{freecad_executable}",0'),
        (rf"{WINDOWS_CLASS_KEY}\shell\open\command", "", command),
    )
    try:
        for key_path, name, value in values:
            with winreg_module.CreateKey(winreg_module.HKEY_CURRENT_USER, key_path) as key:
                winreg_module.SetValueEx(
                    key,
                    name,
                    0,
                    winreg_module.REG_SZ,
                    value,
                )
    except OSError as exc:
        return ProtocolRegistrationResult(
            False,
            "windows",
            False,
            f"Windows-Handler konnte nicht registriert werden: {exc}",
        )
    return ProtocolRegistrationResult(
        True,
        "windows",
        launcher_changed,
        "FreeCAD-PLM-Weblinks sind für diesen Windows-Benutzer eingerichtet.",
        command,
    )


def register_protocol_handler(*, platform=None, executable=None):
    platform = platform or sys.platform
    if platform.startswith("win"):
        return register_windows_protocol_handler(executable=executable)
    if platform.startswith("linux"):
        return register_linux_protocol_handler(executable=executable)
    return ProtocolRegistrationResult(
        False,
        platform,
        False,
        "Automatische Weblink-Registrierung wird auf diesem Betriebssystem noch nicht unterstützt.",
    )
