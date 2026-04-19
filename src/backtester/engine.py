import argparse
import uuid

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from src.storage.db import get_engine, get_session
from src.storage.models import Market, PriceSnapshot, BacktestResult
from src.backtester.strategies import STRATEGIES
from src.backtester.selection import (
    SELECTION_MODES,
    _PRIORITY_KEYS,
    _select_markets,
    _template_key,
)
from src.live.sizing import SIZING_RULES, SizingResult

__all__ = [
    "run_backtest",
    "run_all_strategies",
    "SELECTION_MODES",
    "_PRIORITY_KEYS",
    "_select_markets",
    "_template_key",
]


def _compute_sizing(
    rule: str, params: dict, entry_price: float, bankroll: float
) -> SizingResult | None:
    if rule == "unit":
        return None
    if rule not in SIZING_RULES:
        raise ValueError(f"Unknown sizing rule: {rule}")
    fn = SIZING_RULES[rule]
    return fn(entry_price=entry_price, bankroll=bankroll, **params)


def run_backtest(
    session: Session,
    strategy_name: str,
    params: dict,
    categories: list[str] | None = None,
    selection_mode: str = "none",
    sizing_rule: str = "unit",
    sizing_params: dict | None = None,
    bankroll: float = 1_000_000.0,
) -> str:
    if selection_mode not in SELECTION_MODES:
        raise ValueError(f"Unknown selection mode: {selection_mode}")

    sizing_params = sizing_params or {}

    strategy_info = STRATEGIES[strategy_name]
    strategy_fn = strategy_info["fn"]
    param_suffix = ""
    if params:
        param_suffix = "_" + "_".join(str(v) for v in params.values())
    selection_suffix = "" if selection_mode == "none" else f"__{selection_mode}"
    strategy_label = f"{strategy_name}{param_suffix}{selection_suffix}"
    run_id = str(uuid.uuid4())[:8]

    has_snapshots = exists().where(PriceSnapshot.market_id == Market.id)
    query = select(Market).where(Market.resolution.isnot(None), has_snapshots)
    if categories:
        query = query.where(Market.category.in_(categories))
    markets = session.execute(query).scalars().all()
    markets = _select_markets(markets, selection_mode)

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

        sizing = _compute_sizing(sizing_rule, sizing_params, entry_price, bankroll)
        size_shares = sizing.shares if sizing else None
        size_notional = sizing.notional if sizing else None
        sizing_rule_label = sizing.rule if sizing else None
        pnl_notional = profit * sizing.shares if sizing else None

        session.add(BacktestResult(
            market_id=market.id, strategy=strategy_label,
            entry_price=entry_price, entry_timestamp=entry_timestamp,
            exit_price=exit_price, profit=profit,
            category=market.category, run_id=run_id,
            size_shares=size_shares, size_notional=size_notional,
            sizing_rule=sizing_rule_label, pnl_notional=pnl_notional,
        ))

    session.commit()
    return run_id


def run_all_strategies(session: Session, categories: list[str] | None = None) -> list[str]:
    run_ids = []
    for selection_mode in SELECTION_MODES:
        for strategy_name, info in STRATEGIES.items():
            for params in info["params"]:
                run_id = run_backtest(
                    session, strategy_name, params, categories, selection_mode
                )
                run_ids.append(run_id)
    return run_ids


def main():
    parser = argparse.ArgumentParser(description="Run backtests")
    parser.add_argument("--strategy", type=str, default=None)
    parser.add_argument("--param", type=str, default=None)
    parser.add_argument("--categories", type=str, default=None)
    parser.add_argument(
        "--selection",
        type=str,
        choices=list(SELECTION_MODES),
        default="none",
        help="Selection mode for deduplicating template-duplicate markets",
    )
    parser.add_argument(
        "--sizing",
        type=str,
        choices=["unit", "fixed_notional", "fixed_shares"],
        default="unit",
        help="Position-sizing rule. 'unit' (default) writes per-share profit only.",
    )
    parser.add_argument("--sizing-notional", type=float, default=100.0)
    parser.add_argument("--sizing-shares", type=float, default=100.0)
    parser.add_argument("--bankroll", type=float, default=1_000_000.0)
    args = parser.parse_args()

    sizing_params: dict = {}
    if args.sizing == "fixed_notional":
        sizing_params = {"notional": args.sizing_notional}
    elif args.sizing == "fixed_shares":
        sizing_params = {"shares": args.sizing_shares}

    engine = get_engine()
    session = get_session(engine)
    categories = args.categories.split(",") if args.categories else None

    if args.strategy:
        params = {}
        if args.param and args.strategy == "threshold":
            params["threshold"] = float(args.param)
        elif args.param and args.strategy == "snapshot":
            params["offset_hours"] = int(args.param)
        run_id = run_backtest(
            session, args.strategy, params, categories, args.selection,
            sizing_rule=args.sizing, sizing_params=sizing_params,
            bankroll=args.bankroll,
        )
        print(f"Backtest complete. Run ID: {run_id}")
    else:
        run_ids = run_all_strategies(session, categories)
        print(f"All backtests complete. {len(run_ids)} runs.")

    session.close()
    engine.dispose()

if __name__ == "__main__":
    main()
