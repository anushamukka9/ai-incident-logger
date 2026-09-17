# ai-incident-logger

Structured logging for AI incidents, in the spirit of a safety database:
file incident reports with severity and harm categories, move them through a
reviewed **reported → triaged → mitigated → resolved** lifecycle, catch
near-duplicate reports, summarize trends over time, and export everything as
JSON — from a CLI or as a Python library.

## Install

Requires Python 3.9+.

```bash
pip install git+https://github.com/anushamukka9/ai-incident-logger.git
```

Or from source:

```bash
git clone https://github.com/anushamukka9/ai-incident-logger.git
cd ai-incident-logger
pip install -e ".[dev]"
```

## Quickstart

```bash
# File an incident
ailog file --title "Chatbot leaked a user's phone number" \
  --system "support-chatbot v3" --severity high --harms privacy \
  --description "The assistant pasted the user's phone number into the agent-visible transcript."

# Triage it through the lifecycle
ailog update <id> --status triaged --note "reproduced; assigned to safety"
ailog update <id> --status mitigated --note "PII redaction filter deployed"
ailog update <id> --status resolved --note "verified on 200 transcripts"

# Find near-duplicate reports, view trends, export
ailog dedup
ailog trends --bucket month
ailog export backup.json
```

A runnable end-to-end tour (throwaway database, no setup):

```bash
python examples/quickstart.py
```

## CLI reference

| Command | Purpose |
|---|---|
| `ailog file` | File a new incident (`--title`, `--description`, `--system`, `--severity`, `--harms`, `--reporter`, `--ref`) |
| `ailog update <id> --status <s> [--note]` | Move through the lifecycle (transitions validated) |
| `ailog edit <id> [--title …]` | Edit fields without touching status |
| `ailog list [--status …] [--severity …] [--min-severity …] [--system …] [--harm …] [--text …] [--json]` | Filter and list |
| `ailog show <id> [--json]` | Full record incl. audit history |
| `ailog dedup [--threshold 0.45] [--json]` | Near-duplicate candidates + clusters |
| `ailog trends [--bucket month\|week] [--json]` | Counts by status/severity/harm + time series |
| `ailog export <path> [filters…]` | Versioned JSON export (full backup) |

The database defaults to `~/.ai-incident-logger/incidents.jsonl`; override
with `--db PATH` or the `AI_INCIDENT_DB` environment variable. Incident ids
accept unambiguous prefixes.

## Python API

```python
from ai_incident_logger import (
    IncidentStore, Severity, Status, HarmCategory, new_incident,
    find_duplicates, summarize, timeseries, export_json,
)

store = IncidentStore("incidents.jsonl")
inc = store.add(new_incident(
    title="Chatbot leaked a user's phone number",
    description="...",
    system="support-chatbot v3",
    severity=Severity.HIGH,
    harm_categories=[HarmCategory.PRIVACY],
))
store.update_status(inc.id, Status.TRIAGED, note="reproduced")
print(summarize(store.all()))
print(find_duplicates(store.all()))
export_json(store.all(), "backup.json")
```

## Architecture

```
src/ai_incident_logger/
├── models.py    # Incident record, Severity/Status/HarmCategory vocabularies,
│                # lifecycle transition rules, validation
├── store.py     # JSONL-backed IncidentStore: CRUD, prefix id lookup, filters
├── dedup.py     # Near-duplicate detection (weighted token-overlap similarity)
├── trends.py    # summarize(), timeseries(), severity_mix_trend(), text report
├── exporter.py  # Versioned JSON export / import (full-fidelity snapshots)
└── cli.py       # `ailog` command-line interface (+ `python -m` entry point)
```

Design notes:

- **Lifecycle is enforced, not suggested.** `reported → resolved` in one jump
  raises `InvalidTransitionError`; every legal move is appended to an
  audit `history` with timestamp and note.
- **Deduplication is dependency-free** — normalized token Jaccard, weighted
  65% title / 35% description, with a small same-system boost. No ML model
  to install, deterministic scores, tunable threshold.
- **JSONL storage** keeps the database human-readable and append-friendly;
  versioned JSON exports are the portable backup format.

## Development

```bash
pip install -e ".[dev]"
pytest -q
```

CI runs the test suite on Python 3.9, 3.11, and 3.12.

## License

MIT — Copyright (c) 2026 Anusha Mukka. See [LICENSE](LICENSE).

Author: Anusha Mukka · https://anushamukka.com
