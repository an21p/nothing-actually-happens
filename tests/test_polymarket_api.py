import json
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from src.collector.polymarket_api import (
    parse_market,
    parse_open_market,
    determine_resolution,
    fetch_resolved_markets,
)

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

def test_determine_resolution_rejects_sub_threshold():
    """Only truly oracle-settled markets (price >= 0.999) count — not just high-prob live ones."""
    assert determine_resolution(["Yes", "No"], ["0.05", "0.95"]) is None
    assert determine_resolution(["Yes", "No"], ["0.01", "0.99"]) is None

def test_parse_market_no_resolution():
    result = parse_market(SAMPLE_GAMMA_MARKET)
    assert result["id"] == "0xa6d544beef271a4e941e55897ee14396c2c3b656a44aba63c8de5854e919eaa6"
    assert result["question"] == "Will Russia invade Finland by 2025?"
    assert result["resolution"] == "No"
    assert result["no_token_id"] == "52791640887"
    assert result["category"] == "geopolitical"
    assert result["source_url"] == "https://polymarket.com/market/will-russia-invade-finland-2025"
    assert isinstance(result["created_at"], datetime)

def test_parse_market_yes_resolution():
    result = parse_market(SAMPLE_YES_WIN_MARKET)
    assert result["resolution"] == "Yes"
    assert result["category"] == "political"
    assert result["no_token_id"] == "222222"

def test_parse_market_skips_unresolved():
    market = {
        **SAMPLE_GAMMA_MARKET,
        "outcomePrices": json.dumps(["0.5", "0.5"]),
    }
    assert parse_market(market) is None

def test_parse_market_skips_neg_risk():
    market = {**SAMPLE_GAMMA_MARKET, "negRisk": True}
    assert parse_market(market) is None

def test_parse_market_skips_non_yes_no_outcomes():
    market = {
        **SAMPLE_GAMMA_MARKET,
        "outcomes": json.dumps(["Team A", "Team B"]),
        "outcomePrices": json.dumps(["1", "0"]),
        "clobTokenIds": json.dumps(["111", "222"]),
    }
    assert parse_market(market) is None


def test_parse_market_populates_end_date():
    result = parse_market(SAMPLE_GAMMA_MARKET)
    assert result["end_date"] is not None
    assert result["end_date"] == datetime(2025, 1, 1, tzinfo=timezone.utc)


SAMPLE_OPEN_MARKET = {
    "id": "12345",
    "conditionId": "0xopen1",
    "slug": "will-live-event-happen",
    "question": "Will the live event happen by April 30, 2026?",
    "outcomes": json.dumps(["Yes", "No"]),
    "outcomePrices": json.dumps(["0.25", "0.75"]),
    "clobTokenIds": json.dumps(["aaa", "bbb"]),
    "active": True,
    "closed": False,
    "createdAt": "2026-04-10T00:00:00.000000Z",
    "endDate": "2026-04-30T00:00:00Z",
    "category": "Geopolitics",
    "negRisk": False,
}


def test_parse_open_market_accepts_unresolved():
    result = parse_open_market(SAMPLE_OPEN_MARKET)
    assert result is not None
    assert result["id"] == "0xopen1"
    assert result["resolution"] is None
    assert result["resolved_at"] is None
    assert result["no_token_id"] == "bbb"
    assert result["category"] == "geopolitical"
    assert result["end_date"] == datetime(2026, 4, 30, tzinfo=timezone.utc)
    assert result["source_url"] == "https://polymarket.com/market/will-live-event-happen"


def test_parse_open_market_rejects_neg_risk():
    market = {**SAMPLE_OPEN_MARKET, "negRisk": True}
    assert parse_open_market(market) is None


def test_parse_open_market_rejects_non_yes_no():
    market = {
        **SAMPLE_OPEN_MARKET,
        "outcomes": json.dumps(["Team A", "Team B"]),
    }
    assert parse_open_market(market) is None


def test_parse_open_market_handles_missing_end_date():
    market = {**SAMPLE_OPEN_MARKET}
    market.pop("endDate", None)
    result = parse_open_market(market)
    assert result is not None
    assert result["end_date"] is None


def _make_api_market(condition_id: str, question: str = "Test?") -> dict:
    return {
        "id": "999",
        "conditionId": condition_id,
        "slug": "test",
        "question": question,
        "outcomes": json.dumps(["Yes", "No"]),
        "outcomePrices": json.dumps(["0", "1"]),
        "clobTokenIds": json.dumps(["111", "222"]),
        "active": False,
        "closed": True,
        "createdAt": "2024-01-01T00:00:00.000000Z",
        "closedTime": "2024-06-01 00:00:00+00",
        "category": None,
        "negRisk": False,
    }


@patch("src.collector.polymarket_api.time.sleep")
@patch("src.collector.polymarket_api.httpx.Client")
def test_fetch_passes_end_date_max_to_api(mock_client_cls, mock_sleep):
    """end_date_max is forwarded as a query parameter to the API."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.side_effect = [[_make_api_market("id_a")], []]
    mock_response.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.get.return_value = mock_response
    mock_client_cls.return_value = mock_client

    results = fetch_resolved_markets(end_date_max="2026-04-03T00:00:00Z")

    call_params = mock_client.get.call_args_list[0][1]["params"]
    assert call_params["end_date_max"] == "2026-04-03T00:00:00Z"
    assert len(results) == 1


@patch("src.collector.polymarket_api.time.sleep")
@patch("src.collector.polymarket_api.httpx.Client")
def test_fetch_no_end_date_max_by_default(mock_client_cls, mock_sleep):
    """Without end_date_max, the parameter is not sent to the API."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.side_effect = [[_make_api_market("id_a")], []]
    mock_response.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.get.return_value = mock_response
    mock_client_cls.return_value = mock_client

    fetch_resolved_markets()

    call_params = mock_client.get.call_args_list[0][1]["params"]
    assert "end_date_max" not in call_params
