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
    if raw.get("negRisk"):
        return None

    outcomes = json.loads(raw["outcomes"])
    prices = json.loads(raw["outcomePrices"])
    clob_token_ids = json.loads(raw["clobTokenIds"])

    if len(outcomes) != 2:
        return None

    # Only accept Yes/No binary markets (skip eSports, team-name markets, etc.)
    outcome_set = {o.lower() for o in outcomes}
    if outcome_set != {"yes", "no"}:
        return None

    resolution = determine_resolution(outcomes, prices)

    try:
        no_idx = outcomes.index("No")
    except ValueError:
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
        time.sleep(0.05)

    client.close()
    return all_markets
