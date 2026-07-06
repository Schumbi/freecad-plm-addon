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


def documents_by_name():
    import FreeCAD

    list_documents = getattr(FreeCAD, "listDocuments", None)
    if list_documents is None:
        return {}
    documents = list_documents() or {}
    return documents if isinstance(documents, dict) else {}


def document_names():
    return set(documents_by_name())


def opened_document_names(before_names, root_document=None):
    names = set(document_names()) - set(before_names)
    root_name = getattr(root_document, "Name", "")
    if root_name:
        names.add(root_name)
    return sorted(names)


def close_documents(names):
    import FreeCAD

    closed = []
    failed = []
    existing = documents_by_name()
    for name in names:
        if name not in existing:
            continue
        try:
            FreeCAD.closeDocument(name)
            closed.append(name)
        except Exception:
            failed.append(name)
    return closed, failed


def open_document(path, recompute=True):
    import FreeCAD

    document = FreeCAD.openDocument(str(path))
    if recompute and document is not None:
        document.recompute()
        try:
            import FreeCADGui

            FreeCADGui.updateGui()
        except Exception:
            pass
    return document


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
