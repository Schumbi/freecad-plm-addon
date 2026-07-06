COMMAND_NAMES = [
    "FreeCADPLM_Connect",
    "FreeCADPLM_Refresh",
    "FreeCADPLM_Checkout",
    "FreeCADPLM_Checkin",
    "FreeCADPLM_CancelCheckout",
    "FreeCADPLM_CreateAnnotation",
]


class BaseCommand:
    menu_text = ""
    tooltip = ""

    def GetResources(self):
        return {
            "MenuText": self.menu_text,
            "ToolTip": self.tooltip or self.menu_text,
        }

    def IsActive(self):
        return True


class ConnectCommand(BaseCommand):
    menu_text = "Verbinden"

    def Activated(self):
        from .panel import show_panel

        show_panel()


class RefreshCommand(BaseCommand):
    menu_text = "Aktualisieren"

    def Activated(self):
        from .panel import refresh_panel

        refresh_panel()


class CheckoutCommand(BaseCommand):
    menu_text = "Auschecken"

    def Activated(self):
        from .panel import checkout_selected_revision

        checkout_selected_revision()


class CheckinCommand(BaseCommand):
    menu_text = "Einchecken"

    def Activated(self):
        from .panel import checkin_active_checkout

        checkin_active_checkout()


class CancelCheckoutCommand(BaseCommand):
    menu_text = "Checkout abbrechen"

    def Activated(self):
        from .panel import cancel_active_checkout

        cancel_active_checkout()


class CreateAnnotationCommand(BaseCommand):
    menu_text = "Anmerkung erstellen"

    def Activated(self):
        from .panel import create_annotation_for_selection

        create_annotation_for_selection()


def register_commands():
    import FreeCADGui

    commands = {
        "FreeCADPLM_Connect": ConnectCommand(),
        "FreeCADPLM_Refresh": RefreshCommand(),
        "FreeCADPLM_Checkout": CheckoutCommand(),
        "FreeCADPLM_Checkin": CheckinCommand(),
        "FreeCADPLM_CancelCheckout": CancelCheckoutCommand(),
        "FreeCADPLM_CreateAnnotation": CreateAnnotationCommand(),
    }
    for name, command in commands.items():
        FreeCADGui.addCommand(name, command)
    return list(commands)
