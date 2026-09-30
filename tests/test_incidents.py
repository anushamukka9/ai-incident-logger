"""Test suite for ai-incident-logger."""

import json
import os
import subprocess
import sys

import pytest

from ai_incident_logger import (
    HarmCategory,
    IncidentStore,
    InvalidTransitionError,
    Severity,
    Status,
    ValidationError,
    duplicate_clusters,
    export_json,
    find_duplicates,
    load_json,
    new_incident,
    summarize,
    timeseries,
)


def make_incident(title="Model leaked PII in chat", system="chatbot v2",
                  severity=Severity.HIGH, harms=None, description=None):
    return new_incident(
        title=title,
        description=description or "The assistant disclosed a user's phone number in a chat transcript.",
        system=system,
        severity=severity,
        harm_categories=harms or [HarmCategory.PRIVACY],
        reporter="safety-team",
    )


def test_file_and_retrieve(tmp_path):
    store = IncidentStore(str(tmp_path / "incidents.jsonl"))
    incident = make_incident()
    store.add(incident)

    fetched = store.get(incident.id)
    assert fetched.title == "Model leaked PII in chat"
    assert fetched.status == Status.REPORTED
    assert fetched.severity == Severity.HIGH
    assert fetched.harm_categories == [HarmCategory.PRIVACY]
    assert len(store) == 1
    # unambiguous prefix lookup works
    assert store.get(incident.id[:6]).id == incident.id


def test_status_lifecycle_valid(tmp_path):
    store = IncidentStore(str(tmp_path / "incidents.jsonl"))
    incident = store.add(make_incident())

    store.update_status(incident.id, Status.TRIAGED, note="assigned")
    store.update_status(incident.id, Status.MITIGATED, note="patch deployed")
    store.update_status(incident.id, Status.RESOLVED, note="verified in prod")

    fetched = store.get(incident.id)
    assert fetched.status == Status.RESOLVED
    transitions = [(e["from"], e["to"]) for e in fetched.history]
    assert ("reported", "triaged") in transitions
    assert ("triaged", "mitigated") in transitions
    assert ("mitigated", "resolved") in transitions


def test_status_lifecycle_invalid_transition(tmp_path):
    store = IncidentStore(str(tmp_path / "incidents.jsonl"))
    incident = store.add(make_incident())

    with pytest.raises(InvalidTransitionError):
        store.update_status(incident.id, Status.RESOLVED)  # skip triage/mitigation

    # incident is unchanged after the failed transition
    assert store.get(incident.id).status == Status.REPORTED


def test_resolved_incident_can_reopen(tmp_path):
    store = IncidentStore(str(tmp_path / "incidents.jsonl"))
    incident = store.add(make_incident())
    for status in (Status.TRIAGED, Status.MITIGATED, Status.RESOLVED):
        store.update_status(incident.id, status)

    reopened = store.update_status(incident.id, Status.TRIAGED, note="regression found")
    assert reopened.status == Status.TRIAGED
    assert reopened.history[-1]["note"] == "regression found"


def test_validation_rejects_bad_input():
    with pytest.raises(ValidationError):
        new_incident(title="", description="d", system="s", severity=Severity.LOW)
    with pytest.raises(ValidationError):
        new_incident(title="t", description="d", system="s", severity="extreme")
    with pytest.raises(ValidationError):
        new_incident(title="t", description="d", system="s",
                     severity=Severity.LOW, harm_categories=["not-a-harm"])


