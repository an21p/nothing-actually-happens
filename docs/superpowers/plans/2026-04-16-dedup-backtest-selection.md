# Deduplicated Backtest Selection — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two selection modes (`earliest_created`, `earliest_deadline`) that filter template-duplicate Polymarket markets before backtesting, and run all (entry × selection) combinations by default.

**Architecture:** Add a pre-filter stage in `src/backtester/engine.py` that groups markets by a date-stripped template key and walks each group in priority order, emitting markets only when prior emissions have already resolved. The filter runs before the existing entry-strategy loop. `run_all_strategies` iterates the cross product of entry strategies and selection modes.

**Tech Stack:** Python 3.14, SQLAlchemy 2.x, pytest, `uv` for dependency management. Existing project conventions (in-memory SQLite for tests via `tests/conftest.py`).

**Spec:** `docs/superpowers/specs/2026-04-16-dedup-backtest-selection-design.md`

---

## File Structure

**Modified:**
- `src/backtester/engine.py` — adds `_template_key`, `_select_markets`, `SELECTION_MODES`; modifies `run_backtest`, `run_all_strategies`, `main`

**Created:**
- `tests/test_selection.py` — unit tests for `_template_key` and `_select_markets`

**Modified (extended, not rewritten):**
- `tests/test_engine.py` — adds integration tests for selection-mode wiring

No new modules, no schema changes, no new dependencies. Helpers stay in `engine.py` (it grows from 92 → ~160 lines, well under the 300-line split threshold from the spec).

---

## Task 1: `_template_key` helper

Strips date references and normalizes the question text into a stable group key.

**Files:**
- Create: `tests/test_selection.py`
- Modify: `src/backtester/engine.py` (add helper near top, after imports)

- [ ] **Step 1: Write failing tests**

Create `tests/test_selection.py` with the following content:

```python
from datetime import datetime, timedelta, timezone

import pytest

from src.backtester.engine import _select_markets, _template_key
from src.storage.models import Market


def _utc(year, month, day, hour=0):
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


def _market(mid, question, created_at, resolved_at):
    return Market(
        id=mid,
        question=question,
        category="political",
        no_token_id=f"tok_{mid}",
        created_at=created_at,
        resolved_at=resolved_at,
        resolution="No",
    )


def test_template_key_strips_full_month_name_date():
    a = _template_key("Will Israel strike Gaza on January 31, 2026?")
    b = _template_key("Will Israel strike Gaza on January 5, 2026?")
    c = _template_key("Will Israel strike Gaza on December 1?")
    assert a == b == c


def test_template_key_strips_by_phrase():
    a = _template_key("US strikes Iran by February 27, 2026?")
    b = _template_key("US strikes Iran by February 6, 2026?")
    assert a == b


def test_template_key_strips_week_of_phrase():
    a = _template_key("Will Netflix (NFLX) finish week of April 6 above $130?")
    b = _template_key("Will Netflix (NFLX) finish week of March 23 above $130?")
    assert a == b


def test_template_key_strips_short_numeric_date():
    a = _template_key("Trade ABC closes on 4/12?")
    b = _template_key("Trade ABC closes on 12/30/25?")
    assert a == b


def test_template_key_strips_abbreviated_month():
    a = _template_key("Event by Feb 14, 2026?")
    b = _template_key("Event by Mar 7?")
    assert a == b


def test_template_key_distinct_questions_stay_distinct():
    assert _template_key("Will Israel strike Gaza on January 31, 2026?") != _template_key(
        "Will Israel strike Lebanon on January 31, 2026?"
    )


def test_template_key_lowercases_and_collapses_whitespace():
    assert _template_key("  WILL  X   HAPPEN?  ") == "will x happen?"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_selection.py -v`
Expected: collection error / `ImportError: cannot import name '_template_key' from 'src.backtester.engine'`

- [ ] **Step 3: Implement `_template_key` in `src/backtester/engine.py`**

Add to the top of `src/backtester/engine.py`, immediately after the existing imports (before `def run_backtest`):

