from datetime import datetime, timezone

from src.storage.models import Market, Trade


def _seed_trade(session, market_id, ts, price, shares, notional, side, block):
    session.add(Trade(
        market_id=market_id, venue="polymarket",
        timestamp=ts, price=price, size_shares=shares,
        usdc_notional=notional, side=side, is_yes_token=False,
        tx_hash=f"0x{block:064x}", log_index=0, block_number=block,
        raw_event_json="{}",
    ))


def _seed_market(session, mid, cat="political"):
    session.add(Market(
        id=mid, question=f"Q {mid}", category=cat,
        no_token_id="2222",
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    ))
    session.commit()


def test_markets_with_trades(session):
    from src.dashboard.trades_tab import markets_with_trades

    _seed_market(session, "0xm1")
    _seed_market(session, "0xm2")
    _seed_trade(session, "0xm1",
        datetime(2024, 2, 1, tzinfo=timezone.utc), 0.5, 1.0, 0.5, "buy_no", 1)
    session.commit()

    result = markets_with_trades(session)
    ids = [r.id for r in result]
    assert "0xm1" in ids
    assert "0xm2" not in ids


def test_daily_volume(session):
    from src.dashboard.trades_tab import daily_volume

    _seed_market(session, "0xm1")
    _seed_trade(session, "0xm1",
        datetime(2024, 2, 1, 9, 0, tzinfo=timezone.utc), 0.5, 10.0, 5.0, "buy_no", 1)
    _seed_trade(session, "0xm1",
        datetime(2024, 2, 1, 14, 0, tzinfo=timezone.utc), 0.6, 10.0, 6.0, "buy_no", 2)
    _seed_trade(session, "0xm1",
        datetime(2024, 2, 2, 9, 0, tzinfo=timezone.utc), 0.7, 10.0, 7.0, "buy_no", 3)
    session.commit()

    rows = daily_volume(session, "0xm1")
    totals = {r["date"]: r["notional"] for r in rows}
    assert totals[datetime(2024, 2, 1).date()] == 11.0
    assert totals[datetime(2024, 2, 2).date()] == 7.0


def test_top_markets_by_notional(session):
    from src.dashboard.trades_tab import top_markets_by_notional

    _seed_market(session, "0xbig")
    _seed_market(session, "0xsmall")
    _seed_trade(session, "0xbig",
        datetime(2024, 2, 1, tzinfo=timezone.utc), 0.5, 100.0, 50.0, "buy_no", 1)
    _seed_trade(session, "0xsmall",
        datetime(2024, 2, 1, tzinfo=timezone.utc), 0.5, 1.0, 0.5, "buy_no", 2)
    session.commit()

    rows = top_markets_by_notional(session, limit=10)
    assert rows[0]["market_id"] == "0xbig"
    assert rows[0]["total_notional"] == 50.0
    assert rows[1]["market_id"] == "0xsmall"


def test_cross_market_daily_volume(session):
    from src.dashboard.trades_tab import cross_market_daily_volume

    _seed_market(session, "0xa")
    _seed_market(session, "0xb")
    _seed_trade(session, "0xa",
        datetime(2024, 2, 1, 9, 0, tzinfo=timezone.utc), 0.5, 10.0, 5.0, "buy_no", 1)
    _seed_trade(session, "0xb",
        datetime(2024, 2, 1, 14, 0, tzinfo=timezone.utc), 0.5, 10.0, 6.0, "buy_no", 2)
    _seed_trade(session, "0xa",
        datetime(2024, 2, 2, 9, 0, tzinfo=timezone.utc), 0.5, 10.0, 7.0, "buy_no", 3)
    session.commit()

    rows = cross_market_daily_volume(session, ["0xa", "0xb"])
    totals = {r["date"]: r["notional"] for r in rows}
    assert totals[datetime(2024, 2, 1).date()] == 11.0
    assert totals[datetime(2024, 2, 2).date()] == 7.0

    # Isolation: excluding 0xb drops its contribution
    rows_a = cross_market_daily_volume(session, ["0xa"])
    assert {r["date"]: r["notional"] for r in rows_a}[datetime(2024, 2, 1).date()] == 5.0


