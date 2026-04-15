import statistics

from sqlalchemy import func, extract
from sqlalchemy.orm import Session

from src.storage.models import BacktestResult


def compute_strategy_metrics(session: Session, run_id: str) -> list[dict]:
    strategies = (
        session.query(BacktestResult.strategy).filter_by(run_id=run_id).distinct().all()
    )
    metrics = []
    for (strategy,) in strategies:
        results = session.query(BacktestResult).filter_by(run_id=run_id, strategy=strategy).all()
        metrics.append(_compute_group_metrics(results, {"strategy": strategy}))
    return metrics


def compute_category_metrics(session: Session, run_id: str) -> list[dict]:
    categories = (
        session.query(BacktestResult.category).filter_by(run_id=run_id).distinct().all()
    )
    metrics = []
    for (category,) in categories:
        results = session.query(BacktestResult).filter_by(run_id=run_id, category=category).all()
        metrics.append(_compute_group_metrics(results, {"category": category}))
    return metrics


def compute_time_period_metrics(session: Session, run_id: str) -> list[dict]:
    years = (
        session.query(extract("year", BacktestResult.entry_timestamp).label("year"))
        .filter_by(run_id=run_id).distinct().all()
    )
    metrics = []
    for (year,) in years:
        results = (
            session.query(BacktestResult)
            .filter(BacktestResult.run_id == run_id, extract("year", BacktestResult.entry_timestamp) == year)
            .all()
        )
        metrics.append(_compute_group_metrics(results, {"year": int(year)}))
    return metrics


def _compute_group_metrics(results: list[BacktestResult], group_info: dict) -> dict:
    profits = [r.profit for r in results]
    trade_count = len(results)
    win_count = sum(1 for r in results if r.profit > 0)
    total_pnl = sum(profits)
    avg_ev = total_pnl / trade_count if trade_count > 0 else 0.0
    win_rate = win_count / trade_count if trade_count > 0 else 0.0
    sharpe = 0.0
    if len(profits) > 1:
        std = statistics.stdev(profits)
        if std > 0:
            sharpe = avg_ev / std
    return {
        **group_info,
        "trade_count": trade_count,
        "win_count": win_count,
        "win_rate": win_rate,
        "total_pnl": total_pnl,
        "avg_ev": avg_ev,
        "sharpe": sharpe,
    }
