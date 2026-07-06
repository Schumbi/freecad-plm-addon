import hashlib
import json
import re
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


def safe_download_filename(filename, default="revision.FCStd"):
    name = Path(str(filename or "")).name.strip()
    if not name or name in (".", ".."):
        return default
    return name


def resolve_reference_path(source_path, reference_file):
    source_dir = PurePosixPath(source_path).parent
    reference_path = PurePosixPath(reference_file)
    if reference_path.is_absolute():
        return str(reference_path)
    if str(source_dir) == ".":
        combined = reference_path
    else:
        combined = source_dir / reference_path

    parts = []
    for part in combined.parts:
        if part in ("", "."):
            continue
        if part == "..":
            if parts:
                parts.pop()
            else:
                parts.append(part)
            continue
        parts.append(part)
    return str(PurePosixPath(*parts))


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
