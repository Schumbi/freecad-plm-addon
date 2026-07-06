import hashlib
import json
import re
import shutil
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

from .errors import HashMismatchError, WorkspaceError


def safe_join(root, relative_path):
    root = Path(root)
    path = PurePosixPath(relative_path)
    if path.is_absolute() or ".." in path.parts:
        raise WorkspaceError(f"Unsicherer Manifest-Pfad: {relative_path}")
    return root.joinpath(*path.parts)


def server_slug(server_url):
    parsed = urlparse(server_url)
    host = parsed.netloc or parsed.path
    slug = re.sub(r"[^A-Za-z0-9]+", "-", host).strip("-").lower()
    return slug or "server"


def checkout_dir(base_root, server_url, project_code, checkout_id):
    return (
        Path(base_root).expanduser()
        / server_slug(server_url)
        / project_code
        / f"checkout-{checkout_id}"
    )


def readonly_revision_dir(base_root, server_url, project_code, revision_id):
    return (
        Path(base_root).expanduser()
        / server_slug(server_url)
        / project_code
        / "readonly"
        / f"revision-{revision_id}"
    )


def readonly_root(base_root, server_url):
    return Path(base_root).expanduser() / server_slug(server_url)


def safe_download_filename(filename, default="revision.FCStd"):
    name = Path(str(filename or "")).name.strip()
    if not name or name in (".", ".."):
        return default
    return name


def touch_directory(path):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)


def _mtime(path):
    try:
        return Path(path).stat().st_mtime
    except OSError:
        return 0


def _readonly_project_dirs(server_root):
    server_root = Path(server_root)
    if not server_root.exists():
        return []
    projects = []
    for project_dir in server_root.iterdir():
        readonly = project_dir / "readonly"
        if project_dir.is_dir() and readonly.is_dir():
            projects.append(project_dir)
    return projects


def _readonly_revision_dirs(project_dir):
    readonly = Path(project_dir) / "readonly"
    if not readonly.is_dir():
        return []
    return [
        revision_dir
        for revision_dir in readonly.iterdir()
        if revision_dir.is_dir() and revision_dir.name.startswith("revision-")
    ]


def _project_cache_mtime(project_dir):
    revisions = _readonly_revision_dirs(project_dir)
    if revisions:
        return max(_mtime(revision) for revision in revisions)
    return _mtime(Path(project_dir) / "readonly")


def _fcstd_count(project_dirs):
    count = 0
    for project_dir in project_dirs:
        readonly = Path(project_dir) / "readonly"
        if not readonly.is_dir():
            continue
        count += sum(
            1
            for path in readonly.rglob("*")
            if path.is_file() and path.suffix.lower() == ".fcstd"
        )
    return count


def _remove_readonly_project(project_dir):
    shutil.rmtree(Path(project_dir) / "readonly", ignore_errors=True)


def prune_readonly_cache(
    base_root,
    server_url,
    current_project_code=None,
    current_revision_id=None,
    max_fcstd_files=20,
    max_projects=5,
    max_revisions_per_project=5,
):
    server_root = readonly_root(base_root, server_url)
    projects = _readonly_project_dirs(server_root)
    current_project_dir = server_root / str(current_project_code) if current_project_code else None
    current_revision_dir = (
        current_project_dir / "readonly" / f"revision-{current_revision_id}"
        if current_project_dir is not None and current_revision_id is not None
        else None
    )

    removed = []

    for project_dir in list(projects):
        revisions = sorted(_readonly_revision_dirs(project_dir), key=_mtime)
        while len(revisions) > max_revisions_per_project:
            candidate = next((path for path in revisions if path != current_revision_dir), None)
            if candidate is None:
                break
            shutil.rmtree(candidate, ignore_errors=True)
            removed.append(candidate)
            revisions.remove(candidate)

    projects = _readonly_project_dirs(server_root)
    while len(projects) > max_projects:
        candidates = [path for path in projects if path != current_project_dir]
        if not candidates:
            break
        candidate = min(candidates, key=_project_cache_mtime)
        _remove_readonly_project(candidate)
        removed.append(candidate / "readonly")
        projects.remove(candidate)

    projects = _readonly_project_dirs(server_root)
    while _fcstd_count(projects) > max_fcstd_files:
        candidates = [path for path in projects if path != current_project_dir]
        if not candidates:
            break
        candidate = min(candidates, key=_project_cache_mtime)
        _remove_readonly_project(candidate)
        removed.append(candidate / "readonly")
        projects.remove(candidate)

    return removed


def write_manifest(path, manifest):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    (path / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def read_manifest(path):
    return json.loads((Path(path) / "manifest.json").read_text(encoding="utf-8"))


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def files_root(path):
    return Path(path) / "files"


def download_manifest_files(client, manifest, path):
    target_root = files_root(path)
    downloaded = []
    for item in manifest["files"]:
        target = safe_join(target_root, item["path"])
        if target.exists():
            target.chmod(0o644)
        client.download_revision_file(item["download_url"], target, item["sha256"])
        if sha256_file(target) != item["sha256"]:
            raise HashMismatchError(f"SHA-256 stimmt nicht: {target}")
        downloaded.append(target)
    return downloaded


def root_file_path(manifest, path):
    roots = [item for item in manifest["files"] if item.get("is_root")]
    if len(roots) != 1:
        raise WorkspaceError("Manifest muss genau eine Root-Datei enthalten.")
    return safe_join(files_root(path), roots[0]["path"])
