# Server API Requirement: Read-only Revision Manifest

> Historische API-Anforderungsentwicklung. Der aktuelle Gesamtvertrag steht im
> Server-Repository unter `planning/FREECAD_ADDON_PLAN.md`; die aktuelle
> Bedienung beschreibt `README.md`.

## Ziel

Das FreeCAD-PLM Addon soll read-only Revisionen und später echte Checkouts über dieselbe Manifest-Struktur laden können.

Der aktuelle Addon-Read-only-Pfad rekonstruiert referenzierte FCStd-Dateien aus `extracted_metadata.freecad_document.references` und sucht passende Revisionen im Projekt über Dateinamen. Das funktioniert als Fallback, ist aber nicht exakt genug für Baugruppenstände.

## Neuer Endpunkt

```http
GET /api/revisions/<revision_id>/manifest/
```

Optional:

```http
GET /api/revisions/<revision_id>/manifest/?snapshot_id=<snapshot_id>
```

## Authentifizierung

Scope:

```text
read
```

Der Endpunkt darf keinen Checkout erzeugen, keinen Checkout-Lock setzen und keine schreibenden Seiteneffekte haben.

## Verhalten

- Liefert ein Manifest für die angefragte Root-Revision.
- Nutzt dieselbe Datei-Auflösung wie der bestehende Checkout-Manifest-Pfad.
- Wenn `snapshot_id` angegeben ist, werden Abhängigkeiten exakt aus diesem Projektstand aufgelöst.
- Wenn keine Referenzen existieren, reicht eine Ein-Datei-Manifest-Antwort.
- Wenn Referenzen existieren, aber kein geeigneter Snapshot verfügbar/angegeben ist, soll der Server mit einem klaren Fehler antworten.

Empfohlene Fehler:

```http
409 Conflict
```

Payload:

```json
{
  "error": "Referenzierte Revisionen können nur mit Projektstand geladen werden."
}
```

## Antwortformat

Die Antwort soll kompatibel zum bestehenden Checkout-Manifest sein, aber ohne Checkout-Objekt:

```json
{
  "manifest": {
    "part": {
      "id": 1,
      "number": "A-001",
      "name": "Druck"
    },
    "revision": {
      "id": 10,
      "revision_code": "R0001",
      "status": "draft",
      "original_filename": "Druck.FCStd",
      "sha256": "...",
      "download_url": "https://plm.example/api/revisions/10/file/"
    },
    "snapshot": {
      "id": 3,
      "name": "Arbeitsstand"
    },
    "files": [
      {
        "path": "Druck.FCStd",
        "revision_id": 10,
        "sha256": "...",
        "download_url": "https://plm.example/api/revisions/10/file/",
        "is_root": true
      },
      {
        "path": "Box.FCStd",
        "revision_id": 11,
        "sha256": "...",
        "download_url": "https://plm.example/api/revisions/11/file/",
        "is_root": false
      }
    ]
  }
}
```

## Addon-Nutzung

Nach Umsetzung soll das Addon beide Pfade auf eine gemeinsame Download-Logik umstellen:

```text
Read-only öffnen
-> GET /api/revisions/<id>/manifest/
-> manifest.files herunterladen
-> SHA-256 prüfen
-> manifest.json schreiben
-> Root-Datei aus is_root öffnen
```

```text
Checkout
-> POST /api/revisions/<id>/checkout/
-> Checkout-Manifest laden
-> manifest.files herunterladen
-> SHA-256 prüfen
-> manifest.json schreiben
-> Root-Datei aus is_root öffnen
```

## Akzeptanzkriterien

- Read-only Manifest-Endpunkt funktioniert mit `read`-Token.
- Endpunkt erzeugt keinen `Checkout`.
- Antwort enthält genau eine Root-Datei mit `is_root: true`.
- Jede Datei enthält `path`, `revision_id`, `sha256`, `download_url`, `is_root`.
- Unsichere Pfade wie absolute Pfade oder `..` werden nicht ausgeliefert.
- Baugruppen mit Snapshot liefern alle referenzierten FCStd-Dateien in korrekter relativer Struktur.
- Baugruppen ohne passenden Snapshot liefern einen klaren `409 Conflict`.
- Bestehender Checkout-Manifest-Code wird möglichst wiederverwendet, damit read-only und checkout dieselbe Abhängigkeitslogik nutzen.

---

# Server API Requirement: Aktive Checkouts wiederfinden

## Ziel

