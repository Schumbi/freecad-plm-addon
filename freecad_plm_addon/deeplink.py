from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit


DEEPLINK_SCHEME = "freecad-plm"
DEEPLINK_ACTIONS = {"checkout", "readonly", "slicer"}


@dataclass(frozen=True)
class RevisionDeepLink:
    project_id: int
    part_id: int
    revision_id: int
    action: str


def parse_revision_deep_link(value):
    parsed = urlsplit(str(value or "").strip())
    if parsed.scheme.lower() != DEEPLINK_SCHEME or parsed.netloc != "revision":
        raise ValueError("Kein unterstützter FreeCAD-PLM-Link.")
    if parsed.fragment:
        raise ValueError("FreeCAD-PLM-Links dürfen keinen Fragmentteil enthalten.")
    query = parse_qs(parsed.query, keep_blank_values=False, strict_parsing=True)
    if set(query) - {"project_id", "part_id", "action"}:
        raise ValueError("FreeCAD-PLM-Link enthält unbekannte Parameter.")
    if any(len(values) != 1 for values in query.values()):
        raise ValueError("FreeCAD-PLM-Link enthält mehrdeutige Parameter.")
    try:
        revision_id = int(parsed.path.strip("/"))
        project_id = int(query["project_id"][0])
        part_id = int(query["part_id"][0])
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        raise ValueError("FreeCAD-PLM-Link enthält ungültige IDs.") from exc
    if min(project_id, part_id, revision_id) < 1:
        raise ValueError("FreeCAD-PLM-Link enthält ungültige IDs.")
    action = (query.get("action") or ["checkout"])[0]
    if action not in DEEPLINK_ACTIONS:
        raise ValueError("FreeCAD-PLM-Link enthält eine unbekannte Aktion.")
    return RevisionDeepLink(project_id, part_id, revision_id, action)


def deep_link_from_argv(arguments):
    for argument in arguments or []:
        if str(argument).lower().startswith(f"{DEEPLINK_SCHEME}://"):
            return parse_revision_deep_link(argument)
    return None
