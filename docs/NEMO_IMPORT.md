# Verzeichnisimport aus Nemo

Die Nemo-Actions **„In FreeCAD-PLM importieren“** und **„Diesen Ordner in
FreeCAD-PLM importieren“** importieren einen lokalen Ordner als neues Projekt
oder als neuen Projektstand eines bestehenden Projekts.

Der Import läuft über das Python-CLI
`freecad-plm-addon/scripts/import_directory.py` und verwendet die HTTP-Schicht
des Add-ons. FreeCAD selbst muss dafür nicht laufen.

## Voraussetzungen

- Python 3.10 oder neuer
- `zenity` für die Dialoge
- installiertes FreeCAD-PLM-Add-on mit Token-Konfiguration
- Token-Scopes:
  - neues Projekt: `admin` und PLM-Adminrolle
  - bestehendes Projekt: `write`

## Nemo-Actions installieren

Die Actions liegen im Repo unter `nemo-actions/`. Die vollständige
Installationsanleitung steht in
[`../nemo-actions/README.md`](../nemo-actions/README.md).

Zum Installieren werden die Dateien nach `~/.local/share/nemo/actions/`
kopiert:

- `freecad-plm-import-folder.nemo_action` – ausgewählter Ordner
- `freecad-plm-import-here.nemo_action` – aktueller Ordner über die freie Fläche
- `freecad-plm-import.sh` – Wrapper auf das CLI
- `freecad-plm-import.svg` – Icon

Der Wrapper findet das Repo automatisch, wenn er direkt aus dem Repo gestartet
wird. Für die installierte Kopie verwendet er den in `ADDON_ROOT` hinterlegten
Pfad; alternativ kann `FREECAD_PLM_ADDON_ROOT` gesetzt werden.

## Konfiguration

Standardmäßig werden Server-URL und Token aus der FreeCAD-Parametergruppe
`FreeCADPLM` gelesen:

- `~/.var/app/org.freecad.FreeCAD/config/FreeCAD/v*/user.cfg`
- `~/.config/FreeCAD/user.cfg`
- `~/.config/FreeCAD/v*/user.cfg`
- `~/.FreeCAD/user.cfg`

Alternativ kann eine eigene Datei
`~/.config/freecad-plm/nemo-import.json` verwendet werden:

```json
{
  "server_url": "https://plm.lan.schumbi.de",
  "api_token": "plm_pat_...",
  "exclude_patterns": ["*.tmp"],
  "open_browser": false
}
```

Die Datei sollte nur für den Benutzer lesbar sein. Der Token wird nicht
geloggt und nicht als Kommandozeilenargument an den Serverprozess übergeben.

## Ablauf

1. Ordner prüfen und Dateien zählen.
2. Ziel wählen: neues Projekt oder bestehendes Projekt.
   Zusätzlich: alle Dateien oder nur CAD-Dateien.
3. Bei einem neuen Projekt Code, Name, Projektstand und optional eine
   Beschreibung eingeben. Leere Felder verwenden die Vorschläge aus dem
   Ordnernamen.
4. Bei einem bestehenden Projekt Projekt und Projektstand wählen.
5. Bei mehreren `.FCStd`-Dateien plus STEP/STL die Wurzeldatei auswählen.
6. ZIP lokal erstellen, hochladen und Ergebnis anzeigen.

Der Quellordner wird nicht verändert, nicht verschoben und nicht gelöscht.
Ein Checkout oder Öffnen in FreeCAD ist nicht Teil der Nemo-Action; dafür
bleibt der Importdialog im Add-on zuständig.

## Dateien und Ausschlüsse

Standardmäßig werden alle Dateien importiert. Nicht-CAD-Dateien werden vom
Server als Projektdokumente gespeichert. Mit **Nur CAD-Dateien** werden nur
`.FCStd`, `.step`, `.stp` und `.stl` übertragen.

Ausgeschlossen werden unter anderem:

- `.git`, `.svn`, `.hg`, `__pycache__`
- `*.pyc`, `*.pyo`
- `.DS_Store`, `Thumbs.db`, `desktop.ini`
- Office-/LibreOffice-Sperrdateien
- `checkout.json`
- FreeCAD-Backups wie `*.FCStd1` und `*.FCBak`

Symbolische Links werden nicht verfolgt.

## Serverlimits

Vor dem Upload geprüft:

- maximal 500 MB ZIP
- maximal 2000 Dateien
- maximal 2 GB entpackt
- maximal 200 MB pro Datei

Zusätzlich werden Pfad- und Dateinamenlängen geprüft. Die Werte entsprechen
den Standardwerten des Servers und können bei abweichender Serverkonfiguration
im CLI über die `ScanLimits`-Klasse angepasst werden.

## Kommandozeile

Der Import ist auch ohne Nemo nutzbar:

```bash
python3 freecad-plm-addon/scripts/import_directory.py \
  --folder /pfad/zum/ordner
```

Nur prüfen, ohne Serververbindung:

```bash
python3 scripts/import_directory.py --dry-run --folder /pfad/zum/ordner
```

Nicht interaktiv, beispielsweise für Tests:

```bash
python3 scripts/import_directory.py --yes \
  --server-url http://127.0.0.1:8000 --api-token plm_pat_test \
  --code TEST-1 --name "Testimport" \
  --folder /pfad/zum/ordner
```

Weitere Optionen: `--mode new|existing`, `--project-id`, `--snapshot`,
`--description`, `--cad-only`, `--dependency-root`, `--open-browser`,
`--config`.

## Fehler und Log

Fehler werden als Zenity-Dialog angezeigt. Zusätzlich wird eine kurze
Ereigniszeile ohne Token in

```text
~/.local/state/freecad-plm/nemo-import.log
```

geschrieben.

Typische Meldungen:

- keine `.FCStd`-Datei gefunden
- Token fehlt oder hat nicht den benötigten Scope
- Projektcode bereits vergeben
- ZIP- oder Dateilimit überschritten
- Server nicht erreichbar

## Tests

```bash
cd freecad-plm-addon
python3 -m unittest tests.test_import_directory
```

Die Tests prüfen Dateisammlung, Ausschlüsse, Limits, Code-Ableitung,
Konfigurationsparser, ZIP-Inhalt, Dependency-Root-Logik und die
Zenity-Auswertung. Sie benötigen keine Serververbindung.
