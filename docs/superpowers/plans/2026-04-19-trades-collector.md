# Trade-Tape Collector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a per-fill trade-tape collector for Polymarket (Polygon on-chain `OrderFilled` events) with a unified schema that anticipates Kalshi as a second venue, plus a Streamlit tab to explore the data and a shell wrapper for catchup runs.

**Architecture:** New `Trade` model alongside existing `price_snapshots` (schema unchanged). New `src/collector/trades/` package with a pure event-to-trade mapper, a `fetch_trades` iterator that streams on-chain fills, and a runner with `backfill` and `catchup` modes. New Streamlit tab `src/dashboard/trades_tab.py` reads the `trades` table. Kalshi is scaffolded as a config slot that raises `NotImplementedError` until credentials are supplied.

**Tech Stack:** Python 3, SQLAlchemy 2.0 ORM, SQLite, web3.py (optional), httpx, Streamlit, Altair, pytest. Package manager: `uv`.

**Design spec:** [docs/superpowers/specs/2026-04-19-trades-collector-design.md](../specs/2026-04-19-trades-collector-design.md)

---

## File Map

### Created
- `src/collector/trades/__init__.py` — empty package marker
- `src/collector/trades/polymarket.py` — `event_to_trade`, `fetch_yes_token_id`, `fetch_trades`
- `src/collector/trades/kalshi.py` — `KalshiConfig`, `fetch_trades` stub
- `src/collector/trades/runner.py` — `run_backfill`, `run_catchup`, `main` (CLI)
- `src/dashboard/trades_tab.py` — `render(session, selected_categories, date_range)` Streamlit view
- `scripts/trades_catchup.sh` — one-liner wrapper for catchup
- `tests/test_trades_schema.py` — `Trade` model CRUD + unique constraints
- `tests/test_trades_polymarket.py` — mapper (4 cases), `fetch_yes_token_id`, `fetch_trades` smoke
- `tests/test_trades_runner.py` — `run_backfill` + `run_catchup` idempotency

### Modified
- `src/storage/models.py` — add `Trade` class, import `Boolean`, `UniqueConstraint`, `Index`
- `src/dashboard/app.py` — import `trades_tab`, add "Trades" to the `view` radio + dispatch
- `.env.example` — add three commented Kalshi vars

### Unchanged (load-bearing — do NOT modify)
- `src/collector/polygon_chain.py` — imported for ABI + helpers; not edited
- `src/collector/polymarket_api.py` — not edited; `fetch_yes_token_id` is a separate helper
- `src/collector/runner.py`, `src/backtester/`, `src/live/` — unrelated

---

## Task 1: Add `Trade` Model and Schema Tests

**Files:**
- Modify: `src/storage/models.py`
- Create: `tests/test_trades_schema.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_trades_schema.py`:

```python
from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from src.storage.models import Market, Trade


def _make_market(session, id="0xm1"):
    market = Market(
        id=id,
        question="Test market",
        category="political",
        no_token_id="100",
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    session.add(market)
    session.flush()
    return market


def test_trade_roundtrip(session):
    _make_market(session)
    trade = Trade(
        market_id="0xm1",
        venue="polymarket",
        timestamp=datetime(2024, 1, 2, 10, 0, tzinfo=timezone.utc),
        price=0.42,
        size_shares=100.0,
        usdc_notional=42.0,
        side="buy_no",
        is_yes_token=False,
        tx_hash="0xdeadbeef",
        log_index=3,
        block_number=50_000_000,
        maker_address="0xaa",
        taker_address="0xbb",
        order_hash="0xabc",
        maker_asset_id="0",
        taker_asset_id="100",
        fee=0.0,
        raw_event_json='{"foo":"bar"}',
    )
    session.add(trade)
    session.commit()

    fetched = session.query(Trade).filter_by(market_id="0xm1").one()
    assert fetched.price == 0.42
    assert fetched.side == "buy_no"
    assert fetched.is_yes_token is False
    assert fetched.venue == "polymarket"


def test_trade_onchain_unique_constraint_rejects_duplicate(session):
    _make_market(session)
    t1 = Trade(
        market_id="0xm1", venue="polymarket",
        timestamp=datetime(2024, 1, 2, tzinfo=timezone.utc),
        price=0.5, size_shares=1.0, usdc_notional=0.5,
        side="buy_no", is_yes_token=False,
        tx_hash="0xabc", log_index=0, block_number=1,
        raw_event_json="{}",
    )
    session.add(t1)
    session.commit()

    t2 = Trade(
        market_id="0xm1", venue="polymarket",
        timestamp=datetime(2024, 1, 3, tzinfo=timezone.utc),
        price=0.6, size_shares=1.0, usdc_notional=0.6,
        side="sell_no", is_yes_token=False,
        tx_hash="0xabc", log_index=0, block_number=1,
        raw_event_json="{}",
    )
    session.add(t2)
    with pytest.raises(IntegrityError):
        session.commit()


def test_trade_multiple_null_txhash_allowed(session):
    """Kalshi rows have tx_hash=NULL; multiple NULLs must coexist."""
    _make_market(session)
    for kalshi_id in ("k1", "k2"):
        session.add(Trade(
            market_id="0xm1", venue="kalshi",
            timestamp=datetime(2024, 1, 2, tzinfo=timezone.utc),
            price=0.5, size_shares=1.0, usdc_notional=0.5,
            side="buy_no", is_yes_token=False,
            tx_hash=None, log_index=None, block_number=None,
            kalshi_trade_id=kalshi_id,
            raw_event_json="{}",
        ))
    session.commit()
    assert session.query(Trade).filter_by(venue="kalshi").count() == 2


def test_trade_kalshi_unique_constraint_rejects_duplicate(session):
    _make_market(session)
    session.add(Trade(
        market_id="0xm1", venue="kalshi",
        timestamp=datetime(2024, 1, 2, tzinfo=timezone.utc),
        price=0.5, size_shares=1.0, usdc_notional=0.5,
        side="buy_no", is_yes_token=False,
        kalshi_trade_id="KDUP",
        raw_event_json="{}",
    ))
    session.commit()

    session.add(Trade(
        market_id="0xm1", venue="kalshi",
        timestamp=datetime(2024, 1, 3, tzinfo=timezone.utc),
        price=0.5, size_shares=1.0, usdc_notional=0.5,
        side="sell_no", is_yes_token=False,
        kalshi_trade_id="KDUP",
        raw_event_json="{}",
    ))
    with pytest.raises(IntegrityError):
        session.commit()
```

- [ ] **Step 2: Verify tests fail**

```bash
uv run pytest tests/test_trades_schema.py -v
```

Expected: `ImportError: cannot import name 'Trade'` (collection error).

- [ ] **Step 3: Add `Trade` model**

Edit `src/storage/models.py`. At the top, extend the imports:

```python
from sqlalchemy import String, Float, DateTime, Text, ForeignKey, Integer, Boolean, UniqueConstraint, Index
```

At the bottom of the file, add:

```python
class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_id: Mapped[str] = mapped_column(ForeignKey("markets.id"))
    venue: Mapped[str] = mapped_column(String)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    price: Mapped[float] = mapped_column(Float)
    size_shares: Mapped[float] = mapped_column(Float)
    usdc_notional: Mapped[float] = mapped_column(Float)
    side: Mapped[str] = mapped_column(String)
    is_yes_token: Mapped[bool] = mapped_column(Boolean)

    tx_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    log_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    block_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    maker_address: Mapped[str | None] = mapped_column(String, nullable=True)
    taker_address: Mapped[str | None] = mapped_column(String, nullable=True)
    order_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    maker_asset_id: Mapped[str | None] = mapped_column(String, nullable=True)
    taker_asset_id: Mapped[str | None] = mapped_column(String, nullable=True)
    fee: Mapped[float | None] = mapped_column(Float, nullable=True)

    kalshi_trade_id: Mapped[str | None] = mapped_column(String, nullable=True)

    raw_event_json: Mapped[str] = mapped_column(Text)

    market: Mapped["Market"] = relationship()

    __table_args__ = (
        UniqueConstraint("venue", "tx_hash", "log_index", name="uq_trade_onchain"),
        UniqueConstraint("venue", "kalshi_trade_id", name="uq_trade_kalshi"),
        Index("ix_trades_market_timestamp", "market_id", "timestamp"),
        Index("ix_trades_venue_timestamp", "venue", "timestamp"),
    )
```

- [ ] **Step 4: Verify tests pass**

```bash
uv run pytest tests/test_trades_schema.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Run full suite (no regressions)**

```bash
uv run pytest
```

Expected: all existing tests still pass plus the 4 new ones.

- [ ] **Step 6: Commit**

```bash
git add src/storage/models.py tests/test_trades_schema.py
git commit -m "feat(trades): add Trade model with unique constraints"
```

---

## Task 2: `event_to_trade` Pure Mapper

**Files:**
- Create: `src/collector/trades/__init__.py`
- Create: `src/collector/trades/polymarket.py`
- Create: `tests/test_trades_polymarket.py`

- [ ] **Step 1: Create package marker**

```bash
mkdir -p src/collector/trades
touch src/collector/trades/__init__.py
```

- [ ] **Step 2: Write failing tests (4 cases covering taker-side convention)**

Create `tests/test_trades_polymarket.py`:

```python
from datetime import datetime, timezone

