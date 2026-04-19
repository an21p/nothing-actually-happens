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


from types import SimpleNamespace


class _FakeContractEvent:
    def __init__(self, logs_per_chunk):
        self._chunks = iter(logs_per_chunk)

    def get_logs(self, fromBlock, toBlock):  # noqa: N803
        try:
            return next(self._chunks)
        except StopIteration:
            return []


class _FakeContractEvents:
    def __init__(self, logs_per_chunk):
        self.OrderFilled = _FakeContractEvent(logs_per_chunk)


class _FakeContract:
    def __init__(self, logs_per_chunk):
        self.events = _FakeContractEvents(logs_per_chunk)


class _FakeEth:
    def __init__(self, logs_per_chunk, block_timestamps, latest_block):
        self._contract = _FakeContract(logs_per_chunk)
        self.block_number = latest_block
        self._ts = block_timestamps

    def contract(self, address=None, abi=None):
        return self._contract

    def get_block(self, n):
        return {"timestamp": self._ts.get(n, 1704153600)}


class _FakeWeb3:
    def __init__(self, logs_per_chunk, block_timestamps=None, latest=60_000_000, connected=True):
        self.eth = _FakeEth(logs_per_chunk, block_timestamps or {}, latest)
        self._connected = connected

    def is_connected(self):
        return self._connected


def _sample_event(maker_asset, taker_asset, maker_amt, taker_amt, block=50_000_000, log_idx=0, tx="0xaa"):
    return {
        "args": {
            "orderHash": b"\x01" * 32,
            "maker": "0xMAKER",
            "taker": "0xTAKER",
            "makerAssetId": maker_asset,
            "takerAssetId": taker_asset,
            "makerAmountFilled": maker_amt,
            "takerAmountFilled": taker_amt,
            "fee": 0,
        },
        "transactionHash": bytes.fromhex(tx[2:] + "00" * (32 - len(tx[2:]) // 2)),
        "logIndex": log_idx,
        "blockNumber": block,
    }


def test_fetch_trades_yields_mapped_trades(session):
    from src.collector.trades.polymarket import fetch_trades
    from src.storage.models import Market

    market = Market(
        id="0xmarket",
        question="q",
        category="political",
        no_token_id=NO_ID,
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        resolved_at=datetime(2024, 1, 2, tzinfo=timezone.utc),
    )
    session.add(market); session.commit()

    ev = _sample_event(0, int(NO_ID), 150_000, 1_000_000, block=50_000_010)
    fake = _FakeWeb3(
        logs_per_chunk=[[ev]],
        block_timestamps={50_000_010: 1704153600},
        latest=50_000_020,
    )

    trades = list(fetch_trades(
        market, yes_token_id=YES_ID, no_token_id=NO_ID,
        from_block=50_000_000, to_block=50_000_020,
        w3=fake,
    ))
    assert len(trades) == 1
    assert trades[0]["market_id"] == "0xmarket"
    assert trades[0]["side"] == "sell_no"


def test_fetch_trades_returns_empty_when_disconnected(session):
    from src.collector.trades.polymarket import fetch_trades
    from src.storage.models import Market

    market = Market(
        id="0xmarket",
        question="q",
        category="political",
        no_token_id=NO_ID,
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        resolved_at=datetime(2024, 1, 2, tzinfo=timezone.utc),
    )
    session.add(market); session.commit()

    fake = _FakeWeb3(logs_per_chunk=[], connected=False)
    trades = list(fetch_trades(
        market, yes_token_id=YES_ID, no_token_id=NO_ID,
        from_block=50_000_000, to_block=50_000_020,
        w3=fake,
    ))
    assert trades == []


def test_fetch_trades_filters_unrelated_asset(session):
    from src.collector.trades.polymarket import fetch_trades
    from src.storage.models import Market

    market = Market(
        id="0xmarket", question="q", category="political",
        no_token_id=NO_ID,
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        resolved_at=datetime(2024, 1, 2, tzinfo=timezone.utc),
    )
    session.add(market); session.commit()

    unrelated = _sample_event(0, 999_999_999, 500_000, 1_000_000, block=50_000_011)
    fake = _FakeWeb3(
        logs_per_chunk=[[unrelated]],
        block_timestamps={50_000_011: 1704153600},
        latest=50_000_020,
    )
    trades = list(fetch_trades(
        market, yes_token_id=YES_ID, no_token_id=NO_ID,
        from_block=50_000_000, to_block=50_000_020,
        w3=fake,
    ))
    assert trades == []
