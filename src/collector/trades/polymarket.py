"""Polymarket on-chain trade collector.

Reuses the CTF Exchange ABI and block-estimation helpers from
src/collector/polygon_chain.py. Produces per-fill Trade dicts suitable for
insertion into the `trades` table.
"""
import httpx
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Iterator

from src.collector.polygon_chain import (
    ORDER_FILLED_ABI,
    CTF_EXCHANGE_ADDRESS,
    estimate_block_for_timestamp,
)

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
