"""FreeCAD importer for one-shot files created by the protocol launcher."""

from pathlib import Path

from .deeplink import parse_revision_deep_link
from .protocol_handler import LINK_FILE_MAGIC, LINK_FILE_SUFFIX


def read_link_file(filename):
    path = Path(filename)
    if path.suffix.lower() != LINK_FILE_SUFFIX.lower():
        raise ValueError("Kein FreeCAD-PLM-Linkformat.")
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) != 2 or lines[0] != LINK_FILE_MAGIC:
        raise ValueError("Ungültige FreeCAD-PLM-Linkdatei.")
    value = lines[1].strip()
    parse_revision_deep_link(value)
    return value


def open(filename):
    """Consume a link file through FreeCAD's standard import dispatch."""

    path = Path(filename)
    value = read_link_file(path)
    try:
        from .deeplink_runtime import queue_deep_link

        queue_deep_link(value)
    finally:
        try:
            path.unlink()
        except OSError:
            pass


def insert(filename, _document_name):
    open(filename)
