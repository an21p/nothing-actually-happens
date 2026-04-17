# nothing-actually-happens

A Polymarket backtester for the **"nothing ever happens"** thesis: systematically buy the **No** side of binary Yes/No prediction markets in geopolitical, political, and cultural categories — then measure how often the market was right to be boring.

> Most dramatic-sounding things that "could happen" don't. This repo puts a number on that intuition.

## What it does

1. **Collects** resolved Yes/No markets and their hourly price history from Polymarket's Gamma + CLOB APIs into a local SQLite DB.
2. **Classifies** each market into `geopolitical` / `political` / `culture` / `other` using tag and keyword heuristics.
3. **Backtests** a sweep of entry strategies (threshold-based, time-snapshot based) that always sell at `No` token resolution. Profit per trade is `(1.0 if resolution == "No" else 0.0) - entry_price`.
4. **Reports** win rate, total PnL, average EV, and Sharpe per strategy / category / year.
5. **Paper-trades** the winning strategy against live open markets (read-only; no funds at risk) with a Streamlit dashboard to monitor positions.

This is an **offline analysis pipeline**, not a live on-chain trader. The optional `--enrich-onchain` flag pulls Polygon CTF Exchange trades for richer fill data but is not required.

## Quick start

Requires Python 3.11+ and [`uv`](https://github.com/astral-sh/uv).

```bash
# Install
uv sync --extra dev

# Collect resolved markets (resumable — subsequent runs walk backwards in time)
uv run python -m src.collector.runner

# Run every strategy × param combo; writes a new run_id to backtest_results
uv run python -m src.backtester.engine

# Explore results
uv run streamlit run src/dashboard/app.py

# Tests (in-memory SQLite, no network)
uv run pytest
```

## Architecture

Four loosely coupled packages under `src/`, all coordinating through a single SQLite DB at `data/polymarket.db`.

```
collector ──► SQLite ──► backtester ──► SQLite ──► dashboard
                │                                     ▲
                └─────────────► live (paper) ─────────┘
```

| Package | Role |
|---------|------|
| `src/collector/` | Paginates Gamma API for `closed=true&resolved=true`, filters to true binary Yes/No markets, pulls hourly No-token price history. Optional Polygon RPC enrichment. |
| `src/backtester/` | Pure-function strategies `(created_at, price_history, **params) → (entry_price, entry_ts)`. Engine iterates markets, computes PnL, tags every row with a fresh 8-char `run_id`. |
| `src/dashboard/` | Streamlit app for category/date-filtered metrics. Can trigger backtests from the UI. |
| `src/live/` | Cron-friendly one-pass paper-trading runner: fetch open markets → detect entries → mark-to-market → close on resolution. |

## Design notes

- **Only Yes/No binary markets are valid data.** `negRisk` markets, non-2-outcome events, and any market whose outcomes aren't exactly `{yes, no}` (case-insensitive) are rejected at parse time. This is what keeps eSports and multi-outcome slates out of the dataset.
- **Collection is iterative and resumable.** If the DB already has markets, the next collector run passes the earliest known `created_at` as `end_date_max` so it walks backwards rather than re-fetching the same recent window.
- **Backtest results accumulate across runs.** Every query in `metrics.py` and the dashboard filters by a specific `run_id`. Never aggregate across runs — each engine invocation is its own experiment.
- **Timestamps are timezone-aware UTC everywhere.** SQLAlchemy columns use `DateTime(timezone=True)`; don't introduce naive datetimes.
- **No migrations framework.** Schema changes via `Base.metadata.create_all` only add tables on fresh DBs. For existing DBs, delete `data/polymarket.db` or migrate manually.

## Configuration

Optional `.env` (see `.env.example`):

```
POLYGON_RPC_URL=https://polygon-rpc.com   # only consulted with --enrich-onchain
```

## Disclaimer

This repository is a research tool. Historical performance of the "nothing ever happens" thesis on resolved markets is not a prediction of future results, and nothing here is financial advice. The live module is paper-trading only.

## License

MIT
