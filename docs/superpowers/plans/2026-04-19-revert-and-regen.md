# Revert to b8c43fd, narrow scope, regen data — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve the abandoned polygon trade-tape work on a side branch, force `main` back to commit `b8c43fd`, strip the unrealistic `best_price` strategy, narrow the collector to politics/geopolitics markets since 2020, document the failed Polygon on-chain experiment in `CLAUDE.md`, then regenerate the DB and re-run the backtester.

**Architecture:** No structural changes. Restores the tree to `b8c43fd` + small edits to the collector runner, strategies registry, tests, dashboard description dict, and CLAUDE.md.

**Tech Stack:** Git (branch + force-push), Python 3 / pytest, SQLite, uv.

**Spec:** [docs/superpowers/specs/2026-04-19-revert-and-regen-design.md](../specs/2026-04-19-revert-and-regen-design.md)

---

## Pre-flight check

Before starting, confirm you're in `/Users/pishias/code/ai/polymarket` on branch `main` with uncommitted changes to `src/collector/trades/polymarket.py` and `tests/test_trades_polymarket.py`, and untracked `scripts/trades_backfill.sh`.

```bash
pwd
# → /Users/pishias/code/ai/polymarket

git status --short
# Expected: M src/collector/trades/polymarket.py
#           M tests/test_trades_polymarket.py
#           ?? .claude/
#           ?? scripts/trades_backfill.sh
#           ?? docs/superpowers/specs/2026-04-19-revert-and-regen-design.md
#           ?? docs/superpowers/plans/2026-04-19-revert-and-regen.md
```

The two `docs/superpowers/**` files are the spec + this plan — they're untracked and will survive the `reset --hard` in Task 2. We commit them onto post-reset `main` in Task 3.

---

## Task 1: Preserve abandoned work on `polygon` branch

**Goal:** Capture the 16 trade-tape commits + uncommitted trade-collector modifications + `scripts/trades_backfill.sh` on a new `polygon` branch pushed to origin, so none of it is lost when we reset `main`.

**Files:** No source edits. Git operations only.

- [ ] **Step 1: Create `polygon` branch from current HEAD**

```bash
git checkout -b polygon
git status --short
# Expected: same M/?? status as before — we just renamed HEAD, didn't touch the tree.
```

- [ ] **Step 2: Stage ONLY the trade-tape changes (not the spec/plan)**

Explicit staging — avoid `git add -A` because it would also grab `docs/superpowers/specs/2026-04-19-revert-and-regen-design.md` and this plan file, which belong on `main` not `polygon`. It would also grab `.claude/` which is local-only.

```bash
git add src/collector/trades/polymarket.py tests/test_trades_polymarket.py scripts/trades_backfill.sh
git status --short
# Expected: A scripts/trades_backfill.sh
#           M src/collector/trades/polymarket.py
#           M tests/test_trades_polymarket.py
#           ?? .claude/
#           ?? docs/superpowers/specs/2026-04-19-revert-and-regen-design.md
#           ?? docs/superpowers/plans/2026-04-19-revert-and-regen.md
```

- [ ] **Step 3: Commit on `polygon`**

```bash
git commit -m "wip: polygon trade-tape attempt (abandoned)

Final state of the on-chain trade-history collector before we abandoned
the approach. Retained here so the experiment isn't lost. See
docs/superpowers/specs/2026-04-19-revert-and-regen-design.md on main
for the rationale."
```

- [ ] **Step 4: Push `polygon` to origin**

```bash
git push -u origin polygon
# Expected: branch created on origin
```

- [ ] **Step 5: Verify polygon tip**

```bash
git log --oneline -3 polygon
# Expected: newest commit is "wip: polygon trade-tape attempt (abandoned)"
#           parent is 0e1ff4c refactor(trades): push _catchup_market_ids NOT IN filter into SQL
```

---

## Task 2: Force `main` back to `b8c43fd`

**Goal:** Rewrite `main` so its tip is `b8c43fd49fb09a76d100085400538c330e642812` (`streatch`). Destructive and irreversible on origin, so verify carefully.

**Files:** No source edits. Git operations only.

- [ ] **Step 1: Switch to main**

