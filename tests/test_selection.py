from datetime import datetime, timedelta, timezone

import pytest

from src.backtester.engine import _template_key
from src.storage.models import Market


def _utc(year, month, day, hour=0):
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


def _market(mid, question, created_at, resolved_at):
    return Market(
        id=mid,
        question=question,
        category="political",
        no_token_id=f"tok_{mid}",
        created_at=created_at,
        resolved_at=resolved_at,
        resolution="No",
    )


def test_template_key_strips_full_month_name_date():
    a = _template_key("Will Israel strike Gaza on January 31, 2026?")
    b = _template_key("Will Israel strike Gaza on January 5, 2026?")
    c = _template_key("Will Israel strike Gaza on December 1?")
    assert a == b == c


def test_template_key_strips_by_phrase():
    a = _template_key("US strikes Iran by February 27, 2026?")
    b = _template_key("US strikes Iran by February 6, 2026?")
    assert a == b


def test_template_key_strips_week_of_phrase():
    a = _template_key("Will Netflix (NFLX) finish week of April 6 above $130?")
    b = _template_key("Will Netflix (NFLX) finish week of March 23 above $130?")
    assert a == b


def test_template_key_strips_short_numeric_date():
    a = _template_key("Trade ABC closes on 4/12?")
    b = _template_key("Trade ABC closes on 12/30/25?")
    assert a == b


def test_template_key_strips_abbreviated_month():
    a = _template_key("Event by Feb 14, 2026?")
    b = _template_key("Event by Mar 7?")
    assert a == b


def test_template_key_distinct_questions_stay_distinct():
    assert _template_key("Will Israel strike Gaza on January 31, 2026?") != _template_key(
        "Will Israel strike Lebanon on January 31, 2026?"
    )


def test_template_key_lowercases_and_collapses_whitespace():
    assert _template_key("  WILL  X   HAPPEN?  ") == "will x happen?"
