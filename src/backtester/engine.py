import argparse
import re
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.storage.db import get_engine, get_session
from src.storage.models import Market, PriceSnapshot, BacktestResult
from src.backtester.strategies import STRATEGIES


_MONTH_PATTERN = (
    r"(?:january|february|march|april|may|june|july|august|september|october|"
    r"november|december|jan|feb|mar|apr|may|jun|jul|aug|sept|sep|oct|nov|dec)"
)
_DATE_PHRASE_RE = re.compile(
    rf"\b(?:by|on|before|after|until|in|week\s+of)\s+{_MONTH_PATTERN}\.?\s+"
    rf"\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s*\d{{2,4}})?",
    re.IGNORECASE,
)
_BARE_MONTH_DATE_RE = re.compile(
    rf"\b{_MONTH_PATTERN}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s*\d{{2,4}})?",
    re.IGNORECASE,
)
_NUMERIC_DATE_RE = re.compile(r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b")
_WHITESPACE_RE = re.compile(r"\s+")


def _template_key(question: str) -> str:
    text = _DATE_PHRASE_RE.sub("", question)
    text = _BARE_MONTH_DATE_RE.sub("", text)
    text = _NUMERIC_DATE_RE.sub("", text)
    text = _WHITESPACE_RE.sub(" ", text).strip().lower()
    return text


SELECTION_MODES = ("none", "earliest_created", "earliest_deadline")

_PRIORITY_KEYS = {
    "earliest_created": lambda m: (m.created_at, m.resolved_at or m.created_at),
    "earliest_deadline": lambda m: (m.resolved_at or m.created_at, m.created_at),
}


def _select_markets(markets, mode):
    if mode == "none":
        return list(markets)
    if mode not in _PRIORITY_KEYS:
        raise ValueError(f"Unknown selection mode: {mode}")

    sort_key = _PRIORITY_KEYS[mode]
    groups: dict[str, list] = {}
    for m in markets:
        groups.setdefault(_template_key(m.question), []).append(m)

    selected = []
    for group in groups.values():
        group.sort(key=sort_key)
        emitted = []
        for candidate in group:
            if all(
                (e.resolved_at or e.created_at) <= candidate.created_at
                for e in emitted
            ):
                emitted.append(candidate)
        selected.extend(emitted)
    return selected


def run_backtest(session: Session, strategy_name: str, params: dict, categories: list[str] | None = None) -> str:
    strategy_info = STRATEGIES[strategy_name]
    strategy_fn = strategy_info["fn"]
    param_suffix = ""
    if params:
        param_suffix = "_" + "_".join(str(v) for v in params.values())
    strategy_label = f"{strategy_name}{param_suffix}"
    run_id = str(uuid.uuid4())[:8]

    query = select(Market).where(Market.resolution.isnot(None))
    if categories:
        query = query.where(Market.category.in_(categories))
    markets = session.execute(query).scalars().all()

    for market in markets:
        snapshots = (
            session.query(PriceSnapshot)
            .filter_by(market_id=market.id)
            .order_by(PriceSnapshot.timestamp)
            .all()
        )
        price_history = [{"timestamp": s.timestamp, "no_price": s.no_price} for s in snapshots]
        if not price_history:
            continue

        result = strategy_fn(market.created_at, price_history, **params)
        if result is None:
            continue

        entry_price, entry_timestamp = result
        exit_price = 1.0 if market.resolution == "No" else 0.0
        profit = exit_price - entry_price

        session.add(BacktestResult(
            market_id=market.id, strategy=strategy_label,
            entry_price=entry_price, entry_timestamp=entry_timestamp,
            exit_price=exit_price, profit=profit,
            category=market.category, run_id=run_id,
        ))

    session.commit()
    return run_id


def run_all_strategies(session: Session, categories: list[str] | None = None) -> list[str]:
    run_ids = []
    for strategy_name, info in STRATEGIES.items():
        for params in info["params"]:
            run_id = run_backtest(session, strategy_name, params, categories)
            run_ids.append(run_id)
    return run_ids


def main():
    parser = argparse.ArgumentParser(description="Run backtests")
    parser.add_argument("--strategy", type=str, default=None)
    parser.add_argument("--param", type=str, default=None)
    parser.add_argument("--categories", type=str, default=None)
    args = parser.parse_args()

    engine = get_engine()
    session = get_session(engine)
    categories = args.categories.split(",") if args.categories else None

    if args.strategy:
        params = {}
        if args.param and args.strategy == "threshold":
            params["threshold"] = float(args.param)
        elif args.param and args.strategy == "snapshot":
            params["offset_hours"] = int(args.param)
        run_id = run_backtest(session, args.strategy, params, categories)
        print(f"Backtest complete. Run ID: {run_id}")
    else:
        run_ids = run_all_strategies(session, categories)
        print(f"All backtests complete. {len(run_ids)} runs.")

    session.close()
    engine.dispose()

if __name__ == "__main__":
    main()