```bash
git checkout main
git rev-parse HEAD
# Expected: 0e1ff4c9... (the current tip, NOT b8c43fd yet)
```

- [ ] **Step 2: Confirm `polygon` has everything before resetting**

```bash
git log --oneline polygon -1
# Expected: "wip: polygon trade-tape attempt (abandoned)"
git diff polygon~1..polygon --stat
# Expected: shows the trade-collector files — confirms nothing's missing
```

- [ ] **Step 3: Hard reset `main` to b8c43fd**

```bash
git reset --hard b8c43fd49fb09a76d100085400538c330e642812
git log --oneline -3
# Expected:
#   b8c43fd streatch
#   208a5d9 dashboard market
#   be00e58 docs: add collector expansion implementation plan
```

Untracked files (`.claude/`, the spec, this plan) are left alone by `reset --hard`. Verify:

```bash
ls docs/superpowers/specs/ | grep 2026-04-19
# Expected: 2026-04-19-revert-and-regen-design.md
ls docs/superpowers/plans/ | grep 2026-04-19
# Expected: 2026-04-19-revert-and-regen.md
```

- [ ] **Step 4: Force-push main**

```bash
git push --force origin main
# Expected: "+ 0e1ff4c...b8c43fd main -> main (forced update)"
```

- [ ] **Step 5: Verify local tree matches b8c43fd**

```bash
git status --short
# Expected ONLY untracked: .claude/, docs/superpowers/specs/2026-04-19-...md, docs/superpowers/plans/2026-04-19-...md
git diff b8c43fd -- src/ tests/ CLAUDE.md
# Expected: empty — tracked files match the revert target exactly
```

---

## Task 3: Commit spec + plan on the reset `main`

**Goal:** Land the design + implementation plan as the first commit on top of `b8c43fd`, so future tasks have a recorded reference and the force-push is followed by a real change rather than raw reset.

**Files:**
- Add (from untracked): `docs/superpowers/specs/2026-04-19-revert-and-regen-design.md`
- Add (from untracked): `docs/superpowers/plans/2026-04-19-revert-and-regen.md`

- [ ] **Step 1: Stage both docs explicitly**

```bash
git add docs/superpowers/specs/2026-04-19-revert-and-regen-design.md docs/superpowers/plans/2026-04-19-revert-and-regen.md
git status --short
# Expected: A docs/superpowers/plans/2026-04-19-revert-and-regen.md
#           A docs/superpowers/specs/2026-04-19-revert-and-regen-design.md
#           ?? .claude/   (still untracked, correct — local settings only)
```

- [ ] **Step 2: Commit**

```bash
git commit -m "docs: add revert-to-b8c43fd spec and implementation plan"
```

- [ ] **Step 3: Push**

```bash
git push origin main
# Expected: fast-forward push, no --force needed this time
```

---

## Task 4: Remove `best_price` strategy (TDD-ish)

**Goal:** Delete the `best_price` function + its registry entry + tests + dashboard description. This eliminates `best_price`, `best_price__earliest_created`, and `best_price__earliest_deadline` labels from future backtest runs (the engine composes those variants from `STRATEGIES × SELECTION_MODES`).

**Files:**
- Modify: [src/backtester/strategies.py](../../../src/backtester/strategies.py)
- Modify: [tests/test_strategies.py](../../../tests/test_strategies.py)
- Modify: [src/dashboard/app.py:16-21](../../../src/dashboard/app.py)

- [ ] **Step 1: Run existing tests to establish baseline**

```bash
uv run pytest tests/test_strategies.py -v
# Expected: 12 tests pass (including test_best_price_finds_minimum, test_best_price_empty_history)
```

- [ ] **Step 2: Delete `best_price` tests + import**

In `tests/test_strategies.py`:

- Remove `best_price,` from the import block at the top (lines 3-8). After edit, the import reads:

```python
from src.backtester.strategies import (
    at_creation,
    price_threshold,
    time_snapshot,
)
```

- Delete the two `test_best_price_*` tests (lines 62-68):

```python
def test_best_price_finds_minimum():
    history = make_history([(1, 0.90), (2, 0.75), (3, 0.85)])
    result = best_price(CREATED_AT, history)
    assert result == (0.75, CREATED_AT + timedelta(hours=2))

def test_best_price_empty_history():
    assert best_price(CREATED_AT, []) is None
```

