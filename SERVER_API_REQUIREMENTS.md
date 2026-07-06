# Server API Requirement: Read-only Revision Manifest

## Ziel

Das FreeCAD-PLM Addon soll read-only Revisionen und spaeter echte Checkouts ueber dieselbe Manifest-Struktur laden koennen.

Der aktuelle Addon-Read-only-Pfad rekonstruiert referenzierte FCStd-Dateien aus `extracted_metadata.freecad_document.references` und sucht passende Revisionen im Projekt ueber Dateinamen. Das funktioniert als Fallback, ist aber nicht exakt genug fuer Baugruppenstaende.

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

- Liefert ein Manifest fuer die angefragte Root-Revision.
- Nutzt dieselbe Datei-Aufloesung wie der bestehende Checkout-Manifest-Pfad.
- Wenn `snapshot_id` angegeben ist, werden Abhaengigkeiten exakt aus diesem Projektstand aufgeloest.
- Wenn keine Referenzen existieren, reicht eine Ein-Datei-Manifest-Antwort.
- Wenn Referenzen existieren, aber kein geeigneter Snapshot verfuegbar/angegeben ist, soll der Server mit einem klaren Fehler antworten.

Empfohlene Fehler:

```http
409 Conflict
```

Payload:

```json
{
  "error": "Referenzierte Revisionen koennen nur mit Projektstand geladen werden."
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
Read-only oeffnen
-> GET /api/revisions/<id>/manifest/
-> manifest.files herunterladen
-> SHA-256 pruefen
-> manifest.json schreiben
-> Root-Datei aus is_root oeffnen
```

```text
Checkout
-> POST /api/revisions/<id>/checkout/
-> Checkout-Manifest laden
-> manifest.files herunterladen
-> SHA-256 pruefen
-> manifest.json schreiben
-> Root-Datei aus is_root oeffnen
```

## Akzeptanzkriterien

- Read-only Manifest-Endpunkt funktioniert mit `read`-Token.
- Endpunkt erzeugt keinen `Checkout`.
- Antwort enthaelt genau eine Root-Datei mit `is_root: true`.
- Jede Datei enthaelt `path`, `revision_id`, `sha256`, `download_url`, `is_root`.
- Unsichere Pfade wie absolute Pfade oder `..` werden nicht ausgeliefert.
- Baugruppen mit Snapshot liefern alle referenzierten FCStd-Dateien in korrekter relativer Struktur.
- Baugruppen ohne passenden Snapshot liefern einen klaren `409 Conflict`.
- Bestehender Checkout-Manifest-Code wird moeglichst wiederverwendet, damit read-only und checkout dieselbe Abhaengigkeitslogik nutzen.

---

# Server API Requirement: Aktive Checkouts wiederfinden

## Ziel

Wenn FreeCAD geschlossen und spaeter erneut gestartet wird, darf ein bereits
serverseitig aktiver Checkout nicht im Addon verloren gehen.

Der Server bleibt die Wahrheit fuer Checkout-Locks. Das Addon kann lokale
Workspace-Dateien und Marker verlieren oder veraltet haben. Deshalb braucht das
Addon nach dem Verbinden eine API, um aktive Checkouts des aktuellen API-Users
abzufragen und wieder aufnehmen zu koennen.

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
- Erzeugt keine neuen Checkouts und veraendert keine Locks.
- Die Antwort muss ausreichen, damit das Addon den lokalen Workspace-Pfad
  `.../<server>/<project_code>/checkout-<checkout_id>/` rekonstruieren kann.
- Die Antwort soll fuer jeden Checkout entweder direkt das Manifest enthalten
  oder einen stabilen Manifest-Endpunkt nennen.
- Wenn fuer einen aktiven Checkout lokale Dateien fehlen, kann das Addon ueber
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
-> fuer jeden Checkout lokalen Pfad rekonstruieren
-> wenn manifest.json und Root-Datei vorhanden sind: "Checkout wieder oeffnen"
-> wenn Dateien fehlen: Manifest laden und Dateien erneut herunterladen
```

```text
Checkout wieder oeffnen
-> vorhandenes oder neu geladenes Manifest nutzen
-> Root-Datei aus is_root oeffnen
-> Check-in und Checkout abbrechen fuer diesen Checkout aktivieren
```

## Akzeptanzkriterien

- Der Endpunkt funktioniert fuer Token mit `checkout`-Scope.
- Die Antwort enthaelt nur aktive Checkouts des authentifizierten Users.
- Jeder Checkout enthaelt mindestens `id`, `status`, `project.code`,
  `revision.id` und entweder `manifest_url` oder `manifest`.
- `GET /api/checkouts/<checkout_id>/manifest/` bleibt fuer aktive Checkouts des
  aktuellen Users abrufbar.
- Ein Addon-Neustart verliert serverseitige Locks nicht aus der UI: Nach
  Verbinden kann der User aktive Checkouts sehen und wieder oeffnen.
- Checkouts, die bereits eingecheckt oder abgebrochen wurden, werden nicht als
  aktiv ausgeliefert.

---

# Server API Requirement: Manifest-basierter Multi-Datei-Check-in

## Ziel

Wenn eine ausgecheckte Baugruppe referenzierte FCStd-Dateien enthaelt, kann der
User nicht nur die Root-Datei, sondern auch abhaengige Teile aendern. Beim
Check-in muss das Addon alle geaenderten Dateien aus dem Checkout-Manifest
uebertragen koennen.

Der bisherige Single-File-Check-in bleibt fuer reine Root-Aenderungen
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
-> unveraenderte Dateien nicht hochladen
-> wenn nur Root geaendert ist: bestehenden Single-File-Check-in verwenden
-> wenn referenzierte Dateien geaendert sind: Multi-Datei-Check-in verwenden
```

Vorhandene lokale Checkout-Dateien duerfen beim Wiederaufnehmen eines Checkouts
nicht mit Manifest-Downloads ueberschrieben werden, weil sie lokale Aenderungen
enthalten koennen.

## Server-Verhalten

- Der Server validiert, dass `files_metadata[].path` im Checkout-Manifest
  existiert.
- Der Server validiert, dass `files_metadata[].base_sha256` dem Manifeststand
  entspricht, auf dem der Checkout basiert.
- Unsichere Pfade wie absolute Pfade oder `..` werden abgelehnt.
- Jede hochgeladene Datei muss eine gueltige `.FCStd` sein.
- Fuer jede geaenderte Datei soll der Server eine neue Revision des
  zugehoerigen Teils erzeugen.
- Die Root-Datei ist der Eintrag mit `is_root: true`.
- Wenn nur referenzierte Dateien geaendert sind und die Root-Datei unveraendert
  ist, soll der Server trotzdem den Checkout abschliessen und die erzeugten
  Revisionen in der Antwort ausweisen.
- Bei Konflikten antwortet der Server mit `409 Conflict` und laesst den
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

`revision` bleibt fuer Rueckwaertskompatibilitaet die Root-Revision, sofern
eine Root-Datei eingecheckt wurde.

## Akzeptanzkriterien

- Single-File-Check-in mit `file` funktioniert unveraendert weiter.
- Multi-Datei-Check-in mit `files_metadata` und `file_<n>` funktioniert fuer
  Root- und referenzierte Dateien.
- Unveraenderte Dateien muessen nicht hochgeladen werden.
- Der Server lehnt unbekannte oder unsichere Manifest-Pfade ab.
- Bei erfolgreichem Multi-Datei-Check-in ist der Checkout `completed`.
- Die Antwort enthaelt alle erzeugten Revisionen mit Manifest-Pfadbezug.
