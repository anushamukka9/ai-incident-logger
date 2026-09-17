"""Trend summaries over the incident database.

Answers questions like "are critical incidents rising?", "which harm
categories dominate this quarter?", and "how many reports are still stuck in
``reported``?". Outputs are plain data structures (easy to plot or feed to a
dashboard); :func:`format_report` renders a human-readable text summary for
the CLI.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime

from .models import HarmCategory, Incident, Severity, Status


def _parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def summarize(incidents: list[Incident]) -> dict:
    """Aggregate counts: totals by status, severity, harm category, system."""
    by_status: Counter = Counter()
    by_severity: Counter = Counter()
    by_harm: Counter = Counter()
    by_system: Counter = Counter()
    open_count = 0

    for incident in incidents:
        by_status[incident.status] += 1
        by_severity[incident.severity] += 1
        by_system[incident.system] += 1
        for harm in incident.harm_categories:
            by_harm[harm] += 1
        if incident.status != Status.RESOLVED:
            open_count += 1

    # Present severities / statuses in canonical order, not count order.
    ordered_severity = {s: by_severity.get(s, 0) for s in Severity.ALL}
    ordered_status = {s: by_status.get(s, 0) for s in Status.ALL}

    return {
        "total": len(incidents),
        "open": open_count,
        "resolved": by_status.get(Status.RESOLVED, 0),
        "by_status": ordered_status,
        "by_severity": ordered_severity,
        "by_harm": dict(by_harm.most_common()),
        "by_system": dict(by_system.most_common(10)),
    }


def _bucket_key(ts: datetime, bucket: str) -> str:
    if bucket == "week":
        year, week, _ = ts.isocalendar()
        return f"{year}-W{week:02d}"
    if bucket == "month":
        return ts.strftime("%Y-%m")
    raise ValueError(f"bucket must be 'week' or 'month', got {bucket!r}")


def timeseries(incidents: list[Incident], bucket: str = "month") -> list[dict]:
    """Per-bucket counts by severity, ordered chronologically.

    Each row: ``{"bucket": "2026-09", "total": 3, "by_severity": {...}}``.
    """
    buckets: dict[str, Counter] = defaultdict(Counter)
    for incident in incidents:
        key = _bucket_key(_parse_ts(incident.created_at), bucket)
        buckets[key][incident.severity] += 1

    rows = []
    for key in sorted(buckets):
        counts = buckets[key]
        rows.append({
            "bucket": key,
            "total": sum(counts.values()),
            "by_severity": {s: counts.get(s, 0) for s in Severity.ALL},
        })
    return rows


def severity_mix_trend(incidents: list[Incident], bucket: str = "month") -> list[dict]:
    """Share of high/critical incidents per bucket — a single "are things
    getting worse?" line."""
    rows = []
    for row in timeseries(incidents, bucket=bucket):
        sev = row["by_severity"]
        serious = sev[Severity.HIGH] + sev[Severity.CRITICAL]
        share = round(serious / row["total"], 3) if row["total"] else 0.0
        rows.append({
            "bucket": row["bucket"],
            "total": row["total"],
            "high_critical": serious,
            "high_critical_share": share,
        })
    return rows


def _bar(n: int, width: int = 24) -> str:
    return "#" * n if n <= width else "#" * width + f" (+{n - width})"


def format_report(summary: dict, series: list[dict] | None = None) -> str:
    """Render a plain-text trend report."""
    lines = [
        "AI incident trend report",
        "=" * 40,
        f"total incidents : {summary['total']}",
        f"open            : {summary['open']}",
        f"resolved        : {summary['resolved']}",
        "",
        "by status:",
    ]
    for status, count in summary["by_status"].items():
        lines.append(f"  {status:<10} {count:>4} {_bar(count)}")
    lines.append("by severity:")
    for severity, count in summary["by_severity"].items():
        lines.append(f"  {severity:<10} {count:>4} {_bar(count)}")
    lines.append("by harm category:")
    for harm, count in summary["by_harm"].items():
        lines.append(f"  {harm:<20} {count:>4} {_bar(count)}")
    if series:
        lines += ["", "incidents per bucket (by severity):"]
        header = f"  {'bucket':<10} {'total':>5}  " + " ".join(f"{s[:4]:>4}" for s in Severity.ALL)
        lines.append(header)
        for row in series:
            sev = row["by_severity"]
            cells = " ".join(f"{sev[s]:>4}" for s in Severity.ALL)
            lines.append(f"  {row['bucket']:<10} {row['total']:>5}  {cells}")
    lines.append("")
    lines.append("harm categories use the fixed vocabulary in HarmCategory.ALL; "
                 "'other' marks reports needing reclassification.")
    return "\n".join(lines)


def top_systems(summary: dict, n: int = 5) -> list[tuple[str, int]]:
    return list(summary["by_system"].items())[:n]
