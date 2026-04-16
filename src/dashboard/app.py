from datetime import datetime

import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy import func

from src.storage.db import get_engine, get_session
from src.storage.models import Market, PriceSnapshot, BacktestResult, Position
from src.backtester.engine import run_all_strategies, run_backtest
from src.live.sizing import fixed_notional, fixed_shares, kelly

st.set_page_config(page_title="Polymarket Backtester", layout="wide")

STRATEGY_DESCRIPTIONS = {
    "at_creation": 'Buys the "NO" token at the first recorded price after market creation. Baseline strategy to measure early entry timing.',
    "threshold": 'Waits for the "NO" token price to drop to a specific level before buying. Tests entry discipline by requiring a minimum discount.',
    "snapshot": 'Buys the "NO" token at a fixed time offset after market creation (24h, 48h, or 7d). Tests whether fixed timing works as an edge.',
    "best_price": 'Buys at the lowest "NO" token price observed during the market\'s lifetime. Theoretical upper bound with perfect hindsight.',
}

SELECTION_MODE_DESCRIPTIONS = {
    "__earliest_created": 'Deduplicates near-duplicate markets (same question, different dates — e.g. "Will X happen by Jan 15?" vs. "...by Feb 1?"). Within each template group, keeps only the market created earliest, then walks forward: a later market is only added if it starts after all previously kept markets have resolved. Prevents stacking correlated trades on the same underlying question.',
    "__earliest_deadline": 'Same deduplication as earliest_created, but within each template group prefers the market that resolves soonest (earliest deadline) instead of the one created first. Captures the shortest-dated version of each recurring question.',
}


def get_strategy_description(strategy_label: str) -> str:
    """Return the description for a strategy label like 'threshold_0.85'."""
    base = strategy_label.split("_")[0]
    if base == "at" and strategy_label.startswith("at_creation"):
        base = "at_creation"
    return STRATEGY_DESCRIPTIONS.get(base, "")


@st.cache_resource
def init_db():
    engine = get_engine()
    return engine


def get_db_session():
    engine = init_db()
    return get_session(engine)


# ---- Sidebar ----

st.sidebar.title("Nothing Ever Happens")
st.sidebar.markdown("*Polymarket Backtester*")

session = get_db_session()

# Category filter
all_categories = [
    row[0]
    for row in session.query(Market.category).distinct().all()
    if row[0]
]
selected_categories = st.sidebar.multiselect(
    "Categories", all_categories, default=all_categories
)

# Date range
min_date = session.query(func.min(Market.created_at)).scalar()
max_date = session.query(func.max(Market.created_at)).scalar()
if min_date and max_date:
    date_range = st.sidebar.date_input(
        "Date range",
        value=(min_date.date(), max_date.date()),
        min_value=min_date.date(),
        max_value=max_date.date(),
    )
else:
    date_range = None


def _apply_date_filter(query, date_col):
    """Apply the sidebar date range filter to a query."""
    if date_range and len(date_range) == 2:
        start, end = date_range
        query = query.filter(date_col >= datetime(start.year, start.month, start.day))
        query = query.filter(date_col <= datetime(end.year, end.month, end.day, 23, 59, 59))
    return query


# Strategy filter
all_strategies = [
    row[0]
    for row in session.query(BacktestResult.strategy).distinct().all()
]
selected_strategies = st.sidebar.multiselect(
    "Strategies", all_strategies, default=all_strategies
)

# Run backtest button
if st.sidebar.button("Run All Backtests"):
    with st.spinner("Running backtests..."):
        run_all_strategies(session, categories=selected_categories or None)
    st.sidebar.success("Done!")
    st.rerun()

# Latest run_id per strategy (each strategy gets its own run_id)
_latest_id_subq = (
    session.query(
        BacktestResult.strategy,
        func.max(BacktestResult.id).label("max_id"),
    )
    .group_by(BacktestResult.strategy)
    .subquery()
)
latest_run_ids = [
    row[0]
    for row in session.query(BacktestResult.run_id)
    .join(_latest_id_subq, BacktestResult.id == _latest_id_subq.c.max_id)
    .distinct()
    .all()
]

# ---- Navigation ----

view = st.sidebar.radio(
    "View",
    [
        "Thesis Overview",
        "Strategy Comparison",
        "Deep Dive",
        "Market Browser",
        "Live Positions",
        "Sizing Comparison",
    ],
)


