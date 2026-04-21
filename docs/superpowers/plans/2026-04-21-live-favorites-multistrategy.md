# Live Favorites Multi-Strategy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewire the live paper-trading pipeline to run every DB-favorited strategy in parallel (currently `snapshot_24__earliest_created` and `threshold_0.3__earliest_created`), each with its own $1000 bankroll that compounds on wins, plus a Candidates dashboard view and per-strategy tabs on Live Positions.

**Architecture:** YAML-backed config + per-strategy `Favorite` records parsed from the `favorite_strategies` DB table. Two strategy-specific signal detectors (snapshot window; threshold observation). Pure-function bankroll computed from position history. Runner loops over favorites and bankroll-gates each signal before opening a paper position. Geopolitical-only scope, 6h cron cadence, no schema changes.

**Tech Stack:** Python 3.11, SQLAlchemy 2.0, Streamlit, PyYAML (new), pytest, uv.

**Reference spec:** `docs/superpowers/specs/2026-04-21-live-favorites-multistrategy-design.md`

---

## File Structure

**New files:**
- `live_config.example.yaml` — checked-in example
- `.gitignore` entry for `live_config.yaml` (local, uncommitted)
- `src/live/favorites.py` — label parser + `Favorite` dataclass + `load_favorites`
- `src/live/bankroll.py` — `BankrollState` + `compute_bankroll`
- `tests/test_live_favorites.py`
- `tests/test_live_bankroll.py`
- `tests/test_live_signals_multistrategy.py` — new tests for the rewritten signals
- `tests/test_dashboard_candidates.py`

**Modified files:**
- `pyproject.toml` — add `pyyaml>=6.0`
- `.gitignore` — add `live_config.yaml`
- `src/live/config.py` — full rewrite: YAML + per-strategy block, drop removed fields
- `src/live/signals.py` — full rewrite: `detect_snapshot_entries`, `detect_threshold_entries`, `enumerate_candidates`
- `src/live/runner.py` — loops over favorites, bankroll-gates signals
- `src/dashboard/app.py` — Candidates view, Live Positions tabs
- `tests/test_live_config.py` — rewrite for YAML
- `tests/test_live_signals.py` — delete (replaced by `test_live_signals_multistrategy.py`)
- `tests/test_live_runner.py` — rewrite for multi-strategy + bankroll gating

**Principle:** TDD. Every task writes the failing test first, then the minimal implementation. Commit after every passing task. Each task is independently runnable.

---

## Task 1: Add PyYAML dependency and gitignore

**Files:**
- Modify: `pyproject.toml`
- Modify: `.gitignore`

- [ ] **Step 1: Add pyyaml to dependencies**

Edit `pyproject.toml`, in the `dependencies` list:

```toml
dependencies = [
    "sqlalchemy>=2.0",
    "httpx>=0.27",
    "web3>=7.0",
    "streamlit>=1.38",
    "plotly>=5.24",
    "python-dotenv>=1.0",
    "pandas>=2.0",
    "pyyaml>=6.0",
]
```

- [ ] **Step 2: Sync dependencies**

Run: `uv sync --extra dev`
Expected: installs pyyaml without error.

- [ ] **Step 3: Add `live_config.yaml` to `.gitignore`**

Check `.gitignore` for an existing entry first. If missing, append:

```
# Live bot config (secrets + local tuning)
live_config.yaml
```

- [ ] **Step 4: Verify import works**

Run: `uv run python -c "import yaml; print(yaml.__version__)"`
Expected: prints a 6.x version string.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock .gitignore
git commit -m "chore: add pyyaml dependency for live config"
```

---

## Task 2: Live config example YAML

**Files:**
- Create: `live_config.example.yaml`

- [ ] **Step 1: Create the example file**

```yaml
# live_config.example.yaml
# Copy to live_config.yaml and edit. live_config.yaml is gitignored.
#
# Secrets (telegram tokens) are NOT in this file — they come from
# environment variables TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.

categories:
  - geopolitical

# Hours of slack on snapshot age windows. With 6h cron ticks, 12h tolerance
# means a snapshot_24 market can be caught on any of 4 consecutive ticks.
tolerance_hours: 12

# "paper" (writes simulated fills to DB) or "live" (stub; not wired).
executor: paper

# Per-strategy settings. Key = label from the favorite_strategies DB table.
# A favorite without an entry here is skipped with a warning at startup.
strategies:
  snapshot_24__earliest_created:
    starting_bankroll: 1000.0
    shares_per_trade: 10.0
  threshold_0.3__earliest_created:
    starting_bankroll: 1000.0
    shares_per_trade: 10.0
```

- [ ] **Step 2: Copy to local `live_config.yaml` for runtime use**

Run: `cp live_config.example.yaml live_config.yaml`
Expected: file created locally, gitignored.

- [ ] **Step 3: Verify git ignores the runtime file**

Run: `git status --short live_config.yaml`
Expected: no output (ignored).

- [ ] **Step 4: Commit**

```bash
git add live_config.example.yaml
git commit -m "feat(live): example yaml config for per-strategy bankrolls"
```

---

## Task 3: Rewrite `src/live/config.py` for YAML

**Files:**
- Modify: `src/live/config.py`
- Modify: `tests/test_live_config.py`

- [ ] **Step 1: Rewrite the config test file first (TDD)**

Replace the contents of `tests/test_live_config.py` with:

```python
from pathlib import Path

import pytest

from src.live.config import LiveConfig, StrategyConfig, load_config


def _write_config(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "live_config.yaml"
    path.write_text(text)
    return path


def test_load_config_full_shape(tmp_path, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    path = _write_config(
        tmp_path,
        """
categories: [geopolitical]
tolerance_hours: 12
executor: paper
strategies:
  snapshot_24__earliest_created:
    starting_bankroll: 1000.0
    shares_per_trade: 10.0
  threshold_0.3__earliest_created:
    starting_bankroll: 500.0
    shares_per_trade: 5.0
""",
    )
    cfg = load_config(path)
    assert isinstance(cfg, LiveConfig)
    assert cfg.categories == ["geopolitical"]
    assert cfg.tolerance_hours == 12
    assert cfg.executor == "paper"
    assert set(cfg.strategies.keys()) == {
        "snapshot_24__earliest_created",
        "threshold_0.3__earliest_created",
    }
    snap = cfg.strategies["snapshot_24__earliest_created"]
    assert isinstance(snap, StrategyConfig)
    assert snap.label == "snapshot_24__earliest_created"
    assert snap.starting_bankroll == 1000.0
    assert snap.shares_per_trade == 10.0
    thr = cfg.strategies["threshold_0.3__earliest_created"]
    assert thr.starting_bankroll == 500.0
    assert thr.shares_per_trade == 5.0
    assert cfg.telegram_bot_token is None
    assert cfg.telegram_chat_id is None


def test_load_config_pulls_telegram_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "abc123")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999")
    path = _write_config(
        tmp_path,
        """
categories: [geopolitical]
tolerance_hours: 12
executor: paper
strategies: {}
""",
    )
    cfg = load_config(path)
    assert cfg.telegram_bot_token == "abc123"
    assert cfg.telegram_chat_id == "999"


def test_load_config_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "does_not_exist.yaml")


def test_load_config_rejects_missing_required_keys(tmp_path):
    path = _write_config(tmp_path, "categories: [geopolitical]\n")
    with pytest.raises(KeyError):
        load_config(path)
```

- [ ] **Step 2: Run tests — confirm they fail**

Run: `uv run pytest tests/test_live_config.py -v`
Expected: failures — the new shape doesn't exist yet (old `LiveConfig` fields don't match).

- [ ] **Step 3: Rewrite `src/live/config.py`**

Replace the entire file with:

```python
"""Live bot configuration loaded from YAML + environment variables.

Structural settings (categories, per-strategy bankrolls) come from
`live_config.yaml`. Secrets (telegram tokens) still come from env.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml


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
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None


def load_config(path: Path = Path("live_config.yaml")) -> LiveConfig:
    raw = yaml.safe_load(Path(path).read_text())
    strategies_raw = raw["strategies"] or {}
    strategies = {
        label: StrategyConfig(
            label=label,
            starting_bankroll=float(block["starting_bankroll"]),
            shares_per_trade=float(block["shares_per_trade"]),
        )
        for label, block in strategies_raw.items()
    }
    return LiveConfig(
        categories=list(raw["categories"]),
        tolerance_hours=int(raw["tolerance_hours"]),
        executor=str(raw["executor"]),
        strategies=strategies,
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN") or None,
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID") or None,
    )
```

- [ ] **Step 4: Run tests — confirm they pass**

Run: `uv run pytest tests/test_live_config.py -v`
Expected: all 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/live/config.py tests/test_live_config.py
git commit -m "feat(live): yaml-backed config with per-strategy bankrolls"
```

---

## Task 4: Favorite label parser

**Files:**
- Create: `src/live/favorites.py`
- Create: `tests/test_live_favorites.py`

- [ ] **Step 1: Write failing tests for `parse_label`**

Create `tests/test_live_favorites.py`:

```python
import pytest

from src.live.favorites import parse_label


def test_parse_snapshot_label():
    name, params, mode = parse_label("snapshot_24__earliest_created")
    assert name == "snapshot"
    assert params == {"offset_hours": 24}
    assert mode == "earliest_created"


def test_parse_threshold_label():
    name, params, mode = parse_label("threshold_0.3__earliest_created")
    assert name == "threshold"
    assert params == {"threshold": 0.3}
    assert mode == "earliest_created"


def test_rejects_unsupported_strategy():
    with pytest.raises(ValueError, match="unsupported strategy"):
        parse_label("limit_0.5__earliest_created")


def test_rejects_unsupported_selection_mode():
    with pytest.raises(ValueError, match="selection mode"):
        parse_label("snapshot_24__earliest_deadline")


def test_rejects_malformed_label():
    with pytest.raises(ValueError):
        parse_label("not_a_valid_label")
```

- [ ] **Step 2: Run to confirm failure**

Run: `uv run pytest tests/test_live_favorites.py -v`
Expected: ImportError — module doesn't exist.

- [ ] **Step 3: Create `src/live/favorites.py` with `parse_label`**

```python
"""Favorite-strategy records: parse DB labels into typed records, and
merge with LiveConfig per-strategy settings.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from src.live.config import LiveConfig
from src.storage.models import FavoriteStrategy

