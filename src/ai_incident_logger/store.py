"""Persistent JSONL store for incident records.

Each incident is one JSON object per line, so the file is append-friendly and
stays readable with plain text tools. Incident ids are 12-hex-char prefixes;
``get()`` accepts an unambiguous id prefix for convenience.
"""

from __future__ import annotations

import json
import os

from .models import Incident, InvalidTransitionError


class IncidentNotFoundError(Exception):
    pass


class AmbiguousIdError(Exception):
    pass


class IncidentStore:
    def __init__(self, path: str):
        self.path = os.path.expanduser(path)
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        if not os.path.exists(self.path):
            open(self.path, "a", encoding="utf-8").close()
        self._incidents: dict[str, Incident] = {}
        self._load()

    # -- persistence ------------------------------------------------------
    def _load(self) -> None:
        self._incidents = {}
        with open(self.path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                incident = Incident.from_dict(json.loads(line))
                self._incidents[incident.id] = incident

    def _save(self) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            for incident in self._incidents.values():
                fh.write(json.dumps(incident.to_dict(), ensure_ascii=False) + "\n")
        os.replace(tmp, self.path)

    # -- basic access ------------------------------------------------------
    def add(self, incident: Incident) -> Incident:
        self._incidents[incident.id] = incident
        self._save()
        return incident

    def get(self, id_or_prefix: str) -> Incident:
        matches = [i for i in self._incidents.values()
                   if i.id.startswith(id_or_prefix)]
        if not matches:
            raise IncidentNotFoundError(f"no incident matches {id_or_prefix!r}")
        if len(matches) > 1:
            raise AmbiguousIdError(
                f"{id_or_prefix!r} matches {len(matches)} incidents; "
                "use a longer prefix"
            )
        return matches[0]

    def all(self) -> list[Incident]:
        return sorted(self._incidents.values(), key=lambda i: i.created_at)

    def __len__(self) -> int:
        return len(self._incidents)

    # -- mutation -----------------------------------------------------------
    def update_status(self, id_or_prefix: str, to_status: str, note: str = "") -> Incident:
        """Transition an incident's status (lifecycle rules enforced).

        Raises :class:`InvalidTransitionError` for illegal transitions.
        """
        incident = self.get(id_or_prefix)
        incident.transition(to_status, note=note)
        self._save()
        return incident

    def update_fields(self, id_or_prefix: str, **fields) -> Incident:
        """Edit mutable fields: title, description, system, severity,
        harm_categories, reporter, refs."""
        from .models import HarmCategory, Severity, ValidationError, _now, _validate

        incident = self.get(id_or_prefix)
        editable = {"title", "description", "system", "severity",
                    "harm_categories", "reporter", "refs"}
        unknown = set(fields) - editable
        if unknown:
            raise ValidationError(f"cannot edit field(s): {sorted(unknown)}")
        if "severity" in fields:
            _validate(fields["severity"], Severity.ALL, "severity")
        if "harm_categories" in fields:
            for harm in fields["harm_categories"]:
                _validate(harm, HarmCategory.ALL, "harm category")
        for key, value in fields.items():
            setattr(incident, key, value)
        incident.updated_at = _now()
        self._save()
        return incident

    # -- querying ------------------------------------------------------------
    def query(
        self,
        status: str | None = None,
        severity: str | None = None,
        system: str | None = None,
        harm: str | None = None,
        text: str | None = None,
        min_severity: str | None = None,
    ) -> list[Incident]:
        """Filter incidents. ``text`` matches title/description (case-insensitive)."""
        from .models import Severity

        results = self.all()
        if status:
            results = [i for i in results if i.status == status]
        if severity:
            results = [i for i in results if i.severity == severity]
        if min_severity:
            floor = Severity.rank(min_severity)
            results = [i for i in results if Severity.rank(i.severity) >= floor]
        if system:
            needle = system.lower()
            results = [i for i in results if needle in i.system.lower()]
        if harm:
            results = [i for i in results if harm in i.harm_categories]
        if text:
            needle = text.lower()
            results = [i for i in results
                       if needle in i.title.lower() or needle in i.description.lower()]
        return results