Wenn FreeCAD geschlossen und später erneut gestartet wird, darf ein bereits
serverseitig aktiver Checkout nicht im Addon verloren gehen.

Der Server bleibt die Wahrheit für Checkout-Locks. Das Addon kann lokale
Workspace-Dateien und Marker verlieren oder veraltet haben. Deshalb braucht das
Addon nach dem Verbinden eine API, um aktive Checkouts des aktuellen API-Users
abzufragen und wieder aufnehmen zu können.

## Neuer Endpunkt

```http
GET /api/checkouts/active/
```

## Authentifizierung

Scope:

```text
checkout
```

Wenn der Endpunkt auch Projektdaten, Teil-/Revisionsdaten oder Manifest-Links
ausliefert, die sonst nur mit `read` sichtbar sind, ist ein Token mit beiden
Scopes empfohlen:

```text
read, checkout
```

## Verhalten

- Liefert alle aktiven, nicht eingecheckten und nicht abgebrochenen Checkouts
  des aktuellen API-Users.
- Liefert keine Checkouts anderer User.
- Erzeugt keine neuen Checkouts und verändert keine Locks.
- Die Antwort muss ausreichen, damit das Addon den lokalen Workspace-Pfad
  `.../<server>/<project_code>/checkout-<checkout_id>/` rekonstruieren kann.
- Die Antwort soll für jeden Checkout entweder direkt das Manifest enthalten
  oder einen stabilen Manifest-Endpunkt nennen.
- Wenn für einen aktiven Checkout lokale Dateien fehlen, kann das Addon über
  das Manifest die Dateien erneut herunterladen.

## Antwortformat

Empfohlen:

```json
{
  "checkouts": [
    {
      "id": 42,
      "status": "active",
      "created_at": "2026-07-06T12:00:00Z",
      "updated_at": "2026-07-06T12:10:00Z",
      "workspace_hint": "/home/ralf/FreeCAD-PLM",
      "project": {
        "id": 1,
        "code": "PRJ",
        "name": "Testprojekt"
      },
      "part": {
        "id": 5,
        "number": "A-001",
        "name": "Druck"
      },
      "revision": {
        "id": 10,
        "revision_code": "R0001",
        "original_filename": "Druck.FCStd"
      },
      "snapshot": {
        "id": 3,
        "name": "Arbeitsstand"
      },
      "manifest_url": "/api/checkouts/42/manifest/"
    }
  ]
}
```

Alternativ darf `manifest` direkt eingebettet werden, solange es dieselbe
Struktur wie `GET /api/checkouts/<checkout_id>/manifest/` verwendet.

## Addon-Nutzung

```text
PLM-Verbindung aktivieren
-> GET /api/projects/
-> GET /api/checkouts/active/
-> aktive Checkouts im Panel anzeigen
-> für jeden Checkout lokalen Pfad rekonstruieren
-> wenn manifest.json und Root-Datei vorhanden sind: "Checkout wieder öffnen"
-> wenn Dateien fehlen: Manifest laden und Dateien erneut herunterladen
```

```text
Checkout wieder öffnen
-> vorhandenes oder neu geladenes Manifest nutzen
-> Root-Datei aus is_root öffnen
-> Check-in und Checkout abbrechen für diesen Checkout aktivieren
```

## Akzeptanzkriterien

- Der Endpunkt funktioniert für Token mit `checkout`-Scope.
- Die Antwort enthält nur aktive Checkouts des authentifizierten Users.
- Jeder Checkout enthält mindestens `id`, `status`, `project.code`,
  `revision.id` und entweder `manifest_url` oder `manifest`.
- `GET /api/checkouts/<checkout_id>/manifest/` bleibt für aktive Checkouts des
  aktuellen Users abrufbar.
- Ein Addon-Neustart verliert serverseitige Locks nicht aus der UI: Nach
  Verbinden kann der User aktive Checkouts sehen und wieder öffnen.
- Checkouts, die bereits eingecheckt oder abgebrochen wurden, werden nicht als
  aktiv ausgeliefert.

---

# Server API Requirement: Manifest-basierter Multi-Datei-Check-in

## Ziel

Wenn eine ausgecheckte Baugruppe referenzierte FCStd-Dateien enthält, kann der
User nicht nur die Root-Datei, sondern auch abhängige Teile ändern. Beim
Check-in muss das Addon alle geänderten Dateien aus dem Checkout-Manifest
übertragen können.

Der bisherige Single-File-Check-in bleibt für reine Root-Änderungen
kompatibel:

