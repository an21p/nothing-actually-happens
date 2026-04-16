import json
import time
from datetime import datetime, timezone

import httpx

from src.collector.categories import classify_market

GAMMA_API_BASE = "https://gamma-api.polymarket.com"
MARKETS_PER_PAGE = 1000


def determine_resolution(outcomes: list[str], prices: list[str]) -> str | None:
    float_prices = [float(p) for p in prices]
    for i, price in enumerate(float_prices):
        if price > 0.9:
            return outcomes[i]
    return None


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00").replace(" ", "T"))
    except ValueError:
        return None


def _parse_market_common(raw: dict) -> dict | None:
    """Shared parsing for resolved and open Yes/No binary markets.

    Returns the common fields (no resolution/resolved_at) or None if the
    market is a negRisk / multi-outcome / non-Yes-No market. Callers
    layer resolution-specific fields on top.
    """
    if raw.get("negRisk"):
        return None

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

    category = classify_market(raw["question"], raw.get("category"))
    slug = raw.get("slug", "")

    return {
        "id": raw["conditionId"],
        "question": raw["question"],
        "category": category,
        "no_token_id": no_token_id,
        "created_at": created_at,
        "end_date": end_date,
        "source_url": f"https://polymarket.com/event/{slug}" if slug else None,
        # raw outcomes/prices retained so resolution-aware callers can use them
        "_outcomes": outcomes,
        "_prices": prices,
    }


def parse_market(raw: dict) -> dict | None:
    """Parse a closed & resolved market. Returns None unless the market has a clear resolution."""
    common = _parse_market_common(raw)
    if common is None:
        return None

    resolution = determine_resolution(common["_outcomes"], common["_prices"])
    if resolution is None:
        return None

    resolved_at = _parse_datetime(raw.get("closedTime"))

    common.pop("_outcomes", None)
    common.pop("_prices", None)
    common["resolution"] = resolution
    common["resolved_at"] = resolved_at
    return common


def parse_open_market(raw: dict) -> dict | None:
    """Parse an open/active market. Resolution is None; resolved_at is None."""
    common = _parse_market_common(raw)
    if common is None:
        return None

    common.pop("_outcomes", None)
    common.pop("_prices", None)
    common["resolution"] = None
    common["resolved_at"] = None
    return common


def fetch_resolved_markets(
    categories: list[str] | None = None,
    limit: int | None = None,
    end_date_max: str | None = None,
) -> list[dict]:
    """Fetch resolved markets from the Gamma API with pagination.

    If end_date_max is provided, only fetches markets with endDate <= that value.
    Use this to continue collecting older markets from where the last run left off.
    """
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
        if end_date_max:
            params["end_date_max"] = end_date_max

        response = client.get(f"{GAMMA_API_BASE}/markets", params=params)
        if response.status_code == 422:
            print(f"  API rejected offset={offset}, stopping pagination")
            break
        response.raise_for_status()
        raw_markets = response.json()

        if isinstance(raw_markets, dict):
            raw_markets = raw_markets.get("data", [])

        if not raw_markets:
            break

        page_num = offset // MARKETS_PER_PAGE + 1
        accepted = 0
        for raw in raw_markets:
            parsed = parse_market(raw)
            if parsed is None:
                continue
            if categories and parsed["category"] not in categories:
                continue
            accepted += 1
            all_markets.append(parsed)

            if limit and len(all_markets) >= limit:
                client.close()
                return all_markets[:limit]

        print(f"  Page {page_num}: {len(raw_markets)} raw, {accepted} accepted, {len(all_markets)} total")
        offset += MARKETS_PER_PAGE
        time.sleep(0.05)

    client.close()
    return all_markets
