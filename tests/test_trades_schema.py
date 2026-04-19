from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from src.storage.models import Market, Trade


def _make_market(session, id="0xm1"):
    market = Market(
        id=id,
        question="Test market",
        category="political",
        no_token_id="100",
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    session.add(market)
    session.flush()
    return market


def test_trade_roundtrip(session):
    _make_market(session)
    trade = Trade(
        market_id="0xm1",
        venue="polymarket",
        timestamp=datetime(2024, 1, 2, 10, 0, tzinfo=timezone.utc),
        price=0.42,
        size_shares=100.0,
        usdc_notional=42.0,
        side="buy_no",
        is_yes_token=False,
        tx_hash="0xdeadbeef",
        log_index=3,
        block_number=50_000_000,
        maker_address="0xaa",
        taker_address="0xbb",
        order_hash="0xabc",
        maker_asset_id="0",
        taker_asset_id="100",
        fee=0.0,
        raw_event_json='{"foo":"bar"}',
    )
    session.add(trade)
    session.commit()

    fetched = session.query(Trade).filter_by(market_id="0xm1").one()
    assert fetched.price == 0.42
    assert fetched.side == "buy_no"
    assert fetched.is_yes_token is False
    assert fetched.venue == "polymarket"


def test_trade_onchain_unique_constraint_rejects_duplicate(session):
    _make_market(session)
    t1 = Trade(
        market_id="0xm1", venue="polymarket",
        timestamp=datetime(2024, 1, 2, tzinfo=timezone.utc),
        price=0.5, size_shares=1.0, usdc_notional=0.5,
        side="buy_no", is_yes_token=False,
        tx_hash="0xabc", log_index=0, block_number=1,
        raw_event_json="{}",
    )
    session.add(t1)
    session.commit()

    t2 = Trade(
        market_id="0xm1", venue="polymarket",
        timestamp=datetime(2024, 1, 3, tzinfo=timezone.utc),
        price=0.6, size_shares=1.0, usdc_notional=0.6,
        side="sell_no", is_yes_token=False,
        tx_hash="0xabc", log_index=0, block_number=1,
        raw_event_json="{}",
    )
    session.add(t2)
    with pytest.raises(IntegrityError):
        session.commit()


def test_trade_multiple_null_txhash_allowed(session):
    """Kalshi rows have tx_hash=NULL; multiple NULLs must coexist."""
    _make_market(session)
    for kalshi_id in ("k1", "k2"):
        session.add(Trade(
            market_id="0xm1", venue="kalshi",
            timestamp=datetime(2024, 1, 2, tzinfo=timezone.utc),
            price=0.5, size_shares=1.0, usdc_notional=0.5,
            side="buy_no", is_yes_token=False,
            tx_hash=None, log_index=None, block_number=None,
            kalshi_trade_id=kalshi_id,
            raw_event_json="{}",
        ))
    session.commit()
    assert session.query(Trade).filter_by(venue="kalshi").count() == 2


def test_trade_kalshi_unique_constraint_rejects_duplicate(session):
    _make_market(session)
    session.add(Trade(
        market_id="0xm1", venue="kalshi",
        timestamp=datetime(2024, 1, 2, tzinfo=timezone.utc),
        price=0.5, size_shares=1.0, usdc_notional=0.5,
        side="buy_no", is_yes_token=False,
        kalshi_trade_id="KDUP",
        raw_event_json="{}",
    ))
    session.commit()

    session.add(Trade(
        market_id="0xm1", venue="kalshi",
        timestamp=datetime(2024, 1, 3, tzinfo=timezone.utc),
        price=0.5, size_shares=1.0, usdc_notional=0.5,
        side="sell_no", is_yes_token=False,
        kalshi_trade_id="KDUP",
        raw_event_json="{}",
    ))
    with pytest.raises(IntegrityError):
        session.commit()
