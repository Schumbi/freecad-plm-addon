# FreeCAD-PLM Addon

FreeCAD Workbench für das Django-basierte FreeCAD-PLM.

Die nutzerorientierte Darstellung für den Addon Manager steht in
[`Resources/Documents/Overview.md`](Resources/Documents/Overview.md).

## Status

Arbeitsfähige FreeCAD-Workbench für den aktuellen PLM-Addon-Workflow. Die
HTTP- und Workspace-Schicht ist so angelegt, dass sie ohne FreeCAD getestet
werden kann.

Aktuell umgesetzt:

- Server verbinden und Projekte, Teile/Baugruppen, Revisionen und aktive
  Checkouts laden.
- Projekte, Teile/Baugruppen und Revisionen platzsparend in einem lazy
  geladenen Baum mit Kontextmenüs durchsuchen. Aktive Checkouts werden direkt
  an ihrer Revision markiert und automatisch aufgeklappt.
- Eine einzige kontextabhängige Arbeitsleiste zeigt zur aktuellen Auswahl die
  wichtigste Aktion; seltenere Aktionen liegen unter `Mehr`.
- Revisionen read-only über ein Server-Manifest öffnen.
- Revisionen auschecken, Manifest-Dateien mit SHA-256 prüfen und Root-Datei in
  FreeCAD öffnen.
- Check-in für Root- und referenzierte Dateien; unveränderte Dateien und
  technische FreeCAD-Speicherartefakte werden nicht als neue Revision
  eingecheckt.
- Checkout abbrechen.
- Projektmetadaten im Addon bearbeiten: Code, Name, Status, Datum und
  Beschreibung.
- Neue Teile/Baugruppen samt leerer FCStd-Revision `R0001` anlegen und direkt öffnen, ohne vorheriges lokales Speichern.
- Revisionsnotizen bearbeiten.
- Anmerkungen lesen, anlegen, bearbeiten, erledigen/wieder öffnen und
  löschen.
- Streng validierte `freecad-plm://revision/...`-Links aus dem Web unter Linux
  und Windows öffnen; Checkout-Links werden vor Ausführung nochmals bestätigt.
- Lokale CAD-Ordner mit FCStd-, STEP- und STL-Dateien als Projektstand oder neues Projekt importieren.
- Aus FCStd-, STEP- und STL-Revisionen projektbezogene Druckprojekte anlegen,
  zusätzliche PLM-Revisionen oder externe STL-Dateien als Quellen zuordnen und
  den gemeinsamen 3MF-Arbeitsstand aus Bambu Studio oder OrcaSlicer
  synchronisieren.

## Code-Struktur

`freecad_plm_addon/panel.py` erstellt das Dock-Widget und stellt die
Einstiegspunkte für die FreeCAD-Befehle bereit. Die Panel-Methoden sind
nach Aufgaben aufgeteilt:

- `panel_state.py` und `panel_browser.py`: Verbindungsstatus, Aktionen und Projektbaum.
- `panel_projects.py` und `panel_parts.py`: Projekte, Teile und Revisionen.
- `panel_annotations.py`: Revisionsdetails, Notizen und Anmerkungen.
- `panel_slicer.py`: Druckprojekte und 3MF-Synchronisation.
- `panel_checkout.py`: Checkout, Check-in und Workspace-Dateien.
- `panel_helpers.py`: gemeinsam genutzte Beschriftungen und Ablaufentscheidungen.

## Konfiguration

Server-URL:

```text
https://plm.lan.schumbi.de
```

Der Server erwartet Bearer Token:

```http
Authorization: Bearer plm_pat_...
```

Für normale CAD-Arbeit einschließlich Teilanlage werden diese Scopes benötigt:

```text
read write checkout
```

`admin` ist zusätzlich nötig für Projektanlage, Projektmetadaten und den
Kombiflow "neues Projekt plus Import". Ohne `admin` funktionieren Lesen,
Checkout/Check-in, Teilanlage, Notizen, Anmerkungen und Import in ein
vorhandenes Projekt.

