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
- Lokale CAD-Ordner mit FCStd-, STEP- und STL-Dateien als Projektstand oder neues Projekt importieren.

## Konfiguration

Server-URL:

```text
https://plm.lan.schumbi.de
```

Der Server erwartet Bearer Token:

```http
Authorization: Bearer plm_pat_...
```

Für den vollständigen Addon-Workflow werden typischerweise diese Scopes
benötigt:

```text
read write checkout admin
```

Ohne `admin` funktionieren Lesen, Checkout/Check-in, Notizen, Anmerkungen und
Import in ein vorhandenes Projekt. `admin` ist nötig für Projektanlage,
Projektmetadaten und den Kombiflow "neues Projekt plus Import".

`Projekt importieren` packt alle `.FCStd`-, `.step`-, `.stp`- und `.stl`-Dateien unterhalb eines gewählten
lokalen Ordners in ein ZIP mit relativen Pfaden. Das Addon kann damit entweder
einen Projektstand in ein vorhandenes Projekt importieren oder ein neues
Projekt mit Code, Name, Status, Datum und Beschreibung anlegen und direkt
befüllen. Nach erfolgreichem Import kann ein importiertes Teil/Baugruppe als
Root ausgewählt und sofort über den normalen Checkout-Workflow geöffnet
werden. Der ursprüngliche Importordner wird auf Wunsch erst danach nach
`~/FreeCAD-PLM/imported/...` verschoben.

Nur FCStd-Revisionen können als Checkout-Root bearbeitet und eingecheckt werden. STEP/STL lassen sich schreibgeschützt öffnen und können als unveränderte Begleitdateien in einem FCStd-Checkout liegen.

`Neues Teil` fragt nur Name, optionale Teilenummer und Typ ab. Das Addon erzeugt
die leere FCStd-Datei intern und übergibt sie direkt an das PLM. Bei einem
geöffneten Projekt-Checkout wird die neue Revision `R0001` dort als zusätzliche
Datei aufgenommen; andernfalls öffnet das Addon einen eigenen Checkout für das
neue Teil.

## Tests

```bash
python3 -m unittest discover -s tests
```

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

Danach FreeCAD neu starten und die Workbench `FreeCAD-PLM` aktivieren. Für die
Nutzung muss anschließend im Addon unter `Verbindungseinstellungen` die
Server-URL, ein API-Token und der lokale Workspace gesetzt werden.

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
ln -s /home/ralf/devel/freecad-plm-addon \
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
ln -s /home/ralf/devel/freecad-plm-addon \
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
