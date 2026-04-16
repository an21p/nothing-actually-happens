from datetime import datetime, timedelta, timezone

import pytest

from src.backtester.engine import _select_markets, _template_key
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


def test_select_markets_none_returns_input_unchanged():
    markets = [
        _market("a", "Will X happen on Jan 5, 2026?", _utc(2026, 1, 1), _utc(2026, 1, 5)),
        _market("b", "Will X happen on Jan 6, 2026?", _utc(2026, 1, 1), _utc(2026, 1, 6)),
    ]
    result = _select_markets(markets, "none")
    assert {m.id for m in result} == {"a", "b"}


def test_select_markets_singleton_group_emits_single():
    markets = [_market("solo", "Will Y happen?", _utc(2026, 1, 1), _utc(2026, 1, 5))]
    result = _select_markets(markets, "earliest_created")
    assert [m.id for m in result] == ["solo"]


def test_earliest_created_same_day_batch_picks_smallest_deadline():
    # All created same day; earliest_created ties broken by smallest deadline.
    markets = [
        _market("late", "Will X strike on Jan 31, 2026?", _utc(2025, 12, 30), _utc(2026, 1, 31)),
        _market("mid", "Will X strike on Jan 15, 2026?", _utc(2025, 12, 30), _utc(2026, 1, 15)),
        _market("early", "Will X strike on Jan 2, 2026?", _utc(2025, 12, 30), _utc(2026, 1, 2)),
    ]
    result = _select_markets(markets, "earliest_created")
    assert [m.id for m in result] == ["early"]


def test_earliest_deadline_same_day_batch_picks_smallest_deadline():
    markets = [
        _market("late", "Will X strike on Jan 31, 2026?", _utc(2025, 12, 30), _utc(2026, 1, 31)),
        _market("mid", "Will X strike on Jan 15, 2026?", _utc(2025, 12, 30), _utc(2026, 1, 15)),
        _market("early", "Will X strike on Jan 2, 2026?", _utc(2025, 12, 30), _utc(2026, 1, 2)),
    ]
    result = _select_markets(markets, "earliest_deadline")
    assert [m.id for m in result] == ["early"]


def test_earliest_created_rolling_cohorts_picks_one_per_cohort():
    # Cohort 1 created Jan 2 (deadlines Jan 10, Jan 17).
    # Cohort 2 created Jan 12 (deadlines Jan 24, Jan 31).
    # Cohort 1's pick (Jan 10) resolves before Cohort 2 is created -> Cohort 2 eligible.
    markets = [
        _market("c1a", "Trump strike by Jan 10, 2026?", _utc(2026, 1, 2), _utc(2026, 1, 10)),
        _market("c1b", "Trump strike by Jan 17, 2026?", _utc(2026, 1, 2), _utc(2026, 1, 17)),
        _market("c2a", "Trump strike by Jan 24, 2026?", _utc(2026, 1, 12), _utc(2026, 1, 24)),
        _market("c2b", "Trump strike by Jan 31, 2026?", _utc(2026, 1, 12), _utc(2026, 1, 31)),
    ]
    result = _select_markets(markets, "earliest_created")
    assert sorted(m.id for m in result) == ["c1a", "c2a"]


def test_earliest_deadline_rolling_cohorts_picks_one_per_cohort():
    markets = [
        _market("c1a", "Trump strike by Jan 10, 2026?", _utc(2026, 1, 2), _utc(2026, 1, 10)),
        _market("c1b", "Trump strike by Jan 17, 2026?", _utc(2026, 1, 2), _utc(2026, 1, 17)),
        _market("c2a", "Trump strike by Jan 24, 2026?", _utc(2026, 1, 12), _utc(2026, 1, 24)),
        _market("c2b", "Trump strike by Jan 31, 2026?", _utc(2026, 1, 12), _utc(2026, 1, 31)),
    ]
    result = _select_markets(markets, "earliest_deadline")
    assert sorted(m.id for m in result) == ["c1a", "c2a"]


def test_earliest_created_recurring_pattern_picks_each_occurrence():
    # Daily independent markets -- each new market created after prior resolved.
    markets = [
        _market("d1", "Will WH call lid on Apr 13?", _utc(2026, 4, 9), _utc(2026, 4, 13, 19)),
        _market("d2", "Will WH call lid on Apr 14?", _utc(2026, 4, 14, 0), _utc(2026, 4, 14, 19)),
        _market("d3", "Will WH call lid on Apr 15?", _utc(2026, 4, 15, 0), _utc(2026, 4, 15, 19)),
    ]
    result = _select_markets(markets, "earliest_created")
    assert sorted(m.id for m in result) == ["d1", "d2", "d3"]


def test_earliest_deadline_diverges_from_earliest_created():
    # A: created Jan 2, deadline Jan 30 (long-running)
    # B: created Jan 5, deadline Jan 10 (short, but created later)
    # earliest_created -> picks A (then B blocked: A unresolved at Jan 5)
    # earliest_deadline -> picks B (then A blocked: B unresolved at Jan 2)
    markets = [
        _market("A", "Event by Jan 30, 2026?", _utc(2026, 1, 2), _utc(2026, 1, 30)),
        _market("B", "Event by Jan 10, 2026?", _utc(2026, 1, 5), _utc(2026, 1, 10)),
    ]
    assert [m.id for m in _select_markets(markets, "earliest_created")] == ["A"]
    assert [m.id for m in _select_markets(markets, "earliest_deadline")] == ["B"]


def test_select_markets_unknown_mode_raises():
    markets = [_market("a", "Will X happen?", _utc(2026, 1, 1), _utc(2026, 1, 2))]
    with pytest.raises(ValueError, match="Unknown selection mode"):
        _select_markets(markets, "bogus")


def test_select_markets_missing_resolved_at_falls_back_to_created():
    # Defensive: if resolved_at is None, treat the market as resolving at creation.
    m = _market("nores", "Will X happen by Jan 5, 2026?", _utc(2026, 1, 1), None)
    result = _select_markets([m], "earliest_deadline")
    assert [x.id for x in result] == ["nores"]
