#!/usr/bin/env python3
"""SLA review example for ai-incident-logger.

Seeds a throwaway database with incidents at various ages and stages, then
prints the aging report: which open incidents have been stuck in their
current status past the SLA, and for how long.

Run:
    python examples/sla_review.py
"""

import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ai_incident_logger import (  # noqa: E402
    HarmCategory,
    IncidentStore,
    Severity,
    format_aging,
    new_incident,
    stale_incidents,
)


def backdate(incident, *, filed_days_ago: int):
    """Pretend the incident was filed N days ago (demo data only)."""
    filed = datetime.now(timezone.utc) - timedelta(days=filed_days_ago)
    stamp = filed.isoformat(timespec="seconds")
    incident.created_at = stamp
    incident.updated_at = stamp
    for event in incident.history:
        event["at"] = stamp
    return incident


def main() -> None:
    tmpdir = tempfile.mkdtemp(prefix="ailog-sla-")
    store = IncidentStore(os.path.join(tmpdir, "incidents.jsonl"))

    # A fresh critical report: not stale.
    fresh = store.add(backdate(new_incident(
        title="Model refused emergency dispatch request",
        description="The triage assistant declined to escalate a 911-adjacent call.",
        system="dispatch-assistant 2.0",
        severity=Severity.CRITICAL,
        harm_categories=[HarmCategory.PHYSICAL_SAFETY],
    ), filed_days_ago=1))
    store.update_status(fresh.id, "triaged", note="on-call paged")

    # A high-severity report filed 20 days ago and never triaged: stale.
    store.add(backdate(new_incident(
        title="Loan model rejected applicants by zip code",
        description="Approval rates correlate strongly with zip code in the pilot region.",
        system="credit-scorer 1.4",
        severity=Severity.HIGH,
        harm_categories=[HarmCategory.BIAS_DISCRIMINATION],
    ), filed_days_ago=20))

    # Triaged 12 days ago, mitigation never verified: stale in triaged.
    stuck = store.add(backdate(new_incident(
        title="Translation model dropped negation",
        description="Negated clauses were translated as affirmations in medical leaflets.",
        system="translate-x 3.1",
        severity=Severity.HIGH,
        harm_categories=[HarmCategory.MISINFORMATION],
    ), filed_days_ago=30))
    store.update_status(stuck.id, "triaged", note="reproduced on 50 samples")
    stuck = store.get(stuck.id)
    old = (datetime.now(timezone.utc) - timedelta(days=12)).isoformat(timespec="seconds")
    stuck.history[-1]["at"] = old
    stuck.updated_at = old
    store._save()

    print(format_aging(store.all(), stale_days=7.0))
    print()
    stale = stale_incidents(store.all(), stale_days=7.0)
    print(f"{len(stale)} stale incident(s); worst first:")
    for row in stale:
        print(f"  {row['incident'].id} stuck {row['stuck_days']}d "
              f"in {row['incident'].status!r}: {row['incident'].title}")


if __name__ == "__main__":
    main()
