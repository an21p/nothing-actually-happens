# Polymarket & Kalshi Trade-Tape Collector — Design

**Date:** 2026-04-19
**Status:** Proposed
**Author:** Claude (brainstorming session with user)

## Background

The project today captures resolved Polymarket markets and hourly price snapshots (from the CLOB `prices-history` endpoint) plus optional per-fill price snapshots (from Polygon on-chain `OrderFilled` events). These feed the "nothing ever happens" No-side backtester.

For deeper market microstructure analysis (volume profiles, trader behavior, cross-venue comparison), we need the **full trade tape** — one row per executed fill with price, size, side, and maximal traceability. The existing `price_snapshots` table is lossy for this: it keeps only `(timestamp, no_price, source)` and drops size, side, counterparty, and on-chain provenance.

This spec adds a dedicated trade-tape collector, starting with Polymarket (Polygon on-chain), with Kalshi scaffolded as a second venue for later activation.

## Goal

Capture full historical trade tape for Polymarket Yes/No binary markets in the existing category filter (`geopolitical / political / culture`), store it in the project SQLite DB with idempotent upserts, and surface it in a new Streamlit dashboard tab. Provide a shell wrapper for daily catchup that the user schedules externally.

## Non-goals

- **No L1/L2 book reconstruction.** On-chain `OrderFilled` events give the tape (executed trades) only, not resting-order-book snapshots. True L1 would require polling Polymarket's CLOB REST going forward, and historical L2 is effectively unrecoverable for either venue. This spec captures **trades only**.
- **No changes to the existing `price_snapshots` table or the backtester.** The existing on-chain price-snapshot path (`polygon_chain.py`) stays intact.
- **No live trading integration.** `src/live/` is untouched.
- **No Kalshi activation in the pilot.** Kalshi is scaffolded as a config slot with `NotImplementedError`; full implementation is a follow-up once the user has credentials.
- **No cron/launchd installation.** A shell wrapper is provided; user wires it into their scheduler of choice later.

## Scope Decisions

| Decision | Value | Rationale |
|---|---|---|
| Data granularity | Trade tape (A) — per-fill rows | Achievable from on-chain data; L2 is not |
| Market universe | Mirror existing filter (a) — Yes/No binary, categories `geopolitical / political / culture` | Keeps scope tight; matches backtester universe |
| Kalshi in pilot | Scaffolded only (b) — config slot, no credentials yet | No account provisioned yet |
| Trade-row richness | Maximal — raw event JSON, order metadata, YES/NO distinction, notional | Captures everything needed for future analyses; avoids schema churn |
| Pilot size | Auto-pick N=5 most recently resolved markets in filter | No hand-picking required; varied categories |
| Dashboard placement | New tab in existing `src/dashboard/app.py` | Lowest friction; reuses sidebar filters |
| Scheduling | Shell wrapper only; user sets up cron externally | User preference |

## Architecture

### Data flow

```
Polymarket Gamma API (existing)       Polygon RPC (CTF Exchange)
            |                                    |
            v                                    v
        markets table              ------->  trades_runner.py
                                                 |
                                                 v
                                           trades table  (NEW)
                                                 |
                                                 v
                                    Streamlit "Trades" tab  (NEW)

Kalshi REST API (scaffolded, inactive) -->  trades_runner.py  -->  trades table
```

Each layer stays independently runnable. The dashboard and runner never cross-call. The only shared surface is the SQLite DB at `data/polymarket.db`.

### Package layout (additions only)

```
src/collector/trades/
    __init__.py
    polymarket.py      # on-chain trade extraction, reuses polygon_chain.py helpers
    kalshi.py          # scaffold: client stub + config-driven auth, raises NotImplementedError
    runner.py          # CLI entrypoint, orchestrates backfill + catchup
src/dashboard/
    trades_tab.py      # views rendered into the existing app's new tab
scripts/
    trades_catchup.sh  # `uv run python -m src.collector.trades.runner --mode catchup`
tests/
    test_trades_schema.py
    test_trades_polymarket.py
    test_trades_runner.py
```

Nothing inside `src/collector/polymarket_api.py`, `polygon_chain.py`, `price_history.py`, `runner.py`, or `src/backtester/` changes. A single new import in `src/dashboard/app.py` wires the new tab in.

## Storage Schema

New `Trade` model added to `src/storage/models.py`:

