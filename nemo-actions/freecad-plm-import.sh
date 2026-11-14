#!/usr/bin/env bash
# Nemo wrapper for the FreeCAD-PLM directory importer.
set -u

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if [ -n "${FREECAD_PLM_ADDON_ROOT:-}" ]; then
  ADDON_ROOT=$FREECAD_PLM_ADDON_ROOT
elif [ -f "$SCRIPT_DIR/../scripts/import_directory.py" ]; then
  ADDON_ROOT=$(cd -- "$SCRIPT_DIR/.." && pwd)
else
  # Default for the local installation in ~/.local/share/nemo/actions.
  ADDON_ROOT=/home/ralf/devel/freecad-plm/freecad-plm-addon
fi

exec python3 "$ADDON_ROOT/scripts/import_directory.py" "$@"
