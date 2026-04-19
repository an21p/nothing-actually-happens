# Collector Expansion — Design

**Date:** 2026-04-19
**Status:** Proposed
**Author:** Claude (brainstorming session with user)

## Background

The current Polymarket collector (`src/collector/`) filters out a large portion of available data:

- **Category filter:** Only markets classified as `geopolitical`, `political`, or `culture` are kept. Anything else falls into `"other"` and is discarded at ingest time.
- **negRisk filter:** Multi-outcome events (e.g., "Who will win the presidency?" with Trump / Harris / etc. as sub-markets) are rejected wholesale in `parse_market`, because the "nothing ever happens" thesis assumes independent Yes/No binaries.
- **Classification is keyword-first:** The API's rich tag set (`events[].tags`) is ignored in favour of a small `TAG_MAP` on `raw.category` plus four regex lines per category. Many real geopolitical/political markets from the 2020–2023 era miss the keyword list entirely.
- **Price history is sparse:** Of 8,405 market rows currently in `data/polymarket.db`, only **878 have any price snapshots** — the runner ingests markets faster than it fetches prices, and there is no catch-up pass.

The current `markets` table goes back to 2020-10-02, so the lower time bound is already satisfied. The missing data is lateral (more markets, more classification coverage) and deep (price history on the markets we already have).

## Goal

Expand the collector to ingest as much Polymarket data as possible back to 2020, while keeping the "nothing ever happens" thesis (backtester + dashboard) strictly on simple binary markets only. Specifically:

1. Drop the category filter at the collector level — collect every resolved Yes/No market the Gamma API surfaces.
2. Include `negRisk` sub-markets as individual binary rows, tagged so the backtester can exclude them by default.
3. Classify via API tags first, keyword fallback second; rename `"other"` → `"misc"`.
4. Backfill price history for all markets with zero snapshots, via a bounded-concurrency fetcher. Exposed as both a per-run budget in the main `runner` and a dedicated bulk command.
5. Gate the backtester and dashboard so they default to `is_neg_risk == False` — existing analyses behave identically.

## Non-goals

- No change to price fidelity (stay on `fidelity=60`, hourly).
- No change to strategies, dashboards, or on-chain enrichment logic.
- No new dashboard UI for exploring negRisk markets. If wanted later, add as a separate tab.
- No change to the `price_snapshots` schema. The existing `(market_id, timestamp)` dedup remains authoritative.
- Not re-fetching price history for markets that already have at least one snapshot. A `--force` flag on the bulk backfill exists for the rare case this is needed.

## Schema Changes

Two new columns on `markets`:

```python
is_neg_risk: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
event_id: Mapped[str | None] = mapped_column(String, nullable=True)
```

- `is_neg_risk`: `True` if the source market was part of a Polymarket multi-outcome event (`raw.negRisk == True`).
- `event_id`: The parent event identifier. The exact Gamma API field(s) to extract this from are not yet verified against a live response — plausible candidates are `raw["events"][0]["id"]` (if events are nested in the `/markets` response), `raw["negRiskMarketId"]`, or `raw["eventSlug"]`. The first implementation step is to hit the API with `curl` or equivalent, inspect one negRisk and one non-negRisk market, and pick the right source. `None` is an acceptable value when no identifier is available.

The Yes/No outcome invariant (`outcome_set == {"yes", "no"}`) is preserved — each negRisk sub-market is individually a Yes/No binary with its own `conditionId`, `no_token_id`, and price history. The load-bearing filter becomes "must be Yes/No", not "must not be negRisk".

### Migration

One-shot script: `src/storage/reset_markets.py`.

```python
# pseudocode
from src.storage.db import get_engine
from src.storage.models import Base, Market, PriceSnapshot

def reset():
    engine = get_engine()
    PriceSnapshot.__table__.drop(engine, checkfirst=True)
    Market.__table__.drop(engine, checkfirst=True)
    Base.metadata.create_all(engine)
```

- Drops only `price_snapshots` and `markets`.
- Leaves `backtest_results` and `positions` intact (Polymarket `conditionId`s are deterministic, so old results will point at valid markets after re-collection).
- Idempotent — safe to re-run.

## Collector Changes

### `src/collector/polymarket_api.py`

