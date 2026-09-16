import json
import os
import platform
import shlex
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ElementTree
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4
from zipfile import BadZipFile, ZipFile, ZIP_DEFLATED

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
        return [PurePosixPath("/Applications") / name for name in names.get(kind, ())]
    if platform_name == "Windows":
        roots = [
            PureWindowsPath(value)
            for value in (
                environ.get("ProgramFiles"),
                environ.get("LOCALAPPDATA"),
            )
            if value
        ]
        names = {
            "bambu": (
                PureWindowsPath("Bambu Studio") / "bambu-studio.exe",
                PureWindowsPath("Programs") / "Bambu Studio" / "bambu-studio.exe",
            ),
            "orca": (
                PureWindowsPath("OrcaSlicer") / "orca-slicer.exe",
                PureWindowsPath("Programs") / "OrcaSlicer" / "orca-slicer.exe",
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
    path_exists = path_exists or (lambda candidate: Path(candidate).is_file())
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


def slicer_project_dir(base_root, server_url, project_code, revision_id, print_project_id=None):
    revision_dir = (
        Path(base_root).expanduser()
        / server_slug(server_url)
        / str(project_code)
        / "slicer-projects"
        / f"revision-{revision_id}"
    )
    if print_project_id is None:
        return revision_dir
    return revision_dir / f"print-project-{int(print_project_id)}"


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
    project_path = Path(project_path)
    return project_path.with_name(f"{project_path.name}.sync.json")


def migrate_legacy_slicer_project(legacy_path, project_path, print_project_id):
    """Copy an identified old working file without touching other print projects."""
    legacy_path = Path(legacy_path)
    project_path = Path(project_path)
    if project_path.is_file() or not legacy_path.is_file():
        return False
    legacy_state = legacy_path.with_name("sync.json")
    try:
        state = json.loads(legacy_state.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(state, dict) or state.get("print_project_id") != print_project_id:
        return False
    project_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(legacy_path, project_path)
    write_sync_state(project_path, state)
    return True


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


SOURCES_MEMBER = "Metadata/freecad_plm_sources.json"
SOURCES_RELATIONSHIP = "urn:freecad-plm:relationships:sources"


def revision_sources(manifest, revision_id, server_url=""):
    address = urlsplit(server_url)
    server = urlunsplit((address.scheme, address.netloc.rsplit("@", 1)[-1], address.path, "", ""))
    fields = ("path", "part_id", "revision_id", "revision_code", "sha256", "is_root")
    return {
        "schema_version": 1,
        "server": server.rstrip("/"),
        "project_id": manifest.get("project", {}).get("id"),
        "root_revision_id": revision_id,
        "files": sorted(
            [{key: item.get(key) for key in fields} for item in manifest["files"]],
            key=lambda item: item["path"],
        ),
    }


def read_3mf_sources(project_path):
    try:
        with ZipFile(project_path) as archive:
            if archive.getinfo(SOURCES_MEMBER).file_size > 1024 * 1024:
                return None
            data = json.loads(archive.read(SOURCES_MEMBER))
        if not isinstance(data, dict) or data.get("schema_version") != 1:
            return None
        files = data.get("files")
        if not isinstance(files, list) or not files:
            return None
        if any(
            not isinstance(item, dict)
            or not isinstance(item.get("path"), str)
            or not isinstance(item.get("sha256"), str)
            or len(item["sha256"]) != 64
            for item in files
        ):
            return None
        return data
    except (OSError, BadZipFile, KeyError, ValueError, RuntimeError):
        return None


def slicer_sources_status(project_path, current_sources):
    stored = read_3mf_sources(project_path)
    if stored is None:
        return "unknown"
    stored = {key: stored.get(key) for key in current_sources}
    stored["files"] = sorted(stored["files"], key=lambda item: item["path"])
    return "current" if stored == current_sources else "changed"


def write_3mf_sources(project_path, sources):
    project_path = Path(project_path)
    temporary = project_path.with_name(f".{project_path.name}.{uuid4().hex}.tmp")
    content_namespace = "http://schemas.openxmlformats.org/package/2006/content-types"
    relation_namespace = "http://schemas.openxmlformats.org/package/2006/relationships"
    try:
        with ZipFile(project_path) as source, ZipFile(temporary, "w", ZIP_DEFLATED) as target:
            names = set(source.namelist())
            content = (
                ElementTree.fromstring(source.read("[Content_Types].xml"))
                if "[Content_Types].xml" in names
                else ElementTree.Element(f"{{{content_namespace}}}Types")
            )
            for child in list(content):
                if child.get("PartName") == f"/{SOURCES_MEMBER}":
                    content.remove(child)
            ElementTree.SubElement(content, f"{{{content_namespace}}}Override", {
                "PartName": f"/{SOURCES_MEMBER}", "ContentType": "application/json",
            })
            relations = (
                ElementTree.fromstring(source.read("_rels/.rels"))
                if "_rels/.rels" in names
                else ElementTree.Element(f"{{{relation_namespace}}}Relationships")
            )
            for child in list(relations):
                if child.get("Type") == SOURCES_RELATIONSHIP:
                    relations.remove(child)
            ElementTree.SubElement(relations, f"{{{relation_namespace}}}Relationship", {
                "Id": f"plmSources{uuid4().hex}",
                "Type": SOURCES_RELATIONSHIP,
                "Target": f"/{SOURCES_MEMBER}",
            })
            replaced = {SOURCES_MEMBER, "[Content_Types].xml", "_rels/.rels"}
            for member in source.infolist():
                if member.filename not in replaced:
                    target.writestr(member, source.read(member))
            ElementTree.register_namespace("", content_namespace)
            target.writestr("[Content_Types].xml", ElementTree.tostring(content, encoding="utf-8", xml_declaration=True))
            ElementTree.register_namespace("", relation_namespace)
            target.writestr("_rels/.rels", ElementTree.tostring(relations, encoding="utf-8", xml_declaration=True))
            target.writestr(SOURCES_MEMBER, json.dumps({
                **sources,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }, ensure_ascii=False, indent=2))
        temporary.replace(project_path)
    finally:
        temporary.unlink(missing_ok=True)


def backup_slicer_project(project_path):
    project_path = Path(project_path)
    backup_dir = project_path.parent / "backups" / (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    )
    backup_dir.mkdir(parents=True)
    backup = backup_dir / project_path.name
    shutil.copy2(project_path, backup)
    state_path = sync_state_path(project_path)
    if state_path.is_file():
        shutil.copy2(state_path, backup_dir / state_path.name)
    return backup


def export_revision_manifest_to_3mf(
    client, revision_id, workspace_dir, target_path, *, manifest=None, backup=False
):
    workspace_dir = Path(workspace_dir)
    target_path = Path(target_path)
    manifest = manifest if manifest is not None else client.get_revision_manifest(revision_id)
    workspace_dir.mkdir(parents=True, exist_ok=True)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    original_sha = sha256_file(target_path) if target_path.is_file() else None
    temporary = target_path.with_name(f".{target_path.stem}.{uuid4().hex}.exporting.3mf")
    try:
        with tempfile.TemporaryDirectory(prefix="export-", dir=workspace_dir) as isolated:
            source_dir = Path(isolated)
            write_manifest(source_dir, manifest)
            download_manifest_files(client, manifest, source_dir)
            source_path = root_file_path(manifest, source_dir)
            export_revision_to_3mf(source_path, temporary)
        write_3mf_sources(temporary, revision_sources(
            manifest, revision_id, getattr(client, "base_url", "")
        ))
        validate_3mf(temporary)
        current_sha = sha256_file(target_path) if target_path.is_file() else None
        if current_sha != original_sha:
            raise WorkspaceError(
                "Die 3MF wurde während des Exports geändert. Der neue Export wurde verworfen; "
                "bitte das Projekt im Slicer schließen und erneut versuchen."
            )
        if backup and target_path.is_file():
            backup_slicer_project(target_path)
        temporary.replace(target_path)
    finally:
        temporary.unlink(missing_ok=True)
    return target_path


def export_revision_manifest_to_stl(client, revision_id, workspace_dir, target_path):
    workspace_dir = Path(workspace_dir)
    target_path = Path(target_path)
    manifest = client.get_revision_manifest(revision_id)
    write_manifest(workspace_dir, manifest)
    download_manifest_files(client, manifest, workspace_dir)
    source_path = root_file_path(manifest, workspace_dir)
    temporary = target_path.with_name(f".{target_path.stem}.exporting.stl")
    temporary.unlink(missing_ok=True)
    try:
        export_revision_to_stl(source_path, temporary)
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


def export_revision_to_mesh(source_path, target_path):
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
        if not target_path.is_file() or target_path.stat().st_size < 1:
            raise WorkspaceError("FreeCAD hat keine Exportdatei erzeugt.")
        return target_path
    finally:
        for name in set((FreeCAD.listDocuments() or {}).keys()) - before:
            FreeCAD.closeDocument(name)


def export_revision_to_3mf(source_path, target_path):
    target_path = export_revision_to_mesh(source_path, target_path)
    return validate_3mf(target_path)


def export_revision_to_stl(source_path, target_path):
    target_path = Path(target_path)
    if target_path.suffix.lower() != ".stl":
        raise WorkspaceError("Die Slicer-Übergabedatei muss eine STL-Datei sein.")
    return export_revision_to_mesh(source_path, target_path)


class SlicerProjectMonitor:
    """Directory watcher with debounce; keeps working across atomic file replace."""

    def __init__(self, qt_core, project_path, callback, debounce_ms=1500):
        self.project_path = Path(project_path)
        self.callback = callback
        self.paused = False
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
        if self.paused:
            return
        self._restore_paths()
        self.timer.start()

    def flush(self):
        if self.paused:
            return
        self._restore_paths()
        self.callback(self.project_path)

    def pause(self):
        self.paused = True
        self.timer.stop()

    def resume(self):
        self.paused = False
        self._restore_paths()
        self.timer.start()

    def stop(self):
        self.pause()
        self.watcher.blockSignals(True)
        self.watcher.deleteLater()
        self.timer.deleteLater()
