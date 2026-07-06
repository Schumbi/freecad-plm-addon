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
