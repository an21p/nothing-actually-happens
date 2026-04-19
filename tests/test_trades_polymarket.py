from datetime import datetime, timezone

import pytest

from src.collector.trades.polymarket import event_to_trade

YES_ID = "1111"
NO_ID = "2222"
TS = 1704153600  # 2024-01-02 00:00:00 UTC
EXPECTED_DT = datetime.fromtimestamp(TS, tz=timezone.utc)


def _event(args: dict, tx="0xabcd", log_idx=0, block=50_000_000):
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
    assert trade["tx_hash"] == "0xabcd"
    assert trade["order_hash"] == "0x" + "01" * 32
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


def test_event_to_trade_raises_when_no_usdc_leg():
    ev = _event({
        "orderHash": b"\x07" * 32,
        "maker": "0xM", "taker": "0xT",
        "makerAssetId": int(YES_ID), "takerAssetId": int(NO_ID),  # both non-USDC
        "makerAmountFilled": 1_000_000, "takerAmountFilled": 1_000_000,
        "fee": 0,
    })
    with pytest.raises(ValueError, match="without USDC leg"):
        event_to_trade(ev, YES_ID, NO_ID, "0xm1", TS)


def test_event_to_trade_raises_when_asset_neither_yes_nor_no():
    ev = _event({
        "orderHash": b"\x08" * 32,
        "maker": "0xM", "taker": "0xT",
        "makerAssetId": 0, "takerAssetId": 999_999,  # unknown outcome token
        "makerAmountFilled": 500_000, "takerAmountFilled": 1_000_000,
        "fee": 0,
    })
    with pytest.raises(ValueError, match="matches neither YES nor NO"):
        event_to_trade(ev, YES_ID, NO_ID, "0xm1", TS)
