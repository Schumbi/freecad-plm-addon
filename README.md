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

## Tests

```bash
python3 -m unittest discover -s tests
```

## FreeCAD Installation Fuer Entwicklung

Dieses Verzeichnis kann in FreeCADs `Mod`-Verzeichnis verlinkt werden:

```bash
ln -s /home/ralf/devel/freecad-plm-addon ~/.local/share/FreeCAD/Mod/freecad-plm-addon
```