logger = logging.getLogger(__name__)

SUPPORTED_SELECTION_MODES = {"earliest_created"}


def parse_label(label: str) -> tuple[str, dict, str]:
    """Parse a favorite label into (strategy_name, params, selection_mode).

    Grammar:
        snapshot_<N>__<mode>        → ("snapshot", {"offset_hours": N}, mode)
        threshold_<p>__<mode>       → ("threshold", {"threshold": p}, mode)
    """
    if "__" not in label:
        raise ValueError(f"malformed label (missing __): {label}")
    strategy_part, mode = label.split("__", 1)
    if mode not in SUPPORTED_SELECTION_MODES:
        raise ValueError(f"unsupported selection mode: {mode!r} in {label}")
    if "_" not in strategy_part:
        raise ValueError(f"malformed strategy part: {strategy_part}")
    name, _, raw_param = strategy_part.partition("_")
    if name == "snapshot":
        try:
            offset = int(raw_param)
        except ValueError as exc:
            raise ValueError(f"snapshot offset not an int: {raw_param!r}") from exc
        return name, {"offset_hours": offset}, mode
    if name == "threshold":
        try:
            threshold = float(raw_param)
        except ValueError as exc:
            raise ValueError(f"threshold not a float: {raw_param!r}") from exc
        return name, {"threshold": threshold}, mode
    raise ValueError(f"unsupported strategy: {name!r} in {label}")


@dataclass(frozen=True)
class Favorite:
    label: str
    strategy_name: str
    params: dict
    selection_mode: str
    starting_bankroll: float
    shares_per_trade: float


def load_favorites(session: Session, config: LiveConfig) -> list[Favorite]:
    rows = session.query(FavoriteStrategy).all()
    favorites: list[Favorite] = []
    for row in rows:
        try:
            name, params, mode = parse_label(row.strategy)
        except ValueError as exc:
            logger.warning("skipping unparseable favorite %r: %s", row.strategy, exc)
            continue
        sc = config.strategies.get(row.strategy)
        if sc is None:
            logger.warning(
                "skipping favorite %r: no entry in live_config.yaml", row.strategy
            )
            continue
        favorites.append(
            Favorite(
                label=row.strategy,
                strategy_name=name,
                params=params,
                selection_mode=mode,
                starting_bankroll=sc.starting_bankroll,
                shares_per_trade=sc.shares_per_trade,
            )
        )
    return favorites
```

- [ ] **Step 4: Run tests — confirm pass**

Run: `uv run pytest tests/test_live_favorites.py -v`
Expected: all 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/live/favorites.py tests/test_live_favorites.py
git commit -m "feat(live): favorite label parser"
```

---

## Task 5: `load_favorites` joins DB rows with config

**Files:**
- Modify: `tests/test_live_favorites.py`

- [ ] **Step 1: Add test for `load_favorites`**

Append to `tests/test_live_favorites.py`:

```python
from src.live.config import LiveConfig, StrategyConfig
from src.live.favorites import Favorite, load_favorites
from src.storage.models import FavoriteStrategy


def _cfg_with(strategies: dict[str, StrategyConfig]) -> LiveConfig:
    return LiveConfig(
        categories=["geopolitical"],
        tolerance_hours=12,
        executor="paper",
        strategies=strategies,
    )


def test_load_favorites_merges_db_and_config(session):
    session.add(FavoriteStrategy(strategy="snapshot_24__earliest_created"))
    session.add(FavoriteStrategy(strategy="threshold_0.3__earliest_created"))
    session.commit()

    cfg = _cfg_with(
        {
            "snapshot_24__earliest_created": StrategyConfig(
                label="snapshot_24__earliest_created",
                starting_bankroll=1000.0,
                shares_per_trade=10.0,
            ),
            "threshold_0.3__earliest_created": StrategyConfig(
                label="threshold_0.3__earliest_created",
                starting_bankroll=500.0,
                shares_per_trade=5.0,
            ),
        }
    )
    favs = load_favorites(session, cfg)
    assert len(favs) == 2
    by_label = {f.label: f for f in favs}
    snap = by_label["snapshot_24__earliest_created"]
    assert isinstance(snap, Favorite)
    assert snap.strategy_name == "snapshot"
    assert snap.params == {"offset_hours": 24}
    assert snap.starting_bankroll == 1000.0
    assert snap.shares_per_trade == 10.0
    thr = by_label["threshold_0.3__earliest_created"]
    assert thr.strategy_name == "threshold"
    assert thr.params == {"threshold": 0.3}
    assert thr.shares_per_trade == 5.0


def test_load_favorites_skips_fav_missing_from_config(session, caplog):
    session.add(FavoriteStrategy(strategy="snapshot_24__earliest_created"))
    session.commit()
    cfg = _cfg_with({})  # no config entry
    with caplog.at_level("WARNING"):
        favs = load_favorites(session, cfg)
    assert favs == []
    assert any("no entry in live_config.yaml" in r.message for r in caplog.records)


def test_load_favorites_skips_unparseable_label(session, caplog):
    session.add(FavoriteStrategy(strategy="limit_0.5__earliest_created"))
    session.commit()
    cfg = _cfg_with({})
    with caplog.at_level("WARNING"):
        favs = load_favorites(session, cfg)
    assert favs == []
    assert any("unparseable favorite" in r.message for r in caplog.records)
```

- [ ] **Step 2: Run and confirm pass**

Run: `uv run pytest tests/test_live_favorites.py -v`
Expected: all 8 tests pass (3 new ones use `load_favorites`, already implemented in Task 4).

- [ ] **Step 3: Commit**

```bash
git add tests/test_live_favorites.py
git commit -m "test(live): load_favorites merges DB rows with config"
```

---

## Task 6: Bankroll computation

**Files:**
- Create: `src/live/bankroll.py`
- Create: `tests/test_live_bankroll.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_live_bankroll.py`:

```python
from datetime import datetime, timedelta, timezone

from src.live.bankroll import BankrollState, compute_bankroll
from src.storage.models import Market, Position


NOW = datetime(2026, 4, 21, 12, tzinfo=timezone.utc)


def _market(session, mid: str) -> Market:
    m = Market(
        id=mid,
        question=f"Q {mid}",
        category="geopolitical",
        no_token_id=f"tok_{mid}",
        created_at=NOW - timedelta(days=1),
    )
    session.add(m)
    session.flush()
    return m


def _open_position(session, market_id: str, strategy: str, entry: float, shares: float) -> Position:
    pos = Position(
        market_id=market_id,
        strategy=strategy,
        executor="paper",
        status="open",
        entry_price=entry,
        entry_timestamp=NOW - timedelta(hours=12),
        size_shares=shares,
        size_notional=entry * shares,
        sizing_rule="fixed_shares",
        sizing_params_json="{}",
    )
    session.add(pos)
    session.flush()
    return pos


def _closed_position(
    session, market_id: str, strategy: str, entry: float, shares: float, exit_price: float
) -> Position:
    pos = _open_position(session, market_id, strategy, entry, shares)
    pos.status = "resolved"
    pos.exit_price = exit_price
    pos.exit_timestamp = NOW - timedelta(hours=1)
    pos.realized_pnl = (exit_price - entry) * shares
    pos.unrealized_pnl = None
    return pos


def test_bankroll_empty_history(session):
    state = compute_bankroll(session, "snapshot_24__earliest_created", starting=1000.0)
    assert state == BankrollState(
        strategy="snapshot_24__earliest_created",
        starting=1000.0,
        locked=0.0,
        realized_pnl=0.0,
        available=1000.0,
        open_positions=0,
        closed_positions=0,
    )


def test_bankroll_only_open_positions(session):
    _market(session, "a")
    _market(session, "b")
    _open_position(session, "a", "snapshot_24__earliest_created", entry=0.4, shares=10)
    _open_position(session, "b", "snapshot_24__earliest_created", entry=0.25, shares=10)
    session.commit()

    state = compute_bankroll(session, "snapshot_24__earliest_created", starting=1000.0)
    # locked = 0.4*10 + 0.25*10 = 6.5
    assert state.locked == 6.5
    assert state.realized_pnl == 0.0
    assert state.available == 1000.0 - 6.5
    assert state.open_positions == 2
    assert state.closed_positions == 0


def test_bankroll_wins_compound(session):
    _market(session, "w1")
    _closed_position(
        session, "w1", "snapshot_24__earliest_created",
        entry=0.3, shares=10, exit_price=1.0,
    )  # realized_pnl = (1 - 0.3) * 10 = 7
    session.commit()

    state = compute_bankroll(session, "snapshot_24__earliest_created", starting=1000.0)
    assert state.locked == 0.0
    assert state.realized_pnl == 7.0
    assert state.available == 1007.0
    assert state.closed_positions == 1


def test_bankroll_losses_deduct(session):
    _market(session, "L1")
    _closed_position(
        session, "L1", "snapshot_24__earliest_created",
        entry=0.6, shares=10, exit_price=0.0,
    )  # realized_pnl = (0 - 0.6) * 10 = -6
    session.commit()

    state = compute_bankroll(session, "snapshot_24__earliest_created", starting=1000.0)
    assert state.realized_pnl == -6.0
    assert state.available == 994.0


def test_bankroll_scoped_by_strategy(session):
    _market(session, "shared")
    _open_position(session, "shared", "snapshot_24__earliest_created", entry=0.4, shares=10)
    _market(session, "other")
    _open_position(session, "other", "threshold_0.3__earliest_created", entry=0.25, shares=5)
    session.commit()

    snap = compute_bankroll(session, "snapshot_24__earliest_created", starting=1000.0)
    thr = compute_bankroll(session, "threshold_0.3__earliest_created", starting=500.0)
    assert snap.locked == 4.0
    assert snap.open_positions == 1
    assert thr.locked == 1.25
    assert thr.open_positions == 1


def test_bankroll_mixed_open_and_closed(session):
    _market(session, "o1")
    _open_position(session, "o1", "snapshot_24__earliest_created", entry=0.4, shares=10)  # locked 4
    _market(session, "c1")
    _closed_position(session, "c1", "snapshot_24__earliest_created", entry=0.3, shares=10, exit_price=1.0)  # +7
    _market(session, "c2")
    _closed_position(session, "c2", "snapshot_24__earliest_created", entry=0.5, shares=10, exit_price=0.0)  # -5
    session.commit()

    state = compute_bankroll(session, "snapshot_24__earliest_created", starting=1000.0)
    assert state.locked == 4.0
    assert state.realized_pnl == 2.0  # 7 - 5
    assert state.available == 1000.0 - 4.0 + 2.0
    assert state.open_positions == 1
    assert state.closed_positions == 2
```