- [ ] **Step 3: Run tests to confirm failure from missing `best_price` in strategies.py**

```bash
uv run pytest tests/test_strategies.py -v
# Expected: 10 tests pass (the two best_price tests are gone, import block no longer fails)
```

If pytest reports an `ImportError` for `best_price`, it means Step 2's import edit was missed — go fix.

- [ ] **Step 4: Delete the `best_price` function + registry entry**

In `src/backtester/strategies.py`:

- Delete lines 35-39 (the function):

```python
def best_price(created_at: datetime, price_history: list[dict]) -> tuple[float, datetime] | None:
    if not price_history:
        return None
    best = min(price_history, key=lambda p: p["no_price"])
    return (best["no_price"], best["timestamp"])
```

- Delete line 51 (the registry entry — keep the closing `}` of the `STRATEGIES` dict):

```python
    "best_price": {"fn": best_price, "params": [{}]},
```

The final file must read:

```python
from datetime import datetime, timedelta

SNAPSHOT_MAX_DISTANCE_HOURS = 12

def at_creation(created_at: datetime, price_history: list[dict]) -> tuple[float, datetime] | None:
    if not price_history:
        return None
    first = price_history[0]
    return (first["no_price"], first["timestamp"])

def price_threshold(created_at: datetime, price_history: list[dict], threshold: float) -> tuple[float, datetime] | None:
    for point in price_history:
        if point["no_price"] <= threshold:
            return (point["no_price"], point["timestamp"])
    return None

def time_snapshot(created_at: datetime, price_history: list[dict], offset_hours: int) -> tuple[float, datetime] | None:
    if not price_history:
        return None
    target = created_at + timedelta(hours=offset_hours)
    max_distance = timedelta(hours=SNAPSHOT_MAX_DISTANCE_HOURS)
    closest = None
    closest_distance = None
    for point in price_history:
        distance = abs(point["timestamp"] - target)
        if distance > max_distance:
            continue
        if closest_distance is None or distance < closest_distance:
            closest = point
            closest_distance = distance
    if closest is None:
        return None
    return (closest["no_price"], closest["timestamp"])

STRATEGIES = {
    "at_creation": {"fn": at_creation, "params": [{}]},
    "threshold": {
        "fn": price_threshold,
        "params": [{"threshold": t} for t in [0.20, 0.30, 0.40, 0.50, 0.60]],
    },
    "snapshot": {
        "fn": time_snapshot,
        "params": [{"offset_hours": h} for h in [24, 48, 168]],
    },
}
```

- [ ] **Step 5: Remove `best_price` from dashboard description dict**

In `src/dashboard/app.py`, delete the `best_price` line from the `STRATEGY_DESCRIPTIONS` dict (line 20). After edit the dict reads:

```python
STRATEGY_DESCRIPTIONS = {
    "at_creation": 'Buys the "NO" token at the first recorded price after market creation. Baseline strategy to measure early entry timing.',
    "threshold": 'Waits for the "NO" token price to drop to a specific level before buying. Tests entry discipline by requiring a minimum discount.',
    "snapshot": 'Buys the "NO" token at a fixed time offset after market creation (24h, 48h, or 7d). Tests whether fixed timing works as an edge.',
}
```

- [ ] **Step 6: Run full test suite**

```bash
uv run pytest -v
# Expected: all tests pass. Count dropped by 2 vs. pre-revert baseline.
```

- [ ] **Step 7: Grep for stragglers**

```bash
# Using Grep tool: pattern "best_price", path /Users/pishias/code/ai/polymarket/src /Users/pishias/code/ai/polymarket/tests
```

Expected: zero matches across `src/` and `tests/`. Hits inside `docs/superpowers/plans/2026-04-15-polymarket-backtester.md` (the historical backtester plan) and `.claude/worktrees/` are fine — don't edit those.

- [ ] **Step 8: Commit**