- `_parse_market_common`: remove the `if raw.get("negRisk"): return None` early-out. Instead, extract `is_neg_risk` and `event_id` and include them in the returned dict. The exact `event_id` extraction logic depends on inspecting a live API response (see Schema Changes above); below is an illustrative shape, not the final implementation:

```python
is_neg_risk = bool(raw.get("negRisk"))
# placeholder — replace with whichever field(s) the /markets endpoint actually returns
event_id = None
events = raw.get("events") or []
if events:
    event_id = events[0].get("id")
if is_neg_risk and not event_id:
    event_id = raw.get("negRiskMarketId")
```

- The Yes/No invariant (`outcome_set == {"yes", "no"}`), 2-outcome requirement, and `>0.9` resolution detection stay exactly as they are.
- `parse_market` and `parse_open_market` propagate `is_neg_risk` and `event_id` into their output dicts.

### `src/collector/categories.py`

New signature: `classify_market(question: str, api_category: str | None, api_tags: list[dict] | None) -> str`.

Classification order:
1. Walk the flattened `api_tags` label list through `TAG_MAP`, longest-match-wins. First hit returns.
2. Fall back to `api_category` through `TAG_MAP` (current behaviour).
3. Fall back to keyword regex patterns on `question`.
4. Final fallback: return `"misc"` (renamed from `"other"`).

Keyword patterns for `geopolitical` and `political` get modest expansion (Biden-era, COVID-era politics, broader country/region terms). `culture` keywords unchanged.

Callers extract tags from whatever field the live API actually surfaces (plausible: `raw["tags"]`, `raw["events"][0]["tags"]`). Same first-implementation-step as for `event_id` — confirm against a real response before wiring the extraction. Where tags are absent, pass `api_tags=[]`.

### `src/collector/runner.py`

- `collect(categories=None, …)`: when `None`, do not filter by category at all. Markets of every category (including `"misc"`) are ingested.
- CLI default changes from `--categories geopolitical,political,culture` to `--categories ""` (empty string → `None` → no filter). Passing `--categories political,geopolitical` still narrows post-classification for users who want it.
- `end_date_max` continuation logic, upsert, `price_snapshots` dedup, and on-chain enrichment behaviour unchanged.

### Per-run price-history backfill

After the main ingest loop in `collect()`, a new pass:

```python
if backfill_limit != 0:
    missing = session.query(Market.id, Market.no_token_id).filter(
        ~Market.id.in_(session.query(PriceSnapshot.market_id).distinct())
    ).limit(backfill_limit or None).all()
    if missing:
        results = asyncio.run(fetch_price_histories_concurrent(
            [(no_token_id, market_id) for market_id, no_token_id in missing],
            max_concurrency=5,
        ))
        # store via existing store_price_snapshots, commit every 50
```

New CLI flag on `runner`: `--backfill-limit N`, default `100`. `--backfill-limit 0` skips the backfill pass entirely.

## Price History — Async Fetcher

New functions in `src/collector/price_history.py`, alongside the existing sync API:

```python
async def fetch_price_history_async(
    client: httpx.AsyncClient,
    token_id: str,
    market_id: str,
) -> list[dict]: ...

async def fetch_price_histories_concurrent(
    token_market_pairs: list[tuple[str, str]],
    max_concurrency: int = 5,
) -> dict[str, list[dict]]: ...
```

- Single shared `httpx.AsyncClient(timeout=30)`.
- `asyncio.Semaphore(max_concurrency)` to cap concurrent requests.
- Per-request exponential backoff on `429` and `5xx` (1s → 2s → 4s, give up after 3 attempts, return `[]` for that market).
- Progress printed every 100 markets.
- The existing sync `fetch_price_history` and `fetch_price_histories_batch` stay as-is; nothing else in the codebase needs to change.

## Bulk Backfill Command

New module: `src/collector/backfill_runner.py`.

```bash
uv run python -m src.collector.backfill_runner                  # all missing
uv run python -m src.collector.backfill_runner --limit 1000     # cap
uv run python -m src.collector.backfill_runner --concurrency 10
uv run python -m src.collector.backfill_runner --force          # re-fetch markets that already have snapshots
```

Purely a price-history catch-up. No market ingestion. Internally reuses `fetch_price_histories_concurrent`.

