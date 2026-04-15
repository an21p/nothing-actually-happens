import uuid
from datetime import datetime, timedelta, timezone

from src.storage.models import Market, PriceSnapshot, BacktestResult
from src.backtester.engine import run_backtest

def _seed_data(session):
    m1 = Market(id="0xcond1", question="Will X invade Y?", category="geopolitical",
        no_token_id="token_1", created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        resolved_at=datetime(2024, 6, 1, tzinfo=timezone.utc), resolution="No")
    m2 = Market(id="0xcond2", question="Will Congress pass Z?", category="political",
        no_token_id="token_2", created_at=datetime(2024, 3, 1, tzinfo=timezone.utc),
        resolved_at=datetime(2024, 9, 1, tzinfo=timezone.utc), resolution="Yes")
    session.add_all([m1, m2])
    session.flush()
    base1 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    for i, price in enumerate([0.90, 0.85, 0.80, 0.82, 0.88]):
        session.add(PriceSnapshot(market_id="0xcond1", timestamp=base1 + timedelta(hours=i * 24), no_price=price, source="api"))
    base2 = datetime(2024, 3, 1, tzinfo=timezone.utc)
    for i, price in enumerate([0.70, 0.65, 0.60, 0.55]):
        session.add(PriceSnapshot(market_id="0xcond2", timestamp=base2 + timedelta(hours=i * 24), no_price=price, source="api"))
    session.commit()

def test_run_backtest_at_creation(session):
    _seed_data(session)
    run_id = run_backtest(session, strategy_name="at_creation", params={}, categories=None)
    results = session.query(BacktestResult).filter_by(run_id=run_id).all()
    assert len(results) == 2
    r1 = next(r for r in results if r.market_id == "0xcond1")
    assert r1.entry_price == 0.90
    assert r1.exit_price == 1.0
    assert abs(r1.profit - 0.10) < 0.001
    r2 = next(r for r in results if r.market_id == "0xcond2")
    assert r2.entry_price == 0.70
    assert r2.exit_price == 0.0
    assert abs(r2.profit - (-0.70)) < 0.001

def test_run_backtest_threshold(session):
    _seed_data(session)
    run_id = run_backtest(session, strategy_name="threshold", params={"threshold": 0.85}, categories=None)
    results = session.query(BacktestResult).filter_by(run_id=run_id).all()
    assert len(results) == 2
    r1 = next(r for r in results if r.market_id == "0xcond1")
    assert r1.entry_price == 0.85
    assert r1.strategy == "threshold_0.85"

def test_run_backtest_category_filter(session):
    _seed_data(session)
    run_id = run_backtest(session, strategy_name="at_creation", params={}, categories=["geopolitical"])
    results = session.query(BacktestResult).filter_by(run_id=run_id).all()
    assert len(results) == 1
    assert results[0].market_id == "0xcond1"

def test_run_backtest_skips_unresolved(session):
    session.add(Market(id="0xunresolved", question="Unresolved market", category="political",
        no_token_id="token_3", created_at=datetime(2024, 1, 1, tzinfo=timezone.utc), resolution=None))
    session.commit()
    run_id = run_backtest(session, strategy_name="at_creation", params={}, categories=None)
    results = session.query(BacktestResult).filter_by(run_id=run_id).all()
    assert len(results) == 0
