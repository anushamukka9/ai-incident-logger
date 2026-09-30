"""JSON export / import of incident records.

Exports are full-fidelity snapshots (every field, including the status-change
history) wrapped in a small envelope with export metadata, so a JSON file is a
complete backup that :func:`load_json` can read back into ``Incident``
objects. :func:`export_csv` writes a flat one-row-per-incident CSV for
spreadsheets and dashboards; it drops the history detail.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone

from .models import Incident

EXPORT_FORMAT = "ai-incident-logger/1"

CSV_COLUMNS = (
    "id", "title", "description", "system", "severity", "status",
    "harm_categories", "reporter", "refs", "related_ids",
    "created_at", "updated_at",
)


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


def export_csv(incidents: list[Incident], path: str) -> str:
    """Write incidents to ``path`` as a flat CSV (one row per incident).

    List fields are joined with ";". The status-change history is not
    included; use :func:`export_json` for the full record.
    """
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for incident in incidents:
            writer.writerow({
                "id": incident.id,
                "title": incident.title,
                "description": incident.description,
                "system": incident.system,
                "severity": incident.severity,
                "status": incident.status,
                "harm_categories": ";".join(incident.harm_categories),
                "reporter": incident.reporter,
                "refs": ";".join(incident.refs),
                "related_ids": ";".join(incident.related_ids),
                "created_at": incident.created_at,
                "updated_at": incident.updated_at,
            })
    return path