Scope of "missing": markets with zero snapshot rows. `--force` re-fetches everything (useful if a fidelity change or API fix warrants it later).

## Backtester / Dashboard Gating

New module: `src/storage/queries.py`.

```python
from sqlalchemy.orm import Session
from sqlalchemy.orm.query import Query
from src.storage.models import Market

def thesis_markets(session: Session) -> Query:
    """Markets eligible for the 'nothing ever happens' thesis.

    Excludes negRisk sub-markets (mutually-exclusive by construction, which
    violates the thesis's independence assumption).
    """
    return session.query(Market).filter(Market.is_neg_risk == False)
```

Call-site updates:

- `src/backtester/engine.py::run_backtest` — replace the `session.query(Market).filter(Market.resolution.isnot(None))` chain with `thesis_markets(session).filter(Market.resolution.isnot(None))`. Category and date filters compose on top as today.
- `src/dashboard/app.py` — every `Market` query goes through `thesis_markets(session)`. Sidebar category multiselect and date range continue to compose.

No dashboard toggle for negRisk in v1. Future negRisk analysis, if wanted, can be added as a separate tab with its own queries.

## Testing

All tests use in-memory SQLite via the `engine`/`session` fixtures in `tests/conftest.py`. No network.

New tests:

- `tests/test_polymarket_api.py`
  - `parse_market` on a negRisk fixture → returns dict with `is_neg_risk=True`, `event_id=<event id>`.
  - `parse_market` still rejects non-Yes/No markets (e.g., 3-outcome, sports team names).
  - `parse_market` on a normal market → `is_neg_risk=False`, `event_id` set from `events[0].id`.
- `tests/test_categories.py`
  - `classify_market` with `api_tags=[{"label": "Elections"}]` and a non-political question → `"political"`.
  - Falls back to `api_category` when tags are empty.
  - Falls back to keywords when both tags and API category are empty.
  - Returns `"misc"` (not `"other"`) for unclassifiable input.
- `tests/test_price_history_async.py`
  - `fetch_price_histories_concurrent` honours the concurrency bound (asserted via a counter in a mock transport).
  - A 429 response triggers backoff, then succeeds; final result is the success payload.
  - Persistent 5xx → empty list for that market, other markets unaffected.
- `tests/test_queries.py`
  - `thesis_markets` excludes `is_neg_risk=True` rows; includes `False` rows; unrelated filters compose correctly.

Existing test updates:

- `tests/test_engine.py` — add a fixture with one negRisk market + one normal market, confirm only the normal market appears in `BacktestResult` rows.
- `tests/test_collector.py` (if present) — update any fixture that asserts the old category filter behavior.

## Manual Verification Checklist

Before declaring the work done:

0. Confirm the exact Gamma API fields used for `event_id` and `api_tags` against one negRisk and one non-negRisk live market response, then update the collector code to match.
1. Run `uv run python -m src.storage.reset_markets` on a copy of `data/polymarket.db` (not the live one).
2. Run `uv run python -m src.collector.runner --limit 200` — confirm (a) at least some rows have `is_neg_risk=True` and an `event_id`, (b) at least one row has `category="misc"`.
3. Run `uv run python -m src.collector.backfill_runner --limit 100` — confirm price snapshots fill in for previously-empty markets.
4. Open the dashboard (`uv run streamlit run src/dashboard/app.py`) — confirm (a) the category counts roughly match the pre-change thesis view after filtering `is_neg_risk=False`, (b) no negRisk markets surface in any panel.
5. Run a full backtest: `uv run python -m src.backtester.engine --strategy threshold --param 0.85` — confirm `run_id` row count matches the number of non-negRisk resolved markets with a qualifying snapshot.
6. `uv run pytest` — full test suite passes.

## Open Questions / Future Work

- **negRisk-aware analysis.** Once we have `event_id`, the natural follow-up is a "per-event" backtest that picks one sub-market per event (e.g., the shortest-odds No) and measures PnL across events. Out of scope here.
- **Price fidelity.** Hourly is fine for strategies in place today. If a future strategy needs minute-level data, the bulk backfill can be re-run with `--force` once the fetcher supports `fidelity < 60`.
- **Rate-limit tuning.** `max_concurrency=5` is a guess. If the bulk backfill runs clean at 5, try 10 on the next pass.
