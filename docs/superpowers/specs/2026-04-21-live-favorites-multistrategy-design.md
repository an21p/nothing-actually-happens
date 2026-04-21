# Live Paper-Trading: Multi-Strategy From Favorites

**Status:** Draft — awaiting user review
**Date:** 2026-04-21
**Scope:** `src/live/`, `src/dashboard/app.py`, new `live_config.yaml`

## Motivation

The live paper-trading pipeline currently runs a single hard-coded strategy (`snapshot_24__earliest_deadline`) and exposes only a flat "Live Positions" view that aggregates all positions. Backtests have surfaced two favourite strategies with distinct edges: `snapshot_24__earliest_created` (highest win rate) and `threshold_0.3__earliest_created` (highest ROI). Both should run live, each with its own independent bankroll, and the dashboard should show (a) which open markets currently qualify for entry and (b) per-strategy performance.

The system must be driven by the `favorite_strategies` DB table (the same table the Strategy Comparison tab writes to via the star-toggle button), so favouriting in the UI is the single control surface.

## Non-goals

- Real CLOB order execution (`LiveExecutor` stays a stub).
- Early exits or stop-losses — positions hold to resolution.
- Manual bankroll top-up from the UI; bankroll changes require editing YAML and restart.
- Political / culture / other categories — live scope is geopolitical only.
- Schema migrations — no new DB tables.

## Architecture

Data flow:

```
Gamma API (open markets)
     │
     ▼
src/live/open_markets.py  ──►  markets table (upsert open markets)
                               │
src/live/quotes.py  ───────────┤  (mid-price per NO-token from CLOB)
                               ▼
           src/live/signals.py         — multi-strategy
                (reads favorite_strategies + LiveConfig)
                               │
                ┌──────────────┼──────────────┐
                ▼              ▼              ▼
        EntrySignal       EntrySignal     EntrySignal
     (snapshot_24)     (threshold_0.3)     (future fav)
                               │
                               ▼
           src/live/bankroll.py  ◄──  positions (history)
                (computed per-strategy balance, pure fn)
                               │
                               ▼   (gate each signal by available bankroll)
           src/live/executor.py  (PaperExecutor, unchanged)
                               │
                               ▼
                         positions table
                               │
                               ▼
                 src/dashboard/app.py
              ├─ Candidates (new view)
              └─ Live Positions (extended w/ per-strategy tabs)
```

**New modules:**
- `src/live/favorites.py` — parses `FavoriteStrategy.strategy` labels into typed `Favorite` records and merges them with per-strategy `LiveConfig` settings.
- `src/live/bankroll.py` — pure function `compute_bankroll(session, strategy, starting) -> BankrollState` over position history.
- New dashboard **Candidates** view.

**Modified modules:**
- `src/live/signals.py` — generalized from single hard-coded strategy to iterating over DB favorites; splits into `detect_snapshot_entries` and `detect_threshold_entries`.
- `src/live/config.py` — YAML-backed `LiveConfig` with per-strategy settings block.
- `src/live/runner.py` — loops over favorites; bankroll-gates each signal before open.
- `src/dashboard/app.py` — Live Positions gains per-strategy tabs; new Candidates view.

**Schema:** no changes. `markets`, `positions`, and `favorite_strategies` already cover everything.

## Favorite label grammar

Supported labels (anything else is rejected at load time with a logged warning — not a crash):

```
snapshot_<N>__earliest_created      → time_snapshot(offset_hours=N)
threshold_<p>__earliest_created     → price_threshold(threshold=p)
```

Unsupported in live scope: `limit_*` (distinct crossing semantics; live policy is "fire on observation"), `at_creation` (no practical edge), `earliest_deadline` (switched to `earliest_created` to match backtest findings).

## Core modules

### `src/live/favorites.py`

