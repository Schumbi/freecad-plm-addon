"""Project metadata, imports and project-level refresh."""

from pathlib import Path
import tempfile

from .project_tags import project_tag_names, install_tag_completer
from .errors import PLMError
from .workspace import archive_import_source_dir, build_project_import_zip
from .panel_helpers import (
    import_checkout_candidates,
    import_checkout_followup_text,
    part_label,
    print_freecad_console,
    project_edit_payload,
    project_import_result_text,
    project_label,
    revision_overview_text,
    revision_technical_text,
)


class PanelProjectsMixin:
    def clear_project_form(self):
        self.project_code.setText("")
        self.project_name.setText("")
        self.project_tags.setText("")
        self.project_status.setCurrentIndex(0)
        self.project_date.setText("")
        self.project_description.setPlainText("")
        self.save_project_button.setEnabled(False)

    def set_project_form(self, project):
        self.project_code.setText(project.get("code", "") or "")
        self.project_name.setText(project.get("name", "") or "")
        self.project_tags.setText(", ".join(project_tag_names(project)))
        status = project.get("status") or "running"
        index = self.project_status.findData(status)
        self.project_status.setCurrentIndex(index if index >= 0 else 0)
        self.project_date.setText(project.get("project_date", "") or "")
        self.project_description.setPlainText(project.get("description", "") or "")
        self.save_project_button.setEnabled(project.get("id") is not None)

    def project_form_values(self):
        current_data = getattr(self.project_status, "currentData", None)
        status = current_data() if callable(current_data) else None
        if status is None:
            status = self.project_status.itemData(self.project_status.currentIndex())
        return {
            "code": self.project_code.text(),
            "name": self.project_name.text(),
            "tags": self.project_tags.text(),
            "status": status or "running",
            "project_date": self.project_date.text(),
            "description": self.project_description.toPlainText(),
        }

    def clear_part_form(self):
        self.part_number.setText("")
        self.part_name.setText("")
        self.part_category.setCurrentIndex(0)
        self.part_description.setPlainText("")
        self.part_material.setText("")
        self.part_supplier.setText("")
        self.part_tags.setText("")
        self.part_archived.setChecked(False)
        self.save_part_button.setEnabled(False)

    def set_part_form(self, part):
        self.part_number.setText(part.get("number", "") or "")
        self.part_name.setText(part.get("name", "") or "")
        category = part.get("category") or "part"
        index = self.part_category.findData(category)
        self.part_category.setCurrentIndex(index if index >= 0 else 0)
        self.part_description.setPlainText(part.get("description", "") or "")
        self.part_material.setText(part.get("material", "") or "")
        self.part_supplier.setText(part.get("supplier", "") or "")
        self.part_tags.setText(part.get("tags", "") or "")
        self.part_archived.setChecked(bool(part.get("is_archived", False)))
        self.save_part_button.setEnabled(part.get("id") is not None)

    def part_form_values(self, include_number=False):
        current_data = getattr(self.part_category, "currentData", None)
        category = current_data() if callable(current_data) else None
        if category is None:
            category = self.part_category.itemData(self.part_category.currentIndex())
        values = {
            "name": self.part_name.text(),
            "category": category or "part",
            "description": self.part_description.toPlainText(),
            "material": self.part_material.text(),
            "supplier": self.part_supplier.text(),
            "tags": self.part_tags.text(),
            "is_archived": self.part_archived.isChecked(),
        }
        if include_number:
            values["number"] = self.part_number.text()
        return values

    def set_revision_context(self, revision):
        self.revision_overview.setPlainText(revision_overview_text(revision))
        self.revision_notes.setPlainText(revision.get("notes") or "")
        self.save_revision_notes_button.setEnabled(revision.get("id") is not None)
        self.revert_revision_notes_button.setEnabled(revision.get("id") is not None)
        self.technical_details.setPlainText(revision_technical_text(revision))
        self.new_annotation_button.setEnabled(True)
        self.refresh_annotations(revision)

    def refresh_projects(self):
        from . import config

        server_url = self.server_url.text().strip()
        api_token = self.api_token.text().strip()
        workspace_root = self.workspace_root.text().strip()
        max_fcstd_files = self.cache_max_fcstd_files.value()
        max_projects = self.cache_max_projects.value()
        max_revisions_per_project = self.cache_max_revisions_per_project.value()

        config.set_server_url(server_url)
        config.set_api_token(api_token)
        config.set_workspace_root(workspace_root)
        config.set_cache_max_fcstd_files(max_fcstd_files)
        config.set_cache_max_projects(max_projects)
        config.set_cache_max_revisions_per_project(max_revisions_per_project)
        if not server_url or not api_token:
            self.set_status("Server und API-Token eintragen.")
            return

        self.set_status("Lade Projekte...")
        previous_selection = self.tree_selection_key()
        self.browser_tree.clear()
        self.server_checkouts = []
        self.clear_revision_context()
        self.clear_project_form()
        self.clear_part_form()

        try:
            client = self.client()
            projects = client.get_projects()
        except PLMError as exc:
            self.set_status(f"PLM-Fehler: {exc}")
            return
        except Exception as exc:
            self.set_status(f"Verbindung fehlgeschlagen: {exc}")
            return

        for project in projects:
            item = self.add_tree_item(
                None,
                "project",
                project,
                project_label(project),
                lazy=True,
            )
            item.setToolTip(0, "Aufklappen, um Teile und Baugruppen zu laden.")

        count = len(projects)
        checkout_count = self.refresh_active_checkouts(client)
        restored = self.restore_tree_selection(previous_selection)
        if not restored:
            target_checkout_id = self.active_checkout_id()
            if target_checkout_id not in self.checkout_tree_items and len(self.server_checkouts) == 1:
                target_checkout_id = self.server_checkouts[0].get("id")
            target_item = self.checkout_tree_items.get(target_checkout_id)
            if target_item is not None:
                self.browser_tree.setCurrentItem(target_item)
                self.browser_tree.scrollToItem(target_item)
        self.update_context_actions()
        suffix = "" if count == 1 else "e"
        message = f"{count} Projekt{suffix} geladen."
        if checkout_count is not None:
            message = f"{message} Aktive Checkouts: {checkout_count}."
        self.set_status(message)
        self.set_connected(server_url)
        self.update_project_tag_options()
        if hasattr(self, "project_tags"):
            self.project_tag_completer = install_tag_completer(self.project_tags, self.QtCore,
                self.QtWidgets, [name for p in projects for name in project_tag_names(p)])

    def refresh_parts(self):
        project_item = self.tree_ancestor(self.browser_tree.currentItem(), "project")
        if project_item is None:
            return
        selection = self.tree_selection_key()
        self.load_project_parts(project_item, force=True)
        self.reveal_active_checkouts()
        self.restore_tree_selection(selection)
        self.update_context_actions()

    def load_project_parts(self, project_item, force=False):
        if project_item is None:
            return
        if bool(project_item.data(0, self.tree_role(2))) and not force:
            return

        project = self.tree_item_payload(project_item)
        project_id = project.get("id") if isinstance(project, dict) else None
        if project_id is None:
            self.set_status("Projekt hat keine ID.")
            return
        self.set_status("Lade Teile...")

        try:
            parts = self.client().get_parts(project_id)
        except PLMError as exc:
            self.set_status(f"PLM-Fehler: {exc}")
            return
        except Exception as exc:
            self.set_status(f"Verbindung fehlgeschlagen: {exc}")
            return

        self.clear_tree_children(project_item)
        for part in parts:
            item = self.add_tree_item(
                project_item,
                "part",
                part,
                part_label(part),
                lazy=True,
            )
            item.setToolTip(0, "Aufklappen, um Revisionen zu laden.")
        project_item.setData(0, self.tree_role(2), True)
        project_item.setExpanded(True)

        count = len(parts)
        suffix = "" if count == 1 else "e"
        self.set_status(f"{count} Teil{suffix} geladen.")

    def save_selected_project(self):
        project = self.selected_project()
        project_id = project.get("id") if isinstance(project, dict) else None
        if project_id is None:
            self.set_status("Kein Projekt ausgewählt.")
            return

        payload = project_edit_payload(self.project_form_values())
        try:
            updated_project = self.client().update_project(project_id, payload)
        except PLMError as exc:
            self.set_status(f"PLM-Fehler: {exc}")
            return
        except Exception as exc:
            self.set_status(f"Projekt konnte nicht gespeichert werden: {exc}")
            return

        item = self.tree_ancestor(self.browser_tree.currentItem(), "project")
        if item is not None:
            item.setData(0, int(self.QtCore.Qt.UserRole), updated_project)
            label = project_label(updated_project)
            item.setText(0, label)
            item.setData(0, self.tree_role(5), label)
        self.set_project_form(updated_project)
        self.set_status(f"Projekt gespeichert: {project_label(updated_project)}")
        self.update_project_tag_options()

    def import_project_dialog(self):
        selected_project = self.selected_project()
        dialog = self.QtWidgets.QDialog(self.widget)
        dialog.setWindowTitle("Projekt importieren")
        layout = self.QtWidgets.QVBoxLayout(dialog)

        mode_group = self.QtWidgets.QButtonGroup(dialog)
        new_project_radio = self.QtWidgets.QRadioButton("Neues Projekt")
        existing_project_radio = self.QtWidgets.QRadioButton("Ausgewähltes Projekt")
        mode_group.addButton(new_project_radio)
        mode_group.addButton(existing_project_radio)
        mode_row = self.QtWidgets.QHBoxLayout()
        mode_row.addWidget(new_project_radio)
        mode_row.addWidget(existing_project_radio)
        layout.addLayout(mode_row)

        form = self.QtWidgets.QFormLayout()
        code = self.QtWidgets.QLineEdit()
        name = self.QtWidgets.QLineEdit()
        status = self.QtWidgets.QComboBox()
        status.addItem("Laufend", "running")
        status.addItem("Abgeschlossen", "completed")
        status.addItem("Idee", "idea")
        status.addItem("Wichtig", "important")
        status.addItem("Auftrag", "order")
        project_date = self.QtWidgets.QLineEdit()
        project_date.setPlaceholderText("YYYY-MM-DD")
        description = self.QtWidgets.QPlainTextEdit()
        description.setMaximumHeight(80)
        snapshot_name = self.QtWidgets.QLineEdit()
        snapshot_name.setText("Initial")
        source_dir = self.QtWidgets.QLineEdit()
        browse_button = self.QtWidgets.QPushButton("Ordner wählen")
        source_row = self.QtWidgets.QHBoxLayout()
        source_row.addWidget(source_dir)
        source_row.addWidget(browse_button)
        source_widget = self.QtWidgets.QWidget()
        source_widget.setLayout(source_row)

        try:
            from . import fcstd

            active_path = fcstd.active_document_path()
        except Exception:
            active_path = None
        if active_path:
            source_dir.setText(str(Path(active_path).parent))

        form.addRow("Code", code)
        form.addRow("Name", name)
        form.addRow("Status", status)
        form.addRow("Datum", project_date)
        form.addRow("Beschreibung", description)
        form.addRow("Projektstand", snapshot_name)
        form.addRow("Ordner", source_widget)
        layout.addLayout(form)

        buttons = self.QtWidgets.QDialogButtonBox(
            self.QtWidgets.QDialogButtonBox.Ok | self.QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.button(self.QtWidgets.QDialogButtonBox.Ok).setText("Importieren")
        layout.addWidget(buttons)

        def set_new_project_enabled(enabled):
            for widget in (code, name, status, project_date, description):
                widget.setEnabled(enabled)
            existing_project_radio.setEnabled(selected_project is not None)

        def update_mode():
            set_new_project_enabled(new_project_radio.isChecked())

        def browse():
            chosen = self.QtWidgets.QFileDialog.getExistingDirectory(
                dialog,
                "Projektordner wählen",
                source_dir.text().strip(),
            )
            if chosen:
                source_dir.setText(chosen)

        if selected_project is None:
            new_project_radio.setChecked(True)
        else:
            existing_project_radio.setChecked(True)
        update_mode()
        new_project_radio.toggled.connect(update_mode)
        browse_button.clicked.connect(browse)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)

        if dialog.exec_() != self.QtWidgets.QDialog.Accepted:
            self.set_status("Projektimport abgebrochen.")
            return

        source = source_dir.text().strip()
        if not source:
            self.set_status("Projektordner ist erforderlich.")
            return
        snapshot = snapshot_name.text().strip() or "Initial"

        try:
            with tempfile.TemporaryDirectory() as tmp:
                zip_path = Path(tmp) / "freecad-plm-import.zip"
                paths = build_project_import_zip(source, zip_path)
                client = self.client()
                if new_project_radio.isChecked():
                    project_data = project_edit_payload(
                        {
                            "code": code.text(),
                            "name": name.text(),
                            "status": status.itemData(status.currentIndex()) or "running",
                            "project_date": project_date.text(),
                            "description": description.toPlainText(),
                        }
                    )
                    if not project_data["code"] or not project_data["name"]:
                        self.set_status("Code und Name sind erforderlich.")
                        return
                    result = client.import_project(zip_path, project_data, snapshot)
                else:
                    project_id = selected_project.get("id") if isinstance(selected_project, dict) else None
                    if project_id is None:
                        self.set_status("Kein Projekt ausgewählt.")
                        return
                    result = client.import_project_snapshot(project_id, zip_path, snapshot)
        except PLMError as exc:
            self.set_status(f"PLM-Fehler: {exc}")
            return
        except Exception as exc:
            self.set_status(f"Projektimport fehlgeschlagen: {exc}")
            return

        imported_project = result.get("project") or {}
        imported_project_id = imported_project.get("id")
        followup_message = self.checkout_imported_project_dialog(result, source)
        self.refresh_projects()
        if imported_project_id is not None:
            self.select_project_by_id(imported_project_id)
        message = f"{project_import_result_text(result)} ZIP: {len(paths)} Datei(en)."
        if followup_message:
            message = f"{message} {followup_message}"
        self.set_status(message)

    def checkout_imported_project_dialog(self, import_result, source_dir):
        candidates = import_checkout_candidates(import_result)
        if not candidates:
            return import_checkout_followup_text(import_result)

        answer = self.QtWidgets.QMessageBox.question(
            self.widget,
            "Import abgeschlossen",
            "Soll eine importierte FCStd-Revision jetzt ausgecheckt werden?\n\n"
            "STEP- und STL-Revisionen werden nach der Auswahl schreibgeschützt geöffnet.",
            self.QtWidgets.QMessageBox.Yes | self.QtWidgets.QMessageBox.No,
            self.QtWidgets.QMessageBox.Yes,
        )
        if answer != self.QtWidgets.QMessageBox.Yes:
            return ""

        labels = [candidate["label"] for candidate in candidates]
        label, accepted = self.QtWidgets.QInputDialog.getItem(
            self.widget,
            "Root-Teil auschecken",
            "Importiertes Teil",
            labels,
            0,
            False,
        )
        if not accepted:
            return "Checkout nach Import abgebrochen."

        candidate = candidates[labels.index(label)]
        archive_answer = self.QtWidgets.QMessageBox.question(
            self.widget,
            "Importordner archivieren",
            "Soll der lokale Importordner nach erfolgreichem Checkout ins PLM-Archiv verschoben werden?",
            self.QtWidgets.QMessageBox.Yes | self.QtWidgets.QMessageBox.No,
            self.QtWidgets.QMessageBox.Yes,
        )
        archive_source = archive_answer == self.QtWidgets.QMessageBox.Yes

        project = import_result.get("project") or {}
        revision_id = candidate.get("revision_id")
        snapshot_id = candidate.get("snapshot_id")
        try:
            self.set_status("Starte Checkout des importierten Teils...")
            checkout_result = self.checkout_revision_to_workspace(
                project,
                revision_id,
                snapshot_id=snapshot_id,
            )
        except PLMError as exc:
            return f"Checkout nach Import fehlgeschlagen: {exc}"
        except Exception as exc:
            return f"Checkout nach Import fehlgeschlagen: {exc}"

        print_freecad_console(
            f"FreeCAD-PLM Checkout geöffnet: {checkout_result['root_path']} "
            f"({len(checkout_result['downloaded'])} Datei(en))."
        )
        message = f"Checkout geöffnet ({len(checkout_result['downloaded'])} Datei(en))."
        if archive_source:
            try:
                archived_path = archive_import_source_dir(
                    source_dir,
                    self.workspace_root.text().strip(),
                    self.server_url.text().strip(),
                    project.get("code") or f"project-{project.get('id')}",
                )
            except Exception as exc:
                message = f"{message} Importordner konnte nicht archiviert werden: {exc}"
            else:
                message = f"{message} Importordner archiviert: {archived_path}"
        return message
