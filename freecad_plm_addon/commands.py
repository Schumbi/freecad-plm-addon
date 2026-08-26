from pathlib import Path


ICON_DIR = Path(__file__).resolve().parent / "icons"


def icon_path(filename):
    return str(ICON_DIR / filename)


COMMAND_NAMES = [
    "FreeCADPLM_ActivateConnection",
    "FreeCADPLM_Connect",
    "FreeCADPLM_Refresh",
    "FreeCADPLM_Checkout",
    "FreeCADPLM_Checkin",
    "FreeCADPLM_CancelCheckout",
    "FreeCADPLM_CreateAnnotation",
    "FreeCADPLM_OpenInSlicer",
    "FreeCADPLM_OpenDeepLink",
]


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


class ConnectCommand(BaseCommand):
    menu_text = "Verbinden"
    pixmap = icon_path("connect.svg")

    def Activated(self):
        from .panel import show_panel

        show_panel()


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

    def Activated(self):
        from .panel import refresh_panel

        refresh_panel()


class CheckoutCommand(BaseCommand):
    menu_text = "Auschecken"
    pixmap = "document-open"

    def Activated(self):
        from .panel import checkout_selected_revision

        checkout_selected_revision()


class CheckinCommand(BaseCommand):
    menu_text = "Einchecken"
    pixmap = "document-save"

    def Activated(self):
        from .panel import checkin_active_checkout

        checkin_active_checkout()


class CancelCheckoutCommand(BaseCommand):
    menu_text = "Checkout abbrechen"
    pixmap = "edit-delete"

    def Activated(self):
        from .panel import cancel_active_checkout

        cancel_active_checkout()


class CreateAnnotationCommand(BaseCommand):
    menu_text = "Anmerkung erstellen"
    pixmap = "list-add"

    def Activated(self):
        from .panel import create_annotation_for_selection

        create_annotation_for_selection()


class OpenInSlicerCommand(BaseCommand):
    menu_text = "Im Slicer öffnen"
    tooltip = "Ausgewählte Revision als synchronisiertes 3MF-Slicer-Projekt öffnen"
    pixmap = icon_path("open-slicer.svg")

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


def register_commands():
    import FreeCADGui

    commands = {
        "FreeCADPLM_ActivateConnection": ActivateConnectionCommand(),
        "FreeCADPLM_Connect": ConnectCommand(),
        "FreeCADPLM_Refresh": RefreshCommand(),
        "FreeCADPLM_Checkout": CheckoutCommand(),
        "FreeCADPLM_Checkin": CheckinCommand(),
        "FreeCADPLM_CancelCheckout": CancelCheckoutCommand(),
        "FreeCADPLM_CreateAnnotation": CreateAnnotationCommand(),
        "FreeCADPLM_OpenInSlicer": OpenInSlicerCommand(),
        "FreeCADPLM_OpenDeepLink": OpenDeepLinkCommand(),
    }
    for name, command in commands.items():
        FreeCADGui.addCommand(name, command)
    return list(commands)
