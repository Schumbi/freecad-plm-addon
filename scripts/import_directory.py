#!/usr/bin/env python3
"""Launcher for the Nemo directory importer."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from freecad_plm_addon.import_directory import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
