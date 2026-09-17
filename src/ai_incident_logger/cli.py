"""Command-line interface for ai-incident-logger.

Usage examples:
    ailog file --title "..." --system "chatbot v2" --severity high \\
        --harms privacy,misinformation --description "..."
    ailog update <id> --status triaged --note "assigned to safety team"
    ailog list --min-severity high
    ailog dedup
    ailog trends --bucket month
    ailog export incidents-backup.json

The database defaults to ``~/.ai-incident-logger/incidents.jsonl``; override
with ``--db PATH`` or the ``AI_INCIDENT_DB`` environment variable.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import __version__
from .dedup import duplicate_clusters, find_duplicates
from .exporter import export_json
from .models import HarmCategory, Incident, Severity, Status
from .store import IncidentNotFoundError, AmbiguousIdError, IncidentStore
from .trends import format_report, summarize, timeseries


DEFAULT_DB = os.path.expanduser("~/.ai-incident-logger/incidents.jsonl")


def resolve_db(args: argparse.Namespace) -> str:
    return args.db or os.environ.get("AI_INCIDENT_DB") or DEFAULT_DB


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _one_line(incident: Incident) -> str:
    return (
        f"{incident.id}  [{incident.severity:<8}] [{incident.status:<9}] "
        f"{incident.system} :: {incident.title}"
    )


def _detail(incident: Incident) -> str:
    lines = [
        f"id          : {incident.id}",
        f"title       : {incident.title}",
        f"system      : {incident.system}",
        f"severity    : {incident.severity}",
        f"status      : {incident.status}",
        f"harms       : {', '.join(incident.harm_categories) or '-'}",
        f"reporter    : {incident.reporter or '-'}",
        f"refs        : {', '.join(incident.refs) or '-'}",
        f"created     : {incident.created_at}",
        f"updated     : {incident.updated_at}",
        "description :",
        f"  {incident.description}",
        "history     :",
    ]
    for event in incident.history:
        frm = event.get("from") or "(new)"
        note = f" — {event['note']}" if event.get("note") else ""
        lines.append(f"  {event['at']}  {frm} -> {event['to']}{note}")
    return "\n".join(lines)


def _parse_harms(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [h.strip() for h in raw.split(",") if h.strip()]


# ---------------------------------------------------------------------------
# Subcommand implementations
# ---------------------------------------------------------------------------

def cmd_file(args: argparse.Namespace) -> int:
    from .models import new_incident

    store = IncidentStore(resolve_db(args))
    incident = new_incident(
        title=args.title,
        description=args.description,
        system=args.system,
        severity=args.severity,
        harm_categories=_parse_harms(args.harms),
        reporter=args.reporter or "",
        refs=args.ref or [],
    )
    store.add(incident)
    print(f"filed incident {incident.id}")
    print(_one_line(incident))
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    store = IncidentStore(resolve_db(args))
    try:
        incident = store.update_status(args.id, args.status, note=args.note or "")
    except (IncidentNotFoundError, AmbiguousIdError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"incident {incident.id} -> {incident.status}")
    return 0


def cmd_edit(args: argparse.Namespace) -> int:
    store = IncidentStore(resolve_db(args))
    fields: dict = {}
    for name in ("title", "description", "system", "severity", "reporter"):
        value = getattr(args, name)
        if value is not None:
            fields[name] = value
    if args.harms is not None:
        fields["harm_categories"] = _parse_harms(args.harms)
    if args.ref is not None:
        fields["refs"] = args.ref
    if not fields:
        print("error: nothing to edit; pass at least one field flag", file=sys.stderr)
        return 1
    try:
        incident = store.update_fields(args.id, **fields)
    except (IncidentNotFoundError, AmbiguousIdError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"updated incident {incident.id}")
    return 0


def _query_kwargs(args: argparse.Namespace) -> dict:
    kwargs: dict = {}
    for name in ("status", "severity", "min_severity", "system", "harm", "text"):
        value = getattr(args, name, None)
        if value:
            kwargs[name] = value
    return kwargs


def cmd_list(args: argparse.Namespace) -> int:
    store = IncidentStore(resolve_db(args))
    incidents = store.query(**_query_kwargs(args))
    if args.json:
        print(json.dumps([i.to_dict() for i in incidents], indent=2))
    else:
        if not incidents:
            print("no incidents match")
        for incident in incidents:
            print(_one_line(incident))
        print(f"\n{len(incidents)} incident(s)")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    store = IncidentStore(resolve_db(args))
    try:
        incident = store.get(args.id)
    except (IncidentNotFoundError, AmbiguousIdError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(incident.to_dict(), indent=2))
    else:
        print(_detail(incident))
    return 0


def cmd_dedup(args: argparse.Namespace) -> int:
    store = IncidentStore(resolve_db(args))
    incidents = store.all()
    pairs = find_duplicates(incidents, threshold=args.threshold)
    if args.json:
        print(json.dumps(pairs, indent=2))
        return 0
    if not pairs:
        print(f"no near-duplicates found (threshold {args.threshold})")
        return 0
    by_id = {i.id: i for i in incidents}
    print(f"candidate duplicates (threshold {args.threshold}):\n")
    for pair in pairs:
        a, b = by_id[pair["a"]], by_id[pair["b"]]
        print(f"  {a.id} <-> {b.id}  score={pair['score']}")
        print(f"    - [{a.severity}/{a.status}] {a.system}: {a.title}")
        print(f"    - [{b.severity}/{b.status}] {b.system}: {b.title}")
    clusters = duplicate_clusters(incidents, threshold=args.threshold)
    if clusters:
        print(f"\n{len(clusters)} duplicate cluster(s):")
        for cluster in clusters:
            print("  " + ", ".join(cluster))
    return 0


def cmd_trends(args: argparse.Namespace) -> int:
    store = IncidentStore(resolve_db(args))
    incidents = store.all()
    summary = summarize(incidents)
    series = timeseries(incidents, bucket=args.bucket)
    if args.json:
        print(json.dumps({"summary": summary, "timeseries": series}, indent=2))
    else:
        print(format_report(summary, series))
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    store = IncidentStore(resolve_db(args))
    incidents = store.query(**_query_kwargs(args))
    export_json(incidents, args.path)
    print(f"exported {len(incidents)} incident(s) to {args.path}")
    return 0


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def _add_query_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--status", choices=Status.ALL)
    parser.add_argument("--severity", choices=Severity.ALL)
    parser.add_argument("--min-severity", choices=Severity.ALL,
                        help="minimum severity (inclusive)")
    parser.add_argument("--system", help="substring match on system name")
    parser.add_argument("--harm", choices=HarmCategory.ALL)
    parser.add_argument("--text", help="substring match on title/description")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ailog",
        description="Structured AI incident logging: file, triage, dedup, and report.",
    )
    parser.add_argument("--db", help="path to the incidents JSONL database")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("file", help="file a new incident")
    p.add_argument("--title", required=True)
    p.add_argument("--description", required=True)
    p.add_argument("--system", required=True, help="model / product / deployment")
    p.add_argument("--severity", required=True, choices=Severity.ALL)
    p.add_argument("--harms", default="",
                   help="comma-separated harm categories, e.g. privacy,security")
    p.add_argument("--reporter", default="")
    p.add_argument("--ref", action="append", default=[],
                   help="external reference (repeatable)")
    p.set_defaults(func=cmd_file)

    p = sub.add_parser("update", help="move an incident to a new status")
    p.add_argument("id", help="incident id (unambiguous prefix accepted)")
    p.add_argument("--status", required=True, choices=Status.ALL)
    p.add_argument("--note", default="", help="note recorded in history")
    p.set_defaults(func=cmd_update)

    p = sub.add_parser("edit", help="edit incident fields")
    p.add_argument("id")
    p.add_argument("--title")
    p.add_argument("--description")
    p.add_argument("--system")
    p.add_argument("--severity", choices=Severity.ALL)
    p.add_argument("--harms", help="comma-separated harm categories (replaces)")
    p.add_argument("--reporter")
    p.add_argument("--ref", action="append", help="references (replaces)")
    p.set_defaults(func=cmd_edit)

    p = sub.add_parser("list", help="list incidents with optional filters")
    _add_query_flags(p)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("show", help="show one incident in detail")
    p.add_argument("id")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("dedup", help="find near-duplicate incident reports")
    p.add_argument("--threshold", type=float, default=0.45)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_dedup)

    p = sub.add_parser("trends", help="print trend summaries")
    p.add_argument("--bucket", choices=["month", "week"], default="month")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_trends)

    p = sub.add_parser("export", help="export incidents to JSON")
    p.add_argument("path")
    _add_query_flags(p)
    p.set_defaults(func=cmd_export)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:  # domain validation errors
        from .models import IncidentError
        if isinstance(exc, IncidentError):
            print(f"error: {exc}", file=sys.stderr)
            return 1
        raise


if __name__ == "__main__":
    sys.exit(main())
