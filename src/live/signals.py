"""Entry-signal detection for the live paper-trading bot.

Applies `snapshot_24__earliest_deadline`:
- Market is aged 24h ± tolerance_hours (default 12h)
- Market category is in scope
- Market has no prior Position (no re-entry)
- No open Position on a template-duplicate of this market
- Among template-duplicates inside a tick, earliest end_date wins

Returns a quote-backed `EntrySignal` per selected market.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.storage.models import Market, Position
from src.backtester.selection import _select_markets, _template_key


@dataclass(frozen=True)
class EntrySignal:
    market: Market
    entry_price: float
    entry_timestamp: datetime


def detect_entries(
    session: Session,
    *,
    now: datetime,
    categories: list[str] | None,
    max_age_hours: int = 24,
    tolerance_hours: int = 12,
    quote_fn: Callable[[str], float | None] | None = None,
) -> list[EntrySignal]:
    if quote_fn is None:
        from src.live.quotes import fetch_midpoint
        quote_fn = fetch_midpoint

    low = max_age_hours - tolerance_hours
    high = max_age_hours + tolerance_hours
    oldest_eligible = now - timedelta(hours=high)
    youngest_eligible = now - timedelta(hours=low)

    query = select(Market).where(Market.resolution.is_(None))
    if categories:
        query = query.where(Market.category.in_(categories))
    markets = list(session.execute(query).scalars().all())

    def _age_ok(m: Market) -> bool:
        created = m.created_at
        if created.tzinfo is None:
            # SQLite round-trip strips tzinfo — treat as UTC.
            from datetime import timezone as _tz
            created = created.replace(tzinfo=_tz.utc)
        return oldest_eligible <= created <= youngest_eligible

    candidates = [m for m in markets if _age_ok(m)]

    traded_market_ids = {
        row[0] for row in session.query(Position.market_id).distinct().all()
    }
    candidates = [m for m in candidates if m.id not in traded_market_ids]

    open_pos_markets = (
        session.query(Position.market_id)
        .filter(Position.status == "open")
        .distinct()
        .all()
    )
    blocked_templates = set()
    for (mid,) in open_pos_markets:
        mm = session.get(Market, mid)
        if mm is not None:
            blocked_templates.add(_template_key(mm.question))
    candidates = [
        m for m in candidates if _template_key(m.question) not in blocked_templates
    ]

    selected = _select_markets(candidates, "earliest_deadline")

    signals: list[EntrySignal] = []
    for m in selected:
        price = quote_fn(m.no_token_id)
        if price is None:
            continue
        signals.append(EntrySignal(market=m, entry_price=price, entry_timestamp=now))
    return signals
