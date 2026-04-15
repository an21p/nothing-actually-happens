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
    client = httpx.Client(timeout=30)
    params = {
        "market": token_id,
        "interval": "max",
        "fidelity": 60,
    }
    response = client.get(f"{CLOB_API_BASE}/prices-history", params=params)
    response.raise_for_status()
    snapshots = parse_price_history(response.json(), market_id)
    client.close()
    return snapshots


def fetch_price_histories_batch(
    token_market_pairs: list[tuple[str, str]],
) -> dict[str, list[dict]]:
    result = {}
    for token_id, market_id in token_market_pairs:
        try:
            snapshots = fetch_price_history(token_id, market_id)
            result[market_id] = snapshots
        except httpx.HTTPStatusError:
            result[market_id] = []
        time.sleep(0.02)
    return result
