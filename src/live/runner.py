"""One-pass orchestrator for the multi-strategy live paper-trading bot.

Run by cron every ~6 hours. In a single pass:

  1. Fetch open markets from Gamma and upsert rows.
  2. Load favorites from the DB + config.
  3. Per favorite: detect entry signals and bankroll-gate them before
     opening paper positions.
  4. Mark all open positions to market via the executor.
  5. Close any positions whose market has resolved; notify on resolution.

All external calls (Gamma, CLOB) are dependency-injected so tests can
drive the runner with deterministic fixtures.
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import replace
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy.orm import Session

from src.live.bankroll import compute_bankroll
from src.live.config import LiveConfig, load_config
from src.live.executor import Executor, get_executor
from src.live.favorites import Favorite, load_favorites
from src.live.notifier import Notifier, get_notifier
from src.live.resolution import sync_resolutions
from src.live.signals import detect_snapshot_entries, detect_threshold_entries
from src.live.sizing import SizingResult
from src.storage.models import Market, Position

logger = logging.getLogger(__name__)

FetchOpenFn = Callable[[list[str] | None], list[dict]]
QuoteFn = Callable[[str], float | None]


def _upsert_open_market(session: Session, row: dict) -> bool:
    existing = session.get(Market, row["id"])
    if existing is not None:
        for attr in ("question", "category", "no_token_id", "end_date"):
            if attr in row and row[attr] is not None:
                setattr(existing, attr, row[attr])
        return False
    session.add(Market(**row))
    return True


def _detect_for(
    session: Session,
    fav: Favorite,
    *,
    now: datetime,
    tolerance_hours: int,
    quote_fn: QuoteFn,
):
    if fav.strategy_name == "snapshot":
        return detect_snapshot_entries(
            session, fav, now=now, tolerance_hours=tolerance_hours, quote_fn=quote_fn
        )
    if fav.strategy_name == "threshold":
        return detect_threshold_entries(session, fav, now=now, quote_fn=quote_fn)
    raise ValueError(f"unsupported strategy in runner: {fav.strategy_name}")


def run_once(
    session: Session,
    config: LiveConfig,
    *,
    now: datetime,
    executor: Executor,
    notifier: Notifier,
    fetch_open_fn: FetchOpenFn,
    quote_fn: QuoteFn,
    dry_run: bool = False,
) -> dict:
    stats = {
        "markets_seen": 0,
        "markets_upserted": 0,
        "positions_opened": 0,
        "positions_marked": 0,
        "positions_resolved": 0,
        "dry_run": dry_run,
    }

    # 1. Upsert open markets.
    try:
        raw_markets = fetch_open_fn(config.categories) or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("fetch_open_fn failed: %s", exc)
        raw_markets = []
    stats["markets_seen"] = len(raw_markets)
    for row in raw_markets:
        if _upsert_open_market(session, row):
            stats["markets_upserted"] += 1
    session.flush()

    # 2. Load favorites.
    favorites = load_favorites(session, config)

    # 3. Per favorite: detect → gate → open.
    for fav in favorites:
        signals = _detect_for(
            session, fav, now=now,
            tolerance_hours=config.tolerance_hours,
            quote_fn=quote_fn,
        )
        bankroll = compute_bankroll(session, fav.label, fav.starting_bankroll)
        for sig in signals:
            cost = fav.shares_per_trade * sig.entry_price
            if cost > bankroll.available:
                logger.info(
                    "skip %s for %s: need %.2f, have %.2f",
                    sig.market.id, fav.label, cost, bankroll.available,
                )
                continue
            sizing = SizingResult(
                shares=fav.shares_per_trade,
                notional=cost,
                rule="fixed_shares",
                params={"shares": fav.shares_per_trade},
            )
            pos = executor.open_position(
                market=sig.market,
                entry_price=sig.entry_price,
                entry_timestamp=sig.entry_timestamp,
                sizing_result=sizing,
                strategy=fav.label,
            )
            stats["positions_opened"] += 1
            bankroll = replace(
                bankroll,
                locked=bankroll.locked + cost,
                available=bankroll.available - cost,
                open_positions=bankroll.open_positions + 1,
            )
            try:
                notifier.on_entry(pos, sig.market)
            except Exception as exc:  # noqa: BLE001
                logger.warning("notifier.on_entry failed: %s", exc)

    # 4. Mark-to-market open positions.
    open_positions = session.query(Position).filter(Position.status == "open").all()
    for pos in open_positions:
        market = session.get(Market, pos.market_id)
        if market is None:
            continue
        try:
            mid = quote_fn(market.no_token_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("quote_fn failed for %s: %s", market.no_token_id, exc)
            mid = None
        if mid is None:
            continue
        executor.mark_position(pos, mid=mid, at=now)
        stats["positions_marked"] += 1

    # 5. Sync resolutions + notify.
    closed = sync_resolutions(session, executor, now=now)
    stats["positions_resolved"] = len(closed)
    for pos in closed:
        market = session.get(Market, pos.market_id)
        if market is None:
            continue
        try:
            notifier.on_resolution(pos, market)
        except Exception as exc:  # noqa: BLE001
            logger.warning("notifier.on_resolution failed: %s", exc)

    if dry_run:
        session.rollback()
    else:
        session.commit()
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Live paper-trading runner")
    parser.add_argument("--dry-run", action="store_true", help="Skip DB writes")
    args = parser.parse_args()

    from src.live.open_markets import fetch_open_markets
    from src.live.quotes import fetch_midpoint
    from src.storage.db import get_engine, get_session

    config = load_config()
    engine = get_engine()
    session = get_session(engine)

    executor = get_executor(config.executor, session)
    notifier = get_notifier()

    stats = run_once(
        session,
        config,
        now=datetime.now(tz=timezone.utc),
        executor=executor,
        notifier=notifier,
        fetch_open_fn=lambda cats: fetch_open_markets(categories=cats),
        quote_fn=fetch_midpoint,
        dry_run=args.dry_run,
    )
    print(json.dumps(stats, indent=2))
    session.close()
    engine.dispose()


if __name__ == "__main__":
    main()
