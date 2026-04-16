from datetime import datetime, timezone

from src.storage.models import Market, PriceSnapshot, BacktestResult, Position


def test_create_market(session):
    market = Market(
        id="0xabc123",
        question="Will X happen by 2025?",
        category="geopolitical",
        no_token_id="99887766",
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        resolved_at=datetime(2024, 12, 31, tzinfo=timezone.utc),
        resolution="No",
        source_url="https://polymarket.com/event/test-slug",
    )
    session.add(market)
    session.commit()

    result = session.get(Market, "0xabc123")
    assert result is not None
    assert result.question == "Will X happen by 2025?"
    assert result.resolution == "No"
    assert result.category == "geopolitical"


def test_create_price_snapshot(session):
    market = Market(
        id="0xabc123",
        question="Test market",
        category="political",
        no_token_id="99887766",
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    session.add(market)
    session.flush()

    snapshot = PriceSnapshot(
        market_id="0xabc123",
        timestamp=datetime(2024, 1, 2, tzinfo=timezone.utc),
        no_price=0.85,
        source="api",
    )
    session.add(snapshot)
    session.commit()

    result = session.query(PriceSnapshot).filter_by(market_id="0xabc123").first()
    assert result is not None
    assert result.no_price == 0.85
    assert result.source == "api"


def test_create_backtest_result(session):
    market = Market(
        id="0xabc123",
        question="Test market",
        category="political",
        no_token_id="99887766",
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        resolved_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
        resolution="No",
    )
    session.add(market)
    session.flush()

    result = BacktestResult(
        market_id="0xabc123",
        strategy="threshold_0.85",
        entry_price=0.85,
        entry_timestamp=datetime(2024, 1, 15, tzinfo=timezone.utc),
        exit_price=1.0,
        profit=0.15,
        category="political",
        run_id="run_001",
    )
    session.add(result)
    session.commit()

    fetched = session.query(BacktestResult).filter_by(run_id="run_001").first()
    assert fetched is not None
    assert fetched.profit == 0.15
    assert fetched.strategy == "threshold_0.85"


def test_market_end_date_persists(session):
    end_date = datetime(2025, 6, 1, tzinfo=timezone.utc)
    market = Market(
        id="0xend",
        question="Will X happen by June 1, 2025?",
        category="geopolitical",
        no_token_id="tok_end",
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        end_date=end_date,
    )
    session.add(market)
    session.commit()

    fetched = session.get(Market, "0xend")
    assert fetched.end_date is not None
    assert fetched.end_date.replace(tzinfo=timezone.utc) == end_date


def test_market_end_date_nullable(session):
    market = Market(
        id="0xnoend",
        question="Will Y happen?",
        category="political",
        no_token_id="tok_noend",
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    session.add(market)
    session.commit()
    assert session.get(Market, "0xnoend").end_date is None


def test_create_position_open(session):
    market = Market(
        id="0xpos1",
        question="Will Z happen?",
        category="political",
        no_token_id="tok_pos",
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    session.add(market)
    session.flush()

    pos = Position(
        market_id="0xpos1",
        strategy="snapshot_24__earliest_deadline",
        executor="paper",
        status="open",
        entry_price=0.80,
        entry_timestamp=datetime(2024, 1, 2, tzinfo=timezone.utc),
        size_shares=125.0,
        size_notional=100.0,
        sizing_rule="fixed_notional",
        sizing_params_json='{"notional": 100.0}',
    )
    session.add(pos)
    session.commit()

    fetched = session.query(Position).filter_by(market_id="0xpos1").first()
    assert fetched is not None
    assert fetched.status == "open"
    assert fetched.size_shares == 125.0
    assert fetched.exit_price is None
    assert fetched.realized_pnl is None


def test_create_position_resolved(session):
    market = Market(
        id="0xpos2",
        question="Resolved market",
        category="political",
        no_token_id="tok_pos2",
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        resolution="No",
    )
    session.add(market)
    session.flush()

    pos = Position(
        market_id="0xpos2",
        strategy="snapshot_24__earliest_deadline",
        executor="paper",
        status="resolved",
        entry_price=0.80,
        entry_timestamp=datetime(2024, 1, 2, tzinfo=timezone.utc),
        size_shares=125.0,
        size_notional=100.0,
        sizing_rule="fixed_notional",
        sizing_params_json='{"notional": 100.0}',
        exit_price=1.0,
        exit_timestamp=datetime(2024, 6, 1, tzinfo=timezone.utc),
        realized_pnl=25.0,
    )
    session.add(pos)
    session.commit()

    fetched = session.query(Position).filter_by(market_id="0xpos2").first()
    assert fetched.status == "resolved"
    assert fetched.exit_price == 1.0
    assert fetched.realized_pnl == 25.0


def test_backtest_result_sizing_columns(session):
    market = Market(
        id="0xbtrsize",
        question="Test",
        category="political",
        no_token_id="tok_bt",
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        resolved_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
        resolution="No",
    )
    session.add(market)
    session.flush()

    row = BacktestResult(
        market_id="0xbtrsize",
        strategy="snapshot_24__earliest_deadline",
        entry_price=0.80,
        entry_timestamp=datetime(2024, 1, 2, tzinfo=timezone.utc),
        exit_price=1.0,
        profit=0.20,
        category="political",
        run_id="run_sizing",
        size_shares=125.0,
        size_notional=100.0,
        sizing_rule="fixed_notional",
        pnl_notional=25.0,
    )
    session.add(row)
    session.commit()

    fetched = session.query(BacktestResult).filter_by(run_id="run_sizing").first()
    assert fetched.size_shares == 125.0
    assert fetched.sizing_rule == "fixed_notional"
    assert fetched.pnl_notional == 25.0


def test_backtest_result_sizing_columns_nullable(session):
    # Existing rows without sizing data must still work.
    market = Market(
        id="0xnosize",
        question="Test",
        category="political",
        no_token_id="tok_no",
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        resolved_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
        resolution="No",
    )
    session.add(market)
    session.flush()

    row = BacktestResult(
        market_id="0xnosize",
        strategy="at_creation",
        entry_price=0.85,
        entry_timestamp=datetime(2024, 1, 2, tzinfo=timezone.utc),
        exit_price=1.0,
        profit=0.15,
        category="political",
        run_id="run_legacy",
    )
    session.add(row)
    session.commit()
    fetched = session.query(BacktestResult).filter_by(run_id="run_legacy").first()
    assert fetched.size_shares is None
    assert fetched.sizing_rule is None


def test_market_price_snapshots_relationship(session):
    market = Market(
        id="0xabc123",
        question="Test market",
        category="culture",
        no_token_id="99887766",
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    session.add(market)
    session.flush()

    for i, price in enumerate([0.90, 0.85, 0.80]):
        session.add(PriceSnapshot(
            market_id="0xabc123",
            timestamp=datetime(2024, 1, i + 1, tzinfo=timezone.utc),
            no_price=price,
            source="api",
        ))
    session.commit()

    result = session.get(Market, "0xabc123")
    assert len(result.price_snapshots) == 3
