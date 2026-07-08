import hashlib
import json
import re
import shutil
from io import BytesIO
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from .errors import HashMismatchError, WorkspaceError

CHECKOUT_METADATA_VERSION = 4
IGNORED_DOCUMENT_PROPERTIES = {
    "LastModifiedBy",
    "LastModifiedDate",
    "PLMRevision",
}
IGNORED_DOCUMENT_ATTRIBUTES = {
    "Touched",
    "stamp",
    "status",
}
CHECKOUT_FILE_REFERENCE_RE = re.compile(
    r"(?P<prefix>'?)(?:[A-Za-z]:)?[/\\][^'\"<>]*[/\\]checkout-\d+[/\\]files[/\\]"
    r"(?P<filename>[^'\"<>]+?\.FCStd)",
    re.IGNORECASE,
)
FLOAT_RE = re.compile(r"^[+-]?(?:\d+\.\d*|\.\d+)(?:[eE][+-]?\d+)?$")


def safe_join(root, relative_path):
    root = Path(root)
    path = PurePosixPath(relative_path)
    if path.is_absolute() or ".." in path.parts:
        raise WorkspaceError(f"Unsicherer Manifest-Pfad: {relative_path}")
    return root.joinpath(*path.parts)


def safe_zip_path(path):
    path = PurePosixPath(path)
    if path.is_absolute() or ".." in path.parts or not str(path).strip():
        raise WorkspaceError(f"Unsicherer ZIP-Pfad: {path}")
    return str(path)


