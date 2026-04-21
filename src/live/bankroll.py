"""Per-strategy bankroll computed from position history (pure function).

Accounting model:
- Entry locks `shares * entry_price` dollars (tracked as `locked`).
- Closed position realizes `(exit_price - entry_price) * shares` — that's
  exactly what's stored in Position.realized_pnl.
- available = starting - locked + sum(realized_pnl)

No mutable state; no new table. The DB stores immutable position facts.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from src.storage.models import Position


@dataclass(frozen=True)
class BankrollState:
    strategy: str
    starting: float
    locked: float
    realized_pnl: float
    available: float
    open_positions: int
    closed_positions: int


def compute_bankroll(session: Session, strategy: str, starting: float) -> BankrollState:
    positions = (
        session.query(Position).filter(Position.strategy == strategy).all()
    )
    locked = 0.0
    realized = 0.0
    open_count = 0
    closed_count = 0
    for p in positions:
        if p.status == "open":
            locked += p.entry_price * p.size_shares
            open_count += 1
        else:
            realized += p.realized_pnl or 0.0
            closed_count += 1
    return BankrollState(
        strategy=strategy,
        starting=starting,
        locked=locked,
        realized_pnl=realized,
        available=starting - locked + realized,
        open_positions=open_count,
        closed_positions=closed_count,
    )