# ---- View: Thesis Overview ----

def render_thesis_overview():
    st.header("Thesis Overview: Does Anything Ever Happen?")

    base_q = session.query(Market).filter(
        Market.resolution.isnot(None),
        Market.category.in_(selected_categories),
    )
    base_q = _apply_date_filter(base_q, Market.created_at)

    total_markets = base_q.count()
    no_count = base_q.filter(Market.resolution == "No").count()
    yes_count = total_markets - no_count
    no_rate = no_count / total_markets if total_markets > 0 else 0

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Resolved Markets", total_markets)
    col2.metric('Resolved "NO"', no_count)
    col3.metric("Resolved Yes", yes_count)
    col4.metric('"NO" Resolution Rate', f"{no_rate:.1%}")

    # Category breakdown
    cat_data = []
    for cat in selected_categories:
        cat_q = session.query(Market).filter(
            Market.resolution.isnot(None), Market.category == cat
        )
        cat_q = _apply_date_filter(cat_q, Market.created_at)
        cat_total = cat_q.count()
        cat_no = cat_q.filter(Market.resolution == "No").count()
        if cat_total > 0:
            cat_data.append({
                "Category": cat,
                '"NO" Rate': cat_no / cat_total,
                "Total": cat_total,
            })

    if cat_data:
        df = pd.DataFrame(cat_data)
        fig = px.bar(
            df, x="Category", y='"NO" Rate', text="Total",
            title='"NO" Resolution Rate by Category',
            color='"NO" Rate',
            color_continuous_scale=["red", "yellow", "green"],
            range_color=[0, 1],
        )
        fig.update_traces(textposition="outside")
        fig.update_yaxes(range=[0, 1], tickformat=".0%")
        st.plotly_chart(fig, use_container_width=True)


# ---- View: Strategy Comparison ----

def render_trade_breakdown(strategy_label: str, results: list) -> None:
    """Detail panel showing every trade that made up a strategy's row."""
    st.markdown(f"### Trade Breakdown — `{strategy_label}`")
    desc = get_strategy_description(strategy_label)
    if desc:
        st.caption(desc)

    market_ids = [r.market_id for r in results]
    markets_by_id = {
        m.id: m
        for m in session.query(Market).filter(Market.id.in_(market_ids)).all()
    }

    rows = []
    for r in sorted(results, key=lambda x: x.profit, reverse=True):
        m = markets_by_id.get(r.market_id)
        rows.append({
            "Question": (m.question if m else "(missing)"),
            "Category": r.category,
            "Resolution": m.resolution if m else "",
            "Entry Price": r.entry_price,
            "Exit Price": r.exit_price,
            "Profit": r.profit,
            "Entry": r.entry_timestamp,
            "URL": m.source_url if m and m.source_url else "",
        })

    trades_df = pd.DataFrame(rows)
    total_profit = trades_df["Profit"].sum()
    wins = int((trades_df["Profit"] > 0).sum())
    losses = int((trades_df["Profit"] < 0).sum())

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Trades", len(trades_df))
    c2.metric("Wins / Losses", f"{wins} / {losses}")
    c3.metric("Total P&L", f"${total_profit:,.2f}")
    c4.metric("Avg Entry", f"${trades_df['Entry Price'].mean():.4f}")

    st.dataframe(
        trades_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Entry Price": st.column_config.NumberColumn(format="$%.4f"),
            "Exit Price": st.column_config.NumberColumn(format="$%.2f"),
            "Profit": st.column_config.NumberColumn(format="$%+.4f"),
            "Entry": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm"),
            "URL": st.column_config.LinkColumn("Link", display_text="open"),
        },
    )


