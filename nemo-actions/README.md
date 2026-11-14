# Nemo-Actions für den FreeCAD-PLM-Import

Diese Dateien sind die installationsfertige Kopie der Nemo-Actions für den
Verzeichnisimport. Sie gehören **nicht** zur FreeCAD-Workbench und werden nicht
vom Add-on Manager installiert.

## Dateien

- `freecad-plm-import-folder.nemo_action` – ausgewählten Ordner importieren
- `freecad-plm-import-here.nemo_action` – aktuellen Ordner über die freie Fläche importieren
- `freecad-plm-import.sh` – Wrapper auf `scripts/import_directory.py`
- `freecad-plm-import.svg` – Icon

## Installation

```bash
cd /home/ralf/devel/freecad-plm/freecad-plm-addon

mkdir -p ~/.local/share/nemo/actions
cp nemo-actions/freecad-plm-import-folder.nemo_action \
   nemo-actions/freecad-plm-import-here.nemo_action \
   nemo-actions/freecad-plm-import.sh \
   nemo-actions/freecad-plm-import.svg \
   ~/.local/share/nemo/actions/
chmod +x ~/.local/share/nemo/actions/freecad-plm-import.sh
```

Der Wrapper findet das Add-on-Repo automatisch, wenn er direkt aus dem Repo
gestartet wird. Für die installierte Kopie unter
`~/.local/share/nemo/actions/` wird der Pfad aus der Zeile `ADDON_ROOT`
verwendet. Wenn das Repo woanders liegt, entweder diese Zeile anpassen oder
die Umgebungsvariable `FREECAD_PLM_ADDON_ROOT` setzen:

```bash
export FREECAD_PLM_ADDON_ROOT=/pfad/zum/freecad-plm-addon
```

Nemo neu starten, damit die Actions sicher geladen werden:

```bash
nemo --quit && nemo &
```

## Nutzung

- Ordner markieren → Rechtsklick → **In FreeCAD-PLM importieren**
- Freie Fläche im Ordner → Rechtsklick → **Diesen Ordner in FreeCAD-PLM importieren**

Der Import benötigt einen Ordner mit mindestens einer `.FCStd`-Datei.
Server-URL und Token werden aus der FreeCAD-Addon-Konfiguration gelesen.
Details zum Ablauf, zu den Ausschlüssen und zu den Token-Scopes stehen in
[`../docs/NEMO_IMPORT.md`](../docs/NEMO_IMPORT.md).

## Test ohne Upload

```bash
./nemo-actions/freecad-plm-import.sh --dry-run \
  --folder /pfad/zu/einem/projektordner
```

## Deinstallation

```bash
rm -f ~/.local/share/nemo/actions/freecad-plm-import-folder.nemo_action \
      ~/.local/share/nemo/actions/freecad-plm-import-here.nemo_action \
      ~/.local/share/nemo/actions/freecad-plm-import.sh \
      ~/.local/share/nemo/actions/freecad-plm-import.svg
nemo --quit && nemo &
```
