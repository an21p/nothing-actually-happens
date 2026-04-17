"""One-pass orchestrator for the live paper-trading bot.

Designed to be invoked by cron every ~10 minutes. In a single pass:

  1. Fetch open markets from Gamma and upsert rows (so new markets become
     eligible for entry on the next pass that catches them in the 24h
     window).
  2. Detect entry signals (`snapshot_24__earliest_deadline`).
  3. Open a Position per signal via the configured executor, subject to
     the `max_open_positions` cap; notify on entry.
  4. Mark all open positions to market via the executor.
  5. Close any positions whose market has resolved; notify on resolution.

All external calls (Gamma, CLOB) are dependency-injected so tests can
drive the runner with deterministic fixtures. The CLI wires up the real
clients.
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy.orm import Session

from src.live.config import LiveConfig, load_config
from src.live.executor import Executor, get_executor
from src.live.notifier import Notifier, get_notifier
from src.live.resolution import sync_resolutions
from src.live.signals import detect_entries
from src.live.sizing import SIZING_RULES, SizingResult
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


def _apply_sizing(cfg: LiveConfig, entry_price: float, bankroll: float) -> SizingResult:
    rule = SIZING_RULES[cfg.sizing_rule]
    if cfg.sizing_rule == "fixed_notional":
        return rule(
            entry_price=entry_price, bankroll=bankroll, notional=cfg.sizing_notional
        )
    if cfg.sizing_rule == "fixed_shares":
        return rule(
            entry_price=entry_price, bankroll=bankroll, shares=cfg.sizing_shares
        )
    raise ValueError(f"Unknown sizing rule: {cfg.sizing_rule}")


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
    """Execute one live pass. All IO deps are injected for testability."""
    stats = {
        "markets_upserted": 0,
        "markets_seen": 0,
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

    # 2. Detect entries.
    signals = detect_entries(
        session,
        now=now,
        categories=config.categories,
        max_age_hours=config.max_age_hours,
        tolerance_hours=config.tolerance_hours,
        quote_fn=quote_fn,
    )

    # 3. Open positions subject to cap.
    open_count = (
        session.query(Position).filter(Position.status == "open").count()
    )
    room = max(0, config.max_open_positions - open_count)
    for signal in signals[:room]:
        sizing = _apply_sizing(
            config, entry_price=signal.entry_price, bankroll=config.bankroll_start
        )
        if sizing.shares <= 0:
            continue
        pos = executor.open_position(
            market=signal.market,
            entry_price=signal.entry_price,
            entry_timestamp=signal.entry_timestamp,
            sizing_result=sizing,
            strategy="snapshot_24__earliest_deadline",
        )
        stats["positions_opened"] += 1
        try:
            notifier.on_entry(pos, signal.market)
        except Exception as exc:  # noqa: BLE001
            logger.warning("notifier.on_entry failed: %s", exc)

    # 4. Mark-to-market open positions.
    open_positions = (
        session.query(Position).filter(Position.status == "open").all()
    )
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
    print(stats)
    session.close()
    engine.dispose()


if __name__ == "__main__":
    main()
