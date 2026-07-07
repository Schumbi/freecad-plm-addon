from pathlib import Path


def active_document_path():
    import FreeCAD

    document = FreeCAD.ActiveDocument
    if document is None or not getattr(document, "FileName", ""):
        return None
    return Path(document.FileName)


def document_path(document):
    if document is None or not getattr(document, "FileName", ""):
        return None
    return Path(document.FileName)


def active_document_name():
    import FreeCAD

    document = FreeCAD.ActiveDocument
    if document is None:
        return ""
    return getattr(document, "Name", "") or ""


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


def save_documents(names):
    saved = []
    failed = []
    existing = documents_by_name()
    for name in names:
        document = existing.get(name)
        if document is None:
            continue
        try:
            document.save()
            saved.append(name)
        except Exception:
            failed.append(name)
    return saved, failed


def document_is_modified(document):
    if document is None:
        return False

    is_modified = getattr(document, "isModified", None)
    if callable(is_modified):
        try:
            return bool(is_modified())
        except Exception:
            return False

    if hasattr(document, "Modified"):
        try:
            return bool(getattr(document, "Modified"))
        except Exception:
            return False

    return False


def _path_is_under(path, root):
    try:
        path = Path(path).resolve()
        root = Path(root).resolve()
    except Exception:
        return False

    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def document_names_in_directory(root):
    root = Path(root)
    existing = documents_by_name()
    return [
        name
        for name, document in existing.items()
        if _path_is_under(document_path(document), root)
    ]


def active_document_name_in_directory(root):
    active_name = active_document_name()
    if not active_name:
        return ""

    existing = documents_by_name()
    document = existing.get(active_name)
    if document is None:
        return ""
    if _path_is_under(document_path(document), root):
        return active_name
    return ""


def modified_document_names(names):
    existing = documents_by_name()
    return [
        name
        for name in names
        if document_is_modified(existing.get(name))
    ]


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
