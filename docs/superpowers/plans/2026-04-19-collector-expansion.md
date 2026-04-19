# Collector Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand the collector to ingest every resolved Polymarket Yes/No market back to 2020 — including negRisk sub-markets and previously-discarded categories — while keeping the "nothing ever happens" thesis (backtester + dashboard) strictly on simple independent binaries only. Backfill price history for the ~90% of stored markets that have zero snapshots.

**Architecture:** Two new columns on `markets` (`is_neg_risk`, `event_id`). The collector stops rejecting negRisk markets and classifies via Gamma API tags first. A single `thesis_markets(session)` helper centralises the `is_neg_risk == False` gate that the backtester and dashboard apply to every `Market` query. A new async price-history fetcher (bounded `Semaphore(5)`) runs both as a per-ingest-run backfill budget and as a dedicated bulk CLI.

**Tech Stack:** Python 3, SQLAlchemy 2.0 ORM, SQLite, httpx (sync + async), asyncio, pytest. Package manager: `uv`.

**Design spec:** [docs/superpowers/specs/2026-04-19-collector-expansion-design.md](../specs/2026-04-19-collector-expansion-design.md)

**Verified Gamma API field locations** (from `curl` of live `/markets?include_tag=true`):
- `raw["negRisk"]` → `True`/`False`/absent. Top-level.
- `raw["events"][0]["id"]` → string event id (e.g. `"903193"`). Present on both negRisk and non-negRisk markets.
- `raw["tags"]` → list of tag dicts, each with `label`, `slug`. **Only returned when the request includes `include_tag=true`**. Never on `events[0].tags` (that field exists but is `None`).
- `raw["category"]` → often `None` now; tags are the primary classification signal.

---

## File Map

### Created
- `src/storage/reset_markets.py` — one-shot drop-and-recreate of `markets` + `price_snapshots`
- `src/storage/queries.py` — `thesis_markets(session)` helper
- `src/collector/backfill_runner.py` — bulk price-history catchup CLI
- `tests/test_queries.py` — `thesis_markets` behaviour
- `tests/test_price_history_async.py` — async fetcher (concurrency bound, backoff, failure isolation)
- `tests/test_backfill_runner.py` — bulk backfill CLI end-to-end with mocks

### Modified
- `src/storage/models.py` — add `is_neg_risk`, `event_id` columns on `Market`
- `src/collector/polymarket_api.py` — drop `negRisk` rejection, extract new fields, pass `include_tag=true`
- `src/collector/categories.py` — add `api_tags` parameter, tag-first classification, rename `"other"` → `"misc"`, expand keyword patterns
- `src/collector/price_history.py` — add `fetch_price_history_async` + `fetch_price_histories_concurrent`
- `src/collector/runner.py` — drop default category filter, add per-run `--backfill-limit` pass
- `src/backtester/engine.py` — route `run_backtest` through `thesis_markets`
- `src/dashboard/app.py` — route every `Market` query through `thesis_markets`
- `tests/test_polymarket_api.py` — new negRisk/event_id/tags fixtures; old negRisk-rejection test inverted
- `tests/test_categories.py` — new tag-based cases; `"other"` → `"misc"`
- `tests/test_engine.py` — one negRisk + one normal seeded, only normal appears in results

### Unchanged (load-bearing — do NOT modify)
- `src/collector/polygon_chain.py` — on-chain enrichment; not part of this change
- `src/backtester/strategies.py`, `src/backtester/selection.py`, `src/backtester/metrics.py` — strategies unchanged
- `src/live/` — separate subsystem
- `tests/conftest.py` — fixtures already give in-memory SQLite

---

## Task 1: Add schema columns and migration script

**Files:**
- Modify: `src/storage/models.py:15-34`
- Create: `src/storage/reset_markets.py`
- Modify: `tests/test_models.py`

- [ ] **Step 1: Write failing tests for new columns**

Append to `tests/test_models.py` (create if the file is empty or add at end):

```python
from datetime import datetime, timezone

from src.storage.models import Market


def test_market_has_neg_risk_columns(session):
    m = Market(
        id="0xtest_neg",
        question="Will X happen?",
        category="political",
        no_token_id="tok",
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        is_neg_risk=True,
        event_id="12345",
    )
    session.add(m)
    session.commit()

    roundtrip = session.query(Market).filter_by(id="0xtest_neg").one()
    assert roundtrip.is_neg_risk is True
    assert roundtrip.event_id == "12345"


def test_market_neg_risk_defaults_false(session):
    m = Market(
        id="0xtest_default",
        question="Will X happen?",
        category="political",
        no_token_id="tok",
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    session.add(m)
    session.commit()

    roundtrip = session.query(Market).filter_by(id="0xtest_default").one()
    assert roundtrip.is_neg_risk is False
    assert roundtrip.event_id is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_models.py::test_market_has_neg_risk_columns tests/test_models.py::test_market_neg_risk_defaults_false -v`
Expected: FAIL — `TypeError: 'is_neg_risk' is an invalid keyword argument for Market` (or AttributeError).

- [ ] **Step 3: Add columns to the Market model**

In `src/storage/models.py`, add `Boolean` to the imports from `sqlalchemy` and add the two new columns on `Market`. Final imports and the top of the `Market` class should look like:

```python
from datetime import datetime, timezone

from sqlalchemy import String, Float, DateTime, Text, ForeignKey, Integer, Boolean
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Market(Base):
    __tablename__ = "markets"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    question: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String)
    no_token_id: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution: Mapped[str | None] = mapped_column(String, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_neg_risk: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    event_id: Mapped[str | None] = mapped_column(String, nullable=True)

    # ...relationships unchanged...
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_models.py -v`
Expected: PASS for the two new tests; all pre-existing tests pass.

- [ ] **Step 5: Create the migration script**

Create `src/storage/reset_markets.py`:

```python
"""One-shot migration: drop and recreate markets + price_snapshots only.

Preserves backtest_results and positions. Polymarket conditionIds are
deterministic, so old BacktestResult.market_id values remain valid after
re-collection.

Usage:
    uv run python -m src.storage.reset_markets
"""
import sys

from src.storage.db import get_engine
from src.storage.models import Base, Market, PriceSnapshot


def reset(db_path: str | None = None) -> None:
    engine = get_engine(db_path)
    PriceSnapshot.__table__.drop(engine, checkfirst=True)
    Market.__table__.drop(engine, checkfirst=True)
    Base.metadata.create_all(engine)
    engine.dispose()
    print("Reset complete: dropped + recreated markets and price_snapshots.")


if __name__ == "__main__":
    db_path = sys.argv[1] if len(sys.argv) > 1 else None
    reset(db_path)
```

- [ ] **Step 6: Smoke-test the migration script**

Run: `uv run python -c "import tempfile, os; from src.storage.reset_markets import reset; f = tempfile.NamedTemporaryFile(suffix='.db', delete=False); f.close(); reset(f.name); reset(f.name); os.unlink(f.name); print('idempotent OK')"`
Expected: prints "Reset complete" twice then "idempotent OK".

- [ ] **Step 7: Commit**

```bash
git add src/storage/models.py src/storage/reset_markets.py tests/test_models.py
git commit -m "feat(storage): add is_neg_risk + event_id columns; add reset_markets migration"
```

---

