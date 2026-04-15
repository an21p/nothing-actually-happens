from datetime import datetime, timezone

from src.collector.price_history import parse_price_history

SAMPLE_CLOB_RESPONSE = {
    "history": [
        {"t": 1704067200, "p": 0.92},
        {"t": 1704153600, "p": 0.88},
        {"t": 1704240000, "p": 0.85},
        {"t": 1704326400, "p": 0.83},
        {"t": 1704412800, "p": 0.90},
    ]
}

EMPTY_RESPONSE = {"history": []}

def test_parse_price_history():
    snapshots = parse_price_history(SAMPLE_CLOB_RESPONSE, market_id="0xabc")
    assert len(snapshots) == 5
    assert snapshots[0]["no_price"] == 0.92
    assert snapshots[0]["source"] == "api"
    assert snapshots[0]["market_id"] == "0xabc"
    assert isinstance(snapshots[0]["timestamp"], datetime)

def test_parse_price_history_timestamps():
    snapshots = parse_price_history(SAMPLE_CLOB_RESPONSE, market_id="0xabc")
    assert snapshots[0]["timestamp"] == datetime(2024, 1, 1, tzinfo=timezone.utc)

def test_parse_price_history_sorted_by_time():
    snapshots = parse_price_history(SAMPLE_CLOB_RESPONSE, market_id="0xabc")
    timestamps = [s["timestamp"] for s in snapshots]
    assert timestamps == sorted(timestamps)

def test_parse_empty_history():
    snapshots = parse_price_history(EMPTY_RESPONSE, market_id="0xabc")
    assert snapshots == []