```python
import re

_MONTH_PATTERN = (
    r"(?:january|february|march|april|may|june|july|august|september|october|"
    r"november|december|jan|feb|mar|apr|may|jun|jul|aug|sept|sep|oct|nov|dec)"
)
_DATE_PHRASE_RE = re.compile(
    rf"\b(?:by|on|before|after|until|in|week\s+of)\s+{_MONTH_PATTERN}\.?\s+"
    rf"\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s*\d{{2,4}})?",
    re.IGNORECASE,
)
_BARE_MONTH_DATE_RE = re.compile(
    rf"\b{_MONTH_PATTERN}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s*\d{{2,4}})?",
    re.IGNORECASE,
)
_NUMERIC_DATE_RE = re.compile(r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b")
_WHITESPACE_RE = re.compile(r"\s+")


def _template_key(question: str) -> str:
    text = _DATE_PHRASE_RE.sub("", question)
    text = _BARE_MONTH_DATE_RE.sub("", text)
    text = _NUMERIC_DATE_RE.sub("", text)
    text = _WHITESPACE_RE.sub(" ", text).strip().lower()
    return text
```

Note: keep the existing `import argparse` and `import uuid` lines as they are; add the `import re` either alphabetized with them or grouped with the new constants.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_selection.py -v -k template_key`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add tests/test_selection.py src/backtester/engine.py
git commit -m "feat(backtester): add _template_key helper for grouping duplicate markets"
```

---

## Task 2: `_select_markets` helper (all modes + eligibility)

Implements the core selection rule: group → walk in priority order → emit only when priors have resolved.

**Files:**
- Modify: `tests/test_selection.py` (append tests)
- Modify: `src/backtester/engine.py` (add helper)

- [ ] **Step 1: Append failing tests to `tests/test_selection.py`**

Append this block to the bottom of `tests/test_selection.py`:

```python
def test_select_markets_none_returns_input_unchanged():
    markets = [
        _market("a", "Will X happen on Jan 5, 2026?", _utc(2026, 1, 1), _utc(2026, 1, 5)),
        _market("b", "Will X happen on Jan 6, 2026?", _utc(2026, 1, 1), _utc(2026, 1, 6)),
    ]
    result = _select_markets(markets, "none")
    assert {m.id for m in result} == {"a", "b"}


def test_select_markets_singleton_group_emits_single():
    markets = [_market("solo", "Will Y happen?", _utc(2026, 1, 1), _utc(2026, 1, 5))]
    result = _select_markets(markets, "earliest_created")
    assert [m.id for m in result] == ["solo"]


def test_earliest_created_same_day_batch_picks_smallest_deadline():
    # All created same day; earliest_created ties broken by smallest deadline.
    markets = [
        _market("late", "Will X strike on Jan 31, 2026?", _utc(2025, 12, 30), _utc(2026, 1, 31)),
        _market("mid", "Will X strike on Jan 15, 2026?", _utc(2025, 12, 30), _utc(2026, 1, 15)),
        _market("early", "Will X strike on Jan 2, 2026?", _utc(2025, 12, 30), _utc(2026, 1, 2)),
    ]
    result = _select_markets(markets, "earliest_created")
    assert [m.id for m in result] == ["early"]


def test_earliest_deadline_same_day_batch_picks_smallest_deadline():
    markets = [
        _market("late", "Will X strike on Jan 31, 2026?", _utc(2025, 12, 30), _utc(2026, 1, 31)),
        _market("mid", "Will X strike on Jan 15, 2026?", _utc(2025, 12, 30), _utc(2026, 1, 15)),
        _market("early", "Will X strike on Jan 2, 2026?", _utc(2025, 12, 30), _utc(2026, 1, 2)),
    ]
    result = _select_markets(markets, "earliest_deadline")
    assert [m.id for m in result] == ["early"]


def test_earliest_created_rolling_cohorts_picks_one_per_cohort():
    # Cohort 1 created Jan 2 (deadlines Jan 10, Jan 17).
    # Cohort 2 created Jan 12 (deadlines Jan 24, Jan 31).
    # Cohort 1's pick (Jan 10) resolves before Cohort 2 is created -> Cohort 2 eligible.
    markets = [
        _market("c1a", "Trump strike by Jan 10, 2026?", _utc(2026, 1, 2), _utc(2026, 1, 10)),
        _market("c1b", "Trump strike by Jan 17, 2026?", _utc(2026, 1, 2), _utc(2026, 1, 17)),
        _market("c2a", "Trump strike by Jan 24, 2026?", _utc(2026, 1, 12), _utc(2026, 1, 24)),
        _market("c2b", "Trump strike by Jan 31, 2026?", _utc(2026, 1, 12), _utc(2026, 1, 31)),
    ]
    result = _select_markets(markets, "earliest_created")
    assert sorted(m.id for m in result) == ["c1a", "c2a"]


def test_earliest_deadline_rolling_cohorts_picks_one_per_cohort():
    markets = [
        _market("c1a", "Trump strike by Jan 10, 2026?", _utc(2026, 1, 2), _utc(2026, 1, 10)),
        _market("c1b", "Trump strike by Jan 17, 2026?", _utc(2026, 1, 2), _utc(2026, 1, 17)),
        _market("c2a", "Trump strike by Jan 24, 2026?", _utc(2026, 1, 12), _utc(2026, 1, 24)),
        _market("c2b", "Trump strike by Jan 31, 2026?", _utc(2026, 1, 12), _utc(2026, 1, 31)),
    ]
    result = _select_markets(markets, "earliest_deadline")
    assert sorted(m.id for m in result) == ["c1a", "c2a"]


def test_earliest_created_recurring_pattern_picks_each_occurrence():
    # Daily independent markets -- each new market created after prior resolved.
    markets = [
        _market("d1", "Will WH call lid on Apr 13?", _utc(2026, 4, 9), _utc(2026, 4, 13, 19)),
        _market("d2", "Will WH call lid on Apr 14?", _utc(2026, 4, 14, 0), _utc(2026, 4, 14, 19)),
        _market("d3", "Will WH call lid on Apr 15?", _utc(2026, 4, 15, 0), _utc(2026, 4, 15, 19)),
    ]
    result = _select_markets(markets, "earliest_created")
    assert sorted(m.id for m in result) == ["d1", "d2", "d3"]


def test_earliest_deadline_diverges_from_earliest_created():
    # A: created Jan 2, deadline Jan 30 (long-running)
    # B: created Jan 5, deadline Jan 10 (short, but created later)
    # earliest_created -> picks A (then B blocked: A unresolved at Jan 5)
    # earliest_deadline -> picks B (then A blocked: B unresolved at Jan 2)
    markets = [
        _market("A", "Event by Jan 30, 2026?", _utc(2026, 1, 2), _utc(2026, 1, 30)),
        _market("B", "Event by Jan 10, 2026?", _utc(2026, 1, 5), _utc(2026, 1, 10)),
    ]
    assert [m.id for m in _select_markets(markets, "earliest_created")] == ["A"]
    assert [m.id for m in _select_markets(markets, "earliest_deadline")] == ["B"]


def test_select_markets_unknown_mode_raises():
    markets = [_market("a", "Will X happen?", _utc(2026, 1, 1), _utc(2026, 1, 2))]
    with pytest.raises(ValueError, match="Unknown selection mode"):
        _select_markets(markets, "bogus")


def test_select_markets_missing_resolved_at_falls_back_to_created():
    # Defensive: if resolved_at is None, treat the market as resolving at creation.
    m = _market("nores", "Will X happen by Jan 5, 2026?", _utc(2026, 1, 1), None)
    result = _select_markets([m], "earliest_deadline")
    assert [x.id for x in result] == ["nores"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_selection.py -v`
