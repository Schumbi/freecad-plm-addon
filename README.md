# FreeCAD-PLM Addon

FreeCAD Workbench fuer das Django-basierte FreeCAD-PLM.

## Status

Grundgeruest fuer die Addon-Entwicklung. Die HTTP- und Workspace-Schicht ist so
angelegt, dass sie ohne FreeCAD getestet werden kann.

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
