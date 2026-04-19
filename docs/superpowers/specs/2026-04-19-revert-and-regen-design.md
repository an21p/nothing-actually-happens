# Revert to b8c43fd, narrow scope, regen data

**Date:** 2026-04-19
**Status:** Approved — ready for implementation plan

## Motivation

The trade-tape collector work (commits after `b8c43fd`, plus uncommitted modifications
to `src/collector/trades/polymarket.py`) tried to pull historical trade data directly
from Polygon chain via CTF Exchange `OrderFilled` events. The approach proved
unreliable (slow RPC pagination, brittle event parsing) and we are abandoning it. The
"nothing ever happens" backtester only needs price-snapshot history, which the existing
Gamma CLOB `prices-history` endpoint already provides.

This spec covers reverting the trade-tape work, narrowing market coverage to
politics / geopolitics only, enforcing a 2020-01-01 floor, dropping the unrealistic
`best_price` strategy (which had hindsight look-ahead bias), and regenerating the
SQLite DB so future backtests run against a clean dataset.

## Scope

In scope:

- Preserve the abandoned trade-tape work on a dedicated `polygon` branch
- Force `main` back to `b8c43fd` (`streatch`)
- Remove `best_price` from the strategies registry + its tests + dashboard description
- Narrow default collector categories to `political,geopolitical` (drop `culture`)
- Enforce `created_at >= 2020-01-01` in the collector runner
- Document the abandoned Polygon on-chain experiment in `CLAUDE.md`
- Regenerate `data/polymarket.db` from scratch
- Re-run the full backtester sweep

Out of scope:

- Further changes to collector, backtester, or dashboard logic beyond what is listed above
- Retrying the on-chain trade-tape collection in any form
- Migration tooling for the existing DB (we delete and rebuild)

## Architecture Impact

No structural change. The four-package layout (`collector` / `backtester` / `storage` /
`dashboard`) is restored to what it was at `b8c43fd`. The `trades/` module, `Trade`
model, and `positions` / `trades` tables go away with the revert. After regen, the
live DB will contain only `markets`, `price_snapshots`, and `backtest_results`.

## Implementation Steps

### 1. Preserve current work on `polygon` branch

From the current `main` working tree:

```bash
git checkout -b polygon
git add -A
git commit -m "wip: polygon trade-tape attempt (abandoned)"
git push -u origin polygon
```

Carries the 16 trade-collector commits plus the uncommitted changes in
`src/collector/trades/polymarket.py` and `tests/test_trades_polymarket.py`, and the
untracked `scripts/trades_backfill.sh`. The `.claude/worktrees/` directory is
ignored (not under git).

### 2. Force `main` back to `b8c43fd`

```bash
git checkout main
git reset --hard b8c43fd
git push --force origin main
```

Destructive but acceptable: single-author repo, linear history, abandoned work is
preserved on `polygon`.

### 3. Remove `best_price` strategy

On `main` (post-revert):

- **`src/backtester/strategies.py`**: delete the `best_price` function (lines 35-39)
  and the `"best_price"` entry in the `STRATEGIES` dict (line 51).
- **`tests/test_strategies.py`**: remove the `best_price` import and the two
  `test_best_price_*` tests (lines 62-68).
- **`src/dashboard/app.py:20`**: remove the `"best_price"` key from the
  strategy-description dict.

The label variants `best_price__earliest_created` and `best_price__earliest_deadline`
disappear automatically because the engine composes them from the cross-product of
`STRATEGIES × SELECTION_MODES` — with `best_price` gone, those labels are never
produced.

### 4. Narrow collector scope

- **Categories**: change the `--categories` default in `src/collector/runner.py:116`
  from `"geopolitical,political,culture"` to `"political,geopolitical"`.
- **Date floor**: in `collect()` in `src/collector/runner.py`, after
  `fetch_resolved_markets` returns, filter markets where
  `market_data["created_at"] < datetime(2020, 1, 1, tzinfo=timezone.utc)`. Since
  pagination is newest-first via `end_date_max`, once we begin seeing pre-2020
  markets the iteration naturally runs out; no early-abort optimisation needed in
  this spec.

### 5. Document abandoned Polygon on-chain experiment

Add a short paragraph to `CLAUDE.md` immediately after the existing
`polygon_chain.py` bullet in the "src/collector/" section:

> **Note — Polygon on-chain trade history was attempted and abandoned.** An earlier
> branch (`polygon`) tried to pull per-market trade fills by streaming `OrderFilled`
> events from the CTF Exchange contract on Polygon, writing them to a `trades`
> table. The approach was too slow and brittle to be useful. Gamma's
> `clob.polymarket.com/prices-history` remains the authoritative source for the
> price snapshots that `threshold` and `snapshot` strategies need. `polygon_chain.py`
> is retained only for the optional `--enrich-onchain` price interpolation; no new
> trade-tape work should be attempted on top of it without revisiting the failure
> mode on the `polygon` branch first.

### 6. Regenerate `data/polymarket.db`

```bash
rm data/polymarket.db
uv run python -m src.collector.runner
```

Runs with the narrowed defaults: politics + geopolitical, ≥2020. This is a multi-hour
operation (hourly price snapshots for every resolved Yes/No market in-scope).

### 7. Rerun backtester

```bash
uv run python -m src.backtester.engine
```

Writes a fresh sweep of run_ids to `backtest_results`. The dashboard picks up the
latest run_id automatically.

## Testing

- `uv run pytest` after step 3 — should pass with the `best_price` tests removed
  (expect test count to drop by 2). No other tests should be affected.
- Smoke-run the collector with `uv run python -m src.collector.runner --limit 50`
  before the full regen to catch any regression in the date-floor / category
  narrowing logic.
- After the full backtester run, query the dashboard's Metrics tab and confirm no
  `best_price*` strategy labels appear in the latest `run_id`.

## Rollback

The abandoned work lives on `origin/polygon`. If we need anything from it:

```bash
git checkout polygon -- <path>
```

If the revert itself needs undoing, `git reflog` on `main` will show the
pre-reset SHA for a recovery point; the `polygon` branch also contains the
same tree at its tip.
