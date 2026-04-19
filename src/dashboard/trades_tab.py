"""Streamlit "Trades" tab — trade-tape exploration views."""
from datetime import date, datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.storage.models import Market, Trade


def markets_with_trades(session: Session) -> list[Market]:
    """Markets that have at least one row in trades, ordered by most-recent trade."""
    subq = (
        session.query(
            Trade.market_id.label("mid"),
            func.max(Trade.timestamp).label("latest"),
        )
        .filter(Trade.venue == "polymarket")
        .group_by(Trade.market_id)
        .subquery()
    )
    rows = (
        session.query(Market)
        .join(subq, Market.id == subq.c.mid)
        .order_by(subq.c.latest.desc())
        .all()
    )
    return rows


def daily_volume(session: Session, market_id: str) -> list[dict]:
    """Return [{date, notional, shares, trades}] per day for the market."""
    rows = (
        session.query(Trade)
        .filter(Trade.market_id == market_id, Trade.venue == "polymarket")
        .all()
    )
    buckets: dict[date, dict] = {}
    for t in rows:
        d = t.timestamp.date()
        b = buckets.setdefault(d, {"date": d, "notional": 0.0, "shares": 0.0, "trades": 0})
        b["notional"] += t.usdc_notional
        b["shares"] += t.size_shares
        b["trades"] += 1
    return sorted(buckets.values(), key=lambda r: r["date"])


def top_markets_by_notional(session: Session, limit: int = 10) -> list[dict]:
    rows = (
        session.query(
            Trade.market_id,
            func.sum(Trade.usdc_notional).label("total"),
            func.count(Trade.id).label("n"),
        )
        .filter(Trade.venue == "polymarket")
        .group_by(Trade.market_id)
        .order_by(func.sum(Trade.usdc_notional).desc())
        .limit(limit)
        .all()
    )
    return [
        {"market_id": r[0], "total_notional": float(r[1] or 0.0), "trade_count": int(r[2])}
        for r in rows
    ]


def recent_trades(session: Session, market_id: str, limit: int = 50) -> list[Trade]:
    return (
        session.query(Trade)
        .filter(Trade.market_id == market_id, Trade.venue == "polymarket")
        .order_by(Trade.timestamp.desc())
        .limit(limit)
        .all()
    )


def cross_market_daily_volume(session: Session, market_ids: list[str]) -> list[dict]:
    """Return [{date, notional}] summed across the given markets per day."""
    if not market_ids:
        return []
    rows = (
        session.query(Trade.timestamp, Trade.usdc_notional)
        .filter(Trade.venue == "polymarket", Trade.market_id.in_(market_ids))
        .all()
    )
    buckets: dict[date, float] = {}
    for ts, notional in rows:
        buckets[ts.date()] = buckets.get(ts.date(), 0.0) + (notional or 0.0)
    return [{"date": d, "notional": v} for d, v in sorted(buckets.items())]