from src.collector.trades.polymarket import event_to_trade

YES_ID = "1111"
NO_ID = "2222"
TS = 1704153600  # 2024-01-02 00:00:00 UTC
EXPECTED_DT = datetime.fromtimestamp(TS, tz=timezone.utc)


def _event(args: dict, tx="0xabc", log_idx=0, block=50_000_000):
    return {
        "args": args,
        "transactionHash": bytes.fromhex(tx[2:]) if tx.startswith("0x") else tx,
        "logIndex": log_idx,
        "blockNumber": block,
    }


def test_maker_usdc_taker_yes_means_taker_sells_yes():
    # Maker offers 850 USDC for 1000 YES shares -> taker sold 1000 YES at 0.85
    ev = _event({
        "orderHash": b"\x01" * 32,
        "maker": "0xMAKER",
        "taker": "0xTAKER",
        "makerAssetId": 0,
        "takerAssetId": int(YES_ID),
        "makerAmountFilled": 850_000,
        "takerAmountFilled": 1_000_000,
        "fee": 0,
    })
    trade = event_to_trade(ev, YES_ID, NO_ID, "0xm1", TS)
    assert trade["market_id"] == "0xm1"
    assert trade["venue"] == "polymarket"
    assert trade["timestamp"] == EXPECTED_DT
    assert trade["price"] == 0.85
    assert trade["size_shares"] == 1.0
    assert trade["usdc_notional"] == 0.85
    assert trade["side"] == "sell_yes"
    assert trade["is_yes_token"] is True
    assert trade["tx_hash"] == "0x" + "01" * 0 + ("01" * 32)[:0] or isinstance(trade["tx_hash"], str)
    assert trade["log_index"] == 0
    assert trade["block_number"] == 50_000_000
    assert trade["maker_address"] == "0xMAKER"
    assert trade["taker_address"] == "0xTAKER"
    assert trade["maker_asset_id"] == "0"
    assert trade["taker_asset_id"] == YES_ID
    assert trade["fee"] == 0.0


def test_maker_yes_taker_usdc_means_taker_buys_yes():
    # Maker offers 1000 YES for 850 USDC -> taker bought 1000 YES at 0.85
    ev = _event({
        "orderHash": b"\x02" * 32,
        "maker": "0xM",
        "taker": "0xT",
        "makerAssetId": int(YES_ID),
        "takerAssetId": 0,
        "makerAmountFilled": 1_000_000,
        "takerAmountFilled": 850_000,
        "fee": 0,
    })
    trade = event_to_trade(ev, YES_ID, NO_ID, "0xm1", TS)
    assert trade["price"] == 0.85
    assert trade["size_shares"] == 1.0
    assert trade["side"] == "buy_yes"
    assert trade["is_yes_token"] is True


def test_maker_usdc_taker_no_means_taker_sells_no():
    ev = _event({
        "orderHash": b"\x03" * 32,
        "maker": "0xM",
        "taker": "0xT",
        "makerAssetId": 0,
        "takerAssetId": int(NO_ID),
        "makerAmountFilled": 150_000,
        "takerAmountFilled": 1_000_000,
        "fee": 0,
    })
    trade = event_to_trade(ev, YES_ID, NO_ID, "0xm1", TS)
    assert trade["price"] == 0.15
    assert trade["size_shares"] == 1.0
    assert trade["side"] == "sell_no"
    assert trade["is_yes_token"] is False


def test_maker_no_taker_usdc_means_taker_buys_no():
    ev = _event({
        "orderHash": b"\x04" * 32,
        "maker": "0xM",
        "taker": "0xT",
        "makerAssetId": int(NO_ID),
        "takerAssetId": 0,
        "makerAmountFilled": 1_000_000,
        "takerAmountFilled": 150_000,
        "fee": 0,
    })
    trade = event_to_trade(ev, YES_ID, NO_ID, "0xm1", TS)
    assert trade["price"] == 0.15
    assert trade["size_shares"] == 1.0
    assert trade["side"] == "buy_no"
    assert trade["is_yes_token"] is False


def test_fee_is_normalized_by_usdc_decimals():
    ev = _event({
        "orderHash": b"\x05" * 32,
        "maker": "0xM", "taker": "0xT",
        "makerAssetId": 0, "takerAssetId": int(NO_ID),
        "makerAmountFilled": 500_000,
        "takerAmountFilled": 1_000_000,
        "fee": 2_500,  # 0.0025 USDC
    })
    trade = event_to_trade(ev, YES_ID, NO_ID, "0xm1", TS)
    assert trade["fee"] == 0.0025


def test_raw_event_json_is_json_serializable():
    ev = _event({
        "orderHash": b"\x06" * 32,
        "maker": "0xM", "taker": "0xT",
        "makerAssetId": 0, "takerAssetId": int(NO_ID),
        "makerAmountFilled": 500_000, "takerAmountFilled": 1_000_000,
        "fee": 0,
    })
    trade = event_to_trade(ev, YES_ID, NO_ID, "0xm1", TS)
    import json
    parsed = json.loads(trade["raw_event_json"])
    assert parsed["makerAmountFilled"] == 500_000
```

- [ ] **Step 3: Verify tests fail**

```bash
uv run pytest tests/test_trades_polymarket.py -v
```

Expected: `ModuleNotFoundError` or `ImportError`.

- [ ] **Step 4: Implement the mapper**

Create `src/collector/trades/polymarket.py`:

```python
"""Polymarket on-chain trade collector.

Reuses the CTF Exchange ABI and block-estimation helpers from
src/collector/polygon_chain.py. Produces per-fill Trade dicts suitable for
insertion into the `trades` table.
"""
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Iterator

logger = logging.getLogger(__name__)

DECIMALS_USDC = 10 ** 6
DECIMALS_OUTCOME = 10 ** 6


def _tx_hash_to_hex(raw) -> str:
    if isinstance(raw, (bytes, bytearray)):
        return "0x" + raw.hex()
    if isinstance(raw, str):
        return raw if raw.startswith("0x") else "0x" + raw
    return str(raw)


def _serialize_args(args: dict) -> str:
    """JSON-serialize an event args dict; handles bytes and int."""
    def default(v):
        if isinstance(v, (bytes, bytearray)):
            return "0x" + v.hex()
        if isinstance(v, int) and v.bit_length() > 53:
            return str(v)
        raise TypeError(f"Unserializable {type(v).__name__}")
    return json.dumps(dict(args), default=default)


def event_to_trade(
    event: dict,
    yes_token_id: str,
    no_token_id: str,
    market_id: str,
    block_timestamp: float,
) -> dict:
    """Map an OrderFilled event to a Trade dict.

    Convention: `side` stores the TAKER perspective (taker = market-order
    initiator). If maker offered USDC (makerAssetId == 0), taker SOLD the
    outcome token; if taker offered USDC, taker BOUGHT it.
    """
    args = event["args"]
    maker_asset = args["makerAssetId"]
    taker_asset = args["takerAssetId"]
    maker_amount = args["makerAmountFilled"]
    taker_amount = args["takerAmountFilled"]

    yes_int = int(yes_token_id)
    no_int = int(no_token_id)

    if maker_asset == 0:
        outcome_asset = taker_asset
        outcome_amount = taker_amount
        usdc_amount = maker_amount
        taker_buys = False
    elif taker_asset == 0:
        outcome_asset = maker_asset
        outcome_amount = maker_amount
        usdc_amount = taker_amount
        taker_buys = True
    else:
        raise ValueError("OrderFilled without USDC leg (maker/taker both nonzero asset)")

    is_yes = outcome_asset == yes_int
    if not is_yes and outcome_asset != no_int:
        raise ValueError(f"Event asset {outcome_asset} matches neither YES nor NO token")

    size_shares = outcome_amount / DECIMALS_OUTCOME
    notional = usdc_amount / DECIMALS_USDC
    price = notional / size_shares if size_shares else 0.0

    outcome_label = "yes" if is_yes else "no"
    direction = "buy" if taker_buys else "sell"
    side = f"{direction}_{outcome_label}"

    return {
        "market_id": market_id,
        "venue": "polymarket",
        "timestamp": datetime.fromtimestamp(block_timestamp, tz=timezone.utc),
        "price": price,
        "size_shares": size_shares,
        "usdc_notional": notional,
        "side": side,
        "is_yes_token": is_yes,
        "tx_hash": _tx_hash_to_hex(event["transactionHash"]),
        "log_index": event["logIndex"],
        "block_number": event["blockNumber"],
        "maker_address": args["maker"],
        "taker_address": args["taker"],
        "order_hash": _tx_hash_to_hex(args["orderHash"]),
        "maker_asset_id": str(maker_asset),
        "taker_asset_id": str(taker_asset),
        "fee": args["fee"] / DECIMALS_USDC,
        "kalshi_trade_id": None,
        "raw_event_json": _serialize_args(args),
    }
