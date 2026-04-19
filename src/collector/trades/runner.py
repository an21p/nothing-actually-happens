"""Trade-tape collector runner.

Provides run_backfill / run_catchup as pure-ish functions taking injected
fetchers (for testability), plus a CLI via main().
"""
import argparse
import logging
import sys
import time
from typing import Callable, Iterator

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.storage.db import get_engine, get_session
from src.storage.models import Market, Trade
from src.collector.trades import polymarket

logger = logging.getLogger(__name__)

ALLOWED_CATEGORIES = ("geopolitical", "political", "culture")
WRITE_BATCH = 100
COMMIT_BATCH = 500


def select_pilot_markets(session: Session, n: int) -> list[str]:
    """Return the N most-recently-resolved market IDs in ALLOWED_CATEGORIES."""
    rows = (
        session.query(Market.id)
        .filter(Market.resolution.isnot(None))
        .filter(Market.resolved_at.isnot(None))
        .filter(Market.category.in_(ALLOWED_CATEGORIES))
        .order_by(Market.resolved_at.desc())
        .limit(n)
        .all()
    )
    return [r[0] for r in rows]


def _existing_keys(session: Session, market_id: str) -> set[tuple[str, int]]:
    rows = (
        session.query(Trade.tx_hash, Trade.log_index)
        .filter(Trade.market_id == market_id, Trade.venue == "polymarket")
        .all()
    )
    return {(r[0], r[1]) for r in rows}


def _max_block_for_market(session: Session, market_id: str) -> int | None:
    return (
        session.query(func.max(Trade.block_number))
        .filter(Trade.market_id == market_id, Trade.venue == "polymarket")
        .scalar()
    )


def _write_trade(session: Session, trade_dict: dict, seen_keys: set) -> bool:
    """Insert a trade dict; return True if written, False if deduplicated."""
    key = (trade_dict["tx_hash"], trade_dict["log_index"])
    if key in seen_keys:
        return False
    seen_keys.add(key)
    session.add(Trade(**trade_dict))
    return True


def run_backfill(
    session: Session,
    market_ids: list[str],
    fetch_trades_fn: Callable[..., Iterator[dict]],
    yes_token_fn: Callable[[str], str | None],
) -> dict[str, int]:
    """Backfill the full block window for each market. Returns {market_id: trades_written}."""
    results: dict[str, int] = {}
    for market_id in market_ids:
        market = session.get(Market, market_id)
        if market is None:
            raise ValueError(f"unknown market id: {market_id}")

        yes_id = yes_token_fn(market_id)
        if yes_id is None:
            logger.warning("skip %s: yes_token_id unavailable", market_id)
            results[market_id] = 0
            continue

        seen = _existing_keys(session, market_id)
        written = 0
        started = time.monotonic()

        try:
            for trade in fetch_trades_fn(
                market,
                yes_token_id=yes_id,
                no_token_id=market.no_token_id,
            ):
                if _write_trade(session, trade, seen):
                    written += 1
                    if written % WRITE_BATCH == 0:
                        session.flush()
                    if written % COMMIT_BATCH == 0:
                        session.commit()
            session.commit()
            logger.info(
                "backfill %s: %d trades in %.1fs",
                market_id, written, time.monotonic() - started,
            )
        except Exception as exc:
            session.rollback()
            logger.warning("backfill %s aborted after %d trades: %s", market_id, written, exc)

        results[market_id] = written
    return results


def _catchup_market_ids(session: Session) -> list[str]:
    """Union of (markets with existing trades) and (resolved filtered markets w/ no trades yet)."""
    with_trades = {
        r[0] for r in session.query(Trade.market_id)
        .filter(Trade.venue == "polymarket")
        .distinct().all()
    }
    new_resolved = {
        r[0] for r in session.query(Market.id)
        .filter(Market.resolution.isnot(None))
        .filter(Market.resolved_at.isnot(None))
        .filter(Market.category.in_(ALLOWED_CATEGORIES))
        .all()
        if r[0] not in with_trades
    }
    return sorted(with_trades | new_resolved)


def run_catchup(
    session: Session,
    fetch_trades_fn: Callable[..., Iterator[dict]],
    yes_token_fn: Callable[[str], str | None],
) -> dict[str, int]:
    """Incremental pull for markets in trades + any resolved markets not yet present."""
    results: dict[str, int] = {}
    for market_id in _catchup_market_ids(session):
        market = session.get(Market, market_id)
        if market is None:
            continue

        yes_id = yes_token_fn(market_id)
        if yes_id is None:
            logger.warning("skip %s: yes_token_id unavailable", market_id)
            continue

        last_block = _max_block_for_market(session, market_id)
        from_block = (last_block + 1) if last_block is not None else None

        seen = _existing_keys(session, market_id)
        written = 0
        started = time.monotonic()

        try:
            for trade in fetch_trades_fn(
                market,
                yes_token_id=yes_id,
                no_token_id=market.no_token_id,
                from_block=from_block,
            ):
                if _write_trade(session, trade, seen):
                    written += 1
                    if written % WRITE_BATCH == 0:
                        session.flush()
                    if written % COMMIT_BATCH == 0:
                        session.commit()
            session.commit()
            logger.info(
                "catchup %s: %d new trades in %.1fs",
                market_id, written, time.monotonic() - started,
            )
        except Exception as exc:
            session.rollback()
            logger.warning("catchup %s aborted after %d trades: %s", market_id, written, exc)

        results[market_id] = written
    return results
