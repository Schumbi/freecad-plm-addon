"""Parts, revisions, sources and their edit dialogs."""

from pathlib import Path
import tempfile

from .errors import PLMError
from .panel_helpers import (
    new_part_filename,
    part_edit_payload,
    part_label,
    print_project_label,
    project_edit_payload,
    project_label,
    revision_label,
    revision_workflow_hint,
    revisions_from_part_detail,
)


class PanelPartsMixin:
    def refresh_revisions(self):
        part_item = self.tree_ancestor(self.browser_tree.currentItem(), "part")
        if part_item is None:
            return
        selection = self.tree_selection_key()
        self.load_part_revisions(part_item, force=True)
        self.reveal_active_checkouts()
        self.restore_tree_selection(selection)
        self.update_context_actions()

    def load_part_revisions(self, part_item, force=False):
        if part_item is None:
            return
        if bool(part_item.data(0, self.tree_role(2))) and not force:
            return

        part = self.tree_item_payload(part_item)
        part_id = part.get("id") if isinstance(part, dict) else None
        if part_id is None:
            self.set_status("Teil hat keine ID.")
            return
        self.set_part_form(part)

        self.set_status("Lade Revisionen...")

        try:
            part_detail = self.client().get_part(part_id)
        except PLMError as exc:
            self.set_status(f"PLM-Fehler: {exc}")
            return
        except Exception as exc:
            self.set_status(f"Verbindung fehlgeschlagen: {exc}")
            return

        revisions = revisions_from_part_detail(part_detail)
        detail_part = part_detail.get("part") if isinstance(part_detail, dict) else None
        if isinstance(detail_part, dict):
            part_item.setData(0, int(self.QtCore.Qt.UserRole), detail_part)
            label = part_label(detail_part)
            part_item.setText(0, label)
            part_item.setData(0, self.tree_role(5), label)
            if self.tree_ancestor(self.browser_tree.currentItem(), "part") is part_item:
                self.set_part_form(detail_part)
        self.clear_tree_children(part_item)
        for revision in revisions:
            item = self.add_tree_item(
                part_item,
                "revision",
                revision,
                revision_label(revision),
            )
            item.setToolTip(0, revision_workflow_hint(revision))
        part_item.setData(0, self.tree_role(2), True)
        part_item.setExpanded(True)

        count = len(revisions)
        suffix = "" if count == 1 else "en"
        self.set_status(f"{count} Revision{suffix} geladen.")

    def create_part_dialog(self):
        from . import fcstd

        project = self.selected_project()
        project_id = project.get("id") if isinstance(project, dict) else None
        if project_id is None:
            self.set_status("Kein Projekt ausgewählt.")
            return

        active_checkout_id = self.active_checkout_id()
        active_project = (
            self.active_checkout.get("project")
            if isinstance(self.active_checkout, dict)
            and isinstance(self.active_checkout.get("project"), dict)
            else {}
        )
        active_project_id = active_project.get("id")
        if active_project_id is not None and active_project_id != project_id:
            self.select_project_by_id(active_project_id)
            project = self.selected_project() or active_project
            project_id = project.get("id")
        if active_checkout_id is not None and self.active_checkout_dir is None:
            self.set_status(
                "Bitte den aktiven Checkout zuerst öffnen, bevor ein neues Teil hinzugefügt wird."
            )
            return

        dialog = self.QtWidgets.QDialog(self.widget)
        dialog.setWindowTitle("Neues FreeCAD-Teil")
        layout = self.QtWidgets.QVBoxLayout(dialog)
        intro = self.QtWidgets.QLabel(
            (
                "Das PLM legt Teil und Revision R0001 an und fügt die neue FCStd-Datei "
                "direkt zum aktiven Checkout hinzu."
                if active_checkout_id is not None
                else (
                    "Das PLM legt Teil und Revision R0001 an und öffnet die "
                    "neue FCStd-Datei direkt als Checkout."
                )
            )
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = self.QtWidgets.QFormLayout()
        name_input = self.QtWidgets.QLineEdit()
        name_input.setPlaceholderText("z. B. Klebeschale")
        number_input = self.QtWidgets.QLineEdit()
        number_input.setPlaceholderText("automatisch")
        category_input = self.QtWidgets.QComboBox()
        category_input.addItem("Teil", "part")
        category_input.addItem("Baugruppe", "assembly")
        filename_label = self.QtWidgets.QLabel(new_part_filename(""))
        form.addRow("Name", name_input)
        form.addRow("Teilenummer", number_input)
        form.addRow("Typ", category_input)
        form.addRow("Neue Datei", filename_label)
        layout.addLayout(form)

        buttons = self.QtWidgets.QDialogButtonBox(
            self.QtWidgets.QDialogButtonBox.Ok | self.QtWidgets.QDialogButtonBox.Cancel
        )
        ok_button = buttons.button(self.QtWidgets.QDialogButtonBox.Ok)
        ok_button.setText("Anlegen und öffnen")
        ok_button.setEnabled(False)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        def update_name(value):
            filename_label.setText(new_part_filename(value))
            ok_button.setEnabled(bool(value.strip()))

        name_input.textChanged.connect(update_name)
        name_input.setFocus()

        if dialog.exec_() != self.QtWidgets.QDialog.Accepted:
            self.set_status("Teilanlage abgebrochen.")
            return

        name = name_input.text().strip()
        if not name:
            self.set_status("Name ist erforderlich.")
            return

        category = category_input.itemData(category_input.currentIndex()) or "part"
        filename = new_part_filename(name)
        payload = {
            "number": number_input.text().strip(),
            "name": name,
            "category": category,
        }
        try:
            with tempfile.TemporaryDirectory() as tmp:
                fcstd_path = fcstd.create_empty_document(Path(tmp) / filename, name)
                response = self.client().create_fcstd_part(
                    project_id,
                    payload,
                    fcstd_path,
                    checkout_id=active_checkout_id,
                    workspace_hint=self.workspace_root.text().strip(),
                )
        except PLMError as exc:
            self.set_status(f"PLM-Fehler: {exc}")
            return
        except Exception as exc:
            self.set_status(f"Teil konnte nicht angelegt werden: {exc}")
            return

        part = response.get("part") or {}
        revision = response.get("revision") or {}
        try:
            if active_checkout_id is not None:
                open_result = self.add_checkout_response_to_workspace(response)
                result_text = f"zum Checkout hinzugefügt: {open_result['added_path']}"
            else:
                open_result = self.open_checkout_response_to_workspace(project, response)
                result_text = f"als Checkout geöffnet: {open_result['root_path'].name}"
        except Exception as exc:
            self.refresh_parts()
            self.refresh_active_checkouts()
            self.set_status(
                f"{part_label(part)} und R0001 wurden angelegt, konnten lokal "
                f"aber nicht geöffnet werden: {exc}"
            )
            return

        self.refresh_parts()
        if part.get("id") is not None:
            self.select_part_by_id(part["id"])
        if revision.get("id") is not None:
            self.select_revision_by_id(revision["id"])
        self.set_status(
            f"{part_label(part)} mit R0001 angelegt und {result_text}."
        )

    def add_local_fcstd_part_dialog(self):
        from . import fcstd

        project = self.selected_project()
        project_id = project.get("id") if isinstance(project, dict) else None
        active_checkout_id = self.active_checkout_id()
        active_project = (
            self.active_checkout.get("project")
            if isinstance(self.active_checkout, dict)
            and isinstance(self.active_checkout.get("project"), dict)
            else {}
        )
        active_project_id = active_project.get("id")
        if active_project_id is not None and active_project_id != project_id:
            self.select_project_by_id(active_project_id)
            project = self.selected_project() or active_project
            project_id = project.get("id")
        if project_id is None:
            self.set_status("Kein Projekt ausgewählt.")
            return
        if active_checkout_id is not None and self.active_checkout_dir is None:
            self.set_status(
                "Bitte den aktiven Checkout zuerst öffnen, bevor eine lokale Datei hinzugefügt wird."
            )
            return

        source_name, _selected_filter = self.QtWidgets.QFileDialog.getOpenFileName(
            self.widget,
            "Lokale FreeCAD-Datei zum PLM hinzufügen",
            str(Path.home()),
            "FreeCAD-Dateien (*.FCStd *.fcstd)",
        )
        if not source_name:
            self.set_status("Hinzufügen abgebrochen.")
            return
        source_path = Path(source_name)
        if not source_path.is_file() or source_path.suffix.lower() != ".fcstd":
            self.set_status("Bitte eine vorhandene FCStd-Datei auswählen.")
            return

        open_names = fcstd.document_names_for_path(source_path)
        modified_names = fcstd.modified_document_names(open_names)
        if modified_names:
            self.set_status("Bitte die lokale FCStd-Datei vor dem Hinzufügen speichern.")
            return

        dialog = self.QtWidgets.QDialog(self.widget)
        dialog.setWindowTitle("Lokale FCStd als neues Teil hinzufügen")
        layout = self.QtWidgets.QVBoxLayout(dialog)
        intro = self.QtWidgets.QLabel(
            "Das PLM legt aus der vorhandenen Datei ein neues Teil mit Revision R0001 an"
            + (
                " und nimmt es direkt in den geöffneten Checkout auf."
                if active_checkout_id is not None
                else " und öffnet dafür einen eigenen Checkout."
            )
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        form = self.QtWidgets.QFormLayout()
        name_input = self.QtWidgets.QLineEdit(source_path.stem)
        number_input = self.QtWidgets.QLineEdit()
        number_input.setPlaceholderText("automatisch")
        category_input = self.QtWidgets.QComboBox()
        category_input.addItem("Teil", "part")
        category_input.addItem("Baugruppe", "assembly")
        source_label = self.QtWidgets.QLabel(str(source_path))
        source_label.setWordWrap(True)
        form.addRow("Datei", source_label)
        form.addRow("Name", name_input)
        form.addRow("Teilenummer", number_input)
        form.addRow("Typ", category_input)
        layout.addLayout(form)
        buttons = self.QtWidgets.QDialogButtonBox(
            self.QtWidgets.QDialogButtonBox.Ok | self.QtWidgets.QDialogButtonBox.Cancel
        )
        ok_button = buttons.button(self.QtWidgets.QDialogButtonBox.Ok)
        ok_button.setText("Hinzufügen und öffnen")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec_() != self.QtWidgets.QDialog.Accepted:
            self.set_status("Hinzufügen abgebrochen.")
            return

        name = name_input.text().strip()
        if not name:
            self.set_status("Name ist erforderlich.")
            return
        _closed, failed = fcstd.close_documents(open_names)
        if failed:
            self.set_status(
                f"Lokale Datei konnte nicht geschlossen werden: {', '.join(failed)}"
            )
            return
        payload = {
            "number": number_input.text().strip(),
            "name": name,
            "category": category_input.itemData(category_input.currentIndex()) or "part",
            "source": "addon_local_fcstd",
        }
        try:
            response = self.client().create_fcstd_part(
                project_id,
                payload,
                source_path,
                checkout_id=active_checkout_id,
                workspace_hint=self.workspace_root.text().strip(),
            )
            if active_checkout_id is not None:
                open_result = self.add_checkout_response_to_workspace(response)
                result_text = f"zum Checkout hinzugefügt: {open_result['added_path']}"
            else:
                open_result = self.open_checkout_response_to_workspace(project, response)
                result_text = f"als Checkout geöffnet: {open_result['root_path'].name}"
        except PLMError as exc:
            self.set_status(f"PLM-Fehler: {exc}")
            return
        except Exception as exc:
            self.set_status(f"Lokale FCStd konnte nicht hinzugefügt werden: {exc}")
            return

        part = response.get("part") or {}
        revision = response.get("revision") or {}
        self.refresh_parts()
        if part.get("id") is not None:
            self.select_part_by_id(part["id"])
        if revision.get("id") is not None:
            self.select_revision_by_id(revision["id"])
        self.set_status(f"{part_label(part)} mit R0001 angelegt und {result_text}.")

    def add_selected_revision_to_print_project(self):
        from .slicer import export_revision_manifest_to_stl
        from .workspace import server_slug

        project = self.selected_project()
        part = self.selected_part()
        revision = self.selected_revision()
        if not project or not part or not revision or revision.get("id") is None:
            self.set_status("Projekt, Teil und Revision auswählen.")
            return
        try:
            candidates = [
                item
                for item in self.client().get_print_projects()
                if item.get("project_id") == project.get("id")
                and not any(
                    source.get("revision_id") == revision["id"]
                    for source in item.get("sources") or []
                )
            ]
        except Exception as exc:
            self.set_status(f"Druckprojekte konnten nicht geladen werden: {exc}")
            return
        if not candidates:
            self.set_status("Kein passendes Druckprojekt ohne diese Revision gefunden.")
            return
        labels = [print_project_label(item) for item in candidates]
        selected_label, accepted = self.QtWidgets.QInputDialog.getItem(
            self.widget,
            "Revision zum Druckprojekt hinzufügen",
            "Druckprojekt",
            labels,
            0,
            False,
        )
        if not accepted:
            self.set_status("Hinzufügen zum Druckprojekt abgebrochen.")
            return
        print_project = candidates[labels.index(selected_label)]
        safe_stem = "_".join(
            "".join(char if char.isalnum() or char in "-_." else "_" for char in str(value))
            for value in (
                part.get("number") or part.get("name") or "Teil",
                revision.get("revision_code") or f"revision-{revision['id']}",
            )
        )
        export_dir = (
            Path(self.workspace_root.text().strip()).expanduser()
            / server_slug(self.server_url.text().strip())
            / str(project.get("code") or f"project-{project.get('id')}")
            / "slicer-projects"
            / f"print-project-{print_project['id']}"
            / "source-additions"
        )
        export_path = export_dir / f"{safe_stem}.stl"
        try:
            self.set_status("Erzeuge STL-Übergabedatei für das Druckprojekt...")
            export_revision_manifest_to_stl(
                self.client(),
                revision["id"],
                export_dir / "revision-source",
                export_path,
            )
            self.client().add_print_project_revision_source(
                print_project["id"],
                revision["id"],
                f"{part.get('number', '')} {revision.get('revision_code', '')}".strip(),
            )
        except Exception as exc:
            self.set_status(f"Revision konnte nicht zum Druckprojekt hinzugefügt werden: {exc}")
            return

        self.QtGui.QDesktopServices.openUrl(
            self.QtCore.QUrl.fromLocalFile(str(export_dir))
        )
        self.QtWidgets.QMessageBox.information(
            self.widget,
            "Revision zum Druckprojekt hinzugefügt",
            "Die PLM-Revision ist jetzt als Quelle dokumentiert. Ziehe die erzeugte "
            f"Datei in das geöffnete Slicerprojekt und ordne sie auf der gewünschten Platte an:\n\n{export_path}",
        )
        self.set_status(
            f"Revision als Druckprojekt-Quelle hinzugefügt; STL bereit: {export_path}"
        )

    def save_selected_part(self):
        part = self.selected_part()
        part_id = part.get("id") if isinstance(part, dict) else None
        if part_id is None:
            self.set_status("Kein Teil ausgewählt.")
            return

        payload = part_edit_payload(self.part_form_values())
        try:
            updated_part = self.client().update_part(part_id, payload)
        except PLMError as exc:
            self.set_status(f"PLM-Fehler: {exc}")
            return
        except Exception as exc:
            self.set_status(f"Teil konnte nicht gespeichert werden: {exc}")
            return

        item = self.tree_ancestor(self.browser_tree.currentItem(), "part")
        if item is not None:
            item.setData(0, int(self.QtCore.Qt.UserRole), updated_part)
            label = part_label(updated_part)
            item.setText(0, label)
            item.setData(0, self.tree_role(5), label)
        self.set_part_form(updated_part)
        self.set_status(f"Stammdaten gespeichert: {part_label(updated_part)}")

    def show_project_dialog(self):
        project = self.selected_project()
        project_id = project.get("id") if isinstance(project, dict) else None
        if project_id is None:
            self.set_status("Kein Projekt ausgewählt.")
            return

        dialog = self.QtWidgets.QDialog(self.widget)
        dialog.setWindowTitle("Projekt bearbeiten")
        layout = self.QtWidgets.QVBoxLayout(dialog)
        form = self.QtWidgets.QFormLayout()
        code = self.QtWidgets.QLineEdit(project.get("code", "") or "")
        name = self.QtWidgets.QLineEdit(project.get("name", "") or "")
        status = self.QtWidgets.QComboBox()
        for label, value in (
            ("Laufend", "running"),
            ("Abgeschlossen", "completed"),
            ("Idee", "idea"),
            ("Wichtig", "important"),
            ("Auftrag", "order"),
        ):
            status.addItem(label, value)
        status_value = project.get("status") or "running"
        status_index = status.findData(status_value)
        status.setCurrentIndex(status_index if status_index >= 0 else 0)
        project_date = self.QtWidgets.QLineEdit(project.get("project_date", "") or "")
        project_date.setPlaceholderText("YYYY-MM-DD")
        description = self.QtWidgets.QPlainTextEdit(project.get("description", "") or "")
        description.setMaximumHeight(120)
        form.addRow("Code", code)
        form.addRow("Name", name)
        form.addRow("Status", status)
        form.addRow("Datum", project_date)
        form.addRow("Beschreibung", description)
        layout.addLayout(form)
        buttons = self.QtWidgets.QDialogButtonBox(
            self.QtWidgets.QDialogButtonBox.Ok | self.QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.button(self.QtWidgets.QDialogButtonBox.Ok).setText("Speichern")
        layout.addWidget(buttons)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        if dialog.exec_() != self.QtWidgets.QDialog.Accepted:
            self.set_status("Projektbearbeitung abgebrochen.")
            return

        payload = project_edit_payload(
            {
                "code": code.text(),
                "name": name.text(),
                "status": status.itemData(status.currentIndex()) or "running",
                "project_date": project_date.text(),
                "description": description.toPlainText(),
            }
        )
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

    def show_part_dialog(self):
        part = self.selected_part()
        part_id = part.get("id") if isinstance(part, dict) else None
        if part_id is None:
            self.set_status("Kein Teil ausgewählt.")
            return

        dialog = self.QtWidgets.QDialog(self.widget)
        dialog.setWindowTitle("Teil bearbeiten")
        layout = self.QtWidgets.QVBoxLayout(dialog)
        form = self.QtWidgets.QFormLayout()
        number = self.QtWidgets.QLineEdit(part.get("number", "") or "")
        number.setReadOnly(True)
        name = self.QtWidgets.QLineEdit(part.get("name", "") or "")
        category = self.QtWidgets.QComboBox()
        category.addItem("Teil", "part")
        category.addItem("Baugruppe", "assembly")
        category_index = category.findData(part.get("category") or "part")
        category.setCurrentIndex(category_index if category_index >= 0 else 0)
        description = self.QtWidgets.QPlainTextEdit(part.get("description", "") or "")
        description.setMaximumHeight(100)
        material = self.QtWidgets.QLineEdit(part.get("material", "") or "")
        supplier = self.QtWidgets.QLineEdit(part.get("supplier", "") or "")
        tags = self.QtWidgets.QLineEdit(part.get("tags", "") or "")
        archived = self.QtWidgets.QCheckBox("Archiviert")
        archived.setChecked(bool(part.get("is_archived", False)))
        form.addRow("Nummer", number)
        form.addRow("Name", name)
        form.addRow("Kategorie", category)
        form.addRow("Beschreibung", description)
        form.addRow("Material", material)
        form.addRow("Lieferant", supplier)
        form.addRow("Tags", tags)
        form.addRow("", archived)
        layout.addLayout(form)
        buttons = self.QtWidgets.QDialogButtonBox(
            self.QtWidgets.QDialogButtonBox.Ok | self.QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.button(self.QtWidgets.QDialogButtonBox.Ok).setText("Speichern")
        layout.addWidget(buttons)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        if dialog.exec_() != self.QtWidgets.QDialog.Accepted:
            self.set_status("Teilbearbeitung abgebrochen.")
            return

        payload = part_edit_payload(
            {
                "name": name.text(),
                "category": category.itemData(category.currentIndex()) or "part",
                "description": description.toPlainText(),
                "material": material.text(),
                "supplier": supplier.text(),
                "tags": tags.text(),
                "is_archived": archived.isChecked(),
            }
        )
        try:
            updated_part = self.client().update_part(part_id, payload)
        except PLMError as exc:
            self.set_status(f"PLM-Fehler: {exc}")
            return
        except Exception as exc:
            self.set_status(f"Teil konnte nicht gespeichert werden: {exc}")
            return
        item = self.tree_ancestor(self.browser_tree.currentItem(), "part")
        if item is not None:
            item.setData(0, int(self.QtCore.Qt.UserRole), updated_part)
            label = part_label(updated_part)
            item.setText(0, label)
            item.setData(0, self.tree_role(5), label)
        self.set_part_form(updated_part)
        self.set_status(f"Stammdaten gespeichert: {part_label(updated_part)}")
