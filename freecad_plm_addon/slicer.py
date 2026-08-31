import json
import os
import platform
import shlex
import shutil
import subprocess
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from .errors import EmptyGeometryError, WorkspaceError
from .workspace import (
    download_manifest_files,
    root_file_path,
    safe_download_filename,
    server_slug,
    sha256_file,
    write_manifest,
)


SLICERS = {
    "bambu": {
        "label": "Bambu Studio",
        "executables": ("bambu-studio", "BambuStudio"),
        "flatpak": "com.bambulab.BambuStudio",
    },
    "orca": {
        "label": "OrcaSlicer",
        "executables": ("orca-slicer", "OrcaSlicer"),
        "flatpak": "io.github.softfever.OrcaSlicer",
    },
}


def parse_extra_args(value):
    text = str(value or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = shlex.split(text)
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        raise WorkspaceError("Slicer-Argumente müssen eine Liste von Textwerten sein.")
    return parsed


def known_slicer_paths(kind, platform_name=None, environ=None):
    platform_name = platform_name or platform.system()
    environ = environ or os.environ
    if platform_name == "Darwin":
        names = {
            "bambu": ("BambuStudio.app/Contents/MacOS/BambuStudio",),
            "orca": ("OrcaSlicer.app/Contents/MacOS/OrcaSlicer",),
        }
        return [Path("/Applications") / name for name in names.get(kind, ())]
    if platform_name == "Windows":
        roots = [
            Path(value)
            for value in (
                environ.get("ProgramFiles"),
                environ.get("LOCALAPPDATA"),
            )
            if value
        ]
        names = {
            "bambu": (
                Path("Bambu Studio") / "bambu-studio.exe",
                Path("Programs") / "Bambu Studio" / "bambu-studio.exe",
            ),
            "orca": (
                Path("OrcaSlicer") / "orca-slicer.exe",
                Path("Programs") / "OrcaSlicer" / "orca-slicer.exe",
            ),
        }
        return [root / name for root in roots for name in names.get(kind, ())]
    return []


def detect_slicer(
    kind="auto",
    which=shutil.which,
    flatpak_apps=None,
    platform_name=None,
    path_exists=None,
    environ=None,
    flatpak_command=None,
):
    kinds = ("bambu", "orca") if kind == "auto" else (kind,)
    flatpak_apps = set(flatpak_apps or ())
    path_exists = path_exists or Path.is_file
    for candidate_kind in kinds:
        definition = SLICERS.get(candidate_kind)
        if not definition:
            continue
        for executable in definition["executables"]:
            path = which(executable)
            if path:
                return {
                    "kind": candidate_kind,
                    "label": definition["label"],
                    "command": [path],
                }
        for path in known_slicer_paths(candidate_kind, platform_name, environ):
            if path_exists(path):
                return {
                    "kind": candidate_kind,
                    "label": definition["label"],
                    "command": [str(path)],
                }
        if definition["flatpak"] in flatpak_apps:
            flatpak_command = list(flatpak_command or ["flatpak"])
            return {
                "kind": candidate_kind,
                "label": definition["label"],
                "command": [*flatpak_command, "run", definition["flatpak"]],
            }
    return None


def flatpak_cli_command():
    flatpak = shutil.which("flatpak")
    if flatpak:
        return [flatpak]
    flatpak_spawn = shutil.which("flatpak-spawn")
    if flatpak_spawn:
        return [flatpak_spawn, "--host", "flatpak"]
    return []


def installed_flatpak_apps(flatpak_command=None):
    flatpak_command = list(flatpak_command or flatpak_cli_command())
    if not flatpak_command:
        return set()
    result = subprocess.run(
        [*flatpak_command, "list", "--app", "--columns=application"],
        capture_output=True,
        text=True,
        check=False,
    )
    return set(result.stdout.split()) if result.returncode == 0 else set()


def resolve_slicer_command(kind="auto", executable="", extra_args=""):
    args = parse_extra_args(extra_args)
    if executable.strip():
        return [str(Path(executable).expanduser()), *args]
    flatpak_command = flatpak_cli_command()
    detected = detect_slicer(
        kind,
        flatpak_apps=installed_flatpak_apps(flatpak_command),
        flatpak_command=flatpak_command,
    )
    if detected is None:
        raise WorkspaceError(
            "Kein Slicer gefunden. Bitte Bambu Studio oder OrcaSlicer konfigurieren."
        )
    return [*detected["command"], *args]


def slicer_project_dir(base_root, server_url, project_code, revision_id):
    return (
        Path(base_root).expanduser()
        / server_slug(server_url)
        / str(project_code)
        / "slicer-projects"
        / f"revision-{revision_id}"
    )


def slicer_project_filename(
    project_code, part_number, revision_code, original_filename=""
):
    """Return the globally unique name used by the slicer and Bambuddy."""
    stem = "_".join(
        value.strip("_")
        for value in (
            str(project_code or ""),
            str(part_number or ""),
            str(revision_code or ""),
        )
        if value
    )
    if not stem:
        stem = Path(safe_download_filename(original_filename, "slicer-project")).stem
    safe_stem = "".join(char if char.isalnum() or char in "-_." else "_" for char in stem)
    return f"{safe_stem or 'slicer-project'}.3mf"


def sync_state_path(project_path):
    return Path(project_path).with_name("sync.json")


def read_sync_state(project_path):
    path = sync_state_path(project_path)
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def write_sync_state(project_path, state):
    path = sync_state_path(project_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(state, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary.replace(path)
    return path


def validate_3mf(path):
    path = Path(path)
    if not path.is_file() or path.suffix.lower() != ".3mf":
        raise WorkspaceError("Das Slicer-Projekt ist keine 3MF-Datei.")
    try:
        with ZipFile(path) as archive:
            names = archive.namelist()
            model_names = [name for name in names if name.lower().endswith(".model")]
            if not model_names:
                raise WorkspaceError("Die 3MF enthält kein 3D-Modell.")
            bad_member = archive.testzip()
            if bad_member:
                raise WorkspaceError(f"Die 3MF ist beschädigt: {bad_member}")
            triangle_count = 0
            for name in model_names:
                try:
                    root = ElementTree.fromstring(archive.read(name))
                except ElementTree.ParseError as exc:
                    raise WorkspaceError(
                        f"Die 3MF-Modelldatei ist ungültig: {name}."
                    ) from exc
                triangle_count += sum(
                    1
                    for node in root.iter()
                    if str(node.tag).rsplit("}", 1)[-1] == "triangle"
                )
            if triangle_count < 1:
                raise EmptyGeometryError(
                    "Die 3MF enthält keine Geometriedreiecke."
                )
    except BadZipFile as exc:
        raise WorkspaceError("Die 3MF ist kein gültiger ZIP-Container.") from exc
    return path


def export_revision_manifest_to_3mf(client, revision_id, workspace_dir, target_path):
    workspace_dir = Path(workspace_dir)
    target_path = Path(target_path)
    manifest = client.get_revision_manifest(revision_id)
    write_manifest(workspace_dir, manifest)
    download_manifest_files(client, manifest, workspace_dir)
    source_path = root_file_path(manifest, workspace_dir)
    temporary = target_path.with_name(f".{target_path.stem}.exporting.3mf")
    temporary.unlink(missing_ok=True)
    try:
        export_revision_to_3mf(source_path, temporary)
        validate_3mf(temporary)
        temporary.replace(target_path)
    finally:
        temporary.unlink(missing_ok=True)
    return target_path


def reconcile_slicer_project(local_sha256, previous_server_sha256, server_sha256):
    """Choose a safe action without silently discarding either side."""
    local_dirty = bool(
        local_sha256
        and previous_server_sha256
        and local_sha256 != previous_server_sha256
    )
    if local_dirty:
        return "upload" if server_sha256 == previous_server_sha256 else "conflict"
    if server_sha256:
        return "current" if local_sha256 == server_sha256 else "download"
    return "upload" if local_sha256 else "create"


def launch_slicer(project_path, command):
    validate_3mf(project_path)
    argv = [*command, str(Path(project_path))]
    subprocess.Popen(argv, start_new_session=True)
    return argv


def select_export_objects(objects):
    """Return visible top-level geometry without exporting child shapes twice."""
    candidates = []
    for obj in objects:
        view_object = getattr(obj, "ViewObject", None)
        visible = getattr(view_object, "Visibility", True)
        if visible and (hasattr(obj, "Shape") or hasattr(obj, "Mesh")):
            candidates.append(obj)

    candidate_ids = {id(obj) for obj in candidates}
    selected = []
    for obj in candidates:
        parent_getter = getattr(obj, "getParentGeoFeatureGroup", None)
        parent = parent_getter() if callable(parent_getter) else None
        seen = set()
        while parent is not None and id(parent) not in seen:
            if id(parent) in candidate_ids:
                break
            seen.add(id(parent))
            parent_getter = getattr(parent, "getParentGeoFeatureGroup", None)
            parent = parent_getter() if callable(parent_getter) else None
        else:
            selected.append(obj)
    return selected


def export_revision_to_3mf(source_path, target_path):
    """Export an FCStd/STEP/STL revision through FreeCAD's Mesh workbench."""
    import FreeCAD
    import Mesh

    source_path = Path(source_path)
    target_path = Path(target_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    before = set((FreeCAD.listDocuments() or {}).keys())
    document = None
    try:
        if source_path.suffix.lower() == ".fcstd":
            document = FreeCAD.openDocument(str(source_path))
        elif source_path.suffix.lower() in (".step", ".stp"):
            import Import

            document = FreeCAD.newDocument()
            Import.insert(str(source_path), document.Name)
        elif source_path.suffix.lower() == ".stl":
            document = FreeCAD.newDocument()
            Mesh.insert(str(source_path), document.Name)
        else:
            raise WorkspaceError(f"Nicht unterstütztes CAD-Format: {source_path.suffix}")
        document.recompute()
        objects = select_export_objects(document.Objects)
        if not objects:
            raise WorkspaceError("Die Revision enthält keine exportierbare Geometrie.")
        Mesh.export(objects, str(target_path))
        return validate_3mf(target_path)
    finally:
        for name in set((FreeCAD.listDocuments() or {}).keys()) - before:
            FreeCAD.closeDocument(name)


class SlicerProjectMonitor:
    """Directory watcher with debounce; keeps working across atomic file replace."""

    def __init__(self, qt_core, project_path, callback, debounce_ms=1500):
        self.project_path = Path(project_path)
        self.callback = callback
        self.watcher = qt_core.QFileSystemWatcher()
        self.timer = qt_core.QTimer()
        self.timer.setSingleShot(True)
        self.timer.setInterval(debounce_ms)
        self.watcher.directoryChanged.connect(self.schedule)
        self.watcher.fileChanged.connect(self.schedule)
        self.timer.timeout.connect(self.flush)
        self._restore_paths()

    def _restore_paths(self):
        paths = [str(self.project_path.parent)]
        if self.project_path.exists():
            paths.append(str(self.project_path))
        current = set(self.watcher.files()) | set(self.watcher.directories())
        missing = [path for path in paths if path not in current]
        if missing:
            self.watcher.addPaths(missing)

    def schedule(self, *_args):
        self._restore_paths()
        self.timer.start()

    def flush(self):
        self._restore_paths()
        self.callback(self.project_path)
