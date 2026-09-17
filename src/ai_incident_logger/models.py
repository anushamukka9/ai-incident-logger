"""Data model for AI incident records.

An incident moves through a strict status lifecycle:

    reported -> triaged -> mitigated -> resolved

with two escape hatches: a triaged incident can be sent back to ``reported``
for more information, a mitigated incident can regress to ``triaged``, and a
resolved incident can be *reopened* (back to ``triaged``) when the fix turns
out to be incomplete. Every transition is appended to the incident's history
so the record keeps a tamper-evident audit trail.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Vocabularies
# ---------------------------------------------------------------------------

class Severity:
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    ALL = (LOW, MEDIUM, HIGH, CRITICAL)

    @classmethod
    def rank(cls, severity: str) -> int:
        return cls.ALL.index(_validate(severity, cls.ALL, "severity"))


class Status:
    REPORTED = "reported"
    TRIAGED = "triaged"
    MITIGATED = "mitigated"
    RESOLVED = "resolved"
    ALL = (REPORTED, TRIAGED, MITIGATED, RESOLVED)


class HarmCategory:
    PRIVACY = "privacy"
    BIAS_DISCRIMINATION = "bias_discrimination"
    PHYSICAL_SAFETY = "physical_safety"
    MISINFORMATION = "misinformation"
    SECURITY = "security"
    ROBUSTNESS = "robustness"
    TRANSPARENCY = "transparency"
    AUTONOMY = "autonomy"
    OTHER = "other"
    ALL = (
        PRIVACY, BIAS_DISCRIMINATION, PHYSICAL_SAFETY, MISINFORMATION,
        SECURITY, ROBUSTNESS, TRANSPARENCY, AUTONOMY, OTHER,
    )


# status -> statuses it is allowed to move to
ALLOWED_TRANSITIONS = {
    Status.REPORTED: {Status.TRIAGED},
    Status.TRIAGED: {Status.REPORTED, Status.MITIGATED},
    Status.MITIGATED: {Status.TRIAGED, Status.RESOLVED},
    Status.RESOLVED: {Status.TRIAGED},  # reopen
}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class IncidentError(Exception):
    """Base class for incident-domain errors."""


class InvalidTransitionError(IncidentError):
    """Raised when a status change is not allowed by the lifecycle."""


class ValidationError(IncidentError):
    """Raised when incident fields fail validation."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _validate(value: str, allowed: tuple, field_name: str) -> str:
    if value not in allowed:
        raise ValidationError(
            f"invalid {field_name} {value!r}; must be one of {sorted(allowed)}"
        )
    return value


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Incident record
# ---------------------------------------------------------------------------

@dataclass
class Incident:
    id: str
    title: str
    description: str
    system: str                      # model / product / deployment that failed
    severity: str                    # one of Severity.ALL
    harm_categories: list            # subset of HarmCategory.ALL
    status: str                      # one of Status.ALL
    reporter: str = ""
    refs: list = field(default_factory=list)      # external links / ticket ids
    created_at: str = ""
    updated_at: str = ""
    history: list = field(default_factory=list)   # [{from,to,at,note}]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Incident":
        return cls(**data)

    def transition(self, to_status: str, note: str = "") -> "Incident":
        """Move the incident to a new status, enforcing the lifecycle."""
        _validate(to_status, Status.ALL, "status")
        allowed = ALLOWED_TRANSITIONS[self.status]
        if to_status not in allowed:
            raise InvalidTransitionError(
                f"cannot move incident {self.id} from {self.status!r} "
                f"to {to_status!r}; allowed: {sorted(allowed)}"
            )
        self.history.append({
            "from": self.status,
            "to": to_status,
            "at": _now(),
            "note": note,
        })
        self.status = to_status
        self.updated_at = _now()
        return self


def new_incident(
    title: str,
    description: str,
    system: str,
    severity: str,
    harm_categories: list | None = None,
    reporter: str = "",
    refs: list | None = None,
) -> Incident:
    """Create and validate a new incident in the ``reported`` state."""
    title = (title or "").strip()
    description = (description or "").strip()
    system = (system or "").strip()
    if not title:
        raise ValidationError("title is required")
    if not description:
        raise ValidationError("description is required")
    if not system:
        raise ValidationError("system is required")
    _validate(severity, Severity.ALL, "severity")
    harms = list(harm_categories or [])
    for harm in harms:
        _validate(harm, HarmCategory.ALL, "harm category")
    now = _now()
    return Incident(
        id=uuid.uuid4().hex[:12],
        title=title,
        description=description,
        system=system,
        severity=severity,
        harm_categories=harms,
        status=Status.REPORTED,
        reporter=reporter.strip(),
        refs=list(refs or []),
        created_at=now,
        updated_at=now,
        history=[{"from": "", "to": Status.REPORTED, "at": now, "note": "incident filed"}],
    )
