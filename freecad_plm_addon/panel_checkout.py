"""Read-only opening, checkout, check-in and workspace files."""

from .errors import ConflictError, PLMError
from .workspace import (
    build_checkout_metadata,
    checkout_dir,
    delete_checkout_manifest_file,
    download_manifest_files,
    ensure_checkout_manifest_files,
    ensure_checkout_metadata,
    merge_checkout_metadata,
    prune_readonly_cache,
    read_manifest,
    readonly_revision_dir,
    removable_manifest_files,
    root_file_path,
    safe_join,
    technically_changed_manifest_files,
    touch_directory,
    update_changed_files_plm_revisions,
    write_checkout_metadata,
    write_manifest,
)
from .panel_helpers import (
    checkin_completed,
    checkin_conflict_text,
    checkin_created_revision_count,
    checkin_result_text,
    checkout_file_label,
    checkout_guard_action,
    checkout_project_code,
    compact_revision_summary,
    part_label,
    print_freecad_console,
    response_manifest,
    revision_is_checkout_editable,
    unchanged_checkout_text,
)


class PanelCheckoutMixin:
    def open_selected_revision_readonly(self):
        from . import fcstd

        project = self.selected_project()
        revision = self.selected_revision()
        if project is None:
            self.set_status("Kein Projekt ausgewählt.")
            return
        if revision is None:
            self.set_status("Keine Revision ausgewählt.")
            return

        revision_id = revision.get("id")
        if revision_id is None:
            self.set_status("Revision hat keine ID.")
            return

        project_code = (
            project.get("code")
            or project.get("project_code")
            or f"project-{project.get('id')}"
        )
        target_dir = readonly_revision_dir(
            self.workspace_root.text().strip(),
            self.server_url.text().strip(),
            project_code,
            revision_id,
        )

        try:
            closed, failed = fcstd.close_documents(self.readonly_document_names)
            self.readonly_document_names = []
            if failed:
                failed_names = ", ".join(failed)
                self.set_status(
                    f"Vorherige read-only Dokumente konnten nicht geschlossen werden: {failed_names}"
                )
                return

            self.set_status("Lade Manifest und Dateien herunter...")
            manifest = self.client().get_revision_manifest(revision_id)
            write_manifest(target_dir, manifest)
            downloaded = download_manifest_files(self.client(), manifest, target_dir)
            for path in downloaded:
                path.chmod(0o444)
            root_path = root_file_path(manifest, target_dir)
            before_documents = fcstd.document_names()
            document = fcstd.open_document(root_path)
            self.readonly_document_names = fcstd.opened_document_names(before_documents, document)
            touch_directory(target_dir)
            pruned = prune_readonly_cache(
                self.workspace_root.text().strip(),
                self.server_url.text().strip(),
                current_project_code=project_code,
                current_revision_id=revision_id,
                max_fcstd_files=self.cache_max_fcstd_files.value(),
                max_projects=self.cache_max_projects.value(),
                max_revisions_per_project=self.cache_max_revisions_per_project.value(),
            )
        except PLMError as exc:
            self.set_status(f"PLM-Fehler: {exc}")
            return
        except Exception as exc:
            self.set_status(f"Öffnen fehlgeschlagen: {exc}")
            return

        print_freecad_console(
            f"FreeCAD-PLM Read-only geöffnet: {root_path} ({len(downloaded)} Datei(en))"
        )
        message = f"Read-only geöffnet ({len(downloaded)} Datei(en))"
        if closed:
            message = f"{message}; vorher geschlossen: {len(closed)}"
        if pruned:
            message = f"{message}; Cache bereinigt: {len(pruned)}"
        self.set_status(message)

    def checkout_revision_to_workspace(self, project, revision_id, snapshot_id=None):
        response = self.client().checkout_revision(
            revision_id,
            snapshot_id=snapshot_id,
            workspace_hint=self.workspace_root.text().strip(),
        )
        return self.open_checkout_response_to_workspace(project, response)

    def open_checkout_response_to_workspace(self, project, response):
        from . import fcstd

        project_code = (
            project.get("code")
            or project.get("project_code")
            or f"project-{project.get('id')}"
        )
        workspace_root = self.workspace_root.text().strip()
        server_url = self.server_url.text().strip()

        closed, failed = fcstd.close_documents(self.readonly_document_names)
        self.readonly_document_names = []
        if failed:
            failed_names = ", ".join(failed)
            raise RuntimeError(
                f"Vorherige read-only Dokumente konnten nicht geschlossen werden: {failed_names}"
            )

        client = self.client()
        checkout = response.get("checkout") or {}
        checkout_id = (
            checkout.get("id")
            or response.get("checkout_id")
            or response.get("id")
        )
        if checkout_id is None:
            raise RuntimeError("Checkout-Antwort enthält keine Checkout-ID.")

        manifest = response.get("manifest")
        if manifest is None:
            manifest_response = client.get_checkout_manifest(checkout_id)
            manifest = manifest_response.get("manifest", manifest_response)

        target_dir = checkout_dir(workspace_root, server_url, project_code, checkout_id)
        write_manifest(target_dir, manifest)
        downloaded = ensure_checkout_manifest_files(client, manifest, target_dir)
        write_checkout_metadata(target_dir, build_checkout_metadata(manifest, target_dir))
        root_path = root_file_path(manifest, target_dir)

        before_documents = fcstd.document_names()
        document = fcstd.open_document(root_path)
        self.checkout_document_names = fcstd.opened_document_names(before_documents, document)
        self.active_checkout = dict(checkout)
        self.active_checkout.setdefault("id", checkout_id)
        self.active_checkout.setdefault(
            "project",
            {
                "id": project.get("id"),
                "code": project.get("code") or project.get("project_code"),
                "name": project.get("name"),
            },
        )
        self.active_checkout_dir = target_dir
        self.active_checkout_root_path = root_path
        self.invalidate_checkout_change_state()
        self.clear_checkout_error(checkout_id)
        touch_directory(target_dir)
        self.update_checkout_controls()
        self.refresh_active_checkouts(client)
        return {
            "root_path": root_path,
            "downloaded": downloaded,
            "closed_readonly": closed,
            "checkout": self.active_checkout,
        }

    def add_checkout_response_to_workspace(self, response):
        from . import fcstd

        if self.active_checkout_dir is None:
            raise RuntimeError("Aktiver Checkout ist lokal noch nicht geöffnet.")
        current_manifest = read_manifest(self.active_checkout_dir)
        checkout_metadata = ensure_checkout_metadata(
            current_manifest,
            self.active_checkout_dir,
        )
        updated_manifest = response.get("manifest") or {}
        added_file = response.get("added_file") or {}
        added_path = added_file.get("path") or ""
        if not updated_manifest.get("files") or not added_path:
            raise RuntimeError("Server-Antwort enthält keine hinzugefügte Datei.")
        downloaded = ensure_checkout_manifest_files(
            self.client(),
            updated_manifest,
            self.active_checkout_dir,
        )
        write_manifest(self.active_checkout_dir, updated_manifest)
        write_checkout_metadata(
            self.active_checkout_dir,
            merge_checkout_metadata(
                updated_manifest,
                checkout_metadata,
                self.active_checkout_dir,
            ),
        )
        local_path = safe_join(self.active_checkout_dir / "files", added_path)
        before_documents = fcstd.document_names()
        document = fcstd.open_document(local_path)
        opened = fcstd.opened_document_names(before_documents, document)
        self.checkout_document_names = sorted(
            set(self.checkout_document_names).union(opened)
        )
        return {
            "added_path": added_path,
            "downloaded": downloaded,
            "local_path": local_path,
        }

    def checkout_selected_revision(self):
        project = self.selected_project()
        revision = self.selected_revision()
        if project is None:
            self.set_status("Kein Projekt ausgewählt.")
            return
        if revision is None:
            self.set_status("Keine Revision ausgewählt.")
            return
        if not revision_is_checkout_editable(revision):
            self.set_status(
                "Nur FreeCAD-Revisionen können ausgecheckt und bearbeitet werden."
            )
            return

        revision_id = revision.get("id")
        if revision_id is None:
            self.set_status("Revision hat keine ID.")
            return

        action = checkout_guard_action(self.active_checkout, revision)
        if action == "missing_revision":
            self.set_status("Revision hat keine ID.")
            return
        if action == "same_checkout":
            self.open_active_checkout_root()
            return
        if action == "blocked_by_other_checkout":
            conflict_action = self.ask_checkout_conflict_action(revision)
            if conflict_action == "open_active":
                self.open_active_checkout_root()
            elif conflict_action == "checkin":
                self.checkin_active_checkout()
            elif conflict_action == "cancel":
                self.cancel_active_checkout()
            else:
                self.set_status("Checkout nicht gestartet.")
            return

        try:
            self.set_status("Starte Checkout und lade Dateien herunter...")
            result = self.checkout_revision_to_workspace(project, revision_id)
        except ConflictError as exc:
            self.refresh_active_checkouts()
            self.set_status(
                f"Checkout bereits aktiv oder blockiert: {exc}. Aktive Checkouts wurden aktualisiert."
            )
            return
        except PLMError as exc:
            self.set_status(f"PLM-Fehler: {exc}")
            return
        except Exception as exc:
            self.set_status(f"Checkout fehlgeschlagen: {exc}")
            return

        root_path = result["root_path"]
        downloaded = result["downloaded"]
        closed = result["closed_readonly"]
        print_freecad_console(
            f"FreeCAD-PLM Checkout geöffnet: {root_path} ({len(downloaded)} Datei(en))"
        )
        message = f"Checkout geöffnet ({len(downloaded)} Datei(en))"
        if closed:
            message = f"{message}; read-only geschlossen: {len(closed)}"
        self.set_status(message)

    def ask_checkout_conflict_action(self, target_revision):
        box = self.QtWidgets.QMessageBox(self.widget)
        box.setWindowTitle("Aktiver Checkout")
        box.setText(
            "Es ist bereits ein anderer Checkout aktiv.\n\n"
            f"Gewünschte Revision: {compact_revision_summary(target_revision)}"
        )
        open_button = box.addButton("Aktiven Checkout öffnen", self.QtWidgets.QMessageBox.AcceptRole)
        checkin_button = box.addButton("Einchecken", self.QtWidgets.QMessageBox.ActionRole)
        cancel_button = box.addButton("Checkout abbrechen", self.QtWidgets.QMessageBox.DestructiveRole)
        stop_button = box.addButton("Nicht starten", self.QtWidgets.QMessageBox.RejectRole)
        box.setDefaultButton(open_button)
        box.exec_()
        clicked = box.clickedButton()
        if clicked == open_button:
            return "open_active"
        if clicked == checkin_button:
            return "checkin"
        if clicked == cancel_button:
            return "cancel"
        if clicked == stop_button:
            return "stop"
        return "stop"

    def open_active_checkout_root(self):
        from . import fcstd

        if self.active_checkout_root_path is None:
            message = "Aktiver Checkout ist lokal noch nicht geöffnet."
            self.mark_checkout_error(self.active_checkout_id(), message)
            self.set_status(message)
            return
        try:
            before_documents = fcstd.document_names()
            document = fcstd.open_document(self.active_checkout_root_path)
            opened = fcstd.opened_document_names(before_documents, document)
            if opened:
                self.checkout_document_names = opened
        except Exception as exc:
            message = f"Aktiver Checkout konnte nicht geöffnet werden: {exc}"
            self.mark_checkout_error(self.active_checkout_id(), message)
            self.set_status(message)
            return
        self.clear_checkout_error(self.active_checkout_id())
        self.update_checkout_controls()
        print_freecad_console(
            f"FreeCAD-PLM aktiver Checkout geöffnet: {self.active_checkout_root_path}"
        )
        self.set_status("Aktiver Checkout geöffnet.")

    def reopen_selected_checkout(self):
        from . import fcstd

        checkout = self.selected_active_checkout() or self.active_checkout
        if checkout is None:
            self.set_status("Kein aktiver Checkout ausgewählt.")
            return

        checkout_id = checkout.get("id")
        if checkout_id is None:
            self.set_status("Aktiver Checkout hat keine ID.")
            return

        active_id = self.active_checkout_id()
        if active_id is not None and active_id != checkout_id:
            self.set_status("Es ist bereits ein anderer Checkout geöffnet.")
            return
        if active_id == checkout_id and self.active_checkout_root_path is not None:
            self.open_active_checkout_root()
            return

        workspace_root = self.workspace_root.text().strip()
        server_url = self.server_url.text().strip()
        project_code = checkout_project_code(checkout)
        target_dir = checkout_dir(workspace_root, server_url, project_code, checkout_id)

        try:
            closed_readonly, failed_readonly = fcstd.close_documents(self.readonly_document_names)
            self.readonly_document_names = []
            if failed_readonly:
                failed_names = ", ".join(failed_readonly)
                message = (
                    "Vorherige read-only Dokumente konnten nicht geschlossen werden: "
                    f"{failed_names}"
                )
                self.mark_checkout_error(checkout_id, message)
                self.set_status(message)
                return

            closed_checkout, failed_checkout = fcstd.close_documents(self.checkout_document_names)
            self.checkout_document_names = []
            if failed_checkout:
                failed_names = ", ".join(failed_checkout)
                message = (
                    "Vorherige Checkout-Dokumente konnten nicht geschlossen werden: "
                    f"{failed_names}"
                )
                self.mark_checkout_error(checkout_id, message)
                self.set_status(message)
                return

            client = self.client()
            self.set_status("Öffne aktiven Checkout wieder...")
            manifest = response_manifest(checkout.get("manifest"))
            if manifest is None:
                manifest = response_manifest(client.get_checkout_manifest(checkout_id))
            write_manifest(target_dir, manifest)
            downloaded = ensure_checkout_manifest_files(client, manifest, target_dir)
            ensure_checkout_metadata(manifest, target_dir)
            root_path = root_file_path(manifest, target_dir)

            before_documents = fcstd.document_names()
            document = fcstd.open_document(root_path)
            self.checkout_document_names = fcstd.opened_document_names(before_documents, document)
            self.active_checkout = dict(checkout)
            self.active_checkout.setdefault("id", checkout_id)
            self.active_checkout_dir = target_dir
            self.active_checkout_root_path = root_path
            self.invalidate_checkout_change_state()
            self.clear_checkout_error(checkout_id)
            touch_directory(target_dir)
            self.update_checkout_controls()
        except PLMError as exc:
            message = f"PLM-Fehler: {exc}"
            self.mark_checkout_error(checkout_id, message)
            self.set_status(message)
            return
        except Exception as exc:
            message = f"Checkout konnte nicht wieder geöffnet werden: {exc}"
            self.mark_checkout_error(checkout_id, message)
            self.set_status(message)
            return

        print_freecad_console(
            f"FreeCAD-PLM Checkout wieder geöffnet: {root_path} ({len(downloaded)} ergänzt)"
        )
        message = f"Checkout wieder geöffnet ({len(downloaded)} ergänzt)"
        closed = len(closed_readonly) + len(closed_checkout)
        if closed:
            message = f"{message}; vorher geschlossen: {closed}"
        self.set_status(message)

    def checkin_active_checkout(self):
        from . import fcstd

        checkout_id = self.active_checkout_id()
        if (
            checkout_id is None
            or self.active_checkout_dir is None
            or self.active_checkout_root_path is None
        ):
            self.set_status("Kein aktiver Checkout.")
            return

        saved = []
        closed = []
        close_failed = []
        try:
            manifest = read_manifest(self.active_checkout_dir)
            checkout_metadata = ensure_checkout_metadata(manifest, self.active_checkout_dir)
            checkout_document_names = fcstd.document_names_in_directory(
                self.active_checkout_dir / "files"
            )
            if not checkout_document_names:
                checkout_document_names = list(self.checkout_document_names)
            if checkout_document_names:
                saved, failed = fcstd.save_documents(checkout_document_names)
                if failed:
                    failed_names = ", ".join(failed)
                    self.set_status(
                        f"Dokumente konnten nicht gespeichert werden: {failed_names}"
                    )
                    return

            changed_files = technically_changed_manifest_files(
                manifest,
                checkout_metadata,
                self.active_checkout_dir,
            )
            has_structural_changes = bool(
                manifest.get("removed_paths") or manifest.get("added_paths")
            )
            if not changed_files and not has_structural_changes:
                self.offer_cancel_unchanged_checkout(saved_count=len(saved))
                return

            update_changed_files_plm_revisions(changed_files)
            changed_files = technically_changed_manifest_files(
                manifest,
                checkout_metadata,
                self.active_checkout_dir,
            )
            if not changed_files and not has_structural_changes:
                self.offer_cancel_unchanged_checkout(saved_count=len(saved))
                return

            summary, accepted = self.QtWidgets.QInputDialog.getMultiLineText(
                self.widget,
                "Einchecken",
                "Änderungskommentar",
                "",
            )
            if not accepted:
                self.set_status("Einchecken abgebrochen.")
                return

            change_summary = summary.strip()
            if not change_summary:
                self.set_status("Änderungskommentar ist erforderlich.")
                return

            self.set_status("Sende Check-in...")
            response = self.client().checkin_files(
                checkout_id,
                changed_files,
                change_summary,
            )
            if checkin_created_revision_count(response) == 0 and not checkin_completed(response):
                self.refresh_active_checkouts()
                message = unchanged_checkout_text(saved_count=len(saved))
                result_text = checkin_result_text(response)
                if result_text:
                    message = f"{message} {result_text}"
                self.set_status(message)
                return

            closed, close_failed = fcstd.close_documents(self.checkout_document_names)
            self.reset_active_checkout()
            self.refresh_revisions()
            revision = response.get("revision") if isinstance(response, dict) else None
            if isinstance(revision, dict) and revision.get("id") is not None:
                self.select_revision_by_id(revision["id"])
            self.refresh_active_checkouts()
        except ConflictError as exc:
            self.refresh_active_checkouts()
            self.set_status(checkin_conflict_text(exc))
            return
        except PLMError as exc:
            self.set_status(f"PLM-Fehler: {exc}")
            return
        except Exception as exc:
            self.set_status(f"Einchecken fehlgeschlagen: {exc}")
            return

        message = "Check-in abgeschlossen."
        result_text = checkin_result_text(response)
        if result_text:
            message = f"{message} {result_text}"
        message = f"{message} Geänderte Dateien: {len(changed_files)}."
        if saved:
            message = f"{message} Gespeichert: {len(saved)}."
        if closed:
            message = f"{message} Geschlossen: {len(closed)}."
        if close_failed:
            message = f"{message} Schließen fehlgeschlagen: {', '.join(close_failed)}."
        self.set_status(message)

    def add_selected_file_to_active_checkout(self):
        checkout_id = self.active_checkout_id()
        revision = self.selected_revision()
        revision_id = revision.get("id") if isinstance(revision, dict) else None
        if checkout_id is None or self.active_checkout_dir is None:
            self.set_status("Kein aktiver Checkout.")
            return
        if revision_id is None:
            self.set_status("Bitte die hinzuzufügende Revision auswählen.")
            return

        answer = self.QtWidgets.QMessageBox.question(
            self.widget,
            "Teil zum Checkout hinzufügen",
            (
                f"{compact_revision_summary(revision)} zum aktiven Checkout hinzufügen?\n\n"
                "Die Datei wird in den Checkout-Ordner geladen und in FreeCAD geöffnet."
            ),
            self.QtWidgets.QMessageBox.Yes | self.QtWidgets.QMessageBox.No,
            self.QtWidgets.QMessageBox.Yes,
        )
        if answer != self.QtWidgets.QMessageBox.Yes:
            self.set_status("Hinzufügen abgebrochen.")
            return

        try:
            response = self.client().add_checkout_file(checkout_id, revision_id)
            result = self.add_checkout_response_to_workspace(response)
        except PLMError as exc:
            self.set_status(f"PLM-Fehler: {exc}")
            return
        except Exception as exc:
            self.set_status(f"Teil konnte nicht hinzugefügt werden: {exc}")
            return

        self.set_status(
            f"{result['added_path']} wurde hinzugefügt, geladen und in FreeCAD geöffnet "
            f"({len(result['downloaded'])} neue Datei(en))."
        )

    def choose_revision_for_active_checkout(self):
        checkout_id = self.active_checkout_id()
        if checkout_id is None or self.active_checkout_dir is None:
            self.set_status("Kein lokal geöffneter Checkout.")
            return

        project = self.active_checkout.get("project") or {}
        project_item = self.find_tree_item("project", project.get("id"))
        if project_item is None:
            self.set_status("Projekt des aktiven Checkouts wurde nicht gefunden.")
            return

        self.load_project_parts(project_item)
        existing_revision_ids = set()
        try:
            manifest = read_manifest(self.active_checkout_dir)
            existing_revision_ids = {
                entry.get("revision_id")
                for entry in manifest.get("files") or []
                if entry.get("revision_id") is not None
            }
        except Exception:
            pass

        candidates = []
        for part_index in range(project_item.childCount()):
            part_item = project_item.child(part_index)
            if self.tree_item_kind(part_item) != "part":
                continue
            self.load_part_revisions(part_item)
            part = self.tree_item_payload(part_item) or {}
            for revision_index in range(part_item.childCount()):
                revision_item = part_item.child(revision_index)
                revision = self.tree_item_payload(revision_item) or {}
                revision_id = revision.get("id")
                if (
                    self.tree_item_kind(revision_item) != "revision"
                    or not revision_is_checkout_editable(revision)
                    or revision_id in existing_revision_ids
                ):
                    continue
                label = (
                    f"{part_label(part)} · {compact_revision_summary(revision)} "
                    f"[ID {revision_id}]"
                )
                candidates.append((label, revision_item))

        self.reveal_active_checkouts()
        if not candidates:
            self.set_status("Keine weitere FCStd-Revision zum Hinzufügen gefunden.")
            return

        label, accepted = self.QtWidgets.QInputDialog.getItem(
            self.widget,
            "Teil zum Checkout hinzufügen",
            "Revision",
            [candidate[0] for candidate in candidates],
            0,
            False,
        )
        if not accepted:
            self.set_status("Hinzufügen abgebrochen.")
            return

        selected_item = dict(candidates).get(label)
        if selected_item is None:
            self.set_status("Ausgewählte Revision wurde nicht gefunden.")
            return
        self.browser_tree.setCurrentItem(selected_item)
        self.browser_tree.scrollToItem(selected_item)
        self.add_selected_file_to_active_checkout()

    def remove_file_from_active_checkout(self):
        from . import fcstd

        checkout_id = self.active_checkout_id()
        if checkout_id is None or self.active_checkout_dir is None:
            self.set_status("Kein aktiver Checkout.")
            return

        try:
            manifest = read_manifest(self.active_checkout_dir)
            checkout_metadata = ensure_checkout_metadata(manifest, self.active_checkout_dir)
        except Exception as exc:
            self.set_status(f"Checkout-Manifest konnte nicht gelesen werden: {exc}")
            return

        candidates = removable_manifest_files(manifest)
        if not candidates:
            self.set_status("Der Checkout enthält kein entfernbares Teil.")
            return

        labels = [checkout_file_label(item) for item in candidates]
        label, accepted = self.QtWidgets.QInputDialog.getItem(
            self.widget,
            "Teil aus Checkout entfernen",
            "Teil",
            labels,
            0,
            False,
        )
        if not accepted:
            self.set_status("Entfernen abgebrochen.")
            return

        item = candidates[labels.index(label)]
        path = item.get("path") or ""
        local_path = safe_join(self.active_checkout_dir / "files", path)
        document_names = fcstd.document_names_for_path(local_path)
        modified_names = fcstd.modified_document_names(document_names)
        warning = (
            f"{path} aus diesem Checkout entfernen?\n\n"
            "Die gespeicherte Revision und der Teilestammsatz bleiben im PLM erhalten. "
            "Beim Einchecken wird ein neuer Projektstand ohne diese Datei erzeugt."
        )
        if modified_names:
            warning += "\n\nNicht gespeicherte lokale Änderungen werden verworfen."
        answer = self.QtWidgets.QMessageBox.question(
            self.widget,
            "Teil entfernen",
            warning,
            self.QtWidgets.QMessageBox.Yes | self.QtWidgets.QMessageBox.No,
            self.QtWidgets.QMessageBox.No,
        )
        if answer != self.QtWidgets.QMessageBox.Yes:
            self.set_status("Entfernen abgebrochen.")
            return

        closed, failed = fcstd.close_documents(document_names)
        if failed:
            self.set_status(f"Teil konnte nicht geschlossen werden: {', '.join(failed)}")
            return

        try:
            response = self.client().remove_checkout_file(checkout_id, path)
            updated_manifest = response.get("manifest") or {}
            if not updated_manifest.get("files"):
                raise RuntimeError("Server-Antwort enthält kein Checkout-Manifest.")
            delete_checkout_manifest_file(self.active_checkout_dir, path)
            write_manifest(self.active_checkout_dir, updated_manifest)
            write_checkout_metadata(
                self.active_checkout_dir,
                merge_checkout_metadata(
                    updated_manifest,
                    checkout_metadata,
                    self.active_checkout_dir,
                ),
            )
        except Exception as exc:
            if local_path.exists():
                try:
                    document = fcstd.open_document(local_path)
                    document_name = getattr(document, "Name", "")
                    if document_name:
                        self.checkout_document_names.append(document_name)
                except Exception:
                    pass
            self.set_status(f"Teil konnte nicht entfernt werden: {exc}")
            return

        self.checkout_document_names = [
            name for name in self.checkout_document_names if name not in closed
        ]
        self.set_status(f"{path} wurde zum Entfernen vorgemerkt.")

    def offer_cancel_unchanged_checkout(self, saved_count=0):
        answer = self.QtWidgets.QMessageBox.question(
            self.widget,
            "Keine Änderungen",
            "Keine modellrelevanten Änderungen gefunden. Checkout abbrechen?",
        )
        if answer != self.QtWidgets.QMessageBox.Yes:
            self.set_status(unchanged_checkout_text(saved_count=saved_count))
            return
        self.cancel_active_checkout(confirm=False)

    def cancel_checkout(self, checkout, confirm=True):
        from . import fcstd

        checkout_id = checkout.get("id") if isinstance(checkout, dict) else None
        if checkout_id is None:
            self.set_status("Kein Checkout ausgewählt.")
            return

        if confirm:
            answer = self.QtWidgets.QMessageBox.question(
                self.widget,
                "Checkout abbrechen",
                f"Checkout {checkout_id} wirklich abbrechen?",
            )
            if answer != self.QtWidgets.QMessageBox.Yes:
                self.set_status("Checkout-Abbruch abgebrochen.")
                return

        is_local_checkout = checkout_id == self.active_checkout_id()
        closed = []
        failed = []
        try:
            self.set_status("Breche Checkout ab...")
            self.client().cancel_checkout(checkout_id)
            if is_local_checkout:
                closed, failed = fcstd.close_documents(self.checkout_document_names)
                self.reset_active_checkout()
            else:
                self.checkout_errors.pop(checkout_id, None)
            self.refresh_active_checkouts()
        except PLMError as exc:
            self.set_status(f"PLM-Fehler: {exc}")
            return
        except Exception as exc:
            self.set_status(f"Checkout-Abbruch fehlgeschlagen: {exc}")
            return

        message = "Checkout abgebrochen."
        if closed:
            message = f"{message} Geschlossen: {len(closed)}."
        if failed:
            message = f"{message} Schließen fehlgeschlagen: {', '.join(failed)}."
        self.set_status(message)

    def cancel_selected_checkout(self, confirm=True):
        checkout = self.selected_tree_checkout()
        if checkout is None:
            self.set_status("Kein Checkout ausgewählt.")
            return
        self.cancel_checkout(checkout, confirm=confirm)

    def cancel_active_checkout(self, confirm=True):
        self.cancel_checkout(self.active_checkout, confirm=confirm)
