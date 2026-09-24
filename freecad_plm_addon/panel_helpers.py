"""Labels, payloads and workflow decisions shared by panel sections."""

from pathlib import Path
import json
import re

from .workspace import safe_join, technically_changed_manifest_files


def project_label(project):
    code = project.get("code") or project.get("project_code") or ""
    name = project.get("name") or project.get("title") or ""
    if code and name:
        return f"{code} - {name}"
    return code or name or f"Projekt {project.get('id', '')}".strip()


def print_project_label(print_project):
    code = str(print_project.get("code") or "").strip()
    name = str(print_project.get("name") or "").strip()
    project_id = print_project.get("id")
    label = " · ".join(value for value in (code, name) if value)
    if not label:
        label = "Druckprojekt"
    if project_id is not None:
        label = f"{label} [ID {project_id}]"
    return label


def project_edit_payload(values):
    payload = {}
    fields = ("code", "name", "status", "project_date", "description")
    for field in fields:
        value = values.get(field, "")
        payload[field] = value.strip() if isinstance(value, str) else value
    if "tags" in values:
        payload["tags"] = [name.strip() for name in values["tags"].split(",") if name.strip()]
    payload["code"] = payload.get("code", "").upper()
    return payload


def project_import_result_text(result):
    summary = result.get("import_summary") or {}
    snapshot = result.get("snapshot") or {}
    files = summary.get("files") or snapshot.get("entries") or []
    return (
        f"Import abgeschlossen: {snapshot.get('name') or 'Projektstand'} "
        f"({len(files)} Datei(en), "
        f"{summary.get('created_parts', 0)} neue Teile, "
        f"{summary.get('created_revisions', 0)} neue Revisionen, "
        f"{summary.get('reused_revisions', 0)} wiederverwendet)."
    )


def import_checkout_candidates(result):
    snapshot = result.get("snapshot") or {}
    snapshot_id = snapshot.get("id")
    candidates = []
    for entry in snapshot.get("entries") or []:
        revision_id = entry.get("revision_id")
        file_format = str(entry.get("file_format") or "").lower()
        path = entry.get("path") or entry.get("filename") or ""
        if not file_format:
            file_format = "fcstd" if path.lower().endswith(".fcstd") else ""
        if revision_id is None or file_format != "fcstd":
            continue
        part_number = entry.get("part_number") or ""
        part_name = entry.get("part_name") or ""
        category = entry.get("part_category") or ""
        label = path
        part_label_text = " - ".join(item for item in (part_number, part_name) if item)
        if part_label_text:
            label = f"{label} ({part_label_text})" if label else part_label_text
        if category:
            label = f"{label} [{category}]"
        candidates.append(
            {
                "label": label or f"Revision {revision_id}",
                "path": path,
                "revision_id": revision_id,
                "snapshot_id": snapshot_id,
                "part_id": entry.get("part_id"),
                "part_number": part_number,
                "part_name": part_name,
                "part_category": category,
            }
        )
    return candidates


def import_checkout_followup_text(result):
    snapshot = result.get("snapshot") or {}
    external_count = 0
    for entry in snapshot.get("entries") or []:
        path = str(entry.get("path") or entry.get("filename") or "").lower()
        file_format = str(entry.get("file_format") or "").lower()
        if file_format in ("step", "stl") or path.endswith((".step", ".stp", ".stl")):
            external_count += 1
    if external_count:
        revision_word = "Revision" if external_count == 1 else "Revisionen"
        return (
            f"{external_count} STEP-/STL-{revision_word} importiert. "
            "Diese Austauschmodelle können in der Revisionsliste schreibgeschützt geöffnet werden."
        )
    return "Keine bearbeitbare FCStd-Revision für einen Checkout gefunden."


def connection_label(server_url):
    text = server_url.replace("https://", "").replace("http://", "").strip("/")
    return f"Verbunden mit {text}" if text else "Nicht verbunden."


def save_slicer_settings(kind, executable, extra_args):
    from . import config

    config.set_slicer_kind(kind)
    config.set_slicer_executable(executable)
    config.set_slicer_extra_args(extra_args)


def part_label(part):
    number = part.get("number") or part.get("part_number") or part.get("code") or ""
    name = part.get("name") or part.get("title") or ""
    status = part.get("status") or part.get("release_status") or ""
    label = " - ".join(value for value in (number, name) if value)
    if not label:
        label = f"Teil {part.get('id', '')}".strip()
    if status:
        return f"{label} [{status}]"
    return label


def part_edit_payload(values, include_number=False):
    payload = {}
    fields = ("name", "description", "material", "supplier", "tags", "category")
    if include_number:
        fields = ("number", *fields)
    for field in fields:
        value = values.get(field, "")
        payload[field] = value.strip() if isinstance(value, str) else value
    payload["is_archived"] = bool(values.get("is_archived", False))
    return payload


