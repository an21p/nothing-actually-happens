"""Entry-signal detection + candidate enumeration for the live bot.

Two strategy-specific detectors share the same EntrySignal output:
- `detect_snapshot_entries` — age-window strategy (snapshot_N)
- `detect_threshold_entries` — observation-price strategy (threshold_p)

`enumerate_candidates` is for the dashboard; it classifies every open
market × favorite pair into a state without opening any positions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.backtester.selection import _select_markets, _template_key
from src.live.bankroll import BankrollState
from src.live.favorites import Favorite
from src.storage.models import Market, Position


@dataclass(frozen=True)
class EntrySignal:
    market: Market
    entry_price: float
    entry_timestamp: datetime
    favorite: Favorite


def _ensure_utc(ts: datetime) -> datetime:
    # SQLite round-trips strip tzinfo; assume UTC on naive.
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts


def _load_open_geopolitical_markets(session: Session) -> list[Market]:
    query = select(Market).where(
        Market.resolution.is_(None),
        Market.category == "geopolitical",
    )
    return list(session.execute(query).scalars().all())


def _blocked_by_prior_position(
    session: Session, strategy_label: str
) -> set[str]:
    """Markets on which THIS strategy already entered (ever, any status)."""
    rows = (
        session.query(Position.market_id)
        .filter(Position.strategy == strategy_label)
        .distinct()
        .all()
    )
    return {mid for (mid,) in rows}


def _blocked_template_keys(
    session: Session, strategy_label: str
) -> set[str]:
    """Template keys currently held open by THIS strategy."""
    open_rows = (
        session.query(Position.market_id)
        .filter(
            Position.strategy == strategy_label,
            Position.status == "open",
        )
        .distinct()
        .all()
    )
    keys: set[str] = set()
    for (mid,) in open_rows:
        m = session.get(Market, mid)
        if m is not None:
            keys.add(_template_key(m.question))
    return keys


def detect_snapshot_entries(
    session: Session,
    fav: Favorite,
    *,
    now: datetime,
    tolerance_hours: int,
    quote_fn: Callable[[str], float | None],
) -> list[EntrySignal]:
    offset = fav.params["offset_hours"]
    low = offset - tolerance_hours
    high = offset + tolerance_hours
    oldest = now - timedelta(hours=high)
    youngest = now - timedelta(hours=low)

    markets = _load_open_geopolitical_markets(session)

    def _age_ok(m: Market) -> bool:
        created = _ensure_utc(m.created_at)
        return oldest <= created <= youngest

    candidates = [m for m in markets if _age_ok(m)]
    taken = _blocked_by_prior_position(session, fav.label)
    candidates = [m for m in candidates if m.id not in taken]
    blocked_keys = _blocked_template_keys(session, fav.label)
    candidates = [m for m in candidates if _template_key(m.question) not in blocked_keys]

    # Within a single detection tick, pick at most one market per template group.
    # `_select_markets` handles rolling-series dedup for the backtester (multiple
    # cohorts with non-overlapping deadlines can all emit), but for live entry we
    # want exactly one entry per template — the one ranked first by selection_mode.
    if fav.selection_mode == "earliest_created":
        by_template: dict[str, Market] = {}
        for m in sorted(candidates, key=lambda m: (_ensure_utc(m.created_at),)):
            key = _template_key(m.question)
            if key not in by_template:
                by_template[key] = m
        selected = list(by_template.values())
    else:
        selected = _select_markets(candidates, fav.selection_mode)

    signals: list[EntrySignal] = []
    for m in selected:
        price = quote_fn(m.no_token_id)
        if price is None:
            continue
        signals.append(
            EntrySignal(market=m, entry_price=price, entry_timestamp=now, favorite=fav)
        )
    return signals


def detect_threshold_entries(
    session: Session,
    fav: Favorite,
    *,
    now: datetime,
    quote_fn: Callable[[str], float | None],
) -> list[EntrySignal]:
    threshold = fav.params["threshold"]
    markets = _load_open_geopolitical_markets(session)

    taken = _blocked_by_prior_position(session, fav.label)
    markets = [m for m in markets if m.id not in taken]
    blocked_keys = _blocked_template_keys(session, fav.label)
    markets = [m for m in markets if _template_key(m.question) not in blocked_keys]

    # Quote each; keep those at-or-below threshold.
    priced: list[tuple[Market, float]] = []
    for m in markets:
        price = quote_fn(m.no_token_id)
        if price is None or price > threshold:
            continue
        priced.append((m, price))

    # Template dedup: per Task 7, _select_markets' rolling-series behavior
    # is wrong for live ticks — pick one per template.
    if fav.selection_mode == "earliest_created":
        by_template: dict[str, Market] = {}
        for m, _ in sorted(priced, key=lambda pair: _ensure_utc(pair[0].created_at)):
            key = _template_key(m.question)
            if key not in by_template:
                by_template[key] = m
        selected = list(by_template.values())
    else:
        selected = _select_markets([m for m, _ in priced], fav.selection_mode)

    price_by_id = {m.id: p for m, p in priced}

    return [
        EntrySignal(
            market=m,
            entry_price=price_by_id[m.id],
            entry_timestamp=now,
            favorite=fav,
        )
        for m in selected
    ]


@dataclass(frozen=True)
class Candidate:
    favorite: Favorite
    market: Market
    state: str  # "ready" | "watching" | "waiting" | "expired" | "entered"
    quote: float | None
    target: float | None
    eta_hours: float | None
    age_hours: float
    blocked_by_bankroll: bool


def _classify_snapshot(
    m: Market, fav: Favorite, *, now: datetime, tolerance_hours: int
) -> tuple[str, float | None]:
    created = _ensure_utc(m.created_at)
    age_hours = (now - created).total_seconds() / 3600.0
    offset = fav.params["offset_hours"]
    low = offset - tolerance_hours
    high = offset + tolerance_hours
    if age_hours < low:
        return "waiting", low - age_hours
    if age_hours > high:
        return "expired", None
    return "ready", None


def _classify_threshold(
    quote: float | None, fav: Favorite
) -> str:
    threshold = fav.params["threshold"]
    if quote is None:
        return "watching"
    return "ready" if quote <= threshold else "watching"


def enumerate_candidates(
    session: Session,
    favs: list[Favorite],
    *,
    now: datetime,
    tolerance_hours: int,
    quote_fn: Callable[[str], float | None],
    bankrolls: dict[str, BankrollState],
) -> list[Candidate]:
    markets = _load_open_geopolitical_markets(session)
    # Cache: quote per no_token_id (called once per market regardless of fav count).
    quote_cache: dict[str, float | None] = {}

    def _get_quote(token_id: str) -> float | None:
        if token_id not in quote_cache:
            quote_cache[token_id] = quote_fn(token_id)
        return quote_cache[token_id]

    # Per-strategy: markets already entered by this strategy.
    entered_by: dict[str, set[str]] = {
        fav.label: _blocked_by_prior_position(session, fav.label) for fav in favs
    }

    results: list[Candidate] = []
    for m in markets:
        age_hours = (now - _ensure_utc(m.created_at)).total_seconds() / 3600.0
        for fav in favs:
            if m.id in entered_by.get(fav.label, set()):
                state = "entered"
                quote = None
                target = None
                eta = None
            elif fav.strategy_name == "snapshot":
                state, eta = _classify_snapshot(
                    m, fav, now=now, tolerance_hours=tolerance_hours
                )
                quote = _get_quote(m.no_token_id) if state == "ready" else None
                target = None
            else:  # threshold
                quote = _get_quote(m.no_token_id)
                state = _classify_threshold(quote, fav)
                target = fav.params["threshold"]
                eta = None

            blocked = False
            if state == "ready" and quote is not None:
                br = bankrolls.get(fav.label)
                cost = fav.shares_per_trade * quote
                if br is not None and cost > br.available:
                    blocked = True

            results.append(
                Candidate(
                    favorite=fav,
                    market=m,
                    state=state,
                    quote=quote,
                    target=target,
                    eta_hours=eta,
                    age_hours=age_hours,
                    blocked_by_bankroll=blocked,
                )
            )
    return results
