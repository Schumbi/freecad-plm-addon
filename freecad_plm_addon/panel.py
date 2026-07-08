import json

from .api_client import PLMClient
from .errors import ConflictError, PLMError
from .workspace import (
    build_checkout_metadata,
    checkout_dir,
    download_manifest_files,
    ensure_checkout_metadata,
    ensure_checkout_manifest_files,
    prune_readonly_cache,
    read_manifest,
    readonly_revision_dir,
    root_file_path,
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


def connection_label(server_url):
    text = server_url.replace("https://", "").replace("http://", "").strip("/")
    return f"Verbunden mit {text}" if text else "Nicht verbunden."


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
    status = revision.get("status") or revision.get("release_status") or ""
    filename = revision.get("original_filename") or revision.get("filename") or revision.get("file_name") or ""
    created = revision.get("created_at") or revision.get("created") or revision.get("uploaded_at") or ""
    label = f"Revision {number}" if number else f"Revision {revision.get('id', '')}".strip()
    details = [value for value in (status, filename, created[:10]) if value]
    if details:
        return f"{label} - {', '.join(details)}"
    return label


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

        return QtCore, QtGui
    except ImportError:
        pass

    try:
        from PySide6 import QtCore, QtWidgets

        return QtCore, QtWidgets
    except ImportError:
        from PySide2 import QtCore, QtWidgets

        return QtCore, QtWidgets


class PLMPanel:
    def __init__(self):
        from . import config

        self.QtCore, self.QtWidgets = _load_qt()
        self.widget = self.QtWidgets.QWidget()
        self.widget.setObjectName("FreeCADPLMPanelWidget")
        self.readonly_document_names = []
        self.checkout_document_names = []
        self.active_checkout = None
        self.active_checkout_dir = None
        self.active_checkout_root_path = None
        self.current_annotations = []

        layout = self.QtWidgets.QVBoxLayout(self.widget)

        self.connection_summary = self.QtWidgets.QLabel("Nicht verbunden.")
        layout.addWidget(self.connection_summary)

        self.settings_button = self.QtWidgets.QPushButton("Einstellungen")
        layout.addWidget(self.settings_button)

        self.settings_widget = self.QtWidgets.QWidget()
        settings_layout = self.QtWidgets.QVBoxLayout(self.settings_widget)
        form = self.QtWidgets.QFormLayout()

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

        form.addRow("Server", self.server_url)
        form.addRow("API-Token", self.api_token)
        form.addRow("Workspace", self.workspace_root)
        form.addRow("Max. FCStd-Dateien", self.cache_max_fcstd_files)
        form.addRow("Max. Projekte", self.cache_max_projects)
        form.addRow("Max. Revisionen je Projekt", self.cache_max_revisions_per_project)
        settings_layout.addLayout(form)

        button_row = self.QtWidgets.QHBoxLayout()
        self.connect_button = self.QtWidgets.QPushButton("Verbinden")
        self.refresh_button = self.QtWidgets.QPushButton("Aktualisieren")
        button_row.addWidget(self.connect_button)
        button_row.addWidget(self.refresh_button)
        settings_layout.addLayout(button_row)
        layout.addWidget(self.settings_widget)

        self.refresh_button.setVisible(False)

        splitter = self.QtWidgets.QSplitter(self.QtCore.Qt.Horizontal)
        layout.addWidget(splitter)

        browser_widget = self.QtWidgets.QWidget()
        browser_layout = self.QtWidgets.QVBoxLayout(browser_widget)

        browser_layout.addWidget(self.QtWidgets.QLabel("Projekte"))
        self.projects = self.QtWidgets.QListWidget()
        browser_layout.addWidget(self.projects)

        browser_layout.addWidget(self.QtWidgets.QLabel("Teile"))
        self.parts = self.QtWidgets.QListWidget()
        browser_layout.addWidget(self.parts)

        part_action_row = self.QtWidgets.QHBoxLayout()
        self.new_part_button = self.QtWidgets.QPushButton("Neues Teil")
        self.new_part_button.setEnabled(False)
        part_action_row.addWidget(self.new_part_button)
        browser_layout.addLayout(part_action_row)

        browser_layout.addWidget(self.QtWidgets.QLabel("Revisionen"))
        self.revisions = self.QtWidgets.QListWidget()
        browser_layout.addWidget(self.revisions)

        details_widget = self.QtWidgets.QWidget()
        details_layout = self.QtWidgets.QVBoxLayout(details_widget)

        self.detail_tabs = self.QtWidgets.QTabWidget()

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

        details_layout.addWidget(self.detail_tabs)

        self.open_readonly_button = self.QtWidgets.QPushButton("Read-only öffnen")
        self.open_readonly_button.setEnabled(False)
        details_layout.addWidget(self.open_readonly_button)

        self.checkout_button = self.QtWidgets.QPushButton("Auschecken")
        self.checkout_button.setEnabled(False)
        details_layout.addWidget(self.checkout_button)

        details_layout.addWidget(self.QtWidgets.QLabel("Aktive Checkouts"))
        self.active_checkouts = self.QtWidgets.QListWidget()
        details_layout.addWidget(self.active_checkouts)

        self.reopen_checkout_button = self.QtWidgets.QPushButton("Checkout wieder öffnen")
        self.reopen_checkout_button.setEnabled(False)
        details_layout.addWidget(self.reopen_checkout_button)

        self.active_checkout_label = self.QtWidgets.QLabel("Kein aktiver Checkout.")
        self.active_checkout_label.setWordWrap(True)
        details_layout.addWidget(self.active_checkout_label)

        checkout_action_row = self.QtWidgets.QHBoxLayout()
        self.checkin_button = self.QtWidgets.QPushButton("Einchecken")
        self.cancel_checkout_button = self.QtWidgets.QPushButton("Checkout abbrechen")
        self.checkin_button.setEnabled(False)
        self.cancel_checkout_button.setEnabled(False)
        checkout_action_row.addWidget(self.checkin_button)
        checkout_action_row.addWidget(self.cancel_checkout_button)
        details_layout.addLayout(checkout_action_row)

        self.status = self.QtWidgets.QLabel("Nicht verbunden.")
        self.status.setWordWrap(True)
        details_layout.addWidget(self.status)

        splitter.addWidget(browser_widget)
        splitter.addWidget(details_widget)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)

        self.connect_button.clicked.connect(self.refresh_projects)
        self.refresh_button.clicked.connect(self.refresh_projects)
        self.settings_button.clicked.connect(self.toggle_settings)
        self.projects.itemSelectionChanged.connect(self.refresh_parts)
        self.parts.itemSelectionChanged.connect(self.refresh_revisions)
        self.new_part_button.clicked.connect(self.create_part_dialog)
        self.save_part_button.clicked.connect(self.save_selected_part)
        self.revisions.itemSelectionChanged.connect(self.show_revision_details)
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
        self.open_readonly_button.clicked.connect(self.open_selected_revision_readonly)
        self.checkout_button.clicked.connect(self.checkout_selected_revision)
        self.checkin_button.clicked.connect(self.checkin_active_checkout)
        self.cancel_checkout_button.clicked.connect(self.cancel_active_checkout)
        self.active_checkouts.itemSelectionChanged.connect(self.update_reopen_checkout_button)
        self.reopen_checkout_button.clicked.connect(self.reopen_selected_checkout)

    def toggle_settings(self):
        self.settings_widget.setVisible(not self.settings_widget.isVisible())

    def set_connected(self, server_url):
        self.connection_summary.setText(connection_label(server_url))
        self.settings_widget.setVisible(False)
        self.refresh_button.setVisible(True)

    def client(self):
        return PLMClient(self.server_url.text().strip(), self.api_token.text().strip())

    def selected_project(self):
        items = self.projects.selectedItems()
        if not items:
            return None
        project = items[0].data(self.QtCore.Qt.UserRole)
        return project if isinstance(project, dict) else None

    def selected_part(self):
        items = self.parts.selectedItems()
        if not items:
            return None
        part = items[0].data(self.QtCore.Qt.UserRole)
        return part if isinstance(part, dict) else None

    def selected_revision(self):
        items = self.revisions.selectedItems()
        if not items:
            return None
        revision = items[0].data(self.QtCore.Qt.UserRole)
        return revision if isinstance(revision, dict) else None

    def selected_annotation(self):
        items = self.annotations.selectedItems()
        if not items:
            return None
        annotation = items[0].data(self.QtCore.Qt.UserRole)
        return annotation if isinstance(annotation, dict) else None

    def select_revision_by_id(self, revision_id):
        for index in range(self.revisions.count()):
            item = self.revisions.item(index)
            revision = item.data(self.QtCore.Qt.UserRole)
            if isinstance(revision, dict) and revision.get("id") == revision_id:
                self.revisions.setCurrentItem(item)
                return True
        return False

    def selected_active_checkout(self):
        items = self.active_checkouts.selectedItems()
        if not items:
            return None
        checkout = items[0].data(self.QtCore.Qt.UserRole)
        return checkout if isinstance(checkout, dict) else None

    def update_reopen_checkout_button(self):
        self.reopen_checkout_button.setEnabled(self.selected_active_checkout() is not None)

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
        checkout_id = self.active_checkout_id()
        has_checkout = checkout_id is not None
        self.checkin_button.setEnabled(has_checkout)
        self.cancel_checkout_button.setEnabled(has_checkout)
        if not has_checkout:
            self.active_checkout_label.setText("Kein aktiver Checkout.")
            return

        path = str(self.active_checkout_root_path or "")
        details = f"Aktiver Checkout: {checkout_id}"
        if path:
            details = f"{details}\n{path}"
        self.active_checkout_label.setText(details)

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
        self.open_readonly_button.setEnabled(False)
        self.checkout_button.setEnabled(False)

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
        self.open_readonly_button.setEnabled(True)
        self.checkout_button.setEnabled(True)
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
            self.status.setText("Server und API-Token eintragen.")
            return

        self.status.setText("Lade Projekte...")
        self.projects.clear()
        self.parts.clear()
        self.revisions.clear()
        self.active_checkouts.clear()
        self.new_part_button.setEnabled(False)
        self.update_reopen_checkout_button()
        self.clear_revision_context()
        self.clear_part_form()

        try:
            client = self.client()
            projects = client.get_projects()
        except PLMError as exc:
            self.status.setText(f"PLM-Fehler: {exc}")
            return
        except Exception as exc:
            self.status.setText(f"Verbindung fehlgeschlagen: {exc}")
            return

        for project in projects:
            item = self.QtWidgets.QListWidgetItem(project_label(project))
            item.setData(self.QtCore.Qt.UserRole, project)
            self.projects.addItem(item)

        count = len(projects)
        checkout_count = self.refresh_active_checkouts(client)
        suffix = "" if count == 1 else "e"
        message = f"{count} Projekt{suffix} geladen."
        if checkout_count is not None:
            message = f"{message} Aktive Checkouts: {checkout_count}."
        self.status.setText(message)
        self.set_connected(server_url)

    def refresh_active_checkouts(self, client=None):
        self.active_checkouts.clear()
        self.update_reopen_checkout_button()
        try:
            checkouts = (client or self.client()).get_active_checkouts()
        except PLMError as exc:
            self.active_checkouts.addItem(f"PLM-Fehler: {exc}")
            return None
        except Exception as exc:
            self.active_checkouts.addItem(f"Aktive Checkouts konnten nicht geladen werden: {exc}")
            return None

        for checkout in checkouts:
            item = self.QtWidgets.QListWidgetItem(checkout_label(checkout))
            item.setData(self.QtCore.Qt.UserRole, checkout)
            self.active_checkouts.addItem(item)
        return len(checkouts)

    def refresh_parts(self):
        items = self.projects.selectedItems()
        self.parts.clear()
        self.revisions.clear()
        self.clear_revision_context()
        self.clear_part_form()
        self.new_part_button.setEnabled(False)
        if not items:
            return

        project = items[0].data(self.QtCore.Qt.UserRole)
        project_id = project.get("id") if isinstance(project, dict) else None
        if project_id is None:
            self.status.setText("Projekt hat keine ID.")
            return
        self.new_part_button.setEnabled(True)

        self.status.setText("Lade Teile...")

        try:
            parts = self.client().get_parts(project_id)
        except PLMError as exc:
            self.status.setText(f"PLM-Fehler: {exc}")
            return
        except Exception as exc:
            self.status.setText(f"Verbindung fehlgeschlagen: {exc}")
            return

        for part in parts:
            item = self.QtWidgets.QListWidgetItem(part_label(part))
            item.setData(self.QtCore.Qt.UserRole, part)
            self.parts.addItem(item)

        count = len(parts)
        suffix = "" if count == 1 else "e"
        self.status.setText(f"{count} Teil{suffix} geladen.")

    def refresh_revisions(self):
        items = self.parts.selectedItems()
        self.revisions.clear()
        self.clear_revision_context()
        if not items:
            self.clear_part_form()
            return

        part = items[0].data(self.QtCore.Qt.UserRole)
        part_id = part.get("id") if isinstance(part, dict) else None
        if part_id is None:
            self.status.setText("Teil hat keine ID.")
            return
        self.set_part_form(part)

        self.status.setText("Lade Revisionen...")

        try:
            part_detail = self.client().get_part(part_id)
        except PLMError as exc:
            self.status.setText(f"PLM-Fehler: {exc}")
            return
        except Exception as exc:
            self.status.setText(f"Verbindung fehlgeschlagen: {exc}")
            return

        revisions = revisions_from_part_detail(part_detail)
        detail_part = part_detail.get("part") if isinstance(part_detail, dict) else None
        if isinstance(detail_part, dict):
            items[0].setData(self.QtCore.Qt.UserRole, detail_part)
            items[0].setText(part_label(detail_part))
            self.set_part_form(detail_part)
        for revision in revisions:
            item = self.QtWidgets.QListWidgetItem(revision_label(revision))
            item.setData(self.QtCore.Qt.UserRole, revision)
            self.revisions.addItem(item)

        count = len(revisions)
        suffix = "" if count == 1 else "en"
        self.status.setText(f"{count} Revision{suffix} geladen.")

    def create_part_dialog(self):
        project = self.selected_project()
        project_id = project.get("id") if isinstance(project, dict) else None
        if project_id is None:
            self.status.setText("Kein Projekt ausgewählt.")
            return

        name, accepted = self.QtWidgets.QInputDialog.getText(
            self.widget,
            "Neues Teil",
            "Name",
            self.QtWidgets.QLineEdit.Normal,
            "",
        )
        if not accepted:
            self.status.setText("Teilanlage abgebrochen.")
            return

        name = name.strip()
        if not name:
            self.status.setText("Name ist erforderlich.")
            return

        category, accepted = self.QtWidgets.QInputDialog.getItem(
            self.widget,
            "Kategorie",
            "Kategorie",
            ["Teil", "Baugruppe"],
            0,
            False,
        )
        if not accepted:
            self.status.setText("Teilanlage abgebrochen.")
            return

        payload = {
            "name": name,
            "category": "assembly" if category == "Baugruppe" else "part",
        }
        try:
            part = self.client().create_part(project_id, payload)
        except PLMError as exc:
            self.status.setText(f"PLM-Fehler: {exc}")
            return
        except Exception as exc:
            self.status.setText(f"Teil konnte nicht angelegt werden: {exc}")
            return

        item = self.QtWidgets.QListWidgetItem(part_label(part))
        item.setData(self.QtCore.Qt.UserRole, part)
        self.parts.addItem(item)
        self.parts.setCurrentItem(item)
        self.status.setText(f"Teil angelegt: {part_label(part)}")

    def save_selected_part(self):
        part = self.selected_part()
        part_id = part.get("id") if isinstance(part, dict) else None
        if part_id is None:
            self.status.setText("Kein Teil ausgewählt.")
            return

        payload = part_edit_payload(self.part_form_values())
        try:
            updated_part = self.client().update_part(part_id, payload)
        except PLMError as exc:
            self.status.setText(f"PLM-Fehler: {exc}")
            return
        except Exception as exc:
            self.status.setText(f"Teil konnte nicht gespeichert werden: {exc}")
            return

        items = self.parts.selectedItems()
        if items:
            items[0].setData(self.QtCore.Qt.UserRole, updated_part)
            items[0].setText(part_label(updated_part))
        self.set_part_form(updated_part)
        self.status.setText(f"Stammdaten gespeichert: {part_label(updated_part)}")

    def show_revision_details(self):
        items = self.revisions.selectedItems()
        if not items:
            self.clear_revision_context()
            return

        revision = items[0].data(self.QtCore.Qt.UserRole)
        if not isinstance(revision, dict):
            self.clear_revision_context()
            return

        self.set_revision_context(revision)

    def save_revision_notes(self):
        revision = self.selected_revision()
        revision_id = revision.get("id") if isinstance(revision, dict) else None
        if revision_id is None:
            self.status.setText("Keine Revision ausgewählt.")
            return

        payload = revision_notes_payload(self.revision_notes.toPlainText())
        try:
            updated_revision = self.client().update_revision_notes(revision_id, payload["notes"])
        except PLMError as exc:
            self.status.setText(f"PLM-Fehler: {exc}")
            return
        except Exception as exc:
            self.status.setText(f"Notizen konnten nicht gespeichert werden: {exc}")
            return

        items = self.revisions.selectedItems()
        if items:
            items[0].setData(self.QtCore.Qt.UserRole, updated_revision)
            items[0].setText(revision_label(updated_revision))
        self.set_revision_context(updated_revision)
        self.status.setText("Revisionsnotizen gespeichert.")

    def revert_revision_notes(self):
        revision = self.selected_revision()
        if not isinstance(revision, dict):
            self.status.setText("Keine Revision ausgewählt.")
            return
        self.revision_notes.setPlainText(revision.get("notes") or "")
        self.status.setText("Revisionsnotizen zurückgesetzt.")

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
            self.status.setText("Teil und Revision auswählen.")
            return

        text, accepted = self.QtWidgets.QInputDialog.getMultiLineText(
            self.widget,
            "Anmerkung",
            "Text",
            "",
        )
        if not accepted:
            self.status.setText("Anmerkung abgebrochen.")
            return

        text = text.strip()
        if not text:
            self.status.setText("Anmerkungstext ist erforderlich.")
            return

        payload = annotation_create_payload(revision_id, text, object_name, subelement)
        try:
            annotation = self.client().create_annotation(part_id, payload)
        except PLMError as exc:
            self.status.setText(f"PLM-Fehler: {exc}")
            return
        except Exception as exc:
            self.status.setText(f"Anmerkung konnte nicht gespeichert werden: {exc}")
            return

        self.refresh_annotations(revision)
        self.status.setText(f"Anmerkung angelegt: {annotation_label(annotation)}")

    def edit_selected_annotation(self):
        annotation = self.selected_annotation()
        annotation_id = annotation.get("id") if isinstance(annotation, dict) else None
        if annotation_id is None:
            self.status.setText("Keine Anmerkung ausgewählt.")
            return

        text, accepted = self.QtWidgets.QInputDialog.getMultiLineText(
            self.widget,
            "Anmerkung bearbeiten",
            "Text",
            annotation.get("text", ""),
        )
        if not accepted:
            self.status.setText("Bearbeiten abgebrochen.")
            return

        payload = annotation_update_payload(text=text)
        if not payload.get("text"):
            self.status.setText("Anmerkungstext ist erforderlich.")
            return
        self.update_selected_annotation(payload, "Anmerkung gespeichert")

    def update_selected_annotation_status(self, status):
        payload = annotation_update_payload(status=status)
        label = "Anmerkung erledigt" if status == "resolved" else "Anmerkung wieder geöffnet"
        self.update_selected_annotation(payload, label)

    def update_selected_annotation(self, payload, success_prefix):
        annotation = self.selected_annotation()
        annotation_id = annotation.get("id") if isinstance(annotation, dict) else None
        if annotation_id is None:
            self.status.setText("Keine Anmerkung ausgewählt.")
            return

        try:
            updated = self.client().update_annotation(annotation_id, payload)
        except PLMError as exc:
            self.status.setText(f"PLM-Fehler: {exc}")
            return
        except Exception as exc:
            self.status.setText(f"Anmerkung konnte nicht gespeichert werden: {exc}")
            return

        revision = self.selected_revision()
        if isinstance(revision, dict):
            self.refresh_annotations(revision)
        self.status.setText(f"{success_prefix}: {annotation_label(updated)}")

    def delete_selected_annotation(self):
        annotation = self.selected_annotation()
        annotation_id = annotation.get("id") if isinstance(annotation, dict) else None
        if annotation_id is None:
            self.status.setText("Keine Anmerkung ausgewählt.")
            return

        answer = self.QtWidgets.QMessageBox.question(
            self.widget,
            "Anmerkung löschen",
            "Ausgewählte Anmerkung wirklich löschen?",
        )
        if answer != self.QtWidgets.QMessageBox.Yes:
            self.status.setText("Löschen abgebrochen.")
            return

        try:
            self.client().delete_annotation(annotation_id)
        except PLMError as exc:
            self.status.setText(f"PLM-Fehler: {exc}")
            return
        except Exception as exc:
            self.status.setText(f"Anmerkung konnte nicht gelöscht werden: {exc}")
            return

        revision = self.selected_revision()
        if isinstance(revision, dict):
            self.refresh_annotations(revision)
        self.status.setText("Anmerkung gelöscht.")

    def open_selected_revision_readonly(self):
        from . import fcstd

        project = self.selected_project()
        revision = self.selected_revision()
        if project is None:
            self.status.setText("Kein Projekt ausgewählt.")
            return
        if revision is None:
            self.status.setText("Keine Revision ausgewählt.")
            return

        revision_id = revision.get("id")
        if revision_id is None:
            self.status.setText("Revision hat keine ID.")
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
                self.status.setText(
                    f"Vorherige read-only Dokumente konnten nicht geschlossen werden: {failed_names}"
                )
                return

            self.status.setText("Lade Manifest und Dateien herunter...")
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
            self.status.setText(f"PLM-Fehler: {exc}")
            return
        except Exception as exc:
            self.status.setText(f"Öffnen fehlgeschlagen: {exc}")
            return

        message = f"Read-only geöffnet: {root_path} ({len(downloaded)} Datei(en))"
        if closed:
            message = f"{message}; vorher geschlossen: {len(closed)}"
        if pruned:
            message = f"{message}; Cache bereinigt: {len(pruned)}"
        self.status.setText(message)

    def checkout_selected_revision(self):
        from . import fcstd

        project = self.selected_project()
        revision = self.selected_revision()
        if project is None:
            self.status.setText("Kein Projekt ausgewählt.")
            return
        if revision is None:
            self.status.setText("Keine Revision ausgewählt.")
            return

        revision_id = revision.get("id")
        if revision_id is None:
            self.status.setText("Revision hat keine ID.")
            return

        project_code = (
            project.get("code")
            or project.get("project_code")
            or f"project-{project.get('id')}"
        )
        workspace_root = self.workspace_root.text().strip()
        server_url = self.server_url.text().strip()

        try:
            closed, failed = fcstd.close_documents(self.readonly_document_names)
            self.readonly_document_names = []
            if failed:
                failed_names = ", ".join(failed)
                self.status.setText(
                    f"Vorherige read-only Dokumente konnten nicht geschlossen werden: {failed_names}"
                )
                return

            self.status.setText("Starte Checkout und lade Dateien herunter...")
            client = self.client()
            response = client.checkout_revision(revision_id, workspace_hint=workspace_root)
            checkout = response.get("checkout") or {}
            checkout_id = (
                checkout.get("id")
                or response.get("checkout_id")
                or response.get("id")
            )
            if checkout_id is None:
                self.status.setText("Checkout-Antwort enthält keine Checkout-ID.")
                return

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
            self.active_checkout_dir = target_dir
            self.active_checkout_root_path = root_path
            touch_directory(target_dir)
            self.update_checkout_controls()
            self.refresh_active_checkouts(client)
        except PLMError as exc:
            self.status.setText(f"PLM-Fehler: {exc}")
            return
        except Exception as exc:
            self.status.setText(f"Checkout fehlgeschlagen: {exc}")
            return

        message = f"Checkout geöffnet: {root_path} ({len(downloaded)} Datei(en))"
        if closed:
            message = f"{message}; read-only geschlossen: {len(closed)}"
        self.status.setText(message)

    def reopen_selected_checkout(self):
        from . import fcstd

        checkout = self.selected_active_checkout()
        if checkout is None:
            self.status.setText("Kein aktiver Checkout ausgewählt.")
            return

        checkout_id = checkout.get("id")
        if checkout_id is None:
            self.status.setText("Aktiver Checkout hat keine ID.")
            return

        active_id = self.active_checkout_id()
        if active_id is not None and active_id != checkout_id:
            self.status.setText("Es ist bereits ein anderer Checkout geöffnet.")
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
                self.status.setText(
                    f"Vorherige read-only Dokumente konnten nicht geschlossen werden: {failed_names}"
                )
                return

            closed_checkout, failed_checkout = fcstd.close_documents(self.checkout_document_names)
            self.checkout_document_names = []
            if failed_checkout:
                failed_names = ", ".join(failed_checkout)
                self.status.setText(
                    f"Vorherige Checkout-Dokumente konnten nicht geschlossen werden: {failed_names}"
                )
                return

            client = self.client()
            self.status.setText("Öffne aktiven Checkout wieder...")
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
            touch_directory(target_dir)
            self.update_checkout_controls()
        except PLMError as exc:
            self.status.setText(f"PLM-Fehler: {exc}")
            return
        except Exception as exc:
            self.status.setText(f"Checkout konnte nicht wieder geöffnet werden: {exc}")
            return

        message = f"Checkout wieder geöffnet: {root_path} ({len(downloaded)} ergänzt)"
        closed = len(closed_readonly) + len(closed_checkout)
        if closed:
            message = f"{message}; vorher geschlossen: {closed}"
        self.status.setText(message)

    def checkin_active_checkout(self):
        from . import fcstd

        checkout_id = self.active_checkout_id()
        if (
            checkout_id is None
            or self.active_checkout_dir is None
            or self.active_checkout_root_path is None
        ):
            self.status.setText("Kein aktiver Checkout.")
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
                    self.status.setText(
                        f"Dokumente konnten nicht gespeichert werden: {failed_names}"
                    )
                    return

            changed_files = technically_changed_manifest_files(
                manifest,
                checkout_metadata,
                self.active_checkout_dir,
            )
            if not changed_files:
                self.offer_cancel_unchanged_checkout(saved_count=len(saved))
                return

            update_changed_files_plm_revisions(changed_files)
            changed_files = technically_changed_manifest_files(
                manifest,
                checkout_metadata,
                self.active_checkout_dir,
            )
            if not changed_files:
                self.offer_cancel_unchanged_checkout(saved_count=len(saved))
                return

            summary, accepted = self.QtWidgets.QInputDialog.getMultiLineText(
                self.widget,
                "Einchecken",
                "Änderungskommentar",
                "",
            )
            if not accepted:
                self.status.setText("Einchecken abgebrochen.")
                return

            change_summary = summary.strip()
            if not change_summary:
                self.status.setText("Änderungskommentar ist erforderlich.")
                return

            self.status.setText("Sende Check-in...")
            response = self.client().checkin_files(
                checkout_id,
                changed_files,
                change_summary,
            )
            if checkin_created_revision_count(response) == 0:
                self.refresh_active_checkouts()
                message = unchanged_checkout_text(saved_count=len(saved))
                result_text = checkin_result_text(response)
                if result_text:
                    message = f"{message} {result_text}"
                self.status.setText(message)
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
            self.status.setText(checkin_conflict_text(exc))
            return
        except PLMError as exc:
            self.status.setText(f"PLM-Fehler: {exc}")
            return
        except Exception as exc:
            self.status.setText(f"Einchecken fehlgeschlagen: {exc}")
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
        self.status.setText(message)

    def offer_cancel_unchanged_checkout(self, saved_count=0):
        answer = self.QtWidgets.QMessageBox.question(
            self.widget,
            "Keine Änderungen",
            "Keine modellrelevanten Änderungen gefunden. Checkout abbrechen?",
        )
        if answer != self.QtWidgets.QMessageBox.Yes:
            self.status.setText(unchanged_checkout_text(saved_count=saved_count))
            return
        self.cancel_active_checkout(confirm=False)

    def cancel_active_checkout(self, confirm=True):
        from . import fcstd

        checkout_id = self.active_checkout_id()
        if checkout_id is None:
            self.status.setText("Kein aktiver Checkout.")
            return

        if confirm:
            answer = self.QtWidgets.QMessageBox.question(
                self.widget,
                "Checkout abbrechen",
                "Aktiven Checkout wirklich abbrechen?",
            )
            if answer != self.QtWidgets.QMessageBox.Yes:
                self.status.setText("Checkout-Abbruch abgebrochen.")
                return

        try:
            self.status.setText("Breche Checkout ab...")
            self.client().cancel_checkout(checkout_id)
            closed, failed = fcstd.close_documents(self.checkout_document_names)
            self.reset_active_checkout()
            self.refresh_active_checkouts()
        except PLMError as exc:
            self.status.setText(f"PLM-Fehler: {exc}")
            return
        except Exception as exc:
            self.status.setText(f"Checkout-Abbruch fehlgeschlagen: {exc}")
            return

        message = "Checkout abgebrochen."
        if closed:
            message = f"{message} Geschlossen: {len(closed)}."
        if failed:
            message = f"{message} Schließen fehlgeschlagen: {', '.join(failed)}."
        self.status.setText(message)


def _find_dock(main_window, QtWidgets):
    return main_window.findChild(QtWidgets.QDockWidget, PANEL_OBJECT_NAME)


def show_panel():
    import FreeCADGui

    global _active_panel

    QtCore, QtWidgets = _load_qt()
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
