"""Close open Positions whose underlying Market has resolved."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from src.storage.models import Market, Position
from src.live.executor import Executor


def _ensure_utc(ts: datetime) -> datetime:
    return ts if ts.tzinfo is not None else ts.replace(tzinfo=timezone.utc)


def sync_resolutions(
    session: Session, executor: Executor, *, now: datetime
) -> list[Position]:
    """Close every open Position whose Market row now has a resolution."""
    closed: list[Position] = []
    open_positions = session.query(Position).filter(Position.status == "open").all()
    for pos in open_positions:
        market = session.get(Market, pos.market_id)
        if market is None or market.resolution is None:
            continue

        exit_price = 1.0 if market.resolution == "No" else 0.0
        exit_ts = market.resolved_at or now
        exit_ts = _ensure_utc(exit_ts)

        executor.close_position(pos, exit_price=exit_price, exit_timestamp=exit_ts)
        closed.append(pos)
    return closed
