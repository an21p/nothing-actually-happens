"""Fetch currently open (active & unresolved) markets from Gamma."""

from __future__ import annotations

import time

import httpx

from src.collector.polymarket_api import (
    GAMMA_API_BASE,
    MARKETS_PER_PAGE,
    parse_open_market,
)


def fetch_open_markets(
    categories: list[str] | None = None,
    limit: int | None = None,
) -> list[dict]:
    """List open (active, unresolved, non-archived) Yes/No markets from Gamma."""
    client = httpx.Client(timeout=30)
    all_markets: list[dict] = []
    offset = 0

    while True:
        params = {
            "closed": "false",
            "active": "true",
            "archived": "false",
            "limit": MARKETS_PER_PAGE,
            "offset": offset,
            "order": "createdAt",
            "ascending": "false",
        }
        response = client.get(f"{GAMMA_API_BASE}/markets", params=params)
        if response.status_code == 422:
            break
        response.raise_for_status()
        raw_markets = response.json()
        if isinstance(raw_markets, dict):
            raw_markets = raw_markets.get("data", [])
        if not raw_markets:
            break

        for raw in raw_markets:
            parsed = parse_open_market(raw)
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