def new_part_filename(name):
    stem = re.sub(r"[^\w.-]+", "_", str(name or "").strip(), flags=re.UNICODE)
    stem = stem.strip("._-") or "Neues_Teil"
    if stem.lower().endswith(".fcstd"):
        stem = stem[:-6].rstrip("._-") or "Neues_Teil"
    return f"{stem}.FCStd"


def revisions_from_part_detail(part_detail):
    if not isinstance(part_detail, dict):
        return []
    for key in ("revisions", "revision_set", "latest_revisions"):
        revisions = part_detail.get(key)
        if isinstance(revisions, list):
            return revisions
    part = part_detail.get("part") if isinstance(part_detail.get("part"), dict) else part_detail
    for key in ("revisions", "revision_set", "latest_revisions"):
        revisions = part.get(key)
        if isinstance(revisions, list):
            return revisions
    return []


def revision_label(revision):
    number = (
        revision.get("revision")
        or revision.get("revision_code")
        or revision.get("version")
        or revision.get("number")
        or revision.get("label")
        or ""
    )
    status = revision_status_label(
        revision.get("status") or revision.get("release_status") or ""
    )
    file_format = revision_format_label(revision)
    filename = revision.get("original_filename") or revision.get("filename") or revision.get("file_name") or ""
    created = revision.get("created_at") or revision.get("created") or revision.get("uploaded_at") or ""
    if number:
        label = f"R{number}" if str(number).isdigit() else str(number)
    else:
        label = f"Revision {revision.get('id', '')}".strip()
    details = [value for value in (status, file_format, filename, created[:10]) if value]
    if details:
        return " · ".join([label, *details])
    return label


def revision_status_label(status):
    labels = {
        "draft": "Entwurf",
        "released": "Freigegeben",
        "obsolete": "Obsolet",
    }
    value = str(status or "").strip()
    return labels.get(value.lower(), value)


def revision_file_format(revision):
    if not isinstance(revision, dict):
        return ""
    file_format = str(revision.get("file_format") or "").strip().lower()
    if file_format:
        return file_format
    filename = str(
        revision.get("original_filename")
        or revision.get("filename")
        or revision.get("file_name")
        or ""
    ).lower()
    if filename.endswith(".fcstd"):
        return "fcstd"
    if filename.endswith((".step", ".stp")):
        return "step"
    if filename.endswith(".stl"):
        return "stl"
    return ""


def revision_format_label(revision):
    labels = {"fcstd": "FCStd", "step": "STEP", "stl": "STL"}
    file_format = revision_file_format(revision)
    return labels.get(file_format, file_format.upper())


def revision_is_checkout_editable(revision):
    return revision_file_format(revision) == "fcstd"


def revision_primary_action(revision):
    if not isinstance(revision, dict) or revision.get("id") is None:
        return "missing_revision"
    if revision_is_checkout_editable(revision):
        return "checkout"
    return "open_readonly"


def revision_workflow_hint(revision):
    file_format = revision_format_label(revision) or "CAD"
    if revision_is_checkout_editable(revision):
        return f"{file_format}: bearbeitbar · Doppelklick startet den Checkout"
    return f"{file_format}: Austauschmodell · Doppelklick öffnet schreibgeschützt"


def active_checkout_revision_id(checkout):
    if not isinstance(checkout, dict):
        return None
    for key in ("revision_id", "base_revision_id", "root_revision_id"):
        if checkout.get(key) is not None:
            return checkout.get(key)
    for key in ("revision", "base_revision", "root_revision"):
        revision = checkout.get(key)
        if isinstance(revision, dict) and revision.get("id") is not None:
            return revision.get("id")
    return None


def checkout_guard_action(active_checkout, target_revision):
    if not isinstance(target_revision, dict) or target_revision.get("id") is None:
        return "missing_revision"
    if not active_checkout:
        return "checkout"
    if active_checkout_revision_id(active_checkout) == target_revision.get("id"):
        return "same_checkout"
    return "blocked_by_other_checkout"


def checkout_visual_state(checkout, local_checkout_id=None, error=False):
    if not isinstance(checkout, dict) or checkout.get("id") is None:
        return "none"
    if error:
        return "error"
    if checkout.get("id") == local_checkout_id:
        return "local"
    return "server"


def checkout_can_cancel(checkout):
    return isinstance(checkout, dict) and checkout.get("id") is not None