`Projekt importieren` packt alle `.FCStd`-, `.step`-, `.stp`- und `.stl`-Dateien unterhalb eines gewählten
lokalen Ordners in ein ZIP mit relativen Pfaden. Das Addon kann damit entweder
einen Projektstand in ein vorhandenes Projekt importieren oder ein neues
Projekt mit Code, Name, Status, Datum und Beschreibung anlegen und direkt
befüllen. Nach erfolgreichem Import kann ein importiertes Teil/Baugruppe als
Root ausgewählt und sofort über den normalen Checkout-Workflow geöffnet
werden. Der ursprüngliche Importordner wird auf Wunsch erst danach nach
`~/FreeCAD-PLM/imported/...` verschoben.

Nur FCStd-Revisionen können als Checkout-Root bearbeitet und eingecheckt
werden. STEP/STP werden beim schreibgeschützten Öffnen über FreeCADs
`Import`-Modul und STL über das `Mesh`-Modul in ein neues, nicht gespeichertes
Arbeitsdokument geladen. Sie können außerdem als unveränderte Begleitdateien in
einem FCStd-Checkout liegen.

Der Befehl `PLM-Link öffnen` akzeptiert Revisionslinks aus dem Web-UI. Beim
FreeCAD-Start richtet das Addon das Schema `freecad-plm://` automatisch für den
aktuellen Benutzer ein: unter Linux als XDG-MIME-Handler (auch aus dem
FreeCAD-Flatpak heraus), unter Windows unter `HKCU\Software\Classes`, also ohne
Administratorrechte. Der Menüpunkt `FreeCAD-PLM -> Web-Link-Handler
einrichten` repariert die Zuordnung bei Bedarf.

Der Handler funktioniert sowohl bei geschlossenem als auch bei bereits
laufendem FreeCAD. Dazu übergibt er nicht die URL selbst an FreeCADs
Ein-Instanz-Mechanismus, sondern eine kurzlebige `.FCPLMLink`-Datei. Das Addon
prüft und entfernt diese Datei nach der Übergabe. Links dürfen nur
`project_id`, `part_id` und eine der Aktionen `checkout`, `readonly` oder
`slicer` enthalten; Zugangsdaten werden nie in den Link geschrieben. Je nach
Browser muss die externe Anwendung beim ersten Aufruf bestätigt werden.

`Neues Teil` fragt nur Name, optionale Teilenummer und Typ ab. Das Addon erzeugt
die leere FCStd-Datei intern und übergibt sie direkt an das PLM. Bei einem
geöffneten Projekt-Checkout wird die neue Revision `R0001` dort als zusätzliche
Datei aufgenommen; andernfalls öffnet das Addon einen eigenen Checkout für das
neue Teil. Ein auf dem Server bereits aktiver Projekt-Checkout muss dafür zuerst
im Addon lokal geöffnet werden. Die Aktion benötigt `write` und `checkout`.

### Druckprojekte und Slicer

Unter `Verbindungseinstellungen` wird der Slicer auf `Automatisch erkennen`,
`Bambu Studio`, `OrcaSlicer` oder `Benutzerdefiniert` gestellt. Der
Programmpfad kann leer bleiben; unter Linux erkennt das Addon auch die
Flatpaks `com.bambulab.BambuStudio` und `io.github.softfever.OrcaSlicer`.
Zusätzliche Argumente werden als JSON-Liste, zum Beispiel
`["--single-instance"]`, gespeichert und ohne Shell an den Prozess übergeben.

Nach Auswahl einer FCStd-, STEP- oder STL-Revision startet `Druckprojekt
öffnen/erstellen` den Ablauf. Das Addon sucht ein `PrintProject`, dessen
primäre CAD-Revision der Auswahl entspricht. Existiert keines, legt es ein
Druckprojekt an und führt die Revision als erste, unveränderliche Quelle.
Existieren mehrere Druckprojekte mit dieser Hauptrevision, muss das gewünschte
Projekt anhand von Code, Name und ID ausgewählt werden; ein Abbruch lässt alle
Projekte unverändert.
Optional ausgewählte externe STL-Dateien werden als weitere Quellen im PLM
gespeichert. Weitere PLM-Revisionen lassen sich später mit `Zum Druckprojekt
hinzufügen` zuordnen.

Das Druckprojekt besitzt genau einen veränderlichen 3MF-Arbeitsstand. Beim
ersten Öffnen erzeugt das Addon aus der primären Revision und ihren
Manifest-Abhängigkeiten eine generische 3MF; einen vorhandenen Arbeitsstand
lädt es vom Server. Jedes Druckprojekt erhält unter der primären Revision
einen eigenen lokalen Ordner:

```text
~/FreeCAD-PLM/<server>/<projekt>/slicer-projects/revision-<id>/print-project-<id>/
```

Beim FCStd-Export wählt das Addon sichtbare Geometrie auf der höchsten
sinnvollen Ebene aus. Enthält ein sichtbarer `PartDesign::Body` ein ebenfalls
sichtbares Tip-Feature, wird nur der Body exportiert; dadurch erscheint das
Modell im Slicer nicht doppelt. Unabhängige Körper und Meshes bleiben erhalten.

### Quellen prüfen und 3MF neu erzeugen

Neu erzeugte 3MF enthalten unter `Metadata/freecad_plm_sources.json` den
CAD-Quellenstand: Server ohne Zugangsdaten, Projekt-ID, Hauptrevision und alle
tatsächlich für den Export geladenen CAD-Dateien mit relativem Pfad,
Teil-/Revisions-ID, Revisionscode und SHA-256. Beim Öffnen vergleicht das Addon
diese Angaben mit dem aktuellen Revisionsmanifest. Damit wird auch ein neuer
Deckel erkannt, wenn die Revision der übergeordneten Druckbaugruppe gleich bleibt.

Bei abweichenden Quellen bietet der Dialog `3MF neu erzeugen`,
`Bisherigen Stand öffnen` und `Abbrechen` an. Ältere 3MF ohne Quellenangaben
gelten als **nicht prüfbar**. Dasselbe gilt, wenn ein Slicer die zusätzlichen
Metadaten beim Speichern entfernt; das Addon behauptet dann nicht, die Datei
sei aktuell, und trägt auch keine heutigen Quellen nachträglich als Herkunft ein.
Die Metadaten dokumentieren den CAD-Export der primären Revision, nicht spätere
manuelle Änderungen der Geometrie oder weitere Druckprojektquellen.

`Mehr → 3MF neu erzeugen` ist auch bei unveränderten Quellen verfügbar.
Vor dem Bestätigen das bisherige Projekt im Slicer schließen. Exportiert wird
die ausgewählte **gespeicherte** Revision mit ihren serverseitig aufgelösten
Abhängigkeiten; lokale Checkout-Änderungen müssen vorher eingecheckt werden.
Die Neuerzeugung übernimmt keine Druckeinstellungen, Plattenanordnung,
Farbzuweisungen oder weitere Druckprojektquellen. Sie sichert die bisherige 3MF
und ihre `<datei>.3mf.sync.json` lokal unter `backups/<UTC-Zeitstempel>-<Kennung>/` neben dem
Arbeitsstand. Zum Wiederherstellen die gesicherte 3MF im Slicer öffnen und als
Arbeitsdatei speichern. Erst nach erfolgreichem Export, Prüfung und Sicherung
wird die Arbeitsdatei ersetzt und synchronisiert. Ein fehlgeschlagener Export
oder eine fehlgeschlagene Sicherung lässt die bisherige 3MF unangetastet.

### Slicer-Synchronisation

Eine Dateiüberwachung erkennt anschließend das Speichern im Slicer und lädt
die geänderte Druckprojekt-3MF automatisch hoch. Die zugehörige
`<datei>.3mf.sync.json` enthält nur IDs
und Hashes, keine Zugangsdaten. Beim Öffnen gleicht das Addon lokalen Stand,
zuletzt bekannten Server-Hash und aktuellen Server-Hash ab; bei bereits
auseinandergelaufenen Ständen bleibt die lokale Datei unangetastet.

Beim Hochladen übermittelt das Addon den zuletzt bekannten Server-Hash. Hat
ein anderer Rechner das Druckprojekt inzwischen geändert, weist der Server
den Upload mit HTTP 409 ab und die lokale Datei bleibt zur Konfliktlösung
erhalten. Der
Workflow benötigt die Token-Scopes `read` und `write`, aber keinen Checkout
und keinen zusätzlichen Hintergrunddienst.

Download-URLs und Weiterleitungen müssen dieselbe Origin wie der konfigurierte
PLM-Server besitzen. Das Addon sendet den API-Token weder an andere Hosts oder
Ports noch bei einem Wechsel von HTTPS auf HTTP.

## Tests

`tests/test_review_regressions.py` prüft zusätzlich die Sicherheits- und
Synchronisationsgrenzen aus dem Review vom 2026-09-16. Die behobenen Befunde
bleiben dort als normale Regressionstests erhalten.
Die Netzwerkprüfungen verwenden nur temporäre Loopback-Server und Dummy-Tokens.