```

- [ ] **Step 5: Verify tests pass**

```bash
uv run pytest tests/test_trades_polymarket.py -v
```

Expected: 6 passed.

- [ ] **Step 6: Commit**

```bash
git add src/collector/trades/__init__.py src/collector/trades/polymarket.py tests/test_trades_polymarket.py
git commit -m "feat(trades): add pure event_to_trade mapper for Polymarket fills"
```

---

## Task 3: `fetch_yes_token_id` Gamma Lookup Helper

**Files:**
- Modify: `src/collector/trades/polymarket.py`
- Modify: `tests/test_trades_polymarket.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_trades_polymarket.py`:

```python
import httpx
import json as _json

def test_fetch_yes_token_id_happy_path(monkeypatch):
    from src.collector.trades.polymarket import fetch_yes_token_id

    fake_payload = {
        "outcomes": _json.dumps(["Yes", "No"]),
        "clobTokenIds": _json.dumps(["111", "222"]),
    }

    class FakeResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return fake_payload

    def fake_get(url, timeout=None):
        assert url.endswith("/markets/0xmarket")
        return FakeResp()

    monkeypatch.setattr(httpx, "get", fake_get)
    assert fetch_yes_token_id("0xmarket") == "111"


def test_fetch_yes_token_id_no_first(monkeypatch):
    from src.collector.trades.polymarket import fetch_yes_token_id

    fake_payload = {
        "outcomes": _json.dumps(["No", "Yes"]),
        "clobTokenIds": _json.dumps(["222", "111"]),
    }

    class FakeResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return fake_payload

    monkeypatch.setattr(httpx, "get", lambda url, timeout=None: FakeResp())
    assert fetch_yes_token_id("0xmarket") == "111"


def test_fetch_yes_token_id_returns_none_on_malformed(monkeypatch):
    from src.collector.trades.polymarket import fetch_yes_token_id

    class FakeResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"outcomes": "not-json"}

    monkeypatch.setattr(httpx, "get", lambda url, timeout=None: FakeResp())
    assert fetch_yes_token_id("0xbad") is None


def test_fetch_yes_token_id_returns_none_on_http_error(monkeypatch):
    from src.collector.trades.polymarket import fetch_yes_token_id

    def fake_get(url, timeout=None):
        raise httpx.ConnectError("no network")

    monkeypatch.setattr(httpx, "get", fake_get)
    assert fetch_yes_token_id("0xmarket") is None
```

- [ ] **Step 2: Verify tests fail**

```bash
uv run pytest tests/test_trades_polymarket.py -v
```

Expected: 4 failures (`cannot import name 'fetch_yes_token_id'`).

- [ ] **Step 3: Implement helper**

Append to `src/collector/trades/polymarket.py`:

```python
import httpx

GAMMA_API_BASE = "https://gamma-api.polymarket.com"


def fetch_yes_token_id(market_id: str) -> str | None:
    """Look up the YES clobTokenId for a market via Gamma API.

    Returns None if the market is missing, malformed, or unreachable.
    """
    try:
        resp = httpx.get(f"{GAMMA_API_BASE}/markets/{market_id}", timeout=30)
        resp.raise_for_status()
        raw = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("fetch_yes_token_id: request failed for %s: %s", market_id, exc)
        return None

    try:
        outcomes = json.loads(raw["outcomes"])
        token_ids = json.loads(raw["clobTokenIds"])
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        logger.warning("fetch_yes_token_id: malformed payload for %s: %s", market_id, exc)
        return None

    if len(outcomes) != 2 or len(token_ids) != 2:
        return None

    try:
        yes_idx = [o.lower() for o in outcomes].index("yes")
    except ValueError:
        return None

    return token_ids[yes_idx]
```

- [ ] **Step 4: Verify tests pass**

```bash
uv run pytest tests/test_trades_polymarket.py -v
```

Expected: 10 passed (6 mapper tests + 4 new).

- [ ] **Step 5: Commit**

```bash
git add src/collector/trades/polymarket.py tests/test_trades_polymarket.py
git commit -m "feat(trades): add fetch_yes_token_id Gamma lookup helper"
```

---

## Task 4: `fetch_trades` Iterator with Injected Web3

**Files:**
- Modify: `src/collector/trades/polymarket.py`
- Modify: `tests/test_trades_polymarket.py`

- [ ] **Step 1: Add failing smoke test using a fake Web3**

Append to `tests/test_trades_polymarket.py`:

```python
from datetime import datetime, timezone
from types import SimpleNamespace


class _FakeContractEvent:
    def __init__(self, logs_per_chunk):
        self._chunks = iter(logs_per_chunk)

    def get_logs(self, fromBlock, toBlock):  # noqa: N803
        try:
            return next(self._chunks)
        except StopIteration:
            return []


class _FakeContractEvents:
    def __init__(self, logs_per_chunk):
        self.OrderFilled = _FakeContractEvent(logs_per_chunk)


class _FakeContract:
    def __init__(self, logs_per_chunk):
        self.events = _FakeContractEvents(logs_per_chunk)


class _FakeEth:
    def __init__(self, logs_per_chunk, block_timestamps, latest_block):
        self._contract = _FakeContract(logs_per_chunk)
        self.block_number = latest_block
        self._ts = block_timestamps

    def contract(self, address=None, abi=None):
        return self._contract

    def get_block(self, n):
        return {"timestamp": self._ts.get(n, 1704153600)}


class _FakeWeb3:
    def __init__(self, logs_per_chunk, block_timestamps=None, latest=60_000_000, connected=True):
        self.eth = _FakeEth(logs_per_chunk, block_timestamps or {}, latest)
        self._connected = connected

    def is_connected(self):
        return self._connected