```python
class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_id: Mapped[str] = mapped_column(ForeignKey("markets.id"))
    venue: Mapped[str] = mapped_column(String)              # 'polymarket' | 'kalshi'
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    price: Mapped[float] = mapped_column(Float)             # 0..1
    size_shares: Mapped[float] = mapped_column(Float)
    usdc_notional: Mapped[float] = mapped_column(Float)
    side: Mapped[str] = mapped_column(String)               # 'buy_no'|'sell_no'|'buy_yes'|'sell_yes'
    is_yes_token: Mapped[bool] = mapped_column(Boolean)     # which outcome token traded

    # On-chain provenance (Polymarket); NULL for Kalshi
    tx_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    log_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    block_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    maker_address: Mapped[str | None] = mapped_column(String, nullable=True)
    taker_address: Mapped[str | None] = mapped_column(String, nullable=True)
    order_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    maker_asset_id: Mapped[str | None] = mapped_column(String, nullable=True)
    taker_asset_id: Mapped[str | None] = mapped_column(String, nullable=True)
    fee: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Kalshi-native fields (NULL for Polymarket)
    kalshi_trade_id: Mapped[str | None] = mapped_column(String, nullable=True)

    # Audit/replay
    raw_event_json: Mapped[str] = mapped_column(Text)

    market: Mapped["Market"] = relationship()

    __table_args__ = (
        UniqueConstraint("venue", "tx_hash", "log_index", name="uq_trade_onchain"),
        UniqueConstraint("venue", "kalshi_trade_id", name="uq_trade_kalshi"),
        Index("ix_trades_market_timestamp", "market_id", "timestamp"),
        Index("ix_trades_venue_timestamp", "venue", "timestamp"),
    )
```

**Idempotency:** unique constraints on `(venue, tx_hash, log_index)` and `(venue, kalshi_trade_id)` make re-runs safe. SQLite treats NULLs as distinct in unique constraints, so Kalshi rows (no `tx_hash`) don't collide via the on-chain constraint and vice versa.

**Schema creation:** per project convention, no migrations framework. `Base.metadata.create_all()` in `db.get_engine()` adds the new `trades` table to existing databases on next init without touching existing data.

## Polymarket Collector — `src/collector/trades/polymarket.py`

### Reuse

Imports from existing `src/collector/polygon_chain.py`:

- `ORDER_FILLED_ABI`
- `CTF_EXCHANGE_ADDRESS`
- `estimate_block_for_timestamp`
- `compute_price_from_event` (where applicable; see mapping below)

No copy-paste.

### Public interface

```python
def fetch_trades(
    market: Market,
    yes_token_id: str,
    no_token_id: str,
    from_block: int | None = None,
    to_block: int | None = None,
    w3=None,  # injected Web3 instance for testability
) -> Iterator[dict]:
    ...
```

Yields trade dicts (streaming, not a list). Lets the runner batch-write and respect memory on fat markets.

### Event → Trade mapping

For each `OrderFilled` log where `maker_asset_id` or `taker_asset_id` matches `yes_token_id` or `no_token_id`:

- `is_yes_token` = `(maker_asset_id == yes_token_id) or (taker_asset_id == yes_token_id)`
- `price` = USDC leg / outcome-token leg (via `compute_price_from_event`, already handles both directions)
- `size_shares` = whichever leg is the outcome token, divided by `10^6` (CTF token decimals)
- `usdc_notional` = `price * size_shares`
- `side`:
  - If `maker_asset_id == 0` (maker is offering USDC): maker is **buying** the outcome token, taker is **selling** it
  - If `taker_asset_id == 0`: taker is **buying**, maker is **selling**
  - Combined with `is_yes_token`, one of `buy_yes | sell_yes | buy_no | sell_no`
  - **Convention: store the taker side** (taker = aggressor / market-order initiator)
- Provenance: `tx_hash`, `log_index`, `block_number`, `maker_address`, `taker_address`, `order_hash` lifted directly from the event
- `fee` = `args.fee / 10^6` (USDC decimals)
- `raw_event_json` = `json.dumps(dict(event.args))` for audit/replay

### Block windowing