Bei Schnittstellenänderungen außerdem im Server-Repository
`python scripts/run_contract_tests.py` ausführen (Linux: `python3`). Dieser
separate Lauf prüft den echten Addon-Client gegen einen Django-Testserver,
einschließlich JSON, Multipart, Downloads und Fehlerzuordnung. Das Addon wird
standardmäßig im Nachbarverzeichnis gesucht; alternativ `--addon PFAD` angeben.

Der plattformunabhängige Teststarter prüft zuerst die Python-Quellen und führt
danach die vollständige Unit-Test-Suite aus:

Windows 11:

```powershell
python scripts/run_tests.py
```

Linux Mint:

```bash
python3 scripts/run_tests.py
```

Python 3.10 oder neuer genügt; FreeCAD muss für die Unit-Tests nicht
installiert sein.

## Installation über den FreeCAD Addon Manager

Das Repo enthält ein `package.xml` für den FreeCAD Addon Manager. In FreeCAD
kann das Addon als benutzerdefiniertes Repository installiert werden.

Repository-URL:

```text
https://git.home.schumbi.de/ralf/freecad-plm-addon
```

Branch:

```text
main
```

Danach FreeCAD neu starten und die Workbench `FreeCAD-PLM` aktivieren. Beim
Start wird zugleich der Web-Link-Handler für Linux oder Windows eingerichtet.
Für die Nutzung muss anschließend im Addon unter `Verbindungseinstellungen`
die Server-URL, ein API-Token und der lokale Workspace gesetzt werden.

Die serverseitige Forgejo- und Reverse-Proxy-Konfiguration für eine Installation
mit einem unveränderten FreeCAD ist in
[`docs/ADDON_MANAGER_HOSTING.md`](docs/ADDON_MANAGER_HOSTING.md) dokumentiert.

## FreeCAD-Installation für die Entwicklung

FreeCAD lädt externe Workbenches aus seinem Benutzer-`Mod`-Verzeichnis.
Der robusteste Weg ist, den Pfad in der jeweiligen FreeCAD-Installation direkt
abzufragen:

```python
import FreeCAD as App
App.getUserAppDataDir()
```

Das Addon muss dann als Ordner `Mod/freecad-plm-addon` unter diesem Pfad
liegen.

### Linux: Flatpak

Auf diesem Rechner wird FreeCAD per Flatpak gestartet:

```bash
/usr/bin/flatpak run --branch=stable --arch=x86_64 --command=FreeCAD --file-forwarding org.freecad.FreeCAD - --single-instance @@ %F @@
```

Der lokale FreeCAD-1.1-User-AppData-Pfad ist:

```text
~/.var/app/org.freecad.FreeCAD/data/FreeCAD/v1-1/
```

Für die Entwicklung kann das Repo dorthin verlinkt werden:

```bash
mkdir -p ~/.var/app/org.freecad.FreeCAD/data/FreeCAD/v1-1/Mod
ln -s /home/ralf/devel/freecad-plm/freecad-plm-addon \
  ~/.var/app/org.freecad.FreeCAD/data/FreeCAD/v1-1/Mod/freecad-plm-addon
```

Falls der Link schon existiert:

```bash
ls -l ~/.var/app/org.freecad.FreeCAD/data/FreeCAD/v1-1/Mod/freecad-plm-addon
```

### Linux: klassische Installation

Bei einer nicht-Flatpak-Installation ist der Pfad typischerweise:

```bash
mkdir -p ~/.local/share/FreeCAD/Mod
ln -s /home/ralf/devel/freecad-plm/freecad-plm-addon \
  ~/.local/share/FreeCAD/Mod/freecad-plm-addon
```

### Windows: FreeCAD `.exe`

In FreeCADs Python-Konsole zuerst den Benutzerpfad abfragen:

```python
import FreeCAD as App
App.getUserAppDataDir()
```

Dann das Addon als Ordner in dessen `Mod`-Unterordner kopieren, zum Beispiel:

```text
%APPDATA%\FreeCAD\Mod\freecad-plm-addon
```

oder bei versionierten FreeCAD-Profilen:

```text
%APPDATA%\FreeCAD\v1-1\Mod\freecad-plm-addon
```