```bash
git add src/backtester/strategies.py tests/test_strategies.py src/dashboard/app.py
git commit -m "refactor(backtester): drop best_price strategy

best_price picks the min NO price across the full market lifetime,
which is a hindsight-biased upper-bound that doesn't model a
tradeable entry rule. Removing it also kills the
best_price__earliest_created / best_price__earliest_deadline variants
(engine composes them from STRATEGIES × SELECTION_MODES)."
```

---

## Task 5: Narrow default collector categories

**Goal:** Change the runner's `--categories` default from `geopolitical,political,culture` to `political,geopolitical`. `culture` is still available via explicit `--categories culture` if ever needed.

**Files:**
- Modify: [src/collector/runner.py:116](../../../src/collector/runner.py)
- Modify: [CLAUDE.md](../../../CLAUDE.md) (defaults comment)

- [ ] **Step 1: Update the argparse default**

In `src/collector/runner.py` replace line 116:

```python
    parser.add_argument("--categories", type=str, default="geopolitical,political,culture", help="Comma-separated categories (default: geopolitical,political,culture)")
```

with:

```python
    parser.add_argument("--categories", type=str, default="political,geopolitical", help="Comma-separated categories (default: political,geopolitical)")
```

- [ ] **Step 2: Update the CLAUDE.md comment that mirrors the default**

In `CLAUDE.md` replace line 15:

```markdown
uv run python -m src.collector.runner                          # defaults: geopolitical,political,culture
```

with:

```markdown
uv run python -m src.collector.runner                          # defaults: political,geopolitical
```

- [ ] **Step 3: Sanity-check the CLI help output**

```bash
uv run python -m src.collector.runner --help
# Expected: "--categories CATEGORIES  Comma-separated categories (default: political,geopolitical)"
```

- [ ] **Step 4: Commit**

```bash
git add src/collector/runner.py CLAUDE.md
git commit -m "feat(collector): narrow default categories to political,geopolitical

Drop culture from the default sweep. culture markets are noisy for
the 'nothing ever happens' thesis (celebrity/entertainment). Still
reachable via explicit --categories culture."
```

---

## Task 6: Add 2020-01-01 date floor to collector (TDD)

**Goal:** Enforce `created_at >= 2020-01-01 UTC` inside `collect()` so regens don't accidentally sweep earlier markets even if the Gamma API offers them.

**Files:**
- Modify: [src/collector/runner.py](../../../src/collector/runner.py)
- Modify: [tests/test_collector_runner.py](../../../tests/test_collector_runner.py) (new test; file already exists)

- [ ] **Step 1: Inspect existing test file to match style**

Check the existing runner tests to mirror their fixtures/imports. The file should already import from `src.collector.runner` — add the new test near the other `collect()` tests.

```bash
# Using Read tool on /Users/pishias/code/ai/polymarket/tests/test_collector_runner.py
```

If the file doesn't exist at `b8c43fd`, create it fresh in Step 2 using the scaffold below; otherwise add the single new test function to whichever test file covers `collect()`.

- [ ] **Step 2: Write the failing test**

Append to whichever test file covers `collect()` (or create a new one if needed):

```python
from datetime import datetime, timezone
from unittest.mock import patch

from src.collector.runner import collect
from src.storage.db import get_engine, get_session
from src.storage.models import Market


def test_collect_drops_markets_created_before_2020():
    """Markets with created_at < 2020-01-01 UTC must never reach the DB."""
    fake_markets = [
        {
            "id": "old",
            "question": "pre-2020 market",
            "category": "political",
            "no_token_id": "tok_old",
            "created_at": datetime(2019, 6, 1, tzinfo=timezone.utc),
            "end_date": datetime(2019, 12, 1, tzinfo=timezone.utc),
            "source_url": None,
            "resolution": "No",
            "resolved_at": datetime(2019, 12, 1, tzinfo=timezone.utc),
        },
        {
            "id": "new",
            "question": "2021 market",
            "category": "political",
            "no_token_id": "tok_new",
            "created_at": datetime(2021, 6, 1, tzinfo=timezone.utc),
            "end_date": datetime(2021, 12, 1, tzinfo=timezone.utc),
            "source_url": None,
            "resolution": "No",
            "resolved_at": datetime(2021, 12, 1, tzinfo=timezone.utc),
        },
    ]

    with patch("src.collector.runner.fetch_resolved_markets", return_value=fake_markets), \
         patch("src.collector.runner.fetch_price_history", return_value=[]):
        collect(categories=["political"], db_path=":memory:")

    # Re-open same in-memory DB to verify — but :memory: is per-connection.
    # Instead, capture via patching session.add:
```

