from datetime import datetime, timedelta, timezone

from src.backtester.strategies import (
    at_creation,
    limit,
    price_threshold,
    time_snapshot,
)

def make_history(prices_with_offsets: list[tuple[int, float]], base_time: datetime | None = None):
    if base_time is None:
        base_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return [
        {"timestamp": base_time + timedelta(hours=h), "no_price": p}
        for h, p in prices_with_offsets
    ]

CREATED_AT = datetime(2024, 1, 1, tzinfo=timezone.utc)

def test_at_creation_returns_first_price():
    history = make_history([(1, 0.90), (2, 0.85), (3, 0.80)])
    result = at_creation(CREATED_AT, history)
    assert result == (0.90, CREATED_AT + timedelta(hours=1))

def test_at_creation_empty_history():
    assert at_creation(CREATED_AT, []) is None

def test_threshold_finds_first_below():
    history = make_history([(1, 0.92), (2, 0.88), (3, 0.84), (4, 0.80)])
    result = price_threshold(CREATED_AT, history, threshold=0.85)
    assert result == (0.84, CREATED_AT + timedelta(hours=3))

def test_threshold_exact_match():
    history = make_history([(1, 0.90), (2, 0.85)])
    result = price_threshold(CREATED_AT, history, threshold=0.85)
    assert result == (0.85, CREATED_AT + timedelta(hours=2))

def test_threshold_never_met():
    history = make_history([(1, 0.92), (2, 0.90)])
    assert price_threshold(CREATED_AT, history, threshold=0.85) is None

def test_threshold_empty_history():
    assert price_threshold(CREATED_AT, [], threshold=0.85) is None

def test_snapshot_finds_closest():
    history = make_history([(22, 0.90), (25, 0.88), (48, 0.85)])
    result = time_snapshot(CREATED_AT, history, offset_hours=24)
    assert result == (0.88, CREATED_AT + timedelta(hours=25))

def test_snapshot_exact_match():
    history = make_history([(24, 0.87), (48, 0.85)])
    result = time_snapshot(CREATED_AT, history, offset_hours=24)
    assert result == (0.87, CREATED_AT + timedelta(hours=24))

def test_snapshot_no_data_within_window():
    history = make_history([(100, 0.80), (200, 0.75)])
    assert time_snapshot(CREATED_AT, history, offset_hours=24) is None

def test_snapshot_empty_history():
    assert time_snapshot(CREATED_AT, [], offset_hours=24) is None

def test_limit_fills_on_crossing():
    """Price must have been above threshold first; fill price is exactly threshold."""
    history = make_history([(1, 0.50), (2, 0.45), (3, 0.30), (4, 0.25)])
    result = limit(CREATED_AT, history, threshold=0.30)
    assert result == (0.30, CREATED_AT + timedelta(hours=3))

def test_limit_skips_market_opening_below_threshold():
    """Markets that open at-or-below threshold never trigger — no pre-existing limit order."""
    history = make_history([(1, 0.20), (2, 0.15), (3, 0.40)])
    assert limit(CREATED_AT, history, threshold=0.30) is None

def test_limit_never_crosses():
    history = make_history([(1, 0.80), (2, 0.70), (3, 0.60)])
    assert limit(CREATED_AT, history, threshold=0.50) is None

def test_limit_empty_history():
    assert limit(CREATED_AT, [], threshold=0.30) is None