## Task 2: Extract is_neg_risk and event_id in the parser; lift the negRisk rejection

**Files:**
- Modify: `src/collector/polymarket_api.py:30-110`
- Modify: `tests/test_polymarket_api.py`

- [ ] **Step 1: Update existing test fixtures and add new ones**

In `tests/test_polymarket_api.py`, replace the existing `test_parse_market_skips_neg_risk` test and add three new tests. The test file should end up with these additions (keeping all other existing tests untouched):

Delete the old test:
```python
def test_parse_market_skips_neg_risk():
    market = {**SAMPLE_GAMMA_MARKET, "negRisk": True}
    assert parse_market(market) is None
```

Add in its place:
```python
SAMPLE_NEG_RISK_MARKET = {
    "id": "5555555",
    "conditionId": "0xnegrisk1",
    "slug": "will-trump-win-2024",
    "question": "Will Donald Trump win the 2024 US Presidential Election?",
    "outcomes": json.dumps(["Yes", "No"]),
    "outcomePrices": json.dumps(["1", "0"]),
    "clobTokenIds": json.dumps(["tok_yes", "tok_no"]),
    "active": False,
    "closed": True,
    "createdAt": "2024-01-01T00:00:00.000000Z",
    "closedTime": "2024-11-06 12:00:00+00",
    "category": None,
    "negRisk": True,
    "events": [{"id": "903193", "slug": "presidential-election-winner-2024"}],
    "tags": [
        {"label": "Politics", "slug": "politics"},
        {"label": "US Election", "slug": "us-presidential-election"},
    ],
}


def test_parse_market_accepts_neg_risk():
    result = parse_market(SAMPLE_NEG_RISK_MARKET)
    assert result is not None
    assert result["is_neg_risk"] is True
    assert result["event_id"] == "903193"
    assert result["resolution"] == "Yes"


def test_parse_market_default_not_neg_risk():
    result = parse_market(SAMPLE_GAMMA_MARKET)
    assert result is not None
    assert result["is_neg_risk"] is False


def test_parse_market_extracts_event_id_when_present():
    market = {
        **SAMPLE_GAMMA_MARKET,
        "events": [{"id": "4690", "slug": "event-slug"}],
    }
    result = parse_market(market)
    assert result["event_id"] == "4690"


def test_parse_market_event_id_none_when_no_events():
    result = parse_market(SAMPLE_GAMMA_MARKET)
    assert result["event_id"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_polymarket_api.py -v`
Expected: FAIL — `test_parse_market_accepts_neg_risk` returns None because of current `if raw.get("negRisk"): return None`; the event_id tests fail with `KeyError: 'event_id'`.

- [ ] **Step 3: Update `_parse_market_common` to extract the new fields and drop the negRisk rejection**

Replace the body of `_parse_market_common` in `src/collector/polymarket_api.py`:

```python
def _parse_market_common(raw: dict) -> dict | None:
    """Shared parsing for Yes/No binary markets (including negRisk sub-markets).

    Returns the common fields (no resolution/resolved_at) or None if the
    market is multi-outcome or non-Yes-No. Callers layer resolution-specific
    fields on top. negRisk markets are kept — each sub-market is individually
    a Yes/No binary. Callers can filter them downstream via Market.is_neg_risk.
    """
    if not all(k in raw for k in ("outcomes", "outcomePrices", "clobTokenIds")):
        return None

    outcomes = json.loads(raw["outcomes"])
    prices = json.loads(raw["outcomePrices"])
    clob_token_ids = json.loads(raw["clobTokenIds"])

    if len(outcomes) != 2:
        return None

    outcome_set = {o.lower() for o in outcomes}
    if outcome_set != {"yes", "no"}:
        return None

    try:
        no_idx = outcomes.index("No")
    except ValueError:
        no_idx = 1

    no_token_id = clob_token_ids[no_idx]

    created_at = datetime.fromisoformat(raw["createdAt"].replace("Z", "+00:00"))
    end_date = _parse_datetime(raw.get("endDate"))

    api_tags = raw.get("tags") or []
    category = classify_market(raw["question"], raw.get("category"), api_tags)
    slug = raw.get("slug", "")

    is_neg_risk = bool(raw.get("negRisk"))
    events = raw.get("events") or []
    event_id = events[0].get("id") if events else None
    if event_id is not None:
        event_id = str(event_id)

    return {
        "id": raw["conditionId"],
        "question": raw["question"],
        "category": category,
        "no_token_id": no_token_id,
        "created_at": created_at,
        "end_date": end_date,
        "source_url": f"https://polymarket.com/market/{slug}" if slug else None,
        "is_neg_risk": is_neg_risk,
        "event_id": event_id,
        # raw outcomes/prices retained so resolution-aware callers can use them
        "_outcomes": outcomes,
        "_prices": prices,
    }
```

Note: `classify_market` now takes a third argument `api_tags`. That change lands in Task 4 — for Task 2 the call with three arguments will fail. To keep this commit green, extract a helper shim: define a local adapter at the top of the file:

```python
# Temporary shim — removed in Task 4 once classify_market takes api_tags directly.
def _classify_with_tags(question: str, api_category: str | None, api_tags: list[dict]) -> str:
    return classify_market(question, api_category)
```

…and call `_classify_with_tags(raw["question"], raw.get("category"), api_tags)` inside `_parse_market_common` instead of `classify_market(...)`. Task 4 deletes the shim and calls the real 3-arg `classify_market` directly.

- [ ] **Step 4: Run the collector test suite**

