# Usage Guide

This guide covers the full workflow: filing incidents, triaging them through
the status lifecycle, finding duplicates, reading trend reports, and exporting
data. For a 2-minute tour, see `examples/quickstart.py`.

## Concepts

**Incident record.** Every incident has:

| Field | Required | Notes |
|---|---|---|
| `title` | yes | One-line summary |
| `description` | yes | What happened, with enough detail to reproduce |
| `system` | yes | Model / product / deployment, e.g. `support-chatbot v3` |
| `severity` | yes | `low`, `medium`, `high`, `critical` |
| `harm_categories` | no | Any of: `privacy`, `bias_discrimination`, `physical_safety`, `misinformation`, `security`, `robustness`, `transparency`, `autonomy`, `other` |
| `reporter` | no | Who filed it |
| `refs` | no | Ticket ids, URLs, paper links |
| `status` | — | Managed through the lifecycle below |
| `history` | — | Append-only log of every status change |

**Status lifecycle.**

```
reported → triaged → mitigated → resolved
              ↑          ↑            │
              └──────────┴────────────┘
              (send back / regress / reopen)
```

- `reported → triaged`: someone owns it and has reproduced/scoped it.
- `triaged → mitigated`: a fix or containment is deployed.
- `mitigated → resolved`: the fix is verified.
- Backward moves are allowed where they make sense (e.g. `mitigated → triaged`
  when the patch fails, `resolved → triaged` to reopen), but you can never
  skip a stage: `reported → resolved` is rejected. Every move is recorded in
  `history` with a timestamp and an optional note.

**Database.** Incidents live in a JSONL file (one JSON object per line),
defaulting to `~/.ai-incident-logger/incidents.jsonl`. Override per-command
with `--db PATH` or globally with the `AI_INCIDENT_DB` environment variable.
Ids are 12-hex-character strings; commands accept any unambiguous prefix.

## CLI workflow

File an incident:

```bash
ailog file --title "Chatbot leaked a user's phone number" \
  --system "support-chatbot v3" \
  --severity high \
  --harms privacy \
  --description "During a support chat, the assistant pasted the user's phone number into the agent-visible transcript." \
  --reporter agent-ops
# filed incident 9f3c1a2b4d5e
```

Move it through triage (notes are stored in the audit history):

```bash
ailog update 9f3c1a --status triaged --note "reproduced; assigned to safety"
ailog update 9f3c1a --status mitigated --note "PII redaction filter deployed"
ailog update 9f3c1a --status resolved --note "verified on 200 sampled transcripts"
```

List and inspect:

```bash
ailog list --min-severity high            # high and critical
ailog list --status reported --harm privacy
ailog list --system chatbot --text "phone" --json
ailog show 9f3c1a
```

Fix a typo without touching the lifecycle:

```bash
ailog edit 9f3c1a --severity critical --harms privacy,security
```

## Deduplication

The same failure is often reported twice with different wording. `ailog dedup`
scores every pair by weighted token overlap (title counts more than
description, same-system pairs get a small boost) and lists candidates above
a threshold:

```bash
ailog dedup --threshold 0.45
```

Output shows each candidate pair with its score plus the merged duplicate
clusters. Raise the threshold for fewer, safer matches; lower it when
cleaning up after a bulk import.

## Trend reports

```bash
ailog trends --bucket month
```

prints totals, open vs. resolved, counts by status / severity / harm category,
and a per-bucket time series. `--bucket week` gives weekly granularity.
Add `--json` for machine-readable output you can pipe into a dashboard.

## Export

```bash
ailog export backup.json                      # everything
ailog export q3-critical.json --min-severity high --status resolved
```

Exports are versioned JSON documents (`"format": "ai-incident-logger/1"`)
containing every field including history — a complete backup. Read one back
in Python with `ai_incident_logger.load_json`.

## Python API

```python
from ai_incident_logger import (
    IncidentStore, Severity, Status, HarmCategory,
    new_incident, find_duplicates, summarize, timeseries, export_json,
)

store = IncidentStore("~/.ai-incident-logger/incidents.jsonl")

incident = new_incident(
    title="Chatbot leaked a user's phone number",
    description="...",
    system="support-chatbot v3",
    severity=Severity.HIGH,
    harm_categories=[HarmCategory.PRIVACY],
)
store.add(incident)

store.update_status(incident.id, Status.TRIAGED, note="reproduced")

open_high = store.query(status=Status.REPORTED, min_severity=Severity.HIGH)
dups = find_duplicates(store.all(), threshold=0.55)
report = summarize(store.all())
series = timeseries(store.all(), bucket="month")
export_json(store.all(), "backup.json")
```

## Tips

- **File first, perfect later.** A `reported` incident with a rough
  description beats a perfect report filed next week. Use `ailog edit` to
  refine.
- **Keep `system` names stable** (`support-chatbot v3`, not `the bot`) —
  deduplication and per-system trends both rely on it.
- **Put the "why" in the transition note**, not just the "what":
  `--note "regression on 2.1.4; reopening"` is far more useful than
  `--note "reopened"`.
- **Reclassify `other`.** The `other` harm category is a holding pen; trend
  reports are only as good as the vocabulary, so revisit `other` incidents
  monthly.
- **Back up with `ailog export`.** The JSONL file is the live database; a
  versioned JSON export is the portable backup.
