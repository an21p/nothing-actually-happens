from datetime import datetime, timezone

import pytest

from src.storage.models import Market, Trade


def _seed_market(session, market_id, created, resolved=None):
    m = Market(
        id=market_id,
        question=f"Market {market_id}",
        category="political",
        no_token_id="2222",
        created_at=created,
        resolved_at=resolved,
        resolution="No" if resolved else None,
    )
    session.add(m)
    session.commit()
    return m


def _fake_trade(market_id, block, log_idx=0, tx_suffix="aa"):
    return {
        "market_id": market_id,
        "venue": "polymarket",
        "timestamp": datetime.fromtimestamp(1704153600 + block, tz=timezone.utc),
        "price": 0.5,
        "size_shares": 1.0,
        "usdc_notional": 0.5,
        "side": "buy_no",
        "is_yes_token": False,
        "tx_hash": f"0x{tx_suffix:0<64}",
        "log_index": log_idx,
        "block_number": block,
        "maker_address": "0xM",
        "taker_address": "0xT",
        "order_hash": "0xABC",
        "maker_asset_id": "0",
        "taker_asset_id": "2222",
        "fee": 0.0,
        "kalshi_trade_id": None,
        "raw_event_json": "{}",
    }


def test_run_backfill_writes_trades(session):
    from src.collector.trades.runner import run_backfill

    _seed_market(
        session, "0xm1",
        created=datetime(2024, 1, 1, tzinfo=timezone.utc),
        resolved=datetime(2024, 2, 1, tzinfo=timezone.utc),
    )

    def fake_fetch(market, yes_token_id, no_token_id, from_block=None, to_block=None, w3=None):
        yield _fake_trade("0xm1", block=50_000_000, log_idx=0, tx_suffix="a1")
        yield _fake_trade("0xm1", block=50_000_001, log_idx=0, tx_suffix="a2")

    def fake_yes_token(mid):
        return "1111"

    run_backfill(
        session,
        market_ids=["0xm1"],
        fetch_trades_fn=fake_fetch,
        yes_token_fn=fake_yes_token,
    )
    session.commit()
    assert session.query(Trade).count() == 2


def test_run_backfill_is_idempotent(session):
    from src.collector.trades.runner import run_backfill

    _seed_market(
        session, "0xm1",
        created=datetime(2024, 1, 1, tzinfo=timezone.utc),
        resolved=datetime(2024, 2, 1, tzinfo=timezone.utc),
    )

    def fake_fetch(market, yes_token_id, no_token_id, from_block=None, to_block=None, w3=None):
        yield _fake_trade("0xm1", block=50_000_000, log_idx=0, tx_suffix="a1")
        yield _fake_trade("0xm1", block=50_000_001, log_idx=0, tx_suffix="a2")

    run_backfill(session, ["0xm1"], fake_fetch, lambda _: "1111")
    session.commit()
    run_backfill(session, ["0xm1"], fake_fetch, lambda _: "1111")
    session.commit()

    assert session.query(Trade).count() == 2


def test_run_backfill_skips_market_missing_yes_token(session):
    from src.collector.trades.runner import run_backfill

    _seed_market(
        session, "0xm1",
        created=datetime(2024, 1, 1, tzinfo=timezone.utc),
        resolved=datetime(2024, 2, 1, tzinfo=timezone.utc),
    )

    def fake_fetch(market, yes_token_id, no_token_id, from_block=None, to_block=None, w3=None):
        yield _fake_trade("0xm1", block=50_000_000)

    run_backfill(session, ["0xm1"], fake_fetch, lambda _: None)
    session.commit()
    assert session.query(Trade).count() == 0


def test_run_backfill_raises_for_unknown_market(session):
    from src.collector.trades.runner import run_backfill

    def fake_fetch(*a, **kw):
        return iter(())

    with pytest.raises(ValueError, match="unknown market"):
        run_backfill(session, ["0xDOESNOTEXIST"], fake_fetch, lambda _: "1111")


def test_select_pilot_markets_orders_by_most_recent_resolution(session):
    from src.collector.trades.runner import select_pilot_markets

    _seed_market(session, "0xold",
        created=datetime(2023, 1, 1, tzinfo=timezone.utc),
        resolved=datetime(2023, 6, 1, tzinfo=timezone.utc))
    _seed_market(session, "0xmid",
        created=datetime(2024, 1, 1, tzinfo=timezone.utc),
        resolved=datetime(2024, 6, 1, tzinfo=timezone.utc))
    _seed_market(session, "0xnew",
        created=datetime(2024, 6, 1, tzinfo=timezone.utc),
        resolved=datetime(2024, 12, 1, tzinfo=timezone.utc))
    # Unresolved market — must be excluded
    _seed_market(session, "0xopen",
        created=datetime(2025, 1, 1, tzinfo=timezone.utc),
        resolved=None)

    picks = select_pilot_markets(session, n=2)
    assert picks == ["0xnew", "0xmid"]


def test_select_pilot_markets_respects_category_filter(session):
    from src.collector.trades.runner import select_pilot_markets, ALLOWED_CATEGORIES

    # Default categories are geopolitical / political / culture
    assert "political" in ALLOWED_CATEGORIES
    _seed_market(session, "0xpol",
        created=datetime(2024, 1, 1, tzinfo=timezone.utc),
        resolved=datetime(2024, 6, 1, tzinfo=timezone.utc))
    m = session.query(Market).filter_by(id="0xpol").one()
    m.category = "sports"  # outside filter
    session.commit()

    assert select_pilot_markets(session, n=5) == []
