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


def test_collect_drops_markets_created_before_2020():
    """Markets with created_at < 2020-01-01 UTC must never reach upsert_market."""
    fake_markets = [
        _make_market("old", datetime(2019, 6, 1, tzinfo=timezone.utc)),
        _make_market("new", datetime(2021, 6, 1, tzinfo=timezone.utc)),
    ]

    captured_ids: list[str] = []

    def _fake_upsert(session, market_data):
        captured_ids.append(market_data["id"])
        return True

    with patch("src.collector.runner.fetch_resolved_markets", return_value=fake_markets), \
         patch("src.collector.runner.fetch_price_history", return_value=[]), \
         patch("src.collector.runner.upsert_market", side_effect=_fake_upsert):
        collect(categories=["political"], db_path=":memory:")

    assert captured_ids == ["new"], f"pre-2020 market leaked: {captured_ids}"


def test_collect_keeps_markets_created_on_or_after_2020_boundary():
    """Exactly 2020-01-01 00:00:00 UTC must pass the floor (>=, not >)."""
    boundary = datetime(2020, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
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