```python
@dataclass(frozen=True)
class Favorite:
    label: str                  # "threshold_0.3__earliest_created"
    strategy_name: str          # "threshold" | "snapshot"
    params: dict                # {"threshold": 0.3} | {"offset_hours": 24}
    selection_mode: str         # "earliest_created"
    starting_bankroll: float    # from LiveConfig
    shares_per_trade: float     # from LiveConfig

def parse_label(label: str) -> tuple[str, dict, str]: ...
def load_favorites(session, config: LiveConfig) -> list[Favorite]: ...
```

`load_favorites` reads every row from `favorite_strategies`, parses the label, and joins with `config.strategies[label]`. A favorite without a matching config entry is skipped with a warning (prevents accidentally trading with an undefined bankroll).

### `src/live/bankroll.py`

Pure function; no mutable state, no new table.

```python
@dataclass(frozen=True)
class BankrollState:
    strategy: str
    starting: float
    locked: float            # sum(size_shares * entry_price) for open positions
    realized_pnl: float      # sum(realized_pnl) for closed positions
    available: float         # starting - locked + realized_pnl
    open_positions: int
    closed_positions: int

def compute_bankroll(session, strategy: str, starting: float) -> BankrollState: ...
```

**Accounting model** (matches "bankroll refills on win" semantics):

- At entry: `available -= shares * entry_price` (locked in position)
- At close, resolved No (win): `+shares * 1.0` returns → net `+(1 - entry_price) * shares` vs. entry cost
- At close, resolved Yes (loss): `+$0` returns → net `-(entry_price * shares)` vs. entry cost

Both cases are captured by `Position.realized_pnl`, so `available = starting - locked + sum(realized_pnl)` is exactly cash-on-hand after compounding.

### `src/live/signals.py`

Split into two strategy-specific detectors with a common `EntrySignal` output.

```python
def detect_snapshot_entries(
    session, fav: Favorite, *, now, tolerance_hours, quote_fn
) -> list[EntrySignal]:
    # Age window = fav.params["offset_hours"] ± tolerance_hours
    # Filter: market.category == "geopolitical", resolution is None
    # Filter: no Position where (market_id=X AND strategy=fav.label)
    # Filter: no open Position with same template_key AND same strategy
    # Dedup via _select_markets(candidates, fav.selection_mode)
    # Quote each survivor → EntrySignal(market, entry_price=quote, entry_timestamp=now)

def detect_threshold_entries(
    session, fav: Favorite, *, now, quote_fn
) -> list[EntrySignal]:
    # No age window — any unresolved geopolitical market is a candidate
    # Quote each → only those with quote <= fav.params["threshold"] fire
    # Filter: no Position where (market_id=X AND strategy=fav.label)
    # Filter: no open Position with same template_key AND same strategy
    # Dedup via _select_markets(survivors, fav.selection_mode)
```

**Correctness note — per-strategy dedup:** the existing dedup in the old `signals.py` uses `traded_market_ids` across all positions and all strategies, which would block the second strategy from ever entering a market the first one already took. Both per-market-per-strategy filter and the template-dupe block are scoped to `Position.strategy == fav.label` only.

**`enumerate_candidates`** — used by the dashboard, not the runner:

```python
@dataclass(frozen=True)
class Candidate:
    favorite: Favorite
    market: Market
    state: str            # "ready" | "watching" | "waiting" | "expired" | "entered"
    quote: float | None
    target: float | None  # threshold price (threshold strategy) or None
    eta_hours: float | None
    age_hours: float
    blocked_by_bankroll: bool

def enumerate_candidates(
    session, favs: list[Favorite], *, now, quote_fn, bankrolls: dict[str, BankrollState]
) -> list[Candidate]: ...
```

State classification:
- **entered** — `Position` already exists for `(market.id, fav.label)`
- **ready** — would fire on next tick (snapshot window active OR threshold quote ≤ target)
- **watching** — threshold strategy, quote > target
- **waiting** — snapshot strategy, market too young for window (age < low)
- **expired** — snapshot strategy, market too old for window (age > high)

