"""Aging and staleness reports for open incidents.

Answers "what has been sitting too long?" An incident counts as stale when
it has been open longer than ``stale_days`` *in its current status*, which
catches both un-triaged reports and mitigations that were never verified.
All helpers accept an explicit ``now`` (ISO-8601 string or datetime) so
reports are reproducible in tests.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .models import Incident, Status


def _parse_ts(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _now_dt(now=None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if isinstance(now, datetime):
        return now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    return _parse_ts(now)


def age_days(incident: Incident, now=None) -> float:
    """Days since the incident was filed."""
    return (_now_dt(now) - _parse_ts(incident.created_at)).total_seconds() / 86400


def time_in_status_days(incident: Incident, now=None) -> float:
    """Days since the incident last changed status.

    The status history is append-only, so the last entry marks the most
    recent move (or the filing, for a fresh report).
    """
    if incident.history:
        last_move = _parse_ts(incident.history[-1]["at"])
    else:
        last_move = _parse_ts(incident.created_at)
    return (_now_dt(now) - last_move).total_seconds() / 86400


def stale_incidents(
    incidents: list[Incident], stale_days: float = 7.0, now=None
) -> list[dict]:
    """Open incidents sitting in their current status too long.

    Returns dicts with the incident and its ages, sorted worst-first.
    Resolved incidents are never stale.
    """
    stale = []
    for incident in incidents:
        if incident.status == Status.RESOLVED:
            continue
        stuck = time_in_status_days(incident, now)
        if stuck >= stale_days:
            stale.append({
                "incident": incident,
                "age_days": round(age_days(incident, now), 1),
                "stuck_days": round(stuck, 1),
            })
    stale.sort(key=lambda row: row["stuck_days"], reverse=True)
    return stale


def format_aging(
    incidents: list[Incident], stale_days: float = 7.0, now=None
) -> str:
    """Render a plain-text aging report."""
    open_incidents = [i for i in incidents if i.status != Status.RESOLVED]
    stale = stale_incidents(incidents, stale_days=stale_days, now=now)
    lines = [
        "AI incident aging report",
        "=" * 40,
        f"open incidents : {len(open_incidents)}",
        f"stale (>={stale_days:g}d in current status): {len(stale)}",
        "",
    ]
    if not stale:
        lines.append("nothing stale. all open incidents are moving.")
        return "\n".join(lines)
    header = f"  {'id':<12} {'stuck':>7} {'age':>7}  {'severity':<8} {'status':<9} title"
    lines.append(header)
    for row in stale:
        incident = row["incident"]
        lines.append(
            f"  {incident.id:<12} {row['stuck_days']:>6.1f}d {row['age_days']:>6.1f}d  "
            f"{incident.severity:<8} {incident.status:<9} {incident.title}"
        )
    return "\n".join(lines)