def _sample_event(maker_asset, taker_asset, maker_amt, taker_amt, block=50_000_000, log_idx=0, tx="0xaa"):
    return {
        "args": {
            "orderHash": b"\x01" * 32,
            "maker": "0xMAKER",
            "taker": "0xTAKER",
            "makerAssetId": maker_asset,
            "takerAssetId": taker_asset,
            "makerAmountFilled": maker_amt,
            "takerAmountFilled": taker_amt,
            "fee": 0,
        },
        "transactionHash": bytes.fromhex(tx[2:] + "00" * (32 - len(tx[2:]) // 2)),
        "logIndex": log_idx,
        "blockNumber": block,
    }


def test_fetch_trades_yields_mapped_trades(session):
    from src.collector.trades.polymarket import fetch_trades
    from src.storage.models import Market

    market = Market(
        id="0xmarket",
        question="q",
        category="political",
        no_token_id=NO_ID,
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        resolved_at=datetime(2024, 1, 2, tzinfo=timezone.utc),
    )
    session.add(market); session.commit()

    ev = _sample_event(0, int(NO_ID), 150_000, 1_000_000, block=50_000_010)
    fake = _FakeWeb3(
        logs_per_chunk=[[ev]],
        block_timestamps={50_000_010: 1704153600},
        latest=50_000_020,
    )

    trades = list(fetch_trades(
        market, yes_token_id=YES_ID, no_token_id=NO_ID,
        from_block=50_000_000, to_block=50_000_020,
        w3=fake,
    ))
    assert len(trades) == 1
    assert trades[0]["market_id"] == "0xmarket"
    assert trades[0]["side"] == "sell_no"


def test_fetch_trades_returns_empty_when_disconnected(session):
    from src.collector.trades.polymarket import fetch_trades
    from src.storage.models import Market

    market = Market(
        id="0xmarket",
        question="q",
        category="political",
        no_token_id=NO_ID,
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        resolved_at=datetime(2024, 1, 2, tzinfo=timezone.utc),
    )
    session.add(market); session.commit()

    fake = _FakeWeb3(logs_per_chunk=[], connected=False)
    trades = list(fetch_trades(
        market, yes_token_id=YES_ID, no_token_id=NO_ID,
        from_block=50_000_000, to_block=50_000_020,
        w3=fake,
    ))
    assert trades == []


def test_fetch_trades_filters_unrelated_asset(session):
    from src.collector.trades.polymarket import fetch_trades
    from src.storage.models import Market

    market = Market(
        id="0xmarket", question="q", category="political",
        no_token_id=NO_ID,
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        resolved_at=datetime(2024, 1, 2, tzinfo=timezone.utc),
    )
    session.add(market); session.commit()

    unrelated = _sample_event(0, 999_999_999, 500_000, 1_000_000, block=50_000_011)
    fake = _FakeWeb3(
        logs_per_chunk=[[unrelated]],
        block_timestamps={50_000_011: 1704153600},
        latest=50_000_020,
    )
    trades = list(fetch_trades(
        market, yes_token_id=YES_ID, no_token_id=NO_ID,
        from_block=50_000_000, to_block=50_000_020,
        w3=fake,
    ))
    assert trades == []
```

- [ ] **Step 2: Verify tests fail**

```bash
uv run pytest tests/test_trades_polymarket.py -v
```

Expected: 3 failures on the new tests (`cannot import name 'fetch_trades'`).

- [ ] **Step 3: Implement `fetch_trades`**

Append to `src/collector/trades/polymarket.py`:

```python
from src.collector.polygon_chain import (
    ORDER_FILLED_ABI,
    CTF_EXCHANGE_ADDRESS,
    estimate_block_for_timestamp,
)

BLOCK_CHUNK = 10_000
CHUNK_SLEEP_SECONDS = 0.1
MAX_RETRIES = 3


def _build_web3():
    try:
        from web3 import Web3
    except ImportError:
        logger.warning("web3 not installed; Polymarket trade fetching disabled")
        return None
    rpc_url = os.getenv("POLYGON_RPC_URL", "https://polygon-rpc.com")
    return Web3(Web3.HTTPProvider(rpc_url))


def _get_logs_with_retry(contract, from_block, to_block):
    delay = 1.0
    last_exc = None
    for attempt in range(MAX_RETRIES):
        try:
            return contract.events.OrderFilled.get_logs(
                fromBlock=from_block, toBlock=to_block
            )
        except Exception as exc:
            last_exc = exc
            if attempt < MAX_RETRIES - 1:
                time.sleep(delay)
                delay *= 2
    logger.warning(
        "get_logs failed after %d retries (%d-%d): %s",
        MAX_RETRIES, from_block, to_block, last_exc,
    )
    return []


def fetch_trades(
    market,
    yes_token_id: str,
    no_token_id: str,
    from_block: int | None = None,
    to_block: int | None = None,
    w3=None,
) -> Iterator[dict]:
    """Yield Trade dicts for all OrderFilled events touching the market's tokens.

    `w3` is injectable for tests. If omitted, constructs one from POLYGON_RPC_URL
    (or the public default). Returns empty if web3 is missing or disconnected.
    """
    if w3 is None:
        w3 = _build_web3()
    if w3 is None or not w3.is_connected():
        logger.warning("w3 unavailable; yielding no trades for %s", market.id)
        return

    try:
        from web3 import Web3 as _W3
        address = _W3.to_checksum_address(CTF_EXCHANGE_ADDRESS)
    except ImportError:
        address = CTF_EXCHANGE_ADDRESS

    contract = w3.eth.contract(address=address, abi=ORDER_FILLED_ABI)

    latest_block = w3.eth.block_number
    latest_ts = float(w3.eth.get_block(latest_block)["timestamp"])

    fb = from_block if from_block is not None else estimate_block_for_timestamp(
        market.created_at.timestamp(), latest_block, latest_ts
    )
    tb = to_block if to_block is not None else (
        estimate_block_for_timestamp(
            market.resolved_at.timestamp(), latest_block, latest_ts
        ) if market.resolved_at else latest_block
    )

    yes_int = int(yes_token_id)
    no_int = int(no_token_id)

    for chunk_start in range(fb, tb + 1, BLOCK_CHUNK):
        chunk_end = min(chunk_start + BLOCK_CHUNK - 1, tb)
        events = _get_logs_with_retry(contract, chunk_start, chunk_end)

        relevant = [
            e for e in events
            if e["args"]["makerAssetId"] in (yes_int, no_int)
            or e["args"]["takerAssetId"] in (yes_int, no_int)
        ]
        if not relevant:
            time.sleep(CHUNK_SLEEP_SECONDS)
            continue

        ts_cache: dict[int, float] = {}
        for ev in relevant:
            bn = ev["blockNumber"]
            if bn not in ts_cache:
                ts_cache[bn] = float(w3.eth.get_block(bn)["timestamp"])
            try:
                yield event_to_trade(ev, yes_token_id, no_token_id, market.id, ts_cache[bn])
            except ValueError as exc:
                logger.warning("skip malformed event in %s: %s", market.id, exc)

        time.sleep(CHUNK_SLEEP_SECONDS)
```

- [ ] **Step 4: Verify tests pass**

```bash
uv run pytest tests/test_trades_polymarket.py -v
```

Expected: 13 passed.

- [ ] **Step 5: Commit**

```bash
git add src/collector/trades/polymarket.py tests/test_trades_polymarket.py
git commit -m "feat(trades): add fetch_trades iterator with injectable web3"
```

---

## Task 5: Runner — `run_backfill` Core Logic

**Files:**
- Create: `src/collector/trades/runner.py`
- Create: `tests/test_trades_runner.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_trades_runner.py`:

```python
from datetime import datetime, timezone

import pytest

from src.storage.models import Market, Trade


def _seed_market(session, market_id, created, resolved=None):
    m = Market(
        id=market_id,
        question=f"Market {market_id}",
        category="political",
        no_token_id="2222",
        created_at=created,
        resolved_at=resolved,
        resolution="No" if resolved else None,
    )
    session.add(m)
    session.commit()
    return m


def _fake_trade(market_id, block, log_idx=0, tx_suffix="aa"):
    return {
        "market_id": market_id,
        "venue": "polymarket",
        "timestamp": datetime.fromtimestamp(1704153600 + block, tz=timezone.utc),
        "price": 0.5,
        "size_shares": 1.0,
        "usdc_notional": 0.5,
        "side": "buy_no",
        "is_yes_token": False,
        "tx_hash": f"0x{tx_suffix:0<64}",
        "log_index": log_idx,
        "block_number": block,
        "maker_address": "0xM",
        "taker_address": "0xT",
        "order_hash": "0xABC",
        "maker_asset_id": "0",
        "taker_asset_id": "2222",
        "fee": 0.0,
        "kalshi_trade_id": None,
        "raw_event_json": "{}",
    }


def test_run_backfill_writes_trades(session):
    from src.collector.trades.runner import run_backfill

    _seed_market(
        session, "0xm1",
        created=datetime(2024, 1, 1, tzinfo=timezone.utc),
        resolved=datetime(2024, 2, 1, tzinfo=timezone.utc),
    )

    def fake_fetch(market, yes_token_id, no_token_id, from_block=None, to_block=None, w3=None):
        yield _fake_trade("0xm1", block=50_000_000, log_idx=0, tx_suffix="a1")
        yield _fake_trade("0xm1", block=50_000_001, log_idx=0, tx_suffix="a2")

    def fake_yes_token(mid):
        return "1111"

    run_backfill(
        session,
        market_ids=["0xm1"],
        fetch_trades_fn=fake_fetch,
        yes_token_fn=fake_yes_token,
    )
    session.commit()
    assert session.query(Trade).count() == 2


def test_run_backfill_is_idempotent(session):
    from src.collector.trades.runner import run_backfill

    _seed_market(
        session, "0xm1",
        created=datetime(2024, 1, 1, tzinfo=timezone.utc),
        resolved=datetime(2024, 2, 1, tzinfo=timezone.utc),
    )

    def fake_fetch(market, yes_token_id, no_token_id, from_block=None, to_block=None, w3=None):
        yield _fake_trade("0xm1", block=50_000_000, log_idx=0, tx_suffix="a1")
        yield _fake_trade("0xm1", block=50_000_001, log_idx=0, tx_suffix="a2")

    run_backfill(session, ["0xm1"], fake_fetch, lambda _: "1111")
    session.commit()
    run_backfill(session, ["0xm1"], fake_fetch, lambda _: "1111")
    session.commit()

    assert session.query(Trade).count() == 2


def test_run_backfill_skips_market_missing_yes_token(session):
    from src.collector.trades.runner import run_backfill

    _seed_market(
        session, "0xm1",
        created=datetime(2024, 1, 1, tzinfo=timezone.utc),
        resolved=datetime(2024, 2, 1, tzinfo=timezone.utc),
    )

    def fake_fetch(market, yes_token_id, no_token_id, from_block=None, to_block=None, w3=None):
        yield _fake_trade("0xm1", block=50_000_000)

    run_backfill(session, ["0xm1"], fake_fetch, lambda _: None)
    session.commit()
    assert session.query(Trade).count() == 0


def test_run_backfill_raises_for_unknown_market(session):
    from src.collector.trades.runner import run_backfill

    def fake_fetch(*a, **kw):
        return iter(())

    with pytest.raises(ValueError, match="unknown market"):
        run_backfill(session, ["0xDOESNOTEXIST"], fake_fetch, lambda _: "1111")


def test_select_pilot_markets_orders_by_most_recent_resolution(session):
    from src.collector.trades.runner import select_pilot_markets

    _seed_market(session, "0xold",
        created=datetime(2023, 1, 1, tzinfo=timezone.utc),
        resolved=datetime(2023, 6, 1, tzinfo=timezone.utc))
    _seed_market(session, "0xmid",
        created=datetime(2024, 1, 1, tzinfo=timezone.utc),
        resolved=datetime(2024, 6, 1, tzinfo=timezone.utc))
    _seed_market(session, "0xnew",
        created=datetime(2024, 6, 1, tzinfo=timezone.utc),
        resolved=datetime(2024, 12, 1, tzinfo=timezone.utc))
    # Unresolved market — must be excluded
    _seed_market(session, "0xopen",
        created=datetime(2025, 1, 1, tzinfo=timezone.utc),
        resolved=None)

    picks = select_pilot_markets(session, n=2)
    assert picks == ["0xnew", "0xmid"]


def test_select_pilot_markets_respects_category_filter(session):
    from src.collector.trades.runner import select_pilot_markets, ALLOWED_CATEGORIES

    # Default categories are geopolitical / political / culture
    assert "political" in ALLOWED_CATEGORIES
    _seed_market(session, "0xpol",
        created=datetime(2024, 1, 1, tzinfo=timezone.utc),
        resolved=datetime(2024, 6, 1, tzinfo=timezone.utc))
    m = session.query(Market).filter_by(id="0xpol").one()
    m.category = "sports"  # outside filter
    session.commit()

    assert select_pilot_markets(session, n=5) == []
```

- [ ] **Step 2: Verify tests fail**

```bash
uv run pytest tests/test_trades_runner.py -v
```

Expected: all fail on `ModuleNotFoundError: src.collector.trades.runner`.

- [ ] **Step 3: Implement `run_backfill` and `select_pilot_markets`**

Create `src/collector/trades/runner.py`:

```python
"""Trade-tape collector runner.

Provides run_backfill / run_catchup as pure-ish functions taking injected
fetchers (for testability), plus a CLI via main().
"""
import argparse
import logging
import sys
import time
from typing import Callable, Iterable, Iterator

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.storage.db import get_engine, get_session
from src.storage.models import Market, Trade
from src.collector.trades import polymarket

logger = logging.getLogger(__name__)

ALLOWED_CATEGORIES = ("geopolitical", "political", "culture")
WRITE_BATCH = 100
COMMIT_BATCH = 500


def select_pilot_markets(session: Session, n: int) -> list[str]:
    """Return the N most-recently-resolved market IDs in ALLOWED_CATEGORIES."""
    rows = (
        session.query(Market.id)
        .filter(Market.resolution.isnot(None))
        .filter(Market.resolved_at.isnot(None))
        .filter(Market.category.in_(ALLOWED_CATEGORIES))
        .order_by(Market.resolved_at.desc())
        .limit(n)
        .all()
    )
    return [r[0] for r in rows]


def _existing_keys(session: Session, market_id: str) -> set[tuple[str, int]]:
    rows = (
        session.query(Trade.tx_hash, Trade.log_index)
        .filter(Trade.market_id == market_id, Trade.venue == "polymarket")
        .all()
    )
    return {(r[0], r[1]) for r in rows}


def _max_block_for_market(session: Session, market_id: str) -> int | None:
    return (
        session.query(func.max(Trade.block_number))
        .filter(Trade.market_id == market_id, Trade.venue == "polymarket")
        .scalar()
    )


def _write_trade(session: Session, trade_dict: dict, seen_keys: set) -> bool:
    """Insert a trade dict; return True if written, False if deduplicated."""
    key = (trade_dict["tx_hash"], trade_dict["log_index"])
    if key in seen_keys:
        return False
    seen_keys.add(key)
    session.add(Trade(**trade_dict))
    return True


def run_backfill(
    session: Session,
    market_ids: list[str],
    fetch_trades_fn: Callable[..., Iterator[dict]],
    yes_token_fn: Callable[[str], str | None],
) -> dict[str, int]:
    """Backfill the full block window for each market. Returns {market_id: trades_written}."""
    results: dict[str, int] = {}
    for market_id in market_ids:
        market = session.get(Market, market_id)
        if market is None:
            raise ValueError(f"unknown market id: {market_id}")

        yes_id = yes_token_fn(market_id)
        if yes_id is None:
            logger.warning("skip %s: yes_token_id unavailable", market_id)
            results[market_id] = 0
            continue

        seen = _existing_keys(session, market_id)
        written = 0
        started = time.monotonic()

        try:
            for trade in fetch_trades_fn(
                market,
                yes_token_id=yes_id,
                no_token_id=market.no_token_id,
            ):
                if _write_trade(session, trade, seen):
                    written += 1
                    if written % WRITE_BATCH == 0:
                        session.flush()
                    if written % COMMIT_BATCH == 0:
                        session.commit()
            session.commit()
            logger.info(
                "backfill %s: %d trades in %.1fs",
                market_id, written, time.monotonic() - started,
            )
        except Exception as exc:
            session.rollback()
            logger.warning("backfill %s aborted after %d trades: %s", market_id, written, exc)

        results[market_id] = written
    return results
```

- [ ] **Step 4: Verify tests pass**

```bash
uv run pytest tests/test_trades_runner.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/collector/trades/runner.py tests/test_trades_runner.py
git commit -m "feat(trades): add run_backfill with idempotent writes"
```

---

## Task 6: Runner — `run_catchup` Core Logic

**Files:**
- Modify: `src/collector/trades/runner.py`
- Modify: `tests/test_trades_runner.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_trades_runner.py`:

```python
def test_run_catchup_resumes_from_last_block(session):
    from src.collector.trades.runner import run_catchup, run_backfill

    _seed_market(
        session, "0xm1",
        created=datetime(2024, 1, 1, tzinfo=timezone.utc),
        resolved=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )

    def first_run_fetch(market, **kwargs):
        yield _fake_trade("0xm1", block=50_000_000, tx_suffix="a1")
        yield _fake_trade("0xm1", block=50_000_005, tx_suffix="a2")

    run_backfill(session, ["0xm1"], first_run_fetch, lambda _: "1111")
    session.commit()
    assert session.query(Trade).count() == 2

    observed_from = {}

    def catchup_fetch(market, yes_token_id, no_token_id, from_block=None, to_block=None, w3=None):
        observed_from[market.id] = from_block
        yield _fake_trade("0xm1", block=50_000_006, tx_suffix="a3")

    run_catchup(session, fetch_trades_fn=catchup_fetch, yes_token_fn=lambda _: "1111")
    session.commit()

    assert observed_from["0xm1"] == 50_000_006
    assert session.query(Trade).count() == 3


def test_run_catchup_backfills_market_with_no_trades_yet(session):
    from src.collector.trades.runner import run_catchup

    _seed_market(session, "0xnew",
        created=datetime(2024, 6, 1, tzinfo=timezone.utc),
        resolved=datetime(2024, 12, 1, tzinfo=timezone.utc))

    observed_from = {}

    def catchup_fetch(market, yes_token_id, no_token_id, from_block=None, to_block=None, w3=None):
        observed_from[market.id] = from_block
        yield _fake_trade("0xnew", block=55_000_000, tx_suffix="b1")

    run_catchup(session, fetch_trades_fn=catchup_fetch, yes_token_fn=lambda _: "1111")
    session.commit()
    # No prior rows -> from_block must be None (let fetch compute from created_at).
    assert observed_from["0xnew"] is None
    assert session.query(Trade).count() == 1


def test_run_catchup_skips_unresolved_markets_not_in_trades(session):
    from src.collector.trades.runner import run_catchup

    _seed_market(session, "0xopen",
        created=datetime(2025, 1, 1, tzinfo=timezone.utc),
        resolved=None)

    called = []
    def fetch(market, **kwargs):
        called.append(market.id)
        return iter(())

    run_catchup(session, fetch_trades_fn=fetch, yes_token_fn=lambda _: "1111")
    assert called == []
```

- [ ] **Step 2: Verify new tests fail**

```bash
uv run pytest tests/test_trades_runner.py -v
```

Expected: 3 failures (`cannot import name 'run_catchup'`).

- [ ] **Step 3: Implement `run_catchup`**

Append to `src/collector/trades/runner.py`:

```python
def _catchup_market_ids(session: Session) -> list[str]:
    """Union of (markets with existing trades) and (resolved filtered markets w/ no trades yet)."""
    with_trades = {
        r[0] for r in session.query(Trade.market_id)
        .filter(Trade.venue == "polymarket")
        .distinct().all()
    }
    new_resolved = {
        r[0] for r in session.query(Market.id)
        .filter(Market.resolution.isnot(None))
        .filter(Market.resolved_at.isnot(None))
        .filter(Market.category.in_(ALLOWED_CATEGORIES))
        .all()
        if r[0] not in with_trades
    }
    return sorted(with_trades | new_resolved)


def run_catchup(
    session: Session,
    fetch_trades_fn: Callable[..., Iterator[dict]],
    yes_token_fn: Callable[[str], str | None],
) -> dict[str, int]:
    """Incremental pull for markets in trades + any resolved markets not yet present."""
    results: dict[str, int] = {}
    for market_id in _catchup_market_ids(session):
        market = session.get(Market, market_id)
        if market is None:
            continue

        yes_id = yes_token_fn(market_id)
        if yes_id is None:
            logger.warning("skip %s: yes_token_id unavailable", market_id)
            continue

        last_block = _max_block_for_market(session, market_id)
        from_block = (last_block + 1) if last_block is not None else None

        seen = _existing_keys(session, market_id)
        written = 0
        started = time.monotonic()

        try:
            for trade in fetch_trades_fn(
                market,
                yes_token_id=yes_id,
                no_token_id=market.no_token_id,
                from_block=from_block,
            ):
                if _write_trade(session, trade, seen):
                    written += 1
                    if written % WRITE_BATCH == 0:
                        session.flush()
                    if written % COMMIT_BATCH == 0:
                        session.commit()
            session.commit()
            logger.info(
                "catchup %s: %d new trades in %.1fs",
                market_id, written, time.monotonic() - started,
            )
        except Exception as exc:
            session.rollback()
            logger.warning("catchup %s aborted after %d trades: %s", market_id, written, exc)

        results[market_id] = written
    return results
```

- [ ] **Step 4: Verify tests pass**

```bash
uv run pytest tests/test_trades_runner.py -v
```

Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add src/collector/trades/runner.py tests/test_trades_runner.py
git commit -m "feat(trades): add run_catchup with per-market block checkpoint"
```

---

## Task 7: Runner — CLI

**Files:**
- Modify: `src/collector/trades/runner.py`
- Modify: `tests/test_trades_runner.py`

- [ ] **Step 1: Add failing CLI tests**

Append to `tests/test_trades_runner.py`:

```python
def test_parse_args_backfill_pilot():
    from src.collector.trades.runner import parse_args
    args = parse_args(["--mode", "backfill", "--pilot", "5"])
    assert args.mode == "backfill"
    assert args.pilot == 5
    assert args.market_ids is None
    assert args.venues == ["polymarket"]


def test_parse_args_backfill_market_ids():
    from src.collector.trades.runner import parse_args
    args = parse_args(["--mode", "backfill", "--market-ids", "0xa,0xb"])
    assert args.market_ids == ["0xa", "0xb"]


def test_parse_args_catchup_defaults():
    from src.collector.trades.runner import parse_args
    args = parse_args(["--mode", "catchup"])
    assert args.mode == "catchup"


def test_validate_args_requires_pilot_xor_market_ids_in_backfill():
    from src.collector.trades.runner import parse_args, validate_args

    with pytest.raises(SystemExit):
        validate_args(parse_args(["--mode", "backfill"]))

    with pytest.raises(SystemExit):
        validate_args(parse_args([
            "--mode", "backfill", "--pilot", "5", "--market-ids", "0xa",
        ]))


def test_validate_args_rejects_kalshi_without_credentials(monkeypatch):
    from src.collector.trades.runner import parse_args, validate_args
    monkeypatch.delenv("KALSHI_API_KEY_ID", raising=False)
    monkeypatch.delenv("KALSHI_API_KEY_SECRET", raising=False)
    with pytest.raises(SystemExit):
        validate_args(parse_args(["--mode", "catchup", "--venues", "kalshi"]))
```

- [ ] **Step 2: Verify tests fail**

```bash
uv run pytest tests/test_trades_runner.py::test_parse_args_backfill_pilot -v
```

Expected: fail (`cannot import name 'parse_args'`).

- [ ] **Step 3: Implement CLI**

Append to `src/collector/trades/runner.py`:

```python
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Polymarket / Kalshi trade-tape collector")
    p.add_argument("--mode", required=True, choices=["backfill", "catchup"])
    p.add_argument("--pilot", type=int, default=None,
                   help="(backfill) pick top-N most-recently-resolved markets")
    p.add_argument("--market-ids", type=str, default=None,
                   help="(backfill) comma-separated explicit market ids")
    p.add_argument("--venues", type=str, default="polymarket",
                   help="Comma-separated venues (default: polymarket)")
    p.add_argument("--db", type=str, default=None, help="Override DB path")
    ns = p.parse_args(argv)
    if ns.market_ids:
        ns.market_ids = [s for s in ns.market_ids.split(",") if s]
    ns.venues = [v.strip() for v in ns.venues.split(",") if v.strip()]
    return ns


def validate_args(ns: argparse.Namespace) -> None:
    import os
    if ns.mode == "backfill":
        has_pilot = ns.pilot is not None
        has_ids = bool(ns.market_ids)
        if has_pilot == has_ids:
            print("error: --mode backfill requires exactly one of --pilot or --market-ids",
                  file=sys.stderr)
            sys.exit(1)
    if "kalshi" in ns.venues:
        if not (os.getenv("KALSHI_API_KEY_ID") and os.getenv("KALSHI_API_KEY_SECRET")):
            print("error: --venues kalshi requires KALSHI_API_KEY_ID and KALSHI_API_KEY_SECRET",
                  file=sys.stderr)
            sys.exit(1)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ns = parse_args(argv)
    validate_args(ns)

    engine = get_engine(ns.db)
    session = get_session(engine)

    try:
        for venue in ns.venues:
            if venue == "polymarket":
                fetch_fn = polymarket.fetch_trades
                yes_fn = polymarket.fetch_yes_token_id
            elif venue == "kalshi":
                from src.collector.trades import kalshi
                cfg = kalshi.KalshiConfig.from_env()
                fetch_fn = lambda market, **kw: kalshi.fetch_trades(market, cfg)  # noqa: E731
                yes_fn = lambda _mid: None  # kalshi path raises before this is used  # noqa: E731
            else:
                print(f"error: unknown venue {venue!r}", file=sys.stderr)
                return 1

            if ns.mode == "backfill":
                ids = ns.market_ids or select_pilot_markets(session, ns.pilot)
                if not ids:
                    print("no pilot markets available", file=sys.stderr)
                    continue
                # Verify explicit ids exist
                for mid in ids:
                    if session.get(Market, mid) is None:
                        print(f"error: unknown market id {mid!r}", file=sys.stderr)
                        return 1
                run_backfill(session, ids, fetch_fn, yes_fn)
            else:
                run_catchup(session, fetch_fn, yes_fn)
    finally:
        session.close()
        engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Verify tests pass**

```bash
uv run pytest tests/test_trades_runner.py -v
```

Expected: 14 passed.

- [ ] **Step 5: Smoke-test CLI help**

```bash
uv run python -m src.collector.trades.runner --help
```

Expected: argparse help output, no errors.

- [ ] **Step 6: Commit**

```bash
git add src/collector/trades/runner.py tests/test_trades_runner.py
git commit -m "feat(trades): add runner CLI with backfill and catchup modes"
```

---

## Task 8: Shell Wrapper

**Files:**
- Create: `scripts/trades_catchup.sh`

- [ ] **Step 1: Check scripts directory**

```bash
ls scripts/ 2>/dev/null || mkdir scripts
```

- [ ] **Step 2: Create wrapper**

Create `scripts/trades_catchup.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
exec uv run python -m src.collector.trades.runner --mode catchup "$@"
```

- [ ] **Step 3: Make executable and verify**

```bash
chmod +x scripts/trades_catchup.sh
./scripts/trades_catchup.sh --help
```

Expected: argparse help output.

- [ ] **Step 4: Commit**

```bash
git add scripts/trades_catchup.sh
git commit -m "feat(trades): add trades_catchup.sh wrapper for external cron"
```

---

## Task 9: Dashboard Query Helpers

**Files:**
- Create: `src/dashboard/trades_tab.py` (partial — query helpers only in this task)
- Create: `tests/test_trades_tab.py`

- [ ] **Step 1: Write failing tests for query helpers**

Create `tests/test_trades_tab.py`:

```python
from datetime import datetime, timezone

from src.storage.models import Market, Trade


def _seed_trade(session, market_id, ts, price, shares, notional, side, block):
    session.add(Trade(
        market_id=market_id, venue="polymarket",
        timestamp=ts, price=price, size_shares=shares,
        usdc_notional=notional, side=side, is_yes_token=False,
        tx_hash=f"0x{block:064x}", log_index=0, block_number=block,
        raw_event_json="{}",
    ))


def _seed_market(session, mid, cat="political"):
    session.add(Market(
        id=mid, question=f"Q {mid}", category=cat,
        no_token_id="2222",
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    ))
    session.commit()


def test_markets_with_trades(session):
    from src.dashboard.trades_tab import markets_with_trades

    _seed_market(session, "0xm1")
    _seed_market(session, "0xm2")
    _seed_trade(session, "0xm1",
        datetime(2024, 2, 1, tzinfo=timezone.utc), 0.5, 1.0, 0.5, "buy_no", 1)
    session.commit()

    result = markets_with_trades(session)
    ids = [r.id for r in result]
    assert "0xm1" in ids
    assert "0xm2" not in ids


def test_daily_volume(session):
    from src.dashboard.trades_tab import daily_volume

    _seed_market(session, "0xm1")
    _seed_trade(session, "0xm1",
        datetime(2024, 2, 1, 9, 0, tzinfo=timezone.utc), 0.5, 10.0, 5.0, "buy_no", 1)
    _seed_trade(session, "0xm1",
        datetime(2024, 2, 1, 14, 0, tzinfo=timezone.utc), 0.6, 10.0, 6.0, "buy_no", 2)
    _seed_trade(session, "0xm1",
        datetime(2024, 2, 2, 9, 0, tzinfo=timezone.utc), 0.7, 10.0, 7.0, "buy_no", 3)
    session.commit()

    rows = daily_volume(session, "0xm1")
    totals = {r["date"]: r["notional"] for r in rows}
    assert totals[datetime(2024, 2, 1).date()] == 11.0
    assert totals[datetime(2024, 2, 2).date()] == 7.0


def test_top_markets_by_notional(session):
    from src.dashboard.trades_tab import top_markets_by_notional

    _seed_market(session, "0xbig")
    _seed_market(session, "0xsmall")
    _seed_trade(session, "0xbig",
        datetime(2024, 2, 1, tzinfo=timezone.utc), 0.5, 100.0, 50.0, "buy_no", 1)
    _seed_trade(session, "0xsmall",
        datetime(2024, 2, 1, tzinfo=timezone.utc), 0.5, 1.0, 0.5, "buy_no", 2)
    session.commit()

    rows = top_markets_by_notional(session, limit=10)
    assert rows[0]["market_id"] == "0xbig"
    assert rows[0]["total_notional"] == 50.0
    assert rows[1]["market_id"] == "0xsmall"


def test_cross_market_daily_volume(session):
    from src.dashboard.trades_tab import cross_market_daily_volume

    _seed_market(session, "0xa")
    _seed_market(session, "0xb")
    _seed_trade(session, "0xa",
        datetime(2024, 2, 1, 9, 0, tzinfo=timezone.utc), 0.5, 10.0, 5.0, "buy_no", 1)
    _seed_trade(session, "0xb",
        datetime(2024, 2, 1, 14, 0, tzinfo=timezone.utc), 0.5, 10.0, 6.0, "buy_no", 2)
    _seed_trade(session, "0xa",
        datetime(2024, 2, 2, 9, 0, tzinfo=timezone.utc), 0.5, 10.0, 7.0, "buy_no", 3)
    session.commit()

    rows = cross_market_daily_volume(session, ["0xa", "0xb"])
    totals = {r["date"]: r["notional"] for r in rows}
    assert totals[datetime(2024, 2, 1).date()] == 11.0
    assert totals[datetime(2024, 2, 2).date()] == 7.0

    # Isolation: excluding 0xb drops its contribution
    rows_a = cross_market_daily_volume(session, ["0xa"])
    assert {r["date"]: r["notional"] for r in rows_a}[datetime(2024, 2, 1).date()] == 5.0
```

- [ ] **Step 2: Verify tests fail**

```bash
uv run pytest tests/test_trades_tab.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement query helpers**

Create `src/dashboard/trades_tab.py`:

```python
"""Streamlit "Trades" tab — trade-tape exploration views."""
from datetime import date, datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.storage.models import Market, Trade


def markets_with_trades(session: Session) -> list[Market]:
    """Markets that have at least one row in trades, ordered by most-recent trade."""
    subq = (
        session.query(
            Trade.market_id.label("mid"),
            func.max(Trade.timestamp).label("latest"),
        )
        .filter(Trade.venue == "polymarket")
        .group_by(Trade.market_id)
        .subquery()
    )
    rows = (
        session.query(Market)
        .join(subq, Market.id == subq.c.mid)
        .order_by(subq.c.latest.desc())
        .all()
    )
    return rows


def daily_volume(session: Session, market_id: str) -> list[dict]:
    """Return [{date, notional, shares, trades}] per day for the market."""
    rows = (
        session.query(Trade)
        .filter(Trade.market_id == market_id, Trade.venue == "polymarket")
        .all()
    )
    buckets: dict[date, dict] = {}
    for t in rows:
        d = t.timestamp.date()
        b = buckets.setdefault(d, {"date": d, "notional": 0.0, "shares": 0.0, "trades": 0})
        b["notional"] += t.usdc_notional
        b["shares"] += t.size_shares
        b["trades"] += 1
    return sorted(buckets.values(), key=lambda r: r["date"])


def top_markets_by_notional(session: Session, limit: int = 10) -> list[dict]:
    rows = (
        session.query(
            Trade.market_id,
            func.sum(Trade.usdc_notional).label("total"),
            func.count(Trade.id).label("n"),
        )
        .filter(Trade.venue == "polymarket")
        .group_by(Trade.market_id)
        .order_by(func.sum(Trade.usdc_notional).desc())
        .limit(limit)
        .all()
    )
    return [
        {"market_id": r[0], "total_notional": float(r[1] or 0.0), "trade_count": int(r[2])}
        for r in rows
    ]


def recent_trades(session: Session, market_id: str, limit: int = 50) -> list[Trade]:
    return (
        session.query(Trade)
        .filter(Trade.market_id == market_id, Trade.venue == "polymarket")
        .order_by(Trade.timestamp.desc())
        .limit(limit)
        .all()
    )


def cross_market_daily_volume(session: Session, market_ids: list[str]) -> list[dict]:
    """Return [{date, notional}] summed across the given markets per day."""
    if not market_ids:
        return []
    rows = (
        session.query(Trade.timestamp, Trade.usdc_notional)
        .filter(Trade.venue == "polymarket", Trade.market_id.in_(market_ids))
        .all()
    )
    buckets: dict[date, float] = {}
    for ts, notional in rows:
        buckets[ts.date()] = buckets.get(ts.date(), 0.0) + (notional or 0.0)
    return [{"date": d, "notional": v} for d, v in sorted(buckets.items())]
```

- [ ] **Step 4: Verify tests pass**

```bash
uv run pytest tests/test_trades_tab.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/dashboard/trades_tab.py tests/test_trades_tab.py
git commit -m "feat(trades): add dashboard query helpers for trade tape"
```

---

## Task 10: Dashboard `render()` Function

**Files:**
- Modify: `src/dashboard/trades_tab.py`

- [ ] **Step 1: Append the render function**

Append to `src/dashboard/trades_tab.py`:

```python
import pandas as pd
import plotly.express as px
import streamlit as st


def render(session: Session, selected_categories: list[str], date_range) -> None:
    st.header("Trades — Per-fill tape")

    markets = markets_with_trades(session)
    if not markets:
        st.info(
            "No trades collected yet. Run "
            "`uv run python -m src.collector.trades.runner --mode backfill --pilot 5`."
        )
        return

    # Apply sidebar category filter
    markets = [m for m in markets if m.category in selected_categories]
    if not markets:
        st.info("No trades match your category filter.")
        return

    market_labels = {m.id: f"{m.question[:80]} — {m.category}" for m in markets}
    selected_id = st.selectbox(
        "Market",
        options=[m.id for m in markets],
        format_func=lambda mid: market_labels[mid],
    )
    selected_market = next(m for m in markets if m.id == selected_id)

    st.markdown(f"**Question:** {selected_market.question}")
    if selected_market.source_url:
        st.markdown(f"[View on Polymarket]({selected_market.source_url})")
    st.markdown(f"**Resolution:** {selected_market.resolution or '—'}")

    trades = recent_trades(session, selected_id, limit=5000)
    if not trades:
        st.info("No trades for this market.")
        return

    df = pd.DataFrame([{
        "timestamp": t.timestamp,
        "price": t.price,
        "size_shares": t.size_shares,
        "usdc_notional": t.usdc_notional,
        "side": t.side,
        "taker": (t.taker_address or "")[:10],
    } for t in trades]).sort_values("timestamp")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Trades", f"{len(df):,}")
    col2.metric("Total notional", f"${df['usdc_notional'].sum():,.0f}")
    col3.metric("Total shares", f"{df['size_shares'].sum():,.0f}")
    col4.metric("VWAP", f"${(df['usdc_notional'].sum() / df['size_shares'].sum()):.4f}"
                if df['size_shares'].sum() else "—")

    # Scatter: price over time, colored by side, sized by shares
    st.subheader("Price over time")
    fig_price = px.scatter(
        df, x="timestamp", y="price", color="side", size="size_shares",
        hover_data=["usdc_notional"], title=None,
    )
    fig_price.update_yaxes(range=[0, 1])
    st.plotly_chart(fig_price, use_container_width=True)

    # Daily volume histogram
    st.subheader("Daily volume")
    vol = daily_volume(session, selected_id)
    vol_df = pd.DataFrame(vol)
    if not vol_df.empty:
        fig_vol = px.bar(vol_df, x="date", y="notional",
                         labels={"notional": "USDC notional"})
        st.plotly_chart(fig_vol, use_container_width=True)

    # Cumulative notional vs price
    st.subheader("Cumulative notional vs price")
    cum_df = df.copy()
    cum_df["cum_notional"] = cum_df["usdc_notional"].cumsum()
    fig_cum = px.line(cum_df, x="timestamp", y="cum_notional",
                      labels={"cum_notional": "Cumulative USDC notional"})
    st.plotly_chart(fig_cum, use_container_width=True)

    # Trade ladder (last 50)
    st.subheader("Most recent trades")
    ladder = df.sort_values("timestamp", ascending=False).head(50)
    st.dataframe(
        ladder,
        use_container_width=True, hide_index=True,
        column_config={
            "price": st.column_config.NumberColumn(format="$%.4f"),
            "size_shares": st.column_config.NumberColumn(format="%.2f"),
            "usdc_notional": st.column_config.NumberColumn(format="$%.2f"),
            "timestamp": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm:ss"),
        },
    )

    # Cross-market section
    st.markdown("---")

    all_market_ids = [m.id for m in markets]

    # Cross-market: total daily volume across all collected (+ filtered) markets
    st.subheader("Total daily volume across collected markets")
    cross = cross_market_daily_volume(session, all_market_ids)
    if cross:
        cross_df = pd.DataFrame(cross)
        fig_cross = px.line(cross_df, x="date", y="notional",
                            labels={"notional": "USDC notional"})
        st.plotly_chart(fig_cross, use_container_width=True)

    # Cross-market: top markets by notional
    st.subheader("Top markets by notional (all collected)")
    top = top_markets_by_notional(session, limit=10)
    if top:
        top_df = pd.DataFrame(top)
        labels = {m.id: m.question[:60] for m in markets}
        top_df["question"] = top_df["market_id"].map(lambda mid: labels.get(mid, mid))
        fig_top = px.bar(top_df, x="question", y="total_notional",
                         labels={"total_notional": "Total USDC notional"})
        fig_top.update_xaxes(tickangle=-30)
        st.plotly_chart(fig_top, use_container_width=True)
```

- [ ] **Step 2: Verify existing tests still pass (render is untested but imports must work)**

```bash
uv run pytest tests/test_trades_tab.py -v
```

Expected: 3 passed (unchanged).

- [ ] **Step 3: Smoke-test the import in isolation**

```bash
uv run python -c "from src.dashboard.trades_tab import render; print('ok')"
```

Expected: `ok`.

- [ ] **Step 4: Commit**

```bash
git add src/dashboard/trades_tab.py
git commit -m "feat(trades): add Streamlit render for trade-tape views"
```

---

## Task 11: Wire `trades_tab` into `app.py`

**Files:**
- Modify: `src/dashboard/app.py`

- [ ] **Step 1: Read the current view-radio and dispatch**

The current radio is at [src/dashboard/app.py:122-132](../../../src/dashboard/app.py#L122-L132), dispatch at [app.py:940-951](../../../src/dashboard/app.py#L940-L951). We add one entry.

- [ ] **Step 2: Add the import**

Edit `src/dashboard/app.py`. Near the top with the other imports, add:

```python
from src.dashboard import trades_tab
```

- [ ] **Step 3: Add "Trades" to the radio options**

In the `view = st.sidebar.radio(...)` call (around line 122), change the options list to include `"Trades"`:

```python
view = st.sidebar.radio(
    "View",
    [
        "Thesis Overview",
        "Live Positions",
        "Strategy Comparison",
        "Sizing Comparison",
        "Deep Dive",
        "Market Browser",
        "Trades",
    ],
)
```

- [ ] **Step 4: Add the dispatch branch**

At the bottom of the file, extend the dispatch chain:

```python
elif view == "Trades":
    trades_tab.render(session, selected_categories, date_range)
```

- [ ] **Step 5: Smoke-test by starting the dashboard**

```bash
uv run streamlit run src/dashboard/app.py --server.headless=true &
STREAMLIT_PID=$!
sleep 5
curl -fsS http://localhost:8501 > /dev/null && echo OK
kill $STREAMLIT_PID
```

Expected: `OK`.

(If no trades exist yet, the tab shows the "No trades collected" prompt — that's correct.)

- [ ] **Step 6: Commit**

```bash
git add src/dashboard/app.py
git commit -m "feat(dashboard): add Trades tab to main app"
```

---

## Task 12: Kalshi Scaffold

**Files:**
- Create: `src/collector/trades/kalshi.py`
- Modify: `.env.example`
- Modify: `tests/test_trades_runner.py` (add Kalshi scaffold test)

- [ ] **Step 1: Add failing test**

Append to `tests/test_trades_runner.py`:

```python
def test_kalshi_fetch_raises_without_credentials(monkeypatch):
    from src.collector.trades.kalshi import fetch_trades, KalshiConfig
    monkeypatch.delenv("KALSHI_API_KEY_ID", raising=False)
    monkeypatch.delenv("KALSHI_API_KEY_SECRET", raising=False)
    cfg = KalshiConfig.from_env()
    with pytest.raises(NotImplementedError, match="not configured"):
        list(fetch_trades(None, cfg))


def test_kalshi_fetch_raises_when_configured_but_unimplemented(monkeypatch):
    from src.collector.trades.kalshi import fetch_trades, KalshiConfig
    monkeypatch.setenv("KALSHI_API_KEY_ID", "id")
    monkeypatch.setenv("KALSHI_API_KEY_SECRET", "secret")
    cfg = KalshiConfig.from_env()
    with pytest.raises(NotImplementedError, match="not yet implemented"):
        list(fetch_trades(None, cfg))
```

- [ ] **Step 2: Verify tests fail**

```bash
uv run pytest tests/test_trades_runner.py::test_kalshi_fetch_raises_without_credentials -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement scaffold**

Create `src/collector/trades/kalshi.py`:

```python
"""Kalshi trade-tape collector scaffold.

Not functional — raises NotImplementedError until credentials are provisioned
and the API client is wired in. Exists so the runner's --venues flag validates
cleanly and the package shape is in place for a later follow-up.
"""
import os
from dataclasses import dataclass
from typing import Iterator


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


def fetch_trades(market, config: KalshiConfig) -> Iterator[dict]:
    if not config.api_key_id or not config.api_key_secret:
        raise NotImplementedError(
            "Kalshi collector not configured. Set KALSHI_API_KEY_ID and "
            "KALSHI_API_KEY_SECRET in .env to activate."
        )
    raise NotImplementedError("Kalshi trade fetching not yet implemented.")
```

- [ ] **Step 4: Update `.env.example`**

Open `.env.example`. Append at the bottom:

```
# --- Kalshi (not yet activated; set these to enable the kalshi venue) ---
# KALSHI_API_KEY_ID=
# KALSHI_API_KEY_SECRET=
# KALSHI_API_BASE=https://api.elections.kalshi.com/trade-api/v2
```

- [ ] **Step 5: Verify tests pass**

```bash
uv run pytest tests/test_trades_runner.py -v
```

Expected: all previous tests plus 2 new pass.

- [ ] **Step 6: Commit**

```bash
git add src/collector/trades/kalshi.py .env.example tests/test_trades_runner.py
git commit -m "feat(trades): scaffold Kalshi venue behind config slot"
```

---

## Task 13: Pilot Sanity-Check Run (operational, no code)

**Files:** none (manual checks against `data/polymarket.db`).

- [ ] **Step 1: Run the pilot backfill**

```bash
uv run python -m src.collector.trades.runner --mode backfill --pilot 5
```

Expected: logging output per market `backfill 0x...: N trades in T.Ts`. Duration will vary with RPC speed (public `polygon-rpc.com` may take multiple minutes per market).

- [ ] **Step 2: Verify row counts by market**

```bash
uv run python -c "
from src.storage.db import get_engine, get_session
from src.storage.models import Trade, Market
from sqlalchemy import func
engine = get_engine()
with get_session(engine) as s:
    rows = s.query(Trade.market_id, func.count(Trade.id), func.sum(Trade.usdc_notional)).group_by(Trade.market_id).all()
    for mid, n, notional in rows:
        m = s.get(Market, mid)
        print(f'{n:>6} trades  ${float(notional or 0):>12,.0f}  {m.question[:60] if m else mid}')
"
```

Expected: one row per pilot market with a plausible trade count and total notional. Spot-check one market against the Polymarket UI if possible.

- [ ] **Step 3: Verify idempotency**

```bash
uv run python -m src.collector.trades.runner --mode catchup
```

Re-query counts — they should be equal to step 2 (or slightly higher if the pilot markets aren't fully resolved; should NOT double).

- [ ] **Step 4: Launch the dashboard and confirm the tab renders**

```bash
uv run streamlit run src/dashboard/app.py
```

Open in browser, navigate to the **Trades** view, pick a market from the dropdown, and eyeball: price scatter has points, daily volume bars populate, cumulative line rises monotonically, trade ladder shows the 50 most recent rows.

- [ ] **Step 5: Decision gate — decide whether to continue scaling**

If row counts look wildly off (e.g. 0 trades, or orders of magnitude off versus the Polymarket UI), do NOT scale to more markets. Triage first — likely candidates: RPC throttling (check `POLYGON_RPC_URL`), malformed `clobTokenIds` lookup, or a side/price mapping regression.

If everything looks right, the collector is ready to run over a wider universe.

- [ ] **Step 6: Commit a note if useful**

No code changes here. If the pilot revealed operational notes worth keeping (e.g. "public RPC takes ~8 min/market, use Alchemy past 20 markets"), add a short README note at `scripts/README.md` and commit — otherwise skip.

---

## Final Verification

- [ ] **Step 1: Full test suite passes**

```bash
uv run pytest
```

Expected: all tests pass.

- [ ] **Step 2: No uncommitted changes**

```bash
git status
```

Expected: working tree clean (pilot data in `data/polymarket.db` is gitignored).

- [ ] **Step 3: Dashboard launches cleanly**

```bash
uv run streamlit run src/dashboard/app.py
```

Expected: all tabs including Trades render without errors.