def render_strategy_comparison():
    st.header("Strategy Comparison")

    with st.expander("How positions and P&L work", expanded=False):
        st.markdown(
            """
Polymarket binary markets run on Gnosis's Conditional Token Framework. Each
market mints two ERC-1155 outcome tokens (**Yes** and **No**) that each
redeem for **$1 USDC** if that outcome wins, **$0** if it loses.

- Pre-resolution, the No token trades between $0 and $1 as a market-implied
  probability (e.g. $0.85 ≈ 85% chance of No).
- At resolution it snaps to exactly **$1** (No wins) or **$0** (Yes wins).
- Each strategy buys **1 No share** per market at some historic entry price
  and holds to resolution. Per-trade P&L is `exit_price − entry_price`:
  - Resolves **No** → `1 − entry_price` (profit)
  - Resolves **Yes** → `−entry_price` (full loss of what you paid)

**Why high win rate ≠ high P&L.** The payouts are asymmetric: entering at
$0.95 wins $0.05 and loses $0.95. Breakeven win rate equals the average
entry price, so a strategy that enters at $0.95 needs to win ≥95% of the
time just to not lose money. Strategies that enter cheap (low threshold,
early snapshot) win less often but each win pays more — that's where the
edge usually lives. Compare `Win Rate` to entry price, not to 50%.

**Caveats:** no fees, no slippage, assumes fills at the historic price and
that you hold all the way to resolution (no early exit).
            """
        )

    if not latest_run_ids:
        st.warning("No backtest results found. Run a backtest first.")
        return

    category_filter = st.selectbox(
        "Filter by category",
        ["All"] + sorted(selected_categories),
    )

    results_q = (
        session.query(BacktestResult)
        .filter(BacktestResult.run_id.in_(latest_run_ids))
        .filter(BacktestResult.strategy.in_(selected_strategies))
        .filter(BacktestResult.category.in_(selected_categories))
    )
    if category_filter != "All":
        results_q = results_q.filter(BacktestResult.category == category_filter)
    results_q = _apply_date_filter(results_q, BacktestResult.entry_timestamp)
    all_results = results_q.all()

    if not all_results:
        st.info("No results match your filters.")
        return

    # Group by strategy
    strategy_groups: dict[str, list] = {}
    for r in all_results:
        strategy_groups.setdefault(r.strategy, []).append(r)

    rows = []
    for strategy, results in sorted(strategy_groups.items()):
        profits = [r.profit for r in results]
        entry_costs = [r.entry_price for r in results]
        wins = sum(1 for p in profits if p > 0)
        total = len(profits)
        avg_ev = sum(profits) / total if total else None
        total_pnl = sum(profits)
        total_cost = sum(entry_costs)
        roi = (total_pnl / total_cost * 100) if total_cost else None
        rows.append({
            "Strategy": strategy,
            "Trades": total,
            "Win Rate": (wins / total * 100) if total else None,
            "Avg EV": avg_ev,
            "Total P&L": total_pnl,
            "Cost": total_cost,
            "ROI": roi,
            "_avg_ev": avg_ev or 0,
            "_win_rate": wins / total if total else 0,
            "_roi": roi if roi is not None else float("-inf"),
        })

    df = pd.DataFrame(rows).sort_values("_roi", ascending=False).reset_index(drop=True)

    display_df = df.drop(columns=["_avg_ev", "_win_rate", "_roi"])
    ev_values = df["_avg_ev"]
    styled = display_df.style.apply(
        lambda row: (
            ["background-color: rgba(40, 167, 69, 0.1)"] * len(row) if ev_values.iloc[row.name] > 0
            else ["background-color: rgba(220, 53, 69, 0.1)"] * len(row) if ev_values.iloc[row.name] < 0
            else [""] * len(row)
        ), axis=1
    )
    event = st.dataframe(
        styled,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            "Win Rate": st.column_config.NumberColumn(format="%.1f%%"),
            "Avg EV": st.column_config.NumberColumn(format="$%.4f"),
            "Total P&L": st.column_config.NumberColumn(format="$%.2f"),
            "Cost": st.column_config.NumberColumn(format="$%.2f"),
            "ROI": st.column_config.NumberColumn(format="%.2f%%"),
        },
    )

    selected_rows = event.selection.rows if event and event.selection else []
    if selected_rows:
        selected_strategy = display_df.iloc[selected_rows[0]]["Strategy"]
        render_trade_breakdown(selected_strategy, strategy_groups[selected_strategy])

    st.markdown("### Strategy Descriptions")
    for name, desc in STRATEGY_DESCRIPTIONS.items():
        st.markdown(f"- **{name}** — {desc}")

    st.markdown("### Selection Mode Suffixes")
    st.caption(
        "Suffixes appended to a strategy label (e.g. `threshold_0.85__earliest_created`) "
        "indicate a market-selection filter applied before running the strategy. "
        "No suffix = all resolved markets used as-is."
    )
    for name, desc in SELECTION_MODE_DESCRIPTIONS.items():
        st.markdown(f"- **{name}** — {desc}")


