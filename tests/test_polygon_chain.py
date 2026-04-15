from src.collector.polygon_chain import compute_price_from_event, filter_events_for_token

SAMPLE_ORDER_FILLED_EVENT = {
    "args": {
        "orderHash": b"\x01" * 32,
        "maker": "0xMakerAddress",
        "taker": "0xTakerAddress",
        "makerAssetId": 0,
        "takerAssetId": 52791640887,
        "makerAmountFilled": 850000,
        "takerAmountFilled": 1000000,
        "fee": 0,
    },
    "blockNumber": 50000000,
}

SAMPLE_SELL_EVENT = {
    "args": {
        "orderHash": b"\x02" * 32,
        "maker": "0xSellerAddress",
        "taker": "0xBuyerAddress",
        "makerAssetId": 52791640887,
        "takerAssetId": 0,
        "makerAmountFilled": 1000000,
        "takerAmountFilled": 900000,
        "fee": 0,
    },
    "blockNumber": 50000100,
}

UNRELATED_EVENT = {
    "args": {
        "orderHash": b"\x03" * 32,
        "maker": "0xOther",
        "taker": "0xOther2",
        "makerAssetId": 0,
        "takerAssetId": 99999999,
        "makerAmountFilled": 500000,
        "takerAmountFilled": 1000000,
        "fee": 0,
    },
    "blockNumber": 50000200,
}

def test_compute_price_buyer_side():
    price = compute_price_from_event(SAMPLE_ORDER_FILLED_EVENT["args"])
    assert price == 0.85

def test_compute_price_seller_side():
    price = compute_price_from_event(SAMPLE_SELL_EVENT["args"])
    assert price == 0.90

def test_filter_events_for_token():
    events = [SAMPLE_ORDER_FILLED_EVENT, SAMPLE_SELL_EVENT, UNRELATED_EVENT]
    filtered = filter_events_for_token(events, token_id=52791640887)
    assert len(filtered) == 2

def test_filter_events_excludes_unrelated():
    events = [UNRELATED_EVENT]
    filtered = filter_events_for_token(events, token_id=52791640887)
    assert len(filtered) == 0
