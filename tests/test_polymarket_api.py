import json
from datetime import datetime, timezone

from src.collector.polymarket_api import parse_market, determine_resolution

SAMPLE_GAMMA_MARKET = {
    "id": "1237864",
    "conditionId": "0xa6d544beef271a4e941e55897ee14396c2c3b656a44aba63c8de5854e919eaa6",
    "slug": "will-russia-invade-finland-2025",
    "question": "Will Russia invade Finland by 2025?",
    "outcomes": json.dumps(["Yes", "No"]),
    "outcomePrices": json.dumps(["0", "1"]),
    "clobTokenIds": json.dumps(["13915383884", "52791640887"]),
    "volume": "50000.00",
    "volumeNum": 50000.0,
    "active": False,
    "closed": True,
    "createdAt": "2024-01-15T00:00:00.000000Z",
    "endDate": "2025-01-01T00:00:00Z",
    "closedTime": "2024-12-31 23:59:59+00",
    "category": "Geopolitics",
    "negRisk": False,
}

SAMPLE_YES_WIN_MARKET = {
    "id": "9999999",
    "conditionId": "0xbbb222",
    "slug": "will-gov-shutdown-oct",
    "question": "Will there be a government shutdown in October?",
    "outcomes": json.dumps(["Yes", "No"]),
    "outcomePrices": json.dumps(["1", "0"]),
    "clobTokenIds": json.dumps(["111111", "222222"]),
    "volume": "10000.00",
    "volumeNum": 10000.0,
    "active": False,
    "closed": True,
    "createdAt": "2024-08-01T00:00:00.000000Z",
    "endDate": "2024-11-01T00:00:00Z",
    "closedTime": "2024-10-15 12:00:00+00",
    "category": None,
    "negRisk": False,
}

def test_determine_resolution_no_wins():
    assert determine_resolution(["Yes", "No"], ["0", "1"]) == "No"

def test_determine_resolution_yes_wins():
    assert determine_resolution(["Yes", "No"], ["1", "0"]) == "Yes"

def test_determine_resolution_unresolved():
    assert determine_resolution(["Yes", "No"], ["0.5", "0.5"]) is None

def test_determine_resolution_near_one():
    assert determine_resolution(["Yes", "No"], ["0.001", "0.999"]) == "No"

def test_parse_market_no_resolution():
    result = parse_market(SAMPLE_GAMMA_MARKET)
    assert result["id"] == "0xa6d544beef271a4e941e55897ee14396c2c3b656a44aba63c8de5854e919eaa6"
    assert result["question"] == "Will Russia invade Finland by 2025?"
    assert result["resolution"] == "No"
    assert result["no_token_id"] == "52791640887"
    assert result["category"] == "geopolitical"
    assert result["source_url"] == "https://polymarket.com/event/will-russia-invade-finland-2025"
    assert isinstance(result["created_at"], datetime)

def test_parse_market_yes_resolution():
    result = parse_market(SAMPLE_YES_WIN_MARKET)
    assert result["resolution"] == "Yes"
    assert result["category"] == "political"
    assert result["no_token_id"] == "222222"

def test_parse_market_skips_neg_risk():
    market = {**SAMPLE_GAMMA_MARKET, "negRisk": True}
    assert parse_market(market) is None
