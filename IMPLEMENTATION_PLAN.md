# FreeCAD-PLM Addon Implementierungsplan

## Summary

Das Addon ist ein eigenes Projekt unter `/home/ralf/devel/freecad-plm-addon`.
Es wird als FreeCAD-Workbench entwickelt und spricht ausschließlich per
Bearer Token mit der `/api/`-Schnittstelle des PLM.

Entwicklungsserver:

```text
https://plm.lan.schumbi.de
```

API-Token werden serverseitig erzeugt:

```bash
python manage.py create_api_token addon-user "FreeCAD Addon" --scope read --scope write --scope checkout
```

## Projektstruktur

```text
freecad-plm-addon/
  Init.py
  InitGui.py
  README.md
  IMPLEMENTATION_PLAN.md
  freecad_plm_addon/
    __init__.py
    api_client.py
    config.py
    workbench.py
    commands.py
    panel.py
    workspace.py
    fcstd.py
    errors.py
  tests/
    test_api_client.py
    test_workspace.py
```

## API-Schnittstelle

Alle API-Requests senden:

```http
Authorization: Bearer <api_token>
Content-Type: application/json
```

Dateidownloads senden ebenfalls `Authorization: Bearer <api_token>`.

Client-Interface:

```python
class PLMClient:
    def __init__(self, base_url: str, api_token: str): ...
    def get_projects(self) -> list[dict]: ...
    def get_project(self, project_id: int) -> dict: ...
    def get_parts(self, project_id: int) -> list[dict]: ...
    def get_part(self, part_id: int) -> dict: ...
    def update_part(self, part_id: int, data: dict) -> dict: ...
    def get_revision(self, revision_id: int) -> dict: ...
    def download_revision_file(self, download_url, target_path, expected_sha256): ...
    def checkout_revision(self, revision_id, snapshot_id=None, workspace_hint="") -> dict: ...
    def get_checkout_manifest(self, checkout_id: int) -> dict: ...
    def checkin(self, checkout_id: int, fcstd_path, change_summary: str) -> dict: ...
    def cancel_checkout(self, checkout_id: int) -> dict: ...
    def get_annotations(self, part_id: int) -> list[dict]: ...
    def create_annotation(self, part_id: int, data: dict) -> dict: ...
    def update_annotation(self, annotation_id: int, data: dict) -> dict: ...
```

Scopes:

- `read`: Projekte, Teile, Revisionen, Downloads, Manifest, Anmerkungen lesen
- `write`: Teile bearbeiten und Anmerkungen schreiben
- `checkout`: Checkout, Check-in, Cancel
- `admin`: Projektanlage/-bearbeitung über API

Fehler:

- `401`: Token fehlt/falsch/abgelaufen/widerrufen
- `403`: Scope oder Django-Rolle reicht nicht
- `404`: Objekt nicht gefunden
- `409`: fachlicher Konflikt wie aktiver Checkout oder PLMRevision-Konflikt

## Workspace-Regeln

Default:

```text
~/FreeCAD-PLM/
  <server-slug>/
    <project-code>/
      checkout-<checkout-id>/
        manifest.json
        files/
          <manifest.files[].path>
```

Regeln:

- `manifest.files[].path` ist relativ zu `files/`.
- Absolute Pfade und `..` werden lokal abgelehnt.
- Nach jedem Download wird SHA-256 geprüft.
- Root-Datei ist `is_root == true`.
- V1 checkt nur die Root-`.FCStd` wieder ein.
- Abhängige Dateien bleiben lokale Referenzdateien.

## Implementierungsreihenfolge

1. Grundstruktur und Tests anlegen.
2. `api_client.py` ohne FreeCAD-Abhängigkeit implementieren.
3. `workspace.py` implementieren und testen.
4. Verbindungstest gegen `GET /api/projects/` bauen.
5. FreeCAD-Workbench registrieren.
6. Dock/Panel mit Verbindung, Projektliste, Teileliste, Revisionsliste.
7. Checkout mit Manifest-Download, Hashprüfung und Root-Datei-Öffnung.
8. Check-in der Root-Datei mit Änderungsnotiz.
9. Cancel.
10. Annotationen lesen und schreiben.

## Test Plan

Automatisch ohne FreeCAD:

- Authorization-Header wird immer gesetzt.
- JSON-GET/POST serialisiert korrekt.
- Multipart-Check-in enthält `file` und `change_summary`.
- `401`, `403`, `404`, `409` werden zu eigenen Exceptions.
- Unsichere Workspace-Pfade werden abgelehnt.
- Manifest wird geschrieben/gelesen.
- SHA-256-Prüfung erkennt falsche Downloads.
- Root-Datei wird aus `is_root == true` bestimmt.

Manueller FreeCAD-Smoke:

1. Token erzeugen.
2. Server-URL und Token speichern.
3. Projektliste laden.
4. Teil und Revision auswählen.
5. Revision auschecken.
6. Dateien und Manifest im Workspace prüfen.
7. Root-Datei öffnet in FreeCAD.
8. Datei speichern.
9. Check-in mit Änderungsnotiz.
10. Neue Revision im Web-PLM prüfen.
11. Annotation aus FreeCAD erstellen und im Web prüfen.

## Defaults

- Addon-Verzeichnis: `/home/ralf/devel/freecad-plm-addon`
- Server: `https://plm.lan.schumbi.de`
- Token-only API
- HTTP-Bibliothek: Python-Standardbibliothek `urllib.request`
- Token-Speicherung: FreeCAD Preferences
- Keine Serveränderungen im Addon-Projekt
