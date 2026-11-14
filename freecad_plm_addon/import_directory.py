"""Import a local directory into FreeCAD-PLM.

This module is intentionally independent of FreeCAD itself so it can be used by
the Nemo file manager. It reuses the add-on's HTTP client and token
configuration, builds a ZIP from the selected folder and submits it to the PLM
project import API.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import webbrowser
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Sequence
from urllib.error import URLError
from xml.etree import ElementTree
from zipfile import ZIP_STORED, ZipFile

try:
    from .api_client import PLMClient
    from .errors import (
        AuthenticationError,
        PermissionDeniedError,
        PLMError,
    )
except ImportError:  # Direct execution: python freecad_plm_addon/import_directory.py
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from freecad_plm_addon.api_client import PLMClient
    from freecad_plm_addon.errors import (
        AuthenticationError,
        PermissionDeniedError,
        PLMError,
    )


PROJECT_SUFFIXES = {".fcstd", ".step", ".stp", ".stl"}
FCSTD_SUFFIX = ".fcstd"
EXTERNAL_SUFFIXES = {".step", ".stp", ".stl"}

DEFAULT_EXCLUDED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
}

DEFAULT_EXCLUDED_FILE_PATTERNS = (
    ".ds_store",
    "thumbs.db",
    "desktop.ini",
    "~$*",
    ".~lock.*",
    "*.lck",
    "*.pyc",
    "*.pyo",
    "checkout.json",
    "*.fcstd[0-9]*",
    "*.fcbak",
    "*.fcstd.bak",
)

DEFAULT_CONFIG_PATH = (
    Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    / "freecad-plm"
    / "nemo-import.json"
)
DEFAULT_LOG_PATH = (
    Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local" / "state")))
    / "freecad-plm"
    / "nemo-import.log"
)

ZENITY_BIN = os.environ.get("ZENITY_BIN", "zenity")


class ImportValidationError(Exception):
    """The selected folder or its files cannot be imported."""


class ConfigError(Exception):
    """No usable PLM server configuration was found."""


@dataclass(frozen=True)
class ScanLimits:
    max_zip_bytes: int = 500 * 1024 * 1024
    max_members: int = 2000
    max_uncompressed_bytes: int = 2 * 1024 * 1024 * 1024
    max_member_bytes: int = 200 * 1024 * 1024
    max_path_length: int = 500
    max_name_length: int = 255


@dataclass(frozen=True)
class ImportFile:
    path: Path
    relative_path: str
    size: int
    kind: str  # "fcstd", "external" or "document"


@dataclass
class ImportScan:
    folder: Path
    files: list[ImportFile] = field(default_factory=list)
    excluded_files: int = 0
    skipped_symlinks: int = 0
    pruned_dirs: list[str] = field(default_factory=list)
    omitted_documents: int = 0

    @property
    def fcstd_files(self) -> list[ImportFile]:
        return [item for item in self.files if item.kind == "fcstd"]

    @property
    def external_files(self) -> list[ImportFile]:
        return [item for item in self.files if item.kind == "external"]

    @property
    def document_files(self) -> list[ImportFile]:
        return [item for item in self.files if item.kind == "document"]

    @property
    def total_size(self) -> int:
        return sum(item.size for item in self.files)


class DependencyRootRequired(ImportValidationError):
    def __init__(self, message: str, candidates: Sequence[str]) -> None:
        super().__init__(message)
        self.candidates = tuple(candidates)


@dataclass
class PLMConfig:
    server_url: str
    api_token: str
    exclude_patterns: list[str] = field(default_factory=list)
    open_browser: bool = False


def _matches_file_pattern(name: str, relative_path: str, patterns: Sequence[str]) -> bool:
    lowered_name = name.lower()
    lowered_path = relative_path.lower()
    for pattern in patterns:
        lowered = pattern.lower()
        if "/" in lowered:
            if fnmatch.fnmatch(lowered_path, lowered):
                return True
        elif fnmatch.fnmatch(lowered_name, lowered):
            return True
    return False


def scan_directory(
    folder: str | Path,
    *,
    include_documents: bool = True,
    exclude_patterns: Sequence[str] | None = None,
) -> ImportScan:
    """Collect importable files from *folder* without following symlinks."""

    folder = Path(folder).expanduser()
    if not folder.is_dir():
        raise ImportValidationError(f"Der Ordner existiert nicht: {folder}")

    patterns = tuple(exclude_patterns or DEFAULT_EXCLUDED_FILE_PATTERNS)
    scan = ImportScan(folder=folder.resolve())

    def on_walk_error(exc: OSError) -> None:
        raise ImportValidationError(
            f"Ordner kann nicht gelesen werden: {exc.filename} ({exc.strerror or exc})"
        )

    for root, dirs, filenames in os.walk(folder, followlinks=False, onerror=on_walk_error):
        root_path = Path(root)
        kept_dirs: list[str] = []
        for dirname in sorted(dirs):
            candidate = root_path / dirname
            relative_dir = candidate.relative_to(folder).as_posix()
            if candidate.is_symlink():
                scan.skipped_symlinks += 1
                continue
            if dirname.lower() in DEFAULT_EXCLUDED_DIRS:
                scan.pruned_dirs.append(relative_dir)
                continue
            kept_dirs.append(dirname)
        dirs[:] = kept_dirs

        for filename in sorted(filenames):
            source = root_path / filename
            relative_path = source.relative_to(folder).as_posix()

            if source.is_symlink():
                scan.skipped_symlinks += 1
                continue
            if _matches_file_pattern(filename, relative_path, patterns):
                scan.excluded_files += 1
                continue
            if not source.is_file():
                continue

            suffix = source.suffix.lower()
            if suffix in EXTERNAL_SUFFIXES:
                kind = "external"
            elif suffix == FCSTD_SUFFIX:
                kind = "fcstd"
            else:
                if not include_documents:
                    scan.omitted_documents += 1
                    continue
                kind = "document"

            try:
                size = source.stat().st_size
            except OSError as exc:
                raise ImportValidationError(
                    f"Datei kann nicht gelesen werden: {relative_path} ({exc})"
                ) from exc
            scan.files.append(
                ImportFile(
                    path=source,
                    relative_path=relative_path,
                    size=size,
                    kind=kind,
                )
            )

    scan.files.sort(key=lambda item: item.relative_path)
    return scan


def validate_scan(scan: ImportScan, limits: ScanLimits = ScanLimits()) -> None:
    """Raise a readable error if the scan cannot be imported."""

    errors: list[str] = []
    if not scan.fcstd_files:
        errors.append("Im Ordner wurde keine .FCStd-Datei gefunden.")

    if len(scan.files) > limits.max_members:
        errors.append(
            f"Zu viele Dateien: {len(scan.files)} (maximal {limits.max_members})."
        )

    total_size = scan.total_size
    estimated_zip_size = scan.total_size + 256 * max(len(scan.files), 1)
    if total_size > limits.max_uncompressed_bytes:
        raise ImportValidationError(
            "Der Ordner ist entpackt zu groß "
            f"({_format_bytes(scan.total_size)}; erlaubt sind "
            f"{_format_bytes(limits.max_uncompressed_bytes)})."
        )
    if estimated_zip_size > limits.max_zip_bytes:
        raise ImportValidationError(
            f"Der geschätzte ZIP-Upload ist zu groß "
            f"({_format_bytes(estimated_zip_size)}; erlaubt sind "
            f"{_format_bytes(limits.max_zip_bytes)})."
        )

    for item in scan.files:
        if item.size > limits.max_member_bytes:
            errors.append(
                f"Datei zu groß: {item.relative_path} "
                f"({_format_bytes(item.size)}; maximal "
                f"{_format_bytes(limits.max_member_bytes)})."
            )
        if len(item.relative_path) > limits.max_path_length:
            errors.append(
                f"Pfad zu lang ({len(item.relative_path)} Zeichen): "
                f"{item.relative_path}"
            )
        if len(Path(item.relative_path).name) > limits.max_name_length:
            errors.append(
                f"Dateiname zu lang: {Path(item.relative_path).name}"
            )

    if errors:
        raise ImportValidationError("\n".join(errors))


def resolve_dependency_root(
    scan: ImportScan,
    requested: str = "",
) -> str:
    """Return the ZIP-relative FCStd root or raise DependencyRootRequired."""

    if not scan.external_files:
        return ""

    fcstd_paths = tuple(item.relative_path for item in scan.fcstd_files)
    if not fcstd_paths:
        raise ImportValidationError(
            "Der Ordner enthält STEP/STL-Dateien, aber keine .FCStd-Datei. "
            "Für diesen Fall bitte den Importdialog im FreeCAD-Addon verwenden."
        )
    if len(fcstd_paths) == 1:
        return fcstd_paths[0]
    if requested:
        requested = str(requested).replace("\\", "/").strip()
        if requested.startswith("./"):
            requested = requested[2:]
        if requested not in fcstd_paths:
            candidate = Path(requested)
            if candidate.is_absolute():
                try:
                    requested = candidate.resolve().relative_to(scan.folder.resolve()).as_posix()
                except ValueError:
                    pass
        if requested not in fcstd_paths:
            raise ImportValidationError(
                f"Die gewählte FreeCAD-Datei gehört nicht zum Import: {requested}"
            )
        return requested
    raise DependencyRootRequired(
        "Bitte die FreeCAD-Datei für die abhängigen STEP-/STL-Dateien auswählen.",
        candidates=fcstd_paths,
    )


def build_import_zip(scan: ImportScan, target: str | Path) -> Path:
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(target, "w", compression=ZIP_STORED) as archive:
        for item in scan.files:
            archive.write(item.path, item.relative_path)
    return target


def derive_project_code(folder_name: str) -> str:
    transliteration = str.maketrans(
        {
            "ä": "ae",
            "ö": "oe",
            "ü": "ue",
            "Ä": "Ae",
            "Ö": "Oe",
            "Ü": "Ue",
            "ß": "ss",
        }
    )
    value = folder_name.translate(transliteration)
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._")
    value = value.upper()[:40].strip("-._")
    return value or f"PROJEKT-{date.today():%Y%m%d}"


def derive_project_name(folder_name: str) -> str:
    return folder_name.strip()[:200] or "Import"


def next_available_code(code: str, existing_codes: Iterable[str]) -> str:
    existing = {item.upper() for item in existing_codes}
    code = code.strip().upper()[:40] or f"PROJEKT-{date.today():%Y%m%d}"
    if code not in existing:
        return code
    base = code[:36].rstrip("-._")
    for index in range(2, 1000):
        suffix = f"-{index}"
        candidate = f"{base[:40 - len(suffix)]}{suffix}"
        if candidate not in existing:
            return candidate
    raise ImportValidationError("Es konnte kein freier Projektcode gefunden werden.")


def default_snapshot_name(existing_project: bool) -> str:
    if existing_project:
        return f"Import {datetime.now():%Y-%m-%d %H:%M}"
    return "Initial"


def validate_project_values(
    code: str,
    name: str,
    snapshot: str,
    *,
    existing_codes: Iterable[str] = (),
) -> tuple[str, str, str]:
    code = code.strip().upper()
    name = name.strip()
    snapshot = snapshot.strip()
    if not code:
        raise ImportValidationError("Projektcode ist erforderlich.")
    if len(code) > 40:
        raise ImportValidationError("Projektcode darf höchstens 40 Zeichen lang sein.")
    if code in {item.upper() for item in existing_codes}:
        raise ImportValidationError(f"Der Projektcode {code} ist bereits vergeben.")
    if not name:
        raise ImportValidationError("Projektname ist erforderlich.")
    if len(name) > 200:
        raise ImportValidationError("Projektname darf höchstens 200 Zeichen lang sein.")
    if not snapshot:
        snapshot = default_snapshot_name(False)
    if len(snapshot) > 200:
        raise ImportValidationError("Projektstand darf höchstens 200 Zeichen lang sein.")
    return code, name, snapshot


def load_config_file(path: str | Path) -> dict:
    path = Path(path).expanduser()
    if not path.is_file():
        raise ConfigError(f"Konfigurationsdatei nicht gefunden: {path}")
    if path.suffix.lower() == ".json":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigError(f"Konfigurationsdatei kann nicht gelesen werden: {path}") from exc
        if not isinstance(data, dict):
            raise ConfigError(f"Ungültige Konfigurationsdatei: {path}")
        return data
    return read_freecad_config(path) or {}


def _local_tag(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def read_freecad_config(path: str | Path) -> dict[str, str] | None:
    path = Path(path).expanduser()
    try:
        root = ElementTree.parse(path).getroot()
    except (OSError, ElementTree.ParseError):
        return None

    for group in root.iter():
        if _local_tag(group.tag) != "FCParamGroup":
            continue
        if group.get("Name") != "FreeCADPLM":
            continue
        values: dict[str, str] = {}
        for child in group:
            name = child.get("Name")
            if name in {"server_url", "api_token"}:
                values[name] = (child.text or "").strip()
        if values.get("server_url") or values.get("api_token"):
            return values
    return None


def freecad_config_candidates() -> list[Path]:
    home = Path.home()
    xdg_config = Path(os.environ.get("XDG_CONFIG_HOME", str(home / ".config")))
    flatpak_root = home / ".var" / "app" / "org.freecad.FreeCAD" / "config" / "FreeCAD"
    candidates: list[Path] = []
    candidates.extend(sorted(flatpak_root.glob("v*/user.cfg")))
    candidates.append(flatpak_root / "user.cfg")
    candidates.extend(sorted((xdg_config / "FreeCAD").glob("v*/user.cfg")))
    candidates.append(xdg_config / "FreeCAD" / "user.cfg")
    candidates.append(home / ".FreeCAD" / "user.cfg")
    seen: set[Path] = set()
    result: list[Path] = []
    for candidate in sorted(candidates, key=lambda item: item.stat().st_mtime if item.exists() else 0, reverse=True):
        if candidate in seen:
            continue
        seen.add(candidate)
        if candidate.is_file():
            result.append(candidate)
    return result


def load_plm_config(
    config_path: str | Path | None = None,
) -> PLMConfig:
    data: dict = {}
    if config_path:
        data.update(load_config_file(config_path))
    elif DEFAULT_CONFIG_PATH.is_file():
        data.update(load_config_file(DEFAULT_CONFIG_PATH))

    freecad_values: dict[str, str] = {}
    for candidate in freecad_config_candidates():
        values = read_freecad_config(candidate)
        if values and values.get("server_url") and values.get("api_token"):
            freecad_values = values
            break

    server_url = str(data.get("server_url") or freecad_values.get("server_url") or "").strip()
    api_token = str(data.get("api_token") or freecad_values.get("api_token") or "").strip()
    if not server_url or not api_token:
        raise ConfigError(
            "Keine PLM-Server-Konfiguration gefunden. Bitte Server-URL und API-Token "
            "in den FreeCAD-Addon-Einstellungen oder in "
            f"{DEFAULT_CONFIG_PATH} hinterlegen."
        )
    if not server_url.lower().startswith(("http://", "https://")):
        raise ConfigError("Die PLM-Server-URL muss mit http:// oder https:// beginnen.")

    patterns = data.get("exclude_patterns")
    if not isinstance(patterns, list) or not all(isinstance(item, str) for item in patterns):
        patterns = list(DEFAULT_EXCLUDED_FILE_PATTERNS)
    else:
        patterns = list(DEFAULT_EXCLUDED_FILE_PATTERNS) + patterns

    return PLMConfig(
        server_url=server_url.rstrip("/"),
        api_token=api_token,
        exclude_patterns=patterns,
        open_browser=bool(data.get("open_browser", False)),
    )


def _format_bytes(size: int) -> str:
    if size >= 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024 * 1024):.1f} GB"
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    if size >= 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size} Byte"


def scan_summary(scan: ImportScan) -> str:
    lines = [
        f"Ordner: {scan.folder}",
        "",
        f"Dateien: {len(scan.files)}",
        f"  FCStd: {len(scan.fcstd_files)}",
        f"  STEP/STL: {len(scan.external_files)}",
        f"  Dokumente: {len(scan.document_files)}",
        f"Gesamtgröße: {_format_bytes(scan.total_size)}",
    ]
    if scan.excluded_files or scan.skipped_symlinks:
        lines.append(
            f"Ausgeschlossen: {scan.excluded_files} Datei(en), "
            f"{scan.skipped_symlinks} Symlink(s)"
        )
    if scan.omitted_documents:
        lines.append(f"Nicht enthalten: {scan.omitted_documents} Dokument(e)")
    if scan.pruned_dirs:
        lines.append("Übersprungene Ordner: " + ", ".join(scan.pruned_dirs[:5]))
    return "\n".join(lines)


def run_zenity(args: Sequence[str], *, input_text: str | None = None) -> str | None:
    if not shutil.which(ZENITY_BIN):
        raise ConfigError("Zenity ist nicht installiert; der interaktive Import ist nicht möglich.")
    result = subprocess.run(
        [ZENITY_BIN, *args],
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def show_error(message: str, *, title: str = "FreeCAD-PLM Import") -> None:
    try:
        run_zenity(
            [
                "--error",
                "--no-markup",
                f"--title={title}",
                f"--text={message}",
            ]
        )
    except (ConfigError, OSError):
        print(message, file=sys.stderr)


def show_info(message: str, *, title: str = "FreeCAD-PLM Import") -> None:
    try:
        run_zenity(
            [
                "--info",
                "--no-markup",
                f"--title={title}",
                f"--text={message}",
            ]
        )
    except (ConfigError, OSError):
        print(message)


def ask_import_options(
    scan: ImportScan,
    *,
    projects: Sequence[dict],
    default_cad_only: bool = False,
    default_open_browser: bool = False,
) -> tuple[str, bool, bool] | None:
    """Step 1: target, document inclusion and browser option."""

    target_values = ["Neues Projekt"]
    if projects:
        target_values.append("Bestehendes Projekt")
    file_values = (
        ["Nur CAD-Dateien", "Alle Dateien"]
        if default_cad_only
        else ["Alle Dateien", "Nur CAD-Dateien"]
    )
    browser_values = ["Ja", "Nein"] if default_open_browser else ["Nein", "Ja"]
    summary = scan_summary(scan)
    output = run_zenity(
        [
            "--forms",
            "--no-markup",
            "--title=In FreeCAD-PLM importieren",
            "--width=680",
            f"--text={summary}",
            "--add-combo=Ziel",
            f"--combo-values={'|'.join(target_values)}",
            "--add-combo=Dateien",
            f"--combo-values={'|'.join(file_values)}",
            "--add-combo=Nach Import im Browser öffnen",
            f"--combo-values={'|'.join(browser_values)}",
            "--ok-label=Weiter",
            "--cancel-label=Abbrechen",
            "--separator=|",
        ]
    )
    if output is None:
        return None
    parts = output.split("|")
    if len(parts) != 3:
        raise ImportValidationError("Ungültige Auswahl im Importdialog.")
    target, files, browser = (part.strip() for part in parts)
    return target, files == "Nur CAD-Dateien", browser == "Ja"


def ask_new_project_details(
    scan: ImportScan,
    *,
    suggested_code: str,
    suggested_name: str,
    existing_codes: Iterable[str],
    error: str = "",
) -> tuple[str, str, str, str] | None:
    summary = scan_summary(scan)
    if error:
        summary = f"{error}\n\n{summary}"
    output = run_zenity(
        [
            "--forms",
            "--no-markup",
            "--title=Neues Projekt",
            "--width=680",
            f"--text={summary}",
            f"--add-entry=Projektcode (leer = {suggested_code})",
            f"--add-entry=Projektname (leer = {suggested_name})",
            "--add-entry=Projektstand (leer = Initial)",
            "--add-entry=Beschreibung (optional)",
            "--ok-label=Importieren",
            "--cancel-label=Abbrechen",
            "--separator=|",
        ]
    )
    if output is None:
        return None
    parts = output.split("|")
    if len(parts) != 4:
        raise ImportValidationError("Ungültige Eingaben im Projektdialog.")
    code = parts[0].strip() or suggested_code
    name = parts[1].strip() or suggested_name
    snapshot = parts[2].strip() or "Initial"
    description = parts[3].strip()
    return code, name, snapshot, description


def ask_existing_project_details(
    scan: ImportScan,
    *,
    projects: Sequence[dict],
) -> tuple[int, str] | None:
    labels = [project_label(project) for project in projects]
    summary = scan_summary(scan)
    output = run_zenity(
        [
            "--forms",
            "--no-markup",
            "--title=Bestehendes Projekt",
            "--width=680",
            f"--text={summary}",
            "--add-combo=Projekt",
            f"--combo-values={'|'.join(labels)}",
            f"--add-entry=Projektstand (leer = {default_snapshot_name(True)})",
            "--ok-label=Importieren",
            "--cancel-label=Abbrechen",
            "--separator=|",
        ]
    )
    if output is None:
        return None
    parts = output.split("|")
    if len(parts) != 2:
        raise ImportValidationError("Ungültige Auswahl im Projektdialog.")
    label = parts[0].strip()
    snapshot = parts[1].strip() or default_snapshot_name(True)
    try:
        project = projects[labels.index(label)]
    except ValueError as exc:
        raise ImportValidationError("Das ausgewählte Projekt wurde nicht gefunden.") from exc
    return int(project["id"]), snapshot


def ask_dependency_root(candidates: Sequence[str]) -> str | None:
    if len(candidates) == 1:
        return candidates[0]
    args = [
        "--list",
        "--radiolist",
        "--no-markup",
        "--title=Abhängige Dateien",
        "--width=680",
        "--text=Mehrere FreeCAD-Dateien gefunden. Welche Datei ist die Wurzel für STEP-/STL-Dateien?",
        "--column=",
        "--column=FCStd-Datei",
        "--print-column=2",
        "--ok-label=Weiter",
        "--cancel-label=Abbrechen",
    ]
    for index, candidate in enumerate(candidates):
        args.extend(["TRUE" if index == 0 else "FALSE", candidate])
    output = run_zenity(args)
    if output is None:
        return None
    return output or candidates[0]


def project_label(project: dict) -> str:
    code = str(project.get("code") or "").strip()
    name = str(project.get("name") or "").strip()
    return f"{code} – {name}".replace("|", "/")


class ProgressDialog:
    def __init__(self, enabled: bool, title: str = "FreeCAD-PLM Import") -> None:
        self.process: subprocess.Popen[str] | None = None
        if not enabled or not shutil.which(ZENITY_BIN):
            return
        try:
            self.process = subprocess.Popen(
                [
                    ZENITY_BIN,
                    "--progress",
                    "--pulsate",
                    "--no-cancel",
                    "--auto-close",
                    "--no-markup",
                    f"--title={title}",
                    "--width=420",
                    "--text=Import wird vorbereitet …",
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
            )
        except OSError:
            self.process = None

    def update(self, text: str) -> None:
        if not self.process or not self.process.stdin:
            return
        try:
            self.process.stdin.write(f"# {text}\n")
            self.process.stdin.flush()
        except (BrokenPipeError, OSError):
            pass

    def close(self) -> None:
        if not self.process:
            return
        try:
            if self.process.stdin:
                self.process.stdin.close()
            self.process.wait(timeout=5)
        except (BrokenPipeError, OSError, subprocess.TimeoutExpired):
            try:
                self.process.terminate()
            except OSError:
                pass


def write_log(folder: str | Path, project: str, status: str, detail: str = "") -> None:
    try:
        path = DEFAULT_LOG_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.chmod(0o600)
        except OSError:
            pass
        line = "\t".join(
            [
                datetime.now().isoformat(timespec="seconds"),
                str(folder),
                project,
                status,
                " ".join(str(detail).splitlines()),
            ]
        )
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"{line}\n")
    except OSError:
        pass


def result_summary(result: dict, server_url: str) -> tuple[str, str]:
    project = result.get("project") or {}
    snapshot = result.get("snapshot") or {}
    summary = result.get("import_summary") or {}
    files = summary.get("files") or []
    documents = sum(1 for item in files if item.get("document_id"))
    project_id = project.get("id")
    url = f"{server_url}/projects/{project_id}/" if project_id else server_url
    text = "\n".join(
        [
            "Import abgeschlossen.",
            "",
            f"Projekt: {project.get('code', '')} – {project.get('name', '')}",
            f"Projektstand: {snapshot.get('name', '')}",
            f"Dateien: {len(files)}",
            f"Neue Teile: {summary.get('created_parts', 0)}",
            f"Neue Revisionen: {summary.get('created_revisions', 0)}",
            f"Wiederverwendete Revisionen: {summary.get('reused_revisions', 0)}",
            f"Dokumente: {documents}",
            "",
            url,
        ]
    )
    return text, url


def import_directory(
    scan: ImportScan,
    *,
    client: PLMClient,
    mode: str,
    code: str = "",
    name: str = "",
    description: str = "",
    snapshot: str = "",
    project_id: int | None = None,
    dependency_root: str = "",
    progress: ProgressDialog | None = None,
) -> dict:
    validate_scan(scan)
    root = resolve_dependency_root(scan, dependency_root)

    with tempfile.TemporaryDirectory(prefix="freecad-plm-import-") as tmp:
        zip_path = Path(tmp) / "import.zip"
        if progress:
            progress.update("ZIP wird erstellt …")
        build_import_zip(scan, zip_path)

        if progress:
            progress.update("Daten werden an den PLM-Server übertragen …")
        if mode == "existing":
            if project_id is None:
                raise ImportValidationError("Kein bestehendes Projekt ausgewählt.")
            result = client.import_project_snapshot(
                project_id,
                zip_path,
                snapshot or default_snapshot_name(True),
                dependency_root_path=root,
            )
        else:
            result = client.import_project(
                zip_path,
                {
                    "code": code,
                    "name": name,
                    "description": description,
                    "status": "running",
                    "project_date": date.today().isoformat(),
                },
                snapshot or default_snapshot_name(False),
                dependency_root_path=root,
            )
    if progress:
        progress.update("Fertig.")
    return result


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="import_directory.py",
        description="Importiert einen lokalen Ordner in FreeCAD-PLM.",
    )
    parser.add_argument("folder", nargs="?", help="Zu importierender Ordner")
    parser.add_argument("--folder", dest="folder_option", help="Zu importierender Ordner")
    parser.add_argument("--mode", choices=("ask", "new", "existing"), default="ask")
    parser.add_argument("--project-id", type=int)
    parser.add_argument("--code")
    parser.add_argument("--name")
    parser.add_argument("--snapshot")
    parser.add_argument("--description", default="")
    parser.add_argument("--cad-only", action="store_true")
    parser.add_argument("--dependency-root", default="")
    parser.add_argument("--open-browser", action="store_true")
    parser.add_argument("--yes", action="store_true", help="Ohne Dialoge ausführen")
    parser.add_argument("--dry-run", action="store_true", help="Nur prüfen, nichts hochladen")
    parser.add_argument("--config")
    parser.add_argument("--server-url")
    parser.add_argument("--api-token")
    parser.add_argument("--timeout", type=int, default=300)
    return parser.parse_args(argv)


def _choose_folder(args: argparse.Namespace) -> Path:
    raw = args.folder_option or args.folder
    if not raw:
        raise ImportValidationError("Kein Ordner angegeben.")
    return Path(raw).expanduser().resolve()


def _build_client(args: argparse.Namespace, config: PLMConfig) -> PLMClient:
    return PLMClient(
        args.server_url or config.server_url,
        args.api_token or config.api_token,
        timeout=args.timeout,
    )


def _run_interactive(
    scan_all: ImportScan,
    args: argparse.Namespace,
    config: PLMConfig,
    projects: Sequence[dict],
    *,
    existing_codes: Sequence[str],
) -> tuple[ImportScan, str, dict] | None:
    choice = ask_import_options(
        scan_all,
        projects=projects,
        default_cad_only=args.cad_only,
        default_open_browser=args.open_browser or config.open_browser,
    )
    if choice is None:
        return None
    target, cad_only, open_browser = choice

    scan = scan_all
    if cad_only:
        scan = scan_directory(
            scan_all.folder,
            include_documents=False,
            exclude_patterns=config.exclude_patterns,
        )
    if not scan.fcstd_files:
        raise ImportValidationError("Im Ordner wurde keine .FCStd-Datei gefunden.")
    validate_scan(scan)

    if target == "Bestehendes Projekt":
        if not projects:
            raise ImportValidationError("Es sind keine bestehenden Projekte verfügbar.")
        details = ask_existing_project_details(scan, projects=projects)
        if details is None:
            return None
        project_id, snapshot = details
        return scan, "existing", {
            "project_id": project_id,
            "snapshot": snapshot,
            "open_browser": open_browser,
            "dependency_root": args.dependency_root,
        }

    suggested_code = next_available_code(
        args.code or derive_project_code(scan.folder.name),
        existing_codes,
    )
    suggested_name = args.name or derive_project_name(scan.folder.name)
    error = ""
    while True:
        details = ask_new_project_details(
            scan,
            suggested_code=suggested_code,
            suggested_name=suggested_name,
            existing_codes=existing_codes,
            error=error,
        )
        if details is None:
            return None
        code, name, snapshot, description = details
        try:
            code, name, snapshot = validate_project_values(
                code,
                name,
                snapshot,
                existing_codes=existing_codes,
            )
        except ImportValidationError as exc:
            error = str(exc)
            suggested_code = next_available_code(code, existing_codes)
            continue
        return scan, "new", {
            "code": code,
            "name": name,
            "snapshot": snapshot,
            "description": description,
            "open_browser": open_browser,
            "dependency_root": args.dependency_root,
        }


def _noninteractive_options(
    scan: ImportScan,
    args: argparse.Namespace,
    *,
    existing_codes: Sequence[str],
    projects: Sequence[dict],
) -> tuple[str, dict]:
    mode = args.mode
    if mode == "ask":
        mode = "existing" if args.project_id is not None else "new"

    if mode == "existing":
        if args.project_id is None:
            raise ImportValidationError("Für ein bestehendes Projekt ist --project-id erforderlich.")
        if not any(int(project["id"]) == args.project_id for project in projects):
            raise ImportValidationError("Das angegebene Projekt wurde nicht gefunden.")
        return mode, {
            "project_id": args.project_id,
            "snapshot": args.snapshot or default_snapshot_name(True),
            "open_browser": args.open_browser,
            "dependency_root": args.dependency_root,
        }

    code = args.code or derive_project_code(scan.folder.name)
    name = args.name or derive_project_name(scan.folder.name)
    snapshot = args.snapshot or default_snapshot_name(False)
    try:
        code, name, snapshot = validate_project_values(
            code,
            name,
            snapshot,
            existing_codes=existing_codes,
        )
    except ImportValidationError as exc:
        if "bereits vergeben" in str(exc):
            raise ImportValidationError(
                f"{exc} Vorschlag: {next_available_code(code, existing_codes)}"
            ) from exc
        raise
    return mode, {
        "code": code,
        "name": name,
        "snapshot": snapshot,
        "description": args.description,
        "open_browser": args.open_browser,
        "dependency_root": args.dependency_root,
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    progress: ProgressDialog | None = None
    folder: Path | None = None
    try:
        folder = _choose_folder(args)
        config: PLMConfig | None = None
        if not args.dry_run:
            try:
                config = load_plm_config(args.config)
            except ConfigError:
                if args.server_url and args.api_token:
                    config = PLMConfig(args.server_url, args.api_token)
                else:
                    raise

        if args.dry_run:
            scan = scan_directory(
                folder,
                include_documents=not args.cad_only,
                exclude_patterns=(config.exclude_patterns if config else DEFAULT_EXCLUDED_FILE_PATTERNS),
            )
            validate_scan(scan)
            root = resolve_dependency_root(scan, args.dependency_root)
            print(scan_summary(scan))
            if scan.external_files:
                print(f"Dependency Root: {root}")
            return 0

        assert config is not None
        client = _build_client(args, config)
        # Keep the initial project query responsive; uploads may take longer.
        client.timeout = min(args.timeout, 20)
        projects = client.get_projects()
        client.timeout = args.timeout
        existing_codes = [str(project.get("code") or "") for project in projects]

        if args.yes or args.mode != "ask" or args.project_id is not None:
            scan = scan_directory(
                folder,
                include_documents=not args.cad_only,
                exclude_patterns=config.exclude_patterns,
            )
            validate_scan(scan)
            mode, options = _noninteractive_options(
                scan,
                args,
                existing_codes=existing_codes,
                projects=projects,
            )
            options["open_browser"] = bool(options.get("open_browser")) or config.open_browser
        else:
            scan_all = scan_directory(
                folder,
                include_documents=True,
                exclude_patterns=config.exclude_patterns,
            )
            if not scan_all.fcstd_files:
                raise ImportValidationError("Im Ordner wurde keine .FCStd-Datei gefunden.")
            interactive = _run_interactive(
                scan_all,
                args,
                config,
                projects,
                existing_codes=existing_codes,
            )
            if interactive is None:
                return 0
            scan, mode, options = interactive

        try:
            root = resolve_dependency_root(scan, options.get("dependency_root", ""))
        except DependencyRootRequired as exc:
            if args.yes:
                raise
            root = ask_dependency_root(exc.candidates) or ""
            if not root:
                return 0
            options["dependency_root"] = root

        progress = ProgressDialog(not args.yes)
        result = import_directory(
            scan,
            client=client,
            mode=mode,
            code=options.get("code", ""),
            name=options.get("name", ""),
            description=options.get("description", ""),
            snapshot=options.get("snapshot", ""),
            project_id=options.get("project_id"),
            dependency_root=options.get("dependency_root", ""),
            progress=progress,
        )
        progress.close()
        progress = None

        text, url = result_summary(result, args.server_url or config.server_url)
        project = result.get("project") or {}
        write_log(folder, str(project.get("code") or ""), "ok", text)
        if options.get("open_browser"):
            webbrowser.open(url)
        if args.yes:
            print(text)
        else:
            show_info(text)
        return 0
    except DependencyRootRequired as exc:
        message = f"{exc}\n\nKandidaten:\n" + "\n".join(exc.candidates)
        if args.yes or args.dry_run:
            print(message, file=sys.stderr)
        else:
            show_error(message)
        write_log(folder or "", "", "error", message)
        return 1
    except AuthenticationError:
        message = (
            "Der PLM-Token ist ungültig oder abgelaufen. Bitte den Token in den "
            "FreeCAD-Addon-Einstellungen erneuern."
        )
        if args.yes or args.dry_run:
            print(message, file=sys.stderr)
        else:
            show_error(message)
        write_log(folder or "", "", "error", message)
        return 1
    except PermissionDeniedError as exc:
        message = (
            "Der PLM-Token hat nicht die benötigte Berechtigung. Für ein neues "
            "Projekt werden der Scope 'admin' und die PLM-Adminrolle benötigt; "
            "für einen bestehenden Projektstand genügt 'write'.\n\n"
            f"{exc}"
        )
        if args.yes or args.dry_run:
            print(message, file=sys.stderr)
        else:
            show_error(message)
        write_log(folder or "", "", "error", message)
        return 1
    except (ConfigError, ImportValidationError, PLMError, URLError, OSError) as exc:
        message = str(exc)
        if args.yes or args.dry_run:
            print(message, file=sys.stderr)
        else:
            show_error(message)
        write_log(folder or "", "", "error", message)
        return 1
    except Exception as exc:  # Last-resort UI feedback instead of a silent Nemo action.
        message = f"Unerwarteter Fehler: {exc}"
        if args.yes or args.dry_run:
            print(message, file=sys.stderr)
        else:
            show_error(message)
        write_log(folder or "", "", "error", message)
        return 1
    finally:
        if progress:
            progress.close()


if __name__ == "__main__":
    raise SystemExit(main())
