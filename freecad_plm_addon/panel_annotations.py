"""Revision details, notes and annotations."""

from .errors import PLMError
from .panel_helpers import (
    annotation_create_payload,
    annotation_label,
    annotation_matches_filter,
    annotation_update_payload,
    annotations_for_revision,
    revision_label,
    revision_notes_payload,
    revision_overview_text,
    revision_technical_text,
)


class PanelAnnotationsMixin:
    def show_revision_details_dialog(self):
        revision = self.selected_revision()
        if not isinstance(revision, dict):
            self.set_status("Keine Revision ausgewählt.")
            return
        dialog = self.QtWidgets.QDialog(self.widget)
        dialog.setWindowTitle("Revisionsdetails")
        layout = self.QtWidgets.QVBoxLayout(dialog)
        tabs = self.QtWidgets.QTabWidget()
        overview = self.QtWidgets.QPlainTextEdit(revision_overview_text(revision))
        overview.setReadOnly(True)
        technical = self.QtWidgets.QPlainTextEdit(revision_technical_text(revision))
        technical.setReadOnly(True)
        tabs.addTab(overview, "Details")
        tabs.addTab(technical, "Technik")
        layout.addWidget(tabs)
        buttons = self.QtWidgets.QDialogButtonBox(self.QtWidgets.QDialogButtonBox.Close)
        layout.addWidget(buttons)
        buttons.rejected.connect(dialog.reject)
        dialog.exec_()

    def show_revision_notes_dialog(self):
        revision = self.selected_revision()
        revision_id = revision.get("id") if isinstance(revision, dict) else None
        if revision_id is None:
            self.set_status("Keine Revision ausgewählt.")
            return
        dialog = self.QtWidgets.QDialog(self.widget)
        dialog.setWindowTitle("Revisionsnotizen")
        layout = self.QtWidgets.QVBoxLayout(dialog)
        notes = self.QtWidgets.QPlainTextEdit(revision.get("notes") or "")
        notes.setMinimumHeight(160)
        layout.addWidget(notes)
        buttons = self.QtWidgets.QDialogButtonBox(
            self.QtWidgets.QDialogButtonBox.Save | self.QtWidgets.QDialogButtonBox.Cancel
        )
        layout.addWidget(buttons)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        if dialog.exec_() != self.QtWidgets.QDialog.Accepted:
            self.set_status("Notizenbearbeitung abgebrochen.")
            return
        payload = revision_notes_payload(notes.toPlainText())
        try:
            updated_revision = self.client().update_revision_notes(revision_id, payload["notes"])
        except PLMError as exc:
            self.set_status(f"PLM-Fehler: {exc}")
            return
        except Exception as exc:
            self.set_status(f"Notizen konnten nicht gespeichert werden: {exc}")
            return
        item = self.browser_tree.currentItem()
        if self.tree_item_kind(item) == "revision":
            item.setData(0, int(self.QtCore.Qt.UserRole), updated_revision)
            label = revision_label(updated_revision)
            item.setText(0, label)
            item.setData(0, self.tree_role(5), label)
            self.update_checkout_controls()
        self.set_revision_context(updated_revision)
        self.set_status("Revisionsnotizen gespeichert.")

    def show_annotations_dialog(self):
        revision = self.selected_revision()
        if not isinstance(revision, dict):
            self.set_status("Keine Revision ausgewählt.")
            return
        dialog = self.QtWidgets.QDialog(self.widget)
        dialog.setWindowTitle("Anmerkungen")
        layout = self.QtWidgets.QVBoxLayout(dialog)
        filter_box = self.QtWidgets.QComboBox()
        for label, value in (
            ("Alle", "all"),
            ("Offen", "open"),
            ("Erledigt", "resolved"),
            ("Nur diese Revision", "revision"),
            ("Teil allgemein", "part"),
        ):
            filter_box.addItem(label, value)
        annotation_list = self.QtWidgets.QListWidget()
        layout.addWidget(filter_box)
        layout.addWidget(annotation_list)
        action_row = self.QtWidgets.QHBoxLayout()
        new_button = self.QtWidgets.QPushButton("Neu")
        edit_button = self.QtWidgets.QPushButton("Bearbeiten")
        resolve_button = self.QtWidgets.QPushButton("Erledigt")
        reopen_button = self.QtWidgets.QPushButton("Wieder öffnen")
        delete_button = self.QtWidgets.QPushButton("Löschen")
        for button in (new_button, edit_button, resolve_button, reopen_button, delete_button):
            action_row.addWidget(button)
        layout.addLayout(action_row)
        close_buttons = self.QtWidgets.QDialogButtonBox(self.QtWidgets.QDialogButtonBox.Close)
        layout.addWidget(close_buttons)

        def selected_dialog_annotation():
            items = annotation_list.selectedItems()
            if not items:
                return None
            annotation = items[0].data(self.QtCore.Qt.UserRole)
            return annotation if isinstance(annotation, dict) else None

        def refill():
            annotation_list.clear()
            filter_key = filter_box.itemData(filter_box.currentIndex()) or "all"
            revision_id = revision.get("id")
            annotations = [
                annotation
                for annotation in self.current_annotations
                if annotation_matches_filter(annotation, filter_key, revision_id)
            ]
            for annotation in annotations:
                item = self.QtWidgets.QListWidgetItem(annotation_label(annotation))
                item.setData(self.QtCore.Qt.UserRole, annotation)
                annotation_list.addItem(item)

        def reload_annotations():
            self.refresh_annotations(revision)
            refill()

        def create():
            self.create_annotation_for_current_revision()
            reload_annotations()

        def edit():
            annotation = selected_dialog_annotation()
            if not annotation:
                self.set_status("Keine Anmerkung ausgewählt.")
                return
            self._edit_annotation(annotation)
            reload_annotations()

        def set_status(status):
            annotation = selected_dialog_annotation()
            if not annotation:
                self.set_status("Keine Anmerkung ausgewählt.")
                return
            self._update_annotation(annotation, annotation_update_payload(status=status))
            reload_annotations()

        def delete():
            annotation = selected_dialog_annotation()
            if not annotation:
                self.set_status("Keine Anmerkung ausgewählt.")
                return
            self._delete_annotation(annotation)
            reload_annotations()

        reload_annotations()
        filter_box.currentIndexChanged.connect(refill)
        new_button.clicked.connect(create)
        edit_button.clicked.connect(edit)
        resolve_button.clicked.connect(lambda: set_status("resolved"))
        reopen_button.clicked.connect(lambda: set_status("open"))
        delete_button.clicked.connect(delete)
        close_buttons.rejected.connect(dialog.reject)
        dialog.exec_()

    def show_revision_details(self):
        revision = self.selected_revision()
        if not isinstance(revision, dict):
            self.clear_revision_context()
            return

        self.set_revision_context(revision)

    def save_revision_notes(self):
        revision = self.selected_revision()
        revision_id = revision.get("id") if isinstance(revision, dict) else None
        if revision_id is None:
            self.set_status("Keine Revision ausgewählt.")
            return

        payload = revision_notes_payload(self.revision_notes.toPlainText())
        try:
            updated_revision = self.client().update_revision_notes(revision_id, payload["notes"])
        except PLMError as exc:
            self.set_status(f"PLM-Fehler: {exc}")
            return
        except Exception as exc:
            self.set_status(f"Notizen konnten nicht gespeichert werden: {exc}")
            return

        item = self.browser_tree.currentItem()
        if self.tree_item_kind(item) == "revision":
            item.setData(0, int(self.QtCore.Qt.UserRole), updated_revision)
            label = revision_label(updated_revision)
            item.setText(0, label)
            item.setData(0, self.tree_role(5), label)
            self.update_checkout_controls()
        self.set_revision_context(updated_revision)
        self.set_status("Revisionsnotizen gespeichert.")

    def revert_revision_notes(self):
        revision = self.selected_revision()
        if not isinstance(revision, dict):
            self.set_status("Keine Revision ausgewählt.")
            return
        self.revision_notes.setPlainText(revision.get("notes") or "")
        self.set_status("Revisionsnotizen zurückgesetzt.")

    def refresh_annotations(self, revision):
        self.current_annotations = []
        self.annotations.clear()
        self.update_annotation_controls()
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

        self.current_annotations = annotations
        self.apply_current_annotation_filter()

    def apply_current_annotation_filter(self, *_args):
        self.annotations.clear()
        revision = self.selected_revision()
        revision_id = revision.get("id") if isinstance(revision, dict) else None
        current_data = getattr(self.annotation_filter, "currentData", None)
        filter_key = current_data() if callable(current_data) else None
        if filter_key is None:
            filter_key = self.annotation_filter.itemData(self.annotation_filter.currentIndex())

        annotations = [
            annotation
            for annotation in self.current_annotations
            if annotation_matches_filter(annotation, filter_key or "all", revision_id)
        ]

        if not annotations:
            message = "Keine Anmerkungen vorhanden."
            if self.current_annotations:
                message = "Keine Anmerkungen für diesen Filter."
            self.annotations.addItem(message)
            self.update_annotation_controls()
            return

        for annotation in annotations:
            item = self.QtWidgets.QListWidgetItem(annotation_label(annotation))
            item.setData(self.QtCore.Qt.UserRole, annotation)
            self.annotations.addItem(item)
        self.update_annotation_controls()

    def create_annotation_for_current_revision(self, object_name="", subelement=""):
        part = self.selected_part()
        revision = self.selected_revision()
        part_id = part.get("id") if isinstance(part, dict) else None
        revision_id = revision.get("id") if isinstance(revision, dict) else None
        if part_id is None or revision_id is None:
            self.set_status("Teil und Revision auswählen.")
            return

        text, accepted = self.QtWidgets.QInputDialog.getMultiLineText(
            self.widget,
            "Anmerkung",
            "Text",
            "",
        )
        if not accepted:
            self.set_status("Anmerkung abgebrochen.")
            return

        text = text.strip()
        if not text:
            self.set_status("Anmerkungstext ist erforderlich.")
            return

        payload = annotation_create_payload(revision_id, text, object_name, subelement)
        try:
            annotation = self.client().create_annotation(part_id, payload)
        except PLMError as exc:
            self.set_status(f"PLM-Fehler: {exc}")
            return
        except Exception as exc:
            self.set_status(f"Anmerkung konnte nicht gespeichert werden: {exc}")
            return

        self.refresh_annotations(revision)
        self.set_status(f"Anmerkung angelegt: {annotation_label(annotation)}")

    def edit_selected_annotation(self):
        annotation = self.selected_annotation()
        self._edit_annotation(annotation)

    def _edit_annotation(self, annotation):
        annotation_id = annotation.get("id") if isinstance(annotation, dict) else None
        if annotation_id is None:
            self.set_status("Keine Anmerkung ausgewählt.")
            return

        text, accepted = self.QtWidgets.QInputDialog.getMultiLineText(
            self.widget,
            "Anmerkung bearbeiten",
            "Text",
            annotation.get("text", ""),
        )
        if not accepted:
            self.set_status("Bearbeiten abgebrochen.")
            return

        payload = annotation_update_payload(text=text)
        if not payload.get("text"):
            self.set_status("Anmerkungstext ist erforderlich.")
            return
        self._update_annotation(annotation, payload, "Anmerkung gespeichert")

    def update_selected_annotation_status(self, status):
        payload = annotation_update_payload(status=status)
        label = "Anmerkung erledigt" if status == "resolved" else "Anmerkung wieder geöffnet"
        self._update_annotation(self.selected_annotation(), payload, label)

    def update_selected_annotation(self, payload, success_prefix):
        self._update_annotation(self.selected_annotation(), payload, success_prefix)

    def _update_annotation(self, annotation, payload, success_prefix="Anmerkung gespeichert"):
        annotation_id = annotation.get("id") if isinstance(annotation, dict) else None
        if annotation_id is None:
            self.set_status("Keine Anmerkung ausgewählt.")
            return

        try:
            updated = self.client().update_annotation(annotation_id, payload)
        except PLMError as exc:
            self.set_status(f"PLM-Fehler: {exc}")
            return
        except Exception as exc:
            self.set_status(f"Anmerkung konnte nicht gespeichert werden: {exc}")
            return

        revision = self.selected_revision()
        if isinstance(revision, dict):
            self.refresh_annotations(revision)
        self.set_status(f"{success_prefix}: {annotation_label(updated)}")

    def delete_selected_annotation(self):
        annotation = self.selected_annotation()
        self._delete_annotation(annotation)

    def _delete_annotation(self, annotation):
        annotation_id = annotation.get("id") if isinstance(annotation, dict) else None
        if annotation_id is None:
            self.set_status("Keine Anmerkung ausgewählt.")
            return

        answer = self.QtWidgets.QMessageBox.question(
            self.widget,
            "Anmerkung löschen",
            "Ausgewählte Anmerkung wirklich löschen?",
        )
        if answer != self.QtWidgets.QMessageBox.Yes:
            self.set_status("Löschen abgebrochen.")
            return

        try:
            self.client().delete_annotation(annotation_id)
        except PLMError as exc:
            self.set_status(f"PLM-Fehler: {exc}")
            return
        except Exception as exc:
            self.set_status(f"Anmerkung konnte nicht gelöscht werden: {exc}")
            return

        revision = self.selected_revision()
        if isinstance(revision, dict):
            self.refresh_annotations(revision)
        self.set_status("Anmerkung gelöscht.")
