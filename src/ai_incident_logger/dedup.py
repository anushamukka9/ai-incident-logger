"""Near-duplicate detection for incident reports.

The same failure mode is often reported several times with different wording
("model leaked PII in chat" vs. "chatbot disclosed personal data"). This
module scores pairs of incidents and flags pairs above a threshold so
reviewers can link duplicates instead of triaging the same incident twice.

Similarity is dependency-free and deterministic. Each text field is compared
two ways — stemmed token overlap (catches shared vocabulary despite
morphology: "disclosed"/"disclose") and character-level sequence ratio
(catches paraphrased short titles) — and the stronger signal wins. Titles
count more than descriptions, and same-system pairs get a small boost since
repeat reports usually name the same deployment.

Scores are *suggestions for a human reviewer*, not verdicts: same-system
incidents with similar phrasing can score above the threshold by coincidence.
Tune the threshold to your stream (lower after bulk imports, higher for noisy
intake).
"""

from __future__ import annotations

import difflib
import re
from itertools import combinations

from .models import Incident

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Common glue words that add noise to overlap scores.
_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with",
    "is", "was", "were", "are", "be", "it", "its", "this", "that", "by",
    "from", "as", "at", "when", "which", "their", "they", "has", "have",
    "had", "not", "but", "into", "over", "under", "after", "before",
})

TITLE_WEIGHT = 0.6
DESC_WEIGHT = 0.4
SAME_SYSTEM_BOOST = 0.05
DEFAULT_THRESHOLD = 0.45


def _stem(token: str) -> str:
    """Very light suffix stripper so morphological variants still match."""
    for suffix in ("ing", "ed", "es", "s"):
        if token.endswith(suffix) and len(token) - len(suffix) >= 4:
            return token[: -len(suffix)]
    return token


def tokenize(text: str) -> set[str]:
    """Lowercase alphanumeric tokens, stemmed, minus stopwords."""
    return {_stem(t) for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _normalized(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", "", text.lower())).strip()


def sequence_ratio(a: str, b: str) -> float:
    """Character-level similarity in [0, 1] (difflib, dependency-free)."""
    a, b = _normalized(a), _normalized(b)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def field_similarity(a: str, b: str) -> float:
    """Similarity of two text fields: the stronger of token overlap and
    character-level resemblance wins."""
    return max(jaccard(tokenize(a), tokenize(b)), sequence_ratio(a, b))


def similarity(a: Incident, b: Incident) -> float:
    """Similarity score in [0, 1] for a pair of incidents."""
    score = (
        TITLE_WEIGHT * field_similarity(a.title, b.title)
        + DESC_WEIGHT * field_similarity(a.description, b.description)
    )
    if a.system.strip() and a.system.strip().lower() == b.system.strip().lower():
        score = min(1.0, score + SAME_SYSTEM_BOOST)
    return round(score, 3)


def find_duplicates(
    incidents: list[Incident],
    threshold: float = DEFAULT_THRESHOLD,
) -> list[dict]:
    """Return candidate duplicate pairs sorted by descending score.

    Each item is ``{"a": id, "b": id, "score": float}``. Pairs involving the
    same incident id are never returned.
    """
    pairs = []
    for first, second in combinations(incidents, 2):
        if first.id == second.id:
            continue
        score = similarity(first, second)
        if score >= threshold:
            pairs.append({"a": first.id, "b": second.id, "score": score})
    pairs.sort(key=lambda p: p["score"], reverse=True)
    return pairs


def duplicate_clusters(
    incidents: list[Incident],
    threshold: float = DEFAULT_THRESHOLD,
) -> list[list[str]]:
    """Group incidents into connected clusters of near-duplicates."""
    pairs = find_duplicates(incidents, threshold=threshold)
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: str, y: str) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    for pair in pairs:
        union(pair["a"], pair["b"])

    clusters: dict[str, list[str]] = {}
    for incident in incidents:
        if incident.id in parent:
            clusters.setdefault(find(incident.id), []).append(incident.id)
    return [sorted(ids) for ids in clusters.values() if len(ids) > 1]