def context_primary_action(kind, revision=None, checkout=None, local_checkout_id=None):
    if kind in ("", None):
        return "import_project"
    if kind == "project":
        return "new_part"
    if kind == "part":
        return "edit_part"
    if kind == "checkout_error":
        return "refresh"
    if kind != "revision":
        return "none"
    state = checkout_visual_state(checkout, local_checkout_id)
    if state == "local":
        return "checkin"
    if state == "server":
        return "reopen_checkout"
    return revision_primary_action(revision)


def checkout_display_name(path):
    if not path:
        return ""
    return Path(path).name or str(path)


def print_freecad_console(message):
    if not message:
        return
    text = str(message)
    if text.startswith("[FreeCAD-PLM]"):
        output = text
    elif text.startswith("FreeCAD-PLM "):
        output = f"[FreeCAD-PLM] {text[len('FreeCAD-PLM '):]}"
    else:
        output = f"[FreeCAD-PLM] {text}"
    try:
        import FreeCAD
    except Exception:
        return
    console = getattr(FreeCAD, "Console", None)
    printer = getattr(console, "PrintMessage", None)
    if callable(printer):
        printer(f"{output}\n")


def compact_revision_summary(revision):
    if not isinstance(revision, dict) or revision.get("id") is None:
        return "Keine Revision ausgewählt."
    number = (
        revision.get("revision")
        or revision.get("revision_code")
        or revision.get("version")
        or revision.get("number")
        or revision.get("label")
        or revision.get("id")
    )
    status = revision_status_label(
        revision.get("status") or revision.get("release_status")
    )
    file_format = revision_format_label(revision)
    filename = revision.get("original_filename") or revision.get("filename") or revision.get("file_name")
    created = revision.get("created_at") or revision.get("created") or revision.get("uploaded_at")
    details = [f"R{number}" if str(number).isdigit() else str(number)]
    details.extend(
        str(value)
        for value in (status, file_format, filename, (created or "")[:10])
        if value
    )
    return " · ".join(details)


def format_bytes(size_bytes):
    if size_bytes in ("", None):
        return ""
    try:
        value = int(size_bytes)
    except (TypeError, ValueError):
        return str(size_bytes)
    units = ("B", "KB", "MB", "GB")
    amount = float(value)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(amount)} {unit}"
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return str(value)


def revision_overview_text(revision):
    rows = [
        ("ID", revision.get("id")),
        ("Revision", revision.get("revision_code") or revision.get("revision") or revision.get("version")),
        ("Status", revision.get("status") or revision.get("release_status")),
        ("Datei", revision.get("original_filename") or revision.get("filename") or revision.get("file_name")),
        ("Format", revision.get("file_format")),
        ("Groesse", format_bytes(revision.get("size_bytes"))),
        ("SHA-256", revision.get("sha256")),
        ("Erstellt", revision.get("created_at") or revision.get("created") or revision.get("uploaded_at")),
        ("Freigegeben", revision.get("released_at")),
        ("Download-URL", revision.get("download_url")),
    ]
    lines = [f"{label}: {value}" for label, value in rows if value not in ("", None)]
    return "\n".join(lines) or "Keine Revisionsdetails vorhanden."


def revision_notes_text(revision):
    return revision.get("notes") or "Keine Notizen vorhanden."


def revision_notes_payload(notes):
    return {"notes": (notes or "").strip()}


def revision_technical_text(revision):
    metadata = revision.get("extracted_metadata")
    if not metadata:
        return "Keine technischen Metadaten vorhanden."
    return json.dumps(metadata, indent=2, sort_keys=True, ensure_ascii=False)


def annotation_label(annotation):
    parts = []
    target = annotation.get("object_name") or ""
    subelement = annotation.get("subelement") or ""
    if target and subelement:
        parts.append(f"{target}.{subelement}")
    elif target:
        parts.append(target)

    status = annotation.get("status") or ""
    if status:
        parts.append(f"[{status}]")

    author = annotation.get("created_by") or ""
    created = annotation.get("created_at") or ""
    if author or created:
        parts.append(" ".join(value for value in (author, created[:10]) if value))

    text = annotation.get("text") or ""
    if text:
        parts.append(text)

    return " - ".join(parts) or f"Anmerkung {annotation.get('id', '')}".strip()


def annotation_update_payload(text=None, status=None):
    payload = {}
    if text is not None:
        payload["text"] = text.strip()
    if status is not None:
        payload["status"] = status
    return payload


def annotation_create_payload(revision_id, text, object_name="", subelement=""):
    object_name = object_name.strip() if isinstance(object_name, str) else ""
    subelement = subelement.strip() if isinstance(subelement, str) else ""
    return {
        "revision_id": revision_id,
        "text": text.strip(),
        "object_name": object_name,
        "subelement": subelement,
    }