- [ ] **Step 2: Run and confirm failure**

Run: `uv run pytest tests/test_live_bankroll.py -v`
Expected: ImportError — module doesn't exist.

- [ ] **Step 3: Create `src/live/bankroll.py`**

```python
"""Per-strategy bankroll computed from position history (pure function).

Accounting model:
- Entry locks `shares * entry_price` dollars (tracked as `locked`).
- Closed position realizes `(exit_price - entry_price) * shares` — that's
  exactly what's stored in Position.realized_pnl.
- available = starting - locked + sum(realized_pnl)

No mutable state; no new table. The DB stores immutable position facts.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from src.storage.models import Position


@dataclass(frozen=True)
class BankrollState:
    strategy: str
    starting: float
    locked: float
    realized_pnl: float
    available: float
    open_positions: int
    closed_positions: int


def compute_bankroll(session: Session, strategy: str, starting: float) -> BankrollState:
    positions = (
        session.query(Position).filter(Position.strategy == strategy).all()
    )
    locked = 0.0
    realized = 0.0
    open_count = 0
    closed_count = 0
    for p in positions:
        if p.status == "open":
            locked += p.entry_price * p.size_shares
            open_count += 1
        else:
            realized += p.realized_pnl or 0.0
            closed_count += 1
    return BankrollState(
        strategy=strategy,
        starting=starting,
        locked=locked,
        realized_pnl=realized,
        available=starting - locked + realized,
        open_positions=open_count,
        closed_positions=closed_count,
    )
```

- [ ] **Step 4: Run and confirm pass**

Run: `uv run pytest tests/test_live_bankroll.py -v`
Expected: all 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/live/bankroll.py tests/test_live_bankroll.py
git commit -m "feat(live): per-strategy bankroll computed from position history"
```

---

## Task 7: Rewrite `signals.py` — snapshot detector

**Files:**
- Modify: `src/live/signals.py`
- Create: `tests/test_live_signals_multistrategy.py`
- Delete: `tests/test_live_signals.py` (replaced)

- [ ] **Step 1: Delete the old signals test file**

```bash
git rm tests/test_live_signals.py
```

- [ ] **Step 2: Write failing tests for `detect_snapshot_entries`**

Create `tests/test_live_signals_multistrategy.py`:

```python
from datetime import datetime, timedelta, timezone

from src.live.favorites import Favorite
from src.live.signals import EntrySignal, detect_snapshot_entries
from src.storage.models import Market, Position


NOW = datetime(2026, 4, 21, 12, tzinfo=timezone.utc)


SNAP = Favorite(
    label="snapshot_24__earliest_created",
    strategy_name="snapshot",
    params={"offset_hours": 24},
    selection_mode="earliest_created",
    starting_bankroll=1000.0,
    shares_per_trade=10.0,
)


def _add_market(session, mid: str, *, question="Will X happen by May 10, 2026?",
                created_at=None, end_date=None, category="geopolitical") -> Market:
    m = Market(
        id=mid, question=question, category=category,
        no_token_id=f"tok_{mid}",
        created_at=created_at or (NOW - timedelta(hours=24)),
        end_date=end_date,
    )
    session.add(m)
    return m


def _add_position(session, market_id: str, strategy: str, *, status="open") -> Position:
    pos = Position(
        market_id=market_id, strategy=strategy, executor="paper", status=status,
        entry_price=0.5, entry_timestamp=NOW - timedelta(days=1),
        size_shares=10.0, size_notional=5.0,
        sizing_rule="fixed_shares", sizing_params_json="{}",
    )
    session.add(pos)
    return pos


def _quote(p):
    return lambda _tok: p


def test_snapshot_detects_market_at_24h(session):
    _add_market(session, "m", created_at=NOW - timedelta(hours=24))
    session.commit()
    signals = detect_snapshot_entries(session, SNAP, now=NOW, tolerance_hours=12, quote_fn=_quote(0.45))
    assert len(signals) == 1
    s = signals[0]
    assert isinstance(s, EntrySignal)
    assert s.market.id == "m"
    assert s.entry_price == 0.45
    assert s.entry_timestamp == NOW


def test_snapshot_detects_within_tolerance(session):
    _add_market(session, "young", created_at=NOW - timedelta(hours=14))
    _add_market(session, "old", question="Other?", created_at=NOW - timedelta(hours=34))
    session.commit()
    signals = detect_snapshot_entries(session, SNAP, now=NOW, tolerance_hours=12, quote_fn=_quote(0.5))
    assert {s.market.id for s in signals} == {"young", "old"}


def test_snapshot_skips_outside_tolerance(session):
    _add_market(session, "tooYoung", created_at=NOW - timedelta(hours=10))
    _add_market(session, "tooOld", question="Other?", created_at=NOW - timedelta(hours=40))
    session.commit()
    signals = detect_snapshot_entries(session, SNAP, now=NOW, tolerance_hours=12, quote_fn=_quote(0.5))
    assert signals == []


def test_snapshot_skips_non_geopolitical(session):
    _add_market(session, "pol", category="political", created_at=NOW - timedelta(hours=24))
    session.commit()
    signals = detect_snapshot_entries(session, SNAP, now=NOW, tolerance_hours=12, quote_fn=_quote(0.5))
    assert signals == []


def test_snapshot_per_strategy_dedup_allows_other_strategy_on_same_market(session):
    m = _add_market(session, "shared", created_at=NOW - timedelta(hours=24))
    session.flush()
    # Threshold already took this market; snapshot should still be eligible.
    _add_position(session, m.id, "threshold_0.3__earliest_created")
    session.commit()
    signals = detect_snapshot_entries(session, SNAP, now=NOW, tolerance_hours=12, quote_fn=_quote(0.5))
    assert [s.market.id for s in signals] == ["shared"]


def test_snapshot_blocks_when_same_strategy_already_entered(session):
    m = _add_market(session, "dup", created_at=NOW - timedelta(hours=24))
    session.flush()
    _add_position(session, m.id, SNAP.label)
    session.commit()
    signals = detect_snapshot_entries(session, SNAP, now=NOW, tolerance_hours=12, quote_fn=_quote(0.5))
    assert signals == []


def test_snapshot_template_dedup_prefers_earliest_created(session):
    base = NOW - timedelta(hours=24)
    _add_market(session, "earlier",
                question="Will Israel strike Gaza by January 2, 2026?",
                created_at=base - timedelta(minutes=1))
    _add_market(session, "later",
                question="Will Israel strike Gaza by January 31, 2026?",
                created_at=base)
    session.commit()
    signals = detect_snapshot_entries(session, SNAP, now=NOW, tolerance_hours=12, quote_fn=_quote(0.5))
    assert [s.market.id for s in signals] == ["earlier"]


def test_snapshot_template_block_scoped_to_strategy(session):
    old = _add_market(session, "oldT",
                      question="Will Israel strike Gaza by January 2, 2026?",
                      created_at=NOW - timedelta(days=5), end_date=NOW - timedelta(days=1))
    session.flush()
    # Threshold holds a position on the old template sibling — should NOT block snapshot.
    _add_position(session, old.id, "threshold_0.3__earliest_created")
    _add_market(session, "newT",
                question="Will Israel strike Gaza by February 28, 2026?",
                created_at=NOW - timedelta(hours=24))
    session.commit()
    signals = detect_snapshot_entries(session, SNAP, now=NOW, tolerance_hours=12, quote_fn=_quote(0.5))
    assert [s.market.id for s in signals] == ["newT"]


def test_snapshot_skips_when_quote_unavailable(session):
    _add_market(session, "noq", created_at=NOW - timedelta(hours=24))
    session.commit()
    signals = detect_snapshot_entries(session, SNAP, now=NOW, tolerance_hours=12, quote_fn=lambda _t: None)
    assert signals == []