def test_query_filters(tmp_path):
    store = IncidentStore(str(tmp_path / "incidents.jsonl"))
    store.add(make_incident(title="PII leak in chat", system="chatbot v2",
                            severity=Severity.CRITICAL, harms=[HarmCategory.PRIVACY]))
    store.add(make_incident(title="Biased hiring scores", system="resume ranker",
                            severity=Severity.MEDIUM, harms=[HarmCategory.BIAS_DISCRIMINATION],
                            description="The model downgraded resumes with employment gaps."))
    second = store.add(make_incident(title="PII leak in email digest", system="chatbot v2",
                                     severity=Severity.HIGH, harms=[HarmCategory.PRIVACY],
                                     description="Email digest included another user's address."))
    store.update_status(second.id, Status.TRIAGED)

    assert len(store.query(severity=Severity.CRITICAL)) == 1
    assert len(store.query(min_severity=Severity.HIGH)) == 2
    assert len(store.query(system="chatbot")) == 2
    assert len(store.query(harm=HarmCategory.BIAS_DISCRIMINATION)) == 1
    assert len(store.query(status=Status.TRIAGED)) == 1
    assert len(store.query(text="resumes")) == 1
    assert len(store.query(text="PII", severity=Severity.HIGH)) == 1


def test_dedup_flags_near_duplicates(tmp_path):
    incidents = [
        make_incident(title="Model leaked PII in chat", system="chatbot v2"),
        make_incident(title="Chatbot disclosed personal data in conversation",
                      system="chatbot v2",
                      description="The assistant revealed a user's phone number during a chat session."),
        make_incident(title="Biased hiring scores", system="resume ranker",
                      severity=Severity.MEDIUM,
                      description="The model downgraded resumes with employment gaps."),
    ]
    pairs = find_duplicates(incidents, threshold=0.4)
    pair_ids = {(p["a"], p["b"]) for p in pairs} | {(p["b"], p["a"]) for p in pairs}
    assert (incidents[0].id, incidents[1].id) in pair_ids
    # the unrelated incident is not paired with anything
    for p in pairs:
        assert incidents[2].id not in (p["a"], p["b"])

    clusters = duplicate_clusters(incidents, threshold=0.4)
    assert len(clusters) == 1
    assert set(clusters[0]) == {incidents[0].id, incidents[1].id}


def test_dedup_ignores_distinct_reports():
    incidents = [
        make_incident(title="Model leaked PII in chat", system="chatbot v2"),
        make_incident(title="Biased hiring scores", system="resume ranker",
                      severity=Severity.MEDIUM,
                      description="The model downgraded resumes with employment gaps."),
    ]
    assert find_duplicates(incidents) == []


def test_trends_summary_counts(tmp_path):
    store = IncidentStore(str(tmp_path / "incidents.jsonl"))
    a = store.add(make_incident(severity=Severity.CRITICAL))
    b = store.add(make_incident(title="Prompt injection in helpdesk bot",
                                system="helpdesk bot", severity=Severity.HIGH,
                                harms=[HarmCategory.SECURITY],
                                description="User prompt overrode system instructions."))
    store.update_status(b.id, Status.TRIAGED)
    store.update_status(a.id, Status.TRIAGED)
    store.update_status(a.id, Status.MITIGATED)
    store.update_status(a.id, Status.RESOLVED)

    summary = summarize(store.all())
    assert summary["total"] == 2
    assert summary["open"] == 1
    assert summary["resolved"] == 1
    assert summary["by_severity"][Severity.CRITICAL] == 1
    assert summary["by_severity"][Severity.HIGH] == 1
    assert summary["by_status"][Status.RESOLVED] == 1
    assert summary["by_status"][Status.TRIAGED] == 1
    assert summary["by_harm"][HarmCategory.PRIVACY] == 1
    assert summary["by_harm"][HarmCategory.SECURITY] == 1

    series = timeseries(store.all(), bucket="month")
    assert len(series) >= 1
    assert sum(row["total"] for row in series) == 2


def test_export_import_roundtrip(tmp_path):
    store = IncidentStore(str(tmp_path / "incidents.jsonl"))
    incident = store.add(make_incident())
    store.update_status(incident.id, Status.TRIAGED, note="looking into it")

    path = str(tmp_path / "export.json")
    export_json(store.all(), path)
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    assert doc["format"] == "ai-incident-logger/1"
    assert doc["count"] == 1

    loaded = load_json(path)
    assert len(loaded) == 1
    assert loaded[0].id == incident.id
    assert loaded[0].status == Status.TRIAGED
    assert loaded[0].history[-1]["note"] == "looking into it"


