from datetime import datetime, timezone
from unittest.mock import patch

from src.collector.runner import collect


def _make_market(market_id: str, created_at: datetime) -> dict:
    return {
        "id": market_id,
        "question": f"market {market_id}",
        "category": "political",
        "no_token_id": f"tok_{market_id}",
        "created_at": created_at,
        "end_date": created_at,
        "source_url": None,
        "resolution": "No",
        "resolved_at": created_at,
    }


def test_collect_drops_markets_created_before_floor():
    """Markets with created_at < MIN_CREATED_AT must never reach upsert_market."""
    fake_markets = [
        _make_market("old", datetime(2023, 6, 1, tzinfo=timezone.utc)),
        _make_market("new", datetime(2025, 6, 1, tzinfo=timezone.utc)),
    ]

    captured_ids: list[str] = []

    def _fake_upsert(session, market_data):
        captured_ids.append(market_data["id"])
        return True

    with patch("src.collector.runner.fetch_resolved_markets", return_value=fake_markets), \
         patch("src.collector.runner.fetch_price_history", return_value=[]), \
         patch("src.collector.runner.upsert_market", side_effect=_fake_upsert):
        collect(categories=["political"], db_path=":memory:")

    assert captured_ids == ["new"], f"pre-floor market leaked: {captured_ids}"


def test_collect_keeps_markets_on_floor_boundary():
    """Exactly MIN_CREATED_AT must pass the floor (>=, not >)."""
    from src.collector.runner import MIN_CREATED_AT
    boundary = MIN_CREATED_AT
    fake_markets = [_make_market("boundary", boundary)]

    captured_ids: list[str] = []

    def _fake_upsert(session, market_data):
        captured_ids.append(market_data["id"])
        return True

    with patch("src.collector.runner.fetch_resolved_markets", return_value=fake_markets), \
         patch("src.collector.runner.fetch_price_history", return_value=[]), \
         patch("src.collector.runner.upsert_market", side_effect=_fake_upsert):
        collect(categories=["political"], db_path=":memory:")

    assert captured_ids == ["boundary"], f"boundary market dropped: {captured_ids}"