# ---- View: Deep Dive Explorer ----

def render_deep_dive():
    st.header("Deep Dive Explorer")

    if not latest_run_ids:
        st.warning("No backtest results found. Run a backtest first.")
        return

    dive_q = (
        session.query(BacktestResult)
        .filter(BacktestResult.run_id.in_(latest_run_ids))
        .filter(BacktestResult.strategy.in_(selected_strategies))
        .filter(BacktestResult.category.in_(selected_categories))
    )
    dive_q = _apply_date_filter(dive_q, BacktestResult.entry_timestamp)
    results = dive_q.all()

    if not results:
        st.info("No results match your filters.")
        return

    df = pd.DataFrame([{
        "entry_price": r.entry_price,
        "profit": r.profit,
        "category": r.category,
        "strategy": r.strategy,
        "entry_timestamp": r.entry_timestamp,
    } for r in results])

    # Scatter plot: entry price vs profit
    st.caption("Each dot is a single trade. Shows whether cheaper entries consistently lead to higher profits, and how categories cluster.")
    fig_scatter = px.scatter(
        df, x="entry_price", y="profit", color="category",
        title="Entry Price vs Profit",
        labels={"entry_price": '"NO" Entry Price', "profit": "Profit per Share"},
        hover_data=["strategy"],
    )
    fig_scatter.add_hline(y=0, line_dash="dash", line_color="gray")
    st.plotly_chart(fig_scatter, use_container_width=True)

    # Cumulative P&L curve — strategies ordered by total P&L descending
    strategies_by_pnl = (
        df.groupby("strategy")["profit"].sum().sort_values(ascending=False).index.tolist()
    )
    strategy_for_curve = st.selectbox("P&L Curve Strategy", strategies_by_pnl)
    desc = get_strategy_description(strategy_for_curve)
    if desc:
        st.caption(desc)
    st.caption("Running total of profits over time, broken down by category with an overall total. An upward slope means the strategy is consistently profitable; flat or declining signals it's losing edge.")
    strategy_df = df[df["strategy"] == strategy_for_curve].sort_values("entry_timestamp")

    by_category = strategy_df.copy()
    by_category["cumulative_pnl"] = by_category.groupby("category")["profit"].cumsum()

    total = strategy_df.copy()
    total["cumulative_pnl"] = total["profit"].cumsum()
    total["category"] = "Total"

    curve_df = pd.concat([by_category, total], ignore_index=True)

    fig_pnl = px.line(
        curve_df, x="entry_timestamp", y="cumulative_pnl",
        color="category",
        title=f"Cumulative P&L — {strategy_for_curve}",
        labels={"entry_timestamp": "Date", "cumulative_pnl": "Cumulative P&L ($)", "category": "Category"},
    )
    for trace in fig_pnl.data:
        if trace.name == "Total":
            trace.line.width = 4
            trace.line.color = "white"
    fig_pnl.add_hline(y=0, line_dash="dash", line_color="gray")
    st.plotly_chart(fig_pnl, use_container_width=True)

    # Entry price histogram
    st.caption("Shows where most entry prices land. A concentration at higher prices means fewer discount opportunities were available.")
    fig_hist = px.histogram(
        df, x="entry_price", nbins=30, color="category",
        title='Distribution of "NO" Entry Prices',
        labels={"entry_price": '"NO" Token Price at Entry'},
    )
    st.plotly_chart(fig_hist, use_container_width=True)


# ---- View: Market Browser ----

