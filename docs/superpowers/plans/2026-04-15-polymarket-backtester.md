# Polymarket Backtester Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a backtesting tool that validates the "nothing ever happens" thesis on Polymarket by fetching resolved markets, running "No" entry strategies, and computing expected value.

**Architecture:** Three-stage pipeline — data collector (Polymarket APIs + Polygon on-chain) writes to SQLite via SQLAlchemy, backtest engine runs strategies against stored data, Streamlit dashboard visualizes results. Each stage runs independently.

**Tech Stack:** Python 3.11+, SQLAlchemy 2.0, httpx, web3.py, Streamlit, Plotly, SQLite

---

## File Structure

```
polymarket/
├── pyproject.toml
├── .gitignore
├── .env.example
├── src/
│   ├── __init__.py
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── models.py           # SQLAlchemy ORM models
│   │   └── db.py               # Engine/session factory
│   ├── collector/
│   │   ├── __init__.py
│   │   ├── categories.py       # Category classification logic
│   │   ├── polymarket_api.py   # Gamma API client (market metadata)
│   │   ├── price_history.py    # CLOB API client (price timeseries)
│   │   ├── polygon_chain.py    # On-chain price enrichment
│   │   └── runner.py           # Orchestrates collection + CLI
│   ├── backtester/
│   │   ├── __init__.py
│   │   ├── strategies.py       # Entry strategy functions
│   │   ├── engine.py           # Runs strategies + persists results
│   │   └── metrics.py          # Aggregation + EV computation
│   └── dashboard/
│       ├── __init__.py
│       └── app.py              # Streamlit app (all views)
├── tests/
│   ├── __init__.py
│   ├── conftest.py             # Shared DB fixtures
│   ├── test_models.py
│   ├── test_categories.py
│   ├── test_polymarket_api.py
│   ├── test_price_history.py
│   ├── test_strategies.py
│   ├── test_engine.py
│   └── test_metrics.py
└── data/                       # SQLite DB lives here (gitignored)
```

---

### Task 1: Project Setup

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `.env.example`
- Create: all `__init__.py` files
- Create: `data/.gitkeep`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "polymarket-backtester"
version = "0.1.0"
description = "Backtester for the 'nothing ever happens' thesis on Polymarket"
requires-python = ">=3.11"
dependencies = [
    "sqlalchemy>=2.0",
    "httpx>=0.27",
    "web3>=7.0",
    "streamlit>=1.38",
    "plotly>=5.24",
    "python-dotenv>=1.0",
    "pandas>=2.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
]

