from datetime import datetime

import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy import func

from src.storage.db import get_engine, get_session
from src.storage.models import Market, PriceSnapshot, BacktestResult
from src.backtester.engine import run_all_strategies

st.set_page_config(page_title="Polymarket Backtester", layout="wide")

STRATEGY_DESCRIPTIONS = {
    "at_creation": 'Buys the "NO" token at the first recorded price after market creation. Baseline strategy to measure early entry timing.',
    "threshold": 'Waits for the "NO" token price to drop to a specific level before buying. Tests entry discipline by requiring a minimum discount.',
    "snapshot": 'Buys the "NO" token at a fixed time offset after market creation (24h, 48h, or 7d). Tests whether fixed timing works as an edge.',
    "best_price": 'Buys at the lowest "NO" token price observed during the market\'s lifetime. Theoretical upper bound with perfect hindsight.',
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
    "View", ["Thesis Overview", "Strategy Comparison", "Deep Dive", "Market Browser"]
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

def render_strategy_comparison():
    st.header("Strategy Comparison")

    if not latest_run_ids:
        st.warning("No backtest results found. Run a backtest first.")
        return

    results_q = (
        session.query(BacktestResult)
        .filter(BacktestResult.run_id.in_(latest_run_ids))
        .filter(BacktestResult.strategy.in_(selected_strategies))
        .filter(BacktestResult.category.in_(selected_categories))
    )
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
        wins = sum(1 for p in profits if p > 0)
        total = len(profits)
        avg_ev = sum(profits) / total if total else None
        rows.append({
            "Strategy": strategy,
            "Trades": total,
            "Win Rate": (wins / total * 100) if total else None,
            "Avg EV": avg_ev,
            "Total P&L": sum(profits),
            "Sharpe": (avg_ev / (pd.Series(profits).std() or 1)) if total > 1 else None,
            "_avg_ev": avg_ev or 0,
            "_win_rate": wins / total if total else 0,
        })

    df = pd.DataFrame(rows).sort_values("_win_rate", ascending=False).reset_index(drop=True)

    display_df = df.drop(columns=["_avg_ev", "_win_rate"])
    ev_values = df["_avg_ev"]
    styled = display_df.style.apply(
        lambda row: (
            ["background-color: rgba(40, 167, 69, 0.1)"] * len(row) if ev_values.iloc[row.name] > 0
            else ["background-color: rgba(220, 53, 69, 0.1)"] * len(row) if ev_values.iloc[row.name] < 0
            else [""] * len(row)
        ), axis=1
    )
    st.dataframe(
        styled,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Win Rate": st.column_config.NumberColumn(format="%.1f%%"),
            "Avg EV": st.column_config.NumberColumn(format="$%.4f"),
            "Total P&L": st.column_config.NumberColumn(format="$%.2f"),
            "Sharpe": st.column_config.NumberColumn(format="%.2f"),
        },
    )

    st.markdown("### Strategy Descriptions")
    for name, desc in STRATEGY_DESCRIPTIONS.items():
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


# ---- Render selected view ----

if view == "Thesis Overview":
    render_thesis_overview()
elif view == "Strategy Comparison":
    render_strategy_comparison()
elif view == "Deep Dive":
    render_deep_dive()
elif view == "Market Browser":
    render_market_browser()

session.close()