Because `:memory:` SQLite is per-connection, rewrite the test to patch `upsert_market` and capture the IDs that reach it:

```python
def test_collect_drops_markets_created_before_2020():
    """Markets with created_at < 2020-01-01 UTC must never reach upsert_market."""
    fake_markets = [
        {
            "id": "old", "question": "pre-2020 market", "category": "political",
            "no_token_id": "tok_old",
            "created_at": datetime(2019, 6, 1, tzinfo=timezone.utc),
            "end_date": datetime(2019, 12, 1, tzinfo=timezone.utc),
            "source_url": None, "resolution": "No",
            "resolved_at": datetime(2019, 12, 1, tzinfo=timezone.utc),
        },
        {
            "id": "new", "question": "2021 market", "category": "political",
            "no_token_id": "tok_new",
            "created_at": datetime(2021, 6, 1, tzinfo=timezone.utc),
            "end_date": datetime(2021, 12, 1, tzinfo=timezone.utc),
            "source_url": None, "resolution": "No",
            "resolved_at": datetime(2021, 12, 1, tzinfo=timezone.utc),
        },
    ]

    captured_ids: list[str] = []

    def _fake_upsert(session, market_data):
        captured_ids.append(market_data["id"])
        return True

    with patch("src.collector.runner.fetch_resolved_markets", return_value=fake_markets), \
         patch("src.collector.runner.fetch_price_history", return_value=[]), \
         patch("src.collector.runner.upsert_market", side_effect=_fake_upsert):
        collect(categories=["political"], db_path=":memory:")

    assert captured_ids == ["new"], f"pre-2020 market leaked: {captured_ids}"
```

- [ ] **Step 3: Run test — expect failure**

```bash
uv run pytest tests/test_collector_runner.py::test_collect_drops_markets_created_before_2020 -v
# Expected: FAIL — captured_ids == ["old", "new"] because the filter doesn't exist yet.
```

- [ ] **Step 4: Add the date-floor filter in `collect()`**

In `src/collector/runner.py`:

At the top of the file (after the existing stdlib imports `argparse`, `sys`, `time`), add a new stdlib import line and a module-level constant:

```python
import argparse
import sys
import time
from datetime import datetime, timezone

import httpx
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.storage.db import get_engine, get_session
from src.storage.models import Market, PriceSnapshot
from src.collector.polymarket_api import fetch_resolved_markets
from src.collector.price_history import fetch_price_history
from src.collector.polygon_chain import fetch_onchain_prices

MIN_CREATED_AT = datetime(2020, 1, 1, tzinfo=timezone.utc)
```

Then immediately after the `markets = fetch_resolved_markets(...)` call inside `collect()`, insert the filter:

```python
    markets = fetch_resolved_markets(
        categories=categories, limit=limit, end_date_max=end_date_max
    )
    pre_filter = len(markets)
    markets = [m for m in markets if m["created_at"] >= MIN_CREATED_AT]
    if pre_filter != len(markets):
        print(f"Dropped {pre_filter - len(markets)} markets with created_at < {MIN_CREATED_AT.date()}")
    print(f"Found {len(markets)} markets from API")
```

