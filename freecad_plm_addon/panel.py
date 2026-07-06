import json

from .api_client import PLMClient
from .errors import PLMError
from .workspace import (
    download_manifest_files,
    prune_readonly_cache,
    readonly_revision_dir,
    root_file_path,
    touch_directory,
    write_manifest,
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


def annotations_for_revision(annotations, revision_id):
    return [
        annotation
        for annotation in annotations
        if annotation.get("revision_id") in (None, revision_id)
    ]


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

        browser_layout.addWidget(self.QtWidgets.QLabel("Revisionen"))
        self.revisions = self.QtWidgets.QListWidget()
        browser_layout.addWidget(self.revisions)

        details_widget = self.QtWidgets.QWidget()
        details_layout = self.QtWidgets.QVBoxLayout(details_widget)

        self.detail_tabs = self.QtWidgets.QTabWidget()

        self.revision_overview = self.QtWidgets.QPlainTextEdit()
        self.revision_overview.setReadOnly(True)
        self.revision_overview.setPlainText("Keine Revision ausgewählt.")
        self.detail_tabs.addTab(self.revision_overview, "Übersicht")

        self.revision_notes = self.QtWidgets.QPlainTextEdit()
        self.revision_notes.setReadOnly(True)
        self.revision_notes.setPlainText("Keine Revision ausgewählt.")
        self.detail_tabs.addTab(self.revision_notes, "Notizen")

        self.annotations = self.QtWidgets.QListWidget()
        self.detail_tabs.addTab(self.annotations, "Anmerkungen")

        self.technical_details = self.QtWidgets.QPlainTextEdit()
        self.technical_details.setReadOnly(True)
        self.technical_details.setPlainText("Keine Revision ausgewählt.")
        self.detail_tabs.addTab(self.technical_details, "Technik")

        details_layout.addWidget(self.detail_tabs)

        self.open_readonly_button = self.QtWidgets.QPushButton("Read-only öffnen")
        self.open_readonly_button.setEnabled(False)
        details_layout.addWidget(self.open_readonly_button)

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
        self.revisions.itemSelectionChanged.connect(self.show_revision_details)
        self.open_readonly_button.clicked.connect(self.open_selected_revision_readonly)

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

    def clear_revision_context(self):
        self.revision_overview.setPlainText("Keine Revision ausgewählt.")
        self.revision_notes.setPlainText("Keine Revision ausgewählt.")
        self.technical_details.setPlainText("Keine Revision ausgewählt.")
        self.annotations.clear()
        self.open_readonly_button.setEnabled(False)

    def set_revision_context(self, revision):
        self.revision_overview.setPlainText(revision_overview_text(revision))
        self.revision_notes.setPlainText(revision_notes_text(revision))
        self.technical_details.setPlainText(revision_technical_text(revision))
        self.open_readonly_button.setEnabled(True)
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
        self.clear_revision_context()

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
        suffix = "" if count == 1 else "e"
        self.status.setText(f"{count} Projekt{suffix} geladen.")
        self.set_connected(server_url)

    def refresh_parts(self):
        items = self.projects.selectedItems()
        self.parts.clear()
        self.revisions.clear()
        self.clear_revision_context()
        if not items:
            return

        project = items[0].data(self.QtCore.Qt.UserRole)
        project_id = project.get("id") if isinstance(project, dict) else None
        if project_id is None:
            self.status.setText("Projekt hat keine ID.")
            return

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
            return

        part = items[0].data(self.QtCore.Qt.UserRole)
        part_id = part.get("id") if isinstance(part, dict) else None
        if part_id is None:
            self.status.setText("Teil hat keine ID.")
            return

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
        for revision in revisions:
            item = self.QtWidgets.QListWidgetItem(revision_label(revision))
            item.setData(self.QtCore.Qt.UserRole, revision)
            self.revisions.addItem(item)

        count = len(revisions)
        suffix = "" if count == 1 else "en"
        self.status.setText(f"{count} Revision{suffix} geladen.")

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

    def refresh_annotations(self, revision):
        self.annotations.clear()
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

        if not annotations:
            self.annotations.addItem("Keine Anmerkungen vorhanden.")
            return

        for annotation in annotations:
            item = self.QtWidgets.QListWidgetItem(annotation_label(annotation))
            item.setData(self.QtCore.Qt.UserRole, annotation)
            self.annotations.addItem(item)

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

        project_code = project.get("code") or project.get("project_code") or f"project-{project.get('id')}"
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


def checkin_active_checkout():
    show_panel()


def cancel_active_checkout():
    show_panel()


def create_annotation_for_selection():
    show_panel()
