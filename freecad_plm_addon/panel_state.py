"""Connection settings, contextual actions and checkout state."""

from .api_client import PLMClient
from .errors import PLMError
from .workspace import ensure_checkout_metadata, read_manifest
from .panel_helpers import (
    active_checkout_revision_id,
    checkout_can_cancel,
    checkout_files_signature,
    checkout_has_changes,
    checkout_primary_button_action,
    checkout_visual_state,
    compact_revision_summary,
    connection_label,
    context_primary_action,
    part_label,
    print_freecad_console,
    project_label,
    revision_file_format,
    revision_is_checkout_editable,
    save_slicer_settings,
)


class PanelStateMixin:
    def connection_summary_height(self):
        return self.widget.fontMetrics().lineSpacing() + 8

    def set_status(self, message):
        print_freecad_console(message)

    def set_connected(self, server_url):
        self.connection_summary.setText(connection_label(server_url))
        self.refresh_button.setVisible(True)
        self.update_context_actions()

    def run_context_primary_action(self):
        callback = self.context_primary_callback
        if callable(callback):
            callback()

    def invalidate_checkout_change_state(self):
        self.checkout_change_signature = None
        self.checkout_change_state = True

    def active_checkout_has_changes(self):
        from . import fcstd

        if self.active_checkout_dir is None:
            return True
        try:
            manifest = read_manifest(self.active_checkout_dir)
            checkout_metadata = ensure_checkout_metadata(
                manifest,
                self.active_checkout_dir,
            )
            document_names = fcstd.document_names_in_directory(
                self.active_checkout_dir / "files"
            )
            if not document_names:
                document_names = list(self.checkout_document_names)
            modified_names = fcstd.modified_document_names(document_names)
            if modified_names:
                return True

            signature = checkout_files_signature(manifest, self.active_checkout_dir)
            if signature == self.checkout_change_signature:
                return self.checkout_change_state
            state = checkout_has_changes(
                manifest,
                checkout_metadata,
                self.active_checkout_dir,
            )
            self.checkout_change_signature = signature
            self.checkout_change_state = state
            return state
        except Exception:
            # Bei unklarem Zustand niemals einen möglicherweise geänderten
            # Checkout über den primären Button abbrechen.
            return True

    def run_active_checkout_primary_action(self):
        if self.active_checkout_has_changes():
            self.checkin_active_checkout()
        else:
            self.cancel_active_checkout()

    def refresh_active_checkout_primary_button(self):
        item = self.browser_tree.currentItem()
        checkout = self.selected_tree_checkout()
        state = checkout_visual_state(checkout, self.active_checkout_id())
        if self.tree_item_kind(item) != "revision" or state != "local":
            return
        action = checkout_primary_button_action(self.active_checkout_has_changes())
        label = "Einchecken" if action == "checkin" else "Abbrechen"
        if self.context_primary_label == label:
            return
        self.context_primary_button.setText(label)
        self.context_primary_label = label
        self.context_primary_callback = self.run_active_checkout_primary_action

    def set_context_actions(self, summary, primary_label, primary_callback, more_actions):
        self.context_summary.setText(summary)
        self.context_primary_button.setText(primary_label or "Keine Aktion")
        self.context_primary_callback = primary_callback
        self.context_primary_label = primary_label or ""
        self.context_more_actions = list(more_actions)
        self.context_primary_button.setEnabled(callable(primary_callback))
        menu = self.QtWidgets.QMenu(self.context_more_button)
        for label, callback in more_actions:
            if label is None:
                menu.addSeparator()
                continue
            action = menu.addAction(label)
            action.triggered.connect(
                lambda _checked=False, selected_callback=callback: selected_callback()
            )
        self.context_more_button.setMenu(menu)
        self.context_more_button.setEnabled(bool(more_actions))

    def update_context_actions(self):
        item = self.browser_tree.currentItem()
        kind = self.tree_item_kind(item)
        project = self.selected_project()
        part = self.selected_part()
        revision = self.selected_revision()
        checkout = self.selected_tree_checkout()
        primary = context_primary_action(
            kind,
            revision,
            checkout,
            self.active_checkout_id(),
        )
        summary = "Projekt auswählen."
        label = "Projekt importieren"
        callback = (
            self.import_project_dialog
            if self.server_url.text().strip() and self.api_token.text().strip()
            else None
        )
        more = []

        if kind == "project":
            summary = project_label(project or {})
            label = "Neues Teil"
            callback = self.create_part_dialog
            more = [
                ("Lokale FCStd hinzufügen", self.add_local_fcstd_part_dialog),
                ("Projekt importieren", self.import_project_dialog),
                ("Projekt bearbeiten", self.show_project_dialog),
            ]
        elif kind == "part":
            summary = part_label(part or {})
            label = "Teil bearbeiten"
            callback = self.show_part_dialog
            more = [("Revisionen aktualisieren", self.refresh_revisions)]
        elif kind == "checkout_error":
            summary = item.text(0) if item is not None else "Checkout-Fehler"
            label = "Aktualisieren"
            callback = self.refresh_projects
            if checkout_can_cancel(checkout):
                more = [("Checkout abbrechen", self.cancel_selected_checkout)]
        elif kind == "revision":
            summary = compact_revision_summary(revision)
            state = checkout_visual_state(
                checkout,
                self.active_checkout_id(),
                bool(self.tree_item_checkout_error(item)),
            )
            if state == "local":
                summary = f"Checkout lokal · {summary}"
            elif state == "server":
                summary = f"Checkout auf Server · {summary}"
            elif state == "error":
                summary = f"Checkout fehlerhaft · {summary}"

            action_map = {
                "checkout": ("Auschecken", self.checkout_selected_revision),
                "open_readonly": (
                    "Schreibgeschützt öffnen",
                    self.open_selected_revision_readonly,
                ),
                "reopen_checkout": ("Checkout öffnen", self.reopen_selected_checkout),
                "refresh": ("Aktualisieren", self.refresh_projects),
            }
            if primary == "checkin":
                checkout_action = checkout_primary_button_action(
                    self.active_checkout_has_changes()
                )
                label = "Einchecken" if checkout_action == "checkin" else "Abbrechen"
                callback = self.run_active_checkout_primary_action
            else:
                label, callback = action_map.get(primary, ("Keine Aktion", None))
            if state == "local":
                more = [
                    ("Checkout öffnen", self.open_active_checkout_root),
                    ("Lokale FCStd hinzufügen", self.add_local_fcstd_part_dialog),
                    ("Teil hinzufügen", self.choose_revision_for_active_checkout),
                    ("Teil entfernen", self.remove_file_from_active_checkout),
                    (None, None),
                    ("Checkout abbrechen", self.cancel_active_checkout),
                ]
            else:
                if state in ("server", "error") and checkout_can_cancel(checkout):
                    more.append(("Checkout abbrechen", self.cancel_selected_checkout))
                if revision_is_checkout_editable(revision or {}):
                    more.append(("Schreibgeschützt öffnen", self.open_selected_revision_readonly))
                    if (
                        self.active_checkout_id() is not None
                        and revision.get("id") != active_checkout_revision_id(self.active_checkout)
                    ):
                        more.append(
                            ("Zum aktiven Checkout hinzufügen", self.add_selected_file_to_active_checkout)
                        )
            if revision_file_format(revision or {}) in ("fcstd", "step", "stl"):
                more.append(("Druckprojekt öffnen/erstellen", self.open_selected_revision_in_slicer))
                more.append(("3MF neu erzeugen", self.rebuild_selected_revision_in_slicer))
                more.append(("Zum Druckprojekt hinzufügen", self.add_selected_revision_to_print_project))
            more.extend(
                [
                    (None, None),
                    ("Details", self.show_revision_details_dialog),
                    ("Notizen", self.show_revision_notes_dialog),
                    ("Anmerkungen", self.show_annotations_dialog),
                ]
            )
        self.set_context_actions(summary, label, callback, more)

    def client(self):
        return PLMClient(self.server_url.text().strip(), self.api_token.text().strip())

    def show_connection_settings_dialog(self):
        dialog = self.QtWidgets.QDialog(self.widget)
        dialog.setWindowTitle("Verbindungseinstellungen")
        layout = self.QtWidgets.QVBoxLayout(dialog)
        form = self.QtWidgets.QFormLayout()

        server_url = self.QtWidgets.QLineEdit(self.server_url.text())
        api_token = self.QtWidgets.QLineEdit(self.api_token.text())
        api_token.setEchoMode(self.QtWidgets.QLineEdit.Password)
        workspace_root = self.QtWidgets.QLineEdit(self.workspace_root.text())
        cache_max_fcstd_files = self.QtWidgets.QSpinBox()
        cache_max_fcstd_files.setMinimum(self.cache_max_fcstd_files.minimum())
        cache_max_fcstd_files.setMaximum(self.cache_max_fcstd_files.maximum())
        cache_max_fcstd_files.setValue(self.cache_max_fcstd_files.value())
        cache_max_projects = self.QtWidgets.QSpinBox()
        cache_max_projects.setMinimum(self.cache_max_projects.minimum())
        cache_max_projects.setMaximum(self.cache_max_projects.maximum())
        cache_max_projects.setValue(self.cache_max_projects.value())
        cache_max_revisions_per_project = self.QtWidgets.QSpinBox()
        cache_max_revisions_per_project.setMinimum(
            self.cache_max_revisions_per_project.minimum()
        )
        cache_max_revisions_per_project.setMaximum(
            self.cache_max_revisions_per_project.maximum()
        )
        cache_max_revisions_per_project.setValue(
            self.cache_max_revisions_per_project.value()
        )
        slicer_kind = self.QtWidgets.QComboBox()
        slicer_kind.addItem("Automatisch erkennen", "auto")
        slicer_kind.addItem("Bambu Studio", "bambu")
        slicer_kind.addItem("OrcaSlicer", "orca")
        slicer_kind.addItem("Benutzerdefiniert", "custom")
        slicer_kind_index = slicer_kind.findData(self.slicer_kind)
        slicer_kind.setCurrentIndex(slicer_kind_index if slicer_kind_index >= 0 else 0)
        slicer_executable = self.QtWidgets.QLineEdit(self.slicer_executable)
        slicer_executable.setPlaceholderText("Leer lassen für automatische Erkennung")
        slicer_extra_args = self.QtWidgets.QLineEdit(self.slicer_extra_args)
        slicer_extra_args.setPlaceholderText('["--option"]')

        form.addRow("Server", server_url)
        form.addRow("API-Token", api_token)
        form.addRow("Workspace", workspace_root)
        form.addRow("Max. CAD-Dateien", cache_max_fcstd_files)
        form.addRow("Max. Projekte", cache_max_projects)
        form.addRow("Max. Revisionen je Projekt", cache_max_revisions_per_project)
        form.addRow("Slicer", slicer_kind)
        form.addRow("Slicer-Programm", slicer_executable)
        form.addRow("Zusätzliche Argumente", slicer_extra_args)
        layout.addLayout(form)

        buttons = self.QtWidgets.QDialogButtonBox(
            self.QtWidgets.QDialogButtonBox.Ok | self.QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.button(self.QtWidgets.QDialogButtonBox.Ok).setText("Speichern und verbinden")
        layout.addWidget(buttons)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)

        if dialog.exec_() != self.QtWidgets.QDialog.Accepted:
            self.set_status("Verbindungseinstellungen abgebrochen.")
            return

        self.server_url.setText(server_url.text().strip())
        self.api_token.setText(api_token.text().strip())
        self.workspace_root.setText(workspace_root.text().strip())
        self.cache_max_fcstd_files.setValue(cache_max_fcstd_files.value())
        self.cache_max_projects.setValue(cache_max_projects.value())
        self.cache_max_revisions_per_project.setValue(
            cache_max_revisions_per_project.value()
        )
        self.slicer_kind = slicer_kind.itemData(slicer_kind.currentIndex()) or "auto"
        self.slicer_executable = slicer_executable.text().strip()
        self.slicer_extra_args = slicer_extra_args.text().strip() or "[]"
        save_slicer_settings(
            self.slicer_kind,
            self.slicer_executable,
            self.slicer_extra_args,
        )
        self.refresh_projects()

    def update_annotation_controls(self):
        annotation = self.selected_annotation()
        has_annotation = annotation is not None and annotation.get("id") is not None
        self.edit_annotation_button.setEnabled(has_annotation)
        self.delete_annotation_button.setEnabled(has_annotation)
        self.resolve_annotation_button.setEnabled(
            has_annotation and annotation.get("status") != "resolved"
        )
        self.reopen_annotation_button.setEnabled(
            has_annotation and annotation.get("status") == "resolved"
        )

    def update_checkout_controls(self):
        if self.server_checkouts:
            self.reveal_active_checkouts()
        self.update_context_actions()

    def mark_checkout_error(self, checkout_id, message):
        if checkout_id is None:
            return
        self.checkout_errors[checkout_id] = str(message)
        self.update_checkout_controls()

    def clear_checkout_error(self, checkout_id):
        if checkout_id is None:
            return
        self.checkout_errors.pop(checkout_id, None)

    def active_checkout_id(self):
        if not isinstance(self.active_checkout, dict):
            return None
        return self.active_checkout.get("id")

    def reset_active_checkout(self):
        self.active_checkout = None
        self.active_checkout_dir = None
        self.active_checkout_root_path = None
        self.checkout_document_names = []
        self.invalidate_checkout_change_state()
        self.update_checkout_controls()

    def clear_revision_context(self):
        self.revision_overview.setPlainText("Keine Revision ausgewählt.")
        self.revision_notes.setPlainText("Keine Revision ausgewählt.")
        self.save_revision_notes_button.setEnabled(False)
        self.revert_revision_notes_button.setEnabled(False)
        self.technical_details.setPlainText("Keine Revision ausgewählt.")
        self.current_annotations = []
        self.annotations.clear()
        self.new_annotation_button.setEnabled(False)
        self.update_annotation_controls()

    def refresh_active_checkouts(self, client=None):
        try:
            checkouts = (client or self.client()).get_active_checkouts()
        except PLMError as exc:
            self.server_checkouts = []
            self.checkout_tree_items = {}
            self.reset_checkout_tree_markers()
            self.update_context_actions()
            self.set_status(f"PLM-Fehler beim Laden aktiver Checkouts: {exc}")
            return None
        except Exception as exc:
            self.server_checkouts = []
            self.checkout_tree_items = {}
            self.reset_checkout_tree_markers()
            self.update_context_actions()
            self.set_status(f"Aktive Checkouts konnten nicht geladen werden: {exc}")
            return None

        self.server_checkouts = list(checkouts or [])
        active_ids = {
            checkout.get("id")
            for checkout in self.server_checkouts
            if isinstance(checkout, dict) and checkout.get("id") is not None
        }
        self.checkout_errors = {
            checkout_id: message
            for checkout_id, message in self.checkout_errors.items()
            if checkout_id in active_ids
        }
        self.checkout_tree_items = self.reveal_active_checkouts()
        self.update_context_actions()
        return len(checkouts)
