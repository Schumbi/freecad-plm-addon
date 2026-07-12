# FreeCAD-PLM Addon

FreeCAD Workbench fuer das Django-basierte FreeCAD-PLM.

## Status

Arbeitsfaehige FreeCAD-Workbench fuer den aktuellen PLM-Addon-Workflow. Die
HTTP- und Workspace-Schicht ist so angelegt, dass sie ohne FreeCAD getestet
werden kann.

Aktuell umgesetzt:

- Server verbinden und Projekte, Teile/Baugruppen, Revisionen und aktive
  Checkouts laden.
- Revisionen read-only ueber ein Server-Manifest oeffnen.
- Revisionen auschecken, Manifest-Dateien mit SHA-256 pruefen und Root-Datei in
  FreeCAD oeffnen.
- Check-in fuer Root- und referenzierte Dateien; unveraenderte Dateien und
  technische FreeCAD-Speicherartefakte werden nicht als neue Revision
  eingecheckt.
- Checkout abbrechen.
- Projektmetadaten im Addon bearbeiten: Code, Name, Status, Datum und
  Beschreibung.
- Neue Teile/Baugruppen als PLM-Metadatensatz anlegen.
- Revisionsnotizen bearbeiten.
- Anmerkungen lesen, anlegen, bearbeiten, erledigen/wieder oeffnen und
  loeschen.
- Lokale FreeCAD-Ordner als Projektstand oder neues Projekt importieren.

## Konfiguration

Server-URL:

```text
https://plm.lan.schumbi.de
```

Der Server erwartet Bearer Token:

```http
Authorization: Bearer plm_pat_...
```

Fuer den vollstaendigen Addon-Workflow werden typischerweise diese Scopes
benoetigt:

```text
read write checkout admin
```

Ohne `admin` funktionieren Lesen, Checkout/Check-in, Notizen, Anmerkungen und
Import in ein vorhandenes Projekt. `admin` ist noetig fuer Projektanlage,
Projektmetadaten und den Kombiflow "neues Projekt plus Import".

`Projekt importieren` packt alle `.FCStd`-Dateien unterhalb eines gewaehlten
lokalen Ordners in ein ZIP mit relativen Pfaden. Das Addon kann damit entweder
einen Projektstand in ein vorhandenes Projekt importieren oder ein neues
Projekt mit Code, Name, Status, Datum und Beschreibung anlegen und direkt
befuellen. Nach erfolgreichem Import kann ein importiertes Teil/Baugruppe als
Root ausgewaehlt und sofort ueber den normalen Checkout-Workflow geoeffnet
werden. Der urspruengliche Importordner wird auf Wunsch erst danach nach
`~/FreeCAD-PLM/imported/...` verschoben.

## Tests

```bash
python3 -m unittest discover -s tests
```

## Installation ueber den FreeCAD Addon Manager

Das Repo enthaelt ein `package.xml` fuer den FreeCAD Addon Manager. In FreeCAD
kann das Addon als benutzerdefiniertes Repository installiert werden.

Repository-URL:

```text
ssh://forgejo@home.schumbi.de/ralf/freecad-plm-addon.git
```

Danach FreeCAD neu starten und die Workbench `FreeCAD-PLM` aktivieren. Fuer die
Nutzung muss anschliessend im Addon unter `Verbindungseinstellungen` die
Server-URL, ein API-Token und der lokale Workspace gesetzt werden.

## FreeCAD Installation Fuer Entwicklung

FreeCAD laedt externe Workbenches aus seinem Benutzer-`Mod`-Verzeichnis.
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

Fuer die Entwicklung kann das Repo dorthin verlinkt werden:

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