- **Backfill mode:** `from_block = estimate_block_for_timestamp(market.created_at)`, `to_block = estimate_block_for_timestamp(market.resolved_at)` (or latest block if unresolved — won't occur in pilot since we only pick resolved markets).
- **Catchup mode:** `from_block = max(block_number) + 1` across existing trades for this market. `to_block = latest`. Per-market checkpoint; partial runs don't lose progress.

### Rate limits and resilience

- 10k-block chunks (matches existing `polygon_chain.py`).
- `time.sleep(0.1)` between chunks.
- Per-chunk `Exception` caught and retried with exponential backoff (3 retries: 1s, 2s, 4s). After final failure, log `warning` and continue to next chunk.
- Missing `web3` import → return empty iterator (matches existing behavior).
- RPC not connected → return empty iterator + log `warning`.

### Token-ID resolution

`Market` currently stores `no_token_id` only. We also need `yes_token_id` for YES-leg classification and filtering.

**Resolution strategy:** a small helper in `src/collector/trades/polymarket.py` — `fetch_yes_token_id(market_id: str) -> str | None` — calls Polymarket Gamma `/markets/{id}` and returns `clobTokenIds[yes_idx]`, mirroring the YES/NO index logic already in `parse_market` from `polymarket_api.py`. The runner calls this once per market, caches per-run in memory. Returns `None` if the market has malformed `clobTokenIds`; runner logs a warning and skips the market.

No new column added to `Market` — avoids migration surface, and token IDs are effectively immutable per market so a lookup-cache is fine. No change to `polymarket_api.parse_market`.

## Runner — `src/collector/trades/runner.py`

### CLI

```bash
# Backfill: N most recently resolved markets in the existing filter
uv run python -m src.collector.trades.runner --mode backfill --pilot 5

# Backfill: explicit market-ID list
uv run python -m src.collector.trades.runner --mode backfill --market-ids 0xabc,0xdef

# Catchup: incremental pull for markets already in `trades` + any newly-resolved markets
uv run python -m src.collector.trades.runner --mode catchup

# Venue selection (default: polymarket)
uv run python -m src.collector.trades.runner --mode catchup --venues polymarket,kalshi
```

### Mode behavior

- **`backfill`** — market selection via `--pilot N` (top-N most-recently-resolved markets passing the existing `outcome_set == {yes,no}` + category filter) or `--market-ids` (explicit comma-separated list). For each market, pulls the full block window `created_at → resolved_at`. No skip heuristic — idempotency is enforced by the unique constraint, so re-running is safe; the cost is the wasted RPC calls, not duplicate rows. (If this becomes painful at scale we can add a "last-seen checkpoint" later.)
- **`catchup`** — two disjoint sub-populations, each with its own `from_block` rule:
  - Markets **already present** in `trades`: `from_block = max(block_number) + 1`, `to_block = latest`.
  - Resolved markets in `markets` with **no rows yet** in `trades`: full window, same as backfill (`from_block = estimate_block_for_timestamp(created_at)`).
  - Skips any market whose last stored trade is past `resolved_at` — it's already fully captured.

Exactly one of `--pilot` or `--market-ids` must be set when `--mode backfill`. `--mode catchup` takes neither.

### Batching and logging

- Write to DB every 100 trades; commit every 500. Tighter than the existing collector (which commits every 10 markets) because a single market can have tens of thousands of fills.
- Structured logging (`logging.INFO`): one line per market start/finish with `(market_id, trades_written, blocks_scanned, duration_s)`.
- Per-market errors don't halt the run; market is skipped with a logged warning, runner continues.

### Exit codes

- `0` — clean run or partial-with-errors-logged.
- `1` — configuration error: mutually-exclusive flag violation (both `--pilot` and `--market-ids` set, or neither in backfill mode); unknown market ID passed to `--market-ids` that isn't in the `markets` table; `--venues kalshi` without Kalshi credentials.

Note: `POLYGON_RPC_URL` is **not** required — the collector defaults to `https://polygon-rpc.com` if unset, matching the existing `polygon_chain.py`. RPC-not-connected is a runtime condition (empty iterator + logged warning), not a config error.

## Kalshi Scaffold — `src/collector/trades/kalshi.py`

Non-functional in pilot. Provides the shape Kalshi will slot into:

```python
@dataclass
class KalshiConfig:
    api_key_id: str | None = None
    api_key_secret: str | None = None
    api_base: str = "https://api.elections.kalshi.com/trade-api/v2"

    @classmethod
    def from_env(cls) -> "KalshiConfig":
        return cls(
            api_key_id=os.getenv("KALSHI_API_KEY_ID"),
            api_key_secret=os.getenv("KALSHI_API_KEY_SECRET"),
            api_base=os.getenv("KALSHI_API_BASE", cls.api_base),
        )


def fetch_trades(market, config: KalshiConfig):
    if not config.api_key_id or not config.api_key_secret:
        raise NotImplementedError(
            "Kalshi collector not configured. Set KALSHI_API_KEY_ID and "
            "KALSHI_API_KEY_SECRET in .env to activate."
        )
    raise NotImplementedError("Kalshi trade fetching not yet implemented.")
```

`.env.example` gets three new entries documented:

```
# KALSHI_API_KEY_ID=
# KALSHI_API_KEY_SECRET=
# KALSHI_API_BASE=https://api.elections.kalshi.com/trade-api/v2
```

Runner's `--venues` flag defaults to `polymarket` only; passing `kalshi` before credentials are set hits the `NotImplementedError` with a clear message rather than a stack trace.

### Deferred Kalshi questions (noted, not solved here)

- **Kalshi market-universe model:** Kalshi uses ticker-based events/markets. When Kalshi goes live we'll need to decide whether to add a `venue` column to the `markets` table or namespace Kalshi IDs (e.g. `kalshi:TICKER`). Pilot doesn't require the decision.
- **Kalshi category mapping:** the existing `categories.py` classifier is regex/tag-based over Polymarket tag conventions; Kalshi has its own event taxonomy. Classifier extension deferred.

## Shell Wrapper — `scripts/trades_catchup.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
exec uv run python -m src.collector.trades.runner --mode catchup "$@"
```

Made executable. Committed to the repo. User sets up their own cron/launchd later. Idempotent by construction via the unique constraints.

## Dashboard Tab — `src/dashboard/trades_tab.py`

New tab wired into the existing tab structure in `src/dashboard/app.py`. Module exposes `render(session, filters)`; `app.py` adds one `st.tabs(...)` entry and one import. Reuses the existing sidebar category multiselect and date-range picker via `_apply_date_filter`.

### Views

**Top:** market picker dropdown, listing markets that appear in `trades` (ordered by most recent trade). Defaults to first.

**Per-market (once selected):**

1. **Price over time** — Altair scatter: x=timestamp, y=price, color=side, size=size_shares. Overlay a line for daily VWAP.
2. **Volume histogram** — bars of USDC notional per day.
3. **Trade ladder** — last 50 trades, table with `(time, side, price, shares, notional, taker_address[:8])`. Side color-coded.
4. **Cumulative volume vs price** — step line of cumulative notional with price scatter on secondary axis.

**Cross-market (below):**

5. **Total daily volume across pilot markets** — line chart.
6. **Top-10 markets by notional** — sortable bar chart.

All queries hit `trades` (joined with `markets` for labels). No network calls. All queries filter by `venue` so Kalshi data stays isolated when activated.

## Testing

Three new test files under `tests/`, using the existing in-memory SQLite fixture from `conftest.py`. No live network.

### `test_trades_schema.py`

- `Base.metadata.create_all` creates the `trades` table.
- Unique constraint on `(venue, tx_hash, log_index)` rejects duplicates on insert.
- Multiple NULL-`tx_hash` rows (simulating Kalshi) coexist without collision.

### `test_trades_polymarket.py`

Pure unit tests on the event→trade mapper. Fixture builds fake `OrderFilled` `args` dicts covering four cases:

- `maker=YES, taker=USDC`
- `maker=USDC, taker=YES`
- `maker=NO, taker=USDC`
- `maker=USDC, taker=NO`

Each case asserts correct `side`, `price`, `size_shares`, `usdc_notional`, `is_yes_token`. No `web3` mocking — the mapper is a pure function over event dicts.

### `test_trades_runner.py`

- Monkeypatch `polymarket.fetch_trades` to yield a fixed list of trade dicts.
- Seed an in-memory DB with a `Market` row.
- Run `--mode catchup` twice; assert trade count is stable on the second run (idempotent).
- Assert `from_block` checkpoint advances: second run's `from_block` equals `max(block_number)+1` from first run's rows.

## Pilot Execution Plan

Phased landing once implementation plan is written:

1. **Schema PR.** Add `Trade` model + `test_trades_schema.py`. No behavior change. Lands the table.
2. **Mapper PR.** Add `src/collector/trades/polymarket.py` with the pure event-mapper + `test_trades_polymarket.py`. No runner, no I/O.
3. **Runner PR.** Add `fetch_trades` iterator + `src/collector/trades/runner.py` + `test_trades_runner.py`. Add `scripts/trades_catchup.sh`. Run `--mode backfill --pilot 5` against `data/polymarket.db`.
4. **Sanity checks** on pilot data before proceeding:
   - Trade counts per market against Polymarket UI spot-checks where possible.
   - Re-run yields zero new rows (idempotency verified).
   - Per-market VWAP correlates strongly with existing `price_snapshots` for that market.
5. **Dashboard PR.** Add `src/dashboard/trades_tab.py` + wire into `app.py`. Verify charts render on pilot data.
6. **Kalshi scaffold PR.** Add `src/collector/trades/kalshi.py` + update `.env.example`. Kalshi remains inactive.

## Known Risks

- **Public RPC rate limits.** `polygon-rpc.com` (the default) rate-limits hard. Fat markets (election-scale, 10k+ fills across weeks of blocks) will likely hit throttling during backfill. Mitigation: the pilot will reveal whether a private RPC (Alchemy / QuickNode) is required; swap in via `POLYGON_RPC_URL` env var with no code change. Flagged in the phase-3 sanity checks.
- **Gamma API `clobTokenIds` availability.** If a market's Gamma record lacks `clobTokenIds[0]` (YES) or `clobTokenIds[1]` (NO), the collector skips the market with a logged warning rather than crashing. Expected to be rare.
- **Side-convention risk.** The choice to store **taker side** is a convention. If it turns out the user wants maker-perspective or both, schema already captures enough raw fields to derive either — no reshape needed.
