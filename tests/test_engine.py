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


def _seed_duplicate_group(session):
    # Three markets with the same template, all created same day, different deadlines.
    base_create = datetime(2025, 12, 30, tzinfo=timezone.utc)
    markets = [
        Market(
            id="dup_early",
            question="Will Israel strike Gaza on January 2, 2026?",
            category="geopolitical",
            no_token_id="tok_e",
            created_at=base_create,
            resolved_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            resolution="No",
        ),
        Market(
            id="dup_mid",
            question="Will Israel strike Gaza on January 15, 2026?",
            category="geopolitical",
            no_token_id="tok_m",
            created_at=base_create,
            resolved_at=datetime(2026, 1, 15, tzinfo=timezone.utc),
            resolution="No",
        ),
        Market(
            id="dup_late",
            question="Will Israel strike Gaza on January 31, 2026?",
            category="geopolitical",
            no_token_id="tok_l",
            created_at=base_create,
            resolved_at=datetime(2026, 1, 31, tzinfo=timezone.utc),
            resolution="No",
        ),
    ]
    session.add_all(markets)
    session.flush()
    for m in markets:
        session.add(
            PriceSnapshot(
                market_id=m.id,
                timestamp=base_create,
                no_price=0.85,
                source="api",
            )
        )
    session.commit()


def test_run_backtest_selection_mode_none_writes_all(session):
    _seed_duplicate_group(session)
    run_id = run_backtest(
        session, strategy_name="at_creation", params={}, categories=None,
        selection_mode="none",
    )
    results = session.query(BacktestResult).filter_by(run_id=run_id).all()
    assert len(results) == 3
    assert all(r.strategy == "at_creation" for r in results)


def test_run_backtest_selection_mode_earliest_created_dedupes(session):
    _seed_duplicate_group(session)
    run_id = run_backtest(
        session, strategy_name="at_creation", params={}, categories=None,
        selection_mode="earliest_created",
    )
    results = session.query(BacktestResult).filter_by(run_id=run_id).all()
    assert len(results) == 1
    assert results[0].market_id == "dup_early"
    assert results[0].strategy == "at_creation__earliest_created"


def test_run_backtest_selection_mode_earliest_deadline_dedupes(session):
    _seed_duplicate_group(session)
    run_id = run_backtest(
        session, strategy_name="at_creation", params={}, categories=None,
        selection_mode="earliest_deadline",
    )
    results = session.query(BacktestResult).filter_by(run_id=run_id).all()
    assert len(results) == 1
    assert results[0].market_id == "dup_early"
    assert results[0].strategy == "at_creation__earliest_deadline"


def test_run_backtest_selection_with_params_label(session):
    _seed_duplicate_group(session)
    run_id = run_backtest(
        session, strategy_name="threshold", params={"threshold": 0.85},
        categories=None, selection_mode="earliest_created",
    )
    results = session.query(BacktestResult).filter_by(run_id=run_id).all()
    assert len(results) == 1
    assert results[0].strategy == "threshold_0.85__earliest_created"


def test_run_backtest_default_selection_is_none(session):
    # Backwards compat: not passing selection_mode = old behavior.
    _seed_duplicate_group(session)
    run_id = run_backtest(session, strategy_name="at_creation", params={}, categories=None)
    results = session.query(BacktestResult).filter_by(run_id=run_id).all()
    assert len(results) == 3
    assert all(r.strategy == "at_creation" for r in results)