[tool.hatch.build.targets.wheel]
packages = ["src"]

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
```

- [ ] **Step 2: Create `.gitignore`**

```
__pycache__/
*.pyc
.env
data/*.db
*.egg-info/
dist/
.venv/
```

- [ ] **Step 3: Create `.env.example`**

```bash
# Optional: Polygon RPC endpoint for on-chain data enrichment
# Default: https://polygon-rpc.com (public, rate-limited)
POLYGON_RPC_URL=https://polygon-rpc.com
```

- [ ] **Step 4: Create directory structure**

```bash
mkdir -p src/storage src/collector src/backtester src/dashboard tests data
touch src/__init__.py src/storage/__init__.py src/collector/__init__.py src/backtester/__init__.py src/dashboard/__init__.py tests/__init__.py
touch data/.gitkeep
```

- [ ] **Step 5: Install dependencies**

```bash
pip install -e ".[dev]"
```

Run: `python -c "import sqlalchemy; import httpx; print('OK')"`
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml .gitignore .env.example src/ tests/ data/.gitkeep
git commit -m "chore: scaffold project structure and dependencies"
```

---

### Task 2: Storage Layer

**Files:**
- Create: `src/storage/models.py`
- Create: `src/storage/db.py`
- Create: `tests/conftest.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: Write failing test for models**

Create `tests/test_models.py`:

```python
from datetime import datetime, timezone

from src.storage.models import Market, PriceSnapshot, BacktestResult


def test_create_market(session):
    market = Market(
        id="0xabc123",
        question="Will X happen by 2025?",
        category="geopolitical",
        no_token_id="99887766",
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        resolved_at=datetime(2024, 12, 31, tzinfo=timezone.utc),
        resolution="No",
        source_url="https://polymarket.com/event/test-slug",
    )
    session.add(market)
    session.commit()

    result = session.get(Market, "0xabc123")
    assert result is not None
    assert result.question == "Will X happen by 2025?"
    assert result.resolution == "No"
    assert result.category == "geopolitical"


def test_create_price_snapshot(session):
    market = Market(
        id="0xabc123",
        question="Test market",
        category="political",
        no_token_id="99887766",
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    session.add(market)
    session.flush()

    snapshot = PriceSnapshot(
        market_id="0xabc123",
        timestamp=datetime(2024, 1, 2, tzinfo=timezone.utc),
        no_price=0.85,
        source="api",
    )
    session.add(snapshot)
    session.commit()

    result = session.query(PriceSnapshot).filter_by(market_id="0xabc123").first()
    assert result is not None
    assert result.no_price == 0.85
    assert result.source == "api"


def test_create_backtest_result(session):
    market = Market(
        id="0xabc123",
        question="Test market",
        category="political",
        no_token_id="99887766",
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        resolved_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
        resolution="No",
    )
    session.add(market)
    session.flush()

    result = BacktestResult(
        market_id="0xabc123",
        strategy="threshold_0.85",
        entry_price=0.85,
        entry_timestamp=datetime(2024, 1, 15, tzinfo=timezone.utc),
        exit_price=1.0,
        profit=0.15,
        category="political",
        run_id="run_001",
    )
    session.add(result)
    session.commit()

    fetched = session.query(BacktestResult).filter_by(run_id="run_001").first()
    assert fetched is not None
    assert fetched.profit == 0.15
    assert fetched.strategy == "threshold_0.85"


def test_market_price_snapshots_relationship(session):
    market = Market(
        id="0xabc123",
        question="Test market",
        category="culture",
        no_token_id="99887766",
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    session.add(market)
    session.flush()

    for i, price in enumerate([0.90, 0.85, 0.80]):
        session.add(PriceSnapshot(
            market_id="0xabc123",
            timestamp=datetime(2024, 1, i + 1, tzinfo=timezone.utc),
            no_price=price,
            source="api",
        ))
    session.commit()

    result = session.get(Market, "0xabc123")
    assert len(result.price_snapshots) == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.storage.models'`

- [ ] **Step 3: Write `src/storage/models.py`**

```python
from datetime import datetime

from sqlalchemy import String, Float, DateTime, Text, ForeignKey, Integer
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Market(Base):
    __tablename__ = "markets"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    question: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String)
    no_token_id: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution: Mapped[str | None] = mapped_column(String, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    price_snapshots: Mapped[list["PriceSnapshot"]] = relationship(
        back_populates="market", order_by="PriceSnapshot.timestamp"
    )
    backtest_results: Mapped[list["BacktestResult"]] = relationship(
        back_populates="market"
    )


class PriceSnapshot(Base):
    __tablename__ = "price_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_id: Mapped[str] = mapped_column(ForeignKey("markets.id"))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    no_price: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String)

    market: Mapped["Market"] = relationship(back_populates="price_snapshots")


class BacktestResult(Base):
    __tablename__ = "backtest_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_id: Mapped[str] = mapped_column(ForeignKey("markets.id"))
    strategy: Mapped[str] = mapped_column(String)
    entry_price: Mapped[float] = mapped_column(Float)
    entry_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    exit_price: Mapped[float] = mapped_column(Float)
    profit: Mapped[float] = mapped_column(Float)
    category: Mapped[str] = mapped_column(String)
    run_id: Mapped[str] = mapped_column(String)

    market: Mapped["Market"] = relationship(back_populates="backtest_results")
```

- [ ] **Step 4: Write `src/storage/db.py`**

```python
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.storage.models import Base

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"


def get_engine(db_path: str | None = None):
    if db_path is None:
        db_path = str(DATA_DIR / "polymarket.db")
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    return engine


def get_session(engine) -> Session:
    return Session(engine)
```

- [ ] **Step 5: Write `tests/conftest.py`**

```python
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.storage.models import Base


@pytest.fixture
def engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine):
    with Session(engine) as session:
        yield session
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_models.py -v`
Expected: 4 passed

- [ ] **Step 7: Commit**

```bash
git add src/storage/ tests/conftest.py tests/test_models.py
git commit -m "feat: add SQLAlchemy storage models and DB setup"
```

---

### Task 3: Category Mapping

**Files:**
- Create: `src/collector/categories.py`
- Create: `tests/test_categories.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_categories.py`:

```python
from src.collector.categories import classify_market


def test_geopolitical_classification():
    assert classify_market("Will Russia invade Finland by 2025?", None) == "geopolitical"
    assert classify_market("Will China blockade Taiwan?", None) == "geopolitical"
    assert classify_market("Will NATO deploy troops to Ukraine?", None) == "geopolitical"
    assert classify_market("Will Iran strike Israel before June?", None) == "geopolitical"


def test_political_classification():
    assert classify_market("Will Congress pass the TikTok ban?", None) == "political"
    assert classify_market("Will Biden sign the infrastructure bill?", None) == "political"
    assert classify_market("Will the Senate confirm the nominee?", None) == "political"
    assert classify_market("Will there be a government shutdown?", None) == "political"


def test_culture_classification():
    assert classify_market("Will Taylor Swift announce retirement?", None) == "culture"
    assert classify_market("Who will win Best Picture at the Oscars?", None) == "culture"
    assert classify_market("Will the Super Bowl halftime show feature Drake?", None) == "culture"
    assert classify_market("Will Elon Musk appear on SNL again?", None) == "culture"


def test_category_from_api_tag():
    assert classify_market("Some unclear question", "Politics") == "political"
    assert classify_market("Some unclear question", "Pop Culture") == "culture"
    assert classify_market("Some unclear question", "Geopolitics") == "geopolitical"


def test_other_fallback():
    assert classify_market("Will Bitcoin hit $100k?", None) == "other"
    assert classify_market("What will the weather be?", None) == "other"


def test_case_insensitive():
    assert classify_market("WILL NATO EXPAND?", None) == "geopolitical"
    assert classify_market("will congress act?", None) == "political"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_categories.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write `src/collector/categories.py`**

```python
import re

# API tag label -> our category
TAG_MAP: dict[str, str] = {
    "politics": "political",
    "us politics": "political",
    "elections": "political",
    "geopolitics": "geopolitical",
    "world": "geopolitical",
    "pop culture": "culture",
    "entertainment": "culture",
    "sports": "culture",
    "celebrities": "culture",
}

# Keyword patterns for classification from question text
CATEGORY_PATTERNS: dict[str, list[str]] = {
    "geopolitical": [
        r"\b(invade|invasion|blockade|nato|troops|missile|nuclear|sanctions|annex)\b",
        r"\b(russia|china|iran|ukraine|taiwan|israel|north korea|syria)\b",
        r"\b(war|conflict|military|strike|deploy|ceasefire|treaty)\b",
    ],
    "political": [
        r"\b(congress|senate|house|parliament|legislation|bill|law|act)\b",
        r"\b(president|governor|mayor|election|vote|ballot|impeach)\b",
        r"\b(government shutdown|executive order|veto|filibuster|confirm)\b",
        r"\b(biden|trump|democrat|republican|gop)\b",
    ],
    "culture": [
        r"\b(oscar|grammy|emmy|tony|golden globe|award show)\b",
        r"\b(super bowl|world series|nba|nfl|world cup|olympics)\b",
        r"\b(taylor swift|beyonce|drake|kanye|elon musk|celebrity)\b",
        r"\b(movie|album|tour|concert|halftime|snl|netflix|spotify)\b",
        r"\b(retire|comeback|announce|release|premiere)\b",
    ],
}


def classify_market(question: str, api_category: str | None) -> str:
    # First, try to classify from the API-provided category/tag
    if api_category:
        tag_lower = api_category.lower()
        for tag_key, our_category in TAG_MAP.items():
            if tag_key in tag_lower:
                return our_category

    # Fall back to keyword matching on the question text
    question_lower = question.lower()
    for category, patterns in CATEGORY_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, question_lower):
                return category

    return "other"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_categories.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/collector/categories.py tests/test_categories.py
git commit -m "feat: add category classification for market questions"
```

---

### Task 4: Polymarket API Client

**Files:**
- Create: `src/collector/polymarket_api.py`
- Create: `tests/test_polymarket_api.py`

- [ ] **Step 1: Write failing test for response parsing**

Create `tests/test_polymarket_api.py`:

```python
import json
from datetime import datetime, timezone

from src.collector.polymarket_api import parse_market, determine_resolution


# Realistic fixture based on actual Gamma API response
SAMPLE_GAMMA_MARKET = {
    "id": "1237864",
    "conditionId": "0xa6d544beef271a4e941e55897ee14396c2c3b656a44aba63c8de5854e919eaa6",
    "slug": "will-russia-invade-finland-2025",
    "question": "Will Russia invade Finland by 2025?",
    "outcomes": json.dumps(["Yes", "No"]),
    "outcomePrices": json.dumps(["0", "1"]),
    "clobTokenIds": json.dumps(["13915383884", "52791640887"]),
    "volume": "50000.00",
    "volumeNum": 50000.0,
    "active": False,
    "closed": True,
    "createdAt": "2024-01-15T00:00:00.000000Z",
    "endDate": "2025-01-01T00:00:00Z",
    "closedTime": "2024-12-31 23:59:59+00",
    "category": "Geopolitics",
    "negRisk": False,
}

SAMPLE_YES_WIN_MARKET = {
    "id": "9999999",
    "conditionId": "0xbbb222",
    "slug": "will-gov-shutdown-oct",
    "question": "Will there be a government shutdown in October?",
    "outcomes": json.dumps(["Yes", "No"]),
    "outcomePrices": json.dumps(["1", "0"]),
    "clobTokenIds": json.dumps(["111111", "222222"]),
    "volume": "10000.00",
    "volumeNum": 10000.0,
    "active": False,
    "closed": True,
    "createdAt": "2024-08-01T00:00:00.000000Z",
    "endDate": "2024-11-01T00:00:00Z",
    "closedTime": "2024-10-15 12:00:00+00",
    "category": None,
    "negRisk": False,
}


def test_determine_resolution_no_wins():
    outcomes = ["Yes", "No"]
    prices = ["0", "1"]
    assert determine_resolution(outcomes, prices) == "No"


def test_determine_resolution_yes_wins():
    outcomes = ["Yes", "No"]
    prices = ["1", "0"]
    assert determine_resolution(outcomes, prices) == "Yes"


def test_determine_resolution_unresolved():
    outcomes = ["Yes", "No"]
    prices = ["0.5", "0.5"]
    assert determine_resolution(outcomes, prices) is None


def test_determine_resolution_near_one():
    outcomes = ["Yes", "No"]
    prices = ["0.001", "0.999"]
    assert determine_resolution(outcomes, prices) == "No"


def test_parse_market_no_resolution():
    result = parse_market(SAMPLE_GAMMA_MARKET)
    assert result["id"] == "0xa6d544beef271a4e941e55897ee14396c2c3b656a44aba63c8de5854e919eaa6"
    assert result["question"] == "Will Russia invade Finland by 2025?"
    assert result["resolution"] == "No"
    assert result["no_token_id"] == "52791640887"
    assert result["category"] == "geopolitical"
    assert result["source_url"] == "https://polymarket.com/event/will-russia-invade-finland-2025"
    assert isinstance(result["created_at"], datetime)


def test_parse_market_yes_resolution():
    result = parse_market(SAMPLE_YES_WIN_MARKET)
    assert result["resolution"] == "Yes"
    assert result["category"] == "political"
    assert result["no_token_id"] == "222222"


def test_parse_market_skips_neg_risk():
    market = {**SAMPLE_GAMMA_MARKET, "negRisk": True}
    result = parse_market(market)
    assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_polymarket_api.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write `src/collector/polymarket_api.py`**

```python
import json
import time
from datetime import datetime, timezone

import httpx

from src.collector.categories import classify_market

GAMMA_API_BASE = "https://gamma-api.polymarket.com"
MARKETS_PER_PAGE = 100


def determine_resolution(outcomes: list[str], prices: list[str]) -> str | None:
    float_prices = [float(p) for p in prices]
    for i, price in enumerate(float_prices):
        if price > 0.9:
            return outcomes[i]
    return None


def parse_market(raw: dict) -> dict | None:
    # Skip multi-outcome (negRisk) markets — we only handle binary Yes/No
    if raw.get("negRisk"):
        return None

    outcomes = json.loads(raw["outcomes"])
    prices = json.loads(raw["outcomePrices"])
    clob_token_ids = json.loads(raw["clobTokenIds"])

    # We need exactly 2 outcomes for binary markets
    if len(outcomes) != 2:
        return None

    resolution = determine_resolution(outcomes, prices)

    # Find the "No" token ID — it corresponds to the "No" position in outcomes
    try:
        no_idx = outcomes.index("No")
    except ValueError:
        # Non-standard outcomes (e.g., team names) — use index 1 as "No"
        no_idx = 1

    no_token_id = clob_token_ids[no_idx]

    created_at = datetime.fromisoformat(raw["createdAt"].replace("Z", "+00:00"))

    resolved_at = None
    if raw.get("closedTime"):
        try:
            resolved_at = datetime.fromisoformat(raw["closedTime"].replace(" ", "T"))
        except ValueError:
            pass

    category = classify_market(raw["question"], raw.get("category"))
    slug = raw.get("slug", "")

    return {
        "id": raw["conditionId"],
        "question": raw["question"],
        "category": category,
        "no_token_id": no_token_id,
        "created_at": created_at,
        "resolved_at": resolved_at,
        "resolution": resolution,
        "source_url": f"https://polymarket.com/event/{slug}" if slug else None,
    }


def fetch_resolved_markets(
    categories: list[str] | None = None,
    limit: int | None = None,
) -> list[dict]:
    """Fetch all resolved markets from the Gamma API with pagination."""
    client = httpx.Client(timeout=30)
    all_markets = []
    offset = 0

    while True:
        params = {
            "closed": "true",
            "resolved": "true",
            "limit": MARKETS_PER_PAGE,
            "offset": offset,
            "order": "createdAt",
            "ascending": "false",
        }

        response = client.get(f"{GAMMA_API_BASE}/markets", params=params)
        response.raise_for_status()
        raw_markets = response.json()

        # Handle both bare array and {data: []} response formats
        if isinstance(raw_markets, dict):
            raw_markets = raw_markets.get("data", [])

        if not raw_markets:
            break

        for raw in raw_markets:
            parsed = parse_market(raw)
            if parsed is None:
                continue
            if categories and parsed["category"] not in categories:
                continue
            all_markets.append(parsed)

            if limit and len(all_markets) >= limit:
                client.close()
                return all_markets[:limit]

        offset += MARKETS_PER_PAGE

        # Respect rate limits (300 req/10s)
        time.sleep(0.05)

    client.close()
    return all_markets
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_polymarket_api.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/collector/polymarket_api.py tests/test_polymarket_api.py
git commit -m "feat: add Polymarket Gamma API client with market parsing"
```

---

### Task 5: Price History Client

**Files:**
- Create: `src/collector/price_history.py`
- Create: `tests/test_price_history.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_price_history.py`:

```python
from datetime import datetime, timezone

from src.collector.price_history import parse_price_history


SAMPLE_CLOB_RESPONSE = {
    "history": [
        {"t": 1704067200, "p": 0.92},
        {"t": 1704153600, "p": 0.88},
        {"t": 1704240000, "p": 0.85},
        {"t": 1704326400, "p": 0.83},
        {"t": 1704412800, "p": 0.90},
    ]
}

EMPTY_RESPONSE = {"history": []}


def test_parse_price_history():
    snapshots = parse_price_history(SAMPLE_CLOB_RESPONSE, market_id="0xabc")
    assert len(snapshots) == 5
    assert snapshots[0]["no_price"] == 0.92
    assert snapshots[0]["source"] == "api"
    assert snapshots[0]["market_id"] == "0xabc"
    assert isinstance(snapshots[0]["timestamp"], datetime)


def test_parse_price_history_timestamps():
    snapshots = parse_price_history(SAMPLE_CLOB_RESPONSE, market_id="0xabc")
    # 1704067200 = 2024-01-01 00:00:00 UTC
    assert snapshots[0]["timestamp"] == datetime(2024, 1, 1, tzinfo=timezone.utc)


def test_parse_price_history_sorted_by_time():
    snapshots = parse_price_history(SAMPLE_CLOB_RESPONSE, market_id="0xabc")
    timestamps = [s["timestamp"] for s in snapshots]
    assert timestamps == sorted(timestamps)


def test_parse_empty_history():
    snapshots = parse_price_history(EMPTY_RESPONSE, market_id="0xabc")
    assert snapshots == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_price_history.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write `src/collector/price_history.py`**

```python
import time
from datetime import datetime, timezone

import httpx

CLOB_API_BASE = "https://clob.polymarket.com"


def parse_price_history(response_data: dict, market_id: str) -> list[dict]:
    history = response_data.get("history", [])
    snapshots = []
    for point in history:
        snapshots.append({
            "market_id": market_id,
            "timestamp": datetime.fromtimestamp(point["t"], tz=timezone.utc),
            "no_price": float(point["p"]),
            "source": "api",
        })
    snapshots.sort(key=lambda s: s["timestamp"])
    return snapshots


def fetch_price_history(token_id: str, market_id: str) -> list[dict]:
    """Fetch full price history for a No token from the CLOB API."""
    client = httpx.Client(timeout=30)

    params = {
        "market": token_id,
        "interval": "max",
        "fidelity": 60,  # Hourly data points
    }

    response = client.get(f"{CLOB_API_BASE}/prices-history", params=params)
    response.raise_for_status()

    snapshots = parse_price_history(response.json(), market_id)
    client.close()
    return snapshots


def fetch_price_histories_batch(
    token_market_pairs: list[tuple[str, str]],
) -> dict[str, list[dict]]:
    """Fetch price history for multiple tokens. Returns {market_id: [snapshots]}."""
    result = {}
    for token_id, market_id in token_market_pairs:
        try:
            snapshots = fetch_price_history(token_id, market_id)
            result[market_id] = snapshots
        except httpx.HTTPStatusError:
            result[market_id] = []
        # Respect rate limits
        time.sleep(0.02)
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_price_history.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/collector/price_history.py tests/test_price_history.py
git commit -m "feat: add CLOB API price history client"
```

---

### Task 6: Polygon On-Chain Price Enrichment

**Files:**
- Create: `src/collector/polygon_chain.py`
- Create: `tests/test_polygon_chain.py`

- [ ] **Step 1: Write failing test for price computation from events**

Create `tests/test_polygon_chain.py`:

```python
from datetime import datetime, timezone

from src.collector.polygon_chain import compute_price_from_event, filter_events_for_token


SAMPLE_ORDER_FILLED_EVENT = {
    "args": {
        "orderHash": b"\x01" * 32,
        "maker": "0xMakerAddress",
        "taker": "0xTakerAddress",
        "makerAssetId": 0,           # 0 = USDC (buyer side)
        "takerAssetId": 52791640887,  # No token
        "makerAmountFilled": 850000,  # 0.85 USDC (6 decimals)
        "takerAmountFilled": 1000000, # 1.0 token (6 decimals)
        "fee": 0,
    },
    "blockNumber": 50000000,
}

SAMPLE_SELL_EVENT = {
    "args": {
        "orderHash": b"\x02" * 32,
        "maker": "0xSellerAddress",
        "taker": "0xBuyerAddress",
        "makerAssetId": 52791640887,  # No token (seller side)
        "takerAssetId": 0,            # 0 = USDC
        "makerAmountFilled": 1000000, # 1.0 token
        "takerAmountFilled": 900000,  # 0.90 USDC
        "fee": 0,
    },
    "blockNumber": 50000100,
}

UNRELATED_EVENT = {
    "args": {
        "orderHash": b"\x03" * 32,
        "maker": "0xOther",
        "taker": "0xOther2",
        "makerAssetId": 0,
        "takerAssetId": 99999999,  # Different token
        "makerAmountFilled": 500000,
        "takerAmountFilled": 1000000,
        "fee": 0,
    },
    "blockNumber": 50000200,
}


def test_compute_price_buyer_side():
    # Maker is buyer: makerAssetId=0 (USDC), takerAssetId=token
    # Price = USDC / tokens = 850000 / 1000000 = 0.85
    price = compute_price_from_event(SAMPLE_ORDER_FILLED_EVENT["args"])
    assert price == 0.85


def test_compute_price_seller_side():
    # Maker is seller: makerAssetId=token, takerAssetId=0 (USDC)
    # Price = USDC / tokens = 900000 / 1000000 = 0.90
    price = compute_price_from_event(SAMPLE_SELL_EVENT["args"])
    assert price == 0.90


def test_filter_events_for_token():
    events = [SAMPLE_ORDER_FILLED_EVENT, SAMPLE_SELL_EVENT, UNRELATED_EVENT]
    filtered = filter_events_for_token(events, token_id=52791640887)
    assert len(filtered) == 2


def test_filter_events_excludes_unrelated():
    events = [UNRELATED_EVENT]
    filtered = filter_events_for_token(events, token_id=52791640887)
    assert len(filtered) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_polygon_chain.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write `src/collector/polygon_chain.py`**

```python
import os
import time
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

# Polymarket CTF Exchange on Polygon
CTF_EXCHANGE_ADDRESS = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"

# Minimal ABI for OrderFilled event only
ORDER_FILLED_ABI = [
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "orderHash", "type": "bytes32"},
            {"indexed": True, "name": "maker", "type": "address"},
            {"indexed": True, "name": "taker", "type": "address"},
            {"indexed": False, "name": "makerAssetId", "type": "uint256"},
            {"indexed": False, "name": "takerAssetId", "type": "uint256"},
            {"indexed": False, "name": "makerAmountFilled", "type": "uint256"},
            {"indexed": False, "name": "takerAmountFilled", "type": "uint256"},
            {"indexed": False, "name": "fee", "type": "uint256"},
        ],
        "name": "OrderFilled",
        "type": "event",
    }
]

DECIMALS = 6
BLOCK_CHUNK = 10_000  # ~5.5 hours on Polygon (2s blocks)
POLYGON_BLOCK_TIME_SECS = 2


def compute_price_from_event(args: dict) -> float:
    """Compute the No token price from an OrderFilled event's arguments.

    Asset ID 0 = USDC collateral. Non-zero = outcome token.
    Price = USDC amount / token amount.
    """
    maker_asset = args["makerAssetId"]
    taker_asset = args["takerAssetId"]
    maker_amount = args["makerAmountFilled"]
    taker_amount = args["takerAmountFilled"]

    if maker_asset == 0:
        # Maker is buyer: paying USDC (makerAmount) for tokens (takerAmount)
        return maker_amount / taker_amount
    elif taker_asset == 0:
        # Maker is seller: giving tokens (makerAmount) for USDC (takerAmount)
        return taker_amount / maker_amount
    else:
        # Both non-zero — token-for-token swap, skip
        return -1.0


def filter_events_for_token(events: list[dict], token_id: int) -> list[dict]:
    """Keep only OrderFilled events involving the given token ID."""
    return [
        e for e in events
        if e["args"]["makerAssetId"] == token_id
        or e["args"]["takerAssetId"] == token_id
    ]


def estimate_block_for_timestamp(target_ts: float, latest_block_num: int, latest_block_ts: float) -> int:
    """Estimate the Polygon block number for a given unix timestamp."""
    diff_secs = latest_block_ts - target_ts
    diff_blocks = int(diff_secs / POLYGON_BLOCK_TIME_SECS)
    return max(0, latest_block_num - diff_blocks)


def fetch_onchain_prices(
    no_token_id: str,
    market_id: str,
    created_at: datetime,
    resolved_at: datetime | None,
) -> list[dict]:
    """Fetch price data from Polygon OrderFilled events for a No token.

    Requires web3.py and a Polygon RPC endpoint. This is an enrichment step —
    the CLOB API price history is the primary data source.
    """
    try:
        from web3 import Web3
    except ImportError:
        return []

    rpc_url = os.getenv("POLYGON_RPC_URL", "https://polygon-rpc.com")
    w3 = Web3(Web3.HTTPProvider(rpc_url))

    if not w3.is_connected():
        return []

    contract = w3.eth.contract(
        address=Web3.to_checksum_address(CTF_EXCHANGE_ADDRESS),
        abi=ORDER_FILLED_ABI,
    )

    latest_block = w3.eth.block_number
    latest_ts = float(w3.eth.get_block(latest_block)["timestamp"])

    start_block = estimate_block_for_timestamp(
        created_at.timestamp(), latest_block, latest_ts
    )
    end_block = (
        estimate_block_for_timestamp(resolved_at.timestamp(), latest_block, latest_ts)
        if resolved_at
        else latest_block
    )

    token_id_int = int(no_token_id)
    snapshots = []

    for chunk_start in range(start_block, end_block, BLOCK_CHUNK):
        chunk_end = min(chunk_start + BLOCK_CHUNK - 1, end_block)
        try:
            events = contract.events.OrderFilled.get_logs(
                fromBlock=chunk_start, toBlock=chunk_end
            )
        except Exception:
            continue

        relevant = filter_events_for_token(events, token_id_int)
        for event in relevant:
            price = compute_price_from_event(event["args"])
            if price < 0:
                continue
            block = w3.eth.get_block(event["blockNumber"])
            snapshots.append({
                "market_id": market_id,
                "timestamp": datetime.fromtimestamp(block["timestamp"], tz=timezone.utc),
                "no_price": price,
                "source": "polygon",
            })

        time.sleep(0.1)  # Rate limit for public RPC

    snapshots.sort(key=lambda s: s["timestamp"])
    return snapshots
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_polygon_chain.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/collector/polygon_chain.py tests/test_polygon_chain.py
git commit -m "feat: add Polygon on-chain price enrichment module"
```

---

### Task 7: Collection Runner

**Files:**
- Create: `src/collector/runner.py`

- [ ] **Step 1: Write `src/collector/runner.py`**

```python
import argparse
import sys

from sqlalchemy.orm import Session

from src.storage.db import get_engine, get_session
from src.storage.models import Market, PriceSnapshot
from src.collector.polymarket_api import fetch_resolved_markets
from src.collector.price_history import fetch_price_history
from src.collector.polygon_chain import fetch_onchain_prices


def upsert_market(session: Session, market_data: dict) -> bool:
    """Insert or update a market. Returns True if new."""
    existing = session.get(Market, market_data["id"])
    if existing:
        existing.resolution = market_data["resolution"]
        existing.resolved_at = market_data["resolved_at"]
        return False

    market = Market(**market_data)
    session.add(market)
    return True


def store_price_snapshots(session: Session, snapshots: list[dict], market_id: str):
    """Store price snapshots, skipping duplicates by timestamp+source."""
    existing_timestamps = set(
        row[0]
        for row in session.query(PriceSnapshot.timestamp)
        .filter_by(market_id=market_id)
        .all()
    )
    new_snapshots = [
        PriceSnapshot(**s)
        for s in snapshots
        if s["timestamp"] not in existing_timestamps
    ]
    session.add_all(new_snapshots)


def collect(
    categories: list[str] | None = None,
    limit: int | None = None,
    enrich_onchain: bool = False,
    db_path: str | None = None,
):
    """Main collection pipeline: fetch markets, fetch prices, store everything."""
    engine = get_engine(db_path)
    session = get_session(engine)

    print(f"Fetching resolved markets from Polymarket API...")
    markets = fetch_resolved_markets(categories=categories, limit=limit)
    print(f"Found {len(markets)} markets")

    new_count = 0
    for i, market_data in enumerate(markets):
        is_new = upsert_market(session, market_data)
        if is_new:
            new_count += 1
        session.flush()

        # Fetch price history from CLOB API
        print(f"  [{i+1}/{len(markets)}] {market_data['question'][:60]}...")
        snapshots = fetch_price_history(
            token_id=market_data["no_token_id"],
            market_id=market_data["id"],
        )

        # Optionally enrich with on-chain data
        if enrich_onchain:
            onchain = fetch_onchain_prices(
                no_token_id=market_data["no_token_id"],
                market_id=market_data["id"],
                created_at=market_data["created_at"],
                resolved_at=market_data["resolved_at"],
            )
            snapshots.extend(onchain)

        store_price_snapshots(session, snapshots, market_data["id"])

        # Commit in batches of 10
        if (i + 1) % 10 == 0:
            session.commit()

    session.commit()
    session.close()
    engine.dispose()

    print(f"Done. {new_count} new markets added, {len(markets) - new_count} updated.")


def main():
    parser = argparse.ArgumentParser(description="Collect Polymarket data")
    parser.add_argument(
        "--categories",
        type=str,
        default=None,
        help="Comma-separated categories: geopolitical,political,culture",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max number of markets to fetch",
    )
    parser.add_argument(
        "--enrich-onchain",
        action="store_true",
        help="Also fetch on-chain price data from Polygon (slow)",
    )
    args = parser.parse_args()

    categories = args.categories.split(",") if args.categories else None
    collect(categories=categories, limit=args.limit, enrich_onchain=args.enrich_onchain)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify it runs (dry-run help)**

Run: `python -m src.collector.runner --help`
Expected output including `--categories`, `--limit`, `--enrich-onchain` options

- [ ] **Step 3: Commit**

```bash
git add src/collector/runner.py
git commit -m "feat: add collection runner with CLI interface"
```

---

### Task 8: Entry Strategies

**Files:**
- Create: `src/backtester/strategies.py`
- Create: `tests/test_strategies.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_strategies.py`:

```python
from datetime import datetime, timedelta, timezone

from src.backtester.strategies import (
    at_creation,
    price_threshold,
    time_snapshot,
    best_price,
)


# Helper to create a simple price history
def make_history(prices_with_offsets: list[tuple[int, float]], base_time: datetime | None = None):
    """Create price history from (hours_offset, price) pairs."""
    if base_time is None:
        base_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return [
        {"timestamp": base_time + timedelta(hours=h), "no_price": p}
        for h, p in prices_with_offsets
    ]


CREATED_AT = datetime(2024, 1, 1, tzinfo=timezone.utc)


# -- at_creation tests --

def test_at_creation_returns_first_price():
    history = make_history([(1, 0.90), (2, 0.85), (3, 0.80)])
    result = at_creation(CREATED_AT, history)
    assert result == (0.90, CREATED_AT + timedelta(hours=1))


def test_at_creation_empty_history():
    result = at_creation(CREATED_AT, [])
    assert result is None


# -- price_threshold tests --

def test_threshold_finds_first_below():
    history = make_history([(1, 0.92), (2, 0.88), (3, 0.84), (4, 0.80)])
    result = price_threshold(CREATED_AT, history, threshold=0.85)
    assert result == (0.84, CREATED_AT + timedelta(hours=3))


def test_threshold_exact_match():
    history = make_history([(1, 0.90), (2, 0.85)])
    result = price_threshold(CREATED_AT, history, threshold=0.85)
    assert result == (0.85, CREATED_AT + timedelta(hours=2))


def test_threshold_never_met():
    history = make_history([(1, 0.92), (2, 0.90)])
    result = price_threshold(CREATED_AT, history, threshold=0.85)
    assert result is None


def test_threshold_empty_history():
    result = price_threshold(CREATED_AT, [], threshold=0.85)
    assert result is None


# -- time_snapshot tests --

def test_snapshot_finds_closest():
    history = make_history([(22, 0.90), (25, 0.88), (48, 0.85)])
    # Looking for 24h after creation — closest is 25h
    result = time_snapshot(CREATED_AT, history, offset_hours=24)
    assert result == (0.88, CREATED_AT + timedelta(hours=25))


def test_snapshot_exact_match():
    history = make_history([(24, 0.87), (48, 0.85)])
    result = time_snapshot(CREATED_AT, history, offset_hours=24)
    assert result == (0.87, CREATED_AT + timedelta(hours=24))


def test_snapshot_no_data_within_window():
    # All data is >48h away from target — too far
    history = make_history([(100, 0.80), (200, 0.75)])
    result = time_snapshot(CREATED_AT, history, offset_hours=24)
    assert result is None


def test_snapshot_empty_history():
    result = time_snapshot(CREATED_AT, [], offset_hours=24)
    assert result is None


# -- best_price tests --

def test_best_price_finds_minimum():
    history = make_history([(1, 0.90), (2, 0.75), (3, 0.85)])
    result = best_price(CREATED_AT, history)
    assert result == (0.75, CREATED_AT + timedelta(hours=2))


def test_best_price_empty_history():
    result = best_price(CREATED_AT, [])
    assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_strategies.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write `src/backtester/strategies.py`**

```python
from datetime import datetime, timedelta


# Maximum time distance for a snapshot to be considered "close enough" to a target time
SNAPSHOT_MAX_DISTANCE_HOURS = 12


def at_creation(
    created_at: datetime, price_history: list[dict]
) -> tuple[float, datetime] | None:
    """Entry at the first recorded No price after market creation."""
    if not price_history:
        return None
    first = price_history[0]
    return (first["no_price"], first["timestamp"])


def price_threshold(
    created_at: datetime,
    price_history: list[dict],
    threshold: float,
) -> tuple[float, datetime] | None:
    """Entry at the first No price at or below the threshold."""
    for point in price_history:
        if point["no_price"] <= threshold:
            return (point["no_price"], point["timestamp"])
    return None


def time_snapshot(
    created_at: datetime,
    price_history: list[dict],
    offset_hours: int,
) -> tuple[float, datetime] | None:
    """Entry at the No price closest to `created_at + offset_hours`."""
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


def best_price(
    created_at: datetime, price_history: list[dict]
) -> tuple[float, datetime] | None:
    """Entry at the lowest No price observed (theoretical perfect timing)."""
    if not price_history:
        return None
    best = min(price_history, key=lambda p: p["no_price"])
    return (best["no_price"], best["timestamp"])


# Registry for easy lookup by name
STRATEGIES = {
    "at_creation": {"fn": at_creation, "params": [{}]},
    "threshold": {
        "fn": price_threshold,
        "params": [
            {"threshold": t} for t in [0.70, 0.75, 0.80, 0.85, 0.90, 0.95]
        ],
    },
    "snapshot": {
        "fn": time_snapshot,
        "params": [
            {"offset_hours": h} for h in [24, 48, 168]  # 1d, 2d, 7d
        ],
    },
    "best_price": {"fn": best_price, "params": [{}]},
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_strategies.py -v`
Expected: 12 passed

- [ ] **Step 5: Commit**

```bash
git add src/backtester/strategies.py tests/test_strategies.py
git commit -m "feat: add four backtesting entry strategies"
```

---

### Task 9: Backtest Engine

**Files:**
- Create: `src/backtester/engine.py`
- Create: `tests/test_engine.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_engine.py`:

```python
import uuid
from datetime import datetime, timedelta, timezone

from src.storage.models import Market, PriceSnapshot, BacktestResult
from src.backtester.engine import run_backtest


def _seed_data(session):
    """Create two markets with price histories for testing."""
    m1 = Market(
        id="0xcond1",
        question="Will X invade Y?",
        category="geopolitical",
        no_token_id="token_1",
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        resolved_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
        resolution="No",
    )
    m2 = Market(
        id="0xcond2",
        question="Will Congress pass Z?",
        category="political",
        no_token_id="token_2",
        created_at=datetime(2024, 3, 1, tzinfo=timezone.utc),
        resolved_at=datetime(2024, 9, 1, tzinfo=timezone.utc),
        resolution="Yes",
    )
    session.add_all([m1, m2])
    session.flush()

    base1 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    for i, price in enumerate([0.90, 0.85, 0.80, 0.82, 0.88]):
        session.add(PriceSnapshot(
            market_id="0xcond1",
            timestamp=base1 + timedelta(hours=i * 24),
            no_price=price,
            source="api",
        ))

    base2 = datetime(2024, 3, 1, tzinfo=timezone.utc)
    for i, price in enumerate([0.70, 0.65, 0.60, 0.55]):
        session.add(PriceSnapshot(
            market_id="0xcond2",
            timestamp=base2 + timedelta(hours=i * 24),
            no_price=price,
            source="api",
        ))

    session.commit()


def test_run_backtest_at_creation(session):
    _seed_data(session)
    run_id = run_backtest(
        session,
        strategy_name="at_creation",
        params={},
        categories=None,
    )

    results = session.query(BacktestResult).filter_by(run_id=run_id).all()
    assert len(results) == 2

    # Market 1: resolved No, entry at 0.90, exit at 1.00, profit 0.10
    r1 = next(r for r in results if r.market_id == "0xcond1")
    assert r1.entry_price == 0.90
    assert r1.exit_price == 1.0
    assert abs(r1.profit - 0.10) < 0.001

    # Market 2: resolved Yes, entry at 0.70, exit at 0.00, profit -0.70
    r2 = next(r for r in results if r.market_id == "0xcond2")
    assert r2.entry_price == 0.70
    assert r2.exit_price == 0.0
    assert abs(r2.profit - (-0.70)) < 0.001


def test_run_backtest_threshold(session):
    _seed_data(session)
    run_id = run_backtest(
        session,
        strategy_name="threshold",
        params={"threshold": 0.85},
        categories=None,
    )

    results = session.query(BacktestResult).filter_by(run_id=run_id).all()
    assert len(results) == 2

    r1 = next(r for r in results if r.market_id == "0xcond1")
    assert r1.entry_price == 0.85  # First price <= 0.85
    assert r1.strategy == "threshold_0.85"


def test_run_backtest_category_filter(session):
    _seed_data(session)
    run_id = run_backtest(
        session,
        strategy_name="at_creation",
        params={},
        categories=["geopolitical"],
    )

    results = session.query(BacktestResult).filter_by(run_id=run_id).all()
    assert len(results) == 1
    assert results[0].market_id == "0xcond1"


def test_run_backtest_skips_unresolved(session):
    session.add(Market(
        id="0xunresolved",
        question="Unresolved market",
        category="political",
        no_token_id="token_3",
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        resolution=None,
    ))
    session.commit()

    run_id = run_backtest(
        session,
        strategy_name="at_creation",
        params={},
        categories=None,
    )

    results = session.query(BacktestResult).filter_by(run_id=run_id).all()
    assert len(results) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_engine.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write `src/backtester/engine.py`**

```python
import argparse
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.storage.db import get_engine, get_session
from src.storage.models import Market, PriceSnapshot, BacktestResult
from src.backtester.strategies import STRATEGIES


def run_backtest(
    session: Session,
    strategy_name: str,
    params: dict,
    categories: list[str] | None = None,
) -> str:
    """Run a single strategy across all matching markets. Returns the run_id."""
    strategy_info = STRATEGIES[strategy_name]
    strategy_fn = strategy_info["fn"]

    # Build strategy label for storage
    param_suffix = ""
    if params:
        param_suffix = "_" + "_".join(str(v) for v in params.values())
    strategy_label = f"{strategy_name}{param_suffix}"

    run_id = str(uuid.uuid4())[:8]

    # Query resolved markets
    query = select(Market).where(Market.resolution.isnot(None))
    if categories:
        query = query.where(Market.category.in_(categories))

    markets = session.execute(query).scalars().all()

    for market in markets:
        # Get price history as list of dicts
        snapshots = (
            session.query(PriceSnapshot)
            .filter_by(market_id=market.id)
            .order_by(PriceSnapshot.timestamp)
            .all()
        )
        price_history = [
            {"timestamp": s.timestamp, "no_price": s.no_price}
            for s in snapshots
        ]

        if not price_history:
            continue

        # Run strategy
        result = strategy_fn(market.created_at, price_history, **params)
        if result is None:
            continue

        entry_price, entry_timestamp = result
        exit_price = 1.0 if market.resolution == "No" else 0.0
        profit = exit_price - entry_price

        session.add(BacktestResult(
            market_id=market.id,
            strategy=strategy_label,
            entry_price=entry_price,
            entry_timestamp=entry_timestamp,
            exit_price=exit_price,
            profit=profit,
            category=market.category,
            run_id=run_id,
        ))

    session.commit()
    return run_id


def run_all_strategies(
    session: Session,
    categories: list[str] | None = None,
) -> list[str]:
    """Run all strategies with all parameter combinations. Returns list of run_ids."""
    run_ids = []
    for strategy_name, info in STRATEGIES.items():
        for params in info["params"]:
            run_id = run_backtest(session, strategy_name, params, categories)
            run_ids.append(run_id)
    return run_ids


def main():
    parser = argparse.ArgumentParser(description="Run backtests")
    parser.add_argument(
        "--strategy",
        type=str,
        default=None,
        help="Strategy name (at_creation, threshold, snapshot, best_price). Omit to run all.",
    )
    parser.add_argument(
        "--param",
        type=str,
        default=None,
        help="Strategy parameter value (e.g., 0.85 for threshold, 24 for snapshot)",
    )
    parser.add_argument(
        "--categories",
        type=str,
        default=None,
        help="Comma-separated categories to filter",
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

        run_id = run_backtest(session, args.strategy, params, categories)
        print(f"Backtest complete. Run ID: {run_id}")
    else:
        run_ids = run_all_strategies(session, categories)
        print(f"All backtests complete. {len(run_ids)} runs.")

    session.close()
    engine.dispose()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_engine.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/backtester/engine.py tests/test_engine.py
git commit -m "feat: add backtest engine with strategy execution"
```

---

### Task 10: Metrics Aggregation

**Files:**
- Create: `src/backtester/metrics.py`
- Create: `tests/test_metrics.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_metrics.py`:

```python
from datetime import datetime, timezone

from src.storage.models import Market, BacktestResult
from src.backtester.metrics import (
    compute_strategy_metrics,
    compute_category_metrics,
    compute_time_period_metrics,
)


def _seed_results(session):
    """Seed backtest results for metrics testing."""
    # Create markets
    for i in range(1, 5):
        session.add(Market(
            id=f"0xm{i}",
            question=f"Market {i}",
            category="geopolitical" if i <= 2 else "political",
            no_token_id=f"tok_{i}",
            created_at=datetime(2024, i, 1, tzinfo=timezone.utc),
            resolved_at=datetime(2024, i + 3, 1, tzinfo=timezone.utc),
            resolution="No" if i != 3 else "Yes",
        ))
    session.flush()

    # Results for "at_creation" strategy
    results = [
        # Market 1: No win, entry 0.90, profit +0.10
        BacktestResult(
            market_id="0xm1", strategy="at_creation", entry_price=0.90,
            entry_timestamp=datetime(2024, 1, 2, tzinfo=timezone.utc),
            exit_price=1.0, profit=0.10, category="geopolitical", run_id="run1",
        ),
        # Market 2: No win, entry 0.85, profit +0.15
        BacktestResult(
            market_id="0xm2", strategy="at_creation", entry_price=0.85,
            entry_timestamp=datetime(2024, 2, 2, tzinfo=timezone.utc),
            exit_price=1.0, profit=0.15, category="geopolitical", run_id="run1",
        ),
        # Market 3: Yes win (loss), entry 0.80, profit -0.80
        BacktestResult(
            market_id="0xm3", strategy="at_creation", entry_price=0.80,
            entry_timestamp=datetime(2024, 3, 2, tzinfo=timezone.utc),
            exit_price=0.0, profit=-0.80, category="political", run_id="run1",
        ),
        # Market 4: No win, entry 0.88, profit +0.12
        BacktestResult(
            market_id="0xm4", strategy="at_creation", entry_price=0.88,
            entry_timestamp=datetime(2024, 4, 2, tzinfo=timezone.utc),
            exit_price=1.0, profit=0.12, category="political", run_id="run1",
        ),
    ]
    session.add_all(results)
    session.commit()


def test_strategy_metrics(session):
    _seed_results(session)
    metrics = compute_strategy_metrics(session, run_id="run1")
    assert len(metrics) == 1  # One strategy

    m = metrics[0]
    assert m["strategy"] == "at_creation"
    assert m["trade_count"] == 4
    assert m["win_count"] == 3
    assert abs(m["win_rate"] - 0.75) < 0.001
    assert abs(m["total_pnl"] - (-0.43)) < 0.01
    assert abs(m["avg_ev"] - (-0.1075)) < 0.001


def test_category_metrics(session):
    _seed_results(session)
    metrics = compute_category_metrics(session, run_id="run1")

    geo = next(m for m in metrics if m["category"] == "geopolitical")
    assert geo["trade_count"] == 2
    assert geo["win_count"] == 2
    assert abs(geo["win_rate"] - 1.0) < 0.001
    assert abs(geo["total_pnl"] - 0.25) < 0.01

    pol = next(m for m in metrics if m["category"] == "political")
    assert pol["trade_count"] == 2
    assert pol["win_count"] == 1
    assert abs(pol["win_rate"] - 0.5) < 0.001


def test_time_period_metrics(session):
    _seed_results(session)
    metrics = compute_time_period_metrics(session, run_id="run1")
    # All trades are in 2024, so we should have one year
    assert len(metrics) == 1
    assert metrics[0]["year"] == 2024
    assert metrics[0]["trade_count"] == 4
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_metrics.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write `src/backtester/metrics.py`**

```python
import statistics

from sqlalchemy import func, extract
from sqlalchemy.orm import Session

from src.storage.models import BacktestResult


def compute_strategy_metrics(session: Session, run_id: str) -> list[dict]:
    """Compute metrics grouped by strategy for a given run."""
    strategies = (
        session.query(BacktestResult.strategy)
        .filter_by(run_id=run_id)
        .distinct()
        .all()
    )

    metrics = []
    for (strategy,) in strategies:
        results = (
            session.query(BacktestResult)
            .filter_by(run_id=run_id, strategy=strategy)
            .all()
        )
        metrics.append(_compute_group_metrics(results, {"strategy": strategy}))
    return metrics


def compute_category_metrics(session: Session, run_id: str) -> list[dict]:
    """Compute metrics grouped by category for a given run."""
    categories = (
        session.query(BacktestResult.category)
        .filter_by(run_id=run_id)
        .distinct()
        .all()
    )

    metrics = []
    for (category,) in categories:
        results = (
            session.query(BacktestResult)
            .filter_by(run_id=run_id, category=category)
            .all()
        )
        metrics.append(_compute_group_metrics(results, {"category": category}))
    return metrics


def compute_time_period_metrics(session: Session, run_id: str) -> list[dict]:
    """Compute metrics grouped by year of entry."""
    years = (
        session.query(extract("year", BacktestResult.entry_timestamp).label("year"))
        .filter_by(run_id=run_id)
        .distinct()
        .all()
    )

    metrics = []
    for (year,) in years:
        results = (
            session.query(BacktestResult)
            .filter(
                BacktestResult.run_id == run_id,
                extract("year", BacktestResult.entry_timestamp) == year,
            )
            .all()
        )
        metrics.append(_compute_group_metrics(results, {"year": int(year)}))
    return metrics


def _compute_group_metrics(results: list[BacktestResult], group_info: dict) -> dict:
    """Compute metrics for a group of backtest results."""
    profits = [r.profit for r in results]
    trade_count = len(results)
    win_count = sum(1 for r in results if r.profit > 0)
    total_pnl = sum(profits)
    avg_ev = total_pnl / trade_count if trade_count > 0 else 0.0
    win_rate = win_count / trade_count if trade_count > 0 else 0.0

    sharpe = 0.0
    if len(profits) > 1:
        std = statistics.stdev(profits)
        if std > 0:
            sharpe = avg_ev / std

    return {
        **group_info,
        "trade_count": trade_count,
        "win_count": win_count,
        "win_rate": win_rate,
        "total_pnl": total_pnl,
        "avg_ev": avg_ev,
        "sharpe": sharpe,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_metrics.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/backtester/metrics.py tests/test_metrics.py
git commit -m "feat: add metrics aggregation by strategy, category, and time"
```

---

### Task 11: Dashboard

**Files:**
- Create: `src/dashboard/app.py`

- [ ] **Step 1: Write the Streamlit dashboard**

Create `src/dashboard/app.py`:

```python
import subprocess
import sys

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from sqlalchemy import func, extract
from sqlalchemy.orm import Session

from src.storage.db import get_engine, get_session
from src.storage.models import Market, PriceSnapshot, BacktestResult
from src.backtester.engine import run_all_strategies
from src.backtester.metrics import (
    compute_strategy_metrics,
    compute_category_metrics,
    compute_time_period_metrics,
)

st.set_page_config(page_title="Polymarket Backtester", layout="wide")


@st.cache_resource
def init_db():
    engine = get_engine()
    return engine


def get_db_session():
    engine = init_db()
    return get_session(engine)


# ---- Sidebar ----

st.sidebar.title("Nothing Ever Happens")
st.sidebar.markdown("*Polymarket Backtester*")

session = get_db_session()

# Category filter
all_categories = [
    row[0]
    for row in session.query(Market.category).distinct().all()
    if row[0]
]
selected_categories = st.sidebar.multiselect(
    "Categories", all_categories, default=all_categories
)

# Date range
min_date = session.query(func.min(Market.created_at)).scalar()
max_date = session.query(func.max(Market.created_at)).scalar()
if min_date and max_date:
    date_range = st.sidebar.date_input(
        "Date range",
        value=(min_date.date(), max_date.date()),
        min_value=min_date.date(),
        max_value=max_date.date(),
    )
else:
    date_range = None

# Strategy filter
all_strategies = [
    row[0]
    for row in session.query(BacktestResult.strategy).distinct().all()
]
selected_strategies = st.sidebar.multiselect(
    "Strategies", all_strategies, default=all_strategies
)

# Run backtest button
if st.sidebar.button("Run All Backtests"):
    with st.spinner("Running backtests..."):
        run_all_strategies(session, categories=selected_categories or None)
    st.sidebar.success("Done!")
    st.rerun()

# Latest run_id
latest_run_id = (
    session.query(BacktestResult.run_id)
    .order_by(BacktestResult.id.desc())
    .limit(1)
    .scalar()
)

# ---- Navigation ----

view = st.sidebar.radio(
    "View", ["Thesis Overview", "Strategy Comparison", "Deep Dive", "Market Browser"]
)


# ---- View: Thesis Overview ----

def render_thesis_overview():
    st.header("Thesis Overview: Does Nothing Ever Happen?")

    total_markets = (
        session.query(Market)
        .filter(Market.resolution.isnot(None))
        .filter(Market.category.in_(selected_categories))
        .count()
    )
    no_count = (
        session.query(Market)
        .filter(Market.resolution == "No")
        .filter(Market.category.in_(selected_categories))
        .count()
    )
    yes_count = total_markets - no_count
    no_rate = no_count / total_markets if total_markets > 0 else 0

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Resolved Markets", total_markets)
    col2.metric("Resolved No", no_count)
    col3.metric("Resolved Yes", yes_count)
    col4.metric("No Resolution Rate", f"{no_rate:.1%}")

    # Category breakdown
    cat_data = []
    for cat in selected_categories:
        cat_total = session.query(Market).filter(
            Market.resolution.isnot(None), Market.category == cat
        ).count()
        cat_no = session.query(Market).filter(
            Market.resolution == "No", Market.category == cat
        ).count()
        if cat_total > 0:
            cat_data.append({
                "Category": cat,
                "No Rate": cat_no / cat_total,
                "Total": cat_total,
            })

    if cat_data:
        df = pd.DataFrame(cat_data)
        fig = px.bar(
            df, x="Category", y="No Rate", text="Total",
            title="No-Resolution Rate by Category",
            color="No Rate",
            color_continuous_scale=["red", "yellow", "green"],
            range_color=[0, 1],
        )
        fig.update_traces(textposition="outside")
        fig.update_yaxes(range=[0, 1], tickformat=".0%")
        st.plotly_chart(fig, use_container_width=True)


# ---- View: Strategy Comparison ----

def render_strategy_comparison():
    st.header("Strategy Comparison")

    if not latest_run_id:
        st.warning("No backtest results found. Run a backtest first.")
        return

    # Get all run_ids and their strategies
    all_results = (
        session.query(BacktestResult)
        .filter(BacktestResult.strategy.in_(selected_strategies))
        .filter(BacktestResult.category.in_(selected_categories))
        .all()
    )

    if not all_results:
        st.info("No results match your filters.")
        return

    # Group by strategy
    strategy_groups: dict[str, list] = {}
    for r in all_results:
        strategy_groups.setdefault(r.strategy, []).append(r)

    rows = []
    for strategy, results in sorted(strategy_groups.items()):
        profits = [r.profit for r in results]
        wins = sum(1 for p in profits if p > 0)
        total = len(profits)
        rows.append({
            "Strategy": strategy,
            "Trades": total,
            "Win Rate": f"{wins/total:.1%}" if total else "N/A",
            "Avg EV": f"${sum(profits)/total:.4f}" if total else "N/A",
            "Total P&L": f"${sum(profits):.2f}",
            "Sharpe": f"{(sum(profits)/total) / (pd.Series(profits).std() or 1):.2f}" if total > 1 else "N/A",
            "_avg_ev": sum(profits) / total if total else 0,
        })

    df = pd.DataFrame(rows)

    # Color rows by EV
    def highlight_ev(row):
        ev = row["_avg_ev"]
        if ev > 0:
            return ["background-color: #d4edda"] * len(row)
        elif ev < 0:
            return ["background-color: #f8d7da"] * len(row)
        return [""] * len(row)

    display_df = df.drop(columns=["_avg_ev"])
    styled = display_df.style.apply(
        lambda row: highlight_ev(df.iloc[row.name]), axis=1
    )
    st.dataframe(styled, use_container_width=True, hide_index=True)


# ---- View: Deep Dive Explorer ----

def render_deep_dive():
    st.header("Deep Dive Explorer")

    if not latest_run_id:
        st.warning("No backtest results found. Run a backtest first.")
        return

    results = (
        session.query(BacktestResult)
        .filter(BacktestResult.strategy.in_(selected_strategies))
        .filter(BacktestResult.category.in_(selected_categories))
        .all()
    )

    if not results:
        st.info("No results match your filters.")
        return

    df = pd.DataFrame([{
        "entry_price": r.entry_price,
        "profit": r.profit,
        "category": r.category,
        "strategy": r.strategy,
        "entry_timestamp": r.entry_timestamp,
    } for r in results])

    # Scatter plot: entry price vs profit
    fig_scatter = px.scatter(
        df, x="entry_price", y="profit", color="category",
        title="Entry Price vs Profit",
        labels={"entry_price": "No Entry Price", "profit": "Profit per Share"},
        hover_data=["strategy"],
    )
    fig_scatter.add_hline(y=0, line_dash="dash", line_color="gray")
    st.plotly_chart(fig_scatter, use_container_width=True)

    # Cumulative P&L curve
    strategy_for_curve = st.selectbox(
        "P&L Curve Strategy", sorted(df["strategy"].unique())
    )
    curve_df = df[df["strategy"] == strategy_for_curve].sort_values("entry_timestamp")
    curve_df["cumulative_pnl"] = curve_df["profit"].cumsum()

    fig_pnl = px.line(
        curve_df, x="entry_timestamp", y="cumulative_pnl",
        title=f"Cumulative P&L — {strategy_for_curve}",
        labels={"entry_timestamp": "Date", "cumulative_pnl": "Cumulative P&L ($)"},
    )
    fig_pnl.add_hline(y=0, line_dash="dash", line_color="gray")
    st.plotly_chart(fig_pnl, use_container_width=True)

    # Entry price histogram
    fig_hist = px.histogram(
        df, x="entry_price", nbins=30, color="category",
        title="Distribution of No Entry Prices",
        labels={"entry_price": "No Token Price at Entry"},
    )
    st.plotly_chart(fig_hist, use_container_width=True)


# ---- View: Market Browser ----

def render_market_browser():
    st.header("Market Browser")

    search = st.text_input("Search markets", "")

    query = session.query(Market).filter(
        Market.resolution.isnot(None),
        Market.category.in_(selected_categories),
    )
    if search:
        query = query.filter(Market.question.contains(search))

    markets = query.order_by(Market.created_at.desc()).limit(200).all()

    if not markets:
        st.info("No markets found.")
        return

    market_data = [{
        "Question": m.question[:80],
        "Category": m.category,
        "Resolution": m.resolution,
        "Created": m.created_at.strftime("%Y-%m-%d") if m.created_at else "",
        "Resolved": m.resolved_at.strftime("%Y-%m-%d") if m.resolved_at else "",
        "id": m.id,
    } for m in markets]

    df = pd.DataFrame(market_data)
    display_df = df.drop(columns=["id"])

    st.dataframe(display_df, use_container_width=True, hide_index=True)

    # Market detail expander
    selected_q = st.selectbox(
        "Select market for detail view",
        [m.question[:80] for m in markets],
    )
    selected_market = next(
        (m for m in markets if m.question[:80] == selected_q), None
    )

    if selected_market:
        with st.expander(f"Detail: {selected_market.question[:60]}...", expanded=True):
            st.markdown(f"**Resolution:** {selected_market.resolution}")
            st.markdown(f"**Category:** {selected_market.category}")
            if selected_market.source_url:
                st.markdown(f"[View on Polymarket]({selected_market.source_url})")

            # Price history chart
            snapshots = (
                session.query(PriceSnapshot)
                .filter_by(market_id=selected_market.id)
                .order_by(PriceSnapshot.timestamp)
                .all()
            )
            if snapshots:
                price_df = pd.DataFrame([{
                    "Date": s.timestamp,
                    "No Price": s.no_price,
                    "Source": s.source,
                } for s in snapshots])

                fig = px.line(
                    price_df, x="Date", y="No Price",
                    title="No Token Price History",
                    color="Source",
                )
                fig.update_yaxes(range=[0, 1])
                st.plotly_chart(fig, use_container_width=True)

            # Strategy results for this market
            market_results = (
                session.query(BacktestResult)
                .filter_by(market_id=selected_market.id)
                .all()
            )
            if market_results:
                st.markdown("**Strategy Results:**")
                result_data = [{
                    "Strategy": r.strategy,
                    "Entry Price": f"${r.entry_price:.4f}",
                    "Exit Price": f"${r.exit_price:.2f}",
                    "Profit": f"${r.profit:+.4f}",
                } for r in market_results]
                st.dataframe(pd.DataFrame(result_data), hide_index=True)


# ---- Render selected view ----

if view == "Thesis Overview":
    render_thesis_overview()
elif view == "Strategy Comparison":
    render_strategy_comparison()
elif view == "Deep Dive":
    render_deep_dive()
elif view == "Market Browser":
    render_market_browser()

session.close()
```

- [ ] **Step 2: Run the dashboard**

Run: `streamlit run src/dashboard/app.py`

Verify:
- App loads without errors
- Sidebar shows category/strategy filters
- "Run All Backtests" button is visible
- Each view renders (may show "no data" messages if DB is empty — that's correct)

- [ ] **Step 3: Commit**

```bash
git add src/dashboard/app.py
git commit -m "feat: add Streamlit dashboard with all four views"
```

---

### Task 12: End-to-End Verification

- [ ] **Step 1: Run full test suite**

Run: `pytest tests/ -v`
Expected: All tests pass (27 tests total across 7 test files)

- [ ] **Step 2: Test collection with a small batch**

Run: `python -m src.collector.runner --categories geopolitical,political,culture --limit 10`

Verify: Output shows fetching markets and storing data. Check that `data/polymarket.db` is created.

- [ ] **Step 3: Run backtests on collected data**

Run: `python -m src.backtester.engine`

Verify: Output shows backtest runs completing.

- [ ] **Step 4: Launch dashboard and verify with real data**

Run: `streamlit run src/dashboard/app.py`

Verify:
- Thesis Overview shows resolution stats and category bar chart
- Strategy Comparison shows a table with metrics for each strategy
- Deep Dive shows scatter plot, P&L curve, and histogram
- Market Browser shows searchable table with expandable details

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "chore: end-to-end verification complete"
```
