# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Backtester for the "nothing ever happens" thesis on Polymarket: systematically buy the **No** side of resolved binary Yes/No prediction markets in geopolitical/political/culture categories and measure PnL. Not a live trader — an offline analysis pipeline over historical market data stored in SQLite.

## Commands

This project uses **uv**. Prefix Python commands with `uv run` (creates/uses `.venv/` automatically). `uv sync --extra dev` installs dependencies including pytest.

```bash
# Collect resolved markets + price history into data/polymarket.db (iterative — resumes from earliest collected market)
uv run python -m src.collector.runner                          # defaults: political,geopolitical
uv run python -m src.collector.runner --limit 100              # cap fetched markets for quick iteration
uv run python -m src.collector.runner --categories political   # single category
uv run python -m src.collector.runner --enrich-onchain         # ALSO pull on-chain trades via Polygon RPC (slow)

# Run backtests — writes to backtest_results with a fresh run_id per invocation
uv run python -m src.backtester.engine                          # all strategies × all params
uv run python -m src.backtester.engine --strategy threshold --param 0.85
uv run python -m src.backtester.engine --strategy snapshot --param 48

# Dashboard (reads data/polymarket.db)
uv run streamlit run src/dashboard/app.py

# Tests (in-memory SQLite via conftest.py; no network)
uv run pytest
uv run pytest tests/test_engine.py::test_run_backtest_creates_results
uv run pytest -k threshold
```

Optional `POLYGON_RPC_URL` in `.env` (see `.env.example`) — only consulted when `--enrich-onchain` is passed.

## Architecture

Four loosely coupled packages under `src/`, all coordinating through a single SQLite DB at `data/polymarket.db`.

**Data flow:** `collector` → SQLite (`markets`, `price_snapshots`) → `backtester` → SQLite (`backtest_results`) → `dashboard`. Each layer is independently runnable; the dashboard and backtester never call the network.

### `src/storage/`
SQLAlchemy 2.0 ORM models: `Market`, `PriceSnapshot`, `BacktestResult`. `db.get_engine()` auto-creates tables and defaults to `data/polymarket.db`. Tests use `:memory:` via the `engine`/`session` fixtures in `tests/conftest.py`.

### `src/collector/`
- `polymarket_api.py` — paginates Polymarket's public Gamma API (`gamma-api.polymarket.com/markets`) for `closed=true&resolved=true`. `parse_market` drops anything that isn't a true Yes/No binary: `negRisk` markets, non-2-outcome markets, and markets whose outcomes are not exactly `{yes, no}` (case-insensitive) are rejected. This filter is load-bearing — it's what keeps eSports/team-name markets and multi-outcome events out of the backtest.
- `categories.py` — classifies markets into `geopolitical` / `political` / `culture` / `other`. Uses the API-provided tag first (longest match wins), then falls back to regex keyword patterns over the question text. Categories drive the collection filter AND the backtest filter.
- `price_history.py` — pulls `no_token_id` price series from the CLOB API (`clob.polymarket.com/prices-history`) at hourly fidelity.
- `polygon_chain.py` — opt-in enrichment. Reads `OrderFilled` events from the CTF Exchange (`0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E`) in 10k-block chunks, computes trade prices from maker/taker amounts, timestamps via block time. Missing `web3` or RPC connectivity silently yields `[]`.
- `runner.py` — entry point. **Key behavior: collection is iterative/resumable.** If the DB already has markets, the runner queries the current earliest `created_at` and passes it as `end_date_max` to the Gamma API so the next run pulls older markets rather than re-fetching the same recent ones. Markets are upserted (existing rows have resolution refreshed); price snapshots are deduped by `(market_id, timestamp)`. Commits every 10 markets.

### `src/backtester/`
- `strategies.py` — each strategy is a pure function `(created_at, price_history, **params) -> (entry_price, entry_timestamp) | None`. The `STRATEGIES` dict enumerates every `(strategy, params)` combination that `run_all_strategies` should sweep. `time_snapshot` enforces a ±12h window (`SNAPSHOT_MAX_DISTANCE_HOURS`) around the target offset — if no snapshot is close enough, the market is skipped for that strategy rather than using a stale point.
- `engine.py` — iterates resolved markets, applies one strategy, computes profit as `(1.0 if resolution=="No" else 0.0) - entry_price` (reflects the "buy No, hold to resolution" thesis), and tags every row with a fresh 8-char `run_id`. Each param combo gets a distinct `strategy` label like `threshold_0.85`.
- `metrics.py` — groups `BacktestResult` rows by strategy, category, or year and returns dicts with `trade_count`, `win_rate`, `total_pnl`, `avg_ev`, and Sharpe. Always filters by `run_id` — **never aggregate across run_ids**; each invocation of the engine is a separate experiment.

### `src/dashboard/`
Single-file Streamlit app (`app.py`). Sidebar category multiselect + date-range picker feed every query via `_apply_date_filter`. Reads the latest `run_id` to render the default metrics view. There's a button that calls `run_all_strategies` directly — running backtests from the UI writes to the same DB.

## Conventions worth knowing

- **Timestamps are timezone-aware UTC everywhere** (`datetime(... tz=timezone.utc)`). SQLAlchemy columns use `DateTime(timezone=True)`. Don't introduce naive datetimes.
- **Only Yes/No binary markets are valid data.** If you're adding a new filter or market source, preserve the `outcome_set == {"yes", "no"}` invariant.
- **Backtest results accumulate across runs.** Queries in `metrics.py` and `dashboard/app.py` always filter by a specific `run_id`; if you add new aggregates, do the same.
- **No migrations framework.** Schema changes via `Base.metadata.create_all` only add tables/columns on a fresh DB — for existing DBs (`data/polymarket.db`), delete the file or migrate manually.
