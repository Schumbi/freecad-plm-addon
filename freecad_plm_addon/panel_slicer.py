"""Print project selection and slicer synchronization."""

from pathlib import Path

from .errors import ConflictError, EmptyGeometryError, PLMError, WorkspaceError
from .panel_helpers import (
    print_project_label,
    revision_file_format,
    revision_primary_action,
)


class PanelSlicerMixin:
    def choose_print_project(self, matches, client):
        from .print_project_dialog import choose_print_project
        return choose_print_project(self.widget, self.QtCore, self.QtGui, self.QtWidgets, matches, client)

    def open_selected_revision(self):
        revision = self.selected_revision()
        action = revision_primary_action(revision)
        if action == "checkout":
            self.checkout_selected_revision()
        elif action == "open_readonly":
            self.open_selected_revision_readonly()
        else:
            self.set_status("Keine Revision ausgewählt.")

    def _sync_slicer_project_path(self, project_path, revision, state=None):
        from .slicer import read_sync_state, validate_3mf, write_sync_state
        from .workspace import sha256_file

        project_path = Path(project_path)
        state = dict(state or read_sync_state(project_path))
        directory_id = project_path.parent.name.removeprefix("print-project-")
        if project_path.parent.name.startswith("print-project-") and str(state.get("print_project_id")) != directory_id:
            raise WorkspaceError("Slicer-Datei und Druckprojekt-ID stimmen nicht überein.")
        validate_3mf(project_path)
        local_sha256 = sha256_file(project_path)
        if local_sha256 == state.get("server_sha256"):
            return False
        if state.get("print_project_id"):
            result = self.client().sync_print_project(
                state["print_project_id"], project_path,
                base_sha256=state.get("server_sha256", ""),
            )
            server_project = result["slicer_project"]
        else:
            result = self.client().sync_slicer_project(
                revision["id"], project_path,
                base_sha256=state.get("server_sha256", ""),
                label="Slicer-Projekt", slicer_name=state.get("slicer_name", ""),
            )
            server_project = result["slicer_project"]
        state.update(
            {
                "revision_id": revision["id"],
                "manufacturing_file_id": server_project.get("id"),
                "server_sha256": server_project["sha256"],
                "local_sha256": local_sha256,
                "sync_status": "synchronized",
            }
        )
        write_sync_state(project_path, state)
        self.set_status(f"Slicer-Projekt synchronisiert: {project_path.name}")
        return True

    def _slicer_file_changed(self, project_path, revision):
        from .slicer import read_sync_state, write_sync_state

        try:
            self._sync_slicer_project_path(project_path, revision)
        except ConflictError as exc:
            state = read_sync_state(project_path)
            state["sync_status"] = "conflict"
            write_sync_state(project_path, state)
            self.set_status(f"Slicer-Synchronisationskonflikt: {exc}")
        except Exception as exc:
            self.set_status(f"Slicer-Projekt noch nicht synchronisiert: {exc}")

    def rebuild_selected_revision_in_slicer(self):
        self.open_selected_revision_in_slicer(force_rebuild=True)

    def choose_slicer_geometry_action(self, sources_status, force_rebuild=False):
        box = self.QtWidgets.QMessageBox(self.widget)
        box.setWindowTitle("3MF neu erzeugen" if force_rebuild else "Slicer-Geometrie prüfen")
        reasons = {
            "changed": "Die CAD-Quellen haben sich seit dem Export geändert.",
            "unknown": "Der Quellenstand dieser 3MF ist nicht prüfbar. Die Quellenangaben fehlen oder sind ungültig.",
            "current": "Die 3MF wird aus dem gespeicherten CAD-Stand neu erzeugt.",
            "empty": "Diese 3MF enthält keine druckbare Geometrie.",
        }
        box.setText(
            reasons[sources_status]
            + "\n\nNeu erzeugen exportiert die ausgewählte gespeicherte Revision samt "
            "ihren Abhängigkeiten. Lokale Checkout-Änderungen müssen vorher eingecheckt werden. "
            "Der bisherige Slicerstand wird lokal im Unterordner backups gesichert. "
            "Anordnung, Druckeinstellungen, Farbzuweisungen und zusätzlich im Slicer "
            "eingefügte Quellen werden nicht übernommen.\n\n"
            "Bitte das bisherige Projekt im Slicer vor dem Neuerzeugen schließen."
        )
        rebuild = box.addButton("3MF neu erzeugen", self.QtWidgets.QMessageBox.AcceptRole)
        keep = None
        if not force_rebuild and sources_status != "empty":
            keep = box.addButton("Bisherigen Stand öffnen", self.QtWidgets.QMessageBox.ActionRole)
        cancel = box.addButton("Abbrechen", self.QtWidgets.QMessageBox.RejectRole)
        box.setDefaultButton(cancel)
        box.exec_()
        clicked = box.clickedButton()
        if clicked == rebuild:
            return "rebuild"
        if keep is not None and clicked == keep:
            return "keep"
        return "cancel"

    def open_selected_revision_in_slicer(self, force_rebuild=False):
        from .slicer import (
            SLICERS,
            SlicerProjectMonitor,
            export_revision_manifest_to_3mf,
            launch_slicer,
            migrate_legacy_slicer_project,
            read_sync_state,
            reconcile_slicer_project,
            resolve_slicer_command,
            revision_sources,
            slicer_sources_status,
            slicer_project_dir,
            slicer_project_filename,
            validate_3mf,
            write_sync_state,
        )
        from .workspace import sha256_file

        project = self.selected_project()
        part = self.selected_part()
        revision = self.selected_revision()
        if not project or not part or not revision or revision.get("id") is None:
            self.set_status("Projekt, Teil und Revision auswählen.")
            return
        if revision_file_format(revision) not in ("fcstd", "step", "stl"):
            self.set_status("Diese Revision kann nicht als Slicer-Projekt geöffnet werden.")
            return

        revision_id = revision["id"]
        project_code = project.get("code") or f"project-{project.get('id')}"
        revision_dir = slicer_project_dir(
            self.workspace_root.text().strip(),
            self.server_url.text().strip(),
            project_code,
            revision_id,
        )
        previous_monitor = None
        try:
            command = resolve_slicer_command(
                self.slicer_kind,
                self.slicer_executable,
                self.slicer_extra_args,
            )
            client = self.client()
            projects = client.get_print_projects()
            matches = [item for item in projects if item.get("project_id") == project["id"]]
            selection = self.choose_print_project(matches, client)
            if selection is None:
                self.set_status("Öffnen des Druckprojekts abgebrochen.")
                return
            action, print_project = selection
            if action == "new":
                from .print_project_dialog import next_print_project_code
                suggested = next_print_project_code(projects, project["id"], revision_id)
                code, accepted = self.QtWidgets.QInputDialog.getText(
                    self.widget, "Neues Druckprojekt", "Code des neuen Druckprojekts:",
                    self.QtWidgets.QLineEdit.Normal, suggested,
                )
                if not accepted or not code.strip():
                    self.set_status("Erstellen des Druckprojekts abgebrochen.")
                    return
                print_project = client.create_print_project(
                    revision_id, code.strip(),
                    f"Druckprojekt {part.get('number', '')} {revision.get('revision_code', '')}".strip(),
                    require_new=True,
                )
                source_paths, _selected_filter = self.QtWidgets.QFileDialog.getOpenFileNames(
                    None,
                    "Externe STL-Quellen zum Druckprojekt hinzufügen (optional)",
                    "",
                    "STL-Dateien (*.stl)",
                )
                for source_path in source_paths:
                    client.add_print_project_source(print_project["id"], source_path)
            if action == "existing" and print_project["primary_revision_id"] != revision_id:
                revision = client.get_revision(print_project["primary_revision_id"])
                revision_id = revision["id"]
                part = {"id": revision["part_id"]}
            # Existing projects always use their assigned revision, not the tree selection.
            revision_dir = slicer_project_dir(
                self.workspace_root.text().strip(), self.server_url.text().strip(),
                project_code, revision_id,
            )
            target_dir = slicer_project_dir(
                self.workspace_root.text().strip(),
                self.server_url.text().strip(),
                project_code,
                revision_id,
                print_project["id"],
            )
            target_dir.mkdir(parents=True, exist_ok=True)
            filename = slicer_project_filename(
                project_code, print_project["code"], "", revision.get("original_filename", "")
            )
            target_path = target_dir / filename
            migrate_legacy_slicer_project(
                revision_dir / filename, target_path, print_project["id"]
            )
            previous_monitor = self.slicer_monitors.get(str(target_path))
            if previous_monitor is not None:
                previous_monitor.pause()
            server_project = print_project.get("slicer_project")
            state = read_sync_state(target_path)
            state["print_project_id"] = print_project["id"]
            local_sha = sha256_file(target_path) if target_path.is_file() else ""
            previous_server_sha = state.get("server_sha256", "")
            current_server_sha = server_project.get("sha256", "") if server_project else ""
            reconcile_action = reconcile_slicer_project(
                local_sha, previous_server_sha, current_server_sha
            )

            if reconcile_action == "conflict":
                raise ConflictError(
                    409,
                    "Lokale und serverseitige Slicer-Projekte wurden geändert. "
                    "Die lokale Datei bleibt unangetastet.",
                )
            if reconcile_action == "upload":
                try:
                    validate_3mf(target_path)
                except EmptyGeometryError:
                    reconcile_action = "rebuild"
                else:
                    self._sync_slicer_project_path(target_path, revision, state)
                    server_project = client.get_print_project(print_project["id"]).get("slicer_project")
            elif reconcile_action in ("download", "current") and server_project:
                if reconcile_action == "download":
                    client.download_manufacturing_file(
                        server_project["download_url"],
                        target_path,
                        server_project["sha256"],
                    )
                state.update(
                    {
                        "revision_id": revision_id,
                        "manufacturing_file_id": server_project.get("id"),
                        "server_sha256": server_project["sha256"],
                        "local_sha256": server_project["sha256"],
                        "sync_status": "synchronized",
                    }
                )

            if target_path.is_file() and reconcile_action != "rebuild":
                try:
                    validate_3mf(target_path)
                except EmptyGeometryError:
                    reconcile_action = "rebuild"

            manifest = client.get_revision_manifest(revision_id)
            if target_path.is_file():
                sources_status = (
                    "empty" if reconcile_action == "rebuild" else slicer_sources_status(
                        target_path, revision_sources(manifest, revision_id, client.base_url)
                    )
                )
                if force_rebuild or sources_status == "empty":
                    choice = self.choose_slicer_geometry_action(sources_status, force_rebuild)
                    if choice == "cancel":
                        self.set_status("Öffnen des Slicer-Projekts abgebrochen.")
                        return
                    if choice == "rebuild":
                        reconcile_action = "rebuild"

            if not target_path.is_file() or reconcile_action == "rebuild":
                self.set_status(
                    "Erzeuge 3MF aus der CAD-Revision und ihren Abhängigkeiten..."
                )
                export_revision_manifest_to_3mf(
                    client,
                    revision_id,
                    target_dir / "source",
                    target_path,
                    manifest=manifest,
                    backup=True,
                )

            validate_3mf(target_path)
            slicer_label = SLICERS.get(self.slicer_kind, {}).get("label", "")
            if not slicer_label:
                joined = " ".join(command).lower()
                slicer_label = "OrcaSlicer" if "orca" in joined else "Bambu Studio"
            state.update(
                {
                    "revision_id": revision_id,
                    "project_code": project_code,
                    "part_id": part.get("id"),
                    "slicer_name": slicer_label,
                }
            )
            write_sync_state(target_path, state)
            self._sync_slicer_project_path(target_path, revision, state)
            if previous_monitor is not None:
                previous_monitor.stop()
                previous_monitor = None
            monitor = SlicerProjectMonitor(
                self.QtCore,
                target_path,
                lambda changed_path, item=dict(revision): self._slicer_file_changed(
                    changed_path, item
                ),
            )
            self.slicer_monitors[str(target_path)] = monitor
            launch_slicer(target_path, command)
        except ConflictError as exc:
            self.set_status(f"Slicer-Projekt-Konflikt: {exc}")
            return
        except PLMError as exc:
            self.set_status(f"PLM-Fehler: {exc}")
            return
        except Exception as exc:
            self.set_status(f"Slicer konnte nicht geöffnet werden: {exc}")
            return
        finally:
            if previous_monitor is not None:
                previous_monitor.resume()

        self.set_status(
            f"Slicer-Projekt geöffnet; Speichern wird automatisch synchronisiert: {target_path}"
        )
