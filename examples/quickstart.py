#!/usr/bin/env python3
"""Quickstart example for ai-incident-logger.

Files three incidents into a throwaway database (two of them describing the
same underlying failure in different words), walks one through the status
lifecycle, then prints near-duplicate candidates, a trend report, and a JSON
export.

Run:
    python examples/quickstart.py
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ai_incident_logger import (  # noqa: E402
    HarmCategory,
    IncidentStore,
    Severity,
    Status,
    duplicate_clusters,
    export_json,
    find_duplicates,
    format_report,
    new_incident,
    summarize,
    timeseries,
)


def main() -> None:
    tmpdir = tempfile.mkdtemp(prefix="ailog-quickstart-")
    db_path = os.path.join(tmpdir, "incidents.jsonl")
    store = IncidentStore(db_path)

    # 1. File three incidents; the first two are the same failure mode,
    #    reported twice with different wording.
    incidents = [
        new_incident(
            title="Chatbot leaked a user's phone number",
            description="During a support chat, the assistant pasted the user's phone number into the transcript visible to the agent.",
            system="support-chatbot v3",
            severity=Severity.HIGH,
            harm_categories=[HarmCategory.PRIVACY],
            reporter="agent-ops",
        ),
        new_incident(
            title="Support bot disclosed personal contact details",
            description="The support chatbot revealed a customer's phone number mid-conversation.",
            system="support-chatbot v3",
            severity=Severity.HIGH,
            harm_categories=[HarmCategory.PRIVACY],
            reporter="customer-trust",
        ),
        new_incident(
            title="Resume screener penalized career gaps",
            description="Candidates with parental-leave gaps were scored systematically lower for engineering roles.",
            system="hire-rank 1.2",
            severity=Severity.MEDIUM,
            harm_categories=[HarmCategory.BIAS_DISCRIMINATION],
            reporter="hr-audit",
        ),
    ]
    for incident in incidents:
        store.add(incident)
        print(f"filed {incident.id}  [{incident.severity}] {incident.title}")

    # 2. Walk the first incident through the lifecycle.
    first_id = incidents[0].id
    for status, note in [
        (Status.TRIAGED, "confirmed reproducible; assigned to safety"),
        (Status.MITIGATED, "PII redaction filter deployed"),
        (Status.RESOLVED, "verified on 200 sampled transcripts"),
    ]:
        store.update_status(first_id, status, note=note)
        print(f"  -> {status} ({note})")

    # 3. Near-duplicate detection.
    print("\nNear-duplicate candidates:")
    for pair in find_duplicates(store.all(), threshold=0.4):
        print(f"  {pair['a']} <-> {pair['b']}  score={pair['score']}")
    print("Clusters:", duplicate_clusters(store.all(), threshold=0.4))

    # 4. Trend summary.
    print("\n" + format_report(summarize(store.all()),
                              timeseries(store.all(), bucket="month")))

    # 5. JSON export.
    export_path = os.path.join(tmpdir, "incidents-export.json")
    export_json(store.all(), export_path)
    print(f"Exported {len(store)} incident(s) to {export_path}")
    print(f"(throwaway database lived at {db_path})")


if __name__ == "__main__":
    main()
