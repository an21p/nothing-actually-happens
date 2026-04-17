"""Position sizing rules.

Shared between the live paper-trading bot and the backtester's sizing
comparison view. Every rule returns a `SizingResult` so downstream code
can log/persist both the shares and the notional committed.

Conventions:
- `entry_price` is the No-token price paid (0..1).
- `bankroll` is the current available capital in USDC.
- All rules cap spend at `bankroll` — never return more notional than
  the caller can afford.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class SizingResult:
    shares: float
    notional: float
    rule: str
    params: dict


def _cap_notional(notional: float, bankroll: float) -> float:
    return max(0.0, min(notional, bankroll))


def fixed_notional(
    *, entry_price: float, bankroll: float, notional: float
) -> SizingResult:
    spend = _cap_notional(notional, bankroll)
    shares = spend / entry_price if entry_price > 0 else 0.0
    return SizingResult(
        shares=shares,
        notional=spend,
        rule="fixed_notional",
        params={"notional": notional},
    )


def fixed_shares(
    *, entry_price: float, bankroll: float, shares: float
) -> SizingResult:
    wanted_notional = shares * entry_price
    spend = _cap_notional(wanted_notional, bankroll)
    # If we had to cap, recompute shares so shares*price == spend.
    actual_shares = spend / entry_price if entry_price > 0 else 0.0
    return SizingResult(
        shares=actual_shares,
        notional=spend,
        rule="fixed_shares",
        params={"shares": shares},
    )


SIZING_RULES: dict[str, Callable[..., SizingResult]] = {
    "fixed_notional": fixed_notional,
    "fixed_shares": fixed_shares,
}
