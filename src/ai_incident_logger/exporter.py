"""JSON export / import of incident records.

Exports are full-fidelity snapshots (every field, including the status-change
history) wrapped in a small envelope with export metadata, so a JSON file is a
complete backup that :func:`load_json` can read back into ``Incident``
objects.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from .models import Incident

EXPORT_FORMAT = "ai-incident-logger/1"


def export_json(incidents: list[Incident], path: str, indent: int = 2) -> str:
    """Write incidents to ``path`` as a versioned JSON document.

    Returns the path written.
    """
    doc = {
        "format": EXPORT_FORMAT,
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": len(incidents),
        "incidents": [i.to_dict() for i in incidents],
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=indent, ensure_ascii=False)
        fh.write("\n")
    return path


def load_json(path: str) -> list[Incident]:
    """Read a file written by :func:`export_json` back into incidents."""
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    if doc.get("format") != EXPORT_FORMAT:
        raise ValueError(
            f"unsupported export format {doc.get('format')!r}; "
            f"expected {EXPORT_FORMAT!r}"
        )
    return [Incident.from_dict(item) for item in doc.get("incidents", [])]


def export_json_string(incidents: list[Incident]) -> str:
    """Serialize incidents to a JSON string (same envelope, no file)."""
    doc = {
        "format": EXPORT_FORMAT,
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": len(incidents),
        "incidents": [i.to_dict() for i in incidents],
    }
    return json.dumps(doc, ensure_ascii=False)