```http
POST /api/checkouts/<checkout_id>/checkin/
```

mit Multipart-Feld:

```text
file=<root.FCStd>
change_summary=<text>
```

## Multi-Datei-Request

Dasselbe Endpoint soll optional mehrere Dateien akzeptieren.

Multipart-Felder:

```text
change_summary=<text>
files_metadata=<json>
file_0=<FCStd>
file_1=<FCStd>
...
```

`files_metadata` ist eine JSON-Liste. Jeder Eintrag beschreibt genau ein
Dateifeld:

```json
[
  {
    "field": "file_0",
    "path": "Root.FCStd",
    "revision_id": 10,
    "base_sha256": "sha256-aus-manifest",
    "sha256": "sha256-der-lokalen-datei",
    "is_root": true
  },
  {
    "field": "file_1",
    "path": "parts/Child.FCStd",
    "revision_id": 11,
    "base_sha256": "sha256-aus-manifest",
    "sha256": "sha256-der-lokalen-datei",
    "is_root": false
  }
]
```

## Addon-Verhalten

```text
Einchecken
-> alle Checkout-Dokumente speichern
-> manifest.json lesen
-> SHA-256 jeder lokalen Datei unter files/ mit manifest.files[].sha256 vergleichen
-> unveränderte Dateien nicht hochladen
-> wenn nur Root geändert ist: bestehenden Single-File-Check-in verwenden
-> wenn referenzierte Dateien geändert sind: Multi-Datei-Check-in verwenden
```

Vorhandene lokale Checkout-Dateien dürfen beim Wiederaufnehmen eines Checkouts
nicht mit Manifest-Downloads überschrieben werden, weil sie lokale Änderungen
enthalten können.

## Server-Verhalten

- Der Server validiert, dass `files_metadata[].path` im Checkout-Manifest
  existiert.
- Der Server validiert, dass `files_metadata[].base_sha256` dem Manifeststand
  entspricht, auf dem der Checkout basiert.
- Unsichere Pfade wie absolute Pfade oder `..` werden abgelehnt.
- Jede hochgeladene Datei muss eine gültige `.FCStd` sein.
- Für jede geänderte Datei soll der Server eine neue Revision des
  zugehörigen Teils erzeugen.
- Die Root-Datei ist der Eintrag mit `is_root: true`.
- Wenn nur referenzierte Dateien geändert sind und die Root-Datei unverändert
  ist, soll der Server trotzdem den Checkout abschließen und die erzeugten
  Revisionen in der Antwort ausweisen.
- Bei Konflikten antwortet der Server mit `409 Conflict` und lässt den
  Checkout aktiv.

## Antwortformat

Empfohlen:

```json
{
  "checkout": {
    "id": 42,
    "status": "completed"
  },
  "revision": {
    "id": 20,
    "revision_code": "R0002"
  },
  "revisions": [
    {
      "path": "Root.FCStd",
      "revision": {
        "id": 20,
        "revision_code": "R0002"
      }
    },
    {
      "path": "parts/Child.FCStd",
      "revision": {
        "id": 21,
        "revision_code": "R0004"
      }
    }
  ]
}
```

`revision` bleibt für Rückwärtskompatibilität die Root-Revision, sofern
eine Root-Datei eingecheckt wurde.

## Akzeptanzkriterien

- Single-File-Check-in mit `file` funktioniert unverändert weiter.
- Multi-Datei-Check-in mit `files_metadata` und `file_<n>` funktioniert für
  Root- und referenzierte Dateien.
- Unveränderte Dateien müssen nicht hochgeladen werden.
- Der Server lehnt unbekannte oder unsichere Manifest-Pfade ab.
- Bei erfolgreichem Multi-Datei-Check-in ist der Checkout `completed`.
- Die Antwort enthält alle erzeugten Revisionen mit Manifest-Pfadbezug.

---

# Server API Requirement: Revisionsnotizen und Anmerkungs-CRUD

## Ziel

Das Addon soll Revisionsnotizen direkt im FreeCAD-Workflow pflegen können und
Anmerkungen vollständig verwalten: lesen, anlegen, bearbeiten, Status setzen
und löschen.

## Revisionsnotizen

```http
POST /api/revisions/<revision_id>/notes/
```

Scope:

```text
write
```

Request:

```json
{
  "notes": "Vor Serienfreigabe in Baugruppe prüfen."
}
```

Antwort:

```json
{
  "revision": {
    "id": 10,
    "revision_code": "R0002",
    "notes": "Vor Serienfreigabe in Baugruppe prüfen."
  }
}
```

