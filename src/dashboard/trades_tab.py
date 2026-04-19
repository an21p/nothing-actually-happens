"""Streamlit "Trades" tab — trade-tape exploration views."""
from datetime import date, datetime, timezone

import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.storage.models import Market, Trade


def _apply_trade_date_filter(query, date_range):
    """Apply a (start_date, end_date) date range tuple to a query filtered on Trade.timestamp.

    date_range is None or a 2-tuple of datetime.date. When set, start is inclusive at 00:00 UTC
    and end is inclusive through 23:59:59 UTC.
    """
    if date_range and len(date_range) == 2:
        start, end = date_range
        query = query.filter(Trade.timestamp >= datetime(start.year, start.month, start.day, tzinfo=timezone.utc))
        query = query.filter(Trade.timestamp <= datetime(end.year, end.month, end.day, 23, 59, 59, tzinfo=timezone.utc))
    return query


def markets_with_trades(session: Session, date_range=None) -> list[Market]:
    """Markets that have at least one row in trades, ordered by most-recent trade."""
    subq_base = (
        session.query(
            Trade.market_id.label("mid"),
            func.max(Trade.timestamp).label("latest"),
        )
        .filter(Trade.venue == "polymarket")
    )
    subq_base = _apply_trade_date_filter(subq_base, date_range)
    subq = subq_base.group_by(Trade.market_id).subquery()
    rows = (
        session.query(Market)
        .join(subq, Market.id == subq.c.mid)
        .order_by(subq.c.latest.desc())
        .all()
    )
    return rows


def daily_volume(session: Session, market_id: str, date_range=None) -> list[dict]:
    """Return [{date, notional, shares, trades}] per day for the market."""
    q = (
        session.query(Trade)
        .filter(Trade.market_id == market_id, Trade.venue == "polymarket")
    )
    q = _apply_trade_date_filter(q, date_range)
    rows = q.all()
    buckets: dict[date, dict] = {}
    for t in rows:
        d = t.timestamp.date()
        b = buckets.setdefault(d, {"date": d, "notional": 0.0, "shares": 0.0, "trades": 0})
        b["notional"] += t.usdc_notional
        b["shares"] += t.size_shares
        b["trades"] += 1
    return sorted(buckets.values(), key=lambda r: r["date"])


def top_markets_by_notional(session: Session, limit: int = 10, date_range=None) -> list[dict]:
    q = (
        session.query(
            Trade.market_id,
            func.sum(Trade.usdc_notional).label("total"),
            func.count(Trade.id).label("n"),
        )
        .filter(Trade.venue == "polymarket")
    )
    q = _apply_trade_date_filter(q, date_range)
    rows = (
        q.group_by(Trade.market_id)
         .order_by(func.sum(Trade.usdc_notional).desc())
         .limit(limit)
         .all()
    )
    return [
        {"market_id": r[0], "total_notional": float(r[1] or 0.0), "trade_count": int(r[2])}
        for r in rows
    ]


def recent_trades(session: Session, market_id: str, limit: int = 50, date_range=None) -> list[Trade]:
    q = (
        session.query(Trade)
        .filter(Trade.market_id == market_id, Trade.venue == "polymarket")
    )
    q = _apply_trade_date_filter(q, date_range)
    return q.order_by(Trade.timestamp.desc()).limit(limit).all()


def cross_market_daily_volume(session: Session, market_ids: list[str], date_range=None) -> list[dict]:
    """Return [{date, notional}] summed across the given markets per day."""
    if not market_ids:
        return []
    q = (
        session.query(Trade.timestamp, Trade.usdc_notional)
        .filter(Trade.venue == "polymarket", Trade.market_id.in_(market_ids))
    )
    q = _apply_trade_date_filter(q, date_range)
    rows = q.all()
    buckets: dict[date, float] = {}
    for ts, notional in rows:
        buckets[ts.date()] = buckets.get(ts.date(), 0.0) + (notional or 0.0)
    return [{"date": d, "notional": v} for d, v in sorted(buckets.items())]