```

- [ ] **Step 3: Run to confirm failure**

Run: `uv run pytest tests/test_live_signals_multistrategy.py -v`
Expected: ImportError on `detect_snapshot_entries`.

- [ ] **Step 4: Rewrite `src/live/signals.py` with both `EntrySignal` and `detect_snapshot_entries`**

Replace the entire file with (we'll add `detect_threshold_entries` and `enumerate_candidates` in later tasks):

```python
"""Entry-signal detection + candidate enumeration for the live bot.

Two strategy-specific detectors share the same EntrySignal output:
- `detect_snapshot_entries` — age-window strategy (snapshot_N)
- `detect_threshold_entries` — observation-price strategy (threshold_p)

`enumerate_candidates` is for the dashboard; it classifies every open
market × favorite pair into a state without opening any positions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.backtester.selection import _select_markets, _template_key
from src.live.favorites import Favorite
from src.storage.models import Market, Position


@dataclass(frozen=True)
class EntrySignal:
    market: Market
    entry_price: float
    entry_timestamp: datetime
    favorite: Favorite


def _ensure_utc(ts: datetime) -> datetime:
    # SQLite round-trips strip tzinfo; assume UTC on naive.
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts


def _load_open_geopolitical_markets(session: Session) -> list[Market]:
    query = select(Market).where(
        Market.resolution.is_(None),
        Market.category == "geopolitical",
    )
    return list(session.execute(query).scalars().all())


def _blocked_by_prior_position(
    session: Session, strategy_label: str
) -> set[str]:
    """Markets on which THIS strategy already entered (ever, any status)."""
    rows = (
        session.query(Position.market_id)
        .filter(Position.strategy == strategy_label)
        .distinct()
        .all()
    )
    return {mid for (mid,) in rows}


def _blocked_template_keys(
    session: Session, strategy_label: str
) -> set[str]:
    """Template keys currently held open by THIS strategy."""
    open_rows = (
        session.query(Position.market_id)
        .filter(
            Position.strategy == strategy_label,
            Position.status == "open",
        )
        .distinct()
        .all()
    )
    keys: set[str] = set()
    for (mid,) in open_rows:
        m = session.get(Market, mid)
        if m is not None:
            keys.add(_template_key(m.question))
    return keys


def detect_snapshot_entries(
    session: Session,
    fav: Favorite,
    *,
    now: datetime,
    tolerance_hours: int,
    quote_fn: Callable[[str], float | None],
) -> list[EntrySignal]:
    offset = fav.params["offset_hours"]
    low = offset - tolerance_hours
    high = offset + tolerance_hours
    oldest = now - timedelta(hours=high)
    youngest = now - timedelta(hours=low)

    markets = _load_open_geopolitical_markets(session)

    def _age_ok(m: Market) -> bool:
        created = _ensure_utc(m.created_at)
        return oldest <= created <= youngest

    candidates = [m for m in markets if _age_ok(m)]
    taken = _blocked_by_prior_position(session, fav.label)
    candidates = [m for m in candidates if m.id not in taken]
    blocked_keys = _blocked_template_keys(session, fav.label)
    candidates = [m for m in candidates if _template_key(m.question) not in blocked_keys]
    selected = _select_markets(candidates, fav.selection_mode)

    signals: list[EntrySignal] = []
    for m in selected:
        price = quote_fn(m.no_token_id)
        if price is None:
            continue
        signals.append(
            EntrySignal(market=m, entry_price=price, entry_timestamp=now, favorite=fav)
        )
    return signals
```

- [ ] **Step 5: Run tests — confirm pass**

Run: `uv run pytest tests/test_live_signals_multistrategy.py -v`
Expected: all 9 snapshot tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/live/signals.py tests/test_live_signals_multistrategy.py tests/test_live_signals.py
git commit -m "feat(live): multi-strategy snapshot entry detector"
```

---

## Task 8: Threshold entry detector

**Files:**
- Modify: `src/live/signals.py`
- Modify: `tests/test_live_signals_multistrategy.py`

- [ ] **Step 1: Append failing tests for `detect_threshold_entries`**

Append to `tests/test_live_signals_multistrategy.py`:

```python
from src.live.signals import detect_threshold_entries


THR = Favorite(
    label="threshold_0.3__earliest_created",
    strategy_name="threshold",
    params={"threshold": 0.3},
    selection_mode="earliest_created",
    starting_bankroll=1000.0,
    shares_per_trade=10.0,
)


def test_threshold_fires_when_quote_at_or_below_threshold(session):
    _add_market(session, "dip", created_at=NOW - timedelta(days=2))
    session.commit()
    signals = detect_threshold_entries(session, THR, now=NOW, quote_fn=_quote(0.28))
    assert len(signals) == 1
    assert signals[0].entry_price == 0.28


def test_threshold_fires_on_exactly_threshold(session):
    _add_market(session, "edge", created_at=NOW - timedelta(days=2))
    session.commit()
    signals = detect_threshold_entries(session, THR, now=NOW, quote_fn=_quote(0.3))
    assert [s.market.id for s in signals] == ["edge"]


def test_threshold_fires_on_market_that_opened_below(session):
    # Market opened 2h ago already below threshold — still a valid entry
    # (live policy: fire on observation, not on crossing).
    _add_market(session, "fresh", created_at=NOW - timedelta(hours=2))
    session.commit()
    signals = detect_threshold_entries(session, THR, now=NOW, quote_fn=_quote(0.15))
    assert [s.market.id for s in signals] == ["fresh"]


def test_threshold_skips_when_quote_above_threshold(session):
    _add_market(session, "up", created_at=NOW - timedelta(days=2))
    session.commit()
    signals = detect_threshold_entries(session, THR, now=NOW, quote_fn=_quote(0.45))
    assert signals == []


def test_threshold_skips_non_geopolitical(session):
    _add_market(session, "pol", category="political", created_at=NOW - timedelta(days=2))
    session.commit()
    signals = detect_threshold_entries(session, THR, now=NOW, quote_fn=_quote(0.2))
    assert signals == []


def test_threshold_per_strategy_dedup_allows_snapshot_on_same_market(session):
    m = _add_market(session, "shared", created_at=NOW - timedelta(days=2))
    session.flush()
    _add_position(session, m.id, "snapshot_24__earliest_created")
    session.commit()
    signals = detect_threshold_entries(session, THR, now=NOW, quote_fn=_quote(0.2))
    assert [s.market.id for s in signals] == ["shared"]


def test_threshold_blocks_when_same_strategy_already_entered(session):
    m = _add_market(session, "dup", created_at=NOW - timedelta(days=2))
    session.flush()
    _add_position(session, m.id, THR.label)
    session.commit()
    signals = detect_threshold_entries(session, THR, now=NOW, quote_fn=_quote(0.2))
    assert signals == []


def test_threshold_template_dedup_prefers_earliest_created(session):
    base = NOW - timedelta(days=2)
    _add_market(session, "earlier",
                question="Will Israel strike Gaza by January 2, 2026?",
                created_at=base - timedelta(minutes=1))
    _add_market(session, "later",
                question="Will Israel strike Gaza by January 31, 2026?",
                created_at=base)
    session.commit()
    signals = detect_threshold_entries(session, THR, now=NOW, quote_fn=_quote(0.2))
    assert [s.market.id for s in signals] == ["earlier"]


def test_threshold_skips_when_quote_none(session):
    _add_market(session, "noq", created_at=NOW - timedelta(days=2))
    session.commit()
    signals = detect_threshold_entries(session, THR, now=NOW, quote_fn=lambda _t: None)
    assert signals == []
```

- [ ] **Step 2: Run to confirm failure**

Run: `uv run pytest tests/test_live_signals_multistrategy.py -v`
Expected: new tests fail — function doesn't exist yet.

- [ ] **Step 3: Add `detect_threshold_entries` to `src/live/signals.py`**

Append to `src/live/signals.py`:

```python
def detect_threshold_entries(
    session: Session,
    fav: Favorite,
    *,
    now: datetime,
    quote_fn: Callable[[str], float | None],
) -> list[EntrySignal]:
    threshold = fav.params["threshold"]
    markets = _load_open_geopolitical_markets(session)

    taken = _blocked_by_prior_position(session, fav.label)
    markets = [m for m in markets if m.id not in taken]
    blocked_keys = _blocked_template_keys(session, fav.label)
    markets = [m for m in markets if _template_key(m.question) not in blocked_keys]

    # Quote each; keep those at-or-below threshold.
    priced: list[tuple[Market, float]] = []
    for m in markets:
        price = quote_fn(m.no_token_id)
        if price is None or price > threshold:
            continue
        priced.append((m, price))

    selected = _select_markets([m for m, _ in priced], fav.selection_mode)
    selected_ids = {m.id for m in selected}
    price_by_id = {m.id: p for m, p in priced}

    return [
        EntrySignal(
            market=m,
            entry_price=price_by_id[m.id],
            entry_timestamp=now,
            favorite=fav,
        )
        for m in selected
        if m.id in selected_ids
    ]
```

- [ ] **Step 4: Run tests — confirm pass**

Run: `uv run pytest tests/test_live_signals_multistrategy.py -v`
Expected: all 18 tests pass (9 snapshot + 9 threshold).

- [ ] **Step 5: Commit**

```bash
git add src/live/signals.py tests/test_live_signals_multistrategy.py
git commit -m "feat(live): threshold entry detector (fire on observation)"
```

---

## Task 9: Candidate enumeration

**Files:**
- Modify: `src/live/signals.py`
- Create: `tests/test_dashboard_candidates.py`

- [ ] **Step 1: Write failing tests for `enumerate_candidates`**

Create `tests/test_dashboard_candidates.py`:

```python
from datetime import datetime, timedelta, timezone

from src.live.bankroll import BankrollState
from src.live.favorites import Favorite
from src.live.signals import enumerate_candidates
from src.storage.models import Market, Position


NOW = datetime(2026, 4, 21, 12, tzinfo=timezone.utc)

SNAP = Favorite(
    label="snapshot_24__earliest_created",
    strategy_name="snapshot",
    params={"offset_hours": 24},
    selection_mode="earliest_created",
    starting_bankroll=1000.0,
    shares_per_trade=10.0,
)
THR = Favorite(
    label="threshold_0.3__earliest_created",
    strategy_name="threshold",
    params={"threshold": 0.3},
    selection_mode="earliest_created",
    starting_bankroll=1000.0,
    shares_per_trade=10.0,
)


def _full_bankroll(fav: Favorite) -> BankrollState:
    return BankrollState(
        strategy=fav.label,
        starting=fav.starting_bankroll,
        locked=0.0,
        realized_pnl=0.0,
        available=fav.starting_bankroll,
        open_positions=0,
        closed_positions=0,
    )


def _add_market(session, mid, *, created_at, question=None, category="geopolitical"):
    m = Market(
        id=mid,
        question=question or f"Will {mid}?",
        category=category,
        no_token_id=f"tok_{mid}",
        created_at=created_at,
    )
    session.add(m)
    return m


def _add_position(session, market_id, strategy):
    pos = Position(
        market_id=market_id, strategy=strategy, executor="paper", status="open",
        entry_price=0.5, entry_timestamp=NOW - timedelta(hours=1),
        size_shares=10.0, size_notional=5.0,
        sizing_rule="fixed_shares", sizing_params_json="{}",
    )
    session.add(pos)
    return pos


def test_snapshot_ready_when_in_window(session):
    _add_market(session, "m", created_at=NOW - timedelta(hours=24))
    session.commit()
    bankrolls = {SNAP.label: _full_bankroll(SNAP)}
    cands = enumerate_candidates(
        session, [SNAP], now=NOW, tolerance_hours=12,
        quote_fn=lambda _t: 0.55, bankrolls=bankrolls,
    )
    by_state = {c.state for c in cands}
    assert "ready" in by_state
    ready = [c for c in cands if c.state == "ready"][0]
    assert ready.market.id == "m"
    assert ready.quote == 0.55


def test_snapshot_waiting_when_too_young(session):
    _add_market(session, "young", created_at=NOW - timedelta(hours=4))
    session.commit()
    bankrolls = {SNAP.label: _full_bankroll(SNAP)}
    cands = enumerate_candidates(
        session, [SNAP], now=NOW, tolerance_hours=12,
        quote_fn=lambda _t: 0.55, bankrolls=bankrolls,
    )
    c = [c for c in cands if c.market.id == "young"][0]
    assert c.state == "waiting"
    assert c.eta_hours is not None and c.eta_hours > 0


def test_snapshot_expired_when_too_old(session):
    _add_market(session, "old", created_at=NOW - timedelta(hours=50))
    session.commit()
    bankrolls = {SNAP.label: _full_bankroll(SNAP)}
    cands = enumerate_candidates(
        session, [SNAP], now=NOW, tolerance_hours=12,
        quote_fn=lambda _t: 0.55, bankrolls=bankrolls,
    )
    c = [c for c in cands if c.market.id == "old"][0]
    assert c.state == "expired"


def test_snapshot_entered_when_position_exists(session):
    m = _add_market(session, "has", created_at=NOW - timedelta(hours=24))
    session.flush()
    _add_position(session, m.id, SNAP.label)
    session.commit()
    bankrolls = {SNAP.label: _full_bankroll(SNAP)}
    cands = enumerate_candidates(
        session, [SNAP], now=NOW, tolerance_hours=12,
        quote_fn=lambda _t: 0.55, bankrolls=bankrolls,
    )
    c = [c for c in cands if c.market.id == "has"][0]
    assert c.state == "entered"


def test_threshold_ready_when_quote_below(session):
    _add_market(session, "dip", created_at=NOW - timedelta(days=2))
    session.commit()
    bankrolls = {THR.label: _full_bankroll(THR)}
    cands = enumerate_candidates(
        session, [THR], now=NOW, tolerance_hours=12,
        quote_fn=lambda _t: 0.25, bankrolls=bankrolls,
    )
    c = [c for c in cands if c.market.id == "dip"][0]
    assert c.state == "ready"
    assert c.target == 0.3


def test_threshold_watching_when_quote_above(session):
    _add_market(session, "hi", created_at=NOW - timedelta(days=2))
    session.commit()
    bankrolls = {THR.label: _full_bankroll(THR)}
    cands = enumerate_candidates(
        session, [THR], now=NOW, tolerance_hours=12,
        quote_fn=lambda _t: 0.6, bankrolls=bankrolls,
    )
    c = [c for c in cands if c.market.id == "hi"][0]
    assert c.state == "watching"
    assert c.quote == 0.6


def test_blocked_by_bankroll_flag(session):
    _add_market(session, "dip", created_at=NOW - timedelta(days=2))
    session.commit()
    # Bankroll too low to afford 10 shares at 0.25 = 2.5 dollars
    bankrolls = {
        THR.label: BankrollState(
            strategy=THR.label, starting=1.0, locked=0.0, realized_pnl=0.0,
            available=1.0, open_positions=0, closed_positions=0,
        )
    }
    cands = enumerate_candidates(
        session, [THR], now=NOW, tolerance_hours=12,
        quote_fn=lambda _t: 0.25, bankrolls=bankrolls,
    )
    c = [c for c in cands if c.market.id == "dip"][0]
    assert c.state == "ready"
    assert c.blocked_by_bankroll is True


def test_cross_strategy_same_market_appears_per_favorite(session):
    _add_market(session, "M", created_at=NOW - timedelta(hours=24))
    session.commit()
    bankrolls = {
        SNAP.label: _full_bankroll(SNAP),
        THR.label: _full_bankroll(THR),
    }
    cands = enumerate_candidates(
        session, [SNAP, THR], now=NOW, tolerance_hours=12,
        quote_fn=lambda _t: 0.25, bankrolls=bankrolls,
    )
    got_labels = {c.favorite.label for c in cands if c.market.id == "M"}
    assert got_labels == {SNAP.label, THR.label}
```

- [ ] **Step 2: Run to confirm failure**

Run: `uv run pytest tests/test_dashboard_candidates.py -v`
Expected: ImportError on `enumerate_candidates`.

- [ ] **Step 3: Add `Candidate` + `enumerate_candidates` to `src/live/signals.py`**

Append to `src/live/signals.py`:

```python
@dataclass(frozen=True)
class Candidate:
    favorite: Favorite
    market: Market
    state: str  # "ready" | "watching" | "waiting" | "expired" | "entered"
    quote: float | None
    target: float | None
    eta_hours: float | None
    age_hours: float
    blocked_by_bankroll: bool


def _classify_snapshot(
    m: Market, fav: Favorite, *, now: datetime, tolerance_hours: int
) -> tuple[str, float | None]:
    created = _ensure_utc(m.created_at)
    age_hours = (now - created).total_seconds() / 3600.0
    offset = fav.params["offset_hours"]
    low = offset - tolerance_hours
    high = offset + tolerance_hours
    if age_hours < low:
        return "waiting", low - age_hours
    if age_hours > high:
        return "expired", None
    return "ready", None


def _classify_threshold(
    quote: float | None, fav: Favorite
) -> str:
    threshold = fav.params["threshold"]
    if quote is None:
        return "watching"
    return "ready" if quote <= threshold else "watching"


def enumerate_candidates(
    session: Session,
    favs: list[Favorite],
    *,
    now: datetime,
    tolerance_hours: int,
    quote_fn: Callable[[str], float | None],
    bankrolls: dict[str, "BankrollState"],
) -> list[Candidate]:
    markets = _load_open_geopolitical_markets(session)
    # Cache: quote per no_token_id (called once per market regardless of fav count).
    quote_cache: dict[str, float | None] = {}

    def _get_quote(token_id: str) -> float | None:
        if token_id not in quote_cache:
            quote_cache[token_id] = quote_fn(token_id)
        return quote_cache[token_id]

    # Per-strategy: markets already entered by this strategy.
    entered_by: dict[str, set[str]] = {
        fav.label: _blocked_by_prior_position(session, fav.label) for fav in favs
    }

    results: list[Candidate] = []
    for m in markets:
        age_hours = (now - _ensure_utc(m.created_at)).total_seconds() / 3600.0
        for fav in favs:
            if m.id in entered_by.get(fav.label, set()):
                state = "entered"
                quote = None
                target = None
                eta = None
            elif fav.strategy_name == "snapshot":
                state, eta = _classify_snapshot(
                    m, fav, now=now, tolerance_hours=tolerance_hours
                )
                quote = _get_quote(m.no_token_id) if state == "ready" else None
                target = None
            else:  # threshold
                quote = _get_quote(m.no_token_id)
                state = _classify_threshold(quote, fav)
                target = fav.params["threshold"]
                eta = None

            blocked = False
            if state == "ready" and quote is not None:
                br = bankrolls.get(fav.label)
                cost = fav.shares_per_trade * quote
                if br is not None and cost > br.available:
                    blocked = True

            results.append(
                Candidate(
                    favorite=fav,
                    market=m,
                    state=state,
                    quote=quote,
                    target=target,
                    eta_hours=eta,
                    age_hours=age_hours,
                    blocked_by_bankroll=blocked,
                )
            )
    return results
```

Also add the forward-ref import at the top of the file (after the existing imports) to avoid circular imports:

```python
from src.live.bankroll import BankrollState
```

- [ ] **Step 4: Run tests — confirm pass**

Run: `uv run pytest tests/test_dashboard_candidates.py -v`
Expected: all 8 tests pass.

- [ ] **Step 5: Run full test suite to verify nothing else broke**

Run: `uv run pytest tests/test_live_signals_multistrategy.py tests/test_live_favorites.py tests/test_live_bankroll.py tests/test_dashboard_candidates.py -v`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/live/signals.py tests/test_dashboard_candidates.py
git commit -m "feat(live): enumerate_candidates for dashboard transparency view"
```

---

## Task 10: Rewrite runner for multi-strategy + bankroll gating

**Files:**
- Modify: `src/live/runner.py`
- Modify: `tests/test_live_runner.py`

- [ ] **Step 1: Rewrite `tests/test_live_runner.py`**

Replace the entire file with:

```python
from datetime import datetime, timedelta, timezone

from src.live.config import LiveConfig, StrategyConfig
from src.live.executor import PaperExecutor
from src.live.notifier import NullNotifier
from src.live.runner import run_once
from src.storage.models import FavoriteStrategy, Market, Position


NOW = datetime(2026, 4, 21, 12, tzinfo=timezone.utc)


def _cfg(**overrides) -> LiveConfig:
    base = dict(
        categories=["geopolitical"],
        tolerance_hours=12,
        executor="paper",
        strategies={
            "snapshot_24__earliest_created": StrategyConfig(
                label="snapshot_24__earliest_created",
                starting_bankroll=1000.0,
                shares_per_trade=10.0,
            ),
            "threshold_0.3__earliest_created": StrategyConfig(
                label="threshold_0.3__earliest_created",
                starting_bankroll=1000.0,
                shares_per_trade=10.0,
            ),
        },
        telegram_bot_token=None,
        telegram_chat_id=None,
    )
    base.update(overrides)
    return LiveConfig(**base)


def _add_favorites(session, labels):
    for label in labels:
        session.add(FavoriteStrategy(strategy=label))
    session.flush()


def _open_market_row(mid, *, question="Will X happen by May 10, 2026?",
                     created_at=NOW - timedelta(hours=24),
                     category="geopolitical") -> dict:
    return dict(
        id=mid, question=question, category=category,
        no_token_id=f"tok_{mid}", created_at=created_at,
        end_date=None, resolved_at=None, resolution=None,
        source_url=f"https://polymarket.com/{mid}",
    )


def test_run_once_opens_snapshot_position(session):
    _add_favorites(session, ["snapshot_24__earliest_created"])
    session.commit()

    fetched = [_open_market_row("m1")]

    stats = run_once(
        session, _cfg(), now=NOW,
        executor=PaperExecutor(session), notifier=NullNotifier(),
        fetch_open_fn=lambda cats: fetched,
        quote_fn=lambda _tok: 0.5,
    )
    session.commit()

    positions = session.query(Position).all()
    assert len(positions) == 1
    pos = positions[0]
    assert pos.strategy == "snapshot_24__earliest_created"
    assert pos.size_shares == 10.0
    assert pos.sizing_rule == "fixed_shares"
    assert pos.entry_price == 0.5
    assert stats["positions_opened"] == 1


def test_run_once_opens_threshold_position_when_quote_low(session):
    _add_favorites(session, ["threshold_0.3__earliest_created"])
    session.commit()

    fetched = [_open_market_row("t1", created_at=NOW - timedelta(days=2))]

    run_once(
        session, _cfg(), now=NOW,
        executor=PaperExecutor(session), notifier=NullNotifier(),
        fetch_open_fn=lambda cats: fetched,
        quote_fn=lambda _tok: 0.25,
    )
    session.commit()

    positions = session.query(Position).all()
    assert [p.strategy for p in positions] == ["threshold_0.3__earliest_created"]
    assert positions[0].entry_price == 0.25


def test_run_once_both_strategies_same_market(session):
    _add_favorites(session, [
        "snapshot_24__earliest_created",
        "threshold_0.3__earliest_created",
    ])
    session.commit()

    fetched = [_open_market_row("shared", created_at=NOW - timedelta(hours=24))]

    run_once(
        session, _cfg(), now=NOW,
        executor=PaperExecutor(session), notifier=NullNotifier(),
        fetch_open_fn=lambda cats: fetched,
        quote_fn=lambda _tok: 0.2,  # qualifies for both
    )
    session.commit()

    positions = session.query(Position).all()
    strategies = {p.strategy for p in positions}
    assert strategies == {
        "snapshot_24__earliest_created",
        "threshold_0.3__earliest_created",
    }


def test_run_once_gates_on_bankroll(session):
    _add_favorites(session, ["threshold_0.3__earliest_created"])
    session.commit()

    # Two markets, both would fire. Bankroll = 1.0 only covers one trade at 0.25 * 10 = 2.5.
    fetched = [
        _open_market_row(f"t{i}", question=f"Will t{i}?", created_at=NOW - timedelta(days=2))
        for i in range(2)
    ]

    cfg = _cfg(strategies={
        "threshold_0.3__earliest_created": StrategyConfig(
            label="threshold_0.3__earliest_created",
            starting_bankroll=1.0,
            shares_per_trade=10.0,
        )
    })

    run_once(
        session, cfg, now=NOW,
        executor=PaperExecutor(session), notifier=NullNotifier(),
        fetch_open_fn=lambda cats: fetched,
        quote_fn=lambda _tok: 0.25,
    )
    session.commit()

    assert session.query(Position).count() == 0  # none can afford


def test_run_once_in_memory_bankroll_prevents_double_spend(session):
    _add_favorites(session, ["threshold_0.3__earliest_created"])
    session.commit()

    # Two markets. Bankroll = 3.0. Each trade is 0.25 * 10 = 2.5.
    # First trade OK (3.0 - 2.5 = 0.5 remaining), second must be skipped.
    fetched = [
        _open_market_row(f"t{i}", question=f"Will q{i}?", created_at=NOW - timedelta(days=2))
        for i in range(2)
    ]
    cfg = _cfg(strategies={
        "threshold_0.3__earliest_created": StrategyConfig(
            label="threshold_0.3__earliest_created",
            starting_bankroll=3.0,
            shares_per_trade=10.0,
        )
    })

    run_once(
        session, cfg, now=NOW,
        executor=PaperExecutor(session), notifier=NullNotifier(),
        fetch_open_fn=lambda cats: fetched,
        quote_fn=lambda _tok: 0.25,
    )
    session.commit()

    assert session.query(Position).count() == 1


def test_run_once_marks_and_resolves_as_before(session):
    _add_favorites(session, ["snapshot_24__earliest_created"])
    m = Market(
        id="mResolve",
        question="Will Y?",
        category="geopolitical",
        no_token_id="tok_mResolve",
        created_at=NOW - timedelta(days=10),
        end_date=NOW - timedelta(days=1),
        resolved_at=NOW - timedelta(days=1),
        resolution="No",
    )
    session.add(m)
    session.flush()
    pos = Position(
        market_id="mResolve",
        strategy="snapshot_24__earliest_created",
        executor="paper",
        status="open",
        entry_price=0.4,
        entry_timestamp=NOW - timedelta(days=9),
        size_shares=10.0,
        size_notional=4.0,
        sizing_rule="fixed_shares",
        sizing_params_json="{}",
    )
    session.add(pos)
    session.commit()

    stats = run_once(
        session, _cfg(), now=NOW,
        executor=PaperExecutor(session), notifier=NullNotifier(),
        fetch_open_fn=lambda cats: [],
        quote_fn=lambda _tok: 0.99,
    )
    session.commit()

    got = session.get(Position, pos.id)
    assert got.status == "resolved"
    assert got.exit_price == 1.0
    assert got.realized_pnl == (1.0 - 0.4) * 10.0
    assert stats["positions_resolved"] == 1


def test_run_once_dry_run_writes_nothing(session):
    _add_favorites(session, ["snapshot_24__earliest_created"])
    session.commit()

    fetched = [_open_market_row("mDry")]

    stats = run_once(
        session, _cfg(), now=NOW,
        executor=PaperExecutor(session), notifier=NullNotifier(),
        fetch_open_fn=lambda cats: fetched,
        quote_fn=lambda _tok: 0.5,
        dry_run=True,
    )
    session.rollback()

    assert session.get(Market, "mDry") is None
    assert session.query(Position).count() == 0
    assert stats["dry_run"] is True
```

- [ ] **Step 2: Run to confirm failure**

Run: `uv run pytest tests/test_live_runner.py -v`
Expected: runner still uses old single-strategy API — tests fail on config shape.

- [ ] **Step 3: Rewrite `src/live/runner.py`**

Replace the entire file with:

```python
"""One-pass orchestrator for the multi-strategy live paper-trading bot.