Verhalten:

- Aktualisiert nur das Feld `Revision.notes`.
- Erzeugt keine neue Revision.
- Erzeugt ein AuditEvent `revision_notes_updated`.
- Leere Notizen sind erlaubt und löschen den Notiztext.

## Anmerkungen löschen

Der bestehende Endpunkt soll zusätzlich `DELETE` akzeptieren:

```http
DELETE /api/annotations/<annotation_id>/
```

Scope:

```text
write
```

Antwort:

```http
204 No Content
```

Verhalten:

- Löscht die Anmerkung oder markiert sie serverseitig als gelöscht.
- Erzeugt ein AuditEvent `annotation_deleted`.
- Darf keine Revision erzeugen.
- Darf keine Anmerkungen anderer Projekte ohne Berechtigung löschen.

## Addon-Nutzung

```text
Revision auswählen
-> Notizen im Detail-Tab bearbeiten
-> POST /api/revisions/<id>/notes/
-> Revisionsliste und Detailkontext aktualisieren
```

```text
Anmerkung auswählen
-> Bearbeiten, Erledigt/Wieder offen oder Löschen
-> POST oder DELETE /api/annotations/<id>/
-> Anmerkungsliste mit aktuellem Filter neu laden
```

---

# Server API Requirement: Projektmetadaten im Addon

## Ziel

Das Addon soll die Projektdaten spiegeln, die im WebUI am Projekt gepflegt
werden: Code, Name, Status, Datum und Beschreibung.

## Endpunkt

```http
GET /api/projects/<project_id>/
POST /api/projects/<project_id>/
```

Scope für `GET`:

```text
read
```

Scope für `POST`:

```text
admin
```

## Payload

Der Server liefert und akzeptiert folgende Felder:

```json
{
  "code": "PRJ",
  "name": "Projekt",
  "status": "running",
  "project_date": "2026-07-08",
  "description": "Optional"
}
```

`status` nutzt dieselben Werte wie das WebUI: `running`, `completed`, `idea`,
`important`, `order`. `project_date` ist leer oder ein Datum im Format
`YYYY-MM-DD`. Der Server normalisiert `code` auf Großbuchstaben und schreibt
bei Änderungen ein AuditEvent `project_updated`.

## Addon-Nutzung

```text
Projekt auswählen
-> Projektdaten im Tab "Projekt" anzeigen
-> Bearbeiten
-> POST /api/projects/<id>/
-> Projektliste und Formular mit Serverantwort aktualisieren
```

---

# Server API Requirement: Lokalen FreeCAD-Ordner importieren

## Ziel

Das Addon soll neue lokale FreeCAD-Teile und Baugruppen inklusive abhängiger
`.FCStd`-Dateien in das PLM aufnehmen können. Dafür wird ein lokaler Ordner
als ZIP mit relativen Pfaden an den Server gesendet. Der Server legt daraus
Teile/Baugruppen, Revisionen und einen Projektstand an.

## Bestehendes Projekt

```http
POST /api/projects/<project_id>/snapshots/import/
```

Scope:

```text
write
```

Multipart:

- `file`: ZIP mit `.FCStd`-Dateien
- `name`: Name des Projektstands

## Neues Projekt plus Import

```http
POST /api/projects/import/
```

Scope:

```text
admin
```

Multipart:

- `file`: ZIP mit `.FCStd`-Dateien
- `code`, `name`, `status`, `project_date`, `description`
- `snapshot_name`

Der Kombiflow muss atomar sein: Wenn der ZIP-Import fehlschlägt, darf kein
leeres Projekt übrig bleiben.

## Addon-Nutzung

```text
Projekt importieren
-> neues Projekt oder ausgewähltes Projekt wählen
-> Projektmetadaten und Projektstandsname erfassen
-> lokalen Ordner wählen
-> alle .FCStd rekursiv mit relativen Pfaden ins ZIP packen
-> passenden Import-Endpunkt aufrufen
-> optional importiertes Root-Teil auswählen
-> optional über bestehenden Checkout-Endpunkt auschecken
-> optional lokalen Importordner nach ~/FreeCAD-PLM/imported/... verschieben
-> Projektliste und Teileliste aktualisieren
```

Der Ordnerimport ist der V1-Hauptpfad, weil er FreeCAD-Baugruppen mit
relativen Referenzen robuster abbildet als das reine Einsammeln geöffneter
Dokumente.