Expected: the new tests fail with `ImportError: cannot import name '_select_markets'`. The 7 `_template_key` tests still pass.

- [ ] **Step 3: Implement `_select_markets` in `src/backtester/engine.py`**

Add this block to `src/backtester/engine.py` immediately below the `_template_key` function:

```python
SELECTION_MODES = ("none", "earliest_created", "earliest_deadline")

_PRIORITY_KEYS = {
    "earliest_created": lambda m: (m.created_at, m.resolved_at or m.created_at),
    "earliest_deadline": lambda m: (m.resolved_at or m.created_at, m.created_at),
}


def _select_markets(markets, mode):
    if mode == "none":
        return list(markets)
    if mode not in _PRIORITY_KEYS:
        raise ValueError(f"Unknown selection mode: {mode}")

    sort_key = _PRIORITY_KEYS[mode]
    groups: dict[str, list] = {}
    for m in markets:
        groups.setdefault(_template_key(m.question), []).append(m)

    selected = []
    for group in groups.values():
        group.sort(key=sort_key)
        emitted = []
        for candidate in group:
            if all(
                (e.resolved_at or e.created_at) <= candidate.created_at
                for e in emitted
            ):
                emitted.append(candidate)
        selected.extend(emitted)
    return selected
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_selection.py -v`
Expected: 17 passed (7 from Task 1 + 10 new).

- [ ] **Step 5: Commit**

```bash
git add tests/test_selection.py src/backtester/engine.py
git commit -m "feat(backtester): add _select_markets with eligibility-walk dedup"
```

