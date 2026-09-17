"""ai-incident-logger: structured AI incident logging.

File incidents with severity and harm categories, move them through a
reviewed status lifecycle, find near-duplicate reports, summarize trends,
and export everything as JSON — from the CLI or as a Python library.
"""

from .dedup import duplicate_clusters, find_duplicates, similarity
from .exporter import export_json, export_json_string, load_json
from .models import (
    ALLOWED_TRANSITIONS,
    HarmCategory,
    Incident,
    InvalidTransitionError,
    Severity,
    Status,
    ValidationError,
    new_incident,
)
from .store import AmbiguousIdError, IncidentNotFoundError, IncidentStore
from .trends import format_report, severity_mix_trend, summarize, timeseries

__version__ = "0.1.0"

__all__ = [
    "ALLOWED_TRANSITIONS",
    "AmbiguousIdError",
    "HarmCategory",
    "Incident",
    "IncidentNotFoundError",
    "IncidentStore",
    "InvalidTransitionError",
    "Severity",
    "Status",
    "ValidationError",
    "duplicate_clusters",
    "export_json",
    "export_json_string",
    "find_duplicates",
    "format_report",
    "load_json",
    "new_incident",
    "severity_mix_trend",
    "similarity",
    "summarize",
    "timeseries",
]