def test_cli_file_and_list(tmp_path):
    db = str(tmp_path / "cli.jsonl")
    env = dict(os.environ, AI_INCIDENT_DB=db)

    def run(*argv):
        return subprocess.run(
            [sys.executable, "-m", "ai_incident_logger", *argv],
            capture_output=True, text=True, env=env, check=False,
        )

    filed = run("file", "--title", "Hallucinated medical dosage",
                "--description", "The model invented a dosage not present in any source.",
                "--system", "med-assistant", "--severity", "critical",
                "--harms", "physical_safety,misinformation",
                "--reporter", "clinician")
    assert filed.returncode == 0, filed.stderr
    assert "filed incident" in filed.stdout

    listed = run("list", "--min-severity", "high")
    assert listed.returncode == 0, listed.stderr
    assert "Hallucinated medical dosage" in listed.stdout

    incident_id = filed.stdout.split("filed incident")[1].split()[0]
    updated = run("update", incident_id, "--status", "triaged", "--note", "triage call done")
    assert updated.returncode == 0, updated.stderr

    bad = run("update", incident_id, "--status", "resolved")
    assert bad.returncode != 0  # triaged -> resolved skips mitigation
    assert "error" in bad.stderr.lower()


def test_link_and_unlink_incidents(tmp_path):
    from ai_incident_logger import IncidentError

    store = IncidentStore(str(tmp_path / "incidents.jsonl"))
    a = store.add(make_incident(title="PII leak in chat"))
    b = store.add(make_incident(title="PII leak in email digest"))

    store.link_incidents(a.id, b.id, note="same root cause")
    assert store.get(a.id).related_ids == [b.id]
    assert store.get(b.id).related_ids == [a.id]
    assert "linked to" in store.get(a.id).history[-1]["note"]

    # linking twice does not duplicate the link
    store.link_incidents(a.id, b.id)
    assert store.get(a.id).related_ids == [b.id]

    # self-linking is rejected
    with pytest.raises(IncidentError):
        store.link_incidents(a.id, a.id)

    store.unlink_incidents(a.id, b.id)
    assert store.get(a.id).related_ids == []
    assert store.get(b.id).related_ids == []


def test_link_survives_reload(tmp_path):
    store = IncidentStore(str(tmp_path / "incidents.jsonl"))
    a = store.add(make_incident(title="PII leak in chat"))
    b = store.add(make_incident(title="PII leak in email digest"))
    store.link_incidents(a.id, b.id)

    reloaded = IncidentStore(str(tmp_path / "incidents.jsonl"))
    assert reloaded.get(a.id).related_ids == [b.id]


def test_old_records_load_without_related_ids(tmp_path):
    # Simulate a database written before linking existed.
    db = tmp_path / "incidents.jsonl"
    incident = make_incident()
    data = incident.to_dict()
    del data["related_ids"]
    db.write_text(json.dumps(data) + "\n", encoding="utf-8")

    store = IncidentStore(str(db))
    assert store.get(incident.id).related_ids == []


def test_add_note_keeps_status(tmp_path):
    store = IncidentStore(str(tmp_path / "incidents.jsonl"))
    incident = store.add(make_incident())
    store.add_note(incident.id, "waiting on vendor patch")

    fetched = store.get(incident.id)
    assert fetched.status == Status.REPORTED
    assert fetched.history[-1]["note"] == "waiting on vendor patch"
    assert fetched.history[-1]["from"] == fetched.history[-1]["to"] == Status.REPORTED