---

## Task 3: Wire `selection_mode` into `run_backtest`

Adds the parameter, applies the filter before the per-market loop, and appends the suffix to the run label.

**Files:**
- Modify: `src/backtester/engine.py:run_backtest` (lines 12-53)
- Modify: `tests/test_engine.py` (append tests)

- [ ] **Step 1: Append failing integration tests to `tests/test_engine.py`**

Append the following to the end of `tests/test_engine.py`:

```python
def _seed_duplicate_group(session):
    # Three markets with the same template, all created same day, different deadlines.
    base_create = datetime(2025, 12, 30, tzinfo=timezone.utc)
    markets = [
        Market(
            id="dup_early",
            question="Will Israel strike Gaza on January 2, 2026?",
            category="geopolitical",
            no_token_id="tok_e",
            created_at=base_create,
            resolved_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            resolution="No",
        ),
        Market(
            id="dup_mid",
            question="Will Israel strike Gaza on January 15, 2026?",
            category="geopolitical",
            no_token_id="tok_m",
            created_at=base_create,
            resolved_at=datetime(2026, 1, 15, tzinfo=timezone.utc),
            resolution="No",
        ),
        Market(
            id="dup_late",
            question="Will Israel strike Gaza on January 31, 2026?",
            category="geopolitical",
            no_token_id="tok_l",
            created_at=base_create,
            resolved_at=datetime(2026, 1, 31, tzinfo=timezone.utc),
            resolution="No",
        ),
    ]
    session.add_all(markets)
    session.flush()
    for m in markets:
        session.add(
            PriceSnapshot(
                market_id=m.id,
                timestamp=base_create,
                no_price=0.85,
                source="api",
            )
        )
    session.commit()


def test_run_backtest_selection_mode_none_writes_all(session):
    _seed_duplicate_group(session)
    run_id = run_backtest(
        session, strategy_name="at_creation", params={}, categories=None,
        selection_mode="none",
    )
    results = session.query(BacktestResult).filter_by(run_id=run_id).all()
    assert len(results) == 3
    assert all(r.strategy == "at_creation" for r in results)


def test_run_backtest_selection_mode_earliest_created_dedupes(session):
    _seed_duplicate_group(session)
    run_id = run_backtest(
        session, strategy_name="at_creation", params={}, categories=None,
        selection_mode="earliest_created",
    )
    results = session.query(BacktestResult).filter_by(run_id=run_id).all()
    assert len(results) == 1
    assert results[0].market_id == "dup_early"
    assert results[0].strategy == "at_creation__earliest_created"


def test_run_backtest_selection_mode_earliest_deadline_dedupes(session):
    _seed_duplicate_group(session)
    run_id = run_backtest(
        session, strategy_name="at_creation", params={}, categories=None,
        selection_mode="earliest_deadline",
    )
    results = session.query(BacktestResult).filter_by(run_id=run_id).all()
    assert len(results) == 1
    assert results[0].market_id == "dup_early"
    assert results[0].strategy == "at_creation__earliest_deadline"


def test_run_backtest_selection_with_params_label(session):
    _seed_duplicate_group(session)
    run_id = run_backtest(
        session, strategy_name="threshold", params={"threshold": 0.85},
        categories=None, selection_mode="earliest_created",
    )
    results = session.query(BacktestResult).filter_by(run_id=run_id).all()
    assert len(results) == 1
    assert results[0].strategy == "threshold_0.85__earliest_created"


def test_run_backtest_default_selection_is_none(session):
    # Backwards compat: not passing selection_mode = old behavior.
    _seed_duplicate_group(session)
    run_id = run_backtest(session, strategy_name="at_creation", params={}, categories=None)
    results = session.query(BacktestResult).filter_by(run_id=run_id).all()
    assert len(results) == 3
    assert all(r.strategy == "at_creation" for r in results)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_engine.py -v -k selection`
Expected: 4 fail (TypeError: unexpected keyword `selection_mode`). `test_run_backtest_default_selection_is_none` will pass already (uses no kwarg) but the existing 3 markets seed expects 1 result of `at_creation` strategy — actually it expects 3 since `selection_mode` defaults to none. Verify failure mode matches the missing kwarg before continuing.

- [ ] **Step 3: Modify `run_backtest` in `src/backtester/engine.py`**

Replace the existing `def run_backtest(...)` (lines 12-53) with:

