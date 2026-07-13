# Hosting für den FreeCAD Addon Manager

Dieses Dokument beschreibt die serverseitige Konfiguration, mit der ein
unverändertes FreeCAD das Addon allein über die Repository-URL und den Branch
installieren kann.

## Ziel

Im FreeCAD Addon Manager wird ein benutzerdefiniertes Repository eingetragen:

```text
Repository: https://git.home.schumbi.de/ralf/freecad-plm-addon
Branch: main
```

Es sind keine lokalen Git-Ausnahmen, Symlinks oder manuellen Kopien in das
FreeCAD-`Mod`-Verzeichnis erforderlich.

## Hintergrund

FreeCAD 1.1 behandelt unbekannte Git-Hosts wie eine selbst gehostete
GitLab-Instanz. Für ein benutzerdefiniertes Repository leitet der Addon Manager
deshalb diese Pfade ab:

```text
/-/raw/<branch>/<file>
/-/blob/<branch>/<file>
/-/archive/<branch>/<repository>-<branch>.zip
```

Forgejo verwendet stattdessen:

```text
/raw/branch/<branch>/<file>
/src/branch/<branch>/<file>
/archive/<branch>.zip
```

Die `package.xml` kann das für die Erstinstallation nicht korrigieren. Sie wird
bei einem benutzerdefinierten Repository erst nach dem Herunterladen lokal
gelesen und kennt keinen separaten URL-Typ für ein Installationsarchiv.

## Nginx Proxy Manager

Im Proxy Host für `git.home.schumbi.de` unter `Advanced` stehen diese Regeln:

```nginx
location ~ ^/ralf/freecad-plm-addon/-/raw/([^/]+)/(.*)$ {
    return 302 /ralf/freecad-plm-addon/raw/branch/$1/$2;
}

location ~ ^/ralf/freecad-plm-addon/-/blob/([^/]+)/(.*)$ {
    return 302 /ralf/freecad-plm-addon/src/branch/$1/$2;
}

location = /ralf/freecad-plm-addon/-/archive/main/freecad-plm-addon-main.zip {
    return 302 /ralf/freecad-plm-addon/archive/main.zip;
}
```

Die Regeln speichern keine Addon-Dateien im Nginx Proxy Manager. Sie leiten
ausschließlich auf die von Forgejo bereitgestellten Repository-Pfade um.

## Forgejo

Forgejo legt standardmäßig alle Dateien eines Repository-Archivs in einen
zusätzlichen Ordner. FreeCAD würde dadurch zum Beispiel so installieren:

```text
Mod/freecad-plm-addon/freecad-plm-addon/InitGui.py
```

Die Workbench wird in dieser Struktur nicht gefunden. In der Forgejo-`app.ini`
muss deshalb im vorhandenen oder neuen Abschnitt `repository` stehen:

```ini
[repository]
PREFIX_ARCHIVE_FILES = false
```

Diese Einstellung gilt für alle von der Forgejo-Instanz erzeugten
Repository-Archive. Nach der Änderung:

1. Forgejo neu starten.
2. Im Forgejo-Adminbereich unter den Wartungsoperationen die erzeugten
   Repository-Archive löschen.
3. Das Archiv erneut abrufen, damit Forgejo es mit der neuen Einstellung
   erzeugt.

## Prüfung

README und Archiv müssen über FreeCADs abgeleitete URLs erreichbar sein:

```bash
curl -fL \
  https://git.home.schumbi.de/ralf/freecad-plm-addon/-/raw/main/README.md

curl -fL \
  -o /tmp/freecad-plm-addon-main.zip \
  https://git.home.schumbi.de/ralf/freecad-plm-addon/-/archive/main/freecad-plm-addon-main.zip

unzip -t /tmp/freecad-plm-addon-main.zip
unzip -Z1 /tmp/freecad-plm-addon-main.zip | sed -n '1,20p'
```

Im Archiv müssen `Init.py`, `InitGui.py`, `package.xml` und das Verzeichnis
`freecad_plm_addon/` direkt auf oberster Ebene liegen. Ein zusätzlicher
Wurzelordner `freecad-plm-addon/` ist falsch.

## Installation testen

1. In FreeCAD den Addon Manager öffnen.
2. Unter den Einstellungen das benutzerdefinierte Repository und `main`
   eintragen.
3. Den Addon Manager neu laden und `freecad-plm-addon` installieren.
4. FreeCAD vollständig neu starten.
5. Die Workbench `FreeCAD-PLM` auswählen.

Wenn FreeCAD eine erfolgreiche Installation meldet, aber keine Workbench
anzeigt, zuerst die innere ZIP-Struktur prüfen. Das ist das typische Symptom
für ein noch aktives `PREFIX_ARCHIVE_FILES = true` oder ein altes, von Forgejo
zwischengespeichertes Archiv.
