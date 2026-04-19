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
