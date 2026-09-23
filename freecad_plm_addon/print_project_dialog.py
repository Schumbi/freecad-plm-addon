"""Explicit print project selection with optional, asynchronously loaded previews."""

from concurrent.futures import ThreadPoolExecutor

from .panel_helpers import print_project_label


def next_print_project_code(projects, project_id, revision_id):
    used = {item["code"] for item in projects if item.get("project_id") == project_id}
    base = f"DP-{revision_id}"
    code, suffix = base, 2
    while code in used:
        code = f"{base}-{suffix}"
        suffix += 1
    return code


def choose_print_project(parent, QtCore, QtGui, QtWidgets, projects, client):
    dialog = QtWidgets.QDialog(parent)
    dialog.setWindowTitle("Druckprojekt öffnen oder erstellen")
    dialog.resize(660, 460)
    layout = QtWidgets.QVBoxLayout(dialog)
    hint = QtWidgets.QLabel("Vorhandenen Slicerstand öffnen oder ein neues Druckprojekt für diese Revision erstellen.")
    hint.setWordWrap(True)
    layout.addWidget(hint)
    listing = QtWidgets.QListWidget()
    listing.setIconSize(QtCore.QSize(128, 96))
    layout.addWidget(listing)
    buttons = QtWidgets.QHBoxLayout()
    create = QtWidgets.QPushButton("Neues Druckprojekt erstellen")
    open_button = QtWidgets.QPushButton("Ausgewähltes öffnen")
    cancel = QtWidgets.QPushButton("Abbrechen")
    for button in (create, open_button, cancel):
        buttons.addWidget(button)
    layout.addLayout(buttons)
    open_button.setEnabled(bool(projects))
    open_button.setDefault(bool(projects))
    create.setDefault(not projects)
    selection = []
    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="plm-preview")
    pending = {}
    for project in projects:
        plate = next((plate for plate in project.get("plates", []) if plate.get("preview_url")), None)
        label = print_project_label(project)
        if plate:
            caption = f"Platte {plate['number']} · Vorschau wird geladen …"
        else:
            caption = "Keine Vorschau vorhanden"
        item = QtWidgets.QListWidgetItem(label + "\n" + caption)
        item.setSizeHint(QtCore.QSize(560, 108))
        listing.addItem(item)
        if plate:
            pending[executor.submit(client.get_print_project_preview, plate["preview_url"])] = (item, label, plate)
    if projects:
        listing.setCurrentRow(0)
    else:
        hint.setText("Für diese Revision gibt es noch kein Druckprojekt. Du kannst jetzt ein neues erstellen.")

    def choose_new():
        selection.append(("new", None))
        dialog.accept()

    def choose_existing(*args):
        row = listing.currentRow()
        if 0 <= row < len(projects):
            selection.append(("existing", projects[row]))
            dialog.accept()

    def update_previews():
        for future in list(pending):
            if not future.done():
                continue
            item, label, plate = pending.pop(future)
            try:
                data = QtCore.QByteArray(future.result())
                buffer = QtCore.QBuffer()
                buffer.setData(data)
                buffer.open(QtCore.QIODevice.ReadOnly)
                reader = QtGui.QImageReader(buffer)
                size = reader.size()
                if not size.isValid() or size.width() * size.height() > 4_000_000:
                    raise ValueError("Ungültige Bildgröße")
                reader.setScaledSize(size.scaled(128, 96, QtCore.Qt.KeepAspectRatio))
                image = reader.read()
                if image.isNull():
                    raise ValueError("Ungültiges Vorschaubild")
                item.setIcon(QtGui.QIcon(QtGui.QPixmap.fromImage(image)))
                item.setText(label + f"\nVorschau: Platte {plate['number']}")
            except Exception:
                item.setText(label + "\nVorschau nicht verfügbar")
        if not pending:
            timer.stop()

    timer = QtCore.QTimer(dialog)
    timer.timeout.connect(update_previews)
    timer.start(100)
    create.clicked.connect(choose_new)
    open_button.clicked.connect(choose_existing)
    listing.itemDoubleClicked.connect(choose_existing)
    cancel.clicked.connect(dialog.reject)
    try:
        dialog.exec_()
        return selection[0] if selection else None
    finally:
        timer.stop()
        executor.shutdown(wait=False, cancel_futures=True)
        dialog.deleteLater()