Run by cron every ~6 hours. In a single pass:

  1. Fetch open markets from Gamma and upsert rows.
  2. Load favorites from the DB + config.
  3. Per favorite: detect entry signals and bankroll-gate them before
     opening paper positions.
  4. Mark all open positions to market via the executor.
  5. Close any positions whose market has resolved; notify on resolution.

All external calls (Gamma, CLOB) are dependency-injected so tests can
drive the runner with deterministic fixtures.
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import replace
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy.orm import Session

from src.live.bankroll import compute_bankroll
from src.live.config import LiveConfig, load_config
from src.live.executor import Executor, get_executor
from src.live.favorites import Favorite, load_favorites
from src.live.notifier import Notifier, get_notifier
from src.live.resolution import sync_resolutions
from src.live.signals import detect_snapshot_entries, detect_threshold_entries
from src.live.sizing import SizingResult
from src.storage.models import Market, Position

logger = logging.getLogger(__name__)

FetchOpenFn = Callable[[list[str] | None], list[dict]]
QuoteFn = Callable[[str], float | None]


def _upsert_open_market(session: Session, row: dict) -> bool:
    existing = session.get(Market, row["id"])
    if existing is not None:
        for attr in ("question", "category", "no_token_id", "end_date"):
            if attr in row and row[attr] is not None:
                setattr(existing, attr, row[attr])
        return False
    session.add(Market(**row))
    return True


