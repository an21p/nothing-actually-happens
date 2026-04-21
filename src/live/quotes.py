"""Live price quotes from the Polymarket CLOB.

Used for paper-trade entry pricing and mark-to-market on open positions.
Paper trades pay no slippage: we just read the midpoint as fair value.
"""

from __future__ import annotations

import logging
import time

import httpx

logger = logging.getLogger(__name__)

CLOB_API_BASE = "https://clob.polymarket.com"
_HTTP_TIMEOUT = 10.0


def fetch_midpoint(token_id: str) -> float | None:
    with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
        response = client.get(
            f"{CLOB_API_BASE}/midpoint", params={"token_id": token_id}
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        data = response.json()
        mid = data.get("mid")
        return float(mid) if mid is not None else None


def fetch_midpoints_batch(token_ids: list[str]) -> dict[str, float]:
    if not token_ids:
        return {}
    payload = [{"token_id": tid} for tid in token_ids]
    logger.info("quotes.batch: posting %d token_ids", len(token_ids))
    t0 = time.perf_counter()
    with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
        response = client.post(f"{CLOB_API_BASE}/midpoints", json=payload)
        if response.status_code == 404:
            logger.warning("quotes.batch: /midpoints returned 404")
            return {}
        response.raise_for_status()
        data = response.json()
    out: dict[str, float] = {}
    # Response is `{"token_id": "mid", ...}` — handle list-of-dicts too.
    if isinstance(data, dict):
        iterable = data.items()
    elif isinstance(data, list):
        iterable = (
            (row.get("token_id"), row.get("mid"))
            for row in data
            if isinstance(row, dict)
        )
    else:
        logger.warning("quotes.batch: unexpected response shape: %r", type(data))
        return {}
    for tid, mid in iterable:
        if tid is None or mid is None:
            continue
        try:
            out[tid] = float(mid)
        except (TypeError, ValueError):
            continue
    elapsed = time.perf_counter() - t0
    logger.info(
        "quotes.batch: %d/%d midpoints resolved in %.2fs",
        len(out), len(token_ids), elapsed,
    )
    return out
