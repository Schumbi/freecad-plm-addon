import json
import re
import tempfile
from pathlib import Path

from .api_client import PLMClient
from .errors import ConflictError, EmptyGeometryError, PLMError
from .workspace import (
    archive_import_source_dir,
    build_checkout_metadata,
    build_project_import_zip,
    checkout_dir,
    delete_checkout_manifest_file,
    download_manifest_files,
    ensure_checkout_metadata,
    ensure_checkout_manifest_files,
    merge_checkout_metadata,
    prune_readonly_cache,
    read_manifest,
    removable_manifest_files,
    readonly_revision_dir,
    root_file_path,
    safe_join,
    technically_changed_manifest_files,
    touch_directory,
    update_changed_files_plm_revisions,
    write_manifest,
    write_checkout_metadata,
)


PANEL_OBJECT_NAME = "FreeCADPLMPanel"
_active_panel = None


def project_label(project):
    code = project.get("code") or project.get("project_code") or ""
    name = project.get("name") or project.get("title") or ""
    if code and name:
        return f"{code} - {name}"
    return code or name or f"Projekt {project.get('id', '')}".strip()


def project_edit_payload(values):
    payload = {}
    fields = ("code", "name", "status", "project_date", "description")
    for field in fields:
        value = values.get(field, "")
        payload[field] = value.strip() if isinstance(value, str) else value
    payload["code"] = payload.get("code", "").upper()
    return payload


def project_import_result_text(result):
    summary = result.get("import_summary") or {}
    snapshot = result.get("snapshot") or {}
    files = summary.get("files") or snapshot.get("entries") or []
    return (
        f"Import abgeschlossen: {snapshot.get('name') or 'Projektstand'} "
        f"({len(files)} Datei(en), "
        f"{summary.get('created_parts', 0)} neue Teile, "
        f"{summary.get('created_revisions', 0)} neue Revisionen, "
        f"{summary.get('reused_revisions', 0)} wiederverwendet)."
    )


def import_checkout_candidates(result):
    snapshot = result.get("snapshot") or {}
    snapshot_id = snapshot.get("id")
    candidates = []
    for entry in snapshot.get("entries") or []:
        revision_id = entry.get("revision_id")
        file_format = str(entry.get("file_format") or "").lower()
        path = entry.get("path") or entry.get("filename") or ""
        if not file_format:
            file_format = "fcstd" if path.lower().endswith(".fcstd") else ""
        if revision_id is None or file_format != "fcstd":
            continue
        part_number = entry.get("part_number") or ""
        part_name = entry.get("part_name") or ""
        category = entry.get("part_category") or ""
        label = path
        part_label_text = " - ".join(item for item in (part_number, part_name) if item)
        if part_label_text:
            label = f"{label} ({part_label_text})" if label else part_label_text
        if category:
            label = f"{label} [{category}]"
        candidates.append(
            {
                "label": label or f"Revision {revision_id}",
                "path": path,
                "revision_id": revision_id,
                "snapshot_id": snapshot_id,
                "part_id": entry.get("part_id"),
                "part_number": part_number,
                "part_name": part_name,
                "part_category": category,
            }
        )
    return candidates


def import_checkout_followup_text(result):
    snapshot = result.get("snapshot") or {}
    external_count = 0
    for entry in snapshot.get("entries") or []:
        path = str(entry.get("path") or entry.get("filename") or "").lower()
        file_format = str(entry.get("file_format") or "").lower()
        if file_format in ("step", "stl") or path.endswith((".step", ".stp", ".stl")):
            external_count += 1
    if external_count:
        revision_word = "Revision" if external_count == 1 else "Revisionen"
        return (
            f"{external_count} STEP-/STL-{revision_word} importiert. "
            "Diese Austauschmodelle können in der Revisionsliste schreibgeschützt geöffnet werden."
        )
    return "Keine bearbeitbare FCStd-Revision für einen Checkout gefunden."


def connection_label(server_url):
    text = server_url.replace("https://", "").replace("http://", "").strip("/")
    return f"Verbunden mit {text}" if text else "Nicht verbunden."


def save_slicer_settings(kind, executable, extra_args):
    from . import config

    config.set_slicer_kind(kind)
    config.set_slicer_executable(executable)
    config.set_slicer_extra_args(extra_args)


def part_label(part):
    number = part.get("number") or part.get("part_number") or part.get("code") or ""
    name = part.get("name") or part.get("title") or ""
    status = part.get("status") or part.get("release_status") or ""
    label = " - ".join(value for value in (number, name) if value)
    if not label:
        label = f"Teil {part.get('id', '')}".strip()
    if status:
        return f"{label} [{status}]"
    return label


def part_edit_payload(values, include_number=False):
    payload = {}
    fields = ("name", "description", "material", "supplier", "tags", "category")
    if include_number:
        fields = ("number", *fields)
    for field in fields:
        value = values.get(field, "")
        payload[field] = value.strip() if isinstance(value, str) else value
    payload["is_archived"] = bool(values.get("is_archived", False))
    return payload


def new_part_filename(name):
    stem = re.sub(r"[^\w.-]+", "_", str(name or "").strip(), flags=re.UNICODE)
    stem = stem.strip("._-") or "Neues_Teil"
    if stem.lower().endswith(".fcstd"):
        stem = stem[:-6].rstrip("._-") or "Neues_Teil"
    return f"{stem}.FCStd"


def revisions_from_part_detail(part_detail):
    if not isinstance(part_detail, dict):
        return []
    for key in ("revisions", "revision_set", "latest_revisions"):
        revisions = part_detail.get(key)
        if isinstance(revisions, list):
            return revisions
    part = part_detail.get("part") if isinstance(part_detail.get("part"), dict) else part_detail
    for key in ("revisions", "revision_set", "latest_revisions"):
        revisions = part.get(key)
        if isinstance(revisions, list):
            return revisions
    return []


def revision_label(revision):
    number = (
        revision.get("revision")
        or revision.get("revision_code")
        or revision.get("version")
        or revision.get("number")
        or revision.get("label")
        or ""
    )
    status = revision_status_label(
        revision.get("status") or revision.get("release_status") or ""
    )
    file_format = revision_format_label(revision)
    filename = revision.get("original_filename") or revision.get("filename") or revision.get("file_name") or ""
    created = revision.get("created_at") or revision.get("created") or revision.get("uploaded_at") or ""
    if number:
        label = f"R{number}" if str(number).isdigit() else str(number)
    else:
        label = f"Revision {revision.get('id', '')}".strip()
    details = [value for value in (status, file_format, filename, created[:10]) if value]
    if details:
        return " · ".join([label, *details])
    return label


def revision_status_label(status):
    labels = {
        "draft": "Entwurf",
        "released": "Freigegeben",
        "obsolete": "Obsolet",
    }
    value = str(status or "").strip()
    return labels.get(value.lower(), value)


def revision_file_format(revision):
    if not isinstance(revision, dict):
        return ""
    file_format = str(revision.get("file_format") or "").strip().lower()
    if file_format:
        return file_format
    filename = str(
        revision.get("original_filename")
        or revision.get("filename")
        or revision.get("file_name")
        or ""
    ).lower()
    if filename.endswith(".fcstd"):
        return "fcstd"
    if filename.endswith((".step", ".stp")):
        return "step"
    if filename.endswith(".stl"):
        return "stl"
    return ""


def revision_format_label(revision):
    labels = {"fcstd": "FCStd", "step": "STEP", "stl": "STL"}
    file_format = revision_file_format(revision)
    return labels.get(file_format, file_format.upper())


def revision_is_checkout_editable(revision):
    return revision_file_format(revision) == "fcstd"


def revision_primary_action(revision):
    if not isinstance(revision, dict) or revision.get("id") is None:
        return "missing_revision"
    if revision_is_checkout_editable(revision):
        return "checkout"
    return "open_readonly"


def revision_workflow_hint(revision):
    file_format = revision_format_label(revision) or "CAD"
    if revision_is_checkout_editable(revision):
        return f"{file_format}: bearbeitbar · Doppelklick startet den Checkout"
    return f"{file_format}: Austauschmodell · Doppelklick öffnet schreibgeschützt"


def active_checkout_revision_id(checkout):
    if not isinstance(checkout, dict):
        return None
    for key in ("revision_id", "base_revision_id", "root_revision_id"):
        if checkout.get(key) is not None:
            return checkout.get(key)
    for key in ("revision", "base_revision", "root_revision"):
        revision = checkout.get(key)
        if isinstance(revision, dict) and revision.get("id") is not None:
            return revision.get("id")
    return None


def checkout_guard_action(active_checkout, target_revision):
    if not isinstance(target_revision, dict) or target_revision.get("id") is None:
        return "missing_revision"
    if not active_checkout:
        return "checkout"
    if active_checkout_revision_id(active_checkout) == target_revision.get("id"):
        return "same_checkout"
    return "blocked_by_other_checkout"


def checkout_visual_state(checkout, local_checkout_id=None, error=False):
    if not isinstance(checkout, dict) or checkout.get("id") is None:
        return "none"
    if error:
        return "error"
    if checkout.get("id") == local_checkout_id:
        return "local"
    return "server"


def checkout_can_cancel(checkout):
    return isinstance(checkout, dict) and checkout.get("id") is not None


def context_primary_action(kind, revision=None, checkout=None, local_checkout_id=None):
    if kind in ("", None):
        return "import_project"
    if kind == "project":
        return "new_part"
    if kind == "part":
        return "edit_part"
    if kind == "checkout_error":
        return "refresh"
    if kind != "revision":
        return "none"
    state = checkout_visual_state(checkout, local_checkout_id)
    if state == "local":
        return "checkin"
    if state == "server":
        return "reopen_checkout"
    return revision_primary_action(revision)


def checkout_display_name(path):
    if not path:
        return ""
    return Path(path).name or str(path)


def print_freecad_console(message):
    if not message:
        return
    text = str(message)
    if text.startswith("[FreeCAD-PLM]"):
        output = text
    elif text.startswith("FreeCAD-PLM "):
        output = f"[FreeCAD-PLM] {text[len('FreeCAD-PLM '):]}"
    else:
        output = f"[FreeCAD-PLM] {text}"
    try:
        import FreeCAD
    except Exception:
        return
    console = getattr(FreeCAD, "Console", None)
    printer = getattr(console, "PrintMessage", None)
    if callable(printer):
        printer(f"{output}\n")


def compact_revision_summary(revision):
    if not isinstance(revision, dict) or revision.get("id") is None:
        return "Keine Revision ausgewählt."
    number = (
        revision.get("revision")
        or revision.get("revision_code")
        or revision.get("version")
        or revision.get("number")
        or revision.get("label")
        or revision.get("id")
    )
    status = revision_status_label(
        revision.get("status") or revision.get("release_status")
    )
    file_format = revision_format_label(revision)
    filename = revision.get("original_filename") or revision.get("filename") or revision.get("file_name")
    created = revision.get("created_at") or revision.get("created") or revision.get("uploaded_at")
    details = [f"R{number}" if str(number).isdigit() else str(number)]
    details.extend(
        str(value)
        for value in (status, file_format, filename, (created or "")[:10])
        if value
    )
    return " · ".join(details)


def format_bytes(size_bytes):
    if size_bytes in ("", None):
        return ""
    try:
        value = int(size_bytes)
    except (TypeError, ValueError):
        return str(size_bytes)
    units = ("B", "KB", "MB", "GB")
    amount = float(value)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(amount)} {unit}"
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return str(value)


def revision_overview_text(revision):
    rows = [
        ("ID", revision.get("id")),
        ("Revision", revision.get("revision_code") or revision.get("revision") or revision.get("version")),
        ("Status", revision.get("status") or revision.get("release_status")),
        ("Datei", revision.get("original_filename") or revision.get("filename") or revision.get("file_name")),
        ("Format", revision.get("file_format")),
        ("Groesse", format_bytes(revision.get("size_bytes"))),
        ("SHA-256", revision.get("sha256")),
        ("Erstellt", revision.get("created_at") or revision.get("created") or revision.get("uploaded_at")),
        ("Freigegeben", revision.get("released_at")),
        ("Download-URL", revision.get("download_url")),
    ]
    lines = [f"{label}: {value}" for label, value in rows if value not in ("", None)]
    return "\n".join(lines) or "Keine Revisionsdetails vorhanden."


def revision_notes_text(revision):
    return revision.get("notes") or "Keine Notizen vorhanden."


def revision_notes_payload(notes):
    return {"notes": (notes or "").strip()}


def revision_technical_text(revision):
    metadata = revision.get("extracted_metadata")
    if not metadata:
        return "Keine technischen Metadaten vorhanden."
    return json.dumps(metadata, indent=2, sort_keys=True, ensure_ascii=False)


def annotation_label(annotation):
    parts = []
    target = annotation.get("object_name") or ""
    subelement = annotation.get("subelement") or ""
    if target and subelement:
        parts.append(f"{target}.{subelement}")
    elif target:
        parts.append(target)

    status = annotation.get("status") or ""
    if status:
        parts.append(f"[{status}]")

    author = annotation.get("created_by") or ""
    created = annotation.get("created_at") or ""
    if author or created:
        parts.append(" ".join(value for value in (author, created[:10]) if value))

    text = annotation.get("text") or ""
    if text:
        parts.append(text)

    return " - ".join(parts) or f"Anmerkung {annotation.get('id', '')}".strip()


def annotation_update_payload(text=None, status=None):
    payload = {}
    if text is not None:
        payload["text"] = text.strip()
    if status is not None:
        payload["status"] = status
    return payload


def annotation_create_payload(revision_id, text, object_name="", subelement=""):
    object_name = object_name.strip() if isinstance(object_name, str) else ""
    subelement = subelement.strip() if isinstance(subelement, str) else ""
    return {
        "revision_id": revision_id,
        "text": text.strip(),
        "object_name": object_name,
        "subelement": subelement,
    }


def annotation_matches_filter(annotation, filter_key, revision_id):
    status = annotation.get("status") or "open"
    annotation_revision_id = annotation.get("revision_id")
    if filter_key == "open":
        return status != "resolved"
    if filter_key == "resolved":
        return status == "resolved"
    if filter_key == "revision":
        return annotation_revision_id == revision_id
    if filter_key == "part":
        return annotation_revision_id is None
    return True


def annotations_for_revision(annotations, revision_id):
    return [
        annotation
        for annotation in annotations
        if annotation.get("revision_id") in (None, revision_id)
    ]


def checkout_project_code(checkout):
    project = checkout.get("project") if isinstance(checkout.get("project"), dict) else {}
    return (
        project.get("code")
        or project.get("project_code")
        or checkout.get("project_code")
        or f"project-{project.get('id') or checkout.get('project_id')}"
    )


def checkout_label(checkout):
    checkout_id = checkout.get("id", "")
    project = checkout.get("project") if isinstance(checkout.get("project"), dict) else {}
    part = checkout.get("part") if isinstance(checkout.get("part"), dict) else {}
    revision = checkout.get("revision") if isinstance(checkout.get("revision"), dict) else {}
    project_code = checkout_project_code(checkout)
    part_text = part.get("number") or part.get("part_number") or part.get("name") or ""
    revision_text = (
        revision.get("revision_code")
        or revision.get("revision")
        or revision.get("version")
        or revision.get("id")
        or ""
    )
    details = [value for value in (project_code, part_text, f"Revision {revision_text}") if value]
    if details:
        return f"Checkout {checkout_id} - {', '.join(str(value) for value in details)}"
    return f"Checkout {checkout_id}".strip()


def response_manifest(response):
    if response is None:
        return None
    return response.get("manifest", response) if isinstance(response, dict) else response


def checkin_result_text(response):
    if not isinstance(response, dict):
        return ""
    parts = []
    revision = response.get("revision")
    if isinstance(revision, dict) and revision.get("id") is not None:
        parts.append(f"Neue Root-Revision: {revision.get('id')}.")

    revisions = response.get("revisions")
    if isinstance(revisions, list):
        count = len(revisions)
        if count:
            suffix = "" if count == 1 else "en"
            parts.append(f"Neue Revision{suffix}: {count}.")
    ignored_files = response.get("ignored_files")
    if isinstance(ignored_files, list) and ignored_files:
        parts.append(f"Ignoriert: {len(ignored_files)}.")
    return " ".join(parts)


def checkin_created_revision_count(response):
    if not isinstance(response, dict):
        return 0
    revisions = response.get("revisions")
    if isinstance(revisions, list):
        return len(revisions)
    revision = response.get("revision")
    return 1 if isinstance(revision, dict) and revision.get("id") is not None else 0


def checkin_completed(response):
    checkout = response.get("checkout") if isinstance(response, dict) else None
    return isinstance(checkout, dict) and checkout.get("status") == "completed"


def checkout_file_label(item):
    path = item.get("path") or item.get("filename") or "Datei"
    part_number = item.get("part_number") or ""
    revision_code = item.get("revision_code") or ""
    details = " · ".join(value for value in (part_number, revision_code) if value)
    return f"{path} ({details})" if details else path


def checkin_conflict_text(exc):
    details = str(exc).strip()
    prefix = (
        "Check-in-Konflikt: Der Serverstand passt nicht mehr zum lokalen Checkout. "
        "Bitte aktive Checkouts aktualisieren und den Checkout neu laden oder abbrechen."
    )
    if details:
        return f"{prefix} Servermeldung: {details}"
    return prefix


def unchanged_checkout_text(saved_count=0):
    message = "Keine modellrelevanten Änderungen; Checkout bleibt aktiv."
    if saved_count:
        message = f"{message} Gespeichert: {saved_count}."
    return message


def _load_qt():
    try:
        from PySide import QtCore, QtGui

        return QtCore, QtGui, QtGui
    except ImportError:
        pass

    try:
        from PySide6 import QtCore, QtGui, QtWidgets

        return QtCore, QtGui, QtWidgets
    except ImportError:
        from PySide2 import QtCore, QtGui, QtWidgets

        return QtCore, QtGui, QtWidgets


