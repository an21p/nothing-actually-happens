"""Executor abstractions: paper (in-DB) and a live stub.

The runner never imports PaperExecutor / LiveExecutor directly; it goes
through `get_executor(name, session)`. Swapping from paper to live at a
later date means fleshing out LiveExecutor without touching any other
module.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Protocol

from sqlalchemy.orm import Session

from src.storage.models import Market, Position
from src.live.sizing import SizingResult


class Executor(Protocol):
    def open_position(
        self,
        *,
        market: Market,
        entry_price: float,
        entry_timestamp: datetime,
        sizing_result: SizingResult,
        strategy: str,
    ) -> Position: ...

    def mark_position(self, position: Position, *, mid: float, at: datetime) -> None: ...

    def close_position(
        self, position: Position, *, exit_price: float, exit_timestamp: datetime
    ) -> None: ...


class PaperExecutor:
    """Writes simulated fills + marks to the DB; no external side effects."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def open_position(
        self,
        *,
        market: Market,
        entry_price: float,
        entry_timestamp: datetime,
        sizing_result: SizingResult,
        strategy: str,
    ) -> Position:
        pos = Position(
            market_id=market.id,
            strategy=strategy,
            executor="paper",
            status="open",
            entry_price=entry_price,
            entry_timestamp=entry_timestamp,
            size_shares=sizing_result.shares,
            size_notional=sizing_result.notional,
            sizing_rule=sizing_result.rule,
            sizing_params_json=json.dumps(sizing_result.params),
        )
        self.session.add(pos)
        self.session.flush()
        return pos

    def mark_position(self, position: Position, *, mid: float, at: datetime) -> None:
        position.last_mark_price = mid
        position.last_mark_timestamp = at
        position.unrealized_pnl = (mid - position.entry_price) * position.size_shares

    def close_position(
        self, position: Position, *, exit_price: float, exit_timestamp: datetime
    ) -> None:
        position.status = "resolved"
        position.exit_price = exit_price
        position.exit_timestamp = exit_timestamp
        position.realized_pnl = (exit_price - position.entry_price) * position.size_shares
        position.unrealized_pnl = None


class LiveExecutor:
    """Placeholder. Flesh out when wiring real CLOB orders."""

    _MSG = "Live execution not wired up; set LIVE_EXECUTOR=paper"

    def open_position(self, **_: object) -> Position:  # type: ignore[override]
        raise NotImplementedError(self._MSG)

    def mark_position(self, *_: object, **__: object) -> None:  # type: ignore[override]
        raise NotImplementedError(self._MSG)

    def close_position(self, *_: object, **__: object) -> None:  # type: ignore[override]
        raise NotImplementedError(self._MSG)


def get_executor(name: str, session: Session) -> Executor:
    if name == "paper":
        return PaperExecutor(session)
    if name == "live":
        return LiveExecutor()
    raise ValueError(f"Unknown executor: {name}")