(Remove the original `print(f"Found {len(markets)} markets from API")` line — it's replaced above.)

- [ ] **Step 5: Run the new test — expect pass**

```bash
uv run pytest tests/test_collector_runner.py::test_collect_drops_markets_created_before_2020 -v
# Expected: PASS
```

- [ ] **Step 6: Run the full test suite — no regressions**

```bash
uv run pytest -v
# Expected: all pass
```

- [ ] **Step 7: Commit**

```bash
git add src/collector/runner.py tests/test_collector_runner.py
git commit -m "feat(collector): enforce created_at >= 2020-01-01 floor

Client-side filter in collect() — defensive even if the Gamma API
returns older markets. 2020 is roughly when Polymarket launched, so
this matches the natural data boundary but makes it explicit."
```

---

## Task 7: Document abandoned Polygon on-chain experiment in CLAUDE.md

**Goal:** Future-me reads CLAUDE.md before touching the collector. Leave a clear "don't retry this" note pointing at the `polygon` branch.

**Files:**
- Modify: [CLAUDE.md](../../../CLAUDE.md)

- [ ] **Step 1: Add the note**

In `CLAUDE.md`, find the `### src/collector/` section. Immediately after the `polygon_chain.py` bullet (the line starting with "`polygon_chain.py` — opt-in enrichment..."), insert a new paragraph:

```markdown
- `polygon_chain.py` — opt-in enrichment. Reads `OrderFilled` events from the CTF Exchange (`0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E`) in 10k-block chunks, computes trade prices from maker/taker amounts, timestamps via block time. Missing `web3` or RPC connectivity silently yields `[]`.

> **Note — Polygon on-chain trade history was attempted and abandoned.** An earlier branch (`polygon`, still on origin) tried to pull per-market trade fills by streaming `OrderFilled` events from the CTF Exchange contract on Polygon, writing them to a `trades` table with a dashboard tab, runner CLI, and backfill/catchup modes. The approach was too slow (RPC pagination over years of blocks) and too brittle (event-decode edge cases, missing fills) to be useful for backtesting. Gamma's `clob.polymarket.com/prices-history` remains the authoritative source for the price snapshots that `threshold` and `snapshot` strategies need. `polygon_chain.py` is retained only for the optional `--enrich-onchain` price interpolation; do NOT resurrect the trade-tape collector without first re-reading the `polygon` branch and understanding why it failed.
```

- [ ] **Step 2: Verify CLAUDE.md renders correctly**

```bash
# Using Read tool on /Users/pishias/code/ai/polymarket/CLAUDE.md to visually confirm the note lands in the right section.
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(CLAUDE): record abandoned Polygon on-chain trade-tape experiment

Point future work at the polygon branch so the failure mode isn't
rediscovered from scratch."
```

---

## Task 8: Smoke-test the collector

**Goal:** Catch any regression in the date-floor / category-narrowing logic before launching the multi-hour full regen. A `--limit 50` run takes <2 minutes and exercises both the API and the filter.

**Files:** No source edits. Runtime verification.

- [ ] **Step 1: Move the old DB aside (don't delete yet)**

```bash
mv data/polymarket.db data/polymarket.db.bak
# Expected: rename succeeds; data/polymarket.db no longer exists
```

- [ ] **Step 2: Smoke-run with --limit 50**

```bash
uv run python -m src.collector.runner --limit 50
# Expected output includes:
#   "Empty DB, fetching newest markets..."
#   "Found N markets from API"
#   [1/N] NEW <question text>  — ×50
#   "Done. 50 new, 0 skipped (already collected)."
```

- [ ] **Step 3: Inspect what landed in the smoke DB**

```bash
sqlite3 data/polymarket.db "SELECT COUNT(*) FROM markets; SELECT category, COUNT(*) FROM markets GROUP BY category; SELECT MIN(created_at) FROM markets;"
# Expected:
#   COUNT(*) == 50
#   Only 'political' and 'geopolitical' rows (no 'culture', 'other')
#   MIN(created_at) >= 2020-01-01
```

- [ ] **Step 4: Remove the smoke DB**

```bash
rm data/polymarket.db
# Ready for full regen. Keep data/polymarket.db.bak until Task 11 passes, as a recovery snapshot.
```

---

## Task 9: Full data regen

**Goal:** Rebuild `data/polymarket.db` from scratch with the narrowed filters. This is a multi-hour operation — run unattended.

**Files:** No source edits. Data collection.

- [ ] **Step 1: Confirm DB absent**

```bash
ls data/
# Expected: polymarket.db.bak present, polymarket.db absent
```

- [ ] **Step 2: Full collection**

```bash
uv run python -m src.collector.runner 2>&1 | tee data/regen-$(date +%Y%m%d-%H%M).log
# Expected: runs until the API stops returning new markets under the 2020 floor + political/geopolitical filters.
# Progress prints every market. Commits every 10.
```

Plan for this to take several hours. Resumable — if interrupted, rerunning picks up from the earliest `created_at` already in the DB (see `runner.collect()` behavior).

- [ ] **Step 3: Verify DB population**

```bash
sqlite3 data/polymarket.db "SELECT COUNT(*) FROM markets; SELECT category, COUNT(*) FROM markets GROUP BY category; SELECT MIN(created_at), MAX(created_at) FROM markets; SELECT COUNT(*) FROM price_snapshots;"
# Expected:
#   Market count in the low thousands (prior run had ~7.5k political+geopolitical combined)
#   ONLY 'political' and 'geopolitical' categories (no 'culture', 'other')
#   MIN(created_at) >= 2020-01-01, MAX reasonable (close to current date)
#   price_snapshots count in the tens of thousands
```

Flag for the user if the counts look suspiciously low (<500 total markets) before proceeding.

---

## Task 10: Rerun full backtester sweep

**Goal:** Populate a fresh `run_id` in `backtest_results` using the post-revert `STRATEGIES` (no `best_price`).

**Files:** No source edits. Backtest execution.

- [ ] **Step 1: Run the sweep**

```bash
uv run python -m src.backtester.engine 2>&1 | tee data/backtest-$(date +%Y%m%d-%H%M).log
# Expected: "All backtests complete. N runs." where N = |STRATEGIES × params × SELECTION_MODES|.
#           After removing best_price: 9 strategy-param combos (1 at_creation + 5 threshold + 3 snapshot) × 3 selection modes = 27 runs.
```

- [ ] **Step 2: Verify no `best_price*` rows in the latest sweep**

```bash
sqlite3 data/polymarket.db "SELECT DISTINCT strategy FROM backtest_results WHERE run_id IN (SELECT run_id FROM backtest_results ORDER BY id DESC LIMIT 10000);"
# Expected: no labels starting with 'best_price'. Only at_creation, threshold_*, snapshot_*, plus __earliest_created / __earliest_deadline variants.
```

Stronger check — assert absence:

```bash
sqlite3 data/polymarket.db "SELECT COUNT(*) FROM backtest_results WHERE strategy LIKE 'best_price%' AND run_id IN (SELECT DISTINCT run_id FROM backtest_results ORDER BY id DESC LIMIT 10000);"
# Expected: 0
```

- [ ] **Step 3: Report top runs to the user**

```bash
sqlite3 data/polymarket.db "SELECT strategy, COUNT(*) AS n, ROUND(AVG(profit), 4) AS avg_ev, ROUND(SUM(profit), 2) AS total_pnl FROM backtest_results WHERE run_id IN (SELECT DISTINCT run_id FROM backtest_results ORDER BY id DESC LIMIT 10000) GROUP BY strategy ORDER BY total_pnl DESC LIMIT 20;"
# Expected: ranked table of strategies by total PnL. Surface this to the user.
```

---

## Task 11: Clean up and verify dashboard

**Goal:** Remove the smoke-test backup and open the dashboard for a visual confirmation.

**Files:** No source edits.

- [ ] **Step 1: Delete the backup DB**

```bash
rm data/polymarket.db.bak
```

- [ ] **Step 2: Launch dashboard (user-verified, not scripted)**

```bash
uv run streamlit run src/dashboard/app.py
```

Tell the user:

> Dashboard is up on the default Streamlit port. Please confirm:
> 1. The Strategies tab lists only `at_creation`, `threshold_*`, `snapshot_*` (no `best_price*`).
> 2. Categories in the sidebar show only `political` and `geopolitical`.
> 3. The default run_id rendered is the fresh sweep from Task 10.

- [ ] **Step 3: After user approval, stop the dashboard (Ctrl+C) and we're done.**

---

## Post-completion sanity check

```bash
git log --oneline -10
# Expected, newest first:
#   feat/docs commits from Tasks 4–7 (exact messages from each task)
#   docs: add revert-to-b8c43fd spec and implementation plan   (Task 3)
#   b8c43fd streatch                                           (pre-existing, post-reset base)
```

```bash
git branch -a
# Expected: main (local + remote), polygon (local + remote)
```

Both branches are pushed; `polygon` preserves the abandoned work; `main` is the clean narrowed baseline with fresh data.