def render(session: Session, selected_categories: list[str], date_range) -> None:
    st.header("Trades — Per-fill tape")

    markets = markets_with_trades(session, date_range=date_range)
    if not markets:
        st.info(
            "No trades collected yet. Run "
            "`uv run python -m src.collector.trades.runner --mode backfill --pilot 5`."
        )
        return

    # Apply sidebar category filter
    markets = [m for m in markets if m.category in selected_categories]
    if not markets:
        st.info("No trades match your category filter.")
        return

    market_labels = {m.id: f"{m.question[:80]} — {m.category}" for m in markets}
    selected_id = st.selectbox(
        "Market",
        options=[m.id for m in markets],
        format_func=lambda mid: market_labels[mid],
    )
    selected_market = next(m for m in markets if m.id == selected_id)

    st.markdown(f"**Question:** {selected_market.question}")
    if selected_market.source_url:
        st.markdown(f"[View on Polymarket]({selected_market.source_url})")
    st.markdown(f"**Resolution:** {selected_market.resolution or '—'}")

    trades = recent_trades(session, selected_id, limit=5000, date_range=date_range)
    if not trades:
        st.info("No trades for this market.")
        return

    df = pd.DataFrame([{
        "timestamp": t.timestamp,
        "price": t.price,
        "size_shares": t.size_shares,
        "usdc_notional": t.usdc_notional,
        "side": t.side,
        "taker": (t.taker_address or "")[:10],
    } for t in trades]).sort_values("timestamp")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Trades", f"{len(df):,}")
    col2.metric("Total notional", f"${df['usdc_notional'].sum():,.0f}")
    col3.metric("Total shares", f"{df['size_shares'].sum():,.0f}")
    col4.metric("VWAP", f"${(df['usdc_notional'].sum() / df['size_shares'].sum()):.4f}"
                if df['size_shares'].sum() else "—")

    # Scatter: price over time, colored by side, sized by shares
    st.subheader("Price over time")
    fig_price = px.scatter(
        df, x="timestamp", y="price", color="side", size="size_shares",
        hover_data=["usdc_notional"], title=None,
    )
    fig_price.update_yaxes(range=[0, 1])
    st.plotly_chart(fig_price, use_container_width=True)

    # Daily volume histogram
    st.subheader("Daily volume")
    vol = daily_volume(session, selected_id, date_range=date_range)
    vol_df = pd.DataFrame(vol)
    if not vol_df.empty:
        fig_vol = px.bar(vol_df, x="date", y="notional",
                         labels={"notional": "USDC notional"})
        st.plotly_chart(fig_vol, use_container_width=True)

    # Cumulative notional vs price
    st.subheader("Cumulative notional vs price")
    cum_df = df.copy()
    cum_df["cum_notional"] = cum_df["usdc_notional"].cumsum()
    fig_cum = px.line(cum_df, x="timestamp", y="cum_notional",
                      labels={"cum_notional": "Cumulative USDC notional"})
    st.plotly_chart(fig_cum, use_container_width=True)

    # Trade ladder (last 50)
    st.subheader("Most recent trades")
    ladder = df.sort_values("timestamp", ascending=False).head(50)
    st.dataframe(
        ladder,
        use_container_width=True, hide_index=True,
        column_config={
            "price": st.column_config.NumberColumn(format="$%.4f"),
            "size_shares": st.column_config.NumberColumn(format="%.2f"),
            "usdc_notional": st.column_config.NumberColumn(format="$%.2f"),
            "timestamp": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm:ss"),
        },
    )

    # Cross-market section
    st.markdown("---")

    all_market_ids = [m.id for m in markets]

    # Cross-market: total daily volume across all collected (+ filtered) markets
    st.subheader("Total daily volume across collected markets")
    cross = cross_market_daily_volume(session, all_market_ids, date_range=date_range)
    if cross:
        cross_df = pd.DataFrame(cross)
        fig_cross = px.line(cross_df, x="date", y="notional",
                            labels={"notional": "USDC notional"})
        st.plotly_chart(fig_cross, use_container_width=True)

    # Cross-market: top markets by notional
    st.subheader("Top markets by notional (all collected)")
    top = top_markets_by_notional(session, limit=10, date_range=date_range)
    if top:
        top_df = pd.DataFrame(top)
        labels = {m.id: m.question[:60] for m in markets}
        top_df["question"] = top_df["market_id"].map(lambda mid: labels.get(mid, mid))
        fig_top = px.bar(top_df, x="question", y="total_notional",
                         labels={"total_notional": "Total USDC notional"})
        fig_top.update_xaxes(tickangle=-30)
        st.plotly_chart(fig_top, use_container_width=True)