`blocked_by_bankroll` is `True` when state is `ready` but `shares_per_trade * quote > bankroll.available`.

### `src/live/config.py`

Replace env-var-only config with a YAML file for structured settings + env for secrets. New file: `live_config.yaml` at repo root (gitignored; `live_config.example.yaml` checked in).

```yaml
# live_config.yaml
categories: ["geopolitical"]
tolerance_hours: 12
executor: "paper"

strategies:
  snapshot_24__earliest_created:
    starting_bankroll: 1000.0
    shares_per_trade: 10.0
  threshold_0.3__earliest_created:
    starting_bankroll: 1000.0
    shares_per_trade: 10.0
```

```python
@dataclass(frozen=True)
class StrategyConfig:
    label: str
    starting_bankroll: float
    shares_per_trade: float

@dataclass(frozen=True)
class LiveConfig:
    categories: list[str]
    tolerance_hours: int
    executor: str
    strategies: dict[str, StrategyConfig]  # keyed by label
    telegram_bot_token: str | None   # from env TELEGRAM_BOT_TOKEN
    telegram_chat_id: str | None     # from env TELEGRAM_CHAT_ID

def load_config(path: Path = Path("live_config.yaml")) -> LiveConfig: ...
```

Secrets (`telegram_bot_token`, `telegram_chat_id`) stay in env; structural settings move to YAML.

Removed fields from the old `LiveConfig`:
- `sizing_rule`, `sizing_notional`, `sizing_shares`, `bankroll_start` — replaced by per-strategy `StrategyConfig`. Sizing rule is always `fixed_shares`.
- `max_open_positions` — per-strategy bankroll is the natural cap.
- `max_age_hours` — was single-strategy specific; each snapshot favorite encodes its own offset in the label.

**Dependency:** `pyyaml>=6.0` must be added to `pyproject.toml`.

### `src/live/runner.py`

Per-tick flow:

```python
def run_once(session, config, *, now, executor, notifier, fetch_open_fn, quote_fn, dry_run=False) -> dict:
    # 1. Upsert open markets (unchanged)
    # 2. Load favorites
    favorites = load_favorites(session, config)

    # 3. Per-favorite: detect → gate → open
    for fav in favorites:
        if fav.strategy_name == "snapshot":
            signals = detect_snapshot_entries(session, fav, now=now,
                                              tolerance_hours=config.tolerance_hours,
                                              quote_fn=quote_fn)
        else:
            signals = detect_threshold_entries(session, fav, now=now, quote_fn=quote_fn)

        bankroll = compute_bankroll(session, fav.label, fav.starting_bankroll)
        for sig in signals:
            cost = fav.shares_per_trade * sig.entry_price
            if cost > bankroll.available:
                logger.info("skipping %s: insufficient bankroll for %s", sig.market.id, fav.label)
                continue
            pos = executor.open_position(
                market=sig.market,
                entry_price=sig.entry_price,
                entry_timestamp=sig.entry_timestamp,
                sizing_result=SizingResult(
                    shares=fav.shares_per_trade,
                    notional=cost,
                    rule="fixed_shares",
                    params={"shares": fav.shares_per_trade},
                ),
                strategy=fav.label,
            )
            bankroll = replace(bankroll,
                               locked=bankroll.locked + cost,
                               available=bankroll.available - cost,
                               open_positions=bankroll.open_positions + 1)
            notifier.on_entry(pos, sig.market)

    # 4. Mark-to-market (unchanged)
    # 5. Sync resolutions + notify (unchanged)
```

The in-memory bankroll update within a tick prevents double-spending when multiple signals fire on the same favorite.

## Cron cadence

6-hour ticks. Update any cron doc / README hints from "every 10 minutes" to "every 6 hours." The snapshot tolerance (±12h) comfortably absorbs a 6h tick interval — a market in the window for 24h can be caught on up to 4 consecutive ticks; the per-(market, strategy) Position filter prevents duplicate entries across them.

## Dashboard changes