def collect_project_fcstd_files(source_dir):
    source_dir = Path(source_dir).expanduser()
    if not source_dir.exists() or not source_dir.is_dir():
        raise WorkspaceError(f"Projektordner existiert nicht: {source_dir}")

    files = []
    for path in sorted(source_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() != ".fcstd":
            continue
        relative_path = safe_zip_path(path.relative_to(source_dir).as_posix())
        files.append((relative_path, path))

    if not files:
        raise WorkspaceError("Projektordner enthaelt keine FCStd-Dateien.")
    return files


def build_project_import_zip(source_dir, target_path):
    target_path = Path(target_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    files = collect_project_fcstd_files(source_dir)
    with ZipFile(target_path, "w") as archive:
        for relative_path, local_path in files:
            archive.write(local_path, relative_path)
    return [relative_path for relative_path, _local_path in files]


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


def write_checkout_metadata(path, metadata):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    (path / "checkout.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def read_checkout_metadata(path):
    return json.loads((Path(path) / "checkout.json").read_text(encoding="utf-8"))


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def next_revision_code(revision_code):
    match = re.fullmatch(r"R(\d{4})", str(revision_code or ""))
    if match is None:
        raise WorkspaceError(f"Ungueltiger Revisionscode: {revision_code}")
    return f"R{int(match.group(1)) + 1:04d}"


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


def ensure_checkout_manifest_files(client, manifest, path):
    target_root = files_root(path)
    downloaded = []
    for item in manifest["files"]:
        target = safe_join(target_root, item["path"])
        if target.exists():
            target.chmod(0o644)
            continue
        client.download_revision_file(item["download_url"], target, item["sha256"])
        if sha256_file(target) != item["sha256"]:
            raise HashMismatchError(f"SHA-256 stimmt nicht: {target}")
        downloaded.append(target)
    return downloaded


def _hash_zip_members(path, include_member):
    digest = hashlib.sha256()
    matched = False
    try:
        with ZipFile(path) as archive:
            names = sorted(name for name in archive.namelist() if include_member(name))
            for name in names:
                matched = True
                encoded_name = name.encode("utf-8")
                digest.update(len(encoded_name).to_bytes(8, "big"))
                digest.update(encoded_name)
                content = archive.read(name)
                digest.update(len(content).to_bytes(8, "big"))
                digest.update(content)
    except BadZipFile as exc:
        raise WorkspaceError(f"Ungueltige FCStd-Datei: {path}") from exc

    return digest.hexdigest() if matched else None


def _is_brep_member(name):
    lower = str(name).lower()
    return lower.endswith(".brp") or lower.endswith(".brep")


def _normalize_checkout_file_references(value):
    return CHECKOUT_FILE_REFERENCE_RE.sub(
        lambda match: f"{match.group('prefix')}{match.group('filename')}",
        value,
    )


def _normalize_document_attribute_value(value):
    value = _normalize_checkout_file_references(value)
    if not FLOAT_RE.match(value):
        return value

    try:
        number = float(value)
    except ValueError:
        return value
    if abs(number) < 1e-9:
        return "0"
    return format(number, ".12g")


def normalized_document_xml(document_xml):
    try:
        root = ElementTree.fromstring(document_xml)
    except ElementTree.ParseError as exc:
        raise WorkspaceError("Document.xml konnte nicht gelesen werden.") from exc

    properties_node = root.find("./Properties")
    if properties_node is not None:
        for property_node in list(properties_node.findall("./Property")):
            if property_node.attrib.get("name") in IGNORED_DOCUMENT_PROPERTIES:
                properties_node.remove(property_node)
        properties_node.attrib["Count"] = str(len(properties_node.findall("./Property")))

    for node in root.iter():
        for name in IGNORED_DOCUMENT_ATTRIBUTES:
            node.attrib.pop(name, None)
        for name, value in list(node.attrib.items()):
            node.attrib[name] = _normalize_document_attribute_value(value)
        node.attrib = dict(sorted(node.attrib.items()))
        if node.text is not None and not node.text.strip():
            node.text = None
        if node.tail is not None and not node.tail.strip():
            node.tail = None

    return ElementTree.tostring(root, encoding="utf-8")


def fcstd_technical_hashes(path):
    try:
        with ZipFile(path) as archive:
            if "Document.xml" not in archive.namelist():
                raise WorkspaceError(f"Document.xml fehlt in {path}")
            document_xml = normalized_document_xml(archive.read("Document.xml"))
    except BadZipFile as exc:
        raise WorkspaceError(f"Ungueltige FCStd-Datei: {path}") from exc

    return {
        "document_sha256": hashlib.sha256(document_xml).hexdigest(),
        "brep_sha256": _hash_zip_members(path, _is_brep_member),
    }


def build_checkout_metadata(manifest, path):
    target_root = files_root(path)
    files = []
    for item in manifest["files"]:
        target = safe_join(target_root, item["path"])
        if not target.exists():
            raise WorkspaceError(f"Checkout-Datei fehlt: {target}")
        technical_hashes = fcstd_technical_hashes(target)
        files.append(
            {
                "path": item["path"],
                "revision_id": item.get("revision_id"),
                "revision_code": item.get("revision_code"),
                **technical_hashes,
            }
        )
    return {"version": CHECKOUT_METADATA_VERSION, "files": files}


def ensure_checkout_metadata(manifest, path):
    metadata_path = Path(path) / "checkout.json"
    if not metadata_path.exists():
        raise WorkspaceError(
            "Checkout-Metadaten fehlen. Bitte Checkout abbrechen und neu auschecken."
        )
    metadata = read_checkout_metadata(path)
    if metadata.get("version") != CHECKOUT_METADATA_VERSION:
        raise WorkspaceError(
            "Checkout-Metadaten sind veraltet. Bitte Checkout abbrechen und neu auschecken."
        )
    return metadata


def changed_manifest_files(manifest, path):
    target_root = files_root(path)
    changed = []
    for item in manifest["files"]:
        target = safe_join(target_root, item["path"])
        if not target.exists():
            raise WorkspaceError(f"Checkout-Datei fehlt: {target}")
        digest = sha256_file(target)
        if digest == item["sha256"]:
            continue
        changed.append(
            {
                "path": item["path"],
                "local_path": target,
                "revision_id": item.get("revision_id"),
                "revision_code": item.get("revision_code"),
                "base_sha256": item.get("sha256"),
                "sha256": digest,
                "is_root": bool(item.get("is_root")),
            }
        )
    return changed


def _checkout_metadata_by_path(metadata):
    return {
        item.get("path"): item
        for item in metadata.get("files", [])
        if item.get("path")
    }


def technically_changed_manifest_files(manifest, metadata, path):
    target_root = files_root(path)
    metadata_by_path = _checkout_metadata_by_path(metadata)
    changed = []
    for item in manifest["files"]:
        manifest_path = item["path"]
        base = metadata_by_path.get(manifest_path)
        if base is None:
            raise WorkspaceError(f"Checkout-Metadaten fehlen: {manifest_path}")
        target = safe_join(target_root, manifest_path)
        if not target.exists():
            raise WorkspaceError(f"Checkout-Datei fehlt: {target}")
        technical_hashes = fcstd_technical_hashes(target)
        if (
            technical_hashes["document_sha256"] == base.get("document_sha256")
        ):
            continue
        digest = sha256_file(target)
        changed.append(
            {
                "path": manifest_path,
                "local_path": target,
                "revision_id": item.get("revision_id"),
                "revision_code": item.get("revision_code"),
                "base_sha256": item.get("sha256"),
                "sha256": digest,
                "is_root": bool(item.get("is_root")),
                **technical_hashes,
            }
        )
    return changed


def set_document_string_property(document_xml, name, value):
    root = ElementTree.fromstring(document_xml)
    properties_node = root.find("./Properties")
    if properties_node is None:
        properties_node = ElementTree.SubElement(root, "Properties")

    property_node = None
    for candidate in properties_node.findall("./Property"):
        if candidate.attrib.get("name") == name:
            property_node = candidate
            break

    if property_node is None:
        property_node = ElementTree.SubElement(
            properties_node,
            "Property",
            {"name": name, "type": "App::PropertyString"},
        )
    else:
        property_node.attrib["type"] = "App::PropertyString"

    for child in list(property_node):
        property_node.remove(child)
    ElementTree.SubElement(property_node, "String", {"value": value})
    properties_node.attrib["Count"] = str(len(properties_node.findall("./Property")))
    return ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)


def set_fcstd_plm_revision(path, revision_code):
    path = Path(path)
    try:
        original_data = path.read_bytes()
        source = BytesIO(original_data)
        target = BytesIO()
        with ZipFile(source) as archive:
            if "Document.xml" not in archive.namelist():
                raise WorkspaceError(f"Document.xml fehlt in {path}")
            updated_document_xml = set_document_string_property(
                archive.read("Document.xml"),
                "PLMRevision",
                revision_code,
            )

            with ZipFile(target, "w") as updated_archive:
                for info in archive.infolist():
                    content = (
                        updated_document_xml
                        if info.filename == "Document.xml"
                        else archive.read(info.filename)
                    )
                    updated_archive.writestr(info, content)
    except BadZipFile as exc:
        raise WorkspaceError(f"Ungueltige FCStd-Datei: {path}") from exc
    except ElementTree.ParseError as exc:
        raise WorkspaceError(f"Document.xml konnte nicht gelesen werden: {path}") from exc

    updated_data = target.getvalue()
    if updated_data != original_data:
        path.write_bytes(updated_data)


def update_changed_files_plm_revisions(changed_files):
    updated = []
    for item in changed_files:
        revision_code = next_revision_code(item.get("revision_code"))
        set_fcstd_plm_revision(item["local_path"], revision_code)
        updated.append({**item, "expected_revision_code": revision_code})
    return updated


def root_file_path(manifest, path):
    roots = [item for item in manifest["files"] if item.get("is_root")]
    if len(roots) != 1:
        raise WorkspaceError("Manifest muss genau eine Root-Datei enthalten.")
    return safe_join(files_root(path), roots[0]["path"])
