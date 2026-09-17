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