def _detect_for(
    session: Session,
    fav: Favorite,
    *,
    now: datetime,
    tolerance_hours: int,
    quote_fn: QuoteFn,
):
    if fav.strategy_name == "snapshot":
        return detect_snapshot_entries(
            session, fav, now=now, tolerance_hours=tolerance_hours, quote_fn=quote_fn
        )
    if fav.strategy_name == "threshold":
        return detect_threshold_entries(session, fav, now=now, quote_fn=quote_fn)
    raise ValueError(f"unsupported strategy in runner: {fav.strategy_name}")


def run_once(
    session: Session,
    config: LiveConfig,
    *,
    now: datetime,
    executor: Executor,
    notifier: Notifier,
    fetch_open_fn: FetchOpenFn,
    quote_fn: QuoteFn,
    dry_run: bool = False,
) -> dict:
    stats = {
        "markets_seen": 0,
        "markets_upserted": 0,
        "positions_opened": 0,
        "positions_marked": 0,
        "positions_resolved": 0,
        "dry_run": dry_run,
    }

    # 1. Upsert open markets.
    try:
        raw_markets = fetch_open_fn(config.categories) or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("fetch_open_fn failed: %s", exc)
        raw_markets = []
    stats["markets_seen"] = len(raw_markets)
    for row in raw_markets:
        if _upsert_open_market(session, row):
            stats["markets_upserted"] += 1
    session.flush()

    # 2. Load favorites.
    favorites = load_favorites(session, config)

    # 3. Per favorite: detect → gate → open.
    for fav in favorites:
        signals = _detect_for(
            session, fav, now=now,
            tolerance_hours=config.tolerance_hours,
            quote_fn=quote_fn,
        )
        bankroll = compute_bankroll(session, fav.label, fav.starting_bankroll)
        for sig in signals:
            cost = fav.shares_per_trade * sig.entry_price
            if cost > bankroll.available:
                logger.info(
                    "skip %s for %s: need %.2f, have %.2f",
                    sig.market.id, fav.label, cost, bankroll.available,
                )
                continue
            sizing = SizingResult(
                shares=fav.shares_per_trade,
                notional=cost,
                rule="fixed_shares",
                params={"shares": fav.shares_per_trade},
            )
            pos = executor.open_position(
                market=sig.market,
                entry_price=sig.entry_price,
                entry_timestamp=sig.entry_timestamp,
                sizing_result=sizing,
                strategy=fav.label,
            )
            stats["positions_opened"] += 1
            bankroll = replace(
                bankroll,
                locked=bankroll.locked + cost,
                available=bankroll.available - cost,
                open_positions=bankroll.open_positions + 1,
            )
            try:
                notifier.on_entry(pos, sig.market)
            except Exception as exc:  # noqa: BLE001
                logger.warning("notifier.on_entry failed: %s", exc)

    # 4. Mark-to-market open positions.
    open_positions = session.query(Position).filter(Position.status == "open").all()
    for pos in open_positions:
        market = session.get(Market, pos.market_id)
        if market is None:
            continue
        try:
            mid = quote_fn(market.no_token_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("quote_fn failed for %s: %s", market.no_token_id, exc)
            mid = None
        if mid is None:
            continue
        executor.mark_position(pos, mid=mid, at=now)
        stats["positions_marked"] += 1

    # 5. Sync resolutions + notify.
    closed = sync_resolutions(session, executor, now=now)
    stats["positions_resolved"] = len(closed)
    for pos in closed:
        market = session.get(Market, pos.market_id)
        if market is None:
            continue
        try:
            notifier.on_resolution(pos, market)
        except Exception as exc:  # noqa: BLE001
            logger.warning("notifier.on_resolution failed: %s", exc)

    if dry_run:
        session.rollback()
    else:
        session.commit()
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Live paper-trading runner")
    parser.add_argument("--dry-run", action="store_true", help="Skip DB writes")
    args = parser.parse_args()

    from src.live.open_markets import fetch_open_markets
    from src.live.quotes import fetch_midpoint
    from src.storage.db import get_engine, get_session

    config = load_config()
    engine = get_engine()
    session = get_session(engine)

    executor = get_executor(config.executor, session)
    notifier = get_notifier()

    stats = run_once(
        session,
        config,
        now=datetime.now(tz=timezone.utc),
        executor=executor,
        notifier=notifier,
        fetch_open_fn=lambda cats: fetch_open_markets(categories=cats),
        quote_fn=fetch_midpoint,
        dry_run=args.dry_run,
    )
    print(json.dumps(stats, indent=2))
    session.close()
    engine.dispose()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_live_runner.py -v`
Expected: all 7 tests pass.

- [ ] **Step 5: Run all live tests to verify no regressions**

Run: `uv run pytest tests/ -v`
Expected: all tests pass. If `tests/test_live_signals.py` is reported as missing, that's expected (it was deleted in Task 7).

- [ ] **Step 6: Commit**

```bash
git add src/live/runner.py tests/test_live_runner.py
git commit -m "feat(live): multi-strategy runner with per-strategy bankroll gating"
```

---

## Task 11: Candidates dashboard view

**Files:**
- Modify: `src/dashboard/app.py`

- [ ] **Step 1: Add `render_candidates` view function**

In `src/dashboard/app.py`, near the other `render_*` functions, add:

```python
# ---- View: Candidates ----

def render_candidates():
    from src.live.bankroll import compute_bankroll
    from src.live.config import load_config
    from src.live.favorites import load_favorites
    from src.live.quotes import fetch_midpoint
    from src.live.signals import enumerate_candidates
    from datetime import datetime, timezone

    st.header("Candidates")
    st.caption(
        "Open markets scored against each favorited strategy. `ready` = would fire "
        "next tick; `watching` = threshold not hit; `waiting`/`expired` = snapshot "
        "window; `entered` = position already exists. Read-only."
    )

    try:
        config = load_config()
    except FileNotFoundError:
        st.error(
            "live_config.yaml not found. Copy live_config.example.yaml and edit."
        )
        return

    favs = load_favorites(session, config)
    if not favs:
        st.warning(
            "No favorites active. Favourite strategies on the Strategy Comparison tab "
            "and add matching entries to live_config.yaml."
        )
        return

    bankrolls = {
        f.label: compute_bankroll(session, f.label, f.starting_bankroll) for f in favs
    }

    # --- Bankroll summary ---
    st.subheader("Bankrolls")
    rows = []
    for f in favs:
        b = bankrolls[f.label]
        rows.append({
            "Strategy": f.label,
            "Starting": b.starting,
            "Locked": b.locked,
            "Realized P&L": b.realized_pnl,
            "Available": b.available,
            "Open": b.open_positions,
            "Closed": b.closed_positions,
        })
    st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        width="stretch",
        column_config={
            "Starting": st.column_config.NumberColumn(format="$%.2f"),
            "Locked": st.column_config.NumberColumn(format="$%.2f"),
            "Realized P&L": st.column_config.NumberColumn(format="$%+.2f"),
            "Available": st.column_config.NumberColumn(format="$%.2f"),
        },
    )

    # --- Candidate tabs ---
    st.subheader("Candidates")
    now = datetime.now(tz=timezone.utc)
    cands = enumerate_candidates(
        session, favs,
        now=now,
        tolerance_hours=config.tolerance_hours,
        quote_fn=fetch_midpoint,
        bankrolls=bankrolls,
    )

    state_order = {"ready": 0, "watching": 1, "waiting": 2, "expired": 3, "entered": 4}

    tabs = st.tabs([f.label for f in favs])
    for tab, fav in zip(tabs, favs):
        with tab:
            fav_cands = [c for c in cands if c.favorite.label == fav.label]
            if not fav_cands:
                st.info("No open markets in scope.")
                continue
            fav_cands.sort(key=lambda c: (
                state_order.get(c.state, 99),
                c.quote if c.quote is not None else 99,
                c.eta_hours if c.eta_hours is not None else 9999,
            ))
            rows = []
            for c in fav_cands[:200]:
                rows.append({
                    "State": c.state,
                    "Question": c.market.question,
                    "Quote": c.quote,
                    "Target": c.target,
                    "ETA (h)": c.eta_hours,
                    "Age (h)": c.age_hours,
                    "Blocked?": "!" if c.blocked_by_bankroll else "",
                    "URL": c.market.source_url or "",
                })
            st.dataframe(
                pd.DataFrame(rows),
                hide_index=True,
                width="stretch",
                column_config={
                    "Quote": st.column_config.NumberColumn(format="%.4f"),
                    "Target": st.column_config.NumberColumn(format="%.4f"),
                    "ETA (h)": st.column_config.NumberColumn(format="%.1f"),
                    "Age (h)": st.column_config.NumberColumn(format="%.1f"),
                    "URL": st.column_config.LinkColumn("Link", display_text="open"),
                },
            )