def render_market_browser():
    st.header("Market Browser")

    search = st.text_input("Search markets", "")

    query = session.query(Market).filter(
        Market.resolution.isnot(None),
        Market.category.in_(selected_categories),
    )
    query = _apply_date_filter(query, Market.created_at)
    if search:
        query = query.filter(Market.question.contains(search))

    markets = query.order_by(Market.created_at.desc()).limit(200).all()

    if not markets:
        st.info("No markets found.")
        return

    market_data = [{
        "Question": m.question[:80],
        "Category": m.category,
        "Resolution": m.resolution,
        "Created": m.created_at.strftime("%Y-%m-%d") if m.created_at else "",
        "Resolved": m.resolved_at.strftime("%Y-%m-%d") if m.resolved_at else "",
        "id": m.id,
    } for m in markets]

    df = pd.DataFrame(market_data)
    display_df = df.drop(columns=["id"])

    st.dataframe(display_df, use_container_width=True, hide_index=True)

    # Market detail expander
    selected_idx = st.selectbox(
        "Select market for detail view",
        range(len(markets)),
        format_func=lambda i: markets[i].question[:80],
    )
    selected_market = markets[selected_idx] if markets else None

    if selected_market:
        with st.expander(f"Detail: {selected_market.question[:60]}...", expanded=True):
            st.markdown(f"**Resolution:** {selected_market.resolution}")
            st.markdown(f"**Category:** {selected_market.category}")
            if selected_market.source_url:
                st.markdown(f"[View on Polymarket]({selected_market.source_url})")

            # Price history chart
            snapshots = (
                session.query(PriceSnapshot)
                .filter_by(market_id=selected_market.id)
                .order_by(PriceSnapshot.timestamp)
                .all()
            )
            if snapshots:
                price_df = pd.DataFrame([{
                    "Date": s.timestamp,
                    '"NO" Price': s.no_price,
                    "Source": s.source,
                } for s in snapshots])

                fig = px.line(
                    price_df, x="Date", y='"NO" Price',
                    title='"NO" Token Price History',
                    color="Source",
                )
                fig.update_yaxes(range=[0, 1])
                st.plotly_chart(fig, use_container_width=True)

            # Strategy results for this market
            market_results = (
                session.query(BacktestResult)
                .filter_by(market_id=selected_market.id)
                .all()
            )
            if market_results:
                st.markdown("**Strategy Results:**")
                result_data = [{
                    "Strategy": r.strategy,
                    "Entry Price": f"${r.entry_price:.4f}",
                    "Exit Price": f"${r.exit_price:.2f}",
                    "Profit": f"${r.profit:+.4f}",
                } for r in market_results]
                st.dataframe(pd.DataFrame(result_data), hide_index=True)


# ---- View: Live Positions ----


def _humanize_age(delta_seconds: float) -> str:
    hours = delta_seconds / 3600.0
    if hours < 48:
        return f"{hours:.1f}h"
    return f"{hours / 24:.1f}d"


def _position_detail(pos: Position, market: Market | None) -> None:
    st.markdown(f"### {market.question if market else pos.market_id}")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Entry", f"${pos.entry_price:.4f}")
    c2.metric(
        "Current mid",
        f"${pos.last_mark_price:.4f}" if pos.last_mark_price is not None else "—",
    )
    c3.metric(
        "Unrealized P&L",
        f"${pos.unrealized_pnl:+,.2f}" if pos.unrealized_pnl is not None else "—",
    )
    c4.metric("Shares", f"{pos.size_shares:,.2f}")

    if market is not None and market.source_url:
        st.markdown(f"[Open on Polymarket]({market.source_url})")

    if market is not None:
        snapshots = (
            session.query(PriceSnapshot)
            .filter_by(market_id=market.id)
            .order_by(PriceSnapshot.timestamp)
            .all()
        )
        if snapshots:
            df = pd.DataFrame(
                [
                    {"Date": s.timestamp, '"NO" Price': s.no_price, "Source": s.source}
                    for s in snapshots
                ]
            )
            fig = px.line(
                df,
                x="Date",
                y='"NO" Price',
                color="Source",
                title=f'"NO" Price — entry @ ${pos.entry_price:.4f}',
            )
            fig.update_yaxes(range=[0, 1])
            fig.add_hline(
                y=pos.entry_price, line_dash="dash", line_color="orange",
                annotation_text="entry",
            )
            fig.add_vline(
                x=pos.entry_timestamp, line_dash="dot", line_color="gray",
            )
            st.plotly_chart(fig, use_container_width=True)


