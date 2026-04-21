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
import time
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
BatchQuoteFn = Callable[[list[str]], dict[str, float]]


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
    batch_quote_fn: BatchQuoteFn | None = None,
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
    tick_t0 = time.perf_counter()
    logger.info(
        "tick.start now=%s dry_run=%s categories=%s",
        now.isoformat(), dry_run, config.categories,
    )

    # 1. Upsert open markets.
    step_t0 = time.perf_counter()
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
    logger.info(
        "step1.markets: seen=%d upserted=%d elapsed=%.2fs",
        stats["markets_seen"], stats["markets_upserted"],
        time.perf_counter() - step_t0,
    )

    # Pre-fetch midpoints in one batch so detectors + mark-to-market
    # don't make one HTTP call per market. Falls through to per-token
    # `quote_fn` for anything the batch didn't cover.
    quote_cache_hits = 0
    quote_cache_misses = 0
    if batch_quote_fn is not None:
        step_t0 = time.perf_counter()
        token_ids: set[str] = set()
        for m in (
            session.query(Market)
            .filter(Market.resolution.is_(None), Market.category == "geopolitical")
            .all()
        ):
            if m.no_token_id:
                token_ids.add(m.no_token_id)
        for pos in session.query(Position).filter(Position.status == "open").all():
            market = session.get(Market, pos.market_id)
            if market is not None and market.no_token_id:
                token_ids.add(market.no_token_id)
        logger.info("step2.quotes: %d unique token_ids to fetch", len(token_ids))
        cache: dict[str, float] = {}
        if token_ids:
            try:
                cache = batch_quote_fn(sorted(token_ids))
            except Exception as exc:  # noqa: BLE001
                logger.warning("batch_quote_fn failed: %s", exc)
                cache = {}
        logger.info(
            "step2.quotes: %d/%d midpoints cached elapsed=%.2fs",
            len(cache), len(token_ids), time.perf_counter() - step_t0,
        )
        inner_quote_fn = quote_fn

        def _cached_quote(token_id: str) -> float | None:
            nonlocal quote_cache_hits, quote_cache_misses
            if token_id in cache:
                quote_cache_hits += 1
                return cache[token_id]
            quote_cache_misses += 1
            return inner_quote_fn(token_id)

        quote_fn = _cached_quote

    # 2. Load favorites.
    favorites = load_favorites(session, config)
    logger.info(
        "step3.favorites: %d enabled -> %s",
        len(favorites), [f.label for f in favorites],
    )

    # 3. Per favorite: detect → gate → open.
    for fav in favorites:
        fav_t0 = time.perf_counter()
        signals = _detect_for(
            session, fav, now=now,
            tolerance_hours=config.tolerance_hours,
            quote_fn=quote_fn,
        )
        bankroll = compute_bankroll(session, fav.label, fav.starting_bankroll)
        logger.info(
            "fav[%s]: %d signals detected; bankroll available=%.2f locked=%.2f",
            fav.label, len(signals), bankroll.available, bankroll.locked,
        )
        opened_here = 0
        skipped_here = 0
        for sig in signals:
            cost = fav.shares_per_trade * sig.entry_price
            if cost > bankroll.available:
                logger.info(
                    "fav[%s]: skip %s need=%.2f have=%.2f",
                    fav.label, sig.market.id, cost, bankroll.available,
                )
                skipped_here += 1
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
            opened_here += 1
            bankroll = replace(
                bankroll,
                locked=bankroll.locked + cost,
                available=bankroll.available - cost,
                open_positions=bankroll.open_positions + 1,
            )
            logger.info(
                "fav[%s]: opened %s @ %.4f (cost=%.2f, remaining=%.2f)",
                fav.label, sig.market.id, sig.entry_price, cost, bankroll.available,
            )
            try:
                notifier.on_entry(pos, sig.market)
            except Exception as exc:  # noqa: BLE001
                logger.warning("notifier.on_entry failed: %s", exc)
        logger.info(
            "fav[%s]: done opened=%d skipped=%d elapsed=%.2fs",
            fav.label, opened_here, skipped_here, time.perf_counter() - fav_t0,
        )

    # 4. Mark-to-market open positions.
    step_t0 = time.perf_counter()
    open_positions = session.query(Position).filter(Position.status == "open").all()
    logger.info("step4.mark: %d open positions", len(open_positions))
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
    logger.info(
        "step4.mark: %d marked elapsed=%.2fs",
        stats["positions_marked"], time.perf_counter() - step_t0,
    )

    # 5. Sync resolutions + notify.
    step_t0 = time.perf_counter()
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
    logger.info(
        "step5.resolve: %d positions resolved elapsed=%.2fs",
        stats["positions_resolved"], time.perf_counter() - step_t0,
    )

    if dry_run:
        session.rollback()
    else:
        session.commit()
    logger.info(
        "tick.done elapsed=%.2fs quote_cache hits=%d misses=%d stats=%s",
        time.perf_counter() - tick_t0,
        quote_cache_hits, quote_cache_misses, stats,
    )
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Live paper-trading runner")
    parser.add_argument("--dry-run", action="store_true", help="Skip DB writes")
    parser.add_argument(
        "--log-file",
        default="logs/live_runner.log",
        help="Path to append run logs (default: logs/live_runner.log)",
    )
    args = parser.parse_args()

    from src.logging_setup import configure_logging

    configure_logging(args.log_file)
    logger.info("runner.main: starting (log_file=%s)", args.log_file)

    from src.live.open_markets import fetch_open_markets
    from src.live.quotes import fetch_midpoint, fetch_midpoints_batch
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
        batch_quote_fn=fetch_midpoints_batch,
        dry_run=args.dry_run,
    )
    print(json.dumps(stats, indent=2))
    session.close()
    engine.dispose()


if __name__ == "__main__":
    main()
