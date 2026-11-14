from pathlib import Path


ICON_DIR = Path(__file__).resolve().parent / "icons"


def icon_path(filename):
    return str(ICON_DIR / filename)


COMMAND_NAMES = [
    "FreeCADPLM_ActivateConnection",
    "FreeCADPLM_Refresh",
    "FreeCADPLM_Checkout",
    "FreeCADPLM_Checkin",
    "FreeCADPLM_CancelCheckout",
    "FreeCADPLM_CreateAnnotation",
    "FreeCADPLM_OpenInSlicer",
    "FreeCADPLM_OpenDeepLink",
    "FreeCADPLM_SetupProtocolHandler",
]


def active_panel():
    from .panel import _active_panel

    return _active_panel


def has_revision_selection():
    panel = active_panel()
    if panel is None:
        return False
    try:
        return panel.selected_revision() is not None
    except Exception:
        return False


def selected_revision_is_editable():
    from .panel_helpers import revision_is_checkout_editable

    panel = active_panel()
    if panel is None:
        return False
    try:
        revision = panel.selected_revision()
        return revision_is_checkout_editable(revision or {})
    except Exception:
        return False


def has_active_checkout():
    panel = active_panel()
    if panel is None:
        return False
    try:
        return panel.active_checkout_id() is not None
    except Exception:
        return False


class BaseCommand:
    menu_text = ""
    tooltip = ""
    pixmap = ""

    def GetResources(self):
        resources = {
            "MenuText": self.menu_text,
            "ToolTip": self.tooltip or self.menu_text,
        }
        if self.pixmap:
            resources["Pixmap"] = self.pixmap
        return resources

    def IsActive(self):
        return True


class ActivateConnectionCommand(BaseCommand):
    menu_text = "PLM-Verbindung aktivieren"
    tooltip = "FreeCAD-PLM Panel öffnen und Projekte laden"
    pixmap = icon_path("activate-connection.svg")

    def Activated(self):
        from .panel import refresh_panel

        refresh_panel()


class RefreshCommand(BaseCommand):
    menu_text = "Aktualisieren"
    pixmap = "view-refresh"

    def IsActive(self):
        panel = active_panel()
        if panel is None:
            return False
        return bool(panel.server_url.text().strip() and panel.api_token.text().strip())

    def Activated(self):
        from .panel import refresh_panel

        refresh_panel()


class CheckoutCommand(BaseCommand):
    menu_text = "Auschecken"
    pixmap = "document-open"

    def IsActive(self):
        return selected_revision_is_editable()

    def Activated(self):
        from .panel import checkout_selected_revision

        checkout_selected_revision()


class CheckinCommand(BaseCommand):
    menu_text = "Einchecken"
    pixmap = "document-save"

    def IsActive(self):
        return has_active_checkout()

    def Activated(self):
        from .panel import checkin_active_checkout

        checkin_active_checkout()


class CancelCheckoutCommand(BaseCommand):
    menu_text = "Checkout verwerfen"
    pixmap = "edit-delete"

    def IsActive(self):
        return has_active_checkout()

    def Activated(self):
        from .panel import cancel_active_checkout

        cancel_active_checkout()


class CreateAnnotationCommand(BaseCommand):
    menu_text = "Anmerkung erstellen"
    pixmap = "list-add"

    def IsActive(self):
        return has_revision_selection()

    def Activated(self):
        from .panel import create_annotation_for_selection

        create_annotation_for_selection()


class OpenInSlicerCommand(BaseCommand):
    menu_text = "Druckprojekt öffnen/erstellen"
    tooltip = "Revision als Druckprojekt öffnen oder anlegen"
    pixmap = icon_path("open-slicer.svg")

    def IsActive(self):
        from .panel_helpers import revision_file_format

        panel = active_panel()
        if panel is None:
            return False
        try:
            revision = panel.selected_revision() or {}
        except Exception:
            return False
        return revision_file_format(revision) in ("fcstd", "step", "stl")

    def Activated(self):
        from .panel import open_selected_revision_in_slicer

        open_selected_revision_in_slicer()


class OpenDeepLinkCommand(BaseCommand):
    menu_text = "PLM-Link öffnen"
    tooltip = "Einen freecad-plm://-Link sicher öffnen"
    pixmap = icon_path("open-deep-link.svg")

    def Activated(self):
        from .panel import prompt_for_revision_deep_link

        prompt_for_revision_deep_link()


class SetupProtocolHandlerCommand(BaseCommand):
    menu_text = "Web-Link-Handler einrichten"
    tooltip = "freecad-plm://-Links für diesen Benutzer registrieren"
    pixmap = icon_path("open-deep-link.svg")

    def Activated(self):
        from .panel import _load_qt
        from .protocol_handler import register_protocol_handler

        result = register_protocol_handler()
        _QtCore, _QtGui, QtWidgets = _load_qt()
        message_box = (
            QtWidgets.QMessageBox.information
            if result.success
            else QtWidgets.QMessageBox.warning
        )
        message_box(
            None,
            "FreeCAD-PLM Web-Link-Handler",
            result.message,
        )


def register_commands():
    import FreeCADGui

    commands = {
        "FreeCADPLM_ActivateConnection": ActivateConnectionCommand(),
        "FreeCADPLM_Refresh": RefreshCommand(),
        "FreeCADPLM_Checkout": CheckoutCommand(),
        "FreeCADPLM_Checkin": CheckinCommand(),
        "FreeCADPLM_CancelCheckout": CancelCheckoutCommand(),
        "FreeCADPLM_CreateAnnotation": CreateAnnotationCommand(),
        "FreeCADPLM_OpenInSlicer": OpenInSlicerCommand(),
        "FreeCADPLM_OpenDeepLink": OpenDeepLinkCommand(),
        "FreeCADPLM_SetupProtocolHandler": SetupProtocolHandlerCommand(),
    }
    for name, command in commands.items():
        FreeCADGui.addCommand(name, command)
    return list(commands)