def annotation_matches_filter(annotation, filter_key, revision_id):
    status = annotation.get("status") or "open"
    annotation_revision_id = annotation.get("revision_id")
    if filter_key == "open":
        return status != "resolved"
    if filter_key == "resolved":
        return status == "resolved"
    if filter_key == "revision":
        return annotation_revision_id == revision_id
    if filter_key == "part":
        return annotation_revision_id is None
    return True


def annotations_for_revision(annotations, revision_id):
    return [
        annotation
        for annotation in annotations
        if annotation.get("revision_id") in (None, revision_id)
    ]


def checkout_project_code(checkout):
    project = checkout.get("project") if isinstance(checkout.get("project"), dict) else {}
    return (
        project.get("code")
        or project.get("project_code")
        or checkout.get("project_code")
        or f"project-{project.get('id') or checkout.get('project_id')}"
    )


def checkout_label(checkout):
    checkout_id = checkout.get("id", "")
    project = checkout.get("project") if isinstance(checkout.get("project"), dict) else {}
    part = checkout.get("part") if isinstance(checkout.get("part"), dict) else {}
    revision = checkout.get("revision") if isinstance(checkout.get("revision"), dict) else {}
    project_code = checkout_project_code(checkout)
    part_text = part.get("number") or part.get("part_number") or part.get("name") or ""
    revision_text = (
        revision.get("revision_code")
        or revision.get("revision")
        or revision.get("version")
        or revision.get("id")
        or ""
    )
    details = [value for value in (project_code, part_text, f"Revision {revision_text}") if value]
    if details:
        return f"Checkout {checkout_id} - {', '.join(str(value) for value in details)}"
    return f"Checkout {checkout_id}".strip()


def response_manifest(response):
    if response is None:
        return None
    return response.get("manifest", response) if isinstance(response, dict) else response


def checkin_result_text(response):
    if not isinstance(response, dict):
        return ""
    parts = []
    revision = response.get("revision")
    if isinstance(revision, dict) and revision.get("id") is not None:
        parts.append(f"Neue Root-Revision: {revision.get('id')}.")

    revisions = response.get("revisions")
    if isinstance(revisions, list):
        count = len(revisions)
        if count:
            suffix = "" if count == 1 else "en"
            parts.append(f"Neue Revision{suffix}: {count}.")
    ignored_files = response.get("ignored_files")
    if isinstance(ignored_files, list) and ignored_files:
        parts.append(f"Ignoriert: {len(ignored_files)}.")
    return " ".join(parts)


def checkin_created_revision_count(response):
    if not isinstance(response, dict):
        return 0
    revisions = response.get("revisions")
    if isinstance(revisions, list):
        return len(revisions)
    revision = response.get("revision")
    return 1 if isinstance(revision, dict) and revision.get("id") is not None else 0


def checkin_completed(response):
    checkout = response.get("checkout") if isinstance(response, dict) else None
    return isinstance(checkout, dict) and checkout.get("status") == "completed"


def checkout_file_label(item):
    path = item.get("path") or item.get("filename") or "Datei"
    part_number = item.get("part_number") or ""
    revision_code = item.get("revision_code") or ""
    details = " · ".join(value for value in (part_number, revision_code) if value)
    return f"{path} ({details})" if details else path


def checkin_conflict_text(exc):
    details = str(exc).strip()
    prefix = (
        "Check-in-Konflikt: Der Serverstand passt nicht mehr zum lokalen Checkout. "
        "Bitte aktive Checkouts aktualisieren und den Checkout neu laden oder abbrechen."
    )
    if details:
        return f"{prefix} Servermeldung: {details}"
    return prefix


def unchanged_checkout_text(saved_count=0):
    message = "Keine modellrelevanten Änderungen; Checkout bleibt aktiv."
    if saved_count:
        message = f"{message} Gespeichert: {saved_count}."
    return message


def checkout_primary_button_action(has_changes):
    return "checkin" if has_changes else "cancel"


def checkout_files_signature(manifest, checkout_path):
    files_root = Path(checkout_path) / "files"
    signature = []
    for item in manifest.get("files") or []:
        relative_path = item.get("path") or ""
        target = safe_join(files_root, relative_path)
        stat = target.stat()
        signature.append((relative_path, stat.st_size, stat.st_mtime_ns))
    return tuple(signature)


def checkout_has_changes(
    manifest,
    checkout_metadata,
    checkout_path,
    modified_document_names=(),
):
    if modified_document_names:
        return True
    if manifest.get("removed_paths") or manifest.get("added_paths"):
        return True
    return bool(
        technically_changed_manifest_files(
            manifest,
            checkout_metadata,
            checkout_path,
        )
    )