class PLMPanel:
    def __init__(self):
        from . import config

        self.QtCore, self.QtGui, self.QtWidgets = _load_qt()
        self.widget = self.QtWidgets.QWidget()
        self.widget.setObjectName("FreeCADPLMPanelWidget")
        self.readonly_document_names = []
        self.checkout_document_names = []
        self.active_checkout = None
        self.active_checkout_dir = None
        self.active_checkout_root_path = None
        self.server_checkouts = []
        self.checkout_tree_items = {}
        self.checkout_errors = {}
        self.context_primary_callback = None
        self.context_primary_label = ""
        self.context_more_actions = []
        self.current_annotations = []
        self.slicer_monitors = {}

        layout = self.QtWidgets.QVBoxLayout(self.widget)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        header = self.QtWidgets.QWidget()
        header_layout = self.QtWidgets.QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(4)
        header_height = self.connection_summary_height()
        header.setFixedHeight(header_height)

        self.connection_summary = self.QtWidgets.QLabel("Nicht verbunden.")
        self.connection_summary.setWordWrap(False)
        self.connection_summary.setSizePolicy(
            self.QtWidgets.QSizePolicy.Ignored,
            self.QtWidgets.QSizePolicy.Preferred,
        )
        self.connection_summary.setFixedHeight(header_height)
        header_layout.addWidget(self.connection_summary, 1)

        self.refresh_button = self.QtWidgets.QPushButton("Aktualisieren")
        self.refresh_button.setVisible(False)
        self.refresh_button.setFixedHeight(header_height)
        header_layout.addWidget(self.refresh_button)

        self.settings_button = self.QtWidgets.QPushButton("Verbindungseinstellungen")
        self.settings_button.setFixedHeight(header_height)
        header_layout.addWidget(self.settings_button)
        layout.addWidget(header)

        self.server_url = self.QtWidgets.QLineEdit(config.get_server_url())
        self.api_token = self.QtWidgets.QLineEdit(config.get_api_token())
        self.api_token.setEchoMode(self.QtWidgets.QLineEdit.Password)
        self.workspace_root = self.QtWidgets.QLineEdit(config.get_workspace_root())
        self.cache_max_fcstd_files = self.QtWidgets.QSpinBox()
        self.cache_max_fcstd_files.setMinimum(config.DEFAULT_CACHE_MAX_FCSTD_FILES)
        self.cache_max_fcstd_files.setMaximum(9999)
        self.cache_max_fcstd_files.setValue(config.get_cache_max_fcstd_files())
        self.cache_max_projects = self.QtWidgets.QSpinBox()
        self.cache_max_projects.setMinimum(config.DEFAULT_CACHE_MAX_PROJECTS)
        self.cache_max_projects.setMaximum(999)
        self.cache_max_projects.setValue(config.get_cache_max_projects())
        self.cache_max_revisions_per_project = self.QtWidgets.QSpinBox()
        self.cache_max_revisions_per_project.setMinimum(
            config.DEFAULT_CACHE_MAX_REVISIONS_PER_PROJECT
        )
        self.cache_max_revisions_per_project.setMaximum(999)
        self.cache_max_revisions_per_project.setValue(
            config.get_cache_max_revisions_per_project()
        )
        self.slicer_kind = config.get_slicer_kind()
        self.slicer_executable = config.get_slicer_executable()
        self.slicer_extra_args = config.get_slicer_extra_args()

        splitter = self.QtWidgets.QSplitter(self.QtCore.Qt.Vertical)
        layout.addWidget(splitter, 1)

        browser_widget = self.QtWidgets.QWidget()
        browser_layout = self.QtWidgets.QVBoxLayout(browser_widget)
        browser_layout.setContentsMargins(2, 2, 2, 2)
        browser_layout.setSpacing(4)

        tree_header = self.QtWidgets.QHBoxLayout()
        tree_header.addWidget(self.QtWidgets.QLabel("Projekte · Teile · Revisionen"))
        tree_header.addStretch(1)
        browser_layout.addLayout(tree_header)

        self.browser_tree = self.QtWidgets.QTreeWidget()
        self.browser_tree.setHeaderHidden(True)
        self.browser_tree.setUniformRowHeights(True)
        self.browser_tree.setAnimated(False)
        self.browser_tree.setContextMenuPolicy(self.QtCore.Qt.CustomContextMenu)
        browser_layout.addWidget(self.browser_tree, 1)

        details_widget = self.QtWidgets.QWidget()
        details_widget.setObjectName("PLMActionBar")
        details_widget.setStyleSheet(
            "#PLMActionBar {"
            "border-top: 1px solid #c8c8c8;"
            "background: #f6f6f6;"
            "}"
        )
        details_widget.setMaximumHeight(48)
        details_layout = self.QtWidgets.QVBoxLayout(details_widget)
        details_layout.setContentsMargins(4, 3, 4, 3)
        details_layout.setSpacing(3)

        self.detail_tabs = self.QtWidgets.QTabWidget()

        self.project_details = self.QtWidgets.QWidget()
        project_form = self.QtWidgets.QFormLayout(self.project_details)
        self.project_code = self.QtWidgets.QLineEdit()
        self.project_name = self.QtWidgets.QLineEdit()
        self.project_status = self.QtWidgets.QComboBox()
        self.project_status.addItem("Laufend", "running")
        self.project_status.addItem("Abgeschlossen", "completed")
        self.project_status.addItem("Idee", "idea")
        self.project_status.addItem("Wichtig", "important")
        self.project_status.addItem("Auftrag", "order")
        self.project_date = self.QtWidgets.QLineEdit()
        self.project_date.setPlaceholderText("YYYY-MM-DD")
        self.project_description = self.QtWidgets.QPlainTextEdit()
        self.project_description.setMaximumHeight(100)
        self.save_project_button = self.QtWidgets.QPushButton("Projekt speichern")
        self.save_project_button.setEnabled(False)
        project_form.addRow("Code", self.project_code)
        project_form.addRow("Name", self.project_name)
        project_form.addRow("Status", self.project_status)
        project_form.addRow("Datum", self.project_date)
        project_form.addRow("Beschreibung", self.project_description)
        project_form.addRow("", self.save_project_button)
        self.detail_tabs.addTab(self.project_details, "Projekt")

        self.part_details = self.QtWidgets.QWidget()
        part_form = self.QtWidgets.QFormLayout(self.part_details)
        self.part_number = self.QtWidgets.QLineEdit()
        self.part_number.setReadOnly(True)
        self.part_name = self.QtWidgets.QLineEdit()
        self.part_category = self.QtWidgets.QComboBox()
        self.part_category.addItem("Teil", "part")
        self.part_category.addItem("Baugruppe", "assembly")
        self.part_description = self.QtWidgets.QPlainTextEdit()
        self.part_description.setMaximumHeight(80)
        self.part_material = self.QtWidgets.QLineEdit()
        self.part_supplier = self.QtWidgets.QLineEdit()
        self.part_tags = self.QtWidgets.QLineEdit()
        self.part_archived = self.QtWidgets.QCheckBox("Archiviert")
        self.save_part_button = self.QtWidgets.QPushButton("Stammdaten speichern")
        self.save_part_button.setEnabled(False)
        part_form.addRow("Nummer", self.part_number)
        part_form.addRow("Name", self.part_name)
        part_form.addRow("Kategorie", self.part_category)
        part_form.addRow("Beschreibung", self.part_description)
        part_form.addRow("Material", self.part_material)
        part_form.addRow("Lieferant", self.part_supplier)
        part_form.addRow("Tags", self.part_tags)
        part_form.addRow("", self.part_archived)
        part_form.addRow("", self.save_part_button)
        self.detail_tabs.addTab(self.part_details, "Teil")

        self.revision_overview = self.QtWidgets.QPlainTextEdit()
        self.revision_overview.setReadOnly(True)
        self.revision_overview.setPlainText("Keine Revision ausgewählt.")
        self.detail_tabs.addTab(self.revision_overview, "Übersicht")

        self.revision_notes = self.QtWidgets.QPlainTextEdit()
        self.revision_notes.setPlainText("Keine Revision ausgewählt.")
        revision_notes_action_row = self.QtWidgets.QHBoxLayout()
        self.save_revision_notes_button = self.QtWidgets.QPushButton("Notizen speichern")
        self.revert_revision_notes_button = self.QtWidgets.QPushButton("Zurücksetzen")
        self.save_revision_notes_button.setEnabled(False)
        self.revert_revision_notes_button.setEnabled(False)
        revision_notes_action_row.addWidget(self.save_revision_notes_button)
        revision_notes_action_row.addWidget(self.revert_revision_notes_button)
        revision_notes_widget = self.QtWidgets.QWidget()
        revision_notes_layout = self.QtWidgets.QVBoxLayout(revision_notes_widget)
        revision_notes_layout.addWidget(self.revision_notes)
        revision_notes_layout.addLayout(revision_notes_action_row)
        self.detail_tabs.addTab(revision_notes_widget, "Notizen")

        annotation_widget = self.QtWidgets.QWidget()
        annotation_layout = self.QtWidgets.QVBoxLayout(annotation_widget)
        annotation_filter_row = self.QtWidgets.QHBoxLayout()
        annotation_filter_row.addWidget(self.QtWidgets.QLabel("Filter"))
        self.annotation_filter = self.QtWidgets.QComboBox()
        self.annotation_filter.addItem("Alle", "all")
        self.annotation_filter.addItem("Offen", "open")
        self.annotation_filter.addItem("Erledigt", "resolved")
        self.annotation_filter.addItem("Nur diese Revision", "revision")
        self.annotation_filter.addItem("Teil allgemein", "part")
        annotation_filter_row.addWidget(self.annotation_filter)
        annotation_layout.addLayout(annotation_filter_row)
        self.annotations = self.QtWidgets.QListWidget()
        annotation_layout.addWidget(self.annotations)
        annotation_action_row = self.QtWidgets.QHBoxLayout()
        self.new_annotation_button = self.QtWidgets.QPushButton("Neu")
        self.edit_annotation_button = self.QtWidgets.QPushButton("Bearbeiten")
        self.resolve_annotation_button = self.QtWidgets.QPushButton("Erledigt")
        self.reopen_annotation_button = self.QtWidgets.QPushButton("Wieder öffnen")
        self.delete_annotation_button = self.QtWidgets.QPushButton("Löschen")
        self.new_annotation_button.setEnabled(False)
        self.edit_annotation_button.setEnabled(False)
        self.resolve_annotation_button.setEnabled(False)
        self.reopen_annotation_button.setEnabled(False)
        self.delete_annotation_button.setEnabled(False)
        annotation_action_row.addWidget(self.new_annotation_button)
        annotation_action_row.addWidget(self.edit_annotation_button)
        annotation_action_row.addWidget(self.resolve_annotation_button)
        annotation_action_row.addWidget(self.reopen_annotation_button)
        annotation_action_row.addWidget(self.delete_annotation_button)
        annotation_layout.addLayout(annotation_action_row)
        self.detail_tabs.addTab(annotation_widget, "Anmerkungen")

        self.technical_details = self.QtWidgets.QPlainTextEdit()
        self.technical_details.setReadOnly(True)
        self.technical_details.setPlainText("Keine Revision ausgewählt.")
        self.detail_tabs.addTab(self.technical_details, "Technik")

        self.detail_tabs.setVisible(False)

        context_row = self.QtWidgets.QHBoxLayout()
        context_row.setContentsMargins(0, 0, 0, 0)
        context_row.setSpacing(4)
        self.context_summary = self.QtWidgets.QLabel("Projekt auswählen.")
        self.context_summary.setWordWrap(False)
        self.context_summary.setMinimumWidth(80)
        self.context_summary.setSizePolicy(
            self.QtWidgets.QSizePolicy.Ignored,
            self.QtWidgets.QSizePolicy.Preferred,
        )
        context_row.addWidget(self.context_summary, 1)
        self.context_primary_button = self.QtWidgets.QPushButton("Projekt importieren")
        self.context_primary_button.setEnabled(False)
        self.context_primary_button.setFixedHeight(self.connection_summary_height())
        context_row.addWidget(self.context_primary_button)
        self.context_more_button = self.QtWidgets.QToolButton()
        self.context_more_button.setText("Mehr")
        self.context_more_button.setPopupMode(self.QtWidgets.QToolButton.InstantPopup)
        self.context_more_button.setFixedHeight(self.connection_summary_height())
        self.context_more_button.setEnabled(False)
        context_row.addWidget(self.context_more_button)
        details_layout.addLayout(context_row)

        self.status = self.QtWidgets.QLabel("")
        self.status.setVisible(False)

        splitter.addWidget(browser_widget)
        splitter.addWidget(details_widget)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)

        self.refresh_button.clicked.connect(self.refresh_projects)
        self.settings_button.clicked.connect(self.show_connection_settings_dialog)
        self.browser_tree.itemSelectionChanged.connect(self.browser_selection_changed)
        self.browser_tree.itemExpanded.connect(self.browser_item_expanded)
        self.browser_tree.itemDoubleClicked.connect(self.browser_item_double_clicked)
        self.browser_tree.customContextMenuRequested.connect(self.show_browser_context_menu)
        self.context_primary_button.clicked.connect(self.run_context_primary_action)
        self.save_revision_notes_button.clicked.connect(self.save_revision_notes)
        self.revert_revision_notes_button.clicked.connect(self.revert_revision_notes)
        self.annotation_filter.currentIndexChanged.connect(self.apply_current_annotation_filter)
        self.annotations.itemSelectionChanged.connect(self.update_annotation_controls)
        self.new_annotation_button.clicked.connect(
            lambda: self.create_annotation_for_current_revision()
        )
        self.edit_annotation_button.clicked.connect(self.edit_selected_annotation)
        self.resolve_annotation_button.clicked.connect(
            lambda: self.update_selected_annotation_status("resolved")
        )
        self.reopen_annotation_button.clicked.connect(
            lambda: self.update_selected_annotation_status("open")
        )
        self.delete_annotation_button.clicked.connect(self.delete_selected_annotation)
        self.update_context_actions()

    def connection_summary_height(self):
        return self.widget.fontMetrics().lineSpacing() + 8

    def set_status(self, message):
        print_freecad_console(message)

    def set_connected(self, server_url):
        self.connection_summary.setText(connection_label(server_url))
        self.refresh_button.setVisible(True)
        self.update_context_actions()

    def run_context_primary_action(self):
        callback = self.context_primary_callback
        if callable(callback):
            callback()

    def set_context_actions(self, summary, primary_label, primary_callback, more_actions):
        self.context_summary.setText(summary)
        self.context_primary_button.setText(primary_label or "Keine Aktion")
        self.context_primary_callback = primary_callback
        self.context_primary_label = primary_label or ""
        self.context_more_actions = list(more_actions)
        self.context_primary_button.setEnabled(callable(primary_callback))
        menu = self.QtWidgets.QMenu(self.context_more_button)
        for label, callback in more_actions:
            if label is None:
                menu.addSeparator()
                continue
            action = menu.addAction(label)
            action.triggered.connect(
                lambda _checked=False, selected_callback=callback: selected_callback()
            )
        self.context_more_button.setMenu(menu)
        self.context_more_button.setEnabled(bool(more_actions))

    def update_context_actions(self):
        item = self.browser_tree.currentItem()
        kind = self.tree_item_kind(item)
        project = self.selected_project()
        part = self.selected_part()
        revision = self.selected_revision()
        checkout = self.selected_tree_checkout()
        primary = context_primary_action(
            kind,
            revision,
            checkout,
            self.active_checkout_id(),
        )
        summary = "Projekt auswählen."
        label = "Projekt importieren"
        callback = (
            self.import_project_dialog
            if self.server_url.text().strip() and self.api_token.text().strip()
            else None
        )
        more = []

        if kind == "project":
            summary = project_label(project or {})
            label = "Neues Teil"
            callback = self.create_part_dialog
            more = [
                ("Lokale FCStd hinzufügen", self.add_local_fcstd_part_dialog),
                ("Projekt importieren", self.import_project_dialog),
                ("Projekt bearbeiten", self.show_project_dialog),
            ]
        elif kind == "part":
            summary = part_label(part or {})
            label = "Teil bearbeiten"
            callback = self.show_part_dialog
            more = [("Revisionen aktualisieren", self.refresh_revisions)]
        elif kind == "checkout_error":
            summary = item.text(0) if item is not None else "Checkout-Fehler"
            label = "Aktualisieren"
            callback = self.refresh_projects
            if checkout_can_cancel(checkout):
                more = [("Checkout abbrechen", self.cancel_selected_checkout)]
        elif kind == "revision":
            summary = compact_revision_summary(revision)
            state = checkout_visual_state(
                checkout,
                self.active_checkout_id(),
                bool(self.tree_item_checkout_error(item)),
            )
            if state == "local":
                summary = f"Checkout lokal · {summary}"
            elif state == "server":
                summary = f"Checkout auf Server · {summary}"
            elif state == "error":
                summary = f"Checkout fehlerhaft · {summary}"

            action_map = {
                "checkout": ("Auschecken", self.checkout_selected_revision),
                "open_readonly": (
                    "Schreibgeschützt öffnen",
                    self.open_selected_revision_readonly,
                ),
                "reopen_checkout": ("Checkout öffnen", self.reopen_selected_checkout),
                "checkin": ("Einchecken", self.checkin_active_checkout),
                "refresh": ("Aktualisieren", self.refresh_projects),
            }
            label, callback = action_map.get(primary, ("Keine Aktion", None))
            if state == "local":
                more = [
                    ("Checkout öffnen", self.open_active_checkout_root),
                    ("Lokale FCStd hinzufügen", self.add_local_fcstd_part_dialog),
                    ("Teil hinzufügen", self.choose_revision_for_active_checkout),
                    ("Teil entfernen", self.remove_file_from_active_checkout),
                    (None, None),
                    ("Checkout abbrechen", self.cancel_active_checkout),
                ]
            else:
                if state in ("server", "error") and checkout_can_cancel(checkout):
                    more.append(("Checkout abbrechen", self.cancel_selected_checkout))
                if revision_is_checkout_editable(revision or {}):
                    more.append(("Schreibgeschützt öffnen", self.open_selected_revision_readonly))
                    if (
                        self.active_checkout_id() is not None
                        and revision.get("id") != active_checkout_revision_id(self.active_checkout)
                    ):
                        more.append(
                            ("Zum aktiven Checkout hinzufügen", self.add_selected_file_to_active_checkout)
                        )
            if revision_file_format(revision or {}) in ("fcstd", "step", "stl"):
                more.append(("Druckprojekt öffnen/erstellen", self.open_selected_revision_in_slicer))
                more.append(("Zum Druckprojekt hinzufügen", self.add_selected_revision_to_print_project))
            more.extend(
                [
                    (None, None),
                    ("Details", self.show_revision_details_dialog),
                    ("Notizen", self.show_revision_notes_dialog),
                    ("Anmerkungen", self.show_annotations_dialog),
                ]
            )
        self.set_context_actions(summary, label, callback, more)

    def client(self):
        return PLMClient(self.server_url.text().strip(), self.api_token.text().strip())

    def show_connection_settings_dialog(self):
        dialog = self.QtWidgets.QDialog(self.widget)
        dialog.setWindowTitle("Verbindungseinstellungen")
        layout = self.QtWidgets.QVBoxLayout(dialog)
        form = self.QtWidgets.QFormLayout()

        server_url = self.QtWidgets.QLineEdit(self.server_url.text())
        api_token = self.QtWidgets.QLineEdit(self.api_token.text())
        api_token.setEchoMode(self.QtWidgets.QLineEdit.Password)
        workspace_root = self.QtWidgets.QLineEdit(self.workspace_root.text())
        cache_max_fcstd_files = self.QtWidgets.QSpinBox()
        cache_max_fcstd_files.setMinimum(self.cache_max_fcstd_files.minimum())
        cache_max_fcstd_files.setMaximum(self.cache_max_fcstd_files.maximum())
        cache_max_fcstd_files.setValue(self.cache_max_fcstd_files.value())
        cache_max_projects = self.QtWidgets.QSpinBox()
        cache_max_projects.setMinimum(self.cache_max_projects.minimum())
        cache_max_projects.setMaximum(self.cache_max_projects.maximum())
        cache_max_projects.setValue(self.cache_max_projects.value())
        cache_max_revisions_per_project = self.QtWidgets.QSpinBox()
        cache_max_revisions_per_project.setMinimum(
            self.cache_max_revisions_per_project.minimum()
        )
        cache_max_revisions_per_project.setMaximum(
            self.cache_max_revisions_per_project.maximum()
        )
        cache_max_revisions_per_project.setValue(
            self.cache_max_revisions_per_project.value()
        )
        slicer_kind = self.QtWidgets.QComboBox()
        slicer_kind.addItem("Automatisch erkennen", "auto")
        slicer_kind.addItem("Bambu Studio", "bambu")
        slicer_kind.addItem("OrcaSlicer", "orca")
        slicer_kind.addItem("Benutzerdefiniert", "custom")
        slicer_kind_index = slicer_kind.findData(self.slicer_kind)
        slicer_kind.setCurrentIndex(slicer_kind_index if slicer_kind_index >= 0 else 0)
        slicer_executable = self.QtWidgets.QLineEdit(self.slicer_executable)
        slicer_executable.setPlaceholderText("Leer lassen für automatische Erkennung")
        slicer_extra_args = self.QtWidgets.QLineEdit(self.slicer_extra_args)
        slicer_extra_args.setPlaceholderText('["--option"]')

        form.addRow("Server", server_url)
        form.addRow("API-Token", api_token)
        form.addRow("Workspace", workspace_root)
        form.addRow("Max. CAD-Dateien", cache_max_fcstd_files)
        form.addRow("Max. Projekte", cache_max_projects)
        form.addRow("Max. Revisionen je Projekt", cache_max_revisions_per_project)
        form.addRow("Slicer", slicer_kind)
        form.addRow("Slicer-Programm", slicer_executable)
        form.addRow("Zusätzliche Argumente", slicer_extra_args)
        layout.addLayout(form)

        buttons = self.QtWidgets.QDialogButtonBox(
            self.QtWidgets.QDialogButtonBox.Ok | self.QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.button(self.QtWidgets.QDialogButtonBox.Ok).setText("Speichern und verbinden")
        layout.addWidget(buttons)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)

        if dialog.exec_() != self.QtWidgets.QDialog.Accepted:
            self.set_status("Verbindungseinstellungen abgebrochen.")
            return

        self.server_url.setText(server_url.text().strip())
        self.api_token.setText(api_token.text().strip())
        self.workspace_root.setText(workspace_root.text().strip())
        self.cache_max_fcstd_files.setValue(cache_max_fcstd_files.value())
        self.cache_max_projects.setValue(cache_max_projects.value())
        self.cache_max_revisions_per_project.setValue(
            cache_max_revisions_per_project.value()
        )
        self.slicer_kind = slicer_kind.itemData(slicer_kind.currentIndex()) or "auto"
        self.slicer_executable = slicer_executable.text().strip()
        self.slicer_extra_args = slicer_extra_args.text().strip() or "[]"
        save_slicer_settings(
            self.slicer_kind,
            self.slicer_executable,
            self.slicer_extra_args,
        )
        self.refresh_projects()

    def selected_project(self):
        item = self.tree_ancestor(self.browser_tree.currentItem(), "project")
        return self.tree_item_payload(item)

    def select_project_by_id(self, project_id):
        for item in self.iter_tree_items():
            project = self.tree_item_payload(item)
            if self.tree_item_kind(item) == "project" and project and project.get("id") == project_id:
                self.browser_tree.setCurrentItem(item)
                item.setExpanded(True)
                return True
        return False

    def selected_part(self):
        item = self.tree_ancestor(self.browser_tree.currentItem(), "part")
        return self.tree_item_payload(item)

    def select_part_by_id(self, part_id):
        for item in self.iter_tree_items():
            part = self.tree_item_payload(item)
            if self.tree_item_kind(item) == "part" and part and part.get("id") == part_id:
                self.browser_tree.setCurrentItem(item)
                item.setExpanded(True)
                return True
        return False

    def selected_revision(self):
        item = self.browser_tree.currentItem()
        if self.tree_item_kind(item) != "revision":
            return None
        return self.tree_item_payload(item)

    def selected_annotation(self):
        items = self.annotations.selectedItems()
        if not items:
            return None
        annotation = items[0].data(self.QtCore.Qt.UserRole)
        return annotation if isinstance(annotation, dict) else None

    def select_revision_by_id(self, revision_id):
        for item in self.iter_tree_items():
            revision = self.tree_item_payload(item)
            if self.tree_item_kind(item) == "revision" and revision and revision.get("id") == revision_id:
                self.browser_tree.setCurrentItem(item)
                return True
        return False

    def selected_active_checkout(self):
        return self.selected_tree_checkout()

    def tree_role(self, offset):
        return int(self.QtCore.Qt.UserRole) + offset

    def tree_item_kind(self, item):
        return item.data(0, self.tree_role(1)) if item is not None else ""

    def tree_item_payload(self, item):
        if item is None:
            return None
        payload = item.data(0, int(self.QtCore.Qt.UserRole))
        return payload if isinstance(payload, dict) else None

    def tree_item_checkout(self, item):
        if item is None:
            return None
        checkout = item.data(0, self.tree_role(3))
        return checkout if isinstance(checkout, dict) else None

    def tree_item_checkout_error(self, item):
        if item is None:
            return ""
        return str(item.data(0, self.tree_role(4)) or "")

    def selected_tree_checkout(self):
        return self.tree_item_checkout(self.browser_tree.currentItem())

    def tree_ancestor(self, item, kind):
        while item is not None:
            if self.tree_item_kind(item) == kind:
                return item
            item = item.parent()
        return None

    def iter_tree_items(self):
        pending = [
            self.browser_tree.topLevelItem(index)
            for index in range(self.browser_tree.topLevelItemCount())
        ]
        while pending:
            item = pending.pop(0)
            yield item
            pending[0:0] = [item.child(index) for index in range(item.childCount())]

    def find_tree_item(self, kind, entity_id, parent=None):
        for item in self.iter_tree_items():
            if self.tree_item_kind(item) != kind:
                continue
            payload = self.tree_item_payload(item) or {}
            if payload.get("id") != entity_id:
                continue
            if parent is None or self.tree_ancestor(item, self.tree_item_kind(parent)) is parent:
                return item
        return None

    def tree_selection_key(self):
        item = self.browser_tree.currentItem()
        payload = self.tree_item_payload(item) or {}
        kind = self.tree_item_kind(item)
        entity_id = payload.get("id")
        if not kind or entity_id is None:
            return None
        project = self.tree_item_payload(self.tree_ancestor(item, "project")) or {}
        part = self.tree_item_payload(self.tree_ancestor(item, "part")) or {}
        return (kind, entity_id, project.get("id"), part.get("id"))

    def restore_tree_selection(self, key):
        if not key:
            return False
        kind, entity_id = key[:2]
        project_id = key[2] if len(key) > 2 else None
        part_id = key[3] if len(key) > 3 else None
        project_item = self.find_tree_item("project", project_id) if project_id else None
        if project_item is not None and kind in ("part", "revision"):
            self.load_project_parts(project_item)
        part_item = (
            self.find_tree_item("part", part_id, project_item)
            if part_id is not None
            else None
        )
        if part_item is not None and kind == "revision":
            self.load_part_revisions(part_item)
        parent = part_item if kind == "revision" else project_item if kind == "part" else None
        item = self.find_tree_item(kind, entity_id, parent)
        if item is None:
            return False
        if project_item is not None:
            project_item.setExpanded(True)
        if part_item is not None:
            part_item.setExpanded(True)
        self.browser_tree.setCurrentItem(item)
        self.browser_tree.scrollToItem(item)
        return True

    def add_tree_item(self, parent, kind, payload, label, lazy=False):
        item = self.QtWidgets.QTreeWidgetItem([label])
        item.setData(0, int(self.QtCore.Qt.UserRole), payload)
        item.setData(0, self.tree_role(1), kind)
        item.setData(0, self.tree_role(2), not lazy)
        item.setData(0, self.tree_role(5), label)
        if parent is None:
            self.browser_tree.addTopLevelItem(item)
        else:
            parent.addChild(item)
        if lazy:
            placeholder = self.QtWidgets.QTreeWidgetItem(["Wird beim Aufklappen geladen …"])
            placeholder.setData(0, self.tree_role(1), "placeholder")
            item.addChild(placeholder)
        return item

    def remove_checkout_error_items(self):
        for top_index in range(self.browser_tree.topLevelItemCount() - 1, -1, -1):
            top_item = self.browser_tree.topLevelItem(top_index)
            if self.tree_item_kind(top_item) == "checkout_error":
                self.browser_tree.takeTopLevelItem(top_index)
                continue
            for child_index in range(top_item.childCount() - 1, -1, -1):
                if self.tree_item_kind(top_item.child(child_index)) == "checkout_error":
                    top_item.takeChild(child_index)

    def reset_checkout_tree_markers(self):
        self.remove_checkout_error_items()
        for item in self.iter_tree_items():
            if self.tree_item_kind(item) != "revision":
                continue
            base_label = item.data(0, self.tree_role(5)) or revision_label(
                self.tree_item_payload(item) or {}
            )
            item.setText(0, base_label)
            item.setData(0, self.tree_role(3), None)
            item.setData(0, self.tree_role(4), "")
            font = item.font(0)
            font.setBold(False)
            font.setItalic(False)
            item.setFont(0, font)
            item.setForeground(0, self.QtGui.QBrush())
            item.setIcon(0, self.QtGui.QIcon())
            item.setToolTip(0, revision_workflow_hint(self.tree_item_payload(item) or {}))

    def checkout_icon(self, state):
        filename = {
            "local": "checkout-local.svg",
            "server": "checkout-server.svg",
            "error": "checkout-error.svg",
        }.get(state)
        if not filename:
            return self.QtGui.QIcon()
        return self.QtGui.QIcon(str(Path(__file__).resolve().parent / "icons" / filename))

    def mark_checkout_item(self, item, checkout, error=""):
        state = checkout_visual_state(
            checkout,
            self.active_checkout_id(),
            bool(error),
        )
        labels = {
            "local": "Checkout lokal",
            "server": "Checkout auf Server",
            "error": "Checkout fehlerhaft",
        }
        colors = {
            "local": "#18794e",
            "server": "#9a6700",
            "error": "#c62828",
        }
        base_label = item.data(0, self.tree_role(5)) or item.text(0)
        item.setText(0, f"{base_label} · {labels[state]}")
        item.setData(0, self.tree_role(3), checkout)
        item.setData(0, self.tree_role(4), error)
        font = item.font(0)
        font.setBold(state == "local")
        font.setItalic(False)
        item.setFont(0, font)
        item.setForeground(0, self.QtGui.QBrush(self.QtGui.QColor(colors[state])))
        item.setIcon(0, self.checkout_icon(state))
        tooltip = labels[state]
        if error:
            tooltip = f"{tooltip}: {error}"
        item.setToolTip(0, tooltip)

    def add_checkout_error_item(self, parent, checkout, message):
        checkout_id = checkout.get("id") if isinstance(checkout, dict) else "?"
        item = self.add_tree_item(
            parent,
            "checkout_error",
            checkout,
            f"Checkout {checkout_id} konnte nicht zugeordnet werden",
        )
        item.setData(0, self.tree_role(3), checkout)
        item.setData(0, self.tree_role(4), message)
        font = item.font(0)
        font.setBold(True)
        item.setFont(0, font)
        item.setForeground(0, self.QtGui.QBrush(self.QtGui.QColor("#c62828")))
        item.setIcon(0, self.checkout_icon("error"))
        item.setToolTip(0, message)
        if parent is not None:
            parent.setExpanded(True)
        return item

    def reveal_active_checkouts(self):
        self.reset_checkout_tree_markers()
        checkout_items = {}
        for checkout in self.server_checkouts:
            checkout_id = checkout.get("id")
            project = checkout.get("project") or {}
            part = checkout.get("part") or {}
            revision_id = active_checkout_revision_id(checkout)
            project_item = self.find_tree_item("project", project.get("id"))
            if project_item is None:
                checkout_items[checkout_id] = self.add_checkout_error_item(
                    None,
                    checkout,
                    "Projekt des aktiven Checkouts wurde nicht gefunden.",
                )
                continue
            self.load_project_parts(project_item)
            part_item = self.find_tree_item("part", part.get("id"), project_item)
            if part_item is None:
                checkout_items[checkout_id] = self.add_checkout_error_item(
                    project_item,
                    checkout,
                    "Teil des aktiven Checkouts wurde im Projekt nicht gefunden.",
                )
                continue
            self.load_part_revisions(part_item)
            revision_item = self.find_tree_item("revision", revision_id, part_item)
            if revision_item is None:
                checkout_items[checkout_id] = self.add_checkout_error_item(
                    project_item,
                    checkout,
                    "Revision des aktiven Checkouts wurde im Teil nicht gefunden.",
                )
                continue
            error = self.checkout_errors.get(checkout_id, "")
            self.mark_checkout_item(revision_item, checkout, error)
            project_item.setExpanded(True)
            part_item.setExpanded(True)
            checkout_items[checkout_id] = revision_item
        self.checkout_tree_items = checkout_items
        return checkout_items

    def clear_tree_children(self, item):
        while item is not None and item.childCount():
            item.takeChild(0)

    def browser_selection_changed(self):
        item = self.browser_tree.currentItem()
        kind = self.tree_item_kind(item)
        project = self.selected_project()
        part = self.selected_part()
        revision = self.selected_revision()

        self.clear_project_form()
        self.clear_part_form()
        self.clear_revision_context()
        if project:
            self.set_project_form(project)
        if part:
            self.set_part_form(part)
        if revision:
            self.set_revision_context(revision)
        self.update_context_actions()
        if kind == "project":
            self.set_status("Projekt ausgewählt. Zum Laden der Teile aufklappen.")
        elif kind == "part":
            self.set_status("Teil ausgewählt. Zum Laden der Revisionen aufklappen.")

    def browser_item_expanded(self, item):
        if bool(item.data(0, self.tree_role(2))):
            return
        kind = self.tree_item_kind(item)
        if kind == "project":
            self.load_project_parts(item)
        elif kind == "part":
            self.load_part_revisions(item)

    def browser_item_double_clicked(self, item, _column=0):
        kind = self.tree_item_kind(item)
        if kind == "checkout_error":
            self.refresh_projects()
            return
        if kind != "revision":
            return
        checkout = self.tree_item_checkout(item)
        state = checkout_visual_state(
            checkout,
            self.active_checkout_id(),
            bool(self.tree_item_checkout_error(item)),
        )
        if state == "local":
            self.open_active_checkout_root()
        elif state in ("server", "error"):
            self.reopen_selected_checkout()
        else:
            self.open_selected_revision()

    def show_browser_context_menu(self, position):
        item = self.browser_tree.itemAt(position)
        if item is None or self.tree_item_kind(item) == "placeholder":
            return
        self.browser_tree.setCurrentItem(item)
        self.update_context_actions()
        menu = self.QtWidgets.QMenu(self.browser_tree)
        if self.context_primary_label and callable(self.context_primary_callback):
            menu.addAction(self.context_primary_label, self.context_primary_callback)
        if self.context_more_actions:
            menu.addSeparator()
        for label, callback in self.context_more_actions:
            if label is None:
                menu.addSeparator()
            else:
                menu.addAction(label, callback)
        menu.exec_(self.browser_tree.viewport().mapToGlobal(position))

    def handle_revision_deep_link(self, deep_link):
        self.refresh_projects()
        project_item = next(
            (
                item
                for item in self.iter_tree_items()
                if self.tree_item_kind(item) == "project"
                and (self.tree_item_payload(item) or {}).get("id")
                == deep_link.project_id
            ),
            None,
        )
        if project_item is None:
            self.set_status("Projekt aus dem PLM-Link wurde nicht gefunden.")
            return False
        self.load_project_parts(project_item)
        part_item = next(
            (
                item
                for item in self.iter_tree_items()
                if self.tree_item_kind(item) == "part"
                and (self.tree_item_payload(item) or {}).get("id") == deep_link.part_id
                and self.tree_ancestor(item, "project") is project_item
            ),
            None,
        )
        if part_item is None:
            self.set_status("Teil aus dem PLM-Link wurde im Projekt nicht gefunden.")
            return False
        self.load_part_revisions(part_item)
        revision_item = next(
            (
                item
                for item in self.iter_tree_items()
                if self.tree_item_kind(item) == "revision"
                and (self.tree_item_payload(item) or {}).get("id")
                == deep_link.revision_id
                and self.tree_ancestor(item, "part") is part_item
            ),
            None,
        )
        if revision_item is None:
            self.set_status("Revision aus dem PLM-Link wurde im Teil nicht gefunden.")
            return False
        self.browser_tree.setCurrentItem(revision_item)
        self.browser_tree.scrollToItem(revision_item)

        if deep_link.action == "checkout":
            revision = self.selected_revision() or {}
            answer = self.QtWidgets.QMessageBox.question(
                self.widget,
                "Revision auschecken",
                f"{revision_label(revision)} wirklich zum Bearbeiten auschecken?",
                self.QtWidgets.QMessageBox.Yes | self.QtWidgets.QMessageBox.No,
                self.QtWidgets.QMessageBox.No,
            )
            if answer != self.QtWidgets.QMessageBox.Yes:
                self.set_status("Checkout aus PLM-Link abgebrochen.")
                return False
            self.checkout_selected_revision()
        elif deep_link.action == "slicer":
            self.open_selected_revision_in_slicer()
        else:
            self.open_selected_revision_readonly()
        return True

    def update_annotation_controls(self):
        annotation = self.selected_annotation()
        has_annotation = annotation is not None and annotation.get("id") is not None
        self.edit_annotation_button.setEnabled(has_annotation)
        self.delete_annotation_button.setEnabled(has_annotation)
        self.resolve_annotation_button.setEnabled(
            has_annotation and annotation.get("status") != "resolved"
        )
        self.reopen_annotation_button.setEnabled(
            has_annotation and annotation.get("status") == "resolved"
        )

    def update_checkout_controls(self):
        if self.server_checkouts:
            self.reveal_active_checkouts()
        self.update_context_actions()

    def mark_checkout_error(self, checkout_id, message):
        if checkout_id is None:
            return
        self.checkout_errors[checkout_id] = str(message)
        self.update_checkout_controls()

    def clear_checkout_error(self, checkout_id):
        if checkout_id is None:
            return
        self.checkout_errors.pop(checkout_id, None)

    def active_checkout_id(self):
        if not isinstance(self.active_checkout, dict):
            return None
        return self.active_checkout.get("id")

    def reset_active_checkout(self):
        self.active_checkout = None
        self.active_checkout_dir = None
        self.active_checkout_root_path = None
        self.checkout_document_names = []
        self.update_checkout_controls()

    def clear_revision_context(self):
        self.revision_overview.setPlainText("Keine Revision ausgewählt.")
        self.revision_notes.setPlainText("Keine Revision ausgewählt.")
        self.save_revision_notes_button.setEnabled(False)
        self.revert_revision_notes_button.setEnabled(False)
        self.technical_details.setPlainText("Keine Revision ausgewählt.")
        self.current_annotations = []
        self.annotations.clear()
        self.new_annotation_button.setEnabled(False)
        self.update_annotation_controls()

    def clear_project_form(self):
        self.project_code.setText("")
        self.project_name.setText("")
        self.project_status.setCurrentIndex(0)
        self.project_date.setText("")
        self.project_description.setPlainText("")
        self.save_project_button.setEnabled(False)

    def set_project_form(self, project):
        self.project_code.setText(project.get("code", "") or "")
        self.project_name.setText(project.get("name", "") or "")
        status = project.get("status") or "running"
        index = self.project_status.findData(status)
        self.project_status.setCurrentIndex(index if index >= 0 else 0)
        self.project_date.setText(project.get("project_date", "") or "")
        self.project_description.setPlainText(project.get("description", "") or "")
        self.save_project_button.setEnabled(project.get("id") is not None)

    def project_form_values(self):
        current_data = getattr(self.project_status, "currentData", None)
        status = current_data() if callable(current_data) else None
        if status is None:
            status = self.project_status.itemData(self.project_status.currentIndex())
        return {
            "code": self.project_code.text(),
            "name": self.project_name.text(),
            "status": status or "running",
            "project_date": self.project_date.text(),
            "description": self.project_description.toPlainText(),
        }

    def clear_part_form(self):
        self.part_number.setText("")
        self.part_name.setText("")
        self.part_category.setCurrentIndex(0)
        self.part_description.setPlainText("")
        self.part_material.setText("")
        self.part_supplier.setText("")
        self.part_tags.setText("")
        self.part_archived.setChecked(False)
        self.save_part_button.setEnabled(False)

    def set_part_form(self, part):
        self.part_number.setText(part.get("number", "") or "")
        self.part_name.setText(part.get("name", "") or "")
        category = part.get("category") or "part"
        index = self.part_category.findData(category)
        self.part_category.setCurrentIndex(index if index >= 0 else 0)
        self.part_description.setPlainText(part.get("description", "") or "")
        self.part_material.setText(part.get("material", "") or "")
        self.part_supplier.setText(part.get("supplier", "") or "")
        self.part_tags.setText(part.get("tags", "") or "")
        self.part_archived.setChecked(bool(part.get("is_archived", False)))
        self.save_part_button.setEnabled(part.get("id") is not None)

    def part_form_values(self, include_number=False):
        current_data = getattr(self.part_category, "currentData", None)
        category = current_data() if callable(current_data) else None
        if category is None:
            category = self.part_category.itemData(self.part_category.currentIndex())
        values = {
            "name": self.part_name.text(),
            "category": category or "part",
            "description": self.part_description.toPlainText(),
            "material": self.part_material.text(),
            "supplier": self.part_supplier.text(),
            "tags": self.part_tags.text(),
            "is_archived": self.part_archived.isChecked(),
        }
        if include_number:
            values["number"] = self.part_number.text()
        return values

    def set_revision_context(self, revision):
        self.revision_overview.setPlainText(revision_overview_text(revision))
        self.revision_notes.setPlainText(revision.get("notes") or "")
        self.save_revision_notes_button.setEnabled(revision.get("id") is not None)
        self.revert_revision_notes_button.setEnabled(revision.get("id") is not None)
        self.technical_details.setPlainText(revision_technical_text(revision))
        self.new_annotation_button.setEnabled(True)
        self.refresh_annotations(revision)

    def refresh_projects(self):
        from . import config

        server_url = self.server_url.text().strip()
        api_token = self.api_token.text().strip()
        workspace_root = self.workspace_root.text().strip()
        max_fcstd_files = self.cache_max_fcstd_files.value()
        max_projects = self.cache_max_projects.value()
        max_revisions_per_project = self.cache_max_revisions_per_project.value()

        config.set_server_url(server_url)
        config.set_api_token(api_token)
        config.set_workspace_root(workspace_root)
        config.set_cache_max_fcstd_files(max_fcstd_files)
        config.set_cache_max_projects(max_projects)
        config.set_cache_max_revisions_per_project(max_revisions_per_project)
        if not server_url or not api_token:
            self.set_status("Server und API-Token eintragen.")
            return

        self.set_status("Lade Projekte...")
        previous_selection = self.tree_selection_key()
        self.browser_tree.clear()
        self.server_checkouts = []
        self.clear_revision_context()
        self.clear_project_form()
        self.clear_part_form()

        try:
            client = self.client()
            projects = client.get_projects()
        except PLMError as exc:
            self.set_status(f"PLM-Fehler: {exc}")
            return
        except Exception as exc:
            self.set_status(f"Verbindung fehlgeschlagen: {exc}")
            return

        for project in projects:
            item = self.add_tree_item(
                None,
                "project",
                project,
                project_label(project),
                lazy=True,
            )
            item.setToolTip(0, "Aufklappen, um Teile und Baugruppen zu laden.")

        count = len(projects)
        checkout_count = self.refresh_active_checkouts(client)
        restored = self.restore_tree_selection(previous_selection)
        if not restored:
            target_checkout_id = self.active_checkout_id()
            if target_checkout_id not in self.checkout_tree_items and len(self.server_checkouts) == 1:
                target_checkout_id = self.server_checkouts[0].get("id")
            target_item = self.checkout_tree_items.get(target_checkout_id)
            if target_item is not None:
                self.browser_tree.setCurrentItem(target_item)
                self.browser_tree.scrollToItem(target_item)
        self.update_context_actions()
        suffix = "" if count == 1 else "e"
        message = f"{count} Projekt{suffix} geladen."
        if checkout_count is not None:
            message = f"{message} Aktive Checkouts: {checkout_count}."
        self.set_status(message)
        self.set_connected(server_url)

    def refresh_active_checkouts(self, client=None):
        try:
            checkouts = (client or self.client()).get_active_checkouts()
        except PLMError as exc:
            self.server_checkouts = []
            self.checkout_tree_items = {}
            self.reset_checkout_tree_markers()
            self.update_context_actions()
            self.set_status(f"PLM-Fehler beim Laden aktiver Checkouts: {exc}")
            return None
        except Exception as exc:
            self.server_checkouts = []
            self.checkout_tree_items = {}
            self.reset_checkout_tree_markers()
            self.update_context_actions()
            self.set_status(f"Aktive Checkouts konnten nicht geladen werden: {exc}")
            return None

        self.server_checkouts = list(checkouts or [])
        active_ids = {
            checkout.get("id")
            for checkout in self.server_checkouts
            if isinstance(checkout, dict) and checkout.get("id") is not None
        }
        self.checkout_errors = {
            checkout_id: message
            for checkout_id, message in self.checkout_errors.items()
            if checkout_id in active_ids
        }
        self.checkout_tree_items = self.reveal_active_checkouts()
        self.update_context_actions()
        return len(checkouts)

    def refresh_parts(self):
        project_item = self.tree_ancestor(self.browser_tree.currentItem(), "project")
        if project_item is None:
            return
        selection = self.tree_selection_key()
        self.load_project_parts(project_item, force=True)
        self.reveal_active_checkouts()
        self.restore_tree_selection(selection)
        self.update_context_actions()

    def load_project_parts(self, project_item, force=False):
        if project_item is None:
            return
        if bool(project_item.data(0, self.tree_role(2))) and not force:
            return

        project = self.tree_item_payload(project_item)
        project_id = project.get("id") if isinstance(project, dict) else None
        if project_id is None:
            self.set_status("Projekt hat keine ID.")
            return
        self.set_status("Lade Teile...")

        try:
            parts = self.client().get_parts(project_id)
        except PLMError as exc:
            self.set_status(f"PLM-Fehler: {exc}")
            return
        except Exception as exc:
            self.set_status(f"Verbindung fehlgeschlagen: {exc}")
            return

        self.clear_tree_children(project_item)
        for part in parts:
            item = self.add_tree_item(
                project_item,
                "part",
                part,
                part_label(part),
                lazy=True,
            )
            item.setToolTip(0, "Aufklappen, um Revisionen zu laden.")
        project_item.setData(0, self.tree_role(2), True)
        project_item.setExpanded(True)

        count = len(parts)
        suffix = "" if count == 1 else "e"
        self.set_status(f"{count} Teil{suffix} geladen.")

    def save_selected_project(self):
        project = self.selected_project()
        project_id = project.get("id") if isinstance(project, dict) else None
        if project_id is None:
            self.set_status("Kein Projekt ausgewählt.")
            return

        payload = project_edit_payload(self.project_form_values())
        try:
            updated_project = self.client().update_project(project_id, payload)
        except PLMError as exc:
            self.set_status(f"PLM-Fehler: {exc}")
            return
        except Exception as exc:
            self.set_status(f"Projekt konnte nicht gespeichert werden: {exc}")
            return

        item = self.tree_ancestor(self.browser_tree.currentItem(), "project")
        if item is not None:
            item.setData(0, int(self.QtCore.Qt.UserRole), updated_project)
            label = project_label(updated_project)
            item.setText(0, label)
            item.setData(0, self.tree_role(5), label)
        self.set_project_form(updated_project)
        self.set_status(f"Projekt gespeichert: {project_label(updated_project)}")

    def import_project_dialog(self):
        selected_project = self.selected_project()
        dialog = self.QtWidgets.QDialog(self.widget)
        dialog.setWindowTitle("Projekt importieren")
        layout = self.QtWidgets.QVBoxLayout(dialog)

        mode_group = self.QtWidgets.QButtonGroup(dialog)
        new_project_radio = self.QtWidgets.QRadioButton("Neues Projekt")
        existing_project_radio = self.QtWidgets.QRadioButton("Ausgewähltes Projekt")
        mode_group.addButton(new_project_radio)
        mode_group.addButton(existing_project_radio)
        mode_row = self.QtWidgets.QHBoxLayout()
        mode_row.addWidget(new_project_radio)
        mode_row.addWidget(existing_project_radio)
        layout.addLayout(mode_row)

        form = self.QtWidgets.QFormLayout()
        code = self.QtWidgets.QLineEdit()
        name = self.QtWidgets.QLineEdit()
        status = self.QtWidgets.QComboBox()
        status.addItem("Laufend", "running")
        status.addItem("Abgeschlossen", "completed")
        status.addItem("Idee", "idea")
        status.addItem("Wichtig", "important")
        status.addItem("Auftrag", "order")
        project_date = self.QtWidgets.QLineEdit()
        project_date.setPlaceholderText("YYYY-MM-DD")
        description = self.QtWidgets.QPlainTextEdit()
        description.setMaximumHeight(80)
        snapshot_name = self.QtWidgets.QLineEdit()
        snapshot_name.setText("Initial")
        source_dir = self.QtWidgets.QLineEdit()
        browse_button = self.QtWidgets.QPushButton("Ordner wählen")
        source_row = self.QtWidgets.QHBoxLayout()
        source_row.addWidget(source_dir)
        source_row.addWidget(browse_button)
        source_widget = self.QtWidgets.QWidget()
        source_widget.setLayout(source_row)

        try:
            from . import fcstd

            active_path = fcstd.active_document_path()
        except Exception:
            active_path = None
        if active_path:
            source_dir.setText(str(Path(active_path).parent))

        form.addRow("Code", code)
        form.addRow("Name", name)
        form.addRow("Status", status)
        form.addRow("Datum", project_date)
        form.addRow("Beschreibung", description)
        form.addRow("Projektstand", snapshot_name)
        form.addRow("Ordner", source_widget)
        layout.addLayout(form)

        buttons = self.QtWidgets.QDialogButtonBox(
            self.QtWidgets.QDialogButtonBox.Ok | self.QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.button(self.QtWidgets.QDialogButtonBox.Ok).setText("Importieren")
        layout.addWidget(buttons)

        def set_new_project_enabled(enabled):
            for widget in (code, name, status, project_date, description):
                widget.setEnabled(enabled)
            existing_project_radio.setEnabled(selected_project is not None)

        def update_mode():
            set_new_project_enabled(new_project_radio.isChecked())

        def browse():
            chosen = self.QtWidgets.QFileDialog.getExistingDirectory(
                dialog,
                "Projektordner wählen",
                source_dir.text().strip(),
            )
            if chosen:
                source_dir.setText(chosen)

        if selected_project is None:
            new_project_radio.setChecked(True)
        else:
            existing_project_radio.setChecked(True)
        update_mode()
        new_project_radio.toggled.connect(update_mode)
        browse_button.clicked.connect(browse)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)

        if dialog.exec_() != self.QtWidgets.QDialog.Accepted:
            self.set_status("Projektimport abgebrochen.")
            return

        source = source_dir.text().strip()
        if not source:
            self.set_status("Projektordner ist erforderlich.")
            return
        snapshot = snapshot_name.text().strip() or "Initial"

        try:
            with tempfile.TemporaryDirectory() as tmp:
                zip_path = Path(tmp) / "freecad-plm-import.zip"
                paths = build_project_import_zip(source, zip_path)
                client = self.client()
                if new_project_radio.isChecked():
                    project_data = project_edit_payload(
                        {
                            "code": code.text(),
                            "name": name.text(),
                            "status": status.itemData(status.currentIndex()) or "running",
                            "project_date": project_date.text(),
                            "description": description.toPlainText(),
                        }
                    )
                    if not project_data["code"] or not project_data["name"]:
                        self.set_status("Code und Name sind erforderlich.")
                        return
                    result = client.import_project(zip_path, project_data, snapshot)
                else:
                    project_id = selected_project.get("id") if isinstance(selected_project, dict) else None
                    if project_id is None:
                        self.set_status("Kein Projekt ausgewählt.")
                        return
                    result = client.import_project_snapshot(project_id, zip_path, snapshot)
        except PLMError as exc:
            self.set_status(f"PLM-Fehler: {exc}")
            return
        except Exception as exc:
            self.set_status(f"Projektimport fehlgeschlagen: {exc}")
            return

        imported_project = result.get("project") or {}
        imported_project_id = imported_project.get("id")
        followup_message = self.checkout_imported_project_dialog(result, source)
        self.refresh_projects()
        if imported_project_id is not None:
            self.select_project_by_id(imported_project_id)
        message = f"{project_import_result_text(result)} ZIP: {len(paths)} Datei(en)."
        if followup_message:
            message = f"{message} {followup_message}"
        self.set_status(message)

    def checkout_imported_project_dialog(self, import_result, source_dir):
        candidates = import_checkout_candidates(import_result)
        if not candidates:
            return import_checkout_followup_text(import_result)

        answer = self.QtWidgets.QMessageBox.question(
            self.widget,
            "Import abgeschlossen",
            "Soll eine importierte FCStd-Revision jetzt ausgecheckt werden?\n\n"
            "STEP- und STL-Revisionen werden nach der Auswahl schreibgeschützt geöffnet.",
            self.QtWidgets.QMessageBox.Yes | self.QtWidgets.QMessageBox.No,
            self.QtWidgets.QMessageBox.Yes,
        )
        if answer != self.QtWidgets.QMessageBox.Yes:
            return ""

        labels = [candidate["label"] for candidate in candidates]
        label, accepted = self.QtWidgets.QInputDialog.getItem(
            self.widget,
            "Root-Teil auschecken",
            "Importiertes Teil",
            labels,
            0,
            False,
        )
        if not accepted:
            return "Checkout nach Import abgebrochen."

        candidate = candidates[labels.index(label)]
        archive_answer = self.QtWidgets.QMessageBox.question(
            self.widget,
            "Importordner archivieren",
            "Soll der lokale Importordner nach erfolgreichem Checkout ins PLM-Archiv verschoben werden?",
            self.QtWidgets.QMessageBox.Yes | self.QtWidgets.QMessageBox.No,
            self.QtWidgets.QMessageBox.Yes,
        )
        archive_source = archive_answer == self.QtWidgets.QMessageBox.Yes

        project = import_result.get("project") or {}
        revision_id = candidate.get("revision_id")
        snapshot_id = candidate.get("snapshot_id")
        try:
            self.set_status("Starte Checkout des importierten Teils...")
            checkout_result = self.checkout_revision_to_workspace(
                project,
                revision_id,
                snapshot_id=snapshot_id,
            )
        except PLMError as exc:
            return f"Checkout nach Import fehlgeschlagen: {exc}"
        except Exception as exc:
            return f"Checkout nach Import fehlgeschlagen: {exc}"

        print_freecad_console(
            f"FreeCAD-PLM Checkout geöffnet: {checkout_result['root_path']} "
            f"({len(checkout_result['downloaded'])} Datei(en))."
        )
        message = f"Checkout geöffnet ({len(checkout_result['downloaded'])} Datei(en))."
        if archive_source:
            try:
                archived_path = archive_import_source_dir(
                    source_dir,
                    self.workspace_root.text().strip(),
                    self.server_url.text().strip(),
                    project.get("code") or f"project-{project.get('id')}",
                )
            except Exception as exc:
                message = f"{message} Importordner konnte nicht archiviert werden: {exc}"
            else:
                message = f"{message} Importordner archiviert: {archived_path}"
        return message

    def refresh_revisions(self):
        part_item = self.tree_ancestor(self.browser_tree.currentItem(), "part")
        if part_item is None:
            return
        selection = self.tree_selection_key()
        self.load_part_revisions(part_item, force=True)
        self.reveal_active_checkouts()
        self.restore_tree_selection(selection)
        self.update_context_actions()

    def load_part_revisions(self, part_item, force=False):
        if part_item is None:
            return
        if bool(part_item.data(0, self.tree_role(2))) and not force:
            return

        part = self.tree_item_payload(part_item)
        part_id = part.get("id") if isinstance(part, dict) else None
        if part_id is None:
            self.set_status("Teil hat keine ID.")
            return
        self.set_part_form(part)

        self.set_status("Lade Revisionen...")

        try:
            part_detail = self.client().get_part(part_id)
        except PLMError as exc:
            self.set_status(f"PLM-Fehler: {exc}")
            return
        except Exception as exc:
            self.set_status(f"Verbindung fehlgeschlagen: {exc}")
            return

        revisions = revisions_from_part_detail(part_detail)
        detail_part = part_detail.get("part") if isinstance(part_detail, dict) else None
        if isinstance(detail_part, dict):
            part_item.setData(0, int(self.QtCore.Qt.UserRole), detail_part)
            label = part_label(detail_part)
            part_item.setText(0, label)
            part_item.setData(0, self.tree_role(5), label)
            if self.tree_ancestor(self.browser_tree.currentItem(), "part") is part_item:
                self.set_part_form(detail_part)
        self.clear_tree_children(part_item)
        for revision in revisions:
            item = self.add_tree_item(
                part_item,
                "revision",
                revision,
                revision_label(revision),
            )
            item.setToolTip(0, revision_workflow_hint(revision))
        part_item.setData(0, self.tree_role(2), True)
        part_item.setExpanded(True)

        count = len(revisions)
        suffix = "" if count == 1 else "en"
        self.set_status(f"{count} Revision{suffix} geladen.")

    def create_part_dialog(self):
        from . import fcstd

        project = self.selected_project()
        project_id = project.get("id") if isinstance(project, dict) else None
        if project_id is None:
            self.set_status("Kein Projekt ausgewählt.")
            return

        active_checkout_id = self.active_checkout_id()
        active_project = (
            self.active_checkout.get("project")
            if isinstance(self.active_checkout, dict)
            and isinstance(self.active_checkout.get("project"), dict)
            else {}
        )
        active_project_id = active_project.get("id")
        if active_project_id is not None and active_project_id != project_id:
            self.select_project_by_id(active_project_id)
            project = self.selected_project() or active_project
            project_id = project.get("id")
        if active_checkout_id is not None and self.active_checkout_dir is None:
            self.set_status(
                "Bitte den aktiven Checkout zuerst öffnen, bevor ein neues Teil hinzugefügt wird."
            )
            return

        dialog = self.QtWidgets.QDialog(self.widget)
        dialog.setWindowTitle("Neues FreeCAD-Teil")
        layout = self.QtWidgets.QVBoxLayout(dialog)
        intro = self.QtWidgets.QLabel(
            (
                "Das PLM legt Teil und Revision R0001 an und fügt die neue FCStd-Datei "
                "direkt zum aktiven Checkout hinzu."
                if active_checkout_id is not None
                else (
                    "Das PLM legt Teil und Revision R0001 an und öffnet die "
                    "neue FCStd-Datei direkt als Checkout."
                )
            )
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = self.QtWidgets.QFormLayout()
        name_input = self.QtWidgets.QLineEdit()
        name_input.setPlaceholderText("z. B. Klebeschale")
        number_input = self.QtWidgets.QLineEdit()
        number_input.setPlaceholderText("automatisch")
        category_input = self.QtWidgets.QComboBox()
        category_input.addItem("Teil", "part")
        category_input.addItem("Baugruppe", "assembly")
        filename_label = self.QtWidgets.QLabel(new_part_filename(""))
        form.addRow("Name", name_input)
        form.addRow("Teilenummer", number_input)
        form.addRow("Typ", category_input)
        form.addRow("Neue Datei", filename_label)
        layout.addLayout(form)

        buttons = self.QtWidgets.QDialogButtonBox(
            self.QtWidgets.QDialogButtonBox.Ok | self.QtWidgets.QDialogButtonBox.Cancel
        )
        ok_button = buttons.button(self.QtWidgets.QDialogButtonBox.Ok)
        ok_button.setText("Anlegen und öffnen")
        ok_button.setEnabled(False)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        def update_name(value):
            filename_label.setText(new_part_filename(value))
            ok_button.setEnabled(bool(value.strip()))

        name_input.textChanged.connect(update_name)
        name_input.setFocus()

        if dialog.exec_() != self.QtWidgets.QDialog.Accepted:
            self.set_status("Teilanlage abgebrochen.")
            return

        name = name_input.text().strip()
        if not name:
            self.set_status("Name ist erforderlich.")
            return

        category = category_input.itemData(category_input.currentIndex()) or "part"
        filename = new_part_filename(name)
        payload = {
            "number": number_input.text().strip(),
            "name": name,
            "category": category,
        }
        try:
            with tempfile.TemporaryDirectory() as tmp:
                fcstd_path = fcstd.create_empty_document(Path(tmp) / filename, name)
                response = self.client().create_fcstd_part(
                    project_id,
                    payload,
                    fcstd_path,
                    checkout_id=active_checkout_id,
                    workspace_hint=self.workspace_root.text().strip(),
                )
        except PLMError as exc:
            self.set_status(f"PLM-Fehler: {exc}")
            return
        except Exception as exc:
            self.set_status(f"Teil konnte nicht angelegt werden: {exc}")
            return

        part = response.get("part") or {}
        revision = response.get("revision") or {}
        try:
            if active_checkout_id is not None:
                open_result = self.add_checkout_response_to_workspace(response)
                result_text = f"zum Checkout hinzugefügt: {open_result['added_path']}"
            else:
                open_result = self.open_checkout_response_to_workspace(project, response)
                result_text = f"als Checkout geöffnet: {open_result['root_path'].name}"
        except Exception as exc:
            self.refresh_parts()
            self.refresh_active_checkouts()
            self.set_status(
                f"{part_label(part)} und R0001 wurden angelegt, konnten lokal "
                f"aber nicht geöffnet werden: {exc}"
            )
            return

        self.refresh_parts()
        if part.get("id") is not None:
            self.select_part_by_id(part["id"])
        if revision.get("id") is not None:
            self.select_revision_by_id(revision["id"])
        self.set_status(
            f"{part_label(part)} mit R0001 angelegt und {result_text}."
        )

    def add_local_fcstd_part_dialog(self):
        from . import fcstd

        project = self.selected_project()
        project_id = project.get("id") if isinstance(project, dict) else None
        active_checkout_id = self.active_checkout_id()
        active_project = (
            self.active_checkout.get("project")
            if isinstance(self.active_checkout, dict)
            and isinstance(self.active_checkout.get("project"), dict)
            else {}
        )
        active_project_id = active_project.get("id")
        if active_project_id is not None and active_project_id != project_id:
            self.select_project_by_id(active_project_id)
            project = self.selected_project() or active_project
            project_id = project.get("id")
        if project_id is None:
            self.set_status("Kein Projekt ausgewählt.")
            return
        if active_checkout_id is not None and self.active_checkout_dir is None:
            self.set_status(
                "Bitte den aktiven Checkout zuerst öffnen, bevor eine lokale Datei hinzugefügt wird."
            )
            return

        source_name, _selected_filter = self.QtWidgets.QFileDialog.getOpenFileName(
            self.widget,
            "Lokale FreeCAD-Datei zum PLM hinzufügen",
            str(Path.home()),
            "FreeCAD-Dateien (*.FCStd *.fcstd)",
        )
        if not source_name:
            self.set_status("Hinzufügen abgebrochen.")
            return
        source_path = Path(source_name)
        if not source_path.is_file() or source_path.suffix.lower() != ".fcstd":
            self.set_status("Bitte eine vorhandene FCStd-Datei auswählen.")
            return

        open_names = fcstd.document_names_for_path(source_path)
        modified_names = fcstd.modified_document_names(open_names)
        if modified_names:
            self.set_status("Bitte die lokale FCStd-Datei vor dem Hinzufügen speichern.")
            return

        dialog = self.QtWidgets.QDialog(self.widget)
        dialog.setWindowTitle("Lokale FCStd als neues Teil hinzufügen")
        layout = self.QtWidgets.QVBoxLayout(dialog)
        intro = self.QtWidgets.QLabel(
            "Das PLM legt aus der vorhandenen Datei ein neues Teil mit Revision R0001 an"
            + (
                " und nimmt es direkt in den geöffneten Checkout auf."
                if active_checkout_id is not None
                else " und öffnet dafür einen eigenen Checkout."
            )
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        form = self.QtWidgets.QFormLayout()
        name_input = self.QtWidgets.QLineEdit(source_path.stem)
        number_input = self.QtWidgets.QLineEdit()
        number_input.setPlaceholderText("automatisch")
        category_input = self.QtWidgets.QComboBox()
        category_input.addItem("Teil", "part")
        category_input.addItem("Baugruppe", "assembly")
        source_label = self.QtWidgets.QLabel(str(source_path))
        source_label.setWordWrap(True)
        form.addRow("Datei", source_label)
        form.addRow("Name", name_input)
        form.addRow("Teilenummer", number_input)
        form.addRow("Typ", category_input)
        layout.addLayout(form)
        buttons = self.QtWidgets.QDialogButtonBox(
            self.QtWidgets.QDialogButtonBox.Ok | self.QtWidgets.QDialogButtonBox.Cancel
        )
        ok_button = buttons.button(self.QtWidgets.QDialogButtonBox.Ok)
        ok_button.setText("Hinzufügen und öffnen")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec_() != self.QtWidgets.QDialog.Accepted:
            self.set_status("Hinzufügen abgebrochen.")
            return

        name = name_input.text().strip()
        if not name:
            self.set_status("Name ist erforderlich.")
            return
        _closed, failed = fcstd.close_documents(open_names)
        if failed:
            self.set_status(
                f"Lokale Datei konnte nicht geschlossen werden: {', '.join(failed)}"
            )
            return
        payload = {
            "number": number_input.text().strip(),
            "name": name,
            "category": category_input.itemData(category_input.currentIndex()) or "part",
            "source": "addon_local_fcstd",
        }
        try:
            response = self.client().create_fcstd_part(
                project_id,
                payload,
                source_path,
                checkout_id=active_checkout_id,
                workspace_hint=self.workspace_root.text().strip(),
            )
            if active_checkout_id is not None:
                open_result = self.add_checkout_response_to_workspace(response)
                result_text = f"zum Checkout hinzugefügt: {open_result['added_path']}"
            else:
                open_result = self.open_checkout_response_to_workspace(project, response)
                result_text = f"als Checkout geöffnet: {open_result['root_path'].name}"
        except PLMError as exc:
            self.set_status(f"PLM-Fehler: {exc}")
            return
        except Exception as exc:
            self.set_status(f"Lokale FCStd konnte nicht hinzugefügt werden: {exc}")
            return

        part = response.get("part") or {}
        revision = response.get("revision") or {}
        self.refresh_parts()
        if part.get("id") is not None:
            self.select_part_by_id(part["id"])
        if revision.get("id") is not None:
            self.select_revision_by_id(revision["id"])
        self.set_status(f"{part_label(part)} mit R0001 angelegt und {result_text}.")

    def add_selected_revision_to_print_project(self):
        from .slicer import export_revision_manifest_to_stl
        from .workspace import server_slug

        project = self.selected_project()
        part = self.selected_part()
        revision = self.selected_revision()
        if not project or not part or not revision or revision.get("id") is None:
            self.set_status("Projekt, Teil und Revision auswählen.")
            return
        try:
            candidates = [
                item
                for item in self.client().get_print_projects()
                if item.get("project_id") == project.get("id")
                and not any(
                    source.get("revision_id") == revision["id"]
                    for source in item.get("sources") or []
                )
            ]
        except Exception as exc:
            self.set_status(f"Druckprojekte konnten nicht geladen werden: {exc}")
            return
        if not candidates:
            self.set_status("Kein passendes Druckprojekt ohne diese Revision gefunden.")
            return
        labels = [f"{item.get('code', '')} · {item.get('name', '')}" for item in candidates]
        selected_label, accepted = self.QtWidgets.QInputDialog.getItem(
            self.widget,
            "Revision zum Druckprojekt hinzufügen",
            "Druckprojekt",
            labels,
            0,
            False,
        )
        if not accepted:
            self.set_status("Hinzufügen zum Druckprojekt abgebrochen.")
            return
        print_project = candidates[labels.index(selected_label)]
        safe_stem = "_".join(
            "".join(char if char.isalnum() or char in "-_." else "_" for char in str(value))
            for value in (
                part.get("number") or part.get("name") or "Teil",
                revision.get("revision_code") or f"revision-{revision['id']}",
            )
        )
        export_dir = (
            Path(self.workspace_root.text().strip()).expanduser()
            / server_slug(self.server_url.text().strip())
            / str(project.get("code") or f"project-{project.get('id')}")
            / "slicer-projects"
            / f"print-project-{print_project['id']}"
            / "source-additions"
        )
        export_path = export_dir / f"{safe_stem}.stl"
        try:
            self.set_status("Erzeuge STL-Übergabedatei für das Druckprojekt...")
            export_revision_manifest_to_stl(
                self.client(),
                revision["id"],
                export_dir / "revision-source",
                export_path,
            )
            self.client().add_print_project_revision_source(
                print_project["id"],
                revision["id"],
                f"{part.get('number', '')} {revision.get('revision_code', '')}".strip(),
            )
        except Exception as exc:
            self.set_status(f"Revision konnte nicht zum Druckprojekt hinzugefügt werden: {exc}")
            return

        self.QtGui.QDesktopServices.openUrl(
            self.QtCore.QUrl.fromLocalFile(str(export_dir))
        )
        self.QtWidgets.QMessageBox.information(
            self.widget,
            "Revision zum Druckprojekt hinzugefügt",
            "Die PLM-Revision ist jetzt als Quelle dokumentiert. Ziehe die erzeugte "
            f"Datei in das geöffnete Slicerprojekt und ordne sie auf der gewünschten Platte an:\n\n{export_path}",
        )
        self.set_status(
            f"Revision als Druckprojekt-Quelle hinzugefügt; STL bereit: {export_path}"
        )

    def save_selected_part(self):
        part = self.selected_part()
        part_id = part.get("id") if isinstance(part, dict) else None
        if part_id is None:
            self.set_status("Kein Teil ausgewählt.")
            return

        payload = part_edit_payload(self.part_form_values())
        try:
            updated_part = self.client().update_part(part_id, payload)
        except PLMError as exc:
            self.set_status(f"PLM-Fehler: {exc}")
            return
        except Exception as exc:
            self.set_status(f"Teil konnte nicht gespeichert werden: {exc}")
            return

        item = self.tree_ancestor(self.browser_tree.currentItem(), "part")
        if item is not None:
            item.setData(0, int(self.QtCore.Qt.UserRole), updated_part)
            label = part_label(updated_part)
            item.setText(0, label)
            item.setData(0, self.tree_role(5), label)
        self.set_part_form(updated_part)
        self.set_status(f"Stammdaten gespeichert: {part_label(updated_part)}")

    def show_project_dialog(self):
        project = self.selected_project()
        project_id = project.get("id") if isinstance(project, dict) else None
        if project_id is None:
            self.set_status("Kein Projekt ausgewählt.")
            return

        dialog = self.QtWidgets.QDialog(self.widget)
        dialog.setWindowTitle("Projekt bearbeiten")
        layout = self.QtWidgets.QVBoxLayout(dialog)
        form = self.QtWidgets.QFormLayout()
        code = self.QtWidgets.QLineEdit(project.get("code", "") or "")
        name = self.QtWidgets.QLineEdit(project.get("name", "") or "")
        status = self.QtWidgets.QComboBox()
        for label, value in (
            ("Laufend", "running"),
            ("Abgeschlossen", "completed"),
            ("Idee", "idea"),
            ("Wichtig", "important"),
            ("Auftrag", "order"),
        ):
            status.addItem(label, value)
        status_value = project.get("status") or "running"
        status_index = status.findData(status_value)
        status.setCurrentIndex(status_index if status_index >= 0 else 0)
        project_date = self.QtWidgets.QLineEdit(project.get("project_date", "") or "")
        project_date.setPlaceholderText("YYYY-MM-DD")
        description = self.QtWidgets.QPlainTextEdit(project.get("description", "") or "")
        description.setMaximumHeight(120)
        form.addRow("Code", code)
        form.addRow("Name", name)
        form.addRow("Status", status)
        form.addRow("Datum", project_date)
        form.addRow("Beschreibung", description)
        layout.addLayout(form)
        buttons = self.QtWidgets.QDialogButtonBox(
            self.QtWidgets.QDialogButtonBox.Ok | self.QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.button(self.QtWidgets.QDialogButtonBox.Ok).setText("Speichern")
        layout.addWidget(buttons)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        if dialog.exec_() != self.QtWidgets.QDialog.Accepted:
            self.set_status("Projektbearbeitung abgebrochen.")
            return

        payload = project_edit_payload(
            {
                "code": code.text(),
                "name": name.text(),
                "status": status.itemData(status.currentIndex()) or "running",
                "project_date": project_date.text(),
                "description": description.toPlainText(),
            }
        )
        try:
            updated_project = self.client().update_project(project_id, payload)
        except PLMError as exc:
            self.set_status(f"PLM-Fehler: {exc}")
            return
        except Exception as exc:
            self.set_status(f"Projekt konnte nicht gespeichert werden: {exc}")
            return
        item = self.tree_ancestor(self.browser_tree.currentItem(), "project")
        if item is not None:
            item.setData(0, int(self.QtCore.Qt.UserRole), updated_project)
            label = project_label(updated_project)
            item.setText(0, label)
            item.setData(0, self.tree_role(5), label)
        self.set_project_form(updated_project)
        self.set_status(f"Projekt gespeichert: {project_label(updated_project)}")

    def show_part_dialog(self):
        part = self.selected_part()
        part_id = part.get("id") if isinstance(part, dict) else None
        if part_id is None:
            self.set_status("Kein Teil ausgewählt.")
            return

        dialog = self.QtWidgets.QDialog(self.widget)
        dialog.setWindowTitle("Teil bearbeiten")
        layout = self.QtWidgets.QVBoxLayout(dialog)
        form = self.QtWidgets.QFormLayout()
        number = self.QtWidgets.QLineEdit(part.get("number", "") or "")
        number.setReadOnly(True)
        name = self.QtWidgets.QLineEdit(part.get("name", "") or "")
        category = self.QtWidgets.QComboBox()
        category.addItem("Teil", "part")
        category.addItem("Baugruppe", "assembly")
        category_index = category.findData(part.get("category") or "part")
        category.setCurrentIndex(category_index if category_index >= 0 else 0)
        description = self.QtWidgets.QPlainTextEdit(part.get("description", "") or "")
        description.setMaximumHeight(100)
        material = self.QtWidgets.QLineEdit(part.get("material", "") or "")
        supplier = self.QtWidgets.QLineEdit(part.get("supplier", "") or "")
        tags = self.QtWidgets.QLineEdit(part.get("tags", "") or "")
        archived = self.QtWidgets.QCheckBox("Archiviert")
        archived.setChecked(bool(part.get("is_archived", False)))
        form.addRow("Nummer", number)
        form.addRow("Name", name)
        form.addRow("Kategorie", category)
        form.addRow("Beschreibung", description)
        form.addRow("Material", material)
        form.addRow("Lieferant", supplier)
        form.addRow("Tags", tags)
        form.addRow("", archived)
        layout.addLayout(form)
        buttons = self.QtWidgets.QDialogButtonBox(
            self.QtWidgets.QDialogButtonBox.Ok | self.QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.button(self.QtWidgets.QDialogButtonBox.Ok).setText("Speichern")
        layout.addWidget(buttons)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        if dialog.exec_() != self.QtWidgets.QDialog.Accepted:
            self.set_status("Teilbearbeitung abgebrochen.")
            return

        payload = part_edit_payload(
            {
                "name": name.text(),
                "category": category.itemData(category.currentIndex()) or "part",
                "description": description.toPlainText(),
                "material": material.text(),
                "supplier": supplier.text(),
                "tags": tags.text(),
                "is_archived": archived.isChecked(),
            }
        )
        try:
            updated_part = self.client().update_part(part_id, payload)
        except PLMError as exc:
            self.set_status(f"PLM-Fehler: {exc}")
            return
        except Exception as exc:
            self.set_status(f"Teil konnte nicht gespeichert werden: {exc}")
            return
        item = self.tree_ancestor(self.browser_tree.currentItem(), "part")
        if item is not None:
            item.setData(0, int(self.QtCore.Qt.UserRole), updated_part)
            label = part_label(updated_part)
            item.setText(0, label)
            item.setData(0, self.tree_role(5), label)
        self.set_part_form(updated_part)
        self.set_status(f"Stammdaten gespeichert: {part_label(updated_part)}")

    def show_revision_details_dialog(self):
        revision = self.selected_revision()
        if not isinstance(revision, dict):
            self.set_status("Keine Revision ausgewählt.")
            return
        dialog = self.QtWidgets.QDialog(self.widget)
        dialog.setWindowTitle("Revisionsdetails")
        layout = self.QtWidgets.QVBoxLayout(dialog)
        tabs = self.QtWidgets.QTabWidget()
        overview = self.QtWidgets.QPlainTextEdit(revision_overview_text(revision))
        overview.setReadOnly(True)
        technical = self.QtWidgets.QPlainTextEdit(revision_technical_text(revision))
        technical.setReadOnly(True)
        tabs.addTab(overview, "Details")
        tabs.addTab(technical, "Technik")
        layout.addWidget(tabs)
        buttons = self.QtWidgets.QDialogButtonBox(self.QtWidgets.QDialogButtonBox.Close)
        layout.addWidget(buttons)
        buttons.rejected.connect(dialog.reject)
        dialog.exec_()

    def show_revision_notes_dialog(self):
        revision = self.selected_revision()
        revision_id = revision.get("id") if isinstance(revision, dict) else None
        if revision_id is None:
            self.set_status("Keine Revision ausgewählt.")
            return
        dialog = self.QtWidgets.QDialog(self.widget)
        dialog.setWindowTitle("Revisionsnotizen")
        layout = self.QtWidgets.QVBoxLayout(dialog)
        notes = self.QtWidgets.QPlainTextEdit(revision.get("notes") or "")
        notes.setMinimumHeight(160)
        layout.addWidget(notes)
        buttons = self.QtWidgets.QDialogButtonBox(
            self.QtWidgets.QDialogButtonBox.Save | self.QtWidgets.QDialogButtonBox.Cancel
        )
        layout.addWidget(buttons)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        if dialog.exec_() != self.QtWidgets.QDialog.Accepted:
            self.set_status("Notizenbearbeitung abgebrochen.")
            return
        payload = revision_notes_payload(notes.toPlainText())
        try:
            updated_revision = self.client().update_revision_notes(revision_id, payload["notes"])
        except PLMError as exc:
            self.set_status(f"PLM-Fehler: {exc}")
            return
        except Exception as exc:
            self.set_status(f"Notizen konnten nicht gespeichert werden: {exc}")
            return
        item = self.browser_tree.currentItem()
        if self.tree_item_kind(item) == "revision":
            item.setData(0, int(self.QtCore.Qt.UserRole), updated_revision)
            label = revision_label(updated_revision)
            item.setText(0, label)
            item.setData(0, self.tree_role(5), label)
            self.update_checkout_controls()
        self.set_revision_context(updated_revision)
        self.set_status("Revisionsnotizen gespeichert.")

    def show_annotations_dialog(self):
        revision = self.selected_revision()
        if not isinstance(revision, dict):
            self.set_status("Keine Revision ausgewählt.")
            return
        dialog = self.QtWidgets.QDialog(self.widget)
        dialog.setWindowTitle("Anmerkungen")
        layout = self.QtWidgets.QVBoxLayout(dialog)
        filter_box = self.QtWidgets.QComboBox()
        for label, value in (
            ("Alle", "all"),
            ("Offen", "open"),
            ("Erledigt", "resolved"),
            ("Nur diese Revision", "revision"),
            ("Teil allgemein", "part"),
        ):
            filter_box.addItem(label, value)
        annotation_list = self.QtWidgets.QListWidget()
        layout.addWidget(filter_box)
        layout.addWidget(annotation_list)
        action_row = self.QtWidgets.QHBoxLayout()
        new_button = self.QtWidgets.QPushButton("Neu")
        edit_button = self.QtWidgets.QPushButton("Bearbeiten")
        resolve_button = self.QtWidgets.QPushButton("Erledigt")
        reopen_button = self.QtWidgets.QPushButton("Wieder öffnen")
        delete_button = self.QtWidgets.QPushButton("Löschen")
        for button in (new_button, edit_button, resolve_button, reopen_button, delete_button):
            action_row.addWidget(button)
        layout.addLayout(action_row)
        close_buttons = self.QtWidgets.QDialogButtonBox(self.QtWidgets.QDialogButtonBox.Close)
        layout.addWidget(close_buttons)

        def selected_dialog_annotation():
            items = annotation_list.selectedItems()
            if not items:
                return None
            annotation = items[0].data(self.QtCore.Qt.UserRole)
            return annotation if isinstance(annotation, dict) else None

        def refill():
            annotation_list.clear()
            filter_key = filter_box.itemData(filter_box.currentIndex()) or "all"
            revision_id = revision.get("id")
            annotations = [
                annotation
                for annotation in self.current_annotations
                if annotation_matches_filter(annotation, filter_key, revision_id)
            ]
            for annotation in annotations:
                item = self.QtWidgets.QListWidgetItem(annotation_label(annotation))
                item.setData(self.QtCore.Qt.UserRole, annotation)
                annotation_list.addItem(item)

        def reload_annotations():
            self.refresh_annotations(revision)
            refill()

        def create():
            self.create_annotation_for_current_revision()
            reload_annotations()

        def edit():
            annotation = selected_dialog_annotation()
            if not annotation:
                self.set_status("Keine Anmerkung ausgewählt.")
                return
            self._edit_annotation(annotation)
            reload_annotations()

        def set_status(status):
            annotation = selected_dialog_annotation()
            if not annotation:
                self.set_status("Keine Anmerkung ausgewählt.")
                return
            self._update_annotation(annotation, annotation_update_payload(status=status))
            reload_annotations()

        def delete():
            annotation = selected_dialog_annotation()
            if not annotation:
                self.set_status("Keine Anmerkung ausgewählt.")
                return
            self._delete_annotation(annotation)
            reload_annotations()

        reload_annotations()
        filter_box.currentIndexChanged.connect(refill)
        new_button.clicked.connect(create)
        edit_button.clicked.connect(edit)
        resolve_button.clicked.connect(lambda: set_status("resolved"))
        reopen_button.clicked.connect(lambda: set_status("open"))
        delete_button.clicked.connect(delete)
        close_buttons.rejected.connect(dialog.reject)
        dialog.exec_()

    def show_revision_details(self):
        revision = self.selected_revision()
        if not isinstance(revision, dict):
            self.clear_revision_context()
            return

        self.set_revision_context(revision)

    def save_revision_notes(self):
        revision = self.selected_revision()
        revision_id = revision.get("id") if isinstance(revision, dict) else None
        if revision_id is None:
            self.set_status("Keine Revision ausgewählt.")
            return

        payload = revision_notes_payload(self.revision_notes.toPlainText())
        try:
            updated_revision = self.client().update_revision_notes(revision_id, payload["notes"])
        except PLMError as exc:
            self.set_status(f"PLM-Fehler: {exc}")
            return
        except Exception as exc:
            self.set_status(f"Notizen konnten nicht gespeichert werden: {exc}")
            return

        item = self.browser_tree.currentItem()
        if self.tree_item_kind(item) == "revision":
            item.setData(0, int(self.QtCore.Qt.UserRole), updated_revision)
            label = revision_label(updated_revision)
            item.setText(0, label)
            item.setData(0, self.tree_role(5), label)
            self.update_checkout_controls()
        self.set_revision_context(updated_revision)
        self.set_status("Revisionsnotizen gespeichert.")

    def revert_revision_notes(self):
        revision = self.selected_revision()
        if not isinstance(revision, dict):
            self.set_status("Keine Revision ausgewählt.")
            return
        self.revision_notes.setPlainText(revision.get("notes") or "")
        self.set_status("Revisionsnotizen zurückgesetzt.")

    def refresh_annotations(self, revision):
        self.current_annotations = []
        self.annotations.clear()
        self.update_annotation_controls()
        part = self.selected_part()
        part_id = part.get("id") if isinstance(part, dict) else None
        if part_id is None:
            return

        try:
            annotations = annotations_for_revision(
                self.client().get_annotations(part_id),
                revision.get("id"),
            )
        except PLMError as exc:
            self.annotations.addItem(f"PLM-Fehler: {exc}")
            return
        except Exception as exc:
            self.annotations.addItem(f"Anmerkungen konnten nicht geladen werden: {exc}")
            return

        self.current_annotations = annotations
        self.apply_current_annotation_filter()

    def apply_current_annotation_filter(self, *_args):
        self.annotations.clear()
        revision = self.selected_revision()
        revision_id = revision.get("id") if isinstance(revision, dict) else None
        current_data = getattr(self.annotation_filter, "currentData", None)
        filter_key = current_data() if callable(current_data) else None
        if filter_key is None:
            filter_key = self.annotation_filter.itemData(self.annotation_filter.currentIndex())

        annotations = [
            annotation
            for annotation in self.current_annotations
            if annotation_matches_filter(annotation, filter_key or "all", revision_id)
        ]

        if not annotations:
            message = "Keine Anmerkungen vorhanden."
            if self.current_annotations:
                message = "Keine Anmerkungen für diesen Filter."
            self.annotations.addItem(message)
            self.update_annotation_controls()
            return

        for annotation in annotations:
            item = self.QtWidgets.QListWidgetItem(annotation_label(annotation))
            item.setData(self.QtCore.Qt.UserRole, annotation)
            self.annotations.addItem(item)
        self.update_annotation_controls()

    def create_annotation_for_current_revision(self, object_name="", subelement=""):
        part = self.selected_part()
        revision = self.selected_revision()
        part_id = part.get("id") if isinstance(part, dict) else None
        revision_id = revision.get("id") if isinstance(revision, dict) else None
        if part_id is None or revision_id is None:
            self.set_status("Teil und Revision auswählen.")
            return

        text, accepted = self.QtWidgets.QInputDialog.getMultiLineText(
            self.widget,
            "Anmerkung",
            "Text",
            "",
        )
        if not accepted:
            self.set_status("Anmerkung abgebrochen.")
            return

        text = text.strip()
        if not text:
            self.set_status("Anmerkungstext ist erforderlich.")
            return

        payload = annotation_create_payload(revision_id, text, object_name, subelement)
        try:
            annotation = self.client().create_annotation(part_id, payload)
        except PLMError as exc:
            self.set_status(f"PLM-Fehler: {exc}")
            return
        except Exception as exc:
            self.set_status(f"Anmerkung konnte nicht gespeichert werden: {exc}")
            return

        self.refresh_annotations(revision)
        self.set_status(f"Anmerkung angelegt: {annotation_label(annotation)}")

    def edit_selected_annotation(self):
        annotation = self.selected_annotation()
        self._edit_annotation(annotation)

    def _edit_annotation(self, annotation):
        annotation_id = annotation.get("id") if isinstance(annotation, dict) else None
        if annotation_id is None:
            self.set_status("Keine Anmerkung ausgewählt.")
            return

        text, accepted = self.QtWidgets.QInputDialog.getMultiLineText(
            self.widget,
            "Anmerkung bearbeiten",
            "Text",
            annotation.get("text", ""),
        )
        if not accepted:
            self.set_status("Bearbeiten abgebrochen.")
            return

        payload = annotation_update_payload(text=text)
        if not payload.get("text"):
            self.set_status("Anmerkungstext ist erforderlich.")
            return
        self._update_annotation(annotation, payload, "Anmerkung gespeichert")

    def update_selected_annotation_status(self, status):
        payload = annotation_update_payload(status=status)
        label = "Anmerkung erledigt" if status == "resolved" else "Anmerkung wieder geöffnet"
        self._update_annotation(self.selected_annotation(), payload, label)

    def update_selected_annotation(self, payload, success_prefix):
        self._update_annotation(self.selected_annotation(), payload, success_prefix)

    def _update_annotation(self, annotation, payload, success_prefix="Anmerkung gespeichert"):
        annotation_id = annotation.get("id") if isinstance(annotation, dict) else None
        if annotation_id is None:
            self.set_status("Keine Anmerkung ausgewählt.")
            return

        try:
            updated = self.client().update_annotation(annotation_id, payload)
        except PLMError as exc:
            self.set_status(f"PLM-Fehler: {exc}")
            return
        except Exception as exc:
            self.set_status(f"Anmerkung konnte nicht gespeichert werden: {exc}")
            return

        revision = self.selected_revision()
        if isinstance(revision, dict):
            self.refresh_annotations(revision)
        self.set_status(f"{success_prefix}: {annotation_label(updated)}")

    def delete_selected_annotation(self):
        annotation = self.selected_annotation()
        self._delete_annotation(annotation)

    def _delete_annotation(self, annotation):
        annotation_id = annotation.get("id") if isinstance(annotation, dict) else None
        if annotation_id is None:
            self.set_status("Keine Anmerkung ausgewählt.")
            return

        answer = self.QtWidgets.QMessageBox.question(
            self.widget,
            "Anmerkung löschen",
            "Ausgewählte Anmerkung wirklich löschen?",
        )
        if answer != self.QtWidgets.QMessageBox.Yes:
            self.set_status("Löschen abgebrochen.")
            return

        try:
            self.client().delete_annotation(annotation_id)
        except PLMError as exc:
            self.set_status(f"PLM-Fehler: {exc}")
            return
        except Exception as exc:
            self.set_status(f"Anmerkung konnte nicht gelöscht werden: {exc}")
            return

        revision = self.selected_revision()
        if isinstance(revision, dict):
            self.refresh_annotations(revision)
        self.set_status("Anmerkung gelöscht.")

    def open_selected_revision(self):
        revision = self.selected_revision()
        action = revision_primary_action(revision)
        if action == "checkout":
            self.checkout_selected_revision()
        elif action == "open_readonly":
            self.open_selected_revision_readonly()
        else:
            self.set_status("Keine Revision ausgewählt.")

    def _sync_slicer_project_path(self, project_path, revision, state=None):
        from .slicer import read_sync_state, validate_3mf, write_sync_state
        from .workspace import sha256_file

        project_path = Path(project_path)
        state = dict(state or read_sync_state(project_path))
        validate_3mf(project_path)
        local_sha256 = sha256_file(project_path)
        if local_sha256 == state.get("server_sha256"):
            return False
        if state.get("print_project_id"):
            result = self.client().sync_print_project(
                state["print_project_id"], project_path
            )
            server_project = result["slicer_project"]
        else:
            result = self.client().sync_slicer_project(
                revision["id"], project_path,
                base_sha256=state.get("server_sha256", ""),
                label="Slicer-Projekt", slicer_name=state.get("slicer_name", ""),
            )
            server_project = result["slicer_project"]
        state.update(
            {
                "revision_id": revision["id"],
                "manufacturing_file_id": server_project.get("id"),
                "server_sha256": server_project["sha256"],
                "local_sha256": local_sha256,
                "sync_status": "synchronized",
            }
        )
        write_sync_state(project_path, state)
        self.set_status(f"Slicer-Projekt synchronisiert: {project_path.name}")
        return True

    def _slicer_file_changed(self, project_path, revision):
        from .slicer import read_sync_state, write_sync_state

        try:
            self._sync_slicer_project_path(project_path, revision)
        except ConflictError as exc:
            state = read_sync_state(project_path)
            state["sync_status"] = "conflict"
            write_sync_state(project_path, state)
            self.set_status(f"Slicer-Synchronisationskonflikt: {exc}")
        except Exception as exc:
            self.set_status(f"Slicer-Projekt noch nicht synchronisiert: {exc}")

    def open_selected_revision_in_slicer(self):
        from .slicer import (
            SLICERS,
            SlicerProjectMonitor,
            export_revision_manifest_to_3mf,
            launch_slicer,
            read_sync_state,
            reconcile_slicer_project,
            resolve_slicer_command,
            slicer_project_dir,
            slicer_project_filename,
            validate_3mf,
            write_sync_state,
        )
        from .workspace import sha256_file

        project = self.selected_project()
        part = self.selected_part()
        revision = self.selected_revision()
        if not project or not part or not revision or revision.get("id") is None:
            self.set_status("Projekt, Teil und Revision auswählen.")
            return
        if revision_file_format(revision) not in ("fcstd", "step", "stl"):
            self.set_status("Diese Revision kann nicht als Slicer-Projekt geöffnet werden.")
            return

        revision_id = revision["id"]
        project_code = project.get("code") or f"project-{project.get('id')}"
        target_dir = slicer_project_dir(
            self.workspace_root.text().strip(),
            self.server_url.text().strip(),
            project_code,
            revision_id,
        )
        target_dir.mkdir(parents=True, exist_ok=True)
        try:
            command = resolve_slicer_command(
                self.slicer_kind,
                self.slicer_executable,
                self.slicer_extra_args,
            )
            client = self.client()
            matches = [
                item for item in client.get_print_projects()
                if item.get("primary_revision_id") == revision_id
            ]
            if matches:
                print_project = matches[0]
            else:
                print_project = client.create_print_project(
                    revision_id,
                    f"DP-{revision_id}",
                    f"Druckprojekt {part.get('number', '')} {revision.get('revision_code', '')}".strip(),
                )
                source_paths, _selected_filter = self.QtWidgets.QFileDialog.getOpenFileNames(
                    None,
                    "Externe STL-Quellen zum Druckprojekt hinzufügen (optional)",
                    "",
                    "STL-Dateien (*.stl)",
                )
                for source_path in source_paths:
                    client.add_print_project_source(print_project["id"], source_path)
            target_path = target_dir / slicer_project_filename(
                project_code, print_project["code"], "", revision.get("original_filename", "")
            )
            server_project = print_project.get("slicer_project")
            state = read_sync_state(target_path)
            state["print_project_id"] = print_project["id"]
            local_sha = sha256_file(target_path) if target_path.is_file() else ""
            previous_server_sha = state.get("server_sha256", "")
            current_server_sha = server_project.get("sha256", "") if server_project else ""
            reconcile_action = reconcile_slicer_project(
                local_sha, previous_server_sha, current_server_sha
            )

            if reconcile_action == "conflict":
                raise ConflictError(
                    409,
                    "Lokale und serverseitige Slicer-Projekte wurden geändert. "
                    "Die lokale Datei bleibt unangetastet.",
                )
            if reconcile_action == "upload":
                try:
                    validate_3mf(target_path)
                except EmptyGeometryError:
                    reconcile_action = "rebuild"
                else:
                    self._sync_slicer_project_path(target_path, revision, state)
                    server_project = client.get_print_project(print_project["id"]).get("slicer_project")
            elif reconcile_action in ("download", "current") and server_project:
                if reconcile_action == "download":
                    client.download_manufacturing_file(
                        server_project["download_url"],
                        target_path,
                        server_project["sha256"],
                    )
                state.update(
                    {
                        "revision_id": revision_id,
                        "manufacturing_file_id": server_project["id"],
                        "server_sha256": server_project["sha256"],
                        "local_sha256": server_project["sha256"],
                        "sync_status": "synchronized",
                    }
                )

            if target_path.is_file() and reconcile_action != "rebuild":
                try:
                    validate_3mf(target_path)
                except EmptyGeometryError:
                    reconcile_action = "rebuild"

            if not target_path.is_file() or reconcile_action == "rebuild":
                self.set_status(
                    "Erzeuge 3MF aus der CAD-Revision und ihren Abhängigkeiten..."
                )
                export_revision_manifest_to_3mf(
                    client,
                    revision_id,
                    target_dir / "source",
                    target_path,
                )

            validate_3mf(target_path)
            slicer_label = SLICERS.get(self.slicer_kind, {}).get("label", "")
            if not slicer_label:
                joined = " ".join(command).lower()
                slicer_label = "OrcaSlicer" if "orca" in joined else "Bambu Studio"
            state.update(
                {
                    "revision_id": revision_id,
                    "project_code": project_code,
                    "part_id": part.get("id"),
                    "slicer_name": slicer_label,
                }
            )
            write_sync_state(target_path, state)
            self._sync_slicer_project_path(target_path, revision, state)
            monitor = SlicerProjectMonitor(
                self.QtCore,
                target_path,
                lambda changed_path, item=dict(revision): self._slicer_file_changed(
                    changed_path, item
                ),
            )
            self.slicer_monitors[str(target_path)] = monitor
            launch_slicer(target_path, command)
        except ConflictError as exc:
            self.set_status(f"Slicer-Projekt-Konflikt: {exc}")
            return
        except PLMError as exc:
            self.set_status(f"PLM-Fehler: {exc}")
            return
        except Exception as exc:
            self.set_status(f"Slicer konnte nicht geöffnet werden: {exc}")
            return

        self.set_status(
            f"Slicer-Projekt geöffnet; Speichern wird automatisch synchronisiert: {target_path}"
        )

    def open_selected_revision_readonly(self):
        from . import fcstd

        project = self.selected_project()
        revision = self.selected_revision()
        if project is None:
            self.set_status("Kein Projekt ausgewählt.")
            return
        if revision is None:
            self.set_status("Keine Revision ausgewählt.")
            return

        revision_id = revision.get("id")
        if revision_id is None:
            self.set_status("Revision hat keine ID.")
            return

        project_code = (
            project.get("code")
            or project.get("project_code")
            or f"project-{project.get('id')}"
        )
        target_dir = readonly_revision_dir(
            self.workspace_root.text().strip(),
            self.server_url.text().strip(),
            project_code,
            revision_id,
        )

        try:
            closed, failed = fcstd.close_documents(self.readonly_document_names)
            self.readonly_document_names = []
            if failed:
                failed_names = ", ".join(failed)
                self.set_status(
                    f"Vorherige read-only Dokumente konnten nicht geschlossen werden: {failed_names}"
                )
                return

            self.set_status("Lade Manifest und Dateien herunter...")
            manifest = self.client().get_revision_manifest(revision_id)
            write_manifest(target_dir, manifest)
            downloaded = download_manifest_files(self.client(), manifest, target_dir)
            for path in downloaded:
                path.chmod(0o444)
            root_path = root_file_path(manifest, target_dir)
            before_documents = fcstd.document_names()
            document = fcstd.open_document(root_path)
            self.readonly_document_names = fcstd.opened_document_names(before_documents, document)
            touch_directory(target_dir)
            pruned = prune_readonly_cache(
                self.workspace_root.text().strip(),
                self.server_url.text().strip(),
                current_project_code=project_code,
                current_revision_id=revision_id,
                max_fcstd_files=self.cache_max_fcstd_files.value(),
                max_projects=self.cache_max_projects.value(),
                max_revisions_per_project=self.cache_max_revisions_per_project.value(),
            )
        except PLMError as exc:
            self.set_status(f"PLM-Fehler: {exc}")
            return
        except Exception as exc:
            self.set_status(f"Öffnen fehlgeschlagen: {exc}")
            return

        print_freecad_console(
            f"FreeCAD-PLM Read-only geöffnet: {root_path} ({len(downloaded)} Datei(en))"
        )
        message = f"Read-only geöffnet ({len(downloaded)} Datei(en))"
        if closed:
            message = f"{message}; vorher geschlossen: {len(closed)}"
        if pruned:
            message = f"{message}; Cache bereinigt: {len(pruned)}"
        self.set_status(message)

    def checkout_revision_to_workspace(self, project, revision_id, snapshot_id=None):
        response = self.client().checkout_revision(
            revision_id,
            snapshot_id=snapshot_id,
            workspace_hint=self.workspace_root.text().strip(),
        )
        return self.open_checkout_response_to_workspace(project, response)

    def open_checkout_response_to_workspace(self, project, response):
        from . import fcstd

        project_code = (
            project.get("code")
            or project.get("project_code")
            or f"project-{project.get('id')}"
        )
        workspace_root = self.workspace_root.text().strip()
        server_url = self.server_url.text().strip()

        closed, failed = fcstd.close_documents(self.readonly_document_names)
        self.readonly_document_names = []
        if failed:
            failed_names = ", ".join(failed)
            raise RuntimeError(
                f"Vorherige read-only Dokumente konnten nicht geschlossen werden: {failed_names}"
            )

        client = self.client()
        checkout = response.get("checkout") or {}
        checkout_id = (
            checkout.get("id")
            or response.get("checkout_id")
            or response.get("id")
        )
        if checkout_id is None:
            raise RuntimeError("Checkout-Antwort enthält keine Checkout-ID.")

        manifest = response.get("manifest")
        if manifest is None:
            manifest_response = client.get_checkout_manifest(checkout_id)
            manifest = manifest_response.get("manifest", manifest_response)

        target_dir = checkout_dir(workspace_root, server_url, project_code, checkout_id)
        write_manifest(target_dir, manifest)
        downloaded = ensure_checkout_manifest_files(client, manifest, target_dir)
        write_checkout_metadata(target_dir, build_checkout_metadata(manifest, target_dir))
        root_path = root_file_path(manifest, target_dir)

        before_documents = fcstd.document_names()
        document = fcstd.open_document(root_path)
        self.checkout_document_names = fcstd.opened_document_names(before_documents, document)
        self.active_checkout = dict(checkout)
        self.active_checkout.setdefault("id", checkout_id)
        self.active_checkout.setdefault(
            "project",
            {
                "id": project.get("id"),
                "code": project.get("code") or project.get("project_code"),
                "name": project.get("name"),
            },
        )
        self.active_checkout_dir = target_dir
        self.active_checkout_root_path = root_path
        self.clear_checkout_error(checkout_id)
        touch_directory(target_dir)
        self.update_checkout_controls()
        self.refresh_active_checkouts(client)
        return {
            "root_path": root_path,
            "downloaded": downloaded,
            "closed_readonly": closed,
            "checkout": self.active_checkout,
        }

    def add_checkout_response_to_workspace(self, response):
        from . import fcstd

        if self.active_checkout_dir is None:
            raise RuntimeError("Aktiver Checkout ist lokal noch nicht geöffnet.")
        current_manifest = read_manifest(self.active_checkout_dir)
        checkout_metadata = ensure_checkout_metadata(
            current_manifest,
            self.active_checkout_dir,
        )
        updated_manifest = response.get("manifest") or {}
        added_file = response.get("added_file") or {}
        added_path = added_file.get("path") or ""
        if not updated_manifest.get("files") or not added_path:
            raise RuntimeError("Server-Antwort enthält keine hinzugefügte Datei.")
        downloaded = ensure_checkout_manifest_files(
            self.client(),
            updated_manifest,
            self.active_checkout_dir,
        )
        write_manifest(self.active_checkout_dir, updated_manifest)
        write_checkout_metadata(
            self.active_checkout_dir,
            merge_checkout_metadata(
                updated_manifest,
                checkout_metadata,
                self.active_checkout_dir,
            ),
        )
        local_path = safe_join(self.active_checkout_dir / "files", added_path)
        before_documents = fcstd.document_names()
        document = fcstd.open_document(local_path)
        opened = fcstd.opened_document_names(before_documents, document)
        self.checkout_document_names = sorted(
            set(self.checkout_document_names).union(opened)
        )
        return {
            "added_path": added_path,
            "downloaded": downloaded,
            "local_path": local_path,
        }

    def checkout_selected_revision(self):
        project = self.selected_project()
        revision = self.selected_revision()
        if project is None:
            self.set_status("Kein Projekt ausgewählt.")
            return
        if revision is None:
            self.set_status("Keine Revision ausgewählt.")
            return
        if not revision_is_checkout_editable(revision):
            self.set_status(
                "Nur FreeCAD-Revisionen können ausgecheckt und bearbeitet werden."
            )
            return

        revision_id = revision.get("id")
        if revision_id is None:
            self.set_status("Revision hat keine ID.")
            return

        action = checkout_guard_action(self.active_checkout, revision)
        if action == "missing_revision":
            self.set_status("Revision hat keine ID.")
            return
        if action == "same_checkout":
            self.open_active_checkout_root()
            return
        if action == "blocked_by_other_checkout":
            conflict_action = self.ask_checkout_conflict_action(revision)
            if conflict_action == "open_active":
                self.open_active_checkout_root()
            elif conflict_action == "checkin":
                self.checkin_active_checkout()
            elif conflict_action == "cancel":
                self.cancel_active_checkout()
            else:
                self.set_status("Checkout nicht gestartet.")
            return

        try:
            self.set_status("Starte Checkout und lade Dateien herunter...")
            result = self.checkout_revision_to_workspace(project, revision_id)
        except ConflictError as exc:
            self.refresh_active_checkouts()
            self.set_status(
                f"Checkout bereits aktiv oder blockiert: {exc}. Aktive Checkouts wurden aktualisiert."
            )
            return
        except PLMError as exc:
            self.set_status(f"PLM-Fehler: {exc}")
            return
        except Exception as exc:
            self.set_status(f"Checkout fehlgeschlagen: {exc}")
            return

        root_path = result["root_path"]
        downloaded = result["downloaded"]
        closed = result["closed_readonly"]
        print_freecad_console(
            f"FreeCAD-PLM Checkout geöffnet: {root_path} ({len(downloaded)} Datei(en))"
        )
        message = f"Checkout geöffnet ({len(downloaded)} Datei(en))"
        if closed:
            message = f"{message}; read-only geschlossen: {len(closed)}"
        self.set_status(message)

    def ask_checkout_conflict_action(self, target_revision):
        box = self.QtWidgets.QMessageBox(self.widget)
        box.setWindowTitle("Aktiver Checkout")
        box.setText(
            "Es ist bereits ein anderer Checkout aktiv.\n\n"
            f"Gewünschte Revision: {compact_revision_summary(target_revision)}"
        )
        open_button = box.addButton("Aktiven Checkout öffnen", self.QtWidgets.QMessageBox.AcceptRole)
        checkin_button = box.addButton("Einchecken", self.QtWidgets.QMessageBox.ActionRole)
        cancel_button = box.addButton("Checkout abbrechen", self.QtWidgets.QMessageBox.DestructiveRole)
        stop_button = box.addButton("Nicht starten", self.QtWidgets.QMessageBox.RejectRole)
        box.setDefaultButton(open_button)
        box.exec_()
        clicked = box.clickedButton()
        if clicked == open_button:
            return "open_active"
        if clicked == checkin_button:
            return "checkin"
        if clicked == cancel_button:
            return "cancel"
        if clicked == stop_button:
            return "stop"
        return "stop"

    def open_active_checkout_root(self):
        from . import fcstd

        if self.active_checkout_root_path is None:
            message = "Aktiver Checkout ist lokal noch nicht geöffnet."
            self.mark_checkout_error(self.active_checkout_id(), message)
            self.set_status(message)
            return
        try:
            before_documents = fcstd.document_names()
            document = fcstd.open_document(self.active_checkout_root_path)
            opened = fcstd.opened_document_names(before_documents, document)
            if opened:
                self.checkout_document_names = opened
        except Exception as exc:
            message = f"Aktiver Checkout konnte nicht geöffnet werden: {exc}"
            self.mark_checkout_error(self.active_checkout_id(), message)
            self.set_status(message)
            return
        self.clear_checkout_error(self.active_checkout_id())
        self.update_checkout_controls()
        print_freecad_console(
            f"FreeCAD-PLM aktiver Checkout geöffnet: {self.active_checkout_root_path}"
        )
        self.set_status("Aktiver Checkout geöffnet.")

    def reopen_selected_checkout(self):
        from . import fcstd

        checkout = self.selected_active_checkout() or self.active_checkout
        if checkout is None:
            self.set_status("Kein aktiver Checkout ausgewählt.")
            return

        checkout_id = checkout.get("id")
        if checkout_id is None:
            self.set_status("Aktiver Checkout hat keine ID.")
            return

        active_id = self.active_checkout_id()
        if active_id is not None and active_id != checkout_id:
            self.set_status("Es ist bereits ein anderer Checkout geöffnet.")
            return
        if active_id == checkout_id and self.active_checkout_root_path is not None:
            self.open_active_checkout_root()
            return

        workspace_root = self.workspace_root.text().strip()
        server_url = self.server_url.text().strip()
        project_code = checkout_project_code(checkout)
        target_dir = checkout_dir(workspace_root, server_url, project_code, checkout_id)

        try:
            closed_readonly, failed_readonly = fcstd.close_documents(self.readonly_document_names)
            self.readonly_document_names = []
            if failed_readonly:
                failed_names = ", ".join(failed_readonly)
                message = (
                    "Vorherige read-only Dokumente konnten nicht geschlossen werden: "
                    f"{failed_names}"
                )
                self.mark_checkout_error(checkout_id, message)
                self.set_status(message)
                return

            closed_checkout, failed_checkout = fcstd.close_documents(self.checkout_document_names)
            self.checkout_document_names = []
            if failed_checkout:
                failed_names = ", ".join(failed_checkout)
                message = (
                    "Vorherige Checkout-Dokumente konnten nicht geschlossen werden: "
                    f"{failed_names}"
                )
                self.mark_checkout_error(checkout_id, message)
                self.set_status(message)
                return

            client = self.client()
            self.set_status("Öffne aktiven Checkout wieder...")
            manifest = response_manifest(checkout.get("manifest"))
            if manifest is None:
                manifest = response_manifest(client.get_checkout_manifest(checkout_id))
            write_manifest(target_dir, manifest)
            downloaded = ensure_checkout_manifest_files(client, manifest, target_dir)
            ensure_checkout_metadata(manifest, target_dir)
            root_path = root_file_path(manifest, target_dir)

            before_documents = fcstd.document_names()
            document = fcstd.open_document(root_path)
            self.checkout_document_names = fcstd.opened_document_names(before_documents, document)
            self.active_checkout = dict(checkout)
            self.active_checkout.setdefault("id", checkout_id)
            self.active_checkout_dir = target_dir
            self.active_checkout_root_path = root_path
            self.clear_checkout_error(checkout_id)
            touch_directory(target_dir)
            self.update_checkout_controls()
        except PLMError as exc:
            message = f"PLM-Fehler: {exc}"
            self.mark_checkout_error(checkout_id, message)
            self.set_status(message)
            return
        except Exception as exc:
            message = f"Checkout konnte nicht wieder geöffnet werden: {exc}"
            self.mark_checkout_error(checkout_id, message)
            self.set_status(message)
            return

        print_freecad_console(
            f"FreeCAD-PLM Checkout wieder geöffnet: {root_path} ({len(downloaded)} ergänzt)"
        )
        message = f"Checkout wieder geöffnet ({len(downloaded)} ergänzt)"
        closed = len(closed_readonly) + len(closed_checkout)
        if closed:
            message = f"{message}; vorher geschlossen: {closed}"
        self.set_status(message)

    def checkin_active_checkout(self):
        from . import fcstd

        checkout_id = self.active_checkout_id()
        if (
            checkout_id is None
            or self.active_checkout_dir is None
            or self.active_checkout_root_path is None
        ):
            self.set_status("Kein aktiver Checkout.")
            return

        saved = []
        closed = []
        close_failed = []
        try:
            manifest = read_manifest(self.active_checkout_dir)
            checkout_metadata = ensure_checkout_metadata(manifest, self.active_checkout_dir)
            checkout_document_names = fcstd.document_names_in_directory(
                self.active_checkout_dir / "files"
            )
            if not checkout_document_names:
                checkout_document_names = list(self.checkout_document_names)
            if checkout_document_names:
                saved, failed = fcstd.save_documents(checkout_document_names)
                if failed:
                    failed_names = ", ".join(failed)
                    self.set_status(
                        f"Dokumente konnten nicht gespeichert werden: {failed_names}"
                    )
                    return

            changed_files = technically_changed_manifest_files(
                manifest,
                checkout_metadata,
                self.active_checkout_dir,
            )
            has_structural_changes = bool(
                manifest.get("removed_paths") or manifest.get("added_paths")
            )
            if not changed_files and not has_structural_changes:
                self.offer_cancel_unchanged_checkout(saved_count=len(saved))
                return

            update_changed_files_plm_revisions(changed_files)
            changed_files = technically_changed_manifest_files(
                manifest,
                checkout_metadata,
                self.active_checkout_dir,
            )
            if not changed_files and not has_structural_changes:
                self.offer_cancel_unchanged_checkout(saved_count=len(saved))
                return

            summary, accepted = self.QtWidgets.QInputDialog.getMultiLineText(
                self.widget,
                "Einchecken",
                "Änderungskommentar",
                "",
            )
            if not accepted:
                self.set_status("Einchecken abgebrochen.")
                return

            change_summary = summary.strip()
            if not change_summary:
                self.set_status("Änderungskommentar ist erforderlich.")
                return

            self.set_status("Sende Check-in...")
            response = self.client().checkin_files(
                checkout_id,
                changed_files,
                change_summary,
            )
            if checkin_created_revision_count(response) == 0 and not checkin_completed(response):
                self.refresh_active_checkouts()
                message = unchanged_checkout_text(saved_count=len(saved))
                result_text = checkin_result_text(response)
                if result_text:
                    message = f"{message} {result_text}"
                self.set_status(message)
                return

            closed, close_failed = fcstd.close_documents(self.checkout_document_names)
            self.reset_active_checkout()
            self.refresh_revisions()
            revision = response.get("revision") if isinstance(response, dict) else None
            if isinstance(revision, dict) and revision.get("id") is not None:
                self.select_revision_by_id(revision["id"])
            self.refresh_active_checkouts()
        except ConflictError as exc:
            self.refresh_active_checkouts()
            self.set_status(checkin_conflict_text(exc))
            return
        except PLMError as exc:
            self.set_status(f"PLM-Fehler: {exc}")
            return
        except Exception as exc:
            self.set_status(f"Einchecken fehlgeschlagen: {exc}")
            return

        message = "Check-in abgeschlossen."
        result_text = checkin_result_text(response)
        if result_text:
            message = f"{message} {result_text}"
        message = f"{message} Geänderte Dateien: {len(changed_files)}."
        if saved:
            message = f"{message} Gespeichert: {len(saved)}."
        if closed:
            message = f"{message} Geschlossen: {len(closed)}."
        if close_failed:
            message = f"{message} Schließen fehlgeschlagen: {', '.join(close_failed)}."
        self.set_status(message)

    def add_selected_file_to_active_checkout(self):
        checkout_id = self.active_checkout_id()
        revision = self.selected_revision()
        revision_id = revision.get("id") if isinstance(revision, dict) else None
        if checkout_id is None or self.active_checkout_dir is None:
            self.set_status("Kein aktiver Checkout.")
            return
        if revision_id is None:
            self.set_status("Bitte die hinzuzufügende Revision auswählen.")
            return

        answer = self.QtWidgets.QMessageBox.question(
            self.widget,
            "Teil zum Checkout hinzufügen",
            (
                f"{compact_revision_summary(revision)} zum aktiven Checkout hinzufügen?\n\n"
                "Die Datei wird in den Checkout-Ordner geladen und in FreeCAD geöffnet."
            ),
            self.QtWidgets.QMessageBox.Yes | self.QtWidgets.QMessageBox.No,
            self.QtWidgets.QMessageBox.Yes,
        )
        if answer != self.QtWidgets.QMessageBox.Yes:
            self.set_status("Hinzufügen abgebrochen.")
            return

        try:
            response = self.client().add_checkout_file(checkout_id, revision_id)
            result = self.add_checkout_response_to_workspace(response)
        except PLMError as exc:
            self.set_status(f"PLM-Fehler: {exc}")
            return
        except Exception as exc:
            self.set_status(f"Teil konnte nicht hinzugefügt werden: {exc}")
            return

        self.set_status(
            f"{result['added_path']} wurde hinzugefügt, geladen und in FreeCAD geöffnet "
            f"({len(result['downloaded'])} neue Datei(en))."
        )

    def choose_revision_for_active_checkout(self):
        checkout_id = self.active_checkout_id()
        if checkout_id is None or self.active_checkout_dir is None:
            self.set_status("Kein lokal geöffneter Checkout.")
            return

        project = self.active_checkout.get("project") or {}
        project_item = self.find_tree_item("project", project.get("id"))
        if project_item is None:
            self.set_status("Projekt des aktiven Checkouts wurde nicht gefunden.")
            return

        self.load_project_parts(project_item)
        existing_revision_ids = set()
        try:
            manifest = read_manifest(self.active_checkout_dir)
            existing_revision_ids = {
                entry.get("revision_id")
                for entry in manifest.get("files") or []
                if entry.get("revision_id") is not None
            }
        except Exception:
            pass

        candidates = []
        for part_index in range(project_item.childCount()):
            part_item = project_item.child(part_index)
            if self.tree_item_kind(part_item) != "part":
                continue
            self.load_part_revisions(part_item)
            part = self.tree_item_payload(part_item) or {}
            for revision_index in range(part_item.childCount()):
                revision_item = part_item.child(revision_index)
                revision = self.tree_item_payload(revision_item) or {}
                revision_id = revision.get("id")
                if (
                    self.tree_item_kind(revision_item) != "revision"
                    or not revision_is_checkout_editable(revision)
                    or revision_id in existing_revision_ids
                ):
                    continue
                label = (
                    f"{part_label(part)} · {compact_revision_summary(revision)} "
                    f"[ID {revision_id}]"
                )
                candidates.append((label, revision_item))

        self.reveal_active_checkouts()
        if not candidates:
            self.set_status("Keine weitere FCStd-Revision zum Hinzufügen gefunden.")
            return

        label, accepted = self.QtWidgets.QInputDialog.getItem(
            self.widget,
            "Teil zum Checkout hinzufügen",
            "Revision",
            [candidate[0] for candidate in candidates],
            0,
            False,
        )
        if not accepted:
            self.set_status("Hinzufügen abgebrochen.")
            return

        selected_item = dict(candidates).get(label)
        if selected_item is None:
            self.set_status("Ausgewählte Revision wurde nicht gefunden.")
            return
        self.browser_tree.setCurrentItem(selected_item)
        self.browser_tree.scrollToItem(selected_item)
        self.add_selected_file_to_active_checkout()

    def remove_file_from_active_checkout(self):
        from . import fcstd

        checkout_id = self.active_checkout_id()
        if checkout_id is None or self.active_checkout_dir is None:
            self.set_status("Kein aktiver Checkout.")
            return

        try:
            manifest = read_manifest(self.active_checkout_dir)
            checkout_metadata = ensure_checkout_metadata(manifest, self.active_checkout_dir)
        except Exception as exc:
            self.set_status(f"Checkout-Manifest konnte nicht gelesen werden: {exc}")
            return

        candidates = removable_manifest_files(manifest)
        if not candidates:
            self.set_status("Der Checkout enthält kein entfernbares Teil.")
            return

        labels = [checkout_file_label(item) for item in candidates]
        label, accepted = self.QtWidgets.QInputDialog.getItem(
            self.widget,
            "Teil aus Checkout entfernen",
            "Teil",
            labels,
            0,
            False,
        )
        if not accepted:
            self.set_status("Entfernen abgebrochen.")
            return

        item = candidates[labels.index(label)]
        path = item.get("path") or ""
        local_path = safe_join(self.active_checkout_dir / "files", path)
        document_names = fcstd.document_names_for_path(local_path)
        modified_names = fcstd.modified_document_names(document_names)
        warning = (
            f"{path} aus diesem Checkout entfernen?\n\n"
            "Die gespeicherte Revision und der Teilestammsatz bleiben im PLM erhalten. "
            "Beim Einchecken wird ein neuer Projektstand ohne diese Datei erzeugt."
        )
        if modified_names:
            warning += "\n\nNicht gespeicherte lokale Änderungen werden verworfen."
        answer = self.QtWidgets.QMessageBox.question(
            self.widget,
            "Teil entfernen",
            warning,
            self.QtWidgets.QMessageBox.Yes | self.QtWidgets.QMessageBox.No,
            self.QtWidgets.QMessageBox.No,
        )
        if answer != self.QtWidgets.QMessageBox.Yes:
            self.set_status("Entfernen abgebrochen.")
            return

        closed, failed = fcstd.close_documents(document_names)
        if failed:
            self.set_status(f"Teil konnte nicht geschlossen werden: {', '.join(failed)}")
            return

        try:
            response = self.client().remove_checkout_file(checkout_id, path)
            updated_manifest = response.get("manifest") or {}
            if not updated_manifest.get("files"):
                raise RuntimeError("Server-Antwort enthält kein Checkout-Manifest.")
            delete_checkout_manifest_file(self.active_checkout_dir, path)
            write_manifest(self.active_checkout_dir, updated_manifest)
            write_checkout_metadata(
                self.active_checkout_dir,
                merge_checkout_metadata(
                    updated_manifest,
                    checkout_metadata,
                    self.active_checkout_dir,
                ),
            )
        except Exception as exc:
            if local_path.exists():
                try:
                    document = fcstd.open_document(local_path)
                    document_name = getattr(document, "Name", "")
                    if document_name:
                        self.checkout_document_names.append(document_name)
                except Exception:
                    pass
            self.set_status(f"Teil konnte nicht entfernt werden: {exc}")
            return

        self.checkout_document_names = [
            name for name in self.checkout_document_names if name not in closed
        ]
        self.set_status(f"{path} wurde zum Entfernen vorgemerkt.")

    def offer_cancel_unchanged_checkout(self, saved_count=0):
        answer = self.QtWidgets.QMessageBox.question(
            self.widget,
            "Keine Änderungen",
            "Keine modellrelevanten Änderungen gefunden. Checkout abbrechen?",
        )
        if answer != self.QtWidgets.QMessageBox.Yes:
            self.set_status(unchanged_checkout_text(saved_count=saved_count))
            return
        self.cancel_active_checkout(confirm=False)

    def cancel_checkout(self, checkout, confirm=True):
        from . import fcstd

        checkout_id = checkout.get("id") if isinstance(checkout, dict) else None
        if checkout_id is None:
            self.set_status("Kein Checkout ausgewählt.")
            return

        if confirm:
            answer = self.QtWidgets.QMessageBox.question(
                self.widget,
                "Checkout abbrechen",
                f"Checkout {checkout_id} wirklich abbrechen?",
            )
            if answer != self.QtWidgets.QMessageBox.Yes:
                self.set_status("Checkout-Abbruch abgebrochen.")
                return

        is_local_checkout = checkout_id == self.active_checkout_id()
        closed = []
        failed = []
        try:
            self.set_status("Breche Checkout ab...")
            self.client().cancel_checkout(checkout_id)
            if is_local_checkout:
                closed, failed = fcstd.close_documents(self.checkout_document_names)
                self.reset_active_checkout()
            else:
                self.checkout_errors.pop(checkout_id, None)
            self.refresh_active_checkouts()
        except PLMError as exc:
            self.set_status(f"PLM-Fehler: {exc}")
            return
        except Exception as exc:
            self.set_status(f"Checkout-Abbruch fehlgeschlagen: {exc}")
            return

        message = "Checkout abgebrochen."
        if closed:
            message = f"{message} Geschlossen: {len(closed)}."
        if failed:
            message = f"{message} Schließen fehlgeschlagen: {', '.join(failed)}."
        self.set_status(message)

    def cancel_selected_checkout(self, confirm=True):
        checkout = self.selected_tree_checkout()
        if checkout is None:
            self.set_status("Kein Checkout ausgewählt.")
            return
        self.cancel_checkout(checkout, confirm=confirm)

    def cancel_active_checkout(self, confirm=True):
        self.cancel_checkout(self.active_checkout, confirm=confirm)


def _find_dock(main_window, QtWidgets):
    return main_window.findChild(QtWidgets.QDockWidget, PANEL_OBJECT_NAME)


def show_panel():
    import FreeCADGui

    global _active_panel

    QtCore, _QtGui, QtWidgets = _load_qt()
    main_window = FreeCADGui.getMainWindow()
    dock = _find_dock(main_window, QtWidgets)
    if dock is None:
        dock = QtWidgets.QDockWidget("FreeCAD-PLM", main_window)
        dock.setObjectName(PANEL_OBJECT_NAME)
        _active_panel = PLMPanel()
        _active_panel.widget._plm_panel = _active_panel
        dock.setWidget(_active_panel.widget)
        main_window.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
    elif _active_panel is None:
        _active_panel = getattr(dock.widget(), "_plm_panel", None)
    dock.show()
    dock.raise_()
    return dock


def refresh_panel():
    show_panel()
    if _active_panel is not None:
        _active_panel.refresh_projects()


def checkout_selected_revision():
    show_panel()
    if _active_panel is not None:
        _active_panel.checkout_selected_revision()


def checkin_active_checkout():
    show_panel()
    if _active_panel is not None:
        _active_panel.checkin_active_checkout()


def cancel_active_checkout():
    show_panel()
    if _active_panel is not None:
        _active_panel.cancel_active_checkout()


def create_annotation_for_selection():
    show_panel()
    if _active_panel is None:
        return
    try:
        from . import fcstd

        object_name = fcstd.selected_object_name()
        subelement = fcstd.selected_subelement_name()
    except Exception:
        object_name = ""
        subelement = ""
    _active_panel.create_annotation_for_current_revision(
        object_name=object_name,
        subelement=subelement,
    )


def open_selected_revision_in_slicer():
    show_panel()
    if _active_panel is not None:
        _active_panel.open_selected_revision_in_slicer()


def open_revision_deep_link(deep_link):
    show_panel()
    if _active_panel is not None:
        _active_panel.handle_revision_deep_link(deep_link)


def prompt_for_revision_deep_link():
    from .deeplink import parse_revision_deep_link

    show_panel()
    if _active_panel is None:
        return
    value, accepted = _active_panel.QtWidgets.QInputDialog.getText(
        _active_panel.widget,
        "PLM-Link öffnen",
        "freecad-plm://-Link",
    )
    if not accepted:
        return
    try:
        deep_link = parse_revision_deep_link(value)
    except ValueError as exc:
        _active_panel.set_status(str(exc))
        return
    _active_panel.handle_revision_deep_link(deep_link)
