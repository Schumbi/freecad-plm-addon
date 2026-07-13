# Hosting fuer den FreeCAD Addon Manager

Dieses Dokument beschreibt die serverseitige Konfiguration, mit der ein
unveraendertes FreeCAD das Addon allein ueber die Repository-URL und den Branch
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
GitLab-Instanz. Fuer ein benutzerdefiniertes Repository leitet der Addon Manager
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

Die `package.xml` kann das fuer die Erstinstallation nicht korrigieren. Sie wird
bei einem benutzerdefinierten Repository erst nach dem Herunterladen lokal
gelesen und kennt keinen separaten URL-Typ fuer ein Installationsarchiv.

## Nginx Proxy Manager

Im Proxy Host fuer `git.home.schumbi.de` unter `Advanced` stehen diese Regeln:

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
ausschliesslich auf die von Forgejo bereitgestellten Repository-Pfade um.

## Forgejo

Forgejo legt standardmaessig alle Dateien eines Repository-Archivs in einen
zusaetzlichen Ordner. FreeCAD wuerde dadurch zum Beispiel so installieren:

```text
Mod/freecad-plm-addon/freecad-plm-addon/InitGui.py
```

Die Workbench wird in dieser Struktur nicht gefunden. In der Forgejo-`app.ini`
muss deshalb im vorhandenen oder neuen Abschnitt `repository` stehen:

```ini
[repository]
PREFIX_ARCHIVE_FILES = false
```

Diese Einstellung gilt fuer alle von der Forgejo-Instanz erzeugten
Repository-Archive. Nach der Aenderung:

1. Forgejo neu starten.
2. Im Forgejo-Adminbereich unter den Wartungsoperationen die erzeugten
   Repository-Archive loeschen.
3. Das Archiv erneut abrufen, damit Forgejo es mit der neuen Einstellung
   erzeugt.

## Pruefung

README und Archiv muessen ueber FreeCADs abgeleitete URLs erreichbar sein:

```bash
curl -fL \
  https://git.home.schumbi.de/ralf/freecad-plm-addon/-/raw/main/README.md

curl -fL \
  -o /tmp/freecad-plm-addon-main.zip \
  https://git.home.schumbi.de/ralf/freecad-plm-addon/-/archive/main/freecad-plm-addon-main.zip

unzip -t /tmp/freecad-plm-addon-main.zip
unzip -Z1 /tmp/freecad-plm-addon-main.zip | sed -n '1,20p'
```

Im Archiv muessen `Init.py`, `InitGui.py`, `package.xml` und das Verzeichnis
`freecad_plm_addon/` direkt auf oberster Ebene liegen. Ein zusaetzlicher
Wurzelordner `freecad-plm-addon/` ist falsch.

## Installation testen

1. In FreeCAD den Addon Manager oeffnen.
2. Unter den Einstellungen das benutzerdefinierte Repository und `main`
   eintragen.
3. Den Addon Manager neu laden und `freecad-plm-addon` installieren.
4. FreeCAD vollstaendig neu starten.
5. Die Workbench `FreeCAD-PLM` auswaehlen.

Wenn FreeCAD eine erfolgreiche Installation meldet, aber keine Workbench
anzeigt, zuerst die innere ZIP-Struktur pruefen. Das ist das typische Symptom
fuer ein noch aktives `PREFIX_ARCHIVE_FILES = true` oder ein altes, von Forgejo
zwischengespeichertes Archiv.