def render_live_positions():
    st.header("Live Positions")

    positions = session.query(Position).all()
    if not positions:
        st.info("No live positions yet. Run `uv run python -m src.live.runner`.")
        return

    open_pos = [p for p in positions if p.status == "open"]
    closed_pos = [p for p in positions if p.status != "open"]

    realized = sum((p.realized_pnl or 0.0) for p in closed_pos)
    unrealized = sum((p.unrealized_pnl or 0.0) for p in open_pos)
    wins = sum(1 for p in closed_pos if (p.realized_pnl or 0.0) > 0)
    win_rate = wins / len(closed_pos) if closed_pos else 0.0

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Open", len(open_pos))
    c2.metric("Resolved", len(closed_pos))
    c3.metric("Realized P&L", f"${realized:+,.2f}")
    c4.metric("Unrealized P&L", f"${unrealized:+,.2f}")
    c5.metric("Win rate", f"{win_rate:.1%}" if closed_pos else "—")

    market_ids = [p.market_id for p in positions]
    markets_by_id = {
        m.id: m
        for m in session.query(Market).filter(Market.id.in_(market_ids)).all()
    }

    now = datetime.utcnow()

    st.subheader(f"Open positions ({len(open_pos)})")
    if open_pos:
        rows = []
        for p in open_pos:
            m = markets_by_id.get(p.market_id)
            entry_ts = p.entry_timestamp
            age = (now - entry_ts.replace(tzinfo=None)).total_seconds() if entry_ts else 0.0
            proj_no = (1.0 - p.entry_price) * p.size_shares
            rows.append({
                "Question": m.question if m else p.market_id,
                "Category": m.category if m else "",
                "Age": _humanize_age(age),
                "Entry": p.entry_price,
                "Mid": p.last_mark_price,
                "Shares": p.size_shares,
                "Unrealized": p.unrealized_pnl,
                "Projected (No)": proj_no,
                "Entered": p.entry_timestamp,
                "id": p.id,
            })
        df_open = pd.DataFrame(rows)
        st.dataframe(
            df_open.drop(columns=["id"]),
            use_container_width=True,
            hide_index=True,
            column_config={
                "Entry": st.column_config.NumberColumn(format="$%.4f"),
                "Mid": st.column_config.NumberColumn(format="$%.4f"),
                "Unrealized": st.column_config.NumberColumn(format="$%+.2f"),
                "Projected (No)": st.column_config.NumberColumn(format="$%+.2f"),
                "Entered": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm"),
            },
        )

        selected_q = st.selectbox(
            "Drill down",
            options=["—"] + [r["Question"] for r in rows],
        )
        if selected_q != "—":
            pick = next(r for r in rows if r["Question"] == selected_q)
            pos = session.get(Position, pick["id"])
            _position_detail(pos, markets_by_id.get(pos.market_id))

    st.subheader(f"Resolved positions ({len(closed_pos)})")
    if closed_pos:
        rows = []
        for p in sorted(closed_pos, key=lambda x: x.exit_timestamp or datetime.min, reverse=True):
            m = markets_by_id.get(p.market_id)
            rows.append({
                "Question": m.question if m else p.market_id,
                "Entry": p.entry_price,
                "Exit": p.exit_price,
                "Realized": p.realized_pnl,
                "Entered": p.entry_timestamp,
                "Exited": p.exit_timestamp,
            })
        df_closed = pd.DataFrame(rows)
        st.dataframe(
            df_closed,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Entry": st.column_config.NumberColumn(format="$%.4f"),
                "Exit": st.column_config.NumberColumn(format="$%.2f"),
                "Realized": st.column_config.NumberColumn(format="$%+.2f"),
                "Entered": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm"),
                "Exited": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm"),
            },
        )

    # Equity curve: cumulative realized, sorted by exit timestamp.
    realized_rows = sorted(
        [p for p in closed_pos if p.exit_timestamp],
        key=lambda p: p.exit_timestamp,
    )
    if realized_rows:
        eq_df = pd.DataFrame([
            {"Date": p.exit_timestamp, "Realized": p.realized_pnl or 0.0}
            for p in realized_rows
        ])
        eq_df["Cumulative"] = eq_df["Realized"].cumsum()
        fig = px.line(eq_df, x="Date", y="Cumulative", title="Cumulative realized P&L")
        st.plotly_chart(fig, use_container_width=True)


# ---- View: Sizing Comparison ----


def _apply_rule(rule: str, entry_price: float, bankroll: float, cfg: dict) -> float:
    """Return shares for the given rule + params at the given entry."""
    if rule == "fixed_notional":
        return fixed_notional(
            entry_price=entry_price, bankroll=bankroll, notional=cfg["notional"]
        ).shares
    if rule == "fixed_shares":
        return fixed_shares(
            entry_price=entry_price, bankroll=bankroll, shares=cfg["shares"]
        ).shares
    if rule == "kelly":
        return kelly(
            entry_price=entry_price,
            bankroll=bankroll,
            win_rate=cfg["win_rate"],
            kelly_fraction=cfg["kelly_fraction"],
        ).shares
    return 0.0


