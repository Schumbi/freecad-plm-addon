"""FreeCAD dock widget and stable command entry points."""

# Keep helper names available to existing panel imports.
from .panel_helpers import (
    active_checkout_revision_id,
    annotation_create_payload,
    annotation_label,
    annotation_matches_filter,
    annotation_update_payload,
    annotations_for_revision,
    checkin_completed,
    checkin_conflict_text,
    checkin_created_revision_count,
    checkin_result_text,
    checkout_can_cancel,
    checkout_display_name,
    checkout_file_label,
    checkout_files_signature,
    checkout_guard_action,
    checkout_has_changes,
    checkout_label,
    checkout_primary_button_action,
    checkout_project_code,
    checkout_visual_state,
    compact_revision_summary,
    connection_label,
    context_primary_action,
    format_bytes,
    import_checkout_candidates,
    import_checkout_followup_text,
    new_part_filename,
    part_edit_payload,
    part_label,
    print_freecad_console,
    print_project_label,
    project_edit_payload,
    project_import_result_text,
    project_label,
    response_manifest,
    revision_file_format,
    revision_format_label,
    revision_is_checkout_editable,
    revision_label,
    revision_notes_payload,
    revision_notes_text,
    revision_overview_text,
    revision_primary_action,
    revision_status_label,
    revision_technical_text,
    revision_workflow_hint,
    revisions_from_part_detail,
    save_slicer_settings,
    unchanged_checkout_text,
)
from .panel_state import PanelStateMixin
from .panel_browser import PanelBrowserMixin
from .panel_projects import PanelProjectsMixin
from .panel_parts import PanelPartsMixin
from .panel_annotations import PanelAnnotationsMixin
from .panel_slicer import PanelSlicerMixin
from .panel_checkout import PanelCheckoutMixin


PANEL_OBJECT_NAME = "FreeCADPLMPanel"
_active_panel = None


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


class PLMPanel(PanelStateMixin, PanelBrowserMixin, PanelProjectsMixin, PanelPartsMixin, PanelAnnotationsMixin, PanelSlicerMixin, PanelCheckoutMixin):
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
        self.checkout_change_signature = None
        self.checkout_change_state = True
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
        self.checkout_state_timer = self.QtCore.QTimer(self.widget)
        self.checkout_state_timer.setInterval(1000)
        self.checkout_state_timer.timeout.connect(
            self.refresh_active_checkout_primary_button
        )
        self.checkout_state_timer.start()
        self.update_context_actions()


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
