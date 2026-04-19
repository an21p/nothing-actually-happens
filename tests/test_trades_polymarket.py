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


import httpx
import json as _json


def test_fetch_yes_token_id_happy_path(monkeypatch):
    from src.collector.trades.polymarket import fetch_yes_token_id

    fake_payload = {
        "outcomes": _json.dumps(["Yes", "No"]),
        "clobTokenIds": _json.dumps(["111", "222"]),
    }

    class FakeResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return fake_payload

    def fake_get(url, timeout=None):
        assert url.endswith("/markets/0xmarket")
        return FakeResp()

    monkeypatch.setattr(httpx, "get", fake_get)
    assert fetch_yes_token_id("0xmarket") == "111"


def test_fetch_yes_token_id_no_first(monkeypatch):
    from src.collector.trades.polymarket import fetch_yes_token_id

    fake_payload = {
        "outcomes": _json.dumps(["No", "Yes"]),
        "clobTokenIds": _json.dumps(["222", "111"]),
    }

    class FakeResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return fake_payload

    monkeypatch.setattr(httpx, "get", lambda url, timeout=None: FakeResp())
    assert fetch_yes_token_id("0xmarket") == "111"


def test_fetch_yes_token_id_returns_none_on_malformed(monkeypatch):
    from src.collector.trades.polymarket import fetch_yes_token_id

    class FakeResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"outcomes": "not-json"}

    monkeypatch.setattr(httpx, "get", lambda url, timeout=None: FakeResp())
    assert fetch_yes_token_id("0xbad") is None


def test_fetch_yes_token_id_returns_none_on_http_error(monkeypatch):
    from src.collector.trades.polymarket import fetch_yes_token_id

    def fake_get(url, timeout=None):
        raise httpx.ConnectError("no network")

    monkeypatch.setattr(httpx, "get", fake_get)
    assert fetch_yes_token_id("0xmarket") is None
