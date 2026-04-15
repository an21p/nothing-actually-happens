from datetime import datetime, timezone

from src.storage.models import Market, BacktestResult
from src.backtester.metrics import compute_strategy_metrics, compute_category_metrics, compute_time_period_metrics

def _seed_results(session):
    for i in range(1, 5):
        session.add(Market(id=f"0xm{i}", question=f"Market {i}",
            category="geopolitical" if i <= 2 else "political",
            no_token_id=f"tok_{i}",
            created_at=datetime(2024, i, 1, tzinfo=timezone.utc),
            resolved_at=datetime(2024, i + 3, 1, tzinfo=timezone.utc),
            resolution="No" if i != 3 else "Yes"))
    session.flush()

    results = [
        BacktestResult(market_id="0xm1", strategy="at_creation", entry_price=0.90,
            entry_timestamp=datetime(2024, 1, 2, tzinfo=timezone.utc),
            exit_price=1.0, profit=0.10, category="geopolitical", run_id="run1"),
        BacktestResult(market_id="0xm2", strategy="at_creation", entry_price=0.85,
            entry_timestamp=datetime(2024, 2, 2, tzinfo=timezone.utc),
            exit_price=1.0, profit=0.15, category="geopolitical", run_id="run1"),
        BacktestResult(market_id="0xm3", strategy="at_creation", entry_price=0.80,
            entry_timestamp=datetime(2024, 3, 2, tzinfo=timezone.utc),
            exit_price=0.0, profit=-0.80, category="political", run_id="run1"),
        BacktestResult(market_id="0xm4", strategy="at_creation", entry_price=0.88,
            entry_timestamp=datetime(2024, 4, 2, tzinfo=timezone.utc),
            exit_price=1.0, profit=0.12, category="political", run_id="run1"),
    ]
    session.add_all(results)
    session.commit()

def test_strategy_metrics(session):
    _seed_results(session)
    metrics = compute_strategy_metrics(session, run_id="run1")
    assert len(metrics) == 1
    m = metrics[0]
    assert m["strategy"] == "at_creation"
    assert m["trade_count"] == 4
    assert m["win_count"] == 3
    assert abs(m["win_rate"] - 0.75) < 0.001
    assert abs(m["total_pnl"] - (-0.43)) < 0.01
    assert abs(m["avg_ev"] - (-0.1075)) < 0.001

def test_category_metrics(session):
    _seed_results(session)
    metrics = compute_category_metrics(session, run_id="run1")
    geo = next(m for m in metrics if m["category"] == "geopolitical")
    assert geo["trade_count"] == 2
    assert geo["win_count"] == 2
    assert abs(geo["win_rate"] - 1.0) < 0.001
    assert abs(geo["total_pnl"] - 0.25) < 0.01
    pol = next(m for m in metrics if m["category"] == "political")
    assert pol["trade_count"] == 2
    assert pol["win_count"] == 1
    assert abs(pol["win_rate"] - 0.5) < 0.001

def test_time_period_metrics(session):
    _seed_results(session)
    metrics = compute_time_period_metrics(session, run_id="run1")
    assert len(metrics) == 1
    assert metrics[0]["year"] == 2024
    assert metrics[0]["trade_count"] == 4
