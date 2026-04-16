"""Template-duplicate detection and selection-mode logic.

Extracted from `src.backtester.engine` so both the backtester and the
live signal path can import without dragging in CLI/argparse plumbing.
"""

from __future__ import annotations

import re


_MONTH_PATTERN = (
    r"(?:january|february|march|april|may|june|july|august|september|october|"
    r"november|december|jan|feb|mar|apr|may|jun|jul|aug|sept|sep|oct|nov|dec)"
)
_DATE_PHRASE_RE = re.compile(
    rf"\b(?:by|on|before|after|until|in|week\s+of)\s+{_MONTH_PATTERN}\.?\s+"
    rf"\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s*\d{{2,4}})?",
    re.IGNORECASE,
)
_BARE_MONTH_DATE_RE = re.compile(
    rf"\b{_MONTH_PATTERN}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s*\d{{2,4}})?",
    re.IGNORECASE,
)
_NUMERIC_DATE_RE = re.compile(r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b")
_WHITESPACE_RE = re.compile(r"\s+")


SELECTION_MODES = ("none", "earliest_created", "earliest_deadline")


def _template_key(question: str) -> str:
    text = _DATE_PHRASE_RE.sub("", question)
    text = _BARE_MONTH_DATE_RE.sub("", text)
    text = _NUMERIC_DATE_RE.sub("", text)
    text = _WHITESPACE_RE.sub(" ", text).strip().lower()
    return text


def _deadline_of(m):
    # Precedence: the actual resolution time when we know it (historical),
    # otherwise the scheduled endDate from Gamma (live), finally the creation
    # time as a defensive fallback so the sort key is never None.
    return m.resolved_at or m.end_date or m.created_at


_PRIORITY_KEYS = {
    "earliest_created": lambda m: (m.created_at, _deadline_of(m)),
    "earliest_deadline": lambda m: (_deadline_of(m), m.created_at),
}


def _select_markets(markets, mode):
    if mode == "none":
        return list(markets)
    if mode not in _PRIORITY_KEYS:
        raise ValueError(f"Unknown selection mode: {mode}")

    sort_key = _PRIORITY_KEYS[mode]
    groups: dict[str, list] = {}
    for m in markets:
        groups.setdefault(_template_key(m.question), []).append(m)

    selected = []
    for group in groups.values():
        group.sort(key=sort_key)
        emitted = []
        for candidate in group:
            if all(_deadline_of(e) <= candidate.created_at for e in emitted):
                emitted.append(candidate)
        selected.extend(emitted)
    return selected
