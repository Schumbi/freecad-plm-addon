"""Parts, revisions, sources and their edit dialogs."""

from pathlib import Path
import tempfile

from .errors import PLMError
from .panel_helpers import (
    active_checkout_revision_id,
    new_part_filename,
    part_edit_payload,
    part_label,
    print_project_label,
    project_edit_payload,
    project_label,
    revision_label,
    revision_file_format,
    revision_is_checkout_editable,
    revision_number_sort_key,
    revision_workflow_hint,
    revisions_from_part_detail,
)


class PanelPartsMixin:
    def create_variant_dialog(self):
        from . import fcstd
        from .workspace import document_source_revision

        try:
            source_path = fcstd.active_document_path()
            if source_path is None:
                raise ValueError("Bitte eine PLM-Revision in FreeCAD öffnen.")
            client = self.client()
            document_revision_id, source_dir, local_manifest = document_source_revision(
                source_path, self.workspace_root.text().strip(), self.server_url.text().strip(),
                with_context=True,
            )
            revision_id = document_revision_id
            selected = self.selected_revision() or {}
            local_revision_ids = {item["revision_id"] for item in local_manifest["files"]}
            if selected.get("id") in local_revision_ids:
                revision_id = selected["id"]
            snapshot_id = (local_manifest.get("snapshot") or {}).get("id")
            source_manifest = client.get_revision_manifest(revision_id, snapshot_id=snapshot_id)
            if not any(item["revision_id"] == document_revision_id for item in source_manifest["files"]):
                raise ValueError("Das aktive Dokument gehört nicht zur ausgewählten Ausgangsrevision.")
            revision = client.get_revision(revision_id)
            detail = client.get_part(revision["part_id"])
            source_part = detail["part"]
            if not detail.get("can_create_variant", False):
                raise ValueError("Keine Berechtigung zum Erstellen einer Variante (Serverrechte und Token prüfen).")
            project = client.get_project(source_part["project_id"])
        except Exception as exc:
            self.set_status(f"Variante kann nicht erstellt werden: {exc}")
            return

        dialog = self.QtWidgets.QDialog(self.widget)
        dialog.setWindowTitle("Als neue Variante speichern")
        layout = self.QtWidgets.QVBoxLayout(dialog)
        intro = self.QtWidgets.QLabel(
            f"Ausgang: {part_label(source_part)} · {revision.get('revision_code', '')}\n"
            "Die aktuellen Parameter und verknüpften Dateien werden unabhängig mit Revision R0001 gespeichert."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        form = self.QtWidgets.QFormLayout()
        name = self.QtWidgets.QLineEdit()
        name.setPlaceholderText("z. B. Chipbox – 20 Chips")
        number = self.QtWidgets.QLineEdit()
        number.setPlaceholderText("automatisch")
        form.addRow("Variantenname", name)
        form.addRow("Teilenummer", number)
        layout.addLayout(form)
        buttons = self.QtWidgets.QDialogButtonBox(
            self.QtWidgets.QDialogButtonBox.Ok | self.QtWidgets.QDialogButtonBox.Cancel
        )
        ok_button = buttons.button(self.QtWidgets.QDialogButtonBox.Ok)
        ok_button.setText("Variante speichern und öffnen")
        ok_button.setEnabled(False)
        name.textChanged.connect(lambda value: ok_button.setEnabled(bool(value.strip())))
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        name.setFocus()
        if dialog.exec_() != self.QtWidgets.QDialog.Accepted:
            return
        if not name.text().strip():
            self.set_status("Ein Variantenname ist erforderlich.")
            return
        response = None
        try:
            with tempfile.TemporaryDirectory() as tmp:
                copy_path = fcstd.build_variant_bundle(source_manifest, source_dir, Path(tmp) / "variant.zip")
                response = client.create_variant(
                    project["id"], revision_id,
                    {"name": name.text().strip(), "number": number.text().strip()}, copy_path,
                    workspace_hint=self.workspace_root.text().strip(),
                    source_snapshot_id=snapshot_id,
                )
            self.open_checkout_response_to_workspace(project, response, preserve_readonly=True)
        except Exception as exc:
            if response is not None:
                self.refresh_parts()
                self.refresh_active_checkouts()
                self.set_status(f"Variante wurde gespeichert, konnte aber nicht geöffnet werden: {exc}")
            else:
                self.set_status(f"Variante konnte nicht gespeichert werden: {exc}")
            return
        self.select_project_by_id(project["id"])
        self.refresh_parts()
        self.select_part_by_id(response["part"]["id"])
        self.select_revision_by_id(response["revision"]["id"])
        self.set_status(f"Variante {part_label(response['part'])} mit R0001 gespeichert und geöffnet.")

    def refresh_revisions(self):
        part_item = self.tree_ancestor(self.browser_tree.currentItem(), "part")
        if part_item is None:
            return
        selection = self.tree_selection_key()
        self.load_part_revisions(part_item, force=True)
        self.reveal_active_checkouts()
        self.restore_tree_selection(selection)
        self.update_context_actions()

    def load_part_revisions(self, part_item, force=False, *, background=False, part_detail=None):
        if part_item is None:
            return
        if bool(part_item.data(0, self.tree_role(2))) and not force:
            return

        part = self.tree_item_payload(part_item)
        part_id = part.get("id") if isinstance(part, dict) else None
        if part_id is None:
            self.set_status("Teil hat keine ID.")
            return
        if self.tree_ancestor(self.browser_tree.currentItem(), "part") is part_item:
            self.set_part_form(part)

        if self.tree_ancestor(self.browser_tree.currentItem(), "part") is part_item:
            self.set_status("Lade Revisionen...")

        if background:
            from .background_work import run_gui_work
            generation = getattr(self, "_tree_load_generation", 0) + 1
            self._tree_load_generation = generation
            part_item.setData(0, self.tree_role(8), generation)
            client = self.client()

            def finished(result, error):
                try:
                    current = (part_item.treeWidget() is self.browser_tree
                               and part_item.data(0, self.tree_role(8)) == generation)
                except RuntimeError:
                    current = False
                if not current:
                    return
                if error is not None:
                    self.set_status(f"Revisionen konnten nicht geladen werden: {error}")
                    return
                self.load_part_revisions(part_item, force=True, part_detail=result)

            run_gui_work(self.QtCore, self.widget,
                         lambda: client.get_part(part_id), finished)
            return

        try:
            if part_detail is None:
                cache = getattr(self, "_refresh_part_details", {})
                part_detail = cache[part_id] if isinstance(cache, dict) and part_id in cache else self.client().get_part(part_id)
        except PLMError as exc:
            self.set_status(f"PLM-Fehler: {exc}")
            return
        except Exception as exc:
            self.set_status(f"Verbindung fehlgeschlagen: {exc}")
            return

        revisions = sorted(
            revisions_from_part_detail(part_detail),
            key=revision_number_sort_key,
            reverse=True,
        )
        detail_part = part_detail.get("part") if isinstance(part_detail, dict) else None
        if isinstance(detail_part, dict):
            detail_part["can_create_variant"] = bool(part_detail.get("can_create_variant", False))
            detail_part["variants"] = part_detail.get("variants", [])
            part_item.setData(0, int(self.QtCore.Qt.UserRole), detail_part)
            # Keep the project-tree context (main file or variant name) when
            # refreshing the part payload after selecting its row.
            label = part_item.data(0, self.tree_role(5)) or part_label(detail_part)
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
            item.setHidden(True)
        part_item.setData(0, self.tree_role(7), revisions[0] if revisions else None)
        base_label = part_item.data(0, self.tree_role(5)) or part_item.text(0)
        if revisions:
            part_item.setText(0, f"{base_label} · {revision_label(revisions[0]).split(' · ')[0]}")
            part_item.setToolTip(0, revision_workflow_hint(revisions[0]))
        else:
            part_item.setText(0, base_label)
            part_item.setToolTip(0, "Keine Revision vorhanden.")
        part_item.setData(0, self.tree_role(2), True)
        part_item.setChildIndicatorPolicy(self.QtWidgets.QTreeWidgetItem.DontShowIndicator)
        part_item.setExpanded(False)
        if self.browser_tree.currentItem() is part_item:
            self.browser_selection_changed()

        count = len(revisions)
        suffix = "" if count == 1 else "en"
        if self.tree_ancestor(self.browser_tree.currentItem(), "part") is part_item:
            self.set_status(f"{count} Revision{suffix} geladen.")

    def show_revisions_dialog(self):
        part_item = self.tree_ancestor(self.browser_tree.currentItem(), "part")
        if part_item is None:
            return
        self.load_part_revisions(part_item)
        older_items = [
            part_item.child(index)
            for index in range(1, part_item.childCount())
            if self.tree_item_kind(part_item.child(index)) == "revision"
            and part_item.child(index).data(0, self.tree_role(6)) != "checkout_row"
        ]
        if not older_items:
            self.set_status("Keine älteren Revisionen vorhanden.")
            return

        dialog = self.QtWidgets.QDialog(self.widget)
        dialog.setWindowTitle("Revisionen")
        layout = self.QtWidgets.QVBoxLayout(dialog)
        layout.addWidget(self.QtWidgets.QLabel("Ältere Revision auswählen:"))
        revision_input = self.QtWidgets.QComboBox()
        for item in older_items:
            revision_input.addItem(revision_label(self.tree_item_payload(item) or {}))
        layout.addWidget(revision_input)
        layout.addWidget(self.QtWidgets.QLabel("Aktion:"))
        action_input = self.QtWidgets.QComboBox()
        layout.addWidget(action_input)
        actions = []

        def refresh_actions(_index=None):
            nonlocal actions
            revision = self.tree_item_payload(older_items[revision_input.currentIndex()]) or {}
            actions = []
            active_id = self.active_checkout_id()
            checkout = next(
                (item for item in self.server_checkouts
                 if item.get("part", {}).get("id") == (self.tree_item_payload(part_item) or {}).get("id")
                 and active_checkout_revision_id(item) == revision.get("id")),
                None,
            )
            if checkout:
                actions.append(("Checkout öffnen", self.reopen_selected_checkout))
            elif revision_is_checkout_editable(revision):
                actions.append(("Auschecken", self.checkout_selected_revision))
            actions.append(("Schreibgeschützt öffnen", self.open_selected_revision_readonly))
            active_part = (self.active_checkout or {}).get("part") or {}
            if (
                active_id is not None
                and active_part.get("id") != (self.tree_item_payload(part_item) or {}).get("id")
                and revision_is_checkout_editable(revision)
            ):
                actions.append(("Zum aktiven Checkout hinzufügen", self.add_selected_file_to_active_checkout))
            if revision_file_format(revision) in ("fcstd", "step", "stl"):
                actions.extend((
                    ("Druckprojekt öffnen/erstellen", self.open_selected_revision_in_slicer),
                    ("3MF neu erzeugen", self.rebuild_selected_revision_in_slicer),
                    ("Zum Druckprojekt hinzufügen", self.add_selected_revision_to_print_project),
                ))
            actions.extend((
                ("Details", self.show_revision_details_dialog),
                ("Notizen", self.show_revision_notes_dialog),
                ("Anmerkungen", self.show_annotations_dialog),
            ))
            part = self.tree_item_payload(part_item) or {}
            if revision_file_format(revision) == "fcstd" and part.get("can_create_variant", False):
                actions.append(("Als neue Variante speichern", self.create_variant_dialog))
            if part.get("family"):
                actions.append(("Varianten anzeigen", self.show_variants_dialog))
            action_input.clear()
            for label, _callback in actions:
                action_input.addItem(label)

        revision_input.currentIndexChanged.connect(refresh_actions)
        refresh_actions()
        buttons = self.QtWidgets.QDialogButtonBox(
            self.QtWidgets.QDialogButtonBox.Ok | self.QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.button(self.QtWidgets.QDialogButtonBox.Ok).setText("Ausführen")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec_() != self.QtWidgets.QDialog.Accepted:
            return
        selected_item = older_items[revision_input.currentIndex()]
        selected_checkout = next(
            (checkout for checkout in self.server_checkouts
             if active_checkout_revision_id(checkout) == (self.tree_item_payload(selected_item) or {}).get("id")),
            None,
        )
        if selected_checkout:
            selected_item.setData(0, self.tree_role(3), selected_checkout)
        callback = actions[action_input.currentIndex()][1]
        self._revision_action_override = self.tree_item_payload(selected_item)
        self._checkout_action_override = selected_checkout
        try:
            callback()
        finally:
            self._revision_action_override = None
            self._checkout_action_override = None
            self.update_context_actions()

    def show_variants_dialog(self):
        part = self.selected_part()
        if not part or part.get("id") is None:
            return
        try:
            variants = self.client().get_part(part["id"]).get("variants", [])
        except Exception as exc:
            self.set_status(f"Varianten konnten nicht geladen werden: {exc}")
            return
        if not variants:
            self.set_status("Dieses Teil hat noch keine Variantenfamilie.")
            return
        labels = [part_label(item) for item in variants]
        label, accepted = self.QtWidgets.QInputDialog.getItem(
            self.widget, "Varianten der Teilefamilie", "Variante", labels, 0, False,
        )
        if accepted:
            self.select_part_by_id(variants[labels.index(label)]["id"])

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
