import os
import time
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

CTF_EXCHANGE_ADDRESS = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"

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
BLOCK_CHUNK = 10_000
POLYGON_BLOCK_TIME_SECS = 2


def compute_price_from_event(args: dict) -> float:
    maker_asset = args["makerAssetId"]
    taker_asset = args["takerAssetId"]
    maker_amount = args["makerAmountFilled"]
    taker_amount = args["takerAmountFilled"]

    if maker_asset == 0:
        return maker_amount / taker_amount
    elif taker_asset == 0:
        return taker_amount / maker_amount
    else:
        return -1.0


def filter_events_for_token(events: list[dict], token_id: int) -> list[dict]:
    return [
        e for e in events
        if e["args"]["makerAssetId"] == token_id
        or e["args"]["takerAssetId"] == token_id
    ]


def estimate_block_for_timestamp(target_ts: float, latest_block_num: int, latest_block_ts: float) -> int:
    diff_secs = latest_block_ts - target_ts
    diff_blocks = int(diff_secs / POLYGON_BLOCK_TIME_SECS)
    return max(0, latest_block_num - diff_blocks)


def fetch_onchain_prices(
    no_token_id: str,
    market_id: str,
    created_at: datetime,
    resolved_at: datetime | None,
) -> list[dict]:
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

    start_block = estimate_block_for_timestamp(created_at.timestamp(), latest_block, latest_ts)
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

        time.sleep(0.1)

    snapshots.sort(key=lambda s: s["timestamp"])
    return snapshots