def render_sizing_comparison():
    st.header("Sizing Comparison")
    st.caption(
        "Overlay three cumulative-P&L curves on the same resolved trades: "
        "fixed notional, fixed shares, and fractional Kelly. "
        "Picks a backtest run with sizing_rule populated."
    )

    strategies = sorted({
        row[0]
        for row in session.query(BacktestResult.strategy).distinct().all()
    })
    if not strategies:
        st.info("No backtest results yet.")
        return

    strategy_label = st.selectbox(
        "Strategy",
        strategies,
        index=strategies.index("at_creation") if "at_creation" in strategies else 0,
    )

    latest_id = (
        session.query(func.max(BacktestResult.id))
        .filter(BacktestResult.strategy == strategy_label)
        .scalar()
    )
    run_id = (
        session.query(BacktestResult.run_id)
        .filter(BacktestResult.id == latest_id)
        .scalar()
    )
    results = (
        session.query(BacktestResult)
        .filter(
            BacktestResult.run_id == run_id,
            BacktestResult.strategy == strategy_label,
        )
        .order_by(BacktestResult.entry_timestamp)
        .all()
    )
    if not results:
        st.info("No trades for the selected strategy.")
        return

    bankroll = st.number_input("Bankroll (USDC)", value=10_000.0, step=500.0)
    notional = st.number_input("Fixed notional per trade ($)", value=100.0, step=10.0)
    shares = st.number_input("Fixed shares per trade", value=100.0, step=10.0)
    win_rate = st.slider("Kelly win rate", 0.5, 0.99, 0.85, step=0.01)
    kelly_fraction = st.slider("Kelly fraction", 0.05, 1.0, 0.25, step=0.05)

    rule_cfgs = {
        "fixed_notional": {"notional": notional},
        "fixed_shares": {"shares": shares},
        "kelly": {"win_rate": win_rate, "kelly_fraction": kelly_fraction},
    }

    curves: dict[str, list[dict]] = {rule: [] for rule in rule_cfgs}
    totals: dict[str, dict[str, float]] = {
        rule: {"total_pnl": 0.0, "wins": 0, "losses": 0, "notional": 0.0}
        for rule in rule_cfgs
    }
    for r in results:
        for rule, cfg in rule_cfgs.items():
            size_shares = _apply_rule(rule, r.entry_price, bankroll, cfg)
            pnl = r.profit * size_shares
            totals[rule]["total_pnl"] += pnl
            totals[rule]["notional"] += size_shares * r.entry_price
            if r.profit > 0:
                totals[rule]["wins"] += 1
            elif r.profit < 0:
                totals[rule]["losses"] += 1
            curves[rule].append({
                "Date": r.entry_timestamp,
                "P&L": pnl,
                "Rule": rule,
            })

    frames = []
    for rule, rows in curves.items():
        df = pd.DataFrame(rows).sort_values("Date")
        df["Cumulative"] = df["P&L"].cumsum()
        frames.append(df)
    plot_df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if not plot_df.empty:
        fig = px.line(
            plot_df, x="Date", y="Cumulative", color="Rule",
            title="Cumulative P&L by sizing rule",
        )
        st.plotly_chart(fig, use_container_width=True)

    rows = []
    n = len(results)
    for rule, stats_ in totals.items():
        rows.append({
            "Rule": rule,
            "Total P&L": stats_["total_pnl"],
            "Trades": n,
            "Wins": stats_["wins"],
            "Losses": stats_["losses"],
            "Win rate": (stats_["wins"] / n) if n else 0.0,
            "Avg notional/trade": stats_["notional"] / n if n else 0.0,
        })
    st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        use_container_width=True,
        column_config={
            "Total P&L": st.column_config.NumberColumn(format="$%+.2f"),
            "Win rate": st.column_config.NumberColumn(format="%.1%%"),
            "Avg notional/trade": st.column_config.NumberColumn(format="$%.2f"),
        },
    )


# ---- Render selected view ----

if view == "Thesis Overview":
    render_thesis_overview()
elif view == "Strategy Comparison":
    render_strategy_comparison()
elif view == "Deep Dive":
    render_deep_dive()
elif view == "Market Browser":
    render_market_browser()
elif view == "Live Positions":
    render_live_positions()
elif view == "Sizing Comparison":
    render_sizing_comparison()

session.close()
