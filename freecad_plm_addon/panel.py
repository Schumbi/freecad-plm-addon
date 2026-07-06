from .api_client import PLMClient
from .errors import PLMError


PANEL_OBJECT_NAME = "FreeCADPLMPanel"
_active_panel = None


def project_label(project):
    code = project.get("code") or project.get("project_code") or ""
    name = project.get("name") or project.get("title") or ""
    if code and name:
        return f"{code} - {name}"
    return code or name or f"Projekt {project.get('id', '')}".strip()


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

        layout = self.QtWidgets.QVBoxLayout(self.widget)
        form = self.QtWidgets.QFormLayout()

        self.server_url = self.QtWidgets.QLineEdit(config.get_server_url())
        self.api_token = self.QtWidgets.QLineEdit(config.get_api_token())
        self.api_token.setEchoMode(self.QtWidgets.QLineEdit.Password)
        self.workspace_root = self.QtWidgets.QLineEdit(config.get_workspace_root())

        form.addRow("Server", self.server_url)
        form.addRow("API-Token", self.api_token)
        form.addRow("Workspace", self.workspace_root)
        layout.addLayout(form)

        button_row = self.QtWidgets.QHBoxLayout()
        self.connect_button = self.QtWidgets.QPushButton("Verbinden")
        self.refresh_button = self.QtWidgets.QPushButton("Aktualisieren")
        button_row.addWidget(self.connect_button)
        button_row.addWidget(self.refresh_button)
        layout.addLayout(button_row)

        self.status = self.QtWidgets.QLabel("Nicht verbunden.")
        layout.addWidget(self.status)

        self.projects = self.QtWidgets.QListWidget()
        layout.addWidget(self.projects)

        self.connect_button.clicked.connect(self.refresh_projects)
        self.refresh_button.clicked.connect(self.refresh_projects)

    def refresh_projects(self):
        from . import config

        server_url = self.server_url.text().strip()
        api_token = self.api_token.text().strip()
        workspace_root = self.workspace_root.text().strip()

        config.set_server_url(server_url)
        config.set_api_token(api_token)
        config.set_workspace_root(workspace_root)

        if not server_url or not api_token:
            self.status.setText("Server und API-Token eintragen.")
            return

        self.status.setText("Lade Projekte...")
        self.projects.clear()

        try:
            client = PLMClient(server_url, api_token)
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
