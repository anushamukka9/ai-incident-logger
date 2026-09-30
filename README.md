# ai-incident-logger

Structured logging for AI incidents, in the spirit of a safety database:
file incident reports with severity and harm categories, move them through a
reviewed **reported -> triaged -> mitigated -> resolved** lifecycle, link
related reports, add notes without touching the lifecycle, catch
near-duplicate reports, summarize trends and aging over time, and export
everything as JSON or CSV. From a CLI or as a Python library.

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

# Link a confirmed duplicate, add a note, check what is going stale
ailog link <id> <other-id> --note "same root cause"
ailog note <id> --note "waiting on vendor patch"
ailog aging --stale-days 7

# Find near-duplicate reports, view trends, export
ailog dedup
ailog trends --bucket month
ailog export backup.json
ailog export report.csv --format csv
```

Runnable end-to-end tours (throwaway databases, no setup):

```bash
python examples/quickstart.py   # file, triage, dedup, trends, export
python examples/sla_review.py   # aging report and stale detection
```

## CLI reference

| Command | Purpose |
|---|---|
| `ailog file` | File a new incident (`--title`, `--description`, `--system`, `--severity`, `--harms`, `--reporter`, `--ref`) |
| `ailog update <id> --status <s> [--note]` | Move through the lifecycle (transitions validated) |
| `ailog edit <id> [--title ...]` | Edit fields without touching status |
| `ailog note <id> --note <text>` | Append a note to the history |
| `ailog link <id> <other> [--note] [--remove]` | Link/unlink related incidents |
| `ailog list [--status ...] [--severity ...] [--min-severity ...] [--system ...] [--harm ...] [--text ...] [--json]` | Filter and list |
| `ailog show <id> [--json]` | Full record incl. audit history |
| `ailog dedup [--threshold 0.45] [--json]` | Near-duplicate candidates + clusters |
| `ailog trends [--bucket month\|week] [--json]` | Counts by status/severity/harm + time series |
| `ailog aging [--stale-days 7] [--json]` | Open incidents stuck in their current status |
| `ailog export <path> [filters...] [--format json\|csv]` | Versioned JSON export (full backup) or flat CSV |

The database defaults to `~/.ai-incident-logger/incidents.jsonl`; override
with `--db PATH` or the `AI_INCIDENT_DB` environment variable. Incident ids
accept unambiguous prefixes.

## Python API

```python
from ai_incident_logger import (
    IncidentStore, Severity, Status, HarmCategory, new_incident,
    find_duplicates, summarize, timeseries, export_json, export_csv,
    stale_incidents, format_aging,
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
store.add_note(inc.id, "waiting on vendor patch")
print(summarize(store.all()))
print(find_duplicates(store.all()))
print(format_aging(store.all(), stale_days=7.0))
export_json(store.all(), "backup.json")
export_csv(store.all(), "report.csv")
```

## Architecture

```
src/ai_incident_logger/
├── models.py    # Incident record, Severity/Status/HarmCategory vocabularies,
│                # lifecycle transition rules, validation
├── store.py     # JSONL-backed IncidentStore: CRUD, prefix id lookup, filters,
│                # linking, notes
├── dedup.py     # Near-duplicate detection (weighted token-overlap similarity)
├── trends.py    # summarize(), timeseries(), severity_mix_trend(), text report
├── aging.py     # age_days(), time_in_status_days(), stale_incidents()
├── exporter.py  # Versioned JSON export / import, flat CSV export
└── cli.py       # `ailog` command-line interface (+ `python -m` entry point)
```

Design notes:

- **Lifecycle is enforced, not suggested.** `reported -> resolved` in one jump
  raises `InvalidTransitionError`; every legal move is appended to an
  audit `history` with timestamp and note.
- **Deduplication is dependency-free.** Normalized token Jaccard, weighted
  65% title / 35% description, with a small same-system boost. No ML model
  to install, deterministic scores, tunable threshold.
- **Links confirm what dedup suggests.** `ailog dedup` finds candidates;
  `ailog link` records the human verdict in both incidents' histories.
- **JSONL storage** keeps the database human-readable and append-friendly;
  versioned JSON exports are the portable backup format.

## Development

```bash
pip install -e ".[dev]"
pytest -q
python examples/quickstart.py
python examples/sla_review.py
```

CI runs the test suite on Python 3.9, 3.11, and 3.12.

## License

MIT. Copyright (c) 2026 Anusha Mukka. See [LICENSE](LICENSE).

Author: Anusha Mukka, https://anushamukka.com
