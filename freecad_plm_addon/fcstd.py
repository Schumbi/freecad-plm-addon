from pathlib import Path


def active_document_path():
    import FreeCAD

    document = FreeCAD.ActiveDocument
    if document is None or not getattr(document, "FileName", ""):
        return None
    return Path(document.FileName)


def save_active_document():
    import FreeCAD

    document = FreeCAD.ActiveDocument
    if document is None:
        return None
    document.save()
    return active_document_path()


def open_document(path):
    import FreeCAD

    return FreeCAD.openDocument(str(path))


def selected_object_name():
    import FreeCADGui

    selection = FreeCADGui.Selection.getSelection()
    if not selection:
        return ""
    return getattr(selection[0], "Name", "")


def selected_subelement_name():
    import FreeCADGui

    selection = FreeCADGui.Selection.getSelectionEx()
    if not selection or not selection[0].SubElementNames:
        return ""
    return selection[0].SubElementNames[0]