```python
def run_backtest(
    session: Session,
    strategy_name: str,
    params: dict,
    categories: list[str] | None = None,
    selection_mode: str = "none",
) -> str:
    if selection_mode not in SELECTION_MODES:
        raise ValueError(f"Unknown selection mode: {selection_mode}")

    strategy_info = STRATEGIES[strategy_name]
    strategy_fn = strategy_info["fn"]
    param_suffix = ""
    if params:
        param_suffix = "_" + "_".join(str(v) for v in params.values())
    selection_suffix = "" if selection_mode == "none" else f"__{selection_mode}"
    strategy_label = f"{strategy_name}{param_suffix}{selection_suffix}"
    run_id = str(uuid.uuid4())[:8]

    query = select(Market).where(Market.resolution.isnot(None))
    if categories:
        query = query.where(Market.category.in_(categories))
    markets = session.execute(query).scalars().all()
    markets = _select_markets(markets, selection_mode)

    for market in markets:
        snapshots = (
            session.query(PriceSnapshot)
            .filter_by(market_id=market.id)
            .order_by(PriceSnapshot.timestamp)
            .all()
        )
        price_history = [{"timestamp": s.timestamp, "no_price": s.no_price} for s in snapshots]
        if not price_history:
            continue

        result = strategy_fn(market.created_at, price_history, **params)
        if result is None:
            continue

        entry_price, entry_timestamp = result
        exit_price = 1.0 if market.resolution == "No" else 0.0
        profit = exit_price - entry_price

        session.add(BacktestResult(
            market_id=market.id, strategy=strategy_label,
            entry_price=entry_price, entry_timestamp=entry_timestamp,
            exit_price=exit_price, profit=profit,
            category=market.category, run_id=run_id,
        ))

    session.commit()
    return run_id
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_engine.py tests/test_selection.py -v`
Expected: all selection tests pass. Existing engine tests still pass (the four legacy `test_run_backtest_*` tests are unchanged).

- [ ] **Step 5: Commit**

```bash
git add src/backtester/engine.py tests/test_engine.py
git commit -m "feat(backtester): add selection_mode parameter to run_backtest"
```

---

## Task 4: Cross-product runs in `run_all_strategies` + CLI flag

Default-run iterates `(selection_mode, strategy, params)`. CLI exposes `--selection`.

**Files:**
- Modify: `src/backtester/engine.py:run_all_strategies` (lines 56-62)
- Modify: `src/backtester/engine.py:main` (lines 65-89)
- Modify: `tests/test_engine.py` (append test)

- [ ] **Step 1: Append failing test to `tests/test_engine.py`**

Append:

```python
def test_run_all_strategies_runs_cross_product(session):
    _seed_data(session)
    from src.backtester.engine import run_all_strategies
    from src.backtester.strategies import STRATEGIES

    run_ids = run_all_strategies(session, categories=None)

    expected_entry_combos = sum(len(info["params"]) for info in STRATEGIES.values())
    expected_total = expected_entry_combos * 3  # none + earliest_created + earliest_deadline
    assert len(run_ids) == expected_total

    labels = {r.strategy for r in session.query(BacktestResult).all()}
    # Ensure both selection suffixes appear in the label set.
    assert any("__earliest_created" in l for l in labels)
    assert any("__earliest_deadline" in l for l in labels)
    # And that "none" mode labels are bare (no suffix).
    assert any("__" not in l for l in labels)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_engine.py::test_run_all_strategies_runs_cross_product -v`
Expected: FAIL with `assert N == 3*N` where N is the prior combo count.

- [ ] **Step 3: Modify `run_all_strategies` in `src/backtester/engine.py`**

Replace the existing `def run_all_strategies(...)` with:

```python
def run_all_strategies(session: Session, categories: list[str] | None = None) -> list[str]:
    run_ids = []
    for selection_mode in SELECTION_MODES:
        for strategy_name, info in STRATEGIES.items():
            for params in info["params"]:
                run_id = run_backtest(
                    session, strategy_name, params, categories, selection_mode
                )
                run_ids.append(run_id)
    return run_ids
```

- [ ] **Step 4: Modify `main` in `src/backtester/engine.py`**

Replace the existing `def main()` with:

```python
def main():
    parser = argparse.ArgumentParser(description="Run backtests")
    parser.add_argument("--strategy", type=str, default=None)
    parser.add_argument("--param", type=str, default=None)
    parser.add_argument("--categories", type=str, default=None)
    parser.add_argument(
        "--selection",
        type=str,
        choices=list(SELECTION_MODES),
        default="none",
        help="Selection mode for deduplicating template-duplicate markets",
    )
    args = parser.parse_args()

    engine = get_engine()
    session = get_session(engine)
    categories = args.categories.split(",") if args.categories else None

    if args.strategy:
        params = {}
        if args.param and args.strategy == "threshold":
            params["threshold"] = float(args.param)
        elif args.param and args.strategy == "snapshot":
            params["offset_hours"] = int(args.param)
        run_id = run_backtest(
            session, args.strategy, params, categories, args.selection
        )
        print(f"Backtest complete. Run ID: {run_id}")
    else:
        run_ids = run_all_strategies(session, categories)
        print(f"All backtests complete. {len(run_ids)} runs.")

    session.close()
    engine.dispose()
```

- [ ] **Step 5: Run all tests to verify everything passes**

Run: `uv run pytest tests/ -v`
Expected: all tests pass, including the new `test_run_all_strategies_runs_cross_product`.

- [ ] **Step 6: Commit**

```bash
git add src/backtester/engine.py tests/test_engine.py
git commit -m "feat(backtester): cross-product entry x selection in run_all_strategies, add --selection CLI flag"
```

---

## Task 5: Manual smoke test against real data

Verify the new modes behave sensibly on the actual database. No new code — just runs the CLI and inspects results.

**Files:** none (verification only)

- [ ] **Step 1: Snapshot result counts before**

Run:

```bash
uv run python -c "
from src.storage.db import get_engine, get_session
from src.storage.models import BacktestResult
from sqlalchemy import distinct, func, select
e = get_engine(); s = get_session(e)
print('Total result rows:', s.query(func.count(BacktestResult.id)).scalar())
print('Distinct strategies:', s.query(func.count(distinct(BacktestResult.strategy))).scalar())
print('Distinct run_ids:', s.query(func.count(distinct(BacktestResult.run_id))).scalar())
"
```

Record the three numbers.

- [ ] **Step 2: Run a single-strategy single-mode backtest**

Run:

```bash
uv run python -m src.backtester.engine --strategy at_creation --selection earliest_created
```

Expected: prints `Backtest complete. Run ID: <8-char-hex>`.

- [ ] **Step 3: Verify the run is much smaller than the unfiltered baseline**

Run:

```bash
uv run python -c "
from src.storage.db import get_engine, get_session
from src.storage.models import BacktestResult
from sqlalchemy import select, func
e = get_engine(); s = get_session(e)
labels = ['at_creation', 'at_creation__earliest_created']
for label in labels:
    q = select(func.count(BacktestResult.id)).where(BacktestResult.strategy == label)
    print(label, '->', s.execute(q).scalar())
"
```

Expected: `at_creation__earliest_created` count is meaningfully smaller than `at_creation` (we expect ~700+ fewer rows based on the spec's 848 markets in 126 duplicate groups).

- [ ] **Step 4: Run all strategies (the full default run)**

Only run this if you want a full refresh. It will take a few minutes:

```bash
uv run python -m src.backtester.engine
```

Expected: `All backtests complete. 33 runs.` (11 entry combos × 3 selection modes).

- [ ] **Step 5: No commit — verification only**

Manual verification step. Record observed numbers in a comment on the PR if you open one.

---

## Self-Review Notes

Spec coverage:
- Selection rule (eligibility walk) → Task 2
- `earliest_created` mode → Task 2
- `earliest_deadline` mode → Task 2
- `none` mode (backwards compat) → Task 2 + Task 3
- Run label suffix `__{mode}` → Task 3
- `run_backtest(selection_mode)` parameter → Task 3
- Default-run cross product → Task 4
- `--selection` CLI flag → Task 4
- `_template_key` regex coverage → Task 1
- Singleton/missing-resolved_at edge cases → Task 2
- Tests for all of the above → Tasks 1, 2, 3, 4

Type/name consistency:
- `_template_key`, `_select_markets`, `SELECTION_MODES`, `_PRIORITY_KEYS` defined in Task 1/2 — referenced consistently in Tasks 3 and 4.
- Run-label format `{strategy}{param_suffix}{selection_suffix}` matches assertion strings in Task 3 (`at_creation__earliest_created`, `threshold_0.85__earliest_created`).
- `selection_mode` parameter spelled identically across `run_backtest`, `run_all_strategies`, and `_select_markets`.

No placeholders detected.