def test_aging_and_stale_detection():
    from datetime import datetime, timedelta, timezone

    from ai_incident_logger import (
        age_days,
        format_aging,
        stale_incidents,
        time_in_status_days,
    )

    now = datetime(2026, 9, 29, 12, 0, 0, tzinfo=timezone.utc)

    def aged(days_ago, status=Status.REPORTED):
        incident = make_incident()
        stamp = (now - timedelta(days=days_ago)).isoformat(timespec="seconds")
        incident.created_at = stamp
        incident.updated_at = stamp
        incident.status = status
        incident.history = [{"from": "", "to": status, "at": stamp, "note": ""}]
        return incident

    fresh = aged(1)
    stale_report = aged(20)
    old_but_moving = aged(20)
    old_but_moving.history.append({
        "from": Status.REPORTED, "to": Status.TRIAGED,
        "at": (now - timedelta(days=2)).isoformat(timespec="seconds"),
        "note": "triaged",
    })
    old_but_moving.status = Status.TRIAGED
    resolved = aged(30, status=Status.RESOLVED)

    assert age_days(fresh, now=now) == pytest.approx(1.0, abs=0.01)
    assert time_in_status_days(stale_report, now=now) == pytest.approx(20.0, abs=0.01)

    stale = stale_incidents(
        [fresh, stale_report, old_but_moving, resolved], stale_days=7, now=now
    )
    stale_ids = [row["incident"].id for row in stale]
    assert stale_report.id in stale_ids
    assert fresh.id not in stale_ids          # too young
    assert old_but_moving.id not in stale_ids  # moved recently
    assert resolved.id not in stale_ids        # resolved is never stale

    report = format_aging([stale_report], stale_days=7, now=now)
    assert "stale" in report
    assert stale_report.title in report


def test_export_csv_roundtrip(tmp_path):
    import csv

    from ai_incident_logger import export_csv

    store = IncidentStore(str(tmp_path / "incidents.jsonl"))
    a = store.add(make_incident(title="PII leak in chat"))
    b = store.add(make_incident(title="Biased hiring scores",
                                severity=Severity.MEDIUM))
    store.link_incidents(a.id, b.id)

    path = str(tmp_path / "incidents.csv")
    export_csv(store.all(), path)
    with open(path, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 2
    by_id = {row["id"]: row for row in rows}
    assert by_id[a.id]["severity"] == Severity.HIGH
    assert by_id[a.id]["related_ids"] == b.id
    assert by_id[b.id]["harm_categories"] == HarmCategory.PRIVACY


def test_cli_link_note_aging_and_csv_export(tmp_path):
    db = str(tmp_path / "cli.jsonl")
    env = dict(os.environ, AI_INCIDENT_DB=db)

    def run(*argv):
        return subprocess.run(
            [sys.executable, "-m", "ai_incident_logger", *argv],
            capture_output=True, text=True, env=env, check=False,
        )

    filed_a = run("file", "--title", "PII leak in chat",
                  "--description", "phone number in transcript",
                  "--system", "chatbot v2", "--severity", "high")
    assert filed_a.returncode == 0, filed_a.stderr
    filed_b = run("file", "--title", "PII leak in digest",
                  "--description", "address in email digest",
                  "--system", "chatbot v2", "--severity", "medium")
    assert filed_b.returncode == 0, filed_b.stderr
    id_a = filed_a.stdout.split("filed incident")[1].split()[0]
    id_b = filed_b.stdout.split("filed incident")[1].split()[0]

    linked = run("link", id_a, id_b, "--note", "same root cause")
    assert linked.returncode == 0, linked.stderr
    assert "linked" in linked.stdout

    noted = run("note", id_a, "--note", "waiting on vendor patch")
    assert noted.returncode == 0, noted.stderr

    shown = run("show", id_a)
    assert shown.returncode == 0, shown.stderr
    assert id_b in shown.stdout  # related id visible
    assert "waiting on vendor patch" in shown.stdout

    csv_path = str(tmp_path / "out.csv")
    exported = run("export", csv_path, "--format", "csv")
    assert exported.returncode == 0, exported.stderr
    with open(csv_path, encoding="utf-8") as fh:
        assert "PII leak in chat" in fh.read()

    # pin "now" far in the future so both reports count as stale
    aging = run("aging", "--stale-days", "7", "--now", "2030-01-01T00:00:00+00:00")
    assert aging.returncode == 0, aging.stderr
    assert "stale" in aging.stdout