Run: `uv run pytest tests/test_polymarket_api.py -v`
Expected: PASS — all four new tests and all pre-existing tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/collector/polymarket_api.py tests/test_polymarket_api.py
git commit -m "feat(collector): keep negRisk markets, extract event_id and is_neg_risk"
```

---

## Task 3: Pass `include_tag=true` to the Gamma API

**Files:**
- Modify: `src/collector/polymarket_api.py:113-172`
- Modify: `tests/test_polymarket_api.py`

- [ ] **Step 1: Write a failing test asserting the parameter is sent**

Add this to `tests/test_polymarket_api.py`:

```python
@patch("src.collector.polymarket_api.time.sleep")
@patch("src.collector.polymarket_api.httpx.Client")
def test_fetch_sends_include_tag_true(mock_client_cls, mock_sleep):
    """include_tag=true must be passed so raw['tags'] is populated."""
    mock_response = MagicMock()
    mock_response.json.side_effect = [[_make_api_market("id_a")], []]
    mock_response.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.get.return_value = mock_response
    mock_client_cls.return_value = mock_client

    fetch_resolved_markets()

    call_params = mock_client.get.call_args_list[0][1]["params"]
    assert call_params["include_tag"] == "true"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_polymarket_api.py::test_fetch_sends_include_tag_true -v`
Expected: FAIL — `KeyError: 'include_tag'`.

- [ ] **Step 3: Add the parameter to the request**

In `src/collector/polymarket_api.py`, inside `fetch_resolved_markets`, add `"include_tag": "true"` to the `params` dict:

```python
        params = {
            "closed": "true",
            "resolved": "true",
            "limit": MARKETS_PER_PAGE,
            "offset": offset,
            "order": "createdAt",
            "ascending": "false",
            "include_tag": "true",
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_polymarket_api.py -v`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add src/collector/polymarket_api.py tests/test_polymarket_api.py
git commit -m "feat(collector): request include_tag=true so classification has tag data"
```

---

## Task 4: Tag-first classification, misc rename, keyword expansion

**Files:**
- Modify: `src/collector/categories.py`
- Modify: `src/collector/polymarket_api.py` (remove the `_classify_with_tags` shim from Task 2)
- Modify: `tests/test_categories.py`

- [ ] **Step 1: Write failing tests**

Replace the contents of `tests/test_categories.py` with:

```python
from src.collector.categories import classify_market


# ---- Keyword-based classification (unchanged behaviour) ----

def test_geopolitical_classification():
    assert classify_market("Will Russia invade Finland by 2025?", None, None) == "geopolitical"
    assert classify_market("Will China blockade Taiwan?", None, None) == "geopolitical"
    assert classify_market("Will NATO deploy troops to Ukraine?", None, None) == "geopolitical"
    assert classify_market("Will Iran strike Israel before June?", None, None) == "geopolitical"


def test_political_classification():
    assert classify_market("Will Congress pass the TikTok ban?", None, None) == "political"
    assert classify_market("Will Biden sign the infrastructure bill?", None, None) == "political"
    assert classify_market("Will the Senate confirm the nominee?", None, None) == "political"
    assert classify_market("Will there be a government shutdown?", None, None) == "political"


def test_culture_classification():
    assert classify_market("Will Taylor Swift announce retirement?", None, None) == "culture"
    assert classify_market("Who will win Best Picture at the Oscars?", None, None) == "culture"
    assert classify_market("Will the Super Bowl halftime show feature Drake?", None, None) == "culture"
    assert classify_market("Will Elon Musk appear on SNL again?", None, None) == "culture"


# ---- API category fallback (second priority) ----

def test_category_from_api_tag():
    assert classify_market("Some unclear question", "Politics", None) == "political"
    assert classify_market("Some unclear question", "Pop Culture", None) == "culture"
    assert classify_market("Some unclear question", "Geopolitics", None) == "geopolitical"


def test_case_insensitive():
    assert classify_market("WILL NATO EXPAND?", None, None) == "geopolitical"
    assert classify_market("will congress act?", None, None) == "political"


# ---- "misc" fallback (renamed from "other") ----

def test_misc_fallback():
    assert classify_market("Will Bitcoin hit $100k?", None, None) == "misc"
    assert classify_market("What will the weather be?", None, None) == "misc"


# ---- Tag-first classification (new priority 1) ----

def test_tag_classification_elections():
    tags = [{"label": "Elections"}, {"label": "Trump"}]
    # Even a non-political question resolves via tags.
    assert classify_market("Will the arcane thing occur?", None, tags) == "political"


def test_tag_classification_geopolitics():
    tags = [{"label": "Geopolitics"}]
    assert classify_market("Ambiguous question about pandas?", None, tags) == "geopolitical"


def test_tag_longest_match_wins():
    # "us politics" is longer than "politics"; longest-match-wins via sorted TAG_MAP.
    tags = [{"label": "US Politics"}]
    assert classify_market("Ambiguous.", None, tags) == "political"


def test_tag_trumps_keyword_fallback():
    # Question would match the "culture" keyword "super bowl", but Sports tag wins.
    tags = [{"label": "Sports"}]
    assert classify_market("Super Bowl halftime predictions?", None, tags) == "culture"


def test_falls_through_tags_to_api_category():
    # No tag hit, but api_category resolves.
    tags = [{"label": "unrelated-label"}]
    assert classify_market("Random question.", "Politics", tags) == "political"


def test_falls_through_tags_and_category_to_keywords():
    tags = [{"label": "unrelated-label"}]
    assert classify_market("Will Russia invade Finland?", "Random", tags) == "geopolitical"


def test_empty_tag_list_behaves_like_none():
    assert classify_market("Will Congress act?", None, []) == "political"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_categories.py -v`
Expected: FAIL — `TypeError: classify_market() takes 2 positional arguments but 3 were given` on every test.

- [ ] **Step 3: Rewrite `src/collector/categories.py`**

Replace the file with:

```python
import re

# API tag/category label -> our category (longest match wins)
TAG_MAP: dict[str, str] = {
    "geopolitics": "geopolitical",
    "us politics": "political",
    "politics": "political",
    "elections": "political",
    "world": "geopolitical",
    "pop culture": "culture",
    "entertainment": "culture",
    "sports": "culture",
    "celebrities": "culture",
}

# Keyword patterns for classification from question text (fallback).
CATEGORY_PATTERNS: dict[str, list[str]] = {
    "geopolitical": [
        r"\b(invade|invasion|blockade|nato|troops|missile|nuclear|sanctions|annex)\b",
        r"\b(russia|china|iran|ukraine|taiwan|israel|north korea|syria|gaza|hamas|hezbollah)\b",
        r"\b(war|conflict|military|airstrike|deploy|ceasefire|treaty|coup|regime)\b",
        r"\b(eu|european union|brexit|g7|g20|un security council|un general assembly)\b",
    ],
    "political": [
        r"\b(congress|senate|house|parliament|legislation|bill|law|act)\b",
        r"\b(president|governor|mayor|election|vote|ballot|impeach|primary|primaries|caucus)\b",
        r"\b(government shutdown|executive order|veto|filibuster|confirm|cabinet|scotus|supreme court)\b",
        r"\b(biden|trump|harris|desantis|obama|clinton|pence|democrat|republican|gop|maga)\b",
        r"\b(covid|pandemic|vaccine mandate|mask mandate)\b",
    ],
    "culture": [
        r"\b(oscar|grammy|emmy|tony|golden globe|award show|best picture)\b",
        r"\b(super bowl|world series|nba|nfl|world cup|olympics)\b",
        r"\b(taylor swift|beyonce|drake|kanye|elon musk|celebrity)\b",
        r"\b(movie|album|tour|concert|halftime|snl|netflix|spotify)\b",
        r"\b(retire|comeback|announce|release|premiere)\b",
    ],
}


def _match_tag_map(text: str | None) -> str | None:
    if not text:
        return None
    text_lower = text.lower()
    # Sort by length (longest first) so "us politics" beats "politics".
    for tag_key in sorted(TAG_MAP.keys(), key=len, reverse=True):
        if tag_key in text_lower:
            return TAG_MAP[tag_key]
    return None


def classify_market(
    question: str,
    api_category: str | None,
    api_tags: list[dict] | None,
) -> str:
    """Classify a market by (in priority order): API tags, API category, keywords.

    api_tags is a list of dicts with at least a 'label' key, as returned by the
    Gamma API's /markets endpoint when include_tag=true. Falls back to 'misc'
    when nothing matches.
    """
    # 1. Walk API tag labels through TAG_MAP (longest match wins per tag).
    for tag in api_tags or []:
        label = tag.get("label") if isinstance(tag, dict) else None
        match = _match_tag_map(label)
        if match:
            return match

    # 2. Fall back to API category.
    match = _match_tag_map(api_category)
    if match:
        return match

    # 3. Fall back to keyword regex on the question text.
    question_lower = question.lower()
    for category, patterns in CATEGORY_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, question_lower):
                return category

    return "misc"
```

- [ ] **Step 4: Remove the Task-2 shim from `polymarket_api.py`**

In `src/collector/polymarket_api.py`, delete the `_classify_with_tags` shim added in Task 2 and replace the call inside `_parse_market_common` with a direct three-argument call:

```python
    api_tags = raw.get("tags") or []
    category = classify_market(raw["question"], raw.get("category"), api_tags)
```

- [ ] **Step 5: Run the test suite to verify everything passes**

Run: `uv run pytest tests/test_categories.py tests/test_polymarket_api.py -v`
Expected: PASS.

Also run the full suite briefly to spot collateral breakage from the `"other"` → `"misc"` rename:

Run: `uv run pytest -x --ignore=tests/test_live_runner.py -q`
Expected: PASS. If any other test references the string `"other"` as a category, update those tests to `"misc"` in the same commit.

- [ ] **Step 6: Commit**

```bash
git add src/collector/categories.py src/collector/polymarket_api.py tests/test_categories.py
git commit -m "feat(collector): tag-first classification; rename 'other' -> 'misc'"
```

---

## Task 5: Thesis-markets query helper

**Files:**
- Create: `src/storage/queries.py`
- Create: `tests/test_queries.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_queries.py`:

```python
from datetime import datetime, timezone

from src.storage.models import Market
from src.storage.queries import thesis_markets


def _make_market(id: str, is_neg_risk: bool, category: str = "political") -> Market:
    return Market(
        id=id,
        question=f"Question {id}",
        category=category,
        no_token_id=f"tok_{id}",
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        resolution="No",
        is_neg_risk=is_neg_risk,
    )


def test_thesis_markets_excludes_neg_risk(session):
    session.add_all([
        _make_market("a", False),
        _make_market("b", True),
        _make_market("c", False),
    ])
    session.commit()

    ids = {m.id for m in thesis_markets(session).all()}
    assert ids == {"a", "c"}


def test_thesis_markets_composes_with_filter(session):
    session.add_all([
        _make_market("a", False, category="political"),
        _make_market("b", False, category="geopolitical"),
        _make_market("c", True, category="political"),
    ])
    session.commit()

    q = thesis_markets(session).filter(Market.category == "political")
    ids = {m.id for m in q.all()}
    assert ids == {"a"}


def test_thesis_markets_empty_db(session):
    assert thesis_markets(session).all() == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_queries.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.storage.queries'`.

- [ ] **Step 3: Create the helper**

Create `src/storage/queries.py`:

```python
"""Shared query helpers for Market access.

The thesis_markets helper centralises the is_neg_risk==False filter that the
'nothing ever happens' backtester and dashboard apply to every Market query.
negRisk sub-markets are mutually exclusive by construction, which violates the
thesis's independence assumption — so they are excluded from thesis queries by
default. Collection still ingests them; analysis that wants them must query
the Market model directly.
"""
from sqlalchemy.orm import Query, Session

from src.storage.models import Market


def thesis_markets(session: Session) -> Query:
    """Query over Market rows eligible for the 'nothing ever happens' thesis."""
    return session.query(Market).filter(Market.is_neg_risk == False)  # noqa: E712
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_queries.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/storage/queries.py tests/test_queries.py
git commit -m "feat(storage): add thesis_markets helper for is_neg_risk gating"
```

---

## Task 6: Gate backtester engine through `thesis_markets`

**Files:**
- Modify: `src/backtester/engine.py:63-67`
- Modify: `tests/test_engine.py`

- [ ] **Step 1: Add a failing test asserting negRisk exclusion**

Append to `tests/test_engine.py`:

```python
def test_run_backtest_excludes_neg_risk_markets(session):
    """Backtest results should skip markets with is_neg_risk=True."""
    normal = Market(
        id="0xnormal",
        question="Normal market",
        category="political",
        no_token_id="tok_n",
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        resolved_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
        resolution="No",
        is_neg_risk=False,
    )
    neg = Market(
        id="0xneg",
        question="NegRisk sub-market",
        category="political",
        no_token_id="tok_ng",
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        resolved_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
        resolution="No",
        is_neg_risk=True,
        event_id="evt-42",
    )
    session.add_all([normal, neg])
    session.flush()

    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    for mid in ("0xnormal", "0xneg"):
        for i, price in enumerate([0.9, 0.85, 0.8]):
            session.add(PriceSnapshot(
                market_id=mid,
                timestamp=base + timedelta(hours=i * 24),
                no_price=price,
                source="api",
            ))
    session.commit()

    run_id = run_backtest(session, strategy_name="at_creation", params={}, categories=None)
    results = session.query(BacktestResult).filter_by(run_id=run_id).all()
    assert len(results) == 1
    assert results[0].market_id == "0xnormal"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_engine.py::test_run_backtest_excludes_neg_risk_markets -v`
Expected: FAIL — two result rows, not one.

- [ ] **Step 3: Route `run_backtest` through `thesis_markets`**

In `src/backtester/engine.py`, change the imports and the market-selection query. Replace lines 3-8 with:

```python
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.storage.db import get_engine, get_session
from src.storage.models import Market, PriceSnapshot, BacktestResult
from src.storage.queries import thesis_markets
from src.backtester.strategies import STRATEGIES
```

Replace the market-fetch block inside `run_backtest` (currently lines 63-66) with:

```python
    query = thesis_markets(session).filter(Market.resolution.isnot(None))
    if categories:
        query = query.filter(Market.category.in_(categories))
    markets = query.all()
    markets = _select_markets(markets, selection_mode)
```

(We switch from `session.execute(select(...)).scalars().all()` to `query.all()` because `thesis_markets` returns a legacy `Query`, not a 2.0-style `select()`. Remove the unused `from sqlalchemy import select` import if nothing else uses it — check first.)

- [ ] **Step 4: Run the engine tests**

Run: `uv run pytest tests/test_engine.py -v`
Expected: PASS (all, including the new neg-risk exclusion test).

- [ ] **Step 5: Commit**

```bash
git add src/backtester/engine.py tests/test_engine.py
git commit -m "feat(backtester): route Market queries through thesis_markets helper"
```

---

## Task 7: Gate dashboard queries through `thesis_markets`

**Files:**
- Modify: `src/dashboard/app.py` (lines 140, 160, 199, 470, 637)

- [ ] **Step 1: Read the dashboard file and confirm the five query sites**

Run: `uv run python -c "import re; t=open('src/dashboard/app.py').read(); print(list(re.finditer(r'session.query\\(Market\\)', t)))"`
Expected: five matches at positions corresponding to the five lines listed.

- [ ] **Step 2: Add the import**

At the top of `src/dashboard/app.py`, alongside the existing `from src.storage.models import ...`, add:

```python
from src.storage.queries import thesis_markets
```

- [ ] **Step 3: Replace every `session.query(Market)` with `thesis_markets(session)`**

Use find-and-replace for the five occurrences. For each site, replace the literal `session.query(Market)` with `thesis_markets(session)`. The surrounding `.filter(...)`/`.order_by(...)` chain is untouched.

Example transform (line 140):
```python
# before
base_q = session.query(Market).filter(
    Market.resolution.isnot(None),
    Market.category.in_(selected_categories),
)
# after
base_q = thesis_markets(session).filter(
    Market.resolution.isnot(None),
    Market.category.in_(selected_categories),
)
```

Apply identically at lines 160, 199, 470, 637.

- [ ] **Step 4: Verify syntactic correctness**

Run: `uv run python -c "import ast; ast.parse(open('src/dashboard/app.py').read()); print('ok')"`
Expected: "ok".

- [ ] **Step 5: Sanity-check with pytest (dashboard has no direct tests; rely on collection)**

Run: `uv run pytest -q`
Expected: PASS — nothing new passes/fails, just confirming no import-time errors.

- [ ] **Step 6: Commit**

```bash
git add src/dashboard/app.py
git commit -m "feat(dashboard): route Market queries through thesis_markets helper"
```

---

## Task 8: Async price-history fetcher

**Files:**
- Modify: `src/collector/price_history.py`
- Create: `tests/test_price_history_async.py`

- [ ] **Step 1: Write failing tests for the async fetcher**

Create `tests/test_price_history_async.py`:

```python
import asyncio
from unittest.mock import patch

import httpx
import pytest

from src.collector.price_history import fetch_price_histories_concurrent


def _ok_response(points: list[tuple[int, float]]) -> httpx.Response:
    return httpx.Response(
        200,
        json={"history": [{"t": t, "p": p} for t, p in points]},
    )


@pytest.mark.asyncio
async def test_fetches_multiple_markets():
    pairs = [("tok_a", "mkt_a"), ("tok_b", "mkt_b"), ("tok_c", "mkt_c")]

    def handler(request: httpx.Request) -> httpx.Response:
        token = request.url.params.get("market")
        return _ok_response([(1_700_000_000, 0.5)]) if token else _ok_response([])

    transport = httpx.MockTransport(handler)
    with patch("httpx.AsyncClient", lambda timeout=30: httpx.AsyncClient(transport=transport, timeout=timeout)):
        results = await fetch_price_histories_concurrent(pairs, max_concurrency=2)

    assert set(results.keys()) == {"mkt_a", "mkt_b", "mkt_c"}
    for snaps in results.values():
        assert len(snaps) == 1
        assert snaps[0]["no_price"] == 0.5


@pytest.mark.asyncio
async def test_respects_concurrency_bound():
    in_flight = 0
    peak = 0
    pairs = [(f"tok_{i}", f"mkt_{i}") for i in range(10)]

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.02)
        in_flight -= 1
        return _ok_response([(1_700_000_000, 0.5)])

    transport = httpx.MockTransport(handler)
    with patch("httpx.AsyncClient", lambda timeout=30: httpx.AsyncClient(transport=transport, timeout=timeout)):
        await fetch_price_histories_concurrent(pairs, max_concurrency=3)

    assert peak <= 3
    assert peak > 0


@pytest.mark.asyncio
async def test_backoff_on_429_then_succeeds():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={"error": "rate limited"})
        return _ok_response([(1_700_000_000, 0.7)])

    transport = httpx.MockTransport(handler)
    with patch("httpx.AsyncClient", lambda timeout=30: httpx.AsyncClient(transport=transport, timeout=timeout)):
        with patch("src.collector.price_history.asyncio.sleep", new=lambda _: asyncio.sleep(0)):
            results = await fetch_price_histories_concurrent([("tok", "mkt")], max_concurrency=1)

    assert calls["n"] == 2
    assert len(results["mkt"]) == 1
    assert results["mkt"][0]["no_price"] == 0.7


@pytest.mark.asyncio
async def test_persistent_5xx_yields_empty_list():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(500, json={"error": "boom"})

    transport = httpx.MockTransport(handler)
    with patch("httpx.AsyncClient", lambda timeout=30: httpx.AsyncClient(transport=transport, timeout=timeout)):
        with patch("src.collector.price_history.asyncio.sleep", new=lambda _: asyncio.sleep(0)):
            results = await fetch_price_histories_concurrent([("tok", "mkt")], max_concurrency=1)

    assert calls["n"] == 3  # three attempts
    assert results["mkt"] == []


@pytest.mark.asyncio
async def test_failure_isolation():
    def handler(request: httpx.Request) -> httpx.Response:
        token = request.url.params.get("market")
        if token == "tok_bad":
            return httpx.Response(500, json={"error": "boom"})
        return _ok_response([(1_700_000_000, 0.5)])

    transport = httpx.MockTransport(handler)
    with patch("httpx.AsyncClient", lambda timeout=30: httpx.AsyncClient(transport=transport, timeout=timeout)):
        with patch("src.collector.price_history.asyncio.sleep", new=lambda _: asyncio.sleep(0)):
            results = await fetch_price_histories_concurrent(
                [("tok_bad", "mkt_bad"), ("tok_ok", "mkt_ok")],
                max_concurrency=2,
            )

    assert results["mkt_bad"] == []
    assert len(results["mkt_ok"]) == 1
```

Also add `pytest-asyncio` to dev deps if not present. Check `pyproject.toml`:

Run: `grep -c pytest-asyncio pyproject.toml`
If 0, add it:

```bash
uv add --dev pytest-asyncio
```

Then add to `pyproject.toml` under `[tool.pytest.ini_options]` (create the section if absent):

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_price_history_async.py -v`
Expected: FAIL — `AttributeError: module 'src.collector.price_history' has no attribute 'fetch_price_histories_concurrent'`.

- [ ] **Step 3: Implement the async fetcher**

Append to `src/collector/price_history.py` (keep the existing sync code untouched):

```python
import asyncio


async def fetch_price_history_async(
    client: httpx.AsyncClient,
    token_id: str,
    market_id: str,
) -> list[dict]:
    """Fetch price history for one market. Returns [] on persistent failure."""
    params = {"market": token_id, "interval": "max", "fidelity": 60}
    delays = [1.0, 2.0, 4.0]
    for attempt, delay in enumerate(delays):
        try:
            response = await client.get(f"{CLOB_API_BASE}/prices-history", params=params)
        except (httpx.TimeoutException, httpx.TransportError):
            if attempt < len(delays) - 1:
                await asyncio.sleep(delay)
                continue
            return []

        if response.status_code == 429 or 500 <= response.status_code < 600:
            if attempt < len(delays) - 1:
                await asyncio.sleep(delay)
                continue
            return []

        if response.status_code != 200:
            return []

        return parse_price_history(response.json(), market_id)
    return []


async def fetch_price_histories_concurrent(
    token_market_pairs: list[tuple[str, str]],
    max_concurrency: int = 5,
) -> dict[str, list[dict]]:
    """Fetch many price histories under a bounded Semaphore. Progress every 100."""
    results: dict[str, list[dict]] = {}
    semaphore = asyncio.Semaphore(max_concurrency)
    completed = {"n": 0}
    total = len(token_market_pairs)

    async with httpx.AsyncClient(timeout=30) as client:
        async def one(token_id: str, market_id: str):
            async with semaphore:
                snapshots = await fetch_price_history_async(client, token_id, market_id)
            results[market_id] = snapshots
            completed["n"] += 1
            if completed["n"] % 100 == 0:
                print(f"  Price history: {completed['n']}/{total} markets")

        await asyncio.gather(*(one(t, m) for t, m in token_market_pairs))

    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_price_history_async.py -v`
Expected: PASS (all five).

- [ ] **Step 5: Commit**

```bash
git add src/collector/price_history.py tests/test_price_history_async.py pyproject.toml uv.lock
git commit -m "feat(collector): async bounded-concurrency price-history fetcher"
```

---

## Task 9: Per-run price-history backfill in `runner.py`

**Files:**
- Modify: `src/collector/runner.py`

- [ ] **Step 1: Add imports and the backfill helper**

At the top of `src/collector/runner.py`, add:

```python
import asyncio
from src.collector.price_history import (
    fetch_price_history,
    fetch_price_histories_concurrent,
)
```

(Replace the existing `from src.collector.price_history import fetch_price_history` line.)

- [ ] **Step 2: Extract the backfill pass as a helper**

After `store_price_snapshots` and before `collect`, add:

```python
def backfill_missing_price_histories(
    session: Session,
    limit: int | None,
    max_concurrency: int = 5,
) -> int:
    """Fetch price snapshots for markets that have zero snapshot rows.

    Returns the number of markets for which at least one snapshot was stored.
    limit=None fetches all missing; limit=0 is rejected by the caller before
    this is invoked.
    """
    missing_q = (
        session.query(Market.id, Market.no_token_id)
        .outerjoin(PriceSnapshot, Market.id == PriceSnapshot.market_id)
        .filter(PriceSnapshot.id.is_(None))
        .distinct()
    )
    if limit is not None:
        missing_q = missing_q.limit(limit)
    missing = missing_q.all()

    if not missing:
        print("Backfill: no markets missing price history.")
        return 0

    print(f"Backfill: fetching price history for {len(missing)} markets (concurrency={max_concurrency})...")
    pairs = [(no_token_id, market_id) for market_id, no_token_id in missing]
    results = asyncio.run(
        fetch_price_histories_concurrent(pairs, max_concurrency=max_concurrency)
    )

    stored = 0
    for i, (market_id, snaps) in enumerate(results.items(), start=1):
        if snaps:
            store_price_snapshots(session, snaps, market_id)
            stored += 1
        if i % 50 == 0:
            session.commit()
    session.commit()

    print(f"Backfill: stored snapshots for {stored}/{len(missing)} markets.")
    return stored
```

- [ ] **Step 3: Update `collect()` to accept a backfill budget and invoke the helper**

Change the `collect` signature to add `backfill_limit: int | None = 100` and call the helper after the main loop:

```python
def collect(
    categories: list[str] | None = None,
    limit: int | None = None,
    enrich_onchain: bool = False,
    db_path: str | None = None,
    backfill_limit: int | None = 100,
):
    engine = get_engine(db_path)
    session = get_session(engine)

    existing_ids = set(row[0] for row in session.query(Market.id).all())
    earliest = session.query(func.min(Market.created_at)).scalar()

    end_date_max = None
    if earliest:
        end_date_max = earliest.strftime("%Y-%m-%dT%H:%M:%SZ")
        print(f"Found {len(existing_ids)} existing markets in DB (earliest: {earliest.date()})")
        print(f"Fetching markets created on or before {earliest.date()}...")
    else:
        print("Empty DB, fetching newest markets...")

    markets = fetch_resolved_markets(
        categories=categories, limit=limit, end_date_max=end_date_max
    )
    print(f"Found {len(markets)} markets from API")

    new_count = 0
    skipped_count = 0
    for i, market_data in enumerate(markets):
        is_new = upsert_market(session, market_data)
        if is_new:
            new_count += 1
            session.flush()

            print(f"  [{i+1}/{len(markets)}] NEW {market_data['question'][:60]}...")
            snapshots = []
            for attempt in range(3):
                try:
                    snapshots = fetch_price_history(
                        token_id=market_data["no_token_id"],
                        market_id=market_data["id"],
                    )
                    break
                except (httpx.ReadTimeout, httpx.ConnectTimeout):
                    if attempt < 2:
                        time.sleep(2 ** attempt)
                    else:
                        print(f"    Skipping price history (timeout after 3 attempts)")

            if enrich_onchain:
                onchain = fetch_onchain_prices(
                    no_token_id=market_data["no_token_id"],
                    market_id=market_data["id"],
                    created_at=market_data["created_at"],
                    resolved_at=market_data["resolved_at"],
                )
                snapshots.extend(onchain)

            store_price_snapshots(session, snapshots, market_data["id"])
        else:
            skipped_count += 1

        if (i + 1) % 10 == 0:
            session.commit()

    session.commit()

    if backfill_limit != 0:
        backfill_missing_price_histories(session, limit=backfill_limit)

    session.close()
    engine.dispose()

    print(f"Done. {new_count} new, {skipped_count} skipped (already collected).")
```

- [ ] **Step 4: Update `main()` to expose the new flag and drop the default category filter**

Replace the `main` function with:

```python
def main():
    parser = argparse.ArgumentParser(description="Collect Polymarket data")
    parser.add_argument(
        "--categories",
        type=str,
        default="",
        help="Comma-separated categories (default: '' = no filter)",
    )
    parser.add_argument("--limit", type=int, default=None, help="Max number of markets to fetch")
    parser.add_argument("--enrich-onchain", action="store_true", help="Also fetch on-chain price data from Polygon (slow)")
    parser.add_argument(
        "--backfill-limit",
        type=int,
        default=100,
        help="After ingest, backfill price history for up to N markets with zero snapshots. 0 disables. Use a large number (or -1) to attempt all.",
    )
    args = parser.parse_args()

    categories: list[str] | None
    if args.categories.strip():
        categories = [c.strip() for c in args.categories.split(",") if c.strip()]
    else:
        categories = None

    backfill_limit: int | None = args.backfill_limit
    if backfill_limit is not None and backfill_limit < 0:
        backfill_limit = None  # None = unlimited

    collect(
        categories=categories,
        limit=args.limit,
        enrich_onchain=args.enrich_onchain,
        backfill_limit=backfill_limit,
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Add a lightweight test for the backfill helper**

Append to `tests/test_price_history.py` (create a sensible name if the file exists and uses a different structure):

```python
from datetime import datetime, timezone
from unittest.mock import patch

from src.collector.runner import backfill_missing_price_histories
from src.storage.models import Market, PriceSnapshot


def test_backfill_only_fetches_markets_without_snapshots(session):
    m1 = Market(id="m1", question="Q1", category="political", no_token_id="t1",
                created_at=datetime(2024, 1, 1, tzinfo=timezone.utc))
    m2 = Market(id="m2", question="Q2", category="political", no_token_id="t2",
                created_at=datetime(2024, 1, 1, tzinfo=timezone.utc))
    session.add_all([m1, m2])
    session.add(PriceSnapshot(
        market_id="m1", timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
        no_price=0.5, source="api",
    ))
    session.commit()

    def fake_concurrent(pairs, max_concurrency=5):
        # Capture which markets got requested.
        assert {m for _, m in pairs} == {"m2"}
        return {"m2": [
            {"market_id": "m2", "timestamp": datetime(2024, 2, 1, tzinfo=timezone.utc),
             "no_price": 0.4, "source": "api"},
        ]}

    with patch("src.collector.runner.fetch_price_histories_concurrent",
               side_effect=lambda pairs, max_concurrency=5: fake_concurrent(pairs, max_concurrency)):
        with patch("src.collector.runner.asyncio.run", side_effect=lambda coro: coro.__await__() and None):
            # asyncio.run with a coroutine — easier to directly patch at the call site:
            pass

    # Simpler: patch fetch_price_histories_concurrent as an async function via asyncio.run.
```

Replace that test block with this cleaner version:

```python
import asyncio
from datetime import datetime, timezone
from unittest.mock import patch

from src.collector.runner import backfill_missing_price_histories
from src.storage.models import Market, PriceSnapshot


def test_backfill_only_fetches_markets_without_snapshots(session):
    m1 = Market(id="m1", question="Q1", category="political", no_token_id="t1",
                created_at=datetime(2024, 1, 1, tzinfo=timezone.utc))
    m2 = Market(id="m2", question="Q2", category="political", no_token_id="t2",
                created_at=datetime(2024, 1, 1, tzinfo=timezone.utc))
    session.add_all([m1, m2])
    session.add(PriceSnapshot(
        market_id="m1", timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
        no_price=0.5, source="api",
    ))
    session.commit()

    captured_pairs: list[tuple[str, str]] = []

    async def fake_fetch(pairs, max_concurrency=5):
        captured_pairs.extend(pairs)
        return {m: [
            {"market_id": m, "timestamp": datetime(2024, 2, 1, tzinfo=timezone.utc),
             "no_price": 0.4, "source": "api"},
        ] for _, m in pairs}

    with patch("src.collector.runner.fetch_price_histories_concurrent", fake_fetch):
        stored = backfill_missing_price_histories(session, limit=None)

    assert captured_pairs == [("t2", "m2")]
    assert stored == 1
    # m1 unchanged, m2 now has a snapshot.
    assert session.query(PriceSnapshot).filter_by(market_id="m2").count() == 1
    assert session.query(PriceSnapshot).filter_by(market_id="m1").count() == 1
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/test_price_history.py tests/test_polymarket_api.py -v`
Expected: PASS (all, including the new backfill test).

- [ ] **Step 7: Commit**

```bash
git add src/collector/runner.py tests/test_price_history.py
git commit -m "feat(collector): per-run price-history backfill + no-default-category filter"
```

---

## Task 10: Bulk backfill CLI

**Files:**
- Create: `src/collector/backfill_runner.py`
- Create: `tests/test_backfill_runner.py`

- [ ] **Step 1: Write failing tests for the CLI module**

Create `tests/test_backfill_runner.py`:

```python
from datetime import datetime, timezone
from unittest.mock import patch

from src.collector.backfill_runner import run_backfill
from src.storage.models import Market, PriceSnapshot


def _seed(session, with_snapshot=True):
    m = Market(id="m1", question="Q", category="political", no_token_id="t1",
               created_at=datetime(2024, 1, 1, tzinfo=timezone.utc))
    session.add(m)
    if with_snapshot:
        session.add(PriceSnapshot(
            market_id="m1", timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            no_price=0.5, source="api",
        ))
    session.commit()


def test_default_skips_markets_with_snapshots(session):
    _seed(session, with_snapshot=True)

    async def fake_fetch(pairs, max_concurrency=5):
        assert pairs == []  # nothing missing
        return {}

    with patch("src.collector.backfill_runner.fetch_price_histories_concurrent", fake_fetch):
        stored = run_backfill(session, limit=None, concurrency=5, force=False)

    assert stored == 0


def test_force_refetches_markets_with_snapshots(session):
    _seed(session, with_snapshot=True)

    async def fake_fetch(pairs, max_concurrency=5):
        assert pairs == [("t1", "m1")]
        return {"m1": [
            {"market_id": "m1", "timestamp": datetime(2024, 3, 1, tzinfo=timezone.utc),
             "no_price": 0.3, "source": "api"},
        ]}

    with patch("src.collector.backfill_runner.fetch_price_histories_concurrent", fake_fetch):
        stored = run_backfill(session, limit=None, concurrency=5, force=True)

    assert stored == 1
    assert session.query(PriceSnapshot).filter_by(market_id="m1").count() == 2


def test_limit_respected(session):
    for i in range(3):
        session.add(Market(id=f"m{i}", question="Q", category="political",
                           no_token_id=f"t{i}",
                           created_at=datetime(2024, 1, 1, tzinfo=timezone.utc)))
    session.commit()

    captured: list = []

    async def fake_fetch(pairs, max_concurrency=5):
        captured.extend(pairs)
        return {m: [] for _, m in pairs}

    with patch("src.collector.backfill_runner.fetch_price_histories_concurrent", fake_fetch):
        run_backfill(session, limit=2, concurrency=5, force=False)

    assert len(captured) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_backfill_runner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.collector.backfill_runner'`.

- [ ] **Step 3: Implement the CLI module**

Create `src/collector/backfill_runner.py`:

```python
"""Bulk price-history catchup CLI.

Usage:
    uv run python -m src.collector.backfill_runner                  # all missing
    uv run python -m src.collector.backfill_runner --limit 1000     # cap
    uv run python -m src.collector.backfill_runner --concurrency 10
    uv run python -m src.collector.backfill_runner --force          # re-fetch even markets with existing snapshots
"""
import argparse
import asyncio

from sqlalchemy.orm import Session

from src.collector.price_history import fetch_price_histories_concurrent
from src.collector.runner import store_price_snapshots
from src.storage.db import get_engine, get_session
from src.storage.models import Market, PriceSnapshot


def run_backfill(
    session: Session,
    limit: int | None,
    concurrency: int,
    force: bool,
) -> int:
    if force:
        q = session.query(Market.id, Market.no_token_id)
    else:
        q = (
            session.query(Market.id, Market.no_token_id)
            .outerjoin(PriceSnapshot, Market.id == PriceSnapshot.market_id)
            .filter(PriceSnapshot.id.is_(None))
            .distinct()
        )
    if limit is not None:
        q = q.limit(limit)
    rows = q.all()

    if not rows:
        print("Bulk backfill: no markets to process.")
        return 0

    pairs = [(no_token_id, market_id) for market_id, no_token_id in rows]
    print(f"Bulk backfill: {len(pairs)} markets, concurrency={concurrency}, force={force}")

    results = asyncio.run(
        fetch_price_histories_concurrent(pairs, max_concurrency=concurrency)
    )

    stored = 0
    for i, (market_id, snaps) in enumerate(results.items(), start=1):
        if snaps:
            store_price_snapshots(session, snaps, market_id)
            stored += 1
        if i % 50 == 0:
            session.commit()
    session.commit()

    print(f"Bulk backfill: stored snapshots for {stored}/{len(pairs)} markets.")
    return stored


def main():
    parser = argparse.ArgumentParser(description="Backfill Polymarket price histories")
    parser.add_argument("--limit", type=int, default=None, help="Max markets to process (default: all)")
    parser.add_argument("--concurrency", type=int, default=5, help="Max concurrent requests (default: 5)")
    parser.add_argument("--force", action="store_true", help="Re-fetch even markets that already have snapshots")
    args = parser.parse_args()

    engine = get_engine()
    session = get_session(engine)
    try:
        run_backfill(session, limit=args.limit, concurrency=args.concurrency, force=args.force)
    finally:
        session.close()
        engine.dispose()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_backfill_runner.py -v`
Expected: PASS (all three).

- [ ] **Step 5: Smoke test the CLI imports**

Run: `uv run python -m src.collector.backfill_runner --help`
Expected: argparse help text listing `--limit`, `--concurrency`, `--force`.

- [ ] **Step 6: Commit**

```bash
git add src/collector/backfill_runner.py tests/test_backfill_runner.py
git commit -m "feat(collector): bulk price-history backfill CLI"
```

---

## Task 11: Run full test suite and manual verification

**Files:** none (verification only)

- [ ] **Step 1: Full test suite passes**

Run: `uv run pytest`
Expected: all tests pass. If any test fails, fix it in-place and re-run before continuing.

- [ ] **Step 2: Reset a copy of the live DB**

```bash
cp data/polymarket.db data/polymarket.db.bak
uv run python -m src.storage.reset_markets data/polymarket.db
```

Expected output: "Reset complete: dropped + recreated markets and price_snapshots."

Verify the `backtest_results` and `positions` tables are intact:

```bash
uv run python -c "
from sqlalchemy import create_engine, inspect
e = create_engine('sqlite:///data/polymarket.db')
i = inspect(e)
print('tables:', sorted(i.get_table_names()))
"
```
Expected: `tables: ['backtest_results', 'markets', 'positions', 'price_snapshots']`.

- [ ] **Step 3: Ingest a small slice and confirm new fields populate**

Run: `uv run python -m src.collector.runner --limit 200 --backfill-limit 0`

After it completes, inspect a few rows:

```bash
uv run python -c "
from src.storage.db import get_engine, get_session
from src.storage.models import Market
engine = get_engine()
session = get_session(engine)
total = session.query(Market).count()
neg = session.query(Market).filter(Market.is_neg_risk == True).count()
misc = session.query(Market).filter(Market.category == 'misc').count()
with_event = session.query(Market).filter(Market.event_id.isnot(None)).count()
print(f'total={total} neg_risk={neg} misc={misc} with_event_id={with_event}')
by_cat = dict(session.query(Market.category, __import__('sqlalchemy').func.count()).group_by(Market.category).all())
print(f'by_category={by_cat}')
"
```

Expected: `neg_risk > 0`, `with_event_id > 0`, at least one `misc`, no row with `category == 'other'`.

- [ ] **Step 4: Backfill price history for a sample**

Run: `uv run python -m src.collector.backfill_runner --limit 100`

Expected: "Bulk backfill: 100 markets..." followed by progress output every 100 markets, then "stored snapshots for N/100 markets."

Verify:
```bash
uv run python -c "
from src.storage.db import get_engine, get_session
from src.storage.models import Market, PriceSnapshot
engine = get_engine()
session = get_session(engine)
markets_with_snaps = session.query(PriceSnapshot.market_id).distinct().count()
print(f'markets with price snapshots: {markets_with_snaps}')
"
```

Expected: number roughly equal to (prior count + ~100 × success rate).

- [ ] **Step 5: Verify dashboard gating**

Run: `uv run streamlit run src/dashboard/app.py` in one terminal. In the Market Browser tab, search for a known negRisk market question (e.g. "Will Donald Trump win the 2024") — it should NOT appear. The Thesis Overview metrics should exclude negRisk rows.

Run a DB-level check:
```bash
uv run python -c "
from src.storage.db import get_engine, get_session
from src.storage.queries import thesis_markets
engine = get_engine()
session = get_session(engine)
print('thesis count:', thesis_markets(session).count())
print('total count:', session.query(__import__('src.storage.models', fromlist=['Market']).Market).count())
"
```

Expected: thesis count < total count by exactly the negRisk count.

- [ ] **Step 6: Run a backtest and confirm exclusion propagates**

Run: `uv run python -m src.backtester.engine --strategy threshold --param 0.85`

Expected: a `run_id` printed. Verify the row count matches non-negRisk resolved markets with qualifying snapshots:

```bash
uv run python -c "
from src.storage.db import get_engine, get_session
from src.storage.models import BacktestResult, Market
from src.storage.queries import thesis_markets
engine = get_engine()
session = get_session(engine)
last = session.query(BacktestResult).order_by(BacktestResult.id.desc()).first()
if last:
    run_id = last.run_id
    n = session.query(BacktestResult).filter_by(run_id=run_id).count()
    neg_in_run = (
        session.query(BacktestResult)
        .join(Market, Market.id == BacktestResult.market_id)
        .filter(BacktestResult.run_id == run_id, Market.is_neg_risk == True)
        .count()
    )
    print(f'run_id={run_id} rows={n} neg_risk_rows={neg_in_run}')
"
```

Expected: `neg_risk_rows=0`.

- [ ] **Step 7: Restore DB if desired**

If the live DB should be preserved as-is until the user explicitly wants to re-collect:

```bash
mv data/polymarket.db.bak data/polymarket.db
```

Otherwise the ingested 200-market slice plus backfilled snapshots stay in place.

- [ ] **Step 8: Final commit of any tweaks**

If Steps 3-6 revealed small issues you fixed inline, commit them now.

```bash
git status
# if nothing to commit, skip.
git add -A
git commit -m "chore: verification fixes from manual checklist"
```

---

## Self-Review

**Spec coverage** (each spec section maps to at least one task):

| Spec section | Tasks |
|---|---|
| Schema Changes (new columns) | Task 1 |
| Migration (`reset_markets.py`) | Task 1 |
| Collector — lift negRisk filter, extract `event_id` | Task 2 |
| Collector — `include_tag=true` request | Task 3 |
| Collector — tag-first classification + `misc` rename + pattern expansion | Task 4 |
| Runner — drop default category filter | Task 9 (main) |
| Runner — per-run backfill pass | Task 9 |
| Price History — async fetcher | Task 8 |
| Bulk Backfill Command | Task 10 |
| Backtester gating via `thesis_markets` | Tasks 5, 6 |
| Dashboard gating via `thesis_markets` | Tasks 5, 7 |
| Testing (new + updated) | Tasks 1, 2, 4, 5, 6, 8, 9, 10 |
| Manual verification checklist | Task 11 |

**Placeholder scan**: no `TBD`, no `TODO`, no "implement later". Every code step contains the actual code. Two places use intentional adapter shims (Task 2's `_classify_with_tags` which Task 4 removes, and Task 9's pattern of replacing an earlier fake test block with a cleaner one) — these are explicit and contained to a single task.

**Type consistency**:
- `thesis_markets(session)` returns a `Query` — used as such in Tasks 6 and 7 (both chain `.filter(...)` which is valid on legacy `Query`).
- `fetch_price_histories_concurrent` signature `(pairs: list[tuple[str, str]], max_concurrency: int = 5) -> dict[str, list[dict]]` is consistent across Tasks 8, 9, 10.
- `backfill_missing_price_histories(session, limit, max_concurrency=5)` in Task 9 is the per-run helper; `run_backfill(session, limit, concurrency, force)` in Task 10 is the bulk CLI helper. Names differ intentionally (per-run vs bulk) and neither is referenced from the other's tests.
- Task 2 adds `is_neg_risk` and `event_id` to the parser output; Task 1 adds the matching columns; `Market(**market_data)` in `runner.py` already splats the dict so no further wiring is needed. `upsert_market` handles only resolution/resolved_at/source_url on updates — existing behaviour preserves the new columns only on insert, which is correct because `is_neg_risk` and `event_id` don't change over a market's life.

Plan complete.