def test_daily_volume_respects_date_range(session):
    from src.dashboard.trades_tab import daily_volume

    _seed_market(session, "0xm1")
    _seed_trade(session, "0xm1",
        datetime(2024, 1, 15, 9, 0, tzinfo=timezone.utc), 0.5, 10.0, 5.0, "buy_no", 1)
    _seed_trade(session, "0xm1",
        datetime(2024, 2, 1, 9, 0, tzinfo=timezone.utc), 0.5, 10.0, 6.0, "buy_no", 2)
    _seed_trade(session, "0xm1",
        datetime(2024, 3, 10, 9, 0, tzinfo=timezone.utc), 0.5, 10.0, 7.0, "buy_no", 3)
    session.commit()

    # Whole range
    all_rows = daily_volume(session, "0xm1")
    assert len(all_rows) == 3

    # Narrow range: only Feb 1
    rows = daily_volume(
        session, "0xm1",
        date_range=(datetime(2024, 2, 1).date(), datetime(2024, 2, 1).date()),
    )
    assert len(rows) == 1
    assert rows[0]["date"] == datetime(2024, 2, 1).date()
    assert rows[0]["notional"] == 6.0


def test_markets_with_trades_respects_date_range(session):
    from src.dashboard.trades_tab import markets_with_trades

    _seed_market(session, "0xold")
    _seed_market(session, "0xrecent")
    _seed_trade(session, "0xold",
        datetime(2023, 6, 1, tzinfo=timezone.utc), 0.5, 1.0, 0.5, "buy_no", 1)
    _seed_trade(session, "0xrecent",
        datetime(2024, 6, 1, tzinfo=timezone.utc), 0.5, 1.0, 0.5, "buy_no", 2)
    session.commit()

    # Only 2024 window → 0xold drops out
    rows = markets_with_trades(
        session,
        date_range=(datetime(2024, 1, 1).date(), datetime(2024, 12, 31).date()),
    )
    ids = [m.id for m in rows]
    assert "0xrecent" in ids
    assert "0xold" not in ids


def test_top_markets_by_notional_respects_date_range(session):
    from src.dashboard.trades_tab import top_markets_by_notional

    _seed_market(session, "0xa")
    _seed_trade(session, "0xa",
        datetime(2024, 1, 15, tzinfo=timezone.utc), 0.5, 10.0, 100.0, "buy_no", 1)
    _seed_trade(session, "0xa",
        datetime(2024, 6, 15, tzinfo=timezone.utc), 0.5, 10.0, 5.0, "buy_no", 2)
    session.commit()

    # Only June: sum = 5.0 (not 105.0)
    rows = top_markets_by_notional(
        session, limit=5,
        date_range=(datetime(2024, 6, 1).date(), datetime(2024, 6, 30).date()),
    )
    assert rows[0]["market_id"] == "0xa"
    assert rows[0]["total_notional"] == 5.0


def test_cross_market_daily_volume_respects_date_range(session):
    from src.dashboard.trades_tab import cross_market_daily_volume

    _seed_market(session, "0xa")
    _seed_trade(session, "0xa",
        datetime(2024, 1, 15, tzinfo=timezone.utc), 0.5, 10.0, 3.0, "buy_no", 1)
    _seed_trade(session, "0xa",
        datetime(2024, 6, 15, tzinfo=timezone.utc), 0.5, 10.0, 7.0, "buy_no", 2)
    session.commit()

    rows = cross_market_daily_volume(
        session, ["0xa"],
        date_range=(datetime(2024, 6, 1).date(), datetime(2024, 6, 30).date()),
    )
    totals = {r["date"]: r["notional"] for r in rows}
    assert totals == {datetime(2024, 6, 15).date(): 7.0}


def test_date_range_none_is_no_op(session):
    """Passing date_range=None (default) returns unfiltered results — backwards compat."""
    from src.dashboard.trades_tab import daily_volume

    _seed_market(session, "0xm1")
    _seed_trade(session, "0xm1",
        datetime(2020, 1, 1, tzinfo=timezone.utc), 0.5, 10.0, 5.0, "buy_no", 1)
    _seed_trade(session, "0xm1",
        datetime(2030, 1, 1, tzinfo=timezone.utc), 0.5, 10.0, 6.0, "buy_no", 2)
    session.commit()

    rows = daily_volume(session, "0xm1", date_range=None)
    assert len(rows) == 2
