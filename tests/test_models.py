from datetime import datetime, timezone

from src.storage.models import Market, PriceSnapshot, BacktestResult


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