### New view: `render_candidates()`

Sidebar view order: `Thesis Overview | Live Positions | Candidates | Strategy Comparison | Sizing Comparison | Deep Dive | Market Browser`.

**Top panel — per-strategy bankroll summary** (one row per enabled favorite):

| Strategy | Starting | Locked | Realized P&L | Available | Open | Closed | W/L |

Data: `compute_bankroll` per favorite.

**Bottom panel — candidate table, per-strategy tabs:**

Columns (adapt per strategy):

| State | Market | Category | Quote | Target | ETA | Age | Blocked? | Link |

Ordering: `ready` → `watching` (quote ascending — closest to target first) → `waiting` (ETA ascending) → `expired` → `entered`. Top 50 per state with a "show all" toggle.

Respects the sidebar date-range filter; category is effectively pinned to `geopolitical`.

Read-only. No manual-open button.

### Extended view: `render_live_positions()`

**Strategy tabs:** one tab per enabled favorite (full label), plus an "All" tab first. For the current favorites: `st.tabs(["All", "snapshot_24__earliest_created", "threshold_0.3__earliest_created"])`. "All" preserves today's aggregate view. Each strategy tab shows:

- Metrics row: `Starting`, `Available`, `Locked`, `Realized P&L`, `Unrealized P&L`, `Win rate`, `Open`, `Resolved` (scoped to that strategy's positions).
- Open positions table (scoped).
- Resolved positions table (scoped).
- **Equity curve:** plots `available + locked` over time, replayed from position events. Horizontal reference line at `starting_bankroll`.

**Duplicate-market visibility:** "All" tab adds a `Strategy` badge column; rows sortable by question so cross-strategy behavior on the same market is visible.

**Bankroll-exhausted warning:** if `available < shares_per_trade * 0.3` (can't afford even the cheapest plausible threshold entry), render an inline warning on that tab.

## Testing

- `tests/test_favorites.py` — label parser (valid snapshot/threshold labels, reject unsupported, reject malformed), `load_favorites` joins correctly with config and skips favorites missing from config.
- `tests/test_bankroll.py` — pure-function correctness: starting only, with open positions, with mixed open/closed, with wins only, with losses only, empty position history.
- `tests/test_signals.py` — extend existing tests:
  - `detect_snapshot_entries` respects per-(market, strategy) dedup (same market can be entered by threshold even if snapshot entered it).
  - `detect_threshold_entries` fires when quote ≤ threshold including markets that open below threshold.
  - `detect_threshold_entries` does not fire when quote > threshold.
  - Template-dupe block is scoped to the current strategy.
- `tests/test_runner_multistrategy.py` — per-tick flow with two favorites, bankroll gating blocks over-commit, in-memory bankroll update prevents double-spend within a tick.
- `tests/test_dashboard_candidates.py` — `enumerate_candidates` classifies each state correctly from fixture data.

All tests use the in-memory SQLite fixture already established in `tests/conftest.py`. No network.

## Rollout

1. Land `favorites.py`, `bankroll.py`, YAML config — unit-tested, no runner changes yet.
2. Refactor `signals.py` into two detectors + update tests. No back-compat kept — the single-strategy runner is replaced in step 3.
3. Update `runner.py` to loop over favorites + bankroll-gate; `snapshot_24__earliest_deadline` hard-code removed.
4. Dashboard: Candidates view + Live Positions tabs.
5. Manual smoke test: run `uv run python -m src.live.runner` with the real `data/polymarket.db`; verify positions open for both strategies across a few ticks.
6. Cron setup: 6h interval, documented in README.

## Open questions (none blocking implementation)

- Quote batching: the CLOB midpoints endpoint may or may not support batch requests. If not, per-token `httpx` calls with concurrency (e.g. 10 in-flight) is the fallback. Decide during step 2 of rollout.
- Equity curve on Candidates page (per-strategy sparkline) is a stretch goal; deferred unless the main table lands quickly.