```

- [ ] **Step 2: Wire the view into the sidebar radio**

Find the sidebar navigation at around line 143 (the `view = st.sidebar.radio(...)` block). Update the options list and the dispatch at the bottom of the file:

```python
view = st.sidebar.radio(
    "View",
    [
        "Thesis Overview",
        "Live Positions",
        "Candidates",
        "Strategy Comparison",
        "Sizing Comparison",
        "Deep Dive",
        "Market Browser",
    ],
)
```

At the bottom of the file, in the view-dispatch block, add:

```python
elif view == "Candidates":
    render_candidates()
```

- [ ] **Step 3: Smoke-test the dashboard locally**

Run: `uv run streamlit run src/dashboard/app.py`
Open `http://localhost:8501`, click **Candidates** in the sidebar.
Expected: bankroll table renders at top; one tab per favorite in `favorite_strategies`. If `live_config.yaml` isn't set up, the view shows a helpful error.

- [ ] **Step 4: Commit**

```bash
git add src/dashboard/app.py
git commit -m "feat(dashboard): candidates view with per-strategy bankroll + states"
```

---

## Task 12: Per-strategy tabs on Live Positions

**Files:**
- Modify: `src/dashboard/app.py`

- [ ] **Step 1: Refactor `render_live_positions` to use strategy tabs**

Replace the existing `render_live_positions` function (at around line 699) with:

```python
def _render_positions_panel(
    positions: list[Position],
    markets_by_id: dict[str, Market],
    *,
    bankroll: "BankrollState | None" = None,
    now: datetime,
) -> None:
    """Render metrics + open/closed tables + equity curve for a filtered set."""
    open_pos = [p for p in positions if p.status == "open"]
    closed_pos = [p for p in positions if p.status != "open"]

    realized = sum((p.realized_pnl or 0.0) for p in closed_pos)
    unrealized = sum((p.unrealized_pnl or 0.0) for p in open_pos)
    wins = sum(1 for p in closed_pos if (p.realized_pnl or 0.0) > 0)
    win_rate = wins / len(closed_pos) if closed_pos else 0.0

    if bankroll is not None:
        if bankroll.available < bankroll.starting * 0.01:
            st.warning(
                f"{bankroll.strategy} is bankroll-exhausted — no new entries "
                "until a winning position closes."
            )
        c1, c2, c3, c4, c5, c6, c7 = st.columns(7)
        c1.metric("Starting", f"${bankroll.starting:,.0f}")
        c2.metric("Available", f"${bankroll.available:,.2f}")
        c3.metric("Locked", f"${bankroll.locked:,.2f}")
        c4.metric("Realized P&L", f"${bankroll.realized_pnl:+,.2f}")
        c5.metric("Unrealized", f"${unrealized:+,.2f}")
        c6.metric("Win rate", f"{win_rate:.1%}" if closed_pos else "—")
        c7.metric("Open / Closed", f"{len(open_pos)} / {len(closed_pos)}")
    else:
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Open", len(open_pos))
        c2.metric("Resolved", len(closed_pos))
        c3.metric("Realized P&L", f"${realized:+,.2f}")
        c4.metric("Unrealized P&L", f"${unrealized:+,.2f}")
        c5.metric("Win rate", f"{win_rate:.1%}" if closed_pos else "—")

    st.subheader(f"Open positions ({len(open_pos)})")
    if open_pos:
        rows = []
        for p in open_pos:
            m = markets_by_id.get(p.market_id)
            entry_ts = p.entry_timestamp
            age = (now - entry_ts.replace(tzinfo=None)).total_seconds() if entry_ts else 0.0
            rows.append({
                "Question": m.question if m else p.market_id,
                "Strategy": p.strategy,
                "Category": m.category if m else "",
                "Age": _humanize_age(age),
                "Entry": p.entry_price,
                "Mid": p.last_mark_price,
                "Shares": p.size_shares,
                "Unrealized": p.unrealized_pnl,
                "Entered": p.entry_timestamp,
            })
        st.dataframe(
            pd.DataFrame(rows),
            width="stretch",
            hide_index=True,
            column_config={
                "Entry": st.column_config.NumberColumn(format="$%.4f"),
                "Mid": st.column_config.NumberColumn(format="$%.4f"),
                "Unrealized": st.column_config.NumberColumn(format="$%+.2f"),
                "Entered": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm"),
            },
        )

    st.subheader(f"Resolved positions ({len(closed_pos)})")
    if closed_pos:
        rows = []
        for p in sorted(closed_pos, key=lambda x: x.exit_timestamp or datetime.min, reverse=True):
            m = markets_by_id.get(p.market_id)
            rows.append({
                "Question": m.question if m else p.market_id,
                "Strategy": p.strategy,
                "Entry": p.entry_price,
                "Exit": p.exit_price,
                "Realized": p.realized_pnl,
                "Entered": p.entry_timestamp,
                "Exited": p.exit_timestamp,
            })
        st.dataframe(
            pd.DataFrame(rows),
            width="stretch",
            hide_index=True,
            column_config={
                "Entry": st.column_config.NumberColumn(format="$%.4f"),
                "Exit": st.column_config.NumberColumn(format="$%.2f"),
                "Realized": st.column_config.NumberColumn(format="$%+.2f"),
                "Entered": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm"),
                "Exited": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm"),
            },
        )

    # Equity curve = cumulative realized over time.
    realized_rows = sorted(
        [p for p in closed_pos if p.exit_timestamp],
        key=lambda p: p.exit_timestamp,
    )
    if realized_rows:
        eq_df = pd.DataFrame([
            {"Date": p.exit_timestamp, "Realized": p.realized_pnl or 0.0}
            for p in realized_rows
        ])
        eq_df["Cumulative"] = eq_df["Realized"].cumsum()
        fig = px.line(eq_df, x="Date", y="Cumulative", title="Cumulative realized P&L")
        if bankroll is not None:
            fig.add_hline(y=0, line_dash="dot", line_color="gray")
        st.plotly_chart(fig, width="stretch")


def render_live_positions():
    from src.live.bankroll import compute_bankroll
    from src.live.config import load_config
    from src.live.favorites import load_favorites

    st.header("Live Positions")

    positions = session.query(Position).all()
    if not positions:
        st.info("No live positions yet. Run `uv run python -m src.live.runner`.")
        return

    market_ids = [p.market_id for p in positions]
    markets_by_id = {
        m.id: m
        for m in session.query(Market).filter(Market.id.in_(market_ids)).all()
    }
    now = datetime.utcnow()

    # Config is optional — the All tab works without it.
    try:
        config = load_config()
        favs = load_favorites(session, config)
    except FileNotFoundError:
        config = None
        favs = []

    tab_labels = ["All"] + [f.label for f in favs]
    tabs = st.tabs(tab_labels)

    with tabs[0]:
        _render_positions_panel(positions, markets_by_id, bankroll=None, now=now)

    for tab, fav in zip(tabs[1:], favs):
        with tab:
            scoped = [p for p in positions if p.strategy == fav.label]
            bankroll = compute_bankroll(session, fav.label, fav.starting_bankroll)
            if not scoped:
                st.info(f"No positions for {fav.label} yet.")
                # Still render bankroll metrics so starting bankroll is visible.
            _render_positions_panel(scoped, markets_by_id, bankroll=bankroll, now=now)
```

- [ ] **Step 2: Smoke-test**

Run: `uv run streamlit run src/dashboard/app.py`
Open the **Live Positions** view. You should see "All" + one tab per favorite. Each strategy tab shows a 7-metric row (Starting / Available / Locked / Realized / Unrealized / Win rate / Open/Closed).

- [ ] **Step 3: Commit**

```bash
git add src/dashboard/app.py
git commit -m "feat(dashboard): per-strategy tabs + bankroll panel on Live Positions"
```

---

## Task 13: Update README + CLAUDE.md hints

**Files:**
- Modify: `README.md` (if it exists)
- Modify: `CLAUDE.md`

- [ ] **Step 1: Check for README**

Run: `ls README.md 2>/dev/null`
If present: update the live-bot section. If absent, skip to CLAUDE.md.

- [ ] **Step 2: Update `CLAUDE.md` live-bot commands section**

In `CLAUDE.md`, find the Commands section and add under it (or update existing live-bot hints):

```markdown
# Live paper-trading bot (reads favorite_strategies table + live_config.yaml)
cp live_config.example.yaml live_config.yaml  # first-time setup
uv run python -m src.live.runner               # one pass; cron this every 6h
uv run python -m src.live.runner --dry-run     # no DB writes
```

Also add a short paragraph to the Architecture section (under `src/live/`) describing the multi-strategy model:

```markdown
The live runner is driven by the `favorite_strategies` DB table (populated via
the dashboard Strategy Comparison star-toggle) plus `live_config.yaml` (per-
strategy bankroll + shares-per-trade). Each enabled favorite gets its own
independent bankroll that compounds on wins: each trade locks
`shares * entry_price`, and on resolution the full `shares * exit_price`
returns (1.0 for a winning No-resolution, 0 for a loss). `detect_snapshot_entries`
and `detect_threshold_entries` share the `EntrySignal` output; the runner
bankroll-gates each signal before `executor.open_position`. Scope is
geopolitical-only; cron cadence is 6 hours (±12h snapshot tolerance absorbs
this comfortably).
```

- [ ] **Step 3: Run full test suite**

Run: `uv run pytest`
Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: live bot multi-strategy model + 6h cron cadence"
```

---

## Final verification

- [ ] **Run the full test suite one more time**

Run: `uv run pytest -v`
Expected: all tests green.

- [ ] **Full smoke test the runner against the real DB**

Run: `uv run python -m src.live.runner --dry-run`
Expected: prints a JSON stats block (markets_seen, markets_upserted, positions_opened, positions_marked, positions_resolved, dry_run=true). No errors. No rows written (rollback at end).

- [ ] **Confirm dashboard renders**

Run: `uv run streamlit run src/dashboard/app.py`
Navigate: Live Positions (tabs work, All + per-strategy); Candidates (bankroll row + per-strategy tabs render). If `live_config.yaml` is missing, a helpful error shows instead of a crash.

---

## Self-Review

**Spec coverage:**

| Spec section | Covered by |
|---|---|
| Data flow diagram | Tasks 4–10 wire the pipeline end-to-end |
| `src/live/favorites.py` | Tasks 4, 5 |
| `src/live/bankroll.py` | Task 6 |
| `src/live/signals.py` rewrite (snapshot + threshold + enumerate) | Tasks 7, 8, 9 |
| `src/live/config.py` YAML + StrategyConfig | Task 3 |
| `src/live/runner.py` loop + gating | Task 10 |
| Cron cadence docs (6h) | Task 13 |
| Candidates dashboard view | Task 11 |
| Live Positions per-strategy tabs + warning | Task 12 |
| `pyyaml` dependency | Task 1 |
| Accounting model (starting - locked + realized) | Task 6 tests cover all four cases |
| Per-(market, strategy) dedup | Tasks 7, 8 explicit tests |
| Threshold fires on open-below-threshold markets | Task 8, `test_threshold_fires_on_market_that_opened_below` |
| In-memory bankroll update within tick | Task 10, `test_run_once_in_memory_bankroll_prevents_double_spend` |
| Bankroll-exhausted warning | Task 12 |
| Secrets stay in env | Task 3 config shape |
| No schema changes | No migrations in any task |

**Placeholder scan:** No TBDs, no "similar to above," no "handle edge cases" steps. Every test shows the assertion; every implementation shows the code.

**Type consistency:**
- `Favorite` fields consistent across Tasks 4–11.
- `EntrySignal` carries `favorite` (not `strategy_label`) consistently across Tasks 7, 8, 10.
- `BankrollState` fields consistent across Tasks 6, 9, 10, 11, 12.
- `Candidate` fields consistent across Tasks 9, 11.
- `SizingResult` constructed in Task 10 matches the existing `src/live/sizing.py` dataclass.
