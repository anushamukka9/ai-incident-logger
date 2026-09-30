"""ai-incident-logger: structured AI incident logging.

File incidents with severity and harm categories, move them through a
reviewed status lifecycle, link related reports, add notes, find
near-duplicate reports, summarize trends and aging, and export everything
as JSON or CSV. From the CLI or as a Python library.
"""

from .aging import (
    age_days,
    format_aging,
    stale_incidents,
    time_in_status_days,
)
from .dedup import duplicate_clusters, find_duplicates, similarity
from .exporter import export_csv, export_json, export_json_string, load_json
from .models import (
    ALLOWED_TRANSITIONS,
    HarmCategory,
    Incident,
    IncidentError,
    InvalidTransitionError,
    Severity,
    Status,
    ValidationError,
    new_incident,
)
from .store import AmbiguousIdError, IncidentNotFoundError, IncidentStore
from .trends import format_report, severity_mix_trend, summarize, timeseries

__version__ = "0.2.0"

__all__ = [
    "ALLOWED_TRANSITIONS",
    "AmbiguousIdError",
    "HarmCategory",
    "Incident",
    "IncidentError",
    "IncidentNotFoundError",
    "IncidentStore",
    "InvalidTransitionError",
    "Severity",
    "Status",
    "ValidationError",
    "age_days",
    "duplicate_clusters",
    "export_csv",
    "export_json",
    "export_json_string",
    "find_duplicates",
    "format_aging",
    "format_report",
    "load_json",
    "new_incident",
    "severity_mix_trend",
    "similarity",
    "stale_incidents",
    "summarize",
    "time_in_status_days",
    "timeseries",
]
