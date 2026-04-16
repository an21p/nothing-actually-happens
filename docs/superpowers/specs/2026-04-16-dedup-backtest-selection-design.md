# Deduplicated Backtest Selection — Design

**Date:** 2026-04-16
**Status:** Proposed
**Author:** Claude (brainstorming session with user)

## Background

The Polymarket dataset contains many *template-duplicate* markets — the same question repeated with different deadline dates. Examples observed in the current DB:

- 66 markets matching "Will Israel strike Gaza on January NN, 2026?" — all created 2025-12-30
- 45 markets matching "US strikes Iran by February NN, 2026?" — all created 2026-02-16
- 25 markets matching "Trump announces new drug boat strike by ..." — created in three weekly cohorts (2026-01-02, 2026-01-12, 2026-01-27)
- 26 markets matching "Will the White House call a full lid by 6:30PM on Month DD?" — daily recurring pattern

Total: 126 duplicate groups covering 848 of 4,148 resolved markets (~20%).

Backtesting every duplicate independently overstates strategy performance — each near-identical market behaves similarly, so a single edge is double-counted. We want backtest results that reflect *one trade per real-world event*.

## Goal

Add a **selection stage** to the backtester that, given a list of resolved markets, returns a deduplicated subset with one market per template-group at any given time. Two selection priorities are exposed: prefer the earliest-created market, or prefer the earliest-deadline market.

## Non-goals

- No changes to the data collection pipeline.
- No new columns on the `Market` model. The existing `resolved_at` field is used as a deadline proxy.
- No dashboard UI changes. Dedup runs surface as additional rows under their own strategy labels.
- No fuzzy/LLM-based grouping. A regex date-stripping heuristic is sufficient for v1.

## Selection Rule

A market is **eligible** within its template-group if every previously-selected market in that group has already resolved (`resolved_at <= candidate.created_at`) by the time the candidate was created. Walking the group in priority order yields the selected subset.

This rule produces the desired behavior for all three observed patterns:

| Pattern | Behavior |
|---|---|
| Same-day batch (66 Israel-Gaza markets all created the same day) | Only one market is picked — the rest were not-yet-resolved siblings of the first |
| Rolling cohorts (Trump drug-boat-strike, weekly drops) | One pick per cohort — next cohort becomes eligible only after the prior pick has resolved |
| Pure recurring (daily White House lid) | Each occurrence is picked — by the time the next is created, the previous has already resolved |

## Two Selection Modes

Both modes apply the same eligibility rule. They differ only in **walk order** within a group, which changes which sibling wins ties.

- **`earliest_created`** — primary key: `created_at` ascending; tie-break: `resolved_at` ascending.
- **`earliest_deadline`** — primary key: `resolved_at` ascending; tie-break: `created_at` ascending.

A third mode `none` preserves today's behavior (no filtering).

## Architecture

### Selection stage in `engine.py`

`run_backtest` gains a new parameter:

```python
def run_backtest(
    session: Session,
    strategy_name: str,
    params: dict,
    categories: list[str] | None = None,
    selection_mode: str = "none",
) -> str:
```

After the `select(Market).where(...)` query loads the candidate markets, the engine calls `_select_markets(markets, selection_mode)` once. The downstream per-market loop is unchanged.

Run label format becomes `{strategy}{param_suffix}__{selection_mode}` (e.g. `at_creation__earliest_created`, `threshold_0.85__earliest_deadline`). When `selection_mode == "none"` the suffix is omitted to preserve existing labels.

### Selection helpers

Two private helpers added to `src/backtester/engine.py` (move to `selection.py` later if the file exceeds ~300 lines):

**`_template_key(question: str) -> str`** — strips date references and normalizes:
- `Month DD[, YYYY]` and abbreviations (`Jan`, `Feb`, ...)
- `MM/DD[/YY[YY]]`
- `week of <date>`
- `by/on/before/until/in <date>`
- Ordinals (`1st`, `21st`, `2nd`, etc.)
- Collapses whitespace, lowercases

**`_select_markets(markets: list[Market], mode: str) -> list[Market]`**
1. If `mode == "none"`: return `markets` unchanged
2. Group by `_template_key(market.question)`
3. For each group, sort by `(primary_key, tie_break_key)` per mode
4. Walk sorted group: emit candidate iff every previously-emitted market has `resolved_at <= candidate.created_at`
5. Return the union of emitted markets across groups (order does not matter — downstream loop is order-independent)

### Default-run behavior

`run_all_strategies` is updated to iterate over the **cross product** of `(strategy, params, selection_mode)` for every selection mode in `["none", "earliest_created", "earliest_deadline"]`. This satisfies the user requirement that the default backtester runs all combinations.

With the current `STRATEGIES` table (4 entry strategies × 10 param sets = 11 entry combos) and 3 selection modes, the default run produces **33 backtest result sets** instead of today's 11.

### CLI

`src/backtester/engine.py:main` adds:

```
--selection {none, earliest_created, earliest_deadline}
```

When omitted with `--strategy`, defaults to `none` (single-mode runs preserve today's behavior). When omitted without `--strategy`, all selection modes run (per the default-run behavior above).

## Edge cases

- **Missing `resolved_at`** — fall back to `created_at`. (Should not occur because the query filters `resolution.isnot(None)`, but the fallback is defensive.)
- **Singleton group** — emits the single market unchanged; identical to `none` for that group.
- **Timezone consistency** — both `created_at` and `resolved_at` are stored timezone-aware; direct `<=` comparison is safe.
- **Over-merging** (regex collapses topically-different questions into one group) — accepted risk for v1; the regex targets explicit date phrases only, so collisions require the questions to differ *only* in dates. A diagnostic script can be run post-hoc to dump groups for manual review if false positives are suspected.

## Testing

`tests/test_selection.py`:

- `test_template_key_strips_iso_dates`
- `test_template_key_strips_month_name_dates`
- `test_template_key_strips_week_of_phrase`
- `test_template_key_strips_short_dates`
- `test_select_markets_none_returns_input`
- `test_select_markets_singleton_group_unchanged`
- `test_earliest_created_same_day_batch_picks_smallest_deadline`
- `test_earliest_deadline_same_day_batch_picks_smallest_deadline`
- `test_earliest_created_rolling_cohorts_picks_one_per_cohort`
- `test_earliest_deadline_rolling_cohorts_picks_one_per_cohort`
- `test_earliest_created_recurring_picks_each_occurrence`
- `test_eligibility_blocks_overlapping_sibling`

`tests/test_engine.py` (or extension to existing test file):

- `test_run_backtest_with_selection_writes_fewer_rows_than_none`
- `test_run_backtest_label_includes_selection_suffix`
- `test_run_all_strategies_produces_expected_combo_count` (asserts 3× the prior count)

## Out of scope

- Dashboard split of `entry__selection` strategy labels into separate columns
- Storing `endDate` from the Gamma API on the `Market` model
- LLM/embedding-based grouping
- Cross-template "topical" grouping (e.g. recognizing "Israel strikes Gaza" and "Will Israel strike Gaza" as the same event)
