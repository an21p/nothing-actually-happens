# Polymarket "Nothing Ever Happens" Backtester

## Overview

A Python backtesting tool that validates the thesis that most Polymarket events resolve to "No." Fetches historical resolved markets and price data, runs multiple entry strategies, computes expected value, and presents results via an interactive Streamlit dashboard.

**Scope:** Backtester only. The live trading bot is a future project, gated on backtester results proving positive EV.

**Target categories:** Geopolitical, political, and culture/celebrity events.

## Architecture

Pipeline architecture with three stages:

1. **Data Collector** — fetches and caches market data into SQLite
2. **Backtest Engine** — runs entry strategies against stored data
3. **Dashboard** — Streamlit app for interactive exploration

Each stage is independently runnable. Collect once, backtest many times.

## Project Structure

```
polymarket/
├── src/
│   ├── collector/
│   │   ├── polymarket_api.py   # REST API client for markets & outcomes
│   │   ├── polygon_chain.py    # On-chain price history from Polygon
│   │   └── runner.py           # Orchestrates collection, handles rate limits
│   ├── storage/
│   │   ├── models.py           # SQLAlchemy models
│   │   └── db.py               # DB connection, query helpers
│   ├── backtester/
│   │   ├── strategies.py       # Entry strategies
│   │   ├── engine.py           # Runs strategies, computes EV/P&L
│   │   └── metrics.py          # Aggregation by category, strategy, time
│   └── dashboard/
│       └── app.py              # Streamlit app
├── data/
│   └── polymarket.db           # SQLite database (gitignored)
├── pyproject.toml
└── .env                        # API keys if needed (gitignored)
```

## Data Model

### `markets`

| Column      | Type     | Description                                      |
|-------------|----------|--------------------------------------------------|
| id          | TEXT PK  | Polymarket's condition_id                        |
| question    | TEXT     | The market question                              |
| category    | TEXT     | geopolitical, political, culture, or other       |
| created_at  | DATETIME | When the market was created                      |
| resolved_at | DATETIME | When it resolved (null if still open)            |
| resolution  | TEXT     | "Yes", "No", or null if unresolved               |
| source_url  | TEXT     | Link back to Polymarket                          |

### `price_snapshots`

| Column    | Type       | Description                                    |
|-----------|------------|------------------------------------------------|
| id        | INTEGER PK | Auto-increment                                |
| market_id | TEXT FK    | References markets.id                          |
| timestamp | DATETIME   | When this price was recorded                   |
| no_price  | REAL       | Price of the "No" token (0.00-1.00)            |
| source    | TEXT       | "api" or "polygon"                             |

### `backtest_results`

| Column      | Type       | Description                                   |
|-------------|------------|-----------------------------------------------|
| id          | INTEGER PK | Auto-increment                               |
| market_id       | TEXT FK    | References markets.id                          |
| strategy        | TEXT       | e.g., "at_creation", "threshold_0.85"          |
| entry_price     | REAL       | The "No" price at simulated entry              |
| entry_timestamp | DATETIME   | When the simulated entry occurred              |
| exit_price      | REAL       | 1.00 if resolved No, 0.00 if resolved Yes      |
| profit          | REAL       | exit_price - entry_price                       |
| category        | TEXT       | Denormalized from markets for fast queries     |
| run_id          | TEXT       | Groups results from the same backtest run      |

## Data Collector

### Polymarket REST API (`polymarket_api.py`)

- Fetches resolved markets via the `/markets` endpoint filtered by resolved status
- Captures market metadata: question, category, resolution outcome, timestamps
- Captures available price data from the API
- Handles pagination for large result sets
- Exponential backoff for rate limits

### Polygon On-Chain Data (`polygon_chain.py`)

- For each market's "No" token, fetches historical trade data from Polygon
- Reconstructs price timeline from on-chain trades to fill gaps in API price data
- Uses a public Polygon RPC endpoint (configurable to Alchemy/Infura for reliability)

### Runner (`runner.py`)

- Orchestrates both collectors: fetch markets from API, then enrich with on-chain price data
- Incremental collection with upsert logic — safe to re-run without duplicating data
- CLI: `python -m src.collector.runner --categories geopolitical,political,culture`

### Category Mapping

Polymarket's raw tags are stored as-is. A configurable mapping dict classifies markets into our categories (geopolitical, political, culture, other) based on keyword matching and Polymarket's tag taxonomy. Easy to adjust without code changes.

## Backtest Engine

### Entry Strategies (`strategies.py`)

Each strategy is a function: `(market, price_history) -> entry_price | None`

1. **At creation** — first recorded "No" price after market creation
2. **Price threshold** — first "No" price below a configurable threshold. Parameterized for sweeping: 0.70, 0.75, 0.80, 0.85, 0.90, 0.95
3. **Time snapshot** — "No" price at a fixed offset after creation (24h, 48h, 7d). Also parameterized
4. **Best price** — lowest "No" price during the market's lifetime (theoretical max edge with perfect timing)

All strategies hold until resolution. Exit: $1.00 (resolved No) or $0.00 (resolved Yes).

### Engine (`engine.py`)

- Takes a strategy + parameters, runs across all markets matching category filters
- For each market: get entry price from strategy, compute profit, persist result
- Generates a `run_id` per backtest run for grouping
- CLI: `python -m src.backtester.engine --strategy threshold --param 0.85 --categories geopolitical,political,culture`

### Metrics (`metrics.py`)

Aggregates backtest results across dimensions:

- **Per strategy:** total P&L, average EV per trade, win rate, trade count
- **Per category:** same metrics broken down by geopolitical/political/culture
- **Over time:** edge across different periods (e.g., 2022 vs 2023 vs 2024)
- **Risk-adjusted:** Sharpe-like ratio (average return / stddev of returns)

## Dashboard

Streamlit app with four views:

### 1. Thesis Overview

- Headline stats: total resolved markets, overall No-resolution rate
- Bar chart: No-resolution rate by category
- Quick validation of the core thesis

### 2. Strategy Comparison

- Side-by-side table of all strategy/parameter combinations
- Columns: strategy, parameter, trade count, win rate, avg EV, total P&L
- Sortable, with green/red highlighting for positive/negative EV

### 3. Deep Dive Explorer

- Filters: category, time range, strategy, price threshold
- Scatter plot: entry price vs. profit, colored by category
- Cumulative P&L curve over time for selected strategy
- Entry price distribution histogram

### 4. Market Browser

- Searchable table of all collected markets
- Columns: question, category, resolution, dates
- Click-to-expand: price history chart and per-strategy outcomes for that market

### Sidebar Controls

- Category multi-select filter
- Date range picker
- Strategy selector
- "Run backtest" button to trigger engine with selected parameters and refresh

## Tech Stack

- **Python 3.11+**
- **SQLAlchemy** — ORM for SQLite (swappable to Postgres later)
- **SQLite** — zero-infrastructure local storage
- **Streamlit** — interactive dashboard
- **web3.py** — Polygon on-chain data access
- **httpx** — async HTTP client for Polymarket REST API
- **plotly** — charts in the dashboard

## Future: Live Trading Bot

Not in scope for this spec. The bot will be a separate project, built after the backtester demonstrates positive EV. It will reuse the same data models and strategy logic, adding:

- Polymarket CLOB API integration via `py-clob-client`
- Polygon wallet management (USDC)
- Risk management (bet sizing, portfolio caps)
- Real-time market monitoring
